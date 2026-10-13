"""Shared colors and widget styling for the first desktop workspace."""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "background": "#F4F6F7",
    "surface": "#FFFFFF",
    "text": "#23313B",
    "muted": "#697780",
    "border": "#E0E6E9",
    "accent": "#167D8D",
    "accent_soft": "#E8F4F4",
    "warning": "#805A24",
}


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont()
    font.setPointSizeF(10.5)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["background"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F8FAFB"))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#8D999F"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { color: #23313B; }
        QMainWindow, QDialog { background: #F4F6F7; }
        QFrame#header { background: white; border-bottom: 1px solid #E0E6E9; }
        QFrame#sidebar { background: #EFF3F4; border: 0; }
        QFrame#card { background: white; border: 1px solid #E0E6E9; border-radius: 10px; }
        QLabel { background: transparent; }
        QLabel#brand { font-size: 21px; font-weight: 650; letter-spacing: -0.5px; }
        QLabel#title { font-size: 25px; font-weight: 600; letter-spacing: -0.5px; }
        QLabel#section { font-size: 11px; color: #697780; font-weight: 600; }
        QLabel#muted { color: #697780; }
        QLabel#badge { background: #E8F4F4; color: #167D8D; border-radius: 5px;
                       padding: 5px 9px; font-size: 11px; font-weight: 600; }
        QLabel#warning { color: #805A24; background: #FFF5E4; padding: 10px;
                         border-radius: 6px; }
        QLabel#error { color: #A03238; background: #FDEEEF; padding: 10px;
                       border-radius: 6px; }
        QPushButton { background: white; border: 1px solid #D8E0E4; border-radius: 6px;
                      padding: 8px 14px; font-weight: 500; }
        QPushButton:hover { background: #F0F6F7; border-color: #A7BEC4; }
        QPushButton:pressed { background: #DFEDF0; }
        QPushButton:focus { border: 1px solid #167D8D; }
        QPushButton:disabled { color: #97A2A8; background: #F4F6F7; border-color: #E5EAEC; }
        QPushButton#primary { background: #167D8D; color: white; border-color: #167D8D; }
        QPushButton#primary:hover { background: #116B7A; }
        QPushButton#primary:disabled { background: #B8D3D8; border-color: #B8D3D8; }
        QPushButton#quiet { background: transparent; border: 0; color: #167D8D; }
        QPushButton:checked { background: #E8F4F4; color: #167D8D; border-color: #90BDC4; }
        QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #D8E0E4;
                                      border-radius: 5px; padding: 6px 8px; min-height: 20px; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #167D8D; }
        QComboBox::drop-down { border: 0; width: 22px; }
        QComboBox QAbstractItemView { background: white; selection-background-color: #E8F4F4;
                                    selection-color: #23313B; }
        QListWidget { background: transparent; border: 0; outline: 0; }
        QListWidget::item { padding: 12px 10px; border-radius: 6px; margin: 2px 0; }
        QListWidget::item:selected { background: #DFECEF; color: #145F6C; }
        QListWidget::item:hover { background: #E7EEF0; }
        QTableView { background: white; alternate-background-color: #F8FAFB;
                     border: 0; gridline-color: #EDF1F3; selection-background-color: #E8F4F4;
                     selection-color: #23313B; }
        QHeaderView::section { background: #F5F8F9; color: #697780; padding: 8px;
                               border: 0; border-bottom: 1px solid #E0E6E9; }
        QScrollArea { border: 0; background: transparent; }
        QScrollArea > QWidget > QWidget { background: transparent; }
        QScrollBar:vertical { width: 9px; background: transparent; margin: 0; }
        QScrollBar::handle:vertical { background: #CDD8DC; border-radius: 4px; min-height: 28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { height: 9px; background: transparent; }
        QScrollBar::handle:horizontal { background: #CDD8DC; border-radius: 4px; min-width: 28px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QSplitter::handle { background: transparent; }
        QStatusBar { background: white; color: #697780; border-top: 1px solid #E0E6E9; }
        QMenuBar { background: white; }
        QMenu { background: white; border: 1px solid #E0E6E9; padding: 5px; }
        QMenu::item { padding: 6px 24px; }
        QMenu::item:selected { background: #E8F4F4; }
        QToolTip { background: #23313B; color: white; border: 0; padding: 6px; }
    """)
