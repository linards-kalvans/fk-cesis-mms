"""P23 — MedicalPermit model shape and fixed validity-rule contract.

The MedicalPermit model does not exist yet; every import of it (or of the
`apps.documents.medical_permits` helpers) lives inside a test body so pytest
collection succeeds and the suite fails at run time with the feature-missing
signal (ImportError), not a setup error.
"""

from __future__ import annotations

import datetime

import pytest

pytestmark = pytest.mark.django_db

# Fixed validity rule: an upload/confirmation recorded in calendar year N is
# valid through 30 September of N+1. Boundary dates below exercise the helper.
VALID_UNTIL = datetime.date(2026, 9, 30)


def _upload(name="permit.pdf", content_type="application/pdf"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name=name, content=b"%PDF-1.4 test", content_type=content_type
    )


def _make_app():
    from apps.registrations.models import RegistrationApplication

    return RegistrationApplication.objects.create(
        claimed_email="permit-model@example.com",
        member_full_name="Model Child",
    )


def _make_permit(
    application,
    *,
    valid_until=VALID_UNTIL,
    source="staff_confirmation",
    with_file=False,
    member=None,
):
    from apps.documents.models import MedicalPermit

    kwargs = dict(
        application=application,
        source=source,
        valid_until=valid_until,
    )
    if with_file:
        kwargs.update(
            file=_upload("model.pdf"),
            original_filename="model.pdf",
            content_type="application/pdf",
            file_size=13,
        )
    if member is not None:
        kwargs["member"] = member
    return MedicalPermit.objects.create(**kwargs)


def test_application_and_member_relations_shape():
    """One-to-one linkage to the source application and (nullable) member."""
    from django.db.models import OneToOneField

    from apps.documents.models import MedicalPermit

    application_field = MedicalPermit._meta.get_field("application")
    assert isinstance(application_field, OneToOneField)
    assert application_field.related_model.__name__ == "RegistrationApplication"

    member_field = MedicalPermit._meta.get_field("member")
    assert isinstance(member_field, OneToOneField)
    assert member_field.related_model.__name__ == "Member"
    assert member_field.null is True
    assert member_field.blank is True


def test_source_choices_include_parent_staff_and_confirmation():
    from apps.documents.models import MedicalPermit

    values = set(MedicalPermit.Source.values)
    assert {
        "parent_upload",
        "staff_upload",
        "staff_confirmation",
    } <= values


def test_confirmation_only_permit_has_no_file():
    """A confirmation-only permit stores no private file."""
    permit = _make_permit(_make_app(), with_file=False)
    assert permit.file == ""


def test_permit_with_file_stores_metadata():
    app = _make_app()
    permit = _make_permit(app, source="parent_upload", with_file=True)
    assert permit.file != ""
    assert permit.original_filename == "model.pdf"
    assert permit.content_type == "application/pdf"
    assert permit.file_size == 13


def test_valid_until_is_a_date_field():
    from django.db.models import DateField

    from apps.documents.models import MedicalPermit

    field = MedicalPermit._meta.get_field("valid_until")
    assert isinstance(field, DateField)


def test_status_missing_when_no_permit_exists():
    from apps.documents.medical_permits import medical_permit_status

    assert medical_permit_status(None, on=datetime.date(2026, 8, 1)) == "missing"


@pytest.mark.parametrize(
    "on, expected",
    [
        # Before 1 August of valid_until.year → current.
        (datetime.date(2025, 12, 31), "current"),
        (datetime.date(2026, 1, 1), "current"),
        (datetime.date(2026, 7, 31), "current"),
        # From 1 August through 30 September inclusive → expiring.
        (datetime.date(2026, 8, 1), "expiring"),
        (datetime.date(2026, 8, 15), "expiring"),
        (datetime.date(2026, 9, 30), "expiring"),
        # From 1 October onward → expired.
        (datetime.date(2026, 10, 1), "expired"),
        (datetime.date(2027, 1, 1), "expired"),
    ],
)
def test_status_boundaries(on, expected):
    from apps.documents.medical_permits import medical_permit_status

    permit = _make_permit(_make_app(), valid_until=VALID_UNTIL, with_file=True)
    assert medical_permit_status(permit, on=on) == expected


def test_status_missing_for_record_with_neither_file_nor_confirmation():
    """A row that has no stored file and no confirmation classifies as missing."""
    from apps.documents.medical_permits import medical_permit_status

    permit = _make_permit(_make_app(), with_file=False)
    assert permit.confirmed_by_id is None
    assert medical_permit_status(permit, on=datetime.date(2026, 8, 1)) == "missing"


def test_status_expired_current_file_stays_private():
    """An expired permit is still classified expired and keeps its stored file."""
    from apps.documents.medical_permits import medical_permit_status

    permit = _make_permit(_make_app(), valid_until=VALID_UNTIL, with_file=True)
    assert medical_permit_status(permit, on=datetime.date(2026, 10, 1)) == "expired"
    assert permit.file != ""


def test_unique_application_linkage_enforced():
    from django.db import IntegrityError, transaction

    app = _make_app()
    _make_permit(app)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_permit(app)


def test_unique_member_linkage_enforced():
    from django.db import IntegrityError, transaction

    from apps.members.models import Member
    from tests.support import make_guardian

    guardian = make_guardian(email="member-unique@example.com")
    member = Member.objects.create(full_name="Unique Child", guardian=guardian)
    app = _make_app()
    _make_permit(app, member=member)
    other_app = _make_app()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_permit(other_app, member=member)


def test_confirmation_actor_and_time_fields_nullable():
    """Confirmation actor/time are nullable — a permit may exist with no
    staff confirmation yet (upload-only or bare row)."""
    from django.db.models import DateTimeField, ForeignKey

    from apps.documents.models import MedicalPermit

    confirmed_by = MedicalPermit._meta.get_field("confirmed_by")
    assert isinstance(confirmed_by, ForeignKey)
    assert confirmed_by.related_model.__name__ == "User"
    assert confirmed_by.null is True
    assert confirmed_by.blank is True

    confirmed_at = MedicalPermit._meta.get_field("confirmed_at")
    assert isinstance(confirmed_at, DateTimeField)
    assert confirmed_at.null is True
    assert confirmed_at.blank is True

    # An upload-only permit carries neither.
    permit = _make_permit(_make_app(), source="parent_upload", with_file=True)
    assert permit.confirmed_by_id is None
    assert permit.confirmed_at is None