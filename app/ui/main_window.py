import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QStackedWidget, QButtonGroup, QStatusBar, QComboBox, QApplication
)

from app import database as db
from app import i18n

ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "app", "assets", "cortex_icon.ico",
)

# الترتيب الهرمي للصلاحيات: أدمن (كل حاجة) > سوبر فايزر (أوسع من الموظف،
# أقل من الأدمن) > موظف. كل شاشة في _get_modules() ليها min_role - أي رتبة
# مساوية أو أعلى منه تقدر توصلها.
ROLE_RANK = {"employee": 1, "supervisor": 2, "admin": 3}


class MainWindow(QMainWindow):
    def __init__(self, user, trial_days_left=None):
        super().__init__()
        self.user = user
        self.role = user["role"]
        self.is_admin = self.role == "admin"
        self.is_supervisor = self.role == "supervisor"
        self.trial_days_left = trial_days_left

        self.setWindowTitle(f"Cortex - {i18n.tr('app.title_suffix')}")
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1200, 760)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.stack = QStackedWidget()
        sidebar = self._build_sidebar()

        root_layout.addWidget(self.stack, 1)
        root_layout.addWidget(sidebar)

        self._build_status_bar(trial_days_left)

    # ---------------- Sidebar ----------------

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(4)

        shop_name = self._get_setting("shop_name", i18n.tr("app.default_shop_name"))
        title = QLabel(shop_name)
        title.setObjectName("ShopTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        if self.is_admin:
            role_text = i18n.tr("sidebar.role_admin")
        elif self.is_supervisor:
            role_text = i18n.tr("sidebar.role_supervisor")
        else:
            role_text = i18n.tr("sidebar.role_employee")
        role_label = QLabel(i18n.tr("sidebar.logged_in", name=self.user["full_name"], role=role_text))
        role_label.setObjectName("CardTitle")
        role_label.setAlignment(Qt.AlignCenter)
        role_label.setWordWrap(True)
        layout.addWidget(role_label)

        if self.is_admin:
            branches = db.fetch_all("SELECT id, name FROM branches WHERE is_active=1 ORDER BY name")
            if len(branches) > 1:
                current_branch_id, _ = db.get_session_branch()
                layout.addWidget(QLabel(i18n.tr("sidebar.current_branch")))
                branch_combo = QComboBox()
                for b in branches:
                    branch_combo.addItem(b["name"], b["id"])
                idx = branch_combo.findData(current_branch_id)
                if idx >= 0:
                    branch_combo.setCurrentIndex(idx)
                branch_combo.currentIndexChanged.connect(
                    lambda _i, combo=branch_combo: self._switch_branch(combo.currentData())
                )
                layout.addWidget(branch_combo)

        layout.addSpacing(12)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.page_index_by_key = {}
        self.button_by_key = {}

        modules = self._get_modules()
        first_done = False
        for key, label, min_role, factory in modules:
            if ROLE_RANK[self.role] < ROLE_RANK[min_role]:
                continue
            page = factory()
            page_index = self.stack.addWidget(page)
            self.page_index_by_key[key] = page_index

            btn = QPushButton(label)
            btn.setObjectName("SidebarButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=page_index: self.stack.setCurrentIndex(i))
            self.button_group.addButton(btn)
            self.button_by_key[key] = btn
            layout.addWidget(btn)

            if not first_done:
                btn.setChecked(True)
                self.stack.setCurrentIndex(page_index)
                first_done = True

        layout.addStretch()

        logout_btn = QPushButton(i18n.tr("sidebar.logout"))
        logout_btn.setObjectName("DangerButton")
        logout_btn.clicked.connect(self.close)
        layout.addWidget(logout_btn)

        return sidebar

    def _get_modules(self):
        """(key, label, min_role, factory_callable) - min_role هو أقل رتبة
        لازم تكون عندها عشان توصل الشاشة دي (شوف ROLE_RANK فوق)."""
        from app.ui.dashboard_view import DashboardView
        from app.ui.inventory_view import InventoryView
        from app.ui.sales_view import SalesView
        from app.ui.purchases_view import PurchasesView
        from app.ui.customers_view import CustomersView
        from app.ui.suppliers_view import SuppliersView
        from app.ui.debts_view import DebtsView
        from app.ui.employees_view import EmployeesView
        from app.ui.expenses_view import ExpensesView
        from app.ui.treasury_view import TreasuryView
        from app.ui.company_accounts_view import CompanyAccountsView
        from app.ui.maintenance_view import MaintenanceView
        from app.ui.reports_view import ReportsView
        from app.ui.settings_view import SettingsView

        can_view_all_debts = self.is_admin or self.is_supervisor

        return [
            ("dashboard", f"🏠 {i18n.tr('nav.dashboard')}", "employee", lambda: DashboardView(self.user, self.goto)),
            ("inventory", f"📱 {i18n.tr('nav.inventory')}", "employee", lambda: InventoryView(self.is_admin)),
            ("sales", f"🧾 {i18n.tr('nav.sales')}", "employee", lambda: SalesView(self.user)),
            ("purchases", f"📦 {i18n.tr('nav.purchases')}", "supervisor", lambda: PurchasesView(self.user)),
            ("customers", f"👤 {i18n.tr('nav.customers')}", "employee", lambda: CustomersView()),
            ("suppliers", f"🏭 {i18n.tr('nav.suppliers')}", "supervisor", lambda: SuppliersView()),
            ("debts", f"💳 {i18n.tr('nav.debts')}", "employee", lambda: DebtsView(can_view_all_debts)),
            ("maintenance", f"🔧 {i18n.tr('nav.maintenance')}", "employee", lambda: MaintenanceView()),
            ("employees", f"👥 {i18n.tr('nav.employees')}", "admin", lambda: EmployeesView()),
            ("expenses", f"💸 {i18n.tr('nav.expenses')}", "supervisor", lambda: ExpensesView()),
            ("treasury", f"🏦 {i18n.tr('nav.treasury')}", "supervisor", lambda: TreasuryView(self.user)),
            ("company_accounts", f"🏢 {i18n.tr('nav.company_accounts')}", "supervisor", lambda: CompanyAccountsView()),
            ("reports", f"📊 {i18n.tr('nav.reports')}", "supervisor", lambda: ReportsView(self.goto)),
            ("settings", f"⚙️ {i18n.tr('nav.settings')}", "admin", lambda: SettingsView(self.restart_ui)),
        ]

    def restart_ui(self):
        """بتتنادى بعد تغيير اللغة من شاشة الإعدادات - النافذة الحالية اتبنيت
        بنصوص اللغة القديمة، فبنبنيها من جديد بنفس نمط _switch_branch (تبديل
        النافذة من غير ما نقفل ونفتح البرنامج كله)."""
        new_win = MainWindow(self.user, trial_days_left=self.trial_days_left)
        new_win.showMaximized()
        QApplication.instance()._main_window_ref = new_win
        self.close()

    def _switch_branch(self, branch_id):
        if branch_id is None:
            return
        db.set_session_branch(branch_id, is_admin=True)
        new_win = MainWindow(self.user)
        new_win.showMaximized()
        # لازم نحتفظ بمرجع بايثون للنافذة الجديدة (على مستوى الـ QApplication)
        # عشان الـ garbage collector مايشيلهاش بمجرد ما المتغير المحلي هنا يخرج من الـ scope.
        QApplication.instance()._main_window_ref = new_win
        self.close()

    def goto(self, page_key, sub_target=None):
        index = self.page_index_by_key.get(page_key)
        if index is None:
            return
        self.stack.setCurrentIndex(index)
        btn = self.button_by_key.get(page_key)
        if btn:
            btn.setChecked(True)
        if sub_target is not None:
            page = self.stack.widget(index)
            if hasattr(page, "show_tab"):
                page.show_tab(sub_target)

    def _build_status_bar(self, trial_days_left):
        bar = QStatusBar()
        self.setStatusBar(bar)
        if trial_days_left is not None:
            bar.showMessage(i18n.tr("app.trial_notice", n=trial_days_left))

    @staticmethod
    def _get_setting(key, default=""):
        row = db.fetch_one("SELECT value FROM settings WHERE setting_key=?", (key,))
        return row["value"] if row and row["value"] else default
