import hashlib
import json
from uuid import uuid4


def result_key(result):
    return (
        hashlib.sha256(
            json.dumps(result.metadata(), sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        if result
        else None
    )


def make_label(trace, baseline, result, peak, name, status="Tentative", origin="Measured peaks"):
    if not name.strip():
        raise ValueError("Enter a compound name.")
    from numpy import interp, ptp

    time = peak.retention_time
    return {
        "id": uuid4().hex,
        "trace_id": trace.id,
        "peak_id": peak.id,
        "name": name.strip(),
        "status": status,
        "origin": origin,
        "result_key": result_key(result),
        "time": time,
        "height": peak.height,
        "label_x": time,
        "label_y": float(peak.height + 0.07 * ptp(baseline.corrected)),
        "label_y_raw": float(
            peak.height
            + interp(time, trace.display_time, baseline.baseline)
            + 0.07 * ptp(trace.signal)
        ),
        "raw_height": float(peak.height + interp(time, trace.display_time, baseline.baseline)),
        "dx": 0.0,
        "dy": 18.0,
        "rotation": 0.0,
    }


def reviewed_labels(labels, peak_result, fit_result, baseline=None, library=None):
    from chromakit.analysis.peaks import baseline_key
    from chromakit.compounds.library import Compound, library_key

    keys = {"Measured peaks": result_key(peak_result), "Fitted components": result_key(fit_result)}
    current = baseline_key(baseline) if baseline else None
    results = {"Measured peaks": peak_result, "Fitted components": fit_result}
    library_keys = {
        c["id"]: library_key(Compound(**dict(c, aliases=tuple(c.get("aliases", ())))))
        for c in (library or [])
    }
    return [
        dict(
            label,
            stale=(
                label["result_key"] != keys.get(label["origin"])
                or getattr(results.get(label["origin"]), "baseline_key", None) != current
                or (
                    library is not None
                    and label.get("compound_id")
                    and library_keys.get(label["compound_id"]) != label.get("library_key")
                )
            ),
        )
        for label in labels
    ]
