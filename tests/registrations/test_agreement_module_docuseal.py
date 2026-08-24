"""Līgums module DocuSeal UI: error surface, retry, sync, external link.

Ported to the admin change page + review-action endpoint (P7 C-i).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.agreements.services import get_current_agreement
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True, is_superuser=True)


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


def _docuseal_document_url(app_id, agreement_id):
    return reverse(
        "admin:registrations_registrationapplication_docuseal_document",
        args=[app_id, agreement_id],
    )


def _approved_agreement(submitted_application, reviewer, **fields):
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    for k, v in fields.items():
        setattr(agreement, k, v)
    if fields:
        agreement.save(update_fields=list(fields))
    return agreement


def test_failed_state_renders_latvian_error_and_retry(
    client, submitted_application, reviewer
):
    _approved_agreement(
        submitted_application,
        reviewer,
        external_state="failed",
        external_error_code="auth_failed",
    )
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "DocuSeal autentifikācija neizdevās" in html
    assert 'value="retry_docuseal"' in html


def test_external_url_no_longer_renders_open_link(
    client, submitted_application, reviewer
):
    """The old 'Atvērt DocuSeal ↗' external link must be gone — the DocuSeal
    document URL must never leak into rendered HTML."""
    _approved_agreement(
        submitted_application,
        reviewer,
        external_id="ds-1",
        external_url="https://sign.example/s/abc",
    )
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "Atvērt DocuSeal" not in html
    assert "https://sign.example" not in html
    assert "sign.example" not in html


def test_download_link_rendered_with_exact_label(
    client, submitted_application, reviewer
):
    """The change page must render a download link with the exact label
    'Lejupielādēt ģenerēto līgumu' pointing at the same-origin document
    endpoint."""
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "Lejupielādēt ģenerēto līgumu" in html
    url = _docuseal_document_url(submitted_application.id, agreement.id)
    assert url in html
    # The rendered download anchor must request the attachment disposition.
    assert f"{url}?disposition=attachment" in html


def test_download_link_hidden_without_external_id(
    client, submitted_application, reviewer
):
    """An approved agreement with no DocuSeal submission must not render the
    download link (and the old external link stays absent)."""
    _approved_agreement(submitted_application, reviewer)  # no external_id
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "Lejupielādēt ģenerēto līgumu" not in html
    assert "Atvērt DocuSeal" not in html


def test_no_leaked_multiline_django_comment_text(
    client, submitted_application, reviewer
):
    """Multi-line Django `{# #}` comments leak their literal body into the
    rendered page (Django `{# #}` is single-line only). The agreement module
    and the shared agreement-list partial must never leak their prose into
    the Registration admin HTML."""
    _approved_agreement(submitted_application, reviewer, external_id="ds-1")
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "Document list — every non-empty-external-id agreement" not in html
    assert "Shared app-neutral partial" not in html


def test_change_page_lists_download_links_for_history_agreements(
    client, submitted_application, reviewer
):
    """Every agreement for the member with a nonempty external_id must be
    listed (current + history), each with its own download link."""
    from django.utils import timezone

    from apps.agreements.models import Agreement

    current = _approved_agreement(
        submitted_application, reviewer, external_id="cur-1"
    )
    member = submitted_application.approved_member
    history = Agreement.objects.create(
        member=member,
        is_current=False,
        state=Agreement.State.VOID,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        generated_at=timezone.now(),
        external_id="hist-1",
    )

    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()

    assert _docuseal_document_url(submitted_application.id, current.id) in html
    assert _docuseal_document_url(submitted_application.id, history.id) in html


def test_docuseal_document_route_streams_pdf(
    settings, client, submitted_application, reviewer
):
    """GET the document route must stream the proxied PDF (stub yields
    %PDF- bytes), not redirect."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    client.force_login(reviewer)
    resp = client.get(
        _docuseal_document_url(submitted_application.id, agreement.id)
    )
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content).startswith(b"%PDF-")


def test_docuseal_document_route_rejects_foreign_agreement(
    settings, client, submitted_application, reviewer, other_parent_account
):
    """The route must 404 when the agreement does not belong to the
    application's approved member."""
    from apps.agreements.services import create_agreement_for_member
    from apps.members.models import Member
    from apps.members.services import resolve_guardian_for_account

    settings.AGREEMENT_PROVIDER_MODE = "stub"
    _approved_agreement(submitted_application, reviewer, external_id="ds-1")

    other_guardian = resolve_guardian_for_account(other_parent_account)
    other_member = Member.objects.create(
        full_name="Other Child", guardian=other_guardian
    )
    other_agreement = create_agreement_for_member(
        other_member, signing_path="paper"
    )
    other_agreement.external_id = "ds-other"
    other_agreement.save(update_fields=["external_id"])

    client.force_login(reviewer)
    resp = client.get(
        _docuseal_document_url(submitted_application.id, other_agreement.id)
    )
    assert resp.status_code == 404


def test_docuseal_document_route_invalid_disposition_404(
    settings, client, submitted_application, reviewer
):
    """Invalid ?disposition must be a 404."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    client.force_login(reviewer)
    url = _docuseal_document_url(submitted_application.id, agreement.id)
    resp = client.get(f"{url}?disposition=bogus")
    assert resp.status_code == 404


def test_docuseal_document_route_no_external_id_redirects_with_message(
    settings, client, submitted_application, reviewer
):
    """No external id → Latvian admin message + redirect to the application
    change page (not 404)."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    agreement = _approved_agreement(submitted_application, reviewer)
    client.force_login(reviewer)
    resp = client.get(
        _docuseal_document_url(submitted_application.id, agreement.id),
        follow=True,
    )
    assert resp.status_code == 200
    assert "DocuSeal sūtījums vēl nav izveidots" in resp.content.decode()


def test_docuseal_document_route_provider_error_redirects_with_latvian_message(
    settings, client, submitted_application, reviewer
):
    """A provider error must surface a fixed Latvian generic error on the
    change page — never the raw provider exception text."""
    from apps.integrations import agreement_platform as ap

    settings.AGREEMENT_PROVIDER_MODE = "stub"
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    client.force_login(reviewer)
    url = _docuseal_document_url(submitted_application.id, agreement.id)
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        side_effect=ap.AgreementPlatformNotFoundError("gone"),
        create=True,
    ):
        resp = client.get(url, follow=True)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Radās kļūda saziņā ar DocuSeal" in html
    assert "gone" not in html


@pytest.mark.parametrize(
    "state, label",
    [
        ("generated", "Sagatavots"),
        ("sent", "Nosūtīts parakstīšanai"),
        ("signed", "Parakstīts"),
        ("void", "Atcelts"),
        ("superseded", "Aizvietots"),
        ("discontinued", "Pārtraukts"),
    ],
)
def test_change_page_renders_history_state_label_and_download_link(
    client, submitted_application, reviewer, state, label,
):
    """For each agreement state, the change page must render the exact state
    display and the corresponding same-origin download endpoint for a
    history row."""
    from django.utils import timezone

    from apps.agreements.models import Agreement

    current = _approved_agreement(
        submitted_application, reviewer, external_id="cur-1"
    )
    member = submitted_application.approved_member
    history = Agreement.objects.create(
        member=member,
        is_current=False,
        state=state,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        generated_at=timezone.now(),
        external_id="hist-1",
    )

    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()

    assert label in html
    assert _docuseal_document_url(submitted_application.id, history.id) in html


def test_retry_action_re_enqueues_create_paper_send_email_false(
    client, submitted_application, reviewer
):
    """Retrying a failed paper-path submission must pass send_email=False."""
    from apps.agreements.models import Agreement

    agreement = _approved_agreement(
        submitted_application,
        reviewer,
        signing_path=Agreement.SigningPath.PAPER,
        external_state="failed",
        external_error_code="unavailable",
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_create_agreement_submission"
    ) as spy:
        client.post(
            _action_url(submitted_application.id),
            {"action": "retry_docuseal"},
        )
    spy.assert_called_once_with(agreement.id, send_email=False)


def test_retry_action_re_enqueues_create_electronic_send_email_true(
    client, submitted_application, reviewer
):
    """Retrying a failed electronic-path submission must pass send_email=True."""
    from apps.agreements.models import Agreement

    agreement = _approved_agreement(
        submitted_application,
        reviewer,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        external_state="failed",
        external_error_code="unavailable",
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_create_agreement_submission"
    ) as spy:
        client.post(
            _action_url(submitted_application.id),
            {"action": "retry_docuseal"},
        )
    spy.assert_called_once_with(agreement.id, send_email=True)


def test_retry_action_rejected_when_not_failed(
    client, submitted_application, reviewer
):
    _approved_agreement(
        submitted_application, reviewer, external_state="pending"
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_create_agreement_submission"
    ) as spy:
        resp = client.post(
            _action_url(submitted_application.id),
            {"action": "retry_docuseal"},
            follow=True,
        )
    assert "Atkārtot var tikai neizdevušos sūtījumu." in resp.content.decode()
    spy.assert_not_called()


def test_sync_action_enqueues_sync(client, submitted_application, reviewer):
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_sync_agreement_submission"
    ) as spy:
        client.post(
            _action_url(submitted_application.id),
            {"action": "sync_docuseal"},
        )
    spy.assert_called_once_with(agreement.id)
