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
