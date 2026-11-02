"""Expected parent input and delivery failures must not become server errors."""

from smtplib import SMTPException, SMTPSenderRefused
from unittest.mock import patch

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
def test_submit_service_validation_error_is_rendered(
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
    assert "member portrait document is required before submit" in response.content.decode()
    assert response.context["form"].non_field_errors()
    draft_with_documents.refresh_from_db()
    assert draft_with_documents.status == "draft"
    track.assert_not_called()
