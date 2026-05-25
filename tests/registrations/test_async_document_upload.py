"""Async document upload endpoint tests.

P3.5 Phase 2 — POST /applications/<id>/documents/ creates the Document
record, enqueues the OCR job, and returns a JSON payload immediately.
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


_FERNET_KEY_FIXTURE = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="


def _png_bytes(size: int = 64) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def _verified_client(account: ParentAccount) -> Client:
    client = Client()
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.id
    session.save()
    return client


def _make_application(account: ParentAccount) -> RegistrationApplication:
    app: RegistrationApplication = RegistrationApplication.objects.create(
        parent_account=account,
        guardian_email=account.email,
        guardian_full_name="Test Parent",
        guardian_personal_id="010101-12345",
        guardian_phone="+37120000001",
        guardian_declared_address="Riga 1",
        member_full_name="Test Child",
        member_personal_id="010125-12345",
        member_birth_date="2025-01-01",
    )
    return app


def test_post_creates_document_and_enqueues_ocr(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = ParentAccount.objects.create(
        email="upload@example.com", phone="+37120000001"
    )
    app = _make_application(account)
    client = _verified_client(account)

    enqueued: list[int] = []

    def _spy(document_id: int) -> None:
        enqueued.append(document_id)

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )

    with patch(
        "apps.registrations.views.enqueue_ocr_job",
        side_effect=_spy,
    ):
        response = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={"kind": "guardian_identity", "file": upload},
        )

    assert response.status_code == 201
    payload = json.loads(response.content)
    assert payload["kind"] == "guardian_identity"
    assert payload["ocr_status"] == "pending"
    assert isinstance(payload["document_id"], int)

    doc = Document.objects.get(pk=payload["document_id"])
    assert doc.application_id == app.id
    assert doc.kind == "guardian_identity"
    assert doc.ocr_status == Document.OcrStatus.PENDING
    assert enqueued == [doc.id]


def test_post_rejects_unverified_session():
    account = ParentAccount.objects.create(
        email="anon@example.com", phone="+37120000002"
    )
    app = _make_application(account)
    client = Client()  # no verified session

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code in {302, 401, 403, 404}


def test_post_rejects_non_owner():
    owner = ParentAccount.objects.create(
        email="owner@example.com", phone="+37120000003"
    )
    intruder = ParentAccount.objects.create(
        email="intruder@example.com", phone="+37120000004"
    )
    app = _make_application(owner)
    client = _verified_client(intruder)

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code in {403, 404}
    assert not Document.objects.filter(application=app).exists()


def test_post_rejects_invalid_kind():
    account = ParentAccount.objects.create(
        email="kind@example.com", phone="+37120000005"
    )
    app = _make_application(account)
    client = _verified_client(account)

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "not_a_real_kind", "file": upload},
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert payload["error"] == "invalid_kind"


def test_post_rejects_missing_file():
    account = ParentAccount.objects.create(
        email="missing@example.com", phone="+37120000006"
    )
    app = _make_application(account)
    client = _verified_client(account)

    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity"},
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert payload["error"] == "missing_file"


def test_post_rejects_oversized_file(settings):
    settings.DOCUMENT_UPLOAD_MAX_BYTES = 1024

    account = ParentAccount.objects.create(
        email="big@example.com", phone="+37120000007"
    )
    app = _make_application(account)
    client = _verified_client(account)

    upload = SimpleUploadedFile(
        "big.png", _png_bytes(size=2048), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code == 413
    payload = json.loads(response.content)
    assert payload["error"] == "file_too_large"


def test_post_rejects_disallowed_content_type():
    account = ParentAccount.objects.create(
        email="ct@example.com", phone="+37120000008"
    )
    app = _make_application(account)
    client = _verified_client(account)

    upload = SimpleUploadedFile(
        "doc.exe", b"\x00\x01\x02", content_type="application/x-msdownload"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert payload["error"] == "invalid_content_type"


def test_post_rejects_missing_csrf_when_enforced():
    """With CSRF enforcement, a token-less POST must be rejected."""
    account = ParentAccount.objects.create(
        email="csrf@example.com", phone="+37120000009"
    )
    app = _make_application(account)
    client = Client(enforce_csrf_checks=True)
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.id
    session.save()

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code == 403


def test_post_replaces_prior_active_document_of_same_kind(settings):
    """Re-upload soft-deletes the prior active doc of the same kind."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = ParentAccount.objects.create(
        email="replace@example.com", phone="+37120000010"
    )
    app = _make_application(account)
    client = _verified_client(account)

    # First upload
    with patch("apps.registrations.views.enqueue_ocr_job"):
        first = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={
                "kind": "guardian_identity",
                "file": SimpleUploadedFile(
                    "a.png", _png_bytes(), content_type="image/png"
                ),
            },
        )
    assert first.status_code == 201
    first_id = json.loads(first.content)["document_id"]

    # Second upload of the same kind
    with patch("apps.registrations.views.enqueue_ocr_job"):
        second = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={
                "kind": "guardian_identity",
                "file": SimpleUploadedFile(
                    "b.png", _png_bytes(), content_type="image/png"
                ),
            },
        )
    assert second.status_code == 201
    second_id = json.loads(second.content)["document_id"]
    assert second_id != first_id

    # Prior should be soft-deleted
    prior = Document.objects.get(pk=first_id)
    assert prior.deleted_at is not None
    current = Document.objects.get(pk=second_id)
    assert current.deleted_at is None


def test_post_member_portrait_does_not_enqueue_ocr():
    account = ParentAccount.objects.create(
        email="portrait@example.com", phone="+37120000011"
    )
    app = _make_application(account)
    client = _verified_client(account)

    enqueued: list[int] = []

    upload = SimpleUploadedFile(
        "portrait.png", _png_bytes(), content_type="image/png"
    )
    with patch(
        "apps.registrations.views.enqueue_ocr_job",
        side_effect=lambda did: enqueued.append(did),
    ):
        response = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={"kind": "member_portrait", "file": upload},
        )

    assert response.status_code == 201
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "not_requested"
    assert enqueued == []


# ---------------------------------------------------------------------------
# Source-level contract checks on static/js/async_upload.js
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402  (import after pytestmark is fine here)

JS_PATH = Path(__file__).resolve().parents[2] / "static" / "js" / "async_upload.js"


def _read_async_upload_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


class TestAsyncUploadJsContract:
    """Source-level contract checks on static/js/async_upload.js.

    The file ships unbundled and there is no JS test runner; substring
    sniffs are the simplest stable assertion for "this hook exists".
    """

    @staticmethod
    def _read_js() -> str:
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "static" / "js" / "async_upload.js"
        return path.read_text(encoding="utf-8")

    def test_polling_checks_document_hidden(self):
        source = _read_async_upload_js()
        assert "document.hidden" in source, (
            "Polling must check document.hidden so it can pause when the tab "
            "is in the background (P4 Slice B requirement)."
        )

    def test_polling_resumes_on_visibilitychange(self):
        source = _read_async_upload_js()
        assert "visibilitychange" in source, (
            "Polling must register a visibilitychange listener so a paused "
            "poll resumes when the tab becomes visible again."
        )

    def test_polling_listener_uses_once_semantics(self):
        """The visibilitychange listener must remove itself after firing once."""
        source = _read_async_upload_js()
        assert "{ once: true }" in source or "removeEventListener" in source, (
            "Visibilitychange listener must be one-shot — use `{ once: true }` "
            "or call removeEventListener inside the handler."
        )

    def test_pending_state_renders_branded_spinner_markup(self):
        source = _read_async_upload_js()
        # The spinner markup the JS injects must carry the same DOM hook the
        # parent_ui/includes/spinner.html partial uses, so future CSS and JS
        # controllers can attach to a single selector.
        assert "fk-spinner" in source
        assert "data-spinner" in source

    def test_completed_state_renders_branded_toast_markup(self):
        source = _read_async_upload_js()
        assert "fk-toast" in source
        assert "data-toast" in source
        # The success copy must be Latvian and reference the recognized person.
        assert "Persona atpazīta" in source
        assert "Dokumenta apstrāde pabeigta" in source

    def test_failed_state_consumes_server_supplied_latvian_message(self):
        source = _read_async_upload_js()
        # The JS must read the new ocr_error_message field instead of
        # synthesizing an English-free template inline.
        assert "ocr_error_message" in source
        # The pre-Slice-B raw-text path must be gone.
        assert "'OCR neizdevās ('" not in source

    def test_toast_auto_dismisses(self):
        source = _read_async_upload_js()
        # Auto-dismiss happens via a setTimeout that removes the toast DOM
        # node. We don't pin the exact duration, just that auto-dismiss exists.
        assert "TOAST_AUTO_DISMISS_MS" in source or "auto-dismiss" in source.lower()

    def test_upload_failure_renders_latvian_message_not_raw_code(self):
        source = _read_async_upload_js()
        # The old path interpolated the raw English error code.
        assert "'Augšupielāde neizdevās (' + err.message" not in source
        # New path uses renderFailure with a stable Latvian sentence.
        assert "Pamēģini vēlreiz vai aizpildi laukus manuāli" in source

    def test_failure_renderer_uses_role_alert_wrapper(self):
        source = _read_async_upload_js()
        # renderFailure must inject a role="alert" wrapper so screen readers
        # announce the failure (the bare <p> slot has no aria-live).
        assert 'role="alert"' in source
        assert "fk-inline-error" in source

    def test_no_ocr_badge_text_is_latvian(self):
        source = _read_async_upload_js()
        # The legacy "No OCR" English literal is gone. Latvian "No OCR
        # dokumenta" replaces it (reads "from the OCR document").
        assert "'No OCR'" not in source
        assert "No OCR dokumenta" in source

    def test_camera_affordance_listener_present(self):
        js = self._read_js()
        assert "data-camera-affordance" in js, (
            "async_upload.js must wire up label[data-camera-affordance]."
        )

    def test_camera_shim_sets_capture_environment(self):
        js = self._read_js()
        assert "'capture'" in js or '"capture"' in js, (
            "Camera shim must setAttribute('capture', ...)"
        )
        assert "'environment'" in js or '"environment"' in js, (
            "Camera shim must set capture value to 'environment'."
        )

    def test_camera_shim_sets_image_accept(self):
        js = self._read_js()
        assert "'image/*'" in js or '"image/*"' in js, (
            "Camera shim must defensively set accept='image/*' on the canonical input."
        )

    def test_camera_shim_calls_preventDefault_and_clicks_input(self):
        js = self._read_js()
        assert "preventDefault" in js, "Camera shim must call event.preventDefault()."
        assert ".click()" in js, "Camera shim must trigger input.click()."

    def test_pointerdown_clears_stale_capture(self):
        js = self._read_js()
        assert "pointerdown" in js, (
            "Slice D needs a pointerdown listener on the non-camera file labels "
            "that clears any stale `capture` attribute left over from a cancelled camera flow."
        )
        assert "removeAttribute('capture')" in js or 'removeAttribute("capture")' in js, (
            "pointerdown listener must call input.removeAttribute('capture')."
        )


class TestParentThemeCssContract:
    """Selectors that the Slice B JS renders into the DOM must have matching
    CSS in parent_theme.css so the markup actually styles."""

    @staticmethod
    def _read_css() -> str:
        path = Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css"
        return path.read_text(encoding="utf-8")

    def test_spinner_selectors_exist(self):
        css = self._read_css()
        for selector in (".fk-spinner", ".fk-spinner__dot", ".fk-spinner__label"):
            assert selector in css, f"Missing CSS selector: {selector}"

    def test_toast_selectors_exist(self):
        css = self._read_css()
        for selector in (".fk-toast", ".fk-toast--success", ".fk-toast__message"):
            assert selector in css, f"Missing CSS selector: {selector}"

    def test_ocr_suggestion_selectors_exist(self):
        css = self._read_css()
        for selector in (
            ".fk-ocr-suggestion",
            ".fk-ocr-suggestion__label",
            ".fk-ocr-suggestion__value",
            ".fk-ocr-suggestion__accept",
            ".fk-ocr-suggestion__dismiss",
        ):
            assert selector in css, f"Missing CSS selector: {selector}"


class TestParentThemeCssContractSliceC:
    """P4 Slice C — CSS hooks for save indicator, consent block, disabled CTA."""

    SECTION_HEADER = "Wizard gating"

    @staticmethod
    def _read_css() -> str:
        path = Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css"
        return path.read_text(encoding="utf-8")

    def _slice_c_section(self) -> str:
        css = self._read_css()
        idx = css.find(self.SECTION_HEADER)
        assert idx != -1, f"Section header containing {self.SECTION_HEADER!r} not found"
        return css[idx:]

    def test_fk_save_indicator_class_defined(self):
        css = self._read_css()
        assert ".fk-save-indicator" in css

    def test_fk_save_indicator_state_variants(self):
        css = self._read_css()
        for variant in ('data-save-state="saving"', 'data-save-state="saved"', 'data-save-state="error"'):
            assert variant in css, f"Missing state selector: {variant}"

    def test_fk_save_indicator_uses_red_token_for_error(self):
        section = self._slice_c_section()
        # The error variant block must reference --fk-red.
        error_idx = section.find('data-save-state="error"')
        assert error_idx != -1
        # Look at the rule body that follows (next ~200 chars should cover it).
        window = section[error_idx : error_idx + 400]
        assert "var(--fk-red)" in window, "Error state must use --fk-red token"

    def test_fk_consent_class_defined(self):
        css = self._read_css()
        assert ".fk-consent" in css

    def test_fk_consent_label_meets_touch_target(self):
        section = self._slice_c_section()
        label_idx = section.find(".fk-consent__label")
        assert label_idx != -1
        window = section[label_idx : label_idx + 400]
        assert re.search(
            r"min-height\s*:\s*44px", window
        ), ".fk-consent__label must declare ≥ 44px touch target"

    def test_disabled_wizard_next_visual_cue(self):
        section = self._slice_c_section()
        assert "[data-wizard-next]" in section
        # Find a rule for the disabled state and confirm it sets opacity + cursor.
        # The selector could be `:disabled` or `[disabled]`.
        has_disabled_selector = (
            "[data-wizard-next]:disabled" in section
            or "[data-wizard-next][disabled]" in section
        )
        assert has_disabled_selector, "Need disabled selector for [data-wizard-next]"
        assert "opacity" in section
        assert "cursor" in section
        assert "not-allowed" in section

    def test_no_new_color_tokens_introduced(self):
        import re

        section = self._slice_c_section()
        # No 6-digit hex literals allowed in the new section.
        matches = re.findall(r"#[0-9a-fA-F]{6}\b", section)
        assert matches == [], f"Unexpected new hex color literals in Slice C section: {matches}"


class TestParentThemeCssContractSliceD:
    """P4 Slice D — CSS hooks for upload slots, camera affordance, mobile layout."""

    SECTION_HEADER = "P4 Slice D"

    @staticmethod
    def _read_css() -> str:
        path = Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css"
        return path.read_text(encoding="utf-8")

    def _slice_d_section(self) -> str:
        css = self._read_css()
        idx = css.find(self.SECTION_HEADER)
        assert idx != -1, f"Section header containing {self.SECTION_HEADER!r} not found"
        return css[idx:]

    def test_visually_hidden_class_defined(self):
        section = self._slice_d_section()
        assert ".fk-visually-hidden" in section, "Missing .fk-visually-hidden"
        # Must be accessible (screen-reader-only), not display:none.
        assert "position: absolute" in section or "clip:" in section, (
            "fk-visually-hidden must use position:absolute / clip technique, "
            "not display:none, so screen readers can still discover the input."
        )

    def test_upload_slot_class_defined(self):
        section = self._slice_d_section()
        assert ".fk-upload-slot" in section, "Missing .fk-upload-slot"

    def test_camera_only_class_defined_and_hidden_on_fine_pointer(self):
        section = self._slice_d_section()
        assert ".fk-camera-only" in section, "Missing .fk-camera-only"
        assert "@media not (pointer: coarse)" in section, (
            "Missing `@media not (pointer: coarse)` block that hides .fk-camera-only "
            "on devices without a coarse pointer (desktop)."
        )

    def test_checkbox_row_class_defined(self):
        section = self._slice_d_section()
        assert ".fk-checkbox-row" in section, "Missing .fk-checkbox-row"
        # Must enforce 44px touch target.
        import re
        match = re.search(
            r"\.fk-checkbox-row\s*\{[^}]*min-height:\s*44px",
            section,
            re.DOTALL,
        )
        assert match, ".fk-checkbox-row must set min-height: 44px"

    def test_wizard_nav_sticky_modifier_defined(self):
        section = self._slice_d_section()
        assert ".fk-wizard-nav--sticky" in section, "Missing .fk-wizard-nav--sticky"
        assert "position: sticky" in section, (
            "Sticky CTA modifier must use position: sticky inside the appropriate media query."
        )
        assert "(pointer: coarse)" in section, (
            "Sticky CTA must be gated by `(pointer: coarse)` media query."
        )

    def test_fk_button_full_modifier_defined(self):
        # Used by the document_card upload labels so they stretch to the
        # full width of the .fk-upload-slot flex column.
        css = self._read_css()
        match = re.search(
            r"\.fk-button--full\s*\{[^}]*width:\s*100%",
            css,
            re.DOTALL,
        )
        assert match, ".fk-button--full must set width: 100%"
        assert "box-sizing: border-box" in css, (
            ".fk-button--full must use box-sizing: border-box so padding stays "
            "inside the 100% width."
        )

    def test_fk_button_icon_helper_defined(self):
        css = self._read_css()
        assert ".fk-button__icon" in css, (
            "Missing .fk-button__icon helper for the inline SVG icons on upload labels."
        )

    def test_fk_button_small_meets_40px_floor(self):
        # The bumped rule lives inside the Slice D section as an override,
        # OR the existing .fk-button--small rule has been edited to 40px+.
        css = self._read_css()
        match = re.search(
            r"\.fk-button--small\s*\{[^}]*min-height:\s*(\d+)px",
            css,
            re.DOTALL,
        )
        assert match, ".fk-button--small must define a min-height"
        assert int(match.group(1)) >= 40, (
            f".fk-button--small min-height is {match.group(1)}px; "
            "Slice D requires ≥ 40px."
        )

    def test_workspace_container_uses_clamp_padding(self):
        section = self._slice_d_section()
        # Padding-inline declaration on .fk-workspace (or .fk-application-workspace)
        # uses clamp(16px, 4vw, 32px).
        assert "clamp(16px, 4vw, 32px)" in section, (
            "Workspace container must use clamp(16px, 4vw, 32px) padding."
        )

    def test_address_sync_row_stacks_at_mobile(self):
        section = self._slice_d_section()
        # Slice D section must contain a media query block for max-width 720
        # that targets .fk-address-row with flex-direction: column.
        assert ".fk-address-row" in section, (
            "Slice D must define stacking behavior for the address-sync row."
        )

    def test_save_pill_flows_inline_on_mobile(self):
        section = self._slice_d_section()
        # The save-pill (.fk-save-indicator) needs to switch from absolute
        # positioning to static/in-flow on mobile.
        match = re.search(
            r"\.fk-save-indicator[^\{]*\{[^}]*position:\s*static",
            section,
            re.DOTALL,
        )
        assert match, (
            "Slice D must reposition .fk-save-indicator to position: static "
            "on mobile (max-width: 720px)."
        )

