# Architecture and scientific contracts

## Direction
Python 3.11+, PySide6 with Qt Widgets, local-first research workflow. These are
implementation defaults; use docs/DECISIONS.md when a choice changes. The current
implementation contains the launcher, domain.py, importers/text.py, and UI modules
for the window, mapping dialog, read-only models, styling, and background tasks.
analysis/baseline.py holds pure estimation contracts and algorithms;
application/baselines.py holds per-trace drafts/applied history. The baseline panel
and single-worker controller handle debouncing, cancellation, and stale generations.
analysis/peaks.py implements signed detection and sampled integration;
application/peaks.py tracks per-trace history and corrected-baseline fingerprints.
PeakPanel uses a table model editable only in boundary columns and a cancellable
worker sharing the generation-checked scheduler. Measurements consume applied
baselines only, with physical-coordinate integration and gap/artifact segmentation.

analysis/deconvolution.py implements constrained Gaussian/EMG fits, explicit recipes,
full/window fitted areas and diagnostics. application/deconvolution.py stores per-trace
drafts and accepted history. FitPanel exposes bounds/locks, live streamed components
and residuals, alternative counts and fitted tables; FitController extends the
generation scheduler to reject obsolete provisional curves as well as final results.

Grow the package as features arrive:

```text
run_app.py                  source-checkout entry point
src/chromakit/
  app.py                    application bootstrap
  domain/                   typed records, units, validation
  importers/                sniffing, readers, normalized import results
  digitization/             image calibration, tracing, uncertainty
  analysis/                 baseline, peak detection, integration, fitting
  application/              use cases, recipes, task orchestration, undo
  ui/                       main window, models, panels, shared tokens
  persistence/              versioned project schema and safe saves
  export/                   figure specs, renderers, result tables
tests/                      focused numerical, format, project, and UI tests
```

Dependencies flow from UI to application services to domain/analysis; neither
domain nor analysis knows about Qt, widgets, or user-facing dialogs. Readers and
exporters use domain contracts. Do not create all modules before they are needed.

## Core records (design contracts, not implemented classes)
- `Trace`: stable ID, time and signal arrays, explicit units, channel/detector,
  metadata, and provenance. Arrays must be treated as immutable inputs.
- `ImportResult`: traces, source hash, reader/version, metadata, warnings, and
  proposed repair actions. Original observations stay recoverable.
- `DigitizationRecord`: image hash/reference, pixel-to-data transform, calibration
  anchors/units, masks, extracted path, edits, gap map, and uncertainty information.
  Trace provenance distinguishes native acquisition, text export, and image recovery.
- `ProcessingRecipe`: ordered steps, method/version, parameters, units, region
  masks, dependencies, and random seed where relevant.
- `AnalysisResult`: input/recipe identity, output arrays, diagnostics, warnings,
  version, and timestamp. Cache identity includes all scientifically relevant inputs.
- `Peak`: stable ID, region, apex, polarity, baseline reference, area/height/units,
  quality flags, and analytical versus fitted measurement origin.
- `FitResult`: component models/parameters/bounds, objective, convergence,
  residuals, parameter uncertainty when justified, and component areas.
- `CompoundAssignment`: compound ID, peak ID, status, rule/manual provenance.
  A separate annotation record holds text and presentation offsets.
- `Calibration`: standards and peak references, concentrations/units, replicate
  data, model/weights, exclusions, diagnostics, valid range, and version.
- `FigureSpec`: trace/result references, physical/pixel dimensions, DPI, background,
  axis bounds, theme, labels, legend, and export format options.

## Numerical conventions
Preserve original units; normalize time internally to seconds with reversible
display conversion. Unknown units require confirmation before physical quantification.
Area units are signal × time; concentration is a separate calibrated result.
Require finite strictly increasing coordinates for analysis, with explicit recorded
repair for duplicates/disorder. Treat gaps as segments; do not integrate across them
without a user-selected policy. Preserve signed data and support detector polarity.

Keep baseline estimation, smoothing, peak detection, integration, fitting, and
calibration as independent pure functions with structured diagnostics. Algorithms
may impose stricter sampling assumptions; validate them or explicitly resample
with a recorded transform. Use floating-point tolerances, not exact equality.

## Rendering and responsiveness
pyqtgraph is selected for interactive traces. Matplotlib remains a candidate for
publication output. Both must use the same underlying trace,
units, labeling semantics, and explicit plot specification. Display decimation
must never affect analytical arrays or exported quantitative results.

Qt workers emit progress and structured results. A generation/request ID prevents
old results replacing newer edits. Cancellation is cooperative; use processes for
CPU-heavy work if threading is insufficient. Persist only completed accepted results.
Use Qt model/view for large peak tables and keep widget changes on the GUI thread.

## Projects and provenance
Select a versioned portable project container before implementing save/reopen.
Decide embedded versus referenced source data explicitly; referenced files need
hash validation, relinking, and a clear missing-source state. Projects should retain
digitization images/calibration and never rely on a machine-specific absolute path.
Use atomic replacement, schema validation, recovery, and migration tests. Untrusted
project files must not deserialize arbitrary code (no pickle-based project format).

Research provenance is required; validated regulatory audit/signature systems are
outside the present scope. Diagnostics/logging should avoid leaking lab data.

## Candidate building blocks
- [Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html): desktop UI.
- [pybaselines](https://pybaselines.readthedocs.io/en/latest/): baseline method library.
- [SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html):
  evaluate bounded component fitting, with application-specific diagnostics/tests.
- NumPy for arrays and integration coordinates; Matplotlib for figure rendering.
- Evaluate Pillow/OpenCV for image digitization only when the first slice needs it.

Dependency presence never substitutes for chromatogram-specific validation.

## Implemented workflow expansion
`persistence/project.py` implements version-1 portable ZIP/JSON/NPY projects with
atomic saves and field/array/feature validation. Qt project actions protect unsaved
changes and use workers. `export/` shares FigureSpec across preview and figure
formats, and exports accepted current tables. `annotations/` separates assignment
identity and layout; `digitization/` calibrates/traces images with preserved gaps.
`analysis/calibration.py` implements external weighted linear models; `application/batch.py`
provides per-file outcomes; `compounds/` validates libraries and ambiguous matches.
Feature metadata lives in project extras keyed by stable trace/compound IDs; worker
previews and transient caches remain outside the saved session. See WORKFLOWS.md.

`analysis/comparison.py` builds read-only overlays and segment-confined reference
differences. `analysis/stability.py` evaluates perturbed starts under accepted
constraints and stores scalar reports keyed to exact fit/baseline fingerprints.
`digitization/geometry.py` records image rectification; `quality.py` flags heuristic
pixel-path concerns. Modal review dialogs share cancellable generation guards and
persist scientific choices separately from worker caches.
