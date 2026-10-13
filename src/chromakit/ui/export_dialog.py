"""Publication figure preview and accepted-result export."""

from dataclasses import asdict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chromakit.export.figures import FigureSpec, export_figure, figure_bytes
from chromakit.export.results import export_results
from chromakit.importers.text import ImportCancelled
from chromakit.ui.file_helpers import choose_output
from chromakit.ui.operation_tasks import OperationController
from chromakit.ui.peak_panel import spin


class ExportDialog(QDialog):
    def __init__(self, trace, baseline, peaks, fitted, labels, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export figures and results")
        self.resize(1000, 720)
        self.inputs = trace, baseline, fitted, labels
        self.peaks = peaks
        self.settings = settings
        self.controller = OperationController(self)
        self.controller.succeeded.connect(self.ready)
        self.controller.failed.connect(self.failed)
        root = QHBoxLayout(self)
        controls = QVBoxLayout()
        tabs = QTabWidget()
        figure = QWidget()
        form = QFormLayout(figure)
        self.view = QComboBox()
        self.view.addItems(["Raw + baseline", "Corrected", "Fit + residuals"])
        self.width_spin = spin(0.1, 20000, 180)
        self.height_spin = spin(0.1, 20000, 120)
        self.unit = QComboBox()
        self.unit.addItems(["mm", "in", "px"])
        self.dpi = spin(36, 1200, 300)
        self.dpi.setDecimals(0)
        self.font_spin = spin(4, 40, 10)
        self.family = QComboBox()
        self.family.addItems(["DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono"])
        self.line_spin = spin(0.1, 10, 1.5)
        self.transparent = QCheckBox("Transparent background")
        self.title = QLineEdit(trace.name)
        self.background = QLineEdit("#FFFFFF")
        self.limit = QCheckBox("Custom time bounds")
        self.start = spin(-1e12, 1e12, float(trace.display_time[0]))
        self.end = spin(-1e12, 1e12, float(trace.display_time[-1]))
        for label, control in [
            ("View", self.view),
            ("Width", self.width_spin),
            ("Height", self.height_spin),
            ("Size unit", self.unit),
            ("DPI", self.dpi),
            ("Font size (pt)", self.font_spin),
            ("Font family", self.family),
            ("Line width (pt)", self.line_spin),
            ("Title", self.title),
            ("Background", self.background),
            ("", self.transparent),
            ("", self.limit),
            ("Time start", self.start),
            ("Time end", self.end),
        ]:
            form.addRow(label, control)
        tabs.addTab(figure, "Figure")
        results = QWidget()
        results_form = QFormLayout(results)
        self.kind = QComboBox()
        self.kind.addItems(["Sampled signal", "Measured peaks", "Fitted components"])
        results_form.addRow("Table", self.kind)
        note = QLabel(
            "CSV retains units, origin and source/baseline identity. "
            "JSON additionally includes the full recipe and diagnostics. "
            "Only current accepted results are exported."
        )
        note.setWordWrap(True)
        results_form.addRow(note)
        tabs.addTab(results, "Results")
        controls.addWidget(tabs)
        self.save = QPushButton("Export figure…")
        self.save.setObjectName("primary")
        controls.addWidget(self.save)
        self.message = QLabel("Rendering preview…")
        self.message.setWordWrap(True)
        controls.addWidget(self.message)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        controls.addWidget(self.close_button)
        root.addLayout(controls, 1)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(500, 400)
        root.addWidget(self.preview, 2)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.render_preview)
        self.controls = [
            self.view,
            self.width_spin,
            self.height_spin,
            self.unit,
            self.dpi,
            self.font_spin,
            self.family,
            self.line_spin,
            self.transparent,
            self.title,
            self.background,
            self.limit,
            self.start,
            self.end,
        ]
        for control in self.controls:
            signal = (
                control.currentTextChanged
                if isinstance(control, QComboBox)
                else control.textChanged
                if isinstance(control, QLineEdit)
                else control.toggled
                if isinstance(control, QCheckBox)
                else control.valueChanged
            )
            signal.connect(lambda *_: self.timer.start())
        tabs.currentChanged.connect(
            lambda index: self.save.setText("Export results…" if index else "Export figure…")
        )
        self.save.clicked.connect(lambda: self.export_file(tabs.currentIndex()))
        for key, control in [
            ("width", self.width_spin),
            ("height", self.height_spin),
            ("dpi", self.dpi),
            ("font_size", self.font_spin),
            ("line_width", self.line_spin),
        ]:
            if key in settings:
                control.setValue(settings[key])
        self.unit.setCurrentText(settings.get("unit", "mm"))
        self.family.setCurrentText(settings.get("font_family", "DejaVu Sans"))
        self.background.setText(settings.get("background", "#FFFFFF"))
        self.transparent.setChecked(settings.get("transparent", False))
        self.render_preview()

    def spec(self):
        return FigureSpec(
            self.width_spin.value(),
            self.height_spin.value(),
            self.unit.currentText(),
            int(self.dpi.value()),
            self.transparent.isChecked(),
            self.background.text(),
            self.view.currentText(),
            self.title.text(),
            self.font_spin.value(),
            self.line_spin.value(),
            (self.start.value(), self.end.value()) if self.limit.isChecked() else None,
            self.family.currentText(),
        )

    def render_preview(self):
        self.controller.cancel()
        spec = self.spec()
        self.message.setText("Rendering exact-size preview…")
        self.controller.request_operation(
            lambda cancel: ("preview", figure_bytes(*self.inputs, spec))
        )

    def ready(self, result):
        mode, value = result
        if mode == "preview":
            pixmap = QPixmap()
            pixmap.loadFromData(value)
            self.preview.setPixmap(
                pixmap.scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.message.setText("Preview uses the same figure specification as saved output.")
        else:
            self.message.setText(f"Exported {value.name}")
        self.save.setEnabled(True)
        for control in self.controls:
            control.setEnabled(True)

    def failed(self, message):
        self.message.setText(message)
        self.save.setEnabled(True)
        for control in self.controls:
            control.setEnabled(True)

    def export_file(self, tab):
        filters = (
            "CSV (*.csv);;JSON (*.json)"
            if tab
            else "PNG (*.png);;TIFF (*.tiff);;PDF (*.pdf);;SVG (*.svg)"
        )
        try:
            path = choose_output(
                self,
                "Export results" if tab else "Export figure",
                "results.csv" if tab else "chromatogram.png",
                filters,
                ["csv", "json"] if tab else ["png", "tiff", "tif", "pdf", "svg"],
            )
        except ValueError as error:
            self.failed(str(error))
            return
        if path is None:
            return
        self.timer.stop()
        self.save.setEnabled(False)
        for control in self.controls:
            control.setEnabled(False)
        spec = self.spec()
        kind = self.kind.currentText()
        trace, baseline, fitted, labels = self.inputs

        def operation(cancel):
            if cancel():
                raise ImportCancelled()
            value = (
                export_results(
                    path, trace, baseline, self.peaks, fitted, kind, labels=labels, cancel=cancel
                )
                if tab
                else export_figure(path, *self.inputs, spec, cancel=cancel)
            )
            return "saved", value

        self.settings.update(asdict(spec))
        self.controller.request_operation(operation)

    def done(self, result):
        self.timer.stop()
        self.controller.shutdown()
        super().done(result)
