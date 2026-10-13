"""Desktop application bootstrap."""

import sys


def main() -> int:
    """Create the desktop workspace."""
    try:
        from PySide6.QtWidgets import QApplication

        from chromakit.ui.theme import apply_theme
        from chromakit.ui.window import MainWindow
    except ModuleNotFoundError as error:
        if error.name not in {"PySide6", "numpy", "pyqtgraph", "scipy", "pybaselines"}:
            raise
        print(
            "App dependencies are missing. Use .venv/bin/python run_app.py or install "
            "from the repository root with python -m pip install -e .",
            file=sys.stderr,
        )
        return 1

    application = QApplication(sys.argv)
    application.setApplicationName("ChromaKit")
    application.setApplicationVersion("0.1.0")
    apply_theme(application)
    window = MainWindow()
    window.show()
    return application.exec()
