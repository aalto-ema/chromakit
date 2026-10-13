"""Editable fitting workflow, streaming previews and dependency invalidation."""

from dataclasses import replace

import numpy as np
from PySide6.QtCore import Qt
from test_deconvolution import overlap_fixture

from chromakit.ui.theme import apply_theme
from chromakit.ui.window import MainWindow


def workspace(qtbot, qapp):
    apply_theme(qapp)
    window = MainWindow()
    qtbot.addWidget(window, before_close_func=lambda widget: widget.traces.clear())
    window.resize(1440, 1000)
    window.show()
    trace, baseline, recipe, _truth = overlap_fixture("Right tail")
    window.add_trace(trace)
    window.baseline_panel.state.applied = baseline
    window.baseline_panel.state.discard()
    window.render_baseline()
    window.inspector_tabs.setCurrentIndex(3)
    panel = window.fit_panel
    panel.live.setChecked(False)
    panel.state.recipe = recipe
    panel.set_state(panel.state)
    return window, panel


def test_fit_edit_accept_history_and_baseline_stale(qtbot, qapp):
    window, panel = workspace(qtbot, qapp)
    assert panel.workspace.isVisible() and not window.stack.isVisible()
    qtbot.mouseClick(panel.fit_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=10000)
    result = panel.state.preview
    assert panel.results.rowCount() == 3
    assert len(panel.total.xData) == len(result.x)
    np.testing.assert_allclose(panel.residual.yData, result.residual)
    assert panel.apply_button.isEnabled()
    panel.accept()
    assert panel.state.result is result
    assert window.undo_action.isEnabled()
    window.undo_action.trigger()
    assert panel.state.result is None
    window.redo_action.trigger()
    assert panel.state.result is result
    panel.parameters.item(0, 3).setText("2.6")
    assert panel.state.recipe.components[0].area.value == 2.6
    assert panel.state.result is result and panel.state.preview is None
    assert "GUESS" in panel.plot_note.text()
    assert not panel.apply_button.isEnabled()
    panel.parameters.item(0, 4).setText("3.5")
    assert "rejected" in panel.status.text()
    assert panel.state.recipe.components[0].area.lower == 0
    panel.restore()
    assert panel.state.preview is result
    state = window.baseline_panel.state
    state.applied = replace(state.applied, corrected=state.applied.corrected + 0.01)
    window.render_baseline()
    assert "stale" in panel.status.text()
    assert panel.total.xData is None and panel.results.rowCount() == 0
    assert not panel.apply_button.isEnabled()


def test_initialize_drag_window_locks_live_refit_and_trace_switch(qtbot, qapp):
    window, panel = workspace(qtbot, qapp)
    panel.region.setRegion((10.5, 13.5))
    assert panel.start.value() == 10.5 and panel.state.recipe.start == 10.5
    panel.initialize()
    assert panel.parameters.rowCount() == 12
    panel.parameters.item(1, 6).setCheckState(Qt.CheckState.Checked)
    assert panel.state.recipe.components[0].center.locked
    panel.live.setChecked(True)
    qtbot.waitUntil(lambda: panel.state.preview is not None, timeout=15000)
    assert (
        panel.state.preview.fitted[0].center.value == panel.state.recipe.components[0].center.value
    )
    old_state = panel.state
    trace, _baseline, _recipe, _truth = overlap_fixture()
    window.add_trace(trace)
    assert panel.state is not old_state and not panel.initialize_button.isEnabled()
    window.samples.setCurrentRow(0)
    assert panel.state is old_state and panel.state.preview is not None
    window.inspector_tabs.setCurrentIndex(2)
    assert window.stack.isVisible() and not panel.workspace.isVisible()


def test_compare_counts_and_select_without_automatic_accept(qtbot, qapp):
    window, panel = workspace(qtbot, qapp)
    panel.shape.setCurrentText("Gaussian")
    panel.starts.setValue(1)
    panel.compare_counts()
    qtbot.waitUntil(lambda: len(panel.alternatives) == 4, timeout=30000)
    assert panel.comparison.rowCount() == 4
    assert panel.state.result is None
    panel.choose_alternative(1, 0)
    assert len(panel.state.recipe.components) == 3
    assert panel.state.preview is panel.alternatives[1]
    assert panel.apply_button.isEnabled()


def test_cancel_invalidates_worker_streams_and_completed_results(qtbot, qapp):
    _window, panel = workspace(qtbot, qapp)
    panel.run_fit()
    assert panel.busy
    panel.cancel()
    qtbot.wait(250)
    assert panel.state.preview is None
    assert not panel.busy
