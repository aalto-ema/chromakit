from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from test_new_workflows import rendered_image

from chromakit.digitization.core import create_trace
from chromakit.digitization.repair import repair_pixels
from chromakit.importers.text import ImportCancelled, ImportProblem
from chromakit.ui.digitize_dialog import DigitizeDialog


def test_linear_gap_fill_is_bounded_preserves_observations_and_does_not_extrapolate():
    _, recipe = rendered_image()
    points = ((2.0, 12.0), (3.0, 13.0), (7.0, 17.0), (20.0, 30.0), (21.0, 31.0))
    repaired = repair_pixels(points, replace(recipe, interpolate_gaps=True, maximum_gap=3))
    array = np.asarray(repaired.points)
    assert repaired.interpolated_x == (4, 5, 6)
    np.testing.assert_allclose(array[:, 1], array[:, 0] + 10)
    assert array[0, 0] == 2 and array[-1, 0] == 21
    assert all(point in repaired.points for point in points)
    assert not any(7 < x < 20 for x, _ in repaired.points)
    assert repair_pixels(points, recipe).points == points


def test_isolated_signed_spikes_repaired_without_smoothing_broad_peak_or_ramp():
    _, recipe = rendered_image()
    x = np.arange(100.0)
    clean = 60 - 25 * np.exp(-(((x - 50) / 9) ** 2)) + 0.05 * x
    noisy = clean.copy()
    noisy[20] -= 30
    noisy[80] += 30
    recipe = replace(recipe, remove_spikes=True)
    repair = repair_pixels(tuple(zip(x, noisy, strict=True)), recipe)
    assert repair.corrected_x == (20, 80)
    result = np.asarray(repair.points)[:, 1]
    np.testing.assert_allclose(result, clean, atol=0.01)
    np.testing.assert_array_equal(result[35:66], clean[35:66])
    assert not repair.interpolated_x


def test_long_runs_endpoints_and_separate_gap_segments_are_not_spike_repaired():
    _, recipe = rendered_image()
    x = np.arange(30.0)
    y = np.full(30, 60.0)
    y[0] = 15
    y[12:16] = 15
    repair = repair_pixels(tuple(zip(x, y, strict=True)), replace(recipe, remove_spikes=True))
    np.testing.assert_array_equal(np.asarray(repair.points)[:, 1], y)
    points = ((0.0, 60.0), (1.0, 15.0), (2.0, 60.0), (20.0, 60.0), (21.0, 60.0))
    assert not repair_pixels(points, replace(recipe, remove_spikes=True)).corrected_x


def test_repaired_trace_retains_original_path_and_flags_even_for_reversed_calibration():
    data, recipe = rendered_image()
    x = np.r_[np.arange(10, 30), np.arange(33, 70)].astype(float)
    y = np.full(len(x), 70.0)
    y[8] = 20
    points = tuple(zip(x, y, strict=True))
    recipe = replace(
        recipe, remove_spikes=True, interpolate_gaps=True, time1=18, time2=0, crop=(0, 10, 201, 110)
    )
    trace, record = create_trace(data, Path("test.png"), recipe, points)
    assert not trace.gap_after.any()
    assert (np.diff(trace.time) > 0).all()
    assert len(record["original_pixel_points"]) == len(points)
    assert record["spike_corrected_pixel_x"] == [18.0]
    assert record["interpolated_pixel_x"] == [30.0, 31.0, 32.0]
    assert len(record["pixel_points"]) == len(points) + 3
    assert any("INTERPOLATED" in warning for warning in trace.warnings)
    assert any("SPIKE REPAIR" in warning for warning in trace.warnings)
    original, _ = create_trace(data, Path("test.png"), replace(recipe, remove_spikes=False), points)
    assert original.import_settings != trace.import_settings


def test_repair_cancellation_and_invalid_parameters():
    _, recipe = rendered_image()
    with pytest.raises(ImportCancelled):
        repair_pixels(((0, 1), (4, 2)), recipe, cancel=lambda: True)
    for options in ({"maximum_gap": 0}, {"spike_window": 8}, {"spike_threshold": np.nan}):
        with pytest.raises(ImportProblem):
            repair_pixels(((0, 1), (4, 2)), replace(recipe, **options))
    with pytest.raises(ImportProblem):
        repair_pixels(((4, 2), (0, 1)), recipe)


def test_preview_controls_and_embedded_original_path_restore(qtbot, tmp_path):
    data, recipe = rendered_image()
    points = [(float(x), 70.0) for x in range(10, 70) if x not in (30, 31, 32)]
    points[8] = (18.0, 20.0)
    recipe = replace(recipe, remove_spikes=True, interpolate_gaps=True, crop=(0, 10, 201, 110))
    trace, record = create_trace(data, tmp_path / "missing.png", recipe, points)
    dialog = DigitizeDialog(trace.source, record=record)
    qtbot.addWidget(dialog)
    assert dialog.points == points
    qtbot.waitUntil(lambda: dialog.recovery is not None, timeout=10000)
    assert dialog.recovery.corrected_x == (18,)
    assert dialog.recovery.interpolated_x == (30, 31, 32)
    dialog.interpolate_gaps.setChecked(False)
    dialog.remove_spikes.setChecked(False)
    qtbot.waitUntil(lambda: dialog.recovery is not None, timeout=10000)
    assert dialog.recovery.points == tuple(points)
    dialog.create()
    assert dialog.trace.gap_after.sum() == 1
    assert dialog.record["original_pixel_points"] == record["original_pixel_points"]


def test_repair_project_roundtrip_preserves_originals_and_settings(tmp_path):
    from chromakit.application.baselines import BaselineState
    from chromakit.application.deconvolution import FitState
    from chromakit.application.peaks import PeakState
    from chromakit.persistence.project import load_project, save_project, snapshot

    data, recipe = rendered_image()
    points = [(float(x), 70.0) for x in range(25, 80) if x not in (50, 51)]
    points[10] = (35.0, 20.0)
    recipe = replace(recipe, interpolate_gaps=True, remove_spikes=True)
    trace, record = create_trace(data, tmp_path / "missing.png", recipe, points)
    baseline = BaselineState(trace)
    path = tmp_path / "repaired.chromakit"
    save_project(
        path,
        snapshot(
            [baseline],
            [PeakState(baseline)],
            [FitState(baseline)],
            extras={"digitizations": {trace.id: record}},
        ),
    )
    bs, _, _, _, extras = load_project(path)
    restored = extras["digitizations"][trace.id]
    assert restored["original_pixel_points"] == record["original_pixel_points"]
    assert restored["interpolated_pixel_x"] == [50.0, 51.0]
    assert restored["spike_corrected_pixel_x"] == [35.0]
    assert restored["recipe"]["interpolate_gaps"] is True
    np.testing.assert_array_equal(bs[0].trace.signal, trace.signal)
