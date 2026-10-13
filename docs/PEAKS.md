# Peak detection and measured integration

Implemented for single chromatograms using the **applied** baseline-corrected
signal. Unapplied baseline previews never become measurement inputs. Raw arrays
and baseline results remain unchanged. Peak results are held in memory per session.

## Workflow
1. Import a trace, review its baseline, and click **Apply baseline**.
2. Open **Peaks**, select positive/negative/both directions, and click **Detect peaks**.
   Start with automatic noise-based prominence; explicit prominence is available.
3. Inspect retention time, signed corrected height, signed area, boundaries,
   polarity, and review flags in the table. Area units are signal × displayed time
   unit, e.g. mAU × min. Heights and areas are separate measured quantities.
4. Select a row or click an apex marker. Drag the shaded boundaries, double-click
   Start/End cells, or enter times and click **Update boundaries**. Edits trigger
   background reintegration. Invalid edits retain the previous measurements.
5. **Remove selected peak** removes a false detection. On the Peaks tab, Edit-menu
   Undo/Redo reverses detection, edits, and removal; other tabs retain baseline history.
6. Applying another baseline marks existing results **STALE**, disables editing,
   and removes the old plot overlay. Re-detect before using those measurements.
   Undoing the baseline change can restore the original result's exact dependency.

Settings are retained per trace. Changing them does not erase measurements; status
indicates that a detection run is needed to update them. Re-detection replaces
manual edits, with the previous result available through undo. P1, P2, etc. are
local labels within a detection result, not compound identities or reliable matches
across separate runs. Plot/table selection is synchronized.

Advanced settings include minimum height, half-prominence width, actual-time
minimum separation, and boundary fraction. Controls display the relevant time or
signal units and accept scientific notation. The Peaks view focuses on corrected
signal; Trace/Baseline tabs retain the raw+baseline comparison. Compact windows
use scrolling for the full table and inspector.

## Algorithms and definitions
Detection uses SciPy [local maxima and prominence](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)
on the signed corrected observations. No smoothing is applied to the measured
height or area. Negative peaks retain negative heights/areas; both-sign mode detects
both classes. Minimum height and prominence are independent filters.

Automatic prominence defaults to six times an estimated noise scale: the maximum
of a robust first-difference estimate and a median-filter residual estimate (up to
51 samples). The latter guards against correlated oscillations. Filtering is used
only to estimate noise. This is a heuristic; explicit prominence can be more useful
for unusual detector noise. Width means full width at **half prominence**, not
universally FWHM relative to zero. Fractional sample positions are mapped to actual
time coordinates. Separation preferentially retains stronger candidates.

Default boundaries are the nearest return below the larger of twice the noise
estimate or 0.5% of peak height, limited by adjacent peak partitions and sampled
segment bounds. Same-sign neighbors partition at a valley; opposite signs partition
near zero. Automatic intervals never overlap. Boundaries at a valley without reaching
the threshold or at a segment edge receive review flags.

Retention time and height refer to the detected sampled apex, not a fitted maximum.
Boundary edits retain that apex and require start < apex time < end. They cannot
cross an acquisition gap/excluded artifact or overlap another peak's interval.
Area is trapezoidal integration against actual time coordinates, with linear
interpolation at between-sample endpoints. There is no additional local sloped
baseline, clipping, absolute-area conversion, or rectangular approximation.

Baseline-protected peaks remain eligible. Baseline-excluded artifacts and detected
sampling gaps split the analysis into separate segments; areas never bridge them.
Endpoint maxima are not automatically counted by this local-maximum method;
incomplete acquisitions need review. Overlap areas are valley-split measured signals,
**not deconvolved component areas**, and can differ substantially from true component
quantities. Unknown units are identified as numerical coordinate integrals, with
no inferred concentration or physical calibration. A nonconverged applied baseline
is explicitly marked as requiring measurement review.

Metadata records settings, corrected-baseline fingerprint, source identity, values
and current bounds, manual-edit flags, units, timestamp, algorithm and SciPy versions.
Stale jobs are cancelled or rejected by generation and baseline identity. Global
prominence is evaluated in candidate chunks to permit cancellation without silently
imposing a local time window. Detection is limited to 2,000 accepted peaks per run;
increase prominence or separation when this limit is reached.

## Validation and remaining work
Synthetic tests cover Gaussian retention/height/area (area error <0.2% on the tested
well-sampled isolated fixtures), signed peaks, irregular times, exact between-sample
integration, overlap, actual-time filters, flat/correlated noise, gaps/artifacts,
edits, metadata, cancellation, history, and stale dependencies. Qt tests and native
macOS checks cover selection, table/plot editing, reintegration, invalid edits,
trace switching, scientific entry, and undo/redo.

Fitted deconvolution is implemented separately; see DECONVOLUTION.md.
Compound assignment, manual peak creation, concentration calibration, persistent projects, and table export remain future work. Native Windows
and representative lab data still need validation. Synthetic recovery criteria
are not universal experimental error guarantees.
