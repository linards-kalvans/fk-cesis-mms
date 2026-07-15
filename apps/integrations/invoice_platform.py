"""Invoicing boundary — stub + Invoice Ninja dispatch (P6 Slice B).

Mirrors apps/integrations/agreement_platform.py. The boundary owns the
exception taxonomy; the real provider (apps/integrations/invoice_ninja.py)
imports and raises these. Mode is settings.INVOICE_PROVIDER_MODE
("stub" default, "invoiceninja" in production).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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


@dataclass(frozen=True)
class PaymentResult:
    external_invoice_id: str
    payment_status: str
    amount: Decimal
    paid_to_date: Decimal
    balance: Decimal | None
    last_payment_date: date | None
    # P12: parent-safe invoice URL. Empty string when the provider response
    # does not contain a known safe URL field — never synthesized from base.
    external_url: str = ""


@dataclass(frozen=True)
class CreditResult:
    external_id: str
    external_status: str


@dataclass(frozen=True)
class CreditApplyResult:
    applied: bool
    external_status: str


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
            external_url=f"https://stub.invalid/invoices/{external_invoice_id}",
        )
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.fetch_invoice_payment(external_invoice_id)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def email_invoice(external_invoice_id: str) -> None:
    mode = _mode()
    if mode == "stub":
        return None
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.email_invoice(external_invoice_id)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def archive_invoice(external_invoice_id: str) -> None:
    mode = _mode()
    if mode == "stub":
        return None
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.archive_invoice(external_invoice_id)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def cancel_invoice(external_invoice_id: str, reason: str) -> None:
    mode = _mode()
    if mode == "stub":
        return None
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.cancel_invoice(external_invoice_id, reason)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def create_credit_note(adjustment) -> CreditResult:
    mode = _mode()
    if mode == "stub":
        return CreditResult(
            external_id=f"stub-credit-{adjustment.pk}",
            external_status="created",
        )
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.create_credit_note(adjustment)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")


def apply_credit_to_invoice(credit_id: str, invoice_id: str, amount: Decimal) -> CreditApplyResult:
    mode = _mode()
    if mode == "stub":
        return CreditApplyResult(applied=True, external_status="applied")
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.apply_credit_to_invoice(credit_id, invoice_id, amount)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")
