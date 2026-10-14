"""Inspect repeated starting guesses, area ranges and residuals without accepting a new fit."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from chromakit.analysis.deconvolution import Component, Parameter, curves
from chromakit.analysis.stability import analyze_stability, fit_key
from chromakit.export.figures import COLORS, atomic_bytes
from chromakit.export.stability import stability_bytes
from chromakit.ui.file_helpers import choose_output
from chromakit.ui.fit_tasks import FitController
from chromakit.ui.peak_panel import spin


class StabilityDialog(QDialog):
    def __init__(self, window, state):
        super().__init__(window)
        self.window, self.state = window, state
        self.reference = state.result
        self.report = None
        self.setWindowTitle("Fit stability · repeated starting guesses")
        self.resize(1250, 820)
        self.controller = FitController(self)
        self.controller.live.connect(
            lambda p: self.message.setText(f"Completed start {p[0]} / {p[1]}")
        )
        self.controller.succeeded.connect(self.ready)
        self.controller.failed.connect(self.failed)
        root = QVBoxLayout(self)
        note = QLabel(
            "Repeat fits with perturbed starting guesses using the accepted count, shapes, "
            "bounds and locks. Area spread tests sensitivity; it is not a confidence interval. "
            "Your accepted fit stays unchanged."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        self.repeats = QSpinBox()
        self.repeats.setRange(3, 30)
        self.repeats.setValue(12)
        self.spread = spin(0.05, 2, 0.5)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(1729)
        self.tolerance = spin(0, 100, 5)
        for name, field in [
            ("Repeated starts", self.repeats),
            ("Starting perturbation", self.spread),
            ("Seed", self.seed),
            ("Comparable objective tolerance (%)", self.tolerance),
        ]:
            form.addRow(name, field)
        root.addLayout(form)
        actions = QHBoxLayout()
        self.run_button = QPushButton("Analyze stability")
        self.run_button.clicked.connect(self.run)
        cancel = QPushButton("Cancel analysis")
        cancel.clicked.connect(self.cancel)
        export = QPushButton("Export report…")
        export.clicked.connect(self.export)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        for button in [self.run_button, cancel, export, close]:
            actions.addWidget(button)
        root.addLayout(actions)
        self.message = QLabel("Accept a current fit before running stability analysis.")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        self.summary = QTableWidget(0, 7)
        self.summary.setHorizontalHeaderLabels(
            [
                "Component",
                "Comparable\nstarts",
                "Accepted area",
                "Area min",
                "Area max",
                "Area range\n(%)",
                "Window area\nmin…max",
            ]
        )
        self.summary.setMaximumHeight(145)
        self.summary.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.summary)
        self.attempts = QTableWidget(0, 5)
        self.attempts.setHorizontalHeaderLabels(
            ["Start", "Converged", "Comparable", "RMSE", "Objective"]
        )
        self.attempts.setMaximumHeight(130)
        self.attempts.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.attempts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.attempts.cellClicked.connect(self.show_attempt)
        root.addWidget(self.attempts)
        self.plot = pg.PlotWidget(background="white")
        self.plot.addLegend()
        self.residual = pg.PlotWidget(background="white")
        self.residual.setXLink(self.plot)
        root.addWidget(self.plot, 2)
        root.addWidget(self.residual, 1)
        saved = window.project_extras.get("fit_stability", {}).get(state.baseline_state.trace.id)
        if saved and self.reference and saved.get("fit_key") == fit_key(self.reference):
            self.ready(saved)
        self.run_button.setEnabled(state.valid(self.reference))

    def run(self):
        if not self.state.valid(self.reference):
            return
        repeats, spread, seed, tolerance = (
            self.repeats.value(),
            self.spread.value(),
            self.seed.value(),
            self.tolerance.value() / 100,
        )
        trace, baseline = self.state.baseline_state.trace, self.state.baseline_state.applied
        self.run_button.setEnabled(False)
        self.report = None
        self.summary.setRowCount(0)
        self.attempts.setRowCount(0)
        self.message.setText("Running repeated fits…")
        self.controller.request_operation(
            lambda cancel, update: analyze_stability(
                trace,
                baseline,
                self.reference,
                repeats,
                spread,
                seed,
                tolerance,
                cancel,
                lambda done, total: update((done, total)),
            )
        )

    def cancel(self):
        self.controller.cancel()
        self.run_button.setEnabled(self.state.valid(self.reference))
        self.message.setText("Cancelled. Partial attempts are not a completed stability report.")

    def failed(self, message):
        self.run_button.setEnabled(self.state.valid(self.reference))
        self.message.setText(message)

    def ready(self, report):
        if not self.state.valid(self.reference):
            return
        self.report = report
        self.run_button.setEnabled(True)
        self.window.project_extras.setdefault("fit_stability", {})[report["trace_id"]] = report
        self.window.project_changed()
        self.message.setText(
            f"{report['comparable_count']} / {report['repeats']} comparable fits; "
            f"{report['converged_count']} converged · "
            f"Areas: {report['signal_unit']} × {report['time_unit']}.\n"
            + "\n".join(report["warnings"])
        )
        self.summary.setRowCount(len(report["components"]))
        for row, item in enumerate(report["components"]):
            values = [
                item["id"],
                item["count"],
                item["accepted_area"],
                item["area"]["min"],
                item["area"]["max"],
                item["area"]["relative_range_percent"],
                (
                    f"{item['window_area']['min']:.6g} … {item['window_area']['max']:.6g}"
                    if item["window_area"]["min"] is not None
                    else "—"
                ),
            ]
            for column, value in enumerate(values):
                self.summary.setItem(
                    row,
                    column,
                    QTableWidgetItem(
                        f"{value:.6g}"
                        if isinstance(value, float)
                        else "—"
                        if value is None
                        else str(value)
                    ),
                )
        self.attempts.setRowCount(len(report["runs"]))
        for row, run in enumerate(report["runs"]):
            for column, key in enumerate(["index", "converged", "comparable", "rmse", "cost"]):
                value = run[key]
                self.attempts.setItem(
                    row,
                    column,
                    QTableWidgetItem(f"{value:.6g}" if isinstance(value, float) else str(value)),
                )
        self.show_attempt(0, 0)

    def show_attempt(self, row, _column):
        if not self.report:
            return
        run = self.report["runs"][row]
        self.plot.clear()
        self.residual.clear()
        if not run["fitted"]:
            return
        components = tuple(
            Component(
                **dict(
                    c, **{name: Parameter(**c[name]) for name in ["area", "center", "sigma", "tau"]}
                )
            )
            for c in run["fitted"]
        )
        parts = curves(self.reference.x, components)
        total = sum(parts, np.zeros_like(self.reference.x))
        self.plot.plot(
            self.reference.x, self.reference.observed, pen="#84939B", name="Corrected signal"
        )
        self.plot.plot(
            self.reference.x, total, pen=pg.mkPen("#24343F", width=2), name=f"Start {row + 1}"
        )
        for peak, y, color in zip(run["peaks"], parts, COLORS, strict=False):
            self.plot.plot(self.reference.x, y, pen=color, name=peak["id"])
        self.residual.plot(self.reference.x, self.reference.observed - total, pen="#9271C6")
        self.plot.setLabel("left", "Signal", units=self.reference.signal_unit)
        self.residual.setLabel("left", "Residual", units=self.reference.signal_unit)
        self.residual.setLabel("bottom", "Time", units=self.reference.time_unit)

    def export(self):
        if not self.report or not self.state.valid(self.reference):
            return
        try:
            path = choose_output(
                self,
                "Export stability report",
                "fit-stability.json",
                "JSON (*.json);;CSV (*.csv)",
                {"json", "csv"},
            )
            if not path:
                return
            data = stability_bytes(self.report, path.suffix.lower()[1:])
            atomic_bytes(path, data)
            self.message.setText(f"Saved {path.name}")
        except (OSError, ValueError) as error:
            self.message.setText(str(error))

    def done(self, result):
        self.controller.shutdown()
        super().done(result)
