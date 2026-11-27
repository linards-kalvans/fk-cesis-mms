"""Task 3 red-phase contract: local agreement lifecycle guards.

Pins the post-Task-2 rules for locally generated agreements:

* a readable, ready private PDF is required before handover *and* explicit
  signing confirmation;
* blocked transitions mutate no agreement state, mail, audit or billing;
* a real signed-artifact upload is required before local signing confirmation;
* the frozen signing path cannot be changed through the service setter or the
  application admin ``save_model``;
* local notices are plain, club-owned mail with no provider link, session claim
  or attachment;
* local rows never enqueue or call DocuSeal.

No provider or SMTP network is touched: the provider boundary is patched to
fail loudly if reached and mail uses Django's locmem backend.
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement, GeneratedAgreementDocument
from apps.agreements.services import (
    mark_agreement_sent,
    mark_agreement_signed,
    set_signing_path,
    upload_signed_artifact,
    void_agreement,
)
from apps.billing.models import BillingRecord
from apps.core.models import AuditEvent
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.7\nlocal agreement fixture\n"

_TRANSITION_FIELDS = (
    "state",
    "sent_at",
    "signed_at",
    "signing_path",
    "signed_artifact",
    "external_provider",
    "external_id",
    "external_state",
    "external_url",
    "external_error_code",
)

_FORBIDDEN_NOTICE_FRAGMENTS = (
    "DocuSeal",
    "docuseal",
    "stub.invalid",
    "https://stub",
    "parakstīšanas saite",
    "saņemsiet atsevišķā e-pastā",
    "sesij",
)


@pytest.fixture(autouse=True)
def isolated_private_storage(settings, tmp_path):
    settings.PRIVATE_DOCUMENTS_ROOT = tmp_path


@pytest.fixture
def actor(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="local-lifecycle-staff", is_staff=True)


@pytest.fixture
def local_agreement(agreement_member, agreement_guardian, default_plan):
    """A current local-backend agreement with a valid billing intent."""
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        parent_account=agreement_guardian.parent_account,
        guardian=agreement_guardian,
        approved_member=agreement_member,
        member_full_name=agreement_member.full_name,
        member_personal_id=agreement_member.personal_id,
        member_birth_date=agreement_member.birth_date,
        member_actual_address="Bērnu iela 9, Cēsis",
        preferred_agreement_signing=Agreement.SigningPath.PAPER,
    )
    return Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        document_backend=Agreement.DocumentBackend.LOCAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-880",
        billing_plan=default_plan,
        first_billing_month="2026-09",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _use_signing_path(agreement, signing_path):
    agreement.signing_path = signing_path
    agreement.save(update_fields=["signing_path"])
    application = agreement.member.source_application
    application.preferred_agreement_signing = signing_path
    application.save(update_fields=["preferred_agreement_signing"])
    return agreement


def _pending_document(agreement):
    return GeneratedAgreementDocument.objects.create(
        agreement=agreement,
        status=GeneratedAgreementDocument.Status.PENDING,
        template_version="v1-2026-11",
        signing_path=agreement.signing_path,
        snapshot={"frozen": True},
        provenance={"template_version": "v1-2026-11"},
    )


def _failed_document(agreement):
    document = _pending_document(agreement)
    document.status = GeneratedAgreementDocument.Status.FAILED
    document.error_code = GeneratedAgreementDocument.ErrorCode.RENDER_FAILED
    document.save(update_fields=["status", "error_code", "updated_at"])
    return document


def _ready_document(agreement, data=PDF):
    document = GeneratedAgreementDocument.objects.create(
        agreement=agreement,
        status=GeneratedAgreementDocument.Status.READY,
        template_version="v1-2026-11",
        signing_path=agreement.signing_path,
        snapshot={},
        provenance={"template_version": "v1-2026-11"},
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        ready_at=timezone.now(),
    )
    document.file.save("ready.pdf", ContentFile(data), save=True)
    document.refresh_from_db()
    return document


def _ready_document_missing_bytes(agreement):
    return GeneratedAgreementDocument.objects.create(
        agreement=agreement,
        status=GeneratedAgreementDocument.Status.READY,
        template_version="v1-2026-11",
        signing_path=agreement.signing_path,
        snapshot={},
        provenance={"template_version": "v1-2026-11"},
        file="agreements/generated/missing.pdf",
        size_bytes=len(PDF),
        sha256=hashlib.sha256(PDF).hexdigest(),
        ready_at=timezone.now(),
    )


def _ready_document_corrupt_bytes(agreement):
    data = b"NOT-A-PDF"
    document = GeneratedAgreementDocument.objects.create(
        agreement=agreement,
        status=GeneratedAgreementDocument.Status.READY,
        template_version="v1-2026-11",
        signing_path=agreement.signing_path,
        snapshot={},
        provenance={"template_version": "v1-2026-11"},
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        ready_at=timezone.now(),
    )
    document.file.save("corrupt.pdf", ContentFile(data), save=True)
    document.refresh_from_db()
    return document


def _make_document_case(agreement, case):
    if case == "missing_row":
        return None
    if case == "pending":
        return _pending_document(agreement)
    if case == "failed":
        return _failed_document(agreement)
    if case == "missing_bytes":
        return _ready_document_missing_bytes(agreement)
    if case == "corrupt_bytes":
        return _ready_document_corrupt_bytes(agreement)
    raise AssertionError(case)


def _upload_signed_pdf(agreement, actor):
    upload_signed_artifact(
        agreement,
        SimpleUploadedFile(
            "signed.pdf", b"%PDF-1.7\nsigned artifact\n", content_type="application/pdf"
        ),
        actor,
    )
    agreement.refresh_from_db()
    return agreement


def _snapshot(agreement):
    agreement.refresh_from_db()
    values = (
        Agreement.objects.filter(pk=agreement.pk)
        .values(*_TRANSITION_FIELDS)
        .get()
    )
    return {
        "agreement": values,
        "mail": len(mail.outbox),
        "audit": AuditEvent.objects.count(),
        "billing": BillingRecord.objects.count(),
    }


def _count_agreement_updates(queries):
    return sum(
        1
        for sql in queries
        if sql["sql"].lstrip().upper().startswith("UPDATE")
        and "agreements_agreement" in sql["sql"]
    )


def _legacy_agreement(member, signing_path, *, state=Agreement.State.GENERATED, plan=None):
    return Agreement.objects.create(
        member=member,
        state=state,
        signing_path=signing_path,
        document_backend=Agreement.DocumentBackend.DOCUSEAL,
        generated_at=timezone.now(),
        billing_plan=plan,
        first_billing_month="2026-09" if plan is not None else "",
    )


# ---------------------------------------------------------------------------
# A ready, readable PDF is required before handover and signing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["missing_row", "pending", "failed", "missing_bytes", "corrupt_bytes"])
@pytest.mark.parametrize("transition", ["sent", "signed"])
def test_local_transition_requires_a_readable_ready_pdf(
    local_agreement, actor, case, transition
):
    if transition == "signed":
        # A real upload proves the missing/blocked artifact is the ready PDF,
        # not the signed-artifact precondition.
        _upload_signed_pdf(local_agreement, actor)
    _make_document_case(local_agreement, case)
    before = _snapshot(local_agreement)

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue:
        with pytest.raises(ValueError):
            if transition == "sent":
                mark_agreement_sent(local_agreement, actor)
            else:
                mark_agreement_signed(local_agreement, actor)

    enqueue.assert_not_called()
    assert _snapshot(local_agreement) == before


@pytest.mark.parametrize(
    "signing_path", [Agreement.SigningPath.PAPER, Agreement.SigningPath.ELECTRONIC]
)
def test_local_handover_succeeds_with_a_ready_pdf(
    local_agreement, actor, signing_path
):
    _use_signing_path(local_agreement, signing_path)
    _ready_document(local_agreement)
    mail.outbox.clear()

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue:
        mark_agreement_sent(local_agreement, actor)

    enqueue.assert_not_called()
    local_agreement.refresh_from_db()
    assert local_agreement.state == Agreement.State.SENT
    assert local_agreement.sent_at is not None
    assert AuditEvent.objects.filter(
        action=str(AuditEvent.Action.AGREEMENT_SENT)
    ).exists()
    assert len(mail.outbox) == 1


# ---------------------------------------------------------------------------
# A real signed upload is required before explicit local confirmation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signing_path", [Agreement.SigningPath.PAPER, Agreement.SigningPath.ELECTRONIC]
)
def test_local_signing_confirmation_requires_a_real_signed_upload(
    local_agreement, actor, signing_path
):
    _use_signing_path(local_agreement, signing_path)
    _ready_document(local_agreement)
    mail.outbox.clear()
    before = _snapshot(local_agreement)

    with pytest.raises(ValueError):
        mark_agreement_signed(local_agreement, actor)

    assert _snapshot(local_agreement) == before


@pytest.mark.parametrize(
    "signing_path", [Agreement.SigningPath.PAPER, Agreement.SigningPath.ELECTRONIC]
)
def test_local_signing_confirmation_succeeds_after_real_upload(
    local_agreement, actor, signing_path
):
    _use_signing_path(local_agreement, signing_path)
    _ready_document(local_agreement)
    _upload_signed_pdf(local_agreement, actor)
    mail.outbox.clear()
    billing_before = BillingRecord.objects.count()

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue:
        mark_agreement_signed(local_agreement, actor)

    enqueue.assert_not_called()
    local_agreement.refresh_from_db()
    assert local_agreement.state == Agreement.State.SIGNED
    assert local_agreement.signed_at is not None
    assert local_agreement.signed_artifact.name
    assert AuditEvent.objects.filter(
        action=str(AuditEvent.Action.AGREEMENT_SIGNED)
    ).exists()
    assert BillingRecord.objects.count() == billing_before + 1
    assert len(mail.outbox) == 1


def test_local_upload_alone_does_not_sign_or_create_billing(local_agreement, actor):
    _ready_document(local_agreement)
    mail.outbox.clear()
    billing_before = BillingRecord.objects.count()

    _upload_signed_pdf(local_agreement, actor)

    local_agreement.refresh_from_db()
    assert local_agreement.state == Agreement.State.GENERATED
    assert local_agreement.signed_at is None
    assert BillingRecord.objects.count() == billing_before
    assert mail.outbox == []


def test_local_ready_signing_still_honours_plan_and_month_guards(
    local_agreement, actor
):
    _ready_document(local_agreement)
    _upload_signed_pdf(local_agreement, actor)
    local_agreement.billing_plan = None
    local_agreement.first_billing_month = ""
    local_agreement.save(update_fields=["billing_plan", "first_billing_month"])
    mail.outbox.clear()
    before = _snapshot(local_agreement)

    with pytest.raises(ValueError):
        mark_agreement_signed(local_agreement, actor)

    assert _snapshot(local_agreement) == before


# ---------------------------------------------------------------------------
# Frozen signing path: service setter and application admin save_model
# ---------------------------------------------------------------------------


def test_local_frozen_path_setter_refuses_and_persists_nothing(
    local_agreement, actor
):
    _pending_document(local_agreement)
    application = local_agreement.member.source_application
    other = Agreement.SigningPath.ELECTRONIC
    assert local_agreement.signing_path == Agreement.SigningPath.PAPER

    with pytest.raises(ValueError):
        set_signing_path(local_agreement, other, actor)

    local_agreement.refresh_from_db()
    application.refresh_from_db()
    assert local_agreement.signing_path == Agreement.SigningPath.PAPER
    assert application.preferred_agreement_signing == Agreement.SigningPath.PAPER


def test_local_frozen_path_setter_same_value_is_a_noop(local_agreement, actor):
    _pending_document(local_agreement)
    with CaptureQueriesContext(connection) as queries:
        result = set_signing_path(
            local_agreement, Agreement.SigningPath.PAPER, actor
        )

    assert result.pk == local_agreement.pk
    assert _count_agreement_updates(queries) == 0


def test_local_frozen_path_admin_save_model_rolls_back_both_sides(
    local_agreement, actor
):
    from django.contrib.admin import AdminSite

    from apps.registrations.admin import RegistrationApplicationAdmin

    _pending_document(local_agreement)
    application = local_agreement.member.source_application
    request = RequestFactory().post("/")
    request.user = actor

    application.preferred_agreement_signing = Agreement.SigningPath.ELECTRONIC
    with pytest.raises(ValueError):
        RegistrationApplicationAdmin(
            RegistrationApplication, AdminSite()
        ).save_model(request, application, form=None, change=True)

    application.refresh_from_db()
    local_agreement.refresh_from_db()
    assert application.preferred_agreement_signing == Agreement.SigningPath.PAPER
    assert local_agreement.signing_path == Agreement.SigningPath.PAPER


def test_local_frozen_path_admin_save_model_same_value_is_a_noop(
    local_agreement, actor
):
    from django.contrib.admin import AdminSite

    from apps.registrations.admin import RegistrationApplicationAdmin

    _pending_document(local_agreement)
    application = local_agreement.member.source_application
    request = RequestFactory().post("/")
    request.user = actor

    with CaptureQueriesContext(connection) as queries:
        RegistrationApplicationAdmin(
            RegistrationApplication, AdminSite()
        ).save_model(request, application, form=None, change=True)

    local_agreement.refresh_from_db()
    assert _count_agreement_updates(queries) == 0
    assert local_agreement.signing_path == Agreement.SigningPath.PAPER


# ---------------------------------------------------------------------------
# Notices: plain club-owned text, no provider link/session/attachment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signing_path", [Agreement.SigningPath.PAPER, Agreement.SigningPath.ELECTRONIC]
)
def test_local_handover_notice_is_plain_club_owned(
    local_agreement, actor, signing_path
):
    _use_signing_path(local_agreement, signing_path)
    _ready_document(local_agreement)
    mail.outbox.clear()

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue:
        mark_agreement_sent(local_agreement, actor)

    enqueue.assert_not_called()
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "Jūsu līgums ir nosūtīts parakstīšanai"
    assert message.content_subtype == "plain"
    assert message.attachments == []
    assert getattr(message, "alternatives", []) == []
    assert "FK Cēsis" in message.body
    assert "/portal/" in message.body
    for fragment in _FORBIDDEN_NOTICE_FRAGMENTS:
        assert fragment not in message.body


@pytest.mark.parametrize(
    "signing_path", [Agreement.SigningPath.PAPER, Agreement.SigningPath.ELECTRONIC]
)
def test_local_signed_notice_is_plain_club_owned(
    local_agreement, actor, signing_path
):
    _use_signing_path(local_agreement, signing_path)
    _ready_document(local_agreement)
    _upload_signed_pdf(local_agreement, actor)
    mail.outbox.clear()

    mark_agreement_signed(local_agreement, actor)

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == "Jūsu līgums ir parakstīts"
    assert message.content_subtype == "plain"
    assert message.attachments == []
    assert getattr(message, "alternatives", []) == []
    assert "FK Cēsis" in message.body
    assert "/portal/" in message.body
    for fragment in _FORBIDDEN_NOTICE_FRAGMENTS:
        assert fragment not in message.body


def test_legacy_electronic_handover_still_suppresses_email(
    agreement_member, actor
):
    agreement = _legacy_agreement(
        agreement_member, Agreement.SigningPath.ELECTRONIC
    )
    mail.outbox.clear()

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ):
        mark_agreement_sent(agreement, actor)

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SENT
    assert mail.outbox == []


def test_legacy_paper_handover_still_sends_email(agreement_member, actor):
    agreement = _legacy_agreement(agreement_member, Agreement.SigningPath.PAPER)
    mail.outbox.clear()

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ):
        mark_agreement_sent(agreement, actor)

    assert len(mail.outbox) == 1


def test_legacy_electronic_signed_still_suppresses_email(
    agreement_member, actor, default_plan
):
    agreement = _legacy_agreement(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
        plan=default_plan,
    )
    mail.outbox.clear()

    mark_agreement_signed(agreement, actor)

    assert mail.outbox == []


def test_local_electronic_missing_email_does_not_fall_back_to_paper(
    local_agreement, actor
):
    _use_signing_path(local_agreement, Agreement.SigningPath.ELECTRONIC)
    _ready_document(local_agreement)
    account = local_agreement.member.guardian.parent_account
    account.email = ""
    account.save(update_fields=["email", "updated_at"])
    mail.outbox.clear()
    before = _snapshot(local_agreement)

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue:
        with pytest.raises(ValueError):
            mark_agreement_sent(local_agreement, actor)

    enqueue.assert_not_called()
    local_agreement.refresh_from_db()
    assert local_agreement.signing_path == Agreement.SigningPath.ELECTRONIC
    assert _snapshot(local_agreement) == before


# ---------------------------------------------------------------------------
# Local rows never enqueue or call DocuSeal
# ---------------------------------------------------------------------------


def test_local_handover_never_enqueues_or_calls_provider(
    local_agreement, actor
):
    _ready_document(local_agreement)
    mail.outbox.clear()

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue, patch(
        "apps.integrations.agreement_platform.create_submission",
        side_effect=AssertionError("provider create must not run"),
    ), patch(
        "apps.integrations.agreement_platform.sync_submission",
        side_effect=AssertionError("provider sync must not run"),
    ), patch(
        "apps.integrations.agreement_platform.archive_submission",
        side_effect=AssertionError("provider archive must not run"),
    ):
        mark_agreement_sent(local_agreement, actor)

    enqueue.assert_not_called()


def test_local_provider_jobs_are_noops(local_agreement):
    from apps.integrations import tasks

    local_agreement.external_id = "local-row-must-not-sync"
    local_agreement.external_state = "pending"
    local_agreement.save(update_fields=["external_id", "external_state"])
    before = _snapshot(local_agreement)

    with patch(
        "apps.integrations.agreement_platform.create_submission",
        side_effect=AssertionError("provider create must not run"),
    ), patch(
        "apps.integrations.agreement_platform.sync_submission",
        side_effect=AssertionError("provider sync must not run"),
    ), patch("apps.integrations.tasks.async_task") as enqueue:
        tasks.create_agreement_submission(local_agreement.id)
        tasks.sync_agreement_submission(local_agreement.id)
        tasks.enqueue_create_agreement_submission(local_agreement.id)

    enqueue.assert_not_called()
    assert _snapshot(local_agreement) == before


# ---------------------------------------------------------------------------
# Review fixes: frozen path consistency, lock order and Latvian error copy
# ---------------------------------------------------------------------------


def _set_pg_session_timeouts():
    """Bound real concurrent DB work so a broken lock fails fast, not hangs."""
    from django.db import connection

    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = 20000")
        cursor.execute("SET lock_timeout = 10000")
        cursor.execute("SET idle_in_transaction_session_timeout = 20000")


def test_local_handover_rejects_frozen_path_mismatch(local_agreement, actor):
    _ready_document(local_agreement)  # frozen with PAPER
    local_agreement.signing_path = Agreement.SigningPath.ELECTRONIC
    local_agreement.save(update_fields=["signing_path"])
    before = _snapshot(local_agreement)

    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as enqueue:
        with pytest.raises(ValueError):
            mark_agreement_sent(local_agreement, actor)

    enqueue.assert_not_called()
    assert _snapshot(local_agreement) == before


def test_local_signing_rejects_frozen_path_mismatch(local_agreement, actor):
    _ready_document(local_agreement)  # frozen with PAPER
    _upload_signed_pdf(local_agreement, actor)
    local_agreement.signing_path = Agreement.SigningPath.ELECTRONIC
    local_agreement.save(update_fields=["signing_path"])
    before = _snapshot(local_agreement)

    with pytest.raises(ValueError):
        mark_agreement_signed(local_agreement, actor)

    assert _snapshot(local_agreement) == before


def test_local_void_with_stray_external_id_never_archives_provider(
    local_agreement, actor
):
    local_agreement.external_id = "stray-local-id"
    local_agreement.external_state = "pending"
    local_agreement.save(update_fields=["external_id", "external_state"])

    with patch(
        "apps.integrations.tasks.enqueue_archive_agreement_submission"
    ) as enqueue, patch(
        "apps.integrations.agreement_platform.archive_submission",
        side_effect=AssertionError("provider archive must not run"),
    ):
        void_agreement(local_agreement, actor, "pārtraukts")

    enqueue.assert_not_called()
    local_agreement.refresh_from_db()
    assert local_agreement.state == Agreement.State.VOID


def test_local_sync_enqueue_is_a_noop(local_agreement):
    from apps.integrations import tasks

    with patch("apps.integrations.tasks.async_task") as enqueue:
        tasks.enqueue_sync_agreement_submission(local_agreement.id)

    enqueue.assert_not_called()


@pytest.mark.admin_view
def test_admin_set_signing_path_action_reports_frozen_without_500(
    local_agreement, staff_client, actor
):
    _pending_document(local_agreement)
    application = local_agreement.member.source_application
    url = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application.id],
    )

    response = staff_client.post(
        url,
        {"action": "set_signing_path", "signing_path": Agreement.SigningPath.ELECTRONIC},
    )

    assert response.status_code == 302
    local_agreement.refresh_from_db()
    application.refresh_from_db()
    assert local_agreement.signing_path == Agreement.SigningPath.PAPER
    assert application.preferred_agreement_signing == Agreement.SigningPath.PAPER


def test_admin_change_form_rejects_frozen_path_change(local_agreement):
    from apps.registrations.admin import RegistrationApplicationAdminForm

    _pending_document(local_agreement)
    form = RegistrationApplicationAdminForm(
        data={
            "preferred_agreement_signing": Agreement.SigningPath.ELECTRONIC,
        },
        instance=local_agreement.member.source_application,
    )

    assert not form.is_valid()
    assert "preferred_agreement_signing" in form.errors


@pytest.mark.admin_view
def test_admin_changeform_race_fallback_shows_message_not_500(
    local_agreement, staff_client, actor, monkeypatch
):
    from django.contrib.admin import AdminSite

    from apps.registrations.admin import RegistrationApplicationAdmin

    application = local_agreement.member.source_application
    url = reverse(
        "admin:registrations_registrationapplication_change",
        args=[application.id],
    )
    request = RequestFactory().get("/")
    request.user = actor
    admin_instance = RegistrationApplicationAdmin(
        RegistrationApplication, AdminSite()
    )
    form_class = admin_instance.get_form(request, application)
    form = form_class(instance=application)
    data = {}
    for name in form.fields:
        value = form[name].value()
        if value is None:
            data[name] = ""
        else:
            data[name] = value

    def refuse(*_args, **_kwargs):
        raise ValueError("signing path is frozen")

    monkeypatch.setattr(
        RegistrationApplicationAdmin, "save_model", refuse
    )

    response = staff_client.post(url, data)

    assert response.status_code == 302
    application.refresh_from_db()
    assert (
        application.preferred_agreement_signing
        == Agreement.SigningPath.PAPER
    )


def test_local_lifecycle_errors_map_to_latvian_copy():
    from apps.agreements.messages import get_local_lifecycle_message

    for code in (
        "document_not_ready",
        "document_unavailable",
        "document_integrity",
        "signed artifact required",
        "signing path is frozen",
        "signing path mismatch",
        "docuseal creation disabled",
        "guardian email required for electronic agreement",
    ):
        message = get_local_lifecycle_message(code)
        assert message
        assert message != code

    assert get_local_lifecycle_message("not-a-real-code") is None


@pytest.mark.django_db(transaction=True)
def test_setter_waits_for_generation_lock_then_refuses(
    local_agreement, actor, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time

    from django.db import close_old_connections, connection
    from django.test import RequestFactory  # noqa: F401

    from apps.agreements import document_generation

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")

    locked = Event()
    release = Event()
    setter_started = Event()
    outcome: dict[str, str] = {}
    original = document_generation._frozen_snapshot

    def blocked_snapshot(agreement):
        locked.set()
        if not release.wait(10):
            raise RuntimeError("freeze release timeout")
        return original(agreement)

    monkeypatch.setattr(document_generation, "_frozen_snapshot", blocked_snapshot)

    def freeze_worker():
        close_old_connections()
        try:
            _set_pg_session_timeouts()
            agreement = Agreement.objects.get(pk=local_agreement.pk)
            document_generation.request_document_generation(agreement, actor=None)
        finally:
            connection.close()

    def setter_worker():
        close_old_connections()
        setter_started.set()
        try:
            _set_pg_session_timeouts()
            agreement = Agreement.objects.get(pk=local_agreement.pk)
            try:
                set_signing_path(
                    agreement, Agreement.SigningPath.ELECTRONIC, actor
                )
            except ValueError as exc:
                outcome["error"] = str(exc)
        finally:
            connection.close()

    with patch(
        "apps.agreements.document_generation.enqueue_document_generation"
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            freeze = pool.submit(freeze_worker)
            assert locked.wait(10)
            setter = pool.submit(setter_worker)
            assert setter_started.wait(10)
            time.sleep(0.3)
            assert not setter.done(), "setter must wait for the agreement row lock"
            release.set()
            freeze.result(timeout=30)
            setter.result(timeout=30)

    agreement = Agreement.objects.get(pk=local_agreement.pk)
    document = GeneratedAgreementDocument.objects.get(agreement=agreement)
    assert outcome.get("error") == "signing path is frozen"
    assert agreement.signing_path == Agreement.SigningPath.PAPER
    assert document.signing_path == agreement.signing_path


@pytest.mark.django_db(transaction=True)
def test_admin_save_model_waits_for_generation_lock_then_rolls_back(
    local_agreement, actor, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import time

    from django.contrib.admin import AdminSite
    from django.db import close_old_connections, connection

    from apps.agreements import document_generation
    from apps.registrations.admin import RegistrationApplicationAdmin

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")

    locked = Event()
    release = Event()
    save_started = Event()
    outcome: dict[str, str] = {}
    original = document_generation._frozen_snapshot

    def blocked_snapshot(agreement):
        locked.set()
        if not release.wait(10):
            raise RuntimeError("freeze release timeout")
        return original(agreement)

    monkeypatch.setattr(document_generation, "_frozen_snapshot", blocked_snapshot)

    def freeze_worker():
        close_old_connections()
        try:
            _set_pg_session_timeouts()
            agreement = Agreement.objects.get(pk=local_agreement.pk)
            document_generation.request_document_generation(agreement, actor=None)
        finally:
            connection.close()

    def save_worker():
        close_old_connections()
        save_started.set()
        try:
            _set_pg_session_timeouts()
            application = RegistrationApplication.objects.get(
                pk=application_id
            )
            application.preferred_agreement_signing = (
                Agreement.SigningPath.ELECTRONIC
            )
            request = RequestFactory().post("/")
            request.user = actor
            try:
                RegistrationApplicationAdmin(
                    RegistrationApplication, AdminSite()
                ).save_model(request, application, form=None, change=True)
            except ValueError as exc:
                outcome["error"] = str(exc)
        finally:
            connection.close()

    application_id = local_agreement.member.source_application.pk
    with patch(
        "apps.agreements.document_generation.enqueue_document_generation"
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            freeze = pool.submit(freeze_worker)
            assert locked.wait(10)
            save = pool.submit(save_worker)
            assert save_started.wait(10)
            time.sleep(0.3)
            assert not save.done(), "admin save must wait for the agreement row lock"
            release.set()
            freeze.result(timeout=30)
            save.result(timeout=30)

    agreement = Agreement.objects.get(pk=local_agreement.pk)
    application = RegistrationApplication.objects.get(pk=application_id)
    document = GeneratedAgreementDocument.objects.get(agreement=agreement)
    assert outcome.get("error") == "signing path is frozen"
    assert application.preferred_agreement_signing == Agreement.SigningPath.PAPER
    assert agreement.signing_path == Agreement.SigningPath.PAPER
    assert document.signing_path == agreement.signing_path
