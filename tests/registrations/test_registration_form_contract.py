"""P1 — Registration field-contract tests.

Uses the exact approved P1 field names from the implementation plan:
  guardian_full_name
  guardian_personal_id
  guardian_declared_address
  guardian_email
  guardian_phone
  member_full_name
  member_personal_id
  member_birth_date
  member_actual_address
  member_same_address_as_guardian
  preferred_agreement_signing
  support_club_instead_of_multi_child_discount

Documents are NOT model fields on RegistrationApplication.
They are separate Document records with `kind` values:
  guardian_identity, member_identity, member_portrait.

Kit sizes are managed by the admin lookup model KitSizeOption.
Application fields: member_kit_size_shirt, member_kit_size_shorts.

Must FAIL because current implementation still uses old child_* fields,
guardian_address, child_identity document kind, and lacks the P1 fields.
"""

import pytest

from apps.accounts.models import ParentAccount

pytestmark = pytest.mark.django_db


# ===========================================================================
# 1. Guardian snapshot fields exist with exact P1 names
# ===========================================================================


class TestGuardianFields:
    """Guardian snapshot fields on RegistrationApplication must exist with P1 names."""

    def test_guardian_full_name_field_exists(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "guardian_full_name" in field_names

    def test_guardian_personal_id_field_exists(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "guardian_personal_id" in field_names

    def test_guardian_declared_address_field_exists(self):
        """Must use guardian_declared_address, not guardian_address."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "guardian_declared_address" in field_names, (
            "RegistrationApplication must have guardian_declared_address field."
        )

    def test_guardian_email_field_exists(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "guardian_email" in field_names

    def test_guardian_phone_field_exists(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "guardian_phone" in field_names


# ===========================================================================
# 2. Member (child/player) snapshot fields exist with exact P1 names
# ===========================================================================


class TestMemberFields:
    """Member snapshot fields on RegistrationApplication must exist with P1 names."""

    def test_member_full_name_field_exists(self):
        """Must use member_full_name, not child_full_name."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_full_name" in field_names, (
            "RegistrationApplication must have member_full_name field."
        )

    def test_member_personal_id_field_exists(self):
        """Must use member_personal_id, not child_personal_id."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_personal_id" in field_names, (
            "RegistrationApplication must have member_personal_id field."
        )

    def test_member_birth_date_field_exists(self):
        """Must use member_birth_date, not child_birth_date."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_birth_date" in field_names, (
            "RegistrationApplication must have member_birth_date field."
        )

    def test_member_actual_address_field_exists(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_actual_address" in field_names

    def test_member_same_address_as_guardian_field_exists(self):
        """Must use member_same_address_as_guardian, not same_address."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_same_address_as_guardian" in field_names, (
            "RegistrationApplication must have "
            "member_same_address_as_guardian field."
        )

    def test_member_kit_size_shirt_field_exists(self):
        """Shirt kit size must be a FK to KitSizeOption."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_kit_size_shirt" in field_names, (
            "RegistrationApplication must have member_kit_size_shirt field."
        )

    def test_member_kit_size_shorts_field_exists(self):
        """Shorts kit size must be a FK to KitSizeOption."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_kit_size_shorts" in field_names, (
            "RegistrationApplication must have member_kit_size_shorts field."
        )


# ===========================================================================
# 3. Application-level fields exist with exact P1 names
# ===========================================================================


class TestApplicationFields:
    """Application-level fields on RegistrationApplication must exist."""

    def test_preferred_agreement_signing_field_exists(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "preferred_agreement_signing" in field_names

    def test_support_club_instead_of_multi_child_discount_field_exists(self):
        """Must use exact P1 name: support_club_instead_of_multi_child_discount."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "support_club_instead_of_multi_child_discount" in field_names, (
            "RegistrationApplication must have "
            "support_club_instead_of_multi_child_discount field."
        )

    def test_field_sources_json_field_exists(self):
        """field_sources JSON field must exist for source classification."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "field_sources" in field_names, (
            "RegistrationApplication must have field_sources JSON field."
        )


# ===========================================================================
# 4. Submit-time: all listed fields required
# ===========================================================================


class TestSubmitRequiredFields:
    """submit_application must reject when any required P1 field is missing."""

    def _make_verified_account(self, email):
        return ParentAccount.objects.create(
            email=email,
            phone="+37100000000",
        )

    def test_submit_requires_guardian_declared_address(self):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqaddr@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqaddr@example.com",
                "guardian_full_name": "ReqAddr Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_declared_address": "",
                "guardian_phone": "+37122222222",
                "member_full_name": "Child ReqAddr",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_member_full_name(self):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqmname@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqmname@example.com",
                "guardian_full_name": "ReqMName Guardian",
                "guardian_personal_id": "010101-22222",
                "guardian_declared_address": "Riga 2",
                "guardian_phone": "+37133333333",
                "member_full_name": "",
                "member_personal_id": "010125-22222",
                "member_birth_date": "2025-02-01",
                "member_actual_address": "Riga 2",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_member_kit_sizes(self):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqkit@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqkit@example.com",
                "guardian_full_name": "ReqKit Guardian",
                "guardian_personal_id": "010101-33333",
                "guardian_declared_address": "Riga 3",
                "guardian_phone": "+37144444444",
                "member_full_name": "Child ReqKit",
                "member_personal_id": "010125-33333",
                "member_birth_date": "2025-03-01",
                "member_actual_address": "Riga 3",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_preferred_agreement_signing(self):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqagree@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqagree@example.com",
                "guardian_full_name": "ReqAgree Guardian",
                "guardian_personal_id": "010101-44444",
                "guardian_declared_address": "Riga 4",
                "guardian_phone": "+37155555555",
                "member_full_name": "Child ReqAgree",
                "member_personal_id": "010125-44444",
                "member_birth_date": "2025-04-01",
                "member_actual_address": "Riga 4",
                "preferred_agreement_signing": "",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_guardian_personal_id(self):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqpid@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqpid@example.com",
                "guardian_full_name": "ReqPID Guardian",
                "guardian_personal_id": "",
                "guardian_declared_address": "Riga 5",
                "guardian_phone": "+37166666666",
                "member_full_name": "Child ReqPID",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-05-01",
                "member_actual_address": "Riga 5",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_member_birth_date(self):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqbd@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqbd@example.com",
                "guardian_full_name": "ReqBD Guardian",
                "guardian_personal_id": "010101-66666",
                "guardian_declared_address": "Riga 6",
                "guardian_phone": "+37177777777",
                "member_full_name": "Child ReqBD",
                "member_personal_id": "010125-66666",
                "member_birth_date": None,
                "member_actual_address": "Riga 6",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_guardian_identity_document(self):
        """Submit must require an active guardian_identity Document."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqgid@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqgid@example.com",
                "guardian_full_name": "ReqGID Guardian",
                "guardian_personal_id": "010101-88888",
                "guardian_declared_address": "Riga 8",
                "guardian_phone": "+37188888888",
                "member_full_name": "Child ReqGID",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-08-01",
                "member_actual_address": "Riga 8",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_member_identity_document(self):
        """Submit must require an active member_identity Document."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqmid@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqmid@example.com",
                "guardian_full_name": "ReqMID Guardian",
                "guardian_personal_id": "010101-99999",
                "guardian_declared_address": "Riga 9",
                "guardian_phone": "+37199999999",
                "member_full_name": "Child ReqMID",
                "member_personal_id": "010125-99999",
                "member_birth_date": "2025-09-01",
                "member_actual_address": "Riga 9",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_requires_member_portrait_document(self):
        """Submit must require an active member_portrait Document."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._make_verified_account("reqmp@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "reqmp@example.com",
                "guardian_full_name": "ReqMP Guardian",
                "guardian_personal_id": "010101-10101",
                "guardian_declared_address": "Riga 10",
                "guardian_phone": "+37110101010",
                "member_full_name": "Child ReqMP",
                "member_personal_id": "010125-10101",
                "member_birth_date": "2025-10-01",
                "member_actual_address": "Riga 10",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)


# ===========================================================================
# 5. Document uploads are NOT RegistrationApplication model fields
# ===========================================================================


class TestDocumentsAreSeparateModel:
    """Document uploads must be separate Document rows, not model columns."""

    def test_guardian_identity_document_not_application_field(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "guardian_identity_document" not in field_names, (
            "guardian_identity_document must NOT be a direct field on "
            "RegistrationApplication; use Document records instead."
        )

    def test_member_identity_document_not_application_field(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_identity_document" not in field_names, (
            "member_identity_document must NOT be a direct field on "
            "RegistrationApplication; use Document records instead."
        )

    def test_member_portrait_not_application_field(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "member_portrait_photo" not in field_names, (
            "member_portrait_photo must NOT be a direct field on "
            "RegistrationApplication; use Document records instead."
        )

    def test_child_identity_document_not_application_field(self):
        """Old child_identity_document field must also be absent."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "child_identity_document" not in field_names, (
            "child_identity_document must NOT be a direct field on "
            "RegistrationApplication; use Document records instead."
        )


# ===========================================================================
# 6. Document.Kind must include all three P1 kinds
# ===========================================================================


class TestDocumentKinds:
    """Document.Kind must include guardian_identity, member_identity, member_portrait."""

    def test_document_kind_guardian_identity_exists(self):
        from apps.documents.models import Document

        choices = dict(Document.Kind.choices)
        assert "guardian_identity" in choices

    def test_document_kind_member_identity_exists(self):
        from apps.documents.models import Document

        choices = dict(Document.Kind.choices)
        assert "member_identity" in choices

    def test_document_kind_member_portrait_exists(self):
        from apps.documents.models import Document

        choices = dict(Document.Kind.choices)
        assert "member_portrait" in choices

    def test_child_identity_kind_not_present(self):
        """Old child_identity kind must be replaced by member_identity."""
        from apps.documents.models import Document

        choices = dict(Document.Kind.choices)
        assert "child_identity" not in choices, (
            "Document.Kind must not include child_identity; use member_identity instead."
        )


# ===========================================================================
# 7. KitSizeOption model exists and is admin-managed
# ===========================================================================


class TestKitSizeOption:
    """Kit sizes must reference an admin-managed KitSizeOption model."""

    def test_kit_size_option_model_exists(self):
        from apps.members.models import KitSizeOption

        assert KitSizeOption is not None

    def test_kit_size_option_has_kind_field(self):
        from apps.members.models import KitSizeOption

        field_names = {f.name for f in KitSizeOption._meta.get_fields()}
        assert "kind" in field_names

    def test_kit_size_option_has_label_field(self):
        from apps.members.models import KitSizeOption

        field_names = {f.name for f in KitSizeOption._meta.get_fields()}
        assert "label" in field_names

    def test_kit_size_option_has_is_active_field(self):
        from apps.members.models import KitSizeOption

        field_names = {f.name for f in KitSizeOption._meta.get_fields()}
        assert "is_active" in field_names

    def test_kit_size_option_kind_has_shirt_and_shorts(self):
        from apps.members.models import KitSizeOption

        choices = dict(KitSizeOption.Kind.choices)
        assert "shirt" in choices, "KitSizeOption.Kind must include shirt."
        assert "shorts" in choices, "KitSizeOption.Kind must include shorts."


# ===========================================================================
# 8. Draft save allows incomplete values after verified entry
# ===========================================================================


class TestDraftAllowsIncompleteAfterVerified:
    """After verified entry, draft save must tolerate missing P1 fields."""

    def test_draft_save_allows_missing_guardian_fields(self):
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="draftincomplete@example.com",
            phone="+37160606060",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "draftincomplete@example.com",
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_declared_address": "",
                "guardian_phone": "",
                "member_full_name": "",
                "member_personal_id": "",
                "member_birth_date": None,
                "member_actual_address": "",
                "preferred_agreement_signing": "",
            },
            files={},
            verified_account=acct,
        )
        assert app.status == "draft"
        assert app.is_draft() is True

    def test_draft_save_allows_missing_kit_sizes(self):
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="draftkit@example.com",
            phone="+37170707070",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "draftkit@example.com",
                "guardian_full_name": "DraftKit Guardian",
                "guardian_personal_id": "010101-70707",
                "guardian_declared_address": "Riga 7",
                "guardian_phone": "+37180808080",
                "member_full_name": "Child DraftKit",
                "member_personal_id": "010125-70707",
                "member_birth_date": "2025-05-01",
                "member_actual_address": "Riga 7",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        assert app.status == "draft"


# ===========================================================================
# 9. Same-address toggle: copy guardian address to member address
# ===========================================================================


class TestSameAddressToggle:
    """member_same_address_as_guardian must copy guardian_declared_address
    to member_actual_address when True."""

    def test_same_address_true_copies_guardian_declared_address(self):
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="sameaddr@example.com",
            phone="+37190909090",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "sameaddr@example.com",
                "guardian_full_name": "SameAddr Guardian",
                "guardian_personal_id": "010101-90909",
                "guardian_declared_address": "Riga 90, iela 5",
                "guardian_phone": "+37101010101",
                "member_full_name": "Child SameAddr",
                "member_personal_id": "010125-90909",
                "member_birth_date": "2025-06-01",
                "member_same_address_as_guardian": True,
            },
            files={},
            verified_account=acct,
        )
        assert app.member_same_address_as_guardian is True
        assert app.member_actual_address == "Riga 90, iela 5", (
            "member_same_address_as_guardian=True must copy "
            "guardian_declared_address to member_actual_address."
        )

    def test_same_address_false_keeps_separate_member_actual_address(self):
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="diffaddr@example.com",
            phone="+37112121212",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "diffaddr@example.com",
                "guardian_full_name": "DiffAddr Guardian",
                "guardian_personal_id": "010101-12121",
                "guardian_declared_address": "Riga 90, iela 5",
                "guardian_phone": "+37123232323",
                "member_full_name": "Child DiffAddr",
                "member_personal_id": "010125-12121",
                "member_birth_date": "2025-07-01",
                "member_same_address_as_guardian": False,
                "member_actual_address": "Daugavpils, iela 10",
            },
            files={},
            verified_account=acct,
        )
        assert app.member_same_address_as_guardian is False
        assert app.member_actual_address == "Daugavpils, iela 10", (
            "member_same_address_as_guardian=False must keep the separately "
            "entered member_actual_address."
        )


# ===========================================================================
# 10. Field-source support: field_sources enum values
# ===========================================================================


class TestFieldSources:
    """field_sources must store exact enum values for source classification."""

    def test_same_address_true_stores_derived_system_filled(self):
        """When same_address is True, member_actual_address source must be
        derived_system_filled."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="srcderived@example.com",
            phone="+37113131313",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "srcderived@example.com",
                "guardian_full_name": "SrcDerived Guardian",
                "guardian_personal_id": "010101-13131",
                "guardian_declared_address": "Riga 13, iela 3",
                "guardian_phone": "+37114141414",
                "member_full_name": "Child SrcDerived",
                "member_personal_id": "010125-13131",
                "member_birth_date": "2025-08-01",
                "member_same_address_as_guardian": True,
            },
            files={},
            verified_account=acct,
        )
        sources = app.field_sources
        assert sources.get("member_actual_address") == "derived_system_filled", (
            "member_actual_address with same_address=True must store "
            "derived_system_filled in field_sources."
        )

    def test_same_address_false_stores_manual_only(self):
        """When same_address is False, member_actual_address source must be
        manual_only."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="srcmanual@example.com",
            phone="+37115151515",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "srcmanual@example.com",
                "guardian_full_name": "SrcManual Guardian",
                "guardian_personal_id": "010101-15151",
                "guardian_declared_address": "Riga 15, iela 7",
                "guardian_phone": "+37116161616",
                "member_full_name": "Child SrcManual",
                "member_personal_id": "010125-15151",
                "member_birth_date": "2025-09-01",
                "member_same_address_as_guardian": False,
                "member_actual_address": "Liepaja, iela 2",
            },
            files={},
            verified_account=acct,
        )
        sources = app.field_sources
        assert sources.get("member_actual_address") == "manual_only", (
            "member_actual_address with same_address=False must store "
            "manual_only in field_sources."
        )

    def test_guardian_email_stores_derived_system_filled(self):
        """Guardian email must be classified as derived_system_filled."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="srceemail@example.com",
            phone="+37117171717",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "srceemail@example.com",
                "guardian_full_name": "SrcEmail Guardian",
                "guardian_personal_id": "010101-17171",
                "guardian_declared_address": "Riga 17",
                "guardian_phone": "+37118181818",
                "member_full_name": "Child SrcEmail",
                "member_personal_id": "010125-17171",
                "member_birth_date": "2025-10-01",
                "member_actual_address": "Riga 17",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        sources = app.field_sources
        assert sources.get("guardian_email") == "derived_system_filled", (
            "guardian_email must store derived_system_filled in field_sources."
        )
