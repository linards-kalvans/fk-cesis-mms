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

All fixtures use P1 field names (member_*, guardian_declared_address,
guardian_identity_document, member_identity_document, member_portrait,
kit sizes).
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from unittest.mock import patch

from apps.accounts.models import ParentAccount
from apps.members.models import KitSizeOption, Guardian, Member
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    create_or_update_draft,
    submit_application,
    request_application_fix,
    reject_application,
    approve_application,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Module-level fixture: kit size options required for submit
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_kit_sizes(db):
    """Ensure KitSizeOption records (S and M for both kinds) exist for every test."""
    for kind in (KitSizeOption.Kind.SHIRT, KitSizeOption.Kind.SHORTS):
        for label in ("S", "M"):
            KitSizeOption.objects.get_or_create(
                kind=kind,
                label=label,
                defaults={"is_active": True},
            )


# ---------------------------------------------------------------------------
# Module-level helpers (only those still needed by tests not yet on fixtures)
# ---------------------------------------------------------------------------


def _make_png(name="doc.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _create_staff_user(username="staff", email="staff@example.com"):
    """Create a Django superuser for staff-only access."""
    return User.objects.create_superuser(
        username=username,
        email=email,
        password="staffpass",
    )


def _create_submitted_app(email="review@example.com"):
    """Create and submit a RegistrationApplication with verified_account.

    Used by tests that need an isolated submitted app without touching the
    shared submitted_application fixture (e.g. anonymous-redirect tests that
    must not share state with the fixture's parent_account).
    """
    shirt = KitSizeOption.objects.get(kind=KitSizeOption.Kind.SHIRT, label="S")
    shorts = KitSizeOption.objects.get(kind=KitSizeOption.Kind.SHORTS, label="S")

    acct = ParentAccount.objects.create(email=email, phone="+37111111111")

    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Review Guardian",
            "guardian_personal_id": "010101-11111",
            "guardian_phone": "+37122222222",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Child Review",
            "member_personal_id": "010125-11111",
            "member_birth_date": "2025-01-01",
            "member_actual_address": "Riga 1",
            "member_same_address_as_guardian": True,
            "member_kit_size_shirt": shirt.pk,
            "member_kit_size_shorts": shorts.pk,
            "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
            "support_club_instead_of_multi_child_discount": False,
        },
        files={
            "guardian_identity_document": _make_png("guardian_id.png"),
            "member_identity_document": _make_png("member_id.png"),
            "member_portrait_document": _make_png("portrait.png"),
        },
        verified_account=acct,
    )
    submit_application(app, acct)
    return app


# Detail URL template — same pattern as urls.py admin-review-detail
_DETAIL_URL = "/admin/review/applications/{pk}/"


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
        resp = client.get(_DETAIL_URL.format(pk=app.pk), follow=False)
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
        resp = client.get(_DETAIL_URL.format(pk=app.pk), follow=False)
        assert resp.status_code == 404, (
            f"Expected 404 for non-staff on detail, got {resp.status_code}."
        )


# ---------------------------------------------------------------------------
# 3. Staff queue lists only submitted applications
# ---------------------------------------------------------------------------


class TestStaffReviewQueue:
    """Staff user sees only submitted applications in the queue."""

    def test_queue_lists_only_submitted_applications(
        self, staff_client, submitted_application
    ):
        """Queue must only show applications with status=submitted."""
        # Draft app (should NOT appear in queue)
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
                "guardian_declared_address": "Riga 2",
                "member_full_name": "Child QueueDraft",
                "member_personal_id": "010125-22222",
                "member_birth_date": "2025-02-01",
                "member_actual_address": "Riga 2",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHIRT, label="M",
                ).pk,
                "member_kit_size_shorts": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHORTS, label="M",
                ).pk,
                "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
                "support_club_instead_of_multi_child_discount": False,
            },
            files={},
            verified_account=draft_acct,
        )

        # Fix-requested app (should NOT appear in queue)
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
                "guardian_declared_address": "Riga 3",
                "member_full_name": "Child QueueFix",
                "member_personal_id": "010125-33333",
                "member_birth_date": "2025-03-01",
                "member_actual_address": "Riga 3",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHIRT, label="S",
                ).pk,
                "member_kit_size_shorts": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHORTS, label="S",
                ).pk,
                "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
                "support_club_instead_of_multi_child_discount": False,
            },
            files={
                "guardian_identity_document": _make_png("fix_g.png"),
                "member_identity_document": _make_png("fix_m.png"),
                "member_portrait_document": _make_png("fix_p.png"),
            },
            verified_account=fix_acct,
        )
        submit_application(fix_app, fix_acct)
        fix_app.status = RegistrationApplication.Status.FIX_REQUESTED
        fix_app.save(update_fields=["status"])

        resp = staff_client.get("/admin/review/applications/")
        assert resp.status_code == 200, (
            f"Expected 200 for staff queue, got {resp.status_code}."
        )
        content = resp.content.decode()
        # submitted_application uses "Submit Child" as member_full_name (from submit_payload)
        assert "Submit Child" in content, "Submitted app child name must appear in queue."
        assert "Child QueueDraft" not in content, "Draft app must not appear in queue."
        assert "Child QueueFix" not in content, "Fix-requested app must not appear in queue."


# ---------------------------------------------------------------------------
# 4. Staff detail page — child name, controls, document link
# ---------------------------------------------------------------------------


class TestStaffReviewDetailPage:
    """Staff detail page must show child name, review controls, and document preview."""

    def test_detail_page_shows_child_name(self, staff_client, submitted_application):
        """Detail page must display the child's full name."""
        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200, (
            f"Expected 200 for staff detail, got {resp.status_code}."
        )
        assert submitted_application.member_full_name in resp.content.decode(), (
            "Detail page must show child full name."
        )

    @pytest.mark.parametrize(
        "marker",
        [
            'value="approve"',
            'value="request_fix"',
            'value="reject"',
            "priekšskatījums",  # Latvian word in the document preview link text
        ],
    )
    def test_detail_page_renders_marker(
        self, staff_client, submitted_application, marker
    ):
        """Detail page must render the expected control or document preview marker."""
        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        assert marker in resp.content.decode(), (
            f"Detail page must contain marker: {marker!r}"
        )


# ---------------------------------------------------------------------------
# 5. Request fix action — requires message, changes status
# ---------------------------------------------------------------------------


class TestRequestFixAction:
    """Request fix must require a message and change status to fix_requested."""

    def test_request_fix_requires_message(self, staff_client, submitted_application):
        """POST request_fix without a message must fail (not change status)."""
        resp = staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={"action": "request_fix"},
            follow=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for request_fix without message, got {resp.status_code}."
        )
        submitted_application.refresh_from_db()
        assert submitted_application.status == RegistrationApplication.Status.SUBMITTED, (
            "Status must remain submitted when fix request has no message."
        )

    def test_request_fix_changes_status(self, staff_client, submitted_application):
        """POST request_fix with a message must set status=fix_requested."""
        resp = staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={
                "action": "request_fix",
                "review_message": "Please correct the personal ID format.",
            },
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect after fix request, got {resp.status_code}."
        )
        submitted_application.refresh_from_db()
        assert submitted_application.status == RegistrationApplication.Status.FIX_REQUESTED, (
            f"Status must be fix_requested, got {submitted_application.status}."
        )

    def test_request_fix_stores_message_and_reviewer(
        self, staff_client, submitted_application
    ):
        """Request fix must store review_message, reviewed_by, reviewed_at."""
        staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={
                "action": "request_fix",
                "review_message": "Fix the address field.",
            },
            follow=False,
        )
        submitted_application.refresh_from_db()
        assert submitted_application.review_message == "Fix the address field.", (
            "review_message must be stored."
        )
        staff_user = User.objects.get(username="staff")
        assert submitted_application.reviewed_by_id == staff_user.pk, (
            "reviewed_by must be set to the staff user."
        )
        assert submitted_application.reviewed_at is not None, (
            "reviewed_at must be set."
        )


# ---------------------------------------------------------------------------
# 6. Reject action — requires message, changes status
# ---------------------------------------------------------------------------


class TestRejectAction:
    """Reject must require a message and change status to rejected."""

    def test_reject_requires_message(self, staff_client, submitted_application):
        """POST reject without a message must fail."""
        resp = staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={"action": "reject"},
            follow=False,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for reject without message, got {resp.status_code}."
        )
        submitted_application.refresh_from_db()
        assert submitted_application.status == RegistrationApplication.Status.SUBMITTED, (
            "Status must remain submitted when reject has no message."
        )

    def test_reject_changes_status(self, staff_client, submitted_application):
        """POST reject with a message must set status=rejected."""
        resp = staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={
                "action": "reject",
                "review_message": "Application incomplete.",
            },
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect after reject, got {resp.status_code}."
        )
        submitted_application.refresh_from_db()
        assert submitted_application.status == RegistrationApplication.Status.REJECTED, (
            f"Status must be rejected, got {submitted_application.status}."
        )

    def test_reject_stores_message_and_reviewer(
        self, staff_client, submitted_application
    ):
        """Reject must store review_message, reviewed_by, reviewed_at."""
        staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={
                "action": "reject",
                "review_message": "Duplicate application.",
            },
            follow=False,
        )
        submitted_application.refresh_from_db()
        assert submitted_application.review_message == "Duplicate application.", (
            "review_message must be stored on reject."
        )
        staff_user = User.objects.get(username="staff")
        assert submitted_application.reviewed_by_id == staff_user.pk, (
            "reviewed_by must be set on reject."
        )


# ---------------------------------------------------------------------------
# 7. Approve action — creates guardian/member, redirects
# ---------------------------------------------------------------------------


class TestApproveAction:
    """Approve must create Guardian + Member and set approved_member."""

    def test_approve_changes_status_and_creates_member(
        self, staff_client, submitted_application
    ):
        """Approve must set status=approved and link approved_member."""
        resp = staff_client.post(
            _DETAIL_URL.format(pk=submitted_application.pk),
            data={"action": "approve"},
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Expected 302 redirect after approve, got {resp.status_code}."
        )
        submitted_application.refresh_from_db()
        assert submitted_application.status == RegistrationApplication.Status.APPROVED, (
            f"Status must be approved, got {submitted_application.status}."
        )
        assert submitted_application.approved_member_id is not None, (
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
                "guardian_declared_address": "Riga 4",
                "member_full_name": "Child FixOnFix",
                "member_personal_id": "010125-44444",
                "member_birth_date": "2025-04-01",
                "member_actual_address": "Riga 4",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHIRT, label="S",
                ).pk,
                "member_kit_size_shorts": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHORTS, label="S",
                ).pk,
                "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
                "support_club_instead_of_multi_child_discount": False,
            },
            files={
                "guardian_identity_document": _make_png("ff_g.png"),
                "member_identity_document": _make_png("ff_m.png"),
                "member_portrait_document": _make_png("ff_p.png"),
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
            _DETAIL_URL.format(pk=app.pk),
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
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child RejectApproved",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-05-01",
                "member_actual_address": "Riga 5",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHIRT, label="M",
                ).pk,
                "member_kit_size_shorts": KitSizeOption.objects.get(
                    kind=KitSizeOption.Kind.SHORTS, label="M",
                ).pk,
                "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
                "support_club_instead_of_multi_child_discount": False,
            },
            files={
                "guardian_identity_document": _make_png("ra_g.png"),
                "member_identity_document": _make_png("ra_m.png"),
                "member_portrait_document": _make_png("ra_p.png"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = _create_staff_user(username="staff2", email="staff2@example.com")
        approve_application(app, staff_user)

        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            _DETAIL_URL.format(pk=app.pk),
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

    def test_admin_changelist_has_review_link(self, staff_client, submitted_application):
        """Admin RegistrationApplication changelist must link to review detail."""
        resp = staff_client.get("/admin/registrations/registrationapplication/")
        assert resp.status_code == 200, (
            f"Expected 200 on admin changelist, got {resp.status_code}."
        )
        content = resp.content.decode()
        assert f"/admin/review/applications/{submitted_application.pk}/" in content, (
            "Admin changelist must link to custom review detail page."
        )


# ---------------------------------------------------------------------------
# 10. Email notifications on review actions
# ---------------------------------------------------------------------------


class TestEmailOnReviewActions:
    """Review actions (fix, reject, approve) must send email to the parent."""

    def test_request_fix_sends_email(self, submitted_application):
        """request_application_fix must send an email to the parent."""
        staff_user = User.objects.create_superuser(
            username="fixstaff",
            email="fixstaff@example.com",
            password="fixstaffpass",
        )
        with patch("apps.registrations.services.send_mail") as mock_send:
            request_application_fix(submitted_application, staff_user, "Please fix the address.")
            assert mock_send.call_count >= 1

    def test_reject_sends_email(self, submitted_application):
        """reject_application must send an email to the parent."""
        staff_user = User.objects.create_superuser(
            username="rejectstaff",
            email="rejectstaff@example.com",
            password="rejectstaffpass",
        )
        with patch("apps.registrations.services.send_mail") as mock_send:
            reject_application(submitted_application, staff_user, "Does not meet requirements.")
            assert mock_send.call_count >= 1

    def test_approve_sends_email(self, submitted_application):
        """approve_application must send an approval email to the parent."""
        staff_user = User.objects.create_superuser(
            username="approvestaff",
            email="approvestaff@example.com",
            password="approvestaffpass",
        )
        with patch("apps.registrations.services.send_mail") as mock_send:
            approve_application(submitted_application, staff_user)
            assert mock_send.call_count >= 1


# ---------------------------------------------------------------------------
# 11. Admin readonly — consent stamp fields must not be editable
# ---------------------------------------------------------------------------


def test_admin_consent_fields_are_readonly():
    """Admin must not allow staff to edit consent timestamps directly."""
    from apps.registrations.admin import RegistrationApplicationAdmin

    readonly = set(RegistrationApplicationAdmin.readonly_fields)
    assert "personal_data_consent_at" in readonly
    assert "personal_data_consent_version" in readonly
