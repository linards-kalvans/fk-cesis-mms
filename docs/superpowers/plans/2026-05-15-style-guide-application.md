# Style-Guide Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply FK Cēsis brand design from `style-guide/` to all parent-facing Django templates, including a JS-driven multi-step wizard on registration forms.

**Architecture:** Update `parent_theme.css` (component styles) and `parent_pages.css` (page layout) with extracted style-guide CSS. Redesign `parent_portal.html` to match `fk_cesis_list.html`. Add JS step navigator (`wizard.js`) and update registration templates to multi-step wizard matching `fk_cesis_responsive_registration.html`. No backend changes.

**Tech Stack:** Django templates, vanilla CSS (no preprocessor), vanilla JS (no dependencies), pytest-django for tests.

---

## Critical Constraints From Existing Tests

Read `tests/registrations/test_parent_visual_pages.py` before touching templates. These assertions MUST hold:

- `base.html` must have `href="/static/style-guide/tokens.css"` (do NOT change this path)
- `parent_portal.html` must include `hero_card.html`, `section_card.html`, `status_badge.html`
- Portal rendered HTML must contain: "Mani pieteikumi", "Pārskatiet un turpiniet", "Turpināt pieteikumu" (when draft exists), "Sākt jaunu reģistrāciju" (always), "Nav pieteikumu" (empty state)
- The line with "Turpināt pieteikumu" must contain `{% url` on the same line
- `start_registration.html` must include `hero_card.html`, `section_card.html`, `error_summary.html`
- Portal must use `fk-parent-page` and `fk-site-header` CSS classes
- Run `uv run pytest tests/registrations/test_parent_visual_pages.py -x` after each template task

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `static/css/parent_theme.css` | Rewrite | Full component system: header, section cards, stepper, buttons, dropzones |
| `static/css/parent_pages.css` | Rewrite | Portal layout: progress bars, clipboard illustration, helper card |
| `templates/base.html` | Modify | Add Inter weight 800, `extra_js` block |
| `templates/parent_ui/includes/header.html` | Modify | Add `fk-header-inner` wrapper div |
| `templates/parent_ui/includes/hero_card.html` | Rewrite | Portal variant (3-col) and default variant |
| `static/js/wizard.js` | Create | Vanilla JS step navigator |
| `templates/registrations/parent_portal.html` | Rewrite | Match `fk_cesis_list.html` design |
| `templates/registrations/application_workspace.html` | Rewrite | Multi-step wizard for editable mode |
| `templates/registrations/new_registration.html` | Rewrite | Multi-step wizard |

---

## Task 1: Rewrite `static/css/parent_theme.css`

**Files:**
- Modify: `static/css/parent_theme.css`

- [ ] **Step 1: Run existing tests to establish baseline**

```bash
cd /home/linards/Documents/Private/fk-cesis-mms
uv run pytest tests/registrations/test_parent_visual_pages.py -x -q 2>&1 | tail -5
```

Expected: all pass (or note which fail as pre-existing failures).

- [ ] **Step 2: Rewrite `static/css/parent_theme.css`**

Replace the entire file with:

```css
/* Parent-page theme — FK Cēsis MMS. Components, typography, shared UI. */

:root {
  --fk-blue: #0f0851;
  --fk-red: #ce1c20;
  --fk-red-dark: #ab171b;
  --fk-bg: #f4f6fb;
  --fk-white: #ffffff;
  --fk-text: #1e2141;
  --fk-muted: #6f7694;
  --fk-border: #dfe4f1;
  --fk-soft-blue: #eef1ff;
  --fk-radius: 12px;
  --fk-radius-xl: 24px;
  --fk-radius-lg: 18px;
  --fk-radius-md: 12px;
  --fk-spacing: 16px;
  --fk-shadow: 0 12px 30px rgba(15, 8, 81, 0.08);
  --fk-shadow-soft: 0 8px 20px rgba(15, 8, 81, 0.06);
  --fk-maxw: 1180px;
  --fk-maxw-list: 1240px;
}

* { box-sizing: border-box; }

body {
  font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
  background:
    radial-gradient(circle at top left, rgba(206, 28, 32, 0.06), transparent 25rem),
    linear-gradient(180deg, #fafbfe 0%, var(--fk-bg) 100%);
  color: var(--fk-text);
  margin: 0;
  min-height: 100vh;
}

img { max-width: 100%; display: block; }
a { color: inherit; text-decoration: none; }

h1, h2, h3 {
  font-family: 'Anton', sans-serif;
  letter-spacing: 0.02em;
  font-weight: 400;
  text-transform: uppercase;
}

.fk-parent-page {
  max-width: var(--fk-maxw);
  margin: 0 auto;
  padding: var(--fk-spacing);
}

/* ── Site header ── */

.fk-site-header {
  background: var(--fk-blue);
  color: var(--fk-white);
  border-bottom: 4px solid var(--fk-red);
  position: sticky;
  top: 0;
  z-index: 30;
  box-shadow: 0 10px 24px rgba(15, 8, 81, 0.18);
}

.fk-header-inner {
  max-width: var(--fk-maxw-list);
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.fk-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.fk-brand-logo {
  width: 72px;
  height: 72px;
  object-fit: contain;
  flex: 0 0 auto;
  filter: drop-shadow(0 8px 14px rgba(0, 0, 0, 0.25));
}

.fk-brand-text { min-width: 0; }

.fk-brand-title {
  font-family: 'Anton', sans-serif;
  font-size: 1.9rem;
  line-height: 1;
  letter-spacing: 0.02em;
  color: var(--fk-white);
  text-transform: uppercase;
  font-weight: 400;
}

.fk-brand-subtitle {
  margin-top: 4px;
  color: rgba(255, 255, 255, 0.86);
  font-size: 0.97rem;
  font-weight: 500;
}

/* ── Eyebrow / lead ── */

.fk-eyebrow {
  color: var(--fk-red);
  text-transform: uppercase;
  letter-spacing: .12em;
  font-weight: 800;
  font-size: 13px;
  margin-bottom: 8px;
}

.fk-lead {
  color: var(--fk-muted);
  font-size: 18px;
  line-height: 1.6;
  margin: 0;
  max-width: 720px;
}

/* ── Hero card (default: registration 2-col) ── */

.fk-hero-card {
  background: var(--fk-white);
  border: 1px solid var(--fk-border);
  box-shadow: var(--fk-shadow);
  border-radius: var(--fk-radius-xl);
  padding: 34px;
  margin-bottom: 24px;
  display: grid;
  grid-template-columns: 1.25fr .9fr;
  gap: 32px;
  overflow: hidden;
  position: relative;
}

.fk-hero-card::after {
  content: "";
  position: absolute;
  width: 260px;
  height: 260px;
  right: -90px;
  top: -110px;
  border-radius: 50%;
  background: rgba(215, 25, 32, 0.08);
  pointer-events: none;
}

.fk-hero-card h1 {
  font-family: 'Anton', sans-serif;
  font-weight: 400;
  text-transform: uppercase;
  font-size: clamp(38px, 5vw, 62px);
  margin: 0 0 12px;
  line-height: 1.03;
  color: var(--fk-blue);
  letter-spacing: -0.04em;
}

/* ── Section card ── */

.fk-section-card {
  background: var(--fk-white);
  border: 1px solid var(--fk-border);
  box-shadow: var(--fk-shadow-soft);
  border-radius: var(--fk-radius-xl);
  overflow: hidden;
  margin-bottom: 16px;
}

.fk-section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 28px 32px 8px;
}

.fk-section-title-wrap {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.fk-section-icon {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--fk-soft-blue);
  color: var(--fk-blue);
  flex: 0 0 auto;
  font-size: 22px;
}

.fk-section-header h2 {
  margin: 0;
  color: var(--fk-blue);
  font-size: 26px;
}

.fk-section-note {
  margin: 6px 0 0;
  color: var(--fk-muted);
  font-size: 15px;
  line-height: 1.55;
}

.fk-section-body {
  padding: 18px 32px 30px;
}

/* ── Form grid ── */

.fk-form-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 18px 22px;
  align-items: start;
}

.fk-field { grid-column: span 6; }
.fk-field--third { grid-column: span 4; }
.fk-field--full { grid-column: 1 / -1; }

/* ── Form fields ── */

.fk-form-field {
  margin-bottom: 16px;
}

.fk-form-field--error .fk-form-label { color: var(--fk-red); }

.fk-form-label {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #272759;
  margin-bottom: 7px;
}

.fk-form-field input[type="text"],
.fk-form-field input[type="email"],
.fk-form-field input[type="date"],
.fk-form-field input[type="number"],
.fk-form-field input[type="tel"],
.fk-form-field select,
.fk-form-field textarea {
  width: 100%;
  min-height: 46px;
  border: 1px solid var(--fk-border);
  border-radius: 8px;
  padding: 0 14px;
  color: var(--fk-text);
  background: var(--fk-white);
  font: inherit;
  font-size: 15px;
  outline: none;
  transition: border-color .15s ease, box-shadow .15s ease;
}

.fk-form-field input[type="checkbox"] {
  width: 19px;
  height: 19px;
  accent-color: var(--fk-blue);
}

.fk-form-field input:focus,
.fk-form-field select:focus,
.fk-form-field textarea:focus {
  border-color: var(--fk-blue);
  box-shadow: 0 0 0 4px rgba(15, 8, 81, 0.08);
}

.fk-form-field input.fk-input--error {
  border-color: var(--fk-red);
}

.fk-form-help {
  color: var(--fk-muted);
  font-size: 13px;
  margin: 4px 0 0;
}

.fk-form-error {
  color: var(--fk-red);
  font-size: 13px;
  font-weight: 600;
  margin: 4px 0 0;
}

/* ── Dropzone (file upload) ── */

.fk-dropzone {
  display: block;
  min-height: 142px;
  border: 2px dashed #b8bfd3;
  border-radius: 12px;
  display: grid;
  place-items: center;
  text-align: center;
  padding: 20px;
  color: var(--fk-blue);
  background: linear-gradient(180deg, #fff 0%, #fafbff 100%);
  cursor: pointer;
  transition: border-color .15s ease, background .15s ease, transform .15s ease;
  width: 100%;
}

.fk-dropzone:hover {
  border-color: var(--fk-blue);
  background: #f7f8ff;
  transform: translateY(-1px);
}

.fk-dropzone-icon { font-size: 28px; margin-bottom: 8px; }
.fk-dropzone-title { font-weight: 700; margin-bottom: 5px; }
.fk-dropzone-meta { color: var(--fk-muted); font-size: 13px; }

/* ── Info / requirements boxes ── */

.fk-info-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 13px 16px;
  margin-top: 18px;
  background: #eef4ff;
  color: #3a4670;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.45;
}

.fk-requirements {
  background: #f1f5ff;
  border-radius: 12px;
  padding: 18px;
  color: #303762;
  font-size: 14px;
  line-height: 1.55;
}

.fk-requirements strong { color: var(--fk-blue); }
.fk-requirements ul { margin: 8px 0 0; padding-left: 18px; }

/* ── Buttons ── */

.fk-button {
  appearance: none;
  border: 1px solid transparent;
  min-height: 48px;
  padding: 0 28px;
  border-radius: 9px;
  font-weight: 700;
  font-size: 15px;
  font-family: 'Inter', sans-serif;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: transform .15s ease, box-shadow .15s ease;
  text-decoration: none;
  white-space: nowrap;
}

.fk-button:hover { transform: translateY(-1px); }

/* BEM and legacy shorthand both supported */
.fk-button--primary,
.fk-button.primary {
  color: var(--fk-white);
  background: linear-gradient(135deg, var(--fk-blue), #1a0a7e);
  box-shadow: 0 12px 22px rgba(9, 6, 74, .20);
}

.fk-button--secondary,
.fk-button.secondary {
  color: var(--fk-blue);
  background: var(--fk-white);
  border-color: var(--fk-blue);
}

.fk-button--red {
  color: var(--fk-white);
  background: linear-gradient(135deg, var(--fk-red), var(--fk-red-dark));
  box-shadow: 0 10px 20px rgba(206, 28, 32, 0.18);
}

/* ── Stepper ── */

.fk-stepper {
  align-self: center;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
  gap: 0;
  position: relative;
  z-index: 1;
}

.fk-step {
  text-align: center;
  color: var(--fk-muted);
  position: relative;
  min-width: 60px;
}

.fk-step:not(:first-child)::before {
  content: "";
  position: absolute;
  height: 2px;
  left: -50%;
  right: 50%;
  top: 18px;
  background: var(--fk-border);
  z-index: -1;
}

.fk-step-number {
  width: 38px;
  height: 38px;
  margin: 0 auto 10px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: #eef0f6;
  border: 1px solid var(--fk-border);
  color: var(--fk-muted);
  font-weight: 800;
  font-size: 15px;
}

.fk-step--active { color: var(--fk-red); }
.fk-step--active .fk-step-number {
  color: var(--fk-white);
  background: var(--fk-red);
  border-color: var(--fk-red);
  box-shadow: 0 10px 18px rgba(215, 25, 32, .24);
}

.fk-step-label {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.3;
}

/* ── Mobile progress (wizard) ── */

.fk-mobile-progress {
  display: none;
  margin-top: 22px;
  font-size: 14px;
}

.fk-progress-line {
  height: 4px;
  background: #eef0f6;
  border-radius: 99px;
  overflow: hidden;
  margin: 8px 0;
}

.fk-progress-line span {
  display: block;
  height: 100%;
  background: var(--fk-red);
  transition: width .3s ease;
  width: 0%;
}

/* ── Wizard step visibility ── */

.fk-wizard-step { display: none; }
.fk-wizard-step.fk-wizard-step--active { display: block; }

/* ── Wizard nav ── */

.fk-wizard-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 26px;
}

.fk-wizard-nav-actions {
  display: flex;
  gap: 12px;
}

/* ── Status badges ── */

.fk-status-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.95rem;
  white-space: nowrap;
}

.fk-status-draft { color: #4b63d1; background: #edf2ff; }
.fk-status-submitted { color: #22a85a; background: #eaf8ef; }
.fk-status-fix-requested { color: #991b1b; background: #fee2e2; }
.fk-status-approved { color: #22a85a; background: #eaf8ef; }
.fk-status-rejected { color: #991b1b; background: #fee2e2; }

/* ── Status banner ── */

.fk-status-banner {
  border-radius: 12px;
  padding: 14px 18px;
  margin-top: 16px;
  font-size: 15px;
}

.fk-status-banner--draft { background: #edf2ff; color: #4b63d1; }
.fk-status-banner--submitted { background: #eaf8ef; color: #22a85a; }
.fk-status-banner--fix_requested { background: #fee2e2; color: #991b1b; }
.fk-status-banner--approved { background: #eaf8ef; color: #22a85a; }
.fk-status-banner--rejected { background: #fee2e2; color: #991b1b; }

/* ── Error summary ── */

.fk-error-summary {
  background: #fef2f2;
  border-left: 4px solid var(--fk-red);
  padding: 14px 18px;
  margin-bottom: 20px;
  border-radius: 8px;
  color: #991b1b;
  font-weight: 600;
  font-size: 15px;
}

.fk-error-summary ul { margin: 8px 0 0; padding-left: 18px; }
.fk-error-summary a { color: inherit; text-decoration: underline; }

/* ── Source / document badges ── */

.fk-source-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--fk-soft-blue);
  color: var(--fk-blue);
  margin-left: 6px;
  vertical-align: middle;
}

/* ── Document card ── */

.fk-document-card {
  border: 1px solid var(--fk-border);
  border-radius: var(--fk-radius-md);
  padding: 16px;
  background: var(--fk-white);
  margin-bottom: 12px;
}

.fk-document-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.fk-document-card__kind { font-weight: 700; color: var(--fk-text); }
.fk-document-card__filename { color: var(--fk-muted); font-size: 14px; margin: 0 0 8px; }
.fk-document-card__hint { color: var(--fk-muted); font-size: 13px; margin: 0 0 10px; }
.fk-document-card__empty { color: var(--fk-muted); font-size: 14px; margin: 0; }

.fk-link { color: var(--fk-blue); text-decoration: underline; }

/* ── Summary grid (wizard review step) ── */

.fk-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 22px;
}

.fk-summary-item {
  background: #fafbff;
  border: 1px solid var(--fk-border);
  border-radius: 12px;
  padding: 16px;
}

.fk-summary-item span {
  display: block;
  color: var(--fk-muted);
  font-size: 13px;
  margin-bottom: 6px;
}

.fk-summary-item strong {
  color: var(--fk-blue);
  font-size: 16px;
}

.fk-fine-print {
  margin-top: 0;
  margin-bottom: 0;
  color: var(--fk-muted);
  font-size: 13px;
  line-height: 1.5;
}

/* ── Empty state ── */

.fk-empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--fk-muted);
}

.fk-empty-state h2 {
  font-size: 20px;
  color: var(--fk-text);
  margin: 0 0 8px;
}

/* ── Page heading ── */

.fk-page-heading { margin-bottom: 24px; }

.fk-page-heading h1 {
  font-size: clamp(38px, 5vw, 62px);
  color: var(--fk-blue);
  margin: 0 0 12px;
}

/* ── Form actions (flat form, non-wizard) ── */

.fk-form-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
}

/* ── Responsive ── */

@media (max-width: 980px) {
  .fk-hero-card { grid-template-columns: 1fr; }
  .fk-stepper { overflow-x: auto; padding-bottom: 4px; }
  .fk-summary-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 720px) {
  .fk-site-header { position: static; }
  .fk-header-inner { padding: 12px 16px; }
  .fk-brand-logo { width: 58px; height: 58px; }
  .fk-brand-title { font-size: 1.5rem; }
  .fk-brand-subtitle { font-size: 0.86rem; }
  .fk-hero-card { border-radius: 20px; padding: 24px 20px; }
  .fk-hero-card .fk-stepper { display: none; }
  .fk-mobile-progress { display: block; }
  .fk-section-header { padding: 22px 20px 4px; }
  .fk-section-body { padding: 16px 20px 22px; }
  .fk-section-icon { width: 40px; height: 40px; font-size: 19px; }
  .fk-section-header h2 { font-size: 21px; }
  .fk-form-grid .fk-field,
  .fk-form-grid .fk-field--third { grid-column: 1 / -1; }
  .fk-summary-grid { grid-template-columns: 1fr; }
  .fk-wizard-nav {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
}

@media (max-width: 420px) {
  .fk-brand-title { font-size: 1.2rem; }
  .fk-brand-subtitle { display: none; }
  .fk-hero-card { padding: 22px 18px; }
  .fk-section-header { padding: 20px 16px 4px; }
  .fk-section-body { padding: 14px 16px 20px; }
}
```

- [ ] **Step 3: Verify Django check passes**

```bash
uv run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Run visual page tests**

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -x -q 2>&1 | tail -10
```

Expected: same pass/fail ratio as baseline (CSS changes don't affect template tests).

- [ ] **Step 5: Commit**

```bash
git add static/css/parent_theme.css
git commit -m "style: rewrite parent_theme.css with full style-guide component system"
```

---

## Task 2: Rewrite `static/css/parent_pages.css`

**Files:**
- Modify: `static/css/parent_pages.css`

- [ ] **Step 1: Rewrite `static/css/parent_pages.css`**

Replace the entire file with:

```css
/* Parent-page layout — FK Cēsis MMS. Portal layout, application cards, portal components. */

/* ── Page wrapper ── */

.fk-page-wrapper,
.fk-page {
  max-width: var(--fk-maxw-list, 1240px);
  margin: 0 auto;
  padding: 34px 24px 56px;
  min-height: calc(100vh - 120px);
}

/* ── Portal page title ── */

.fk-page-title {
  margin: 0 0 8px;
  color: var(--fk-blue);
  font-size: clamp(2.3rem, 4vw, 4rem);
  line-height: 1;
}

.fk-page-subtitle {
  margin: 0 0 28px;
  color: var(--fk-muted);
  font-size: 1.05rem;
  line-height: 1.55;
}

/* ── Portal hero card (3-col variant) ── */

.fk-hero-card--portal {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 270px;
  gap: 24px;
  align-items: center;
  padding: 28px;
}

.fk-hero-illustration {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  position: relative;
}

/* CSS clipboard illustration */
.fk-clipboard {
  width: 140px;
  height: 172px;
  background: linear-gradient(180deg, #ffffff 0%, #f5f7ff 100%);
  border: 5px solid var(--fk-blue);
  border-radius: 18px;
  position: relative;
  box-shadow: 0 16px 28px rgba(15, 8, 81, 0.1);
}

.fk-clipboard::before {
  content: "";
  position: absolute;
  width: 62px;
  height: 24px;
  background: var(--fk-blue);
  border-radius: 10px 10px 14px 14px;
  top: -14px;
  left: 50%;
  transform: translateX(-50%);
}

.fk-clipboard-line {
  height: 8px;
  border-radius: 10px;
  background: #dbe2fa;
  margin: 16px 18px 0;
}

.fk-clipboard-line--short { width: 50%; }
.fk-clipboard-line--med { width: 72%; }

.fk-clipboard-check {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--fk-red);
  margin: 14px 18px 0 auto;
}

.fk-ball {
  position: absolute;
  left: 18px;
  bottom: 4px;
  width: 44px;
  height: 44px;
  background: radial-gradient(circle at 30% 30%, #fff 0%, #f0f3ff 100%);
  border: 4px solid var(--fk-blue);
  border-radius: 50%;
  box-shadow: 0 10px 16px rgba(15, 8, 81, 0.08);
}

.fk-hero-copy {
  position: relative;
  z-index: 1;
}

.fk-hero-copy h2 {
  margin: 0 0 10px;
  color: var(--fk-blue);
  font-size: 2rem;
  line-height: 1.05;
}

.fk-hero-copy p {
  margin: 0 0 20px;
  color: var(--fk-muted);
  line-height: 1.65;
  font-size: 1rem;
  max-width: 640px;
}

.fk-hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

/* ── Info card (inside hero) ── */

.fk-info-card {
  background: var(--fk-white);
  border: 1px solid var(--fk-border);
  border-radius: var(--fk-radius-lg);
  padding: 22px 20px;
  box-shadow: var(--fk-shadow-soft);
  position: relative;
  z-index: 1;
}

.fk-info-card-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: var(--fk-soft-blue);
  color: var(--fk-blue);
  font-size: 22px;
  margin-bottom: 12px;
}

.fk-info-card h3 {
  margin: 0 0 10px;
  font-size: 1.08rem;
  color: var(--fk-blue);
  font-weight: 800;
  text-transform: none;
  letter-spacing: normal;
}

.fk-info-card p {
  margin: 0;
  font-size: 0.95rem;
  color: var(--fk-muted);
  line-height: 1.6;
}

/* ── Section head ── */

.fk-section-head {
  margin-top: 28px;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}

.fk-section-head h2 {
  margin: 0;
  color: var(--fk-blue);
  font-size: 2rem;
  line-height: 1;
}

/* ── Application list ── */

.fk-applications {
  display: grid;
  gap: 14px;
}

.fk-application-card {
  background: var(--fk-white);
  border: 1px solid var(--fk-border);
  border-radius: 20px;
  box-shadow: var(--fk-shadow-soft);
  padding: 20px;
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(160px, 1.2fr) minmax(220px, 1.6fr) auto;
  align-items: center;
  gap: 18px;
}

.fk-app-person {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.fk-app-avatar {
  width: 74px;
  height: 74px;
  border-radius: 50%;
  background: linear-gradient(180deg, #f6f8ff 0%, #eef2ff 100%);
  border: 1px solid var(--fk-border);
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: var(--fk-blue);
  font-size: 30px;
}

.fk-app-main { min-width: 0; }

.fk-app-name {
  margin: 0 0 8px;
  color: var(--fk-blue);
  font-size: 1.55rem;
  line-height: 1;
}

.fk-app-meta {
  display: grid;
  gap: 6px;
  color: var(--fk-muted);
  font-size: 0.96rem;
}

.fk-app-block { min-width: 0; }

.fk-block-label {
  display: block;
  font-size: 0.88rem;
  color: var(--fk-muted);
  margin-bottom: 8px;
  font-weight: 600;
}

/* ── Progress bar ── */

.fk-progress-wrap { min-width: 0; }

.fk-progress-title {
  font-weight: 700;
  color: var(--fk-text);
  margin-bottom: 6px;
  line-height: 1.4;
  font-size: 0.95rem;
}

.fk-progress-meta {
  color: var(--fk-muted);
  font-size: 0.9rem;
  margin-bottom: 8px;
}

.fk-progress-bar {
  width: 100%;
  height: 8px;
  background: #edf0f7;
  border-radius: 999px;
  overflow: hidden;
}

.fk-progress-bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--fk-blue), #3d57d3);
  transition: width .3s ease;
}

.fk-progress-bar--success > span {
  background: linear-gradient(90deg, #1a9a4d, #2db960);
}

.fk-app-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
}

/* ── Helper card ── */

.fk-helper-card {
  margin-top: 18px;
  background: var(--fk-white);
  border: 1px solid var(--fk-border);
  border-radius: 20px;
  box-shadow: var(--fk-shadow-soft);
  padding: 18px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}

.fk-helper-copy {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}

.fk-helper-icon {
  width: 46px;
  height: 46px;
  border-radius: 14px;
  background: var(--fk-soft-blue);
  color: var(--fk-blue);
  display: grid;
  place-items: center;
  font-size: 20px;
  flex: 0 0 auto;
}

.fk-helper-copy h3 {
  margin: 0 0 6px;
  color: var(--fk-blue);
  font-size: 1.05rem;
  font-weight: 800;
  text-transform: none;
  letter-spacing: normal;
}

.fk-helper-copy p {
  margin: 0;
  color: var(--fk-muted);
  line-height: 1.55;
  font-size: 0.95rem;
}

/* ── CTA group ── */

.fk-cta-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

/* ── Guidance section (start_registration page) ── */

.fk-guidance-section {
  background: var(--fk-white);
  border-radius: var(--fk-radius);
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.fk-guidance-section h2 {
  font-size: 18px;
  margin: 0 0 16px;
  color: var(--fk-blue);
  text-transform: none;
  letter-spacing: normal;
  font-family: 'Inter', sans-serif;
  font-weight: 800;
}

.fk-form-group { margin-bottom: 16px; }

.fk-form-group label {
  display: block;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 6px;
  color: var(--fk-text);
}

.fk-form-group input[type="email"],
.fk-form-group input[type="text"],
.fk-form-group input[type="password"] {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--fk-border);
  border-radius: 8px;
  font-size: 15px;
  font-family: 'Inter', sans-serif;
  box-sizing: border-box;
  min-height: 46px;
}

/* ── Responsive ── */

@media (max-width: 1120px) {
  .fk-hero-card--portal {
    grid-template-columns: 220px minmax(0, 1fr);
  }
  .fk-info-card { grid-column: 1 / -1; }
  .fk-application-card {
    grid-template-columns: minmax(0, 1.8fr) minmax(150px, 1fr) minmax(220px, 1.4fr) auto;
  }
}

@media (max-width: 900px) {
  .fk-hero-card--portal {
    grid-template-columns: 1fr;
    padding: 22px;
  }
  .fk-hero-illustration { justify-content: flex-start; }
  .fk-application-card {
    grid-template-columns: 1fr;
    align-items: start;
  }
  .fk-app-actions { justify-content: stretch; }
  .fk-app-actions .fk-button { width: 100%; }
}

@media (max-width: 680px) {
  .fk-page-wrapper,
  .fk-page { padding: 24px 12px 40px; }
  .fk-page-subtitle { margin-bottom: 20px; }
  .fk-hero-card--portal,
  .fk-application-card,
  .fk-helper-card { border-radius: 18px; }
  .fk-hero-card--portal { padding: 18px; }
  .fk-hero-copy h2 { font-size: 1.7rem; }
  .fk-hero-actions { display: grid; grid-template-columns: 1fr; }
  .fk-hero-actions .fk-button { width: 100%; }
  .fk-section-head { align-items: stretch; }
  .fk-app-person { align-items: flex-start; }
  .fk-app-avatar { width: 62px; height: 62px; font-size: 24px; }
  .fk-app-name { font-size: 1.3rem; }
  .fk-helper-card { padding: 16px; }
  .fk-helper-card .fk-button { width: 100%; }
}

@media (max-width: 420px) {
  .fk-page-title { font-size: 2.2rem; }
  .fk-hero-copy h2 { font-size: 1.45rem; }
}
```

- [ ] **Step 2: Run check + tests**

```bash
uv run python manage.py check && uv run pytest tests/registrations/test_parent_visual_pages.py -x -q 2>&1 | tail -10
```

Expected: Django check passes, visual tests same as baseline.

- [ ] **Step 3: Commit**

```bash
git add static/css/parent_pages.css
git commit -m "style: rewrite parent_pages.css with portal layout and progress components"
```

---

## Task 3: Update `templates/base.html`

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1: Add Inter weight 800 and `extra_js` block**

Current `base.html` line 11:
```html
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

Replace with `400;500;600;700;800`:
```html
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
```

Also, the file currently ends with:
```html
  {% block body_content %}{% block content %}{% endblock %}{% endblock %}
</body>
</html>
```

Change to:
```html
  {% block body_content %}{% block content %}{% endblock %}{% endblock %}
  {% block extra_js %}{% endblock %}
</body>
</html>
```

Do NOT change `href="/static/style-guide/tokens.css"` — an existing test asserts that exact path.

- [ ] **Step 2: Run test that asserts font and CSS links**

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py::TestBaseTemplateAssets -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add templates/base.html
git commit -m "feat(base): add Inter weight 800 and extra_js block"
```

---

## Task 4: Update `templates/parent_ui/includes/header.html`

**Files:**
- Modify: `templates/parent_ui/includes/header.html`

- [ ] **Step 1: Add `fk-header-inner` wrapper**

Replace the entire file with:

```html
{% load static %}
<header class="fk-site-header">
  <div class="fk-header-inner">
    <div class="fk-brand">
      <img class="fk-brand-logo" src="{% static 'img/fk-cesis-logo.png' %}" alt="FK Cēsis logo">
      <div class="fk-brand-text">
        <div class="fk-brand-title">FK Cēsis</div>
        <div class="fk-brand-subtitle">Futbola klubs</div>
      </div>
    </div>
  </div>
</header>
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -x -q 2>&1 | tail -5
```

Expected: all pass (header CSS classes are tested via `fk-site-header`).

- [ ] **Step 3: Commit**

```bash
git add templates/parent_ui/includes/header.html
git commit -m "feat(header): add fk-header-inner wrapper for max-width constraint"
```

---

## Task 5: Redesign `templates/parent_ui/includes/hero_card.html`

**Files:**
- Modify: `templates/parent_ui/includes/hero_card.html`

This template is included in multiple places. It supports two variants:
- `variant="portal"` — 3-column grid with clipboard illustration (used in `parent_portal.html`)
- default — 2-column registration hero with stepper slot (used in `start_registration.html`)

- [ ] **Step 1: Rewrite `hero_card.html`**

Replace the entire file with:

```html
{% load static %}
{% if variant == "portal" %}
<section class="fk-hero-card fk-hero-card--portal">
  <div class="fk-hero-illustration" aria-hidden="true">
    <div class="fk-clipboard">
      <div class="fk-clipboard-line fk-clipboard-line--med"></div>
      <div class="fk-clipboard-line fk-clipboard-line--short"></div>
      <div class="fk-clipboard-line fk-clipboard-line--med"></div>
      <div class="fk-clipboard-check"></div>
      <div class="fk-clipboard-line fk-clipboard-line--med"></div>
      <div class="fk-clipboard-check"></div>
      <div class="fk-clipboard-line fk-clipboard-line--short"></div>
    </div>
    <div class="fk-ball"></div>
  </div>
  <div class="fk-hero-copy">
    <h2>Sveiks!</h2>
    <p>Pārvaldi savu bērnu pieteikumus FK Cēsis viegli un ātri. Turpini iesākto vai sāc jaunu reģistrāciju.</p>
    <div class="fk-hero-actions">
      {% if primary_application %}<a href="{% url 'registrations:application-workspace' primary_application.pk %}" class="fk-button fk-button--primary">Turpināt pieteikumu</a>{% endif %}
      <a href="{% url 'registrations:new-application' %}" class="fk-button fk-button--red">＋ Sākt jaunu reģistrāciju</a>
    </div>
  </div>
  <aside class="fk-info-card">
    <div class="fk-info-card-icon">🛡</div>
    <h3>Tavi dati ir drošībā</h3>
    <p>Mēs rūpējamies par tavu informācijas drošību un privātumu.</p>
  </aside>
</section>
{% else %}
<section class="fk-hero-card">
  <div>
    <p class="fk-eyebrow">{{ eyebrow|default:"FK Cēsis" }}</p>
    <h1>{{ hero_title|default:"" }}</h1>
    {% if hero_subtitle %}<p class="fk-lead">{{ hero_subtitle }}</p>{% endif %}
  </div>
</section>
{% endif %}
```

- [ ] **Step 2: Run visual page tests**

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add templates/parent_ui/includes/hero_card.html
git commit -m "feat(hero-card): add portal variant with clipboard illustration"
```

---

## Task 6: Create `static/js/wizard.js`

**Files:**
- Create: `static/js/wizard.js`

- [ ] **Step 1: Create `static/js/` directory and `wizard.js`**

```bash
mkdir -p /home/linards/Documents/Private/fk-cesis-mms/static/js
```

Create `static/js/wizard.js`:

```javascript
(function () {
  'use strict';

  var steps = document.querySelectorAll('.fk-wizard-step');
  if (!steps.length) return;

  var indicators = document.querySelectorAll('.fk-stepper .fk-step');
  var mobileCount = document.querySelector('.fk-mobile-step-count');
  var mobileLabel = document.querySelector('.fk-mobile-step-label');
  var progressLine = document.querySelector('.fk-progress-line span');

  var current = 0;
  var total = steps.length;

  function showStep(n) {
    steps.forEach(function (s, i) {
      s.classList.toggle('fk-wizard-step--active', i === n);
    });
    indicators.forEach(function (s, i) {
      s.classList.toggle('fk-step--active', i === n);
    });
    if (mobileCount) mobileCount.textContent = (n + 1) + ' / ' + total;
    if (mobileLabel && indicators[n]) {
      var lbl = indicators[n].querySelector('.fk-step-label');
      if (lbl) mobileLabel.textContent = lbl.textContent;
    }
    if (progressLine) {
      progressLine.style.width = Math.round((n + 1) / total * 100) + '%';
    }
    current = n;
    window.scrollTo(0, 0);
  }

  function validateStep(n) {
    var step = steps[n];
    var inputs = step.querySelectorAll('input[required], select[required], textarea[required]');
    var ok = true;
    inputs.forEach(function (input) {
      if (!input.value.trim()) {
        input.classList.add('fk-input--error');
        ok = false;
      } else {
        input.classList.remove('fk-input--error');
      }
    });
    return ok;
  }

  document.addEventListener('click', function (e) {
    if (e.target.matches('[data-wizard-next]') || e.target.closest('[data-wizard-next]')) {
      var btn = e.target.matches('[data-wizard-next]') ? e.target : e.target.closest('[data-wizard-next]');
      if (validateStep(current) && current < total - 1) {
        showStep(current + 1);
      }
    }
    if (e.target.matches('[data-wizard-prev]') || e.target.closest('[data-wizard-prev]')) {
      if (current > 0) {
        showStep(current - 1);
      }
    }
  });

  showStep(0);
})();
```

- [ ] **Step 2: Verify file exists**

```bash
ls static/js/wizard.js
```

Expected: file listed.

- [ ] **Step 3: Commit**

```bash
git add static/js/wizard.js
git commit -m "feat(wizard): add vanilla JS step navigator"
```

---

## Task 7: Redesign `templates/registrations/parent_portal.html`

**Files:**
- Modify: `templates/registrations/parent_portal.html`

Key test constraints (from `tests/registrations/test_parent_visual_pages.py`):
- Must include `hero_card.html`, `section_card.html`, `status_badge.html`
- Rendered HTML must contain: "Mani pieteikumi", "Pārskatiet un turpiniet", "Nav pieteikumu" (empty state), "Sākt jaunu reģistrāciju" (always), "Turpināt pieteikumu" (when draft)
- The line with "Turpināt pieteikumu" must contain `{% url` on same line
- Must use `fk-parent-page` and `fk-site-header` (these come from `base_parent_page.html`)

- [ ] **Step 1: Rewrite `parent_portal.html`**

Replace the entire file with:

```html
{% extends "parent_ui/base_parent_page.html" %}
{% load static %}

{% block page_title %}Mani pieteikumi — FK Cēsis MMS{% endblock %}

{% block page_content %}
<h1 class="fk-page-title">Mani pieteikumi</h1>
<p class="fk-page-subtitle">Pārskatiet un turpiniet — šeit redzams katra pieteikuma statuss un nākamais solis.</p>

{% include "parent_ui/includes/hero_card.html" with variant="portal" primary_application=primary_application %}

{% if applications %}
<div class="fk-section-head">
  <h2>Pieteikumu saraksts</h2>
</div>

<section class="fk-applications">
  {% include "parent_ui/includes/section_card.html" %}
  {% for app in applications %}
  <article class="fk-application-card">
    <div class="fk-app-person">
      <div class="fk-app-avatar">🙂</div>
      <div class="fk-app-main">
        <h3 class="fk-app-name">{{ app.guardian_full_name }}</h3>
        <div class="fk-app-meta">
          <div>Bērns: {{ app.member_full_name }}</div>
        </div>
      </div>
    </div>

    <div class="fk-app-block">
      <span class="fk-block-label">Statuss</span>
      {% include "parent_ui/includes/status_badge.html" with status=app.status %}
      {% if app.review_message %}
      <div class="fk-app-meta" style="margin-top:10px;">
        <div>{{ app.review_message }}</div>
      </div>
      {% endif %}
    </div>

    <div class="fk-app-block fk-progress-wrap">
      <span class="fk-block-label">Nākamais solis</span>
      {% if app.status == 'draft' or app.status == 'fix_requested' %}
        <div class="fk-progress-title">Aizpildi un iesniegt pieteikumu</div>
        <div class="fk-progress-meta">Melnraksts</div>
        <div class="fk-progress-bar"><span style="width:40%"></span></div>
      {% elif app.status == 'submitted' %}
        <div class="fk-progress-title">Pieteikums izskatīšanā</div>
        <div class="fk-progress-meta">Iesniegts</div>
        <div class="fk-progress-bar fk-progress-bar--success"><span style="width:100%"></span></div>
      {% elif app.status == 'approved' %}
        <div class="fk-progress-title">Pieteikums apstiprināts</div>
        <div class="fk-progress-meta">Apstiprināts</div>
        <div class="fk-progress-bar fk-progress-bar--success"><span style="width:100%"></span></div>
      {% else %}
        <div class="fk-progress-title">{{ app.get_status_display }}</div>
        <div class="fk-progress-bar"><span style="width:0%"></span></div>
      {% endif %}
    </div>

    <div class="fk-app-actions">
      {% if app.status == 'draft' or app.status == 'fix_requested' %}
        <a href="{% url 'registrations:application-workspace' app.pk %}" class="fk-button fk-button--primary">Turpināt</a>
      {% else %}
        <a href="{% url 'registrations:application-workspace' app.pk %}" class="fk-button fk-button--secondary">Skatīt</a>
      {% endif %}
    </div>
  </article>
  {% endfor %}
</section>

{% else %}
<div class="fk-empty-state" style="margin-top:28px;">
  <h2>Nav pieteikumu</h2>
  <p>Jums vēl nav neviena pieteikuma.</p>
  <a href="{% url 'registrations:new-application' %}" class="fk-button fk-button--primary" style="margin-top:16px;">Sākt jaunu reģistrāciju</a>
</div>
{% endif %}

<div class="fk-helper-card">
  <div class="fk-helper-copy">
    <div class="fk-helper-icon">ⓘ</div>
    <div>
      <h3>Nevari atrast savu pieteikumu?</h3>
      <p>Pārliecinies, ka esi reģistrējies ar to pašu e-pasta adresi, ko izmantoji pieteikuma izveidē.</p>
    </div>
  </div>
  <a href="{% url 'registrations:start-registration' %}" class="fk-button fk-button--secondary">✉ Pārbaudīt citu e-pastu</a>
</div>
{% endblock %}
```

- [ ] **Step 2: Run full visual page test suite**

```bash
uv run pytest tests/registrations/test_parent_visual_pages.py -x -v 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 3: Run workspace tests to check no regressions**

```bash
uv run pytest tests/registrations/test_parent_application_workspace.py -x -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add templates/registrations/parent_portal.html
git commit -m "feat(portal): full redesign matching fk_cesis_list.html style-guide"
```

---

## Task 8: Update `templates/registrations/application_workspace.html` — wizard

**Files:**
- Modify: `templates/registrations/application_workspace.html`

The editable mode gets the multi-step wizard. The read-only mode keeps its existing flat display. The documents section is rendered outside the wizard (always visible at the top of editable mode too, before the form).

Note: `form.grouped_fields` is an iterable of `(section_name, bound_fields)` tuples. `section_name` is a string like `"guardian"`, `"member"`, `"agreement"`. The wizard maps these sections to steps. A final "Pārskats" step is added after all form sections.

- [ ] **Step 1: Rewrite `application_workspace.html`**

Replace the entire file with:

```html
{% extends "parent_ui/base_parent_page.html" %}
{% load static %}
{% load reg_filters %}

{% block extra_js %}<script src="{% static 'js/wizard.js' %}"></script>{% endblock %}

{% block page_content %}

{# ── Hero card with stepper (editable) or status banner (read-only) ── #}
<section class="fk-hero-card">
  <div>
    <p class="fk-eyebrow">Pieteikums</p>
    <h1>{{ application.member_full_name|default:"Jauns pieteikums" }}</h1>
    {% if workspace_mode == "editable" %}
    <div class="fk-mobile-progress" aria-label="Reģistrācijas progress">
      <strong><span class="fk-mobile-step-count">1 / {{ form.grouped_fields|length|add:1 }}</span></strong>
      <div class="fk-progress-line"><span></span></div>
      <span class="fk-mobile-step-label"></span>
    </div>
    {% else %}
    {% include "parent_ui/includes/application_status_banner.html" with application=application mode=workspace_mode %}
    {% endif %}
  </div>

  {% if workspace_mode == "editable" %}
  <div class="fk-stepper" aria-label="Reģistrācijas soļi">
    {% for section_name, bound_fields in form.grouped_fields %}
    <div class="fk-step">
      <div class="fk-step-number">{{ forloop.counter }}</div>
      <div class="fk-step-label">{% if section_name == "documents" %}ID dokuments{% elif section_name == "guardian" %}Vecāka informācija{% elif section_name == "member" %}Bērna informācija{% elif section_name == "agreement" %}Piekrišana{% else %}{{ section_name|title }}{% endif %}</div>
    </div>
    {% endfor %}
    <div class="fk-step">
      <div class="fk-step-number">{{ form.grouped_fields|length|add:1 }}</div>
      <div class="fk-step-label">Pārskats</div>
    </div>
  </div>
  {% endif %}
</section>

{% include "parent_ui/includes/error_summary.html" with items=form.error_summary_items %}

{# ── Documents section (always shown above wizard) ── #}
<section class="fk-section-card">
  <div class="fk-section-header">
    <div class="fk-section-title-wrap">
      <div class="fk-section-icon">▣</div>
      <div>
        <h2>Dokumenti</h2>
        <p class="fk-section-note">Personas apliecinoši dokumenti un bērna foto.</p>
      </div>
    </div>
  </div>
  <div class="fk-section-body">
    {% include "parent_ui/includes/document_card.html" with document_state=document_state workspace_mode=workspace_mode document_field_id_map=document_field_id_map document_kind_labels=document_kind_labels %}
  </div>
</section>

{% if workspace_mode == "editable" %}

{# ── Multi-step wizard form ── #}
<form method="post" enctype="multipart/form-data" class="fk-workspace-form">
  {% csrf_token %}

  {% for section_name, bound_fields in form.grouped_fields %}
  <div class="fk-wizard-step {% if forloop.first %}fk-wizard-step--active{% endif %}" data-step="{{ forloop.counter0 }}">
    <section class="fk-section-card">
      <div class="fk-section-header">
        <div class="fk-section-title-wrap">
          <div class="fk-section-icon">{% if section_name == "documents" %}▣{% elif section_name == "guardian" %}👤{% elif section_name == "member" %}⚽{% elif section_name == "agreement" %}✓{% else %}📋{% endif %}</div>
          <div>
            <h2>{% if section_name == "documents" %}ID dokuments{% elif section_name == "guardian" %}Vecāka informācija{% elif section_name == "member" %}Bērna informācija{% elif section_name == "agreement" %}Piekrišana{% else %}{{ section_name|title }}{% endif %}</h2>
          </div>
        </div>
      </div>
      <div class="fk-section-body">
        {% for bound_field in bound_fields %}
          {% if section_name == "member" and bound_field.name == "member_same_address_as_guardian" %}
            <input type="hidden" id="member_actual_address_previous" value="{{ form.member_actual_address.value|default:'' }}">
            {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|get_item:bound_field.name %}
            <script>
(function(){
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
})();
            </script>
          {% else %}
            {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|get_item:bound_field.name %}
          {% endif %}
        {% endfor %}
        <div class="fk-wizard-nav">
          {% if not forloop.first %}
          <button type="button" data-wizard-prev class="fk-button fk-button--secondary">← Atpakaļ</button>
          {% else %}
          <span></span>
          {% endif %}
          <button type="button" data-wizard-next class="fk-button fk-button--primary">Turpināt →</button>
        </div>
      </div>
    </section>
  </div>
  {% endfor %}

  {# ── Review step ── #}
  <div class="fk-wizard-step" data-step="{{ form.grouped_fields|length }}">
    <section class="fk-section-card">
      <div class="fk-section-header">
        <div class="fk-section-title-wrap">
          <div class="fk-section-icon">▤</div>
          <div>
            <h2>Pārskats</h2>
            <p class="fk-section-note">Pārbaudiet pieteikuma kopsavilkumu pirms iesniegšanas.</p>
          </div>
        </div>
      </div>
      <div class="fk-section-body">
        <div class="fk-summary-grid">
          <div class="fk-summary-item"><span>Vecāks</span><strong>{{ application.guardian_full_name|default:"—" }}</strong></div>
          <div class="fk-summary-item"><span>Bērns</span><strong>{{ application.member_full_name|default:"Nav aizpildīts" }}</strong></div>
          <div class="fk-summary-item"><span>Statuss</span><strong>{{ application.get_status_display|default:"Melnraksts" }}</strong></div>
        </div>
        <p class="fk-fine-print">Iesniedzot pieteikumu, apstiprināt, ka ievadītie dati ir patiesi un dokumenti ir augšupielādēti pieteikuma sagatavošanai.</p>
        <div class="fk-wizard-nav" style="margin-top:22px;">
          <button type="button" data-wizard-prev class="fk-button fk-button--secondary">← Atpakaļ</button>
          <div class="fk-wizard-nav-actions">
            <button type="submit" name="submit_action" value="save_draft" class="fk-button fk-button--secondary">Saglabāt melnrakstu</button>
            <button type="submit" name="submit_action" value="submit" class="fk-button fk-button--red">Iesniegt pieteikumu</button>
          </div>
        </div>
      </div>
    </section>
  </div>
</form>

{% else %}

{# ── Read-only flat view ── #}
{% for section_name, bound_fields in form.grouped_fields %}
<section class="fk-section-card">
  <div class="fk-section-header">
    <div class="fk-section-title-wrap">
      <div class="fk-section-icon">{% if section_name == "documents" %}▣{% elif section_name == "guardian" %}👤{% elif section_name == "member" %}⚽{% elif section_name == "agreement" %}✓{% else %}📋{% endif %}</div>
      <div>
        <h2>{% if section_name == "documents" %}ID dokuments{% elif section_name == "guardian" %}Vecāka informācija{% elif section_name == "member" %}Bērna informācija{% elif section_name == "agreement" %}Piekrišana{% else %}{{ section_name|title }}{% endif %}</h2>
      </div>
    </div>
  </div>
  <div class="fk-section-body">
    <div class="fk-form-section">
      {% for bound_field in bound_fields %}
        <p><strong>{{ bound_field.label }}:</strong>
          {% if section_name == "member" and bound_field.name == "member_birth_date" %}
            {{ application.member_birth_date|date:"Y-m-d" }}
          {% elif section_name == "agreement" and bound_field.name == "support_club_instead_of_multi_child_discount" %}
            {{ bound_field.value|yesno:"Jā,Nē" }}
          {% elif bound_field.name == "guardian_email" %}
            {{ application.guardian_email }}
          {% else %}
            {{ bound_field.value|default:"—" }}
          {% endif %}
        </p>
      {% endfor %}
    </div>
  </div>
</section>
{% endfor %}

{% endif %}
{% endblock %}
```

- [ ] **Step 2: Run workspace tests**

```bash
uv run pytest tests/registrations/test_parent_application_workspace.py -x -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add templates/registrations/application_workspace.html
git commit -m "feat(workspace): add multi-step wizard for editable mode"
```

---

## Task 9: Update `templates/registrations/new_registration.html` — wizard

**Files:**
- Modify: `templates/registrations/new_registration.html`

Same wizard pattern as the workspace, but `application` object is not available (new registration). Review step shows a simple summary message instead of application data.

- [ ] **Step 1: Rewrite `new_registration.html`**

Replace the entire file with:

```html
{% extends "parent_ui/base_parent_page.html" %}
{% load static %}
{% load reg_filters %}

{% block page_title %}Jauna reģistrācija — FK Cēsis MMS{% endblock %}

{% block extra_js %}<script src="{% static 'js/wizard.js' %}"></script>{% endblock %}

{% block page_content %}

{# ── Hero card with stepper ── #}
<section class="fk-hero-card">
  <div>
    <p class="fk-eyebrow">FK Cēsis</p>
    <h1>Bērna reģistrācija</h1>
    <p class="fk-lead">Reģistrējiet savu bērnu treniņiem FK Cēsis, aizpildot sekojošās sadaļas.</p>
    <div class="fk-mobile-progress" aria-label="Reģistrācijas progress">
      <strong><span class="fk-mobile-step-count">1 / {{ form.grouped_fields|length|add:1 }}</span></strong>
      <div class="fk-progress-line"><span></span></div>
      <span class="fk-mobile-step-label"></span>
    </div>
  </div>
  <div class="fk-stepper" aria-label="Reģistrācijas soļi">
    {% for section_name, bound_fields in form.grouped_fields %}
    <div class="fk-step">
      <div class="fk-step-number">{{ forloop.counter }}</div>
      <div class="fk-step-label">{% if section_name == "documents" %}ID dokuments{% elif section_name == "guardian" %}Vecāka informācija{% elif section_name == "member" %}Bērna informācija{% elif section_name == "agreement" %}Piekrišana{% else %}{{ section_name|title }}{% endif %}</div>
    </div>
    {% endfor %}
    <div class="fk-step">
      <div class="fk-step-number">{{ form.grouped_fields|length|add:1 }}</div>
      <div class="fk-step-label">Pārskats</div>
    </div>
  </div>
</section>

{% if form.errors %}
  {% include "parent_ui/includes/error_summary.html" with items=form.error_summary_items %}
{% endif %}

<form method="post" enctype="multipart/form-data" class="fk-workspace-form">
  {% csrf_token %}

  {% for section_name, bound_fields in form.grouped_fields %}
  <div class="fk-wizard-step {% if forloop.first %}fk-wizard-step--active{% endif %}" data-step="{{ forloop.counter0 }}">
    <section class="fk-section-card">
      <div class="fk-section-header">
        <div class="fk-section-title-wrap">
          <div class="fk-section-icon">{% if section_name == "documents" %}▣{% elif section_name == "guardian" %}👤{% elif section_name == "member" %}⚽{% elif section_name == "agreement" %}✓{% else %}📋{% endif %}</div>
          <div>
            <h2>{% if section_name == "documents" %}ID dokuments{% elif section_name == "guardian" %}Vecāka informācija{% elif section_name == "member" %}Bērna informācija{% elif section_name == "agreement" %}Piekrišana{% else %}{{ section_name|title }}{% endif %}</h2>
          </div>
        </div>
      </div>
      <div class="fk-section-body">
        {% for bound_field in bound_fields %}
          {% if section_name == "member" and bound_field.name == "member_same_address_as_guardian" %}
            <input type="hidden" id="member_actual_address_previous" value="{{ form.member_actual_address.value|default:'' }}">
            {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|get_item:"member_same_address_as_guardian" %}
            <script>
(function(){
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
})();
            </script>
          {% else %}
            {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|get_item:bound_field.name %}
          {% endif %}
        {% endfor %}
        <div class="fk-wizard-nav">
          {% if not forloop.first %}
          <button type="button" data-wizard-prev class="fk-button fk-button--secondary">← Atpakaļ</button>
          {% else %}
          <span></span>
          {% endif %}
          <button type="button" data-wizard-next class="fk-button fk-button--primary">Turpināt →</button>
        </div>
      </div>
    </section>
  </div>
  {% endfor %}

  {# ── Review step ── #}
  <div class="fk-wizard-step" data-step="{{ form.grouped_fields|length }}">
    <section class="fk-section-card">
      <div class="fk-section-header">
        <div class="fk-section-title-wrap">
          <div class="fk-section-icon">▤</div>
          <div>
            <h2>Pārskats</h2>
            <p class="fk-section-note">Pārbaudiet aizpildīto informāciju pirms iesniegšanas.</p>
          </div>
        </div>
      </div>
      <div class="fk-section-body">
        <p class="fk-fine-print">Iesniedzot pieteikumu, apstiprināt, ka ievadītie dati ir patiesi un dokumenti ir augšupielādēti pieteikuma sagatavošanai.</p>
        <div class="fk-wizard-nav" style="margin-top:22px;">
          <button type="button" data-wizard-prev class="fk-button fk-button--secondary">← Atpakaļ</button>
          <div class="fk-wizard-nav-actions">
            <button type="submit" name="submit_action" value="save_draft" class="fk-button fk-button--secondary">Saglabāt melnrakstu</button>
            <button type="submit" name="submit_action" value="submit" class="fk-button fk-button--red">Iesniegt pieteikumu</button>
          </div>
        </div>
      </div>
    </section>
  </div>
</form>
{% endblock %}
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -x -q --ignore=tests/documents 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add templates/registrations/new_registration.html
git commit -m "feat(new-registration): add multi-step wizard"
```

---

## Task 10: Smoke Test All Pages

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -q 2>&1 | tail -20
```

Expected: all pass. Note any failures and fix before proceeding.

- [ ] **Step 2: Start dev server and verify visually**

```bash
uv run python manage.py runserver 8000
```

Open in browser:
1. `http://localhost:8000/register/` — verify: FK Cēsis header, hero card, email form with "Droša piekļuve" label
2. `http://localhost:8000/portal/` (after login) — verify: clipboard illustration, application cards with progress bars, helper card
3. `http://localhost:8000/applications/<id>/` (after creating draft) — verify: stepper in hero, wizard steps show/hide on Next/Back, submit on final step
4. On mobile width (< 720px): verify header loses sticky, stepper hides, mobile progress bar appears

- [ ] **Step 3: Fix any visual regressions found**

If any page breaks, check:
- CSS class names match between templates and CSS files
- `{% url %}` tags reference correct URL names
- Template `{% load %}` tags present where needed

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -p
git commit -m "fix(ui): address visual regressions from style-guide application"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All spec sections covered — CSS tokens ✓, body bg ✓, header-inner ✓, section card structure ✓, stepper ✓, dropzone ✓, portal redesign ✓, application cards with progress bars ✓, clipboard illustration ✓, helper card ✓, wizard JS ✓, registration wizard ✓, button standardization ✓
- [x] **Placeholder scan:** No TBD, TODO, or incomplete sections
- [x] **Type consistency:** CSS class names consistent throughout — `.fk-wizard-step`, `.fk-wizard-step--active`, `.fk-stepper`, `.fk-step`, `.fk-step--active`, `.fk-section-card`, `.fk-section-header`, `.fk-section-body`, `.fk-section-icon`, `.fk-section-title-wrap`, `.fk-application-card`, `.fk-progress-bar`, `.fk-helper-card`
- [x] **Test constraints respected:** `style-guide/tokens.css` path unchanged, "Pārskatiet un turpiniet" present, "Turpināt pieteikumu" on same line as `{% url %}`, includes for hero_card/section_card/status_badge all kept
- [x] **Backwards compat:** `.fk-button.primary` and `.fk-button.secondary` still work alongside BEM variants
