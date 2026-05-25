# P4 Slice D — Camera capture + mobile-first workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land HTML-native camera capture on document-upload slots and finish the mobile-first workspace polish (sticky CTA, touch-target floors, container padding, save-pill mobile flow) without touching Slice C gating/auto-save/consent behavior.

**Architecture:** Each document slot keeps a single canonical hidden `<input type="file">`. Two visible `<label for>` controls (file + camera) wrap that input. A small JS shim toggles `capture="environment"`/`accept="image/*"` on the canonical input when the camera label is clicked, then calls `input.click()` — no second input, so wizard.js step-gating is untouched. The "Uzņemt attēlu" label is wrapped in `<span class="fk-camera-only">` and hidden via CSS on non-coarse pointers (`@media not (pointer: coarse)`). Mobile layout work fills in existing breakpoint blocks (`max-width: 720px`, `420px`); no JS layout logic.

**Tech Stack:** Django 5 templates, plain CSS (no preprocessor), vanilla JS (no framework), pytest + Django test client.

---

## Pre-flight: spec + working tree

- Spec: `docs/superpowers/specs/2026-05-25-p4-slice-d-camera-and-mobile-design.md` (read this first if context is thin).
- Branch: work directly on `main` per project policy. Each task ends with a commit.
- Baseline: `uv run pytest -q` → 762 passed before this slice. After Slice D the expected count is ~785–795 (the plan adds ~25 assertions, removes ~3 obsolete ones).

## File map

**Modified:**
- `apps/registrations/forms.py` — move `member_portrait_document` from member section to documents section; add `fk-visually-hidden` class to all three FileField widgets.
- `templates/parent_ui/includes/document_card.html` — full rewrite to own upload UI (canonical input + file label + camera label).
- `templates/registrations/application_workspace.html` — skip file fields in the documents section's `bound_fields` loop; add `fk-wizard-nav--sticky` class to per-step nav rows; mark save-status pill container with a mobile-flow hook.
- `static/css/parent_theme.css` — add new selectors (`.fk-visually-hidden`, `.fk-upload-slot`, `.fk-camera-only`, `.fk-checkbox-row`, `.fk-wizard-nav--sticky`); bump touch-target minimums; add mobile media-query refinements; reposition save-status pill on mobile.
- `static/js/async_upload.js` — append camera-affordance shim + pointerdown reset listener.
- Existing tests in `tests/registrations/test_document_state_presentation.py` — update `TestReplaceActionVisible` and `TestReplaceUploadLinksPointToFileInputs` classes for the new partial shape.

**New test additions (no new files):**
- `tests/registrations/test_document_state_presentation.py` — new tests under a `TestUploadSlotMarkup` class.
- `tests/registrations/test_application_workspace_template.py` — new tests for sticky-CTA marker, container padding, and the "no duplicate file input" guard.
- `tests/registrations/test_async_document_upload.py` — extend `TestAsyncUploadJsContract` with camera-shim assertions; extend `TestParentThemeCssContract` (or add a sibling class) with the new selectors.
- `tests/registrations/test_wizard_js_contract.py` — verify wizard.js still treats file inputs the same way (regression guard).

**Untouched (out of scope per spec):**
- `apps/registrations/views.py`, `apps/registrations/services.py` — no behavior change.
- `apps/integrations/*` — no behavior change.
- Schema, migrations — none.
- Admin templates — none.
- Entry/chooser/portal templates — Slice E.

---

## Task 1: Move `member_portrait_document` into the documents section

**Why:** The new document_card partial owns the upload UI for *every* document kind. The portrait kind is currently rendered as a file input inside the member step (via `form_field.html`'s file branch). Moving the field into the documents section keeps "documents step = every document" semantically consistent and gives the portrait the same camera/file affordance as the identity docs.

**Files:**
- Modify: `apps/registrations/forms.py:13-43` (section_order tuple).
- Test: `tests/registrations/test_document_state_presentation.py` (add a check that the portrait field lives in the documents section).

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_document_state_presentation.py`:

```python
class TestMemberPortraitInDocumentsSection:
    """P4 Slice D — member portrait lives alongside the identity docs in step 1."""

    def test_member_portrait_field_in_documents_section(self):
        from apps.registrations.forms import RegistrationApplicationForm
        sections = dict(RegistrationApplicationForm.section_order)
        assert "member_portrait_document" in sections["documents"], (
            "member_portrait_document must live in the documents section for "
            "Slice D so its upload UI ships in step 1."
        )
        assert "member_portrait_document" not in sections["member"], (
            "member_portrait_document must no longer live in the member section."
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_document_state_presentation.py::TestMemberPortraitInDocumentsSection -v`
Expected: FAIL with `member_portrait_document must live in the documents section`.

- [ ] **Step 3: Implement — move the field in `section_order`**

In `apps/registrations/forms.py` change:

```python
    section_order = (
        (
            "documents",
            (
                "guardian_identity_document",
                "member_identity_document",
            ),
        ),
```

to:

```python
    section_order = (
        (
            "documents",
            (
                "guardian_identity_document",
                "member_identity_document",
                "member_portrait_document",
            ),
        ),
```

and remove `"member_portrait_document",` from the member-section tuple at line ~41.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_document_state_presentation.py::TestMemberPortraitInDocumentsSection -v`
Expected: PASS.

Also run the full registrations test file to flag downstream breakage:

Run: `uv run pytest tests/registrations/ -q 2>&1 | tail -30`
Expected: some failures in tests that asserted portrait inside the member step. Note the failing test names — they get fixed in Task 10.

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/forms.py tests/registrations/test_document_state_presentation.py
git commit -m "feat(registrations): move member_portrait_document into documents section"
```

---

## Task 2: CSS — add `.fk-visually-hidden`, `.fk-upload-slot`, `.fk-camera-only`, `.fk-checkbox-row`, `.fk-wizard-nav--sticky` selectors

**Why:** New markup in the document card partial (Task 5) and workspace template (Task 7) references these selectors. Land the CSS first so subsequent template tests can rely on the contract.

**Files:**
- Modify: `static/css/parent_theme.css` (append a new "P4 Slice D" section near the end).
- Test: `tests/registrations/test_async_document_upload.py` (add a new `TestParentThemeCssContractSliceD` class alongside the existing `TestParentThemeCssContractSliceC`).

- [ ] **Step 1: Write the failing test**

Append a new class to `tests/registrations/test_async_document_upload.py` (after `TestParentThemeCssContractSliceC`):

```python
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
        # Grep for the rule body containing min-height.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD -v`
Expected: FAIL on every test — `Section header containing 'P4 Slice D' not found`.

- [ ] **Step 3: Implement — append a new section to `static/css/parent_theme.css`**

Append at the end of `static/css/parent_theme.css` (file currently ends around line 1036):

```css

/* ── P4 Slice D — upload slots, camera affordance, mobile polish ── */

/* Screen-reader-accessible hidden helper. Used by the canonical file input
   inside .fk-upload-slot so the upload button (a <label for>) still works
   and AT users can discover the input via label association. */
.fk-visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* Upload slot — appears once per document card, holds the canonical hidden
   input + the two visible labels (file + camera). */
.fk-upload-slot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

/* Camera control visibility — only show on devices with a coarse pointer
   (touch). Desktop browsers ignore the `capture` attribute, so the camera
   button would just open the regular file picker — redundant. */
@media not (pointer: coarse) {
  .fk-camera-only { display: none; }
}

/* Checkbox row wrapper — used on the consent checkbox + address-sync
   checkbox so the entire row is tappable (not just the 16px native box). */
.fk-checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 10px 0;
  cursor: pointer;
}

/* Sticky wizard nav (mobile-only). The base .fk-wizard-nav layout stays
   inline; the --sticky modifier opts into sticky positioning, gated by
   `(pointer: coarse) and (max-width: 720px)` so desktop users with narrow
   windows are not affected. */
.fk-wizard-nav--sticky {
  /* No effect outside the mobile media query. */
}

@media (pointer: coarse) and (max-width: 720px) {
  .fk-wizard-nav--sticky {
    position: sticky;
    bottom: 0;
    background: var(--fk-bg, #fff);
    padding: 12px 0;
    box-shadow: 0 -4px 8px rgba(0, 0, 0, 0.04);
    z-index: 10;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD -v`
Expected: PASS — all five tests green.

- [ ] **Step 5: Commit**

```bash
git add static/css/parent_theme.css tests/registrations/test_async_document_upload.py
git commit -m "feat(parent-ui-css): add Slice D selectors (upload-slot, camera-only, sticky nav)"
```

---

## Task 3: CSS — touch-target floors for buttons, inputs, selects, date pickers

**Why:** Acceptance criterion #5. Class-level minimums so every future caller inherits the floor.

**Files:**
- Modify: `static/css/parent_theme.css` — bump `.fk-button--small`; add `min-height` rule for form inputs.
- Test: `tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD` (extend the same class).

- [ ] **Step 1: Write the failing test**

Add inside `TestParentThemeCssContractSliceD`:

```python
    def test_fk_button_small_meets_40px_floor(self):
        import re
        section = self._slice_d_section()
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

    def test_form_inputs_meet_44px_floor(self):
        import re
        section = self._slice_d_section()
        # New rule lives in Slice D section.
        match = re.search(
            r"\.fk-input[^\{]*\{[^}]*min-height:\s*(\d+)px",
            section,
            re.DOTALL,
        )
        assert match, "Slice D must define min-height for .fk-input"
        assert int(match.group(1)) >= 44, (
            f".fk-input min-height is {match.group(1)}px; require ≥ 44px."
        )

    def test_date_input_meets_44px_floor(self):
        section = self._slice_d_section()
        assert 'input[type="date"]' in section, (
            "Slice D must include a touch-target floor for input[type=date]"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD::test_fk_button_small_meets_40px_floor tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD::test_form_inputs_meet_44px_floor tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD::test_date_input_meets_44px_floor -v`
Expected: FAIL.

- [ ] **Step 3: Implement — append touch-target floors to the Slice D section**

In `static/css/parent_theme.css`, find the existing `.fk-button--small { min-height: 36px; ... }` rule (around line 446–448) and change `36px` to `40px`:

```css
.fk-button--small {
  min-height: 40px;
  ...
}
```

Then append to the Slice D section (after the sticky-nav block from Task 2):

```css
/* Touch-target floors for form controls (Slice D acceptance #5). */
.fk-input,
.fk-select,
.fk-textarea {
  min-height: 44px;
}

input[type="date"] {
  min-height: 44px;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD -v`
Expected: PASS for all eight tests.

- [ ] **Step 5: Commit**

```bash
git add static/css/parent_theme.css tests/registrations/test_async_document_upload.py
git commit -m "feat(parent-ui-css): enforce 44px touch-target floor on form controls"
```

---

## Task 4: CSS — mobile media query refinements (container padding, address-row stacking, save-pill flow)

**Why:** Acceptance criterion #4. Fill in gaps in existing `(max-width: 720px)` and `(max-width: 420px)` blocks.

**Files:**
- Modify: `static/css/parent_theme.css` — extend mobile blocks; add container padding rule outside media queries.
- Test: `tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD`.

- [ ] **Step 1: Write the failing test**

Add inside `TestParentThemeCssContractSliceD`:

```python
    def test_workspace_container_uses_clamp_padding(self):
        import re
        section = self._slice_d_section()
        # Padding-inline declaration on .fk-workspace (or .fk-application-workspace)
        # uses clamp(16px, 4vw, 32px).
        assert "clamp(16px, 4vw, 32px)" in section, (
            "Workspace container must use clamp(16px, 4vw, 32px) padding."
        )

    def test_address_sync_row_stacks_at_mobile(self):
        section = self._slice_d_section()
        # Slice D section must contain a media query block for max-width 720
        # that targets .fk-address-row (or similar) with flex-direction: column.
        assert ".fk-address-row" in section, (
            "Slice D must define stacking behavior for the address-sync row."
        )

    def test_save_pill_flows_inline_on_mobile(self):
        import re
        section = self._slice_d_section()
        # The save-pill (existing .fk-save-indicator) needs to switch from
        # absolute positioning to static/in-flow on mobile.
        match = re.search(
            r"\.fk-save-indicator[^\{]*\{[^}]*position:\s*static",
            section,
            re.DOTALL,
        )
        assert match, (
            "Slice D must reposition .fk-save-indicator to position: static "
            "on mobile (max-width: 720px)."
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD -v`
Expected: FAIL on the three new tests.

- [ ] **Step 3: Implement — append mobile refinements to the Slice D section**

Append to `static/css/parent_theme.css` (within or appended after the Slice D section):

```css
/* Container padding (clamp-based, scales with viewport). Applies to
   both the workspace shell and the new-app body. */
.fk-application-workspace,
.fk-workspace {
  padding-inline: clamp(16px, 4vw, 32px);
}

/* Address-sync row — wraps the actual-address input + "same as guardian"
   checkbox. Stacked on mobile so each control has its own row. */
.fk-address-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

@media (max-width: 720px) {
  .fk-address-row {
    flex-direction: column;
    gap: 8px;
  }

  /* Save indicator: move into the flow above the active step so it
     doesn't overlap the sticky CTA. Existing rule pins it absolute
     at top-right of the workspace; the override puts it in normal flow
     and right-aligns it. */
  .fk-save-indicator {
    position: static;
    margin-left: auto;
    margin-bottom: 8px;
  }
}
```

Note: `.fk-address-row` is a new wrapper class that the workspace template (Task 7) applies to the `member_actual_address` + `member_same_address_as_guardian` group.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestParentThemeCssContractSliceD -v`
Expected: PASS — all eleven tests green.

- [ ] **Step 5: Commit**

```bash
git add static/css/parent_theme.css tests/registrations/test_async_document_upload.py
git commit -m "feat(parent-ui-css): mobile-first refinements (clamp padding, stacked address row, save pill flow)"
```

---

## Task 5: Document-card partial rewrite (RED — markup contract)

**Why:** Acceptance criteria #1 (camera label), #2 (camera-only wrapper), #3 (no Aizvietot anchor).

**Files:**
- Test: `tests/registrations/test_document_state_presentation.py` (add `TestUploadSlotMarkup` class).

- [ ] **Step 1: Write the failing tests**

Append to `tests/registrations/test_document_state_presentation.py`:

```python
import pytest
from django.test import Client


@pytest.mark.django_db
class TestUploadSlotMarkup:
    """P4 Slice D — document_card.html owns the upload UI.

    Each card renders:
    - one canonical hidden <input type="file" class="fk-visually-hidden">
    - one <label for="…"> styled as the file-picker button
    - one .fk-camera-only wrapper containing <label for="…" data-camera-affordance>
    """

    def _workspace_html(self, draft_application, parent_client):
        # parent_client and draft_application fixtures live in tests/registrations/conftest.py
        response = parent_client.get(f"/applications/{draft_application.id}/")
        assert response.status_code == 200, response.content[:300]
        return response.content.decode()

    def test_each_doc_card_has_one_canonical_hidden_input(self, draft_application, parent_client):
        html = self._workspace_html(draft_application, parent_client)
        for field_name in ("guardian_identity_document", "member_identity_document", "member_portrait_document"):
            input_id = f"id_{field_name}"
            # Exactly one input with this id.
            assert html.count(f'id="{input_id}"') == 1, (
                f"{input_id} must render exactly once (no duplicates)."
            )
            # The input must carry the visually-hidden class.
            import re
            match = re.search(
                rf'<input[^>]*id="{input_id}"[^>]*>',
                html,
            )
            assert match, f"<input id={input_id}> not found"
            assert "fk-visually-hidden" in match.group(0), (
                f"Canonical input for {field_name} must use fk-visually-hidden class."
            )

    def test_each_doc_card_has_file_label_pointing_at_canonical_input(self, draft_application, parent_client):
        html = self._workspace_html(draft_application, parent_client)
        for field_name in ("guardian_identity_document", "member_identity_document", "member_portrait_document"):
            input_id = f"id_{field_name}"
            # A <label for="id_<field>"> exists and contains "Augšupielādēt failu".
            import re
            match = re.search(
                rf'<label[^>]*for="{input_id}"[^>]*>[^<]*Augšupielādēt failu',
                html,
            )
            assert match, (
                f"File-picker label for {field_name} must contain "
                f'`for="{input_id}"` and the text "Augšupielādēt failu".'
            )

    def test_each_doc_card_has_camera_label_with_marker(self, draft_application, parent_client):
        html = self._workspace_html(draft_application, parent_client)
        for field_name in ("guardian_identity_document", "member_identity_document", "member_portrait_document"):
            input_id = f"id_{field_name}"
            import re
            match = re.search(
                rf'<label[^>]*for="{input_id}"[^>]*data-camera-affordance[^>]*>[^<]*Uzņemt attēlu',
                html,
            )
            assert match, (
                f"Camera label for {field_name} must have `for=\"{input_id}\"`, "
                "`data-camera-affordance` marker, and the text \"Uzņemt attēlu\"."
            )

    def test_camera_label_wrapped_in_fk_camera_only(self, draft_application, parent_client):
        html = self._workspace_html(draft_application, parent_client)
        # The camera label must sit inside a <span class="fk-camera-only">.
        import re
        # Count occurrences of fk-camera-only — one per slot, so three total.
        assert html.count("fk-camera-only") >= 3, (
            "Expected at least three .fk-camera-only wrappers (one per document slot)."
        )

    def test_no_aizvietot_anchor_link(self, draft_application, parent_client):
        # Pre-existing identity doc → previously rendered "Aizvietot" anchor.
        # After Slice D the anchor is gone.
        html = self._workspace_html(draft_application, parent_client)
        # There must be no <a> element whose text is "Aizvietot".
        import re
        match = re.search(r"<a[^>]*>\s*Aizvietot\s*</a>", html)
        assert match is None, (
            "The Aizvietot anchor link must be removed in Slice D. "
            "Upload-slot buttons own the replace action now."
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_document_state_presentation.py::TestUploadSlotMarkup -v`
Expected: FAIL on every test — fk-visually-hidden absent, file/camera labels not in card, etc.

- [ ] **Step 3: Hold off committing yet — implementation is in Task 6.**

The RED tests stay failing until Task 6 lands the partial rewrite. Move directly to Task 6.

---

## Task 6: Document-card partial rewrite (GREEN — implement)

**Files:**
- Modify: `templates/parent_ui/includes/document_card.html` (full rewrite).
- Test: same RED tests from Task 5.

- [ ] **Step 1: Rewrite `templates/parent_ui/includes/document_card.html`**

Replace the entire file with:

```django
{% load reg_filters %}

{% for kind, document in document_state.items %}
  <div class="fk-document-card">
    <div class="fk-document-card__header">
      <span class="fk-document-card__kind">{% if document %}{{ document.get_kind_display }}{% else %}{{ document_kind_labels|get_item:kind }}{% endif %}</span>
      {% if document %}
        <span class="fk-source-badge fk-source-badge--active">Aktīvs</span>
      {% else %}
        <span class="fk-source-badge fk-source-badge--inactive">Nav augšupielādēts</span>
      {% endif %}
    </div>
    <div class="fk-document-card__body">
      {% if document %}
        <p class="fk-document-card__filename">{{ document.original_filename }}</p>
        <p class="fk-document-card__hint">Dokuments jau ir augšupielādēts.</p>
        {% if workspace_mode == "editable" %}
          <p class="fk-document-card__hint">
            Aizvietojiet tikai tad, ja dokuments ir nepareizs vai novecojis.
          </p>
        {% endif %}
      {% else %}
        <p class="fk-document-card__empty">
          Dokuments nav augšupielādēts.
        </p>
      {% endif %}
    </div>

    {% if workspace_mode == "editable" %}
      {% with field_id=document_field_id_map|get_item:kind %}
        {% with bound_field=document_bound_fields|get_item:kind %}
          <div class="fk-upload-slot">
            {# Canonical hidden file input. Form-side widget attrs (data-async-upload,
               data-progress-slot, data-step-required, data-step-error-empty) are
               applied by RegistrationApplicationForm.__init__. #}
            {{ bound_field }}

            <label for="{{ field_id }}" class="fk-button fk-button--secondary fk-button--full">
              Augšupielādēt failu
            </label>

            <span class="fk-camera-only">
              <label for="{{ field_id }}" data-camera-affordance class="fk-button fk-button--secondary fk-button--full">
                Uzņemt attēlu
              </label>
            </span>

            <p id="{{ field_id }}_progress" class="fk-form-progress" data-state="idle" hidden></p>
          </div>
        {% endwith %}
      {% endwith %}
    {% endif %}
  </div>
{% endfor %}
```

Key points:
- The canonical input is rendered by `{{ bound_field }}` — Django will emit `<input type="file" name="…" id="id_…" class="fk-visually-hidden" data-async-upload="…" data-progress-slot="…" data-step-required="…">` provided the form widget attrs include the class (added in Task 9).
- The "Aizvietot" anchor is gone.
- The progress slot `<p id="…_progress">` moves into the card so async_upload.js's status updates stay co-located with the buttons.
- The partial requires a new template variable: `document_bound_fields` (a dict mapping kind → bound field). The view supplies this in Task 8.

- [ ] **Step 2: Tests still fail until Task 8 wires up the view context.**

Move directly to Task 7 (which adjusts the workspace template).

---

## Task 7: Workspace template — wire partial as sole renderer + add sticky-CTA marker + address-row wrapper

**Files:**
- Modify: `templates/registrations/application_workspace.html` (around lines 70–115 for the documents section, lines 105–115 for wizard nav, and the same-address fragment around lines 85–100).
- Test: new tests in `tests/registrations/test_application_workspace_template.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/registrations/test_application_workspace_template.py`:

```python
import pytest
import re


@pytest.mark.django_db
class TestSliceDWorkspaceTemplate:
    """P4 Slice D — workspace template markers."""

    def _html(self, draft_application, parent_client):
        response = parent_client.get(f"/applications/{draft_application.id}/")
        assert response.status_code == 200
        return response.content.decode()

    def test_per_step_nav_has_sticky_modifier(self, draft_application, parent_client):
        html = self._html(draft_application, parent_client)
        # Every <div class="fk-wizard-nav … "> in the wizard form must include
        # the --sticky modifier so the CSS gate (pointer: coarse, max-width 720)
        # picks it up.
        wizard_navs = re.findall(r'<div[^>]*class="[^"]*fk-wizard-nav[^"]*"[^>]*>', html)
        assert len(wizard_navs) >= 2, (
            f"Expected at least 2 wizard nav rows (per-step + review), found {len(wizard_navs)}."
        )
        for nav in wizard_navs:
            assert "fk-wizard-nav--sticky" in nav, (
                f"Wizard nav row is missing the --sticky modifier: {nav}"
            )

    def test_documents_step_renders_no_dropzone_markup(self, draft_application, parent_client):
        # The old fk-dropzone label (from form_field.html's file branch) must
        # not appear anywhere in the documents step body. Upload UI is the
        # partial's job now.
        html = self._html(draft_application, parent_client)
        assert "fk-dropzone" not in html, (
            "fk-dropzone markup must not be rendered in Slice D. "
            "document_card.html owns the file inputs."
        )

    def test_address_sync_row_has_wrapper_class(self, draft_application, parent_client):
        html = self._html(draft_application, parent_client)
        assert "fk-address-row" in html, (
            "Slice D wraps the actual-address + same-as-guardian fields in a "
            ".fk-address-row container so the mobile stack CSS rule can target it."
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_application_workspace_template.py::TestSliceDWorkspaceTemplate -v`
Expected: FAIL.

- [ ] **Step 3: Modify `templates/registrations/application_workspace.html`**

**Change 1 — documents section: skip file fields in the bound_fields loop.**

Find the block starting at line ~70 (`{% if section_name == "documents" %}` … `{% include "parent_ui/includes/document_card.html" with … %}`). After the include, the `{% for bound_field in bound_fields %}` loop currently renders every documents-section field via `form_field.html` — including the three file inputs (which we now want rendered exclusively by the partial).

Add a skip condition inside the `for bound_field in bound_fields` loop. Replace the loop body's outer `{% if … %}{% else %}…{% endif %}` with:

```django
{% for bound_field in bound_fields %}
  {% if section_name == "documents" and bound_field.field.widget.input_type == "file" %}
    {# Rendered by document_card.html above — skip here to avoid duplicate input. #}
  {% elif section_name == "member" and bound_field.name == "member_same_address_as_guardian" %}
    <div class="fk-address-row">
      <input type="hidden" id="member_actual_address_previous" value="{{ form.member_actual_address.value|default:'' }}">
      {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|get_item:bound_field.name existing_doc=document_by_field|get_item:bound_field.name kind_label=field_kind_labels|get_item:bound_field.name %}
    </div>
    <script>
// SameAddressSync — unchanged
document.addEventListener('DOMContentLoaded',function(){
  var cb=document.getElementById('id_member_same_address_as_guardian');
  var addr=document.getElementById('id_member_actual_address');
  var prev=document.getElementById('member_actual_address_previous');
  var guardian=document.getElementById('id_guardian_declared_address');
  if(!cb||!addr||!prev||!guardian)return;
  function syncFromGuardian(){addr.value=guardian.value;addr.disabled=true;}
  function restorePrev(){addr.value=prev.value;addr.disabled=false;}
  if(cb.checked){syncFromGuardian();}
  cb.addEventListener('change',function(){if(cb.checked){prev.value=addr.value;syncFromGuardian();}else{restorePrev();}});
  guardian.addEventListener('input',function(){if(cb.checked){syncFromGuardian();}});
});
    </script>
  {% else %}
    {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|get_item:bound_field.name existing_doc=document_by_field|get_item:bound_field.name kind_label=field_kind_labels|get_item:bound_field.name %}
  {% endif %}
{% endfor %}
```

The `.fk-address-row` wrapper is new; everything else inside the second branch is verbatim from the existing template.

**Change 2 — sticky CTA modifier on every wizard nav row.**

Find each `<div class="fk-wizard-nav">` occurrence (there are two: one in the per-section step body around line 108, one in the review step around line 163) and change them to:

```django
<div class="fk-wizard-nav fk-wizard-nav--sticky">
```

**Change 3 — pass `document_bound_fields` to the document_card include.**

Update the include line (around line 83) from:

```django
{% include "parent_ui/includes/document_card.html" with document_state=document_state document_kind_labels=document_kind_labels document_field_id_map=document_field_id_map workspace_mode=workspace_mode %}
```

to:

```django
{% include "parent_ui/includes/document_card.html" with document_state=document_state document_kind_labels=document_kind_labels document_field_id_map=document_field_id_map document_bound_fields=document_bound_fields workspace_mode=workspace_mode %}
```

`document_bound_fields` is populated by the view in Task 8.

- [ ] **Step 4: Tests still fail because the view does not yet provide `document_bound_fields`. Move to Task 8.**

---

## Task 8: View — populate `document_bound_fields` context

**Why:** The new partial uses `{{ bound_field }}` to render the canonical input with all the form widget attrs intact. The view that renders the workspace must pass a dict of `kind → bound field` so the template can index into it.

**Files:**
- Modify: `apps/registrations/views.py` — find the workspace render context (look for `document_field_id_map` to locate it).
- Test: implicit — Task 5 / Task 7 tests will pass once this and Task 9 are done.

- [ ] **Step 1: Locate the workspace view context**

Run: `grep -n "document_field_id_map\|document_state\|document_kind_labels" apps/registrations/views.py | head`

Find the function that builds the workspace render context (likely named `application_workspace` or similar). Note the line numbers of the `document_field_id_map`/`document_state` keys in the context dict.

- [ ] **Step 2: Write the failing test**

Append a small unit-level test to `tests/registrations/test_application_workspace_template.py`:

```python
@pytest.mark.django_db
class TestSliceDViewContext:
    """Slice D — document_bound_fields is passed to the workspace template."""

    def test_workspace_context_includes_document_bound_fields(self, draft_application, parent_client):
        response = parent_client.get(f"/applications/{draft_application.id}/")
        assert response.status_code == 200
        # The context (Django adds it to response.context for template responses)
        # must include 'document_bound_fields' mapping the three doc kinds
        # to their bound fields.
        ctx = response.context
        assert "document_bound_fields" in ctx, (
            "View must pass document_bound_fields so the document_card partial "
            "can render the canonical file input via {{ bound_field }}."
        )
        bound_fields = ctx["document_bound_fields"]
        for kind in ("guardian_identity", "member_identity", "member_portrait"):
            assert kind in bound_fields, f"Missing bound field for kind: {kind}"
            assert bound_fields[kind].name.endswith("_document"), (
                f"Bound field for {kind} should be the *_document FileField."
            )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_application_workspace_template.py::TestSliceDViewContext -v`
Expected: FAIL — `document_bound_fields` not in context.

- [ ] **Step 4: Implement — extend the view context**

In `apps/registrations/views.py`, find the dict where `document_field_id_map` is built (likely uses the `FIELD_NAME_BY_KIND` constant from `apps/registrations/presentation.py`).

Right above or below that line, add:

```python
        document_bound_fields = {
            "guardian_identity": form["guardian_identity_document"],
            "member_identity": form["member_identity_document"],
            "member_portrait": form["member_portrait_document"],
        }
```

and add `"document_bound_fields": document_bound_fields,` to the context dict passed to `render(...)`.

If the constant `FIELD_NAME_BY_KIND` from `presentation.py` is more idiomatic, use it:

```python
        from apps.registrations.presentation import FIELD_NAME_BY_KIND
        document_bound_fields = {
            kind: form[field_name]
            for kind, field_name in FIELD_NAME_BY_KIND.items()
        }
```

(Check the existing import structure first — `FIELD_NAME_BY_KIND` may already be imported at the top of the file.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_application_workspace_template.py::TestSliceDViewContext tests/registrations/test_document_state_presentation.py::TestUploadSlotMarkup tests/registrations/test_application_workspace_template.py::TestSliceDWorkspaceTemplate -v`
Expected: Most pass. The remaining failures should be the `fk-visually-hidden` class check (Task 9 adds it).

- [ ] **Step 6: Commit**

```bash
git add apps/registrations/views.py templates/registrations/application_workspace.html templates/parent_ui/includes/document_card.html tests/registrations/test_application_workspace_template.py tests/registrations/test_document_state_presentation.py
git commit -m "feat(registrations): document_card owns upload UI; sticky nav modifier; address row wrapper"
```

---

## Task 9: Form widget attrs — visually-hide canonical file inputs

**Why:** Task 5's RED test requires every canonical file input to render with `class="fk-visually-hidden"`. The cleanest place to set this is the form's `__init__`, alongside the existing `data-async-upload`/`data-progress-slot`/`data-step-required` widget attrs.

**Files:**
- Modify: `apps/registrations/forms.py:118-127` (the three blocks that set widget attrs on file fields).
- Test: re-run Task 5 tests.

- [ ] **Step 1: Write a focused failing test**

Add to `tests/registrations/test_registration_form_contract.py` (existing file — append at end):

```python
class TestSliceDFileWidgetAttrs:
    """P4 Slice D — canonical file inputs render visually hidden so the
    document_card partial's visible labels are the only tap surface."""

    def test_guardian_identity_file_input_is_visually_hidden(self):
        from apps.registrations.forms import RegistrationApplicationForm
        form = RegistrationApplicationForm()
        attrs = form.fields["guardian_identity_document"].widget.attrs
        css_class = attrs.get("class", "")
        assert "fk-visually-hidden" in css_class, (
            f"guardian_identity_document widget must include 'fk-visually-hidden' "
            f"in its class attr; got: {css_class!r}"
        )

    def test_member_identity_file_input_is_visually_hidden(self):
        from apps.registrations.forms import RegistrationApplicationForm
        form = RegistrationApplicationForm()
        attrs = form.fields["member_identity_document"].widget.attrs
        assert "fk-visually-hidden" in attrs.get("class", "")

    def test_member_portrait_file_input_is_visually_hidden(self):
        from apps.registrations.forms import RegistrationApplicationForm
        form = RegistrationApplicationForm()
        attrs = form.fields["member_portrait_document"].widget.attrs
        assert "fk-visually-hidden" in attrs.get("class", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_registration_form_contract.py::TestSliceDFileWidgetAttrs -v`
Expected: FAIL.

- [ ] **Step 3: Implement — add `class` to file widget attrs in `forms.py.__init__`**

In `apps/registrations/forms.py`, immediately after the existing block that tags file inputs (around line 121–126):

```python
        # P3.5: tag file inputs so static/js/async_upload.js can bind to them.
        self.fields["guardian_identity_document"].widget.attrs["data-async-upload"] = "guardian_identity"
        self.fields["guardian_identity_document"].widget.attrs["data-progress-slot"] = "id_guardian_identity_document_progress"
        self.fields["member_identity_document"].widget.attrs["data-async-upload"] = "member_identity"
        self.fields["member_identity_document"].widget.attrs["data-progress-slot"] = "id_member_identity_document_progress"
        self.fields["member_portrait_document"].widget.attrs["data-async-upload"] = "member_portrait"
        self.fields["member_portrait_document"].widget.attrs["data-progress-slot"] = "id_member_portrait_document_progress"
```

append:

```python
        # P4 Slice D: canonical file inputs are visually hidden — the visible
        # tap surface is the <label for=...> rendered by document_card.html.
        for _file_field in ("guardian_identity_document", "member_identity_document", "member_portrait_document"):
            existing = self.fields[_file_field].widget.attrs.get("class", "")
            classes = (existing + " fk-visually-hidden").strip()
            self.fields[_file_field].widget.attrs["class"] = classes
```

- [ ] **Step 4: Run all the previously-failing Slice D markup tests**

Run: `uv run pytest tests/registrations/test_registration_form_contract.py::TestSliceDFileWidgetAttrs tests/registrations/test_document_state_presentation.py::TestUploadSlotMarkup tests/registrations/test_application_workspace_template.py::TestSliceDWorkspaceTemplate -v`
Expected: PASS — every Slice D markup/contract test green.

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/forms.py tests/registrations/test_registration_form_contract.py
git commit -m "feat(registrations): visually-hide canonical file inputs for upload-slot UI"
```

---

## Task 10: Update the pre-existing tests broken by the partial rewrite

**Why:** The old `TestReplaceActionVisible` and `TestReplaceUploadLinksPointToFileInputs` classes in `test_document_state_presentation.py` assert the "Aizvietot" anchor or anchor-link semantics. Those are gone after Slice D. Also, tests that asserted the portrait file input lives in the member step (Task 1 moves it) will fail.

**Files:**
- Modify: `tests/registrations/test_document_state_presentation.py:236-348` — replace anchor-link assertions with upload-button assertions, or delete redundant tests.

- [ ] **Step 1: Identify breakage**

Run: `uv run pytest tests/registrations/ -q 2>&1 | grep FAIL | head -20`

Expected fails (rough):
- `TestReplaceActionVisible::test_replace_action_visible_when_document_exists` — asserts "Aizvietot" anchor.
- `TestReplaceUploadLinksPointToFileInputs::*` — asserts anchor `href="#id_…"` semantics.
- Possibly tests in `test_parent_application_workspace.py` or similar that asserted form_field.html rendered the file input.

- [ ] **Step 2: Replace anchor-link assertions with button-label assertions**

For each broken test, rewrite the assertion. Example pattern:

Before:
```python
def test_replace_action_visible_when_document_exists(self, draft_application_with_doc, parent_client):
    response = parent_client.get(f"/applications/{draft_application_with_doc.id}/")
    assert "Aizvietot" in response.content.decode()
```

After:
```python
def test_replace_action_visible_when_document_exists(self, draft_application_with_doc, parent_client):
    response = parent_client.get(f"/applications/{draft_application_with_doc.id}/")
    html = response.content.decode()
    # Slice D — the "replace" action is the upload buttons themselves,
    # rendered inside the document card alongside the active-state hint.
    assert "Aizvietojiet tikai tad" in html, (
        "Document card must still show the replace-only-if-wrong hint."
    )
    assert "Augšupielādēt failu" in html, (
        "Upload buttons must be visible even when a document is already attached."
    )
```

For `TestReplaceUploadLinksPointToFileInputs` — these tests assert that anchor links point to specific input ids. After Slice D those anchors are gone; the labels (`<label for="id_…">`) carry the wiring instead. Rewrite each as:

```python
def test_replace_link_points_to_guardian_identity_input(self, …):
    html = …
    # Slice D — replaced by <label for="id_guardian_identity_document"> on
    # both the file-picker and camera labels.
    import re
    assert re.search(
        r'<label[^>]*for="id_guardian_identity_document"',
        html,
    ), "Upload labels must point at the canonical file input via for-attribute."
```

If a test has no Slice-D equivalent (e.g. it only asserted the anchor's `class="fk-link"`), delete it — the upload-slot tests in Task 5 cover the new contract.

- [ ] **Step 3: Run the full registrations suite**

Run: `uv run pytest tests/registrations/ -q 2>&1 | tail -10`
Expected: 0 failed.

- [ ] **Step 4: Commit**

```bash
git add tests/registrations/test_document_state_presentation.py
git commit -m "test(document-state): align replace-action tests with upload-slot UI"
```

---

## Task 11: Camera-affordance JS shim

**Why:** Acceptance criterion #1 — the "Uzņemt attēlu" label needs JS to set `capture="environment"` and `accept="image/*"` on the canonical input before triggering the file picker.

**Files:**
- Modify: `static/js/async_upload.js` — append the shim at the bottom of the IIFE.
- Test: `tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract` (extend with new assertions).

- [ ] **Step 1: Write the failing tests**

Append to the existing `TestAsyncUploadJsContract` class in `tests/registrations/test_async_document_upload.py`:

```python
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
        # input.click() is already present (used elsewhere), but the shim's intent
        # is that after setting the attrs, .click() runs on the canonical input.
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
```

The `_read_js` helper already exists higher in the file — confirm by running:

Run: `grep -n "_read_js\|def _read_js" tests/registrations/test_async_document_upload.py`

If it isn't there, add this helper inside the `TestAsyncUploadJsContract` class (top of class body):

```python
    @staticmethod
    def _read_js() -> str:
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "static" / "js" / "async_upload.js"
        return path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract -v -k camera`
Expected: FAIL on all five new tests.

- [ ] **Step 3: Implement — append shim to `static/js/async_upload.js`**

Append at the bottom of the IIFE in `static/js/async_upload.js` (before the closing `})();`):

```javascript

  /* P4 Slice D — camera-affordance shim.
   *
   * The document_card partial renders two <label for="id_<field>"> controls
   * pointing at the same canonical hidden file input. The "Augšupielādēt failu"
   * label uses native label→input wiring (no JS needed). The "Uzņemt attēlu"
   * label has the data-camera-affordance marker and lives inside a
   * .fk-camera-only wrapper (hidden on non-coarse pointers).
   *
   * When the camera label is clicked we:
   *   1. preventDefault — stop the native label→input click flow.
   *   2. Set capture="environment" and accept="image/*" on the canonical input.
   *   3. Call input.click() ourselves so the device opens the camera.
   *
   * To avoid stale `capture` attributes (if the user cancelled the camera
   * picker without selecting a file), the non-camera labels get a pointerdown
   * listener that defensively clears `capture` before the native label→input
   * click runs.
   */
  function wireCameraAffordance() {
    var cameraLabels = document.querySelectorAll('label[data-camera-affordance]');
    cameraLabels.forEach(function (lbl) {
      lbl.addEventListener('click', function (event) {
        event.preventDefault();
        var inputId = lbl.getAttribute('for');
        if (!inputId) return;
        var input = document.getElementById(inputId);
        if (!input) return;
        input.setAttribute('accept', 'image/*');
        input.setAttribute('capture', 'environment');
        input.click();
      });
    });

    var fileLabels = document.querySelectorAll(
      'label.fk-button[for]:not([data-camera-affordance])'
    );
    fileLabels.forEach(function (lbl) {
      lbl.addEventListener('pointerdown', function () {
        var inputId = lbl.getAttribute('for');
        if (!inputId) return;
        var input = document.getElementById(inputId);
        if (input) input.removeAttribute('capture');
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wireCameraAffordance);
  } else {
    wireCameraAffordance();
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_async_document_upload.py::TestAsyncUploadJsContract -v -k camera`
Expected: PASS — five tests green.

- [ ] **Step 5: Commit**

```bash
git add static/js/async_upload.js tests/registrations/test_async_document_upload.py
git commit -m "feat(async-upload): camera-affordance shim for Uzņemt attēlu labels"
```

---

## Task 12: Visual contract regression — extend the consolidated visual test

**Why:** The project has `tests/registrations/test_visual_contract.py` that asserts cross-page visual selectors. Slice D adds `.fk-upload-slot`, `.fk-camera-only`, `.fk-wizard-nav--sticky`, `.fk-visually-hidden`, `.fk-address-row` — wire them into the same file so future drifts get caught.

**Files:**
- Modify: `tests/registrations/test_visual_contract.py`.

- [ ] **Step 1: Inspect existing structure**

Run: `grep -n "def test_\|class " tests/registrations/test_visual_contract.py | head -20`

Pick the test most likely to assert a selector list per page (e.g. one that checks parent-theme css for several selectors).

- [ ] **Step 2: Append new assertions**

Add a new test class near the bottom of `tests/registrations/test_visual_contract.py`:

```python
class TestVisualContractSliceD:
    """Cross-page visual selectors introduced by Slice D."""

    @staticmethod
    def _css() -> str:
        from pathlib import Path
        return (
            Path(__file__).resolve().parents[2]
            / "static" / "css" / "parent_theme.css"
        ).read_text(encoding="utf-8")

    def test_upload_slot_selector_present(self):
        assert ".fk-upload-slot" in self._css()

    def test_camera_only_selector_present(self):
        assert ".fk-camera-only" in self._css()

    def test_wizard_nav_sticky_selector_present(self):
        assert ".fk-wizard-nav--sticky" in self._css()

    def test_visually_hidden_selector_present(self):
        assert ".fk-visually-hidden" in self._css()

    def test_address_row_selector_present(self):
        assert ".fk-address-row" in self._css()
```

- [ ] **Step 3: Run the test**

Run: `uv run pytest tests/registrations/test_visual_contract.py::TestVisualContractSliceD -v`
Expected: PASS (CSS was added in Tasks 2 and 4).

- [ ] **Step 4: Commit**

```bash
git add tests/registrations/test_visual_contract.py
git commit -m "test(visual-contract): cover Slice D selectors"
```

---

## Task 13: Full verification gates

**Files:** none modified (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: `XXX passed` with no failures. Baseline was 762; expect ~785–795 after Slice D additions.

If any failure appears, diagnose against the slice diff. Likely categories:
- A test in an unrelated file referenced `member_portrait_document` as a member-section field (Task 1 moved it). Update the test to reference it via the documents section.
- A test asserted the old `fk-dropzone` markup. Update to the new partial markup or delete if redundant.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: Run mypy**

Run: `uv run mypy .`
Expected: `Success: no issues found`. If any new typing issue surfaces (the view change in Task 8 might prompt one), add minimal annotations to fix.

- [ ] **Step 4: Manual LAN verification — phone**

Open `http://192.168.3.245:8000/` on an Android or iOS phone (or use Chrome DevTools device emulation if no device is available — note that explicitly in the commit body).

Check:
- `/applications/<id>/` step 1 renders 3 cards (guardian ID, member ID, portrait), each with two buttons.
- Tapping "Uzņemt attēlu" opens the device camera.
- Tapping "Augšupielādēt failu" opens the file picker.
- Sticky "Turpināt →" stays visible while scrolling through the documents step.
- After picking a file, the upload progress + OCR toast still appear (Slice B regression check).
- Address-sync row in step 2 stacks vertically.

- [ ] **Step 5: Manual LAN verification — desktop**

Open `http://192.168.3.245:8000/` on a desktop browser.

Check:
- Documents step shows 3 cards each with ONE visible button ("Augšupielādēt failu"). Camera button hidden.
- Inline (non-sticky) wizard nav at the bottom of each step.
- Clicking step indicators in the stepper still jumps between steps.

- [ ] **Step 6: Record verification evidence**

No commit here — verification evidence goes into the Task 14 commit body when AGENTS.md is updated.

---

## Task 14: Update AGENTS.md with the Slice D delivery note

**Files:**
- Modify: `AGENTS.md` — append a new "P4 Slice D delivered" subsection after the existing "P4 Slice C delivered" block.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "P4 Slice C delivered\|P4 Slice B delivered\|P4 Slice A delivered" AGENTS.md`

Insertion point is immediately after the end of the Slice C subsection.

- [ ] **Step 2: Append the new subsection**

Add to `AGENTS.md` after the Slice C block:

```markdown
### P4 Slice D delivered — camera capture + mobile-first workspace (2026-05-25)
- `templates/parent_ui/includes/document_card.html` now owns the upload UI for every document kind (guardian ID, member ID, member portrait). Each card renders a single canonical hidden `<input type="file">` (visually-hidden via `.fk-visually-hidden`) plus two visible `<label for="id_<field>">` controls: "Augšupielādēt failu" (native label→input wiring) and "Uzņemt attēlu" (carries `data-camera-affordance`, lives inside `.fk-camera-only`).
- `member_portrait_document` moved into the documents section in `RegistrationApplicationForm.section_order` so all three document uploads live in step 1.
- `static/js/async_upload.js` ships a camera-affordance shim: clicking a `label[data-camera-affordance]` calls `event.preventDefault()`, sets `accept="image/*"` and `capture="environment"` on the canonical input, then calls `input.click()`. A `pointerdown` listener on the non-camera file labels clears stale `capture` attrs (handles the camera-cancelled-without-pick edge case).
- `.fk-camera-only` is hidden on non-coarse pointers via `@media not (pointer: coarse)` — no JS feature detection, no UA sniffing. Wizard.js step-gating is untouched (single canonical input per slot).
- Mobile-first polish: `.fk-wizard-nav--sticky` modifier on per-step nav rows turns sticky on `(pointer: coarse) and (max-width: 720px)`; container padding uses `clamp(16px, 4vw, 32px)`; `.fk-address-row` wraps the actual-address + same-as-guardian fields and stacks at `max-width: 720px`; `.fk-save-indicator` switches to `position: static` on mobile so it doesn't collide with the sticky CTA.
- Touch-target floors enforced at class level: `.fk-button` (≥48 px, existing); `.fk-button--small` bumped to 40 px; `.fk-input`, `.fk-select`, `.fk-textarea`, `input[type="date"]` ≥44 px. Hidden file inputs are exempted (tap surface lives on the visible labels). `.fk-checkbox-row` wrapper (≥44 px, 10 px vertical padding) applied to the consent + address-sync rows.
- Full repo verification after Slice D landing: `uv run pytest -q` → `<count> passed`, `uv run ruff check .` → passed, `uv run mypy .` → passed.
- Manual LAN verification on `http://192.168.3.245:8000/applications/<id>/`: <note device(s) checked and result>.
```

Fill in `<count>` and the manual-verification note from Task 13.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "$(cat <<'EOF'
docs(agents): record P4 Slice D (camera capture + mobile-first workspace) delivery

- Single canonical input per slot + two labels (file + camera)
- camera-affordance JS shim toggles capture/accept on the canonical input
- mobile-only sticky CTA via @media (pointer: coarse) and (max-width: 720px)
- touch-target floors (44px) at class level
- member_portrait moved into the documents section
- Full suite green; ruff/mypy green; LAN-checked on <device>.
EOF
)"
```

- [ ] **Step 4: Final clean-tree check**

Run: `git status` and `git log --oneline -15`
Expected: clean working tree; the Slice D commits appear in order.

---

## Self-review

**Spec coverage check:**
- Acceptance #1 (camera labels + wiring) → Tasks 5, 6, 8, 9, 11.
- Acceptance #2 (camera hidden on non-coarse pointers) → Task 2.
- Acceptance #3 (document-card refactor, no Aizvietot) → Tasks 5, 6, 10.
- Acceptance #4 (mobile-first workspace: sticky CTA, save pill, padding, address row) → Tasks 2, 4, 7.
- Acceptance #5 (touch-target floors) → Task 3.
- Acceptance #6 (no regression) → Task 13.
- Acceptance #7 (tests cover the listed surfaces) → Tasks 5, 7, 11, 12 plus the regression sweep in Task 10.
- Acceptance #8 (verification gates green) → Task 13.
- Acceptance #9 (manual LAN verification documented) → Tasks 13, 14.

**Placeholder scan:** No "TBD", "implement later", or "add appropriate" patterns. Every step shows the actual code, test, or command an engineer needs.

**Type / name consistency:** `document_bound_fields` introduced in Tasks 6, 7, 8 with identical semantics (dict keyed by `"guardian_identity" / "member_identity" / "member_portrait"`). `FIELD_NAME_BY_KIND` in Task 8 matches the existing constant in `apps/registrations/presentation.py:17-19`. `fk-visually-hidden`, `fk-upload-slot`, `fk-camera-only`, `fk-wizard-nav--sticky`, `fk-address-row`, `fk-checkbox-row` selectors are spelled identically in CSS (Tasks 2, 3, 4), tests (Tasks 5, 7, 12), templates (Tasks 6, 7), and form widget attrs (Task 9).
