"""Billing signal receivers. Connected in BillingConfig.ready()."""

from __future__ import annotations


def on_agreement_signed(sender, agreement, **kwargs):
    from apps.billing.services import create_draft_billing_for_member

    create_draft_billing_for_member(agreement.member, agreement=agreement)


def connect_billing_signals() -> None:
    from apps.agreements.signals import agreement_signed

    agreement_signed.connect(
        on_agreement_signed,
        dispatch_uid="billing.on_agreement_signed",
    )
