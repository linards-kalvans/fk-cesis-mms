# Style-Guide Application to Django Templates

**Date:** 2026-05-15  
**Status:** Approved  
**Scope:** Full alignment — CSS, HTML structure, rich components, multi-step wizard

---

## Goal

Apply the FK Cēsis brand design from `style-guide/fk_cesis_list.html` and `style-guide/fk_cesis_responsive_registration.html` to all parent-facing Django templates. Result: templates visually match the style-guide pixel-for-pixel, including a JS-driven multi-step wizard on registration forms.

---

## Current State

- `static/css/tokens.css` — 3 root variables only
- `static/css/parent_theme.css` — partial styles; missing body background, section card body structure, button gradients, stepper, dropzones
- `static/css/parent_pages.css` — partial styles; missing progress bars, helper card, clipboard illustration
- Templates use `fk-*` class names but inconsistently (`.fk-button.primary` vs `.fk-button--primary` BEM)
- `parent_portal.html` has many inline styles; application cards lack progress bars
- Registration forms are flat single-page; no step-by-step UX

---

## Architecture

### CSS Layer

Three files, each with a clear purpose:

**`static/css/tokens.css`**  
Canonical design tokens only. Source of truth for all values.

**`static/css/parent_theme.css`**  
Component styles: body, header, hero card, section card structure, buttons, status badges, stepper, dropzones, info boxes.

**`static/css/parent_pages.css`**  
Page layout styles: application cards, progress bars, helper card, clipboard illustration, portal page structure.

No inline styles in any template.

### Button Class Standardization

Migrate all button classes to BEM:
- `.fk-button--primary` (navy gradient)
- `.fk-button--secondary` (white, navy border)
- `.fk-button--red` (red gradient, used for final submit)

Applies to: `parent_portal.html`, `start_registration.html`, `new_registration.html`, `application_workspace.html`.

---

## Component Design

### Header (`parent_ui/includes/header.html`)

Add `header-inner` wrapper div. The header element spans full width with navy background; the inner div constrains content to max-width with padding. Matches style-guide exactly.

```
<header class="fk-site-header">
  <div class="fk-header-inner">
    <div class="fk-brand">...</div>
  </div>
</header>
```

### Section Card (`parent_ui/includes/section_card.html`)

Redesign from bare wrapper to structured card:

```
<section class="fk-section-card">
  <div class="fk-section-header">
    <div class="fk-section-title-wrap">
      <div class="fk-section-icon">{{ icon }}</div>
      <div>
        <h2>{{ title }}</h2>
        <p class="fk-section-note">{{ note }}</p>
      </div>
    </div>
    [optional collapse button]
  </div>
  <div class="fk-section-body">
    {{ content }}
  </div>
</section>
```

Existing direct usages of `fk-section-card` in `application_workspace.html` and `new_registration.html` are updated inline (not via include, since `{% block %}` doesn't work with `{% include %}`).

### Hero Card — Portal Variant

Three-column grid: illustration | copy + CTAs | info card.

```
[clipboard CSS illustration] | [title + subtitle + action buttons] | [info card]
```

CSS clipboard illustration uses pure CSS (`.clipboard`, `.ball`) — no external image.

### Hero Card — Registration Variant

Two-column grid: copy + mobile progress | stepper.

```
[eyebrow + h1 + lead + mobile-progress] | [stepper: 6 steps]
```

On mobile (<720px): stepper hides, mobile progress bar shows.

### Stepper

```html
<div class="fk-stepper">
  <div class="fk-step fk-step--active">
    <div class="fk-step-number">1</div>
    <div class="fk-step-label">ID dokuments</div>
  </div>
  ...
</div>
```

JS marks current step with `fk-step--active` class.

---

## Multi-Step Wizard

### Implementation: JS Tab Navigator

All form fields rendered in HTML on page load. JavaScript controls visibility of `.fk-wizard-step` containers. Single form submit at end. No backend changes.

### Step Mapping

Django `form.grouped_fields` sections map to wizard steps:

| Section name | Step # | Icon | Label |
|---|---|---|---|
| documents | 1 | ▣ | ID dokuments |
| guardian | 2 | 👤 | Vecāka informācija |
| member | 3 | ⚽ | Bērna informācija |
| agreement | 4 | ✓ | Piekrišana |
| _(summary)_ | 5 | ▤ | Pārskats |

The last "Pārskats" step renders a summary of entered values (read-only) plus the final submit button.

### Navigation

Each step (except last) has:
- Back button (`.fk-button--secondary`) — hidden on step 1
- Next button (`.fk-button--primary`)

Last step has:
- Back button
- Save draft (`.fk-button--secondary`)
- Submit (`.fk-button--red`)

### JS Behavior

```js
// Vanilla JS, no dependencies
// - Reads total step count from DOM
// - Shows/hides .fk-wizard-step[data-step="N"]
// - Updates stepper active class
// - Updates mobile progress text + bar width
// - "Next" validates required fields in current step before advancing
```

### Validation

On "Next": check that all `required` inputs in visible step are non-empty. If any fail, show inline error. Do not advance. On final submit, Django handles full validation server-side.

---

## Portal Page (`registrations/parent_portal.html`)

Full redesign to match `fk_cesis_list.html`:

1. Page title + subtitle (`.page-title.anton`, `.page-subtitle`)
2. Hero card (3-column): clipboard illustration, greeting copy + CTAs, info card
3. Section head (`section-head`) with h2 "Pieteikumu saraksts"
4. Application cards with progress bars
5. Helper card at bottom
6. New registration CTA

Application cards add `.progress-wrap` column with:
- Progress title (next step label, if known)
- Progress meta text
- Progress bar (width = percentage complete)

If no `progress_pct` available from context, show indeterminate state.

---

## Registration Forms

**`application_workspace.html`** and **`new_registration.html`** both get the wizard. The workspace also keeps its read-only view mode (when `workspace_mode != "editable"`, skip wizard and show flat read-only sections as before).

---

## Files Changed

### CSS
- `static/css/tokens.css`
- `static/css/parent_theme.css`
- `static/css/parent_pages.css`

### Templates
- `templates/base.html`
- `templates/parent_ui/includes/header.html`
- `templates/parent_ui/includes/section_card.html` _(note: mostly superseded by direct inline usage)_
- `templates/registrations/parent_portal.html`
- `templates/registrations/application_workspace.html`
- `templates/registrations/new_registration.html`
- `templates/accounts/request_magic_link.html`

---

## What Is NOT Changing

- Django views, models, forms — no backend changes
- Admin templates
- Deprecated pages (`edit_registration.html`, `view_registration_detail.html`, `view_registration_summary.html`) — left as-is (they redirect to workspace)
- `verify_code.html`, `magic_link_sent.html`, `verify_error.html` — minor CSS class cleanup only

---

## Risks

- `form.grouped_fields` sections may not exactly match the 4 sections assumed above. Implementation will use actual section names returned by the Django form.
- If the form has fewer or more than 4 sections, the stepper adapts (step count = section count + 1 for review).
- `progress_pct` for application cards requires data from view context. If not present, progress bar is hidden.
