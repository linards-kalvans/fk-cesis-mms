"""Task 2 contract tests: frozen snapshot, queue boundary and immutable publish.

These tests are intentionally written before the implementation.  They pin the
durable ``GeneratedAgreementDocument`` row, the explicit staff request/retry
services, the worker boundary and the private storage rules.  Everything is
stubbed: no provider, mail, billing or real network call may be involved.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

import pytest
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

TEMPLATE_VERSION = "v1-2026-11"

# Exact minimum frozen input.  Adding a field here is a document-contract
# change, not an ordinary test update.
FIELD_NAMES = (
    "agreement_number",
    "child_name",
    "child_personal_id",
    "child_birth_date",
    "child_address",
    "guardian_name",
    "guardian_personal_id",
    "guardian_address",
    "guardian_email",
    "guardian_phone",
)

PRODUCTION_ASSET_NAMES = (
    "v1_2026_11.html",
    "v1_2026_11.css",
    "DejaVuSans.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSansMono-Bold.ttf",
    "fk-cesis-logo.png",
)

# One structurally valid, empty A5 page.  The worker validates that published
# bytes are a readable PDF with a bounded page count, so the fixture must be a
# real document rather than a magic header plus trailer.
PDF_BYTES = base64.b64decode(
    "JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjguMgoKMSAwIG9iago8PC9UeXBl"
    "L0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjguMik+Pj4+CmVu"
    "ZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoK"
    "CjMgMCBvYmoKPDw+PgplbmRvYmoKCjQgMCBvYmoKPDwvVHlwZS9QYWdlL01lZGlhQm94WzAgMCAy"
    "MDAgMTAwXS9Sb3RhdGUgMC9SZXNvdXJjZXMgMyAwIFIvUGFyZW50IDIgMCBSPj4KZW5kb2JqCgp4"
    "cmVmCjAgNQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwNDIgMDAwMDAgbiAKMDAwMDAwMDEy"
    "MCAwMDAwMCBuIAowMDAwMDAwMTcyIDAwMDAwIG4gCjAwMDAwMDAxOTMgMDAwMDAgbiAKCnRyYWls"
    "ZXIKPDwvU2l6ZSA1L1Jvb3QgMSAwIFIvSURbPEMzOUNDMzhENURDMkIxQzJBNzQ3NjQ1Nzc5QzM5"
    "MDZBPjw5MkFEQkI1NUM4MkVDNDQ2OTlCQTFEQTUyOUFFRjU3Nz5dPj4Kc3RhcnR4cmVmCjI4NAol"
    "JUVPRgo="
)

PII_EMAIL = "frozen-pii@example.test"
PII_PHONE = "+37129999999"
PII_ADDRESS = "Slepenā adrese 42, Cēsis"


@pytest.fixture(autouse=True)
def isolated_private_storage(settings, tmp_path):
    settings.PRIVATE_DOCUMENTS_ROOT = tmp_path


@pytest.fixture
def local_agreement(agreement_member, agreement_guardian, default_plan):
    """A local-backend agreement with the minimum source data for a snapshot."""
    from apps.agreements.models import Agreement
    from apps.registrations.models import RegistrationApplication

    member = agreement_member
    guardian = agreement_guardian
    # The child address is application-owned, not member-owned.
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        parent_account=guardian.parent_account,
        guardian=guardian,
        approved_member=member,
        member_full_name=member.full_name,
        member_personal_id=member.personal_id,
        member_birth_date=member.birth_date,
        member_actual_address="Bērnu iela 9, Cēsis",
    )
    return Agreement.objects.create(
        member=member,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        document_backend=Agreement.DocumentBackend.LOCAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-777",
        billing_plan=default_plan,
        first_billing_month="2026-09",
    )


def _model():
    from apps.agreements.models import GeneratedAgreementDocument

    return GeneratedAgreementDocument


def _request_document(agreement, *, queue=None):
    from apps.agreements.document_generation import request_document_generation

    queue = queue if queue is not None else Mock()
    with _patch_enqueue(queue):
        document = request_document_generation(agreement, actor=None)
    return document, queue


def _retry_document(document, *, queue=None):
    from django.test import TestCase

    from apps.agreements.document_generation import retry_document_generation

    queue = queue if queue is not None else Mock()
    with _patch_enqueue(queue):
        # pytest-django wraps the test in an outer transaction, so on-commit
        # callbacks only run when this helper explicitly releases them.
        with TestCase.captureOnCommitCallbacks(execute=True):
            retried = retry_document_generation(document.agreement, actor=None)
    return retried, queue


def _retry_agreement(agreement, *, queue=None):
    from django.test import TestCase

    from apps.agreements.document_generation import retry_document_generation

    queue = queue if queue is not None else Mock()
    with _patch_enqueue(queue):
        with TestCase.captureOnCommitCallbacks(execute=True):
            retried = retry_document_generation(agreement, actor=None)
    return retried, queue


def _generate(document_id):
    from apps.agreements.document_tasks import generate_agreement_document

    generate_agreement_document(document_id)


@contextmanager
def _patch_enqueue(mock):
    """Patch the single queue boundary wherever the service resolves it.

    The plan names ``apps.agreements.document_tasks.enqueue_document_generation``
    as the boundary.  Patching both the task module and the service module keeps
    the test independent of whether the service imports the function directly or
    through the module, without allowing any real django-q job.
    """
    targets = (
        "apps.agreements.document_generation.enqueue_document_generation",
        "apps.agreements.document_tasks.enqueue_document_generation",
    )
    with ExitStack() as stack:
        for target in targets:
            stack.enter_context(patch(target, mock, create=True))
        yield mock


def _expected_frozen_fields(agreement):
    member = agreement.member
    guardian = member.guardian
    application = member.source_application
    return {
        "agreement_number": agreement.agreement_number,
        "child_name": member.full_name,
        "child_personal_id": member.personal_id,
        "child_birth_date": (
            member.birth_date.strftime("%d.%m.%Y") if member.birth_date else ""
        ),
        "child_address": application.member_actual_address,
        "guardian_name": guardian.display_name,
        "guardian_personal_id": guardian.personal_id,
        "guardian_address": guardian.address,
        "guardian_email": guardian.email,
        "guardian_phone": guardian.phone,
    }


def _assert_pending(document):
    assert document.status == "pending"
    assert document.file.name in ("", None)
    assert document.size_bytes == 0
    assert document.sha256 == ""
    assert document.ready_at is None
    assert document.error_code == ""


def _publish(document, *, pdf=PDF_BYTES):
    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", return_value=pdf
    ) as render:
        _generate(document.pk)
    document.refresh_from_db()
    assert document.status == "ready"
    assert render.call_count == 1
    return document


def _set_pg_session_timeouts():
    """Bound real concurrent DB work so a broken lock fails fast, not hangs."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = 20000")
        cursor.execute("SET lock_timeout = 10000")
        cursor.execute("SET idle_in_transaction_session_timeout = 20000")


def _in_worker(function):
    close_old_connections()
    try:
        _set_pg_session_timeouts()
        return function()
    finally:
        close_old_connections()


# ---------------------------------------------------------------------------
# Durable model contract
# ---------------------------------------------------------------------------


def test_generated_document_model_contract():
    from apps.documents.storage import PrivateDocumentStorage

    model = _model()
    agreement_field = model._meta.get_field("agreement")
    assert agreement_field.many_to_one is False
    assert agreement_field.one_to_one is True
    assert agreement_field.remote_field.related_name == "generated_document"
    assert agreement_field.remote_field.on_delete.__name__ == "CASCADE"

    status = model._meta.get_field("status")
    assert status.default == "pending"
    assert {value for value, _label in status.choices} == {
        "pending",
        "ready",
        "failed",
    }
    assert model._meta.get_field("template_version").max_length >= 16
    assert model._meta.get_field("signing_path").max_length >= 16
    assert model._meta.get_field("snapshot").default is dict
    assert model._meta.get_field("provenance").default is dict
    assert model._meta.get_field("sha256").max_length == 64
    assert model._meta.get_field("size_bytes").null is False
    assert model._meta.get_field("ready_at").null is True
    assert model._meta.get_field("error_code").blank is True
    assert isinstance(model._meta.get_field("file").storage, PrivateDocumentStorage)
    assert model._meta.get_field("created_at") is not None
    assert model._meta.get_field("updated_at") is not None


# ---------------------------------------------------------------------------
# Explicit request, frozen input and queue ordering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_is_explicit_and_creates_nothing_on_agreement_creation(settings):
    from apps.agreements.services import create_agreement_for_member
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication
    from tests.support import make_guardian

    settings.AGREEMENT_DOCUMENT_MODE = "local"
    guardian = make_guardian(
        full_name="Anna Bērziņa",
        email="explicit@example.test",
        personal_id="111111-11111",
        address="Guardian iela 1, Cēsis",
    )
    member = Member.objects.create(
        full_name="Eksplicīts Bērns",
        personal_id="151210-22222",
        birth_date=date(2015, 12, 10),
        guardian=guardian,
    )
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        parent_account=guardian.parent_account,
        guardian=guardian,
        approved_member=member,
        member_full_name=member.full_name,
        member_personal_id=member.personal_id,
        member_birth_date=member.birth_date,
        member_actual_address="Bērnu iela 9, Cēsis",
    )
    created = create_agreement_for_member(member, "paper")

    assert created.document_backend == "local"
    assert not _model().objects.filter(agreement=created).exists()

    document, _queue = _request_document(created)
    assert document.pk is not None
    assert _model().objects.filter(agreement=created).count() == 1


@pytest.mark.django_db
def test_request_freezes_exact_minimum_fields_and_version(local_agreement):
    document, _queue = _request_document(local_agreement)
    document.refresh_from_db()

    expected = _expected_frozen_fields(local_agreement)
    assert set(expected) == set(FIELD_NAMES)
    assert document.agreement_id == local_agreement.pk
    assert document.template_version == TEMPLATE_VERSION
    assert document.signing_path == "paper"
    assert document.snapshot == {"fields": expected, "signing_path": "paper"}
    assert set(document.snapshot["fields"]) == set(FIELD_NAMES)
    _assert_pending(document)


@pytest.mark.django_db
def test_snapshot_excludes_ocr_documents_training_group_and_billing(
    local_agreement, default_plan
):
    from apps.billing.models import BillingRecord
    from apps.members.models import TrainingGroup

    group = TrainingGroup.objects.create(name="Slepenā grupa U11")
    local_agreement.member.training_group = group
    local_agreement.member.save(update_fields=["training_group"])
    BillingRecord.objects.create(
        member=local_agreement.member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("1.00"),
        manual_amount_override=Decimal("1.00"),
        manual_override_reason="billing-internal-only",
    )

    document, _queue = _request_document(local_agreement)
    document.refresh_from_db()

    assert set(document.snapshot) == {"fields", "signing_path"}
    assert set(document.snapshot["fields"]) == set(FIELD_NAMES)
    rendered = repr(document.snapshot)
    for forbidden in (
        "Slepenā grupa U11",
        "billing-internal-only",
        "ocr",
        "training_group",
        "uploaded",
        "document",
    ):
        assert forbidden not in rendered


@pytest.mark.django_db
def test_request_records_renderer_provenance_and_hashes(local_agreement):
    document, _queue = _request_document(local_agreement)
    document.refresh_from_db()

    provenance = document.provenance
    assert provenance["template_version"] == TEMPLATE_VERSION
    assert provenance["weasyprint"] == "70.0"
    assert provenance["pango"]
    assert provenance["harfbuzz"]
    assert set(provenance["assets"]) == set(PRODUCTION_ASSET_NAMES)
    for name in PRODUCTION_ASSET_NAMES:
        assert isinstance(provenance["assets"][name], str)
        assert len(provenance["assets"][name]) == 64


@pytest.mark.django_db
def test_frozen_input_survives_profile_changes(local_agreement):
    document, _queue = _request_document(local_agreement)
    frozen = deepcopy(document.snapshot)

    guardian = local_agreement.member.guardian
    guardian.first_name = "Mainīts"
    guardian.family_name = "Vēlāk"
    guardian.personal_id = "999999-99999"
    guardian.address = "Mainīta adrese 1"
    guardian.save()
    account = guardian.parent_account
    account.email = PII_EMAIL
    account.phone = PII_PHONE
    account.save(update_fields=["email", "phone", "updated_at"])

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", return_value=PDF_BYTES
    ) as render:
        _generate(document.pk)

    assert render.call_args.args[0] == frozen
    document.refresh_from_db()
    assert document.status == "ready"


@pytest.mark.django_db
def test_snapshot_is_not_exposed_by_repr_logs_audit_or_admin(
    local_agreement, caplog
):
    from django.contrib import admin as django_admin

    from apps.core.models import AuditEvent

    document, _queue = _request_document(local_agreement)
    document.refresh_from_db()
    pii_values = (
        PII_EMAIL,
        PII_PHONE,
        PII_ADDRESS,
        local_agreement.member.personal_id,
        local_agreement.member.guardian.personal_id,
    )

    caplog.set_level(logging.WARNING)
    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        side_effect=RuntimeError(PII_EMAIL),
    ):
        _generate(document.pk)

    text = "\n".join(
        [
            str(document),
            repr(document),
            caplog.text,
            repr(AuditEvent.objects.values_list("metadata", "target_repr")),
        ]
    )
    for value in pii_values:
        if value:
            assert value not in text

    model_admin = django_admin.site._registry.get(_model())
    if model_admin is not None:
        explicit = set(model_admin.fields or ()) | set(model_admin.readonly_fields or ())
        assert "snapshot" not in explicit


@pytest.mark.django_db
def test_exports_do_not_read_the_frozen_snapshot(local_agreement):
    from apps.members.exports import member_row
    from apps.registrations.exports import application_row

    document, _queue = _request_document(local_agreement)
    snapshot = deepcopy(document.snapshot)
    snapshot["fields"]["child_name"] = "EXPORT-ONLY-SENTINEL"
    _model().objects.filter(pk=document.pk).update(snapshot=snapshot)

    application = local_agreement.member.source_application
    rows = [
        member_row(local_agreement.member, sensitive=True),
        application_row(application, sensitive=True),
    ]
    assert "EXPORT-ONLY-SENTINEL" not in repr(rows)


@pytest.mark.django_db
def test_enqueue_runs_only_after_commit(local_agreement, django_capture_on_commit_callbacks):
    from apps.agreements.document_generation import request_document_generation

    queue = Mock()
    with _patch_enqueue(queue):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            with transaction.atomic():
                document = request_document_generation(local_agreement, actor=None)
            assert not queue.called

    assert len(callbacks) == 1
    for callback in callbacks:
        callback()
    queue.assert_called_once_with(document.pk)


@pytest.mark.django_db
def test_rollback_never_enqueues_or_persists_a_row(local_agreement):
    from apps.agreements.document_generation import request_document_generation

    queue = Mock()
    with _patch_enqueue(queue):
        with pytest.raises(RuntimeError, match="rollback"):
            with transaction.atomic():
                request_document_generation(local_agreement, actor=None)
                raise RuntimeError("rollback")

    assert not queue.called
    assert not _model().objects.exists()


@pytest.mark.django_db
def test_queue_failure_is_visible_and_retryable(
    local_agreement, caplog, django_capture_on_commit_callbacks
):
    from apps.agreements.document_generation import request_document_generation

    secret = "queue-failure@example.test"
    caplog.set_level(logging.WARNING)
    queue = Mock(side_effect=RuntimeError(secret))
    with _patch_enqueue(queue):
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                document = request_document_generation(local_agreement, actor=None)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "queue_failed"
    assert document.snapshot
    assert secret not in caplog.text

    retried, retry_queue = _retry_document(document)
    retried.refresh_from_db()
    assert retried.status == "pending"
    assert retried.error_code == ""
    assert retried.snapshot == document.snapshot
    retry_queue.assert_called_once_with(document.pk)


# ---------------------------------------------------------------------------
# Explicit retry and stale pending recovery
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fresh_pending_document_is_not_retryable(local_agreement):
    document, _queue = _request_document(local_agreement)

    with pytest.raises(ValueError, match="not_retryable"):
        _retry_document(document)


@pytest.mark.django_db
def test_stale_pending_document_is_retryable(local_agreement):
    document, _queue = _request_document(local_agreement)
    frozen = deepcopy(document.snapshot)
    _model().objects.filter(pk=document.pk).update(
        updated_at=timezone.now() - timedelta(minutes=6)
    )

    retried, retry_queue = _retry_document(document)

    retried.refresh_from_db()
    assert retried.pk == document.pk
    assert retried.status == "pending"
    assert retried.snapshot == frozen
    retry_queue.assert_called_once_with(document.pk)


@pytest.mark.django_db
def test_ready_document_is_never_retryable(local_agreement):
    document, _queue = _request_document(local_agreement)
    document = _publish(document)
    _model().objects.filter(pk=document.pk).update(
        updated_at=timezone.now() - timedelta(minutes=6)
    )

    with pytest.raises(ValueError, match="not_retryable"):
        _retry_document(document)


@pytest.mark.django_db
def test_retry_after_failure_reuses_the_frozen_input(local_agreement):
    document, _queue = _request_document(local_agreement)
    frozen = deepcopy(document.snapshot)

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        side_effect=RuntimeError("first render failed"),
    ):
        _generate(document.pk)
    document.refresh_from_db()
    assert document.status == "failed"
    assert document.snapshot == frozen

    guardian = local_agreement.member.guardian
    guardian.first_name = "Mainīts"
    guardian.family_name = "Pēc neizdošanās"
    guardian.save()

    retried, _retry_queue = _retry_document(document)
    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", return_value=PDF_BYTES
    ) as render:
        _generate(retried.pk)

    assert render.call_args.args[0] == frozen
    retried.refresh_from_db()
    assert retried.status == "ready"
    assert retried.snapshot == {}


# ---------------------------------------------------------------------------
# Worker publication, bounds, provenance and cleanup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_worker_publishes_once_clears_snapshot_and_keeps_provenance(local_agreement):
    document, _queue = _request_document(local_agreement)
    original_provenance = deepcopy(document.provenance)

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", return_value=PDF_BYTES
    ) as render:
        _generate(document.pk)
        _generate(document.pk)

    document.refresh_from_db()
    assert render.call_count == 1
    assert document.status == "ready"
    assert document.file.read() == PDF_BYTES
    assert document.size_bytes == len(PDF_BYTES)
    assert document.sha256 == hashlib.sha256(PDF_BYTES).hexdigest()
    assert document.ready_at is not None
    assert document.snapshot == {}
    assert document.error_code == ""
    assert document.provenance == original_provenance
    files = list(Path(document.file.storage.location).rglob("*.pdf"))
    assert len(files) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["malformed", "oversized"])
def test_worker_rejects_malformed_or_oversized_output(local_agreement, case):
    document, _queue = _request_document(local_agreement)
    frozen = deepcopy(document.snapshot)
    rendered = (
        b"not a pdf"
        if case == "malformed"
        else b"%PDF-" + b"0" * (20 * 1024 * 1024)
    )

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", return_value=rendered
    ):
        _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "invalid_output"
    assert document.snapshot == frozen
    assert not document.file
    assert not list(Path(document.file.storage.location).rglob("*.pdf"))


@pytest.mark.django_db
def test_worker_rejects_changed_renderer_provenance(local_agreement):
    document, _queue = _request_document(local_agreement)
    altered = deepcopy(document.provenance)
    altered["template_version"] = "v1-2099-01"
    altered["assets"] = {}

    with patch(
        "apps.agreements.document_tasks.agreement_renderer_provenance",
        return_value=altered,
    ):
        with patch(
            "apps.agreements.document_tasks.render_agreement_pdf"
        ) as render:
            _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "version_mismatch"
    assert document.snapshot
    assert not render.called


@pytest.mark.django_db
def test_worker_rejects_missing_renderer_provenance(local_agreement):
    document, _queue = _request_document(local_agreement)
    _model().objects.filter(pk=document.pk).update(provenance={})

    with patch("apps.agreements.document_tasks.render_agreement_pdf") as render:
        _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "version_mismatch"
    assert document.snapshot
    assert not render.called


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["render", "storage"])
def test_worker_failure_is_redacted_and_preserves_snapshot(
    local_agreement, failure, caplog
):
    document, _queue = _request_document(local_agreement)
    frozen = deepcopy(document.snapshot)
    caplog.set_level(logging.WARNING)

    if failure == "render":
        render_patch = patch(
            "apps.agreements.document_tasks.render_agreement_pdf",
            side_effect=RuntimeError(PII_EMAIL),
        )
        storage_patch = patch("apps.documents.storage.PrivateDocumentStorage.save")
    else:
        render_patch = patch(
            "apps.agreements.document_tasks.render_agreement_pdf",
            return_value=PDF_BYTES,
        )
        storage_patch = patch(
            "apps.documents.storage.PrivateDocumentStorage.save",
            side_effect=RuntimeError(PII_EMAIL),
        )

    with render_patch, storage_patch:
        _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "render_failed"
    assert document.snapshot == frozen
    assert not document.file
    assert not list(Path(document.file.storage.location).rglob("*.pdf"))
    assert PII_EMAIL not in caplog.text


@pytest.mark.django_db
def test_failed_publication_removes_temporary_file_and_keeps_snapshot(local_agreement):
    model = _model()
    document, _queue = _request_document(local_agreement)
    frozen = deepcopy(document.snapshot)
    original_save = model.save

    def fail_publication(self, *args, **kwargs):
        if self.status == "ready":
            raise OSError("private publication path")
        return original_save(self, *args, **kwargs)

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", return_value=PDF_BYTES
    ):
        with patch.object(model, "save", fail_publication):
            _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.snapshot == frozen
    assert not document.file
    assert not list(Path(document.file.storage.location).rglob("*.pdf"))


@pytest.mark.django_db
def test_published_bytes_survive_duplicate_worker_failure(local_agreement):
    document = _publish(_request_document(local_agreement)[0])
    storage, name = document.file.storage, document.file.name

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        side_effect=RuntimeError("must not regenerate"),
    ) as render:
        _generate(document.pk)

    assert not render.called
    assert storage.exists(name)
    assert document.file.read() == PDF_BYTES
    document.refresh_from_db()
    assert document.status == "ready"
    assert document.sha256 == hashlib.sha256(PDF_BYTES).hexdigest()


@pytest.mark.django_db
def test_worker_noops_for_a_deleted_document(local_agreement):
    document, _queue = _request_document(local_agreement)
    document_id = document.pk
    document.delete()

    with patch("apps.agreements.document_tasks.render_agreement_pdf") as render:
        _generate(document_id)

    assert not render.called
    assert not _model().objects.filter(pk=document_id).exists()


@pytest.mark.django_db
def test_deleting_document_cleans_private_file_after_commit(
    local_agreement, django_capture_on_commit_callbacks
):
    document = _publish(_request_document(local_agreement)[0])
    storage, name = document.file.storage, document.file.name

    with django_capture_on_commit_callbacks(execute=True):
        document.delete()
        assert storage.exists(name)

    assert not storage.exists(name)


@pytest.mark.django_db
def test_generation_has_no_provider_mail_or_billing_side_effects(local_agreement):
    from django.core import mail

    from apps.agreements.models import Agreement
    from apps.billing.models import BillingRecord

    agreement_fields = (
        "state",
        "sent_at",
        "signed_at",
        "voided_at",
        "external_provider",
        "external_id",
        "external_state",
        "external_url",
        "external_error_code",
    )
    before = Agreement.objects.filter(pk=local_agreement.pk).values(*agreement_fields).get()
    billing_before = BillingRecord.objects.count()

    with patch(
        "apps.integrations.agreement_platform.create_submission",
        side_effect=AssertionError("provider create must not run"),
    ), patch(
        "apps.integrations.agreement_platform.sync_submission",
        side_effect=AssertionError("provider sync must not run"),
    ), patch(
        "apps.integrations.agreement_platform.archive_submission",
        side_effect=AssertionError("provider archive must not run"),
    ), patch(
        "apps.agreements.services.send_mail",
        side_effect=AssertionError("mail must not run"),
    ):
        document, _queue = _request_document(local_agreement)
        _publish(document)

    after = Agreement.objects.filter(pk=local_agreement.pk).values(*agreement_fields).get()
    assert after == before
    assert BillingRecord.objects.count() == billing_before
    assert mail.outbox == []


# ---------------------------------------------------------------------------
# Row lock and real PostgreSQL concurrency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_locks_the_agreement_row(local_agreement, monkeypatch):
    from apps.agreements.models import Agreement

    original = Agreement.objects.select_for_update
    calls = []

    def spy(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(Agreement.objects, "select_for_update", spy)

    _request_document(local_agreement)

    assert calls


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_create_exactly_one_row(local_agreement):
    from apps.agreements.document_generation import request_document_generation
    from apps.agreements.models import Agreement

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")

    barrier = Barrier(2)

    def worker():
        def run():
            agreement = Agreement.objects.get(pk=local_agreement.pk)
            barrier.wait(timeout=10)
            return request_document_generation(agreement, actor=None).pk

        return _in_worker(run)

    queue = Mock()
    with _patch_enqueue(queue):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            ids = [future.result(timeout=30) for future in futures]

    assert len(set(ids)) == 1
    assert _model().objects.count() == 1
    assert _model().objects.get().status == "pending"


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_publish_one_winning_file(local_agreement):
    from apps.agreements.models import GeneratedAgreementDocument

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")

    document, _queue = _request_document(local_agreement)
    barrier = Barrier(2)

    def render(*args, **kwargs):
        barrier.wait(timeout=10)
        return PDF_BYTES

    def worker():
        return _in_worker(lambda: _generate(document.pk))

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf", side_effect=render
    ) as render_mock:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=30)

    assert render_mock.call_count == 2
    stored = GeneratedAgreementDocument.objects.get(pk=document.pk)
    assert stored.status == "ready"
    assert stored.file.read() == PDF_BYTES
    assert stored.sha256 == hashlib.sha256(PDF_BYTES).hexdigest()
    assert stored.size_bytes == len(PDF_BYTES)
    assert stored.snapshot == {}
    files = list(Path(stored.file.storage.location).rglob("*.pdf"))
    assert len(files) == 1


# ---------------------------------------------------------------------------
# Review follow-up: retry routing, commit reconciliation and source contract
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_retry_resolves_document_by_agreement_id_not_agreement_pk(local_agreement):
    """Agreement and document are separate tables; their PKs may legitimately
    differ. Retry receives an Agreement and must resolve the document by its
    ``agreement_id``, never by reusing the agreement's PK as a document PK."""
    from apps.agreements.document_generation import retry_document_generation

    while True:
        document, _queue = _request_document(local_agreement)
        if document.pk != local_agreement.pk:
            break
        document.delete()
    assert document.pk != local_agreement.pk
    _model().objects.filter(pk=document.pk).update(
        status="failed", error_code="render_failed"
    )

    queue = Mock()
    with _patch_enqueue(queue):
        from django.test import TestCase

        with TestCase.captureOnCommitCallbacks(execute=True):
            retried = retry_document_generation(local_agreement, actor=None)

    retried.refresh_from_db()
    assert retried.pk == document.pk
    assert retried.status == "pending"
    assert retried.snapshot == document.snapshot
    queue.assert_called_once_with(document.pk)


@pytest.mark.django_db
def test_retry_locks_the_agreement_row(local_agreement, monkeypatch):
    from apps.agreements.models import Agreement

    document, _queue = _request_document(local_agreement)
    _model().objects.filter(pk=document.pk).update(status="failed")
    calls = []
    original = Agreement.objects.select_for_update

    def spy(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(Agreement.objects, "select_for_update", spy)
    _retry_agreement(local_agreement)

    assert calls


@pytest.mark.django_db
def test_stale_failure_cannot_clobber_newer_retry(local_agreement):
    document, _queue = _request_document(local_agreement)
    _model().objects.filter(pk=document.pk).update(
        updated_at=timezone.now() - timedelta(minutes=6)
    )

    def render_then_retry(*args, **kwargs):
        _retry_agreement(local_agreement)
        raise RuntimeError("stale worker failure")

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        side_effect=render_then_retry,
    ):
        _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "pending"
    assert document.error_code == ""
    assert document.snapshot


@pytest.mark.django_db
def test_stale_failure_does_not_clobber_ready_document(local_agreement):
    from apps.agreements import document_tasks

    document = _publish(_request_document(local_agreement)[0])
    old_attempt = document.updated_at - timedelta(seconds=1)

    document_tasks._fail_if_unchanged(document.pk, "render_failed", old_attempt)

    document.refresh_from_db()
    assert document.status == "ready"
    assert document.file.read() == PDF_BYTES


@pytest.mark.django_db
def test_worker_survives_document_deletion_during_render(local_agreement):
    document, _queue = _request_document(local_agreement)
    storage = document.file.storage

    def delete_then_render(*args, **kwargs):
        _model().objects.filter(pk=document.pk).delete()
        return PDF_BYTES

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        side_effect=delete_then_render,
    ):
        _generate(document.pk)

    assert not _model().objects.filter(pk=document.pk).exists()
    assert not list(Path(storage.location).rglob("*.pdf"))


@pytest.mark.django_db
def test_commit_uncertainty_keeps_winning_file_when_row_is_committed(local_agreement):
    document, _queue = _request_document(local_agreement)
    storage = document.file.storage

    def fail_after_write(self, *args, **kwargs):
        raise OSError("commit outcome uncertain")

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        return_value=PDF_BYTES,
    ), patch.object(_model(), "save", fail_after_write), patch(
        "apps.agreements.document_tasks._publication_outcome",
        return_value=True,
        create=True,
    ), patch(
        "apps.agreements.document_tasks._delete_quietly"
    ) as delete_spy:
        _generate(document.pk)

    files = list(Path(storage.location).rglob("*.pdf"))
    assert len(files) == 1
    delete_spy.assert_not_called()


@pytest.mark.django_db
def test_commit_uncertainty_leaves_orphan_when_outcome_unknown(local_agreement):
    document, _queue = _request_document(local_agreement)
    storage = document.file.storage

    def fail_after_write(self, *args, **kwargs):
        raise OSError("commit outcome uncertain")

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        return_value=PDF_BYTES,
    ), patch.object(_model(), "save", fail_after_write), patch(
        "apps.agreements.document_tasks._publication_outcome",
        side_effect=RuntimeError("database unavailable"),
        create=True,
    ), patch(
        "apps.agreements.document_tasks._delete_quietly"
    ) as delete_spy:
        _generate(document.pk)

    files = list(Path(storage.location).rglob("*.pdf"))
    assert len(files) == 1
    delete_spy.assert_not_called()


@pytest.mark.django_db
def test_worker_guards_missing_native_pdf_import(local_agreement):
    document, _queue = _request_document(local_agreement)

    with patch.dict(sys.modules, {"pymupdf": None}):
        with patch(
            "apps.agreements.document_tasks.render_agreement_pdf",
            return_value=PDF_BYTES,
        ):
            _generate(document.pk)

    document.refresh_from_db()
    assert document.status == "failed"
    assert document.error_code == "invalid_output"


@pytest.mark.django_db
def test_ready_lookup_ignores_a_stale_cached_relation(local_agreement):
    from apps.agreements.document_generation import get_ready_document

    document, _queue = _request_document(local_agreement)
    assert local_agreement.generated_document.status == "pending"
    _model().objects.filter(pk=document.pk).update(
        status="ready",
        file="agreements/generated/fresh.pdf",
        size_bytes=1,
        sha256="0" * 64,
    )

    fresh = get_ready_document(local_agreement)
    assert fresh.pk == document.pk
    assert fresh.status == "ready"


@pytest.mark.django_db
def test_generated_document_is_not_registered_in_admin():
    from django.contrib import admin

    assert admin.site._registry.get(_model()) is None


def _clear_required_source(member, application, guardian, field):
    if field == "child_name":
        member.full_name = ""
        application.member_full_name = ""
    elif field == "child_personal_id":
        member.personal_id = ""
        application.member_personal_id = ""
    elif field == "child_birth_date":
        member.birth_date = None
        application.member_birth_date = None
    elif field == "child_address":
        application.member_actual_address = ""
    elif field == "guardian_name":
        guardian.first_name = ""
        guardian.family_name = ""
    elif field == "guardian_personal_id":
        guardian.personal_id = ""
    elif field == "guardian_address":
        guardian.address = ""
    else:  # pragma: no cover - defensive test helper
        raise AssertionError(field)
    member.save()
    application.save()
    guardian.save()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    [
        "child_name",
        "child_personal_id",
        "child_birth_date",
        "child_address",
        "guardian_name",
        "guardian_personal_id",
        "guardian_address",
    ],
)
def test_request_fails_closed_when_required_source_is_missing(
    local_agreement, field
):
    from apps.registrations.models import RegistrationApplication

    member = local_agreement.member
    guardian = member.guardian
    application = RegistrationApplication.objects.get(approved_member=member)
    _clear_required_source(member, application, guardian, field)

    with pytest.raises(ValueError, match="document_generation_unavailable"):
        _request_document(local_agreement)
    assert not _model().objects.filter(agreement=local_agreement).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("terminal_state", ["void", "superseded"])
def test_worker_never_publishes_when_agreement_ends_during_render(
    local_agreement, terminal_state
):
    """A void/superseded agreement must not receive a newly published PDF.

    The worker renders outside every lock, so the agreement can reach a
    terminal lifecycle state between the freeze and publication. That late
    transition must abort the publish and clean the temporary file instead of
    leaving an operative-looking artifact attached to a dead agreement.
    """
    from apps.agreements.models import Agreement

    document, _queue = _request_document(local_agreement)
    storage = document.file.storage

    def end_agreement_then_render(*args, **kwargs):
        changes = {"state": terminal_state}
        if terminal_state == "superseded":
            changes["is_current"] = False
        Agreement.objects.filter(pk=local_agreement.pk).update(**changes)
        return PDF_BYTES

    with patch(
        "apps.agreements.document_tasks.render_agreement_pdf",
        side_effect=end_agreement_then_render,
    ):
        _generate(document.pk)

    document.refresh_from_db()
    local_agreement.refresh_from_db()
    assert local_agreement.state == terminal_state
    if terminal_state == "superseded":
        assert local_agreement.is_current is False
    assert document.status == "failed"
    assert document.file.name in ("", None)
    assert not list(Path(storage.location).rglob("*.pdf"))


@pytest.mark.django_db
@pytest.mark.parametrize("terminal_state", ["void", "superseded"])
def test_terminal_agreement_keeps_already_ready_historical_bytes(
    local_agreement, terminal_state
):
    """An agreement ending later must not delete bytes already published."""
    from apps.agreements.models import Agreement

    document = _publish(_request_document(local_agreement)[0])
    storage, name = document.file.storage, document.file.name

    changes = {"state": terminal_state}
    if terminal_state == "superseded":
        changes["is_current"] = False
    Agreement.objects.filter(pk=local_agreement.pk).update(**changes)

    _generate(document.pk)

    assert storage.exists(name)
    document.refresh_from_db()
    assert document.status == "ready"
    assert document.file.read() == PDF_BYTES


@pytest.mark.django_db
def test_request_uses_registration_legacy_child_fields_when_member_is_blank(
    local_agreement,
):
    from apps.registrations.models import RegistrationApplication

    member = local_agreement.member
    application = RegistrationApplication.objects.get(approved_member=member)
    expected = {
        "child_name": application.member_full_name,
        "child_personal_id": application.member_personal_id,
        "child_birth_date": application.member_birth_date.strftime("%d.%m.%Y"),
        "child_address": application.member_actual_address,
    }
    member.full_name = ""
    member.personal_id = ""
    member.birth_date = None
    member.save()

    document, _queue = _request_document(local_agreement)

    for key, value in expected.items():
        assert document.snapshot["fields"][key] == value


@pytest.mark.django_db
@pytest.mark.parametrize("signing_path", ["paper", "electronic"])
def test_request_allows_missing_guardian_contact_and_keeps_frozen_path(
    local_agreement, signing_path
):
    from apps.agreements.models import Agreement
    from apps.registrations.models import RegistrationApplication

    agreement = Agreement.objects.get(pk=local_agreement.pk)
    agreement.signing_path = signing_path
    agreement.save(update_fields=["signing_path"])
    application = RegistrationApplication.objects.get(
        approved_member=agreement.member
    )
    application.preferred_agreement_signing = signing_path
    application.save(update_fields=["preferred_agreement_signing"])
    guardian = agreement.member.guardian
    guardian.parent_account.email = ""
    guardian.parent_account.phone = ""
    guardian.parent_account.save(update_fields=["email", "phone", "updated_at"])

    document, _queue = _request_document(agreement)
    document.refresh_from_db()

    assert document.signing_path == signing_path
    assert document.snapshot["signing_path"] == signing_path
    assert document.snapshot["fields"]["guardian_email"] == ""
    assert document.snapshot["fields"]["guardian_phone"] == ""


@pytest.mark.django_db
def test_request_maps_initial_provenance_error_to_staff_safe_value_error(
    local_agreement, caplog
):
    caplog.set_level(logging.WARNING)
    with patch(
        "apps.agreements.document_generation.agreement_renderer_provenance",
        side_effect=RuntimeError("asset_digest_mismatch"),
    ):
        with pytest.raises(ValueError, match="document_generation_unavailable"):
            _request_document(local_agreement)

    assert not _model().objects.filter(agreement=local_agreement).exists()
    assert "asset_digest_mismatch" not in caplog.text


@pytest.mark.django_db
def test_publication_outcome_rechecks_the_fresh_ready_row(local_agreement):
    from apps.agreements import document_tasks

    document = _publish(_request_document(local_agreement)[0])

    assert document_tasks._publication_outcome(
        document.pk, document.file.name, document.sha256
    )
    assert not document_tasks._publication_outcome(
        document.pk, document.file.name, "0" * 64
    )


@pytest.mark.django_db
def test_request_uses_guardian_address_for_same_address_child(local_agreement):
    from apps.registrations.models import RegistrationApplication

    application = RegistrationApplication.objects.get(
        approved_member=local_agreement.member
    )
    application.member_actual_address = ""
    application.member_same_address_as_guardian = True
    application.save(
        update_fields=["member_actual_address", "member_same_address_as_guardian"]
    )

    document, _queue = _request_document(local_agreement)

    assert document.snapshot["fields"]["child_address"] == (
        local_agreement.member.guardian.address
    )
