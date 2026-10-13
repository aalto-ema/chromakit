"""Atomic ZIP/JSON/NPY projects with immutable arrays and bounded validation."""

import hashlib
import io
import json
import os
import re
import tempfile
import types
import typing
import zipfile
from copy import deepcopy
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path

import numpy as np

from chromakit.analysis.baseline import (
    Anchor,
    BaselineRecipe,
    BaselineResult,
    MaskRegion,
    SegmentDiagnostic,
    validate_recipe,
)
from chromakit.analysis.deconvolution import Component, FitRecipe, FitResult, FittedPeak, Parameter
from chromakit.analysis.peaks import Peak, PeakRecipe, PeakResult
from chromakit.application.baselines import BaselineState
from chromakit.application.deconvolution import FitState
from chromakit.application.peaks import PeakState
from chromakit.domain import TIME_SCALES, Trace, readonly_array
from chromakit.importers.text import ImportCancelled, ImportProblem
from chromakit.persistence.extra_validation import validate_extras

VERSION = 1
LIMIT = 512 * 1024 * 1024
REGISTRY = {
    cls.__name__: cls
    for cls in (
        Trace,
        Anchor,
        MaskRegion,
        BaselineRecipe,
        SegmentDiagnostic,
        BaselineResult,
        PeakRecipe,
        Peak,
        PeakResult,
        Parameter,
        Component,
        FitRecipe,
        FittedPeak,
        FitResult,
    )
}


class ProjectProblem(ImportProblem):
    """Invalid or unsupported project; existing session is preserved."""


def matches_type(value, expected):
    origin = typing.get_origin(expected)
    args = typing.get_args(expected)
    if origin in (types.UnionType, typing.Union):
        return any(matches_type(value, option) for option in args)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(matches_type(item, args[0]) for item in value)
        return len(value) == len(args) and all(
            matches_type(v, t) for v, t in zip(value, args, strict=True)
        )
    if expected is float:
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value)
        )
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected in (typing.Any, object):
        return True
    if (
        expected is np.ndarray
        or origin is np.ndarray
        or getattr(origin, "__name__", None) == "NDArray"
    ):
        return isinstance(value, np.ndarray) and np.isfinite(value).all()
    return isinstance(value, origin or expected)


def validate_record(record):
    annotations = typing.get_type_hints(type(record))
    for field in fields(record):
        value = getattr(record, field.name)
        if not matches_type(value, annotations[field.name]):
            raise ProjectProblem(f"Invalid field {type(record).__name__}.{field.name}.")
        if isinstance(value, np.ndarray) and value.dtype != (
            np.dtype("bool") if field.name == "gap_after" else np.dtype("float64")
        ):
            raise ProjectProblem("Invalid scientific array type.")
    return record


def snapshot(baselines, peaks, fits, selected=0, extras=None):
    if not len(baselines) == len(peaks) == len(fits):
        raise ProjectProblem("Project state lists do not match.")
    return {
        "selected": selected,
        "extras": deepcopy(extras or {}),
        "traces": [
            {
                "trace": baseline.trace,
                "baseline": {
                    name: tuple(getattr(baseline, name))
                    if name.endswith("history")
                    else getattr(baseline, name)
                    for name in ("draft", "applied", "undo_history", "redo_history")
                },
                "peaks": {
                    name: tuple(getattr(peak, name))
                    if name.endswith("history")
                    else getattr(peak, name)
                    for name in ("recipe", "result", "undo_history", "redo_history", "selected_id")
                },
                "fits": {
                    name: tuple(getattr(fitted, name))
                    if name.endswith("history")
                    else getattr(fitted, name)
                    for name in ("recipe", "result", "undo_history", "redo_history")
                },
            }
            for baseline, peak, fitted in zip(baselines, peaks, fits, strict=True)
        ],
    }


def save_project(path: Path, project: dict, cancel=lambda: False):
    arrays = {}

    def encode(value):
        if cancel():
            raise ImportCancelled()
        if isinstance(value, bytes):
            name = f"assets/{len(arrays)}.bin"
            arrays[name] = value
            return {"blob": name, "sha256": hashlib.sha256(value).hexdigest()}
        if isinstance(value, np.ndarray):
            name = f"arrays/{len(arrays)}.npy"
            buffer = io.BytesIO()
            np.save(buffer, value, allow_pickle=False)
            payload = buffer.getvalue()
            arrays[name] = payload
            return {"array": name, "sha256": hashlib.sha256(payload).hexdigest()}
        if isinstance(value, Path):
            return {"path": str(value)}
        if is_dataclass(value):
            return {
                "type": type(value).__name__,
                "fields": {
                    field.name: encode(getattr(value, field.name)) for field in fields(value)
                },
            }
        if isinstance(value, tuple):
            return {"tuple": [encode(item) for item in value]}
        if isinstance(value, list):
            return [encode(item) for item in value]
        if isinstance(value, dict):
            return {"mapping": {key: encode(item) for key, item in value.items()}}
        return value

    document = {"format": "chromakit", "schema_version": VERSION, "session": encode(project)}
    payload = json.dumps(document, allow_nan=False, ensure_ascii=False).encode()
    if len(payload) + sum(map(len, arrays.values())) > LIMIT:
        raise ProjectProblem("Project exceeds the 512 MiB uncompressed limit.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", payload)
                for name, data in arrays.items():
                    if cancel():
                        raise ImportCancelled()
                    archive.writestr(name, data)
            stream.flush()
            os.fsync(stream.fileno())
        if cancel():
            raise ImportCancelled()
        os.replace(temporary, path)
    except (ValueError, TypeError) as error:
        raise ProjectProblem(f"Could not encode project: {error}") from error
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return path


def load_project(path: Path, cancel=lambda: False):
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 20000 or sum(item.file_size for item in members) > LIMIT:
                raise ProjectProblem("Project exceeds archive safety limits.")
            names = [item.filename for item in members]
            if len(names) != len(set(names)) or any(
                not re.fullmatch(r"manifest\.json|arrays/[0-9]+\.npy|assets/[0-9]+\.bin", name)
                for name in names
            ):
                raise ProjectProblem("Unexpected or duplicate project archive members.")
            if archive.getinfo("manifest.json").file_size > 32 * 1024 * 1024:
                raise ProjectProblem("Project manifest is too large.")
            document = json.loads(
                archive.read("manifest.json"),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
            )
            if document.get("format") != "chromakit" or document.get("schema_version") != VERSION:
                raise ProjectProblem("Unsupported project schema; this app reads version 1.")

            def decode(value, depth=0):
                if cancel():
                    raise ImportCancelled()
                if depth > 80:
                    raise ProjectProblem("Project nesting is excessive.")
                if isinstance(value, list):
                    return [decode(item, depth + 1) for item in value]
                if not isinstance(value, dict):
                    return value
                if set(value) == {"mapping"}:
                    return {key: decode(item, depth + 1) for key, item in value["mapping"].items()}
                if "blob" in value:
                    data = archive.read(value["blob"])
                    if hashlib.sha256(data).hexdigest() != value["sha256"]:
                        raise ProjectProblem("Embedded asset checksum failed.")
                    return data
                if "array" in value:
                    data = archive.read(value["array"])
                    if hashlib.sha256(data).hexdigest() != value["sha256"]:
                        raise ProjectProblem("Project array checksum failed.")
                    buffer = io.BytesIO(data)
                    version = np.lib.format.read_magic(buffer)
                    reader = {
                        (1, 0): np.lib.format.read_array_header_1_0,
                        (2, 0): np.lib.format.read_array_header_2_0,
                    }.get(version)
                    if reader is None:
                        raise ProjectProblem("Unsupported numerical array encoding.")
                    shape, _order, dtype = reader(buffer)
                    if len(shape) != 1 or dtype not in (np.dtype("float64"), np.dtype("bool")):
                        raise ProjectProblem("Invalid array dimensions/type.")
                    if shape[0] * dtype.itemsize != len(data) - buffer.tell():
                        raise ProjectProblem("Array length does not match its payload.")
                    array = np.load(io.BytesIO(data), allow_pickle=False)
                    if (
                        array.dtype not in (np.dtype("float64"), np.dtype("bool"))
                        or array.ndim != 1
                    ):
                        raise ProjectProblem("Project arrays must be one-dimensional float64/bool.")
                    return readonly_array(array, array.dtype)
                if "path" in value:
                    return Path(value["path"])
                if "tuple" in value:
                    return tuple(decode(item, depth + 1) for item in value["tuple"])
                if "type" in value:
                    cls = REGISTRY.get(value["type"])
                    if (
                        cls is None
                        or not set(value["fields"]).issubset({field.name for field in fields(cls)})
                        or any(
                            field.name not in value["fields"]
                            and field.default is MISSING
                            and field.default_factory is MISSING
                            for field in fields(cls)
                        )
                    ):
                        raise ProjectProblem("Unknown record type or fields in project.")
                    return validate_record(
                        cls(
                            **{
                                key: decode(item, depth + 1)
                                for key, item in value["fields"].items()
                            }
                        )
                    )
                return {key: decode(item, depth + 1) for key, item in value.items()}

            project = decode(document["session"])
        if (
            not isinstance(project["traces"], list)
            or len(project["traces"]) > 1000
            or not isinstance(project["extras"], dict)
            or not isinstance(project["selected"], int)
        ):
            raise ProjectProblem("Invalid project session structure.")
        baselines, peaks, fits = [], [], []
        identifiers = set()
        for record in project["traces"]:
            trace = record["trace"]
            if not isinstance(trace, Trace) or not trace.id or trace.id in identifiers:
                raise ProjectProblem("Invalid trace record.")
            identifiers.add(trace.id)
            validate_recipe(trace, record["baseline"]["draft"])
            if (
                trace.time_unit not in TIME_SCALES
                or trace.time.shape != trace.signal.shape
                or not np.all(np.isfinite(trace.time))
                or not np.array_equal(trace.time, trace.source_time * TIME_SCALES[trace.time_unit])
            ):
                raise ProjectProblem("Trace coordinates and units do not agree.")
            baseline = BaselineState(
                trace,
                **{
                    key: list(value) if key.endswith("history") else value
                    for key, value in record["baseline"].items()
                },
            )
            for result in [baseline.applied, *baseline.undo_history, *baseline.redo_history]:
                if result and (
                    len(result.baseline) != len(trace.signal)
                    or len(result.corrected) != len(trace.signal)
                ):
                    raise ProjectProblem("Baseline arrays do not match the trace.")
            baseline.preview = baseline.applied
            peak = PeakState(
                baseline,
                **{
                    key: list(value) if key.endswith("history") else value
                    for key, value in record["peaks"].items()
                },
            )
            peak.sync_baseline()
            fitted = FitState(
                baseline,
                **{
                    key: list(value) if key.endswith("history") else value
                    for key, value in record["fits"].items()
                },
            )
            fitted.preview = (
                fitted.result if fitted.recipe == getattr(fitted.result, "recipe", None) else None
            )
            baselines.append(baseline)
            peaks.append(peak)
            fits.append(fitted)
        validate_extras(project["extras"], validate_record)
        return baselines, peaks, fits, project["selected"], project["extras"]
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        zipfile.BadZipFile,
        RecursionError,
    ) as error:
        if isinstance(error, ProjectProblem):
            raise
        raise ProjectProblem(f"Cannot open this project: {error}") from error
