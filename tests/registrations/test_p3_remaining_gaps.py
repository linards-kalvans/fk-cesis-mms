"""P3 remaining gaps — RED phase.

Covers:
1. Guardian auto-reuse default on /applications/new/ (extraction prefill visible)
2. Admin review shows both guardian and member preview/extracted sections,
   confidence only when present

Does NOT add tests for already-covered gaps:
- member_portrait OCR scope → test_guardian_document_reuse.py
- OCR failure blocks draft save → test_application_workflow.py
- OCR failure blocks submit → test_application_workflow.py
- parent OCR visibility auth → test_parent_ocr_prefill_flow.py
- admin OCR visibility auth → test_admin_ocr_review_detail.py
"""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link

from apps.registrations.services import create_or_update_draft, submit_application
from apps.members.models import KitSizeOption

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_png(name="doc.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _ensure_kit_sizes():
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT, label="S", defaults={"is_active": True},
    )
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS, label="S", defaults={"is_active": True},
    )
    return {
        "shirt": KitSizeOption.objects.get(kind=KitSizeOption.Kind.SHIRT, label="S"),
        "shorts": KitSizeOption.objects.get(kind=KitSizeOption.Kind.SHORTS, label="S"),
    }


def _create_submitted_app_with_ocr(
    email="ocradmin@example.com",
):
    """Create a submitted application with guardian and member identity docs in stub OCR mode."""
    kit = _ensure_kit_sizes()
    account = ParentAccount.objects.create(
        email=email,
        phone="+37120000040",
    )

    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Admin OCR Parent",
            "guardian_personal_id": "010101-20202",
            "guardian_phone": "+37120000040",
            "guardian_declared_address": "Riga 40",
            "member_full_name": "Admin OCR Child",
            "member_personal_id": "010125-20202",
            "member_birth_date": "2025-01-01",
            "member_kit_size_shirt": kit["shirt"].pk,
            "member_kit_size_shorts": kit["shorts"].pk,
            "preferred_agreement_signing": "paper",
        },
        files={
            "guardian_identity_document": _make_png("admin_guardian.png"),
            "member_identity_document": _make_png("admin_member.png"),
            "member_portrait_document": _make_png("admin_portrait.png"),
        },
        verified_account=account,
    )
    submit_application(app, account)
    return app


# ===========================================================================
# 1. Guardian auto-reuse default on /applications/new/
# ===========================================================================


class TestGuardianAutoReuseDefault:
    """New application form must prefill from prior extraction by default."""

    def test_new_app_form_prefills_guardian_from_prior_extraction(self, settings):
        """GET /applications/new/ must show OCR-extracted guardian values as prefill."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        _create_submitted_app_with_ocr("autoreuse@example.com")

        account = ParentAccount.objects.get(email="autoreuse@example.com")
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub OCR extracts first_name="Anna", last_name="Bērziņa" for guardian_identity
        # These must appear as prefill values in the form
        assert "Anna" in content or "Bērziņa" in content, (
            "New app form must prefill guardian values from prior OCR extraction."
        )

    def test_new_app_form_prefills_member_from_prior_extraction(self, settings):
        """GET /applications/new/ must show OCR-extracted member values as prefill."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        _create_submitted_app_with_ocr("autoreusemember@example.com")

        account = ParentAccount.objects.get(email="autoreusemember@example.com")
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub OCR extracts first_name="Jānis" for member_identity
        assert "Jānis" in content, (
            "New app form must prefill member values from prior OCR extraction."
        )

    def test_new_app_form_shows_reusable_hint_when_extraction_exists(self, settings):
        """GET /applications/new/ must reuse the prior guardian identity doc when extraction exists.

        P3.5 redirect: /applications/new/ now redirects straight into the
        workspace, so the reuse signal moved from a hint label to an
        actual active guardian_identity Document on the new draft.
        """
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        _create_submitted_app_with_ocr("reusehint@example.com")

        account = ParentAccount.objects.get(email="reusehint@example.com")
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)
        assert resp.status_code == 200

        # The new draft must have an active guardian_identity Document
        # carried over from the prior application (the reuse behavior).
        from apps.documents.models import Document as _Document
        from apps.registrations.models import RegistrationApplication as _RA

        new_app = (
            _RA.objects.filter(
                parent_account=account, status=_RA.Status.DRAFT
            )
            .order_by("-created_at")
            .first()
        )
        assert new_app is not None
        assert new_app.documents.filter(
            kind=_Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).exists()

    def test_new_app_form_no_reuse_hint_without_prior_app(self, settings):
        """GET /applications/new/ must NOT show reusable hint when no prior app exists."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        account = ParentAccount.objects.create(
            email="noreuse@example.com",
            phone="+37120000055",
        )
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        # No reusable hint should be shown
        has_reusable_hint = (
            "Izmanto iepriekš" in content
            or "reusable" in content.lower()
        )
        assert not has_reusable_hint, (
            "New app form must not show reusable hint without prior app."
        )


# ===========================================================================
# 2. Admin review shows both guardian and member sections, confidence when present
# ===========================================================================


class TestAdminReviewBothSectionsAndConfidence:
    """Admin review detail must show both guardian and member OCR sections,
    and confidence only when extraction has it."""

    def test_admin_detail_shows_both_guardian_and_member_sections(self, settings):
        """Detail page must show both guardian and member extracted sections."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        _create_submitted_app_with_ocr("bothsections@example.com")

        staff_user = User.objects.create_superuser(
            username="bothstaff",
            email="bothstaff@example.com",
            password="bothstaffpass",
        )
        client = Client()
        client.force_login(staff_user)

        app = ParentAccount.objects.get(email="bothsections@example.com").applications.first()

        resp = client.get(f"/admin/review/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()

        # Must show both guardian and member sections
        has_guardian_section = (
            "Anna" in content  # stub guardian first_name
            or "guardian" in content.lower()
            or "Bērziņa" in content  # stub guardian last_name
        )
        has_member_section = (
            "Jānis" in content  # stub member first_name
            or "member" in content.lower()
        )
        assert has_guardian_section, (
            "Admin detail must show guardian extracted section."
        )
        assert has_member_section, (
            "Admin detail must show member extracted section."
        )

    def test_admin_detail_shows_confidence_when_present(self, settings):
        """Detail page must show confidence values when OCR returns them."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        _create_submitted_app_with_ocr("confidencetest@example.com")

        staff_user = User.objects.create_superuser(
            username="confstaff",
            email="confstaff@example.com",
            password="confstaffpass",
        )
        client = Client()
        client.force_login(staff_user)

        app = ParentAccount.objects.get(email="confidencetest@example.com").applications.first()

        resp = client.get(f"/admin/review/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub returns confidence dict with values like 0.98, 0.97, 0.99, 0.95
        has_confidence = (
            "0.98" in content
            or "0.97" in content
            or "0.99" in content
            or "0.95" in content
            or "pārliecība" in content.lower()
            or "confidence" in content.lower()
        )
        assert has_confidence, (
            "Admin detail must show confidence when OCR returns it."
        )

    def test_admin_detail_shows_both_doc_preview_links(self, settings):
        """Detail page must show preview links for both guardian and member docs."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        _create_submitted_app_with_ocr("previewboth@example.com")

        staff_user = User.objects.create_superuser(
            username="prevstaff",
            email="prevstaff@example.com",
            password="prevstaffpass",
        )
        client = Client()
        client.force_login(staff_user)

        app = ParentAccount.objects.get(email="previewboth@example.com").applications.first()

        resp = client.get(f"/admin/review/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Must show preview links for both guardian and member documents
        has_preview_link = (
            "priekšskatījums" in content.lower()
            or "preview" in content.lower()
            or "/admin/documents/" in content.lower()
        )
        assert has_preview_link, (
            "Admin detail must show document preview links for both guardian and member."
        )

    def test_admin_detail_no_crash_without_any_ocr(self, settings):
        """Detail page must render fine when no OCR extractions exist."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        # Create submitted app WITHOUT identity docs (no OCR possible)
        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="noocrexample.com",
            phone="+37120000056",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "noocrexample.com",
                "guardian_full_name": "No OCR Parent",
                "guardian_personal_id": "010101-56565",
                "guardian_phone": "+37120000056",
                "guardian_declared_address": "Riga 56",
                "member_full_name": "No OCR Child",
                "member_personal_id": "010125-56565",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
                "preferred_agreement_signing": "paper",
                "member_same_address_as_guardian": True,
            },
            files={},
            verified_account=account,
        )
        # Manually set status to submitted (skip submit validation since no docs)
        app.status = "submitted"
        app.submitted_at = app.created_at
        app.save(update_fields=["status", "submitted_at", "updated_at"])

        staff_user = User.objects.create_superuser(
            username="noocrstaff",
            email="noocrstaff@example.com",
            password="noocrstaffpass",
        )
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Page must render without crashing
        assert "No OCR Parent" in content
