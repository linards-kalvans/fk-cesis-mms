"""``signed_artifact_upload_view`` must honour a validated ``next`` the same
way Task 5 fixed ``review_action_view``'s actions.

The Hub's agreement page (Task 6) posts the signed-artifact upload form with
a ``next`` set to the page it came from. Before this fix every one of this
view's four returns called ``self._change_redirect(object_id)``
unconditionally, so a successful (or failed) upload always bounced the
reviewer into Django admin instead of back to the Hub.

Every branch's existing no-``next`` destination (the change page) must be
unchanged — that is also exercised by
``tests/registrations/test_signed_artifact_admin.py::
test_upload_rejects_get_and_redirects_to_change_page`` for the non-POST
branch, and by ``test_upload_without_next_still_lands_on_the_change_page``
below for the success branch.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.agreements.services import get_current_agreement

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]

HUB_URL = "/hub/pieteikumi/"


def _upload_url(application, agreement):
    return reverse(
        "admin:registrations_registrationapplication_signed_artifact_upload",
        args=[application.pk, agreement.pk],
    )


def _change_url(application):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[application.pk]
    )


def _file():
    return SimpleUploadedFile(
        "signed.pdf", b"%PDF-1.7", content_type="application/pdf"
    )


def test_upload_returns_to_a_safe_next(staff_client, approved_application):
    agreement = get_current_agreement(approved_application.approved_member)
    url = _upload_url(approved_application, agreement)
    resp = staff_client.post(f"{url}?next={HUB_URL}", {"signed_artifact": _file()})
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_upload_without_next_still_lands_on_the_change_page(
    staff_client, approved_application
):
    agreement = get_current_agreement(approved_application.approved_member)
    url = _upload_url(approved_application, agreement)
    resp = staff_client.post(url, {"signed_artifact": _file()})
    assert resp.status_code == 302
    assert resp["Location"] == _change_url(approved_application)


def test_upload_ignores_an_offsite_next(staff_client, approved_application):
    agreement = get_current_agreement(approved_application.approved_member)
    url = _upload_url(approved_application, agreement)
    resp = staff_client.post(
        f"{url}?next=https://evil.example.com/", {"signed_artifact": _file()}
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp["Location"]
    assert resp["Location"] == _change_url(approved_application)


def test_upload_error_path_also_returns_to_a_safe_next(
    staff_client, approved_application
):
    """No file chosen is the cheapest error branch to exercise; it shares
    the same ``_after_review_redirect`` call as the success path, so this
    guards against a fix that only patches the happy path."""
    agreement = get_current_agreement(approved_application.approved_member)
    url = _upload_url(approved_application, agreement)
    resp = staff_client.post(f"{url}?next={HUB_URL}", {})
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL
