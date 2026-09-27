from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QLineEdit, QDoubleSpinBox
)

from app import database as db
from app import i18n
from app.utils.widgets import build_table, fill_row, confirm, warn, info, fmt_money

CATEGORIES = ["إيجار", "كهرباء", "مياه", "إنترنت", "صيانة", "نقل", "موظفين", "أخرى"]
EMPLOYEE_CATEGORY = "موظفين"


class ExpensesView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("expenses.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        form = QHBoxLayout()
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems(CATEGORIES)
        self.category_combo.currentTextChanged.connect(self._update_category_fields)
        form.addWidget(QLabel(i18n.tr("expenses.category_label")))
        form.addWidget(self.category_combo)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText(i18n.tr("expenses.description_placeholder"))
        form.addWidget(self.description_input)

        self.employee_combo = QComboBox()
        self.employee_combo.currentIndexChanged.connect(self._autofill_salary)
        form.addWidget(self.employee_combo)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, 1_000_000)
        form.addWidget(QLabel(i18n.tr("expenses.amount_label")))
        form.addWidget(self.amount_input)

        add_btn = QPushButton(i18n.tr("expenses.add_button"))
        add_btn.clicked.connect(self.add_expense)
        form.addWidget(add_btn)
        layout.addLayout(form)

        self.table = build_table([
            i18n.tr("expenses.col.category"), i18n.tr("expenses.col.description"),
            i18n.tr("expenses.col.amount"), i18n.tr("expenses.col.date"),
        ])
        layout.addWidget(self.table)

        delete_btn = QPushButton(i18n.tr("expenses.delete_selected"))
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self.delete_expense)
        layout.addWidget(delete_btn)

        self._reload_employees()
        self._update_category_fields(self.category_combo.currentText())
        self.refresh()

    def _reload_employees(self):
        self.employee_combo.blockSignals(True)
        self.employee_combo.clear()
        for e in db.fetch_all("SELECT id, name, salary FROM employees ORDER BY name"):
            self.employee_combo.addItem(e["name"], e["id"])
        self.employee_combo.blockSignals(False)

    def _update_category_fields(self, text):
        is_employee = (text.strip() == EMPLOYEE_CATEGORY)
        self.description_input.setVisible(not is_employee)
        self.employee_combo.setVisible(is_employee)
        if is_employee:
            self._autofill_salary()

    def _pending_advance(self, employee_id):
        return db.fetch_one(
            "SELECT COALESCE(SUM(amount),0) v FROM advances WHERE employee_id=? AND settled=0",
            (employee_id,),
        )["v"]

    def _autofill_salary(self):
        emp_id = self.employee_combo.currentData()
        if emp_id is None:
            return
        emp = db.fetch_one("SELECT * FROM employees WHERE id=?", (emp_id,))
        if not emp:
            return
        pending_advance = self._pending_advance(emp_id)
        net = max(0, (emp["salary"] or 0) - pending_advance)
        self.amount_input.setValue(net)

    def _employee_salary_description(self, emp_id, emp_name):
        pending_advance = self._pending_advance(emp_id)
        if pending_advance > 0:
            desc = i18n.tr("expenses.salary_desc_with_advance", name=emp_name, amount=fmt_money(pending_advance))
            return desc, True
        return i18n.tr("expenses.salary_desc", name=emp_name), False

    def add_expense(self):
        amount = self.amount_input.value()
        if amount <= 0:
            warn(self, i18n.tr("expenses.error_invalid_amount"))
            return

        category = self.category_combo.currentText().strip()
        is_employee = (category == EMPLOYEE_CATEGORY)
        emp_id = None
        had_advance_deduction = False

        if is_employee:
            emp_id = self.employee_combo.currentData()
            if emp_id is None:
                warn(self, i18n.tr("expenses.error_no_employee"))
                return
            emp_name = self.employee_combo.currentText()
            description, had_advance_deduction = self._employee_salary_description(emp_id, emp_name)
        else:
            description = self.description_input.text().strip()

        expense_id = db.execute(
            "INSERT INTO expenses (category, description, amount) VALUES (?,?,?)",
            (category, description, amount),
        )
        account = db.fetch_one("SELECT id FROM treasury_accounts WHERE type='cash' LIMIT 1") \
            or db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
        if account:
            db.execute("UPDATE treasury_accounts SET balance = balance - ? WHERE id=?", (amount, account["id"]))
            tx_id = db.execute(
                "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                (account["id"], amount, "out", i18n.tr("expenses.treasury_tx_desc", description=description)),
            )
            db.execute("UPDATE expenses SET treasury_transaction_id=? WHERE id=?", (tx_id, expense_id))

        if is_employee:
            db.execute("UPDATE advances SET settled=1 WHERE employee_id=? AND settled=0", (emp_id,))
            notice_key = "expenses.salary_paid_notice_with_advance" if had_advance_deduction else "expenses.salary_paid_notice"
            info(self, i18n.tr(notice_key))

        self.description_input.clear()
        self.amount_input.setValue(0)
        self.refresh()

    def refresh(self):
        rows = db.fetch_all("SELECT * FROM expenses ORDER BY date DESC, id DESC")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.table, i, [r["category"] or "-", r["description"] or "-", fmt_money(r["amount"]), r["date"]])
        self._rows_cache = rows

    def delete_expense(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows_cache):
            warn(self, i18n.tr("common.select_item_first"))
            return
        exp = self._rows_cache[row]
        if not confirm(self, i18n.tr("expenses.confirm_delete")):
            return
        tx_id = exp["treasury_transaction_id"]
        db.execute("DELETE FROM expenses WHERE id=?", (exp["id"],))
        if tx_id:
            tx = db.fetch_one("SELECT * FROM treasury_transactions WHERE id=?", (tx_id,))
            if tx:
                db.execute(
                    "UPDATE treasury_accounts SET balance = balance + ? WHERE id=?",
                    (exp["amount"], tx["account_id"]),
                )
                db.execute("DELETE FROM treasury_transactions WHERE id=?", (tx_id,))
        self.refresh()

    def showEvent(self, event):
        self._reload_employees()
        self.refresh()
        super().showEvent(event)
