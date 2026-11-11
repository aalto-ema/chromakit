"""Collect installed wheel notices and versioned upstream runtime license texts."""

import re
import shutil
import sys
from importlib import metadata
from pathlib import Path
from urllib.request import urlopen

from PySide6.QtCore import qVersion

ROOT = Path(__file__).resolve().parents[2]
RAW = "https://raw.githubusercontent.com"


def fetch_notice(url: str, path: Path) -> None:
    with urlopen(url, timeout=30) as response:
        data = response.read(1_000_001)
    if not data or len(data) > 1_000_000:
        raise ValueError(f"Unexpected license size from {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def collect(bundle: Path) -> None:
    shutil.copyfile(ROOT / "LICENSE", bundle / "LICENSE")
    notices = bundle / "ThirdParty"
    notices.mkdir(exist_ok=True)
    pyside, qt = metadata.version("PySide6"), qVersion()
    python = ".".join(str(part) for part in sys.version_info[:3])
    for name in ("GPL-3.0-only.txt", "LGPL-3.0-only.txt", "BSD-3-Clause.txt", "Apache-2.0.txt"):
        fetch_notice(
            f"{RAW}/pyside/pyside-setup/v{pyside}/LICENSES/{name}",
            notices / "Qt-and-PySide" / name,
        )
    fetch_notice(f"{RAW}/python/cpython/v{python}/LICENSE", notices / "Python" / "LICENSE.txt")

    index = [
        "ChromaKit is distributed under the MIT license in the installation directory.",
        "Bundled runtime components retain their own licenses.",
        "Qt and PySide6 are bundled as separate libraries under the LGPL v3 option.",
        f"Qt {qt} source: https://github.com/qt/qt5/tree/v{qt}",
        f"Qt {qt} notices: https://doc.qt.io/qt-{qt.rsplit('.', 1)[0]}/licenses-used-in-qt.html",
        f"PySide6 {pyside} source: https://github.com/pyside/pyside-setup/tree/v{pyside}",
        f"Python {python} source: https://github.com/python/cpython/tree/v{python}",
        "PyInstaller bootloader: https://pyinstaller.org/en/stable/license.html",
        "",
        "Build environment distributions (some are build tools, not bundled):",
    ]
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name.startswith("."):
            raise ValueError(f"Invalid distribution name: {name!r}")
        index.append(f"{name} {dist.version}: https://pypi.org/project/{name}/{dist.version}/")
        for entry in dist.files or ():
            if ".." in entry.parts or entry.is_absolute() or not entry.parts:
                continue
            if not entry.parts[0].endswith(".dist-info") or len(entry.parts) < 2:
                continue
            if not (
                entry.parts[1].lower() == "licenses"
                or entry.name.lower().startswith(("license", "copying", "notice", "copyright"))
            ):
                continue
            target = notices / name / Path(*entry.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dist.locate_file(entry), target)
    (notices / "README.txt").write_text("\n".join(index) + "\n", encoding="utf-8")


if __name__ == "__main__":
    collect(Path(sys.argv[1]).resolve())
