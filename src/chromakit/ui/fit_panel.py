"""Guided region fitting, parameter constraints, and live component/residual views."""

from dataclasses import replace

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chromakit.analysis.deconvolution import (
    FitProblem,
    curves,
    fit,
    initialize,
    validate,
    window_data,
)
from chromakit.ui.fit_tasks import FitController
from chromakit.ui.peak_panel import spin

PALETTE = ["#169C89", "#D79622", "#9271C6", "#329ECE", "#CB6C88", "#63864D", "#AE7A50", "#5776C0"]


class FitPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.loading = False
        self.busy = False
        self.alternatives = ()
        self.controller = FitController(self)
        self.controller.live.connect(self.live_preview)
        self.controller.succeeded.connect(self.ready)
        self.controller.failed.connect(self.failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self.run_fit)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        title = QLabel("OVERLAPPING PEAKS")
        title.setObjectName("section")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        explanation = QLabel(
            "1  Apply a baseline.\n2  Frame an overlapping group.\n"
            "3  Choose a count, initialize, then fit.\n\n"
            "Edit guesses, bounds and locks in the parameter table. "
            "Compare counts and inspect residuals before accepting areas."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.start, self.end = spin(-1e12, 1e12), spin(-1e12, 1e12, 1)
        self.start.valueChanged.connect(self.window_changed)
        self.end.valueChanged.connect(self.window_changed)
        form.addRow("Window start", self.start)
        form.addRow("Window end", self.end)
        self.count = QSpinBox()
        self.count.setRange(1, 8)
        self.count.setValue(3)
        form.addRow("Components", self.count)
        self.shape = QComboBox()
        self.shape.addItems(["Right tail", "Gaussian", "Left tail"])
        form.addRow("Starting shape", self.shape)
        self.negative = QCheckBox("Start with negative peaks")
        form.addRow(self.negative)
        self.loss = QComboBox()
        self.loss.addItems(["Least squares", "Robust (soft L1)"])
        self.loss.currentIndexChanged.connect(self.options_changed)
        form.addRow("Objective", self.loss)
        self.starts = QSpinBox()
        self.starts.setRange(1, 8)
        self.starts.setValue(3)
        self.starts.valueChanged.connect(self.options_changed)
        form.addRow("Starting attempts", self.starts)
        layout.addLayout(form)
        self.initialize_button = QPushButton("Initialize components")
        self.initialize_button.clicked.connect(self.initialize)
        layout.addWidget(self.initialize_button)
        self.live = QCheckBox("Refit automatically after edits")
        self.live.setChecked(True)
        layout.addWidget(self.live)
        self.live.toggled.connect(self.live_changed)
        row = QHBoxLayout()
        self.fit_button = QPushButton("Fit components")
        self.fit_button.setObjectName("primary")
        self.fit_button.clicked.connect(self.run_fit)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_requested)
        row.addWidget(self.fit_button)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.use_button = QPushButton("Use fitted values as guesses")
        self.use_button.clicked.connect(self.use_fitted)
        layout.addWidget(self.use_button)
        self.apply_button = QPushButton("Accept fit")
        self.apply_button.clicked.connect(self.accept)
        layout.addWidget(self.apply_button)
        self.restore_button = QPushButton("Restore accepted fit")
        self.restore_button.clicked.connect(self.restore)
        layout.addWidget(self.restore_button)
        self.compare_button = QPushButton("Compare 2–5 components")
        self.compare_button.setToolTip(
            "Fresh automatic guesses for each count; current custom constraints are not reused."
        )
        self.compare_button.clicked.connect(self.compare_counts)
        layout.addWidget(self.compare_button)
        self.stability_button = QPushButton("Analyze fit stability…")
        self.stability_button.clicked.connect(self.open_stability)
        layout.addWidget(self.stability_button)
        self.status = QLabel("Apply a baseline to begin.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.diagnostics = QLabel("")
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.diagnostics)
        layout.addStretch()
        self.workspace = QWidget()
        outer = QVBoxLayout(self.workspace)
        outer.setContentsMargins(14, 12, 14, 12)
        heading = QLabel("DECONVOLUTION · APPLIED CORRECTED SIGNAL")
        heading.setObjectName("section")
        outer.addWidget(heading)
        self.plot = pg.PlotWidget(background="white")
        self.plot.setMinimumHeight(230)
        self.plot.setMaximumHeight(310)
        self.plot.addLegend(offset=(12, 10), labelTextColor="#52656E")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.raw = self.plot.plot(pen=pg.mkPen("#8BA4AD", width=1.8), name="Corrected observations")
        self.total = self.plot.plot(pen=pg.mkPen("#24343F", width=2), name="Component sum")
        self.component_curves = [
            self.plot.plot(pen=pg.mkPen(color, width=1.8), name=f"C{i + 1}")
            for i, color in enumerate(PALETTE)
        ]
        for i, curve in enumerate(self.component_curves):
            curve.hide()
            sample, legend_label = self.plot.getPlotItem().legend.items[i + 2]
            sample.hide()
            legend_label.hide()
        self.region = pg.LinearRegionItem(
            brush=pg.mkBrush(22, 156, 137, 15), pen=pg.mkPen("#169C89")
        )
        self.plot.addItem(self.region, ignoreBounds=True)
        self.region.sigRegionChangeFinished.connect(self.region_changed)
        outer.addWidget(self.plot)
        self.residual_plot = pg.PlotWidget(background="white")
        self.residual_plot.setMinimumHeight(110)
        self.residual_plot.setMaximumHeight(130)
        self.residual_plot.setXLink(self.plot)
        self.residual_plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#AABBC2")))
        self.residual = self.residual_plot.plot(pen=pg.mkPen("#8065BA", width=1.4))
        self.residual_plot.setLabel("left", "Residual (data − fit)")
        outer.addWidget(self.residual_plot)
        self.plot_note = QLabel("No fitted model yet.")
        self.plot_note.setWordWrap(True)
        outer.addWidget(self.plot_note)
        self.table_tabs = QTabWidget()
        self.table_tabs.setMinimumHeight(245)
        self.table_tabs.setMaximumHeight(310)
        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        parameter_page = QWidget()
        parameter_layout = QVBoxLayout(parameter_page)
        comparison_page = QWidget()
        comparison_layout = QVBoxLayout(comparison_page)
        self.table_tabs.addTab(result_page, "Fitted areas")
        self.table_tabs.addTab(parameter_page, "Parameters & bounds")
        self.table_tabs.addTab(comparison_page, "Count comparison")
        outer.addWidget(self.table_tabs)
        parameter_layout.addWidget(
            QLabel("Double-click to edit; select a row to highlight its component.")
        )
        self.parameters = QTableWidget(0, 7)
        self.parameters.setHorizontalHeaderLabels(
            ["Component", "Shape", "Parameter", "Value", "Lower", "Upper", "Lock"]
        )
        self.parameters.setMinimumHeight(190)
        self.parameters.setMaximumHeight(230)
        self.parameters.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.parameters.horizontalHeader().setStretchLastSection(True)
        self.parameters.itemChanged.connect(self.parameter_changed)
        self.parameters.itemSelectionChanged.connect(self.highlight)
        parameter_layout.addWidget(self.parameters)
        self.results = QTableWidget(0, 8)
        self.results.setHorizontalHeaderLabels(
            [
                "Component",
                "Shape",
                "Apex",
                "Height",
                "Full area",
                "Window area",
                "Area SE*",
                "Review flags",
            ]
        )
        self.results.setMinimumHeight(140)
        self.results.setMaximumHeight(190)
        self.results.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        result_layout.addWidget(self.results)
        note = QLabel(
            "*Local covariance estimate, conditional on the chosen model, count and baseline; "
            "unavailable for robust, constrained or ill-conditioned fits. "
            "Components do not establish compound identity."
        )
        note.setWordWrap(True)
        result_layout.addWidget(note)
        comparison_layout.addWidget(
            QLabel("Fresh guesses for each count · click a row to review its preview")
        )
        self.comparison = QTableWidget(0, 6)
        self.comparison.setHorizontalHeaderLabels(
            ["Count", "RMSE", "AICc", "BIC", "Converged", "Review warnings"]
        )
        self.comparison.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.comparison.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.comparison.horizontalHeader().setStretchLastSection(True)
        self.comparison.setMinimumHeight(135)
        self.comparison.setMaximumHeight(180)
        self.comparison.cellClicked.connect(self.choose_alternative)
        comparison_layout.addWidget(self.comparison)
        for plot in (self.plot, self.residual_plot):
            plot.setMenuEnabled(False)
            plot.getPlotItem().hideButtons()
            for position in ("left", "bottom"):
                axis = plot.getAxis(position)
                axis.setPen(pg.mkPen("#CDD8DC"))
                axis.setTextPen(pg.mkPen("#637780"))
                axis.enableAutoSIPrefix(False)
        self.refresh_controls()

    def set_state(self, state):
        self.cancel()
        self.state = state
        self.alternatives = ()
        self.comparison.setRowCount(0)
        self._applied = object()
        self.loading = True
        if state and state.recipe:
            self.start.setValue(state.recipe.start)
            self.end.setValue(state.recipe.end)
            self.count.setValue(len(state.recipe.components))
            self.shape.setCurrentText(state.recipe.components[0].model)
            self.negative.setChecked(state.recipe.components[0].area.value < 0)
            self.loss.setCurrentIndex(state.recipe.loss != "linear")
            self.starts.setValue(state.recipe.starts)
        elif state:
            x = state.baseline_state.trace.display_time
            self.start.setValue(float(x[0]))
            self.end.setValue(float(x[-1]))
        self.loading = False
        self.populate()
        self.sync_baseline()

    def sync_baseline(self):
        applied = self.state.baseline_state.applied if self.state else None
        if getattr(self, "_applied", object()) is applied:
            return
        self._applied = applied
        self.alternatives = ()
        self.comparison.setRowCount(0)
        self.cancel()
        state = self.state
        self.raw.clear()
        if state and state.baseline_state.applied:
            trace = state.baseline_state.trace
            y = state.baseline_state.applied.corrected
            # Preserve acquisition gaps in display too.
            x = trace.display_time.copy()
            x[1:][trace.gap_after] = np.nan
            self.raw.setData(x, y)
            self.plot.setLabel("bottom", "Time", units=trace.time_unit)
            self.residual_plot.setLabel("bottom", "Time", units=trace.time_unit)
            self.plot.setLabel("left", "Corrected signal", units=trace.signal_unit)
            self.region.setBounds((float(trace.display_time[0]), float(trace.display_time[-1])))
            self.plot.setXRange(self.start.value(), self.end.value(), padding=0.03)
        result = state.preview or state.result if state else None
        if state and state.valid(result) and result.recipe == state.recipe:
            self.show_result(result)
        elif (
            state
            and state.baseline_state.applied
            and state.recipe
            and state.preview is None
            and (result is None or state.valid(result))
        ):
            self.results.setRowCount(0)
            self.diagnostics.clear()
            self.restore_display()
            self.status.setText("Draft guesses restored. Fit again or restore the accepted fit.")
        else:
            self.clear_fit()
            self.status.setText(
                "Fit is stale: baseline changed. Initialize or refit."
                if result
                else "Frame an overlap, then initialize components."
                if state and state.baseline_state.applied
                else "Apply a baseline to begin."
            )
            self.results.setRowCount(0)
        self.refresh_controls()

    def refresh_controls(self):
        available = bool(self.state and self.state.baseline_state.applied)
        recipe = self.state.recipe if self.state else None
        self.initialize_button.setEnabled(available)
        self.fit_button.setEnabled(available and recipe is not None)
        self.compare_button.setEnabled(available and not self.busy)
        self.cancel_button.setEnabled(self.busy)
        current = bool(
            self.state
            and self.state.valid(self.state.preview)
            and self.state.preview.recipe == recipe
        )
        self.apply_button.setEnabled(
            current and not self.busy and self.state.preview is not self.state.result
        )
        self.use_button.setEnabled(current and not self.busy)
        self.restore_button.setEnabled(bool(self.state and self.state.valid(self.state.result)))
        self.parameters.setEnabled(available)

    def cancel(self):
        self.timer.stop()
        self.controller.cancel()
        self.busy = False
        self.refresh_controls()

    def cancel_requested(self):
        self.cancel()
        self.restore_display()
        self.status.setText("Fit cancelled. Edit guesses or fit again.")

    def restore_display(self):
        if not self.state or not self.state.recipe:
            self.clear_fit()
            return
        if self.state.valid(self.state.preview) and self.state.preview.recipe == self.state.recipe:
            self.show_result(self.state.preview)
            return
        try:
            x, y = window_data(
                self.state.baseline_state.trace,
                self.state.baseline_state.applied,
                self.state.recipe.start,
                self.state.recipe.end,
            )
            self.draw(x, curves(x, self.state.recipe.components), y)
            self.plot_note.setText("GUESS PREVIEW · click Fit components to optimize")
        except FitProblem:
            self.clear_fit()

    def initialize(self):
        if not self.state or not self.state.baseline_state.applied:
            return
        self.cancel()
        try:
            self.state.recipe = initialize(
                self.state.baseline_state.trace,
                self.state.baseline_state.applied,
                self.start.value(),
                self.end.value(),
                self.count.value(),
                self.shape.currentText(),
                self.negative.isChecked(),
            )
            self.state.recipe = replace(
                self.state.recipe,
                loss="soft_l1" if self.loss.currentIndex() else "linear",
                starts=self.starts.value(),
            )
        except FitProblem as error:
            self.failed(str(error))
            return
        self.populate()
        self.table_tabs.setCurrentIndex(1)
        self.edited()

    def populate(self):
        self.loading = True
        recipe = self.state.recipe if self.state else None
        rows = (
            [
                (component, name)
                for component in recipe.components
                for name in ("area", "center", "sigma", "tau")
                if name != "tau" or component.model != "Gaussian"
            ]
            if recipe
            else []
        )
        self.rows = [(component.id, name) for component, name in rows]
        self.parameters.setRowCount(len(rows))
        for row, (component, name) in enumerate(rows):
            p = getattr(component, name)
            for column, value in enumerate(
                [
                    component.id,
                    component.model,
                    name,
                    f"{p.value:.12g}",
                    f"{p.lower:.12g}",
                    f"{p.upper:.12g}",
                    "",
                ]
            ):
                item = QTableWidgetItem(value)
                if column in (0, 2):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 1:
                    item.setToolTip(
                        "Gaussian, Right tail, or Left tail "
                        "(applies to all rows of this component)."
                    )
                if column == 2:
                    item.setToolTip(
                        "center = Gaussian location μ; tailed model apex is reported separately. "
                        "sigma = Gaussian width; tau = exponential tail time. "
                        "Area = signed full model integral."
                    )
                if column == 6:
                    item.setFlags(
                        (item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        & ~Qt.ItemFlag.ItemIsEditable
                    )
                    item.setCheckState(
                        Qt.CheckState.Checked if p.locked else Qt.CheckState.Unchecked
                    )
                self.parameters.setItem(row, column, item)
        self.loading = False
        self.update_region()

    def parameter_changed(self, item):
        if self.loading or not self.state or not self.state.recipe:
            return
        identifier, name = self.rows[item.row()]
        recipe = self.state.recipe
        component = next(c for c in recipe.components if c.id == identifier)
        try:
            if item.column() == 1:
                component = replace(component, model=item.text())
            else:
                p = getattr(component, name)
                if item.column() == 6:
                    p = replace(p, locked=item.checkState() == Qt.CheckState.Checked)
                else:
                    p = replace(
                        p, **{["value", "lower", "upper"][item.column() - 3]: float(item.text())}
                    )
                component = replace(component, **{name: p})
            updated = replace(
                recipe,
                components=tuple(component if c.id == identifier else c for c in recipe.components),
            )
            validate(updated)
        except (ValueError, FitProblem) as error:
            self.status.setText(f"Edit rejected: {error}")
            self.populate()
            return
        self.state.recipe = updated
        self.populate()
        self.edited()

    def window_changed(self):
        if self.loading:
            return
        if self.state and self.state.recipe:
            self.state.recipe = replace(
                self.state.recipe, start=self.start.value(), end=self.end.value()
            )
        self.update_region()
        self.edited()

    def update_region(self):
        self.region.blockSignals(True)
        self.region.setRegion((self.start.value(), self.end.value()))
        self.region.blockSignals(False)

    def region_changed(self):
        self.loading = True
        start, end = self.region.getRegion()
        self.start.setValue(start)
        self.end.setValue(end)
        self.loading = False
        self.window_changed()

    def options_changed(self):
        if self.loading or not self.state or not self.state.recipe:
            return
        self.state.recipe = replace(
            self.state.recipe,
            loss="soft_l1" if self.loss.currentIndex() else "linear",
            starts=self.starts.value(),
        )
        self.edited()

    def live_changed(self, checked):
        if checked:
            self.edited()
        else:
            self.timer.stop()

    def edited(self):
        self.cancel()
        if not self.state or not self.state.recipe or not self.state.baseline_state.applied:
            return
        self.state.preview = None
        self.results.setRowCount(0)
        self.diagnostics.clear()
        try:
            validate(self.state.recipe)
            x, y = window_data(
                self.state.baseline_state.trace,
                self.state.baseline_state.applied,
                self.state.recipe.start,
                self.state.recipe.end,
            )
            self.draw(x, curves(x, self.state.recipe.components), y)
            self.plot_note.setText(
                "LIVE GUESS PREVIEW · residual = corrected observations − component sum"
            )
            self.status.setText(
                "Guesses updated. Fitting will start shortly."
                if self.live.isChecked()
                else "Guesses updated. Click Fit components."
            )
            if self.live.isChecked():
                self.timer.start()
        except FitProblem as error:
            self.clear_fit()
            self.status.setText(str(error))
        self.refresh_controls()
        self.changed.emit()

    def run_fit(self):
        if not self.state or not self.state.recipe or not self.state.baseline_state.applied:
            return
        self.timer.stop()
        self.busy = True
        self.results.setRowCount(0)
        self.diagnostics.clear()
        self.status.setText("Fitting components… You can cancel or edit to replace this run.")
        self.refresh_controls()
        trace, baseline, recipe = (
            self.state.baseline_state.trace,
            self.state.baseline_state.applied,
            self.state.recipe,
        )
        self.controller.request_operation(
            lambda cancel, update: fit(trace, baseline, recipe, cancel, update)
        )

    def live_preview(self, snapshot):
        if self.busy:
            self.draw(*snapshot)
            self.plot_note.setText("FITTING IN PROGRESS · provisional components and residuals")

    def ready(self, result):
        self.busy = False
        if isinstance(result, tuple):
            self.alternatives = result
            self.comparison.setRowCount(len(result))
            for row, alternative in enumerate(result):
                values = [
                    len(alternative.peaks),
                    alternative.rmse,
                    alternative.aicc,
                    alternative.bic,
                    "Yes" if alternative.converged else "No",
                    "; ".join(alternative.warnings[1:]),
                ]
                for column, value in enumerate(values):
                    self.comparison.setItem(
                        row,
                        column,
                        QTableWidgetItem(
                            "—"
                            if value is None
                            else f"{value:.6g}"
                            if isinstance(value, float)
                            else str(value)
                        ),
                    )
            self.restore_display()
            self.table_tabs.setCurrentIndex(2)
            self.status.setText(
                "Comparison complete. Select a count to review; no count is accepted automatically."
            )
            self.refresh_controls()
            return
        if self.state and self.state.valid(result) and result.recipe == self.state.recipe:
            self.state.preview = result
            self.show_result(result)
        self.refresh_controls()
        self.changed.emit()

    def compare_counts(self):
        if not self.state or not self.state.baseline_state.applied:
            return
        self.cancel()
        trace, baseline = self.state.baseline_state.trace, self.state.baseline_state.applied
        start, end, model = self.start.value(), self.end.value(), self.shape.currentText()
        negative, loss, starts = (
            self.negative.isChecked(),
            "soft_l1" if self.loss.currentIndex() else "linear",
            self.starts.value(),
        )

        def operation(cancel, update):
            results = []
            for count in range(2, 6):
                recipe = initialize(trace, baseline, start, end, count, model, negative)
                results.append(
                    fit(trace, baseline, replace(recipe, loss=loss, starts=starts), cancel, update)
                )
            return tuple(results)

        self.busy = True
        self.results.setRowCount(0)
        self.diagnostics.clear()
        self.status.setText("Comparing 2–5 components with fresh guesses…")
        self.refresh_controls()
        self.controller.request_operation(operation)

    def choose_alternative(self, row, _column):
        if not 0 <= row < len(self.alternatives) or not self.state:
            return
        result = self.alternatives[row]
        if not self.state.valid(result):
            return
        self.cancel()
        self.state.recipe, self.state.preview = result.recipe, result
        self.table_tabs.setCurrentIndex(0)
        self.loading = True
        self.start.setValue(result.recipe.start)
        self.end.setValue(result.recipe.end)
        self.count.setValue(len(result.peaks))
        self.loading = False
        self.populate()
        self.show_result(result)
        self.refresh_controls()
        self.changed.emit()

    def failed(self, message):
        self.busy = False
        self.restore_display()
        self.status.setText(message)
        self.refresh_controls()

    def clear_fit(self):
        self.total.clear()
        self.residual.clear()
        for i, curve in enumerate(self.component_curves):
            curve.clear()
            curve.hide()
            sample, legend_label = self.plot.getPlotItem().legend.items[i + 2]
            sample.hide()
            legend_label.hide()
        self.plot_note.setText("No current fitted model.")
        self.diagnostics.clear()

    def draw(self, x, component_curves, y):
        total = sum(component_curves, np.zeros_like(x))
        self.total.setData(x, total)
        self.residual.setData(x, y - total)
        for i, curve in enumerate(self.component_curves):
            visible = i < len(component_curves)
            curve.setVisible(visible)
            sample, legend_label = self.plot.getPlotItem().legend.items[i + 2]
            sample.setVisible(visible)
            legend_label.setVisible(visible)
            if i < len(component_curves):
                curve.setData(x, component_curves[i])
        self.residual_plot.enableAutoRange(axis="y", enable=True)

    def show_result(self, result):
        self.draw(result.x, result.curves, result.observed)
        accepted = result is self.state.result
        self.plot_note.setText(
            f"{'ACCEPTED FIT' if accepted else 'FIT PREVIEW'} · {len(result.peaks)} components "
            f"· RMSE {result.rmse:.5g} {result.signal_unit}"
        )
        self.status.setText(
            "Fit accepted in this session."
            if accepted
            else "Fit converged. Review diagnostics, then accept."
            if result.converged
            else "Fit did not converge. Review settings before accepting."
        )

        def metric(value):
            return "unavailable" if value is None else f"{value:.6g}"

        self.diagnostics.setText(
            f"RMSE  {result.rmse:.6g} {result.signal_unit}\nR²  {metric(result.r_squared)}\n"
            f"AICc  {metric(result.aicc)} · BIC  {metric(result.bic)}\n"
            f"Free parameters  {result.free_parameters}\nEvaluations  {result.evaluations}\n"
            f"Jacobian condition  {metric(result.condition)}\n\n{result.message}\n\n"
            + "\n\n".join(result.warnings)
        )
        self.results.setHorizontalHeaderLabels(
            [
                "Component",
                "Shape",
                f"Apex ({result.time_unit})",
                f"Height ({result.signal_unit})",
                f"Full area ({result.signal_unit} × {result.time_unit})",
                "Window area",
                "Area SE*",
                "Review flags",
            ]
        )
        self.results.setRowCount(len(result.peaks))
        for row, peak in enumerate(result.peaks):
            values = [
                peak.id,
                peak.model,
                peak.retention_time,
                peak.height,
                peak.area,
                peak.window_area,
                peak.area_se,
                "; ".join(peak.flags),
            ]
            for column, value in enumerate(values):
                self.results.setItem(
                    row,
                    column,
                    QTableWidgetItem(
                        "—"
                        if value is None
                        else f"{value:.7g}"
                        if isinstance(value, float)
                        else str(value)
                    ),
                )

    def highlight(self):
        rows = self.parameters.selectionModel().selectedRows()
        row = rows[0].row() if rows else self.parameters.currentRow()
        identifier = self.rows[row][0] if 0 <= row < len(self.rows) else None
        recipe = self.state.recipe if self.state else None
        for i, curve in enumerate(self.component_curves):
            selected = (
                recipe and i < len(recipe.components) and recipe.components[i].id == identifier
            )
            curve.setPen(pg.mkPen(PALETTE[i], width=3 if selected else 1.8))

    def use_fitted(self):
        if self.state and self.state.valid(self.state.preview):
            self.state.recipe = replace(
                self.state.preview.recipe, components=self.state.preview.fitted
            )
            self.populate()
            self.edited()

    def accept(self):
        if self.state and self.state.accept():
            self.show_result(self.state.result)
            self.refresh_controls()
            self.changed.emit()

    def restore(self):
        if self.state and self.state.valid(self.state.result):
            self.cancel()
            self.state.recipe = self.state.result.recipe
            self.state.preview = self.state.result
            self.set_state(self.state)
            self.changed.emit()

    def history_action(self, redo=False):
        if self.state:
            self.cancel()
            self.state.undo(redo)
            self.set_state(self.state)
            self.changed.emit()

    def open_stability(self):
        from chromakit.ui.stability_dialog import StabilityDialog

        if self.state and self.state.valid(self.state.result):
            StabilityDialog(self.window(), self.state).exec()
        else:
            self.status.setText("Accept a current fit before analyzing its stability.")

    def shutdown(self):
        self.timer.stop()
        self.controller.shutdown()
