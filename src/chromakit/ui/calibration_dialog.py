"""Reviewed external standards, residuals and explicitly ranged quantification."""

import csv
import io
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chromakit.analysis.calibration import (
    CalibrationPoint,
    CalibrationRecipe,
    CalibrationResult,
    calibration_key,
    fit_calibration,
    quantify,
)
from chromakit.annotations.labels import result_key
from chromakit.export.figures import FigureSpec, atomic_bytes, calibration_figure_bytes
from chromakit.importers.text import ImportCancelled
from chromakit.ui.file_helpers import choose_output
from chromakit.ui.operation_tasks import OperationController
from chromakit.ui.peak_panel import spin


def candidates(window):
    output = []
    for i, trace in enumerate(window.traces):
        for origin, state in [
            ("Measured peaks", window.peak_states[i]),
            ("Fitted components", window.fit_states[i]),
        ]:
            current = state.current if origin == "Measured peaks" else state.valid(state.result)
            if current:
                for peak in state.result.peaks:
                    output.append((trace, origin, state.result, peak))
    return output


class CalibrationDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("External-standard calibration")
        self.resize(1200, 820)
        self.controller = OperationController(self)
        self.controller.succeeded.connect(
            lambda path: self.message.setText("Exported " + path.name)
        )
        self.controller.failed.connect(lambda message: self.message.setText(message))
        self.result = None
        self.sources = candidates(window)
        root = QHBoxLayout(self)
        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_widget)
        self.compound = QComboBox()
        self.compound.setEditable(True)
        self.compound.addItems(list(window.project_extras.get("calibrations", {})))
        if not self.compound.count():
            self.compound.addItem("New compound")
        left.addWidget(QLabel("Compound calibration"))
        left.addWidget(self.compound)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.source = QComboBox()
        self.source.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.source.setMinimumContentsLength(15)
        self.source.addItems(
            [f"{t.name} · {o} · {p.id} · {p.retention_time:.6g}" for t, o, _, p in self.sources]
        )
        form.addRow("Standard/sample signal", self.source)
        self.response_metric = QComboBox()
        self.response_metric.addItems(["Area", "Height"])
        form.addRow("Response", self.response_metric)
        self.concentration = spin(0, 1e12, 1)
        self.unit = QLineEdit("mg/L")
        form.addRow("Known concentration", self.concentration)
        form.addRow("Concentration unit", self.unit)
        self.weight = QComboBox()
        self.weight.addItems(["none", "1/x", "1/x²"])
        form.addRow("Weighting", self.weight)
        self.intercept = QCheckBox("Fit intercept")
        self.intercept.setChecked(True)
        form.addRow(self.intercept)
        self.reason = QLineEdit()
        form.addRow("Exclusion reason", self.reason)
        self.dilution = spin(0.000001, 1e12, 1)
        form.addRow("Sample dilution factor", self.dilution)
        self.extrapolate = QCheckBox("Allow extrapolation (flagged)")
        form.addRow(self.extrapolate)
        left.addLayout(form)
        for text, callback in [
            ("Add standard", self.add_standard),
            ("Exclude/include selected standard", self.exclude),
            ("Remove selected standard", self.remove),
            ("Update selected concentration", self.update_concentration),
            ("Fit calibration", self.fit),
            ("Quantify selected sample signal", self.quantify),
            ("Export calibration table…", self.export),
            ("Export calibration figure…", self.export_figure),
            ("Export concentrations…", self.export_quantifications),
        ]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            left.addWidget(button)
        self.message = QLabel(
            "Add standards with known concentrations. Replicate injections remain separate; "
            "matching and exclusions require review."
        )
        self.message.setWordWrap(True)
        left.addWidget(self.message)
        left.addStretch()
        root.addWidget(left_scroll, 1)
        right = QVBoxLayout()
        self.plot = pg.PlotWidget(background="white")
        self.residual = pg.PlotWidget(background="white")
        self.residual.setMaximumHeight(160)
        right.addWidget(self.plot, 2)
        right.addWidget(self.residual, 1)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Sample",
                "Concentration",
                "Response",
                "Residual",
                "Back-calculated",
                "Exclusion",
                "Source review",
            ]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.select_standard)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        right.addWidget(self.table, 1)
        root.addLayout(right, 2)
        self.compound.currentTextChanged.connect(self.load)
        self.weight.currentTextChanged.connect(self.invalidate)
        self.intercept.toggled.connect(self.invalidate)
        self.load()

    def entry(self):
        return self.window.project_extras.setdefault("calibrations", {}).setdefault(
            self.compound.currentText().strip() or "New compound",
            {"points": [], "recipe": {}, "result": None},
        )

    def points(self):
        return tuple(CalibrationPoint(**p) for p in self.entry()["points"])

    def valid_sources(self):
        active = {(t.id, o, p.id): result_key(r) for t, o, r, p in candidates(self.window)}
        return all(
            p.excluded or active.get((p.trace_id, p.origin, p.peak_id)) == p.result_key
            for p in self.points()
        )

    def load(self, *_):
        self.weight.blockSignals(True)
        self.intercept.blockSignals(True)
        recipe = self.entry().get("recipe", {})
        self.weight.setCurrentText(recipe.get("weighting", "none"))
        self.intercept.setChecked(recipe.get("fit_intercept", True))
        self.weight.blockSignals(False)
        self.intercept.blockSignals(False)
        self.result = None
        self.refresh()
        saved = self.entry()["result"]
        if saved and self.valid_sources():
            recipe = CalibrationRecipe(**saved["recipe"])
            if saved["input_key"] == calibration_key(self.points(), recipe):
                self.result = CalibrationResult(
                    **dict(
                        saved,
                        recipe=recipe,
                        points=tuple(CalibrationPoint(**p) for p in saved["points"]),
                        diagnostics=tuple(saved["diagnostics"]),
                        warnings=tuple(saved["warnings"]),
                    )
                )
                self.display_result()
        self.response_metric.setCurrentText(self.entry().get("response_metric", "Area"))
        if self.entry()["points"]:
            self.unit.setText(self.entry()["points"][0]["concentration_unit"])

    def invalidate(self, *_):
        self.result = None
        self.entry()["result"] = None
        self.entry()["recipe"] = {
            "weighting": self.weight.currentText(),
            "fit_intercept": self.intercept.isChecked(),
        }
        self.plot.clear()
        self.residual.clear()
        self.refresh()
        self.window.project_changed()

    def add_standard(self):
        if not 0 <= self.source.currentIndex() < len(self.sources):
            return
        trace, origin, result, peak = self.sources[self.source.currentIndex()]
        if any(p.trace_id == trace.id for p in self.points()):
            self.message.setText(
                "This injection is already a standard for this compound. "
                "Use a separate trace for another standard or replicate."
            )
            return
        if self.points() and (
            self.entry().get("response_origin", origin) != origin
            or self.entry().get("detector", trace.detector) != trace.detector
        ):
            self.message.setText(
                "Use the same measured/fitted origin and detector for all standards."
            )
            return
        metric = self.response_metric.currentText()
        if trace.signal_unit.strip().casefold() in {"", "unknown", "unspecified"} or (
            metric == "Area" and trace.time_unit == "unknown"
        ):
            self.message.setText(
                "Confirm signal units and, for areas, time units before calibration."
            )
            return
        point = CalibrationPoint(
            uuid4().hex,
            trace.id,
            peak.id,
            origin,
            result_key(result),
            self.concentration.value(),
            peak.area if metric == "Area" else peak.height,
            self.unit.text().strip(),
            f"{trace.signal_unit} × {trace.time_unit}" if metric == "Area" else trace.signal_unit,
            sample=trace.name,
        )
        if not self.points():
            self.entry().update(
                response_metric=metric, response_origin=origin, detector=trace.detector
            )
        if self.entry()["response_metric"] != metric:
            self.message.setText(
                "Use the same response definition for all standards in this calibration."
            )
            return
        self.entry()["points"].append(asdict(point))
        self.invalidate()

    def select_standard(self, row, _column):
        if 0 <= row < len(self.entry()["points"]):
            point = self.entry()["points"][row]
            self.concentration.setValue(point["concentration"])
            self.unit.setText(point["concentration_unit"])
            self.reason.setText(point["reason"])

    def update_concentration(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entry()["points"]):
            self.entry()["points"][row].update(
                concentration=self.concentration.value(),
                concentration_unit=self.unit.text().strip(),
            )
            self.invalidate()

    def exclude(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entry()["points"]):
            point = self.entry()["points"][row]
            if not point["excluded"] and not self.reason.text().strip():
                self.message.setText("Enter an exclusion reason first.")
                return
            point["excluded"] = not point["excluded"]
            point["reason"] = self.reason.text().strip() if point["excluded"] else ""
            self.invalidate()

    def remove(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entry()["points"]):
            self.entry()["points"].pop(row)
            self.invalidate()

    def refresh(self):
        points = self.points()
        self.table.setRowCount(len(points))
        active = {(t.id, o, p.id): result_key(r) for t, o, r, p in candidates(self.window)}
        for row, p in enumerate(points):
            diag = self.result.diagnostics[row] if self.result else {}
            values = [
                p.sample,
                p.concentration,
                p.response,
                diag.get("residual", "—"),
                diag.get("back_calculated", "—"),
                p.reason if p.excluded else "",
                "Current"
                if active.get((p.trace_id, p.origin, p.peak_id)) == p.result_key
                else "STALE",
            ]
            for col, value in enumerate(values):
                self.table.setItem(
                    row,
                    col,
                    QTableWidgetItem(f"{value:.7g}" if isinstance(value, float) else str(value)),
                )

    def fit(self):
        try:
            if not self.valid_sources():
                raise ValueError(
                    "Included standards reference stale/missing analyses. "
                    "Remove and add reviewed current signals."
                )
            recipe = CalibrationRecipe(self.weight.currentText(), self.intercept.isChecked())
            result = fit_calibration(self.points(), recipe)
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.result = result
        self.entry()["recipe"] = asdict(recipe)
        self.entry()["result"] = asdict(result)
        self.display_result()
        self.window.project_changed()

    def display_result(self):
        result = self.result
        self.plot.clear()
        self.residual.clear()
        included = [p for p in result.points if not p.excluded]
        self.plot.plot(
            [p.concentration for p in included],
            [p.response for p in included],
            pen=None,
            symbol="o",
            symbolBrush="#137F90",
        )
        x = np.linspace(result.minimum, result.maximum, 100)
        self.plot.plot(x, result.slope * x + result.intercept, pen=pg.mkPen("#D79622", width=2))
        self.plot.setLabel("bottom", "Concentration", units=result.concentration_unit)
        self.plot.setLabel("left", "Response", units=result.response_unit)
        diag = [d for d in result.diagnostics if not d["excluded"]]
        self.residual.plot(
            [d["concentration"] for d in diag], [d["residual"] for d in diag], pen=None, symbol="o"
        )
        self.residual.addItem(pg.InfiniteLine(pos=0, angle=0))
        self.residual.setLabel("left", "Residual")
        self.message.setText(
            f"Response = {result.slope:.7g} × concentration + {result.intercept:.7g}\n"
            f"R² = {result.r_squared}\nRMSE = {result.rmse:.6g} {result.response_unit}\n"
            f"Slope SE = {result.slope_se}\n"
            f"Range {result.minimum:g}–{result.maximum:g} {result.concentration_unit}\n\n"
            + "\n".join(result.warnings)
        )
        self.refresh()

    def quantify(self):
        try:
            if (
                not self.result
                or not self.valid_sources()
                or self.result.input_key != calibration_key(self.points(), self.result.recipe)
            ):
                raise ValueError("Fit a current calibration before quantifying.")
            if not 0 <= self.source.currentIndex() < len(self.sources):
                return
            trace, origin, result, peak = self.sources[self.source.currentIndex()]
            if (
                self.entry().get("response_origin", origin) != origin
                or self.entry().get("detector", trace.detector) != trace.detector
            ):
                raise ValueError("Sample response origin and detector must match the calibration.")
            metric = self.entry().get("response_metric", "Area")
            response = peak.area if metric == "Area" else peak.height
            unit = (
                f"{trace.signal_unit} × {trace.time_unit}"
                if metric == "Area"
                else trace.signal_unit
            )
            quantified = quantify(
                response, unit, self.result, self.dilution.value(), self.extrapolate.isChecked()
            )
            quantified.update(
                trace_id=trace.id,
                origin=origin,
                peak_id=peak.id,
                result_key=result_key(result),
                compound=self.compound.currentText(),
            )
            self.window.project_extras.setdefault("quantifications", []).append(quantified)
            self.message.setText(
                "Outside calibration range; concentration withheld."
                if quantified["concentration"] is None
                else f"{quantified['concentration']:.7g} {quantified['concentration_unit']}"
                + (" · EXTRAPOLATED" if quantified["outside_range"] else "")
            )
            self.window.project_changed()
        except ValueError as error:
            self.message.setText(str(error))

    def export(self):
        if not self.result or not self.valid_sources():
            self.message.setText("Fit a current calibration first.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export calibration", "calibration.json", "JSON (*.json);;CSV (*.csv)"
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() == ".csv":
            stream = io.StringIO()
            rows = [
                dict(
                    d,
                    concentration_unit=d.get("concentration_unit", self.result.concentration_unit),
                    response_unit=d.get("response_unit", self.result.response_unit),
                    calibration_key=self.result.input_key,
                )
                for d in self.result.diagnostics
            ]
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            payload = stream.getvalue().encode("utf-8-sig")
        else:
            payload = json.dumps(asdict(self.result), allow_nan=False, indent=2).encode()
        try:
            atomic_bytes(path, payload)
            self.message.setText("Exported " + path.name)
        except OSError as error:
            self.message.setText(str(error))

    def export_figure(self):
        if not self.result or not self.valid_sources():
            self.message.setText("Fit a current calibration first.")
            return
        try:
            path = choose_output(
                self,
                "Export calibration figure",
                "calibration.png",
                "PNG (*.png);;TIFF (*.tiff);;PDF (*.pdf);;SVG (*.svg)",
                ["png", "tiff", "pdf", "svg"],
            )
            if path is None:
                return
            settings = dict(self.window.project_extras.get("figure_spec", {}))
            settings.update(x_limits=None, title=self.compound.currentText())
            spec = FigureSpec(**settings)
            result = self.result
            title = self.compound.currentText()

            def operation(cancel):
                data = calibration_figure_bytes(
                    result, spec, path.suffix.lower().lstrip("."), title
                )
                if cancel():
                    raise ImportCancelled()
                return atomic_bytes(path, data)

            self.message.setText("Rendering calibration figure…")
            self.controller.request_operation(operation)
        except (OSError, ValueError) as error:
            self.message.setText(str(error))

    def export_quantifications(self):
        rows = []
        active = {(t.id, o, p.id): result_key(r) for t, o, r, p in candidates(self.window)}
        calibrations = self.window.project_extras.get("calibrations", {})
        for record in self.window.project_extras.get("quantifications", []):
            calibration = calibrations.get(record["compound"], {}).get("result")
            standards_current = bool(calibration) and all(
                p["excluded"]
                or active.get((p["trace_id"], p["origin"], p["peak_id"])) == p["result_key"]
                for p in calibration["points"]
            )
            stale = (
                not standards_current
                or active.get((record["trace_id"], record["origin"], record["peak_id"]))
                != record["result_key"]
                or not calibration
                or calibration["input_key"] != record["calibration_key"]
            )
            rows.append(
                dict(
                    record,
                    stale=bool(stale),
                    concentration=None if stale else record["concentration"],
                )
            )
        try:
            path = choose_output(
                self,
                "Export concentrations",
                "concentrations.json",
                "JSON (*.json);;CSV (*.csv)",
                ["json", "csv"],
            )
            if path is None:
                return
            if path.suffix.lower() == ".json":
                payload = json.dumps(rows, indent=2, allow_nan=False).encode()
            else:
                stream = io.StringIO()
                writer = csv.DictWriter(
                    stream,
                    fieldnames=list(rows[0])
                    if rows
                    else ["compound", "concentration", "concentration_unit", "stale"],
                )
                writer.writeheader()
                writer.writerows(rows)
                payload = stream.getvalue().encode("utf-8-sig")
            atomic_bytes(path, payload)
            self.message.setText("Exported " + path.name)
        except (OSError, ValueError) as error:
            self.message.setText(str(error))

    def done(self, result):
        self.controller.shutdown()
        super().done(result)
