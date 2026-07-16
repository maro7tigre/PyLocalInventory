"""Application-wide visual theme shared by every supported desktop OS."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory


WINDOW = "#2b2b2b"
BASE = "#242424"
ALTERNATE = "#303030"
CONTROL = "#3c3c3c"
BORDER = "#555555"
TEXT = "#f2f2f2"
MUTED_TEXT = "#aaaaaa"
ACCENT = "#2196f3"


GLOBAL_DARK_STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    background-color: {WINDOW};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}

QMainWindow, QDialog, QMessageBox {{
    background-color: {WINDOW};
    color: {TEXT};
}}

QLabel {{
    color: {TEXT};
    background-color: transparent;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QDateEdit, QTimeEdit, QDateTimeEdit, QComboBox {{
    background-color: {BASE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 5px;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
QTimeEdit:focus, QDateTimeEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled,
QTimeEdit:disabled, QDateTimeEdit:disabled, QComboBox:disabled {{
    background-color: #202020;
    color: #777777;
}}

QComboBox::drop-down {{
    border: 0;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background-color: {BASE};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
    outline: 0;
}}

QAbstractItemView, QTableView, QTableWidget, QListView, QListWidget,
QTreeView, QTreeWidget {{
    background-color: {BASE};
    alternate-background-color: {ALTERNATE};
    color: {TEXT};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    outline: 0;
}}

QAbstractItemView::item:selected {{
    background-color: {ACCENT};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: #333333;
    color: {TEXT};
    border: 0;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 5px;
}}

QPushButton {{
    background-color: {CONTROL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 12px;
}}

QPushButton:hover {{ background-color: #4a4a4a; }}
QPushButton:pressed {{ background-color: #555555; }}
QPushButton:disabled {{ background-color: #242424; color: #777777; }}

QMenuBar {{
    background-color: {CONTROL};
    color: {TEXT};
}}

QMenuBar::item {{
    background-color: transparent;
    padding: 5px 9px;
}}

QMenuBar::item:selected, QMenuBar::item:pressed {{ background-color: #555555; }}

QMenu {{
    background-color: {CONTROL};
    color: {TEXT};
    border: 1px solid {BORDER};
}}

QMenu::item {{ padding: 6px 26px 6px 10px; }}
QMenu::item:selected {{ background-color: {ACCENT}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background-color: {BORDER}; margin: 4px 7px; }}

QTabWidget::pane {{
    background-color: {WINDOW};
    border: 1px solid {BORDER};
}}

QTabBar::tab {{
    background-color: {CONTROL};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 7px 13px;
}}

QTabBar::tab:selected {{ background-color: #555555; }}
QTabBar::tab:hover:!selected {{ background-color: #484848; }}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
}}

QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}

QScrollArea, QScrollArea::viewport, QScrollArea > QWidget > QWidget, QAbstractScrollArea::viewport {{
    background-color: {WINDOW};
}}

QScrollBar:vertical {{ background: {BASE}; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: {BASE}; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: #5a5a5a; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #707070; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QCheckBox, QRadioButton {{ color: {TEXT}; background-color: transparent; spacing: 6px; }}

QProgressBar {{
    background-color: {BASE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 3px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; }}

QToolTip {{
    background-color: {CONTROL};
    color: {TEXT};
    border: 1px solid #777777;
    padding: 4px;
}}
"""


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(WINDOW))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BASE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(ALTERNATE))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(CONTROL))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(CONTROL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED_TEXT))

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor("#777777"))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor("#777777"))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor("#777777"))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, QColor("#444444"))
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, QColor("#aaaaaa"))
    return palette


def apply_dark_theme(app: QApplication) -> None:
    """Force a deterministic dark appearance instead of an OS-native theme."""
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)

    app.setPalette(_dark_palette())
    app.setStyleSheet(GLOBAL_DARK_STYLESHEET)

    try:
        QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except (AttributeError, RuntimeError):
        # The explicit Fusion palette and stylesheet remain authoritative on
        # older Qt builds where the color-scheme hint is unavailable.
        pass
