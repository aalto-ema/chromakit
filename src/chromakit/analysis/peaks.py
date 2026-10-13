"""Detection and signed integration of an applied baseline-corrected trace."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

import numpy as np
import scipy
from scipy.integrate import trapezoid
from scipy.ndimage import median_filter
from scipy.signal import find_peaks, peak_prominences, peak_widths

from chromakit.analysis.baseline import BaselineResult, input_key
from chromakit.domain import Trace

VERSION = "peaks-v1"


class PeakProblem(ValueError):
    """An actionable detection/integration validation error."""


class PeakCancelled(Exception):
    """Superseded work."""


@dataclass(frozen=True)
class PeakRecipe:
    polarity: str = "positive"
    noise_multiplier: float = 6.0
    minimum_prominence: float = 0.0  # zero selects noise-based threshold
    minimum_height: float = 0.0
    minimum_width: float = 0.0  # half-prominence width, displayed time units
    minimum_separation: float = 0.0  # actual time, not sample count
    boundary_fraction: float = 0.005


@dataclass(frozen=True)
class Peak:
    id: str
    apex_index: int
    retention_time: float
    height: float  # signed corrected signal height
    area: float  # signed trapezoidal integral, signal × displayed time unit
    start: float
    end: float
    polarity: str
    prominence: float
    width: float
    noise: float
    segment_start: int
    segment_end: int
    manually_edited: bool = False
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class PeakResult:
    input_key: str
    baseline_key: str
    recipe: PeakRecipe
    peaks: tuple[Peak, ...]
    warnings: tuple[str, ...]
    time_unit: str
    signal_unit: str
    created_at: str
    source_hash: str
    scipy_version: str = scipy.__version__
    algorithm_version: str = VERSION

    @property
    def area_unit(self):
        return f"{self.signal_unit} × {self.time_unit}"

    def metadata(self):
        return {
            "input_key": self.input_key,
            "source_hash": self.source_hash,
            "baseline_key": self.baseline_key,
            "recipe": asdict(self.recipe),
            "peaks": [asdict(peak) for peak in self.peaks],
            "warnings": self.warnings,
            "time_unit": self.time_unit,
            "signal_unit": self.signal_unit,
            "area_unit": self.area_unit,
            "created_at": self.created_at,
            "algorithm_version": self.algorithm_version,
            "scipy_version": self.scipy_version,
        }


def baseline_key(baseline: BaselineResult) -> str:
    digest = hashlib.sha256(
        json.dumps(
            [
                baseline.input_key,
                asdict(baseline.recipe),
                baseline.algorithm_version,
                baseline.software_versions,
            ],
            sort_keys=True,
            allow_nan=False,
        ).encode()
    )
    digest.update(baseline.corrected.tobytes())
    return digest.hexdigest()


def check_cancel(cancel):
    if cancel():
        raise PeakCancelled


def valid_segments(trace, baseline):
    if baseline.input_key != input_key(trace) or baseline.corrected.shape != trace.signal.shape:
        raise PeakProblem("This baseline belongs to a different trace or import mapping.")
    x, y = trace.source_time, baseline.corrected
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(x)) or np.any(np.diff(x) <= 0):
        raise PeakProblem("Peak analysis requires finite samples and increasing time coordinates.")
    eligible = np.ones(len(x), dtype=bool)
    for region in baseline.recipe.regions:
        if region.kind == "Excluded artifact":
            eligible &= ~((x >= region.start) & (x <= region.end))
    edges = np.ones(len(x) + 1, dtype=bool)
    edges[1:-1] = trace.gap_after | ~eligible[:-1] | ~eligible[1:]
    cuts = np.flatnonzero(edges)
    return [
        (int(a), int(b - 1))
        for a, b in zip(cuts[:-1], cuts[1:], strict=True)
        if eligible[a] and b - a >= 2
    ]


def validate_recipe(recipe):
    if recipe.polarity not in {"positive", "negative", "both"}:
        raise PeakProblem("Select positive, negative, or both peak directions.")
    for value in (
        recipe.noise_multiplier,
        recipe.minimum_prominence,
        recipe.minimum_height,
        recipe.minimum_width,
        recipe.minimum_separation,
        recipe.boundary_fraction,
    ):
        if not np.isfinite(value) or value < 0:
            raise PeakProblem("Detection settings must be finite and nonnegative.")
    if recipe.noise_multiplier < 1 or not 0 < recipe.boundary_fraction < 0.5:
        raise PeakProblem("Use a noise multiplier ≥ 1 and a boundary fraction between 0 and 0.5.")


def noise_estimate(y):
    differences = np.diff(y)
    white = np.median(np.abs(differences - np.median(differences))) / (0.67448975 * np.sqrt(2))
    window = min(51, len(y) if len(y) % 2 else len(y) - 1)
    residual = y - median_filter(y, size=max(3, window), mode="nearest")
    correlated = np.median(np.abs(residual - np.median(residual))) / 0.67448975
    return float(max(white, correlated))


def integrated_area(x, y, start, end):
    """Exact trapezoidal integration of the piecewise linear sampled signal.

    Interpolated endpoint heights permit boundaries between observations. No
    straight-line rebaseline, clipping, smoothing or rectangular approximation.
    """
    first = np.searchsorted(x, start, side="right")
    last = np.searchsorted(x, end, side="left")
    times = np.r_[start, x[first:last], end]
    heights = np.r_[np.interp(start, x, y), y[first:last], np.interp(end, x, y)]
    area = float(trapezoid(heights, times))
    if not np.isfinite(area):
        raise PeakProblem("Integrated area exceeds the supported numerical range.")
    return area


def threshold_boundary(x, z, apex, limit, threshold):
    """Find the nearest return to a small positive level within a partition."""
    if limit < apex:
        below = np.flatnonzero(z[limit : apex + 1] <= threshold)
        if len(below):
            outer = limit + int(below[-1])
            inner = min(outer + 1, apex)
        else:
            return float(x[limit]), True
    else:
        below = np.flatnonzero(z[apex : limit + 1] <= threshold)
        if len(below):
            outer = apex + int(below[0])
            inner = max(outer - 1, apex)
        else:
            return float(x[limit]), True
    if z[inner] == z[outer]:
        return float(x[outer]), False
    fraction = (threshold - z[outer]) / (z[inner] - z[outer])
    return float(x[outer] + fraction * (x[inner] - x[outer])), False


def detect_peaks(
    trace: Trace,
    baseline: BaselineResult,
    recipe: PeakRecipe,
    cancel: Callable[[], bool] = lambda: False,
) -> PeakResult:
    check_cancel(cancel)
    validate_recipe(recipe)
    segments = valid_segments(trace, baseline)
    peaks = []
    notices = list(baseline.warnings)
    directions = (
        (1, -1) if recipe.polarity == "both" else (1 if recipe.polarity == "positive" else -1,)
    )
    for first, last in segments:
        check_cancel(cancel)
        x, y = trace.source_time[first : last + 1], baseline.corrected[first : last + 1]
        if len(x) < 3:
            continue
        noise = noise_estimate(y)
        if not np.isfinite(noise):
            raise PeakProblem("Signal range is too large for a finite noise estimate.")
        numerical_floor = (
            np.finfo(float).eps * max(float(np.max(np.abs(y))), np.finfo(float).tiny) * 32
        )
        prominence = recipe.minimum_prominence or max(
            noise * recipe.noise_multiplier, numerical_floor
        )
        candidates = []
        sample_indices = np.arange(len(x))
        for sign in directions:
            check_cancel(cancel)
            z = sign * y
            indices, _ = find_peaks(z, height=max(recipe.minimum_height, numerical_floor))
            # Keep global prominence semantics, but bound individual library calls
            # so cancellation can be observed on long/densely peaked traces.
            for offset in range(0, len(indices), 128):
                check_cancel(cancel)
                chunk = indices[offset : offset + 128]
                prominences, left_bases, right_bases = peak_prominences(z, chunk)
                keep = prominences >= prominence
                chunk = chunk[keep]
                if not len(chunk):
                    continue
                data = (prominences[keep], left_bases[keep], right_bases[keep])
                _, _, left_ips, right_ips = peak_widths(z, chunk, prominence_data=data)
                for j, index in enumerate(chunk):
                    width = float(
                        np.interp(right_ips[j], sample_indices, x)
                        - np.interp(left_ips[j], sample_indices, x)
                    )
                    if width >= recipe.minimum_width:
                        candidates.append((int(index), sign, float(data[0][j]), width))
        accepted = []
        for candidate in sorted(candidates, key=lambda item: item[2], reverse=True):
            check_cancel(cancel)
            if all(
                abs(x[candidate[0]] - x[item[0]]) >= recipe.minimum_separation for item in accepted
            ):
                accepted.append(candidate)
            if len(peaks) + len(accepted) > 2000:
                raise PeakProblem(
                    "More than 2,000 peaks found. Increase prominence or minimum separation."
                )
        accepted.sort(key=lambda item: item[0])
        divisions = [0]
        for a, b in zip(accepted[:-1], accepted[1:], strict=True):
            # Same polarity splits at a valley; opposite signs split nearest zero.
            section = y[a[0] : b[0] + 1]
            valley = np.argmin(a[1] * section) if a[1] == b[1] else np.argmin(np.abs(section))
            divisions.append(a[0] + int(valley))
        divisions.append(len(x) - 1)
        for j, (index, sign, prominence, width) in enumerate(accepted):
            check_cancel(cancel)
            level = max(noise * 2, abs(y[index]) * recipe.boundary_fraction)
            start, left_cut = threshold_boundary(x, sign * y, index, divisions[j], level)
            end, right_cut = threshold_boundary(x, sign * y, index, divisions[j + 1], level)
            if not start < x[index] < end:
                continue
            flags = []
            if left_cut or right_cut:
                flags.append(
                    "Boundary at valley/segment edge; tail may be truncated or overlapping"
                )
            if start == x[0] or end == x[-1]:
                flags.append(
                    "Touches segment edge; inspect acquisition gaps, artifacts, or truncation"
                )
            peak = Peak(
                f"P{len(peaks) + 1}",
                first + index,
                float(x[index]),
                float(y[index]),
                integrated_area(x, y, start, end),
                start,
                end,
                "positive" if sign == 1 else "negative",
                prominence,
                width,
                noise,
                first,
                last,
                flags=tuple(flags),
            )
            peaks.append(peak)
    if "unknown" in {trace.time_unit, trace.signal_unit}:
        notices.append(
            "Unknown units: areas are numerical coordinate integrals, not physical quantities."
        )
    if any(not segment.converged for segment in baseline.segments):
        notices.append(
            "The applied baseline did not fully converge; peak measurements need review."
        )
    if not peaks:
        notices.append(
            "No peaks met these settings. Lower the prominence or review polarity/baseline."
        )
    notices.append("Valley-split areas are measured integrals, not deconvolved component areas.")
    check_cancel(cancel)
    return PeakResult(
        input_key(trace),
        baseline_key(baseline),
        recipe,
        tuple(peaks),
        tuple(dict.fromkeys(notices)),
        trace.time_unit,
        trace.signal_unit,
        datetime.now(UTC).isoformat(),
        trace.source_hash,
    )


def edit_boundaries(trace, baseline, result, peak_id, start, end, cancel=lambda: False):
    check_cancel(cancel)
    if result.baseline_key != baseline_key(baseline) or result.input_key != input_key(trace):
        raise PeakProblem("Peak results are stale. Detect peaks again using the applied baseline.")
    peak = next((item for item in result.peaks if item.id == peak_id), None)
    if peak is None:
        raise PeakProblem("The selected peak no longer exists.")
    if not np.isfinite(start) or not np.isfinite(end) or not start < peak.retention_time < end:
        raise PeakProblem("Start < retention time < end is required; retain this peak's apex.")
    x = trace.source_time[peak.segment_start : peak.segment_end + 1]
    y = baseline.corrected[peak.segment_start : peak.segment_end + 1]
    if start < x[0] or end > x[-1]:
        raise PeakProblem("Boundaries cannot cross an acquisition gap or excluded artifact.")
    if any(
        other.id != peak.id and start < other.end and end > other.start for other in result.peaks
    ):
        raise PeakProblem("Boundaries overlap another peak. Adjust that peak first or remove it.")
    updated = replace(
        peak,
        start=float(start),
        end=float(end),
        area=integrated_area(x, y, start, end),
        manually_edited=True,
        flags=("Manually edited boundaries; apex retained",),
    )
    check_cancel(cancel)
    return replace(
        result,
        peaks=tuple(updated if item.id == peak.id else item for item in result.peaks),
        created_at=datetime.now(UTC).isoformat(),
    )
