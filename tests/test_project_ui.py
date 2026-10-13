from PySide6.QtWidgets import QFileDialog
from test_projects import populated

from chromakit.ui.window import MainWindow


def test_save_load_updates_workspace_and_dirty_state(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(
        window,
        before_close_func=lambda widget: setattr(
            widget, "saved_signature", widget.project_signature()
        ),
    )
    b, p, f = populated()
    window.add_trace(b.trace)
    window.baseline_states[0], window.peak_states[0], window.fit_states[0] = b, p, f
    window.select_trace(0)
    target = tmp_path / "project.chromakit"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.save_project()
    qtbot.waitUntil(lambda: window.project_task is None, timeout=10000)
    assert target.exists()
    assert window.project_signature() == window.saved_signature
    window.open_project(target)
    qtbot.waitUntil(lambda: window.project_task is None, timeout=10000)
    assert len(window.traces) == 1 and window.peak_states[0].current
    assert window.fit_states[0].valid(window.fit_states[0].result)
    assert window.project_signature() == window.saved_signature


def test_new_project_clears_feature_state_and_empty_library_changes_are_protected(
    qtbot, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    window = MainWindow()
    qtbot.addWidget(
        window, before_close_func=lambda w: setattr(w, "saved_signature", w.project_signature())
    )
    window.show()
    window.project_extras["compound_library"] = [
        {
            "id": "one",
            "name": "Example",
            "start": 1.0,
            "end": 2.0,
            "time_unit": "min",
            "aliases": (),
            "formula": "",
            "detector": "",
        }
    ]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not window.close()
    assert window.isVisible()
    window.new_project()
    assert not window.project_extras and not window.traces
    assert window.saved_signature == window.project_signature()
