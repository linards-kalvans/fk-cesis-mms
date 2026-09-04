"""P16-A: signed-artifact upload/replace service tests.

Covers the wishful ``apps.agreements.services.upload_signed_artifact``
contract: six artifact fields directly on ``Agreement``, validation
(suffix / size / PDF MIME), replacement safety (save new -> commit ->
delete old), redacted audit metadata, and state/billing/provider/queue
isolation. P16-B artifacts (validation model, version token, eParaksts,
jobs) must stay absent.

Red-phase discipline: the service, fields, audit action, and settings are
intentionally not implemented yet. Every test first asserts the missing
feature exists so the red run fails on clean assertions (missing feature),
never on AttributeError/NoReverseMatch collection errors.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.agreements import services as agreements_services
from apps.agreements.models import Agreement
from apps.core import models as core_models

pytestmark = pytest.mark.django_db

# Wishful API — bound at collection; None while P16-A is unimplemented.
upload_signed_artifact = getattr(agreements_services, "upload_signed_artifact", None)

SIGNED_ARTIFACT_UPLOADED = getattr(
    core_models.AuditEvent.Action, "SIGNED_ARTIFACT_UPLOADED", None
)

_MSG_UNSUPPORTED = (
    "Neatbalstītais faila formāts. Pieņemti tikai PDF vai .edoc faili."
)
_MSG_OVERSIZED = "Faila izmērs pārsniedz atļauto robežu."
_MSG_MIME = "PDF failam jābūt ar 'application/pdf' tipu."


def uploaded_file(name: str, body: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, body, content_type=content_type)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def actor(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="artifact-staff", is_staff=True)


@pytest.fixture
def agreement(agreement_member):
    """Current generated paper-path agreement for the shared member."""
    return agreements_services.create_agreement_for_member(
        agreement_member, Agreement.SigningPath.PAPER
    )


def _store(agreement, filename, body, content_type, *, at=None):
    """Direct storage write used to pre-position artifacts on an Agreement.

    Test-shape only — mirrors the six fields the service will populate.
    ``at`` overrides ``signed_artifact_updated_at`` for ordering tests.
    """
    agreement.signed_artifact.save(filename, ContentFile(body), save=False)
    agreement.signed_artifact_original_filename = filename
    agreement.signed_artifact_content_type = content_type
    agreement.signed_artifact_file_size = len(body)
    now = at or timezone.now()
    agreement.signed_artifact_uploaded_at = agreement.signed_artifact_uploaded_at or now
    agreement.signed_artifact_updated_at = now
    agreement.save(
        update_fields=[
            "signed_artifact",
            "signed_artifact_original_filename",
            "signed_artifact_content_type",
            "signed_artifact_file_size",
            "signed_artifact_uploaded_at",
            "signed_artifact_updated_at",
            "updated_at",
        ]
    )
    agreement.refresh_from_db()
    return agreement


# ---------------------------------------------------------------------------
# Model + config shape (requirement 1, 10)
# ---------------------------------------------------------------------------


def test_agreement_owns_six_p16a_artifact_fields():
    """The six artifact fields live directly on Agreement — no artifact model."""
    assert hasattr(Agreement, "signed_artifact")
    assert hasattr(Agreement, "signed_artifact_original_filename")
    assert hasattr(Agreement, "signed_artifact_content_type")
    assert hasattr(Agreement, "signed_artifact_file_size")
    assert hasattr(Agreement, "signed_artifact_uploaded_at")
    assert hasattr(Agreement, "signed_artifact_updated_at")


def test_signed_artifact_field_defaults_and_private_storage():
    assert hasattr(Agreement, "signed_artifact")
    field = Agreement._meta.get_field("signed_artifact")
    from django.db.models import FileField

    assert isinstance(field, FileField)
    assert field.blank is True
    assert field.default == ""
    assert field.max_length == 255
    assert field.upload_to.startswith("agreements/signed/")
    # Private storage — rooted under PRIVATE_DOCUMENTS_ROOT, never MEDIA_ROOT.
    location = str(field.storage.location)
    assert location.endswith("private-uploads")


def test_artifact_metadata_field_types():
    assert hasattr(Agreement, "signed_artifact_file_size")
    from django.db.models import CharField, DateTimeField, PositiveIntegerField

    for name in ("signed_artifact_original_filename", "signed_artifact_content_type"):
        f = Agreement._meta.get_field(name)
        assert isinstance(f, CharField)
        assert f.blank is True
        assert f.default == ""
    assert isinstance(
        Agreement._meta.get_field("signed_artifact_file_size"), PositiveIntegerField
    )
    assert Agreement._meta.get_field("signed_artifact_file_size").default == 0
    for name in ("signed_artifact_uploaded_at", "signed_artifact_updated_at"):
        assert isinstance(Agreement._meta.get_field(name), DateTimeField)
        assert Agreement._meta.get_field(name).null is True
        assert Agreement._meta.get_field(name).blank is True


def test_no_artifact_model_no_validation_field_no_version_token():
    """P16-B stays absent from the Agreement schema (requirement 10)."""
    from apps.agreements import models as agreements_models

    assert getattr(agreements_models, "AgreementSignedArtifactValidation", None) is None
    assert not hasattr(Agreement, "signed_artifact_version")
    assert not hasattr(Agreement, "validation_error_code")
    assert not hasattr(Agreement, "is_valid")


def test_signed_artifact_max_bytes_setting_defined():
    assert getattr(settings, "SIGNED_ARTIFACT_MAX_BYTES", None) is not None


def test_single_audit_action_exists_without_replaced_variant():
    assert SIGNED_ARTIFACT_UPLOADED is not None
    assert not hasattr(core_models.AuditEvent.Action, "SIGNED_ARTIFACT_REPLACED")


# ---------------------------------------------------------------------------
# Happy-path upload (requirements 1, 2)
# ---------------------------------------------------------------------------


def test_upload_sets_private_agreement_fields_and_redacted_audit(agreement, actor):
    assert upload_signed_artifact is not None
    assert SIGNED_ARTIFACT_UPLOADED is not None
    body = b"%PDF-1.7\n"
    updated = upload_signed_artifact(
        agreement,
        uploaded_file("signed.PDF", body, "application/pdf"),
        actor,
    )
    updated.refresh_from_db()
    from django.db.models.fields.files import FieldFile

    assert isinstance(updated.signed_artifact, FieldFile)
    assert updated.signed_artifact.name.startswith("agreements/signed/")
    assert updated.signed_artifact_original_filename == "signed.PDF"
    assert updated.signed_artifact_content_type == "application/pdf"
    assert updated.signed_artifact_file_size == len(body)
    assert updated.signed_artifact_uploaded_at is not None
    assert updated.signed_artifact_updated_at is not None
    assert updated.signed_artifact.storage.exists(updated.signed_artifact.name)

    from apps.core.models import AuditEvent

    events = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED)
    ).order_by("pk")
    assert events.count() == 1
    event = events.get()
    assert event.actor == actor
    assert event.target_type == "agreement"
    assert event.target_id == str(agreement.pk)
    # Requirement 3/8: metadata is exactly {agreement_id, operation} — no
    # filename, content type, size, signer, or bytes ever recorded.
    assert event.metadata == {"agreement_id": agreement.pk, "operation": "uploaded"}


def test_upload_returns_the_agreement_instance(agreement, actor):
    assert upload_signed_artifact is not None
    updated = upload_signed_artifact(
        agreement, uploaded_file("a.pdf", b"%PDF-", "application/pdf"), actor
    )
    assert isinstance(updated, Agreement)
    assert updated.pk == agreement.pk


@pytest.mark.parametrize(
    "name, content_type, expected_content_type",
    [
        ("signed.PDF", "application/pdf", "application/pdf"),
        ("signed.pdf", "application/pdf", "application/pdf"),
        ("līgums.EDOC", "application/octet-stream", ""),
        ("līgums.edoc", "application/pdf", ""),
    ],
)
def test_upload_accepts_case_insensitive_pdf_and_edoc(
    agreement, actor, name, content_type, expected_content_type
):
    assert upload_signed_artifact is not None
    updated = upload_signed_artifact(
        agreement, uploaded_file(name, b"DATA-2026", content_type), actor
    )
    updated.refresh_from_db()
    assert updated.signed_artifact_original_filename == name
    assert updated.signed_artifact_content_type == expected_content_type
    assert updated.signed_artifact_file_size == len(b"DATA-2026")


def test_upload_accepts_pdf_with_blank_browser_content_type(actor, agreement):
    """Best-effort MIME policy: an empty browser content type is not a
    mismatch — the upload succeeds and the stored content type stays blank.
    No PDF magic-byte validation is required."""
    assert upload_signed_artifact is not None
    updated = upload_signed_artifact(
        agreement,
        uploaded_file("blank-mime.pdf", b"%PDF-1.7\n", ""),
        actor,
    )
    updated.refresh_from_db()
    assert updated.signed_artifact.name.startswith("agreements/signed/")
    assert updated.signed_artifact_original_filename == "blank-mime.pdf"
    assert updated.signed_artifact_content_type == ""
    assert updated.signed_artifact_file_size == len(b"%PDF-1.7\n")


def test_upload_does_not_change_state_or_create_billing(actor, agreement):
    assert upload_signed_artifact is not None
    from apps.billing.models import BillingRecord

    before_state = agreement.state
    before_external = (
        agreement.external_id,
        agreement.external_state,
        agreement.external_url,
        agreement.external_error_code,
        agreement.signing_path,
    )
    before_records = BillingRecord.objects.count()
    upload_signed_artifact(
        agreement, uploaded_file("x.pdf", b"%PDF-", "application/pdf"), actor
    )
    agreement.refresh_from_db()
    assert agreement.state == before_state
    assert BillingRecord.objects.count() == before_records
    assert (
        agreement.external_id,
        agreement.external_state,
        agreement.external_url,
        agreement.external_error_code,
        agreement.signing_path,
    ) == before_external


def test_co_created_billing_draft_still_untouched_by_upload(
    actor, agreement, default_plan,
):
    """An existing BillingRecord (even a draft on the same member) is not
    mutated or duplicated by an upload."""
    assert upload_signed_artifact is not None
    from decimal import Decimal

    from apps.billing.models import BillingRecord

    member = agreement.member
    BillingRecord.objects.create(
        member=member,
        plan=default_plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.DRAFT,
    )

    def snapshot(record):
        return (
            record.status,
            record.base_amount,
            record.final_amount,
            record.external_status,
        )

    before = snapshot(BillingRecord.objects.get(member=member))
    upload_signed_artifact(
        agreement, uploaded_file("x.pdf", b"%PDF-", "application/pdf"), actor
    )
    after = snapshot(BillingRecord.objects.get(member=member))
    assert after == before
    assert BillingRecord.objects.filter(member=member).count() == 1


# ---------------------------------------------------------------------------
# Validation failures — old artifact preserved (requirements 2, 3)
# ---------------------------------------------------------------------------


def _seeded_agreement(agreement, actor):
    """First successful upload via the service; returns (agreement, old_name)."""
    upload_signed_artifact(
        agreement,
        uploaded_file("first.pdf", b"%PDF-1.7\n", "application/pdf"),
        actor,
    )
    agreement.refresh_from_db()
    return agreement, agreement.signed_artifact.name


def test_reject_unsupported_suffix_preserves_old(actor, agreement):
    assert upload_signed_artifact is not None
    agreement, old_name = _seeded_agreement(agreement, actor)
    old_filename = agreement.signed_artifact_original_filename

    with pytest.raises(ValueError) as exc:
        upload_signed_artifact(
            agreement,
            uploaded_file("signed.txt", b"hello world", "text/plain"),
            actor,
        )
    assert str(exc.value) == _MSG_UNSUPPORTED
    agreement.refresh_from_db()
    assert agreement.signed_artifact.name == old_name
    assert agreement.signed_artifact_original_filename == old_filename
    assert agreement.signed_artifact.storage.exists(old_name)


def test_reject_oversized_file_preserves_old(settings, actor, agreement):
    assert upload_signed_artifact is not None
    # Seed under the default 20 MiB cap, then tighten the limit so the
    # replacement above the cap is rejected and the original survives. The
    # cap must apply uniformly to every upload including the first one.
    agreement, old_name = _seeded_agreement(agreement, actor)
    settings.SIGNED_ARTIFACT_MAX_BYTES = 4
    old_filename = agreement.signed_artifact_original_filename

    with pytest.raises(ValueError) as exc:
        upload_signed_artifact(
            agreement,
            uploaded_file("big.pdf", b"%PDF-12345", "application/pdf"),
            actor,
        )
    assert str(exc.value) == _MSG_OVERSIZED
    agreement.refresh_from_db()
    assert agreement.signed_artifact.name == old_name
    assert agreement.signed_artifact_original_filename == old_filename
    assert agreement.signed_artifact.storage.exists(old_name)


def test_first_upload_over_cap_is_rejected_without_side_effects(
    settings, actor, agreement,
):
    """The size cap applies to the first upload too — no artifact may exist
    with a file above ``SIGNED_ARTIFACT_MAX_BYTES``. Rejection leaves the
    Agreement blank and records no signed-artifact audit event."""
    assert upload_signed_artifact is not None
    assert SIGNED_ARTIFACT_UPLOADED is not None
    settings.SIGNED_ARTIFACT_MAX_BYTES = 4

    with pytest.raises(ValueError) as exc:
        upload_signed_artifact(
            agreement,
            uploaded_file(
                "oversized.pdf", b"%PDF-over-4-bytes", "application/pdf"
            ),
            actor,
        )
    assert str(exc.value) == _MSG_OVERSIZED

    agreement.refresh_from_db()
    assert agreement.signed_artifact.name == ""
    assert agreement.signed_artifact_original_filename == ""
    assert agreement.signed_artifact_content_type == ""
    assert agreement.signed_artifact_file_size == 0
    assert agreement.signed_artifact_uploaded_at is None
    assert agreement.signed_artifact_updated_at is None

    from apps.core.models import AuditEvent

    assert (
        AuditEvent.objects.filter(action=str(SIGNED_ARTIFACT_UPLOADED)).count() == 0
    )


def test_reject_pdf_mime_mismatch_preserves_old(actor, agreement):
    assert upload_signed_artifact is not None
    agreement, old_name = _seeded_agreement(agreement, actor)

    with pytest.raises(ValueError) as exc:
        upload_signed_artifact(
            agreement,
            uploaded_file("wrong.pdf", b"%PDF-", "text/plain"),
            actor,
        )
    assert str(exc.value) == _MSG_MIME
    agreement.refresh_from_db()
    assert agreement.signed_artifact.name == old_name
    assert agreement.signed_artifact.storage.exists(old_name)


def test_validation_failures_emit_no_audit_event(actor, agreement):
    assert upload_signed_artifact is not None
    assert SIGNED_ARTIFACT_UPLOADED is not None
    _seeded_agreement(agreement, actor)

    from apps.core.models import AuditEvent

    before_count = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED)
    ).count()
    with pytest.raises(ValueError):
        upload_signed_artifact(
            agreement,
            uploaded_file("bad.pdf", b"%PDF-", "text/plain"),
            actor,
        )
    after_count = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED)
    ).count()
    assert after_count == before_count


# ---------------------------------------------------------------------------
# Replacement (requirements 2, 3)
# ---------------------------------------------------------------------------


def test_replacement_updates_metadata_and_audits_operation_replaced(
    actor, agreement,
):
    assert upload_signed_artifact is not None
    assert SIGNED_ARTIFACT_UPLOADED is not None
    upload_signed_artifact(
        agreement,
        uploaded_file("first.pdf", b"%PDF-1.7\n", "application/pdf"),
        actor,
    )
    agreement.refresh_from_db()
    first_uploaded_at = agreement.signed_artifact_uploaded_at
    first_name = agreement.signed_artifact.name

    body2 = b"%PDF-2.0\nsecond"
    upload_signed_artifact(
        agreement,
        uploaded_file("second.pdf", body2, "application/pdf"),
        actor,
    )
    agreement.refresh_from_db()
    assert agreement.signed_artifact.name != first_name
    assert agreement.signed_artifact.name.startswith("agreements/signed/")
    assert agreement.signed_artifact_original_filename == "second.pdf"
    assert agreement.signed_artifact_file_size == len(body2)
    assert agreement.signed_artifact_uploaded_at == first_uploaded_at
    assert agreement.signed_artifact_updated_at is not None

    from apps.core.models import AuditEvent

    events = list(
        AuditEvent.objects.filter(action=str(SIGNED_ARTIFACT_UPLOADED)).order_by("pk")
    )
    assert len(events) == 2
    assert events[0].metadata == {
        "agreement_id": agreement.pk,
        "operation": "uploaded",
    }
    assert events[1].metadata == {
        "agreement_id": agreement.pk,
        "operation": "replaced",
    }
    for event in events:
        assert set(event.metadata) == {"agreement_id", "operation"}


def test_replacement_deletes_old_storage_only_after_commit(
    actor, agreement, django_capture_on_commit_callbacks,
):
    """Save new + commit DB first; the old private object is deleted only when
    the on_commit callback executes (requirement 3)."""
    assert upload_signed_artifact is not None
    with django_capture_on_commit_callbacks(execute=True):
        upload_signed_artifact(
            agreement,
            uploaded_file("first.pdf", b"%PDF-1.7\n", "application/pdf"),
            actor,
        )
    agreement.refresh_from_db()
    old_name = agreement.signed_artifact.name
    storage = agreement.signed_artifact.storage
    assert storage.exists(old_name)

    with django_capture_on_commit_callbacks(execute=True):
        upload_signed_artifact(
            agreement,
            uploaded_file("second.pdf", b"%PDF-2.0\n", "application/pdf"),
            actor,
        )
        # Inside the block the callback has not run yet — old object still there.
        assert storage.exists(old_name) is True
    # After block exit the captured on_commit callback has executed.
    assert storage.exists(old_name) is False
    agreement.refresh_from_db()
    assert storage.exists(agreement.signed_artifact.name) is True


def test_replacement_db_failure_preserves_old_field_storage_and_audit(
    actor, agreement,
):
    """If persistence fails after the new storage write, the old DB fields and
    storage object survive, the newly written object is best-effort removed,
    and no audit event is created (requirement 3)."""
    assert upload_signed_artifact is not None
    assert SIGNED_ARTIFACT_UPLOADED is not None
    from unittest.mock import patch

    upload_signed_artifact(
        agreement,
        uploaded_file("first.pdf", b"%PDF-1.7\n", "application/pdf"),
        actor,
    )
    agreement.refresh_from_db()
    old_name = agreement.signed_artifact.name
    old_filename = agreement.signed_artifact_original_filename
    storage = agreement.signed_artifact.storage

    from apps.core.models import AuditEvent

    before_audit = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED)
    ).count()

    with patch.object(
        Agreement, "save", side_effect=RuntimeError("db down")
    ), patch.object(storage, "delete", wraps=storage.delete) as delete_spy:
        with pytest.raises(RuntimeError):
            upload_signed_artifact(
                agreement,
                uploaded_file("second.pdf", b"%PDF-2.0\n", "application/pdf"),
                actor,
            )

    deleted_names = [call.args[0] for call in delete_spy.call_args_list]
    assert old_name not in deleted_names
    assert len(deleted_names) == 1, deleted_names
    # The best-effort cleanup removed the freshly written storage object.
    assert storage.exists(deleted_names[0]) is False

    agreement.refresh_from_db()
    assert agreement.signed_artifact.name == old_name
    assert agreement.signed_artifact_original_filename == old_filename
    assert storage.exists(old_name) is True
    after_audit = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED)
    ).count()
    assert after_audit == before_audit