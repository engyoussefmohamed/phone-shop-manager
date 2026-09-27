import datetime

from PySide6.QtCore import Qt, QTimer, QRectF, QDate
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDialog, QComboBox, QDateEdit, QCheckBox, QScrollArea, QFormLayout
)

from app import database as db
from app import i18n
from app.utils.branding import draw_node_mark
from app.utils.widgets import Card, fmt_money, warn

PERIOD_TODAY = "today"
PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_CUSTOM = "custom"

_PERIOD_LABEL_KEYS = {
    PERIOD_TODAY: "dashboard.summary.period_today",
    PERIOD_WEEK: "dashboard.summary.period_week",
    PERIOD_MONTH: "dashboard.summary.period_month",
    PERIOD_CUSTOM: "dashboard.summary.period_custom",
}


def _period_range(period, custom_from=None, custom_to=None):
    """بترجع (date_from, date_to) كنص "YYYY-MM-DD" حسب الفترة المختارة."""
    today = datetime.date.today()
    if period == PERIOD_TODAY:
        return today.isoformat(), today.isoformat()
    if period == PERIOD_WEEK:
        return (today - datetime.timedelta(days=6)).isoformat(), today.isoformat()
    if period == PERIOD_CUSTOM and custom_from and custom_to:
        return custom_from, custom_to
    # الشهر - وكمان الافتراضي لو الفترة المخصصة لسه مش متحددة.
    return today.replace(day=1).isoformat(), today.isoformat()


class SummaryEditorDialog(QDialog):
    """ديالوج "تحرير" ملخص لوحة التحكم - اختيار الفترة الزمنية اللي بتتحكم
    في أرقام الكاردت (الإيرادات/المصروفات/الربح/المشتريات - أما المخزون
    والديون المعلقة فأرقام رصيد آني مش بتتفلتر بفترة)، وقائمة بكل كارت مع
    خيار إخفائه (يتحول لـ •••• بدل الرقم الحقيقي، من غير ما يغيّر أي بيانات
    فعلية في قاعدة البيانات - بس إخفاء العرض)."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setWindowTitle(i18n.tr("dashboard.summary.dialog_title"))
        self.resize(420, 480)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(i18n.tr("dashboard.summary.period_section_title")))
        self.period_combo = QComboBox()
        for key in (PERIOD_TODAY, PERIOD_WEEK, PERIOD_MONTH, PERIOD_CUSTOM):
            self.period_combo.addItem(i18n.tr(_PERIOD_LABEL_KEYS[key]), key)
        idx = self.period_combo.findData(view.period)
        self.period_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.period_combo.currentIndexChanged.connect(self._update_custom_visibility)
        layout.addWidget(self.period_combo)

        self._custom_widget = QWidget()
        custom_form = QFormLayout(self._custom_widget)
        custom_form.setContentsMargins(0, 0, 0, 0)
        today = QDate.currentDate()
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(QDate.fromString(view.custom_from, "yyyy-MM-dd") if view.custom_from else today)
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(QDate.fromString(view.custom_to, "yyyy-MM-dd") if view.custom_to else today)
        custom_form.addRow(i18n.tr("dashboard.summary.from_label"), self.from_date)
        custom_form.addRow(i18n.tr("dashboard.summary.to_label"), self.to_date)
        layout.addWidget(self._custom_widget)
        self._update_custom_visibility()

        layout.addSpacing(10)
        layout.addWidget(QLabel(i18n.tr("dashboard.summary.cards_section_title")))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        self.checkboxes = {}
        for key, title in view.card_definitions():
            cb = QCheckBox(title)
            cb.setChecked(key in view.hidden_cards)
            inner_layout.addWidget(cb)
            self.checkboxes[key] = cb
        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        save_btn = QPushButton(i18n.tr("dashboard.summary.save_button"))
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    def _update_custom_visibility(self):
        self._custom_widget.setVisible(self.period_combo.currentData() == PERIOD_CUSTOM)

    def _save(self):
        period = self.period_combo.currentData()
        custom_from = custom_to = None
        if period == PERIOD_CUSTOM:
            custom_from = self.from_date.date().toString("yyyy-MM-dd")
            custom_to = self.to_date.date().toString("yyyy-MM-dd")
            if custom_from > custom_to:
                warn(self, i18n.tr("dashboard.summary.error_invalid_range"))
                return

        hidden = {key for key, cb in self.checkboxes.items() if cb.isChecked()}
        self.view.apply_summary_settings(period, custom_from, custom_to, hidden)
        self.accept()


class DashboardView(QWidget):
    def __init__(self, user, goto_callback):
        super().__init__()
        self.user = user
        # السوبر فايزر عنده صلاحيات أوسع من الموظف (تقارير/خزنة/مشتريات..)
        # فبيشوف نفس مجموعة كاردت الأدمن الكاملة، مش مجموعة الموظف المختصرة.
        self.show_full_dashboard = user["role"] in ("admin", "supervisor")
        self.goto_callback = goto_callback

        self.hidden_cards = db.get_dashboard_hidden_cards(user["id"])
        self.quick_hide = False
        self.period = PERIOD_MONTH
        self.custom_from = None
        self.custom_to = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        header_row = QHBoxLayout()
        title = QLabel(i18n.tr("nav.dashboard"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        header_row.addWidget(title)
        header_row.addStretch()

        summary_label = QLabel(i18n.tr("dashboard.summary.label"))
        summary_label.setStyleSheet("font-size:15px; font-weight:600;")
        header_row.addWidget(summary_label)

        self.period_hint = QLabel()
        self.period_hint.setObjectName("CardTitle")
        header_row.addWidget(self.period_hint)

        self.quick_hide_btn = QPushButton("🔒")
        self.quick_hide_btn.setFixedWidth(34)
        self.quick_hide_btn.setCursor(Qt.PointingHandCursor)
        self.quick_hide_btn.setToolTip(i18n.tr("dashboard.summary.quick_hide_tooltip_on"))
        self.quick_hide_btn.clicked.connect(self.toggle_quick_hide)
        header_row.addWidget(self.quick_hide_btn)

        edit_btn = QPushButton(i18n.tr("dashboard.summary.edit_button"))
        edit_btn.clicked.connect(self.open_summary_editor)
        header_row.addWidget(edit_btn)

        outer.addLayout(header_row)

        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        outer.addLayout(self.grid)
        outer.addStretch()

        self.cards = {}
        self._build_cards()
        self._update_period_hint()
        self.refresh()

        # تحديث تلقائي كل ما الشاشة تتفتح تاني
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(15000)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        size = 340
        margin = 16
        rect = QRectF(self.width() - size - margin, self.height() - size - margin, size, size)
        draw_node_mark(painter, rect, opacity=0.05)
        painter.end()

    def _card_specs(self):
        """(key, title, variant, target_page, target_tab) - قائمة واحدة
        بتتبنى منها الكاردت وقائمة الإخفاء في ديالوج التحرير مع بعض، عشان
        الاتنين يفضلوا متوافقين دايمًا من غير تكرار."""
        if self.show_full_dashboard:
            return [
                ("revenue", i18n.tr("dashboard.revenue"), "primary", "sales", None),
                ("expenses", i18n.tr("dashboard.expenses"), "negative", "expenses", None),
                ("profit", i18n.tr("dashboard.profit"), "primary", "reports", None),
                ("stock", i18n.tr("dashboard.stock"), "info", "inventory", None),
                ("stock_value", i18n.tr("dashboard.stock_value"), "info", "inventory", None),
                ("stock_cost", i18n.tr("dashboard.stock_cost"), "info", "inventory", None),
                ("owed_to_me", i18n.tr("dashboard.owed_to_me"), "primary", "debts", "owed_to_me"),
                ("i_owe", i18n.tr("dashboard.i_owe"), "negative", "debts", "i_owe"),
                ("purchases", i18n.tr("dashboard.purchases"), "info", "purchases", None),
            ]
        return [
            ("stock", i18n.tr("dashboard.stock"), "info", "inventory", None),
            ("stock_value", i18n.tr("dashboard.stock_value"), "info", "inventory", None),
            ("owed_to_me", i18n.tr("dashboard.owed_to_me_employee"), "primary", "debts", "owed_to_me"),
        ]

    def card_definitions(self):
        return [(key, title) for key, title, *_ in self._card_specs()]

    def _build_cards(self):
        for i, (key, title, variant, target_page, target_tab) in enumerate(self._card_specs()):
            row, col = divmod(i, 3)
            card = Card(title, "...", variant=variant)
            if target_page:
                card.clicked.connect(lambda tp=target_page, tt=target_tab: self.goto_callback(tp, tt))
            self.grid.addWidget(card, row, col)
            self.cards[key] = card

    def _current_range(self):
        return _period_range(self.period, self.custom_from, self.custom_to)

    def _update_period_hint(self):
        if self.period == PERIOD_CUSTOM and self.custom_from and self.custom_to:
            text = f"{self.custom_from} → {self.custom_to}"
        else:
            text = i18n.tr(_PERIOD_LABEL_KEYS.get(self.period, "dashboard.summary.period_month"))
        self.period_hint.setText(i18n.tr("dashboard.summary.period_prefix", period=text))

    def refresh(self):
        date_from, date_to = self._current_range()
        s = db.dashboard_summary(date_from, date_to)
        values = {
            "revenue": fmt_money(s["revenue"]),
            "expenses": fmt_money(s["expenses"]),
            "profit": fmt_money(s["profit"]),
            "stock": str(int(s["stock_qty"])),
            "stock_value": fmt_money(s["stock_value_sale"]),
            "stock_cost": fmt_money(s["stock_value_cost"]),
            "owed_to_me": fmt_money(s["owed_to_me"]),
            "i_owe": fmt_money(s["i_owe"]),
            "purchases": fmt_money(s["purchases_cost"]),
        }
        placeholder = i18n.tr("dashboard.hidden_placeholder")
        for key, card in self.cards.items():
            if self.quick_hide or key in self.hidden_cards:
                card.set_value(placeholder)
            else:
                card.set_value(values.get(key, "-"))

    def toggle_quick_hide(self):
        """تبديل سريع لوضع إخفاء كل الأرقام فورًا (زي شاشة خصوصية) - من غير
        ما يحتاج يفتح ديالوج التحرير، وده منفصل تمامًا عن قائمة الكاردت
        المخفية المحفوظة للمستخدم (ده تبديل لحظي بس لجلسة الشغل الحالية)."""
        self.quick_hide = not self.quick_hide
        self.quick_hide_btn.setToolTip(
            i18n.tr(
                "dashboard.summary.quick_hide_tooltip_off" if self.quick_hide
                else "dashboard.summary.quick_hide_tooltip_on"
            )
        )
        self.refresh()

    def open_summary_editor(self):
        dlg = SummaryEditorDialog(self)
        dlg.exec()

    def apply_summary_settings(self, period, custom_from, custom_to, hidden_keys):
        self.period = period
        self.custom_from = custom_from
        self.custom_to = custom_to
        self.hidden_cards = hidden_keys
        db.set_dashboard_hidden_cards(self.user["id"], hidden_keys)
        self._update_period_hint()
        self.refresh()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
