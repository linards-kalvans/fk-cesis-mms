"""P23 — parent preview/download access contract for MedicalPermit files.

Routes live under the ``registrations`` namespace:
- ``registrations:medical-permit-preview``
- ``registrations:medical-permit-download``

Ownership-scoped GETs that stream the stored file only. Anonymous or
cross-family requests get the project-standard redirect or 404; a
confirmation-only / file-less permit is always 404. Preview/download are
audited and the audit metadata must not contain names / filenames / medical
facts / file bytes.
"""

from __future__ import annotations

import datetime
import pytest

pytestmark = pytest.mark.django_db


def _upload(name="permit.pdf", content_type="application/pdf"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name=name, content=b"%PDF-1.4 access", content_type=content_type
    )


def _verified_login(client, account):
    from apps.accounts.services import issue_magic_link

    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_owner_with_permit(*, with_file=True, confirmed=False):
    """Build owner account + application + permit; return (client, account, app, permit)."""
    from django.contrib.auth.models import User
    from django.test import Client

    from apps.accounts.models import ParentAccount
    from apps.documents.models import MedicalPermit
    from apps.registrations.models import RegistrationApplication

    account = ParentAccount.objects.create(
        email="permit-access-owner@example.com",
    )
    app = RegistrationApplication.objects.create(
        parent_account=account,
        claimed_email=account.email,
        status=RegistrationApplication.Status.DRAFT,
        member_full_name="Access Child",
    )
    source = (
        MedicalPermit.Source.STAFF_CONFIRMATION if confirmed
        else MedicalPermit.Source.PARENT_UPLOAD
    )
    kwargs = dict(
        application=app,
        source=source,
        valid_until=datetime.date(2027, 9, 30),
    )
    if with_file:
        kwargs.update(
            file=_upload(),
            original_filename="permit.pdf",
            content_type="application/pdf",
            file_size=15,
        )
    if confirmed:
        staff = User.objects.create_user(username="access-confirmer")
        kwargs["confirmed_by"] = staff
        kwargs["confirmed_at"] = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
    permit = MedicalPermit.objects.create(**kwargs)

    client = Client()
    _verified_login(client, account)
    return client, account, app, permit


class TestStoredFileStreaming:
    def test_owner_preview_streams_file_inline(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit()

        response = client.get(
            reverse("registrations:medical-permit-preview", args=[permit.pk])
        )

        assert response.status_code == 200
        assert response.streaming
        assert response["Content-Type"].startswith("application/pdf")
        assert "inline" in response.get("Content-Disposition", "")

    def test_owner_download_streams_file_attachment(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit()

        response = client.get(
            reverse("registrations:medical-permit-download", args=[permit.pk])
        )

        assert response.status_code == 200
        assert response.streaming
        assert response["Content-Type"].startswith("application/pdf")
        assert response["Content-Disposition"].startswith("attachment")


class TestAccessDenial:
    def test_anonymous_preview_refused(self):
        from django.test import Client
        from django.urls import reverse

        _client, _account, _app, permit = _make_owner_with_permit()

        response = Client().get(
            reverse("registrations:medical-permit-preview", args=[permit.pk])
        )

        assert response.status_code in (302, 404)
        assert response.status_code != 200

    def test_anonymous_download_refused(self):
        from django.test import Client
        from django.urls import reverse

        _client, _account, _app, permit = _make_owner_with_permit()

        response = Client().get(
            reverse("registrations:medical-permit-download", args=[permit.pk])
        )

        assert response.status_code in (302, 404)
        assert response.status_code != 200

    def test_cross_family_preview_refused(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit()
        from apps.accounts.models import ParentAccount
        from tests.conftest import _verified_login as _other_login  # noqa: F401

        other = ParentAccount.objects.create(email="permit-access-stranger@example.com")
        from django.test import Client

        stranger = Client()
        _verified_login(stranger, other)

        response = stranger.get(
            reverse("registrations:medical-permit-preview", args=[permit.pk])
        )

        assert response.status_code == 404

    def test_cross_family_download_refused(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit()
        from apps.accounts.models import ParentAccount
        from django.test import Client

        other = ParentAccount.objects.create(email="permit-access-stranger-2@example.com")
        stranger = Client()
        _verified_login(stranger, other)

        response = stranger.get(
            reverse("registrations:medical-permit-download", args=[permit.pk])
        )

        assert response.status_code == 404

    def test_confirmation_only_permit_preview_refused(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit(
            with_file=False, confirmed=True
        )

        response = client.get(
            reverse("registrations:medical-permit-preview", args=[permit.pk])
        )

        assert response.status_code == 404

    def test_confirmation_only_permit_download_refused(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit(
            with_file=False, confirmed=True
        )

        response = client.get(
            reverse("registrations:medical-permit-download", args=[permit.pk])
        )

        assert response.status_code == 404

    def test_cleared_permit_preview_refused(self):
        from django.urls import reverse

        client, _account, _app, permit = _make_owner_with_permit(
            with_file=False, confirmed=False
        )

        response = client.get(
            reverse("registrations:medical-permit-preview", args=[permit.pk])
        )

        assert response.status_code == 404


class TestAuditContract:
    def _recent_event(self, action):
        from apps.core.models import AuditEvent

        return (
            AuditEvent.objects.filter(action=action).order_by("-created_at").first()
        )

    def test_preview_is_audited_without_sensitive_metadata(self):
        from django.urls import reverse

        client, _account, app, permit = _make_owner_with_permit()

        client.get(reverse("registrations:medical-permit-preview", args=[permit.pk]))

        event = self._recent_event("medical_permit_previewed")
        assert event is not None
        assert event.target_id == str(permit.pk)
        payload = str(event.metadata)
        assert permit.original_filename not in payload
        assert app.member_full_name not in payload

    def test_download_is_audited_without_sensitive_metadata(self):
        from django.urls import reverse

        client, _account, app, permit = _make_owner_with_permit()

        client.get(reverse("registrations:medical-permit-download", args=[permit.pk]))

        event = self._recent_event("medical_permit_downloaded")
        assert event is not None
        assert event.target_id == str(permit.pk)
        payload = str(event.metadata)
        assert permit.original_filename not in payload
        assert app.member_full_name not in payload

    def test_upload_is_audited_without_sensitive_metadata(self):
        from django.urls import reverse

        client, _account, app, permit = _make_owner_with_permit(with_file=False)
        upload = _upload("private-name.pdf")

        response = client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": upload},
        )

        assert response.status_code == 201
        event = self._recent_event("medical_permit_uploaded")
        assert event is not None
        assert "private-name.pdf" not in str(event.metadata)

    def test_second_upload_is_audited_as_replaced(self):
        from django.urls import reverse

        client, _account, app, permit = _make_owner_with_permit()

        response = client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload("replacement.pdf")},
        )

        assert response.status_code == 201
        event = self._recent_event("medical_permit_replaced")
        assert event is not None
        assert "replacement.pdf" not in str(event.metadata)

    def test_first_upload_is_uploaded_and_second_is_replaced(self):
        """The first write to a permit is an upload, the second a replacement —
        two distinct audit events, neither carrying filename or member name."""
        from django.urls import reverse

        from apps.core.models import AuditEvent

        client, _account, app, _permit = _make_owner_with_permit(with_file=False)

        first = client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload("first.pdf")},
        )
        second = client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload("second.pdf")},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        uploaded = self._recent_event("medical_permit_uploaded")
        replaced = self._recent_event("medical_permit_replaced")
        assert uploaded is not None
        assert replaced is not None
        assert (
            AuditEvent.objects.filter(action__in=(
                "medical_permit_uploaded", "medical_permit_replaced",
            )).count() == 2
        )
        payload = str(uploaded.metadata) + str(replaced.metadata)
        assert "first.pdf" not in payload
        assert "second.pdf" not in payload
        assert app.member_full_name not in payload

    def test_confirm_is_audited_with_redacted_metadata(self):
        """Staff confirmation emits medical_permit_confirmed with metadata free
        of filename and member name."""
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import confirm_medical_permit

        client, _account, app, permit = _make_owner_with_permit()
        staff = User.objects.create_user(username="audit-confirmer")

        confirm_medical_permit(permit, actor=staff)

        event = self._recent_event("medical_permit_confirmed")
        assert event is not None
        assert event.target_id == str(permit.pk)
        payload = str(event.metadata)
        assert permit.original_filename not in payload
        assert app.member_full_name not in payload

    def test_clear_is_audited_with_redacted_metadata(self):
        """Clearing a staff confirmation emits medical_permit_confirmation_cleared
        with metadata free of filename and member name."""
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import (
            clear_medical_permit_confirmation,
            confirm_medical_permit,
        )

        client, _account, app, permit = _make_owner_with_permit()
        staff = User.objects.create_user(username="audit-clearer")
        confirm_medical_permit(permit, actor=staff)

        clear_medical_permit_confirmation(permit, actor=staff)

        event = self._recent_event("medical_permit_confirmation_cleared")
        assert event is not None
        assert event.target_id == str(permit.pk)
        payload = str(event.metadata)
        assert permit.original_filename not in payload
        assert app.member_full_name not in payload