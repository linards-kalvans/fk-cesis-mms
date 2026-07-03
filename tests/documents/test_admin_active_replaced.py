"""Active-vs-replaced badge + search/filter on the documents admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _doc(app, **kw):
    return Document.objects.create(
        application=app, kind=Document.Kind.MEMBER_IDENTITY, **kw
    )


def test_active_doc_shows_active_badge():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    _doc(app)
    c = _staff_client()
    # tbody only — "Aktīvs" also appears as a filter-sidebar label.
    body = c.get(reverse("admin:documents_document_changelist")).content.decode().split("</thead>")[-1]
    assert "fk-badge--ok" in body
    assert "Aktīvs" in body


def test_replaced_doc_shows_muted_badge():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    _doc(app, deleted_at=timezone.now())
    c = _staff_client()
    # tbody only — "Vēsturisks" also appears as a filter-sidebar label.
    body = c.get(reverse("admin:documents_document_changelist")).content.decode().split("</thead>")[-1]
    assert "fk-badge--muted" in body
    assert "Vēsturisks" in body


def test_state_filter_isolates_replaced():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    active = _doc(app)
    replaced = _doc(app, deleted_at=timezone.now())
    c = _staff_client()
    url = reverse("admin:documents_document_changelist") + "?state=replaced"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert f"/documents/document/{replaced.pk}/change/" in body
    assert f"/documents/document/{active.pk}/change/" not in body


def test_state_filter_isolates_active():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    active = _doc(app)
    replaced = _doc(app, deleted_at=timezone.now())
    c = _staff_client()
    url = reverse("admin:documents_document_changelist") + "?state=active"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert f"/documents/document/{active.pk}/change/" in body
    assert f"/documents/document/{replaced.pk}/change/" not in body
