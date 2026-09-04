"""P23 — MedicalPermit service-layer contract.

Services in `apps.documents.medical_permits` do not exist yet. All imports of
that module / the model live inside test bodies so collection succeeds and
each test fails at run time with the feature-missing ImportError.
"""

from __future__ import annotations

import datetime

import pytest

pytestmark = pytest.mark.django_db

MAX_MEDICAL_PERMIT_BYTES = 25 * 1024 * 1024


def _upload(name="permit.pdf", content_type="application/pdf", size=None):
    from django.core.files.uploadedfile import SimpleUploadedFile

    content = b"%PDF-1.4 test" if size is None else b"x" * size
    return SimpleUploadedFile(name=name, content=content, content_type=content_type)


def _account(seq):
    from apps.accounts.models import ParentAccount

    return ParentAccount.objects.create(email=f"permitsvc-{seq}@example.com")


def _make_app(account, *, status="submitted", member_name="Service Child"):
    from apps.registrations.models import RegistrationApplication

    return RegistrationApplication.objects.create(
        parent_account=account,
        claimed_email=account.email,
        status=status,
        member_full_name=member_name,
    )


def _link_guardian(account, app):
    from tests.support import make_guardian

    guardian = make_guardian(account=account, full_name="Service Guardian")
    app.guardian = guardian
    app.save(update_fields=["guardian"])
    return guardian


def _make_member(guardian, name="Service Member Child"):
    from apps.members.models import Member

    return Member.objects.create(full_name=name, guardian=guardian)


def _bare_permit(app):
    from apps.documents.models import MedicalPermit

    return MedicalPermit.objects.create(
        application=app,
        source=MedicalPermit.Source.PARENT_UPLOAD,
        valid_until=datetime.date(2027, 9, 30),
    )


def _freeze(monkeypatch, year, month, day):
    import django.utils.timezone as timezone_module

    def _localdate():
        return datetime.date(year, month, day)

    monkeypatch.setattr(timezone_module, "localdate", _localdate)


# ---------------------------------------------------------------------------
# validate_medical_permit_upload
# ---------------------------------------------------------------------------


class TestValidateMedicalPermitUpload:
    @pytest.mark.parametrize(
        ("filename", "content_type"),
        [
            ("permit.pdf", "application/pdf"),
            ("permit.jpg", "image/jpeg"),
            ("permit.jpeg", "image/jpeg"),
            ("permit.png", "image/png"),
            ("permit.heic", "image/heic"),
        ],
    )
    def test_accepts_supported_filename_and_mime_pairs(self, filename, content_type):
        """Allowed formats pair an allowed filename extension with its MIME type."""
        from apps.documents.medical_permits import validate_medical_permit_upload

        assert (
            validate_medical_permit_upload(
                _upload(name=filename, content_type=content_type)
            )
            is None
        )

    def test_accepts_exactly_max_size(self):
        from apps.documents.medical_permits import validate_medical_permit_upload

        upload = _upload(size=MAX_MEDICAL_PERMIT_BYTES)
        assert validate_medical_permit_upload(upload) is None

    def test_rejects_unsupported_content_type(self):
        from apps.documents.medical_permits import validate_medical_permit_upload

        with pytest.raises(ValueError):
            validate_medical_permit_upload(_upload(content_type="application/zip"))

    def test_rejects_disallowed_extension_with_allowed_content_type(self):
        """A renamed unsupported file (bad extension, allowed MIME) is rejected —
        a renamed archive must not pass as a PDF just because its declared MIME
        is application/pdf."""
        from apps.documents.medical_permits import validate_medical_permit_upload

        with pytest.raises(ValueError):
            validate_medical_permit_upload(
                _upload(name="permit.zip", content_type="application/pdf")
            )

    def test_rejects_oversize(self):
        from apps.documents.medical_permits import validate_medical_permit_upload

        upload = _upload(size=MAX_MEDICAL_PERMIT_BYTES + 1)
        with pytest.raises(ValueError):
            validate_medical_permit_upload(upload)


# ---------------------------------------------------------------------------
# replace_medical_permit
# ---------------------------------------------------------------------------


class TestReplaceMedicalPermit:
    def test_replace_saves_file_metadata_and_fixed_expiry(self, monkeypatch):
        from apps.documents.medical_permits import replace_medical_permit

        _freeze(monkeypatch, 2026, 1, 15)
        account = _account(1)
        app = _make_app(account)
        permit = _bare_permit(app)

        result = replace_medical_permit(
            permit, _upload("replacement.pdf"), actor_label="parent: x"
        )

        assert result.pk == permit.pk
        assert result.source == "parent_upload"
        assert result.original_filename == "replacement.pdf"
        assert result.content_type == "application/pdf"
        assert result.file_size == len(b"%PDF-1.4 test")
        assert result.file != ""
        # Recorded in calendar year 2026 → valid until 30 September 2027.
        assert result.valid_until == datetime.date(2027, 9, 30)

    def test_replace_in_december_uses_next_year_expiry(self, monkeypatch):
        from apps.documents.medical_permits import replace_medical_permit

        _freeze(monkeypatch, 2026, 12, 31)
        account = _account(2)
        app = _make_app(account)
        permit = _bare_permit(app)

        result = replace_medical_permit(
            permit, _upload(), actor_label="parent: x"
        )

        assert result.valid_until == datetime.date(2027, 9, 30)

    def test_replace_with_staff_actor_sets_staff_source(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import replace_medical_permit

        _freeze(monkeypatch, 2026, 5, 1)
        account = _account(3)
        app = _make_app(account)
        permit = _bare_permit(app)
        staff = User.objects.create_user(username="staff-user")

        result = replace_medical_permit(
            permit, _upload(), actor_label="staff: y", actor=staff
        )

        assert result.source == "staff_upload"

    def test_replace_clears_prior_staff_confirmation(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import (
            confirm_medical_permit,
            replace_medical_permit,
        )

        _freeze(monkeypatch, 2026, 6, 1)
        account = _account(4)
        app = _make_app(account)
        permit = _bare_permit(app)
        staff = User.objects.create_user(username="confirm-first")
        confirm_medical_permit(permit, actor=staff)
        assert permit.confirmed_by_id is not None

        replace_medical_permit(permit, _upload(), actor_label="parent: x")

        permit.refresh_from_db()
        assert permit.confirmed_by_id is None
        assert permit.confirmed_at is None
        assert permit.file != ""

    def test_replace_rejected_content_type_preserves_old_file(self):
        from apps.documents.medical_permits import replace_medical_permit

        account = _account(5)
        app = _make_app(account)
        permit = _bare_permit(app)
        replace_medical_permit(permit, _upload("old.pdf"), actor_label="parent: x")
        old_name = permit.file.name
        old_bytes = permit.file.read()

        with pytest.raises(ValueError):
            replace_medical_permit(
                permit, _upload("bad.zip", content_type="application/zip"),
                actor_label="parent: x",
            )

        permit.refresh_from_db()
        assert permit.file.name == old_name
        assert permit.file.read() == old_bytes

    def test_replace_oversize_preserves_old_file(self):
        from apps.documents.medical_permits import replace_medical_permit

        account = _account(6)
        app = _make_app(account)
        permit = _bare_permit(app)
        replace_medical_permit(permit, _upload("old.pdf"), actor_label="parent: x")
        old_name = permit.file.name
        old_bytes = permit.file.read()

        with pytest.raises(ValueError):
            replace_medical_permit(
                permit,
                _upload("huge.pdf", size=MAX_MEDICAL_PERMIT_BYTES + 1),
                actor_label="parent: x",
            )

        permit.refresh_from_db()
        assert permit.file.name == old_name
        assert permit.file.read() == old_bytes

    def test_replace_storage_failure_preserves_old_file(self, monkeypatch):
        from apps.documents.medical_permits import replace_medical_permit

        account = _account(7)
        app = _make_app(account)
        permit = _bare_permit(app)
        replace_medical_permit(permit, _upload("old.pdf"), actor_label="parent: x")
        old_name = permit.file.name
        old_bytes = permit.file.read()

        storage = permit.file.field.storage

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(storage, "save", _boom)

        with pytest.raises(Exception):
            replace_medical_permit(
                permit, _upload("new.pdf"), actor_label="parent: x"
            )

        permit.refresh_from_db()
        assert permit.file.name == old_name
        assert permit.file.read() == old_bytes

    def test_replace_database_persistence_failure_preserves_old_file(
        self, monkeypatch,
    ):
        """The persistence phase (model save) failing after candidate handling
        has started must leave the original file name and bytes intact.

        ``MedicalPermit.save`` is patched to raise so the database-write step of
        the replacement fails; the candidate may already be on disk, but the
        prior file must not be deleted and the stored row must still reference
        it. No implementation-specific temporary-file name is asserted.
        """
        from apps.documents.models import MedicalPermit
        from apps.documents.medical_permits import replace_medical_permit

        account = _account(24)
        app = _make_app(account)
        permit = _bare_permit(app)
        replace_medical_permit(permit, _upload("old.pdf"), actor_label="parent: x")
        old_name = permit.file.name
        old_bytes = permit.file.read()

        def _boom(*args, **kwargs):
            raise RuntimeError("database persistence failed")

        monkeypatch.setattr(MedicalPermit, "save", _boom)

        with pytest.raises(RuntimeError):
            replace_medical_permit(
                permit, _upload("new.pdf"), actor_label="parent: x"
            )

        permit.refresh_from_db()
        assert permit.file.name == old_name
        assert permit.file.read() == old_bytes


# ---------------------------------------------------------------------------
# confirm_medical_permit / clear_medical_permit_confirmation
# ---------------------------------------------------------------------------


class TestConfirmAndClear:
    def test_confirm_records_no_file_confirmation(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import confirm_medical_permit

        _freeze(monkeypatch, 2026, 7, 1)
        account = _account(8)
        app = _make_app(account)
        permit = _bare_permit(app)
        from apps.documents.medical_permits import replace_medical_permit

        replace_medical_permit(permit, _upload(), actor_label="parent: x")
        assert permit.file != ""
        staff = User.objects.create_user(username="confirmer")

        result = confirm_medical_permit(permit, actor=staff)

        assert result.pk == permit.pk
        assert result.source == "staff_confirmation"
        assert result.file == ""
        assert result.confirmed_by_id == staff.pk
        assert result.confirmed_at is not None
        assert result.valid_until == datetime.date(2027, 9, 30)

    def test_confirm_sets_next_year_expiry_in_december(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import confirm_medical_permit

        _freeze(monkeypatch, 2026, 12, 31)
        account = _account(9)
        app = _make_app(account)
        permit = _bare_permit(app)
        staff = User.objects.create_user(username="december-confirmer")

        result = confirm_medical_permit(permit, actor=staff)

        assert result.valid_until == datetime.date(2027, 9, 30)

    def test_clear_removes_confirmation_and_record_becomes_missing(
        self, monkeypatch,
    ):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import (
            clear_medical_permit_confirmation,
            confirm_medical_permit,
            medical_permit_status,
        )

        _freeze(monkeypatch, 2026, 8, 1)
        account = _account(10)
        app = _make_app(account)
        permit = _bare_permit(app)
        staff = User.objects.create_user(username="clear-me")
        confirm_medical_permit(permit, actor=staff)

        result = clear_medical_permit_confirmation(permit, actor=staff)

        assert result.confirmed_by_id is None
        assert result.confirmed_at is None
        # No file and no confirmation → missing.
        assert medical_permit_status(result, on=datetime.date(2026, 8, 1)) == "missing"

    def test_clear_does_not_touch_stored_file(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.medical_permits import (
            clear_medical_permit_confirmation,
            medical_permit_status,
            replace_medical_permit,
        )

        _freeze(monkeypatch, 2026, 8, 1)
        account = _account(11)
        app = _make_app(account)
        permit = _bare_permit(app)
        # Give the permit a stored file first; clearing must leave it intact.
        permit = replace_medical_permit(
            permit, _upload("held.pdf"), actor_label="parent: x"
        )
        stored_name = permit.file.name
        stored_bytes = permit.file.read()
        user = User.objects.create_user(username="parent-holder")

        result = clear_medical_permit_confirmation(permit, actor=user)

        result.refresh_from_db()
        assert result.file.name == stored_name
        assert result.file.read() == stored_bytes
        assert medical_permit_status(result, on=datetime.date(2026, 8, 1)) != "missing"

    def test_confirm_resets_validity_to_next_september(self, monkeypatch):
        """A staff confirmation in calendar year N resets validity to 30
        September N+1 even when the permit carried an older valid_until."""
        from django.contrib.auth.models import User

        from apps.documents.models import MedicalPermit
        from apps.documents.medical_permits import confirm_medical_permit

        _freeze(monkeypatch, 2026, 7, 1)
        account = _account(25)
        app = _make_app(account)
        permit = MedicalPermit.objects.create(
            application=app,
            source=MedicalPermit.Source.PARENT_UPLOAD,
            valid_until=datetime.date(2025, 9, 30),  # stale prior validity
        )
        staff = User.objects.create_user(username="reset-confirmer")

        result = confirm_medical_permit(permit, actor=staff)

        # Confirmed in 2026 → valid through 30 September 2027, not the old 2025.
        assert result.valid_until == datetime.date(2027, 9, 30)

    def test_confirm_database_failure_preserves_stored_file(self, monkeypatch):
        """A DB persistence failure during confirmation must not destroy the
        stored evidence file — the original file survives the failed confirm.

        ``MedicalPermit.save`` is patched to raise so the database-write step
        of the confirmation fails; the stored file must still be intact and
        referenced by the row. No internal/temporary name is asserted.
        """
        from django.contrib.auth.models import User

        from apps.documents.models import MedicalPermit
        from apps.documents.medical_permits import (
            confirm_medical_permit,
            replace_medical_permit,
        )

        _freeze(monkeypatch, 2026, 7, 1)
        account = _account(26)
        app = _make_app(account)
        permit = _bare_permit(app)
        permit = replace_medical_permit(
            permit, _upload("held.pdf"), actor_label="parent: x"
        )
        stored_name = permit.file.name
        stored_bytes = permit.file.read()
        staff = User.objects.create_user(username="confirm-db-fail")

        def _boom(*args, **kwargs):
            raise RuntimeError("database persistence failed")

        monkeypatch.setattr(MedicalPermit, "save", _boom)

        with pytest.raises(RuntimeError):
            confirm_medical_permit(permit, actor=staff)

        permit.refresh_from_db()
        assert permit.file.name == stored_name
        assert permit.file.read() == stored_bytes


# ---------------------------------------------------------------------------
# attach_application_medical_permit + approval integration
# ---------------------------------------------------------------------------


class TestAttachApplicationMedicalPermit:
    def test_attaches_application_permit_to_member(self):
        from apps.documents.medical_permits import attach_application_medical_permit

        account = _account(12)
        app = _make_app(account)
        guardian = _link_guardian(account, app)
        member = _make_member(guardian)
        permit = _bare_permit(app)
        app_id = app.pk
        permit_id = permit.pk

        result = attach_application_medical_permit(app, member)

        assert result is not None
        assert result.pk == permit_id
        # Member link added; application linkage retained for traceability.
        assert result.member_id == member.pk
        assert result.application_id == app_id

    def test_returns_none_when_application_has_no_permit(self):
        from apps.documents.medical_permits import attach_application_medical_permit

        account = _account(13)
        app = _make_app(account)
        guardian = _link_guardian(account, app)
        member = _make_member(guardian)

        assert attach_application_medical_permit(app, member) is None

        from apps.documents.models import MedicalPermit

        assert MedicalPermit.objects.count() == 0

    def test_attach_is_idempotent(self):
        from apps.documents.medical_permits import attach_application_medical_permit

        from apps.documents.models import MedicalPermit

        account = _account(14)
        app = _make_app(account)
        guardian = _link_guardian(account, app)
        member = _make_member(guardian)
        permit = _bare_permit(app)

        first = attach_application_medical_permit(app, member)
        second = attach_application_medical_permit(app, member)

        assert first.pk == second.pk == permit.pk
        assert MedicalPermit.objects.count() == 1


class TestApproveApplicationIntegration:
    def _submitted_with_permit(self, seq):
        from apps.documents.models import MedicalPermit

        account = _account(seq)
        app = _make_app(account)
        guardian = _link_guardian(account, app)
        permit = MedicalPermit.objects.create(
            application=app,
            source=MedicalPermit.Source.PARENT_UPLOAD,
            valid_until=datetime.date(2027, 9, 30),
        )
        return app, guardian, permit

    def test_approval_attaches_permit_inside_transaction(self):
        from django.contrib.auth.models import User

        from apps.registrations.services import approve_application

        app, _guardian, permit = self._submitted_with_permit(20)
        reviewer = User.objects.create_user(username="approver-20")

        approve_application(app, reviewer)

        app.refresh_from_db()
        member = app.approved_member
        assert member is not None
        assert member.medical_permit.pk == permit.pk
        # Traceability retained.
        permit.refresh_from_db()
        assert permit.application_id == app.pk
        assert permit.member_id == member.pk

    def test_approval_without_permit_creates_none(self):
        from django.contrib.auth.models import User

        from apps.documents.models import MedicalPermit
        from apps.registrations.services import approve_application

        account = _account(21)
        app = _make_app(account)
        _link_guardian(account, app)
        reviewer = User.objects.create_user(username="approver-21")

        approve_application(app, reviewer)

        assert MedicalPermit.objects.count() == 0

    def test_reapproval_does_not_duplicate_or_mutate_permit(self):
        from django.contrib.auth.models import User

        from apps.documents.models import MedicalPermit
        from apps.registrations.services import approve_application

        app, _guardian, permit = self._submitted_with_permit(22)
        reviewer = User.objects.create_user(username="approver-22")
        approve_application(app, reviewer)
        original_valid_until = permit.valid_until
        original_pk = permit.pk

        approve_application(app, reviewer)

        perm = app.approved_member.medical_permit
        assert perm.pk == original_pk
        assert perm.valid_until == original_valid_until
        assert MedicalPermit.objects.count() == 1

    def test_failed_approval_leaves_no_partial_linkage(self, monkeypatch):
        from django.contrib.auth.models import User

        from apps.documents.models import MedicalPermit
        from apps.members.models import Member
        from apps.registrations.services import approve_application

        account = _account(23)
        app = _make_app(account)
        _link_guardian(account, app)
        permit = _bare_permit(app)
        reviewer = User.objects.create_user(username="approver-23")

        def _boom(*args, **kwargs):
            raise RuntimeError("agreement creation failed")

        monkeypatch.setattr(
            "apps.registrations.services.create_agreement_for_member", _boom
        )

        with pytest.raises(RuntimeError):
            approve_application(app, reviewer)

        # Nothing partial: no member row, no permit linked to a member,
        # the application is still submitted and unapproved.
        assert Member.objects.filter(guardian=app.guardian).count() == 0
        assert (
            MedicalPermit.objects.filter(member_id__isnull=False).count() == 0
        )
        app.refresh_from_db()
        assert app.status == "submitted"
        assert app.approved_member_id is None
        assert app.medical_permit.pk == permit.pk