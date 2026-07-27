import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _member_with_app(guardian, name):
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        approved_member=member,
    )
    return member


def test_recompute_updates_draft_after_plan_edit(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member, recompute_billing_record

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    assert rec.final_amount == Decimal("300.00")

    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()
    recompute_billing_record(rec)
    rec.refresh_from_db()
    assert rec.base_amount == Decimal("400.00")
    assert rec.final_amount == Decimal("400.00")


def test_recompute_skips_confirmed(active_plan, guardian):
    from apps.billing.models import BillingRecord
    from apps.billing.services import create_draft_billing_for_member, recompute_billing_record

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save()
    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()
    recompute_billing_record(rec)
    rec.refresh_from_db()
    assert rec.base_amount == Decimal("300.00")  # untouched


def test_recompute_preserves_manual_override(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member, recompute_billing_record

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    rec.manual_amount_override = Decimal("250.00")
    rec.save()

    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()
    recompute_billing_record(rec)
    rec.refresh_from_db()
    # Natural amounts re-derive from the plan, but final_amount honors the override.
    assert rec.base_amount == Decimal("400.00")
    assert rec.final_amount == Decimal("250.00")


def test_admin_registered():
    from django.contrib import admin
    from apps.billing.models import BillingRecord, MembershipPlan

    assert admin.site.is_registered(BillingRecord)
    assert admin.site.is_registered(MembershipPlan)


def test_membership_plan_admin_shows_schedule_fields(active_plan, staff_client):
    from django.urls import reverse

    url = reverse("admin:billing_membershipplan_change", args=[active_plan.pk])
    resp = staff_client.get(url)
    assert resp.status_code == 200
    assert b"payment_due_day" in resp.content
    assert b"skip_months" in resp.content


# ---------------------------------------------------------------------------
# P14 — Admin override: BillingRecordAdminForm validation + audit
# ---------------------------------------------------------------------------


def test_admin_form_requires_reason_for_non_null_override(active_plan, guardian):
    """P14: Setting manual_amount_override (including zero) requires a trimmed reason."""
    from apps.billing.admin import BillingRecordAdminForm
    from apps.billing.models import BillingRecord
    from apps.members.models import Member

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.DRAFT,
    )

    form = BillingRecordAdminForm(
        data={
            "manual_amount_override": "250.00",
            "manual_override_reason": "",
            "status": BillingRecord.Status.DRAFT,
        },
        instance=rec,
    )
    assert not form.is_valid()
    assert "manual_override_reason" in form.errors


def test_admin_form_requires_trimmed_reason(active_plan, guardian):
    """P14: Whitespace-only reason is rejected."""
    from apps.billing.admin import BillingRecordAdminForm
    from apps.billing.models import BillingRecord
    from apps.members.models import Member

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.DRAFT,
    )

    form = BillingRecordAdminForm(
        data={
            "manual_amount_override": "250.00",
            "manual_override_reason": "   ",
            "status": BillingRecord.Status.DRAFT,
        },
        instance=rec,
    )
    assert not form.is_valid()
    assert "manual_override_reason" in form.errors


def test_admin_form_zero_override_requires_reason(active_plan, guardian):
    """P14: Zero override also requires a reason."""
    from apps.billing.admin import BillingRecordAdminForm
    from apps.billing.models import BillingRecord
    from apps.members.models import Member

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.DRAFT,
    )

    form = BillingRecordAdminForm(
        data={
            "manual_amount_override": "0.00",
            "manual_override_reason": "",
            "status": BillingRecord.Status.DRAFT,
        },
        instance=rec,
    )
    assert not form.is_valid()
    assert "manual_override_reason" in form.errors


def test_admin_draft_override_updates_final_amount(active_plan, guardian, staff_client):
    """P14: Draft override updates final_amount."""
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from django.urls import reverse

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.DRAFT,
    )

    url = reverse("admin:billing_billingrecord_change", args=[rec.pk])
    resp = staff_client.post(
        url,
        {
            "manual_amount_override": "250.00",
            "manual_override_reason": "Student discount",
            "status": BillingRecord.Status.DRAFT,
            "invoices-TOTAL_FORMS": "0",
            "invoices-INITIAL_FORMS": "0",
            "invoices-MIN_NUM_FORMS": "0",
            "invoices-MAX_NUM_FORMS": "0",
        },
    )
    assert resp.status_code in (200, 302)
    rec.refresh_from_db()
    assert rec.final_amount == Decimal("250.00")


def test_admin_clear_override_restores_natural(active_plan, guardian, staff_client):
    """P14: Clearing override restores natural final_amount."""
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from django.urls import reverse

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=Decimal("250.00"),
        manual_amount_override=Decimal("250.00"),
        manual_override_reason="Previous reason",
        status=BillingRecord.Status.DRAFT,
    )

    url = reverse("admin:billing_billingrecord_change", args=[rec.pk])
    resp = staff_client.post(
        url,
        {
            "manual_amount_override": "",
            "manual_override_reason": "",
            "status": BillingRecord.Status.DRAFT,
            "invoices-TOTAL_FORMS": "0",
            "invoices-INITIAL_FORMS": "0",
            "invoices-MIN_NUM_FORMS": "0",
            "invoices-MAX_NUM_FORMS": "0",
        },
    )
    assert resp.status_code in (200, 302)
    rec.refresh_from_db()
    assert rec.final_amount == Decimal("300.00")


def test_admin_confirmed_cannot_change_amount_or_reason(active_plan, guardian, staff_client):
    """P14: Confirmed record cannot change amount/reason."""
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from django.urls import reverse

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.CONFIRMED,
    )

    url = reverse("admin:billing_billingrecord_change", args=[rec.pk])
    resp = staff_client.post(
        url,
        {
            "manual_amount_override": "250.00",
            "manual_override_reason": "Should not work",
            "status": BillingRecord.Status.CONFIRMED,
            "invoices-TOTAL_FORMS": "0",
            "invoices-INITIAL_FORMS": "0",
            "invoices-MIN_NUM_FORMS": "0",
            "invoices-MAX_NUM_FORMS": "0",
        },
    )
    rec.refresh_from_db()
    # Confirmed: override not applied.
    assert rec.manual_amount_override is None
    assert rec.final_amount == Decimal("300.00")


def test_admin_confirmed_cannot_change_reason_only(active_plan, guardian, staff_client):
    """P14: Confirmed record cannot change reason even if amount unchanged."""
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from django.urls import reverse

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        manual_amount_override=Decimal("250.00"),
        manual_override_reason="Original reason",
        status=BillingRecord.Status.CONFIRMED,
    )

    url = reverse("admin:billing_billingrecord_change", args=[rec.pk])
    resp = staff_client.post(
        url,
        {
            "manual_amount_override": "250.00",  # Same amount.
            "manual_override_reason": "Changed reason",  # Different reason.
            "status": BillingRecord.Status.CONFIRMED,
            "invoices-TOTAL_FORMS": "0",
            "invoices-INITIAL_FORMS": "0",
            "invoices-MIN_NUM_FORMS": "0",
            "invoices-MAX_NUM_FORMS": "0",
        },
    )
    rec.refresh_from_db()
    # Confirmed: reason not changed.
    assert rec.manual_override_reason == "Original reason"


def test_admin_override_audit_emitted(active_plan, guardian, staff_client):
    """P14: Successful admin save emits BILLING_RECORD_AMOUNT_OVERRIDDEN audit."""
    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent
    from apps.members.models import Member
    from django.urls import reverse

    member = Member.objects.create(full_name="Test", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.DRAFT,
    )

    url = reverse("admin:billing_billingrecord_change", args=[rec.pk])
    resp = staff_client.post(
        url,
        {
            "manual_amount_override": "250.00",
            "manual_override_reason": "Student discount",
            "status": BillingRecord.Status.DRAFT,
            "invoices-TOTAL_FORMS": "0",
            "invoices-INITIAL_FORMS": "0",
            "invoices-MIN_NUM_FORMS": "0",
            "invoices-MAX_NUM_FORMS": "0",
        },
    )
    assert resp.status_code in (200, 302)

    # Assert changed amount.
    rec.refresh_from_db()
    assert rec.final_amount == Decimal("250.00")

    audit = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.BILLING_RECORD_AMOUNT_OVERRIDDEN),
        target_id=rec.pk,
    ).first()
    assert audit is not None

    # Assert actor is staff_client user.
    from django.contrib.auth.models import User
    staff_user = User.objects.get(username="staff")
    assert audit.actor == staff_user

    # Metadata contains old/new override, no reason text.
    assert "old_override" in audit.metadata
    assert "new_override" in audit.metadata
    assert "reason" not in audit.metadata

    # Assert no free-text behavior — "Student discount" not in metadata.
    assert "Student discount" not in str(audit.metadata)
