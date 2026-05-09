"""ParentAccount, MagicLinkToken, and EmailVerificationCode models."""

from django.db import models

from apps.core.models import TimeStampedModel


class ParentAccount(TimeStampedModel):
    """A parent/guardian account for magic-link auth."""

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = "parent account"


class MagicLinkToken(TimeStampedModel):
    """Hashed magic-link token linked to a ParentAccount.

    For claimed-email verification (no ParentAccount yet), account is NULL
    and claimed_email stores the email to verify.
    """

    account = models.ForeignKey(
        "accounts.ParentAccount",
        on_delete=models.CASCADE,
        related_name="magic_link_tokens",
        null=True,
        blank=True,
    )
    claimed_email = models.EmailField(blank=True, default="")
    token_hash = models.CharField(max_length=256, unique=True)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        email = self.account.email if self.account else self.claimed_email
        return f"Token for {email}"

    class Meta:
        verbose_name = "magic link token"


class EmailVerificationCode(TimeStampedModel):
    """One-time 6-digit code for registration entry verification."""

    email = models.EmailField()
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Code for {self.email}"

    @property
    def is_expired(self):
        from django.utils import timezone

        return timezone.now() > self.expires_at

    class Meta:
        verbose_name = "email verification code"
