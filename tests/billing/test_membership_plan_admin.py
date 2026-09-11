"""MembershipPlan admin — external_product_id must be absent from the staff
create/change form even though it remains a model field used by the Invoice
Ninja integration jobs."""

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def plan(db, active_plan):
    return active_plan


def _change_url(plan_id):
    from django.urls import reverse

    return reverse("admin:billing_membershipplan_change", args=[plan_id])


def test_external_product_id_absent_from_change_form(staff_client, plan):
    """The MembershipPlan change form must not expose ``external_product_id``."""
    resp = staff_client.get(_change_url(plan.pk))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "external_product_id" not in content
    assert "id_external_product_id" not in content
    assert "external product id" not in content.lower()


def test_external_product_id_absent_from_add_form(staff_client):
    """The MembershipPlan add form must not expose ``external_product_id``."""
    from django.urls import reverse

    url = reverse("admin:billing_membershipplan_add")
    resp = staff_client.get(url)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "external_product_id" not in content
    assert "id_external_product_id" not in content


def test_external_product_id_field_still_exists_and_used_by_integration(plan):
    """The model field must remain present (the Invoice Ninja push job reads
    it) even though it is hidden from the admin form."""
    from apps.billing.models import MembershipPlan

    field = MembershipPlan._meta.get_field("external_product_id")
    assert field is not None
    # The integration job consumes the stored value; prove it is persisted.
    plan.external_product_id = "biedra-maksa-2026-2027"
    plan.save(update_fields=["external_product_id"])
    plan.refresh_from_db()
    assert plan.external_product_id == "biedra-maksa-2026-2027"
