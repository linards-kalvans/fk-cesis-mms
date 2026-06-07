"""Billing domain models — local membership plan + per-member billing record.

Slice A is local only: no Invoice Ninja calls. The Invoice Ninja sync fields
arrive in Slice B.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from apps.core.models import TimeStampedModel


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
    is_active = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name


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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "season"],
                name="one_billing_record_per_member_per_season",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.member} — {self.season} — {self.final_amount} {self.plan.currency}"
