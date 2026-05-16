"""P2 Task 4 — OCR/system source badges visible where field_sources contains source markers.

Covers:
- Source badge label visible when field_sources contains a source marker.
- Source badge absent when no source marker for a field.
- OCR-extracted badge visible when field_sources contains OCR source markers.
- Error summary shows heading, field label, validation message, and anchor target.
- Verified-parent ownership/workspace access (no regression).
"""

import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client, account):
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _create_workspace_draft_with_field_sources(email="srcpres@example.com"):
    """Create a verified draft that populates field_sources."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37120000000",
    )
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "SourcePres Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "SourcePres Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
            "member_actual_address": "Riga 1",
            "member_same_address_as_guardian": True,
            "preferred_agreement_signing": "paper",
        },
        files={},
        verified_account=acct,
    )
    return acct, app


# ===========================================================================
# 1. Source badge visible when field_sources contains a source marker
# ===========================================================================


class TestSourceBadgeVisible:
    """Source badges must be visible where field_sources contains source markers."""

    def test_source_badge_label_visible_in_workspace(self):
        """Workspace must display source badge labels when field_sources has values."""
        client = Client()
        acct, app = _create_workspace_draft_with_field_sources()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Ievadījāt jūs" in content, (
            "Workspace must display the source badge label "
            "(e.g. 'Ievadījāt jūs') when field_sources contains a marker."
        )

    def test_source_badge_label_visible_for_derived_source(self):
        """Workspace must display derived source badge when guardian_email is derived."""
        client = Client()
        acct, app = _create_workspace_draft_with_field_sources()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Aizpildīts no pārbaudīta konta" in content, (
            "Workspace must display 'Aizpildīts no pārbaudīta konta' badge "
            "for fields with derived_system_filled source."
        )


# ===========================================================================
# 2. Source badge absent when no source marker
# ===========================================================================


class TestSourceBadgeAbsent:
    """Source badges must not appear when no source marker exists for a field."""

    def test_no_source_badge_when_field_sources_empty(self):
        """When field_sources is empty, source badge labels must not appear."""
        acct = ParentAccount.objects.create(
            email="nosrc@example.com",
            phone="+37160000000",
        )
        app = RegistrationApplication.objects.create(
            parent_account=acct,
            guardian_email="nosrc@example.com",
            guardian_full_name="NoSrc Parent",
            guardian_personal_id="010101-60000",
            guardian_phone="+37160000000",
            guardian_declared_address="Riga 6",
            member_full_name="NoSrc Child",
            member_personal_id="010125-60000",
            member_birth_date="2025-01-01",
            member_actual_address="Riga 6",
            member_same_address_as_guardian=True,
            preferred_agreement_signing="paper",
            field_sources={},
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # None of the known source labels should appear
        assert "Aizpildīts no dokumenta" not in content, (
            "Source badge must not appear when no source marker exists."
        )
        assert "Ievadījāt jūs" not in content, (
            "Source badge must not appear when no source marker exists."
        )


# ===========================================================================
# 3. OCR-extracted badge visible when field_sources contains OCR markers
# ===========================================================================


class TestOcrExtractedBadgeVisible:
    """OCR-extracted source badges must be visible when field_sources contains OCR markers."""

    def test_ocr_extracted_label_visible_in_workspace(self):
        """Workspace must display 'Aizpildīts no dokumenta' badge when field_sources contains
        an OCR source marker (e.g. ocr_guardian_identity or ocr_member_identity)."""
        acct = ParentAccount.objects.create(
            email="ocrexample@example.com",
            phone="+37130000001",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "ocrexample@example.com",
                "guardian_full_name": "OcrExtract Parent",
                "guardian_personal_id": "010101-70000",
                "guardian_phone": "+37130000001",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "OcrExtract Child",
                "member_personal_id": "010125-70000",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 7",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        # Simulate OCR-extracted field sources (what OCR integration would set)
        app.field_sources = {
            "guardian_full_name": "ocr_guardian_identity",
            "guardian_personal_id": "ocr_guardian_identity",
            "member_full_name": "ocr_member_identity",
            "member_personal_id": "ocr_member_identity",
        }
        app.save(update_fields=["field_sources"])

        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Aizpildīts no dokumenta" in content, (
            "Workspace must display the OCR-extracted badge label "
            "'Aizpildīts no dokumenta' when field_sources contains an OCR marker."
        )


# ===========================================================================
# 4. Error summary shows full top-level summary behavior
# ===========================================================================


class TestErrorSummaryFullBehavior:
    """Invalid submit must show a top-level error summary with heading,
    field label, validation message, and anchor target."""

    def test_error_summary_full_behavior_on_invalid_submit(self):
        """When guardian_email is empty on submit, the error summary must:
        - show a heading/summary block text,
        - show the field label ('E-pasts'),
        - show the validation message ('E-pasts ir obligāts.'),
        - include an anchor target linking to the invalid field (id-guardian_email)."""
        client = Client()
        acct, app = _create_workspace_draft_with_field_sources()
        _login(client, acct)

        resp = client.post(
            f"/applications/{app.pk}/",
            {
                "guardian_email": "",  # invalid — empty
                "guardian_full_name": "Valid Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Valid Child",
                "member_personal_id": "010125-54321",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
                "submit_action": "submit",
            },
        )

        assert resp.status_code == 200
        content = resp.content.decode()

        # 1. Summary heading / block text visible
        assert "Sekojošas kļūdas ir jāizlabo" in content, (
            "Error summary must show the heading text 'Sekojošas kļūdas ir jāizlabo'."
        )

        # 2. Field label visible in summary
        assert "E-pasts" in content, (
            "Error summary must show the field label 'E-pasts' for the invalid field."
        )

        # 3. Validation message visible in summary
        assert "E-pasts ir obligāts" in content, (
            "Error summary must show the validation message 'E-pasts ir obligāts'."
        )

        # 4. Anchor link points to invalid field
        assert "id-guardian_email" in content, (
            "Error summary must include an anchor target linking to "
            "the invalid field (id-guardian_email)."
        )


# ===========================================================================
# 5. Verified-parent ownership/workspace access (no regression)
# ===========================================================================


class TestVerifiedParentOwnershipNoRegression:
    """Verified-parent ownership and workspace access must not regress."""

    def test_owner_can_access_workspace(self):
        """Authenticated owner must get 200 on their workspace."""
        client = Client()
        acct, app = _create_workspace_draft_with_field_sources()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200

    def test_non_owner_gets_404(self):
        """Non-owning parent must get 404 on another parent's workspace."""
        owner_acct, owner_app = _create_workspace_draft_with_field_sources(
            "owner@example.com"
        )
        stranger = ParentAccount.objects.create(
            email="stranger@example.com",
            phone="+37160000001",
        )
        stranger_client = Client()
        _login(stranger_client, stranger)

        resp = stranger_client.get(f"/applications/{owner_app.pk}/")

        assert resp.status_code == 404

    def test_anonymous_gets_404(self):
        """Anonymous user must get 404 on workspace."""
        _, app = _create_workspace_draft_with_field_sources()

        resp = Client().get(f"/applications/{app.pk}/")

        assert resp.status_code == 404


# ===========================================================================
# 6. review_hint_extracted source label
# ===========================================================================


class TestReviewHintExtractedSource:
    """The review_hint_extracted source marker must map to 'Lūdzu, pārbaudiet'."""

    def test_review_hint_extracted_maps_to_ludzu_parbaudiet(self):
        """When field_sources contains 'review_hint_extracted', the workspace must
        display 'Lūdzu, pārbaudiet' as the source badge label."""
        acct = ParentAccount.objects.create(
            email="reviewhint@example.com",
            phone="+37140000001",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "reviewhint@example.com",
                "guardian_full_name": "ReviewHint Parent",
                "guardian_personal_id": "010101-40001",
                "guardian_phone": "+37140000001",
                "guardian_declared_address": "Riga 4",
                "member_full_name": "ReviewHint Child",
                "member_personal_id": "010125-40001",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 4",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        # Simulate a review_hint_extracted source marker
        app.field_sources = {
            "guardian_full_name": "review_hint_extracted",
            "guardian_personal_id": "review_hint_extracted",
        }
        app.save(update_fields=["field_sources"])

        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Lūdzu, pārbaudiet" in content, (
            "Workspace must display 'Lūdzu, pārbaudiet' when field_sources "
            "contains the 'review_hint_extracted' source marker."
        )
