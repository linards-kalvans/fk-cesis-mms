"""Expected parent input and delivery failures must not become server errors."""

from smtplib import SMTPException, SMTPSenderRefused
from unittest.mock import patch
import re

import pytest
from django.urls import reverse

from apps.accounts.models import EmailVerificationCode
from apps.documents.models import Document

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("email", ["not-an-email", "parent@", "a\n@example.com"])
def test_invalid_entry_email_is_rejected_before_issuing_code(client, email):
    with patch("apps.registrations.views.issue_one_time_code") as issue:
        response = client.post("/register/", {"email": email})

    assert response.status_code == 400
    assert "Ievadiet derīgu e-pasta adresi." in response.content.decode()
    issue.assert_not_called()
    assert not EmailVerificationCode.objects.exists()
    assert "pending_verification_email" not in client.session


@pytest.mark.parametrize(
    "error",
    [SMTPException("private SMTP details"), SMTPSenderRefused(550, b"denied", "sender")],
)
def test_code_delivery_failure_is_friendly(client, error):
    with patch("apps.registrations.views.send_one_time_code_email", side_effect=error):
        response = client.post("/register/", {"email": "parent@example.com"})

    assert response.status_code == 400
    assert "Neizdevās nosūtīt kodu. Lūdzu, mēģiniet vēlreiz." in response.content.decode()
    assert "private SMTP details" not in response.content.decode()
    assert "pending_verification_email" not in client.session


@pytest.mark.parametrize("route", ["application-workspace", "submit-registration"])
def test_missing_portrait_has_friendly_linked_field_error(
    verified_client, draft_with_documents, submit_payload, route,
):
    draft_with_documents.documents.filter(kind=Document.Kind.MEMBER_PORTRAIT).delete()
    url = reverse(f"registrations:{route}", args=[draft_with_documents.pk])
    with patch("apps.registrations.views.analytics_services.track_application_submitted") as track:
        response = verified_client.post(url, {
            **submit_payload,
            "member_birth_date": "01.01.2025",
            "submit_action": "submit",
            "personal_data_consent": True,
        })

    assert response.status_code == 400
    content = response.content.decode()
    assert "Lūdzu, augšupielādējiet bērna portretu." in content
    assert 'href="#id_member_portrait_document"' in content
    assert "__all__" not in content
    assert "member portrait document is required before submit" not in content
    assert "member_portrait_document" in response.context["form"].errors
    draft_with_documents.refresh_from_db()
    assert draft_with_documents.status == "draft"
    track.assert_not_called()


def test_portrait_participates_in_documents_step_gate(verified_client, draft_application):
    response = verified_client.get(reverse(
        "registrations:application-workspace", args=[draft_application.pk],
    ))
    field = response.context["form"].fields["member_portrait_document"]
    assert field.widget.attrs["data-step-required"] == "documents"
    assert field.widget.attrs["data-step-error-empty"] == "Lūdzu, augšupielādējiet bērna portretu."
    portrait_input = re.search(
        r'<input\b[^>]*name="member_portrait_document"[^>]*>', response.content.decode(),
    ).group()
    assert 'data-step-required="documents"' in portrait_input


@pytest.mark.parametrize("route", ["application-workspace", "submit-registration"])
def test_existing_portrait_allows_submit_without_reupload(
    verified_client, draft_with_documents, submit_payload, route,
):
    response = verified_client.post(
        reverse(f"registrations:{route}", args=[draft_with_documents.pk]),
        {**submit_payload, "member_birth_date": "01.01.2025",
         "personal_data_consent": True, "submit_action": "submit"},
    )
    assert response.status_code == 302
    draft_with_documents.refresh_from_db()
    assert draft_with_documents.status == "submitted"


def test_missing_portrait_does_not_block_draft_autosave(
    verified_client, draft_application, submit_payload,
):
    response = verified_client.post(
        reverse("registrations:application-workspace", args=[draft_application.pk]),
        {**submit_payload, "member_birth_date": "01.01.2025"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200


@pytest.mark.parametrize("route", ["application-workspace", "submit-registration"])
def test_new_portrait_upload_allows_submit(
    verified_client, draft_with_documents, submit_payload, member_portrait_file, route,
):
    draft_with_documents.documents.filter(kind=Document.Kind.MEMBER_PORTRAIT).delete()
    member_portrait_file.seek(0)
    response = verified_client.post(
        reverse(f"registrations:{route}", args=[draft_with_documents.pk]),
        {**submit_payload, "member_birth_date": "01.01.2025",
         "personal_data_consent": True, "submit_action": "submit",
         "member_portrait_document": member_portrait_file},
    )
    assert response.status_code == 302, response.context["form"].errors
    draft_with_documents.refresh_from_db()
    assert draft_with_documents.status == "submitted"


@pytest.mark.parametrize("route", ["application-workspace", "submit-registration"])
def test_other_submit_service_errors_still_return_400(
    verified_client, draft_with_documents, submit_payload, route,
):
    with patch("apps.registrations.views.submit_application", side_effect=ValueError("Nevar iesniegt pieteikumu.")):
        response = verified_client.post(
            reverse(f"registrations:{route}", args=[draft_with_documents.pk]),
            {**submit_payload, "member_birth_date": "01.01.2025",
             "personal_data_consent": True, "submit_action": "submit"},
        )
    assert response.status_code == 400
    content = response.content.decode()
    assert "Nevar iesniegt pieteikumu." in content
    assert "__all__" not in content
