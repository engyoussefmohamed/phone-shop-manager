from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QFormLayout, QLineEdit, QDoubleSpinBox, QDateEdit, QTextEdit,
    QDialogButtonBox, QTabWidget, QComboBox
)
from PySide6.QtCore import QDate

from app import database as db
from app import i18n
from app.utils.widgets import build_table, fill_row, confirm, warn, info, fmt_money


class EmployeeDialog(QDialog):
    def __init__(self, employee=None):
        super().__init__()
        self.employee = employee
        self.setWindowTitle(i18n.tr("employees.dialog.edit_title" if employee else "employees.dialog.add_title"))
        self.setMinimumWidth(360)
        form = QFormLayout(self)

        self.name_input = QLineEdit(employee["name"] if employee else "")
        form.addRow(i18n.tr("party.field.name"), self.name_input)
        self.job_input = QLineEdit(employee["job_title"] if employee else "")
        form.addRow(i18n.tr("employees.field.job_title"), self.job_input)
        self.phone_input = QLineEdit(employee["phone"] if employee else "")
        form.addRow(i18n.tr("party.field.phone"), self.phone_input)
        self.salary_input = QDoubleSpinBox()
        self.salary_input.setRange(0, 1_000_000)
        self.salary_input.setValue(employee["salary"] if employee else 0)
        form.addRow(i18n.tr("employees.field.salary"), self.salary_input)
        self.hire_date_input = QDateEdit()
        self.hire_date_input.setCalendarPopup(True)
        self.hire_date_input.setDate(
            QDate.fromString(employee["hire_date"], "yyyy-MM-dd") if employee and employee.get("hire_date") else QDate.currentDate()
        )
        form.addRow(i18n.tr("employees.field.hire_date"), self.hire_date_input)
        self.notes_input = QTextEdit(employee["notes"] if employee else "")
        self.notes_input.setFixedHeight(60)
        form.addRow(i18n.tr("common.notes"), self.notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(i18n.tr("common.save"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "job_title": self.job_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "salary": self.salary_input.value(),
            "hire_date": self.hire_date_input.date().toString("yyyy-MM-dd"),
            "notes": self.notes_input.toPlainText().strip(),
        }


class EmployeesView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("employees.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_employees_tab(), i18n.tr("employees.tab.list"))
        tabs.addTab(self._build_advances_tab(), i18n.tr("employees.tab.advances"))
        layout.addWidget(tabs)

    # ---------------- Employees ----------------

    def _build_employees_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        header = QHBoxLayout()
        add_btn = QPushButton(i18n.tr("employees.add_button"))
        add_btn.clicked.connect(self.add_employee)
        header.addStretch()
        header.addWidget(add_btn)
        v.addLayout(header)

        self.table = build_table([
            i18n.tr("employees.col.name"), i18n.tr("employees.col.job_title"), i18n.tr("employees.col.phone"),
            i18n.tr("employees.col.salary"), i18n.tr("employees.col.hire_date"),
        ])
        v.addWidget(self.table)

        actions = QHBoxLayout()
        edit_btn = QPushButton(i18n.tr("common.edit"))
        edit_btn.setObjectName("SecondaryButton")
        edit_btn.clicked.connect(self.edit_employee)
        actions.addWidget(edit_btn)
        delete_btn = QPushButton(i18n.tr("common.delete"))
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self.delete_employee)
        actions.addWidget(delete_btn)
        actions.addStretch()
        v.addLayout(actions)

        self.refresh_employees()
        return w

    def refresh_employees(self):
        rows = db.fetch_all("SELECT * FROM employees ORDER BY name")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.table, i, [r["name"], r["job_title"] or "-", r["phone"] or "-",
                                      fmt_money(r["salary"]), r["hire_date"] or "-"])
        self._rows_cache = rows

    def _selected_employee(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows_cache):
            return None
        return self._rows_cache[row]

    def add_employee(self):
        dlg = EmployeeDialog()
        if dlg.exec():
            d = dlg.get_data()
            if not d["name"]:
                warn(self, i18n.tr("party.error_no_name"))
                return
            db.execute(
                "INSERT INTO employees (name, job_title, salary, phone, hire_date, notes) VALUES (?,?,?,?,?,?)",
                (d["name"], d["job_title"], d["salary"], d["phone"], d["hire_date"], d["notes"]),
            )
            self.refresh_employees()
            self._reload_employee_combo()

    def edit_employee(self):
        emp = self._selected_employee()
        if not emp:
            warn(self, i18n.tr("common.select_item_first"))
            return
        dlg = EmployeeDialog(emp)
        if dlg.exec():
            d = dlg.get_data()
            db.execute(
                "UPDATE employees SET name=?, job_title=?, salary=?, phone=?, hire_date=?, notes=? WHERE id=?",
                (d["name"], d["job_title"], d["salary"], d["phone"], d["hire_date"], d["notes"], emp["id"]),
            )
            self.refresh_employees()
            self._reload_employee_combo()

    def delete_employee(self):
        emp = self._selected_employee()
        if not emp:
            warn(self, i18n.tr("common.select_item_first"))
            return
        if confirm(self, i18n.tr("employees.confirm_delete", name=emp["name"])):
            db.execute("DELETE FROM employees WHERE id=?", (emp["id"],))
            self.refresh_employees()
            self._reload_employee_combo()

    # ---------------- Advances (سلف) ----------------

    def _build_advances_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        form = QHBoxLayout()
        self.emp_combo = QComboBox()
        self._reload_employee_combo()
        form.addWidget(QLabel(i18n.tr("employees.advance.employee_label")))
        form.addWidget(self.emp_combo)

        self.advance_amount = QDoubleSpinBox()
        self.advance_amount.setRange(0, 1_000_000)
        form.addWidget(QLabel(i18n.tr("employees.advance.amount_label")))
        form.addWidget(self.advance_amount)

        add_btn = QPushButton(i18n.tr("employees.advance.add_button"))
        add_btn.clicked.connect(self.add_advance)
        form.addWidget(add_btn)
        v.addLayout(form)

        self.advances_table = build_table([
            i18n.tr("employees.advance.col.employee"), i18n.tr("employees.advance.col.amount"),
            i18n.tr("employees.advance.col.date"), i18n.tr("employees.advance.col.status"),
            i18n.tr("employees.advance.col.notes"),
        ])
        v.addWidget(self.advances_table)

        advance_actions = QHBoxLayout()
        delete_advance_btn = QPushButton(i18n.tr("employees.advance.delete_button"))
        delete_advance_btn.setObjectName("DangerButton")
        delete_advance_btn.clicked.connect(self.delete_advance)
        advance_actions.addWidget(delete_advance_btn)
        advance_actions.addStretch()
        v.addLayout(advance_actions)

        self.refresh_advances()
        return w

    def _reload_employee_combo(self):
        if not hasattr(self, "emp_combo"):
            return
        self.emp_combo.clear()
        for e in db.fetch_all("SELECT id, name FROM employees ORDER BY name"):
            self.emp_combo.addItem(e["name"], e["id"])

    def add_advance(self):
        emp_id = self.emp_combo.currentData()
        if emp_id is None:
            warn(self, i18n.tr("employees.advance.error_no_employee"))
            return
        amount = self.advance_amount.value()
        if amount <= 0:
            warn(self, i18n.tr("expenses.error_invalid_amount"))
            return
        advance_id = db.execute("INSERT INTO advances (employee_id, amount) VALUES (?,?)", (emp_id, amount))

        account = db.fetch_one("SELECT id FROM treasury_accounts WHERE type='cash' LIMIT 1") \
            or db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
        if account:
            db.execute("UPDATE treasury_accounts SET balance = balance - ? WHERE id=?", (amount, account["id"]))
            tx_id = db.execute(
                "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                (account["id"], amount, "out", i18n.tr("employees.advance.treasury_tx_desc", name=self.emp_combo.currentText())),
            )
            db.execute("UPDATE advances SET treasury_transaction_id=? WHERE id=?", (tx_id, advance_id))

        info(self, i18n.tr("employees.advance.notice_recorded"))
        self.advance_amount.setValue(0)
        self.refresh_advances()

    def refresh_advances(self):
        rows = db.fetch_all(
            """SELECT a.*, e.name as emp_name FROM advances a
               JOIN employees e ON e.id = a.employee_id ORDER BY a.date DESC"""
        )
        self.advances_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            status = i18n.tr("employees.advance.status_settled" if r["settled"] else "employees.advance.status_pending")
            fill_row(self.advances_table, i, [
                r["emp_name"], fmt_money(r["amount"]), r["date"], status, r["notes"] or "-"
            ])
        self._advances_cache = rows

    def delete_advance(self):
        row = self.advances_table.currentRow()
        if row < 0 or row >= len(self._advances_cache):
            warn(self, i18n.tr("employees.advance.error_select_first"))
            return
        adv = self._advances_cache[row]
        if adv["settled"]:
            warn(self, i18n.tr("employees.advance.error_already_settled"))
            return
        if not confirm(self, i18n.tr("employees.advance.confirm_delete", name=adv["emp_name"], amount=fmt_money(adv["amount"]))):
            return
        tx_id = adv["treasury_transaction_id"]
        db.execute("DELETE FROM advances WHERE id=?", (adv["id"],))
        if tx_id:
            tx = db.fetch_one("SELECT * FROM treasury_transactions WHERE id=?", (tx_id,))
            if tx:
                db.execute(
                    "UPDATE treasury_accounts SET balance = balance + ? WHERE id=?",
                    (adv["amount"], tx["account_id"]),
                )
                db.execute("DELETE FROM treasury_transactions WHERE id=?", (tx_id,))
        self.refresh_advances()

    def showEvent(self, event):
        self.refresh_employees()
        self._reload_employee_combo()
        self.refresh_advances()
        super().showEvent(event)
