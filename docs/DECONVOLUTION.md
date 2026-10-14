# Overlapping-peak deconvolution

Implemented for single, applied baseline-corrected traces. Fitted components are
mathematical models; counts, areas and retention times do not establish chemical
identity. Results and accepted history can be saved in portable projects.

## Workflow
1. Import sampled data and **apply** a reviewed baseline. For broad overlapping
   humps, protect the whole group or use manual anchors outside it so the baseline
   does not absorb broad components.
2. Open **Fit peaks**. Drag the window edges or enter its start/end in displayed
   time units. Frame one continuous group with some baseline on both sides.
3. Choose 1–8 components and a starting shape: **Right tail** is a useful first
   choice for the broad shoulders and tailing illustrated in the supplied images;
   **Gaussian** suits symmetric peaks; **Left tail** handles leading asymmetry.
   Choose negative starting peaks when appropriate. Click **Initialize components**.
   Changing the count or starting shape takes effect on the next initialization.
4. In **Parameters & bounds**, double-click values/lower/upper limits and tick
   **Lock** for known parameters. Shape is editable per component: use `Gaussian`,
   `Right tail`, or `Left tail`. `center` is the Gaussian location μ, which differs
   from the apex of a tailed peak; `sigma` is Gaussian width and `tau` tail time.
   These all use displayed time units; area uses signal × displayed time.
   Selecting a row highlights the component. Initialization replaces existing guesses.
5. Guesses update the component sum and data-minus-model residual immediately.
   **Refit automatically after edits** debounces a new worker fit; disable it to
   edit several constraints before clicking **Fit components**. Provisional curves
   stream during optimization. **Use fitted values as guesses** starts refinement
   from the last solution while retaining bounds and locks. Cancellation or invalid
   edits preserve the accepted result; cancelled curves cannot become a result.
6. Review **Fitted areas** and inspector diagnostics. Full area integrates the
   signed model across its entire distribution; **Window area** integrates only
   the selected interval, including between-sample endpoints through the model CDF.
   The fitted apex and height refer to the continuous model, not sampled maxima.
   Extrapolated full areas, constraints and unstable fits receive review flags.
7. **Compare 2–5 components** fits fresh automatic guesses for each count in the
   same window and starting shape, using the selected loss and number of attempts.
   Custom component bounds/locks are not reused. Click a count row to inspect its
   preview; there is no automatic chemical count selection or acceptance.
8. Click **Accept fit** after review. **Restore accepted fit** discards the draft;
   Edit-menu Undo/Redo on Fit peaks reverses accepted fits. Baseline changes make
   old fits stale and remove overlays/tables until refitted. Restoring the exact
   applied baseline restores its fit dependency. Each trace has independent drafts
   and accepted history. Peak integration remains a separate measured result.

The supplied pictures informed the shape requirements; they were not digitized or
used as quantitative input. Try `examples/synthetic_overlaps.csv`, an explicitly
synthetic three-component overlap with a broad shoulder, central tailed peak and
small late bump. The red/blue signal columns provide two shapes; its companion truth JSON describes
all model parameters. Recovering
observations from pictures requires the calibrated digitization flow in WORKFLOWS.md.

## Numerical model and diagnostics

Pure scientific code lives in `analysis/deconvolution.py`; `application/deconvolution.py`
tracks accepted history and the applied-baseline fingerprint. Qt workers use the
single-worker generation scheduler; newer edits/trace changes cancel obsolete work
and reject obsolete provisional/final results. Fitting never edits or silently
resamples observations. Windows spanning an acquisition gap or excluded artifact
are rejected. At least 12 observations and more observations than free parameters
plus two are required; windows are limited to 20,000 observations, 8 components,
and 8 deterministic starting attempts. Narrow the region for larger acquisitions.

Each Gaussian or exponentially modified Gaussian (EMG) kernel has unit integral;
the area parameter multiplies that kernel and retains its sign. EMG uses SciPy
`exponnorm` with K = tau/sigma; reflecting coordinates gives a left tail. Gaussian
models omit tau from optimization. Centers, widths, tails and areas may vary
independently within finite bounds or be locked. Width/tail bounds must stay
strictly positive; area bounds stay in one direction. There is no additional
hidden baseline, area clipping, local interpolation or smoothing in the fit.

SciPy bounded `least_squares` (TRF) fits equally weighted observations at their
actual coordinates. Internal coordinate/area scales improve conditioning without
changing observations or the objective. Irregular sampling is supported, but dense
regions contribute more observations and therefore more weight. `soft_l1` is an
optional robust objective using a recorded deterministic first-difference noise
scale rule; ordinary least squares is the default. A seeded multistart search
perturbs guesses within bounds; the lowest objective wins. This explores some
local solutions and does not guarantee a global or unique decomposition.

Diagnostics include convergence/message, total solver evaluations, free parameter
count, RMSE in signal units, R², scaled Jacobian condition and bound flags. R² alone
is insufficient. AICc/BIC use the same-data, independent constant-variance Gaussian
residual likelihood (including estimated variance in parameter count), with omitted
constants. Lower values suggest a statistical preference under those assumptions;
correlated detector noise, inappropriate shapes and baseline errors can invalidate
that preference. Criteria are unavailable for robust loss. Compare only fits to
identical observations and loss assumptions.

Local linear covariance area SE is available only for converged ordinary least
squares with an adequately conditioned Jacobian and no active constraints. Locked
areas have no estimated SE. Correlation >0.98, condition >10⁶, and materially different
areas in comparably good starts trigger warnings. SE excludes baseline, model/count
choice, pixel recovery and other systematic uncertainty. Full areas outside the
window are particularly model dependent. Failing to flag a fit does not prove
identifiability. Components can change ordering between runs; C1 etc. are local
component labels, not persistent compound assignments.

Metadata records source hash, corrected-baseline fingerprint, units, original
guesses/bounds/locks/model/loss/window, final parameters, multistart seed/settings,
values, objective cost/noise scale, diagnostics, timestamp and algorithm/library versions. Projects and figure/table export are implemented; see WORKFLOWS.md. Shared parameter
constraints, instrument-specific validation and bootstrap/profile-likelihood
uncertainties remain future work.

## Validation

Known-truth tests cover three overlapping Gaussian/EMG components and a broad four-component group, both tail
orientations, signed signals and irregular coordinates, with fitted areas within
0.01% on the tested noiseless fixtures. A fresh automatic initialization recovers
the tested broad shoulder/central peak/late bump total area within 2%. These are
synthetic fixture checks, not experimental accuracy claims. Additional tests cover
locks, robust diagnostics, rank-deficient duplicate components, truncated windows,
bounds, nonconvergence, active constraints, gaps/artifacts, flat data, cancellation,
immutable arrays, metadata,
accepted history, stale baselines, streamed plots, parameter edits, count comparisons
and trace switching. Native macOS rendering/workflow is checked; native Windows
and permitted real lab examples remain unverified.

Primary mathematical references: [SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html)
and [SciPy exponentially modified normal](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.exponnorm.html).

## Repeated-start stability
After accepting a current fit, use **Analyze fit stability…** for repeated-start
sensitivity, component-area ranges, per-attempt curves/residuals and saved/exportable
reports. Matching respects shape/bound/lock constraints, and flags near-coincident
components. This supplements covariance and count comparisons; it is not a confidence
interval or identity test. See WORKFLOWS.md for criteria and limits.
