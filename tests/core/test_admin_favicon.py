import pytest
from django.contrib.auth.models import User
from django.test import Client

pytestmark = pytest.mark.django_db


def test_admin_index_links_favicon() -> None:
    user = User.objects.create_superuser("favicon", "favicon@example.com", "pw")
    client = Client()
    client.force_login(user)

    resp = client.get("/admin/")

    assert resp.status_code == 200
    content = resp.content.decode()
    assert 'rel="icon"' in content
    assert 'type="image/png"' in content
    assert 'href="/static/img/favicon.png"' in content
