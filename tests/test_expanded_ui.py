from dataclasses import replace

from PySide6.QtWidgets import QFileDialog
from test_new_workflows import rendered_image
from test_projects import populated

from chromakit.ui.calibration_dialog import CalibrationDialog
from chromakit.ui.digitize_dialog import DigitizeDialog
from chromakit.ui.library_dialog import LibraryDialog, MatchDialog
from chromakit.ui.window import MainWindow


def workspace(qtbot):
    window = MainWindow()
    qtbot.addWidget(
        window, before_close_func=lambda w: setattr(w, "saved_signature", w.project_signature())
    )
    b, p, f = populated()
    window.add_trace(b.trace)
    window.baseline_states[0], window.peak_states[0], window.fit_states[0] = b, p, f
    window.select_trace(0)
    return window


def test_labels_drag_history_library_matching_and_project_roundtrip(qtbot, tmp_path, monkeypatch):
    window = workspace(qtbot)
    window.inspector_tabs.setCurrentIndex(4)
    panel = window.label_panel
    panel.name.setPlainText("Example compound")
    panel.assign()
    assert window.label_items
    assert window.undo_action.isEnabled()
    label = panel.entries()[0]
    panel.move(label["id"], 12.1, 15)
    assert panel.entries()[0]["label_x"] == 12.1
    window.undo_action.trigger()
    assert panel.entries()[0].get("label_x") != 12.1
    lib = LibraryDialog(window)
    qtbot.addWidget(lib)
    lib.name.setText("Known standard")
    lib.start.setValue(11)
    lib.end.setValue(12.3)
    lib.add()
    assert len(lib.entries()) == 1
    matches = MatchDialog(window, lib.compounds())
    qtbot.addWidget(matches)
    matches.apply()
    assert any(e.get("compound_id") for e in panel.entries())
    path = tmp_path / "labels.chromakit"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window.save_project()
    qtbot.waitUntil(lambda: window.project_task is None, timeout=10000)
    window.open_project(path)
    qtbot.waitUntil(lambda: window.project_task is None, timeout=10000)
    assert window.label_panel.entries()
    assert window.project_extras["compound_library"]
    assert window.label_panel.undo_history


def test_calibration_dialog_reports_stale_and_fit_controls(qtbot):
    window = workspace(qtbot)
    from test_peaks import corrected_trace

    from chromakit.analysis.peaks import PeakRecipe, detect_peaks

    original = window.baseline_states[0]
    trace, baseline = corrected_trace(original.trace.display_time, original.applied.corrected * 2)
    window.add_trace(trace)
    window.baseline_states[1].applied = baseline
    window.baseline_states[1].discard()
    window.peak_states[1].accept(detect_peaks(trace, baseline, PeakRecipe(minimum_prominence=0.1)))
    window.select_trace(1)
    dialog = CalibrationDialog(window)
    qtbot.addWidget(dialog)
    dialog.concentration.setValue(1)
    dialog.add_standard()
    dialog.source.setCurrentIndex(
        next(
            i
            for i, (t, origin, _r, peak) in enumerate(dialog.sources)
            if t.id == trace.id and origin == "Measured peaks" and peak.id == "P1"
        )
    )
    dialog.concentration.setValue(2)
    dialog.add_standard()
    dialog.fit()
    assert dialog.result is not None
    saved = dict(dialog.entry()["result"])
    dialog.load()
    assert dialog.result.created_at == saved["created_at"]
    state = window.peak_states[0]
    state.result = replace(state.result, created_at="reprocessed")
    dialog.fit()
    assert "stale" in dialog.message.text()


def test_image_dialog_creates_calibrated_trace_with_original_bytes(qtbot, tmp_path):
    data, recipe = rendered_image()
    path = tmp_path / "image.png"
    path.write_bytes(data)
    dialog = DigitizeDialog(path)
    qtbot.addWidget(dialog)
    for name, field in dialog.axes.items():
        field.setValue(getattr(recipe, name))
    for field, value in zip(dialog.crop, recipe.crop, strict=True):
        field.setValue(value)
    dialog.time_unit.setCurrentText("min")
    dialog.signal_unit.setCurrentText("mAU")
    dialog.extract()
    qtbot.waitUntil(lambda: len(dialog.points) > 2, timeout=10000)
    dialog.create()
    assert dialog.trace is not None and dialog.record["original_image"] == data
    assert dialog.trace.gap_after.sum() == 1


def test_batch_dialog_streams_and_adds_reviewed_results(qtbot, tmp_path):
    import numpy as np

    from chromakit.analysis.baseline import Anchor, BaselineRecipe, estimate_baseline
    from chromakit.importers.text import (
        ParseOptions,
        build_trace,
        load_source,
        parse_source,
        suggest_mapping,
    )
    from chromakit.ui.batch_dialog import BatchDialog

    x = np.linspace(0, 4, 401)
    y = 3 + 10 * np.exp(-0.5 * ((x - 2) / 0.2) ** 2)
    source = tmp_path / "template.csv"
    np.savetxt(
        source, np.column_stack([x, y]), delimiter=",", header="Time (min),UV (mAU)", comments=""
    )
    table = parse_source(load_source(source), ParseOptions())
    trace = build_trace(table, suggest_mapping(table))
    window = MainWindow()
    qtbot.addWidget(
        window, before_close_func=lambda w: setattr(w, "saved_signature", w.project_signature())
    )
    window.add_trace(trace)
    recipe = BaselineRecipe(method="manual", anchors=(Anchor(0, 3), Anchor(4, 3)))
    window.baseline_states[0].applied = estimate_baseline(trace, recipe)
    window.baseline_states[0].discard()
    window.select_trace(0)
    dialog = BatchDialog(window)
    qtbot.addWidget(dialog)
    dialog.paths = [source]
    dialog.run()
    qtbot.waitUntil(lambda: not dialog.running, timeout=10000)
    assert len(dialog.outcomes) == 1 and dialog.outcomes[0].status == "Success"
    dialog.add()
    assert len(window.traces) == 2 and window.peak_states[1].current


def test_embedded_digitization_can_be_reviewed_without_original_file(qtbot, tmp_path):
    from chromakit.digitization.core import create_trace, trace_pixels

    data, recipe = rendered_image()
    trace, record = create_trace(data, tmp_path / "missing.png", recipe, trace_pixels(data, recipe))
    dialog = DigitizeDialog(tmp_path / "missing.png", record=record)
    qtbot.addWidget(dialog)
    assert dialog.data == data and dialog.points
    dialog.create()
    assert dialog.trace.source_hash == trace.source_hash
