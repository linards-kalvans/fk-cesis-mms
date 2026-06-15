# P7 C-ii batch 2 — Plan 1: Cross-links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Guardian ↔ Application ↔ Member ↔ Agreement ↔ Billing relationship web navigable in both directions from the Django admin — change-page "Saistītie ieraksti" link rows on every node plus two high-value clickable changelist columns.

**Architecture:** A shared `apps/core/admin_links.py` helper (`admin_link` for one FK target, `admin_links` for a to-many) mints `format_html` anchors to each object's admin change page (URL derived from `obj._meta`, with a `NoReverseMatch` fallback to plain text). Each ModelAdmin gains a `related_records` readonly display method (rendered as a row on the default change form); the registrations admin — which uses a custom C-i `change_form_template` — gets its links injected via `build_review_context`. Two changelist columns (application→member, billing→guardian/agreement) use the same helper.

**Tech Stack:** Django 5.x admin, pytest-django, `uv run`. No model changes / no migrations.

Spec: `docs/superpowers/specs/2026-06-15-p7-cii-batch2-admin-polish-design.md` (§2 shared foundation, §3 Plan 1).

---

## File Structure

- `apps/core/admin_links.py` — **new** `admin_link(obj, label=None)` + `admin_links(objs, *, limit=10, empty="—")`.
- `apps/registrations/admin.py` — add a `member_link` changelist column to `RegistrationApplicationAdmin`.
- `apps/registrations/admin_panels.py` — add `related_links` to `build_review_context`.
- `templates/admin/registrations/registrationapplication/change_form.html` — render the related-records block.
- `apps/members/admin.py` — `related_records` readonly method on `MemberAdmin` and `GuardianAdmin`.
- `apps/agreements/admin.py` — `related_records` readonly method on `AgreementAdmin`.
- `apps/billing/admin.py` — `related_records` readonly method on `BillingRecordAdmin` + `guardian_link`/`agreement_link` changelist columns (the existing plain `guardian_name` column is replaced by the clickable `guardian_link`).
- Tests (new): `tests/core/test_admin_links.py`, `tests/registrations/test_admin_cross_links.py`, `tests/members/test_admin_cross_links.py`, `tests/agreements/test_admin_cross_links.py`, `tests/billing/test_admin_cross_links.py`.

**Verified reverse relations:** `guardian.members`, `guardian.applications`, `parent_account.guardian` (OneToOne), `member.source_application` (OneToOne reverse of `RegistrationApplication.approved_member`), `member.agreements`, `member.billing_records`, `agreement.billing_records`, `agreement.member`, `application.approved_member`, `application.guardian`, `application.parent_account`, `billing_record.member`, `billing_record.agreement`, `member.guardian`.

**Verified admin facts:**
- `MemberAdmin` (apps/members/admin.py:25) and `GuardianAdmin` (:13) use the default change template (no `fields`/`readonly_fields` set → adding `readonly_fields`/`fields` is additive).
- `AgreementAdmin` (apps/agreements/admin.py:8) has `fields` unset but a large `readonly_fields`; `has_change_permission` returns `False` (view-only) — readonly display methods still render on the view page.
- `BillingRecordAdmin` (apps/billing/admin.py) has `readonly_fields` + `fields = readonly_fields + (...)`; `list_display` includes `guardian_name` and `confirm_action`.
- `RegistrationApplicationAdmin` (apps/registrations/admin.py:39) custom `change_form_template` + `change_view` injecting `build_review_context`; `list_display` is `("member_full_name", "guardian_contact_email", "status", "submitted_at", "agreement_status", "quick_actions")`.

---

### Task 1: Shared `admin_link` / `admin_links` helper

**Files:**
- Create: `apps/core/admin_links.py`
- Test: `tests/core/test_admin_links.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_admin_links.py
"""Reusable admin cross-link helpers."""

import pytest

from apps.core.admin_links import admin_link, admin_links
from apps.members.models import Guardian, Member

pytestmark = pytest.mark.django_db


def test_admin_link_renders_anchor_to_change_page():
    g = Guardian.objects.create(full_name="Vecāks V")
    html = str(admin_link(g))
    assert f"/members/guardian/{g.pk}/change/" in html
    assert "Vecāks V" in html
    assert html.startswith("<a ")


def test_admin_link_custom_label():
    g = Guardian.objects.create(full_name="Vecāks V")
    assert "Atvērt" in str(admin_link(g, label="Atvērt"))


def test_admin_link_none_returns_dash():
    assert admin_link(None) == "—"


def test_admin_links_lists_targets():
    g = Guardian.objects.create(full_name="V")
    m1 = Member.objects.create(full_name="Bērns A", guardian=g)
    m2 = Member.objects.create(full_name="Bērns B", guardian=g)
    html = str(admin_links([m1, m2]))
    assert f"/members/member/{m1.pk}/change/" in html
    assert f"/members/member/{m2.pk}/change/" in html


def test_admin_links_empty_returns_dash():
    assert admin_links([]) == "—"


def test_admin_links_overflow_marker():
    g = Guardian.objects.create(full_name="V")
    members = [Member.objects.create(full_name=f"B{i}", guardian=g) for i in range(4)]
    html = str(admin_links(members, limit=2))
    assert "+2" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_admin_links.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.core.admin_links`.

- [ ] **Step 3: Implement the helper**

`apps/core/admin_links.py`:

```python
"""Reusable Django-admin cross-link helpers.

``admin_link`` renders an anchor to any model instance's admin change page;
``admin_links`` renders a compact list for a to-many relation. Both fall back
to plain text when the target model is not registered in the admin.
"""

from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe


def admin_link(obj, label=None):
    """Anchor to ``obj``'s admin change page, or "—" when ``obj`` is None."""
    if obj is None:
        return "—"
    text = str(obj) if label is None else label
    try:
        url = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
            args=[obj.pk],
        )
    except NoReverseMatch:
        return text
    return format_html('<a href="{}">{}</a>', url, text)  # type: ignore[return-value,no-any-return]


def admin_links(objs, *, limit=10, empty="—"):
    """Comma/`<br>`-joined anchors for an iterable of instances.

    Caps the list at ``limit`` and appends a "+N" overflow marker. Returns
    ``empty`` for an empty iterable. Each part is escaped by ``admin_link``.
    """
    items = list(objs)
    if not items:
        return empty
    parts = [str(admin_link(o)) for o in items[:limit]]
    extra = len(items) - limit
    if extra > 0:
        parts.append(f"+{extra}")
    return mark_safe("<br>".join(parts))  # noqa: S308 — parts are admin_link-escaped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_admin_links.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/core/admin_links.py tests/core/test_admin_links.py && \
uv run mypy apps/core/admin_links.py && \
git add apps/core/admin_links.py tests/core/test_admin_links.py && \
git commit -m "feat(core): reusable admin cross-link helpers (P7 C-ii b2)"
```

---

### Task 2: RegistrationApplication — member changelist column + related-records block

**Files:**
- Modify: `apps/registrations/admin.py`, `apps/registrations/admin_panels.py`, `templates/admin/registrations/registrationapplication/change_form.html`
- Test: `tests/registrations/test_admin_cross_links.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/registrations/test_admin_cross_links.py
"""Cross-links on the registrations admin (changelist column + change page block)."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import Guardian, Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_links_to_approved_member():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert f"/members/member/{m.pk}/change/" in html


def test_changelist_member_column_dash_when_unapproved():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    resp = c.get(reverse("admin:registrations_registrationapplication_changelist"))
    assert resp.status_code == 200  # renders without error, no member link


def test_change_page_shows_related_records_block():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_change", args=[app.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html      # member link
    assert f"/members/guardian/{g.pk}/change/" in html    # guardian link
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_admin_cross_links.py -v`
Expected: FAIL — no member link in changelist / no "Saistītie ieraksti" block.

- [ ] **Step 3a: Add the changelist column**

In `apps/registrations/admin.py`, add the import near the top (with the other `apps.*` imports):

```python
from apps.core.admin_links import admin_link
```

Add `"member_link"` to `list_display` immediately before `"agreement_status"`, and add the method (place it next to the existing `agreement_status` method):

```python
    @admin.display(description="Biedrs")
    def member_link(self, obj):
        return admin_link(obj.approved_member)
```

- [ ] **Step 3b: Build the related-records links in the review context**

In `apps/registrations/admin_panels.py`, add at the top of the file (with the other imports):

```python
from apps.core.admin_links import admin_link, admin_links
```

In `build_review_context`, just before the `return {`, compute the links (the function already has `agreement` and `application.approved_member_id` in scope):

```python
    member = application.approved_member if application.approved_member_id else None
    billing_records = list(member.billing_records.all()) if member is not None else []
    related_links = {
        "Biedrs": admin_link(member),
        "Vecāks": admin_link(application.guardian),
        "Vecāka konts": admin_link(application.parent_account),
        "Līgums": admin_link(agreement),
        "Rēķini": admin_links(billing_records),
    }
```

Add `"related_links": related_links,` to the returned dict.

- [ ] **Step 3c: Render the block in the template**

In `templates/admin/registrations/registrationapplication/change_form.html`, inside `{% block mms_action_bar %}` and within the `{% if original %}` guard (right after the `{% endif %}` that closes the `status == "submitted"` action module, before the `{% if original.approved_member_id %}` line), add:

```django
        <div class="module mms-related-records">
          <h2>Saistītie ieraksti</h2>
          <ul>
            {% for label, link in related_links.items %}
              <li><strong>{{ label }}:</strong> {{ link }}</li>
            {% endfor %}
          </ul>
        </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_admin_cross_links.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/registrations/ -q && \
uv run ruff check apps/registrations/admin.py apps/registrations/admin_panels.py tests/registrations/test_admin_cross_links.py && \
uv run mypy apps/registrations/admin.py apps/registrations/admin_panels.py && \
git add apps/registrations/admin.py apps/registrations/admin_panels.py templates/admin/registrations/registrationapplication/change_form.html tests/registrations/test_admin_cross_links.py && \
git commit -m "feat(registrations): member changelist link + related-records block (P7 C-ii b2)"
```

---

### Task 3: Member change-page related-records row

**Files:**
- Modify: `apps/members/admin.py`
- Test: `tests/members/test_admin_cross_links.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/members/test_admin_cross_links.py
"""Related-records cross-links on the members admin."""

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


def test_member_change_page_links_to_guardian_application_agreement():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:members_member_change", args=[m.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/guardian/{g.pk}/change/" in html
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html
    assert f"/agreements/agreement/" in html


def test_guardian_change_page_links_to_members_and_applications():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns", guardian=g,
    )
    c = _staff_client()
    html = c.get(reverse("admin:members_guardian_change", args=[g.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/members/test_admin_cross_links.py -v`
Expected: FAIL — no "Saistītie ieraksti" row on either page.

- [ ] **Step 3: Add the readonly link methods**

In `apps/members/admin.py`, add the import:

```python
from apps.agreements.services import get_current_agreement
from apps.core.admin_links import admin_link, admin_links
```

On `MemberAdmin`, add `readonly_fields` + `fields` so the method renders (MemberAdmin currently sets neither). Add a `related_records` method:

```python
    readonly_fields = ("related_records",)

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        source_application = getattr(obj, "source_application", None)
        agreement = get_current_agreement(obj) if obj.pk else None
        billing_records = list(obj.billing_records.all()) if obj.pk else []
        return format_html(
            "<strong>Vecāks:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Līgums:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_link(obj.guardian),
            admin_link(source_application),
            admin_link(agreement),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]
```

Add `from django.utils.html import format_html` to the imports if not already present (it is not in members/admin.py — add it).

On `GuardianAdmin`, add:

```python
    readonly_fields = ("related_records",)

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        members = list(obj.members.all()) if obj.pk else []
        applications = list(obj.applications.all()) if obj.pk else []
        billing_records = [br for m in members for br in m.billing_records.all()]
        return format_html(
            "<strong>Biedri:</strong> {}<br>"
            "<strong>Pieteikumi:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_links(members),
            admin_links(applications),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]
```

(`KitSizeOption` reverse relations `shirt_applications`/`shorts_applications` are unrelated; do not touch `KitSizeOptionAdmin`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/members/test_admin_cross_links.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/members/ -q && \
uv run ruff check apps/members/admin.py tests/members/test_admin_cross_links.py && \
uv run mypy apps/members/admin.py && \
git add apps/members/admin.py tests/members/test_admin_cross_links.py && \
git commit -m "feat(members): related-records rows on Member + Guardian admin (P7 C-ii b2)"
```

---

### Task 4: Agreement change-page related-records row

**Files:**
- Modify: `apps/agreements/admin.py`
- Test: `tests/agreements/test_admin_cross_links.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agreements/test_admin_cross_links.py
"""Related-records cross-links on the agreements admin."""

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


def test_agreement_change_page_links_to_member_and_application():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:agreements_agreement_change", args=[agreement.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_admin_cross_links.py -v`
Expected: FAIL — no "Saistītie ieraksti" row.

- [ ] **Step 3: Add the readonly link method**

In `apps/agreements/admin.py`, add imports:

```python
from django.utils.html import format_html

from apps.core.admin_links import admin_link, admin_links
```

Add `"related_records"` to the **front** of `readonly_fields` and add the method to `AgreementAdmin`:

```python
    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        member = obj.member
        source_application = getattr(member, "source_application", None)
        billing_records = list(obj.billing_records.all()) if obj.pk else []
        return format_html(
            "<strong>Biedrs:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_link(member),
            admin_link(source_application),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]
```

(`AgreementAdmin.has_change_permission` is `False` → the change page renders read-only, and readonly display methods still show. Do not add `fields`; Django renders all `readonly_fields`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_admin_cross_links.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/agreements/ -q && \
uv run ruff check apps/agreements/admin.py tests/agreements/test_admin_cross_links.py && \
uv run mypy apps/agreements/admin.py && \
git add apps/agreements/admin.py tests/agreements/test_admin_cross_links.py && \
git commit -m "feat(agreements): related-records row on Agreement admin (P7 C-ii b2)"
```

---

### Task 5: BillingRecord — clickable guardian/agreement columns + related-records row

**Files:**
- Modify: `apps/billing/admin.py`
- Test: `tests/billing/test_admin_cross_links.py`

**Context:** `BillingRecordAdmin` already has a plain-text `guardian_name` column (method at apps/billing/admin.py ~line 100) and `member`/`agreement` in `readonly_fields`. Replace `guardian_name` in `list_display` with a clickable `guardian_link`, add an `agreement_link` column, and add a `related_records` readonly row. Keep the `guardian_name` method only if other code references it — it does not, so rename it to `guardian_link` returning a link.

- [ ] **Step 1: Write the failing test**

```python
# tests/billing/test_admin_cross_links.py
"""Cross-links on the billing admin (changelist columns + change page row)."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _record(active_plan, guardian, agreement=None):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, agreement=agreement,
    )


def test_changelist_links_to_guardian_and_agreement(active_plan, guardian):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    rec = BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, agreement=agreement,
    )
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert f"/members/guardian/{guardian.pk}/change/" in html
    assert f"/agreements/agreement/{agreement.pk}/change/" in html


def test_change_page_shows_related_records_row(active_plan, guardian):
    rec = _record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_change", args=[rec.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{rec.member.pk}/change/" in html
    assert f"/members/guardian/{guardian.pk}/change/" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_admin_cross_links.py -v`
Expected: FAIL — no guardian/agreement links in the changelist; no related-records row.

- [ ] **Step 3: Implement the columns + row**

In `apps/billing/admin.py`, add the import (with the existing `from apps.core...` imports):

```python
from apps.core.admin_links import admin_link
```

Replace the `guardian_name` method (the `@admin.display(description="Vecāks") def guardian_name`) with a clickable version and add `agreement_link` + `related_records`:

```python
    @admin.display(description="Vecāks")
    def guardian_link(self, obj):
        return admin_link(obj.member.guardian)

    @admin.display(description="Līgums")
    def agreement_link(self, obj):
        return admin_link(obj.agreement)

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        source_application = getattr(obj.member, "source_application", None)
        return format_html(
            "<strong>Biedrs:</strong> {}<br>"
            "<strong>Vecāks:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Līgums:</strong> {}",
            admin_link(obj.member),
            admin_link(obj.member.guardian),
            admin_link(source_application),
            admin_link(obj.agreement),
        )  # type: ignore[return-value,no-any-return]
```

In `list_display`, replace `"guardian_name"` with `"guardian_link"` and add `"agreement_link"` right after it. Add `"related_records"` to the **front** of `readonly_fields` (so it appears at the top of the change form). `format_html` is already imported in this file (from the batch-1 confirm work).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_admin_cross_links.py -v`
Expected: PASS.

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/billing/ -q && \
uv run ruff check apps/billing/admin.py tests/billing/test_admin_cross_links.py && \
uv run mypy apps/billing/admin.py && \
git add apps/billing/admin.py tests/billing/test_admin_cross_links.py && \
git commit -m "feat(billing): clickable guardian/agreement columns + related-records row (P7 C-ii b2)"
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

- `AGENTS.md`: add a "P7 Slice C-ii batch 2 — Plan 1 (cross-links) delivered" entry: shared `apps/core/admin_links.py` (`admin_link`/`admin_links`); related-records rows on Member/Guardian/Agreement/BillingRecord change pages + the registrations review block; member changelist column on applications; clickable guardian/agreement columns on billing. Note Plans 2 (visibility) + 3 (group dedup) remain.
- `docs/milestones.md`: mark batch-2 Plan 1 (cross-links) delivered under the C-ii line.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record P7 C-ii batch 2 Plan 1 cross-links"
```

---

## Self-Review Notes

- **Spec coverage:** §2 `admin_link` helper → T1; §3.1 change-page blocks (Application/Member/Agreement/Billing/Guardian) → T2/T3/T4/T5; §3.2 changelist columns (application→member, billing→guardian/agreement) → T2/T5; §6 testing → each task; docs → T6.
- **`admin_links` (to-many) helper** is also covered in T1 and used for Guardian→members/applications/billing and Member/Agreement→billing.
- **No model changes / no migrations** — `makemigrations --check` must stay clean.
- **Deviation note:** the spec lists "ParentAccount" as a link target from the application; `admin_link` derives the URL from `obj._meta` and falls back to plain text if ParentAccount is not admin-registered, so this is safe either way.
- **Type consistency:** the helper name `admin_link`/`admin_links` and the per-admin method name `related_records` (description "Saistītie ieraksti") are used identically across T2–T5. `member_link`/`guardian_link`/`agreement_link` are the changelist column method names.
- **Implementer caveat:** `guardian_name` → `guardian_link` rename — grep for `guardian_name` references first; the only use is its own `list_display` entry, replaced in this task.
