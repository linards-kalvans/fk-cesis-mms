# P4 Slice A — Foundations (name normalization, consent schema, UX primitives)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the structural foundations that unblock every other P4 slice: a unit-tested Latvian name-normalization helper wired into OCR consumption sites, the schema migration adding personal-data-consent fields on `RegistrationApplication`, and the four shared parent-UI primitive partials (spinner, toast, empty state, error state) that Slices B–E will consume.

**Architecture:**
- Pure helper `normalize_latvian_name(name)` in `apps/integrations/name_normalization.py`. Applied at *consumption* sites only — encrypted OCR `payload` at rest stays raw (audit posture preserved); only the `encrypted_summary` lines and the `services.py` prefill reads use normalized names.
- Consent persistence is two nullable fields on `RegistrationApplication` plus one module-level version constant (`PERSONAL_DATA_CONSENT_VERSION = "v1-2026-05"`). The gate UX, T&C partial, and view wiring land in Slice C.
- Shared primitives live under `templates/parent_ui/includes/` alongside the existing `alert.html`, `form_field.html`, etc. Slice A only creates them and adds rendering smoke tests; downstream slices consume them.

**Tech Stack:** Django 5.x, Python 3.12, pytest, pytest-django, ruff, mypy. Run everything via `uv run`.

---

## File Structure

**Create:**
- `apps/integrations/name_normalization.py` — pure helper module.
- `tests/integrations/test_name_normalization.py` — unit tests for the helper.
- `apps/registrations/migrations/0007_personal_data_consent.py` — schema migration.
- `tests/registrations/test_personal_data_consent_schema.py` — migration + model smoke test.
- `templates/parent_ui/includes/spinner.html` — branded calm spinner partial.
- `templates/parent_ui/includes/toast.html` — auto-dismiss confirmation partial.
- `templates/parent_ui/includes/empty_state.html` — shared empty-state partial.
- `templates/parent_ui/includes/error_state.html` — shared page-level error-state partial.
- `tests/registrations/test_parent_ui_primitives.py` — render-smoke tests for the four primitives.

**Modify:**
- `apps/integrations/tiny_idp.py` — no change to encrypted payload mapping; leave provider names raw. (Documented here so the implementer does not accidentally normalize here.)
- `apps/integrations/tasks.py:108-113` — apply `normalize_latvian_name` when building the summary lines for `first_name` / `last_name` / `middle_name`.
- `apps/registrations/services.py:147-188` — apply `normalize_latvian_name` to `first_name` / `last_name` reads in both guardian-merge and member-merge blocks.
- `apps/registrations/models.py` — add `personal_data_consent_at` and `personal_data_consent_version` fields plus module-level `PERSONAL_DATA_CONSENT_VERSION` constant.

**Out of scope for Slice A** (will land in later slices):
- Wiring spinner/toast/empty/error partials into any view.
- Consent form, checkbox, T&C partial, gate logic, persistence on submit.
- Visibility-aware polling and OCR success confirmation behavior.

---

## Task 1: Latvian name-normalization helper

**Files:**
- Create: `apps/integrations/name_normalization.py`
- Test: `tests/integrations/test_name_normalization.py`

The helper converts ALL CAPS OCR names to Latvian title case. `str.title()` is insufficient — it mishandles hyphenated compound surnames, apostrophes, and lowercase nobiliary particles. The helper:

- Splits on whitespace into tokens.
- For each token, splits on hyphens into sub-tokens; each sub-token is capitalized (first char upper, rest lower) preserving Latvian diacritics.
- Lowercase nobiliary particles (`van`, `der`, `den`, `de`, `da`, `di`, `du`, `la`, `le`, `von`, `zu`, `af`, `al`) stay lowercase **unless** they are the first token of the name.
- Apostrophes are treated as in-token characters (the letter after `'` is lower-case, matching Latvian convention — `D'arcy` becomes `D'arcy` is unusual in Latvian; default to lowercase after apostrophe to avoid `D'Arcy`).
- Empty / whitespace-only input returns `""`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integrations/test_name_normalization.py
"""Unit tests for Latvian name normalization helper."""

import pytest

from apps.integrations.name_normalization import normalize_latvian_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("JĀNIS BĒRZIŅŠ", "Jānis Bērziņš"),
        ("jānis bērziņš", "Jānis Bērziņš"),
        ("BĒRZIŅŠ-KALNIŅŠ", "Bērziņš-Kalniņš"),
        ("ANNA MARIJA", "Anna Marija"),
        ("ŪLA", "Ūla"),
        ("VAN DER BERG", "van der Berg"),
        ("DE LA CRUZ", "de la Cruz"),
        ("VON TRAPP", "von Trapp"),
        ("VAN", "Van"),  # particle as the only/first token must capitalize.
        ("KALNIŅŠ-VAN-BERG", "Kalniņš-van-Berg"),
        ("  KRŪMIŅŠ   ", "Krūmiņš"),
        ("", ""),
        ("   ", ""),
        ("Jānis", "Jānis"),  # already normalized stays stable.
        ("ČUKČA-ĶĒNIŅŠ", "Čukča-Ķēniņš"),
    ],
)
def test_normalize_latvian_name(raw, expected):
    assert normalize_latvian_name(raw) == expected


def test_non_string_input_returns_empty_string():
    # Defensive: OCR payload values are always strings, but the helper should
    # not crash if callers pass None or a non-string.
    assert normalize_latvian_name(None) == ""  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/test_name_normalization.py -v`

Expected: collection error or `ModuleNotFoundError: No module named 'apps.integrations.name_normalization'`.

- [ ] **Step 3: Implement the helper**

```python
# apps/integrations/name_normalization.py
"""Latvian name normalization for OCR-extracted person fields.

OCR providers (tiny-IDP and similar) return names in ALL CAPS following
passport/eID conventions. Latvian display convention is title case, with
nobiliary particles ("van", "de", "von", ...) kept lowercase except when
they are the first token of the name. Hyphenated compound surnames must
capitalize each sub-token.

The helper is pure and side-effect free; apply it only at consumption
boundaries (summary rendering, prefill reads). The encrypted OCR payload
at rest is intentionally left raw to preserve audit posture.
"""

from __future__ import annotations

# Nobiliary particles that stay lowercase except when they are the first
# token of the name. Kept conservative — only common forms used in Latvia.
_PARTICLES: frozenset[str] = frozenset(
    {
        "van",
        "der",
        "den",
        "de",
        "da",
        "di",
        "du",
        "la",
        "le",
        "von",
        "zu",
        "af",
        "al",
    }
)


def _cap_subtoken(subtoken: str) -> str:
    """Capitalize a single sub-token preserving diacritics.

    Empty string returns empty string. Otherwise: first character upper,
    remaining characters lower.
    """
    if not subtoken:
        return ""
    return subtoken[0].upper() + subtoken[1:].lower()


def _normalize_token(token: str, *, is_first: bool) -> str:
    """Normalize a whitespace-separated token.

    Handles hyphenated compound surnames by splitting on ``-`` and
    capitalizing each sub-token. Particles (e.g. "van") stay lowercase
    unless they form the first token of the full name.
    """
    if not token:
        return ""

    if "-" in token:
        sub_tokens = token.split("-")
        normalized_sub = []
        for index, sub in enumerate(sub_tokens):
            lower_sub = sub.lower()
            if lower_sub in _PARTICLES and not (is_first and index == 0):
                normalized_sub.append(lower_sub)
            else:
                normalized_sub.append(_cap_subtoken(sub))
        return "-".join(normalized_sub)

    lower_token = token.lower()
    if lower_token in _PARTICLES and not is_first:
        return lower_token
    return _cap_subtoken(token)


def normalize_latvian_name(name: object) -> str:
    """Convert an OCR-provided name to Latvian title case.

    Pure helper — no I/O, no Django imports. Safe to call from any layer.

    Args:
        name: Raw name string from OCR (typically ALL CAPS). Non-string
            input is defensively coerced to empty string.

    Returns:
        Title-cased name with particles kept lowercase (unless first token)
        and hyphenated compounds capitalized per sub-token. Empty input
        returns ``""``.
    """
    if not isinstance(name, str):
        return ""

    stripped = name.strip()
    if not stripped:
        return ""

    tokens = stripped.split()
    return " ".join(
        _normalize_token(token, is_first=(index == 0))
        for index, token in enumerate(tokens)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/test_name_normalization.py -v`

Expected: all parametrized cases pass.

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/name_normalization.py tests/integrations/test_name_normalization.py
git commit -m "feat(integrations): add Latvian name normalization helper for OCR names"
```

---

## Task 2: Apply normalization at OCR consumption sites

**Files:**
- Modify: `apps/integrations/tasks.py` (summary builder around line 108-113)
- Modify: `apps/registrations/services.py` (prefill reads around line 147-188)
- Test: `tests/integrations/test_ocr_tasks.py` (extend existing)
- Test: `tests/registrations/test_new_app_prefill_from_extraction.py` (extend existing)

Wiring strategy:
- `apps/integrations/tasks.py` builds `encrypted_summary` lines from `result.person_fields`. We normalize `first_name`, `last_name`, and `middle_name` before formatting the summary line. `encrypted_payload` stays untouched (audit-preserved raw provider data).
- `apps/registrations/services.py:147-188` reads `first_name` / `last_name` from the decrypted payload to build prefill values. We normalize at the read site so prefill displays title-case names.

- [ ] **Step 1: Read the existing test files so the new tests match house style**

Run: `uv run pytest tests/integrations/test_ocr_tasks.py tests/registrations/test_new_app_prefill_from_extraction.py --collect-only -q`

Expected: collection succeeds; note the fixture names and pattern used (look at the existing OCR task test that drives a successful extraction end-to-end). The new tests will plug into the same fixtures.

- [ ] **Step 2: Add a failing test that the encrypted summary contains title-cased names**

Append to `tests/integrations/test_ocr_tasks.py`:

```python
def test_ocr_extract_job_normalizes_names_in_summary(db, settings):
    """Summary lines title-case ALL CAPS OCR names; raw payload stays raw."""
    from apps.documents.models import Document, DocumentExtraction
    from apps.documents.ocr import decrypt_json
    from apps.integrations.tasks import ocr_extract_job

    # Force the stub provider so the test is deterministic. The stub returns
    # ALL CAPS names — see apps/integrations/ocr.py::_stub_person.
    settings.OCR_PROVIDER = "stub"

    application = _make_application_with_uploaded_identity_document()
    document = application.documents.get(kind=Document.Kind.GUARDIAN_IDENTITY)

    ocr_extract_job(document.id)

    extraction = DocumentExtraction.objects.get(document=document)
    summary_text = decrypt_json(extraction.encrypted_summary)
    payload = decrypt_json(extraction.encrypted_payload)

    # Summary must show title case (Jānis Bērziņš), not ALL CAPS.
    assert "first_name: " in summary_text
    first_name_line = next(
        line for line in summary_text.splitlines() if line.startswith("first_name: ")
    )
    value = first_name_line.removeprefix("first_name: ")
    assert value == value.title() or value[0].isupper() and not value.isupper()
    # Raw payload preserves the provider value verbatim (audit posture).
    assert payload["person_fields"]["first_name"].isupper()
```

If `_make_application_with_uploaded_identity_document` is not already in this test module, replace the call with the same fixture pattern used by the file's existing successful-extraction test. **Do not** invent a new fixture — reuse what is there.

- [ ] **Step 3: Run the new test to verify it fails**

Run: `uv run pytest tests/integrations/test_ocr_tasks.py::test_ocr_extract_job_normalizes_names_in_summary -v`

Expected: FAIL — summary value is uppercase (matches payload).

- [ ] **Step 4: Wire normalization into the summary builder**

Open `apps/integrations/tasks.py`. At the top of the file, add the import next to the existing `from apps.documents.ocr import encrypt_json`:

```python
from apps.integrations.name_normalization import normalize_latvian_name
```

Then locate the summary loop (currently around line 108-113):

```python
    summary_lines: list[str] = []
    for key, value in result.person_fields.items():
        summary_lines.append(f"{key}: {value}")
    for key, value in result.document_metadata.items():
        summary_lines.append(f"{key}: {value}")
    encrypted_summary = encrypt_json("\n".join(summary_lines))
```

Replace with:

```python
    _NAME_KEYS = ("first_name", "last_name", "middle_name")
    summary_lines: list[str] = []
    for key, value in result.person_fields.items():
        display_value = normalize_latvian_name(value) if key in _NAME_KEYS else value
        summary_lines.append(f"{key}: {display_value}")
    for key, value in result.document_metadata.items():
        summary_lines.append(f"{key}: {value}")
    encrypted_summary = encrypt_json("\n".join(summary_lines))
```

Note: `encrypted_payload` is built **before** this block and still uses `result.person_fields` directly. Do not change it.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `uv run pytest tests/integrations/test_ocr_tasks.py::test_ocr_extract_job_normalizes_names_in_summary -v`

Expected: PASS.

- [ ] **Step 6: Add a failing test that prefill reads normalize names**

Append to `tests/registrations/test_new_app_prefill_from_extraction.py`:

```python
def test_new_app_prefill_normalizes_guardian_full_name(db):
    """Prior guardian extraction with ALL CAPS names yields title-case prefill."""
    from apps.registrations.services import build_new_application_prefill

    account, prior_app = _make_account_with_completed_guardian_extraction(
        first_name="JĀNIS",
        last_name="BĒRZIŅŠ",
    )

    prefill = build_new_application_prefill(account)

    assert prefill["guardian_full_name"] == "Jānis Bērziņš"


def test_new_app_prefill_normalizes_member_full_name(db):
    """Prior member extraction with ALL CAPS names yields title-case prefill."""
    from apps.registrations.services import build_new_application_prefill

    account, prior_app = _make_account_with_completed_member_extraction(
        first_name="ANNA",
        last_name="KALNIŅA-BĒRZIŅA",
    )

    prefill = build_new_application_prefill(account)

    assert prefill["member_full_name"] == "Anna Kalniņa-Bērziņa"
```

If the helper fixtures `_make_account_with_completed_guardian_extraction` / `_make_account_with_completed_member_extraction` do not already exist in this test module **with the `first_name` / `last_name` keyword arguments**, factor them out from the file's existing prior-extraction test instead of duplicating setup. The actual prefill entry point in services.py is whatever the existing test in this file already calls — use the same one.

- [ ] **Step 7: Run the new tests to verify they fail**

Run: `uv run pytest tests/registrations/test_new_app_prefill_from_extraction.py -k normalizes -v`

Expected: FAIL — current prefill returns `"JĀNIS BĒRZIŅŠ"` / `"ANNA KALNIŅA-BĒRZIŅA"`.

- [ ] **Step 8: Apply normalization in `apps/registrations/services.py`**

Open `apps/registrations/services.py`. Add to the existing imports:

```python
from apps.integrations.name_normalization import normalize_latvian_name
```

In the guardian-merge block (around line 147-160), change:

```python
                        fn = str(person_fields.get("first_name", "")).strip()
                        ln = str(person_fields.get("last_name", "")).strip()
```

to:

```python
                        fn = normalize_latvian_name(person_fields.get("first_name", ""))
                        ln = normalize_latvian_name(person_fields.get("last_name", ""))
```

In the member-merge block (around line 171-184) make the same substitution. Do **not** change the `pid` read.

- [ ] **Step 9: Run the new tests to verify they pass**

Run: `uv run pytest tests/registrations/test_new_app_prefill_from_extraction.py -k normalizes -v`

Expected: PASS.

- [ ] **Step 10: Run the regression-adjacent suites**

Run: `uv run pytest tests/integrations/ tests/registrations/ -q`

Expected: all green. If an older test asserted uppercase prefill or uppercase summary, update its expected value to match the new normalized output (it is documenting the bug, not the desired contract).

- [ ] **Step 11: Commit**

```bash
git add apps/integrations/tasks.py apps/registrations/services.py \
        tests/integrations/test_ocr_tasks.py \
        tests/registrations/test_new_app_prefill_from_extraction.py
git commit -m "feat(ocr): title-case OCR names in summary and prefill, preserve raw payload"
```

---

## Task 3: Personal-data-consent schema

**Files:**
- Modify: `apps/registrations/models.py`
- Create: `apps/registrations/migrations/0007_personal_data_consent.py`
- Test: `tests/registrations/test_personal_data_consent_schema.py`

Two nullable fields plus a module-level version constant. No view, form, or gate behavior in this slice.

- [ ] **Step 1: Write the failing schema test**

```python
# tests/registrations/test_personal_data_consent_schema.py
"""Schema smoke tests for personal-data-consent fields on RegistrationApplication."""

from datetime import datetime, timezone

import pytest

from apps.registrations.models import (
    PERSONAL_DATA_CONSENT_VERSION,
    RegistrationApplication,
)


def test_consent_version_constant_exposed():
    assert isinstance(PERSONAL_DATA_CONSENT_VERSION, str)
    assert PERSONAL_DATA_CONSENT_VERSION  # non-empty


@pytest.mark.django_db
def test_consent_fields_default_to_null():
    app = RegistrationApplication.objects.create(guardian_email="parent@example.com")
    assert app.personal_data_consent_at is None
    assert app.personal_data_consent_version is None


@pytest.mark.django_db
def test_consent_fields_persist_when_set():
    when = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    app = RegistrationApplication.objects.create(
        guardian_email="parent@example.com",
        personal_data_consent_at=when,
        personal_data_consent_version=PERSONAL_DATA_CONSENT_VERSION,
    )
    app.refresh_from_db()
    assert app.personal_data_consent_at == when
    assert app.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/registrations/test_personal_data_consent_schema.py -v`

Expected: `ImportError: cannot import name 'PERSONAL_DATA_CONSENT_VERSION'`.

- [ ] **Step 3: Add the model fields and constant**

In `apps/registrations/models.py`, at module scope after the existing `import` block (before `class RegistrationApplication`), add:

```python
PERSONAL_DATA_CONSENT_VERSION = "v1-2026-05"
"""Current version identifier for the personal-data-consent text.

Bump this string (and ship a new T&C template partial) whenever the consent
content materially changes. The version persisted on
`RegistrationApplication.personal_data_consent_version` records which text
the user agreed to.
"""
```

Inside `class RegistrationApplication`, add the two fields immediately before `submitted_at`:

```python
    # Personal-data-consent (P4 — gate UX lands in slice C)
    personal_data_consent_at = models.DateTimeField(null=True, blank=True)
    personal_data_consent_version = models.CharField(
        max_length=32, null=True, blank=True
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations registrations --name personal_data_consent`

Expected: a new file `apps/registrations/migrations/0007_personal_data_consent.py` containing one `AddField` per new column.

- [ ] **Step 5: Inspect the generated migration**

Open `apps/registrations/migrations/0007_personal_data_consent.py` and confirm:
- It depends on `0006_alter_registrationapplication_preferred_agreement_signing` (or whatever the latest existing migration is).
- It adds `personal_data_consent_at` as `DateTimeField(null=True, blank=True)`.
- It adds `personal_data_consent_version` as `CharField(max_length=32, null=True, blank=True)`.
- No other operations.

If anything else is in there (e.g. the autogenerator mutated an unrelated field because of a stale alter), discard, fix the trigger, and regenerate.

- [ ] **Step 6: Run the schema tests to verify they pass**

Run: `uv run pytest tests/registrations/test_personal_data_consent_schema.py -v`

Expected: all three tests PASS.

- [ ] **Step 7: Run the full registrations suite to confirm no regressions**

Run: `uv run pytest tests/registrations/ -q`

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add apps/registrations/models.py \
        apps/registrations/migrations/0007_personal_data_consent.py \
        tests/registrations/test_personal_data_consent_schema.py
git commit -m "feat(registrations): add personal_data_consent_at/version fields and version constant"
```

---

## Task 4: Cross-cutting parent-UI primitives

**Files:**
- Create: `templates/parent_ui/includes/spinner.html`
- Create: `templates/parent_ui/includes/toast.html`
- Create: `templates/parent_ui/includes/empty_state.html`
- Create: `templates/parent_ui/includes/error_state.html`
- Test: `tests/registrations/test_parent_ui_primitives.py`

The primitives are token-driven (use existing `style-guide/tokens.css` classes / CSS custom properties — do not introduce new tokens). Slice A creates them and validates they render from `{% include %}`; downstream slices will use them in views.

Each partial accepts named parameters via the `{% include ... with ... %}` contract. The tests render an isolated template that includes each partial and asserts the expected DOM structure / Latvian copy.

- [ ] **Step 1: Read one existing partial to match the house style**

Run: `cat templates/parent_ui/includes/alert.html templates/parent_ui/includes/section_card.html`

Expected: small Django templates using existing utility classes from the style guide. The new partials must follow the same shape (root `<div class="…">`, optional Latvian default copy, minimal JS, no inline styles).

- [ ] **Step 2: Write failing primitive-render tests**

```python
# tests/registrations/test_parent_ui_primitives.py
"""Render-smoke tests for the four P4 cross-cutting UI primitives.

Each partial is rendered through an inline template that exercises the
{% include ... with ... %} contract. Tests assert the documented DOM hooks
(class names / data attributes) and the Latvian default copy. Behavior
(auto-dismiss, polling, etc.) lands in later P4 slices.
"""

from django.template import Context, Template


def _render(template_source: str) -> str:
    return Template(template_source).render(Context({}))


def test_spinner_renders_with_default_latvian_label():
    output = _render(
        '{% include "parent_ui/includes/spinner.html" %}'
    )
    assert "Apstrādājam dokumentu" in output
    assert 'role="status"' in output
    assert 'data-spinner' in output


def test_spinner_accepts_custom_label():
    output = _render(
        '{% include "parent_ui/includes/spinner.html" with label="Lūdzu uzgaidiet…" %}'
    )
    assert "Lūdzu uzgaidiet…" in output
    assert "Apstrādājam dokumentu" not in output


def test_toast_renders_message_and_auto_dismiss_hook():
    output = _render(
        '{% include "parent_ui/includes/toast.html" with message="Saglabāts" tone="success" %}'
    )
    assert "Saglabāts" in output
    assert 'data-toast' in output
    assert 'data-toast-tone="success"' in output


def test_toast_defaults_to_neutral_tone_when_unspecified():
    output = _render(
        '{% include "parent_ui/includes/toast.html" with message="Saglabāts" %}'
    )
    assert 'data-toast-tone="neutral"' in output


def test_empty_state_renders_title_and_body():
    output = _render(
        '{% include "parent_ui/includes/empty_state.html" '
        'with title="Nav pieteikumu" body="Sāciet jaunu reģistrāciju." %}'
    )
    assert "Nav pieteikumu" in output
    assert "Sāciet jaunu reģistrāciju." in output
    assert 'data-empty-state' in output


def test_error_state_renders_title_body_and_retry_hook():
    output = _render(
        '{% include "parent_ui/includes/error_state.html" '
        'with title="Radās kļūda" body="Lūdzu, mēģiniet vēlreiz." %}'
    )
    assert "Radās kļūda" in output
    assert "Lūdzu, mēģiniet vēlreiz." in output
    assert 'data-error-state' in output
    assert 'role="alert"' in output
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_parent_ui_primitives.py -v`

Expected: `TemplateDoesNotExist: parent_ui/includes/spinner.html` (and similar for the other three partials).

- [ ] **Step 4: Create `spinner.html`**

```html
{# templates/parent_ui/includes/spinner.html
   Calm branded spinner for async work (e.g. OCR processing).

   Parameters (via {% include ... with ... %}):
     label  — Latvian status text. Defaults to "Apstrādājam dokumentu…".

   Slice A creates the markup; the visibility-aware polling behavior
   that consumes this partial lands in P4 Slice B.
#}
<div class="parent-ui-spinner" role="status" aria-live="polite" data-spinner>
  <span class="parent-ui-spinner__dot" aria-hidden="true"></span>
  <span class="parent-ui-spinner__label">{{ label|default:"Apstrādājam dokumentu…" }}</span>
</div>
```

- [ ] **Step 5: Create `toast.html`**

```html
{# templates/parent_ui/includes/toast.html
   Auto-dismiss confirmation / inline status pill.

   Parameters:
     message — visible text (required by caller; renders empty if omitted).
     tone    — "success" | "warning" | "neutral". Defaults to "neutral".

   The data-toast / data-toast-tone hooks are consumed by a small JS
   controller landing in P4 Slice B (auto-dismiss + dismiss-on-action).
#}
<div
  class="parent-ui-toast parent-ui-toast--{{ tone|default:'neutral' }}"
  role="status"
  aria-live="polite"
  data-toast
  data-toast-tone="{{ tone|default:'neutral' }}"
>
  <span class="parent-ui-toast__message">{{ message|default:'' }}</span>
</div>
```

- [ ] **Step 6: Create `empty_state.html`**

```html
{# templates/parent_ui/includes/empty_state.html
   Shared empty-state primitive for "no items yet" surfaces.

   Parameters:
     title — Latvian heading copy.
     body  — Latvian explanatory copy (optional).
#}
<div class="parent-ui-empty-state" data-empty-state>
  <p class="parent-ui-empty-state__title">{{ title|default:'' }}</p>
  {% if body %}<p class="parent-ui-empty-state__body">{{ body }}</p>{% endif %}
</div>
```

- [ ] **Step 7: Create `error_state.html`**

```html
{# templates/parent_ui/includes/error_state.html
   Shared page-level error-state primitive for "something went wrong"
   surfaces. For per-field validation errors keep using form_field.html;
   for form-summary errors keep using error_summary.html.

   Parameters:
     title — Latvian heading copy.
     body  — Latvian explanatory / next-step copy (optional).
#}
<div class="parent-ui-error-state" role="alert" data-error-state>
  <p class="parent-ui-error-state__title">{{ title|default:'' }}</p>
  {% if body %}<p class="parent-ui-error-state__body">{{ body }}</p>{% endif %}
</div>
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_parent_ui_primitives.py -v`

Expected: all six tests PASS.

- [ ] **Step 9: Commit**

```bash
git add templates/parent_ui/includes/spinner.html \
        templates/parent_ui/includes/toast.html \
        templates/parent_ui/includes/empty_state.html \
        templates/parent_ui/includes/error_state.html \
        tests/registrations/test_parent_ui_primitives.py
git commit -m "feat(parent-ui): add shared spinner, toast, empty-state, and error-state partials"
```

---

## Task 5: Full verification + AGENTS.md note

**Files:**
- Modify: `AGENTS.md` — append a short entry under the existing P3 follow-up notes describing the consent fields and primitives.

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest -q`

Expected: green, with the new tests included. If any pre-existing test breaks, diagnose it against the Slice A changes (most likely culprit: a test that asserts ALL CAPS OCR output in a summary or prefill string).

- [ ] **Step 2: Run lint**

Run: `uv run ruff check .`

Expected: green.

- [ ] **Step 3: Run type check**

Run: `uv run mypy .`

Expected: green.

- [ ] **Step 4: Update AGENTS.md**

Open `AGENTS.md`. Inside the existing "Recent Changes" / status section (after the P3.5 entries), append a short bullet block:

```markdown
### P4 Slice A delivered — foundations
- `apps/integrations/name_normalization.py` — pure Latvian title-case helper applied at OCR consumption boundaries (`apps/integrations/tasks.py` summary builder, `apps/registrations/services.py` prefill reads). Encrypted OCR payload at rest stays raw for audit posture.
- `RegistrationApplication.personal_data_consent_at` + `personal_data_consent_version` fields (migration `0007_personal_data_consent`). Current consent version constant `apps.registrations.models.PERSONAL_DATA_CONSENT_VERSION = "v1-2026-05"`. Gate UX, T&C partial, and view wiring land in P4 Slice C.
- Cross-cutting parent-UI primitives in `templates/parent_ui/includes/`: `spinner.html`, `toast.html`, `empty_state.html`, `error_state.html`. Consumers land in P4 Slices B–E.
```

(Place this block so it reads chronologically after the existing P3.5 / Task 6 follow-up bullets.)

- [ ] **Step 5: Commit the docs update**

```bash
git add AGENTS.md
git commit -m "docs(agents): record P4 Slice A foundations (name normalization, consent schema, UI primitives)"
```

- [ ] **Step 6: Confirm clean working tree**

Run: `git status` and `git log --oneline -6`

Expected: clean tree; the five commits from this slice appear in order.

---

## Self-review checklist (for the implementer, not part of the work)

- Encrypted OCR `payload` is untouched anywhere in this slice. Only `encrypted_summary` and `services.py` prefill reads use `normalize_latvian_name`.
- The new model fields are nullable, blank-allowed, and have no `default=` other than implicit `None`. Existing draft rows therefore migrate cleanly with `null` values, matching the spec's resume-without-rewrite expectation.
- No new design tokens. The four primitives use existing `style-guide/tokens.css` utility classes via `parent-ui-*` BEM-style names that match the existing partials' conventions.
- No view, form, or business-rule changes. Slice A is foundations only — every UX behavior (gate, auto-save, polling, camera capture, mobile layout) lands in later slices.
