import math
import calendar
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QRectF, QPointF, QDate, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QLinearGradient, QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QFrame, QToolTip,
    QComboBox, QPushButton, QSizePolicy, QScrollArea, QDateEdit
)

from app import database as db
from app import i18n
from app.utils import palette as pal
from app.utils.widgets import build_table, fill_row, fmt_money

ALL_TIME_START = "0001-01-01"
ALL_TIME_END = "9999-12-31"

# تدرّج تيل→أزرق متعدد الدرجات لتوزيع المبيعات حسب الفئة (رسم فئوي محتاج
# ألوان متمايزة لتوزيع منطقي - مش "كارت" بيتلوّن عشوائي زي الممنوع في الهوية).
PALETTE = ["#4FD8C4", "#4C6FFF", "#7FE8D9", "#8AA3FF", "#2FA394", "#2E4FCC", "#B4EFE4", "#B8C6FF"]


def _month_bounds(offset=0):
    """يرجع (بداية الشهر, بداية الشهر اللي بعده) كنصوص ISO، مع إزاحة
    `offset` شهر للخلف (0 = الشهر الحالي، 1 = اللي فات، إلخ)."""
    today = date.today()
    idx = today.year * 12 + (today.month - 1) - offset
    y, m = divmod(idx, 12)
    m += 1
    start = f"{y:04d}-{m:02d}-01"
    end = f"{y + 1:04d}-01-01" if m == 12 else f"{y:04d}-{m + 1:02d}-01"
    return start, end


def _pct_change(cur, prev):
    if not prev:
        return None
    return (cur - prev) / prev * 100.0


def _make_icon_pixmap(emoji, size, bg_color):
    """بيرسم شارة الأيقونة (دائرة ملوّنة + إيموجي) على صورة بحجم ثابت.
    خطوط الإيموجي الملوّنة في ويندوز أحيانًا بترسم أكبر بكتير من حجم
    الخط المطلوب وبتطلع برّه حدود الـ QLabel - رسمها على QPixmap بحجم
    ثابت بيضمن إنها متتقصش برّه الدائرة أبدًا."""
    ratio = 2  # نرسم بدقة أعلى (retina-style) عشان تبقى واضحة مش مبكسلة
    pm = QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(bg_color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)
    font = QFont("Segoe UI Emoji")  # خط الإيموجي الملوّنة بتاع ويندوز - خط
    # الواجهة العادي (Segoe UI) مالوش رموز إيموجي ملوّنة فبيطلعها مشوّهة
    font.setPixelSize(int(size * 0.5))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, emoji)
    painter.end()
    return pm


def _short_num(v):
    v = abs(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}m"
    if v >= 1_000:
        return f"{v / 1_000:.1f}k"
    return f"{v:.0f}"


class _RevealMixin:
    """ميكسين مشترك بين كل الرسومات - بيدي تأثير حركي (زي Power BI) لما
    البيانات تتغيّر: الرسم بيتكشف تدريجيًا من صفر لحد القيمة الكاملة
    بدل ما يظهر فجأة، بس بضبط progress 0..1 ويعيد الرسم كل فريم."""

    def _init_reveal(self):
        self._progress = 1.0
        self._reveal_anim = QVariantAnimation(self)
        self._reveal_anim.setDuration(500)
        self._reveal_anim.setStartValue(0.0)
        self._reveal_anim.setEndValue(1.0)
        self._reveal_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._reveal_anim.valueChanged.connect(self._on_reveal_progress)

    def _on_reveal_progress(self, v):
        self._progress = v
        self.update()

    def _replay_reveal(self):
        self._reveal_anim.stop()
        self._progress = 0.0
        self._reveal_anim.start()


class LineAreaChart(_RevealMixin, QWidget):
    """رسم بياني خطي (منطقة متدرجة تحت خط المبيعات اليومية) مرسوم يدويًا
    بـ QPainter. بيدعم Tooltip عند تمرير الماوس، وبيتحرك (يتكشف من الشمال
    لليمين) كل ما البيانات تتغيّر."""

    def __init__(self, values, day_labels, target=None, color=None, parent=None):
        super().__init__(parent)
        self.values = values
        self.day_labels = day_labels
        self.target = target
        self.color = QColor(color or pal.current().ACCENT_TEAL)
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self._points = []
        self._init_reveal()

    def set_values(self, values, day_labels, target=None):
        self.values = values
        self.day_labels = day_labels
        self.target = target
        self._replay_reveal()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        margin_left, margin_right, margin_top, margin_bottom = 46, 16, 14, 28
        plot = QRectF(
            margin_left, margin_top,
            max(rect.width() - margin_left - margin_right, 10),
            max(rect.height() - margin_top - margin_bottom, 10),
        )

        n = len(self.values)
        if n < 2:
            self._points = []
            painter.setPen(QColor(pal.current().TEXT_MUTED))
            painter.drawText(rect, Qt.AlignCenter, i18n.tr("reports.no_data_yet"))
            return

        max_v = max(self.values + ([self.target] if self.target else []) + [1]) * 1.15

        grid_pen = QPen(QColor(pal.current().BG_SURFACE_ALT), 1)
        label_pen = QPen(QColor(pal.current().TEXT_MUTED))
        steps = 4
        for i in range(steps + 1):
            y = plot.bottom() - plot.height() * i / steps
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(label_pen)
            painter.drawText(QRectF(0, y - 8, margin_left - 8, 16), Qt.AlignRight | Qt.AlignVCenter,
                              _short_num(max_v * i / steps))

        def point_for(i, v):
            x = plot.left() + plot.width() * i / (n - 1)
            y = plot.bottom() - (v / max_v) * plot.height() if max_v else plot.bottom()
            return QPointF(x, y)

        points = [point_for(i, v) for i, v in enumerate(self.values)]
        self._points = points

        # تأثير الحركة: نقص الرسم على قد ما البروجرس وصل، بحيث الخط يتكشف
        # تدريجيًا من الشمال لليمين بدل ما يظهر فجأة.
        painter.save()
        clip_w = plot.width() * self._progress
        painter.setClipRect(QRectF(plot.left(), plot.top() - 4, clip_w + 1, plot.height() + 8))

        area_path = QPainterPath()
        area_path.moveTo(points[0].x(), plot.bottom())
        for p in points:
            area_path.lineTo(p)
        area_path.lineTo(points[-1].x(), plot.bottom())
        area_path.closeSubpath()

        gradient = QLinearGradient(0, plot.top(), 0, plot.bottom())
        top_color = QColor(self.color)
        top_color.setAlpha(140)
        bottom_color = QColor(self.color)
        bottom_color.setAlpha(8)
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bottom_color)
        painter.fillPath(area_path, QBrush(gradient))

        line_path = QPainterPath()
        line_path.moveTo(points[0])
        for p in points[1:]:
            line_path.lineTo(p)
        painter.setPen(QPen(self.color, 2))
        painter.drawPath(line_path)
        painter.restore()

        if self.target:
            y = plot.bottom() - (self.target / max_v) * plot.height()
            pen = QPen(QColor(pal.current().AMBER), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        painter.setPen(label_pen)
        step = max(1, n // 6)
        for i in range(0, n, step):
            x = points[i].x()
            painter.drawText(QRectF(x - 20, plot.bottom() + 6, 40, 18), Qt.AlignCenter, self.day_labels[i])
        if (n - 1) % step != 0:
            x = points[-1].x()
            painter.drawText(QRectF(x - 20, plot.bottom() + 6, 40, 18), Qt.AlignCenter, self.day_labels[-1])

    def mouseMoveEvent(self, event):
        if not self._points:
            return
        pos = event.position() if hasattr(event, "position") else event.pos()
        x = pos.x()
        nearest_i = min(range(len(self._points)), key=lambda i: abs(self._points[i].x() - x))
        if abs(self._points[nearest_i].x() - x) <= 18:
            global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            QToolTip.showText(global_pos, f"{self.day_labels[nearest_i]}: {fmt_money(self.values[nearest_i])}", self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class BarChart(_RevealMixin, QWidget):
    """رسم بياني بالأعمدة مرسوم يدويًا بـ QPainter. بيدعم Tooltip عند
    المرور، وSignal لما يتم الضغط على عمود (للفلترة)، وحركة نمو للأعمدة
    كل ما البيانات تتغيّر."""

    bar_clicked = Signal(str)

    def __init__(self, labels, values, color=None, parent=None):
        super().__init__(parent)
        self.labels = labels
        self.values = values
        self.color = QColor(color or pal.current().ACCENT_TEAL)
        self.setMinimumHeight(280)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._bar_rects = []
        self._hover_index = -1
        self._init_reveal()

    def set_values(self, labels, values):
        self.labels = labels
        self.values = values
        self._replay_reveal()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        if not self.values:
            self._bar_rects = []
            painter.setPen(QColor(pal.current().TEXT_MUTED))
            painter.drawText(rect, Qt.AlignCenter, i18n.tr("reports.no_data_yet"))
            return

        margin_left, margin_right, margin_top, margin_bottom = 46, 16, 14, 30
        plot = QRectF(
            margin_left, margin_top,
            max(rect.width() - margin_left - margin_right, 10),
            max(rect.height() - margin_top - margin_bottom, 10),
        )

        max_v = max(self.values) * 1.2 or 1
        grid_pen = QPen(QColor(pal.current().BG_SURFACE_ALT), 1)
        label_pen = QPen(QColor(pal.current().TEXT_MUTED))
        steps = 4
        for i in range(steps + 1):
            y = plot.bottom() - plot.height() * i / steps
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(label_pen)
            painter.drawText(QRectF(0, y - 8, margin_left - 8, 16), Qt.AlignRight | Qt.AlignVCenter,
                              _short_num(max_v * i / steps))

        n = len(self.values)
        slot_w = plot.width() / n
        bar_w = min(slot_w * 0.5, 56)
        painter.setPen(Qt.NoPen)
        self._bar_rects = []
        for i, (label, v) in enumerate(zip(self.labels, self.values)):
            cx = plot.left() + slot_w * i + slot_w / 2
            h = (v / max_v) * plot.height() * self._progress if max_v else 0
            bar_rect = QRectF(cx - bar_w / 2, plot.bottom() - h, bar_w, h)
            hit_rect = QRectF(cx - slot_w / 2, plot.top(), slot_w, plot.height())
            self._bar_rects.append((hit_rect, label, v))
            color = QColor(self.color)
            if i == self._hover_index:
                color = color.lighter(125)
            painter.setBrush(color)
            painter.drawRoundedRect(bar_rect, 4, 4)

            painter.setPen(label_pen)
            painter.drawText(QRectF(cx - slot_w / 2, plot.bottom() + 6, slot_w, 18), Qt.AlignCenter, label)
            painter.setPen(Qt.NoPen)

    def _bar_at(self, pos):
        for i, (hit_rect, label, v) in enumerate(self._bar_rects):
            if hit_rect.contains(pos):
                return i, label, v
        return -1, None, None

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        i, label, v = self._bar_at(pos)
        if i != self._hover_index:
            self._hover_index = i
            self.update()
        if label is not None:
            global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            QToolTip.showText(global_pos, f"{label}: {fmt_money(v)}", self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        _, label, v = self._bar_at(pos)
        if label is not None:
            self.bar_clicked.emit(label)

    def leaveEvent(self, event):
        if self._hover_index != -1:
            self._hover_index = -1
            self.update()
        QToolTip.hideText()
        super().leaveEvent(event)


class DonutChart(_RevealMixin, QWidget):
    """رسم بياني دائري (Donut) لتوزيع المبيعات حسب فئة المنتج - بيتحرك
    (يتكشف بالدوران) لما البيانات تتغيّر، وبتقدر تدوس على أي قطاع
    عشان تفلتر بيه (زي عمود الموظفين بالظبط)."""

    segment_clicked = Signal(str)

    def __init__(self, labels, values, parent=None):
        super().__init__(parent)
        self.labels = labels
        self.values = values
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._segments = []
        self._hover_index = -1
        self._center = QPointF(0, 0)
        self._inner_r = 0
        self._outer_r = 0
        self._init_reveal()

    def set_values(self, labels, values):
        self.labels = labels
        self.values = values
        self._replay_reveal()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        total = sum(self.values) if self.values else 0
        self._segments = []

        if not self.values or total <= 0:
            painter.setPen(QColor(pal.current().TEXT_MUTED))
            painter.drawText(rect, Qt.AlignCenter, i18n.tr("reports.no_data_yet"))
            return

        margin = 10
        show_legend = len(self.labels) >= 1
        legend_w = min(150, rect.width() * 0.36) if show_legend else 0
        donut_area_w = max(rect.width() - legend_w - margin * 2, 10)
        donut_size = min(donut_area_w, rect.height() - margin * 2)
        donut_size = max(donut_size, 50)
        cx = margin + donut_area_w / 2
        cy = rect.height() / 2
        thickness = max(16, donut_size * 0.32)
        outer_r = donut_size / 2
        inner_r = outer_r - thickness
        self._center = QPointF(cx, cy)
        self._outer_r = outer_r
        self._inner_r = inner_r

        donut_rect = QRectF(cx - outer_r + thickness / 2, cy - outer_r + thickness / 2,
                             donut_size - thickness, donut_size - thickness)

        revealed_deg = 360.0 * self._progress
        cum = 0.0
        for i, (label, v) in enumerate(zip(self.labels, self.values)):
            frac_deg = (v / total) * 360.0
            seg_start = cum
            seg_end = cum + frac_deg
            visible_end = min(seg_end, revealed_deg)
            visible_deg = max(0.0, visible_end - seg_start)
            color = QColor(PALETTE[i % len(PALETTE)])
            if i == self._hover_index:
                color = color.lighter(125)
            if visible_deg > 359.9:
                # قطاع واحد بياخد الدائرة كلها (100%) - drawArc بيسيب خط
                # رفيع فاصل عند نقطة البداية/النهاية بسبب شكل نهاية الخط
                # (Cap)، فبنرسم حلقة كاملة بدل القوس عشان تبقى متصلة تمامًا.
                pen = QPen(color, thickness)
                painter.setPen(pen)
                painter.drawEllipse(donut_rect)
            elif visible_deg > 0.01:
                pen = QPen(color, thickness)
                pen.setCapStyle(Qt.FlatCap)
                painter.setPen(pen)
                a_start = int((90 - seg_start) * 16)
                a_span = int(-visible_deg * 16)
                painter.drawArc(donut_rect, a_start, a_span)
            self._segments.append((seg_start, seg_end, label, v, color))
            cum = seg_end

        painter.setPen(QColor(pal.current().TEXT_MUTED))
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(
            QRectF(cx - outer_r, cy - 10, outer_r * 2, 20), Qt.AlignCenter, i18n.tr("reports.donut_total_label")
        )
        bold_font = QFont(font)
        bold_font.setBold(True)
        bold_font.setPointSize(11)
        painter.setFont(bold_font)
        painter.setPen(QColor(pal.current().TEXT_PRIMARY))
        painter.drawText(
            QRectF(cx - outer_r, cy + 6, outer_r * 2, 20), Qt.AlignCenter, _short_num(total)
        )

        if not show_legend:
            return

        legend_x = donut_area_w + margin * 2 + 6
        legend_y = max(8, cy - len(self.labels) * 11)
        painter.setFont(QFont(font.family(), 9))
        for i, (seg_start, seg_end, label, v, color) in enumerate(self._segments):
            y = legend_y + i * 22
            if y > rect.height() - 8:
                break
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(legend_x, y, 10, 10), 2, 2)
            painter.setPen(QColor(pal.current().TEXT_MUTED) if i != self._hover_index else QColor(pal.current().TEXT_PRIMARY))
            pct = v / total * 100
            text = f"{label} ({pct:.0f}%)"
            painter.drawText(QRectF(legend_x + 16, y - 4, legend_w - 20, 18), Qt.AlignVCenter | Qt.AlignRight, text)

    def _segment_at(self, pos):
        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()
        r = math.hypot(dx, dy)
        if r < self._inner_r or r > self._outer_r:
            return -1, None, None
        angle = math.degrees(math.atan2(-dy, dx))
        deg_from_top_cw = (90 - angle) % 360
        for i, (seg_start, seg_end, label, v, color) in enumerate(self._segments):
            if seg_start <= deg_from_top_cw < seg_end:
                return i, label, v
        return -1, None, None

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        i, label, v = self._segment_at(pos)
        if i != self._hover_index:
            self._hover_index = i
            self.update()
        if label is not None:
            total = sum(self.values) or 1
            global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            QToolTip.showText(global_pos, f"{label}: {fmt_money(v)} ({v / total * 100:.1f}%)", self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        _, label, v = self._segment_at(pos)
        if label is not None:
            self.segment_clicked.emit(label)

    def leaveEvent(self, event):
        if self._hover_index != -1:
            self._hover_index = -1
            self.update()
        QToolTip.hideText()
        super().leaveEvent(event)


class ClickableFrame(QFrame):
    """فريم عادي بس بيدوس تقدر تربطه بأكشن (زي كارت داشبورد قابل للضغط)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

    def set_clickable(self, enabled=True):
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self._clickable = enabled

    def mousePressEvent(self, event):
        if getattr(self, "_clickable", False):
            self.clicked.emit()
        super().mousePressEvent(event)


class KpiCard(ClickableFrame):
    """كارت KPI بيدعم عداد متحرك للقيمة (تتحرك من الرقم القديم للجديد
    بدل ما تتغيّر فجأة) وقابل للضغط للانتقال لشاشة تانية."""

    def __init__(self, icon, title, variant="info", invert_trend_color=False, is_money=True, parent=None):
        super().__init__(parent)
        color = pal.variant_color(variant)
        self.invert_trend_color = invert_trend_color
        self.is_money = is_money
        self._current_value = 0.0
        self.setObjectName("Card")
        self.setProperty("variant", variant)
        self.setMinimumHeight(150)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 16)
        v.setSpacing(0)

        icon_size = 44
        icon_label = QLabel()
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setPixmap(_make_icon_pixmap(icon, icon_size, color))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(icon_label)
        top.addStretch()
        v.addLayout(top)
        v.addSpacing(14)  # فاصل واضح بين الأيقونة والنص عشان ميتلخبطوش في بعض

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        title_label.setWordWrap(True)
        v.addWidget(title_label)
        v.addSpacing(4)

        self.value_label = QLabel("0")
        self.value_label.setObjectName("CardValue")
        v.addWidget(self.value_label)
        v.addSpacing(6)

        self.footer_label = QLabel("")
        self.footer_label.setStyleSheet("font-size:12px; font-weight:bold;")
        v.addWidget(self.footer_label)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(500)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)

    def _format(self, v):
        return fmt_money(v) if self.is_money else str(int(round(v)))

    def _on_anim_value(self, v):
        self.value_label.setText(self._format(v))

    def set_data(self, value, pct=None, subtitle=None):
        self._anim.stop()
        self._anim.setStartValue(float(self._current_value))
        self._anim.setEndValue(float(value))
        self._anim.start()
        self._current_value = value

        if pct is not None:
            positive = pct >= 0
            good = positive if not self.invert_trend_color else (not positive)
            trend_color = pal.current().ACCENT_TEAL if good else pal.current().RED
            arrow = "↑" if positive else "↓"
            self.footer_label.setStyleSheet(f"color:{trend_color}; font-size:12px; font-weight:bold;")
            self.footer_label.setText(i18n.tr("reports.trend_vs_previous", pct=f"{abs(pct):.0f}", arrow=arrow))
        elif subtitle:
            self.footer_label.setStyleSheet(f"color:{pal.current().TEXT_MUTED}; font-size:12px; font-weight:normal;")
            self.footer_label.setText(subtitle)
        else:
            self.footer_label.setText("")


class DebtBox(ClickableFrame):
    """صندوق ملخص دين قابل للضغط - بيوديك مباشرة لتاب الدين المناسب
    في شاشة الآجل، مع عداد متحرك للقيمة."""

    def __init__(self, title, variant="info", parent=None):
        super().__init__(parent)
        self._current_value = 0.0
        self.setObjectName("Card")
        self.setProperty("variant", variant)
        bv = QVBoxLayout(self)
        bv.setContentsMargins(14, 14, 14, 14)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        t.setWordWrap(True)
        bv.addWidget(t)
        self.value_label = QLabel(fmt_money(0))
        self.value_label.setStyleSheet("font-size:20px; font-weight:bold;")
        bv.addWidget(self.value_label)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(500)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.value_label.setText(fmt_money(v)))

    def set_value(self, value):
        self._anim.stop()
        self._anim.setStartValue(float(self._current_value))
        self._anim.setEndValue(float(value))
        self._anim.start()
        self._current_value = value


class ProductRow(ClickableFrame):
    """صف صنف قابل للضغط في قايمة "أعلى المنتجات مبيعاً" - بيفلتر
    باقي الشاشة على الصنف ده."""

    def __init__(self, rank, name, qty, pct, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame:hover { background-color: rgba(127,127,127,40); border-radius:6px; }")
        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(4, 4, 4, 4)

        rank_label = QLabel(str(rank))
        rank_label.setFixedSize(24, 24)
        rank_label.setAlignment(Qt.AlignCenter)
        rank_label.setStyleSheet(
            f"background-color:{pal.current().ACCENT_TEAL}; border-radius:12px; "
            f"color:{pal.current().BG_PRIMARY}; font-weight:bold; font-size:11px;"
        )
        row_layout.addWidget(rank_label)

        name_label = QLabel(name)
        row_layout.addWidget(name_label, 1)

        qty_label = QLabel(i18n.tr("reports.qty_pieces", qty=qty))
        qty_label.setObjectName("CardTitle")
        row_layout.addWidget(qty_label)

        pct_label = QLabel(f"{pct:.1f}%")
        pct_label.setStyleSheet(f"color:{pal.current().ACCENT_TEAL}; font-weight:bold; min-width:44px;")
        pct_label.setAlignment(Qt.AlignLeft)
        row_layout.addWidget(pct_label)


class ReportsView(QWidget):
    DATE_PRESET_KEYS = [
        "reports.date_preset.current_month", "reports.date_preset.last_month",
        "reports.date_preset.last_7_days", "reports.date_preset.all_time", "reports.date_preset.custom",
    ]

    def __init__(self, goto_callback=None):
        super().__init__()
        self.goto_callback = goto_callback
        self.filter_start, self.filter_end = _month_bounds(0)
        self.filter_employee = None
        self.filter_category = None
        self.filter_product = None
        self.DATE_PRESETS = [i18n.tr(k) for k in self.DATE_PRESET_KEYS]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("reports.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), i18n.tr("reports.tab.overview"))
        tabs.addTab(self._build_top_products_tab(), i18n.tr("reports.tab.top_products"))
        tabs.addTab(self._build_monthly_tab(), i18n.tr("reports.tab.monthly"))
        tabs.addTab(self._build_daily_tab(), i18n.tr("reports.tab.daily"))
        layout.addWidget(tabs)
        self._tabs = tabs

    # ---------------- Overview (dashboard style) ----------------

    def _build_overview_tab(self):
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 4, 4)
        outer.setSpacing(12)

        self._active_filters_label = QLabel("")
        self._active_filters_label.setStyleSheet(f"color:{pal.current().AMBER}; font-size:12px;")
        self._active_filters_label.setWordWrap(True)
        self._active_filters_label.setVisible(False)

        outer.addWidget(self._build_filter_bar())
        outer.addWidget(self._active_filters_label)
        outer.addLayout(self._build_kpi_row())

        mid_row = QHBoxLayout()
        mid_row.setSpacing(16)
        mid_row.addWidget(self._build_sales_chart_card(), 2)
        mid_row.addWidget(self._build_employees_chart_card(), 1)
        outer.addLayout(mid_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)
        bottom_row.addWidget(self._build_top_products_card(), 1)
        bottom_row.addWidget(self._build_category_donut_card(), 1)
        bottom_row.addWidget(self._build_debts_summary_card(), 1)
        outer.addLayout(bottom_row)

        # الصفحة كلها بقت قابلة للتمرير (Scroll) عشان الرسومات تاخد
        # مساحتها الطبيعية كاملة من غير ما تتقص لحد ما تتظبط جوه الشاشة.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)

        self._refresh_overview()
        return scroll

    def _build_filter_bar(self):
        frame = QFrame()
        frame.setObjectName("Card")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        period_row = QHBoxLayout()
        period_row.setSpacing(10)

        period_label = QLabel(i18n.tr("reports.filter.period"))
        period_label.setStyleSheet("font-weight:bold; font-size:14px;")
        period_row.addWidget(period_label)

        self.date_filter_combo = QComboBox()
        self.date_filter_combo.addItems(self.DATE_PRESETS)
        self.date_filter_combo.setMinimumWidth(150)
        self.date_filter_combo.setMinimumHeight(32)
        self.date_filter_combo.currentTextChanged.connect(self._on_date_preset_changed)
        period_row.addWidget(self.date_filter_combo)

        self.date_from_label = QLabel(i18n.tr("reports.filter.from"))
        period_row.addWidget(self.date_from_label)
        self.date_from_input = QDateEdit()
        self.date_from_input.setCalendarPopup(True)
        self.date_from_input.setDisplayFormat("yyyy-MM-dd")
        self.date_from_input.setMinimumHeight(32)
        self.date_from_input.setDate(QDate.currentDate().addMonths(-1))
        period_row.addWidget(self.date_from_input)

        self.date_to_label = QLabel(i18n.tr("reports.filter.to"))
        period_row.addWidget(self.date_to_label)
        self.date_to_input = QDateEdit()
        self.date_to_input.setCalendarPopup(True)
        self.date_to_input.setDisplayFormat("yyyy-MM-dd")
        self.date_to_input.setMinimumHeight(32)
        self.date_to_input.setDate(QDate.currentDate())
        period_row.addWidget(self.date_to_input)

        period_row.addStretch()
        outer.addLayout(period_row)
        self._set_custom_range_visible(False)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(10)

        employee_label = QLabel(i18n.tr("reports.filter.employee"))
        employee_label.setStyleSheet("font-weight:bold; font-size:14px;")
        filters_row.addWidget(employee_label)
        self.employee_filter_combo = QComboBox()
        self.employee_filter_combo.setMinimumWidth(160)
        self.employee_filter_combo.setMinimumHeight(32)
        filters_row.addWidget(self.employee_filter_combo)

        category_label = QLabel(i18n.tr("reports.filter.category"))
        category_label.setStyleSheet("font-weight:bold; font-size:14px;")
        filters_row.addWidget(category_label)
        self.category_filter_combo = QComboBox()
        self.category_filter_combo.setMinimumWidth(160)
        self.category_filter_combo.setMinimumHeight(32)
        filters_row.addWidget(self.category_filter_combo)

        self._reload_filter_options()

        filters_row.addStretch()

        apply_btn = QPushButton(i18n.tr("reports.filter.apply"))
        apply_btn.setMinimumHeight(34)
        apply_btn.clicked.connect(self._apply_filters)
        filters_row.addWidget(apply_btn)

        clear_btn = QPushButton(i18n.tr("reports.filter.clear"))
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.setMinimumHeight(34)
        clear_btn.clicked.connect(self._clear_filters)
        filters_row.addWidget(clear_btn)

        outer.addLayout(filters_row)
        return frame

    def _set_custom_range_visible(self, visible):
        self.date_from_label.setVisible(visible)
        self.date_from_input.setVisible(visible)
        self.date_to_label.setVisible(visible)
        self.date_to_input.setVisible(visible)

    def _on_date_preset_changed(self, text):
        self._set_custom_range_visible(text == i18n.tr("reports.date_preset.custom"))

    def _reload_filter_options(self):
        self.employee_filter_combo.clear()
        self.employee_filter_combo.addItem(i18n.tr("reports.filter.all"), None)
        for r in db.fetch_all(
            """SELECT DISTINCT s.created_by, COALESCE(u.full_name, s.created_by) as name
               FROM sales s LEFT JOIN users u ON u.username = s.created_by
               ORDER BY name"""
        ):
            self.employee_filter_combo.addItem(r["name"] or r["created_by"], r["created_by"])

        self.category_filter_combo.clear()
        self.category_filter_combo.addItem(i18n.tr("reports.filter.all"), None)
        for r in db.fetch_all(
            "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ):
            self.category_filter_combo.addItem(r["category"], r["category"])

    def _apply_filters(self):
        preset = self.date_filter_combo.currentText()
        today = date.today()
        if preset == i18n.tr("reports.date_preset.current_month"):
            self.filter_start, self.filter_end = _month_bounds(0)
        elif preset == i18n.tr("reports.date_preset.last_month"):
            self.filter_start, self.filter_end = _month_bounds(1)
        elif preset == i18n.tr("reports.date_preset.last_7_days"):
            self.filter_start = (today - timedelta(days=7)).isoformat()
            self.filter_end = (today + timedelta(days=1)).isoformat()
        elif preset == i18n.tr("reports.date_preset.custom"):
            d_from = self.date_from_input.date().toPython()
            d_to = self.date_to_input.date().toPython()
            if d_from > d_to:
                d_from, d_to = d_to, d_from
            self.filter_start = d_from.isoformat()
            self.filter_end = (d_to + timedelta(days=1)).isoformat()
        else:
            self.filter_start, self.filter_end = ALL_TIME_START, ALL_TIME_END

        self.filter_employee = self.employee_filter_combo.currentData()
        self.filter_category = self.category_filter_combo.currentData()
        self.filter_product = None
        self._refresh_overview()

    def _clear_filters(self):
        self.date_filter_combo.setCurrentIndex(0)
        self.employee_filter_combo.setCurrentIndex(0)
        self.category_filter_combo.setCurrentIndex(0)
        self.filter_start, self.filter_end = _month_bounds(0)
        self.filter_employee = None
        self.filter_category = None
        self.filter_product = None
        self._refresh_overview()

    def _filter_by_employee_name(self, name_clicked):
        idx = self.employee_filter_combo.findText(name_clicked)
        if idx >= 0:
            self.employee_filter_combo.setCurrentIndex(idx)
            self.filter_employee = self.employee_filter_combo.currentData()
            self._refresh_overview()

    def _filter_by_category_clicked(self, category_clicked):
        idx = self.category_filter_combo.findText(category_clicked)
        if idx >= 0:
            self.category_filter_combo.setCurrentIndex(idx)
            self.filter_category = self.category_filter_combo.currentData()
            self._refresh_overview()

    def _filter_by_product_clicked(self, product_name):
        self.filter_product = product_name
        self._refresh_overview()

    def _refresh_overview(self):
        labels = []
        if self.filter_employee:
            labels.append(i18n.tr("reports.active_filter.employee", name=self.employee_filter_combo.currentText()))
        if self.filter_category:
            labels.append(i18n.tr("reports.active_filter.category", category=self.filter_category))
        if self.filter_product:
            labels.append(i18n.tr("reports.active_filter.product", product=self.filter_product))
        self._active_filters_label.setText(
            (i18n.tr("reports.active_filter_prefix") + " | ".join(labels)) if labels else ""
        )
        self._active_filters_label.setVisible(bool(labels))

        self._refresh_kpis()
        self._refresh_sales_chart()
        self._refresh_employees_chart()
        self._refresh_category_donut()
        self._refresh_top_products()
        self._refresh_debts_summary()

    def _kpi_card(self, icon, title, variant, invert_trend_color=False, is_money=True, on_click=None):
        card = KpiCard(icon, title, variant, invert_trend_color=invert_trend_color, is_money=is_money)
        if on_click:
            card.set_clickable(True)
            card.clicked.connect(on_click)
        return card

    # ---------------- Filter-aware data helpers ----------------

    def _is_all_time(self):
        return self.filter_start == ALL_TIME_START

    def _prev_period(self):
        if self._is_all_time():
            return None, None
        d_start = datetime.strptime(self.filter_start[:10], "%Y-%m-%d")
        d_end = datetime.strptime(self.filter_end[:10], "%Y-%m-%d")
        length = d_end - d_start
        prev_end = self.filter_start
        prev_start = (d_start - length).strftime("%Y-%m-%d")
        return prev_start, prev_end

    def _sale_items_filter(self, start, end, ignore_product=False):
        conditions = ["s.created_at>=?", "s.created_at<?"]
        params = [start, end]
        if self.filter_employee:
            conditions.append("s.created_by=?")
            params.append(self.filter_employee)
        if self.filter_category:
            conditions.append("p.category=?")
            params.append(self.filter_category)
        if self.filter_product and not ignore_product:
            conditions.append("si.product_name=?")
            params.append(self.filter_product)
        return " AND ".join(conditions), params

    def _period_totals(self, start, end):
        """يرجع (revenue, cogs) بعد تطبيق فلاتر الموظف/الفئة/الصنف."""
        where, params = self._sale_items_filter(start, end)
        row = db.fetch_one(
            f"""SELECT COALESCE(SUM(si.price*si.qty),0) rev, COALESCE(SUM(si.cost_price*si.qty),0) cogs
                FROM sale_items si JOIN sales s ON s.id=si.sale_id LEFT JOIN products p ON p.id=si.product_id
                WHERE {where}""",
            params,
        )
        return row["rev"], row["cogs"]

    def _period_expenses(self, start, end):
        return db.fetch_one(
            "SELECT COALESCE(SUM(amount),0) v FROM expenses WHERE date>=? AND date<?", (start, end)
        )["v"]

    def _monthly_target(self):
        row = db.fetch_one("SELECT value FROM settings WHERE setting_key='monthly_sales_target'")
        if not row or not row["value"]:
            return None
        try:
            v = float(row["value"])
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    def _build_kpi_row(self):
        row = QHBoxLayout()
        row.setSpacing(16)
        self.kpi_sales = self._kpi_card(
            "📈", i18n.tr("reports.kpi.sales"), "primary",
            on_click=(lambda: self.goto_callback("sales")) if self.goto_callback else None,
        )
        self.kpi_expenses = self._kpi_card(
            "🧾", i18n.tr("dashboard.expenses"), "negative", invert_trend_color=True,
            on_click=(lambda: self.goto_callback("expenses")) if self.goto_callback else None,
        )
        self.kpi_profit = self._kpi_card("💰", i18n.tr("dashboard.profit"), "primary")
        self.kpi_customers = self._kpi_card(
            "👥", i18n.tr("reports.kpi.customers"), "info", is_money=False,
            on_click=(lambda: self.goto_callback("customers")) if self.goto_callback else None,
        )
        row.addWidget(self.kpi_sales)
        row.addWidget(self.kpi_expenses)
        row.addWidget(self.kpi_profit)
        row.addWidget(self.kpi_customers)
        return row

    def _refresh_kpis(self):
        start, end = self.filter_start, self.filter_end
        prev_start, prev_end = self._prev_period()

        cur_rev, cur_cogs = self._period_totals(start, end)
        cur_exp = self._period_expenses(start, end)
        cur_profit = cur_rev - cur_cogs - cur_exp

        if prev_start:
            prev_rev, prev_cogs = self._period_totals(prev_start, prev_end)
            prev_exp = self._period_expenses(prev_start, prev_end)
            prev_profit = prev_rev - prev_cogs - prev_exp
            rev_pct = _pct_change(cur_rev, prev_rev)
            exp_pct = _pct_change(cur_exp, prev_exp)
            profit_pct = _pct_change(cur_profit, prev_profit)
        else:
            rev_pct = exp_pct = profit_pct = None

        total_customers = db.fetch_one("SELECT COUNT(*) c FROM customers")["c"]
        new_customers = db.fetch_one(
            "SELECT COUNT(*) c FROM customers WHERE created_at>=? AND created_at<?", (start, end)
        )["c"]

        self.kpi_sales.set_data(cur_rev, pct=rev_pct)
        self.kpi_expenses.set_data(cur_exp, pct=exp_pct)
        self.kpi_profit.set_data(cur_profit, pct=profit_pct)
        self.kpi_customers.set_data(total_customers, subtitle=i18n.tr("reports.new_customers_subtitle", count=new_customers))

    def _build_sales_chart_card(self):
        frame = QFrame()
        frame.setObjectName("Card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        title = QLabel(i18n.tr("reports.sales_chart_title"))
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        v.addWidget(title)

        self._sales_legend_box = QHBoxLayout()
        v.addLayout(self._sales_legend_box)

        self.sales_chart = LineAreaChart([], [], color=pal.current().ACCENT_TEAL)
        v.addWidget(self.sales_chart)
        return frame

    def _refresh_sales_chart(self):
        if self._is_all_time():
            first_sale = db.fetch_one("SELECT MIN(LEFT(created_at,10)) d FROM sales")["d"]
            start_d = date.fromisoformat(first_sale) if first_sale else date.today()
            end_d = date.today() + timedelta(days=1)
        else:
            start_d = date.fromisoformat(self.filter_start[:10])
            end_d = date.fromisoformat(self.filter_end[:10])
        num_days = max(min((end_d - start_d).days, 366), 1)

        where, params = self._sale_items_filter(start_d.isoformat(), end_d.isoformat())
        rows = db.fetch_all(
            f"""SELECT LEFT(s.created_at,10) d, SUM(si.price*si.qty) v
                FROM sale_items si JOIN sales s ON s.id=si.sale_id LEFT JOIN products p ON p.id=si.product_id
                WHERE {where} GROUP BY LEFT(s.created_at,10)""",
            params,
        )
        daily = {r["d"]: (r["v"] or 0) for r in rows}
        values, day_labels = [], []
        for i in range(num_days):
            d = start_d + timedelta(days=i)
            values.append(daily.get(d.isoformat(), 0))
            day_labels.append(str(d.day))

        is_current_month = (self.filter_start, self.filter_end) == _month_bounds(0)
        no_extra_filters = not (self.filter_employee or self.filter_category or self.filter_product)
        target = self._monthly_target() if (is_current_month and no_extra_filters) else None
        daily_target = (target / num_days) if target else None

        while self._sales_legend_box.count():
            item = self._sales_legend_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._sales_legend_box.addWidget(self._legend_dot(pal.current().ACCENT_TEAL, i18n.tr("reports.daily_sales_legend")))
        if daily_target:
            self._sales_legend_box.addWidget(self._legend_dot(pal.current().AMBER, i18n.tr("reports.daily_target_legend"), dashed=True))
        self._sales_legend_box.addStretch()

        self.sales_chart.set_values(values, day_labels, target=daily_target)

    def _legend_dot(self, color, text, dashed=False):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        dot = QLabel()
        dot.setFixedSize(14, 3)
        style = "dashed" if dashed else "solid"
        dot.setStyleSheet(f"border-top: 3px {style} {color};")
        h.addWidget(dot)
        label = QLabel(text)
        label.setStyleSheet(f"color:{pal.current().TEXT_MUTED}; font-size:12px;")
        h.addWidget(label)
        return box

    def _build_employees_chart_card(self):
        frame = QFrame()
        frame.setObjectName("Card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        title = QLabel(i18n.tr("reports.employees_chart_title"))
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        v.addWidget(title)

        self.employees_chart = BarChart([], [], color=pal.current().ACCENT_TEAL)
        self.employees_chart.bar_clicked.connect(self._filter_by_employee_name)
        v.addWidget(self.employees_chart)
        return frame

    def _refresh_employees_chart(self):
        where, params = self._sale_items_filter(self.filter_start, self.filter_end)
        rows = db.fetch_all(
            f"""SELECT COALESCE(u.full_name, s.created_by) as name, SUM(si.price*si.qty) as total
                FROM sale_items si JOIN sales s ON s.id=si.sale_id LEFT JOIN products p ON p.id=si.product_id
                LEFT JOIN users u ON u.username = s.created_by
                WHERE {where} GROUP BY s.created_by, u.full_name ORDER BY total DESC LIMIT 6""",
            params,
        )
        labels = [r["name"] or "-" for r in rows]
        values = [r["total"] or 0 for r in rows]
        self.employees_chart.set_values(labels, values)

    def _build_category_donut_card(self):
        frame = QFrame()
        frame.setObjectName("Card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        title = QLabel(i18n.tr("reports.category_donut_title"))
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        v.addWidget(title)

        self.category_donut = DonutChart([], [])
        self.category_donut.segment_clicked.connect(self._filter_by_category_clicked)
        v.addWidget(self.category_donut)
        return frame

    def _refresh_category_donut(self):
        where, params = self._sale_items_filter(self.filter_start, self.filter_end)
        # بنجمّع على العمود الخام (product.category ممكن يكون NULL) بدل ما نحط
        # COALESCE(..., ?) في الـ SELECT والـ GROUP BY مع باراميتر منفصل لكل واحد -
        # SQL Server مش بيعتبرهم نفس التعبير في الحالة دي وبيرفض بخطأ 8120.
        # نستبدل NULL بتسمية "غير مصنّف" في بايثون بعد الجلب بدل كده.
        uncategorized = i18n.tr("reports.uncategorized")
        rows = db.fetch_all(
            f"""SELECT p.category as category, SUM(si.price*si.qty) as total
                FROM sale_items si JOIN sales s ON s.id=si.sale_id LEFT JOIN products p ON p.id=si.product_id
                WHERE {where} GROUP BY p.category ORDER BY total DESC LIMIT 8""",
            params,
        )
        labels = [r["category"] or uncategorized for r in rows]
        values = [r["total"] or 0 for r in rows]
        self.category_donut.set_values(labels, values)

    def _build_top_products_card(self):
        frame = QFrame()
        frame.setObjectName("Card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        title = QLabel(i18n.tr("reports.top_products_title"))
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        v.addWidget(title)

        self._top_products_inner = QVBoxLayout()
        v.addLayout(self._top_products_inner)
        v.addStretch()
        return frame

    def _refresh_top_products(self):
        while self._top_products_inner.count():
            item = self._top_products_inner.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        where, params = self._sale_items_filter(self.filter_start, self.filter_end, ignore_product=True)
        rows = db.fetch_all(
            f"""SELECT si.product_name, SUM(si.qty) total_qty, SUM(si.price*si.qty) total_sales
                FROM sale_items si JOIN sales s ON s.id=si.sale_id LEFT JOIN products p ON p.id=si.product_id
                WHERE {where} GROUP BY si.product_name ORDER BY total_sales DESC LIMIT 5""",
            params,
        )
        if not rows:
            empty = QLabel(i18n.tr("reports.no_sales_matching_filter"))
            empty.setObjectName("CardTitle")
            self._top_products_inner.addWidget(empty)
            return

        total_all = sum(r["total_sales"] or 0 for r in rows) or 1
        for i, r in enumerate(rows, start=1):
            pct = (r["total_sales"] or 0) / total_all * 100
            product_row = ProductRow(i, r["product_name"], r["total_qty"], pct)
            product_row.set_clickable(True)
            product_row.clicked.connect(lambda name=r["product_name"]: self._filter_by_product_clicked(name))
            self._top_products_inner.addWidget(product_row)

    def _build_debts_summary_card(self):
        frame = QFrame()
        frame.setObjectName("Card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        title = QLabel(i18n.tr("reports.debts_summary_title"))
        title.setStyleSheet("font-size:15px; font-weight:bold;")
        v.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.debt_i_owe_box = DebtBox(i18n.tr("dashboard.i_owe"), "negative")
        self.debt_owed_box = DebtBox(i18n.tr("dashboard.owed_to_me"), "primary")
        if self.goto_callback:
            self.debt_i_owe_box.set_clickable(True)
            self.debt_i_owe_box.clicked.connect(lambda: self.goto_callback("debts", "i_owe"))
            self.debt_owed_box.set_clickable(True)
            self.debt_owed_box.clicked.connect(lambda: self.goto_callback("debts", "owed_to_me"))
        row.addWidget(self.debt_i_owe_box)
        row.addWidget(self.debt_owed_box)
        v.addLayout(row)
        v.addStretch()
        return frame

    def _refresh_debts_summary(self):
        s = db.dashboard_summary()
        self.debt_i_owe_box.set_value(s["i_owe"])
        self.debt_owed_box.set_value(s["owed_to_me"])

    # ---------------- Top products (detailed table) ----------------

    def _build_top_products_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(i18n.tr("reports.top_products_hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        v.addWidget(hint)
        table = build_table([
            i18n.tr("reports.col.product"), i18n.tr("reports.col.qty_sold"),
            i18n.tr("reports.col.total_sales"), i18n.tr("reports.col.total_profit"),
        ])
        rows = db.fetch_all(
            """SELECT product_name,
                      SUM(qty) as total_qty,
                      SUM(price*qty) as total_sales,
                      SUM((price-cost_price)*qty) as total_profit
               FROM sale_items GROUP BY product_name ORDER BY total_qty DESC LIMIT 50"""
        )
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(table, i, [r["product_name"], r["total_qty"], fmt_money(r["total_sales"]), fmt_money(r["total_profit"])])
        table.cellDoubleClicked.connect(lambda r, c, rows=rows: self._drill_into_product(rows, r))
        v.addWidget(table)
        return w

    def _drill_into_product(self, rows, row_index):
        if row_index < 0 or row_index >= len(rows):
            return
        self.filter_product = rows[row_index]["product_name"]
        self._refresh_overview()
        self._tabs.setCurrentIndex(0)

    # ---------------- Monthly summary ----------------

    def _build_monthly_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(i18n.tr("reports.monthly_hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        v.addWidget(hint)
        table = build_table([
            i18n.tr("reports.col.month"), i18n.tr("reports.col.revenue"),
            i18n.tr("reports.col.expenses"), i18n.tr("reports.col.purchases"),
        ])
        revenue_rows = db.fetch_all(
            "SELECT LEFT(created_at,7) as ym, SUM(total) as v FROM sales GROUP BY LEFT(created_at,7) ORDER BY ym DESC"
        )
        expenses_rows = {
            r["ym"]: r["v"] for r in db.fetch_all(
                "SELECT LEFT(date,7) as ym, SUM(amount) as v FROM expenses GROUP BY LEFT(date,7)"
            )
        }
        purchases_rows = {
            r["ym"]: r["v"] for r in db.fetch_all(
                "SELECT LEFT(created_at,7) as ym, SUM(total) as v FROM purchases GROUP BY LEFT(created_at,7)"
            )
        }
        table.setRowCount(len(revenue_rows))
        for i, r in enumerate(revenue_rows):
            ym = r["ym"]
            fill_row(table, i, [
                ym, fmt_money(r["v"] or 0), fmt_money(expenses_rows.get(ym, 0)), fmt_money(purchases_rows.get(ym, 0))
            ])
        table.cellDoubleClicked.connect(lambda r, c, rows=revenue_rows: self._drill_into_month(rows, r))
        v.addWidget(table)
        return w

    def _drill_into_month(self, rows, row_index):
        if row_index < 0 or row_index >= len(rows):
            return
        ym = rows[row_index]["ym"]
        if not ym:
            return
        year, month = map(int, ym.split("-"))
        start = f"{year:04d}-{month:02d}-01"
        end = f"{year + 1:04d}-01-01" if month == 12 else f"{year:04d}-{month + 1:02d}-01"
        self.filter_start, self.filter_end = start, end
        self.date_filter_combo.blockSignals(True)
        self.date_filter_combo.setCurrentIndex(-1)
        self.date_filter_combo.blockSignals(False)
        self._set_custom_range_visible(False)
        self._refresh_overview()
        self._tabs.setCurrentIndex(0)

    # ---------------- Daily summary ----------------

    def _build_daily_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(i18n.tr("reports.daily_hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        v.addWidget(hint)
        table = build_table([
            i18n.tr("reports.col.day"), i18n.tr("reports.col.revenue"),
            i18n.tr("reports.col.expenses"), i18n.tr("reports.col.purchases"),
        ])
        revenue_rows = db.fetch_all(
            """SELECT LEFT(created_at,10) as ymd, SUM(total) as v FROM sales
               GROUP BY LEFT(created_at,10) ORDER BY ymd DESC LIMIT 365"""
        )
        expenses_rows = {
            r["ymd"]: r["v"] for r in db.fetch_all(
                "SELECT LEFT(date,10) as ymd, SUM(amount) as v FROM expenses GROUP BY LEFT(date,10)"
            )
        }
        purchases_rows = {
            r["ymd"]: r["v"] for r in db.fetch_all(
                "SELECT LEFT(created_at,10) as ymd, SUM(total) as v FROM purchases GROUP BY LEFT(created_at,10)"
            )
        }
        table.setRowCount(len(revenue_rows))
        for i, r in enumerate(revenue_rows):
            ymd = r["ymd"]
            fill_row(table, i, [
                ymd, fmt_money(r["v"] or 0), fmt_money(expenses_rows.get(ymd, 0)), fmt_money(purchases_rows.get(ymd, 0))
            ])
        table.cellDoubleClicked.connect(lambda r, c, rows=revenue_rows: self._drill_into_day(rows, r))
        v.addWidget(table)
        return w

    def _drill_into_day(self, rows, row_index):
        if row_index < 0 or row_index >= len(rows):
            return
        ymd = rows[row_index]["ymd"]
        if not ymd:
            return
        start = ymd
        end = (date.fromisoformat(ymd) + timedelta(days=1)).isoformat()
        self.filter_start, self.filter_end = start, end
        self.date_filter_combo.blockSignals(True)
        self.date_filter_combo.setCurrentIndex(-1)
        self.date_filter_combo.blockSignals(False)
        self._set_custom_range_visible(False)
        self._refresh_overview()
        self._tabs.setCurrentIndex(0)
