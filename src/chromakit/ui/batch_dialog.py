"""Per-file progress, cancellation and reviewed import of successful batch results."""

import csv
import io
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from chromakit.application.batch import process_batch, stored_recipe, text_recipe
from chromakit.export.figures import atomic_bytes
from chromakit.ui.operation_tasks import OperationController, OperationTask


class BatchTask(OperationTask):
    updated = Signal(int, object)

    def __init__(self, generation, operation, parent):
        super().__init__(
            generation,
            lambda cancel: operation(
                cancel, lambda outcome: self.updated.emit(generation, outcome)
            ),
            parent,
        )


class BatchController(OperationController):
    updated = Signal(object)

    def create_task(self, generation, operation, unused):
        task = BatchTask(generation, operation, self)
        task.updated.connect(self.forward)
        return task

    def forward(self, generation, outcome):
        if generation == self.generation:
            self.updated.emit(outcome)


class BatchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Batch processing · reusable active-trace recipe")
        self.resize(1100, 650)
        self.outcomes = []
        self.paths = []
        self.running = False
        self.added = set()
        self.controller = BatchController(self)
        self.controller.updated.connect(self.progress)
        self.controller.succeeded.connect(self.batch_completed)
        self.controller.failed.connect(self.failed)
        root = QVBoxLayout(self)
        note = QLabel(
            "Uses the active text trace’s reviewed mapping/units, applied baseline recipe "
            "and peak detection settings. Optional fits reuse exact windows, shapes and bounds. "
            "Review each outcome before adding it to the project; files fail independently."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        row = QHBoxLayout()
        choose = QPushButton("Choose CSV/TSV/TXT files…")
        choose.clicked.connect(self.choose)
        row.addWidget(choose)
        self.saved_check = QCheckBox("Use saved batch recipe")
        self.saved_check.setEnabled(bool(window.project_extras.get("batch_recipe")))
        row.addWidget(self.saved_check)
        self.headers_check = QCheckBox("Require matching column names")
        self.headers_check.setChecked(True)
        row.addWidget(self.headers_check)
        self.fit_check = QCheckBox("Reuse accepted fit recipe")
        row.addWidget(self.fit_check)
        self.run_button = QPushButton("Run batch")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run)
        row.addWidget(self.run_button)
        self.cancel_button = QPushButton("Cancel remaining files")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        root.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Add", "File", "Status", "Peaks/components", "Warnings/error"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)
        add = QPushButton("Add checked results to project")
        add.clicked.connect(self.add)
        root.addWidget(add)
        export = QPushButton("Export batch summary…")
        export.clicked.connect(self.export)
        root.addWidget(export)
        self.message = QLabel("Choose files to process. Original files are never changed.")
        self.message.setWordWrap(True)
        root.addWidget(self.message)

    def choose(self):
        if self.running:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Batch chromatograms", "", "Text data (*.csv *.tsv *.txt)"
        )
        if files:
            self.paths = [Path(path) for path in files]
            self.message.setText(f"{len(files)} files selected.")

    def run(self):
        if not self.paths:
            self.failed("Choose files to process.")
            return
        try:
            if self.saved_check.isChecked():
                record = self.window.project_extras["batch_recipe"]
                options, mapping, baseline_recipe, peak_recipe, fit_recipe = stored_recipe(record)
                headers = record.get("headers")
                if self.fit_check.isChecked() and fit_recipe is None:
                    raise ValueError("The saved recipe does not contain a fit.")
                if not self.fit_check.isChecked():
                    fit_recipe = None
            else:
                if self.window.trace is None:
                    raise ValueError("Choose an active text-imported template trace.")
                i = self.window.samples.currentRow()
                baseline = self.window.baseline_states[i].applied
                if baseline is None:
                    raise ValueError("Apply a reviewed baseline to the template trace first.")
                options, mapping = text_recipe(self.window.trace)
                baseline_recipe = baseline.recipe
                peak_recipe = self.window.peak_states[i].recipe
                fitted = self.window.fit_states[i].result if self.fit_check.isChecked() else None
                if self.fit_check.isChecked() and not self.window.fit_states[i].valid(fitted):
                    raise ValueError("Accept a current template fit before batch fitting.")
                fit_recipe = fitted.recipe if fitted else None
                headers = (self.window.trace.time_column, self.window.trace.channel)
            if not self.headers_check.isChecked():
                headers = None
        except (ValueError, KeyError, TypeError) as error:
            self.failed(str(error))
            return
        self.outcomes = []
        self.table.setRowCount(0)
        self.added.clear()
        self.running = True
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        paths = tuple(self.paths)
        self.window.project_extras["batch_recipe"] = {
            "parse": asdict(options),
            "mapping": asdict(mapping),
            "baseline": asdict(baseline_recipe),
            "peaks": asdict(peak_recipe),
            "fit": asdict(fit_recipe) if fit_recipe else None,
            "headers": headers,
        }
        self.saved_check.setEnabled(True)
        self.controller.request_operation(
            lambda cancel, progress: process_batch(
                paths,
                options,
                mapping,
                baseline_recipe,
                peak_recipe,
                fit_recipe,
                cancel,
                progress,
                headers=headers,
            )
        )
        self.message.setText("Processing files…")

    def progress(self, outcome):
        from PySide6.QtCore import Qt

        row = len(self.outcomes)
        self.outcomes.append(outcome)
        self.table.insertRow(row)
        check = QTableWidgetItem("")
        check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked if outcome.trace else Qt.CheckState.Unchecked)
        self.table.setItem(row, 0, check)
        values = [
            outcome.path.name,
            outcome.status,
            f"{len(outcome.peaks.peaks) if outcome.peaks else 0}/"
            f"{len(outcome.fitted.peaks) if outcome.fitted else 0}",
            outcome.message,
        ]
        for col, value in enumerate(values, 1):
            self.table.setItem(row, col, QTableWidgetItem(value))
        self.message.setText(f"{len(self.outcomes)}/{len(self.paths)} files reviewed by worker.")

    def batch_completed(self, outcomes):
        self.running = False
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.message.setText(
            f"Completed {len(outcomes)} files. Check warnings, then add selected results."
        )

    def cancel(self):
        self.controller.cancel()
        self.running = False
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.message.setText(
            "Cancelled. Completed outcomes already shown remain available for review."
        )

    def failed(self, message):
        self.running = False
        self.run_button.setEnabled(True)
        self.message.setText(message)

    def add(self):
        from PySide6.QtCore import Qt

        if self.running:
            self.message.setText("Wait for completion or cancel before adding reviewed results.")
            return
        for row, outcome in enumerate(self.outcomes):
            if (
                row in self.added
                or not outcome.trace
                or self.table.item(row, 0).checkState() != Qt.CheckState.Checked
            ):
                continue
            self.window.add_trace(outcome.trace)
            i = len(self.window.traces) - 1
            b = self.window.baseline_states[i]
            b.applied = outcome.baseline
            b.discard()
            p = self.window.peak_states[i]
            p.recipe = outcome.peaks.recipe
            p.accept(outcome.peaks)
            f = self.window.fit_states[i]
            if outcome.fitted:
                f.recipe = outcome.fitted.recipe
                f.preview = outcome.fitted
                f.accept()
            self.added.add(row)
            self.window.select_trace(i)
        self.window.project_changed()
        self.message.setText(f"{len(self.added)} reviewed results added to project.")

    def export(self):
        if not self.outcomes:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export batch summary", "batch.csv", "CSV (*.csv)"
        )
        if not filename:
            return
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["file", "status", "message", "source_hash", "time_unit", "signal_unit"])
        for outcome in self.outcomes:
            t = outcome.trace
            writer.writerow(
                [
                    outcome.path.name,
                    outcome.status,
                    outcome.message,
                    t.source_hash if t else "",
                    t.time_unit if t else "",
                    t.signal_unit if t else "",
                ]
            )
        try:
            atomic_bytes(Path(filename), stream.getvalue().encode("utf-8-sig"))
        except OSError as error:
            self.failed(str(error))

    def done(self, result):
        self.controller.shutdown()
        super().done(result)
