"""Slice C — guardian-profile lock signal + form/view locking + visual-state hooks."""

from pathlib import Path

import pytest

from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db

GUARDIAN_PROFILE_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_phone",
    "guardian_declared_address",
)


class TestGuardianProfilePopulated:
    def test_false_when_no_guardian_linked(self):
        app = RegistrationApplication.objects.create(claimed_email="p@example.com")
        assert app.guardian_profile_populated is False

    def test_false_when_guardian_has_empty_full_name(self, parent_account, make_guardian):
        guardian = make_guardian(parent_account)  # full_name="" by default
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian
        )
        assert app.guardian_profile_populated is False

    def test_true_when_guardian_full_name_set(self, parent_account, make_guardian):
        guardian = make_guardian(parent_account, full_name="Anna Ozola")
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian
        )
        assert app.guardian_profile_populated is True


class TestFormReadonlyLocking:
    def test_email_always_readonly(self):
        form = RegistrationApplicationForm()
        assert form.fields["guardian_email"].widget.attrs.get("readonly") == "readonly"

    def test_profile_fields_readonly_when_locked(self):
        form = RegistrationApplicationForm(guardian_profile_locked=True)
        for name in GUARDIAN_PROFILE_FIELDS:
            assert form.fields[name].widget.attrs.get("readonly") == "readonly", name

    def test_profile_fields_editable_when_unlocked(self):
        form = RegistrationApplicationForm(guardian_profile_locked=False)
        for name in GUARDIAN_PROFILE_FIELDS:
            assert "readonly" not in form.fields[name].widget.attrs, name


class TestWorkspaceLockWiring:
    def test_returning_parent_sees_locked_profile(self, verified_client, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)
        guardian.full_name = "Anna Ozola"
        guardian.save(update_fields=["full_name"])

        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )
        resp = verified_client.get(f"/applications/{app.id}/")
        assert resp.status_code == 200
        assert resp.context["guardian_profile_locked"] is True
        assert resp.context["form"].fields["guardian_full_name"].widget.attrs.get("readonly") == "readonly"

    def test_first_registration_profile_unlocked(self, verified_client, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)  # empty profile
        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )
        resp = verified_client.get(f"/applications/{app.id}/")
        assert resp.status_code == 200
        assert resp.context["guardian_profile_locked"] is False
        assert "readonly" not in resp.context["form"].fields["guardian_full_name"].widget.attrs


class TestLockedRenderMarkup:
    def _make_locked_app(self, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)
        guardian.full_name = "Anna Ozola"
        guardian.save(update_fields=["full_name"])
        return RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )

    def test_locked_render_includes_unlock_toggle(self, verified_client, parent_account):
        app = self._make_locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert "data-guardian-unlock" in html
        assert "Rediģēt vecāka datus" in html

    def test_unlocked_render_omits_unlock_toggle(self, verified_client, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)  # empty profile
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian, claimed_email=parent_account.email
        )
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert "data-guardian-unlock" not in html


# ---------------------------------------------------------------------------
# Visual-state hooks — approved design: stateful toggle + grayed locked fields.
# ---------------------------------------------------------------------------

_LOCKABLE_FIELDS = [
    "id_guardian_full_name",
    "id_guardian_personal_id",
    "id_guardian_phone",
    "id_guardian_declared_address",
]


class TestGuardianLockVisualState:
    """Acceptance criteria: locked render exposes data attributes, toggle text,
    lock class hook, correct unlockable field set, and CSS contract."""

    @staticmethod
    def _locked_app(parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)
        guardian.full_name = "Anna Ozola"
        guardian.save(update_fields=["full_name"])
        return RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )

    def test_locked_block_has_lock_state_data_attr(self, verified_client, parent_account):
        """Criterion 1: data-guardian-lock-state="locked" on the lock block."""
        app = self._locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert 'data-guardian-lock-state="locked"' in html

    def test_locked_script_contains_future_toggle_text(self, verified_client, parent_account):
        """Criterion 2: Slēgt rediģēšanu appears in the inline script alongside
        Rediģēt vecāka datus, so the client can switch the label on toggle."""
        app = self._locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert "Rediģēt vecāka datus" in html
        assert "Slēgt rediģēšanu" in html

    def test_locked_script_contains_lock_class_hook(self, verified_client, parent_account):
        """Criterion 3: fk-input--guardian-locked string in the template/script
        so JS can gray the four lockable profile fields."""
        app = self._locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert "fk-input--guardian-locked" in html

    def test_unlockable_fields_include_four_profile_exclude_email(self, verified_client, parent_account):
        """Criterion 4: The unlockable-field list contains the four profile
        field DOM ids and does NOT contain id_guardian_email."""
        app = self._locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        for field_id in _LOCKABLE_FIELDS:
            assert field_id in html, f"{field_id} missing from unlock script"
        # Email must NOT be in the unlockable list.  The id_guardian_email
        # input exists in the form, but the JS array literal must not list it.
        assert "'id_guardian_email'" not in html

    def test_guardian_email_is_always_rendered_with_locked_visual_class(self, verified_client, parent_account):
        """Guardian email is never editable by parents, so it should always
        use the same gray visual as locked profile fields."""
        app = self._locked_app(parent_account)
        html = verified_client.get(f"/applications/{app.id}/").content.decode()
        assert 'id="id_guardian_email"' in html
        assert 'name="guardian_email"' in html
        assert 'fk-input--guardian-locked' in html


class TestGuardianLockCssContract:
    """Criterion 5: The CSS file must define the locked-field visual class."""

    _CSS_PATH = (
        Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css"
    )

    def test_parent_theme_defines_fk_input_guardian_locked(self):
        css = self._CSS_PATH.read_text()
        assert ".fk-input--guardian-locked" in css
