from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QFormLayout, QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit, QDialogButtonBox
)

from app import database as db
from app import i18n
from app.utils.widgets import build_table, fill_row, confirm, warn, info, fmt_money

STATUS_KEYS = {
    "received": "maintenance.status.received",
    "in_progress": "maintenance.status.in_progress",
    "done": "maintenance.status.done",
    "delivered": "maintenance.status.delivered",
}


def status_label(status):
    return i18n.tr(STATUS_KEYS.get(status, status))


class MaintenanceDialog(QDialog):
    def __init__(self, ticket=None):
        super().__init__()
        self.ticket = ticket
        self.setWindowTitle(i18n.tr("maintenance.dialog.edit_title" if ticket else "maintenance.dialog.add_title"))
        self.setMinimumWidth(380)
        form = QFormLayout(self)

        self.customer_name_input = QLineEdit(ticket["customer_name"] if ticket else "")
        form.addRow(i18n.tr("maintenance.field.customer_name"), self.customer_name_input)

        self.customer_phone_input = QLineEdit(ticket["customer_phone"] if ticket and ticket.get("customer_phone") else "")
        form.addRow(i18n.tr("maintenance.field.customer_phone"), self.customer_phone_input)

        self.device_input = QLineEdit(ticket["device_name"] if ticket else "")
        form.addRow(i18n.tr("maintenance.field.device"), self.device_input)

        self.imei_input = QLineEdit(ticket["imei"] if ticket else "")
        form.addRow("IMEI:", self.imei_input)

        self.problem_input = QTextEdit(ticket["problem_description"] if ticket else "")
        self.problem_input.setFixedHeight(60)
        form.addRow(i18n.tr("maintenance.field.problem"), self.problem_input)

        self.status_input = QComboBox()
        for key, key_i18n in STATUS_KEYS.items():
            self.status_input.addItem(i18n.tr(key_i18n), key)
        if ticket:
            idx = self.status_input.findData(ticket["status"])
            if idx >= 0:
                self.status_input.setCurrentIndex(idx)
        form.addRow(i18n.tr("maintenance.field.status"), self.status_input)

        self.cost_input = QDoubleSpinBox()
        self.cost_input.setRange(0, 1_000_000)
        self.cost_input.setValue(ticket["cost"] if ticket else 0)
        form.addRow(i18n.tr("maintenance.field.cost"), self.cost_input)

        self.customer_price_input = QDoubleSpinBox()
        self.customer_price_input.setRange(0, 1_000_000)
        self.customer_price_input.setValue(ticket["customer_price"] if ticket and ticket.get("customer_price") else 0)
        form.addRow(i18n.tr("maintenance.field.customer_price"), self.customer_price_input)

        self.notes_input = QTextEdit(ticket["notes"] if ticket else "")
        self.notes_input.setFixedHeight(50)
        form.addRow(i18n.tr("common.notes"), self.notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(i18n.tr("common.save"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_data(self):
        return {
            "customer_name": self.customer_name_input.text().strip(),
            "customer_phone": self.customer_phone_input.text().strip(),
            "device_name": self.device_input.text().strip(),
            "imei": self.imei_input.text().strip(),
            "problem_description": self.problem_input.toPlainText().strip(),
            "status": self.status_input.currentData(),
            "cost": self.cost_input.value(),
            "customer_price": self.customer_price_input.value(),
            "notes": self.notes_input.toPlainText().strip(),
        }


class MaintenanceView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(i18n.tr("maintenance.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        add_btn = QPushButton(i18n.tr("maintenance.add_button"))
        add_btn.clicked.connect(self.add_ticket)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.table = build_table([
            i18n.tr("maintenance.col.customer"), i18n.tr("maintenance.col.customer_phone"),
            i18n.tr("maintenance.col.device"), "IMEI", i18n.tr("maintenance.col.problem"),
            i18n.tr("maintenance.col.status"), i18n.tr("maintenance.col.cost"),
            i18n.tr("maintenance.col.customer_price"), i18n.tr("maintenance.col.linked_invoice"),
        ])
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        edit_btn = QPushButton(i18n.tr("maintenance.edit_button"))
        edit_btn.setObjectName("SecondaryButton")
        edit_btn.clicked.connect(self.edit_ticket)
        actions.addWidget(edit_btn)
        delete_btn = QPushButton(i18n.tr("common.delete"))
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self.delete_ticket)
        actions.addWidget(delete_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.refresh()

    def refresh(self):
        rows = db.fetch_all("SELECT * FROM maintenance ORDER BY received_date DESC, id DESC")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.table, i, [
                r["customer_name"] or "-", r.get("customer_phone") or "-", r["device_name"] or "-", r["imei"] or "-",
                (r["problem_description"] or "-")[:40], status_label(r["status"]),
                fmt_money(r["cost"]), fmt_money(r["customer_price"] or 0),
                i18n.tr("maintenance.linked_invoice_value", id=r["sale_id"]) if r["sale_id"] else "-",
            ])
        self._rows_cache = rows

    def _selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows_cache):
            return None
        return self._rows_cache[row]

    def add_ticket(self):
        dlg = MaintenanceDialog()
        if dlg.exec():
            d = dlg.get_data()
            if not d["device_name"]:
                warn(self, i18n.tr("maintenance.error_no_device"))
                return
            db.execute(
                """INSERT INTO maintenance (customer_name, customer_phone, device_name, imei, problem_description, status, cost,
                   customer_price, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (d["customer_name"], d["customer_phone"], d["device_name"], d["imei"], d["problem_description"], d["status"], d["cost"],
                 d["customer_price"], d["notes"]),
            )
            self.refresh()

    def edit_ticket(self):
        ticket = self._selected()
        if not ticket:
            warn(self, i18n.tr("maintenance.error_select_first"))
            return
        dlg = MaintenanceDialog(ticket)
        if dlg.exec():
            d = dlg.get_data()
            delivered_date = db.today_str() if d["status"] == "delivered" else ticket.get("delivered_date")
            db.execute(
                """UPDATE maintenance SET customer_name=?, customer_phone=?, device_name=?, imei=?, problem_description=?,
                   status=?, cost=?, customer_price=?, notes=?, delivered_date=? WHERE id=?""",
                (d["customer_name"], d["customer_phone"], d["device_name"], d["imei"], d["problem_description"],
                 d["status"], d["cost"], d["customer_price"], d["notes"], delivered_date, ticket["id"]),
            )
            self.refresh()

    def delete_ticket(self):
        ticket = self._selected()
        if not ticket:
            warn(self, i18n.tr("maintenance.error_select_first"))
            return
        if confirm(self, i18n.tr("maintenance.confirm_delete")):
            db.execute("DELETE FROM maintenance WHERE id=?", (ticket["id"],))
            self.refresh()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
