"""Tests for P4 Slice E follow-up — OCR summary presentation in the parent workspace."""

import re
from pathlib import Path

import pytest
from django.urls import reverse

from apps.registrations.presentation import OCR_FIELD_LABELS, parse_ocr_summary


class TestOcrFieldLabels:
    def test_covers_stub_person_fields(self):
        for key in ("first_name", "last_name", "personal_id"):
            assert key in OCR_FIELD_LABELS

    def test_covers_stub_document_metadata(self):
        for key in (
            "document_number",
            "issuer",
            "issuance_date",
            "expiry_date",
        ):
            assert key in OCR_FIELD_LABELS

    def test_all_labels_are_non_empty_latvian_strings(self):
        for key, label in OCR_FIELD_LABELS.items():
            assert isinstance(label, str) and label.strip(), key
            # Latvian labels must not be the raw key.
            assert label != key


class TestParseOcrSummary:
    def test_empty_input_returns_empty_list(self):
        assert parse_ocr_summary(None) == []
        assert parse_ocr_summary("") == []
        assert parse_ocr_summary("   \n  ") == []

    def test_known_keys_get_latvian_labels(self):
        text = "first_name: Anna\nlast_name: Bērziņa\npersonal_id: 010101-10001"
        result = parse_ocr_summary(text)
        labels = [label for label, _ in result]
        assert "Vārds" in labels
        assert "Uzvārds" in labels
        assert "Personas kods" in labels

    def test_unknown_keys_fall_back_to_title_case(self):
        text = "unknown_extra_field: foo"
        result = parse_ocr_summary(text)
        assert result == [("Unknown Extra Field", "foo")]

    def test_value_with_colons_is_preserved(self):
        text = "issuance_date: 2020-01-01T00:00:00"
        result = parse_ocr_summary(text)
        assert result == [("Izsniegšanas datums", "2020-01-01T00:00:00")]

    def test_blank_lines_and_keyless_lines_are_skipped(self):
        text = "\n\nfirst_name: Anna\nthis line has no colon\n: only-value\n"
        result = parse_ocr_summary(text)
        assert result == [("Vārds", "Anna")]


@pytest.mark.django_db
class TestWorkspaceOcrSummaryRendering:
    def _make_app_with_ocr(self, parent_account):
        """Create a draft application with a guardian-identity document that
        carries a real DocumentExtraction with an encrypted summary, so the
        workspace renders the OCR summary section."""
        from apps.documents.models import Document, DocumentExtraction
        from apps.documents.ocr import encrypt_json
        from apps.registrations.models import RegistrationApplication

        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
        )
        doc = Document.objects.create(
            application=app,
            kind=Document.Kind.GUARDIAN_IDENTITY,
            original_filename="passport.jpg",
            content_type="image/jpeg",
            ocr_status=Document.OcrStatus.COMPLETED,
        )
        summary = "first_name: Anna\nlast_name: Bērziņa\npersonal_id: 010101-10001"
        DocumentExtraction.objects.create(
            document=doc,
            subject_role="guardian",
            provider="stub",
            extraction_schema_version="v1",
            encrypted_payload=encrypt_json({}),
            encrypted_summary=encrypt_json(summary),
        )
        return app

    def test_workspace_shows_latvian_document_kind_label(
        self, verified_client, parent_account
    ):
        app = self._make_app_with_ocr(parent_account)
        url = reverse("registrations:application-workspace", args=[app.id])
        response = verified_client.get(url)
        assert response.status_code == 200
        html = response.content.decode("utf-8")
        # The raw "guardian_identity" key must not appear in user-visible text.
        # Confirm by looking inside the OCR summary section specifically.
        ocr_section = re.search(
            r"OCR kopsavilkums.*?</div>\s*</div>",
            html,
            re.DOTALL,
        )
        assert ocr_section, "expected OCR kopsavilkums section to render"
        assert "guardian_identity" not in ocr_section.group(0)
        # The Latvian kind label from DOCUMENT_KIND_LABELS must appear.
        from apps.registrations.presentation import DOCUMENT_KIND_LABELS

        assert DOCUMENT_KIND_LABELS["guardian_identity"] in ocr_section.group(0)

    def test_workspace_shows_latvian_field_labels(
        self, verified_client, parent_account
    ):
        app = self._make_app_with_ocr(parent_account)
        url = reverse("registrations:application-workspace", args=[app.id])
        response = verified_client.get(url)
        assert response.status_code == 200
        html = response.content.decode("utf-8")
        ocr_section_match = re.search(
            r"OCR kopsavilkums.*?</div>\s*</div>",
            html,
            re.DOTALL,
        )
        assert ocr_section_match
        section = ocr_section_match.group(0)
        # Raw OCR field keys must not appear.
        for raw in ("first_name", "last_name", "personal_id"):
            assert raw not in section, f"raw key {raw!r} leaked into rendered HTML"
        # Their Latvian labels must appear.
        for label in ("Vārds", "Uzvārds", "Personas kods"):
            assert label in section


class TestOcrSummaryListCss:
    def test_ocr_summary_list_class_defined(self):
        css = (
            Path(__file__).resolve().parents[2]
            / "static"
            / "css"
            / "parent_theme.css"
        ).read_text(encoding="utf-8")
        assert re.search(r"\.fk-ocr-summary-list\s*\{", css)
        assert re.search(r"\.fk-ocr-summary-row\s*\{", css)
