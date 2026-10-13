"""Whole-trace baseline estimates on real coordinates, with explicit refinement.

P-spline methods come from pybaselines. One iteration per call permits cooperative
cancellation without replacing its solvers or weighting formulas. Protected and
excluded observations are omitted from estimation, never removed from the trace.
"""

import hashlib
import json
import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
import pybaselines
import scipy
from numpy.typing import NDArray
from pybaselines import Baseline
from scipy.interpolate import PchipInterpolator

from chromakit.domain import TIME_SCALES, Trace, readonly_array

METHODS = {
    "arpls": "Adaptive spline · arPLS",
    "asls": "Peak-preserving spline · AsLS",
    "manual": "Manual anchors · PCHIP",
}
ALGORITHM_VERSION = "baseline-v1"


class BaselineProblem(ValueError):
    """Input or numerical conditions that need a user decision."""


class BaselineCancelled(Exception):
    """A superseded or cancelled preview."""


@dataclass(frozen=True)
class Anchor:
    time: float  # original display coordinates, units recorded in the result
    value: float  # absolute baseline height, never a correction offset


@dataclass(frozen=True)
class MaskRegion:
    start: float
    end: float
    kind: str = "Protected peak"


@dataclass(frozen=True)
class BaselineRecipe:
    method: str = "arpls"
    smoothness: float = 1000.0
    asymmetry: float = 0.001
    knots: int = 80
    polarity: str = "positive"
    max_iterations: int = 80
    tolerance: float = 0.001
    anchors: tuple[Anchor, ...] = ()
    regions: tuple[MaskRegion, ...] = ()


@dataclass(frozen=True)
class SegmentDiagnostic:
    first_sample: int
    last_sample: int
    fitted_samples: int
    iterations: int
    converged: bool
    final_tolerance: float | None
    effective_knots: int | None = None


@dataclass(frozen=True)
class BaselineResult:
    input_key: str
    recipe: BaselineRecipe
    baseline: NDArray[np.float64]
    corrected: NDArray[np.float64]
    segments: tuple[SegmentDiagnostic, ...]
    warnings: tuple[str, ...]
    created_at: str
    time_unit: str
    signal_unit: str
    software_versions: tuple[tuple[str, str], ...]
    source_hash: str
    algorithm_version: str = ALGORITHM_VERSION

    def metadata(self) -> dict:
        """Serializable recipe/provenance, ready for future project persistence."""
        return {
            "algorithm_version": self.algorithm_version,
            "input_key": self.input_key,
            "source_hash": self.source_hash,
            "recipe": asdict(self.recipe),
            "segments": [asdict(item) for item in self.segments],
            "warnings": self.warnings,
            "created_at": self.created_at,
            "time_unit": self.time_unit,
            "signal_unit": self.signal_unit,
            "software_versions": dict(self.software_versions),
        }


def input_key(trace: Trace) -> str:
    identity = json.dumps(
        [trace.source_hash, trace.import_settings, trace.time_unit, trace.signal_unit],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def validate_recipe(trace: Trace, recipe: BaselineRecipe, check_samples=True) -> None:
    x, y = trace.source_time, trace.signal
    if len(x) < 2 or x.shape != y.shape or x.ndim != 1:
        raise BaselineProblem("At least two matching time/signal samples are required.")
    if check_samples and (
        not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)) or np.any(np.diff(x) <= 0)
    ):
        raise BaselineProblem("Baseline correction requires finite, increasing time coordinates.")
    if len(trace.gap_after) != len(x) - 1:
        raise BaselineProblem("Sampling-gap metadata does not match this trace.")
    if recipe.method not in METHODS or recipe.polarity not in {"positive", "negative"}:
        raise BaselineProblem("Select a supported baseline method and peak polarity.")
    if not np.isfinite(recipe.smoothness) or not 0.001 <= recipe.smoothness <= 1e9:
        raise BaselineProblem("Spline smoothness must be between 0.001 and 1e9.")
    if not 0 < recipe.asymmetry < 0.5:
        raise BaselineProblem("AsLS peak weight must be greater than 0 and below 0.5.")
    if not 5 <= recipe.knots <= 300 or not 1 <= recipe.max_iterations <= 500:
        raise BaselineProblem("Use 5–300 knots and 1–500 iterations.")
    if not np.isfinite(recipe.tolerance) or not 1e-8 <= recipe.tolerance <= 0.1:
        raise BaselineProblem("Convergence tolerance must be between 1e-8 and 0.1.")
    seen = set()
    for anchor in recipe.anchors:
        if not np.isfinite(anchor.time) or not np.isfinite(anchor.value):
            raise BaselineProblem("Anchor times and heights must be finite numbers.")
        if not x[0] <= anchor.time <= x[-1]:
            raise BaselineProblem("Every anchor must be within the chromatogram's time range.")
        if anchor.time in seen:
            raise BaselineProblem("Two anchors cannot have the same time coordinate.")
        seen.add(anchor.time)
    for region in recipe.regions:
        if (
            not np.isfinite(region.start)
            or not np.isfinite(region.end)
            or not x[0] <= region.start < region.end <= x[-1]
        ):
            raise BaselineProblem(
                "Each protected/excluded region needs start < end within the trace."
            )
        if region.kind not in {"Protected peak", "Excluded artifact"}:
            raise BaselineProblem("Choose protected peak or excluded artifact for each region.")


def interpolate_with_constant_edges(x, knot_x, knot_y):
    """Shape-preserving interpolation; outer values are explicit constant extension."""
    clipped_x = np.clip(x, knot_x[0], knot_x[-1])
    if len(knot_x) == 1:
        return np.full_like(x, knot_y[0])
    return PchipInterpolator(knot_x, knot_y, extrapolate=False)(clipped_x)


def fit_spline(x, y, recipe, cancel, progress):
    if len(x) < 4:
        raise BaselineProblem(
            "Automatic fitting needs four unmasked samples per segment. Use anchors."
        )
    # Normalize coordinates and ordinates for conditioning, not resampling.
    span = x[-1] - x[0]
    offset = np.median(y)
    scale = np.max(np.abs(y - offset))
    if not np.isfinite(span) or not np.isfinite(scale) or span <= 0:
        raise BaselineProblem("Coordinate/signal range is too large for a stable baseline fit.")
    normalized_x = (x - x[0]) / span
    affine = np.interp(normalized_x, [0, 1], [y[0], y[-1]])
    affine_tolerance = 64 * np.finfo(float).eps * max(np.max(np.abs(y)), np.finfo(float).tiny)
    if np.allclose(y, affine, rtol=0, atol=affine_tolerance):
        return affine, 0, True, 0.0, ()
    polarity = 1 if recipe.polarity == "positive" else -1
    normalized_y = polarity * (y - offset) / scale
    solver = Baseline(normalized_x, assume_sorted=True)
    method = getattr(solver, f"pspline_{recipe.method}")
    weights = np.ones(len(x))
    captured_messages = []
    converged = False
    difference = None
    for iteration in range(recipe.max_iterations):
        if cancel():
            raise BaselineCancelled
        options = dict(
            lam=recipe.smoothness,
            num_knots=min(recipe.knots, max(5, len(x) // 2)),
            max_iter=0,
            tol=recipe.tolerance,
            weights=weights,
        )
        if recipe.method == "asls":
            options["p"] = recipe.asymmetry
        with warnings.catch_warnings(record=True) as messages:
            warnings.simplefilter("always")
            estimated, parameters = method(normalized_y, **options)
        captured_messages.extend(str(message.message) for message in messages)
        progress(iteration + 1, recipe.max_iterations)
        history = parameters["tol_history"]
        if not len(history):
            break
        difference = float(history[-1])
        if np.isfinite(difference) and difference < recipe.tolerance:
            converged = True
            break
        weights = parameters["weights"]
    return (
        offset + polarity * scale * estimated,
        iteration + 1,
        converged,
        difference,
        tuple(dict.fromkeys(captured_messages)),
    )


def estimate_baseline(
    trace: Trace,
    recipe: BaselineRecipe,
    cancel: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int], None] = lambda current, total: None,
) -> BaselineResult:
    """Estimate each contiguous segment and refine with absolute baseline anchors."""
    if cancel():
        raise BaselineCancelled
    validate_recipe(trace, recipe)
    # Seconds internally; recipe coordinates retain the original displayed units.
    scale = TIME_SCALES[trace.time_unit]
    x = trace.time
    mask = np.zeros(len(x), dtype=bool)
    for region in recipe.regions:
        mask |= (trace.source_time >= region.start) & (trace.source_time <= region.end)
    anchors = sorted(recipe.anchors, key=lambda item: item.time)
    boundaries = np.r_[0, np.flatnonzero(trace.gap_after) + 1, len(x)]
    baseline = np.empty_like(trace.signal)
    diagnostics = []
    notices = []
    used_anchors = 0
    if len(boundaries) > 2:
        notices.append(
            "Sampling gaps are fitted independently; no baseline is bridged across them."
        )
    if np.count_nonzero(mask) > len(mask) / 2:
        notices.append("More than half the samples are masked; inspect interpolation carefully.")
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        if cancel():
            raise BaselineCancelled
        sx, sy = x[start:stop], trace.signal[start:stop]
        segment_anchors = [
            anchor
            for anchor in anchors
            if trace.source_time[start] <= anchor.time <= trace.source_time[stop - 1]
        ]
        used_anchors += len(segment_anchors)
        ax = np.array([anchor.time * scale for anchor in segment_anchors])
        ay = np.array([anchor.value for anchor in segment_anchors])
        supported = ~mask[start:stop]
        if recipe.method == "manual":
            required = 1 if len(sx) == 1 else 2
            if len(segment_anchors) < required:
                raise BaselineProblem(
                    f"Manual baseline needs {required} anchors in segment "
                    f"{len(diagnostics) + 1}. Add anchors near its edges."
                )
            estimate = interpolate_with_constant_edges(sx, ax, ay)
            iterations, converged, difference = 0, True, None
            if ax[0] > sx[0] or ax[-1] < sx[-1]:
                notices.append("Manual baseline uses constant extension beyond its outer anchors.")
            if recipe.regions:
                notices.append("Masks do not affect a baseline defined entirely by manual anchors.")
        else:
            fx, fy = sx[supported], sy[supported]
            estimate, iterations, converged, difference, messages = fit_spline(
                fx,
                fy,
                recipe,
                cancel,
                progress,
            )
            notices.extend(messages)
            estimate = interpolate_with_constant_edges(sx, fx, estimate)
            if fx[0] > sx[0] or fx[-1] < sx[-1]:
                notices.append("Masked segment edges use constant extension from fitted support.")
            if len(ax):
                # Zero correction at segment edges localizes refinements. Additional
                # anchors can delimit a smaller neighborhood explicitly.
                correction = ay - np.interp(ax, sx, estimate)
                cx, cy = list(ax), list(correction)
                if ax[0] > sx[0]:
                    cx.insert(0, sx[0])
                    cy.insert(0, 0.0)
                if ax[-1] < sx[-1]:
                    cx.append(sx[-1])
                    cy.append(0.0)
                estimate += interpolate_with_constant_edges(sx, np.array(cx), np.array(cy))
            if not converged:
                notices.append(
                    f"Segment {len(diagnostics) + 1} did not converge. "
                    "Review settings, protected regions, or use manual anchors."
                )
        baseline[start:stop] = estimate
        diagnostics.append(
            SegmentDiagnostic(
                int(start),
                int(stop - 1),
                len(ax) if recipe.method == "manual" else int(np.count_nonzero(supported)),
                iterations,
                converged,
                difference,
                min(recipe.knots, max(5, int(np.count_nonzero(supported)) // 2))
                if recipe.method != "manual" and iterations
                else None,
            )
        )
    if used_anchors != len(anchors):
        raise BaselineProblem(
            "An anchor lies inside a sampling gap. Move it onto a sampled segment."
        )
    if cancel():
        raise BaselineCancelled
    corrected = trace.signal - baseline
    if not np.all(np.isfinite(baseline)) or not np.all(np.isfinite(corrected)):
        raise BaselineProblem(
            "The estimate is not finite. Reduce parameter extremes or review anchors."
        )
    if any(
        item.final_tolerance is not None and not np.isfinite(item.final_tolerance)
        for item in diagnostics
    ):
        notices.append("A convergence metric was nonfinite; the estimate needs review.")
    return BaselineResult(
        input_key(trace),
        recipe,
        readonly_array(baseline),
        readonly_array(corrected),
        tuple(diagnostics),
        tuple(dict.fromkeys(notices)),
        datetime.now(UTC).isoformat(),
        trace.time_unit,
        trace.signal_unit,
        (
            ("pybaselines", pybaselines.__version__),
            ("numpy", np.__version__),
            ("scipy", scipy.__version__),
        ),
        trace.source_hash,
    )
