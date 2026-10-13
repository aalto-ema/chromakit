# UX and visual quality

## Experience goals
A precise, calm desktop workspace that makes scientific decisions visible. Favor
legible traces and predictable interactions over decorative dashboards. The user
has requested an aesthetic, highly consistent PySide UI; the starter window is not
a chosen visual design. Product Design can help explore a future visual direction.

## Proposed workspace
Resizable sample/channel navigator at left, dominant chromatogram plot in the
center, context-sensitive inspector at right, and collapsible peak/results table
below. Keep plot/table selections synchronized. Distinguish whole-trace processing
from the selected region. Preserve zoom when changing baseline/fit parameters.

Use a guided sequence for import, baseline, peaks, labels, and export without
forcing experts through a wizard every time. Show basic controls first; advanced
options disclose constraints, units, defaults, and scientific effects.

## Interaction requirements
- Immediate reversible preview followed by explicit Apply/Cancel for analytical
  changes. Applied changes enter undo history; stale derived results are marked.
- Baseline overlays and fit residuals visible on demand; warnings explain what
  happened and offer a concrete recovery action.
- Manual boundary/anchor/label editing supports keyboard alternatives and numeric
  entry. Dragging must remain precise at high zoom and on high-DPI displays.
- Image digitization uses a dedicated workspace with source/overlay comparison,
  magnifier, editable calibration anchors, clear axis units, and gap review.
- Import preview resolves uncertain mappings and units before analysis. Empty
  states explain the next available step; missing features do not masquerade as buttons.
- Long operations show useful progress, cancellation, and per-file failures.
- Export preview exposes actual dimensions and background; reusable presets reduce
  repeated formatting. Warn about content outside fixed figure bounds.

## Shared design system
Centralize semantic colors (surface/text/accent/warning/error), typography hierarchy,
spacing, control heights, icon sizes, plot palette, line weights, and focus styles.
Use system-compatible fonts, restrained accent color, and high contrast. Support
light mode first; design tokens should permit a later dark mode without changing
export backgrounds. Use color plus line/shape/text cues for analytical states.

Use Qt layouts rather than fixed positions. Preserve native macOS/Windows shortcuts,
menus, file dialogs, focus behavior, and high-DPI scaling. Persist workspace sizes
and user preferences separately from scientific project data.

## Quality gate for each UI slice
Inspect on macOS and Windows before claiming cross-platform readiness. Check
small windows, scaled displays, keyboard navigation, text clipping, long compound
names, empty/loading/error states, disabled explanations, undo/redo, and plot/table
synchronization. Use actual screenshots for visual reviews. Numerical correctness
and attractive screenshots are separate requirements.
