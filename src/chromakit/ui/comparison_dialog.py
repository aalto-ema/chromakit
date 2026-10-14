"""Select, color, normalize and compare project chromatograms without modifying them."""

from dataclasses import asdict

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from chromakit.analysis.comparison import compare
from chromakit.export.comparison import comparison_bytes, comparison_csv
from chromakit.export.figures import COLORS, FigureSpec, atomic_bytes
from chromakit.ui.file_helpers import choose_output
from chromakit.ui.operation_tasks import OperationController
from chromakit.ui.peak_panel import spin


class ComparisonDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Compare chromatograms")
        self.resize(1250, 800)
        self.comparison_result = None
        self.controller = OperationController(self)
        self.controller.succeeded.connect(self.ready)
        self.controller.failed.connect(self.failed)
        self.export_controller = OperationController(self)
        self.export_controller.failed.connect(self.failed)
        self.export_controller.succeeded.connect(
            lambda path: self.message.setText(f"Saved {path.name}")
        )
        root = QHBoxLayout(self)
        controls = QVBoxLayout()
        note = QLabel(
            "Select at least two traces. Double-click a color to change it. "
            "Normalization affects this comparison only; source data stay unchanged."
        )
        note.setWordWrap(True)
        controls.addWidget(note)
        saved = window.project_extras.get("comparison", {})
        self.table = QTableWidget(len(window.traces), 3)
        self.table.setHorizontalHeaderLabels(["Show", "Chromatogram", "Color"])
        colors = saved.get("colors", {})
        for row, trace in enumerate(window.traces):
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if trace.id in saved.get("selected", [t.id for t in window.traces[:8]])
                else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 0, item)
            name = QTableWidgetItem(trace.name)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 1, name)
            color = QTableWidgetItem()
            value = colors.get(trace.id, COLORS[row % len(COLORS)])
            color.setData(Qt.ItemDataRole.UserRole, value)
            color.setToolTip(value + " · double-click to change")
            color.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            color.setBackground(QColor(value))
            self.table.setItem(row, 2, color)
        self.table.setColumnWidth(0, 45)
        self.table.setColumnWidth(2, 55)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumWidth(410)
        self.table.itemChanged.connect(self.refresh)
        self.table.cellDoubleClicked.connect(self.pick_color)
        controls.addWidget(self.table, 1)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Raw", "Corrected"])
        self.normalization = QComboBox()
        self.normalization.addItems(["None", "Peak magnitude", "Absolute area"])
        self.reference = QComboBox()
        for trace in window.traces:
            self.reference.addItem(trace.name, trace.id)
        self.time_unit = QComboBox()
        self.time_unit.addItems(["s", "min", "h", "unknown"])
        self.mode.setCurrentText(saved.get("mode", "Raw"))
        self.normalization.setCurrentText(saved.get("normalization", "None"))
        self.time_unit.setCurrentText(saved.get("time_unit", "min"))
        index = self.reference.findData(saved.get("reference_id"))
        if index >= 0:
            self.reference.setCurrentIndex(index)
        for label, widget in [
            ("Signal", self.mode),
            ("Normalize", self.normalization),
            ("Reference", self.reference),
            ("Time unit", self.time_unit),
        ]:
            form.addRow(label, widget)
            widget.currentIndexChanged.connect(self.refresh)
        controls.addLayout(form)
        spec = FigureSpec(**window.project_extras.get("figure_spec", {}))
        self.figure_width = spin(1, 20000, spec.width)
        self.figure_height = spin(1, 20000, spec.height)
        self.unit = QComboBox()
        self.unit.addItems(["mm", "in", "px"])
        self.unit.setCurrentText(spec.unit)
        self.dpi = spin(36, 1200, spec.dpi)
        self.transparent = QCheckBox("Transparent background")
        self.transparent.setChecked(spec.transparent)
        for label, widget in [
            ("Figure width", self.figure_width),
            ("Height", self.figure_height),
            ("Size unit", self.unit),
            ("DPI", self.dpi),
        ]:
            form.addRow(label, widget)
        form.addRow(self.transparent)
        export = QPushButton("Export comparison figure…")
        export.clicked.connect(self.export_figure)
        csv = QPushButton("Export comparison data…")
        csv.clicked.connect(self.export_data)
        controls.addWidget(export)
        controls.addWidget(csv)
        self.message = QLabel()
        self.message.setWordWrap(True)
        controls.addWidget(self.message)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        root.addLayout(controls)
        plots = QVBoxLayout()
        self.plot = pg.PlotWidget(background="white")
        self.plot.addLegend()
        self.difference = pg.PlotWidget(background="white")
        self.difference.setXLink(self.plot)
        plots.addWidget(self.plot, 3)
        plots.addWidget(self.difference, 1)
        root.addLayout(plots, 2)
        self.refresh()

    def pick_color(self, row, column):
        if column != 2:
            return
        item = self.table.item(row, column)
        color = QColorDialog.getColor(
            QColor(item.data(Qt.ItemDataRole.UserRole)), self, "Trace color"
        )
        if color.isValid():
            self.table.blockSignals(True)
            item.setData(Qt.ItemDataRole.UserRole, color.name())
            item.setToolTip(color.name() + " · double-click to change")
            item.setBackground(color)
            self.table.blockSignals(False)
            self.refresh()

    def refresh(self, *_):
        self.controller.cancel()
        self.comparison_result = None
        self.plot.clear()
        self.difference.clear()
        rows = [
            r
            for r in range(self.table.rowCount())
            if self.table.item(r, 0).checkState() == Qt.CheckState.Checked
        ]
        if len(rows) > 30:
            self.message.setText("Select at most 30 chromatograms for one comparison.")
            return
        traces = [self.window.traces[r] for r in rows]
        settings = dict(
            selected=[t.id for t in traces],
            colors={
                t.id: self.table.item(r, 2).data(Qt.ItemDataRole.UserRole)
                for r, t in zip(rows, traces, strict=True)
            },
            mode=self.mode.currentText(),
            normalization=self.normalization.currentText(),
            reference_id=self.reference.currentData(),
            time_unit=self.time_unit.currentText(),
        )
        self.window.project_extras["comparison"] = settings
        self.window.project_changed()
        baselines = [self.window.baseline_states[r].applied for r in rows]
        colors = [settings["colors"][t.id] for t in traces]
        self.message.setText("Preparing comparison…")
        self.controller.request_operation(
            lambda cancel: compare(
                traces,
                baselines,
                colors,
                settings["reference_id"],
                settings["mode"],
                settings["normalization"],
                settings["time_unit"],
                cancel,
            )
        )

    def ready(self, result):
        self.comparison_result = result
        for series in result.series:
            self.plot.plot(
                series.x,
                series.y,
                connect=series.connect,
                pen=pg.mkPen(series.color, width=2),
                name=series.name,
            )
            self.difference.plot(
                series.x,
                series.difference,
                connect=series.difference_connect,
                pen=pg.mkPen(series.color, width=1.5),
            )
        self.plot.setLabel("left", "Signal", units=result.signal_unit)
        self.difference.setLabel("left", "Difference", units=result.signal_unit)
        self.difference.setLabel("bottom", "Time", units=result.time_unit)
        self.message.setText(
            "Difference = trace − reference, sampled at each trace's coordinates. "
            "Reference interpolation stays within continuous segments; gaps remain gaps."
        )

    def failed(self, message):
        self.message.setText(message)

    def export_figure(self):
        if self.comparison_result is None:
            return
        try:
            path = choose_output(
                self,
                "Export comparison",
                "comparison.png",
                "PNG (*.png);;TIFF (*.tiff);;PDF (*.pdf);;SVG (*.svg)",
                {"png", "tiff", "pdf", "svg"},
            )
            if not path:
                return
            values = asdict(FigureSpec(**self.window.project_extras.get("figure_spec", {})))
            values.update(
                width=self.figure_width.value(),
                height=self.figure_height.value(),
                unit=self.unit.currentText(),
                dpi=int(self.dpi.value()),
                transparent=self.transparent.isChecked(),
            )
            spec = FigureSpec(**values)
            spec.inches()
            result = self.comparison_result

            def operation(cancel):
                data = comparison_bytes(result, spec, path.suffix.lower()[1:])
                from chromakit.importers.text import ImportCancelled

                if cancel():
                    raise ImportCancelled()
                return atomic_bytes(path, data)

            self.export_controller.request_operation(operation)
        except ValueError as error:
            self.failed(str(error))

    def export_data(self):
        if self.comparison_result is None:
            return
        try:
            path = choose_output(
                self, "Export comparison data", "comparison.csv", "CSV (*.csv)", {"csv"}
            )
            if path:
                result = self.comparison_result
                self.export_controller.request_operation(
                    lambda cancel: atomic_bytes(path, comparison_csv(result))
                )
        except ValueError as error:
            self.failed(str(error))

    def done(self, result):
        self.controller.shutdown()
        self.export_controller.shutdown()
        super().done(result)
