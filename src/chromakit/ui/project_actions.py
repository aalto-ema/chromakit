"""Asynchronous project operations and save/discard protection for the workspace."""

import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from chromakit.importers.text import ImportCancelled
from chromakit.persistence.project import load_project, save_project, snapshot


class ProjectTask(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.cancelled = Event()

    def run(self):
        try:
            result = self.operation(self.cancelled.is_set)
        except ImportCancelled:
            return
        except Exception as error:
            logging.getLogger(__name__).exception("Project operation failed")
            self.failed.emit(str(error))
        else:
            if not self.cancelled.is_set():
                self.succeeded.emit(result)


class ProjectActions:
    """Mixin: keep project mechanics separate from plotting and analytical widgets."""

    def setup_projects(self):
        self.project_path = None
        self.project_task = None
        self.project_extras = {}
        self.saved_signature = None
        menu = self.open_action.parent().menuBar().actions()[0].menu()
        self.new_project_action = QAction("New project", self)
        self.new_project_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_project_action.triggered.connect(
            lambda: self.guard_project_changes(self.new_project)
        )
        menu.insertAction(self.open_action, self.new_project_action)
        self.project_open_action = QAction("Open project…", self)
        self.project_open_action.setShortcut("Ctrl+Shift+O")
        self.project_open_action.triggered.connect(self.choose_project)
        menu.insertAction(self.open_action, self.project_open_action)
        self.save_action = QAction("Save project", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(lambda: self.save_project())
        menu.addAction(self.save_action)
        self.save_as_action = QAction("Save project as…", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(lambda: self.save_project(save_as=True))
        menu.addAction(self.save_as_action)
        self.baseline_panel.changed.connect(self.project_changed)
        self.peak_panel.changed.connect(self.project_changed)
        self.fit_panel.changed.connect(self.project_changed)
        self.samples.currentRowChanged.connect(self.project_changed)
        self.project_cancel_button = QPushButton("Cancel operation")
        self.project_cancel_button.clicked.connect(self.cancel_project)
        self.statusBar().addPermanentWidget(self.project_cancel_button)
        self.project_cancel_button.hide()
        self.saved_signature = self.project_signature()

    @staticmethod
    def extra_signature(value):
        if isinstance(value, bytes):
            return (id(value), len(value))
        if isinstance(value, dict):
            return tuple(
                (key, ProjectActions.extra_signature(item))
                for key, item in sorted(value.items())
                if item is not None
                and not (
                    isinstance(item, (dict, list, tuple))
                    and not ProjectActions.extra_signature(item)
                )
            )
        if isinstance(value, (tuple, list)):
            return tuple(ProjectActions.extra_signature(item) for item in value)
        return value

    def project_signature(self):
        return (
            tuple(
                (
                    id(s.trace),
                    repr(s.draft),
                    id(s.applied),
                    tuple(map(id, s.undo_history)),
                    tuple(map(id, s.redo_history)),
                )
                for s in self.baseline_states
            ),
            tuple(
                (
                    repr(s.recipe),
                    id(s.result),
                    s.selected_id,
                    tuple(map(id, s.undo_history)),
                    tuple(map(id, s.redo_history)),
                )
                for s in self.peak_states
            ),
            tuple(
                (
                    repr(s.recipe),
                    id(s.result),
                    tuple(map(id, s.undo_history)),
                    tuple(map(id, s.redo_history)),
                )
                for s in self.fit_states
            ),
            self.samples.currentRow(),
            self.extra_signature(self.project_extras),
        )

    def project_changed(self, *_):
        if not hasattr(self, "saved_signature"):
            return
        dirty = self.project_signature() != self.saved_signature
        name = self.project_path.name if self.project_path else "Untitled project"
        self.setWindowTitle(f"ChromaKit · {name}{' *' if dirty else ''}")
        self.session_note.setText(name + (" · Unsaved changes" if dirty else ""))

    def cancel_project(self):
        if self.project_task:
            self.project_task.cancelled.set()
            self.project_cancel_button.setEnabled(False)
            self.statusBar().showMessage("Cancelling project operation…")

    def project_job(self, operation, callback):
        if self.project_task:
            return False
        task = ProjectTask(operation, self)
        self.project_task = task
        self.project_cancel_button.setEnabled(True)
        self.project_cancel_button.show()
        self.centralWidget().setEnabled(False)
        self.menuBar().setEnabled(False)
        task.succeeded.connect(callback)
        task.failed.connect(self.project_failed)
        task.finished.connect(self.project_finished)
        self.statusBar().showMessage("Project operation in progress…")
        task.start()
        return True

    def project_failed(self, message):
        self.statusBar().showMessage(message)
        self.project_error = QMessageBox(
            QMessageBox.Icon.Warning, "Project operation failed", message, parent=self
        )
        self.project_error.show()

    def project_finished(self):
        task = self.project_task
        self.project_task = None
        self.project_cancel_button.hide()
        if task.cancelled.is_set():
            self.statusBar().showMessage("Project operation cancelled")
        self.centralWidget().setEnabled(True)
        self.menuBar().setEnabled(True)
        task.deleteLater()
        self.project_changed()

    def save_project(self, save_as=False, on_success=None):
        if self.project_task:
            return
        path = self.project_path
        if save_as or path is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save ChromaKit project",
                str(path or "Untitled.chromakit"),
                "ChromaKit project (*.chromakit)",
            )
            if not filename:
                return
            path = Path(filename)
            if path.suffix.lower() != ".chromakit":
                path = path.with_suffix(".chromakit")
                if (
                    path.exists()
                    and QMessageBox.question(
                        self,
                        "Replace project?",
                        f"Replace {path.name}?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
        state = snapshot(
            self.baseline_states,
            self.peak_states,
            self.fit_states,
            self.samples.currentRow(),
            self.project_extras,
        )
        signature = self.project_signature()

        def saved(_result):
            self.project_path = path
            self.saved_signature = signature
            self.statusBar().showMessage(f"Saved {path.name}")
            if on_success:
                # Wait until the worker is fully cleaned up before a dependent load/close.
                self.project_task.finished.connect(on_success)

        self.project_job(lambda cancel: save_project(path, state, cancel), saved)

    def guard_project_changes(self, callback):
        if self.project_task:
            return False
        if self.project_signature() == self.saved_signature:
            callback()
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved project changes",
            "Save your changes before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:

            def proceed_after_save():
                if self.project_signature() == self.saved_signature:
                    callback()
                else:
                    QMessageBox.information(
                        self,
                        "New analysis results",
                        "Analysis changed during saving. "
                        "Save the updated project before continuing.",
                    )

            self.save_project(on_success=proceed_after_save)
        elif answer == QMessageBox.StandardButton.Discard:
            callback()
            return True
        return False

    def new_project(self):
        self.baseline_panel.controller.cancel()
        self.peak_panel.controller.cancel()
        self.fit_panel.cancel()
        self.samples.blockSignals(True)
        self.traces.clear()
        self.baseline_states.clear()
        self.peak_states.clear()
        self.fit_states.clear()
        self.samples.clear()
        self.samples.blockSignals(False)
        self.project_extras = {}
        self.project_path = None
        self.label_panel.undo_history.clear()
        self.label_panel.redo_history.clear()
        self.select_trace(-1)
        self.saved_signature = self.project_signature()
        self.project_changed()
        self.statusBar().showMessage("New empty project")

    def choose_project(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open ChromaKit project", "", "ChromaKit project (*.chromakit)"
        )
        if filename:
            self.guard_project_changes(lambda: self.open_project(Path(filename)))

    def open_project(self, path):
        def opened(result):
            baselines, peaks, fits, selected, extras = result
            self.baseline_panel.controller.cancel()
            self.peak_panel.controller.cancel()
            self.fit_panel.cancel()
            self.samples.blockSignals(True)
            self.samples.clear()
            self.traces.clear()
            self.baseline_states.clear()
            self.peak_states.clear()
            self.fit_states.clear()
            for baseline in baselines:
                self.add_trace(baseline.trace)
            self.baseline_states, self.peak_states, self.fit_states = baselines, peaks, fits
            self.samples.blockSignals(False)
            selected = selected if 0 <= selected < len(baselines) else 0 if baselines else -1
            self.samples.setCurrentRow(selected)
            self.select_trace(selected)
            self.project_extras = extras
            if hasattr(self, "label_panel"):
                self.label_panel.undo_history = extras.get("labels_undo", [])
                self.label_panel.redo_history = extras.get("labels_redo", [])
                self.refresh_labels()
            self.project_path = path
            self.saved_signature = self.project_signature()
            self.project_changed()
            self.statusBar().showMessage(f"Opened {path.name} · embedded source data")

        self.project_job(lambda cancel: load_project(path, cancel), opened)
