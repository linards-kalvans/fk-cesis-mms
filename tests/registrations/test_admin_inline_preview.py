"""P5 Slice A (Revision A) — admin review thumbnail grid + lightbox.

Contract:
- Admin review templates extend ``admin/base_site.html`` (no club branding).
- Each per-kind panel renders a thumbnail grid; clicking a thumbnail opens a
  native ``<dialog class="mms-lightbox">`` populated by JS.
- Image docs render as ``<img class="mms-review-thumb-img">`` inside the link;
  PDFs render an inline SVG (``data-doc-icon="pdf"``) — no real PDF preview;
  the iframe is only created at click-time in JS.
- "Other" file kinds render the SVG icon plus a fallback download link.
- The portrait panel has no OCR readout.
- Replaced docs appear inside ``<details class="mms-review-history">``; the
  ``<details>`` is absent when no replaced docs exist.
- OCR readout renders as ``<dl class="mms-review-ocr-readout">`` with Latvian
  labels; the confidence chip list uses Latvian labels too.
- Anonymous access continues to redirect (regression guards).
- ``_doc_preview_kind`` helper classifies filenames into image/pdf/other.
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
    """Per-kind doc panels with thumbnail grid + lightbox."""

    def test_page_extends_django_admin_shell(
        self, settings, staff_client, submitted_application
    ):
        """Admin review detail must extend admin/base_site.html, not the club shell."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        # Django admin's base.html renders <div id="branding"> — a stable marker.
        assert 'id="branding"' in content, (
            "Admin review detail must extend admin/base_site.html "
            "(missing '<div id=\"branding\">' marker)."
        )
        # The old club shell wrappers must be gone.
        assert "fk-parent-shell" not in content, (
            "Admin review detail must not carry the parent club shell wrappers."
        )

    def test_lightbox_dialog_and_script_present(
        self, settings, staff_client, submitted_application
    ):
        """The lightbox <dialog> and JS bootstrapping script must load on the page."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "admin/js/doc_lightbox.js" in content, (
            "Admin detail must reference admin/js/doc_lightbox.js."
        )

    def test_image_doc_renders_thumbnail_link_with_img(
        self, settings, staff_client, submitted_application
    ):
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
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

        # Active image renders inside an anchor with data-mms-lightbox / data-doc-kind="image".
        link_re_g = re.compile(
            r'<a[^>]+class="[^"]*mms-review-thumb-link[^"]*"[^>]*'
            r'data-mms-lightbox[^>]*data-doc-kind="image"[^>]*'
            r'href="' + re.escape(guardian_preview_url) + r'"[^>]*>'
            r'.*?<img[^>]+class="[^"]*mms-review-thumb-img[^"]*"[^>]+'
            r'src="' + re.escape(guardian_preview_url) + r'"',
            re.DOTALL,
        )
        # data attributes can appear in any order; build a more tolerant variant too.
        link_re_g_alt = re.compile(
            r'<a[^>]+class="[^"]*mms-review-thumb-link[^"]*"[^>]+'
            r'href="' + re.escape(guardian_preview_url) + r'"[^>]*>'
            r'.*?<img[^>]+class="[^"]*mms-review-thumb-img[^"]*"[^>]+'
            r'src="' + re.escape(guardian_preview_url) + r'"',
            re.DOTALL,
        )
        assert link_re_g.search(content) or link_re_g_alt.search(content), (
            "Guardian active PNG must render inside an mms-review-thumb-link anchor "
            "with an mms-review-thumb-img child."
        )
        # Both data-mms-lightbox and data-doc-kind="image" appear at least once.
        assert "data-mms-lightbox" in content
        assert 'data-doc-kind="image"' in content
        assert f'src="{member_preview_url}"' in content, (
            "Member preview URL must appear in an <img src>."
        )

    def test_pdf_doc_renders_inline_svg_icon_not_iframe(
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

        # PDF panel must contain a thumbnail link pointing at preview URL with
        # data-doc-kind="pdf", and an inline SVG icon marked data-doc-icon="pdf".
        panel_re = re.compile(
            r'<section[^>]+class="[^"]*mms-review-panel[^"]*"[^>]+'
            r'data-kind="guardian_identity"[^>]*>(.*?)</section>',
            re.DOTALL,
        )
        match = panel_re.search(content)
        assert match, "Guardian-identity panel must be present."
        panel_html = match.group(1)

        assert 'data-doc-kind="pdf"' in panel_html, (
            "PDF thumbnail link must carry data-doc-kind=\"pdf\"."
        )
        assert 'data-doc-icon="pdf"' in panel_html, (
            "PDF panel must render the inline SVG icon (data-doc-icon=\"pdf\")."
        )
        assert preview_url in panel_html, (
            "PDF thumbnail link must reference the preview URL (no-JS fallback)."
        )
        # No <iframe> in markup — the iframe is built at click-time by JS.
        assert "<iframe" not in content, (
            "PDFs must NOT render as <iframe> in the markup; JS creates one at click."
        )
        # No image thumbnail for the PDF.
        assert not re.search(
            r'<img[^>]+class="[^"]*mms-review-thumb-img[^"]*"[^>]+'
            + r'src="' + re.escape(preview_url) + r'"',
            content,
        ), "PDF must NOT render an <img class=mms-review-thumb-img> child."

    def test_other_file_type_renders_svg_icon_and_download_link(
        self, settings, staff_client, submitted_application
    ):
        """Non-image, non-pdf docs render the inline SVG icon + download link."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY

        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        guardian.original_filename = "guardian_id.docx"
        guardian.content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        guardian.save(update_fields=["original_filename", "content_type"])

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        preview_url = reverse(
            "documents:admin-document-preview", args=[guardian.id]
        )
        download_url = reverse(
            "documents:admin-document-download", args=[guardian.id]
        )

        # Isolate the guardian-identity panel.
        panel_re = re.compile(
            r'<section[^>]+class="[^"]*mms-review-panel[^"]*"[^>]+'
            r'data-kind="guardian_identity"[^>]*>(.*?)</section>',
            re.DOTALL,
        )
        match = panel_re.search(content)
        assert match, "Guardian-identity panel must be present."
        panel_html = match.group(1)

        # No image thumbnail for the .docx
        assert not re.search(
            r'<img[^>]+class="[^"]*mms-review-thumb-img[^"]*"[^>]+'
            + r'src="' + re.escape(preview_url) + r'"',
            panel_html,
        ), ".docx must NOT render as an mms-review-thumb-img <img>."
        # No iframe for the .docx
        assert "<iframe" not in panel_html, (
            ".docx must NOT render as <iframe> in the panel markup."
        )
        # Inline SVG icon present (same icon, neutral styling).
        assert "data-doc-icon" in panel_html, (
            "Other-kind panel must render the inline SVG icon."
        )
        # Fallback download link must reference the download URL with the
        # Latvian "Lejupielādēt failu" label.
        assert download_url in panel_html, (
            "Other-kind panel must include the admin-document-download link."
        )
        assert "Lejupielādēt failu" in panel_html, (
            "Other-kind panel must offer a 'Lejupielādēt failu' link."
        )

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

        portrait_panel_re = re.compile(
            r'<section[^>]+class="[^"]*mms-review-panel[^"]*"[^>]+'
            r'data-kind="member_portrait"[^>]*>(.*?)</section>',
            re.DOTALL,
        )
        match = portrait_panel_re.search(content)
        assert match, "Portrait panel section must be present."
        portrait_html = match.group(1)
        assert "mms-review-ocr-readout" not in portrait_html, (
            "Portrait panel must NOT carry an OCR readout."
        )
        # Thumbnail still renders.
        preview_url = reverse("documents:admin-document-preview", args=[portrait.id])
        assert preview_url in portrait_html, (
            "Portrait panel must embed the active doc preview URL."
        )
        # Image thumbnail present.
        assert re.search(
            r'<img[^>]+class="[^"]*mms-review-thumb-img[^"]*"[^>]+'
            + r'src="' + re.escape(preview_url) + r'"',
            portrait_html,
        ), "Portrait panel must render an image thumbnail."

    def test_replaced_docs_render_inside_history_disclosure(
        self, settings, staff_client, submitted_application
    ):
        """Replaced docs appear inside <details class="mms-review-history">."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY

        for active in submitted_application.documents.filter(deleted_at__isnull=True):
            active.original_filename = f"active_{active.kind}.png"
            active.save(update_fields=["original_filename"])

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

        details_count = len(
            re.findall(r'<details[^>]+class="[^"]*mms-review-history', content)
        )
        assert details_count == 3, (
            f"Expected 3 mms-review-history disclosures, got {details_count}."
        )

        for filename in (
            "replaced_guardian.png",
            "replaced_member.png",
            "replaced_portrait.png",
        ):
            assert filename in content, f"{filename} must render somewhere."

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
        # Disclosure summary copy preserved.
        assert "Iepriekšējās versijas" in content

    def test_ocr_readout_renders_with_latvian_labels(
        self, settings, staff_client, submitted_application
    ):
        """OCR summary renders as <dl class="mms-review-ocr-readout"> with LV labels."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        DocumentExtraction.objects.filter(document=guardian).delete()
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

        assert '<dl class="mms-review-ocr-readout"' in content, (
            "OCR readout must render as <dl class=\"mms-review-ocr-readout\">."
        )
        assert ("Vārds" in content) or ("Personas kods" in content), (
            "OCR readout must carry at least one Latvian label."
        )
        assert "<pre" not in content, (
            "Legacy raw <pre> OCR summary block must be removed."
        )

    def test_confidence_chip_list_uses_latvian_labels(
        self, settings, staff_client, submitted_application
    ):
        """Confidence chip section uses Latvian labels and no raw English keys."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        guardian = submitted_application.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        ).first()
        DocumentExtraction.objects.filter(document=guardian).delete()
        _attach_extraction(
            guardian,
            summary_text="first_name: Jānis\n",
            payload={"confidence": {"first_name": 0.98}},
        )
        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        chip_match = re.search(
            r'<ul class="mms-review-ocr-confidence">.*?</ul>', content, re.DOTALL
        )
        assert chip_match, "Confidence chip list must render as <ul class=\"mms-review-ocr-confidence\">."
        chip_section = chip_match.group(0)
        assert "Vārds" in chip_section, (
            "Confidence chip must render the Latvian label 'Vārds'."
        )
        assert "first_name" not in chip_section, (
            "Confidence chip must not leak the raw English key 'first_name'."
        )

    def test_history_disclosure_absent_when_no_replaced_docs(
        self, settings, staff_client, submitted_application
    ):
        """No <details class="mms-review-history"> when no replaced docs for a kind."""
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY
        assert (
            submitted_application.documents.filter(deleted_at__isnull=False).count()
            == 0
        )

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "mms-review-history" not in content, (
            "mms-review-history disclosure must be hidden when no replaced docs exist."
        )

    def test_replaced_image_doc_carries_image_preview_kind(
        self, settings, staff_client, submitted_application
    ):
        """Replaced image docs must expose data-doc-kind="image", not "other".

        Otherwise the lightbox JS treats them as iframe targets and downloads
        the file inside an iframe instead of rendering it as a clean <img>.
        """
        settings.OCR_ENCRYPTION_KEY = _OCR_KEY

        # Replace the active guardian-identity image twice → two replaced image
        # docs in history.
        for filename in ("replaced_guardian_1.png", "replaced_guardian_2.jpg"):
            _make_doc(
                application=submitted_application,
                kind=Document.Kind.GUARDIAN_IDENTITY,
                filename=filename,
                deleted=True,
            )

        resp = staff_client.get(_DETAIL_URL.format(pk=submitted_application.pk))
        assert resp.status_code == 200
        content = resp.content.decode()

        # Isolate the guardian-identity panel + its history disclosure.
        panel_re = re.compile(
            r'<section[^>]+class="[^"]*mms-review-panel[^"]*"[^>]+'
            r'data-kind="guardian_identity"[^>]*>(.*?)</section>',
            re.DOTALL,
        )
        panel_match = panel_re.search(content)
        assert panel_match, "Guardian-identity panel must be present."
        panel_html = panel_match.group(1)

        history_match = re.search(
            r'<details[^>]+class="[^"]*mms-review-history.*?</details>',
            panel_html,
            re.DOTALL,
        )
        assert history_match, "Replaced-history disclosure must be present."
        history_html = history_match.group(0)

        # Both replaced thumbnail anchors carry data-doc-kind="image".
        image_kind_anchors = re.findall(
            r'<a[^>]+data-mms-lightbox[^>]+data-doc-kind="image"',
            history_html,
        )
        assert len(image_kind_anchors) == 2, (
            f"Both replaced image docs must carry data-doc-kind=\"image\"; "
            f"found {len(image_kind_anchors)}."
        )
        assert 'data-doc-kind="other"' not in history_html, (
            "Replaced image docs must not fall back to data-doc-kind=\"other\"."
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
