"""Billing domain models — local membership plan + per-member billing record.

Slice A is local only: no Invoice Ninja calls. The Invoice Ninja sync fields
arrive in Slice B.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class PaymentStatus(models.TextChoices):
    UNPAID = "unpaid", "Nav apmaksāts"
    PARTIAL = "partial", "Daļēji apmaksāts"
    PAID = "paid", "Apmaksāts"


class MembershipPlan(TimeStampedModel):
    """Staff-editable billing configuration. Exactly one row is expected to be
    active at a time (enforced by convention + the active-plan lookup, not a DB
    constraint, so staff can stage a next-season plan as inactive)."""

    name = models.CharField(max_length=255)
    season = models.CharField(max_length=16)
    currency = models.CharField(max_length=8, default="EUR")
    annual_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("300.00")
    )
    sibling_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    installment_count = models.PositiveSmallIntegerField(default=1)
    first_installment_month = models.PositiveSmallIntegerField(default=9)
    payment_due_day = models.PositiveSmallIntegerField(
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Mēneša diena, kad iestājas maksājuma termiņš (1–31).",
    )
    skip_months = models.CharField(
        max_length=32,
        default="7,12",
        blank=True,
        help_text='Mēneši (1–12) bez rēķina, ar komatu, piem. "7,12" (jūlijs, decembris).',
    )
    is_active = models.BooleanField(default=False)
    external_product_id = models.CharField(max_length=64, blank=True, default="")

    @property
    def skip_months_list(self) -> list[int]:
        months: set[int] = set()
        for part in self.skip_months.split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= 12:
                months.add(int(part))
        return sorted(months)

    def __str__(self) -> str:
        return str(self.name)


class BillingRecord(TimeStampedModel):
    """One per (member, season). Money fields are snapshotted at creation so a
    later plan edit never silently mutates an existing draft. `final_amount`
    equals `manual_amount_override` when an admin sets one, else
    `base_amount - discount_amount`."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Sagatavots"
        CONFIRMED = "confirmed", "Apstiprināts"

    class PaymentMode(models.TextChoices):
        UPFRONT = "upfront", "Vienā maksājumā"
        INSTALLMENTS = "installments", "Pa daļām"

    member = models.ForeignKey(
        "members.Member", on_delete=models.PROTECT, related_name="billing_records"
    )
    plan = models.ForeignKey(
        MembershipPlan, on_delete=models.PROTECT, related_name="billing_records"
    )
    agreement = models.ForeignKey(
        "agreements.Agreement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="billing_records",
    )
    season = models.CharField(max_length=16)

    base_amount = models.DecimalField(max_digits=8, decimal_places=2)
    is_full_price = models.BooleanField(default=True)
    sibling_discount_percent_applied = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    discount_amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    final_amount = models.DecimalField(max_digits=8, decimal_places=2)

    payment_mode = models.CharField(
        max_length=16, choices=PaymentMode.choices, default=PaymentMode.INSTALLMENTS
    )
    full_price_opt_out = models.BooleanField(default=False)

    manual_amount_override = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    manual_override_reason = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    external_status = models.CharField(max_length=16, blank=True, default="")
    external_error_code = models.CharField(max_length=64, blank=True, default="")
    payment_status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, blank=True, default=""
    )
    payment_synced_at = models.DateTimeField(null=True, blank=True)
    payment_error_code = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "season"],
                name="one_billing_record_per_member_per_season",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.member} — {self.season} — {self.final_amount} {self.plan.currency}"


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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["billing_record", "sequence"],
                name="one_invoice_per_record_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.billing_record_id} #{self.sequence} — {self.amount}"
