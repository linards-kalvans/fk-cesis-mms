"""P23 — parent-flow endpoints and surfaces for MedicalPermit.

Registrations namespace routes covered here:
- ``registrations:application-medical-permit-upload``  — POST, ownership-scoped,
  allowed on submitted applications (no submit/approval gate).
- ``registrations:member-medical-permit-upload``       — POST, guardian owner only.
- ``registrations:medical-permit-preview`` / ``-download`` — GET, guardian only;
  streaming + denial matrix live in ``test_medical_permit_access.py``.

Surface contract: the application workspace renders the application upload
control; the portal renders per-approved-child permit status, the member
upload control, an August-starting expiry warning, and — for a
confirmation-only permit — no file links.

The medical-permit implementation does not exist yet; model/service imports
live inside test bodies so collection succeeds and each test fails at run
time with the feature-missing signal (ImportError / NoReverseMatch).
"""

from __future__ import annotations

import datetime

import pytest

pytestmark = pytest.mark.django_db


def _upload(name="permit.pdf", content_type="application/pdf"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name=name, content=b"%PDF-1.4 flow", content_type=content_type
    )


def _freeze(monkeypatch, year, month, day):
    import django.utils.timezone as timezone_module

    def _localdate():
        return datetime.date(year, month, day)

    monkeypatch.setattr(timezone_module, "localdate", _localdate)


def _app_for(account, *, status="draft", member_name="Flow Child"):
    from apps.registrations.models import RegistrationApplication

    return RegistrationApplication.objects.create(
        parent_account=account,
        claimed_email=account.email,
        status=status,
        member_full_name=member_name,
    )


def _permit(app, *, with_file=True, confirmed=False, member=None,
            valid_until=datetime.date(2026, 9, 30)):
    from django.contrib.auth.models import User

    from apps.documents.models import MedicalPermit

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
    if confirmed:
        staff = User.objects.create_user(username="flow-confirmer")
        kwargs.update(
            confirmed_by=staff,
            confirmed_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
        )
    if member is not None:
        kwargs["member"] = member
    return MedicalPermit.objects.create(**kwargs)


def _approve(app):
    from django.contrib.auth.models import User

    from apps.registrations.services import approve_application

    return approve_application(app, User.objects.create_user(username="flow-approver"))


def _approved_family(parent_account, make_guardian):
    """Guardian + submitted application + permit; returns (app, member, permit)
    after real approval attachment runs."""
    guardian = make_guardian(parent_account, full_name="Flow Guardian")
    app = _app_for(parent_account, status="submitted")
    app.guardian = guardian
    app.save(update_fields=["guardian"])
    permit = _permit(app)
    member = _approve(app).approved_member
    permit.refresh_from_db()
    return app, member, permit


# ---------------------------------------------------------------------------
# application-medical-permit-upload
# ---------------------------------------------------------------------------


class TestApplicationPermitUpload:
    def test_owner_can_upload_on_draft(
        self, monkeypatch, verified_client, parent_account
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 1, 15)
        app = _app_for(parent_account)
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 201
        permit = app.medical_permit
        assert permit.source == "parent_upload"
        assert permit.file != ""
        # Recorded in 2026 → valid through 30 September 2027.
        assert permit.valid_until == datetime.date(2027, 9, 30)

    def test_owner_can_upload_on_submitted(self, verified_client, parent_account):
        """No submit gate: a submitted application still accepts an upload."""
        from django.urls import reverse

        app = _app_for(parent_account, status="submitted")
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 201
        app.refresh_from_db()
        assert app.status == "submitted"

    def test_cross_family_upload_refused(self, other_verified_client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account)
        response = other_verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 404

    def test_anonymous_upload_refused(self, client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account)
        response = client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code in (302, 404)
        assert response.status_code != 201

    def test_workspace_renders_upload_control(self, verified_client, parent_account):
        """The parent workspace for an editable draft shows the upload control."""
        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            in html
        )


# ---------------------------------------------------------------------------
# member-medical-permit-upload
# ---------------------------------------------------------------------------


class TestMemberPermitUpload:
    def test_guardian_owner_can_replace_member_permit(
        self, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _app, member, permit = _approved_family(parent_account, make_guardian)
        old_name = permit.file.name

        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("replacement.pdf")},
        )

        assert response.status_code == 201
        permit.refresh_from_db()
        assert permit.file.name != old_name
        assert permit.original_filename == "replacement.pdf"
        assert permit.member_id == member.pk
        assert permit.application_id == _app.pk  # traceability retained

    def test_cross_family_member_upload_refused(
        self, other_verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _app, member, _permit = _approved_family(parent_account, make_guardian)
        response = other_verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 404

    def test_anonymous_member_upload_refused(self, client, parent_account, make_guardian):
        from django.urls import reverse

        _app, member, _permit = _approved_family(parent_account, make_guardian)
        response = client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload()},
        )

        assert response.status_code in (302, 404)
        assert response.status_code != 201

    def test_guardian_can_upload_first_permit_after_approval(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        """An approved child may have no permit (approval never requires one);
        the owning parent can still upload the first permit via the member
        route — a new record linked to both the source application and the
        approved member."""
        from django.urls import reverse

        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 3, 10)
        guardian = make_guardian(parent_account, full_name="Flow Guardian")
        app = _app_for(parent_account, status="submitted")
        app.guardian = guardian
        app.save(update_fields=["guardian"])
        member = _approve(app).approved_member
        assert not MedicalPermit.objects.filter(member=member).exists()

        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("first.pdf")},
        )

        assert response.status_code == 201
        permit = MedicalPermit.objects.get(member=member)
        assert permit.application_id == app.pk  # traceability retained
        assert permit.source == "parent_upload"
        # Uploaded in 2026 → valid through 30 September 2027.
        assert permit.valid_until == datetime.date(2027, 9, 30)


# ---------------------------------------------------------------------------
# Portal surface: status, warning, confirmation-only, upload control
# ---------------------------------------------------------------------------


class TestPortalSurface:
    def test_portal_shows_permit_status_for_approved_child(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 8, 1)
        _app, member, _permit = _approved_family(parent_account, make_guardian)

        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        # 2026-08-01 with valid_until 2026-09-30 → expiring.
        assert 'data-medical-permit-status="expiring"' in html
        # The approved child's portal card offers the member upload control.
        assert (
            reverse("registrations:member-medical-permit-upload", args=[member.pk])
            in html
        )

    def test_portal_has_no_warning_before_august(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 7, 31)
        _app, _member, _permit = _approved_family(parent_account, make_guardian)

        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode()
        assert "data-medical-permit-warning" not in html

    def test_portal_warning_begins_on_first_august(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 8, 1)
        _app, _member, _permit = _approved_family(parent_account, make_guardian)

        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode()
        assert "data-medical-permit-warning" in html

    def test_confirmation_only_portal_shows_state_without_file_links(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.contrib.auth.models import User

        from django.urls import reverse

        from apps.documents.medical_permits import confirm_medical_permit

        _freeze(monkeypatch, 2026, 8, 1)
        _app, member, permit = _approved_family(parent_account, make_guardian)
        confirm_medical_permit(
            permit, actor=User.objects.create_user(username="portal-confirmer")
        )
        assert permit.file == ""
        # Confirmed in 2026 → valid through 30 September 2027, so on 2026-08-01
        # the permit is current and no expiry warning shows.
        assert permit.valid_until == datetime.date(2027, 9, 30)

        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert 'data-medical-permit-status="current"' in html
        assert "data-medical-permit-warning" not in html
        # Confirmation-only: no preview/download file links anywhere on the page.
        assert reverse("registrations:medical-permit-preview", args=[permit.pk]) not in html
        assert reverse("registrations:medical-permit-download", args=[permit.pk]) not in html