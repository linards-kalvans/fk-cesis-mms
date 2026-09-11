"""Field readout assembly for the review cockpit."""

from __future__ import annotations

import pytest

from apps.admin_hub.fields import (
    STAFF_SOURCE_LABELS,
    build_field_groups,
    checkable_keys,
)

pytestmark = pytest.mark.django_db


def _flat(groups):
    return {field.key: field for group in groups for field in group.fields}


def test_groups_are_in_review_order(submitted_application):
    groups = build_field_groups(submitted_application)
    assert [group.title for group in groups] == [
        "Bērns",
        "Vecāks / likumiskais pārstāvis",
        "Ekipējums un izvēles",
        "Piekrišanas",
    ]


def test_exactly_ten_fields_are_checkable(submitted_application):
    keys = checkable_keys(build_field_groups(submitted_application))
    assert keys == [
        "member_full_name",
        "member_personal_id",
        "member_birth_date",
        "member_actual_address",
        "guardian_first_name",
        "guardian_personal_id",
        "guardian_declared_address",
        "guardian_phone",
        "guardian_email",
        "member_kit_size_shirt",
    ]


def test_kit_size_is_a_single_field(submitted_application):
    fields = _flat(build_field_groups(submitted_application))
    assert fields["member_kit_size_shirt"].label == "Formas izmērs"
    assert "member_kit_size_shorts" not in fields, (
        "shirt/shorts were collapsed into one field by commit 21945c4"
    )


def test_guardian_email_is_pre_checked_as_system_verified(submitted_application):
    fields = _flat(build_field_groups(submitted_application))
    email = fields["guardian_email"]
    assert email.default_checked is True
    assert email.checkable is True, "a reviewer may still clear it"
    assert email.source_tone == "verified"


def test_only_the_email_is_pre_checked(submitted_application):
    groups = build_field_groups(submitted_application)
    pre_checked = [
        field.key
        for group in groups
        for field in group.fields
        if field.default_checked
    ]
    assert pre_checked == ["guardian_email"]


def test_email_is_not_pre_checked_without_a_verified_account(submitted_application):
    """parent_account is the only proof the address is reachable."""
    submitted_application.parent_account = None
    submitted_application.save(update_fields=["parent_account"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["guardian_email"].default_checked is False


def test_ocr_sourced_field_gets_the_document_tone(submitted_application):
    submitted_application.field_sources = {
        "member_full_name": "ocr_member_identity"
    }
    submitted_application.save(update_fields=["field_sources"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["member_full_name"].source_label == "No dokumenta"
    assert fields["member_full_name"].source_tone == "doc"


def test_review_hint_gets_the_attention_tone(submitted_application):
    submitted_application.field_sources = {
        "guardian_phone": "review_hint_extracted"
    }
    submitted_application.save(update_fields=["field_sources"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["guardian_phone"].source_tone == "flag"


def test_no_label_ever_claims_the_parent_edited_a_value(submitted_application):
    """field_sources cannot express an edit - see the module docstring.

    Covers every staff-facing string the module can emit: the
    STAFF_SOURCE_LABELS mapping itself, plus every source_label and note
    actually produced for a real application (this also catches strings
    like guardian_email's "Sistēma apstiprinājusi", which are set inline
    and never appear in STAFF_SOURCE_LABELS).
    """
    emitted = list(STAFF_SOURCE_LABELS.values())
    for group in build_field_groups(submitted_application):
        for hub_field in group.fields:
            emitted.append(hub_field.source_label)
            emitted.append(hub_field.note)
    for label in emitted:
        assert "labo" not in label.lower(), f"{label!r} implies an edit"


def test_unknown_source_value_degrades_quietly(submitted_application):
    submitted_application.field_sources = {"member_full_name": "something_new"}
    submitted_application.save(update_fields=["field_sources"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["member_full_name"].source_label == ""
    assert fields["member_full_name"].source_tone == ""


def test_empty_referral_code_is_blank_and_not_checkable(submitted_application):
    submitted_application.referral_code = ""
    submitted_application.save(update_fields=["referral_code"])
    fields = _flat(build_field_groups(submitted_application))
    assert fields["referral_code"].value == ""
    assert fields["referral_code"].checkable is False
