"""Service functions for the agreements domain."""

from __future__ import annotations

from typing import cast

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent
from apps.members.models import Member


def get_current_agreement(member: Member) -> Agreement | None:
    """Return the member's current (non-archived) agreement, or None."""
    return cast(
        "Agreement | None",
        member.agreements.select_related("member__guardian__parent_account")
        .filter(is_current=True)
        .first(),
    )


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
    actor,  # AUTH_USER_MODEL — plumbed for P7 audit hook
) -> Agreement:
    """generated → sent. Paper path: Latvian email to guardian. Electronic
    path: optimistic sent, suppress email, enqueue DocuSeal create. When
    electronic but guardian has no email, fall back to paper first."""
    if agreement.state != Agreement.State.GENERATED:
        raise ValueError(f"cannot mark sent from state {agreement.state}")

    # Electronic requires a guardian email to send the signing request.
    # Without one, degrade to the paper (staff-managed) path before sending.
    if (
        agreement.signing_path == Agreement.SigningPath.ELECTRONIC
        and not agreement.member.guardian.email
    ):
        set_signing_path(agreement, str(Agreement.SigningPath.PAPER), actor)

    agreement.state = Agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])
    record_audit_event(
        action=str(AuditEvent.Action.AGREEMENT_SENT),
        actor=actor,
        target=agreement,
        metadata={"signing_path": agreement.signing_path},
    )
    _render_and_send_agreement_email(agreement, template_name="sent")

    if agreement.signing_path == Agreement.SigningPath.ELECTRONIC:
        from apps.integrations.tasks import enqueue_create_agreement_submission

        enqueue_create_agreement_submission(agreement.id)
    return agreement


def mark_agreement_signed(
    agreement: Agreement,
    actor,
) -> Agreement:
    """{generated, sent} → signed. Sets signed_at, sends Latvian email, emits
    the agreement_signed signal (billing listens)."""
    if agreement.state not in (Agreement.State.GENERATED, Agreement.State.SENT):
        raise ValueError(
            f"cannot mark signed from state {agreement.state}"
        )
    agreement.state = Agreement.State.SIGNED
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "signed_at"])
    record_audit_event(
        action=str(AuditEvent.Action.AGREEMENT_SIGNED),
        actor=actor,
        target=agreement,
        actor_label="" if actor else "system: docuseal_webhook",
    )
    _render_and_send_agreement_email(agreement, template_name="signed")

    from apps.agreements.signals import agreement_signed

    agreement_signed.send(sender=Agreement, agreement=agreement)
    return agreement


def void_agreement(
    agreement: Agreement,
    actor,
    reason: str,
) -> Agreement:
    """Any non-void state → void. Keeps is_current=True. Sends a Latvian
    plain-text notification to the guardian (both paths). For an electronic
    agreement with a live DocuSeal submission, also enqueues an archive job.
    Idempotent on void → void (early return, no UPDATE, no second email)."""
    if agreement.state == Agreement.State.VOID:
        return agreement
    agreement.state = Agreement.State.VOID
    agreement.voided_at = timezone.now()
    agreement.void_reason = reason
    agreement.save(update_fields=["state", "voided_at", "void_reason"])
    record_audit_event(
        action=str(AuditEvent.Action.AGREEMENT_VOIDED),
        actor=actor,
        target=agreement,
    )
    _render_and_send_agreement_email(agreement, template_name="void")

    if (
        agreement.signing_path == Agreement.SigningPath.ELECTRONIC
        and agreement.external_id
    ):
        from apps.integrations.tasks import enqueue_archive_agreement_submission

        enqueue_archive_agreement_submission(agreement.external_id)
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
    """Change signing_path at any state. Bidirectional sync: also writes back
    to the source application's ``preferred_agreement_signing`` so the two
    fields never drift. No email. Idempotent on same value (no writes when
    the agreement is already at the desired path)."""
    if agreement.signing_path == signing_path:
        return agreement
    agreement.signing_path = signing_path
    agreement.save(update_fields=["signing_path"])
    application = getattr(agreement.member, "source_application", None)
    if application is not None and application.preferred_agreement_signing != signing_path:
        application.preferred_agreement_signing = signing_path
        application.save(update_fields=["preferred_agreement_signing"])
    return agreement


def sync_application_signing_path_to_agreement(application) -> None:
    """Sync a staff-edited application's preferred_agreement_signing into the
    member's current agreement. Updates regardless of agreement state — the
    two fields are always equal post-approval (bidirectional sync invariant).
    An empty preference never clears a concrete agreement signing path.

    Called from RegistrationApplicationAdmin.save_model so staff edits to the
    application's preference propagate to the agreement; the reverse direction
    (picker → application) lives inside ``set_signing_path``.
    """
    member = getattr(application, "approved_member", None)
    if member is None:
        return
    agreement = get_current_agreement(member)
    if agreement is None:
        return
    desired = application.preferred_agreement_signing
    if not desired:
        return
    if agreement.signing_path == desired:
        return
    agreement.signing_path = desired
    agreement.save(update_fields=["signing_path"])


def _should_send_email(agreement: Agreement, template_name: str) -> bool:
    """Electronic path suppresses `sent`/`signed` (DocuSeal notifies the
    signer). `void` always sends; paper sends on all transitions."""
    if (
        agreement.signing_path == Agreement.SigningPath.ELECTRONIC
        and template_name in {"sent", "signed"}
    ):
        return False
    return True


def _render_and_send_agreement_email(
    agreement: Agreement,
    template_name: str,
) -> None:
    """Render an agreement plain-text email and send to the guardian."""
    if not _should_send_email(agreement, template_name):
        return
    member = agreement.member
    guardian = member.guardian
    portal_url = f"{settings.SITE_URL}{reverse('registrations:parent-portal')}"
    context = {
        "guardian_full_name": guardian.full_name,
        "member_full_name": member.full_name,
        "signing_path": agreement.signing_path,
        "void_reason": agreement.void_reason,
        "portal_url": portal_url,
    }
    body = render_to_string(f"emails/agreements/{template_name}.txt", context)
    subject = {
        "sent": "Jūsu līgums ir nosūtīts parakstīšanai",
        "signed": "Jūsu līgums ir parakstīts",
        "void": "Jūsu līgums ir atcelts",
    }[template_name]
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[guardian.email],
        fail_silently=False,
    )
