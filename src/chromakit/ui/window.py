"""Single active chromatogram workspace with interactive inspection."""

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chromakit.application.baselines import BaselineState
from chromakit.application.deconvolution import FitState
from chromakit.application.peaks import PeakState
from chromakit.domain import Trace
from chromakit.ui.baseline_panel import BaselinePanel
from chromakit.ui.fit_panel import FitPanel
from chromakit.ui.import_dialog import ImportDialog
from chromakit.ui.models import TraceModel
from chromakit.ui.peak_panel import PeakPanel
from chromakit.ui.theme import COLORS


def label(text: str, style: str = "", wrap=False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if style:
        widget.setObjectName(style)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, callback, style: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if style:
        widget.setObjectName(style)
    return widget


class TraceGlyph(QWidget):
    """A deliberately abstract trace symbol, never presented as sample data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 78)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pg.mkColor(COLORS["accent_soft"]))
        painter.drawRoundedRect(0, 0, 96, 78, 18, 18)
        path = QPainterPath()
        path.moveTo(13, 56)
        path.cubicTo(25, 56, 24, 54, 30, 48)
        path.cubicTo(36, 42, 34, 22, 41, 22)
        path.cubicTo(49, 22, 45, 56, 56, 56)
        path.cubicTo(65, 56, 61, 38, 69, 38)
        path.cubicTo(76, 38, 71, 56, 83, 56)
        painter.setPen(QPen(pg.mkColor(COLORS["accent"]), 2.5))
        painter.drawPath(path)


class ChromatogramPlot(pg.PlotWidget):
    """Stable layout hints rather than inheriting the last rendered plot size."""

    def sizeHint(self):
        return QSize(600, getattr(self, "preferred_height", 280))

    def minimumSizeHint(self):
        return QSize(200, min(getattr(self, "preferred_height", 280), 230))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.traces: list[Trace] = []
        self.baseline_states: list[BaselineState] = []
        self.peak_states: list[PeakState] = []
        self.fit_states: list[FitState] = []
        self.peak_region = None
        self.peaks_focused = False
        self.region_items = []
        self.trace: Trace | None = None
        self.import_dialog: ImportDialog | None = None
        self.display_x = np.array([])
        self.setWindowTitle("ChromaKit · Chromatogram workspace")
        self.resize(1400, 880)
        self.setMinimumSize(1050, 680)
        self.setAcceptDrops(True)
        self._build_menu()
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 17, 24, 17)
        header_layout.setSpacing(16)
        header_layout.addWidget(label("ChromaKit", "brand"))
        header_layout.addWidget(label("/  Chromatogram workspace", "muted"))
        header_layout.addStretch()
        header_layout.addWidget(label("RESEARCH", "badge"))
        self.import_button = button("Import chromatogram…", self.choose_file, "primary")
        header_layout.addWidget(self.import_button)
        root.addWidget(header)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(190)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 24, 14, 16)
        sidebar_layout.setSpacing(14)
        row = QHBoxLayout()
        row.addWidget(label("CHROMATOGRAMS", "section"))
        row.addStretch()
        self.sample_count = label("0", "muted")
        row.addWidget(self.sample_count)
        sidebar_layout.addLayout(row)
        sidebar_layout.addWidget(
            label("One trace at a time.\nAll original samples preserved.", "muted", True)
        )
        self.samples = QListWidget()
        self.samples.setAccessibleName("Imported chromatograms")
        self.samples.currentRowChanged.connect(self.select_trace)
        sidebar_layout.addWidget(self.samples, 1)
        self.remove_button = button("Remove selected", self.remove_trace, "quiet")
        self.remove_button.setEnabled(False)
        sidebar_layout.addWidget(self.remove_button)
        sidebar_layout.addWidget(label("LOCAL WORKSPACE", "section"))
        sidebar_layout.addWidget(
            label("CSV · TSV · TXT\nImports stay in memory for this session.", "muted", True)
        )
        splitter.addWidget(sidebar)

        workspace = QWidget()
        workspace.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(20, 22, 20, 18)
        layout.setSpacing(15)
        heading = QHBoxLayout()
        heading.addWidget(label("Chromatogram", "title"))
        heading.addStretch()
        self.raw_badge = label("RAW SIGNAL", "badge")
        self.raw_badge.setMinimumWidth(135)
        self.raw_badge.hide()
        heading.addWidget(self.raw_badge)
        self.baseline_button = button("Baseline…", self.open_baseline)
        self.baseline_button.setEnabled(False)
        heading.addWidget(self.baseline_button)
        layout.addLayout(heading)
        self.subtitle = label("Import a time–signal file to begin exploring your data.", "muted")
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.subtitle)
        self.warning = label("", "warning", True)
        self.warning.hide()
        layout.addWidget(self.warning)
        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(340)
        self.stack.addWidget(self._empty_state())
        self.stack.addWidget(self._plot_card())
        layout.addWidget(self.stack, 1)
        self.data_card = QFrame()
        self.data_card.setObjectName("card")
        data_layout = QVBoxLayout(self.data_card)
        data_layout.setContentsMargins(15, 12, 15, 10)
        self.data_heading = label("SOURCE SAMPLES", "section")
        data_layout.addWidget(self.data_heading)
        self.data_table = QTableView()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.data_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.data_table.horizontalHeader().setStretchLastSection(True)
        self.data_table.clicked.connect(self.inspect_row)
        data_layout.addWidget(self.data_table)
        self.data_card.setMaximumHeight(225)
        self.data_card.setMinimumHeight(180)
        self.data_card.hide()
        layout.addWidget(self.data_card)
        self.peak_card = QFrame()
        self.peak_card.setObjectName("card")
        peak_layout = QVBoxLayout(self.peak_card)
        peak_layout.setContentsMargins(14, 12, 14, 12)
        self.peak_heading = label("PEAK RESULTS", "section")
        peak_layout.addWidget(self.peak_heading)
        self.peak_layout = peak_layout
        self.peak_card.setMinimumHeight(190)
        self.peak_card.setMaximumHeight(260)
        self.peak_card.hide()
        layout.addWidget(self.peak_card)
        workspace_scroll = QScrollArea()
        workspace_scroll.setWidgetResizable(True)
        workspace_scroll.setWidget(workspace)
        workspace_scroll.setMinimumWidth(440)
        splitter.addWidget(workspace_scroll)
        splitter.addWidget(self._inspector())
        layout.addWidget(self.fit_panel.workspace)
        self.fit_panel.workspace.hide()
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([210, 850, 340])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready · Open a file or drop one into the workspace")
        self.session_note = label("ChromaKit 0.1  ·  Local session", "muted")
        self.statusBar().addPermanentWidget(self.session_note)

    def _build_menu(self):
        edit_menu = self.menuBar().addMenu("&Edit")
        self.undo_action = QAction("Undo baseline change", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(lambda: self.history_action())
        self.undo_action.setEnabled(False)
        edit_menu.addAction(self.undo_action)
        self.redo_action = QAction("Redo baseline change", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(lambda: self.history_action(redo=True))
        self.redo_action.setEnabled(False)
        edit_menu.addAction(self.redo_action)
        file_menu = self.menuBar().addMenu("&File")
        self.menuBar().insertMenu(edit_menu.menuAction(), file_menu)
        self.open_action = QAction("&Import chromatogram…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_file)
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        exit_action = QAction("&Quit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        view_menu = self.menuBar().addMenu("&View")
        self.fit_action = QAction("Fit entire trace", self)
        self.fit_action.setShortcut("Ctrl+0")
        self.fit_action.triggered.connect(self.fit_trace)
        self.fit_action.setEnabled(False)
        view_menu.addAction(self.fit_action)
        self.data_action = QAction("Show source samples", self)
        self.data_action.setCheckable(True)
        self.data_action.setEnabled(False)
        self.data_action.triggered.connect(self.toggle_data)
        view_menu.addAction(self.data_action)

    def _empty_state(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setSpacing(16)
        layout.addStretch()
        layout.addWidget(TraceGlyph(), 0, Qt.AlignmentFlag.AlignHCenter)
        title = label("A clear view of your chromatogram", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        description = label(
            "Bring in a time–signal file, review its columns,\n"
            "and explore every sample in an interactive plot.",
            "muted",
            True,
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)
        layout.addWidget(
            button("Choose a data file…", self.choose_file, "primary"),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        layout.addWidget(
            label("CSV, TSV or TXT  ·  You can also drop a file here", "muted"),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        layout.addStretch()
        return card

    def _plot_card(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(label("●", "badge"))
        self.plot_name = label("", "muted")
        self.plot_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tools.addWidget(self.plot_name, 1)
        tools.addWidget(button("Fit trace", self.fit_trace))
        self.zoom_button = button("Zoom box", self.toggle_zoom)
        self.zoom_button.setCheckable(True)
        self.zoom_button.setToolTip("Drag a rectangle to zoom; uncheck to pan. Scroll to zoom.")
        tools.addWidget(self.zoom_button)
        self.grid_button = button("Grid", self.toggle_grid)
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        tools.addWidget(self.grid_button)
        self.data_button = button("Data", self.toggle_data)
        self.data_button.setCheckable(True)
        tools.addWidget(self.data_button)
        layout.addLayout(tools)
        self.plot = ChromatogramPlot(background="white")
        self.plot.setMinimumHeight(230)
        self.plot.setMenuEnabled(False)
        self.plot.getPlotItem().hideButtons()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        for position in ("left", "bottom"):
            axis = self.plot.getAxis(position)
            axis.setPen(pg.mkPen("#CDD8DC"))
            axis.setTextPen(pg.mkPen(COLORS["muted"]))
            axis.enableAutoSIPrefix(False)
        self.plot.setLabel("bottom", "Time")
        self.plot.setLabel("left", "Signal")
        self.curve = self.plot.plot(pen=pg.mkPen(COLORS["accent"], width=1.8))
        self.baseline_curve = self.plot.plot(
            pen=pg.mkPen("#C58B30", width=2, style=Qt.PenStyle.DashLine)
        )
        self.anchor_points = pg.ScatterPlotItem(
            size=10, brush=pg.mkBrush("#C58B30"), pen=pg.mkPen("white", width=1.5)
        )
        self.plot.addItem(self.anchor_points, ignoreBounds=True)
        self.plot.scene().sigMouseClicked.connect(self.baseline_plot_clicked)
        self.marker = pg.ScatterPlotItem(
            size=9, brush=pg.mkBrush(COLORS["accent"]), pen=pg.mkPen("white", width=2)
        )
        self.plot.addItem(self.marker)
        self.cursor_line = pg.InfiniteLine(
            angle=90, pen=pg.mkPen("#A3C8CE", style=Qt.PenStyle.DashLine)
        )
        self.plot.addItem(self.cursor_line, ignoreBounds=True)
        self.cursor_line.hide()
        self.mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved, rateLimit=30, slot=self.mouse_moved
        )
        layout.addWidget(self.plot, 1)
        self.series_row = QWidget()
        series = QHBoxLayout(self.series_row)
        series.setContentsMargins(0, 0, 0, 0)
        self.raw_visible = QCheckBox("Raw")
        self.baseline_visible = QCheckBox("Baseline")
        self.corrected_visible = QCheckBox("Corrected")
        self.raw_visible.setStyleSheet("color: #667E8A")
        self.baseline_visible.setStyleSheet("color: #A87423")
        self.corrected_visible.setStyleSheet("color: #167D8D")
        for toggle in (self.raw_visible, self.baseline_visible, self.corrected_visible):
            toggle.setChecked(True)
            toggle.toggled.connect(self.update_series_visibility)
            series.addWidget(toggle)
        series.addStretch()
        self.baseline_caption = label("", "muted")
        series.addWidget(self.baseline_caption)
        layout.addWidget(self.series_row)
        self.series_row.hide()
        self.corrected_plot = ChromatogramPlot(background="white")
        self.corrected_plot.preferred_height = 170
        self.corrected_plot.setMinimumHeight(170)
        self.corrected_plot.setMaximumHeight(210)
        self.corrected_plot.setMenuEnabled(False)
        self.corrected_plot.getPlotItem().hideButtons()
        self.corrected_plot.setXLink(self.plot)
        self.corrected_plot.showGrid(x=True, y=True, alpha=0.15)
        for position in ("left", "bottom"):
            axis = self.corrected_plot.getAxis(position)
            axis.setPen(pg.mkPen("#CDD8DC"))
            axis.setTextPen(pg.mkPen(COLORS["muted"]))
            axis.enableAutoSIPrefix(False)
        self.corrected_curve = self.corrected_plot.plot(pen=pg.mkPen(COLORS["accent"], width=1.8))
        self.zero_line = pg.InfiniteLine(angle=0, pen=pg.mkPen("#BBC8CD"))
        self.corrected_plot.addItem(self.zero_line, ignoreBounds=True)
        self.corrected_marker = pg.ScatterPlotItem(
            size=7, brush=pg.mkBrush(COLORS["accent"]), pen=pg.mkPen("white")
        )
        self.corrected_plot.addItem(self.corrected_marker, ignoreBounds=True)
        self.corrected_mouse_proxy = pg.SignalProxy(
            self.corrected_plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self.corrected_mouse_moved,
        )
        self.peak_markers = pg.ScatterPlotItem(
            size=11, brush=pg.mkBrush("#8065BA"), pen=pg.mkPen("white", width=1.5)
        )
        self.corrected_plot.addItem(self.peak_markers)
        self.peak_markers.sigClicked.connect(self.peak_marker_clicked)
        layout.addWidget(self.corrected_plot)
        self.corrected_plot.hide()
        footer = QHBoxLayout()
        self.cursor_readout = label("Move over the trace to inspect a sample", "muted")
        self.cursor_readout.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.cursor_readout, 1)
        self.plot.setToolTip(
            "Scroll to zoom. Drag to pan, or enable Zoom box to select a rectangle."
        )
        layout.addLayout(footer)
        return card

    def _inspector(self):
        container = QWidget()
        container.setMinimumWidth(230)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 22, 20, 18)
        layout.setSpacing(14)
        layout.addWidget(label("TRACE DETAILS", "section"))
        card = QFrame()
        card.setObjectName("card")
        details = QVBoxLayout(card)
        details.setContentsMargins(18, 18, 18, 18)
        details.setSpacing(8)
        self.detail_labels = {}
        for key, title in (
            ("detector", "Detector"),
            ("channel", "Signal column"),
            ("points", "Samples"),
            ("time", "Time range"),
            ("signal", "Signal range"),
            ("units", "Units"),
            ("delimiter", "Text format"),
            ("encoding", "Encoding"),
        ):
            details.addWidget(label(title, "muted"))
            value = label("—", wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.detail_labels[key] = value
            details.addWidget(value)
            details.addSpacing(5)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(card)
        layout.addWidget(scroll, 1)
        source_card = QFrame()
        source_card.setObjectName("card")
        source_layout = QVBoxLayout(source_card)
        source_layout.setContentsMargins(16, 14, 16, 14)
        source_layout.addWidget(label("SOURCE & PROVENANCE", "section"))
        self.source_name = label("No source loaded", "muted", True)
        self.source_name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_layout.addWidget(self.source_name)
        self.source_hash = label("", "muted", True)
        source_layout.addWidget(self.source_hash)
        source_layout.addWidget(label("Raw observations are never modified.", "muted", True))
        layout.addWidget(source_card)
        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setMinimumWidth(325)
        self.inspector_tabs.addTab(container, "Trace details")
        self.baseline_panel = BaselinePanel()
        self.inspector_tabs.addTab(self.baseline_panel, "Baseline")
        self.peak_panel = PeakPanel()
        self.inspector_tabs.addTab(self.peak_panel, "Peaks")
        self.peak_layout.addWidget(self.peak_panel.table)
        self.peak_panel.changed.connect(self.render_peaks)
        self.fit_panel = FitPanel()
        self.inspector_tabs.addTab(self.fit_panel, "Fit peaks")
        self.fit_panel.changed.connect(self.update_history_actions)
        self.inspector_tabs.currentChanged.connect(self.render_fit_workspace)
        self.baseline_panel.changed.connect(self.render_baseline)
        self.baseline_panel.geometry_changed.connect(self.render_refinements)
        self.inspector_tabs.currentChanged.connect(
            lambda index: self.baseline_panel.set_active(index == 1)
        )
        self.inspector_tabs.currentChanged.connect(self.render_peaks)
        return self.inspector_tabs

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import chromatogram", "", "Text data (*.csv *.tsv *.txt);;All files (*)"
        )
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path):
        if self.import_dialog is not None:
            return
        self.import_dialog = ImportDialog(path, self)
        dialog = self.import_dialog
        try:
            if dialog.exec() == ImportDialog.DialogCode.Accepted and dialog.trace is not None:
                self.add_trace(dialog.trace)
        finally:
            self.import_dialog = None
            dialog.deleteLater()

    def add_trace(self, trace: Trace):
        self.traces.append(trace)
        self.baseline_states.append(BaselineState(trace))
        self.peak_states.append(PeakState(self.baseline_states[-1]))
        self.fit_states.append(FitState(self.baseline_states[-1]))
        item = QListWidgetItem(f"{trace.name}\n{trace.detector} · {len(trace.time):,} samples")
        item.setToolTip(f"{trace.name}\n{trace.source}")
        item.setSizeHint(QSize(180, 62))
        self.samples.addItem(item)
        self.sample_count.setText(str(len(self.traces)))
        self.samples.setCurrentRow(len(self.traces) - 1)
        self.statusBar().showMessage(f"Imported {trace.source.name} · {len(trace.time):,} samples")

    def select_trace(self, row: int):
        if not 0 <= row < len(self.traces):
            self.trace = None
            self.baseline_panel.set_state(None)
            self.peak_panel.set_state(None)
            self.fit_panel.set_state(None)
            self.baseline_button.setEnabled(False)
            self.render_baseline()
            self.stack.setCurrentIndex(0)
            self.raw_badge.hide()
            self.warning.hide()
            self.data_card.hide()
            self.fit_action.setEnabled(False)
            self.data_action.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.subtitle.setText("Import a time–signal file to begin exploring your data.")
            self.source_name.setText("No source loaded")
            self.source_hash.clear()
            for field in self.detail_labels.values():
                field.setText("—")
            old_model = self.data_table.model()
            self.data_table.setModel(None)
            if old_model is not None:
                old_model.deleteLater()
            self.curve.clear()
            self.marker.clear()
            self.display_x = np.array([])
            return
        trace = self.traces[row]
        self.trace = trace
        self.baseline_button.setEnabled(True)
        self.display_x = trace.display_time
        self.subtitle.setText(trace.name)
        self.subtitle.setToolTip(trace.name)
        self.plot_name.setText(trace.channel)
        self.plot_name.setToolTip(trace.channel)
        self.stack.setCurrentIndex(1)
        self.raw_badge.show()
        self.remove_button.setEnabled(True)
        self.fit_action.setEnabled(True)
        self.data_action.setEnabled(True)
        self.data_card.setVisible(self.data_button.isChecked())
        self.warning.setText("\n".join(trace.warnings))
        self.warning.setVisible(bool(trace.warnings))
        self.plot.setLabel(
            "bottom", "Time", units="" if trace.time_unit == "unknown" else trace.time_unit
        )
        self.plot.setLabel(
            "left", "Signal", units="" if trace.signal_unit == "unknown" else trace.signal_unit
        )
        self.corrected_plot.setLabel(
            "bottom", "Time", units="" if trace.time_unit == "unknown" else trace.time_unit
        )
        self.corrected_plot.setLabel(
            "left", "Corrected", units="" if trace.signal_unit == "unknown" else trace.signal_unit
        )
        connect = np.ones(len(trace.time), dtype=np.int32)
        connect[:-1] = ~trace.gap_after
        has_gaps = bool(np.any(trace.gap_after))
        # Display-only peak decimation keeps large continuous traces responsive.
        # Explicit gap connectivity takes precedence; source arrays stay untouched.
        self.curve.setDownsampling(auto=not has_gaps, method="peak")
        self.curve.setClipToView(True)
        self.curve.setData(self.display_x, trace.signal, connect=connect if has_gaps else "all")
        self.marker.clear()
        self.corrected_marker.clear()
        self.cursor_line.hide()
        self.cursor_readout.setText("Move over the trace to inspect a sample")
        self.fit_trace()
        details = {
            "detector": trace.detector,
            "channel": trace.channel,
            "points": f"{len(trace.time):,}",
            "time": f"{self.display_x[0]:.6g} – {self.display_x[-1]:.6g} {trace.time_unit}",
            "signal": f"{np.min(trace.signal):.6g} – {np.max(trace.signal):.6g}",
            "units": f"Time: {trace.time_unit}\nSignal: {trace.signal_unit}",
            "delimiter": trace.delimiter,
            "encoding": trace.encoding,
        }
        for key, value in details.items():
            self.detail_labels[key].setText(value)
        self.source_name.setText(trace.source.name)
        self.source_name.setToolTip(str(trace.source))
        self.source_hash.setText(f"SHA-256  {trace.source_hash[:16]}…")
        self.source_hash.setToolTip(trace.source_hash)
        self.source_name.setToolTip(
            f"{trace.source}\n"
            + "\n".join(f"{key}: {value}" for key, value in trace.import_settings)
        )
        old_model = self.data_table.model()
        self.data_table.setModel(TraceModel(trace, self.data_table))
        if old_model is not None:
            old_model.deleteLater()
        self.data_table.setColumnWidth(0, 180)
        self.baseline_panel.set_state(self.baseline_states[row])
        self.peak_panel.set_state(self.peak_states[row])
        self.fit_panel.set_state(self.fit_states[row])
        self.render_baseline()

    def remove_trace(self):
        row = self.samples.currentRow()
        if not 0 <= row < len(self.traces):
            return
        self.samples.blockSignals(True)
        self.traces.pop(row)
        self.baseline_states.pop(row)
        self.peak_states.pop(row)
        self.fit_states.pop(row)
        self.samples.takeItem(row)
        next_row = min(row, len(self.traces) - 1)
        self.samples.setCurrentRow(next_row)
        self.samples.blockSignals(False)
        self.select_trace(next_row)
        self.sample_count.setText(str(len(self.traces)))
        self.statusBar().showMessage("Removed from this session · Source file unchanged")

    def fit_trace(self):
        if self.trace is not None:
            target = (
                self.fit_panel.plot
                if self.inspector_tabs.currentIndex() == 3
                else self.corrected_plot
                if self.peaks_focused
                else self.plot
            )
            target.getViewBox().autoRange(padding=0.04)
            self.corrected_plot.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    def toggle_zoom(self, checked=False):
        mode = pg.ViewBox.RectMode if checked else pg.ViewBox.PanMode
        self.plot.getViewBox().setMouseMode(mode)
        self.corrected_plot.getViewBox().setMouseMode(mode)

    def toggle_grid(self, checked=False):
        self.plot.showGrid(x=checked, y=checked, alpha=0.15)
        self.corrected_plot.showGrid(x=checked, y=checked, alpha=0.15)

    def toggle_data(self, checked=False):
        self.data_button.setChecked(checked)
        self.data_action.setChecked(checked)
        self.data_card.setVisible(checked and self.trace is not None)

    def show_sample(self, index: int, corrected=False):
        if self.trace is None:
            return
        x, y = self.display_x[index], self.trace.signal[index]
        self.marker.setData([x], [y])
        self.cursor_line.setPos(x)
        self.cursor_line.show()
        self.cursor_readout.setText(
            f"Time {x:.7g} {self.trace.time_unit}  ·  Raw Signal {y:.7g} {self.trace.signal_unit}"
            f"  ·  #{index + 1:,}"
        )
        result = self.displayed_baseline()
        if result is not None:
            self.corrected_marker.setData([x], [result.corrected[index]])
            if corrected:
                self.cursor_readout.setText(
                    f"Time {x:.7g} {self.trace.time_unit} · Corrected "
                    f"{result.corrected[index]:.7g} {self.trace.signal_unit} · #{index + 1:,}"
                )
        self.cursor_readout.setToolTip(
            f"Raw: {y:.10g} {self.trace.signal_unit}"
            + (
                f"\nBaseline: {result.baseline[index]:.10g} {self.trace.signal_unit}"
                f"\nCorrected: {result.corrected[index]:.10g} {self.trace.signal_unit}"
                if result
                else ""
            )
        )

    def mouse_moved(self, event, corrected=False):
        if self.trace is None or (self.peaks_focused and not corrected):
            return
        position = event[0]
        plot = self.corrected_plot if corrected else self.plot
        if not plot.getViewBox().sceneBoundingRect().contains(position):
            return
        x = plot.getViewBox().mapSceneToView(position).x()
        index = min(int(np.searchsorted(self.display_x, x)), len(self.display_x) - 1)
        if index > 0 and abs(self.display_x[index - 1] - x) < abs(self.display_x[index] - x):
            index -= 1
        self.show_sample(index, corrected)

    def corrected_mouse_moved(self, event):
        self.mouse_moved(event, corrected=True)

    def inspect_row(self, index):
        self.show_sample(index.row())

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.open_path(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent):
        if self.traces:
            answer = QMessageBox.question(
                self,
                "Close workspace?",
                "Imported traces and baseline edits are held in memory for this session. "
                "Close the workspace? Your source files will remain unchanged.",
                QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Close:
                event.ignore()
                return
        self.baseline_panel.shutdown()
        self.peak_panel.shutdown()
        self.fit_panel.shutdown()
        event.accept()

    def open_baseline(self):
        if self.trace is not None:
            if self.inspector_tabs.currentIndex() == 1:
                self.baseline_panel.edited()
            else:
                self.inspector_tabs.setCurrentIndex(1)

    def displayed_baseline(self):
        state = self.baseline_panel.state
        if state is None:
            return None
        if self.baseline_panel.active and self.baseline_panel.valid and state.preview is not None:
            return state.preview
        return state.applied

    def render_baseline(self):
        if hasattr(self, "peak_panel"):
            self.peak_panel.sync_baseline()
            self.fit_panel.sync_baseline()
            self.render_peaks()
        state = self.baseline_panel.state
        self.update_history_actions()
        result = self.displayed_baseline()
        model = self.data_table.model()
        if isinstance(model, TraceModel):
            model.set_baseline(result)
        self.data_heading.setText(
            "SOURCE + BASELINE · PREVIEW"
            if result is not None and result is not state.applied
            else "SOURCE + BASELINE · APPLIED"
            if result is not None
            else "SOURCE SAMPLES"
        )
        if result is None or self.trace is None:
            self.baseline_curve.clear()
            self.corrected_curve.clear()
            self.corrected_marker.clear()
            editing = self.trace is not None and self.baseline_panel.active
            self.corrected_plot.setVisible(editing and self.corrected_visible.isChecked())
            self.series_row.setVisible(editing)
            self.baseline_caption.setText(
                "Updating…" if self.baseline_panel.busy else "No current preview"
            )
            self.raw_badge.setText("PREVIEW PENDING" if editing else "RAW SIGNAL")
            self.curve.setPen(pg.mkPen(COLORS["accent"], width=1.8))
            self.curve.show()
            return
        trace = self.trace
        has_gaps = bool(np.any(trace.gap_after))
        connect = np.ones(len(trace.time), dtype=np.int32)
        connect[:-1] = ~trace.gap_after
        for curve, data in (
            (self.baseline_curve, result.baseline),
            (self.corrected_curve, result.corrected),
        ):
            curve.setDownsampling(auto=not has_gaps, method="peak")
            curve.setClipToView(True)
            curve.setData(self.display_x, data, connect=connect if has_gaps else "all")
        self.curve.setPen(pg.mkPen("#667E8A", width=1.5))
        applied = state.applied is result
        self.raw_badge.setText("BASELINE APPLIED" if applied else "LIVE PREVIEW")
        self.baseline_caption.setText(
            "Applied · updating…"
            if applied and self.baseline_panel.busy
            else "Applied"
            if applied
            else "Preview"
        )
        self.baseline_caption.setToolTip("\n".join(result.warnings))
        self.corrected_plot.setLabel(
            "bottom", "Time", units="" if trace.time_unit == "unknown" else trace.time_unit
        )
        self.corrected_plot.setLabel(
            "left", "Corrected", units="" if trace.signal_unit == "unknown" else trace.signal_unit
        )
        self.series_row.show()
        self.update_series_visibility()

    def update_series_visibility(self):
        result = self.displayed_baseline() if hasattr(self, "baseline_panel") else None
        self.curve.setVisible(result is None or self.raw_visible.isChecked())
        self.marker.setVisible(result is None or self.raw_visible.isChecked())
        self.baseline_curve.setVisible(result is not None and self.baseline_visible.isChecked())
        editing = hasattr(self, "baseline_panel") and self.baseline_panel.active and self.trace
        self.corrected_plot.setVisible(
            bool(result is not None or editing) and self.corrected_visible.isChecked()
        )

    def render_refinements(self):
        for item in self.region_items:
            self.plot.removeItem(item)
        self.region_items.clear()
        self.anchor_points.clear()
        panel = self.baseline_panel
        self.plot.setCursor(
            Qt.CursorShape.CrossCursor
            if panel.active and panel.anchor_mode.isChecked()
            else Qt.CursorShape.ArrowCursor
        )
        if panel.state is None or not panel.active or not panel.valid:
            return
        recipe = panel.state.draft
        if recipe.anchors:
            self.anchor_points.setData(
                [anchor.time for anchor in recipe.anchors],
                [anchor.value for anchor in recipe.anchors],
            )
        for row, region in enumerate(recipe.regions):
            color = "#167D8D" if region.kind == "Protected peak" else "#AA6E38"
            item = pg.LinearRegionItem(
                values=(region.start, region.end),
                bounds=(self.display_x[0], self.display_x[-1]),
                brush=pg.mkBrush(color + "22"),
                pen=pg.mkPen(color),
            )
            item.setZValue(-5)
            item.sigRegionChangeFinished.connect(
                lambda current, row=row: panel.move_region(row, *current.getRegion())
            )
            self.plot.addItem(item, ignoreBounds=True)
            self.region_items.append(item)

    def baseline_plot_clicked(self, event):
        panel = self.baseline_panel
        if (
            self.trace is not None
            and panel.active
            and panel.anchor_mode.isChecked()
            and event.button() == Qt.MouseButton.LeftButton
            and self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos())
        ):
            point = self.plot.getViewBox().mapSceneToView(event.scenePos())
            panel.add_anchor(point.x(), point.y())

    def history_action(self, redo=False):
        if self.inspector_tabs.currentIndex() == 3:
            self.fit_panel.history_action(redo)
        elif self.inspector_tabs.currentIndex() == 2:
            self.peak_panel.history_action(redo)
        else:
            self.baseline_panel.history_action(redo)

    def update_history_actions(self):
        peaks = self.inspector_tabs.currentIndex() == 2
        fitting = self.inspector_tabs.currentIndex() == 3
        state = (
            self.fit_panel.state
            if fitting
            else self.peak_panel.state
            if peaks
            else self.baseline_panel.state
        )
        self.undo_action.setText(
            "Undo fit change"
            if fitting
            else "Undo peak change"
            if peaks
            else "Undo baseline change"
        )
        self.redo_action.setText(
            "Redo fit change"
            if fitting
            else "Redo peak change"
            if peaks
            else "Redo baseline change"
        )
        self.undo_action.setEnabled(state is not None and bool(state.undo_history))
        self.redo_action.setEnabled(state is not None and bool(state.redo_history))

    def render_peaks(self, *_):
        focused = self.inspector_tabs.currentIndex() == 2
        if focused != self.peaks_focused:
            self.cursor_readout.setText(
                "Move over the corrected trace to inspect a sample"
                if focused
                else "Move over the trace to inspect a sample"
            )
            if focused:
                bounds = self.plot.getViewBox().viewRange()[0]
                self.corrected_plot.setXLink(None)
                self.corrected_plot.setXRange(*bounds, padding=0)
            else:
                bounds = self.corrected_plot.getViewBox().viewRange()[0]
                self.plot.setXRange(*bounds, padding=0)
                self.corrected_plot.setXLink(self.plot)
            self.peaks_focused = focused
        self.plot.setVisible(not focused)
        self.raw_visible.setVisible(not focused)
        self.baseline_visible.setVisible(not focused)
        self.update_history_actions()
        state = self.peak_panel.state
        current = bool(state and state.current)
        result = state.result if state else None
        self.peak_card.setVisible(
            self.inspector_tabs.currentIndex() != 3
            and (result is not None or self.inspector_tabs.currentIndex() == 2)
        )
        self.peak_heading.setText(
            "PEAK RESULTS · APPLIED BASELINE"
            if current
            else "PEAK RESULTS · STALE"
            if result
            else "PEAK RESULTS · DETECT TO BEGIN"
        )
        self.peak_heading.setToolTip("\n".join(result.warnings) if result else "")
        self.peak_markers.clear()
        if self.peak_region is not None:
            self.corrected_plot.removeItem(self.peak_region)
            self.peak_region.deleteLater()
            self.peak_region = None
        displayed = self.displayed_baseline()
        if (
            self.inspector_tabs.currentIndex() == 3
            or not current
            or displayed is not state.baseline_state.applied
        ):
            return
        self.peak_markers.setData(
            [
                {
                    "pos": (peak.retention_time, peak.height),
                    "data": peak.id,
                    "brush": pg.mkBrush("#6741A0" if peak.id == state.selected_id else "#A18AC6"),
                }
                for peak in result.peaks
            ]
        )
        peak = next((peak for peak in result.peaks if peak.id == state.selected_id), None)
        if peak is not None and not self.peak_panel.busy:
            region = pg.LinearRegionItem(
                values=(peak.start, peak.end),
                bounds=(self.display_x[peak.segment_start], self.display_x[peak.segment_end]),
                brush=pg.mkBrush(128, 101, 186, 25),
                pen=pg.mkPen("#8065BA"),
            )
            region.setZValue(-4)
            region.sigRegionChangeFinished.connect(
                lambda item, peak_id=peak.id: self.peak_panel.edit_peak(peak_id, *item.getRegion())
            )
            self.corrected_plot.addItem(region, ignoreBounds=True)
            self.peak_region = region

    def render_fit_workspace(self, *_):
        fitting = self.inspector_tabs.currentIndex() == 3
        self.stack.setVisible(not fitting)
        self.fit_panel.workspace.setVisible(fitting)
        self.data_card.setVisible(not fitting and self.data_action.isChecked())

    def peak_marker_clicked(self, item, points, event):
        if points:
            self.peak_panel.select_id(points[0].data())
