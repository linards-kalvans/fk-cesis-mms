"""P17 — member export template admin: permissions, run page, audit metadata.

Describes the desired admin surface (``MemberExportTemplateAdmin``, its run
endpoint, and audit metadata) that does not exist yet.
"""

import json

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.core.models import AuditEvent

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def member_export_template(db):
    from apps.members.models import MemberExportTemplate

    return MemberExportTemplate.objects.create(
        name="Test template", column_keys=["member_full_name"]
    )


def _regular_staff_client():
    User.objects.create_user(
        username="regular", password="pw", is_staff=True, is_active=True
    )
    client = Client()
    client.login(username="regular", password="pw")
    return client


# ---------------------------------------------------------------------------
# Registration + permissions
# ---------------------------------------------------------------------------


def test_template_admin_registers_model():
    from django.contrib import admin

    from apps.members.admin import MemberExportTemplateAdmin
    from apps.members.models import MemberExportTemplate

    assert admin.site.is_registered(MemberExportTemplate)
    registered = admin.site._registry.get(MemberExportTemplate)
    assert isinstance(registered, MemberExportTemplateAdmin)


def test_template_has_no_file_or_output_field():
    from django.db.models import FileField

    from apps.members.models import MemberExportTemplate

    fields = MemberExportTemplate._meta.get_fields()
    # The template stores configuration only; the export is generated in
    # memory and returned directly, never persisted to a file/output field.
    assert not any(isinstance(f, FileField) for f in fields)
    names = {f.name for f in fields}
    for banned in ("output", "file", "export_file", "result", "stored_output"):
        assert banned not in names


def test_template_admin_has_staff_only_permissions(member_export_template, staff_client):
    response = staff_client.get(
        reverse(
            "admin:members_memberexporttemplate_change",
            args=[member_export_template.pk],
        )
    )
    assert response.status_code == 200


def test_anonymous_get_redirects_to_login(member_export_template):
    response = Client().get(
        reverse(
            "admin:members_memberexporttemplate_change",
            args=[member_export_template.pk],
        )
    )
    assert response.status_code == 302


def test_authenticated_non_staff_redirects_to_login(member_export_template, client):
    non_staff = User.objects.create_user(
        username="nonstaff", password="pass", is_staff=False, is_active=True
    )
    client.force_login(non_staff)
    response = client.get(
        reverse(
            "admin:members_memberexporttemplate_change",
            args=[member_export_template.pk],
        )
    )
    assert response.status_code == 302


def test_valid_template_creation_redirects(staff_client):
    response = staff_client.post(
        reverse("admin:members_memberexporttemplate_add"),
        {
            "name": "Valid",
            "column_keys": '["member_full_name"]',
            "agreement_status_filters": [],
        },
    )
    assert response.status_code == 302


def test_regular_staff_can_reach_add_change_delete(member_export_template):
    client = _regular_staff_client()
    assert (
        client.get(reverse("admin:members_memberexporttemplate_add")).status_code == 200
    )
    assert (
        client.get(
            reverse(
                "admin:members_memberexporttemplate_change",
                args=[member_export_template.pk],
            )
        ).status_code
        == 200
    )
    assert (
        client.get(
            reverse(
                "admin:members_memberexporttemplate_delete",
                args=[member_export_template.pk],
            )
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Run page
# ---------------------------------------------------------------------------


def test_change_form_has_export_link(member_export_template, staff_client):
    url = reverse(
        "admin:members_memberexporttemplate_change",
        args=[member_export_template.pk],
    )
    response = staff_client.get(url)
    assert response.status_code == 200
    run_url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    assert run_url in response.content.decode()


def test_add_page_has_no_export_link(staff_client):
    url = reverse("admin:members_memberexporttemplate_add")
    response = staff_client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    # The export action (and its run URL) only exist for an existing object.
    assert "Eksportēt" not in content
    assert "/run/" not in content


def test_run_page_xlsx_preselected(member_export_template, staff_client):
    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    response = staff_client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    assert 'value="xlsx"' in content
    assert "checked" in content


def test_run_page_csrf_protected(member_export_template):
    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    client = Client(enforce_csrf_checks=True)
    staff = User.objects.create_user(
        username="csrf-staff", password="pass", is_staff=True, is_active=True
    )
    client.force_login(staff)
    response = client.post(url, {"fmt": "xlsx"})
    assert response.status_code == 403


def test_run_page_missing_template_404(staff_client):
    url = reverse("admin:members_memberexporttemplate_run", args=[999999])
    response = staff_client.get(url)
    assert response.status_code == 404


def test_run_page_invalid_format_no_download(member_export_template, staff_client):
    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    response = staff_client.post(url, {"fmt": "invalid"})
    assert response.status_code == 200
    assert not response.has_header("Content-Disposition")
    assert "errorlist" in response.content.decode()


def test_run_page_rejects_persisted_invalid_template(
    member_export_template, staff_client
):
    from apps.members.models import MemberExportTemplate

    # Persist an invalid column key by bypassing model validation, so a
    # defensive run view must reject it rather than crash or download.
    MemberExportTemplate.objects.filter(pk=member_export_template.pk).update(
        column_keys=["invalid_key"]
    )

    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    response = staff_client.post(url, {"fmt": "csv"})

    assert response.status_code == 200
    assert not response.has_header("Content-Disposition")
    assert not AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_RUN)
    ).exists()


def test_run_is_direct_output_no_retention(member_export_template, staff_client, member):
    from apps.members.models import MemberExportTemplate

    before = MemberExportTemplate.objects.count()

    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    response = staff_client.post(url, {"fmt": "csv"})

    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]
    # Direct download: running must not persist any export-output row.
    assert MemberExportTemplate.objects.count() == before


def test_run_page_exports_xlsx(member_export_template, staff_client, member):
    member_export_template.column_keys = ["member_full_name", "guardian_name"]
    member_export_template.save()

    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    response = staff_client.post(url, {"fmt": "xlsx"})

    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in response["Content-Disposition"]


def test_run_page_exports_csv(member_export_template, staff_client, member):
    member_export_template.column_keys = ["member_full_name"]
    member_export_template.save()

    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    response = staff_client.post(url, {"fmt": "csv"})

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment" in response["Content-Disposition"]
    assert response.content[:3] == b"\xef\xbb\xbf"


def test_regular_staff_creates_and_runs_sensitive_template(member):
    from apps.members.models import MemberExportTemplate

    client = _regular_staff_client()
    staff = User.objects.get(username="regular")

    # Regular non-superuser staff creates the template through the admin add
    # flow (not ORM), with a sensitive column.
    response = client.post(
        reverse("admin:members_memberexporttemplate_add"),
        {
            "name": "Sensitive",
            "column_keys": '["member_full_name", "guardian_email", "guardian_phone"]',
            "agreement_status_filters": [],
        },
    )
    assert response.status_code == 302

    template = MemberExportTemplate.objects.get(name="Sensitive")
    assert template.created_by == staff

    url = reverse("admin:members_memberexporttemplate_run", args=[template.pk])
    response = client.post(url, {"fmt": "xlsx"})
    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]


# ---------------------------------------------------------------------------
# Audit metadata + redaction
# ---------------------------------------------------------------------------


def test_audit_on_template_create(staff_client):
    response = staff_client.post(
        reverse("admin:members_memberexporttemplate_add"),
        {
            "name": "Test template",
            "column_keys": '["member_full_name"]',
            "agreement_status_filters": [],
        },
    )
    assert response.status_code in (302, 200)

    audit = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_TEMPLATE_MUTATED),
    ).order_by("-created_at").first()
    assert audit is not None
    assert audit.metadata["operation"] == "create"
    assert set(audit.metadata.keys()) == {"template_id", "operation"}
    assert audit.target_type == "member_export_template"
    assert audit.target_repr == "Member export template"
    assert str(audit.target_id).isdigit()
    assert "Test template" not in audit.target_repr


def test_audit_on_template_delete(staff_client, member_export_template):
    staff_client.post(
        reverse(
            "admin:members_memberexporttemplate_delete",
            args=[member_export_template.pk],
        ),
        {"post": "yes"},
    )

    audit = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_TEMPLATE_MUTATED),
        metadata__operation="delete",
    ).first()
    assert audit is not None
    assert audit.metadata["template_id"] == member_export_template.pk
    assert set(audit.metadata.keys()) == {"template_id", "operation"}
    assert audit.target_type == "member_export_template"
    assert audit.target_repr == "Member export template"
    assert str(audit.target_id) == str(member_export_template.pk)
    assert str(audit.target_id).isdigit()


def test_audit_on_effective_edit(staff_client, member_export_template):
    staff_client.post(
        reverse(
            "admin:members_memberexporttemplate_change",
            args=[member_export_template.pk],
        ),
        {
            "name": member_export_template.name,
            "column_keys": '["member_full_name", "guardian_email"]',
            "agreement_status_filters": [],
            "training_groups": [],
        },
        follow=True,
    )

    audit = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_TEMPLATE_MUTATED),
        metadata__operation="edit",
    ).first()
    assert audit is not None
    assert audit.metadata["template_id"] == member_export_template.pk
    assert set(audit.metadata.keys()) == {"template_id", "operation"}
    assert audit.target_type == "member_export_template"
    assert audit.target_repr == "Member export template"
    assert str(audit.target_id) == str(member_export_template.pk)
    assert str(audit.target_id).isdigit()


def test_noop_edit_emits_no_audit(staff_client, member_export_template):
    action = str(AuditEvent.Action.MEMBER_EXPORT_TEMPLATE_MUTATED)
    before = AuditEvent.objects.filter(action=action).count()

    staff_client.post(
        reverse(
            "admin:members_memberexporttemplate_change",
            args=[member_export_template.pk],
        ),
        {
            "name": member_export_template.name,
            "column_keys": json.dumps(member_export_template.column_keys),
            "agreement_status_filters": member_export_template.agreement_status_filters,
            "training_groups": [],
        },
        follow=True,
    )

    assert AuditEvent.objects.filter(action=action).count() == before


def test_audit_on_bulk_delete(member_export_template):
    from apps.members.admin import MemberExportTemplateAdmin
    from apps.members.models import MemberExportTemplate

    User.objects.create_superuser("bulkstaff", "b@example.com", "pw")
    req = RequestFactory().post("/admin/")
    req.user = User.objects.get(username="bulkstaff")
    req.session = {}

    admin_obj = MemberExportTemplateAdmin(MemberExportTemplate, AdminSite())
    admin_obj.delete_queryset(req, MemberExportTemplate.objects.all())

    events = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_TEMPLATE_MUTATED),
        metadata__operation="delete",
    )
    assert events.count() == 1
    event = events.first()
    assert event.metadata["template_id"] == member_export_template.pk
    assert set(event.metadata.keys()) == {"template_id", "operation"}
    assert event.target_type == "member_export_template"
    assert event.target_repr == "Member export template"
    assert str(event.target_id) == str(member_export_template.pk)
    assert str(event.target_id).isdigit()


def test_run_audit_metadata(member_export_template, staff_client, member):
    member_export_template.column_keys = ["member_full_name", "guardian_email"]
    member_export_template.save()

    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    staff_client.post(url, {"fmt": "xlsx"})

    audit = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_RUN),
    ).order_by("-created_at").first()
    assert audit is not None
    assert set(audit.metadata.keys()) == {
        "template_id",
        "column_keys",
        "agreement_status_filters",
        "training_group_ids",
        "row_count",
        "format",
        "sensitive",
    }
    assert audit.metadata["format"] == "xlsx"
    assert audit.metadata["sensitive"] is True
    assert audit.target_type == "member_export_template"
    assert audit.target_repr == "Member export template"
    assert str(audit.target_id).isdigit()


def test_run_audit_omits_pii_and_data(member_export_template, staff_client, member):
    from apps.members.models import Member

    member_export_template.name = "SENTINEL-TEMPLATE-NAME"
    member_export_template.column_keys = [
        "member_full_name",
        "guardian_email",
        "member_personal_id",
        "guardian_address",
    ]
    member_export_template.save()

    Member.objects.create(
        full_name="=EVIL()", personal_id="999999-99999", guardian=member.guardian
    )

    url = reverse(
        "admin:members_memberexporttemplate_run", args=[member_export_template.pk]
    )
    staff_client.post(url, {"fmt": "csv"})

    audit = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.MEMBER_EXPORT_RUN),
    ).order_by("-created_at").first()
    assert audit is not None

    # Exact required metadata key set — nothing extra.
    assert set(audit.metadata.keys()) == {
        "template_id",
        "column_keys",
        "agreement_status_filters",
        "training_group_ids",
        "row_count",
        "format",
        "sensitive",
    }

    # Generic target — never the template name or member data.
    assert audit.target_type == "member_export_template"
    assert audit.target_repr == "Member export template"

    serialized = (
        str(audit.metadata)
        + audit.target_repr
        + audit.target_id
        + audit.target_type
    )
    for sentinel in [
        "SENTINEL-TEMPLATE-NAME",
        member.full_name,
        member.personal_id,
        member.guardian.email,
        member.guardian.address,
        "=EVIL()",
        str(b"=EVIL()"),  # "b'=EVIL()'" — reject any bytes representation too
    ]:
        assert sentinel not in serialized, sentinel
