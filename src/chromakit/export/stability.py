"""Scalar stability report exports keep failed starts and component-area origin explicit."""

import csv
import io
import json


def stability_bytes(report, format="json"):
    if format == "json":
        return json.dumps(report, indent=2, allow_nan=False).encode()
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "start",
            "converged",
            "comparable",
            "rmse",
            "objective",
            "component",
            "full_area",
            "window_area",
            "retention_time",
            "time_unit",
            "signal_unit",
            "fit_key",
            "message",
        ]
    )
    for run in report["runs"]:
        for peak in run["peaks"] or [{}]:
            writer.writerow(
                [
                    run["index"],
                    run["converged"],
                    run["comparable"],
                    run["rmse"],
                    run["cost"],
                    peak.get("id", ""),
                    peak.get("area", ""),
                    peak.get("window_area", ""),
                    peak.get("retention_time", ""),
                    report["time_unit"],
                    report["signal_unit"],
                    report["fit_key"],
                    run["message"],
                ]
            )
    return stream.getvalue().encode()
