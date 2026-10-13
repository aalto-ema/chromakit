# Product requirements

## Confirmed scope
Research desktop app for macOS and Windows, using PySide6. Start with single HPLC
chromatograms from Thermo Scientific and Agilent, with RID (refractive index), UV,
and PAD (pulsed amperometric) detectors. Add batch processing and calibration after
the single-trace workflow. Native file variants remain to be identified.

Primary journey: import → inspect → correct baseline → detect/integrate or fit
peaks → assign labels → review → save/export. Generic text import and interactive
trace inspection, baseline correction, peak detection/integration and constrained
peak deconvolution are implemented. Image recovery, calibration, labeling, persistence,
and export requirements below remain planned.

## Import and trace inspection
- Read common delimited text (CSV, TSV, TXT) with a preview for headers, delimiter,
  decimal separator, encoding, time/signal columns, channels, and units.
- Add validated vendor exchange formats and native adapters using docs/FORMATS.md.
  A table of peak results is not a sampled chromatogram; distinguish these inputs.
- Preserve sample/injection identity, detector/channel, method, timestamps, units,
  acquisition metadata where available, and source provenance. Unknown remains unknown.
- Support zoom, pan, time-region selection, raw-data inspection, multiple channels,
  overlays, and clear sign/unit handling for RID, UV, and PAD traces.
- Detect nonfinite values, duplicate/nonmonotonic times, gaps, saturation, and
  truncated acquisitions. Offer explicit repair choices; record transformations.

## Recover chromatograms from images
Pictures from old instruments are a first-class input route, alongside sampled
data. Accept PNG/JPEG/TIFF initially; decide PDF page import separately.
- Guided workflow: select plot region → orient/deskew → calibrate axes → select
  trace → preview extraction → correct points/gaps → confirm units → create trace.
- Calibrate both axes from at least two known coordinates per axis. Require the
  user to enter tick values and units; never infer quantitative scale from appearance.
  Support reversed axes and offsets; linear axes first, logarithmic axes later.
- Allow assisted color/contrast tracing and manual point/segment tracing for
  monochrome scans. Show the recovered path over the original image at full resolution.
- Let users mask grid lines, labels, legends, and artifacts; split intersecting
  traces manually; mark missing or occluded sections. Never silently bridge gaps.
- Keep original image, crop/coordinate transforms, calibration anchors, extraction
  settings, manually edited points, and method version. Preview calibration error
  and estimate resolution-related coordinate uncertainty where defensible.
- Retain `image_digitized` provenance through analysis, projects, and result exports.
  Flag clipped peaks, trace thickness, compression, low resolution, and perspective
  distortion as measurement limitations. Higher interpolation density adds no new
  information; do not present recovered data as native sampling precision.
- Export recovered time/signal data as CSV with metadata. Allow ordinary analysis
  of recovered traces with visible provenance and uncertainty caveats.

Acceptance: recover known curves from synthetic rendered plots, compare time,
height, and integrated area to truth across resolution/noise/rotation, and verify
saved calibration reproduces the same points. Uncalibrated images cannot yield
quantitative peak area or concentration. OCR may suggest ticks; the user confirms them.

## Whole-chromatogram baseline correction
Implemented first slice: arPLS/AsLS penalized splines, presets/advanced controls,
signed-peak selection, PCHIP manual anchors and automatic anchor refinement,
protected/excluded regions, live linked plots, diagnostics, applied history, and
source/recipe provenance. See BASELINE.md for usage, validation, and limitations.

- Offer a small set of understandable presets backed by validated methods, such
  as asymmetric penalized smoothing and robust anchor/spline baselines. Evaluate
  pybaselines before writing custom methods; no universal automatic method is assumed.
- Handle global drift, curved baselines, dense/broad peaks, local artifacts, and
  both signal polarities. Include protected peak regions, excluded artifacts,
  manual anchors, and local refinement with continuous region boundaries.
- Show raw trace, baseline, corrected trace, and the effect of parameter changes.
  Applying changes is reversible; preserve the full recipe and diagnostics.
- Quantify area/height recovery on known synthetic baselines and representative
  traces, especially broad peaks that an aggressive baseline can remove.

## Peak detection, integration, and decomposition
Detection/integration is implemented with signed maxima, noise/prominence and
actual-time filters, editable bounds, quantitative tables, flags, history, and
baseline dependency checks. See PEAKS.md. Gaussian/EMG component fitting includes
editable bounds/locks, live residuals, fitted
areas, count comparison and ambiguity diagnostics. See DECONVOLUTION.md. Manual peak
creation and shared fit parameters remain planned.

- Guided automatic detection with sensitivity, prominence/noise, width, polarity,
  and region controls; editable start/end boundaries and split/merge actions.
- Report retention time, height, baseline-corrected integrated area, width,
  signal-to-noise definition, and quality flags. Use actual time coordinates.
- Fit overlapping peaks using a constrained model selected for observed shapes:
  Gaussian first, then asymmetric/exponentially modified Gaussian where justified.
  Allow component addition/removal, bounds, shared parameters, and locked centers.
- Explain controls in plain language; provide a guided mode and an advanced mode.
  Preview components, their sum, residuals, and integrated versus fitted areas.
- Report fit failure, instability, active bounds, sensitivity to starting values,
  and possible nonunique decompositions. Do not force every shoulder into a peak.
- Evaluate component-count selection; model preference alone cannot establish
  chemical identity. Multi-channel evidence is a later extension.

## Quantification and automatic calibration (later phase)
- First provide peak height/area tables; concentrations require valid calibration.
- Build calibration sets from explicitly designated standards, known concentrations,
  units, compound assignments, replicates, and concentration levels. Do not guess
  which chromatograms are standards or infer concentrations from filenames alone.
- Match compound peaks using editable retention windows and approved assignments.
  Preview missing/ambiguous matches before constructing plots.
- Start with linear external-standard calibration. Add weighted fitting (including
  defined handling of zero concentrations), internal-standard response ratios,
  dilution/sample preparation factors, and suitable nonlinear models later.
- Show equations, weights, fit range, residuals, back-calculated standards,
  replicate variation, exclusions with reasons, and out-of-range predictions.
- Keep calibration versions linked to quantified results. Never silently extrapolate.
  LOD/LOQ estimates need a named method, assumptions, and validation evidence.

## Powerful compound labels
- Compound library with stable IDs, display names, aliases, optional formulas,
  expected retention windows, detector-specific rules, and reusable templates.
- Assign labels manually or from matching rules, with confirmed/tentative states.
  Reprocessing must flag changed peak matches instead of silently moving identities.
- Support multi-line labels, superscripts/subscripts where supported, leaders,
  rotation, relative offsets, collision avoidance, groups, bulk edits, and undo/redo.
- Separate chemical assignment from presentation placement. Store label anchors in
  trace/peak coordinates; keep placement usable on resized exported figures.

## Figure and data export
- Required figure formats: PNG, TIFF, PDF, SVG. Support transparent or selected
  solid backgrounds, exact width/height in mm/inches or pixels, raster DPI,
  editable vector output where feasible, and explicit fonts/colors/line weights.
- Include trace overlays, baseline/components/residuals, labels, legends, axis
  limits/units, and saved journal/layout presets. Export without transient UI selection.
- Preview the same figure specification used for saving. Keep dimensions exact;
  automatic tight cropping must not silently change requested physical dimensions.
- Validate transparency, raster dimensions, vector page size, Unicode labels,
  clipping, and TIFF readability. Transparency capabilities of PDF viewers differ.
- Export result tables and recipes with units and provenance, plus digitized data.

## Additional valuable features
Prioritize project save/reopen, reproducible processing recipes, undo/redo,
comparison overlays, and quality flags alongside the single-trace workflow.
Then add batch recipes with per-file failures, retention-time alignment with an
explicit transform, internal standards, blank subtraction, carryover checks,
replicate statistics, suitability metrics (resolution/tailing/plates with named
definitions), and reusable report templates. Never alter quantitative data merely
to improve an overlay's visual alignment.

Later candidates: PDA/DAD spectral matrices and purity exploration, headless
processing, folder monitoring, method comparison, and detector-specific libraries.
GC/MS, molecular identification, instrument control, cloud collaboration, and
regulated certification are outside the first release.
