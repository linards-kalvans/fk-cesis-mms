# Guardian consolidation — Plan 1: model + migration + single-writer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the duplicated `email`/`phone` from `Guardian` (proxy them to the linked `ParentAccount`), enforce a mandatory 1:1, and collapse all contact-field writes to a single owner — without breaking any reader.

**Architecture:** A tested `consolidate_guardians()` service links every orphan Guardian to its ParentAccount by email (creating the account when missing), backfills the account phone, and merges duplicate guardians; a data migration calls it. Then `Guardian.email`/`phone` become read-only `@property` proxies, the columns are dropped, and `parent_account` is made NOT NULL. Write paths (`change_parent_email`, draft-save, approval) are pointed at the account. A shared `make_guardian` test helper provides accounts so fixtures stay valid under NOT NULL.

**Tech Stack:** Django 5.x, pytest-django, `uv run`. Two new migrations in `apps/members/migrations/` (next numbers after `0005`).

Spec: `docs/superpowers/specs/2026-06-15-guardian-parentaccount-consolidation-design.md` (§3.1–3.3, §5).

---

## File Structure

- `apps/members/services.py` — **new** `consolidate_guardians()` (link + create-missing-account + backfill phone + merge duplicates); modify `resolve_guardian_for_account` (drop the `email` default).
- `apps/members/models.py` — `Guardian`: drop `email`/`phone` fields, add `@property email`/`phone`, `parent_account` → `null=False`.
- `apps/members/migrations/0006_*.py` — **new** data migration (RunPython → `consolidate_guardians`).
- `apps/members/migrations/0007_*.py` — **new** schema migration (`AlterField parent_account NOT NULL`, `RemoveField email`, `RemoveField phone`).
- `apps/accounts/services.py` — `change_parent_email`: drop the `Guardian.email` mirror.
- `apps/registrations/services.py` — draft-save phone → account; delete submit-time phone sync; approval orphan fallback requires an account.
- `tests/support.py` — **new** `make_guardian(...)` helper (creates a ParentAccount + Guardian).
- Tests (new): `tests/members/test_guardian_consolidation.py`, `tests/members/test_guardian_proxy_fields.py`; sweep of existing fixtures (enumerated in Task 1).

**Verified current code:**
- `resolve_guardian_for_account` (`apps/members/services.py:43-56`): `get_or_create(parent_account=account, defaults={"email": account.email})`.
- `change_parent_email` (`apps/accounts/services.py:325-357`): ends with `Guardian.objects.filter(parent_account=account).update(email=normalized)` (line 356) — the mirror to drop.
- Draft-save (`apps/registrations/services.py:426-432`): writes `_guardian.phone = str(data.get("guardian_phone","")).strip()` and saves `update_fields=["full_name","personal_id","phone","address"]`.
- Submit phone sync (`apps/registrations/services.py:~641-648`): `account.phone = application.guardian_contact_phone` block.
- Approval fallback (`apps/registrations/services.py:~768-776`): `guardian = Guardian.objects.create()` when `parent_account_id` is None.
- Accessor `guardian_contact_phone` (`apps/registrations/models.py:162-163`): reads `self.guardian.phone` — works unchanged once `phone` is a proxy.
- `Member.guardian` (FK, related_name "members"), `RegistrationApplication.guardian` (FK, PROTECT, related_name "applications"), `Agreement.member` (no direct guardian FK). `ParentAccount.email` is `unique=True`.
- Latest members migration: `0005_traininggroup_uniq_training_group_name_ci`.

---

### Task 1: Shared `make_guardian` test helper + fixture sweep

**Why first:** 35 `Guardian.objects.create(...)` calls in tests pass no `parent_account`; they must provide one before NOT NULL lands (Task 4). Six also pass `email=`/`phone=` kwargs that become invalid once the columns are dropped. Sweeping now (while the columns are still nullable/present) keeps the suite green at every later step.

**Files:**
- Create: `tests/support.py`
- Modify (sweep): the test files listed in Step 3.

- [ ] **Step 1: Write the helper + its test**

Create `tests/support.py`:
```python
"""Shared test helpers."""

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

_counter = {"n": 0}


def make_guardian(*, email="", phone="", account=None, **guardian_kwargs):
    """Create a Guardian linked to a ParentAccount.

    Pass ``account`` to reuse one, or ``email``/``phone`` to mint a fresh
    account (a unique email is generated when none is given). ``email``/
    ``phone`` live on the account; remaining kwargs (full_name, personal_id,
    address, external_client_id) go on the Guardian.
    """
    if account is None:
        if not email:
            _counter["n"] += 1
            email = f"guardian{_counter['n']}@example.test"
        account = ParentAccount.objects.create(email=email.lower(), phone=phone)
    return Guardian.objects.create(parent_account=account, **guardian_kwargs)
```

Create `tests/members/test_support_make_guardian.py`:
```python
"""The make_guardian helper links a guardian to a parent account."""

import pytest

from apps.accounts.models import ParentAccount
from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def test_make_guardian_creates_linked_account():
    g = make_guardian(full_name="Anna", email="anna@example.com", phone="+371200")
    assert g.parent_account is not None
    assert g.parent_account.email == "anna@example.com"
    assert g.parent_account.phone == "+371200"
    assert g.full_name == "Anna"


def test_make_guardian_generates_unique_emails():
    a = make_guardian(full_name="A")
    b = make_guardian(full_name="B")
    assert a.parent_account_id != b.parent_account_id
    assert ParentAccount.objects.count() == 2


def test_make_guardian_reuses_account():
    acc = ParentAccount.objects.create(email="shared@example.com")
    a = make_guardian(full_name="A", account=acc)
    b = make_guardian(full_name="B", account=acc)
    assert a.parent_account_id == b.parent_account_id == acc.pk
```

- [ ] **Step 2: Run the helper test**

Run: `uv run pytest tests/members/test_support_make_guardian.py -v`
Expected: PASS (3 passed). (`Guardian.parent_account` is still nullable here, but the helper always sets it.)

- [ ] **Step 3: Sweep existing Guardian creations to provide an account**

For **every** `Guardian.objects.create(...)` / `Guardian(...)` call in these files, ensure a `parent_account` is supplied and move any `email=`/`phone=` kwarg onto that account. Prefer replacing the call with `make_guardian(...)` from `tests.support`; where a test already creates a `ParentAccount`, pass it via `account=`.

Files to sweep (every Guardian-construction site in each):
- `tests/conftest.py`
- `tests/agreements/conftest.py`
- `tests/billing/conftest.py`
- `tests/integrations/conftest.py`
- `tests/members/conftest.py`
- `tests/registrations/test_agreement_admin_polish.py`
- `tests/agreements/test_admin_cross_links.py`
- `tests/agreements/test_admin_sync_health.py`
- `tests/accounts/test_admin_cross_links.py`
- `tests/core/test_admin_links.py`
- `tests/members/test_audit_training_group.py`
- `tests/members/test_member_models.py`
- `tests/members/test_admin_cross_links.py`
- `tests/registrations/test_admin_review_context.py`
- `tests/members/test_member_export.py`
- `tests/members/test_admin_group_merge.py`
- `tests/registrations/test_guardian_read_through.py`
- `tests/registrations/test_admin_cross_links.py`
- `tests/billing/test_discount_engine.py`
- `tests/billing/test_send_due_invoices.py`
- `tests/registrations/test_admin_agreement_status_column.py`
- `tests/registrations/test_admin_changelist_quick_actions.py`
- `tests/registrations/test_guardian_dedup.py`
- `tests/members/test_guardian_resolution.py`
- `tests/integrations/test_docuseal_provider.py`

Transformation pattern (apply verbatim to each site):
```python
# BEFORE
g = Guardian.objects.create(full_name="V")
g = Guardian.objects.create(full_name="Anna", email="anna@example.com")
g = Guardian.objects.create(full_name="X", email="", phone="+371")
# AFTER  (import: from tests.support import make_guardian)
g = make_guardian(full_name="V")
g = make_guardian(full_name="Anna", email="anna@example.com")
g = make_guardian(full_name="X", email="", phone="+371")
```
Special cases:
- `tests/members/test_guardian_resolution.py:16` already passes `parent_account=account, email=account.email` — change to drop `email=` (it becomes a proxy): `Guardian.objects.create(parent_account=account)`.
- `tests/registrations/test_guardian_dedup.py` / `test_guardian_read_through.py`: these assert dedup/read-through semantics — keep any explicit `parent_account=` they already use; only remove `email=`/`phone=` kwargs and ensure an account is linked.
- A test that asserts `guardian.email == "..."` must set that email on the account (via `make_guardian(email=...)` or the reused `account`).
- `tests/agreements/test_backfill_migration.py` is a migration test — leave its historical-model `Guardian` construction as-is **unless** it sets `email`/`phone` (it predates this change and uses frozen model state; only touch it if it fails in Step 4).

- [ ] **Step 4: Run the full suite to confirm green after the sweep**

Run: `uv run pytest -q`
Expected: all pass (the model is unchanged so far — this step only proves the sweep didn't break anything). Fix any site the sweep missed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/ && \
git add tests/ && \
git commit -m "test: route all Guardian fixtures through make_guardian (account-linked) (guardian consolidation)"
```

---

### Task 2: `consolidate_guardians()` service + data migration

**Files:**
- Modify: `apps/members/services.py`
- Create: `apps/members/migrations/0006_consolidate_guardians.py`
- Test: `tests/members/test_guardian_consolidation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/members/test_guardian_consolidation.py
"""consolidate_guardians links orphans, creates missing accounts, merges dups."""

import pytest

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian, Member
from apps.members.services import consolidate_guardians

pytestmark = pytest.mark.django_db


def test_orphan_guardian_linked_to_existing_account_by_email():
    acc = ParentAccount.objects.create(email="p@example.com", phone="+371")
    g = Guardian.objects.create(full_name="P", email="p@example.com")  # orphan
    consolidate_guardians()
    g.refresh_from_db()
    assert g.parent_account_id == acc.pk


def test_orphan_with_no_account_gets_one_created():
    g = Guardian.objects.create(full_name="Q", email="q@example.com", phone="+37122")
    consolidate_guardians()
    g.refresh_from_db()
    assert g.parent_account is not None
    assert g.parent_account.email == "q@example.com"
    assert g.parent_account.phone == "+37122"  # phone carried to the new account


def test_account_phone_backfilled_from_guardian_when_empty():
    acc = ParentAccount.objects.create(email="r@example.com", phone="")
    Guardian.objects.create(full_name="R", email="r@example.com", phone="+37133")
    consolidate_guardians()
    acc.refresh_from_db()
    assert acc.phone == "+37133"


def test_duplicate_guardians_merge_to_survivor_with_external_client_id():
    acc = ParentAccount.objects.create(email="s@example.com")
    keep = Guardian.objects.create(full_name="S", email="s@example.com", external_client_id="IN-9")
    drop = Guardian.objects.create(full_name="S dup", email="s@example.com")
    m = Member.objects.create(full_name="Child", guardian=drop)
    consolidate_guardians()
    m.refresh_from_db()
    assert m.guardian_id == keep.pk                      # member repointed to survivor
    assert not Guardian.objects.filter(pk=drop.pk).exists()  # loser deleted
    assert Guardian.objects.get(pk=keep.pk).external_client_id == "IN-9"


def test_idempotent_on_clean_data():
    acc = ParentAccount.objects.create(email="t@example.com")
    Guardian.objects.create(full_name="T", parent_account=acc, email="t@example.com")
    consolidate_guardians()
    consolidate_guardians()  # second run is a no-op
    assert Guardian.objects.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_guardian_consolidation.py -v`
Expected: FAIL — `consolidate_guardians` does not exist.

- [ ] **Step 3: Implement `consolidate_guardians`**

In `apps/members/services.py`, add (use the real models — this is also import-safe for the migration, which will pass `apps` explicitly; see Step 4):
```python
from django.db import transaction


def consolidate_guardians(guardian_model=None, account_model=None, member_model=None,
                          application_model=None):
    """Link every Guardian to a ParentAccount by email (creating the account
    when missing), backfill the account phone, and merge duplicate guardians
    that resolve to the same account. Idempotent.

    Models are injected for migration use; defaults bind the live models.
    """
    from apps.accounts.models import ParentAccount as _Account
    from apps.members.models import Guardian as _Guardian
    from apps.members.models import Member as _Member
    from apps.registrations.models import RegistrationApplication as _Application

    Guardian = guardian_model or _Guardian
    ParentAccount = account_model or _Account
    Member = member_model or _Member
    Application = application_model or _Application

    with transaction.atomic():
        # 1. Ensure every guardian has an account (link by email, else create).
        for guardian in Guardian.objects.filter(parent_account__isnull=True):
            email = (guardian.email or "").strip().lower()
            account = None
            if email:
                account = ParentAccount.objects.filter(email__iexact=email).first()
            if account is None:
                account = ParentAccount.objects.create(
                    email=email or f"guardian-{guardian.pk}@placeholder.invalid",
                    phone=guardian.phone or "",
                )
            guardian.parent_account = account
            guardian.save(update_fields=["parent_account"])

        # 2. Backfill account.phone from a guardian where the account's is empty.
        for guardian in Guardian.objects.select_related("parent_account").all():
            acc = guardian.parent_account
            if acc and not acc.phone and guardian.phone:
                acc.phone = guardian.phone
                acc.save(update_fields=["phone"])

        # 3. Merge duplicates that share an account: keep a survivor, repoint
        #    members + applications, delete losers.
        seen: dict[int, object] = {}
        for guardian in Guardian.objects.all().order_by("pk"):
            acc_id = guardian.parent_account_id
            if acc_id not in seen:
                seen[acc_id] = guardian
                continue
            survivor = seen[acc_id]
            # Prefer the one with an external_client_id, then with members.
            survivor = _pick_survivor(survivor, guardian, Member)
            loser = guardian if survivor is not seen[acc_id] else (
                survivor if survivor is guardian else guardian
            )
            # Recompute cleanly: survivor vs the other of the pair.
            pair = [seen[acc_id], guardian]
            survivor = _pick_survivor(pair[0], pair[1], Member)
            loser = pair[0] if survivor is pair[1] else pair[1]
            Member.objects.filter(guardian=loser).update(guardian=survivor)
            Application.objects.filter(guardian=loser).update(guardian=survivor)
            if not survivor.external_client_id and loser.external_client_id:
                survivor.external_client_id = loser.external_client_id
                survivor.save(update_fields=["external_client_id"])
            loser.delete()
            seen[acc_id] = survivor


def _pick_survivor(a, b, member_model):
    """Choose the guardian to keep: external_client_id, then members, then pk."""
    if bool(a.external_client_id) != bool(b.external_client_id):
        return a if a.external_client_id else b
    a_members = member_model.objects.filter(guardian=a).count()
    b_members = member_model.objects.filter(guardian=b).count()
    if a_members != b_members:
        return a if a_members > b_members else b
    return a if a.pk <= b.pk else b
```

> Note for the implementer: the duplicate-merge loop above is written defensively; simplify if you can keep it correct — the contract is exactly the five test cases. Keep `_pick_survivor`'s ordering (external_client_id → member count → lowest pk).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/members/test_guardian_consolidation.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Create the data migration**

`apps/members/migrations/0006_consolidate_guardians.py`:
```python
from django.db import migrations


def forwards(apps, schema_editor):
    from apps.members.services import consolidate_guardians

    consolidate_guardians(
        guardian_model=apps.get_model("members", "Guardian"),
        account_model=apps.get_model("accounts", "ParentAccount"),
        member_model=apps.get_model("members", "Member"),
        application_model=apps.get_model("registrations", "RegistrationApplication"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0005_traininggroup_uniq_training_group_name_ci"),
        ("accounts", "__latest__"),
        ("registrations", "__latest__"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
```
Replace each `"__latest__"` with the actual latest migration name for that app — run `uv run python manage.py showmigrations accounts registrations | tail` and use the last applied name (the migration must run *after* those apps' models exist).

- [ ] **Step 6: Verify migration applies + commit**

```bash
uv run python manage.py migrate members 2>&1 | tail -3   # applies 0006 on the dev DB
uv run pytest tests/members/test_guardian_consolidation.py -q && \
uv run ruff check apps/members/services.py && \
uv run mypy apps/members/services.py && \
git add apps/members/services.py apps/members/migrations/0006_consolidate_guardians.py tests/members/test_guardian_consolidation.py && \
git commit -m "feat(members): consolidate_guardians service + data migration (link/merge orphans)"
```

---

> **CORRECTION (during execution):** Tasks 3 and 4 below were **merged into one atomic task**.
> Moving the writers off the `Guardian.email`/`phone` columns (Task 3) while readers still read those
> columns (`guardian_contact_phone` gates submission; `mark_agreement_sent` reads `guardian.email`)
> breaks ~144 tests. The proxies (Task 4) must land **with** the writer collapse so readers
> transparently read the account. The combined task = model proxies + `parent_account` NOT NULL +
> schema migration `0007` + the writer changes below + cleanup of the temporary test-fixture
> Guardian-column mirror writes. No extra reader files need editing (the proxies cover them).

### Task 3: Single-writer collapse (drop email mirror, phone → account, approval fix)

**Files:**
- Modify: `apps/accounts/services.py`, `apps/registrations/services.py`, `apps/members/services.py`
- Test: `tests/accounts/test_change_parent_email.py` (extend), `tests/registrations/` (extend an existing draft/submit test or add one)

- [ ] **Step 1: Write the failing tests**

Add to `tests/members/test_guardian_consolidation.py` (or a new `tests/registrations/test_guardian_single_writer.py`):
```python
# tests/registrations/test_guardian_single_writer.py
"""Contact-field writes flow to the ParentAccount, not a Guardian mirror."""

import pytest

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email
from apps.members.models import Guardian

pytestmark = pytest.mark.django_db


def test_change_parent_email_updates_only_the_account():
    acc = ParentAccount.objects.create(email="old@example.com")
    g = Guardian.objects.create(full_name="G", parent_account=acc)
    change_parent_email(acc, "new@example.com")
    acc.refresh_from_db()
    assert acc.email == "new@example.com"
    # The guardian reflects it through the (Task 4) proxy / FK — no stale mirror.
    assert g.parent_account.email == "new@example.com"
```

(`change_parent_email` keeps working before Task 4; this test pins that it no longer needs a Guardian.email column to update.)

- [ ] **Step 2: Run to verify current behaviour, then change the writers**

Run: `uv run pytest tests/registrations/test_guardian_single_writer.py -v` (passes today via the mirror; will still pass after we drop the mirror).

Apply these edits:

**(a) `apps/accounts/services.py` — drop the mirror.** Remove the final line of `change_parent_email`:
```python
    Guardian.objects.filter(parent_account=account).update(email=normalized)
```
and the now-unused `from apps.members.models import Guardian` import inside the function. Update the docstring to drop "and updates the linked Guardian.email mirror".

**(b) `apps/members/services.py` — `resolve_guardian_for_account`.** Drop the email default (email is now a proxy):
```python
    guardian, _created = Guardian.objects.get_or_create(parent_account=account)
```
Update the docstring (remove the "email is mirrored" sentence).

**(c) `apps/registrations/services.py` — draft-save phone → account.** In the `if application.guardian_id is not None:` block (lines ~426-432): remove the `_guardian.phone = ...` line and drop `"phone"` from `update_fields`; instead write the phone to the account:
```python
    if application.guardian_id is not None:
        _guardian = application.guardian
        _guardian.full_name = str(data.get("guardian_full_name", "")).strip()
        _guardian.personal_id = str(data.get("guardian_personal_id", "")).strip()
        _guardian.address = str(data.get("guardian_declared_address", "")).strip()
        _guardian.save(update_fields=["full_name", "personal_id", "address"])
        account = _guardian.parent_account
        new_phone = str(data.get("guardian_phone", "")).strip()
        if account is not None and new_phone and account.phone != new_phone:
            account.phone = new_phone
            account.save(update_fields=["phone", "updated_at"])
```

**(d) `apps/registrations/services.py` — delete the submit-time phone sync** block (lines ~641-648, the `# Sync the parent account's phone ...` block) entirely — draft-save now owns it.

**(e) `apps/registrations/services.py` — approval orphan fallback** (lines ~768-776): replace the bare-create branch so a guardian is never created without an account:
```python
    guardian = application.guardian
    if guardian is None:
        if application.parent_account_id is None:
            raise ValueError("Cannot approve an application without a parent account.")
        guardian = resolve_guardian_for_account(application.parent_account)
        application.guardian = guardian
```

- [ ] **Step 3: Run the writer tests + suite**

Run: `uv run pytest tests/accounts/ tests/registrations/ tests/members/ -q`
Expected: green. (If a test asserted the old submit-time `account.phone` sync, update it to the draft-save path.)

- [ ] **Step 4: Lint/type + commit**

```bash
uv run ruff check apps/accounts/services.py apps/registrations/services.py apps/members/services.py tests/registrations/test_guardian_single_writer.py && \
uv run mypy apps/accounts/services.py apps/registrations/services.py apps/members/services.py && \
git add apps/accounts/services.py apps/registrations/services.py apps/members/services.py tests/registrations/test_guardian_single_writer.py && \
git commit -m "feat: single-writer contact fields — account owns email/phone (guardian consolidation)"
```

---

### Task 4: Proxies + drop columns + NOT NULL

**Files:**
- Modify: `apps/members/models.py`
- Create: `apps/members/migrations/0007_guardian_proxy_fields.py` (via makemigrations)
- Test: `tests/members/test_guardian_proxy_fields.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/members/test_guardian_proxy_fields.py
"""Guardian.email/phone proxy the linked ParentAccount; parent_account is required."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import Field

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

pytestmark = pytest.mark.django_db


def test_email_and_phone_proxy_the_account():
    acc = ParentAccount.objects.create(email="proxy@example.com", phone="+37199")
    g = Guardian.objects.create(full_name="G", parent_account=acc)
    assert g.email == "proxy@example.com"
    assert g.phone == "+37199"


def test_proxy_reflects_account_update():
    acc = ParentAccount.objects.create(email="a@example.com", phone="+1")
    g = Guardian.objects.create(full_name="G", parent_account=acc)
    acc.phone = "+2"
    acc.save(update_fields=["phone"])
    assert Guardian.objects.get(pk=g.pk).phone == "+2"


def test_email_phone_are_not_db_columns():
    field_names = {f.name for f in Guardian._meta.get_fields() if isinstance(f, Field)}
    assert "email" not in field_names
    assert "phone" not in field_names


def test_parent_account_is_required():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Guardian.objects.create(full_name="No account")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_guardian_proxy_fields.py -v`
Expected: FAIL — `email`/`phone` are still columns; the NOT NULL create still succeeds.

- [ ] **Step 3: Change the model**

In `apps/members/models.py`, on `Guardian`:
- Remove the `email = models.EmailField(...)` and `phone = models.CharField(...)` fields.
- Change `parent_account` to `null=False` (drop `null=True`; keep `blank=True` off or on per form needs — set `null=False`, and keep `on_delete=models.PROTECT`, `related_name="guardian"`).
- Add the proxies (place after the field block):
```python
    @property
    def email(self) -> str:
        return self.parent_account.email if self.parent_account_id else ""

    @property
    def phone(self) -> str:
        return self.parent_account.phone if self.parent_account_id else ""
```

- [ ] **Step 4: Generate + apply the schema migration**

```bash
uv run python manage.py makemigrations members
```
Confirm the generated `0007_*` has `AlterField(parent_account, null=False)` + `RemoveField(email)` + `RemoveField(phone)` and depends on `0006_consolidate_guardians`. Then:
```bash
uv run python manage.py migrate members 2>&1 | tail -3
uv run pytest tests/members/test_guardian_proxy_fields.py -v
```
Expected: migration applies cleanly on the consolidated dev DB; 4 passed.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/members/ -q && \
uv run ruff check apps/members/models.py tests/members/test_guardian_proxy_fields.py && \
uv run mypy apps/members/models.py && \
git add apps/members/models.py apps/members/migrations/0007_*.py tests/members/test_guardian_proxy_fields.py && \
git commit -m "feat(members): Guardian email/phone are account proxies; parent_account NOT NULL"
```

---

### Task 5: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: pytest/ruff/mypy green; "No changes detected" (migrations 0006 + 0007 committed). Fail loud on any failure.

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "Guardian/ParentAccount consolidation — Plan 1 delivered" entry: `Guardian.email`/`phone` are now `@property` proxies of the linked `ParentAccount`; `parent_account` is NOT NULL; `consolidate_guardians` data migration linked/merged orphan+duplicate guardians; `change_parent_email`/draft-save/approval write the account only; `make_guardian` test helper. Note Plan 2 (unified admin) remains.
- `docs/milestones.md`: record Plan 1 delivered under a new "Guardian consolidation" line; Plan 2 (unified admin) pending.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record guardian consolidation Plan 1 (de-dup fields + 1:1)"
```

---

## Self-Review Notes

- **Spec coverage:** §3.1 proxies/NOT NULL → T4; §3.2 single-writer (change_parent_email, draft-save phone, drop submit sync, accessor unchanged, approval fix) → T3; §3.3 data migration link+merge + schema → T2 (data) + T4 (schema); §5 fixture sweep → T1; docs → T5.
- **Ordering rationale:** T1 (sweep) before T4 (NOT NULL) keeps the suite green; T2 (data migration) before T4 (schema drop) so the link/merge runs while columns exist; the schema migration `0007` depends on the data migration `0006`.
- **No reader churn:** `guardian.email`/`guardian.phone` reads (billing, DocuSeal, agreements) are untouched — verified no ORM filters on those names.
- **`guardian_contact_phone` accessor** needs no change (reads `self.guardian.phone`, now the proxy).
- **Idempotency:** `consolidate_guardians` is guarded so a re-run (or a clean DB) is a no-op — tested.
- **Risk flagged:** the duplicate-merge loop in T2 Step 3 is the subtlest code; its contract is the five tests. The implementer may simplify provided all five pass and `_pick_survivor` ordering holds.
- **Type consistency:** `consolidate_guardians`/`_pick_survivor`/`make_guardian` names used identically across tasks; migration numbers `0006`/`0007` consistent.
