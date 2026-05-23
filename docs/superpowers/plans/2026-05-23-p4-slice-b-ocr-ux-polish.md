# P4 Slice B — P3.5 polish leftovers (OCR UX)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the P3.5 polish backlog — branded spinner during `ocr_running`, one-shot confirmation toast on `ocr_done` with the normalized recognized name, visibility-aware polling, Latvianized failure messages, and CSS polish for the OCR suggestion chip + source badges + new spinner/toast.

**Architecture:**
- All OCR error-code → Latvian-text mapping moves server-side into a single `apps/integrations/ocr_messages.py` module, surfaced through the existing status polling endpoint as a new `ocr_error_message` field. The JS becomes a dumb renderer.
- `static/js/async_upload.js` swaps the raw-text `progressSlot.textContent = '…'` calls for three small DOM helpers that render the `fk-spinner` partial markup, the `fk-toast` partial markup, and a Latvian inline error from the server-supplied message. Markup is built inside JS (mirroring partial structure) so the existing single-`<p>` progress slot still works as the container.
- Polling pauses on `document.visibilitychange` when hidden; the next-scheduled `setTimeout` is cleared and a one-shot `visibilitychange` listener resumes polling when visible.
- CSS additions land in `static/css/parent_theme.css` next to the existing `fk-source-badge` / `fk-ocr-suggestion` selectors. No new CSS file.

**Tech Stack:** Django 5.x, Python 3.12, vanilla ES5-style JS (matches existing `async_upload.js` style — no build step), CSS3. `uv run` for everything Python.

---

## File Structure

**Create:**
- `apps/integrations/ocr_messages.py` — pure mapping `OCR_ERROR_MESSAGES_LV: dict[str, str]` plus `get_ocr_error_message(code: str) -> str` helper with a fallback string.
- `tests/integrations/test_ocr_messages.py` — unit tests covering every known code + fallback for unknown.

**Modify:**
- `apps/registrations/views.py` — `document_ocr_status` adds `"ocr_error_message"` to the JSON response when `ocr_status == FAILED`.
- `apps/integrations/ocr.py` — no change. The 6 known error codes already live here; the new module imports the canonical list from this module via a string constant set.
- `static/js/async_upload.js` — replaces the inline raw-text rendering with three new render helpers; adds visibility-aware polling; consumes the new `ocr_error_message` field.
- `static/css/parent_theme.css` — appends a new "OCR async UX (P4 Slice B)" CSS section: `.fk-spinner`, `.fk-toast`, refined `.fk-ocr-suggestion`, polish on `.fk-source-badge`.
- `tests/registrations/test_document_status_endpoint.py` — new tests for the `ocr_error_message` field.
- `tests/registrations/test_async_document_upload.py` (or new sibling file) — assertions on the JS source file: it must reference `document.hidden`, `visibilitychange`, the spinner / toast class names, and consume `ocr_error_message`.

**Out of scope for Slice B** (lands in later slices):
- Step-gated wizard validation + draft auto-save (Slice C).
- Personal data consent gate (Slice C).
- Camera capture and mobile-first workspace (Slice D).
- Entry / chooser / portal polish (Slice E).

---

## Task 1: Latvianized OCR error message map (server-side)

**Files:**
- Create: `apps/integrations/ocr_messages.py`
- Test: `tests/integrations/test_ocr_messages.py`

The six known error codes already live in `apps/integrations/ocr.py::_classify_exception` and are documented in AGENTS.md. Centralize the Latvian copy in one pure module, with a fallback string for unknown codes.

- [ ] **Step 1: Write the failing test**

```python
# tests/integrations/test_ocr_messages.py
"""Unit tests for OCR error-code → Latvian-message mapping."""

import pytest

from apps.integrations.ocr_messages import (
    OCR_ERROR_MESSAGES_LV,
    get_ocr_error_message,
)


KNOWN_CODES = (
    "provider_misconfigured",
    "auth_failed",
    "rate_limited",
    "request_timeout",
    "provider_unavailable",
    "invalid_response",
)


@pytest.mark.parametrize("code", KNOWN_CODES)
def test_every_known_code_has_a_latvian_message(code):
    assert code in OCR_ERROR_MESSAGES_LV
    msg = OCR_ERROR_MESSAGES_LV[code]
    assert isinstance(msg, str)
    assert msg  # non-empty
    # Latvian copy must not be a copy of the code itself.
    assert msg != code
    # Sanity: messages must end with a period or ellipsis (full sentence).
    assert msg.rstrip().endswith((".", "…"))


def test_get_returns_mapped_message_for_known_code():
    assert get_ocr_error_message("auth_failed") == OCR_ERROR_MESSAGES_LV["auth_failed"]


def test_get_returns_generic_fallback_for_unknown_code():
    message = get_ocr_error_message("totally_unknown_code")
    # Fallback is the same as for provider_unavailable's neighborhood —
    # generic "could not process, please try again or fill manually".
    assert isinstance(message, str)
    assert message
    assert "manuāli" in message.lower() or "vēlāk" in message.lower()


def test_get_returns_generic_fallback_for_empty_code():
    assert get_ocr_error_message("") == get_ocr_error_message("unknown")
```

- [ ] **Step 2: Verify the test fails**

Run: `uv run pytest tests/integrations/test_ocr_messages.py -v`

Expect: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# apps/integrations/ocr_messages.py
"""Latvian copy for OCR error codes surfaced to parents.

The codes themselves are produced by `apps.integrations.ocr._classify_exception`
and persisted on `Document.ocr_error_code`. Keeping the user-facing copy in
one pure module means JS only renders text — no embedded English fallbacks,
no per-code branching on the client.
"""

from __future__ import annotations

# Order matches the classifier; copy is Latvian-only by project policy.
OCR_ERROR_MESSAGES_LV: dict[str, str] = {
    "provider_misconfigured": (
        "OCR pakalpojums šobrīd nav konfigurēts. "
        "Lūdzu, aizpildi laukus manuāli."
    ),
    "auth_failed": (
        "Neizdevās autorizēties OCR pakalpojumā. "
        "Lūdzu, aizpildi laukus manuāli — mēs to atrisināsim īsumā."
    ),
    "rate_limited": (
        "OCR pakalpojums šobrīd ir noslogots. "
        "Pamēģini pēc brīža vai aizpildi laukus manuāli."
    ),
    "request_timeout": (
        "OCR atbilde nepienāca laikā. "
        "Pamēģini vēlreiz vai aizpildi laukus manuāli."
    ),
    "provider_unavailable": (
        "OCR pakalpojums šobrīd nav pieejams. "
        "Pamēģini vēlāk vai aizpildi laukus manuāli."
    ),
    "invalid_response": (
        "Saņēmām neparedzētu atbildi no OCR pakalpojuma. "
        "Lūdzu, aizpildi laukus manuāli."
    ),
}


_GENERIC_FALLBACK_LV = (
    "Neizdevās apstrādāt dokumentu automātiski. "
    "Lūdzu, aizpildi laukus manuāli."
)


def get_ocr_error_message(code: str | None) -> str:
    """Return a Latvian message for an OCR error code.

    Unknown or empty codes return a generic "please fill manually" fallback
    so the UI never leaks raw codes to parents.
    """
    if not code:
        return _GENERIC_FALLBACK_LV
    return OCR_ERROR_MESSAGES_LV.get(code, _GENERIC_FALLBACK_LV)
```

- [ ] **Step 4: Verify the tests pass**

Run: `uv run pytest tests/integrations/test_ocr_messages.py -v`

Expect: all parametrized cases + 3 explicit tests pass.

- [ ] **Step 5: Lint + type-check**

Run: `uv run ruff check apps/integrations/ocr_messages.py tests/integrations/test_ocr_messages.py`
Run: `uv run mypy apps/integrations/ocr_messages.py`

Both clean.

- [ ] **Step 6: Commit**

```bash
git add apps/integrations/ocr_messages.py tests/integrations/test_ocr_messages.py
git commit -m "feat(integrations): centralize Latvian OCR error messages with generic fallback"
```

---

## Task 2: Surface `ocr_error_message` in the status endpoint

**Files:**
- Modify: `apps/registrations/views.py` — `document_ocr_status` (line ~682-706)
- Test: `tests/registrations/test_document_status_endpoint.py`

- [ ] **Step 1: Read the existing endpoint test to match style**

Run: `uv run pytest tests/registrations/test_document_status_endpoint.py --collect-only -q`

Note the helper / fixture pattern used. The new tests reuse it.

- [ ] **Step 2: Write the failing tests**

Append to `tests/registrations/test_document_status_endpoint.py`:

```python
def test_status_endpoint_includes_latvian_error_message_when_failed(client, db):
    """FAILED status response must carry ocr_error_message in Latvian."""
    from apps.integrations.ocr_messages import OCR_ERROR_MESSAGES_LV

    # Use the existing helper used by the file's failed-status test.
    application, document, account = _make_failed_document(error_code="auth_failed")
    _login(client, account)

    resp = client.get(
        f"/applications/{application.id}/documents/{document.id}/status/"
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ocr_status"] == "failed"
    assert body["ocr_error_code"] == "auth_failed"
    assert body["ocr_error_message"] == OCR_ERROR_MESSAGES_LV["auth_failed"]


def test_status_endpoint_emits_fallback_message_for_unknown_failure_code(client, db):
    """Unknown error code still produces a usable Latvian fallback message."""
    application, document, account = _make_failed_document(
        error_code="totally_bogus_value_not_in_mapping",
    )
    _login(client, account)

    resp = client.get(
        f"/applications/{application.id}/documents/{document.id}/status/"
    )

    body = resp.json()
    assert "ocr_error_message" in body
    assert "manuāli" in body["ocr_error_message"].lower()


def test_status_endpoint_omits_error_message_when_status_not_failed(client, db):
    """ocr_error_message must NOT appear on running/completed payloads."""
    application, document, account = _make_pending_document()
    _login(client, account)

    resp = client.get(
        f"/applications/{application.id}/documents/{document.id}/status/"
    )

    body = resp.json()
    assert "ocr_error_message" not in body
```

If the existing module does not already define `_make_failed_document` / `_make_pending_document` / `_login` helpers in this exact shape, **read the file** and adapt: use the same factory pattern the file currently uses. Do not invent new fixtures.

- [ ] **Step 3: Run tests to confirm failure**

Run: `uv run pytest tests/registrations/test_document_status_endpoint.py -k "error_message or fallback or omits_error_message" -v`

Expect: FAIL (field missing).

- [ ] **Step 4: Wire the field into the view**

In `apps/registrations/views.py`, the existing `document_ocr_status` block (around line 698-706) builds:

```python
    payload: dict[str, object] = {
        "ocr_status": document.ocr_status,
        "extracted_fields": _ocr_extracted_fields(document)
        if document.ocr_status == Document.OcrStatus.COMPLETED
        else {},
    }
    if document.ocr_status == Document.OcrStatus.FAILED and document.ocr_error_code:
        payload["ocr_error_code"] = document.ocr_error_code
```

Add to the imports at the top of the file:

```python
from apps.integrations.ocr_messages import get_ocr_error_message
```

Extend the FAILED branch so it also emits `ocr_error_message`. The condition should fire on `FAILED` regardless of whether `ocr_error_code` is set (so the parent always sees the fallback if the worker forgot to set a code):

```python
    if document.ocr_status == Document.OcrStatus.FAILED:
        if document.ocr_error_code:
            payload["ocr_error_code"] = document.ocr_error_code
        payload["ocr_error_message"] = get_ocr_error_message(document.ocr_error_code)
```

- [ ] **Step 5: Run the new endpoint tests**

Run: `uv run pytest tests/registrations/test_document_status_endpoint.py -v`

Expect: all green.

- [ ] **Step 6: Regression sweep**

Run: `uv run pytest tests/registrations/ tests/integrations/ -q`

Expect: green.

- [ ] **Step 7: Lint + type-check**

Run: `uv run ruff check apps/registrations/views.py tests/registrations/test_document_status_endpoint.py`
Run: `uv run mypy apps/registrations/views.py`

Both clean.

- [ ] **Step 8: Commit**

```bash
git add apps/registrations/views.py tests/registrations/test_document_status_endpoint.py
git commit -m "feat(registrations): expose Latvian ocr_error_message on status polling endpoint"
```

---

## Task 3: Visibility-aware polling in `async_upload.js`

**Files:**
- Modify: `static/js/async_upload.js`
- Test: `tests/registrations/test_async_document_upload.py` (extend with JS-source assertions)

The current polling uses `setTimeout(..., nextInterval)` unconditionally and keeps polling even when the tab is hidden. P4 spec: pause when `document.visibilityState === 'hidden'`; resume on `visibilitychange`.

Approach: keep the existing recursive `pollStatus` shape; before scheduling the next `setTimeout`, check `document.hidden`. If hidden, register a one-shot `visibilitychange` listener that, when the tab returns to visible, immediately re-invokes `pollStatus`. The listener removes itself on first fire.

- [ ] **Step 1: Write the failing JS-source contract tests**

Append to `tests/registrations/test_async_document_upload.py` (a new test class is fine):

```python
from pathlib import Path

import pytest


JS_PATH = Path(__file__).resolve().parents[2] / "static" / "js" / "async_upload.js"


def _read_async_upload_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


class TestAsyncUploadJsContract:
    """Source-level contract checks. The file ships as static JS with no
    bundler, so a substring sniff is the simplest stable assertion."""

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
        """The visibilitychange listener must remove itself after firing once
        to avoid accumulating listeners across multiple pauses."""
        source = _read_async_upload_js()
        # Either `{ once: true }` option or explicit removeEventListener.
        assert "{ once: true }" in source or "removeEventListener" in source, (
            "Visibilitychange listener must be one-shot — use `{ once: true }` "
            "or call removeEventListener inside the handler."
        )
```

- [ ] **Step 2: Verify the new tests fail**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract -v`

Expect: 3 FAIL.

- [ ] **Step 3: Add visibility-aware polling**

Open `static/js/async_upload.js`. Locate the existing `pollStatus` function (around line 120-151). Replace the `setTimeout(...)` block in the "still pending/running" branch so it consults `document.hidden`:

Before:
```javascript
        // Still pending/running — keep polling with mild backoff.
        var nextInterval = Math.min(intervalMs + 500, POLL_MAX_MS);
        setProgressLabel(progressSlot, 'OCR notiek…');
        setTimeout(function () {
          pollStatus(documentId, progressSlot, deadline, nextInterval);
        }, nextInterval);
```

After:
```javascript
        // Still pending/running — keep polling with mild backoff.
        var nextInterval = Math.min(intervalMs + 500, POLL_MAX_MS);
        setProgressLabel(progressSlot, 'OCR notiek…');
        scheduleNextPoll(documentId, progressSlot, deadline, nextInterval);
```

In the `.catch(...)` branch, do the same substitution.

Add the helper near the top of the IIFE (just below `pollStatus` is fine, but before it would also work since JS hoists function declarations):

```javascript
  function scheduleNextPoll(documentId, progressSlot, deadline, intervalMs) {
    // Pause polling when the tab is hidden — the browser already throttles
    // setTimeout in background tabs, but resuming on visibilitychange gives
    // a snappier user experience when the parent comes back to the tab.
    if (document.hidden) {
      var resume = function () {
        document.removeEventListener('visibilitychange', resume);
        pollStatus(documentId, progressSlot, deadline, intervalMs);
      };
      document.addEventListener('visibilitychange', resume, { once: true });
      return;
    }
    setTimeout(function () {
      pollStatus(documentId, progressSlot, deadline, intervalMs);
    }, intervalMs);
  }
```

(The `{ once: true }` option AND the explicit `removeEventListener` inside the handler are both kept — `{ once: true }` is the modern idiom and `removeEventListener` is defensive against older browsers that ignore the option dictionary.)

- [ ] **Step 4: Run the JS-contract tests**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract -v`

Expect: all 3 pass.

- [ ] **Step 5: Smoke the rest of the suite**

Run: `uv run pytest tests/registrations/ -q`

Expect: green. If a pre-existing test asserts the old "setTimeout" placement, update it to match the new shape (only if it asserts behavior that genuinely changed).

- [ ] **Step 6: Commit**

```bash
git add static/js/async_upload.js tests/registrations/test_async_document_upload.py
git commit -m "feat(async-upload): pause OCR polling when tab is hidden; resume on visibilitychange"
```

---

## Task 4: Branded spinner + OCR-done toast + Latvianized error rendering in JS

**Files:**
- Modify: `static/js/async_upload.js`
- Test: `tests/registrations/test_async_document_upload.py`

Three rendering changes inside the same JS file:

1. While `ocr_status === 'pending' | 'running'`, the progress slot renders the branded spinner markup (matches the `templates/parent_ui/includes/spinner.html` partial: `<div class="fk-spinner" role="status" aria-live="polite" data-spinner><span class="fk-spinner__dot" aria-hidden="true"></span><span class="fk-spinner__label">Apstrādājam dokumentu…</span></div>`).
2. On `ocr_status === 'completed'`, render an auto-dismissing toast: `Dokumenta apstrāde pabeigta. Persona atpazīta kā <First Last>.` if the extraction supplied a name, otherwise `Dokumenta apstrāde pabeigta.` The toast lives in the same progress slot, auto-dismisses after 4 seconds, and is also dismissed on the next user action against any input on the page.
3. On `ocr_status === 'failed'`, render the Latvian message from `payload.ocr_error_message` (fallback: the existing English-free string) inside the existing `data-state="failed"` `<p>`. Drop the `'OCR neizdevās (' + errorCode + ')'` raw-text path entirely.

- [ ] **Step 1: Write the failing JS-source contract tests**

Append to the same `TestAsyncUploadJsContract` class:

```python
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
        # The auto-dismiss happens via a setTimeout that removes the toast DOM
        # node. We don't pin the exact duration, just that auto-dismiss exists.
        assert "TOAST_AUTO_DISMISS_MS" in source or "auto-dismiss" in source.lower()
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract -v`

Expect: 4 new tests FAIL.

- [ ] **Step 3: Add three render helpers to `async_upload.js`**

Inside the existing IIFE, just below `setProgressLabel` (around line 50), add:

```javascript
  var TOAST_AUTO_DISMISS_MS = 4000;

  function renderSpinner(slot, label) {
    if (!slot) return;
    slot.removeAttribute('hidden');
    slot.setAttribute('data-state', 'running');
    slot.innerHTML =
      '<div class="fk-spinner" role="status" aria-live="polite" data-spinner>'
      + '<span class="fk-spinner__dot" aria-hidden="true"></span>'
      + '<span class="fk-spinner__label"></span>'
      + '</div>';
    slot.querySelector('.fk-spinner__label').textContent =
      label || 'Apstrādājam dokumentu…';
  }

  function renderSuccessToast(slot, recognizedName) {
    if (!slot) return;
    slot.removeAttribute('hidden');
    slot.setAttribute('data-state', 'completed');
    var message = recognizedName
      ? ('Dokumenta apstrāde pabeigta. Persona atpazīta kā ' + recognizedName + '.')
      : 'Dokumenta apstrāde pabeigta.';
    slot.innerHTML =
      '<div class="fk-toast fk-toast--success" role="status" aria-live="polite" '
      + 'data-toast data-toast-tone="success">'
      + '<span class="fk-toast__message"></span>'
      + '</div>';
    slot.querySelector('.fk-toast__message').textContent = message;
    // Auto-dismiss after a short delay.
    setTimeout(function () { dismissToast(slot); }, TOAST_AUTO_DISMISS_MS);
  }

  function dismissToast(slot) {
    if (!slot) return;
    var toast = slot.querySelector('[data-toast]');
    if (toast) toast.remove();
    if (!slot.children || slot.children.length === 0) {
      slot.setAttribute('hidden', '');
    }
  }

  function renderFailure(slot, message) {
    if (!slot) return;
    slot.removeAttribute('hidden');
    slot.setAttribute('data-state', 'failed');
    slot.textContent = message
      || 'Neizdevās apstrādāt dokumentu automātiski. Lūdzu, aizpildi laukus manuāli.';
  }
```

- [ ] **Step 4: Replace the three call-sites in `pollStatus`**

The completed branch (line ~129) currently does:
```javascript
        if (payload.ocr_status === 'completed') {
          setProgressLabel(progressSlot, 'OCR pabeigts');
          applyExtractedFields(payload.extracted_fields || {});
          return;
        }
```

Replace with:
```javascript
        if (payload.ocr_status === 'completed') {
          var fields = payload.extracted_fields || {};
          var name = fields.guardian_full_name || fields.member_full_name || '';
          renderSuccessToast(progressSlot, name);
          applyExtractedFields(fields);
          return;
        }
```

The failed branch (line ~134):
```javascript
        if (payload.ocr_status === 'failed') {
          renderError(progressSlot, payload.ocr_error_code);
          return;
        }
```

Replace with:
```javascript
        if (payload.ocr_status === 'failed') {
          renderFailure(progressSlot, payload.ocr_error_message);
          return;
        }
```

The pending/running branch sets `'OCR notiek…'` via `setProgressLabel`. Replace with `renderSpinner(progressSlot)`:
```javascript
        // Still pending/running — keep polling with mild backoff.
        var nextInterval = Math.min(intervalMs + 500, POLL_MAX_MS);
        renderSpinner(progressSlot);
        scheduleNextPoll(documentId, progressSlot, deadline, nextInterval);
```

The deadline-exceeded branch (top of `pollStatus`) keeps text — that's a long-press informational message, not a transient running state. Leave the existing setProgressLabel call:
```javascript
    if (Date.now() > deadline) {
      setProgressLabel(progressSlot, 'OCR aizņem ilgāk nekā parasti — vari turpināt aizpildīt manuāli.');
      return;
    }
```

In the `pollPendingDocumentsOnLoad` IIFE (around line 230) replace `setProgressLabel(slot, 'OCR notiek…')` with `renderSpinner(slot)`. Same for the upload-success branch at line 190.

Finally, delete the old `renderError` function (around line 56-61) — it's superseded by `renderFailure`.

- [ ] **Step 5: Run the JS-contract tests**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract -v`

Expect: all 7 pass (3 from Task 3 + 4 from Task 4).

- [ ] **Step 6: Run the full polling/upload suite + integrations + registrations**

Run: `uv run pytest tests/registrations/ tests/integrations/ -q`

Expect: green. Watch for any test that asserted the literal raw-text strings (`'OCR notiek…'`, `'OCR pabeigts'`, `'OCR neizdevās'`). Update only the assertions that pinned the old wording — leave assertions on behavior alone.

- [ ] **Step 7: Commit**

```bash
git add static/js/async_upload.js tests/registrations/test_async_document_upload.py
git commit -m "feat(async-upload): branded spinner, OCR-done toast with recognized name, server-supplied error copy"
```

---

## Task 5: CSS polish — spinner, toast, OCR suggestion chip, source badge

**Files:**
- Modify: `static/css/parent_theme.css`
- Test: `tests/registrations/test_async_document_upload.py` (CSS-source assertion class)

CSS-only polish. Add a new section to `parent_theme.css` for `.fk-spinner` / `.fk-toast`. Refine the existing `.fk-ocr-suggestion` and `.fk-source-badge` blocks for visual consistency (same border radius family, calmer color usage). No JS or template changes.

Visual goals (calibrated against tokens.md):
- Spinner uses the `--fk-blue` token for the rotating dot; label uses `--fk-text` muted at 80% opacity.
- Toast uses `--fk-soft-blue` background, `--fk-blue` text, `border-radius: var(--fk-radius-md)`, a subtle 1px border in `--fk-blue` at 15% alpha. Success variant only — warning/neutral land later.
- OCR suggestion chip aligns with the badge family: same pill border-radius (`999px`), same padding scale.
- Source badge: tighten the "Active / Inactive" muted contrast so green/blue badges don't dominate the section header.

- [ ] **Step 1: Write the failing CSS-source contract test**

Append a new test class to `tests/registrations/test_async_document_upload.py`:

```python
class TestParentThemeCssContract:
    """Selectors that future Slice B JS already references must exist in
    parent_theme.css so the markup actually styles."""

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
```

- [ ] **Step 2: Confirm failure**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContract -v`

Expect: the spinner / toast / fk-ocr-suggestion__* tests fail (the existing CSS has `.fk-source-badge` but no spinner/toast yet, and the OCR suggestion chip selectors are referenced from JS but not styled).

- [ ] **Step 3: Append the new CSS section**

At the end of `static/css/parent_theme.css`, append:

```css

/* ── OCR async UX (P4 Slice B) ── */

.fk-spinner {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--fk-radius-md);
  background: color-mix(in srgb, var(--fk-soft-blue) 70%, transparent);
  color: var(--fk-blue);
  font-size: 13px;
}

.fk-spinner__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid var(--fk-blue);
  border-top-color: transparent;
  animation: fk-spinner-rotate 0.9s linear infinite;
}

.fk-spinner__label {
  opacity: 0.85;
  font-weight: 600;
}

@keyframes fk-spinner-rotate {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .fk-spinner__dot { animation: none; }
}

.fk-toast {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--fk-radius-md);
  border: 1px solid color-mix(in srgb, var(--fk-blue) 15%, transparent);
  background: var(--fk-soft-blue);
  color: var(--fk-blue);
  font-size: 13px;
  font-weight: 600;
  animation: fk-toast-fade-in 0.2s ease-out;
}

.fk-toast--success {
  background: #eaf8ef;
  color: #22a85a;
  border-color: color-mix(in srgb, #22a85a 18%, transparent);
}

.fk-toast--warning {
  background: #fff8e1;
  color: #b8860b;
  border-color: color-mix(in srgb, #b8860b 22%, transparent);
}

.fk-toast__message { line-height: 1.35; }

@keyframes fk-toast-fade-in {
  from { opacity: 0; transform: translateY(2px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* OCR suggestion chip — align with badge family. */

.fk-ocr-suggestion {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 6px 0 0 8px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--fk-soft-blue);
  color: var(--fk-blue);
  font-size: 12px;
  font-weight: 600;
}

.fk-ocr-suggestion__label { opacity: 0.75; }
.fk-ocr-suggestion__value { font-weight: 700; }

.fk-ocr-suggestion__accept,
.fk-ocr-suggestion__dismiss {
  appearance: none;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}

.fk-ocr-suggestion__accept {
  background: var(--fk-blue);
  color: var(--fk-white);
}

.fk-ocr-suggestion__accept:hover { filter: brightness(1.05); }
.fk-ocr-suggestion__dismiss:hover { background: rgba(15, 8, 81, 0.06); }
```

- [ ] **Step 4: Run the CSS-contract test**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContract -v`

Expect: all 3 pass.

- [ ] **Step 5: Lint (no Python touched here, so skip ruff/mypy; just confirm pytest)**

Run: `uv run pytest tests/registrations/ -q`

Expect: green.

- [ ] **Step 6: Commit**

```bash
git add static/css/parent_theme.css tests/registrations/test_async_document_upload.py
git commit -m "feat(parent-ui-css): style fk-spinner, fk-toast, and OCR suggestion chip"
```

---

## Task 6: Full verification + AGENTS.md note

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`

Expect: green.

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`

Expect: green.

- [ ] **Step 3: Type check**

Run: `uv run mypy .`

Expect: green.

- [ ] **Step 4: AGENTS.md update**

In `AGENTS.md`, append a new sub-section immediately after the "P4 Slice A delivered" block (do NOT replace Slice A):

```markdown
### P4 Slice B delivered — P3.5 polish leftovers (OCR UX)
- `apps/integrations/ocr_messages.py` — centralized Latvian error-code → message map plus generic fallback (`get_ocr_error_message`). Six known codes covered (`provider_misconfigured`, `auth_failed`, `rate_limited`, `request_timeout`, `provider_unavailable`, `invalid_response`); unknown / missing codes fall back to a generic "fill manually" message. No English fallback anywhere in the parent flow.
- Status polling endpoint (`/applications/<id>/documents/<doc_id>/status/`) now emits `ocr_error_message` on FAILED responses alongside the existing `ocr_error_code`. Running / completed payloads do not carry it.
- `static/js/async_upload.js` no longer renders raw text status. Running state uses the `fk-spinner` markup; completed state uses an auto-dismissing `fk-toast` carrying `"Dokumenta apstrāde pabeigta. Persona atpazīta kā <Name>."` (name comes pre-normalized from Slice A); failed state renders the server-supplied Latvian message. Polling pauses when `document.hidden === true` and resumes on a one-shot `visibilitychange` listener.
- `static/css/parent_theme.css` ships full styling for `.fk-spinner`, `.fk-toast` (+ success / warning variants), and the previously-unstyled `.fk-ocr-suggestion` chip family. `prefers-reduced-motion` disables the spinner animation.
```

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): record P4 Slice B (OCR UX polish) delivery"
```

- [ ] **Step 6: Confirm clean tree**

Run: `git status` and `git log --oneline -7`

Expect: clean tree; commits in order.

---

## Self-review checklist (for the implementer, not part of the work)

- Server-side `ocr_error_message` is the only place Latvian error copy lives. JS never synthesizes its own message.
- Visibility-aware polling uses both `{ once: true }` AND `removeEventListener` defensively; the listener cannot accumulate across multiple pauses.
- The branded spinner and the toast both attach their DOM hooks (`data-spinner`, `data-toast`, `data-toast-tone`) — Slices C/E partials and any future controller can attach via the same hooks.
- Auto-dismiss uses `setTimeout` not animation-end; the toast remains accessible to screen readers via `aria-live="polite"` even after the visual disappears (which is fine; SR has already announced).
- No mobile-first layout, no consent gate, no wizard validation — those belong to later slices.
