"""
واجهة مشتركة للعملاء والموردين (نفس الشكل تقريباً: اسم، تليفون، عنوان،
ملاحظات، وإجمالي المديونية المرتبطة بيهم من جدول الآجل). كل واحد فيهم
ممكن يضيف حقل إضافي خاص بيه (النوع للعملاء، نوع البضاعة للموردين) عن
طريق EXTRA_FIELD.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog,
    QFormLayout, QLineEdit, QTextEdit, QComboBox, QDialogButtonBox
)

from app import database as db
from app import i18n
from app.utils.widgets import build_table, fill_row, confirm, warn, search_box, fmt_money


class PartyDialog(QDialog):
    def __init__(self, title, party=None, extra_field=None, notes_label=None):
        super().__init__()
        self.party = party
        self.extra_field = extra_field
        self.setWindowTitle(title)
        self.setMinimumWidth(360)

        form = QFormLayout(self)
        self.name_input = QLineEdit(party["name"] if party else "")
        form.addRow(i18n.tr("party.field.name"), self.name_input)
        self.phone_input = QLineEdit(party["phone"] if party else "")
        form.addRow(i18n.tr("party.field.phone"), self.phone_input)
        self.address_input = QLineEdit(party["address"] if party else "")
        form.addRow(i18n.tr("party.field.address"), self.address_input)

        self.extra_input = None
        if extra_field:
            self.extra_input = QComboBox()
            self.extra_input.setEditable(True)
            self.extra_input.addItems(extra_field["options"])
            if party and party.get(extra_field["key"]):
                self.extra_input.setCurrentText(party[extra_field["key"]])
            form.addRow(extra_field["label"], self.extra_input)

        self.notes_input = QTextEdit(party["notes"] if party else "")
        self.notes_input.setFixedHeight(70)
        form.addRow(notes_label or i18n.tr("party.default_notes_label"), self.notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(i18n.tr("party.save"))
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.tr("party.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_data(self):
        data = {
            "name": self.name_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "address": self.address_input.text().strip(),
            "notes": self.notes_input.toPlainText().strip(),
        }
        if self.extra_input is not None:
            data[self.extra_field["key"]] = self.extra_input.currentText().strip()
        return data


class PartyView(QWidget):
    TABLE = "customers"
    DEBT_PARTY_TYPE = "customer"
    TITLE_KEY = "customers.title"
    ADD_TITLE_KEY = "customers.add_title"
    EDIT_TITLE_KEY = "customers.edit_title"
    DEBT_LABEL_KEY = "customers.debt_label"
    EXTRA_FIELD = None  # {"key": "gender", "label_key": "...", "options": [...]}
    NOTES_LABEL_KEY = "party.default_notes_label"

    def __init__(self):
        super().__init__()
        # النصوص متترجمة هنا (وقت التشغيل) مش كـ ثوابت على مستوى الكلاس،
        # عشان تتحدث صح لو المستخدم غيّر اللغة والشاشة اتبنت تاني.
        self.TITLE = i18n.tr(self.TITLE_KEY)
        self.ADD_TITLE = i18n.tr(self.ADD_TITLE_KEY)
        self.EDIT_TITLE = i18n.tr(self.EDIT_TITLE_KEY)
        self.DEBT_LABEL = i18n.tr(self.DEBT_LABEL_KEY)
        self.NOTES_LABEL = i18n.tr(self.NOTES_LABEL_KEY)
        if self.EXTRA_FIELD:
            self.EXTRA_FIELD = {
                "key": self.EXTRA_FIELD["key"],
                "label": i18n.tr(self.EXTRA_FIELD["label_key"]),
                "options": self.EXTRA_FIELD["options"],
            }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(self.TITLE)
        title.setStyleSheet("font-size:22px; font-weight:bold;")
        header.addWidget(title)
        header.addStretch()

        self.search = search_box(i18n.tr("party.search_placeholder"))
        self.search.textChanged.connect(self.refresh)
        header.addWidget(self.search)

        add_btn = QPushButton(i18n.tr("party.add_button"))
        add_btn.clicked.connect(self.add_party)
        header.addWidget(add_btn)
        layout.addLayout(header)

        headers = [i18n.tr("party.col.name"), i18n.tr("party.col.phone"), i18n.tr("party.col.address")]
        if self.EXTRA_FIELD:
            headers.append(self.EXTRA_FIELD["label"].rstrip(":"))
        headers.append(self.DEBT_LABEL)
        self.table = build_table(headers)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        edit_btn = QPushButton(i18n.tr("party.edit_button"))
        edit_btn.setObjectName("SecondaryButton")
        edit_btn.clicked.connect(self.edit_party)
        actions.addWidget(edit_btn)

        delete_btn = QPushButton(i18n.tr("party.delete_button"))
        delete_btn.setObjectName("DangerButton")
        delete_btn.clicked.connect(self.delete_party)
        actions.addWidget(delete_btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.refresh()

    def _query(self):
        term = f"%{self.search.text().strip()}%"
        rows = db.fetch_all(
            f"SELECT * FROM {self.TABLE} WHERE name LIKE ? OR phone LIKE ? ORDER BY name",
            (term, term),
        )
        for r in rows:
            debt = db.fetch_one(
                "SELECT COALESCE(SUM(amount),0) v FROM debts WHERE party_type=? AND party_id=? AND status='pending'",
                (self.DEBT_PARTY_TYPE, r["id"]),
            )["v"]
            r["debt"] = debt
        return rows

    def refresh(self):
        rows = self._query()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [r["name"], r["phone"] or "-", r["address"] or "-"]
            if self.EXTRA_FIELD:
                values.append(r[self.EXTRA_FIELD["key"]] or "-")
            values.append(fmt_money(r["debt"]))
            fill_row(self.table, i, values)
        self._rows_cache = rows

    def _selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows_cache):
            return None
        return self._rows_cache[row]

    def add_party(self):
        dlg = PartyDialog(self.ADD_TITLE, extra_field=self.EXTRA_FIELD, notes_label=self.NOTES_LABEL)
        if dlg.exec():
            data = dlg.get_data()
            if not data["name"]:
                warn(self, i18n.tr("party.error_no_name"))
                return
            if self.EXTRA_FIELD:
                key = self.EXTRA_FIELD["key"]
                db.execute(
                    f"INSERT INTO {self.TABLE} (name, phone, address, {key}, notes) VALUES (?,?,?,?,?)",
                    (data["name"], data["phone"], data["address"], data[key], data["notes"]),
                )
            else:
                db.execute(
                    f"INSERT INTO {self.TABLE} (name, phone, address, notes) VALUES (?,?,?,?)",
                    (data["name"], data["phone"], data["address"], data["notes"]),
                )
            self.refresh()

    def edit_party(self):
        party = self._selected()
        if not party:
            warn(self, i18n.tr("party.error_select_first"))
            return
        dlg = PartyDialog(self.EDIT_TITLE, party=party, extra_field=self.EXTRA_FIELD, notes_label=self.NOTES_LABEL)
        if dlg.exec():
            data = dlg.get_data()
            if self.EXTRA_FIELD:
                key = self.EXTRA_FIELD["key"]
                db.execute(
                    f"UPDATE {self.TABLE} SET name=?, phone=?, address=?, {key}=?, notes=? WHERE id=?",
                    (data["name"], data["phone"], data["address"], data[key], data["notes"], party["id"]),
                )
            else:
                db.execute(
                    f"UPDATE {self.TABLE} SET name=?, phone=?, address=?, notes=? WHERE id=?",
                    (data["name"], data["phone"], data["address"], data["notes"], party["id"]),
                )
            self.refresh()

    def delete_party(self):
        party = self._selected()
        if not party:
            warn(self, i18n.tr("party.error_select_first"))
            return
        if confirm(self, i18n.tr("party.confirm_delete", name=party["name"])):
            db.execute(f"DELETE FROM {self.TABLE} WHERE id=?", (party["id"],))
            self.refresh()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)
