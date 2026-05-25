# P4 Slice D — Camera capture + mobile-first workspace (design)

**Date:** 2026-05-25
**Phase:** P4 (parent-flow UX polish + mobile-first workspace)
**Slice scope:** workspace camera capture + mobile-first `/applications/<id>/` layout + touch-target audit
**Predecessors:** Slice A (foundations, 2026-05-23), Slice B (OCR UX polish, 2026-05-23), Slice C (wizard gating + auto-save + consent, 2026-05-24)
**Successor:** Slice E (entry/chooser/portal polish + Latvian copy normalization audit)

## Context

P4 acceptance criteria #6 (camera capture) and #7 (mobile-first workspace) remain open. Acceptance #2 (Latvian copy audit) and #8 (entry/chooser/portal polish) are deferred to Slice E and are explicit non-goals here. Acceptance #9 (cross-cutting empty/error state usage on entry surfaces) is also deferred.

The current parent workspace (`/applications/<id>/`):
- Renders the multi-step wizard from `templates/registrations/application_workspace.html`.
- Document fields (`guardian_identity_document`, `member_identity_document`, `member_portrait_document`) are declared as `forms.FileField` in `apps/registrations/forms.py` and tagged with `data-async-upload="<kind>"` for the `static/js/async_upload.js` binding.
- `templates/parent_ui/includes/document_card.html` renders per-kind status (active/not-uploaded) and an "Aizvietot" anchor that jumps the user down the page to the visible file input.
- `static/css/parent_theme.css` has `@media (max-width: 720px)` and `(max-width: 420px)` blocks, plus a `.fk-mobile-progress` swap for the desktop stepper.
- The wizard already shows one step at a time (Slice C); stepper-click navigation works on desktop.

Open UX gaps this slice closes:
- No camera-capture affordance on the upload slots.
- Document-card "Aizvietot" link causes a page jump on mobile because the visible file input is rendered separately below the card grid.
- "Turpināt →" lives at the bottom of each step's nav row; on mobile (documents step in particular) users have to scroll to reach it.
- Touch targets across the documents step are inconsistent — some buttons rely on default padding rather than enforced minimums.

## Renumbering impact

None. Slice D inserts cleanly between Slice C (landed) and Slice E (still to plan). No further phase shifts.

## Target outcome

### Camera capture wiring

Each of the three document slots exposes two buttons inside the `document_card.html` partial:
- **"Augšupielādēt failu"** — triggers a hidden `<input type="file">` (the canonical form field).
- **"Uzņemt attēlu"** — triggers a hidden `<input type="file" accept="image/*" capture="environment">` with the same `name` and `data-async-upload`/`data-progress-slot` attributes as the canonical input. This input is markup-only — it's not declared on the Django form, but it carries the same `name` so file data flows through the existing form binding on submit.

Both inputs route through `static/js/async_upload.js` unchanged (same binding selector `[data-async-upload]`). The server-side upload endpoint does not need to know which input fired.

The "Uzņemt attēlu" button + its hidden input are wrapped in `<span class="fk-camera-only">…</span>` and hidden via CSS: `@media not (pointer: coarse) { .fk-camera-only { display: none; } }`. No JS feature detection, no UA sniffing.

When JavaScript is unavailable, the visible "Augšupielādēt failu" button uses native `<label for="…">` to trigger the canonical hidden input — the sync upload fallback path still works.

### Document-card refactor

`document_card.html` becomes the single owner of the upload UI:

- Status block (kind label, "Aktīvs"/"Nav augšupielādēts" badge, filename, hint) stays as today.
- A new `.fk-upload-slot` block appended to each card contains:
  - Hidden `<input type="file">` (canonical, carries all `data-async-upload`/`data-progress-slot`/`data-step-required` attrs).
  - Visible `<button class="fk-button fk-button--secondary fk-button--full">` labeled "Augšupielādēt failu" that triggers the canonical input.
  - `.fk-camera-only` wrapper containing hidden camera input + visible "Uzņemt attēlu" button.
- The existing "Aizvietot" anchor link is removed.
- `application_workspace.html` stops rendering visible file inputs in the documents step. The step body becomes: consent block + `{% include document_card.html %}` (3 cards) + member-portrait card.

Form binding posture is unchanged. `apps/registrations/forms.py` still declares the three `FileField`s; `__init__` keeps setting the `data-*` attrs on the canonical input via widget attrs. The template wires the camera input by name/attrs only.

### Mobile-first wizard layout

Filling gaps in existing breakpoint blocks (`(max-width: 720px)`, `(max-width: 420px)`) rather than restructuring:

- **Container padding:** workspace switches to `padding-inline: clamp(16px, 4vw, 32px)` so narrow viewports get tighter side gutters.
- **Card grid:** documents step renders 3 cards stacked full-width with `gap: 12px` on mobile; desktop grid unchanged.
- **Address sync row:** `member_actual_address` field + `member_same_address_as_guardian` checkbox reflow to stacked on `(max-width: 720px)`.
- **Form inputs:** `.fk-input`, `.fk-select`, `.fk-textarea` get `min-height: 44px` at the base level (not media-queried; current heights are close, this enforces the floor).
- **Sticky "Turpināt →":** per-step nav row gets a `fk-wizard-nav--sticky` modifier. Inside `@media (pointer: coarse) and (max-width: 720px)`: `position: sticky; bottom: 0; background: var(--fk-bg); padding: 12px 0; box-shadow: 0 -4px 8px rgba(0,0,0,0.04); z-index: 10`. Above 720 px or on non-coarse pointers: inline behavior unchanged. The review step's "Iesniegt pieteikumu" gets the same treatment.
- **Step indicator:** existing `.fk-mobile-progress` ("1 / N" + step label) stays. No clickable mobile stepper this slice; back-nav uses the inline "← Atpakaļ" button.
- **Save-status pill (`Saglabāts ✓`):** currently absolute-positioned at workspace top-right. On mobile (`(max-width: 720px)`) it moves into the flow above the active step (still right-aligned) so it doesn't collide with the sticky CTA.

### Touch-target audit

Two layers:

**Class-level minimums** in `static/css/parent_theme.css`:
- `.fk-button` → `min-height: 44px`, `min-width: 44px`.
- `.fk-button--small` → `min-height: 40px` (kept usable for niche callsites; primary user was the removed "Aizvietot" link).
- `.fk-input`, `.fk-select`, `.fk-textarea`, `input[type="date"]` → `min-height: 44px` (single-line controls only). File inputs are visually hidden after the document-card refactor; their tap surface is the visible "Augšupielādēt failu" / "Uzņemt attēlu" buttons, which inherit the `.fk-button` floor.
- `.fk-checkbox-row` wrapper: `min-height: 44px`, `padding: 10px 0` so the full label is tappable, not just the native checkbox box. Applied to the existing consent checkbox and the address-sync checkbox.

**Step-1 documents-step sweep** — manual audit of every interactive element:
1. Consent checkbox + label → covered by `.fk-checkbox-row`.
2. "Lasīt vairāk" T&C toggle → ensure ≥44 px tap area.
3. Per-card "Augšupielādēt failu" / "Uzņemt attēlu" buttons → covered by `.fk-button` floor.
4. Sticky "Turpināt →" → already `.fk-button--primary`, gets the floor.

**Out of audit scope (this slice):** entry/chooser/portal pages, guardian step inputs, member step inputs, review step. They inherit the class-level minimums automatically; no manual sweep here.

## Non-goals

- Latvian copy normalization audit on parent-facing templates (acceptance #2) — Slice E.
- Entry/chooser/portal mobile polish (acceptance #8) — Slice E.
- Cross-cutting empty/error-state partial usage on entry surfaces (acceptance #9) — Slice E.
- Custom `getUserMedia` / canvas / WebRTC pipeline — explicitly excluded per P4 design.
- UA sniffing for capture support — replaced by `(pointer: coarse)` CSS-only detection.
- iOS-specific "Photo Library / Take Photo" handling beyond what the native picker already provides.
- New schema migrations, new business rules, new admin surfaces.
- Polling, auto-save, or consent-gate behavior changes (Slice C remains authoritative).
- Stepper-click back-navigation on mobile (desktop keeps its existing click-to-jump indicator; mobile uses the inline back button).

## Out-of-scope assumptions

- The `(pointer: coarse)` media query is a sufficient proxy for "device that honors `capture`". A touchscreen laptop will show both buttons; that's acceptable (no broken UX, just a redundant control). Modern mobile browsers all match `pointer: coarse`.
- The existing async upload + OCR enqueue path from Slice B is stable; we add a second input but do not change the binding or polling logic.
- Submitting the form when only the camera input has a file works because both inputs share the same `name`; Django's `MultiPartParser` exposes the last value with that name on the request. If both inputs are populated simultaneously (rare but possible), the camera input wins — acceptable for first slice.
- Sticky CTA does not collide with the on-screen keyboard on iOS Safari. If field-keyboard scenarios surface a regression during manual verification, we'll fall back to `position: fixed` with a viewport-padding adjustment, but the default sticky path is preferred.

## Acceptance criteria

This slice is complete when all of the following are true:

1. **Camera capture buttons present and wired**:
   - Each document card renders both "Augšupielādēt failu" and "Uzņemt attēlu" buttons backed by hidden file inputs.
   - The camera input has `accept="image/*"` and `capture="environment"`.
   - Both inputs share the canonical form field's `name` and `data-async-upload` attrs.
   - `.fk-camera-only` wrapper is present on the camera control.
2. **Camera control hidden on non-coarse pointers**:
   - CSS `@media not (pointer: coarse) { .fk-camera-only { display: none; } }` is in `parent_theme.css`.
   - No JS-based show/hide; no UA sniffing.
3. **Document-card refactor complete**:
   - `document_card.html` renders the upload-slot block with both inputs and both buttons.
   - The "Aizvietot" anchor link is removed.
   - `application_workspace.html` documents step renders only via the partial (no duplicate file inputs).
4. **Mobile-first workspace**:
   - `.fk-wizard-nav--sticky` modifier applied to per-step nav rows; sticky on `(pointer: coarse) and (max-width: 720px)`.
   - Save-status pill repositioned into the flow on mobile.
   - Container padding uses `clamp(16px, 4vw, 32px)`.
   - Address-sync row stacks on `(max-width: 720px)`.
5. **Touch-target floors enforced**:
   - `.fk-button`, `.fk-input`, `.fk-select`, `.fk-textarea`, `input[type="date"]` ≥44 px `min-height`. Hidden file inputs are exempted (tap surface lives on the visible buttons).
   - `.fk-checkbox-row` wrapper applied to consent + address-sync checkboxes.
6. **No regression**:
   - Existing async upload, OCR polling, suggestion accept/dismiss still work.
   - Slice C wizard gating + auto-save + consent gate still pass their tests.
   - Non-blocking OCR failure path still passes its test.
   - Ownership/security posture unchanged.
7. **Tests cover**:
   - Documents step renders 3 cards with both file + camera inputs per kind.
   - "Aizvietot" anchor link is no longer rendered (regression guard).
   - Sticky-CTA marker class is on per-step nav rows.
   - Async upload endpoint accepts a POST from the camera input the same way as from the file-picker input.
   - Visual contract test extended with the new selectors (`.fk-upload-slot`, `.fk-camera-only`, `.fk-wizard-nav--sticky`).
8. **Verification gates green**:
   - `uv run pytest -q` green.
   - `uv run ruff check .` green.
   - `uv run mypy .` green.
9. **Manual LAN verification documented**:
   - Phone load of `/applications/<id>/`: 3 cards with two buttons each; camera button opens device camera; sticky Turpināt visible while scrolling.
   - Desktop load: camera buttons hidden; existing layout intact.
   - Notes recorded in the delivery commit body.

## Verification (for the P4 Slice D build, not this design doc)

Verification gates the slice as a whole, not individual tasks:
- Full pytest run green at slice end.
- ruff + mypy green.
- Manual LAN check on `http://192.168.3.245:8000/applications/<id>/` on at least one Android or iOS device and one desktop browser, documented in the delivery commit.
- Slice deliverables logged in `AGENTS.md` under a new "P4 Slice D delivered" subsection.

## Open questions

None at design time. The two areas where implementation could surface a question:
- Sticky CTA + iOS Safari on-screen keyboard interaction — fall back to `position: fixed` with a viewport-aware padding if a regression is observed.
- Form binding when both file inputs are populated — default to "camera wins" (Django's last-value semantics). Revisit only if user testing surfaces confusion.
