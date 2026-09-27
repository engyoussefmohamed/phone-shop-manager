from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QFormLayout, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDialogButtonBox
)

from app import database as db
from app import i18n
from app.utils.widgets import build_table, fill_row, confirm, warn, info, search_box, fmt_money

CATEGORIES = ["تلفون", "سكرينات", "جرابات", "شواحن", "سماعات", "ادبتر", "باور بانك", "وصلات", "صبات", "أخرى"]
STORAGE_OPTIONS = ["32GB", "64GB", "128GB", "256GB", "512GB", "1TB"]
RAM_OPTIONS = ["2GB", "3GB", "4GB", "6GB", "8GB", "12GB", "16GB", "24GB"]
# الفئات دي بيكون ليها "سعة" بمعنى مختلف عن مساحة تخزين التلفون (واط
# للشواحن/الأدبتر، أمبير للباور بانك) - فالحقل بيفضل متاح ليهم بس نسيبه
# قابل للكتابة الحرة (مش قايمة مقفولة زي GB) عشان يقدر يكتب أي وحدة.
CAPACITY_CATEGORIES = {"تلفون", "شواحن", "ادبتر", "باور بانك"}


class ProductDialog(QDialog):
    def __init__(self, is_admin, product=None):
        super().__init__()
        self.is_admin = is_admin
        self.product = product
        self.setWindowTitle(i18n.tr("inventory.dialog.edit_title" if product else "inventory.dialog.add_title"))
        self.setMinimumWidth(380)

        form = QFormLayout(self)

        self.code_input = QLineEdit(product["code"] if product and product.get("code") else "")
        self.code_input.setPlaceholderText(i18n.tr("inventory.code_placeholder"))
        form.addRow(i18n.tr("inventory.field.code"), self.code_input)

        self.name_input = QLineEdit(product["name"] if product else "")
        form.addRow(i18n.tr("inventory.field.name"), self.name_input)

        self.model_input = QLineEdit(product["model"] if product else "")
        form.addRow(i18n.tr("inventory.field.model"), self.model_input)

        self.imei_input = QLineEdit(product["imei"] if product else "")
        self.imei_input.setPlaceholderText(i18n.tr("inventory.imei1_placeholder"))
        self.imei_input.returnPressed.connect(lambda: self.imei2_input.setFocus())
        form.addRow(i18n.tr("inventory.field.imei1"), self.imei_input)

        self.imei2_input = QLineEdit(product["imei2"] if product and product.get("imei2") else "")
        self.imei2_input.setPlaceholderText(i18n.tr("inventory.imei2_placeholder"))
        self.imei2_input.returnPressed.connect(self._focus_after_scan)
        form.addRow(i18n.tr("inventory.field.imei2"), self.imei2_input)

        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.addItems(CATEGORIES)
        if product and product.get("category"):
            self.category_input.setCurrentText(product["category"])
        self.category_input.currentTextChanged.connect(self._update_spec_fields)
        form.addRow(i18n.tr("inventory.field.category"), self.category_input)

        self.storage_label = QLabel(i18n.tr("inventory.field.storage_phone"))
        self.storage_input = QComboBox()
        self.storage_input.setEditable(True)
        self.storage_input.addItems(STORAGE_OPTIONS)
        self.storage_input.lineEdit().setPlaceholderText(i18n.tr("inventory.storage_placeholder"))
        if product and product.get("storage"):
            self.storage_input.setCurrentText(product["storage"])
        form.addRow(self.storage_label, self.storage_input)

        self.ram_label = QLabel(i18n.tr("inventory.field.ram"))
        self.ram_input = QComboBox()
        self.ram_input.addItems(RAM_OPTIONS)
        if product and product.get("ram"):
            self.ram_input.setCurrentText(product["ram"])
        form.addRow(self.ram_label, self.ram_input)

        self.color_label = QLabel(i18n.tr("inventory.field.color"))
        self.color_input = QLineEdit(product["color"] if product and product.get("color") else "")
        form.addRow(self.color_label, self.color_input)

        self.condition_input = QComboBox()
        self.condition_input.addItems(["جديد", "مستعمل"])
        if product and product.get("condition_type"):
            self.condition_input.setCurrentText(product["condition_type"])
        form.addRow(i18n.tr("inventory.field.condition"), self.condition_input)

        self.qty_input = QSpinBox()
        self.qty_input.setRange(0, 100000)
        if product:
            self.qty_input.setValue(product["quantity"])
        else:
            # صنف جديد بيتسجل بكمية صفر عمدًا - الكمية الحقيقية بتتزوّد
            # بس لما تعمله فاتورة شراء فعلية من شاشة المشتريات، عشان
            # يبقى ممكن تسجّل بيانات أصناف كتير قبل ما تشتريها فعلًا من
            # غير ما تأثر على أرقام المخزون/لوحة التحكم.
            self.qty_input.setValue(0)
            self.qty_input.setEnabled(False)
            self.qty_input.setToolTip(i18n.tr("inventory.quantity_tooltip"))
        form.addRow(i18n.tr("inventory.field.quantity"), self.qty_input)

        self.sale_price_input = QDoubleSpinBox()
        self.sale_price_input.setRange(0, 10_000_000)
        self.sale_price_input.setValue(product["sale_price"] if product else 0)
        form.addRow(i18n.tr("inventory.field.sale_price"), self.sale_price_input)

        self.wholesale_price_input = QDoubleSpinBox()
        self.wholesale_price_input.setRange(0, 10_000_000)
        self.wholesale_price_input.setValue(product["wholesale_price"] if product else 0)
        if not is_admin:
            self.wholesale_price_input.setEnabled(False)
            self.wholesale_price_input.setToolTip(i18n.tr("inventory.hidden_from_employee_tooltip"))
        form.addRow(i18n.tr("inventory.field.wholesale_price"), self.wholesale_price_input)

        self.max_discount_input = QDoubleSpinBox()
        self.max_discount_input.setRange(0, 10_000_000)
        self.max_discount_input.setValue(product["max_discount"] if product and product.get("max_discount") else 0)
        self.max_discount_input.setToolTip(i18n.tr("inventory.max_discount_tooltip"))
        if not is_admin:
            self.max_discount_input.setEnabled(False)
            self.max_discount_input.setToolTip(i18n.tr("inventory.hidden_from_employee_tooltip"))
        form.addRow(i18n.tr("inventory.field.max_discount"), self.max_discount_input)

        self.supplier_input = QComboBox()
        self.supplier_input.addItem(i18n.tr("inventory.no_supplier"), None)
        for sup in db.fetch_all("SELECT id, name FROM suppliers ORDER BY name"):
            self.supplier_input.addItem(sup["name"], sup["id"])
        if product and product.get("supplier_id"):
            idx = self.supplier_input.findData(product["supplier_id"])
            if idx >= 0:
                self.supplier_input.setCurrentIndex(idx)
        if not is_admin:
            self.supplier_input.setEnabled(False)
        form.addRow(i18n.tr("inventory.field.supplier"), self.supplier_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(i18n.tr("common.save"))
        buttons.button(QDialogButtonBox.Save).setAutoDefault(False)
        buttons.button(QDialogButtonBox.Save).setDefault(False)
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.tr("common.cancel"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._update_spec_fields(self.category_input.currentText())

    def _update_spec_fields(self, category_text):
        category = category_text.strip()
        is_phone = (category == "تلفون")
        needs_capacity = category in CAPACITY_CATEGORIES
        self.storage_label.setVisible(needs_capacity)
        self.storage_input.setVisible(needs_capacity)
        self.storage_label.setText(i18n.tr("inventory.field.storage_phone" if is_phone else "inventory.field.storage_other"))
        for w in (self.ram_label, self.ram_input, self.color_label, self.color_input):
            w.setVisible(is_phone)

    def _focus_after_scan(self):
        """بعد مسح الباركود/QR جوه حقل IMEI (اللي بيبعت Enter زي الكيبورد
        بالظبط)، منسيبش الـ Enter يقفل الدياموج - بننقل التركيز للحقل
        اللي محتاج يتملى بعد كده."""
        if not self.name_input.text().strip():
            self.name_input.setFocus()
        else:
            self.sale_price_input.setFocus()

    def save(self):
        name = self.name_input.text().strip()
        if not name:
            warn(self, i18n.tr("inventory.error_no_name"))
            return
        imei = self.imei_input.text().strip() or None
        imei2 = self.imei2_input.text().strip() or None
        category = self.category_input.currentText().strip()
        is_phone = (category == "تلفون")
        needs_capacity = category in CAPACITY_CATEGORIES

        data = {
            "name": name,
            "model": self.model_input.text().strip(),
            "imei": imei,
            "imei2": imei2,
            "category": category,
            "condition_type": self.condition_input.currentText(),
            "storage": self.storage_input.currentText().strip() if needs_capacity else None,
            "ram": self.ram_input.currentText() if is_phone else None,
            "color": self.color_input.text().strip() if is_phone else None,
            "quantity": self.qty_input.value(),
            "sale_price": self.sale_price_input.value(),
            "wholesale_price": self.wholesale_price_input.value() if self.is_admin else (
                self.product["wholesale_price"] if self.product else 0
            ),
            "max_discount": self.max_discount_input.value() if self.is_admin else (
                self.product["max_discount"] if self.product else 0
            ),
            "supplier_id": self.supplier_input.currentData() if self.is_admin else (
                self.product["supplier_id"] if self.product else None
            ),
        }

        custom_code = self.code_input.text().strip() or None
        final_code = custom_code

        try:
            if self.product:
                final_code = custom_code or self.product.get("code")
                db.execute(
                    """UPDATE products SET code=?, name=?, model=?, imei=?, imei2=?, category=?, condition_type=?,
                       storage=?, ram=?, color=?, quantity=?, sale_price=?, wholesale_price=?, max_discount=?, supplier_id=?
                       WHERE id=?""",
                    (final_code, data["name"], data["model"], data["imei"], data["imei2"], data["category"], data["condition_type"],
                     data["storage"], data["ram"], data["color"],
                     data["quantity"], data["sale_price"], data["wholesale_price"], data["max_discount"],
                     data["supplier_id"], self.product["id"]),
                )
            else:
                new_id = db.execute(
                    """INSERT INTO products (name, model, imei, imei2, category, condition_type, storage, ram, color,
                       quantity, sale_price, wholesale_price, max_discount, supplier_id, status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'in_stock')""",
                    (data["name"], data["model"], data["imei"], data["imei2"], data["category"], data["condition_type"],
                     data["storage"], data["ram"], data["color"],
                     data["quantity"], data["sale_price"], data["wholesale_price"], data["max_discount"],
                     data["supplier_id"]),
                )
                final_code = custom_code or db.generate_product_code(new_id)
                db.execute("UPDATE products SET code=? WHERE id=?", (final_code, new_id))
        except Exception as e:
            warn(self, i18n.tr("inventory.error_save_failed", error=e))
            return

        info(self, i18n.tr("inventory.notice_saved", code=final_code))
        self.accept()


class InventoryView(QWidget):
    def __init__(self, is_admin):
        super().__init__()
        self.is_admin = is_admin

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(i18n.tr("nav.inventory"))
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        header.addWidget(title)
        header.addStretch()

        self.search = search_box(i18n.tr("inventory.search_placeholder"))
        self.search.textChanged.connect(self.refresh)
        header.addWidget(self.search)

        add_btn = QPushButton(i18n.tr("inventory.add_button"))
        add_btn.clicked.connect(self.add_product)
        header.addWidget(add_btn)

        layout.addLayout(header)

        headers = [
            i18n.tr("inventory.col.code"), i18n.tr("inventory.col.name"), i18n.tr("inventory.col.category"),
            i18n.tr("inventory.col.specs"), i18n.tr("inventory.col.model"), "IMEI",
            i18n.tr("inventory.col.condition"), i18n.tr("inventory.col.quantity"), i18n.tr("inventory.col.sale_price"),
        ]
        if is_admin:
            headers += [i18n.tr("inventory.col.wholesale_price"), i18n.tr("inventory.col.supplier")]
        self.headers = headers
        self.table = build_table(headers)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        edit_btn = QPushButton(i18n.tr("common.edit"))
        edit_btn.setObjectName("SecondaryButton")
        edit_btn.clicked.connect(self.edit_product)
        actions.addWidget(edit_btn)

        if is_admin:
            delete_btn = QPushButton(i18n.tr("common.delete"))
            delete_btn.setObjectName("DangerButton")
            delete_btn.clicked.connect(self.delete_product)
            actions.addWidget(delete_btn)

        actions.addStretch()
        layout.addLayout(actions)

        self.refresh()

    def _query(self):
        term = f"%{self.search.text().strip()}%"
        rows = db.fetch_all(
            """SELECT p.*, s.name as supplier_name FROM products p
               LEFT JOIN suppliers s ON s.id = p.supplier_id
               WHERE p.status='in_stock' AND (p.name LIKE ? OR p.imei LIKE ? OR p.model LIKE ? OR p.code LIKE ?)
               ORDER BY p.created_at DESC""",
            (term, term, term, term),
        )
        return rows

    def refresh(self):
        rows = self._query()
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for i, p in enumerate(rows):
            specs = " / ".join(s for s in [p["storage"], p["ram"], p["color"]] if s) or "-"
            values = [p.get("code") or "-", p["name"], p["category"] or "-", specs, p["model"] or "-", p["imei"] or "-",
                      p["condition_type"], p["quantity"], fmt_money(p["sale_price"])]
            if self.is_admin:
                values += [fmt_money(p["wholesale_price"]), p["supplier_name"] or "-"]
            fill_row(self.table, i, values)
        self._rows_cache = rows

    def _selected_product(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows_cache):
            return None
        return self._rows_cache[row]

    def add_product(self):
        dlg = ProductDialog(self.is_admin)
        if dlg.exec():
            self.refresh()

    def edit_product(self):
        product = self._selected_product()
        if not product:
            warn(self, i18n.tr("inventory.error_select_first"))
            return
        dlg = ProductDialog(self.is_admin, product=product)
        if dlg.exec():
            self.refresh()

    def delete_product(self):
        product = self._selected_product()
        if not product:
            warn(self, i18n.tr("inventory.error_select_first"))
            return
        if confirm(self, i18n.tr("inventory.confirm_delete", name=product["name"])):
            db.execute("DELETE FROM products WHERE id=?", (product["id"],))
            self.refresh()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
