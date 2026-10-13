"""Resolve final export paths and confirm overwrites after suffix selection."""

import re
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox


def choose_output(parent, title, default, filters, allowed):
    filename, selected = QFileDialog.getSaveFileName(parent, title, default, filters)
    if not filename:
        return None
    path = Path(filename)
    original = path
    if not path.suffix:
        match = re.search(r"\*\.([a-z0-9]+)", selected or filters)
        path = path.with_suffix("." + match[1] if match else Path(default).suffix)
    if path.suffix.lower().lstrip(".") not in allowed:
        raise ValueError("Choose a supported file extension: " + ", ".join(allowed))
    if (
        path != original
        and path.exists()
        and QMessageBox.question(
            parent,
            "Replace output?",
            f"Replace {path.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        != QMessageBox.StandardButton.Yes
    ):
        return None
    return path
