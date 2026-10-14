# ChromaKit coding guidance

## Purpose and current state
ChromaKit is a Python desktop app for chromatogram analysis, built with PySide6.
Target macOS and Windows research use. Initial scope is single HPLC chromatograms
from Thermo Scientific/Agilent with RID, UV, and pulsed amperometric PAD detectors;
batch and calibration follow the single-trace workflow. Include calibrated recovery
from chromatogram images for older instruments.
The repository implements a styled text-import and plotting workspace, with pure
importers, immutable trace records, and asynchronous Qt tasks. Whole-trace baseline
correction is implemented with automatic splines, manual refinement, live preview,
and applied history. Detection/integration uses the applied corrected signal, with
editable bounds, result tables, and per-trace history. Constrained deconvolution
includes Gaussian/EMG components, live residuals, editable
bounds/locks, alternative counts, diagnostics and accepted history. Portable projects, figure/result exports, compound labels, calibrated image recovery,
external-standard calibration, batch text processing and compound libraries are implemented.
Comparison overlays, image deskew/perspective/multi-color recovery, and repeated-start
fit stability reports are also implemented. Native vendor formats remain planned.
Read docs/WORKFLOWS.md for current boundaries. Read README.md,
docs/PRODUCT.md, docs/ARCHITECTURE.md, and docs/ROADMAP.md before substantial work.
Track unanswered questions in docs/DECISIONS.md. User decisions override provisional defaults.
Read docs/BASELINE.md before modifying baseline methods or their UI. Preserve the
distinction between preview and applied results, per-trace history, recipe identity,
real-coordinate fitting, gap segmentation, and cancellation at solver iterations.
Read docs/PEAKS.md before modifying peak analysis. Preserve signed measured areas,
actual-time filters, interpolated integration endpoints, and applied-baseline
fingerprints. Mark stale results; never quantify an unapplied baseline preview
or call valley-split areas deconvolved component quantities.

Read docs/DECONVOLUTION.md before modifying fitting. Preserve signed full/window
areas, explicit component shapes/bounds/locks, baseline fingerprints, provisional versus
accepted results, covariance limitations, and component-count ambiguity warnings.

## Product priorities
- Preserve raw data and make every transformation inspectable and reversible.
- Provide strong whole-trace baseline correction and versatile peak decomposition
  with approachable defaults, advanced controls, and honest fit diagnostics.
- Support peak detection, integration, calibration, quantification, compound labels,
  and publication-quality exports. See PRODUCT.md for acceptance requirements.
- Keep the UI calm, consistent, accessible, and responsive. Do not expose algorithms
  as an unexplained list of technical names; explain controls and their effects.
- Never claim compound identity from retention time alone or treat an ambiguous
  decomposition as a confirmed chemical result.

## Boundaries and conventions
- Keep root run_app.py as a thin launcher. `python run_app.py` must work from the
  repository root after installation; it must not depend on the caller's directory.
- Source lives in src/chromakit. Separate domain, analysis, importers, application,
  UI, persistence, and export modules as they become necessary; avoid empty abstractions.
- Scientific and importer code must not import Qt. UI callbacks must not contain
  numerical algorithms. Pass typed requests/results through application services.
- Use NumPy arrays and explicit units; integrate against real time coordinates,
  including nonuniform sampling. Do not silently resample, sort, or drop observations.
- Use type hints, small cohesive modules, pathlib, explicit errors, and logging.
  Avoid global mutable state and broad catch-all exception handlers.
- Store algorithm versions, parameters, source hashes, units, seeds when relevant,
  and user overrides with derived results. Invalidate dependent results after edits.
- Run slow imports/analysis/export off the GUI thread. Only the GUI thread may
  mutate widgets. Support progress, cancellation, and rejecting stale worker results.
- Keep dependencies minimal and use maintained numerical libraries before custom
  solvers. Record mathematical assumptions and limitations of each method.

## Scientific correctness
- Never overwrite input files or raw arrays. Display raw, baseline, corrected,
  fitted components, and residuals distinctly. Display smoothing is not analytical
  preprocessing unless the user explicitly selects and records it.
- Distinguish measured integrated area from fitted component area, height from area,
  missing data from zero, and negative peaks from positive peaks.
- Fit only models supported by the selected data. Report convergence, residuals,
  constraints hit, and ambiguity. Covariance uncertainty is not reliable in every fit.
- Do not use R² alone to judge calibration. Keep replicate observations, weights,
  exclusions/reasons, range, residuals, and back-calculated concentrations visible.
- Test numerical changes against synthetic known truth and licensed representative
  fixtures, with explicit tolerances. Cover broad/overlapping peaks, drift, irregular
  sampling, negative signals, flat traces, NaNs, and missing/truncated inputs.

## Import and export contracts
- File extensions are hints, not proof of format. Sniff content, validate units,
  preserve metadata, and return actionable errors. Never execute imported content.
- Do not promise a vendor reader without exact format/version and fixture evidence.
  Add its capability/limitations to docs/FORMATS.md. Optional vendor SDKs need a
  portable fallback or explicit platform limitation.
- Image recovery requires explicit axis calibration and units, original-image
  provenance, editable tracing, visible gaps, and uncertainty/quality flags. Do not
  confuse recovered pixel coordinates with instrument sampling precision.
- Export PNG, TIFF, PDF, and SVG through a shared figure specification, independent
  of widget screenshots. Support dimensions, units, DPI where applicable, transparent
  or solid backgrounds, fonts, bounds, labels, and consistent preview.
- Save project files and exports safely, confirm overwrites in user-facing flows,
  and version the project schema with tested migrations when persistence is added.

## UI quality
Follow docs/UX.md. Centralize colors, spacing, typography, icons, and plot styling.
Use Qt layouts and model/view tables; support keyboard focus and high-DPI screens.
Empty, busy, error, and partial-success states are part of each feature. Undo/redo
must cover analytical edits and labels when those features are introduced.
Do not add fake functional controls, random demo results, or unlabelled sample data.
Do not start a Product Design workflow unless the task benefits from it or the user
requests it; preserve the PySide desktop target when using visual references.

## Workflow and verification
1. Inspect the relevant documents and implementation; state material assumptions.
2. Implement a small complete slice and keep documentation/status accurate.
3. Run `python -m compileall -q run_app.py src`, `ruff check .`, and the relevant
   tests. Use `pytest` once tests exist; do not invent tests for documentation edits.
4. For UI work, launch and visually inspect the affected states and interactions;
   use offscreen smoke checks as supplementary evidence, not visual verification.
5. Report changes, validation, and remaining limitations. Never claim a check ran
   when a dependency or GUI environment prevented it.

Do not commit confidential instrument files, credentials, private lab data, large
raw datasets, or generated figures. Use synthetic or explicitly permitted fixtures.
The user selected MIT for this public repository; preserve LICENSE and package
license metadata. Do not change that decision or claim regulatory compliance.
Before publication/release, follow docs/PUBLISHING.md and CONTRIBUTING.md.
