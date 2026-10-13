"""Axis picking, color tracing, masks and editable pixel points over the original image."""

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chromakit.digitization.core import DigitizeRecipe, create_trace, image_pixels, trace_pixels
from chromakit.digitization.repair import repair_pixels
from chromakit.ui.operation_tasks import OperationController
from chromakit.ui.peak_panel import spin


class ImageView(QGraphicsView):
    def __init__(self, scene, callback):
        super().__init__(scene)
        self.callback = callback
        self.setDragMode(self.DragMode.ScrollHandDrag)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            p = self.mapToScene(event.position().toPoint())
            self.callback(p.x(), p.y())
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)


class DigitizeDialog(QDialog):
    def __init__(self, path, parent=None, record=None):
        super().__init__(parent)
        self.setWindowTitle("Recover chromatogram from image")
        self.resize(1300, 850)
        self.path = path
        if record is None:
            if Path(path).stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Choose an image smaller than 64 MiB.")
            self.data = Path(path).read_bytes()
        else:
            self.data = record["original_image"]
        self.pick = None
        self.points = []
        self.manual = False
        self.trace = None
        self.record = None
        self.valid_points = True
        self.extracted_recipe = None
        self.overlays = []
        self.controller = OperationController(self)
        self.controller.succeeded.connect(self.ready)
        self.controller.failed.connect(lambda error: self.message.setText(error))
        self.preview_controller = OperationController(self)
        self.preview_controller.succeeded.connect(self.preview_ready)
        self.preview_controller.failed.connect(lambda error: self.message.setText(error))
        self.recovery = None
        root = QHBoxLayout(self)
        self.scene = QGraphicsScene()
        self.view = ImageView(self.scene, self.picked)
        comparison = QVBoxLayout()
        comparison.addWidget(self.view, 3)
        preview_legend = QLabel(
            "Pixel preview · gray: original points · teal: prepared trace · "
            "orange squares: interpolated · red crosses: replaced spikes"
        )
        preview_legend.setWordWrap(True)
        comparison.addWidget(preview_legend)
        self.preview_plot = pg.PlotWidget(background="white")
        self.preview_plot.setMinimumHeight(180)
        self.preview_plot.setLabel("bottom", "Image column", units="px")
        self.preview_plot.setLabel("left", "Image row", units="px")
        self.preview_plot.getViewBox().invertY(True)
        comparison.addWidget(self.preview_plot, 1)
        root.addLayout(comparison, 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        controls = QVBoxLayout(panel)
        scroll.setWidget(panel)
        root.addWidget(scroll, 1)
        guide = QLabel(
            "1  Orient and crop the plot.\n"
            "2  Set two known values on each axis; pick their pixel positions.\n"
            "3  Pick the trace color, preview and correct pixel points.\n"
            "4  Confirm units, then create a trace. "
            "Scroll over the image to zoom; drag to pan."
        )
        guide.setWordWrap(True)
        controls.addWidget(guide)
        self.rotation = QComboBox()
        self.rotation.addItems(["0", "90", "180", "270"])
        controls.addWidget(QLabel("Rotate image (degrees counter-clockwise)"))
        controls.addWidget(self.rotation)
        self.rotation.currentTextChanged.connect(self.reset_image)
        self.axes = {}
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        axis_labels = {
            "x1": "First time tick · pixel x",
            "time1": "First time tick · value",
            "x2": "Second time tick · pixel x",
            "time2": "Second time tick · value",
            "y1": "First signal tick · pixel y",
            "signal1": "First signal tick · value",
            "y2": "Second signal tick · pixel y",
            "signal2": "Second signal tick · value",
        }
        for name in ["x1", "time1", "x2", "time2", "y1", "signal1", "y2", "signal2"]:
            field = spin(-1e12, 1e12, 0)
            self.axes[name] = field
            form.addRow(axis_labels[name], field)
        for name in ["x1", "x2", "y1", "y2", "color", "manual point"]:
            description = {
                "x1": "Pick first time tick",
                "x2": "Pick second time tick",
                "y1": "Pick first signal tick",
                "y2": "Pick second signal tick",
                "color": "Pick trace color",
                "manual point": "Add manual trace point",
            }
            button = QPushButton(description[name])
            button.clicked.connect(lambda _=False, name=name: self.set_pick(name))
            form.addRow(button)
        self.crop = [spin(0, 100000, 0) for _ in range(4)]
        for name, field in zip(
            ["Crop left", "Crop top", "Crop right", "Crop bottom"], self.crop, strict=True
        ):
            form.addRow(name, field)
        self.tolerance = spin(1, 441, 90)
        form.addRow("Color tolerance", self.tolerance)
        self.time_unit = QComboBox()
        self.time_unit.addItems(["unknown", "s", "min", "h"])
        self.signal_unit = QComboBox()
        self.signal_unit.addItems(["unknown", "mAU", "AU", "mV", "nA", "RIU"])
        self.signal_unit.setEditable(True)
        form.addRow("Calibrated time unit", self.time_unit)
        form.addRow("Calibrated signal unit", self.signal_unit)
        controls.addLayout(form)
        masknote = QLabel(
            "Masks: pixel rectangles x0,y0,x1,y1; exclude legends, grid or crossed traces. "
            "Add rows as needed."
        )
        masknote.setWordWrap(True)
        controls.addWidget(masknote)
        self.masks = QTableWidget(0, 4)
        self.masks.setHorizontalHeaderLabels(["x0", "y0", "x1", "y1"])
        self.masks.setMaximumHeight(95)
        controls.addWidget(self.masks)
        maskadd = QPushButton("Add exclusion rectangle")
        maskadd.clicked.connect(lambda: self.masks.insertRow(self.masks.rowCount()))
        controls.addWidget(maskadd)
        auto = QPushButton("Trace selected color")
        auto.clicked.connect(self.extract)
        controls.addWidget(auto)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Pixel x", "Pixel y"])
        self.table.setMaximumHeight(150)
        self.table.itemChanged.connect(self.edited)
        controls.addWidget(self.table)
        remove = QPushButton("Remove selected pixel point")
        remove.clicked.connect(self.remove_point)
        controls.addWidget(remove)
        controls.addWidget(QLabel("Repair missing samples and isolated spikes"))
        repair_form = QFormLayout()
        self.interpolate_gaps = QCheckBox("Interpolate missing columns")
        self.maximum_gap = spin(1, 20000, 25)
        self.maximum_gap.setDecimals(0)
        self.remove_spikes = QCheckBox("Replace isolated spikes")
        self.spike_window = QComboBox()
        self.spike_window.addItems([str(value) for value in range(5, 102, 2)])
        self.spike_window.setCurrentText("11")
        self.spike_threshold = spin(1, 20, 4)
        self.spike_minimum = spin(1, 10000, 6)
        repair_form.addRow(self.interpolate_gaps)
        repair_form.addRow("Maximum missing columns", self.maximum_gap)
        repair_form.addRow(self.remove_spikes)
        repair_form.addRow("Spike neighborhood (columns)", self.spike_window)
        repair_form.addRow("Outlier threshold (lower = stronger)", self.spike_threshold)
        repair_form.addRow("Minimum spike jump (pixels)", self.spike_minimum)
        controls.addLayout(repair_form)
        note = QLabel(
            "Repairs affect the created data, not just its display. Gaps beyond the "
            "limit stay missing. Spike repair can remove very narrow real peaks; "
            "compare the preview with the image. Original points remain in the project."
        )
        note.setWordWrap(True)
        controls.addWidget(note)
        create = QPushButton("Create calibrated trace")
        create.setObjectName("primary")
        create.clicked.connect(self.create)
        controls.addWidget(create)
        self.message = QLabel(
            "Axis calibration is required; image pixels alone are not quantitative data."
        )
        self.message.setWordWrap(True)
        controls.addWidget(self.message)
        self.color = (0, 0, 255)
        self.seed_y = None
        self.reset_image()
        for check in (self.interpolate_gaps, self.remove_spikes):
            check.toggled.connect(self.request_preview)
        for field in (self.maximum_gap, self.spike_threshold, self.spike_minimum):
            field.valueChanged.connect(self.request_preview)
        self.spike_window.currentTextChanged.connect(self.request_preview)
        if record is not None:
            self.restore_record(record)

    def restore_record(self, record):
        values = record["recipe"]
        self.rotation.setCurrentText(str(values["rotation"]))
        for name, field in self.axes.items():
            field.setValue(values[name])
        for field, value in zip(self.crop, values["crop"], strict=True):
            field.setValue(value)
        self.color = tuple(values["color"])
        self.seed_y = values.get("seed_y")
        self.tolerance.setValue(values["tolerance"])
        self.time_unit.setCurrentText(values["time_unit"])
        self.signal_unit.setCurrentText(values["signal_unit"])
        self.masks.setRowCount(len(values["masks"]))
        for row, mask in enumerate(values["masks"]):
            for column, value in enumerate(mask):
                self.masks.setItem(row, column, QTableWidgetItem(str(value)))
        self.interpolate_gaps.setChecked(values.get("interpolate_gaps", False))
        self.maximum_gap.setValue(values.get("maximum_gap", 25))
        self.remove_spikes.setChecked(values.get("remove_spikes", False))
        self.spike_window.setCurrentText(str(values.get("spike_window", 11)))
        self.spike_threshold.setValue(values.get("spike_threshold", 4))
        self.spike_minimum.setValue(values.get("spike_minimum", 6))
        self.points = [
            tuple(point) for point in record.get("original_pixel_points", record["pixel_points"])
        ]
        self.manual = record["manual_overrides"]
        self.extracted_recipe = self.recipe()
        self.populate()
        self.message.setText(
            "Embedded original image and calibration restored. "
            "Creating a refined trace keeps the original trace and its analysis."
        )

    def reset_image(self, *_):
        self.controller.cancel()
        self.preview_controller.cancel()
        self.recovery = None
        self.preview_plot.clear()
        self.pixels = image_pixels(self.data, int(self.rotation.currentText()))
        height, width = self.pixels.shape[:2]
        image = QImage(
            self.pixels.data, width, height, 3 * width, QImage.Format.Format_RGB888
        ).copy()
        self.scene.clear()
        self.overlays = []
        self.scene.addPixmap(QPixmap.fromImage(image))
        self.scene.setSceneRect(0, 0, width, height)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        for field, value in zip(self.crop, [0, 0, width, height], strict=True):
            field.setValue(value)
        self.points = []
        self.seed_y = None
        for field in self.axes.values():
            field.setValue(0)
        self.masks.setRowCount(0)
        self.table.setRowCount(0)
        self.message.setText("Set axis calibration for this image orientation.")

    def set_pick(self, name):
        self.pick = name
        self.message.setText(
            "Click the image to pick " + name + ". Axis values must be entered separately."
        )

    def picked(self, x, y):
        if not self.pick or not 0 <= x < self.pixels.shape[1] or not 0 <= y < self.pixels.shape[0]:
            return
        if self.pick in self.axes:
            self.axes[self.pick].setValue(x if self.pick.startswith("x") else y)
        elif self.pick == "color":
            self.color = tuple(int(v) for v in self.pixels[int(y), int(x)])
            self.seed_y = y
            self.message.setText(
                f"Trace color RGB {self.color}. Choose a crop avoiding axes and legends."
            )
        else:
            self.points.append((x, y))
            self.points.sort()
            self.manual = True
            self.populate()
        self.pick = None

    def recipe(self):
        masks = []
        for row in range(self.masks.rowCount()):
            masks.append(tuple(int(self.masks.item(row, col).text()) for col in range(4)))
        return DigitizeRecipe(
            **{name: field.value() for name, field in self.axes.items()},
            crop=tuple(int(f.value()) for f in self.crop),
            color=self.color,
            tolerance=self.tolerance.value(),
            rotation=int(self.rotation.currentText()),
            seed_y=self.seed_y,
            masks=tuple(masks),
            time_unit=self.time_unit.currentText(),
            signal_unit=self.signal_unit.currentText(),
            interpolate_gaps=self.interpolate_gaps.isChecked(),
            maximum_gap=int(self.maximum_gap.value()),
            remove_spikes=self.remove_spikes.isChecked(),
            spike_window=int(self.spike_window.currentText()),
            spike_threshold=self.spike_threshold.value(),
            spike_minimum=self.spike_minimum.value(),
        )

    def extract(self):
        try:
            recipe = self.recipe()
        except (ValueError, AttributeError) as error:
            self.message.setText("Complete all mask rectangle cells: " + str(error))
            return
        self.controller.request_operation(
            lambda cancel: (trace_pixels(self.data, recipe, cancel), recipe)
        )
        self.message.setText("Tracing color…")

    def ready(self, result):
        points, self.extracted_recipe = result
        self.points = list(points)
        self.manual = False
        self.populate()
        self.message.setText(
            f"{len(points)} recovered pixel columns. Inspect the overlay and edit "
            "occluded/incorrect points before creating a trace."
        )

    def populate(self):
        self.valid_points = True
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.points))
        for row, point in enumerate(self.points):
            for column, value in enumerate(point):
                self.table.setItem(row, column, QTableWidgetItem(f"{value:.17g}"))
        self.table.blockSignals(False)
        self.draw_points()
        self.request_preview()

    def draw_points(self):
        for item in self.overlays:
            self.scene.removeItem(item)
        self.overlays = []
        for x, y in self.points:
            self.overlays.append(
                self.scene.addEllipse(x - 1.5, y - 1.5, 3, 3, QPen(QColor("#16BB88")))
            )

    def edited(self, *_):
        try:
            points = [
                tuple(float(self.table.item(row, col).text()) for col in range(2))
                for row in range(self.table.rowCount())
            ]
            if not np.isfinite(points).all():
                raise ValueError("Pixel coordinates must be finite.")
            self.points = points
            self.valid_points = True
            self.manual = True
            self.draw_points()
            self.request_preview()
        except (ValueError, AttributeError):
            self.valid_points = False
            self.preview_controller.cancel()
            self.recovery = None
            self.preview_plot.clear()
            self.message.setText("Enter finite pixel coordinates.")

    def remove_point(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.points):
            self.points.pop(row)
            self.manual = True
            self.populate()

    def create(self):
        try:
            if not self.valid_points:
                raise ValueError("Fix invalid pixel table entries before creating a trace.")
            recipe = self.recipe()
            if (
                self.extracted_recipe
                and not self.manual
                and any(
                    getattr(recipe, key) != getattr(self.extracted_recipe, key)
                    for key in ("color", "tolerance", "crop", "rotation", "masks", "seed_y")
                )
            ):
                raise ValueError("Tracing settings changed. Run Trace selected color again.")
            self.trace, self.record = create_trace(
                self.data,
                self.path,
                self.recipe(),
                self.points,
                "Digitized " + self.path.stem,
                self.manual,
            )
        except (ValueError, AttributeError) as error:
            self.message.setText(str(error))
            return
        self.accept()

    def request_preview(self, *_):
        self.preview_controller.cancel()
        self.recovery = None
        self.preview_plot.clear()
        if len(self.points) < 2 or not self.valid_points:
            return
        try:
            recipe = self.recipe()
        except (ValueError, AttributeError):
            return
        points = tuple(self.points)
        self.preview_controller.request_operation(
            lambda cancel: repair_pixels(points, recipe, cancel)
        )

    def preview_ready(self, recovery):
        self.recovery = recovery
        original = np.asarray(self.points)
        prepared = np.asarray(recovery.points)
        plot = self.preview_plot
        plot.clear()
        plot.plot(
            original[:, 0],
            original[:, 1],
            pen=None,
            symbol="o",
            symbolSize=3,
            symbolBrush="#84939B",
            symbolPen=None,
        )
        plot.plot(
            prepared[:, 0],
            prepared[:, 1],
            pen=pg.mkPen("#167D8D", width=2),
            connect=np.r_[np.diff(prepared[:, 0]) <= 1.5, False],
        )
        for xs, color, symbol in (
            (recovery.interpolated_x, "#E79828", "s"),
            (recovery.corrected_x, "#C94752", "x"),
        ):
            selected = np.isin(prepared[:, 0], xs)
            plot.plot(
                prepared[selected, 0],
                prepared[selected, 1],
                pen=None,
                symbol=symbol,
                symbolSize=7,
                symbolBrush=color,
                symbolPen=color,
            )
        self.message.setText(
            f"{len(self.points)} original points → {len(recovery.points)} prepared points · "
            f"{len(recovery.interpolated_x)} interpolated · "
            f"{len(recovery.corrected_x)} spikes replaced. Inspect before creating."
        )

    def done(self, result):
        self.controller.shutdown()
        self.preview_controller.shutdown()
        super().done(result)
