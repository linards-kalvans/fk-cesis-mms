"""Service functions for the agreements domain."""

from __future__ import annotations

from typing import cast

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member


def get_current_agreement(member: Member) -> Agreement | None:
    """Return the member's current (non-archived) agreement, or None."""
    return cast("Agreement | None", member.agreements.filter(is_current=True).first())


def create_agreement_for_member(
    member: Member,
    signing_path: str,
) -> Agreement:
    """Return the current agreement when it exists and is not void; otherwise
    archive any void current and create a fresh row. Idempotent on the
    happy path."""
    current = get_current_agreement(member)
    if current is not None and current.state != Agreement.State.VOID:
        return current
    if current is not None and current.state == Agreement.State.VOID:
        current.is_current = False
        current.save(update_fields=["is_current"])
    return cast(
        "Agreement",
        Agreement.objects.create(
            member=member,
            signing_path=signing_path,
            generated_at=timezone.now(),
        ),
    )


def mark_agreement_sent(
    agreement: Agreement,
    actor,  # AUTH_USER_MODEL — plumbed for P7 audit hook  # noqa: ARG001
) -> Agreement:
    """generated → sent. Sets sent_at, sends Latvian email to guardian."""
    if agreement.state != Agreement.State.GENERATED:
        raise ValueError(
            f"cannot mark sent from state {agreement.state}"
        )
    agreement.state = Agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])
    _render_and_send_agreement_email(agreement, template_name="sent")
    return agreement


def mark_agreement_signed(
    agreement: Agreement,
    actor,  # noqa: ARG001
) -> Agreement:
    """{generated, sent} → signed. Sets signed_at, sends Latvian email."""
    if agreement.state not in (Agreement.State.GENERATED, Agreement.State.SENT):
        raise ValueError(
            f"cannot mark signed from state {agreement.state}"
        )
    agreement.state = Agreement.State.SIGNED
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "signed_at"])
    _render_and_send_agreement_email(agreement, template_name="signed")
    return agreement


def void_agreement(
    agreement: Agreement,
    actor,  # noqa: ARG001
    reason: str,
) -> Agreement:
    """Any non-void state → void. Keeps is_current=True. No email.
    Idempotent on void → void (early return, no UPDATE)."""
    if agreement.state == Agreement.State.VOID:
        return agreement
    agreement.state = Agreement.State.VOID
    agreement.voided_at = timezone.now()
    agreement.void_reason = reason
    agreement.save(update_fields=["state", "voided_at", "void_reason"])
    return agreement


def regenerate_agreement(
    member: Member,
    signing_path: str,
    actor,  # noqa: ARG001
) -> Agreement:
    """Archive a void current agreement and create a fresh one. Refuses to
    clobber a non-void current."""
    current = get_current_agreement(member)
    if current is None:
        raise ValueError("no agreement exists to regenerate")
    if current.state != Agreement.State.VOID:
        raise ValueError("active agreement cannot be replaced")
    return create_agreement_for_member(member, signing_path)


def set_signing_path(
    agreement: Agreement,
    signing_path: str,
    actor,  # noqa: ARG001
) -> Agreement:
    """Change signing_path at any state. No email. Idempotent on same value."""
    if agreement.signing_path == signing_path:
        return agreement
    agreement.signing_path = signing_path
    agreement.save(update_fields=["signing_path"])
    return agreement


def sync_application_signing_path_to_agreement(application) -> None:
    """Sync a staff-edited application's preferred_agreement_signing into the
    member's current agreement IFF the agreement is still in ``generated``
    state. No-op otherwise: post-generated agreements (sent / signed / void)
    are managed only via the admin review-detail Līgums module, and an empty
    preference never clears an agreement's concrete signing path.

    Called from RegistrationApplicationAdmin.save_model so staff edits to the
    application's preference propagate naturally while the agreement window
    is still open.
    """
    member = getattr(application, "approved_member", None)
    if member is None:
        return
    agreement = get_current_agreement(member)
    if agreement is None:
        return
    if agreement.state != Agreement.State.GENERATED:
        return
    desired = application.preferred_agreement_signing
    if not desired:
        return
    if agreement.signing_path == desired:
        return
    agreement.signing_path = desired
    agreement.save(update_fields=["signing_path"])


def _render_and_send_agreement_email(
    agreement: Agreement,
    template_name: str,
) -> None:
    """Render an agreement plain-text email and send to the guardian."""
    member = agreement.member
    guardian = member.guardian
    portal_url = f"{settings.SITE_URL}{reverse('registrations:parent-portal')}"
    context = {
        "guardian_full_name": guardian.full_name,
        "member_full_name": member.full_name,
        "signing_path": agreement.signing_path,
        "portal_url": portal_url,
    }
    body = render_to_string(f"emails/agreements/{template_name}.txt", context)
    subject = {
        "sent": "Jūsu līgums ir nosūtīts parakstīšanai",
        "signed": "Jūsu līgums ir parakstīts",
    }[template_name]
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[guardian.email],
        fail_silently=False,
    )
