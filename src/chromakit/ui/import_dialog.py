"""Preview and mapping before a source is admitted to the workspace."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QVBoxLayout,
)

from chromakit.domain import Trace
from chromakit.importers.text import (
    DELIMITERS,
    ColumnMapping,
    ParsedTable,
    ParseOptions,
    TextSource,
    build_trace,
    load_source,
    parse_source,
    suggest_mapping,
)
from chromakit.ui.models import PreviewModel
from chromakit.ui.tasks import ImportTask


def combo(items: list[str]) -> QComboBox:
    widget = QComboBox()
    widget.addItems(items)
    return widget


class ImportDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.source: TextSource | None = None
        self.table: ParsedTable | None = None
        self.trace: Trace | None = None
        self.tasks: list[ImportTask] = []
        self.closing = False
        self.setWindowTitle("Import chromatogram")
        self.resize(980, 760)
        self.setMinimumSize(820, 620)
        self.setModal(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        title = QLabel("Import chromatogram")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(path.name)
        subtitle.setObjectName("muted")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setToolTip(str(path))
        root.addWidget(subtitle)

        settings = QHBoxLayout()
        self.delimiter = combo(["Auto", *DELIMITERS, "Whitespace"])
        self.encoding = combo(["Auto", "utf-8-sig", "utf-16", "cp1252", "latin-1"])
        self.decimal = combo([".", ","])
        self.header = combo(["Auto", "Yes", "No"])
        self.skip = QSpinBox()
        self.skip.setRange(0, 100_000)
        self.skip.setToolTip("Leading physical lines to omit, such as an instrument report header.")
        for label, control in (
            ("Delimiter", self.delimiter),
            ("Encoding", self.encoding),
            ("Decimal", self.decimal),
            ("Header row", self.header),
            ("Skip lines", self.skip),
        ):
            column = QVBoxLayout()
            field_label = QLabel(label)
            field_label.setBuddy(control)
            column.addWidget(field_label)
            column.addWidget(control)
            settings.addLayout(column)
        self.refresh = QPushButton("Update preview")
        self.refresh.clicked.connect(self.update_preview)
        settings.addWidget(self.refresh, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(settings)

        body = QHBoxLayout()
        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        self.preview_info = QLabel("Reading source…")
        self.preview_info.setObjectName("section")
        preview_layout.addWidget(self.preview_info)
        self.preview = QTableView()
        self.preview.setAlternatingRowColors(True)
        self.preview.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.preview.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self.preview)
        hint = QLabel("Preview shows the first 50 data rows. Row numbers refer to source lines.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        preview_layout.addWidget(hint)
        body.addWidget(preview_card, 2)

        mapping_card = QFrame()
        mapping_card.setObjectName("card")
        mapping_layout = QVBoxLayout(mapping_card)
        mapping_layout.setContentsMargins(18, 16, 18, 16)
        mapping_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        section = QLabel("TRACE MAPPING")
        section.setObjectName("section")
        mapping_layout.addWidget(section)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setSpacing(12)
        self.name = QLineEdit(path.stem)
        self.time_column = QComboBox()
        self.time_unit = combo(["unknown", "s", "min", "h"])
        self.signal_column = QComboBox()
        self.signal_unit = combo(["unknown", "mAU", "AU", "mV", "µV", "nA", "µA", "nC", "RIU"])
        self.signal_unit.setEditable(True)
        self.detector = combo(["Unspecified", "UV", "RID", "PAD"])
        self.missing_signal = combo(["Reject", "Omit with gaps"])
        self.missing_signal.setToolTip(
            "Omit only blank/NaN/NA signal values. Preserve internal breaks "
            "and source line provenance; "
            "never fill or bridge gaps. Invalid times, infinity and malformed values still fail."
        )
        for label, control in (
            ("Sample name", self.name),
            ("Time column", self.time_column),
            ("Time unit", self.time_unit),
            ("Signal column", self.signal_column),
            ("Signal unit", self.signal_unit),
            ("Detector", self.detector),
            ("Missing signal", self.missing_signal),
        ):
            form.addRow(label, control)
        mapping_layout.addLayout(form)
        note = QLabel(
            "Use sampled detector data, not a peak-results table. "
            "Review units; unknown units allow inspection only."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        mapping_layout.addWidget(note)
        mapping_layout.addStretch()
        mapping_scroll = QScrollArea()
        self.mapping_scroll = mapping_scroll
        mapping_scroll.setWidgetResizable(True)
        mapping_scroll.setFrameShape(QFrame.Shape.NoFrame)
        mapping_scroll.setWidget(mapping_card)
        mapping_scroll.setMinimumWidth(280)
        body.addWidget(mapping_scroll, 1)
        root.addLayout(body, 1)
        self.message = QLabel("Reading file in the background…")
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setObjectName("muted")
        root.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        root.addWidget(self.progress)
        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.import_button = QPushButton("Import && plot")
        self.import_button.setObjectName("primary")
        self.import_button.clicked.connect(self.import_trace)
        self.import_button.setDefault(True)
        self.import_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.import_button)
        root.addLayout(footer)
        self.parse_controls = [self.delimiter, self.encoding, self.decimal, self.header, self.skip]
        self.mapping_controls = [
            self.name,
            self.time_column,
            self.time_unit,
            self.signal_column,
            self.signal_unit,
            self.detector,
            self.missing_signal,
        ]
        for control in self.parse_controls:
            if isinstance(control, QSpinBox):
                control.valueChanged.connect(self.mark_stale)
            else:
                control.currentTextChanged.connect(self.mark_stale)
        self.set_busy(True)
        self.start_task(lambda cancel: load_source(path, cancel), self.source_ready)

    def start_task(self, operation, callback):
        task = ImportTask(operation, self)
        self.tasks.append(task)
        task.succeeded.connect(callback)
        task.failed.connect(self.failed)
        task.start()

    def set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        for control in self.parse_controls + self.mapping_controls + [self.refresh]:
            control.setEnabled(not busy)
        self.import_button.setEnabled(not busy and self.table is not None)

    def mark_stale(self):
        self.import_button.setEnabled(False)
        self.feedback("Settings changed. Update the preview before importing.")

    def feedback(self, message: str, error=False):
        self.message.setText(message)
        self.message.setObjectName("error" if error else "muted")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)

    def options(self) -> ParseOptions:
        return ParseOptions(
            self.delimiter.currentText(),
            self.encoding.currentText(),
            self.decimal.currentText(),
            self.skip.value(),
            self.header.currentText(),
        )

    def source_ready(self, source: TextSource):
        if self.closing:
            return
        self.source = source
        self.update_preview()

    def update_preview(self):
        if self.source is None or self.closing:
            return
        self.table = None
        options = self.options()
        self.set_busy(True)
        self.feedback("Parsing and checking column structure…")
        self.start_task(
            lambda cancel: parse_source(self.source, options, cancel), self.preview_ready
        )

    def preview_ready(self, table: ParsedTable):
        if self.closing:
            return
        self.table = table
        old_model = self.preview.model()
        self.preview.setModel(PreviewModel(table, self.preview))
        if old_model is not None:
            old_model.deleteLater()
        self.preview_info.setText(
            f"{len(table.rows):,} ROWS  ·  {len(table.columns)} COLUMNS"
            f"  ·  {table.delimiter.upper()}"
        )
        mapping = suggest_mapping(table)
        for control in (self.time_column, self.signal_column):
            control.clear()
            control.addItems([f"{i + 1} · {name}" for i, name in enumerate(table.columns)])
        self.time_column.setCurrentIndex(mapping.time)
        self.signal_column.setCurrentIndex(mapping.signal)
        self.time_unit.setCurrentText(mapping.time_unit)
        self.signal_unit.setCurrentText(mapping.signal_unit)
        self.feedback("Review the mapping, then import. " + " ".join(table.warnings))
        self.set_busy(False)

    def import_trace(self):
        if self.table is None:
            return
        table = self.table
        mapping = ColumnMapping(
            self.time_column.currentIndex(),
            self.signal_column.currentIndex(),
            self.time_unit.currentText(),
            self.signal_unit.currentText(),
            self.detector.currentText(),
            self.name.text(),
            self.missing_signal.currentText(),
        )
        self.set_busy(True)
        self.feedback("Validating every selected sample…")
        self.start_task(lambda cancel: build_trace(table, mapping, cancel), self.trace_ready)

    def trace_ready(self, trace: Trace):
        if self.closing:
            return
        self.trace = trace
        self.accept()

    def failed(self, message: str):
        if self.closing:
            return
        self.feedback(message, error=True)
        self.set_busy(False)
        if "Omit with gaps" in message:
            self.mapping_scroll.ensureWidgetVisible(self.missing_signal, 0, 24)

    def done(self, result: int):
        self.closing = True
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            task.wait()
        super().done(result)
