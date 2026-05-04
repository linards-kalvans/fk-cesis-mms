"""Forms for the accounts app."""

from django import forms

from apps.accounts.models import ParentAccount


class MagicLinkRequestForm(forms.Form):
    email = forms.EmailField()

    def clean_email(self):
        email = self.cleaned_data["email"]
        if not ParentAccount.objects.filter(email=email).exists():
            raise forms.ValidationError("No account found with this email.")
        return email
