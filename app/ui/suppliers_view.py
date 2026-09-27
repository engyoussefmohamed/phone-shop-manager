from app.ui.party_view import PartyView


class SuppliersView(PartyView):
    TABLE = "suppliers"
    DEBT_PARTY_TYPE = "supplier"
    TITLE_KEY = "suppliers.title"
    ADD_TITLE_KEY = "suppliers.add_title"
    EDIT_TITLE_KEY = "suppliers.edit_title"
    DEBT_LABEL_KEY = "suppliers.debt_label"
    EXTRA_FIELD = {
        "key": "goods_type", "label_key": "suppliers.goods_type_label",
        "options": ["أجهزة جديدة", "أجهزة مستعملة", "إكسسوارات", "قطع غيار", "أخرى"],
    }
    NOTES_LABEL_KEY = "suppliers.notes_label"
