"""Reusable admin cross-link helpers."""

import pytest
from django.urls import NoReverseMatch

from apps.core.admin_links import admin_link, admin_links
from apps.members.models import Guardian, Member

pytestmark = pytest.mark.django_db


def test_admin_link_renders_anchor_to_change_page():
    g = Guardian.objects.create(full_name="Vecāks V")
    html = str(admin_link(g))
    assert f'href="/admin/members/guardian/{g.pk}/change/"' in html
    assert "Vecāks V" in html
    assert html.startswith("<a ")


def test_admin_link_escapes_fallback_label_when_unregistered(monkeypatch):
    # Force the NoReverseMatch path and pass an unsafe label.
    from apps.core import admin_links as mod

    def _boom(*a, **k):
        raise NoReverseMatch

    monkeypatch.setattr(mod, "reverse", _boom)
    g = Guardian.objects.create(full_name="V")
    out = str(admin_link(g, label="<b>x</b>"))
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_admin_link_custom_label():
    g = Guardian.objects.create(full_name="Vecāks V")
    assert "Atvērt" in str(admin_link(g, label="Atvērt"))


def test_admin_link_none_returns_dash():
    assert admin_link(None) == "—"


def test_admin_links_lists_targets():
    g = Guardian.objects.create(full_name="V")
    m1 = Member.objects.create(full_name="Bērns A", guardian=g)
    m2 = Member.objects.create(full_name="Bērns B", guardian=g)
    html = str(admin_links([m1, m2]))
    assert f"/members/member/{m1.pk}/change/" in html
    assert f"/members/member/{m2.pk}/change/" in html


def test_admin_links_empty_returns_dash():
    assert admin_links([]) == "—"


def test_admin_links_overflow_marker():
    g = Guardian.objects.create(full_name="V")
    members = [Member.objects.create(full_name=f"B{i}", guardian=g) for i in range(4)]
    html = str(admin_links(members, limit=2))
    assert "+2" in html
