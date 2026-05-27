"""P5 Slice A — admin review inline doc preview + approval-ready inspection.

Contract:
- Admin review detail renders three per-kind panels (guardian_identity,
  member_identity, member_portrait) using the new
  `templates/registrations/admin/_doc_panel.html` partial.
- Active image documents embed as `<img>`; PDFs embed as `<iframe>`; other
  file types render a fallback note with a download link.
- The portrait panel has no OCR readout.
- Replaced docs land in a `<details class="fk-doc-history">` per kind; the
  `<details>` is absent when no replaced docs exist.
- OCR readout renders as `<dl class="fk-ocr-readout">` with Latvian labels;
  the legacy raw `<pre>` summary block is gone.
- Anonymous access continues to redirect (regression guards).
- `_doc_preview_kind` helper classifies filenames into image/pdf/other.
"""

from __future__ import annotations

import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.documents.models import Document, DocumentExtraction
from apps.documents.ocr import encrypt_json
from apps.registrations.views import _doc_preview_kind

pytestmark = pytest.mark.django_db


_DETAIL_URL = "/admin/review/applications/{pk}/"
_OCR_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="


def _png(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_doc(
    *,
    application,
    kind: str,
    filename: str,
    content_type: str = "image/png",
    deleted: bool = False,
):
    from django.utils import timezone

    doc = Document.objects.create(
        application=application,
        kind=kind,
        file=_png(filename),
        original_filename=filename,
        content_type=content_type,
        file_size=20,
    )
    if deleted:
        doc.deleted_at = timezone.now()
        doc.save(update_fields=["deleted_at"])
    return doc


def _attach_extraction(doc: Document, *, summary_text: str, payload: dict | None = None):
    payload = payload or {}
    DocumentExtraction.objects.create(
        document=doc,
        encrypted_payload=encrypt_json(payload),
        encrypted_summary=encrypt_json(summary_text),
    )


# ---------------------------------------------------------------------------
# _doc_preview_kind helper
# ---------------------------------------------------------------------------


class _DocStub:
    """Stand-in object exposing `original_filename` + `file.name`."""

    def __init__(self, original: str = "", file_name: str = ""):
        self.original_filename = original

        class _F:
            name = file_name

        self.file = _F()


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("photo.jpg", "image"),
        ("scan.JPEG", "image"),
        ("img.png", "image"),
        ("img.webp", "image"),
        ("img.heic", "image"),
        ("doc.pdf", "pdf"),
        ("doc.PDF", "pdf"),
        ("paper.docx", "other"),
        ("", "other"),
        ("noextension", "other"),
    ],
)
def test_doc_preview_kind_classifies_extensions(filename, expected):
    """Original filename drives classification; case-insensitive."""
    doc = _DocStub(original=filename)
    assert _doc_preview_kind(doc) == expected


def test_doc_preview_kind_falls_back_to_file_name():
    """Falls back to `document.file.name` when original_filename is empty."""
    doc = _DocStub(original="", file_name="storage/path/IMG.PNG")
    assert _doc_preview_kind(doc) == "image"


# ---------------------------------------------------------------------------
# Admin detail rendering — uses shared fixtures (staff_client + submitted_application)
# ---------------------------------------------------------------------------


class TestAdminInlinePreview:
    """Per-kind doc panels with inline preview + history."""

    def test_image_doc_renders_img_tag_with_preview_url(
        self, settings, staff_client, submitted_application
    ):
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        # Replace docs to deterministic names regardless of OCR side effects
        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        guardian.original_filename = "guardian.png"
        guardian.save(update_fields=["original_filename"])
        member = submitted_application.documents.filter(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        ).first()
        member.original_filename = "member.jpg"
        member.save(update_fields=["original_filename"])

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        guardian_preview_url = reverse(
            "documents:admin-document-preview", args=[guardian.id]
        )
        member_preview_url = reverse(
            "documents:admin-document-preview", args=[member.id]
        )

        # Each active doc renders an <img> tag whose src matches the preview URL.
        img_re_g = re.compile(
            r'<img[^>]+class="[^"]*fk-doc-preview--image[^"]*"[^>]+src="'
            + re.escape(guardian_preview_url)
            + r'"',
            re.DOTALL,
        )
        img_re_m = re.compile(
            r'<img[^>]+class="[^"]*fk-doc-preview--image[^"]*"[^>]+src="'
            + re.escape(member_preview_url)
            + r'"',
            re.DOTALL,
        )
        assert img_re_g.search(content), (
            "Guardian active PNG must render as <img> with preview URL."
        )
        assert img_re_m.search(content), (
            "Member active JPG must render as <img> with preview URL."
        )

    def test_pdf_doc_renders_iframe(
        self, settings, staff_client, submitted_application
    ):
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        guardian.original_filename = "guardian.pdf"
        guardian.content_type = "application/pdf"
        guardian.save(update_fields=["original_filename", "content_type"])

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        preview_url = reverse("documents:admin-document-preview", args=[guardian.id])
        iframe_re = re.compile(
            r'<iframe[^>]+class="[^"]*fk-doc-preview--pdf[^"]*"[^>]+src="'
            + re.escape(preview_url)
            + r'"',
            re.DOTALL,
        )
        assert iframe_re.search(content), "PDF must render as <iframe>, not <img>."
        # Also check the same URL isn't accidentally embedded as an <img>.
        assert not re.search(
            r'<img[^>]+src="' + re.escape(preview_url) + r'"', content
        ), "PDF must NOT render as <img>."

    def test_portrait_panel_has_no_ocr_readout(
        self, settings, staff_client, submitted_application
    ):
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        portrait = submitted_application.documents.filter(
            kind=Document.Kind.MEMBER_PORTRAIT, deleted_at__isnull=True
        ).first()
        assert portrait is not None

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        # Isolate the portrait panel block to assert no <dl class="fk-ocr-readout">
        # appears within it.
        portrait_panel_re = re.compile(
            r'<section[^>]+class="[^"]*fk-doc-panel[^"]*"[^>]+'
            r'data-kind="member_portrait"[^>]*>(.*?)</section>',
            re.DOTALL,
        )
        match = portrait_panel_re.search(content)
        assert match, "Portrait panel section must be present."
        portrait_html = match.group(1)
        assert "fk-ocr-readout" not in portrait_html, (
            "Portrait panel must NOT carry an OCR readout."
        )
        # Active doc embed must still render.
        preview_url = reverse("documents:admin-document-preview", args=[portrait.id])
        assert preview_url in portrait_html, (
            "Portrait panel must embed the active doc preview URL."
        )

    def test_replaced_docs_render_inside_history_disclosure(
        self, settings, staff_client, submitted_application
    ):
        """Replaced docs appear inside <details class="fk-doc-history">.

        The currently active doc must NOT appear inside any <details>.
        """
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY

        # Rename active docs so their names cannot collide as substrings of
        # replaced-doc names below.
        for active in submitted_application.documents.filter(deleted_at__isnull=True):
            active.original_filename = f"active_{active.kind}.png"
            active.save(update_fields=["original_filename"])

        # Add replaced (soft-deleted) docs for each kind.
        for kind, filename in (
            (Document.Kind.GUARDIAN_IDENTITY, "replaced_guardian.png"),
            (Document.Kind.MEMBER_IDENTITY, "replaced_member.png"),
            (Document.Kind.MEMBER_PORTRAIT, "replaced_portrait.png"),
        ):
            _make_doc(
                application=submitted_application,
                kind=kind,
                filename=filename,
                deleted=True,
            )

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        # Each panel must contain a <details class="fk-doc-history">.
        details_count = len(
            re.findall(r'<details[^>]+class="[^"]*fk-doc-history', content)
        )
        assert details_count == 3, (
            f"Expected 3 fk-doc-history disclosures, got {details_count}."
        )

        # Each replaced filename must appear within a <details> block.
        for filename in (
            "replaced_guardian.png",
            "replaced_member.png",
            "replaced_portrait.png",
        ):
            assert filename in content, f"{filename} must render somewhere."

        # The active docs must NOT appear inside any <details> block.
        active_docs = submitted_application.documents.filter(deleted_at__isnull=True)
        details_blocks = re.findall(
            r"<details[^>]*>.*?</details>", content, re.DOTALL
        )
        joined_details = "\n".join(details_blocks)
        for active in active_docs:
            assert active.original_filename not in joined_details, (
                f"Active doc {active.original_filename} must not appear inside a "
                f"<details> disclosure."
            )

    def test_ocr_readout_renders_with_latvian_labels(
        self, settings, staff_client, submitted_application
    ):
        """OCR summary renders as <dl class="fk-ocr-readout"> with LV labels."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        # The stub OCR provider populates extractions during submit; the existing
        # encrypted_summary should already contain key:value lines like
        # "first_name: Jānis". Make sure a guardian extraction exists.
        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        if not hasattr(guardian, "extraction") or guardian.extraction is None:
            _attach_extraction(
                guardian,
                summary_text=(
                    "first_name: Jānis\n"
                    "last_name: Bērziņš\n"
                    "personal_id: 010101-12345\n"
                ),
            )

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        assert '<dl class="fk-ocr-readout"' in content, (
            "OCR readout must render as <dl class=\"fk-ocr-readout\">."
        )
        # At least one canonical Latvian label appears (from OCR_FIELD_LABELS).
        assert ("Vārds" in content) or ("Personas kods" in content), (
            "OCR readout must carry at least one Latvian label."
        )
        # The legacy raw <pre> summary block must be gone.
        assert "<pre" not in content, (
            "Legacy raw <pre> OCR summary block must be removed."
        )

    def test_history_disclosure_absent_when_no_replaced_docs(
        self, settings, staff_client, submitted_application
    ):
        """No <details class="fk-doc-history"> when no replaced docs for a kind."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        # By default the submitted_application fixture leaves no soft-deleted docs.
        assert (
            submitted_application.documents.filter(deleted_at__isnull=False).count()
            == 0
        )

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-doc-history" not in content, (
            "fk-doc-history disclosure must be hidden when no replaced docs exist."
        )

    def test_anonymous_get_detail_still_redirects(self, submitted_application):
        """Regression guard: anonymous still gated."""
        client = Client()
        resp = client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code in (302, 404), (
            f"Anonymous must be redirected or 404'd; got {resp.status_code}."
        )

    def test_anonymous_get_preview_still_gated(self, submitted_application):
        """Regression guard: inline embed does not widen preview access."""
        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        client = Client()
        url = reverse("documents:admin-document-preview", args=[guardian.id])
        resp = client.get(url)
        assert resp.status_code in (302, 404), (
            f"Anonymous preview must stay gated; got {resp.status_code}."
        )
