# P4 Slice E — Entry / Chooser / Portal Polish + Latvian Copy Audit (Design Spec)

**Date:** 2026-05-25
**Phase:** P4 (Parent-flow UX polish + mobile-first workspace)
**Slice:** E — final remainder
**Predecessors:** Slices A–D delivered (see `AGENTS.md` and `docs/milestones.md`)

---

## 1. Goal

Close P4 by polishing the three secondary parent surfaces — `/register/`, `/register/verify/`, `/portal/` — so they match the mobile-first visual cohesion delivered for the workspace in Slice D, fold them onto the shared cross-cutting UX primitives, and normalize Latvian copy across all parent-facing surfaces.

This slice satisfies the remaining P4 acceptance criteria:

- **Item 2** — Latvian copy normalized across `/register/`, `/register/verify/`, `/portal/`, `/applications/new/`, `/applications/<id>/`; zero English leakage on parent flows; admin surfaces unchanged.
- **Item 8** — Entry + chooser + portal polished: audited at mobile breakpoints, empty/error states use the shared cross-cutting primitives, visual cohesion with the workspace.
- **Item 9** — Cross-cutting UX primitives consistently applied (shared empty-state, error-state, spinner, toast, inline-error). Note: error-state is reviewed against these surfaces and found not applicable — `/register/` and `/register/verify/` handle errors via `alert.html` + `error_summary.html` (which remain unchanged here), and `/portal/` has no recoverable page-level error path. Empty-state coverage is the active change.

## 2. Scope

### 2.1 In scope

1. **`/register/` — `templates/registrations/start_registration.html`** — full polish: mobile breakpoints, visual cohesion, fix duplicate `section_card` include, fix `fk-button primary` → `fk-button fk-button--primary`, drop the `fk-eyebrow` wrapper around the form, ≥44 px touch targets.
2. **`/register/verify/` — `templates/registrations/verify_code.html`** — full polish: mobile breakpoints, visual cohesion, replace the inline-styled `pending_email` paragraph with a shared `.fk-page-intro` helper class, add `autofocus` / `inputmode="numeric"` / `autocomplete="one-time-code"` on the code field, ≥44 px touch targets.
3. **`/portal/` — `templates/registrations/parent_portal.html`** — full polish: mobile breakpoints for the `.fk-applications` grid, strip inline `style="..."` attributes from the application-list region, apply the shared `empty_state.html` partial (currently uses bespoke `.fk-empty-state` markup).
4. **`/applications/new/` — `templates/registrations/new_registration.html`** — copy-only audit (no-JS fallback path; not used by users with JavaScript). No layout or mobile work.
5. **`/applications/<id>/` — `templates/registrations/application_workspace.html`** — copy-only sweep. Workspace mobile polish was delivered in Slice D.
6. **Latvian copy normalization regression test** — a single parametrized test that renders each parent surface and scans rendered visible text for English-token leakage. Drives the audit.
7. **Cross-cutting partials** — extend `templates/parent_ui/includes/empty_state.html` with an optional CTA slot so the portal can switch off its bespoke markup without losing the "Sākt jaunu reģistrāciju" call-to-action.
8. **CSS additions** in `static/css/parent_theme.css` — `.fk-page-intro` helper class and a new `@media (max-width: 720px)` block covering portal-list stacking, helper-card stacking, and entry/verify-form mobile attributes.

### 2.2 Out of scope

- Translation infrastructure (`gettext`, `.po` files). Multilingual architecture is an explicit non-priority per milestones Section 8; the work here is hardcoded Latvian text, not i18n machinery.
- Admin surfaces (`admin_review_queue.html`, `admin_review_detail.html`, and partials used only by admin). Acceptance criterion 2 says admin surfaces are unchanged.
- `view_registration_detail.html` / `view_registration_summary.html` — thin shells; no polish required.
- Structural template refactors beyond the three clear bugs in `start_registration.html`.
- New visual elements (illustrations, icons beyond Slice D additions, motion).
- Workspace mobile polish (delivered in Slice D; copy sweep only here).
- Schema / model changes; no DB migrations.
- Backend logic changes. The only view-layer touch is providing `cta_url`/`cta_label` context variables to the portal's empty-state include if the existing context isn't already sufficient.
- Adjusting the hero-card illustration (`.fk-clipboard` SVG) at narrow viewport; already collapses correctly at the existing breakpoints.

## 3. Component Details

### 3.1 `start_registration.html`

Bugs to fix:

- Remove the duplicate `{% include "parent_ui/includes/section_card.html" %}` on line 11 (line 8 already includes it).
- Change `class="fk-button primary"` to `class="fk-button fk-button--primary"`.
- Drop the `fk-eyebrow` div wrapping the form. `fk-eyebrow` is a small-uppercase tagline style; wrapping a form in it produces incorrect visual treatment.
- Replace the bespoke `<div class="fk-guidance-section">` block with a `<section class="fk-section-card">` so the surface visually matches the workspace.

Mobile polish:

- Email input: `inputmode="email"`, `autocomplete="email"`, `font-size: 16px` (prevents iOS auto-zoom on focus), `min-height: 48px`.
- Submit button: `fk-button--full` at ≤720 px (existing modifier from Slice D).

### 3.2 `verify_code.html`

- Replace the inline-styled `<p class="fk-eyebrow" style="margin: 0 0 16px; color: var(--fk-muted);">` with a new shared helper class `.fk-page-intro` (defined in CSS — see 3.5).
- Code input: `inputmode="numeric"`, `autocomplete="one-time-code"`, `autofocus`, `min-height: 48px`, `font-size: 18px`, `letter-spacing: 0.3em` for legibility. Preserve existing `maxlength="6"` and `pattern="[0-9]{6}"`.
- Submit button: `fk-button--full` at ≤720 px.

### 3.3 `parent_portal.html`

Replace inline `style="..."` attributes with token-based classes:

- `style="margin: 0 0 16px; color: var(--fk-muted);"` → `.fk-page-intro`.
- `style="margin-top:28px;"` and `style="margin-top:10px;"` → remove; rely on partial-level spacing or add minimal modifier classes. Inline margin-top values that exist solely because of historical layout drift should not survive this slice.
- `style="margin-top:16px;"` on the empty-state CTA → solved by moving to the shared `empty_state.html` partial whose CTA slot owns its own spacing.

Use shared `empty_state.html`. Replace this current bespoke markup:

```django
<div class="fk-empty-state" style="margin-top:28px;">
  <h2>Nav pieteikumu</h2>
  <p>Jums vēl nav neviena pieteikuma.</p>
  <a href="{% url 'registrations:new-application' %}"
     class="fk-button fk-button--primary"
     style="margin-top:16px;">Sākt jaunu reģistrāciju</a>
</div>
```

with:

```django
{% include "parent_ui/includes/empty_state.html" with title="Nav pieteikumu" body="Jums vēl nav neviena pieteikuma." cta_url=new_application_url cta_label="Sākt jaunu reģistrāciju" %}
```

`new_application_url` is resolved in the view (`apps/registrations/views.py`) and added to the template context; the include itself stays template-only.

Mobile breakpoint for `.fk-applications` at ≤720 px:

- Each `.fk-application-card` stacks its child blocks vertically (person → status → next-step → actions).
- The action button becomes full-width.
- The avatar element shrinks slightly to keep the header line clean.

`.fk-helper-card` at ≤720 px: icon + copy stack, CTA full-width.

### 3.4 `new_registration.html`

Copy-only sweep. The page text is already Latvian; the audit test will catch anything missed. No layout work.

### 3.5 `static/css/parent_theme.css` additions

New helper class:

```css
.fk-page-intro {
  margin: 0 0 16px;
  color: var(--fk-muted);
  font-size: 0.95rem;
  line-height: 1.5;
}
```

New rules appended to the existing `@media (max-width: 720px)` block (or, if cleaner, a new sibling block — implementation detail decided in the plan):

```css
@media (max-width: 720px) {
  .fk-applications { grid-template-columns: 1fr; gap: 16px; }
  .fk-application-card { grid-template-columns: 1fr; padding: 18px; }
  .fk-app-actions .fk-button { width: 100%; box-sizing: border-box; }
  .fk-helper-card { flex-direction: column; align-items: stretch; }
  .fk-helper-card .fk-button { width: 100%; box-sizing: border-box; }
}
```

Exact selectors will be confirmed in the plan by reading the current CSS — the rules above are illustrative of intent.

### 3.6 Updated `empty_state.html`

```django
{% comment %}
Shared empty-state primitive. Optional CTA slot.

Parameters:
  title      — Latvian heading copy (required if used).
  body       — Latvian explanatory copy (optional).
  cta_url    — URL for the optional action button (optional).
  cta_label  — Latvian label for the optional action button (optional).
{% endcomment %}
<div class="fk-empty-state" data-empty-state>
  {% if title %}<p class="fk-empty-state__title">{{ title }}</p>{% endif %}
  {% if body %}<p class="fk-empty-state__body">{{ body }}</p>{% endif %}
  {% if cta_url and cta_label %}
    <a href="{{ cta_url }}" class="fk-button fk-button--primary fk-button--full fk-empty-state__cta">{{ cta_label }}</a>
  {% endif %}
</div>
```

Existing two-argument callers (`title` + `body` only) continue to render the same DOM. Backward compatibility verified by test.

## 4. Tests & Verification

### 4.1 New test files

**`tests/registrations/test_parent_surface_copy_contract.py`**

A parametrized test that renders each parent surface and asserts no English-token leakage in visible text. Visible text is extracted by stripping `<script>`, `<style>`, and HTML tags from the rendered response.

```python
ENGLISH_TOKENS = (
    "submit", "save", "continue", "back", "next", "cancel",
    "loading", "error", "success", "please", "required",
    "yes", "no", "warning", "delete", "edit",
)

ALLOWED_FRAGMENTS = (
    "FK Cēsis",
    "csrfmiddlewaretoken",
    "multipart/form-data",
    "image/*",
    "id_",
)
```

Parametrized across `start-registration`, `verify-code`, `parent-portal`, `application-workspace`, and `new-application` (rendered via its POST-invalid path).

**`tests/registrations/test_entry_surface_polish.py`**

- `TestStartRegistrationPolish`: rendered HTML contains exactly one `fk-section-card` element (regression for duplicate include), the submit button uses `fk-button--primary` (regression for the typo), there is no `fk-eyebrow` element wrapping a `<form>`, the email input has `inputmode="email"` and `autocomplete="email"`.
- `TestVerifyCodePolish`: code input has `inputmode="numeric"`, `autocomplete="one-time-code"`, `autofocus`, preserved `maxlength="6"` and `pattern="[0-9]{6}"`; the pending-email notice uses `.fk-page-intro` and contains no `style="..."` attribute.
- `TestParentThemeCssEntrySurfaces`: `.fk-page-intro` rule exists in `static/css/parent_theme.css`.

**`tests/registrations/test_portal_polish.py`**

- `TestPortalEmptyState`: rendering the portal with a verified account that has no applications produces the shared empty-state DOM (`data-empty-state`, `.fk-empty-state__title`, `.fk-empty-state__cta`).
- `TestPortalNoInlineStyles`: in the application-list region, neither `<article class="fk-application-card">` nor its descendants carry a `style="..."` attribute.
- `TestParentThemeCssPortalMobile`: CSS contains a `@media (max-width: 720px)` block referencing `.fk-applications`, `.fk-application-card`, `.fk-app-actions .fk-button`, and `.fk-helper-card`.
- `TestEmptyStatePartialAcceptsCta`: rendering `empty_state.html` directly with `cta_url`/`cta_label` produces the anchor with `fk-button--primary fk-button--full`; rendering without them produces no anchor (backward compatibility).

### 4.2 Existing tests that may need updates

Any test that depends on the bespoke portal empty-state markup (`<h2>Nav pieteikumu</h2>` rendered directly) must be updated to match the shared partial's `__title` class. The plan must run `uv run pytest -q tests/registrations/ -k 'portal or empty_state' --collect-only` early to surface collisions.

### 4.3 Manual LAN verification (recorded in `AGENTS.md` at closeout)

To be performed at `192.168.3.245` on a phone after implementation lands:

1. `/register/` at 320 px viewport — form fits, no horizontal scroll, button reachable with thumb, `type="email"` keyboard appears.
2. `/register/verify/` at 320 px — code field autofocuses, numeric keypad appears, paste-from-SMS works.
3. `/portal/` empty state (new verified account, no apps) — empty state renders via shared partial, CTA full-width and tappable.
4. `/portal/` with apps — list stacks cleanly, action button full-width, status badge readable.
5. All four surfaces — no visible English text anywhere except the FK Cēsis brand.

### 4.4 Project gates

- `uv run pytest -q` (full suite — expected to land at ~810 tests, up from 798).
- `uv run ruff check .` clean.
- `uv run mypy .` clean.

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| English-token regex false-positives on HTML element names or attribute values | Strip tags and attributes before scanning; allowlist legitimate fragments with code comments explaining each entry. |
| Extending `empty_state.html` breaks existing callers | New CTA parameters are optional; existing two-arg calls continue to render the same DOM. Backward-compat test added. |
| Mobile-stacking CSS bleeds into desktop layout | Tests assert each new rule lives inside `@media (max-width: 720px)`; LAN verification confirms desktop layout unchanged. |
| Copy audit catches strings outside the listed token vocabulary | The audit test is the source of truth, not this spec's token list. If novel English fragments surface during implementation, extend the token list and re-run. |
| `verify_code.html` `autofocus` interferes with screen readers | `autofocus` on the primary input of a single-purpose page is standard and accessible; no skip-link removal required. |

## 6. Task sequencing (high level)

1. Latvian copy audit contract test scaffold (RED) — drives the rest.
2. Fix Latvian leaks surface by surface (GREEN).
3. Extend `empty_state.html` with optional CTA slot + backward-compat test.
4. `start_registration.html` polish — bug fixes + mobile input attrs + tests.
5. `verify_code.html` polish — input attrs + `.fk-page-intro` migration + tests.
6. `parent_portal.html` polish — switch to shared empty-state partial, strip inline styles, view-context updates if needed + tests.
7. CSS mobile breakpoints — append the new media-query block + tests.
8. Final gates + manual LAN verification + docs closeout (`AGENTS.md` "Slice E delivered" + `docs/milestones.md` P4 status flipped to complete).

The implementation plan (`docs/superpowers/plans/2026-05-25-p4-slice-e-entry-chooser-portal-polish.md`) will expand this sequence into bite-sized TDD tasks.

## 7. Definition of Done

This slice is closed when:

- P4 acceptance criteria 2, 8, and 9 are met (re-read and confirmed after implementation).
- Test count moves from 798 to ~810 (or higher); `ruff` and `mypy` clean.
- LAN verification checklist results recorded in `AGENTS.md`.
- `docs/milestones.md` P4 status flips from "Slices A–D delivered; Slice E outstanding" to "Slices A–E delivered" (P4 complete).
