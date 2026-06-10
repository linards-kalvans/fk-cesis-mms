import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _confirmed_record(active_plan, guardian, payment_mode):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=payment_mode, status=BillingRecord.Status.CONFIRMED,
    )


def test_push_creates_invoices_and_marks_synced(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations.tasks import push_billing_record

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS)
    push_billing_record(rec.pk)

    rec.refresh_from_db()
    guardian.refresh_from_db()
    active_plan.refresh_from_db()
    assert rec.external_status == "synced"
    assert active_plan.external_product_id == f"stub-product-{active_plan.pk}"
    assert guardian.external_client_id == f"stub-client-{guardian.pk}"
    rows = BillingInvoice.objects.filter(billing_record=rec)
    assert rows.count() == 10
    assert all(r.external_invoice_id and r.external_status == "created" for r in rows)


def test_push_is_idempotent(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations.tasks import push_billing_record

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS)
    push_billing_record(rec.pk)
    push_billing_record(rec.pk)
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10
    rec.refresh_from_db()
    assert rec.external_status == "synced"


def test_transient_failure_marks_failed_and_raises(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT)

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformTransientError("down")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    with pytest.raises(tasks.RetryableInvoiceError):
        tasks.push_billing_record(rec.pk)
    rec.refresh_from_db()
    assert rec.external_status == "failed"
    assert rec.external_error_code == "unavailable"


def test_terminal_failure_marks_failed_no_raise(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT)

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformAuthError("401")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    tasks.push_billing_record(rec.pk)  # must NOT raise
    rec.refresh_from_db()
    assert rec.external_status == "failed"
    assert rec.external_error_code == "auth_failed"


# --- Concurrency guard: sibling pushes must not duplicate client/product ---
#
# Two BillingRecords for the same guardian (siblings) are pushed by separate
# django-q worker processes concurrently. Each must resolve the shared client
# (and shared product) without creating a duplicate. The guard re-reads the
# locked row, so an id committed by a concurrent task is reused, not recreated.


def test_ensure_client_id_reuses_id_committed_concurrently(guardian, monkeypatch):
    from apps.members.models import Guardian
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    # A concurrent push already created + committed the client id. Any object
    # loaded before that commit (e.g. via record.member.guardian) is now stale.
    Guardian.objects.filter(pk=guardian.pk).update(external_client_id="racer-client")

    called = False

    def should_not_create(g):
        nonlocal called
        called = True
        return invoice_platform.ClientResult(external_id="duplicate-client")

    monkeypatch.setattr(invoice_platform, "ensure_client", should_not_create)

    result = tasks._ensure_client_id(guardian.pk)

    assert result == "racer-client"
    assert called is False, "must not create a second client when one already exists"
    guardian.refresh_from_db()
    assert guardian.external_client_id == "racer-client"


def test_ensure_client_id_creates_and_persists_when_absent(guardian, monkeypatch):
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    monkeypatch.setattr(
        invoice_platform,
        "ensure_client",
        lambda g: invoice_platform.ClientResult(external_id="fresh-client"),
    )

    result = tasks._ensure_client_id(guardian.pk)

    assert result == "fresh-client"
    guardian.refresh_from_db()
    assert guardian.external_client_id == "fresh-client"


def test_ensure_product_id_reuses_id_committed_concurrently(active_plan, monkeypatch):
    from apps.billing.models import MembershipPlan
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    MembershipPlan.objects.filter(pk=active_plan.pk).update(external_product_id="racer-product")

    called = False

    def should_not_create(p):
        nonlocal called
        called = True
        return invoice_platform.ProductResult(external_id="duplicate-product")

    monkeypatch.setattr(invoice_platform, "ensure_product", should_not_create)

    result = tasks._ensure_product_id(active_plan.pk)

    assert result == "racer-product"
    assert called is False, "must not create a second product when one already exists"
    active_plan.refresh_from_db()
    assert active_plan.external_product_id == "racer-product"
