"""Preview isolation, worker cancellation, refinement, history and trace switching."""

from dataclasses import replace
from threading import Event

import numpy as np
from PySide6.QtCore import QPointF, Qt
from test_baseline import make_trace, synthetic_curve

from chromakit.analysis.baseline import BaselineCancelled, BaselineRecipe, estimate_baseline
from chromakit.ui.baseline_tasks import BaselineController
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
    trace = make_trace(x, baseline + peaks + noise)
    window.add_trace(trace)
    window.open_baseline()
    qtbot.waitUntil(lambda: window.baseline_panel.state.preview is not None, timeout=10000)
    return window, trace


def test_live_preview_apply_discard_and_history(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    raw_before = trace.signal.copy()
    panel = window.baseline_panel
    first = panel.state.preview
    assert panel.state.applied is None
    assert window.raw_badge.text() == "LIVE PREVIEW"
    assert window.corrected_plot.isVisible()
    np.testing.assert_allclose(window.baseline_curve.yData, first.baseline)
    np.testing.assert_allclose(window.corrected_curve.yData, first.corrected)
    assert window.data_table.model().columnCount() == 4
    qtbot.mouseClick(panel.apply, Qt.MouseButton.LeftButton)
    assert panel.state.applied is first
    assert window.undo_action.isEnabled()
    assert window.raw_badge.text() == "BASELINE APPLIED"
    old_range = window.plot.getViewBox().viewRange()[0]
    window.plot.setXRange(2, 9, padding=0)
    panel.stiffness.setValue(70)
    assert not panel.apply.isEnabled()
    assert panel.state.applied is first
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    np.testing.assert_allclose(window.plot.getViewBox().viewRange()[0], [2, 9])
    assert panel.state.preview is not first
    qtbot.mouseClick(panel.discard, Qt.MouseButton.LeftButton)
    assert panel.state.preview is first
    panel.method.setCurrentIndex(panel.method.findData("asls"))
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    qtbot.mouseClick(panel.apply, Qt.MouseButton.LeftButton)
    second = panel.state.applied
    window.undo_action.trigger()
    assert panel.state.applied is first
    window.redo_action.trigger()
    assert panel.state.applied is second
    qtbot.mouseClick(panel.clear, Qt.MouseButton.LeftButton)
    assert panel.state.applied is None
    assert window.data_table.model().columnCount() == 2
    window.undo_action.trigger()
    assert panel.state.applied is second
    np.testing.assert_array_equal(trace.signal, raw_before)
    assert old_range[1] > old_range[0]
    window.remove_trace()


def test_manual_anchor_controls_and_visibility(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.baseline_panel
    panel.method.setCurrentIndex(panel.method.findData("manual"))
    qtbot.waitUntil(lambda: "anchors" in panel.status.text(), timeout=5000)
    panel.add_anchor(0, 3.2)
    panel.add_anchor(20, 7.2)
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    assert panel.state.preview.recipe.method == "manual"
    assert panel.state.preview.baseline[0] == 3.2
    panel.tabs.setCurrentIndex(1)
    panel.anchor_table.item(1, 1).setText("6.2")
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    assert panel.state.preview.baseline[-1] == 6.2
    panel.anchor_table.item(0, 0).setText("not a number")
    assert not panel.apply.isEnabled()
    assert not panel.valid
    assert "numeric" in panel.status.text()
    panel.anchor_table.item(0, 0).setText("0")
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    window.corrected_visible.setChecked(False)
    assert not window.corrected_plot.isVisible()
    window.corrected_visible.setChecked(True)
    assert window.corrected_plot.isVisible()
    window.raw_visible.setChecked(False)
    assert not window.curve.isVisible()
    window.raw_visible.setChecked(True)
    window.remove_trace()


def test_plot_anchor_and_draggable_region_updates_live_recipe(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.baseline_panel
    panel.tabs.setCurrentIndex(1)
    panel.anchor_mode.setChecked(True)
    point = window.plot.getViewBox().mapViewToScene(QPointF(5, 2.5))
    position = window.plot.mapFromScene(point)
    qtbot.mouseClick(window.plot.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert panel.anchor_table.rowCount() == 1
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    panel.add_region()
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    assert len(window.region_items) == 1
    region = window.region_items[0]
    region.setRegion((6, 8))
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    assert panel.state.draft.regions[0].start == 6
    assert panel.state.draft.regions[0].end == 8
    assert panel.state.preview.recipe.regions[0].start == 6
    window.remove_trace()


def test_switching_traces_restores_applied_result_without_cross_contamination(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.baseline_panel
    panel.apply_preview()
    first = panel.state.applied
    second = make_trace(trace.source_time, trace.signal + 10)
    panel.stiffness.setValue(90)  # supersede an in-flight draft immediately
    window.add_trace(second)
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    assert panel.state.trace is second
    assert panel.state.applied is None
    assert panel.state.preview.input_key != first.input_key
    window.samples.setCurrentRow(0)
    assert panel.state.applied is first
    assert panel.state.trace is trace
    panel.discard_preview()
    window.inspector_tabs.setCurrentIndex(0)
    assert window.displayed_baseline() is first
    window.remove_trace()
    window.remove_trace()


def test_controller_coalesces_requests_and_rejects_stale_results(qtbot, monkeypatch):
    started = Event()
    calls = []
    original = estimate_baseline

    def delayed(trace, recipe, cancel, progress):
        calls.append(recipe.smoothness)
        if len(calls) == 1:
            started.set()
            while not cancel():
                Event().wait(0.005)
            raise BaselineCancelled
        return original(trace, recipe, cancel, progress)

    monkeypatch.setattr("chromakit.ui.baseline_tasks.estimate_baseline", delayed)
    x, baseline, peaks, noise = synthetic_curve()
    trace = make_trace(x, baseline + peaks + noise)
    controller = BaselineController()
    delivered = []
    controller.succeeded.connect(delivered.append)
    controller.request(trace, BaselineRecipe())
    qtbot.waitUntil(started.is_set, timeout=5000)
    old_generation = controller.generation
    controller.request(trace, BaselineRecipe(smoothness=2000))
    controller.request(trace, BaselineRecipe(smoothness=3000))
    controller._succeeded(old_generation, original(trace, BaselineRecipe()))
    assert not delivered
    qtbot.waitUntil(lambda: bool(delivered), timeout=10000)
    assert len(delivered) == 1
    assert delivered[0].recipe.smoothness == 3000
    assert calls == [1000, 3000]
    controller.shutdown()


def test_stop_discards_worker_and_window_close_joins_it(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.baseline_panel
    panel.stiffness.setValue(91)
    panel.stop()
    qtbot.wait(400)
    assert panel.state.preview is None
    assert not panel.apply.isEnabled()
    assert not panel.busy
    panel.state.update_draft(replace(panel.state.draft, smoothness=1200))
    panel.controller.request(trace, panel.state.draft)
    window.remove_trace()
    window.close()
    assert panel.controller.task is None or not panel.controller.task.isRunning()


def test_add_anchor_button_starts_with_distinct_edge_anchors(qtbot, qapp):
    window, trace = workspace(qtbot, qapp)
    panel = window.baseline_panel
    panel.method.setCurrentIndex(panel.method.findData("manual"))
    panel.add_default_anchor()
    panel.add_default_anchor()
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    assert [anchor.time for anchor in panel.state.draft.anchors] == [0, 20]
    window.remove_trace()
