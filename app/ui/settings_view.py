import hashlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTabWidget, QFormLayout, QFileDialog, QComboBox, QApplication
)

from app import database as db
from app import db_config
from app import i18n
from app.licensing import hwid, license_manager
from app.ui.db_setup_dialog import DbSetupDialog
from app.ui.license_gate import LicenseGateDialog
from app.utils import palette
from app.utils.styles import get_stylesheet
from app.utils.widgets import build_table, fill_row, info, warn


class SettingsView(QWidget):
    def __init__(self, restart_ui_callback=None):
        super().__init__()
        self.restart_ui_callback = restart_ui_callback
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("nav.settings"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_shop_tab(), i18n.tr("settings.tab.shop"))
        tabs.addTab(self._build_branches_tab(), i18n.tr("settings.tab.branches"))
        tabs.addTab(self._build_connection_tab(), i18n.tr("settings.tab.connection"))
        tabs.addTab(self._build_backup_tab(), i18n.tr("settings.tab.backup"))
        tabs.addTab(self._build_license_tab(), i18n.tr("settings.tab.license"))
        tabs.addTab(self._build_users_tab(), i18n.tr("settings.tab.users"))
        tabs.addTab(self._build_appearance_tab(), i18n.tr("settings.tab.appearance"))
        layout.addWidget(tabs)

    # ---------------- Shop info ----------------

    def _build_shop_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.shop_name_input = QLineEdit(self._get("shop_name"))
        form.addRow(i18n.tr("settings.field.shop_name"), self.shop_name_input)
        self.shop_phone_input = QLineEdit(self._get("shop_phone"))
        form.addRow(i18n.tr("settings.field.shop_phone"), self.shop_phone_input)
        self.shop_address_input = QLineEdit(self._get("shop_address"))
        form.addRow(i18n.tr("settings.field.shop_address"), self.shop_address_input)

        self.monthly_target_input = QLineEdit(self._get("monthly_sales_target"))
        self.monthly_target_input.setPlaceholderText(i18n.tr("settings.monthly_target_placeholder"))
        form.addRow(i18n.tr("settings.field.monthly_target"), self.monthly_target_input)

        save_btn = QPushButton(i18n.tr("common.save"))
        save_btn.clicked.connect(self.save_shop_info)
        form.addRow(save_btn)
        return w

    def _get(self, key, default=""):
        row = db.fetch_one("SELECT value FROM settings WHERE setting_key=?", (key,))
        return row["value"] if row and row["value"] else default

    def save_shop_info(self):
        target_text = self.monthly_target_input.text().strip()
        if target_text:
            try:
                float(target_text)
            except ValueError:
                warn(self, i18n.tr("settings.error_target_not_number"))
                return
        db.execute("UPDATE settings SET value=? WHERE setting_key='shop_name'", (self.shop_name_input.text().strip(),))
        db.execute("UPDATE settings SET value=? WHERE setting_key='shop_phone'", (self.shop_phone_input.text().strip(),))
        db.execute("UPDATE settings SET value=? WHERE setting_key='shop_address'", (self.shop_address_input.text().strip(),))
        db.execute("UPDATE settings SET value=? WHERE setting_key='monthly_sales_target'", (target_text,))
        info(self, i18n.tr("settings.notice_shop_saved"))

    # ---------------- Branches (الفروع) ----------------

    def _build_branches_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(i18n.tr("settings.branches_hint")))

        self.branches_table = build_table([
            i18n.tr("settings.col.branch_name"), i18n.tr("settings.col.branch_address"),
            i18n.tr("settings.col.branch_phone"), i18n.tr("settings.col.branch_status"),
        ])
        v.addWidget(self.branches_table)

        form = QHBoxLayout()
        self.new_branch_name = QLineEdit()
        self.new_branch_name.setPlaceholderText(i18n.tr("settings.new_branch_name_placeholder"))
        form.addWidget(self.new_branch_name)
        self.new_branch_address = QLineEdit()
        self.new_branch_address.setPlaceholderText(i18n.tr("settings.address_optional_placeholder"))
        form.addWidget(self.new_branch_address)
        self.new_branch_phone = QLineEdit()
        self.new_branch_phone.setPlaceholderText(i18n.tr("settings.phone_optional_placeholder"))
        form.addWidget(self.new_branch_phone)
        add_branch_btn = QPushButton(i18n.tr("settings.add_branch_button"))
        add_branch_btn.clicked.connect(self.add_branch)
        form.addWidget(add_branch_btn)
        v.addLayout(form)

        self.refresh_branches()
        return w

    def refresh_branches(self):
        rows = db.fetch_all("SELECT * FROM branches ORDER BY name")
        self.branches_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            status_text = i18n.tr("settings.branch_active" if r["is_active"] else "settings.branch_inactive")
            fill_row(self.branches_table, i, [
                r["name"], r["address"] or "-", r["phone"] or "-", status_text,
            ])
        self._branches_cache = rows

    def add_branch(self):
        name = self.new_branch_name.text().strip()
        if not name:
            warn(self, i18n.tr("settings.error_no_branch_name"))
            return
        try:
            db.create_branch(name, self.new_branch_address.text().strip(), self.new_branch_phone.text().strip())
        except Exception as e:
            warn(self, i18n.tr("settings.error_add_branch_failed", error=e))
            return
        self.new_branch_name.clear()
        self.new_branch_address.clear()
        self.new_branch_phone.clear()
        self.refresh_branches()
        info(self, i18n.tr("settings.notice_branch_added"))

    # ---------------- Connection (الاتصال بقاعدة البيانات) ----------------

    def _build_connection_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        cfg = db_config.load_config()
        self.conn_info_label = QLabel(self._connection_summary(cfg))
        self.conn_info_label.setWordWrap(True)
        v.addWidget(self.conn_info_label)

        edit_btn = QPushButton(i18n.tr("settings.edit_connection_button"))
        edit_btn.clicked.connect(self.edit_connection)
        v.addWidget(edit_btn)
        v.addStretch()
        return w

    def _connection_summary(self, cfg):
        auth = i18n.tr("settings.windows_auth") if cfg.get("auth") == "windows" else i18n.tr("settings.sql_user", user=cfg.get("username", "-"))
        return i18n.tr(
            "settings.connection_summary",
            server=cfg.get("server", "-"), database=cfg.get("database", "-"), auth=auth,
        )

    def edit_connection(self):
        dlg = DbSetupDialog(self)
        if dlg.exec():
            self.conn_info_label.setText(self._connection_summary(db_config.load_config()))
            info(self, i18n.tr("settings.notice_connection_saved"))

    # ---------------- Backup ----------------

    def _build_backup_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(i18n.tr("settings.backup_hint")))
        path_row = QHBoxLayout()
        self.backup_path_input = QLineEdit()
        self.backup_path_input.setPlaceholderText(i18n.tr("settings.backup_path_placeholder"))
        path_row.addWidget(self.backup_path_input)
        backup_btn = QPushButton(i18n.tr("settings.export_backup_button"))
        backup_btn.clicked.connect(self.do_backup)
        path_row.addWidget(backup_btn)
        v.addLayout(path_row)

        v.addSpacing(10)
        v.addWidget(QLabel(i18n.tr("settings.restore_hint")))
        v.addStretch()
        return w

    def do_backup(self):
        path = self.backup_path_input.text().strip()
        if not path:
            warn(self, i18n.tr("settings.error_no_backup_path"))
            return
        cfg = db_config.load_config()
        db_name = cfg.get("database", "PhoneShopManager")
        try:
            db.execute_autocommit(f"BACKUP DATABASE [{db_name}] TO DISK = ?", (path,))
        except Exception as e:
            warn(self, i18n.tr("settings.error_backup_failed", error=e))
            return
        info(self, i18n.tr("settings.notice_backup_saved", path=path))

    # ---------------- License ----------------

    def _build_license_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        valid, data, reason = license_manager.get_current_license_status()
        status_text = i18n.tr("settings.license_active" if valid else "settings.license_inactive")
        v.addWidget(QLabel(i18n.tr("settings.license_status", status=status_text)))
        v.addWidget(QLabel(i18n.tr("settings.license_details", reason=reason)))
        if valid and data:
            v.addWidget(QLabel(i18n.tr("settings.license_owner", customer=data.get("customer", "-"))))

        v.addSpacing(10)
        v.addWidget(QLabel(i18n.tr("settings.license_activate_hint")))
        export_btn = QPushButton(i18n.tr("settings.export_license_button"))
        export_btn.clicked.connect(self.export_license_request)
        v.addWidget(export_btn)

        v.addSpacing(6)
        v.addWidget(QLabel(i18n.tr("settings.device_code_hint")))
        code_box = QLineEdit(hwid.get_device_code())
        code_box.setReadOnly(True)
        v.addWidget(code_box)

        activate_btn = QPushButton(i18n.tr("settings.import_license_button"))
        activate_btn.clicked.connect(self.open_license_dialog)
        v.addWidget(activate_btn)
        v.addStretch()
        return w

    def export_license_request(self):
        default_name = f"طلب_ترخيص_{hwid.get_device_code()}.txt"
        path, _ = QFileDialog.getSaveFileName(self, i18n.tr("settings.save_license_request_title"), default_name, "Text Files (*.txt)")
        if not path:
            return
        shop_name = self._get("shop_name")
        hwid.export_request_file(path, shop_name=shop_name)
        info(self, i18n.tr("settings.notice_license_request_saved"))

    def open_license_dialog(self):
        dlg = LicenseGateDialog(reason=i18n.tr("settings.update_license_reason"))
        dlg.exec()

    # ---------------- Users / passwords ----------------

    def _build_users_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.user_combo = QComboBox()
        self._reload_user_combo()
        self.user_combo.currentIndexChanged.connect(self._load_selected_user)
        form.addRow(i18n.tr("settings.field.user"), self.user_combo)

        self.username_input = QLineEdit()
        form.addRow(i18n.tr("settings.field.username"), self.username_input)

        self.full_name_input = QLineEdit()
        form.addRow(i18n.tr("settings.field.full_name"), self.full_name_input)

        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input.setPlaceholderText(i18n.tr("settings.new_password_placeholder"))
        form.addRow(i18n.tr("settings.field.new_password"), self.new_password_input)

        self.role_combo = QComboBox()
        self.role_combo.addItem(i18n.tr("settings.role_admin"), "admin")
        self.role_combo.addItem(i18n.tr("settings.role_supervisor"), "supervisor")
        self.role_combo.addItem(i18n.tr("settings.role_employee"), "employee")
        form.addRow(i18n.tr("settings.field.role"), self.role_combo)

        self.user_branch_combo = QComboBox()
        self.user_branch_combo.addItem(i18n.tr("settings.no_fixed_branch"), None)
        for b in db.fetch_all("SELECT id, name FROM branches ORDER BY name"):
            self.user_branch_combo.addItem(b["name"], b["id"])
        form.addRow(i18n.tr("settings.field.user_branch"), self.user_branch_combo)

        save_btn = QPushButton(i18n.tr("settings.save_changes_button"))
        save_btn.clicked.connect(self.save_user_changes)
        form.addRow(save_btn)

        self._load_selected_user()
        return w

    def _reload_user_combo(self):
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        for u in db.fetch_all("SELECT username, full_name FROM users ORDER BY id"):
            self.user_combo.addItem(f"{u['full_name']} ({u['username']})", u["username"])
        self.user_combo.blockSignals(False)

    def _load_selected_user(self):
        username = self.user_combo.currentData()
        if not username:
            return
        user = db.fetch_one("SELECT * FROM users WHERE username=?", (username,))
        if not user:
            return
        self.username_input.setText(user["username"])
        self.full_name_input.setText(user["full_name"] or "")
        self.new_password_input.clear()
        role_idx = self.role_combo.findData(user.get("role"))
        self.role_combo.setCurrentIndex(role_idx if role_idx >= 0 else 0)
        idx = self.user_branch_combo.findData(user.get("branch_id"))
        self.user_branch_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def save_user_changes(self):
        old_username = self.user_combo.currentData()
        if not old_username:
            return
        new_username = self.username_input.text().strip()
        full_name = self.full_name_input.text().strip()
        new_password = self.new_password_input.text()

        if not new_username:
            warn(self, i18n.tr("settings.error_username_empty"))
            return
        if not full_name:
            warn(self, i18n.tr("settings.error_fullname_empty"))
            return
        if new_password and len(new_password) < 4:
            warn(self, i18n.tr("settings.error_password_too_short"))
            return

        if new_username != old_username:
            exists = db.fetch_one("SELECT id FROM users WHERE username=?", (new_username,))
            if exists:
                warn(self, i18n.tr("settings.error_username_taken"))
                return

        new_role = self.role_combo.currentData()
        branch_id = self.user_branch_combo.currentData()
        if new_role in ("employee", "supervisor") and branch_id is None:
            warn(self, i18n.tr("settings.error_employee_needs_branch"))
            return

        current = db.fetch_one("SELECT role FROM users WHERE username=?", (old_username,))
        if current and current["role"] == "admin" and new_role != "admin":
            admin_count = db.fetch_one("SELECT COUNT(*) c FROM users WHERE role='admin'")["c"]
            if admin_count <= 1:
                warn(self, i18n.tr("settings.error_last_admin"))
                return

        try:
            db.execute(
                "UPDATE users SET username=?, full_name=?, branch_id=?, role=? WHERE username=?",
                (new_username, full_name, branch_id, new_role, old_username),
            )
        except Exception as e:
            warn(self, i18n.tr("settings.error_save_failed", error=e))
            return

        if new_password:
            password_hash = hashlib.sha256(new_password.encode("utf-8")).hexdigest()
            db.execute(
                "UPDATE users SET password_hash=?, must_change_password=0 WHERE username=?",
                (password_hash, new_username),
            )

        info(self, i18n.tr("settings.notice_user_saved"))
        self._reload_user_combo()
        idx = self.user_combo.findData(new_username)
        if idx >= 0:
            self.user_combo.setCurrentIndex(idx)
        self._load_selected_user()

    # ---------------- Appearance & language (المظهر واللغة) ----------------

    THEME_OPTIONS = [("غامق (Dark)", "dark"), ("فاتح (Light)", "light")]
    LANGUAGE_OPTIONS = [("العربية", "ar"), ("English", "en")]

    def _build_appearance_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.theme_combo = QComboBox()
        for label, value in self.THEME_OPTIONS:
            self.theme_combo.addItem(label, value)
        idx = self.theme_combo.findData(self._get("theme", "dark"))
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(i18n.tr("settings.field.theme"), self.theme_combo)

        self.language_combo = QComboBox()
        for label, value in self.LANGUAGE_OPTIONS:
            self.language_combo.addItem(label, value)
        idx = self.language_combo.findData(self._get("language", "ar"))
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(i18n.tr("settings.field.language"), self.language_combo)

        hint = QLabel(i18n.tr("settings.appearance_hint"))
        hint.setObjectName("CardTitle")
        form.addRow(hint)

        save_btn = QPushButton(i18n.tr("settings.save_apply_button"))
        save_btn.clicked.connect(self.save_appearance)
        form.addRow(save_btn)
        return w

    def save_appearance(self):
        theme = self.theme_combo.currentData()
        language = self.language_combo.currentData()

        db.execute("UPDATE settings SET value=? WHERE setting_key='theme'", (theme,))
        db.execute("UPDATE settings SET value=? WHERE setting_key='language'", (language,))

        i18n.set_language(language)
        palette.set_theme(theme)
        app = QApplication.instance()
        app.setStyleSheet(get_stylesheet(theme))
        app.setLayoutDirection(Qt.RightToLeft if language == "ar" else Qt.LeftToRight)

        # الشاشة الحالية (الشريط الجانبي/الداشبورد/الكروت) اتبنيت بألوان
        # ونصوص الاختيار القديم - لازم تتبني تاني عشان كل حاجة (لوجو الكروت،
        # أيقونات الـ KPI، النصوص) تتحدث فورًا، من غير ما نقفل ونفتح البرنامج
        # كله من الأول (نفس نمط _switch_branch في main_window.py).
        if self.restart_ui_callback:
            self.restart_ui_callback()
            return

        info(self, i18n.tr("settings.notice_appearance_applied"))
