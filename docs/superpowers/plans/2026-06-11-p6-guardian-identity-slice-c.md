# P6 Guardian Identity — Slice C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the guardian profile for returning parents (read-only with an explicit unlock), and let staff change a parent's verified email from Django admin with uniqueness enforced and the `Guardian.email` mirror kept in sync.

**Architecture:** Builds on Slices A/B (canonical `Guardian` 1:1 with `ParentAccount`, read-through accessors, dropped `guardian_*` columns). Locking is a *render concern*: profile inputs get the HTML `readonly` attribute (NOT `disabled` — disabled inputs are not POSTed, which would wipe the Guardian on save) and a small client-side toggle removes it. The verified email field is always read-only in the parent form (it is the OTP identity, changeable only by staff). Email change is a single-writer service that enforces the `ParentAccount.email` unique constraint and updates the `Guardian.email` mirror in one atomic operation; the admin routes through it.

**Tech Stack:** Django 5.x, pytest-django, `uv run` for all commands. SQLite for tests.

This plan closes the two remaining acceptance items from the design spec (`docs/superpowers/specs/2026-06-09-p6-canonical-guardian-identity-design.md`): **#4** (locked profile + propagation) and **#6** (admin email change). Items #1–#3 (Slice A) and #5 (Slice B2) are already delivered.

---

## File Structure

- `apps/registrations/models.py` — add `guardian_profile_populated` read-through property (lock signal).
- `apps/registrations/forms.py` — `RegistrationApplicationForm.__init__`: always-readonly `guardian_email`; new `guardian_profile_locked` param applies `readonly` to the four guardian profile fields.
- `apps/registrations/views.py` — `application_workspace` computes the lock flag and passes it to the form and template context.
- `templates/registrations/application_workspace.html` — unlock toggle + scoped inline JS in the guardian section, shown only when locked.
- `apps/accounts/services.py` — add `change_parent_email(account, new_email)` (uniqueness + mirror, atomic). *(File already exists — it holds `issue_magic_link`.)*
- `apps/accounts/admin.py` — **new** `ParentAccountAdmin`; `save_model` routes email changes through the service.
- Tests:
  - `tests/registrations/test_guardian_profile_lock.py` — **new** (property + form + view).
  - `tests/registrations/test_parent_surface_copy_contract.py` — extend with the locked-render static scan, OR a new focused template-scan test in the new file (see Task 4).
  - `tests/accounts/test_change_parent_email.py` — **new** (service).
  - `tests/accounts/test_parent_account_admin.py` — **new** (admin wiring).

Lock signal (used in Task 1 and Task 3): a returning parent is one whose canonical `Guardian` profile is already populated, i.e. `application.guardian` is linked **and** `guardian.full_name` is non-empty. (Per spec §6: "Returning parent (profile already populated): fields render read-only/locked".)

---

## Part 1 — Locked profile UX

### Task 1: `guardian_profile_populated` read-through property

**Files:**
- Modify: `apps/registrations/models.py` (alongside the existing `guardian_name` / `guardian_pid` accessors)
- Test: `tests/registrations/test_guardian_profile_lock.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_guardian_profile_lock.py
"""Slice C — guardian-profile lock signal + form/view locking."""

import pytest

from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


class TestGuardianProfilePopulated:
    def test_false_when_no_guardian_linked(self):
        app = RegistrationApplication.objects.create(claimed_email="p@example.com")
        assert app.guardian_profile_populated is False

    def test_false_when_guardian_has_empty_full_name(self, parent_account, make_guardian):
        guardian = make_guardian(parent_account)  # full_name="" by default
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian
        )
        assert app.guardian_profile_populated is False

    def test_true_when_guardian_full_name_set(self, parent_account, make_guardian):
        guardian = make_guardian(parent_account, full_name="Anna Ozola")
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian
        )
        assert app.guardian_profile_populated is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestGuardianProfilePopulated -v`
Expected: FAIL — `AttributeError: 'RegistrationApplication' object has no attribute 'guardian_profile_populated'`

- [ ] **Step 3: Add the property**

In `apps/registrations/models.py`, next to the other guardian read accessors:

```python
    @property
    def guardian_profile_populated(self) -> bool:
        """True when this application's canonical Guardian profile is already
        filled (returning parent). Drives the locked-profile UX in Slice C."""
        return bool(self.guardian_id is not None and self.guardian.full_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestGuardianProfilePopulated -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/models.py tests/registrations/test_guardian_profile_lock.py
git commit -m "feat(registrations): add guardian_profile_populated lock signal (P6 Slice C)"
```

---

### Task 2: Form — readonly email always; readonly profile fields when locked

**Files:**
- Modify: `apps/registrations/forms.py` (`RegistrationApplicationForm.__init__`)
- Test: `tests/registrations/test_guardian_profile_lock.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_profile_lock.py`:

```python
from apps.registrations.forms import RegistrationApplicationForm

GUARDIAN_PROFILE_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_phone",
    "guardian_declared_address",
)


class TestFormReadonlyLocking:
    def test_email_always_readonly(self):
        form = RegistrationApplicationForm()
        assert form.fields["guardian_email"].widget.attrs.get("readonly") == "readonly"

    def test_profile_fields_readonly_when_locked(self):
        form = RegistrationApplicationForm(guardian_profile_locked=True)
        for name in GUARDIAN_PROFILE_FIELDS:
            assert form.fields[name].widget.attrs.get("readonly") == "readonly", name

    def test_profile_fields_editable_when_unlocked(self):
        form = RegistrationApplicationForm(guardian_profile_locked=False)
        for name in GUARDIAN_PROFILE_FIELDS:
            assert "readonly" not in form.fields[name].widget.attrs, name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestFormReadonlyLocking -v`
Expected: FAIL — `test_email_always_readonly` fails (no readonly attr); `guardian_profile_locked` is an unexpected kwarg → `TypeError`.

- [ ] **Step 3: Implement in the form**

In `apps/registrations/forms.py`, change the signature and add locking near the end of `__init__` (after the existing attr setup):

```python
    def __init__(
        self,
        *args,
        is_submit: bool = False,
        has_existing_document: bool = False,
        guardian_profile_locked: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.is_submit = is_submit
        self.has_existing_document = has_existing_document
        self.guardian_profile_locked = guardian_profile_locked
        # ... existing body unchanged ...
```

Then, as the **last** block of `__init__`:

```python
        # Slice C — verified email is the OTP identity; never parent-editable.
        # Staff change it via Django admin (apps.accounts.services.change_parent_email).
        self.fields["guardian_email"].widget.attrs["readonly"] = "readonly"

        # Slice C — returning parents see the guardian profile locked. readonly
        # (NOT disabled) keeps the values in the POST so a save round-trips them
        # unchanged; the template's unlock toggle removes readonly client-side.
        if guardian_profile_locked:
            for _name in (
                "guardian_full_name",
                "guardian_personal_id",
                "guardian_phone",
                "guardian_declared_address",
            ):
                self.fields[_name].widget.attrs["readonly"] = "readonly"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestFormReadonlyLocking -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the registrations form/view suite to confirm no regression**

Run: `uv run pytest tests/registrations/ -q`
Expected: PASS (no failures introduced by the new readonly attrs).

- [ ] **Step 6: Commit**

```bash
git add apps/registrations/forms.py tests/registrations/test_guardian_profile_lock.py
git commit -m "feat(registrations): lock verified email + guardian profile fields in form (P6 Slice C)"
```

---

### Task 3: View — workspace computes and passes the lock flag

**Files:**
- Modify: `apps/registrations/views.py` (`application_workspace`, the GET `else:` branch around line 268, and the render context around line 322)
- Test: `tests/registrations/test_guardian_profile_lock.py`

**Context:** The workspace's GET branch builds the form with `initial={...}`. Locking applies only when the page is editable (draft/fix). Pass `guardian_profile_locked=editable and application.guardian_profile_populated` into the form, and the same value into the template context for the toggle.

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_profile_lock.py`:

```python
class TestWorkspaceLockWiring:
    def _new_draft(self, verified_client, parent_account):
        # GET /applications/new/ creates a blank draft + redirects to its workspace.
        resp = verified_client.get("/applications/new/", follow=True)
        return resp

    def test_returning_parent_sees_locked_profile(
        self, verified_client, parent_account, make_guardian
    ):
        from apps.registrations.models import RegistrationApplication

        # Populate the canonical guardian (simulates a prior registration).
        guardian = parent_account.guardian if hasattr(parent_account, "guardian") else None
        # Resolve-or-create then populate:
        from apps.members.services import resolve_guardian_for_account

        guardian = resolve_guardian_for_account(parent_account)
        guardian.full_name = "Anna Ozola"
        guardian.save(update_fields=["full_name"])

        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )
        resp = verified_client.get(f"/applications/{app.id}/")
        assert resp.status_code == 200
        assert resp.context["guardian_profile_locked"] is True
        assert resp.context["form"].fields["guardian_full_name"].widget.attrs.get("readonly") == "readonly"

    def test_first_registration_profile_unlocked(
        self, verified_client, parent_account
    ):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)  # empty profile
        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )
        resp = verified_client.get(f"/applications/{app.id}/")
        assert resp.status_code == 200
        assert resp.context["guardian_profile_locked"] is False
        assert "readonly" not in resp.context["form"].fields["guardian_full_name"].widget.attrs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestWorkspaceLockWiring -v`
Expected: FAIL — `KeyError: 'guardian_profile_locked'` (not in context) and the readonly assertion fails.

- [ ] **Step 3: Implement in the view**

In `apps/registrations/views.py`, inside `application_workspace`, compute the flag once after `editable = application.is_editable_by(account)`:

```python
    editable = application.is_editable_by(account)
    guardian_profile_locked = editable and application.guardian_profile_populated
```

In the GET `else:` branch, pass it to the form constructor:

```python
        form = RegistrationApplicationForm(
            guardian_profile_locked=guardian_profile_locked,
            initial={
                # ... unchanged ...
            },
        )
```

Add it to the `render(...)` context dict:

```python
            "guardian_profile_locked": guardian_profile_locked,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestWorkspaceLockWiring -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/views.py tests/registrations/test_guardian_profile_lock.py
git commit -m "feat(registrations): wire guardian profile lock into workspace view (P6 Slice C)"
```

---

### Task 4: Template — unlock toggle + scoped JS

**Files:**
- Modify: `templates/registrations/application_workspace.html` (guardian section, inside the `{% for section_name, bound_fields in form.grouped_fields %}` loop, in the section body before the field loop)
- Test: `tests/registrations/test_guardian_profile_lock.py` (template static scan via the live render context)

**Context:** The four profile inputs already render `readonly` (from Task 2). This task adds the visible **"Rediģēt vecāka datus"** toggle and a small inline script (mirrors the existing `SameAddressSync` inline pattern) that removes `readonly` from the four profile inputs on click. The verified email input stays readonly. All copy is Latvian (the parent-surface copy-contract test scans for leaked English tokens).

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_profile_lock.py`:

```python
class TestLockedRenderMarkup:
    def _make_locked_app(self, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)
        guardian.full_name = "Anna Ozola"
        guardian.save(update_fields=["full_name"])
        return RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )

    def test_locked_render_includes_unlock_toggle(self, verified_client, parent_account):
        app = self._make_locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert "data-guardian-unlock" in html
        assert "Rediģēt vecāka datus" in html

    def test_unlocked_render_omits_unlock_toggle(self, verified_client, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)  # empty profile
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian, claimed_email=parent_account.email
        )
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert "data-guardian-unlock" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestLockedRenderMarkup -v`
Expected: FAIL — `data-guardian-unlock` not in HTML.

- [ ] **Step 3: Implement the template block**

In `templates/registrations/application_workspace.html`, inside the section-body, add a guardian-only block. Place it immediately after the `{% if section_name == "documents" %}...{% endif %}` block (around line 87), before `{% for bound_field in bound_fields %}`:

```django
        {% if section_name == "guardian" and guardian_profile_locked %}
          <div class="fk-guardian-lock" data-guardian-lock>
            <p class="fk-guardian-lock__note">Vecāka dati ir aizpildīti no Jūsu profila. Lai labotu, nospiediet pogu.</p>
            <button type="button" class="fk-button fk-button--secondary" data-guardian-unlock>Rediģēt vecāka datus</button>
          </div>
          <script>
// GuardianProfileUnlock — Slice C. Removes readonly from the four guardian
// profile inputs on click so a returning parent can edit. Email stays readonly.
document.addEventListener('DOMContentLoaded', function () {
  var btn = document.querySelector('[data-guardian-unlock]');
  if (!btn) return;
  btn.addEventListener('click', function () {
    ['id_guardian_full_name', 'id_guardian_personal_id', 'id_guardian_phone', 'id_guardian_declared_address'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.removeAttribute('readonly');
    });
    btn.setAttribute('hidden', 'hidden');
  });
});
          </script>
        {% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_profile_lock.py::TestLockedRenderMarkup -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the parent-surface copy-contract test to confirm no English leaked**

Run: `uv run pytest tests/registrations/test_parent_surface_copy_contract.py -q`
Expected: PASS (the new Latvian strings introduce no English tokens).

- [ ] **Step 6: Commit**

```bash
git add templates/registrations/application_workspace.html tests/registrations/test_guardian_profile_lock.py
git commit -m "feat(registrations): unlock toggle for locked guardian profile (P6 Slice C)"
```

---

## Part 2 — Admin-initiated email change

### Task 5: `change_parent_email` service

**Files:**
- Modify: `apps/accounts/services.py` (add the function)
- Test: `tests/accounts/test_change_parent_email.py` (new)

**Context:** Single writer for verified-email changes. Atomic. Normalizes the new email (strip + lowercase). No-op if unchanged. Rejects (raises `ValueError`) if **another** account already owns the email (case-insensitive). On success, sets `account.email` and updates the linked `Guardian.email` mirror (the Invoice Ninja client contact reads `Guardian.email`). Safe when the account has no `Guardian` yet.

- [ ] **Step 1: Write the failing test**

```python
# tests/accounts/test_change_parent_email.py
"""Slice C — admin-initiated verified email change service."""

import pytest

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email
from apps.members.services import resolve_guardian_for_account

pytestmark = pytest.mark.django_db


def test_changes_email_and_syncs_guardian_mirror():
    account = ParentAccount.objects.create(email="old@example.com")
    guardian = resolve_guardian_for_account(account)  # mirror == old@example.com
    assert guardian.email == "old@example.com"

    change_parent_email(account, "new@example.com")

    account.refresh_from_db()
    guardian.refresh_from_db()
    assert account.email == "new@example.com"
    assert guardian.email == "new@example.com"


def test_normalizes_new_email():
    account = ParentAccount.objects.create(email="old@example.com")
    change_parent_email(account, "  New@Example.COM ")
    account.refresh_from_db()
    assert account.email == "new@example.com"


def test_noop_when_unchanged():
    account = ParentAccount.objects.create(email="same@example.com")
    # Case-insensitive no-op: must not raise a self-collision.
    change_parent_email(account, "SAME@example.com")
    account.refresh_from_db()
    assert account.email == "same@example.com"


def test_rejects_email_owned_by_another_account():
    ParentAccount.objects.create(email="taken@example.com")
    account = ParentAccount.objects.create(email="mine@example.com")
    with pytest.raises(ValueError):
        change_parent_email(account, "TAKEN@example.com")
    account.refresh_from_db()
    assert account.email == "mine@example.com"


def test_safe_when_account_has_no_guardian():
    account = ParentAccount.objects.create(email="noguardian@example.com")
    change_parent_email(account, "moved@example.com")  # must not raise
    account.refresh_from_db()
    assert account.email == "moved@example.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/accounts/test_change_parent_email.py -v`
Expected: FAIL — `ImportError: cannot import name 'change_parent_email'`.

- [ ] **Step 3: Implement the service**

Add to `apps/accounts/services.py`:

```python
from django.db import transaction

from apps.accounts.models import ParentAccount


@transaction.atomic
def change_parent_email(account: ParentAccount, new_email: str) -> ParentAccount:
    """Change a parent's verified email (admin-initiated).

    Normalizes the new email, enforces the unique constraint (rejecting an
    email already owned by another account, case-insensitive), persists it,
    and updates the linked Guardian.email mirror in the same transaction.
    No-op when the email is unchanged. Raises ValueError on collision.
    """
    normalized = new_email.strip().lower()
    if not normalized:
        raise ValueError("new email is required")
    if normalized == account.email.lower():
        return account

    clash = (
        ParentAccount.objects.filter(email__iexact=normalized)
        .exclude(pk=account.pk)
        .exists()
    )
    if clash:
        raise ValueError("email already in use by another account")

    account.email = normalized
    account.save(update_fields=["email", "updated_at"])

    # Mirror update — the IN client contact reads Guardian.email. Use a query
    # rather than the reverse accessor so an absent Guardian is a clean no-op.
    from apps.members.models import Guardian

    Guardian.objects.filter(parent_account=account).update(email=normalized)
    return account
```

(Place the `from apps.accounts.models import ParentAccount` / `transaction` imports with the existing module imports; the in-function `Guardian` import avoids a circular import.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/accounts/test_change_parent_email.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add apps/accounts/services.py tests/accounts/test_change_parent_email.py
git commit -m "feat(accounts): change_parent_email service with uniqueness + Guardian mirror (P6 Slice C)"
```

---

### Task 6: ParentAccount admin + email-change routing

**Files:**
- Create: `apps/accounts/admin.py`
- Test: `tests/accounts/test_parent_account_admin.py` (new)

**Context:** `ParentAccount` is not currently registered in admin. Register it so staff can edit it, and override `save_model` so an email change routes through `change_parent_email` (keeping it the single writer and syncing the mirror). The admin ModelForm's field-level `unique=True` validation rejects duplicate emails before `save_model` runs, so the service's `ValueError` path is the programmatic guard, not the normal admin path. Use `form.initial["email"]` to recover the pre-edit value.

- [ ] **Step 1: Write the failing test**

```python
# tests/accounts/test_parent_account_admin.py
"""Slice C — ParentAccount admin email-change routing."""

import pytest
from django.contrib.admin.sites import AdminSite

from apps.accounts.admin import ParentAccountAdmin
from apps.accounts.models import ParentAccount
from apps.members.services import resolve_guardian_for_account

pytestmark = pytest.mark.django_db


class _StubForm:
    """Minimal stand-in for the admin ModelForm in save_model."""

    def __init__(self, changed_data, initial):
        self.changed_data = changed_data
        self.initial = initial


def test_registered_in_admin():
    from django.contrib import admin

    assert ParentAccount in admin.site._registry


def test_save_model_routes_email_change_through_service():
    account = ParentAccount.objects.create(email="old@example.com")
    guardian = resolve_guardian_for_account(account)
    assert guardian.email == "old@example.com"

    admin_obj = ParentAccountAdmin(ParentAccount, AdminSite())
    account.email = "new@example.com"  # mimic the admin form mutating the instance
    form = _StubForm(changed_data=["email"], initial={"email": "old@example.com"})
    admin_obj.save_model(request=None, obj=account, form=form, change=True)

    account.refresh_from_db()
    guardian.refresh_from_db()
    assert account.email == "new@example.com"
    assert guardian.email == "new@example.com"


def test_save_model_plain_save_when_email_unchanged():
    account = ParentAccount.objects.create(email="stable@example.com", phone="111")
    admin_obj = ParentAccountAdmin(ParentAccount, AdminSite())
    account.phone = "222"
    form = _StubForm(changed_data=["phone"], initial={"phone": "111"})
    admin_obj.save_model(request=None, obj=account, form=form, change=True)

    account.refresh_from_db()
    assert account.email == "stable@example.com"
    assert account.phone == "222"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/accounts/test_parent_account_admin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.accounts.admin'`.

- [ ] **Step 3: Implement the admin**

```python
# apps/accounts/admin.py
"""Django admin for accounts app."""

from django.contrib import admin

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email


@admin.register(ParentAccount)
class ParentAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "phone", "is_active", "last_login")
    search_fields = ("email", "phone")
    list_filter = ("is_active",)

    def save_model(self, request, obj, form, change):
        """Route verified-email changes through change_parent_email so the
        Guardian.email mirror stays in sync (single writer)."""
        if change and "email" in form.changed_data:
            new_email = obj.email
            # Save the non-email fields first under the original email, then let
            # the service perform the email change + mirror update atomically.
            obj.email = form.initial.get("email", obj.email)
            super().save_model(request, obj, form, change)
            change_parent_email(obj, new_email)
        else:
            super().save_model(request, obj, form, change)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/accounts/test_parent_account_admin.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Verify read-through: changed email surfaces on applications**

Add to `tests/accounts/test_change_parent_email.py`:

```python
def test_changed_email_visible_through_application_accessor(make_guardian):
    from apps.registrations.models import RegistrationApplication

    account = ParentAccount.objects.create(email="before@example.com")
    guardian = resolve_guardian_for_account(account)
    app = RegistrationApplication.objects.create(parent_account=account, guardian=guardian)
    assert app.guardian_contact_email == "before@example.com"

    change_parent_email(account, "after@example.com")
    app.refresh_from_db()
    assert app.guardian_contact_email == "after@example.com"
```

Run: `uv run pytest tests/accounts/test_change_parent_email.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/admin.py tests/accounts/test_parent_account_admin.py tests/accounts/test_change_parent_email.py
git commit -m "feat(accounts): register ParentAccount admin; route email change through service (P6 Slice C)"
```

---

## Task 7: Full gate + docs

**Files:**
- Modify: `AGENTS.md` (Slice C delivery entry), `docs/milestones.md` (mark Slice C done)

- [ ] **Step 1: Full suite + lint + types**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
Expected: all green. Fail loud on any failure — fix before proceeding.

- [ ] **Step 2: Update AGENTS.md and milestones**

Add a "P6 Guardian Identity — Slice C delivered" entry summarizing: locked-profile UX (returning parents read-only + unlock toggle), always-readonly verified email in the parent form, `change_parent_email` service (uniqueness + Guardian mirror), ParentAccount admin registration + email-change routing. Note LAN acceptance pending. Mark Slice C done in `docs/milestones.md`.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: record P6 guardian-identity Slice C delivery"
```

---

## LAN Acceptance (after implementation, before sign-off)

Browser-driven against the local `0.0.0.0:8000` instance + qcluster (console email backend). Verify:

- **L1 (lock + unlock):** As a returning parent (one prior populated registration), open a new application workspace → guardian name/PID/phone/address render read-only and the verified email is read-only. Click **"Rediģēt vecāka datus"** → the four profile fields become editable (email stays read-only). Edit the name, save.
- **L2 (propagation):** The edit from L1 appears on the parent's other application + `/portal/` (shared `Guardian`).
- **L3 (first registration unlocked):** A brand-new parent's first application shows the guardian profile editable (no toggle), email read-only.
- **L4 (admin email change):** In Django admin → Parent accounts, change a parent's email. Confirm: the change saves; the linked Guardian's email updates (admin → Guardians); the parent's applications display the new verified email (read-through). Attempt to set an email already owned by another account → admin rejects it.

Record results in `docs/acceptance/2026-06-11-p6-guardian-identity-slice-c-lan-acceptance.md` and add the sign-off line to the AGENTS.md Slice C entry.

---

## Self-Review Notes

- **Spec coverage:** Acceptance #4 (locked profile + propagation) → Tasks 1–4 + L1/L2/L3. Acceptance #6 (admin email change, uniqueness, mirror) → Tasks 5–6 + L4. Acceptance #7 (gate + LAN) → Task 7 + LAN section.
- **`readonly` not `disabled`:** deliberate — disabled inputs are omitted from POST, which `create_or_update_draft` would read as empty and wipe the Guardian. `readonly` round-trips values. Called out in Task 2.
- **Lock signal:** profile-populated (`guardian.full_name` set), per spec §6. Known minor interaction: reloading mid-first-registration after the name is set shows locked — mitigated by the one-click unlock; acceptable.
- **Admin ValueError path:** the admin ModelForm's `unique=True` field validation rejects duplicate emails before `save_model`, so the service's collision `ValueError` is the programmatic guard (and what direct/self-service callers rely on), not the normal admin flow. Documented in Task 6.
- **No new migrations:** Slice C is code-only (no schema change).
