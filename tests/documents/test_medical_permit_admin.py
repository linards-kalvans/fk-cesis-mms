"""P23 — admin surfaces for MedicalPermit.

- ``RegistrationApplication`` + ``Member`` changelists expose a
  missing/expiring/expired status filter (``medical_permit_status``), mirroring
  the sync-health filter parameter convention (``?sync_health=…``).
- The ``RegistrationApplication`` change page renders the permit status plus
  staff controls (upload/replace, confirmation-without-file, clear
  confirmation) that dispatch through the existing review-action POST endpoint.
- The Guardian family hub renders per-member permit status and the same staff
  controls through the family-hub action endpoint.

Audit contract: every permit mutation is audited with the six
``medical_permit_*`` actions and redacted metadata (no filename / names).
"""

from __future__ import annotations

import datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import Member

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _freeze(monkeypatch, year, month, day):
    import django.utils.timezone as timezone_module

    def _localdate():
        return datetime.date(year, month, day)

    monkeypatch.setattr(timezone_module, "localdate", _localdate)


def _upload(name="permit.pdf", content_type="application/pdf"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name=name, content=b"%PDF-1.4 admin", content_type=content_type
    )


def _app_with_permit(name, *, valid_until, with_file=True):
    from apps.documents.models import MedicalPermit
    from apps.registrations.models import RegistrationApplication

    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        member_full_name=name,
    )
    kwargs = dict(
        application=app,
        source=MedicalPermit.Source.PARENT_UPLOAD,
        valid_until=valid_until,
    )
    if with_file:
        kwargs.update(
            file=_upload(),
            original_filename="permit.pdf",
            content_type="application/pdf",
            file_size=15,
        )
    MedicalPermit.objects.create(**kwargs)
    return app


def _member_with_permit(name, *, valid_until=None, with_file=True):
    from tests.support import make_guardian

    from apps.documents.models import MedicalPermit
    from apps.registrations.models import RegistrationApplication

    guardian = make_guardian(full_name=f"{name} Guardian")
    member = Member.objects.create(full_name=name, guardian=guardian)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        member_full_name=name,
        guardian=guardian,
        approved_member=member,
    )
    if valid_until is not None:
        kwargs = dict(
            application=app,
            source=MedicalPermit.Source.PARENT_UPLOAD,
            valid_until=valid_until,
        )
        if with_file:
            kwargs.update(
                file=_upload(),
                original_filename="permit.pdf",
                content_type="application/pdf",
                file_size=15,
            )
        MedicalPermit.objects.create(member=member, **kwargs)
    return member


# ---------------------------------------------------------------------------
# RegistrationApplication changelist filter
# ---------------------------------------------------------------------------


class TestRegistrationChangelistFilter:
    def test_filter_sidebar_is_present(self):
        c = _staff_client()
        body = c.get(
            reverse("admin:registrations_registrationapplication_changelist")
        ).content.decode()
        assert "medical_permit_status" in body

    def test_filter_isolates_missing(self):
        c = _staff_client()
        _app_with_permit("HasPermitSentinel", valid_until=datetime.date(2027, 9, 30))
        from apps.registrations.models import RegistrationApplication

        RegistrationApplication.objects.create(
            status=RegistrationApplication.Status.SUBMITTED,
            member_full_name="MissingSentinel",
        )
        url = (
            reverse("admin:registrations_registrationapplication_changelist")
            + "?medical_permit_status=missing"
        )
        body = c.get(url).content.decode().split("</thead>")[-1]
        assert "MissingSentinel" in body
        assert "HasPermitSentinel" not in body

    def test_filter_isolates_expiring(self, monkeypatch):
        _freeze(monkeypatch, 2026, 8, 1)
        c = _staff_client()
        _app_with_permit("ExpiringSentinel", valid_until=datetime.date(2026, 9, 30))
        _app_with_permit("CurrentSentinel", valid_until=datetime.date(2027, 9, 30))
        url = (
            reverse("admin:registrations_registrationapplication_changelist")
            + "?medical_permit_status=expiring"
        )
        body = c.get(url).content.decode().split("</thead>")[-1]
        assert "ExpiringSentinel" in body
        assert "CurrentSentinel" not in body

    def test_filter_isolates_expired(self, monkeypatch):
        _freeze(monkeypatch, 2026, 10, 1)
        c = _staff_client()
        _app_with_permit("ExpiredSentinel", valid_until=datetime.date(2026, 9, 30))
        _app_with_permit("CurrentSentinel", valid_until=datetime.date(2027, 9, 30))
        url = (
            reverse("admin:registrations_registrationapplication_changelist")
            + "?medical_permit_status=expired"
        )
        body = c.get(url).content.decode().split("</thead>")[-1]
        assert "ExpiredSentinel" in body
        assert "CurrentSentinel" not in body


# ---------------------------------------------------------------------------
# Member changelist filter
# ---------------------------------------------------------------------------


class TestMemberChangelistFilter:
    def test_filter_isolates_missing(self):
        c = _staff_client()
        _member_with_permit("MHasPermitSentinel", valid_until=datetime.date(2027, 9, 30))
        _member_with_permit("MMissingSentinel", valid_until=None)
        url = (
            reverse("admin:members_member_changelist")
            + "?medical_permit_status=missing"
        )
        body = c.get(url).content.decode().split("</thead>")[-1]
        assert "MMissingSentinel" in body
        assert "MHasPermitSentinel" not in body

    def test_filter_isolates_expiring(self, monkeypatch):
        _freeze(monkeypatch, 2026, 8, 1)
        c = _staff_client()
        _member_with_permit("MExpiringSentinel", valid_until=datetime.date(2026, 9, 30))
        _member_with_permit("MCurrentSentinel", valid_until=datetime.date(2027, 9, 30))
        url = (
            reverse("admin:members_member_changelist")
            + "?medical_permit_status=expiring"
        )
        body = c.get(url).content.decode().split("</thead>")[-1]
        assert "MExpiringSentinel" in body
        assert "MCurrentSentinel" not in body

    def test_filter_isolates_expired(self, monkeypatch):
        _freeze(monkeypatch, 2026, 10, 1)
        c = _staff_client()
        _member_with_permit("MExpiredSentinel", valid_until=datetime.date(2026, 9, 30))
        _member_with_permit("MCurrentSentinel", valid_until=datetime.date(2027, 9, 30))
        url = (
            reverse("admin:members_member_changelist")
            + "?medical_permit_status=expired"
        )
        body = c.get(url).content.decode().split("</thead>")[-1]
        assert "MExpiredSentinel" in body
        assert "MCurrentSentinel" not in body


# ---------------------------------------------------------------------------
# RegistrationApplication change page: status + staff controls
# ---------------------------------------------------------------------------


class TestRegistrationChangePage:
    def test_change_page_renders_status_and_controls(self, monkeypatch):
        _freeze(monkeypatch, 2026, 8, 1)
        c = _staff_client()
        app = _app_with_permit("ControlChild", valid_until=datetime.date(2026, 9, 30))
        body = c.get(
            reverse("admin:registrations_registrationapplication_change", args=[app.pk])
        ).content.decode()
        assert 'data-medical-permit-status="expiring"' in body
        # Staff upload/replace control + confirmation-without-file + clear.
        assert 'name="medical_permit_file"' in body
        assert "confirm_medical_permit" in body
        assert "clear_medical_permit_confirmation" in body

    def test_confirm_without_file_via_review_action(self, monkeypatch):
        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        app = _app_with_permit("ConfirmChild", valid_until=datetime.date(2027, 9, 30))
        url = reverse(
            "admin:registrations_registrationapplication_review-action", args=[app.pk]
        )
        resp = c.post(url, {"action": "confirm_medical_permit"})
        assert resp.status_code == 302

        permit = MedicalPermit.objects.get(application=app)
        assert permit.source == "staff_confirmation"
        assert permit.file == ""
        assert permit.confirmed_by_id is not None
        assert permit.confirmed_at is not None

    def test_clear_confirmation_via_review_action(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import confirm_medical_permit

        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        app = _app_with_permit("ClearChild", valid_until=datetime.date(2027, 9, 30))
        confirm_medical_permit(
            app.medical_permit, actor=User.objects.create_user(username="cleared-by")
        )
        url = reverse(
            "admin:registrations_registrationapplication_review-action", args=[app.pk]
        )
        resp = c.post(url, {"action": "clear_medical_permit_confirmation"})
        assert resp.status_code == 302

        permit = MedicalPermit.objects.get(application=app)
        assert permit.confirmed_by_id is None
        assert permit.confirmed_at is None

    def test_staff_upload_replaces_via_review_action(self, monkeypatch):
        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        app = _app_with_permit("ReplaceChild", valid_until=datetime.date(2027, 9, 30))
        old_name = app.medical_permit.file.name
        url = reverse(
            "admin:registrations_registrationapplication_review-action", args=[app.pk]
        )
        resp = c.post(
            url,
            {"action": "medical_permit_upload", "medical_permit_file": _upload("staff.pdf")},
        )
        assert resp.status_code == 302

        permit = MedicalPermit.objects.get(application=app)
        assert permit.file.name != old_name
        assert permit.source == "staff_upload"
        assert permit.original_filename == "staff.pdf"

    def test_confirm_is_audited_without_sensitive_metadata(self, monkeypatch):
        from apps.core.models import AuditEvent

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        app = _app_with_permit("AuditChild", valid_until=datetime.date(2027, 9, 30))
        url = reverse(
            "admin:registrations_registrationapplication_review-action", args=[app.pk]
        )
        c.post(url, {"action": "confirm_medical_permit"})

        event = (
            AuditEvent.objects.filter(action="medical_permit_confirmed")
            .order_by("-created_at")
            .first()
        )
        assert event is not None
        assert event.target_id == str(app.medical_permit.pk)
        assert "permit.pdf" not in str(event.metadata)
        assert "AuditChild" not in str(event.metadata)


# ---------------------------------------------------------------------------
# Guardian family hub: per-member status + staff controls
# ---------------------------------------------------------------------------


class TestFamilyHub:
    def _hub_url(self, guardian):
        return reverse("admin:members_guardian_family_hub", args=[guardian.pk])

    def _hub_action_url(self, guardian):
        return reverse("admin:members_guardian_family_hub_action", args=[guardian.pk])

    def test_hub_renders_permit_status(self, monkeypatch):
        _freeze(monkeypatch, 2026, 8, 1)
        c = _staff_client()
        member = _member_with_permit("HubChild", valid_until=datetime.date(2026, 9, 30))
        body = c.get(self._hub_url(member.guardian)).content.decode()
        assert 'data-medical-permit-status="expiring"' in body

    def test_hub_confirm_without_file(self, monkeypatch):
        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        member = _member_with_permit("HubConfirm", valid_until=datetime.date(2027, 9, 30))
        resp = c.post(
            self._hub_action_url(member.guardian),
            {"action": "confirm_medical_permit", "member_id": member.pk},
        )
        assert resp.status_code == 302

        permit = MedicalPermit.objects.get(member=member)
        assert permit.source == "staff_confirmation"
        assert permit.file == ""
        assert permit.confirmed_by_id is not None

    def test_hub_clear_confirmation(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import confirm_medical_permit

        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        member = _member_with_permit("HubClear", valid_until=datetime.date(2027, 9, 30))
        confirm_medical_permit(
            member.medical_permit, actor=User.objects.create_user(username="hub-clear")
        )
        resp = c.post(
            self._hub_action_url(member.guardian),
            {"action": "clear_medical_permit_confirmation", "member_id": member.pk},
        )
        assert resp.status_code == 302

        permit = MedicalPermit.objects.get(member=member)
        assert permit.confirmed_by_id is None
        assert permit.confirmed_at is None

    def test_hub_staff_upload_replaces(self, monkeypatch):
        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 7, 1)
        c = _staff_client()
        member = _member_with_permit("HubUpload", valid_until=datetime.date(2027, 9, 30))
        old_name = member.medical_permit.file.name
        resp = c.post(
            self._hub_action_url(member.guardian),
            {
                "action": "medical_permit_upload",
                "member_id": member.pk,
                "medical_permit_file": _upload("hub-staff.pdf"),
            },
        )
        assert resp.status_code == 302

        permit = MedicalPermit.objects.get(member=member)
        assert permit.file.name != old_name
        assert permit.source == "staff_upload"
        assert permit.original_filename == "hub-staff.pdf"