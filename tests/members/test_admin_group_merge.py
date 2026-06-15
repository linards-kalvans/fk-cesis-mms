"""Merge admin action reparents members and deletes duplicate groups."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import Guardian, Member, TrainingGroup

pytestmark = pytest.mark.django_db


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
    g = Guardian.objects.create(full_name="V")
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
