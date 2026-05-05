"""Task 5 — Registration views: start, edit, submit, portal. RED tests.

Covers:
- Owner can open draft edit page.
- Other parent cannot open draft edit page.
- Submitted application is not editable by owner.
- Portal lists only current parent applications.
- Start page works without existing session.
- Resumed parent can continue own draft.
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
    """Convenience: issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_child_identity_file(name="id.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _submit_form_data(email):
    """Build POST data matching a draft created with the given email."""
    return {
        "guardian_full_name": "Submit Guardian",
        "guardian_personal_id": "010101-12345",
        "guardian_email": email,
        "guardian_phone": "+37120000000",
        "guardian_address": "Riga, Brivibas 1",
        "child_full_name": "Submit Child",
        "child_personal_id": "010125-67890",
        "child_birth_date": "2025-01-01",
    }


# ---------------------------------------------------------------------------
# View: start_registration — /register/
# ---------------------------------------------------------------------------

class TestStartRegistrationView:
    """Start page should be accessible without login."""

    def test_start_page_accessible_without_session(self):
        client = Client()
        resp = client.get("/register/")
        assert resp.status_code == 200

    def test_start_page_accessible_without_login(self):
        """Even if no ParentAccount exists, the page loads."""
        client = Client()
        resp = client.get("/register/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# View: edit_registration — /applications/<id>/edit/
# ---------------------------------------------------------------------------

class TestEditRegistrationView:
    """Edit page should enforce ownership and draft status."""

    def setup_method(self):
        self.client = Client()

    def _create_draft_with_owner(self, email="edit@example.com"):
        """Helper: create a ParentAccount, log in, create a draft app."""
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Edit Owner",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child Edit",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={},
        )
        return acct, app

    def test_owner_can_open_draft_edit_page(self):
        acct, app = self._create_draft_with_owner("ownedit@example.com")
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

    def test_other_parent_cannot_open_draft_edit_page(self):
        """A different logged-in parent gets blocked."""
        self._create_draft_with_owner("ownedit2@example.com")
        # Create and login a different parent
        other = ParentAccount.objects.create(
            email="otheredit@example.com",
            phone="+37133333333",
        )
        _login_via_magic_link(self.client, other)
        from apps.registrations.models import RegistrationApplication

        app = RegistrationApplication.objects.first()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404

    def test_submitted_application_not_editable_by_owner(self):
        """Once submitted, owner cannot edit."""
        acct, app = self._create_draft_with_owner("subedit@example.com")
        from apps.registrations.services import submit_application

        # Attach a child identity document so submit can succeed
        from django.core.files.uploadedfile import SimpleUploadedFile

        app.documents.create(
            kind="child_identity",
            file=SimpleUploadedFile("id.jpg", b"fake", content_type="image/jpeg"),
            original_filename="id.jpg",
            content_type="image/jpeg",
            file_size=5,
        )
        submit_application(app, acct)
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# View: submit_registration — /applications/<id>/submit/
# ---------------------------------------------------------------------------

class TestSubmitRegistrationView:
    """Submit view should enforce ownership and required document."""

    def setup_method(self):
        self.client = Client()

    def _create_draft_with_doc_and_login(self, email="subview@example.com"):
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37144444444",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Submit View",
                "guardian_personal_id": "010101-44444",
                "guardian_phone": "+37155555555",
                "guardian_address": "Riga 5",
                "child_full_name": "Child SubView",
                "child_personal_id": "010125-44444",
                "child_birth_date": "2025-02-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("subview_id.jpg"),
            },
        )
        return acct, app

    def test_owner_can_submit_with_document(self):
        acct, app = self._create_draft_with_doc_and_login("owndocsubmit@example.com")
        resp = self.client.post(
            f"/applications/{app.pk}/submit/",
            data=_submit_form_data("owndocsubmit@example.com"),
        )
        # Successful submit redirects to parent portal
        assert resp.status_code == 302
        # Verify status changed
        app.refresh_from_db()
        assert app.status == "submitted"

    def test_owner_cannot_submit_without_document(self):
        acct = ParentAccount.objects.create(
            email="nosubmit@example.com",
            phone="+37166666666",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "nosubmit@example.com",
                "guardian_full_name": "No Submit",
                "guardian_personal_id": "010101-66666",
                "guardian_phone": "+37177777777",
                "guardian_address": "Riga 7",
                "child_full_name": "Child NoSub",
                "child_personal_id": "010125-66666",
                "child_birth_date": "2025-03-01",
            },
            files={},
        )
        resp = self.client.post(
            f"/applications/{app.pk}/submit/",
            data=_submit_form_data("nosubmit@example.com"),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# View: parent_portal — /portal/
# ---------------------------------------------------------------------------

class TestParentPortalView:
    """Portal should list only the current parent's applications."""

    def setup_method(self):
        self.client = Client()

    def test_portal_lists_only_current_parent_applications(self):
        """Two parents, two apps — each portal shows only own."""
        # Parent A
        acct_a = ParentAccount.objects.create(
            email="portalA@example.com",
            phone="+37188888888",
        )
        _login_via_magic_link(self.client, acct_a)
        from apps.registrations.services import create_or_update_draft

        create_or_update_draft(
            data={
                "guardian_email": "portalA@example.com",
                "guardian_full_name": "Parent A",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37199999999",
                "guardian_address": "Riga 88",
                "child_full_name": "Child A",
                "child_personal_id": "010125-88888",
                "child_birth_date": "2025-04-01",
            },
            files={},
        )

        # Parent B
        acct_b = ParentAccount.objects.create(
            email="portalB@example.com",
            phone="+37100000000",
        )
        _login_via_magic_link(self.client, acct_b)
        create_or_update_draft(
            data={
                "guardian_email": "portalB@example.com",
                "guardian_full_name": "Parent B",
                "guardian_personal_id": "010101-00000",
                "guardian_phone": "+37112121212",
                "guardian_address": "Riga 99",
                "child_full_name": "Child B",
                "child_personal_id": "010125-00000",
                "child_birth_date": "2025-05-01",
            },
            files={},
        )

        # Re-login as A and check portal
        _login_via_magic_link(self.client, acct_a)
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Parent A" in content or "portalA" in content
        assert "Parent B" not in content and "portalB" not in content

    def test_portal_redirects_anonymous(self):
        client = Client()
        resp = client.get("/portal/")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Resumed parent — continue own draft after magic-link login
# ---------------------------------------------------------------------------

class TestResumedParentCanContinueDraft:
    """After magic-link login, parent should see and continue their draft."""

    def test_resumed_parent_can_continue_own_draft(self):
        """Parent creates draft without login, then logs in via magic link and continues."""
        # Step 1: Create draft without login (anonymous)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "resume@example.com",
                "guardian_full_name": "Resume Parent",
                "guardian_personal_id": "010101-21212",
                "guardian_phone": "+37132323232",
                "guardian_address": "Riga 21",
                "child_full_name": "Child Resume",
                "child_personal_id": "010125-21212",
                "child_birth_date": "2025-06-01",
            },
            files={},
        )

        # Step 2: Login via magic link
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.get(email="resume@example.com")
        client = Client()
        _login_via_magic_link(client, acct)

        # Step 3: Open edit page — should work
        resp = client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

    def test_resumed_parent_cannot_edit_other_parent_draft(self):
        """Resumed parent should NOT be able to edit someone else's draft."""
        from apps.registrations.services import create_or_update_draft

        # Parent A creates draft
        app_a = create_or_update_draft(
            data={
                "guardian_email": "otherdraft@example.com",
                "guardian_full_name": "Other Draft",
                "guardian_personal_id": "010101-31313",
                "guardian_phone": "+37142424242",
                "guardian_address": "Riga 31",
                "child_full_name": "Child Other",
                "child_personal_id": "010125-31313",
                "child_birth_date": "2025-07-01",
            },
            files={},
        )

        # Parent B logs in
        acct_b = ParentAccount.objects.create(
            email="blogin@example.com",
            phone="+37152525252",
        )
        client = Client()
        _login_via_magic_link(client, acct_b)

        # Parent B tries to edit Parent A's draft
        resp = client.get(f"/applications/{app_a.pk}/edit/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: edit page must not duplicate form fields
# ---------------------------------------------------------------------------

class TestEditPageNoDuplicateFields:
    """Bug: edit_registration.html renders the form twice (once for save, once for submit).

    Desired behavior: one single set of fields with two buttons on the page.
    """

    def setup_method(self):
        self.client = Client()

    def _create_draft_with_owner(self, email="edit@example.com"):
        """Helper: create a ParentAccount, log in, create a draft app."""
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Edit Owner",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child Edit",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={},
        )
        return acct, app

    def test_edit_page_has_single_form_fields(self):
        """Form field 'guardian_email' should appear exactly once in the HTML.

        The template currently renders {{ form.as_p }} inside two separate
        <form> blocks, so every field name appears twice. This test catches
        that duplication.
        """
        acct, app = self._create_draft_with_owner("nodup@example.com")
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

        content = resp.content.decode()
        # Count how many times the field name appears as an HTML attribute.
        # Using 'name="guardian_email"' is stable — it is the form field name
        # from RegistrationApplicationForm, unlikely to change.
        count = content.count('name="guardian_email"')
        assert count == 1, (
            f"Expected 1 occurrence of name=\"guardian_email\" in edit page HTML, "
            f"found {count}. Form fields appear duplicated."
        )

    def test_edit_page_has_save_draft_button(self):
        """The edit page must contain a save-draft button."""
        acct, app = self._create_draft_with_owner("btnsd@example.com")
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert "Saglabāt melnrakstu" in content, (
            "Save draft button label 'Saglabāt melnrakstu' not found on edit page."
        )

    def test_edit_page_has_submit_button(self):
        """The edit page must contain a submit-application button."""
        acct, app = self._create_draft_with_owner("btnsub@example.com")
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert "Iesniegt pieteikumu" in content, (
            "Submit button label 'Iesniegt pieteikumu' not found on edit page."
        )


# ---------------------------------------------------------------------------
# Regression: child birth date uses native browser date picker
# ---------------------------------------------------------------------------

class TestChildBirthDateNativeDatePicker:
    """Approved change: child birth date field should use native browser date picker.

    - Backend stays as Django DateField.
    - Input renders with type="date" for the native picker.
    - No custom parsing, no JS library.
    """

    def _get_start_page(self):
        """Return the start page HTML."""
        client = Client()
        resp = client.get("/register/")
        assert resp.status_code == 200
        return resp.content.decode()

    def test_start_page_has_child_birth_date_field(self):
        """The start page should render a form field named child_birth_date."""
        content = self._get_start_page()
        assert 'name="child_birth_date"' in content, (
            "child_birth_date field not found on start page."
        )

    def test_start_page_child_birth_date_is_native_date_picker(self):
        """The child_birth_date input must have type='date' for native browser picker."""
        content = self._get_start_page()
        # The field should render as <input type="date" name="child_birth_date"
        # or equivalent — check both type and name appear near each other.
        assert 'type="date"' in content and 'name="child_birth_date"' in content, (
            "child_birth_date input does not use type='date'. "
            "Expected native browser date picker."
        )

    def test_edit_page_child_birth_date_is_native_date_picker(self):
        """The edit page should also render child_birth_date as type='date'."""
        client = Client()
        acct = ParentAccount.objects.create(
            email="dateedit@example.com",
            phone="+37111111111",
        )
        _login_via_magic_link(client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "dateedit@example.com",
                "guardian_full_name": "Date Edit",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child Date",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={},
        )
        resp = client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert 'type="date"' in content and 'name="child_birth_date"' in content, (
            "child_birth_date input on edit page does not use type='date'."
        )

    def test_start_page_no_birth_date_hint_text(self):
        """The start page must NOT show the conflicting date-format hint.

        Approved change: keep native date picker, remove help text
        'DD.MM.GGGG vai izvēlieties no kalendāra.' from child_birth_date field.
        """
        content = self._get_start_page()
        assert "DD.MM.GGGG" not in content, (
            "Conflicting hint text 'DD.MM.GGGG vai izvēlieties no kalendāra.' "
            "still rendered on start page. Help text should be removed."
        )
