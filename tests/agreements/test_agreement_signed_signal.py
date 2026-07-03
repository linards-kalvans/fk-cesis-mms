import pytest

pytestmark = pytest.mark.django_db


def test_mark_signed_emits_agreement_signed(agreement_member, default_plan):
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_signed
    from apps.agreements.signals import agreement_signed
    from django.utils import timezone

    agreement = Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
        billing_plan=default_plan,
        first_billing_month="2026-09",
    )
    received = {}

    def receiver(sender, agreement, **kwargs):
        received["agreement"] = agreement

    agreement_signed.connect(receiver)
    try:
        mark_agreement_signed(agreement, actor=None)
    finally:
        agreement_signed.disconnect(receiver)

    assert received["agreement"].pk == agreement.pk
    assert received["agreement"].state == Agreement.State.SIGNED
