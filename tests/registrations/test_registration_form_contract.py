"""P1 + P2 Task 3 — Registration field-contract and grouped-form contract.

P1 sections (unchanged):
- Guardian/member/application field names
- Submit-time required fields
- Document separation
- Document.Kind values
- KitSizeOption model
- Draft allows incomplete values
- Same-address toggle
- Field-source support

P2 Task 3 additions:
- RegistrationApplicationForm.section_order class attribute
- RegistrationApplicationForm.grouped_fields() method
- RegistrationApplicationForm.error_summary_items() method
- Workspace template iterates over form.grouped_fields
"""

import pytest

from apps.accounts.models import ParentAccount

pytestmark = pytest.mark.django_db


# ===========================================================================
# 1-3. Form exposes all P1 fields; model retains field_sources JSON field
# ===========================================================================


class TestRegistrationApplicationFormFields:
    """P1 form exposes every field expected by the registration UX."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "guardian_full_name",
            "guardian_personal_id",
            "guardian_declared_address",
            "guardian_email",
            "guardian_phone",
            "member_full_name",
            "member_personal_id",
            "member_birth_date",
            "member_actual_address",
            "member_same_address_as_guardian",
            "member_kit_size_shirt",
            "member_kit_size_shorts",
            "preferred_agreement_signing",
            "support_club_instead_of_multi_child_discount",
        ],
    )
    def test_form_exposes_p1_field(self, field_name):
        from apps.registrations.forms import RegistrationApplicationForm

        assert field_name in RegistrationApplicationForm.base_fields

    def test_field_sources_json_field_exists(self):
        """field_sources JSON field must exist on the model for source classification."""
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


class TestDocumentKindSeparation:
    """Document fields must live on Document, not on RegistrationApplication."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "guardian_identity_document",
            "member_identity_document",
            "member_portrait_document",
            "child_identity_document",
        ],
    )
    def test_document_field_is_not_on_application_model(self, field_name):
        from apps.registrations.models import RegistrationApplication

        names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert field_name not in names


# ===========================================================================
# 6. Document.Kind must include all three P1 kinds
# ===========================================================================


class TestDocumentKindChoices:
    """Document.Kind enumerates only P1 kinds; child_identity must not exist."""

    @pytest.mark.parametrize(
        ("kind_value", "should_exist"),
        [
            ("guardian_identity", True),
            ("member_identity", True),
            ("member_portrait", True),
            ("child_identity", False),
        ],
    )
    def test_document_kind_membership(self, kind_value, should_exist):
        from apps.documents.models import Document

        values = {choice[0] for choice in Document.Kind.choices}
        assert (kind_value in values) is should_exist


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


# ===========================================================================
# 11. P2 Task 3 — Grouped form contract
# ===========================================================================


class TestGroupedFormContract:
    """RegistrationApplicationForm must expose section_order and grouped_fields()
    for the canonical workspace template to render grouped sections.

    Section order (from Task 3 plan):
      1. guardian — guardian_full_name, guardian_personal_id, guardian_email,
         guardian_phone, guardian_declared_address
      2. member — member_full_name, member_personal_id, member_birth_date,
         member_actual_address, member_same_address_as_guardian,
         member_kit_size_shirt, member_kit_size_shorts
      3. documents — guardian_identity_document, member_identity_document,
         member_portrait_document
      4. agreement — preferred_agreement_signing,
         support_club_instead_of_multi_child_discount
    """

    def test_section_order_class_attribute_exists(self):
        """RegistrationApplicationForm must have a section_order class attribute."""
        from apps.registrations.forms import RegistrationApplicationForm

        assert hasattr(RegistrationApplicationForm, "section_order"), (
            "RegistrationApplicationForm must define section_order class attribute."
        )

    def test_section_order_has_four_sections(self):
        """section_order must contain exactly 4 sections."""
        from apps.registrations.forms import RegistrationApplicationForm

        sections = [name for name, _ in RegistrationApplicationForm.section_order]
        assert len(sections) == 4, (
            f"Expected 4 sections, got {len(sections)}."
        )

    def test_section_order_names_are_guardian_member_documents_agreement(self):
        """Section names must be 'documents', 'guardian', 'member', 'agreement'."""
        from apps.registrations.forms import RegistrationApplicationForm

        sections = [name for name, _ in RegistrationApplicationForm.section_order]
        assert sections == ["documents", "guardian", "member", "agreement"], (
            f"Section names must be ['documents', 'guardian', 'member', 'agreement'], "
            f"got {sections}."
        )

    def test_guardian_section_fields(self):
        """Guardian section must contain: guardian_full_name, guardian_personal_id,
        guardian_email, guardian_phone, guardian_declared_address."""
        from apps.registrations.forms import RegistrationApplicationForm

        guardian_fields = [
            fields for name, fields in RegistrationApplicationForm.section_order
            if name == "guardian"
        ][0]
        expected = (
            "guardian_full_name",
            "guardian_personal_id",
            "guardian_email",
            "guardian_phone",
            "guardian_declared_address",
        )
        assert guardian_fields == expected, (
            f"Guardian section fields must be {expected}, got {guardian_fields}."
        )

    def test_member_section_fields(self):
        """Member section must contain: member_full_name, member_personal_id,
        member_birth_date, member_actual_address, member_same_address_as_guardian,
        member_kit_size_shirt, member_kit_size_shorts.

        Slice D — member_portrait_document moved to the documents section.
        """
        from apps.registrations.forms import RegistrationApplicationForm

        member_fields = [
            fields for name, fields in RegistrationApplicationForm.section_order
            if name == "member"
        ][0]
        expected = (
            "member_full_name",
            "member_personal_id",
            "member_birth_date",
            "member_same_address_as_guardian",
            "member_actual_address",
            "member_kit_size_shirt",
            "member_kit_size_shorts",
        )
        assert member_fields == expected, (
            f"Member section fields must be {expected}, got {member_fields}."
        )

    def test_documents_section_fields(self):
        """Documents section must contain: guardian_identity_document,
        member_identity_document, member_portrait_document.

        Slice D — member_portrait_document now lives in the documents section
        alongside the two identity uploads.
        """
        from apps.registrations.forms import RegistrationApplicationForm

        docs_fields = [
            fields for name, fields in RegistrationApplicationForm.section_order
            if name == "documents"
        ][0]
        expected = (
            "guardian_identity_document",
            "member_identity_document",
            "member_portrait_document",
        )
        assert docs_fields == expected, (
            f"Documents section fields must be {expected}, got {docs_fields}."
        )

    def test_agreement_section_fields(self):
        """Agreement section must contain: preferred_agreement_signing,
        support_club_instead_of_multi_child_discount, and preferred_payment_mode."""
        from apps.registrations.forms import RegistrationApplicationForm

        agree_fields = [
            fields for name, fields in RegistrationApplicationForm.section_order
            if name == "agreement"
        ][0]
        expected = (
            "preferred_agreement_signing",
            "support_club_instead_of_multi_child_discount",
            "preferred_payment_mode",
        )
        assert agree_fields == expected, (
            f"Agreement section fields must be {expected}, got {agree_fields}."
        )

    def test_grouped_fields_method_exists(self):
        """RegistrationApplicationForm must have a grouped_fields() method."""
        from apps.registrations.forms import RegistrationApplicationForm

        assert hasattr(RegistrationApplicationForm, "grouped_fields"), (
            "RegistrationApplicationForm must define grouped_fields() method."
        )

    def test_grouped_fields_yields_correct_sections(self):
        """grouped_fields() must yield (section_name, [bound_fields]) tuples."""
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        sections = list(form.grouped_fields())

        section_names = [name for name, _ in sections]
        assert section_names == ["documents", "guardian", "member", "agreement"], (
            f"grouped_fields() must yield sections in order, got {section_names}."
        )

    def test_grouped_fields_yields_correct_field_count_per_section(self):
        """Each section yielded by grouped_fields() must have the correct number of fields."""
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        sections = list(form.grouped_fields())

        expected_counts = {
            "documents": 3,
            "guardian": 5,
            "member": 7,
            "agreement": 3,
        }
        for name, fields in sections:
            assert len(fields) == expected_counts[name], (
                f"Section '{name}' must have {expected_counts[name]} fields, "
                f"got {len(fields)}."
            )

    def test_grouped_fields_yields_bound_field_objects(self):
        """Each item yielded by grouped_fields() must be a BoundField instance."""
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        for section_name, bound_fields in form.grouped_fields():
            for bf in bound_fields:
                assert hasattr(bf, "name"), (
                    f"Items in grouped_fields() must be BoundField objects, "
                    f"got {type(bf)}."
                )


# ===========================================================================
# 12. P2 Task 3 — Error summary contract
# ===========================================================================


class TestErrorSummaryContract:
    """RegistrationApplicationForm must expose error_summary_items() that
    returns a list of dicts with 'field', 'label', 'message' keys."""

    def test_error_summary_items_method_exists(self):
        """RegistrationApplicationForm must have an error_summary_items() method."""
        from apps.registrations.forms import RegistrationApplicationForm

        assert hasattr(RegistrationApplicationForm, "error_summary_items"), (
            "RegistrationApplicationForm must define error_summary_items() method."
        )

    def test_error_summary_items_returns_list_of_dicts(self):
        """error_summary_items() must return a list of dicts with field/label/message."""
        from apps.registrations.forms import RegistrationApplicationForm

        # Submit with invalid data to trigger errors
        form = RegistrationApplicationForm(
            data={
                "guardian_email": "",  # invalid — empty
                "guardian_full_name": "Valid Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Valid Child",
                "member_personal_id": "010125-54321",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            is_submit=True,
            has_existing_document=True,
        )
        # Force validation to populate errors
        form.is_valid()

        items = form.error_summary_items()

        assert isinstance(items, list), (
            f"error_summary_items() must return a list, got {type(items)}."
        )
        if items:
            first = items[0]
            assert isinstance(first, dict), (
                f"Each item must be a dict, got {type(first)}."
            )
            assert "field" in first, "Each item must have 'field' key."
            assert "label" in first, "Each item must have 'label' key."
            assert "message" in first, "Each item must have 'message' key."

    def test_error_summary_items_contains_guardian_email_error(self):
        """When guardian_email is empty, error_summary_items must include it."""
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm(
            data={
                "guardian_email": "",
                "guardian_full_name": "Valid Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Valid Child",
                "member_personal_id": "010125-54321",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
            is_submit=True,
            has_existing_document=True,
        )
        form.is_valid()

        items = form.error_summary_items()
        fields_with_errors = [item["field"] for item in items]

        assert "guardian_email" in fields_with_errors, (
            "error_summary_items must include guardian_email when it's invalid."
        )


# ===========================================================================
# 13. P2 Task 3 — Workspace template uses grouped_fields iteration
# ===========================================================================


class TestWorkspaceTemplateGroupedRendering:
    """The application_workspace.html template must iterate over
    form.grouped_fields for section rendering."""

    def test_template_uses_grouped_fields_iteration(self):
        """application_workspace.html must reference form.grouped_fields."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "application_workspace.html"
        content = tpl.read_text()
        assert "grouped_fields" in content, (
            "application_workspace.html must iterate over form.grouped_fields "
            "for grouped section rendering."
        )


# ===========================================================================
# 14. P4 Slice C Task 2 — personal_data_consent BooleanField on form
# ===========================================================================


class TestRegistrationApplicationFormConsentField:
    """The RegistrationApplicationForm must accept an optional
    personal_data_consent BooleanField that is NOT part of
    submit_required_fields nor section_order — the consent gate is enforced
    client-side and at the service layer, not at form-validation time."""

    def test_form_accepts_personal_data_consent_true(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm(
            data={
                "guardian_email": "consent@example.com",
                "personal_data_consent": "on",
            },
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["personal_data_consent"] is True

    def test_form_accepts_personal_data_consent_absent(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm(
            data={"guardian_email": "consent@example.com"},
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data.get("personal_data_consent") is False

    def test_form_consent_not_in_submit_required_fields(self):
        from apps.registrations.forms import RegistrationApplicationForm

        assert "personal_data_consent" not in RegistrationApplicationForm.submit_required_fields, (
            "personal_data_consent must NOT be a submit-required form field; "
            "the consent gate is enforced client-side and at the service layer."
        )

    def test_form_consent_not_in_section_order_fields(self):
        from apps.registrations.forms import RegistrationApplicationForm

        for _section_name, field_names in RegistrationApplicationForm.section_order:
            assert "personal_data_consent" not in field_names, (
                "personal_data_consent must NOT appear in section_order; the "
                "consent checkbox is rendered manually in the template, not via "
                "grouped_fields()."
            )

    def test_form_remains_valid_when_consent_absent_on_submit(self):
        """Even with is_submit=True, omitting personal_data_consent must not
        produce a consent-specific form error. The consent gate is enforced at
        the service layer (and client-side), never inside Form.clean()."""
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm(
            data={
                "guardian_email": "consentsubmit@example.com",
                # personal_data_consent intentionally omitted
            },
            is_submit=True,
            has_existing_document=True,
        )
        # Force validation; other submit-required fields will error, but
        # personal_data_consent must NOT appear in form.errors.
        form.is_valid()
        assert "personal_data_consent" not in form.errors, (
            "personal_data_consent absence must not surface as a form-layer "
            "error; the consent gate lives in the service layer."
        )


class TestSliceDFileWidgetAttrs:
    """P4 Slice D — canonical file inputs render visually hidden so the
    document_card partial's visible labels are the only tap surface."""

    def test_guardian_identity_file_input_is_visually_hidden(self):
        from apps.registrations.forms import RegistrationApplicationForm
        form = RegistrationApplicationForm()
        attrs = form.fields["guardian_identity_document"].widget.attrs
        css_class = attrs.get("class", "")
        assert "fk-visually-hidden" in css_class, (
            f"guardian_identity_document widget must include 'fk-visually-hidden' "
            f"in its class attr; got: {css_class!r}"
        )

    def test_member_identity_file_input_is_visually_hidden(self):
        from apps.registrations.forms import RegistrationApplicationForm
        form = RegistrationApplicationForm()
        attrs = form.fields["member_identity_document"].widget.attrs
        assert "fk-visually-hidden" in attrs.get("class", "")

    def test_member_portrait_file_input_is_visually_hidden(self):
        from apps.registrations.forms import RegistrationApplicationForm
        form = RegistrationApplicationForm()
        attrs = form.fields["member_portrait_document"].widget.attrs
        assert "fk-visually-hidden" in attrs.get("class", "")


# ===========================================================================
# 15. P6 — Form defaults for agreement signing and payment mode
# ===========================================================================


class TestFormFieldDefaults:
    """RegistrationApplicationForm must default preferred_agreement_signing
    to electronic and preferred_payment_mode to installments for new/empty
    selections. Explicit initial values must override."""

    def test_empty_form_agreement_signing_initial_is_electronic(self):
        from apps.registrations.forms import RegistrationApplicationForm
        from apps.registrations.models import RegistrationApplication

        form = RegistrationApplicationForm()
        assert (
            form.fields["preferred_agreement_signing"].initial
            == RegistrationApplication.AgreementSigning.ELECTRONIC
        ), (
            "Empty form must default preferred_agreement_signing.initial "
            "to 'electronic'."
        )

    def test_empty_form_payment_mode_initial_is_installments(self):
        from apps.registrations.forms import RegistrationApplicationForm
        from apps.registrations.models import RegistrationApplication

        form = RegistrationApplicationForm()
        assert (
            form.fields["preferred_payment_mode"].initial
            == RegistrationApplication.PaymentMode.INSTALLMENTS
        ), (
            "Empty form must default preferred_payment_mode.initial "
            "to 'installments'."
        )

    def test_explicit_initial_values_override_defaults(self):
        from apps.registrations.forms import RegistrationApplicationForm
        from apps.registrations.models import RegistrationApplication

        form = RegistrationApplicationForm(
            initial={
                "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
                "preferred_payment_mode": RegistrationApplication.PaymentMode.UPFRONT,
            },
        )
        assert (
            form["preferred_agreement_signing"].value()
            == RegistrationApplication.AgreementSigning.PAPER
        ), (
            "Explicit initial 'paper' must override the default 'electronic' "
            "in the rendered field value."
        )
        assert (
            form["preferred_payment_mode"].value()
            == RegistrationApplication.PaymentMode.UPFRONT
        ), (
            "Explicit initial 'upfront' must override the default 'installments' "
            "in the rendered field value."
        )

    def test_empty_string_initial_values_use_defaults(self):
        from apps.registrations.forms import RegistrationApplicationForm
        from apps.registrations.models import RegistrationApplication

        form = RegistrationApplicationForm(
            initial={
                "preferred_agreement_signing": "",
                "preferred_payment_mode": "",
            },
        )
        assert (
            form["preferred_agreement_signing"].value()
            == RegistrationApplication.AgreementSigning.ELECTRONIC
        )
        assert (
            form["preferred_payment_mode"].value()
            == RegistrationApplication.PaymentMode.INSTALLMENTS
        )
