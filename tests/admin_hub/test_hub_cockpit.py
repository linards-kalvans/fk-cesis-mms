"""Review cockpit page."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from django.urls import reverse

from apps.registrations.models import RegistrationApplication
from tests.admin_hub.viewer_markup import (
    attr_value,
    has_attribute,
    link_with_href,
    open_tag_with_attr,
    stage_html,
    stage_open_tag,
    tab_index,
    tab_labels,
    tab_tags,
    viewer_region,
)

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def test_cockpit_requires_staff(client, submitted_application):
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_cockpit_renders_the_field_readout(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Datu pārbaude" in body
    # All four field groups, not just a sample of them.
    assert "Bērns" in body
    assert "Vecāks / likumiskais pārstāvis" in body
    assert "Ekipējums un izvēles" in body
    assert "Piekrišanas" in body
    assert "Formas izmērs" in body
    assert submitted_application.member_full_name in body


def test_cockpit_shows_the_check_off_bar_with_the_renamed_action(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Apstiprināt visus" in body
    assert "Atzīmēt visus" not in body, "the action was renamed"


def test_approve_button_is_never_gated_on_the_checklist(
    client, reviewer, submitted_application
):
    """The checklist is a working aid. Nothing about it may disable approval.

    Parses the actual <button> element carrying the approve label, rather
    than scanning a substring window of the page, so this fails if the
    button ever grows a `disabled` attribute or an `is-disabled` class -
    whether or not that text happens to land within an arbitrary window.
    """
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    match = re.search(r"<button[^>]*>\s*Apstiprināt pieteikumu[^<]*</button>", body)
    assert match is not None, "approve button not found in the rendered page"
    button_html = match.group(0)
    assert "disabled" not in button_html
    assert "is-disabled" not in button_html


def test_fix_requested_cockpit_offers_correction_resolution_disclosure(
    client, submitted_application
):
    from django.contrib.auth.models import User

    admin = User.objects.create_superuser(
        username="cockpit-admin", email="cockpit-admin@example.com", password="pw"
    )
    submitted_application.status = RegistrationApplication.Status.FIX_REQUESTED
    submitted_application.review_message = "Labojiet adresi."
    submitted_application.save(update_fields=["status", "review_message"])
    client.force_login(admin)

    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "data-resolve-corrections" in body
    assert "Atzīmēt labojumus kā atrisinātus" in body
    assert 'value="resolve_corrections"' in body
    assert reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[submitted_application.pk],
    ) in body
    assert (
        f'name="next" value="/hub/pieteikumi/{submitted_application.pk}/"'
        in body
    )
    assert "csrfmiddlewaretoken" in body
    assert "Jāizskata" in body
    assert "nav" in body and "apstiprinājums" in body


def test_cockpit_hides_correction_resolution_outside_fix_requested(
    client, submitted_application
):
    from django.contrib.auth.models import User

    admin = User.objects.create_superuser(
        username="cockpit-admin-2",
        email="cockpit-admin-2@example.com",
        password="pw",
    )
    client.force_login(admin)

    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "data-resolve-corrections" not in body
    assert 'value="resolve_corrections"' not in body


def test_cockpit_hides_correction_resolution_without_change_permission(
    client, submitted_application
):
    from django.contrib.auth.models import User

    user = User.objects.create_user(
        username="cockpit-viewer", password="x", is_staff=True
    )
    submitted_application.status = RegistrationApplication.Status.FIX_REQUESTED
    submitted_application.save(update_fields=["status"])
    client.force_login(user)

    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "data-resolve-corrections" not in body
    assert 'value="resolve_corrections"' not in body


def test_cockpit_posts_approval_to_the_existing_admin_endpoint(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    approve_url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    assert approve_url in body
    assert "csrfmiddlewaretoken" in body


def test_cockpit_approval_posts_next_to_agreement(client, reviewer, submitted_application):
    """Approval must hand off straight to the agreement Hub page: the
    approve form carries `next` = the agreement URL in both the query string
    and the hidden input, so the admin approve endpoint redirects there
    instead of back to the cockpit."""
    client.force_login(reviewer)
    cockpit_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    agreement_url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    body = client.get(cockpit_url).content.decode()

    assert f"?next={agreement_url}" in body
    assert f'value="{agreement_url}"' in body


def test_approved_cockpit_has_no_redundant_agreement_continue_button(
    client, reviewer, approved_application
):
    """With approval landing on the agreement page directly, the cockpit's
    post-approval continuation CTA is a dead step and must be gone."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[approved_application.pk])
    ).content.decode()

    assert "Turpināt: Līgums" not in body


def test_cockpit_document_links_use_the_authorized_preview_view(
    client, reviewer, submitted_application
):
    """Every document link on the page must be the reversed authorized-proxy
    URL for that application's actual document rows - not merely a page that
    happens to mention the proxy's URL prefix somewhere."""
    from apps.documents.models import Document

    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()

    member_doc = submitted_application.documents.get(
        kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
    )
    guardian_doc = submitted_application.documents.get(
        kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
    )
    portrait_doc = submitted_application.documents.get(
        kind=Document.Kind.MEMBER_PORTRAIT, deleted_at__isnull=True
    )

    for doc in (member_doc, guardian_doc, portrait_doc):
        assert reverse("documents:admin-document-preview", args=[doc.id]) in body
        assert reverse("documents:admin-document-download", args=[doc.id]) in body


def test_cockpit_offers_rotation(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "data-viewer-rotate" in body


def test_cockpit_404s_for_an_unknown_application(client, reviewer):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:cockpit", args=[999999]))
    assert response.status_code == 404

def _approve_button_tag(body: str) -> str:
    """The in-card approve button's own tag, so an assertion cannot be
    satisfied by a `disabled` belonging to some other element."""
    import re

    match = re.search(
        r"<button[^>]*>\s*Apstiprināt pieteikumu[^<]*</button>", body, re.S
    )
    assert match, "approve button not found"
    return match.group(0)


def test_step_rail_links_forward_once_an_agreement_exists(
    client, reviewer, approved_application
):
    """Steps 3-8 live on other pages, and the rail is the only place all eight
    appear together. It shipped as non-clickable text with no other forward
    link anywhere, so the agreement download and signed-copy upload were
    reachable only by typing a URL."""
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[approved_application.pk])
    body = client.get(url).content.decode()
    agreement_url = reverse("admin_hub:agreement", args=[approved_application.pk])
    billing_url = reverse("admin_hub:billing", args=[approved_application.pk])
    assert f'href="{agreement_url}"' in body
    assert f'href="{billing_url}"' in body


def test_step_rail_does_not_link_to_pages_that_would_404(
    client, reviewer, submitted_application
):
    """A submitted application has no agreement, so the agreement and billing
    views raise 404. The rail must not offer those steps as links."""
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    agreement_url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    assert f'href="{agreement_url}"' not in body


def test_approve_action_is_offered_for_a_submitted_application(
    client, reviewer, submitted_application
):
    """approve_application refuses anything but a submitted application, so
    offering the button regardless of status promised an action that errors.
    The bar showed "Apstiprināt pieteikumu" on every application.

    Note these are two tests, not one: approved_application is *derived from*
    submitted_application, so a single test requesting both would receive the
    same, already-approved object and assert against itself."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()
    assert "disabled" not in _approve_button_tag(body)


def test_approve_action_is_withdrawn_once_approved(
    client, reviewer, approved_application
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[approved_application.pk])
    ).content.decode()
    assert "disabled" in _approve_button_tag(body)


# ---------------------------------------------------------------------------
# Member ID-card back "Aizmugure" viewer tab (2026-09-11 plan, Task 3
# Step 2 / requirement 9)
# ---------------------------------------------------------------------------


def _create_back_document(application):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.documents.models import Document

    return Document.objects.create(
        application=application,
        kind=Document.Kind.MEMBER_IDENTITY_BACK,
        file=SimpleUploadedFile(
            "back_id.png",
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
            content_type="image/png",
        ),
        original_filename="back_id.png",
        content_type="image/png",
        file_size=12,
    )


def _viewer_tab_tags(body):
    """Full <button> tags for every viewer tab, in render order."""
    return re.findall(
        r"<button[^>]*data-viewer-tab[^>]*>[^<]*</button>", body
    )


def _viewer_tab_labels(body):
    return [
        re.sub(r"^<button[^>]*>", "", tag).replace("</button>", "").strip()
        for tag in _viewer_tab_tags(body)
    ]


def _aizmugure_tab_tag(body):
    tags = [
        tag
        for tag in _viewer_tab_tags(body)
        if tag.rstrip().endswith(">Aizmugure</button>")
    ]
    assert tags, "an Aizmugure viewer tab button must be rendered"
    return tags[0]


def test_cockpit_aizmugure_tab_disabled_without_back_upload(
    client, reviewer, submitted_application
):
    """No back image → the tab still exists but is disabled, matching the
    existing empty-document viewer behavior."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    labels = _viewer_tab_labels(body)
    assert "Aizmugure" in labels, (
        f"the cockpit viewer must offer the Aizmugure tab; tabs were {labels}"
    )
    tab = _aizmugure_tab_tag(body)
    assert "disabled" in tab, (
        f"the empty Aizmugure tab must be disabled; got {tab!r}"
    )


def test_cockpit_aizmugure_tab_uses_authorized_proxy_urls_when_back_uploaded(
    client, reviewer, submitted_application
):
    """With an active back upload the tab is enabled and carries the existing
    staff-authorized preview + download proxy URLs for that document."""
    client.force_login(reviewer)
    back_doc = _create_back_document(submitted_application)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "Aizmugure" in _viewer_tab_labels(body)
    tab = _aizmugure_tab_tag(body)
    assert "disabled" not in tab

    preview_url = reverse(
        "documents:admin-document-preview", args=[back_doc.id]
    )
    download_url = reverse(
        "documents:admin-document-download", args=[back_doc.id]
    )
    assert preview_url in body
    assert download_url in body
    # The URLs ride on the tab button itself (viewer.js copies them from the
    # data attributes onto the toolbar links).
    assert preview_url in tab
    assert download_url in tab


def test_cockpit_aizmugure_tab_sits_after_member_front_tab(
    client, reviewer, submitted_application
):
    """Document order: the back tab comes directly after the member front
    tab (Bērna ID)."""
    client.force_login(reviewer)
    _create_back_document(submitted_application)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    labels = _viewer_tab_labels(body)
    assert labels.index("Aizmugure") == labels.index("Bērna ID") + 1, (
        f"Aizmugure must follow the member front tab; tab order was {labels}"
    )


# ---------------------------------------------------------------------------
# Slice 2 — native, bounded-format previews
# ---------------------------------------------------------------------------


_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _replace_document(application, kind, filename, content_type, content=None):
    """Soft-delete the active row of *kind* and upload a fresh one.

    The viewer reads the active document of each kind, so this is how a test
    puts a PDF (or an unsupported format) into a slot that the default
    fixtures fill with a PNG.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    from apps.documents.models import Document

    application.documents.filter(kind=kind, deleted_at__isnull=True).update(
        deleted_at=timezone.now()
    )
    payload = content if content is not None else _IMAGE_BYTES
    return Document.objects.create(
        application=application,
        kind=kind,
        file=SimpleUploadedFile(filename, payload, content_type=content_type),
        original_filename=filename,
        content_type=content_type,
        file_size=len(payload),
    )


def _cockpit_html(client, reviewer, application):
    client.force_login(reviewer)
    return client.get(
        reverse("admin_hub:cockpit", args=[application.pk])
    ).content.decode()


def _assert_image_controls_unavailable(viewer):
    """Rotation/zoom/fit are disabled and zoom is not reported as a percentage
    until a picture has actually loaded."""
    for attribute in ("data-viewer-rotate", "data-viewer-zoom", "data-viewer-reset"):
        tags = re.findall(rf"<button[^>]*{attribute}[^>]*>", viewer, re.S)
        assert tags, f"the viewer toolbar must render a {attribute} control"
        for tag in tags:
            assert has_attribute(tag, "disabled"), (
                f"{attribute} must start disabled; got {tag!r}"
            )

    label = re.search(
        r"<[^>]*data-viewer-zoom-label[^>]*>(.*?)</", viewer, re.S
    )
    assert label, "the viewer toolbar must render the zoom readout"
    assert label.group(1).strip() == "—", (
        "the zoom readout must be unavailable (—) until an image loads; "
        f"got {label.group(1)!r}"
    )


def test_cockpit_embeds_a_pdf_with_a_titled_native_element(
    client, reviewer, submitted_application
):
    """A classified PDF is rendered natively, not as a broken <img>."""
    from apps.documents.models import Document

    pdf = _replace_document(
        submitted_application,
        Document.Kind.MEMBER_IDENTITY,
        "member_id.pdf",
        "application/pdf",
        _PDF_BYTES,
    )
    body = _cockpit_html(client, reviewer, submitted_application)
    viewer = viewer_region(body)
    stage = stage_html(viewer, 0)

    assert "data-viewer-doc" not in stage, (
        "a PDF must never receive the image-transform hook"
    )
    assert "<img" not in stage, "a PDF must not be rendered as an image"
    embeds = re.findall(r"<(?:iframe|object)\b[^>]*>", stage, re.S)
    assert embeds, f"a PDF needs a native iframe/object; stage was {stage!r}"
    embed = embeds[0]
    title = attr_value(embed, "title") or ""
    assert len(title.strip()) >= 3, f"the native element needs a title: {embed!r}"
    assert re.search(r"dokument|PDF|Bērna", title, re.I), (
        f"the title must describe the document; got {title!r}"
    )

    preview_url = reverse("documents:admin-document-preview", args=[pdf.id])
    download_url = reverse("documents:admin-document-download", args=[pdf.id])
    assert (attr_value(embed, "src") or attr_value(embed, "data")) == preview_url
    # Native rendering may be unavailable; the fallback links stay in the
    # stage so they work without JavaScript too.
    assert link_with_href(stage, preview_url), "a visible open fallback is required"
    assert link_with_href(stage, download_url), "a visible download fallback is required"

    _assert_image_controls_unavailable(viewer)


@pytest.mark.parametrize(
    ("extension", "content_type"),
    [
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
        ("png", "image/png"),
        ("webp", "image/webp"),
        ("heic", "image/heic"),
    ],
)
def test_cockpit_keeps_supported_images_on_the_image_path(
    client, reviewer, submitted_application, extension, content_type
):
    """JPEG/PNG/WebP use the image path; HEIC uses it too and relies on the
    image-error fallback rather than a conversion dependency."""
    from apps.documents.models import Document

    document = _replace_document(
        submitted_application,
        Document.Kind.MEMBER_IDENTITY,
        f"member_id.{extension}",
        content_type,
    )
    body = _cockpit_html(client, reviewer, submitted_application)
    viewer = viewer_region(body)
    stage = stage_html(viewer, 0)

    image_tag = open_tag_with_attr(stage, "data-viewer-doc")
    assert image_tag.startswith("<img"), f"expected an image, got {image_tag!r}"
    preview_url = reverse("documents:admin-document-preview", args=[document.id])
    download_url = reverse("documents:admin-document-download", args=[document.id])
    assert attr_value(image_tag, "src") == preview_url

    error_fallback = open_tag_with_attr(stage, "data-viewer-image-error")
    assert error_fallback, "an image-error fallback must be present"
    assert has_attribute(error_fallback, "hidden"), (
        "the image-error fallback must be hidden until the image fails"
    )
    assert link_with_href(stage, preview_url)
    assert link_with_href(stage, download_url)
    _assert_image_controls_unavailable(viewer)


def test_image_error_fallback_escapes_an_uploaded_filename(
    client, reviewer, submitted_application
):
    """The fallback is rendered through Django's escaping, not raw."""
    from apps.documents.models import Document

    _replace_document(
        submitted_application,
        Document.Kind.MEMBER_IDENTITY,
        'bad"><script>alert(1)</script>.png',
        "image/png",
    )
    body = _cockpit_html(client, reviewer, submitted_application)
    stage = stage_html(viewer_region(body), 0)

    assert open_tag_with_attr(stage, "data-viewer-image-error")
    assert "<script>alert(1)</script>" not in body
    assert 'bad"><script' not in body


@pytest.mark.parametrize(
    ("extension", "content_type"),
    [
        ("html", "text/html"),
        ("svg", "image/svg+xml"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ],
)
def test_cockpit_never_embeds_unknown_or_active_content_formats(
    client, reviewer, submitted_application, extension, content_type
):
    """HTML, SVG and office documents get open/download only."""
    from apps.documents.models import Document

    document = _replace_document(
        submitted_application,
        Document.Kind.MEMBER_IDENTITY,
        f"member_id.{extension}",
        content_type,
    )
    body = _cockpit_html(client, reviewer, submitted_application)
    viewer = viewer_region(body)
    stage = stage_html(viewer, 0)

    assert "<iframe" not in stage
    assert "<object" not in stage
    assert "<img" not in stage
    assert "data-viewer-doc" not in stage
    preview_url = reverse("documents:admin-document-preview", args=[document.id])
    download_url = reverse("documents:admin-document-download", args=[document.id])
    assert link_with_href(stage, preview_url)
    assert link_with_href(stage, download_url)
    _assert_image_controls_unavailable(viewer)


def test_cockpit_preserves_the_four_document_tabs(
    client, reviewer, submitted_application
):
    body = _cockpit_html(client, reviewer, submitted_application)
    assert tab_labels(viewer_region(body)) == [
        "Bērna ID",
        "Aizmugure",
        "Vecāka ID",
        "Portrets",
    ]


def test_cockpit_selects_the_first_available_tab_in_rendered_markup(
    client, reviewer, submitted_application
):
    """A missing first document must not leave an empty stage active."""
    from django.utils import timezone

    from apps.documents.models import Document

    submitted_application.documents.filter(
        kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
    ).update(deleted_at=timezone.now())
    guardian_doc = submitted_application.documents.get(
        kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
    )

    body = _cockpit_html(client, reviewer, submitted_application)
    viewer = viewer_region(body)
    tags = tab_tags(viewer)
    active = [tab_index(tag) for tag in tags if "is-active" in tag]
    assert active == [2], f"the first available tab is Vecāka ID (2); got {active}"

    assert "hidden" not in stage_open_tag(viewer, 2)
    for missing_index in (0, 1, 3):
        assert has_attribute(stage_open_tag(viewer, missing_index), "hidden"), (
            f"missing stage {missing_index} must be hidden"
        )

    active_tag = tags[2]
    assert attr_value(active_tag, "data-viewer-preview") == reverse(
        "documents:admin-document-preview", args=[guardian_doc.id]
    )
    assert attr_value(active_tag, "data-viewer-download") == reverse(
        "documents:admin-document-download", args=[guardian_doc.id]
    )


def test_cockpit_shows_an_empty_state_when_every_document_is_missing(
    client, reviewer, submitted_application
):
    """With no files at all there is a deliberate empty state and no stale
    authorized links."""
    from django.utils import timezone

    submitted_application.documents.update(deleted_at=timezone.now())
    body = _cockpit_html(client, reviewer, submitted_application)
    viewer = viewer_region(body)

    empty = open_tag_with_attr(viewer, "data-viewer-empty")
    assert empty, "an all-missing viewer must render an explicit empty state"
    assert "Neviens dokuments nav augšupielādēts." in viewer, (
        "the empty state must carry explicit localized visible copy"
    )

    for tag in tab_tags(viewer):
        assert has_attribute(tag, "disabled"), f"missing tab must be disabled: {tag!r}"
    for index in range(4):
        tag = stage_open_tag(viewer, index)
        if tag:
            assert has_attribute(tag, "hidden"), f"stage {index} must be hidden"

    assert "/admin/documents/" not in viewer, "no stale preview/download links"
    assert "<iframe" not in viewer and "<object" not in viewer
    _assert_image_controls_unavailable(viewer)


def test_active_tab_carries_its_own_authorized_toolbar_urls(
    client, reviewer, submitted_application
):
    from apps.documents.models import Document

    member_doc = submitted_application.documents.get(
        kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
    )
    body = _cockpit_html(client, reviewer, submitted_application)
    tag = tab_tags(viewer_region(body))[0]

    assert "is-active" in tag
    assert attr_value(tag, "data-viewer-preview") == reverse(
        "documents:admin-document-preview", args=[member_doc.id]
    )
    assert attr_value(tag, "data-viewer-download") == reverse(
        "documents:admin-document-download", args=[member_doc.id]
    )


# ---------------------------------------------------------------------------
# Slice 3 — medical permit in the cockpit
# ---------------------------------------------------------------------------


def _permit_upload(name="permit.pdf", content_type="application/pdf", content=b"%PDF-1.4 permit"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name=name, content=content, content_type=content_type)


def _make_medical_permit(application, *, with_file=True, confirmed=False, reviewer=None):
    import datetime

    from django.utils import timezone

    from apps.documents.models import MedicalPermit

    kwargs = {
        "application": application,
        "valid_until": datetime.date(timezone.localdate().year + 1, 9, 30),
        "source": MedicalPermit.Source.PARENT_UPLOAD,
    }
    if with_file:
        upload = _permit_upload()
        kwargs.update(
            file=upload,
            original_filename=upload.name,
            content_type="application/pdf",
            file_size=len(b"%PDF-1.4 permit"),
        )
    if confirmed:
        kwargs.update(
            source=MedicalPermit.Source.STAFF_CONFIRMATION,
            confirmed_by=reviewer,
            confirmed_at=timezone.now(),
        )
    return MedicalPermit.objects.create(**kwargs)


def _medical_form(body, application):
    match = re.search(
        r"<form[^>]*data-medical-permit-form[^>]*>.*?</form>", body, re.S
    )
    assert match, f"the cockpit must render a medical permit upload form for {application.pk}"
    return match.group(0)


def test_cockpit_renders_a_standalone_multipart_medical_upload_form(
    client, acting_reviewer, submitted_application
):
    client.force_login(acting_reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()
    form = _medical_form(body, submitted_application)
    form_tag = form[: form.index(">") + 1]

    review_action = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[submitted_application.pk],
    )
    assert 'method="post"' in form_tag
    assert 'enctype="multipart/form-data"' in form_tag
    assert f'action="{review_action}"' in form_tag
    assert "csrfmiddlewaretoken" in form
    assert 'name="medical_permit_file"' in form
    assert 'name="action" value="medical_permit_upload"' in form
    assert 'name="next"' in form
    assert f'value="{reverse("admin_hub:cockpit", args=[submitted_application.pk])}"' in form
    assert 'accept=".pdf,.jpg,.jpeg,.png,.heic"' in form
    assert "25 MB" in form
    assert "webp" not in form.lower()
    # Standalone: never nested inside the approval / correction forms.
    assert "<form" not in form[form.index(">") + 1 :]


def test_cockpit_hides_the_medical_upload_form_without_change_permission(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "data-medical-permit-form" not in body
    # Status still renders; only the writer is hidden.
    assert 'data-medical-permit-status="missing"' in body


def test_cockpit_uploads_the_first_permit_from_the_hub(
    client, acting_reviewer, submitted_application
):
    from apps.documents.models import MedicalPermit

    client.force_login(acting_reviewer)
    cockpit_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    review_action = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[submitted_application.pk],
    )

    response = client.post(
        review_action,
        {
            "action": "medical_permit_upload",
            "medical_permit_file": _permit_upload("first-hub.pdf"),
            "next": cockpit_url,
        },
    )

    assert response.status_code == 302
    assert response["Location"] == cockpit_url
    permit = MedicalPermit.objects.get(application=submitted_application)
    assert permit.original_filename == "first-hub.pdf"
    assert permit.source == MedicalPermit.Source.STAFF_UPLOAD
    assert permit.file


def test_cockpit_replaces_an_existing_permit_file(
    client, acting_reviewer, submitted_application
):
    permit = _make_medical_permit(submitted_application)
    old_name = permit.file.name
    client.force_login(acting_reviewer)
    cockpit_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    review_action = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[submitted_application.pk],
    )

    response = client.post(
        review_action,
        {
            "action": "medical_permit_upload",
            "medical_permit_file": _permit_upload("replacement-hub.pdf"),
            "next": cockpit_url,
        },
    )

    assert response.status_code == 302
    assert response["Location"] == cockpit_url
    permit.refresh_from_db()
    assert permit.original_filename == "replacement-hub.pdf"
    assert permit.file.name != old_name


def test_cockpit_links_the_permit_to_the_approved_member(
    client, acting_reviewer, approved_application
):
    from apps.documents.models import MedicalPermit

    client.force_login(acting_reviewer)
    review_action = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[approved_application.pk],
    )

    response = client.post(
        review_action,
        {
            "action": "medical_permit_upload",
            "medical_permit_file": _permit_upload("approved.pdf"),
            "next": reverse(
                "admin_hub:cockpit", args=[approved_application.pk]
            ),
        },
    )

    assert response.status_code == 302
    permit = MedicalPermit.objects.get(application=approved_application)
    assert permit.member_id == approved_application.approved_member_id


def test_cockpit_shows_confirmation_only_status_without_a_medical_tab(
    client, acting_reviewer, submitted_application
):
    client.force_login(acting_reviewer)
    permit = _make_medical_permit(
        submitted_application,
        with_file=False,
        confirmed=True,
        reviewer=acting_reviewer,
    )
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "Apstiprināta bez faila" in body
    assert permit.valid_until.strftime("%d.%m.%Y") in body
    assert 'data-medical-permit-status="current"' in body
    assert tab_labels(viewer_region(body)) == [
        "Bērna ID",
        "Aizmugure",
        "Vecāka ID",
        "Portrets",
    ]
    assert reverse("registrations:medical-permit-preview", args=[permit.pk]) not in body


def test_cockpit_medical_tab_uses_permit_proxy_urls_not_document_urls(
    client, acting_reviewer, submitted_application
):
    permit = _make_medical_permit(submitted_application)
    client.force_login(acting_reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()
    viewer = viewer_region(body)

    assert tab_labels(viewer) == [
        "Bērna ID",
        "Aizmugure",
        "Vecāka ID",
        "Portrets",
        "Veselības apliecība",
    ]
    medical_tag = [
        tag
        for tag in tab_tags(viewer)
        if "Veselības apliecība" in tag
    ][0]
    permit_preview = reverse(
        "registrations:medical-permit-preview", args=[permit.pk]
    )
    permit_download = reverse(
        "registrations:medical-permit-download", args=[permit.pk]
    )
    assert attr_value(medical_tag, "data-viewer-preview") == permit_preview
    assert attr_value(medical_tag, "data-viewer-download") == permit_download

    stage = stage_html(viewer, 4)
    embed = open_tag_with_attr(stage, "iframe")
    assert attr_value(embed, "src") == permit_preview
    assert link_with_href(stage, permit_preview)
    assert link_with_href(stage, permit_download)


def test_cockpit_selects_the_medical_tab_when_only_the_permit_exists(
    client, acting_reviewer, submitted_application
):
    from django.utils import timezone

    submitted_application.documents.update(deleted_at=timezone.now())
    _make_medical_permit(submitted_application)
    body = _cockpit_html(client, acting_reviewer, submitted_application)
    viewer = viewer_region(body)

    active = [
        tab_index(tag) for tag in tab_tags(viewer) if "is-active" in tag
    ]
    assert active == [4]
    assert "hidden" not in stage_open_tag(viewer, 4)
    assert "data-viewer-empty" not in viewer


# ---------------------------------------------------------------------------
# Slice 3 review — cockpit grid structure and file capability gating
# ---------------------------------------------------------------------------


_VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)


class _CockpitStructureParser(HTMLParser):
    """Collect the .cockpit grid's direct children and the right column's
    medical/checklist markers - the structure the two-column grid depends on."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        self.done = False
        self.depth = 0
        self.direct_children: list[tuple[str, dict[str, str]]] = []
        self.in_main = False
        self.has_medical = False
        self.has_checklist = False

    def handle_starttag(self, tag, attrs) -> None:
        attributes = {key: "" if value is None else value for key, value in attrs}
        if self.done:
            return
        if not self.found:
            if tag == "div" and "cockpit" in attributes.get("class", "").split():
                self.found = True
                self.depth = 1
            return
        if self.in_main and attributes.get("data-medical-permit") is not None:
            self.has_medical = True
        if self.in_main and attributes.get("data-checklist") is not None:
            self.has_checklist = True
        if self.depth == 1:
            self.direct_children.append((tag, attributes))
            if tag == "div" and "cockpit__main" in attributes.get(
                "class", ""
            ).split():
                self.in_main = True
        if tag not in _VOID_TAGS:
            self.depth += 1

    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.depth -= 1

    def handle_endtag(self, tag) -> None:
        if not self.found or tag in _VOID_TAGS:
            return
        if self.depth > 0:
            self.depth -= 1
        if self.in_main and self.depth == 1:
            self.in_main = False
        if self.depth == 0:
            self.done = True


def test_cockpit_grid_has_the_viewer_and_one_right_column_container(
    client, acting_reviewer, submitted_application
):
    """The medical card and the checklist must share the right grid track.

    Placing the medical card directly under .cockpit made it a third grid
    item, pushing the checklist into a narrow second-row cell.
    """
    client.force_login(acting_reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    parser = _CockpitStructureParser()
    parser.feed(body)

    assert parser.found, "the cockpit grid must render"
    assert len(parser.direct_children) == 2, parser.direct_children
    viewer_tag, main_tag = parser.direct_children
    assert viewer_tag[0] == "div"
    assert "viewer" in viewer_tag[1]["class"].split()
    assert main_tag[0] == "div"
    assert "cockpit__main" in main_tag[1]["class"].split()
    assert parser.has_medical, "the medical card must live inside the right column"
    assert parser.has_checklist, "the checklist must live inside the right column"


def test_unauthorized_staff_sees_permit_status_but_no_file_controls(
    client, reviewer, submitted_application
):
    """A staff-only account cannot pass the admin/proxy capability, so the
    file links and viewer tab must not be offered even though status and
    validity stay readable."""
    permit = _make_medical_permit(submitted_application)
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert 'data-medical-permit-status="current"' in body
    assert permit.valid_until.strftime("%d.%m.%Y") in body
    assert permit.original_filename in body
    assert reverse("registrations:medical-permit-preview", args=[permit.pk]) not in body
    assert reverse("registrations:medical-permit-download", args=[permit.pk]) not in body
    assert tab_labels(viewer_region(body)) == [
        "Bērna ID",
        "Aizmugure",
        "Vecāka ID",
        "Portrets",
    ]
    assert "data-medical-permit-form" not in body


# ---------------------------------------------------------------------------
# Unit 3 Task 5: visible, deliberate rejection
# ---------------------------------------------------------------------------


def _detail_block(body: str, marker: str) -> str:
    start = body.index(marker)
    end = body.index("</details>", start)
    return body[start:end]


def test_cockpit_offers_a_separate_visible_reject_disclosure(
    client, acting_reviewer, submitted_application
):
    """Rejection is a distinct review action, not a second button sharing the
    request-fix note field. The disclosure only reveals; the confirm button is
    the actual POST and the reason is required."""
    client.force_login(acting_reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    reject_block = _detail_block(body, "data-reject-application")
    fix_block = _detail_block(body, "data-request-fix")

    assert "<summary>Noraidīt</summary>" in reject_block
    assert "Pieteikums tiks noraidīts" in reject_block
    assert 'name="review_message"' in reject_block
    assert 'id="reject_reason"' in reject_block
    assert "required" in reject_block
    assert 'value="reject"' in reject_block
    assert 'value="request_fix"' not in reject_block
    assert "onclick" not in reject_block

    assert 'id="fix_review_message"' in fix_block
    assert 'value="request_fix"' in fix_block
    assert 'value="reject"' not in fix_block
    assert "onclick" not in fix_block

    assert (
        f'name="next" value="/hub/pieteikumi/{submitted_application.pk}/"'
        in reject_block
    )


def test_cockpit_hides_reject_outside_the_submitted_state(
    client, acting_reviewer, approved_application
):
    client.force_login(acting_reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[approved_application.pk])
    ).content.decode()

    assert "data-reject-application" not in body
    assert 'value="reject"' not in body


def test_cockpit_hides_reject_without_change_permission(
    client, reviewer, submitted_application
):
    """A staff-only account may view the cockpit, but the admin endpoint
    refuses every writer it drives, so no reject affordance is offered."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    assert "data-reject-application" not in body
    assert 'value="reject"' not in body
    assert "data-request-fix" not in body
