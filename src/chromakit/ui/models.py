"""Virtualized, read-only tables; even large traces only render visible rows."""

from PySide6.QtCore import QAbstractTableModel, Qt

from chromakit.domain import Trace
from chromakit.importers.text import ParsedTable


class PreviewModel(QAbstractTableModel):
    def __init__(self, table: ParsedTable, parent=None):
        super().__init__(parent)
        self.table = table

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else min(50, len(self.table.rows))

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.table.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.table.rows[index.row()][index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.table.columns[section] or f"Column {section + 1}"
        return str(self.table.line_numbers[section])


class TraceModel(QAbstractTableModel):
    def __init__(self, trace: Trace, parent=None):
        super().__init__(parent)
        self.trace = trace
        self.baseline = None

    def set_baseline(self, result):
        if self.baseline is result:
            return
        self.beginResetModel()
        self.baseline = result
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.trace.time)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else 4 if self.baseline else 2

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.DisplayRole:
            arrays = [self.trace.source_time, self.trace.signal]
            if self.baseline is not None:
                arrays.extend([self.baseline.baseline, self.baseline.corrected])
            value = arrays[index.column()][index.row()]
            return f"{value:.10g}"
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        if section == 0:
            return f"Time ({self.trace.time_unit})"
        if section == 2:
            return f"Baseline ({self.trace.signal_unit})"
        if section == 3:
            return f"Corrected ({self.trace.signal_unit})"
        return f"{self.trace.channel} · {self.trace.signal_unit}"
