"""Tests for P4 Slice E follow-up — member_same_address_as_guardian
checkbox must not be step-gated."""

import re

import pytest
from django.urls import reverse

from apps.registrations.forms import RegistrationApplicationForm

pytestmark = pytest.mark.django_db


class TestCheckboxIsNotStepGated:
    """The checkbox must not carry data-step-required, because the wizard
    JS treats step-required checkboxes as "must be checked to advance",
    which is wrong for the "addresses are the same" question."""

    def test_form_widget_has_no_data_step_required_attr(self):
        form = RegistrationApplicationForm()
        widget = form.fields["member_same_address_as_guardian"].widget
        assert "data-step-required" not in widget.attrs, (
            "member_same_address_as_guardian must not carry data-step-required"
        )

    def test_form_field_remains_optional(self):
        form = RegistrationApplicationForm()
        assert form.fields["member_same_address_as_guardian"].required is False


@pytest.mark.django_db
class TestWorkspaceRendersCheckboxWithoutStepRequired:
    def _make_draft(self, parent_account):
        from apps.registrations.models import RegistrationApplication

        return RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
        )

    def test_workspace_html_does_not_mark_checkbox_step_required(
        self, verified_client, parent_account
    ):
        app = self._make_draft(parent_account)
        url = reverse("registrations:application-workspace", args=[app.id])
        response = verified_client.get(url)
        assert response.status_code == 200
        html = response.content.decode("utf-8")

        # Locate the checkbox <input>.
        match = re.search(
            r'<input[^>]*\bname="member_same_address_as_guardian"[^>]*>',
            html,
        )
        assert match is not None, "checkbox input must render on the workspace"
        tag = match.group(0)
        assert "data-step-required" not in tag, (
            f"checkbox must not carry data-step-required; got: {tag}"
        )


@pytest.mark.django_db
class TestSubmitWithoutCheckingBoxStillValidates:
    """A submitted draft with the checkbox unchecked must still be a valid
    submission as long as member_actual_address is provided."""

    def test_submit_form_valid_with_unchecked_checkbox(self):
        from apps.registrations.forms import RegistrationApplicationForm

        # Build a complete payload with the checkbox absent (unchecked).
        # Browsers omit unchecked checkboxes from the POST body entirely.
        data = {
            "guardian_full_name": "Anna Bērziņa",
            "guardian_personal_id": "010101-10001",
            "guardian_email": "anna@example.com",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Rīga, Brīvības 1",
            "member_full_name": "Jānis Bērziņš",
            "member_personal_id": "010125-10001",
            "member_birth_date": "2015-01-01",
            "member_actual_address": "Rīga, Brīvības 1",
            # member_same_address_as_guardian intentionally omitted.
            "member_kit_size_shirt": 1,
            "member_kit_size_shorts": 1,
            "preferred_agreement_signing": "in_person",
            "personal_data_consent": "on",
        }
        form = RegistrationApplicationForm(
            data=data, is_submit=True, has_existing_document=True
        )
        # We are not asserting full form.is_valid() because kit-size IDs
        # need to exist in the DB. The point of this test is narrower:
        # the unchecked checkbox must NOT contribute an error for
        # `member_same_address_as_guardian`.
        form.is_valid()  # populates form.errors
        assert "member_same_address_as_guardian" not in form.errors, (
            f"unchecked checkbox produced an error: {form.errors}"
        )
