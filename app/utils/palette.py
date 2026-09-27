"""نظام ألوان Cortex - مصدر واحد لكل الألوان في التطبيق (استُخرجت من هوية
الشركة البصرية). أي لون تاني في الكود لازم يرجع لحد من الـ tokens دي بدل
ما يخترع رقم جديد."""


class Cortex:
    """الثيم الغامق - الألوان الأصلية من هوية Cortex."""
    BG_PRIMARY = "#0A1428"
    BG_SURFACE = "#131F38"
    BG_SURFACE_ALT = "#1B2A47"
    ACCENT_TEAL = "#4FD8C4"
    ACCENT_BLUE = "#4C6FFF"
    TEXT_PRIMARY = "#EDF1F7"
    TEXT_MUTED = "#8B96AC"
    BORDER = "rgba(79, 216, 196, 0.15)"
    RED = "#EF5A5A"
    AMBER = "#F2B84B"


class CortexLight:
    """الثيم الفاتح - نفس درجات التيل/الأزرق بس أغمق شوية عشان تباين كافي
    على خلفية بيضا (مفيش hex values لايت جاهزة من الهوية الأصلية)."""
    BG_PRIMARY = "#F4F7FB"
    BG_SURFACE = "#FFFFFF"
    BG_SURFACE_ALT = "#E9EEF6"
    ACCENT_TEAL = "#0E9C88"
    ACCENT_BLUE = "#3557E8"
    TEXT_PRIMARY = "#10192B"
    TEXT_MUTED = "#5B6B85"
    BORDER = "rgba(14, 156, 136, 0.18)"
    RED = "#EF5A5A"
    AMBER = "#F2B84B"


_current_theme = "dark"


def set_theme(theme):
    global _current_theme
    _current_theme = theme if theme in ("dark", "light") else "dark"


def get_theme():
    return _current_theme


def current():
    """يرجع كلاس الـ palette المناسب للثيم الحالي - بيتستخدم من أي كود
    بيرسم بـ QPainter (كروت، لوجو) ومحتاج يعرف الألوان الصح دلوقتي."""
    return CortexLight if _current_theme == "light" else Cortex


# ---------------- ألوان الـ variant الدلالية للكروت ----------------
# بدل ما كل كارت ياخد لون عشوائي، بنحدد معنى واحد لكل لون: تيل = أساسي/إيجابي،
# أزرق = معلوماتي محايد، أحمر = سلبي بس، عنبر = تحذير بس.

def variant_color(variant):
    p = current()
    return {
        "primary": p.ACCENT_TEAL,
        "info": p.ACCENT_BLUE,
        "negative": p.RED,
        "warning": p.AMBER,
    }.get(variant, p.ACCENT_BLUE)
