# Test Suite Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `tests/` from 18,277 LOC / 807 tests / 153 s to roughly 10–11 k LOC / 600–650 tests / ~100 s, without losing a single covered behaviour, by introducing shared pytest fixtures and removing/merging duplicated visual-contract and field-existence tests.

**Architecture:** Three-pass refactor. Pass 1 introduces shared fixtures in `tests/conftest.py` and a new `tests/registrations/conftest.py` — purely additive, no deletions, full suite must stay green. Pass 2 deletes provably-redundant tests (field-existence, css-link, css-link duplication across slice files) and parametrizes the few worth keeping. Pass 3 migrates the four heaviest view-test files to use the shared fixtures, then folds the tiny RED-phase leftover files into their natural neighbours.

**Tech Stack:** Python 3.12, Django 5.x, pytest-django, uv, postgres test DB. No new test dependencies introduced — `pytest.fixture`, `pytest.mark.parametrize`, and `pytest.mark.django_db` are sufficient.

**Baseline (measured 2026-05-24):**
- 18,277 LOC across 50 files
- 807 tests collected
- 153.03 s wall-clock (`uv run pytest -q`)
- Production code in `apps/` is 4,904 LOC → 3.7× test:prod ratio

**Hard constraints:**
- Every commit ends with `uv run pytest -q && uv run ruff check . && uv run mypy .` green.
- Test counts may go down between commits; covered behaviours may **not**. If a deletion removes the only assertion of a behaviour, that behaviour gets re-asserted in the consolidated test before the deletion is committed.
- No production code under `apps/` is modified by this plan.

---

## File Structure

**New files:**
- `tests/registrations/conftest.py` — registrations-scoped fixtures (verified parent, kit sizes, draft application, draft with documents, sample-file factories).
- `tests/registrations/test_visual_contract.py` — consolidated home for template/CSS-link assertions currently spread across `test_parent_visual_pages.py`, `test_task2_logo_and_css.py`, and the visual half of `test_verified_registration_entry.py`.

**Modified files (additive, Pass 1):**
- `tests/conftest.py` — add cross-app fixtures only (`verified_parent`, `make_parent_client`).

**Deleted files (Pass 2–3):**
- `tests/registrations/test_task2_logo_and_css.py` (folded into `test_visual_contract.py`)
- `tests/registrations/test_parent_visual_pages.py` (folded into `test_visual_contract.py`)
- `tests/registrations/test_personal_data_consent_schema.py` (35 LOC — folded into `test_personal_data_consent_flow.py`)
- `tests/registrations/test_ocr_prefill_vs_suggestion.py` (30 LOC — folded into `test_ocr_source_presentation.py`)
- `tests/registrations/test_p3_remaining_gaps.py` (367 LOC — every assertion either superseded by P3 sign-off coverage or moved to its natural home; see Task 9 for the per-test disposition)

**Significantly rewritten files (Pass 2–3):**
- `tests/registrations/test_registration_form_contract.py` — 1,101 → ~350 LOC. Field-existence test bank collapsed into 2 parametrized tests; submit-required bank collapsed into 1 parametrized test; grouped-fields/section-order kept verbatim.
- `tests/registrations/test_application_workflow.py` — 1,001 → ~500 LOC. Model field-existence tests deleted (migration enforces); shared fixtures replace per-test bootstrap.
- `tests/registrations/test_parent_edit_permissions.py` — 905 → ~550 LOC. Shared fixtures only; behaviour preserved 1:1.
- `tests/registrations/test_admin_review_flow.py` — 948 → ~600 LOC. Shared admin-client and submitted-application fixtures; the 9 view-rendering tests collapsed into 3 parametrized cases.
- `tests/registrations/test_verified_registration_entry.py` — 764 → ~380 LOC. Visual half moves to `test_visual_contract.py`; functional half stays.

**Untouched (already proportional or unique value):**
- All of `tests/accounts/`, `tests/core/`, `tests/documents/`, `tests/integrations/`, `tests/members/`, `tests/scripts/`, `tests/test_settings_env.py`, `tests/test_project_smoke.py`.

---

## Pass 1 — Shared Fixtures (Additive)

### Task 1: Cross-app fixtures in root conftest

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add fixtures without removing any existing tests**

Append to `tests/conftest.py` (keep the existing Django setup and RequestFactory patch unchanged):

```python
# ---------------------------------------------------------------------------
# Shared fixtures — added 2026-05-24 during test-suite consolidation.
# These replace per-test bootstrap repeated across tests/registrations/.
# ---------------------------------------------------------------------------
import pytest
from django.test import Client


@pytest.fixture
def parent_account(db):
    """A fresh ParentAccount with a deterministic email."""
    from apps.accounts.models import ParentAccount

    return ParentAccount.objects.create(email="parent@example.com")


@pytest.fixture
def other_parent_account(db):
    """A second ParentAccount for cross-account isolation tests."""
    from apps.accounts.models import ParentAccount

    return ParentAccount.objects.create(email="other@example.com")


@pytest.fixture
def verified_client(parent_account):
    """A django test Client logged in via magic link as parent_account."""
    from apps.accounts.services import issue_magic_link

    client = Client()
    raw = issue_magic_link(parent_account)
    client.get(f"/accounts/verify/{raw}/")
    return client


@pytest.fixture
def other_verified_client(other_parent_account):
    """A second logged-in Client for cross-account assertions."""
    from apps.accounts.services import issue_magic_link

    client = Client()
    raw = issue_magic_link(other_parent_account)
    client.get(f"/accounts/verify/{raw}/")
    return client


@pytest.fixture
def admin_client(db):
    """A django test Client logged in as a staff superuser."""
    from django.contrib.auth.models import User

    User.objects.create_superuser(
        username="staff", email="staff@example.com", password="pw"
    )
    client = Client()
    client.login(username="staff", password="pw")
    return client
```

- [ ] **Step 2: Run the suite to confirm no regression**

Run: `uv run pytest -q`
Expected: `807 passed`. Fixtures unused yet, so behaviour unchanged.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(conftest): add shared parent/admin client fixtures (no callers yet)"
```

---

### Task 2: Registrations-scoped fixtures

**Files:**
- Create: `tests/registrations/conftest.py`

- [ ] **Step 1: Write the fixtures**

```python
"""Shared fixtures for tests/registrations/.

Centralizes the per-test bootstrap that was repeated 60+ times across
test_application_workflow.py, test_parent_edit_permissions.py, and
test_registration_form_contract.py:
  - magic-link login
  - kit size option creation
  - file uploads for the three required document kinds
  - draft application creation
  - draft + all-documents-uploaded application (ready to submit)
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _png(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name=name, content=_PNG_BYTES, content_type="image/png")


@pytest.fixture
def guardian_identity_file():
    return _png("guardian_id.png")


@pytest.fixture
def member_identity_file():
    return _png("member_id.png")


@pytest.fixture
def member_portrait_file():
    return _png("portrait.png")


@pytest.fixture
def kit_sizes(db):
    """Return (shirt_pk, shorts_pk). Idempotent — safe to use alongside fixtures
    that may have already created the rows."""
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        defaults={"label": "S", "is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        defaults={"label": "S", "is_active": True},
    )
    return shirt.pk, shorts.pk


@pytest.fixture
def submit_payload(kit_sizes, parent_account):
    """A POST payload that passes RegistrationApplicationForm submit validation."""
    shirt_pk, shorts_pk = kit_sizes
    return {
        "guardian_full_name": "Submit Guardian",
        "guardian_personal_id": "010101-12345",
        "guardian_email": parent_account.email,
        "guardian_phone": "+37120000000",
        "guardian_declared_address": "Riga, Brivibas 1",
        "member_full_name": "Submit Child",
        "member_personal_id": "010125-67890",
        "member_birth_date": "2025-01-01",
        "member_same_address_as_guardian": True,
        "member_kit_size_shirt": shirt_pk,
        "member_kit_size_shorts": shorts_pk,
        "preferred_agreement_signing": "paper",
    }


@pytest.fixture
def draft_application(parent_account):
    """A minimal draft application owned by parent_account."""
    from apps.registrations.services import create_or_update_draft

    return create_or_update_draft(
        parent_account=parent_account,
        claimed_email=parent_account.email,
        cleaned_data={"guardian_email": parent_account.email},
    )


@pytest.fixture
def draft_with_documents(
    draft_application,
    guardian_identity_file,
    member_identity_file,
    member_portrait_file,
):
    """draft_application plus the three required documents attached."""
    from apps.documents.models import Document

    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.GUARDIAN_IDENTITY,
        file=guardian_identity_file,
        original_filename=guardian_identity_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.MEMBER_IDENTITY,
        file=member_identity_file,
        original_filename=member_identity_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.MEMBER_PORTRAIT,
        file=member_portrait_file,
        original_filename=member_portrait_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    return draft_application
```

- [ ] **Step 2: Run the suite to confirm no regression**

Run: `uv run pytest -q`
Expected: `807 passed`. Fixtures still unused.

- [ ] **Step 3: Commit**

```bash
git add tests/registrations/conftest.py
git commit -m "test(registrations): add scoped fixtures for parent/draft/document setup"
```

---

## Pass 2 — Delete + Parametrize Bloat

### Task 3: Parametrize form field-existence assertions

**Files:**
- Modify: `tests/registrations/test_registration_form_contract.py` (collapse ~15 field-existence tests + 9 submit-required tests + 4 document-not-application tests + 3 document-kind tests)

- [ ] **Step 1: Read current file to confirm assertion shapes**

Run: `uv run pytest tests/registrations/test_registration_form_contract.py -q --co | head -40`
Expected: see the per-field test names listed at planning time.

- [ ] **Step 2: Replace the four banks with parametrized equivalents**

Find the class containing `test_guardian_full_name_field_exists` through `test_field_sources_json_field_exists` and replace the whole class body with:

```python
class TestRegistrationApplicationFormFields:
    @pytest.mark.parametrize(
        "field_name",
        [
            "guardian_full_name",
            "guardian_personal_id",
            "guardian_declared_address",
            "guardian_email",
            "guardian_phone",
            "member_full_name",
            "member_personal_id",
            "member_birth_date",
            "member_actual_address",
            "member_same_address_as_guardian",
            "member_kit_size_shirt",
            "member_kit_size_shorts",
            "preferred_agreement_signing",
            "support_club_instead_of_multi_child_discount",
            "field_sources",
        ],
    )
    def test_form_exposes_p1_field(self, field_name):
        from apps.registrations.forms import RegistrationApplicationForm

        assert field_name in RegistrationApplicationForm.base_fields
```

Then collapse `test_submit_requires_*` (9 tests) into:

```python
class TestSubmitRequiredFields:
    @pytest.mark.parametrize(
        "field_name",
        [
            "guardian_declared_address",
            "member_full_name",
            "member_kit_size_shirt",
            "member_kit_size_shorts",
            "preferred_agreement_signing",
            "guardian_personal_id",
            "member_birth_date",
            "guardian_identity_document",
            "member_identity_document",
            "member_portrait_document",
        ],
    )
    def test_field_is_in_submit_required(self, field_name):
        from apps.registrations.forms import (
            RegistrationApplicationForm,
            SUBMIT_REQUIRED_FIELDS,
        )

        assert field_name in SUBMIT_REQUIRED_FIELDS
```

(Verify the actual import name for `SUBMIT_REQUIRED_FIELDS` against `apps/registrations/forms.py` before pasting; substitute the real symbol.)

Then collapse `test_*_document_not_application_field` (4 tests) into:

```python
class TestDocumentKindSeparation:
    @pytest.mark.parametrize(
        "field_name",
        [
            "guardian_identity_document",
            "member_identity_document",
            "member_portrait_document",
            "child_identity_document",
        ],
    )
    def test_document_field_is_not_on_application_model(self, field_name):
        from apps.registrations.models import RegistrationApplication

        names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert field_name not in names
```

Then collapse the three `test_document_kind_*_exists` + `test_child_identity_kind_not_present` into:

```python
class TestDocumentKindChoices:
    @pytest.mark.parametrize(
        ("kind_value", "should_exist"),
        [
            ("guardian_identity", True),
            ("member_identity", True),
            ("member_portrait", True),
            ("child_identity", False),
        ],
    )
    def test_document_kind_membership(self, kind_value, should_exist):
        from apps.documents.models import Document

        values = {choice[0] for choice in Document.Kind.choices}
        assert (kind_value in values) is should_exist
```

Leave the rest of the file (grouped_fields / section_order / error_summary / consent / draft-save behaviours) unchanged.

- [ ] **Step 3: Run the file to confirm pass**

Run: `uv run pytest tests/registrations/test_registration_form_contract.py -q`
Expected: green. Test count for the file drops from 64 to ~30.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: green, count drops by ~30.

- [ ] **Step 5: Commit**

```bash
git add tests/registrations/test_registration_form_contract.py
git commit -m "test(form-contract): parametrize field/submit/doc-kind existence assertions"
```

---

### Task 4: Delete model field-existence redundancies in workflow tests

**Files:**
- Modify: `tests/registrations/test_application_workflow.py`

- [ ] **Step 1: Identify the redundant tests**

The first two classes (`TestRegistrationApplicationModel` and `TestDocumentModel`) contain these field-existence tests, all of which are enforced by migration `0001_initial` and later migrations — if a field were missing, every downstream test would already fail:

- `test_has_parent_account_field`
- `test_has_status_field_with_required_choices`
- `test_has_guardian_and_member_fields`
- `test_has_submitted_at_field`
- `test_is_draft_helper_exists`
- `test_is_editable_by_helper_exists`
- `test_has_application_foreign_key`
- `test_has_kind_field_with_guardian_identity`
- `test_has_kind_field_with_member_identity`
- `test_has_kind_field_with_member_portrait`
- `test_has_file_field`
- `test_has_original_filename_field`
- `test_has_content_type_field`
- `test_has_file_size_field`
- `test_has_ocr_status_field`
- `test_has_uploaded_by_parent_at_field`
- `test_has_deleted_at_field`

Keep only `test_model_class_exists` (one importable smoke per model) and delete the rest. The `is_draft_helper_exists` / `is_editable_by_helper_exists` behaviour is already exercised by every test that calls `application.is_draft()` / `is_editable_by()` further down.

- [ ] **Step 2: Apply the deletion**

Edit `tests/registrations/test_application_workflow.py`: keep `TestRegistrationApplicationModel.test_model_class_exists` and `TestDocumentModel.test_model_class_exists`, delete the 17 field-existence tests listed above.

- [ ] **Step 3: Run the file**

Run: `uv run pytest tests/registrations/test_application_workflow.py -q`
Expected: green, file drops from 42 tests to 25.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tests/registrations/test_application_workflow.py
git commit -m "test(workflow): drop model field-existence assertions (covered by migrations + downstream use)"
```

---

### Task 5: Consolidate visual / CSS-link contract into one file

**Files:**
- Create: `tests/registrations/test_visual_contract.py`
- Delete: `tests/registrations/test_parent_visual_pages.py`
- Delete: `tests/registrations/test_task2_logo_and_css.py`
- Modify: `tests/registrations/test_verified_registration_entry.py` (remove its visual half — see Task 6)

- [ ] **Step 1: Inventory unique assertions across the three files**

Run: `grep -E "^    def test_|^def test_" tests/registrations/test_parent_visual_pages.py tests/registrations/test_task2_logo_and_css.py | sort -u | wc -l`
Expected: ~92 tests.

The deduplicated set is roughly:
- Asset linking on the base template (Google fonts preconnect, tokens.css, parent_theme.css, parent_pages.css, parent-pages absolute paths).
- Page-level shell hooks (`fk-parent-page`, `fk-site-header`, `fk-cesis-logo` path, navy background + red border) on the **register**, **verify**, and **portal** pages.
- Include-template existence (`hero_card.html`, `section_card.html`, `status_badge.html`, `alert.html`, `error_summary.html`, `header.html`, `base_parent_page.html`).
- Page-level structural rules (no duplicated `<doctype>` / `<html>` / `<body>` in base parent page; exactly one hero card per landing page).
- Latvian copy hooks (`Bērna reģistrācija`, `Mani pieteikumi`, `Pārskatiet un turpiniet`, `Droša piekļuve`, `Turpat`, `Skatīt ieteikumu`).

- [ ] **Step 2: Write the consolidated file**

```python
"""Consolidated visual / template contract for parent pages.

Merges the previous test_parent_visual_pages.py + test_task2_logo_and_css.py
+ the visual half of test_verified_registration_entry.py.

These tests pin user-visible contract only: stable hooks (class names, copy
strings, asset paths). They deliberately do NOT assert DOM nesting depth or
pixel layout — those belong in a future visual-regression harness.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db


ASSET_LINKS = [
    "tokens.css",
    "parent_theme.css",
    "parent_pages.css",
]

PARENT_PAGE_PATHS = [
    "/register/",
    "/accounts/verify/",  # via pending_email session flow — see helper
    "/portal/",
]


class TestBaseTemplateAssets:
    @pytest.mark.parametrize("asset", ASSET_LINKS)
    def test_base_template_links_asset(self, client, asset):
        resp = client.get("/register/")
        assert asset in resp.content.decode()

    def test_base_template_uses_google_fonts_preconnect(self, client):
        resp = client.get("/register/")
        assert "preconnect" in resp.content.decode()


class TestParentShellHooksOnLandingPages:
    @pytest.mark.parametrize(
        ("path", "needs_pending_email"),
        [
            ("/register/", False),
            ("/portal/", False),
        ],
    )
    @pytest.mark.parametrize("hook", ["fk-parent-page", "fk-site-header"])
    def test_landing_page_has_shell_hook(
        self, verified_client, path, needs_pending_email, hook
    ):
        resp = verified_client.get(path)
        assert hook in resp.content.decode()

    def test_register_page_has_fk_cesis_logo(self, client):
        resp = client.get("/register/")
        assert "fk-cesis-logo" in resp.content.decode()
        assert "img/logo.png" not in resp.content.decode()  # stale path guard


class TestIncludeTemplatesExist:
    @pytest.mark.parametrize(
        "include_path",
        [
            "apps/registrations/templates/parent_ui/base_parent_page.html",
            "apps/registrations/templates/parent_ui/includes/header.html",
            "apps/registrations/templates/parent_ui/includes/hero_card.html",
            "apps/registrations/templates/parent_ui/includes/section_card.html",
            "apps/registrations/templates/parent_ui/includes/status_badge.html",
            "apps/registrations/templates/parent_ui/includes/alert.html",
            "apps/registrations/templates/parent_ui/includes/error_summary.html",
        ],
    )
    def test_include_template_exists(self, include_path):
        assert Path(include_path).exists(), f"missing template: {include_path}"


class TestPortalCopy:
    def test_portal_shows_mani_pieteikumi_eyebrow(self, verified_client):
        resp = verified_client.get("/portal/")
        assert "Mani pieteikumi" in resp.content.decode()

    def test_portal_empty_state(self, verified_client):
        resp = verified_client.get("/portal/")
        # No applications yet → empty-state copy
        body = resp.content.decode()
        assert "Sākt jaunu" in body or "Sākt jauno" in body  # match actual copy

    def test_portal_card_for_draft_shows_turpat(
        self, verified_client, draft_application
    ):
        resp = verified_client.get("/portal/")
        assert "Turpat" in resp.content.decode()
```

(The exact Latvian copy strings must be checked against current templates before paste; adjust to match.)

- [ ] **Step 3: Delete the old visual files**

```bash
git rm tests/registrations/test_parent_visual_pages.py tests/registrations/test_task2_logo_and_css.py
```

- [ ] **Step 4: Run the new file**

Run: `uv run pytest tests/registrations/test_visual_contract.py -q`
Expected: green. Roughly 15–25 tests in the new file vs 92 deleted.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: green. Net test count drops by ~65–75; LOC drops by ~1,400.

- [ ] **Step 6: Commit**

```bash
git add tests/registrations/test_visual_contract.py
git commit -m "test(visual): consolidate parent-page visual contract into one file"
```

---

### Task 6: Split visual half out of verified-registration-entry

**Files:**
- Modify: `tests/registrations/test_verified_registration_entry.py`
- Modify: `tests/registrations/test_visual_contract.py` (absorb anything unique)

- [ ] **Step 1: Identify the visual half**

In `test_verified_registration_entry.py` these tests are pure visual contract and overlap with Task 5:
- `test_register_page_has_fk_parent_page_shell`
- `test_register_page_has_fk_site_header`
- `test_register_page_links_google_fonts`
- `test_register_page_links_parent_theme_css`
- `test_register_page_links_parent_pages_css`
- `test_register_page_still_has_email_input`  (move to functional-half — it asserts an input element, not visuals)
- `test_register_page_still_has_drosa_piekluve_text`
- `test_register_page_still_has_epasts_label`
- `test_verify_page_has_fk_parent_page_shell`
- `test_verify_page_has_fk_site_header`
- `test_verify_page_links_google_fonts`
- `test_verify_page_links_parent_theme_css`
- `test_verify_page_links_parent_pages_css`
- `test_verify_page_has_secure_verification_framing`
- `test_verify_page_has_code_form_label`
- `test_verify_page_has_submit_button`

Plus two `test_get_register_returns_200` duplicates — keep one.

- [ ] **Step 2: Remove the visual-half tests, keep the functional flow tests**

Delete the listed tests above from `test_verified_registration_entry.py`. Keep:
- All `post_register_*` flow tests
- All `verify_page_requires_pending_email` / `verify_page_shows_pending_email` / wrong-code / empty-code tests
- `test_session_established_after_verify`
- `test_typed_email_grants_no_access`
- `test_verify_account_a_does_not_expose_account_b_registrations`
- `test_single_use_code_*` / `test_expired_code_rejected` / `test_rate_limit_rejection`
- `test_full_flow_register_verify_portal`

- [ ] **Step 3: Run the file**

Run: `uv run pytest tests/registrations/test_verified_registration_entry.py -q`
Expected: green, ~25 tests (down from 53), file LOC roughly 380.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add tests/registrations/test_verified_registration_entry.py
git commit -m "test(verified-entry): drop visual-contract half (now in test_visual_contract.py)"
```

---

### Task 7: Parametrize admin review view-rendering tests

**Files:**
- Modify: `tests/registrations/test_admin_review_flow.py`

- [ ] **Step 1: Collapse the detail-page button tests**

Currently `TestStaffReviewDetailPage` has separate tests for `request_fix_button`, `reject_button`, `approve_button`, `document_preview_link`, `child_name`. Replace with:

```python
class TestStaffReviewDetailPage:
    @pytest.mark.parametrize(
        "expected_marker",
        [
            "request_fix",          # button name attr
            "reject",
            "approve",
            "Document",             # preview link label root
        ],
    )
    def test_detail_page_renders_marker(
        self, admin_client, submitted_application, expected_marker
    ):
        resp = admin_client.get(
            f"/admin/registrations/registrationapplication/{submitted_application.pk}/review/"
        )
        assert expected_marker in resp.content.decode()

    def test_detail_page_shows_child_name(
        self, admin_client, submitted_application
    ):
        resp = admin_client.get(
            f"/admin/registrations/registrationapplication/{submitted_application.pk}/review/"
        )
        assert submitted_application.member_full_name in resp.content.decode()
```

(Add a `submitted_application` fixture to `tests/registrations/conftest.py` before this task — it should call `submit_application(draft_with_documents, parent_account)`. Wire that fixture in Step 0 of this task.)

- [ ] **Step 0 (do this first): Add `submitted_application` fixture**

Edit `tests/registrations/conftest.py`, append:

```python
@pytest.fixture
def submitted_application(draft_with_documents, parent_account, submit_payload):
    from apps.registrations.services import submit_application

    return submit_application(
        application=draft_with_documents,
        parent_account=parent_account,
        cleaned_data=submit_payload,
    )
```

(Adjust to match `submit_application`'s real signature — confirm in `apps/registrations/services.py` before paste.)

- [ ] **Step 2: Run the file**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: green, 24 → ~16 tests, ~948 → ~600 LOC.

- [ ] **Step 3: Run the suite + commit**

```bash
uv run pytest -q
git add tests/registrations/conftest.py tests/registrations/test_admin_review_flow.py
git commit -m "test(admin-review): parametrize detail-page markers + use submitted_application fixture"
```

---

## Pass 3 — Migrate Heavy Files to Fixtures

### Task 8: Migrate parent-edit-permissions to shared fixtures

**Files:**
- Modify: `tests/registrations/test_parent_edit_permissions.py`

- [ ] **Step 1: Replace local helpers with fixture calls**

In `test_parent_edit_permissions.py`:
- Delete the local `_login_via_magic_link`, `_make_member_identity_file`, `_make_guardian_identity_file`, `_ensure_kit_sizes` helpers.
- Replace each test's `client = Client(); _login_via_magic_link(client, account)` setup with the `verified_client` fixture.
- Replace cross-parent setup with `other_verified_client`.
- Replace draft setup with `draft_application` / `draft_with_documents`.

Sample diff for one test:

Before:
```python
def test_owner_can_open_draft_edit_page(self):
    account = ParentAccount.objects.create(email="p@example.com")
    client = Client()
    _login_via_magic_link(client, account)
    draft = create_or_update_draft(
        parent_account=account,
        claimed_email="p@example.com",
        cleaned_data={"guardian_email": "p@example.com"},
    )
    resp = client.get(f"/applications/{draft.id}/")
    assert resp.status_code == 200
```

After:
```python
def test_owner_can_open_draft_edit_page(self, verified_client, draft_application):
    resp = verified_client.get(f"/applications/{draft_application.id}/")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run the file**

Run: `uv run pytest tests/registrations/test_parent_edit_permissions.py -q`
Expected: green, file LOC drops from 905 to ~550, test count unchanged.

- [ ] **Step 3: Run the suite + commit**

```bash
uv run pytest -q
git add tests/registrations/test_parent_edit_permissions.py
git commit -m "test(parent-edit): migrate to shared fixtures"
```

---

### Task 9: Migrate application-workflow to shared fixtures

**Files:**
- Modify: `tests/registrations/test_application_workflow.py`

- [ ] **Step 1: Replace helpers**

Same pattern as Task 8 — drop local `_login_via_magic_link` / `_make_*_file` / `_ensure_kit_sizes` / `_submit_form_data`. Wire fixtures (`verified_client`, `draft_application`, `draft_with_documents`, `submit_payload`, `kit_sizes`).

- [ ] **Step 2: Run the file**

Run: `uv run pytest tests/registrations/test_application_workflow.py -q`
Expected: green, file LOC drops from 1,001 (post-Task-4) to ~500.

- [ ] **Step 3: Run the suite + commit**

```bash
uv run pytest -q
git add tests/registrations/test_application_workflow.py
git commit -m "test(workflow): migrate to shared fixtures"
```

---

### Task 10: Fold the tiny RED-phase leftover files

**Files:**
- Modify: `tests/registrations/test_personal_data_consent_flow.py`
- Delete: `tests/registrations/test_personal_data_consent_schema.py`
- Modify: `tests/registrations/test_ocr_source_presentation.py`
- Delete: `tests/registrations/test_ocr_prefill_vs_suggestion.py`
- Inspect, then either delete or redistribute: `tests/registrations/test_p3_remaining_gaps.py`

- [ ] **Step 1: Fold consent schema into consent flow**

Read both files. Move every test from `test_personal_data_consent_schema.py` into `test_personal_data_consent_flow.py` (probably as a `TestSchema` class at the top). Delete the schema file with `git rm`.

- [ ] **Step 2: Fold OCR prefill-vs-suggestion into source presentation**

Same pattern — `test_ocr_prefill_vs_suggestion.py` is 30 LOC. Move its tests into `test_ocr_source_presentation.py` and delete the source file.

- [ ] **Step 3: Disposition `test_p3_remaining_gaps.py`**

Run: `uv run pytest tests/registrations/test_p3_remaining_gaps.py -v --co`

For each listed test:
- If it duplicates an assertion already in `test_async_document_upload.py`, `test_workspace_auto_save.py`, or `test_workspace_ocr_decryption.py` → delete.
- If it asserts a still-unique behaviour → move to the natural home file.
- If you cannot find a natural home → keep the test but rename the file to `test_p3_gaps.py` (drop the "remaining" — P3 is signed off).

Do not skip this analysis. Each test must be either deleted, moved, or explicitly retained with a comment explaining why.

- [ ] **Step 4: Run the suite + commit**

```bash
uv run pytest -q
git add -A tests/registrations/
git commit -m "test(registrations): fold tiny RED-phase files into natural homes"
```

---

## Final Verification

### Task 11: Measure and document

- [ ] **Step 1: Re-run measurements**

```bash
wc -l tests/conftest.py tests/**/*.py tests/*.py 2>/dev/null | tail -1
uv run pytest --collect-only -q 2>&1 | tail -3
time uv run pytest -q
uv run ruff check .
uv run mypy .
```

- [ ] **Step 2: Update AGENTS.md**

Append a one-line entry under the appropriate "delivered" section recording:
- new LOC total
- new test count
- new runtime
- pointer to `tests/conftest.py` + `tests/registrations/conftest.py` as the canonical fixture homes for future tests

- [ ] **Step 3: Final commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): record test-suite consolidation measurements + fixture homes"
```

---

## Risk register

| Risk | Mitigation |
|---|---|
| A "redundant" test was actually the only one covering a behaviour | Each Task runs the full suite immediately. A behaviour loss surfaces as a new failure elsewhere or as zero coverage in the consolidated file's parametrize list. |
| Fixtures change subtle behaviour (e.g. session keys differ from local helper) | Pass 1 lands fixtures without callers — if they're wrong, the suite stays green by accident and we discover this in Pass 3. Mitigation: Pass 3 migrates **one file per commit**, full suite green before next file. |
| Visual-contract consolidation loses a Latvian copy hook | Task 5 Step 1 lists the deduplicated set explicitly; substituted only after `grep`-verifying the exact strings against current templates. |
| `test_p3_remaining_gaps.py` test is genuinely unique and missed | Task 10 Step 3 forbids skipping — each test gets a disposition decision. |
| Auto-save / OCR async work in flight on `main` collides with these edits | Plan develops on `main` per project convention. Keep commits small; if `git pull` brings conflicts, resolve per-commit rather than batch. |

## Out of scope (intentional)

- Splitting tests by layer (unit / integration / visual) — that was Option C; rejected for this round.
- Touching `tests/accounts/`, `tests/documents/`, `tests/integrations/`, `tests/members/`. They are proportional to their app sizes; revisit only if Pass 1 fixtures suggest cross-app cleanup.
- Replacing `pytest-django` DB fixtures with `pytest.mark.django_db(transaction=False)` performance tweaks. Worth doing separately and measurable on its own.
- Adding visual-regression tooling (Playwright snapshots). Out of MVP scope.
