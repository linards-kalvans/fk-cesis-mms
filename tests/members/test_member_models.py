"""Member-domain model shape tests — RED phase.

Covers:
- Guardian model fields: full_name, personal_id, email, phone, address
- TrainingGroup model fields: name, is_active
- Member model fields: full_name, personal_id, birth_date, guardian, training_group
- Member.training_group is nullable (guardian is required per spec)
- RegistrationApplication review fields: review_message, reviewed_by, reviewed_at, approved_member
- Approve creates Guardian + Member exactly once (idempotent)
"""

import pytest

from apps.accounts.models import ParentAccount

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Guardian model
# ---------------------------------------------------------------------------


class TestGuardianModel:
    """Verify Guardian model exists with required fields."""

    def test_guardian_model_exists(self):
        from apps.members.models import Guardian

        assert Guardian is not None

    def test_guardian_has_full_name_field(self):
        from apps.members.models import Guardian

        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "full_name" in field_names, "Guardian must have full_name field."

    def test_guardian_has_personal_id_field(self):
        from apps.members.models import Guardian

        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "personal_id" in field_names, "Guardian must have personal_id field."

    def test_guardian_has_email_field(self):
        from apps.members.models import Guardian

        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "email" in field_names, "Guardian must have email field."

    def test_guardian_has_phone_field(self):
        from apps.members.models import Guardian

        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "phone" in field_names, "Guardian must have phone field."

    def test_guardian_has_address_field(self):
        from apps.members.models import Guardian

        field_names = {f.name for f in Guardian._meta.get_fields()}
        assert "address" in field_names, "Guardian must have address field."

    def test_guardian_can_be_created(self):
        from apps.members.models import Guardian

        g = Guardian.objects.create(
            full_name="Jane Doe",
            personal_id="010101-12345",
            email="jane@example.com",
            phone="+37120000000",
            address="Riga, Brivibas 1",
        )
        assert g.pk is not None
        assert g.full_name == "Jane Doe"
        assert g.email == "jane@example.com"


# ---------------------------------------------------------------------------
# TrainingGroup model
# ---------------------------------------------------------------------------


class TestTrainingGroupModel:
    """Verify TrainingGroup model exists with required fields."""

    def test_training_group_model_exists(self):
        from apps.members.models import TrainingGroup

        assert TrainingGroup is not None

    def test_training_group_has_name_field(self):
        from apps.members.models import TrainingGroup

        field_names = {f.name for f in TrainingGroup._meta.get_fields()}
        assert "name" in field_names, "TrainingGroup must have name field."

    def test_training_group_has_is_active_field(self):
        from apps.members.models import TrainingGroup

        field_names = {f.name for f in TrainingGroup._meta.get_fields()}
        assert "is_active" in field_names, "TrainingGroup must have is_active field."

    def test_training_group_can_be_created(self):
        from apps.members.models import TrainingGroup

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
        from apps.members.models import Member

        assert Member is not None

    def test_member_has_full_name_field(self):
        from apps.members.models import Member

        field_names = {f.name for f in Member._meta.get_fields()}
        assert "full_name" in field_names, "Member must have full_name field."

    def test_member_has_personal_id_field(self):
        from apps.members.models import Member

        field_names = {f.name for f in Member._meta.get_fields()}
        assert "personal_id" in field_names, "Member must have personal_id field."

    def test_member_has_birth_date_field(self):
        from apps.members.models import Member

        field_names = {f.name for f in Member._meta.get_fields()}
        assert "birth_date" in field_names, "Member must have birth_date field."

    def test_member_has_guardian_foreign_key(self):
        from apps.members.models import Member

        field_names = {f.name for f in Member._meta.get_fields()}
        assert "guardian" in field_names, "Member must have guardian FK."

    def test_member_has_training_group_foreign_key(self):
        from apps.members.models import Member

        field_names = {f.name for f in Member._meta.get_fields()}
        assert "training_group" in field_names, "Member must have training_group FK."

    def test_member_training_group_is_nullable(self):
        """Member.training_group must be nullable — assignment is deferred.

        Spec requires linked Guardian on approval; training_group is the
        nullable field (placeholder until admin assigns group).
        """
        from apps.members.models import Guardian, Member

        g = Guardian.objects.create(
            full_name="Jane Doe",
            personal_id="010101-12345",
            email="jane@example.com",
            phone="+37120000000",
            address="Riga, Brivibas 1",
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
        from apps.members.models import Guardian, Member

        g = Guardian.objects.create(
            full_name="Jane Doe",
            personal_id="010101-12345",
            email="jane@example.com",
            phone="+37120000000",
            address="Riga, Brivibas 1",
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
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "review_message" in field_names, (
            "RegistrationApplication must have review_message field."
        )

    def test_has_reviewed_by_foreign_key(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "reviewed_by" in field_names, (
            "RegistrationApplication must have reviewed_by field."
        )

    def test_has_reviewed_at_field(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "reviewed_at" in field_names, (
            "RegistrationApplication must have reviewed_at field."
        )

    def test_has_approved_member_foreign_key(self):
        from apps.registrations.models import RegistrationApplication

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
        """First approve should create one Guardian and one Member."""
        from apps.registrations.services import (
            create_or_update_draft,
            submit_application,
        )
        from apps.members.models import Guardian, Member
        from django.contrib.auth.models import User
        from django.core.files.uploadedfile import SimpleUploadedFile

        acct = ParentAccount.objects.create(
            email="approve@example.com",
            phone="+37111111111",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "approve@example.com",
                "guardian_full_name": "Approve Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child Approve",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={
                "child_identity_document": SimpleUploadedFile(
                    "id.jpg", b"fake", content_type="image/jpeg"
                ),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        # Approve — should create Guardian + Member
        staff_user = User.objects.create_superuser(
            username="approvestaff",
            email="approvestaff@example.com",
            password="approvestaffpass",
        )
        from apps.registrations.services import approve_application

        approve_application(app, staff_user)

        assert Guardian.objects.count() == 1, (
            f"Expected 1 Guardian, got {Guardian.objects.count()}."
        )
        assert Member.objects.count() == 1, (
            f"Expected 1 Member, got {Member.objects.count()}."
        )
        assert app.approved_member_id is not None

    def test_approve_twice_does_not_duplicate_guardian_or_member(self):
        """Calling approve twice must not create duplicate Guardian/Member."""
        from apps.registrations.services import (
            create_or_update_draft,
            submit_application,
            approve_application,
        )
        from apps.members.models import Guardian, Member
        from django.contrib.auth.models import User
        from django.core.files.uploadedfile import SimpleUploadedFile

        acct = ParentAccount.objects.create(
            email="idempotent@example.com",
            phone="+37133333333",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "idempotent@example.com",
                "guardian_full_name": "Idempotent Guardian",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37144444444",
                "guardian_address": "Riga 33",
                "child_full_name": "Child Idem",
                "child_personal_id": "010125-33333",
                "child_birth_date": "2025-02-01",
            },
            files={
                "child_identity_document": SimpleUploadedFile(
                    "id2.jpg", b"fake2", content_type="image/jpeg"
                ),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = User.objects.create_superuser(
            username="idemstaff",
            email="idemstaff@example.com",
            password="idemstaffpass",
        )

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
        from apps.registrations.services import (
            create_or_update_draft,
            submit_application,
            approve_application,
        )
        from apps.members.models import Member
        from django.contrib.auth.models import User
        from django.core.files.uploadedfile import SimpleUploadedFile

        acct = ParentAccount.objects.create(
            email="nullgroup@example.com",
            phone="+37166666666",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "nullgroup@example.com",
                "guardian_full_name": "Null Group Guardian",
                "guardian_personal_id": "010101-66666",
                "guardian_phone": "+37177777777",
                "guardian_address": "Riga 66",
                "child_full_name": "Child NullGroup",
                "child_personal_id": "010125-66666",
                "child_birth_date": "2025-03-01",
            },
            files={
                "child_identity_document": SimpleUploadedFile(
                    "id3.jpg", b"fake3", content_type="image/jpeg"
                ),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        staff_user = User.objects.create_superuser(
            username="nullstaff",
            email="nullstaff@example.com",
            password="nullstaffpass",
        )
        approve_application(app, staff_user)

        member = Member.objects.get(pk=app.approved_member_id)
        assert member.training_group is None, (
            "Approved Member training_group must be None."
        )
