"""Tests for P19 submitted-registration digest daily job.

Covers public-contract behavior of ``apps.registrations.tasks.send_submitted_registration_digest``:
- Selection: submitted_at set AND submission_digest_sent_at is None, regardless of current status.
- Email: exactly one plain-text Latvian EmailMessage(to=[], bcc=[...]); serialized MIME has no Bcc: header.
- Body content: child name, guardian display name, Riga-local submitted time, current Latvian status label, absolute admin change URL.
- Body must NOT include guardian email, phone, personal IDs, addresses, documents, or review-message text.
- Success: return delivered count, set included rows' submission_digest_sent_at, set singleton last_successful_at.
- Empty pending: return 0, no email, no state advance on rows or singleton.
- Failure (no recipients, recipient without email, EmailMessage.send raises, send returns 0): return 0, no state advance on rows or singleton.
- Locking boundary: sent rows excluded next run; resubmitted (pending) rows re-included next run.
- Admin: only superuser can view/change digest settings; add blocked after singleton exists; delete always blocked.

Out of scope: django-q workers, real SMTP, migration reversal, threading, templates.
"""

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_singleton_with_recipients(*emails):
    """Add Users with given emails as recipients on the singleton settings row."""
    from apps.registrations.models import RegistrationSubmissionDigestSettings

    settings_obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
    for email in emails:
        user = User.objects.create_user(
            username=email.split("@")[0], email=email, is_staff=True
        )
        settings_obj.recipients.add(user)
    return settings_obj


def _make_minimal_submitted(parent_account, kit_sizes, *, suffix=""):
    """Build the smallest possible submitted application for digest tests.

    Uses the kit_sizes fixture for a valid shirt FK. Guardian/member data are
    deterministic; documents are created directly (no OCR, no upload mechanics).
    
    Always supplies support_club_instead_of_multi_child_discount=True to pass
    multi-child validation when called multiple times for the same parent.
    """
    from apps.documents.models import Document
    from apps.registrations.services import create_or_update_draft, submit_application
    from django.core.files.base import ContentFile

    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    shirt_pk, _ = kit_sizes

    app = create_or_update_draft(
        data={
            "guardian_email": parent_account.email,
            "guardian_first_name": f"G{suffix}",
            "guardian_family_name": f"Guardian{suffix}",
            "guardian_personal_id": f"010101-1{suffix or '0'}345",
            "guardian_phone": f"+371200000{suffix or '0'}",
            "guardian_declared_address": f"Riga, Street {suffix or '0'}",
            "member_full_name": f"Child{suffix}",
            "member_personal_id": f"010125-6{suffix or '0'}890",
            "member_birth_date": "2025-01-01",
            "member_same_address_as_guardian": True,
            "member_kit_size_shirt": shirt_pk,
            "preferred_agreement_signing": "paper",
            "support_club_instead_of_multi_child_discount": True,
        },
        files={},
        verified_account=parent_account,
    )
    for kind in (
        Document.Kind.GUARDIAN_IDENTITY,
        Document.Kind.MEMBER_IDENTITY,
        Document.Kind.MEMBER_PORTRAIT,
    ):
        Document.objects.create(
            application=app,
            kind=kind,
            file=ContentFile(png, name=f"{kind}.png"),
            original_filename=f"{kind}.png",
            content_type="image/png",
            file_size=len(png),
        )
    return submit_application(app, parent_account)


# ---------------------------------------------------------------------------
# Job: selection criteria
# ---------------------------------------------------------------------------


class TestDigestJobSelection:
    """Job selects applications with submitted_at set and submission_digest_sent_at is None."""

    def test_includes_submitted_application(self, parent_account, kit_sizes):
        """A submitted application must be included in the digest."""
        from apps.registrations.tasks import send_submitted_registration_digest

        _make_minimal_submitted(parent_account, kit_sizes)
        _configure_singleton_with_recipients("rec@example.com")

        assert send_submitted_registration_digest() == 1

    def test_excludes_draft_application(self, draft_application):
        """A draft application must NOT be included."""
        from apps.registrations.tasks import send_submitted_registration_digest

        _configure_singleton_with_recipients("rec@example.com")

        assert send_submitted_registration_digest() == 0

    def test_excludes_already_sent_application(self, parent_account, kit_sizes):
        """An application with submission_digest_sent_at set must be excluded."""
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        app.submission_digest_sent_at = timezone.now()
        app.save(update_fields=["submission_digest_sent_at"])

        _configure_singleton_with_recipients("rec@example.com")

        assert send_submitted_registration_digest() == 0

    @override_settings(SITE_URL="https://members.example.test")
    def test_includes_approved_application_with_current_status(
        self, parent_account, kit_sizes
    ):
        """An approved application must be included and body must show current status label."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        app.status = RegistrationApplication.Status.APPROVED
        app.save(update_fields=["status"])

        _configure_singleton_with_recipients("rec@example.com")

        assert send_submitted_registration_digest() == 1

        # Verify body contains approved status label, not stale "Iesniegts"
        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert "Apstiprināts" in body
        assert "Iesniegts" not in body


# ---------------------------------------------------------------------------
# Job: email privacy and content
# ---------------------------------------------------------------------------


class TestDigestJobEmailPrivacy:
    """Email uses EmailMessage(to=[], bcc=[...]); serialized MIME has no Bcc: header."""

    @override_settings(SITE_URL="https://members.example.test")
    def test_email_to_empty_bcc_envelope_no_bcc_header(
        self, parent_account, kit_sizes
    ):
        """Envelope bcc has recipients; serialized MIME has no Bcc: header line."""
        from apps.registrations.tasks import send_submitted_registration_digest

        _make_minimal_submitted(parent_account, kit_sizes)
        _configure_singleton_with_recipients("alice@example.com", "bob@example.com")

        send_submitted_registration_digest()

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == []
        assert set(message.bcc) == {"alice@example.com", "bob@example.com"}

        mime = message.message().as_string()
        for line in mime.splitlines():
            assert not line.lower().startswith("bcc:"), (
                f"Serialized MIME must not render a Bcc: header, found: {line!r}"
            )

    @override_settings(SITE_URL="https://members.example.test")
    def test_email_body_includes_required_fields_with_exact_time_and_url(
        self, parent_account, kit_sizes
    ):
        """Body includes child name, guardian display name, exact Riga-local submitted time, status label, exact admin URL."""
        from datetime import datetime, timezone

        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        # Make submitted_at deterministic for exact-format assertion.
        fixed_submitted = datetime(
            2026, 7, 15, 14, 30, 0, tzinfo=timezone.utc
        )
        app.submitted_at = fixed_submitted
        app.save(update_fields=["submitted_at"])

        _configure_singleton_with_recipients("rec@example.com")

        send_submitted_registration_digest()

        body = mail.outbox[0].body

        # Child name
        assert app.member_full_name in body
        # Guardian display name
        assert app.guardian_name in body
        # Riga-local submitted time — Europe/Riga is UTC+3 in July (EEST).
        from django.utils import timezone as django_timezone
        expected_local = django_timezone.localtime(fixed_submitted)
        expected_time_str = expected_local.strftime("%Y-%m-%d %H:%M")
        assert expected_time_str in body, (
            f"Expected Riga-local time {expected_time_str!r} in body, got: {body!r}"
        )
        # Current Latvian status label
        assert "Iesniegts" in body
        # Exact absolute admin change URL
        expected_url = (
            "https://members.example.test"
            + reverse("admin:registrations_registrationapplication_change", args=[app.pk])
        )
        assert expected_url in body

    @override_settings(SITE_URL="https://members.example.test")
    def test_email_body_excludes_pii(self, parent_account, kit_sizes):
        """Body must NOT include guardian email, phone, personal IDs, addresses, or review-message."""
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        app.review_message = "Secret review message"
        app.save(update_fields=["review_message"])

        _configure_singleton_with_recipients("rec@example.com")

        send_submitted_registration_digest()

        body = mail.outbox[0].body

        assert app.guardian_contact_email not in body
        assert app.guardian_contact_phone not in body
        assert app.guardian_pid not in body
        assert app.guardian_address not in body
        assert app.member_personal_id not in body
        assert "Secret review message" not in body


# ---------------------------------------------------------------------------
# Job: success state updates
# ---------------------------------------------------------------------------


class TestDigestJobSuccessState:
    """On success: return delivered count, set rows' submission_digest_sent_at, set singleton last_successful_at."""

    def test_returns_count_and_updates_row_and_singleton(
        self, parent_account, kit_sizes
    ):
        """Job returns delivered count and updates both row and singleton timestamps."""
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        settings_obj = _configure_singleton_with_recipients("rec@example.com")

        result = send_submitted_registration_digest()
        assert result == 1

        app.refresh_from_db()
        assert app.submission_digest_sent_at is not None

        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at is not None


# ---------------------------------------------------------------------------
# Job: empty pending range
# ---------------------------------------------------------------------------


class TestDigestJobEmptyPending:
    """Empty pending: return 0, no email, no state advance on rows or singleton."""

    def test_returns_zero_when_no_pending(self):
        """Job returns 0 and sends no email when no applications are pending."""
        from datetime import datetime, timezone

        from apps.registrations.tasks import send_submitted_registration_digest

        settings_obj = _configure_singleton_with_recipients("rec@example.com")
        # Pre-set a fixed last_successful_at so we can prove no regression.
        fixed_prior = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        settings_obj.last_successful_at = fixed_prior
        settings_obj.save(update_fields=["last_successful_at"])

        result = send_submitted_registration_digest()
        assert result == 0
        assert len(mail.outbox) == 0

        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at == fixed_prior


# ---------------------------------------------------------------------------
# Job: error handling
# ---------------------------------------------------------------------------


class TestDigestJobErrorHandling:
    """No recipients / recipient without email / send raises / send returns 0: return 0, no state advance."""

    def test_returns_zero_when_no_recipients(self, parent_account, kit_sizes):
        """Job returns 0 when no recipients are configured; row and singleton unchanged."""
        from datetime import datetime, timezone

        from apps.registrations.models import RegistrationSubmissionDigestSettings
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        settings_obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        # Pre-set a fixed last_successful_at so we can prove no regression.
        fixed_prior = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        settings_obj.last_successful_at = fixed_prior
        settings_obj.save(update_fields=["last_successful_at"])

        result = send_submitted_registration_digest()
        assert result == 0
        assert len(mail.outbox) == 0

        app.refresh_from_db()
        assert app.submission_digest_sent_at is None

        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at == fixed_prior

    def test_returns_zero_when_recipient_has_no_email(self, parent_account, kit_sizes):
        """Job returns 0 when recipient has no email address; row and singleton unchanged."""
        from datetime import datetime, timezone

        from apps.registrations.models import RegistrationSubmissionDigestSettings
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        settings_obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        user_no_email = User.objects.create_user(
            username="noemail", email="", is_staff=True
        )
        settings_obj.recipients.add(user_no_email)

        fixed_prior = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        settings_obj.last_successful_at = fixed_prior
        settings_obj.save(update_fields=["last_successful_at"])

        result = send_submitted_registration_digest()
        assert result == 0
        assert len(mail.outbox) == 0

        app.refresh_from_db()
        assert app.submission_digest_sent_at is None

        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at == fixed_prior

    def test_returns_zero_when_send_raises(self, parent_account, kit_sizes, monkeypatch):
        """Job returns 0 when EmailMessage.send raises; row and singleton unchanged."""
        from datetime import datetime, timezone

        from apps.registrations.models import RegistrationSubmissionDigestSettings
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        _configure_singleton_with_recipients("rec@example.com")
        settings_obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        fixed_prior = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        settings_obj.last_successful_at = fixed_prior
        settings_obj.save(update_fields=["last_successful_at"])

        def _raise(*args, **kwargs):
            raise Exception("SMTP error")

        monkeypatch.setattr("apps.registrations.tasks.EmailMessage.send", _raise)

        result = send_submitted_registration_digest()
        assert result == 0

        app.refresh_from_db()
        assert app.submission_digest_sent_at is None

        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at == fixed_prior

    def test_returns_zero_when_send_returns_zero(self, parent_account, kit_sizes, monkeypatch):
        """Job returns 0 when EmailMessage.send returns 0; row and singleton unchanged."""
        from datetime import datetime, timezone

        from apps.registrations.models import RegistrationSubmissionDigestSettings
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        _configure_singleton_with_recipients("rec@example.com")
        settings_obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        fixed_prior = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        settings_obj.last_successful_at = fixed_prior
        settings_obj.save(update_fields=["last_successful_at"])

        monkeypatch.setattr(
            "apps.registrations.tasks.EmailMessage.send", lambda *a, **kw: 0
        )

        result = send_submitted_registration_digest()
        assert result == 0

        app.refresh_from_db()
        assert app.submission_digest_sent_at is None

        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at == fixed_prior

    def test_filters_inactive_recipients_at_runtime(self, parent_account, kit_sizes):
        """Task must filter inactive/non-staff recipients at send time, not rely on picker."""
        from datetime import datetime, timezone

        from django.contrib.auth.models import User

        from apps.registrations.models import RegistrationSubmissionDigestSettings
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)

        # Create inactive staff User and directly attach to M2M (bypassing admin picker)
        settings_obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        inactive_user = User.objects.create_user(
            username="inactive_staff",
            email="inactive@example.com",
            is_staff=True,
            is_active=False,
        )
        settings_obj.recipients.add(inactive_user)

        # Pre-set last_successful_at to verify it's preserved
        fixed_prior = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        settings_obj.last_successful_at = fixed_prior
        settings_obj.save(update_fields=["last_successful_at"])

        # Task should return 0 (no active recipients)
        result = send_submitted_registration_digest()
        assert result == 0

        # No mail sent
        assert len(mail.outbox) == 0

        # Application state preserved
        app.refresh_from_db()
        assert app.submission_digest_sent_at is None

        # Singleton state preserved
        settings_obj.refresh_from_db()
        assert settings_obj.last_successful_at == fixed_prior


# ---------------------------------------------------------------------------
# Job: re-inclusion after resubmission (observable boundary only)
# ---------------------------------------------------------------------------


class TestDigestJobReInclusion:
    """Rows marked sent are excluded next run; rows reset to pending are re-included."""

    def test_sent_rows_excluded_next_run(self, parent_account, kit_sizes):
        """Rows with submission_digest_sent_at set must be excluded from the next run."""
        from apps.registrations.tasks import send_submitted_registration_digest

        _make_minimal_submitted(parent_account, kit_sizes)
        _configure_singleton_with_recipients("rec@example.com")

        assert send_submitted_registration_digest() == 1
        # Second run — row already marked sent, must not be re-delivered.
        assert send_submitted_registration_digest() == 0

    def test_pending_rows_reincluded_after_resubmission(
        self, parent_account, kit_sizes
    ):
        """A row whose submission_digest_sent_at has been cleared is re-included next run."""
        from apps.registrations.tasks import send_submitted_registration_digest

        app = _make_minimal_submitted(parent_account, kit_sizes)
        _configure_singleton_with_recipients("rec@example.com")

        assert send_submitted_registration_digest() == 1

        # Simulate the service clearing the flag on correction resubmission.
        app.submission_digest_sent_at = None
        app.save(update_fields=["submission_digest_sent_at"])

        assert send_submitted_registration_digest() == 1


# ---------------------------------------------------------------------------
# Job: incremental batch
# ---------------------------------------------------------------------------


class TestDigestJobIncrementalBatch:
    """Job handles multiple pending applications in one run."""

    def test_two_pending_returns_two_and_marks_both(self, parent_account, kit_sizes):
        """Two pending applications produce one email, return 2, both rows marked."""
        from apps.registrations.tasks import send_submitted_registration_digest

        app_a = _make_minimal_submitted(parent_account, kit_sizes, suffix="A")
        app_b = _make_minimal_submitted(parent_account, kit_sizes, suffix="B")
        _configure_singleton_with_recipients("rec@example.com")

        result = send_submitted_registration_digest()
        assert result == 2
        assert len(mail.outbox) == 1

        app_a.refresh_from_db()
        app_b.refresh_from_db()
        assert app_a.submission_digest_sent_at is not None
        assert app_b.submission_digest_sent_at is not None


# ---------------------------------------------------------------------------
# Admin authorization and recipient picker
# ---------------------------------------------------------------------------


class TestDigestSettingsAdminAuthorization:
    """Only superusers may access the digest settings admin; staff-only Users are denied. Add blocked after singleton exists; delete always blocked."""

    def test_non_superuser_staff_gets_403(self, db):
        """A staff (non-superuser) User must receive 403 on the digest settings change URL."""
        from django.test import Client

        from apps.registrations.models import RegistrationSubmissionDigestSettings

        # Ensure singleton exists.
        RegistrationSubmissionDigestSettings.objects.get_or_create(pk=1)

        staff_user = User.objects.create_user(
            username="staffonly",
            email="staffonly@example.com",
            password="pw",
            is_staff=True,
            is_superuser=False,
        )
        client = Client()
        client.login(username="staffonly", password="pw")

        resp = client.get(
            reverse(
                "admin:registrations_registrationsubmissiondigestsettings_change",
                args=[1],
            )
        )
        assert resp.status_code == 403, (
            f"Expected 403 for non-superuser staff, got {resp.status_code}"
        )

    def test_superuser_change_form_contains_active_staff_excludes_others(self, db):
        """Superuser change form picker must include active staff Users and exclude inactive/non-staff Users."""
        from django.test import Client
        from django.contrib.auth.models import User

        from apps.registrations.models import RegistrationSubmissionDigestSettings

        RegistrationSubmissionDigestSettings.objects.get_or_create(pk=1)

        active_staff = User.objects.create_user(
            username="active_staff",
            email="active_staff@example.com",
            password="pw",
            is_staff=True,
            is_active=True,
        )
        inactive_staff = User.objects.create_user(
            username="inactive_staff",
            email="inactive_staff@example.com",
            password="pw",
            is_staff=True,
            is_active=False,
        )
        active_non_staff = User.objects.create_user(
            username="active_nonstaff",
            email="active_nonstaff@example.com",
            password="pw",
            is_staff=False,
            is_active=True,
        )

        superuser = User.objects.create_superuser(
            username="su", email="su@example.com", password="pw"
        )
        client = Client()
        client.login(username="su", password="pw")

        resp = client.get(
            reverse(
                "admin:registrations_registrationsubmissiondigestsettings_change",
                args=[1],
            )
        )
        assert resp.status_code == 200
        body = resp.content.decode()

        assert active_staff.email in body
        assert inactive_staff.email not in body
        assert active_non_staff.email not in body

    def test_superuser_cannot_add_second_singleton(self, db):
        """Superuser must not be able to add a second digest settings configuration."""
        from django.test import Client
        from django.contrib.auth.models import User

        from apps.registrations.models import RegistrationSubmissionDigestSettings

        # Ensure singleton exists.
        RegistrationSubmissionDigestSettings.objects.get_or_create(pk=1)

        superuser = User.objects.create_superuser(
            username="su2", email="su2@example.com", password="pw"
        )
        client = Client()
        client.login(username="su2", password="pw")

        resp = client.get(
            reverse(
                "admin:registrations_registrationsubmissiondigestsettings_add"
            )
        )
        # Add should be blocked (403 via has_add_permission).
        assert resp.status_code == 403, (
            f"Expected 403 for add attempt, got {resp.status_code}"
        )

    def test_superuser_cannot_delete_singleton(self, db):
        """Superuser must not be able to delete the digest settings configuration."""
        from django.test import Client
        from django.contrib.auth.models import User

        from apps.registrations.models import RegistrationSubmissionDigestSettings

        # Ensure singleton exists.
        RegistrationSubmissionDigestSettings.objects.get_or_create(pk=1)

        superuser = User.objects.create_superuser(
            username="su3", email="su3@example.com", password="pw"
        )
        client = Client()
        client.login(username="su3", password="pw")

        resp = client.get(
            reverse(
                "admin:registrations_registrationsubmissiondigestsettings_delete",
                args=[1],
            )
        )
        # Delete should be blocked (403 via has_delete_permission).
        assert resp.status_code == 403, (
            f"Expected 403 for delete attempt, got {resp.status_code}"
        )
