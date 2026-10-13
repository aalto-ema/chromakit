import io
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from test_projects import populated

from chromakit.analysis.baseline import Anchor, BaselineRecipe
from chromakit.analysis.calibration import (
    CalibrationPoint,
    CalibrationRecipe,
    fit_calibration,
    quantify,
)
from chromakit.analysis.peaks import PeakRecipe
from chromakit.annotations.labels import make_label, reviewed_labels
from chromakit.application.batch import process_batch
from chromakit.compounds.library import Compound, library_bytes, match_peaks, read_library
from chromakit.digitization.core import DigitizeRecipe, create_trace, trace_pixels
from chromakit.importers.text import ColumnMapping, ImportProblem, ParseOptions


def standard(x, response=None, excluded=False, reason=""):
    return CalibrationPoint(
        str(x),
        "trace" + str(x),
        "P1",
        "Measured peaks",
        "key",
        x,
        4 * x + 2 if response is None else response,
        "mg/L",
        "mAU",
        excluded,
        reason,
    )


@pytest.mark.parametrize("weight", ["none", "1/x", "1/x²"])
def test_external_calibration_preserves_replicates_units_and_range(weight):
    points = [standard(x) for x in [1, 2, 3, 4]]
    result = fit_calibration(points, CalibrationRecipe(weight))
    assert result.slope == pytest.approx(4)
    assert result.intercept == pytest.approx(2)
    assert result.slope_se is not None
    assert quantify(10, "mAU", result)["concentration"] == pytest.approx(2)
    assert quantify(100, "mAU", result)["concentration"] is None
    assert quantify(100, "mAU", result, 2, True)["outside_range"]
    with pytest.raises(ImportProblem):
        quantify(10, "nA", result)


def test_zero_intercept_exclusions_blanks_and_negative_slope():
    points = [standard(0), standard(1), standard(2)]
    with pytest.raises(ImportProblem, match="zero-concentration"):
        fit_calibration(points, CalibrationRecipe("1/x"))
    result = fit_calibration(
        [replace(points[0], excluded=True, reason="blank"), *points[1:]], CalibrationRecipe("1/x")
    )
    assert result.diagnostics[0]["excluded"]
    with pytest.raises(ImportProblem, match="reason"):
        fit_calibration([replace(points[0], excluded=True), *points[1:]])
    result = fit_calibration(
        [standard(x, -4 * x) for x in [1, 2, 3]], CalibrationRecipe(fit_intercept=False)
    )
    assert result.intercept == 0 and result.slope == pytest.approx(-4)
    assert quantify(-8, "mAU", result)["concentration"] == pytest.approx(2)


def rendered_image():
    pixels = np.full((120, 220, 3), 255, dtype=np.uint8)
    ys = []
    for x in range(20, 201):
        y = 90 - int(50 * np.exp(-0.5 * ((x - 110) / 20) ** 2))
        ys.append(y)
        pixels[y - 1 : y + 2, x] = [0, 0, 255]
    pixels[:, 105:109] = 255  # occluded columns are not silently bridged
    stream = io.BytesIO()
    Image.fromarray(pixels).save(stream, format="PNG")
    recipe = DigitizeRecipe(
        20, 200, 0, 18, 100, 20, 0, 8, (20, 10, 201, 110), time_unit="min", signal_unit="mAU"
    )
    return stream.getvalue(), recipe


def test_digitized_calibration_recovery_gaps_and_original_provenance():
    data, recipe = rendered_image()
    points = trace_pixels(data, recipe)
    trace, record = create_trace(data, Path("synthetic.png"), recipe, points)
    assert trace.gap_after.sum() == 1
    assert trace.display_time[0] == pytest.approx(0)
    assert trace.display_time[-1] == pytest.approx(18)
    assert trace.signal.max() == pytest.approx(6)
    assert record["original_image"] == data
    assert record["time_per_pixel"] == pytest.approx(0.1)
    assert dict(trace.import_settings)["reader_version"] == "image-v2"
    with pytest.raises(ImportProblem, match="calibrated"):
        trace_pixels(data, replace(recipe, time_unit="unknown"))
    reversed_trace, _ = create_trace(
        data, Path("synthetic.png"), replace(recipe, time1=18, time2=0), points
    )
    assert np.all(np.diff(reversed_trace.display_time) > 0)
    assert reversed_trace.gap_after.sum() == 1


def test_library_roundtrip_matching_units_ambiguity_and_label_invalidation():
    b, p, f = populated()
    peak = p.result.peaks[0]
    c = Compound(
        "c1",
        "Known name",
        peak.retention_time - 0.1,
        peak.retention_time + 0.1,
        "min",
        ("alias",),
        "C2H4",
        "UV",
    )
    for format in ["csv", "json"]:
        assert read_library(library_bytes([c], format), format) == (c,)
    matching = match_peaks(b.trace, [peak], [c])
    assert len(matching) == 1 and not matching[0][2]
    assert match_peaks(b.trace, [peak], [replace(c, detector="PAD")]) == []
    assert match_peaks(b.trace, [peak], [c, replace(c, id="c2")])[0][2]
    label = make_label(b.trace, b.applied, p.result, peak, "Example")
    assert not reviewed_labels([label], p.result, f.result, b.applied)[0]["stale"]
    assert reviewed_labels([label], replace(p.result, created_at="changed"), f.result, b.applied)[
        0
    ]["stale"]
    from chromakit.compounds.library import library_key

    label.update(compound_id=c.id, library_key=library_key(c))
    assert reviewed_labels(
        [label], p.result, f.result, b.applied, [asdict(replace(c, name="Changed"))]
    )[0]["stale"]


def test_batch_keeps_success_when_other_file_fails_and_can_cancel(tmp_path):
    x = np.linspace(0, 4, 401)
    signal = 3 + 10 * np.exp(-0.5 * ((x - 2) / 0.2) ** 2)
    first = tmp_path / "one.csv"
    second = tmp_path / "two.csv"
    np.savetxt(
        first,
        np.column_stack([x, signal]),
        delimiter=",",
        header="Time (min),UV (mAU)",
        comments="",
    )
    second.write_text("Time,Signal\n0,broken\n1,2\n")
    recipe = BaselineRecipe(method="manual", anchors=(Anchor(0, 3), Anchor(4, 3)))
    result = process_batch(
        [first, second],
        ParseOptions(),
        ColumnMapping(time_unit="min", signal_unit="mAU"),
        recipe,
        PeakRecipe(),
    )
    assert result[0].status == "Success" and len(result[0].peaks.peaks) == 1
    assert result[1].status == "Failed"
    assert (
        process_batch(
            [first], ParseOptions(), ColumnMapping(), recipe, PeakRecipe(), cancel=lambda: True
        )
        == ()
    )


def test_manual_pixel_edits_change_analysis_identity_even_with_same_image():
    from chromakit.analysis.baseline import input_key

    data, recipe = rendered_image()
    points = list(trace_pixels(data, recipe))
    original, _ = create_trace(data, Path("source.png"), recipe, points, manual=True)
    x, y = points[20]
    points[20] = (x, y - 1)
    edited, _ = create_trace(data, Path("source.png"), recipe, points, manual=True)
    assert original.source_hash == edited.source_hash
    assert input_key(original) != input_key(edited)


def test_stored_batch_recipe_roundtrip_and_column_guard(tmp_path):
    from chromakit.application.batch import stored_recipe

    x = np.linspace(0, 4, 401)
    y = 3 + 10 * np.exp(-0.5 * ((x - 2) / 0.2) ** 2)
    source = tmp_path / "different.csv"
    np.savetxt(
        source, np.column_stack([x, y]), delimiter=",", header="Seconds,Signal (mAU)", comments=""
    )
    baseline = BaselineRecipe(method="manual", anchors=(Anchor(0, 3), Anchor(4, 3)))
    record = {
        "parse": asdict(ParseOptions()),
        "mapping": asdict(ColumnMapping(time_unit="min", signal_unit="mAU")),
        "baseline": asdict(baseline),
        "peaks": asdict(PeakRecipe()),
        "fit": None,
    }
    options, mapping, b, p, f = stored_recipe(record)
    assert b == baseline and f is None
    result = process_batch([source], options, mapping, b, p, headers=("Time (min)", "Signal (mAU)"))
    assert result[0].status == "Failed" and "column names" in result[0].message
