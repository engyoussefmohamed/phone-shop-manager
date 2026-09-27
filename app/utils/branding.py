"""رسم لوجو Cortex (3 نقط متصلة بخط تكوّن قوس "C") من ملف الـ SVG الحقيقي
(app/assets/cortex_mark.svg) - نفس الهندسة بالظبط المستخدمة في أيقونة
البرنامج (cortex_icon.ico/svg)، بس من غير خلفية المربع، عشان يتحط على أي
خلفية (شاشة السبلاش، شاشة الدخول). بيتستخدم في أكتر من مكان (خلفية
الداشبورد، شاشة الدخول، شاشة السبلاش)."""
import os

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QPixmap, QPainter, QFont, QPainterPath
from PySide6.QtSvg import QSvgRenderer

from app.utils.palette import Cortex, current

# app/utils/branding.py -> app/utils -> app -> بندخل app/assets من هنا. نفس
# نمط LOGO_PATH في login_window.py بالظبط (مش db_config.BASE_DIR اللي بيرجع
# مجلد الـ exe نفسه - أصول الـ PyInstaller المجمّعة بتتفك ضغطها في مجلد
# مؤقت مختلف (_MEIPASS)، مش جنب الـ exe).
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK_SVG_PATH = os.path.join(_APP_DIR, "assets", "cortex_mark.svg")
_mark_renderer = None


def _get_mark_renderer():
    global _mark_renderer
    if _mark_renderer is None:
        _mark_renderer = QSvgRenderer(MARK_SVG_PATH)
    return _mark_renderer


def draw_node_mark(painter, rect, opacity=1.0):
    """بيرسم لوجو Cortex الحقيقي (من ملف الـ SVG) جوه rect (QRectF) باستخدام
    painter جاهز - يشتغل جوه أي paintEvent موجود بالفعل (زي Card) من غير ما
    يعمل QPixmap منفصل."""
    renderer = _get_mark_renderer()
    painter.save()
    painter.setOpacity(opacity)
    painter.setRenderHint(QPainter.Antialiasing)
    # الملف مربع (200x200) - بنحافظ على النسبة ونوسّطه جوه rect حتى لو مش مربع.
    side = min(rect.width(), rect.height())
    target = QRectF(
        rect.left() + (rect.width() - side) / 2,
        rect.top() + (rect.height() - side) / 2,
        side, side,
    )
    renderer.render(painter, target)
    painter.restore()


def node_mark_pixmap(size, opacity=1.0):
    """بيرجّع QPixmap مربع بحجم size فيه الشكل - للاستخدام في QLabel (هيدر
    السايدبار، خلفية الداشبورد) من غير ما يحتاج widget بـ paintEvent خاص."""
    ratio = 2
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    draw_node_mark(painter, QRectF(0, 0, size, size), opacity=opacity)
    painter.end()
    return pm


def _paint_wordmark_scene(painter, width, height):
    """بيرسم خلفية Cortex.BG_PRIMARY غامقة ثابتة + لوجو + كلمة "Cortex" تحته
    (bold, TEXT_PRIMARY) - نفس التركيبة بالظبط المستخدمة في الصورة المرجعية،
    بس بتتقبل مستطيل مش مربع بس عشان تتظبط في أي حاوية (شاشة السبلاش
    المربعة، لوحة اللوجو المستطيلة في شاشة الدخول)."""
    painter.fillRect(QRectF(0, 0, width, height), QColor(Cortex.BG_PRIMARY))

    logo_size = min(width, height) * 0.32
    logo_top = height * 0.32
    logo_rect = QRectF((width - logo_size) / 2, logo_top, logo_size, logo_size)
    draw_node_mark(painter, logo_rect, opacity=1.0)

    painter.setPen(QColor(Cortex.TEXT_PRIMARY))
    font = QFont("IBM Plex Sans Arabic", int(min(width, height) * 0.075), QFont.Bold)
    painter.setFont(font)
    text_rect = QRectF(0, logo_top + logo_size + height * 0.04, width, height * 0.14)
    painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, "Cortex")


def splash_pixmap(size=420):
    """شاشة البداية (Splash) اللي بتظهر أول ما البرنامج يفتح - خلفية غامقة
    ثابتة بلون Cortex.BG_PRIMARY بغض النظر عن ثيم المستخدم المحفوظ (لسه
    مقروش من قاعدة البيانات في اللحظة دي أصلًا)، ولوجو أكبر في النص، وكلمة
    "Cortex" تحته زي الصورة المرجعية بالظبط."""
    ratio = 2
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    painter = QPainter(pm)
    _paint_wordmark_scene(painter, size, size)
    painter.end()
    return pm


def rounded_rect_path(rect, top_left, top_right, bottom_right, bottom_left):
    """مسار مستطيل بزوايا مختلفة الاستدارة كل واحدة لوحدها - مستخدم عشان
    نقص لوحة اللوجو في شاشة الدخول على شكلها الفعلي (زوايا برّانية مدورة،
    زوايا جوانية (اللي بتلاقي اللوحة التانية) حادة) بدل ما نعتمد على
    border-radius في QSS اللي مابيقصّش الـ pixmap المرسوم جواه."""
    path = QPainterPath()
    x, y, w, h = rect.left(), rect.top(), rect.width(), rect.height()
    path.moveTo(x + top_left, y)
    path.lineTo(x + w - top_right, y)
    path.arcTo(x + w - 2 * top_right, y, 2 * top_right, 2 * top_right, 90, -90)
    path.lineTo(x + w, y + h - bottom_right)
    path.arcTo(x + w - 2 * bottom_right, y + h - 2 * bottom_right, 2 * bottom_right, 2 * bottom_right, 0, -90)
    path.lineTo(x + bottom_left, y + h)
    path.arcTo(x, y + h - 2 * bottom_left, 2 * bottom_left, 2 * bottom_left, -90, -90)
    path.lineTo(x, y + top_left)
    path.arcTo(x, y, 2 * top_left, 2 * top_left, 180, -90)
    path.closeSubpath()
    return path


def draw_mini_accent(painter, rect, opacity=0.15):
    """نسخة مبسّطة جدًا (نقطتين وخط) للاستخدام كلمسة زخرفية صغيرة في ركن
    الكارت - الشكل الكامل (3 نقط) مش هيبان واضح في حجم بالصغر ده."""
    p = current()
    painter.save()
    painter.setOpacity(opacity)
    painter.setRenderHint(QPainter.Antialiasing)

    w, h = rect.width(), rect.height()
    x, y = rect.left(), rect.top()
    a = QPointF(x + w * 0.15, y + h * 0.8)
    b = QPointF(x + w * 0.85, y + h * 0.2)
    r = min(w, h) * 0.16

    pen = QPen(QColor(p.ACCENT_TEAL))
    pen.setWidthF(max(min(w, h) * 0.12, 1.0))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(a, b)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(p.ACCENT_BLUE))
    painter.drawEllipse(b, r, r)
    painter.setBrush(QColor(p.ACCENT_TEAL))
    painter.drawEllipse(a, r * 0.7, r * 0.7)

    painter.restore()
