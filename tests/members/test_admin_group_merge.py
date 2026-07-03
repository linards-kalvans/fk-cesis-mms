"""Merge admin action reparents members and deletes duplicate groups."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import Member, TrainingGroup

from tests.support import make_guardian

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_merge_confirmation_page_lists_selected_groups():
    a = TrainingGroup.objects.create(name="U10 A")
    b = TrainingGroup.objects.create(name="U10 A dublikāts")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk), str(b.pk)],
    })
    assert resp.status_code == 200
    assert b"U10 A" in resp.content
    assert b"Apvienot" in resp.content


def test_merge_reparents_members_and_deletes_others():
    g = make_guardian(full_name="V")
    target = TrainingGroup.objects.create(name="U10 A")
    dup = TrainingGroup.objects.create(name="U10 A dublikāts")
    m1 = Member.objects.create(full_name="A", guardian=g, training_group=target)
    m2 = Member.objects.create(full_name="B", guardian=g, training_group=dup)
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(target.pk), str(dup.pk)],
        "target": str(target.pk),
        "apply": "1",
    })
    assert resp.status_code == 302
    m1.refresh_from_db()
    m2.refresh_from_db()
    assert m1.training_group_id == target.pk
    assert m2.training_group_id == target.pk
    assert not TrainingGroup.objects.filter(pk=dup.pk).exists()
    assert TrainingGroup.objects.filter(pk=target.pk).exists()


def test_merge_single_group_is_rejected():
    a = TrainingGroup.objects.create(name="U10 A")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk)],
    }, follow=True)
    assert TrainingGroup.objects.filter(pk=a.pk).exists()
    assert b"vismaz divas" in resp.content.lower()


def test_merge_rejects_target_outside_selection():
    # A target PK that is not among the selected groups must not delete anything.
    a = TrainingGroup.objects.create(name="A")
    b = TrainingGroup.objects.create(name="B")
    outsider = TrainingGroup.objects.create(name="Outsider")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk), str(b.pk)],
        "target": str(outsider.pk),
        "apply": "1",
    }, follow=True)
    assert TrainingGroup.objects.filter(pk=a.pk).exists()
    assert TrainingGroup.objects.filter(pk=b.pk).exists()
    assert TrainingGroup.objects.filter(pk=outsider.pk).exists()
    assert "derīgu mērķa grupu" in resp.content.decode().lower()


def test_merge_requires_delete_permission():
    from django.contrib.auth.models import Permission

    a = TrainingGroup.objects.create(name="U10 A")
    b = TrainingGroup.objects.create(name="Dublikāts")
    user = User.objects.create_user("editor", "e@example.com", "pw", is_staff=True)
    for codename in ("view_traininggroup", "change_traininggroup"):
        user.user_permissions.add(Permission.objects.get(codename=codename))
    c = Client()
    c.login(username="editor", password="pw")
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk), str(b.pk)],
        "target": str(a.pk),
        "apply": "1",
    }, follow=True)
    # No delete permission → both groups survive.
    assert TrainingGroup.objects.filter(pk=a.pk).exists()
    assert TrainingGroup.objects.filter(pk=b.pk).exists()
    assert "nav ties" in resp.content.decode().lower()
