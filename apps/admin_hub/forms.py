"""Admin Hub — request parsing for the member-export runner (2026-09-11).

The Hub form owns POST coercion and Latvian field errors only. Column
definitions, query rules, filter semantics, and rendering remain canonical
in the P17 service layer (``apps.members.export_templates`` /
``apps.members.exports``) — this module must not duplicate any of them.
"""

from __future__ import annotations

from django import forms

from apps.agreements.models import Agreement
from apps.members.exports import validate_agreement_status_filters
from apps.members.forms import MemberExportRunForm
from apps.members.models import TrainingGroup


class HubMemberExportRunForm(forms.Form):
    """One POST surface for both runner actions (preview / download).

    The multi-selects clean to explicit ``[]`` when nothing was submitted —
    never ``None``, which the P17 service layer reserves for "use the
    template's stored filters". ``fmt`` is optional on the wire and falls
    back to XLSX (the runner's only default).
    """

    ACTION_CHOICES = (("preview", "Priekšskats"), ("download", "Lejupielādēt"))

    action = forms.ChoiceField(
        label="Darbība",
        choices=ACTION_CHOICES,
        error_messages={
            "required": "Nav izvēlēta darbība.",
            "invalid_choice": "Darbība nav atbalstīta.",
        },
    )
    template_id = forms.IntegerField(
        label="Šablons",
        min_value=1,
        error_messages={
            "required": "Nav izvēlēts šablons.",
            "invalid": "Šablona identifikators nav derīgs.",
            "min_value": "Šablona identifikators nav derīgs.",
        },
    )
    agreement_states = forms.MultipleChoiceField(
        label="Līguma statuss",
        required=False,
        choices=Agreement.State.choices,
        error_messages={
            "invalid_choice": "Nezināms līguma statuss.",
        },
    )
    group_ids = forms.ModelMultipleChoiceField(
        label="Treniņu grupa",
        required=False,
        queryset=TrainingGroup.objects.order_by("name", "pk"),
        error_messages={
            "invalid_choice": "Nezināma treniņu grupa.",
        },
    )
    fmt = forms.ChoiceField(
        label="Formāts",
        required=False,
        choices=MemberExportRunForm.FMT_CHOICES,
        initial="xlsx",
        widget=forms.RadioSelect,
        error_messages={
            "invalid_choice": "Nezināms eksporta formāts.",
        },
    )

    def clean_agreement_states(self) -> list[str]:
        """P17's ``validate_agreement_status_filters`` stays canonical for
        the state rule (unknown values AND duplicates) — the plain
        ``MultipleChoiceField`` check alone would let duplicates through."""
        states = list(self.cleaned_data.get("agreement_states") or [])
        try:
            return validate_agreement_status_filters(states)
        except forms.ValidationError as exc:
            # ``validate_*`` raises a dict-like error; surface only the
            # field-scoped messages so the form machinery can attach them.
            messages = exc.error_dict.get("agreement_status_filters", [])
            raise forms.ValidationError(messages)

    def clean_fmt(self) -> str:
        # Omitted format defaults to XLSX; any submitted non-empty value was
        # already validated against P17's FMT_CHOICES by the field itself.
        return self.cleaned_data.get("fmt") or "xlsx"

    @property
    def effective_group_ids(self) -> list[int]:
        """Selected group PKs in the deterministic ``(name, pk)`` order the
        queryset carries — never the raw submission order."""
        groups = self.cleaned_data.get("group_ids")
        if not groups:
            return []
        return [int(group.pk) for group in groups]
