"""Project library editing/import/export and manually reviewed tentative matches."""

from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chromakit.annotations.labels import make_label, result_key
from chromakit.compounds.library import (
    Compound,
    library_bytes,
    library_key,
    match_peaks,
    read_library,
    validate,
)
from chromakit.export.figures import atomic_bytes
from chromakit.ui.calibration_dialog import candidates
from chromakit.ui.peak_panel import spin


class MatchDialog(QDialog):
    def __init__(self, window, compounds):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Review retention-window matches")
        self.resize(1150, 650)
        self.proposals = []
        root = QVBoxLayout(self)
        note = QLabel(
            "Retention matching suggests candidates, not confirmed identity. Review each row; "
            "ambiguous matches are unchecked. Chosen assignments are added as tentative labels."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Apply", "Trace", "Origin/peak", "Retention", "Compound choice", "Review"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        root.addWidget(self.table)
        groups = {}
        for t, o, r, p in candidates(window):
            groups.setdefault((t.id, o), (t, o, r, []))[3].append(p)
        for trace, origin, result, peaks in groups.values():
            try:
                matches = match_peaks(trace, peaks, compounds)
            except ValueError:
                continue
            for peak, choices, ambiguous in matches:
                row = len(self.proposals)
                self.proposals.append((trace, origin, result, peak, choices))
                self.table.insertRow(row)
                check = QTableWidgetItem("")
                check.setCheckState(Qt.CheckState.Unchecked if ambiguous else Qt.CheckState.Checked)
                self.table.setItem(row, 0, check)
                for col, value in enumerate(
                    [
                        trace.name,
                        f"{origin} · {peak.id}",
                        f"{peak.retention_time:.7g} {trace.time_unit}",
                    ],
                    1,
                ):
                    self.table.setItem(row, col, QTableWidgetItem(value))
                choice = QComboBox()
                choice.addItems(
                    [
                        f"{c.name} · {c.start:g}–{c.end:g} {c.time_unit} · {c.id[:8]}"
                        for c in choices
                    ]
                )
                self.table.setCellWidget(row, 4, choice)
                self.table.setItem(
                    row,
                    5,
                    QTableWidgetItem(
                        "AMBIGUOUS — select after review"
                        if ambiguous
                        else "Unique retention candidate — review"
                    ),
                )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        apply = QPushButton("Apply checked tentative labels")
        apply.clicked.connect(self.apply)
        root.addWidget(apply)
        self.message = QLabel(f"{len(self.proposals)} candidate matches.")
        root.addWidget(self.message)

    def apply(self):
        panel = self.window.label_panel
        panel.save_history()
        count = 0
        for row, (trace, origin, result, peak, choices) in enumerate(self.proposals):
            if self.table.item(row, 0).checkState() != Qt.CheckState.Checked:
                continue
            compound = choices[self.table.cellWidget(row, 4).currentIndex()]
            i = next(i for i, t in enumerate(self.window.traces) if t.id == trace.id)
            entries = self.window.project_extras.setdefault("labels", {}).setdefault(trace.id, [])
            if any(
                label.get("compound_id") == compound.id
                and label.get("result_key") == result_key(result)
                and label["peak_id"] == peak.id
                for label in entries
            ):
                continue
            label = make_label(
                trace,
                self.window.baseline_states[i].applied,
                result,
                peak,
                compound.name,
                "Tentative",
                origin,
            )
            label.update(compound_id=compound.id, library_key=library_key(compound))
            entries.append(label)
            count += 1
        panel.refresh()
        panel.changed.emit()
        self.message.setText(f"{count} tentative assignments added. Review/confirm them in Labels.")


class LibraryDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Compound library")
        self.resize(1100, 700)
        root = QHBoxLayout(self)
        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.name = QLineEdit()
        self.aliases = QLineEdit()
        self.formula = QLineEdit()
        self.start = spin(-1e12, 1e12, 0)
        self.end = spin(-1e12, 1e12, 1)
        self.unit = QComboBox()
        self.unit.addItems(["min", "s", "h"])
        self.detector = QComboBox()
        self.detector.addItems(["Any", "UV", "RID", "PAD"])
        for text, widget in [
            ("Name", self.name),
            ("Aliases (; separated)", self.aliases),
            ("Formula", self.formula),
            ("Retention start", self.start),
            ("Retention end", self.end),
            ("Time unit", self.unit),
            ("Detector rule", self.detector),
        ]:
            form.addRow(text, widget)
        left.addLayout(form)
        for text, callback in [
            ("Add compound", self.add),
            ("Update selected compound", self.update),
            ("Remove selected compound", self.remove),
            ("Import library…", self.import_file),
            ("Export library…", self.export),
            ("Review retention matches…", self.match),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            left.addWidget(button)
        self.message = QLabel(
            "Libraries use stable IDs and known-unit retention windows. "
            "They are saved with the project or can be exchanged as CSV/JSON. "
            "Library edits flag linked assignments for review."
        )
        self.message.setWordWrap(True)
        left.addWidget(self.message)
        left.addStretch()
        root.addWidget(left_scroll, 1)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Aliases", "Formula", "Start", "End", "Unit", "Detector"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.cellClicked.connect(self.select)
        root.addWidget(self.table, 2)
        self.refresh()

    def entries(self):
        return self.window.project_extras.setdefault("compound_library", [])

    def compounds(self):
        return tuple(
            Compound(**dict(c, aliases=tuple(c.get("aliases", ())))) for c in self.entries()
        )

    def value(self, identifier):
        return Compound(
            identifier,
            self.name.text().strip(),
            self.start.value(),
            self.end.value(),
            self.unit.currentText(),
            tuple(alias.strip() for alias in self.aliases.text().split(";") if alias.strip()),
            self.formula.text(),
            "" if self.detector.currentText() == "Any" else self.detector.currentText(),
        )

    def refresh(self):
        self.table.setRowCount(len(self.entries()))
        for row, c in enumerate(self.compounds()):
            for col, value in enumerate(
                [
                    c.name,
                    "; ".join(c.aliases),
                    c.formula,
                    c.start,
                    c.end,
                    c.time_unit,
                    c.detector or "Any",
                ]
            ):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.window.refresh_labels()
        self.window.project_changed()

    def select(self, row, _column):
        c = self.compounds()[row]
        self.name.setText(c.name)
        self.aliases.setText("; ".join(c.aliases))
        self.formula.setText(c.formula)
        self.start.setValue(c.start)
        self.end.setValue(c.end)
        self.unit.setCurrentText(c.time_unit)
        self.detector.setCurrentText(c.detector or "Any")

    def add(self):
        try:
            c = self.value(uuid4().hex)
            validate((*self.compounds(), c))
            self.entries().append(asdict(c))
            self.refresh()
        except ValueError as error:
            self.message.setText(str(error))

    def update(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.entries()):
            return
        try:
            c = self.value(self.entries()[row]["id"])
            proposed = list(self.compounds())
            proposed[row] = c
            validate(proposed)
            self.entries()[row] = asdict(c)
            self.refresh()
        except ValueError as error:
            self.message.setText(str(error))

    def remove(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries()):
            self.entries().pop(row)
            self.refresh()

    def import_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import compound library", "", "Library (*.json *.csv)"
        )
        if not filename:
            return
        try:
            path = Path(filename)
            compounds = read_library(path.read_bytes(), path.suffix.lstrip("."))
            if (
                self.entries()
                and QMessageBox.question(
                    self,
                    "Replace library?",
                    "Replace the current project library? Linked assignments will require review.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            self.window.project_extras["compound_library"] = [asdict(c) for c in compounds]
            self.refresh()
        except (OSError, ValueError) as error:
            self.message.setText(str(error))

    def export(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export library", "compounds.json", "JSON (*.json);;CSV (*.csv)"
        )
        if filename:
            try:
                path = Path(filename)
                atomic_bytes(path, library_bytes(self.compounds(), path.suffix.lstrip(".")))
                self.message.setText("Exported " + path.name)
            except (OSError, ValueError) as error:
                self.message.setText(str(error))

    def match(self):
        MatchDialog(self.window, self.compounds()).exec()
