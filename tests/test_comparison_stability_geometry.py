"""Known-coordinate comparison, repeated-start sensitivity and geometric recovery."""

import io
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from test_deconvolution import component, overlap_fixture
from test_expanded_ui import workspace
from test_new_workflows import rendered_image
from test_peaks import corrected_trace

from chromakit.analysis.comparison import compare
from chromakit.analysis.deconvolution import FitCancelled, FitRecipe, curves, fit
from chromakit.analysis.stability import analyze_stability, match_components
from chromakit.digitization.core import create_trace, image_pixels, trace_pixels
from chromakit.digitization.geometry import transform_image
from chromakit.digitization.quality import path_quality
from chromakit.export.comparison import comparison_bytes, comparison_csv
from chromakit.export.figures import FigureSpec
from chromakit.importers.text import ImportProblem
from chromakit.ui.comparison_dialog import ComparisonDialog
from chromakit.ui.digitize_dialog import DigitizeDialog
from chromakit.ui.stability_dialog import StabilityDialog


def test_comparison_converts_time_and_preserves_reference_gaps_and_originals():
    a, ba = corrected_trace(
        np.array([0.0, 1.0, 2.0, 3.0, 4.0]),
        np.array([0.0, 1.0, 2.0, 3.0, 4.0]),
        np.array([False, True, False, False]),
    )
    b, bb = corrected_trace(np.arange(0, 4.1, 0.5), np.arange(0, 4.1, 0.5))
    before = b.signal.copy()
    result = compare([a, b], [ba, bb], ["#000000", "#FF0000"], a.id, mode="Corrected")
    diff = result.series[1].difference
    assert np.isnan(diff[3])
    assert not result.series[1].difference_connect[2]
    np.testing.assert_allclose(diff[np.isfinite(diff)], 0, atol=1e-12)
    seconds = compare([a, b], [ba, bb], ["#000000", "#FF0000"], a.id, time_unit="s")
    np.testing.assert_array_equal(seconds.series[0].x, a.display_time * 60)
    np.testing.assert_array_equal(b.signal, before)
    assert b.signal.flags.writeable is False


def test_comparison_normalization_and_unit_guards_and_export():
    a, ba = corrected_trace(
        np.linspace(0, 5, 101), np.exp(-(((np.linspace(0, 5, 101) - 2) / 0.4) ** 2))
    )
    b, bb = corrected_trace(a.display_time, ba.corrected * 3)
    result = compare([a, b], [ba, bb], ["#000000", "#FF0000"], a.id, "Corrected", "Peak magnitude")
    np.testing.assert_allclose(result.series[1].difference, 0, atol=1e-12)
    assert result.series[1].divisor == pytest.approx(3)
    altered = replace(b, signal_unit="mV")
    with pytest.raises(ImportProblem, match="units"):
        compare([a, altered], [ba, bb], ["#000000", "#FF0000"], a.id)
    with pytest.raises(ImportProblem, match="baseline"):
        compare([a, b], [ba, None], ["#000000", "#FF0000"], a.id, "Corrected")
    data = comparison_bytes(
        result, FigureSpec(width=640, height=480, unit="px", transparent=True), "png"
    )
    image = Image.open(io.BytesIO(data))
    assert image.size == (640, 480) and image.mode == "RGBA"
    assert b"normalization_divisor" in comparison_csv(result)


def test_stability_repeats_recover_known_areas_and_locks_and_cancel():
    trace, baseline, recipe, truth = overlap_fixture()
    result = fit(trace, baseline, recipe)
    report = analyze_stability(trace, baseline, result, repeats=4, spread=0.15)
    assert report["comparable_count"] == 4
    assert all(row["area"]["relative_range_percent"] < 0.01 for row in report["components"])
    np.testing.assert_allclose(
        [row["area"]["median"] for row in report["components"]],
        [c.area.value for c in truth],
        rtol=1e-5,
    )
    with pytest.raises(FitCancelled):
        analyze_stability(trace, baseline, result, 3, cancel=lambda: True)
    locked = replace(
        recipe,
        components=tuple(replace(c, area=replace(c.area, locked=True)) for c in result.fitted),
    )
    locked_result = fit(trace, baseline, locked)
    locked_report = analyze_stability(trace, baseline, locked_result, 3, spread=0.1)
    assert all(row["area"]["min"] == row["area"]["max"] for row in locked_report["components"])


def test_constraint_matching_and_coincident_area_ambiguity():
    a, b = component("A", 2, 11.5, 0.3), component("B", 3, 12, 0.3)
    recipe = FitRecipe(10, 14, (a, b))
    assert match_components((a, b), (b, a), recipe) == (1, 0)
    fixed = replace(a, center=replace(a.center, locked=True))
    constrained = replace(recipe, components=(fixed, b))
    assert match_components((fixed, b), (b, fixed), constrained) == (0, 1)
    x = np.linspace(10, 14, 201)
    coincident = (a, replace(b, center=a.center, sigma=a.sigma))
    trace, baseline = corrected_trace(x, sum(curves(x, coincident)))
    reference = fit(trace, baseline, FitRecipe(10, 14, coincident, starts=1))
    report = analyze_stability(trace, baseline, reference, 5, spread=0.6, tolerance=0.1)
    assert any("coincident" in warning for warning in report["warnings"])
    assert any(row["area"]["relative_range_percent"] > 15 for row in report["components"])


def test_identity_perspective_deskew_and_invalid_corners():
    data, recipe = rendered_image()
    raw = image_pixels(data)
    corners = ((0.0, 0.0), (219.0, 0.0), (219.0, 119.0), (0.0, 119.0))
    transformed = image_pixels(data, perspective=corners, rectified_size=(220, 120))
    np.testing.assert_array_equal(raw, transformed)
    tilted = Image.fromarray(raw).rotate(-7, expand=True, fillcolor="white")
    repaired = transform_image(tilted, deskew=7)
    assert repaired.width >= raw.shape[1]
    with pytest.raises(ImportProblem):
        image_pixels(data, perspective=corners[::-1], rectified_size=(220, 120))
    with pytest.raises(ImportProblem):
        image_pixels(data, deskew=60)
    recipe = replace(recipe, perspective=corners, rectified_size=(220, 120))
    trace, record = create_trace(data, Path("source.png"), recipe, trace_pixels(data, recipe))
    assert record["recipe"]["perspective"] == corners
    assert trace.display_time[-1] == pytest.approx(18)


def test_quality_flags_crossings_wrong_points_and_gaps():
    data, recipe = rendered_image()
    pixels = image_pixels(data)
    points = trace_pixels(data, recipe)
    flags = path_quality(pixels, recipe, points)
    assert any("Missing interval before point" in flag["reasons"] for flag in flags)
    modified = list(points)
    modified[10] = (modified[10][0], 20.0)
    flags = path_quality(pixels, recipe, modified)
    assert any("Point does not follow selected-color pixels" in flag["reasons"] for flag in flags)


def test_comparison_and_stability_dialogs_preserve_accepted_fit(qtbot):
    window = workspace(qtbot)
    trace = replace(window.traces[0], id="second-synthetic", name="Second trace")
    window.add_trace(trace)
    dialog = ComparisonDialog(window)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.comparison_result is not None, timeout=10000)
    assert len(dialog.comparison_result.series) == 2
    accepted = window.fit_states[0].result
    stability = StabilityDialog(window, window.fit_states[0])
    qtbot.addWidget(stability)
    stability.repeats.setValue(3)
    stability.spread.setValue(0.1)
    stability.run()
    qtbot.waitUntil(lambda: stability.report is not None, timeout=30000)
    assert window.fit_states[0].result is accepted
    assert window.project_extras["fit_stability"][window.traces[0].id]


def test_digitize_collection_and_geometry_reset(qtbot, tmp_path):
    data, recipe = rendered_image()
    path = tmp_path / "source.png"
    path.write_bytes(data)
    dialog = DigitizeDialog(path)
    qtbot.addWidget(dialog)
    for name, field in dialog.axes.items():
        field.setValue(getattr(recipe, name))
    for field, value in zip(dialog.crop, recipe.crop, strict=True):
        field.setValue(value)
    dialog.time_unit.setCurrentText("min")
    dialog.signal_unit.setCurrentText("mAU")
    dialog.points = list(trace_pixels(data, recipe))
    dialog.populate()
    dialog.trace_name.setText("Blue")
    dialog.queue_trace()
    assert len(dialog.traces) == 1 and dialog.traces[0].name == "Blue"
    assert not dialog.points and dialog.records[0]["original_image"] == data
    dialog.deskew.setValue(5)
    dialog.apply_geometry()
    qtbot.waitUntil(lambda: dialog.applied_geometry[0] == 5, timeout=10000)
    assert dialog.axes["x2"].value() == 0 and not dialog.points
    assert dialog.records[0]["recipe"]["deskew"] == 0
    dialog.finish_collection()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_projective_rectification_maps_four_source_corners():
    y, x = np.mgrid[:120, :220]
    image = Image.fromarray(np.stack([x, y, np.zeros_like(x)], axis=2).astype("uint8"))
    corners = ((10.0, 20.0), (190.0, 10.0), (170.0, 100.0), (20.0, 110.0))
    repaired = np.asarray(transform_image(image, perspective=corners, size=(181, 91)))
    for point, expected in zip([(0, 0), (0, 180), (90, 180), (90, 0)], corners, strict=True):
        np.testing.assert_allclose(repaired[point][:2], expected, atol=2)


def test_new_metadata_survives_project_roundtrip_and_corrupt_report_is_rejected(tmp_path):
    from chromakit.analysis.stability import validate_report
    from chromakit.application.baselines import BaselineState
    from chromakit.application.deconvolution import FitState
    from chromakit.application.peaks import PeakState
    from chromakit.persistence.project import load_project, save_project, snapshot

    trace, baseline, recipe, _ = overlap_fixture()
    reference = fit(trace, baseline, recipe)
    report = analyze_stability(trace, baseline, reference, 3, spread=0.1)
    b = BaselineState(trace, applied=baseline)
    extras = {
        "comparison": dict(
            selected=[trace.id],
            colors={trace.id: "#167D8D"},
            mode="Corrected",
            normalization="None",
            reference_id=trace.id,
            time_unit="min",
        ),
        "fit_stability": {trace.id: report},
    }
    path = tmp_path / "comparison-stability.chromakit"
    save_project(
        path, snapshot([b], [PeakState(b)], [FitState(b, result=reference)], extras=extras)
    )
    *_, restored = load_project(path)
    assert restored["comparison"] == extras["comparison"]
    assert restored["fit_stability"][trace.id]["components"] == report["components"]
    with pytest.raises(ValueError):
        validate_report(dict(report, repeats=1000))


def test_two_colored_traces_recovered_as_one_reviewed_collection(qtbot, tmp_path):
    from PIL import ImageDraw

    from chromakit.digitization.core import DigitizeRecipe

    image = Image.new("RGB", (180, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.line(
        [(x, 80 - int(30 * np.exp(-(((x - 60) / 20) ** 2)))) for x in range(10, 170)],
        fill="blue",
        width=2,
    )
    draw.line(
        [(x, 95 - int(25 * np.exp(-(((x - 115) / 17) ** 2)))) for x in range(10, 170)],
        fill="red",
        width=2,
    )
    path = tmp_path / "two-colors.png"
    image.save(path)
    recipe = DigitizeRecipe(
        10, 169, 0, 16, 100, 20, 0, 8, (10, 10, 170, 110), time_unit="min", signal_unit="mAU"
    )
    dialog = DigitizeDialog(path)
    qtbot.addWidget(dialog)
    for name, field in dialog.axes.items():
        field.setValue(getattr(recipe, name))
    for field, value in zip(dialog.crop, recipe.crop, strict=True):
        field.setValue(value)
    dialog.time_unit.setCurrentText("min")
    dialog.signal_unit.setCurrentText("mAU")
    for color, name in [((0, 0, 255), "Blue"), ((255, 0, 0), "Red")]:
        dialog.color = color
        dialog.trace_name.setText(name)
        dialog.extract()
        qtbot.waitUntil(lambda: bool(dialog.points), timeout=10000)
        dialog.queue_trace()
    assert [t.name for t in dialog.traces] == ["Blue", "Red"]
    assert dialog.traces[0].source_hash == dialog.traces[1].source_hash
    assert dialog.records[0]["recipe"]["color"] != (255, 0, 0)
    assert dialog.records[1]["recipe"]["color"] == (255, 0, 0)
    assert dialog.traces[0].signal.max() != pytest.approx(dialog.traces[1].signal.max())
    dialog.finish_collection()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_absolute_area_normalization_does_not_integrate_across_gaps():
    a, baseline = corrected_trace(
        np.array([0.0, 1.0, 10.0, 11.0]), np.ones(4), np.array([False, True, False])
    )
    b = replace(a, id="second")
    result = compare(
        [a, b], [baseline, baseline], ["#000000", "#FF0000"], a.id, "Corrected", "Absolute area"
    )
    assert result.series[0].divisor == pytest.approx(2)
    np.testing.assert_allclose(result.series[0].y, 0.5)
