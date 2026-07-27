"""Shared fixtures for P11 family admin hub tests.

Re-exports fixtures from tests/registrations/conftest.py that are not
automatically visible outside that directory.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


# ---------------------------------------------------------------------------
# Re-exported from tests/registrations/conftest.py
# ---------------------------------------------------------------------------

_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _png(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name=name, content=_PNG_BYTES, content_type="image/png")


@pytest.fixture
def guardian_identity_file():
    return _png("guardian_id.png")


@pytest.fixture
def member_identity_file():
    return _png("member_id.png")


@pytest.fixture
def member_portrait_file():
    return _png("portrait.png")


@pytest.fixture
def kit_sizes(db):
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        label="S",
        defaults={"is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        label="S",
        defaults={"is_active": True},
    )
    return shirt.pk, shorts.pk


@pytest.fixture
def submit_payload(kit_sizes, parent_account):
    shirt_pk, _shorts_pk = kit_sizes
    return {
        "guardian_first_name": "Hub Test",
        "guardian_family_name": "Guardian",
        "guardian_personal_id": "010101-12345",
        "guardian_email": parent_account.email,
        "guardian_phone": "+37120000000",
        "guardian_declared_address": "Riga, Brivibas 1",
        "member_full_name": "Hub Test Child",
        "member_personal_id": "010125-67890",
        "member_birth_date": "2025-01-01",
        "member_same_address_as_guardian": True,
        "member_kit_size_shirt": shirt_pk,
        "preferred_agreement_signing": "paper",
    }


@pytest.fixture
def draft_application(parent_account):
    from apps.registrations.services import create_or_update_draft

    return create_or_update_draft(
        data={"guardian_email": parent_account.email},
        files={},
        verified_account=parent_account,
    )


@pytest.fixture
def draft_with_documents(
    draft_application,
    guardian_identity_file,
    member_identity_file,
    member_portrait_file,
):
    from apps.documents.models import Document

    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.GUARDIAN_IDENTITY,
        file=guardian_identity_file,
        original_filename=guardian_identity_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.MEMBER_IDENTITY,
        file=member_identity_file,
        original_filename=member_identity_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.MEMBER_PORTRAIT,
        file=member_portrait_file,
        original_filename=member_portrait_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    return draft_application


@pytest.fixture
def submitted_application(draft_with_documents, parent_account, submit_payload):
    from apps.registrations.services import create_or_update_draft, submit_application

    app = create_or_update_draft(
        data=submit_payload,
        files={},
        application=draft_with_documents,
        verified_account=parent_account,
    )
    return submit_application(app, parent_account)


# ---------------------------------------------------------------------------
# Hub-specific fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="hub_reviewer", is_staff=True)


@pytest.fixture
def default_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="Hub Default Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
        is_default=True,
    )


@pytest.fixture
def active_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="Hub Active Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
    )


@pytest.fixture
def approved_application(submitted_application, reviewer, default_plan):
    """A submitted application that has been approved (creates Member + Agreement)."""
    from apps.registrations.services import approve_application

    return approve_application(submitted_application, reviewer)


@pytest.fixture
def billing_record_factory(db, active_plan):
    """Factory to create BillingRecord with optional overrides."""
    from apps.billing.models import BillingRecord

    def _make(member, **overrides):
        defaults = dict(
            plan=active_plan,
            season=active_plan.season,
            base_amount=active_plan.annual_amount,
            final_amount=active_plan.annual_amount,
            payment_mode=BillingRecord.PaymentMode.UPFRONT,
            status=BillingRecord.Status.CONFIRMED,
        )
        defaults.update(overrides)
        return BillingRecord.objects.create(member=member, **defaults)

    return _make
