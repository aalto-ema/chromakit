"""Constrained, signed component fits to unchanged, applied corrected observations."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from time import monotonic

import numpy as np
import scipy
from scipy.integrate import trapezoid
from scipy.optimize import least_squares, minimize_scalar
from scipy.signal import find_peaks
from scipy.stats import exponnorm, norm

from chromakit.analysis.baseline import BaselineResult
from chromakit.analysis.peaks import PeakCancelled, PeakProblem, baseline_key, valid_segments
from chromakit.domain import Trace, readonly_array


class FitProblem(PeakProblem):
    """Invalid fitting data or constraints."""


class FitCancelled(PeakCancelled):
    """Cancelled numerical work."""


@dataclass(frozen=True)
class Parameter:
    value: float
    lower: float
    upper: float
    locked: bool = False


@dataclass(frozen=True)
class Component:
    id: str
    model: str  # Gaussian, Right tail, Left tail
    area: Parameter  # signed full-distribution area, signal × displayed time
    center: Parameter  # Gaussian location, not EMG apex
    sigma: Parameter
    tau: Parameter


@dataclass(frozen=True)
class FitRecipe:
    start: float
    end: float
    components: tuple[Component, ...]
    loss: str = "linear"
    starts: int = 3
    seed: int = 1729
    max_nfev: int = 1500


@dataclass(frozen=True)
class FittedPeak:
    id: str
    model: str
    retention_time: float
    height: float
    area: float
    window_area: float
    area_se: float | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class FitResult:
    recipe: FitRecipe
    fitted: tuple[Component, ...]
    peaks: tuple[FittedPeak, ...]
    x: np.ndarray
    observed: np.ndarray
    curves: tuple[np.ndarray, ...]
    total: np.ndarray
    residual: np.ndarray
    baseline_key: str
    source_hash: str
    time_unit: str
    signal_unit: str
    converged: bool
    message: str
    rmse: float
    r_squared: float | None
    aicc: float | None
    bic: float | None
    free_parameters: int
    evaluations: int
    condition: float | None
    objective_cost: float
    noise_scale: float
    warnings: tuple[str, ...]
    created_at: str
    numpy_version: str = np.__version__
    scipy_version: str = scipy.__version__
    algorithm_version: str = "deconvolution-v1"

    def metadata(self):
        return {
            key: asdict(value)
            if key == "recipe"
            else [asdict(item) for item in value]
            if key in {"fitted", "peaks"}
            else value
            for key, value in ((field.name, getattr(self, field.name)) for field in fields(self))
            if key not in {"x", "observed", "curves", "total", "residual"}
        }


def density(x: np.ndarray | float, component: Component):
    mu, sigma, tau = component.center.value, component.sigma.value, component.tau.value
    if component.model == "Gaussian":
        return norm.pdf(x, loc=mu, scale=sigma)
    if component.model == "Right tail":
        return exponnorm.pdf(x, tau / sigma, loc=mu, scale=sigma)
    if component.model == "Left tail":
        return exponnorm.pdf(-np.asarray(x), tau / sigma, loc=-mu, scale=sigma)
    raise FitProblem("Choose Gaussian, Right tail, or Left tail for each component.")


def curves(x: np.ndarray, components: tuple[Component, ...]) -> tuple[np.ndarray, ...]:
    return tuple(component.area.value * density(x, component) for component in components)


def window_data(trace: Trace, baseline: BaselineResult, start: float, end: float):
    if not np.isfinite([start, end]).all() or start >= end:
        raise FitProblem("Fit start must be earlier than fit end.")
    segments = valid_segments(trace, baseline)
    x = trace.display_time
    if not any(x[a] <= start < end <= x[b] for a, b in segments):
        raise FitProblem(
            "Choose a window inside one continuous segment, without gaps or excluded artifacts."
        )
    chosen = (x >= start) & (x <= end)
    if chosen.sum() < 12:
        raise FitProblem("Choose a wider window with at least 12 observations.")
    if chosen.sum() > 20000:
        raise FitProblem("Narrow the fit window to at most 20,000 observations.")
    return x[chosen], baseline.corrected[chosen]


def initialize(
    trace: Trace,
    baseline: BaselineResult,
    start: float,
    end: float,
    count: int = 3,
    model: str = "Right tail",
    negative: bool = False,
) -> FitRecipe:
    """Local maxima plus distributed starts for unresolved shoulders; guesses, not identities."""
    x, observed = window_data(trace, baseline, start, end)
    if not 1 <= count <= 8:
        raise FitProblem("Choose between 1 and 8 components.")
    y = -observed if negative else observed
    span = end - start
    scale = float(np.max(np.abs(observed)))
    if scale <= np.finfo(float).eps:
        raise FitProblem("This window has no measurable signal to fit.")
    peaks, _ = find_peaks(y, prominence=scale * 0.03, distance=max(1, len(x) // (count * 4)))
    selected = list(x[sorted(peaks, key=lambda i: y[i], reverse=True)[:count]])
    # Broad unresolved humps need additional starting centers even with only one maximum.
    mass = np.maximum(y, 0)
    if not np.any(mass > scale * 1e-10):
        raise FitProblem(
            "No signal in the chosen direction; change positive/negative starting peaks."
        )
    weights = (mass[:-1] + mass[1:]) / 2 * np.diff(x)
    cumulative = np.r_[0, np.cumsum(weights)]
    candidates = np.interp(
        np.linspace(0.12, 0.88, count * 3), cumulative / max(cumulative[-1], 1e-300), x
    )
    while len(selected) < count:
        candidate = max(
            candidates, key=lambda v: min(abs(v - p) for p in selected) if selected else 1
        )
        selected.append(float(candidate))
        candidates = candidates[candidates != candidate]
    area = max(float(trapezoid(mass, x)), scale * span * 0.02) / count
    sign = -1 if negative else 1
    area_bounds = (-scale * span * 20, 0) if negative else (0, scale * span * 20)
    minimum = max(float(np.min(np.diff(x))) * 0.2, span * 1e-5)
    return FitRecipe(
        start,
        end,
        tuple(
            Component(
                f"C{i + 1}",
                model,
                Parameter(sign * area, *area_bounds),
                Parameter(
                    float(
                        np.clip(
                            center - (span / count / 10 if model == "Right tail" else 0), start, end
                        )
                    ),
                    start,
                    end,
                ),
                Parameter(span / count / 7, minimum, span / 2),
                Parameter(span / count / 6, minimum, span),
            )
            for i, center in enumerate(sorted(selected))
        ),
    )


def validate(recipe: FitRecipe) -> None:
    if not 1 <= len(recipe.components) <= 8 or len({c.id for c in recipe.components}) != len(
        recipe.components
    ):
        raise FitProblem("Use 1–8 components with distinct IDs.")
    if (
        recipe.loss not in {"linear", "soft_l1"}
        or not 1 <= recipe.starts <= 8
        or recipe.max_nfev < 1
    ):
        raise FitProblem("Invalid optimizer settings.")
    for component in recipe.components:
        if component.model not in {"Gaussian", "Right tail", "Left tail"}:
            raise FitProblem("Unknown component shape.")
        for name in ("area", "center", "sigma", "tau"):
            p = getattr(component, name)
            if (
                not np.isfinite([p.value, p.lower, p.upper]).all()
                or not p.lower <= p.value <= p.upper
            ):
                raise FitProblem(f"{component.id} {name}: value must lie inside finite bounds.")
            if not p.locked and p.lower >= p.upper:
                raise FitProblem(
                    f"{component.id} {name}: lower bound must be below upper bound, or lock it."
                )
            if name in {"sigma", "tau"} and p.lower <= 0:
                raise FitProblem(f"{component.id} {name} must stay strictly positive.")
        if component.area.lower < 0 < component.area.upper:
            raise FitProblem(
                "Area bounds must stay positive or negative; "
                "choose the component direction explicitly."
            )


def fit(
    trace: Trace,
    baseline: BaselineResult,
    recipe: FitRecipe,
    cancel: Callable[[], bool] = lambda: False,
    update: Callable | None = None,
) -> FitResult:
    validate(recipe)
    x, y = window_data(trace, baseline, recipe.start, recipe.end)
    span, scale = recipe.end - recipe.start, float(np.max(np.abs(y)))
    if scale <= np.finfo(float).eps:
        raise FitProblem("This window has no measurable signal to fit.")
    variables = []
    for i, component in enumerate(recipe.components):
        for name in ("area", "center", "sigma", "tau"):
            if name == "tau" and component.model == "Gaussian":
                continue
            p = getattr(component, name)
            if not p.locked:
                factor = scale * span if name == "area" else span
                offset = recipe.start if name == "center" else 0
                variables.append((i, name, factor, offset, p))
    count = len(variables)
    if len(x) <= count + 2:
        raise FitProblem(
            "Too few observations for this many free parameters; "
            "widen the window or lock parameters."
        )

    def unpack(values):
        components = list(recipe.components)
        for value, (i, name, factor, offset, p) in zip(values, variables, strict=True):
            components[i] = replace(
                components[i], **{name: replace(p, value=float(value * factor + offset))}
            )
        return tuple(components)

    last_update = 0.0

    def objective(values):
        nonlocal last_update
        if cancel():
            raise FitCancelled()
        component_curves = curves(x, unpack(values))
        if update is not None and monotonic() - last_update > 0.15:
            update(
                (
                    readonly_array(x),
                    tuple(readonly_array(c) for c in component_curves),
                    readonly_array(y),
                )
            )
            last_update = monotonic()
        return (sum(component_curves, np.zeros_like(x)) - y) / scale

    initial = np.array([(p.value - o) / f for _, _, f, o, p in variables])
    lower = np.array([(p.lower - o) / f for _, _, f, o, p in variables])
    upper = np.array([(p.upper - o) / f for _, _, f, o, p in variables])
    noise = max(float(np.median(np.abs(np.diff(y) - np.median(np.diff(y))))) / 0.954 / scale, 1e-5)
    rng = np.random.default_rng(recipe.seed)
    solutions = []
    evaluations = 0
    if count:
        for attempt in range(recipe.starts):
            guess = initial.copy()
            if attempt:
                guess += rng.normal(0, 0.15, count) * np.maximum(np.abs(initial), 0.03)
            guess = np.clip(guess, lower + (upper - lower) * 1e-10, upper - (upper - lower) * 1e-10)
            solution = least_squares(
                objective,
                guess,
                bounds=(lower, upper),
                method="trf",
                x_scale="jac",
                loss=recipe.loss,
                f_scale=noise,
                max_nfev=recipe.max_nfev,
                ftol=1e-9,
                xtol=1e-9,
                gtol=1e-9,
            )
            evaluations += solution.nfev
            solutions.append(solution)
        best = min(solutions, key=lambda result: result.cost)
        fitted = unpack(best.x)
        converged, message = bool(best.success), best.message
    else:
        objective(initial)  # validation/cancellation also applies to fully locked previews
        fitted = recipe.components
        best = None
        converged, message = True, "All parameters locked; evaluated without optimization."
    component_curves = curves(x, fitted)
    total = sum(component_curves, np.zeros_like(x))
    residual = y - total
    sse = float(residual @ residual)
    rmse = float(np.sqrt(sse / len(x)))
    variance = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1 - sse / variance if variance > 0 else None
    k = count + 1  # estimated residual variance is an additional likelihood parameter
    likelihood = len(x) * np.log(max(sse / len(x), np.finfo(float).tiny))
    aicc = (
        float(likelihood + 2 * k + 2 * k * (k + 1) / (len(x) - k - 1))
        if recipe.loss == "linear"
        else None
    )
    bic = float(likelihood + k * np.log(len(x))) if recipe.loss == "linear" else None
    warnings = [
        "Components are mathematical fits, not identified compounds; compare counts and shapes."
    ]
    if trace.time_unit == "unknown":
        warnings.append("Time unit is unknown; areas are numerical coordinate integrals.")
    if any(not segment.converged for segment in baseline.segments):
        warnings.append(
            "Applied baseline did not converge; review baseline before using fitted areas."
        )
    if not converged:
        warnings.append("Optimizer did not converge; fitted areas require review.")
    condition, covariance = None, None
    if best is not None:
        _u, singular, vectors = np.linalg.svd(best.jac, full_matrices=False)
        condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else None
        if condition is None or condition > 1e6:
            warnings.append("Components are poorly resolved: parameter covariance is unreliable.")
        elif recipe.loss == "linear" and not np.any(best.active_mask) and converged:
            covariance = ((vectors.T / singular**2) @ vectors) * (sse / scale**2 / (len(x) - count))
            diagonal = np.sqrt(np.maximum(np.diag(covariance), 0))
            correlation = covariance / np.maximum(np.outer(diagonal, diagonal), 1e-300)
            np.fill_diagonal(correlation, 0)
            if np.max(np.abs(correlation)) > 0.98:
                warnings.append("Strongly correlated parameters: component areas may be nonunique.")
        if np.any(best.active_mask):
            warnings.append("One or more parameters reached a constraint; review bounds.")
        for other in solutions:
            if other is best or other.cost > best.cost * 1.05 + 1e-10:
                continue
            a = sorted(c.area.value for c in unpack(other.x))
            b = sorted(c.area.value for c in fitted)
            if np.max(np.abs(np.array(a) - b)) > max(np.max(np.abs(b)) * 0.15, 1e-12):
                warnings.append(
                    "Similar fits from different starts give different areas; "
                    "decomposition is ambiguous."
                )
                break
    if recipe.loss != "linear":
        warnings.append("Robust loss: AICc/BIC and covariance errors are unavailable.")
    peaks = []
    for i, component in enumerate(fitted):
        mu, sigma, tau = component.center.value, component.sigma.value, component.tau.value
        mode = (
            mu
            if component.model == "Gaussian"
            else float(
                minimize_scalar(
                    lambda t, component=component: -float(density(t, component)),
                    bounds=(mu - 8 * sigma - 8 * tau, mu + 8 * sigma + 8 * tau),
                    method="bounded",
                    options={"xatol": span * 1e-10},
                ).x
            )
        )
        if component.model == "Gaussian":
            fraction = norm.cdf(recipe.end, mu, sigma) - norm.cdf(recipe.start, mu, sigma)
        else:
            left = component.model == "Left tail"
            lo, hi = (-recipe.end, -recipe.start) if left else (recipe.start, recipe.end)
            fraction = exponnorm.cdf(
                hi, tau / sigma, loc=-mu if left else mu, scale=sigma
            ) - exponnorm.cdf(lo, tau / sigma, loc=-mu if left else mu, scale=sigma)
        flags = []
        if fraction < 0.98:
            flags.append("Area extrapolates beyond window")
        area_se = None
        if covariance is not None:
            j = next(
                (j for j, (ci, name, *_rest) in enumerate(variables) if ci == i and name == "area"),
                None,
            )
            if j is not None:
                area_se = float(np.sqrt(max(covariance[j, j], 0)) * scale * span)
        if best is not None and any(
            best.active_mask[j] for j, (ci, *_rest) in enumerate(variables) if ci == i
        ):
            flags.append("Constraint reached")
        peaks.append(
            FittedPeak(
                component.id,
                component.model,
                mode,
                float(component.area.value * density(mode, component)),
                component.area.value,
                float(component.area.value * fraction),
                area_se,
                tuple(flags),
            )
        )
    return FitResult(
        recipe,
        fitted,
        tuple(peaks),
        readonly_array(x),
        readonly_array(y),
        tuple(readonly_array(c) for c in component_curves),
        readonly_array(total),
        readonly_array(residual),
        baseline_key(baseline),
        trace.source_hash,
        trace.time_unit,
        trace.signal_unit,
        converged,
        str(message),
        rmse,
        r_squared,
        aicc,
        bic,
        count,
        evaluations,
        condition,
        float(best.cost * scale**2) if best is not None else sse / 2,
        noise * scale,
        tuple(warnings),
        datetime.now(UTC).isoformat(),
    )
