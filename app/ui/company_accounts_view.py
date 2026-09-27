from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QDoubleSpinBox, QLineEdit, QSpinBox, QDateEdit, QInputDialog
)

from app import database as db
from app import i18n
from app.utils.widgets import Card, build_table, fill_row, warn, info, confirm, fmt_money


class CompanyAccountsView(QWidget):
    """تتبع عمليات الفيزا اللي بتتحصل من خلال شركة وسيطة (زي مايلو) وبتنزل
    رصيدها للمحل بعد فترة (غالبًا 15 يوم) - تفضل الفلوس معلقة لحد ما
    يتحدد إنها اتحصّلت فعلاً."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("company_accounts.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        hint = QLabel(i18n.tr("company_accounts.hint"))
        hint.setWordWrap(True)
        hint.setObjectName("CardTitle")
        layout.addWidget(hint)

        self.cards_row = QHBoxLayout()
        layout.addLayout(self.cards_row)

        form = QHBoxLayout()
        self.company_combo = QComboBox()
        self.company_combo.setEditable(True)
        form.addWidget(QLabel(i18n.tr("company_accounts.company_label")))
        form.addWidget(self.company_combo)

        add_company_btn = QPushButton(i18n.tr("company_accounts.new_company_button"))
        add_company_btn.setObjectName("SecondaryButton")
        add_company_btn.clicked.connect(self.add_company)
        form.addWidget(add_company_btn)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, 10_000_000)
        form.addWidget(QLabel(i18n.tr("company_accounts.amount_label")))
        form.addWidget(self.amount_input)

        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        form.addWidget(QLabel(i18n.tr("company_accounts.transaction_date_label")))
        form.addWidget(self.date_input)

        self.days_input = QSpinBox()
        self.days_input.setRange(0, 365)
        self.days_input.setValue(15)
        form.addWidget(QLabel(i18n.tr("company_accounts.days_label")))
        form.addWidget(self.days_input)

        add_btn = QPushButton(i18n.tr("company_accounts.add_button"))
        add_btn.clicked.connect(self.add_settlement)
        form.addWidget(add_btn)
        layout.addLayout(form)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText(i18n.tr("company_accounts.notes_placeholder"))
        layout.addWidget(self.notes_input)

        self.table = build_table([
            i18n.tr("company_accounts.col.company"), i18n.tr("company_accounts.col.amount"),
            i18n.tr("company_accounts.col.transaction_date"), i18n.tr("company_accounts.col.expected_date"),
            i18n.tr("company_accounts.col.status"), i18n.tr("company_accounts.col.collected_date"),
            i18n.tr("company_accounts.col.notes"),
        ])
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        collect_btn = QPushButton(i18n.tr("company_accounts.mark_collected_button"))
        collect_btn.clicked.connect(self.mark_collected)
        actions.addWidget(collect_btn)

        delete_btn = QPushButton(i18n.tr("company_accounts.delete_button"))
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self.delete_selected)
        actions.addWidget(delete_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self._reload_companies()
        self.refresh()

    def _reload_companies(self, select=None):
        current = select or self.company_combo.currentText().strip()
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        for c in db.fetch_all("SELECT name FROM settlement_companies ORDER BY name"):
            self.company_combo.addItem(c["name"])
        self.company_combo.blockSignals(False)
        if current:
            idx = self.company_combo.findText(current)
            if idx >= 0:
                self.company_combo.setCurrentIndex(idx)
            else:
                self.company_combo.setCurrentText(current)

    def add_company(self):
        name, ok = QInputDialog.getText(
            self, i18n.tr("company_accounts.dialog.new_company_title"), i18n.tr("company_accounts.dialog.new_company_label")
        )
        name = name.strip()
        if not ok or not name:
            return
        existing = db.fetch_one("SELECT id FROM settlement_companies WHERE name=?", (name,))
        if existing:
            warn(self, i18n.tr("company_accounts.error_company_exists"))
            self._reload_companies(select=name)
            return
        db.execute("INSERT INTO settlement_companies (name) VALUES (?)", (name,))
        self._reload_companies(select=name)
        info(self, i18n.tr("company_accounts.notice_company_added"))

    def refresh(self):
        while self.cards_row.count():
            item = self.cards_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        pending_total = db.fetch_one(
            "SELECT COALESCE(SUM(amount),0) v FROM company_settlements WHERE status='pending'"
        )["v"]
        pending_count = db.fetch_one(
            "SELECT COUNT(*) c FROM company_settlements WHERE status='pending'"
        )["c"]
        self.cards_row.addWidget(Card(
            i18n.tr("company_accounts.pending_card_title"), fmt_money(pending_total),
            variant="warning", subtitle=i18n.tr("company_accounts.pending_card_subtitle", count=pending_count),
        ))

        rows = db.fetch_all("SELECT * FROM company_settlements ORDER BY status ASC, expected_date ASC")
        self._rows_cache = rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            status_text = i18n.tr("company_accounts.status_pending" if r["status"] == "pending" else "company_accounts.status_collected")
            fill_row(self.table, i, [
                r["company_name"], fmt_money(r["amount"]), r["transaction_date"], r["expected_date"] or "-",
                status_text, r["collected_date"] or "-", r["notes"] or "-",
            ])

    def _selected_row(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows_cache):
            return None
        return self._rows_cache[row]

    def add_settlement(self):
        company = self.company_combo.currentText().strip()
        amount = self.amount_input.value()
        if not company:
            warn(self, i18n.tr("company_accounts.error_no_company_name"))
            return
        if amount <= 0:
            warn(self, i18n.tr("expenses.error_invalid_amount"))
            return

        tx_date = self.date_input.date().toPython()
        expected_date = tx_date + timedelta(days=self.days_input.value())

        db.execute(
            "IF NOT EXISTS (SELECT 1 FROM settlement_companies WHERE name=?) "
            "INSERT INTO settlement_companies (name) VALUES (?)",
            (company, company),
        )
        db.execute(
            """INSERT INTO company_settlements (company_name, amount, transaction_date, expected_date, notes)
               VALUES (?,?,?,?,?)""",
            (company, amount, tx_date.isoformat(), expected_date.isoformat(), self.notes_input.text().strip()),
        )
        info(self, i18n.tr("treasury.notice_transaction_recorded"))
        self.amount_input.setValue(0)
        self.notes_input.clear()
        self._reload_companies(select=company)
        self.refresh()

    def mark_collected(self):
        row = self._selected_row()
        if not row:
            warn(self, i18n.tr("company_accounts.error_select_first"))
            return
        if row["status"] == "collected":
            warn(self, i18n.tr("company_accounts.error_already_collected"))
            return
        if not confirm(
            self,
            i18n.tr("company_accounts.confirm_mark_collected", amount=fmt_money(row["amount"]), company=row["company_name"]),
        ):
            return

        today = date.today().isoformat()
        db.execute(
            "UPDATE company_settlements SET status='collected', collected_date=? WHERE id=?",
            (today, row["id"]),
        )

        account = (
            db.fetch_one("SELECT id FROM treasury_accounts WHERE type='visa' LIMIT 1")
            or db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
        )
        if account:
            db.execute(
                "UPDATE treasury_accounts SET balance = balance + ? WHERE id=?",
                (row["amount"], account["id"]),
            )
            tx_id = db.execute(
                "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                (account["id"], row["amount"], "in",
                 i18n.tr("company_accounts.treasury_tx_desc", company=row["company_name"], date=row["transaction_date"])),
            )
            db.execute("UPDATE company_settlements SET treasury_transaction_id=? WHERE id=?", (tx_id, row["id"]))

        info(self, i18n.tr("company_accounts.notice_collected"))
        self.refresh()

    def delete_selected(self):
        row = self._selected_row()
        if not row:
            warn(self, i18n.tr("company_accounts.error_select_first"))
            return
        msg = i18n.tr("company_accounts.confirm_delete")
        if row["status"] == "collected":
            msg += i18n.tr("company_accounts.confirm_delete_collected_suffix")
        if not confirm(self, msg):
            return
        tx_id = row["treasury_transaction_id"]
        db.execute("DELETE FROM company_settlements WHERE id=?", (row["id"],))
        if tx_id:
            tx = db.fetch_one("SELECT * FROM treasury_transactions WHERE id=?", (tx_id,))
            if tx:
                db.execute(
                    "UPDATE treasury_accounts SET balance = balance - ? WHERE id=?",
                    (row["amount"], tx["account_id"]),
                )
                db.execute("DELETE FROM treasury_transactions WHERE id=?", (tx_id,))
        self.refresh()

    def showEvent(self, event):
        self._reload_companies()
        self.refresh()
        super().showEvent(event)
