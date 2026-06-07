# P6 Slice B — Invoice Ninja push integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push confirmed local `BillingRecord`s to a self-hosted Invoice Ninja instance — sync the plan as a product, ensure the guardian is a client, and create one invoice per installment — via a deliberate, admin-confirmed action.

**Architecture:** Mirror the proven DocuSeal integration. A boundary module (`apps/integrations/invoice_platform.py`) owns the exception taxonomy + frozen result dataclasses + stub/real dispatch on `settings.INVOICE_PROVIDER_MODE`; a concrete provider (`apps/integrations/invoice_ninja.py`) does the HTTP. A django-q2 job pushes a record; a `BillingRecordAdmin` action enqueues it. Django stays the price/schedule authority — IN computes nothing. Push-only; payment read-back is Slice C.

**Tech Stack:** Django 6, Python 3.12, `uv`, pytest + pytest-django, django-q2, `requests`, ruff, mypy. Reference design: `docs/superpowers/specs/2026-06-07-p6-slice-b-invoice-ninja-push-design.md`.

---

## Background the engineer needs

- **Run everything with `uv run`** (e.g. `uv run pytest …`, `uv run python manage.py …`). Never bare `python`/`pytest`.
- **All dev happens on the `dev` branch.** Never commit to `main`. Small, frequent commits.
- **Latvian** for all guardian/staff-facing strings. Keep the exact strings in this plan.
- **No `responses`/`pytest-mock`.** HTTP and enqueue spies use `unittest.mock` / `monkeypatch` (repo convention).
- **`Guardian` is a plain `models.Model`** (in `apps/members/models.py`) — it has **no `updated_at`**. When saving it with `update_fields`, do **not** include `updated_at`. `MembershipPlan`, `BillingRecord`, and the new `BillingInvoice` extend `TimeStampedModel` (have `created_at`/`updated_at`).
- Existing billing facts (Slice A): `BillingRecord` has `member`, `plan`, `season`, `final_amount`, `is_full_price`, `sibling_discount_percent_applied`, `payment_mode` (`PaymentMode.UPFRONT="upfront"` / `INSTALLMENTS="installments"`), `status` (`Status.DRAFT="draft"` / `CONFIRMED="confirmed"`). `apps/billing/services.py` has `derive_installment_schedule(plan, total) -> list[tuple[date, Decimal]]`.
- Test fixtures in `tests/billing/conftest.py`: `active_plan` (season `"2026/2027"`, `annual_amount` 300.00, `sibling_discount_percent` 50.00, `installment_count` 10, active), `guardian` (Anna Bērziņa, `anna@example.com`), `member` (Jānis Bērziņš, under `guardian`).

---

## File structure

| File | Responsibility |
|------|----------------|
| `fk_cesis_mms/settings.py` | Add `INVOICE_PROVIDER_MODE`, `INVOICE_NINJA_API_URL/KEY`, `INVOICE_NINJA_NUMBER_PREFIX`. |
| `apps/integrations/invoice_platform.py` (new) | Boundary: exception taxonomy, `ProductResult`/`ClientResult`/`InvoiceResult`, stub + dispatch. |
| `apps/integrations/invoice_ninja.py` (new) | Concrete provider: pure payload builders + HTTP (`X-Api-Token`), status→exception map, idempotency recovery. |
| `apps/members/models.py` | `Guardian.external_client_id`. |
| `apps/billing/models.py` | `MembershipPlan.external_product_id`; `BillingRecord.external_status` + `external_error_code`; new `BillingInvoice` model. |
| `apps/billing/services.py` | `membership_plan_product_key(plan)`, `materialize_installments(record)`. |
| `apps/billing/messages.py` | Invoice line label, sibling-discount note, product name, `get_invoice_error_message`, admin feedback strings. |
| `apps/integrations/tasks.py` | `push_billing_record` job, `enqueue_push_billing_record`, error classification. |
| `apps/billing/admin.py` | "Izrakstīt rēķinus (Invoice Ninja)" action; `external_status` display + readonly error. |

> **Note:** the per-plan "Sinhronizēt produktu" action from the spec is intentionally omitted — the push job ensures the product anyway (YAGNI). The design's `product_key` is a derived helper, not a DB column.

---

## Task 1: Settings + boundary module (taxonomy, dataclasses, stub dispatch)

**Files:**
- Modify: `fk_cesis_mms/settings.py` (after line 176, the DocuSeal block)
- Create: `apps/integrations/invoice_platform.py`
- Test: `tests/integrations/test_invoice_platform.py`

- [ ] **Step 1: Add settings**

In `fk_cesis_mms/settings.py`, immediately after the `DOCUSEAL_WEBHOOK_SECRET` line, add:

```python
# Invoicing integration (P6 Slice B — Invoice Ninja self-hosted).
INVOICE_PROVIDER_MODE = os.environ.get("INVOICE_PROVIDER_MODE") or "stub"
INVOICE_NINJA_API_URL = os.environ.get("INVOICE_NINJA_API_URL", "")
INVOICE_NINJA_API_KEY = os.environ.get("INVOICE_NINJA_API_KEY", "")
INVOICE_NINJA_NUMBER_PREFIX = os.environ.get("INVOICE_NINJA_NUMBER_PREFIX") or "MMS"
```

- [ ] **Step 2: Write the failing test**

Create `tests/integrations/test_invoice_platform.py`:

```python
import pytest
from django.test import override_settings


def test_stub_ensure_product_is_deterministic():
    from apps.integrations import invoice_platform

    class _Plan:
        pk = 7

    result = invoice_platform.ensure_product(_Plan())
    assert result.external_id == "stub-product-7"


def test_stub_create_invoice_is_deterministic():
    from apps.integrations import invoice_platform

    class _BI:
        pk = 42

    result = invoice_platform.create_invoice(record=object(), billing_invoice=_BI())
    assert result.external_id == "stub-invoice-42"


@override_settings(INVOICE_PROVIDER_MODE="bogus")
def test_unknown_mode_raises_config_error():
    from apps.integrations import invoice_platform

    with pytest.raises(invoice_platform.InvoicePlatformConfigError):
        invoice_platform.ensure_client(object())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_invoice_platform.py -v`
Expected: FAIL — `apps.integrations.invoice_platform` does not exist.

- [ ] **Step 4: Create the boundary module**

Create `apps/integrations/invoice_platform.py`:

```python
"""Invoicing boundary — stub + Invoice Ninja dispatch (P6 Slice B).

Mirrors apps/integrations/agreement_platform.py. The boundary owns the
exception taxonomy; the real provider (apps/integrations/invoice_ninja.py)
imports and raises these. Mode is settings.INVOICE_PROVIDER_MODE
("stub" default, "invoiceninja" in production).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


class InvoicePlatformError(Exception):
    """Base for all invoicing-platform errors."""


class InvoicePlatformConfigError(InvoicePlatformError):
    """Missing/invalid config or unknown provider mode — permanent."""


class InvoicePlatformAuthError(InvoicePlatformError):
    """Authentication failed (401/403) — permanent."""


class InvoicePlatformNotFoundError(InvoicePlatformError):
    """Resource not found (404) — permanent."""


class InvoicePlatformTransientError(InvoicePlatformError):
    """5xx / timeout / connection error — retryable."""


@dataclass(frozen=True)
class ProductResult:
    external_id: str


@dataclass(frozen=True)
class ClientResult:
    external_id: str


@dataclass(frozen=True)
class InvoiceResult:
    external_id: str


def _mode() -> str:
    return getattr(settings, "INVOICE_PROVIDER_MODE", "stub")


def ensure_product(plan) -> ProductResult:
    mode = _mode()
    if mode == "stub":
        return ProductResult(external_id=f"stub-product-{plan.pk}")
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.ensure_product(plan)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def ensure_client(guardian) -> ClientResult:
    mode = _mode()
    if mode == "stub":
        return ClientResult(external_id=f"stub-client-{guardian.pk}")
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.ensure_client(guardian)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def create_invoice(record, billing_invoice) -> InvoiceResult:
    mode = _mode()
    if mode == "stub":
        return InvoiceResult(external_id=f"stub-invoice-{billing_invoice.pk}")
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.create_invoice(record, billing_invoice)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_invoice_platform.py -v`
Expected: all PASS.

- [ ] **Step 6: Gate + commit**

Run: `uv run ruff check apps/integrations tests/integrations && uv run mypy apps/integrations`
Then:
```bash
git add fk_cesis_mms/settings.py apps/integrations/invoice_platform.py tests/integrations/test_invoice_platform.py
git commit -m "feat(invoicing): boundary taxonomy + stub dispatch + settings (P6 Slice B)"
```

---

## Task 2: Model changes + migration

**Files:**
- Modify: `apps/members/models.py` (`Guardian`)
- Modify: `apps/billing/models.py` (`MembershipPlan`, `BillingRecord`, new `BillingInvoice`)
- Create: migration(s) under `apps/billing/migrations/` and `apps/members/migrations/`
- Test: `tests/billing/test_billing_invoice_model.py`

- [ ] **Step 1: Write the failing test**

Create `tests/billing/test_billing_invoice_model.py`:

```python
import pytest
from decimal import Decimal
from datetime import date

pytestmark = pytest.mark.django_db


def test_guardian_and_plan_and_record_external_fields(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    # defaults exist and are empty
    assert guardian.external_client_id == ""
    assert active_plan.external_product_id == ""
    assert rec.external_status == ""
    assert rec.external_error_code == ""


def test_billing_invoice_unique_per_sequence(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice
    from django.db import IntegrityError

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1), amount=Decimal("30.00")
    )
    with pytest.raises(IntegrityError):
        BillingInvoice.objects.create(
            billing_record=rec, sequence=1, due_date=date(2026, 10, 1), amount=Decimal("30.00")
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_billing_invoice_model.py -v`
Expected: FAIL — fields/model do not exist.

- [ ] **Step 3: Add `Guardian.external_client_id`**

In `apps/members/models.py`, inside `class Guardian`, after the `address` field add:

```python
    external_client_id = models.CharField(max_length=64, blank=True, default="")
```

- [ ] **Step 4: Add plan + record fields and the `BillingInvoice` model**

In `apps/billing/models.py`, inside `class MembershipPlan`, after `is_active` add:

```python
    external_product_id = models.CharField(max_length=64, blank=True, default="")
```

Inside `class BillingRecord`, after the `status` field (before `class Meta`) add:

```python
    external_status = models.CharField(max_length=16, blank=True, default="")
    external_error_code = models.CharField(max_length=64, blank=True, default="")
```

At the end of `apps/billing/models.py` add the new model:

```python
class BillingInvoice(TimeStampedModel):
    """One Invoice Ninja invoice per installment of a BillingRecord (upfront =
    a single row). Materialized at push time from derive_installment_schedule;
    holds the external invoice id + sync status (payment status arrives in
    Slice C)."""

    billing_record = models.ForeignKey(
        BillingRecord, on_delete=models.CASCADE, related_name="invoices"
    )
    sequence = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)

    external_invoice_id = models.CharField(max_length=64, blank=True, default="")
    external_status = models.CharField(max_length=16, blank=True, default="")
    external_error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["billing_record", "sequence"],
                name="one_invoice_per_record_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.billing_record_id} #{self.sequence} — {self.amount}"
```

- [ ] **Step 5: Make migrations**

Run: `uv run python manage.py makemigrations billing members`
Expected: creates a billing migration (plan/record fields + `BillingInvoice`) and a members migration (`Guardian.external_client_id`).

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_billing_invoice_model.py -v`
Expected: all PASS.

- [ ] **Step 7: Gate + commit**

Run: `uv run ruff check apps/billing apps/members tests/billing && uv run mypy apps/billing apps/members`
Then:
```bash
git add apps/members/models.py apps/billing/models.py apps/billing/migrations apps/members/migrations tests/billing/test_billing_invoice_model.py
git commit -m "feat(billing): external sync fields + BillingInvoice model (P6 Slice B)"
```

---

## Task 3: Latvian copy + error-message map

**Files:**
- Modify: `apps/billing/messages.py`
- Test: `tests/billing/test_invoice_messages.py`

- [ ] **Step 1: Write the failing test**

Create `tests/billing/test_invoice_messages.py`:

```python
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, full_price):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        is_full_price=full_price,
        sibling_discount_percent_applied=Decimal("0.00") if full_price else Decimal("50.00"),
    )


def test_invoice_line_label(active_plan, guardian):
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=True)
    assert messages.invoice_line_label(rec) == "Biedra maksa — Jānis — 2026/2027"


def test_sibling_discount_note_uses_percent(active_plan, guardian):
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=False)
    assert messages.sibling_discount_note(rec) == "Ietverta 50% atlaide"


def test_product_name(active_plan):
    from apps.billing import messages

    assert messages.product_name(active_plan) == "Biedra maksa 2026/2027"


def test_error_message_fallback():
    from apps.billing import messages

    assert messages.get_invoice_error_message("auth_failed").startswith("Invoice Ninja")
    assert messages.get_invoice_error_message("totally-unknown") == messages._INVOICE_GENERIC
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_invoice_messages.py -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Extend `apps/billing/messages.py`**

Append to `apps/billing/messages.py`:

```python
def invoice_line_label(record) -> str:
    return f"Biedra maksa — {record.member.full_name} — {record.season}"


def sibling_discount_note(record) -> str:
    percent = int(record.sibling_discount_percent_applied)
    return f"Ietverta {percent}% atlaide"


def product_name(plan) -> str:
    return f"Biedra maksa {plan.season}"


_INVOICE_GENERIC = "Radās kļūda saziņā ar Invoice Ninja. Mēģiniet vēlreiz."

_INVOICE_MESSAGES: dict[str, str] = {
    "auth_failed": "Invoice Ninja autentifikācija neizdevās. Pārbaudiet API atslēgu.",
    "misconfigured": "Invoice Ninja konfigurācija nav pilnīga. Sazinieties ar administratoru.",
    "not_found": "Invoice Ninja resurss nav atrasts.",
    "provider_error": _INVOICE_GENERIC,
    "unavailable": "Invoice Ninja pašlaik nav pieejams. Mēģiniet vēlāk.",
}


def get_invoice_error_message(error_code: str) -> str:
    """Latvian copy for a stored external_error_code, generic fallback."""
    return _INVOICE_MESSAGES.get(error_code, _INVOICE_GENERIC)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_invoice_messages.py -v`
Expected: all PASS.

- [ ] **Step 5: Gate + commit**

Run: `uv run ruff check apps/billing tests/billing && uv run mypy apps/billing`
Then:
```bash
git add apps/billing/messages.py tests/billing/test_invoice_messages.py
git commit -m "feat(billing): Latvian invoice copy + error-message map (P6 Slice B)"
```

---

## Task 4: `product_key` helper + `materialize_installments`

**Files:**
- Modify: `apps/billing/services.py`
- Test: `tests/billing/test_materialize_installments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/billing/test_materialize_installments.py`:

```python
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, payment_mode, final):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal(final),
        payment_mode=payment_mode,
    )


def test_product_key_from_season(active_plan):
    from apps.billing.services import membership_plan_product_key

    assert membership_plan_product_key(active_plan) == "biedra-maksa-2026-2027"


def test_installments_create_ten_rows(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.billing.services import materialize_installments

    rec = _record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS, "300.00")
    rows = materialize_installments(rec)
    assert len(rows) == 10
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10
    assert sum(r.amount for r in rows) == Decimal("300.00")
    assert [r.sequence for r in rows] == list(range(1, 11))


def test_upfront_creates_single_row(active_plan, guardian):
    from apps.billing.models import BillingRecord
    from apps.billing.services import materialize_installments

    rec = _record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT, "300.00")
    rows = materialize_installments(rec)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("300.00")


def test_materialize_is_idempotent(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.billing.services import materialize_installments

    rec = _record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS, "300.00")
    materialize_installments(rec)
    materialize_installments(rec)
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_materialize_installments.py -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Add the helpers to `apps/billing/services.py`**

Append to `apps/billing/services.py`:

```python
def membership_plan_product_key(plan) -> str:
    """Deterministic Invoice Ninja product_key for a plan (no stored column,
    so it can never drift): season "2026/2027" -> "biedra-maksa-2026-2027"."""
    slug = plan.season.replace("/", "-")
    return f"biedra-maksa-{slug}"


def materialize_installments(record):
    """Create the BillingInvoice rows for a record from the snapshotted
    final_amount, idempotently. Upfront -> one row due on the first
    installment date; installments -> derive_installment_schedule rows."""
    from apps.billing.models import BillingInvoice, BillingRecord

    existing = list(record.invoices.order_by("sequence"))
    if existing:
        return existing

    schedule = derive_installment_schedule(record.plan, record.final_amount)
    if record.payment_mode == BillingRecord.PaymentMode.UPFRONT:
        first_due = schedule[0][0]
        schedule = [(first_due, record.final_amount)]

    rows = [
        BillingInvoice.objects.create(
            billing_record=record, sequence=i, due_date=due, amount=amount
        )
        for i, (due, amount) in enumerate(schedule, start=1)
    ]
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_materialize_installments.py -v`
Expected: all PASS.

- [ ] **Step 5: Gate + commit**

Run: `uv run ruff check apps/billing tests/billing && uv run mypy apps/billing`
Then:
```bash
git add apps/billing/services.py tests/billing/test_materialize_installments.py
git commit -m "feat(billing): product_key helper + materialize_installments (P6 Slice B)"
```

---

## Task 5: Invoice Ninja provider (builders + HTTP + idempotency)

**Files:**
- Create: `apps/integrations/invoice_ninja.py`
- Test: `tests/integrations/test_invoice_ninja_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/test_invoice_ninja_provider.py`:

```python
import pytest
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import override_settings

pytestmark = pytest.mark.django_db

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
    INVOICE_NINJA_NUMBER_PREFIX="MMS",
)


def _record(active_plan, guardian, full_price=True):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    guardian.external_client_id = "client-1"
    guardian.save(update_fields=["external_client_id"])
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        is_full_price=full_price,
        sibling_discount_percent_applied=Decimal("0.00") if full_price else Decimal("50.00"),
    )
    bi = BillingInvoice.objects.create(
        billing_record=rec, sequence=3, due_date=date(2026, 11, 1), amount=Decimal("30.00")
    )
    return rec, bi


@override_settings(**INVOICE_NINJA)
def test_build_invoice_body_shape(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    body = invoice_ninja._build_invoice_body(rec, bi)
    assert body["client_id"] == "client-1"
    assert body["number"] == "MMS-{}-3".format(rec.pk)
    assert body["due_date"] == "2026-11-01"
    line = body["line_items"][0]
    assert line["product_key"] == "biedra-maksa-2026-2027"
    assert line["cost"] == "30.00"
    assert line["notes"] == "Biedra maksa — Jānis — 2026/2027"


@override_settings(**INVOICE_NINJA)
def test_sibling_note_appended_for_discounted(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian, full_price=False)
    line = invoice_ninja._build_invoice_body(rec, bi)["line_items"][0]
    assert "Ietverta 50% atlaide" in line["notes"]


@override_settings(**INVOICE_NINJA)
def test_create_invoice_posts_and_returns_id(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    fake = SimpleNamespace(status_code=200, json=lambda: {"id": "inv-99"}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake) as m:
        result = invoice_ninja.create_invoice(rec, bi)
    assert result.external_id == "inv-99"
    # X-Api-Token header sent
    assert m.call_args.kwargs["headers"]["X-Api-Token"] == "secret-token"


@override_settings(**INVOICE_NINJA)
def test_auth_error_maps_to_auth_exception(active_plan, guardian):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    rec, bi = _record(active_plan, guardian)
    fake = SimpleNamespace(status_code=401, json=lambda: {}, text="nope")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformAuthError):
            invoice_ninja.create_invoice(rec, bi)


@override_settings(**INVOICE_NINJA)
def test_timeout_maps_to_transient(active_plan, guardian):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    rec, bi = _record(active_plan, guardian)
    with patch("apps.integrations.invoice_ninja.requests.request", side_effect=requests.Timeout("t")):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.create_invoice(rec, bi)


@override_settings(**INVOICE_NINJA)
def test_duplicate_number_recovers_existing_id(active_plan, guardian):
    """A 4xx 'number already exists' on create must not error — the provider
    looks the invoice up by number and returns its id."""
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    post_resp = SimpleNamespace(
        status_code=422, json=lambda: {}, text="invoice number has already been taken"
    )
    lookup_resp = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"id": "inv-existing"}]}, text=""
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[post_resp, lookup_resp],
    ):
        result = invoice_ninja.create_invoice(rec, bi)
    assert result.external_id == "inv-existing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_invoice_ninja_provider.py -v`
Expected: FAIL — `apps.integrations.invoice_ninja` does not exist.

- [ ] **Step 3: Create the provider**

Create `apps/integrations/invoice_ninja.py`:

```python
"""Invoice Ninja self-hosted provider — HTTP transport + payload builders.

Raises the boundary exception taxonomy from
apps.integrations.invoice_platform directly (no second mapping layer).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.utils import timezone

from apps.billing import messages
from apps.billing.services import membership_plan_product_key
from apps.integrations.invoice_platform import (
    ClientResult,
    InvoicePlatformAuthError,
    InvoicePlatformConfigError,
    InvoicePlatformNotFoundError,
    InvoicePlatformTransientError,
    InvoiceResult,
    ProductResult,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


def _require_config() -> tuple[str, str]:
    api_url = getattr(settings, "INVOICE_NINJA_API_URL", "")
    api_key = getattr(settings, "INVOICE_NINJA_API_KEY", "")
    if not api_url or not api_key:
        raise InvoicePlatformConfigError("Invoice Ninja API URL/key not configured")
    return api_url.rstrip("/"), api_key


def _number(record, sequence: int) -> str:
    prefix = getattr(settings, "INVOICE_NINJA_NUMBER_PREFIX", "MMS") or "MMS"
    return f"{prefix}-{record.pk}-{sequence}"


def _build_line_item(record, billing_invoice) -> dict:
    notes = messages.invoice_line_label(record)
    if not record.is_full_price:
        notes = f"{notes}  {messages.sibling_discount_note(record)}"
    return {
        "product_key": membership_plan_product_key(record.plan),
        "notes": notes,
        "cost": str(billing_invoice.amount),
        "quantity": 1,
    }


def _build_invoice_body(record, billing_invoice) -> dict:
    return {
        "client_id": record.member.guardian.external_client_id,
        "number": _number(record, billing_invoice.sequence),
        "date": timezone.now().date().isoformat(),
        "due_date": billing_invoice.due_date.isoformat(),
        "line_items": [_build_line_item(record, billing_invoice)],
    }


def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    headers = {"X-Api-Token": api_key, **kwargs.pop("headers", {})}
    try:
        resp = requests.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
    except requests.Timeout as exc:
        raise InvoicePlatformTransientError(f"timeout: {exc}") from exc
    except requests.RequestException as exc:
        raise InvoicePlatformTransientError(f"connection error: {exc}") from exc

    status = resp.status_code
    if status in (401, 403):
        raise InvoicePlatformAuthError(f"auth failed: {status}")
    if status == 404:
        raise InvoicePlatformNotFoundError(f"not found: {url}")
    if status >= 500:
        raise InvoicePlatformTransientError(f"server error: {status}")
    return resp


def ensure_product(plan) -> ProductResult:
    api_url, api_key = _require_config()
    body = {
        "product_key": membership_plan_product_key(plan),
        "notes": messages.product_name(plan),
        "price": str(plan.annual_amount),
    }
    resp = _request("POST", f"{api_url}/products", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"product create rejected: {resp.status_code} {resp.text}")
    data = resp.json().get("data", resp.json())
    return ProductResult(external_id=str(data.get("id", "")))


def ensure_client(guardian) -> ClientResult:
    api_url, api_key = _require_config()
    body = {
        "name": guardian.full_name,
        "contacts": [{"first_name": guardian.full_name, "email": guardian.email}],
    }
    resp = _request("POST", f"{api_url}/clients", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"client create rejected: {resp.status_code} {resp.text}")
    data = resp.json().get("data", resp.json())
    return ClientResult(external_id=str(data.get("id", "")))


def _find_invoice_id_by_number(api_url: str, api_key: str, number: str) -> str:
    resp = _request("GET", f"{api_url}/invoices?number={number}", api_key)
    rows = resp.json().get("data", [])
    if rows:
        return str(rows[0].get("id", ""))
    return ""


def create_invoice(record, billing_invoice) -> InvoiceResult:
    api_url, api_key = _require_config()
    body = _build_invoice_body(record, billing_invoice)
    resp = _request("POST", f"{api_url}/invoices", api_key, json=body)
    if resp.status_code >= 400:
        # Idempotency: a duplicate invoice number means a prior attempt created
        # it but we crashed before storing the id. Recover by lookup.
        if "number" in resp.text.lower():
            existing = _find_invoice_id_by_number(api_url, api_key, body["number"])
            if existing:
                return InvoiceResult(external_id=existing)
        raise InvoicePlatformConfigError(f"invoice create rejected: {resp.status_code} {resp.text}")
    data = resp.json().get("data", resp.json())
    return InvoiceResult(external_id=str(data.get("id", "")))
```

> The provider tolerates IN responses that wrap the entity in `{"data": {...}}` (real IN) or return it bare (test stubs) via `resp.json().get("data", resp.json())`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_invoice_ninja_provider.py -v`
Expected: all PASS.

- [ ] **Step 5: Gate + commit**

Run: `uv run ruff check apps/integrations tests/integrations && uv run mypy apps/integrations`
Then:
```bash
git add apps/integrations/invoice_ninja.py tests/integrations/test_invoice_ninja_provider.py
git commit -m "feat(invoicing): Invoice Ninja provider — builders, HTTP, idempotency (P6 Slice B)"
```

---

## Task 6: Push job + enqueue helper + error classification

**Files:**
- Modify: `apps/integrations/tasks.py`
- Test: `tests/billing/test_push_billing_record.py`

- [ ] **Step 1: Write the failing test**

Create `tests/billing/test_push_billing_record.py`:

```python
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _confirmed_record(active_plan, guardian, payment_mode):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=payment_mode, status=BillingRecord.Status.CONFIRMED,
    )


def test_push_creates_invoices_and_marks_synced(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations.tasks import push_billing_record

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS)
    push_billing_record(rec.pk)

    rec.refresh_from_db()
    guardian.refresh_from_db()
    active_plan.refresh_from_db()
    assert rec.external_status == "synced"
    assert active_plan.external_product_id == f"stub-product-{active_plan.pk}"
    assert guardian.external_client_id == f"stub-client-{guardian.pk}"
    rows = BillingInvoice.objects.filter(billing_record=rec)
    assert rows.count() == 10
    assert all(r.external_invoice_id and r.external_status == "created" for r in rows)


def test_push_is_idempotent(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations.tasks import push_billing_record

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS)
    push_billing_record(rec.pk)
    push_billing_record(rec.pk)
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10


def test_transient_failure_marks_failed_and_raises(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT)

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformTransientError("down")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    with pytest.raises(tasks.RetryableInvoiceError):
        tasks.push_billing_record(rec.pk)
    rec.refresh_from_db()
    assert rec.external_status == "failed"
    assert rec.external_error_code == "unavailable"


def test_terminal_failure_marks_failed_no_raise(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT)

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformAuthError("401")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    tasks.push_billing_record(rec.pk)  # must NOT raise
    rec.refresh_from_db()
    assert rec.external_status == "failed"
    assert rec.external_error_code == "auth_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_push_billing_record.py -v`
Expected: FAIL — `push_billing_record` / `RetryableInvoiceError` not defined.

- [ ] **Step 3: Add the job to `apps/integrations/tasks.py`**

At the end of `apps/integrations/tasks.py`, append:

```python
# ---------------------------------------------------------------------------
# Invoicing (Invoice Ninja) push pipeline — P6 Slice B
# ---------------------------------------------------------------------------


class RetryableInvoiceError(Exception):
    """Raised for transient invoicing failures so django-q2 retries."""


_INVOICE_ERROR_CODES: dict[type[Exception], tuple[str, bool]] = {
    invoice_platform.InvoicePlatformTransientError: ("unavailable", True),
    invoice_platform.InvoicePlatformAuthError: ("auth_failed", False),
    invoice_platform.InvoicePlatformConfigError: ("misconfigured", False),
    invoice_platform.InvoicePlatformNotFoundError: ("not_found", False),
}


def _classify_invoice_error(exc: Exception) -> tuple[str, bool]:
    for exc_type, mapping in _INVOICE_ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return mapping
    return ("provider_error", False)


def enqueue_push_billing_record(record_id: int) -> None:
    try:
        async_task("apps.integrations.tasks.push_billing_record", record_id)
    except RetryableInvoiceError:
        return


def push_billing_record(record_id: int) -> None:
    from apps.billing.models import BillingRecord
    from apps.billing.services import materialize_installments

    try:
        record = BillingRecord.objects.select_related(
            "plan", "member__guardian"
        ).get(pk=record_id)
    except BillingRecord.DoesNotExist:
        return
    if record.status != BillingRecord.Status.CONFIRMED:
        return

    record.external_status = "pending"
    record.external_error_code = ""
    record.save(update_fields=["external_status", "external_error_code", "updated_at"])

    # Steps 1-2: ensure product + client (idempotent via stored external ids).
    try:
        plan = record.plan
        if not plan.external_product_id:
            plan.external_product_id = invoice_platform.ensure_product(plan).external_id
            plan.save(update_fields=["external_product_id", "updated_at"])
        guardian = record.member.guardian
        if not guardian.external_client_id:
            # Guardian has no updated_at — do not include it in update_fields.
            guardian.external_client_id = invoice_platform.ensure_client(guardian).external_id
            guardian.save(update_fields=["external_client_id"])
    except Exception as exc:
        code, retry = _classify_invoice_error(exc)
        record.external_status = "failed"
        record.external_error_code = code
        record.save(update_fields=["external_status", "external_error_code", "updated_at"])
        if retry:
            raise RetryableInvoiceError(code) from exc
        return

    # Step 3: materialize installment rows (idempotent).
    rows = materialize_installments(record)

    # Step 4: create one invoice per row lacking an external id.
    failed_code = ""
    for billing_invoice in rows:
        if billing_invoice.external_invoice_id:
            continue
        try:
            result = invoice_platform.create_invoice(record, billing_invoice)
        except Exception as exc:
            code, retry = _classify_invoice_error(exc)
            billing_invoice.external_status = "failed"
            billing_invoice.external_error_code = code
            billing_invoice.save(
                update_fields=["external_status", "external_error_code", "updated_at"]
            )
            if retry:
                record.external_status = "failed"
                record.external_error_code = code
                record.save(
                    update_fields=["external_status", "external_error_code", "updated_at"]
                )
                raise RetryableInvoiceError(code) from exc
            failed_code = failed_code or code
            continue
        billing_invoice.external_invoice_id = result.external_id
        billing_invoice.external_status = "created"
        billing_invoice.external_error_code = ""
        billing_invoice.save(
            update_fields=[
                "external_invoice_id",
                "external_status",
                "external_error_code",
                "updated_at",
            ]
        )

    # Step 5: roll up.
    if failed_code:
        record.external_status = "failed"
        record.external_error_code = failed_code
    else:
        record.external_status = "synced"
        record.external_error_code = ""
    record.save(update_fields=["external_status", "external_error_code", "updated_at"])
```

Also add this import near the top of `apps/integrations/tasks.py`, alongside the existing `from apps.integrations import agreement_platform`:

```python
from apps.integrations import invoice_platform
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_push_billing_record.py -v`
Expected: all PASS.

- [ ] **Step 5: Gate + commit**

Run: `uv run ruff check apps/integrations tests/billing && uv run mypy apps/integrations`
Then:
```bash
git add apps/integrations/tasks.py tests/billing/test_push_billing_record.py
git commit -m "feat(invoicing): push_billing_record job + error classification (P6 Slice B)"
```

---

## Task 7: Admin push action + sync status display

**Files:**
- Modify: `apps/billing/admin.py`
- Test: `tests/billing/test_billing_admin_push.py`

- [ ] **Step 1: Write the failing test**

Create `tests/billing/test_billing_admin_push.py`:

```python
import pytest
from decimal import Decimal
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, status):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=status,
    )


def test_action_enqueues_only_confirmed(active_plan, guardian):
    from django.contrib.admin.sites import AdminSite
    from apps.billing.admin import BillingRecordAdmin
    from apps.billing.models import BillingRecord

    confirmed = _record(active_plan, guardian, BillingRecord.Status.CONFIRMED)
    draft = _record(active_plan, guardian, BillingRecord.Status.DRAFT)

    admin = BillingRecordAdmin(BillingRecord, AdminSite())
    request = type("R", (), {})()
    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue, \
         patch.object(admin, "message_user"):
        admin.push_to_invoice_ninja(request, BillingRecord.objects.all())

    called_ids = {c.args[0] for c in enqueue.call_args_list}
    assert called_ids == {confirmed.pk}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_billing_admin_push.py -v`
Expected: FAIL — `push_to_invoice_ninja` not defined.

- [ ] **Step 3: Extend `apps/billing/admin.py`**

Replace the file with (additions: `messages` import, `external_status` in `list_display`/`list_filter`/`readonly_fields`, the new action in `actions`, the `push_to_invoice_ninja` method):

```python
"""Django admin for the billing app — plan config + draft-record review."""

from django.contrib import admin, messages

from apps.billing.models import BillingRecord, MembershipPlan
from apps.billing.services import recompute_billing_record


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name", "season", "annual_amount", "sibling_discount_percent",
        "installment_count", "first_installment_month", "is_active",
    )
    list_filter = ("season", "is_active")


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = (
        "member", "guardian_name", "season", "final_amount",
        "is_full_price", "payment_mode", "status", "external_status",
    )
    list_filter = ("season", "status", "payment_mode", "is_full_price", "external_status")
    search_fields = ("member__full_name", "member__guardian__full_name")
    readonly_fields = (
        "member", "plan", "agreement", "season", "base_amount", "is_full_price",
        "sibling_discount_percent_applied", "discount_amount", "final_amount",
        "payment_mode", "full_price_opt_out", "external_status", "external_error_code",
        "created_at", "updated_at",
    )
    fields = readonly_fields + (
        "manual_amount_override", "manual_override_reason", "status",
    )
    actions = ("recompute_from_plan", "push_to_invoice_ninja")

    @admin.display(description="Vecāks")
    def guardian_name(self, obj):
        return obj.member.guardian.full_name

    @admin.action(description="Pārrēķināt no plāna")
    def recompute_from_plan(self, request, queryset):
        count = 0
        for record in queryset:
            if record.status == BillingRecord.Status.DRAFT:
                recompute_billing_record(record)
                count += 1
        self.message_user(request, f"Pārrēķināti {count} ieraksti.")

    @admin.action(description="Izrakstīt rēķinus (Invoice Ninja)")
    def push_to_invoice_ninja(self, request, queryset):
        from apps.integrations.tasks import enqueue_push_billing_record

        pushed = 0
        skipped = 0
        for record in queryset:
            if record.status != BillingRecord.Status.CONFIRMED:
                skipped += 1
                continue
            enqueue_push_billing_record(record.pk)
            pushed += 1
        if skipped:
            self.message_user(
                request,
                f"Izrakstīti {pushed} rēķini. Izlaisti {skipped} (vispirms apstipriniet).",
                level=messages.WARNING,
            )
        else:
            self.message_user(request, f"Izrakstīti {pushed} rēķini.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_billing_admin_push.py -v`
Expected: PASS.

- [ ] **Step 5: Gate + commit**

Run: `uv run ruff check apps/billing tests/billing && uv run mypy apps/billing`
Then:
```bash
git add apps/billing/admin.py tests/billing/test_billing_admin_push.py
git commit -m "feat(billing): admin push-to-Invoice-Ninja action + sync status (P6 Slice B)"
```

---

## Task 8: Full verification gate + docs

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/milestones.md`

- [ ] **Step 1: Run the full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all green. Fix any findings introduced by earlier tasks (e.g. unused imports, type hints) and re-run. Record the exact pass count.

- [ ] **Step 2: Update `AGENTS.md`**

Under the Current Status block, add a "P6 Slice B delivered" entry summarizing: new `apps/integrations/invoice_platform.py` boundary + `invoice_ninja.py` provider (stub/invoiceninja on `INVOICE_PROVIDER_MODE`); `Guardian.external_client_id`, `MembershipPlan.external_product_id`, `BillingRecord.external_status`/`external_error_code`, new `BillingInvoice` model; `materialize_installments` + `membership_plan_product_key`; `push_billing_record` django-q job (ensure product → ensure client → materialize → create N invoices → roll up; deterministic `{INVOICE_NINJA_NUMBER_PREFIX}-{record}-{seq}` numbers for idempotency, duplicate-number recovery); `BillingRecordAdmin` "Izrakstīt rēķinus" admin-confirmed action; Latvian invoice copy + error map. Note the verification counts. Note payment read-back/webhooks/void-regenerate remain Slice C.

- [ ] **Step 3: Update `docs/milestones.md`**

Under P6, mark Slice B delivered and note Slice C (payment read-back + sync health) remains.

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: P6 Slice B delivered — Invoice Ninja push integration"
```

---

## Final verification checklist

- [ ] `uv run pytest -q` — all green (new invoicing tests + no regressions).
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run mypy .` — clean.
- [ ] Manual LAN smoke at `http://192.168.3.245:8000` (provider mode `stub` unless a real IN instance is configured):
  - Confirm a `BillingRecord`, run the admin "Izrakstīt rēķinus (Invoice Ninja)" action → `external_status` becomes `synced`; `BillingInvoice` rows created (10 for the installment plan, 1 for upfront).
  - Re-run the action → no duplicate rows (idempotent).
  - A draft record is skipped with the Latvian "vispirms apstipriniet" warning.
  - With `INVOICE_PROVIDER_MODE=invoiceninja` + real creds: a guardian appears as an IN client, the plan as an IN product, and one IN invoice per installment with the `{PREFIX}-{record}-{seq}` number and the Latvian line label.
