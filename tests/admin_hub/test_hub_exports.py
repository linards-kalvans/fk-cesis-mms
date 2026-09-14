"""Admin Hub — member export runner (``/hub/eksporti/``).

Tests for the run-only Hub surface over the shared P17
``MemberExportTemplate`` machinery: route + staff permissions, template
chooser ordering, GET prefill of stored filters, POST preview/download
dispatch through the parameterized P17 services, redacted download-only
audit, invalid/corrupted/zero-result handling, and the stable
``data-export-*`` UI hooks.

The Hub never creates, edits, deletes, defaults, pins, reorders, or
persists templates or their filters, never stores output, and never
audits a preview — each of those boundaries has a test below.

Feature-dependent imports (route name, view, form, settings parser) are
function-local so the module collects and every test fails at runtime
until the feature lands, rather than one ImportError masking the file.
"""

from __future__ import annotations

import csv
import io
import re
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import AuditEvent

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]

_LATVIAN = re.compile(r"[āčēģīķļņšūž]")


def _post(client, data):
    return client.post(reverse("admin_hub:exports"), data)


def _run_events():
    return AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_RUN)
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def export_guardian(db):
    from tests.support import make_guardian

    return make_guardian(
        full_name="Linda Exporta",
        email="hub-export-guardian@example.test",
        personal_id="101010-10101",
        phone="+37121111111",
        address="Sporta iela 5, Cēsis",
    )


@pytest.fixture
def hub_group_a(db):
    from apps.members.models import TrainingGroup

    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def hub_group_b(db):
    from apps.members.models import TrainingGroup

    return TrainingGroup.objects.create(name="U10 B", is_active=True)


@pytest.fixture
def make_member(export_guardian):
    """Member factory: optional current agreement state + training group."""
    from django.utils import timezone

    from apps.agreements.models import Agreement
    from apps.members.models import Member

    def _make(full_name, *, group=None, state=None, personal_id=""):
        member = Member.objects.create(
            full_name=full_name,
            personal_id=personal_id,
            guardian=export_guardian,
            training_group=group,
        )
        if state is not None:
            Agreement.objects.create(
                member=member,
                state=state,
                is_current=True,
                generated_at=timezone.now(),
            )
        return member

    return _make


@pytest.fixture
def make_template(db):
    from apps.members.models import MemberExportTemplate

    def _make(
        name="Hub template",
        *,
        columns=("member_full_name",),
        states=(),
        groups=(),
    ):
        template = MemberExportTemplate.objects.create(
            name=name,
            column_keys=list(columns),
            agreement_status_filters=list(states),
        )
        if groups:
            template.training_groups.add(*groups)
        return template

    return _make


@pytest.fixture
def hub_filter_members(make_member, hub_group_a, hub_group_b):
    """Five members covering every state×group predicate combination."""
    return SimpleNamespace(
        both=make_member("Hub Both", group=hub_group_a, state="signed"),
        state_only=make_member("Hub StateOnly", group=None, state="signed"),
        group_only=make_member("Hub GroupOnly", group=hub_group_a, state="generated"),
        neither=make_member("Hub Neither", group=None, state="generated"),
        replacement=make_member(
            "Hub Replacement", group=hub_group_b, state="sent"
        ),
    )


@pytest.fixture
def stored_filter_template(make_template, hub_group_a):
    """Template stored with agreement_states=[signed] + group A."""
    return make_template("Hub Stored", states=["signed"], groups=(hub_group_a,))


# ---------------------------------------------------------------------------
# Settings: EXPORT_PREVIEW_ROW_LIMIT parser (exact fallback to 20)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "  ", "zero", "0", "-3"])
def test_preview_limit_invalid_value_falls_back_to_20(value):
    from fk_cesis_mms.settings import _parse_export_preview_row_limit

    assert _parse_export_preview_row_limit(value) == 20


def test_preview_limit_positive_integer_is_preserved():
    from fk_cesis_mms.settings import _parse_export_preview_row_limit

    assert _parse_export_preview_row_limit("31") == 31


# ---------------------------------------------------------------------------
# Route + permissions + navigation
# ---------------------------------------------------------------------------


def test_exports_route_resolves():
    assert reverse("admin_hub:exports") == "/hub/eksporti/"


def test_anonymous_exports_redirects_to_login(client):
    response = client.get(reverse("admin_hub:exports"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_exports_rejects_signed_in_non_staff(client, django_user_model):
    django_user_model.objects.create_user(username="hub_export_parent", password="x")
    client.login(username="hub_export_parent", password="x")
    response = client.get(reverse("admin_hub:exports"))
    assert response.status_code == 302, "non-staff must not reach the exports page"
    assert "/admin/login/" in response["Location"]


def test_exports_nav_link_and_active_state_render(client, reviewer):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:exports")).content.decode()
    assert "Eksporti" in body
    nav_lines = [ln for ln in body.splitlines() if "/hub/eksporti/" in ln]
    assert nav_lines, "Eksporti nav item missing"
    assert any("is-active" in ln for ln in nav_lines), (
        "Eksporti nav item must be active on the exports page"
    )

    queue_body = client.get(reverse("admin_hub:queue")).content.decode()
    queue_nav_lines = [ln for ln in queue_body.splitlines() if "/hub/eksporti/" in ln]
    assert queue_nav_lines, "Eksporti link must appear in the nav on every hub page"
    assert not any("is-active" in ln for ln in queue_nav_lines), (
        "Eksporti must not be active on other hub pages"
    )


# ---------------------------------------------------------------------------
# GET: chooser, ordering, selection prefill, 404s, empty state
# ---------------------------------------------------------------------------


def test_template_list_renders_when_templates_exist(
    client, reviewer, make_template
):
    template = make_template("Hub Chosen")
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:exports")).content.decode()
    assert f"?template={template.pk}" in body
    assert "Nav sagatavotu šablonu." not in body


def test_templates_render_in_name_pk_order(
    client, reviewer, make_template
):
    """Existing model ordering ``(name, pk)`` — same-name templates pinned by pk."""
    dup_first = make_template("Dup")
    alpha = make_template("Alpha")
    dup_second = make_template("Dup")
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:exports")).content.decode()
    seen = list(dict.fromkeys(int(m) for m in re.findall(r"\?template=(\d+)", body)))
    assert seen == [alpha.pk, dup_first.pk, dup_second.pk]


def test_get_selected_template_prefills_stored_filters(
    client, reviewer, stored_filter_template, hub_group_a, hub_group_b
):
    client.force_login(reviewer)
    response = client.get(
        reverse("admin_hub:exports"), {"template": stored_filter_template.pk}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Hub Stored" in body

    signed_lines = [ln for ln in body.splitlines() if 'value="signed"' in ln]
    assert any("selected" in ln for ln in signed_lines), (
        "stored agreement state must pre-select its option"
    )
    void_lines = [ln for ln in body.splitlines() if 'value="void"' in ln]
    assert void_lines and all("selected" not in ln for ln in void_lines)

    group_lines = [
        ln for ln in body.splitlines() if f'value="{hub_group_a.pk}"' in ln
    ]
    assert any("selected" in ln for ln in group_lines), (
        "stored training group must pre-select its option"
    )
    other_group_lines = [
        ln for ln in body.splitlines() if f'value="{hub_group_b.pk}"' in ln
    ]
    assert all("selected" not in ln for ln in other_group_lines)

    assert "Sakrit:" not in body, "GET must never run a preview"


def test_selected_template_shows_metadata_and_sensitive_marker(
    client, reviewer, make_template, hub_group_a
):
    template = make_template(
        "Hub Meta",
        columns=("member_full_name", "guardian_email"),
        states=["signed"],
        groups=(hub_group_a,),
    )
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:exports"), {"template": template.pk}
    ).content.decode()
    assert "Biedra vārds, uzvārds" in body
    assert "Vecāka e-pasts" in body
    assert "kolonnas" in body
    assert "Sensitīvi dati" in body


def test_safe_template_hides_sensitive_marker(client, reviewer, make_template):
    template = make_template("Hub Safe", columns=("member_full_name",))
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:exports"), {"template": template.pk}
    ).content.decode()
    assert "Sensitīvi dati" not in body


def test_get_selected_page_prechecks_xlsx_format(client, reviewer, make_template):
    template = make_template("Hub Fmt")
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:exports"), {"template": template.pk}
    ).content.decode()
    xlsx_idx = body.index('value="xlsx"')
    assert "checked" in body[xlsx_idx : xlsx_idx + 80], "xlsx must be preselected"
    csv_idx = body.index('value="csv"')
    assert "checked" not in body[csv_idx : csv_idx + 80]


def test_unknown_get_template_is_404(client, reviewer):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:exports"), {"template": 999999})
    assert response.status_code == 404


def test_non_integer_get_template_is_404(client, reviewer):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:exports"), {"template": "abc"})
    assert response.status_code == 404


def test_zero_templates_renders_admin_changelist_link(client, reviewer):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:exports")).content.decode()
    assert "Nav sagatavotu šablonu." in body
    assert "/admin/members/memberexporttemplate/" in body


def test_get_selection_does_not_mutate_or_audit(
    client, reviewer, stored_filter_template, hub_group_a
):
    from apps.members.models import MemberExportTemplate

    client.force_login(reviewer)
    for _ in range(2):
        response = client.get(
            reverse("admin_hub:exports"), {"template": stored_filter_template.pk}
        )
        assert response.status_code == 200
    stored_filter_template.refresh_from_db()
    assert stored_filter_template.agreement_status_filters == ["signed"]
    assert set(
        stored_filter_template.training_groups.values_list("pk", flat=True)
    ) == {hub_group_a.pk}
    assert MemberExportTemplate.objects.count() == 1
    assert AuditEvent.objects.count() == 0, "GET selection must never audit"


# ---------------------------------------------------------------------------
# HubMemberExportRunForm (apps/admin_hub/forms.py)
# ---------------------------------------------------------------------------


def test_run_form_defaults_to_xlsx_when_unbound(make_template):
    from apps.admin_hub.forms import HubMemberExportRunForm

    make_template("Hub Form")
    form = HubMemberExportRunForm()
    assert form["fmt"].value() == "xlsx"


def test_run_form_cleans_empty_filters_to_explicit_empty_lists(make_template):
    """Unselected multi-selects clean to ``[]`` — never ``None``, which the
    service layer reserves for "use stored filters"."""
    from apps.admin_hub.forms import HubMemberExportRunForm

    template = make_template("Hub Form")
    form = HubMemberExportRunForm(
        data={"action": "preview", "template_id": template.pk, "fmt": "xlsx"}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["agreement_states"] == []
    assert form.effective_group_ids == []


def test_run_form_returns_selected_group_ids_in_name_pk_order(
    make_template, hub_group_a, hub_group_b
):
    from apps.admin_hub.forms import HubMemberExportRunForm

    template = make_template("Hub Form")
    form = HubMemberExportRunForm(
        data={
            "action": "preview",
            "template_id": template.pk,
            "fmt": "csv",
            "group_ids": [hub_group_b.pk, hub_group_a.pk],
        }
    )
    assert form.is_valid(), form.errors
    assert form.effective_group_ids == [hub_group_a.pk, hub_group_b.pk]
    assert all(isinstance(pk, int) for pk in form.effective_group_ids)


def test_run_form_rejects_unknown_action_format_state_and_group(make_template):
    from apps.admin_hub.forms import HubMemberExportRunForm

    template = make_template("Hub Form")
    form = HubMemberExportRunForm(
        data={
            "action": "print",
            "template_id": template.pk,
            "fmt": "pdf",
            "agreement_states": ["not_a_state"],
            "group_ids": [999999],
        }
    )
    assert not form.is_valid()
    assert {"action", "fmt", "agreement_states", "group_ids"} <= set(form.errors)
    joined = " ".join(
        str(error) for errors in form.errors.values() for error in errors
    )
    assert "Select a valid choice" not in joined, "errors must be Latvian"
    assert "Enter a valid" not in joined, "errors must be Latvian"
    assert _LATVIAN.search(joined), "field errors must render Latvian messages"


def test_run_form_rejects_duplicate_agreement_states(make_template):
    """Duplicate-state rejection is P17's canonical rule
    (``validate_agreement_status_filters``) — the Hub form must reuse it,
    not a plain choice check that would let duplicates through."""
    from apps.admin_hub.forms import HubMemberExportRunForm

    template = make_template("Hub Form")
    form = HubMemberExportRunForm(
        data={
            "action": "preview",
            "template_id": template.pk,
            "fmt": "xlsx",
            "agreement_states": ["signed", "signed"],
        }
    )
    assert not form.is_valid()
    assert "agreement_states" in form.errors


def test_run_form_choices_reuse_p17_constants(make_template):
    from apps.admin_hub.forms import HubMemberExportRunForm
    from apps.agreements.models import Agreement
    from apps.members.forms import MemberExportRunForm

    form = HubMemberExportRunForm()
    assert list(form.fields["agreement_states"].choices) == list(
        Agreement.State.choices
    )
    assert list(form.fields["fmt"].choices) == list(MemberExportRunForm.FMT_CHOICES)
    assert "column_keys" not in form.fields
    assert not any("column" in name for name in form.fields), (
        "the Hub form must not define columns"
    )


# ---------------------------------------------------------------------------
# POST preview
# ---------------------------------------------------------------------------


def test_preview_replaces_stored_filters(
    client,
    reviewer,
    stored_filter_template,
    hub_group_a,
    hub_group_b,
    hub_filter_members,
    settings,
):
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    client.force_login(reviewer)
    response = _post(
        client,
        {
            "template_id": stored_filter_template.pk,
            "action": "preview",
            "fmt": "xlsx",
            "agreement_states": ["sent"],
            "group_ids": [hub_group_b.pk],
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Sakrit: 1" in body
    assert "Hub Replacement" in body
    assert "Hub Both" not in body

    # Overrides never persist to the template.
    stored_filter_template.refresh_from_db()
    assert stored_filter_template.agreement_status_filters == ["signed"]
    assert set(
        stored_filter_template.training_groups.values_list("pk", flat=True)
    ) == {hub_group_a.pk}
    assert _run_events().count() == 0


def test_preview_empty_filter_removes_that_predicate(
    client, reviewer, stored_filter_template, hub_filter_members, settings
):
    """An unselected multi-select (no POST keys) removes both stored
    predicates — explicit ``[]`` semantics, not stored-value reuse."""
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    client.force_login(reviewer)
    body = _post(
        client,
        {
            "template_id": stored_filter_template.pk,
            "action": "preview",
            "fmt": "xlsx",
        },
    ).content.decode()
    assert "Sakrit: 5" in body
    for name in (
        "Hub Both",
        "Hub StateOnly",
        "Hub GroupOnly",
        "Hub Neither",
        "Hub Replacement",
    ):
        assert name in body


def test_preview_filters_are_and_combined(
    client, reviewer, make_template, hub_group_a, hub_filter_members, settings
):
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    template = make_template("Hub And")
    client.force_login(reviewer)
    body = _post(
        client,
        {
            "template_id": template.pk,
            "action": "preview",
            "fmt": "xlsx",
            "agreement_states": ["signed"],
            "group_ids": [hub_group_a.pk],
        },
    ).content.decode()
    # signed AND group A -> only "Hub Both"; "Hub StateOnly" is signed but
    # group-less, so the AND across predicate sets must exclude it.
    assert "Sakrit: 1" in body
    assert "Hub Both" in body
    assert "Hub StateOnly" not in body


def test_preview_shows_exact_count_and_first_configured_rows(
    client, reviewer, make_template, make_member, settings
):
    settings.EXPORT_PREVIEW_ROW_LIMIT = 2
    template = make_template("Hub Cap")
    names = ("Hub Cap Alpha", "Hub Cap Beta", "Hub Cap Gamma")
    for name in names:
        make_member(name)
    client.force_login(reviewer)
    body = _post(
        client,
        {"template_id": template.pk, "action": "preview", "fmt": "xlsx"},
    ).content.decode()
    # Exact total count, capped rows (which two depends on DB order).
    assert "Sakrit: 3" in body
    assert sum(1 for name in names if name in body) == 2
    assert "Rādīti pirmie 2 no 3" in body


def test_preview_uses_selected_template_column_order_and_labels(
    client, reviewer, make_template, make_member, settings
):
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    template = make_template(
        "Hub Columns", columns=("guardian_name", "member_full_name")
    )
    make_member("Hub Col Kid")
    client.force_login(reviewer)
    body = _post(
        client,
        {"template_id": template.pk, "action": "preview", "fmt": "xlsx"},
    ).content.decode()
    table = body.split("data-export-table", 1)[1]
    assert "Vecāka vārds, uzvārds" in table
    assert "Biedra vārds, uzvārds" in table
    assert table.index("Vecāka vārds, uzvārds") < table.index(
        "Biedra vārds, uzvārds"
    )
    assert "Hub Col Kid" in table


def test_preview_emits_no_audit_event(client, reviewer, make_template, make_member):
    template = make_template("Hub Silent")
    make_member("Hub Silent Kid")
    client.force_login(reviewer)
    response = _post(
        client,
        {"template_id": template.pk, "action": "preview", "fmt": "xlsx"},
    )
    assert response.status_code == 200
    assert AuditEvent.objects.count() == 0, "preview must never audit"


def test_zero_result_preview_shows_empty_state(
    client, reviewer, make_template, make_member
):
    template = make_template("Hub ZeroP", states=["signed"])
    make_member("Hub Unsigned Kid", state="generated")
    client.force_login(reviewer)
    body = _post(
        client,
        {
            "template_id": template.pk,
            "action": "preview",
            "fmt": "xlsx",
            "agreement_states": ["signed"],
        },
    ).content.decode()
    assert "Sakrit: 0" in body
    assert "Nav biedru" in body


def test_preview_does_not_query_per_member(
    client, reviewer, make_template, make_member, settings
):
    """Reader loop must ride the P17 prefetched queryset: rendering five more
    matching rows adds at most a constant number of queries (a per-member
    reader query would add five times that)."""
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    template = make_template("Hub N1", states=["void"])
    client.force_login(reviewer)
    data = {"template_id": template.pk, "action": "preview", "fmt": "xlsx"}
    with CaptureQueriesContext(connection) as empty_run:
        response = _post(client, data)
    assert response.status_code == 200
    assert "Sakrit: 0" in response.content.decode()

    for i in range(5):
        make_member(f"Hub N1 Kid {i}", state="void")

    with CaptureQueriesContext(connection) as full_run:
        response = _post(client, data)
    assert response.status_code == 200
    assert "Sakrit: 5" in response.content.decode()
    assert len(full_run.captured_queries) - len(empty_run.captured_queries) <= 2


# ---------------------------------------------------------------------------
# POST download
# ---------------------------------------------------------------------------


def test_download_xlsx_audits_effective_metadata(
    client,
    reviewer,
    make_template,
    make_member,
    hub_group_a,
    hub_group_b,
):
    template = make_template(
        "Hub Audit",
        columns=("member_full_name", "guardian_email"),
        states=["void"],
        groups=(hub_group_b,),
    )
    make_member("Hub Audit Kid", group=hub_group_a, state="signed")
    client.force_login(reviewer)
    response = _post(
        client,
        {
            "template_id": template.pk,
            "action": "download",
            "fmt": "xlsx",
            "agreement_states": ["signed"],
            "group_ids": [hub_group_a.pk],
        },
    )
    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    events = _run_events()
    assert events.count() == 1, "download must audit exactly once"
    # Effective (overridden) filters, not the template's stored ones.
    assert events.first().metadata == {
        "template_id": template.pk,
        "column_keys": ["member_full_name", "guardian_email"],
        "agreement_status_filters": ["signed"],
        "training_group_ids": [hub_group_a.pk],
        "row_count": 1,
        "format": "xlsx",
        "sensitive": True,
    }


def test_download_defaults_to_xlsx_when_fmt_omitted(
    client, reviewer, make_template, make_member
):
    template = make_template("Hub Def")
    make_member("Hub Def Kid")
    client.force_login(reviewer)
    response = _post(
        client, {"template_id": template.pk, "action": "download"}
    )
    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    disposition = response["Content-Disposition"]
    assert "attachment" in disposition
    assert f"member-export-{template.pk}" in disposition
    audit = _run_events().first()
    assert audit is not None
    assert audit.metadata["format"] == "xlsx"


def test_download_csv_returns_same_rows_as_preview(
    client, reviewer, make_template, make_member, settings
):
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    template = make_template("Hub Parity", columns=("member_full_name",))
    names = {"Hub Parity One", "Hub Parity Two", "Hub Parity Three"}
    for name in names:
        make_member(name)
    client.force_login(reviewer)
    base = {"template_id": template.pk}

    preview_body = _post(
        client, {**base, "action": "preview", "fmt": "csv"}
    ).content.decode()
    assert "Sakrit: 3" in preview_body
    for name in names:
        assert name in preview_body

    response = _post(client, {**base, "action": "download", "fmt": "csv"})
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment" in response["Content-Disposition"]
    rows = list(
        csv.reader(
            io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"
        )
    )
    assert rows[0] == ["Biedra vārds, uzvārds"]
    assert {row[0] for row in rows[1:]} == names
    assert _run_events().first().metadata["row_count"] == 3


def test_zero_result_download_returns_headers_only_and_audits_zero(
    client, reviewer, make_template, make_member
):
    template = make_template(
        "Hub ZeroD", columns=("member_full_name", "training_group_name"),
        states=["signed"],
    )
    make_member("Hub Zero Unsigned", state="generated")
    client.force_login(reviewer)
    response = _post(
        client,
        {
            "template_id": template.pk,
            "action": "download",
            "fmt": "csv",
            "agreement_states": ["signed"],
        },
    )
    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    rows = list(
        csv.reader(
            io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"
        )
    )
    assert rows == [["Biedra vārds, uzvārds", "Treniņu grupa"]]
    audit = _run_events().first()
    assert audit.metadata["row_count"] == 0


def test_active_staff_can_download_sensitive_template(
    client, reviewer, make_template, make_member
):
    """Any active staff (not only superusers) may run sensitive templates —
    matching the P17 posture."""
    assert reviewer.is_staff and reviewer.is_active
    assert not reviewer.is_superuser
    template = make_template(
        "Hub Sensitive",
        columns=("member_full_name", "guardian_email", "member_personal_id"),
    )
    make_member("Hub Sens Kid", personal_id="333333-33333")
    client.force_login(reviewer)
    response = _post(
        client,
        {"template_id": template.pk, "action": "download", "fmt": "csv"},
    )
    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    assert _run_events().first().metadata["sensitive"] is True


def test_download_audit_metadata_is_structural_only(
    client, reviewer, make_template, make_member, export_guardian, hub_group_a
):
    template = make_template(
        "SENTINEL-HUB-TEMPLATE",
        columns=("member_full_name", "guardian_email", "member_personal_id"),
        states=["signed"],
        groups=(hub_group_a,),
    )
    make_member(
        "Hub Sentinel Child",
        group=hub_group_a,
        state="signed",
        personal_id="222222-22222",
    )
    client.force_login(reviewer)
    _post(
        client,
        {
            "template_id": template.pk,
            "action": "download",
            "fmt": "csv",
            "agreement_states": ["signed"],
            "group_ids": [hub_group_a.pk],
        },
    )
    assert _run_events().count() == 1
    audit = _run_events().first()
    assert set(audit.metadata.keys()) == {
        "template_id",
        "column_keys",
        "agreement_status_filters",
        "training_group_ids",
        "row_count",
        "format",
        "sensitive",
    }
    assert audit.target_type == "member_export_template"
    assert audit.target_repr == "Member export template"
    assert str(audit.target_id) == str(template.pk)

    serialized = (
        str(audit.metadata) + audit.target_repr + str(audit.target_id) + audit.target_type
    )
    for sentinel in (
        "SENTINEL-HUB-TEMPLATE",
        "Hub Sentinel Child",
        "222222-22222",
        export_guardian.email,
        export_guardian.address,
    ):
        assert sentinel not in serialized, sentinel


def test_download_audit_group_ids_are_ascending_numeric(
    client, reviewer, make_template
):
    """MINOR review fix (2026-09-11): the runner's ``effective_group_ids``
    keeps the form's ``(name, pk)`` display order, so a name-first audit
    record would not be deterministic across renames. The audit must store
    ascending numeric PKs."""
    from apps.members.models import TrainingGroup

    # Name order and PK order deliberately disagree: "ZZ" sorts last by
    # name but was created first (lower pk).
    late_named = TrainingGroup.objects.create(name="ZZ Beznīgs", is_active=True)
    early_named = TrainingGroup.objects.create(name="AA Beznīgs", is_active=True)
    assert late_named.pk < early_named.pk
    template = make_template(
        "Hub Order", columns=("member_full_name",), groups=(late_named, early_named)
    )
    client.force_login(reviewer)
    response = _post(
        client,
        {
            "template_id": template.pk,
            "action": "download",
            "fmt": "csv",
            "group_ids": [early_named.pk, late_named.pk],
        },
    )
    assert response.status_code == 200
    audit = _run_events().first()
    assert audit.metadata["training_group_ids"] == [late_named.pk, early_named.pk]
    assert audit.metadata["training_group_ids"] == sorted(
        [early_named.pk, late_named.pk]
    )


# ---------------------------------------------------------------------------
# POST error handling
# ---------------------------------------------------------------------------


def test_invalid_post_action_format_state_or_group_has_error_and_no_audit(
    client, reviewer, stored_filter_template
):
    client.force_login(reviewer)
    response = _post(
        client,
        {
            "template_id": stored_filter_template.pk,
            "action": "print",
            "fmt": "pdf",
            "agreement_states": ["not_a_state"],
            "group_ids": [999999],
        },
    )
    assert response.status_code == 200
    assert not response.has_header("Content-Disposition"), "no output on invalid POST"
    body = response.content.decode()
    assert "errorlist" in body, "field errors must be rendered on the page"
    assert _run_events().count() == 0
    assert AuditEvent.objects.count() == 0


def test_invalid_post_keeps_sensitive_template_metadata_visible(
    client, reviewer, make_template, hub_group_a
):
    """MINOR review fix (2026-09-11): an invalid POST re-render resolves the
    selected template for display — it must carry the same presentation
    annotation as every other render path, so the column labels, column
    count, and ``data-export-sensitive`` marker stay visible beside the
    errors instead of silently degrading to a chooser-only page."""
    template = make_template(
        "Hub InvalidMeta",
        columns=("member_full_name", "guardian_email"),
        states=["signed"],
        groups=(hub_group_a,),
    )
    client.force_login(reviewer)
    response = _post(
        client,
        {
            "template_id": template.pk,
            "action": "print",
            "fmt": "pdf",
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "errorlist" in body
    assert "Hub InvalidMeta" in body
    assert "Biedra vārds, uzvārds" in body, "column labels must survive the re-render"
    assert "Vecāka e-pasts" in body
    assert "kolonnas" in body, "column count metadata must survive the re-render"
    assert "data-export-sensitive" in body, (
        "the sensitive marker must remain rendered for the selected template"
    )
    assert _run_events().count() == 0


def test_corrupted_template_refuses_preview_and_download(
    client, reviewer, make_template
):
    from apps.members.models import MemberExportTemplate

    template = make_template("Hub Corrupt")
    # Bypass model validation to persist an invalid column key.
    MemberExportTemplate.objects.filter(pk=template.pk).update(
        column_keys=["invalid_key"]
    )
    client.force_login(reviewer)
    for action in ("preview", "download"):
        response = _post(
            client,
            {"template_id": template.pk, "action": action, "fmt": "csv"},
        )
        assert response.status_code == 200
        assert not response.has_header("Content-Disposition"), action
        body = response.content.decode()
        assert "Šablons ir nederīgs" in body, action
        assert "/admin/members/memberexporttemplate/" in body, (
            "corrupted template must link staff to the admin repair surface"
        )
    assert _run_events().count() == 0
    assert AuditEvent.objects.count() == 0


def test_unknown_post_template_id_is_404(client, reviewer):
    client.force_login(reviewer)
    response = _post(
        client,
        {"template_id": 999999, "action": "download", "fmt": "xlsx"},
    )
    assert response.status_code == 404
    assert _run_events().count() == 0


# ---------------------------------------------------------------------------
# Stable presentation hooks
# ---------------------------------------------------------------------------


def test_page_renders_stable_data_hooks(
    client, reviewer, make_template, make_member, settings
):
    settings.EXPORT_PREVIEW_ROW_LIMIT = 20
    template = make_template(
        "Hub Hooks", columns=("member_full_name", "guardian_email")
    )
    make_member("Hub Hook Kid")
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:exports"), {"template": template.pk}
    ).content.decode()
    assert "data-export-template-list" in body
    assert "data-export-sensitive" in body

    preview_body = _post(
        client,
        {"template_id": template.pk, "action": "preview", "fmt": "xlsx"},
    ).content.decode()
    assert "data-export-preview" in preview_body
    assert "data-export-table" in preview_body
