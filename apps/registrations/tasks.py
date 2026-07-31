"""Background-job functions for the registrations app.

The P19 daily submitted-registration digest:

- ``send_submitted_registration_digest`` is the django-q2 job body. It sends
  one Bcc plain-text email summarising every submitted application that has
  not yet been included in a digest, and stamps per-row + singleton
  delivery timestamps on success.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.registrations.models import (
    RegistrationApplication,
    RegistrationSubmissionDigestSettings,
)

logger = logging.getLogger(__name__)


def _build_entries(locked_apps):
    """Build the per-application template context (PII-free)."""
    site_url = settings.SITE_URL
    entries = []
    for app in locked_apps:
        change_path = reverse(
            "admin:registrations_registrationapplication_change", args=[app.pk]
        )
        entries.append(
            {
                "child": app.member_full_name,
                "guardian": app.guardian_name,
                "submitted_at": timezone.localtime(app.submitted_at).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "status": app.get_status_display(),
                "admin_url": f"{site_url}{change_path}",
            }
        )
    return entries


def send_submitted_registration_digest() -> int:
    """Send one Bcc digest for pending submissions; return delivered count."""
    User = get_user_model()
    with transaction.atomic():
        # Lock the singleton (created by migration 0012). get_or_create
        # is not used here — the migration guarantees existence, and
        # a missing row means the admin has not finished setup.
        try:
            settings_obj = (
                RegistrationSubmissionDigestSettings.objects.select_for_update()
                .get(pk=1)
            )
        except RegistrationSubmissionDigestSettings.DoesNotExist:
            return 0

        # Pending rows: submitted_at set, never included in a digest yet.
        # Do NOT filter on current status — submissions move through
        # submitted → fix_requested → submitted (and ultimately to
        # approved / rejected) but each new submission event must still
        # be reported.
        # `of=("self",)` restricts the row lock to RegistrationApplication
        # only — the LEFT OUTER JOIN to nullable `guardian` would otherwise
        # make PostgreSQL reject a bare FOR UPDATE (Django 6).
        locked_apps = list(
            RegistrationApplication.objects.select_for_update(of=("self",))
            .select_related("guardian")
            .filter(
                submitted_at__isnull=False,
                submission_digest_sent_at__isnull=True,
            )
            .order_by("submitted_at", "pk")
        )

        if not locked_apps:
            return 0

        # Re-query recipients at runtime: only currently-active staff Users
        # count. Inactive / non-staff rows attached directly via the
        # M2M are silently filtered out, never raise.
        recipients = list(
            User.objects.filter(
                pk__in=settings_obj.recipients.values_list("pk", flat=True),
                is_active=True,
                is_staff=True,
            ).only("email")
        )
        if not recipients:
            logger.error(
                "submission digest: no active staff recipients configured"
            )
            return 0
        if any(not (user.email and user.email.strip()) for user in recipients):
            logger.error(
                "submission digest: active staff recipient has blank email"
            )
            return 0
        recipient_emails = [user.email.strip() for user in recipients]

        entries = _build_entries(locked_apps)
        body = render_to_string(
            "emails/registrations/submission_digest.txt", {"entries": entries}
        )
        subject = f"Jauni iesniegtie pieteikumi ({len(locked_apps)})"
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[],
            bcc=recipient_emails,
        )
        try:
            sent = message.send(fail_silently=False)
        except Exception:
            logger.error("submission digest: send raised")
            return 0
        if sent != 1:
            logger.error("submission digest: send returned non-success")
            return 0

        # Success — stamp per-row + singleton with the same instant so the
        # operator-facing "last delivery" line matches the row timestamps.
        delivered_at = timezone.now()
        RegistrationApplication.objects.filter(
            pk__in=[a.pk for a in locked_apps]
        ).update(submission_digest_sent_at=delivered_at)
        settings_obj.last_successful_at = delivered_at
        settings_obj.save(update_fields=["last_successful_at"])

    return len(locked_apps)
