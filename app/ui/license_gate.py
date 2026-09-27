from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFileDialog, QMessageBox, QApplication
)

from app import i18n
from app.licensing import hwid, license_manager


class LicenseGateDialog(QDialog):
    """
    بيظهر لما فترة التجربة تخلص ومفيش ترخيص مفعّل.
    بيوري للعميل كود الجهاز عشان يبعته للمطوّر، وبيدّيه خيار يستورد ملف
    الترخيص (.lic) اللي هيوصله بعد كده.
    """

    def __init__(self, reason=None):
        super().__init__()
        self.setWindowTitle(i18n.tr("license_gate.window_title"))
        self.setFixedSize(460, 460)
        self.activated = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel(i18n.tr("license_gate.title"))
        title.setStyleSheet("font-size:19px; font-weight:bold;")
        layout.addWidget(title)

        msg = QLabel(i18n.tr("license_gate.message", reason=reason or i18n.tr("license_gate.default_reason")))
        msg.setWordWrap(True)
        layout.addWidget(msg)

        export_btn = QPushButton(i18n.tr("license_gate.export_button"))
        export_btn.clicked.connect(self.export_request)
        layout.addWidget(export_btn)

        layout.addSpacing(6)
        code_label = QLabel(i18n.tr("license_gate.phone_code_hint"))
        code_label.setWordWrap(True)
        layout.addWidget(code_label)

        self.code_box = QLineEdit(hwid.get_device_code())
        self.code_box.setReadOnly(True)
        self.code_box.setAlignment(Qt.AlignCenter)
        self.code_box.setStyleSheet("font-size:18px; font-weight:bold; letter-spacing:2px;")
        layout.addWidget(self.code_box)

        copy_btn = QPushButton(i18n.tr("license_gate.copy_button"))
        copy_btn.setObjectName("SecondaryButton")
        copy_btn.clicked.connect(self.copy_code)
        layout.addWidget(copy_btn)

        layout.addSpacing(10)
        sep = QLabel(i18n.tr("license_gate.import_hint"))
        sep.setWordWrap(True)
        layout.addWidget(sep)

        import_btn = QPushButton(i18n.tr("license_gate.import_button"))
        import_btn.clicked.connect(self.import_license)
        layout.addWidget(import_btn)

        layout.addStretch()

        exit_btn = QPushButton(i18n.tr("license_gate.exit_button"))
        exit_btn.setObjectName("DangerButton")
        exit_btn.clicked.connect(self.reject)
        layout.addWidget(exit_btn)

    def copy_code(self):
        QApplication.clipboard().setText(self.code_box.text())
        QMessageBox.information(self, i18n.tr("license_gate.done_title"), i18n.tr("license_gate.notice_code_copied"))

    def export_request(self):
        default_name = f"طلب_ترخيص_{hwid.get_device_code()}.txt"
        path, _ = QFileDialog.getSaveFileName(self, i18n.tr("license_gate.save_request_title"), default_name, "Text Files (*.txt)")
        if not path:
            return
        hwid.export_request_file(path)
        QMessageBox.information(
            self, i18n.tr("license_gate.done_title"), i18n.tr("license_gate.notice_request_saved")
        )

    def import_license(self):
        path, _ = QFileDialog.getOpenFileName(self, i18n.tr("license_gate.open_file_title"), "", "License Files (*.lic)")
        if not path:
            return
        ok, reason = license_manager.install_license_file(path)
        if ok:
            self.activated = True
            QMessageBox.information(self, i18n.tr("license_gate.done_title"), i18n.tr("license_gate.notice_activated"))
            self.accept()
        else:
            QMessageBox.warning(self, i18n.tr("license_gate.activation_failed_title"), reason)
