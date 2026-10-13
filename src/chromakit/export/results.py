"""Unit/provenance-bearing CSV and JSON output of accepted analytical results."""

import csv
import io
import json
from dataclasses import asdict

from chromakit.analysis.peaks import baseline_key
from chromakit.export.figures import atomic_bytes
from chromakit.importers.text import ImportProblem


def result_bytes(trace, baseline, peaks, fitted, kind, format="csv", labels=()):
    if kind == "Measured peaks":
        if not peaks or not baseline or peaks.baseline_key != baseline_key(baseline):
            raise ImportProblem("Detect current peaks before exporting measured results.")
        rows = [asdict(peak) for peak in peaks.peaks]
        metadata = peaks.metadata()
    elif kind == "Fitted components":
        if not fitted or not baseline or fitted.baseline_key != baseline_key(baseline):
            raise ImportProblem("Accept a current fit before exporting fitted components.")
        rows = [asdict(peak) for peak in fitted.peaks]
        metadata = fitted.metadata()
    elif kind == "Sampled signal":
        rows = [
            {
                "time": float(x),
                "raw": float(y),
                "baseline": float(baseline.baseline[i]) if baseline else None,
                "corrected": float(baseline.corrected[i]) if baseline else None,
                "break_after": bool(trace.gap_after[i]) if i < len(trace.gap_after) else False,
            }
            for i, (x, y) in enumerate(zip(trace.display_time, trace.signal, strict=True))
        ]
        metadata = {
            "source_hash": trace.source_hash,
            "import_settings": dict(trace.import_settings),
        }
    else:
        raise ImportProblem("Choose sampled signal, measured peaks or fitted components.")
    for row in rows:
        row.update(
            {
                "trace": trace.name,
                "time_unit": trace.time_unit,
                "signal_unit": trace.signal_unit,
                "area_unit": f"{trace.signal_unit} × {trace.time_unit}",
                "source_hash": trace.source_hash,
                "origin": kind,
                "baseline_key": baseline_key(baseline) if baseline else "",
            }
        )
        identifier = row.get("id")
        row["compound_labels"] = (
            "; ".join(
                label["name"]
                for label in labels
                if label.get("peak_id") == identifier and not label.get("stale")
            )
            if identifier
            else ""
        )
    if format == "json":
        return json.dumps(
            {"metadata": metadata, "rows": rows}, ensure_ascii=False, allow_nan=False, indent=2
        ).encode()
    stream = io.StringIO(newline="")
    headers = (
        list(rows[0])
        if rows
        else [
            "trace",
            "time_unit",
            "signal_unit",
            "area_unit",
            "source_hash",
            "origin",
            "baseline_key",
        ]
    )
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: "; ".join(map(str, value)) if isinstance(value, (tuple, list)) else value
                for key, value in row.items()
            }
        )
    return stream.getvalue().encode("utf-8-sig")


def export_results(path, *args, cancel=lambda: False, **kwargs):
    from chromakit.importers.text import ImportCancelled

    data = result_bytes(*args, format=path.suffix.lower().lstrip("."), **kwargs)
    if cancel():
        raise ImportCancelled()
    return atomic_bytes(path, data)
