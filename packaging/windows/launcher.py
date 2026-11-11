"""Frozen GUI entry point with an explicit, non-interactive installer smoke mode."""

import sys
import traceback
from pathlib import Path

from chromakit.app import main


def smoke() -> None:
    from PySide6.QtWidgets import QApplication

    from chromakit.analysis.baseline import BaselineRecipe, estimate_baseline
    from chromakit.analysis.peaks import PeakRecipe, detect_peaks
    from chromakit.export.figures import FigureSpec, figure_bytes
    from chromakit.importers.text import (
        ParseOptions,
        build_trace,
        load_source,
        parse_source,
        suggest_mapping,
    )
    from chromakit.ui.theme import apply_theme
    from chromakit.ui.window import MainWindow

    application = QApplication(["ChromaKit"])
    apply_theme(application)
    window = MainWindow()
    try:
        sample = Path(sys._MEIPASS) / "examples" / "synthetic_uv.csv"
        table = parse_source(load_source(sample), ParseOptions())
        trace = build_trace(table, suggest_mapping(table))
        window.add_trace(trace)
        window.show()
        application.processEvents()
        if not window.isVisible() or window.trace is not trace:
            raise RuntimeError("The workspace did not display the bundled synthetic trace.")
        baseline = estimate_baseline(trace, BaselineRecipe())
        if not detect_peaks(trace, baseline, PeakRecipe()).peaks:
            raise RuntimeError("Peak detection did not find a peak in the synthetic trace.")
        png = figure_bytes(trace, baseline, None, [], FigureSpec(dpi=72))
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("PNG export failed in the installed application.")
    finally:
        window.saved_signature = window.project_signature()
        window.close()
        application.processEvents()


def launch() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--installer-smoke-test":
        return main()
    report = Path(sys.argv[2])
    try:
        smoke()
    except Exception:
        # Windowed builds have no console; capture any diagnostic for the CI runner.
        report.write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    report.write_text("PASS\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(launch())
