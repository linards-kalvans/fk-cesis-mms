"""P8: Admin agreement lifecycle action tests.

Tests that the RegistrationApplication admin change page shows lifecycle
forms/actions for signed agreements, that POST workflows work, and that
paid-invoice discontinuation blocks with a Latvian warning.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    mark_agreement_sent,
    mark_agreement_signed,
)
from apps.registrations.services import approve_application


pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer", is_staff=True)


@pytest.fixture
def default_plan(db):
    """An active default MembershipPlan so the P9 signing guard passes."""
    from decimal import Decimal

    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="P8 Default Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
        is_default=True,
    )


@pytest.fixture
def approved_with_signed_agreement(submitted_application, reviewer, default_plan):
    """An approved application whose agreement has been sent + signed.

    ``default_plan`` makes ``create_agreement_for_member`` preselect a
    ``billing_plan`` on the new agreement so the P9 signing guard passes.
    """
    app = approve_application(submitted_application, reviewer)
    agreement = create_agreement_for_member(
        app.approved_member, Agreement.SigningPath.PAPER
    )
    mark_agreement_sent(agreement, reviewer)
    mark_agreement_signed(agreement, reviewer)
    return app


@pytest.fixture
def active_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="P8 Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
    )


@pytest.fixture
def billing_record_factory(db, active_plan):
    """Factory: confirm a BillingRecord for any given member. Reuses the
    draft record the agreement-signing signal already created for the
    same (member, season) — P9 invariant ensures a plan was selected."""
    from apps.billing.models import BillingRecord

    def _make(member):
        record, _ = BillingRecord.objects.update_or_create(
            member=member,
            season=active_plan.season,
            defaults=dict(
                plan=active_plan,
                base_amount=active_plan.annual_amount,
                final_amount=active_plan.annual_amount,
                status=BillingRecord.Status.CONFIRMED,
            ),
        )
        return record

    return _make


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


# -- Visibility on signed agreements --


def test_signed_agreement_page_shows_lifecycle_forms_and_labels(
    approved_with_signed_agreement, staff_client
):
    """Change page for a signed agreement must show the minor amendment,
    material amendment, and discontinuation affordances with the new
    Latvian labels and disclosure copy, and must NOT carry the old
    void label.
    """
    resp = staff_client.get(
        _change_url(approved_with_signed_agreement.id)
    )
    html = resp.content.decode("utf-8")
    html_lower = html.lower()

    # Lifecycle action affordances (P8 originals).
    assert "Neliels labojums" in html
    assert "Sagatavot aizvietojošu līgumu" in html
    assert "Pārtraukt dalību" in html

    # Void disclosure must explain it is document-only and NOT change
    # participation or invoices.
    assert "dokument" in html_lower, (
        "void disclosure must mention the document scope"
    )
    void_negations = ["nemaina dalību", "neietekmē", "neizmaina", "neattiecas"]
    assert any(phrase in html_lower for phrase in void_negations), (
        f"void disclosure must explain limited scope; expected one of {void_negations}"
    )

    # Discontinue disclosure must mention invoice processing and
    # participation ending.
    assert "norēķin" in html_lower, (
        "discontinue disclosure must mention invoice processing"
    )
    assert "dalīb" in html_lower, (
        "discontinue disclosure must mention participation"
    )

    # P8 rework: label changes (J).
    assert "Anulēt līguma dokumentu" in html, (
        "expected new void label in admin page"
    )
    assert "Pārtraukt dalību un norēķinus" in html, (
        "expected new discontinue label in admin page"
    )

    # P8 rework: old void label must be gone.
    assert "Atcelt līgumu" not in html, (
        "old void label must be replaced by 'Anulēt līguma dokumentu'"
    )


# -- Generated (not signed) shows no lifecycle actions --


def test_generated_agreement_shows_no_lifecycle_actions(
    submitted_application, staff_client, reviewer
):
    """Agreement in generated state does not show lifecycle forms."""
    approve_application(submitted_application, reviewer)
    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "Neliels labojums" not in html
    assert "Sagatavot aizvietojošu līgumu" not in html
    assert "Pārtraukt dalību" not in html


# -- POST minor amendment --


def test_post_minor_amendment_creates_event(
    approved_with_signed_agreement, staff_client
):
    """POST with action=minor_amendment creates a lifecycle event."""
    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "minor_amendment", "note": "Labots e-pasts"},
    )
    assert resp.status_code == 302

    agreement = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED
    assert agreement.lifecycle_events.filter(event_type="minor_amendment").exists()


# -- POST material amendment --


def test_post_material_amendment_creates_new_agreement(
    approved_with_signed_agreement, staff_client
):
    """POST with action=material_amendment supersedes old + creates new."""
    old = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    old_id = old.id

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "material_amendment", "note": "Mainīti noteikumi"},
    )
    assert resp.status_code == 302

    old.refresh_from_db()
    assert old.state == Agreement.State.SUPERSEDED
    assert old.is_current is False

    new = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    assert new.id != old_id
    assert new.state == Agreement.State.GENERATED


# -- POST discontinuation blocks with paid invoice --


def test_post_discontinuation_with_paid_invoice_warns_with_latvian(
    approved_with_signed_agreement, staff_client, active_plan, billing_record_factory
):
    """When a selected invoice is paid, the admin action must show a Latvian
    warning and NOT change agreement/member state."""
    from apps.billing.models import BillingInvoice

    member = approved_with_signed_agreement.approved_member
    record = billing_record_factory(member)

    paid = BillingInvoice.objects.create(
        billing_record=record,
        sequence=99,
        due_date="2026-12-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-PAID-1",
        external_status="sent",
        payment_status="paid",
    )

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {
            "action": "discontinue_member",
            "effective_date": "2026-09-01",
            "reason": "Pārcelšanās",
            "selected_invoices": [str(paid.pk)],
        },
        follow=True,
    )
    html = resp.content.decode("utf-8")

    # Latvian warning about paid invoice
    assert "apmaksātu" in html.lower() or "apmaksāt" in html.lower()

    # Nothing mutated
    agreement = Agreement.objects.filter(
        member=member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED
    member.refresh_from_db()
    assert member.status != member.Status.DISCONTINUED  # still active


# -- Anonymous blocked --


def test_post_discontinuation_with_invalid_date_is_rejected(
    approved_with_signed_agreement, staff_client
):
    """An invalid effective_date must not call the service or change state."""
    from apps.agreements.models import Agreement

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {
            "action": "discontinue_member",
            "effective_date": "not-a-date",
            "reason": "Pārcelšanās",
            "selected_invoices": [],
        },
        follow=True,
    )
    assert resp.status_code == 200

    agreement = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED
    assert not agreement.lifecycle_events.filter(
        event_type="discontinued"
    ).exists()


def test_anonymous_cannot_post_lifecycle_actions(
    approved_with_signed_agreement, client
):
    resp = client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "minor_amendment", "note": "test"},
    )
    assert resp.status_code in (302, 403, 404)


# -- Non-staff blocked --


def test_non_staff_verified_parent_cannot_post_actions(
    approved_with_signed_agreement, verified_client
):
    resp = verified_client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "minor_amendment", "note": "test"},
    )
    assert resp.status_code in (302, 403, 404)


# -- P8 rework: Partial invoice blocks (K) --


def test_post_discontinuation_with_partial_invoice_blocks(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory,
):
    """When a selected invoice is partially paid, the admin action must block
    with a Latvian error and leave agreement/member/invoices UNCHANGED."""
    from apps.billing.models import BillingInvoice

    member = approved_with_signed_agreement.approved_member
    record = billing_record_factory(member)

    partial = BillingInvoice.objects.create(
        billing_record=record,
        sequence=99,
        due_date="2026-12-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-PARTIAL-1",
        external_status="sent",
        payment_status="partial",
    )

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {
            "action": "discontinue_member",
            "effective_date": "2026-09-01",
            "reason": "Pārcelšanās",
            "selected_invoices": [str(partial.pk)],
        },
        follow=True,
    )
    html = resp.content.decode("utf-8")
    assert resp.status_code == 200

    # Must show some Latvian error message about the partially paid invoice
    assert "apmaks" in html.lower(), (
        "expected a Latvian error about the partially paid invoice"
    )

    # Nothing mutated — agreement still signed
    agreement = Agreement.objects.filter(
        member=member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED, (
        "agreement must stay signed after partial block"
    )
    member.refresh_from_db()
    assert member.status == member.Status.ACTIVE, (
        "member must stay active after partial block"
    )

    # Invoice unchanged
    partial.refresh_from_db()
    assert partial.cancelled_at is None, (
        "invoice must not be cancelled on block"
    )
    assert partial.payment_status == "partial", (
        "payment status must be unchanged"
    )


# -- P8 rework: Post-discontinuation cancelled invoice visibility (L) --


def test_post_discontinuation_shows_cancelled_invoice_on_change_page(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory,
):
    """After a successful discontinuation with a selected sent-unpaid invoice,
    the admin change page must still show the cancelled invoice state
    even though the member is now discontinued."""
    from apps.billing.models import BillingInvoice
    from apps.agreements.services import discontinue_agreement
    import datetime

    member = approved_with_signed_agreement.approved_member
    record = billing_record_factory(member)

    sent_unpaid = BillingInvoice.objects.create(
        billing_record=record,
        sequence=99,
        due_date="2026-12-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-CANCEL-VIS",
        external_status="sent",
        payment_status="unpaid",
    )

    agreement = Agreement.objects.filter(
        member=member, is_current=True
    ).first()
    discontinue_agreement(
        agreement=agreement,
        actor=None,
        effective_date=datetime.date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[sent_unpaid.pk],
    )

    # Verify member is discontinued
    member.refresh_from_db()
    assert member.status == member.Status.DISCONTINUED

    # Verify the invoice is locally cancelled
    sent_unpaid.refresh_from_db()
    assert sent_unpaid.cancelled_at is not None, (
        "invoice must be locally cancelled"
    )

    # Open the admin change page — must still show the invoice details
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")
    assert resp.status_code == 200

    # After discontinuation, the agreement state must be visible
    assert "Pārtraukts" in html, (
        "agreement state 'Pārtraukts' must be visible on change page"
    )

    # The cancelled invoice's IN id must still be visible on the page
    assert "IN-CANCEL-VIS" in html, (
        "cancelled invoice external id must still be visible on change page"
    )


# ---------------------------------------------------------------------------
# Unit 3 Task 6: document-only void and membership/billing discontinuation
# ---------------------------------------------------------------------------


def _invoice(record, sequence, **overrides):
    from apps.billing.models import BillingInvoice

    values = {
        "billing_record": record,
        "sequence": sequence,
        "due_date": "2026-10-20",
        "amount": Decimal("30.00"),
    }
    values.update(overrides)
    return BillingInvoice.objects.create(**values)


def _discontinue_post(client, application, *, date="2026-10-01", reason="Pārcelšanās",
                      invoice_ids=None, next_url="/hub/pieteikumi/"):
    url = _action_url(application.id)
    if next_url is not None:
        url = f"{url}?next={next_url}"
    return client.post(
        url,
        {
            "action": "discontinue_member",
            "effective_date": date,
            "reason": reason,
            "selected_invoices": [str(pk) for pk in (invoice_ids or [])],
        },
        follow=False,
    )


def test_void_agreement_from_the_admin_preserves_member_billing_and_artifact(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, monkeypatch, mailoutbox,
):
    from apps.agreements.models import Agreement as AgreementModel
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    agreement.signing_path = AgreementModel.SigningPath.ELECTRONIC
    agreement.external_id = "DOCUSEAL-EXISTING"
    agreement.signed_artifact.name = "agreements/signed/existing.pdf"
    agreement.save(
        update_fields=["signing_path", "external_id", "signed_artifact"]
    )
    record = billing_record_factory(member)
    invoice = _invoice(
        record,
        1,
        external_invoice_id="IN-VOID-KEEP",
        external_status="sent",
        payment_status="unpaid",
    )
    original_amount = record.final_amount
    initial_mail = len(mailoutbox)

    archived = []
    monkeypatch.setattr(
        "apps.integrations.tasks.enqueue_archive_agreement_submission",
        lambda external_id: archived.append(external_id),
    )

    response = staff_client.post(
        f"{_action_url(approved_with_signed_agreement.id)}?next=/hub/pieteikumi/",
        {"action": "void_agreement", "void_reason": "Novecojis dokuments"},
        follow=False,
    )

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"

    agreement.refresh_from_db()
    member.refresh_from_db()
    record.refresh_from_db()
    invoice.refresh_from_db()

    assert agreement.state == AgreementModel.State.VOID
    assert agreement.is_current is True
    assert agreement.void_reason == "Novecojis dokuments"
    assert agreement.external_id == "DOCUSEAL-EXISTING"
    assert agreement.signed_artifact.name == "agreements/signed/existing.pdf"
    assert member.status == member.Status.ACTIVE
    assert record.final_amount == original_amount
    assert invoice.cancelled_at is None
    assert invoice.payment_status == "unpaid"
    assert archived == ["DOCUSEAL-EXISTING"]
    assert len(mailoutbox) == initial_mail + 1

    # A replay is a no-op: void_agreement returns before the second email or
    # archive enqueue, and the admin keeps the same safe redirect.
    replay = staff_client.post(
        f"{_action_url(approved_with_signed_agreement.id)}?next=/hub/pieteikumi/",
        {"action": "void_agreement", "void_reason": "Atkārtots"},
        follow=False,
    )
    assert replay.status_code == 302
    assert replay["Location"] == "/hub/pieteikumi/"
    assert len(mailoutbox) == initial_mail + 1
    assert archived == ["DOCUSEAL-EXISTING"]


def test_discontinuation_with_zero_selection_changes_no_invoices(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, mailoutbox,
):
    from apps.agreements.models import AgreementLifecycleEvent
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    local = _invoice(record, 1)
    drafted = _invoice(
        record, 2, external_invoice_id="IN-DRAFT-ZERO", external_status="created"
    )
    initial_mail = len(mailoutbox)

    response = _discontinue_post(staff_client, approved_with_signed_agreement)

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"
    agreement.refresh_from_db()
    member.refresh_from_db()
    local.refresh_from_db()
    drafted.refresh_from_db()

    assert agreement.state == agreement.State.DISCONTINUED
    assert member.status == member.Status.DISCONTINUED
    assert local.cancelled_at is None
    assert drafted.cancelled_at is None
    assert AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).count() == 1
    assert len(mailoutbox) == initial_mail + 1

    replay = _discontinue_post(staff_client, approved_with_signed_agreement)
    assert replay.status_code == 302
    agreement.refresh_from_db()
    assert agreement.state == agreement.State.DISCONTINUED
    assert AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).count() == 1
    assert len(mailoutbox) == initial_mail + 1


def test_discontinuation_applies_only_explicitly_selected_unpaid_invoices(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, monkeypatch, mailoutbox,
    django_capture_on_commit_callbacks,
):
    from apps.agreements.models import AgreementLifecycleEvent
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    local = _invoice(record, 1)
    drafted = _invoice(
        record, 2, external_invoice_id="IN-DRAFT-SELECT", external_status="created"
    )
    sent = _invoice(
        record,
        3,
        external_invoice_id="IN-SENT-SELECT",
        external_status="sent",
        payment_status="unpaid",
    )
    untouched = _invoice(
        record, 4, external_invoice_id="IN-NOT-SELECTED", external_status="sent"
    )
    initial_mail = len(mailoutbox)

    archived, cancelled = [], []
    monkeypatch.setattr(
        "apps.agreements.services._enqueue_archive_invoice",
        lambda invoice_id: archived.append(invoice_id),
    )
    monkeypatch.setattr(
        "apps.agreements.services._enqueue_cancel_invoice",
        lambda invoice_id: cancelled.append(invoice_id),
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = _discontinue_post(
            staff_client,
            approved_with_signed_agreement,
            invoice_ids=[local.pk, drafted.pk, sent.pk],
        )

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"
    agreement.refresh_from_db()
    member.refresh_from_db()
    for invoice in (local, drafted, sent, untouched):
        invoice.refresh_from_db()

    assert agreement.state == agreement.State.DISCONTINUED
    assert member.status == member.Status.DISCONTINUED
    assert local.cancelled_at is not None
    assert local.external_cancellation_action == ""
    assert drafted.cancelled_at is not None
    assert drafted.external_cancellation_action == "archive"
    assert drafted.external_cancellation_status == "pending"
    assert sent.cancelled_at is not None
    assert sent.external_cancellation_action == "cancel"
    assert sent.external_cancellation_status == "pending"
    assert untouched.cancelled_at is None
    assert untouched.external_cancellation_action == ""
    assert archived == [drafted.pk]
    assert cancelled == [sent.pk]
    assert AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).exists()
    assert len(mailoutbox) == initial_mail + 1


@pytest.mark.parametrize("payment_status", ["paid", "partial"])
def test_discontinuation_paid_or_partial_selection_rolls_back_everything(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, mailoutbox, payment_status,
):
    from apps.agreements.models import AgreementLifecycleEvent
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    valid = _invoice(
        record, 1, external_invoice_id="IN-VALID", external_status="sent"
    )
    blocked = _invoice(
        record,
        2,
        external_invoice_id=f"IN-{payment_status.upper()}",
        external_status="sent",
        payment_status=payment_status,
    )
    initial_mail = len(mailoutbox)

    response = _discontinue_post(
        staff_client,
        approved_with_signed_agreement,
        invoice_ids=[valid.pk, blocked.pk],
    )

    assert response.status_code == 302
    agreement.refresh_from_db()
    member.refresh_from_db()
    valid.refresh_from_db()
    blocked.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert member.status == member.Status.ACTIVE
    assert valid.cancelled_at is None
    assert blocked.cancelled_at is None
    assert not AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).exists()
    assert len(mailoutbox) == initial_mail

    followed = staff_client.get("/hub/pieteikumi/", follow=True)
    assert (
        "Apmaksāts vai daļēji apmaksāts rēķins jāapstrādā manuāli Invoice Ninja."
        in followed.content.decode()
    )


def test_discontinuation_foreign_or_unknown_selection_rolls_back(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, mailoutbox,
):
    from apps.agreements.models import AgreementLifecycleEvent
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    valid = _invoice(record, 1)
    initial_mail = len(mailoutbox)

    response = _discontinue_post(
        staff_client,
        approved_with_signed_agreement,
        invoice_ids=[valid.pk, 999999],
    )

    assert response.status_code == 302
    agreement.refresh_from_db()
    member.refresh_from_db()
    valid.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert member.status == member.Status.ACTIVE
    assert valid.cancelled_at is None
    assert not AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).exists()
    assert len(mailoutbox) == initial_mail

    followed = staff_client.get("/hub/pieteikumi/", follow=True)
    assert (
        "Atlasē ir šim biedram nepiederīgi vai nezināmi rēķini."
        in followed.content.decode()
    )


def test_discontinuation_unclear_invoice_state_rolls_back_with_fixed_copy(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, mailoutbox,
):
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    unclear = _invoice(
        record,
        1,
        external_invoice_id="IN-UNKNOWN",
        external_status="failed",
    )
    initial_mail = len(mailoutbox)

    response = _discontinue_post(
        staff_client, approved_with_signed_agreement, invoice_ids=[unclear.pk]
    )

    assert response.status_code == 302
    agreement.refresh_from_db()
    unclear.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert unclear.cancelled_at is None
    assert len(mailoutbox) == initial_mail

    followed = staff_client.get("/hub/pieteikumi/", follow=True)
    assert (
        "Atlasītā rēķina stāvoklis neļauj to apstrādāt. Pārbaudiet to Invoice Ninja."
        in followed.content.decode()
    )


@pytest.mark.parametrize(
    ("date", "reason", "invoice_value", "expected"),
    [
        ("not-a-date", "Pārcelšanās", "", "Nederīgs spēkā stāšanās datums."),
        ("2026-10-01", "", "", "Norādiet spēkā stāšanās datumu un iemeslu."),
        ("2026-10-01", "Pārcelšanās", "not-an-int", "Nederīga rēķinu atlase."),
    ],
)
def test_discontinuation_input_errors_use_fixed_latvian_copy(
    approved_with_signed_agreement, staff_client, billing_record_factory,
    mailoutbox, date, reason, invoice_value, expected,
):
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    billing_record_factory(member)
    initial_mail = len(mailoutbox)

    url = f"{_action_url(approved_with_signed_agreement.id)}?next=/hub/pieteikumi/"
    response = staff_client.post(
        url,
        {
            "action": "discontinue_member",
            "effective_date": date,
            "reason": reason,
            "selected_invoices": [invoice_value] if invoice_value else [],
        },
        follow=False,
    )

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"
    agreement.refresh_from_db()
    member.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert member.status == member.Status.ACTIVE
    assert len(mailoutbox) == initial_mail

    followed = staff_client.get("/hub/pieteikumi/", follow=True)
    assert expected in followed.content.decode()


def test_discontinuation_rejects_a_stale_noncurrent_agreement_before_writing(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, monkeypatch, mailoutbox,
):
    from django.utils import timezone

    from apps.agreements.models import Agreement as AgreementModel
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    current = get_current_agreement(member)
    record = billing_record_factory(member)
    invoice = _invoice(record, 1)
    stale = AgreementModel.objects.create(
        member=member,
        is_current=False,
        state=AgreementModel.State.SIGNED,
        signing_path=AgreementModel.SigningPath.PAPER,
        agreement_number="STALE-UNIT3",
        generated_at=timezone.now(),
        signed_at=timezone.now(),
    )
    monkeypatch.setattr(
        "apps.registrations.admin.get_current_agreement", lambda member: stale
    )
    initial_mail = len(mailoutbox)

    response = _discontinue_post(
        staff_client, approved_with_signed_agreement, invoice_ids=[invoice.pk]
    )

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"
    current.refresh_from_db()
    stale.refresh_from_db()
    member.refresh_from_db()
    invoice.refresh_from_db()
    assert current.state == AgreementModel.State.SIGNED
    assert stale.state == AgreementModel.State.SIGNED
    assert member.status == member.Status.ACTIVE
    assert invoice.cancelled_at is None
    assert len(mailoutbox) == initial_mail

    followed = staff_client.get("/hub/pieteikumi/", follow=True)
    assert (
        "Darbība pieejama tikai parakstītam līgumam ar aktīvu dalību."
        in followed.content.decode()
    )


def test_discontinuation_requires_a_signed_agreement_on_the_server(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, mailoutbox,
):
    from apps.agreements.models import AgreementLifecycleEvent
    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    agreement.state = agreement.State.SENT
    agreement.save(update_fields=["state"])
    record = billing_record_factory(member)
    invoice = _invoice(record, 1)
    initial_mail = len(mailoutbox)

    response = _discontinue_post(
        staff_client, approved_with_signed_agreement, invoice_ids=[invoice.pk]
    )

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"
    agreement.refresh_from_db()
    member.refresh_from_db()
    invoice.refresh_from_db()
    assert agreement.state == agreement.State.SENT
    assert member.status == member.Status.ACTIVE
    assert invoice.cancelled_at is None
    assert not AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).exists()
    assert len(mailoutbox) == initial_mail

    followed = staff_client.get("/hub/pieteikumi/", follow=True)
    assert (
        "Darbība pieejama tikai parakstītam līgumam ar aktīvu dalību."
        in followed.content.decode()
    )


def test_discontinuation_requires_an_active_member_on_the_server(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory, mailoutbox,
):
    from apps.agreements.models import AgreementLifecycleEvent
    from apps.agreements.services import get_current_agreement
    from apps.members.models import Member

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    member.status = Member.Status.DISCONTINUED
    member.save(update_fields=["status"])
    record = billing_record_factory(member)
    invoice = _invoice(record, 1)
    initial_mail = len(mailoutbox)

    response = _discontinue_post(
        staff_client, approved_with_signed_agreement, invoice_ids=[invoice.pk]
    )

    assert response.status_code == 302
    assert response["Location"] == "/hub/pieteikumi/"
    agreement.refresh_from_db()
    invoice.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert invoice.cancelled_at is None
    assert not AgreementLifecycleEvent.objects.filter(
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED
    ).exists()
    assert len(mailoutbox) == initial_mail


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        ("void_agreement", {"void_reason": "Novecojis"}),
        (
            "discontinue_member",
            {
                "effective_date": "2026-10-01",
                "reason": "Pārcelšanās",
                "selected_invoices": [],
            },
        ),
    ],
)
def test_lifecycle_actions_require_change_permission(
    approved_with_signed_agreement, reviewer, active_plan,
    billing_record_factory, monkeypatch, mailoutbox, action, payload,
):
    """A staff-only account may render the pages, but neither writer may
    mutate state, send mail or queue an external job."""
    from django.test import Client

    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    invoice = _invoice(
        record, 1, external_invoice_id="IN-NO-CHANGE", external_status="sent"
    )
    initial_mail = len(mailoutbox)
    archives, cancellations = [], []
    monkeypatch.setattr(
        "apps.integrations.tasks.enqueue_archive_agreement_submission",
        lambda *args: archives.append(args),
    )
    monkeypatch.setattr(
        "apps.agreements.services._enqueue_archive_invoice",
        lambda *args: archives.append(args),
    )
    monkeypatch.setattr(
        "apps.agreements.services._enqueue_cancel_invoice",
        lambda *args: cancellations.append(args),
    )

    if action == "discontinue_member":
        payload = {**payload, "selected_invoices": [str(invoice.pk)]}
    url = f"{_action_url(approved_with_signed_agreement.id)}?next=/hub/pieteikumi/"

    client = Client()
    client.force_login(reviewer)
    response = client.post(url, {"action": action, **payload})

    assert response.status_code == 403
    agreement.refresh_from_db()
    member.refresh_from_db()
    invoice.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert member.status == member.Status.ACTIVE
    assert invoice.cancelled_at is None
    assert len(mailoutbox) == initial_mail
    assert archives == []
    assert cancellations == []


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        ("void_agreement", {"void_reason": "Novecojis"}),
        (
            "discontinue_member",
            {
                "effective_date": "2026-10-01",
                "reason": "Pārcelšanās",
                "selected_invoices": [],
            },
        ),
    ],
)
def test_lifecycle_actions_require_csrf(
    approved_with_signed_agreement, active_plan, billing_record_factory,
    monkeypatch, mailoutbox, action, payload,
):
    """Enforced CSRF rejects both branches before any state, mail or job."""
    from django.contrib.auth.models import User
    from django.test import Client

    from apps.agreements.services import get_current_agreement

    member = approved_with_signed_agreement.approved_member
    agreement = get_current_agreement(member)
    record = billing_record_factory(member)
    invoice = _invoice(
        record, 1, external_invoice_id="IN-CSRF", external_status="sent"
    )
    initial_mail = len(mailoutbox)
    archives, cancellations = [], []
    monkeypatch.setattr(
        "apps.integrations.tasks.enqueue_archive_agreement_submission",
        lambda *args: archives.append(args),
    )
    monkeypatch.setattr(
        "apps.agreements.services._enqueue_archive_invoice",
        lambda *args: archives.append(args),
    )
    monkeypatch.setattr(
        "apps.agreements.services._enqueue_cancel_invoice",
        lambda *args: cancellations.append(args),
    )
    User.objects.create_superuser(
        username="csrf-reviewer", email="csrf@example.com", password="pw"
    )
    client = Client(enforce_csrf_checks=True)
    client.login(username="csrf-reviewer", password="pw")

    if action == "discontinue_member":
        payload = {**payload, "selected_invoices": [str(invoice.pk)]}

    response = client.post(
        f"{_action_url(approved_with_signed_agreement.id)}?next=/hub/pieteikumi/",
        {"action": action, **payload},
    )

    assert response.status_code == 403
    agreement.refresh_from_db()
    member.refresh_from_db()
    invoice.refresh_from_db()
    assert agreement.state == agreement.State.SIGNED
    assert member.status == member.Status.ACTIVE
    assert invoice.cancelled_at is None
    assert len(mailoutbox) == initial_mail
    assert archives == []
    assert cancellations == []
