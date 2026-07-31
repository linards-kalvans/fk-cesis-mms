"""Task 2 — Portal chooser behavior with redesigned parent shell.

Covers Task 2 portal redesign assertions that depend on portal
behavior (draft priority, start-new CTA, registrations list,
verified gate). These tests use the same session-injection pattern
as the existing P1 chooser tests but target the redesigned
portal template structure.

Strategy:
- Assert stable text hooks (Turpināt pieteikumu, Sākt jaunu reģistrāciju,
  Nav pieteikumu, Melnraksts, Skatīt).
- Assert fk-parent-page shell hook presence.
- Do not assert exact DOM nesting.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.contrib.sessions.backends.db import SessionStore

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_verified(client: Client, account: ParentAccount) -> None:
    """Establish verified guardian session by injecting the session cookie."""
    session = SessionStore()
    session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


# ===========================================================================
# Portal redesigned — shell and hero summary
# ===========================================================================


class TestPortalShellAndHero:
    """Portal must render the new shared parent shell and hero summary."""

    def test_portal_has_fk_parent_page_wrapper(self):
        """Portal must contain 'fk-parent-page' shell hook."""
        acct = ParentAccount.objects.create(
            email="shelltest@example.com",
            phone="+3711111111",
        )
        client = Client()
        _login_verified(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode(), (
            "Portal must use fk-parent-page shell."
        )

    def test_portal_has_fk_site_header(self):
        """Portal must contain 'fk-site-header' hook."""
        acct = ParentAccount.objects.create(
            email="headertest@example.com",
            phone="+37122222222",
        )
        client = Client()
        _login_verified(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        assert "fk-site-header" in resp.content.decode(), (
            "Portal must include fk-site-header."
        )

    def test_portal_shows_mani_pieteikumi_eyebrow(self):
        """Portal must contain 'Mani pieteikumi' eyebrow."""
        acct = ParentAccount.objects.create(
            email="eyebrowtest@example.com",
            phone="+37133333333",
        )
        client = Client()
        _login_verified(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        assert "Mani pieteikumi" in resp.content.decode()

    def test_portal_shows_parskatiet_heading(self):
        """Portal must contain 'Pārskatiet un turpiniet' heading."""
        acct = ParentAccount.objects.create(
            email="headingtest@example.com",
            phone="+37144444444",
        )
        client = Client()
        _login_verified(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        assert "Pārskatiet un turpiniet" in resp.content.decode()


# ===========================================================================
# Portal with draft — continue primary + start-new always visible
# ===========================================================================


class TestPortalWithDraft:
    """Portal with an editable draft must prioritize continue CTA."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="draftportal@example.com",
            phone="+37155555555",
        )
        self.client = Client()
        _login_verified(self.client, self.acct)

    def _create_draft(self, email="draftportal@example.com", child="DraftPortal Child"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_first_name": "DraftPortal",
                "guardian_family_name": "Guardian",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37166666666",
                "guardian_declared_address": "Riga 5",
                "member_full_name": child,
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-05-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_portal_shows_continue_cta_with_draft(self):
        """Portal must show 'Turpināt pieteikumu' when draft exists."""
        self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Turpināt pieteikumu" in resp.content.decode()

    def test_portal_shows_start_new_with_draft(self):
        """Portal must show 'Sākt jaunu reģistrāciju' when draft exists."""
        self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Sākt jaunu reģistrāciju" in resp.content.decode()

    def test_continue_cta_links_to_workspace(self):
        """Continue CTA must link to /applications/<id>/."""
        app = self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert f"/applications/{app.pk}/" in resp.content.decode()

    def test_portal_shows_draft_status_and_turpat(self):
        """Draft application card must show 'Melnraksts' and 'Turpināt'."""
        self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Melnraksts" in content
        assert "Turpināt" in content


# ===========================================================================
# Portal without draft — start-new primary, empty state
# ===========================================================================


class TestPortalWithoutDraft:
    """Portal without a draft must show start-new as primary and empty state."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="nodraftportal@example.com",
            phone="+37177777777",
        )
        self.client = Client()
        _login_verified(self.client, self.acct)

    def test_portal_shows_start_new_without_draft(self):
        """Portal must show 'Sākt jaunu reģistrāciju' when no draft exists."""
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Sākt jaunu reģistrāciju" in resp.content.decode()

    def test_portal_shows_empty_state_without_draft(self):
        """Portal must show 'Nav pieteikumu' empty state when no applications exist."""
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Nav pieteikumu" in resp.content.decode()

    def test_portal_does_not_show_continue_without_draft(self):
        """Portal must not show 'Turpināt pieteikumu' when no draft exists."""
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        # The hero should not contain the continue CTA text when no draft exists.
        # We check that the primary hero section does not have it.
        assert "Turpināt pieteikumu" not in content, (
            "Portal must not show 'Turpināt pieteikumu' when no draft exists."
        )


# ===========================================================================
# Portal with submitted application — Skatīt CTA
# ===========================================================================


class TestPortalWithSubmittedApplication:
    """Portal with a submitted application must show 'Skatīt' CTA."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="submittedportal@example.com",
            phone="+37188888888",
        )
        self.client = Client()
        _login_verified(self.client, self.acct)

    def _create_submitted(self, email="submittedportal@example.com"):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.members.models import KitSizeOption
        from django.core.files.uploadedfile import SimpleUploadedFile

        shirt, _ = KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHIRT,
            defaults={"label": "S", "is_active": True},
        )
        shorts, _ = KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHORTS,
            defaults={"label": "S", "is_active": True},
        )

        def _make_file(name="id.png"):
            return SimpleUploadedFile(
                name=name,
                content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
                content_type="image/png",
            )

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_first_name": "SubmittedPortal",
                "guardian_family_name": "Guardian",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37199999999",
                "guardian_declared_address": "Riga 8",
                "member_full_name": "SubmittedPortal Child",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-08-01",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": shirt.pk,
                "member_kit_size_shorts": shorts.pk,
            },
            files={
                "guardian_identity_document": _make_file("sub_guardian.png"),
                "member_identity_document": _make_file("sub_member.png"),
                "member_portrait_document": _make_file("sub_portrait.png"),
            },
            verified_account=self.acct,
        )
        submit_application(app, self.acct)
        return app

    def test_submitted_application_shows_skatit_cta(self):
        """Submitted application card must show 'Skatīt pieteikumu'."""
        self._create_submitted()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Skatīt pieteikumu" in resp.content.decode()

    def test_submitted_application_shows_iesniegts_status(self):
        """Submitted application card must show 'Iesniegts' status."""
        self._create_submitted()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Iesniegts" in resp.content.decode()

    def test_portal_shows_start_new_even_with_submitted(self):
        """Portal must still show 'Sākt jaunu reģistrāciju' alongside submitted app."""
        self._create_submitted()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "Sākt jaunu reģistrāciju" in resp.content.decode()


# ===========================================================================
# Portal verified gate — unauthenticated redirect
# ===========================================================================


class TestPortalVerifiedGate:
    """Portal must redirect unauthenticated users to /register/."""

    def test_unauthenticated_portal_redirects_to_register(self):
        """Unauthenticated GET /portal/ must redirect to /register/."""
        client = Client()
        resp = client.get("/portal/", follow=False)
        assert resp.status_code == 302
        assert "/register/" in resp.url

    def test_portal_shows_fk_parent_page_after_verification(self):
        """Verified user must see fk-parent-page shell on portal."""
        from apps.accounts.services import issue_magic_link

        acct = ParentAccount.objects.create(
            email="gateverify@example.com",
            phone="+37100000000",
        )
        client = Client()
        raw = issue_magic_link(acct)
        client.get(f"/accounts/verify/{raw}/")
        resp = client.get("/portal/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode()


# ===========================================================================
# Portal hero — primary_application as top-level CTA
# ===========================================================================


class TestPortalHeroPrimaryCta:
    """Portal hero must use primary_application as top-level primary CTA.

    When an editable application (draft or fix_requested) exists, the hero
    card area must contain a 'Turpināt pieteikumu' CTA linking to the
    application workspace — not only inside the application card list.
    """

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="herocta@example.com",
            phone="+37112345678",
        )
        self.client = Client()
        _login_verified(self.client, self.acct)

    def _create_draft(self):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": "herocta@example.com",
                "guardian_first_name": "HeroCTA",
                "guardian_family_name": "Guardian",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 9",
                "member_full_name": "HeroCTA Child",
                "member_personal_id": "010125-99999",
                "member_birth_date": "2025-09-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_portal_hero_has_continue_cta_when_draft_exists(self):
        """Portal hero card must contain 'Turpināt pieteikumu' CTA when draft exists."""
        self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Turpināt pieteikumu" in content, (
            "Portal hero must show 'Turpināt pieteikumu' CTA when editable application exists."
        )

    def test_portal_hero_continue_cta_links_to_primary_application(self):
        """Portal hero CTA must link to /applications/<id>/ for the primary application."""
        app = self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert f"/applications/{app.pk}/" in content, (
            f"Portal hero CTA must link to /applications/{app.pk}/."
        )

    def test_portal_hero_continue_cta_visible_when_fix_requested_exists(self):
        """Portal hero must show 'Turpināt pieteikumu' when fix_requested application exists."""
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.members.models import KitSizeOption
        from django.core.files.uploadedfile import SimpleUploadedFile

        shirt, _ = KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHIRT,
            defaults={"label": "S", "is_active": True},
        )
        shorts, _ = KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHORTS,
            defaults={"label": "S", "is_active": True},
        )

        def _make_file(name="id.png"):
            return SimpleUploadedFile(
                name=name,
                content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
                content_type="image/png",
            )

        app = create_or_update_draft(
            data={
                "guardian_email": "herocta@example.com",
                "guardian_first_name": "HeroCTA",
                "guardian_family_name": "Guardian",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 9",
                "member_full_name": "HeroCTA Child",
                "member_personal_id": "010125-99999",
                "member_birth_date": "2025-09-01",
                "member_kit_size_shirt": shirt.pk,
                "member_kit_size_shorts": shorts.pk,
            },
            files={
                "guardian_identity_document": _make_file("hero_guardian.png"),
                "member_identity_document": _make_file("hero_member.png"),
                "member_portrait_document": _make_file("hero_portrait.png"),
            },
            verified_account=self.acct,
        )
        submit_application(app, self.acct)
        app.refresh_from_db()
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.save(update_fields=["status"])

        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Turpināt pieteikumu" in content, (
            "Portal hero must show 'Turpināt pieteikumu' CTA when fix_requested application exists."
        )


# ===========================================================================
# Portal status rendering — fix_requested and broader status contract
# ===========================================================================


class TestPortalStatusBadgeRendering:
    """Portal must render status badges for all application statuses.

    The portal must use the status_badge primitive (or equivalent
    consistent rendering) for all statuses, not only draft and submitted.
    """

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="statustest@example.com",
            phone="+37133344455",
        )
        self.client = Client()
        _login_verified(self.client, self.acct)

    def _create_fix_requested(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.members.models import KitSizeOption
        from django.core.files.uploadedfile import SimpleUploadedFile

        shirt, _ = KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHIRT,
            defaults={"label": "M", "is_active": True},
        )
        shorts, _ = KitSizeOption.objects.get_or_create(
            kind=KitSizeOption.Kind.SHORTS,
            defaults={"label": "M", "is_active": True},
        )

        def _make_file(name="id.png"):
            return SimpleUploadedFile(
                name=name,
                content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
                content_type="image/png",
            )

        app = create_or_update_draft(
            data={
                "guardian_email": "statustest@example.com",
                "guardian_first_name": "StatusTest",
                "guardian_family_name": "Guardian",
                "guardian_personal_id": "010101-44444",
                "guardian_phone": "+37144455566",
                "guardian_declared_address": "Riga 4",
                "member_full_name": "StatusTest Child",
                "member_personal_id": "010125-44444",
                "member_birth_date": "2025-04-01",
                "member_kit_size_shirt": shirt.pk,
                "member_kit_size_shorts": shorts.pk,
            },
            files={
                "guardian_identity_document": _make_file("status_guardian.png"),
                "member_identity_document": _make_file("status_member.png"),
                "member_portrait_document": _make_file("status_portrait.png"),
            },
            verified_account=self.acct,
        )
        submit_application(app, self.acct)
        app.refresh_from_db()
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.save(update_fields=["status"])
        return app

    def test_fix_requested_application_shows_jalabo_status(self):
        """fix_requested application card must show 'Jālabo' status text."""
        self._create_fix_requested()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Jālabo" in content, (
            "Portal must show 'Jālabo' status for fix_requested application."
        )

    def test_fix_requested_application_shows_edit_cta(self):
        """fix_requested application card must show a visible edit/continue CTA."""
        self._create_fix_requested()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Turpināt" in content, (
            "Portal must show a continue/edit CTA for fix_requested application."
        )

    def test_fix_requested_application_card_links_to_workspace(self):
        """fix_requested application card must link to the application workspace."""
        app = self._create_fix_requested()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert f"/applications/{app.pk}/" in content, (
            f"Portal must link fix_requested application card to /applications/{app.pk}/."
        )
