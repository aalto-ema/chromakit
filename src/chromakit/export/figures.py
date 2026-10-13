"""One figure specification for preview and dimension-preserving output."""

import io
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

import numpy as np
from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from chromakit.analysis.peaks import baseline_key
from chromakit.importers.text import ImportCancelled, ImportProblem

LOCK = Lock()  # Matplotlib font/global caches are not safe for concurrent rendering.
COLORS = ["#169C89", "#D79622", "#9271C6", "#329ECE", "#CB6C88", "#63864D", "#AE7A50", "#5776C0"]


@dataclass(frozen=True)
class FigureSpec:
    width: float = 180
    height: float = 120
    unit: str = "mm"
    dpi: int = 300
    transparent: bool = False
    background: str = "#FFFFFF"
    view: str = "Raw + baseline"
    title: str = ""
    font_size: float = 10
    line_width: float = 1.5
    x_limits: tuple[float, float] | None = None
    font_family: str = "DejaVu Sans"

    def inches(self):
        factor = {"mm": 25.4, "in": 1, "px": self.dpi}.get(self.unit)
        if (
            factor is None
            or not np.isfinite(
                [self.width, self.height, self.dpi, self.font_size, self.line_width]
            ).all()
            or self.width <= 0
            or self.height <= 0
            or not 36 <= self.dpi <= 1200
            or not 4 <= self.font_size <= 40
            or not 0.1 <= self.line_width <= 10
        ):
            raise ImportProblem(
                "Choose positive dimensions, DPI 36–1200 and valid font/line sizes."
            )
        if self.unit == "px" and (self.width % 1 or self.height % 1):
            raise ImportProblem("Use whole pixels for pixel-sized figures.")
        size = self.width / factor, self.height / factor
        if self.unit == "px":
            size = tuple(float(np.nextafter(value, np.inf)) for value in size)
        if size[0] * size[1] * self.dpi**2 > 80_000_000 or max(size) * self.dpi > 20000:
            raise ImportProblem(
                "Limit exported rasters to 80 million pixels and 20,000 pixels per side."
            )
        if self.x_limits and (
            not np.isfinite(self.x_limits).all() or self.x_limits[0] >= self.x_limits[1]
        ):
            raise ImportProblem("Figure time bounds must increase.")
        return size


def atomic_bytes(path: Path, data: bytes):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return path


def figure_bytes(trace, baseline, fitted, labels, spec: FigureSpec, format="png"):
    if format not in {"png", "tiff", "pdf", "svg"}:
        raise ImportProblem("Choose PNG, TIFF, PDF or SVG.")
    size = spec.inches()
    if spec.view != "Raw + baseline" and baseline is None:
        raise ImportProblem("Apply a baseline for corrected-signal figures.")
    if spec.view == "Fit + residuals" and (
        not fitted or fitted.baseline_key != baseline_key(baseline)
    ):
        raise ImportProblem("Accept a current fit for component/residual figures.")
    with LOCK, rc_context({"svg.fonttype": "none", "pdf.fonttype": 42}):
        figure = Figure(figsize=size, dpi=spec.dpi, facecolor=spec.background)
        FigureCanvasAgg(figure)
        if spec.view == "Fit + residuals":
            axes = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
            main, residual = axes
            main.plot(
                fitted.x,
                fitted.observed,
                color="#8BA4AD",
                label="Corrected observations",
                lw=spec.line_width,
            )
            main.plot(
                fitted.x, fitted.total, color="#24343F", label="Component sum", lw=spec.line_width
            )
            for peak, y, color in zip(fitted.peaks, fitted.curves, COLORS, strict=False):
                main.plot(fitted.x, y, color=color, label=peak.id, lw=spec.line_width)
            residual.plot(fitted.x, fitted.residual, color="#8065BA", lw=spec.line_width)
            residual.axhline(0, color="#AABBC2", lw=0.7)
            residual.set_ylabel("Residual", fontsize=spec.font_size)
            residual.set_xlabel(f"Time ({trace.time_unit})", fontsize=spec.font_size)
        else:
            main = figure.subplots()
            axes = [main]
            splits = np.r_[0, np.flatnonzero(trace.gap_after) + 1, len(trace.signal)]
            for first, end in zip(splits[:-1], splits[1:], strict=True):
                x = trace.display_time[first:end]
                y = (
                    trace.signal[first:end]
                    if spec.view == "Raw + baseline"
                    else baseline.corrected[first:end]
                )
                main.plot(
                    x,
                    y,
                    color="#137F90",
                    label="Raw signal"
                    if first == 0 and spec.view == "Raw + baseline"
                    else "Corrected signal"
                    if first == 0
                    else None,
                    lw=spec.line_width,
                )
                if spec.view == "Raw + baseline" and baseline:
                    main.plot(
                        x,
                        baseline.baseline[first:end],
                        color="#D79622",
                        ls="--",
                        label="Applied baseline" if first == 0 else None,
                        lw=spec.line_width,
                    )
            main.set_xlabel(f"Time ({trace.time_unit})", fontsize=spec.font_size)
        main.set_ylabel(f"Signal ({trace.signal_unit})", fontsize=spec.font_size)
        main.set_title(spec.title or trace.name, fontsize=spec.font_size + 1, parse_math=False)
        for annotation in labels:
            if annotation.get("stale"):
                continue
            raw = spec.view == "Raw + baseline"
            height = (
                annotation.get("raw_height", annotation["height"]) if raw else annotation["height"]
            )
            placement = annotation.get("label_y_raw" if raw else "label_y")
            main.annotate(
                annotation["name"] + (" ?" if annotation.get("status") == "Tentative" else ""),
                xy=(annotation["time"], height),
                xytext=(annotation.get("label_x", annotation["time"]), placement)
                if placement is not None
                else (annotation.get("dx", 0), annotation.get("dy", 18)),
                textcoords="data" if placement is not None else "offset points",
                fontsize=spec.font_size,
                fontfamily=spec.font_family,
                rotation=annotation.get("rotation", 0),
                arrowprops={"arrowstyle": "-", "color": "#627680", "lw": 0.7},
                parse_math=False,
            )
        for axis in axes:
            axis.set_facecolor(spec.background)
            axis.tick_params(labelsize=spec.font_size)
            axis.xaxis.label.set_fontfamily(spec.font_family)
            axis.yaxis.label.set_fontfamily(spec.font_family)
            axis.title.set_fontfamily(spec.font_family)
            for text in [*axis.get_xticklabels(), *axis.get_yticklabels()]:
                text.set_fontfamily(spec.font_family)
            axis.spines[["top", "right"]].set_visible(False)
            if spec.x_limits:
                axis.set_xlim(*spec.x_limits)
            axis.grid(alpha=0.12)
        main.legend(
            prop={"family": spec.font_family, "size": max(5, spec.font_size - 1)}, frameon=False
        )
        # Layout within fixed page: no bbox_inches='tight' changing physical dimensions.
        figure.subplots_adjust(left=0.16, right=0.97, bottom=0.16, top=0.90, hspace=0.15)
        stream = io.BytesIO()
        figure.savefig(
            stream,
            format=format,
            dpi=spec.dpi,
            transparent=spec.transparent,
            facecolor="none" if spec.transparent else spec.background,
            **(
                {"metadata": {"Title": spec.title or trace.name}}
                if format in {"pdf", "svg"}
                else {}
            ),
        )
        figure.clear()
        return stream.getvalue()


def export_figure(path, trace, baseline, fitted, labels, spec, cancel=lambda: False):
    fmt = path.suffix.lower().lstrip(".")
    if fmt == "tif":
        fmt = "tiff"
    data = figure_bytes(trace, baseline, fitted, labels, spec, fmt)
    if cancel():
        raise ImportCancelled()
    return atomic_bytes(path, data)


def spec_metadata(spec):
    return asdict(spec)


def calibration_figure_bytes(result, spec, format="png", title="Calibration"):
    if format not in {"png", "tiff", "pdf", "svg"}:
        raise ImportProblem("Choose PNG, TIFF, PDF or SVG.")
    with LOCK, rc_context({"svg.fonttype": "none", "pdf.fonttype": 42}):
        figure = Figure(figsize=spec.inches(), dpi=spec.dpi, facecolor=spec.background)
        FigureCanvasAgg(figure)
        main, residual = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        for excluded, color, marker, name in [
            (False, "#137F90", "o", "Included standards"),
            (True, "#9AA5AB", "x", "Excluded standards"),
        ]:
            points = [
                p
                for p in result.points
                if p.excluded == excluded
                and p.concentration_unit == result.concentration_unit
                and p.response_unit == result.response_unit
            ]
            if points:
                main.scatter(
                    [p.concentration for p in points],
                    [p.response for p in points],
                    color=color,
                    marker=marker,
                    label=name,
                )
        x = np.linspace(result.minimum, result.maximum, 100)
        main.plot(
            x,
            result.slope * x + result.intercept,
            color="#D79622",
            lw=spec.line_width,
            label="Linear calibration",
        )
        included = [d for d in result.diagnostics if not d["excluded"]]
        residual.scatter(
            [d["concentration"] for d in included],
            [d["residual"] for d in included],
            color="#8065BA",
        )
        residual.axhline(0, color="#9AA5AB", lw=0.7)
        main.set_title(title, fontsize=spec.font_size + 1, parse_math=False)
        main.set_ylabel(f"Response ({result.response_unit})", fontsize=spec.font_size)
        residual.set_xlabel(f"Concentration ({result.concentration_unit})", fontsize=spec.font_size)
        residual.set_ylabel("Residual", fontsize=spec.font_size)
        main.legend(fontsize=spec.font_size - 1, frameon=False)
        for axis in [main, residual]:
            axis.set_facecolor(spec.background)
            axis.tick_params(labelsize=spec.font_size)
            axis.grid(alpha=0.12)
        figure.subplots_adjust(left=0.16, right=0.97, bottom=0.16, top=0.90, hspace=0.15)
        stream = io.BytesIO()
        figure.savefig(
            stream,
            format=format,
            dpi=spec.dpi,
            transparent=spec.transparent,
            facecolor="none" if spec.transparent else spec.background,
        )
        figure.clear()
        return stream.getvalue()
