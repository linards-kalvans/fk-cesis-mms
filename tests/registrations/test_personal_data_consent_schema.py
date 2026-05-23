"""Schema smoke tests for personal-data-consent fields on RegistrationApplication."""

from datetime import datetime, timezone

import pytest

from apps.registrations.models import (
    PERSONAL_DATA_CONSENT_VERSION,
    RegistrationApplication,
)


def test_consent_version_constant_exposed():
    assert isinstance(PERSONAL_DATA_CONSENT_VERSION, str)
    assert PERSONAL_DATA_CONSENT_VERSION  # non-empty


@pytest.mark.django_db
def test_consent_fields_default_to_null():
    app = RegistrationApplication.objects.create(guardian_email="parent@example.com")
    assert app.personal_data_consent_at is None
    assert app.personal_data_consent_version is None


@pytest.mark.django_db
def test_consent_fields_persist_when_set():
    when = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    app = RegistrationApplication.objects.create(
        guardian_email="parent@example.com",
        personal_data_consent_at=when,
        personal_data_consent_version=PERSONAL_DATA_CONSENT_VERSION,
    )
    app.refresh_from_db()
    assert app.personal_data_consent_at == when
    assert app.personal_data_consent_version == PERSONAL_DATA_CONSENT_VERSION
