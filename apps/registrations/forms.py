"""Django forms for registration workflow."""

from django import forms


class RegistrationApplicationForm(forms.Form):
    """Form for creating/editing a RegistrationApplication."""

    guardian_full_name = forms.CharField(max_length=255, required=False)
    guardian_personal_id = forms.CharField(max_length=32, required=False)
    guardian_email = forms.EmailField(required=True)
    guardian_phone = forms.CharField(max_length=32, required=False)
    guardian_address = forms.CharField(max_length=255, required=False)
    child_full_name = forms.CharField(max_length=255, required=False)
    child_personal_id = forms.CharField(max_length=32, required=False)
    child_birth_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
 
    )
    child_identity_document = forms.FileField(required=False)

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
                self.add_error(field_name, "This field is required for submission.")

        if not self.has_existing_document and not cleaned_data.get("child_identity_document"):
            self.add_error("child_identity_document", "Child identity document is required for submission.")

        return cleaned_data
