"""Durable per-row agreement document routing (Task 1).

These tests define the contract for the additive ``document_backend`` field and
the new-row selection rule.  Existing rows must never be reclassified by a
setting change or a rolled-back creation.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

DOCUSEAL = "docuseal"
LOCAL = "local"


def _create_agreement(member, signing_path="paper"):
    from apps.agreements.services import create_agreement_for_member

    return create_agreement_for_member(member, signing_path)


def _extra_member(guardian, name="Otrais Bērns"):
    from apps.members.models import Member

    return Member.objects.create(full_name=name, guardian=guardian)


def test_document_backend_field_contract():
    from apps.agreements.models import Agreement

    field = Agreement._meta.get_field("document_backend")
    assert field.default == DOCUSEAL
    assert {value for value, _label in field.choices} == {DOCUSEAL, LOCAL}
    assert Agreement.DocumentBackend.DOCUSEAL == DOCUSEAL
    assert Agreement.DocumentBackend.LOCAL == LOCAL


def test_document_mode_defaults_to_docuseal(settings):
    assert settings.AGREEMENT_DOCUMENT_MODE == DOCUSEAL


@pytest.mark.django_db
@pytest.mark.parametrize("mode", [DOCUSEAL, LOCAL])
def test_new_agreement_uses_configured_mode(
    settings, agreement_member, default_plan, mode
):
    settings.AGREEMENT_DOCUMENT_MODE = mode

    agreement = _create_agreement(agreement_member)

    assert agreement.document_backend == mode


@pytest.mark.django_db
def test_invalid_mode_fails_closed_before_creating_a_row(settings, agreement_member):
    from apps.agreements.models import Agreement

    settings.AGREEMENT_DOCUMENT_MODE = "unsupported"
    before = Agreement.objects.count()

    with pytest.raises(ImproperlyConfigured):
        _create_agreement(agreement_member)

    assert Agreement.objects.count() == before


@pytest.mark.django_db
def test_invalid_mode_fails_closed_for_material_amendment(
    settings, agreement_member, default_plan
):
    from apps.agreements.models import Agreement
    from apps.agreements.services import start_material_amendment

    signed = Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.SIGNED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-801",
        billing_plan=default_plan,
        first_billing_month="2026-09",
    )
    settings.AGREEMENT_DOCUMENT_MODE = "unsupported"

    with pytest.raises(ImproperlyConfigured):
        start_material_amendment(signed, actor=None, note="material change")

    signed.refresh_from_db()
    assert signed.state == Agreement.State.SIGNED
    assert signed.is_current is True
    assert Agreement.objects.count() == 1


@pytest.mark.django_db
def test_existing_current_agreement_is_returned_unchanged(
    settings, agreement_member, default_plan
):
    from apps.agreements.models import Agreement

    settings.AGREEMENT_DOCUMENT_MODE = DOCUSEAL
    first = _create_agreement(agreement_member)

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    second = _create_agreement(agreement_member)

    assert second.pk == first.pk
    first.refresh_from_db()
    assert first.document_backend == DOCUSEAL
    assert Agreement.objects.filter(member=agreement_member).count() == 1


@pytest.mark.django_db
def test_existing_agreement_returns_before_mode_resolution(
    settings, agreement_member
):
    """Settings select only future rows: an idempotent return must never read
    the mode, so even an unsupported value cannot affect an existing row."""
    from apps.agreements.models import Agreement

    settings.AGREEMENT_DOCUMENT_MODE = DOCUSEAL
    existing = _create_agreement(agreement_member)

    settings.AGREEMENT_DOCUMENT_MODE = "unsupported"
    returned = _create_agreement(agreement_member)

    assert returned.pk == existing.pk
    existing.refresh_from_db()
    assert existing.document_backend == DOCUSEAL
    assert Agreement.objects.filter(member=agreement_member).count() == 1


@pytest.mark.django_db
def test_full_save_cannot_reclassify_an_existing_row(agreement_member):
    from apps.agreements.models import Agreement

    created = _create_agreement(agreement_member)

    stale = Agreement.objects.get(pk=created.pk)
    stale.document_backend = LOCAL
    stale.void_reason = "stale instance save"
    stale.save()

    persisted = Agreement.objects.get(pk=created.pk)
    assert persisted.document_backend == DOCUSEAL
    assert persisted.void_reason == "stale instance save"


@pytest.mark.django_db
def test_targeted_backend_write_is_refused(agreement_member):
    from apps.agreements.models import Agreement

    created = _create_agreement(agreement_member)

    stale = Agreement.objects.get(pk=created.pk)
    stale.document_backend = LOCAL
    with pytest.raises(ValueError, match="immutable"):
        stale.save(update_fields=["document_backend"])

    created.refresh_from_db()
    assert created.document_backend == DOCUSEAL


@pytest.mark.django_db
def test_approval_creates_agreement_on_configured_backend(
    settings, agreement_guardian, default_plan
):
    """The real approval route goes through the same new-row selection rule."""
    from apps.agreements.models import Agreement
    from apps.registrations.models import RegistrationApplication
    from apps.registrations.services import approve_application

    application = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        parent_account=agreement_guardian.parent_account,
        guardian=agreement_guardian,
        member_full_name="Jānis Bērziņš",
        member_personal_id="151210-22222",
        member_birth_date=date(2015, 12, 10),
    )

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    approve_application(application, reviewer=None)

    agreement = Agreement.objects.get(member=application.approved_member)
    assert agreement.document_backend == LOCAL


@pytest.mark.django_db
def test_invalid_mode_blocks_approval_without_partial_rows(
    settings, agreement_guardian, default_plan
):
    from apps.agreements.models import Agreement
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication
    from apps.registrations.services import approve_application

    application = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        parent_account=agreement_guardian.parent_account,
        guardian=agreement_guardian,
        member_full_name="Jānis Bērziņš",
        member_personal_id="151210-22222",
        member_birth_date=date(2015, 12, 10),
    )
    settings.AGREEMENT_DOCUMENT_MODE = "unsupported"
    members_before = Member.objects.count()

    with pytest.raises(ImproperlyConfigured):
        approve_application(application, reviewer=None)

    application.refresh_from_db()
    assert application.status == RegistrationApplication.Status.SUBMITTED
    assert application.approved_member_id is None
    assert Member.objects.count() == members_before
    assert Agreement.objects.filter(member__guardian=agreement_guardian).count() == 0


@pytest.mark.django_db
def test_mode_switch_selects_only_new_rows(
    settings, agreement_member, agreement_guardian, default_plan
):
    settings.AGREEMENT_DOCUMENT_MODE = DOCUSEAL
    first = _create_agreement(agreement_member)

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    second = _create_agreement(_extra_member(agreement_guardian))

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.document_backend == DOCUSEAL
    assert second.document_backend == LOCAL


@pytest.mark.django_db
def test_regenerate_selects_mode_for_replacement_row(
    settings, agreement_member, default_plan
):
    from apps.agreements.models import Agreement
    from apps.agreements.services import regenerate_agreement

    settings.AGREEMENT_DOCUMENT_MODE = DOCUSEAL
    original = _create_agreement(agreement_member)
    original.state = Agreement.State.VOID
    original.voided_at = timezone.now()
    original.save(update_fields=["state", "voided_at"])

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    replacement = regenerate_agreement(agreement_member, "paper", actor=None)

    original.refresh_from_db()
    assert original.is_current is False
    assert original.document_backend == DOCUSEAL
    assert replacement.pk != original.pk
    assert replacement.is_current is True
    assert replacement.document_backend == LOCAL


@pytest.mark.django_db
def test_material_amendment_selects_mode_for_replacement_row(
    settings, agreement_member, default_plan
):
    from apps.agreements.models import Agreement
    from apps.agreements.services import start_material_amendment

    signed = Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.SIGNED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-802",
        billing_plan=default_plan,
        first_billing_month="2026-09",
    )

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    replacement = start_material_amendment(
        signed, actor=None, note="material change"
    )

    signed.refresh_from_db()
    assert signed.state == Agreement.State.SUPERSEDED
    assert signed.is_current is False
    assert signed.document_backend == DOCUSEAL
    assert replacement.is_current is True
    assert replacement.document_backend == LOCAL
    assert replacement.billing_plan_id == signed.billing_plan_id
    assert replacement.first_billing_month == signed.first_billing_month


@pytest.mark.django_db
def test_rolled_back_creation_does_not_reclassify_existing_rows(
    settings, agreement_member, agreement_guardian, default_plan
):
    from django.db import transaction

    from apps.agreements.models import Agreement

    settings.AGREEMENT_DOCUMENT_MODE = DOCUSEAL
    existing = _create_agreement(agreement_member)
    other = _extra_member(agreement_guardian, "Trešais Bērns")

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            _create_agreement(other)
            raise RuntimeError("rollback")

    existing.refresh_from_db()
    assert existing.document_backend == DOCUSEAL
    assert Agreement.objects.count() == 1


@pytest.mark.django_db
def test_renew_member_billing_does_not_create_an_agreement(
    settings, agreement_member, default_plan
):
    from apps.agreements.models import Agreement
    from apps.billing.services import renew_member_billing

    settings.AGREEMENT_DOCUMENT_MODE = LOCAL
    before = Agreement.objects.count()

    record = renew_member_billing(agreement_member, default_plan)

    assert record is not None
    assert Agreement.objects.count() == before


@pytest.mark.django_db(transaction=True)
def test_0009_migration_backfills_docuseal_and_preserves_external_fields():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from apps.agreements.models import Agreement
    from apps.members.models import Member
    from tests.support import make_guardian

    def member(name, email):
        return Member.objects.create(
            full_name=name, guardian=make_guardian(email=email)
        )

    current_member = member("Pašreizējais Bērns", "migration-current@example.test")
    historical_member = member("Vēsturiskais Bērns", "migration-old@example.test")
    failed_member = member("Neizdevušais Bērns", "migration-failed@example.test")
    no_id_member = member("Bez ID Bērns", "migration-noid@example.test")

    executor = MigrationExecutor(connection)
    executor.migrate([("agreements", "0008_agreement_pdf_shadow")])
    old_apps = executor.loader.project_state(
        [("agreements", "0008_agreement_pdf_shadow")]
    ).apps
    OldAgreement = old_apps.get_model("agreements", "Agreement")

    now = timezone.now()
    expected = {
        "FKC-2026-901": {
            "state": "signed",
            "is_current": True,
            "external_provider": "docuseal",
            "external_id": "submission-current",
            "external_state": "completed",
            "external_url": "https://provider.invalid/current",
            "external_error_code": "",
        },
        "FKC-2026-902": {
            "state": "signed",
            "is_current": False,
            "external_provider": "docuseal",
            "external_id": "submission-historical",
            "external_state": "completed",
            "external_url": "https://provider.invalid/historical",
            "external_error_code": "",
        },
        "FKC-2026-903": {
            "state": "generated",
            "is_current": True,
            "external_provider": "docuseal",
            "external_id": "",
            "external_state": "failed",
            "external_url": "",
            "external_error_code": "provider_unavailable",
        },
        "FKC-2026-904": {
            "state": "generated",
            "is_current": True,
            "external_provider": "",
            "external_id": "",
            "external_state": "",
            "external_url": "",
            "external_error_code": "",
        },
    }
    members = {
        "FKC-2026-901": current_member,
        "FKC-2026-902": historical_member,
        "FKC-2026-903": failed_member,
        "FKC-2026-904": no_id_member,
    }
    for number, fields in expected.items():
        OldAgreement.objects.create(
            member_id=members[number].pk,
            generated_at=now,
            agreement_number=number,
            signing_path="paper",
            **fields,
        )

    executor = MigrationExecutor(connection)
    executor.migrate([("agreements", "0009_agreement_document_backend")])

    for number, fields in expected.items():
        row = Agreement.objects.get(agreement_number=number)
        assert row.document_backend == DOCUSEAL
        for field, value in fields.items():
            assert getattr(row, field) == value
