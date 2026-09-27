from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QDoubleSpinBox, QSpinBox, QTabWidget, QLineEdit, QGridLayout,
    QListWidget, QListWidgetItem
)

from app import database as db
from app import i18n
from app.ui.inventory_view import CATEGORIES, STORAGE_OPTIONS, RAM_OPTIONS, CAPACITY_CATEGORIES
from app.utils import palette as pal
from app.utils.widgets import build_table, fill_row, warn, info, confirm, fmt_money


class PurchasesView(QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.cart = []
        self._paid_auto = True  # لسه المستخدم مغيرش المبلغ المدفوع بإيده

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(i18n.tr("purchases.title"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_new_tab(), i18n.tr("purchases.tab.new"))
        tabs.addTab(self._build_history_tab(), i18n.tr("purchases.tab.history"))
        layout.addWidget(tabs)

    def _build_new_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        code_row = QHBoxLayout()
        self.f_code = QLineEdit()
        self.f_code.setPlaceholderText(i18n.tr("purchases.search_placeholder"))
        self.f_code.textChanged.connect(self._search_products)
        self.f_code.returnPressed.connect(self._lookup_exact)
        code_row.addWidget(QLabel(i18n.tr("purchases.search_label")))
        code_row.addWidget(self.f_code)
        new_btn = QPushButton(i18n.tr("purchases.new_item_button"))
        new_btn.setObjectName("SecondaryButton")
        new_btn.clicked.connect(self._reset_item_form)
        code_row.addWidget(new_btn)
        v.addLayout(code_row)

        self._matched_product_id = None
        self.code_results_list = QListWidget()
        self.code_results_list.setMaximumHeight(110)
        self.code_results_list.itemDoubleClicked.connect(self._select_search_result)
        v.addWidget(self.code_results_list)

        self.code_status_label = QLabel("")
        self.code_status_label.setStyleSheet(f"color:{pal.current().TEXT_MUTED}; font-size:12px;")
        v.addWidget(self.code_status_label)

        form_box = QGridLayout()
        self.f_name = QLineEdit()
        self.f_model = QLineEdit()
        self.f_imei = QLineEdit()
        self.f_imei.setPlaceholderText(i18n.tr("purchases.imei1_placeholder"))
        self.f_imei2 = QLineEdit()
        self.f_imei2.setPlaceholderText(i18n.tr("purchases.imei2_placeholder"))
        self.f_qty = QSpinBox(); self.f_qty.setRange(1, 100000); self.f_qty.setValue(1)
        self.f_cost = QDoubleSpinBox(); self.f_cost.setRange(0, 10_000_000)
        self.f_sale = QDoubleSpinBox(); self.f_sale.setRange(0, 10_000_000)

        self.f_category = QComboBox()
        self.f_category.setEditable(True)
        self.f_category.addItems(CATEGORIES)
        self.f_category.currentTextChanged.connect(self._update_spec_fields)

        self.f_condition = QComboBox()
        self.f_condition.addItems(["جديد", "مستعمل"])

        self.storage_label = QLabel(i18n.tr("inventory.field.storage_phone"))
        self.f_storage = QComboBox()
        self.f_storage.setEditable(True)
        self.f_storage.addItems(STORAGE_OPTIONS)
        self.f_storage.lineEdit().setPlaceholderText(i18n.tr("inventory.storage_placeholder"))
        self.ram_label = QLabel(i18n.tr("inventory.field.ram"))
        self.f_ram = QComboBox()
        self.f_ram.addItems(RAM_OPTIONS)
        self.color_label = QLabel(i18n.tr("inventory.field.color"))
        self.f_color = QLineEdit()

        form_box.addWidget(QLabel(i18n.tr("purchases.field.item_name")), 0, 0); form_box.addWidget(self.f_name, 0, 1)
        form_box.addWidget(QLabel(i18n.tr("purchases.field.model")), 0, 2); form_box.addWidget(self.f_model, 0, 3)
        form_box.addWidget(QLabel(i18n.tr("purchases.field.category")), 1, 0); form_box.addWidget(self.f_category, 1, 1)
        form_box.addWidget(QLabel(i18n.tr("purchases.field.condition")), 1, 2); form_box.addWidget(self.f_condition, 1, 3)
        form_box.addWidget(self.storage_label, 2, 0); form_box.addWidget(self.f_storage, 2, 1)
        form_box.addWidget(self.ram_label, 2, 2); form_box.addWidget(self.f_ram, 2, 3)
        form_box.addWidget(self.color_label, 3, 0); form_box.addWidget(self.f_color, 3, 1)
        form_box.addWidget(QLabel(i18n.tr("inventory.field.imei1")), 3, 2); form_box.addWidget(self.f_imei, 3, 3)
        form_box.addWidget(QLabel(i18n.tr("inventory.field.imei2")), 4, 0); form_box.addWidget(self.f_imei2, 4, 1)
        form_box.addWidget(QLabel(i18n.tr("inventory.field.quantity")), 4, 2); form_box.addWidget(self.f_qty, 4, 3)
        form_box.addWidget(QLabel(i18n.tr("purchases.field.cost_price")), 5, 0); form_box.addWidget(self.f_cost, 5, 1)
        form_box.addWidget(QLabel(i18n.tr("purchases.field.suggested_sale_price")), 5, 2); form_box.addWidget(self.f_sale, 5, 3)
        v.addLayout(form_box)
        self._update_spec_fields(self.f_category.currentText())

        add_btn = QPushButton(i18n.tr("purchases.add_item_button"))
        add_btn.clicked.connect(self._add_item)
        v.addWidget(add_btn)

        self.cart_table = build_table([
            i18n.tr("inventory.col.code"), i18n.tr("purchases.col.item"), "IMEI",
            i18n.tr("inventory.col.quantity"), i18n.tr("purchases.col.cost_price"), i18n.tr("purchases.col.total"),
        ])
        v.addWidget(self.cart_table)

        remove_btn = QPushButton(i18n.tr("purchases.remove_item_button"))
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.clicked.connect(self._remove_selected)
        v.addWidget(remove_btn)

        bottom = QHBoxLayout()
        self.supplier_combo = QComboBox()
        self._reload_suppliers()
        bottom.addWidget(QLabel(i18n.tr("purchases.supplier_label")))
        bottom.addWidget(self.supplier_combo)

        self.payment_type = QComboBox()
        self.payment_type.addItems([i18n.tr("purchases.payment_cash"), i18n.tr("purchases.payment_credit")])
        self.payment_type.currentTextChanged.connect(self._update_payment_fields)
        bottom.addWidget(QLabel(i18n.tr("purchases.payment_method_label")))
        bottom.addWidget(self.payment_type)

        self.paid_amount = QDoubleSpinBox()
        self.paid_amount.setRange(0, 10_000_000)
        self.paid_amount.valueChanged.connect(self._on_paid_amount_changed)
        bottom.addWidget(QLabel(i18n.tr("purchases.paid_amount_label")))
        bottom.addWidget(self.paid_amount)
        v.addLayout(bottom)

        self.total_label = QLabel(i18n.tr("purchases.total_label", total=fmt_money(0)))
        self.total_label.setStyleSheet("font-size:18px; font-weight:bold;")
        v.addWidget(self.total_label)

        self._update_payment_fields(self.payment_type.currentText())

        confirm_btn = QPushButton(i18n.tr("purchases.confirm_purchase_button"))
        confirm_btn.clicked.connect(self._confirm_purchase)
        v.addWidget(confirm_btn)

        return w

    def _on_paid_amount_changed(self, value):
        self._paid_auto = False

    def _update_payment_fields(self, text):
        # تغيير طريقة الدفع يرجّع المبلغ المدفوع لقيمته الافتراضية: صفر لو "آجل"
        # (الشراء كله دين لحد ما يتسدد)، أو الإجمالي كامل غير كده.
        self._paid_auto = True
        self._recalc_paid()

    def _reload_suppliers(self):
        self.supplier_combo.clear()
        self.supplier_combo.addItem(i18n.tr("purchases.no_supplier_selected"), None)
        for s in db.fetch_all("SELECT id, name FROM suppliers ORDER BY name"):
            self.supplier_combo.addItem(s["name"], s["id"])

    def _update_spec_fields(self, category_text):
        category = category_text.strip()
        is_phone = (category == "تلفون")
        needs_capacity = category in CAPACITY_CATEGORIES
        self.storage_label.setVisible(needs_capacity)
        self.f_storage.setVisible(needs_capacity)
        self.storage_label.setText(i18n.tr("inventory.field.storage_phone" if is_phone else "inventory.field.storage_other"))
        for widget in (self.ram_label, self.f_ram, self.color_label, self.f_color):
            widget.setVisible(is_phone)

    def _search_products(self, text):
        self.code_results_list.clear()
        self._matched_product_id = None
        self._set_descriptive_fields_enabled(True)
        term = text.strip()
        if not term:
            return
        like = f"%{term}%"
        rows = db.fetch_all(
            """SELECT * FROM products
               WHERE code LIKE ? OR name LIKE ? OR imei LIKE ? OR imei2 LIKE ?
               ORDER BY name""",
            (like, like, like, like),
        )
        for p in rows[:20]:
            model_suffix = i18n.tr("purchases.model_suffix", model=p["model"]) if p["model"] else ""
            label = i18n.tr(
                "purchases.search_result_label",
                code=p["code"] or "-", name=p["name"], model_suffix=model_suffix, qty=p["quantity"],
            )
            item = QListWidgetItem(label)
            item.setData(1000, p)
            self.code_results_list.addItem(item)

    def _select_search_result(self, item):
        self._apply_matched_product(item.data(1000))

    def _lookup_exact(self):
        """Enter في الخانة (زي ما بيحصل لما ماسح باركود يمسح كود ويبعت
        Enter تلقائي) - بيدوّر على تطابق تام بالكود أو IMEI."""
        term = self.f_code.text().strip()
        if not term:
            self._reset_item_form()
            return
        product = db.fetch_one(
            "SELECT * FROM products WHERE code=? OR imei=? OR imei2=?", (term, term, term)
        )
        if product:
            self._apply_matched_product(product)
        else:
            self._matched_product_id = None
            self._set_descriptive_fields_enabled(True)
            self.code_status_label.setStyleSheet(f"color:{pal.current().RED}; font-size:12px;")
            self.code_status_label.setText(i18n.tr("purchases.error_not_found"))

    def _apply_matched_product(self, product):
        self.code_results_list.clear()
        self._matched_product_id = product["id"]
        self.f_code.blockSignals(True)
        self.f_code.setText(product.get("code") or "")
        self.f_code.blockSignals(False)
        self.f_name.setText(product["name"])
        self.f_model.setText(product["model"] or "")
        self.f_category.setCurrentText(product["category"] or "")
        self.f_condition.setCurrentText(product["condition_type"] or "جديد")
        self.f_storage.setCurrentText(product["storage"] or "")
        self.f_ram.setCurrentText(product["ram"] or "")
        self.f_color.setText(product["color"] or "")
        self.f_cost.setValue(product["wholesale_price"] or 0)
        self.f_sale.setValue(product["sale_price"] or 0)
        self.f_imei.clear()
        self.f_imei2.clear()
        self._set_descriptive_fields_enabled(False)
        self.code_status_label.setStyleSheet(f"color:{pal.current().ACCENT_TEAL}; font-size:12px;")
        self.code_status_label.setText(i18n.tr(
            "purchases.found_product_status",
            name=product["name"], code=product.get("code") or "-", qty=product["quantity"],
        ))

    def _set_descriptive_fields_enabled(self, enabled):
        for widget in (self.f_name, self.f_model, self.f_category, self.f_condition,
                       self.f_storage, self.f_ram, self.f_color):
            widget.setEnabled(enabled)

    def _reset_item_form(self):
        self._matched_product_id = None
        self.code_results_list.clear()
        self.f_code.clear()
        self.code_status_label.setText("")
        self._set_descriptive_fields_enabled(True)
        self.f_name.clear(); self.f_model.clear(); self.f_imei.clear(); self.f_imei2.clear(); self.f_color.clear()
        self.f_category.setCurrentIndex(0)
        self.f_condition.setCurrentIndex(0)
        self.f_qty.setValue(1); self.f_cost.setValue(0); self.f_sale.setValue(0)

    def _add_item(self):
        name = self.f_name.text().strip()
        if not name:
            warn(self, i18n.tr("purchases.error_no_item_name"))
            return
        category = self.f_category.currentText().strip()
        is_phone = (category == "تلفون")
        needs_capacity = category in CAPACITY_CATEGORIES
        item = {
            "product_id": self._matched_product_id,
            "code": self.f_code.text().strip() or None,
            "name": name,
            "model": self.f_model.text().strip(),
            "category": category,
            "condition_type": self.f_condition.currentText(),
            "storage": self.f_storage.currentText().strip() if needs_capacity else None,
            "ram": self.f_ram.currentText() if is_phone else None,
            "color": self.f_color.text().strip() if is_phone else None,
            "imei": self.f_imei.text().strip() or None,
            "imei2": self.f_imei2.text().strip() or None,
            "qty": self.f_qty.value(),
            "cost": self.f_cost.value(),
            "sale": self.f_sale.value(),
        }
        self.cart.append(item)
        self._refresh_cart()
        self._reset_item_form()

    def _refresh_cart(self):
        self.cart_table.setRowCount(len(self.cart))
        total = 0
        for i, c in enumerate(self.cart):
            subtotal = c["cost"] * c["qty"]
            total += subtotal
            fill_row(self.cart_table, i, [
                c.get("code") or "-", c["name"], c["imei"] or "-", c["qty"], fmt_money(c["cost"]), fmt_money(subtotal)
            ])
        self.total_label.setText(i18n.tr("purchases.total_label", total=fmt_money(total)))
        self._recalc_paid(total)

    def _recalc_paid(self, total=None):
        if total is None:
            total = sum(c["cost"] * c["qty"] for c in self.cart)
        if self._paid_auto:
            target = 0.0 if self.payment_type.currentText() == i18n.tr("purchases.payment_credit") else total
            self.paid_amount.blockSignals(True)
            self.paid_amount.setValue(target)
            self.paid_amount.blockSignals(False)

    def _remove_selected(self):
        row = self.cart_table.currentRow()
        if row < 0 or row >= len(self.cart):
            return
        self.cart.pop(row)
        self._refresh_cart()

    def _confirm_purchase(self):
        if not self.cart:
            warn(self, i18n.tr("purchases.cart_empty"))
            return
        total = sum(c["cost"] * c["qty"] for c in self.cart)
        payment_type = "cash" if self.payment_type.currentText() == i18n.tr("purchases.payment_cash") else "credit"
        paid = self.paid_amount.value()
        supplier_id = self.supplier_combo.currentData()
        supplier_name = self.supplier_combo.currentText()

        if payment_type == "credit" and supplier_id is None:
            warn(self, i18n.tr("purchases.error_credit_needs_supplier"))
            return

        if not confirm(self, i18n.tr("purchases.confirm_purchase", total=fmt_money(total))):
            return

        try:
            purchase_id = db.execute(
                "INSERT INTO purchases (supplier_id, total, paid_amount, payment_type, created_by) VALUES (?,?,?,?,?)",
                (supplier_id, total, paid, payment_type, self.user["username"]),
            )

            for c in self.cart:
                # لو الصنف اتحدد بالكود، product_id جاهز خلاص. لو مالوش
                # كود بس ليه IMEI مطابق لصنف موجود، بنعتبره نفس الصنف كمان
                # (زي ما كان بيحصل قبل نظام الأكواد).
                product_id = c.get("product_id")
                if product_id is None and (c["imei"] or c.get("imei2")):
                    existing = db.fetch_one(
                        "SELECT id FROM products WHERE (imei=? AND ? IS NOT NULL) OR (imei2=? AND ? IS NOT NULL)",
                        (c["imei"], c["imei"], c.get("imei2"), c.get("imei2")),
                    )
                    if existing:
                        product_id = existing["id"]

                if product_id is not None:
                    db.execute(
                        "UPDATE products SET quantity = quantity + ?, status='in_stock', wholesale_price=? WHERE id=?",
                        (c["qty"], c["cost"], product_id),
                    )
                else:
                    product_id = db.execute(
                        """INSERT INTO products (name, model, imei, imei2, category, condition_type, storage, ram, color,
                           wholesale_price, sale_price, quantity, supplier_id, status)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'in_stock')""",
                        (c["name"], c["model"], c["imei"], c.get("imei2"), c["category"], c["condition_type"],
                         c["storage"], c["ram"], c["color"], c["cost"], c["sale"], c["qty"], supplier_id),
                    )
                    db.execute(
                        "UPDATE products SET code=? WHERE id=?", (db.generate_product_code(product_id), product_id)
                    )
                db.execute(
                    "INSERT INTO purchase_items (purchase_id, product_id, product_name, cost_price, qty) VALUES (?,?,?,?,?)",
                    (purchase_id, product_id, c["name"], c["cost"], c["qty"]),
                )

            if paid > 0:
                account = db.fetch_one("SELECT id FROM treasury_accounts ORDER BY id LIMIT 1")
                if account:
                    db.execute("UPDATE treasury_accounts SET balance = balance - ? WHERE id=?", (paid, account["id"]))
                    db.execute(
                        "INSERT INTO treasury_transactions (account_id, amount, type, description) VALUES (?,?,?,?)",
                        (account["id"], paid, "out", i18n.tr("purchases.treasury_tx_desc", id=purchase_id)),
                    )

            remaining = total - paid
            if remaining > 0.001:
                db.execute(
                    """INSERT INTO debts (party_type, party_id, party_name, amount, original_amount, debt_type, description)
                       VALUES ('supplier', ?, ?, ?, ?, 'i_owe', ?)""",
                    (supplier_id, supplier_name, remaining, remaining, i18n.tr("purchases.debt_desc", id=purchase_id)),
                )
        except Exception as e:
            warn(self, i18n.tr("purchases.error_purchase_failed", error=e))
            return

        info(self, i18n.tr("purchases.notice_recorded"))
        self.cart = []
        self._paid_auto = True
        self.payment_type.setCurrentText(i18n.tr("purchases.payment_cash"))
        self._refresh_cart()
        self._refresh_history()

    def _build_history_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.history_table = build_table([
            i18n.tr("purchases.col.invoice_no"), i18n.tr("purchases.col.supplier"), i18n.tr("purchases.col.total"),
            i18n.tr("purchases.col.paid"), i18n.tr("purchases.col.payment_method"), i18n.tr("purchases.col.date"),
        ])
        v.addWidget(self.history_table)
        self._refresh_history()
        return w

    def _refresh_history(self):
        rows = db.fetch_all(
            """SELECT p.*, s.name as supplier_name FROM purchases p
               LEFT JOIN suppliers s ON s.id = p.supplier_id
               ORDER BY p.created_at DESC LIMIT 200"""
        )
        self.history_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            payment_text = i18n.tr("purchases.payment_cash" if r["payment_type"] == "cash" else "purchases.payment_credit")
            fill_row(self.history_table, i, [
                r["id"], r["supplier_name"] or "-", fmt_money(r["total"]),
                fmt_money(r["paid_amount"]), payment_text, r["created_at"]
            ])

    def showEvent(self, event):
        self._reload_suppliers()
        self._refresh_history()
        super().showEvent(event)
