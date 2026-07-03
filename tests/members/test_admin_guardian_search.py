"""GuardianAdmin search works after email/phone became account proxies."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from tests.support import make_guardian

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_guardian_search_by_account_email_does_not_error():
    # email is no longer a Guardian column; search_fields must traverse the
    # account, else the changelist 500s with "no such column".
    make_guardian(full_name="Anna Ozola", email="findme@example.com")
    make_guardian(full_name="Cits", email="other@example.com")
    c = _staff_client()
    url = reverse("admin:members_guardian_changelist") + "?q=findme"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Anna Ozola" in body
    assert "Cits" not in body
