# Contributing to ChromaKit

ChromaKit is an early research desktop app. Changes should preserve source data,
make numerical assumptions inspectable, and keep the PySide workflow responsive.
Read [AGENTS.md](AGENTS.md), [the architecture](docs/ARCHITECTURE.md), and the guide
for the area you are changing before substantial implementation.

## Development setup

Use Python 3.11 or later and a virtual environment. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python run_app.py
```

On Windows PowerShell, create the environment with `py -3 -m venv .venv` and
activate with `.venv\Scripts\Activate.ps1`. If activation is unavailable, use
`.venv\Scripts\python.exe` directly for the commands above.

Run the checks before submitting a change:

```sh
python -m compileall -q run_app.py src
python -m ruff check .
```

Run the headless test suite on macOS/Linux:

```sh
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

On Windows PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
```

For UI changes also inspect the native app: offscreen tests cannot establish
visual quality. Describe which OS and workflow you checked. CI exercises Linux,
macOS and Windows, including Python 3.11 and 3.13; results are available on the repository Actions tab. Native UI verification is a
separate check.

## Scientific changes and fixtures

- Keep analysis/importer code independent of Qt. Use actual coordinates and units.
- Keep raw samples immutable. Record settings, source identity and manual overrides.
- Support cancellation and reject obsolete asynchronous results.
- Distinguish sampled integration from fitted component quantities. Report ambiguous
  decompositions, convergence and constraints instead of treating fits as identities.
- Test algorithms on deterministic known-truth synthetic examples with justified
  tolerances, including failures, polarity, irregular sampling, gaps and overlaps.
- Never include patient/sample identifiers, private instrument files, credentials,
  or lab screenshots in commits, issues, logs or CI artifacts. Use small synthetic
  reproductions or data you have explicit permission to publish, documenting its origin.
- Never promise vendor-format support without representative permitted fixtures.

## Issues and pull requests

Use the issue templates for bugs and proposed features. Include expected/actual
behavior, minimal reproduction, OS, Python and relevant library versions. For a
scientific issue include units, settings and an expected result with its definition.

Keep pull requests focused. Explain the problem, resulting behavior, validation,
and material limitations. Update usage/status documentation when scope changes.
Avoid unrelated generated files or dependency upgrades. Contributions to the
project are distributed under its [MIT license](LICENSE); dependencies retain
their own licenses. Report security concerns using [SECURITY.md](SECURITY.md).
