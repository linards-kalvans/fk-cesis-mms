"""Django forms for registration workflow."""

import re

from django import forms


class RegistrationApplicationForm(forms.Form):
    """Form for creating/editing a RegistrationApplication."""

    section_order = (
        (
            "documents",
            (
                "guardian_identity_document",
                "member_identity_document",
            ),
        ),
        (
            "guardian",
            (
                "guardian_full_name",
                "guardian_personal_id",
                "guardian_email",
                "guardian_phone",
                "guardian_declared_address",
            ),
        ),
        (
            "member",
            (
                "member_full_name",
                "member_personal_id",
                "member_birth_date",
                "member_same_address_as_guardian",
                "member_actual_address",
                "member_kit_size_shirt",
                "member_kit_size_shorts",
                "member_portrait_document",
            ),
        ),
        (
            "agreement",
            (
                "preferred_agreement_signing",
                "support_club_instead_of_multi_child_discount",
            ),
        ),
    )

    guardian_full_name = forms.CharField(max_length=255, required=False, label="Vecāka vārds, uzvārds")
    guardian_personal_id = forms.CharField(max_length=32, required=False, label="Vecāka personas kods")
    guardian_email = forms.EmailField(
        required=True,
        label="E-pasts",
        error_messages={"required": "E-pasts ir obligāts.", "invalid": "Ievadiet derīgu e-pasta adresi."},
    )
    guardian_phone = forms.CharField(max_length=32, required=False, label="Tālrunis")
    guardian_declared_address = forms.CharField(max_length=255, required=False, label="Adrese")
    member_full_name = forms.CharField(max_length=255, required=False, label="Bērna vārds, uzvārds")
    member_personal_id = forms.CharField(max_length=32, required=False, label="Bērna personas kods")
    member_birth_date = forms.DateField(
        required=False,
        label="Bērna dzimšanas datums",
        error_messages={"invalid": "Ievadiet derīgu datumu."},
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    member_actual_address = forms.CharField(max_length=255, required=False, label="Bērna faktiskā adrese")
    member_same_address_as_guardian = forms.BooleanField(required=False, label="Adrese tāda pati kā vecāka")
    member_kit_size_shirt = forms.ChoiceField(required=False, label="Krekla izmērs")
    member_kit_size_shorts = forms.ChoiceField(required=False, label="Šortu izmērs")
    preferred_agreement_signing = forms.ChoiceField(required=False, label="Līguma parakstīšanas veids")
    support_club_instead_of_multi_child_discount = forms.BooleanField(required=False, label="Nepiemērot Līgumā noteiktās atlaides - Vēlos atbalstīt klubu")
    guardian_identity_document = forms.FileField(required=False, label="Vecāka personas dokuments")
    member_identity_document = forms.FileField(required=False, label="Bērna personu apliecinošs dokuments")
    member_portrait_document = forms.FileField(required=False, label="Bērna portrets")

    submit_required_fields = (
        "guardian_full_name",
        "guardian_personal_id",
        "guardian_email",
        "guardian_phone",
        "guardian_declared_address",
        "member_full_name",
        "member_personal_id",
        "member_birth_date",
        "member_actual_address",
        "member_same_address_as_guardian",
        "member_kit_size_shirt",
        "member_kit_size_shorts",
        "preferred_agreement_signing",
    )

    def __init__(self, *args, is_submit: bool = False, has_existing_document: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_submit = is_submit
        self.has_existing_document = has_existing_document

        # Populate kit size choices from database
        from apps.members.models import KitSizeOption

        shirt_opts = [(str(o.pk), o.label) for o in KitSizeOption.objects.filter(kind=KitSizeOption.Kind.SHIRT, is_active=True)]
        shorts_opts = [(str(o.pk), o.label) for o in KitSizeOption.objects.filter(kind=KitSizeOption.Kind.SHORTS, is_active=True)]
        self.fields["member_kit_size_shirt"].choices = shirt_opts
        self.fields["member_kit_size_shorts"].choices = shorts_opts

        # Populate agreement signing choices
        from apps.registrations.models import RegistrationApplication

        self.fields["preferred_agreement_signing"].choices = RegistrationApplication.AgreementSigning.choices

        self.fields["member_actual_address"].widget.attrs["data-sync-address-for"] = "id_member_same_address_as_guardian"

    def clean(self):
        cleaned_data = super().clean()
        if not self.is_submit:
            return cleaned_data

        same_addr = cleaned_data.get("member_same_address_as_guardian", False)
        boolean_fields = {"member_same_address_as_guardian"}
        for field_name in self.submit_required_fields:
            if field_name == "member_actual_address" and same_addr:
                continue
            value = cleaned_data.get(field_name)
            if field_name in boolean_fields:
                if value is None:
                    self.add_error(field_name, "Šis lauks ir obligāts iesniegšanai.")
                continue
            if not value:
                self.add_error(field_name, "Šis lauks ir obligāts iesniegšanai.")

        if not self.has_existing_document and not cleaned_data.get("guardian_identity_document"):
            self.add_error("guardian_identity_document", "Vecāka personas dokuments ir obligāts iesniegšanai.")

        return cleaned_data

    def grouped_fields(self):
        """Return list of (section_name, [BoundField, ...]) tuples in section_order."""
        return [(section_name, [self[name] for name in field_names]) for section_name, field_names in self.section_order]

    def clean_guardian_personal_id(self):
        value = self.cleaned_data.get("guardian_personal_id", "")
        if value and not re.match(r"^\d{6}-\d{5}$", value):
            raise forms.ValidationError("Ievadiet personas kodu formātā DDDDDD-DDDDD.")
        return value

    def clean_member_personal_id(self):
        value = self.cleaned_data.get("member_personal_id", "")
        if value and not re.match(r"^\d{6}-\d{5}$", value):
            raise forms.ValidationError("Ievadiet personas kodu formātā DDDDDD-DDDDD.")
        return value

    def error_summary_items(self):
        """Return list of {'field', 'label', 'message'} dicts for all form errors."""
        items = []
        for field_name, errors in self.errors.items():
            label = ""
            if field_name in self.fields:
                label = self.fields[field_name].label or field_name
            for error in errors:
                items.append({"field": field_name, "label": label, "message": error})
        return items
