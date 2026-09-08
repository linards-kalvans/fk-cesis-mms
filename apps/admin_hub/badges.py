"""Status -> badge-class maps for the Admin Hub.

A CSS class is never derived straight from a domain enum value. Two reasons,
both from review findings on this branch:

- A hardcoded class lies. ``queue.html`` once rendered every row with
  ``badge--submitted``, so a rejected application showed a green "submitted"
  pill; ``cockpit.html`` and ``agreement.html`` shipped the same defect.
- An interpolated class fails silently. ``badge--{{ obj.status }}`` resolves
  only while every enum member happens to have a matching rule in ``hub.css``;
  a new member renders unstyled rather than failing.

Lookups therefore go through these maps with an explicit fallback. The class
names are colour roles carried over from the mock-ups, not status names — so
``badge--submitted`` is "the green one", which is why a signed agreement uses
it.
"""

from __future__ import annotations

from apps.agreements.models import Agreement
from apps.registrations.models import RegistrationApplication

FALLBACK_BADGE_CLASS = "badge--neutral"

APPLICATION_STATUS_BADGE_CLASSES: dict[str, str] = {
    str(RegistrationApplication.Status.DRAFT): "badge--draft",
    str(RegistrationApplication.Status.SUBMITTED): "badge--submitted",
    str(RegistrationApplication.Status.FIX_REQUESTED): "badge--fix",
    str(RegistrationApplication.Status.APPROVED): "badge--approved",
    str(RegistrationApplication.Status.REJECTED): "badge--rejected",
}

AGREEMENT_STATE_BADGE_CLASSES: dict[str, str] = {
    str(Agreement.State.GENERATED): "badge--draft",
    # Sent is waiting on the parent, the same posture as a fix request.
    str(Agreement.State.SENT): "badge--fix",
    str(Agreement.State.SIGNED): "badge--submitted",
    str(Agreement.State.VOID): "badge--rejected",
    str(Agreement.State.SUPERSEDED): "badge--neutral",
    str(Agreement.State.DISCONTINUED): "badge--rejected",
}


def application_badge_class(status: str) -> str:
    return APPLICATION_STATUS_BADGE_CLASSES.get(str(status), FALLBACK_BADGE_CLASS)


def agreement_badge_class(state: str) -> str:
    return AGREEMENT_STATE_BADGE_CLASSES.get(str(state), FALLBACK_BADGE_CLASS)
