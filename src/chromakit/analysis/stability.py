"""Repeat-start sensitivity with constraint-aware component matching; not uncertainty intervals."""

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime

import numpy as np
import scipy
from scipy.optimize import linear_sum_assignment

from chromakit.analysis.deconvolution import FitCancelled, FitProblem, fit, validate
from chromakit.analysis.peaks import baseline_key


def fit_key(result):
    return hashlib.sha256(json.dumps(result.metadata(), sort_keys=True).encode()).hexdigest()


def jitter(recipe, rng, spread):
    components = []
    span = recipe.end - recipe.start
    for component in recipe.components:
        values = {}
        for name in ("area", "center", "sigma", "tau"):
            p = getattr(component, name)
            if p.locked or (name == "tau" and component.model == "Gaussian"):
                continue
            scale = (
                span * 0.2 if name == "center" else max(abs(p.value), (p.upper - p.lower) * 0.005)
            )
            value = p.value + rng.normal() * spread * scale
            epsilon = (p.upper - p.lower) * 1e-9
            values[name] = replace(
                p, value=float(np.clip(value, p.lower + epsilon, p.upper - epsilon))
            )
        components.append(replace(component, **values))
    return replace(recipe, components=tuple(components), starts=1)


def constraints(component):
    return (
        component.model,
        tuple(
            (name, p.lower, p.upper, p.locked, p.value if p.locked else None)
            for name in ("area", "center", "sigma", "tau")
            if name != "tau" or component.model != "Gaussian"
            for p in [getattr(component, name)]
        ),
    )


def match_components(reference, fitted, recipe):
    """Only interchangeable constraints may be permuted. Never cross fixed identities."""
    span = recipe.end - recipe.start
    cost = np.full((len(reference), len(fitted)), 1e12)
    for i, a in enumerate(reference):
        for j, b in enumerate(fitted):
            if constraints(recipe.components[i]) != constraints(recipe.components[j]):
                continue
            cost[i, j] = ((a.center.value - b.center.value) / span) ** 2 + 0.01 * (
                np.log(a.sigma.value / b.sigma.value) ** 2
            )
    rows, columns = linear_sum_assignment(cost)
    if np.any(cost[rows, columns] >= 1e12):
        raise FitProblem("Unable to match components under their original constraints.")
    return tuple(int(column) for column in columns)


def analyze_stability(
    trace,
    baseline,
    reference,
    repeats=12,
    spread=0.5,
    seed=1729,
    tolerance=0.05,
    cancel=lambda: False,
    update=None,
):
    if (
        baseline_key(baseline) != reference.baseline_key
        or trace.source_hash != reference.source_hash
    ):
        raise FitProblem("Use a current accepted fit and applied baseline.")
    if (
        type(repeats) is not int
        or not 3 <= repeats <= 30
        or not np.isfinite([spread, tolerance]).all()
        or not 0.05 <= spread <= 2
        or not 0 <= tolerance <= 1
    ):
        raise FitProblem("Use 3–30 starts, spread 0.05–2 and objective tolerance 0–100%.")
    recipe = replace(reference.recipe, components=reference.fitted, starts=1)
    validate(recipe)
    rng = np.random.default_rng(seed)
    runs = []
    for index in range(repeats):
        if cancel():
            raise FitCancelled()
        start = recipe if index == 0 else jitter(recipe, rng, spread)
        try:
            result = fit(trace, baseline, start, cancel)
            matching = match_components(reference.fitted, result.fitted, recipe)
            run = dict(
                index=index + 1,
                converged=result.converged,
                cost=result.objective_cost,
                rmse=result.rmse,
                condition=result.condition,
                message=result.message,
                warnings=list(result.warnings),
                starting_components=[asdict(c) for c in start.components],
                fitted=[asdict(result.fitted[j]) for j in matching],
                peaks=[
                    dict(asdict(result.peaks[j]), id=reference.peaks[i].id)
                    for i, j in enumerate(matching)
                ],
                matching=list(matching),
            )
        except FitProblem as error:
            run = dict(
                index=index + 1,
                converged=False,
                cost=None,
                rmse=None,
                message=str(error),
                starting_components=[asdict(c) for c in start.components],
                fitted=[],
                peaks=[],
            )
        runs.append(run)
        if update:
            update(index + 1, repeats)
    converged = [r for r in runs if r["converged"]]
    best = min((r["cost"] for r in converged), default=None)
    floor = float(reference.observed @ reference.observed) * 1e-10
    good = (
        [r for r in converged if r["cost"] <= best * (1 + tolerance) + floor]
        if best is not None
        else []
    )
    for run in runs:
        run["comparable"] = run in good
    summaries = []
    warnings = [
        "Starting-guess spread is sensitivity, not a confidence interval or compound identity."
    ]
    if len(good) < 3:
        warnings.append(
            "Fewer than three comparably good converged fits; stability is inconclusive."
        )
    if len(converged) < repeats:
        warnings.append("Some starts did not converge; inspect all attempts.")
    for i, peak in enumerate(reference.peaks):
        row = dict(id=peak.id, model=peak.model, accepted_area=peak.area, count=len(good))
        for metric in ("area", "window_area", "retention_time"):
            values = np.array([r["peaks"][i][metric] for r in good])
            median = float(np.median(values)) if len(values) else None
            relative = (
                float(np.ptp(values) / abs(median) * 100)
                if median is not None and abs(median) > 1e-12
                else None
            )
            row[metric] = dict(
                min=float(np.min(values)) if len(values) else None,
                max=float(np.max(values)) if len(values) else None,
                median=median,
                relative_range_percent=relative,
            )
        if (
            row["area"]["relative_range_percent"] is not None
            and row["area"]["relative_range_percent"] > 15
        ):
            warnings.append(f"{peak.id}: full area varies by more than 15% among comparable fits.")
        if len(good) and any(r["matching"][i] != i for r in good):
            warnings.append(
                f"{peak.id}: component ordering swaps across starts; matching is provisional."
            )
        summaries.append(row)
    if any(
        constraints(recipe.components[i]) == constraints(recipe.components[j])
        and abs(a.center.value - b.center.value) < min(a.sigma.value, b.sigma.value)
        for i, a in enumerate(reference.fitted)
        for j, b in enumerate(reference.fitted)
        if i < j
    ):
        warnings.append("Nearly coincident components: individual area matching can be ambiguous.")
    return dict(
        algorithm_version="fit-stability-v1",
        numpy_version=np.__version__,
        scipy_version=scipy.__version__,
        trace_id=trace.id,
        source_hash=trace.source_hash,
        baseline_key=reference.baseline_key,
        fit_key=fit_key(reference),
        time_unit=trace.time_unit,
        signal_unit=trace.signal_unit,
        recipe=asdict(recipe),
        repeats=repeats,
        spread=spread,
        seed=seed,
        tolerance=tolerance,
        comparable_count=len(good),
        converged_count=len(converged),
        runs=runs,
        components=summaries,
        warnings=warnings,
        created_at=datetime.now(UTC).isoformat(),
    )


def recipe_from_dict(value):
    from chromakit.analysis.deconvolution import Component, FitRecipe, Parameter

    recipe = FitRecipe(
        **dict(
            value,
            components=tuple(
                Component(
                    **dict(
                        component,
                        **{
                            name: Parameter(**component[name])
                            for name in ("area", "center", "sigma", "tau")
                        },
                    )
                )
                for component in value["components"]
            ),
        )
    )
    validate(recipe)
    return recipe


def validate_report(report):
    """Validate saved scalar reports before a project is installed in the workspace."""
    try:
        if report["algorithm_version"] != "fit-stability-v1":
            raise ValueError("version")
        for key in [
            "trace_id",
            "source_hash",
            "baseline_key",
            "fit_key",
            "time_unit",
            "signal_unit",
            "created_at",
        ]:
            if not isinstance(report[key], str):
                raise ValueError(key)
        repeats = report["repeats"]
        if type(repeats) is not int or not 3 <= repeats <= 30 or len(report["runs"]) != repeats:
            raise ValueError("repeat count")
        for key in ["converged_count", "comparable_count"]:
            if type(report[key]) is not int or not 0 <= report[key] <= repeats:
                raise ValueError(key)
        if not 0.05 <= report["spread"] <= 2 or not 0 <= report["tolerance"] <= 1:
            raise ValueError("settings")
        recipe = recipe_from_dict(report["recipe"])
        if len(report["components"]) != len(recipe.components):
            raise ValueError("components")
        for run in report["runs"]:
            if type(run["index"]) is not int or not 1 <= run["index"] <= repeats:
                raise ValueError("index")
            if type(run["converged"]) is not bool or type(run["comparable"]) is not bool:
                raise ValueError("status")
            for key in ["cost", "rmse"]:
                if run[key] is not None and (not np.isfinite(run[key]) or run[key] < 0):
                    raise ValueError(key)
            if run["fitted"]:
                recipe_from_dict(dict(report["recipe"], components=run["fitted"]))
                if len(run["peaks"]) != len(recipe.components):
                    raise ValueError("peaks")
            for peak in run["peaks"]:
                if not isinstance(peak["id"], str) or not all(
                    np.isfinite(peak[key]) for key in ["area", "window_area", "retention_time"]
                ):
                    raise ValueError("peak values")
        for row in report["components"]:
            if not isinstance(row["id"], str) or not np.isfinite(row["accepted_area"]):
                raise ValueError("area")
            for key in ["area", "window_area", "retention_time"]:
                for value in row[key].values():
                    if value is not None and not np.isfinite(value):
                        raise ValueError("spread")
        if not isinstance(report["warnings"], list) or not all(
            isinstance(w, str) for w in report["warnings"]
        ):
            raise ValueError("warnings")
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise FitProblem("Invalid saved fit stability report.") from error
