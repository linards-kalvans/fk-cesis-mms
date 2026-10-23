"""Application queue page."""

from __future__ import annotations

import datetime

import pytest
from django.urls import resolve, reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def test_queue_requires_staff(client):
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_queue_rejects_a_signed_in_non_staff_user(client, django_user_model):
    django_user_model.objects.create_user(username="parent_ish", password="x")
    client.login(username="parent_ish", password="x")
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 302, "non-staff must not reach the hub"
    assert "/admin/login/" in response["Location"]


def test_queue_lists_a_submitted_application(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 200
    body = response.content.decode()
    assert submitted_application.member_full_name in body
    assert "Pieteikumu rinda" in body


def test_queue_shows_pipeline_progress_and_next_action(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert "0/7" in body
    assert "Datu pārbaude" in body


def test_queue_default_tab_hides_drafts(client, reviewer, draft_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert draft_application.member_full_name not in body


def test_queue_all_tab_shows_drafts(client, reviewer, draft_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "visi"}).content.decode()
    assert draft_application.member_full_name in body


def test_queue_orders_newest_submission_first(client, reviewer, submitted_application):
    from django.utils import timezone
    from apps.registrations.models import RegistrationApplication

    older = RegistrationApplication.objects.create(
        claimed_email="older@example.lv",
        guardian=submitted_application.guardian,
        parent_account=submitted_application.parent_account,
        member_full_name="Older Child",
        status=RegistrationApplication.Status.SUBMITTED,
        submitted_at=timezone.now() - datetime.timedelta(days=10),
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert body.index(submitted_application.member_full_name) < body.index(
        older.member_full_name
    )


def test_queue_flags_an_application_waiting_over_three_days(
    client, reviewer, submitted_application
):
    from django.utils import timezone

    submitted_application.submitted_at = timezone.now() - datetime.timedelta(days=4)
    submitted_application.save(update_fields=["submitted_at"])
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert "qrow--aging" in body


def test_queue_unknown_tab_falls_back_to_default(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"), {"tab": "../etc/passwd"})
    assert response.status_code == 200
    assert submitted_application.member_full_name in response.content.decode()


def test_queue_invalid_page_falls_back_to_page_one(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"), {"page": "not-a-number"})
    assert response.status_code == 200
    assert submitted_application.member_full_name in response.content.decode()


def test_queue_aging_flag_only_applies_to_old_submitted_rows(
    client, reviewer, submitted_application
):
    from django.utils import timezone
    from apps.registrations.models import RegistrationApplication

    RegistrationApplication.objects.create(
        claimed_email="old-fix@example.lv",
        guardian=submitted_application.guardian,
        parent_account=submitted_application.parent_account,
        member_full_name="Old Fix Child",
        status=RegistrationApplication.Status.FIX_REQUESTED,
        submitted_at=timezone.now() - datetime.timedelta(days=10),
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "visi"}).content.decode()
    assert "qrow--aging" not in body


def test_queue_badge_reflects_non_submitted_status(client, reviewer, approved_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    assert "badge--approved" in body
    assert "badge--submitted" not in body


def test_queue_document_dots_use_distinct_letters_and_titles(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert 'title="Vecāka ID">V<' in body
    assert 'title="Bērna ID">B<' in body
    assert 'title="Portrets">P<' in body
    assert "docdot--missing" not in body


def test_queue_procesa_and_parakstiti_tabs_are_disjoint(
    client, reviewer, approved_application
):
    from django.utils import timezone

    client.force_login(reviewer)
    name = approved_application.member_full_name

    procesa_body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    parakstiti_body = client.get(
        reverse("admin_hub:queue"), {"tab": "parakstiti"}
    ).content.decode()
    assert name in procesa_body, "approved-but-unsigned belongs in Procesā"
    assert name not in parakstiti_body

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at", "signed_at"])

    procesa_body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    parakstiti_body = client.get(
        reverse("admin_hub:queue"), {"tab": "parakstiti"}
    ).content.decode()
    assert name not in procesa_body
    assert name in parakstiti_body, "signed agreement belongs in Parakstīti"

    # Guard against the exclude()-across-a-reverse-FK duplicate-row trap:
    # the signed application must appear exactly once in its tab's queryset.
    from apps.admin_hub import queries

    assert queries._tab_queryset("parakstiti").filter(pk=approved_application.pk).count() == 1
    assert queries._tab_queryset("procesa").filter(pk=approved_application.pk).count() == 0


def test_queue_procesa_keeps_a_member_with_signed_agreement_history(
    client, reviewer, approved_application
):
    """A member can carry a historical signed agreement (is_current=False)
    alongside a current, still-unsigned one — e.g. a prior season. Only the
    *current* agreement's signed state may move the application to
    Parakstiti; the historical row must not leak across tabs.

    Built directly via Agreement.objects.create(), not the service layer:
    apps/agreements/services.py never actually produces this combination
    today (every is_current transition moves state off SIGNED in the same
    write), so a fixture or service call could not reach this state. The
    query must be correct regardless of what the service layer currently
    guarantees.
    """
    from django.utils import timezone

    from apps.agreements.models import Agreement

    Agreement.objects.create(
        member=approved_application.approved_member,
        is_current=False,
        state=Agreement.State.SIGNED,
        generated_at=timezone.now(),
        signed_at=timezone.now(),
    )

    client.force_login(reviewer)
    name = approved_application.member_full_name

    procesa_body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    parakstiti_body = client.get(
        reverse("admin_hub:queue"), {"tab": "parakstiti"}
    ).content.decode()

    assert name in procesa_body, "current agreement is unsigned; must stay in Procesa"
    assert name not in parakstiti_body


# --- Hub index (/hub/) --------------------------------------------------------
# Contract: /hub/ is a permanent 301 redirect to the named queue route. It
# carries no authorization behavior of its own — the queue view owns its
# staff-only gate — and it deliberately drops incoming query parameters.


def test_hub_index_resolves_to_named_route():
    assert reverse("admin_hub:index") == "/hub/"
    assert resolve("/hub/").url_name == "index"


def test_hub_index_permanently_redirects_anonymous_client_to_queue(client):
    # follow=False is explicit: the index itself must hand back the 301, and
    # the Location must be the queue URL verbatim — NOT a login redirect,
    # which would mean the index grew its own auth gate.
    response = client.get(reverse("admin_hub:index"), follow=False)
    assert response.status_code == 301
    assert response["Location"] == reverse("admin_hub:queue")


def test_hub_index_drops_query_parameters(client):
    response = client.get("/hub/", {"tab": "procesa"}, follow=False)
    assert response.status_code == 301
    assert response["Location"] == reverse("admin_hub:queue")
    assert "?" not in response["Location"]


# --- Queue name search (slice 1) -------------------------------------------
# Contract: one normalized query drives the visible list, the tab counts and
# the tab/page links. Tokens are ANDed; each token ORs over the child's full
# name and the guardian's first/family names. Ordinary DB `icontains` only —
# no accent folding, and no claim that SQLite folds Latvian case.


def _make_application(*, full_name, guardian=None, status="submitted"):
    from django.utils import timezone

    from apps.registrations.models import RegistrationApplication

    status_value = {
        "submitted": RegistrationApplication.Status.SUBMITTED,
        "fix_requested": RegistrationApplication.Status.FIX_REQUESTED,
        "approved": RegistrationApplication.Status.APPROVED,
    }[status]
    return RegistrationApplication.objects.create(
        claimed_email="queue-search@example.test",
        guardian=guardian,
        member_full_name=full_name,
        status=status_value,
        submitted_at=timezone.now(),
    )


def _queue_body(client, reviewer, **params):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"), params)
    assert response.status_code == 200
    return response, response.content.decode()


def test_search_matches_child_name_partial(client, reviewer):
    from tests.support import make_guardian

    match = _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )
    other = _make_application(
        full_name="Pēteris Liepa",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="Kalni")

    assert match.member_full_name in body
    assert other.member_full_name not in body


def test_search_matches_guardian_first_and_family_names(client, reviewer):
    from tests.support import make_guardian

    guardian = make_guardian(first_name="Jānis", family_name="Ozols")
    match = _make_application(full_name="Marta Kalniņa", guardian=guardian)
    other = _make_application(
        full_name="Pēteris Liepa",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, by_first = _queue_body(client, reviewer, tab="visi", q="Jānis")
    _, by_family = _queue_body(client, reviewer, tab="visi", q="Ozols")

    for body in (by_first, by_family):
        assert match.member_full_name in body
        assert other.member_full_name not in body


def test_search_tokens_are_order_independent(client, reviewer):
    from tests.support import make_guardian

    match = _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )
    other = _make_application(
        full_name="Pēteris Liepa",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="Ozols Jānis")

    assert match.member_full_name in body
    assert other.member_full_name not in body


def test_search_tokens_can_split_across_child_and_guardian(client, reviewer):
    from tests.support import make_guardian

    match = _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )
    other = _make_application(
        full_name="Marta Liepa",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="Marta Ozols")

    assert match.member_full_name in body
    assert other.member_full_name not in body


def test_search_keeps_child_match_when_guardian_is_null(client, reviewer):
    from tests.support import make_guardian

    match = _make_application(full_name="Bezvecāku Bērns", guardian=None)
    other = _make_application(
        full_name="Cits Bērns",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="Bezvecāku")

    assert match.member_full_name in body
    assert other.member_full_name not in body


def test_normalize_search_strips_collapses_and_caps():
    from apps.admin_hub.queries import MAX_SEARCH_LENGTH, normalize_search

    assert normalize_search(None) == ""
    assert normalize_search("") == ""
    assert normalize_search("   ") == ""
    assert normalize_search("  Jānis   Ozols  ") == "Jānis Ozols"
    assert len(normalize_search("x" * (MAX_SEARCH_LENGTH + 50))) == MAX_SEARCH_LENGTH

    # Truncation must not leave a trailing separator, and re-normalizing an
    # already-normalized value must be a no-op.
    capped = normalize_search("word " * 100)
    assert capped == capped.strip()
    assert "  " not in capped
    assert len(capped) <= MAX_SEARCH_LENGTH
    assert normalize_search(capped) == capped
    for raw in ("  Jānis   Ozols  ", "word " * 100, "x" * 250):
        assert normalize_search(normalize_search(raw)) == normalize_search(raw)


def test_search_whitespace_is_normalized_at_the_view_and_query_boundary(
    client, reviewer
):
    from apps.admin_hub import queries
    from tests.support import make_guardian

    match = _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )
    _make_application(
        full_name="Pēteris Liepa",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    response, body = _queue_body(client, reviewer, tab="visi", q="  Jānis   Ozols  ")

    assert response.context["q"] == "Jānis Ozols"
    assert match.member_full_name in body
    assert queries._tab_queryset("visi", q="  Jānis   Ozols  ").count() == 1
    rows, _page_obj = queries.queue_page("visi", 1, q="  Jānis   Ozols  ")
    assert [row.application.pk for row in rows] == [match.pk]


def test_search_blank_query_lists_every_row(client, reviewer):
    from tests.support import make_guardian

    first = _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )
    second = _make_application(
        full_name="Pēteris Liepa",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="   ")

    assert first.member_full_name in body
    assert second.member_full_name in body


def test_search_no_match_uses_a_distinct_empty_state(client, reviewer):
    from tests.support import make_guardian

    _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )

    response, body = _queue_body(client, reviewer, tab="visi", q="Neeksistējošs")

    assert response.context["q"] == "Neeksistējošs"
    assert "Nav pieteikumu, kas atbilst meklēšanai" in body
    assert "Šajā skatā nav pieteikumu." not in body
    assert "Marta Kalniņa" not in body


def test_search_unfiltered_empty_tab_keeps_the_generic_empty_state(client, reviewer):
    _, body = _queue_body(client, reviewer, tab="visi")

    assert "Šajā skatā nav pieteikumu." in body
    assert "Nav pieteikumu, kas atbilst meklēšanai" not in body


def test_search_query_is_escaped_and_url_encoded_in_links(client, reviewer):
    from tests.support import make_guardian

    _make_application(
        full_name="Anna O'Hara",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="O'Hara")

    # Input value escaped for HTML, link parameter percent-encoded.
    assert 'value="O&#x27;Hara"' in body
    assert "q=O%27Hara" in body
    assert "tab=visi&amp;q=O%27Hara" in body
    assert "Anna O&#x27;Hara" in body


def test_correction_summary_queries_stay_bounded_as_the_page_grows(
    client, reviewer
):
    """History summaries are aggregated per page, not fetched per row.

    Other pipeline queries intentionally scale with the visible rows, so this
    counts only statements touching the correction table. Two applications
    and a full 25-row page must issue the same (constant) number of history
    queries, and never one per row.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.admin_hub import queries
    from apps.registrations.models import ApplicationCorrectionMessage
    from tests.support import make_guardian

    def _correction_query_count() -> int:
        with CaptureQueriesContext(connection) as captured:
            queries.queue_page("visi", 1)
        return sum(
            1
            for query in captured.captured_queries
            if "applicationcorrectionmessage" in query["sql"].lower()
        )

    def _add(message_subject: str) -> None:
        application = _make_application(
            full_name=message_subject,
            guardian=make_guardian(
                first_name="Skaits", family_name=message_subject
            ),
        )
        ApplicationCorrectionMessage.objects.create(
            application=application,
            status=ApplicationCorrectionMessage.Status.SENT,
            subject=message_subject,
            body="Testa teksts.",
        )

    _add("Ziņa viens")
    _add("Ziņa divi")
    small_page_queries = _correction_query_count()
    assert small_page_queries == 2, (
        "one aggregate query for sent counts plus one for the latest row"
    )

    for index in range(3, 26):
        _add(f"Ziņa {index}")
    full_page_queries = _correction_query_count()

    assert full_page_queries == small_page_queries
    assert full_page_queries < 25, "a per-row history query would scale here"


def test_search_counts_match_the_visible_list_across_tabs(
    client, reviewer, approved_application
):
    from apps.admin_hub import queries
    from tests.support import make_guardian

    # approved_application's child + guardian both contain "Hub"; add a
    # submitted row with its own guardian so two tabs have one match each.
    _make_application(
        full_name="Hub Search Child",
        guardian=make_guardian(first_name="Hub Search", family_name="Guardian"),
    )

    counts = queries.tab_counts(q="Hub")
    assert counts == {
        tab: queries._tab_queryset(tab, q="Hub").count() for tab in queries.QUEUE_TABS
    }
    assert counts["procesa"] == 1
    assert counts["jaizskata"] == 1

    for tab, expected in (("jaizskata", 1), ("procesa", 1), ("visi", 2)):
        response, body = _queue_body(client, reviewer, tab=tab, q="Hub")
        assert response.context["tab_counts"] == counts
        assert body.count('<article class="qrow') == expected


def test_search_paginates_and_preserves_tab_and_query(client, reviewer):
    for index in range(26):
        _make_application(full_name=f"Daudz Bērns {index:02d}")

    first_page, first_body = _queue_body(client, reviewer, tab="visi", q="Daudz")

    assert first_page.context["page_obj"].number == 1
    assert first_page.context["page_obj"].paginator.count == 26
    assert first_body.count('<article class="qrow') == 25
    assert "tab=visi&amp;q=Daudz&amp;page=2" in first_body

    second_page, second_body = _queue_body(
        client, reviewer, tab="visi", q="Daudz", page="2"
    )

    assert second_page.context["page_obj"].number == 2
    assert second_body.count('<article class="qrow') == 1
    assert "tab=visi&amp;q=Daudz&amp;page=1" in second_body


def test_search_form_clear_and_tabs_do_not_carry_a_page(client, reviewer):
    for index in range(26):
        _make_application(full_name=f"Daudz Bērns {index:02d}")

    _, body = _queue_body(client, reviewer, tab="visi", q="Daudz", page="2")

    form_start = body.index('<form class="qsearch"')
    form_end = body.index("</form>", form_start)
    form_markup = body[form_start:form_end]
    assert 'name="q"' in form_markup
    assert 'name="tab" value="visi"' in form_markup
    assert 'name="page"' not in form_markup
    # Clear returns to the same tab with no query and no page.
    assert 'href="?tab=visi"' in body
    # Tab switches keep the query but never the page number.
    nav_start = body.index('<nav class="tabs">')
    nav_markup = body[nav_start : body.index("</nav>", nav_start)]
    assert "page=" not in nav_markup
    for slug in ("jaizskata", "procesa", "parakstiti", "noraiditi", "visi"):
        assert f"tab={slug}&amp;q=Daudz" in nav_markup


def test_search_out_of_range_page_falls_back_to_one(client, reviewer):
    for index in range(3):
        _make_application(full_name=f"Mazs Bērns {index}")

    response, body = _queue_body(client, reviewer, tab="visi", q="Mazs", page="999")

    assert response.context["page_obj"].number == 1
    assert body.count('<article class="qrow') == 3


def test_search_form_has_a_programmatic_label_and_no_clear_when_blank(
    client, reviewer
):
    _, body = _queue_body(client, reviewer, tab="visi")

    form_start = body.index('<form class="qsearch"')
    form_end = body.index("</form>", form_start)
    form_markup = body[form_start:form_end]

    assert 'role="search"' in form_markup
    assert '<label for="queue-q">Meklēt pēc vārda</label>' in form_markup
    assert 'id="queue-q"' in form_markup
    assert 'name="q"' in form_markup
    # A blank query has nothing to clear.
    assert "Notīrīt" not in body


def test_search_staff_gate_still_applies(client):
    response = client.get(reverse("admin_hub:queue"), {"q": "Ozols"})
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_search_ascii_matching_is_case_insensitive(client, reviewer):
    from tests.support import make_guardian

    match = _make_application(
        full_name="MixedCase Child",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="mixedcase")

    assert match.member_full_name in body


def test_search_exact_latvian_unicode_matches_without_casefold_claims(
    client, reviewer
):
    from tests.support import make_guardian

    # Exact diacritics only. SQLite does not fold non-ASCII case, and the
    # deployed PostgreSQL collation must be checked manually before promising
    # any broader case/accent behavior.
    match = _make_application(
        full_name="Žanis Šķēle",
        guardian=make_guardian(first_name="Ilze", family_name="Bērziņa"),
    )

    _, body = _queue_body(client, reviewer, tab="visi", q="Šķēle")

    assert match.member_full_name in body


def test_search_overlong_query_is_capped_and_safe(client, reviewer):
    from tests.support import make_guardian

    _make_application(
        full_name="Marta Kalniņa",
        guardian=make_guardian(first_name="Jānis", family_name="Ozols"),
    )

    response, body = _queue_body(client, reviewer, tab="visi", q="x" * 300)

    assert response.status_code == 200
    assert response.context["q"] == "x" * 200
    assert "Nav pieteikumu, kas atbilst meklēšanai" in body
