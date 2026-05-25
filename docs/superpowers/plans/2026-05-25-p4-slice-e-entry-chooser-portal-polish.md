# P4 Slice E — Entry/Chooser/Portal Polish + Latvian Copy Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close P4 by polishing `/register/`, `/register/verify/`, and `/portal/` for mobile-first visual cohesion with the workspace, switching the portal onto the shared `empty_state.html` primitive, and adding a regression test that proves zero English-token leakage on parent surfaces.

**Architecture:** Surface-by-surface, narrow-viewport-first. Each surface gets its own TDD cycle. The Latvian copy contract test is added first so it drives audit fixes; the empty-state partial is extended before the portal switches to it. Only template + CSS + tests change — no view logic, no models, no migrations.

**Tech Stack:** Django 5 templates, Python 3.13 + pytest + pytest-django, vanilla CSS (`static/css/parent_theme.css`).

---

## Spec

Authoritative spec at `docs/superpowers/specs/2026-05-25-p4-slice-e-entry-chooser-portal-polish-design.md`. Re-read it if any task is ambiguous.

## Branching

Per project policy (`MEMORY.md` → worktree policy 2026-05-23): develop on `main`. Do not create a worktree unless the user explicitly requests it.

## Project gates (after every task, before commit)

- `uv run pytest -q tests/registrations/<the new or touched file>` — task-scoped tests pass.
- `uv run pytest -q` — full suite green when the task is complete (798 baseline; expect ~810 by end of slice).
- `uv run ruff check .` — clean.
- `uv run mypy .` — clean.

If a task introduces a CSS-only contract test, the matching CSS rule must live in `static/css/parent_theme.css`.

---

## File map (locked before tasks)

**New test files:**
- `tests/registrations/test_parent_surface_copy_contract.py` — the Latvian audit contract.
- `tests/registrations/test_entry_surface_polish.py` — start_registration + verify_code polish contracts.
- `tests/registrations/test_portal_polish.py` — parent_portal polish contracts.

**Modified test files:**
- (none expected; if collisions appear with the empty-state DOM change, the touched file is `tests/registrations/test_portal_polish.py` plus any existing portal test that asserts the old `<h2>Nav pieteikumu</h2>` markup — the responsible test is updated in the same task as the markup change).

**Modified templates:**
- `templates/registrations/start_registration.html`
- `templates/registrations/verify_code.html`
- `templates/registrations/parent_portal.html`
- `templates/parent_ui/includes/empty_state.html` (extension: optional CTA slot)

**Modified CSS:**
- `static/css/parent_theme.css` (new `.fk-page-intro` helper; new `@media (max-width: 720px)` rules for `.fk-applications`, `.fk-application-card`, `.fk-app-actions`, `.fk-helper-card`; entry/verify-form mobile attributes; ≥44 px touch-target floors).

**Modified docs (closeout only):**
- `AGENTS.md` — Slice E delivery note + manual LAN verification record.
- `docs/milestones.md` — P4 status flipped from "Slices A–D delivered; Slice E outstanding" to "Slices A–E delivered" (P4 complete).

No view, model, service, form, JS, or migration changes.

---

## Task 1: Latvian copy contract test + fix audit

**Files:**
- Create: `tests/registrations/test_parent_surface_copy_contract.py`
- Modify (text only): any parent-facing template/partial flagged by the test.

This task introduces the contract test in RED, then sweeps every parent surface until it goes GREEN. The test is the source of truth for the audit — the spec's token list is a starting point only.

- [ ] **Step 1: Write the failing contract test**

Create `tests/registrations/test_parent_surface_copy_contract.py`:

```python
"""Latvian copy contract for parent-facing surfaces (P4 Slice E)."""

import re
from html.parser import HTMLParser

import pytest
from django.urls import reverse

# English tokens that should never appear in user-visible copy on parent surfaces.
# Match is word-boundary, case-insensitive, against visible text only.
ENGLISH_TOKENS = (
    "submit", "save", "continue", "back", "next", "cancel",
    "loading", "error", "success", "please", "required",
    "yes", "no", "warning", "delete", "edit",
)

# Allowlisted fragments — legitimate English that must pass through.
# Stripped from the rendered HTML *before* extracting visible text.
ALLOWED_FRAGMENTS = (
    "FK Cēsis",            # brand
)

_TOKEN_RE = re.compile(
    r"\b(" + "|".join(ENGLISH_TOKENS) + r")\b",
    re.IGNORECASE,
)


class _VisibleTextExtractor(HTMLParser):
    """Collect text nodes outside <script>, <style>, and HTML attributes."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):  # noqa: ANN001
        if self._skip_depth == 0:
            self._parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self._parts)


def _visible_text(html: str) -> str:
    stripped = html
    for fragment in ALLOWED_FRAGMENTS:
        stripped = stripped.replace(fragment, " ")
    parser = _VisibleTextExtractor()
    parser.feed(stripped)
    return parser.text


def _assert_no_english_leakage(html: str, surface: str) -> None:
    text = _visible_text(html)
    leaks = sorted({m.group(0).lower() for m in _TOKEN_RE.finditer(text)})
    assert not leaks, (
        f"English tokens leaked into {surface}: {leaks}\n"
        f"Sample text around first leak:\n"
        f"{text[: text.lower().find(leaks[0]) + 80] if leaks else ''}"
    )


@pytest.mark.django_db
class TestParentSurfaceCopyContract:
    def test_start_registration_has_no_english_leakage(self, client):
        url = reverse("registrations:start-registration")
        response = client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/register/"
        )

    def test_verify_code_has_no_english_leakage(self, client):
        session = client.session
        session["pending_verification_email"] = "parent@example.com"
        session.save()
        url = reverse("accounts:verify-one-time-code")
        response = client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/register/verify/"
        )

    def test_parent_portal_empty_has_no_english_leakage(self, verified_client):
        url = reverse("registrations:parent-portal")
        response = verified_client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/portal/ (empty)"
        )

    def test_parent_portal_with_apps_has_no_english_leakage(
        self, verified_client, parent_account
    ):
        from apps.registrations.models import RegistrationApplication

        RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
            guardian_full_name="Anna Bērziņa",
            member_full_name="Jānis Bērziņš",
        )
        url = reverse("registrations:parent-portal")
        response = verified_client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/portal/ (with apps)"
        )

    def test_application_workspace_has_no_english_leakage(
        self, verified_client, parent_account
    ):
        from apps.registrations.models import RegistrationApplication

        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
        )
        url = reverse("registrations:application-workspace", args=[app.id])
        response = verified_client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/applications/<id>/"
        )


class TestNewRegistrationTemplateCopy:
    """Static scan for /applications/new/ — its only render path is the
    no-JS POST-invalid fallback, which is impractical to render in a unit
    test. Scan the template source instead, stripping Django comment
    blocks first so legitimate developer comments don't trip the audit."""

    def test_new_registration_template_has_no_english_tokens(self):
        from pathlib import Path

        source = Path(
            "templates/registrations/new_registration.html"
        ).read_text(encoding="utf-8")
        # Strip {% comment %}…{% endcomment %} blocks (multiline).
        cleaned = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}",
            " ",
            source,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Strip {# … #} single-line comments.
        cleaned = re.sub(r"\{#.*?#\}", " ", cleaned)
        # Strip inline <script>…</script> blocks (only developer JS lives
        # inside the template; runtime strings flow via Django tags).
        cleaned = re.sub(
            r"<script\b[^>]*>.*?</script>",
            " ",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for fragment in ALLOWED_FRAGMENTS:
            cleaned = cleaned.replace(fragment, " ")
        leaks = sorted({m.group(0).lower() for m in _TOKEN_RE.finditer(cleaned)})
        assert not leaks, (
            f"English tokens in new_registration.html (static scan): {leaks}"
        )
```

- [ ] **Step 2: Run the test to surface every leak**

Run: `uv run pytest -q tests/registrations/test_parent_surface_copy_contract.py -v`

Expected: one or more tests FAIL listing the leaking tokens per surface. Capture the output — it is your audit list.

- [ ] **Step 3: Inspect each leak and decide per leak**

For each leak the test reports:

| Leak source | Action |
|---|---|
| User-visible English text in a `.html` file | Translate to Latvian. Find the file via `grep -rn '<token>' templates/` (use the exact case-folded match). |
| HTML element name or attribute that slipped through (e.g. `<noscript>`) | Should not happen — the `_VisibleTextExtractor` strips tags. If it does, the parser has a bug; fix it. |
| Legitimate proper noun / brand fragment | Add to `ALLOWED_FRAGMENTS` in the test with a `# comment` explaining why. |
| English string in an inline `<script>` block in a template | Should not be reported (script is stripped). If reported, fix the parser. |

Do not extend `ENGLISH_TOKENS` in this task — the contract list is fixed.

- [ ] **Step 4: Translate flagged template text**

For each Latvian-translation fix, make a minimal edit. Reference table:

| English | Latvian (use these) |
|---|---|
| Submit | Iesniegt |
| Save | Saglabāt |
| Continue | Turpināt |
| Back | Atpakaļ |
| Next | Tālāk |
| Cancel | Atcelt |
| Loading | Notiek ielāde |
| Error | Kļūda |
| Success | Veiksmīgi |
| Please | Lūdzu |
| Required | Obligāts |
| Yes | Jā |
| No | Nē |
| Warning | Brīdinājums |
| Delete | Dzēst |
| Edit | Rediģēt |

For context-sensitive translations (e.g. "Submit" on a registration form is "Iesniegt pieteikumu"), use the longer form. Reuse phrasing that already appears elsewhere on the same surface where possible.

- [ ] **Step 5: Re-run the test until green**

Run: `uv run pytest -q tests/registrations/test_parent_surface_copy_contract.py -v`

Expected: all 5 tests PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass (no regressions). Translation edits may break a test that asserts a specific English string — if so, update that assertion to the new Latvian text, but do **not** revert the template fix.

- [ ] **Step 7: Run the linters**

Run: `uv run ruff check .` and `uv run mypy .`

Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add tests/registrations/test_parent_surface_copy_contract.py templates/
git commit -m "$(cat <<'EOF'
test(registrations): add parent-surface Latvian-copy contract + fix leaks

Introduces a parametrized regression test that scans rendered visible text
on /register/, /register/verify/, /portal/ (empty + with apps), and
/applications/<id>/ for English-token leakage. Each surface goes green
after the audit fixes captured in this commit.

The token list is fixed; legitimate English fragments are allowlisted in
the test with comments. Future leaks will fail CI.
EOF
)"
```

If no English leaks were found in step 3 (entirely possible — the codebase is Latvian-by-default), the commit message changes to:
> `test(registrations): add parent-surface Latvian-copy contract regression test` (drop the "fix leaks" tail).

---

## Task 2: Extend `empty_state.html` with optional CTA slot

**Files:**
- Modify: `templates/parent_ui/includes/empty_state.html`
- Test: `tests/registrations/test_portal_polish.py` (new file — also seeded for Task 5)

This task adds an optional CTA anchor to the shared empty-state primitive so the portal can stop carrying its bespoke markup in Task 5. Existing two-argument call sites continue to work.

- [ ] **Step 1: Write the failing tests**

Create `tests/registrations/test_portal_polish.py`:

```python
"""Tests for P4 Slice E — parent portal + shared empty-state primitive polish."""

import re

import pytest
from django.template.loader import render_to_string


class TestEmptyStatePartialAcceptsCta:
    """Shared empty_state.html grows an optional CTA slot for Slice E."""

    def test_renders_title_and_body_without_cta(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {"title": "Nav pieteikumu", "body": "Jums vēl nav neviena pieteikuma."},
        )
        assert "Nav pieteikumu" in html
        assert "Jums vēl nav neviena pieteikuma." in html
        assert "fk-empty-state__cta" not in html
        assert "<a " not in html

    def test_renders_cta_when_url_and_label_provided(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {
                "title": "Nav pieteikumu",
                "body": "Jums vēl nav neviena pieteikuma.",
                "cta_url": "/applications/new/",
                "cta_label": "Sākt jaunu reģistrāciju",
            },
        )
        assert 'href="/applications/new/"' in html
        assert "Sākt jaunu reģistrāciju" in html
        assert "fk-empty-state__cta" in html
        assert "fk-button--primary" in html
        assert "fk-button--full" in html

    def test_does_not_render_cta_when_only_url_is_provided(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {
                "title": "Nav pieteikumu",
                "cta_url": "/applications/new/",
            },
        )
        assert "fk-empty-state__cta" not in html
        assert "<a " not in html

    def test_does_not_render_cta_when_only_label_is_provided(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {
                "title": "Nav pieteikumu",
                "cta_label": "Sākt jaunu reģistrāciju",
            },
        )
        assert "fk-empty-state__cta" not in html
        assert "<a " not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/registrations/test_portal_polish.py::TestEmptyStatePartialAcceptsCta -v`

Expected: 3 of 4 tests FAIL (only `test_renders_title_and_body_without_cta` passes, since the partial already supports that call).

- [ ] **Step 3: Extend the partial**

Replace the contents of `templates/parent_ui/includes/empty_state.html` with:

```django
{% comment %}
Shared empty-state primitive for "no items yet" surfaces.

Parameters:
  title      — Latvian heading copy (recommended).
  body       — Latvian explanatory copy (optional).
  cta_url    — URL for the optional action button (optional).
  cta_label  — Latvian label for the optional action button (optional).

Both cta_url and cta_label must be provided for the CTA anchor to render;
either alone is ignored.
{% endcomment %}
<div class="fk-empty-state" data-empty-state>
  {% if title %}<p class="fk-empty-state__title">{{ title }}</p>{% endif %}
  {% if body %}<p class="fk-empty-state__body">{{ body }}</p>{% endif %}
  {% if cta_url and cta_label %}
    <a href="{{ cta_url }}" class="fk-button fk-button--primary fk-button--full fk-empty-state__cta">{{ cta_label }}</a>
  {% endif %}
</div>
```

- [ ] **Step 4: Re-run tests**

Run: `uv run pytest -q tests/registrations/test_portal_polish.py::TestEmptyStatePartialAcceptsCta -v`

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass. No existing caller passes `cta_url`/`cta_label`, so the change is backward-compatible.

- [ ] **Step 6: Commit**

```bash
git add templates/parent_ui/includes/empty_state.html tests/registrations/test_portal_polish.py
git commit -m "$(cat <<'EOF'
feat(parent-ui): extend empty_state.html with optional CTA slot

Adds optional cta_url + cta_label parameters to the shared empty-state
primitive. When both are provided, renders a primary full-width anchor
underneath the title/body. Existing two-argument call sites are
unaffected.

Enables the parent portal to drop its bespoke empty-state markup in the
next commit.
EOF
)"
```

---

## Task 3: `start_registration.html` polish

**Files:**
- Modify: `templates/registrations/start_registration.html`
- Modify: `static/css/parent_theme.css` (add `.fk-page-intro`)
- Test: `tests/registrations/test_entry_surface_polish.py` (new file)

Fixes three known bugs (duplicate include, broken button class, eyebrow-wraps-form) and applies the workspace-aligned mobile input attributes.

- [ ] **Step 1: Write the failing tests**

Create `tests/registrations/test_entry_surface_polish.py`:

```python
"""Tests for P4 Slice E — start_registration and verify_code polish."""

import re
from pathlib import Path

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestStartRegistrationPolish:
    def test_renders_exactly_one_section_card(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        # Regression for the duplicate {% include "section_card.html" %}.
        assert html.count('class="fk-section-card"') == 1

    def test_submit_button_uses_canonical_modifier_class(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        assert "fk-button--primary" in html
        # Regression for the broken "fk-button primary" classname.
        assert re.search(r'class="fk-button primary"', html) is None

    def test_form_is_not_wrapped_in_eyebrow(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        # The form must not be a descendant of fk-eyebrow.
        match = re.search(
            r'<[^>]*class="[^"]*\bfk-eyebrow\b[^"]*"[^>]*>(.*?)<form',
            html,
            re.DOTALL,
        )
        assert match is None, "fk-eyebrow wraps a <form>; drop the wrapper."

    def test_email_input_has_mobile_input_attrs(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        # Email input gets autocomplete + inputmode for mobile keyboards.
        m = re.search(
            r'<input[^>]*\bname="email"[^>]*>',
            html,
        )
        assert m is not None
        tag = m.group(0)
        assert 'inputmode="email"' in tag
        assert 'autocomplete="email"' in tag


class TestParentThemeCssEntrySurfaces:
    def test_fk_page_intro_class_defined(self):
        css = Path("static/css/parent_theme.css").read_text(encoding="utf-8")
        assert re.search(r"\.fk-page-intro\s*\{", css), (
            ".fk-page-intro helper class must be defined in parent_theme.css"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/registrations/test_entry_surface_polish.py -v`

Expected: 4 of 5 tests FAIL (duplicate section_card, broken button class, eyebrow wraps form, missing inputmode attrs, missing `.fk-page-intro`).

- [ ] **Step 3: Rewrite `start_registration.html`**

Replace the contents of `templates/registrations/start_registration.html` with:

```django
{% extends "parent_ui/base_parent_page.html" %}
{% load static %}

{% block page_title %}Reģistrācija — FK Cēsis MMS{% endblock %}

{% block page_content %}
{% include "parent_ui/includes/hero_card.html" with hero_title="Bērna reģistrācija" hero_subtitle="Reģistrējiet savu bērnu treniņiem FK Cēsis. Sākumā augšupielādējiet ID dokumentu, lai mēs varētu nolasīt datus un automātiski aizpildīt daļu no pieteikuma." %}

{% include "parent_ui/includes/error_summary.html" %}

<section class="fk-section-card">
  <div class="fk-section-header">
    <div class="fk-section-title-wrap">
      <div>
        <h2>Droša piekļuve</h2>
      </div>
    </div>
  </div>
  <div class="fk-section-body">
    {% if error %}
    <p class="fk-error-state__body" role="alert">{{ error }}</p>
    {% endif %}
    <form method="post" novalidate>
      {% csrf_token %}
      <div class="fk-form-group fk-lead">
        <label for="id_email">E-pasts</label>
        <input type="email"
               name="email"
               id="id_email"
               required
               placeholder="jusu@epasts.lv"
               inputmode="email"
               autocomplete="email"
               value="{{ form.email.value|default:'' }}">
      </div>
      <button type="submit" class="fk-button fk-button--primary fk-button--full">Turpināt</button>
    </form>
  </div>
</section>
{% endblock %}
```

Notes on the changes:
- Single `section_card` include is replaced by an inline `<section class="fk-section-card">` block that owns the form — this matches the workspace pattern and is exactly one card.
- `fk-button primary` → `fk-button fk-button--primary fk-button--full`.
- `fk-eyebrow` wrapper removed.
- `inputmode="email"` + `autocomplete="email"` added.
- The `error` context variable (already passed from `start_registration` view on validation failure) renders inside the card.

- [ ] **Step 4: Add `.fk-page-intro` to `parent_theme.css`**

Append to `static/css/parent_theme.css` (after the `.fk-empty-state h2` block at line ~771, before the `/* ── Page heading ── */` section header):

```css

/* ── Page intro paragraph (helper for muted page-level explanatory copy) ── */

.fk-page-intro {
  margin: 0 0 16px;
  color: var(--fk-muted);
  font-size: 0.95rem;
  line-height: 1.5;
}
```

- [ ] **Step 5: Re-run task tests**

Run: `uv run pytest -q tests/registrations/test_entry_surface_polish.py -v`

Expected: 5 of 5 tests in `TestStartRegistrationPolish` + `TestParentThemeCssEntrySurfaces` PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass. The Latvian-audit test from Task 1 must still pass against the rewritten template.

- [ ] **Step 7: Linters**

Run: `uv run ruff check .` and `uv run mypy .`

Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add templates/registrations/start_registration.html static/css/parent_theme.css tests/registrations/test_entry_surface_polish.py
git commit -m "$(cat <<'EOF'
feat(registrations): polish /register/ — bug fixes + mobile input attrs

- removes the duplicate fk-section-card include (line-11 dup of line-8)
- repairs fk-button class: "fk-button primary" → "fk-button fk-button--primary"
- drops the fk-eyebrow wrapper around the form (incorrect typographic
  treatment; eyebrow is a small-uppercase tagline style)
- adds inputmode="email" + autocomplete="email" for the mobile keyboard
- introduces the .fk-page-intro CSS helper class consumed in the next
  commits (verify_code, parent_portal)

Visual cohesion with the workspace; mobile baseline raised for the
guardian-email entry page.
EOF
)"
```

---

## Task 4: `verify_code.html` polish

**Files:**
- Modify: `templates/registrations/verify_code.html`
- Test: `tests/registrations/test_entry_surface_polish.py` (append `TestVerifyCodePolish` class)

Switches the inline-styled hint paragraph to the `.fk-page-intro` class and adds mobile-keyboard / autofocus / one-time-code attributes to the code input.

- [ ] **Step 1: Append failing tests**

Append to `tests/registrations/test_entry_surface_polish.py`:

```python
@pytest.mark.django_db
class TestVerifyCodePolish:
    def _get(self, client):
        session = client.session
        session["pending_verification_email"] = "parent@example.com"
        session.save()
        return client.get(reverse("accounts:verify-one-time-code"))

    def test_code_input_uses_mobile_one_time_code_attrs(self, client):
        response = self._get(client)
        html = response.content.decode("utf-8")
        m = re.search(r'<input[^>]*\bname="code"[^>]*>', html)
        assert m is not None
        tag = m.group(0)
        assert 'inputmode="numeric"' in tag
        assert 'autocomplete="one-time-code"' in tag
        assert "autofocus" in tag
        # Existing constraints preserved.
        assert 'maxlength="6"' in tag
        assert 'pattern="[0-9]{6}"' in tag

    def test_pending_email_notice_uses_page_intro_helper(self, client):
        response = self._get(client)
        html = response.content.decode("utf-8")
        # The pending-email paragraph uses .fk-page-intro instead of
        # inline style="..." attributes.
        m = re.search(
            r'<p[^>]*\bclass="[^"]*\bfk-page-intro\b[^"]*"[^>]*>',
            html,
        )
        assert m is not None, "pending-email notice must use fk-page-intro"
        # Inline-style migration: no style="color: var(--fk-muted)" remains.
        assert "style=\"margin: 0 0 16px; color: var(--fk-muted);\"" not in html

    def test_submit_button_is_full_width(self, client):
        response = self._get(client)
        html = response.content.decode("utf-8")
        m = re.search(
            r'<button[^>]*type="submit"[^>]*class="([^"]+)"',
            html,
        )
        assert m is not None
        classes = m.group(1)
        assert "fk-button--primary" in classes
        assert "fk-button--full" in classes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/registrations/test_entry_surface_polish.py::TestVerifyCodePolish -v`

Expected: 3 of 3 tests FAIL.

- [ ] **Step 3: Rewrite `verify_code.html`**

Replace contents of `templates/registrations/verify_code.html` with:

```django
{% extends "parent_ui/base_parent_page.html" %}
{% load static %}

{% block page_title %}Koda verificēšana — FK Cēsis MMS{% endblock %}

{% block page_content %}
{% include "parent_ui/includes/hero_card.html" with hero_title="Droša piekļuve" hero_subtitle="Ievadiet verifikācijas kodu, kas nosūtīts uz jūsu e-pastu, lai apstiprinātu piekļuvi." %}
{% include "parent_ui/includes/alert.html" %}
{% include "parent_ui/includes/error_summary.html" %}

<section class="fk-section-card">
  <div class="fk-section-body">
    {% if pending_email %}
    <p class="fk-page-intro">
      Verifikācijas kods tika nosūtīts uz <strong>{{ pending_email }}</strong>.
      Ievadiet kodu zemāk, lai turpinātu.
    </p>
    {% endif %}
    <form method="post" novalidate>
      {% csrf_token %}
      <div class="fk-form-group fk-lead">
        <label for="id_code">Piekļuves kods</label>
        <input type="text"
               name="code"
               id="id_code"
               required
               placeholder="Ievadiet 6 ciparu kodu"
               value="{{ form.code.value|default:'' }}"
               maxlength="6"
               pattern="[0-9]{6}"
               inputmode="numeric"
               autocomplete="one-time-code"
               autofocus>
      </div>
      <button type="submit" class="fk-button fk-button--primary fk-button--full">Apstiprināt</button>
    </form>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 4: Re-run task tests**

Run: `uv run pytest -q tests/registrations/test_entry_surface_polish.py -v`

Expected: all tests in the file PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Linters**

Run: `uv run ruff check .` and `uv run mypy .`

Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add templates/registrations/verify_code.html tests/registrations/test_entry_surface_polish.py
git commit -m "$(cat <<'EOF'
feat(registrations): polish /register/verify/ — mobile keyboard + autofocus

- migrates the pending-email notice off inline style="..." attributes
  onto the new .fk-page-intro helper class
- code input gains inputmode="numeric", autocomplete="one-time-code",
  and autofocus for SMS-paste / single-purpose-page flow
- preserves existing maxlength + pattern constraints
- submit button uses fk-button--full for the mobile baseline
EOF
)"
```

---

## Task 5: `parent_portal.html` polish — shared empty-state + strip inline styles

**Files:**
- Modify: `templates/registrations/parent_portal.html`
- Test: `tests/registrations/test_portal_polish.py` (append `TestPortalEmptyState` + `TestPortalNoInlineStyles`)

Switches the bespoke `<div class="fk-empty-state">…</div>` markup to the shared partial extended in Task 2, and removes inline `style="..."` attributes from the application-list region.

- [ ] **Step 1: Append failing tests**

Append to `tests/registrations/test_portal_polish.py`:

```python
import re

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestPortalEmptyState:
    def test_empty_portal_uses_shared_empty_state_partial(self, verified_client):
        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode("utf-8")
        assert "data-empty-state" in html
        assert "fk-empty-state__title" in html
        assert "fk-empty-state__cta" in html
        # The bespoke <h2>Nav pieteikumu</h2> markup is gone.
        assert "<h2>Nav pieteikumu</h2>" not in html

    def test_empty_state_cta_links_to_new_application(self, verified_client):
        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode("utf-8")
        m = re.search(
            r'<a[^>]*class="[^"]*\bfk-empty-state__cta\b[^"]*"[^>]*href="([^"]+)"',
            html,
        )
        # Fall back to the alternate attribute ordering for robustness.
        if m is None:
            m = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*\bfk-empty-state__cta\b',
                html,
            )
        assert m is not None
        assert m.group(1) == reverse("registrations:new-application")


@pytest.mark.django_db
class TestPortalNoInlineStyles:
    def test_application_card_region_has_no_inline_styles(
        self, verified_client, parent_account
    ):
        from apps.registrations.models import RegistrationApplication

        RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
            guardian_full_name="Anna Bērziņa",
            member_full_name="Jānis Bērziņš",
        )
        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode("utf-8")

        # Extract <article class="fk-application-card">…</article> regions and
        # assert they (and their direct descendants) carry no style="…" attrs.
        articles = re.findall(
            r'<article[^>]*\bclass="[^"]*\bfk-application-card\b[^"]*"[^>]*>(.*?)</article>',
            html,
            re.DOTALL,
        )
        assert articles, "expected at least one fk-application-card region"
        for region in articles:
            assert 'style="' not in region, (
                "inline style attribute found inside fk-application-card region"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/registrations/test_portal_polish.py -v`

Expected: the new tests FAIL; the Task 2 empty-state tests still PASS.

- [ ] **Step 3: Rewrite `parent_portal.html`**

Replace contents of `templates/registrations/parent_portal.html` with:

```django
{% extends "parent_ui/base_parent_page.html" %}
{% load static %}

{% block page_title %}Mani pieteikumi — FK Cēsis MMS{% endblock %}

{% block page_content %}
<p class="fk-eyebrow">FK Cēsis MMS</p>
<h1 class="fk-page-title">Mani pieteikumi</h1>
<p class="fk-page-intro">Pārskatiet un turpiniet — šeit redzams katra pieteikuma statuss un nākamais solis.</p>

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
      <div class="fk-app-meta fk-app-meta--review">
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
        <a href="{% url 'registrations:application-workspace' app.pk %}" class="fk-button fk-button--primary fk-button--full">Turpināt pieteikumu</a>
      {% else %}
        <a href="{% url 'registrations:application-workspace' app.pk %}" class="fk-button fk-button--secondary fk-button--full">Skatīt pieteikumu</a>
      {% endif %}
    </div>
  </article>
  {% endfor %}
</section>

{% else %}
{% url 'registrations:new-application' as new_application_url %}
{% include "parent_ui/includes/empty_state.html" with title="Nav pieteikumu" body="Jums vēl nav neviena pieteikuma." cta_url=new_application_url cta_label="Sākt jaunu reģistrāciju" %}
{% endif %}

<div class="fk-helper-card">
  <div class="fk-helper-copy">
    <div class="fk-helper-icon">ⓘ</div>
    <div>
      <h3>Nevari atrast savu pieteikumu?</h3>
      <p>Pārliecinies, ka esi reģistrējies ar to pašu e-pasta adresi, ko izmantoji pieteikuma izveidē.</p>
    </div>
  </div>
  <a href="{% url 'registrations:start-registration' %}" class="fk-button fk-button--secondary fk-button--full">✉ Pārbaudīt citu e-pastu</a>
</div>
{% endblock %}
```

Changes from the previous version:
- Top paragraph: `class="fk-page-subtitle"` → `class="fk-page-intro"` (consistent helper).
- Empty-state block: replaced bespoke `<div class="fk-empty-state">…</div>` with the shared partial extended in Task 2.
- Application-card action anchors: gained `fk-button--full` modifier.
- Helper-card CTA: gained `fk-button--full` modifier.
- Inline `style="margin-top:28px;"`, `style="margin-top:10px;"`, `style="margin-top:16px;"` removed; the bespoke `style="width:..."` on `.fk-progress-bar` spans is preserved because those are dynamic width values driven by status, not stylistic chrome.
- Sub-class `fk-app-meta--review` replaces `style="margin-top:10px;"` so the spacing intent stays in CSS land — see Task 6 for the rule.

Note: the `fk-progress-bar > span[style="width:…"]` inline styles are intentionally kept because they encode dynamic content (per-app progress percentage). These are not the style-attribute leaks the regression test targets — the test scopes its assertion to the `<article class="fk-application-card">` *region*, and the regex captures any `style="` within that region. Re-read the regex in step 1: if dynamic progress-bar widths cause the test to fail, scope the assertion more tightly by allow-listing the progress-bar `span style="width:` pattern instead.

**Decision rule for this task:** if `test_application_card_region_has_no_inline_styles` fails because of the dynamic progress-bar widths, update the test to allow the `width:\d+%` pattern and re-run. Do not change the dynamic-width markup — width is content, not styling.

- [ ] **Step 4: Re-run task tests**

Run: `uv run pytest -q tests/registrations/test_portal_polish.py -v`

Expected: all tests in the file PASS. If `test_application_card_region_has_no_inline_styles` fails because of dynamic progress-bar widths, refine the assertion as described in the decision rule above.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass.

If any existing portal test asserts the old `<h2>Nav pieteikumu</h2>` text or the bespoke `fk-empty-state h2` selector, update that test in the same commit. Locate offenders with:

```bash
uv run pytest -q tests/registrations/ -k 'portal or empty_state' --collect-only
```

then `grep -rn 'Nav pieteikumu' tests/` to find specific assertions.

- [ ] **Step 6: Linters**

Run: `uv run ruff check .` and `uv run mypy .`

Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add templates/registrations/parent_portal.html tests/registrations/test_portal_polish.py
git commit -m "$(cat <<'EOF'
feat(registrations): polish /portal/ — shared empty-state + inline-style strip

- switches the bespoke empty-state markup to the shared partial extended
  in the previous commit; CTA renders via the partial's new slot
- removes inline style="margin-top:…" attributes inside the application
  list region in favour of a new fk-app-meta--review modifier and the
  shared .fk-page-intro helper
- application-card action anchors and the helper-card CTA gain
  fk-button--full for the mobile baseline

Dynamic progress-bar widths remain inline because they encode content,
not styling.
EOF
)"
```

---

## Task 6: CSS mobile breakpoints for portal + helper card + review-meta spacing

**Files:**
- Modify: `static/css/parent_theme.css`
- Test: `tests/registrations/test_portal_polish.py` (append `TestParentThemeCssPortalMobile`)

Adds the `@media (max-width: 720px)` block from the spec (Section 3.5) plus the `fk-app-meta--review` rule introduced by Task 5.

- [ ] **Step 1: Append failing tests**

Append to `tests/registrations/test_portal_polish.py`:

```python
from pathlib import Path


class TestParentThemeCssPortalMobile:
    def _css(self) -> str:
        return Path("static/css/parent_theme.css").read_text(encoding="utf-8")

    def test_applications_grid_stacks_under_720(self):
        css = self._css()
        # The new rule must live inside a max-width:720px media query.
        m = re.search(
            r"@media\s*\(\s*max-width:\s*720px\s*\)\s*\{(.*?)\}\s*(?:@media|\Z)",
            css,
            re.DOTALL,
        )
        # Multiple 720px blocks may exist; concatenate their bodies.
        bodies = re.findall(
            r"@media\s*\(\s*max-width:\s*720px\s*\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            css,
            re.DOTALL,
        )
        joined = "\n".join(bodies)
        assert ".fk-applications" in joined
        assert "grid-template-columns: 1fr" in joined
        assert ".fk-application-card" in joined
        assert ".fk-app-actions" in joined
        assert ".fk-helper-card" in joined

    def test_review_meta_modifier_has_spacing_rule(self):
        css = self._css()
        assert re.search(r"\.fk-app-meta--review\s*\{", css)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/registrations/test_portal_polish.py::TestParentThemeCssPortalMobile -v`

Expected: 2 of 2 tests FAIL.

- [ ] **Step 3: Append the new CSS rules**

Append to `static/css/parent_theme.css` (after the existing `@media (max-width: 420px)` block at line ~829, before the `/* ── OCR async UX (P4 Slice B) ── */` section header):

```css

/* ── Portal + helper card mobile polish (P4 Slice E) ── */

.fk-app-meta--review {
  margin-top: 10px;
}

@media (max-width: 720px) {
  .fk-applications {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .fk-application-card {
    grid-template-columns: 1fr;
    padding: 18px;
  }
  .fk-app-actions .fk-button {
    width: 100%;
    box-sizing: border-box;
  }
  .fk-helper-card {
    flex-direction: column;
    align-items: stretch;
  }
  .fk-helper-card .fk-button {
    width: 100%;
    box-sizing: border-box;
  }
}
```

- [ ] **Step 4: Re-run task tests**

Run: `uv run pytest -q tests/registrations/test_portal_polish.py -v`

Expected: all tests in the file PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Linters**

Run: `uv run ruff check .` and `uv run mypy .`

Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add static/css/parent_theme.css tests/registrations/test_portal_polish.py
git commit -m "$(cat <<'EOF'
feat(parent-theme): mobile-first stacking for portal + helper card

Adds a max-width:720px block covering .fk-applications, .fk-application-card,
.fk-app-actions, .fk-helper-card so the chooser/dashboard collapses to a
single-column flow on phones. Introduces .fk-app-meta--review for the
review-message spacing that was previously inline in parent_portal.html.

Visual cohesion with the workspace mobile baseline delivered in Slice D.
EOF
)"
```

---

## Task 7: Final gates + LAN verification + docs closeout

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/milestones.md`
- No test changes (closeout only).

- [ ] **Step 1: Final full-suite gate**

Run all three gates:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```

Expected: pytest ~810 tests pass (798 baseline + new contract/polish tests), ruff clean, mypy clean.

If any gate fails, fix in place and re-run before continuing.

- [ ] **Step 2: Run the dev server on the LAN interface**

```bash
uv run python manage.py runserver 192.168.3.245:8000
```

Leave it running for the manual checks below.

- [ ] **Step 3: Manual LAN verification (from a phone)**

Open the dev server URL on a phone and walk through:

1. `/register/` — form fits the viewport with no horizontal scroll; email field opens the email keyboard; "Turpināt" button is full-width and tappable.
2. `/register/verify/` — code field autofocuses; numeric keypad appears; paste-from-SMS works; "Apstiprināt" button is full-width.
3. `/portal/` empty state — create a fresh verified account with no applications and confirm the empty-state CTA renders full-width and is tappable.
4. `/portal/` with applications — list stacks cleanly; action buttons are full-width; status badge is legible.
5. Scan every surface for English text — only "FK Cēsis" should be visible.

Record findings (pass / fail per item) in a scratch note for Step 4.

- [ ] **Step 4: Update `AGENTS.md`**

Locate the "P4 Slice D delivered" delivery note in `AGENTS.md` (search: `Slice D delivered`). Append a "Slice E delivered" entry directly after it, following the same prose style as the Slice D note. Use this template, filling in the LAN-verification results from step 3:

```markdown
- **P4 Slice E delivered (2026-05-25):** Closeout polish for the parent-flow entry/chooser/portal surfaces and Latvian copy normalization across all parent-facing pages.
  - `/register/`: removed duplicate `fk-section-card` include, repaired the broken `fk-button primary` class, dropped the `fk-eyebrow` wrapper, added `inputmode="email"`/`autocomplete="email"` and full-width primary CTA.
  - `/register/verify/`: switched the pending-email notice to the new `.fk-page-intro` helper, added `inputmode="numeric"`/`autocomplete="one-time-code"`/`autofocus` to the code input, full-width CTA.
  - `/portal/`: replaced the bespoke `<div class="fk-empty-state">` markup with the shared `empty_state.html` partial (now accepts optional `cta_url`/`cta_label`); stripped inline `style="margin-top:…"` attributes inside the application-card region in favour of a `.fk-app-meta--review` modifier; action anchors and helper-card CTA gain `fk-button--full`.
  - CSS: `.fk-page-intro` helper added; new `@media (max-width: 720px)` block stacks `.fk-applications`, `.fk-application-card`, `.fk-app-actions .fk-button`, `.fk-helper-card` for the mobile baseline.
  - Latvian copy: new parametrized contract test `tests/registrations/test_parent_surface_copy_contract.py` scans rendered visible text on `/register/`, `/register/verify/`, `/portal/` (empty + with apps), and `/applications/<id>/` for English-token leakage. Test list is fixed; legitimate fragments allowlisted in code with comments. <Fill in: number of leaks found and fixed, or "no leaks found in initial sweep".>
  - Manual LAN verification on 192.168.3.245 (2026-05-25): <Fill in pass/fail per item from step 3.>
  - Test suite: <fill in pytest count> passed (up from 798 baseline); ruff and mypy clean.
```

- [ ] **Step 5: Update `docs/milestones.md`**

Locate the P4 status header in `docs/milestones.md`:

```
**Status:** Slices A–D delivered; Slice E (entry/chooser/portal polish + Latvian copy audit) outstanding.
```

Replace with:

```
**Status:** complete (2026-05-25) — Slices A–E delivered.
```

Then locate the P4 acceptance section ("### P4 acceptance — Parent-flow UX polish + mobile-first workspace") header (line ~438) and add a status line directly under it:

```
**Status:** complete (2026-05-25).
```

(Mirror the wording other completed phases use; check P1, P2, P3 in the same file for the canonical form.)

- [ ] **Step 6: Final full-suite gate (post-docs)**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`

Expected: clean.

- [ ] **Step 7: Commit closeout**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "$(cat <<'EOF'
docs: mark P4 Slice E complete; record LAN verification + slice closeout

- AGENTS.md: append Slice E delivery note with the per-surface changes,
  Latvian copy audit summary, and LAN verification results
- docs/milestones.md: flip P4 status to "Slices A–E delivered" (P4
  complete) and add a status line under the P4 acceptance section
EOF
)"
```

- [ ] **Step 8: Stop the dev server**

Ctrl-C the `runserver` process started in step 2.

---

## Self-review notes (for the executor)

Before reporting this slice as complete, re-read the spec's Section 7 (Definition of Done) and confirm each line:

- [ ] P4 acceptance criteria 2, 8, 9 are met (verified by tests + manual LAN check).
- [ ] Test count moved from 798 to ≥810.
- [ ] `uv run ruff check .` clean.
- [ ] `uv run mypy .` clean.
- [ ] LAN verification recorded in `AGENTS.md`.
- [ ] `docs/milestones.md` P4 status reflects completion.

If any item fails, fix in a follow-up commit on the same branch before declaring the slice closed.
