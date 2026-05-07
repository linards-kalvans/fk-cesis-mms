"""Magic-link service functions."""

import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import cast
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import send_mail

from apps.accounts.models import MagicLinkToken, ParentAccount

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
