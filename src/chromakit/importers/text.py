"""Delimited text import with explicit mapping, locale choices and provenance."""

import csv
import hashlib
import io
import re
import shlex
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from chromakit.domain import TIME_SCALES, Trace, readonly_array

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 1_000_000
DELIMITERS = {"Comma": ",", "Tab": "\t", "Semicolon": ";", "Pipe": "|"}


class ImportProblem(ValueError):
    """An actionable input validation failure."""


class ImportCancelled(Exception):
    """Cooperative cancellation."""


def check_cancel(cancel: Callable[[], bool]) -> None:
    if cancel():
        raise ImportCancelled


@dataclass(frozen=True)
class TextSource:
    path: Path
    content: bytes
    sha256: str


@dataclass(frozen=True)
class ParseOptions:
    delimiter: str = "Auto"
    encoding: str = "Auto"
    decimal: str = "."
    skip_rows: int = 0
    header: str = "Auto"


@dataclass(frozen=True)
class ParsedTable:
    source: TextSource
    options: ParseOptions
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    line_numbers: tuple[int, ...]
    delimiter: str
    encoding: str
    decimal: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ColumnMapping:
    time: int = 0
    signal: int = 1
    time_unit: str = "unknown"
    signal_unit: str = "unknown"
    detector: str = "Unspecified"
    name: str = ""
    missing_signal: str = "Reject"


def load_source(path: Path, cancel: Callable[[], bool] = lambda: False) -> TextSource:
    try:
        chunks = []
        size = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                check_cancel(cancel)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ImportProblem("This first importer supports files up to 64 MiB.")
                chunks.append(chunk)
        content = b"".join(chunks)
    except OSError as error:
        raise ImportProblem(f"Cannot read this file: {error.strerror}") from error
    if not content:
        raise ImportProblem("The file is empty. Choose a sampled time/signal export.")
    return TextSource(path.resolve(), content, hashlib.sha256(content).hexdigest())


def decode(source: TextSource, requested: str) -> tuple[str, str]:
    encoding = requested
    if encoding == "Auto":
        encoding = (
            "utf-16" if source.content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        )
    try:
        text = source.content.decode(encoding)
    except (UnicodeError, LookupError) as error:
        raise ImportProblem(
            "Cannot decode this file. Select its encoding (try Windows-1252)."
        ) from error
    if "\x00" in text:
        raise ImportProblem("This looks like binary data or the wrong encoding. Use a text export.")
    return text, encoding


def number(value: str, decimal: str) -> float:
    cleaned = value.strip().replace("−", "-")
    if decimal == ",":
        if "." in cleaned:
            raise ValueError("Period present with comma decimal")
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def detect_delimiter(lines: list[str]) -> str:
    sample = [line for line in lines[:100] if line.strip() and not line.lstrip().startswith("#")]
    scores = []
    for name, delimiter in DELIMITERS.items():
        try:
            widths = [len(row) for row in csv.reader(sample, delimiter=delimiter, strict=True)]
        except csv.Error:
            continue
        if widths:
            width, count = Counter(widths).most_common(1)[0]
            if width >= 2:
                scores.append((count / len(widths), count, width, name))
    return max(scores)[-1] if scores else "Whitespace"


def parse_source(
    source: TextSource,
    options: ParseOptions,
    cancel: Callable[[], bool] = lambda: False,
) -> ParsedTable:
    check_cancel(cancel)
    text, encoding = decode(source, options.encoding)
    lines = text.splitlines()[options.skip_rows :]
    delimiter = detect_delimiter(lines) if options.delimiter == "Auto" else options.delimiter
    if delimiter not in {*DELIMITERS, "Whitespace"}:
        raise ImportProblem("Choose a supported delimiter.")
    decimal = options.decimal
    if decimal not in {".", ","}:
        raise ImportProblem("Choose a period or comma decimal separator.")
    rows: list[tuple[str, ...]] = []
    line_numbers = []
    ignored = 0
    commented_header = None
    try:
        reader = (
            (shlex.split(line, comments=False) for line in lines)
            if delimiter == "Whitespace"
            else csv.reader(
                io.StringIO("\n".join(lines)), delimiter=DELIMITERS[delimiter], strict=True
            )
        )
        for index, cells in enumerate(reader):
            if index % 2048 == 0:
                check_cancel(cancel)
            line = options.skip_rows + (index + 1 if delimiter == "Whitespace" else reader.line_num)
            if not cells or all(not cell.strip() for cell in cells):
                ignored += 1
                continue
            if cells[0].lstrip().startswith("#"):
                candidate = (
                    tuple(cells[1:])
                    if cells[0].strip() == "#"
                    else (cells[0].lstrip()[1:].strip(), *cells[1:])
                )
                if (
                    not rows
                    and len(candidate) >= 2
                    and re.search(r"(?:^|[\s_])(?:time|retention)(?:$|[\s_(])", candidate[0], re.I)
                ):
                    commented_header = tuple(cell.strip() for cell in candidate)
                ignored += 1
                continue
            rows.append(tuple(cell.strip() for cell in cells))
            line_numbers.append(line)
            if len(rows) > MAX_ROWS:
                raise ImportProblem("This first importer supports up to 1,000,000 rows.")
    except (csv.Error, ValueError) as error:
        if isinstance(error, ImportProblem):
            raise
        raise ImportProblem(
            f"Cannot parse the text: {error}. Check delimiter and quoting."
        ) from error
    if not rows:
        raise ImportProblem("No data rows found. Check skipped rows and delimiter.")
    width = len(rows[0])
    if width < 2:
        raise ImportProblem("At least two columns are needed. Check the delimiter or skipped rows.")
    for row, line in zip(rows, line_numbers, strict=True):
        if len(row) != width:
            raise ImportProblem(
                f"Line {line} has {len(row)} columns; expected {width}. "
                "Check the delimiter, skip metadata rows, or fix this row. No data was dropped."
            )
    use_commented_header = (
        options.header == "Auto" and commented_header is not None and len(commented_header) == width
    )
    has_header = options.header == "Yes"
    if options.header == "Auto" and not use_commented_header:
        numeric_cells = 0
        for value in rows[0]:
            try:
                number(value, decimal)
            except ValueError:
                continue
            numeric_cells += 1
        # Categorical columns must not cause the first sampled row to disappear.
        has_header = numeric_cells == 0 or any(
            re.search(r"\btime\b|\bretention\b", cell, re.I) for cell in rows[0]
        )
    columns = (
        commented_header
        if use_commented_header
        else rows.pop(0)
        if has_header
        else tuple(f"Column {i + 1}" for i in range(width))
    )
    if has_header:
        line_numbers.pop(0)
    if len(rows) < 2:
        raise ImportProblem("At least two sampled data rows are needed. Check the header setting.")
    warnings = [f"Skipped {ignored} blank/comment lines."] if ignored else []
    if use_commented_header:
        warnings.append(
            "Recognized a leading commented column header; no sampled rows were removed."
        )
    if options.skip_rows:
        warnings.append(f"Skipped {options.skip_rows} leading lines as requested.")
    return ParsedTable(
        source,
        options,
        tuple(columns),
        tuple(rows),
        tuple(line_numbers),
        delimiter,
        encoding,
        decimal,
        tuple(warnings),
    )


def suggest_mapping(table: ParsedTable) -> ColumnMapping:
    time = next(
        (i for i, name in enumerate(table.columns) if re.search(r"time|retention", name, re.I)), 0
    )
    signal = next((i for i in range(len(table.columns)) if i != time), 1)
    name = table.columns[time].lower().replace("_", " ")
    unit = "unknown"
    if re.search(r"\bmin(?:utes)?\b", name):
        unit = "min"
    elif re.search(r"\bs(?:ec(?:onds)?)?\b", name):
        unit = "s"
    elif re.search(r"\bh(?:ours)?\b", name):
        unit = "h"
    signal_unit = "unknown"
    match = re.search(r"[\[(]([^\])]+)[\])]", table.columns[signal])
    if match:
        signal_unit = match[1].strip()
    elif re.search(r"(?:^|_)mAU$", table.columns[signal], re.I):
        signal_unit = "mAU"
    return ColumnMapping(time, signal, unit, signal_unit, name=table.source.path.stem)


def build_trace(
    table: ParsedTable,
    mapping: ColumnMapping,
    cancel: Callable[[], bool] = lambda: False,
) -> Trace:
    if mapping.time == mapping.signal:
        raise ImportProblem("Time and signal must use different columns.")
    if not all(0 <= index < len(table.columns) for index in (mapping.time, mapping.signal)):
        raise ImportProblem("The selected columns no longer exist. Review the mapping.")
    if mapping.time_unit not in TIME_SCALES:
        raise ImportProblem("Choose seconds, minutes, hours, or unknown time units.")
    if mapping.missing_signal not in {"Reject", "Omit with gaps"}:
        raise ImportProblem("Choose a supported missing-signal policy.")
    time = np.empty(len(table.rows), dtype=np.float64)
    missing = np.zeros(len(table.rows), dtype=bool)
    signal = np.empty_like(time)
    for index, (row, line) in enumerate(zip(table.rows, table.line_numbers, strict=True)):
        if index % 2048 == 0:
            check_cancel(cancel)
        for column, destination in ((mapping.time, time), (mapping.signal, signal)):
            token = row[column].strip().lower()
            if column == mapping.signal and token in {"", "nan", "+nan", "-nan", "na", "n/a"}:
                if mapping.missing_signal == "Omit with gaps":
                    missing[index] = True
                    destination[index] = np.nan
                    continue
                raise ImportProblem(
                    f"Line {line}, column {column + 1} is missing or nonfinite. "
                    "To import incomplete traces, select Missing signal: Omit with gaps. "
                    "Missing values will not be replaced or interpolated."
                )
            try:
                value = number(row[column], table.decimal)
            except ValueError as error:
                raise ImportProblem(
                    f"Line {line}, column {column + 1} is not numeric ({row[column][:40]!r}). "
                    "Check columns, decimal separator, and skipped rows."
                ) from error
            if not np.isfinite(value):
                raise ImportProblem(f"Line {line}, column {column + 1} is missing or nonfinite.")
            destination[index] = value
    with np.errstate(over="ignore", invalid="ignore"):
        delta = np.diff(time)
    if np.any(delta <= 0):
        index = int(np.flatnonzero(delta <= 0)[0]) + 1
        raise ImportProblem(
            f"Time must strictly increase: check line {table.line_numbers[index]}. "
            "Duplicate or reversed coordinates were not sorted or removed."
        )
    retained = np.flatnonzero(~missing)
    if len(retained) < 2:
        raise ImportProblem(
            "At least two finite signal samples are needed after omitting missing values."
        )
    omitted_lines = tuple(table.line_numbers[i] for i in np.flatnonzero(missing))
    time, signal = time[retained], signal[retained]
    delta = np.diff(time)
    source_time = readonly_array(time)
    with np.errstate(over="ignore", invalid="ignore"):
        time *= TIME_SCALES[mapping.time_unit]
    if not np.all(np.isfinite(time)) or not np.all(np.isfinite(delta)):
        raise ImportProblem("Time coordinates exceed the supported numerical range.")
    with np.errstate(over="ignore", invalid="ignore"):
        normalized_delta = np.diff(time)
    if not np.all(np.isfinite(normalized_delta)) or np.any(normalized_delta <= 0):
        raise ImportProblem("Time coordinates exceed precision or range after unit conversion.")
    with np.errstate(over="ignore", invalid="ignore"):
        sampling_gaps = delta > np.median(delta) * 5
        missing_gaps = np.diff(retained) > 1
        gaps = sampling_gaps | missing_gaps
    warnings = list(table.warnings)
    if mapping.time_unit == "unknown":
        warnings.append("Time unit is unknown; coordinates are displayed as supplied.")
    if not mapping.signal_unit.strip() or mapping.signal_unit == "unknown":
        warnings.append("Signal unit is unknown; no physical quantification is available.")
    if omitted_lines:
        warnings.append(
            f"Omitted {len(omitted_lines)} missing signal row(s) by explicit choice; "
            f"preserved {np.count_nonzero(missing_gaps)} internal break(s). "
            "Missing endpoints are truncated; missing intervals are never "
            "interpolated or integrated across."
        )
    if np.any(sampling_gaps):
        warnings.append(
            f"{np.count_nonzero(sampling_gaps)} possible sampling gap(s) "
            "exceed 5× the median interval. "
            "The plot leaves these intervals disconnected."
        )
    elif not np.allclose(delta, np.median(delta), rtol=1e-4, atol=0):
        warnings.append("Sampling is nonuniform. Original time coordinates are preserved.")
    return Trace(
        mapping.name.strip() or table.source.path.stem,
        table.source.path,
        table.source.sha256,
        readonly_array(time),
        source_time,
        readonly_array(signal),
        mapping.time_unit,
        mapping.signal_unit.strip() or "unknown",
        table.columns[mapping.signal],
        mapping.detector,
        table.encoding,
        table.delimiter,
        table.columns[mapping.time],
        tuple(warnings),
        readonly_array(gaps, np.bool_),
        (
            ("reader_version", "text-v2"),
            ("header", table.options.header),
            ("missing_signal", mapping.missing_signal),
            ("source_data_rows", str(len(table.rows))),
            ("omitted_signal_lines", ",".join(str(line) for line in omitted_lines)),
            ("skip_rows", str(table.options.skip_rows)),
            ("decimal", table.decimal),
            ("time_column", str(mapping.time + 1)),
            ("signal_column", str(mapping.signal + 1)),
            ("time_unit", mapping.time_unit),
            ("signal_unit", mapping.signal_unit.strip() or "unknown"),
        ),
    )
