# FK Cēsis MMS MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build MVP Django system for FK Cēsis youth-member registration, admin approval, secure identity-document handling, and Invoice Ninja billing orchestration.

**Architecture:** Use a Django monolith with PostgreSQL, server-rendered parent/admin flows, private document storage, and background jobs for OCR, email, and Invoice Ninja sync. Keep application workflow, member registry, and billing rules in core app models while isolating third-party API state in dedicated integration records.

**Tech Stack:** Python 3.12+, Django, PostgreSQL, `uv`, pytest, ruff, mypy, django-storages or equivalent private storage adapter, Celery or Django-Q style job runner, email magic links, Invoice Ninja API, OCR provider API.

---

## 1. Scope split and delivery strategy

This spec is one coherent MVP, but implementation should be delivered in six bounded units:
1. project foundation and security baseline
2. registration intake and parent magic-link flow
3. admin review and member creation
4. billing rules and Invoice Ninja sync
5. admin operations screens and CSV export
6. production-readiness docs/configuration

Each unit must end in green tests and a review checkpoint before moving on.
Develop each task or feature in its own git worktree branch, and merge back to `main` only after user approval.
Expose usable app slices on LAN as early as practical so the user can perform acceptance testing before late-stage polish.

## 2. File-by-file architecture plan

### Root project files
- Create: `AGENTS.md`
  - project purpose, stack, commands, conventions, relevant skills
- Create: `.gitignore`
  - Python, Django, env, uploads, `.superpowers/`, local db/files
- Create: `.env.example`
  - DB, Django, email, Invoice Ninja, OCR, storage settings
- Create: `README.md`
  - setup, local run, test/lint/type-check, architecture summary
- Create: `pyproject.toml`
  - project metadata, dependencies, tool config for ruff/pytest/mypy
- Create: `manage.py`
- Create: `fk_cesis_mms/__init__.py`
- Create: `fk_cesis_mms/settings.py`
- Create: `fk_cesis_mms/urls.py`
- Create: `fk_cesis_mms/wsgi.py`
- Create: `fk_cesis_mms/asgi.py`
- Create: `fk_cesis_mms/celery.py` or job-runner bootstrap equivalent

### Domain apps
- Create: `apps/core/`
  - shared enums, base models, audit helpers, time utilities
- Create: `apps/accounts/`
  - admin auth wiring, parent magic-link models/services/views
- Create: `apps/registrations/`
  - registration application, guardian snapshot, child data, OCR intake flow
- Create: `apps/members/`
  - member records, training groups, guardian canonical model
- Create: `apps/billing/`
  - membership plan, sibling discount rules, invoice sync orchestration
- Create: `apps/documents/`
  - private document model, storage adapter, document access views
- Create: `apps/integrations/`
  - Invoice Ninja and OCR clients, payload mappers, retry status records
- Create: `apps/admin_ops/`
  - custom admin dashboards, filters, CSV export actions if needed

### Template/static files
- Create: `templates/base.html`
- Create: `templates/parent_portal/*.html`
- Create: `templates/admin_ops/*.html`
- Create: `static/css/app.css`
- Create: `static/css/admin.css`

### Tests
- Create: `tests/conftest.py`
- Create: `tests/factories/`
- Create: `tests/accounts/`
- Create: `tests/registrations/`
- Create: `tests/members/`
- Create: `tests/billing/`
- Create: `tests/documents/`
- Create: `tests/integrations/`
- Create: `tests/admin_ops/`

### Documentation
- Already created: `docs/milestones.md`
- Already created: `docs/superpowers/specs/2026-05-04-fk-cesis-mms-mvp-design.md`
- Create/update during implementation:
  - `docs/superpowers/plans/2026-05-04-fk-cesis-mms-mvp-implementation.md`
  - `README.md`
  - `AGENTS.md`
  - optional `docs/security-baseline.md`
  - optional `docs/invoice-ninja-mapping.md`

## 3. Design decisions

### 3.1 Monolith over services
**Why:** MVP risk is business-rule correctness and sensitive-data handling, not horizontal scale. One deployable app reduces moving parts and speeds review.

### 3.2 Separate `RegistrationApplication` from `Member`
**Why:** Draft and fix-request flows need mutable intake state without creating partial member records or duplicating approval logic.

### 3.3 Separate `ParentAccount` from `Guardian`
**Why:** Login identity and legal/billing identity are not guaranteed to stay identical. This keeps future multi-guardian or delegated-access changes possible.

### 3.4 Background jobs for all external API work
**Why:** OCR and Invoice Ninja can fail or slow down. Async jobs allow retries, redaction-safe logging, and visible sync state without blocking UI.

### 3.5 Private storage with app-mediated downloads
**Why:** Identity documents must never be world-readable. Streaming files through authenticated views provides auditable access control.

### 3.6 Invoice Ninja as payment truth source
**Why:** Avoids duplicate finance state and reconciliation complexity. App computes membership billing setup; Invoice Ninja owns invoices and payment status.

### 3.7 Server-rendered UI first
**Why:** Fastest way to deliver reliable admin-heavy flows while keeping frontend complexity low. JavaScript should only enhance file upload, OCR prefill UX, and filters where needed.

## 4. Test strategy

### Test framework
- `pytest` with `pytest-django`
- factory-based data setup
- integration tests with HTTP client mocking for OCR and Invoice Ninja
- selective view tests for templates/forms
- model/service unit tests for billing rules and workflow transitions

### What to test
- registration workflow states and permission checks
- magic-link generation, expiry, and single-use behavior
- sibling-discount detection and opt-out logic
- installment schedule generation for Jan–Jun and Aug–Nov only
- private document access checks and audit events
- approval flow creating exactly one member
- Invoice Ninja sync payload mapping and retry behavior
- CSV export columns and filtering behavior

### What not to test
- Django internals
- exact third-party API implementation details beyond payload/response contract used by app
- CSS rendering details
- OCR provider accuracy itself

### Test file structure
- `tests/accounts/test_magic_links.py`
- `tests/registrations/test_application_workflow.py`
- `tests/registrations/test_parent_edit_permissions.py`
- `tests/documents/test_private_document_access.py`
- `tests/members/test_member_creation_on_approval.py`
- `tests/billing/test_membership_rules.py`
- `tests/billing/test_invoice_ninja_sync.py`
- `tests/admin_ops/test_member_filters_and_export.py`

## 5. Acceptance criteria per implementation unit

### Unit A — Foundation
- Django project boots locally via documented `uv` commands
- PostgreSQL settings work in local env
- tests, ruff, and mypy all run from documented commands
- secrets and storage config externalized

### Unit B — Registration intake
- parent can create, edit, and submit minor registration in Latvian
- parent can upload document securely
- OCR assist can prefill without blocking submission
- parent can resume via magic link
- first usable parent flow can be launched on LAN for user acceptance testing

### Unit C — Admin review
- admin can request fixes, reject, or approve
- parent can respond to fix request
- approval creates official member once
- admin can assign one training group and billing start month

### Unit D — Billing
- app can compute upfront or 10-installment membership plan
- sibling-discount offer is based on guardian personal ID match
- parent full-price opt-out is persisted
- Invoice Ninja recurring billing sync is triggered after approval
- payment sync status is visible and retryable

### Unit E — Operations
- member list supports search/filter by status/group
- admin can see payment-status overview
- CSV export produces agreed MVP data
- document delete action exists and is audited

### Unit F — Docs and readiness
- README and AGENTS are accurate
- `.env.example` covers all required settings
- deployment/security notes exist

## 6. Implementation tasks

## 6.1 Execution status update

- **Task 1 completed** on 2026-05-04.
- Task 1 delivered: `.gitignore`, `pyproject.toml`, `.env.example`, `README.md`, `AGENTS.md`, `manage.py`, `fk_cesis_mms/__init__.py`, `fk_cesis_mms/settings.py`, `fk_cesis_mms/urls.py`, `fk_cesis_mms/asgi.py`, `fk_cesis_mms/wsgi.py`, `mypy.ini`, and `tests/test_project_smoke.py`.
- Verified green after Task 1: `uv run pytest -q && uv run ruff check . && uv run mypy .`.
- **Task 2 was absorbed into Task 1** because the initial scaffold already included the minimal Django package and settings work.
- **Task 3 completed** on 2026-05-04.
- Task 3 delivered: `apps/` package skeleton, app configs for `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, `integrations`, `apps/core/models.py` with abstract `TimeStampedModel`, `apps/core/enums.py`, `apps/core/audit.py`, `tests/core/test_base_models.py`, and `tests/conftest.py`.
- Verified green after Task 3: `uv run pytest -q && uv run ruff check . && uv run mypy .`.
- **Task 4 completed** on 2026-05-04.
- Task 4 delivered: `ParentAccount`, `MagicLinkToken`, magic-link request/verify/logout flow, `ensure_admin_user` command, `.env` autoload, tunnel/LAN-aware settings coverage, and Task 4 account/settings tests.
- Verified green after Task 4: `uv run pytest -q && uv run ruff check . && uv run mypy .`.
- **Task 5 completed** on 2026-05-05.
- Task 5 delivered: `RegistrationApplication`, `Document`, draft save/submit flow, anonymous same-browser draft continuation, magic-link parent portal, single edit form with save-draft and submit actions, and native browser date picker for child birth date.
- Verified green after Task 5: `uv run pytest -q && uv run ruff check . && uv run mypy .`.
- **Current user acceptance-test URL:** `http://192.168.3.245:8000`.
- **Next active task:** Task 6 (`Admin review and member creation`).

### Task 1: Project bootstrap and repo metadata — completed

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `AGENTS.md`

- [ ] **Step 1: Write the failing smoke test list**

```python
# tests/test_project_smoke.py
import importlib


def test_django_settings_module_imports():
    module = importlib.import_module("fk_cesis_mms.settings")
    assert module.SECRET_KEY is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_project_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fk_cesis_mms'`

- [ ] **Step 3: Create project metadata and tool config**

```toml
# pyproject.toml
[project]
name = "fk-cesis-mms"
version = "0.1.0"
description = "FK Cesis member management system"
requires-python = ">=3.12"
dependencies = [
  "django>=5.1,<5.2",
  "psycopg[binary]>=3.2,<3.3",
  "pytest>=8.3,<8.4",
  "pytest-django>=4.9,<5",
  "ruff>=0.6,<0.7",
  "mypy>=1.11,<1.12",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "fk_cesis_mms.settings"
pythonpath = ["."]
```
```

- [ ] **Step 4: Create root docs and ignore rules**

```gitignore
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.env
uploads/
media/
staticfiles/
.superpowers/
```
```

```md
# AGENTS.md
## Project Purpose
FK Cēsis youth member registration, approval, and billing MVP.

## Stack
- Python
- Django
- PostgreSQL
- uv

## Commands
- `uv sync`
- `uv run pytest`
- `uv run ruff check .`
- `uv run mypy .`
```
```

- [ ] **Step 5: Run smoke test again**

Run: `uv run pytest tests/test_project_smoke.py -v`
Expected: FAIL with missing Django settings file, not import path error

### Task 2: Django scaffold and settings — absorbed into Task 1 (skip)

**Files:**
- Create: `manage.py`
- Create: `fk_cesis_mms/__init__.py`
- Create: `fk_cesis_mms/settings.py`
- Create: `fk_cesis_mms/urls.py`
- Create: `fk_cesis_mms/wsgi.py`
- Create: `fk_cesis_mms/asgi.py`
- Modify: `tests/test_project_smoke.py`

Implementation note:
- The minimal Django scaffold from this task already exists from Task 1 execution.
- Do not re-run this task unless Task 1 is reverted.
- Continue with Task 3.

- [x] **Step 1: Expand failing settings test**

```python
from django.conf import settings


def test_installed_apps_contains_django_admin():
    assert "django.contrib.admin" in settings.INSTALLED_APPS
```

- [x] **Step 2: Run targeted tests to verify failure**

Run: `uv run pytest tests/test_project_smoke.py -v`
Expected: FAIL because settings module does not exist or is incomplete

- [x] **Step 3: Add minimal Django scaffold**

```python
# fk_cesis_mms/settings.py
SECRET_KEY = "dev-only-placeholder"
DEBUG = True
ALLOWED_HOSTS = ["*"]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
ROOT_URLCONF = "fk_cesis_mms.urls"
```
```

- [x] **Step 4: Run targeted tests to verify pass**

Run: `uv run pytest tests/test_project_smoke.py -v`
Expected: PASS

### Task 3: Core apps skeleton and base models

**Files:**
- Create: `apps/core/apps.py`
- Create: `apps/core/models.py`
- Create: `apps/core/enums.py`
- Create: `apps/core/audit.py`
- Create: `apps/accounts/apps.py`
- Create: `apps/registrations/apps.py`
- Create: `apps/members/apps.py`
- Create: `apps/billing/apps.py`
- Create: `apps/documents/apps.py`
- Create: `apps/integrations/apps.py`
- Create: `tests/core/test_base_models.py`
- Modify: `fk_cesis_mms/settings.py`

- [ ] **Step 1: Write failing base-model test**

```python
from apps.core.models import TimeStampedModel


def test_timestamped_model_has_created_and_updated_fields():
    field_names = {field.name for field in TimeStampedModel._meta.fields}
    assert {"created_at", "updated_at"}.issubset(field_names)
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/core/test_base_models.py -v`
Expected: FAIL with module import error

- [ ] **Step 3: Add app skeleton and shared base model**

```python
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```
```

- [ ] **Step 4: Register apps in settings and rerun test**

Run: `uv run pytest tests/core/test_base_models.py -v`
Expected: PASS

### Task 4: Parent accounts and magic links

**Files:**
- Create: `apps/accounts/models.py`
- Create: `apps/accounts/services.py`
- Create: `apps/accounts/views.py`
- Create: `apps/accounts/urls.py`
- Create: `tests/accounts/test_magic_links.py`
- Modify: `fk_cesis_mms/urls.py`

- [ ] **Step 1: Write failing single-use magic-link test**

```python
def test_magic_link_token_is_single_use(parent_account_factory):
    account = parent_account_factory()
    token = create_magic_link_token(account)
    session = consume_magic_link_token(token)
    assert session.account_id == account.id
    assert consume_magic_link_token(token) is None
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/accounts/test_magic_links.py::test_magic_link_token_is_single_use -v`
Expected: FAIL because token service does not exist

- [ ] **Step 3: Implement minimal models and token service**

```python
class ParentAccount(TimeStampedModel):
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)


class MagicLinkToken(TimeStampedModel):
    account = models.ForeignKey(ParentAccount, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
```
```

- [ ] **Step 4: Run targeted test to verify pass**

Run: `uv run pytest tests/accounts/test_magic_links.py::test_magic_link_token_is_single_use -v`
Expected: PASS

### Task 5: Registration application workflow — completed

**Files:**
- Create: `apps/registrations/models.py`
- Create: `apps/registrations/forms.py`
- Create: `apps/registrations/services.py`
- Create: `apps/registrations/views.py`
- Create: `apps/registrations/urls.py`
- Create: `tests/registrations/test_application_workflow.py`
- Create: `tests/registrations/test_parent_edit_permissions.py`

- [ ] **Step 1: Write failing approval-state transition test**

```python
def test_submitted_application_can_transition_to_fix_requested(application_factory):
    application = application_factory(status="submitted")
    request_fix(application, note="Upload clearer document")
    application.refresh_from_db()
    assert application.status == "fix_requested"
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/registrations/test_application_workflow.py::test_submitted_application_can_transition_to_fix_requested -v`
Expected: FAIL because workflow model/service does not exist

- [ ] **Step 3: Implement application model and transition service**

```python
class RegistrationApplication(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft"
        SUBMITTED = "submitted"
        FIX_REQUESTED = "fix_requested"
        APPROVED = "approved"
        REJECTED = "rejected"

    parent_account = models.ForeignKey("accounts.ParentAccount", on_delete=models.CASCADE)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    guardian_full_name = models.CharField(max_length=255)
    guardian_personal_id = models.CharField(max_length=32)
    child_full_name = models.CharField(max_length=255)
```
```

- [ ] **Step 4: Run targeted workflow tests to verify pass**

Run: `uv run pytest tests/registrations/test_application_workflow.py -v`
Expected: PASS

### Task 6: Private document storage and OCR status

**Files:**
- Create: `apps/documents/models.py`
- Create: `apps/documents/services.py`
- Create: `apps/documents/views.py`
- Create: `tests/documents/test_private_document_access.py`
- Create: `tests/documents/test_ocr_status.py`

- [ ] **Step 1: Write failing document-access permission test**

```python
def test_parent_cannot_download_other_family_document(client, document_factory, parent_session_factory):
    document = document_factory()
    client.force_login(parent_session_factory(other_family=True).account.user)
    response = client.get(document.download_url)
    assert response.status_code == 404
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/documents/test_private_document_access.py -v`
Expected: FAIL because document access view does not exist

- [ ] **Step 3: Implement document model and protected download view**

```python
class Document(TimeStampedModel):
    application = models.ForeignKey("registrations.RegistrationApplication", null=True, blank=True, on_delete=models.CASCADE)
    member = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.CASCADE)
    kind = models.CharField(max_length=32)
    file = models.FileField(upload_to="identity-documents/")
    ocr_status = models.CharField(max_length=32, default="pending")
    deleted_at = models.DateTimeField(null=True, blank=True)
```
```

- [ ] **Step 4: Run document tests to verify pass**

Run: `uv run pytest tests/documents/test_private_document_access.py tests/documents/test_ocr_status.py -v`
Expected: PASS

### Task 7: Admin review and member creation

**Files:**
- Create: `apps/members/models.py`
- Create: `apps/members/services.py`
- Create: `tests/members/test_member_creation_on_approval.py`
- Modify: `apps/registrations/services.py`

- [ ] **Step 1: Write failing member-creation test**

```python
def test_approval_creates_member_once(application_factory):
    application = application_factory(status="submitted")
    member = approve_application(application, group_id=None, billing_start_month=1)
    assert member.child_full_name == application.child_full_name
    assert approve_application(application, group_id=None, billing_start_month=1).id == member.id
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/members/test_member_creation_on_approval.py -v`
Expected: FAIL because approval service does not create member

- [ ] **Step 3: Implement `Guardian`, `Member`, `TrainingGroup`, and approval logic**

```python
class Guardian(TimeStampedModel):
    full_name = models.CharField(max_length=255)
    personal_id = models.CharField(max_length=32, unique=True)
    email = models.EmailField()


class Member(TimeStampedModel):
    guardian = models.ForeignKey(Guardian, on_delete=models.PROTECT)
    child_full_name = models.CharField(max_length=255)
    birth_date = models.DateField(null=True, blank=True)
    training_group = models.ForeignKey("members.TrainingGroup", null=True, blank=True, on_delete=models.PROTECT)
```
```

- [ ] **Step 4: Run member-creation tests to verify pass**

Run: `uv run pytest tests/members/test_member_creation_on_approval.py -v`
Expected: PASS

### Task 8: Membership plan and sibling discount rules

**Files:**
- Create: `apps/billing/models.py`
- Create: `apps/billing/rules.py`
- Create: `tests/billing/test_membership_rules.py`

- [ ] **Step 1: Write failing sibling-discount and installment tests**

```python
def test_second_child_gets_discount_offer_when_guardian_personal_id_matches(member_factory):
    member_factory(guardian__personal_id="010101-12345")
    offer = detect_sibling_discount(guardian_personal_id="010101-12345")
    assert offer.is_discount_available is True
    assert offer.discount_percent == 50


def test_installment_schedule_skips_july_and_december():
    schedule = build_installment_months(start_month=1)
    assert schedule == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11]
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `uv run pytest tests/billing/test_membership_rules.py -v`
Expected: FAIL because billing rules module does not exist

- [ ] **Step 3: Implement membership plan and rule functions**

```python
class MembershipPlan(TimeStampedModel):
    member = models.ForeignKey("members.Member", on_delete=models.CASCADE)
    billing_year = models.PositiveIntegerField()
    payment_mode = models.CharField(max_length=16, choices=[("upfront", "upfront"), ("installments", "installments")])
    annual_fee_cents = models.PositiveIntegerField(default=30000)
    sibling_discount_percent = models.PositiveIntegerField(default=0)
    sibling_discount_opt_out = models.BooleanField(default=False)
    billing_start_month = models.PositiveSmallIntegerField()
```
```

- [ ] **Step 4: Run billing-rule tests to verify pass**

Run: `uv run pytest tests/billing/test_membership_rules.py -v`
Expected: PASS

### Task 9: Invoice Ninja integration layer

**Files:**
- Create: `apps/integrations/invoice_ninja_client.py`
- Create: `apps/billing/services.py`
- Create: `apps/billing/tasks.py`
- Create: `tests/billing/test_invoice_ninja_sync.py`

- [ ] **Step 1: Write failing payload-mapping test**

```python
def test_sync_member_to_invoice_ninja_maps_guardian_as_payer(invoice_ninja_mock, approved_member_factory):
    member = approved_member_factory()
    result = sync_member_billing(member.id)
    assert result.customer_email == member.guardian.email
    assert result.recurring_invoice_created is True
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/billing/test_invoice_ninja_sync.py -v`
Expected: FAIL because sync service does not exist

- [ ] **Step 3: Implement client adapter and sync orchestration**

```python
@dataclass
class InvoiceSyncResult:
    customer_external_id: str
    recurring_invoice_external_id: str
    recurring_invoice_created: bool
    customer_email: str
```
```

- [ ] **Step 4: Run integration tests to verify pass**

Run: `uv run pytest tests/billing/test_invoice_ninja_sync.py -v`
Expected: PASS

### Task 10: Payment status sync and retry visibility

**Files:**
- Create: `apps/billing/sync_models.py` or extend `apps/billing/models.py`
- Create: `tests/billing/test_payment_status_sync.py`
- Modify: `apps/billing/tasks.py`

- [ ] **Step 1: Write failing payment-sync snapshot test**

```python
def test_payment_sync_updates_latest_status(invoice_sync_event_factory, invoice_ninja_mock):
    event = invoice_sync_event_factory(external_invoice_id="inv_123")
    snapshot = sync_invoice_payment_status(event.external_invoice_id)
    assert snapshot.status in {"paid", "partial", "pending", "overdue"}
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/billing/test_payment_status_sync.py -v`
Expected: FAIL because status sync function does not exist

- [ ] **Step 3: Implement sync event snapshots and retry status fields**

```python
class InvoiceSyncEvent(TimeStampedModel):
    member = models.ForeignKey("members.Member", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=32)
    external_object_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=32)
    retry_count = models.PositiveIntegerField(default=0)
    redacted_payload = models.JSONField(default=dict)
```
```

- [ ] **Step 4: Run payment-sync tests to verify pass**

Run: `uv run pytest tests/billing/test_payment_status_sync.py -v`
Expected: PASS

### Task 11: Admin operations screens and CSV export

**Files:**
- Create: `apps/admin_ops/views.py`
- Create: `apps/admin_ops/urls.py`
- Create: `templates/admin_ops/member_list.html`
- Create: `tests/admin_ops/test_member_filters_and_export.py`
- Modify: `fk_cesis_mms/urls.py`

- [ ] **Step 1: Write failing CSV export test**

```python
def test_member_export_contains_status_group_and_payment_columns(admin_client, approved_member_factory):
    approved_member_factory()
    response = admin_client.get("/admin-ops/members/export/")
    assert response.status_code == 200
    assert "group" in response.content.decode()
    assert "payment_status" in response.content.decode()
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/admin_ops/test_member_filters_and_export.py -v`
Expected: FAIL because export view does not exist

- [ ] **Step 3: Implement member list filters and CSV export view**

```python
MEMBER_EXPORT_COLUMNS = [
    "member_id",
    "child_full_name",
    "guardian_full_name",
    "status",
    "training_group",
    "payment_status",
]
```
```

- [ ] **Step 4: Run admin-ops tests to verify pass**

Run: `uv run pytest tests/admin_ops/test_member_filters_and_export.py -v`
Expected: PASS

### Task 12: Documentation and verification pass

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.env.example`
- Optional create: `docs/security-baseline.md`
- Optional create: `docs/invoice-ninja-mapping.md`

- [ ] **Step 1: Write failing docs consistency check**

```python
from pathlib import Path


def test_readme_mentions_uv_and_pytest_commands():
    readme = Path("README.md").read_text()
    assert "uv sync" in readme
    assert "uv run pytest" in readme
```

- [ ] **Step 2: Run targeted test to verify failure**

Run: `uv run pytest tests/test_docs_smoke.py -v`
Expected: FAIL if docs are stale or missing commands

- [ ] **Step 3: Update docs to match actual implementation**

```md
## Development
- `uv sync`
- `uv run python manage.py migrate`
- `uv run python manage.py runserver`
- `uv run pytest`
- `uv run ruff check .`
- `uv run mypy .`
```
```

- [ ] **Step 4: Run docs test and full verification suite**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all commands PASS

## 7. Verification commands

Run after each unit:
- `uv run pytest tests/<target> -v`

Run before any completion claim:
- `uv run pytest -q`
- `uv run ruff check .`
- `uv run mypy .`

## 8. Documentation scope

Must create/update:
- `AGENTS.md` with commands, stack, conventions, and relevant skills
- `README.md` with setup/run/test flow
- `.env.example` with integration settings
- `docs/milestones.md` maintained as units complete
- design spec and implementation plan kept current if scope changes

Should add if integration details grow:
- `docs/security-baseline.md`
- `docs/invoice-ninja-mapping.md`

## 9. Plan self-review

### Spec coverage check
- registration, parent access, admin review, member creation: covered by Tasks 4–7
- secure documents and OCR assist: covered by Task 6
- billing rules and Invoice Ninja sync: covered by Tasks 8–10
- admin operations and export: covered by Task 11
- docs and ops readiness: covered by Tasks 1 and 12
- milestone tracking and local commands: covered by Task 1 and documentation scope

### Placeholder scan
- no TBD/TODO placeholders left in tasks
- every task names exact files and concrete test commands

### Type consistency check
- `RegistrationApplication`, `Member`, `Guardian`, `MembershipPlan`, `Document`, `InvoiceSyncEvent` names are consistent across tasks
- Invoice Ninja integration state remains isolated from core membership models
