"""Run ChromaKit from a source checkout, independent of the current directory."""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
environment = ROOT / ".venv"
interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if (
    interpreter.is_file()
    and Path(sys.prefix).resolve() != environment.resolve()
    and any(
        importlib.util.find_spec(name) is None
        for name in ("PySide6", "numpy", "pyqtgraph", "scipy", "pybaselines")
    )
):
    os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(ROOT / "src"))

from chromakit.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
