"""Django forms for registration workflow."""

import re

from django import forms

from apps.registrations.messages import STEP_FIELD_FORMAT, STEP_FIELD_REQUIRED


class RegistrationApplicationForm(forms.Form):
    """Form for creating/editing a RegistrationApplication."""

    section_order = (
        (
            "documents",
            (
                "guardian_identity_document",
                "member_identity_document",
                "member_portrait_document",
            ),
        ),
        (
            "guardian",
            (
                "guardian_first_name",
                "guardian_family_name",
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
            ),
        ),
        (
            "agreement",
            (
                "preferred_agreement_signing",
                "support_club_instead_of_multi_child_discount",
                "preferred_payment_mode",
            ),
        ),
    )

    guardian_first_name = forms.CharField(max_length=255, required=False, label="Vecāka vārds")
    guardian_family_name = forms.CharField(max_length=255, required=False, label="Vecāka uzvārds")
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
        help_text="Ievadiet datumu formātā DD.MM.GGGG",
        input_formats=["%d.%m.%Y"],
        error_messages={"invalid": "Ievadiet derīgu datumu."},
        widget=forms.DateInput(
            attrs={
                "placeholder": "DD.MM.GGGG",
                "data-date-format": "lv-dot",
                "autocomplete": "bday",
                "inputmode": "numeric",
                "maxlength": "10",
            },
            format="%d.%m.%Y",
        ),
    )
    member_actual_address = forms.CharField(max_length=255, required=False, label="Bērna faktiskā adrese")
    member_same_address_as_guardian = forms.BooleanField(required=False, label="Adrese tāda pati kā vecāka")
    member_kit_size_shirt = forms.ChoiceField(required=False, label="Formas izmērs")
    preferred_agreement_signing = forms.ChoiceField(required=False, label="Līguma parakstīšanas veids")
    support_club_instead_of_multi_child_discount = forms.BooleanField(required=False, label="Nepiemērot Līgumā noteiktās atlaides - Vēlos atbalstīt klubu")
    preferred_payment_mode = forms.ChoiceField(required=False, label="Maksājuma veids")
    # Enforced at service layer, not here — rendered manually in template.
    personal_data_consent = forms.BooleanField(required=False, label="Piekrītu personas datu apstrādei")
    guardian_identity_document = forms.FileField(required=False, label="Vecāka personas dokuments")
    member_identity_document = forms.FileField(required=False, label="Bērna personu apliecinošs dokuments")
    member_portrait_document = forms.FileField(required=False, label="Bērna portrets")

    submit_required_fields = (
        "guardian_first_name",
        "guardian_family_name",
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
        "preferred_agreement_signing",
    )

    def __init__(
        self,
        *args,
        is_submit: bool = False,
        has_existing_document: bool = False,
        guardian_profile_locked: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.is_submit = is_submit
        self.has_existing_document = has_existing_document
        self.guardian_profile_locked = guardian_profile_locked

        # Populate kit size choices from database (active shirt options, natural size order).
        from apps.members.models import KitSizeOption, kit_size_sort_key

        kit_opts = sorted(
            KitSizeOption.objects.filter(kind=KitSizeOption.Kind.SHIRT, is_active=True),
            key=lambda option: kit_size_sort_key(option.label),
        )
        self.fields["member_kit_size_shirt"].choices = [(str(o.pk), o.label) for o in kit_opts]

        # Populate agreement signing choices
        from apps.registrations.models import RegistrationApplication

        self.fields["preferred_agreement_signing"].choices = RegistrationApplication.AgreementSigning.choices
        self.fields["preferred_payment_mode"].choices = RegistrationApplication.PaymentMode.choices
        defaults = {
            "preferred_agreement_signing": RegistrationApplication.AgreementSigning.ELECTRONIC,
            "preferred_payment_mode": RegistrationApplication.PaymentMode.INSTALLMENTS,
        }
        for field_name, default in defaults.items():
            self.fields[field_name].initial = default
            if not self.is_bound and not self.initial.get(field_name):
                self.initial[field_name] = default

        self.fields["member_actual_address"].widget.attrs["data-sync-address-for"] = "id_member_same_address_as_guardian"

        # Address-autocomplete hooks (assist-only; no VZD codes persisted).
        for _address_field in ("guardian_declared_address", "member_actual_address"):
            attrs = self.fields[_address_field].widget.attrs
            attrs["data-address-autocomplete"] = "1"
            attrs["autocomplete"] = "street-address"
            attrs["aria-autocomplete"] = "list"

        # P3.5: tag file inputs so static/js/async_upload.js can bind to them.
        # The progress slot id mirrors id_for_label so the template can render
        # an adjacent <span> with the same id + "_progress".
        self.fields["guardian_identity_document"].widget.attrs["data-async-upload"] = "guardian_identity"
        self.fields["guardian_identity_document"].widget.attrs["data-progress-slot"] = "id_guardian_identity_document_progress"
        self.fields["member_identity_document"].widget.attrs["data-async-upload"] = "member_identity"
        self.fields["member_identity_document"].widget.attrs["data-progress-slot"] = "id_member_identity_document_progress"
        self.fields["member_portrait_document"].widget.attrs["data-async-upload"] = "member_portrait"
        self.fields["member_portrait_document"].widget.attrs["data-progress-slot"] = "id_member_portrait_document_progress"

        # P4 Slice D: canonical file inputs are visually hidden — the visible
        # tap surface is the <label for=...> rendered by document_card.html.
        for _file_field in ("guardian_identity_document", "member_identity_document", "member_portrait_document"):
            existing = self.fields[_file_field].widget.attrs.get("class", "")
            classes = (existing + " fk-visually-hidden").strip()
            self.fields[_file_field].widget.attrs["class"] = classes

        # P4 Slice C — step-gating hooks. The wizard JS controller reads
        # `data-step-required` to know which inputs gate "next" on each step,
        # and the two `data-step-error-*` attrs supply the Latvian error copy
        # without ever embedding it in markup.
        _field_step_map = {
            "guardian_identity_document": "documents",
            "member_identity_document": "documents",
            "guardian_first_name": "guardian",
            "guardian_family_name": "guardian",
            "guardian_personal_id": "guardian",
            "guardian_email": "guardian",
            "guardian_phone": "guardian",
            "guardian_declared_address": "guardian",
            "member_full_name": "member",
            "member_personal_id": "member",
            "member_birth_date": "member",
            "member_actual_address": "member",
            "member_kit_size_shirt": "member",
            "preferred_agreement_signing": "agreement",
            # Note: member_same_address_as_guardian is intentionally absent from
            # the step-gating map. Leaving the checkbox unchecked is a valid
            # answer ("no, addresses differ"), so it must not gate the step's
            # "Turpināt →" CTA via data-step-required.
        }
        _format_validated = {"guardian_personal_id", "member_personal_id"}
        for field_name, step_name in _field_step_map.items():
            widget = self.fields[field_name].widget
            widget.attrs["data-step-required"] = step_name
            widget.attrs["data-step-error-empty"] = STEP_FIELD_REQUIRED
            if field_name in _format_validated:
                widget.attrs["data-step-error-format"] = STEP_FIELD_FORMAT

        # Slice C — verified email is the OTP identity; never parent-editable.
        # Staff change it via Django admin (apps.accounts.services.change_parent_email).
        guardian_email_attrs = self.fields["guardian_email"].widget.attrs
        guardian_email_attrs["readonly"] = "readonly"
        guardian_email_attrs["class"] = " ".join(
            part
            for part in [
                guardian_email_attrs.get("class", ""),
                "fk-input--guardian-locked",
            ]
            if part
        )

        # Slice C — returning parents see the guardian profile locked. readonly
        # (NOT disabled) keeps the values in the POST so a save round-trips them
        # unchanged; the template's unlock toggle removes readonly client-side.
        if guardian_profile_locked:
            for _name in (
                "guardian_first_name",
                "guardian_family_name",
                "guardian_personal_id",
                "guardian_phone",
                "guardian_declared_address",
            ):
                self.fields[_name].widget.attrs["readonly"] = "readonly"

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
