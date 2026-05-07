# Registration Visual System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved FK Cēsis visual system and redesign the parent registration flow so the live registration experience matches the new canonical style guide while preserving the working draft/submit workflow.

**Architecture:** Keep the app server-rendered. Introduce a small shared design-token layer sourced from `style-guide/`, then rebuild parent-facing templates around reusable layout primitives instead of page-specific one-off markup. Preserve current registration domain behavior and magic-link flow; change presentation and form flow structure only where explicitly approved by the design spec.

**Tech Stack:** Django templates, Django forms, existing `apps/accounts` and `apps/registrations` views, project static CSS, pytest + pytest-django, Ruff, mypy.

---

## 1. Scope and sequencing

This plan covers only the **build-now** slice from `docs/superpowers/specs/2026-05-05-registration-design-and-integrations-design.md`:

1. shared visual tokens and parent/admin shell primitives
2. parent-facing registration entry and edit flow redesign
3. parent portal/status page redesign
4. supporting template/CSS cleanup and tests

It does **not** implement:
- OCR vendor research or integration
- agreement generation/signing
- SMTP provider migration
- admin review/business workflow changes beyond safe shell groundwork

Sequence rule:
- implement visual foundation first
- then parent entry/status pages
- then registration form structure
- then polish and verification

---

## 2. File-by-file architecture plan

### Create
- `docs/superpowers/plans/2026-05-05-registration-visual-system-implementation.md`
  - dedicated execution plan for this redesign
- `static/css/tokens.css`
  - CSS variables mirrored from `style-guide/tokens.css` for runtime use in templates
- `static/css/parent.css`
  - parent-facing layout, cards, stepper, form, upload, and status styles
- `static/css/admin_shell.css`
  - minimal admin shell token usage and logo placement groundwork only
- `templates/includes/site_logo.html`
  - canonical logo include supporting hero and compact variants
- `templates/includes/parent_shell.html`
  - reusable parent wrapper with centered card layout and optional hero logo
- `templates/includes/form_field.html`
  - reusable field partial with label, help text, error text, and consistent spacing
- `tests/registrations/test_parent_visual_pages.py`
  - response/content tests for redesigned parent pages

### Modify
- `templates/base.html`
  - load new CSS files and establish top-level blocks for shell/body classes
- `templates/registrations/start_registration.html`
  - redesign entry page to use hero logo and calmer call-to-action layout
- `templates/registrations/edit_registration.html`
  - redesign edit flow, likely multi-section or progressive single-page structure
- `templates/registrations/parent_portal.html`
  - redesign parent status/portal page to match new system
- `apps/registrations/forms.py`
  - add form-level widget classes, grouping helpers, and section metadata if needed
- `apps/registrations/views.py`
  - only if needed to pass shell/form section context; no business-rule changes without tests
- `apps/accounts/views.py`
  - apply parent-shell styling to magic-link request/verify pages if those templates exist or are introduced
- `README.md`
  - note canonical style-guide source and where runtime tokens live if visual implementation changes developer workflow
- `AGENTS.md`
  - keep status accurate if new reusable UI structure changes implementation notes

### Optional modify only if needed after inspection
- `fk_cesis_mms/urls.py`
  - only if template route naming cleanup is required
- `templates/registrations/*.html` additional partials
  - only if form sections become easier to maintain as includes

---

## 3. Design decisions for implementation

### 3.1 Canonical token mirroring
**Why:** `style-guide/` is source of truth, but runtime templates need app-served CSS. Mirror the canonical tokens into `static/css/tokens.css` and keep names FK Cēsis-specific to avoid drift.

### 3.2 Server-rendered component partials over frontend framework
**Why:** Current app already works server-rendered. Reusable Django partials give consistency without adding JS framework complexity.

### 3.3 Parent-first redesign, admin-shell groundwork only
**Why:** Confirmed build-now work is registration-centered. Admin review functionality is not implemented yet, so only add minimal shell conventions needed to keep future work aligned.

### 3.4 Preserve domain workflow semantics
**Why:** Registration draft/submit behavior already works and is tested. Visual redesign should not silently rewrite business behavior.

### 3.5 Style-guide beats design-template
**Why:** `design-template.html` is exploratory. Implementation must treat `style-guide/FK Cesis.pdf`, `style-guide/background-1.jpeg`, `style-guide/tokens.md`, and `style-guide/tokens.css` as canonical.

---

## 4. Test strategy

### Framework
- `pytest` + `pytest-django`
- existing client/integration-style registration tests remain primary regression coverage
- add lightweight page assertions for CSS hooks, headings, and shell content

### What to test
- parent entry page renders hero logo container and primary call to action
- edit page still shows save-draft and submit actions
- form errors still render visibly on invalid submit
- parent portal still shows application statuses after redesign
- existing workflow tests continue to pass unchanged or with minimal assertion updates

### What not to test
- exact pixel values
- exact CSS declarations
- browser rendering quirks
- PDF/image assets themselves

### Test file structure
- existing: `tests/registrations/test_application_workflow.py`
- existing: `tests/registrations/test_parent_edit_permissions.py`
- new: `tests/registrations/test_parent_visual_pages.py`

---

## 5. Acceptance criteria by unit

### Unit A — Tokens and shared shells
- runtime CSS loads canonical FK Cēsis tokens derived from `style-guide/`
- parent shell supports hero-logo layout and centered content
- logo include can render hero and compact variants

### Unit B — Registration entry and portal redesign
- `/register/` presents branded calm entry page with centered layout
- parent portal/status page matches same visual system
- no login requirement regression on entry page

### Unit C — Registration form redesign
- edit page uses approved visual system
- parent can still save draft and submit
- form remains understandable on mobile-width layout
- document upload remains inline in redesigned page

### Unit D — Verification and docs
- targeted visual-page tests pass
- existing registration workflow tests still pass
- `uv run pytest -q && uv run ruff check . && uv run mypy .` pass before completion
- docs mention canonical `style-guide/` source where relevant

---

## 6. Implementation tasks

### Task 1: Add runtime design tokens and shared template primitives

**Files:**
- Create: `static/css/tokens.css`
- Create: `templates/includes/site_logo.html`
- Create: `templates/includes/parent_shell.html`
- Modify: `templates/base.html`
- Test: `tests/registrations/test_parent_visual_pages.py`

- [ ] **Step 1: Write failing page-shell tests**

```python
from django.urls import reverse


def test_register_page_uses_parent_shell(client):
    response = client.get(reverse("registrations:start"))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'fk-parent-shell' in content
    assert 'fk-logo--hero' in content


def test_register_page_loads_canonical_tokens(client):
    response = client.get(reverse("registrations:start"))

    content = response.content.decode()
    assert '/static/css/tokens.css' in content
    assert '/static/css/parent.css' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py -v`
Expected: FAIL because shell classes and stylesheet references do not exist yet.

- [ ] **Step 3: Add runtime token file**

```css
/* static/css/tokens.css */
:root {
  --fk-font-display: "Anton", Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
  --fk-color-blue: #0f0851;
  --fk-color-red: #ce1c20;
  --fk-color-surface: #ffffff;
  --fk-color-bg: #f6f4f1;
  --fk-color-ink: #161616;
  --fk-color-muted: #5e6173;
  --fk-radius-card: 24px;
  --fk-shadow-soft: 0 16px 40px rgba(15, 8, 81, 0.12);
}
```

- [ ] **Step 4: Add shared logo and parent shell partials**

```django
{# templates/includes/site_logo.html #}
{% if variant == "hero" %}
  <div class="fk-logo fk-logo--hero">
    <img src="{% static 'img/fk-cesis-logo.png' %}" alt="FK Cēsis">
  </div>
{% else %}
  <div class="fk-logo fk-logo--compact">
    <img src="{% static 'img/fk-cesis-logo.png' %}" alt="FK Cēsis">
  </div>
{% endif %}
```

```django
{# templates/includes/parent_shell.html #}
<div class="fk-parent-shell {% block parent_shell_modifiers %}{% endblock %}">
  <div class="fk-parent-shell__inner">
    {% block parent_shell_header %}{% endblock %}
    <div class="fk-parent-shell__body">
      {% block parent_shell_content %}{% endblock %}
    </div>
  </div>
</div>
```

- [ ] **Step 5: Load the new stylesheets in base template**

```django
<link rel="stylesheet" href="{% static 'css/tokens.css' %}">
<link rel="stylesheet" href="{% static 'css/parent.css' %}">
<link rel="stylesheet" href="{% static 'css/admin_shell.css' %}">
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py -v`
Expected: PASS for shell/token assertions.

### Task 2: Build parent-facing CSS system

**Files:**
- Create: `static/css/parent.css`
- Create: `static/css/admin_shell.css`
- Modify: `templates/base.html`
- Test: `tests/registrations/test_parent_visual_pages.py`

- [ ] **Step 1: Write failing test for parent CTA structure**

```python
def test_register_page_has_primary_and_secondary_actions(client):
    response = client.get(reverse("registrations:start"))

    content = response.content.decode()
    assert 'fk-button fk-button--primary' in content
    assert 'fk-button fk-button--secondary' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_register_page_has_primary_and_secondary_actions -v`
Expected: FAIL because button classes do not exist yet.

- [ ] **Step 3: Add parent CSS primitives**

```css
/* static/css/parent.css */
.fk-parent-shell {
  min-height: 100vh;
  background: var(--fk-color-bg);
  color: var(--fk-color-ink);
}

.fk-parent-shell__inner {
  width: min(100%, 760px);
  margin: 0 auto;
  padding: 32px 20px 48px;
}

.fk-card {
  background: var(--fk-color-surface);
  border-radius: var(--fk-radius-card);
  box-shadow: var(--fk-shadow-soft);
  padding: 24px;
}

.fk-button--primary {
  background: var(--fk-color-blue);
  color: #fff;
}

.fk-button--secondary {
  background: transparent;
  color: var(--fk-color-blue);
  border: 1px solid var(--fk-color-blue);
}
```

- [ ] **Step 4: Add minimal admin shell groundwork**

```css
/* static/css/admin_shell.css */
.fk-admin-shell__logo {
  max-width: 48px;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_register_page_has_primary_and_secondary_actions -v`
Expected: PASS.

### Task 3: Redesign registration entry page

**Files:**
- Modify: `templates/registrations/start_registration.html`
- Test: `tests/registrations/test_parent_visual_pages.py`

- [ ] **Step 1: Write failing test for hero-style entry content**

```python
def test_register_page_shows_brand_heading_and_help_text(client):
    response = client.get(reverse("registrations:start"))

    content = response.content.decode()
    assert 'FK Cēsis' in content
    assert 'Bērna reģistrācija' in content
    assert 'Saglabāt melnrakstu vēlāk' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_register_page_shows_brand_heading_and_help_text -v`
Expected: FAIL on missing approved copy/classes.

- [ ] **Step 3: Replace entry-page markup with parent shell + hero content**

```django
{% extends "base.html" %}
{% load static %}

{% block content %}
<div class="fk-parent-shell">
  <div class="fk-parent-shell__inner">
    <section class="fk-card fk-hero-card">
      {% include "includes/site_logo.html" with variant="hero" %}
      <p class="fk-eyebrow">FK Cēsis</p>
      <h1>Bērna reģistrācija</h1>
      <p>Ātrs un skaidrs ceļš līdz pieteikuma iesniegšanai.</p>
      <div class="fk-action-row">
        <a class="fk-button fk-button--primary" href="{{ start_url }}">Sākt pieteikumu</a>
        <p class="fk-help-copy">Saglabāt melnrakstu vēlāk varēs pēc pirmās saglabāšanas.</p>
      </div>
    </section>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_register_page_shows_brand_heading_and_help_text -v`
Expected: PASS.

### Task 4: Redesign parent portal/status page

**Files:**
- Modify: `templates/registrations/parent_portal.html`
- Test: `tests/registrations/test_parent_visual_pages.py`

- [ ] **Step 1: Write failing portal-page test**

```python
def test_parent_portal_uses_status_cards(authenticated_parent_client, application):
    response = authenticated_parent_client.get(reverse("registrations:parent_portal"))

    content = response.content.decode()
    assert 'fk-status-card' in content
    assert application.child_full_name in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_parent_portal_uses_status_cards -v`
Expected: FAIL because redesigned status-card markup is absent.

- [ ] **Step 3: Add calm portal layout with status cards**

```django
<section class="fk-card fk-portal-summary">
  <h1>Mani pieteikumi</h1>
  <p>Šeit redzams katra pieteikuma statuss un nākamais solis.</p>
</section>

{% for application in applications %}
  <article class="fk-status-card">
    <h2>{{ application.child_full_name }}</h2>
    <p>{{ application.get_status_display }}</p>
    {% if application.is_editable_by_parent %}
      <a class="fk-button fk-button--secondary" href="{% url 'registrations:edit' application.pk %}">Turpināt</a>
    {% endif %}
  </article>
{% endfor %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_parent_portal_uses_status_cards -v`
Expected: PASS.

### Task 5: Introduce reusable form-field rendering and restructure edit page

**Files:**
- Create: `templates/includes/form_field.html`
- Modify: `apps/registrations/forms.py`
- Modify: `templates/registrations/edit_registration.html`
- Test: `tests/registrations/test_application_workflow.py`
- Test: `tests/registrations/test_parent_visual_pages.py`

- [ ] **Step 1: Write failing test for grouped form sections and actions**

```python
def test_edit_page_shows_grouped_sections_and_both_actions(parent_owned_draft_client, draft_application):
    response = parent_owned_draft_client.get(reverse("registrations:edit", args=[draft_application.pk]))

    content = response.content.decode()
    assert 'Vecāka informācija' in content
    assert 'Bērna informācija' in content
    assert 'Dokuments' in content
    assert 'Saglabāt melnrakstu' in content
    assert 'Iesniegt pieteikumu' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py::test_edit_page_shows_grouped_sections_and_both_actions -v`
Expected: FAIL because current layout does not provide the new section structure.

- [ ] **Step 3: Add reusable field partial**

```django
<div class="fk-field {% if field.errors %}fk-field--error{% endif %}">
  <label for="{{ field.id_for_label }}">{{ field.label }}</label>
  {{ field }}
  {% if field.help_text %}<p class="fk-help">{{ field.help_text }}</p>{% endif %}
  {% for error in field.errors %}<p class="fk-error">{{ error }}</p>{% endfor %}
</div>
```

- [ ] **Step 4: Add form widget classes/group metadata in form class**

```python
for field in self.fields.values():
    existing = field.widget.attrs.get("class", "")
    field.widget.attrs["class"] = f"{existing} fk-input".strip()
```

- [ ] **Step 5: Rebuild edit page around approved section layout**

```django
<section class="fk-card">
  <h1>Pieteikuma aizpildīšana</h1>
  <div class="fk-stepper">...</div>
  <form method="post" enctype="multipart/form-data">
    {% csrf_token %}
    <section><h2>Vecāka informācija</h2>...</section>
    <section><h2>Bērna informācija</h2>...</section>
    <section><h2>Dokuments</h2>...</section>
    <div class="fk-action-row">
      <button name="action" value="save_draft">Saglabāt melnrakstu</button>
      <button name="action" value="submit">Iesniegt pieteikumu</button>
    </div>
  </form>
</section>
```

- [ ] **Step 6: Run tests to verify workflow still passes**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py -v`
Expected: PASS.

### Task 6: Improve invalid-submit error presentation without changing validation rules

**Files:**
- Modify: `templates/registrations/edit_registration.html`
- Modify: `static/css/parent.css`
- Test: `tests/registrations/test_application_workflow.py`

- [ ] **Step 1: Write failing invalid-submit test**

```python
def test_invalid_submit_shows_error_summary(client, draft_application):
    response = client.post(
        reverse("registrations:edit", args=[draft_application.pk]),
        {"action": "submit"},
    )

    content = response.content.decode()
    assert 'Lūdzu pārbaudiet laukus zemāk' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_application_workflow.py::test_invalid_submit_shows_error_summary -v`
Expected: FAIL because summary message is not present.

- [ ] **Step 3: Add top-level error summary block**

```django
{% if form.errors %}
  <div class="fk-alert fk-alert--error">
    <h2>Lūdzu pārbaudiet laukus zemāk</h2>
  </div>
{% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_application_workflow.py::test_invalid_submit_shows_error_summary -v`
Expected: PASS.

### Task 7: Document canonical visual workflow and run full verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` (only if implementation details changed)
- Test: full suite and static checks

- [ ] **Step 1: Update README visual-source note**

```md
## Visual style source

Runtime styling follows the canonical assets in `style-guide/`.
If `design-template.html` differs from `style-guide/`, treat the style-guide directory as the source of truth.
```

- [ ] **Step 2: Run targeted redesign tests**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py -q`
Expected: all pass.

- [ ] **Step 3: Run full project verification**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all pass.

- [ ] **Step 4: Commit redesign work**

```bash
git add static/css/tokens.css static/css/parent.css static/css/admin_shell.css templates/base.html templates/includes/site_logo.html templates/includes/parent_shell.html templates/includes/form_field.html templates/registrations/start_registration.html templates/registrations/edit_registration.html templates/registrations/parent_portal.html apps/registrations/forms.py apps/registrations/views.py tests/registrations/test_parent_visual_pages.py tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py README.md AGENTS.md
git commit -m "feat(registrations): redesign parent registration UI"
```

---

## 7. Self-review checklist

### Spec coverage
- visual tokens/source of truth covered: Tasks 1, 2, 7
- parent entry hero/logo layout covered: Task 3
- parent portal redesign covered: Task 4
- registration form redesign with major flow-safe structure changes covered: Task 5
- inline error clarity covered: Task 6
- documentation alignment covered: Task 7

### Placeholder scan
- no TBD/TODO placeholders remain in execution steps
- all changed files have explicit paths
- every verification step includes exact commands

### Type/behavior consistency
- form actions remain `save_draft` and `submit`
- registration routes remain under `registrations:*`
- `style-guide/` remains canonical over `design-template.html`

---

## 8. Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-05-registration-visual-system-implementation.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
