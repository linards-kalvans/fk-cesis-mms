# Canonical Guardian Identity — Slice B1 (read-through) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `RegistrationApplication` read guardian data through the canonical `Guardian` row (and the verified email through `ParentAccount`), so editing a guardian's profile propagates to every application and agreement — without yet dropping the denormalized `guardian_*` columns.

**Architecture:** Expand/contract, expand phase. Add five guardian-read accessors (model properties) that **prefer** `application.guardian.*` / `application.parent_account.email` and **fall back** to the existing `guardian_*` columns when the Guardian profile is empty or unlinked. Populate the Guardian profile at *draft-save* time (today it is only populated at approval). Repoint every read site — templates, the workspace `initial` dict, prefill, the submit phone-sync, and the review-notification — to the accessors, and drop the now-redundant snapshot-copy block in `approve_application`. The columns stay (dual-written) so no `RegistrationApplication.objects.create(guardian_*=...)` fixture breaks. **Slice B2** stops the dual-write, drops the columns, simplifies the accessors, and sweeps the test fixtures.

**Tech Stack:** Python 3.12 / Django 5.x, pytest + pytest-django, uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-06-09-p6-canonical-guardian-identity-design.md` (§2 read-through, §4 data model, §7 read surface). Slice A delivered the `Guardian.parent_account` OneToOne, the `RegistrationApplication.guardian` FK, `resolve_guardian_for_account`, resolution at initiation, and approval-reuse.

---

## Background the implementer needs

- `RegistrationApplication` (in `apps/registrations/models.py`) has nullable `guardian` (FK → `members.Guardian`) and nullable `parent_account` (FK → `accounts.ParentAccount`). It also still has five denormalized columns: `guardian_full_name`, `guardian_personal_id`, `guardian_email` (NOT NULL `EmailField`), `guardian_phone`, `guardian_declared_address`.
- `Guardian` has `full_name`, `personal_id`, `email`, `phone`, `address`, and `parent_account` (OneToOne). `ParentAccount.email` is the verified email (unique).
- **Today the Guardian profile is only populated at approval** (`approve_application` copies the snapshot onto the Guardian). Drafts carry guardian data only in the columns; their Guardian row is an email-only stub. Task 2 fixes this by populating the Guardian at draft-save.
- The registration form (`apps/registrations/forms.py`) is a plain `forms.Form`; its `guardian_*` fields are form fields (not model fields) and **keep their names** in B1 and B2 — POST-dict keys, `field_sources` JSON keys, the OCR-response JSON keys, and the address-sync JS DOM ids all stay valid. Do not rename form fields.
- Already correctly sourced (no change in this slice): `apps/integrations/docuseal.py`, `apps/agreements/services.py`, `apps/integrations/invoice_ninja.py` (they read `member.guardian.*` directly); the six `emails/agreements/*` + the OCR `encrypted_summary` builder.

## File Structure

- **Modify** `apps/registrations/models.py` — add 5 guardian-read accessor properties; (`__str__` stays on the column this slice — B2 changes it).
- **Modify** `apps/registrations/services.py` — populate Guardian at draft-save (`create_or_update_draft`); repoint `get_application_prefill`, `submit_application` phone-sync, `_render_and_send_notification`; remove the approval snapshot-copy block.
- **Modify** `apps/registrations/views.py` — workspace `initial` dict reads via accessors.
- **Modify** templates: `templates/registrations/admin_review_detail.html`, `parent_portal.html`, `admin_review_queue.html`, `application_workspace.html`.
- **Test** `tests/registrations/test_guardian_read_through.py` (new) — accessors, draft-save population, propagation, approval-keeps-profile.

---

## Task 1: Guardian-read accessors on `RegistrationApplication`

**Files:**
- Modify: `apps/registrations/models.py` (add properties to `RegistrationApplication`, after `__str__`)
- Test: `tests/registrations/test_guardian_read_through.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/registrations/test_guardian_read_through.py`:

```python
"""Slice B1 — guardian-read accessors prefer the canonical Guardian / ParentAccount,
falling back to the denormalized columns (which still exist in B1)."""

from __future__ import annotations

import pytest

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def test_accessors_prefer_guardian_when_profile_populated():
    account = ParentAccount.objects.create(email="acct@example.com")
    guardian = Guardian.objects.create(
        parent_account=account,
        full_name="Guardian Row",
        personal_id="010101-22222",
        phone="+37120000000",
        address="Guardian Address 1",
        email="acct@example.com",
    )
    app = RegistrationApplication.objects.create(
        parent_account=account,
        guardian=guardian,
        guardian_email="stale@example.com",
        guardian_full_name="Stale Column Name",
        guardian_personal_id="999999-99999",
        guardian_phone="+37100000000",
        guardian_declared_address="Stale Column Address",
    )
    assert app.guardian_name == "Guardian Row"
    assert app.guardian_pid == "010101-22222"
    assert app.guardian_contact_phone == "+37120000000"
    assert app.guardian_address == "Guardian Address 1"
    # Verified email is sourced from ParentAccount, never the column.
    assert app.guardian_contact_email == "acct@example.com"


def test_accessors_fall_back_to_columns_when_guardian_profile_empty():
    # No guardian link, no parent_account — only the columns carry data.
    app = RegistrationApplication.objects.create(
        guardian_email="col@example.com",
        guardian_full_name="Column Name",
        guardian_personal_id="010101-33333",
        guardian_phone="+37111111111",
        guardian_declared_address="Column Address",
    )
    assert app.guardian_name == "Column Name"
    assert app.guardian_pid == "010101-33333"
    assert app.guardian_contact_phone == "+37111111111"
    assert app.guardian_address == "Column Address"
    assert app.guardian_contact_email == "col@example.com"


def test_email_accessor_prefers_parent_account_over_column():
    account = ParentAccount.objects.create(email="verified@example.com")
    app = RegistrationApplication.objects.create(
        parent_account=account, guardian_email="old-column@example.com"
    )
    assert app.guardian_contact_email == "verified@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py -v`
Expected: FAIL — `AttributeError: 'RegistrationApplication' object has no attribute 'guardian_name'`.

- [ ] **Step 3: Add the accessors**

In `apps/registrations/models.py`, add these properties to `RegistrationApplication` immediately after the `__str__` method (the class currently ends there). The fallback to the column is a Slice-B1 transitional concession; Slice B2 removes the `or self.guardian_*` halves once the columns are dropped.

```python
    # --- Guardian-read accessors (Slice B1). Prefer the canonical Guardian /
    # ParentAccount; fall back to the denormalized columns while they still
    # exist. Slice B2 drops the columns and the fallback halves. ---
    @property
    def guardian_name(self) -> str:
        if self.guardian_id is not None and self.guardian.full_name:
            return self.guardian.full_name
        return self.guardian_full_name

    @property
    def guardian_pid(self) -> str:
        if self.guardian_id is not None and self.guardian.personal_id:
            return self.guardian.personal_id
        return self.guardian_personal_id

    @property
    def guardian_contact_phone(self) -> str:
        if self.guardian_id is not None and self.guardian.phone:
            return self.guardian.phone
        return self.guardian_phone

    @property
    def guardian_address(self) -> str:
        if self.guardian_id is not None and self.guardian.address:
            return self.guardian.address
        return self.guardian_declared_address

    @property
    def guardian_contact_email(self) -> str:
        if self.parent_account_id is not None and self.parent_account.email:
            return self.parent_account.email
        return self.guardian_email
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + type-check the file**

Run: `uv run ruff check apps/registrations/models.py && uv run mypy apps/registrations/models.py`
Expected: clean (the `-> str` return annotations satisfy mypy; the model attrs are typed `str`).

- [ ] **Step 6: Commit**

```bash
git add apps/registrations/models.py tests/registrations/test_guardian_read_through.py
git commit -m "feat(registrations): guardian-read accessors with column fallback (P6 Slice B1)"
```

---

## Task 2: Populate the Guardian profile at draft-save

**Files:**
- Modify: `apps/registrations/services.py` (`create_or_update_draft`, after the snapshot-column writes near line 407)
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_draft_save_populates_the_guardian_profile():
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="draft@example.com")
    app = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Anna Bērziņa",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000001",
            "guardian_declared_address": "Rīga, Brīvības 1",
        },
        files={},
        verified_account=account,
    )
    guardian = Guardian.objects.get(parent_account=account)
    assert guardian.full_name == "Anna Bērziņa"
    assert guardian.personal_id == "010101-12345"
    assert guardian.phone == "+37120000001"
    assert guardian.address == "Rīga, Brīvības 1"


def test_editing_guardian_on_second_app_propagates_to_first():
    """The propagation guarantee: two apps share one Guardian; editing guardian
    data on the second is visible through the first app's accessors."""
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="prop@example.com")
    app1 = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Old Name",
              "guardian_phone": "+37120000000", "guardian_declared_address": "Addr 1",
              "guardian_personal_id": "010101-11111"},
        files={}, verified_account=account,
    )
    create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "New Name",
              "guardian_phone": "+37120000000", "guardian_declared_address": "Addr 1",
              "guardian_personal_id": "010101-11111"},
        files={}, verified_account=account,
    )
    app1.refresh_from_db()
    assert app1.guardian_name == "New Name"  # read-through sees the shared edit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_draft_save_populates_the_guardian_profile tests/registrations/test_guardian_read_through.py::test_editing_guardian_on_second_app_propagates_to_first -v`
Expected: FAIL — the Guardian profile is still empty after draft save (`assert '' == 'Anna Bērziņa'`).

- [ ] **Step 3: Populate the Guardian at draft-save**

In `apps/registrations/services.py`, the five snapshot writes are (lines ~403-407):

```python
    application.guardian_full_name = str(data.get("guardian_full_name", "")).strip()
    application.guardian_personal_id = str(data.get("guardian_personal_id", "")).strip()
    application.guardian_email = email
    application.guardian_phone = str(data.get("guardian_phone", "")).strip()
    application.guardian_declared_address = str(data.get("guardian_declared_address", "")).strip()
```

Leave those lines in place (B1 keeps the dual-write). Immediately **after** them, add a write to the canonical Guardian:

```python
    # Slice B1: the Guardian profile is now the read source, so populate it at
    # draft-save (was previously only set at approval). Latest write wins;
    # field-locking is Slice C. Email stays sourced from ParentAccount.
    if application.guardian_id is not None:
        _guardian = application.guardian
        _guardian.full_name = application.guardian_full_name
        _guardian.personal_id = application.guardian_personal_id
        _guardian.phone = application.guardian_phone
        _guardian.address = application.guardian_declared_address
        _guardian.save(update_fields=["full_name", "personal_id", "phone", "address"])
```

Note: `application.guardian` is set earlier in this function (the `verified_account is not None` block calls `resolve_guardian_for_account`). The `guardian_id is not None` guard covers the no-verified-account path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/services.py tests/registrations/test_guardian_read_through.py
git commit -m "feat(registrations): populate Guardian profile at draft-save (P6 Slice B1)"
```

---

## Task 3: Repoint templates to the accessors

**Files:**
- Modify: `templates/registrations/admin_review_detail.html` (lines ~32-36)
- Modify: `templates/registrations/parent_portal.html` (line ~25)
- Modify: `templates/registrations/admin_review_queue.html` (line ~29)
- Modify: `templates/registrations/application_workspace.html` (line ~211, the read-only email display)
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing test (propagation visible in admin render)**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_admin_review_detail_renders_guardian_via_read_through(client, django_user_model):
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="render@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Render Name",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Render Addr"},
        files={}, verified_account=account,
    )
    # Simulate a later shared-Guardian edit that the column on THIS app never saw.
    guardian = Guardian.objects.get(parent_account=account)
    guardian.full_name = "Edited Shared Name"
    guardian.save(update_fields=["full_name"])

    staff = django_user_model.objects.create_user(
        username="staff-rt", password="pw", is_staff=True, is_superuser=True
    )
    client.force_login(staff)
    resp = client.get(f"/admin/review/applications/{app.id}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Edited Shared Name" in body          # read-through wins
    assert "Render Name" not in body             # the stale column value is not shown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_admin_review_detail_renders_guardian_via_read_through -v`
Expected: FAIL — body still contains "Render Name" (template reads the column `application.guardian_full_name`).

- [ ] **Step 3: Repoint the templates**

In `templates/registrations/admin_review_detail.html`, replace the five guardian lines (~32-36):

```
{{ application.guardian_full_name }}
{{ application.guardian_personal_id }}
{{ application.guardian_email }}
{{ application.guardian_phone }}
{{ application.guardian_declared_address }}
```

with:

```
{{ application.guardian_name }}
{{ application.guardian_pid }}
{{ application.guardian_contact_email }}
{{ application.guardian_contact_phone }}
{{ application.guardian_address }}
```

In `templates/registrations/parent_portal.html` (~line 25), replace `{{ app.guardian_full_name }}` with `{{ app.guardian_name }}`.

In `templates/registrations/admin_review_queue.html` (~line 29), replace `{{ application.guardian_full_name|default:"—" }}` with `{{ application.guardian_name|default:"—" }}`.

In `templates/registrations/application_workspace.html` (~line 211), replace the read-only email display `{{ application.guardian_email }}` with `{{ application.guardian_contact_email }}`.

Do **not** touch the address-sync `<script>` blocks (`id_guardian_declared_address`) — those reference the form input id, which is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_admin_review_detail_renders_guardian_via_read_through -v`
Expected: PASS.

- [ ] **Step 5: Run the admin/portal render suites for regressions**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py tests/registrations/test_portal_polish.py tests/registrations/test_parent_surface_copy_contract.py tests/registrations/test_admin_inline_preview.py -q`
Expected: PASS (these build apps via `create_or_update_draft`, so the Guardian is populated and the accessors render correctly).

- [ ] **Step 6: Commit**

```bash
git add templates/registrations/ tests/registrations/test_guardian_read_through.py
git commit -m "feat(registrations): templates read guardian via accessors (P6 Slice B1)"
```

---

## Task 4: Repoint the workspace `initial` dict + service reads

**Files:**
- Modify: `apps/registrations/views.py` (workspace `initial` dict, lines ~270-274)
- Modify: `apps/registrations/services.py` — `get_application_prefill` (~124-126), `submit_application` phone-sync (~618-622), `_render_and_send_notification` (~796, ~808)
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_prefill_uses_guardian_profile_for_returning_parent():
    from apps.registrations.services import create_or_update_draft, get_application_prefill

    account = ParentAccount.objects.create(email="prefill@example.com")
    create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Prefill Guardian",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Prefill Addr"},
        files={}, verified_account=account,
    )
    # Edit the shared Guardian directly; prefill must reflect it, not a stale column.
    guardian = Guardian.objects.get(parent_account=account)
    guardian.full_name = "Updated Guardian"
    guardian.save(update_fields=["full_name"])

    prefill = get_application_prefill(account)
    assert prefill["guardian_full_name"] == "Updated Guardian"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_prefill_uses_guardian_profile_for_returning_parent -v`
Expected: FAIL — prefill returns "Prefill Guardian" (reads `latest.guardian_full_name` column).

- [ ] **Step 3a: Repoint `get_application_prefill`**

In `apps/registrations/services.py`, the prefill block (~120-127) currently reads:

```python
    if latest is not None:
        prefill.update(
            {
                "guardian_full_name": latest.guardian_full_name,
                "guardian_personal_id": latest.guardian_personal_id,
                "guardian_declared_address": latest.guardian_declared_address,
            }
        )
```

Replace the dict values with the accessors (null-safe — the accessor handles a missing Guardian):

```python
    if latest is not None:
        prefill.update(
            {
                "guardian_full_name": latest.guardian_name,
                "guardian_personal_id": latest.guardian_pid,
                "guardian_declared_address": latest.guardian_address,
            }
        )
```

- [ ] **Step 3b: Repoint the `submit_application` phone-sync**

The phone-sync block (~616-620) currently reads:

```python
    if application.parent_account_id is not None and application.guardian_phone:
        account = application.parent_account
        if account.phone != application.guardian_phone:
            account.phone = application.guardian_phone
            account.save(update_fields=["phone", "updated_at"])
```

Replace the three `application.guardian_phone` reads with the accessor:

```python
    if application.parent_account_id is not None and application.guardian_contact_phone:
        account = application.parent_account
        if account.phone != application.guardian_contact_phone:
            account.phone = application.guardian_contact_phone
            account.save(update_fields=["phone", "updated_at"])
```

- [ ] **Step 3c: Repoint `_render_and_send_notification`**

In `_render_and_send_notification` (~796 and ~808), replace:

```python
        "guardian_full_name": application.guardian_full_name,
```
with
```python
        "guardian_full_name": application.guardian_name,
```

and the recipient line:

```python
        recipient_list=[application.guardian_email],
```
with
```python
        recipient_list=[application.guardian_contact_email],
```

- [ ] **Step 3d: Repoint the workspace `initial` dict**

In `apps/registrations/views.py` (~270-274) replace:

```python
                "guardian_full_name": application.guardian_full_name,
                "guardian_personal_id": application.guardian_personal_id,
                "guardian_email": application.guardian_email,
                "guardian_phone": application.guardian_phone,
                "guardian_declared_address": application.guardian_declared_address,
```

with:

```python
                "guardian_full_name": application.guardian_name,
                "guardian_personal_id": application.guardian_pid,
                "guardian_email": application.guardian_contact_email,
                "guardian_phone": application.guardian_contact_phone,
                "guardian_declared_address": application.guardian_address,
```

- [ ] **Step 4: Run tests to verify pass + no regressions**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py tests/registrations/test_review_action_emails.py tests/registrations/test_parent_ocr_prefill_flow.py tests/registrations/test_new_app_prefill_from_extraction.py tests/registrations/test_parent_application_workspace.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/views.py apps/registrations/services.py tests/registrations/test_guardian_read_through.py
git commit -m "feat(registrations): views/services read guardian via accessors (P6 Slice B1)"
```

---

## Task 5: Drop the approval snapshot-copy block

**Files:**
- Modify: `apps/registrations/services.py` (`approve_application`, the profile-refresh block ~738-744)
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_approval_does_not_overwrite_guardian_from_stale_columns(django_user_model):
    """Guardian profile is set at draft-save; approval must not clobber it from
    the application's (now-secondary) snapshot columns."""
    from apps.registrations.services import create_or_update_draft, submit_application, approve_application
    from apps.members.models import KitSizeOption
    from apps.documents.models import Document
    from django.core.files.uploadedfile import SimpleUploadedFile

    shirt = KitSizeOption.objects.get_or_create(kind=KitSizeOption.Kind.SHIRT, label="S", defaults={"is_active": True})[0]
    shorts = KitSizeOption.objects.get_or_create(kind=KitSizeOption.Kind.SHORTS, label="S", defaults={"is_active": True})[0]
    account = ParentAccount.objects.create(email="approve@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Draft Guardian",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Addr", "member_full_name": "Child",
              "member_personal_id": "010125-67890", "member_birth_date": "2015-01-01",
              "member_same_address_as_guardian": True, "member_kit_size_shirt": shirt.pk,
              "member_kit_size_shorts": shorts.pk, "preferred_agreement_signing": "paper"},
        files={}, verified_account=account,
    )
    for kind in (Document.Kind.GUARDIAN_IDENTITY, Document.Kind.MEMBER_IDENTITY, Document.Kind.MEMBER_PORTRAIT):
        Document.objects.create(application=app, kind=kind,
            file=SimpleUploadedFile(f"{kind}.png", b"x", content_type="image/png"),
            original_filename=f"{kind}.png", content_type="image/png", file_size=1)
    submit_application(app, account)

    # Corrupt the snapshot columns directly; the Guardian profile is the truth.
    RegistrationApplication.objects.filter(pk=app.pk).update(guardian_full_name="STALE COLUMN")

    staff = django_user_model.objects.create_user(username="rev-rt", is_staff=True)
    approve_application(RegistrationApplication.objects.get(pk=app.pk), staff)

    guardian = Guardian.objects.get(parent_account=account)
    assert guardian.full_name == "Draft Guardian"  # NOT "STALE COLUMN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_approval_does_not_overwrite_guardian_from_stale_columns -v`
Expected: FAIL — `assert 'STALE COLUMN' == 'Draft Guardian'` (approval still copies the column onto the Guardian).

- [ ] **Step 3: Remove the snapshot-copy block**

In `apps/registrations/services.py::approve_application`, the current block is:

```python
    guardian = application.guardian
    if guardian is None:
        if application.parent_account_id is not None:
            guardian = resolve_guardian_for_account(application.parent_account)
        else:
            guardian = Guardian.objects.create()
        application.guardian = guardian

    # Refresh the canonical profile from this application's snapshot.
    guardian.full_name = application.guardian_full_name
    guardian.personal_id = application.guardian_personal_id
    guardian.email = application.guardian_email
    guardian.phone = application.guardian_phone
    guardian.address = application.guardian_declared_address
    guardian.save()
```

Remove the copy + save (keep the resolve/fallback). It becomes:

```python
    # Guardian is resolved at initiation and its profile is written at draft-save
    # (Slice B1), so approval just reuses it — no snapshot copy. The fallback
    # covers ORM-built applications that never went through create_or_update_draft.
    guardian = application.guardian
    if guardian is None:
        if application.parent_account_id is not None:
            guardian = resolve_guardian_for_account(application.parent_account)
        else:
            guardian = Guardian.objects.create()
        application.guardian = guardian
```

- [ ] **Step 4: Run test + the approval/dedup suites**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py tests/registrations/test_guardian_dedup.py tests/registrations/test_admin_approval_with_group.py tests/members/test_member_models.py -q`
Expected: PASS. (The dedup/discount tests still hold: members share one guardian; the guardian profile now comes from draft-save, which the `_build_submitted_application` helper exercises.)

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/services.py tests/registrations/test_guardian_read_through.py
git commit -m "refactor(registrations): approval reuses guardian without snapshot copy (P6 Slice B1)"
```

---

## Task 6: Full verification gate + documentation

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Run the full gate**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```
Expected: all green. If a test fails because it builds an application via raw `RegistrationApplication.objects.create(guardian_*=...)` with an unpopulated/None Guardian **and asserts a guardian read-through value**, fix that test by populating the linked Guardian's profile (or building via `create_or_update_draft`) — do not weaken the assertion. Pure `create(guardian_*=)` fixtures that only need an application to exist keep working (the columns still exist in B1); they are swept in Slice B2. If you hit anything that is not one of these two cases, STOP and report BLOCKED.

- [ ] **Step 2: Update `AGENTS.md`**

Add a dated entry (today) under the Slice A record: B1 delivered — guardian-read accessors (`guardian_name`, `guardian_pid`, `guardian_contact_phone`, `guardian_address`, `guardian_contact_email`) prefer the canonical `Guardian`/`ParentAccount` with a transitional column fallback; the Guardian profile is now written at draft-save; templates, the workspace `initial` dict, prefill, the submit phone-sync, and the review-notification all read through the accessors; `approve_application` no longer copies the snapshot onto the Guardian. The `guardian_*` columns remain (dual-written) — Slice B2 drops them, simplifies the accessors, and sweeps `create(guardian_*=)` fixtures. Use the real passed count from Step 1.

- [ ] **Step 3: Update `docs/milestones.md`**

Add a line recording B1 delivery (read-through + propagation) with a pointer to this plan, and note that the column drop is Slice B2.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: record P6 guardian-identity Slice B1 (read-through)"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** §2/§7 read-through is delivered via the accessors + repoints (Tasks 1, 3, 4); the propagation guarantee (§ "edits propagate to all applications and agreements") is proven by `test_editing_guardian_on_second_app_propagates_to_first` (Task 2) and the admin-render propagation test (Task 3). Agreements already read `member.guardian.*`, so they propagate for free. **Not** in B1: dropping the columns, `__str__`/admin changes, the test-fixture sweep — all Slice B2; locked-profile UX + admin email change — Slice C.
- **Why the column fallback:** it keeps B1 green without touching the dozens of `RegistrationApplication.objects.create(guardian_*=...)` fixtures. The fallback halves are deleted in B2 when the columns go.
- **Null-safety:** every accessor guards `guardian_id is not None` / `parent_account_id is not None` before dereferencing, so applications with a missing Guardian (old/ORM-built) fall back cleanly.
- **Naming:** the accessors are deliberately named differently from the columns (`guardian_name` vs `guardian_full_name`) to avoid clashing while both exist; the names are final, so B2 does not re-churn templates.
- **Form fields unchanged:** `forms.py` field names, `field_sources` keys, the OCR-response JSON keys, and the address-sync JS are untouched.
