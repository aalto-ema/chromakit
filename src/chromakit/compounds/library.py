import csv
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from uuid import uuid4

import numpy as np

from chromakit.domain import TIME_SCALES
from chromakit.importers.text import ImportProblem


@dataclass(frozen=True)
class Compound:
    id: str
    name: str
    start: float
    end: float
    time_unit: str = "min"
    aliases: tuple[str, ...] = ()
    formula: str = ""
    detector: str = ""


def validate(compounds):
    if len(compounds) > 10000 or len({c.id for c in compounds}) != len(compounds):
        raise ImportProblem("Use at most 10,000 compounds with distinct stable IDs.")
    for c in compounds:
        if (
            not c.id
            or not c.name.strip()
            or not np.isfinite([c.start, c.end]).all()
            or c.start >= c.end
        ):
            raise ImportProblem(
                "Each compound needs an ID, name and increasing finite retention window."
            )
        if (
            c.time_unit not in TIME_SCALES
            or c.time_unit == "unknown"
            or c.detector not in {"", "UV", "RID", "PAD"}
        ):
            raise ImportProblem("Choose a known time unit and Any/UV/RID/PAD detector.")


def library_key(compound):
    return hashlib.sha256(
        json.dumps(asdict(compound), sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def library_bytes(compounds, format="json"):
    format = format.lower()
    if format not in {"csv", "json"}:
        raise ImportProblem("Choose CSV or JSON for the library.")
    validate(compounds)
    if format == "json":
        return json.dumps(
            {
                "format": "chromakit-compounds",
                "schema_version": 1,
                "compounds": [asdict(c) for c in compounds],
            },
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ).encode()
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=["id", "name", "start", "end", "time_unit", "aliases", "formula", "detector"],
    )
    writer.writeheader()
    for c in compounds:
        row = asdict(c)
        row["aliases"] = "; ".join(c.aliases)
        writer.writerow(row)
    return stream.getvalue().encode("utf-8-sig")


def read_library(data, format="json"):
    format = format.lower()
    if format not in {"csv", "json"}:
        raise ImportProblem("Choose CSV or JSON for the library.")
    if len(data) > 10 * 1024 * 1024:
        raise ImportProblem("Limit library files to 10 MiB.")
    try:
        text = data.decode("utf-8-sig")
        if format == "json":
            document = json.loads(text)
            if document["format"] != "chromakit-compounds" or document["schema_version"] != 1:
                raise ImportProblem("Unsupported compound library schema.")
            records = document["compounds"]
        else:
            records = list(csv.DictReader(io.StringIO(text)))
        compounds = tuple(
            Compound(
                str(r.get("id") or uuid4().hex),
                str(r["name"]),
                float(r["start"]),
                float(r["end"]),
                str(r.get("time_unit", "min")),
                tuple(v.strip() for v in r.get("aliases", "").split(";") if v.strip())
                if isinstance(r.get("aliases", ""), str)
                else tuple(r.get("aliases", ())),
                str(r.get("formula", "")),
                str(r.get("detector", "")),
            )
            for r in records
        )
        validate(compounds)
        return compounds
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ImportProblem("Cannot read compound library: " + str(error)) from error


def match_peaks(trace, peaks, compounds):
    validate(compounds)
    if trace.time_unit == "unknown":
        raise ImportProblem("Confirm trace time units before retention-window matching.")
    scale = TIME_SCALES[trace.time_unit]
    matches = {}
    for peak in peaks:
        matches[peak.id] = tuple(
            c
            for c in compounds
            if (not c.detector or c.detector == trace.detector)
            and c.start * TIME_SCALES[c.time_unit]
            <= peak.retention_time * scale
            <= c.end * TIME_SCALES[c.time_unit]
        )
    counts = {c.id: sum(c in values for values in matches.values()) for c in compounds}
    return [
        (p, matches[p.id], len(matches[p.id]) != 1 or any(counts[c.id] > 1 for c in matches[p.id]))
        for p in peaks
        if matches[p.id]
    ]
