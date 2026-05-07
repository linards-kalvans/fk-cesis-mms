"""Forms for the accounts app."""

from django import forms


class MagicLinkRequestForm(forms.Form):
    email = forms.EmailField(
        label="E-pasts",
        error_messages={
            "required": "E-pasts ir obligāts.",
            "invalid": "Ievadiet derīgu e-pasta adresi.",
        },
    )

    def clean_email(self):
        email = self.cleaned_data["email"]
        return email
