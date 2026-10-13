"""Inspect public build contents without importing the application or dependencies."""

import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

EXCLUDED_PARTS = {
    ".venv",
    ".git",
    ".agents",
    ".codex",
    "data",
    "private",
    "outputs",
    "exports",
    "screenshots",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def inspect(directory: Path) -> None:
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one source archive.")
    with zipfile.ZipFile(wheels[0]) as wheel:
        wheel_names = wheel.namelist()
        metadata_path = next(name for name in wheel_names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(wheel.read(metadata_path))
        if metadata.get("License-Expression") != "MIT":
            raise ValueError("Wheel metadata must declare the MIT license expression.")
        if not any(name.endswith("/licenses/LICENSE") for name in wheel_names):
            raise ValueError("Wheel is missing its license text.")
        if "chromakit/app.py" not in wheel_names:
            raise ValueError("Wheel is missing the application entry point.")
    with tarfile.open(sources[0], "r:gz") as source:
        source_names = source.getnames()
        relative_names = {"/".join(PurePosixPath(name).parts[1:]) for name in source_names}
        required = {
            "LICENSE",
            "README.md",
            "pyproject.toml",
            "run_app.py",
            "CONTRIBUTING.md",
            "docs/DECONVOLUTION.md",
            "examples/synthetic_uv.csv",
            "examples/synthetic_overlaps.csv",
            "examples/synthetic_overlaps.truth.json",
            "tests/test_text_import.py",
            "scripts/check_distributions.py",
        }
        if missing := required - relative_names:
            raise ValueError(f"Source distribution is missing: {sorted(missing)}")
    for name in wheel_names + source_names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or EXCLUDED_PARTS.intersection(path.parts):
            raise ValueError(f"Unexpected private/generated path in a distribution: {name}")
        if path.name.startswith(".env") or path.suffix in {".pem", ".key", ".log", ".pyc"}:
            raise ValueError(f"Unexpected local file in a distribution: {name}")
    print(
        "Distribution checks passed: source, examples, entry point and MIT license; "
        "no excluded paths."
    )


if __name__ == "__main__":
    inspect(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist"))
