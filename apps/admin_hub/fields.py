"""Field readout for the review cockpit: what the parent submitted, grouped
for eyeball comparison against the uploaded document.

No machine comparison happens here, deliberately. The parent-facing form
pre-fills from OCR and the parent may correct a misread value before
submitting, so a value that differs from the document is not evidence of an
error - it is often evidence the parent fixed one.

Provenance labels are staff-facing and intentionally separate from
``apps.registrations.presentation.SOURCE_LABEL_MAP``, which is phrased for
the parent. Note what these labels do NOT say: ``field_sources`` is written
once and never reset when a parent overwrites an OCR-filled value, so no
stored value can mean "the parent edited this".
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from apps.members.lanes import canonical_kit_size_label
from apps.registrations.models import RegistrationApplication

STAFF_SOURCE_LABELS: dict[str, str] = {
    "ocr_guardian_identity": "No dokumenta",
    "ocr_member_identity": "No dokumenta",
    "manual_only": "Ievadīts",
    "derived_system_filled": "No pārbaudīta konta",
    "review_hint_extracted": "Jāpārbauda",
}
STAFF_SOURCE_TONES: dict[str, str] = {
    "ocr_guardian_identity": "doc",
    "ocr_member_identity": "doc",
    "manual_only": "typed",
    "derived_system_filled": "typed",
    "review_hint_extracted": "flag",
}


@dataclass(frozen=True)
class HubField:
    key: str
    label: str
    value: str
    source_label: str = ""
    source_tone: str = ""
    note: str = ""
    checkable: bool = True
    default_checked: bool = False


@dataclass(frozen=True)
class HubFieldGroup:
    title: str
    hint: str
    fields: list[HubField]


def _fmt_date(value: datetime.date | str | None) -> str:
    # `member_birth_date` may still be a raw ISO string here: the write path
    # (create_or_update_draft) assigns whatever it is given without coercing
    # through a form's DateField, so callers that bypass the form (as some
    # fixtures and services do) can leave a str in place of a date.
    if not value:
        return ""
    parsed: datetime.date
    if isinstance(value, str):
        try:
            parsed = datetime.date.fromisoformat(value)
        except ValueError:
            return value
    else:
        parsed = value
    return parsed.strftime("%d.%m.%Y")


def _fmt_datetime(value) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else ""


def build_field_groups(
    application: RegistrationApplication,
) -> list[HubFieldGroup]:
    sources = application.field_sources or {}

    def field(
        key: str,
        label: str,
        value: object,
        *,
        source_key: str | None = None,
        note: str = "",
        checkable: bool = True,
        default_checked: bool = False,
        source_label: str | None = None,
        source_tone: str | None = None,
    ) -> HubField:
        raw_source = sources.get(source_key if source_key else key, "")
        return HubField(
            key=key,
            label=label,
            value="" if value is None else str(value),
            source_label=(
                source_label
                if source_label is not None
                else STAFF_SOURCE_LABELS.get(raw_source, "")
            ),
            source_tone=(
                source_tone
                if source_tone is not None
                else STAFF_SOURCE_TONES.get(raw_source, "")
            ),
            note=note,
            checkable=checkable,
            default_checked=default_checked,
        )

    same_address_note = (
        'Atzīmēts "tā pati adrese kā vecākam"'
        if application.member_same_address_as_guardian
        else ""
    )
    # A non-null parent_account IS the proof the address is reachable: the
    # one-time-code flow is what sets it. There is no separate boolean.
    email_verified = application.parent_account_id is not None

    child = HubFieldGroup(
        title="Bērns",
        hint="pret bērna ID",
        fields=[
            field("member_full_name", "Vārds, uzvārds", application.member_full_name),
            field("member_personal_id", "Personas kods", application.member_personal_id),
            field(
                "member_birth_date",
                "Dzimšanas datums",
                _fmt_date(application.member_birth_date),
            ),
            field(
                "member_actual_address",
                "Faktiskā adrese",
                application.member_actual_address,
                note=same_address_note,
            ),
        ],
    )

    guardian = HubFieldGroup(
        title="Vecāks / likumiskais pārstāvis",
        hint="pret vecāka ID",
        fields=[
            field(
                "guardian_first_name",
                "Vārds, uzvārds",
                application.guardian_name,
            ),
            field(
                "guardian_personal_id",
                "Personas kods",
                application.guardian_pid,
            ),
            field(
                "guardian_declared_address",
                "Adrese",
                application.guardian_address,
            ),
            field(
                "guardian_phone",
                "Tālrunis",
                application.guardian_contact_phone,
            ),
            field(
                "guardian_email",
                "E-pasts",
                application.guardian_contact_email,
                default_checked=email_verified,
                source_label="Sistēma apstiprinājusi" if email_verified else "",
                source_tone="verified" if email_verified else "",
                note=(
                    "Vienreizējais kods · nav jāpārbauda manuāli"
                    if email_verified
                    else "Konts vēl nav apstiprināts"
                ),
            ),
        ],
    )

    kit = HubFieldGroup(
        title="Ekipējums un izvēles",
        hint="bez dokumenta",
        fields=[
            field(
                "member_kit_size_shirt",
                "Formas izmērs",
                canonical_kit_size_label(application),
                note="Viens izmērs kreklam un šortiem",
            ),
            field(
                "preferred_agreement_signing",
                "Parakstīšanas veids",
                application.get_preferred_agreement_signing_display(),
                note="Nosaka 3.–5. soli",
                checkable=False,
            ),
            field(
                "preferred_payment_mode",
                "Maksājuma veids",
                application.get_preferred_payment_mode_display(),
                note="Nosaka 6. soļa priekšatlasi",
                checkable=False,
            ),
            field(
                "support_club_instead_of_multi_child_discount",
                "Vairāku bērnu atlaide",
                _discount_choice_label(
                    application.support_club_instead_of_multi_child_discount
                ),
                checkable=False,
            ),
            field(
                "referral_code",
                "Ieteikuma kods",
                application.referral_code,
                checkable=False,
            ),
        ],
    )

    consents = HubFieldGroup(
        title="Piekrišanas",
        hint="",
        fields=[
            field(
                "personal_data_consent",
                "Personas datu apstrāde",
                _fmt_datetime(application.personal_data_consent_at),
                note=(
                    f"Versija {application.personal_data_consent_version}"
                    if application.personal_data_consent_version
                    else "Nav piekrišanas"
                ),
                checkable=False,
            ),
        ],
    )

    return [child, guardian, kit, consents]


def _discount_choice_label(value: bool | None) -> str:
    if value is None:
        return ""
    return "Atteicās — atbalsta klubu" if value else "Piemēro atlaidi"


def checkable_keys(groups: list[HubFieldGroup]) -> list[str]:
    return [f.key for g in groups for f in g.fields if f.checkable]
