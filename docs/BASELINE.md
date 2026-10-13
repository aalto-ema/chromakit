# Whole-chromatogram baseline correction

Implemented for imported single traces. Baselines and corrected signals are
derived results; source arrays and files are unchanged. Applied results, drafts,
and undo/redo history are saved in portable projects. Applied baselines/corrected
samples and figures can be exported; see WORKFLOWS.md.

## Workflow
1. Import a chromatogram and click **Baseline…** or the **Baseline** inspector tab.
   The first estimate runs automatically in a background worker.
2. Start with **Adaptive spline · arPLS**. Choose the appropriate positive/negative
   peak direction. **Peak-preserving spline · AsLS** offers a complementary method.
3. Select a starting preset and adjust stiffness. Higher stiffness means fewer
   bends; lower values follow curved drift more closely. These are starting
   settings, not an automatic proof that the baseline is correct.
4. Inspect raw signal (gray) and baseline (amber dashed) in the upper plot; the
   corrected signal (teal) has a separate linked time axis below. Checkboxes toggle
   each layer. Parameter changes recalculate after a short debounce, preserving zoom.
5. Use **Refine** to add numeric anchors or enable **Click plot to add anchors**.
   Anchor heights are absolute baseline values in the displayed signal unit.
   Edit/remove table rows; click mode shows a crosshair on the raw plot.
6. Add protected peak or excluded artifact regions. Edit their start/end times or
   drag the shaded boundaries. Both types omit those observations from estimation,
   while leaving them in the raw and corrected data. Type is kept in the recipe.
7. Read **Review** for convergence, actual knot counts, warnings, units, method
   settings, source identity, algorithm version, and numerical-library versions.
   A result that did not converge is marked **needs review** before applying.
8. **Apply baseline** commits the current valid preview for that trace. **Discard**
   restores the applied recipe/result (or the initial settings). **Clear applied**
   returns to raw signal. Edit-menu Undo/Redo reverse applied/cleared baseline changes;
   preview-only edits are reverted with Discard.

**Stop preview** cancels queued work and cooperatively stops an active fit between
iterations. Change a control or click Baseline… again to recalculate. Switching
traces cancels stale requests and restores each trace's own draft/applied result.
The Data table adds baseline/corrected columns and explicitly indicates preview
versus applied data. Hover a sample readout for exact raw/baseline/corrected values.

## Methods and assumptions

The automatic methods use pybaselines' penalized cubic B-spline versions of
[arPLS](https://pybaselines.readthedocs.io/en/latest/generated/api/pybaselines.Baseline.pspline_arpls.html)
and [AsLS](https://pybaselines.readthedocs.io/en/latest/generated/api/pybaselines.Baseline.pspline_asls.html).
They fit the actual time coordinates, including nonuniform sampling. Coordinates
and signal amplitude are normalized for numerical conditioning; raw samples are
not resampled or smoothed. Negative-peak mode flips the estimation problem and
returns the baseline in the original signal sign/unit. No corrected values are clipped.

The default stiffness is λ = 1000, with up to 80 knots, 80 iterations, relative
tolerance 0.001, and AsLS peak weight 0.001. Short segments reduce the effective
knot count. Advanced controls expose knots, AsLS peak weight, iteration limit, and
tolerance. Sample density, peak width, and baseline shape affect suitable settings.

One library iteration per call supports cancellation. Tests compare this adapter
with uninterrupted library runs. The progress indicator counts iterations within
the current segment; it is not an ETA or a measure of scientific accuracy.

Protected/excluded samples are omitted from the fitting input. The fitted support
is interpolated to every original observation with shape-preserving PCHIP. Masked
segment edges extend constantly from the nearest fitting support, with a warning.
Large protected intervals can make the baseline poorly constrained; masking more
than half the observations is flagged. Automatic methods need at least four
unmasked observations in each contiguous segment.

Automatic anchors refine the estimated baseline by interpolating corrections
through the requested absolute heights, with zero correction at each segment edge
unless the user anchors that edge. To keep an edit local, place anchors matching
the existing baseline on either side of the intended adjustment. No hard clamp
forces the baseline below/above the raw data.

**Manual anchors · PCHIP** directly interpolates the specified heights, independently
of peak polarity. It needs at least two anchors per contiguous sampled segment (one
for a single-observation segment). Values outside the outer anchors extend constantly
with a warning. Masks are not used by this wholly manual definition, which is disclosed.
For mixed positive/negative peaks, use manual anchors or protect both kinds of peaks;
automatic mixed-polarity identification is not implemented.

All importer-detected sampling gaps are processed independently, and plotted
disconnected. Anchors inside gaps are rejected. There is no invented baseline or
interpolation across an acquisition gap. Gap detection remains the importer's
five-times-median-interval heuristic; it cannot identify every gap.

## Validation and limits

Synthetic tests cover curved drift, overlapping/narrow/broad peaks, irregular
sampling, negative peaks, tiny signal scales, affine/flat signals, independently
offset gap segments, protected artifacts, local refinements, and edge extensions.
For the documented curved-drift fixture, default arPLS has <0.03 mAU baseline RMS
error; default AsLS has <0.15 mAU RMS error and <0.5 mAU maximum-peak-height error.
Both meet <1% total peak-area error on that fixture. These thresholds are synthetic
acceptance criteria, not guarantees for experimental chromatograms.

Tests also check raw-array preservation, metadata serialization, stale-result
rejection, cancellation, history, switching traces, plot-based/manual editing, and
zoom preservation. Native macOS UI checks cover live preview, refinement, applying,
history, and compact layouts. Real lab examples and native Windows validation are
still needed; broad peaks with no visible baseline support are inherently ambiguous.
