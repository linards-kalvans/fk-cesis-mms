"""Service-layer tests for personal-data-consent stamping behavior.

P4 Slice C, Task 3. Covers `create_or_update_draft` recording consent on the
`RegistrationApplication` when the form provides ``personal_data_consent=True``.

Stamping rules under test:
- First grant: write timestamp + current version.
- Idempotent: no refresh when stored version already matches current.
- Version upgrade: refresh timestamp + version when stored version differs.
- False/absent: never clears an existing stamp; never stamps a fresh app.
- Orthogonal to fix_requested status.

Also covers schema smoke tests for consent model fields (folded from RED-phase
test_personal_data_consent_schema.py).
"""

from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.registrations.models import (
    PERSONAL_DATA_CONSENT_VERSION,
    RegistrationApplication,
)
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Schema smoke tests (folded from test_personal_data_consent_schema.py)
# ---------------------------------------------------------------------------


class TestSchema:
    """Schema smoke tests for personal-data-consent fields on RegistrationApplication."""

    def test_consent_version_constant_exposed(self):
        assert isinstance(PERSONAL_DATA_CONSENT_VERSION, str)
        assert PERSONAL_DATA_CONSENT_VERSION  # non-empty

    def test_consent_fields_default_to_null(self):
        app = RegistrationApplication.objects.create()
        assert app.personal_data_consent_at is None
        assert app.personal_data_consent_version is None

    def test_consent_fields_persist_when_set(self):
        when = datetime(2026, 5, 23, 12, 0, tzinfo=dt_timezone.utc)
        app = RegistrationApplication.objects.create(
            personal_data_consent_at=when,
            personal_data_consent_version=PERSONAL_DATA_CONSENT_VERSION,
        )
        app.refresh_from_db()
        assert app.personal_data_consent_at == when
        assert app.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_application(email: str = "parent@example.com", **extra) -> RegistrationApplication:
    """Persist a bare-bones draft application for stamping tests."""
    app: RegistrationApplication = RegistrationApplication.objects.create(
        claimed_email=email,
        **extra,
    )
    return app


def _base_data(email: str = "parent@example.com", **overrides) -> dict:
    """Minimal cleaned_data dict for create_or_update_draft."""
    payload = {"guardian_email": email}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_consent_true_stamps_timestamp_and_version_on_first_save():
    app = _make_application()
    assert app.personal_data_consent_at is None
    assert app.personal_data_consent_version is None

    before = timezone.now()
    result = create_or_update_draft(
        data=_base_data(personal_data_consent=True),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_at is not None
    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION
    # Timestamp is within the call window (allow generous +/- 5s).
    assert (result.personal_data_consent_at - before).total_seconds() >= -1
    assert (timezone.now() - result.personal_data_consent_at).total_seconds() < 5


def test_consent_true_is_idempotent_when_version_matches():
    past = timezone.now() - timedelta(days=3)
    app = _make_application(
        personal_data_consent_at=past,
        personal_data_consent_version=PERSONAL_DATA_CONSENT_VERSION,
    )

    result = create_or_update_draft(
        data=_base_data(personal_data_consent=True),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_at == past
    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION


def test_consent_true_refreshes_when_version_mismatches():
    past = timezone.now() - timedelta(days=10)
    app = _make_application(
        personal_data_consent_at=past,
        personal_data_consent_version="v0-test",
    )

    before = timezone.now()
    result = create_or_update_draft(
        data=_base_data(personal_data_consent=True),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION
    assert result.personal_data_consent_at != past
    assert result.personal_data_consent_at >= before - timedelta(seconds=1)
    assert (timezone.now() - result.personal_data_consent_at).total_seconds() < 5


def test_consent_false_does_not_clear_existing_stamp():
    past = timezone.now() - timedelta(days=2)
    app = _make_application(
        personal_data_consent_at=past,
        personal_data_consent_version=PERSONAL_DATA_CONSENT_VERSION,
    )

    result = create_or_update_draft(
        data=_base_data(personal_data_consent=False),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_at == past
    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION


def test_consent_absent_key_does_not_clear_existing_stamp():
    past = timezone.now() - timedelta(days=2)
    app = _make_application(
        personal_data_consent_at=past,
        personal_data_consent_version=PERSONAL_DATA_CONSENT_VERSION,
    )

    # Note: no `personal_data_consent` key in data at all.
    result = create_or_update_draft(
        data=_base_data(),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_at == past
    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION


def test_consent_false_on_unstamped_application_remains_unstamped():
    app = _make_application()

    result = create_or_update_draft(
        data=_base_data(personal_data_consent=False),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_at is None
    assert result.personal_data_consent_version is None


def test_consent_stamping_preserves_fix_requested_status():
    app = _make_application(
        status=RegistrationApplication.Status.FIX_REQUESTED,
    )
    assert app.personal_data_consent_at is None

    result = create_or_update_draft(
        data=_base_data(personal_data_consent=True),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.status == RegistrationApplication.Status.FIX_REQUESTED
    assert result.personal_data_consent_at is not None
    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION


def test_consent_stamping_does_not_break_draft_save_for_non_consent_fields():
    app = _make_application()

    result = create_or_update_draft(
        data=_base_data(
            guardian_full_name="Jānis Bērziņš",
            personal_data_consent=True,
        ),
        files={},
        application=app,
    )
    result.refresh_from_db()

    assert result.personal_data_consent_at is not None
    assert result.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION
