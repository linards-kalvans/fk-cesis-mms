"""Tests for P4 Slice E follow-up — Latvian document-kind labels on parent surfaces."""

import pytest
from django.template.loader import render_to_string
from django.urls import reverse

from apps.registrations.presentation import DOCUMENT_KIND_LABELS


class TestDocumentKindLabelsAreLatvian:
    def test_guardian_identity_label_is_latvian(self):
        label = DOCUMENT_KIND_LABELS["guardian_identity"]
        assert "Vecāka" in label
        assert "Guardian" not in label

    def test_member_identity_label_is_latvian(self):
        label = DOCUMENT_KIND_LABELS["member_identity"]
        assert "Bērna" in label
        assert "Member" not in label

    def test_member_portrait_label_is_latvian(self):
        label = DOCUMENT_KIND_LABELS["member_portrait"]
        assert "Bērna" in label
        assert "Member" not in label

    def test_covers_every_document_kind(self):
        from apps.documents.models import Document

        for kind in Document.Kind:
            assert kind.value in DOCUMENT_KIND_LABELS, (
                f"DOCUMENT_KIND_LABELS missing entry for {kind.value}"
            )


class TestDocumentCardRendersLatvianLabel:
    def test_partial_uses_kind_label_map(self):
        html = render_to_string(
            "parent_ui/includes/document_card.html",
            {
                "document_state": {"guardian_identity": None},
                "document_kind_labels": DOCUMENT_KIND_LABELS,
                "document_field_id_map": {"guardian_identity": "id_guardian_identity_document"},
                "workspace_mode": "read_only",
            },
        )
        assert DOCUMENT_KIND_LABELS["guardian_identity"] in html
        assert "Guardian identity" not in html


@pytest.mark.django_db
class TestWorkspaceRendersLatvianLabelWithExistingDocument:
    """When a Document exists, the partial historically used
    Document.get_kind_display() — that path still produced English.
    After Fix B, the partial always uses the Latvian label map."""

    def test_workspace_does_not_render_english_kind_labels(
        self, verified_client, draft_with_documents
    ):
        url = reverse("registrations:application-workspace", args=[draft_with_documents.id])
        response = verified_client.get(url)
        assert response.status_code == 200
        html = response.content.decode("utf-8")
        # English labels from Document.Kind must NOT leak.
        for english in ("Guardian identity", "Member identity", "Member portrait"):
            assert english not in html, f"{english!r} leaked into rendered workspace"
        # Latvian labels must appear.
        for latvian in (
            DOCUMENT_KIND_LABELS["guardian_identity"],
            DOCUMENT_KIND_LABELS["member_identity"],
            DOCUMENT_KIND_LABELS["member_portrait"],
        ):
            assert latvian in html
