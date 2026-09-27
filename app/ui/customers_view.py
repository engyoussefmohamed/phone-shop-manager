from app.ui.party_view import PartyView


class CustomersView(PartyView):
    TABLE = "customers"
    DEBT_PARTY_TYPE = "customer"
    TITLE_KEY = "customers.title"
    ADD_TITLE_KEY = "customers.add_title"
    EDIT_TITLE_KEY = "customers.edit_title"
    DEBT_LABEL_KEY = "customers.debt_label"
    EXTRA_FIELD = {"key": "gender", "label_key": "customers.gender_label", "options": ["ذكر", "أنثى"]}
