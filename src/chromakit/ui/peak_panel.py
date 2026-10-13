"""Detection controls and synchronized, numerically editable peak results."""

from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, QLocale, Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from chromakit.analysis.peaks import PeakRecipe, detect_peaks, edit_boundaries
from chromakit.ui.peak_tasks import PeakController


class PeakTableModel(QAbstractTableModel):
    edit_requested = Signal(str, float, float)
    invalid_edit = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.editable = False

    def update_result(self, result, editable):
        if self.result is result and self.editable == editable:
            return
        self.beginResetModel()
        self.result, self.editable = result, editable
        self.endResetModel()

    def rowCount(self, parent=None):
        return (
            0
            if parent is not None and parent.isValid()
            else len(self.result.peaks)
            if self.result
            else 0
        )

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else 8

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        time = self.result.time_unit if self.result else "time"
        signal = self.result.signal_unit if self.result else "signal"
        area = self.result.area_unit if self.result else "signal × time"
        return [
            "Peak",
            f"Retention\n({time})",
            f"Height\n({signal})",
            f"Area\n({area})",
            f"Start\n({time})",
            f"End\n({time})",
            "Direction",
            "Review flags",
        ][section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.result is None:
            return None
        peak = self.result.peaks[index.row()]
        values = [
            peak.id,
            peak.retention_time,
            peak.height,
            peak.area,
            peak.start,
            peak.end,
            peak.polarity,
            "; ".join(peak.flags),
        ]
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"{peak.id} · Half-prominence width {peak.width:.8g} {self.result.time_unit}\n"
                f"Prominence {peak.prominence:.8g}; noise estimate {peak.noise:.8g}\n"
                + "\n".join(peak.flags)
            )
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            value = values[index.column()]
            return (
                f"{value:.17g}"
                if isinstance(value, float) and role == Qt.ItemDataRole.EditRole
                else (f"{value:.8g}" if isinstance(value, float) else value)
            )
        return None

    def flags(self, index):
        flags = super().flags(index)
        if self.editable and index.column() in (4, 5):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not self.editable or role != Qt.ItemDataRole.EditRole or index.column() not in (4, 5):
            return False
        peak = self.result.peaks[index.row()]
        try:
            number = float(str(value).replace("−", "-"))
        except ValueError:
            self.invalid_edit.emit("Enter a numeric boundary time.")
            return False
        self.edit_requested.emit(
            peak.id,
            number if index.column() == 4 else peak.start,
            number if index.column() == 5 else peak.end,
        )
        return True


class ScientificSpin(QDoubleSpinBox):
    """Readable numbers and exponent entry for small detector-signal units."""

    def textFromValue(self, value):
        return f"{value:.12g}"

    def valueFromText(self, text):
        try:
            return float(text)
        except ValueError:
            return self.value()

    def validate(self, text, position):
        validator = QDoubleValidator(self.minimum(), self.maximum(), 15)
        validator.setLocale(QLocale.c())
        validator.setNotation(QDoubleValidator.Notation.ScientificNotation)
        return validator.validate(text, position)


def spin(minimum=0, maximum=1e12, value=0):
    widget = ScientificSpin()
    widget.setDecimals(15)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


class PeakPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.busy = False
        self.loading = False
        self.controller = PeakController(self)
        self.controller.succeeded.connect(self.ready)
        self.controller.failed.connect(self.failed)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        title = QLabel("PEAK DETECTION & INTEGRATION")
        title.setObjectName("section")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.description = QLabel(
            "Apply a baseline, then detect peaks in its corrected signal. "
            "Changing detection settings requires a new detection run."
        )
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.polarity = QComboBox()
        for name, key in (
            ("Positive peaks", "positive"),
            ("Negative peaks", "negative"),
            ("Both signs", "both"),
        ):
            self.polarity.addItem(name, key)
        self.noise = spin(1, 100, 6)
        self.prominence = spin()
        self.prominence.setSpecialValueText("Automatic from noise")
        self.height = spin()
        self.width = spin()
        self.separation = spin()
        self.fraction = spin(0.0001, 0.49, 0.005)
        self.controls = [
            self.polarity,
            self.noise,
            self.prominence,
            self.height,
            self.width,
            self.separation,
            self.fraction,
        ]
        for name, control in (
            ("Direction", self.polarity),
            ("Noise multiplier", self.noise),
            ("Minimum prominence", self.prominence),
            ("Minimum height", self.height),
            ("Minimum width (time)", self.width),
            ("Minimum separation (time)", self.separation),
            ("Boundary height fraction", self.fraction),
        ):
            form.addRow(name, control)
        layout.addLayout(form)
        self.advanced = QCheckBox("Advanced detection settings")
        layout.addWidget(self.advanced)
        self.advanced.toggled.connect(
            lambda visible: [
                form.setRowVisible(control, visible)
                for control in (self.height, self.width, self.separation, self.fraction)
            ]
        )
        for control in (self.height, self.width, self.separation, self.fraction):
            form.setRowVisible(control, False)
        self.form = form
        self.width.setToolTip("Full width at half prominence, measured on actual time coordinates.")
        layout.addWidget(QLabel("SELECTED PEAK BOUNDARIES"))
        self.selection = QLabel("Select a peak in the table or click its marker.")
        self.selection.setWordWrap(True)
        layout.addWidget(self.selection)
        self.selected_flags = QLabel()
        self.selected_flags.setObjectName("muted")
        self.selected_flags.setWordWrap(True)
        layout.addWidget(self.selected_flags)
        edit_form = QFormLayout()
        self.start = spin(-1e12)
        self.end = spin(-1e12)
        edit_form.addRow("Start", self.start)
        edit_form.addRow("End", self.end)
        layout.addLayout(edit_form)
        self.update_button = QPushButton("Update boundaries")
        self.update_button.clicked.connect(self.edit_selected)
        layout.addWidget(self.update_button)
        self.remove = QPushButton("Remove selected peak")
        self.remove.clicked.connect(self.remove_selected)
        layout.addWidget(self.remove)
        note = QLabel(
            "Areas are signed integrals relative to the applied baseline. "
            "Valley splitting is not deconvolution. Re-detect replaces edits; undo is available."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        layout.addStretch()
        self.status = QLabel("Apply a baseline to enable detection.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        root.addWidget(self.progress)
        row = QHBoxLayout()
        self.detect = QPushButton("Detect peaks")
        self.detect.setObjectName("primary")
        self.detect.clicked.connect(self.detect_now)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.detect)
        row.addWidget(self.stop_button)
        root.addLayout(row)
        self.model = PeakTableModel(self)
        self.model.edit_requested.connect(self.edit_peak)
        self.model.invalid_edit.connect(self.failed)
        for control in self.controls:
            signal = (
                control.currentIndexChanged
                if isinstance(control, QComboBox)
                else control.valueChanged
            )
            signal.connect(self.settings_changed)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((55, 105, 105, 125, 95, 95, 80, 250)):
            self.table.setColumnWidth(column, width)
        self.table.selectionModel().currentRowChanged.connect(self.table_selected)
        self.set_state(None)

    def set_state(self, state):
        self.stop()
        self.state = state
        self.loading = True
        recipe = state.recipe if state else PeakRecipe()
        self.polarity.setCurrentIndex(self.polarity.findData(recipe.polarity))
        for control, value in zip(
            self.controls[1:],
            [
                recipe.noise_multiplier,
                recipe.minimum_prominence,
                recipe.minimum_height,
                recipe.minimum_width,
                recipe.minimum_separation,
                recipe.boundary_fraction,
            ],
            strict=True,
        ):
            control.setValue(value)
        self.loading = False
        if state:
            trace = state.baseline_state.trace
            for control in (self.width, self.separation):
                name = "Minimum width" if control is self.width else "Minimum separation"
                self.form.labelForField(control).setText(f"{name} ({trace.time_unit})")
            for control in (self.height, self.prominence):
                name = "Minimum height" if control is self.height else "Minimum prominence"
                self.form.labelForField(control).setText(f"{name} ({trace.signal_unit})")
        self.refresh()

    def sync_baseline(self):
        if self.state and self.state.sync_baseline():
            self.stop()
            self.refresh()
            self.changed.emit()

    def recipe(self):
        return PeakRecipe(
            self.polarity.currentData(),
            self.noise.value(),
            self.prominence.value(),
            self.height.value(),
            self.width.value(),
            self.separation.value(),
            self.fraction.value(),
        )

    def settings_changed(self, *_):
        if self.state and not self.loading and not self.busy:
            self.state.recipe = self.recipe()
            self.refresh()

    def launch(self, operation):
        self.busy = True
        self.status.setText("Calculating from the applied corrected signal…")
        self.refresh_buttons()
        self.model.update_result(self.state.result, False)
        self.controller.request_operation(operation)
        self.changed.emit()

    def detect_now(self):
        if not self.state or not self.state.baseline_state.applied or self.busy:
            return
        state = self.state
        baseline = state.baseline_state.applied
        recipe = self.recipe()
        state.recipe = recipe
        self.launch(
            lambda cancel: detect_peaks(state.baseline_state.trace, baseline, recipe, cancel)
        )

    def ready(self, result):
        self.busy = False
        accepted = self.state is not None and self.state.accept(result)
        self.refresh()
        if not accepted:
            self.status.setText("The baseline changed during calculation. Detect peaks again.")
        self.changed.emit()

    def failed(self, message):
        self.busy = False
        self.refresh()
        self.status.setText(message)
        self.changed.emit()

    def stop(self):
        was_busy = self.busy
        self.controller.cancel()
        self.busy = False
        self.refresh_buttons()
        if hasattr(self, "model"):
            self.refresh()
            if was_busy:
                self.status.setText("Calculation stopped; previous results are retained.")
            self.changed.emit()

    def refresh_buttons(self):
        available = self.state is not None and self.state.baseline_state.applied is not None
        editable = bool(self.state and self.state.current and not self.busy)
        self.detect.setEnabled(available and not self.busy)
        self.stop_button.setEnabled(self.busy)
        self.progress.setVisible(self.busy)
        for control in self.controls:
            control.setEnabled(available and not self.busy)
        for control in (self.start, self.end, self.update_button, self.remove):
            control.setEnabled(editable and self.state.selected_id is not None)

    def refresh(self):
        state = self.state
        if state:
            state.sync_baseline()
        self.model.update_result(
            state.result if state else None, bool(state and state.current and not self.busy)
        )
        self.refresh_buttons()
        if state is None or state.baseline_state.applied is None:
            self.status.setText(
                "Apply a baseline to enable detection. Existing results, if any, are stale."
            )
        elif state.result is None:
            self.status.setText("Ready. Detect peaks from the applied corrected signal.")
        elif not state.current:
            self.status.setText(
                "STALE: the applied baseline changed. Re-detect before using these measurements."
            )
        else:
            review = any(not segment.converged for segment in state.baseline_state.applied.segments)
            self.status.setText(
                f"{len(state.result.peaks)} peaks · applied baseline · "
                f"area units: {state.result.area_unit}"
                + (" · baseline needs review" if review else "")
                + (
                    " · settings changed; re-detect to update"
                    if state.result.recipe != state.recipe
                    else ""
                )
            )
            self.status.setToolTip("\n".join(state.result.warnings))
        self.select_id(state.selected_id if state else None, emit=False)

    def table_selected(self, index, old):
        if self.loading or not index.isValid() or not self.state or not self.state.result:
            return
        self.select_id(self.state.result.peaks[index.row()].id)

    def select_id(self, peak_id, emit=True):
        self.selected_flags.clear()
        if not self.state or not self.state.result:
            self.selection.setText("Select a peak in the table or click its marker.")
            return
        peak = next((peak for peak in self.state.result.peaks if peak.id == peak_id), None)
        if peak:
            self.selected_flags.setText("\n".join(peak.flags))
            self.state.selected_id = peak.id
            self.selection.setText(
                f"{peak.id} · retention {peak.retention_time:.8g} {self.state.result.time_unit}"
            )
            self.start.setValue(peak.start)
            self.end.setValue(peak.end)
            self.loading = True
            row = self.state.result.peaks.index(peak)
            self.table.selectRow(row)
            self.loading = False
        else:
            self.state.selected_id = None
        self.refresh_buttons()
        if emit:
            self.changed.emit()

    def edit_selected(self):
        if self.state and self.state.selected_id:
            self.edit_peak(self.state.selected_id, self.start.value(), self.end.value())

    def edit_peak(self, peak_id, start, end):
        if not self.state or not self.state.current or self.busy:
            return
        state = self.state
        baseline, result = state.baseline_state.applied, state.result
        self.launch(
            lambda cancel: edit_boundaries(
                state.baseline_state.trace, baseline, result, peak_id, start, end, cancel
            )
        )

    def remove_selected(self):
        if self.state and self.state.current and not self.busy:
            result = replace(
                self.state.result,
                peaks=tuple(
                    peak for peak in self.state.result.peaks if peak.id != self.state.selected_id
                ),
            )
            self.state.accept(result)
            self.refresh()
            self.changed.emit()

    def history_action(self, redo=False):
        self.stop()
        if self.state:
            self.state.undo(redo)
        self.refresh()
        self.changed.emit()

    def shutdown(self):
        self.controller.shutdown()
