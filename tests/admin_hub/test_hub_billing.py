"""Plan + invoices page — steps 6 to 8."""

from __future__ import annotations

import datetime
import re
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def signed_application(approved_application, default_plan, reviewer):
    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = default_plan
    agreement.first_billing_month = "2026-09"
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(
        update_fields=[
            "billing_plan",
            "first_billing_month",
            "state",
            "sent_at",
            "signed_at",
        ]
    )
    return approved_application


def _next_season_button_tag(body: str) -> str:
    """Return the exact ``<button ...>`` opening tag for
    ``create_next_season_billing``.

    A fixed-size substring window keyed off the position of the ``value``
    attribute is fragile — this exact pattern (``marker[-300:]`` scanning
    *backward* from ``value="..."``) has already been found defective
    elsewhere in this plan: ``disabled`` renders *after* ``value="..."`` in
    the same opening tag, so scanning backward from that marker can never
    see it, regardless of the button's real state. Isolating the actual
    opening tag with a regex checks the real element instead of an
    arbitrary character window that happens to overlap by coincidence.
    """
    match = re.search(
        r'<button[^>]*value="create_next_season_billing"[^>]*>', body, re.DOTALL
    )
    assert match is not None, "create_next_season_billing button must be present"
    return match.group(0)


def test_billing_page_requires_staff(client, signed_application):
    url = reverse("admin_hub:billing", args=[signed_application.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_billing_page_renders_the_three_step_cards(client, reviewer, signed_application):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert "Maksas plāns" in body
    assert "Rēķini" in body
    assert "Nākamā sezona" in body


def test_signed_with_no_record_does_not_post_to_set_billing_setup(
    client, reviewer, signed_application
):
    """DEFECT 1 (mutation-tested — see the report for both observations).

    ``signed_application`` is signed with no matched BillingRecord: its
    fixture forces ``agreement.state`` to SIGNED directly, bypassing
    ``mark_agreement_signed``'s signal that would otherwise create the
    record — exactly the season-matching desync the bug report hit. The
    old routing returned the ``set_billing_setup`` URL unconditionally
    whenever ``record`` was ``None``, regardless of the agreement's state —
    and that service refuses a signed agreement outright ("cannot change
    billing setup after signing"). The plan form must not point there; the
    Hub must instead offer the domain's own remedy
    (``recreate_current_billing``), with its required Invoice Ninja
    confirmation control rendered on the page.
    """
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert _plan_form_action(body) == ""
    assert "disabled" in _plan_form_submit_button_tag(body)
    review_action_url = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[signed_application.pk],
    )
    assert f'action="{review_action_url}"' in body
    assert 'value="recreate_current_billing"' in body
    assert 'name="external_invoice_confirmed_absent"' in body


def test_signed_with_no_record_and_inactive_member_blocks_without_recreate_offer(
    client, reviewer, signed_application
):
    """Complements the test above: recreate_missing_billing_record (via
    _signed_active_agreement at the POST) refuses an inactive member. The
    Hub must not dangle a recreate control the POST would refuse — a
    blocked reason with no offer, mirroring the guard exactly."""
    from apps.members.models import Member

    member = signed_application.approved_member
    member.status = Member.Status.DISCONTINUED
    member.save(update_fields=["status"])

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert _plan_form_action(body) == ""
    assert 'value="recreate_current_billing"' not in body
    assert 'name="external_invoice_confirmed_absent"' not in body
    assert "Šai sezonai nav norēķinu ieraksta" in body


def test_schedule_preview_lists_the_installments(client, reviewer, signed_application):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert "Aprēķinātais grafiks" in body
    # Scope to the schedule rows: a bare "2026" also matches the season
    # string, the plan name and every date elsewhere on the page.
    schedule_rows = re.findall(r'<div class="schedrow">.*?</div>\s*</div>', body, re.S)
    assert schedule_rows, "no schedule rows rendered"
    assert any("2026" in row for row in schedule_rows)


def test_schedule_preview_hint_when_no_plan_is_selected(
    client, reviewer, approved_application
):
    """The brief is explicit that the preview must never fabricate a
    schedule: with no plan selected, the page must show the 'choose a plan'
    hint instead of a guessed grid. None of the other tests exercise the
    no-plan branch, so a view that always calls
    ``derive_installment_schedule`` (crashing or guessing on a null plan)
    would pass every other test in this file."""
    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[approved_application.pk])
    ).content.decode()
    assert "Aprēķinātais grafiks" not in body
    assert "Izvēlieties plānu un pirmo mēnesi, lai redzētu grafiku." in body


def test_schedule_preview_uses_the_record_plan_and_month_once_one_exists(
    client, reviewer, signed_application, default_plan
):
    """IMPORTANT 3: once a BillingRecord exists it IS the billing, so the
    preview must read *its* plan/first_billing_month, not the agreement's —
    even though CRITICAL 1's reassignment sync should normally keep the two
    equal. This isolates the view's read path from that sync by building a
    record that deliberately disagrees with the agreement (e.g. a record
    from before the sync existed), the way a regression in it would."""
    from apps.billing.models import BillingRecord, MembershipPlan

    # Deliberately different from the agreement's default_plan (1
    # installment, anchored September): 3 installments anchored in a
    # different month than either the plan default or the agreement.
    record_plan = MembershipPlan.objects.create(
        name="Record-Only Plan",
        season="2026/2027",
        annual_amount=Decimal("450.00"),
        installment_count=3,
        first_installment_month=11,
        skip_months="",
        payment_due_day=20,
        is_active=True,
    )
    BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=record_plan,
        season=record_plan.season,
        base_amount=Decimal("450.00"),
        final_amount=Decimal("450.00"),
        first_billing_month="2026-12",
    )

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()

    # Each <div class="schedrow"> contains only <span> children (no nested
    # <div>), so its own close tag is the first </div> encountered — unlike
    # the sibling helper above, this does not require (and must not
    # require) a second, immediately-following </div>, which would only
    # ever match the last row before the wrapping .sched container closes.
    schedule_rows = re.findall(r'<div class="schedrow">.*?</div>', body, re.S)
    # Reading the agreement (default_plan, 1 installment, anchored
    # 2026-09) would render exactly one row due 20.09.2026. Reading the
    # record (record_plan, 3 installments, anchored 2026-12) renders three
    # rows, the first due 20.12.2026.
    assert len(schedule_rows) == 3
    assert any("20.12.2026" in row for row in schedule_rows)


def test_invoice_table_shows_a_created_invoice(
    client, reviewer, signed_application, default_plan
):
    from apps.billing.models import BillingInvoice, BillingRecord

    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 9, 20),
        amount=Decimal("30.00"),
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert "30,00" in body or "30.00" in body
    assert "Nav izrakstīts" in body


def test_push_endpoint_honours_next(client, signed_application, default_plan):
    from django.contrib.auth.models import User

    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent

    admin_user = User.objects.create_superuser(
        username="pusher", email="p@example.lv", password="x"
    )
    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    client.force_login(admin_user)
    hub_url = reverse("admin_hub:billing", args=[signed_application.pk])
    push_url = reverse("admin:billing_billingrecord_push", args=[record.pk])
    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue:
        response = client.post(f"{push_url}?next={hub_url}")
    assert response.status_code == 302
    assert response["Location"] == hub_url
    # Confirms the endpoint actually did the work before redirecting, not
    # merely that *some* redirect happened.
    enqueue.assert_called_once_with(record.pk)
    assert AuditEvent.objects.filter(
        action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED),
        target_id=str(record.pk),
    ).exists()


def test_push_endpoint_refuses_an_unconfirmed_record(
    client, signed_application, default_plan
):
    """The brief's original assertion (``record.external_status != "synced"``)
    cannot distinguish a working guard from a missing one: nothing in this
    synchronous test ever sets ``external_status`` to "synced" in the first
    place (the django-q task is not what runs here), AND
    ``enqueue_push_billing_record`` itself carries the exact same
    status-guard redundantly — so the assertion would hold even with
    ``push_view``'s own guard deleted entirely. Asserting that
    ``enqueue_push_billing_record`` is never even called, and that no
    BILLING_PUSH_TRIGGERED audit row is written, actually distinguishes
    "push_view refused" from "push_view proceeded and something downstream
    also happened to no-op"."""
    from django.contrib.auth.models import User

    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent

    admin_user = User.objects.create_superuser(
        username="pusher2", email="p2@example.lv", password="x"
    )
    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.DRAFT,
    )
    client.force_login(admin_user)
    push_url = reverse("admin:billing_billingrecord_push", args=[record.pk])
    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue:
        response = client.post(push_url)
    assert response.status_code == 302
    enqueue.assert_not_called()
    record.refresh_from_db()
    assert record.external_status != "synced"
    assert not AuditEvent.objects.filter(
        action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED),
        target_id=str(record.pk),
    ).exists()


def test_push_endpoint_refuses_a_get_request(
    client, signed_application, default_plan
):
    """push_view's POST-only guard is the one security-motivated line in this
    endpoint: Django does not CSRF-protect GET, so without it a link prefetch
    or an <img> tag could fire a real Invoice Ninja push on any staff session
    with no token and no confirmation click.

    Every other test here uses client.post, so deleting the guard broke
    nothing - which is exactly the regression it exists to prevent. This test
    is the one that fails if it goes. The record is CONFIRMED on purpose:
    every guard *after* the method check would otherwise let the request
    through, so a refusal here can only be the method check."""
    from django.contrib.auth.models import User

    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent

    admin_user = User.objects.create_superuser(
        username="pusher_get", email="pget@example.lv", password="x"
    )
    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    client.force_login(admin_user)
    push_url = reverse("admin:billing_billingrecord_push", args=[record.pk])
    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue:
        response = client.get(push_url)
    assert response.status_code == 302
    enqueue.assert_not_called()
    assert not AuditEvent.objects.filter(
        action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED),
        target_id=str(record.pk),
    ).exists()


def test_push_endpoint_is_a_noop_for_an_already_synced_record(
    client, signed_application, default_plan
):
    """Complements the unconfirmed-record test: a CONFIRMED record that is
    already synced must also be refused (no re-push, no duplicate audit
    row)."""
    from django.contrib.auth.models import User

    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent

    admin_user = User.objects.create_superuser(
        username="pusher3", email="p3@example.lv", password="x"
    )
    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
        external_status="synced",
    )
    client.force_login(admin_user)
    push_url = reverse("admin:billing_billingrecord_push", args=[record.pk])
    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue:
        response = client.post(push_url)
    assert response.status_code == 302
    enqueue.assert_not_called()
    assert not AuditEvent.objects.filter(
        action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED),
        target_id=str(record.pk),
    ).exists()


def test_next_season_action_is_disabled_without_a_current_record(
    client, reviewer, signed_application
):
    """signed_application has no BillingRecord yet, so step 8 cannot run."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    tag = _next_season_button_tag(body)
    assert "disabled" in tag


def test_next_season_action_is_disabled_when_a_next_season_record_already_exists(
    client, reviewer, signed_application, default_plan
):
    """The other half of the gate's OR: a current record exists, but a
    next-season record already exists too, so step 8 must stay disabled."""
    from apps.billing.models import BillingRecord

    BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season="2027/2028",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.DRAFT,
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    tag = _next_season_button_tag(body)
    assert "disabled" in tag


def test_next_season_action_is_enabled_when_current_record_exists_and_no_next_season_record(
    client, reviewer, signed_application, default_plan
):
    """Complements the two disabled-state tests above: without this, a bug
    that always renders `disabled` regardless of state would pass both of
    them silently."""
    from apps.billing.models import BillingRecord

    BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    tag = _next_season_button_tag(body)
    assert "disabled" not in tag


def _plan_form_action(body: str) -> str:
    """The step-6 form's action attribute, scoped to that form."""
    import re

    match = re.search(r'<form id="plan-form"[^>]*action="([^"]*)"', body)
    assert match, "step-6 plan form not found"
    return match.group(1)


def _plan_form_submit_button_tag(body: str) -> str:
    """The step-6 form's own submit button, scoped to its opening tag.

    ``_plan_form_action`` returns only the form's ``action="..."`` URL,
    which can never contain the word "disabled" — asserting against it
    cannot fail regardless of the button's real state. The button carrying
    ``{% if billing_change_blocked_reason %}disabled{% endif %}`` is the
    in-form ``card__foot`` submit (the first ``value="set_billing_setup"``
    button in document order; the actionbar's mirrors it via
    ``form="plan-form"`` further down the page)."""
    match = re.search(
        r'<button[^>]*value="set_billing_setup"[^>]*>', body, re.DOTALL
    )
    assert match is not None, "step-6 plan form submit button must be present"
    return match.group(0)


def test_plan_form_posts_set_billing_setup_before_signing(
    client, reviewer, approved_application, default_plan
):
    """No BillingRecord exists yet, so the plan is an intent on the agreement."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[approved_application.pk])
    ).content.decode()
    assert _plan_form_action(body) == reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[approved_application.pk],
    )


def test_plan_form_posts_reassign_once_a_record_exists(
    client, reviewer, signed_application, default_plan
):
    """After signing the record IS the billing, so changing the plan means
    reassigning that record. Posting set_billing_setup here raised the raw
    English "cannot change billing setup after signing" for a change the
    domain actually supports."""
    from decimal import Decimal

    from apps.billing.models import BillingRecord

    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    assert _plan_form_action(body) == reverse(
        "admin:billing_billingrecord_reassign", args=[record.pk]
    )
    assert "disabled" not in _plan_form_submit_button_tag(body)


def test_plan_change_is_blocked_with_a_reason_once_invoices_are_issued(
    client, reviewer, signed_application, default_plan
):
    """reassign_draft_billing_record refuses a record with a pushed invoice.
    The reviewer must be told which guard bit, not allowed to submit into it."""
    import datetime
    from decimal import Decimal

    from apps.billing.models import BillingInvoice, BillingRecord

    record = BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 9, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-9001",
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    # "Invoice Ninja" renders unconditionally in step 7's card header on
    # every billing page, blocking logic or not — it would pass even with
    # _billing_change_route's guard deleted. The form's action being empty
    # and its submit button carrying "disabled" are what _billing_change_route
    # actually controls, so only these fail when the blocking breaks.
    assert _plan_form_action(body) == ""
    assert "disabled" in _plan_form_submit_button_tag(body)
    assert "Rēķini jau ir izrakstīti" in body


def _plan_form_html(body: str) -> str:
    """The step-6 form's full markup (open tag through ``</form>``), scoped
    so assertions about its inner controls cannot match step 8's form —
    both share the ``billing_plan`` / ``first_billing_month`` field names."""
    match = re.search(r'<form id="plan-form".*?</form>', body, re.DOTALL)
    assert match is not None, "step-6 plan form not found"
    return match.group(0)


def test_confirmed_record_renders_plan_read_only_with_informational_note(
    client, reviewer, signed_application, default_plan
):
    """DEFECT 2: a confirmed record is the *normal* state once invoices are
    about to be issued — not an anomaly. The card must not show an amber
    warning next to what looks like an editable plan form: the plan +
    first-billing-month become read-only values, and the reason renders as
    a quiet informational note (neutral ``callout``, not ``callout--warn``).
    """
    from apps.billing.models import BillingRecord

    BillingRecord.objects.create(
        member=signed_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()
    plan_form = _plan_form_html(body)
    assert _plan_form_action(body) == ""
    # No editable plan controls left in the step-6 form.
    assert 'name="billing_plan"' not in plan_form
    assert 'name="first_billing_month"' not in plan_form
    # The current plan is still visible, just as a read-only value.
    assert default_plan.name in plan_form
    # Informational, not a warning: the neutral `callout` class renders,
    # `callout--warn` does not.
    assert "callout--warn" not in plan_form
    assert "callout" in plan_form


def test_season_desynced_record_withholds_the_recreate_offer(
    client, reviewer, signed_application, default_plan
):
    """The recreate offer must not appear when a record already exists for
    this agreement under a different season.

    The two seasons are the whole point of the finding: the pipeline's
    matcher and ``recreate_missing_billing_record``'s already-exists guard
    read the *same* ``agreement.billing_plan.season``, so neither sees the
    row. Offering recreate here does not produce a refusal the operator can
    learn from — it succeeds, leaving a second BillingRecord (the unique key
    is ``(member, season)``) with the invoices still attached to the first
    and nothing on screen to say so. The page names both seasons instead, so
    the operator repairs the link rather than duplicating the record."""
    from apps.billing.models import BillingRecord, MembershipPlan

    member = signed_application.approved_member
    agreement = member.agreements.get(is_current=True)
    later_plan = MembershipPlan.objects.create(
        name="Hub Desync View Plan",
        season="2027/2028",
        annual_amount=Decimal("320.00"),
        is_active=True,
    )
    agreement.billing_plan = later_plan
    agreement.save(update_fields=["billing_plan"])

    BillingRecord.objects.create(
        member=member,
        agreement=agreement,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        first_billing_month="2026-09",
        status=BillingRecord.Status.DRAFT,
    )

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:billing", args=[signed_application.pk])
    ).content.decode()

    # The remedy that would silently duplicate is not rendered at all.
    assert 'value="recreate_current_billing"' not in body
    assert 'name="external_invoice_confirmed_absent"' not in body
    # Neither is the plan form left submittable — set_billing_setup refuses
    # a signed agreement, which is what produced the raw English error.
    assert _plan_form_action(body) == ""
    # Both seasons are named, so the mismatch is diagnosable from the page.
    plan_form = _plan_form_html(body)
    assert default_plan.season in plan_form
    assert later_plan.season in plan_form
