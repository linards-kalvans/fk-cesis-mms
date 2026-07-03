# P7 Slice C-i — Admin Review Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the bespoke staff review flow into the Django admin: the `RegistrationApplication` change page hosts the review panels + flow actions (at the top) above the native edit form; the changelist gets status-aware quick actions; the custom review queue/detail views are deleted.

**Architecture:** A custom `change_form_template` renders the existing review partials (documents/OCR/lightbox + agreement + training-group) via `extra_context` from an overridden `change_view`, with an action bar at the top. Per-object action endpoints registered via `ModelAdmin.get_urls()` call the existing (already-audited) services and redirect back. The custom `admin_review_queue` / `admin_review_detail` views, URLs, and templates are removed.

**Tech Stack:** Django 5.x admin, pytest-django, `uv run` for everything. No model changes / no migrations.

Spec: `docs/superpowers/specs/2026-06-14-p7-admin-review-consolidation-design.md`. Builds on P7 Slice A (service-layer audit) — services are reused unchanged.

---

## File Structure

- `apps/registrations/admin_panels.py` — **new**. Extracted review-context builder: `doc_preview_kind`, `build_doc_panel`, `build_review_context(application)`. Pure-ish (DB reads only); importable by both the admin and (transitionally) `views.py`.
- `apps/registrations/admin.py` — `RegistrationApplicationAdmin`: `change_form_template`, `change_view` (inject review context), `get_urls()` (action endpoints), the action views (port of the current POST dispatch), changelist quick-action column, `Media` (css/js), repointed `review_link`.
- `templates/admin/registrations/registrationapplication/change_form.html` — **new**. Extends `admin/change_form.html`; top action bar + review panels (includes the existing partials).
- `templates/admin/registrations/registrationapplication/approve_confirm.html` — **new**. Approve confirmation page.
- `apps/registrations/views.py` — **delete** `admin_review_queue`, `admin_review_detail` (and `_doc_preview_kind`/`_build_doc_panel`, now moved; and `_require_staff` if unused after).
- `apps/registrations/urls.py` — **delete** the two `admin/review/...` routes.
- `templates/registrations/admin_review_queue.html`, `templates/registrations/admin_review_detail.html` — **delete**.
- `templates/registrations/admin/_agreement_module.html` — repoint its `<form action=...>` to the new admin action URL.
- **Keep unchanged:** `templates/registrations/admin/_doc_panel.html`, `static/admin/css/review.css`, `static/admin/js/doc_lightbox.js`.

**Facts to use (verified):**
- Services (all already audited at the service layer): `approve_application(application, reviewer, training_group=None)`, `reject_application(application, reviewer, message)`, `request_application_fix(application, reviewer, message)`, `assign_training_group(member, group, actor)`, `mark_agreement_sent(agreement, actor)`, `mark_agreement_signed(agreement, actor)`, `void_agreement(agreement, actor, reason)`, `regenerate_agreement(member, signing_path, actor)`, `set_signing_path(agreement, signing_path, actor)`, `enqueue_create_agreement_submission(agreement_id)`, `enqueue_sync_agreement_submission(agreement_id)`, `get_current_agreement(member)`, `get_agreement_error_message(code)`.
- The current POST dispatch + context build is `apps/registrations/views.py:663-927` (`admin_review_detail`) and `views.py:610-660` (`_build_doc_panel`) — port these.
- `AgreementAdmin` has **no** `get_absolute_url` (nothing to repoint there; leave it as-is).
- `member.source_application` reverse relation exists (RegistrationApplication → its approved Member).
- Admin custom-URL reverse name pattern: `admin:registrations_registrationapplication_<name>`.
- mypy: this repo has no django-stubs plugin — admin method overrides and `format_html` returns may need `# type: ignore[...]` exactly as the existing `review_link` does (`apps/registrations/admin.py:85-93`). Follow that established pattern.

---

### Task 1: Extract the review-context builder

**Files:**
- Create: `apps/registrations/admin_panels.py`
- Modify: `apps/registrations/views.py` (import the moved helpers from the new module)
- Test: `tests/registrations/test_admin_review_context.py`

**Context:** Move `_doc_preview_kind` + `_build_doc_panel` out of `views.py` into a reusable module and add `build_review_context(application)` returning the full context the change page needs. `views.py` keeps working by importing them (it still has `admin_review_detail` until Task 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_admin_review_context.py
"""build_review_context — panels + agreement + training-group context for the admin change page."""

import pytest

from apps.registrations.admin_panels import build_review_context, doc_preview_kind
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def test_doc_preview_kind_classifies_by_extension():
    class _Doc:
        original_filename = "id.PNG"
        file = None
    assert doc_preview_kind(_Doc()) == "image"
    _Doc.original_filename = "scan.pdf"
    assert doc_preview_kind(_Doc()) == "pdf"
    _Doc.original_filename = "notes.txt"
    assert doc_preview_kind(_Doc()) == "other"


def test_build_review_context_keys():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    ctx = build_review_context(app)
    assert set(ctx) >= {
        "guardian_panel", "member_panel", "portrait_panel",
        "active_training_groups", "current_inactive_group",
        "agreement", "agreement_error_message",
    }
    # No approved member yet -> no agreement.
    assert ctx["agreement"] is None
    assert ctx["guardian_panel"]["kind"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_admin_review_context.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.registrations.admin_panels`.

- [ ] **Step 3: Create the module**

Create `apps/registrations/admin_panels.py` by moving the existing `_doc_preview_kind` (views.py:588-607) and `_build_doc_panel` (views.py:610-660) verbatim, renamed public (`doc_preview_kind`, `build_doc_panel`), plus a new `build_review_context`. Copy the exact imports those helpers need (`Document`, `decrypt_json`, `parse_ocr_summary`, `OCR_FIELD_LABELS`, `DOCUMENT_KIND_LABELS`, `TrainingGroup`, `get_current_agreement`, `get_agreement_error_message`) — check `views.py` for their import sources.

```python
"""Review-context builder for the RegistrationApplication admin change page.

Moved out of views.py so the Django admin change view can render the same
document/OCR + agreement + training-group panels the old custom review page did.
"""

from apps.agreements.services import get_current_agreement
from apps.agreements.messages import get_agreement_error_message
from apps.documents.models import Document
from apps.documents.ocr import decrypt_json
from apps.members.models import TrainingGroup
from apps.registrations.models import RegistrationApplication
# OCR_FIELD_LABELS, DOCUMENT_KIND_LABELS, parse_ocr_summary: import from wherever
# views.py imports them (verify the exact module paths in views.py and mirror).

_IMAGE_PREVIEW_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic"})
_PDF_PREVIEW_EXTENSIONS = frozenset({"pdf"})


def doc_preview_kind(document: object) -> str:
    # ... verbatim body of the current _doc_preview_kind ...


def build_doc_panel(application: RegistrationApplication, kind: str) -> dict[str, object]:
    # ... verbatim body of the current _build_doc_panel (calls doc_preview_kind) ...


def build_review_context(application: RegistrationApplication) -> dict[str, object]:
    guardian_panel = build_doc_panel(application, str(Document.Kind.GUARDIAN_IDENTITY))
    member_panel = build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY))
    portrait_panel = build_doc_panel(application, str(Document.Kind.MEMBER_PORTRAIT))

    active_training_groups = list(TrainingGroup.objects.filter(is_active=True).order_by("name"))

    current_inactive_group = None
    agreement = None
    if application.approved_member_id is not None:
        assigned = application.approved_member.training_group
        if assigned is not None and not assigned.is_active:
            current_inactive_group = assigned
        agreement = get_current_agreement(application.approved_member)

    agreement_error_message = None
    if agreement is not None and agreement.external_state == "failed":
        agreement_error_message = get_agreement_error_message(agreement.external_error_code)

    return {
        "guardian_panel": guardian_panel,
        "member_panel": member_panel,
        "portrait_panel": portrait_panel,
        "active_training_groups": active_training_groups,
        "current_inactive_group": current_inactive_group,
        "agreement": agreement,
        "agreement_error_message": agreement_error_message,
    }
```

Then in `views.py`, replace the two moved functions with `from apps.registrations.admin_panels import build_doc_panel, doc_preview_kind` and update `admin_review_detail` to call `build_doc_panel` (it still works until Task 5 deletes it). Remove the now-duplicate `_IMAGE_PREVIEW_EXTENSIONS`/`_PDF_PREVIEW_EXTENSIONS` from views.py.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_context.py -v`
Then: `uv run pytest tests/registrations/ -q` (the existing `admin_review_detail` tests must still pass — it now imports the moved helper).
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/registrations/admin_panels.py apps/registrations/views.py tests/registrations/test_admin_review_context.py
uv run mypy apps/registrations/admin_panels.py apps/registrations/views.py
git add apps/registrations/admin_panels.py apps/registrations/views.py tests/registrations/test_admin_review_context.py && git commit -m "refactor(registrations): extract review-context builder to admin_panels (P7 C-i)"
```

---

### Task 2: Change page renders the review panels (read-only)

**Files:**
- Modify: `apps/registrations/admin.py` (`RegistrationApplicationAdmin`: `change_form_template`, `change_view`, `Media`)
- Create: `templates/admin/registrations/registrationapplication/change_form.html`
- Test: `tests/registrations/test_admin_change_page_panels.py`

**Context:** Render the review panels on the admin change page (no actions yet — Task 3 adds them). The action bar placeholder + panels go above the native form.

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_admin_change_page_panels.py
"""Admin change page renders the review panels."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_change_page_shows_review_panels():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    c = _staff_client()
    url = reverse("admin:registrations_registrationapplication_change", args=[app.pk])
    html = c.get(url).content.decode()
    assert "mms-review-panel" in html        # review.css panel markup present
    assert "review.css" in html              # admin Media loaded the stylesheet
    assert "doc_lightbox.js" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_admin_change_page_panels.py -v`
Expected: FAIL — the default admin change form has none of those markers.

- [ ] **Step 3: Implement the change_form template + admin hooks**

Create `templates/admin/registrations/registrationapplication/change_form.html`:

```django
{% extends "admin/change_form.html" %}
{% load static %}

{% block field_sets %}
  {# Review panels + action bar render ABOVE the native edit form. #}
  <div class="mms-admin-review">
    {% block mms_action_bar %}{% endblock %}
    {% if original %}
      {% include "registrations/admin/_doc_panel.html" with panel=guardian_panel %}
      {% include "registrations/admin/_doc_panel.html" with panel=member_panel %}
      {% include "registrations/admin/_doc_panel.html" with panel=portrait_panel %}
      {% if agreement %}
        {% include "registrations/admin/_agreement_module.html" %}
      {% endif %}
    {% endif %}
  </div>
  {{ block.super }}
{% endblock %}
```

(Verify how `_doc_panel.html` consumes its context — the current detail template includes it as `{% include "registrations/admin/_doc_panel.html" with panel=guardian_panel %}` or by passing the dict members; match the existing include contract exactly. Adjust the `with ...` to match.)

In `apps/registrations/admin.py`, on `RegistrationApplicationAdmin`, add:

```python
    change_form_template = "admin/registrations/registrationapplication/change_form.html"

    class Media:
        css = {"all": ["admin/css/review.css"]}
        js = ["admin/js/doc_lightbox.js"]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        from apps.registrations.admin_panels import build_review_context

        extra_context = extra_context or {}
        app = self.get_object(request, object_id)
        if app is not None:
            extra_context.update(build_review_context(app))
        return super().change_view(request, object_id, form_url, extra_context)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_admin_change_page_panels.py -v`
Expected: PASS. (If `_doc_panel.html` errors on missing context keys, fix the `with` mapping to match the partial's expected names.)

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/registrations/ -q
uv run ruff check apps/registrations/admin.py
uv run mypy apps/registrations/admin.py
git add apps/registrations/admin.py templates/admin/registrations/registrationapplication/change_form.html tests/registrations/test_admin_change_page_panels.py && git commit -m "feat(registrations): admin change page renders review panels (P7 C-i)"
```

---

### Task 3: Action endpoints + top action bar

**Files:**
- Modify: `apps/registrations/admin.py` (`get_urls`, the action views, the approve-confirm view)
- Modify: `templates/admin/registrations/registrationapplication/change_form.html` (fill `mms_action_bar`)
- Create: `templates/admin/registrations/registrationapplication/approve_confirm.html`
- Modify: `templates/registrations/admin/_agreement_module.html` (repoint form `action`)
- Test: `tests/registrations/test_admin_review_actions.py`

**Context:** Port the POST dispatch from `views.py:705-925` into admin endpoints. Two URLs: `review-action/<id>/` (POST dispatch for reject/request_fix/assign_group/agreement_*) and `approve/<id>/` (GET confirm page + POST commit). Buttons live in the top action bar. Service `ValueError` → `self.message_user(..., level=messages.ERROR)`; success → redirect (reject/approve → changelist, else back to change page).

- [ ] **Step 1: Write the failing tests**

```python
# tests/registrations/test_admin_review_actions.py
"""Admin review-action endpoints port the staff flow into the admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _submitted():
    return RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )


def test_reject_action_transitions_and_redirects_to_changelist():
    app = _submitted()
    c = _staff_client()
    url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(url, {"action": "reject", "review_message": "trūkst dokumenta"})
    assert resp.status_code == 302
    assert reverse("admin:registrations_registrationapplication_changelist") in resp.url
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.REJECTED


def test_request_fix_requires_message_surfaces_error():
    app = _submitted()
    c = _staff_client()
    url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(url, {"action": "request_fix", "review_message": ""}, follow=True)
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.SUBMITTED  # unchanged
    assert b"oblig" in resp.content.lower()  # an error message shown


def test_action_endpoint_is_staff_only():
    app = _submitted()
    c = Client()  # anonymous
    url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(url, {"action": "reject", "review_message": "x"})
    assert resp.status_code in (302, 403)  # admin login redirect or forbidden
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.SUBMITTED


def test_approve_confirm_then_commit():
    app = _submitted()
    c = _staff_client()
    confirm_url = reverse("admin:registrations_registrationapplication_approve", args=[app.pk])
    assert c.get(confirm_url).status_code == 200  # confirm page
    resp = c.post(confirm_url, {})  # commit
    assert resp.status_code == 302
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.APPROVED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_admin_review_actions.py -v`
Expected: FAIL — `NoReverseMatch` (endpoints not registered).

- [ ] **Step 3: Implement the endpoints**

In `apps/registrations/admin.py`, add the imports (services + `path`, `redirect`, `get_object_or_404`, `messages`, `TrainingGroup`, `Agreement`) and to `RegistrationApplicationAdmin`:

```python
    def get_urls(self):
        from django.urls import path

        urls = super().get_urls()
        custom = [
            path(
                "<int:object_id>/review-action/",
                self.admin_site.admin_view(self.review_action_view),
                name="registrations_registrationapplication_review-action",
            ),
            path(
                "<int:object_id>/approve/",
                self.admin_site.admin_view(self.approve_view),
                name="registrations_registrationapplication_approve",
            ),
        ]
        return custom + urls

    def _change_redirect(self, object_id):
        from django.shortcuts import redirect
        return redirect("admin:registrations_registrationapplication_change", object_id)

    def _changelist_redirect(self):
        from django.shortcuts import redirect
        return redirect("admin:registrations_registrationapplication_changelist")
```

`review_action_view(self, request, object_id)` ports the POST dispatch from `views.py:705-925` for every action EXCEPT `approve` (approve has its own confirm view). Faithful port, but: replace each `render(..., {error}, status=400)` with `self.message_user(request, "<latvian>", level=messages.ERROR)` + `self._change_redirect(object_id)`; success redirects use `_change_redirect` (or `_changelist_redirect` for `reject`); permission via `admin_site.admin_view` (login) + an explicit `if not self.has_change_permission(request): raise PermissionDenied`. Build `agreement`/`application` exactly as the old view did (`get_object_or_404`, `get_current_agreement`). The Latvian error strings are already in `views.py:705-925` — reuse them verbatim.

`approve_view(self, request, object_id)`:
```python
    def approve_view(self, request, object_id):
        from django.contrib.admin.utils import unquote
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, render
        from apps.members.models import TrainingGroup
        from apps.registrations.services import approve_application

        if not self.has_change_permission(request):
            raise PermissionDenied
        app = get_object_or_404(RegistrationApplication, pk=unquote(object_id))
        if request.method == "POST":
            raw_group = request.POST.get("training_group", "").strip()
            group = None
            if raw_group:
                try:
                    group = TrainingGroup.objects.get(pk=int(raw_group))
                except (TrainingGroup.DoesNotExist, ValueError):
                    self.message_user(request, "Nezināma treniņu grupa.", level=messages.ERROR)
                    return self._change_redirect(object_id)
            try:
                approve_application(app, request.user, training_group=group)
            except ValueError as exc:
                msg = str(exc)
                latvian = (
                    "Nevar piešķirt neaktīvu treniņu grupu apstiprināšanas brīdī." if "inactive" in msg
                    else "Var apstiprināt tikai iesniegtus pieteikumus." if "submitted" in msg
                    else "Pieteikumu nevarēja apstiprināt."
                )
                self.message_user(request, latvian, level=messages.ERROR)
                return self._change_redirect(object_id)
            self.message_user(request, "Pieteikums apstiprināts.")
            return self._changelist_redirect()
        # GET -> confirm page
        return render(request, "admin/registrations/registrationapplication/approve_confirm.html", {
            **self.admin_site.each_context(request),
            "original": app,
            "active_training_groups": TrainingGroup.objects.filter(is_active=True).order_by("name"),
            "opts": self.model._meta,
        })
```

Create `templates/admin/registrations/registrationapplication/approve_confirm.html` extending `admin/base_site.html` with a short form: a heading "Apstiprināt pieteikumu — {{ original.member_full_name }}?", an optional training-group `<select name="training_group">`, a CSRF token, a submit "Apstiprināt" button POSTing to the same URL, and a Cancel link to the change page.

Fill `{% block mms_action_bar %}` in `change_form.html`: for `original.status == "submitted"`, render the Approve button (links/forms to the approve URL), and the Request-fix + Reject disclosure forms (textarea `review_message`, hidden `action`) POSTing to the review-action URL. Reuse the markup/classes from the current `admin_review_detail.html:51-89` (the action forms), changing each `<form>`'s `action` to `{% url 'admin:registrations_registrationapplication_review-action' original.pk %}` and `method="post"` with `{% csrf_token %}`.

Repoint `templates/registrations/admin/_agreement_module.html`: change its form `action` attributes from `{% url 'registrations:admin-review-detail' application.id %}` (or whatever it currently targets) to `{% url 'admin:registrations_registrationapplication_review-action' application.pk %}`. (Verify the current target + the context var name for the application in that partial.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_review_actions.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/registrations/ -q
uv run ruff check apps/registrations/admin.py
uv run mypy apps/registrations/admin.py
git add apps/registrations/admin.py templates/admin/registrations/registrationapplication/ templates/registrations/admin/_agreement_module.html tests/registrations/test_admin_review_actions.py && git commit -m "feat(registrations): admin review-action endpoints + top action bar (P7 C-i)"
```

---

### Task 4: Changelist quick actions + repoint review_link

**Files:**
- Modify: `apps/registrations/admin.py` (`list_display` quick-action column; `review_link`)
- Test: `tests/registrations/test_admin_changelist_quick_actions.py`

**Context:** Add a status-aware quick-action column: agreement `generated` → "Atzīmēt nosūtītu" (POST `agreement_sent`), agreement `sent` → "Atzīmēt parakstītu" (POST `agreement_signed`), always an "Atvērt →" link to the change page. Repoint `review_link` to the admin change URL (or fold it into the open link).

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_admin_changelist_quick_actions.py
"""Changelist shows status-aware quick actions."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.members.models import Guardian, Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_renders_open_link_and_agreement_quick_action():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    Agreement.objects.create(member=m, is_current=True, state=Agreement.State.GENERATED)
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Atvērt" in html
    assert "Atzīmēt nosūtītu" in html  # generated -> mark sent quick action
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_admin_changelist_quick_actions.py -v`
Expected: FAIL — no such markup.

- [ ] **Step 3: Implement the quick-action column**

In `RegistrationApplicationAdmin`, replace `review_link` in `list_display` with a `quick_actions` method that renders (via `format_html` / `format_html_join`):
- always: an "Atvērt →" link to `admin:registrations_registrationapplication_change`.
- if the app has an approved member with a current agreement in `generated`: a small POST form (button "Atzīmēt nosūtītu", hidden `action=mark_agreement_sent` + csrf) to the review-action URL.
- if agreement `sent`: button "Atzīmēt parakstītu" (`action=mark_agreement_signed`).

To avoid N+1 on the changelist, extend `get_queryset` with `select_related("approved_member")` (the agreement lookup uses `get_current_agreement(member)` — acceptable per-row for the modest queue size; note it in a comment). Use the existing `# type: ignore` admin-method pattern (`short_description`, `format_html` return) from the current `review_link`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_admin_changelist_quick_actions.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/registrations/ -q
uv run ruff check apps/registrations/admin.py
uv run mypy apps/registrations/admin.py
git add apps/registrations/admin.py tests/registrations/test_admin_changelist_quick_actions.py && git commit -m "feat(registrations): status-aware changelist quick actions (P7 C-i)"
```

---

### Task 5: Delete the custom review queue + detail

**Files:**
- Modify: `apps/registrations/views.py` (delete `admin_review_queue`, `admin_review_detail`, and `_require_staff` if now unused)
- Modify: `apps/registrations/urls.py` (delete the two routes)
- Delete: `templates/registrations/admin_review_queue.html`, `templates/registrations/admin_review_detail.html`
- Test: `tests/registrations/test_custom_review_views_removed.py`; update/remove the old `admin_review_detail`/`admin_review_queue` tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_custom_review_views_removed.py
"""The bespoke review queue/detail are gone; the admin is the entry point."""

import pytest
from django.urls import NoReverseMatch, reverse

pytestmark = pytest.mark.django_db


def test_old_review_routes_are_gone():
    with pytest.raises(NoReverseMatch):
        reverse("registrations:admin-review-queue")
    with pytest.raises(NoReverseMatch):
        reverse("registrations:admin-review-detail", args=[1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_custom_review_views_removed.py -v`
Expected: FAIL — the routes still reverse.

- [ ] **Step 3: Delete the views, routes, templates**

- Remove `admin_review_queue` and `admin_review_detail` from `views.py`. Remove `_require_staff` if no other view uses it (grep first; keep if used elsewhere). Remove now-unused imports (`get_agreement_error_message`, the agreement-service imports, `TrainingGroup`, etc.) that only `admin_review_detail` used — let ruff F401 guide you.
- Delete the two `path("admin/review/...")` lines from `urls.py`.
- `git rm templates/registrations/admin_review_queue.html templates/registrations/admin_review_detail.html`.
- Find any remaining references: `grep -rn "admin-review-detail\|admin-review-queue\|admin_review_detail\|admin_review_queue" apps/ templates/ tests/` and fix/remove them (e.g. the old admin-review tests in `tests/registrations/test_admin_review_flow.py` and similar — port their assertions to the new admin endpoints if they cover unique behavior, otherwise delete the now-duplicated ones).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_custom_review_views_removed.py -v`
Then: `uv run pytest tests/registrations/ -q` (fix/remove any tests still referencing the deleted views).
Expected: PASS, no references to the deleted routes remain.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/registrations/views.py apps/registrations/urls.py
uv run mypy apps/registrations/views.py
git add -A apps/registrations/ templates/registrations/ tests/registrations/ && git commit -m "refactor(registrations): remove bespoke review queue/detail; admin is the entry point (P7 C-i)"
```

---

### Task 6: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .   # informational only — do NOT reformat unrelated files
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: pytest/ruff-check/mypy green; "No changes detected" for migrations. (`ruff format` is not an enforced gate.)

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "P7 Slice C-i delivered — admin review consolidation" entry: the registration review now lives on the Django admin change page (panels + top action bar) + changelist quick actions; the custom `admin_review_queue`/`admin_review_detail` views/URLs/templates removed; services unchanged + still audited; C-ii (cross-links + sync-health + search/filter) remains.
- `docs/milestones.md`: note C-i delivered under the P7 admin-operations item.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record P7 Slice C-i admin review consolidation"
```

---

## Self-Review Notes

- **Spec coverage:** §2/§3 layout → T2 (panels) + T3 (action bar); §4 action endpoints → T3 (ports the views.py:705-925 dispatch, services unchanged); §5 approve confirm → T3 `approve_view`; §6 changelist quick actions → T4; §7 deletions/repoints → T5 (+ `_agreement_module.html` repoint in T3, `review_link` in T4); §8 perms/audit → T3 (`admin_view` + `has_change_permission`; services audit themselves); §10 testing → each task; §11 acceptance → covered. AgreementAdmin `get_absolute_url` is NOT repointed (it doesn't exist — corrected from the spec).
- **Reuse:** `_doc_panel.html`, `_agreement_module.html` (action repointed), `review.css`, `doc_lightbox.js` kept; the proven POST dispatch ported verbatim with `message_user` swapped for the 400-renders.
- **No model changes / no migrations** — `makemigrations --check` must stay clean.
- **Type/name consistency:** endpoint URL names `registrations_registrationapplication_review-action` / `_approve` used identically in admin `get_urls`, the templates' `{% url %}`, and the tests; `build_review_context` / `build_doc_panel` / `doc_preview_kind` consistent across T1–T2.
- **Implementer caveats flagged inline:** verify `_doc_panel.html` / `_agreement_module.html` include-context contract + current form `action` target; verify exact import sources for `OCR_FIELD_LABELS` / `DOCUMENT_KIND_LABELS` / `parse_ocr_summary`; grep for all references to the deleted routes before removing; follow the existing `# type: ignore` admin pattern.
