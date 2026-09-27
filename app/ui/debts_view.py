from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QFormLayout, QDoubleSpinBox, QDialogButtonBox, QTabWidget, QDateEdit, QLineEdit
)
from PySide6.QtCore import QDate

from app import database as db
from app import i18n
from app.utils import palette as pal
from app.utils.widgets import build_table, fill_row, confirm, warn, info, fmt_money


# ---------------- Shared payment ledger helpers ----------------
# كل دفعة (تسديد/تحصيل) بتتسجل كصف في debt_payments مربوط بمعاملة خزنة،
# عشان يبقى فيه سجل تاريخي قابل للتعديل والحذف، مش بس رقم إجمالي بيتغير.

def _account_for_new_payment():
    return db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")


def _recompute_debt(debt_id):
    debt = db.fetch_one("SELECT * FROM debts WHERE id=?", (debt_id,))
    if not debt:
        return
    paid = db.fetch_one(
        "SELECT COALESCE(SUM(amount),0) v FROM debt_payments WHERE debt_id=?", (debt_id,)
    )["v"]
    original = debt["original_amount"] if debt["original_amount"] is not None else debt["amount"]
    remaining = max(0.0, original - paid)
    status = "paid" if remaining <= 0.001 else "pending"
    db.execute("UPDATE debts SET amount=?, status=? WHERE id=?", (remaining, status, debt_id))


def add_debt_payment(debt, amount, date_str, notes):
    tx_id = None
    if amount > 0:
        account = _account_for_new_payment()
        if account:
            direction = "in" if debt["debt_type"] == "owed_to_me" else "out"
            sign = 1 if direction == "in" else -1
            db.execute(
                "UPDATE treasury_accounts SET balance = balance + ? WHERE id=?",
                (sign * amount, account["id"]),
            )
            tx_id = db.execute(
                "INSERT INTO treasury_transactions (account_id, amount, type, description, date) VALUES (?,?,?,?,?)",
                (account["id"], amount, direction, i18n.tr("debts.treasury_tx_desc", party=debt["party_name"]), date_str),
            )
    db.execute(
        "INSERT INTO debt_payments (debt_id, amount, payment_date, notes, treasury_transaction_id) VALUES (?,?,?,?,?)",
        (debt["id"], amount, date_str, notes, tx_id),
    )
    _recompute_debt(debt["id"])


def update_debt_payment(debt, payment, amount, date_str, notes):
    tx_id = payment["treasury_transaction_id"]
    if tx_id:
        tx = db.fetch_one("SELECT * FROM treasury_transactions WHERE id=?", (tx_id,))
        if tx:
            direction = "in" if debt["debt_type"] == "owed_to_me" else "out"
            sign = 1 if direction == "in" else -1
            delta = amount - payment["amount"]
            db.execute(
                "UPDATE treasury_accounts SET balance = balance + ? WHERE id=?",
                (sign * delta, tx["account_id"]),
            )
            db.execute(
                "UPDATE treasury_transactions SET amount=?, date=?, description=? WHERE id=?",
                (amount, date_str, i18n.tr("debts.treasury_tx_desc", party=debt["party_name"]), tx_id),
            )
    db.execute(
        "UPDATE debt_payments SET amount=?, payment_date=?, notes=? WHERE id=?",
        (amount, date_str, notes, payment["id"]),
    )
    _recompute_debt(debt["id"])


def delete_debt_payment(debt, payment):
    tx_id = payment["treasury_transaction_id"]
    if tx_id:
        tx = db.fetch_one("SELECT * FROM treasury_transactions WHERE id=?", (tx_id,))
        if tx:
            direction = "in" if debt["debt_type"] == "owed_to_me" else "out"
            sign = 1 if direction == "in" else -1
            db.execute(
                "UPDATE treasury_accounts SET balance = balance - ? WHERE id=?",
                (sign * payment["amount"], tx["account_id"]),
            )
            # لازم نشيل صف debt_payments الأول عشان بيشاور على المعاملة دي بمفتاح
            # أجنبي (treasury_transaction_id) - حذف المعاملة قبله بيكسر القيد ويفشل.
            db.execute("DELETE FROM debt_payments WHERE id=?", (payment["id"],))
            db.execute("DELETE FROM treasury_transactions WHERE id=?", (tx_id,))
        else:
            db.execute("DELETE FROM debt_payments WHERE id=?", (payment["id"],))
    else:
        db.execute("DELETE FROM debt_payments WHERE id=?", (payment["id"],))
    _recompute_debt(debt["id"])


# ---------------- Dialogs ----------------

class PayDialog(QDialog):
    """تسديد سريع من شاشة القايمة الرئيسية - سقف المبلغ هو المتبقي بالظبط."""

    def __init__(self, debt):
        super().__init__()
        self.debt = debt
        self.setWindowTitle(i18n.tr("debts.dialog.pay_title"))
        form = QFormLayout(self)
        form.addRow(QLabel(i18n.tr("debts.remaining_amount", amount=fmt_money(debt["amount"]))))
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, debt["amount"])
        self.amount_input.setValue(debt["amount"])
        form.addRow(i18n.tr("debts.field.amount_now"), self.amount_input)
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        form.addRow(i18n.tr("debts.field.payment_date"), self.date_input)
        self.notes_input = QLineEdit()
        form.addRow(i18n.tr("debts.field.notes_optional"), self.notes_input)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(i18n.tr("debts.confirm_button"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_data(self):
        return {
            "amount": self.amount_input.value(),
            "date": self.date_input.date().toString("yyyy-MM-dd"),
            "notes": self.notes_input.text().strip(),
        }


class PaymentDialog(QDialog):
    """يستخدم لإضافة دفعة جديدة أو تعديل دفعة موجودة من شاشة التفاصيل -
    من غير سقف على المبلغ عشان يقدر يصحّح أي غلطة كتبها قبل كده."""

    def __init__(self, amount=0.0, date_str=None, notes="", title=None):
        super().__init__()
        self.setWindowTitle(title or i18n.tr("debts.dialog.add_payment_title"))
        form = QFormLayout(self)
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, 100_000_000)
        self.amount_input.setValue(amount)
        form.addRow(i18n.tr("debts.field.amount"), self.amount_input)
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        qdate = QDate.fromString(date_str, "yyyy-MM-dd") if date_str else QDate()
        self.date_input.setDate(qdate if qdate.isValid() else QDate.currentDate())
        form.addRow(i18n.tr("debts.field.date"), self.date_input)
        self.notes_input = QLineEdit(notes or "")
        form.addRow(i18n.tr("debts.field.notes_optional"), self.notes_input)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(i18n.tr("common.save"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_data(self):
        return {
            "amount": self.amount_input.value(),
            "date": self.date_input.date().toString("yyyy-MM-dd"),
            "notes": self.notes_input.text().strip(),
        }


class DebtDetailDialog(QDialog):
    """تفاصيل دين واحد: سجل كل الدفعات بتواريخها، مع إمكانية إضافة/تعديل/حذف
    أي دفعة براحتك (مثلاً لو اتكتب مبلغ غلط وعايز ترجعه)."""

    def __init__(self, debt):
        super().__init__()
        self.debt_id = debt["id"]
        self.changed = False
        self.setWindowTitle(i18n.tr("debts.detail_title", party=debt["party_name"] or "-"))
        self.resize(650, 420)

        layout = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size:15px; font-weight:bold;")
        layout.addWidget(self.summary_label)

        self.desc_label = QLabel()
        layout.addWidget(self.desc_label)

        self.table = build_table([i18n.tr("debts.col.date"), i18n.tr("debts.col.amount"), i18n.tr("debts.col.notes")])
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        add_btn = QPushButton(i18n.tr("debts.add_payment_button"))
        add_btn.clicked.connect(self._add_payment)
        actions.addWidget(add_btn)

        edit_btn = QPushButton(i18n.tr("debts.edit_payment_button"))
        edit_btn.setObjectName("SecondaryButton")
        edit_btn.clicked.connect(self._edit_payment)
        actions.addWidget(edit_btn)

        delete_btn = QPushButton(i18n.tr("debts.delete_payment_button"))
        delete_btn.setObjectName("SecondaryButton")
        delete_btn.clicked.connect(self._delete_payment)
        actions.addWidget(delete_btn)

        actions.addStretch()
        close_btn = QPushButton(i18n.tr("debts.close_button"))
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self._refresh()

    def _refresh(self):
        debt = db.fetch_one("SELECT * FROM debts WHERE id=?", (self.debt_id,))
        if not debt:
            self.reject()
            return
        self.debt = debt
        original = debt["original_amount"] if debt["original_amount"] is not None else debt["amount"]
        paid_total = original - debt["amount"]
        status_text = i18n.tr("debts.status_fully_paid" if debt["status"] == "paid" else "debts.status_due")
        self.summary_label.setText(i18n.tr(
            "debts.summary",
            original=fmt_money(original), paid=fmt_money(paid_total),
            remaining=fmt_money(debt["amount"]), status=status_text,
        ))
        self.desc_label.setText(debt["description"] or "")

        self.rows = db.fetch_all(
            "SELECT * FROM debt_payments WHERE debt_id=? ORDER BY payment_date, id", (self.debt_id,)
        )
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            fill_row(self.table, i, [r["payment_date"] or "-", fmt_money(r["amount"]), r["notes"] or "-"])

    def _selected_payment(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.rows):
            warn(self, i18n.tr("debts.error_select_payment"))
            return None
        return self.rows[row]

    def _add_payment(self):
        dlg = PaymentDialog(amount=self.debt["amount"], title=i18n.tr("debts.add_payment_button"))
        if not dlg.exec():
            return
        data = dlg.get_data()
        if data["amount"] <= 0:
            warn(self, i18n.tr("debts.error_amount_gt_zero"))
            return
        add_debt_payment(self.debt, data["amount"], data["date"], data["notes"])
        self.changed = True
        self._refresh()

    def _edit_payment(self):
        payment = self._selected_payment()
        if not payment:
            return
        dlg = PaymentDialog(
            amount=payment["amount"], date_str=payment["payment_date"], notes=payment["notes"] or "",
            title=i18n.tr("debts.dialog.edit_payment_title"),
        )
        if not dlg.exec():
            return
        data = dlg.get_data()
        if data["amount"] <= 0:
            warn(self, i18n.tr("debts.error_amount_gt_zero"))
            return
        update_debt_payment(self.debt, payment, data["amount"], data["date"], data["notes"])
        self.changed = True
        self._refresh()

    def _delete_payment(self):
        payment = self._selected_payment()
        if not payment:
            return
        if not confirm(
            self,
            i18n.tr("debts.confirm_delete_payment", amount=fmt_money(payment["amount"]), date=payment["payment_date"]),
        ):
            return
        delete_debt_payment(self.debt, payment)
        self.changed = True
        self._refresh()


class DebtsView(QWidget):
    def __init__(self, can_view_all_debts):
        super().__init__()
        # اسم بارامتر واضح إنه مش أدمن بس - بيتحدد في main_window.py كـ
        # (is_admin or is_supervisor)، عشان السوبر فايزر يشوف تاب "عليا"
        # (ديون المحل للموردين) زي الأدمن بالظبط، مش الموظف اللي بيشوف
        # "ليا" بس.
        self.can_view_all_debts = can_view_all_debts
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("debts.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        hint = QLabel(i18n.tr("debts.hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        layout.addWidget(hint)

        tabs = QTabWidget()
        self._tab_index = {}
        self._tab_index["owed_to_me"] = tabs.addTab(self._build_tab("owed_to_me"), i18n.tr("debts.tab.owed_to_me"))
        if can_view_all_debts:
            self._tab_index["i_owe"] = tabs.addTab(self._build_tab("i_owe"), i18n.tr("debts.tab.i_owe"))
        layout.addWidget(tabs)
        self.tabs = tabs

    def show_tab(self, debt_type):
        index = self._tab_index.get(debt_type)
        if index is not None:
            self.tabs.setCurrentIndex(index)

    def _build_tab(self, debt_type):
        w = QWidget()
        v = QVBoxLayout(w)
        table = build_table([
            i18n.tr("debts.col.name"), i18n.tr("debts.col.amount"), i18n.tr("debts.col.due_date"),
            i18n.tr("debts.col.description"), i18n.tr("debts.col.status"),
        ])
        table.cellClicked.connect(lambda r, c, t=table, dt=debt_type: self._open_details(t, dt, r, c))
        v.addWidget(table)

        actions = QHBoxLayout()
        pay_btn = QPushButton(i18n.tr("debts.pay_button"))
        pay_btn.clicked.connect(lambda: self._pay(table, debt_type))
        actions.addWidget(pay_btn)
        actions.addStretch()
        v.addLayout(actions)

        setattr(self, f"_table_{debt_type}", table)
        self._refresh_table(table, debt_type)
        return w

    def _refresh_table(self, table, debt_type):
        rows = db.fetch_all(
            "SELECT * FROM debts WHERE debt_type=? AND status='pending' "
            "ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date",
            (debt_type,),
        )
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(table, i, [
                r["party_name"] or "-", fmt_money(r["amount"]), r["due_date"] or "-",
                r["description"] or "-", i18n.tr("debts.status_due")
            ])
        setattr(self, f"_rows_{debt_type}", rows)

    def _open_details(self, table, debt_type, row, col):
        if col != 0:
            return
        rows = getattr(self, f"_rows_{debt_type}")
        if row < 0 or row >= len(rows):
            return
        dlg = DebtDetailDialog(rows[row])
        dlg.exec()
        if dlg.changed:
            self._refresh_table(table, debt_type)

    def _pay(self, table, debt_type):
        rows = getattr(self, f"_rows_{debt_type}")
        row = table.currentRow()
        if row < 0 or row >= len(rows):
            warn(self, i18n.tr("common.select_item_first"))
            return
        debt = rows[row]
        dlg = PayDialog(debt)
        if dlg.exec():
            data = dlg.get_data()
            if data["amount"] <= 0:
                warn(self, i18n.tr("debts.error_amount_gt_zero"))
                return
            add_debt_payment(debt, data["amount"], data["date"], data["notes"])
            info(self, i18n.tr("debts.notice_payment_recorded"))
            self._refresh_table(table, debt_type)

    def showEvent(self, event):
        self._refresh_table(self._table_owed_to_me, "owed_to_me")
        if self.can_view_all_debts and hasattr(self, "_table_i_owe"):
            self._refresh_table(self._table_i_owe, "i_owe")
        super().showEvent(event)
