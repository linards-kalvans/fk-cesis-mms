"""Kit-size collapse — single parent-facing "Formas izmērs" field.

Acceptance criteria (design spec 2026-07-07):
- One parent-facing kit-size field labelled "Formas izmērs".
- member_kit_size_shorts is absent from the parent form section, submit-required
  fields, and step-gating widget attrs.
- Active shirt options sort naturally: XS < S < M < L < XL < 2XL...; inactive
  options are excluded.
- Draft save persists member_kit_size_shirt without requiring shorts.
- Submit validation requires member_kit_size_shirt; does not require shorts.
- Parent workspace renders "Formas izmērs" and does not render
  "Krekla izmērs" or "Šortu izmērs".
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _member_section_fields() -> tuple[str, ...]:
    from apps.registrations.forms import RegistrationApplicationForm

    for name, fields in RegistrationApplicationForm.section_order:
        if name == "member":
            return fields
    raise AssertionError("member section not found in section_order")


# ---------------------------------------------------------------------------
# 1. Form contract
# ---------------------------------------------------------------------------


class TestKitSizeCollapseFormContract:
    """Parent form exposes only member_kit_size_shirt as the kit-size field."""

    def test_member_section_contains_member_kit_size_shirt(self):
        assert "member_kit_size_shirt" in _member_section_fields()

    def test_member_section_does_not_contain_member_kit_size_shorts(self):
        assert "member_kit_size_shorts" not in _member_section_fields()

    def test_member_kit_size_shirt_label_is_formas_izmers(self):
        from apps.registrations.forms import RegistrationApplicationForm

        assert (
            RegistrationApplicationForm.base_fields["member_kit_size_shirt"].label
            == "Formas izmērs"
        )

    def test_member_kit_size_shorts_not_in_submit_required_fields(self):
        from apps.registrations.forms import RegistrationApplicationForm

        assert "member_kit_size_shorts" not in RegistrationApplicationForm.submit_required_fields

    def test_member_kit_size_shorts_not_step_gated_in_rendered_widget(self):
        """Even if the field class still exists on the form (legacy), the
        rendered widget must not carry data-step-required attrs."""
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        if "member_kit_size_shorts" in form.fields:
            attrs = form.fields["member_kit_size_shorts"].widget.attrs
            assert "data-step-required" not in attrs, (
                "member_kit_size_shorts must not be step-gated after collapse."
            )


# ---------------------------------------------------------------------------
# 2. Choice ordering
# ---------------------------------------------------------------------------


class TestKitSizeChoiceOrdering:
    """Active shirt options sort naturally; inactive options are excluded."""

    def test_choices_sort_xs_s_m_and_exclude_inactive(self):
        from apps.members.models import KitSizeOption
        from apps.registrations.forms import RegistrationApplicationForm

        KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="M", is_active=True)
        KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="XS", is_active=True)
        KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="S", is_active=True)
        KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="L", is_active=False)

        form = RegistrationApplicationForm()
        labels = [label for _, label in form.fields["member_kit_size_shirt"].choices]

        assert labels == ["XS", "S", "M"]


# ---------------------------------------------------------------------------
# 3. Draft persistence
# ---------------------------------------------------------------------------


class TestKitSizeCollapseDraftPersistence:
    """Draft save persists member_kit_size_shirt without requiring shorts."""

    def test_draft_save_persists_kit_size_shirt_without_shorts(self):
        from apps.members.models import KitSizeOption

        shirt = KitSizeOption.objects.create(
            kind=KitSizeOption.Kind.SHIRT, label="M", is_active=True
        )
        acct = ParentAccount.objects.create(
            email="kitdraft@example.com", phone="+37100000001"
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "kitdraft@example.com",
                "guardian_full_name": "Draft Kit Parent",
                "guardian_personal_id": "010101-00001",
                "guardian_declared_address": "Riga 1",
                "guardian_phone": "+37100000001",
                "member_full_name": "Draft Kit Child",
                "member_personal_id": "010125-00001",
                "member_birth_date": "2025-01-01",
                "member_actual_address": "Riga 1",
                "member_kit_size_shirt": shirt.pk,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        assert app.member_kit_size_shirt_id == shirt.pk


# ---------------------------------------------------------------------------
# 4. Submit validation
# ---------------------------------------------------------------------------


class TestKitSizeCollapseSubmitValidation:
    """Submit requires member_kit_size_shirt; does not require shorts."""

    def _make_verified_account(self, email: str) -> ParentAccount:
        return ParentAccount.objects.create(email=email, phone="+37100000099")  # type: ignore[no-any-return]

    def test_submit_fails_when_member_kit_size_shirt_absent(self):
        from apps.registrations.services import submit_application

        acct = self._make_verified_account("kitmissing@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "kitmissing@example.com",
                "guardian_full_name": "NoKit Parent",
                "guardian_personal_id": "010101-00002",
                "guardian_declared_address": "Riga 2",
                "guardian_phone": "+37100000099",
                "member_full_name": "NoKit Child",
                "member_personal_id": "010125-00002",
                "member_birth_date": "2025-02-01",
                "member_actual_address": "Riga 2",
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_kit_validation_passes_with_shirt_only_no_shorts(self):
        """When member_kit_size_shirt is set and member_kit_size_shorts is
        unset, the kit-size portion of submit validation must not raise.
        Other submit requirements (documents etc.) may still fail; we isolate
        the kit-size check via the private helper used by submit_application.
        """
        from apps.members.models import KitSizeOption
        from apps.registrations.services import _require_valid_kit_sizes

        shirt = KitSizeOption.objects.create(
            kind=KitSizeOption.Kind.SHIRT, label="S", is_active=True
        )
        acct = self._make_verified_account("kitshirtonly@example.com")
        app = create_or_update_draft(
            data={
                "guardian_email": "kitshirtonly@example.com",
                "guardian_full_name": "ShirtOnly Parent",
                "guardian_personal_id": "010101-00003",
                "guardian_declared_address": "Riga 3",
                "guardian_phone": "+37100000099",
                "member_full_name": "ShirtOnly Child",
                "member_personal_id": "010125-00003",
                "member_birth_date": "2025-03-01",
                "member_actual_address": "Riga 3",
                "member_kit_size_shirt": shirt.pk,
                "preferred_agreement_signing": "paper",
            },
            files={},
            verified_account=acct,
        )
        assert app.member_kit_size_shirt_id == shirt.pk
        assert app.member_kit_size_shorts_id is None
        # Must not raise — kit-size validation is satisfied by shirt alone.
        _require_valid_kit_sizes(app)


# ---------------------------------------------------------------------------
# 5. Parent workspace rendering
# ---------------------------------------------------------------------------


class TestKitSizeCollapseWorkspaceRendering:
    """Parent workspace renders "Formas izmērs" and not the old labels."""

    def _make_draft(self, email: str = "kitrender@example.com"):
        from apps.members.models import KitSizeOption

        KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHIRT,
            label="S",
            defaults={"is_active": True},
        )
        acct = ParentAccount.objects.create(email=email, phone="+37120000099")
        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Render Parent",
                "guardian_personal_id": "010101-00004",
                "guardian_phone": "+37120000099",
                "guardian_declared_address": "Riga 4",
                "member_full_name": "Render Child",
                "member_personal_id": "010125-00004",
                "member_birth_date": "2025-04-01",
            },
            files={},
            verified_account=acct,
        )
        return acct, app

    def test_workspace_renders_formas_izmers_label(self):
        client = Client()
        acct, app = self._make_draft("kitrender1@example.com")
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200
        html = resp.content.decode()

        assert "Formas izmērs" in html

    def test_workspace_does_not_render_krekla_izmers(self):
        client = Client()
        acct, app = self._make_draft("kitrender2@example.com")
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200
        html = resp.content.decode()

        assert "Krekla izmērs" not in html

    def test_workspace_does_not_render_sortu_izmers(self):
        client = Client()
        acct, app = self._make_draft("kitrender3@example.com")
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200
        html = resp.content.decode()

        assert "Šortu izmērs" not in html
