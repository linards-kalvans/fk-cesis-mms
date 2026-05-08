# Task 5 Registration Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable parent registration slice with draft save, private single-document upload, magic-link resume, submission, and parent portal status view.

**Architecture:** Keep application workflow in `apps/registrations` and uploaded file records in `apps/documents`. Store guardian and child data as an application snapshot, but use `ParentAccount` as the reusable account and prefill source. Enforce workflow and permission rules in service functions so views stay thin and tests can focus on business behavior.

**Tech Stack:** Python 3.12+, Django 5.x, pytest, pytest-django, Django ORM, Django forms, Django templates, Django file uploads.

---

## 0. Execution status

- **Task 5 completed** on 2026-05-05.
- Registration workflow is usable for LAN acceptance testing.
- Delivered scope includes: anonymous draft start, same-browser draft continuation, magic-link resume, single required identity document upload, parent portal, single edit form with save-draft and submit actions, and native browser date picker for child birth date.
- Verified green after final Task 5 polish: `uv run pytest -q && uv run ruff check . && uv run mypy .`.
- **Next active implementation task:** Task 6 — Admin review and member creation.

## 1. Design decisions

### 1.1 Workflow split
- `apps/registrations` owns form handling, state transitions, and parent-facing routes.
- `apps/documents` owns uploaded file persistence and OCR placeholder state.
- Why: this preserves a clean boundary for later secure streaming, OCR orchestration, and delete/audit work.

### 1.2 Snapshot on application, defaults on account
- `RegistrationApplication` stores guardian and child values submitted for that specific application.
- `ParentAccount` remains the login/resume identity and reusable prefill source.
- Why: admin review needs a stable submitted snapshot; later profile changes must not rewrite older applications.

### 1.3 Service-led workflow
- Views call service functions for create/update/submit and permission checks.
- Why: easier TDD, thinner views, and less duplicated rule logic.

### 1.4 Submit-time strictness
- Draft saves allow incomplete business fields.
- Submission requires all required fields and one active `child_identity` document.
- Why: matches requested UX and keeps partial work resumable.

### 1.5 Parent access model
- Anonymous parent may start a draft.
- First save or submit creates or links a `ParentAccount` by email.
- Magic link later establishes session and shows only that parent's applications.
- Why: fast first-run UX without abandoning account-based resume.

## 2. File-by-file plan

### Files to create

- `apps/registrations/models.py`
  - `RegistrationApplication` model
  - `RegistrationApplication.Status` text choices
  - helper methods `is_draft()` and `is_editable_by(parent_account)`

- `apps/registrations/forms.py`
  - `RegistrationApplicationForm`
  - field list for guardian + child + `child_identity_document`
  - custom `is_submit` flag so draft and submit validations differ

- `apps/registrations/services.py`
  - `get_application_prefill(account: ParentAccount | None) -> dict[str, object]`
  - `create_or_update_draft(*, data: dict[str, object], files: dict[str, object], application: RegistrationApplication | None = None) -> RegistrationApplication`
  - `can_edit_application(application: RegistrationApplication, actor_account: ParentAccount | None) -> bool`
  - `submit_application(application: RegistrationApplication, actor_account: ParentAccount) -> RegistrationApplication`

- `apps/registrations/views.py`
  - `start_registration(request)`
  - `edit_registration(request, application_id: int)`
  - `submit_registration(request, application_id: int)`
  - `parent_portal(request)`

- `apps/registrations/urls.py`
  - route names: `start-registration`, `edit-registration`, `submit-registration`, `parent-portal`

- `apps/documents/models.py`
  - `Document` model
  - `Document.Kind` with `CHILD_IDENTITY`
  - `Document.OcrStatus` with `NOT_REQUESTED`, `PENDING`, `COMPLETED`, `FAILED`
  - helper `is_active` property

- `tests/registrations/test_application_workflow.py`
  - service/model integration tests

- `tests/registrations/test_parent_edit_permissions.py`
  - view/session/permission tests

- `templates/registrations/start_registration.html`
  - form for anonymous or resumed parent

- `templates/registrations/edit_registration.html`
  - draft edit form

- `templates/registrations/parent_portal.html`
  - list of current parent's applications and allowed actions

### Files to modify

- `fk_cesis_mms/settings.py`
  - add `MEDIA_ROOT`, `MEDIA_URL`
  - keep local uploaded files private by not exposing any direct file route

- `fk_cesis_mms/urls.py`
  - include `apps.registrations.urls`

- `apps/accounts/views.py`
  - change magic-link success redirect from `/` to `/portal/`

## 3. Test strategy

### Framework
- `pytest` + `pytest-django`
- use `django.test.Client` for view tests
- use `SimpleUploadedFile` for upload tests

### What to test
- account auto-create/link on first draft save
- second application under same parent account
- draft save with incomplete fields
- submit blocked without document
- submit blocked for non-owner or non-draft
- submit sets `submitted_at` and locks editing
- document creation and replacement
- portal filtering to current parent only
- prefill from account and most recent application

### What not to test
- exact HTML markup
- CSS
- real OCR calls
- file streaming/download views
- admin transitions

## 4. Acceptance criteria per unit

### Unit A — Model and document foundations
- migrations create `RegistrationApplication` and `Document`
- application supports all five statuses
- document stores upload metadata and OCR placeholder state

### Unit B — Draft workflow
- anonymous parent can save draft
- first save creates or links `ParentAccount`
- draft saves allow incomplete data
- repeated save updates same application and can replace document

### Unit C — Submit workflow
- submit requires full required fields and one active document
- submit changes `draft` to `submitted`
- submit sets `submitted_at`
- submitted application becomes read-only to parent

### Unit D — Resume and portal flow
- magic-link verify redirects to `/portal/`
- portal shows only current parent's applications
- resumed parent can continue only own drafts

### Unit E — Verification
- targeted registration tests pass
- full `uv run pytest -q && uv run ruff check . && uv run mypy .` passes

## 5. Implementation tasks

### Task 1: Write failing workflow and service tests

**Files:**
- Create: `tests/registrations/test_application_workflow.py`

- [ ] **Step 1: Write the failing draft-save and account-linking tests**

```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import create_or_update_draft


pytestmark = pytest.mark.django_db


def make_upload(name: str = "child-id.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/jpeg")


def test_create_draft_creates_parent_account_and_application():
    application = create_or_update_draft(
        data={
            "guardian_email": "parent@example.com",
            "guardian_phone": "+37120000000",
            "guardian_full_name": "Anna Ozola",
        },
        files={},
    )

    assert ParentAccount.objects.count() == 1
    account = ParentAccount.objects.get(email="parent@example.com")
    assert application.parent_account == account
    assert application.status == RegistrationApplication.Status.DRAFT
    assert application.guardian_phone == "+37120000000"


def test_second_application_reuses_existing_parent_account():
    first = create_or_update_draft(
        data={"guardian_email": "family@example.com", "guardian_phone": "+37120000001"},
        files={},
    )

    second = create_or_update_draft(
        data={"guardian_email": "family@example.com", "guardian_phone": "+37120000002"},
        files={},
    )

    assert ParentAccount.objects.count() == 1
    assert first.parent_account == second.parent_account
    assert second.parent_account.phone == "+37120000002"


def test_draft_save_allows_incomplete_fields():
    application = create_or_update_draft(
        data={"guardian_email": "draft@example.com"},
        files={},
    )

    assert application.status == RegistrationApplication.Status.DRAFT
    assert application.guardian_email == "draft@example.com"
    assert application.child_full_name == ""


def test_upload_creates_child_identity_document_with_placeholder_ocr_status():
    application = create_or_update_draft(
        data={"guardian_email": "upload@example.com"},
        files={"child_identity_document": make_upload()},
    )

    document = Document.objects.get(application=application, kind=Document.Kind.CHILD_IDENTITY)
    assert document.ocr_status == Document.OcrStatus.NOT_REQUESTED
    assert document.original_filename == "child-id.jpg"
    assert document.deleted_at is None
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `uv run pytest tests/registrations/test_application_workflow.py -v`
Expected: FAIL with `ModuleNotFoundError` or import errors because registration and document models/services do not exist yet.

- [ ] **Step 3: Extend the same test file with failing submit and prefill tests**

```python
from datetime import date

from apps.registrations.services import get_application_prefill, submit_application


def build_complete_data(email: str = "complete@example.com") -> dict[str, object]:
    return {
        "guardian_full_name": "Anna Ozola",
        "guardian_personal_id": "120990-12345",
        "guardian_email": email,
        "guardian_phone": "+37125555555",
        "guardian_address": "Cesis iela 1, Cesis",
        "child_full_name": "Janis Ozols",
        "child_personal_id": "010515-54321",
        "child_birth_date": date(2015, 5, 1),
    }


def test_submit_requires_active_child_identity_document():
    application = create_or_update_draft(data=build_complete_data(), files={})

    with pytest.raises(ValueError, match="child identity document"):
        submit_application(application, application.parent_account)


def test_submit_marks_application_submitted_and_sets_timestamp():
    application = create_or_update_draft(
        data=build_complete_data(),
        files={"child_identity_document": make_upload()},
    )

    submitted = submit_application(application, application.parent_account)
    submitted.refresh_from_db()

    assert submitted.status == RegistrationApplication.Status.SUBMITTED
    assert submitted.submitted_at is not None


def test_submit_rejects_non_owner():
    application = create_or_update_draft(
        data=build_complete_data(email="owner@example.com"),
        files={"child_identity_document": make_upload()},
    )
    stranger = ParentAccount.objects.create(email="stranger@example.com", phone="+37129999999")

    with pytest.raises(ValueError, match="not allowed"):
        submit_application(application, stranger)


def test_prefill_uses_account_and_latest_application_values():
    application = create_or_update_draft(
        data={
            **build_complete_data(email="prefill@example.com"),
            "guardian_phone": "+37127777777",
            "guardian_address": "Parka iela 5, Cesis",
        },
        files={},
    )

    prefill = get_application_prefill(application.parent_account)

    assert prefill["guardian_email"] == "prefill@example.com"
    assert prefill["guardian_phone"] == "+37127777777"
    assert prefill["guardian_address"] == "Parka iela 5, Cesis"
```

- [ ] **Step 4: Run targeted tests again to verify continued failure**

Run: `uv run pytest tests/registrations/test_application_workflow.py -v`
Expected: FAIL because `submit_application` and `get_application_prefill` are still missing.

### Task 2: Implement registration and document models with migrations

**Files:**
- Create: `apps/registrations/models.py`
- Create: `apps/documents/models.py`
- Modify: `fk_cesis_mms/settings.py`

- [ ] **Step 1: Write the minimal registration model implementation**

```python
from django.db import models

from apps.core.models import TimeStampedModel


class RegistrationApplication(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        FIX_REQUESTED = "fix_requested", "Fix requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    parent_account = models.ForeignKey(
        "accounts.ParentAccount",
        on_delete=models.CASCADE,
        related_name="applications",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    guardian_full_name = models.CharField(max_length=255, blank=True)
    guardian_personal_id = models.CharField(max_length=32, blank=True)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=32, blank=True)
    guardian_address = models.CharField(max_length=255, blank=True)
    child_full_name = models.CharField(max_length=255, blank=True)
    child_personal_id = models.CharField(max_length=32, blank=True)
    child_birth_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

    def is_editable_by(self, parent_account):
        return bool(parent_account and self.parent_account_id == parent_account.id and self.is_draft())
```

- [ ] **Step 2: Write the minimal document model implementation**

```python
from django.db import models

from apps.core.models import TimeStampedModel


class Document(TimeStampedModel):
    class Kind(models.TextChoices):
        CHILD_IDENTITY = "child_identity", "Child identity"

    class OcrStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    application = models.ForeignKey(
        "registrations.RegistrationApplication",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    file = models.FileField(upload_to="private/child-identity/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    ocr_status = models.CharField(
        max_length=32,
        choices=OcrStatus.choices,
        default=OcrStatus.NOT_REQUESTED,
    )
    uploaded_by_parent_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None
```

- [ ] **Step 3: Add local media settings for uploads**

```python
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "uploads"
```

Place them below `STATIC_URL = "static/"` in `fk_cesis_mms/settings.py`.

- [ ] **Step 4: Run makemigrations and inspect output**

Run: `uv run python manage.py makemigrations registrations documents`
Expected: creates `apps/registrations/migrations/0001_initial.py` and `apps/documents/migrations/0001_initial.py`.

- [ ] **Step 5: Run targeted tests to verify model-backed tests now reach service failures**

Run: `uv run pytest tests/registrations/test_application_workflow.py -v`
Expected: FAIL because service functions are still missing, but model imports and tables are now valid.

### Task 3: Implement registration services and make workflow tests pass

**Files:**
- Create: `apps/registrations/services.py`
- Modify: `tests/registrations/test_application_workflow.py`

- [ ] **Step 1: Implement account-prefill and ownership helpers**

```python
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.accounts.models import ParentAccount
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication


def _latest_application(account: ParentAccount) -> RegistrationApplication | None:
    return account.applications.order_by("-created_at").first()


def get_application_prefill(account: ParentAccount | None) -> dict[str, object]:
    if account is None:
        return {}

    latest = _latest_application(account)
    prefill: dict[str, object] = {
        "guardian_email": account.email,
        "guardian_phone": account.phone,
    }
    if latest is not None:
        prefill.update(
            {
                "guardian_full_name": latest.guardian_full_name,
                "guardian_personal_id": latest.guardian_personal_id,
                "guardian_address": latest.guardian_address,
                "child_full_name": latest.child_full_name,
                "child_personal_id": latest.child_personal_id,
                "child_birth_date": latest.child_birth_date,
            }
        )
    return prefill


def can_edit_application(application: RegistrationApplication, actor_account: ParentAccount | None) -> bool:
    return application.is_editable_by(actor_account)
```

- [ ] **Step 2: Implement draft creation, linking, and document replacement**

```python
def _get_or_create_parent_account(email: str, phone: str) -> ParentAccount:
    account, created = ParentAccount.objects.get_or_create(
        email=email,
        defaults={"phone": phone or ""},
    )
    if not created and phone and account.phone != phone:
        account.phone = phone
        account.save(update_fields=["phone", "updated_at"])
    return account


def _replace_child_identity_document(application: RegistrationApplication, upload) -> None:
    existing = application.documents.filter(
        kind=Document.Kind.CHILD_IDENTITY,
        deleted_at__isnull=True,
    ).first()
    if existing is not None:
        existing.deleted_at = timezone.now()
        existing.save(update_fields=["deleted_at", "updated_at"])

    Document.objects.create(
        application=application,
        kind=Document.Kind.CHILD_IDENTITY,
        file=upload,
        original_filename=upload.name,
        content_type=getattr(upload, "content_type", "application/octet-stream"),
        file_size=upload.size,
        ocr_status=Document.OcrStatus.NOT_REQUESTED,
    )


def create_or_update_draft(
    *,
    data: Mapping[str, Any],
    files: Mapping[str, Any],
    application: RegistrationApplication | None = None,
) -> RegistrationApplication:
    email = str(data.get("guardian_email", "")).strip().lower()
    if not email:
        raise ValueError("guardian_email is required to save draft")

    phone = str(data.get("guardian_phone", "")).strip()
    account = _get_or_create_parent_account(email, phone)

    if application is None:
        application = RegistrationApplication(parent_account=account)
    elif application.parent_account_id != account.id:
        raise ValueError("application email cannot change owner")

    application.parent_account = account
    application.guardian_full_name = str(data.get("guardian_full_name", "")).strip()
    application.guardian_personal_id = str(data.get("guardian_personal_id", "")).strip()
    application.guardian_email = email
    application.guardian_phone = phone
    application.guardian_address = str(data.get("guardian_address", "")).strip()
    application.child_full_name = str(data.get("child_full_name", "")).strip()
    application.child_personal_id = str(data.get("child_personal_id", "")).strip()
    application.child_birth_date = data.get("child_birth_date") or None
    application.status = RegistrationApplication.Status.DRAFT
    application.save()

    upload = files.get("child_identity_document")
    if upload is not None:
        _replace_child_identity_document(application, upload)

    return application
```

- [ ] **Step 3: Implement submit validation and transition**

```python
REQUIRED_SUBMIT_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_email",
    "guardian_phone",
    "guardian_address",
    "child_full_name",
    "child_personal_id",
    "child_birth_date",
)


def _require_complete_application(application: RegistrationApplication) -> None:
    missing = [field for field in REQUIRED_SUBMIT_FIELDS if not getattr(application, field)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def _require_active_child_identity_document(application: RegistrationApplication) -> None:
    exists = application.documents.filter(
        kind=Document.Kind.CHILD_IDENTITY,
        deleted_at__isnull=True,
    ).exists()
    if not exists:
        raise ValueError("child identity document is required before submit")


def submit_application(
    application: RegistrationApplication,
    actor_account: ParentAccount,
) -> RegistrationApplication:
    if application.parent_account_id != actor_account.id:
        raise ValueError("not allowed to submit this application")
    if application.status != RegistrationApplication.Status.DRAFT:
        raise ValueError("only draft applications can be submitted")

    _require_complete_application(application)
    _require_active_child_identity_document(application)

    application.status = RegistrationApplication.Status.SUBMITTED
    application.submitted_at = timezone.now()
    application.save(update_fields=["status", "submitted_at", "updated_at"])
    return application
```

- [ ] **Step 4: Run targeted workflow tests to verify pass**

Run: `uv run pytest tests/registrations/test_application_workflow.py -v`
Expected: PASS.

### Task 4: Write failing view and permission tests

**Files:**
- Create: `tests/registrations/test_parent_edit_permissions.py`

- [ ] **Step 1: Write draft access, portal filtering, and submit-lock tests**

```python
import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import create_or_update_draft, submit_application

from tests.registrations.test_application_workflow import build_complete_data, make_upload


pytestmark = pytest.mark.django_db


def login_parent(client: Client, account: ParentAccount) -> None:
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
    session.save()


def test_owner_can_open_draft_edit_page():
    application = create_or_update_draft(data={"guardian_email": "owner@example.com"}, files={})
    client = Client()
    login_parent(client, application.parent_account)

    response = client.get(f"/applications/{application.id}/edit/")

    assert response.status_code == 200


def test_other_parent_cannot_open_draft_edit_page():
    application = create_or_update_draft(data={"guardian_email": "owner@example.com"}, files={})
    stranger = ParentAccount.objects.create(email="stranger@example.com", phone="+37128888888")
    client = Client()
    login_parent(client, stranger)

    response = client.get(f"/applications/{application.id}/edit/")

    assert response.status_code == 404


def test_submitted_application_is_not_editable_by_owner():
    application = create_or_update_draft(
        data=build_complete_data(email="locked@example.com"),
        files={"child_identity_document": make_upload()},
    )
    submit_application(application, application.parent_account)
    client = Client()
    login_parent(client, application.parent_account)

    response = client.get(f"/applications/{application.id}/edit/")

    assert response.status_code == 404


def test_portal_lists_only_current_parent_applications():
    own = create_or_update_draft(data={"guardian_email": "me@example.com"}, files={})
    create_or_update_draft(data={"guardian_email": "other@example.com"}, files={})
    client = Client()
    login_parent(client, own.parent_account)

    response = client.get("/portal/")

    page = response.content.decode()
    assert response.status_code == 200
    assert "me@example.com" in page
    assert "other@example.com" not in page
```

- [ ] **Step 2: Run targeted permission tests to verify failure**

Run: `uv run pytest tests/registrations/test_parent_edit_permissions.py -v`
Expected: FAIL because registration views, URLs, and templates do not exist yet.

### Task 5: Implement forms, views, templates, and routing

**Files:**
- Create: `apps/registrations/forms.py`
- Create: `apps/registrations/views.py`
- Create: `apps/registrations/urls.py`
- Create: `templates/registrations/start_registration.html`
- Create: `templates/registrations/edit_registration.html`
- Create: `templates/registrations/parent_portal.html`
- Modify: `fk_cesis_mms/urls.py`
- Modify: `apps/accounts/views.py`

- [ ] **Step 1: Implement the registration form with submit-mode validation**

```python
from django import forms


class RegistrationApplicationForm(forms.Form):
    guardian_full_name = forms.CharField(max_length=255, required=False)
    guardian_personal_id = forms.CharField(max_length=32, required=False)
    guardian_email = forms.EmailField(required=True)
    guardian_phone = forms.CharField(max_length=32, required=False)
    guardian_address = forms.CharField(max_length=255, required=False)
    child_full_name = forms.CharField(max_length=255, required=False)
    child_personal_id = forms.CharField(max_length=32, required=False)
    child_birth_date = forms.DateField(required=False)
    child_identity_document = forms.FileField(required=False)

    submit_required_fields = (
        "guardian_full_name",
        "guardian_personal_id",
        "guardian_email",
        "guardian_phone",
        "guardian_address",
        "child_full_name",
        "child_personal_id",
        "child_birth_date",
    )

    def __init__(self, *args, is_submit: bool = False, has_existing_document: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_submit = is_submit
        self.has_existing_document = has_existing_document

    def clean(self):
        cleaned_data = super().clean()
        if not self.is_submit:
            return cleaned_data

        for field_name in self.submit_required_fields:
            if not cleaned_data.get(field_name):
                self.add_error(field_name, "This field is required for submission.")

        if not self.has_existing_document and not cleaned_data.get("child_identity_document"):
            self.add_error("child_identity_document", "Child identity document is required for submission.")

        return cleaned_data
```

- [ ] **Step 2: Implement parent-session helper, draft views, submit view, and portal view**

```python
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.documents.models import Document
from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    can_edit_application,
    create_or_update_draft,
    get_application_prefill,
    submit_application,
)


def _current_parent_account(request: HttpRequest) -> ParentAccount | None:
    account_id = request.session.get(PARENT_ACCOUNT_SESSION_KEY)
    if not account_id:
        return None
    return ParentAccount.objects.filter(pk=account_id).first()


def _active_document_exists(application: RegistrationApplication) -> bool:
    return application.documents.filter(
        kind=Document.Kind.CHILD_IDENTITY,
        deleted_at__isnull=True,
    ).exists()


def start_registration(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if request.method == "POST":
        form = RegistrationApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = create_or_update_draft(data=form.cleaned_data, files=request.FILES)
            return redirect("registrations:edit-registration", application_id=application.id)
    else:
        form = RegistrationApplicationForm(initial=get_application_prefill(account))
    return render(request, "registrations/start_registration.html", {"form": form})


def edit_registration(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not can_edit_application(application, account):
        raise Http404

    if request.method == "POST":
        form = RegistrationApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            create_or_update_draft(
                data=form.cleaned_data,
                files=request.FILES,
                application=application,
            )
            return redirect("registrations:edit-registration", application_id=application.id)
    else:
        form = RegistrationApplicationForm(
            initial={
                "guardian_full_name": application.guardian_full_name,
                "guardian_personal_id": application.guardian_personal_id,
                "guardian_email": application.guardian_email,
                "guardian_phone": application.guardian_phone,
                "guardian_address": application.guardian_address,
                "child_full_name": application.child_full_name,
                "child_personal_id": application.child_personal_id,
                "child_birth_date": application.child_birth_date,
            }
        )
    return render(
        request,
        "registrations/edit_registration.html",
        {"form": form, "application": application},
    )


def submit_registration(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if request.method != "POST" or account is None or not can_edit_application(application, account):
        raise Http404

    form = RegistrationApplicationForm(
        request.POST,
        request.FILES,
        is_submit=True,
        has_existing_document=_active_document_exists(application),
    )
    if form.is_valid():
        application = create_or_update_draft(
            data=form.cleaned_data,
            files=request.FILES,
            application=application,
        )
        submit_application(application, account)
        return redirect("registrations:parent-portal")

    return render(
        request,
        "registrations/edit_registration.html",
        {"form": form, "application": application},
        status=400,
    )


def parent_portal(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if account is None:
        return redirect("accounts:request-magic-link")
    applications = account.applications.order_by("-created_at")
    return render(
        request,
        "registrations/parent_portal.html",
        {"account": account, "applications": applications},
    )
```

- [ ] **Step 3: Implement URL routing and update project/app redirects**

```python
# apps/registrations/urls.py
from django.urls import path

from apps.registrations import views

app_name = "registrations"

urlpatterns = [
    path("register/", views.start_registration, name="start-registration"),
    path("applications/<int:application_id>/edit/", views.edit_registration, name="edit-registration"),
    path("applications/<int:application_id>/submit/", views.submit_registration, name="submit-registration"),
    path("portal/", views.parent_portal, name="parent-portal"),
]
```

```python
# fk_cesis_mms/urls.py
urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.registrations.urls")),
]
```

```python
# apps/accounts/views.py
def verify_magic_link(request, token):
    ...
    request.session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
    return redirect("registrations:parent-portal")
```

- [ ] **Step 4: Add minimal templates that expose form errors and portal data**

```html
<!-- templates/registrations/start_registration.html -->
<h1>Sākt pieteikumu</h1>
<form method="post" enctype="multipart/form-data">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Saglabāt melnrakstu</button>
</form>
```

```html
<!-- templates/registrations/edit_registration.html -->
<h1>Rediģēt pieteikumu</h1>
<form method="post" enctype="multipart/form-data">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Saglabāt melnrakstu</button>
</form>

<form method="post" action="{% url 'registrations:submit-registration' application.id %}" enctype="multipart/form-data">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Iesniegt pieteikumu</button>
</form>
```

```html
<!-- templates/registrations/parent_portal.html -->
<h1>Mani pieteikumi</h1>

{% for application in applications %}
  <article>
    <h2>{{ application.child_full_name|default:application.guardian_email }}</h2>
    <p>Statuss: {{ application.status }}</p>
    <p>{{ application.guardian_email }}</p>
    {% if application.status == "draft" %}
      <a href="{% url 'registrations:edit-registration' application.id %}">Turpināt</a>
    {% endif %}
  </article>
{% empty %}
  <p>Nav pieteikumu.</p>
{% endfor %}
```

- [ ] **Step 5: Run targeted permission tests to verify pass**

Run: `uv run pytest tests/registrations/test_parent_edit_permissions.py -v`
Expected: PASS.

### Task 6: Run full verification and update docs if implementation differs from current docs

**Files:**
- Modify if needed: `README.md`
- Modify if needed: `AGENTS.md`
- Modify if needed: `docs/milestones.md`

- [ ] **Step 1: Run the registration test files together**

Run: `uv run pytest tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py -v`
Expected: PASS.

- [ ] **Step 2: Run the full verification suite**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: PASS.

- [ ] **Step 3: Update docs only if implementation changed documented behavior**

If the final implementation differs from the spec or current project status, update these lines:

```md
# README.md
- Task 5 registration workflow implemented
- parent can save draft, upload one identity document, resume via magic link, and submit

# docs/milestones.md
- Current execution snapshot: Task 5 completed
- Next active implementation task: Task 6 — Private document storage and OCR status
```

- [ ] **Step 4: Generate critique diff URL for review**

Run: `bunx critique --web "Implement Task 5 registration workflow" --filter "apps/registrations/**" --filter "apps/documents/**" --filter "tests/registrations/**" --filter "templates/registrations/**" --filter "fk_cesis_mms/urls.py" --filter "fk_cesis_mms/settings.py" --filter "apps/accounts/views.py"`
Expected: prints a critique URL for user review.
