"""External-standard weighted linear calibration with explicit units and exclusions."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np

from chromakit.importers.text import ImportProblem


@dataclass(frozen=True)
class CalibrationPoint:
    id: str
    trace_id: str
    peak_id: str
    origin: str
    result_key: str
    concentration: float
    response: float
    concentration_unit: str
    response_unit: str
    excluded: bool = False
    reason: str = ""
    sample: str = ""


@dataclass(frozen=True)
class CalibrationRecipe:
    weighting: str = "none"
    fit_intercept: bool = True


@dataclass(frozen=True)
class CalibrationResult:
    slope: float
    intercept: float
    r_squared: float | None
    rmse: float
    slope_se: float | None
    intercept_se: float | None
    minimum: float
    maximum: float
    concentration_unit: str
    response_unit: str
    recipe: CalibrationRecipe
    points: tuple[CalibrationPoint, ...]
    diagnostics: tuple[dict, ...]
    warnings: tuple[str, ...]
    created_at: str
    input_key: str
    algorithm_version: str = "external-linear-v1"


def calibration_key(points, recipe):
    return hashlib.sha256(
        json.dumps(
            {"points": [asdict(p) for p in points], "recipe": asdict(recipe)},
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def fit_calibration(points, recipe=None):
    recipe = recipe or CalibrationRecipe()
    if len(points) > 10000 or len({p.id for p in points}) != len(points):
        raise ImportProblem("Use at most 10,000 individually identified standards.")
    if any(not np.isfinite([p.concentration, p.response]).all() for p in points):
        raise ImportProblem("All standard records must contain finite observations.")
    if recipe.weighting not in {"none", "1/x", "1/x²"}:
        raise ImportProblem("Choose unweighted, 1/x or 1/x² calibration.")
    if any(p.excluded and not p.reason.strip() for p in points):
        raise ImportProblem("Excluded standards require a reason.")
    included = [p for p in points if not p.excluded]
    if len(included) < 2 or len({p.concentration for p in included}) < 2:
        raise ImportProblem("Include at least two distinct concentration levels.")
    if len({p.origin for p in included}) != 1:
        raise ImportProblem("Use the same measured/fitted response definition across standards.")
    units = {(p.concentration_unit, p.response_unit) for p in included}
    if len(units) != 1 or any(
        not v.strip() or v.strip().casefold() in {"unknown", "unspecified"}
        for v in next(iter(units))
    ):
        raise ImportProblem(
            "Standards require consistent, explicit concentration and response units."
        )
    x = np.array([p.concentration for p in included], dtype=float)
    y = np.array([p.response for p in included], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(x < 0):
        raise ImportProblem("Use finite responses and nonnegative standard concentrations.")
    if recipe.weighting != "none" and np.any(x <= 0):
        raise ImportProblem(
            "1/x weighting cannot include zero-concentration blanks. "
            "Exclude them with a reason or use unweighted calibration."
        )
    weights = (
        np.ones_like(x)
        if recipe.weighting == "none"
        else (np.min(x) / x) ** (1 if recipe.weighting == "1/x" else 2)
    )
    xscale = float(np.max(x))
    yscale = max(float(np.max(np.abs(y))), np.finfo(float).tiny)
    design = (
        np.column_stack((x / xscale, np.ones_like(x)))
        if recipe.fit_intercept
        else (x / xscale)[:, None]
    )
    weighted = design * np.sqrt(weights)[:, None]
    coefficients, _, rank, _ = np.linalg.lstsq(weighted, y / yscale * np.sqrt(weights), rcond=None)
    if rank != design.shape[1]:
        raise ImportProblem("Calibration is rank deficient; review concentration levels.")
    slope = float(coefficients[0] * yscale / xscale)
    intercept = float(coefficients[1] * yscale) if recipe.fit_intercept else 0.0
    if abs(slope * xscale) <= yscale * 1e-12:
        raise ImportProblem(
            "Calibration response has effectively zero slope; concentrations cannot be calculated."
        )
    residual = y - (slope * x + intercept)
    sse = float(np.sum(weights * residual**2))
    total = float(np.sum(weights * (y - np.average(y, weights=weights)) ** 2))
    r_squared = 1 - sse / total if total > 0 else None
    dof = len(x) - design.shape[1]
    se = None
    warnings = [
        "Calibration is conditional on selected standards, assignments and processing; "
        "review residuals and back-calculated concentrations."
    ]
    if dof > 0:
        covariance = np.linalg.pinv(weighted.T @ weighted) * (sse / yscale**2 / dof)
        se = np.sqrt(np.maximum(np.diag(covariance), 0))
    else:
        warnings.append(
            "No residual degrees of freedom: parameter standard errors are unavailable."
        )
    diagnostics = []
    for p in points:
        comparable = (p.concentration_unit, p.response_unit) == next(iter(units))
        predicted = slope * p.concentration + intercept if comparable else None
        back = (p.response - intercept) / slope if comparable else None
        diagnostics.append(
            {
                "id": p.id,
                "concentration": p.concentration,
                "response": p.response,
                "predicted_response": predicted,
                "residual": p.response - predicted if comparable else None,
                "concentration_unit": p.concentration_unit,
                "response_unit": p.response_unit,
                "units_comparable": comparable,
                "back_calculated": back,
                "error_percent": 100 * (back - p.concentration) / p.concentration
                if p.concentration and comparable
                else None,
                "excluded": p.excluded,
                "reason": p.reason,
                "sample": p.sample,
            }
        )
    return CalibrationResult(
        slope,
        intercept,
        r_squared,
        float(np.sqrt(np.mean(residual**2))),
        float(se[0] * yscale / xscale) if se is not None else None,
        float(se[1] * yscale) if se is not None and recipe.fit_intercept else None,
        float(x.min()),
        float(x.max()),
        *next(iter(units)),
        recipe,
        tuple(points),
        tuple(diagnostics),
        tuple(warnings),
        datetime.now(UTC).isoformat(),
        calibration_key(points, recipe),
    )


def quantify(response, response_unit, result, dilution=1.0, allow_extrapolation=False):
    if (
        response_unit != result.response_unit
        or not np.isfinite([response, dilution]).all()
        or dilution <= 0
    ):
        raise ImportProblem(
            "Response units must match calibration and dilution must be finite and positive."
        )
    value = (response - result.intercept) / result.slope
    tolerance = 32 * np.finfo(float).eps * max(abs(result.minimum), abs(result.maximum))
    outside = value < result.minimum - tolerance or value > result.maximum + tolerance
    return {
        "concentration": value * dilution if not outside or allow_extrapolation else None,
        "undiluted_concentration": value,
        "concentration_unit": result.concentration_unit,
        "dilution": dilution,
        "outside_range": outside,
        "extrapolation_allowed": allow_extrapolation,
        "calibration_key": result.input_key,
        "response": response,
        "response_unit": response_unit,
    }
