# ChromaKit

[Repository](https://github.com/aalto-ema/chromakit) ·
[Issues](https://github.com/aalto-ema/chromakit/issues) ·
[CI](https://github.com/aalto-ema/chromakit/actions/workflows/ci.yml)

A PySide6 research desktop workspace for chromatogram analysis, with baseline
correction, measured integration, overlapping-peak fits, portable projects, figure
exports, image recovery, compound labels/libraries, calibration and batch processing.

**Current status:** CSV/TSV/TXT import and inspection, whole-trace baseline correction,
measured integration, constrained peak fits, portable project save/reopen, figure/result
export, editable compound labels, calibrated image recovery, external-standard
calibration, reviewed batch processing and a retention-window compound library.
Native vendor-file readers remain planned. Native macOS workflows are checked;
native Windows and representative laboratory validation remain outstanding.

## Start

Use **Python 3.11 or later**. macOS and Windows are the target desktop platforms.
This is an early research app. Save a `.chromakit` project to preserve imported
data, processing, labels, images, calibration and library records between sessions.

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

Imports run in cancellable background tasks; source files are never overwritten.
Use File → Save project to embed data and results for reopening.

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

## Projects and the expanded workflow

- **File → Save/Open project**: portable projects with embedded traces and images.
- **File → Export figure or results**: PNG/TIFF/PDF/SVG, exact sizes, transparency,
  font settings, and provenance-bearing CSV/JSON tables.
- **Labels** tab: compound names, review states, rotation, draggable placement and history.
- **File → Recover chromatogram from image**: calibrated axes, color/manual tracing,
  masks, editable points and explicit missing intervals.
- **Analysis → External-standard calibration**: linear fits, weighting/intercept options,
  residuals, reviewed standards, ranged concentrations and dilution factors.
- **Analysis → Batch process text chromatograms**: reusable mappings/analysis settings,
  per-file outcomes, cancellation and reviewed addition to a project.
- **Analysis → Compound library and retention matching**: editable windows, aliases,
  detector rules, CSV/JSON libraries and manually reviewed tentative assignments.

Read [the workflow guide](docs/WORKFLOWS.md) for detailed instructions, format limits
and remaining extensions. Image/calibration/matching results require review;
retention matches alone do not establish chemical identity.

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
Matplotlib and Pillow are core dependencies for figure export and image recovery.
The `analysis` extra is retained for compatibility with earlier installs.

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
