"""Django forms for registration workflow."""

from django import forms


class RegistrationApplicationForm(forms.Form):
    """Form for creating/editing a RegistrationApplication."""

    guardian_full_name = forms.CharField(max_length=255, required=False, label="Vecāka vārds, uzvārds")
    guardian_personal_id = forms.CharField(max_length=32, required=False, label="Vecāka personas kods")
    guardian_email = forms.EmailField(
        required=True,
        label="E-pasts",
        error_messages={"required": "E-pasts ir obligāts.", "invalid": "Ievadiet derīgu e-pasta adresi."},
    )
    guardian_phone = forms.CharField(max_length=32, required=False, label="Tālrunis")
    guardian_address = forms.CharField(max_length=255, required=False, label="Adrese")
    child_full_name = forms.CharField(max_length=255, required=False, label="Bērna vārds, uzvārds")
    child_personal_id = forms.CharField(max_length=32, required=False, label="Bērna personas kods")
    child_birth_date = forms.DateField(
        required=False,
        label="Bērna dzimšanas datums",
        error_messages={"invalid": "Ievadiet derīgu datumu."},
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    child_identity_document = forms.FileField(required=False, label="Bērna personu apliecinošs dokuments")

    submit_required_fields = (
        "guardian_full_name",
        "guardian_personal_id",
        "guardian_email",
        "guardian_phone",
        "guardian_address",
        "child_full_name",
        "child_personal_id",
        "child_birth_date",
    )

    def __init__(self, *args, is_submit: bool = False, has_existing_document: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_submit = is_submit
        self.has_existing_document = has_existing_document

    def clean(self):
        cleaned_data = super().clean()
        if not self.is_submit:
            return cleaned_data

        for field_name in self.submit_required_fields:
            if not cleaned_data.get(field_name):
                self.add_error(field_name, "Šis lauks ir obligāts iesniegšanai.")

        if not self.has_existing_document and not cleaned_data.get("child_identity_document"):
            self.add_error("child_identity_document", "Bērna personu apliecinošs dokuments ir obligāts iesniegšanai.")

        return cleaned_data
