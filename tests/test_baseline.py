"""Known-truth recovery, signed signals, gaps, refinement, and provenance."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pybaselines import Baseline

from chromakit.analysis.baseline import (
    Anchor,
    BaselineCancelled,
    BaselineProblem,
    BaselineRecipe,
    MaskRegion,
    estimate_baseline,
)
from chromakit.application.baselines import BaselineState
from chromakit.domain import Trace, readonly_array


def make_trace(x, y, gaps=None):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    return Trace(
        "Synthetic baseline fixture",
        Path("synthetic.csv"),
        hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest(),
        readonly_array(x * 60),
        readonly_array(x),
        readonly_array(y),
        "min",
        "mAU",
        "UV",
        "UV",
        "utf-8",
        "Comma",
        "Time (min)",
        (),
        readonly_array(np.zeros(len(x) - 1) if gaps is None else gaps, np.bool_),
        (("time_column", "1"), ("signal_column", "2")),
    )


def synthetic_curve(irregular=False, polarity=1):
    x = np.linspace(0, 20, 2001)
    if irregular:
        x = 20 * (x / 20) ** 1.25
    baseline = 2 + 0.2 * x + 0.012 * (x - 10) ** 2
    peaks = sum(
        height * np.exp(-0.5 * ((x - center) / width) ** 2)
        for center, width, height in [(3, 0.2, 40), (7, 0.45, 60), (12, 0.5, 30), (17, 0.25, 50)]
    )
    noise = 0.03 * np.sin(31 * x) + 0.015 * np.cos(57 * x)
    return x, baseline, polarity * peaks, noise


@pytest.mark.parametrize("irregular", [False, True])
@pytest.mark.parametrize("polarity", [1, -1])
def test_adaptive_recovery_on_curved_drift_and_signed_peaks(irregular, polarity):
    x, baseline, peaks, noise = synthetic_curve(irregular, polarity)
    trace = make_trace(x, baseline + peaks + noise)
    raw_before = trace.signal.copy()
    result = estimate_baseline(
        trace,
        BaselineRecipe(polarity="positive" if polarity == 1 else "negative"),
    )
    # Explicit synthetic acceptance criteria: 0.03 mAU RMS, 1% total peak area.
    assert np.sqrt(np.mean((result.baseline - baseline) ** 2)) < 0.03
    expected_area = np.trapezoid(peaks, x)
    measured_area = np.trapezoid(result.corrected, x)
    assert abs(measured_area - expected_area) / abs(expected_area) < 0.01
    np.testing.assert_array_equal(trace.signal, raw_before)
    np.testing.assert_allclose(result.corrected + result.baseline, trace.signal)
    assert all(segment.converged for segment in result.segments)
    with pytest.raises(ValueError):
        result.baseline.setflags(write=True)


def test_asls_recovery_and_peak_height_on_same_curved_fixture():
    x, baseline, peaks, noise = synthetic_curve()
    result = estimate_baseline(
        make_trace(x, baseline + peaks + noise), BaselineRecipe(method="asls")
    )
    assert np.sqrt(np.mean((result.baseline - baseline) ** 2)) < 0.15
    assert abs(np.trapezoid(result.corrected - peaks, x)) / np.trapezoid(peaks, x) < 0.01
    assert abs(np.max(result.corrected) - np.max(peaks)) < 0.5


@pytest.mark.parametrize("method", ["arpls", "asls"])
def test_cancellable_iteration_adapter_matches_library(method):
    x, baseline, peaks, noise = synthetic_curve()
    y = baseline + peaks + noise
    recipe = BaselineRecipe(method=method)
    result = estimate_baseline(make_trace(x, y), recipe)
    offset, scale = np.median(y), np.max(np.abs(y - np.median(y)))
    solver = Baseline((x - x[0]) / (x[-1] - x[0]), assume_sorted=True)
    parameters = dict(lam=1000, num_knots=80, max_iter=79, tol=0.001)
    if method == "asls":
        parameters["p"] = recipe.asymmetry
    reference, _ = getattr(solver, f"pspline_{method}")((y - offset) / scale, **parameters)
    np.testing.assert_allclose(result.baseline, offset + scale * reference, atol=1e-8)


def test_protected_broad_peak_and_excluded_artifact_cannot_influence_fit():
    x = np.linspace(0, 20, 2001)
    baseline = 2 + 0.2 * x
    peaks = 40 * np.exp(-0.5 * ((x - 8) / 1.2) ** 2)
    artifact = np.where((x >= 15) & (x <= 15.2), 500, 0)
    recipe = BaselineRecipe(
        regions=(
            MaskRegion(2, 14),
            MaskRegion(15, 15.2, "Excluded artifact"),
        )
    )
    trace = make_trace(x, baseline + peaks + artifact)
    result = estimate_baseline(trace, recipe)
    assert np.max(np.abs(result.baseline - baseline)) < 0.03
    altered = trace.signal.copy()
    mask = ((x >= 2) & (x <= 14)) | ((x >= 15) & (x <= 15.2))
    altered[mask] += 9999
    second = estimate_baseline(make_trace(x, altered), recipe)
    np.testing.assert_allclose(result.baseline, second.baseline, atol=1e-10)
    assert "half" in " ".join(result.warnings)


def test_manual_anchors_recover_linear_baseline_for_mixed_signs_and_irregular_times():
    x = np.array([0, 0.1, 0.4, 1.2, 2, 4, 5])
    baseline = 3 + 0.8 * x
    peaks = np.array([0, 2, 5, -3, -7, 1, 0])
    trace = make_trace(x, baseline + peaks)
    result = estimate_baseline(
        trace,
        BaselineRecipe(
            method="manual",
            anchors=(Anchor(0, 3), Anchor(5, 7)),
        ),
    )
    np.testing.assert_allclose(result.baseline, baseline)
    np.testing.assert_allclose(result.corrected, peaks)


def test_local_refinement_hits_anchor_and_preserves_outside_neighborhood():
    x, baseline, peaks, noise = synthetic_curve()
    trace = make_trace(x, baseline + peaks + noise)
    initial = estimate_baseline(trace, BaselineRecipe())
    indices = [500, 600, 700]
    anchors = tuple(
        Anchor(x[index], initial.baseline[index] + (0.8 if index == 600 else 0))
        for index in indices
    )
    refined = estimate_baseline(trace, BaselineRecipe(anchors=anchors))
    assert refined.baseline[600] == pytest.approx(initial.baseline[600] + 0.8)
    outside = (x < 5) | (x > 7)
    np.testing.assert_allclose(refined.baseline[outside], initial.baseline[outside], atol=1e-10)


def test_gaps_are_fitted_independently_and_do_not_bridge_baseline_jumps():
    x = np.r_[np.linspace(0, 4, 401), np.linspace(10, 14, 401)]
    baseline = np.r_[2 + x[:401] * 0.2, 25 + x[401:] * 0.3]
    peaks = 30 * np.exp(-0.5 * ((x - 2) / 0.12) ** 2) + 20 * np.exp(-0.5 * ((x - 12) / 0.2) ** 2)
    gaps = np.zeros(len(x) - 1, dtype=bool)
    gaps[400] = True
    result = estimate_baseline(make_trace(x, baseline + peaks, gaps), BaselineRecipe())
    assert len(result.segments) == 2
    assert np.max(np.abs(result.baseline - baseline)) < 0.03
    assert "independently" in " ".join(result.warnings)
    with pytest.raises(BaselineProblem, match="sampling gap"):
        estimate_baseline(
            make_trace(x, baseline + peaks, gaps),
            BaselineRecipe(
                anchors=(Anchor(7, 3),),
            ),
        )


@pytest.mark.parametrize("method", ["arpls", "asls"])
def test_flat_and_affine_negative_signals_are_stable(method):
    for y in (np.full(101, -4.0), np.linspace(-4, 3, 101)):
        result = estimate_baseline(
            make_trace(np.linspace(0, 1, 101), y), BaselineRecipe(method=method)
        )
        np.testing.assert_allclose(result.baseline, y, atol=1e-12)
        np.testing.assert_allclose(result.corrected, 0, atol=1e-12)
        assert result.segments[0].converged


def test_nonconvergence_is_reported_and_provenance_is_serializable():
    x, baseline, peaks, noise = synthetic_curve()
    result = estimate_baseline(
        make_trace(x, baseline + peaks + noise), BaselineRecipe(max_iterations=1)
    )
    assert not result.segments[0].converged
    assert "did not converge" in " ".join(result.warnings)
    metadata = json.loads(json.dumps(result.metadata(), allow_nan=False))
    assert metadata["software_versions"]["pybaselines"]
    assert metadata["recipe"]["max_iterations"] == 1
    assert metadata["time_unit"] == "min"


@pytest.mark.parametrize(
    "recipe, message",
    [
        (BaselineRecipe(anchors=(Anchor(1, 2), Anchor(1, 3))), "same time"),
        (BaselineRecipe(anchors=(Anchor(-1, 2),)), "within"),
        (BaselineRecipe(anchors=(Anchor(0.5, np.nan),)), "finite"),
        (BaselineRecipe(method="manual"), "two|2 anchors"),
        (BaselineRecipe(regions=(MaskRegion(0.5, 0.1),)), "start < end"),
        (BaselineRecipe(regions=(MaskRegion(0, 1),)), "four unmasked"),
        (BaselineRecipe(smoothness=np.nan), "smoothness"),
    ],
)
def test_invalid_refinement_is_actionable(recipe, message):
    trace = make_trace(np.linspace(0, 1, 101), np.sin(np.linspace(0, 1, 101)))
    with pytest.raises(BaselineProblem, match=message):
        estimate_baseline(trace, recipe)


def test_manual_and_masked_edges_have_explicit_extension_warnings():
    x = np.linspace(0, 1, 101)
    trace = make_trace(x, 2 + x)
    manual = estimate_baseline(
        trace,
        BaselineRecipe(
            method="manual",
            anchors=(Anchor(0.2, 2.2), Anchor(0.8, 2.8)),
        ),
    )
    assert manual.baseline[0] == pytest.approx(2.2)
    assert manual.baseline[-1] == pytest.approx(2.8)
    assert "constant extension" in " ".join(manual.warnings)
    auto = estimate_baseline(trace, BaselineRecipe(regions=(MaskRegion(0, 0.1),)))
    assert "Masked segment edges" in " ".join(auto.warnings)


def test_cancel_at_start_and_between_solver_iterations():
    x, baseline, peaks, noise = synthetic_curve()
    trace = make_trace(x, baseline + peaks + noise)
    with pytest.raises(BaselineCancelled):
        estimate_baseline(trace, BaselineRecipe(), cancel=lambda: True)
    stopped = False

    def progress(step, total):
        nonlocal stopped
        stopped = True

    with pytest.raises(BaselineCancelled):
        estimate_baseline(trace, BaselineRecipe(), cancel=lambda: stopped, progress=progress)


def test_small_signal_units_do_not_trigger_flat_trace_shortcut():
    x, baseline, peaks, noise = synthetic_curve()
    signal = baseline + peaks + noise
    reference = estimate_baseline(make_trace(x, signal), BaselineRecipe())
    tiny = estimate_baseline(make_trace(x, signal * 1e-14), BaselineRecipe())
    assert tiny.segments[0].iterations > 0
    np.testing.assert_allclose(tiny.baseline / 1e-14, reference.baseline, atol=1e-8)


def test_applied_history_rejects_stale_preview_and_preserves_raw():
    x, baseline, peaks, noise = synthetic_curve()
    trace = make_trace(x, baseline + peaks + noise)
    state = BaselineState(trace)
    first = estimate_baseline(trace, state.draft)
    assert state.accept_preview(first)
    assert state.applied is None
    assert state.apply()
    assert state.applied is first
    new_recipe = replace(state.draft, method="asls")
    state.update_draft(new_recipe)
    assert not state.accept_preview(first)
    assert not state.apply()
    second = estimate_baseline(trace, new_recipe)
    assert state.accept_preview(second)
    assert state.apply()
    state.undo()
    assert state.applied is first
    state.redo()
    assert state.applied is second
    state.clear()
    assert state.applied is None
    state.undo()
    assert state.applied is second
    assert state.accept_preview(replace(second, input_key="other input")) is False
    np.testing.assert_array_equal(trace.signal, baseline + peaks + noise)
