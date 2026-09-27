"""ستايل عام للتطبيق (QSS) - ثيم Cortex غامق وفاتح، بنفس الـ selectors
بالظبط عشان أي ودجت تشتغل صح تحت الاتنين من غير أي كود إضافي. الألوان
كلها بترجع لـ app.utils.palette (المصدر الوحيد) - محدش يكتب hex هنا مباشرة."""
from app.utils.palette import Cortex, CortexLight

FONT_STACK = "'IBM Plex Sans Arabic', 'Segoe UI', 'Tahoma', sans-serif"


def _build_qss(p):
    return f"""
* {{ font-family: {FONT_STACK}; font-size: 14px; }}

QWidget {{ background-color: {p.BG_PRIMARY}; color: {p.TEXT_PRIMARY}; }}

QMainWindow, QDialog {{ background-color: {p.BG_PRIMARY}; }}

#Sidebar {{ background-color: {p.BG_SURFACE}; border-left: 1px solid {p.BORDER}; }}

#SidebarButton {{
    text-align: right;
    padding: 12px 16px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: {p.TEXT_MUTED};
    font-size: 15px;
}}
#SidebarButton:hover {{ background-color: {p.BG_SURFACE_ALT}; }}
#SidebarButton:checked {{
    background-color: {p.BG_SURFACE_ALT};
    border-left: 3px solid {p.ACCENT_TEAL};
    color: {p.ACCENT_TEAL};
    font-weight: bold;
}}

#ShopTitle {{ font-size: 20px; font-weight: 700; color: {p.TEXT_PRIMARY}; padding: 12px 16px 2px 16px; }}

QPushButton {{
    background-color: {p.ACCENT_BLUE};
    color: {p.TEXT_PRIMARY};
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
}}
QPushButton:hover {{ background-color: {p.ACCENT_TEAL}; color: {p.BG_PRIMARY}; }}
QPushButton:disabled {{ background-color: {p.BG_SURFACE_ALT}; color: {p.TEXT_MUTED}; }}

QPushButton#DangerButton {{ background-color: {p.RED}; color: {p.TEXT_PRIMARY}; }}
QPushButton#DangerButton:hover {{ border: 1px solid {p.TEXT_PRIMARY}; }}

QPushButton#SecondaryButton {{ background-color: {p.BG_SURFACE_ALT}; color: {p.TEXT_PRIMARY}; }}
QPushButton#SecondaryButton:hover {{ border: 1px solid {p.ACCENT_TEAL}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTextEdit {{
    background-color: {p.BG_SURFACE};
    border: 1px solid {p.BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    color: {p.TEXT_PRIMARY};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p.ACCENT_TEAL}; }}

QTableWidget {{
    background-color: {p.BG_PRIMARY};
    alternate-background-color: {p.BG_SURFACE};
    gridline-color: {p.BORDER};
    border: 1px solid {p.BORDER};
    border-radius: 6px;
}}
QHeaderView::section {{
    background-color: {p.BG_SURFACE};
    color: {p.TEXT_MUTED};
    padding: 8px;
    border: none;
    border-bottom: 2px solid {p.ACCENT_TEAL};
    font-weight: bold;
}}
QTableWidget::item:selected {{ background-color: {p.ACCENT_BLUE}; color: {p.TEXT_PRIMARY}; }}

QLabel#CardTitle {{ color: {p.TEXT_MUTED}; font-size: 13px; }}
QLabel#CardValue {{ color: {p.TEXT_PRIMARY}; font-size: 26px; font-weight: bold; }}

QFrame#Card {{
    background-color: {p.BG_SURFACE};
    border-radius: 12px;
    border: 1px solid {p.BORDER};
    border-top: 3px solid {p.ACCENT_BLUE};
}}
QFrame#Card:hover {{ border-color: {p.ACCENT_TEAL}; border-top-color: {p.ACCENT_TEAL}; }}
QFrame#Card[variant="primary"] {{ border-top: 3px solid {p.ACCENT_TEAL}; }}
QFrame#Card[variant="info"] {{ border-top: 3px solid {p.ACCENT_BLUE}; }}
QFrame#Card[variant="negative"] {{ border-top: 3px solid {p.RED}; }}
QFrame#Card[variant="warning"] {{ border-top: 3px solid {p.AMBER}; }}

QTabWidget::pane {{ border: 1px solid {p.BORDER}; border-radius: 6px; }}
QTabBar::tab {{
    background: {p.BG_SURFACE}; color: {p.TEXT_MUTED}; padding: 8px 16px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{ background: {p.BG_SURFACE_ALT}; color: {p.ACCENT_TEAL}; }}

QScrollBar:vertical {{ background: {p.BG_PRIMARY}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p.BG_SURFACE_ALT}; border-radius: 5px; }}
"""


DARK_QSS = _build_qss(Cortex)
LIGHT_QSS = _build_qss(CortexLight)

# توافقية مع أي كود قديم بيستورد APP_QSS مباشرة.
APP_QSS = DARK_QSS


def get_stylesheet(theme):
    return LIGHT_QSS if theme == "light" else DARK_QSS
