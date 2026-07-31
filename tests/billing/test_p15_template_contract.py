"""P15 — template contracts for native month input + required attribute."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Agreement module template — native month input + required
# ---------------------------------------------------------------------------


def test_agreement_module_month_input_is_required():
    """The agreement module template must render the first_billing_month
    input as type='month' AND required."""
    template_path = (
        Path(__file__).resolve().parents[2]
        / "templates"
        / "registrations"
        / "admin"
        / "_agreement_module.html"
    )
    template_source = template_path.read_text(encoding="utf-8")

    # Find the first_billing_month input
    input_pattern = re.compile(
        r'<input[^>]*name="first_billing_month"[^>]*>',
        re.IGNORECASE,
    )
    match = input_pattern.search(template_source)
    assert match is not None, "Expected first_billing_month input in template"

    input_html = match.group(0)
    assert 'type="month"' in input_html, "Expected type='month' attribute"
    assert "required" in input_html, "Expected required attribute"


# ---------------------------------------------------------------------------
# Reassign template — native month input + required
# ---------------------------------------------------------------------------


def test_reassign_template_month_input_is_required():
    """The billing record reassign confirmation template must render the
    first_billing_month input as type='month' AND required."""
    template_path = (
        Path(__file__).resolve().parents[2]
        / "templates"
        / "admin"
        / "billing"
        / "billingrecord"
        / "reassign_confirm.html"
    )
    template_source = template_path.read_text(encoding="utf-8")

    input_pattern = re.compile(
        r'<input[^>]*name="first_billing_month"[^>]*>',
        re.IGNORECASE,
    )
    match = input_pattern.search(template_source)
    assert match is not None, "Expected first_billing_month input in template"

    input_html = match.group(0)
    assert 'type="month"' in input_html, "Expected type='month' attribute"
    assert "required" in input_html, "Expected required attribute"


def test_reassign_view_renders_required_month_input(staff_client, db):
    """GET on the admin reassign view renders the form with type='month' AND
    required on the first_billing_month input."""
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.members.models import Member
    from tests.support import make_guardian

    plan = MembershipPlan.objects.create(
        name="Reassign-Test",
        season="2026/2027",
        annual_amount="300.00",
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    guardian = make_guardian(full_name="Reassign Parent")
    member = Member.objects.create(full_name="Reassign Child", guardian=guardian)
    record = BillingRecord.objects.create(
        member=member,
        plan=plan,
        season=plan.season,
        base_amount="300.00",
        final_amount="300.00",
        status=BillingRecord.Status.DRAFT,
    )

    url = reverse("admin:billing_billingrecord_reassign", args=[record.pk])
    response = staff_client.get(url)
    assert response.status_code == 200

    html = response.content.decode()
    input_pattern = re.compile(
        r'<input[^>]*name="first_billing_month"[^>]*>',
        re.IGNORECASE,
    )
    match = input_pattern.search(html)
    assert match is not None, "Expected first_billing_month input in rendered form"

    input_html = match.group(0)
    assert 'type="month"' in input_html, "Expected type='month' attribute"
    assert "required" in input_html, "Expected required attribute"
