"""Reusable text/analysis recipes with cancellable, isolated per-file outcomes."""

from dataclasses import dataclass
from pathlib import Path

from chromakit.analysis.baseline import BaselineCancelled, BaselineProblem, estimate_baseline
from chromakit.analysis.deconvolution import FitProblem, fit
from chromakit.analysis.peaks import PeakCancelled, PeakProblem, detect_peaks
from chromakit.importers.text import (
    ColumnMapping,
    ImportCancelled,
    ImportProblem,
    ParseOptions,
    build_trace,
    load_source,
    parse_source,
)


@dataclass(frozen=True)
class BatchOutcome:
    path: Path
    status: str
    message: str
    trace: object = None
    baseline: object = None
    peaks: object = None
    fitted: object = None


def text_recipe(trace):
    settings = dict(trace.import_settings)
    if not settings.get("reader_version", "").startswith("text-"):
        raise ImportProblem("Choose a text-imported trace as the batch mapping template.")
    options = ParseOptions(
        trace.delimiter,
        trace.encoding,
        settings.get("decimal", "."),
        int(settings.get("skip_rows", 0)),
        settings.get("header", "Auto"),
    )
    mapping = ColumnMapping(
        int(settings["time_column"]) - 1,
        int(settings["signal_column"]) - 1,
        trace.time_unit,
        trace.signal_unit,
        trace.detector,
        "",
        settings.get("missing_signal", "Reject"),
    )
    return options, mapping


def process_batch(
    paths,
    options,
    mapping,
    baseline_recipe,
    peak_recipe,
    fit_recipe=None,
    cancel=lambda: False,
    progress=lambda item: None,
    headers=None,
):
    if len(paths) > 2000:
        raise ImportProblem("Limit a batch to 2,000 files.")
    outcomes = []
    for path in paths:
        if cancel():
            break
        path = Path(path)
        try:
            table = parse_source(load_source(path, cancel), options, cancel)
            if headers is not None and (
                max(mapping.time, mapping.signal) >= len(table.columns)
                or (table.columns[mapping.time], table.columns[mapping.signal]) != tuple(headers)
            ):
                raise ImportProblem(
                    "Mapped column names differ from the reviewed template. "
                    "Review the file layout or explicitly disable the header check."
                )
            trace = build_trace(table, mapping, cancel)
            baseline = estimate_baseline(trace, baseline_recipe, cancel)
            peaks = detect_peaks(trace, baseline, peak_recipe, cancel)
            fitted = None
            status = "Success"
            message = "; ".join((*trace.warnings, *baseline.warnings, *peaks.warnings))
            if fit_recipe:
                try:
                    fitted = fit(trace, baseline, fit_recipe, cancel)
                    message += "; " + "; ".join(fitted.warnings)
                except FitProblem as error:
                    status = "Partial"
                    message += "; Fit failed: " + str(error)
            outcome = BatchOutcome(path, status, message, trace, baseline, peaks, fitted)
        except (ImportCancelled, BaselineCancelled, PeakCancelled):
            break
        except (ImportProblem, BaselineProblem, PeakProblem, OSError) as error:
            outcome = BatchOutcome(path, "Failed", str(error))
        outcomes.append(outcome)
        progress(outcome)
    return tuple(outcomes)


def stored_recipe(record):
    """Rebuild only known recipe records; never import class names from a project."""
    from chromakit.analysis.baseline import Anchor, BaselineRecipe, MaskRegion
    from chromakit.analysis.deconvolution import Component, FitRecipe, Parameter
    from chromakit.analysis.peaks import PeakRecipe

    baseline = dict(record["baseline"])
    baseline.update(
        anchors=tuple(Anchor(**a) for a in baseline.get("anchors", [])),
        regions=tuple(MaskRegion(**r) for r in baseline.get("regions", [])),
    )
    fitted = None
    if record.get("fit"):
        values = dict(record["fit"])
        values["components"] = tuple(
            Component(
                **dict(
                    c, **{name: Parameter(**c[name]) for name in ["area", "center", "sigma", "tau"]}
                )
            )
            for c in values["components"]
        )
        fitted = FitRecipe(**values)
    return (
        ParseOptions(**record["parse"]),
        ColumnMapping(**record["mapping"]),
        BaselineRecipe(**baseline),
        PeakRecipe(**record["peaks"]),
        fitted,
    )
