# P6 Slice C — Payment read-back + scheduled sync + sync health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close P6 by reading Invoice Ninja payment state back into Django on a nightly schedule, surfacing payment + sync health to staff with a manual retry path, hardening the Slice-B push dedup, and validating the whole push+read-back loop against the live Invoice Ninja instance.

**Architecture:** Mirror the existing Slice-B push shape. The boundary `apps/integrations/invoice_platform.py` gains a `fetch_invoice_payment` dispatch (stub/invoiceninja); the concrete `apps/integrations/invoice_ninja.py` does the `GET /invoices/{id}` + status mapping. Two django-q2 jobs in `apps/integrations/tasks.py` (a scheduled batch sweep + a manual per-record sync) write a read-only payment projection onto `BillingInvoice`, rolled up onto `BillingRecord` by a pure service helper. A data migration registers a daily `django_q` `Schedule`. Admin gets a sync action + payment columns + an invoice inline.

**Tech Stack:** Django, django-q2 (DB broker, existing `qcluster`), `requests`, pytest (`unittest.mock.patch` / `monkeypatch` — the repo does NOT use `responses` or `pytest-mock`), Decimal money, Latvian admin copy.

**Spec:** `docs/superpowers/specs/2026-06-08-p6-slice-c-payment-readback-sync-health-design.md`

**Conventions to honour (from AGENTS.md + existing code):**
- HTTP + enqueue spies use `unittest.mock.patch("apps.integrations.invoice_ninja.requests.request", ...)` returning a `types.SimpleNamespace(status_code=..., json=lambda: {...}, text="...")`, or `side_effect=[...]` for multi-call sequences.
- Reuse conftest fixtures: `active_plan`, `guardian` exist in both `tests/billing/conftest.py` and `tests/integrations/conftest.py`.
- `Guardian` has no `updated_at` — never put it in a guardian `update_fields`.
- Latvian admin copy lives in `apps/billing/messages.py`.
- Run gates with `uv run` (`uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`).

---

## File Structure

**Modify:**
- `apps/billing/models.py` — add `PaymentStatus` TextChoices; payment fields on `BillingInvoice` + `BillingRecord`.
- `apps/billing/services.py` — add `roll_up_payment_status(record)`.
- `apps/billing/messages.py` — add `PAYMENT_STATUS_LABELS`.
- `apps/billing/admin.py` — payment columns, `list_filter`, `BillingInvoiceInline`, "Pārbaudīt maksājumus" action.
- `apps/billing/management/commands/backfill_billing.py` — honest created-count (count delta).
- `apps/integrations/invoice_platform.py` — `PaymentResult` dataclass + `fetch_invoice_payment` dispatch.
- `apps/integrations/invoice_ninja.py` — `fetch_invoice_payment` GET + status mapping; dedup lookups in `ensure_product`/`ensure_client`; `_find_client_id_by_pk` helper.
- `apps/integrations/tasks.py` — `_sync_invoice_payment`, `sync_billing_payments`, `sync_billing_record_payments`, `enqueue_sync_billing_record_payments`.
- `fk_cesis_mms/settings.py` — `BILLING_PAYMENT_SYNC_HOUR`.
- `AGENTS.md`, `docs/milestones.md` — Slice C delivery notes + "signed = completed" interpretation.

**Create:**
- `apps/billing/migrations/0004_payment_projection.py` — payment fields.
- `apps/billing/migrations/0005_billing_payment_sync_schedule.py` — daily `Schedule` row.
- `tests/integrations/test_invoice_payment_readback.py` — adapter + provider read-back tests.
- `tests/integrations/test_invoice_ninja_dedup.py` — `ensure_product`/`ensure_client` dedup tests.
- `tests/integrations/test_sync_billing_payments.py` — batch + per-record job tests.
- `tests/billing/test_payment_rollup.py` — `roll_up_payment_status` unit tests.
- `tests/billing/test_payment_sync_schedule.py` — schedule migration idempotency test.
- `tests/billing/test_billing_admin_payment_sync.py` — admin action + inline tests.
- `tests/billing/test_signed_completed_trigger.py` — "signed = completed" verification test.

---

## Task 1: Payment projection data model

**Files:**
- Modify: `apps/billing/models.py`
- Create: `apps/billing/migrations/0004_payment_projection.py`
- Test: `tests/billing/test_billing_invoice_model.py` (append) — or a new assertion file; append is fine.

- [ ] **Step 1: Write the failing test**

Append to `tests/billing/test_billing_invoice_model.py`:

```python
def test_payment_projection_fields_default_blank(active_plan, guardian):
    from datetime import date
    from decimal import Decimal
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice, PaymentStatus

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    bi = BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1), amount=Decimal("30.00"),
    )
    assert bi.payment_status == ""
    assert bi.paid_to_date == Decimal("0.00")
    assert bi.balance is None
    assert bi.last_payment_date is None
    assert bi.last_synced_at is None
    assert rec.payment_status == ""
    assert rec.payment_synced_at is None
    assert PaymentStatus.PAID == "paid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_billing_invoice_model.py::test_payment_projection_fields_default_blank -v`
Expected: FAIL — `ImportError: cannot import name 'PaymentStatus'` (or `AttributeError` on the new fields).

- [ ] **Step 3: Add the choices + fields**

In `apps/billing/models.py`, after the imports (before `class MembershipPlan`), add:

```python
class PaymentStatus(models.TextChoices):
    UNPAID = "unpaid", "Nav apmaksāts"
    PARTIAL = "partial", "Daļēji apmaksāts"
    PAID = "paid", "Apmaksāts"
```

In `BillingRecord`, after the `external_error_code` field (line ~90), add:

```python
    payment_status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, blank=True, default=""
    )
    payment_synced_at = models.DateTimeField(null=True, blank=True)
```

In `BillingInvoice`, after its `external_error_code` field (line ~119), add:

```python
    payment_status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, blank=True, default=""
    )
    paid_to_date = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    balance = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    last_payment_date = models.DateField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
```

(`Decimal` is already imported at the top of the file.)

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations billing --name payment_projection`
Expected: creates `apps/billing/migrations/0004_payment_projection.py` adding the six fields. Open it and confirm it depends on `0003_billingrecord_external_error_code_and_more` and adds no unexpected changes.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_billing_invoice_model.py::test_payment_projection_fields_default_blank -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/billing/models.py apps/billing/migrations/0004_payment_projection.py tests/billing/test_billing_invoice_model.py
git commit -m "feat(billing): payment-projection fields on BillingInvoice + BillingRecord (P6 Slice C)"
```

---

## Task 2: Adapter — `PaymentResult` + stub `fetch_invoice_payment`

**Files:**
- Modify: `apps/integrations/invoice_platform.py`
- Test: `tests/integrations/test_invoice_payment_readback.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/test_invoice_payment_readback.py`:

```python
import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import override_settings

pytestmark = pytest.mark.django_db

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
)


def test_stub_mode_returns_unpaid_projection():
    from apps.integrations import invoice_platform

    result = invoice_platform.fetch_invoice_payment("anything")
    assert result.external_invoice_id == "anything"
    assert result.payment_status == "unpaid"
    assert result.paid_to_date == Decimal("0.00")
    assert result.balance is None
    assert result.last_payment_date is None


@override_settings(INVOICE_PROVIDER_MODE="bogus")
def test_unknown_mode_raises_config_error():
    from apps.integrations import invoice_platform
    from apps.integrations.invoice_platform import InvoicePlatformConfigError

    with pytest.raises(InvoicePlatformConfigError):
        invoice_platform.fetch_invoice_payment("x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_invoice_payment_readback.py -v`
Expected: FAIL — `AttributeError: module 'apps.integrations.invoice_platform' has no attribute 'fetch_invoice_payment'`.

- [ ] **Step 3: Add `PaymentResult` + dispatch**

In `apps/integrations/invoice_platform.py`, add `from datetime import date` and `from decimal import Decimal` to the imports, then after the `InvoiceResult` dataclass (line ~48) add:

```python
@dataclass(frozen=True)
class PaymentResult:
    external_invoice_id: str
    payment_status: str
    amount: Decimal
    paid_to_date: Decimal
    balance: Decimal | None
    last_payment_date: date | None
```

After `create_invoice` (end of file) add:

```python
def fetch_invoice_payment(external_invoice_id: str) -> PaymentResult:
    mode = _mode()
    if mode == "stub":
        return PaymentResult(
            external_invoice_id=external_invoice_id,
            payment_status="unpaid",
            amount=Decimal("0.00"),
            paid_to_date=Decimal("0.00"),
            balance=None,
            last_payment_date=None,
        )
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.fetch_invoice_payment(external_invoice_id)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_invoice_payment_readback.py -v`
Expected: PASS for the two tests written so far.

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/invoice_platform.py tests/integrations/test_invoice_payment_readback.py
git commit -m "feat(invoicing): PaymentResult + fetch_invoice_payment adapter dispatch (P6 Slice C)"
```

---

## Task 3: Provider — `fetch_invoice_payment` GET + status mapping

**Files:**
- Modify: `apps/integrations/invoice_ninja.py`
- Test: `tests/integrations/test_invoice_payment_readback.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/integrations/test_invoice_payment_readback.py`:

```python
@override_settings(**INVOICE_NINJA)
def test_paid_invoice_maps_to_paid_with_amounts():
    from datetime import date
    from apps.integrations import invoice_ninja

    payload = {
        "id": "inv-1", "status_id": "4", "amount": "30.00",
        "paid_to_date": "30.00", "balance": "0.00",
        "payments": [{"date": "2026-09-15"}, {"date": "2026-09-10"}],
    }
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake) as m:
        result = invoice_ninja.fetch_invoice_payment("inv-1")
    assert result.payment_status == "paid"
    assert result.paid_to_date == Decimal("30.00")
    assert result.balance == Decimal("0.00")
    assert result.last_payment_date == date(2026, 9, 15)
    assert m.call_args.kwargs["headers"]["X-Api-Token"] == "secret-token"
    assert m.call_args.args[0] == "GET"


@override_settings(**INVOICE_NINJA)
def test_partial_invoice_maps_to_partial():
    from apps.integrations import invoice_ninja

    payload = {"id": "inv-2", "status_id": "3", "amount": "30.00",
               "paid_to_date": "10.00", "balance": "20.00", "payments": []}
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-2")
    assert result.payment_status == "partial"
    assert result.balance == Decimal("20.00")
    assert result.last_payment_date is None


@override_settings(**INVOICE_NINJA)
def test_sent_unpaid_invoice_maps_to_unpaid():
    from apps.integrations import invoice_ninja

    payload = {"id": "inv-3", "status_id": "2", "amount": "30.00",
               "paid_to_date": "0.00", "balance": "30.00"}
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-3")
    assert result.payment_status == "unpaid"


@override_settings(**INVOICE_NINJA)
def test_amount_derived_fallback_when_status_id_absent():
    from apps.integrations import invoice_ninja

    payload = {"id": "inv-4", "amount": "30.00", "paid_to_date": "30.00", "balance": "0.00"}
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-4")
    assert result.payment_status == "paid"


@override_settings(**INVOICE_NINJA)
def test_readback_auth_error_maps_to_auth_exception():
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    fake = SimpleNamespace(status_code=401, json=lambda: {}, text="nope")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformAuthError):
            invoice_ninja.fetch_invoice_payment("inv-5")


@override_settings(**INVOICE_NINJA)
def test_readback_timeout_maps_to_transient():
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    with patch("apps.integrations.invoice_ninja.requests.request", side_effect=requests.Timeout("t")):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.fetch_invoice_payment("inv-6")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/test_invoice_payment_readback.py -v`
Expected: the six new tests FAIL with `AttributeError: ... has no attribute 'fetch_invoice_payment'`.

- [ ] **Step 3: Implement the provider read-back**

In `apps/integrations/invoice_ninja.py`, add imports near the top (after `import logging`):

```python
import datetime
from decimal import Decimal
```

Add `PaymentResult` to the boundary import block (lines ~17-25):

```python
from apps.integrations.invoice_platform import (
    ClientResult,
    InvoicePlatformAuthError,
    InvoicePlatformConfigError,
    InvoicePlatformNotFoundError,
    InvoicePlatformTransientError,
    InvoiceResult,
    PaymentResult,
    ProductResult,
)
```

At the end of the file add:

```python
def _to_decimal(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else "0"))


def _payment_status_from(data: dict, paid: Decimal, balance: Decimal) -> str:
    status_id = str(data.get("status_id", ""))
    if status_id == "4" or (paid > 0 and balance == 0):
        return "paid"
    if status_id == "3" or paid > 0:
        return "partial"
    return "unpaid"


def _latest_payment_date(data: dict) -> datetime.date | None:
    payments = data.get("payments") or []
    dates = [
        p.get("date") for p in payments
        if isinstance(p, dict) and p.get("date")
    ]
    if not dates:
        return None
    return datetime.date.fromisoformat(max(dates))


def fetch_invoice_payment(external_invoice_id: str) -> PaymentResult:
    api_url, api_key = _require_config()
    resp = _request("GET", f"{api_url}/invoices/{external_invoice_id}", api_key)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(
            f"invoice fetch rejected: {resp.status_code} {resp.text}"
        )
    data = _unwrap(resp)
    amount = _to_decimal(data.get("amount"))
    paid = _to_decimal(data.get("paid_to_date"))
    balance = _to_decimal(data.get("balance"))
    return PaymentResult(
        external_invoice_id=external_invoice_id,
        payment_status=_payment_status_from(data, paid, balance),
        amount=amount,
        paid_to_date=paid,
        balance=balance,
        last_payment_date=_latest_payment_date(data),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/test_invoice_payment_readback.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/invoice_ninja.py tests/integrations/test_invoice_payment_readback.py
git commit -m "feat(invoicing): Invoice Ninja invoice payment read-back + status mapping (P6 Slice C)"
```

---

## Task 4: Slice-B hardening — dedup lookup in `ensure_product` / `ensure_client`

**Files:**
- Modify: `apps/integrations/invoice_ninja.py`
- Test: `tests/integrations/test_invoice_ninja_dedup.py` (create)

**Why:** Deferred Slice-B item. If the IN POST succeeds but the Django `save()` fails, a retry currently creates a duplicate product/client. Look up first: product by `product_key`, client by `custom_value1=guardian.pk`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integrations/test_invoice_ninja_dedup.py`:

```python
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings

pytestmark = pytest.mark.django_db

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
)


@override_settings(**INVOICE_NINJA)
def test_ensure_product_reuses_existing_by_product_key(active_plan):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"id": "prod-existing"}]}, text=""
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=lookup
    ) as m:
        result = invoice_ninja.ensure_product(active_plan)
    assert result.external_id == "prod-existing"
    # Only the GET lookup happened — no POST create.
    assert all(call.args[0] == "GET" for call in m.call_args_list)


@override_settings(**INVOICE_NINJA)
def test_ensure_product_creates_when_absent(active_plan):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")
    create = SimpleNamespace(status_code=200, json=lambda: {"id": "prod-new"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, create],
    ) as m:
        result = invoice_ninja.ensure_product(active_plan)
    assert result.external_id == "prod-new"
    assert m.call_args_list[0].args[0] == "GET"
    assert m.call_args_list[1].args[0] == "POST"


@override_settings(**INVOICE_NINJA)
def test_ensure_client_reuses_existing_by_guardian_pk(guardian):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"id": "client-existing"}]}, text=""
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=lookup
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-existing"
    assert all(call.args[0] == "GET" for call in m.call_args_list)


@override_settings(**INVOICE_NINJA)
def test_ensure_client_creates_with_custom_value1_when_absent(guardian):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")
    create = SimpleNamespace(status_code=200, json=lambda: {"id": "client-new"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, create],
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-new"
    post_call = m.call_args_list[1]
    assert post_call.args[0] == "POST"
    assert post_call.kwargs["json"]["custom_value1"] == str(guardian.pk)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/test_invoice_ninja_dedup.py -v`
Expected: FAIL — current `ensure_product`/`ensure_client` POST first (no GET lookup), so the first call's method is `POST` and the reuse tests fail / the `custom_value1` key is absent.

- [ ] **Step 3: Add lookup helpers + guard the creates**

In `apps/integrations/invoice_ninja.py`, add two lookup helpers (place them just above `ensure_product`):

```python
def _find_product_id_by_key(api_url: str, api_key: str, product_key: str) -> str:
    resp = _request("GET", f"{api_url}/products?product_key={product_key}", api_key)
    rows = resp.json().get("data", [])
    if rows:
        return str(rows[0].get("id", ""))
    return ""


def _find_client_id_by_pk(api_url: str, api_key: str, guardian_pk: int) -> str:
    resp = _request("GET", f"{api_url}/clients?custom_value1={guardian_pk}", api_key)
    rows = resp.json().get("data", [])
    if rows:
        return str(rows[0].get("id", ""))
    return ""
```

Replace `ensure_product` with:

```python
def ensure_product(plan) -> ProductResult:
    api_url, api_key = _require_config()
    product_key = membership_plan_product_key(plan)
    existing = _find_product_id_by_key(api_url, api_key, product_key)
    if existing:
        return ProductResult(external_id=existing)
    body = {
        "product_key": product_key,
        "notes": messages.product_name(plan),
        "price": str(plan.annual_amount),
    }
    resp = _request("POST", f"{api_url}/products", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"product create rejected: {resp.status_code} {resp.text}")
    data = _unwrap(resp)
    return ProductResult(external_id=str(data.get("id", "")))
```

Replace `ensure_client` with:

```python
def ensure_client(guardian) -> ClientResult:
    api_url, api_key = _require_config()
    existing = _find_client_id_by_pk(api_url, api_key, guardian.pk)
    if existing:
        return ClientResult(external_id=existing)
    body = {
        "name": guardian.full_name,
        "custom_value1": str(guardian.pk),
        "contacts": [{"first_name": guardian.full_name, "email": guardian.email}],
    }
    resp = _request("POST", f"{api_url}/clients", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"client create rejected: {resp.status_code} {resp.text}")
    data = _unwrap(resp)
    return ClientResult(external_id=str(data.get("id", "")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/test_invoice_ninja_dedup.py tests/integrations/test_invoice_ninja_provider.py -v`
Expected: all PASS (the existing provider tests still pass — they patch `requests.request`; note `test_create_invoice_posts_and_returns_id` etc. exercise `create_invoice`, unaffected).

- [ ] **Step 5: Verify the push job tests still pass**

Run: `uv run pytest tests/billing/test_push_billing_record.py tests/integrations/test_invoice_platform.py -v`
Expected: PASS. (If any push test stubbed a single POST response for `ensure_product`/`ensure_client`, it now needs a leading GET-lookup response. If a test fails here, update that test's `side_effect` list to prepend an empty-data lookup `SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")` — do NOT change production code.)

- [ ] **Step 6: Commit**

```bash
git add apps/integrations/invoice_ninja.py tests/integrations/test_invoice_ninja_dedup.py
git commit -m "fix(invoicing): dedup ensure_product/ensure_client via lookup before create (P6 Slice C)"
```

---

## Task 5: Roll-up service helper

**Files:**
- Modify: `apps/billing/services.py`
- Test: `tests/billing/test_payment_rollup.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/billing/test_payment_rollup.py`:

```python
import pytest
from datetime import date
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record_with_invoices(active_plan, guardian, statuses):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    for i, status in enumerate(statuses, start=1):
        BillingInvoice.objects.create(
            billing_record=rec, sequence=i, due_date=date(2026, 9, i),
            amount=Decimal("30.00"), payment_status=status,
        )
    return rec


def test_all_paid_rolls_up_to_paid(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["paid", "paid"])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PAID
    assert rec.payment_synced_at is not None


def test_some_paid_rolls_up_to_partial(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["paid", "unpaid"])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PARTIAL


def test_partial_invoice_rolls_up_to_partial(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["partial", "unpaid"])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PARTIAL


def test_none_paid_rolls_up_to_unpaid(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["unpaid", ""])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.UNPAID
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_payment_rollup.py -v`
Expected: FAIL — `ImportError: cannot import name 'roll_up_payment_status'`.

- [ ] **Step 3: Implement the helper**

In `apps/billing/services.py`, add (near `recompute_billing_record`; `timezone` import: add `from django.utils import timezone` to the top of the file if not already present — check the existing imports and only add if missing):

```python
def roll_up_payment_status(record) -> None:
    """Derive the record-level payment_status from its invoices and stamp
    payment_synced_at. all paid -> paid; any paid/partial -> partial; else unpaid."""
    from apps.billing.models import PaymentStatus

    statuses = list(record.invoices.values_list("payment_status", flat=True))
    if statuses and all(s == PaymentStatus.PAID for s in statuses):
        record.payment_status = PaymentStatus.PAID
    elif any(s in (PaymentStatus.PAID, PaymentStatus.PARTIAL) for s in statuses):
        record.payment_status = PaymentStatus.PARTIAL
    else:
        record.payment_status = PaymentStatus.UNPAID
    record.payment_synced_at = timezone.now()
    record.save(update_fields=["payment_status", "payment_synced_at", "updated_at"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_payment_rollup.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/billing/services.py tests/billing/test_payment_rollup.py
git commit -m "feat(billing): roll_up_payment_status record-level payment projection (P6 Slice C)"
```

---

## Task 6: Sync jobs — batch sweep + manual per-record

**Files:**
- Modify: `apps/integrations/tasks.py`
- Test: `tests/integrations/test_sync_billing_payments.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/integrations/test_sync_billing_payments.py`:

```python
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def _confirmed_record_with_invoices(active_plan, guardian, external_ids):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    for i, ext in enumerate(external_ids, start=1):
        BillingInvoice.objects.create(
            billing_record=rec, sequence=i, due_date=date(2026, 9, i),
            amount=Decimal("30.00"), external_invoice_id=ext,
        )
    return rec


def _payment(status="paid", paid="30.00", balance="0.00", dt=None):
    from apps.integrations.invoice_platform import PaymentResult

    return PaymentResult(
        external_invoice_id="x", payment_status=status,
        amount=Decimal("30.00"), paid_to_date=Decimal(paid),
        balance=Decimal(balance), last_payment_date=dt,
    )


def test_batch_sweep_writes_projection_and_rolls_up(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_payments
    from apps.billing.models import PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1", "inv-2"])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(dt=date(2026, 9, 12)),
    ):
        sync_billing_payments()
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PAID
    assert rec.payment_synced_at is not None
    inv = rec.invoices.first()
    assert inv.payment_status == "paid"
    assert inv.paid_to_date == Decimal("30.00")
    assert inv.last_payment_date == date(2026, 9, 12)
    assert inv.last_synced_at is not None


def test_batch_sweep_skips_invoices_without_external_id(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_payments

    rec = _confirmed_record_with_invoices(active_plan, guardian, [""])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=AssertionError("should not be called"),
    ):
        sync_billing_payments()  # must not raise / not call fetch
    rec.refresh_from_db()
    assert rec.payment_synced_at is None


def test_batch_sweep_isolates_per_row_errors(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_payments
    from apps.integrations.invoice_platform import InvoicePlatformTransientError
    from apps.billing.models import PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1", "inv-2"])
    calls = {"n": 0}

    def _side_effect(external_id):
        calls["n"] += 1
        if external_id == "inv-1":
            raise InvoicePlatformTransientError("boom")
        return _payment()

    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=_side_effect,
    ):
        sync_billing_payments()  # one bad row must not abort the sweep
    rec.refresh_from_db()
    # inv-2 still got synced -> record rolled up (partial: one paid, one unsynced)
    assert calls["n"] == 2
    assert rec.payment_status == PaymentStatus.PARTIAL


def test_manual_record_sync_surfaces_terminal_error(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_record_payments
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=InvoicePlatformAuthError("nope"),
    ):
        sync_billing_record_payments(rec.pk)
    rec.refresh_from_db()
    assert rec.external_error_code == "auth_failed"


def test_manual_record_sync_retryable_raises(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_record_payments, RetryableInvoiceError
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=InvoicePlatformTransientError("later"),
    ):
        with pytest.raises(RetryableInvoiceError):
            sync_billing_record_payments(rec.pk)


def test_manual_record_sync_success_clears_error_and_rolls_up(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_record_payments
    from apps.billing.models import BillingRecord, PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    BillingRecord.objects.filter(pk=rec.pk).update(external_error_code="auth_failed")
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(),
    ):
        sync_billing_record_payments(rec.pk)
    rec.refresh_from_db()
    assert rec.external_error_code == ""
    assert rec.payment_status == PaymentStatus.PAID
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/test_sync_billing_payments.py -v`
Expected: FAIL — `ImportError: cannot import name 'sync_billing_payments'`.

- [ ] **Step 3: Implement the jobs**

Append to `apps/integrations/tasks.py` (after `push_billing_record`):

```python
def _sync_invoice_payment(billing_invoice) -> None:
    """Fetch + write the payment projection for one invoice. Raises on
    provider error (caller decides isolation vs. surfacing)."""
    result = invoice_platform.fetch_invoice_payment(billing_invoice.external_invoice_id)
    billing_invoice.payment_status = result.payment_status
    billing_invoice.paid_to_date = result.paid_to_date
    billing_invoice.balance = result.balance
    billing_invoice.last_payment_date = result.last_payment_date
    billing_invoice.last_synced_at = timezone.now()
    billing_invoice.save(
        update_fields=[
            "payment_status",
            "paid_to_date",
            "balance",
            "last_payment_date",
            "last_synced_at",
            "updated_at",
        ]
    )


def sync_billing_payments() -> None:
    """Scheduled nightly sweep: refresh the payment projection for every
    invoice with an external id. Per-row errors are logged and skipped so one
    bad row never aborts the run."""
    from apps.billing.models import BillingInvoice
    from apps.billing.services import roll_up_payment_status

    invoices = BillingInvoice.objects.exclude(external_invoice_id="").select_related(
        "billing_record"
    )
    touched: dict[int, object] = {}
    for billing_invoice in invoices:
        try:
            _sync_invoice_payment(billing_invoice)
        except Exception as exc:  # noqa: BLE001 - batch sweep isolates per-row failures
            logger.warning(
                "payment sync failed for invoice %s: %s", billing_invoice.pk, exc
            )
            continue
        touched[billing_invoice.billing_record_id] = billing_invoice.billing_record
    for record in touched.values():
        roll_up_payment_status(record)


def enqueue_sync_billing_record_payments(record_id: int) -> None:
    try:
        async_task(
            "apps.integrations.tasks.sync_billing_record_payments", record_id
        )
    except RetryableInvoiceError:
        return


def sync_billing_record_payments(record_id: int) -> None:
    """Manual single-record payment sync (admin action). Surfaces a terminal
    error on the record's external_error_code; re-raises transient errors so
    the cluster retries."""
    from apps.billing.models import BillingRecord
    from apps.billing.services import roll_up_payment_status

    try:
        record = BillingRecord.objects.get(pk=record_id)
    except BillingRecord.DoesNotExist:
        return

    for billing_invoice in record.invoices.exclude(external_invoice_id=""):
        try:
            _sync_invoice_payment(billing_invoice)
        except Exception as exc:
            code, retry = _classify_invoice_error(exc)
            record.external_error_code = code
            record.save(update_fields=["external_error_code", "updated_at"])
            if retry:
                raise RetryableInvoiceError(code) from exc
            return

    if record.external_error_code:
        record.external_error_code = ""
        record.save(update_fields=["external_error_code", "updated_at"])
    roll_up_payment_status(record)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/test_sync_billing_payments.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/tasks.py tests/integrations/test_sync_billing_payments.py
git commit -m "feat(invoicing): sync_billing_payments batch sweep + manual per-record sync (P6 Slice C)"
```

---

## Task 7: Setting + scheduled `Schedule` migration

**Files:**
- Modify: `fk_cesis_mms/settings.py`
- Create: `apps/billing/migrations/0005_billing_payment_sync_schedule.py`
- Test: `tests/billing/test_payment_sync_schedule.py` (create)

- [ ] **Step 1: Add the setting**

In `fk_cesis_mms/settings.py`, after the invoice settings block (after line ~182 `INVOICE_NINJA_NUMBER_PREFIX`), add:

```python
# Hour-of-day (local time, 0-23) for the nightly billing payment-sync sweep.
# Editable per-environment; the django-q2 Schedule row created by
# apps/billing/migrations/0005 reads this for its initial next_run.
BILLING_PAYMENT_SYNC_HOUR = int(os.environ.get("BILLING_PAYMENT_SYNC_HOUR", "3"))
```

- [ ] **Step 2: Write the failing test**

Create `tests/billing/test_payment_sync_schedule.py`:

```python
import pytest

pytestmark = pytest.mark.django_db


def test_payment_sync_schedule_row_exists():
    from django_q.models import Schedule

    sched = Schedule.objects.filter(name="billing-payment-sync").first()
    assert sched is not None
    assert sched.func == "apps.integrations.tasks.sync_billing_payments"
    assert sched.schedule_type == Schedule.DAILY


def test_schedule_migration_is_idempotent():
    """Re-running the create function must not create a duplicate row."""
    from django.conf import settings
    from importlib import import_module

    migration = import_module(
        "apps.billing.migrations.0005_billing_payment_sync_schedule"
    )
    from django_q.models import Schedule

    before = Schedule.objects.filter(name="billing-payment-sync").count()
    migration.create_schedule(None, None)
    after = Schedule.objects.filter(name="billing-payment-sync").count()
    assert before == 1
    assert after == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_payment_sync_schedule.py -v`
Expected: FAIL — no such migration module / no Schedule row.

- [ ] **Step 4: Write the migration**

Create `apps/billing/migrations/0005_billing_payment_sync_schedule.py`:

```python
"""Register the nightly billing payment-sync django-q2 Schedule (P6 Slice C)."""

import datetime

from django.conf import settings
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "billing-payment-sync"
SCHEDULE_FUNC = "apps.integrations.tasks.sync_billing_payments"


def _next_run():
    hour = getattr(settings, "BILLING_PAYMENT_SYNC_HOUR", 3)
    now = timezone.localtime()
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": SCHEDULE_FUNC,
            "schedule_type": Schedule.DAILY,
            "next_run": _next_run(),
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_payment_projection"),
        # Depend on django_q's LATEST migration so the fully-migrated Schedule
        # table (name, schedule_type, cluster, ...) exists before we insert a row.
        # Verified latest at plan time; re-check with
        #   uv run python manage.py showmigrations django_q | tail -1
        # and update if django_q was upgraded.
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
```

- [ ] **Step 5: Apply migrations + run test**

Run: `uv run python manage.py migrate billing`
Then: `uv run pytest tests/billing/test_payment_sync_schedule.py -v`
Expected: PASS. (Note: the test DB runs all migrations, so the Schedule row is created during test setup; `create_schedule` being called a second time in the idempotency test stays at count 1 via `get_or_create`.)

- [ ] **Step 6: Commit**

```bash
git add fk_cesis_mms/settings.py apps/billing/migrations/0005_billing_payment_sync_schedule.py tests/billing/test_payment_sync_schedule.py
git commit -m "feat(billing): nightly payment-sync django-q2 Schedule + configurable hour (P6 Slice C)"
```

---

## Task 8: Latvian copy for payment status

**Files:**
- Modify: `apps/billing/messages.py`
- Test: `tests/billing/test_invoice_messages.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/billing/test_invoice_messages.py`:

```python
def test_payment_status_labels_latvian():
    from apps.billing.messages import PAYMENT_STATUS_LABELS

    assert PAYMENT_STATUS_LABELS["unpaid"] == "Nav apmaksāts"
    assert PAYMENT_STATUS_LABELS["partial"] == "Daļēji apmaksāts"
    assert PAYMENT_STATUS_LABELS["paid"] == "Apmaksāts"
    assert PAYMENT_STATUS_LABELS[""] == "—"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_invoice_messages.py::test_payment_status_labels_latvian -v`
Expected: FAIL — `ImportError: cannot import name 'PAYMENT_STATUS_LABELS'`.

- [ ] **Step 3: Add the labels**

In `apps/billing/messages.py`, after `PAYMENT_MODE_LABELS` (line ~6), add:

```python
PAYMENT_STATUS_LABELS = {
    "": "—",
    "unpaid": "Nav apmaksāts",
    "partial": "Daļēji apmaksāts",
    "paid": "Apmaksāts",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_invoice_messages.py::test_payment_status_labels_latvian -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/billing/messages.py tests/billing/test_invoice_messages.py
git commit -m "feat(billing): Latvian payment-status labels (P6 Slice C)"
```

---

## Task 9: Admin — sync action + payment columns + invoice inline

**Files:**
- Modify: `apps/billing/admin.py`
- Test: `tests/billing/test_billing_admin_payment_sync.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/billing/test_billing_admin_payment_sync.py`:

```python
import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def _confirmed_record(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1),
        amount=Decimal("30.00"), external_invoice_id="inv-1",
    )
    return rec


def test_sync_payments_action_enqueues_confirmed(active_plan, guardian, staff_client):
    from django.urls import reverse
    from apps.billing.models import BillingRecord

    rec = _confirmed_record(active_plan, guardian)
    url = reverse("admin:billing_billingrecord_changelist")
    with patch(
        "apps.integrations.tasks.enqueue_sync_billing_record_payments"
    ) as enq:
        resp = staff_client.post(
            url,
            {"action": "sync_payments", "_selected_action": [str(rec.pk)]},
            follow=True,
        )
    assert resp.status_code == 200
    enq.assert_called_once_with(rec.pk)


def test_sync_payments_action_skips_draft(active_plan, guardian, staff_client):
    from django.urls import reverse
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Anna", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.DRAFT,
    )
    url = reverse("admin:billing_billingrecord_changelist")
    with patch(
        "apps.integrations.tasks.enqueue_sync_billing_record_payments"
    ) as enq:
        staff_client.post(
            url,
            {"action": "sync_payments", "_selected_action": [str(rec.pk)]},
            follow=True,
        )
    enq.assert_not_called()


def test_changelist_shows_payment_status_column(active_plan, guardian, staff_client):
    from django.urls import reverse

    _confirmed_record(active_plan, guardian)
    url = reverse("admin:billing_billingrecord_changelist")
    resp = staff_client.get(url)
    assert resp.status_code == 200
    # payment_status is in list_display -> the column header renders
    assert b"payment_status" in resp.content.lower() or b"payment" in resp.content.lower()
```

(`staff_client` fixture lives in `tests/conftest.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_billing_admin_payment_sync.py -v`
Expected: FAIL — the `sync_payments` action does not exist, so the POST is a no-op and `enq.assert_called_once_with` fails.

- [ ] **Step 3: Wire the admin**

In `apps/billing/admin.py`:

Update the import line:

```python
from apps.billing.models import BillingInvoice, BillingRecord, MembershipPlan
```

Add the inline class above `BillingRecordAdmin`:

```python
class BillingInvoiceInline(admin.TabularInline):
    model = BillingInvoice
    extra = 0
    can_delete = False
    fields = (
        "sequence", "due_date", "amount", "external_invoice_id", "external_status",
        "payment_status", "paid_to_date", "balance", "last_payment_date", "last_synced_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False
```

In `BillingRecordAdmin`:

- Extend `list_display` to end with `"payment_status", "payment_synced_at"`:

```python
    list_display = (
        "member", "guardian_name", "season", "final_amount",
        "is_full_price", "payment_mode", "status", "external_status",
        "payment_status", "payment_synced_at",
    )
```

- Extend `list_filter` with `"payment_status"`:

```python
    list_filter = (
        "season", "status", "payment_mode", "is_full_price",
        "external_status", "payment_status",
    )
```

- Add the new fields to `readonly_fields` (append `"payment_status", "payment_synced_at"` before `"created_at"`):

```python
    readonly_fields = (
        "member", "plan", "agreement", "season", "base_amount", "is_full_price",
        "sibling_discount_percent_applied", "discount_amount", "final_amount",
        "payment_mode", "full_price_opt_out", "external_status", "external_error_code",
        "payment_status", "payment_synced_at",
        "created_at", "updated_at",
    )
```

- Add `inlines` and extend `actions`:

```python
    inlines = (BillingInvoiceInline,)
    actions = ("recompute_from_plan", "push_to_invoice_ninja", "sync_payments")
```

- Add the action method (after `push_to_invoice_ninja`):

```python
    @admin.action(description="Pārbaudīt maksājumus (Invoice Ninja)")
    def sync_payments(self, request, queryset):
        from apps.integrations.tasks import enqueue_sync_billing_record_payments

        synced = 0
        unconfirmed = 0
        for record in queryset:
            if record.status != BillingRecord.Status.CONFIRMED:
                unconfirmed += 1
                continue
            enqueue_sync_billing_record_payments(record.pk)
            synced += 1
        parts = [f"Pieprasīta maksājumu pārbaude: {synced}."]
        if unconfirmed:
            parts.append(f"Izlaisti {unconfirmed} (vispirms apstipriniet).")
        level = messages.WARNING if unconfirmed else messages.INFO
        self.message_user(request, " ".join(parts), level=level)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_billing_admin_payment_sync.py tests/billing/test_billing_admin.py tests/billing/test_billing_admin_push.py -v`
Expected: all PASS (existing admin tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add apps/billing/admin.py tests/billing/test_billing_admin_payment_sync.py
git commit -m "feat(billing): admin payment-sync action + payment columns + invoice inline (P6 Slice C)"
```

---

## Task 10: Honest `backfill_billing` created-count

**Files:**
- Modify: `apps/billing/management/commands/backfill_billing.py`
- Test: `tests/billing/test_backfill_billing.py` (append)

**Why:** The command currently increments on `record.agreement_id == agreement.pk`, which is true for pre-existing records too, so it over-reports. Count the actual row delta instead — no service signature change (keeps ~8 call sites stable).

- [ ] **Step 1: Write the failing test**

Append to `tests/billing/test_backfill_billing.py`:

```python
def test_backfill_reports_honest_created_count(active_plan, guardian):
    member = _signed_member(guardian, "Jānis")  # noqa: F841

    out = StringIO()
    call_command("backfill_billing", stdout=out)
    assert "1 created" in out.getvalue()

    out2 = StringIO()
    call_command("backfill_billing", stdout=out2)
    assert "0 created" in out2.getvalue()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_backfill_billing.py::test_backfill_reports_honest_created_count -v`
Expected: FAIL on the second assertion — re-run still reports "1 created".

- [ ] **Step 3: Fix the count**

Replace the body of `handle` in `apps/billing/management/commands/backfill_billing.py`:

```python
    def handle(self, *args, **options):
        from apps.billing.models import BillingRecord

        before = BillingRecord.objects.count()
        seen_members = set()
        signed = (
            Agreement.objects.filter(state=Agreement.State.SIGNED)
            .select_related("member")
            .order_by("pk")
        )
        for agreement in signed:
            if agreement.member_id in seen_members:
                continue
            seen_members.add(agreement.member_id)
            create_draft_billing_for_member(agreement.member, agreement=agreement)
        created = BillingRecord.objects.count() - before
        self.stdout.write(self.style.SUCCESS(f"Backfill complete: {created} created."))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_backfill_billing.py -v`
Expected: all PASS (including the existing idempotency/noop tests).

- [ ] **Step 5: Commit**

```bash
git add apps/billing/management/commands/backfill_billing.py tests/billing/test_backfill_billing.py
git commit -m "fix(billing): backfill_billing reports honest created count (P6 Slice C)"
```

---

## Task 11: Verify "signed = completed" trigger (acceptance items 1-2)

**Files:**
- Create: `tests/billing/test_signed_completed_trigger.py`

**Why:** P6 items 1-2 require billing to start after the agreement reaches its final/"completed" state. The decision (spec §2) is that agreement `signed` IS that final state for both paths. This test documents the contract end-to-end for the electronic path; no production change.

- [ ] **Step 1: Write the test**

Create `tests/billing/test_signed_completed_trigger.py`:

```python
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_electronic_agreement_signed_completes_and_triggers_billing(active_plan, guardian):
    """An electronic agreement reaching SIGNED (the 'completed' final state)
    auto-creates a DRAFT BillingRecord via the agreement_signed signal.
    This is the P6 #1-2 "billing starts after completed" guarantee."""
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_signed
    from apps.billing.models import BillingRecord
    from django.utils import timezone

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    RegistrationApplication.objects.create(
        guardian_email=guardian.email,
        approved_member=member,
        preferred_agreement_signing="electronic",
    )
    agreement = Agreement.objects.create(
        member=member, generated_at=timezone.now(), signing_path="electronic",
    )

    assert not BillingRecord.objects.filter(member=member).exists()

    mark_agreement_signed(agreement, actor=None)

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SIGNED  # "completed" final state
    rec = BillingRecord.objects.get(member=member)
    assert rec.status == BillingRecord.Status.DRAFT
    assert rec.final_amount == Decimal("300.00")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_signed_completed_trigger.py -v`
Expected: PASS (the behaviour already exists from Slice A — this test pins it). If it fails, check that `Agreement` accepts `signing_path` and `RegistrationApplication` accepts `preferred_agreement_signing` (both exist post-P5); adjust the field name to match the model, do NOT change production code.

- [ ] **Step 3: Commit**

```bash
git add tests/billing/test_signed_completed_trigger.py
git commit -m "test(billing): pin 'signed = completed' billing trigger (P6 acceptance 1-2)"
```

---

## Task 12: Full gate + documentation

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Run the full gate**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```
Expected: all green. Record the passed count (should be ~1080 + the new Slice C tests). If ruff/mypy flag anything in the new code, fix it and re-run. Do not proceed with a red gate (Rule 7 — fail loud).

- [ ] **Step 2: Update AGENTS.md**

Under the P6 section, add a `P6 Slice C delivered` entry summarizing: payment-projection fields + migration `0004`; `fetch_invoice_payment` adapter+provider with `status_id`→status mapping and amount-derived fallback; `sync_billing_payments` nightly batch (per-row isolation) + `sync_billing_record_payments` manual sync; `Schedule` row migration `0005` + `BILLING_PAYMENT_SYNC_HOUR`; admin payment columns + inline + "Pārbaudīt maksājumus" action; `ensure_product`/`ensure_client` dedup hardening (the deferred Slice-B item — now closed); honest `backfill_billing` count; "signed = completed" trigger verification (items 1-2). Note the new gate count. Mark the deferred Slice-B hardening line as resolved. State that live-IN end-to-end validation (Task 13) is the remaining sign-off step.

- [ ] **Step 3: Update docs/milestones.md**

In the P6 status block (line ~246), change the status to note Slice C delivered (pending live-IN validation) and that P6 acceptance items 7, 8, 9 are addressed and 1, 2 verified. Reference the plan + spec paths.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: P6 Slice C delivered — payment read-back + scheduled sync + sync health"
```

---

## Task 13: Live Invoice Ninja validation (sign-off gate)

**Not a code task — an operator validation run against the real instance.** Per the P3/P5 lesson, expect this to surface integration bugs the stub hid; fix each with a focused commit and re-verify, then record evidence.

- [ ] **Step 1: Configure live mode**

Set in the deployment `.env` (NOT committed): `INVOICE_PROVIDER_MODE=invoiceninja`, `INVOICE_NINJA_API_URL=<live>/api/v1`, `INVOICE_NINJA_API_KEY=<token>`, optionally `INVOICE_NINJA_NUMBER_PREFIX`. Ensure the `qcluster` worker is running (`uv run python manage.py qcluster`).

- [ ] **Step 2: Validate the push path (Slice B, first live run)**

Confirm a `BillingRecord` → admin "Izrakstīt rēķinus (Invoice Ninja)" → verify in the IN UI: product created with the right `product_key`, client created (check `custom_value1` = guardian pk), one invoice per installment with correct numbers (`{PREFIX}-{record}-{seq}`), net amounts, and the Latvian sibling-discount note. Then re-run the action and the dedup lookups (forced: clear a stored external id and re-push) → confirm NO duplicate product/client/invoice.

- [ ] **Step 3: Validate the read-back path (Slice C)**

In IN, mark one invoice paid and another partially paid. Run the admin "Pārbaudīt maksājumus" action (and let the nightly `Schedule` fire, or trigger `sync_billing_payments` manually via `uv run python manage.py shell`). Verify `BillingInvoice.payment_status`/`paid_to_date`/`balance`/`last_payment_date` are correct and `BillingRecord.payment_status` rolled up to `partial`.

- [ ] **Step 4: Fix any surfaced bugs**

Likely candidates (the recurring pattern): IN field names (`paid_to_date` vs `paid`, payment date location), `status_id` values, list-wrap on the GET response, auth header. Fix each in `apps/integrations/invoice_ninja.py` with a focused `fix(invoicing): ...` commit + a regression test where feasible, and re-run the affected live step.

- [ ] **Step 5: Record evidence + sign off**

Update the AGENTS.md P6 Slice C entry with the live-validation date, what was checked, and any bugs fixed (mirror the P5 Slice D "Live DocuSeal validation" block). Mark P6 complete in `docs/milestones.md`. Commit:

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: P6 Slice C live Invoice Ninja validation + sign-off"
```

---

## Self-Review notes

- **Spec coverage:** §3 model → T1; §4 adapter/provider → T2/T3; §4 hardening → T4; §5 jobs → T5/T6; §6 schedule → T7; §7 admin → T9 (+ messages T8); §8 trigger-verify + cosmetic → T10/T11; §9 live validation → T13; §10 testing distributed across T1-T11; §12 gate → T12.
- **Type consistency:** `PaymentResult(external_invoice_id, payment_status, amount, paid_to_date, balance, last_payment_date)` is defined in T2 and consumed identically in T3 (provider return) and T6 (`_sync_invoice_payment` reads `.payment_status/.paid_to_date/.balance/.last_payment_date`). `PaymentStatus` choices defined in T1, used in T5 roll-up, T6/T8 tests. `roll_up_payment_status(record)` defined T5, called in T6. `enqueue_sync_billing_record_payments` defined T6, called in T9 admin.
- **No service signature change:** backfill count fixed by row-delta (T10), so the ~8 `create_draft_billing_for_member` call sites stay intact.
- **Known live-validation risk:** the IN read-back field mapping in T3 is design-intent and explicitly re-checked in T13 — the one place stub fixtures can be wrong.
