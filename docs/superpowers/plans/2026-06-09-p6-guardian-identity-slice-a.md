# Canonical Guardian Identity — Slice A (dedup + bug fix) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Guardian` a canonical 1:1 entity per verified `ParentAccount`, resolved when a registration is initiated and reused at approval, so a parent's children share one `Guardian` — fixing the broken sibling-discount linkage and producing one Invoice Ninja client per parent.

**Architecture:** Add a `Guardian.parent_account` OneToOne and a `RegistrationApplication.guardian` FK. Resolve-or-create the Guardian inside `create_or_update_draft` whenever a verified account is present (covers `/applications/new/` and every save). `approve_application` stops minting a fresh Guardian and instead reuses the application's resolved Guardian, refreshing its profile from the application snapshot. The denormalized `guardian_*` columns stay in place this slice (Slice B drops them); only identity/linkage changes here, so the system stays green and the fix is shippable on its own.

**Tech Stack:** Django 5.x, PostgreSQL, pytest + pytest-django, uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-06-09-p6-canonical-guardian-identity-design.md` (§4 data model, §5 resolution flow). This plan covers **Slice A only**; Slice B (read-through + drop columns) and Slice C (locked UX + admin email change) are separate plans.

---

## File Structure

- **Modify** `apps/members/models.py` — add `Guardian.parent_account` OneToOne.
- **Modify** `apps/members/services.py` — add `resolve_guardian_for_account`.
- **Modify** `apps/registrations/models.py` — add `RegistrationApplication.guardian` FK.
- **Modify** `apps/registrations/services.py` — wire resolution into `create_or_update_draft`; rewrite the Guardian-creation block in `approve_application`.
- **Create** migration `apps/members/migrations/0XXX_guardian_parent_account.py` (via `makemigrations`).
- **Create** migration `apps/registrations/migrations/0XXX_application_guardian.py` (via `makemigrations`).
- **Create** `tests/members/test_guardian_resolution.py` — model + service unit tests.
- **Create** `tests/registrations/test_guardian_dedup.py` — initiation dedup + approval reuse + sibling-discount payoff.
- **Modify** `AGENTS.md`, `docs/milestones.md` — record Slice A.

---

## Task 1: Add `Guardian.parent_account` OneToOne field

**Files:**
- Modify: `apps/members/models.py`
- Test: `tests/members/test_guardian_resolution.py`
- Create (generated): `apps/members/migrations/`

- [ ] **Step 1: Write the failing test**

Create `tests/members/test_guardian_resolution.py`:

```python
"""Slice A — canonical Guardian 1:1 with ParentAccount."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

pytestmark = pytest.mark.django_db


def test_guardian_links_one_to_one_to_parent_account():
    account = ParentAccount.objects.create(email="link@example.com")
    guardian = Guardian.objects.create(parent_account=account, email=account.email)
    # Reverse accessor is singular (OneToOne).
    assert account.guardian == guardian


def test_parent_account_can_have_only_one_guardian():
    account = ParentAccount.objects.create(email="dup@example.com")
    Guardian.objects.create(parent_account=account)
    with pytest.raises(IntegrityError):
        Guardian.objects.create(parent_account=account)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_guardian_resolution.py -v`
Expected: FAIL — `TypeError`/`FieldError` (no `parent_account` field on `Guardian`).

- [ ] **Step 3: Add the field**

In `apps/members/models.py`, add to the `Guardian` class (after `external_client_id`):

```python
    parent_account = models.OneToOneField(
        "accounts.ParentAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="guardian",
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations members`
Expected: creates `apps/members/migrations/0XXX_guardian_parent_account.py` adding one `OneToOneField`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/members/test_guardian_resolution.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add apps/members/models.py apps/members/migrations/ tests/members/test_guardian_resolution.py
git commit -m "feat(members): Guardian 1:1 OneToOne to ParentAccount (P6 Slice A)"
```

---

## Task 2: Add `RegistrationApplication.guardian` FK

**Files:**
- Modify: `apps/registrations/models.py`
- Test: `tests/registrations/test_guardian_dedup.py`
- Create (generated): `apps/registrations/migrations/`

- [ ] **Step 1: Write the failing test**

Create `tests/registrations/test_guardian_dedup.py`:

```python
"""Slice A — guardian resolved at initiation; approval reuses it; sibling discount."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.documents.models import Document
from apps.members.models import Guardian
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    create_or_update_draft,
    submit_application,
)

pytestmark = pytest.mark.django_db


def test_application_has_guardian_fk():
    account = ParentAccount.objects.create(email="fk@example.com")
    guardian = Guardian.objects.create(parent_account=account)
    app = RegistrationApplication.objects.create(
        guardian_email=account.email, parent_account=account, guardian=guardian
    )
    assert app.guardian == guardian
    assert list(guardian.applications.all()) == [app]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_application_has_guardian_fk -v`
Expected: FAIL — `TypeError` (unexpected keyword `guardian`).

- [ ] **Step 3: Add the field**

In `apps/registrations/models.py`, add to `RegistrationApplication` (just below the `approved_member` OneToOneField block):

```python
    # Canonical guardian (1:1 with ParentAccount), resolved at initiation.
    guardian = models.ForeignKey(
        "members.Guardian",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="applications",
    )
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations registrations`
Expected: creates `apps/registrations/migrations/0XXX_registrationapplication_guardian.py` adding one nullable FK.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_application_has_guardian_fk -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/registrations/models.py apps/registrations/migrations/ tests/registrations/test_guardian_dedup.py
git commit -m "feat(registrations): add RegistrationApplication.guardian FK (P6 Slice A)"
```

---

## Task 3: `resolve_guardian_for_account` service

**Files:**
- Modify: `apps/members/services.py`
- Test: `tests/members/test_guardian_resolution.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/members/test_guardian_resolution.py`:

```python
def test_resolve_guardian_is_idempotent_and_mirrors_email():
    from apps.members.services import resolve_guardian_for_account

    account = ParentAccount.objects.create(email="resolve@example.com")
    first = resolve_guardian_for_account(account)
    second = resolve_guardian_for_account(account)

    assert first.pk == second.pk  # same row, not a duplicate
    assert first.parent_account_id == account.id
    assert first.email == "resolve@example.com"  # email mirrored on create
    assert Guardian.objects.filter(parent_account=account).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_guardian_resolution.py::test_resolve_guardian_is_idempotent_and_mirrors_email -v`
Expected: FAIL — `ImportError` (no `resolve_guardian_for_account`).

- [ ] **Step 3: Implement the service**

In `apps/members/services.py`, update the model import line and append the function:

```python
from apps.members.models import Guardian, Member, TrainingGroup
```

```python
def resolve_guardian_for_account(account) -> Guardian:
    """Return the canonical Guardian for a verified ParentAccount, creating it
    if absent. One verified email maps to exactly one Guardian, forever.

    Called when a registration is initiated so every application carries its
    parent's canonical guardian. The email is mirrored from the account on
    create (the Invoice Ninja client contact reads Guardian.email).
    """
    guardian, _created = Guardian.objects.get_or_create(
        parent_account=account,
        defaults={"email": account.email},
    )
    return guardian
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/members/test_guardian_resolution.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/members/services.py tests/members/test_guardian_resolution.py
git commit -m "feat(members): resolve_guardian_for_account get-or-create service (P6 Slice A)"
```

---

## Task 4: Resolve the Guardian inside `create_or_update_draft`

**Files:**
- Modify: `apps/registrations/services.py:384-387` (the `verified_account` block) and the import section near line 21.
- Test: `tests/registrations/test_guardian_dedup.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_dedup.py`:

```python
def test_two_initiations_same_account_share_one_guardian():
    account = ParentAccount.objects.create(email="siblings@example.com")

    app1 = create_or_update_draft(
        data={"guardian_email": account.email},
        files={},
        verified_account=account,
    )
    app2 = create_or_update_draft(
        data={"guardian_email": account.email},
        files={},
        verified_account=account,
    )

    assert app1.guardian_id is not None
    assert app1.guardian_id == app2.guardian_id
    assert Guardian.objects.filter(parent_account=account).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_two_initiations_same_account_share_one_guardian -v`
Expected: FAIL — `app1.guardian_id is None` (resolution not wired yet).

- [ ] **Step 3: Wire resolution**

In `apps/registrations/services.py`, add the import beside the existing members import (line 21):

```python
from apps.members.services import resolve_guardian_for_account
```

Then in `create_or_update_draft`, change the verified-account block (currently lines 384-387):

```python
    if verified_account is not None:
        if verified_account.email.lower() != email:
            raise ValueError("verified account email must match claimed email")
        application.parent_account = verified_account
```

to also resolve and attach the canonical guardian:

```python
    if verified_account is not None:
        if verified_account.email.lower() != email:
            raise ValueError("verified account email must match claimed email")
        application.parent_account = verified_account
        application.guardian = resolve_guardian_for_account(verified_account)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_two_initiations_same_account_share_one_guardian -v`
Expected: PASS.

- [ ] **Step 5: Run the registrations suite to catch fixture interactions**

Wiring guardian creation into every verified draft means tests that count `Guardian` rows may now see one extra. Run the suite and fix any such count assertions (they should expect the resolved guardian):

Run: `uv run pytest tests/registrations tests/members -q`
Expected: PASS. If a failure is a `Guardian.objects.count()` assertion, update it to account for the resolved guardian; do not weaken behavioural assertions.

- [ ] **Step 6: Commit**

```bash
git add apps/registrations/services.py tests/registrations/test_guardian_dedup.py
git commit -m "feat(registrations): resolve canonical guardian at draft initiation (P6 Slice A)"
```

---

## Task 5: `approve_application` reuses the resolved Guardian

**Files:**
- Modify: `apps/registrations/services.py:724-754` (the `Guardian.objects.create` block + the `application.save` update_fields).
- Test: `tests/registrations/test_guardian_dedup.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_dedup.py` a helper and the reuse test:

```python
_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _build_submitted_application(account, child_name, child_pid, kit_shirt, kit_shorts, *, opt_out=False):
    """Create a fully-populated submitted application for `account`."""
    app = create_or_update_draft(
        data={
            "guardian_full_name": "Sibling Guardian",
            "guardian_personal_id": "010101-12345",
            "guardian_email": account.email,
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga, Brivibas 1",
            "member_full_name": child_name,
            "member_personal_id": child_pid,
            "member_birth_date": "2025-01-01",
            "member_same_address_as_guardian": True,
            "member_kit_size_shirt": kit_shirt,
            "member_kit_size_shorts": kit_shorts,
            "preferred_agreement_signing": "paper",
            "support_club_instead_of_multi_child_discount": opt_out,
        },
        files={},
        verified_account=account,
    )
    for kind in (
        Document.Kind.GUARDIAN_IDENTITY,
        Document.Kind.MEMBER_IDENTITY,
        Document.Kind.MEMBER_PORTRAIT,
    ):
        Document.objects.create(
            application=app,
            kind=kind,
            file=SimpleUploadedFile(f"{kind}.png", _PNG, content_type="image/png"),
            original_filename=f"{kind}.png",
            content_type="image/png",
            file_size=len(_PNG),
        )
    return submit_application(app, account)


@pytest.fixture
def kit_pks(db):
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT, label="S", defaults={"is_active": True}
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS, label="S", defaults={"is_active": True}
    )
    return shirt.pk, shorts.pk


@pytest.fixture
def staff_reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="rev", is_staff=True)


def test_approval_reuses_guardian_no_duplicates(kit_pks, staff_reviewer):
    shirt, shorts = kit_pks
    account = ParentAccount.objects.create(email="reuse@example.com")

    app1 = _build_submitted_application(account, "Child One", "010120-11111", shirt, shorts)
    app2 = _build_submitted_application(account, "Child Two", "010122-22222", shirt, shorts)

    approve_application(app1, staff_reviewer)
    approve_application(app2, staff_reviewer)
    app1.refresh_from_db()
    app2.refresh_from_db()

    # Exactly one Guardian for the account; both Members hang off it.
    assert Guardian.objects.filter(parent_account=account).count() == 1
    guardian = Guardian.objects.get(parent_account=account)
    assert app1.approved_member.guardian_id == guardian.id
    assert app2.approved_member.guardian_id == guardian.id
    assert guardian.members.count() == 2
    # Profile populated from the application snapshot.
    assert guardian.full_name == "Sibling Guardian"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_approval_reuses_guardian_no_duplicates -v`
Expected: FAIL — `Guardian.objects.filter(...).count() == 2` (approval still creates a fresh Guardian per application).

- [ ] **Step 3: Rewrite the Guardian block in `approve_application`**

In `apps/registrations/services.py`, replace the current creation block (lines 724-731):

```python
    # Create Guardian from application guardian data
    guardian = Guardian.objects.create(
        full_name=application.guardian_full_name,
        personal_id=application.guardian_personal_id,
        email=application.guardian_email,
        phone=application.guardian_phone,
        address=application.guardian_declared_address,
    )
```

with reuse-or-resolve plus a profile refresh from the snapshot:

```python
    # Reuse the canonical Guardian resolved at initiation (1:1 with the
    # ParentAccount), so a parent's children share one Guardian — fixing
    # sibling-discount linkage and yielding one Invoice Ninja client per parent.
    # Fallbacks keep ORM-built applications (older tests) working.
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

- [ ] **Step 4: Persist the guardian link on the application**

In the same function, change the `application.save(...)` call (line 754) to include the `guardian` field so the fallback link is persisted:

```python
    application.save(update_fields=["status", "approved_member_id", "guardian", "reviewed_by_id", "reviewed_at", "updated_at"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_approval_reuses_guardian_no_duplicates -v`
Expected: PASS.

- [ ] **Step 6: Run the approval regression suite**

Run: `uv run pytest tests/registrations/test_admin_approval_with_group.py -v`
Expected: PASS (idempotency, group assignment, agreement creation all still green).

- [ ] **Step 7: Commit**

```bash
git add apps/registrations/services.py tests/registrations/test_guardian_dedup.py
git commit -m "fix(registrations): approval reuses canonical guardian, no duplicates (P6 Slice A)"
```

---

## Task 6: Sibling-discount payoff (the bug-fixed proof)

**Files:**
- Test: `tests/registrations/test_guardian_dedup.py` (reuses helpers/fixtures from Task 5).

- [ ] **Step 1: Write the failing-then-passing integration test**

Append to `tests/registrations/test_guardian_dedup.py`:

```python
def test_sibling_discount_applies_after_approving_two_children(kit_pks, staff_reviewer):
    from apps.billing.models import MembershipPlan
    from apps.billing.services import compute_billing_amounts

    shirt, shorts = kit_pks
    plan = MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        sibling_discount_percent=Decimal("50.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    account = ParentAccount.objects.create(email="discount@example.com")

    app1 = _build_submitted_application(account, "First Child", "010120-11111", shirt, shorts)
    app2 = _build_submitted_application(account, "Second Child", "010122-22222", shirt, shorts)
    approve_application(app1, staff_reviewer)
    approve_application(app2, staff_reviewer)
    app1.refresh_from_db()
    app2.refresh_from_db()

    first = compute_billing_amounts(app1.approved_member, plan)
    second = compute_billing_amounts(app2.approved_member, plan)

    # Earliest child pays full price; the sibling is discounted — only possible
    # because both members now share one Guardian.
    assert first.is_full_price is True
    assert first.final_amount == Decimal("300.00")
    assert second.is_full_price is False
    assert second.discount_amount == Decimal("150.00")
    assert second.final_amount == Decimal("150.00")
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/registrations/test_guardian_dedup.py::test_sibling_discount_applies_after_approving_two_children -v`
Expected: PASS (the fix from Tasks 4-5 makes both members share a Guardian, so `_is_first_child` distinguishes them and the discount applies to the second).

- [ ] **Step 3: Commit**

```bash
git add tests/registrations/test_guardian_dedup.py
git commit -m "test(billing): sibling discount applies across approved siblings (P6 Slice A)"
```

---

## Task 7: Full gate + documentation

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Run the full verification gate**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```
Expected: all green. The pytest count should be the prior baseline plus the new Slice A tests. If any non-Slice-A test fails because it counts `Guardian` rows or builds an application without going through `create_or_update_draft`, fix it to expect the resolved guardian (behavioural assertions stay intact).

- [ ] **Step 2: Update `AGENTS.md`**

Add a dated entry under the current-status changelog describing Slice A: `Guardian` is now 1:1 with `ParentAccount` via `Guardian.parent_account`; `resolve_guardian_for_account` get-or-creates it; `create_or_update_draft` attaches `application.guardian` at initiation; `approve_application` reuses it instead of `Guardian.objects.create`, fixing sibling-discount linkage and one-IN-client-per-parent. Note the `guardian_*` columns remain (read-through + column drop is Slice B).

- [ ] **Step 3: Update `docs/milestones.md`**

In the "Data integrity gaps" entry for guardian-dedup-by-email (lines ~101-102), mark Slice A delivered: dedup is resolved go-forward via the canonical Guardian; read-through propagation and admin email-change are tracked for Slices B and C. Add a "Deferred" note for parent self-service email change.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: record P6 guardian-identity Slice A (canonical guardian + dedup)"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage (Slice A subset):** acceptance items 1 (one email → one guardian, at initiation — Tasks 1/3/4), 2 (approval reuses, no duplicates — Task 5), 3 (sibling discount + one IN client per parent — Task 6) are covered. Items 4-6 (read-through propagation, column removal, admin email change) are explicitly out of Slice A.
- **Deferred to Slice B:** repointing the ~105 `guardian_*` reads, moving form persistence onto the Guardian, dropping the five columns. Slice A intentionally keeps the snapshot columns so the change stays small and green.
- **`on_delete=PROTECT`** on both new relations is deliberate: a Guardian linked to applications/members (and downstream Invoice Ninja state) must not be deleted by an accidental cascade.
- **Fixture-interaction risk** (Task 4 Step 5 / Task 7 Step 1): introducing a Guardian row on every verified draft can surface tests that assert `Guardian.objects.count()`. These are expected adjustments, not behavioural regressions.
