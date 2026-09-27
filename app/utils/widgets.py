"""ويدجت مشتركة تُستخدم في أكتر من شاشة."""
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPoint, QPropertyAnimation, QParallelAnimationGroup,
    QEasingCurve, Property, QEvent
)
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QLineEdit, QWidget
)

from app import i18n
from app.utils import palette as pal
from app.utils.branding import draw_mini_accent


def fmt_money(v):
    try:
        return f"{v:,.2f} {i18n.tr('common.currency_suffix')}"
    except Exception:
        return str(v)


class Card(QFrame):
    """كارت إحصائية - اللون بقى دلالي (variant) بدل hex حر: primary (تيل)
    للأرقام الإيجابية/الأساسية، info (أزرق) للأرقام المحايدة/المعلوماتية،
    negative (أحمر) للسلبي بس، warning (عنبر) للتحذير بس. لون الشريط العلوي
    بيتحدد من QSS (QFrame#Card[variant=...]) عشان يتغيّر تلقائي مع الثيم."""

    clicked = Signal()

    def __init__(self, title, value, variant="info", subtitle=""):
        super().__init__()
        self.setObjectName("Card")
        self.setProperty("variant", variant)
        self.setMinimumHeight(110)
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        layout.addWidget(self.title_label)

        self.value_label = QLabel(str(value))
        self.value_label.setObjectName("CardValue")
        layout.addWidget(self.value_label)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("CardTitle")
            layout.addWidget(sub)

        layout.addStretch()

    def set_value(self, value):
        self.value_label.setText(str(value))

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        margin = 10
        size = 22
        accent_rect = QRectF(margin, margin, size, size)
        draw_mini_accent(painter, accent_rect, opacity=0.16)
        painter.end()


def build_table(headers):
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.setAlternatingRowColors(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    return table


def fill_row(table, row_index, values):
    table.setRowCount(max(table.rowCount(), row_index + 1))
    for col, val in enumerate(values):
        item = QTableWidgetItem(str(val) if val is not None else "")
        item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row_index, col, item)


def confirm(parent, text, title=None):
    reply = QMessageBox.question(
        parent, title or i18n.tr("common.confirm_title"), text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    return reply == QMessageBox.Yes


def info(parent, text, title=None):
    QMessageBox.information(parent, title or i18n.tr("common.info_title"), text)


def warn(parent, text, title=None):
    QMessageBox.warning(parent, title or i18n.tr("common.error_title"), text)


def search_box(placeholder=None):
    box = QLineEdit()
    box.setPlaceholderText(placeholder or i18n.tr("common.search_placeholder"))
    return box


class _FloatingLabel(QLabel):
    """QLabel بخاصيتين قابلتين للأنيميشن (حجم الخط ولون النص) عشان
    FloatingLabelInput يقدر يعمل transition سلس بينهم بدل قفزة فجأة."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._font_size = 13.0
        self._color = QColor("#888888")
        self._apply_font()
        self._apply_color()

    def _apply_font(self):
        f = QFont(self.font())
        f.setPointSizeF(self._font_size)
        self.setFont(f)
        self.adjustSize()

    def _apply_color(self):
        self.setStyleSheet(f"color: {self._color.name()}; background: transparent;")

    def get_font_size(self):
        return self._font_size

    def set_font_size(self, value):
        self._font_size = value
        self._apply_font()

    fontSize = Property(float, get_font_size, set_font_size)

    def get_text_color(self):
        return self._color

    def set_text_color(self, color):
        self._color = QColor(color)
        self._apply_color()

    textColor = Property(QColor, get_text_color, set_text_color)


class FloatingLabelInput(QWidget):
    """حقل إدخال بلابل عائم بأسلوب Material - اللابل بيبدأ في نص الحقل
    الفاضي بحجم عادي ولون خافت (زي placeholder)، وأول ما تركّز على الحقل
    أو تكتب فيه، بيتحرك لفوق الحقل بأنيميشن سلس (حجم أصغر ولون accent)
    ويفضل ظاهر هناك حتى بعد ما تكتب (بعكس placeholder اللي بيختفي)."""

    TOP_MARGIN = 18
    FIELD_HEIGHT = 40
    RIGHT_MARGIN = 12
    ANIM_MS = 180

    def __init__(self, label_text, password=False, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.TOP_MARGIN + self.FIELD_HEIGHT)

        self.input = QLineEdit(self)
        self.input.setGeometry(0, self.TOP_MARGIN, self.width(), self.FIELD_HEIGHT)
        if password:
            self.input.setEchoMode(QLineEdit.Password)
        self.input.installEventFilter(self)
        self.input.textChanged.connect(self._refresh_state)

        self.label = _FloatingLabel(label_text, self)
        self._floated = False
        self._anim_group = None
        self._reposition(animate=False)

    def resizeEvent(self, event):
        self.input.setGeometry(0, self.TOP_MARGIN, self.width(), self.FIELD_HEIGHT)
        self._reposition(animate=False)
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self._refresh_state()
        return super().eventFilter(obj, event)

    def _refresh_state(self):
        should_float = self.input.hasFocus() or bool(self.input.text())
        if should_float != self._floated:
            self._floated = should_float
            self._reposition(animate=True)

    def _target_state(self):
        p = pal.current()
        if self._floated:
            return 9.5, QColor(p.ACCENT_TEAL)
        return 13.0, QColor(p.TEXT_MUTED)

    def _target_pos(self, font_size):
        f = QFont(self.label.font())
        f.setPointSizeF(font_size)
        metrics = QFontMetrics(f)
        width = metrics.horizontalAdvance(self.label.text()) + 2
        height = metrics.height()
        x = self.width() - width - self.RIGHT_MARGIN
        y = 0 if self._floated else self.TOP_MARGIN + (self.FIELD_HEIGHT - height) // 2
        return QPoint(max(x, 0), y)

    def _reposition(self, animate):
        font_size, color = self._target_state()
        pos = self._target_pos(font_size)

        if not animate:
            self.label.move(pos)
            self.label.set_font_size(font_size)
            self.label.set_text_color(color)
            return

        if self._anim_group is not None:
            self._anim_group.stop()

        group = QParallelAnimationGroup(self)
        pos_anim = QPropertyAnimation(self.label, b"pos", self)
        pos_anim.setDuration(self.ANIM_MS)
        pos_anim.setStartValue(self.label.pos())
        pos_anim.setEndValue(pos)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(pos_anim)

        size_anim = QPropertyAnimation(self.label, b"fontSize", self)
        size_anim.setDuration(self.ANIM_MS)
        size_anim.setStartValue(self.label.get_font_size())
        size_anim.setEndValue(font_size)
        size_anim.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(size_anim)

        color_anim = QPropertyAnimation(self.label, b"textColor", self)
        color_anim.setDuration(self.ANIM_MS)
        color_anim.setStartValue(self.label.get_text_color())
        color_anim.setEndValue(color)
        group.addAnimation(color_anim)

        self._anim_group = group
        group.start()

    def text(self):
        return self.input.text()

    def clear(self):
        self.input.clear()
