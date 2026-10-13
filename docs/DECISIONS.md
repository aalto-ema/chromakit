# Decisions and open questions

Updated 2026-10-13. Record confirmed answers here so future coding sessions do not
repeatedly ask the same questions.

## Confirmed by the user
- Product: chromatogram analysis with powerful whole-trace baseline correction,
  versatile approachable peak decomposition, area/height quantification, automatic
  calibration plots, and powerful compound labeling.
- Initial analytical scope: HPLC; RID, UV, and PAD detectors. PAD explicitly means
  **pulsed amperometric detection**, not photodiode-array/PDA/DAD.
- Initial vendors: Thermo Scientific and Agilent. File extensions are not yet known.
- Platforms: macOS and Windows. Research analysis of lab data.
- Sequence: single chromatograms first, then batch and calibration.
- UI: PySide, with strong aesthetic consistency and pleasant UX.
- Figure export: PNG, TIFF, PDF, SVG; optional transparency and specific dimensions.
- Root launch entry point: run_app.py.
- Include chromatogram recovery from pictures for old instruments.
- Public repository license: MIT, explicitly selected by the user.
- Product Design may be used when useful; no particular visual direction was chosen.

## Provisional implementation defaults
- Working name ChromaKit (from repository name); Python 3.11+, PySide6/Qt Widgets.
- Local-first storage, immutable raw data, explicit processing provenance.
- First imports: sampled delimited text; vendor exchange formats before unverified
  native support. Images require calibrated recovery and distinct provenance.
- Linear image axes first, manual and assisted curve tracing; logarithmic axes later.
- Candidate stack: NumPy/SciPy/pybaselines for analysis, Matplotlib for export;
  interactive plotting and image-processing libraries need evaluation.
- Light UI first with shared theme tokens; no finished UI has been specified.
- Research reproducibility, without claims of regulated validation or certification.

## First implementation choices
- pyqtgraph for interactive inspection; a shared PySide widget stylesheet for the
  light workspace. Scientific code has no Qt dependency.
- A local .venv contains app and test dependencies; root launcher supports it.
- Text reader v1 uses explicit review of mapping/units/locale, strict validation,
  and immutable source-coordinate/signal arrays plus normalized known-time arrays.
- One selected channel per imported trace; multiple traces may be switched within
  the session. Projects are not persisted yet, which the workspace states visibly.
- Display-only peak downsampling for dense continuous traces; possible gaps use
  explicit disconnected edges without downsampling.

## Baseline implementation choices
- Use pybaselines' arPLS/AsLS penalized cubic splines on real time coordinates;
  no raw-signal resampling/smoothing. Default AsLS peak weight is 0.001.
- Fit each importer-detected gap segment independently. Omit protected peaks and
  excluded artifacts from estimation, then PCHIP-interpolate inside masked support.
  Constant outer extension is explicitly flagged.
- Manual absolute anchors use PCHIP. Automatic anchor refinements interpolate
  corrections with zero correction at unanchored segment edges. Mixed-polarity
  automatic identification is deferred; manual/masked workflows support such traces.
- Linked raw+baseline and corrected plots distinguish preview from applied results.
  Use a debounced, cooperatively cancellable single worker with generation checks.
- Applied baselines have per-trace undo/redo and versioned recipe/provenance metadata;
  persistent project storage remains a later implementation task.

## Peak implementation choices
- Detect and integrate the applied corrected signal only. Fingerprint its recipe
  and corrected array; retain old results as explicitly stale after baseline changes.
- Use signed local maxima/prominence with robust noise estimates. Widths/separation
  use actual display-time coordinates, including irregular sampling.
- Integrate piecewise linear observations with interpolated endpoints. Report
  signed area in signal × display-time units, without an additional local baseline.
- Use valley partitions for overlap and flags for incomplete tails/edges. Fitted
  deconvolution is now implemented separately; compound identification remains planned.
- Boundary edits retain the sampled apex and cannot cross gaps, artifacts, or
  neighboring integration intervals. Detection/edit/removal history is per trace;
  Edit-menu shortcuts use peak history when the Peaks tab is active.

## Questions to resolve when implementation needs them
1. Which CDS/acquisition software and versions are used for Thermo/Agilent? Obtain
   representative permitted native and exported files when designing those adapters.
2. Typical time ranges, point counts, noise/drift, sign, units, and difficult peak
   shapes? What area error is acceptable for the research workflow?
3. What are the old-instrument pictures like: scans, screenshots, camera photos,
   grids, monochrome/multiple traces, skew, scale bars, or logarithmic axes?
4. Desired visual references, theme preferences, and figure/journal presets?
5. Compound libraries, retention-window rules, and existing naming conventions?
6. Calibration practice: concentration units, levels/replicates, external/internal
   standards, weights, dilution corrections, and QC criteria?
7. Embed raw data/images in portable projects or reference originals? Expected
   storage sizes and confidentiality requirements?
8. Supported macOS/Windows versions and CPU architectures, distribution method,
   and dependency redistribution considerations?

These questions do not block the foundation. Resolve only the ones needed for the
next implementation slice, and promote confirmed answers into this document.

## Constrained deconvolution implementation
- Fit applied corrected observations with signed normalized Gaussian and left/right
  EMG kernels, bounded TRF least squares, optional soft-L1 loss, deterministic
  multistart guesses, and explicit parameter locks. Shared constraints remain later work.
- Separate signed full-model area from area inside the fit window and sampled
  integration. Keep preview versus accepted state and exact baseline dependencies.
- Compare fresh 2–5-component alternatives with RMSE/AICc/BIC under stated assumptions;
  never accept a count automatically. Show conditioning, correlations, constraints,
  starting sensitivity and conditional covariance limitations. See DECONVOLUTION.md.
