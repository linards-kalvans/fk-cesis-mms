"""P17 — forms for the member-export template admin surface.

Three pieces:

* :class:`OrderedColumnKeysWidget` — custom widget rendering a picker
  (selected + available lists) plus add/remove/move-up/move-down controls
  wired up by ``static/admin/js/member_export_columns.js``. A hidden JSON
  ``column_keys`` input is what the form actually submits.
* :class:`MemberExportTemplateAdminForm` — validates ``column_keys`` and
  ``agreement_status_filters`` via the registry helpers.
* :class:`MemberExportRunForm` — minimal format picker for the run page.
"""

from __future__ import annotations

import json
from html import escape as _html_escape

from django import forms
from django.utils.safestring import mark_safe

from apps.agreements.models import Agreement
from apps.members.exports import (
    COLUMN_REGISTRY,
    validate_agreement_status_filters,
    validate_column_keys,
)
from apps.members.models import MemberExportTemplate, TrainingGroup


class OrderedColumnKeysWidget(forms.Widget):
    """A picker widget: selected list + available list + add/remove/up/down.

    Submits a single hidden JSON input ``column_keys`` whose value is the
    ordered list of selected keys. The JS hook attribute
    ``data-member-export-columns`` on the root container tells the admin JS
    which DOM to bind to.

    Markup is generated directly here — no separate template — so the picker
    is portable across form renderers and never reflects user-controlled
    values back into raw HTML. Every dynamic string is run through
    :func:`html.escape` before being interpolated.
    """

    def __init__(self, attrs=None):
        default_attrs = {"data-member-export-columns": "true"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    class Media:
        js = ("admin/js/member_export_columns.js",)

    @staticmethod
    def _coerce_selected(value) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        if not isinstance(value, (list, tuple)):
            return []
        return [str(v) for v in value if isinstance(v, str)]

    def get_context(self, name, value, attrs):
        """Compute the picker context.

        Tests call this directly, so we return a ``{"widget": {...}}``
        dict. Inline ``render`` reads the same data to build HTML.
        """
        selected = self._coerce_selected(value)
        # Drop any unknown / stale keys defensively — never crash the form.
        selected = [k for k in selected if k in COLUMN_REGISTRY]
        selected_set = set(selected)
        available_keys = [k for k in COLUMN_REGISTRY if k not in selected_set]
        available_items = [
            {"key": k, "label": COLUMN_REGISTRY[k].label} for k in available_keys
        ]
        selected_items = [
            {"key": k, "label": COLUMN_REGISTRY[k].label} for k in selected
        ]
        return {
            "widget": {
                "name": name,
                "selected": list(selected),
                "available_keys": list(available_keys),
                "selected_items": selected_items,
                "available_items": available_items,
                "json_value": json.dumps(selected),
            }
        }

    def render(self, name, value, attrs=None, renderer=None):
        """Render the picker inline.

        The signature mirrors Django's standard widget render contract —
        Django passes a ``renderer`` keyword argument for BoundField rendering
        and we accept (and ignore) it.
        """
        context = self.get_context(name, value, attrs)
        widget_ctx = context["widget"]
        return mark_safe(_render_picker(name, widget_ctx))

    def value_from_datadict(self, data, files, name):
        raw = data.get(name, "")
        return self._coerce_selected(raw)

    def format_value(self, value):
        return json.dumps(self._coerce_selected(value))


def _render_picker(name: str, widget_ctx: dict) -> str:
    """Build the picker HTML inline. All dynamic strings are HTML-escaped."""
    selected_items = widget_ctx["selected_items"]
    available_items = widget_ctx["available_items"]
    json_value = widget_ctx["json_value"]
    safe_name = _html_escape(str(name))

    parts: list[str] = [
        '<div class="fk-member-export-columns" data-member-export-columns="true">',
        '<div class="fk-member-export-columns__selected">',
        '<p class="help">Izvēlētās kolonnas (parādās izvēlētajā secībā):</p>',
        '<ul class="fk-member-export-columns__list" data-selected-list>',
    ]
    if not selected_items:
        parts.append(
            '<li class="fk-member-export-columns__empty" data-empty>'
            "Izvēlieties kolonnas no labā saraksta.</li>"
        )
    else:
        for item in selected_items:
            key = _html_escape(item["key"])
            label = _html_escape(item["label"])
            parts.append(
                f'<li class="fk-member-export-columns__item" data-key="{key}">'
                f'<span class="fk-member-export-columns__label">{label}</span>'
                f'<button type="button" class="fk-column-remove" data-action="remove" '
                f'data-key="{key}" aria-label="Noņemt kolonnu {label}">−</button>'
                f'<button type="button" class="fk-column-move-up" data-action="up" '
                f'data-key="{key}" aria-label="Pārvietot augšup">↑</button>'
                f'<button type="button" class="fk-column-move-down" data-action="down" '
                f'data-key="{key}" aria-label="Pārvietot lejup">↓</button>'
                "</li>"
            )
    parts.append("</ul></div>")

    parts.append(
        '<div class="fk-member-export-columns__available">'
        '<p class="help">Pieejamās kolonnas:</p>'
        '<ul class="fk-member-export-columns__list" data-available-list>'
    )
    for item in available_items:
        key = _html_escape(item["key"])
        label = _html_escape(item["label"])
        parts.append(
            f'<li class="fk-member-export-columns__item" data-key="{key}">'
            f'<span class="fk-member-export-columns__label">{label}</span>'
            f'<button type="button" class="fk-column-add" data-action="add" '
            f'data-key="{key}" aria-label="Pievienot kolonnu {label}">+</button>'
            "</li>"
        )
    parts.append("</ul></div>")

    safe_json = _html_escape(str(json_value))
    parts.append(
        f'<input type="hidden" name="{safe_name}" '
        f'value=\'{safe_json}\' '
        f'data-member-export-columns-input="true" />'
    )
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Admin form for the MemberExportTemplate model
# ---------------------------------------------------------------------------


def _agreement_state_choices() -> list[tuple[str, str]]:
    """Choices mirror ``Agreement.State.choices`` in the model's defined order."""
    return list(Agreement.State.choices)


class ColumnKeysField(forms.Field):
    """A field that round-trips the ordered column-key list as-is.

    ``OrderedColumnKeysWidget.value_from_datadict`` already parses the hidden
    JSON input into a Python list — we accept that and refuse to coerce it
    back to a string (which ``CharField.to_python`` would via ``str()``).
    """

    def to_python(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, (list, tuple)):
                return [str(v) for v in parsed]
            return []
        return []

    def validate(self, value):
        super().validate(value)


class MemberExportTemplateAdminForm(forms.ModelForm):
    column_keys = ColumnKeysField(
        widget=OrderedColumnKeysWidget,
        help_text="Kolonnas parādīsies izvēlētajā secībā.",
    )
    agreement_status_filters = forms.MultipleChoiceField(
        required=False,
        choices=_agreement_state_choices(),
        widget=forms.CheckboxSelectMultiple,
        help_text="Atstājiet tukšu, lai nefiltrētu pēc līguma statusa.",
    )
    training_groups = forms.ModelMultipleChoiceField(
        required=False,
        queryset=TrainingGroup.objects.all(),
        help_text="Pēc noklusējuma iekļauti biedri no visām grupām.",
    )

    class Meta:
        model = MemberExportTemplate
        fields = ("name", "column_keys", "agreement_status_filters", "training_groups")

    def clean_column_keys(self):
        parsed = list(self.cleaned_data.get("column_keys") or [])
        try:
            return validate_column_keys(parsed)
        except forms.ValidationError as exc:
            # Same trick as ``clean_agreement_status_filters``: surface only the
            # field-scoped messages, not the dict-like error.
            messages = exc.error_dict.get("column_keys", [])
            raise forms.ValidationError(messages)

    def clean_agreement_status_filters(self):
        try:
            return validate_agreement_status_filters(
                self.cleaned_data.get("agreement_status_filters") or []
            )
        except forms.ValidationError as exc:
            # Re-raise only the field-scoped messages — ``validate_*`` returns
            # a dict-like ValidationError that Django's form machinery cannot
            # attach to a single field.
            messages = exc.error_dict.get("agreement_status_filters", [])
            raise forms.ValidationError(messages)


# ---------------------------------------------------------------------------
# Run form
# ---------------------------------------------------------------------------


class MemberExportRunForm(forms.Form):
    FMT_CHOICES = (("xlsx", "XLSX"), ("csv", "CSV"))

    fmt = forms.ChoiceField(
        choices=FMT_CHOICES,
        widget=forms.RadioSelect,
        initial="xlsx",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and "fmt" not in self.initial:
            self.initial["fmt"] = "xlsx"
