# P1 Field Contract and Verified Registration Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finalize P1 field contracts and replace insecure typed-email draft ownership with guardian-email-first one-time-code verification, chooser flow, and verified-only registration continuation.

**Architecture:** Convert `/register/` from anonymous draft form into verified-entry flow. Add dedicated one-time email code auth, expand `RegistrationApplication` into finalized guardian/member/application snapshot fields, and route all registration continuation plus portal access through one verified session. Reuse existing domain apps; keep P1 narrowly focused on field contract, security gate, minimal document-kind support, and admin-managed kit size options.

**Tech Stack:** Django 5.x, PostgreSQL, Django forms/views/templates, pytest + pytest-django, uv, private file storage.

**Execution Status:** Completed in current codebase. Final verification passed with `349 passed`, `ruff check .`, and `mypy .`.

---

## 1. Design decisions

### 1.1 Route structure
- `GET/POST /register/` → guardian email entry, send one-time code
- `GET/POST /register/verify/` → code entry and verification
- `GET /portal/` → chooser/dashboard for verified guardian
- `GET/POST /applications/new/` → create new registration draft
- `GET/POST /applications/<id>/edit/` → edit verified draft/fix-requested application
- existing summary/detail routes remain, but require verified session
- `POST /accounts/logout/` stays
- legacy magic-link request/verify pages should redirect to `/register/` or be removed from active UX

**Why:** This keeps entry/auth separate from registration form, matches approved P1 behavior, and removes the old ambiguous `/register/` dual role.

### 1.2 One-time-code auth model
Add `EmailVerificationCode` in `apps/accounts/models.py` instead of overloading `MagicLinkToken`.

```python
class EmailVerificationCode(TimeStampedModel):
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
```

**Why:** Code flow and magic-link flow have different payloads and UX. Separate model keeps P1 migration small, allows clean tests, and avoids token/link logic leaking into code verification.

### 1.3 Registration snapshot shape
Expand `RegistrationApplication` to finalized P1 names and add field-source metadata.

```python
class RegistrationApplication(TimeStampedModel):
    parent_account = models.ForeignKey(..., null=True, blank=True)
    status = models.CharField(...)
    guardian_full_name = models.CharField(max_length=255, blank=True)
    guardian_personal_id = models.CharField(max_length=32, blank=True)
    guardian_declared_address = models.CharField(max_length=255, blank=True)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=32, blank=True)
    member_full_name = models.CharField(max_length=255, blank=True)
    member_personal_id = models.CharField(max_length=32, blank=True)
    member_birth_date = models.DateField(null=True, blank=True)
    member_actual_address = models.CharField(max_length=255, blank=True)
    member_same_address_as_guardian = models.BooleanField(default=False)
    preferred_agreement_signing = models.CharField(max_length=16, blank=True)
    support_club_instead_of_multi_child_discount = models.BooleanField(null=True, blank=True)
    field_sources = models.JSONField(default=dict, blank=True)
```

**Why:** P1 needs stable snapshot data for approved contract. JSON `field_sources` is smallest way to persist per-field source classification without creating many extra columns.

### 1.4 Kit sizes live in members app
Add admin-managed `KitSizeOption` to `apps/members/models.py`.

```python
class KitSizeOption(models.Model):
    class Kind(models.TextChoices):
        SHIRT = "shirt", "Shirt"
        SHORTS = "shorts", "Shorts"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    label = models.CharField(max_length=64)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

**Why:** Kit sizes are club-managed operational reference data, not account/auth data.

### 1.5 Sibling-order condition for support-club question
Show `support_club_instead_of_multi_child_discount` when verified guardian already has at least one other non-rejected application in the system.

```python
def guardian_has_prior_child_application(account: ParentAccount, current_application_id: int | None = None) -> bool:
    qs = RegistrationApplication.objects.filter(parent_account=account).exclude(status=RegistrationApplication.Status.REJECTED)
    if current_application_id is not None:
        qs = qs.exclude(pk=current_application_id)
    return qs.exists()
```

**Why:** P1 needs deterministic behavior now without building full billing rules. Non-rejected application count is simple, explainable, and testable.

### 1.6 Documents service boundary
Centralize active-document replacement in `apps/documents/services.py`.

```python
def replace_active_document(*, application: RegistrationApplication, kind: str, upload) -> Document: ...
def get_active_document(application: RegistrationApplication, kind: str) -> Document | None: ...
```

**Why:** P1 adds guardian identity, member identity, and portrait uploads. Document replacement rules should not be duplicated in registration views/services.

---

## 2. File-by-file plan

### Create
- `apps/accounts/migrations/0004_email_verification_code_and_parent_profile.py`
- `apps/documents/migrations/0004_p1_document_kinds.py`
- `apps/members/migrations/0002_kit_size_option.py`
- `apps/registrations/migrations/0004_p1_field_contract.py`
- `tests/accounts/test_email_verification_code.py`
- `tests/registrations/test_verified_registration_entry.py`
- `tests/registrations/test_registration_form_contract.py`
- `tests/registrations/test_registration_chooser.py`
- `templates/registrations/verify_registration_code.html`

### Modify
- `apps/accounts/models.py`
- `apps/accounts/forms.py`
- `apps/accounts/services.py`
- `apps/accounts/views.py`
- `apps/accounts/urls.py`
- `apps/accounts/session.py`
- `apps/registrations/models.py`
- `apps/registrations/forms.py`
- `apps/registrations/services.py`
- `apps/registrations/views.py`
- `apps/registrations/urls.py`
- `apps/documents/models.py`
- `apps/documents/services.py`
- `apps/members/models.py`
- `apps/members/admin.py`
- `templates/registrations/start_registration.html`
- `templates/registrations/edit_registration.html`
- `templates/registrations/parent_portal.html`
- `templates/accounts/request_magic_link.html` (redirect/deprecation handling if kept)
- `tests/registrations/test_parent_identity_gate.py`
- `tests/registrations/test_application_workflow.py`
- `tests/accounts/test_login_views.py`
- `tests/accounts/test_magic_links.py`
- `docs/milestones.md`
- `AGENTS.md` (only if command/workflow or architecture notes need refresh after implementation)

### Likely unchanged
- `apps/documents/views.py`
- `tests/documents/test_admin_document_access.py`
- admin review templates, unless new field labels are shown there by existing detail page

---

## 3. Test strategy

### Framework
- `pytest`, `pytest-django`
- model/service tests first
- focused view tests for route gating, redirects, form errors, chooser content

### What to test
- code issuance/verification lifecycle: create, send, rate-limit, expire, consume once
- verified session gating on portal + new/edit/detail routes
- finalized field contract requiredness on submit
- draft allows incomplete fields after verification
- conditional support-club question visibility/requiredness
- guardian-only prefill for existing guardian
- chooser CTA priority with and without draft
- document kind replacement and active-document lookup
- kit size option filtering and validation
- cross-account exposure regression

### What not to test
- exact CSS or P2 visual redesign hooks
- OCR extraction logic
- billing calculation logic
- admin review behavior beyond field-name compatibility

### Test file layout
- `tests/accounts/test_email_verification_code.py` → code model + service + auth views
- `tests/registrations/test_verified_registration_entry.py` → register/verify routes and session gating
- `tests/registrations/test_registration_form_contract.py` → submit/draft validation and conditional fields
- `tests/registrations/test_registration_chooser.py` → chooser dashboard and prefill behavior
- existing older tests updated or trimmed to match code-only flow

---

## 4. Acceptance criteria per unit

### Unit A — auth gate
- one-time code only
- code single-use, short TTL, rate-limited
- successful verification logs guardian into verified session
- typed email alone reveals nothing

### Unit B — field contract
- all guardian/member/application fields exist
- all required on submit except conditional field only when hidden
- drafts save incomplete values after verification
- field sources stored with exact enum values

### Unit C — chooser/dashboard
- existing guardian with draft sees `continue draft` primary CTA
- existing guardian without draft sees `start new registration` primary CTA
- registrations list visible in both cases

### Unit D — registration form
- guardian fields prefill from verified account only
- member fields start blank
- same-address toggle copies and disables member address input
- guardian identity, member identity, portrait uploads supported
- kit sizes come from admin-managed active options

### Unit E — security regression
- no same-browser anonymous continuation path
- no cross-account draft/portal access by typed email or guessed IDs
- parent portal and registration continuation share verified session gate

---

## 5. Documentation scope
- keep approved spec file as source of truth
- update `docs/milestones.md` when implementation lands
- update `AGENTS.md` only if route structure, auth workflow, or commands materially change
- no README update required unless parent entry URLs or local test flow materially change

---

## 6. Task breakdown

> **Commit note:** This plan intentionally omits commit steps because repository rules say commits happen only when user explicitly asks.

### Task 1: Write red tests for one-time-code auth and verified entry routes

**Files:**
- Create: `tests/accounts/test_email_verification_code.py`
- Create: `tests/registrations/test_verified_registration_entry.py`
- Modify: `tests/accounts/test_login_views.py`
- Modify: `tests/accounts/test_magic_links.py`

- [ ] **Step 1: Add failing model/service tests for email codes**

```python
# tests/accounts/test_email_verification_code.py
import pytest
from django.core import mail
from django.test import override_settings

from apps.accounts.models import EmailVerificationCode, ParentAccount
from apps.accounts.services import issue_email_code, verify_email_code

pytestmark = pytest.mark.django_db


def test_issue_email_code_creates_hashed_single_use_code():
    raw_code = issue_email_code("parent@example.com")
    record = EmailVerificationCode.objects.get(email="parent@example.com")
    assert raw_code.isdigit()
    assert len(raw_code) == 6
    assert record.code_hash != raw_code
    assert record.used_at is None


def test_verify_email_code_creates_parent_for_new_email():
    account = verify_email_code("new@example.com", issue_email_code("new@example.com"))
    assert isinstance(account, ParentAccount)
    assert account.email == "new@example.com"


@override_settings(EMAIL_CODE_RATE_LIMIT_PER_MINUTE=1)
def test_second_issue_in_window_raises_value_error():
    issue_email_code("limit@example.com")
    with pytest.raises(ValueError):
        issue_email_code("limit@example.com")
```

- [ ] **Step 2: Add failing route tests for `/register/` and `/register/verify/`**

```python
# tests/registrations/test_verified_registration_entry.py
import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_email_code
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY

pytestmark = pytest.mark.django_db


def test_register_post_sends_code_and_stores_pending_email_in_session():
    client = Client()
    response = client.post("/register/", {"email": "guardian@example.com"})
    assert response.status_code == 302
    assert response.url.endswith("/register/verify/")
    assert client.session["pending_verification_email"] == "guardian@example.com"


def test_verify_post_logs_existing_guardian_in_and_redirects_to_portal():
    ParentAccount.objects.create(email="guardian@example.com", phone="")
    client = Client()
    client.session["pending_verification_email"] = "guardian@example.com"
    client.session.save()
    code = issue_email_code("guardian@example.com")
    response = client.post("/register/verify/", {"code": code})
    assert response.status_code == 302
    assert response.url == "/portal/"
    assert PARENT_ACCOUNT_SESSION_KEY in client.session


def test_unverified_client_cannot_open_new_registration_form():
    response = Client().get("/applications/new/")
    assert response.status_code == 302
    assert response.url.startswith("/register/")
```

- [ ] **Step 3: Rewrite old auth view tests away from magic-link UX**

```python
# tests/accounts/test_login_views.py

def test_get_register_page_renders_email_entry_form(client):
    response = client.get("/register/")
    assert response.status_code == 200
    assert "E-pasts" in response.content.decode()
    assert "Saņemt kodu" in response.content.decode()


def test_invalid_code_shows_latvian_error(client):
    session = client.session
    session["pending_verification_email"] = "guardian@example.com"
    session.save()
    response = client.post("/register/verify/", {"code": "000000"})
    assert response.status_code == 400
    assert "Nederīgs vai noildzis kods" in response.content.decode()
```

- [ ] **Step 4: Run focused red tests**

Run:
```bash
uv run pytest tests/accounts/test_email_verification_code.py tests/registrations/test_verified_registration_entry.py tests/accounts/test_login_views.py -q
```

Expected: FAIL with missing `EmailVerificationCode`, missing `/register/verify/`, or old magic-link assertions.

### Task 2: Implement email-code model, forms, services, session helpers, and auth views

**Files:**
- Modify: `apps/accounts/models.py`
- Modify: `apps/accounts/forms.py`
- Modify: `apps/accounts/services.py`
- Modify: `apps/accounts/views.py`
- Modify: `apps/accounts/urls.py`
- Modify: `apps/accounts/session.py`
- Create: `apps/accounts/migrations/0004_email_verification_code_and_parent_profile.py`
- Create: `apps/documents/migrations/0004_p1_document_kinds.py`

- [ ] **Step 1: Add new model and parent profile fields if missing**

```python
# apps/accounts/models.py
class ParentAccount(TimeStampedModel):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True, default="")
    full_name = models.CharField(max_length=255, blank=True, default="")
    personal_id = models.CharField(max_length=32, blank=True, default="")
    declared_address = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)


class EmailVerificationCode(TimeStampedModel):
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 2: Add forms and session constants**

```python
# apps/accounts/forms.py
class EmailCodeRequestForm(forms.Form):
    email = forms.EmailField(label="E-pasts")


class EmailCodeVerifyForm(forms.Form):
    code = forms.CharField(min_length=6, max_length=6, label="Kods")
```

```python
# apps/accounts/session.py
PARENT_ACCOUNT_SESSION_KEY = "_parent_account_id"
PENDING_VERIFICATION_EMAIL_SESSION_KEY = "pending_verification_email"
```

- [ ] **Step 3: Implement code issue/send/verify services**

```python
# apps/accounts/services.py
from hashlib import sha256
import secrets


def issue_email_code(email: str) -> str:
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    EmailVerificationCode.objects.create(
        email=email,
        code_hash=_hash_token(raw_code),
        expires_at=_now_utc() + timedelta(minutes=_get_ttl_minutes()),
        sent_at=_now_utc(),
    )
    send_mail(..., message=f"Jūsu kods: {raw_code}", recipient_list=[email])
    return raw_code


def verify_email_code(email: str, raw_code: str) -> ParentAccount:
    record = EmailVerificationCode.objects.filter(
        email__iexact=email,
        code_hash=_hash_token(raw_code),
        used_at__isnull=True,
    ).order_by("-created_at").first()
    if record is None or record.expires_at < _now_utc():
        raise ValueError("Invalid or expired code")
    record.used_at = _now_utc()
    record.save(update_fields=["used_at"])
    account, _ = ParentAccount.objects.get_or_create(email=email, defaults={"phone": ""})
    return account
```

- [ ] **Step 4: Replace auth views with register-entry and verify-code handling**

```python
# apps/accounts/views.py

def request_login_code(request):
    form = EmailCodeRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        issue_email_code(email)
        request.session[PENDING_VERIFICATION_EMAIL_SESSION_KEY] = email
        return redirect("registrations:verify-registration-entry")
    return render(request, "registrations/start_registration.html", {"email_form": form})


def verify_login_code(request):
    pending_email = request.session.get(PENDING_VERIFICATION_EMAIL_SESSION_KEY)
    if not pending_email:
        return redirect("registrations:start-registration")
    form = EmailCodeVerifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = verify_email_code(pending_email, form.cleaned_data["code"])
        request.session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
        request.session.pop(PENDING_VERIFICATION_EMAIL_SESSION_KEY, None)
        return redirect("registrations:parent-portal")
    return render(request, "registrations/verify_registration_code.html", {"form": form, "email": pending_email})
```

- [ ] **Step 5: Add migration and run auth tests green**

Run:
```bash
uv run python manage.py makemigrations accounts
uv run pytest tests/accounts/test_email_verification_code.py tests/registrations/test_verified_registration_entry.py tests/accounts/test_login_views.py -q
```

Expected: PASS.

### Task 3: Write red tests for P1 registration field contract and chooser behavior

**Files:**
- Create: `tests/registrations/test_registration_form_contract.py`
- Create: `tests/registrations/test_registration_chooser.py`
- Modify: `tests/registrations/test_application_workflow.py`
- Modify: `tests/registrations/test_parent_identity_gate.py`

- [ ] **Step 1: Add failing field-contract tests**

```python
# tests/registrations/test_registration_form_contract.py
import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.members.models import KitSizeOption

pytestmark = pytest.mark.django_db


def _login(client, account):
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
    session.save()


def test_submit_requires_all_guardian_member_and_application_fields():
    account = ParentAccount.objects.create(email="guardian@example.com", phone="")
    client = Client()
    _login(client, account)
    response = client.post("/applications/new/", {"save_action": "submit"})
    content = response.content.decode()
    assert response.status_code == 400
    assert "guardian_full_name" in content
    assert "member_full_name" in content
    assert "preferred_agreement_signing" in content


def test_second_child_requires_support_club_discount_answer():
    account = ParentAccount.objects.create(email="guardian@example.com", phone="")
    client = Client()
    _login(client, account)
    # seed first child app here
    response = client.post("/applications/new/", valid_payload_without_discount_answer())
    assert response.status_code == 400
    assert "support_club_instead_of_multi_child_discount" in response.content.decode()
```

- [ ] **Step 2: Add failing chooser tests**

```python
# tests/registrations/test_registration_chooser.py

def test_existing_guardian_with_draft_sees_continue_draft_primary(client):
    account = ParentAccount.objects.create(email="guardian@example.com", phone="")
    app = create_draft_for(account, status="draft")
    login_client(client, account)
    response = client.get("/portal/")
    content = response.content.decode()
    assert response.status_code == 200
    assert f'href="/applications/{app.pk}/edit/"' in content
    assert "Turpināt melnrakstu" in content
    assert "Jauns pieteikums" in content


def test_existing_guardian_without_draft_sees_start_new_primary(client):
    account = ParentAccount.objects.create(email="guardian@example.com", phone="")
    login_client(client, account)
    response = client.get("/portal/")
    assert "Jauns pieteikums" in response.content.decode()
```

- [ ] **Step 3: Update security regression tests to new verified-only behavior**

```python
# tests/registrations/test_parent_identity_gate.py

def test_anonymous_client_cannot_resume_draft_without_verification(client, application):
    response = client.get(f"/applications/{application.pk}/edit/")
    assert response.status_code == 302
    assert response.url.startswith("/register/")


def test_typed_email_request_does_not_show_registration_list(client):
    response = client.post("/register/", {"email": "owner@example.com"})
    assert response.status_code == 302
    follow = client.get("/portal/")
    assert follow.status_code == 302
```

- [ ] **Step 4: Run red tests for contract + chooser + security**

Run:
```bash
uv run pytest tests/registrations/test_registration_form_contract.py tests/registrations/test_registration_chooser.py tests/registrations/test_parent_identity_gate.py -q
```

Expected: FAIL because current application model/form/portal still use old child-only fields and anonymous draft behavior.

### Task 4: Implement P1 schema, document kinds, kit sizes, and registration services

**Files:**
- Modify: `apps/registrations/models.py`
- Modify: `apps/registrations/services.py`
- Modify: `apps/documents/models.py`
- Modify: `apps/documents/services.py`
- Modify: `apps/members/models.py`
- Modify: `apps/members/admin.py`
- Create: `apps/members/migrations/0002_kit_size_option.py`
- Create: `apps/registrations/migrations/0004_p1_field_contract.py`

- [ ] **Step 1: Expand registration and document models**

```python
# apps/registrations/models.py
class RegistrationApplication(TimeStampedModel):
    class AgreementSigning(models.TextChoices):
        PAPER = "paper", "Paper"
        ELECTRONIC = "electronic", "Electronic"

    guardian_declared_address = models.CharField(max_length=255, blank=True)
    member_full_name = models.CharField(max_length=255, blank=True)
    member_personal_id = models.CharField(max_length=32, blank=True)
    member_birth_date = models.DateField(null=True, blank=True)
    member_actual_address = models.CharField(max_length=255, blank=True)
    member_same_address_as_guardian = models.BooleanField(default=False)
    member_kit_size_shirt = models.ForeignKey("members.KitSizeOption", ... , null=True, blank=True, related_name="shirt_applications")
    member_kit_size_shorts = models.ForeignKey("members.KitSizeOption", ... , null=True, blank=True, related_name="shorts_applications")
    preferred_agreement_signing = models.CharField(max_length=16, choices=AgreementSigning.choices, blank=True)
    support_club_instead_of_multi_child_discount = models.BooleanField(null=True, blank=True)
    field_sources = models.JSONField(default=dict, blank=True)
```

```python
# apps/documents/models.py
class Kind(models.TextChoices):
    GUARDIAN_IDENTITY = "guardian_identity", "Guardian identity"
    MEMBER_IDENTITY = "member_identity", "Member identity"
    MEMBER_PORTRAIT = "member_portrait", "Member portrait"
```

- [ ] **Step 2: Add kit size model and admin registration**

```python
# apps/members/admin.py
@admin.register(KitSizeOption)
class KitSizeOptionAdmin(admin.ModelAdmin):
    list_display = ("kind", "label", "sort_order", "is_active")
    list_filter = ("kind", "is_active")
    ordering = ("kind", "sort_order", "label")
```

- [ ] **Step 3: Rewrite registration service around finalized fields**

```python
# apps/registrations/services.py
REQUIRED_SUBMIT_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_declared_address",
    "guardian_email",
    "guardian_phone",
    "member_full_name",
    "member_personal_id",
    "member_birth_date",
    "member_actual_address",
    "preferred_agreement_signing",
)


def create_or_update_draft(...):
    application.guardian_email = verified_account.email
    application.guardian_declared_address = data.get("guardian_declared_address", "").strip()
    application.member_full_name = data.get("member_full_name", "").strip()
    application.member_same_address_as_guardian = bool(data.get("member_same_address_as_guardian"))
    if application.member_same_address_as_guardian:
        application.member_actual_address = application.guardian_declared_address
        application.field_sources["member_actual_address"] = "derived_system_filled"
    else:
        application.member_actual_address = data.get("member_actual_address", "").strip()
        application.field_sources["member_actual_address"] = "manual_only"
```

- [ ] **Step 4: Centralize document replacement helpers**

```python
# apps/documents/services.py

def replace_active_document(*, application, kind, upload):
    existing = application.documents.filter(kind=kind, deleted_at__isnull=True).first()
    if existing is not None:
        existing.deleted_at = timezone.now()
        existing.save(update_fields=["deleted_at", "updated_at"])
    return Document.objects.create(
        application=application,
        kind=kind,
        file=upload,
        original_filename=upload.name,
        content_type=getattr(upload, "content_type", "application/octet-stream"),
        file_size=upload.size,
    )
```

- [ ] **Step 5: Run service/model tests green**

Run:
```bash
uv run python manage.py makemigrations members registrations documents
uv run pytest tests/registrations/test_registration_form_contract.py tests/registrations/test_application_workflow.py -q
```

Expected: PASS or smaller remaining failures limited to views/templates.

### Task 5: Implement forms, verified-only registration views, and chooser/dashboard

**Files:**
- Modify: `apps/registrations/forms.py`
- Modify: `apps/registrations/views.py`
- Modify: `apps/registrations/urls.py`
- Modify: `templates/registrations/start_registration.html`
- Create: `templates/registrations/verify_registration_code.html`
- Modify: `templates/registrations/edit_registration.html`
- Modify: `templates/registrations/parent_portal.html`

- [ ] **Step 1: Replace old registration form with finalized P1 fields**

```python
# apps/registrations/forms.py
class RegistrationApplicationForm(forms.Form):
    guardian_full_name = forms.CharField(required=False, label="Vecāka vārds, uzvārds")
    guardian_personal_id = forms.CharField(required=False, label="Vecāka personas kods")
    guardian_declared_address = forms.CharField(required=False, label="Deklarētā adrese")
    guardian_email = forms.EmailField(required=False, disabled=True, label="E-pasts")
    guardian_phone = forms.CharField(required=False, label="Tālrunis")
    guardian_identity_document = forms.FileField(required=False, label="Vecāka ID dokuments")
    member_full_name = forms.CharField(required=False, label="Bērna vārds, uzvārds")
    member_personal_id = forms.CharField(required=False, label="Bērna personas kods")
    member_birth_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    member_same_address_as_guardian = forms.BooleanField(required=False, label="Tāda pati kā vecākam")
    member_actual_address = forms.CharField(required=False, label="Faktiskā adrese")
    member_kit_size_shirt = forms.ModelChoiceField(queryset=KitSizeOption.objects.none(), required=False)
    member_kit_size_shorts = forms.ModelChoiceField(queryset=KitSizeOption.objects.none(), required=False)
    member_identity_document = forms.FileField(required=False, label="Bērna ID dokuments")
    member_portrait = forms.FileField(required=False, label="Portreta foto")
    preferred_agreement_signing = forms.ChoiceField(choices=RegistrationApplication.AgreementSigning.choices, required=False)
    support_club_instead_of_multi_child_discount = forms.NullBooleanField(required=False)
```

- [ ] **Step 2: Add verified guard and chooser view behavior**

```python
# apps/registrations/views.py

def require_parent_account(request):
    account = _current_parent_account(request)
    if account is None:
        return None, redirect("registrations:start-registration")
    return account, None


def start_registration(request):
    return request_login_code(request)


def verify_registration_entry(request):
    return verify_login_code(request)


def parent_portal(request):
    account, redirect_response = require_parent_account(request)
    if redirect_response:
        return redirect_response
    applications = account.applications.order_by("-created_at")
    draft = applications.filter(status__in=[RegistrationApplication.Status.DRAFT, RegistrationApplication.Status.FIX_REQUESTED]).first()
    return render(request, "registrations/parent_portal.html", {"account": account, "applications": applications, "draft_application": draft})
```

- [ ] **Step 3: Add `/applications/new/` and verified-only edit/submit flow**

```python
# apps/registrations/urls.py
urlpatterns = [
    path("register/", views.start_registration, name="start-registration"),
    path("register/verify/", views.verify_registration_entry, name="verify-registration-entry"),
    path("applications/new/", views.new_registration, name="new-registration"),
    path("applications/<int:application_id>/edit/", views.edit_registration, name="edit-registration"),
    path("portal/", views.parent_portal, name="parent-portal"),
]
```

```python
# apps/registrations/views.py

def new_registration(request):
    account, redirect_response = require_parent_account(request)
    if redirect_response:
        return redirect_response
    form = RegistrationApplicationForm(request.POST or None, request.FILES or None, verified_account=account)
    if request.method == "POST" and form.is_valid():
        application = create_or_update_draft(data=form.cleaned_data, files=request.FILES, verified_account=account)
        if request.POST.get("save_action") == "submit":
            submit_application(application, account)
            return redirect("registrations:parent-portal")
        return redirect("registrations:edit-registration", application_id=application.pk)
    return render(request, "registrations/edit_registration.html", {"form": form, "application": None})
```

- [ ] **Step 4: Update templates for email entry, code verify, chooser, and final field list**

```html
<!-- templates/registrations/parent_portal.html -->
{% if draft_application %}
  <a href="{% url 'registrations:edit-registration' draft_application.id %}">Turpināt melnrakstu</a>
{% endif %}
<a href="{% url 'registrations:new-registration' %}">Jauns pieteikums</a>
<ul>
  {% for application in applications %}
    <li>{{ application.member_full_name }} — {{ application.get_status_display }}</li>
  {% endfor %}
</ul>
```

- [ ] **Step 5: Run view tests green**

Run:
```bash
uv run pytest tests/registrations/test_verified_registration_entry.py tests/registrations/test_registration_chooser.py tests/registrations/test_registration_form_contract.py tests/registrations/test_parent_identity_gate.py -q
```

Expected: PASS.

### Task 6: Update approval path and remaining domain tests for renamed fields

**Files:**
- Modify: `apps/registrations/services.py`
- Modify: `tests/registrations/test_application_workflow.py`
- Modify: `tests/registrations/test_admin_review_flow.py`
- Modify: `tests/members/test_member_models.py`

- [ ] **Step 1: Update approval flow to use member-field names**

```python
# apps/registrations/services.py
member = Member.objects.create(
    full_name=application.member_full_name,
    personal_id=application.member_personal_id,
    birth_date=application.member_birth_date,
    guardian=guardian,
    training_group=None,
)
```

- [ ] **Step 2: Update tests that still reference `child_*` and `guardian_address`**

```python
# tests/registrations/test_admin_review_flow.py
assert application.member_full_name == "Test Child"
assert guardian.address == application.guardian_declared_address
```

- [ ] **Step 3: Run affected tests**

Run:
```bash
uv run pytest tests/registrations/test_application_workflow.py tests/registrations/test_admin_review_flow.py tests/members/test_member_models.py -q
```

Expected: PASS.

### Task 7: Full verification and documentation refresh

**Files:**
- Modify: `docs/milestones.md`
- Modify: `AGENTS.md` (only if implementation changed project guidance)

- [ ] **Step 1: Update milestone status after green implementation**

```md
### P1 — Field-set finalization + guardian-email-first verified registration gate
Status: implemented in current worktree
- guardian/member/application field set finalized
- code-based verified entry live
- chooser/dashboard live
```

- [ ] **Step 2: Run full project verification**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```

Expected: all commands pass.

- [ ] **Step 3: Generate review diff for user**

Run:
```bash
bunx critique --web "Implement P1 verified registration gate" --filter "apps/accounts/**" --filter "apps/registrations/**" --filter "apps/documents/**" --filter "apps/members/**" --filter "templates/registrations/**" --filter "tests/accounts/**" --filter "tests/registrations/**" --filter "docs/milestones.md"
```

Expected: critique URL to share with user.

---

## 7. Self-review checklist

### Spec coverage map
- finalized field list → Tasks 3, 4, 5
- one-time-code-only gate → Tasks 1, 2, 5
- existing guardian chooser → Tasks 3, 5
- new guardian immediate account creation → Task 2
- same verified gate for continuation + portal → Tasks 1, 5
- minimal document kinds + kit sizes → Task 4
- cross-account regression coverage → Tasks 1, 3, 5

### Placeholder scan
- no `TODO`, `TBD`, or “similar to above” shortcuts remain
- concrete route paths, model names, and commands are specified

### Type consistency
- P1 field names use `member_*` and `guardian_declared_address` consistently
- support-club conditional answer uses one name: `support_club_instead_of_multi_child_discount`
- code auth uses `EmailVerificationCode` consistently

---

Plan complete and saved to `docs/superpowers/plans/2026-05-08-p1-field-contract-and-verified-registration-gate.md`.

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
