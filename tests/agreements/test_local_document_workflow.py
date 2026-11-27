"""Task 4 red-phase contract: staff generation and document routes.

This file pins the staff-facing local-agreement document workflow:

* the existing review-action endpoint gains ``generate_pdf`` / ``retry_pdf``;
* registration admin, Agreement admin, family hub and Admin Hub surface the
  local document status, generation/retry controls and ready-file download;
* every existing document route serves a ready local PDF (including historical
  and stray-external-id rows) through private/no-store bytes, never a provider
  or an on-demand render;
* missing/corrupt local bytes fail visibly without provider calls;
* legacy rows keep the existing DocuSeal proxy;
* unsigned parent access is denied;
* access is audited with redacted metadata.

Everything is stubbed: no provider, mail or real renderer is reached.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile
from django.http import Http404
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement, GeneratedAgreementDocument
from apps.core.models import AuditEvent
from apps.members.models import Member
from apps.registrations.models import RegistrationApplication
from tests.support import make_guardian

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]

PDF = b"%PDF-1.7\nlocal agreement workflow fixture\n" + b"x" * 64
PROVIDER_PDF = b"%PDF-1.7\nprovider fixture\n"
PII_EMAIL = "local-workflow-pii@example.test"
PII_PHONE = "+37129999998"
PII_ADDRESS = "Slepena darbnīcas adrese 77"

_LOCAL_SURFACES = ("registration", "agreement", "family")
_SURFACE_IDS = {
    "registration": "registration-admin",
    "agreement": "agreement-admin",
    "family": "family-hub",
}
# Local generation is only requestable while the agreement is still an
# unsigned handover candidate (generated/sent). These states are terminal for
# the local-PDF workflow and must not offer generate/retry.
_INELIGIBLE_LOCAL_STATES = ("signed", "void", "superseded", "discontinued")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_private_storage(settings, tmp_path):
    settings.PRIVATE_DOCUMENTS_ROOT = tmp_path


@pytest.fixture
def full_staff(db):
    return User.objects.create_superuser(
        username="local-doc-admin", email="admin@example.test", password="pw"
    )


@pytest.fixture
def plain_staff(db):
    return User.objects.create_user(
        username="local-doc-plain-staff", is_staff=True, password="pw"
    )


@pytest.fixture
def scoped_view_staff(db):
    """Staff with view-only application permission — no mutation capability."""
    user = User.objects.create_user(
        username="local-doc-view-staff", is_staff=True, password="pw"
    )
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="registrations",
            codename="view_registrationapplication",
        ),
        Permission.objects.get(
            content_type__app_label="members", codename="view_guardian"
        ),
        Permission.objects.get(
            content_type__app_label="agreements", codename="view_agreement"
        ),
    )
    return user


@pytest.fixture
def local_context(agreement_guardian, agreement_member):
    application = RegistrationApplication.objects.create(
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
    agreement = Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        document_backend=Agreement.DocumentBackend.LOCAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-991",
    )
    return SimpleNamespace(
        guardian=agreement_guardian,
        member=agreement_member,
        application=application,
        agreement=agreement,
    )


@pytest.fixture
def other_context(db):
    guardian = make_guardian(
        full_name="Cita Ģimene",
        personal_id="222222-22222",
        email="other-local@example.test",
        phone="+37120000001",
        address="Cita iela 2, Cēsis",
    )
    member = Member.objects.create(
        full_name="Cits Bērns",
        personal_id="151210-33333",
        birth_date=timezone.datetime(2015, 12, 10).date(),
        guardian=guardian,
    )
    application = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        parent_account=guardian.parent_account,
        guardian=guardian,
        approved_member=member,
        member_full_name=member.full_name,
        member_personal_id=member.personal_id,
        member_birth_date=member.birth_date,
        member_actual_address="Cita bērnu iela 3, Cēsis",
    )
    agreement = Agreement.objects.create(
        member=member,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        document_backend=Agreement.DocumentBackend.LOCAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-992",
    )
    return SimpleNamespace(
        guardian=guardian,
        member=member,
        application=application,
        agreement=agreement,
    )


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _parent_client(account):
    from apps.accounts.services import issue_magic_link

    client = Client()
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")
    return client


def _reg_change_url(ctx):
    return reverse(
        "admin:registrations_registrationapplication_change",
        args=[ctx.application.pk],
    )


def _reg_action_url(ctx):
    return reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[ctx.application.pk],
    )


def _agreement_change_url(agreement):
    return reverse("admin:agreements_agreement_change", args=[agreement.pk])


def _family_hub_url(ctx):
    return reverse("admin:members_guardian_family_hub", args=[ctx.guardian.pk])


def _family_action_url(ctx):
    return reverse(
        "admin:members_guardian_family_hub_action", args=[ctx.guardian.pk]
    )


def _hub_agreement_url(ctx):
    return reverse("admin_hub:agreement", args=[ctx.application.pk])


def _document_url(surface, ctx, agreement):
    if surface == "registration":
        return reverse(
            "admin:registrations_registrationapplication_docuseal_document",
            args=[ctx.application.pk, agreement.pk],
        )
    if surface == "agreement":
        return reverse(
            "admin:agreements_agreement_docuseal_document", args=[agreement.pk]
        )
    if surface == "family":
        return reverse(
            "admin:members_guardian_docuseal_document",
            args=[ctx.guardian.pk, agreement.pk],
        )
    raise AssertionError(surface)


def _ready_document(agreement, data=PDF, *, snapshot=None):
    document = GeneratedAgreementDocument.objects.create(
        agreement=agreement,
        status=GeneratedAgreementDocument.Status.READY,
        template_version="v1-2026-11",
        signing_path=agreement.signing_path,
        snapshot=snapshot or {},
        provenance={"template_version": "v1-2026-11"},
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        ready_at=timezone.now(),
    )
    document.file.save(f"ready-{agreement.pk}.pdf", ContentFile(data), save=True)
    document.refresh_from_db()
    return document


def _pending_document(agreement):
    return GeneratedAgreementDocument.objects.create(
        agreement=agreement,
        status=GeneratedAgreementDocument.Status.PENDING,
        template_version="v1-2026-11",
        signing_path=agreement.signing_path,
        snapshot={"fields": {"child_name": "Frozen Child"}},
        provenance={"template_version": "v1-2026-11"},
    )


def _failed_document(agreement):
    document = _pending_document(agreement)
    document.status = GeneratedAgreementDocument.Status.FAILED
    document.error_code = GeneratedAgreementDocument.ErrorCode.RENDER_FAILED
    document.save(update_fields=["status", "error_code", "updated_at"])
    return document


def _stale_pending_document(agreement):
    """Pending past the worker-timeout reclaim window (service retryable)."""
    document = _pending_document(agreement)
    GeneratedAgreementDocument.objects.filter(pk=document.pk).update(
        updated_at=timezone.now() - timedelta(minutes=6)
    )
    document.refresh_from_db()
    return document


def _missing_bytes_document(agreement):
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


def _corrupt_bytes_document(agreement):
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
    document.file.save(f"corrupt-{agreement.pk}.pdf", ContentFile(data), save=True)
    document.refresh_from_db()
    return document


def _historical_local_agreement(ctx, *, ready=True):
    agreement = Agreement.objects.create(
        member=ctx.member,
        is_current=False,
        state=Agreement.State.SIGNED,
        signing_path=Agreement.SigningPath.PAPER,
        document_backend=Agreement.DocumentBackend.LOCAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-993",
        signed_at=timezone.now(),
    )
    if ready:
        _ready_document(agreement)
    return agreement


def _legacy_agreement(ctx, *, is_current=False):
    return Agreement.objects.create(
        member=ctx.member,
        is_current=is_current,
        state=Agreement.State.SIGNED,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        document_backend=Agreement.DocumentBackend.DOCUSEAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-994",
        external_id="legacy-submission-1",
        external_state="completed",
    )


def _provider_stream():
    from apps.integrations import agreement_platform as ap

    return ap.DocumentStream(
        filename="provider.pdf",
        content_type="application/pdf",
        chunks=iter([PROVIDER_PDF]),
    )


def _body(response):
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


def _assert_local_stream(response, expected=PDF):
    assert response.status_code == 200
    assert _body(response) == expected
    assert response["Content-Type"].startswith("application/pdf")
    cache_control = response["Cache-Control"].lower()
    assert "private" in cache_control
    assert "no-store" in cache_control
    disposition = response["Content-Disposition"].lower()
    assert "filename" in disposition
    assert ".pdf" in disposition
    assert "fkc-2026-991" in disposition.replace("%2d", "-")
    assert "agreements/generated" not in disposition


def _assert_visible_local_failure(response):
    body = _body(response)
    assert not body.startswith(b"%PDF-")
    if response.status_code == 404:
        return
    assert response.status_code == 200, response.status_code
    text = body.decode("utf-8", "ignore")
    assert "Lokāl" in text, text[:600]


def _stray_local_id(agreement):
    agreement.external_id = "stray-local-provider-id"
    agreement.external_state = "failed"
    agreement.save(update_fields=["external_id", "external_state"])


# ---------------------------------------------------------------------------
# Review-action dispatch: generate_pdf / retry_pdf
# ---------------------------------------------------------------------------


def test_registration_admin_generate_pdf_creates_pending_document_and_queues(
    local_context, full_staff, django_capture_on_commit_callbacks
):
    queue = Mock()
    with patch(
        "apps.agreements.document_generation.enqueue_document_generation", queue
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _client(full_staff).post(
                _reg_action_url(local_context), {"action": "generate_pdf"}
            )

    assert response.status_code == 302
    document = GeneratedAgreementDocument.objects.get(
        agreement=local_context.agreement
    )
    assert document.status == GeneratedAgreementDocument.Status.PENDING
    assert document.snapshot
    assert document.template_version == "v1-2026-11"
    queue.assert_called_once_with(document.pk)
    local_context.agreement.refresh_from_db()
    assert local_context.agreement.state == Agreement.State.GENERATED
    assert local_context.agreement.sent_at is None
    assert local_context.agreement.signed_at is None


def test_registration_admin_retry_pdf_requeues_failed_document(
    local_context, full_staff, django_capture_on_commit_callbacks
):
    document = _failed_document(local_context.agreement)
    frozen = dict(document.snapshot)
    queue = Mock()
    with patch(
        "apps.agreements.document_generation.enqueue_document_generation", queue
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _client(full_staff).post(
                _reg_action_url(local_context), {"action": "retry_pdf"}
            )

    assert response.status_code == 302
    document.refresh_from_db()
    assert document.status == GeneratedAgreementDocument.Status.PENDING
    assert document.error_code == ""
    assert document.snapshot == frozen
    queue.assert_called_once_with(document.pk)


def test_registration_admin_generate_pdf_is_idempotent_for_ready_file(
    local_context, full_staff
):
    document = _ready_document(local_context.agreement)
    before = (document.pk, document.sha256, document.file.name)

    with patch(
        "apps.agreements.document_generation.enqueue_document_generation"
    ) as queue, patch(
        "apps.agreements.document_tasks.render_agreement_pdf"
    ) as render:
        response = _client(full_staff).post(
            _reg_action_url(local_context), {"action": "generate_pdf"}
        )

    assert response.status_code == 302
    queue.assert_not_called()
    render.assert_not_called()
    assert GeneratedAgreementDocument.objects.filter(
        agreement=local_context.agreement
    ).count() == 1
    document.refresh_from_db()
    assert (document.pk, document.sha256, document.file.name) == before
    assert document.file.read() == PDF


def test_registration_admin_generate_pdf_refuses_legacy_rows_without_side_effects(
    local_context, full_staff
):
    # Target the member's *current* agreement: move the local row out of the
    # current slot, then make the legacy DocuSeal row current. Posting
    # generate_pdf must resolve that legacy row and refuse it, not silently
    # operate on some other agreement.
    local_context.agreement.is_current = False
    local_context.agreement.save(update_fields=["is_current"])
    legacy = _legacy_agreement(local_context, is_current=True)
    assert (
        Agreement.objects.get(member=local_context.member, is_current=True).pk
        == legacy.pk
    )
    with patch(
        "apps.agreements.document_generation.enqueue_document_generation"
    ) as queue, patch(
        "apps.integrations.agreement_platform.create_submission"
    ) as provider:
        response = _client(full_staff).post(
            _reg_action_url(local_context), {"action": "generate_pdf"}
        )

    queue.assert_not_called()
    provider.assert_not_called()
    assert not GeneratedAgreementDocument.objects.filter(agreement=legacy).exists()
    assert not GeneratedAgreementDocument.objects.exists()
    assert response.status_code == 302


def test_generate_pdf_requires_csrf(local_context, full_staff):
    client = Client(enforce_csrf_checks=True)
    client.force_login(full_staff)

    response = client.post(
        _reg_action_url(local_context), {"action": "generate_pdf"}
    )

    assert response.status_code == 403
    assert not GeneratedAgreementDocument.objects.filter(
        agreement=local_context.agreement
    ).exists()


def test_scoped_view_only_staff_cannot_generate(
    local_context, scoped_view_staff
):
    response = _client(scoped_view_staff).post(
        _reg_action_url(local_context), {"action": "generate_pdf"}
    )

    assert response.status_code == 403
    assert not GeneratedAgreementDocument.objects.filter(
        agreement=local_context.agreement
    ).exists()


# ---------------------------------------------------------------------------
# Registration admin UI: status, generate/retry, ready download
# ---------------------------------------------------------------------------


def test_registration_admin_offers_generate_pdf_for_local_generated_row(
    local_context, full_staff
):
    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert 'value="generate_pdf"' in html
    assert "Sagatavot PDF" in html
    assert 'value="retry_pdf"' not in html


def test_registration_admin_shows_failed_status_and_retry_for_local_row(
    local_context, full_staff
):
    _failed_document(local_context.agreement)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert "Neizdevās" in html
    assert 'value="retry_pdf"' in html
    assert "Mēģināt vēlreiz" in html


def test_registration_admin_offers_retry_for_stale_pending_local_document(
    local_context, full_staff
):
    _stale_pending_document(local_context.agreement)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert 'value="retry_pdf"' in html
    assert "Mēģināt vēlreiz" in html
    assert 'value="generate_pdf"' not in html


def test_registration_admin_hides_retry_for_fresh_pending_local_document(
    local_context, full_staff
):
    _pending_document(local_context.agreement)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert 'value="retry_pdf"' not in html
    assert 'value="generate_pdf"' not in html


def test_registration_admin_lists_ready_local_document_for_download(
    local_context, full_staff
):
    _ready_document(local_context.agreement)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert _document_url("registration", local_context, local_context.agreement) in html
    assert "Lejupielādēt" in html
    assert "DocuSeal sūtījums vēl nav izveidots" not in html


def test_registration_admin_lists_historical_ready_local_document(
    local_context, full_staff
):
    historical = _historical_local_agreement(local_context)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert _document_url("registration", local_context, historical) in html


def test_registration_admin_hides_provider_sync_for_stray_local_id(
    local_context, full_staff
):
    _stray_local_id(local_context.agreement)
    _failed_document(local_context.agreement)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert "Pārbaudīt DocuSeal statusu" not in html
    assert 'value="sync_docuseal"' not in html
    assert _document_url("registration", local_context, local_context.agreement) in html


def test_registration_admin_sync_action_does_not_enqueue_for_local_stray_id(
    local_context, full_staff
):
    _stray_local_id(local_context.agreement)

    with patch(
        "apps.registrations.admin.enqueue_sync_agreement_submission"
    ) as queue:
        response = _client(full_staff).post(
            _reg_action_url(local_context), {"action": "sync_docuseal"}
        )

    queue.assert_not_called()
    assert response.status_code == 302


# ---------------------------------------------------------------------------
# Agreement admin: ready local document, historical rows, legacy proxy
# ---------------------------------------------------------------------------


def test_agreement_admin_renders_ready_local_document_without_external_id(
    local_context, full_staff
):
    _ready_document(local_context.agreement)

    html = _client(full_staff).get(
        _agreement_change_url(local_context.agreement)
    ).content.decode()

    url = _document_url("agreement", local_context, local_context.agreement)
    assert url in html
    assert f"{url}?disposition=inline" in html
    assert f"{url}?disposition=attachment" in html
    assert "Lejupielādēt ģenerēto līgumu" in html


def test_agreement_admin_renders_historical_ready_local_document(
    local_context, full_staff
):
    historical = _historical_local_agreement(local_context)

    html = _client(full_staff).get(
        _agreement_change_url(historical)
    ).content.decode()

    assert _document_url("agreement", local_context, historical) in html


# ---------------------------------------------------------------------------
# Family hub: status, actions, ready/historical download, stray-ID guard
# ---------------------------------------------------------------------------


def test_family_hub_offers_generate_pdf_for_local_generated_row(
    local_context, full_staff
):
    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert 'value="generate_pdf"' in html
    assert "Sagatavot PDF" in html


def test_family_hub_shows_failed_status_and_retry_for_local_row(
    local_context, full_staff
):
    _failed_document(local_context.agreement)

    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert "Neizdevās" in html
    assert 'value="retry_pdf"' in html
    assert "Mēģināt vēlreiz" in html


def test_family_hub_offers_retry_for_stale_pending_local_document(
    local_context, full_staff
):
    _stale_pending_document(local_context.agreement)

    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert 'value="retry_pdf"' in html
    assert "Mēģināt vēlreiz" in html
    assert 'value="generate_pdf"' not in html


def test_family_hub_hides_retry_for_fresh_pending_local_document(
    local_context, full_staff
):
    _pending_document(local_context.agreement)

    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert 'value="retry_pdf"' not in html
    assert 'value="generate_pdf"' not in html


def test_family_hub_lists_ready_and_historical_local_documents(
    local_context, full_staff
):
    _ready_document(local_context.agreement)
    historical = _historical_local_agreement(local_context)

    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert _document_url("family", local_context, local_context.agreement) in html
    assert _document_url("family", local_context, historical) in html
    assert "Lejupielādēt ģenerēto līgumu" in html


def test_family_hub_generate_pdf_action_creates_pending_and_queues(
    local_context, full_staff, django_capture_on_commit_callbacks
):
    queue = Mock()
    with patch(
        "apps.agreements.document_generation.enqueue_document_generation", queue
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _client(full_staff).post(
                _family_action_url(local_context),
                {
                    "action": "generate_pdf",
                    "agreement_id": local_context.agreement.pk,
                },
            )

    assert response.status_code == 302
    document = GeneratedAgreementDocument.objects.get(
        agreement=local_context.agreement
    )
    assert document.status == GeneratedAgreementDocument.Status.PENDING
    assert document.snapshot
    queue.assert_called_once_with(document.pk)


def test_family_hub_retry_pdf_action_requeues_failed_document(
    local_context, full_staff, django_capture_on_commit_callbacks
):
    document = _failed_document(local_context.agreement)
    queue = Mock()
    with patch(
        "apps.agreements.document_generation.enqueue_document_generation", queue
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = _client(full_staff).post(
                _family_action_url(local_context),
                {
                    "action": "retry_pdf",
                    "agreement_id": local_context.agreement.pk,
                },
            )

    assert response.status_code == 302
    document.refresh_from_db()
    assert document.status == GeneratedAgreementDocument.Status.PENDING
    queue.assert_called_once_with(document.pk)


def test_family_hub_hides_provider_sync_for_stray_local_id(
    local_context, full_staff
):
    _stray_local_id(local_context.agreement)
    _failed_document(local_context.agreement)

    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert "Pārbaudīt DocuSeal statusu" not in html
    assert 'value="sync_docuseal"' not in html


def test_family_hub_sync_action_does_not_enqueue_for_local_stray_id(
    local_context, full_staff
):
    _stray_local_id(local_context.agreement)

    with patch(
        "apps.members.admin.enqueue_sync_agreement_submission"
    ) as queue:
        response = _client(full_staff).post(
            _family_action_url(local_context),
            {
                "action": "sync_docuseal",
                "agreement_id": local_context.agreement.pk,
            },
        )

    queue.assert_not_called()
    assert response.status_code == 302


def test_family_hub_action_requires_csrf(local_context, full_staff):
    client = Client(enforce_csrf_checks=True)
    client.force_login(full_staff)

    response = client.post(
        _family_action_url(local_context),
        {
            "action": "generate_pdf",
            "agreement_id": local_context.agreement.pk,
        },
    )

    assert response.status_code == 403
    assert not GeneratedAgreementDocument.objects.filter(
        agreement=local_context.agreement
    ).exists()


# ---------------------------------------------------------------------------
# Admin Hub agreement page: status and ready download
# ---------------------------------------------------------------------------


def test_hub_agreement_offers_generate_pdf_for_local_generated_row(
    local_context, full_staff
):
    html = _client(full_staff).get(_hub_agreement_url(local_context)).content.decode()

    assert 'value="generate_pdf"' in html
    assert "Sagatavot PDF" in html
    assert _reg_action_url(local_context) in html


def test_hub_agreement_shows_failed_status_and_retry_for_local_row(
    local_context, full_staff
):
    _failed_document(local_context.agreement)

    html = _client(full_staff).get(_hub_agreement_url(local_context)).content.decode()

    assert "Neizdevās" in html
    assert 'value="retry_pdf"' in html
    assert "Mēģināt vēlreiz" in html


def test_hub_agreement_offers_retry_for_stale_pending_local_document(
    local_context, full_staff
):
    _stale_pending_document(local_context.agreement)

    html = _client(full_staff).get(_hub_agreement_url(local_context)).content.decode()

    assert 'value="retry_pdf"' in html
    assert "Mēģināt vēlreiz" in html
    assert 'value="generate_pdf"' not in html


def test_hub_agreement_hides_retry_for_fresh_pending_local_document(
    local_context, full_staff
):
    _pending_document(local_context.agreement)

    html = _client(full_staff).get(_hub_agreement_url(local_context)).content.decode()

    assert 'value="retry_pdf"' not in html
    assert 'value="generate_pdf"' not in html


def test_hub_agreement_download_points_at_ready_local_document(
    local_context, full_staff
):
    _ready_document(local_context.agreement)

    html = _client(full_staff).get(_hub_agreement_url(local_context)).content.decode()

    assert _document_url("registration", local_context, local_context.agreement) in html
    assert "DocuSeal sūtījums vēl nav izveidots" not in html


# ---------------------------------------------------------------------------
# No local PDF mutation controls outside the requestable lifecycle states
# ---------------------------------------------------------------------------


def _set_agreement_state(local_context, state):
    local_context.agreement.state = state
    local_context.agreement.save(update_fields=["state"])


@pytest.mark.parametrize("state", _INELIGIBLE_LOCAL_STATES)
def test_registration_admin_hides_local_pdf_controls_for_ineligible_state(
    state, local_context, full_staff
):
    _set_agreement_state(local_context, state)

    html = _client(full_staff).get(_reg_change_url(local_context)).content.decode()

    assert 'value="generate_pdf"' not in html
    assert 'value="retry_pdf"' not in html
    assert "Sagatavot PDF" not in html
    assert "Mēģināt vēlreiz" not in html


@pytest.mark.parametrize("state", _INELIGIBLE_LOCAL_STATES)
def test_family_hub_hides_local_pdf_controls_for_ineligible_state(
    state, local_context, full_staff
):
    _set_agreement_state(local_context, state)

    html = _client(full_staff).get(_family_hub_url(local_context)).content.decode()

    assert 'value="generate_pdf"' not in html
    assert 'value="retry_pdf"' not in html
    assert "Sagatavot PDF" not in html
    assert "Mēģināt vēlreiz" not in html


@pytest.mark.parametrize("state", _INELIGIBLE_LOCAL_STATES)
def test_hub_agreement_hides_local_pdf_controls_for_ineligible_state(
    state, local_context, full_staff
):
    _set_agreement_state(local_context, state)

    html = _client(full_staff).get(_hub_agreement_url(local_context)).content.decode()

    assert 'value="generate_pdf"' not in html
    assert 'value="retry_pdf"' not in html
    assert "Sagatavot PDF" not in html
    assert "Mēģināt vēlreiz" not in html


@pytest.mark.parametrize(
    ("surface", "url_builder"),
    [
        ("registration", _reg_change_url),
        ("family", _family_hub_url),
        ("hub", _hub_agreement_url),
    ],
    ids=["registration-admin", "family-hub", "admin-hub"],
)
def test_signed_agreement_hides_retry_for_failed_local_document(
    surface, url_builder, local_context, full_staff
):
    _set_agreement_state(local_context, "signed")
    _failed_document(local_context.agreement)

    html = _client(full_staff).get(url_builder(local_context)).content.decode()

    assert 'value="retry_pdf"' not in html
    assert "Mēģināt vēlreiz" not in html
    assert 'value="generate_pdf"' not in html


# ---------------------------------------------------------------------------
# Shared document routes: local bytes, historical rows, dispositions, headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_local_ready_document_streams_private_bytes_without_provider(
    surface, local_context, full_staff
):
    _ready_document(local_context.agreement)
    provider = Mock(return_value=_provider_stream())

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document", provider
    ):
        response = _client(full_staff).get(
            _document_url(surface, local_context, local_context.agreement)
            + "?disposition=attachment"
        )

    provider.assert_not_called()
    _assert_local_stream(response)
    assert "attachment" in response["Content-Disposition"].lower()


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_local_inline_disposition_streams_private_bytes(
    surface, local_context, full_staff
):
    _ready_document(local_context.agreement)

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document"
    ) as provider:
        response = _client(full_staff).get(
            _document_url(surface, local_context, local_context.agreement)
            + "?disposition=inline"
        )

    provider.assert_not_called()
    _assert_local_stream(response)
    assert "inline" in response["Content-Disposition"].lower()


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_local_inline_document_allows_sameorigin_framing(
    surface, local_context, full_staff
):
    _ready_document(local_context.agreement)

    response = _client(full_staff).get(
        _document_url(surface, local_context, local_context.agreement)
        + "?disposition=inline"
    )

    assert response.status_code == 200
    assert response["X-Frame-Options"] == "SAMEORIGIN"


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_local_attachment_document_keeps_deny_framing(
    surface, local_context, full_staff
):
    _ready_document(local_context.agreement)

    response = _client(full_staff).get(
        _document_url(surface, local_context, local_context.agreement)
        + "?disposition=attachment"
    )

    assert response.status_code == 200
    assert response["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_historical_ready_local_row_streams_private_bytes(
    surface, local_context, full_staff
):
    historical = _historical_local_agreement(local_context)

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document"
    ) as provider:
        response = _client(full_staff).get(
            _document_url(surface, local_context, historical)
            + "?disposition=attachment"
        )

    provider.assert_not_called()
    body = _body(response)
    assert response.status_code == 200
    assert body == PDF
    assert "no-store" in response["Cache-Control"].lower()


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_local_stray_external_id_never_reaches_provider(
    surface, local_context, full_staff
):
    _stray_local_id(local_context.agreement)
    _ready_document(local_context.agreement)
    provider = Mock(return_value=_provider_stream())

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document", provider
    ):
        response = _client(full_staff).get(
            _document_url(surface, local_context, local_context.agreement)
            + "?disposition=attachment"
        )

    provider.assert_not_called()
    _assert_local_stream(response)


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
@pytest.mark.parametrize("case", ["missing", "corrupt"])
def test_missing_or_corrupt_local_bytes_fail_visibly_without_provider_or_render(
    surface, case, local_context, full_staff
):
    _stray_local_id(local_context.agreement)
    if case == "missing":
        _missing_bytes_document(local_context.agreement)
    else:
        _corrupt_bytes_document(local_context.agreement)
    provider = Mock(return_value=_provider_stream())

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document", provider
    ), patch(
        "apps.agreements.document_generation.request_document_generation"
    ) as request_generation, patch(
        "apps.agreements.document_generation.retry_document_generation"
    ) as retry_generation, patch(
        "apps.agreements.document_tasks.render_agreement_pdf"
    ) as render:
        response = _client(full_staff).get(
            _document_url(surface, local_context, local_context.agreement),
            follow=True,
        )

    provider.assert_not_called()
    request_generation.assert_not_called()
    retry_generation.assert_not_called()
    render.assert_not_called()
    _assert_visible_local_failure(response)


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_local_document_route_rejects_invalid_disposition(
    surface, local_context, full_staff
):
    _ready_document(local_context.agreement)

    response = _client(full_staff).get(
        _document_url(surface, local_context, local_context.agreement)
        + "?disposition=unsafe"
    )

    assert response.status_code == 404


def test_shared_document_helper_routes_local_bytes_without_provider(
    local_context,
):
    from apps.agreements.document_proxy import build_agreement_document_response

    _ready_document(local_context.agreement)

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document"
    ) as provider:
        response = build_agreement_document_response(
            local_context.agreement, disposition="attachment"
        )

    provider.assert_not_called()
    _assert_local_stream(response)


@pytest.mark.parametrize("case", ["missing", "corrupt"])
def test_shared_document_helper_fails_closed_for_local_bad_bytes(
    case, local_context
):
    from apps.agreements.document_proxy import build_agreement_document_response

    _stray_local_id(local_context.agreement)
    if case == "missing":
        _missing_bytes_document(local_context.agreement)
    else:
        _corrupt_bytes_document(local_context.agreement)

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document"
    ) as provider, pytest.raises((Http404, ValueError)):
        build_agreement_document_response(
            local_context.agreement, disposition="attachment"
        )

    provider.assert_not_called()


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_legacy_row_still_uses_the_existing_provider_proxy(
    surface, local_context, full_staff
):
    legacy = _legacy_agreement(local_context)
    provider = Mock(return_value=_provider_stream())

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document", provider
    ):
        response = _client(full_staff).get(
            _document_url(surface, local_context, legacy)
            + "?disposition=attachment"
        )

    provider.assert_called_once_with("legacy-submission-1")
    assert response.status_code == 200
    assert _body(response) == PROVIDER_PDF


# ---------------------------------------------------------------------------
# Access audit and redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("disposition", "expected_action"),
    [
        ("inline", AuditEvent.Action.DOCUMENT_PREVIEWED),
        ("attachment", AuditEvent.Action.DOCUMENT_DOWNLOADED),
    ],
)
def test_local_document_audit_action_matches_disposition(
    disposition, expected_action, local_context, full_staff
):
    _ready_document(local_context.agreement)

    response = _client(full_staff).get(
        _document_url("registration", local_context, local_context.agreement)
        + f"?disposition={disposition}"
    )
    assert response.status_code == 200

    event = AuditEvent.objects.filter(
        target_type="agreement",
        target_id=str(local_context.agreement.pk),
    ).latest("created_at")
    assert event.action == expected_action
    assert event.metadata["disposition"] == disposition
    assert event.metadata["document_backend"] == "local"


def test_local_download_records_redacted_audit_event(local_context, full_staff):
    snapshot_secret = "FROZEN-SNAPSHOT-SENTINEL"
    document = _ready_document(
        local_context.agreement,
        snapshot={"fields": {"child_address": snapshot_secret}},
    )

    response = _client(full_staff).get(
        _document_url("registration", local_context, local_context.agreement)
        + "?disposition=attachment"
    )
    assert response.status_code == 200

    event = AuditEvent.objects.filter(
        action=AuditEvent.Action.DOCUMENT_DOWNLOADED,
        target_type="agreement",
        target_id=str(local_context.agreement.pk),
    ).latest("created_at")
    rendered = f"{event.metadata!r} {event.target_repr!r}"
    for forbidden in (
        snapshot_secret,
        document.file.name,
        "agreements/generated",
        local_context.member.personal_id,
        local_context.guardian.personal_id,
        PII_EMAIL,
        PII_PHONE,
    ):
        assert forbidden not in rendered


# ---------------------------------------------------------------------------
# Cross-application / cross-guardian ownership
# ---------------------------------------------------------------------------


def test_registration_document_route_rejects_foreign_agreement(
    local_context, other_context, full_staff
):
    _ready_document(other_context.agreement)

    response = _client(full_staff).get(
        _document_url("registration", local_context, other_context.agreement)
        + "?disposition=attachment"
    )

    assert response.status_code == 404


def test_family_hub_document_route_rejects_foreign_agreement(
    local_context, other_context, full_staff
):
    _ready_document(other_context.agreement)

    response = _client(full_staff).get(
        _document_url("family", local_context, other_context.agreement)
        + "?disposition=attachment"
    )

    assert response.status_code == 404


def test_family_hub_generate_action_rejects_foreign_agreement(
    local_context, other_context, full_staff
):
    response = _client(full_staff).post(
        _family_action_url(local_context),
        {
            "action": "generate_pdf",
            "agreement_id": other_context.agreement.pk,
        },
    )

    assert response.status_code == 404
    assert not GeneratedAgreementDocument.objects.filter(
        agreement=other_context.agreement
    ).exists()


# ---------------------------------------------------------------------------
# Authentication / permissions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_anonymous_document_request_is_denied(surface, local_context):
    _ready_document(local_context.agreement)

    response = Client().get(
        _document_url(surface, local_context, local_context.agreement)
    )

    assert response.status_code in (302, 403, 404)
    if response.status_code == 302:
        assert "/admin/login/" in response["Location"]
    assert not _body(response).startswith(b"%PDF-")


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_nonstaff_document_request_is_denied(surface, local_context):
    user = User.objects.create_user(username="not-staff-local", password="pw")
    _ready_document(local_context.agreement)

    response = _client(user).get(
        _document_url(surface, local_context, local_context.agreement)
    )

    assert response.status_code in (302, 403, 404)
    assert not _body(response).startswith(b"%PDF-")


def test_plain_staff_cannot_use_registration_document_route(
    local_context, plain_staff
):
    _ready_document(local_context.agreement)

    response = _client(plain_staff).get(
        _document_url("registration", local_context, local_context.agreement)
    )

    assert response.status_code == 403


def test_scoped_view_staff_cannot_use_family_hub_route(
    local_context, scoped_view_staff
):
    _ready_document(local_context.agreement)

    response = _client(scoped_view_staff).get(_family_hub_url(local_context))

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Unsigned parent access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", _LOCAL_SURFACES, ids=lambda s: _SURFACE_IDS[s])
def test_parent_cannot_read_unsigned_local_generated_document(surface, local_context):
    _ready_document(local_context.agreement)
    parent_client = _parent_client(local_context.guardian.parent_account)

    response = parent_client.get(
        _document_url(surface, local_context, local_context.agreement)
    )

    assert response.status_code in (302, 403, 404)
    assert not _body(response).startswith(b"%PDF-")


def test_parent_signed_artifact_route_never_serves_generated_pdf(local_context):
    _ready_document(local_context.agreement)
    parent_client = _parent_client(local_context.guardian.parent_account)

    response = parent_client.get(
        reverse(
            "registrations:parent-signed-artifact",
            args=[local_context.agreement.pk],
        )
    )

    assert response.status_code == 404
    assert not _body(response).startswith(b"%PDF-")


def test_parent_workspace_does_not_expose_unsigned_generated_document(
    local_context,
):
    _ready_document(local_context.agreement)
    parent_client = _parent_client(local_context.guardian.parent_account)

    response = parent_client.get(
        reverse(
            "registrations:application-workspace",
            args=[local_context.application.pk],
        )
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert _document_url(
        "registration", local_context, local_context.agreement
    ) not in html
