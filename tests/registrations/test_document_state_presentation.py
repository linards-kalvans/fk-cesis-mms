"""P2 Task 4 — Active document state visible per document role in parent workspace.

Covers:
- Active guardian/member document filename visible in workspace.
- Document kind label visible in workspace (uses model display name).
- Replace action visible for existing document.
- Workspace renders cleanly when no document uploaded.
- Verified-parent ownership/workspace access (no regression).
- Empty-state document cards show proper display labels (not raw keys).
"""

import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.documents.models import Document
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_guardian_identity_file(name="test_guardian_id.pdf"):
    return SimpleUploadedFile(
        name=name,
        content=b"%PDF-1.4 fake pdf content",
        content_type="application/pdf",
    )


def _make_member_identity_file(name="test_member_id.pdf"):
    return SimpleUploadedFile(
        name=name,
        content=b"%PDF-1.4 fake pdf content",
        content_type="application/pdf",
    )


def _make_member_portrait_file(name="test_portrait.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
    )


def _login(client, account):
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _ensure_kit_sizes():
    """Create kit size options if they don't already exist. Returns (shirt_pk, shorts_pk)."""
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        defaults={"label": "S", "is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        defaults={"label": "S", "is_active": True},
    )
    return shirt.pk, shorts.pk


def _create_workspace_draft_with_guardian_doc(email="docstate@example.com"):
    """Create a verified draft with a guardian identity document."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37120000000",
    )
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "DocState Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "DocState Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
            "member_actual_address": "Riga 1",
            "member_same_address_as_guardian": True,
            "preferred_agreement_signing": "paper",
        },
        files={
            "guardian_identity_document": _make_guardian_identity_file(
                "test_guardian_id.pdf"
            ),
        },
        verified_account=acct,
    )
    return acct, app


# ===========================================================================
# 1. Active document filename visible in workspace
# ===========================================================================


class TestActiveDocumentFilenameVisible:
    """Workspace must show the original filename of an active document."""

    def test_workspace_shows_guardian_identity_filename(self):
        """Workspace must display the guardian identity document filename."""
        client = Client()
        acct, app = _create_workspace_draft_with_guardian_doc()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "test_guardian_id.pdf" in content

    def test_workspace_shows_member_identity_filename(self):
        """Workspace must display the member identity document filename."""
        acct = ParentAccount.objects.create(
            email="docmember@example.com",
            phone="+37130000000",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "docmember@example.com",
                "guardian_full_name": "DocMember Parent",
                "guardian_personal_id": "010101-30000",
                "guardian_phone": "+37130000000",
                "guardian_declared_address": "Riga 3",
                "member_full_name": "DocMember Child",
                "member_personal_id": "010125-30000",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 3",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={
                "member_identity_document": _make_member_identity_file(
                    "my_member_id.pdf"
                ),
            },
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "my_member_id.pdf" in content

    def test_workspace_shows_portrait_filename(self):
        """Workspace must display the member portrait document filename."""
        acct = ParentAccount.objects.create(
            email="docportrait@example.com",
            phone="+37140000000",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "docportrait@example.com",
                "guardian_full_name": "DocPortrait Parent",
                "guardian_personal_id": "010101-40000",
                "guardian_phone": "+37140000000",
                "guardian_declared_address": "Riga 4",
                "member_full_name": "DocPortrait Child",
                "member_personal_id": "010125-40000",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 4",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={
                "member_portrait_document": _make_member_portrait_file(
                    "child_portrait.png"
                ),
            },
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "child_portrait.png" in content


# ===========================================================================
# 2. Document kind label visible in workspace
# ===========================================================================


class TestDocumentKindLabelVisible:
    """Workspace must show the document kind label for active documents."""

    def test_workspace_shows_guardian_identity_kind_label(self):
        """Workspace must display the guardian identity document kind label
        using the model's actual display name."""
        client = Client()
        acct, app = _create_workspace_draft_with_guardian_doc()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Use the model's actual display name so the test adapts to
        # whatever language the production code uses.
        active_doc = app.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        assert active_doc is not None
        expected_label = active_doc.get_kind_display()
        assert expected_label in content, (
            f"Workspace must show the kind label '{expected_label}' "
            f"for the active guardian identity document."
        )


# ===========================================================================
# 3. Replace action visible for existing document
# ===========================================================================


class TestReplaceActionVisible:
    """Workspace must show a replace action for existing documents."""

    def test_replace_action_visible_when_document_exists(self):
        """Workspace must show a replace action when an active document exists."""
        client = Client()
        acct, app = _create_workspace_draft_with_guardian_doc()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Replace" in content or "Aizvietot" in content


# ===========================================================================
# 4. Workspace renders cleanly without documents
# ===========================================================================


class TestWorkspaceWithoutDocuments:
    """Workspace must render cleanly when no documents are uploaded."""

    def test_workspace_renders_without_documents(self):
        """Workspace must return 200 and render when no documents exist."""
        acct = ParentAccount.objects.create(
            email="nodocs@example.com",
            phone="+37150000000",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "nodocs@example.com",
                "guardian_full_name": "NoDocs Parent",
                "guardian_personal_id": "010101-50000",
                "guardian_phone": "+37150000000",
                "guardian_declared_address": "Riga 5",
                "member_full_name": "NoDocs Child",
                "member_personal_id": "010125-50000",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 5",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "NoDocs Child" in content


# ===========================================================================
# 4b. Replace/upload links point to file-input anchors
# ===========================================================================


class TestReplaceUploadLinksPointToFileInputs:
    """Replace and upload actions must link to the correct file input fields."""

    def test_replace_link_points_to_guardian_identity_input(self):
        """Guardian identity replace link must target id_guardian_identity_document."""
        client = Client()
        acct, app = _create_workspace_draft_with_guardian_doc()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'href="#id_guardian_identity_document"' in content

    def test_upload_link_points_to_guardian_identity_input(self):
        """Empty-state upload link must target id_guardian_identity_document."""
        acct = ParentAccount.objects.create(
            email="uploadlink@example.com",
            phone="+37120000001",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "uploadlink@example.com",
                "guardian_full_name": "UploadLink Parent",
                "guardian_personal_id": "010101-20001",
                "guardian_phone": "+37120000001",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "UploadLink Child",
                "member_personal_id": "010125-20001",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'href="#id_guardian_identity_document"' in content


# ===========================================================================
# 4c. Document cards visible in read-only mode
# ===========================================================================


class TestDocumentCardsReadOnlyMode:
    """Document cards must remain visible in read-only workspace modes."""

    def test_document_cards_visible_when_submitted(self):
        """Document card must show filename and kind label in submitted (read-only) mode."""
        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email="readonly@example.com",
            phone="+37120000002",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "readonly@example.com",
                "guardian_full_name": "ReadOnly Parent",
                "guardian_personal_id": "010101-20002",
                "guardian_phone": "+37120000002",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "ReadOnly Child",
                "member_personal_id": "010125-20002",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
                "preferred_agreement_signing": "paper",
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file(
                    "readonly_id.pdf"
                ),
                "member_identity_document": _make_member_identity_file(
                    "readonly_member.pdf"
                ),
                "member_portrait_document": _make_member_portrait_file(
                    "readonly_portrait.png"
                ),
            },
            verified_account=acct,
        )
        # Transition to submitted (read-only)
        from apps.registrations.services import submit_application

        submit_application(app, acct)

        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Filename must still be visible
        assert "readonly_id.pdf" in content
        # Kind label must still be visible
        active_doc = app.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        assert active_doc is not None
        assert active_doc.get_kind_display() in content
        # Replace action must NOT appear (read-only)
        assert "Aizvietot" not in content


# ===========================================================================
# 5. Verified-parent ownership/workspace access (no regression)
# ===========================================================================


class TestVerifiedParentOwnershipNoRegression:
    """Verified-parent ownership and workspace access must not regress."""

    def test_owner_can_access_workspace(self):
        """Authenticated owner must get 200 on their workspace."""
        client = Client()
        acct, app = _create_workspace_draft_with_guardian_doc()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200

    def test_non_owner_gets_404(self):
        """Non-owning parent must get 404 on another parent's workspace."""
        owner_acct, owner_app = _create_workspace_draft_with_guardian_doc(
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
        _, app = _create_workspace_draft_with_guardian_doc()

        resp = Client().get(f"/applications/{app.pk}/")

        assert resp.status_code == 404


# ===========================================================================
# 6. Empty-state document cards show proper display labels (not raw keys)
# ===========================================================================


class TestEmptyStateDocumentKindLabels:
    """Empty-state document cards must show human-readable kind labels,
    not raw underscored keys with capfirst applied."""

    def test_empty_state_guardian_identity_shows_display_label(self):
        """When no guardian identity document exists, the card must show
        the display label 'Guardian identity', not 'Guardian_identity'."""
        acct = ParentAccount.objects.create(
            email="emptystate@example.com",
            phone="+37170000000",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "emptystate@example.com",
                "guardian_full_name": "EmptyState Parent",
                "guardian_personal_id": "010101-70000",
                "guardian_phone": "+37170000000",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "EmptyState Child",
                "member_personal_id": "010125-70000",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 7",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()

        # The display label from the model must appear
        expected_label = Document.Kind.GUARDIAN_IDENTITY.label
        assert expected_label in content, (
            f"Empty-state card must show the display label '{expected_label}', "
            f"not the raw key '{Document.Kind.GUARDIAN_IDENTITY.value}'."
        )

        # Raw underscored key must NOT appear as a kind label.
        # The template renders: <span class="fk-document-card__kind">...</span>
        kind_spans = re.findall(
            r'<span class="fk-document-card__kind">(.*?)</span>', content
        )
        for span in kind_spans:
            assert (
                Document.Kind.GUARDIAN_IDENTITY.value not in span
            ), f"Kind label '{span}' contains raw underscored key '{Document.Kind.GUARDIAN_IDENTITY.value}'."

    def test_empty_state_member_identity_shows_display_label(self):
        """When no member identity document exists, the card must show
        'Member identity', not 'Member_identity'."""
        acct = ParentAccount.objects.create(
            email="emptystate2@example.com",
            phone="+37170000001",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "emptystate2@example.com",
                "guardian_full_name": "EmptyState2 Parent",
                "guardian_personal_id": "010101-70001",
                "guardian_phone": "+37170000001",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "EmptyState2 Child",
                "member_personal_id": "010125-70001",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 7",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()

        expected_label = Document.Kind.MEMBER_IDENTITY.label
        assert expected_label in content, (
            f"Empty-state card must show the display label '{expected_label}'."
        )

        raw_key = Document.Kind.MEMBER_IDENTITY.value
        kind_spans = re.findall(
            r'<span class="fk-document-card__kind">(.*?)</span>', content
        )
        for span in kind_spans:
            assert raw_key not in span, (
                f"Kind label '{span}' contains raw underscored key '{raw_key}'."
            )

    def test_empty_state_member_portrait_shows_display_label(self):
        """When no member portrait document exists, the card must show
        'Member portrait', not 'Member_portrait'."""
        acct = ParentAccount.objects.create(
            email="emptystate3@example.com",
            phone="+37170000002",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "emptystate3@example.com",
                "guardian_full_name": "EmptyState3 Parent",
                "guardian_personal_id": "010101-70002",
                "guardian_phone": "+37170000002",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "EmptyState3 Child",
                "member_personal_id": "010125-70002",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 7",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        client = Client()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()

        expected_label = Document.Kind.MEMBER_PORTRAIT.label
        assert expected_label in content, (
            f"Empty-state card must show the display label '{expected_label}'."
        )

        raw_key = Document.Kind.MEMBER_PORTRAIT.value
        kind_spans = re.findall(
            r'<span class="fk-document-card__kind">(.*?)</span>', content
        )
        for span in kind_spans:
            assert raw_key not in span, (
                f"Kind label '{span}' contains raw underscored key '{raw_key}'."
            )
