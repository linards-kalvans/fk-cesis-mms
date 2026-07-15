# P12 Parent Invoice Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show issued membership invoices on the existing parent `/portal/`, with owned-only visibility and a safe Django proxy redirect to stored Invoice Ninja URLs.

**Architecture:** Reuse the existing billing domain. Add one stored URL field to `BillingInvoice`, extend payment sync to populate it, build read-only portal presentation data from the verified parent's Guardian ownership chain, and add a small proxy redirect route that performs the same ownership and issued-state checks before redirecting.

**Tech Stack:** Django 5, PostgreSQL/SQLite tests, pytest + pytest-django, uv, existing Invoice Ninja adapter, server-rendered templates.

---

## 1. Design decisions

1. **Use `/portal/`, not a new invoice area.**
   - Why: P12 scope is visibility, not a new billing portal. Existing parent portal already resolves `ParentAccount` and renders family context.

2. **Use `BillingInvoice` as row source.**
   - Why: It already represents one parent-payable invoice/installment and stores due date, amount, external state, payment state, and sync time.

3. **Add `BillingInvoice.external_url`.**
   - Why: Current code stores external ids but no safe parent-facing URL. Guessing URL shapes from Invoice Ninja base URL is unsafe.

4. **Fill `external_url` only from payment sync/fetch.**
   - Why: User chose sync-confirmed URL. It avoids showing unverified push-time URLs and matches P12's “safe URL only” rule.

5. **Show only issued invoices.**
   - Why: Future draft installments are created ahead of time; showing them before scheduled send would confuse parents.

6. **Use Django proxy redirect for invoice opens.**
   - Why: Django can enforce session and Guardian ownership before any external URL is exposed or followed.

7. **Return `404` for owned-resource denials.**
   - Why: Existing private-resource posture avoids leaking cross-family invoice existence.

## 2. File-by-file plan

- Modify `apps/billing/models.py`
  - Add `BillingInvoice.external_url = models.URLField(blank=True, default="")`.

- Create migration `apps/billing/migrations/0010_billinginvoice_external_url.py`
  - Add the field with blank default.

- Modify `apps/integrations/invoice_platform.py`
  - Add `external_url: str = ""` to `PaymentResult`.
  - Stub `fetch_invoice_payment()` returns deterministic URL.

- Modify `apps/integrations/invoice_ninja.py`
  - Extract a safe URL from known response fields only.
  - Do not synthesize URLs.

- Modify `apps/integrations/tasks.py`
  - Save `billing_invoice.external_url` when payment sync returns a non-empty URL.
  - Preserve existing non-empty URL when provider returns empty.

- Create `apps/billing/parent_portal.py`
  - Build small presentation dicts for issued invoice groups.
  - Keep query ownership-scoped through `ParentAccount -> Guardian -> Member -> BillingRecord -> BillingInvoice`.

- Modify `apps/registrations/views.py`
  - Import builder and pass `invoice_groups` to `parent_portal` template.
  - Add `open_parent_invoice(request, invoice_id)` redirect view.

- Modify `apps/registrations/urls.py`
  - Add `portal/invoices/<int:invoice_id>/open/` route.

- Modify `templates/registrations/parent_portal.html`
  - Add `Mani rēķini` section below applications.
  - Render empty state, grouped cards, rows, proxy link/unavailable text.

- Modify `static/css/parent_theme.css`
  - Add minimal `.fk-invoice-*` styles only if existing card/table classes are insufficient.

- Add tests:
  - `tests/billing/test_billing_invoice_external_url.py`
  - `tests/integrations/test_invoice_payment_readback.py` updates
  - `tests/billing/test_payment_sync_external_url.py`
  - `tests/registrations/test_parent_invoice_visibility.py`
  - `tests/registrations/test_parent_invoice_proxy.py`

- Modify `docs/milestones.md` after implementation succeeds.

## 3. Test strategy

- Use existing pytest + pytest-django fixtures: `verified_client`, `parent_account`, `other_parent_account`, `make_guardian`, `active_plan` where available.
- Test integration URL extraction with patched `requests.request`; no live Invoice Ninja calls.
- Test portal HTML with Django test client.
- Test proxy redirect with test client and ownership fixtures.
- Do not test CSS layout beyond class/copy contract; visual LAN acceptance covers final UX.
- Do not add tests for P14 custom invoices.

## 4. Acceptance mapping

- AC1 issued invoices listed: Task 4 tests + Task 5 implementation.
- AC2 unissued invoices hidden: Task 4 tests + builder filter.
- AC3 row fields shown: Task 4 tests + template.
- AC4 grouped child + season: Task 4 tests + builder shape.
- AC5 link only with URL: Task 4 tests + template branch.
- AC6 proxy ownership redirect: Task 6 tests + view.
- AC7 other guardian blocked: Task 6 tests + scoped queryset.
- AC8 Latvian empty/unavailable states: Task 4 tests + template.
- AC9 no custom invoices: no new model/type/routes beyond membership invoice rows.

## 5. Documentation scope

- Update `docs/milestones.md` only after implementation, verification, and review pass.
- Add no new operator doc unless Invoice Ninja live validation discovers a specific URL-field caveat.

---

## Task 1: Add stored invoice URL and provider contract

**Files:**
- Modify: `apps/billing/models.py`
- Create: `apps/billing/migrations/0010_billinginvoice_external_url.py`
- Modify: `apps/integrations/invoice_platform.py`
- Modify: `apps/integrations/invoice_ninja.py`
- Test: `tests/billing/test_billing_invoice_external_url.py`
- Test: `tests/integrations/test_invoice_payment_readback.py`

- [ ] **Step 1: Write failing model-field test**

Create `tests/billing/test_billing_invoice_external_url.py`:

```python
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def test_billing_invoice_external_url_defaults_to_blank(active_plan, guardian):
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.members.models import Member

    member = Member.objects.create(full_name="Jānis Bērziņš", guardian=guardian)
    record = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    invoice = BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
    )

    assert invoice.external_url == ""
```

- [ ] **Step 2: Run model-field test to verify it fails**

Run:

```bash
uv run pytest tests/billing/test_billing_invoice_external_url.py -q
```

Expected: FAIL with `BillingInvoice() got unexpected keyword` or `AttributeError` for `external_url`.

- [ ] **Step 3: Add model field**

In `apps/billing/models.py`, add this field to `BillingInvoice` after `external_invoice_id`:

```python
    external_url = models.URLField(blank=True, default="")
```

- [ ] **Step 4: Create migration**

Run:

```bash
uv run python manage.py makemigrations billing
```

Expected: creates `apps/billing/migrations/0010_billinginvoice_external_url.py` adding `external_url`.

- [ ] **Step 5: Run model-field test to verify it passes**

Run:

```bash
uv run pytest tests/billing/test_billing_invoice_external_url.py -q
```

Expected: PASS.

- [ ] **Step 6: Write failing provider-contract tests**

Append to `tests/integrations/test_invoice_payment_readback.py`:

```python

def test_stub_mode_returns_deterministic_external_url():
    from apps.integrations import invoice_platform

    result = invoice_platform.fetch_invoice_payment("inv-123")

    assert result.external_url == "https://stub.invalid/invoices/inv-123"


@override_settings(**INVOICE_NINJA)
def test_invoice_ninja_fetch_maps_safe_invoice_url():
    from apps.integrations import invoice_ninja

    payload = {
        "id": "inv-7",
        "status_id": "2",
        "amount": "30.00",
        "paid_to_date": "0.00",
        "balance": "30.00",
        "public_url": "https://in.example.com/client/invoices/inv-7",
    }
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")

    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-7")

    assert result.external_url == "https://in.example.com/client/invoices/inv-7"


@override_settings(**INVOICE_NINJA)
def test_invoice_ninja_fetch_does_not_guess_missing_invoice_url():
    from apps.integrations import invoice_ninja

    payload = {
        "id": "inv-8",
        "status_id": "2",
        "amount": "30.00",
        "paid_to_date": "0.00",
        "balance": "30.00",
    }
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")

    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-8")

    assert result.external_url == ""
```

- [ ] **Step 7: Run provider-contract tests to verify they fail**

Run:

```bash
uv run pytest tests/integrations/test_invoice_payment_readback.py -q
```

Expected: FAIL because `PaymentResult` has no `external_url`.

- [ ] **Step 8: Extend `PaymentResult` and stub**

In `apps/integrations/invoice_platform.py`, change `PaymentResult` to:

```python
@dataclass(frozen=True)
class PaymentResult:
    external_invoice_id: str
    payment_status: str
    amount: Decimal
    paid_to_date: Decimal
    balance: Decimal | None
    last_payment_date: date | None
    external_url: str = ""
```

In stub `fetch_invoice_payment()`, add:

```python
            external_url=f"https://stub.invalid/invoices/{external_invoice_id}",
```

- [ ] **Step 9: Add safe URL extraction to Invoice Ninja provider**

In `apps/integrations/invoice_ninja.py`, add helper near `_latest_payment_date`:

```python
def _invoice_external_url(data: dict) -> str:
    for key in ("public_url", "invoice_url", "payment_url", "client_url"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return ""
```

In `fetch_invoice_payment()`, add to `PaymentResult(...)`:

```python
        external_url=_invoice_external_url(data),
```

- [ ] **Step 10: Run provider tests to verify they pass**

Run:

```bash
uv run pytest tests/integrations/test_invoice_payment_readback.py tests/billing/test_billing_invoice_external_url.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit Task 1**

Only commit if user explicitly requested commits. Otherwise skip and leave changes unstaged.

## Task 2: Save external URL during payment sync

**Files:**
- Modify: `apps/integrations/tasks.py`
- Test: `tests/billing/test_payment_sync_external_url.py`

- [ ] **Step 1: Write failing sync tests**

Create `tests/billing/test_payment_sync_external_url.py`:

```python
from dataclasses import replace
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _invoice(active_plan, guardian, *, external_url=""):
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.members.models import Member

    member = Member.objects.create(full_name="Jānis Bērziņš", guardian=guardian)
    record = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
        external_status="synced",
    )
    return BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=timezone.localdate(),
        amount=Decimal("30.00"),
        external_invoice_id="inv-1",
        external_status="sent",
        sent_at=timezone.now(),
        external_url=external_url,
    )


def test_payment_sync_saves_external_url(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    base = invoice_platform.fetch_invoice_payment("inv-1")
    monkeypatch.setattr(
        invoice_platform,
        "fetch_invoice_payment",
        lambda _eid: replace(base, external_url="https://in.example.com/client/invoices/inv-1"),
    )
    invoice = _invoice(active_plan, guardian)

    tasks._sync_invoice_payment(invoice)

    invoice.refresh_from_db()
    assert invoice.external_url == "https://in.example.com/client/invoices/inv-1"


def test_payment_sync_preserves_existing_url_when_provider_returns_empty(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    base = invoice_platform.fetch_invoice_payment("inv-1")
    monkeypatch.setattr(
        invoice_platform,
        "fetch_invoice_payment",
        lambda _eid: replace(base, external_url=""),
    )
    invoice = _invoice(
        active_plan,
        guardian,
        external_url="https://in.example.com/client/invoices/existing",
    )

    tasks._sync_invoice_payment(invoice)

    invoice.refresh_from_db()
    assert invoice.external_url == "https://in.example.com/client/invoices/existing"
```

- [ ] **Step 2: Run sync tests to verify they fail**

Run:

```bash
uv run pytest tests/billing/test_payment_sync_external_url.py -q
```

Expected: FAIL because `_sync_invoice_payment` does not save `external_url`.

- [ ] **Step 3: Save URL in `_sync_invoice_payment`**

In `apps/integrations/tasks.py`, after `billing_invoice.last_synced_at = timezone.now()` add:

```python
    if result.external_url:
        billing_invoice.external_url = result.external_url
```

In `update_fields`, add:

```python
            "external_url",
```

Use this exact save block:

```python
    update_fields = [
        "payment_status",
        "paid_to_date",
        "balance",
        "last_payment_date",
        "last_synced_at",
        "updated_at",
    ]
    if result.external_url:
        billing_invoice.external_url = result.external_url
        update_fields.append("external_url")
    billing_invoice.save(update_fields=update_fields)
```

- [ ] **Step 4: Run sync tests to verify they pass**

Run:

```bash
uv run pytest tests/billing/test_payment_sync_external_url.py -q
```

Expected: PASS.

## Task 3: Build parent invoice presentation data

**Files:**
- Create: `apps/billing/parent_portal.py`
- Test: `tests/registrations/test_parent_invoice_visibility.py`

- [ ] **Step 1: Write failing builder tests**

Create `tests/registrations/test_parent_invoice_visibility.py`:

```python
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _billing_invoice(account, active_plan, make_guardian, *, member_name="Jānis", season="2026/2027", sequence=1, sent=True, payment_status="unpaid", external_url=""):
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.members.models import Member

    guardian = make_guardian(account, full_name="Vecāks")
    member = Member.objects.create(full_name=member_name, guardian=guardian)
    record = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
        external_status="synced",
    )
    return BillingInvoice.objects.create(
        billing_record=record,
        sequence=sequence,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
        external_invoice_id=f"inv-{account.pk}-{sequence}",
        external_status="sent" if sent else "created",
        sent_at=timezone.now() if sent else None,
        payment_status=payment_status,
        last_synced_at=timezone.now() if sent else None,
        external_url=external_url,
    )


def test_parent_invoice_groups_include_only_current_parent_issued_invoices(parent_account, other_parent_account, active_plan, make_guardian):
    from apps.billing.parent_portal import parent_invoice_groups

    own = _billing_invoice(parent_account, active_plan, make_guardian, member_name="Jānis")
    _billing_invoice(parent_account, active_plan, make_guardian, member_name="Future", sent=False)
    _billing_invoice(other_parent_account, active_plan, make_guardian, member_name="Svešs")

    groups = parent_invoice_groups(parent_account)

    assert len(groups) == 1
    assert groups[0]["member_name"] == "Jānis"
    assert groups[0]["season"] == "2026/2027"
    assert groups[0]["invoices"][0]["invoice"] == own


def test_parent_invoice_groups_separate_child_and_season(parent_account, active_plan, make_guardian):
    from apps.billing.parent_portal import parent_invoice_groups

    _billing_invoice(parent_account, active_plan, make_guardian, member_name="Jānis", season="2026/2027")
    _billing_invoice(parent_account, active_plan, make_guardian, member_name="Anna", season="2026/2027")
    _billing_invoice(parent_account, active_plan, make_guardian, member_name="Jānis", season="2027/2028")

    groups = parent_invoice_groups(parent_account)

    assert [(g["member_name"], g["season"]) for g in groups] == [
        ("Anna", "2026/2027"),
        ("Jānis", "2026/2027"),
        ("Jānis", "2027/2028"),
    ]
```

- [ ] **Step 2: Run builder tests to verify they fail**

Run:

```bash
uv run pytest tests/registrations/test_parent_invoice_visibility.py -q
```

Expected: FAIL because `apps.billing.parent_portal` does not exist.

- [ ] **Step 3: Create builder**

Create `apps/billing/parent_portal.py`:

```python
"""Parent-facing invoice presentation helpers for /portal/."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from django.db.models import Q
from django.urls import reverse

from apps.billing.messages import PAYMENT_STATUS_LABELS
from apps.billing.models import BillingInvoice
from apps.accounts.models import ParentAccount


def parent_invoice_groups(account: ParentAccount) -> list[dict[str, Any]]:
    invoices = (
        BillingInvoice.objects.filter(
            Q(sent_at__isnull=False) | Q(external_status="sent"),
            billing_record__member__guardian__parent_account=account,
            cancelled_at__isnull=True,
        )
        .select_related("billing_record__member", "billing_record__plan")
        .order_by(
            "billing_record__member__full_name",
            "billing_record__season",
            "due_date",
            "sequence",
        )
    )
    groups: OrderedDict[tuple[int, str], dict[str, Any]] = OrderedDict()
    for invoice in invoices:
        record = invoice.billing_record
        member = record.member
        key = (record.member_id, record.season)
        if key not in groups:
            groups[key] = {
                "member_name": member.full_name,
                "season": record.season,
                "final_amount": record.final_amount,
                "currency": record.plan.currency,
                "invoices": [],
            }
        groups[key]["invoices"].append(
            {
                "invoice": invoice,
                "sequence": invoice.sequence,
                "due_date": invoice.due_date,
                "amount": invoice.amount,
                "sent_status": "Izsūtīts",
                "payment_status": PAYMENT_STATUS_LABELS.get(invoice.payment_status, "—"),
                "last_synced_at": invoice.last_synced_at,
                "open_url": reverse("registrations:parent-invoice-open", args=[invoice.pk]) if invoice.external_url else "",
            }
        )
    return list(groups.values())
```

- [ ] **Step 4: Run builder tests to verify they pass**

Run:

```bash
uv run pytest tests/registrations/test_parent_invoice_visibility.py -q
```

Expected: PASS.

## Task 4: Render invoices on `/portal/`

**Files:**
- Modify: `apps/registrations/views.py`
- Modify: `templates/registrations/parent_portal.html`
- Modify: `static/css/parent_theme.css` if needed
- Test: `tests/registrations/test_parent_invoice_visibility.py`

- [ ] **Step 1: Add failing portal-render tests**

Append to `tests/registrations/test_parent_invoice_visibility.py`:

```python
from django.urls import reverse


def test_portal_renders_invoice_section_empty_state(verified_client):
    resp = verified_client.get(reverse("registrations:parent-portal"))

    html = resp.content.decode()
    assert resp.status_code == 200
    assert "Mani rēķini" in html
    assert "Šobrīd nav izsūtītu rēķinu." in html


def test_portal_renders_invoice_rows_and_proxy_link(verified_client, parent_account, active_plan, make_guardian):
    invoice = _billing_invoice(
        parent_account,
        active_plan,
        make_guardian,
        member_name="Jānis Bērziņš",
        payment_status="paid",
        external_url="https://in.example.com/client/invoices/inv-1",
    )

    resp = verified_client.get(reverse("registrations:parent-portal"))

    html = resp.content.decode()
    assert "Jānis Bērziņš" in html
    assert "2026/2027" in html
    assert "#1" in html
    assert "30.00" in html
    assert "Izsūtīts" in html
    assert "Apmaksāts" in html
    assert reverse("registrations:parent-invoice-open", args=[invoice.pk]) in html
    assert "Atvērt rēķinu" in html


def test_portal_renders_unavailable_link_copy_when_no_external_url(verified_client, parent_account, active_plan, make_guardian):
    _billing_invoice(parent_account, active_plan, make_guardian, external_url="")

    resp = verified_client.get(reverse("registrations:parent-portal"))

    html = resp.content.decode()
    assert "Saite būs pieejama pēc maksājuma sinhronizācijas." in html
    assert "Atvērt rēķinu" not in html


def test_portal_renders_no_sync_copy(verified_client, parent_account, active_plan, make_guardian):
    invoice = _billing_invoice(parent_account, active_plan, make_guardian)
    invoice.last_synced_at = None
    invoice.save(update_fields=["last_synced_at", "updated_at"])

    resp = verified_client.get(reverse("registrations:parent-portal"))

    assert "Vēl nav sinhronizēts" in resp.content.decode()
```

- [ ] **Step 2: Run portal-render tests to verify they fail**

Run:

```bash
uv run pytest tests/registrations/test_parent_invoice_visibility.py -q
```

Expected: FAIL because view/template do not pass/render `invoice_groups`.

- [ ] **Step 3: Pass invoice groups from view**

In `apps/registrations/views.py`, add import:

```python
from apps.billing.parent_portal import parent_invoice_groups
```

In `parent_portal()` context, add:

```python
            "invoice_groups": parent_invoice_groups(account),
```

- [ ] **Step 4: Render portal invoice section**

In `templates/registrations/parent_portal.html`, add after the applications/empty-state block and before helper card:

```django
<div class="fk-section-head">
  <h2>Mani rēķini</h2>
</div>

{% if invoice_groups %}
<section class="fk-invoice-groups">
  {% for group in invoice_groups %}
  <article class="fk-invoice-card">
    <div class="fk-app-person">
      <div class="fk-app-avatar">€</div>
      <div class="fk-app-main">
        <h3 class="fk-app-name">{{ group.member_name }}</h3>
        <div class="fk-app-meta">
          <div>Sezona: {{ group.season }}</div>
          <div>Kopā: {{ group.final_amount }} {{ group.currency }}</div>
        </div>
      </div>
    </div>
    <div class="fk-invoice-list">
      {% for row in group.invoices %}
      <div class="fk-invoice-row">
        <div>
          <strong>#{{ row.sequence }}</strong>
          <span>{{ row.due_date }}</span>
        </div>
        <div>{{ row.amount }} {{ group.currency }}</div>
        <div>{{ row.sent_status }}</div>
        <div>{{ row.payment_status }}</div>
        <div>{% if row.last_synced_at %}{{ row.last_synced_at }}{% else %}Vēl nav sinhronizēts{% endif %}</div>
        <div>
          {% if row.open_url %}
          <a class="fk-button fk-button--secondary fk-button--small" href="{{ row.open_url }}">Atvērt rēķinu</a>
          {% else %}
          <span class="fk-invoice-muted">Saite būs pieejama pēc maksājuma sinhronizācijas.</span>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
  </article>
  {% endfor %}
</section>
{% else %}
{% include "parent_ui/includes/empty_state.html" with title="Nav izsūtītu rēķinu" body="Šobrīd nav izsūtītu rēķinu." %}
{% endif %}
```

- [ ] **Step 5: Add minimal CSS only if layout needs it**

If raw rows are unreadable, append to `static/css/parent_theme.css`:

```css
.fk-invoice-groups {
  display: grid;
  gap: 16px;
}

.fk-invoice-card {
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(15, 8, 81, 0.12);
  border-radius: 24px;
  padding: 20px;
}

.fk-invoice-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.fk-invoice-row {
  display: grid;
  grid-template-columns: 0.8fr 0.8fr 0.8fr 1fr 1.3fr auto;
  gap: 12px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid rgba(15, 8, 81, 0.1);
}

.fk-invoice-muted {
  color: var(--fk-muted);
  font-size: 14px;
}

@media (max-width: 720px) {
  .fk-invoice-row {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 6: Run portal-render tests to verify they pass**

Run:

```bash
uv run pytest tests/registrations/test_parent_invoice_visibility.py -q
```

Expected: PASS.

## Task 5: Add parent invoice proxy route

**Files:**
- Modify: `apps/registrations/views.py`
- Modify: `apps/registrations/urls.py`
- Test: `tests/registrations/test_parent_invoice_proxy.py`

- [ ] **Step 1: Write failing proxy tests**

Create `tests/registrations/test_parent_invoice_proxy.py`:

```python
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _invoice(account, active_plan, make_guardian, *, sent=True, external_url="https://in.example.com/client/invoices/inv-1"):
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.members.models import Member

    guardian = make_guardian(account, full_name="Vecāks")
    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    record = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    return BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
        external_invoice_id="inv-1",
        external_status="sent" if sent else "created",
        sent_at=timezone.now() if sent else None,
        external_url=external_url,
    )


def test_parent_invoice_open_redirects_for_owned_issued_invoice_with_url(verified_client, parent_account, active_plan, make_guardian):
    invoice = _invoice(parent_account, active_plan, make_guardian)

    resp = verified_client.get(reverse("registrations:parent-invoice-open", args=[invoice.pk]))

    assert resp.status_code == 302
    assert resp["Location"] == "https://in.example.com/client/invoices/inv-1"


def test_parent_invoice_open_404_for_other_guardian(verified_client, other_parent_account, active_plan, make_guardian):
    invoice = _invoice(other_parent_account, active_plan, make_guardian)

    resp = verified_client.get(reverse("registrations:parent-invoice-open", args=[invoice.pk]))

    assert resp.status_code == 404


def test_parent_invoice_open_404_for_unissued_invoice(verified_client, parent_account, active_plan, make_guardian):
    invoice = _invoice(parent_account, active_plan, make_guardian, sent=False)

    resp = verified_client.get(reverse("registrations:parent-invoice-open", args=[invoice.pk]))

    assert resp.status_code == 404


def test_parent_invoice_open_404_when_no_external_url(verified_client, parent_account, active_plan, make_guardian):
    invoice = _invoice(parent_account, active_plan, make_guardian, external_url="")

    resp = verified_client.get(reverse("registrations:parent-invoice-open", args=[invoice.pk]))

    assert resp.status_code == 404


def test_parent_invoice_open_without_session_redirects_to_parent_entry(client, parent_account, active_plan, make_guardian):
    invoice = _invoice(parent_account, active_plan, make_guardian)

    resp = client.get(reverse("registrations:parent-invoice-open", args=[invoice.pk]))

    assert resp.status_code == 302
    assert reverse("registrations:start-registration") in resp["Location"]
```

- [ ] **Step 2: Run proxy tests to verify they fail**

Run:

```bash
uv run pytest tests/registrations/test_parent_invoice_proxy.py -q
```

Expected: FAIL because route/view does not exist.

- [ ] **Step 3: Add proxy view**

In `apps/registrations/views.py`, add imports:

```python
from django.db.models import Q
from apps.billing.models import BillingInvoice
```

Add view near `parent_portal()`:

```python
def open_parent_invoice(request: HttpRequest, invoice_id: int) -> HttpResponse:
    account = _current_parent_account(request)
    if account is None:
        return redirect("registrations:start-registration")

    invoice = (
        BillingInvoice.objects.filter(
            Q(sent_at__isnull=False) | Q(external_status="sent"),
            pk=invoice_id,
            billing_record__member__guardian__parent_account=account,
            cancelled_at__isnull=True,
        )
        .exclude(external_url="")
        .first()
    )
    if invoice is None:
        raise Http404
    return redirect(invoice.external_url)
```

- [ ] **Step 4: Add URL route**

In `apps/registrations/urls.py`, add before `path("portal/", ...)`:

```python
    path(
        "portal/invoices/<int:invoice_id>/open/",
        views.open_parent_invoice,
        name="parent-invoice-open",
    ),
```

- [ ] **Step 5: Run proxy tests to verify they pass**

Run:

```bash
uv run pytest tests/registrations/test_parent_invoice_proxy.py -q
```

Expected: PASS.

## Task 6: Final docs and verification

**Files:**
- Modify: `docs/milestones.md`
- Test: full verification commands

- [ ] **Step 1: Run targeted P12 test lane**

Run:

```bash
uv run pytest tests/billing/test_billing_invoice_external_url.py tests/billing/test_payment_sync_external_url.py tests/integrations/test_invoice_payment_readback.py tests/registrations/test_parent_invoice_visibility.py tests/registrations/test_parent_invoice_proxy.py -q
```

Expected: PASS.

- [ ] **Step 2: Run migration check**

Run:

```bash
uv run python manage.py makemigrations --check
```

Expected: `No changes detected`.

- [ ] **Step 3: Update milestones**

In `docs/milestones.md`, update P12 status under `### P12 — Parent invoice visibility` to note dev complete, files touched, and verification evidence. Use this shape:

```markdown
**Status:** dev complete (2026-07-13) — issued membership invoices are visible on `/portal/`, grouped by child + season, with payment/sent/sync status and a Django-owned proxy redirect for stored safe Invoice Ninja URLs. Future draft installments stay hidden. Verification: targeted P12 tests passed, full suite/lint/type gates pending or passed as recorded below.
```

- [ ] **Step 4: Run full verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: all pass.

- [ ] **Step 5: Generate critique diff URL**

Run:

```bash
bunx critique --web "P12 parent invoice visibility" --filter "apps/billing/models.py" --filter "apps/billing/parent_portal.py" --filter "apps/integrations/invoice_platform.py" --filter "apps/integrations/invoice_ninja.py" --filter "apps/integrations/tasks.py" --filter "apps/registrations/views.py" --filter "apps/registrations/urls.py" --filter "templates/registrations/parent_portal.html" --filter "static/css/parent_theme.css" --filter "tests/billing/test_billing_invoice_external_url.py" --filter "tests/billing/test_payment_sync_external_url.py" --filter "tests/integrations/test_invoice_payment_readback.py" --filter "tests/registrations/test_parent_invoice_visibility.py" --filter "tests/registrations/test_parent_invoice_proxy.py" --filter "docs/milestones.md"
```

Expected: command prints a critique URL. Share it with the user.

## Plan self-review

- Spec coverage: all P12 spec acceptance criteria map to Tasks 1-6.
- Red-flag scan: no unresolved implementation steps are intended in this plan.
- Type consistency: `external_url`, `PaymentResult.external_url`, `parent_invoice_groups()`, and `parent-invoice-open` names are used consistently.
- Scope check: P14 custom invoices, invoice detail pages, and guessed Invoice Ninja URLs are excluded.
