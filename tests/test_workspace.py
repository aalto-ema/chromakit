"""Key user journeys through real asynchronous import and plot widgets."""

import numpy as np
from PySide6.QtCore import Qt, QTimer

from chromakit.importers.text import (
    ColumnMapping,
    ParseOptions,
    build_trace,
    load_source,
    parse_source,
)
from chromakit.ui.import_dialog import ImportDialog
from chromakit.ui.theme import apply_theme
from chromakit.ui.window import MainWindow


def source_file(tmp_path, content="Time (min),UV (mAU)\n0,1\n0.5,3\n1,2\n"):
    path = tmp_path / "trace.csv"
    path.write_text(content)
    return path


def test_import_review_and_workspace_inspection(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    dialog = ImportDialog(source_file(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.table is not None, timeout=5000)
    assert dialog.time_unit.currentText() == "min"
    assert dialog.signal_unit.currentText() == "mAU"
    assert dialog.preview.model().rowCount() == 3
    dialog.detector.setCurrentText("UV")
    qtbot.mouseClick(dialog.import_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.trace is not None, timeout=5000)
    assert all(not task.isRunning() for task in dialog.tasks)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.add_trace(dialog.trace)
    x, y = window.curve.getData()
    np.testing.assert_allclose(x, [0, 0.5, 1])
    np.testing.assert_allclose(y, [1, 3, 2])
    assert window.stack.currentIndex() == 1
    qtbot.mouseClick(window.data_button, Qt.MouseButton.LeftButton)
    assert window.data_card.isVisible()
    assert window.data_table.model().rowCount() == 3
    window.inspect_row(window.data_table.model().index(1, 0))
    assert "Signal 3 mAU" in window.cursor_readout.text()
    qtbot.mouseClick(window.grid_button, Qt.MouseButton.LeftButton)
    assert not window.grid_button.isChecked()
    window.remove_trace()
    assert window.stack.currentIndex() == 0
    assert window.trace is None


def test_settings_require_new_preview_and_validation_errors_allow_correction(qtbot, tmp_path):
    dialog = ImportDialog(source_file(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.table is not None, timeout=5000)
    dialog.header.setCurrentText("No")
    assert not dialog.import_button.isEnabled()
    qtbot.mouseClick(dialog.refresh, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.table is not None, timeout=5000)
    qtbot.mouseClick(dialog.import_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.message.objectName() == "error", timeout=5000)
    assert "not numeric" in dialog.message.text()
    dialog.header.setCurrentText("Yes")
    qtbot.mouseClick(dialog.refresh, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.table is not None, timeout=5000)
    assert dialog.message.objectName() == "muted"
    qtbot.mouseClick(dialog.import_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.trace is not None, timeout=5000)


def test_cancel_during_read_does_not_replace_existing_trace(qtbot, tmp_path):
    path = source_file(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    trace = build_trace(
        parse_source(load_source(path), ParseOptions()), ColumnMapping(time_unit="min")
    )
    window.add_trace(trace)
    dialog = ImportDialog(path, window)
    qtbot.addWidget(dialog)
    dialog.reject()
    qtbot.wait(50)
    assert dialog.trace is None
    assert dialog.table is None
    assert all(not task.isRunning() for task in dialog.tasks)
    assert window.trace is trace
    window.remove_trace()


def test_bad_input_shows_error_without_enabling_import(qtbot, tmp_path):
    dialog = ImportDialog(source_file(tmp_path, "Time,Signal\n0,1\n1,2,3\n"))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.message.objectName() == "error", timeout=5000)
    assert "Line 3" in dialog.message.text()
    assert not dialog.import_button.isEnabled()
    dialog.reject()


def test_native_style_modal_journey_keeps_workspace_visible(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    timer = QTimer(window)

    def confirm_when_ready():
        dialog = window.import_dialog
        if dialog is not None and dialog.table is not None:
            timer.stop()
            dialog.import_trace()

    timer.timeout.connect(confirm_when_ready)
    timer.start(20)
    # Safety timeout also exits the nested event loop if import fails unexpectedly.
    safety = QTimer(window)
    safety.setSingleShot(True)
    safety.timeout.connect(lambda: window.import_dialog and window.import_dialog.reject())
    safety.start(5000)
    window.open_path(source_file(tmp_path))
    safety.stop()
    timer.stop()
    assert window.trace is not None
    assert window.isVisible()
    assert window.import_dialog is None
    window.remove_trace()


def test_missing_signal_policy_recovers_import_without_bridging_gaps(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    path = source_file(
        tmp_path, "# time_min_assumed\tred_mAU\tblue_mAU\n0\t1\t2\n1\t3\tnan\n2\t4\t5\n3\t6\t7\n"
    )
    dialog = ImportDialog(path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.table is not None, timeout=5000)
    assert "time_min_assumed" in dialog.time_column.currentText()
    dialog.signal_column.setCurrentIndex(2)
    qtbot.mouseClick(dialog.import_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.message.objectName() == "error", timeout=5000)
    assert "Omit with gaps" in dialog.message.text()
    dialog.missing_signal.setCurrentText("Omit with gaps")
    qtbot.mouseClick(dialog.import_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.trace is not None, timeout=5000)
    assert dialog.trace.channel == "blue_mAU"
    assert list(dialog.trace.gap_after) == [True, False]
    assert dict(dialog.trace.import_settings)["omitted_signal_lines"] == "3"
    window = MainWindow()
    qtbot.addWidget(
        window,
        before_close_func=lambda widget: setattr(
            widget, "saved_signature", widget.project_signature()
        ),
    )
    window.add_trace(dialog.trace)
    np.testing.assert_array_equal(window.curve.opts["connect"], [False, True, True])
    np.testing.assert_array_equal(window.curve.xData, [0, 2, 3])
