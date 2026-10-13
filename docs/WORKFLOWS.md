# Projects, exports, labels, images, calibration, batches and libraries

These workflows are implemented for local research use. The UI remains PySide6;
run from the root with `python3 run_app.py`. Native vendor formats and regulated
validation remain outside the current implementation.

## 1. Save and reopen a project

File → **New project**, **Save project** (Cmd/Ctrl+S), **Save project as**, and **Open project**
(Ctrl+Shift+O) manage `.chromakit` files. Save/discard/cancel protects unsaved work
before closing or replacing a session. A status-bar button cancels long project
operations. Invalid projects never replace the current session.

Projects embed sampled data, original digitization images, calibration/tracing
records, baseline drafts/applied results/history, peak results/history, fit drafts/
accepted results/history, compound annotations/history, library, calibrations,
quantifications, the last batch recipe and figure settings. Unapplied baseline/fit
preview curves and running jobs are not accepted results and are not persisted.
Saving is an atomic replacement; original instrument/text/image files are unchanged.
Source paths remain provenance metadata and need not exist to reopen a project.

The version-1 container is ZIP with a JSON manifest, numerical NPY arrays and image
assets. There is no pickle or executable object loading. Allowed record types,
field shapes, finite coordinates, units, checksums and feature metadata are checked
before installing the loaded session. Limits: 512 MiB uncompressed, 32 MiB manifest,
20,000 members and 1,000 traces. A version-1 Trace without the later stable `id`
field receives an ID on loading; other missing optional fields use schema defaults.
Unsupported required fields/versions are rejected. Checksums detect damaged assets;
they are not cryptographic signatures or a regulatory audit trail.

## 2. Export figures and results

File → **Export figure or results** opens a background-rendered preview. Choose
raw + applied baseline, corrected signal, or accepted current fit + residuals;
set width/height in mm, inches or pixels, DPI, font family/size, line width, title,
background, transparency and optional time bounds. Export PNG, TIFF, PDF or SVG.
PNG/TIFF preserve alpha when transparent. SVG text remains editable; PDF embeds
TrueType fonts. Vector page dimensions follow the same physical figure specification.
No widget screenshots or tight bounding-box cropping are used. Integer pixel sizes
are exact; mm/inch raster dimensions are quantized to whole pixels at the chosen DPI.

The Results tab exports sampled data, measured peaks or fitted components as CSV
or JSON. Units, origin and source/baseline identity are retained; JSON additionally
includes recipes and diagnostics. Stale measured/fitted results cannot be exported.
Sampled CSV includes `break_after`; external consumers must respect it rather than
interpolate missing intervals. Use project files for lossless application round trips.

Annotation placement/rotation appears in figures. Inspect the preview for very long
names, large fonts or small canvases; fully automatic collision avoidance is not
implemented. Limits: 80 million pixels, 20,000 pixels per side, DPI 36–1200.
Calibration figures/tables and concentrations are exported from their own dialog;
calibration figures reuse the project's physical size/background/DPI settings.

## 3. Assign compound labels

Apply a baseline and detect peaks or accept a fit, then open **Labels**. Choose a
measured peak/component, enter a multiline compound name and tentative/confirmed
status, and assign it. Select a label row to rename, rotate, remove or explicitly
rebind it to another reviewed peak. Drag labels on plots to position them. Label
undo/redo uses the Edit menu on the Labels tab; history is saved with the project.

Labels retain trace/result/peak identity separately from presentation coordinates.
A new analysis or changed applied baseline marks prior assignments stale and removes
those annotations from plots/exports until reviewed and rebound. Library-linked
assignments also become stale after their compound definition changes or is removed.
Confirmation is the user's decision; retention time alone never establishes identity.

## 4. Recover chromatograms from pictures

File → **Recover chromatogram from image** accepts PNG, JPEG and the first TIFF
page. EXIF orientation is applied; additional rotations are 0/90/180/270°. Crop the
plot in pixel coordinates, avoiding axes/legends. Enter two known values per axis
and pick their pixel positions with the x1/x2/y1/y2 buttons. Explicit time and signal
units are required before a trace can be created. Orientation changes reset calibration.

Pick a trace color, adjust tolerance and add optional rectangular exclusion masks;
**Trace selected color** follows matching pixels using continuity. Inspect the green
source overlay, edit/delete pixel points or add manual points by clicking. A changed
tracing recipe requires a new extraction; invalid point cells cannot silently reuse
older data. Missing columns create explicit breaks by default.

Use **Interpolate missing columns** to fill bounded interior gaps with linear
estimates on the image-column grid. **Maximum missing columns** limits which gaps
are bridged (default 25); longer gaps stay missing. There is no extrapolation before
the first or after the last recovered point. Increase the limit deliberately when
you need to bridge a wider occlusion; interpolated regions can affect peak areas.

Use **Replace isolated spikes** for large incorrect recovered values. A local median
and robust deviation threshold identify isolated runs of one or two outliers;
replacement uses the surrounding points without smoothing the entire curve. Adjust
the odd-sized neighborhood (default 11 columns), threshold (default 4; lower is
stronger) and minimum jump (default 6 image pixels). Separate gap segments, longer
outlier runs and unbracketed endpoints are left for manual review. Very narrow real
peaks may resemble spikes; compare with the source image before creating a trace.
Both repair options start off. The live pixel preview distinguishes original points,
the prepared trace, interpolated squares and replaced-spike crosses. These are
analytical repairs applied to the created data, not display-only smoothing.

Create the calibrated trace and process it with the ordinary baseline/peak/fit tools.
File → **Review/edit recovered image** reopens the embedded source/calibration even
when the original file is unavailable. Creating a refined trace preserves the original
trace and its analysis as a separate project entry.
The project embeds the exact original image, hash, calibration/crop/rotation/masks,
original recovered/edited points, prepared points, interpolation/spike-replacement
locations and settings, tracing method and per-pixel coordinate resolution. Reopening
restores the original path, so repairs can be disabled or adjusted without compounding
prior estimates. Older projects without repair settings retain their original behavior. Warnings
distinguish image recovery from instrument sampling. Images: up to 64 MiB compressed,
25 million pixels and 20,000 pixels on a side. Color tracing can follow the wrong line
at intersections or legends; masks/manual review are essential. There is no OCR,
perspective correction, arbitrary-angle deskew, logarithmic axis calibration or
simultaneous multi-trace recovery. Recover each trace separately.

## 5. External-standard calibration and concentrations

Analysis → **External-standard calibration** manages named compound calibrations.
Choose reviewed current measured/fitted signals as standards, enter known
concentrations/units, and use consistently defined area or height responses.
Replicate injections remain individual observations; one response per trace is
allowed in a compound calibration. Click a row to update its concentration/unit. Exclude/include standards with
an explicit reason; source identities and exclusions remain in the project/table.

Fit a linear model with unweighted, 1/x or 1/x² weighting and a fitted or zero
intercept. Weighted fits require positive concentrations; exclude zero blanks with
reasons or choose an unweighted fit. At least two distinct levels are required.
Responses/concentrations must use consistent explicit units; units are not silently
converted. Signed detector responses and slopes are supported.

Review the equation, R², response-unit RMSE, slope SE when degrees of freedom permit,
range, residual plot and back-calculated concentrations. With only two points and a
fitted intercept there are no residual degrees of freedom; perfect R² is not evidence
of validated calibration. Known-truth tests exercise weighted/unweighted fits,
zero intercept, exclusions, signs, units and extrapolation rules.

Select an unknown signal and quantify it with a positive dilution factor. Outside
range, concentration is withheld by default; explicit extrapolation is flagged.
Reprocessing/removing an included standard invalidates use of the calibration.
Concentration exports flag stale dependencies and withhold their concentrations.
Calibration state and response/source links survive reopening without refitting.
Internal standards, nonlinear models, certified uncertainty and LOD/LOQ are not
implemented. Calibration validity also requires scientific review of compound
assignments, baseline/fit choices and standards; R² alone is insufficient.

## 6. Process batches

Analysis → **Batch process text chromatograms** uses the active text trace's
reviewed parse/mapping/units, applied baseline recipe and peak recipe. Optionally
reuse an accepted fit's exact window, shapes and bounds. Choose CSV/TSV/TXT files
and run; results stream with individual warnings/errors. A failed fit can retain
successful baseline/peak processing as a partial outcome. Failed files do not
invalidate successful ones; cancellation keeps already displayed outcomes for review.

Check rows and **Add checked results to project**. No input file is overwritten.
Export the summary as CSV. The last recipe is retained in the project and can be rerun with **Use saved batch
recipe**. Matching mapped column names are required by default; turn off that check
only after reviewing compatible layouts/units. Limit: 2,000
files. Mapping/template units and manual anchor coordinates must be appropriate
for every file; the app does not guess detector metadata or injection roles.
Batch image recovery, recipe exchange as a standalone file, automatic sample-role/
standard concentration parsing and unattended folder monitoring remain future work.
Use the library review step to assign compounds across added traces, then calibration
for explicitly selected standard/unknown signals.

## 7. Maintain a compound library and review matches

Analysis → **Compound library and retention matching** provides name, aliases,
optional formula, expected retention start/end, known time unit and Any/UV/RID/PAD
rule. IDs stay stable when editing a compound. The library is embedded in projects
and can be imported/exported independently as UTF-8 CSV or version-1 JSON.
CSV columns: `id,name,start,end,time_unit,aliases,formula,detector`; `id` is generated
when absent and aliases use semicolons. Importing over an existing library requires
explicit replacement. Limit: 10,000 compounds. No online identification service is used.

**Review retention matches** lists current measured peaks and fitted components
across project traces. Matching converts explicit time units and honors detector
rules. Multiple candidates for one peak or multiple peaks in one compound window
are flagged ambiguous and unchecked. Choose candidates, review the checked rows,
and apply tentative labels. Duplicate current assignments are not added twice.
Confirm identities only after scientific review in Labels; matching never silently
confirms a compound. Window/formula/name changes flag linked assignments for review.

## Validation and release limits

Tests cover project round trips, corruption/version/type checks, cancellation and
history; export dimensions/transparency/vector page sizes; annotation/library staleness;
synthetic pixel recovery with occlusion and reversed axes; known calibration truth,
weights, exclusions and range; batch isolation/cancellation; and Qt interactions.
Native macOS dialogs and populated workflows are visually checked with synthetic
fixtures. Native Windows and representative permitted laboratory data still require
validation. The CI matrix is maintained, but new hosted checks require a later push.
