"""Known-truth overlapping fits, constraints, scientific diagnostics and provenance."""

import json
from dataclasses import replace

import numpy as np
import pytest
from test_peaks import corrected_trace

from chromakit.analysis.baseline import MaskRegion
from chromakit.analysis.deconvolution import (
    Component,
    FitCancelled,
    FitProblem,
    FitRecipe,
    Parameter,
    curves,
    fit,
    initialize,
)
from chromakit.application.baselines import BaselineState
from chromakit.application.deconvolution import FitState


def component(identifier, area, center, sigma, tau=0.1, model="Gaussian"):
    return Component(
        identifier,
        model,
        Parameter(area, 0 if area >= 0 else -100, 100 if area >= 0 else 0),
        Parameter(center, 10, 14),
        Parameter(sigma, 0.005, 1),
        Parameter(tau, 0.001, 2),
    )


def overlap_fixture(model="Gaussian", sign=1, irregular=False):
    x = np.linspace(10, 14, 601)
    if irregular:
        x = 10 + 4 * ((x - 10) / 4) ** 1.2
    truth = (
        component("C1", sign * 3, 11.5, 0.25, 0.3, model),
        component("C2", sign * 4, 11.95, 0.17, 0.17, model),
        component("C3", sign * 0.5, 12.85, 0.13, 0.08, "Gaussian"),
    )
    trace, baseline = corrected_trace(x, sum(curves(x, truth)))
    guesses = tuple(
        replace(
            c,
            center=replace(c.center, value=c.center.value + 0.04),
            area=replace(c.area, value=c.area.value * 0.9),
        )
        for c in truth
    )
    return trace, baseline, FitRecipe(10, 14, guesses, starts=2), truth


@pytest.mark.parametrize("model", ["Gaussian", "Right tail", "Left tail"])
@pytest.mark.parametrize("sign", [1, -1])
def test_recover_overlaps_and_signed_areas_on_irregular_coordinates(model, sign):
    trace, baseline, recipe, truth = overlap_fixture(model, sign, irregular=True)
    before = trace.signal.copy()
    updates = []
    result = fit(trace, baseline, recipe, update=updates.append)
    assert result.converged
    assert result.rmse < 1e-6
    np.testing.assert_allclose(
        [p.area for p in result.peaks], [c.area.value for c in truth], rtol=1e-4
    )
    assert result.aicc is not None and result.bic is not None
    assert result.free_parameters == (9 if model == "Gaussian" else 11)
    assert updates
    for array in (result.x, result.total, result.residual, *result.curves):
        with pytest.raises(ValueError):
            array.setflags(write=True)
    np.testing.assert_array_equal(trace.signal, before)
    json.dumps(result.metadata(), allow_nan=False)


def test_automatic_guesses_resolve_broad_shoulder_and_late_bump():
    trace, baseline, _recipe, truth = overlap_fixture("Right tail")
    recipe = initialize(trace, baseline, 10, 14, 3, "Right tail")
    result = fit(trace, baseline, recipe)
    assert result.rmse < 0.012
    assert result.converged
    assert sum(p.area for p in result.peaks) == pytest.approx(
        sum(c.area.value for c in truth), rel=0.02
    )


def test_locked_parameters_remain_exact_and_all_locked_evaluation():
    trace, baseline, recipe, truth = overlap_fixture()
    locked = tuple(replace(c, center=replace(c.center, locked=True)) for c in truth)
    result = fit(trace, baseline, replace(recipe, components=locked))
    assert [c.center.value for c in result.fitted] == [c.center.value for c in locked]
    all_locked = tuple(
        replace(
            c,
            **{
                name: replace(getattr(c, name), locked=True)
                for name in ("area", "center", "sigma", "tau")
            },
        )
        for c in truth
    )
    result = fit(trace, baseline, replace(recipe, components=all_locked))
    assert result.free_parameters == 0
    assert result.rmse < 1e-12
    assert all(p.area_se is None for p in result.peaks)


def test_robust_loss_does_not_report_covariance_or_likelihood_criteria():
    trace, baseline, recipe, _ = overlap_fixture()
    result = fit(trace, baseline, replace(recipe, loss="soft_l1"))
    assert result.aicc is None and result.bic is None
    assert all(p.area_se is None for p in result.peaks)


def test_unresolved_duplicate_components_are_flagged():
    trace, baseline, recipe, truth = overlap_fixture()
    # Same-location components with locked identical shapes leave interchangeable areas.
    duplicate = replace(truth[0], id="C4")
    components = tuple(
        replace(c, center=replace(c.center, locked=True), sigma=replace(c.sigma, locked=True))
        for c in (*truth, duplicate)
    )
    result = fit(trace, baseline, replace(recipe, components=components))
    assert any("poorly resolved" in warning for warning in result.warnings)
    assert all(p.area_se is None for p in result.peaks)


def test_window_area_is_not_full_extrapolated_area():
    trace, baseline, recipe, truth = overlap_fixture("Right tail")
    result = fit(trace, baseline, replace(recipe, start=11.5, end=12.4))
    assert any(p.window_area < p.area for p in result.peaks)
    assert any("extrapolates" in flag for p in result.peaks for flag in p.flags)


def test_cancel_and_invalid_constraints():
    trace, baseline, recipe, _ = overlap_fixture()
    with pytest.raises(FitCancelled):
        fit(trace, baseline, recipe, cancel=lambda: True)
    broken = replace(recipe.components[0], sigma=Parameter(0.2, 0, 1))
    with pytest.raises(FitProblem, match="strictly positive"):
        fit(trace, baseline, replace(recipe, components=(broken,)))
    broken = replace(recipe.components[0], area=Parameter(1, -2, 3))
    with pytest.raises(FitProblem, match="positive or negative"):
        fit(trace, baseline, replace(recipe, components=(broken,)))


def test_gaps_artifacts_flat_signal_and_too_sparse_windows():
    trace, baseline, recipe, _ = overlap_fixture()
    gaps = np.zeros(len(trace.time) - 1, dtype=bool)
    gaps[300] = True
    trace, baseline = corrected_trace(trace.display_time, baseline.corrected, gaps)
    with pytest.raises(FitProblem, match="continuous segment"):
        fit(trace, baseline, recipe)
    trace, baseline = corrected_trace(
        trace.display_time,
        baseline.corrected,
        regions=(MaskRegion(11.8, 12.1, "Excluded artifact"),),
    )
    with pytest.raises(FitProblem, match="continuous segment"):
        fit(trace, baseline, recipe)
    trace, baseline = corrected_trace(np.linspace(10, 14, 50), np.zeros(50))
    with pytest.raises(FitProblem, match="no measurable signal"):
        initialize(trace, baseline, 10, 14)
    with pytest.raises(FitProblem, match="12 observations"):
        initialize(trace, baseline, 10, 10.1)


def test_history_rejects_stale_baseline_and_preserves_accepted_fit():
    trace, baseline, recipe, _ = overlap_fixture()
    state = FitState(BaselineState(trace, applied=baseline), recipe)
    state.preview = fit(trace, baseline, recipe)
    assert state.accept()
    accepted = state.result
    state.baseline_state.applied = replace(baseline, corrected=baseline.corrected + 0.1)
    assert not state.valid(accepted)
    assert not state.accept()
    state.baseline_state.applied = baseline
    state.undo()
    assert state.result is None
    state.undo(redo=True)
    assert state.result is accepted and state.valid(accepted)


def test_four_components_in_broad_unresolved_blue_like_group():
    x = np.linspace(10.5, 14, 701)
    truth = (
        component("C1", 1.4, 11.15, 0.11, 0.32, "Right tail"),
        component("C2", 2.1, 11.45, 0.16, 0.35, "Right tail"),
        component("C3", 7.5, 11.9, 0.27, 0.21, "Right tail"),
        component("C4", 0.45, 12.84, 0.14, 0.1, "Gaussian"),
    )
    trace, baseline = corrected_trace(x, sum(curves(x, truth)))
    guesses = tuple(
        replace(
            c,
            area=replace(c.area, value=c.area.value * 0.9),
            center=replace(c.center, value=c.center.value + 0.02),
        )
        for c in truth
    )
    result = fit(trace, baseline, FitRecipe(10.5, 14, guesses, starts=2))
    assert result.converged and result.rmse < 1e-5
    np.testing.assert_allclose(
        [p.area for p in result.peaks], [c.area.value for c in truth], rtol=0.005
    )
    simpler = fit(trace, baseline, initialize(trace, baseline, 10.5, 14, 3, "Right tail"))
    assert simpler.rmse > result.rmse
    assert any(
        "correlated" in warning or "poorly resolved" in warning for warning in result.warnings
    )


def test_nonconvergence_and_active_bounds_are_explicit():
    trace, baseline, recipe, _truth = overlap_fixture()
    result = fit(trace, baseline, replace(recipe, max_nfev=1, starts=1))
    assert not result.converged
    assert any("did not converge" in warning for warning in result.warnings)
    restricted = replace(recipe.components[0], area=Parameter(1, 0, 1))
    result = fit(
        trace, baseline, replace(recipe, components=(restricted, *recipe.components[1:]), starts=1)
    )
    assert any("constraint" in warning for warning in result.warnings)
    assert all(p.area_se is None for p in result.peaks)
