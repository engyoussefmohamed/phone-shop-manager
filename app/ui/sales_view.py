import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QDoubleSpinBox, QSpinBox, QTabWidget, QListWidget, QListWidgetItem, QDialog,
    QMessageBox, QFileDialog, QDialogButtonBox
)
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintDialog

from app import database as db
from app import i18n
from app.utils import palette as pal
from app.utils.widgets import build_table, fill_row, warn, info, confirm, search_box, fmt_money

PAYMENT_TYPE_KEYS = {
    "cash": "payment.cash", "wallet": "payment.wallet", "instapay": "payment.instapay",
    "visa": "payment.visa", "credit": "payment.credit",
}
PAYMENT_ACCOUNT_TYPE = {"cash": "cash", "wallet": "wallet", "instapay": "instapay", "credit": "cash"}
VISA_SETTLEMENT_DAYS = 15


def payment_type_label(code):
    return i18n.tr(PAYMENT_TYPE_KEYS.get(code, code))


def payment_type_from_label(label):
    for code, key in PAYMENT_TYPE_KEYS.items():
        if i18n.tr(key) == label:
            return code
    return None


def _debt_for_sale(sale):
    return db.fetch_one(
        "SELECT * FROM debts WHERE party_type='customer' AND description=?",
        (i18n.tr("sales.debt_desc", id=sale["id"]),),
    )


def return_sale(parent, sale):
    """بيرجّع فاتورة بيع بالكامل (مرتجع): يرجّع كمية الأصناف للمخزون،
    يعكس أثر الخزنة لو اتحصّل فلوس، يلغي أي دين مرتبط بيها (لو لسه محدش
    دفع منه حاجة)، ويفك ربط أي طلب صيانة كان متسجل عليها. بيرفض العملية
    لو فيه دفعات آجل اتسددت فعلاً على الدين المرتبط، عشان محاسبيًا يبقى
    محتاج تسوية يدوية بدل تراجع تلقائي معقد."""
    debt = _debt_for_sale(sale)
    if debt:
        paid_on_debt = db.fetch_one(
            "SELECT COALESCE(SUM(amount),0) v FROM debt_payments WHERE debt_id=?", (debt["id"],)
        )["v"]
        if paid_on_debt > 0.001:
            warn(parent, i18n.tr("sales.error_return_has_payments"))
            return False

    if not confirm(parent, i18n.tr("sales.confirm_return_all", invoice=sale["invoice_no"] or sale["id"])):
        return False

    try:
        items = db.fetch_all("SELECT * FROM sale_items WHERE sale_id=?", (sale["id"],))
        for item in items:
            if item["product_id"] is not None:
                db.execute(
                    "UPDATE products SET quantity = quantity + ?, status='in_stock' WHERE id=?",
                    (item["qty"], item["product_id"]),
                )
        db.execute("UPDATE maintenance SET sale_id=NULL WHERE sale_id=?", (sale["id"],))

        if sale["payment_type"] == "visa":
            settlement = db.fetch_one(
                "SELECT * FROM company_settlements WHERE notes LIKE ?",
                (f"%فاتورة بيع {sale['invoice_no']}%",),
            )
            if settlement:
                if settlement["status"] == "collected" and settlement["treasury_transaction_id"]:
                    tx = db.fetch_one(
                        "SELECT * FROM treasury_transactions WHERE id=?", (settlement["treasury_transaction_id"],)
                    )
                    if tx:
                        db.execute(
                            "UPDATE treasury_accounts SET balance = balance - ? WHERE id=?",
                            (tx["amount"], tx["account_id"]),
                        )
                        db.execute("DELETE FROM treasury_transactions WHERE id=?", (tx["id"],))
                db.execute("DELETE FROM company_settlements WHERE id=?", (settlement["id"],))
        elif sale["paid_amount"] > 0:
            account_type = PAYMENT_ACCOUNT_TYPE.get(sale["payment_type"], "cash")
            account = (
                db.fetch_one("SELECT id FROM treasury_accounts WHERE type=? LIMIT 1", (account_type,))
                or db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
            )
            if account:
                db.execute(
                    "UPDATE treasury_accounts SET balance = balance - ? WHERE id=?", (sale["paid_amount"], account["id"])
                )
                db.execute(
                    "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                    (account["id"], sale["paid_amount"], "out", i18n.tr("sales.return_tx_desc", id=sale["id"])),
                )

        if debt:
            db.execute("DELETE FROM debts WHERE id=?", (debt["id"],))

        db.execute("DELETE FROM sales WHERE id=?", (sale["id"],))
    except Exception as e:
        warn(parent, i18n.tr("sales.error_return_failed", error=e))
        return False

    info(parent, i18n.tr("sales.notice_returned"))
    return True


def return_sale_item(parent, sale, item):
    """بيرجّع صنف واحد بس من فاتورة (مش الفاتورة كلها): بيرجّع كميته
    للمخزون، وبيقلل قيمته من إجمالي الفاتورة. لو كان فيه دين لسه متسدد
    (آجل)، قيمة الصنف بتتخصم من الدين الأول؛ ولو الدين مش كفاية (يعني
    جزء من الصنف كان اتدفع فعلاً)، الباقي بيترجع كاش من الخزنة. الجزء
    ده بيشتغل صح مع كل طرق الدفع عدا الفيزا (فيها تسوية يدوية من شاشة
    "حساب شركات" لو لزم، لتعقيد ربطها بمبلغ جزئي)."""
    item_value = item["price"] * item["qty"]
    if not confirm(parent, i18n.tr("sales.confirm_return_item", name=item["product_name"], value=fmt_money(item_value))):
        return False

    debt = _debt_for_sale(sale)
    if debt:
        paid_on_debt = db.fetch_one(
            "SELECT COALESCE(SUM(amount),0) v FROM debt_payments WHERE debt_id=?", (debt["id"],)
        )["v"]
        remaining_before = debt["amount"]
    else:
        paid_on_debt = 0
        remaining_before = max(0.0, sale["total"] - sale["paid_amount"])

    debt_reduction = min(item_value, remaining_before)
    cash_refund = item_value - debt_reduction

    try:
        if item["product_id"] is not None:
            db.execute(
                "UPDATE products SET quantity = quantity + ?, status='in_stock' WHERE id=?",
                (item["qty"], item["product_id"]),
            )

        new_total = sale["total"] - item_value
        new_paid = sale["paid_amount"]

        if debt and debt_reduction > 0:
            new_debt_amount = max(0.0, debt["amount"] - debt_reduction)
            new_original = max(0.0, (debt["original_amount"] or debt["amount"]) - debt_reduction)
            status = "paid" if new_debt_amount <= 0.001 else "pending"
            db.execute(
                "UPDATE debts SET amount=?, original_amount=?, status=? WHERE id=?",
                (new_debt_amount, new_original, status, debt["id"]),
            )

        if cash_refund > 0.001 and sale["payment_type"] != "visa":
            account_type = PAYMENT_ACCOUNT_TYPE.get(sale["payment_type"], "cash")
            account = (
                db.fetch_one("SELECT id FROM treasury_accounts WHERE type=? LIMIT 1", (account_type,))
                or db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
            )
            if account:
                db.execute(
                    "UPDATE treasury_accounts SET balance = balance - ? WHERE id=?", (cash_refund, account["id"])
                )
                db.execute(
                    "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                    (account["id"], cash_refund, "out", i18n.tr("sales.partial_return_tx_desc", name=item["product_name"], id=sale["id"])),
                )
            new_paid = sale["paid_amount"] - cash_refund
        elif cash_refund > 0.001 and sale["payment_type"] == "visa":
            # فيزا: مش بنلمس حساب شركات تلقائي هنا (معقد نربطه بمبلغ جزئي) -
            # بس نقفل قيمة المدفوع على الإجمالي الجديد ونطلب مراجعة يدوية.
            new_paid = min(sale["paid_amount"], new_total)

        db.execute("UPDATE sales SET total=?, paid_amount=? WHERE id=?", (new_total, new_paid, sale["id"]))
        db.execute("DELETE FROM sale_items WHERE id=?", (item["id"],))
    except Exception as e:
        warn(parent, i18n.tr("sales.error_return_item_failed", error=e))
        return False

    msg = i18n.tr("sales.notice_item_returned")
    if sale["payment_type"] == "visa" and cash_refund > 0.001:
        msg += i18n.tr("sales.notice_item_returned_visa_note")
    info(parent, msg)
    return True


class SaleDetailDialog(QDialog):
    def __init__(self, sale, parent=None):
        super().__init__(parent)
        self.sale_id = sale["id"]
        self.returned = False  # اتغيّر أي حاجة (مرتجع كامل أو جزئي) محتاجة تحديث السجل بره
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        hint = QLabel(i18n.tr("sales.detail_hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        layout.addWidget(hint)

        self.table = build_table([i18n.tr("sales.col.item"), i18n.tr("sales.col.price"), i18n.tr("sales.col.qty"), i18n.tr("sales.col.total")])
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        return_item_btn = QPushButton(i18n.tr("sales.return_item_button"))
        return_item_btn.setObjectName("SecondaryButton")
        return_item_btn.clicked.connect(self._do_return_item)
        buttons.addWidget(return_item_btn)

        return_all_btn = QPushButton(i18n.tr("sales.return_all_button"))
        return_all_btn.setObjectName("DangerButton")
        return_all_btn.clicked.connect(self._do_return_all)
        buttons.addWidget(return_all_btn)
        buttons.addStretch()
        close_btn = QPushButton(i18n.tr("debts.close_button"))
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._refresh()

    def _refresh(self):
        self.sale = db.fetch_one(
            """SELECT s.*, c.name as customer_name FROM sales s
               LEFT JOIN customers c ON c.id = s.customer_id WHERE s.id=?""",
            (self.sale_id,),
        )
        if not self.sale:
            self.reject()
            return
        self.setWindowTitle(i18n.tr("sales.detail_title", invoice=self.sale["invoice_no"] or self.sale["id"]))
        self.info_label.setText(i18n.tr(
            "sales.detail_info",
            customer=self.sale.get("customer_name") or i18n.tr("sales.cash_customer"),
            date=self.sale["created_at"],
            payment=payment_type_label(self.sale["payment_type"]),
            total=fmt_money(self.sale["total"]), paid=fmt_money(self.sale["paid_amount"]),
            remaining=fmt_money(self.sale["total"] - self.sale["paid_amount"]),
        ))

        self.items = db.fetch_all(
            "SELECT id, product_id, product_name, price, qty FROM sale_items WHERE sale_id=?", (self.sale_id,)
        )
        self.table.setRowCount(len(self.items))
        for i, it in enumerate(self.items):
            fill_row(self.table, i, [it["product_name"], fmt_money(it["price"]), it["qty"], fmt_money(it["price"] * it["qty"])])

    def _do_return_item(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.items):
            warn(self, i18n.tr("sales.error_select_item_first"))
            return
        if len(self.items) == 1:
            warn(self, i18n.tr("sales.error_last_item"))
            return
        if return_sale_item(self, self.sale, self.items[row]):
            self.returned = True
            self._refresh()

    def _do_return_all(self):
        if return_sale(self, self.sale):
            self.returned = True
            self.accept()


class SalesView(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.cart = []  # list of dict: product_id, name, price, cost, qty, available
        self._paid_auto = True  # لسه المستخدم مغيرش المبلغ المدفوع بإيده

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("nav.sales"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_new_sale_tab(), i18n.tr("sales.tab.new"))
        tabs.addTab(self._build_history_tab(), i18n.tr("sales.tab.history"))
        layout.addWidget(tabs)

    # ---------------- New Sale Tab ----------------

    def _build_new_sale_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        search_row = QHBoxLayout()
        self.product_search = search_box(i18n.tr("sales.search_placeholder"))
        self.product_search.textChanged.connect(self._update_search_results)
        self.product_search.returnPressed.connect(self._scan_add)
        search_row.addWidget(self.product_search)

        maintenance_btn = QPushButton(i18n.tr("sales.receive_maintenance_button"))
        maintenance_btn.setObjectName("SecondaryButton")
        maintenance_btn.clicked.connect(self._receive_maintenance)
        search_row.addWidget(maintenance_btn)
        v.addLayout(search_row)

        self.results_list = QListWidget()
        self.results_list.setMaximumHeight(120)
        self.results_list.itemDoubleClicked.connect(self._add_from_results)
        v.addWidget(self.results_list)

        self.cart_table = build_table([i18n.tr("sales.col.item"), i18n.tr("sales.col.price"), i18n.tr("sales.col.qty"), i18n.tr("sales.col.total"), ""])
        v.addWidget(self.cart_table)

        remove_btn = QPushButton(i18n.tr("sales.remove_item_button"))
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.clicked.connect(self._remove_selected)
        v.addWidget(remove_btn)

        bottom = QHBoxLayout()

        self.customer_combo = QComboBox()
        self._reload_customers()
        bottom.addWidget(QLabel(i18n.tr("sales.customer_label")))
        bottom.addWidget(self.customer_combo)

        self.payment_type = QComboBox()
        self.payment_type.addItems([i18n.tr(k) for k in ["payment.cash", "payment.wallet", "payment.instapay", "payment.visa", "payment.credit"]])
        self.payment_type.currentTextChanged.connect(self._update_payment_fields)
        bottom.addWidget(QLabel(i18n.tr("sales.payment_method_label")))
        bottom.addWidget(self.payment_type)

        self.company_label = QLabel(i18n.tr("sales.settlement_company_label"))
        self.company_combo = QComboBox()
        self.company_combo.setEditable(True)
        self._reload_settlement_companies()
        bottom.addWidget(self.company_label)
        bottom.addWidget(self.company_combo)

        self.paid_amount = QDoubleSpinBox()
        self.paid_amount.setRange(0, 10_000_000)
        self.paid_amount.valueChanged.connect(self._on_paid_amount_changed)
        bottom.addWidget(QLabel(i18n.tr("sales.paid_amount_label")))
        bottom.addWidget(self.paid_amount)

        v.addLayout(bottom)

        self.total_label = QLabel(i18n.tr("sales.total_label", total=fmt_money(0)))
        self.total_label.setStyleSheet("font-size:18px; font-weight:bold;")
        v.addWidget(self.total_label)

        self._update_payment_fields(self.payment_type.currentText())

        confirm_btn = QPushButton(i18n.tr("sales.confirm_sale_button"))
        confirm_btn.clicked.connect(self._confirm_sale)
        v.addWidget(confirm_btn)

        return w

    def _on_paid_amount_changed(self, value):
        self._paid_auto = False

    def _update_payment_fields(self, text):
        is_visa = (text == i18n.tr("payment.visa"))
        self.company_label.setVisible(is_visa)
        self.company_combo.setVisible(is_visa)
        # تغيير طريقة الدفع يرجّع المبلغ المدفوع لقيمته الافتراضية:
        # صفر لو "آجل" (البيع كله دين لحد ما العميل يدفع)، أو الإجمالي كامل غير كده.
        self._paid_auto = True
        self._recalc_total()

    def _reload_settlement_companies(self):
        current = self.company_combo.currentText().strip()
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        for c in db.fetch_all("SELECT name FROM settlement_companies ORDER BY name"):
            self.company_combo.addItem(c["name"])
        self.company_combo.blockSignals(False)
        if current:
            self.company_combo.setCurrentText(current)

    def _reload_customers(self):
        self.customer_combo.clear()
        self.customer_combo.addItem(i18n.tr("sales.cash_customer_option"), None)
        for c in db.fetch_all("SELECT id, name FROM customers ORDER BY name"):
            self.customer_combo.addItem(c["name"], c["id"])

    def _update_search_results(self, text):
        self.results_list.clear()
        if not text.strip():
            return
        term = f"%{text.strip()}%"
        rows = db.fetch_all(
            """SELECT * FROM products WHERE status='in_stock' AND quantity>0
               AND (name LIKE ? OR imei LIKE ? OR imei2 LIKE ? OR model LIKE ? OR code LIKE ?) LIMIT 20""",
            (term, term, term, term, term),
        )
        for p in rows:
            model_suffix = i18n.tr("purchases.model_suffix", model=p["model"]) if p["model"] else ""
            label = i18n.tr(
                "sales.search_result_label",
                name=p["name"], model_suffix=model_suffix, imei=p["imei"] or "-",
                qty=p["quantity"], price=fmt_money(p["sale_price"]),
            )
            item = QListWidgetItem(label)
            item.setData(1000, p)
            self.results_list.addItem(item)

    def _add_from_results(self, item):
        p = item.data(1000)
        self._add_product_to_cart(p)
        self.product_search.clear()
        self.results_list.clear()

    def _scan_add(self):
        """بيتنادى لما يتضغط Enter في مربع البحث - ده اللي بيحصل تلقائي
        لما قارئ الباركود/QR الفعلي يمسح كود ويبعته زي الكيبورد + Enter."""
        code = self.product_search.text().strip()
        if not code:
            return
        p = db.fetch_one(
            "SELECT * FROM products WHERE status='in_stock' AND quantity>0 AND (imei=? OR imei2=? OR code=?)",
            (code, code, code),
        )
        if not p:
            warn(self, i18n.tr("sales.error_not_found_in_stock", code=code))
            return
        self._add_product_to_cart(p)
        self.product_search.clear()
        self.results_list.clear()

    def _add_product_to_cart(self, p):
        for c in self.cart:
            if c["product_id"] == p["id"]:
                warn(self, i18n.tr("sales.error_duplicate_item"))
                return
        self.cart.append({
            "product_id": p["id"],
            "maintenance_id": None,
            "name": p["name"] + (f" ({p['imei']})" if p["imei"] else ""),
            "price": p["sale_price"],
            "cost": p["wholesale_price"],
            "qty": 1,
            "available": p["quantity"],
            "min_price": max(0.0, p["sale_price"] - (p.get("max_discount") or 0)),
        })
        self._refresh_cart()

    def _receive_maintenance(self):
        """يفتح شاشة استلام جهاز صيانة من جوه المبيعات - بمجرد ما تحفظ الطلب،
        بيتسجل في شاشة الصيانة، وسعر الصيانة المطلوب من العميل بيتضاف
        كصنف في الفاتورة الحالية ويدخل في الإجمالي."""
        from app.ui.maintenance_view import MaintenanceDialog

        dlg = MaintenanceDialog()
        if not dlg.exec():
            return
        d = dlg.get_data()
        if not d["device_name"]:
            warn(self, i18n.tr("maintenance.error_no_device"))
            return

        maintenance_id = db.execute(
            """INSERT INTO maintenance (customer_name, customer_phone, device_name, imei, problem_description, status, cost,
               customer_price, notes) VALUES (?,?,?,?,?,?,?,?,?)""",
            (d["customer_name"], d["customer_phone"], d["device_name"], d["imei"], d["problem_description"], d["status"], d["cost"],
             d["customer_price"], d["notes"]),
        )

        self.cart.append({
            "product_id": None,
            "maintenance_id": maintenance_id,
            "name": i18n.tr("sales.maintenance_item_name", device=d["device_name"]) + (f" ({d['imei']})" if d["imei"] else ""),
            "price": d["customer_price"],
            "cost": d["cost"],
            "qty": 1,
            "available": 1,
            "min_price": 0.0,
        })
        self._refresh_cart()
        info(self, i18n.tr("sales.notice_maintenance_added"))

    def _can_override_min_price(self):
        """الأدمن والسوبر فايزر بس يقدروا يبيعوا تحت الحد الأدنى للسعر
        (استثناء تسعير مصرّح بيه لتفاوض عميل مثلاً) - الموظف العادي لأ."""
        return self.user["role"] in ("admin", "supervisor")

    def _refresh_cart(self):
        can_override = self._can_override_min_price()
        self.cart_table.setRowCount(len(self.cart))
        for i, c in enumerate(self.cart):
            subtotal = c["price"] * c["qty"]
            fill_row(self.cart_table, i, [c["name"], "", "", fmt_money(subtotal), ""])

            price_spin = QDoubleSpinBox()
            price_spin.setRange(0, 100_000_000)
            price_spin.setDecimals(2)
            price_spin.setValue(c["price"])
            if not can_override and c.get("min_price", 0) > 0:
                price_spin.setToolTip(i18n.tr("sales.min_price_tooltip", price=fmt_money(c["min_price"])))
            price_spin.valueChanged.connect(lambda value, row=i: self._update_cart_price(row, value))
            self.cart_table.setCellWidget(i, 1, price_spin)

            max_qty = c["available"] if c["product_id"] is not None else 999
            qty_spin = QSpinBox()
            qty_spin.setRange(1, max(1, max_qty))
            qty_spin.setValue(c["qty"])
            qty_spin.valueChanged.connect(lambda value, row=i: self._update_cart_qty(row, value))
            self.cart_table.setCellWidget(i, 2, qty_spin)
        return self._recalc_total()

    def _update_cart_price(self, row, value):
        if row >= len(self.cart):
            return
        c = self.cart[row]
        min_price = c.get("min_price", 0)
        if not self._can_override_min_price() and value < min_price - 0.001:
            warn(self, i18n.tr("sales.error_price_below_min", min=fmt_money(min_price)))
            c["price"] = min_price
            spin = self.cart_table.cellWidget(row, 1)
            if spin:
                spin.blockSignals(True)
                spin.setValue(min_price)
                spin.blockSignals(False)
        else:
            c["price"] = value
        subtotal_item = self.cart_table.item(row, 3)
        if subtotal_item:
            subtotal_item.setText(fmt_money(c["price"] * c["qty"]))
        self._recalc_total()

    def _update_cart_qty(self, row, value):
        if row >= len(self.cart):
            return
        self.cart[row]["qty"] = value
        subtotal_item = self.cart_table.item(row, 3)
        if subtotal_item:
            subtotal_item.setText(fmt_money(self.cart[row]["price"] * value))
        self._recalc_total()

    def _recalc_total(self):
        total = sum(c["price"] * c["qty"] for c in self.cart)
        self.total_label.setText(i18n.tr("sales.total_label", total=fmt_money(total)))
        if self._paid_auto:
            # آجل = افتراضيًا العميل ميدفعش حاجة دلوقتي؛ أي طريقة تانية = مدفوع بالكامل.
            # القيمة دي بتتغير تلقائي بس لحد ما المستخدم يعدلها بإيده (مثلاً عربون جزئي).
            target = 0.0 if self.payment_type.currentText() == i18n.tr("payment.credit") else total
            self.paid_amount.blockSignals(True)
            self.paid_amount.setValue(target)
            self.paid_amount.blockSignals(False)
        return total

    def _remove_selected(self):
        row = self.cart_table.currentRow()
        if row < 0 or row >= len(self.cart):
            return
        self.cart.pop(row)
        self._refresh_cart()

    def _confirm_sale(self):
        if not self.cart:
            warn(self, i18n.tr("sales.cart_empty"))
            return
        if not self._can_override_min_price():
            for c in self.cart:
                if c["price"] < c.get("min_price", 0) - 0.001:
                    warn(self, i18n.tr(
                        "sales.error_price_below_min_confirm",
                        name=c["name"], price=fmt_money(c["price"]), min=fmt_money(c["min_price"]),
                    ))
                    return
        total = sum(c["price"] * c["qty"] for c in self.cart)
        payment_type = payment_type_from_label(self.payment_type.currentText())
        paid = self.paid_amount.value()
        customer_id = self.customer_combo.currentData()
        customer_name = self.customer_combo.currentText()

        if payment_type == "credit" and customer_id is None:
            warn(self, i18n.tr("sales.error_credit_needs_customer"))
            return

        company_name = ""
        if payment_type == "visa":
            company_name = self.company_combo.currentText().strip()
            if not company_name:
                warn(self, i18n.tr("sales.error_no_settlement_company"))
                return

        if not confirm(self, i18n.tr("sales.confirm_sale", total=fmt_money(total))):
            return

        try:
            invoice_no = f"INV-{db.now_str().replace(' ', '').replace(':', '').replace('-', '')}"
            sale_id = db.execute(
                "INSERT INTO sales (invoice_no, customer_id, total, paid_amount, payment_type, created_by) VALUES (?,?,?,?,?,?)",
                (invoice_no, customer_id, total, paid, payment_type, self.user["username"]),
            )
            for c in self.cart:
                db.execute(
                    "INSERT INTO sale_items (sale_id, product_id, product_name, price, cost_price, qty) VALUES (?,?,?,?,?,?)",
                    (sale_id, c["product_id"], c["name"], c["price"], c["cost"], c["qty"]),
                )
                if c["product_id"] is not None:
                    remaining_qty = db.fetch_one("SELECT quantity FROM products WHERE id=?", (c["product_id"],))["quantity"]
                    new_qty = max(0, remaining_qty - c["qty"])
                    status = "sold" if new_qty == 0 else "in_stock"
                    db.execute("UPDATE products SET quantity=?, status=? WHERE id=?", (new_qty, status, c["product_id"]))
                if c.get("maintenance_id"):
                    db.execute("UPDATE maintenance SET sale_id=? WHERE id=?", (sale_id, c["maintenance_id"]))

            if paid > 0:
                if payment_type == "visa":
                    # مش بيتضاف للخزنة على طول - الفلوس بتفضل معلقة في "حساب شركات"
                    # لحد ما تتحدد "تم التحصيل" بعد ما تنزل فعليًا للمحل.
                    tx_date = db.today_str()
                    expected_date = (
                        datetime.date.today() + datetime.timedelta(days=VISA_SETTLEMENT_DAYS)
                    ).isoformat()
                    db.execute(
                        "IF NOT EXISTS (SELECT 1 FROM settlement_companies WHERE name=?) "
                        "INSERT INTO settlement_companies (name) VALUES (?)",
                        (company_name, company_name),
                    )
                    db.execute(
                        """INSERT INTO company_settlements (company_name, amount, transaction_date, expected_date, notes)
                           VALUES (?,?,?,?,?)""",
                        (company_name, paid, tx_date, expected_date, i18n.tr("sales.visa_settlement_desc", invoice=invoice_no)),
                    )
                else:
                    account_type = PAYMENT_ACCOUNT_TYPE.get(payment_type, "cash")
                    account = (
                        db.fetch_one("SELECT id FROM treasury_accounts WHERE type=? LIMIT 1", (account_type,))
                        or db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
                    )
                    if account:
                        db.execute(
                            "UPDATE treasury_accounts SET balance = balance + ? WHERE id=?", (paid, account["id"])
                        )
                        db.execute(
                            "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                            (account["id"], paid, "in", i18n.tr("sales.treasury_tx_desc", id=sale_id)),
                        )

            remaining = total - paid
            if remaining > 0.001:
                db.execute(
                    """INSERT INTO debts (party_type, party_id, party_name, amount, original_amount, debt_type, description)
                       VALUES ('customer', ?, ?, ?, ?, 'owed_to_me', ?)""",
                    (customer_id, customer_name, remaining, remaining, i18n.tr("sales.debt_desc", id=sale_id)),
                )
        except Exception as e:
            warn(self, i18n.tr("sales.error_sale_failed", error=e))
            return

        msg = i18n.tr("sales.notice_recorded")
        if payment_type == "visa" and paid > 0:
            msg += i18n.tr("sales.notice_visa_pending_note", amount=fmt_money(paid), days=VISA_SETTLEMENT_DAYS)
        info(self, msg)
        self.cart = []
        self._paid_auto = True
        self.payment_type.setCurrentText(i18n.tr("payment.cash"))
        self._refresh_cart()
        self._reload_customers()
        self._refresh_history()

        self._offer_invoice_output(sale_id)

    def _offer_invoice_output(self, sale_id):
        box = QMessageBox(self)
        box.setWindowTitle(i18n.tr("sales.invoice_dialog_title"))
        box.setText(i18n.tr("sales.invoice_dialog_question"))
        print_btn = box.addButton(i18n.tr("sales.print_button"), QMessageBox.AcceptRole)
        pdf_btn = box.addButton(i18n.tr("sales.save_pdf_button"), QMessageBox.ActionRole)
        box.addButton(i18n.tr("sales.no_thanks_button"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is print_btn:
            self._print_invoice(sale_id)
        elif clicked is pdf_btn:
            self._export_invoice_pdf(sale_id)

    # ---------------- History Tab ----------------

    def _build_history_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(i18n.tr("sales.history_hint"))
        hint.setStyleSheet(f"color:{pal.current().TEXT_MUTED};")
        v.addWidget(hint)
        self.history_table = build_table([
            i18n.tr("sales.col.invoice_no"), i18n.tr("sales.col.customer"), i18n.tr("sales.col.total"),
            i18n.tr("sales.col.paid"), i18n.tr("sales.col.payment_method"), i18n.tr("sales.col.date"),
        ])
        self.history_table.cellDoubleClicked.connect(self._open_history_details)
        v.addWidget(self.history_table)

        history_actions = QHBoxLayout()
        details_btn = QPushButton(i18n.tr("sales.details_button"))
        details_btn.clicked.connect(lambda: self._open_history_details(self.history_table.currentRow(), 0))
        history_actions.addWidget(details_btn)

        print_btn = QPushButton(i18n.tr("sales.print_selected_button"))
        print_btn.setObjectName("SecondaryButton")
        print_btn.clicked.connect(self._print_selected_history)
        history_actions.addWidget(print_btn)

        pdf_btn = QPushButton(i18n.tr("sales.save_pdf_selected_button"))
        pdf_btn.setObjectName("SecondaryButton")
        pdf_btn.clicked.connect(self._export_selected_history_pdf)
        history_actions.addWidget(pdf_btn)
        v.addLayout(history_actions)

        self._refresh_history()
        return w

    def _refresh_history(self):
        rows = db.fetch_all(
            """SELECT s.*, c.name as customer_name FROM sales s
               LEFT JOIN customers c ON c.id = s.customer_id
               ORDER BY s.created_at DESC LIMIT 200"""
        )
        self._history_rows = rows
        self.history_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            fill_row(self.history_table, i, [
                r["invoice_no"], r["customer_name"] or i18n.tr("sales.cash_customer"), fmt_money(r["total"]),
                fmt_money(r["paid_amount"]), payment_type_label(r["payment_type"]),
                r["created_at"]
            ])

    def _open_history_details(self, row, col):
        if row < 0 or row >= len(self._history_rows):
            warn(self, i18n.tr("sales.error_select_invoice_first"))
            return
        dlg = SaleDetailDialog(self._history_rows[row], parent=self)
        dlg.exec()
        if dlg.returned:
            self._refresh_history()
            self._reload_customers()

    def _print_selected_history(self):
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._history_rows):
            warn(self, i18n.tr("sales.error_select_invoice_first"))
            return
        self._print_invoice(self._history_rows[row]["id"])

    def _export_selected_history_pdf(self):
        row = self.history_table.currentRow()
        if row < 0 or row >= len(self._history_rows):
            warn(self, i18n.tr("sales.error_select_invoice_first"))
            return
        self._export_invoice_pdf(self._history_rows[row]["id"])

    def showEvent(self, event):
        self._reload_customers()
        self._reload_settlement_companies()
        self._refresh_history()
        super().showEvent(event)

    # ---------------- Invoice printing ----------------

    def _setting(self, key, default=""):
        row = db.fetch_one("SELECT value FROM settings WHERE setting_key=?", (key,))
        return (row["value"] if row and row["value"] else default)

    def _invoice_html_for(self, sale_id):
        sale = db.fetch_one(
            """SELECT s.*, c.name as customer_name FROM sales s
               LEFT JOIN customers c ON c.id = s.customer_id WHERE s.id=?""",
            (sale_id,),
        )
        if not sale:
            warn(self, i18n.tr("sales.error_invoice_not_found"))
            return None
        items = db.fetch_all(
            "SELECT product_name, price, qty FROM sale_items WHERE sale_id=?", (sale_id,)
        )
        return self._build_invoice_html(sale, items), sale

    def _print_invoice(self, sale_id):
        result = self._invoice_html_for(sale_id)
        if not result:
            return
        html, sale = result
        document = QTextDocument()
        document.setHtml(html)

        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(i18n.tr("sales.print_dialog_title"))
        if dlg.exec() == QDialog.Accepted:
            document.print_(printer)

    def _export_invoice_pdf(self, sale_id):
        result = self._invoice_html_for(sale_id)
        if not result:
            return
        html, sale = result
        document = QTextDocument()
        document.setHtml(html)

        default_name = f"{sale['invoice_no'] or sale_id}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, i18n.tr("sales.save_pdf_title"), default_name, "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        document.print_(printer)
        info(self, i18n.tr("sales.notice_pdf_saved", path=path))

    def _build_invoice_html(self, sale, items):
        shop_name = self._setting("shop_name", i18n.tr("app.default_shop_name"))
        shop_phone = self._setting("shop_phone")
        shop_address = self._setting("shop_address")
        contact_line = " - ".join(p for p in [shop_address, shop_phone] if p)

        rows_html = "".join(
            f"<tr><td>{i['product_name']}</td><td align='center'>{fmt_money(i['price'])}</td>"
            f"<td align='center'>{i['qty']}</td><td align='center'>{fmt_money(i['price'] * i['qty'])}</td></tr>"
            for i in items
        )

        remaining = sale["total"] - sale["paid_amount"]
        direction = "rtl" if i18n.get_language() == "ar" else "ltr"
        customer_name = sale["customer_name"] or i18n.tr("sales.cash_customer")

        return f"""
        <div dir="{direction}" style="font-family:Arial; font-size:13px;">
            <h2 style="text-align:center; margin-bottom:2px;">{shop_name}</h2>
            <p style="text-align:center; margin-top:0;">{contact_line}</p>
            <hr>
            <table width="100%">
                <tr>
                    <td>{i18n.tr("sales.invoice.invoice_no_label", no=sale['invoice_no'])}</td>
                    <td align="left">{i18n.tr("sales.invoice.date_label", date=sale['created_at'])}</td>
                </tr>
                <tr>
                    <td>{i18n.tr("sales.invoice.customer_label", customer=customer_name)}</td>
                    <td align="left">{i18n.tr("sales.invoice.cashier_label", cashier=sale['created_by'] or '-')}</td>
                </tr>
                <tr>
                    <td>{i18n.tr("sales.invoice.payment_label", payment=payment_type_label(sale['payment_type']))}</td>
                    <td></td>
                </tr>
            </table>
            <hr>
            <table width="100%" border="1" cellspacing="0" cellpadding="5">
                <tr>
                    <th>{i18n.tr("sales.col.item")}</th><th>{i18n.tr("sales.col.price")}</th>
                    <th>{i18n.tr("sales.col.qty")}</th><th>{i18n.tr("sales.col.total")}</th>
                </tr>
                {rows_html}
            </table>
            <br>
            <table width="100%">
                <tr><td>{i18n.tr("sales.invoice.grand_total")}</td><td align="left">{fmt_money(sale['total'])}</td></tr>
                <tr><td>{i18n.tr("sales.invoice.paid")}</td><td align="left">{fmt_money(sale['paid_amount'])}</td></tr>
                <tr><td>{i18n.tr("sales.invoice.remaining")}</td><td align="left">{fmt_money(remaining)}</td></tr>
            </table>
            <p style="text-align:center; margin-top:24px;">{i18n.tr("sales.invoice.thanks")}</p>
        </div>
        """
