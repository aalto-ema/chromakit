"""Read-only overlays and gap-aware differences on actual observation coordinates."""

from dataclasses import dataclass

import numpy as np
from scipy.integrate import trapezoid

from chromakit.analysis.peaks import valid_segments
from chromakit.domain import TIME_SCALES, readonly_array
from chromakit.importers.text import ImportCancelled, ImportProblem


@dataclass(frozen=True)
class ComparisonSeries:
    trace_id: str
    name: str
    color: str
    x: np.ndarray
    y: np.ndarray
    connect: np.ndarray
    difference: np.ndarray
    difference_connect: np.ndarray
    divisor: float
    source_hash: str


@dataclass(frozen=True)
class ComparisonResult:
    series: tuple[ComparisonSeries, ...]
    time_unit: str
    signal_unit: str
    mode: str
    normalization: str
    reference_id: str


def compare(
    traces,
    baselines,
    colors,
    reference_id,
    mode="Raw",
    normalization="None",
    time_unit="min",
    cancel=lambda: False,
):
    if not 2 <= len(traces) <= 30 or len({t.id for t in traces}) != len(traces):
        raise ImportProblem("Select 2–30 distinct chromatograms to compare.")
    if mode not in {"Raw", "Corrected"} or normalization not in {
        "None",
        "Peak magnitude",
        "Absolute area",
    }:
        raise ImportProblem("Choose a supported signal and normalization.")
    if time_unit not in TIME_SCALES:
        raise ImportProblem("Choose a known time unit or unknown coordinates.")
    if any((t.time_unit == "unknown") != (time_unit == "unknown") for t in traces):
        raise ImportProblem("Confirm time units before comparing known and unknown coordinates.")
    if normalization == "None" and len({t.signal_unit for t in traces}) != 1:
        raise ImportProblem(
            "Signal units must agree; normalize explicitly for dimensionless comparison."
        )
    prepared = []
    for trace, baseline, color in zip(traces, baselines, colors, strict=True):
        if cancel():
            raise ImportCancelled()
        x = trace.time / TIME_SCALES[time_unit]
        connect = np.r_[~trace.gap_after, False]
        y = trace.signal.copy()
        if mode == "Corrected":
            if baseline is None:
                raise ImportProblem(
                    f"Apply a baseline to {trace.name} before comparing corrected signals."
                )
            y = baseline.corrected.copy()
            connect[:] = False
            valid = np.zeros(len(x), dtype=bool)
            for start, end in valid_segments(trace, baseline):
                connect[start:end] = True
                valid[start : end + 1] = True
            y[~valid] = np.nan
        divisor = 1.0
        if normalization == "Peak magnitude":
            divisor = float(np.nanmax(np.abs(y))) if np.isfinite(y).any() else 0.0
        elif normalization == "Absolute area":
            divisor = 0.0
            for start, end in segments(connect, np.isfinite(y)):
                divisor += float(trapezoid(np.abs(y[start : end + 1]), x[start : end + 1]))
        if not np.isfinite(divisor) or divisor <= np.finfo(float).tiny:
            raise ImportProblem(f"{trace.name} has no nonzero signal for this normalization.")
        prepared.append((trace, color, x, y / divisor, connect, divisor))
    reference = next((p for p in prepared if p[0].id == reference_id), None)
    if reference is None:
        raise ImportProblem("Select a checked reference chromatogram.")
    _, _, rx, ry, rc, _ = reference
    output = []
    for trace, color, x, y, connect, divisor in prepared:
        if cancel():
            raise ImportCancelled()
        interpolated = np.full(len(x), np.nan)
        membership = np.full(len(x), -1)
        for segment_id, (start, end) in enumerate(segments(rc, np.isfinite(ry))):
            chosen = (x >= rx[start]) & (x <= rx[end])
            if start == end:
                chosen &= x == rx[start]
            interpolated[chosen] = np.interp(x[chosen], rx[start : end + 1], ry[start : end + 1])
            membership[chosen] = segment_id
        difference = y - interpolated
        dc = connect.copy()
        dc[:-1] &= (
            (membership[:-1] == membership[1:])
            & (membership[:-1] >= 0)
            & np.isfinite(difference[:-1])
            & np.isfinite(difference[1:])
        )
        output.append(
            ComparisonSeries(
                trace.id,
                trace.name,
                color,
                readonly_array(x),
                readonly_array(y),
                readonly_array(connect, np.bool_),
                readonly_array(difference),
                readonly_array(dc, np.bool_),
                divisor,
                trace.source_hash,
            )
        )
    unit = (
        traces[0].signal_unit
        if normalization == "None"
        else ("normalized" if normalization == "Peak magnitude" else f"1/{time_unit}")
    )
    return ComparisonResult(tuple(output), time_unit, unit, mode, normalization, reference_id)


def segments(connect, valid):
    start = None
    for index in range(len(valid)):
        if valid[index] and start is None:
            start = index
        if start is not None and (not connect[index] or index == len(valid) - 1):
            yield start, index
            start = None
