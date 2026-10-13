# Implementation roadmap

Milestone 0 and the text-import/inspection slice of milestone 1 are implemented.
The baseline and peak detection/integration slices of milestone 3, and constrained
component fitting in milestone 4, are implemented. No dates or
vendor compatibility are promised.

## 0 — Foundation (current)
Coding guidance, product/architecture/UX documents, dependency configuration, and
root run_app.py launching the workspace, with dependencies installed in .venv.

## 1 — Inspect one chromatogram
Implemented: typed immutable traces, source hashes and mapping provenance, text
preview/locale controls, cancellable background imports, interactive plotting,
trace switching, sample readout, source table, and shared visual styling. Synthetic
fixtures and focused importer/Qt tests are present. Native macOS launch and modal
import are checked. Windows and representative real lab files remain unverified.

Implement typed trace/units/provenance, delimited text import with preview, and
responsive plotting/channel selection. Establish visual tokens and first workspace
layout. Add a synthetic fixture and meaningful importer/unit tests.

Exit: open a real permitted lab export on macOS and Windows, inspect its values,
and report invalid inputs without silently modifying them.

## 2 — Image digitization
Implement crop/orientation, linear axis calibration, assisted/manual tracing,
gap correction, source overlay, saved digitization record, and CSV point export.
Begin with one clear trace per image; add artifact/multi-trace handling incrementally.

Exit: synthetic plotted curves recover time/height/area within documented tolerances;
saved calibration is reproducible, uncalibrated traces cannot be quantified, and
source provenance/limitations stay visible downstream.

## 3 — Baseline, peaks, labels, and reproducible single-trace projects
Baseline slice implemented: two automatic spline methods, presets, polarity,
manual/refinement anchors, protected/excluded regions, live linked plots, diagnostics,
apply/discard/clear, and per-trace undo/redo. Numerical recovery and asynchronous UI
tests plus native macOS checks pass. Peak detection/integration now includes signed
measurements, actual-time filters, editable boundaries, synchronized tables/plots,
review flags, history, cancellation, and baseline invalidation. These remain
session-only; labels, project saving, and real-vendor validation remain outstanding.

Add full-trace baseline methods/preview/manual refinement, detection, editable
integration boundaries, quantitative peak tables, compound assignments and label
placement. Implement undo/redo and project save/reopen using a chosen versioned schema.
Investigate AIA and prioritized vendor exports with fixtures alongside this phase.

Exit: known peak areas are recovered within justified tolerances across drift,
overlaps, polarity, and irregular sampling; saving preserves results and recipes.

## 4 — Overlapping-peak fitting and polished figure exports
Implemented: constrained Gaussian/EMG component fits, editable bounds/locks, live
components/residuals, signed full/window areas, count comparisons, fit diagnostics,
accepted history, cancellation and stale-baseline checks. See DECONVOLUTION.md.
Native macOS is checked; native Windows and real lab validation remain outstanding.

Implement the shared FigureSpec with PNG/TIFF/PDF/SVG, exact
dimensions, background options, export presets, and preview.

Exit: controlled overlap fixtures validate component recovery/failure diagnostics;
all four output formats pass size, transparency, labeling, and clipping checks.
Conduct visual reviews of the complete single-trace journey on both target systems.

## 5 — Batch and calibration
Add reusable recipes, sample roles, compound matching review, standard concentrations,
linear calibration, concentration results, replicate QC, and batch error isolation.
Extend to weighted/internal-standard approaches after the foundational workflow works.

Exit: an explicit standard set generates traceable calibration plots and results;
missing peaks, excluded standards, stale calibrations, and out-of-range samples are
visible. A failed file must not invalidate unrelated successful batch results.

## Later
Retention alignment, blank/carryover/suitability tools, broader native formats,
advanced reporting, optional PDA/DAD data, and release packaging. Prioritize based
on actual lab examples and measured pain points rather than adding controls speculatively.

## Validation principles
Use documented, deterministic synthetic fixtures with truth for baselines, peaks,
image recovery, and calibration. Add licensed anonymized vendor examples for each
supported variant. Define acceptance tolerances from intended use before tuning.
Test core functions without a GUI; add targeted Qt interaction tests for important
flows. Include save/reopen and export round-trips. Set performance budgets after
representative trace sizes and images are known; do not invent benchmarks.
