"""Detection, table/plot editing, baseline invalidation and per-trace history."""

from dataclasses import replace

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QValidator
from test_baseline import synthetic_curve
from test_peaks import corrected_trace

from chromakit.ui.theme import apply_theme
from chromakit.ui.window import MainWindow


def workspace(qtbot, qapp):
    apply_theme(qapp)
    window = MainWindow()
    qtbot.addWidget(
        window,
        before_close_func=lambda widget: setattr(
            widget, "saved_signature", widget.project_signature()
        ),
    )
    window.show()
    x, baseline, peaks, noise = synthetic_curve()
    trace, applied = corrected_trace(x, peaks + noise)
    window.add_trace(trace)
    window.baseline_panel.state.applied = applied
    window.baseline_panel.state.discard()
    window.render_baseline()
    window.inspector_tabs.setCurrentIndex(2)
    panel = window.peak_panel
    qtbot.mouseClick(panel.detect, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: panel.state.result is not None, timeout=10000)
    return window, trace


def test_results_table_and_numeric_edit_recalculate_signed_area(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.peak_panel
    assert panel.model.rowCount() == 4
    assert panel.model.headerData(3, Qt.Orientation.Horizontal) == "Area\n(mAU × min)"
    first = panel.state.result
    peak = first.peaks[0]
    assert window.peak_region is not None
    assert panel.model.setData(panel.model.index(0, 4), "2.9")
    qtbot.waitUntil(lambda: not panel.busy, timeout=10000)
    assert panel.state.result.peaks[0].start == 2.9
    assert panel.state.result.peaks[0].area < peak.area
    assert panel.state.result.peaks[0].manually_edited
    assert not panel.model.flags(panel.model.index(0, 3)) & Qt.ItemFlag.ItemIsEditable
    window.undo_action.trigger()
    assert panel.state.result is first
    window.redo_action.trigger()
    assert panel.state.result.peaks[0].start == 2.9
    window.remove_trace()


def test_plot_boundary_edits_and_row_selection_are_synchronized(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.peak_panel
    second = panel.state.result.peaks[1]
    panel.table.selectRow(1)
    assert panel.state.selected_id == second.id
    assert window.peak_region.getRegion() == (second.start, second.end)
    window.peak_region.setRegion((6.7, 7.3))
    qtbot.waitUntil(lambda: not panel.busy, timeout=10000)
    edited = panel.state.result.peaks[1]
    assert edited.start == 6.7 and edited.end == 7.3
    assert panel.start.value() == 6.7
    assert panel.end.value() == 7.3
    window.remove_trace()


def test_new_baseline_marks_results_stale_and_undo_restores_dependency(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.peak_panel
    baseline_state = window.baseline_panel.state
    original = baseline_state.applied
    baseline_state.undo_history.append(original)
    baseline_state.applied = replace(original, corrected=original.corrected + 0.25)
    window.render_baseline()
    assert not panel.state.current
    assert "STALE" in window.peak_heading.text()
    assert not panel.update_button.isEnabled()
    assert window.peak_region is None
    baseline_state.undo()
    window.render_baseline()
    assert panel.state.current
    assert panel.update_button.isEnabled()
    baseline_state.clear()
    window.render_baseline()
    assert not panel.detect.isEnabled()
    window.remove_trace()


def test_invalid_edit_preserves_measurements_and_remove_is_undoable(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.peak_panel
    initial = panel.state.result
    panel.edit_peak(initial.peaks[0].id, 3.1, 4)
    qtbot.waitUntil(lambda: not panel.busy, timeout=10000)
    assert "apex" in panel.status.text()
    assert panel.state.result is initial
    assert window.peak_region.getRegion() == (initial.peaks[0].start, initial.peaks[0].end)
    panel.remove_selected()
    assert len(panel.state.result.peaks) == 3
    window.undo_action.trigger()
    assert panel.state.result is initial
    window.remove_trace()


def test_trace_switch_cancel_and_preview_do_not_overwrite_applied_results(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.peak_panel
    first = panel.state.result
    panel.detect_now()
    window.add_trace(trace)
    assert panel.state.result is None
    assert not panel.detect.isEnabled()
    qtbot.wait(100)
    assert panel.state.result is None
    window.samples.setCurrentRow(0)
    assert panel.state.result is first
    baseline_panel = window.baseline_panel
    applied = baseline_panel.state.applied
    baseline_panel.state.preview = replace(applied, corrected=applied.corrected + 10)
    window.inspector_tabs.setCurrentIndex(1)
    window.render_baseline()
    assert panel.state.current
    assert not len(window.peak_markers.points())
    window.inspector_tabs.setCurrentIndex(2)
    assert len(window.peak_markers.points()) == 4
    window.remove_trace()
    window.remove_trace()


def test_scientific_settings_and_corrected_sample_readout(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.peak_panel
    assert panel.prominence.validate("1e-10", 5)[0] == QValidator.State.Acceptable
    panel.prominence.setValue(1e-10)
    assert panel.prominence.value() == 1e-10
    assert "settings changed" in panel.status.text()
    window.show_sample(600, corrected=True)
    assert "Corrected" in window.cursor_readout.text()
    window.cursor_readout.setText("Waiting for hover")
    point = window.corrected_plot.getViewBox().mapViewToScene(
        QPointF(trace.source_time[600], window.baseline_panel.state.applied.corrected[600])
    )
    window.corrected_plot.scene().sigMouseMoved.emit(point)
    qtbot.waitUntil(lambda: "Corrected" in window.cursor_readout.text(), timeout=2000)
    before = panel.state.recipe
    window.add_trace(trace)
    window.samples.setCurrentRow(0)
    assert panel.state.recipe == before
    window.remove_trace()
    window.remove_trace()
