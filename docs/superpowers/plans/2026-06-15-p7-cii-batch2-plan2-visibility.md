# P7 C-ii batch 2 — Plan 2: Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make admin records easy to scan and triage: color sync-health badges + a sync-health filter on billing/agreements, search/filter/date-drill polish across the under-equipped admins, and a clear active-vs-replaced distinction in the document list.

**Architecture:** A shared `apps/core/admin_badges.py::status_badge(text, level)` renders a CSS-classed `<span>` (styled by `static/admin/fk_badges.css`, attached via each admin's inner `Media`). Existing `apps.billing.messages.get_invoice_error_message` / `apps.agreements.messages.get_agreement_error_message` supply Latvian tooltips. Sync-health and active-vs-replaced filters are `admin.SimpleListFilter` subclasses translating UI choices to queryset filters. Search/filter polish is plain ModelAdmin attribute additions.

**Tech Stack:** Django 5.x admin, pytest-django, `uv run`. No model changes / no migrations.

Spec: `docs/superpowers/specs/2026-06-15-p7-cii-batch2-admin-polish-design.md` (§2 shared foundation, §4 Plan 2).

---

## File Structure

- `apps/core/admin_badges.py` — **new** `status_badge(text, level)`.
- `static/admin/fk_badges.css` — **new** badge CSS (`.fk-badge`, `.fk-badge--ok|--fail|--pending|--muted`).
- `apps/billing/admin.py` — sync-health badge columns + `SyncHealthFilter` + search/filter/date polish on `BillingRecordAdmin` and `MembershipPlanAdmin`.
- `apps/agreements/admin.py` — sync-health badge column + `AgreementSyncHealthFilter` + date polish on `AgreementAdmin`.
- `apps/documents/admin.py` — search/filter/date polish + active-vs-replaced badge + `DocumentStateFilter` on `DocumentAdmin`.
- `apps/members/admin.py` — `search_fields` on `TrainingGroupAdmin`.
- `apps/registrations/admin.py` — date_hierarchy/ordering + `preferred_agreement_signing` filter on `RegistrationApplicationAdmin`.
- Tests (new): `tests/core/test_admin_badges.py`, `tests/billing/test_admin_sync_health.py`, `tests/agreements/test_admin_sync_health.py`, `tests/registrations/test_admin_search_filter.py` (+ assertions added to billing/agreements/documents/members search-filter behaviour in their sync-health/active-replaced test files).

**Verified facts:**
- `BillingRecord`: `external_status` (str, e.g. `"synced"`), `external_error_code` (str), `payment_status` (choices `unpaid|partial|paid`), `payment_error_code` (str), `payment_synced_at` (datetime), `created_at` (TimeStampedModel). `BillingRecordAdmin.list_display` currently includes `external_status`, `payment_status`, `payment_synced_at`; `list_filter` includes `season, status, payment_mode, is_full_price, external_status, payment_status`.
- `Agreement`: uses `external_state` (NOT `external_status`), `external_error_code`; `generated_at` (datetime, NOT NULL). `AgreementAdmin` is view-only (`has_change_permission=False`), `list_display = ("member", "state", "signing_path", "is_current", "updated_at")`.
- `apps.billing.messages.get_invoice_error_message(code) -> str` and `apps.agreements.messages.get_agreement_error_message(code) -> str` return Latvian copy (generic fallback).
- `Document`: `deleted_at` (null=active), `is_active` property, `kind`, `ocr_status`, `uploaded_by_parent_at`. `DocumentAdmin` has NO `search_fields`/`list_filter`/`date_hierarchy`/`ordering`. `DocumentAdmin.fields = readonly_fields`.
- `MembershipPlanAdmin` has `list_filter=("season","is_active")`, no `search_fields`. `TrainingGroupAdmin` has `list_filter=("is_active",)`, no `search_fields`.

> **Sequencing note:** If Plan 1 already added cross-link columns/rows to billing/agreements, keep them — this plan only adds the sync-health/search/filter attributes alongside. If `search_fields`/`readonly_fields` already exist, extend the tuple rather than replacing it.

---

### Task 1: Shared `status_badge` helper + CSS

**Files:**
- Create: `apps/core/admin_badges.py`, `static/admin/fk_badges.css`
- Test: `tests/core/test_admin_badges.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_admin_badges.py
"""Reusable admin status-badge helper."""

from apps.core.admin_badges import status_badge


def test_badge_renders_span_with_level_class():
    html = str(status_badge("OK", "ok"))
    assert "fk-badge" in html
    assert "fk-badge--ok" in html
    assert "OK" in html
    assert html.startswith("<span")


def test_badge_tooltip_when_provided():
    html = str(status_badge("Neizdevās", "fail", tooltip="Kļūda X"))
    assert 'title="Kļūda X"' in html


def test_badge_no_tooltip_attr_when_absent():
    html = str(status_badge("OK", "ok"))
    assert "title=" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_admin_badges.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.core.admin_badges`.

- [ ] **Step 3: Implement the helper + CSS**

`apps/core/admin_badges.py`:

```python
"""Reusable Django-admin status badge.

``status_badge`` renders a CSS-classed span; pair it with the
``static/admin/fk_badges.css`` stylesheet via a ModelAdmin ``Media`` class.
"""

from django.utils.html import format_html

_LEVELS = {"ok", "fail", "pending", "muted"}


def status_badge(text, level, *, tooltip=""):
    """Coloured badge span. ``level`` is one of ok|fail|pending|muted."""
    css_level = level if level in _LEVELS else "muted"
    if tooltip:
        return format_html(
            '<span class="fk-badge fk-badge--{}" title="{}">{}</span>',
            css_level, tooltip, text,
        )  # type: ignore[return-value,no-any-return]
    return format_html(
        '<span class="fk-badge fk-badge--{}">{}</span>', css_level, text
    )  # type: ignore[return-value,no-any-return]
```

`static/admin/fk_badges.css`:

```css
.fk-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 0.85em;
  font-weight: 600;
  white-space: nowrap;
}
.fk-badge--ok { background: #def7e4; color: #1a7f37; }
.fk-badge--fail { background: #fce8e6; color: #b3261e; }
.fk-badge--pending { background: #fef3c7; color: #92660e; }
.fk-badge--muted { background: #eceff1; color: #607d8b; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_admin_badges.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/core/admin_badges.py tests/core/test_admin_badges.py && \
uv run mypy apps/core/admin_badges.py && \
git add apps/core/admin_badges.py static/admin/fk_badges.css tests/core/test_admin_badges.py && \
git commit -m "feat(core): reusable admin status-badge helper + CSS (P7 C-ii b2)"
```

---

### Task 2: Billing sync-health badges + filter + search/filter polish

**Files:**
- Modify: `apps/billing/admin.py`
- Test: `tests/billing/test_admin_sync_health.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/billing/test_admin_sync_health.py
"""Sync-health badges + filter on the billing admin."""

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


def _record(active_plan, guardian, **kw):
    m = Member.objects.create(full_name=kw.pop("name", "Bērns"), guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, **kw,
    )


def test_failed_sync_shows_fail_badge_with_tooltip(active_plan, guardian):
    _record(active_plan, guardian, external_status="error", external_error_code="provider_unavailable")
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "fk-badge--fail" in html
    assert "title=" in html  # Latvian error copy tooltip


def test_synced_record_shows_ok_badge(active_plan, guardian):
    _record(active_plan, guardian, external_status="synced", name="Sinhr")
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "fk-badge--ok" in html


def test_sync_health_filter_isolates_failed(active_plan, guardian):
    _record(active_plan, guardian, external_status="error", external_error_code="provider_unavailable", name="Fail")
    _record(active_plan, guardian, external_status="synced", name="OK")
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist") + "?sync_health=failed"
    html = c.get(url).content.decode()
    assert "Fail" in html
    assert "OK" not in html.split("</thead>")[-1]  # OK row not in tbody


def test_changelist_filter_links_present(active_plan, guardian):
    _record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "sync_health" in html  # custom filter rendered in sidebar
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_admin_sync_health.py -v`
Expected: FAIL — no badge classes / no `sync_health` filter.

- [ ] **Step 3: Implement badges + filter + polish**

In `apps/billing/admin.py` add imports:

```python
from apps.billing.messages import get_invoice_error_message
from apps.core.admin_badges import status_badge
```

Add the filter class above `BillingRecordAdmin`:

```python
class SyncHealthFilter(admin.SimpleListFilter):
    title = "Sinhronizācijas stāvoklis"
    parameter_name = "sync_health"

    def lookups(self, request, model_admin):
        return [
            ("ok", "OK"),
            ("failed", "Neizdevās"),
            ("pending", "Procesā"),
            ("none", "Nav sinhronizēts"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "ok":
            return queryset.filter(external_status="synced").exclude(
                external_error_code__gt=""
            )
        if value == "failed":
            return queryset.exclude(external_error_code="")
        if value == "pending":
            return queryset.exclude(external_status="").exclude(
                external_status="synced"
            ).filter(external_error_code="")
        if value == "none":
            return queryset.filter(external_status="")
        return queryset
```

On `BillingRecordAdmin`:
- Add an inner `Media` (or extend it if Plan 1/batch-1 added one): `class Media: css = {"all": ["admin/fk_badges.css"]}`.
- Add badge methods:

```python
    @admin.display(description="IN statuss")
    def external_status_badge(self, obj):
        if obj.external_error_code:
            return status_badge(
                "Neizdevās", "fail",
                tooltip=get_invoice_error_message(obj.external_error_code),
            )
        if obj.external_status == "synced":
            return status_badge("Sinhronizēts", "ok")
        if obj.external_status:
            return status_badge(obj.external_status, "pending")
        return status_badge("—", "muted")

    @admin.display(description="Maksājums")
    def payment_status_badge(self, obj):
        if obj.payment_error_code:
            return status_badge(
                "Kļūda", "fail",
                tooltip=get_invoice_error_message(obj.payment_error_code),
            )
        if obj.payment_status == "paid":
            return status_badge(obj.get_payment_status_display(), "ok")
        if obj.payment_status == "partial":
            return status_badge(obj.get_payment_status_display(), "pending")
        if obj.payment_status:
            return status_badge(obj.get_payment_status_display(), "muted")
        return status_badge("—", "muted")
```

- In `list_display`, replace `"external_status"` with `"external_status_badge"` and `"payment_status"` with `"payment_status_badge"`.
- In `list_filter`, replace the raw `"external_status"` entry with `SyncHealthFilter`; keep `payment_status`; add `"plan"`.
- Add `date_hierarchy = "created_at"` and `ordering = ("-created_at",)`.

On `MembershipPlanAdmin`: add `search_fields = ("name", "season")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_admin_sync_health.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/billing/ -q && \
uv run ruff check apps/billing/admin.py tests/billing/test_admin_sync_health.py && \
uv run mypy apps/billing/admin.py && \
git add apps/billing/admin.py tests/billing/test_admin_sync_health.py && \
git commit -m "feat(billing): sync-health badges + filter + search/date polish (P7 C-ii b2)"
```

---

### Task 3: Agreement sync-health badge + filter + date polish

**Files:**
- Modify: `apps/agreements/admin.py`
- Test: `tests/agreements/test_admin_sync_health.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agreements/test_admin_sync_health.py
"""Sync-health badge + filter on the agreements admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Guardian, Member

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _agreement(**kw):
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name=kw.pop("name", "Bērns"), guardian=g)
    return Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT,
        generated_at=timezone.now(), **kw,
    )


def test_failed_agreement_shows_fail_badge(active_plan=None):
    pass  # placeholder removed below


def test_failed_sync_shows_fail_badge():
    _agreement(external_state="failed", external_error_code="provider_error", name="Fail")
    c = _staff_client()
    html = c.get(reverse("admin:agreements_agreement_changelist")).content.decode()
    assert "fk-badge--fail" in html
    assert "title=" in html


def test_sync_health_filter_isolates_failed():
    _agreement(external_state="failed", external_error_code="provider_error", name="Fail")
    _agreement(name="Clean")
    c = _staff_client()
    url = reverse("admin:agreements_agreement_changelist") + "?sync_health=failed"
    html = c.get(url).content.decode()
    assert "Fail" in html
    assert "Clean" not in html.split("</thead>")[-1]
```

(Delete the `test_failed_agreement_shows_fail_badge` placeholder — it is shown only to flag that the real tests are the two below it.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agreements/test_admin_sync_health.py -v`
Expected: FAIL — no badge / no filter.

- [ ] **Step 3: Implement badge + filter**

In `apps/agreements/admin.py` add imports:

```python
from apps.agreements.messages import get_agreement_error_message
from apps.core.admin_badges import status_badge
```

Add the filter class above `AgreementAdmin`:

```python
class AgreementSyncHealthFilter(admin.SimpleListFilter):
    title = "Sinhronizācijas stāvoklis"
    parameter_name = "sync_health"

    def lookups(self, request, model_admin):
        return [("failed", "Neizdevās"), ("ok", "OK"), ("none", "Nav sinhronizēts")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "failed":
            return queryset.exclude(external_error_code="")
        if value == "ok":
            return queryset.exclude(external_state="").filter(external_error_code="")
        if value == "none":
            return queryset.filter(external_state="")
        return queryset
```

On `AgreementAdmin`:
- Add `class Media: css = {"all": ["admin/fk_badges.css"]}`.
- Add the badge method:

```python
    @admin.display(description="Sinhronizācija")
    def sync_health_badge(self, obj):
        if obj.external_error_code:
            return status_badge(
                "Neizdevās", "fail",
                tooltip=get_agreement_error_message(obj.external_error_code),
            )
        if obj.external_state:
            return status_badge(obj.external_state, "ok")
        return status_badge("—", "muted")
```

- Add `"sync_health_badge"` to `list_display` (after `"state"`).
- Add `AgreementSyncHealthFilter` to `list_filter`.
- Add `date_hierarchy = "generated_at"` and `ordering = ("-generated_at",)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agreements/test_admin_sync_health.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/agreements/ -q && \
uv run ruff check apps/agreements/admin.py tests/agreements/test_admin_sync_health.py && \
uv run mypy apps/agreements/admin.py && \
git add apps/agreements/admin.py tests/agreements/test_admin_sync_health.py && \
git commit -m "feat(agreements): sync-health badge + filter + date polish (P7 C-ii b2)"
```

---

### Task 4: Document active-vs-replaced + search/filter polish

**Files:**
- Modify: `apps/documents/admin.py`
- Test: `tests/documents/test_admin_active_replaced.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_admin_active_replaced.py
"""Active-vs-replaced badge + search/filter on the documents admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _doc(app, **kw):
    return Document.objects.create(
        application=app, kind=Document.Kind.MEMBER_IDENTITY, **kw
    )


def test_active_doc_shows_active_badge():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    _doc(app)
    c = _staff_client()
    html = c.get(reverse("admin:documents_document_changelist")).content.decode()
    assert "fk-badge--ok" in html
    assert "Aktīvs" in html


def test_replaced_doc_shows_muted_badge():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    _doc(app, deleted_at=timezone.now())
    c = _staff_client()
    html = c.get(reverse("admin:documents_document_changelist")).content.decode()
    assert "fk-badge--muted" in html
    assert "Vēsturisks" in html


def test_state_filter_isolates_replaced():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    active = _doc(app)
    replaced = _doc(app, deleted_at=timezone.now())
    c = _staff_client()
    url = reverse("admin:documents_document_changelist") + "?state=replaced"
    html = c.get(url).content.decode()
    body = html.split("</thead>")[-1]
    assert f"/documents/document/{replaced.pk}/change/" in html
    # the active doc's id should not appear as a row link in tbody
    assert str(active.pk) not in body or f">{active.pk}<" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_admin_active_replaced.py -v`
Expected: FAIL — no badge / no `state` filter.

- [ ] **Step 3: Implement badge + filter + polish**

In `apps/documents/admin.py` add the import:

```python
from apps.core.admin_badges import status_badge
```

Add the filter class above `DocumentAdmin`:

```python
class DocumentStateFilter(admin.SimpleListFilter):
    title = "Stāvoklis"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("active", "Aktīvs"), ("replaced", "Vēsturisks (aizstāts)")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "active":
            return queryset.filter(deleted_at__isnull=True)
        if value == "replaced":
            return queryset.filter(deleted_at__isnull=False)
        return queryset
```

On `DocumentAdmin`:
- Add `class Media: css = {"all": ["admin/fk_badges.css"]}`.
- Add the badge method:

```python
    @admin.display(description="Stāvoklis")
    def state_badge(self, obj):
        if obj.is_active:
            return status_badge("Aktīvs", "ok")
        return status_badge("Vēsturisks", "muted")
```

- Add `"state_badge"` to `list_display` (after `"kind"`).
- Add `search_fields = ("application__member_full_name", "kind")`.
- Add `list_filter = ("kind", "ocr_status", DocumentStateFilter)`.
- Add `date_hierarchy = "uploaded_by_parent_at"` and `ordering = ("-uploaded_by_parent_at",)`.

(`state_badge` is display-only — do NOT add it to `fields`/`readonly_fields`, which are wired as the change-form field list.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_admin_active_replaced.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/documents/ -q && \
uv run ruff check apps/documents/admin.py tests/documents/test_admin_active_replaced.py && \
uv run mypy apps/documents/admin.py && \
git add apps/documents/admin.py tests/documents/test_admin_active_replaced.py && \
git commit -m "feat(documents): active-vs-replaced badge + search/filter polish (P7 C-ii b2)"
```

---

### Task 5: Remaining search/filter polish (registrations + training group)

**Files:**
- Modify: `apps/registrations/admin.py`, `apps/members/admin.py`
- Test: `tests/registrations/test_admin_search_filter.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/registrations/test_admin_search_filter.py
"""Search/filter polish on registrations + training-group admins."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import TrainingGroup
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_applications_have_signing_path_filter_and_date_drill():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "preferred_agreement_signing" in html  # filter param in sidebar links
    # date_hierarchy renders without error
    assert c.get(
        reverse("admin:registrations_registrationapplication_changelist") + "?submitted_at__year=2026"
    ).status_code == 200


def test_training_group_is_searchable():
    TrainingGroup.objects.create(name="U10 A")
    TrainingGroup.objects.create(name="U12 B")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist") + "?q=U10"
    html = c.get(url).content.decode()
    body = html.split("</thead>")[-1]
    assert "U10 A" in body
    assert "U12 B" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_admin_search_filter.py -v`
Expected: FAIL — no signing-path filter; TrainingGroup not searchable (`?q=` ignored → both rows shown).

- [ ] **Step 3: Implement the polish**

In `apps/registrations/admin.py`, on `RegistrationApplicationAdmin`:
- Change `list_filter = ("status",)` → `list_filter = ("status", "preferred_agreement_signing")`.
- Add `date_hierarchy = "submitted_at"` and `ordering = ("-submitted_at",)`.

(Verify `preferred_agreement_signing` is a field on `RegistrationApplication` — it is, per the agreement signing-path sync. If the field name differs, use the actual field; do not invent one.)

In `apps/members/admin.py`, on `TrainingGroupAdmin`: add `search_fields = ("name",)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_admin_search_filter.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/registrations/ tests/members/ -q && \
uv run ruff check apps/registrations/admin.py apps/members/admin.py tests/registrations/test_admin_search_filter.py && \
uv run mypy apps/registrations/admin.py apps/members/admin.py && \
git add apps/registrations/admin.py apps/members/admin.py tests/registrations/test_admin_search_filter.py && \
git commit -m "feat(admin): search/filter/date polish on applications + training groups (P7 C-ii b2)"
```

---

### Task 6: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: pytest/ruff/mypy green; "No changes detected". Fail loud on any failure.

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add "P7 C-ii batch 2 — Plan 2 (visibility) delivered": shared `status_badge` + `fk_badges.css`; sync-health badges + `SyncHealthFilter` on billing, sync-health badge + filter on agreements (Latvian error tooltips via the existing message helpers); DocumentAdmin active-vs-replaced badge + `state` filter + search/filter/date-drill; search on TrainingGroup/MembershipPlan; date drill + ordering + signing-path filter on applications. Note Plan 3 (group dedup) remains.
- `docs/milestones.md`: mark batch-2 Plan 2 (visibility) delivered under the C-ii line.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record P7 C-ii batch 2 Plan 2 visibility"
```

---

## Self-Review Notes

- **Spec coverage:** §2 `status_badge` → T1; §4.1 sync-health (billing + agreement) → T2/T3; §4.2 search/filter polish (Document, TrainingGroup, MembershipPlan, RegistrationApplication, Agreement, BillingRecord) → T2 (billing+plan), T3 (agreement date), T4 (document), T5 (registrations+training group); §4.3 document active-vs-replaced → T4; §6 testing → each task; docs → T6.
- **Agreement uses `external_state`, not `external_status`** — reflected in T3's filter + badge.
- **`get_payment_status_display()`** relies on `payment_status` being a `choices` field — verified (PaymentStatus choices). If a value has no label, Django returns the raw value (safe).
- **Filter param name `sync_health`** is intentionally identical on both billing and agreement admins (different admins → no collision); both filter classes are named distinctly (`SyncHealthFilter` / `AgreementSyncHealthFilter`).
- **No model changes / no migrations** — `makemigrations --check` must stay clean.
- **Implementer caveats:** (1) the agreements test file contains a `test_failed_agreement_shows_fail_badge` placeholder that must be deleted (noted in T3 Step 1). (2) When adding `Media`/`list_filter`/`readonly_fields`, EXTEND any tuple Plan 1 or batch 1 already added rather than overwriting. (3) `state_badge`/sync badges are `list_display`-only; never add them to `fields`.
