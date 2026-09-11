"""P16-A: registration-admin signed-artifact upload + serve tests.

Covers the named source-member-scoped routes:

* ``admin:registrations_registrationapplication_signed_artifact_upload``
* ``admin:registrations_registrationapplication_signed_artifact``

Contracts: upload requires change permission, is POST-only, validates the
Agreement belongs to ``application.approved_member`` (foreign -> 404), maps
service ``ValueError`` to a Latvian admin message, works for every lifecycle
state (current/superseded/voided/discontinued), and the review page lists
every source-member Agreement newest-first without raw storage URLs.

Red-phase discipline: routes and panel context are absent until
implementation, so every test first asserts the feature exists via clean
assertions (never NoReverseMatch collection errors).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import get_current_agreement
from apps.core import models as core_models
from apps.core.models import AuditEvent
from apps.registrations.services import approve_application

pytestmark = pytest.mark.django_db

SIGNED_ARTIFACT_UPLOADED = getattr(
    core_models.AuditEvent.Action, "SIGNED_ARTIFACT_UPLOADED", None
)

_MSG_UNSUPPORTED = (
    "Neatbalstītais faila formāts. Pieņemti tikai PDF vai .edoc faili."
)


def _resolve(name, args=()):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return None


def _upload_url(application, agreement):
    return _resolve(
        "admin:registrations_registrationapplication_signed_artifact_upload",
        (application.pk, agreement.pk),
    )


def _serve_url(application, agreement):
    return _resolve(
        "admin:registrations_registrationapplication_signed_artifact",
        (application.pk, agreement.pk),
    )


def uploaded_file(name, body, content_type):
    return SimpleUploadedFile(name, body, content_type=content_type)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(username="artifact-reviewer", is_staff=True)


@pytest.fixture
def approved_app(submitted_application, reviewer):
    """A submitted application that has been approved — Member + Agreement."""
    return approve_application(submitted_application, reviewer)


@pytest.fixture
def plain_staff_client(db):
    """Authenticated staff user WITHOUT model change permissions."""
    user = User.objects.create_user(username="plain-staff", is_staff=True, password="pw")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def other_agreement(db):
    """An Agreement belonging to a different member (foreign for approved_app)."""
    from apps.members.models import Member
    from tests.support import make_guardian

    guardian = make_guardian(full_name="Cita Vecāks")
    member = Member.objects.create(full_name="Cits Bērns", guardian=guardian)
    return Agreement.objects.create(
        member=member,
        is_current=True,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=timezone.now(),
    )


def _store(agreement, filename, body, content_type, *, at=None):
    assert hasattr(Agreement, "signed_artifact")
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
# Route existence + permission gates (requirement 6)
# ---------------------------------------------------------------------------


def test_signed_artifact_routes_resolve(approved_app):
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    assert _upload_url(approved_app, agreement) is not None
    assert _serve_url(approved_app, agreement) is not None


def test_upload_requires_change_permission(approved_app, plain_staff_client):
    agreement = get_current_agreement(approved_app.approved_member)
    url = _upload_url(approved_app, agreement)
    assert url is not None
    resp = plain_staff_client.post(
        url, {"signed_artifact": uploaded_file("x.pdf", b"%PDF-", "application/pdf")}
    )
    assert resp.status_code == 403


def test_upload_anonymous_redirected_to_admin_login(approved_app):
    agreement = get_current_agreement(approved_app.approved_member)
    url = _upload_url(approved_app, agreement)
    assert url is not None
    resp = Client().post(
        url, {"signed_artifact": uploaded_file("x.pdf", b"%PDF-", "application/pdf")}
    )
    assert resp.status_code in (302, 403)


def test_upload_rejects_get_and_redirects_to_change_page(
    staff_client, approved_app,
):
    agreement = get_current_agreement(approved_app.approved_member)
    url = _upload_url(approved_app, agreement)
    assert url is not None
    resp = staff_client.get(url)
    assert resp.status_code == 302
    assert resp.url == reverse(
        "admin:registrations_registrationapplication_change", args=[approved_app.pk]
    )


# ---------------------------------------------------------------------------
# Upload happy path (requirements 2, 6)
# ---------------------------------------------------------------------------


def test_upload_accepts_valid_pdf_sets_fields_and_audits(
    staff_client, approved_app,
):
    assert SIGNED_ARTIFACT_UPLOADED is not None
    agreement = get_current_agreement(approved_app.approved_member)
    url = _upload_url(approved_app, agreement)
    assert url is not None
    body = b"%PDF-1.7\n"
    resp = staff_client.post(
        url, {"signed_artifact": uploaded_file("līgums.pdf", body, "application/pdf")},
        follow=True,
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "augšupielādēts" in html.lower()

    agreement.refresh_from_db()
    assert agreement.signed_artifact.name.startswith("agreements/signed/")
    assert agreement.signed_artifact_original_filename == "līgums.pdf"
    assert agreement.signed_artifact_content_type == "application/pdf"
    assert agreement.signed_artifact_file_size == len(body)

    events = AuditEvent.objects.filter(action=str(SIGNED_ARTIFACT_UPLOADED))
    assert events.count() == 1
    assert events.get().metadata == {
        "agreement_id": agreement.pk,
        "operation": "uploaded",
    }


def test_upload_maps_service_valueerror_to_latvian_admin_message(
    staff_client, approved_app,
):
    agreement = get_current_agreement(approved_app.approved_member)
    url = _upload_url(approved_app, agreement)
    assert url is not None
    resp = staff_client.post(
        url,
        {"signed_artifact": uploaded_file("bad.txt", b"hello", "text/plain")},
        follow=True,
    )
    assert resp.status_code == 200
    assert _MSG_UNSUPPORTED in resp.content.decode()


def test_upload_foreign_agreement_is_404(staff_client, approved_app, other_agreement):
    url = _upload_url(approved_app, other_agreement)
    assert url is not None
    resp = staff_client.post(
        url, {"signed_artifact": uploaded_file("x.pdf", b"%PDF-", "application/pdf")}
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "state",
    [
        Agreement.State.GENERATED,
        Agreement.State.SUPERSEDED,
        Agreement.State.VOID,
        Agreement.State.DISCONTINUED,
    ],
)
def test_upload_and_replace_for_every_lifecycle_state(
    staff_client, approved_app, state,
):
    assert SIGNED_ARTIFACT_UPLOADED is not None
    member = approved_app.approved_member
    if state == Agreement.State.GENERATED:
        agreement = get_current_agreement(member)
        assert agreement is not None
    else:
        agreement = Agreement.objects.create(
            member=member,
            is_current=False,
            state=state,
            signing_path=Agreement.SigningPath.PAPER,
            generated_at=timezone.now(),
        )
    url = _upload_url(approved_app, agreement)
    assert url is not None

    resp = staff_client.post(
        url, {"signed_artifact": uploaded_file("a.pdf", b"%PDF-", "application/pdf")},
        follow=True,
    )
    assert resp.status_code == 200
    agreement.refresh_from_db()
    assert agreement.signed_artifact.name.startswith("agreements/signed/")
    first_audit = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED), target_id=str(agreement.pk)
    )
    assert first_audit.count() == 1
    assert first_audit.get().metadata["operation"] == "uploaded"

    resp = staff_client.post(
        url, {"signed_artifact": uploaded_file("b.pdf", b"%PDF-2", "application/pdf")},
        follow=True,
    )
    assert resp.status_code == 200
    agreement.refresh_from_db()
    assert agreement.signed_artifact_original_filename == "b.pdf"
    audits = AuditEvent.objects.filter(
        action=str(SIGNED_ARTIFACT_UPLOADED), target_id=str(agreement.pk)
    ).order_by("pk")
    assert audits.count() == 2
    assert audits[1].metadata == {
        "agreement_id": agreement.pk,
        "operation": "replaced",
    }


# ---------------------------------------------------------------------------
# Review-page panel — every source-member Agreement, newest first
# (requirements 1, 6)
# ---------------------------------------------------------------------------


def test_panel_lists_every_source_member_agreement_newest_first(
    staff_client, approved_app,
):
    assert hasattr(Agreement, "signed_artifact")
    member = approved_app.approved_member
    current = get_current_agreement(member)
    assert current is not None
    t0 = timezone.now()
    rows = [
        (current, Agreement.State.GENERATED, t0),  # newest
    ]
    for index, state in enumerate(
        (Agreement.State.SUPERSEDED, Agreement.State.VOID, Agreement.State.DISCONTINUED)
    ):
        rows.append(
            (
                Agreement.objects.create(
                    member=member,
                    is_current=False,
                    state=state,
                    signing_path=Agreement.SigningPath.PAPER,
                    generated_at=t0 - timezone.timedelta(minutes=1),
                ),
                state,
                t0 - timezone.timedelta(days=index + 1),
            )
        )
    rows.sort(key=lambda r: r[2], reverse=True)
    for agreement, _state, at in rows:
        _store(
            agreement,
            f"file-{agreement.pk}.pdf",
            b"%PDF-",
            "application/pdf",
            at=at,
        )

    resp = staff_client.get(
        reverse("admin:registrations_registrationapplication_change", args=[approved_app.pk])
    )
    assert resp.status_code == 200
    html = resp.content.decode()

    upload_urls = [_upload_url(approved_app, agreement) for agreement, _s, _t in rows]
    assert all(url is not None for url in upload_urls)
    for url in upload_urls:
        assert url in html

    indexes = [html.index(url) for url in upload_urls]
    assert indexes == sorted(indexes), "agreements must render newest-first"


def test_panel_orders_artifact_rows_before_no_artifact_rows(
    staff_client, approved_app,
):
    """In a mixed list, Agreements carrying an artifact timestamp sort ahead
    of no-artifact rows — the intended NULLS LAST contract (PostgreSQL sorts
    DESC NULLS FIRST by default, so the query must pin ``.nulls_last()``).
    May pass on SQLite; must hold cross-database."""
    assert hasattr(Agreement, "signed_artifact")
    member = approved_app.approved_member
    current = get_current_agreement(member)
    assert current is not None
    _store(current, "with-file.pdf", b"%PDF-", "application/pdf")
    no_artifact = Agreement.objects.create(
        member=member,
        is_current=False,
        state=Agreement.State.VOID,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=timezone.now(),
    )

    resp = staff_client.get(
        reverse("admin:registrations_registrationapplication_change", args=[approved_app.pk])
    )
    html = resp.content.decode()

    artifact_url = _serve_url(approved_app, current)
    no_artifact_form_url = _upload_url(approved_app, no_artifact)
    assert artifact_url is not None
    assert no_artifact_form_url is not None
    assert artifact_url in html
    assert no_artifact_form_url in html
    assert html.index(artifact_url) < html.index(no_artifact_form_url)


def test_panel_renders_upload_form_for_every_row_and_serve_links_for_files(
    staff_client, approved_app,
):
    assert hasattr(Agreement, "signed_artifact")
    member = approved_app.approved_member
    current = get_current_agreement(member)
    assert current is not None
    with_file = [current]
    without_file = []
    for state in (Agreement.State.SUPERSEDED, Agreement.State.VOID):
        without_file.append(
            Agreement.objects.create(
                member=member,
                is_current=False,
                state=state,
                signing_path=Agreement.SigningPath.PAPER,
                generated_at=timezone.now(),
            )
        )
    for agreement in with_file:
        _store(agreement, "with-file.pdf", b"%PDF-", "application/pdf")

    resp = staff_client.get(
        reverse("admin:registrations_registrationapplication_change", args=[approved_app.pk])
    )
    html = resp.content.decode()

    all_agreements = with_file + without_file
    for agreement in all_agreements:
        assert _upload_url(approved_app, agreement) in html
    # One upload input per Agreement row (including no-file rows).
    assert html.count('name="signed_artifact"') == len(all_agreements)
    # Rows with a file render the replace button + serve link + neutral status.
    for agreement in with_file:
        assert _serve_url(approved_app, agreement) in html
    assert html.count("Aizvietot") == len(with_file)
    assert html.count("Status nav pieejams") == len(with_file)
    assert html.count("Augšupielādēt") == len(without_file)


def test_panel_never_exposes_raw_storage_url_or_name(
    staff_client, approved_app,
):
    assert hasattr(Agreement, "signed_artifact")
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    _store(agreement, "confidential-name.pdf", b"%PDF-", "application/pdf")

    resp = staff_client.get(
        reverse("admin:registrations_registrationapplication_change", args=[approved_app.pk])
    )
    html = resp.content.decode()
    assert "agreements/signed/" not in html
    assert "private-uploads" not in html
    assert "confidential-name.pdf" not in html


# ---------------------------------------------------------------------------
# Serve route (requirements 5, 6)
# ---------------------------------------------------------------------------


def test_serve_pdf_can_be_inline_for_staff(staff_client, approved_app):
    assert hasattr(Agreement, "signed_artifact")
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    _store(agreement, "preview.pdf", b"%PDF-1.7\n", "application/pdf")

    url = _serve_url(approved_app, agreement)
    assert url is not None
    resp = staff_client.get(f"{url}?disposition=inline")
    assert resp.status_code == 200
    assert "inline" in resp["Content-Disposition"]
    assert resp["Content-Type"] == "application/pdf"


def test_serve_edoc_is_attachment(staff_client, approved_app):
    assert hasattr(Agreement, "signed_artifact")
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    _store(agreement, "signed.edoc", b"EDOC-2026", "")

    url = _serve_url(approved_app, agreement)
    assert url is not None
    resp = staff_client.get(url)
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]


def test_serve_defaults_to_attachment(staff_client, approved_app):
    assert hasattr(Agreement, "signed_artifact")
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    url = _serve_url(approved_app, agreement)
    assert url is not None
    resp = staff_client.get(url)
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]


def test_serve_invalid_disposition_is_404(staff_client, approved_app):
    assert hasattr(Agreement, "signed_artifact")
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    url = _serve_url(approved_app, agreement)
    assert url is not None
    assert staff_client.get(f"{url}?disposition=bogus").status_code == 404


def test_serve_blank_artifact_is_404(staff_client, approved_app):
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    url = _serve_url(approved_app, agreement)
    assert url is not None
    assert staff_client.get(url).status_code == 404


def test_serve_foreign_agreement_is_404(staff_client, approved_app, other_agreement):
    url = _serve_url(approved_app, other_agreement)
    assert url is not None
    assert staff_client.get(url).status_code == 404


def test_serve_streams_stored_bytes_without_provider_call(
    staff_client, approved_app,
):
    assert hasattr(Agreement, "signed_artifact")
    agreement = get_current_agreement(approved_app.approved_member)
    assert agreement is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\nbytes", "application/pdf")

    url = _serve_url(approved_app, agreement)
    assert url is not None
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        create=True,
    ) as stream_spy:
        resp = staff_client.get(url)
    stream_spy.assert_not_called()
    assert b"".join(resp.streaming_content) == b"%PDF-1.7\nbytes"