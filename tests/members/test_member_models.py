"""Member-domain model shape tests — RED phase.

Covers:
- Guardian model fields: full_name, personal_id, address (email/phone are
  read-only proxies onto the linked ParentAccount)
- TrainingGroup model fields: name, is_active
- Member model fields: full_name, personal_id, birth_date, guardian, training_group
- Member.training_group is nullable (guardian is required per spec)
- RegistrationApplication review fields: review_message, reviewed_by, reviewed_at, approved_member
- Approve creates Guardian + Member exactly once (idempotent)

All helper/setup uses current P1 field names and full submit payload:
guardian_declared_address, member_full_name, member_personal_id,
member_birth_date, member_actual_address, member_same_address_as_guardian,
kit sizes, preferred_agreement_signing, guardian/member/portrait docs.
"""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian, KitSizeOption, Member, TrainingGroup
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    create_or_update_draft,
    submit_application,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Module-level fixture: kit sizes required for submit
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def kit_sizes():
    """Ensure KitSizeOption records exist before any test runs."""
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        label="S",
        defaults={"is_active": True},
    )
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        label="M",
        defaults={"is_active": True},
    )
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        label="S",
        defaults={"is_active": True},
    )
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        label="M",
        defaults={"is_active": True},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(name="doc.png"):
    """Return a minimal valid PNG bytes blob wrapped as SimpleUploadedFile."""
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _create_submitted_app(
    email="test@example.com",
    guardian_name="Test Guardian",
    guardian_pid="010101-11111",
    child_name="Test Child",
    child_pid="010125-11111",
):
    """Create and submit a RegistrationApplication with a full P1 payload.

    Uses current P1 field names and all required documents/kit sizes
    so that ``submit_application`` does not raise ValueError.
    """
    shirt = KitSizeOption.objects.get(
        kind=KitSizeOption.Kind.SHIRT, label="S"
    )
    shorts = KitSizeOption.objects.get(
        kind=KitSizeOption.Kind.SHORTS, label="S"
    )

    acct = ParentAccount.objects.create(
        email=email,
        phone="+37111111111",
    )

    guardian_doc = _make_png("guardian_id.png")
    member_doc = _make_png("member_id.png")
    portrait_doc = _make_png("portrait.png")

    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_first_name": guardian_name.split(" ", 1)[0] if " " in guardian_name else "",
            "guardian_family_name": guardian_name.split(" ", 1)[1] if " " in guardian_name else guardian_name,
            "guardian_personal_id": guardian_pid,
            "guardian_phone": "+37122222222",
            "guardian_declared_address": "Riga, Brivibas 1",
            "member_full_name": child_name,
            "member_personal_id": child_pid,
            "member_birth_date": "2025-01-01",
            "member_actual_address": "Riga, Brivibas 1",
            "member_same_address_as_guardian": True,
            "member_kit_size_shirt": shirt.pk,
            "member_kit_size_shorts": shorts.pk,
            "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
            "support_club_instead_of_multi_child_discount": False,
        },
        files={
            "guardian_identity_document": guardian_doc,
            "member_identity_document": member_doc,
            "member_portrait_document": portrait_doc,
        },
        verified_account=acct,
    )
    submit_application(app, acct)
    return app


def _create_staff_user(username="staff"):
    """Create a Django superuser for staff-only access."""
    return User.objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="staffpass",
    )


# ---------------------------------------------------------------------------
# Guardian model
# ---------------------------------------------------------------------------


class TestGuardianModel:
    """Verify Guardian model exists with required fields."""

    def test_guardian_model_exists(self):
        assert Guardian is not None

    def test_guardian_has_first_and_family_name_fields(self):
        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "first_name" in field_names, "Guardian must have first_name field."
        assert "family_name" in field_names, "Guardian must have family_name field."

    def test_guardian_has_personal_id_field(self):
        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "personal_id" in field_names, "Guardian must have personal_id field."

    def test_guardian_email_reads_through_account(self):
        """Guardian.email is a read-only proxy onto the linked ParentAccount."""
        acct = ParentAccount.objects.create(email="jane@example.com")
        g = Guardian.objects.create(
            first_name="Jane",
            family_name="Doe",
            parent_account=acct,
        )
        assert g.email == "jane@example.com"

    def test_guardian_phone_reads_through_account(self):
        """Guardian.phone is a read-only proxy onto the linked ParentAccount."""
        acct = ParentAccount.objects.create(email="jane@example.com", phone="+37120000000")
        g = Guardian.objects.create(
            first_name="Jane",
            family_name="Doe",
            parent_account=acct,
        )
        assert g.phone == "+37120000000"

    def test_guardian_has_address_field(self):
        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "address" in field_names, "Guardian must have address field."

    def test_guardian_can_be_created(self):
        acct = ParentAccount.objects.create(email="jane@example.com", phone="+37120000000")
        g = Guardian.objects.create(
            first_name="Jane",
            family_name="Doe",
            personal_id="010101-12345",
            address="Riga, Brivibas 1",
            parent_account=acct,
        )
        assert g.pk is not None
        assert g.display_name == "Jane Doe"
        assert g.email == "jane@example.com"


# ---------------------------------------------------------------------------
# TrainingGroup model
# ---------------------------------------------------------------------------


class TestTrainingGroupModel:
    """Verify TrainingGroup model exists with required fields."""

    def test_training_group_model_exists(self):
        assert TrainingGroup is not None

    def test_training_group_has_name_field(self):
        field_names = {f.name for f in TrainingGroup._meta.get_fields()}
        assert "name" in field_names, "TrainingGroup must have name field."

    def test_training_group_has_is_active_field(self):
        field_names = {f.name for f in TrainingGroup._meta.get_fields()}
        assert "is_active" in field_names, "TrainingGroup must have is_active field."

    def test_training_group_can_be_created(self):
        tg = TrainingGroup.objects.create(
            name="U10 A",
            is_active=True,
        )
        assert tg.pk is not None
        assert tg.name == "U10 A"
        assert tg.is_active is True


# ---------------------------------------------------------------------------
# Member model
# ---------------------------------------------------------------------------


class TestMemberModel:
    """Verify Member model exists with required fields."""

    def test_member_model_exists(self):
        assert Member is not None

    def test_member_has_full_name_field(self):
        field_names = {f.name for f in Member._meta.get_fields()}
        assert "full_name" in field_names, "Member must have full_name field."

    def test_member_has_personal_id_field(self):
        field_names = {f.name for f in Member._meta.get_fields()}
        assert "personal_id" in field_names, "Member must have personal_id field."

    def test_member_has_birth_date_field(self):
        field_names = {f.name for f in Member._meta.get_fields()}
        assert "birth_date" in field_names, "Member must have birth_date field."

    def test_member_has_guardian_foreign_key(self):
        field_names = {f.name for f in Member._meta.get_fields()}
        assert "guardian" in field_names, "Member must have guardian FK."

    def test_member_has_training_group_foreign_key(self):
        field_names = {f.name for f in Member._meta.get_fields()}
        assert "training_group" in field_names, "Member must have training_group FK."

    def test_member_training_group_is_nullable(self):
        """Member.training_group must be nullable — assignment is deferred.

        Spec requires linked Guardian on approval; training_group is the
        nullable field (placeholder until admin assigns group).
        """
        acct = ParentAccount.objects.create(email="jane@example.com", phone="+37120000000")
        g = Guardian.objects.create(
            first_name="Jane",
            family_name="Doe",
            personal_id="010101-12345",
            address="Riga, Brivibas 1",
            parent_account=acct,
        )
        # Create Member with guardian but no training_group
        m = Member.objects.create(
            full_name="Little Jane",
            personal_id="010125-12345",
            birth_date="2025-01-01",
            guardian=g,
        )
        assert m.training_group is None, "Member.training_group must default to None."

    def test_member_can_be_created_with_guardian(self):
        acct = ParentAccount.objects.create(email="jane@example.com", phone="+37120000000")
        g = Guardian.objects.create(
            first_name="Jane",
            family_name="Doe",
            personal_id="010101-12345",
            address="Riga, Brivibas 1",
            parent_account=acct,
        )
        m = Member.objects.create(
            full_name="Little Jane",
            personal_id="010125-12345",
            birth_date="2025-01-01",
            guardian=g,
        )
        assert m.guardian_id == g.pk
        assert m.training_group is None


# ---------------------------------------------------------------------------
# RegistrationApplication review fields
# ---------------------------------------------------------------------------


class TestRegistrationApplicationReviewFields:
    """Verify RegistrationApplication has review-related fields."""

    def test_has_review_message_field(self):
        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "review_message" in field_names, (
            "RegistrationApplication must have review_message field."
        )

    def test_has_reviewed_by_foreign_key(self):
        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "reviewed_by" in field_names, (
            "RegistrationApplication must have reviewed_by field."
        )

    def test_has_reviewed_at_field(self):
        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "reviewed_at" in field_names, (
            "RegistrationApplication must have reviewed_at field."
        )

    def test_has_approved_member_foreign_key(self):
        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "approved_member" in field_names, (
            "RegistrationApplication must have approved_member field."
        )


# ---------------------------------------------------------------------------
# Approve creates Guardian + Member exactly once (idempotent)
# ---------------------------------------------------------------------------


class TestApproveIdempotent:
    """Approving the same application twice must not create duplicate records."""

    def test_approve_creates_guardian_and_member(self):
        """First approve should create one Guardian and one Member.

        Slice A wires guardian resolution at draft initiation; approval reuses
        that same Guardian (no fresh create). Total = 1 for the account.
        """
        app = _create_submitted_app("approve@example.com")

        staff_user = _create_staff_user("approvestaff")
        approve_application(app, staff_user)

        assert Guardian.objects.count() == 1, (
            f"Expected 1 Guardian (resolved at draft, reused at approval), got {Guardian.objects.count()}."
        )
        assert Member.objects.count() == 1, (
            f"Expected 1 Member, got {Member.objects.count()}."
        )
        assert app.approved_member_id is not None

    def test_approve_twice_does_not_duplicate_guardian_or_member(self):
        """Calling approve twice must not create duplicate Guardian/Member."""
        app = _create_submitted_app("idempotent@example.com")

        staff_user = _create_staff_user("idemstaff")

        approve_application(app, staff_user)
        first_guardian_count = Guardian.objects.count()
        first_member_count = Member.objects.count()

        # Approve again
        approve_application(app, staff_user)

        assert Guardian.objects.count() == first_guardian_count, (
            "Approve must be idempotent — no duplicate Guardian."
        )
        assert Member.objects.count() == first_member_count, (
            "Approve must be idempotent — no duplicate Member."
        )

    def test_approve_sets_training_group_to_null(self):
        """Approved Member must have training_group = None (placeholder)."""
        app = _create_submitted_app("nullgroup@example.com")

        staff_user = _create_staff_user("nullstaff")
        approve_application(app, staff_user)

        member = Member.objects.get(pk=app.approved_member_id)
        assert member.training_group is None, (
            "Approved Member training_group must be None."
        )
