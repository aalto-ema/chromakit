"""Measured peak heights/areas, physical time coordinates, and boundary validation."""

import json
from dataclasses import replace

import numpy as np
import pytest
from test_baseline import make_trace

from chromakit.analysis.baseline import Anchor, BaselineRecipe, MaskRegion, estimate_baseline
from chromakit.analysis.peaks import (
    PeakCancelled,
    PeakProblem,
    PeakRecipe,
    baseline_key,
    detect_peaks,
    edit_boundaries,
    integrated_area,
)
from chromakit.application.baselines import BaselineState
from chromakit.application.peaks import PeakState


def corrected_trace(x, y, gaps=None, regions=()):
    trace = make_trace(x, np.asarray(y) + 3, gaps)
    cuts = np.r_[0, np.flatnonzero(trace.gap_after) + 1, len(x)]
    anchors = tuple(
        Anchor(float(x[index]), 3)
        for first, last in zip(cuts[:-1], cuts[1:], strict=True)
        for index in (first, last - 1)
    )
    baseline = estimate_baseline(
        trace, BaselineRecipe(method="manual", anchors=anchors, regions=regions)
    )
    return trace, baseline


@pytest.mark.parametrize("irregular", [False, True])
@pytest.mark.parametrize("sign", [1, -1])
def test_gaussian_retention_height_and_area(irregular, sign):
    x = np.linspace(0, 5, 2001)
    if irregular:
        x = 5 * (x / 5) ** 1.25
    y = sign * 10 * np.exp(-0.5 * ((x - 2.5) / 0.3) ** 2)
    trace, baseline = corrected_trace(x, y)
    before = trace.signal.copy()
    result = detect_peaks(
        trace,
        baseline,
        PeakRecipe(polarity="positive" if sign > 0 else "negative", minimum_prominence=0.1),
    )
    assert len(result.peaks) == 1
    peak = result.peaks[0]
    assert peak.retention_time == pytest.approx(2.5, abs=0.004)
    assert peak.height == pytest.approx(sign * 10, rel=0.0001)
    assert peak.area == pytest.approx(sign * 10 * 0.3 * np.sqrt(2 * np.pi), rel=0.002)
    assert result.area_unit == "mAU × min"
    np.testing.assert_array_equal(trace.signal, before)


def test_between_sample_boundaries_use_piecewise_linear_integral():
    # This signal is exactly y=2x+1, with irregular observations.
    x = np.array([0, 0.2, 0.8, 1.7, 2.0])
    y = 2 * x + 1
    assert integrated_area(x, y, 0.3, 1.4) == pytest.approx((1.4**2 + 1.4) - (0.3**2 + 0.3))


def test_both_signs_and_signed_areas():
    x = np.linspace(0, 10, 2001)
    y = 8 * np.exp(-0.5 * ((x - 3) / 0.2) ** 2) - 5 * np.exp(-0.5 * ((x - 7) / 0.3) ** 2)
    trace, baseline = corrected_trace(x, y)
    result = detect_peaks(trace, baseline, PeakRecipe(polarity="both", minimum_prominence=0.2))
    assert len(result.peaks) == 2
    assert result.peaks[0].height > 0 and result.peaks[0].area > 0
    assert result.peaks[1].height < 0 and result.peaks[1].area < 0


def test_overlapping_peaks_have_nonoverlapping_valley_splits():
    x = np.linspace(0, 10, 4001)
    y = 12 * np.exp(-0.5 * ((x - 4) / 0.4) ** 2) + 8 * np.exp(-0.5 * ((x - 5) / 0.3) ** 2)
    trace, baseline = corrected_trace(x, y)
    result = detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.5))
    assert len(result.peaks) == 2
    assert result.peaks[0].end <= result.peaks[1].start
    assert any(peak.flags for peak in result.peaks)
    measured = sum(peak.area for peak in result.peaks)
    expected = (12 * 0.4 + 8 * 0.3) * np.sqrt(2 * np.pi)
    assert measured == pytest.approx(expected, rel=0.003)


def test_gap_and_excluded_artifact_segments_are_never_integrated_across():
    x = np.r_[np.linspace(0, 4, 401), np.linspace(10, 14, 401)]
    y = 10 * np.exp(-0.5 * ((x - 2) / 0.2) ** 2) + 8 * np.exp(-0.5 * ((x - 12) / 0.3) ** 2)
    gaps = np.zeros(len(x) - 1, dtype=bool)
    gaps[400] = True
    trace, baseline = corrected_trace(x, y, gaps)
    result = detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.1))
    assert len(result.peaks) == 2
    assert result.peaks[0].segment_end == 400
    with pytest.raises(PeakProblem, match="gap"):
        edit_boundaries(trace, baseline, result, result.peaks[0].id, 0.5, 11)
    with_artifact = y.copy()
    with_artifact[(x >= 1) & (x <= 1.1)] = 1000
    trace, baseline = corrected_trace(
        x, with_artifact, gaps, (MaskRegion(1, 1.1, "Excluded artifact"),)
    )
    result = detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.1))
    assert len(result.peaks) == 2
    assert result.peaks[0].start > 1.1


def test_actual_time_width_and_separation_filters():
    x = np.r_[np.linspace(0, 4, 2000, endpoint=False), np.linspace(4, 10, 301)]
    y = (
        10 * np.exp(-0.5 * ((x - 2) / 0.1) ** 2)
        + 8 * np.exp(-0.5 * ((x - 2.8) / 0.1) ** 2)
        + 6 * np.exp(-0.5 * ((x - 7) / 0.5) ** 2)
    )
    trace, baseline = corrected_trace(x, y)
    result = detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.2, minimum_separation=1))
    assert [round(peak.retention_time, 2) for peak in result.peaks] == [2, 7]
    result = detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.2, minimum_width=0.8))
    assert len(result.peaks) == 1
    assert result.peaks[0].retention_time == pytest.approx(7, abs=0.02)


def test_flat_signal_has_no_peaks_and_correlated_noise_is_rejected():
    x = np.linspace(0, 20, 2401)
    trace, baseline = corrected_trace(x, np.zeros_like(x))
    assert not detect_peaks(trace, baseline, PeakRecipe()).peaks
    y = 0.12 * np.sin(17 * x) + 30 * np.exp(-0.5 * ((x - 8) / 0.3) ** 2)
    trace, baseline = corrected_trace(x, y)
    result = detect_peaks(trace, baseline, PeakRecipe())
    assert len(result.peaks) == 1


def test_edits_reintegrate_and_reject_invalid_or_overlapping_boundaries():
    x = np.linspace(0, 10, 2001)
    y = 10 * np.exp(-0.5 * ((x - 3) / 0.3) ** 2) + 6 * np.exp(-0.5 * ((x - 7) / 0.4) ** 2)
    trace, baseline = corrected_trace(x, y)
    result = detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.2))
    first = result.peaks[0]
    edited = edit_boundaries(trace, baseline, result, first.id, 2.8, 3.2)
    assert edited.peaks[0].area < first.area
    assert edited.peaks[0].manually_edited
    assert edited.peaks[0].height == first.height
    with pytest.raises(PeakProblem, match="apex"):
        edit_boundaries(trace, baseline, result, first.id, 3.1, 4)
    with pytest.raises(PeakProblem, match="overlap"):
        edit_boundaries(trace, baseline, result, first.id, 2, 8)
    with pytest.raises(PeakProblem, match="stale"):
        edit_boundaries(
            trace, replace(baseline, corrected=baseline.corrected + 1), result, first.id, 2, 4
        )


def test_peak_history_and_baseline_invalidation():
    x = np.linspace(0, 5, 1001)
    trace, baseline = corrected_trace(x, 10 * np.exp(-0.5 * ((x - 2) / 0.2) ** 2))
    source = BaselineState(trace, applied=baseline)
    state = PeakState(source)
    state.sync_baseline()
    first = detect_peaks(trace, baseline, PeakRecipe())
    assert state.accept(first) and state.current
    second = edit_boundaries(trace, baseline, first, first.peaks[0].id, 1.8, 2.2)
    state.accept(second)
    state.undo()
    assert state.result is first
    state.undo(redo=True)
    assert state.result is second
    source.applied = replace(baseline, corrected=baseline.corrected + 1)
    state.sync_baseline()
    assert not state.current
    assert not state.accept(first)
    source.applied = baseline
    state.sync_baseline()
    assert state.current
    assert json.loads(json.dumps(second.metadata(), allow_nan=False))[
        "baseline_key"
    ] == baseline_key(baseline)


def test_cancel_and_bad_settings_are_actionable():
    x = np.linspace(0, 5, 101)
    trace, baseline = corrected_trace(x, np.sin(x))
    with pytest.raises(PeakCancelled):
        detect_peaks(trace, baseline, PeakRecipe(), cancel=lambda: True)
    with pytest.raises(PeakProblem, match="finite"):
        detect_peaks(trace, baseline, PeakRecipe(minimum_width=np.nan))
    with pytest.raises(PeakProblem, match="different trace"):
        detect_peaks(trace, replace(baseline, input_key="another input"), PeakRecipe())


def test_cancel_between_global_prominence_chunks(monkeypatch):
    x = np.linspace(0, 5, 4096)
    trace, baseline = corrected_trace(x, np.sin(np.arange(len(x)) * np.pi / 4))
    import chromakit.analysis.peaks as module

    original = module.peak_prominences
    stopped = False

    def wrapped(*args, **kwargs):
        nonlocal stopped
        values = original(*args, **kwargs)
        stopped = True
        return values

    monkeypatch.setattr(module, "peak_prominences", wrapped)
    with pytest.raises(PeakCancelled):
        detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.1), cancel=lambda: stopped)
