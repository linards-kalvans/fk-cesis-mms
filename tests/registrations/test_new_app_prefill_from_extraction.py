"""P3 — new application form prefill includes OCR-extracted values from prior apps.

Approved plan:
- New app form GET shows OCR-extracted guardian values when prior app has extraction.
- New app form GET shows OCR-extracted member values when prior app has extraction.
- New app form falls back to model values when no extraction.
- Guardian auto-reuse: active guardian identity document reused by default on new app.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.documents.models import Document, DocumentExtraction
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


# ===========================================================================
# New app prefill from OCR extraction
# ===========================================================================


class TestNewAppPrefillFromExtraction:
    """New app form must include OCR-extracted values from prior apps."""

    def test_new_app_form_shows_ocr_guardian_last_name(self, settings):
        """New app form must show OCR-extracted guardian last_name as prefill."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="prefillfromocr@example.com",
            phone="+37120000040",
        )

        # Create prior app with guardian identity doc (triggers OCR stub)
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Prior Parent",
                "guardian_personal_id": "010101-40000",
                "guardian_phone": "+37120000040",
                "guardian_declared_address": "Riga 40",
                "member_full_name": "Prior Child",
                "member_personal_id": "010125-40000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("prev_guardian.png"),
                "member_identity_document": _make_png("prev_member.png"),
                "member_portrait_document": _make_png("prev_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify prior extraction exists
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=guardian_doc)
        assert extraction.encrypted_payload != ""

        # New app form must show OCR-extracted values
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub OCR extracts last_name="Bērziņa" for guardian_identity
        assert "Bērziņa" in content, (
            "New app form must prefill OCR-extracted guardian values from prior apps."
        )

    def test_new_app_form_shows_ocr_member_first_name(self, settings):
        """New app form must show OCR-extracted member first_name as prefill."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="prefillmember@example.com",
            phone="+37120000041",
        )

        # Create prior app with member identity doc (triggers OCR stub)
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Prior Parent",
                "guardian_personal_id": "010101-41000",
                "guardian_phone": "+37120000041",
                "guardian_declared_address": "Riga 41",
                "member_full_name": "Prior Child",
                "member_personal_id": "010125-41000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("pm_guardian.png"),
                "member_identity_document": _make_png("pm_member.png"),
                "member_portrait_document": _make_png("pm_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify member extraction exists
        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=member_doc)
        assert extraction.encrypted_payload != ""

        # New app form must show OCR-extracted member values
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub OCR extracts first_name="Jānis" for member_identity
        assert "Jānis" in content, (
            "New app form must prefill OCR-extracted member values from prior apps."
        )

    def test_new_app_form_fallback_to_model_values(self, settings):
        """New app form falls back to model values when no extraction exists."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="fallbackprefill@example.com",
            phone="+37120000042",
        )

        # Create prior app with docs (triggers OCR but form still falls back to model)
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Fallback Parent",
                "guardian_personal_id": "010101-42000",
                "guardian_phone": "+37120000042",
                "guardian_declared_address": "Riga 42",
                "member_full_name": "Fallback Child",
                "member_personal_id": "010125-42000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("fb_guardian.png"),
                "member_identity_document": _make_png("fb_member.png"),
                "member_portrait_document": _make_png("fb_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        # Must fall back to model field value
        assert "Fallback Parent" in content


# ---------------------------------------------------------------------------
# Helpers for direct-injection normalization tests
# ---------------------------------------------------------------------------


def _inject_completed_extraction(
    settings,
    *,
    account,
    kind,
    first_name,
    last_name,
    personal_id="010101-99999",
):
    """Create a submitted prior app with a COMPLETED document + extraction.

    Bypasses the OCR pipeline so the test can inject arbitrary casing
    directly into the encrypted payload.
    """
    from apps.documents.ocr import encrypt_json
    from apps.registrations.models import RegistrationApplication

    settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

    app = RegistrationApplication.objects.create(
        parent_account=account,
        guardian_email=account.email,
        guardian_full_name="Prior Parent",
        guardian_personal_id="010101-90000",
        guardian_phone="+37120000099",
        status=RegistrationApplication.Status.SUBMITTED,
    )
    doc = Document.objects.create(
        application=app,
        kind=kind,
        file=f"private-uploads/test/{kind}.png",
        content_type="image/png",
        ocr_status=Document.OcrStatus.COMPLETED,
    )
    payload = {
        "subject": kind.split("_")[0],
        "person_fields": {
            "first_name": first_name,
            "last_name": last_name,
            "personal_id": personal_id,
        },
        "document_metadata": {},
        "confidence": {},
        "flags": [],
        "raw_reference": {"provider": "tiny_idp"},
    }
    DocumentExtraction.objects.create(
        document=doc,
        subject_role=kind.split("_")[0],
        provider="tiny_idp",
        extraction_schema_version="v1",
        encrypted_payload=encrypt_json(payload),
        encrypted_summary=encrypt_json("noop"),
    )
    return app


class TestPrefillNormalization:
    """OCR-derived prefill values must be Latvian title-case, even when the
    encrypted payload stores ALL CAPS provider data."""

    def test_guardian_full_name_prefill_is_title_case(self, settings):
        from apps.registrations.services import get_application_prefill

        account = ParentAccount.objects.create(
            email="normalize-guardian@example.com",
            phone="+37120000090",
        )
        _inject_completed_extraction(
            settings,
            account=account,
            kind=Document.Kind.GUARDIAN_IDENTITY,
            first_name="JĀNIS",
            last_name="BĒRZIŅŠ",
        )

        prefill = get_application_prefill(account)

        # Prior-app model values are "Prior Parent"; OCR overlay appends normalized.
        assert "Jānis Bērziņš" in str(prefill["guardian_full_name"])
        assert "JĀNIS" not in str(prefill["guardian_full_name"])

    def test_member_full_name_prefill_is_title_case(self, settings):
        from apps.registrations.services import get_application_prefill

        account = ParentAccount.objects.create(
            email="normalize-member@example.com",
            phone="+37120000091",
        )
        _inject_completed_extraction(
            settings,
            account=account,
            kind=Document.Kind.MEMBER_IDENTITY,
            first_name="ANNA",
            last_name="KALNIŅA-BĒRZIŅA",
        )

        prefill = get_application_prefill(account)

        assert "Anna Kalniņa-Bērziņa" in str(prefill["member_full_name"])
        assert "ANNA" not in str(prefill["member_full_name"])


# ===========================================================================
# Guardian auto-reuse on /applications/new/
# (folded from RED-phase test_p3_remaining_gaps.py)
# ===========================================================================


def _create_submitted_app_with_ocr(email: str):
    """Create a submitted application with guardian, member, and portrait docs in stub OCR mode."""
    kit = _ensure_kit_sizes()
    account = ParentAccount.objects.create(email=email, phone="+37120000040")
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Auto Reuse Parent",
            "guardian_personal_id": "010101-20202",
            "guardian_phone": "+37120000040",
            "guardian_declared_address": "Riga 40",
            "member_full_name": "Auto Reuse Child",
            "member_personal_id": "010125-20202",
            "member_birth_date": "2025-01-01",
            "member_kit_size_shirt": kit["shirt"].pk,
            "member_kit_size_shorts": kit["shorts"].pk,
            "preferred_agreement_signing": "paper",
        },
        files={
            "guardian_identity_document": _make_png("ar_guardian.png"),
            "member_identity_document": _make_png("ar_member.png"),
            "member_portrait_document": _make_png("ar_portrait.png"),
        },
        verified_account=account,
    )
    submit_application(app, account)
    return app


class TestGuardianAutoReuseDefault:
    """New application /applications/new/ must reuse prior guardian identity doc by default."""

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
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
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
        has_reusable_hint = (
            "Izmanto iepriekš" in content
            or "reusable" in content.lower()
        )
        assert not has_reusable_hint, (
            "New app form must not show reusable hint without prior app."
        )
