"""Magic-link and one-time-code service functions."""

import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import cast
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone as django_timezone

from apps.accounts.models import EmailVerificationCode, MagicLinkToken, ParentAccount

# ---------------------------------------------------------------------------
# Rate-limit tracking (in-memory, app-level)
# ---------------------------------------------------------------------------
_send_timestamps: dict[str, list[float]] = {}


def _get_rate_limit() -> int:
    """Return configured rate limit (per minute per email)."""
    return int(
        getattr(settings, "MAGIC_LINK_RATE_LIMIT_PER_MINUTE", 5),
    )


def _get_ttl_minutes() -> int:
    """Return configured TTL in minutes."""
    return int(getattr(settings, "MAGIC_LINK_TTL_MINUTES", 60))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(raw: str) -> str:
    return sha256(raw.encode()).hexdigest()


def _check_rate_limit(email: str) -> None:
    """Raise ValueError if rate limit exceeded."""
    limit = _get_rate_limit()
    now = _now_utc().timestamp()
    window_start = now - 60.0
    timestamps = _send_timestamps.setdefault(email, [])
    # Prune old entries
    _send_timestamps[email] = [t for t in timestamps if t > window_start]
    if len(_send_timestamps[email]) >= limit:
        raise ValueError("Rate limit exceeded")


def _record_send(email: str) -> None:
    """Record a send timestamp for rate-limit tracking."""
    _send_timestamps.setdefault(email, []).append(_now_utc().timestamp())


def issue_magic_link(account: ParentAccount) -> str:
    """Issue a new magic-link token for *account*.

    Returns the raw (unhashed) token string.  Only one active token
    per account is allowed — raises ``ValueError`` if one already
    exists.

    A token is considered "active" when it is unused and unsent.
    """
    active = account.magic_link_tokens.filter(
        used_at__isnull=True,
        sent_at__isnull=True,
        expires_at__gt=_now_utc(),
    ).exists()
    if active:
        raise ValueError("Active token already exists")

    raw = secrets.token_urlsafe(32)
    ttl = _get_ttl_minutes()
    now = _now_utc()

    MagicLinkToken.objects.create(
        account=account,
        token_hash=_hash_token(raw),
        expires_at=now + timedelta(minutes=ttl),
    )
    return raw


def issue_magic_link_for_email(email: str) -> str:
    """Issue a magic-link token for an email without a ParentAccount.

    Creates a token with account=NULL and claimed_email set.
    Returns the raw (unhashed) token string.
    """
    raw = secrets.token_urlsafe(32)
    ttl = _get_ttl_minutes()
    now = _now_utc()

    MagicLinkToken.objects.create(
        account=None,
        claimed_email=email,
        token_hash=_hash_token(raw),
        expires_at=now + timedelta(minutes=ttl),
    )
    return raw


def send_magic_link_for_claimed_email(email: str, raw_token: str) -> None:
    """Send a magic-link email for a claimed email without ParentAccount."""
    _check_rate_limit(email)

    token = MagicLinkToken.objects.get(
        account__isnull=True,
        claimed_email=email,
        token_hash=_hash_token(raw_token),
        used_at__isnull=True,
    )
    token.sent_at = _now_utc()
    token.save(update_fields=["sent_at"])

    verify_url = build_magic_link_verify_url(raw_token)

    subject = "Log in to FK Cēsis MMS"
    body = f"Click here to log in: {verify_url}"

    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        recipient_list=[email],
        fail_silently=False,
    )
    _record_send(email)


def send_magic_link(account: ParentAccount, raw_token: str) -> None:
    """Send magic-link email to *account* with the verify URL.

    Marks the token as sent so ``issue_magic_link`` can issue a
    replacement.  The token remains consumable until
    ``consume_magic_link`` marks it used.
    """
    _check_rate_limit(account.email)

    token = MagicLinkToken.objects.get(
        account=account,
        token_hash=_hash_token(raw_token),
        used_at__isnull=True,
    )
    token.sent_at = _now_utc()
    token.save(update_fields=["sent_at"])

    verify_url = build_magic_link_verify_url(raw_token)

    subject = "Log in to FK Cēsis MMS"
    body = f"Click here to log in: {verify_url}"

    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        recipient_list=[account.email],
        fail_silently=False,
    )
    _record_send(account.email)


def _ensure_parent_account(email: str) -> ParentAccount:
    """Get or create a ParentAccount for the given email."""
    account, _ = ParentAccount.objects.get_or_create(
        email=email,
        defaults={"phone": ""},
    )
    return cast(ParentAccount, account)


def build_magic_link_verify_url(raw_token: str) -> str:
    verify_url = urljoin(
        getattr(settings, "SITE_URL", "http://localhost"),
        f"/accounts/verify/{raw_token}/",
    )
    # Strip trailing slash so the debug HTML link and test regex
    # don't produce double slashes (test appends its own "/").
    return verify_url.rstrip("/")


def consume_magic_link(raw_token: str) -> ParentAccount:
    """Consume a magic-link token and return the associated account.

    If the token has no account (claimed-email flow), a ParentAccount
    is created for the email stored on the token.

    Raises ``ValueError`` if the token is invalid, expired, already
    used, or the account is inactive.
    """
    token = MagicLinkToken.objects.filter(
        token_hash=_hash_token(raw_token),
        used_at__isnull=True,
    ).first()

    if token is None:
        raise ValueError("Invalid or already consumed token")

    if token.expires_at < _now_utc():
        raise ValueError("Token expired")

    account = token.account

    # Claimed-email flow: no ParentAccount yet — create one
    if account is None:
        email = token.claimed_email
        if not email:
            raise ValueError("Token has no associated email")
        account = _ensure_parent_account(email)
        token.used_at = _now_utc()
        token.account = account
        token.save(update_fields=["account", "used_at"])

        # Attach matching claimed-email applications to the new parent
        from apps.registrations.services import attach_claimed_email_apps_to_parent

        attach_claimed_email_apps_to_parent(email, account)
    else:
        if not account.is_active:
            raise ValueError("Account is inactive")
        token.used_at = _now_utc()
        token.save(update_fields=["used_at"])

    return cast(ParentAccount, account)


# ---------------------------------------------------------------------------
# One-time code for registration entry
# ---------------------------------------------------------------------------

_OTP_RATE_LIMIT_KEY = "ONE_TIME_CODE_RATE_LIMIT_PER_MINUTE"
_OTP_CODE_LENGTH = 6


def _get_otp_rate_limit() -> int:
    return int(getattr(settings, _OTP_RATE_LIMIT_KEY, 3))


def _get_otp_ttl_seconds() -> int:
    return int(getattr(settings, "ONE_TIME_CODE_TTL_SECONDS", 300))


def issue_one_time_code(email: str) -> str:
    """Issue a 6-digit one-time code for *email*.

    Returns the raw code string.  Respects rate-limit per email.
    """
    limit = _get_otp_rate_limit()
    now = _now_utc().timestamp()
    window_start = now - 60.0
    timestamps = _send_timestamps.setdefault(email, [])
    _send_timestamps[email] = [t for t in timestamps if t > window_start]
    if len(_send_timestamps[email]) >= limit:
        raise ValueError("Rate limit exceeded")

    code = str(secrets.randbelow(10**_OTP_CODE_LENGTH)).zfill(_OTP_CODE_LENGTH)
    ttl = _get_otp_ttl_seconds()

    EmailVerificationCode.objects.create(
        email=email,
        code_hash=_hash_token(code),
        expires_at=django_timezone.now() + timedelta(seconds=ttl),
    )
    return code


def send_one_time_code_email(email: str, raw_code: str) -> None:
    """Send the one-time code to *email*."""
    subject = "Jūsu piekļuves kods — FK Cēsis MMS"
    body = f"Jūsu piekļuves kods ir: {raw_code}\n\nŠis kods ir spēkā 5 minūtes."

    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com"),
        recipient_list=[email],
        fail_silently=False,
    )
    _record_send(email)


def verify_one_time_code(email: str, code: str) -> ParentAccount:
    """Verify a one-time code for *email*.

    Returns the ``ParentAccount``.  Creates one for new emails.
    Raises ``ValueError`` on bad/expired/used code.
    """
    record = (
        EmailVerificationCode.objects.filter(
            email__iexact=email,
            code_hash=_hash_token(code),
            used_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )

    if record is None:
        raise ValueError("Invalid code")

    if record.is_expired:
        raise ValueError("Code expired")

    # Mark used (single-use)
    record.used_at = django_timezone.now()
    record.save(update_fields=["used_at"])

    # Get or create parent account (email is unique, case-sensitive lookup)
    account, _ = ParentAccount.objects.get_or_create(
        email=email,
        defaults={"phone": ""},
    )

    from apps.registrations.services import attach_claimed_email_apps_to_parent

    attach_claimed_email_apps_to_parent(email, cast(ParentAccount, account))
    return cast(ParentAccount, account)


@transaction.atomic
def change_parent_email(account: ParentAccount, new_email: str) -> ParentAccount:
    """Change a parent's verified email (admin-initiated).

    Normalizes the new email, enforces the unique constraint (rejecting an
    email already owned by another account, case-insensitive), persists it,
    and updates the linked Guardian.email mirror in the same transaction.
    No-op when the email is unchanged. Raises ValueError on collision.
    """
    normalized = new_email.strip().lower()
    if not normalized:
        raise ValueError("new email is required")
    if normalized == account.email.lower():
        return account

    clash = (
        ParentAccount.objects.filter(email__iexact=normalized)
        .exclude(pk=account.pk)
        .exists()
    )
    if clash:
        raise ValueError("email already in use by another account")

    account.email = normalized
    account.save(update_fields=["email", "updated_at"])

    from apps.members.models import Guardian

    Guardian.objects.filter(parent_account=account).update(email=normalized)
    return account
