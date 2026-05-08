# Admin Review and Member Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build staff-only review flow for submitted applications, including fix/reject/approve actions, parent notifications, and one-time creation of member records on approval.

**Architecture:** Keep `RegistrationApplication` as workflow source of truth, add review metadata and member linkage, expose thin staff-only custom review pages, and place workflow rules in service-layer functions. Approval creates new `Guardian` and `Member` records exactly once, while parent portal and edit flow are extended to support `fix_requested` reopen/resubmit.

**Tech Stack:** Django 5.x, pytest + pytest-django, Django templates, Django admin, Django mail outbox, uv

---

## 1. Design decisions

### 1.1 Data flow

```text
Parent submits application
        |
        v
RegistrationApplication(status=submitted)
        |
        v
Staff review queue -> review detail -> service action
        |                               |
        |                               +--> request fix / reject / approve
        |                               +--> send email
        |                               +--> create Guardian + Member on approve
        v
Parent portal reflects latest status/message
```

### 1.2 Component boundaries

- `apps/registrations/models.py`
  - workflow state and latest review metadata
  - one-to-one link to approved member
- `apps/members/models.py`
  - `Guardian`, `TrainingGroup`, `Member`
- `apps/registrations/services.py`
  - draft/submit rules remain here
  - add review transition functions and notification helpers
- `apps/registrations/views.py`
  - parent views stay here
  - add staff review queue/detail/action views
- `apps/registrations/forms.py`
  - add small admin review form for message-based actions
- `apps/registrations/urls.py`
  - parent URLs + staff review URLs in same namespace for now
- `apps/registrations/admin.py`
  - Django admin registration with review links
- `tests/registrations/*.py`
  - review flow, parent reopen/resubmit, portal status visibility
- `tests/members/*.py`
  - model presence/shape if needed

### 1.3 API/contracts

Service contracts to implement:

```python
def request_application_fix(application: RegistrationApplication, reviewer: User, message: str) -> RegistrationApplication: ...
def reject_application(application: RegistrationApplication, reviewer: User, message: str) -> RegistrationApplication: ...
def approve_application(application: RegistrationApplication, reviewer: User) -> RegistrationApplication: ...
def send_review_notification(application: RegistrationApplication, *, subject: str, body: str) -> None: ...
```

Model helper contract updates:

```python
def is_editable_by(self, parent_account): ...  # true for draft and fix_requested
```

Submit contract update:

```python
def submit_application(application: RegistrationApplication, actor_account: ParentAccount | None) -> RegistrationApplication:
    # accepts draft and fix_requested
```

### 1.4 State model

```text
draft -> submitted
fix_requested -> submitted
submitted -> fix_requested
submitted -> rejected
submitted -> approved
```

Rules:
- only staff can trigger review transitions
- only `submitted` can go to `fix_requested`, `rejected`, or `approved`
- `fix_requested` becomes parent-editable
- resubmit clears prior review metadata
- `approved` and `rejected` stay terminal
- approval is idempotent via linked member check

### 1.5 Why these decisions

- **Latest review metadata on application** keeps implementation small and sufficient for MVP; full event history can come later.
- **Custom staff pages** match approved UX and avoid forcing workflow into Django admin actions.
- **One-to-one approved member link** is simplest way to guarantee no duplicate member creation.
- **Minimal `TrainingGroup` model now** satisfies future assignment placeholder without pulling in assignment workflow.
- **Reuse Django mail path** avoids premature email infrastructure changes.

## 2. File-by-file plan

### Files to create

- `apps/members/models.py`
  - add `Guardian`, `TrainingGroup`, `Member`
- `apps/members/admin.py`
  - basic Django admin registration for new member-domain models
- `apps/registrations/admin.py`
  - Django admin registration for `RegistrationApplication` with review link column
- `apps/registrations/templates/registrations/admin_review_queue.html`
  - staff review queue table
- `apps/registrations/templates/registrations/admin_review_detail.html`
  - staff review detail + actions
- `tests/registrations/test_admin_review_flow.py`
  - staff queue/detail/actions and parent visibility tests
- `tests/members/test_member_models.py`
  - initial member model shape tests if needed for red-first coverage

### Files to modify

- `apps/registrations/models.py`
  - add review metadata + `approved_member` link
  - expand editability helper
- `apps/registrations/forms.py`
  - add `ApplicationReviewForm`
- `apps/registrations/services.py`
  - add review workflow and email helpers
  - allow resubmission from `fix_requested`
  - clear review metadata on resubmit
- `apps/registrations/views.py`
  - add staff review queue/detail/action views
  - parent views expose status/review message/editability
- `apps/registrations/urls.py`
  - add staff review endpoints
- `tests/registrations/test_parent_edit_permissions.py`
  - update/editability expectations for `fix_requested`
- `tests/registrations/test_application_workflow.py`
  - extend submit service coverage for `fix_requested`
- `docs/milestones.md`
  - update M3 status after implementation accepted
- `AGENTS.md`
  - update current status after implementation accepted if architecture/workflow materially changes

### Likely migration files

- `apps/members/migrations/0001_initial.py`
- `apps/registrations/migrations/000X_admin_review_fields.py`

## 3. Test strategy

### Framework

- `pytest`
- `pytest-django`
- Django test client
- `django.core.mail.outbox`

### What to test

- staff-only access to queue/detail/action views
- queue lists only submitted applications
- request-fix requires message and stores metadata
- fix-request email sent and message shown in portal/detail
- parent can edit `fix_requested` application and resubmit same record
- resubmit clears review metadata and re-queues application
- reject requires message and sends email
- approve creates guardian/member exactly once and sends email
- approve does not duplicate on repeated action
- review links appear in Django admin changelist/detail rendering if practical to assert lightly

### What not to test

- exact HTML/CSS styling details
- full email prose beyond subject/body key text
- billing or downstream integrations
- training-group assignment workflow beyond `None`
- full document binary streaming behavior (already covered elsewhere)

### Test file structure

- `tests/members/test_member_models.py`
  - model field presence / relationships
- `tests/registrations/test_admin_review_flow.py`
  - queue/detail/actions + portal visibility
- `tests/registrations/test_parent_edit_permissions.py`
  - reopen editability rules
- `tests/registrations/test_application_workflow.py`
  - resubmit from fix_requested, service transitions if cleaner here

## 4. Acceptance criteria per unit

### Registration workflow unit

- `RegistrationApplication` stores latest review metadata and optional approved member link
- parent can edit when status is `draft` or `fix_requested`
- parent cannot edit `submitted`, `rejected`, or `approved`
- resubmit from `fix_requested` sets status back to `submitted` and clears review metadata

### Member domain unit

- `Guardian`, `TrainingGroup`, `Member` models exist with planned fields
- `Member.training_group` nullable
- application approval links exactly one member back to source application

### Staff review UI unit

- staff can access `/admin/review/applications/`
- staff can access `/admin/review/applications/<id>/`
- anonymous redirects to admin login
- authenticated non-staff gets `404`

### Review services unit

- request fix and reject require non-empty message
- approve only works from `submitted`
- approve creates records exactly once
- all review actions send email

### Parent visibility unit

- portal/detail shows `fix_requested` or `rejected` reason
- approved application shows approved status
- edit CTA visible only when app editable

## 5. Documentation scope

After implementation acceptance:
- update `docs/milestones.md` to reflect M3 now in progress/partially implemented
- update `AGENTS.md` current-status section with admin review/member creation baseline
- optionally add short README note only if setup/run workflow changes materially

## 6. Task plan

### Task 1: Add failing model tests for member domain and review metadata

**Files:**
- Create: `tests/members/test_member_models.py`
- Modify: `tests/registrations/test_application_workflow.py`
- Modify: `tests/registrations/test_parent_edit_permissions.py`
- Future implementation target: `apps/members/models.py`, `apps/registrations/models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/members/test_member_models.py
import pytest

pytestmark = pytest.mark.django_db


def test_guardian_model_has_expected_fields():
    from apps.members.models import Guardian

    field_names = {f.name for f in Guardian._meta.get_fields()}
    assert {"full_name", "personal_id", "email", "phone", "address"}.issubset(field_names)


def test_training_group_model_has_expected_fields():
    from apps.members.models import TrainingGroup

    field_names = {f.name for f in TrainingGroup._meta.get_fields()}
    assert {"name", "is_active"}.issubset(field_names)


def test_member_model_has_expected_fields_and_relationships():
    from apps.members.models import Member

    field_names = {f.name for f in Member._meta.get_fields()}
    assert {"full_name", "personal_id", "birth_date", "guardian", "training_group"}.issubset(field_names)
    assert Member._meta.get_field("training_group").null is True
```

```python
# tests/registrations/test_application_workflow.py

def test_registration_application_has_review_fields():
    from apps.registrations.models import RegistrationApplication

    field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
    assert {"review_message", "reviewed_by", "reviewed_at", "approved_member"}.issubset(field_names)
```

```python
# tests/registrations/test_parent_edit_permissions.py

def test_fix_requested_application_editable_by_owner(self):
    acct, app = self._create_draft_with_owner("fixedit@example.com")
    app.status = "fix_requested"
    app.review_message = "Please fix personal ID"
    app.save(update_fields=["status", "review_message", "updated_at"])

    resp = self.client.get(f"/applications/{app.pk}/edit/")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/members/test_member_models.py tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py -q`
Expected: FAIL with import/field assertion errors for missing models and review fields.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/members/models.py
from django.db import models

from apps.core.models import TimeStampedModel


class Guardian(TimeStampedModel):
    full_name = models.CharField(max_length=255)
    personal_id = models.CharField(max_length=32)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)


class TrainingGroup(TimeStampedModel):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)


class Member(TimeStampedModel):
    full_name = models.CharField(max_length=255)
    personal_id = models.CharField(max_length=32)
    birth_date = models.DateField(null=True, blank=True)
    guardian = models.ForeignKey("members.Guardian", on_delete=models.PROTECT, related_name="members")
    training_group = models.ForeignKey(
        "members.TrainingGroup",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )
```

```python
# apps/registrations/models.py (new fields + helper)
review_message = models.TextField(blank=True, default="")
reviewed_by = models.ForeignKey(
    "auth.User",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="reviewed_registration_applications",
)
reviewed_at = models.DateTimeField(null=True, blank=True)
approved_member = models.OneToOneField(
    "members.Member",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="source_application",
)


def is_editable_by(self, parent_account):
    editable_statuses = {self.Status.DRAFT, self.Status.FIX_REQUESTED}
    return bool(parent_account and self.parent_account_id == parent_account.id and self.status in editable_statuses)
```

- [ ] **Step 4: Create and run migrations**

Run: `uv run python manage.py makemigrations members registrations && uv run python manage.py migrate`
Expected: migration files created and applied successfully.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/members/test_member_models.py tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py -q`
Expected: PASS.

### Task 2: Add failing service tests for review transitions and resubmission

**Files:**
- Create: `tests/registrations/test_admin_review_flow.py`
- Modify: `tests/registrations/test_application_workflow.py`
- Modify: `apps/registrations/services.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/registrations/test_admin_review_flow.py
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.registrations.services import create_or_update_draft, submit_application

pytestmark = pytest.mark.django_db


def _make_submitted_application(email="review@example.com"):
    account = ParentAccount.objects.create(email=email, phone="+37120000000")
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Guardian Review",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000000",
            "guardian_address": "Riga 1",
            "child_full_name": "Child Review",
            "child_personal_id": "010125-67890",
            "child_birth_date": "2025-01-01",
        },
        files={
            "child_identity_document": SimpleUploadedFile("id.png", b"png", content_type="image/png"),
        },
        verified_account=account,
    )
    submit_application(app, account)
    return account, app


def test_request_fix_changes_status_and_sends_email():
    from apps.registrations.services import request_application_fix

    staff = get_user_model().objects.create_user("staff", password="x", is_staff=True)
    account, app = _make_submitted_application()

    request_application_fix(app, staff, "Please correct child personal ID")

    app.refresh_from_db()
    assert app.status == "fix_requested"
    assert app.review_message == "Please correct child personal ID"
    assert app.reviewed_by_id == staff.id
    assert app.reviewed_at is not None
    assert len(mail.outbox) == 1
    assert account.email in mail.outbox[0].to


def test_reject_requires_message():
    from apps.registrations.services import reject_application

    staff = get_user_model().objects.create_user("staff2", password="x", is_staff=True)
    _, app = _make_submitted_application("reject@example.com")

    with pytest.raises(ValueError, match="message is required"):
        reject_application(app, staff, "")


def test_approve_creates_member_records_exactly_once():
    from apps.members.models import Guardian, Member
    from apps.registrations.services import approve_application

    staff = get_user_model().objects.create_user("staff3", password="x", is_staff=True)
    _, app = _make_submitted_application("approve@example.com")

    approve_application(app, staff)
    approve_application(app, staff)

    app.refresh_from_db()
    assert app.status == "approved"
    assert Guardian.objects.count() == 1
    assert Member.objects.count() == 1
    assert app.approved_member is not None
    assert app.approved_member.training_group is None
    assert len(mail.outbox) == 1
```

```python
# tests/registrations/test_application_workflow.py

def test_submit_application_allows_fix_requested_resubmission():
    from apps.registrations.services import create_or_update_draft, submit_application

    account = ParentAccount.objects.create(email="resubmit@example.com", phone="+37110000000")
    app = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Guardian",
            "guardian_personal_id": "010101-00001",
            "guardian_phone": "+37110000000",
            "guardian_address": "Riga 1",
            "child_full_name": "Child",
            "child_personal_id": "010125-00001",
            "child_birth_date": "2025-01-01",
        },
        files={"child_identity_document": _make_child_identity_file()},
        verified_account=account,
    )
    submit_application(app, account)
    app.status = "fix_requested"
    app.review_message = "Fix data"
    app.save(update_fields=["status", "review_message", "updated_at"])

    submit_application(app, account)

    app.refresh_from_db()
    assert app.status == "submitted"
    assert app.review_message == ""
    assert app.reviewed_by is None
    assert app.reviewed_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py tests/registrations/test_application_workflow.py -q`
Expected: FAIL because review service functions do not exist and `submit_application` rejects `fix_requested`.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/registrations/services.py
from django.conf import settings
from django.core.mail import send_mail

from apps.members.models import Guardian, Member


def _require_submitted(application: RegistrationApplication) -> None:
    if application.status != RegistrationApplication.Status.SUBMITTED:
        raise ValueError("only submitted applications can be reviewed")


def _require_message(message: str) -> str:
    cleaned = message.strip()
    if not cleaned:
        raise ValueError("message is required")
    return cleaned


def send_review_notification(application: RegistrationApplication, *, subject: str, body: str) -> None:
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        recipient_list=[application.guardian_email],
        fail_silently=False,
    )


def request_application_fix(application: RegistrationApplication, reviewer, message: str) -> RegistrationApplication:
    _require_submitted(application)
    cleaned = _require_message(message)
    application.status = RegistrationApplication.Status.FIX_REQUESTED
    application.review_message = cleaned
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "review_message", "reviewed_by", "reviewed_at", "updated_at"])
    send_review_notification(application, subject="Application updates needed", body=cleaned)
    return application


def reject_application(application: RegistrationApplication, reviewer, message: str) -> RegistrationApplication:
    _require_submitted(application)
    cleaned = _require_message(message)
    application.status = RegistrationApplication.Status.REJECTED
    application.review_message = cleaned
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "review_message", "reviewed_by", "reviewed_at", "updated_at"])
    send_review_notification(application, subject="Application rejected", body=cleaned)
    return application


def _create_member_from_application(application: RegistrationApplication) -> Member:
    guardian = Guardian.objects.create(
        full_name=application.guardian_full_name,
        personal_id=application.guardian_personal_id,
        email=application.guardian_email,
        phone=application.guardian_phone,
        address=application.guardian_address,
    )
    return Member.objects.create(
        full_name=application.child_full_name,
        personal_id=application.child_personal_id,
        birth_date=application.child_birth_date,
        guardian=guardian,
        training_group=None,
    )


def approve_application(application: RegistrationApplication, reviewer) -> RegistrationApplication:
    if application.status == RegistrationApplication.Status.APPROVED and application.approved_member_id is not None:
        return application
    _require_submitted(application)
    member = _create_member_from_application(application)
    application.status = RegistrationApplication.Status.APPROVED
    application.review_message = ""
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.approved_member = member
    application.save(update_fields=["status", "review_message", "reviewed_by", "reviewed_at", "approved_member", "updated_at"])
    send_review_notification(application, subject="Application approved", body="Your application has been approved.")
    return application
```

```python
# apps/registrations/services.py submit update
if application.status not in {RegistrationApplication.Status.DRAFT, RegistrationApplication.Status.FIX_REQUESTED}:
    raise ValueError("only draft or fix_requested applications can be submitted")

application.status = RegistrationApplication.Status.SUBMITTED
application.submitted_at = timezone.now()
application.review_message = ""
application.reviewed_by = None
application.reviewed_at = None
application.save(update_fields=["status", "submitted_at", "review_message", "reviewed_by", "reviewed_at", "updated_at"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py tests/registrations/test_application_workflow.py -q`
Expected: PASS.

### Task 3: Add failing staff-view tests for queue, detail, and actions

**Files:**
- Modify/Create: `tests/registrations/test_admin_review_flow.py`
- Modify: `apps/registrations/views.py`
- Modify: `apps/registrations/urls.py`
- Modify: `apps/registrations/forms.py`

- [ ] **Step 1: Extend failing tests for review pages**

```python
# tests/registrations/test_admin_review_flow.py
from django.test import Client


def _login_staff(client, username="staffview"):
    user = get_user_model().objects.create_user(username, password="pw", is_staff=True, is_superuser=True)
    client.force_login(user)
    return user


def test_admin_review_queue_requires_staff():
    client = Client()
    response = client.get("/admin/review/applications/")
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_authenticated_non_staff_gets_404_on_review_queue():
    client = Client()
    user = get_user_model().objects.create_user("plain", password="pw")
    client.force_login(user)
    response = client.get("/admin/review/applications/")
    assert response.status_code == 404


def test_review_queue_lists_only_submitted_applications():
    client = Client()
    _login_staff(client)
    _, submitted = _make_submitted_application("queue1@example.com")
    _, other = _make_submitted_application("queue2@example.com")
    other.status = "fix_requested"
    other.save(update_fields=["status", "updated_at"])

    response = client.get("/admin/review/applications/")
    assert response.status_code == 200
    content = response.content.decode()
    assert submitted.child_full_name in content
    assert other.child_full_name not in content


def test_staff_can_request_fix_from_detail_page():
    client = Client()
    _login_staff(client)
    _, app = _make_submitted_application("fixview@example.com")

    response = client.post(
        f"/admin/review/applications/{app.pk}/",
        data={"action": "request_fix", "message": "Please upload correct data"},
    )

    assert response.status_code == 302
    app.refresh_from_db()
    assert app.status == "fix_requested"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: FAIL because routes, form, and views do not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/registrations/forms.py
class ApplicationReviewForm(forms.Form):
    action = forms.ChoiceField(choices=[("request_fix", "Request fix"), ("reject", "Reject")])
    message = forms.CharField(widget=forms.Textarea, required=True)
```

```python
# apps/registrations/views.py
from django.contrib.admin.views.decorators import staff_member_required


def _staff_or_404(request):
    if not request.user.is_authenticated:
        return redirect(f"/admin/login/?next={request.path}")
    if not request.user.is_staff:
        raise Http404
    return None


def admin_review_queue(request: HttpRequest) -> HttpResponse:
    denied = _staff_or_404(request)
    if denied is not None:
        return denied
    applications = RegistrationApplication.objects.filter(status=RegistrationApplication.Status.SUBMITTED).order_by("-submitted_at")
    return render(request, "registrations/admin_review_queue.html", {"applications": applications})


def admin_review_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    denied = _staff_or_404(request)
    if denied is not None:
        return denied
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            approve_application(application, request.user)
        else:
            form = ApplicationReviewForm(request.POST)
            if form.is_valid():
                if form.cleaned_data["action"] == "request_fix":
                    request_application_fix(application, request.user, form.cleaned_data["message"])
                else:
                    reject_application(application, request.user, form.cleaned_data["message"])
                return redirect("registrations:admin-review-detail", application_id=application.id)
        return redirect("registrations:admin-review-detail", application_id=application.id)
    form = ApplicationReviewForm()
    active_document = application.documents.filter(kind=Document.Kind.CHILD_IDENTITY, deleted_at__isnull=True).first()
    return render(
        request,
        "registrations/admin_review_detail.html",
        {"application": application, "review_form": form, "active_document": active_document},
    )
```

```python
# apps/registrations/urls.py
path("admin/review/applications/", views.admin_review_queue, name="admin-review-queue"),
path("admin/review/applications/<int:application_id>/", views.admin_review_detail, name="admin-review-detail"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: PASS for queue access and basic action flow.

### Task 4: Add failing template/admin-link tests and implement staff UI

**Files:**
- Create: `apps/registrations/templates/registrations/admin_review_queue.html`
- Create: `apps/registrations/templates/registrations/admin_review_detail.html`
- Create: `apps/registrations/admin.py`
- Create: `apps/members/admin.py`
- Modify: `tests/registrations/test_admin_review_flow.py`

- [ ] **Step 1: Extend failing tests for review page content and admin link rendering**

```python
# tests/registrations/test_admin_review_flow.py
from django.urls import reverse


def test_review_detail_page_shows_review_controls_and_document_links():
    client = Client()
    _login_staff(client, "detailstaff")
    _, app = _make_submitted_application("detail@example.com")

    response = client.get(f"/admin/review/applications/{app.pk}/")
    content = response.content.decode()

    assert response.status_code == 200
    assert app.child_full_name in content
    assert "request_fix" in content
    assert "approve" in content
    assert reverse("documents:admin-document-preview", args=[app.documents.first().pk]) in content


def test_registration_admin_review_link_present(admin_client):
    _, app = _make_submitted_application("adminlink@example.com")
    response = admin_client.get("/admin/registrations/registrationapplication/")
    assert response.status_code == 200
    assert reverse("registrations:admin-review-detail", args=[app.pk]) in response.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: FAIL because templates/admin registration do not expose expected content.

- [ ] **Step 3: Write minimal implementation**

```html
<!-- apps/registrations/templates/registrations/admin_review_queue.html -->
<h1>Submitted applications</h1>
<table>
  <thead>
    <tr>
      <th>Child</th>
      <th>Guardian</th>
      <th>Email</th>
      <th>Submitted</th>
      <th>Status</th>
      <th>Review</th>
    </tr>
  </thead>
  <tbody>
    {% for application in applications %}
      <tr>
        <td>{{ application.child_full_name }}</td>
        <td>{{ application.guardian_full_name }}</td>
        <td>{{ application.guardian_email }}</td>
        <td>{{ application.submitted_at }}</td>
        <td>{{ application.get_status_display }}</td>
        <td><a href="{% url 'registrations:admin-review-detail' application.id %}">Open</a></td>
      </tr>
    {% empty %}
      <tr><td colspan="6">No submitted applications.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

```html
<!-- apps/registrations/templates/registrations/admin_review_detail.html -->
<h1>{{ application.child_full_name }}</h1>
<p>{{ application.guardian_full_name }}</p>
<p>{{ application.guardian_email }}</p>
{% if active_document %}
  <a href="{% url 'documents:admin-document-preview' active_document.id %}">Preview document</a>
  <a href="{% url 'documents:admin-document-download' active_document.id %}">Download document</a>
{% endif %}
<form method="post">
  {% csrf_token %}
  <input type="hidden" name="action" value="approve">
  <button type="submit">approve</button>
</form>
<form method="post">
  {% csrf_token %}
  <input type="hidden" name="action" value="request_fix">
  {{ review_form.message }}
  <button type="submit">request_fix</button>
</form>
<form method="post">
  {% csrf_token %}
  <input type="hidden" name="action" value="reject">
  {{ review_form.message }}
  <button type="submit">reject</button>
</form>
```

```python
# apps/registrations/admin.py
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.registrations.models import RegistrationApplication


@admin.register(RegistrationApplication)
class RegistrationApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "guardian_email", "child_full_name", "status", "review_link")

    def review_link(self, obj: RegistrationApplication):
        url = reverse("registrations:admin-review-detail", args=[obj.pk])
        return format_html('<a href="{}">Review</a>', url)
```

```python
# apps/members/admin.py
from django.contrib import admin

from apps.members.models import Guardian, Member, TrainingGroup

admin.site.register(Guardian)
admin.site.register(Member)
admin.site.register(TrainingGroup)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: PASS.

### Task 5: Add failing parent-portal tests and implement parent visibility updates

**Files:**
- Modify: `tests/registrations/test_admin_review_flow.py`
- Modify: `tests/registrations/test_parent_edit_permissions.py`
- Modify: `apps/registrations/views.py`
- Modify or create if missing: parent portal/detail templates under `templates/registrations/`

- [ ] **Step 1: Extend failing tests for parent visibility**

```python
# tests/registrations/test_admin_review_flow.py
from apps.accounts.services import issue_magic_link


def _login_parent(client, account):
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def test_parent_portal_shows_fix_message_and_edit_link():
    client = Client()
    account, app = _make_submitted_application("portalfix@example.com")
    staff = get_user_model().objects.create_user("portalstaff", password="pw", is_staff=True)
    from apps.registrations.services import request_application_fix

    request_application_fix(app, staff, "Please correct address")
    _login_parent(client, account)

    response = client.get("/portal/")
    content = response.content.decode()
    assert "Please correct address" in content
    assert f"/applications/{app.pk}/edit/" in content


def test_parent_portal_shows_reject_message_without_edit_link():
    client = Client()
    account, app = _make_submitted_application("portalreject@example.com")
    staff = get_user_model().objects.create_user("portalstaff2", password="pw", is_staff=True)
    from apps.registrations.services import reject_application

    reject_application(app, staff, "Application not accepted")
    _login_parent(client, account)

    response = client.get("/portal/")
    content = response.content.decode()
    assert "Application not accepted" in content
    assert f"/applications/{app.pk}/edit/" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py tests/registrations/test_parent_edit_permissions.py -q`
Expected: FAIL because parent pages do not render review message/edit CTA correctly.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/registrations/views.py parent portal
for app in applications:
    app.can_edit = app.is_editable_by(account)
    app.review_message_for_parent = app.review_message if app.status in {app.Status.FIX_REQUESTED, app.Status.REJECTED} else ""
```

```html
<!-- parent portal template snippet -->
{% for application in applications %}
  <h2>{{ application.child_full_name }}</h2>
  <p>Status: {{ application.get_status_display }}</p>
  {% if application.review_message_for_parent %}
    <p>{{ application.review_message_for_parent }}</p>
  {% endif %}
  {% if application.can_edit %}
    <a href="{% url 'registrations:edit-registration' application.id %}">Edit application</a>
  {% endif %}
{% endfor %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py tests/registrations/test_parent_edit_permissions.py -q`
Expected: PASS.

### Task 6: Harden approval idempotency and review-action edge cases

**Files:**
- Modify: `tests/registrations/test_admin_review_flow.py`
- Modify: `apps/registrations/services.py`

- [ ] **Step 1: Add failing edge-case tests**

```python
# tests/registrations/test_admin_review_flow.py

def test_request_fix_only_allowed_from_submitted():
    from apps.registrations.services import request_application_fix

    staff = get_user_model().objects.create_user("staffedge", password="pw", is_staff=True)
    account, app = _make_submitted_application("edge1@example.com")
    request_application_fix(app, staff, "Need fix")

    with pytest.raises(ValueError, match="only submitted applications can be reviewed"):
        request_application_fix(app, staff, "Need another fix")


def test_approve_second_post_from_view_does_not_duplicate_records():
    client = Client()
    _login_staff(client, "dupstaff")
    _, app = _make_submitted_application("dup@example.com")

    client.post(f"/admin/review/applications/{app.pk}/", data={"action": "approve"})
    client.post(f"/admin/review/applications/{app.pk}/", data={"action": "approve"})

    from apps.members.models import Guardian, Member
    assert Guardian.objects.count() == 1
    assert Member.objects.count() == 1
```

- [ ] **Step 2: Run tests to verify they fail if safeguards missing**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: FAIL if second view post or non-submitted transitions are not properly guarded.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/registrations/services.py
from django.db import transaction


@transaction.atomic
def approve_application(application: RegistrationApplication, reviewer) -> RegistrationApplication:
    application = RegistrationApplication.objects.select_for_update().get(pk=application.pk)
    if application.status == RegistrationApplication.Status.APPROVED and application.approved_member_id is not None:
        return application
    _require_submitted(application)
    member = _create_member_from_application(application)
    application.status = RegistrationApplication.Status.APPROVED
    application.review_message = ""
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.approved_member = member
    application.save(update_fields=["status", "review_message", "reviewed_by", "reviewed_at", "approved_member", "updated_at"])
    send_review_notification(application, subject="Application approved", body="Your application has been approved.")
    return application
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py -q`
Expected: PASS.

### Task 7: Register admin pages, run full verification, then update project docs

**Files:**
- Modify: `docs/milestones.md`
- Modify: `AGENTS.md`
- All changed code/test files from Tasks 1-6

- [ ] **Step 1: Ensure app/admin wiring is complete**

```python
# apps/members/apps.py and apps/registrations/apps.py
# confirm default app config paths remain valid and Django discovers admin modules automatically.
```

- [ ] **Step 2: Run focused registration/member test suites**

Run: `uv run pytest tests/registrations/test_admin_review_flow.py tests/registrations/test_application_workflow.py tests/registrations/test_parent_edit_permissions.py tests/members/test_member_models.py -q`
Expected: PASS.

- [ ] **Step 3: Run full project verification**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all commands PASS.

- [ ] **Step 4: Update docs after code is accepted**

```markdown
<!-- docs/milestones.md -->
- M3 now has initial admin review workflow implemented: queue, request-fix/reject/approve, and member creation baseline.
```

```markdown
<!-- AGENTS.md -->
- apps/members/models.py now implements Guardian, Member, and TrainingGroup.
- apps/registrations includes custom admin review queue/detail and approval workflow.
```

- [ ] **Step 5: Re-run targeted sanity checks after doc edits**

Run: `uv run pytest tests/test_project_smoke.py -q`
Expected: PASS.

## 7. Plan self-review

### Spec coverage check

- queue/detail pages: covered by Tasks 3-4
- fix/reject/approve actions: covered by Tasks 2-3
- parent reopen/resubmit: covered by Tasks 2 and 5
- approval member creation: covered by Tasks 1-2 and 6
- email notifications: covered by Task 2
- Django admin links: covered by Task 4
- full verification and docs updates: covered by Task 7

### Placeholder scan

- no `TBD` / `TODO`
- explicit file paths included
- explicit commands included
- concrete test snippets included

### Type consistency check

- review service function names consistent across tasks
- `approved_member` naming consistent across model, tests, and services
- staff URLs consistent: `/admin/review/applications/` and `/admin/review/applications/<id>/`
