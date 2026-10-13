# ChromaKit

[Repository](https://github.com/aalto-ema/chromakit) ·
[Issues](https://github.com/aalto-ema/chromakit/issues) ·
[CI](https://github.com/aalto-ema/chromakit/actions/workflows/ci.yml)

A PySide6 desktop workspace for importing, inspecting, and baseline-correcting
chromatograms, with automatic peak detection, measured integration and constrained
overlapping-peak deconvolution. Annotation, calibration, and figure exports are planned.

**Current status:** a styled workspace with CSV/TSV/TXT import preview, explicit
column/unit mapping, interactive plotting, sample inspection, and data tables.
Whole-trace baseline correction includes arPLS/AsLS spline methods, presets, manual
anchors, protected/excluded regions, live raw/baseline/corrected plots, and undo/redo.
Peak detection uses the applied corrected signal, with editable integration bounds
and retention-time/height/area tables, review flags, and per-trace history.
Several files can be held in a session; one trace is displayed at a time. Project
saving, vendor-native import, image digitization, and export are not yet implemented.
Deconvolution includes Gaussian and tailed models, editable bounds/locks, live component
and residual plots, fitted areas/diagnostics, count comparisons, and accepted history.

## Start

Use **Python 3.11 or later**. macOS and Windows are the target desktop platforms.
This is an early research app: analysis is session-only, so closing the app discards
imported traces and processing results. Project saving is not implemented yet.

From a source checkout, create an environment and install the app on macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python run_app.py
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe run_app.py
```

After installation, `chromakit` is also available inside the environment. The root
launcher works independently of the caller's directory and can use the checkout's
`.venv` when the calling interpreter lacks required dependencies. No native vendor
SDKs or instrument connections are needed for the implemented text workflow.

For contributor/test tools, install `python -m pip install -e ".[dev]"`; see
[CONTRIBUTING.md](CONTRIBUTING.md) for development and validation instructions.

## Import and inspect

1. Click **Import chromatogram…**, use Cmd+O on macOS/Ctrl+O on Windows, or drop
   one local file into the workspace.
2. Review the first 50 rows. Adjust delimiter, encoding, decimal separator,
   header handling, or leading lines to skip, then click **Update preview**.
3. Select the time and signal columns, confirm their units, and optionally set
   the sample name and detector. Unit suggestions always need review.
4. Click **Import & plot**. Scroll to zoom, drag to pan, use **Zoom box** for a
   rectangular selection, and **Fit trace** to restore the full view.
5. Hover to inspect the nearest observation. **Data** shows a read-only table;
   clicking a row highlights that sample. Use the navigator to switch traces.

Try [examples/synthetic_uv.csv](examples/synthetic_uv.csv), which contains explicitly
synthetic data. Select UV as detector; the headers suggest minutes and mAU.

The importer supports comma, tab, semicolon, pipe, and whitespace separators;
period/comma decimals; UTF-8 (including BOM), UTF-16 BOM, and explicitly selected
Windows-1252/Latin-1. Quote multi-word column names for whitespace-separated data.
Blank lines and `#` comments are disclosed and ignored. Skip other report metadata
explicitly. Thousands separators, automatic metadata interpretation, and native
vendor containers are not supported. Limits are 64 MiB and 1,000,000 rows per file.

Invalid selected values, nonfinite samples, ragged rows, and duplicate/reversed
times produce actionable errors; they are never silently removed or reordered.
For incomplete digitized traces, explicitly select **Missing signal → Omit with gaps**
to omit blank/NaN/NA/N/A signal entries while preserving internal breaks. Omitted
source lines are recorded; times, infinity and malformed numbers still fail validation.
A leading commented time-column header is recognized in Auto mode, including
underscore names such as `time_min_assumed`. Review assumed coordinate calibration.
Unknown units allow inspection. Possible gaps exceeding five times the median
interval are flagged and drawn disconnected; this is a heuristic, not a detector
of all acquisition gaps. Original coordinates and signals remain read-only.
Plot downsampling for dense continuous traces affects display only.

Imports run in cancellable background tasks. Imported data is held in memory
for the session; source files are never overwritten. Reimport files after closing.

## Correct a baseline

After importing, click **Baseline…**. Review the automatic estimate, choose positive
or negative peaks, and adjust a preset/stiffness. **Refine** provides numeric or
plot-based anchors and draggable protected/excluded regions. **Review** shows
diagnostics; **Apply baseline**, **Discard**, and Edit-menu Undo/Redo keep changes
reversible. Source data stays intact. See [the baseline guide](docs/BASELINE.md)
for method assumptions, local refinement, edge behavior, and validation evidence.

## Detect and integrate peaks

Apply a baseline, open **Peaks**, and click **Detect peaks**. Select a row or marker;
drag boundaries, edit Start/End cells, or use **Update boundaries**. Heights and
areas retain their sign, with units shown in the table. Applying another baseline
marks these results stale. See [the peak guide](docs/PEAKS.md) for definitions and rules.

## Fit overlapping peaks

Apply a reviewed baseline, open **Fit peaks**, frame the group, choose a component
count and starting shape, and click **Initialize components**. Edit guesses, bounds
and locks in **Parameters & bounds**; inspect live fits and residuals, then review
**Fitted areas** and diagnostics before accepting. Compare alternative counts with
**Compare 2–5 components**. See [the deconvolution guide](docs/DECONVOLUTION.md)
for model definitions, workflow, limits and uncertainty. A synthetic overlap example
and its truth parameters are in `examples/synthetic_overlaps.csv` and its JSON companion.

## Project guide

- [AGENTS.md](AGENTS.md): instructions for coding agents and contributors.
- [Product requirements](docs/PRODUCT.md): scientific features and acceptance criteria.
- [Architecture](docs/ARCHITECTURE.md): module boundaries and data contracts.
- [Baseline correction](docs/BASELINE.md): methods, refinement, diagnostics, and usage.
- [Deconvolution](docs/DECONVOLUTION.md): fitting, constraints, residuals and ambiguity.
- [Peak detection and integration](docs/PEAKS.md): measured areas, bounds, and provenance.
- [UX guidance](docs/UX.md): interaction and visual consistency requirements.
- [Format matrix](docs/FORMATS.md): importer priorities and evidence requirements.
- [Roadmap](docs/ROADMAP.md): incremental implementation and validation.
- [Decisions](docs/DECISIONS.md): assumptions and questions requiring user input.
- [Contributing](CONTRIBUTING.md): development, tests and scientific contribution rules.
- [Changelog](CHANGELOG.md): development changes and release scope.
- [Public publishing checklist](docs/PUBLISHING.md): repository and distribution preparation.

SciPy and pybaselines are installed as core dependencies for baseline correction.
The optional `analysis` extra currently adds Matplotlib for future figure exports.

```sh
python -m compileall -q run_app.py src
ruff check .
QT_QPA_PLATFORM=offscreen pytest -q
```

On Windows, set `QT_QPA_PLATFORM=offscreen` in your shell before running `pytest -q`.
Tests cover import formats/encodings, units, missing-signal gaps, numerical baseline
recovery, signed integration, Gaussian/EMG overlap fits, ambiguity/constraints,
async cancellation, history and Qt interactions. Native macOS workflows have been
checked. CI is configured for Linux, macOS and Windows; see the linked workflow for current
hosted results. Native Windows UI and real vendor-format validation remain open.

## License and reporting

ChromaKit source and included synthetic examples use the [MIT license](LICENSE).
Third-party dependencies retain their own licenses. Report bugs/features through
GitHub's issue templates after publication; use [SECURITY.md](SECURITY.md) for
security concerns. Share only synthetic or explicitly publishable data.
