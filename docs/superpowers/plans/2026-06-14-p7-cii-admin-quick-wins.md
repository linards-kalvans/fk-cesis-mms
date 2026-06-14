# P7 Slice C-ii batch 1 — Admin Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three admin flow-polish wins: Registrations app at the top of the admin menu, agreement-status column on the applications list, and one-click billing-record confirm (change page + list).

**Architecture:** A thin custom `AdminSite` (via `AdminConfig.default_site`) reorders the app list; a `list_display` method adds the agreement state to the applications changelist; `BillingRecordAdmin` gets a `get_urls()` confirm endpoint driven by a top change-page button and a per-row one-click POST on the changelist (CSRF token minted from the stored request, mirroring the registrations `quick_actions` pattern).

**Tech Stack:** Django 5.x admin, pytest-django, `uv run`. No model changes / no migrations.

Spec: `docs/superpowers/specs/2026-06-14-p7-cii-admin-quick-wins-design.md`.

---

## File Structure

- `apps/core/admin_site.py` — **new** `FkAdminSite(admin.AdminSite)` overriding `get_app_list` (registrations first).
- `apps/core/apps.py` — add `FkAdminConfig(AdminConfig)` with `default_site` (keep the existing `CoreConfig`).
- `fk_cesis_mms/settings.py` — swap `"django.contrib.admin"` → `"apps.core.apps.FkAdminConfig"` in `INSTALLED_APPS`.
- `apps/registrations/admin.py` — add `agreement_status` display method + column.
- `apps/billing/admin.py` — `BillingRecordAdmin`: `get_urls()` confirm endpoint, `confirm_view`, `change_form_template`, `confirm_action` list column, `get_queryset` request-storage.
- `templates/admin/billing/billingrecord/change_form.html` — **new** top action bar with the confirm button.
- Tests (new): `tests/core/test_admin_app_ordering.py`, `tests/registrations/test_admin_agreement_status_column.py`, `tests/billing/test_admin_confirm_action.py`.

**Facts to use (verified):**
- `INSTALLED_APPS` has `"django.contrib.admin"` at line 41; `apps.core` at line 48.
- `BillingRecord.Status`: `DRAFT = "draft", "Sagatavots"` / `CONFIRMED = "confirmed", "Apstiprināts"`.
- `BillingRecordAdmin` (apps/billing/admin.py) has `actions = ("recompute_from_plan", "push_to_invoice_ninja", "sync_payments")`, no `get_urls`/`get_queryset`/`change_form_template` yet; `recompute_from_plan` already gates on `status == BillingRecord.Status.DRAFT`.
- `RegistrationApplicationAdmin` already imports `get_current_agreement` and has `get_queryset` with `select_related("guardian", "parent_account", "approved_member")` + a `quick_actions` column using `get_token(self._request)` (the request is stored via `self._request = request` in `get_queryset`). Mirror this for billing.
- `Agreement.get_state_display()` gives the concise Latvian state ("Sagatavots"/"Nosūtīts"/"Parakstīts"/"Atcelts"). Use it for the admin column (NOT the verbose parent-facing `agreement_status_copy`).
- `@admin.display(description="…")` decorator is the clean way to add a display method (see `BillingRecordAdmin.guardian_name`) — avoids the `# type: ignore` `short_description` dance, though `format_html` returns may still need `# type: ignore[return-value]` consistent with `quick_actions`.
- Billing test fixtures: `active_plan` + `guardian` in `tests/billing/conftest.py`.
- Open-redirect safety: validate any `next` with `django.utils.http.url_has_allowed_host_and_scheme`.

---

### Task 1: Registrations app to the top of the admin menu

**Files:**
- Create: `apps/core/admin_site.py`
- Modify: `apps/core/apps.py`, `fk_cesis_mms/settings.py`
- Test: `tests/core/test_admin_app_ordering.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_admin_app_ordering.py
"""The Registrations app is listed first in the admin (custom AdminSite)."""

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


def test_registrations_app_listed_first():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff", "s@example.com", "pw")
    app_list = admin.site.get_app_list(req)
    assert app_list, "admin app list is empty"
    assert app_list[0]["app_label"] == "registrations"


def test_all_apps_still_present():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff2", "s2@example.com", "pw")
    labels = {app["app_label"] for app in admin.site.get_app_list(req)}
    # core (AuditEvent), billing, members, agreements all still registered.
    assert {"registrations", "billing", "members", "agreements", "core"} <= labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_admin_app_ordering.py -v`
Expected: FAIL — default `AdminSite` sorts apps alphabetically, so `app_list[0]` is not "registrations".

- [ ] **Step 3: Create the custom AdminSite**

`apps/core/admin_site.py`:

```python
"""Custom admin site — reorders the app list so the most-used app is first."""

from django.contrib import admin


class FkAdminSite(admin.AdminSite):
    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)
        # Stable sort: registrations first, every other app keeps Django's
        # default (alphabetical) order.
        app_list.sort(key=lambda app: app["app_label"] != "registrations")
        return app_list
```

- [ ] **Step 4: Wire it via AdminConfig**

In `apps/core/apps.py`, add (keep `CoreConfig`):

```python
from django.contrib.admin.apps import AdminConfig


class FkAdminConfig(AdminConfig):
    default_site = "apps.core.admin_site.FkAdminSite"
```

In `fk_cesis_mms/settings.py`, replace the `INSTALLED_APPS` entry `"django.contrib.admin",` with `"apps.core.apps.FkAdminConfig",`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_admin_app_ordering.py -v`
Then: `uv run pytest tests/ -q -k "admin"` (smoke: admin changelists/pages still resolve under the swapped site).
Expected: PASS, no admin regressions.

- [ ] **Step 6: Lint/type + commit**

```bash
uv run ruff check apps/core/admin_site.py apps/core/apps.py fk_cesis_mms/settings.py tests/core/test_admin_app_ordering.py
uv run mypy apps/core/admin_site.py apps/core/apps.py
git add apps/core/admin_site.py apps/core/apps.py fk_cesis_mms/settings.py tests/core/test_admin_app_ordering.py && git commit -m "feat(core): custom admin site puts Registrations app first (P7 C-ii)"
```

---

### Task 2: Agreement-status column on the applications changelist

**Files:**
- Modify: `apps/registrations/admin.py`
- Test: `tests/registrations/test_admin_agreement_status_column.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_admin_agreement_status_column.py
"""Applications changelist shows the agreement status."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Guardian, Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_shows_agreement_state_for_approved_app():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Līguma statuss" in html          # column header
    assert Agreement.State.SENT.label in html  # "Nosūtīts"


def test_changelist_dash_when_no_agreement():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Līguma statuss" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_admin_agreement_status_column.py -v`
Expected: FAIL — no "Līguma statuss" column yet.

- [ ] **Step 3: Add the column**

In `apps/registrations/admin.py`, add `"agreement_status"` to `list_display` (place it before `"quick_actions"`), and add the method (use `@admin.display`):

```python
    @admin.display(description="Līguma statuss")
    def agreement_status(self, obj):
        if obj.approved_member_id:
            agreement = get_current_agreement(obj.approved_member)
            if agreement is not None:
                return agreement.get_state_display()
        return "—"
```

(`get_current_agreement` is already imported in this file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_admin_agreement_status_column.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/registrations/ -q
uv run ruff check apps/registrations/admin.py tests/registrations/test_admin_agreement_status_column.py
uv run mypy apps/registrations/admin.py
git add apps/registrations/admin.py tests/registrations/test_admin_agreement_status_column.py && git commit -m "feat(registrations): agreement-status column on applications changelist (P7 C-ii)"
```

---

### Task 3: One-click billing-record confirm

**Files:**
- Modify: `apps/billing/admin.py` (`BillingRecordAdmin`)
- Create: `templates/admin/billing/billingrecord/change_form.html`
- Test: `tests/billing/test_admin_confirm_action.py`

**Context:** Mirror the registrations admin patterns: `get_urls()` for the endpoint, `change_form_template` for the top button, and a CSRF-tokened per-row POST in `list_display` (store the request in `get_queryset`). Confirm is one-click (no intermediate page); redirect honors a safe `next` (so list-confirm returns to the list).

- [ ] **Step 1: Write the failing tests**

```python
# tests/billing/test_admin_confirm_action.py
"""One-click confirm for billing records (change page + changelist)."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.billing.models import BillingRecord
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _draft_record(active_plan, guardian):
    m = Member.objects.create(full_name="B", guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT, status=BillingRecord.Status.DRAFT,
    )


def test_confirm_endpoint_flips_draft_to_confirmed(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    resp = c.post(url)
    assert resp.status_code == 302
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.CONFIRMED


def test_confirm_is_noop_when_already_confirmed(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save(update_fields=["status"])
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    c.post(url, follow=True)
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.CONFIRMED  # unchanged, no error


def test_confirm_is_staff_permission_gated(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = Client()  # anonymous
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    resp = c.post(url)
    assert resp.status_code in (302, 403)
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.DRAFT


def test_change_page_shows_confirm_button_for_draft(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_change", args=[rec.pk])).content.decode()
    confirm_url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    assert confirm_url in html
    assert "Apstiprināt" in html


def test_changelist_shows_one_click_confirm_for_draft(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    confirm_url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    assert f'action="{confirm_url}"' in html
    assert "csrfmiddlewaretoken" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_admin_confirm_action.py -v`
Expected: FAIL — `NoReverseMatch` (no confirm endpoint).

- [ ] **Step 3: Implement the endpoint + columns**

In `apps/billing/admin.py`, add imports at the top: `from django.shortcuts import get_object_or_404, redirect`, `from django.core.exceptions import PermissionDenied`, `from django.middleware.csrf import get_token`, `from django.urls import path, reverse`, `from django.utils.html import format_html`, `from django.utils.http import url_has_allowed_host_and_scheme`. Then in `BillingRecordAdmin`:

```python
    change_form_template = "admin/billing/billingrecord/change_form.html"

    def get_queryset(self, request):
        self._request = request  # confirm_action needs it for a per-row CSRF token
        return super().get_queryset(request)

    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/confirm/",
                self.admin_site.admin_view(self.confirm_view),
                name="billing_billingrecord_confirm",
            ),
        ]
        return custom + super().get_urls()

    def confirm_view(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        record = get_object_or_404(BillingRecord, pk=object_id)
        if request.method != "POST":
            return self._safe_redirect(request, object_id)
        if record.status == BillingRecord.Status.DRAFT:
            record.status = BillingRecord.Status.CONFIRMED
            record.save(update_fields=["status", "updated_at"])
            self.message_user(request, "Ieraksts apstiprināts.")
        else:
            self.message_user(request, "Ieraksts jau ir apstiprināts.", level=messages.INFO)
        return self._safe_redirect(request, object_id)

    def _safe_redirect(self, request, object_id):
        nxt = request.POST.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            return redirect(nxt)
        return redirect("admin:billing_billingrecord_change", object_id)

    @admin.display(description="Apstiprināt")
    def confirm_action(self, obj):
        if obj.status != BillingRecord.Status.DRAFT:
            return format_html('<span>✓ {}</span>', BillingRecord.Status.CONFIRMED.label)
        confirm_url = reverse("admin:billing_billingrecord_confirm", args=[obj.pk])
        changelist_url = reverse("admin:billing_billingrecord_changelist")
        return format_html(  # type: ignore[return-value,no-any-return]
            '<form method="post" action="{}" style="display:inline">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<input type="hidden" name="next" value="{}">'
            '<button type="submit" class="button">Apstiprināt</button>'
            "</form>",
            confirm_url, get_token(self._request), changelist_url,
        )
```

Add `"confirm_action"` to `list_display` (e.g. right after `"status"`). (`messages` is already imported in this file.)

Create `templates/admin/billing/billingrecord/change_form.html`:

```django
{% extends "admin/change_form.html" %}

{% block field_sets %}
  {% if original and original.status == "draft" %}
  <div class="module" style="margin-bottom:1rem">
    <form method="post" action="{% url 'admin:billing_billingrecord_confirm' original.pk %}">
      {% csrf_token %}
      <input type="hidden" name="next" value="{% url 'admin:billing_billingrecord_change' original.pk %}">
      <button type="submit" class="button default">Apstiprināt ierakstu</button>
    </form>
  </div>
  {% endif %}
  {{ block.super }}
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_admin_confirm_action.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/billing/ -q
uv run ruff check apps/billing/admin.py tests/billing/test_admin_confirm_action.py
uv run mypy apps/billing/admin.py
git add apps/billing/admin.py templates/admin/billing/billingrecord/change_form.html tests/billing/test_admin_confirm_action.py && git commit -m "feat(billing): one-click confirm — change-page button + changelist (P7 C-ii)"
```

---

### Task 4: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: pytest/ruff/mypy green; "No changes detected". Fail loud on any failure. (`ruff format` is not an enforced gate.)

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "P7 Slice C-ii batch 1 delivered — admin quick wins" entry (custom `FkAdminSite` puts Registrations first; agreement-status column on the applications changelist; one-click billing confirm endpoint + change-page button + per-row list button). Note the broader C-ii items remain.
- `docs/milestones.md`: mark batch 1 of the user-prioritised C-ii items delivered; the broader C-ii scope remains.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record P7 C-ii batch 1 admin quick wins"
```

---

## Self-Review Notes

- **Spec coverage:** §2 (menu order) → T1; §3 (agreement column) → T2; §4 (billing confirm: endpoint + change-page button + list button) → T3; §5 testing → each task; §6 acceptance → covered; docs → T4.
- **Refinement of the spec:** §3 named `agreement_status_copy`; the plan uses `agreement.get_state_display()` instead — the parent-facing copy is a full sentence, unsuitable for a table cell; the concise state label is the right admin-column rendering. Same "agreement status" intent, column-appropriate.
- **Reuse:** the billing per-row confirm mirrors the registrations `quick_actions` CSRF pattern (`get_token(self._request)` + request stored in `get_queryset`); `@admin.display` used for the new columns.
- **Safety:** confirm endpoint is `has_change_permission`-gated + CSRF (admin_view); the `next` redirect is validated with `url_has_allowed_host_and_scheme` (no open redirect).
- **No model changes / no migrations** — `makemigrations --check` must stay clean. Audit-on-confirm deferred (per spec).
- **Type/name consistency:** endpoint name `billing_billingrecord_confirm` used in the view, the change_form template, the list column, and all tests; `FkAdminSite`/`FkAdminConfig`/`default_site` consistent across T1.
- **Implementer caveats:** confirm the `_doc`-style `original.status == "draft"` template comparison matches the TextChoices value ("draft"); verify `messages` is imported in billing/admin.py (it is).
