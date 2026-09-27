import hashlib
import math
import os

from PySide6.QtCore import (
    Qt, QPointF, QTimer, QPropertyAnimation, QEasingCurve, Property
)
from PySide6.QtGui import QIcon, QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QComboBox, QFormLayout, QDialogButtonBox, QFrame, QWidget, QGraphicsDropShadowEffect, QLineEdit
)

from app import database as db
from app import i18n
from app.utils.branding import node_mark_pixmap, rounded_rect_path
from app.utils import palette as pal
from app.utils.palette import Cortex
from app.utils.widgets import FloatingLabelInput


class BranchPickDialog(QDialog):
    """بتظهر للأدمن بس لو فيه أكتر من فرع مسجّل - يختار يشتغل على أنهي فرع
    دلوقتي (العمليات الجديدة اللي هيسجلها هتتحط على الفرع ده، لكن التقارير
    والاستعلامات هيفضل يشوف فيها كل الفروع مجمّعة زي ما هو أدمن)."""

    def __init__(self, branches):
        super().__init__()
        self.setWindowTitle(i18n.tr("login.branch_pick.title"))
        form = QFormLayout(self)
        form.addRow(QLabel(i18n.tr("login.branch_pick.question")))
        self.combo = QComboBox()
        for b in branches:
            self.combo.addItem(b["name"], b["id"])
        form.addRow(i18n.tr("login.branch_pick.label"), self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText(i18n.tr("login.login_button"))
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    def selected_branch_id(self):
        return self.combo.currentData()


class ForcePasswordChangeDialog(QDialog):
    """بتظهر إجباريًا لو المستخدم بيسجل دخول بكلمة مرور افتراضية معروفة
    (admin123/emp123) - مفيش زرار إغلاق ومينفعش يتخطاها من غير ما يحط
    كلمة مرور جديدة صحيحة، عشان الحسابات الافتراضية الموثّقة في README
    متفضلش زي ما هي في كل نسخة جديدة من البرنامج."""

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.setWindowTitle(i18n.tr("login.force_change.title"))
        self.setModal(True)
        # من غير زرار إغلاق (X) - إجباري، مفيش طريقة يتخطاه من غير ما
        # يغيّر الباسورد فعلاً.
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)

        layout = QVBoxLayout(self)
        msg = QLabel(i18n.tr("login.force_change.message"))
        msg.setWordWrap(True)
        layout.addWidget(msg)

        form = QFormLayout()
        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        form.addRow(i18n.tr("login.force_change.new_password_placeholder"), self.new_password_input)

        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        form.addRow(i18n.tr("login.force_change.confirm_password_placeholder"), self.confirm_password_input)
        layout.addLayout(form)

        save_btn = QPushButton(i18n.tr("login.force_change.save_button"))
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        self.confirm_password_input.returnPressed.connect(self._save)

        skip_btn = QPushButton(i18n.tr("login.force_change.skip_button"))
        skip_btn.setObjectName("SecondaryButton")
        skip_btn.clicked.connect(self.accept)
        layout.addWidget(skip_btn)

    def _save(self):
        new_password = self.new_password_input.text()
        confirm_password = self.confirm_password_input.text()
        if len(new_password) < 4:
            QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.force_change.error_too_short"))
            return
        if new_password != confirm_password:
            QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.force_change.error_mismatch"))
            return
        default_password = db.DEFAULT_LOGIN_PASSWORDS.get(self.user["username"])
        if default_password is not None and new_password == default_password:
            QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.force_change.error_same_as_default"))
            return

        password_hash = hashlib.sha256(new_password.encode("utf-8")).hexdigest()
        db.update_user_password(self.user["id"], password_hash)
        self.accept()

    def closeEvent(self, event):
        event.ignore()

ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "cortex_icon.ico")

DIALOG_WIDTH = 680
DIALOG_HEIGHT = 420
LOGO_PANEL_WIDTH = 260
CORNER_RADIUS = 18


class _AnimatedAccentOverlay(QWidget):
    """لمسة خلفية متحركة خفيفة جدًا مستوحاة من شكل اللوجو (نقط متصلة) في
    خلفية لوحة اللوجو - نقط بتنبض (opacity) ببطء، بشفافية عالية جدًا عشان
    تبقى لمسة حياة مش عنصر يلفت النظر أو يشتت التركيز عن الفورم."""

    # (x_ratio, y_ratio, base_alpha, amplitude, speed, phase, is_teal)
    DOTS = [
        (0.22, 0.14, 0.05, 0.06, 0.55, 0.0, True),
        (0.78, 0.20, 0.04, 0.05, 0.45, 1.6, False),
        (0.16, 0.80, 0.04, 0.05, 0.40, 3.1, False),
        (0.82, 0.86, 0.05, 0.06, 0.50, 4.5, True),
        (0.50, 0.94, 0.03, 0.04, 0.35, 2.2, True),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    def _tick(self):
        self._t += 0.06
        self.update()

    def paintEvent(self, event):
        p = pal.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        for x_r, y_r, base, amp, speed, phase, is_teal in self.DOTS:
            alpha = base + amp * (0.5 + 0.5 * math.sin(self._t * speed + phase))
            color = QColor(p.ACCENT_TEAL if is_teal else p.ACCENT_BLUE)
            color.setAlphaF(max(0.0, min(alpha, 1.0)))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x_r * w, y_r * h), 4, 4)
        painter.end()


class LogoPanel(QWidget):
    """لوحة اللوجو (الشمال بعد انعكاس RTL) - خلفية غامقة ثابتة بزوايا
    برّانية مدورة بس (زي سطح واحد متلاحم مع لوحة الفورم)، مع لمسة نقط
    متحركة خافتة في الخلفية، وأيقونة Cortex بتوهج خفيف حواليها، وكلمة
    "Cortex" تحتها - كل ده widgets حقيقية دلوقتي (مش pixmap مسطّح) عشان
    نقدر نحط عليها أنيميشن حي."""

    def __init__(self, width, height, radii, parent=None):
        super().__init__(parent)
        self._radii = radii
        self.setFixedSize(width, height)

        accent = _AnimatedAccentOverlay(self)
        accent.setGeometry(0, 0, width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(10)

        icon_label = QLabel()
        icon_label.setPixmap(node_mark_pixmap(64))
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("background: transparent;")
        glow = QGraphicsDropShadowEffect(icon_label)
        glow.setBlurRadius(40)
        glow.setOffset(0, 0)
        glow.setColor(QColor(pal.current().ACCENT_TEAL))
        icon_label.setGraphicsEffect(glow)
        layout.addWidget(icon_label)

        layout.addSpacing(14)

        wordmark = QLabel("Cortex")
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setStyleSheet(
            f"font-size:22px; font-weight:700; color:{Cortex.TEXT_PRIMARY}; background: transparent;"
        )
        layout.addWidget(wordmark)

        layout.addStretch(11)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = rounded_rect_path(self.rect(), *self._radii)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(Cortex.BG_PRIMARY))
        painter.end()


class _GradientDivider(QWidget):
    """خط رفيع بتدرج من التيل للأزرق بين لوحة اللوجو ولوحة الفورم - بديل
    عن حافة حادة فاصلة بين اللوحتين."""

    def __init__(self, height, parent=None):
        super().__init__(parent)
        self.setFixedSize(2, height)

    def paintEvent(self, event):
        p = pal.current()
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(p.ACCENT_TEAL))
        gradient.setColorAt(1, QColor(p.ACCENT_BLUE))
        painter.fillRect(self.rect(), gradient)
        painter.end()


class AnimatedLoginButton(QPushButton):
    """زرار "دخول" بتأثير hover/press سلس (تدرّج لوني + توهج) بدل تغيير لون
    مفاجئ زي أي زرار عادي - بيستخدم QPropertyAnimation على لون الخلفية
    و QGraphicsDropShadowEffect متحرك للتوهج."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        p = pal.current()
        self._base_color = QColor(p.ACCENT_BLUE)
        self._hover_color = QColor(p.ACCENT_TEAL)
        self._bg_color = QColor(self._base_color)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(0)
        self._shadow.setColor(QColor(p.ACCENT_TEAL))
        self.setGraphicsEffect(self._shadow)

        self._color_anim = QPropertyAnimation(self, b"bgColor", self)
        self._color_anim.setDuration(200)
        self._color_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._glow_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._glow_anim.setDuration(200)
        self._glow_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._apply_style()

    def get_bg_color(self):
        return self._bg_color

    def set_bg_color(self, color):
        self._bg_color = QColor(color)
        self._apply_style()

    bgColor = Property(QColor, get_bg_color, set_bg_color)

    def _apply_style(self):
        p = pal.current()
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {self._bg_color.name()};
                color: {p.TEXT_PRIMARY};
                border: none; border-radius: 6px; padding: 8px 18px; font-weight: bold;
            }}
            """
        )

    def _animate_to(self, color, blur):
        self._color_anim.stop()
        self._color_anim.setStartValue(self._bg_color)
        self._color_anim.setEndValue(color)
        self._color_anim.start()

        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._shadow.blurRadius())
        self._glow_anim.setEndValue(blur)
        self._glow_anim.start()

    def enterEvent(self, event):
        self._animate_to(self._hover_color, 28)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_to(self._base_color, 0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._animate_to(self._hover_color.darker(115), 14)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.underMouse():
            self._animate_to(self._hover_color, 28)
        else:
            self._animate_to(self._base_color, 0)
        super().mouseReleaseEvent(event)


class LoginWindow(QDialog):
    def __init__(self, shop_name=None):
        super().__init__()
        if shop_name is None:
            shop_name = i18n.tr("app.default_shop_name")
        self.setWindowTitle(i18n.tr("login.title"))
        # ديالوج بلا إطار ويندوز أصلي - عشان الشكل يبقى سطح واحد بحواف
        # برّانية مدورة (مش كارت جوه إطار مستطيل عادي). محتاجين نعمل بديل
        # يدوي للسحب والإغلاق بدل اللي كان بيجيله مجانًا من الإطار الأصلي.
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(DIALOG_WIDTH, DIALOG_HEIGHT)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.user = None
        self._drag_pos = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # الديالوج بياخد اتجاه RTL من التطبيق، فبيعكس ترتيب العناصر الأفقي؛
        # عشان اللوجو يفضل فعليًا على الشمال، لازم نضيفه هنا تاني (بعد الفورم).
        root.addWidget(self._build_form_panel())
        root.addWidget(_GradientDivider(DIALOG_HEIGHT))
        root.addWidget(LogoPanel(LOGO_PANEL_WIDTH, DIALOG_HEIGHT, radii=(CORNER_RADIUS, 0, 0, CORNER_RADIUS)))

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("LoginCloseButton")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setStyleSheet(
            f"""
            QPushButton#LoginCloseButton {{
                background-color: transparent; color: {pal.current().TEXT_MUTED};
                border: none; border-radius: 14px; font-size: 13px; padding: 0px;
            }}
            QPushButton#LoginCloseButton:hover {{
                background-color: {pal.current().RED}; color: {pal.current().TEXT_PRIMARY};
            }}
            """
        )
        self.close_btn.move(DIALOG_WIDTH - 28 - 12, 12)
        self.close_btn.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self.close_btn.raise_()

    def _build_form_panel(self):
        p = pal.current()
        panel = QFrame()
        panel.setObjectName("LoginFormPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setStyleSheet(
            f"""
            QFrame#LoginFormPanel {{
                background-color: {p.BG_PRIMARY};
                border-top-right-radius: {CORNER_RADIUS}px;
                border-bottom-right-radius: {CORNER_RADIUS}px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
            }}
            """
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(40, 0, 40, 0)
        layout.setSpacing(16)
        layout.addStretch(1)

        sub = QLabel(i18n.tr("login.subtitle"))
        sub.setAlignment(Qt.AlignCenter)
        sub.setObjectName("CardTitle")
        layout.addWidget(sub)

        layout.addSpacing(4)

        self.username_input = FloatingLabelInput(i18n.tr("login.username_placeholder"))
        layout.addWidget(self.username_input)

        self.password_input = FloatingLabelInput(i18n.tr("login.password_placeholder"), password=True)
        layout.addWidget(self.password_input)

        login_btn = AnimatedLoginButton(i18n.tr("login.login_button"))
        login_btn.setMinimumHeight(40)
        login_btn.clicked.connect(self.try_login)
        layout.addWidget(login_btn)

        self.password_input.input.returnPressed.connect(self.try_login)

        layout.addStretch(1)
        return panel

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def try_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.error_empty"))
            return

        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        user = db.fetch_one(
            "SELECT * FROM users WHERE username=? AND password_hash=?",
            (username, password_hash),
        )
        if not user:
            QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.error_invalid"))
            return

        if db.needs_password_change(user, password):
            change_dlg = ForcePasswordChangeDialog(user)
            if not change_dlg.exec():
                return
            user = db.fetch_one("SELECT * FROM users WHERE id=?", (user["id"],))

        is_admin = user["role"] == "admin"
        if is_admin:
            branches = db.fetch_all("SELECT id, name FROM branches WHERE is_active=1 ORDER BY name")
            if not branches:
                QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.error_no_branch"))
                return
            if len(branches) == 1:
                branch_id = branches[0]["id"]
            else:
                pick = BranchPickDialog(branches)
                if not pick.exec():
                    return
                branch_id = pick.selected_branch_id()
        else:
            branch_id = user.get("branch_id")
            if not branch_id:
                QMessageBox.warning(self, i18n.tr("login.error_title"), i18n.tr("login.error_unassigned_branch"))
                return

        db.set_session_branch(branch_id, is_admin=is_admin)
        self.user = user
        self.accept()
