"""Staff review queue and detail views — RED phase.

Covers:
- Anonymous users redirected to /admin/login/
- Authenticated non-staff users get 404
- Queue lists only submitted applications
- POST from detail page can request fix (requires message)
- Reject requires message
- Approve action
- Detail page shows child name, review controls, document preview link
- Django admin changelist shows link to custom review detail page
- Email sent on fix/reject/approve actions

Parent-account setup: all drafts are created with verified_account=acct
so submit_application(app, acct) is valid (the app's parent_account FK
matches the acct passed to submit).
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from unittest.mock import patch

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_via_magic_link(client, account):
    """Convenience: issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_child_identity_file(name="id.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _create_staff_user():
    """Create a Django superuser for staff-only access."""
    return User.objects.create_superuser(
        username="staff",
        email="staff@example.com",
        password="staffpass",
    )


def _create_submitted_app(email="review@example.com"):
    """Create and submit a RegistrationApplication with verified_account.

    Pattern: create ParentAccount first, then pass verified_account=acct
    into create_or_update_draft, then call submit_application(app, acct).
    """
    from apps.registrations.services import create_or_update_draft, submit_application

    acct = ParentAccount.objects.create(
        email=email,
        phone="+37111111111",
    )
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Review Guardian",
            "guardian_personal_id": "010101-11111",
            "guardian_phone": "+37122222222",
            "guardian_address": "Riga 1",
            "child_full_name": "Child Review",
            "child_personal_id": "010125-11111",
            "child_birth_date": "2025-01-01",
        },
        files={
            "child_identity_document": _make_child_identity_file("id.jpg"),
        },
        verified_account=acct,
    )
    submit_application(app, acct)
    return app


# ---------------------------------------------------------------------------
# 1. Anonymous access — redirect to admin login
# ---------------------------------------------------------------------------


class TestAnonymousAccessReviewQueue:
    """Anonymous users must be redirected to /admin/login/ on review queue."""

    def test_anonymous_get_queue_redirected_to_admin_login(self):
        """GET /admin/review/applications/ must redirect anonymous to admin login."""
        client = Client()
        resp = client.get("/admin/review/applications/", follow=False)
        assert resp.status_code == 302, (
            f"Expected 302 redirect for anonymous, got {resp.status_code}."
        )
        assert "/admin/login/" in resp.url, (
            f"Expected redirect to /admin/login/, got {resp.url}."
        )

    def test_anonymous_get_detail_redirected_to_admin_login(self):
        """GET /admin/review/applications/<id>/ must redirect anonymous to admin login."""
        app = _create_submitted_app("anonredir@example.com")
        client = Client()
        resp = client.get(f"/admin/review/applications/{app.pk}/", follow=False)
        assert resp.status_code == 302, (
            f"Expected 302 redirect for anonymous, got {resp.status_code}."
        )
        assert "/admin/login/" in resp.url, (
            f"Expected redirect to /admin/login/, got {resp.url}."
        )


# ---------------------------------------------------------------------------
# 2. Non-staff access — 404
# ---------------------------------------------------------------------------


class TestNonStaffAccessReviewQueue:
    """Authenticated non-staff users must get 404 on review queue."""

    def test_non_staff_get_queue_returns_404(self):
        """Logged-in non-staff user gets 404 on review queue."""
        _create_submitted_app("nonstaff@example.com")
        staff_user = User.objects.create_user(
            username="regular",
            email="regular@example.com",
            password="regularpass",
        )
        client = Client()
        client.force_login(staff_user)
        resp = client.get("/admin/review/applications/", follow=False)
        assert resp.status_code == 404, (
            f"Expected 404 for non-staff, got {resp.status_code}."
        )

    def test_non_staff_get_detail_returns_404(self):
        """Logged-in non-staff user gets 404 on review detail."""
        app = _create_submitted_app("nonstaffdetail@example.com")
        staff_user = User.objects.create_user(
            username="regular2",
            email="regular2@example.com",
            password="regular2pass",
        )
        client = Client()
        client.force_login(staff_user)
        resp = client.get(f"/admin/review/applications/{app.pk}/", follow=False)
        assert resp.status_code == 404, (
            f"Expected 404 for non-staff on detail, got {resp.status_code}."
        )


# ---------------------------------------------------------------------------
# 3. Staff queue lists only submitted applications
# ---------------------------------------------------------------------------


class TestStaffReviewQueue:
    """Staff user sees only submitted applications in the queue."""

    def test_queue_lists_only_submitted_applications(self):
        """Queue must only show applications with status=submitted."""
        from apps.registrations.services import create_or_update_draft, submit_application

        # Create a submitted app (verified_account pattern)
        submitted_acct = ParentAccount.objects.create(
            email="queued@example.com",
            phone="+37111111111",
        )
        submitted_app = create_or_update_draft(
            data={
                "guardian_email": "queued@example.com",
                "guardian_full_name": "Queue Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child Review",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id.jpg"),
            },
            verified_account=submitted_acct,
        )
        submit_application(submitted_app, submitted_acct)

        # Create a draft app (should NOT appear in queue)
        draft_acct = ParentAccount.objects.create(
            email="queuedraft@example.com",
            phone="+37133333333",
        )
        draft_app = create_or_update_draft(
            data={
                "guardian_email": "queuedraft@example.com",
                "guardian_full_name": "Queue Draft",
                "guardian_personal_id": "010101-22222",
                "guardian_phone": "+37144444444",
                "guardian_address": "Riga 2",
                "child_full_name": "Child QueueDraft",
                "child_personal_id": "010125-22222",
                "child_birth_date": "2025-02-01",
            },
            files={},
            verified_account=draft_acct,
        )

        # Create a fix_requested app (should NOT appear in queue)
        fix_acct = ParentAccount.objects.create(
            email="queuefix@example.com",
            phone="+37155555555",
        )
        fix_app = create_or_update_draft(
            data={
                "guardian_email": "queuefix@example.com",
                "guardian_full_name": "Queue Fix",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37166666666",
                "guardian_address": "Riga 3",
                "child_full_name": "Child QueueFix",
                "child_personal_id": "010125-33333",
                "child_birth_date": "2025-03-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id2.jpg"),
            },
            verified_account=fix_acct,
        )
        submit_application(fix_app, fix_acct)
        fix_app.status = RegistrationApplication.Status.FIX_REQUESTED
        fix_app.save(update_fields=["status"])

        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.get("/admin/review/applications/")
        assert resp.status_code == 200, (
            f"Expected 200 for staff queue, got {resp.status_code}."
        )
        content = resp.content.decode()
        assert "Child Review" in content, "Submitted app child name must appear in queue."
        assert "Child QueueDraft" not in content, "Draft app must not appear in queue."
        assert "Child QueueFix" not in content, "Fix-requested app must not appear in queue."


# ---------------------------------------------------------------------------
# 4. Staff detail page — child name, controls, document link
# ---------------------------------------------------------------------------


class TestStaffReviewDetailPage:
    """Staff detail page must show child name, review controls, and document preview."""

    def test_detail_page_shows_child_name(self):
        """Detail page must display the child's full name."""
        app = _create_submitted_app("detailchild@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")
        assert resp.status_code == 200, (
            f"Expected 200 for staff detail, got {resp.status_code}."
        )
        content = resp.content.decode()
        assert "Child Review" in content, (
            "Detail page must show child full name."
        )

    def test_detail_page_has_request_fix_button(self):
        """Detail page must have a request-fix control/button."""
        app = _create_submitted_app("detailfix@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        has_fix_control = (
            "fix" in content.lower()
            or "labot" in content.lower()
            or "request_fix" in content.lower()
        )
        assert has_fix_control, (
            "Detail page must show a request-fix control."
        )

    def test_detail_page_has_reject_button(self):
        """Detail page must have a reject control/button."""
        app = _create_submitted_app("detailreject@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        has_reject_control = (
            "reject" in content.lower()
            or "noraidit" in content.lower()
        )
        assert has_reject_control, (
            "Detail page must show a reject control."
        )

    def test_detail_page_has_approve_button(self):
        """Detail page must have an approve control/button."""
        app = _create_submitted_app("detailapprove@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        has_approve_control = (
            "approve" in content.lower()
            or "apstiprinat" in content.lower()
        )
        assert has_approve_control, (
            "Detail page must show an approve control."
        )

    def test_detail_page_has_document_preview_link(self):
        """Detail page must include a link to preview the identity document."""
        app = _create_submitted_app("detaildoc@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        has_doc_link = (
            "preview" in content.lower()
            or "document" in content.lower()
            or "/admin/documents/" in content.lower()
        )
        assert has_doc_link, (
            "Detail page must include a document preview link."
        )


# ---------------------------------------------------------------------------
# 5. Request fix action — requires message, changes status
# ---------------------------------------------------------------------------


class TestRequestFixAction:
    """Request fix must require a message and change status to fix_requested."""

    def test_request_fix_requires_message(self):
        """POST request_fix without a message must fail (not change status)."""
        app = _create_submitted_app("fixmsg@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={"action": "request_fix"},
            follow=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for request_fix without message, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.SUBMITTED, (
            "Status must remain submitted when fix request has no message."
        )

    def test_request_fix_changes_status(self):
        """POST request_fix with a message must set status=fix_requested."""
        app = _create_submitted_app("fixstatus@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={
                "action": "request_fix",
                "review_message": "Please correct the personal ID format.",
            },
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect after fix request, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.FIX_REQUESTED, (
            f"Status must be fix_requested, got {app.status}."
        )

    def test_request_fix_stores_message_and_reviewer(self):
        """Request fix must store review_message, reviewed_by, reviewed_at."""
        app = _create_submitted_app("fixmeta@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        client.post(
            f"/admin/review/applications/{app.pk}/",
            data={
                "action": "request_fix",
                "review_message": "Fix the address field.",
            },
            follow=False,
        )
        app.refresh_from_db()
        assert app.review_message == "Fix the address field.", (
            "review_message must be stored."
        )
        assert app.reviewed_by_id == staff_user.pk, (
            "reviewed_by must be set to the staff user."
        )
        assert app.reviewed_at is not None, (
            "reviewed_at must be set."
        )


# ---------------------------------------------------------------------------
# 6. Reject action — requires message, changes status
# ---------------------------------------------------------------------------


class TestRejectAction:
    """Reject must require a message and change status to rejected."""

    def test_reject_requires_message(self):
        """POST reject without a message must fail."""
        app = _create_submitted_app("rejectmsg@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={"action": "reject"},
            follow=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for reject without message, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.SUBMITTED, (
            "Status must remain submitted when reject has no message."
        )

    def test_reject_changes_status(self):
        """POST reject with a message must set status=rejected."""
        app = _create_submitted_app("rejectstatus@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={
                "action": "reject",
                "review_message": "Application incomplete.",
            },
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect after reject, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.REJECTED, (
            f"Status must be rejected, got {app.status}."
        )

    def test_reject_stores_message_and_reviewer(self):
        """Reject must store review_message, reviewed_by, reviewed_at."""
        app = _create_submitted_app("rejectmeta@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        client.post(
            f"/admin/review/applications/{app.pk}/",
            data={
                "action": "reject",
                "review_message": "Duplicate application.",
            },
            follow=False,
        )
        app.refresh_from_db()
        assert app.review_message == "Duplicate application.", (
            "review_message must be stored on reject."
        )
        assert app.reviewed_by_id == staff_user.pk, (
            "reviewed_by must be set on reject."
        )


# ---------------------------------------------------------------------------
# 7. Approve action — creates guardian/member, redirects
# ---------------------------------------------------------------------------


class TestApproveAction:
    """Approve must create Guardian + Member and set approved_member."""

    def test_approve_changes_status_and_creates_member(self):
        """Approve must set status=approved and link approved_member."""
        from apps.members.models import Guardian, Member

        app = _create_submitted_app("approveaction@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={"action": "approve"},
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect after approve, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.APPROVED, (
            f"Status must be approved, got {app.status}."
        )
        assert app.approved_member_id is not None, (
            "approved_member must be set."
        )
        assert Guardian.objects.count() >= 1, "Must create at least one Guardian."
        assert Member.objects.count() >= 1, "Must create at least one Member."


# ---------------------------------------------------------------------------
# 8. Review actions only allowed from submitted status
# ---------------------------------------------------------------------------


class TestReviewActionsFromSubmittedOnly:
    """Review actions (fix, reject, approve) must only be allowed from submitted."""

    def test_request_fix_on_fix_requested_application_fails(self):
        """Cannot request fix on an already fix_requested application."""
        from apps.registrations.services import create_or_update_draft, submit_application

        fix_acct = ParentAccount.objects.create(
            email="fixonfix@example.com",
            phone="+37144444444",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "fixonfix@example.com",
                "guardian_full_name": "Fix On Fix",
                "guardian_personal_id": "010101-44444",
                "guardian_phone": "+37155555555",
                "guardian_address": "Riga 4",
                "child_full_name": "Child FixOnFix",
                "child_personal_id": "010125-44444",
                "child_birth_date": "2025-04-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id4.jpg"),
            },
            verified_account=fix_acct,
        )
        submit_application(app, fix_acct)
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.save(update_fields=["status"])

        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={
                "action": "request_fix",
                "review_message": "Another fix.",
            },
            follow=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for fix on fix_requested, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.FIX_REQUESTED, (
            "Status must remain fix_requested."
        )

    def test_reject_on_approved_application_fails(self):
        """Cannot reject an already approved application."""
        from apps.registrations.services import (
            create_or_update_draft,
            submit_application,
            approve_application,
        )

        acct = ParentAccount.objects.create(
            email="rejectapproved@example.com",
            phone="+37166666666",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "rejectapproved@example.com",
                "guardian_full_name": "Reject Approved",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37177777777",
                "guardian_address": "Riga 5",
                "child_full_name": "Child RejectApproved",
                "child_personal_id": "010125-55555",
                "child_birth_date": "2025-05-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id5.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = _create_staff_user()
        approve_application(app, staff_user)

        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/admin/review/applications/{app.pk}/",
            data={
                "action": "reject",
                "review_message": "Too late.",
            },
            follow=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for reject on approved, got {resp.status_code}."
        )
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.APPROVED, (
            "Status must remain approved."
        )


# ---------------------------------------------------------------------------
# 9. Django admin integration — changelist link to review page
# ---------------------------------------------------------------------------


class TestDjangoAdminIntegration:
    """Admin changelist must show link to custom review detail page."""

    def test_admin_changelist_has_review_link(self):
        """Admin RegistrationApplication changelist must link to review detail."""
        app = _create_submitted_app("adminlink@example.com")
        staff_user = _create_staff_user()
        client = Client()
        client.force_login(staff_user)

        # Access the admin changelist for RegistrationApplication
        resp = client.get("/admin/registrations/registrationapplication/")
        assert resp.status_code == 200, (
            f"Expected 200 on admin changelist, got {resp.status_code}."
        )
        content = resp.content.decode()
        # The changelist must contain a link to the custom review detail page
        assert f"/admin/review/applications/{app.pk}/" in content, (
            "Admin changelist must link to custom review detail page."
        )


# ---------------------------------------------------------------------------
# 10. Email notifications on review actions
# ---------------------------------------------------------------------------


class TestEmailOnReviewActions:
    """Review actions (fix, reject, approve) must send email to the parent."""

    def test_request_fix_sends_email(self):
        """request_application_fix must send an email to the parent."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = ParentAccount.objects.create(
            email="fixemail@example.com",
            phone="+37134343434",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "fixemail@example.com",
                "guardian_full_name": "Fix Email Guardian",
                "guardian_personal_id": "010101-34343",
                "guardian_phone": "+37145454545",
                "guardian_address": "Riga 34",
                "child_full_name": "Child FixEmail",
                "child_personal_id": "010125-34343",
                "child_birth_date": "2025-07-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id8.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = User.objects.create_superuser(
            username="fixstaff",
            email="fixstaff@example.com",
            password="fixstaffpass",
        )

        from apps.registrations.services import request_application_fix

        with patch("apps.registrations.services.send_mail") as mock_send:
            request_application_fix(app, staff_user, "Please fix the address.")
            assert mock_send.call_count >= 1

    def test_reject_sends_email(self):
        """reject_application must send an email to the parent."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = ParentAccount.objects.create(
            email="rejectemail@example.com",
            phone="+37156565656",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "rejectemail@example.com",
                "guardian_full_name": "Reject Email Guardian",
                "guardian_personal_id": "010101-56565",
                "guardian_phone": "+37167676767",
                "guardian_address": "Riga 56",
                "child_full_name": "Child RejectEmail",
                "child_personal_id": "010125-56565",
                "child_birth_date": "2025-08-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id9.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = User.objects.create_superuser(
            username="rejectstaff",
            email="rejectstaff@example.com",
            password="rejectstaffpass",
        )

        from apps.registrations.services import reject_application

        with patch("apps.registrations.services.send_mail") as mock_send:
            reject_application(app, staff_user, "Does not meet requirements.")
            assert mock_send.call_count >= 1

    def test_approve_sends_email(self):
        """approve_application must send an approval email to the parent."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = ParentAccount.objects.create(
            email="approveemail@example.com",
            phone="+37178787878",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "approveemail@example.com",
                "guardian_full_name": "Approve Email Guardian",
                "guardian_personal_id": "010101-78787",
                "guardian_phone": "+37189898989",
                "guardian_address": "Riga 78",
                "child_full_name": "Child ApproveEmail",
                "child_personal_id": "010125-78787",
                "child_birth_date": "2025-09-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id10.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = User.objects.create_superuser(
            username="approvestaff",
            email="approvestaff@example.com",
            password="approvestaffpass",
        )

        from apps.registrations.services import approve_application

        with patch("apps.registrations.services.send_mail") as mock_send:
            approve_application(app, staff_user)
            assert mock_send.call_count >= 1
