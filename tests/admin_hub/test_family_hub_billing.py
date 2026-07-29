"""P11: Family hub billing block — grouping, invoice rows, error display."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _hub_url(guardian):
    return reverse("admin:members_guardian_family_hub", args=[guardian.pk])


def test_billing_block_groups_by_child_and_season(
    staff_client, approved_application, billing_record_factory,
):
    """Billing block must show child name + season + amount."""
    member = approved_application.approved_member
    record = billing_record_factory(member)
    guardian = approved_application.guardian

    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Norēķini un rēķini" in html
    assert member.full_name in html
    assert record.season in html
    assert str(record.final_amount) in html


def test_billing_block_renders_invoice_rows_in_details(
    staff_client, approved_application, billing_record_factory,
):
    """Invoice rows must render inside a <details> element."""
    from apps.billing.models import BillingInvoice

    member = approved_application.approved_member
    record = billing_record_factory(member)
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date="2026-01-20",
        amount="100.00",
        external_status="created",
    )

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "<details" in html
    assert "2026-01-20" in html
    assert "100.00" in html


def test_billing_block_renders_latvian_error_badge(
    staff_client, approved_application, billing_record_factory,
):
    """Failed billing must show Latvian error copy, NOT raw error code."""
    member = approved_application.approved_member
    record = billing_record_factory(
        member,
        external_status="failed",
        external_error_code="auth_failed",
    )
    guardian = approved_application.guardian

    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    # Must show some Latvian failure indicator
    assert "Neizdevās" in html or "Kļūda" in html
    # Must NOT leak raw error code as primary user-facing text
    assert "auth_failed" not in html


def test_discontinue_disclosure_renders_invoice_checkboxes_when_invoices_exist(
    staff_client, approved_application, billing_record_factory,
):
    """The signed-agreement discontinue disclosure must render one
    `name="selected_invoices"` checkbox per invoice row so staff can pick
    which invoices to cancel as part of the discontinuation flow."""
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_sent, mark_agreement_signed
    from apps.billing.models import BillingInvoice

    member = approved_application.approved_member
    record = billing_record_factory(member)
    invoice = BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date="2026-01-20",
        amount="100.00",
        external_status="created",
    )

    # Drive the agreement to "signed" so the discontinue disclosure renders.
    agreement = Agreement.objects.get(member=member, is_current=True)
    mark_agreement_sent(agreement, None)
    mark_agreement_signed(agreement, None)

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    # At least one checkbox carrying the discontinue invoice field name.
    assert 'name="selected_invoices"' in html
    assert f'value="{invoice.pk}"' in html
    # The checkbox lives inside the discontinue disclosure.
    assert "Pārtraukt dalību" in html


# ---------------------------------------------------------------------------
# Defect 2: pending billing shows syncing copy, no push action.
# ---------------------------------------------------------------------------


def test_billing_pending_shows_syncing_copy_no_push_action(
    staff_client, approved_application, billing_record_factory,
):
    """A confirmed BillingRecord with external_status='pending' must render
    exact Latvian syncing copy 'Rēķini tiek sinhronizēti…' and must NOT
    render the 'Izrakstīt rēķinus' push action."""
    member = approved_application.approved_member
    record = billing_record_factory(
        member,
        status="confirmed",
        external_status="pending",
    )
    guardian = approved_application.guardian

    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    # Exact syncing copy must be present.
    assert "Rēķini tiek sinhronizēti…" in html

    # Push action button must NOT be present.
    assert "Izrakstīt rēķinus" not in html


def test_billing_blank_external_status_shows_push_action(
    staff_client, approved_application, billing_record_factory,
):
    """A confirmed BillingRecord with blank external_status must still render
    the 'Izrakstīt rēķinus' push action."""
    member = approved_application.approved_member
    record = billing_record_factory(
        member,
        status="confirmed",
        external_status="",
    )
    guardian = approved_application.guardian

    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    # Push action button must be present.
    assert "Izrakstīt rēķinus" in html
