"""Slice 4 (Task 5) — correction summaries and staff history endpoint.

Covers the Hub's only view of ``ApplicationCorrectionMessage``: bounded queue
summaries, the shared queue/cockpit trigger, the staff-only GET history
endpoint, escaping, pagination, cache posture and honest send semantics.
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.registrations.models import (
    ApplicationCorrectionMessage,
    RegistrationApplication,
)

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def _message(
    application,
    *,
    status=ApplicationCorrectionMessage.Status.SENT,
    subject="Jūsu pieteikums ir jālabo",
    body="Lūdzu, labojiet pieteikumu.",
    review_message="Lūdzu, labojiet adresi.",
    created_at=None,
    sent_at=None,
    resolved_at=None,
    actor=None,
):
    row = ApplicationCorrectionMessage.objects.create(
        application=application,
        actor=actor,
        status=status,
        subject=subject,
        body=body,
        review_message=review_message,
        sent_at=sent_at,
        resolved_at=resolved_at,
    )
    if created_at is not None:
        ApplicationCorrectionMessage.objects.filter(pk=row.pk).update(
            created_at=created_at
        )
        row.refresh_from_db()
    return row


def _history_url(application):
    return reverse("admin_hub:correction-messages", args=[application.pk])


def _history_body(client, reviewer, application, **params):
    client.force_login(reviewer)
    response = client.get(_history_url(application), params)
    assert response.status_code == 200
    return response, response.content.decode()


def test_history_requires_staff(client, submitted_application):
    response = client.get(_history_url(submitted_application))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_history_rejects_signed_in_non_staff(client, submitted_application):
    from django.contrib.auth.models import User

    user = User.objects.create_user(username="not-staff", password="x")
    client.force_login(user)
    response = client.get(_history_url(submitted_application))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_history_rejects_inactive_staff(client, submitted_application):
    from django.contrib.auth.models import User

    user = User.objects.create_user(
        username="inactive-staff", password="x", is_staff=True, is_active=False
    )
    client.force_login(user)
    response = client.get(_history_url(submitted_application))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_history_unknown_application_is_404(client, reviewer):
    client.force_login(reviewer)
    response = client.get(
        reverse("admin_hub:correction-messages", args=[999999])
    )
    assert response.status_code == 404


def test_history_post_is_refused(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.post(_history_url(submitted_application))
    assert response.status_code == 405


def test_history_get_performs_no_mutation(client, reviewer, submitted_application):
    row = _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.PENDING,
        sent_at=None,
        resolved_at=None,
    )
    before = {
        "count": ApplicationCorrectionMessage.objects.count(),
        "status": row.status,
        "subject": row.subject,
        "body": row.body,
        "resolved_at": row.resolved_at,
    }

    _history_body(client, reviewer, submitted_application)

    row.refresh_from_db()
    assert ApplicationCorrectionMessage.objects.count() == before["count"]
    assert row.status == before["status"]
    assert row.subject == before["subject"]
    assert row.body == before["body"]
    assert row.resolved_at == before["resolved_at"]


def test_history_escapes_malicious_subject_body_and_note(
    client, reviewer, submitted_application
):
    _message(
        submitted_application,
        subject='<script>alert("subject")</script>',
        body='<img src=x onerror="alert(2)">\nOtrā rinda',
        review_message='<b onmouseover="x">Piezīme</b>',
    )

    _, body = _history_body(client, reviewer, submitted_application)

    assert "<script>alert" not in body
    assert "<img src=x" not in body
    assert "<b onmouseover" not in body
    assert "&lt;script&gt;" in body
    assert "&lt;img src=x" in body
    assert "&lt;b onmouseover" in body
    assert "Otrā rinda" in body


def test_history_pages_oldest_first_at_twenty_rows(
    client, reviewer, submitted_application
):
    base = timezone.now() - datetime.timedelta(days=30)
    for index in range(1, 26):
        _message(
            submitted_application,
            subject=f"Ziņa {index:02d}",
            created_at=base + datetime.timedelta(hours=index),
        )

    first_response, first_body = _history_body(
        client, reviewer, submitted_application
    )
    assert first_response.context["page_obj"].number == 1
    assert len(first_response.context["page_obj"].object_list) == 20
    assert "Ziņa 01" in first_body
    assert "Ziņa 20" in first_body
    assert "Ziņa 21" not in first_body
    assert "Lapa 1 no 2" in first_body

    second_response, second_body = _history_body(
        client, reviewer, submitted_application, page=2
    )
    assert second_response.context["page_obj"].number == 2
    assert len(second_response.context["page_obj"].object_list) == 5
    assert "Ziņa 21" in second_body
    assert "Ziņa 25" in second_body
    assert "Ziņa 20" not in second_body
    assert second_body.index("Ziņa 21") < second_body.index("Ziņa 25")


@pytest.mark.parametrize("bad_page", ["not-a-number", "999", "-1", ""])
def test_history_bad_or_out_of_range_page_falls_back_to_first(
    client, reviewer, submitted_application, bad_page
):
    _message(submitted_application, subject="Vienīgā ziņa")
    response, body = _history_body(
        client, reviewer, submitted_application, page=bad_page
    )
    assert response.context["page_obj"].number == 1
    assert "Vienīgā ziņa" in body


def test_history_is_private_and_not_cached(client, reviewer, submitted_application):
    response, _ = _history_body(client, reviewer, submitted_application)
    assert response["Cache-Control"] == "private, no-store"
    assert response["Pragma"] == "no-cache"


def test_ajax_returns_a_fragment_and_normal_get_returns_a_usable_page(
    client, reviewer, submitted_application
):
    _message(submitted_application, subject="Fragmenta ziņa")
    client.force_login(reviewer)

    fragment = client.get(
        _history_url(submitted_application),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    ).content.decode()
    assert "data-correction-history" in fragment
    assert "<html" not in fragment.lower()
    assert "Pieteikumu rinda" not in fragment

    page = client.get(_history_url(submitted_application)).content.decode()
    assert "Fragmenta ziņa" in page
    assert "Django admin" in page


def test_history_empty_state_explains_pre_tracking_uncertainty(
    client, reviewer, submitted_application
):
    _, body = _history_body(client, reviewer, submitted_application)
    assert "Nav reģistrētu labojuma pieprasījuma ziņu" in body
    assert "pirms" in body.lower()
    assert "nav zināma" in body.lower()
    assert "netika nosūtīts" in body


def test_history_renders_pending_failed_and_sent_outcomes_truthfully(
    client, reviewer, submitted_application
):
    now = timezone.now()
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        subject="Nosūtītā ziņa",
        sent_at=now,
    )
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.FAILED,
        subject="Neizdevusies ziņa",
    )
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.PENDING,
        subject="Nezināmā ziņa",
    )

    _, body = _history_body(client, reviewer, submitted_application)

    assert "Nosūtīts e-pasta sistēmai" in body
    assert "Tas neapstiprina piegādi vai atvēršanu" in body
    assert "Nosūtīšana neizdevās" in body
    assert "Vecāks šo ziņu, iespējams, nesaņēma" in body
    assert "Iznākums nav apstiprināts" in body
    assert "pierādīta piegāde vai neizdošanās" in body


def test_history_marks_resolved_and_unresolved_rows(
    client, reviewer, submitted_application
):
    resolved_at = timezone.now()
    _message(
        submitted_application,
        subject="Atrisinātā ziņa",
        resolved_at=resolved_at,
    )
    _message(
        submitted_application,
        subject="Neatrisinātā ziņa",
    )

    _, body = _history_body(client, reviewer, submitted_application)

    assert resolved_at.strftime("%d.%m.%Y") in body
    assert "Nav atrisināta" in body


def _summary(application):
    from apps.admin_hub.correction_messages import correction_summaries

    return correction_summaries([application.pk])[application.pk]


def test_summary_keeps_prior_success_time_after_a_failed_attempt(
    submitted_application,
):
    now = timezone.now()
    sent_at = now - datetime.timedelta(days=2)
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        created_at=now - datetime.timedelta(days=3),
        sent_at=sent_at,
    )
    failed_at = now - datetime.timedelta(days=1)
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.FAILED,
        created_at=failed_at,
    )

    summary = _summary(submitted_application)

    assert summary["sent_count"] == 1
    assert summary["latest_status"] == ApplicationCorrectionMessage.Status.FAILED
    assert summary["latest_created_at"] == failed_at
    assert summary["latest_sent_at"] == sent_at
    assert summary["has_history"] is True


def test_summary_keeps_prior_success_time_after_a_pending_attempt(
    submitted_application,
):
    now = timezone.now()
    sent_at = now - datetime.timedelta(days=2)
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        created_at=now - datetime.timedelta(days=3),
        sent_at=sent_at,
    )
    pending_at = now - datetime.timedelta(days=1)
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.PENDING,
        created_at=pending_at,
    )

    summary = _summary(submitted_application)

    assert summary["sent_count"] == 1
    assert summary["latest_status"] == ApplicationCorrectionMessage.Status.PENDING
    assert summary["latest_created_at"] == pending_at
    assert summary["latest_sent_at"] == sent_at


def test_summary_latest_sent_at_is_the_latest_successful_send(
    submitted_application,
):
    now = timezone.now()
    later_sent_at = now - datetime.timedelta(days=1)
    earlier_sent_at = now - datetime.timedelta(days=4)
    # The later-created row carries the earlier send time, so "latest row"
    # alone would report the wrong timestamp.
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        created_at=now - datetime.timedelta(days=3),
        sent_at=later_sent_at,
    )
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        created_at=now - datetime.timedelta(days=2),
        sent_at=earlier_sent_at,
    )

    summary = _summary(submitted_application)

    assert summary["sent_count"] == 2
    assert summary["latest_status"] == ApplicationCorrectionMessage.Status.SENT
    assert summary["latest_sent_at"] == later_sent_at


@pytest.mark.parametrize(
    "status",
    [
        ApplicationCorrectionMessage.Status.FAILED,
        ApplicationCorrectionMessage.Status.PENDING,
    ],
)
def test_summary_without_a_successful_send_has_no_sent_time(
    submitted_application, status
):
    _message(submitted_application, status=status)

    summary = _summary(submitted_application)

    assert summary["sent_count"] == 0
    assert summary["latest_status"] == status
    assert summary["latest_sent_at"] is None
    assert summary["has_history"] is True


def test_queue_and_cockpit_show_prior_success_time_when_latest_failed(
    client, reviewer, submitted_application
):
    now = timezone.now()
    sent_at = now - datetime.timedelta(days=2)
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        subject="Nosūtītā ziņa",
        created_at=now - datetime.timedelta(days=3),
        sent_at=sent_at,
    )
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.FAILED,
        subject="Neizdevusies ziņa",
        created_at=now - datetime.timedelta(days=1),
    )
    expected_time = timezone.localtime(sent_at).strftime("%d.%m.%Y %H:%M")

    client.force_login(reviewer)
    bodies = (
        client.get(reverse("admin_hub:queue")).content.decode(),
        client.get(
            reverse("admin_hub:cockpit", args=[submitted_application.pk])
        ).content.decode(),
    )

    for body in bodies:
        assert "Ziņas: 1 nosūtītas" in body
        assert "Nosūtīšana neizdevās" in body
        assert f"Pēdējā apstiprinātā nosūtīšana: {expected_time}" in body


def test_queue_summary_counts_sent_only_and_warns_about_latest_failure(
    client, reviewer, submitted_application
):
    now = timezone.now()
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        subject="Pirmā nosūtītā",
        created_at=now - datetime.timedelta(days=3),
        sent_at=now - datetime.timedelta(days=3),
    )
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.SENT,
        subject="Otrā nosūtītā",
        created_at=now - datetime.timedelta(days=2),
        sent_at=now - datetime.timedelta(days=2),
    )
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.FAILED,
        subject="Pēdējā neizdevusies",
        created_at=now - datetime.timedelta(days=1),
    )

    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()

    assert "Ziņas: 2 nosūtītas" in body
    assert "Nosūtīšana neizdevās" in body
    assert "Ziņas: 3" not in body


def test_queue_summary_reports_pending_without_counting_it(
    client, reviewer, submitted_application
):
    _message(
        submitted_application,
        status=ApplicationCorrectionMessage.Status.PENDING,
        subject="Nepabeigta ziņa",
    )

    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()

    assert "Ziņas: 0 nosūtītas" in body
    assert "Nosūtīšanas iznākums nav apstiprināts" in body


def test_queue_never_embeds_full_correspondence(
    client, reviewer, submitted_application
):
    _message(
        submitted_application,
        subject="Slepenais temats",
        body="Slepenais e-pasta teksts",
        review_message="Slepenā piezīme",
    )

    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()

    assert "Slepenais temats" not in body
    assert "Slepenais e-pasta teksts" not in body
    assert "Slepenā piezīme" not in body
    assert _history_url(submitted_application) in body


def test_awaiting_parent_is_independent_of_tracked_history(
    client, reviewer, submitted_application
):
    submitted_application.status = RegistrationApplication.Status.FIX_REQUESTED
    submitted_application.save(update_fields=["status"])
    client.force_login(reviewer)

    queue_body = client.get(
        reverse("admin_hub:queue"), {"tab": "jalabo"}
    ).content.decode()
    cockpit_body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    for body in (queue_body, cockpit_body):
        assert "Nav reģistrētas ziņas" in body
        assert "Gaida vecāka labojumu" in body


def test_queue_and_cockpit_share_the_same_summary_and_endpoint(
    client, reviewer, submitted_application
):
    _message(submitted_application, subject="Kopīgā ziņa")
    client.force_login(reviewer)

    queue_body = client.get(reverse("admin_hub:queue")).content.decode()
    cockpit_body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()

    for body in (queue_body, cockpit_body):
        assert "Ziņas: 1 nosūtītas" in body
        assert _history_url(submitted_application) in body
        assert "correction_messages.js" in body
    # The cockpit also must not prefetch the correspondence itself.
    assert "Kopīgā ziņa" not in queue_body
    assert "Kopīgā ziņa" not in cockpit_body
