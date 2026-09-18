"""P23 — parent-flow endpoints and surfaces for MedicalPermit.

Registrations namespace routes covered here:
- ``registrations:application-medical-permit-upload``  — POST, ownership-scoped,
  allowed on draft/fix_requested/submitted/approved applications only;
  rejected applications return 404 even for the owning parent.
- ``registrations:member-medical-permit-upload``       — POST, guardian owner only;
  stays available after approval regardless of agreement state (signed included).
- ``registrations:medical-permit-preview`` / ``-download`` — GET, guardian only;
  streaming + denial matrix live in ``test_medical_permit_access.py``.

Surface contract: the application workspace renders the upload form for every
allowed status — application-endpoint action before approval, member-endpoint
action once the application has an approved member (so a signed agreement
never blocks upload). The portal renders the permit block + upload control for
every allowed status and nothing for rejected applications; it also shows
per-approved-child permit status, an August-starting expiry warning, and — for
a confirmation-only permit — no file links.

An upload never sends email — proven by behaviour (outbox assertions around
real POSTs), not by source scanning.

Model/service imports live inside test bodies (the file's established
convention since its red-phase origin).
"""

from __future__ import annotations

import datetime

import pytest

pytestmark = pytest.mark.django_db


def _upload(name="permit.pdf", content_type="application/pdf"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name=name, content=b"%PDF-1.4 flow", content_type=content_type
    )


def _freeze(monkeypatch, year, month, day):
    import django.utils.timezone as timezone_module

    def _localdate():
        return datetime.date(year, month, day)

    monkeypatch.setattr(timezone_module, "localdate", _localdate)


def _app_for(account, *, status="draft", member_name="Flow Child"):
    from apps.registrations.models import RegistrationApplication

    return RegistrationApplication.objects.create(
        parent_account=account,
        claimed_email=account.email,
        status=status,
        member_full_name=member_name,
    )


def _permit(app, *, with_file=True, confirmed=False, member=None,
            valid_until=datetime.date(2026, 9, 30)):
    from django.contrib.auth.models import User

    from apps.documents.models import MedicalPermit

    kwargs = dict(
        application=app,
        source=MedicalPermit.Source.PARENT_UPLOAD,
        valid_until=valid_until,
    )
    if with_file:
        kwargs.update(
            file=_upload(),
            original_filename="permit.pdf",
            content_type="application/pdf",
            file_size=15,
        )
    if confirmed:
        staff = User.objects.create_user(username="flow-confirmer")
        kwargs.update(
            confirmed_by=staff,
            confirmed_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc),
        )
    if member is not None:
        kwargs["member"] = member
    return MedicalPermit.objects.create(**kwargs)


def _approve(app):
    from django.contrib.auth.models import User

    from apps.registrations.services import approve_application

    return approve_application(app, User.objects.create_user(username="flow-approver"))


def _approved_family(parent_account, make_guardian):
    """Guardian + submitted application + permit; returns (app, member, permit)
    after real approval attachment runs."""
    guardian = make_guardian(parent_account, full_name="Flow Guardian")
    app = _app_for(parent_account, status="submitted")
    app.guardian = guardian
    app.save(update_fields=["guardian"])
    permit = _permit(app)
    member = _approve(app).approved_member
    permit.refresh_from_db()
    return app, member, permit


def _signed_family(parent_account, make_guardian):
    """Approved family whose agreement has been taken to SIGNED through the
    real service path; returns (app, member, agreement).

    ``mark_agreement_signed`` (P9/P15) refuses to mutate state without an
    active ``billing_plan`` + a season-year ``first_billing_month`` — the plan
    is created here so the signed transition succeeds legitimately."""
    from decimal import Decimal

    from django.contrib.auth.models import User

    from apps.agreements.services import get_current_agreement, mark_agreement_signed
    from apps.billing.models import MembershipPlan

    app, member, _permit = _approved_family(parent_account, make_guardian)
    plan = MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
        is_default=True,
        billing_start_cutoff_day=20,
    )
    agreement = get_current_agreement(member)
    agreement.billing_plan = plan
    agreement.first_billing_month = "2026-09"
    agreement.save(update_fields=["billing_plan", "first_billing_month"])
    mark_agreement_signed(
        agreement, User.objects.create_user(username="flow-signer")
    )
    agreement.refresh_from_db()
    # Setup self-check — fails loudly if the fixture path ever breaks.
    assert agreement.state == "signed"
    return app, member, agreement


# ---------------------------------------------------------------------------
# application-medical-permit-upload
# ---------------------------------------------------------------------------


class TestApplicationPermitUpload:
    def test_owner_can_upload_on_draft(
        self, monkeypatch, verified_client, parent_account
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 1, 15)
        app = _app_for(parent_account)
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 201
        permit = app.medical_permit
        assert permit.source == "parent_upload"
        assert permit.file != ""
        # Recorded in 2026 → valid through 30 September 2027.
        assert permit.valid_until == datetime.date(2027, 9, 30)

    def test_owner_can_upload_on_submitted(self, verified_client, parent_account):
        """No submit gate: a submitted application still accepts an upload."""
        from django.urls import reverse

        app = _app_for(parent_account, status="submitted")
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 201
        app.refresh_from_db()
        assert app.status == "submitted"

    def test_cross_family_upload_refused(self, other_verified_client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account)
        response = other_verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 404

    def test_anonymous_upload_refused(self, client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account)
        response = client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code in (302, 404)
        assert response.status_code != 201

    def test_workspace_renders_upload_control(self, verified_client, parent_account):
        """The parent workspace for an editable draft shows the upload control."""
        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            in html
        )


# ---------------------------------------------------------------------------
# member-medical-permit-upload
# ---------------------------------------------------------------------------


class TestMemberPermitUpload:
    def test_guardian_owner_can_replace_member_permit(
        self, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _app, member, permit = _approved_family(parent_account, make_guardian)
        old_name = permit.file.name

        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("replacement.pdf")},
        )

        assert response.status_code == 201
        permit.refresh_from_db()
        assert permit.file.name != old_name
        assert permit.original_filename == "replacement.pdf"
        assert permit.member_id == member.pk
        assert permit.application_id == _app.pk  # traceability retained

    def test_cross_family_member_upload_refused(
        self, other_verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _app, member, _permit = _approved_family(parent_account, make_guardian)
        response = other_verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 404

    def test_anonymous_member_upload_refused(self, client, parent_account, make_guardian):
        from django.urls import reverse

        _app, member, _permit = _approved_family(parent_account, make_guardian)
        response = client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload()},
        )

        assert response.status_code in (302, 404)
        assert response.status_code != 201

    def test_guardian_can_upload_first_permit_after_approval(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        """An approved child may have no permit (approval never requires one);
        the owning parent can still upload the first permit via the member
        route — a new record linked to both the source application and the
        approved member."""
        from django.urls import reverse

        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 3, 10)
        guardian = make_guardian(parent_account, full_name="Flow Guardian")
        app = _app_for(parent_account, status="submitted")
        app.guardian = guardian
        app.save(update_fields=["guardian"])
        member = _approve(app).approved_member
        assert not MedicalPermit.objects.filter(member=member).exists()

        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("first.pdf")},
        )

        assert response.status_code == 201
        permit = MedicalPermit.objects.get(member=member)
        assert permit.application_id == app.pk  # traceability retained
        assert permit.source == "parent_upload"
        # Uploaded in 2026 → valid through 30 September 2027.
        assert permit.valid_until == datetime.date(2027, 9, 30)

    def test_application_endpoint_upload_then_member_replacement(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        """Approved app: the application endpoint stays status-allowed, so its
        created permit must carry the approved member — otherwise the normal
        member-endpoint replacement creates a SECOND row for the same source
        application and violates the OneToOne(application) constraint."""
        from django.urls import reverse

        from apps.documents.models import MedicalPermit

        _freeze(monkeypatch, 2026, 3, 10)
        guardian = make_guardian(parent_account, full_name="Flow Guardian")
        app = _app_for(parent_account, status="submitted")
        app.guardian = guardian
        app.save(update_fields=["guardian"])
        member = _approve(app).approved_member
        assert not MedicalPermit.objects.filter(member=member).exists()

        # The endpoint allowlist permits application-uploads while approved.
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload("crafted.pdf")},
        )
        assert response.status_code == 201
        permit = MedicalPermit.objects.get(application=app)
        assert permit.member_id == member.pk  # linked, not application-only

        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("replacement.pdf")},
        )
        assert response.status_code == 201  # IntegrityError here pre-fix
        permit.refresh_from_db()
        assert permit.original_filename == "replacement.pdf"
        assert permit.member_id == member.pk
        assert MedicalPermit.objects.filter(application=app).count() == 1


# ---------------------------------------------------------------------------
# Portal surface: status, warning, confirmation-only, upload control
# ---------------------------------------------------------------------------


class TestPortalSurface:
    def test_portal_shows_permit_status_for_approved_child(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 8, 1)
        _app, member, _permit = _approved_family(parent_account, make_guardian)

        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        # 2026-08-01 with valid_until 2026-09-30 → expiring.
        assert 'data-medical-permit-status="expiring"' in html
        # The approved child's portal card offers the member upload control.
        assert (
            reverse("registrations:member-medical-permit-upload", args=[member.pk])
            in html
        )

    def test_portal_has_no_warning_before_august(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 7, 31)
        _app, _member, _permit = _approved_family(parent_account, make_guardian)

        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode()
        assert "data-medical-permit-warning" not in html

    def test_portal_warning_begins_on_first_august(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _freeze(monkeypatch, 2026, 8, 1)
        _app, _member, _permit = _approved_family(parent_account, make_guardian)

        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode()
        assert "data-medical-permit-warning" in html

    def test_confirmation_only_portal_shows_state_without_file_links(
        self, monkeypatch, verified_client, parent_account, make_guardian
    ):
        from django.contrib.auth.models import User

        from django.urls import reverse

        from apps.documents.medical_permits import confirm_medical_permit

        _freeze(monkeypatch, 2026, 8, 1)
        _app, member, permit = _approved_family(parent_account, make_guardian)
        confirm_medical_permit(
            permit, actor=User.objects.create_user(username="portal-confirmer")
        )
        assert permit.file == ""
        # Confirmed in 2026 → valid through 30 September 2027, so on 2026-08-01
        # the permit is current and no expiry warning shows.
        assert permit.valid_until == datetime.date(2027, 9, 30)

        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert 'data-medical-permit-status="current"' in html
        assert "data-medical-permit-warning" not in html
        # Confirmation-only: no preview/download file links anywhere on the page.
        assert reverse("registrations:medical-permit-preview", args=[permit.pk]) not in html
        assert reverse("registrations:medical-permit-download", args=[permit.pk]) not in html


# ---------------------------------------------------------------------------
# Status-scoped upload surfaces — allowed statuses render the form on BOTH
# parent surfaces; the endpoint is gated by the same status set.
# ---------------------------------------------------------------------------


class TestPermitUploadAllowedStatuses:
    @pytest.mark.parametrize("status", ["fix_requested", "submitted"])
    def test_workspace_renders_application_upload_form(
        self, verified_client, parent_account, status
    ):
        """Non-editable-but-allowed statuses still get the upload form on the
        application workspace, wired to the application endpoint."""
        from django.urls import reverse

        app = _app_for(parent_account, status=status)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            in html
        )

    @pytest.mark.parametrize("status", ["draft", "fix_requested", "submitted"])
    def test_portal_renders_application_upload_form(
        self, verified_client, parent_account, status
    ):
        """Pre-approval statuses get the permit upload control on the portal
        card, wired to the application endpoint."""
        from django.urls import reverse

        app = _app_for(parent_account, status=status)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            in html
        )


# ---------------------------------------------------------------------------
# Rejected applications — no upload controls, endpoint 404 for the owner.
# ---------------------------------------------------------------------------


class TestRejectedPermitUploadBlocked:
    def test_workspace_renders_no_upload_form(self, verified_client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account, status="rejected")
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            not in html
        )

    def test_portal_renders_no_upload_form(self, verified_client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account, status="rejected")
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            not in html
        )

    def test_owner_upload_post_returns_404(self, verified_client, parent_account):
        """Even the owning verified parent gets 404 on a rejected app."""
        from django.urls import reverse

        from apps.documents.models import MedicalPermit

        app = _app_for(parent_account, status="rejected")
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload()},
        )

        assert response.status_code == 404
        assert not MedicalPermit.objects.filter(application=app).exists()


# ---------------------------------------------------------------------------
# P23 visual parity — the permit renders with the SAME document-card UI
# grammar as the ID-document cards on BOTH parent surfaces. Contract is
# markup-level only: card root marker + classes, header/body structure,
# visually-hidden native file input driven by a full-width secondary
# label-button, the always-visible "Neobligāti" optional marker, uploaded
# state (filename + preview/download routes kept), and workspace placement
# immediately after the ID-document card group. No CSS values, no JS
# behavior, no business-rule change is asserted here.
# ---------------------------------------------------------------------------


DOC_CARD_MARKER = '<div class="fk-document-card">'
PERMIT_CARD_MARKER = "data-medical-permit-card"
OPTIONAL_LABEL = "Neobligāti"


def _permit_card_fragment(html, end_marker):
    """Return the permit card's opening tag + markup up to ``end_marker``.

    Mirrors the ``_card_fragment`` split technique from
    ``test_document_state_presentation``: the marker is unique per card, and
    the fragment is bounded by the next block-level close so assertions stay
    scoped to the card itself.
    """
    idx = html.index(PERMIT_CARD_MARKER)
    tag_start = html.rindex("<", 0, idx)
    end = html.index(end_marker, idx)
    return html[tag_start:end]


def _open_tag_of(html, marker):
    """Return the full opening tag containing ``marker``."""
    idx = html.index(marker)
    tag_start = html.rindex("<", 0, idx)
    tag_end = html.index(">", idx)
    return html[tag_start : tag_end + 1]


def _attr(tag, attr):
    import re

    match = re.search(
        r"\b" + re.escape(attr) + r"=[\"']([^\"']*)[\"']", tag
    )
    return match.group(1) if match else None


def _assert_document_card_grammar(fragment):
    """Shared grammar contract — same primitives document_card.html uses."""
    import re

    # Same UI grammar: fk-document-card root, header + body regions.
    assert "fk-document-card__header" in fragment, (
        "permit card must render a fk-document-card__header region like the "
        "ID-document cards"
    )
    assert "fk-document-card__body" in fragment, (
        "permit card must render a fk-document-card__body region like the "
        "ID-document cards"
    )

    # Optional marker visible to the parent on every state.
    assert OPTIONAL_LABEL in fragment, (
        f"permit card must visibly say {OPTIONAL_LABEL!r}"
    )

    # Native file input is visually hidden — the visible tap surface is the
    # label-button (mirrors the Slice D canonical-input treatment).
    file_input = re.search(r"<input[^>]*type=\"file\"[^>]*>", fragment)
    assert file_input is not None, "permit card must contain a native file input"
    input_classes = _attr(file_input.group(0), "class") or ""
    assert "fk-visually-hidden" in input_classes, (
        f"permit file input must carry fk-visually-hidden, got class={input_classes!r}"
    )

    # Upload affordance is a full-width secondary label-button bound to the
    # hidden input — the exact class trio document_card.html renders.
    label_tag = None
    for match in re.finditer(r"<label\b[^>]*>", fragment):
        classes = _attr(match.group(0), "class") or ""
        if "fk-button" in classes and "fk-button--full" in classes:
            label_tag = match.group(0)
            break
    assert label_tag is not None, (
        "permit card must offer upload via a fk-button fk-button--secondary "
        "fk-button--full label-button"
    )
    label_classes = _attr(label_tag, "class") or ""
    assert "fk-button--secondary" in label_classes, (
        f"upload label-button must be secondary style, got {label_classes!r}"
    )
    assert _attr(label_tag, "for") == _attr(file_input.group(0), "id"), (
        "upload label-button must target the hidden native file input"
    )


class TestPermitCardVisualParity:
    """Permit must look and feel like the ID-document cards on workspace + portal."""

    # -- workspace: placement + grammar (missing state) -------------------

    def test_workspace_draft_permit_card_follows_document_group(
        self, verified_client, parent_account
    ):
        """The permit card sits immediately after the ID-document card group —
        in the rendered HTML it follows the last fk-document-card, not the
        top-of-page bespoke section."""
        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()

        assert DOC_CARD_MARKER in html, "baseline: ID-document cards render"
        assert PERMIT_CARD_MARKER in html, (
            "workspace permit block must carry the data-medical-permit-card marker"
        )
        assert html.rindex(DOC_CARD_MARKER) < html.index(PERMIT_CARD_MARKER), (
            "permit card must render AFTER the ID-document card group "
            "(below parent ID, child ID, and child portrait)"
        )

    def test_workspace_draft_permit_card_uses_document_card_grammar(
        self, verified_client, parent_account
    ):
        """Missing-permit state on an editable draft uses the shared card
        primitives: fk-document-card root, header/body, hidden input, and the
        full-width secondary label-button. Never a submit-validation gate —
        the 'Neobligāti' marker is what makes that visible."""
        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        html = response.content.decode()

        assert PERMIT_CARD_MARKER in html
        card_tag = _open_tag_of(html, PERMIT_CARD_MARKER)
        assert "fk-document-card" in (_attr(card_tag, "class") or ""), (
            f"permit card root must carry fk-document-card, got tag: {card_tag}"
        )
        fragment = _permit_card_fragment(html, "</section>")
        _assert_document_card_grammar(fragment)

    # -- workspace: uploaded state ----------------------------------------

    def test_workspace_uploaded_permit_card_shows_filename_and_file_links(
        self, verified_client, parent_account
    ):
        """Uploaded state keeps the same card grammar plus filename, a
        replacement affordance, and the private preview/download routes."""
        from django.urls import reverse

        app = _app_for(parent_account)
        permit = _permit(app)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()

        assert PERMIT_CARD_MARKER in html
        fragment = _permit_card_fragment(html, "</section>")
        _assert_document_card_grammar(fragment)

        assert permit.original_filename in fragment, (
            "uploaded permit card must show the original filename"
        )
        assert (
            reverse("registrations:medical-permit-preview", args=[permit.pk])
            in fragment
        )
        assert (
            reverse("registrations:medical-permit-download", args=[permit.pk])
            in fragment
        )
        # Replacement affordance stays on the card (draft is upload-allowed).
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            in fragment
        )

    # -- portal: same grammar on both stages --------------------------------

    def test_portal_preapproval_card_matches_document_grammar(
        self, verified_client, parent_account
    ):
        """Portal card for an allowed pre-approval (draft) application: same
        marker/classes/optional marker, upload wired to the application
        endpoint."""
        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()

        assert PERMIT_CARD_MARKER in html, (
            "portal permit block must carry the data-medical-permit-card marker"
        )
        card_tag = _open_tag_of(html, PERMIT_CARD_MARKER)
        assert "fk-document-card" in (_attr(card_tag, "class") or ""), (
            f"portal permit card root must carry fk-document-card, got: {card_tag}"
        )
        fragment = _permit_card_fragment(html, "</article>")
        _assert_document_card_grammar(fragment)
        assert (
            reverse("registrations:application-medical-permit-upload", args=[app.pk])
            in fragment
        ), "portal pre-approval card must post to the application upload endpoint"

    def test_portal_approved_card_matches_document_grammar(
        self, verified_client, parent_account, make_guardian
    ):
        """Approved child's portal card keeps the same grammar; upload posts
        to the member endpoint (stage-correct URL)."""
        from django.urls import reverse

        _app, member, _permit_obj = _approved_family(parent_account, make_guardian)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()

        assert PERMIT_CARD_MARKER in html
        card_tag = _open_tag_of(html, PERMIT_CARD_MARKER)
        assert "fk-document-card" in (_attr(card_tag, "class") or ""), (
            f"portal permit card root must carry fk-document-card, got: {card_tag}"
        )
        fragment = _permit_card_fragment(html, "</article>")
        _assert_document_card_grammar(fragment)
        assert (
            reverse("registrations:member-medical-permit-upload", args=[member.pk])
            in fragment
        ), "portal approved card must post to the member upload endpoint"


# ---------------------------------------------------------------------------
# P23 async upload follow-up — the fetch-on-change flow replaces the
# submit-button scaffolding entirely. The editable-workspace standalone
# permit form and the HTML5 form= association existed ONLY to give the
# visible submit button a POST target outside the wizard form. With
# async_upload.js binding the marked card input and POSTing directly to
# the card's advertised upload URL, no standalone permit form and no
# form= association may remain, and the only submit control allowed in
# the card is the <noscript> no-JS fallback. The wizard-form purity
# invariants from the original review fix stay: no <form> markup outside
# the noscript block may contribute to the wizard serialization, and no
# visible submit button may capture implicit Enter submission.
# ---------------------------------------------------------------------------


def _strip_noscript(fragment: str) -> str:
    """Remove every <noscript>…</noscript> region from a markup fragment."""
    import re

    return re.sub(r"<noscript>.*?</noscript>", "", fragment, flags=re.DOTALL)


PERMIT_INPUT_MARKER = "data-medical-permit-input"
PERMIT_ACTIONS_MARKER = "data-medical-permit-actions"


class TestPermitNoStandaloneFormAssociation:
    """Intentionally-retired contract: the standalone permit form + form="
    association are replaced by the JS fetch-on-change bind path."""

    def test_editable_workspace_has_no_standalone_permit_form(
        self, verified_client, parent_account
    ):
        """No hidden standalone form, no form= association, no submit
        button outside <noscript> anywhere on the editable workspace."""
        from django.urls import reverse

        app = _app_for(parent_account)  # draft → editable workspace mode
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()

        assert "medical-permit-upload-form-" not in html, (
            "standalone permit form is retired — the JS bind path POSTs "
            "directly to the card's data-medical-permit-upload-url"
        )
        fragment = _strip_noscript(_permit_card_fragment(html, "</section>"))
        assert "<form" not in fragment, "card must not open a form inside wizard"
        assert "</form>" not in fragment, "card must not close the wizard form"
        assert 'form="' not in fragment, "card markup must not use form= association"
        assert (
            'type="submit"' not in fragment
        ), "permit card must have no submit control outside <noscript>"

    def test_editable_workspace_card_exposes_async_bind_hooks(
        self, verified_client, parent_account
    ):
        """The file input carries the JS bind hook, the card root keeps
        advertising the stage-correct endpoint for the fetch path."""
        import re

        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()

        fragment = _strip_noscript(_permit_card_fragment(html, "</section>"))
        assert (
            PERMIT_INPUT_MARKER in fragment
        ), "permit file input must carry the async bind hook data-medical-permit-input"
        file_input = re.search(r"<input[^>]*type=\"file\"[^>]*>", fragment)
        assert file_input is not None
        assert _attr(file_input.group(0), "form") is None, (
            "permit file input must NOT be associated with any form "
            "(form= attribute is retired with the submit button)"
        )
        card_tag = _open_tag_of(html, PERMIT_CARD_MARKER)
        assert (
            _attr(card_tag, "data-medical-permit-upload-url")
            == reverse("registrations:application-medical-permit-upload", args=[app.pk])
        ), "card root must advertise the application upload endpoint for the JS"

    def test_portal_card_exposes_async_bind_hooks(
        self, verified_client, parent_account, make_guardian
    ):
        """The approved child's portal card exposes the same bind hooks and
        advertises the member endpoint (no form= association, no visible
        submit button)."""
        import re

        from django.urls import reverse

        _app, member, _permit = _approved_family(parent_account, make_guardian)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()

        fragment = _strip_noscript(_permit_card_fragment(html, "</article>"))
        assert PERMIT_INPUT_MARKER in fragment, (
            "portal permit file input must carry the async bind hook "
            "data-medical-permit-input"
        )
        file_input = re.search(r"<input[^>]*type=\"file\"[^>]*>", fragment)
        assert file_input is not None
        assert _attr(file_input.group(0), "form") is None
        assert 'type="submit"' not in fragment, (
            "portal permit card must have no submit control outside <noscript>"
        )
        card_tag = _open_tag_of(html, PERMIT_CARD_MARKER)
        assert (
            _attr(card_tag, "data-medical-permit-upload-url")
            == reverse("registrations:member-medical-permit-upload", args=[member.pk])
        ), "portal approved card must advertise the member upload endpoint"

    def test_uploaded_card_wraps_file_links_in_actions_container(
        self, verified_client, parent_account
    ):
        """The preview/download links live inside a stable
        data-medical-permit-actions container so the JS can swap them in
        place after a successful 201."""
        from django.urls import reverse

        app = _app_for(parent_account)
        permit = _permit(app)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()

        fragment = _permit_card_fragment(html, "</section>")
        assert PERMIT_ACTIONS_MARKER in fragment, (
            "uploaded permit card must wrap the file links in a "
            "data-medical-permit-actions container"
        )
        actions_idx = fragment.index(PERMIT_ACTIONS_MARKER)
        preview_url = reverse("registrations:medical-permit-preview", args=[permit.pk])
        download_url = reverse("registrations:medical-permit-download", args=[permit.pk])
        assert actions_idx < fragment.index(preview_url), (
            "actions container must open before the preview link it wraps"
        )
        assert actions_idx < fragment.index(download_url), (
            "actions container must open before the download link it wraps"
        )

    # -- missing state: stable empty container must already exist ----------
    #
    # The first automatic upload has nowhere to insert the private links if
    # the container only appears in the uploaded state. The missing card on
    # BOTH surfaces must therefore ship exactly one
    # data-medical-permit-actions container — present, hidden, and empty of
    # private file links — so the JS populates and reveals it in place.

    def _assert_missing_card_actions_slot(self, fragment: str) -> None:
        import re

        visible = _strip_noscript(fragment)
        assert (
            visible.count(PERMIT_ACTIONS_MARKER) == 1
        ), "missing permit card must contain exactly one actions container"
        container_tag = _open_tag_of(visible, PERMIT_ACTIONS_MARKER)
        assert "hidden" in container_tag, (
            "the initial actions container must be hidden "
            '(HTML5 `hidden` attribute) — no private links are visible yet'
        )
        assert re.search(
            r"<a\b[^>]*href=\"[^\"]*medical-permits/", visible
        ) is None, (
            "missing card's actions container must start empty of private "
            "preview/download links"
        )

    def test_missing_workspace_card_has_single_hidden_actions_container(
        self, verified_client, parent_account
    ):
        from django.urls import reverse

        app = _app_for(parent_account)  # draft, no permit → missing state
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert PERMIT_CARD_MARKER in html
        self._assert_missing_card_actions_slot(
            _permit_card_fragment(html, "</section>")
        )

    def test_missing_portal_card_has_single_hidden_actions_container(
        self, verified_client, parent_account
    ):
        from django.urls import reverse

        _app_for(parent_account)  # draft → portal card in missing state
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert PERMIT_CARD_MARKER in html
        self._assert_missing_card_actions_slot(
            _permit_card_fragment(html, "</article>")
        )


# ---------------------------------------------------------------------------
# Approved application with a SIGNED agreement — upload stays available on
# both surfaces via the member endpoint, and never sends email.
# ---------------------------------------------------------------------------


class TestApprovedWithSignedAgreement:
    def test_workspace_renders_member_upload_form(
        self, verified_client, parent_account, make_guardian
    ):
        """Post-approval the workspace form must target the member endpoint —
        stage-correct URL — even with the agreement signed."""
        from django.urls import reverse

        _app, member, _agreement = _signed_family(parent_account, make_guardian)
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[_app.pk])
        )
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:member-medical-permit-upload", args=[member.pk])
            in html
        )

    def test_portal_renders_member_upload_form(
        self, verified_client, parent_account, make_guardian
    ):
        """Signed agreement must not hide the portal upload control."""
        from django.urls import reverse

        _app, member, _agreement = _signed_family(parent_account, make_guardian)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            reverse("registrations:member-medical-permit-upload", args=[member.pk])
            in html
        )

    def test_member_upload_returns_201_and_sends_no_email(
        self, verified_client, parent_account, make_guardian
    ):
        from django.core import mail
        from django.urls import reverse

        _app, member, agreement = _signed_family(parent_account, make_guardian)
        permit = member.medical_permit
        old_name = permit.file.name
        # Approval/signing setup may have produced mail — start clean so the
        # assertion proves THE UPLOAD sends nothing.
        mail.outbox.clear()

        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("after-signing.pdf")},
        )

        assert response.status_code == 201
        permit.refresh_from_db()
        assert permit.file.name != old_name
        assert permit.original_filename == "after-signing.pdf"
        assert mail.outbox == []
        agreement.refresh_from_db()
        assert agreement.state == "signed"  # upload never mutates agreement


# ---------------------------------------------------------------------------
# P23 async upload follow-up — 201 JSON payloads carry everything the card
# needs to update itself (filename, status, private file links) so the JS
# never has to re-render the whole page. Only the fields the UI consumes
# are asserted — no over-specific response shape.
# ---------------------------------------------------------------------------

PERMIT_STATUS_IDENTIFIERS = {"missing", "current", "expiring", "expired"}


class TestPermitUploadJsonResponse:
    def test_application_upload_201_returns_card_update_payload(
        self, monkeypatch, verified_client, parent_account
    ):
        import json

        from django.urls import reverse

        _freeze(monkeypatch, 2026, 1, 15)
        app = _app_for(parent_account)
        response = verified_client.post(
            reverse("registrations:application-medical-permit-upload", args=[app.pk]),
            {"file": _upload("aplieciba-2026.pdf")},
        )

        assert response.status_code == 201  # retained — the fetch path checks it
        assert response["Content-Type"].startswith("application/json")
        payload = json.loads(response.content)
        permit = app.medical_permit

        assert payload.get("filename") == "aplieciba-2026.pdf", (
            "payload must carry the permit original filename for the card"
        )
        # Status identifier OR label — either is sufficient for the card.
        assert payload.get("status") or payload.get("status_label"), (
            "payload must carry a status identifier or label"
        )
        if payload.get("status"):
            assert payload["status"] in PERMIT_STATUS_IDENTIFIERS
            assert payload["status"] == "current"  # Jan 2026 upload → valid to Sep 2027
        assert payload.get("preview_url") == reverse(
            "registrations:medical-permit-preview", args=[permit.pk]
        ), "payload must carry the private preview URL of the stored permit"
        assert payload.get("download_url") == reverse(
            "registrations:medical-permit-download", args=[permit.pk]
        ), "payload must carry the private download URL of the stored permit"

    def test_member_upload_201_returns_card_update_payload(
        self, verified_client, parent_account, make_guardian
    ):
        import json

        from django.urls import reverse

        _app, member, permit = _approved_family(parent_account, make_guardian)
        response = verified_client.post(
            reverse("registrations:member-medical-permit-upload", args=[member.pk]),
            {"file": _upload("aizvietota-aplieciba.pdf")},
        )

        assert response.status_code == 201
        assert response["Content-Type"].startswith("application/json")
        payload = json.loads(response.content)
        permit.refresh_from_db()

        assert payload.get("filename") == "aizvietota-aplieciba.pdf"
        assert payload.get("status") or payload.get("status_label")
        assert payload.get("preview_url") == reverse(
            "registrations:medical-permit-preview", args=[permit.pk]
        )
        assert payload.get("download_url") == reverse(
            "registrations:medical-permit-download", args=[permit.pk]
        )


# ---------------------------------------------------------------------------
# P23 async upload follow-up — the card partial source contract: the normal
# visible submit button is gone; the no-JS fallback exists ONLY inside a
# <noscript> block that keeps a working manual upload form (own file input,
# CSRF, multipart POST to the card's upload URL). The external_form_id /
# form= association mode is removed with the standalone workspace form.
# ---------------------------------------------------------------------------


class TestPermitCardPartialSourceContract:
    @staticmethod
    def _read_partial() -> str:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "templates"
            / "parent_ui"
            / "includes"
            / "medical_permit_card.html"
        )
        return path.read_text(encoding="utf-8")

    def test_no_submit_button_outside_noscript(self):
        import re

        source = self._read_partial()
        visible = re.sub(r"<noscript>.*?</noscript>", "", source, flags=re.DOTALL)
        assert (
            'type="submit"' not in visible
        ), "card partial must not render a visible submit button outside <noscript>"

    def test_manual_nojs_upload_form_exists_in_some_parent_template(self):
        """P23 code-review regression (no-JS fallback placement): the fallback
        form may live in the card partial OR in a sibling partial / consumer
        template rendered OUTSIDE the wizard — the card-interior
        ``<noscript><form>`` was exactly the acceptance-blocking nesting bug,
        so this test no longer pins placement inside the card fragment.
        Rendered placement is pinned by TestWorkspaceNoJsFallbackPlacement /
        TestPortalNoJsFallbackRetained below."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "templates"
        corpus = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.html"))
        )
        matches = re.findall(r"<noscript>(.*?)</noscript>", corpus, flags=re.DOTALL)
        working = [
            block
            for block in matches
            if "<form" in block
            and 'enctype="multipart/form-data"' in block
            and "{% csrf_token %}" in block
            and 'type="file"' in block
            and 'type="submit"' in block
            and "{{ upload_url }}" in block
        ]
        assert working, (
            "a working no-JS manual upload form (multipart POST to "
            "{{ upload_url }} + CSRF + own file input + submit) must exist "
            "inside a <noscript> block in some parent template"
        )

    def test_external_form_association_mode_removed(self):
        source = self._read_partial()
        assert (
            "external_form_id" not in source
        ), "external_form_id mode is retired — the card renders identically on both surfaces"
        assert 'form="{{' not in source, "no HTML5 form= association may remain"

    def test_async_bind_hooks_present_in_partial(self):
        source = self._read_partial()
        for hook in (
            PERMIT_CARD_MARKER,
            "data-medical-permit-upload-url",
            PERMIT_INPUT_MARKER,
            "data-medical-permit-status",
        ):
            assert hook in source, f"card partial must expose the {hook!r} hook"


# ---------------------------------------------------------------------------
# P23 async upload follow-up — the portal must actually load the binder and
# place the permit card in its own full-width row: after the summary /
# progress blocks, before the fk-app-actions CTA, no longer nested inside
# the fk-app-block status summary.
# ---------------------------------------------------------------------------


class TestPortalAsyncUploadWiring:
    def test_portal_loads_async_upload_js(self, verified_client, parent_account):
        _app_for(parent_account)  # any application so the portal renders cards
        from django.urls import reverse

        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()
        assert (
            "js/async_upload.js" in html
        ), "portal must load async_upload.js so the permit card can fetch-on-change"

    def _assert_permit_row_placement(self, html: str) -> None:
        import re

        progress_idx = html.index("fk-app-block fk-progress-wrap")
        cta_idx = html.index("fk-app-actions")
        row = re.search(r'<div class="[^"]*fk-app-permit[^"]*"', html)
        assert row is not None, (
            "portal permit card must render in its own fk-app-permit row"
        )
        assert "fk-app-block" not in row.group(0), (
            "the permit row must be a full-width row of its own, not a "
            "fk-app-block summary sub-region"
        )
        assert progress_idx < row.start() < cta_idx, (
            "permit row must sit after the summary/progress blocks and "
            "before the main application CTA"
        )
        assert html.index(PERMIT_CARD_MARKER) > row.start(), (
            "the permit card must be inside its own row"
        )

    def test_portal_permit_card_is_own_row_before_cta_draft(
        self, verified_client, parent_account
    ):
        from django.urls import reverse

        _app_for(parent_account)  # draft → portal shows the application card
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        self._assert_permit_row_placement(response.content.decode())

    def test_portal_permit_card_is_own_row_before_cta_approved(
        self, verified_client, parent_account, make_guardian
    ):
        from django.urls import reverse

        _approved_family(parent_account, make_guardian)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        self._assert_permit_row_placement(response.content.decode())


# ---------------------------------------------------------------------------
# P23 code-review regression — no-JS fallback placement (defect 2). The card
# partial emitted ``<noscript><form>…`` INSIDE the wizard ``<form>``. With
# scripting disabled the browser parses the nested ``<form`` start tag as
# markup and drops it (HTML parser: in-scope form), so the fallback submit
# would post to the WIZARD's action/enctype instead of the permit endpoint —
# the no-JS path cannot work while nested. Contract (rendered):
#   * the editable workspace page contains no nested <form> at all (max
#     form depth == 1);
#   * the permit card fragment carries no <noscript> content that opens a
#     <form>;
#   * after the wizard's closing </form> a <noscript> fallback form exists:
#     stage-correct application permit endpoint, multipart, CSRF, own file
#     input, submit control;
#   * the portal keeps a working fallback somewhere outside any other form
#     (its card/row or elsewhere — placement-agnostic on that surface, the
#     portal has no wizard form to nest into).
# The JS-visible DOM rules stay intact (TestPermitNoStandaloneFormAssociation
# above): no visible permit submit, no form= association, no permit form in
# the card's normal markup.
# ---------------------------------------------------------------------------


def _max_form_depth(html: str) -> int:
    """Max nesting depth of raw <form> tags in the rendered markup."""
    import re

    depth = 0
    max_depth = 0
    for match in re.finditer(r"<(/?)form\b", html):
        if match.group(1) == "":
            depth += 1
            max_depth = max(max_depth, depth)
        else:
            depth -= 1
    return max_depth


def _wizard_form_bounds(html: str) -> tuple[int, int]:
    """(start of the wizard <form …> open tag, end just past its matching
    </form>). Depth tracking stays correct even on the broken page where the
    fallback nests inside — the first depth-0 close is the real wizard end."""
    import re

    anchor = html.index("fk-workspace-form")
    start = html.rindex("<form", 0, anchor)
    depth = 0
    for match in re.finditer(r"<(/?)form\b", html[start:]):
        if match.group(1) == "":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                close_start = start + match.start()
                return start, html.index(">", close_start) + 1
    raise AssertionError("wizard <form> is never closed")


def _noscript_blocks(markup: str) -> list[str]:
    import re

    return re.findall(r"<noscript>(.*?)</noscript>", markup, flags=re.DOTALL)


class TestWorkspaceNoJsFallbackPlacement:
    """Rendered editable-workspace contract for the external no-JS fallback."""

    def _draft_workspace(self, verified_client, parent_account):
        from django.urls import reverse

        app = _app_for(parent_account)  # draft → editable wizard mode
        response = verified_client.get(
            reverse("registrations:application-workspace", args=[app.pk])
        )
        assert response.status_code == 200
        return app, response.content.decode()

    def test_editable_workspace_has_no_nested_forms(
        self, verified_client, parent_account
    ):
        _app, html = self._draft_workspace(verified_client, parent_account)
        depth = _max_form_depth(html)
        assert depth == 1, (
            "the permit no-JS fallback must not render as a nested <form> "
            f"inside the wizard form — browsers drop nested forms, so the "
            f"no-JS upload cannot post. Max <form> depth observed: {depth}."
        )

    def test_card_fragment_has_no_noscript_opening_a_form(
        self, verified_client, parent_account
    ):
        _app, html = self._draft_workspace(verified_client, parent_account)
        fragment = _permit_card_fragment(html, "</section>")
        blocks = _noscript_blocks(fragment)
        for block in blocks:
            assert "<form" not in block, (
                "the permit card fragment itself must not ship <noscript> "
                "content that opens a <form> — it renders inside the wizard "
                "form and no-JS browsers discard the nested form"
            )

    def test_external_noscript_fallback_form_after_wizard_close(
        self, verified_client, parent_account
    ):
        import re

        from django.urls import reverse

        app, html = self._draft_workspace(verified_client, parent_account)
        _start, wizard_end = _wizard_form_bounds(html)
        tail = html[wizard_end:]

        blocks = [b for b in _noscript_blocks(tail) if "<form" in b]
        assert blocks, (
            "a <noscript> fallback upload form must exist AFTER the wizard's "
            "closing </form> so no-JS parents get a standalone, submittable "
            "manual upload form"
        )
        fallback = blocks[0]
        open_tag = re.search(r"<form\b[^>]*>", fallback)
        assert open_tag is not None, "fallback <noscript> must open a <form>"
        tag = open_tag.group(0)
        assert 'method="post"' in tag, f"fallback form must POST, got: {tag}"
        upload_url = reverse(
            "registrations:application-medical-permit-upload", args=[app.pk]
        )
        assert f'action="{upload_url}"' in tag, (
            "draft-workspace fallback must post to the stage-correct "
            f"application permit endpoint {upload_url}, got: {tag}"
        )
        assert 'enctype="multipart/form-data"' in tag, (
            "fallback form must be multipart so the file actually uploads"
        )
        assert 'name="csrfmiddlewaretoken"' in fallback, (
            "fallback form must carry CSRF"
        )
        assert re.search(r"<input\b[^>]*type=\"file\"", fallback), (
            "fallback form must include its own file input"
        )
        assert 'name="file"' in fallback, (
            "fallback file input must use the field name the endpoint expects"
        )
        assert 'type="submit"' in fallback, (
            "fallback form must carry a submit control for no-JS use"
        )


class TestPortalNoJsFallbackRetained:
    """The portal has no wizard form, so its fallback may stay inline in the
    card/row or move elsewhere — but it must remain present, standalone, and
    pointed at the stage-correct endpoint. Guards the fix from deleting the
    portal's only manual upload path."""

    def test_portal_permit_fallback_form_usable_outside_any_form(
        self, verified_client, parent_account
    ):
        import re

        from django.urls import reverse

        app = _app_for(parent_account)
        response = verified_client.get(reverse("registrations:parent-portal"))
        assert response.status_code == 200
        html = response.content.decode()

        upload_url = reverse(
            "registrations:application-medical-permit-upload", args=[app.pk]
        )
        pattern = (
            r"<form\b[^>]*action=\"" + re.escape(upload_url) + r"\"[^>]*>(.*?)</form>"
        )
        match = re.search(pattern, html, flags=re.DOTALL)
        assert match is not None, (
            "portal must keep a manual fallback <form> posting to the "
            f"application permit endpoint {upload_url}"
        )
        tag = html[match.start() : html.index(">", match.start()) + 1]
        assert 'method="post"' in tag, f"portal fallback must POST, got: {tag}"
        assert 'enctype="multipart/form-data"' in tag, (
            "portal fallback must be multipart"
        )
        body = match.group(1)
        assert 'name="csrfmiddlewaretoken"' in body, "portal fallback needs CSRF"
        assert re.search(r"<input\b[^>]*type=\"file\"", body), (
            "portal fallback must include a file input"
        )
        assert 'name="file"' in body
        assert 'type="submit"' in body, "portal fallback needs a submit control"
        assert _max_form_depth(html) == 1, (
            "the portal fallback form must not be nested inside any other form"
        )


class TestPermitLabelIconParity:
    """P23 code-review follow-up (minor parity regression): the async success
    path updates the upload control's text but must keep the inline upload
    SVG icon. Contract: the text hook is a CHILD element of the <label>
    button (which also carries the SVG), and the JS writes text only through
    that child span — never via ``label.textContent``, which would replace
    the label's children and erase the icon (identity-document cards keep
    their icon through a text span; the permit card must match)."""

    @staticmethod
    def _read_partial() -> str:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "templates"
            / "parent_ui"
            / "includes"
            / "medical_permit_card.html"
        )
        return path.read_text(encoding="utf-8")

    def test_upload_label_keeps_svg_with_child_text_hook(self):
        import re

        source = self._read_partial()
        label_match = re.search(r"<label\b[^>]*>(.*?)</label>", source, flags=re.DOTALL)
        assert label_match is not None, "card must render the upload label-button"
        label_block = label_match.group(1)
        assert "<svg" in label_block, (
            "the upload label-button must keep its inline upload SVG icon "
            "(parity with document_card.html)"
        )
        assert "data-medical-permit-label" in label_block, (
            "the label text must live in a child hook element INSIDE the "
            "<label> so the JS can swap text without destroying the SVG"
        )
        assert re.search(r"<label[^>]*data-medical-permit-label", source) is None, (
            "the text hook must NOT be placed on the <label> element itself "
            "— writing textContent there would erase the upload SVG"
        )

    def test_js_success_path_writes_child_span_not_label_textContent(self):
        import re
        from pathlib import Path

        js = (
            Path(__file__).resolve().parents[2]
            / "static"
            / "js"
            / "async_upload.js"
        ).read_text(encoding="utf-8")
        assert "[data-medical-permit-label]" in js, (
            "the permit success path must target the child text-span hook"
        )
        assert re.search(r"\blabel\.(textContent|innerHTML)", js) is None, (
            "async_upload.js must not assign through a bare `label.` handle "
            "(label.textContent / label.innerHTML) — name the child span "
            "(e.g. labelText.textContent = …) so the upload SVG inside the "
            "<label> survives the success update"
        )

