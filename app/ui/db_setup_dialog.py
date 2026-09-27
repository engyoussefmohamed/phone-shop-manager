"""
نافذة إعداد الاتصال بقاعدة بيانات SQL Server - بتظهر أول تشغيل للبرنامج
(أو لو إعدادات الاتصال المحفوظة بقت غلط)، وبتتاح كمان من شاشة الإعدادات
لو حبيت تغيّر السيرفر بعد كده (مثلاً لما تربط جهاز جديد على نفس القاعدة).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QPushButton,
    QHBoxLayout, QLabel, QMessageBox
)

from app import db_config
from app import i18n
from app.utils import palette as pal


class DbSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("db_setup.window_title"))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)

        hint = QLabel(i18n.tr("db_setup.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        cfg = db_config.load_config()

        self.server_input = QLineEdit(cfg.get("server", ""))
        self.server_input.setPlaceholderText(i18n.tr("db_setup.server_placeholder"))
        form.addRow(i18n.tr("db_setup.field.server"), self.server_input)

        self.port_input = QLineEdit(cfg.get("port", ""))
        self.port_input.setPlaceholderText(i18n.tr("db_setup.port_placeholder"))
        form.addRow(i18n.tr("db_setup.field.port"), self.port_input)

        self.database_input = QLineEdit(cfg.get("database", "PhoneShopManager"))
        form.addRow(i18n.tr("db_setup.field.database"), self.database_input)

        self.auth_combo = QComboBox()
        self.auth_combo.addItem(i18n.tr("db_setup.auth_sql"), "sql")
        self.auth_combo.addItem(i18n.tr("db_setup.auth_windows"), "windows")
        idx = self.auth_combo.findData(cfg.get("auth", "sql"))
        if idx >= 0:
            self.auth_combo.setCurrentIndex(idx)
        self.auth_combo.currentIndexChanged.connect(self._update_auth_fields)
        form.addRow(i18n.tr("db_setup.field.auth"), self.auth_combo)

        self.username_input = QLineEdit(cfg.get("username", ""))
        form.addRow(i18n.tr("db_setup.field.username"), self.username_input)

        self.password_input = QLineEdit(cfg.get("password", ""))
        self.password_input.setEchoMode(QLineEdit.Password)
        form.addRow(i18n.tr("db_setup.field.password"), self.password_input)

        layout.addLayout(form)
        self._update_auth_fields()

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        test_btn = QPushButton(i18n.tr("db_setup.test_button"))
        test_btn.clicked.connect(self.test_connection)
        buttons.addWidget(test_btn)

        buttons.addStretch()

        cancel_btn = QPushButton(i18n.tr("db_setup.cancel_button"))
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        save_btn = QPushButton(i18n.tr("db_setup.save_button"))
        save_btn.clicked.connect(self.save_and_continue)
        buttons.addWidget(save_btn)

        layout.addLayout(buttons)

    def _update_auth_fields(self):
        is_sql = self.auth_combo.currentData() == "sql"
        self.username_input.setEnabled(is_sql)
        self.password_input.setEnabled(is_sql)

    def _collect(self):
        return {
            "server": self.server_input.text().strip(),
            "port": self.port_input.text().strip(),
            "database": self.database_input.text().strip() or "PhoneShopManager",
            "auth": self.auth_combo.currentData(),
            "username": self.username_input.text().strip(),
            "password": self.password_input.text(),
        }

    def test_connection(self):
        cfg = self._collect()
        if not cfg["server"]:
            self.status_label.setText(i18n.tr("db_setup.error_enter_server_first"))
            return
        self.status_label.setText(i18n.tr("db_setup.testing"))
        self.status_label.repaint()
        ok, message = db_config.test_connection(cfg)
        if ok:
            self.status_label.setStyleSheet(f"color:{pal.current().ACCENT_TEAL};")
            self.status_label.setText("✔ " + message)
        else:
            self.status_label.setStyleSheet(f"color:{pal.current().RED};")
            self.status_label.setText(i18n.tr("db_setup.connection_failed", message=message))

    def save_and_continue(self):
        cfg = self._collect()
        if not cfg["server"]:
            QMessageBox.warning(self, i18n.tr("db_setup.error_title"), i18n.tr("db_setup.error_enter_server"))
            return
        if cfg["auth"] == "sql" and not cfg["username"]:
            QMessageBox.warning(self, i18n.tr("db_setup.error_title"), i18n.tr("db_setup.error_enter_username"))
            return

        ok, message = db_config.test_connection(cfg)
        if not ok:
            resp = QMessageBox.question(
                self, i18n.tr("db_setup.connection_failed_title"),
                i18n.tr("db_setup.connection_failed_question", message=message),
            )
            if resp != QMessageBox.Yes:
                return

        db_config.save_config(cfg)
        try:
            db_config.ensure_database_exists(cfg)
        except Exception as e:
            QMessageBox.warning(
                self, i18n.tr("db_setup.notice_title"),
                i18n.tr("db_setup.db_create_error", error=e),
            )
        self.accept()
