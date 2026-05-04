"""Task 4 — ParentAccount, MagicLinkToken, services RED tests.

Contracts:
  - issue_magic_link(account) -> raw_token: str  (DB stores only hash)
  - send_magic_link(account, raw_token) -> None  (emails magic-link URL)
  - consume_magic_link(raw_token) -> account  (first use only)
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.db import IntegrityError
from django.test import override_settings

from apps.accounts.models import ParentAccount, MagicLinkToken

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# ParentAccount model
# ---------------------------------------------------------------------------

class TestParentAccountModel:

    def test_create_has_email_phone_is_active(self):
        acct = ParentAccount.objects.create(
            email="parent@example.com",
            phone="+37120000000",
            is_active=True,
        )
        assert acct.email == "parent@example.com"
        assert acct.phone == "+37120000000"
        assert acct.is_active is True

    def test_email_unique(self):
        ParentAccount.objects.create(
            email="unique@example.com",
            phone="+3711111111",
        )
        with pytest.raises(IntegrityError):
            ParentAccount.objects.create(
                email="unique@example.com",
                phone="+3712222222",
            )

    def test_is_active_defaults_true(self):
        acct = ParentAccount.objects.create(
            email="default@example.com",
            phone="+3713333333",
        )
        assert acct.is_active is True


# ---------------------------------------------------------------------------
# MagicLinkToken model fields
# ---------------------------------------------------------------------------

class TestMagicLinkTokenModel:

    def test_has_account_fk(self):
        acct = ParentAccount.objects.create(
            email="fk@example.com",
            phone="+3714444444",
        )
        # After issue() the token record must reference the account.
        from apps.accounts.services import issue_magic_link
        issue_magic_link(acct)
        record = MagicLinkToken.objects.get(account=acct)
        assert record.account == acct

    def test_stores_hash_not_raw(self):
        acct = ParentAccount.objects.create(
            email="hash@example.com",
            phone="+3715555555",
        )
        from apps.accounts.services import issue_magic_link
        raw = issue_magic_link(acct)
        record = MagicLinkToken.objects.get(account=acct)
        assert record.token_hash != raw

    def test_default_ttl_60_minutes(self):
        acct = ParentAccount.objects.create(
            email="sixty@example.com",
            phone="+3716666666",
        )
        from apps.accounts.services import issue_magic_link
        issue_magic_link(acct)
        record = MagicLinkToken.objects.get(account=acct)
        expected = record.created_at + timedelta(minutes=60)
        assert abs((record.expires_at - expected).total_seconds()) <= 1

    def test_custom_ttl_via_settings(self):
        with override_settings(MAGIC_LINK_TTL_MINUTES=30):
            acct = ParentAccount.objects.create(
                email="thirty@example.com",
                phone="+3717777777",
            )
            from apps.accounts.services import issue_magic_link
            issue_magic_link(acct)
            record = MagicLinkToken.objects.get(account=acct)
            expected = record.created_at + timedelta(minutes=30)
            assert abs((record.expires_at - expected).total_seconds()) <= 1


# ---------------------------------------------------------------------------
# Services — issue_magic_link
# ---------------------------------------------------------------------------

class TestIssueMagicLink:

    def test_returns_raw_token_string(self):
        acct = ParentAccount.objects.create(
            email="issue@example.com",
            phone="+3718888888",
        )
        from apps.accounts.services import issue_magic_link
        raw = issue_magic_link(acct)
        assert isinstance(raw, str)
        assert len(raw) > 0

    def test_only_one_active_token_per_account(self):
        acct = ParentAccount.objects.create(
            email="single@example.com",
            phone="+3719999999",
        )
        from apps.accounts.services import issue_magic_link
        first = issue_magic_link(acct)
        # A second issue should raise (single active token enforced).
        with pytest.raises(ValueError):
            issue_magic_link(acct)


# ---------------------------------------------------------------------------
# Services — send_magic_link
# ---------------------------------------------------------------------------

class TestSendMagicLink:

    def test_sends_email(self):
        acct = ParentAccount.objects.create(
            email="send@example.com",
            phone="+3710000000",
        )
        from apps.accounts.services import issue_magic_link, send_magic_link
        raw = issue_magic_link(acct)
        send_magic_link(acct, raw)
        assert len(mail.outbox) == 1
        assert "send@example.com" in mail.outbox[0].to

    def test_email_contains_verify_url(self):
        acct = ParentAccount.objects.create(
            email="url@example.com",
            phone="+3711234567",
        )
        from apps.accounts.services import issue_magic_link, send_magic_link
        raw = issue_magic_link(acct)
        send_magic_link(acct, raw)
        body = mail.outbox[0].body.lower()
        assert "/accounts/verify/" in body


# ---------------------------------------------------------------------------
# Services — consume_magic_link
# ---------------------------------------------------------------------------

class TestConsumeMagicLink:

    def test_first_consume_returns_account(self):
        acct = ParentAccount.objects.create(
            email="consume@example.com",
            phone="+3712345678",
        )
        from apps.accounts.services import issue_magic_link, consume_magic_link
        raw = issue_magic_link(acct)
        result = consume_magic_link(raw)
        assert result == acct

    def test_second_consume_raises(self):
        acct = ParentAccount.objects.create(
            email="twice@example.com",
            phone="+3713456789",
        )
        from apps.accounts.services import issue_magic_link, consume_magic_link
        raw = issue_magic_link(acct)
        consume_magic_link(raw)
        with pytest.raises(ValueError):
            consume_magic_link(raw)

    def test_expired_token_raises(self):
        acct = ParentAccount.objects.create(
            email="expired@example.com",
            phone="+3714567890",
        )
        from apps.accounts.services import issue_magic_link, consume_magic_link
        raw = issue_magic_link(acct)
        record = MagicLinkToken.objects.get(account=acct)
        record.created_at = record.created_at - timedelta(hours=2)
        record.expires_at = record.expires_at - timedelta(hours=2)
        record.save(update_fields=["created_at", "expires_at"])
        with pytest.raises(ValueError):
            consume_magic_link(raw)

    def test_inactive_account_raises(self):
        acct = ParentAccount.objects.create(
            email="inactive@example.com",
            phone="+3715678901",
            is_active=False,
        )
        from apps.accounts.services import issue_magic_link, consume_magic_link
        raw = issue_magic_link(acct)
        with pytest.raises(ValueError):
            consume_magic_link(raw)


# ---------------------------------------------------------------------------
# Rate limiting — configurable via settings
# ---------------------------------------------------------------------------

class TestRateLimiting:

    @override_settings(MAGIC_LINK_RATE_LIMIT_PER_MINUTE=1)
    def test_one_send_allowed(self):
        from apps.accounts.services import issue_magic_link, send_magic_link

        acct = ParentAccount.objects.create(
            email="rate@example.com",
            phone="+3716789012",
        )
        raw = issue_magic_link(acct)
        send_magic_link(acct, raw)  # allowed
        assert len(mail.outbox) == 1

    @override_settings(MAGIC_LINK_RATE_LIMIT_PER_MINUTE=1)
    def test_second_send_in_window_raises(self):
        from apps.accounts.services import issue_magic_link, send_magic_link

        acct = ParentAccount.objects.create(
            email="ratetwo@example.com",
            phone="+3717890123",
        )
        raw1 = issue_magic_link(acct)
        send_magic_link(acct, raw1)
        raw2 = issue_magic_link(acct)
        with pytest.raises(ValueError):
            send_magic_link(acct, raw2)
