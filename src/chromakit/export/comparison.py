"""Comparison export uses scientific arrays and the shared physical figure specification."""

import csv
import io

import numpy as np
from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from chromakit.analysis.comparison import segments
from chromakit.export.figures import LOCK
from chromakit.importers.text import ImportProblem


def comparison_bytes(result, spec, format):
    if format not in {"png", "tiff", "svg", "pdf"}:
        raise ImportProblem("Choose PNG, TIFF, PDF or SVG.")
    with (
        LOCK,
        rc_context(
            {
                "svg.fonttype": "none",
                "pdf.fonttype": 42,
                "font.family": spec.font_family,
                "font.size": spec.font_size,
            }
        ),
    ):
        figure = Figure(figsize=spec.inches(), dpi=spec.dpi, facecolor=spec.background)
        FigureCanvasAgg(figure)
        main, difference = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        for series in result.series:
            first = True
            for start, end in segments(series.connect, np.isfinite(series.y)):
                main.plot(
                    series.x[start : end + 1],
                    series.y[start : end + 1],
                    color=series.color,
                    lw=spec.line_width,
                    label=series.name if first else None,
                )
                first = False
            for start, end in segments(series.difference_connect, np.isfinite(series.difference)):
                difference.plot(
                    series.x[start : end + 1],
                    series.difference[start : end + 1],
                    color=series.color,
                    lw=spec.line_width,
                )
        main.set_title(spec.title or f"{result.mode} · {result.normalization}")
        main.set_ylabel(f"Signal ({result.signal_unit})")
        main.legend(fontsize=spec.font_size, frameon=False)
        difference.axhline(0, lw=0.7, color="#84939B")
        difference.set_ylabel("Difference")
        difference.set_xlabel(f"Time ({result.time_unit})")
        for ax in (main, difference):
            ax.set_facecolor(spec.background)
            if spec.x_limits:
                ax.set_xlim(*spec.x_limits)
        figure.subplots_adjust(left=0.15, right=0.97, top=0.89, bottom=0.14, hspace=0.16)
        stream = io.BytesIO()
        figure.savefig(stream, format=format, dpi=spec.dpi, transparent=spec.transparent)
        return stream.getvalue()


def comparison_csv(result):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "trace_id",
            "name",
            "time",
            "signal",
            "difference_to_reference",
            "break_after",
            "difference_break_after",
            "time_unit",
            "signal_unit",
            "normalization",
            "normalization_divisor",
            "mode",
            "reference_id",
            "source_hash",
        ]
    )
    for series in result.series:
        for i, x in enumerate(series.x):
            writer.writerow(
                [
                    series.trace_id,
                    series.name,
                    x,
                    series.y[i] if np.isfinite(series.y[i]) else "",
                    series.difference[i] if np.isfinite(series.difference[i]) else "",
                    not bool(series.connect[i]),
                    not bool(series.difference_connect[i]),
                    result.time_unit,
                    result.signal_unit,
                    result.normalization,
                    series.divisor,
                    result.mode,
                    result.reference_id,
                    series.source_hash,
                ]
            )
    return stream.getvalue().encode("utf-8")
