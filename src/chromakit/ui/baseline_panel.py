"""Baseline controls, manual refinement, diagnostics and reversible application."""

from PySide6.QtCore import Qt, QTimer, Signal
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
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chromakit.analysis.baseline import (
    METHODS,
    Anchor,
    BaselineProblem,
    BaselineRecipe,
    MaskRegion,
    validate_recipe,
)
from chromakit.application.baselines import BaselineState
from chromakit.ui.baseline_tasks import BaselineController


def text_label(text, style="muted"):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(style)
    return widget


class BaselinePanel(QWidget):
    changed = Signal()
    geometry_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state: BaselineState | None = None
        self.active = False
        self.loading = False
        self.busy = False
        self.valid = True
        self.controller = BaselineController(self)
        self.controller.succeeded.connect(self.preview_ready)
        self.controller.failed.connect(self.preview_failed)
        self.controller.progress.connect(self.update_progress)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(250)
        self.debounce.timeout.connect(self.calculate)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        root.addWidget(text_label("WHOLE-TRACE BASELINE", "section"))
        root.addWidget(text_label("Preview changes before applying. Raw samples stay intact."))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._method_tab()
        self._refine_tab()
        self.review = QTextEdit()
        self.review.setReadOnly(True)
        self.review.setAccessibleName("Baseline diagnostics and recipe")
        self.tabs.addTab(self.review, "Review")
        self.status = text_label("Import a chromatogram to correct its baseline.")
        root.addWidget(self.status)
        self.notice = text_label("", "warning")
        self.notice.hide()
        root.addWidget(self.notice)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        root.addWidget(self.progress)
        row = QHBoxLayout()
        self.cancel = QPushButton("Stop preview")
        self.cancel.clicked.connect(self.stop)
        self.discard = QPushButton("Discard")
        self.discard.clicked.connect(self.discard_preview)
        row.addWidget(self.cancel)
        row.addWidget(self.discard)
        root.addLayout(row)
        row = QHBoxLayout()
        self.apply = QPushButton("Apply baseline")
        self.apply.setObjectName("primary")
        self.apply.clicked.connect(self.apply_preview)
        self.clear = QPushButton("Clear applied")
        self.clear.clicked.connect(self.clear_applied)
        row.addWidget(self.apply)
        row.addWidget(self.clear)
        root.addLayout(row)
        self.set_state(None)

    def scroll_tab(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)
        return layout

    def _method_tab(self):
        layout = self.scroll_tab("Method")
        self.method = QComboBox()
        for key, title in METHODS.items():
            self.method.addItem(title, key)
        layout.addWidget(text_label("Method", "section"))
        layout.addWidget(self.method)
        self.description = text_label("")
        layout.addWidget(self.description)
        self.preset = QComboBox()
        self.preset.addItems(["Balanced", "Broad peaks / gentle drift", "Curved drift", "Custom"])
        layout.addWidget(text_label("Starting preset", "section"))
        layout.addWidget(self.preset)
        self.stiffness = QSlider(Qt.Orientation.Horizontal)
        self.stiffness.setRange(0, 120)
        self.stiffness.setValue(60)
        self.stiffness.setAccessibleName("Baseline stiffness")
        self.stiffness_label = text_label("Stiffness · λ = 1000", "section")
        layout.addWidget(self.stiffness_label)
        layout.addWidget(self.stiffness)
        layout.addWidget(
            text_label("Higher = smoother, fewer bends. Lower follows curved drift more closely.")
        )
        layout.addWidget(text_label("Peak direction", "section"))
        self.polarity = QComboBox()
        self.polarity.addItem("Positive peaks", "positive")
        self.polarity.addItem("Negative peaks", "negative")
        layout.addWidget(self.polarity)
        layout.addWidget(
            text_label("For mixed signs, protect both peak regions or use manual anchors.")
        )
        self.advanced_toggle = QCheckBox("Advanced parameters")
        layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.knots = QSpinBox()
        self.knots.setRange(5, 300)
        self.knots.setValue(80)
        self.asymmetry = QDoubleSpinBox()
        self.asymmetry.setDecimals(4)
        self.asymmetry.setRange(0.0001, 0.49)
        self.asymmetry.setSingleStep(0.001)
        self.asymmetry.setValue(0.001)
        self.iterations = QSpinBox()
        self.iterations.setRange(1, 500)
        self.iterations.setValue(80)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(8)
        self.tolerance.setRange(1e-8, 0.1)
        self.tolerance.setValue(0.001)
        for name, widget in (
            ("Spline knots", self.knots),
            ("AsLS peak weight", self.asymmetry),
            ("Maximum iterations", self.iterations),
            ("Convergence tolerance", self.tolerance),
        ):
            form.addRow(name, widget)
        self.asymmetry.setToolTip("AsLS only. A smaller weight reduces the influence of peaks.")
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        layout.addStretch()
        self.method.currentIndexChanged.connect(self.edited)
        self.polarity.currentIndexChanged.connect(self.edited)
        self.stiffness.valueChanged.connect(self.stiffness_changed)
        self.preset.currentIndexChanged.connect(self.preset_changed)
        for widget in (self.knots, self.asymmetry, self.iterations, self.tolerance):
            widget.valueChanged.connect(self.edited)

    def _refine_tab(self):
        layout = self.scroll_tab("Refine")
        layout.addWidget(text_label("Absolute baseline anchors", "section"))
        layout.addWidget(
            text_label(
                "Automatic: refine the fit through anchors. Manual: interpolate anchors "
                "directly. Add outer anchors to limit a local refinement."
            )
        )
        self.anchor_mode = QCheckBox("Click plot to add anchors")
        self.anchor_mode.toggled.connect(self.geometry_changed)
        layout.addWidget(self.anchor_mode)
        self.anchor_table = QTableWidget(0, 2)
        self.anchor_table.setHorizontalHeaderLabels(["Time", "Baseline height"])
        self.anchor_table.horizontalHeader().setStretchLastSection(True)
        self.anchor_table.setColumnWidth(0, 95)
        self.anchor_table.setMaximumHeight(160)
        self.anchor_table.setMinimumHeight(115)
        self.anchor_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.anchor_table.cellChanged.connect(self.edited)
        layout.addWidget(self.anchor_table)
        row = QHBoxLayout()
        add = QPushButton("Add anchor")
        add.clicked.connect(self.add_default_anchor)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self.remove_rows(self.anchor_table))
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        layout.addWidget(text_label("Protected peaks & excluded artifacts", "section"))
        layout.addWidget(
            text_label(
                "These regions cannot influence the automatic fit. All original samples remain. "
                "Drag region boundaries on the plot or edit their times here."
            )
        )
        self.region_table = QTableWidget(0, 3)
        self.region_table.setHorizontalHeaderLabels(["Start", "End", "Type"])
        self.region_table.setColumnWidth(0, 75)
        self.region_table.setColumnWidth(1, 75)
        self.region_table.horizontalHeader().setStretchLastSection(True)
        self.region_table.setMaximumHeight(150)
        self.region_table.setMinimumHeight(115)
        self.region_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.region_table.cellChanged.connect(self.edited)
        layout.addWidget(self.region_table)
        row = QHBoxLayout()
        add = QPushButton("Add region")
        add.clicked.connect(self.add_region)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self.remove_rows(self.region_table))
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        layout.addStretch()

    def set_state(self, state: BaselineState | None):
        self.controller.cancel()
        self.debounce.stop()
        self.state = state
        self.busy = False
        self.progress.hide()
        self.tabs.setEnabled(state is not None)
        self.restore_controls()
        self.refresh_status()
        if state is not None and self.active and state.preview is None:
            self.edited()

    def set_active(self, active):
        self.active = active
        if not active:
            self.stop(update_status=False)
            self.anchor_mode.setChecked(False)
        elif self.state is not None and self.state.preview is None:
            self.edited()
        self.changed.emit()
        self.geometry_changed.emit()

    def restore_controls(self):
        self.loading = True
        self.valid = True
        recipe = self.state.draft if self.state else BaselineRecipe()
        self.method.setCurrentIndex(self.method.findData(recipe.method))
        self.polarity.setCurrentIndex(self.polarity.findData(recipe.polarity))
        import math

        self.stiffness.setValue(round((math.log10(recipe.smoothness) + 3) * 10))
        self.knots.setValue(recipe.knots)
        self.asymmetry.setValue(recipe.asymmetry)
        self.iterations.setValue(recipe.max_iterations)
        self.tolerance.setValue(recipe.tolerance)
        self.preset.setCurrentText("Balanced" if recipe == BaselineRecipe() else "Custom")
        self.anchor_table.setRowCount(0)
        for anchor in recipe.anchors:
            self._append_anchor(anchor)
        self.region_table.setRowCount(0)
        for region in recipe.regions:
            self._append_region(region)
        self.loading = False
        self.update_description()
        self.geometry_changed.emit()

    def update_description(self):
        method = self.method.currentData()
        descriptions = {
            "arpls": "Adaptive weights reduce peak influence while fitting smooth drift. "
            "A good first estimate; always inspect broad peaks and trace edges.",
            "asls": "Asymmetric weights favor baseline observations over peaks. "
            "Tune stiffness and peak weight for broad or crowded chromatograms.",
            "manual": "Shape-preserving interpolation through absolute baseline anchors. "
            "Use at least two anchors per sampled segment. Outer values extend constantly.",
        }
        self.description.setText(descriptions[method])
        automatic = method != "manual"
        for widget in (
            self.stiffness,
            self.preset,
            self.polarity,
            self.knots,
            self.iterations,
            self.tolerance,
        ):
            widget.setEnabled(automatic)
        self.asymmetry.setEnabled(method == "asls")
        self.stiffness_label.setText(
            f"Stiffness · λ = {10 ** (self.stiffness.value() / 10 - 3):.4g}"
        )
        if self.state:
            self.anchor_table.setHorizontalHeaderLabels(
                [
                    f"Time ({self.state.trace.time_unit})",
                    f"Height ({self.state.trace.signal_unit})",
                ]
            )

    def recipe(self):
        try:
            anchors = tuple(
                Anchor(
                    float(self.anchor_table.item(row, 0).text()),
                    float(self.anchor_table.item(row, 1).text()),
                )
                for row in range(self.anchor_table.rowCount())
            )
            regions = tuple(
                MaskRegion(
                    float(self.region_table.item(row, 0).text()),
                    float(self.region_table.item(row, 1).text()),
                    self.region_table.cellWidget(row, 2).currentData(),
                )
                for row in range(self.region_table.rowCount())
            )
        except (ValueError, AttributeError) as error:
            raise BaselineProblem(
                "Enter numeric times and heights in every refinement row."
            ) from error
        return BaselineRecipe(
            self.method.currentData(),
            10 ** (self.stiffness.value() / 10 - 3),
            self.asymmetry.value(),
            self.knots.value(),
            self.polarity.currentData(),
            self.iterations.value(),
            self.tolerance.value(),
            anchors,
            regions,
        )

    def edited(self, *_):
        if self.loading or self.state is None:
            return
        self.controller.cancel()
        self.debounce.stop()
        self.state.preview = None
        self.notice.hide()
        self.review.setPlainText(
            "Settings changed. Calculate a current preview to review diagnostics."
        )
        self.update_description()
        try:
            recipe = self.recipe()
            validate_recipe(self.state.trace, recipe, check_samples=False)
        except BaselineProblem as error:
            self.valid = False
            self.busy = False
            self.progress.hide()
            self.status.setText(str(error))
            self.apply.setEnabled(False)
            self.cancel.setEnabled(False)
            self.geometry_changed.emit()
            self.changed.emit()
            return
        self.valid = True
        self.state.update_draft(recipe)
        self.geometry_changed.emit()
        if self.active:
            self.busy = True
            self.status.setText("Updating preview…")
            self.progress.setRange(0, 0)
            self.progress.show()
            self.apply.setEnabled(False)
            self.cancel.setEnabled(True)
            self.debounce.start()
        self.changed.emit()

    def stiffness_changed(self):
        if not self.loading:
            self.loading = True
            self.preset.setCurrentText("Custom")
            self.loading = False
        self.edited()

    def preset_changed(self):
        if self.loading or self.preset.currentText() == "Custom":
            return
        presets = {
            "Balanced": (60, 80, 0.001),
            "Broad peaks / gentle drift": (75, 60, 0.0005),
            "Curved drift": (40, 100, 0.001),
        }
        stiffness, knots, asymmetry = presets[self.preset.currentText()]
        self.loading = True
        self.stiffness.setValue(stiffness)
        self.knots.setValue(knots)
        self.asymmetry.setValue(asymmetry)
        self.loading = False
        self.edited()

    def calculate(self):
        if self.state is not None and self.active and self.valid:
            self.controller.request(self.state.trace, self.state.draft)

    def preview_ready(self, result):
        if self.state is None or not self.state.accept_preview(result):
            return
        self.busy = False
        self.progress.hide()
        self.refresh_status()
        self.changed.emit()

    def preview_failed(self, message):
        self.busy = False
        self.progress.hide()
        self.status.setText(message)
        self.apply.setEnabled(False)
        self.cancel.setEnabled(False)
        self.changed.emit()

    def update_progress(self, step, total):
        self.progress.setRange(0, total)
        self.progress.setValue(step)

    def refresh_status(self):
        state = self.state
        self.notice.hide()
        self.status.setToolTip("")
        self.apply.setEnabled(
            state is not None
            and state.preview is not None
            and not self.busy
            and (state.applied is None or state.applied.recipe != state.draft)
        )
        self.clear.setEnabled(state is not None and state.applied is not None)
        self.discard.setEnabled(state is not None)
        self.cancel.setEnabled(self.busy)
        if state is None:
            self.status.setText("Import a chromatogram to correct its baseline.")
            self.review.clear()
            return
        result = state.preview or state.applied
        if result is None:
            self.status.setText("No baseline applied. Select a method to preview.")
            self.review.setPlainText(
                "Preview a baseline to see convergence diagnostics and provenance."
            )
            return
        prefix = "Applied" if result is state.applied else "Preview · not applied"
        converged = all(segment.converged for segment in result.segments)
        completion = "defined by anchors" if result.recipe.method == "manual" else "converged"
        self.status.setText(f"{prefix} · {completion if converged else 'needs review'}")
        if result.warnings:
            self.notice.setText(result.warnings[0] + " More details in Review.")
            self.notice.show()
        lines = [METHODS[result.recipe.method], prefix, ""]
        for i, segment in enumerate(result.segments):
            lines.append(
                f"Segment {i + 1}: {segment.fitted_samples:,} fitting samples, "
                f"{segment.iterations} iterations, "
                f"{'converged' if segment.converged else 'not converged'}"
            )
            if segment.effective_knots is not None:
                lines.append(f"  Effective spline knots: {segment.effective_knots}")
        lines.extend(
            [
                "",
                *result.warnings,
                "",
                f"Algorithm: {result.algorithm_version}",
                f"Created: {result.created_at}",
                f"Input: {result.input_key}",
                f"Units: {result.time_unit} / {result.signal_unit}",
                f"Stiffness λ: {result.recipe.smoothness:g}",
                f"Knots: {result.recipe.knots}; tolerance: {result.recipe.tolerance:g}",
                f"Polarity: {result.recipe.polarity}",
                f"Anchors: {len(result.recipe.anchors)}; masks: {len(result.recipe.regions)}",
                *[f"{name}: {version}" for name, version in result.software_versions],
            ]
        )
        self.review.setPlainText("\n".join(lines))
        self.status.setToolTip("\n".join(result.warnings))

    def stop(self, update_status=True):
        self.debounce.stop()
        self.controller.cancel()
        self.busy = False
        self.progress.hide()
        self.cancel.setEnabled(False)
        if update_status:
            self.status.setText("Preview stopped. Change a setting to recalculate.")

    def apply_preview(self):
        if self.state and self.state.apply():
            self.refresh_status()
            self.changed.emit()

    def discard_preview(self):
        self.stop(False)
        if self.state:
            self.state.discard()
            self.restore_controls()
            self.refresh_status()
            self.changed.emit()

    def clear_applied(self):
        self.stop(False)
        if self.state:
            self.state.clear()
            self.restore_controls()
            self.refresh_status()
            self.changed.emit()

    def history_action(self, redo=False):
        self.stop(False)
        if self.state:
            if redo:
                self.state.redo()
            else:
                self.state.undo()
            self.restore_controls()
            self.refresh_status()
            self.changed.emit()

    def _append_anchor(self, anchor):
        row = self.anchor_table.rowCount()
        self.anchor_table.insertRow(row)
        self.anchor_table.setItem(row, 0, QTableWidgetItem(f"{anchor.time:.17g}"))
        self.anchor_table.setItem(row, 1, QTableWidgetItem(f"{anchor.value:.17g}"))

    def add_anchor(self, time, value):
        if self.state is None:
            return
        self.loading = True
        self._append_anchor(Anchor(time, value))
        self.loading = False
        self.edited()

    def add_default_anchor(self):
        if self.state:
            trace = self.state.trace
            try:
                used = {
                    float(self.anchor_table.item(row, 0).text())
                    for row in range(self.anchor_table.rowCount())
                }
            except (ValueError, AttributeError):
                self.status.setText("Correct existing anchor times before adding another anchor.")
                return
            count = len(trace.time)
            candidates = (0, count - 1, count // 2, count // 4, 3 * count // 4)
            index = next((i for i in candidates if trace.source_time[i] not in used), None)
            if index is None:
                index = next(
                    (i for i, time in enumerate(trace.source_time) if time not in used), None
                )
            if index is None:
                self.status.setText("Every sampled coordinate already has an anchor.")
                return
            result = self.state.preview or self.state.applied
            value = result.baseline[index] if result else trace.signal[index]
            self.add_anchor(trace.source_time[index], value)

    def _append_region(self, region):
        row = self.region_table.rowCount()
        self.region_table.insertRow(row)
        self.region_table.setItem(row, 0, QTableWidgetItem(f"{region.start:.17g}"))
        self.region_table.setItem(row, 1, QTableWidgetItem(f"{region.end:.17g}"))
        kind = QComboBox()
        kind.addItem("Peak", "Protected peak")
        kind.addItem("Artifact", "Excluded artifact")
        kind.setCurrentIndex(kind.findData(region.kind))
        kind.setToolTip("Peak: protect peak signal. Artifact: exclude an artifact from estimation.")
        kind.currentTextChanged.connect(self.edited)
        self.region_table.setCellWidget(row, 2, kind)

    def add_region(self):
        if self.state:
            x = self.state.trace.source_time
            span = x[-1] - x[0]
            self.loading = True
            self._append_region(MaskRegion(x[0] + span * 0.25, x[0] + span * 0.5))
            self.loading = False
            self.edited()

    def move_region(self, row, start, end):
        self.loading = True
        self.region_table.item(row, 0).setText(f"{start:.17g}")
        self.region_table.item(row, 1).setText(f"{end:.17g}")
        self.loading = False
        self.edited()

    def remove_rows(self, table):
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        self.loading = True
        for row in rows:
            table.removeRow(row)
        self.loading = False
        self.edited()

    def shutdown(self):
        self.debounce.stop()
        self.controller.shutdown()
