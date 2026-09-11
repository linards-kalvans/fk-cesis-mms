import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_membership_plan_defaults():
    from apps.billing.models import MembershipPlan

    plan = MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        installment_count=10,
        first_installment_month=9,
    )
    assert plan.currency == "EUR"
    assert plan.annual_amount == Decimal("300.00")
    # P14: sibling_discount_percent field removed from MembershipPlan.
    assert not hasattr(MembershipPlan, "sibling_discount_percent")
    # P14: sibling_discount_percent_applied retained on BillingRecord.
    from apps.billing.models import BillingRecord
    assert hasattr(BillingRecord, "sibling_discount_percent_applied")
    assert plan.is_active is False
    assert str(plan) == "Sezona 2026/2027"
    assert plan.created_at is not None
    assert plan.updated_at is not None


def test_schedule_fields_defaults_and_skip_months_list(db):
    from apps.billing.models import MembershipPlan

    p = MembershipPlan.objects.create(name="P", season="2027")
    assert p.payment_due_day == 20
    assert p.skip_months == "7,12"
    assert p.skip_months_list == [7, 12]


def test_skip_months_list_parsing_is_tolerant(db):
    from apps.billing.models import MembershipPlan

    p = MembershipPlan.objects.create(name="P", season="2027", skip_months=" 7 , 12 ,, 13, x ")
    # whitespace tolerated; out-of-range / non-numeric dropped; sorted-unique
    assert p.skip_months_list == [7, 12]
    p2 = MembershipPlan.objects.create(name="P2", season="2027", skip_months="")
    assert p2.skip_months_list == []


def test_saving_default_plan_atomically_replaces_existing_default(db):
    """Saving an active plan with ``is_default=True`` clears any existing
    default so exactly one plan is the default (atomic replacement, no
    unique-constraint error)."""
    from apps.billing.models import MembershipPlan

    plan_a = MembershipPlan.objects.create(
        name="Sezona 2026/2027", season="2026/2027", is_active=True
    )
    plan_a.is_default = True
    plan_a.save()
    assert plan_a.is_default is True

    plan_b = MembershipPlan.objects.create(
        name="Sezona 2027/2028", season="2027/2028", is_active=True
    )
    plan_b.is_default = True
    plan_b.save()

    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_b.is_default is True
    assert plan_a.is_default is False
    assert MembershipPlan.objects.filter(is_default=True).count() == 1


def test_failed_default_save_rolls_back_old_default_clearing(db, monkeypatch):
    """The handover is atomic: when the new default row's save fails, the
    clearing of the previous default must roll back with it. The insert is
    forced to raise a controlled DatabaseError after the clearing UPDATE ran;
    the previous default must survive untouched."""
    import django.db.models.base

    from django.db import DatabaseError

    from apps.billing.models import MembershipPlan

    first = MembershipPlan.objects.create(
        name="Sezona 2026/2027", season="2026/2027", is_active=True
    )
    first.is_default = True
    first.save()
    assert first.is_default is True

    real_model_save = django.db.models.base.Model.save

    def _failing_model_save(self, *args, **kwargs):
        # Simulate the new-row INSERT failing after the handover UPDATE.
        raise DatabaseError("controlled insert failure")

    monkeypatch.setattr(django.db.models.base.Model, "save", _failing_model_save)
    broken = MembershipPlan(
        name="Sezona 2027/2028", season="2027/2028", is_active=True
    )
    broken.is_default = True
    with pytest.raises(DatabaseError):
        broken.save()

    monkeypatch.undo()
    first.refresh_from_db()
    assert first.is_default is True
    assert MembershipPlan.objects.filter(is_default=True).count() == 1


def test_inactive_plan_cannot_be_default_validation(db):
    """Model validation rejects an inactive plan marked as the default
    (``MembershipPlan.clean`` refuses ``is_default=True`` + ``is_active=False``)."""
    from django.core.exceptions import ValidationError

    from apps.billing.models import MembershipPlan

    inactive = MembershipPlan.objects.create(
        name="Neaktīva sezona", season="2027/2028", is_active=False
    )
    inactive.is_default = True
    with pytest.raises(ValidationError):
        inactive.full_clean()


def test_inactive_plan_cannot_be_persisted_as_default(db):
    """An inactive plan can never be persisted as the default (a DB-level
    CHECK constraint backs the invariant, so even a direct ORM save is
    refused)."""
    from django.db import IntegrityError, transaction

    from apps.billing.models import MembershipPlan

    inactive = MembershipPlan.objects.create(
        name="Neaktīva sezona", season="2027/2028", is_active=False
    )
    inactive.is_default = True
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            inactive.save()
    assert MembershipPlan.objects.filter(is_default=True).count() == 0
