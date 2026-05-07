"""Visual system and parent registration redesign — RED tests.

Covers acceptance criteria from the approved 2026-05-05 design spec.

Strategy:
- Assert exact CSS hook class names and Latvian text content.
- Do not assert exact DOM nesting or element depth.
- Tests target new UI structure introduced by the redesign.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY  # noqa: F401
from apps.accounts.services import issue_magic_link

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_via_magic_link(client, account):
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_child_identity_file(name="id.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _create_and_login(email="visualex@example.com"):
    """Create a ParentAccount, log in, return (client, account)."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37111111111",
    )
    client = Client()
    _login_via_magic_link(client, acct)
    return client, acct


# ---------------------------------------------------------------------------
# AC1 — Register page renders fk-parent-shell and stylesheet references
# ---------------------------------------------------------------------------


class TestRegisterPageParentShell:
    """The register page should include parent-shell structure and CSS links."""

    def test_register_page_has_fk_parent_shell_wrapper(self):
        """Register page must contain the 'fk-parent-shell' CSS hook."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "fk-parent-shell" in resp.content.decode()

    def test_register_page_links_tokens_css(self):
        """Register page must link tokens.css."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "tokens.css" in resp.content.decode()

    def test_register_page_links_parent_css(self):
        """Register page must link parent.css."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "parent.css" in resp.content.decode()


# ---------------------------------------------------------------------------
# AC2 — Register page includes hero-logo and branded copy
# ---------------------------------------------------------------------------


class TestRegisterPageHeroLogoAndCopy:
    """The register page should display FK Cēsis branding."""

    def test_register_page_has_fk_logo_hero(self):
        """Register page must contain the 'fk-logo--hero' CSS hook."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "fk-logo--hero" in resp.content.decode()

    def test_register_page_has_fk_cesis_branding(self):
        """Register page must contain 'FK Cēsis' branding text."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "FK Cēsis" in resp.content.decode()

    def test_register_page_has_bernas_registracija_heading(self):
        """Register page must contain 'Bērna reģistrācija' heading."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "Bērna reģistrācija" in resp.content.decode()

    def test_register_page_has_save_draft_later_copy(self):
        """Register page must contain 'Saglabāt melnrakstu vēlāk' copy."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "Saglabāt melnrakstu vēlāk" in resp.content.decode()


# ---------------------------------------------------------------------------
# AC3 — Register page includes primary/secondary action hooks
# ---------------------------------------------------------------------------


class TestRegisterPageActionHooks:
    """The register page should present primary and secondary action buttons."""

    def test_register_page_has_primary_button_hook(self):
        """Register page must contain 'fk-button fk-button--primary'."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "fk-button fk-button--primary" in resp.content.decode()

    def test_register_page_has_secondary_button_hook(self):
        """Register page must contain 'fk-button fk-button--secondary'."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "fk-button fk-button--secondary" in resp.content.decode()


# ---------------------------------------------------------------------------
# AC4 — Parent portal renders fk-status-card and child name
# ---------------------------------------------------------------------------


class TestParentPortalStatusCard:
    """The parent portal should render fk-status-card structure."""

    def setup_method(self):
        self.client, self.acct = _create_and_login("portalcard@example.com")

    def _create_draft(self, email="portalcard@example.com", child_name="Card Child"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Card Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": child_name,
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_portal_has_fk_status_card(self):
        """Portal must contain 'fk-status-card' CSS hook."""
        self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "fk-status-card" in resp.content.decode()

    def test_portal_status_card_shows_child_name(self):
        """Status card must render the application child name."""
        self._create_draft(child_name="StatusCard Child")
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        assert "StatusCard Child" in resp.content.decode()


# ---------------------------------------------------------------------------
# AC5 — Edit page includes grouped section headings and action labels
# ---------------------------------------------------------------------------


class TestEditPageSectionHeadings:
    """The edit page should show grouped section headings and action labels."""

    def setup_method(self):
        self.client, self.acct = _create_and_login("sections@example.com")

    def _create_draft(self, email="sections@example.com"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Sections Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": "Sections Child",
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_edit_page_has_vecaka_informacija_heading(self):
        """Edit page must contain 'Vecāka informācija' section heading."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Vecāka informācija" in resp.content.decode()

    def test_edit_page_has_berna_informacija_heading(self):
        """Edit page must contain 'Bērna informācija' section heading."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Bērna informācija" in resp.content.decode()

    def test_edit_page_has_dokuments_heading(self):
        """Edit page must contain 'Dokuments' section heading."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Dokuments" in resp.content.decode()

    def test_edit_page_has_save_draft_button_label(self):
        """Edit page must contain 'Saglabāt melnrakstu' button label."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Saglabāt melnrakstu" in resp.content.decode()

    def test_edit_page_has_submit_button_label(self):
        """Edit page must contain 'Iesniegt pieteikumu' button label."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Iesniegt pieteikumu" in resp.content.decode()


# ---------------------------------------------------------------------------
# AC6 — Invalid submit shows top-level error summary text
# ---------------------------------------------------------------------------


class TestInvalidSubmitErrorSummary:
    """Invalid form submission should show top-level error summary."""

    def setup_method(self):
        self.client, self.acct = _create_and_login("errors@example.com")

    def _create_draft(self, email="errors@example.com"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Error Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": "Error Child",
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id.jpg"),
            },
            verified_account=self.acct,
        )

    def test_invalid_submit_returns_400(self):
        """Submitting with empty required fields should return HTTP 400."""
        app = self._create_draft()
        resp = self.client.post(
            f"/applications/{app.pk}/submit/",
            data={
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_email": "",
                "guardian_phone": "",
                "guardian_address": "",
                "child_full_name": "",
                "child_personal_id": "",
                "child_birth_date": "",
            },
        )
        assert resp.status_code == 400

    def test_invalid_submit_has_error_summary_text(self):
        """Invalid submit page must contain 'Lūdzu pārbaudiet laukus zemāk'."""
        app = self._create_draft()
        resp = self.client.post(
            f"/applications/{app.pk}/submit/",
            data={
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_email": "",
                "guardian_phone": "",
                "guardian_address": "",
                "child_full_name": "",
                "child_personal_id": "",
                "child_birth_date": "",
            },
        )
        assert resp.status_code == 400
        assert "Lūdzu pārbaudiet laukus zemāk" in resp.content.decode()


# ---------------------------------------------------------------------------
# UAT Bug 1 — Static asset paths must be absolute (/static/…) in rendered HTML
# ---------------------------------------------------------------------------


class TestStaticAssetAbsolutePaths:
    """Register page must reference static assets with absolute /static/ paths.

    UAT root cause: LAN UAT gets 404 for static assets because relative paths
    (e.g. static/css/tokens.css) were rendered instead of absolute
    (/static/css/tokens.css).
    """

    def test_register_page_has_absolute_tokens_css_path(self):
        """Register page HTML must contain href='/static/css/tokens.css'."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert 'href="/static/css/tokens.css"' in resp.content.decode()

    def test_register_page_has_absolute_parent_css_path(self):
        """Register page HTML must contain href='/static/css/parent.css'."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert 'href="/static/css/parent.css"' in resp.content.decode()

    def test_register_page_has_absolute_admin_shell_css_path(self):
        """Register page HTML must contain href='/static/css/admin_shell.css'."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert 'href="/static/css/admin_shell.css"' in resp.content.decode()

    def test_register_page_has_absolute_logo_path(self):
        """Register page HTML must contain src='/static/img/fk-cesis-logo.png'."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert 'src="/static/img/fk-cesis-logo.png"' in resp.content.decode()

    def test_logo_asset_file_exists_in_static_repo(self):
        """The logo file must exist at static/img/fk-cesis-logo.png in the repo."""
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        logo_path = repo_root / "static" / "img" / "fk-cesis-logo.png"
        assert logo_path.is_file(), (
            f"Logo file not found at {logo_path}. "
            "Static file must exist for {% static %} to serve it."
        )


# ---------------------------------------------------------------------------
# UAT Bug 2 — Registration form labels must be in Latvian, not English
# ---------------------------------------------------------------------------


class TestEditPageLatvianFieldLabels:
    """Edit page must show Latvian field labels, not English ones.

    UAT root cause: Django form fields have no explicit label=, so Django
    auto-generates English labels from field names (e.g. 'Guardian full name').
    """

    def setup_method(self):
        self.client, self.acct = _create_and_login("labels@example.com")

    def _create_draft(self, email="labels@example.com"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Labels Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": "Labels Child",
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_edit_page_has_vecaka_vards_unzvards_label(self):
        """Edit page must contain Latvian label 'Vecāka vārds, uzvārds'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Vecāka vārds, uzvārds" in resp.content.decode()

    def test_edit_page_has_vecaka_personas_kods_label(self):
        """Edit page must contain Latvian label 'Vecāka personas kods'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Vecāka personas kods" in resp.content.decode()

    def test_edit_page_has_epasts_label(self):
        """Edit page must contain Latvian label 'E-pasts'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "E-pasts" in resp.content.decode()

    def test_edit_page_has_talrunis_label(self):
        """Edit page must contain Latvian label 'Tālrunis'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Tālrunis" in resp.content.decode()

    def test_edit_page_has_adrese_label(self):
        """Edit page must contain Latvian label 'Adrese'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Adrese" in resp.content.decode()

    def test_edit_page_has_berna_vards_unzvards_label(self):
        """Edit page must contain Latvian label 'Bērna vārds, uzvārds'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Bērna vārds, uzvārds" in resp.content.decode()

    def test_edit_page_has_berna_personas_kods_label(self):
        """Edit page must contain Latvian label 'Bērna personas kods'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Bērna personas kods" in resp.content.decode()

    def test_edit_page_has_berna_dzimšanas_datums_label(self):
        """Edit page must contain Latvian label 'Bērna dzimšanas datums'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Bērna dzimšanas datums" in resp.content.decode()

    def test_edit_page_has_berna_dokuments_label(self):
        """Edit page must contain Latvian label 'Bērna personu apliecinošs dokuments'."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Bērna personu apliecinošs dokuments" in resp.content.decode()


class TestEditPageNoEnglishLabels:
    """Edit page must NOT contain English auto-generated field labels.

    If a label is missing, Django falls back to the field-name-based English
    default (e.g. 'Guardian full name'). These must not appear.
    """

    def setup_method(self):
        self.client, self.acct = _create_and_login("noeng@example.com")

    def _create_draft(self, email="noeng@example.com"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "NoEng Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": "NoEng Child",
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_edit_page_has_no_english_guardian_full_name_label(self):
        """Edit page must not contain English 'Guardian full name' label."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Guardian full name" not in resp.content.decode()

    def test_edit_page_has_no_english_guardian_email_label(self):
        """Edit page must not contain English 'Guardian email' label."""
        app = self._create_draft()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200
        assert "Guardian email" not in resp.content.decode()


# ---------------------------------------------------------------------------
# UAT Bug 2 — Application status display must be in Latvian
# ---------------------------------------------------------------------------


class TestPortalStatusDisplayLatvian:
    """Parent portal application status must display in Latvian, not English.

    UAT root cause: RegistrationApplication.Status TextChoices use English
    strings ('Draft', 'Submitted', etc.) as the human-readable display values.
    """

    def setup_method(self):
        self.client, self.acct = _create_and_login("statuslv@example.com")

    def _create_draft(self, email="statuslv@example.com"):
        from apps.registrations.services import create_or_update_draft

        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Status Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": "Status Child",
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_draft_status_shows_melnraksts_not_draft(self):
        """Draft application portal page must show 'Melnraksts', not 'Draft'."""
        app = self._create_draft()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Melnraksts" in content, (
            "Draft status must display as 'Melnraksts' in Latvian, "
            "not 'Draft' in English."
        )
        assert "Draft" not in content, (
            "English 'Draft' text must not appear in portal status display."
        )

    def test_status_field_text_choices_are_latvian(self):
        """All RegistrationApplication.Status text choices must be Latvian."""
        from apps.registrations.models import RegistrationApplication

        expected = {
            "draft": "Melnraksts",
            "submitted": "Iesniegts",
            "fix_requested": "Jālabo",
            "approved": "Apstiprināts",
            "rejected": "Noraidīts",
        }
        actual = dict(RegistrationApplication.Status.choices)
        for code, expected_label in expected.items():
            assert code in actual, f"Missing status code '{code}' in RegistrationApplication.Status."
            assert actual[code] == expected_label, (
                f"Status '{code}' label is '{actual[code]}', expected '{expected_label}'."
            )


# ---------------------------------------------------------------------------
# AC7 — Submitted application portal card shows 'Skatīt pieteikumu', not 'Turpināt'
# ---------------------------------------------------------------------------


class TestSubmittedApplicationPortalCard:
    """Submitted applications must show 'Skatīt pieteikumu' link, not 'Turpināt'."""

    def setup_method(self):
        self.client, self.acct = _create_and_login("submittedportal@example.com")

    def _create_submitted_application(self, email="submittedportal@example.com"):
        from apps.registrations.services import create_or_update_draft, submit_application

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Submitted Portal Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 1",
                "child_full_name": "Submitted Portal Child",
                "child_personal_id": "010125-12345",
                "child_birth_date": "2025-01-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("submitted_id.png"),
            },
            verified_account=self.acct,
        )
        submit_application(app, self.acct)
        return app

    def test_submitted_application_card_shows_skatit_ieteikumu(self):
        """Submitted application portal card must contain 'Skatīt pieteikumu' link text."""
        self._create_submitted_application()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Skatīt pieteikumu" in content, (
            "Submitted application portal card must show 'Skatīt pieteikumu' link."
        )

    def test_submitted_application_card_does_not_show_turpat(self):
        """Submitted application portal card must NOT contain 'Turpināt' link text."""
        self._create_submitted_application()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Turpināt" not in content, (
            "Submitted application portal card must not show 'Turpināt' link."
        )

    def test_draft_application_card_still_shows_turpat(self):
        """Draft application portal card must still show 'Turpināt' link text."""
        # First create a submitted application (already done by setup)
        # Then create a separate draft for the same account
        from apps.registrations.services import create_or_update_draft

        draft_app = create_or_update_draft(
            data={
                "guardian_email": "submittedportal@example.com",
                "guardian_full_name": "Draft Portal Guardian",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga 2",
                "child_full_name": "Draft Portal Child",
                "child_personal_id": "010125-99999",
                "child_birth_date": "2025-06-01",
            },
            files={},
            verified_account=self.acct,
        )
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Turpināt" in content, (
            "Draft application portal card must show 'Turpināt' link."
        )


# ---------------------------------------------------------------------------
# AC8 — Parent can open submitted application summary view
# ---------------------------------------------------------------------------


class TestSubmittedApplicationSummaryView:
    """Parent should be able to open a read-only summary view for a submitted application."""

    def setup_method(self):
        self.client, self.acct = _create_and_login("summary@example.com")

    def _create_submitted_application(self, email="summary@example.com"):
        from apps.registrations.services import create_or_update_draft, submit_application

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Summary Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37121212121",
                "guardian_address": "Riga 10",
                "child_full_name": "Summary Child",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-02-15",
            },
            files={
                "child_identity_document": _make_child_identity_file("summary_id.png"),
            },
            verified_account=self.acct,
        )
        submit_application(app, self.acct)
        return app

    def test_summary_route_returns_200(self):
        """GET /applications/<id>/summary/ should return HTTP 200 for owner."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/summary/")
        assert resp.status_code == 200

    def test_summary_shows_child_name(self):
        """Summary page must display the child's full name."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/summary/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Summary Child" in content, (
            "Summary page must display child full name."
        )

    def test_summary_shows_guardian_name(self):
        """Summary page must display the guardian's full name."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/summary/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Summary Guardian" in content, (
            "Summary page must display guardian full name."
        )

    def test_summary_shows_latvian_status_text(self):
        """Summary page must display the status in Latvian."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/summary/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Iesniegts" in content, (
            "Summary page must display status as 'Iesniegts' in Latvian."
        )

    def test_summary_includes_link_to_detail_view(self):
        """Summary page must include a link to the full read-only detail view."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/summary/")
        assert resp.status_code == 200
        content = resp.content.decode()
        # Link should point to the detail route for this application
        assert f"/applications/{app.pk}/detail/" in content, (
            "Summary page must include a link to the detail view."
        )


# ---------------------------------------------------------------------------
# AC9 — Parent can open submitted application detail view
# ---------------------------------------------------------------------------


class TestSubmittedApplicationDetailView:
    """Parent should be able to open a fuller read-only detail view for a submitted application."""

    def setup_method(self):
        self.client, self.acct = _create_and_login("detail@example.com")

    def _create_submitted_application(self, email="detail@example.com"):
        from apps.registrations.services import create_or_update_draft, submit_application

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Detail Guardian",
                "guardian_personal_id": "010101-22222",
                "guardian_phone": "+37123232323",
                "guardian_address": "Riga 20",
                "child_full_name": "Detail Child",
                "child_personal_id": "010125-22222",
                "child_birth_date": "2025-03-20",
            },
            files={
                "child_identity_document": _make_child_identity_file("detail_id.png"),
            },
            verified_account=self.acct,
        )
        submit_application(app, self.acct)
        return app

    def test_detail_route_returns_200(self):
        """GET /applications/<id>/detail/ should return HTTP 200 for owner."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200

    def test_detail_shows_guardian_full_name(self):
        """Detail page must display guardian full name."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Detail Guardian" in content

    def test_detail_shows_guardian_personal_id(self):
        """Detail page must display guardian personal ID."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "010101-22222" in content

    def test_detail_shows_guardian_email(self):
        """Detail page must display guardian email."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "detail@example.com" in content

    def test_detail_shows_guardian_phone(self):
        """Detail page must display guardian phone."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "+37123232323" in content

    def test_detail_shows_guardian_address(self):
        """Detail page must display guardian address."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Riga 20" in content

    def test_detail_shows_child_full_name(self):
        """Detail page must display child full name."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Detail Child" in content

    def test_detail_shows_child_personal_id(self):
        """Detail page must display child personal ID."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "010125-22222" in content

    def test_detail_shows_child_birth_date(self):
        """Detail page must display child birth date."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "2025-03-20" in content

    def test_detail_is_read_only_no_edit_fields(self):
        """Detail page must not contain editable form inputs."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 200
        content = resp.content.decode()
        # Read-only detail should not have <input type="text">, <input type="email">, etc.
        assert 'type="text"' not in content, (
            "Detail page must not contain editable text inputs."
        )
        assert 'type="email"' not in content, (
            "Detail page must not contain editable email inputs."
        )
        assert 'type="date"' not in content, (
            "Detail page must not contain editable date inputs."
        )


# ---------------------------------------------------------------------------
# AC10 — Other parent cannot view another parent's submitted application
# ---------------------------------------------------------------------------


class TestOtherParentCannotViewSubmittedApplication:
    """A parent must not be able to view another parent's submitted application."""

    def setup_method(self):
        self.client = Client()

    def _create_submitted_application(self, email="victim@example.com"):
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = ParentAccount.objects.create(
            email=email,
            phone="+37144444444",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Victim Guardian",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37155555555",
                "guardian_address": "Riga 30",
                "child_full_name": "Victim Child",
                "child_personal_id": "010125-33333",
                "child_birth_date": "2025-04-10",
            },
            files={
                "child_identity_document": _make_child_identity_file("victim_id.png"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        return acct, app

    def test_other_parent_cannot_view_summary(self):
        """Other parent GET /applications/<id>/summary/ must return 404."""
        acct, app = self._create_submitted_application()
        # Login as a different parent
        other = ParentAccount.objects.create(
            email="other@example.com",
            phone="+37166666666",
        )
        _login_via_magic_link(self.client, other)
        resp = self.client.get(f"/applications/{app.pk}/summary/")
        assert resp.status_code == 404

    def test_other_parent_cannot_view_detail(self):
        """Other parent GET /applications/<id>/detail/ must return 404."""
        acct, app = self._create_submitted_application()
        other = ParentAccount.objects.create(
            email="other2@example.com",
            phone="+37177777777",
        )
        _login_via_magic_link(self.client, other)
        resp = self.client.get(f"/applications/{app.pk}/detail/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC11 — Owner still cannot edit submitted application
# ---------------------------------------------------------------------------


class TestOwnerCannotEditSubmittedApplication:
    """Owner must get 404 on edit page after submission."""

    def setup_method(self):
        self.client = Client()

    def _create_submitted_application(self, email="noedit@example.com"):
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37188888888",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft, submit_application

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "No Edit Guardian",
                "guardian_personal_id": "010101-44444",
                "guardian_phone": "+37199999999",
                "guardian_address": "Riga 40",
                "child_full_name": "No Edit Child",
                "child_personal_id": "010125-44444",
                "child_birth_date": "2025-05-05",
            },
            files={
                "child_identity_document": _make_child_identity_file("noedit_id.png"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        return app

    def test_owner_gets_404_on_edit_after_submit(self):
        """Owner GET /applications/<id>/edit/ after submit must return 404."""
        app = self._create_submitted_application()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404
