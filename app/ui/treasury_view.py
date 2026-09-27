import os
import uuid
from datetime import datetime

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QDoubleSpinBox, QLineEdit,
    QTabWidget, QDialog, QDialogButtonBox, QApplication, QFileDialog
)

from app import database as db
from app import db_config
from app import i18n
from app.utils import palette as pal
from app.utils.widgets import Card, build_table, fill_row, confirm, warn, info, fmt_money

# الحسابات دي بس هي اللي منطقي يتسجل عليها رقم هاتف/صورة إيصال تحويل -
# الكاش والخزنة العامة مالهمش "محوّل" بمعنى تحويل موبايل.
TRANSFER_ACCOUNT_TYPES = {"visa", "wallet", "instapay"}


def _receipt_button(table, row, col, path):
    """يحط زرار صغير عليه thumbnail لصورة الإيصال في الخلية لو فيه صورة
    مرفقة، ويمسح أي زرار قديم كان قاعد في نفس الخلية من تحديث سابق (عشان
    الجدول ميفضلش شايل thumbnail غلط من صف اتغيّرت بياناته)."""
    table.removeCellWidget(row, col)
    if not path:
        return
    btn = QPushButton()
    btn.setFixedSize(28, 28)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet("background: transparent; border: none; padding: 0px;")
    pixmap = QPixmap(path)
    if not pixmap.isNull():
        btn.setIcon(QIcon(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        btn.setIconSize(QSize(24, 24))
    else:
        btn.setText("🖼")
    btn.clicked.connect(lambda: ReceiptPreviewDialog(path).exec())
    table.setCellWidget(row, col, btn)


class ReceiptPreviewDialog(QDialog):
    """معاينة أكبر لصورة إيصال تحويل واحدة."""

    def __init__(self, path):
        super().__init__()
        self.setWindowTitle(i18n.tr("treasury.receipt_dialog_title"))
        layout = QVBoxLayout(self)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            max_side = 700
            if pixmap.width() > max_side or pixmap.height() > max_side:
                pixmap = pixmap.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pixmap)
        else:
            label.setText(path)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class AccountDetailDialog(QDialog):
    """حركات حساب واحد بس (بيتفتح بالضغط على كارت الحساب في تبويب الحركات
    اليومية) - نفس فكرة DayClosingDetailDialog تحت بس لحساب بدل قفل يوم."""

    def __init__(self, account):
        super().__init__()
        self.account = account
        self.setWindowTitle(i18n.tr("treasury.account_detail_title", name=account["name"]))
        self.resize(760, 440)
        layout = QVBoxLayout(self)

        self.table = build_table([
            i18n.tr("treasury.col.date"), i18n.tr("treasury.col.description"), i18n.tr("treasury.col.type"),
            i18n.tr("treasury.col.amount"), i18n.tr("treasury.col.phone"), i18n.tr("treasury.col.receipt"),
        ])
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._refresh()

    def _refresh(self):
        rows = db.fetch_all(
            "SELECT * FROM treasury_transactions WHERE account_id=? ORDER BY date DESC LIMIT 300",
            (self.account["id"],),
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.table, i, [
                r["date"], r["description"] or "-",
                i18n.tr("treasury.direction_in") if r["type"] == "in" else i18n.tr("treasury.direction_out"),
                fmt_money(r["amount"]), r["phone_number"] or "-", "",
            ])
            _receipt_button(self.table, i, 5, r["receipt_image_path"])


class DayClosingDetailDialog(QDialog):
    """تفاصيل قفل يوم واحد: رصيد كل حساب وقت القفل قبل ما يترحّل للخزنة العامة."""

    def __init__(self, closing, items):
        super().__init__()
        self.setWindowTitle(i18n.tr("treasury.closing_detail_title", date=closing["closed_at"]))
        self.resize(420, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(i18n.tr(
            "treasury.closing_detail_summary",
            total=fmt_money(closing["total_amount"]), by=closing["closed_by"] or "-",
        )))
        table = build_table([i18n.tr("treasury.col.account"), i18n.tr("treasury.col.amount")])
        table.setRowCount(len(items))
        for i, it in enumerate(items):
            fill_row(table, i, [it["account_name"] or "-", fmt_money(it["amount"])])
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class TreasuryView(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self._pending_receipt = None  # QPixmap مؤقت لحد ما "تسجيل حركة" ينجح
        self._account_types = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("nav.treasury"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_daily_tab(), i18n.tr("treasury.tab.daily"))
        tabs.addTab(self._build_capital_tab(), i18n.tr("treasury.tab.capital"))
        tabs.addTab(self._build_closings_tab(), i18n.tr("treasury.tab.closings"))
        layout.addWidget(tabs)

        self.refresh()

    # ---------------- تبويب الحركات اليومية ----------------

    def _build_daily_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.cards_row = QHBoxLayout()
        layout.addLayout(self.cards_row)

        close_row = QHBoxLayout()
        close_btn = QPushButton(i18n.tr("treasury.close_day_button"))
        close_btn.setObjectName("DangerButton")
        close_btn.clicked.connect(self.close_day)
        close_row.addWidget(close_btn)
        close_row.addStretch()
        layout.addLayout(close_row)

        form = QHBoxLayout()
        self.account_combo = QComboBox()
        form.addWidget(QLabel(i18n.tr("treasury.account_label")))
        form.addWidget(self.account_combo)

        self.type_combo = QComboBox()
        self.type_combo.addItems([i18n.tr("treasury.type_in"), i18n.tr("treasury.type_out")])
        form.addWidget(self.type_combo)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setRange(0, 10_000_000)
        form.addWidget(QLabel(i18n.tr("treasury.amount_label")))
        form.addWidget(self.amount_input)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText(i18n.tr("treasury.description_placeholder"))
        form.addWidget(self.desc_input)

        add_btn = QPushButton(i18n.tr("treasury.add_transaction_button"))
        add_btn.clicked.connect(self.add_transaction)
        form.addWidget(add_btn)
        layout.addLayout(form)

        # صف إضافي بيظهر بس لحسابات التحويل (انستاباي/محفظة/فيزا) - رقم
        # هاتف المحوّل + إرفاق صورة الإيصال.
        transfer_row = QHBoxLayout()
        self.phone_label = QLabel(i18n.tr("treasury.field.phone"))
        transfer_row.addWidget(self.phone_label)
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText(i18n.tr("treasury.phone_placeholder"))
        transfer_row.addWidget(self.phone_input)

        self.attach_receipt_btn = QPushButton(i18n.tr("treasury.attach_receipt_button"))
        self.attach_receipt_btn.setObjectName("SecondaryButton")
        self.attach_receipt_btn.clicked.connect(self.attach_receipt)
        transfer_row.addWidget(self.attach_receipt_btn)

        self.receipt_preview_label = QLabel()
        self.receipt_preview_label.setFixedSize(32, 32)
        self.receipt_preview_label.setVisible(False)
        transfer_row.addWidget(self.receipt_preview_label)

        self.remove_receipt_btn = QPushButton(i18n.tr("treasury.remove_receipt_button"))
        self.remove_receipt_btn.setObjectName("DangerButton")
        self.remove_receipt_btn.setFixedWidth(32)
        self.remove_receipt_btn.setVisible(False)
        self.remove_receipt_btn.clicked.connect(self.remove_pending_receipt)
        transfer_row.addWidget(self.remove_receipt_btn)

        transfer_row.addStretch()
        layout.addLayout(transfer_row)

        self.account_combo.currentIndexChanged.connect(self._update_transfer_fields)

        self.table = build_table([
            i18n.tr("treasury.col.account"), i18n.tr("treasury.col.amount"), i18n.tr("treasury.col.type"),
            i18n.tr("treasury.col.description"), i18n.tr("treasury.col.date"),
            i18n.tr("treasury.col.phone"), i18n.tr("treasury.col.receipt"),
        ])
        layout.addWidget(self.table)

        return tab

    def _update_transfer_fields(self):
        account_id = self.account_combo.currentData()
        is_transfer = self._account_types.get(account_id) in TRANSFER_ACCOUNT_TYPES
        self.phone_label.setVisible(is_transfer)
        self.phone_input.setVisible(is_transfer)
        self.attach_receipt_btn.setVisible(is_transfer)
        if not is_transfer:
            self.phone_input.clear()
        show_preview = is_transfer and self._pending_receipt is not None
        self.receipt_preview_label.setVisible(show_preview)
        self.remove_receipt_btn.setVisible(show_preview)

    def attach_receipt(self):
        clipboard_image = QApplication.clipboard().image()
        if not clipboard_image.isNull():
            pixmap = QPixmap.fromImage(clipboard_image)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, i18n.tr("treasury.open_image_title"), "", "Images (*.png *.jpg *.jpeg *.bmp)"
            )
            if not path:
                return
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return
        self._pending_receipt = pixmap
        self.receipt_preview_label.setPixmap(
            pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._update_transfer_fields()

    def remove_pending_receipt(self):
        self._pending_receipt = None
        self.receipt_preview_label.clear()
        self._update_transfer_fields()

    def _save_pending_receipt(self):
        try:
            filename = f"receipt_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}.png"
            path = os.path.join(db_config.receipts_dir(), filename)
            if not self._pending_receipt.save(path, "PNG"):
                raise IOError("QPixmap.save() returned False")
            return path
        except Exception as e:
            warn(self, i18n.tr("treasury.error_image_save_failed", error=e))
            return None

    def _refresh_daily(self):
        while self.cards_row.count():
            item = self.cards_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        accounts = db.fetch_all("SELECT * FROM treasury_accounts")
        self._account_types = {a["id"]: a["type"] for a in accounts}

        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for a in accounts:
            self.account_combo.addItem(a["name"], a["id"])
        self.account_combo.blockSignals(False)
        self._update_transfer_fields()

        for a in accounts:
            variant = "primary" if a["balance"] >= 0 else "negative"
            card = Card(a["name"], fmt_money(a["balance"]), variant=variant)
            card.clicked.connect(lambda acc=a: self.show_account_detail(acc))
            self.cards_row.addWidget(card)

        rows = db.fetch_all(
            """SELECT t.*, a.name as account_name FROM treasury_transactions t
               LEFT JOIN treasury_accounts a ON a.id = t.account_id
               ORDER BY t.date DESC LIMIT 300"""
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.table, i, [
                r["account_name"] or "-", fmt_money(r["amount"]),
                i18n.tr("treasury.direction_in") if r["type"] == "in" else i18n.tr("treasury.direction_out"),
                r["description"] or "-", r["date"], r["phone_number"] or "-", "",
            ])
            _receipt_button(self.table, i, 6, r["receipt_image_path"])

    def show_account_detail(self, account):
        AccountDetailDialog(account).exec()

    def add_transaction(self):
        account_id = self.account_combo.currentData()
        amount = self.amount_input.value()
        if not account_id or amount <= 0:
            warn(self, i18n.tr("treasury.error_invalid_transaction"))
            return
        direction = "in" if self.type_combo.currentIndex() == 0 else "out"
        sign = 1 if direction == "in" else -1

        is_transfer = self._account_types.get(account_id) in TRANSFER_ACCOUNT_TYPES
        phone = (self.phone_input.text().strip() or None) if is_transfer else None
        receipt_path = None
        if is_transfer and self._pending_receipt is not None:
            receipt_path = self._save_pending_receipt()
            if receipt_path is None:
                return

        db.execute("UPDATE treasury_accounts SET balance = balance + ? WHERE id=?", (sign * amount, account_id))
        db.execute(
            """INSERT INTO treasury_transactions (account_id, amount, type, description, phone_number, receipt_image_path)
               VALUES (?,?,?,?,?,?)""",
            (account_id, amount, direction, self.desc_input.text().strip(), phone, receipt_path),
        )
        info(self, i18n.tr("treasury.notice_transaction_recorded"))
        self.amount_input.setValue(0)
        self.desc_input.clear()
        self.phone_input.clear()
        self._pending_receipt = None
        self.receipt_preview_label.clear()
        self.refresh()

    def _record_treasury_delta(self, account_id, delta, description):
        """delta: القيمة اللي هتتضاف لرصيد الحساب - ممكن تكون سالبة (لو الرصيد
        قبل القفل كان سالب أصلًا، أو لو بنرجّع حساب لصفر من رصيد سالب)."""
        if not delta:
            return
        ttype = "in" if delta > 0 else "out"
        db.execute(
            "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
            (account_id, abs(delta), ttype, description),
        )
        db.execute("UPDATE treasury_accounts SET balance = balance + ? WHERE id=?", (delta, account_id))

    def close_day(self):
        accounts = db.fetch_all("SELECT * FROM treasury_accounts WHERE type <> 'general'")
        to_close = [a for a in accounts if a["balance"]]
        total = sum(a["balance"] for a in to_close)
        if not total:
            warn(self, i18n.tr("treasury.error_nothing_to_close"))
            return
        if not confirm(self, i18n.tr("treasury.confirm_close_day", total=fmt_money(total))):
            return
        general = db.fetch_one("SELECT * FROM treasury_accounts WHERE type='general'")
        if not general:
            warn(self, i18n.tr("treasury.error_no_general_account"))
            return

        closing_id = db.execute(
            "INSERT INTO day_closings (total_amount, closed_by) VALUES (?,?)",
            (total, self.user["username"]),
        )
        for a in to_close:
            db.execute(
                "INSERT INTO day_closing_items (day_closing_id, account_id, account_name, amount) VALUES (?,?,?,?)",
                (closing_id, a["id"], a["name"], a["balance"]),
            )
            self._record_treasury_delta(
                a["id"], -a["balance"], i18n.tr("treasury.close_tx_desc", id=closing_id)
            )
        self._record_treasury_delta(general["id"], total, i18n.tr("treasury.close_tx_desc_general", id=closing_id))

        info(self, i18n.tr("treasury.notice_day_closed", total=fmt_money(total)))
        self.refresh()

    # ---------------- تبويب رأس المال ----------------

    def _build_capital_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        cards_row = QHBoxLayout()
        self.capital_card = Card(i18n.tr("treasury.capital_card_title"), fmt_money(0), variant="primary")
        cards_row.addWidget(self.capital_card)
        cards_row.addStretch()
        layout.addLayout(cards_row)

        form = QHBoxLayout()
        self.capital_amount_input = QDoubleSpinBox()
        self.capital_amount_input.setRange(0, 100_000_000)
        form.addWidget(QLabel(i18n.tr("treasury.amount_label")))
        form.addWidget(self.capital_amount_input)

        self.capital_desc_input = QLineEdit()
        self.capital_desc_input.setPlaceholderText(i18n.tr("treasury.capital_description_placeholder"))
        form.addWidget(self.capital_desc_input)

        add_btn = QPushButton(i18n.tr("party.add_button"))
        add_btn.clicked.connect(self.add_capital_entry)
        form.addWidget(add_btn)
        layout.addLayout(form)

        self.capital_table = build_table([
            i18n.tr("treasury.capital_col.date"), i18n.tr("treasury.capital_col.amount"),
            i18n.tr("treasury.capital_col.description"), i18n.tr("treasury.capital_col.added_by"),
        ])
        layout.addWidget(self.capital_table)

        delete_btn = QPushButton(i18n.tr("expenses.delete_selected"))
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self.delete_capital_entry)
        layout.addWidget(delete_btn)

        return tab

    def _refresh_capital(self):
        total = db.fetch_one("SELECT COALESCE(SUM(amount),0) v FROM capital_entries")["v"]
        self.capital_card.set_value(fmt_money(total))
        rows = db.fetch_all("SELECT * FROM capital_entries ORDER BY date DESC, id DESC")
        self.capital_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.capital_table, i, [
                r["date"], fmt_money(r["amount"]), r["description"] or "-", r["created_by"] or "-"
            ])
        self._capital_rows_cache = rows

    def add_capital_entry(self):
        amount = self.capital_amount_input.value()
        if amount <= 0:
            warn(self, i18n.tr("expenses.error_invalid_amount"))
            return
        db.execute(
            "INSERT INTO capital_entries (amount, description, created_by) VALUES (?,?,?)",
            (amount, self.capital_desc_input.text().strip(), self.user["username"]),
        )
        info(self, i18n.tr("treasury.notice_capital_recorded"))
        self.capital_amount_input.setValue(0)
        self.capital_desc_input.clear()
        self.refresh()

    def delete_capital_entry(self):
        row = self.capital_table.currentRow()
        if row < 0 or row >= len(self._capital_rows_cache):
            warn(self, i18n.tr("treasury.error_select_capital_entry"))
            return
        entry = self._capital_rows_cache[row]
        if not confirm(self, i18n.tr("treasury.confirm_delete_capital")):
            return
        db.execute("DELETE FROM capital_entries WHERE id=?", (entry["id"],))
        self.refresh()

    # ---------------- تبويب سجل الإغلاقات اليومية ----------------

    def _build_closings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.month_summary_label = QLabel()
        self.month_summary_label.setStyleSheet("font-weight:bold;")
        layout.addWidget(self.month_summary_label)

        self.closings_table = build_table([
            i18n.tr("treasury.closings_col.datetime"), i18n.tr("treasury.closings_col.total"),
            i18n.tr("treasury.closings_col.by"),
        ])
        self.closings_table.cellClicked.connect(self.show_closing_detail)
        layout.addWidget(self.closings_table)

        hint = QLabel(i18n.tr("treasury.closings_hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        layout.addWidget(hint)

        return tab

    def _refresh_closings(self):
        month_total = db.fetch_one(
            "SELECT COALESCE(SUM(total_amount),0) v FROM day_closings "
            "WHERE LEFT(closed_at,7) = LEFT(CONVERT(varchar(19), GETDATE(),120),7)"
        )["v"]
        self.month_summary_label.setText(i18n.tr("treasury.month_total_summary", total=fmt_money(month_total)))
        rows = db.fetch_all("SELECT * FROM day_closings ORDER BY closed_at DESC")
        self.closings_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.closings_table, i, [r["closed_at"], fmt_money(r["total_amount"]), r["closed_by"] or "-"])
        self._closings_rows_cache = rows

    def show_closing_detail(self, row, _col):
        if row < 0 or row >= len(self._closings_rows_cache):
            return
        closing = self._closings_rows_cache[row]
        items = db.fetch_all("SELECT * FROM day_closing_items WHERE day_closing_id=?", (closing["id"],))
        DayClosingDetailDialog(closing, items).exec()

    # ---------------- عام ----------------

    def refresh(self):
        self._refresh_daily()
        self._refresh_capital()
        self._refresh_closings()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
