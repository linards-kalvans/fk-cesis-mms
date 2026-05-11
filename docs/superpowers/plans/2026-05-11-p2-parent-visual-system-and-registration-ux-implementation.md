# P2 Parent Visual System and Registration UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build cohesive FK Cēsis parent-facing pages with shared Django UI primitives, a unified application workspace, clearer document state, and lightweight OCR source review cues without changing P1 security guarantees.

**Architecture:** Keep verified-parent and ownership rules intact while refactoring parent-facing routes, templates, and form presentation around a shared parent-shell design system. Introduce a canonical application workspace route, presentation helpers for document/source state, and reusable template partials so visual polish can evolve without rewriting business logic.

**Tech Stack:** Django 5.x templates/forms/views, pytest + pytest-django, uv, existing registration/accounts/documents apps, static CSS using style-guide tokens

---

## File structure map

### Existing files to modify
- `apps/registrations/urls.py` — parent-facing route shape, canonical application workspace route, redirect compatibility
- `apps/registrations/views.py` — portal/application workspace context shaping, redirects, parent-facing helper usage
- `apps/registrations/forms.py` — grouped rendering metadata, document help text, error-summary support, source-marker contract
- `apps/accounts/views.py` — verify page context alignment if parent-facing shell needs richer verify-state data
- `templates/base.html` — include parent-facing CSS assets safely
- `templates/includes/parent_shell.html` — either simplify into wrapper include or replace with new parent UI partial usage
- `templates/registrations/start_registration.html` — redesign entry page
- `templates/registrations/verify_code.html` — redesign verification page
- `templates/registrations/parent_portal.html` — redesign chooser/list page
- `templates/registrations/new_registration.html` — either redirect or thin wrapper into canonical workspace
- `templates/registrations/edit_registration.html` — either redirect or thin wrapper into canonical workspace
- `templates/registrations/view_registration_summary.html` — either redirect or status-mode workspace wrapper
- `templates/registrations/view_registration_detail.html` — either redirect or status-mode workspace wrapper
- `tests/registrations/test_parent_visual_pages.py` — stable UI behavior assertions for redesigned parent pages
- `tests/registrations/test_parent_edit_permissions.py` — canonical route and redirect/ownership regression coverage
- `tests/registrations/test_registration_chooser.py` — portal chooser behavior and new route targets
- `tests/registrations/test_registration_form_contract.py` — grouped rendering / submit behavior contract
- `tests/registrations/test_verified_registration_entry.py` — register/verify page regression coverage
- `tests/registrations/test_parent_identity_gate.py` — verified access gate regression coverage
- `AGENTS.md` — update current-status/docs references after implementation
- `docs/milestones.md` — mark P2 scope/status after implementation

### New files to create
- `apps/registrations/presentation.py` — small pure helpers for portal primary action, document card state, OCR/source labels, workspace mode
- `templates/parent_ui/base_parent_page.html` — shared parent page wrapper
- `templates/parent_ui/includes/header.html` — branded FK Cēsis header
- `templates/parent_ui/includes/hero_card.html` — hero/intro block primitive
- `templates/parent_ui/includes/section_card.html` — card wrapper primitive
- `templates/parent_ui/includes/status_badge.html` — workflow badge partial
- `templates/parent_ui/includes/alert.html` — info/success/warning/error partial
- `templates/parent_ui/includes/form_field.html` — labeled field with errors/help/source hint partial
- `templates/parent_ui/includes/error_summary.html` — top validation summary partial
- `templates/parent_ui/includes/document_card.html` — parent-facing document state card partial
- `templates/parent_ui/includes/source_badge.html` — extracted/entered/verified hint partial
- `templates/parent_ui/includes/application_status_banner.html` — status-aware top banner for workspace pages
- `templates/registrations/application_workspace.html` — canonical parent application page
- `static/css/parent_theme.css` — shared parent-facing visual tokens consumption and typography/layout rules
- `static/css/parent_pages.css` — page-level parent components/styles
- `tests/registrations/test_parent_application_workspace.py` — workspace access/mode/redirect coverage
- `tests/registrations/test_document_state_presentation.py` — document card state rendering coverage
- `tests/registrations/test_ocr_source_presentation.py` — OCR/source-hint rendering coverage
- `docs/superpowers/plans/2026-05-11-p2-parent-visual-system-and-registration-ux-implementation.md` — this plan

### Responsibility boundaries
- `apps/registrations/views.py` stays responsible for HTTP flow only.
- `apps/registrations/presentation.py` holds page-shaping helpers so templates and views do not accumulate UI-only logic.
- `apps/registrations/forms.py` holds field grouping/help/error contract, but not route or document-query logic.
- `templates/parent_ui/includes/*.html` holds reusable rendering primitives, not page-specific branching.
- `templates/registrations/application_workspace.html` is the only canonical parent application page template.

---

### Task 1: Lock parent-facing route and workflow contract with failing tests

**Files:**
- Modify: `tests/registrations/test_parent_visual_pages.py`
- Modify: `tests/registrations/test_parent_edit_permissions.py`
- Modify: `tests/registrations/test_registration_chooser.py`
- Modify: `tests/registrations/test_verified_registration_entry.py`
- Modify: `tests/registrations/test_parent_identity_gate.py`
- Create: `tests/registrations/test_parent_application_workspace.py`

- [ ] **Step 1: Write failing tests for canonical application workspace route**

```python
# tests/registrations/test_parent_application_workspace.py
import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def test_owner_can_open_canonical_workspace_route():
    client = Client()
    account = ParentAccount.objects.create(email="workspace@example.com", phone="+37120000000")
    _login(client, account)
    application = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Workspace Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Workspace Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=account,
    )

    response = client.get(f"/applications/{application.pk}/")

    assert response.status_code == 200
    assert "Workspace Child" in response.content.decode()


def test_non_owner_gets_404_on_canonical_workspace_route():
    owner = ParentAccount.objects.create(email="owner@example.com", phone="+37120000001")
    stranger = ParentAccount.objects.create(email="stranger@example.com", phone="+37120000002")
    owner_client = Client()
    _login(owner_client, owner)
    application = create_or_update_draft(
        data={
            "guardian_email": owner.email,
            "guardian_full_name": "Owner Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000001",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Owner Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=owner,
    )
    stranger_client = Client()
    _login(stranger_client, stranger)

    response = stranger_client.get(f"/applications/{application.pk}/")

    assert response.status_code == 404
```

- [ ] **Step 2: Add failing tests for route redirects and mode-specific rendering**

```python
def test_edit_route_redirects_to_canonical_workspace_when_enabled():
    client = Client()
    account = ParentAccount.objects.create(email="redirect@example.com", phone="+37120000003")
    _login(client, account)
    application = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Redirect Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000003",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Redirect Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=account,
    )

    response = client.get(f"/applications/{application.pk}/edit/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/applications/{application.pk}/")


def test_submitted_application_workspace_is_read_only():
    from apps.registrations.services import submit_application
    from django.core.files.uploadedfile import SimpleUploadedFile

    client = Client()
    account = ParentAccount.objects.create(email="readonly@example.com", phone="+37120000004")
    _login(client, account)
    application = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Readonly Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000004",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Readonly Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
            "member_same_address_as_guardian": True,
            "preferred_agreement_signing": "paper",
        },
        files={
            "guardian_identity_document": SimpleUploadedFile("guardian.png", b"x", content_type="image/png"),
            "member_identity_document": SimpleUploadedFile("member.png", b"x", content_type="image/png"),
            "member_portrait_document": SimpleUploadedFile("portrait.png", b"x", content_type="image/png"),
        },
        verified_account=account,
    )
    submit_application(application, account)

    response = client.get(f"/applications/{application.pk}/")
    content = response.content.decode()

    assert response.status_code == 200
    assert "Saglabāt melnrakstu" not in content
    assert "Iesniegt pieteikumu" not in content
    assert "Iesniegts" in content or "submitted" in content.lower()
```

- [ ] **Step 3: Update existing portal and register-page tests to target stable behavior hooks**

```python
# tests/registrations/test_parent_visual_pages.py
class TestParentPortalSummary:
    def test_portal_shows_primary_continue_action_when_editable_application_exists(self):
        response = self.client.get("/portal/")
        content = response.content.decode()
        assert "Turpināt pieteikumu" in content

    def test_portal_shows_start_new_action_even_when_editable_application_exists(self):
        response = self.client.get("/portal/")
        content = response.content.decode()
        assert "Sākt jaunu reģistrāciju" in content


class TestRegisterPageGuidance:
    def test_register_page_explains_secure_verification_step(self):
        response = Client().get("/register/")
        content = response.content.decode()
        assert "Droša piekļuve" in content
        assert "e-pasts" in content.lower()
```

- [ ] **Step 4: Run targeted tests to verify red phase**

Run: `uv run pytest tests/registrations/test_parent_application_workspace.py tests/registrations/test_parent_visual_pages.py tests/registrations/test_registration_chooser.py tests/registrations/test_parent_edit_permissions.py -q`

Expected: FAIL with missing `/applications/<id>/` route, missing redirects, and missing new branded copy/hook assertions.

- [ ] **Step 5: Commit test-only red phase**

```bash
git add tests/registrations/test_parent_application_workspace.py tests/registrations/test_parent_visual_pages.py tests/registrations/test_registration_chooser.py tests/registrations/test_parent_edit_permissions.py tests/registrations/test_verified_registration_entry.py tests/registrations/test_parent_identity_gate.py
git commit -m "test: define P2 parent page contract"
```

---

### Task 2: Implement shared parent shell and redesign register/verify/portal pages

**Files:**
- Create: `templates/parent_ui/base_parent_page.html`
- Create: `templates/parent_ui/includes/header.html`
- Create: `templates/parent_ui/includes/hero_card.html`
- Create: `templates/parent_ui/includes/section_card.html`
- Create: `templates/parent_ui/includes/status_badge.html`
- Create: `templates/parent_ui/includes/alert.html`
- Create: `templates/parent_ui/includes/error_summary.html`
- Create: `static/css/parent_theme.css`
- Create: `static/css/parent_pages.css`
- Modify: `templates/base.html`
- Modify: `templates/includes/parent_shell.html`
- Modify: `templates/registrations/start_registration.html`
- Modify: `templates/registrations/verify_code.html`
- Modify: `templates/registrations/parent_portal.html`
- Modify: `apps/accounts/views.py`
- Modify: `apps/registrations/views.py`
- Test: `tests/registrations/test_parent_visual_pages.py`
- Test: `tests/registrations/test_registration_chooser.py`
- Test: `tests/registrations/test_verified_registration_entry.py`

- [ ] **Step 1: Add parent-facing CSS assets to base template**

```django
{# templates/base.html #}
{% load static %}
<!doctype html>
<html lang="lv">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}FK Cēsis{% endblock %}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{% static 'style-guide/tokens.css' %}">
    <link rel="stylesheet" href="{% static 'css/parent_theme.css' %}">
    <link rel="stylesheet" href="{% static 'css/parent_pages.css' %}">
    {% block extra_head %}{% endblock %}
  </head>
```

- [ ] **Step 2: Create shared parent page wrapper and header partials**

```django
{# templates/parent_ui/base_parent_page.html #}
{% extends "base.html" %}

{% block content %}
<div class="fk-parent-page">
  {% include "parent_ui/includes/header.html" %}
  <main class="fk-parent-page__main">
    {% block parent_page_content %}{% endblock %}
  </main>
</div>
{% endblock %}
```

```django
{# templates/parent_ui/includes/header.html #}
{% load static %}
<header class="fk-site-header">
  <div class="fk-site-header__inner">
    <div class="fk-site-brand">
      {% include "includes/site_logo.html" with logo_class="fk-logo fk-logo--header" %}
      <div>
        <div class="fk-site-brand__title">FK Cēsis</div>
        <div class="fk-site-brand__subtitle">Bērnu reģistrācija</div>
      </div>
    </div>
    {% if request.session.pending_verification_email %}
      <div class="fk-site-header__meta">Droša piekļuve ar e-pasta verifikāciju</div>
    {% endif %}
  </div>
</header>
```

- [ ] **Step 3: Implement redesigned register, verify, and portal templates**

```django
{# templates/registrations/start_registration.html #}
{% extends "parent_ui/base_parent_page.html" %}

{% block title %}FK Cēsis — Bērna reģistrācija{% endblock %}

{% block parent_page_content %}
<section class="fk-hero-card">
  <p class="fk-eyebrow">FK Cēsis</p>
  <h1>Bērna reģistrācija</h1>
  <p class="fk-lead">Droša piekļuve sākas ar vecāka e-pasta pārbaudi. Ievadiet savu e-pastu, lai turpinātu reģistrāciju vai apskatītu iepriekšējos pieteikumus.</p>
</section>
<section class="fk-section-card">
  {% if error %}
    {% include "parent_ui/includes/alert.html" with tone="error" title="Neizdevās turpināt" body=error %}
  {% endif %}
  <form method="post" class="fk-form-stack">
    {% csrf_token %}
    <label class="fk-form-label" for="id_email">E-pasts</label>
    <input id="id_email" name="email" type="email" autocomplete="email" class="fk-text-input" required>
    <p class="fk-form-help">Nosūtīsim vienreizēju kodu drošai piekļuvei.</p>
    <button type="submit" class="fk-button fk-button--primary">Turpināt</button>
  </form>
</section>
{% endblock %}
```

```django
{# templates/registrations/verify_code.html #}
{% extends "parent_ui/base_parent_page.html" %}

{% block parent_page_content %}
<section class="fk-hero-card fk-hero-card--narrow">
  <p class="fk-eyebrow">Droša piekļuve</p>
  <h1>Apstipriniet e-pastu</h1>
  <p class="fk-lead">Ievadiet kodu, ko nosūtījām uz <strong>{{ pending_email }}</strong>. Pēc apstiprināšanas varēsiet turpināt vai pārskatīt savus pieteikumus.</p>
</section>
<section class="fk-section-card fk-section-card--narrow">
  {% if error %}
    {% include "parent_ui/includes/alert.html" with tone="error" title="Kodu neizdevās pārbaudīt" body=error %}
  {% endif %}
  <form method="post" class="fk-form-stack">
    {% csrf_token %}
    <label class="fk-form-label" for="id_code">Piekļuves kods</label>
    <input id="id_code" name="code" type="text" value="{{ code|default:'' }}" class="fk-text-input" inputmode="numeric" autocomplete="one-time-code" required>
    <button type="submit" class="fk-button fk-button--primary">Apstiprināt</button>
  </form>
</section>
{% endblock %}
```

```django
{# templates/registrations/parent_portal.html #}
{% extends "parent_ui/base_parent_page.html" %}

{% block parent_page_content %}
<section class="fk-hero-card">
  <div>
    <p class="fk-eyebrow">Mani pieteikumi</p>
    <h1>Pārskatiet un turpiniet</h1>
    <p class="fk-lead">Šeit redzams katra pieteikuma statuss un nākamais solis.</p>
  </div>
  <div class="fk-hero-actions">
    {% if primary_application %}
      <a class="fk-button fk-button--primary" href="{% url 'registrations:application-workspace' primary_application.id %}">Turpināt pieteikumu</a>
    {% endif %}
    <a class="fk-button fk-button--secondary" href="{% url 'registrations:new-application' %}">Sākt jaunu reģistrāciju</a>
  </div>
</section>
<section class="fk-list-card">
  {% for application in applications %}
    <article class="fk-status-card">
      <div>
        <h2>{{ application.member_full_name|default:application.guardian_email }}</h2>
        <p>{{ application.guardian_full_name|default:application.guardian_email }}</p>
      </div>
      <div>
        {% include "parent_ui/includes/status_badge.html" with status=application.status label=application.get_status_display %}
      </div>
      <div class="fk-status-card__actions">
        <a class="fk-button fk-button--secondary" href="{% url 'registrations:application-workspace' application.id %}">{% if application.can_edit %}Turpināt{% else %}Skatīt{% endif %}</a>
      </div>
    </article>
  {% empty %}
    <div class="fk-empty-state">Nav pieteikumu. Sāciet jaunu reģistrāciju.</div>
  {% endfor %}
</section>
{% endblock %}
```

- [ ] **Step 4: Add minimal view helpers to support portal primary action and richer verify context**

```python
# apps/registrations/views.py

def _portal_primary_application(account: ParentAccount) -> RegistrationApplication | None:
    return (
        account.applications.filter(
            status__in=(
                RegistrationApplication.Status.DRAFT,
                RegistrationApplication.Status.FIX_REQUESTED,
            )
        )
        .order_by("-updated_at", "-created_at")
        .first()
    )


def parent_portal(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if account is None:
        return redirect("registrations:start-registration")

    applications = account.applications.order_by("-created_at")
    for app in applications:
        app.can_edit = app.is_editable_by(account)

    return render(
        request,
        "registrations/parent_portal.html",
        {
            "account": account,
            "applications": applications,
            "primary_application": _portal_primary_application(account),
        },
    )
```

- [ ] **Step 5: Run targeted page tests to verify pass**

Run: `uv run pytest tests/registrations/test_parent_visual_pages.py tests/registrations/test_registration_chooser.py tests/registrations/test_verified_registration_entry.py -q`

Expected: PASS for register/verify/portal redesign assertions; remaining workspace tests may still fail.

- [ ] **Step 6: Commit shared shell and entry/portal redesign**

```bash
git add templates/base.html templates/includes/parent_shell.html templates/parent_ui templates/registrations/start_registration.html templates/registrations/verify_code.html templates/registrations/parent_portal.html static/css/parent_theme.css static/css/parent_pages.css apps/accounts/views.py apps/registrations/views.py
git commit -m "feat: redesign parent entry and portal pages"
```

---

### Task 3: Implement canonical application workspace, grouped form rendering, and redirect compatibility

**Files:**
- Create: `apps/registrations/presentation.py`
- Create: `templates/parent_ui/includes/form_field.html`
- Create: `templates/parent_ui/includes/source_badge.html`
- Create: `templates/parent_ui/includes/application_status_banner.html`
- Create: `templates/registrations/application_workspace.html`
- Modify: `apps/registrations/urls.py`
- Modify: `apps/registrations/views.py`
- Modify: `apps/registrations/forms.py`
- Modify: `templates/registrations/new_registration.html`
- Modify: `templates/registrations/edit_registration.html`
- Modify: `templates/registrations/view_registration_summary.html`
- Modify: `templates/registrations/view_registration_detail.html`
- Test: `tests/registrations/test_parent_application_workspace.py`
- Test: `tests/registrations/test_parent_edit_permissions.py`
- Test: `tests/registrations/test_registration_form_contract.py`

- [ ] **Step 1: Add canonical workspace route and redirect old routes to it**

```python
# apps/registrations/urls.py
path("applications/<int:application_id>/", views.application_workspace, name="application-workspace"),
path("applications/<int:application_id>/edit/", views.redirect_application_workspace, name="edit-registration"),
path("applications/<int:application_id>/summary/", views.redirect_application_workspace, name="view-registration-summary"),
path("applications/<int:application_id>/detail/", views.redirect_application_workspace, name="view-registration-detail"),
```

```python
# apps/registrations/views.py

def redirect_application_workspace(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404
    return redirect("registrations:application-workspace", application_id=application.id)
```

- [ ] **Step 2: Add presentation helpers for mode, field groups, and source labels**

```python
# apps/registrations/presentation.py
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication


def workspace_mode(application: RegistrationApplication, account) -> str:
    return "editable" if application.is_editable_by(account) else "read_only"


def active_documents_by_kind(application: RegistrationApplication) -> dict[str, Document | None]:
    docs = {kind: None for kind in Document.Kind.values}
    for document in application.documents.filter(deleted_at__isnull=True).order_by("-created_at"):
        docs.setdefault(document.kind, document)
        if docs[document.kind] is None:
            docs[document.kind] = document
    return docs


def source_label(source_value: str | None) -> str | None:
    mapping = {
        "ocr_guardian_identity": "Aizpildīts no dokumenta",
        "ocr_member_identity": "Aizpildīts no dokumenta",
        "manual_only": "Ievadījāt jūs",
        "derived_system_filled": "Aizpildīts no pārbaudīta konta",
    }
    return mapping.get(source_value)
```

- [ ] **Step 3: Refactor form to expose grouped fields and error-summary data**

```python
# apps/registrations/forms.py
class RegistrationApplicationForm(forms.Form):
    section_order = (
        ("guardian", ("guardian_full_name", "guardian_personal_id", "guardian_email", "guardian_phone", "guardian_declared_address")),
        ("member", ("member_full_name", "member_personal_id", "member_birth_date", "member_actual_address", "member_same_address_as_guardian", "member_kit_size_shirt", "member_kit_size_shorts")),
        ("documents", ("guardian_identity_document", "member_identity_document", "member_portrait_document")),
        ("agreement", ("preferred_agreement_signing", "support_club_instead_of_multi_child_discount")),
    )

    def grouped_fields(self):
        for section_name, field_names in self.section_order:
            yield section_name, [self[name] for name in field_names]

    def error_summary_items(self):
        items = []
        for field_name, errors in self.errors.items():
            label = self.fields.get(field_name).label if field_name in self.fields else field_name
            for error in errors:
                items.append({"field": field_name, "label": label, "message": error})
        return items
```

- [ ] **Step 4: Implement canonical application workspace template and view**

```python
# apps/registrations/views.py
from apps.registrations.presentation import active_documents_by_kind, source_label, workspace_mode


def application_workspace(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404

    editable = application.is_editable_by(account)
    if request.method == "POST":
        if not editable:
            raise Http404
        form = RegistrationApplicationForm(
            request.POST,
            request.FILES,
            is_submit=request.POST.get("submit_action") == "submit",
            has_existing_document=active_documents_by_kind(application)["guardian_identity"] is not None,
        )
        if form.is_valid():
            application = create_or_update_draft(
                data=form.cleaned_data,
                files=request.FILES,
                application=application,
                verified_account=account,
            )
            if request.POST.get("submit_action") == "submit":
                submit_application(application, account)
                return redirect("registrations:parent-portal")
            return redirect("registrations:application-workspace", application_id=application.id)
    else:
        form = RegistrationApplicationForm(initial={
            "guardian_full_name": application.guardian_full_name,
            "guardian_personal_id": application.guardian_personal_id,
            "guardian_email": application.guardian_email,
            "guardian_phone": application.guardian_phone,
            "guardian_declared_address": application.guardian_declared_address,
            "member_full_name": application.member_full_name,
            "member_personal_id": application.member_personal_id,
            "member_birth_date": application.member_birth_date,
            "member_actual_address": application.member_actual_address,
            "member_same_address_as_guardian": application.member_same_address_as_guardian,
            "member_kit_size_shirt": application.member_kit_size_shirt_id,
            "member_kit_size_shorts": application.member_kit_size_shorts_id,
            "preferred_agreement_signing": application.preferred_agreement_signing,
            "support_club_instead_of_multi_child_discount": application.support_club_instead_of_multi_child_discount,
        })

    context = {
        "application": application,
        "form": form,
        "workspace_mode": workspace_mode(application, account),
        "document_state": active_documents_by_kind(application),
        "field_source_labels": {name: source_label(value) for name, value in (application.field_sources or {}).items()},
    }
    return render(request, "registrations/application_workspace.html", context)
```

```django
{# templates/registrations/application_workspace.html #}
{% extends "parent_ui/base_parent_page.html" %}

{% block parent_page_content %}
<section class="fk-page-heading">
  <p class="fk-eyebrow">Pieteikums</p>
  <h1>{{ application.member_full_name|default:"Jauns pieteikums" }}</h1>
  {% include "parent_ui/includes/application_status_banner.html" with application=application mode=workspace_mode %}
</section>
{% if form.errors %}
  {% include "parent_ui/includes/error_summary.html" with items=form.error_summary_items %}
{% endif %}
<form method="post" enctype="multipart/form-data" class="fk-workspace-form">
  {% csrf_token %}
  {% for section_name, bound_fields in form.grouped_fields %}
    <section class="fk-section-card">
      <h2>{{ section_name|title }}</h2>
      {% for bound_field in bound_fields %}
        {% include "parent_ui/includes/form_field.html" with field=bound_field source_label=field_source_labels|default:{}|dictsort:None %}
      {% endfor %}
    </section>
  {% endfor %}
  {% if workspace_mode == "editable" %}
    <div class="fk-form-actions">
      <button type="submit" name="submit_action" value="save_draft" class="fk-button fk-button--secondary">Saglabāt melnrakstu</button>
      <button type="submit" name="submit_action" value="submit" class="fk-button fk-button--primary">Iesniegt pieteikumu</button>
    </div>
  {% endif %}
</form>
{% endblock %}
```

- [ ] **Step 5: Run targeted workspace and form-contract tests**

Run: `uv run pytest tests/registrations/test_parent_application_workspace.py tests/registrations/test_parent_edit_permissions.py tests/registrations/test_registration_form_contract.py -q`

Expected: PASS for canonical workspace access, redirect compatibility, grouped-form contract, and read-only status behavior.

- [ ] **Step 6: Commit canonical workspace implementation**

```bash
git add apps/registrations/urls.py apps/registrations/views.py apps/registrations/forms.py apps/registrations/presentation.py templates/registrations/application_workspace.html templates/registrations/new_registration.html templates/registrations/edit_registration.html templates/registrations/view_registration_summary.html templates/registrations/view_registration_detail.html templates/parent_ui/includes/form_field.html templates/parent_ui/includes/source_badge.html templates/parent_ui/includes/application_status_banner.html tests/registrations/test_parent_application_workspace.py tests/registrations/test_parent_edit_permissions.py tests/registrations/test_registration_form_contract.py
git commit -m "feat: add parent application workspace"
```

---

### Task 4: Implement document-state cards, OCR source cues, validation summary polish, and full verification

**Files:**
- Create: `templates/parent_ui/includes/document_card.html`
- Modify: `apps/registrations/forms.py`
- Modify: `apps/registrations/presentation.py`
- Modify: `apps/registrations/views.py`
- Modify: `templates/parent_ui/includes/form_field.html`
- Modify: `templates/parent_ui/includes/error_summary.html`
- Modify: `templates/registrations/application_workspace.html`
- Create: `tests/registrations/test_document_state_presentation.py`
- Create: `tests/registrations/test_ocr_source_presentation.py`
- Modify: `tests/registrations/test_parent_visual_pages.py`
- Modify: `AGENTS.md`
- Modify: `docs/milestones.md`

- [ ] **Step 1: Write failing tests for active-document state and OCR source hints**

```python
# tests/registrations/test_document_state_presentation.py
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def test_workspace_shows_existing_guardian_document_filename():
    client = Client()
    account = ParentAccount.objects.create(email="docstate@example.com", phone="+37121111111")
    _login(client, account)
    application = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Doc Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37121111111",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Doc Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={"guardian_identity_document": SimpleUploadedFile("guardian-existing.png", b"x", content_type="image/png")},
        verified_account=account,
    )

    response = client.get(f"/applications/{application.pk}/")
    content = response.content.decode()

    assert "guardian-existing.png" in content
    assert "Esošais dokuments" in content
    assert "Aizstājot tiks saglabāta jaunākā versija" in content
```

```python
# tests/registrations/test_ocr_source_presentation.py
import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def test_workspace_marks_extracted_field_source_when_present():
    client = Client()
    account = ParentAccount.objects.create(email="ocrsource@example.com", phone="+37122222222")
    _login(client, account)
    application = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "OCR Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37122222222",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "OCR Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=account,
    )
    application.field_sources = {
        "guardian_full_name": "ocr_guardian_identity",
        "guardian_email": "derived_system_filled",
    }
    application.save(update_fields=["field_sources", "updated_at"])

    response = client.get(f"/applications/{application.pk}/")
    content = response.content.decode()

    assert "Aizpildīts no dokumenta" in content
    assert "Aizpildīts no pārbaudīta konta" in content
```

- [ ] **Step 2: Implement reusable document card and source-aware form field partials**

```django
{# templates/parent_ui/includes/document_card.html #}
<section class="fk-document-card">
  <div class="fk-document-card__header">
    <h3>{{ title }}</h3>
    {% if document %}
      <span class="fk-document-card__state">Esošais dokuments</span>
    {% else %}
      <span class="fk-document-card__state fk-document-card__state--empty">Dokuments vēl nav pievienots</span>
    {% endif %}
  </div>
  {% if document %}
    <p class="fk-document-card__filename">{{ document.original_filename }}</p>
    <p class="fk-document-card__hint">Aizstājot tiks saglabāta jaunākā versija, bet iepriekšējā versija netiks rādīta kā aktīvā.</p>
  {% else %}
    <p class="fk-document-card__hint">Pievienojiet dokumentu vai aizstājiet esošo, ja dati ir mainījušies.</p>
  {% endif %}
  {{ field }}
</section>
```

```django
{# templates/parent_ui/includes/form_field.html #}
<div class="fk-form-field{% if field.errors %} fk-form-field--error{% endif %}">
  <label class="fk-form-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
  {% if source_label %}
    {% include "parent_ui/includes/source_badge.html" with label=source_label %}
  {% endif %}
  {{ field }}
  {% if field.help_text %}<p class="fk-form-help">{{ field.help_text }}</p>{% endif %}
  {% for error in field.errors %}<p class="fk-form-error">{{ error }}</p>{% endfor %}
</div>
```

- [ ] **Step 3: Wire document cards and source labels into workspace context/template**

```python
# apps/registrations/views.py
context = {
    "application": application,
    "form": form,
    "workspace_mode": workspace_mode(application, account),
    "document_state": active_documents_by_kind(application),
    "field_source_labels": {
        name: source_label(value)
        for name, value in (application.field_sources or {}).items()
        if source_label(value) is not None
    },
}
```

```django
{# templates/registrations/application_workspace.html #}
<section class="fk-section-card">
  <h2>Dokumenti</h2>
  {% include "parent_ui/includes/document_card.html" with title="Vecāka personas dokuments" document=document_state.guardian_identity field=form.guardian_identity_document %}
  {% include "parent_ui/includes/document_card.html" with title="Bērna personu apliecinošs dokuments" document=document_state.member_identity field=form.member_identity_document %}
  {% include "parent_ui/includes/document_card.html" with title="Bērna portrets" document=document_state.member_portrait field=form.member_portrait_document %}
</section>
```

- [ ] **Step 4: Add top error summary rendering and targeted form help text**

```python
# apps/registrations/forms.py
self.fields["guardian_identity_document"].help_text = "Ja dokuments jau ir pievienots, varat to aizstāt ar jaunāku versiju."
self.fields["member_identity_document"].help_text = "Pārbaudiet, vai dokumenta dati sakrīt ar ievadīto informāciju."
self.fields["member_portrait_document"].help_text = "Augšupielādējiet aktuālu portreta foto, ja tas ir pieejams."
```

```django
{# templates/parent_ui/includes/error_summary.html #}
{% if items %}
<div class="fk-alert fk-alert--error" role="alert">
  <h2>Lūdzu pārbaudiet laukus</h2>
  <ul>
    {% for item in items %}
      <li><a href="#{{ item.field }}">{{ item.label }} — {{ item.message }}</a></li>
    {% endfor %}
  </ul>
</div>
{% endif %}
```

- [ ] **Step 5: Run targeted tests, then full verification suite**

Run: `uv run pytest tests/registrations/test_document_state_presentation.py tests/registrations/test_ocr_source_presentation.py tests/registrations/test_parent_application_workspace.py tests/registrations/test_parent_visual_pages.py -q`

Expected: PASS for document-state and source-hint behavior.

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`

Expected: all commands PASS.

- [ ] **Step 6: Update project docs and commit final P2 implementation**

```bash
git add apps/registrations/forms.py apps/registrations/presentation.py apps/registrations/views.py templates/parent_ui/includes/document_card.html templates/parent_ui/includes/form_field.html templates/parent_ui/includes/error_summary.html templates/registrations/application_workspace.html tests/registrations/test_document_state_presentation.py tests/registrations/test_ocr_source_presentation.py tests/registrations/test_parent_visual_pages.py AGENTS.md docs/milestones.md
git commit -m "feat: polish parent document and OCR review UX"
```

---

## Spec coverage self-check
- Shared parent visual system: covered by Task 2 CSS + parent partials.
- Register/verify/portal redesign: covered by Task 2.
- Canonical application workspace: covered by Task 3.
- Route reshaping with compatibility: covered by Task 3 redirects.
- Document active/replace clarity: covered by Task 4 document-card tests and template wiring.
- OCR extracted-vs-entered clarity: covered by Task 4 source-badge tests and field rendering.
- Validation summary improvements: covered by Task 4 error summary and form help text.
- Preserve verified security/ownership: covered by Task 1 and Task 3 regression tests.
- Keep implementation maintainable with shared primitives: covered by file structure and Task 2/3 partials.

## Placeholder self-check
- No `TODO` or `TBD` placeholders remain.
- Every step includes explicit file targets, concrete code direction, command, and expected outcome.
- Commit steps are included but should only be executed if the user explicitly asks for commits during implementation.

## Type/contract consistency self-check
- Canonical route name used consistently: `registrations:application-workspace`.
- Presentation helper names used consistently: `workspace_mode`, `active_documents_by_kind`, `source_label`.
- Form helper names used consistently: `grouped_fields`, `error_summary_items`.
- Route-compatibility helpers consistently redirect old parent application pages to canonical workspace route.
