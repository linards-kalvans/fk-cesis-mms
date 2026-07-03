"""Latvian copy for the billing domain (Slice A: admin-facing summaries)."""

from __future__ import annotations

PAYMENT_MODE_LABELS = {
    "upfront": "Vienā maksājumā",
    "installments": "Pa daļām",
}

PAYMENT_STATUS_LABELS = {
    "": "—",
    "unpaid": "Nav apmaksāts",
    "partial": "Daļēji apmaksāts",
    "paid": "Apmaksāts",
}


def invoice_line_label(record) -> str:
    return f"Biedra maksa — {record.member.full_name} — {record.season}"


def sibling_discount_note(record) -> str:
    percent = f"{record.sibling_discount_percent_applied:.2f}".rstrip("0").rstrip(".")
    return f"Ietverta {percent}% atlaide"


def invoice_public_note(record) -> str:
    """Per-member, per-invoice detail shown on the Invoice Ninja invoice
    (public_notes). Kept off the line item so it never pollutes the shared
    catalog product via Invoice Ninja's "Update Products" behaviour."""
    note = invoice_line_label(record)
    if not record.is_full_price:
        note = f"{note}  {sibling_discount_note(record)}"
    return note


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
