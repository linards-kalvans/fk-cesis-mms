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
    return f"Dalības maksa — {record.member.full_name} — {record.season}"


def sibling_discount_note(record) -> str:
    percent = f"{record.sibling_discount_percent_applied:.2f}".rstrip("0").rstrip(".")
    return f"Ietverta {percent}% atlaide"


# Latvian accusative month forms for the per-installment period line
# (e.g. "Maksājums par 2027. gada septembri").
_INSTALLMENT_MONTH_ACCUSATIVE = {
    1: "janvāri",
    2: "februāri",
    3: "martu",
    4: "aprīli",
    5: "maiju",
    6: "jūniju",
    7: "jūliju",
    8: "augustu",
    9: "septembri",
    10: "oktobri",
    11: "novembri",
    12: "decembri",
}


def _normalize_season(season: str) -> str:
    """Normalize a season to exactly one trailing dot per part: '2027/2028',
    '2027./2028.' and '2027./2028..' all become '2027./2028.'."""
    return "/".join(part.rstrip(".") + "." for part in season.split("/"))


def _installment_period_line(billing_invoice) -> str:
    due = billing_invoice.due_date
    return f"Maksājums par {due.year}. gada {_INSTALLMENT_MONTH_ACCUSATIVE[due.month]}"


def _upfront_period_line(record) -> str:
    return f"Maksājums par {_normalize_season(record.season)} gada sezonu"


def invoice_public_note(record, billing_invoice) -> str:
    """Per-member, per-invoice detail shown on the Invoice Ninja invoice
    (public_notes). Kept off the line item so it never pollutes the shared
    catalog product via Invoice Ninja's "Update Products" behaviour.

    Newline-separated lines:
      heading — <member full name> — <record season>
      period line — per-installment due_date (installments) or normalized
      season (upfront); sibling-discount line only when the record is
      discounted.
    """
    lines = [
        f"Futbola treniņu un spēļu nodrošināšana — {record.member.full_name} — {record.season}"
    ]
    if record.payment_mode == record.PaymentMode.UPFRONT:
        lines.append(_upfront_period_line(record))
    else:
        lines.append(_installment_period_line(billing_invoice))
    if not record.is_full_price:
        lines.append(sibling_discount_note(record))
    return "\n".join(lines)


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
