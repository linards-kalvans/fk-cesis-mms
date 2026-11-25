"""Default-off, primary-independent PDF shadow forwarding regressions."""

from importlib.util import find_spec
from unittest.mock import patch

import pytest
from django.utils import timezone


@pytest.fixture(autouse=True)
def isolated_shadow_storage(settings, tmp_path):
    settings.PRIVATE_DOCUMENTS_ROOT = tmp_path


def test_shadow_renderer_exists():
    assert find_spec("apps.agreements.pdf_rendering") is not None


@pytest.fixture
def shadow_agreement(agreement_member):
    from apps.agreements.models import Agreement

    return Agreement.objects.create(
        member=agreement_member, generated_at=timezone.now(),
        agreement_number="TEST-2026-900", signing_path="paper",
    )


def snapshot_for(agreement):
    from apps.agreements.models import Agreement
    from apps.integrations.docuseal import _build_field_payload

    fresh = Agreement.objects.select_related("member__guardian__parent_account").get(pk=agreement.pk)
    return {"fields": _build_field_payload(fresh), "signing_path": fresh.signing_path}


@pytest.mark.django_db
def test_shadow_default_off_preserves_primary(shadow_agreement, settings):
    from apps.agreements.models import AgreementPDFShadow
    from apps.integrations.tasks import create_agreement_submission

    settings.AGREEMENT_PDF_SHADOW_ENABLED = False
    create_agreement_submission(shadow_agreement.pk)
    shadow_agreement.refresh_from_db()
    assert shadow_agreement.external_id == f"stub-{shadow_agreement.pk}"
    assert not AgreementPDFShadow.objects.exists()


@pytest.mark.django_db
def test_forwarding_freezes_exact_result_snapshot(shadow_agreement, settings):
    from apps.agreements.models import AgreementPDFShadow
    from apps.agreements.shadow import enqueue_agreement_pdf_shadow
    from apps.integrations.agreement_platform import SubmissionResult

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    captured = snapshot_for(shadow_agreement)
    captured["fields"]["guardian_name"] = "Submitted, not current"
    result = SubmissionResult("submission-one", "https://secret.invalid/session", "pending", captured)
    with patch("apps.agreements.shadow.async_task") as queue:
        enqueue_agreement_pdf_shadow(shadow_agreement, result)
    row = AgreementPDFShadow.objects.get()
    assert row.snapshot == captured
    assert row.primary_external_id == "submission-one"
    assert row.status == "pending"
    assert "Submitted" not in repr(result)
    assert "Submitted" not in str(row)
    assert queue.call_args.args[1:] == (row.pk,)


@pytest.mark.django_db
def test_shadow_queue_failure_cannot_fail_primary(shadow_agreement, settings, caplog):
    from apps.agreements.models import AgreementPDFShadow
    from apps.integrations.tasks import create_agreement_submission

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    with patch("apps.agreements.shadow.async_task", side_effect=RuntimeError("secret@example.test")):
        create_agreement_submission(shadow_agreement.pk)
    shadow_agreement.refresh_from_db()
    assert shadow_agreement.external_state == "pending"
    assert shadow_agreement.external_error_code == ""
    assert AgreementPDFShadow.objects.get().error_code == "queue_failed"
    assert "secret@example.test" not in caplog.text


@pytest.mark.django_db
def test_primary_failure_creates_no_shadow(shadow_agreement, settings):
    from apps.agreements.models import AgreementPDFShadow
    from apps.integrations.tasks import create_agreement_submission

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    with patch("apps.integrations.agreement_platform.create_submission", side_effect=ValueError("bad")):
        create_agreement_submission(shadow_agreement.pk)
    assert not AgreementPDFShadow.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["paper", "electronic"])
def test_rendered_shadow_has_expected_fields_and_wording(shadow_agreement, path):
    import pymupdf
    from apps.agreements.pdf_rendering import render_shadow_pdf, TEMPLATE_VERSION

    snapshot = snapshot_for(shadow_agreement)
    snapshot["signing_path"] = path
    snapshot["fields"]["guardian_name"] = "Ārija <script>alert(1)</script> Ģērķe"
    pdf = render_shadow_pdf(snapshot, template_version=TEMPLATE_VERSION)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = " ".join(page.get_text() for page in doc)
        assert len(doc) <= 20
        for page in doc:
            assert "NAV DERĪGS PARAKSTĪŠANAI" in page.get_text()
        assert "Ārija <script>alert(1)</script> Ģērķe" in text
        assert "50.00 EUR" in text
        assert "SINTĒTISKI" not in text
        assert ("ŠIS DOKUMENTS IR ELEKTRONISKI" in text) == (path == "electronic")
        if path == "paper":
            assert "laika zīmog" not in text.casefold()
        fonts = {font[3] for page in doc for font in page.get_fonts()}
        assert any("Fill" in font for font in fonts)


def test_shadow_resource_fetcher_fails_closed():
    from apps.agreements.pdf_rendering import AssetFetcher
    from weasyprint.urls import FatalURLFetchingError

    fetcher = AssetFetcher(set())
    for url in ("file:///etc/passwd", "https://example.invalid/", "data:text/plain,hello"):
        with pytest.raises(FatalURLFetchingError):
            fetcher.fetch(url)


@pytest.mark.django_db
def test_provider_snapshot_matches_actual_submitted_fields(shadow_agreement, settings):
    from apps.agreements.models import Agreement
    from apps.integrations import docuseal
    from unittest.mock import Mock

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    fresh = Agreement.objects.select_related("member__guardian__parent_account").get(pk=shadow_agreement.pk)
    response = Mock()
    response.json.return_value = [{"submission_id": 42, "embed_src": "https://private.invalid/", "status": "pending"}]
    with patch("apps.integrations.docuseal._require_config", return_value=("https://provider.invalid", "secret", 1)):
        with patch("apps.integrations.docuseal._request", return_value=response) as request:
            result = docuseal.create_submission(fresh, send_email=False)
    submitted = request.call_args.kwargs["json"]["submitters"][0]["fields"]
    assert result.generation_snapshot == {
        "fields": {item["name"]: item["default_value"] for item in submitted},
        "signing_path": "paper",
    }
    assert request.call_args.kwargs["json"]["send_email"] is False
    assert "secret" not in repr(result)


@pytest.mark.django_db
def test_shadow_record_failure_cannot_fail_primary(shadow_agreement, settings):
    from apps.integrations.tasks import create_agreement_submission
    from django.db import OperationalError

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    with patch("apps.agreements.shadow.AgreementPDFShadow.objects.get_or_create", side_effect=OperationalError("private")):
        create_agreement_submission(shadow_agreement.pk)
    shadow_agreement.refresh_from_db()
    assert shadow_agreement.external_id == f"stub-{shadow_agreement.pk}"
    assert shadow_agreement.external_error_code == ""


@pytest.mark.django_db
def test_outer_shadow_hook_failure_cannot_fail_primary(shadow_agreement, settings):
    from apps.integrations.tasks import create_agreement_submission

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    with patch("apps.agreements.shadow.enqueue_agreement_pdf_shadow", side_effect=RuntimeError("private")):
        create_agreement_submission(shadow_agreement.pk)
    shadow_agreement.refresh_from_db()
    assert shadow_agreement.external_id == f"stub-{shadow_agreement.pk}"


@pytest.fixture
def shadow_row(shadow_agreement, settings):
    from apps.agreements.models import AgreementPDFShadow
    from apps.agreements.pdf_rendering import TEMPLATE_VERSION, shadow_renderer_provenance
    from apps.agreements.shadow import primary_provider_identity

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    return AgreementPDFShadow.objects.create(
        agreement=shadow_agreement, primary_external_id="original-submission",
        template_version=TEMPLATE_VERSION, signing_path="paper",
        snapshot=snapshot_for(shadow_agreement),
        provenance={"renderer": shadow_renderer_provenance(), "primary_provider": "stub",
                    "primary_provider_identity": primary_provider_identity()},
    )


@pytest.mark.django_db
def test_worker_publishes_once_without_agreement_mutations(shadow_row):
    from apps.agreements.models import Agreement
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    before = Agreement.objects.filter(pk=shadow_row.agreement_id).values().get()
    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison") as render:
        render_agreement_pdf_shadow(shadow_row.pk)
        render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "ready"
    assert shadow_row.snapshot == {}
    assert shadow_row.file_size == len(b"%PDF-comparison")
    assert len(shadow_row.sha256) == 64
    assert shadow_row.file.read() == b"%PDF-comparison"
    assert render.call_count == 1
    assert before == Agreement.objects.filter(pk=shadow_row.agreement_id).values().get()


@pytest.mark.django_db
def test_worker_uses_frozen_input_after_profile_edit(shadow_row):
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    frozen = shadow_row.snapshot
    guardian = shadow_row.agreement.member.guardian
    guardian.full_name = "Edited after primary request"
    guardian.save()
    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison") as render:
        render_agreement_pdf_shadow(shadow_row.pk)
    assert render.call_args.args[0] == frozen


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["render", "storage"])
def test_worker_failure_is_private_and_preserves_snapshot(shadow_row, failure, caplog):
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    target = ("apps.agreements.shadow_tasks.render_shadow_pdf" if failure == "render"
              else "apps.documents.storage.PrivateDocumentStorage.save")
    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison"):
        with patch(target, side_effect=RuntimeError("sensitive@example.test")):
            render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "failed"
    assert shadow_row.error_code == "render_failed"
    assert shadow_row.snapshot
    assert not shadow_row.file
    assert "sensitive@example.test" not in caplog.text


@pytest.mark.django_db
def test_worker_refuses_changed_template(shadow_row):
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    with patch("apps.agreements.shadow_tasks.shadow_renderer_provenance", return_value={}):
        with patch("apps.agreements.shadow_tasks.render_shadow_pdf") as render:
            render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.error_code == "version_mismatch"
    assert not render.called


@pytest.mark.django_db
def test_disable_stops_queued_work_and_retry(shadow_row, settings):
    from apps.agreements.shadow import retry_pdf_shadow
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    settings.AGREEMENT_PDF_SHADOW_ENABLED = False
    with patch("apps.agreements.shadow_tasks.render_shadow_pdf") as render:
        render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.error_code == "disabled"
    assert not render.called
    with pytest.raises(ValueError, match="disabled"):
        retry_pdf_shadow(shadow_row)


@pytest.mark.django_db
def test_duplicate_forward_does_not_enqueue_or_replace(shadow_row):
    from apps.agreements.shadow import enqueue_agreement_pdf_shadow
    from apps.integrations.agreement_platform import SubmissionResult

    result = SubmissionResult(shadow_row.primary_external_id, "", "pending", shadow_row.snapshot)
    with patch("apps.agreements.shadow.async_task") as queue:
        enqueue_agreement_pdf_shadow(shadow_row.agreement, result)
    assert not queue.called


@pytest.mark.django_db
def test_retry_uses_same_row_without_primary_resend(shadow_row):
    from apps.agreements.shadow import retry_pdf_shadow

    shadow_row.status = "failed"
    shadow_row.save()
    frozen = shadow_row.snapshot
    with patch("apps.agreements.shadow.async_task") as queue:
        with patch("apps.integrations.agreement_platform.create_submission") as primary:
            retry_pdf_shadow(shadow_row)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "pending"
    assert shadow_row.snapshot == frozen
    assert queue.call_args.args[1] == shadow_row.pk
    assert not primary.called


@pytest.mark.django_db
def test_staff_can_compare_saved_primary_id(shadow_row, actor, client):
    from django.urls import reverse
    from apps.integrations.agreement_platform import DocumentStream

    shadow_row.agreement.external_id = "new-current-submission"
    shadow_row.agreement.save()
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "primary"])
    stream = DocumentStream("secret.pdf", "application/pdf", iter([b"%PDF-primary"]))
    with patch("apps.integrations.agreement_platform.stream_submission_document", return_value=stream) as primary:
        response = client.get(url)
        assert b"".join(response.streaming_content) == b"%PDF-primary"
    assert primary.call_args.args == ("original-submission",)
    assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
def test_comparison_denies_nonstaff_and_invalid_disposition(shadow_row, actor, client):
    from django.contrib.auth.models import User
    from django.urls import reverse

    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "local"])
    assert client.get(url).status_code == 302
    regular = User.objects.create_user(username="not-staff")
    client.force_login(regular)
    assert client.get(url).status_code == 302
    client.force_login(actor)
    assert client.get(url + "?disposition=unsafe").status_code == 404
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_ready_shadow_readable_when_disabled_and_audited(shadow_row, actor, client, settings):
    from django.urls import reverse
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow
    from apps.core.models import AuditEvent

    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison"):
        render_agreement_pdf_shadow(shadow_row.pk)
    settings.AGREEMENT_PDF_SHADOW_ENABLED = False
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "local"])
    response = client.get(url)
    assert b"".join(response.streaming_content) == b"%PDF-comparison"
    event = AuditEvent.objects.get(action="document_previewed")
    assert event.metadata == {"source": "local", "comparison_only": True}


@pytest.mark.django_db
def test_comparison_detail_hides_snapshot_and_remote_urls(shadow_row, actor, client):
    from django.urls import reverse

    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_change", args=[shadow_row.pk])
    response = client.get(url)
    assert response.status_code == 200
    text = response.content.decode()
    assert "snapshot" not in text
    for value in shadow_row.snapshot["fields"].values():
        if len(value) >= 4:
            assert value not in text
    for sentinel in (
        "https://stub.invalid", "https://sign.example", "secret-key", "X-Auth-Token",
    ):
        assert sentinel not in text


@pytest.mark.django_db
def test_retry_requires_post_and_csrf(shadow_row, actor):
    from django.test import Client
    from django.urls import reverse

    client = Client(enforce_csrf_checks=True)
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_retry", args=[shadow_row.pk])
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 403


@pytest.mark.django_db
def test_failed_publication_removes_temporary_file(shadow_row, settings):
    from pathlib import Path
    from apps.agreements.models import AgreementPDFShadow
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    original_save = AgreementPDFShadow.save

    def fail_publication(self, *args, **kwargs):
        if self.status == "ready":
            raise OSError("private path")
        return original_save(self, *args, **kwargs)

    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison"):
        with patch.object(AgreementPDFShadow, "save", fail_publication):
            render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "failed"
    assert not shadow_row.file
    assert not list(Path(settings.PRIVATE_DOCUMENTS_ROOT).rglob("*.pdf"))


@pytest.mark.django_db
def test_deleting_shadow_cleans_private_file_after_commit(shadow_row, django_capture_on_commit_callbacks):
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison"):
        render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    storage, name = shadow_row.file.storage, shadow_row.file.name
    with django_capture_on_commit_callbacks(execute=True):
        shadow_row.delete()
        assert storage.exists(name)
    assert not storage.exists(name)


@pytest.mark.django_db(transaction=True)
def test_concurrent_publication_preserves_one_file(shadow_row, settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from pathlib import Path
    from django.db import connection, close_old_connections
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locks required")
    barrier = Barrier(2)

    def render(*args, **kwargs):
        barrier.wait(timeout=10)
        return b"%PDF-comparison"

    def worker():
        close_old_connections()
        try:
            render_agreement_pdf_shadow(shadow_row.pk)
        finally:
            close_old_connections()

    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", side_effect=render):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=20)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "ready"
    assert shadow_row.file.read() == b"%PDF-comparison"
    assert len(list(Path(settings.PRIVATE_DOCUMENTS_ROOT).rglob("*.pdf"))) == 1


@pytest.mark.django_db
def test_stale_pending_job_can_be_retried_after_worker_crash(shadow_row):
    from datetime import timedelta
    from apps.agreements.models import AgreementPDFShadow
    from apps.agreements.shadow import retry_pdf_shadow

    with patch("apps.agreements.shadow.async_task") as queue:
        with pytest.raises(ValueError, match="not_retryable"):
            retry_pdf_shadow(shadow_row)
        AgreementPDFShadow.objects.filter(pk=shadow_row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=6),
        )
        retry_pdf_shadow(shadow_row)
    assert queue.call_count == 1
    shadow_row.refresh_from_db()
    assert shadow_row.status == "pending"
    assert shadow_row.snapshot


# --- Independent review fixes -------------------------------------------------


def _render_ready(shadow_row):
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    with patch("apps.agreements.shadow_tasks.render_shadow_pdf", return_value=b"%PDF-comparison"):
        render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("source", "disposition", "expected"),
    [
        ("local", "inline", "SAMEORIGIN"),
        ("local", "attachment", "DENY"),
        ("primary", "inline", "SAMEORIGIN"),
        ("primary", "attachment", "DENY"),
    ],
)
def test_comparison_frame_options_follow_disposition(
    shadow_row, actor, client, source, disposition, expected,
):
    from django.urls import reverse
    from apps.integrations.agreement_platform import DocumentStream

    _render_ready(shadow_row)
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, source])
    if disposition == "attachment":
        url += "?disposition=attachment"

    def stream(*args, **kwargs):
        return DocumentStream("primary.pdf", "application/pdf", iter([b"%PDF-primary"]))

    with patch("apps.integrations.agreement_platform.stream_submission_document", side_effect=stream):
        response = client.get(url)
    assert response.status_code == 200
    assert response["X-Frame-Options"] == expected


@pytest.mark.django_db
def test_renderer_translates_forbidden_resource_to_ordinary_error(shadow_agreement, tmp_path):
    from apps.agreements import pdf_rendering as rendering

    html_path, css_path, regular, bold, mono, logo = rendering._assets()
    hostile_css = tmp_path / "hostile.css"
    hostile_css.write_text(
        css_path.read_text(encoding="utf-8")
        + "\nbody{background-image:url('https://example.invalid/secret-token-abc')}\n",
        encoding="utf-8",
    )
    with patch.object(
        rendering, "_assets", return_value=(html_path, hostile_css, regular, bold, mono, logo),
    ):
        with pytest.raises(Exception) as info:
            rendering.render_shadow_pdf(
                snapshot_for(shadow_agreement), template_version=rendering.TEMPLATE_VERSION,
            )
    assert isinstance(info.value, Exception)
    assert "resource_rejected" in str(info.value)
    assert "secret-token-abc" not in str(info.value)


@pytest.mark.django_db
def test_worker_contains_forbidden_resource_failure(shadow_row, tmp_path, settings, caplog):
    from pathlib import Path
    from apps.agreements import pdf_rendering as rendering
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    html_path, css_path, regular, bold, mono, logo = rendering._assets()
    hostile_css = tmp_path / "hostile-worker.css"
    hostile_css.write_text(
        css_path.read_text(encoding="utf-8")
        + "\nbody{background-image:url('https://example.invalid/secret-token-abc')}\n",
        encoding="utf-8",
    )
    with patch.object(
        rendering, "_assets", return_value=(html_path, hostile_css, regular, bold, mono, logo),
    ):
        with patch(
            "apps.agreements.shadow_tasks.shadow_renderer_provenance",
            return_value=shadow_row.provenance["renderer"],
        ):
            render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "failed"
    assert shadow_row.error_code == "render_failed"
    assert shadow_row.snapshot
    assert not shadow_row.file
    assert not list(Path(settings.PRIVATE_DOCUMENTS_ROOT).rglob("*.pdf"))
    assert "secret-token-abc" not in caplog.text


def test_provenance_reports_native_harfbuzz_version():
    from apps.agreements.pdf_rendering import shadow_renderer_provenance

    provenance = shadow_renderer_provenance()
    assert provenance["weasyprint"] == "70.0"
    assert isinstance(provenance["harfbuzz"], str)
    assert provenance["harfbuzz"].strip()


def test_provenance_fails_closed_without_harfbuzz(monkeypatch):
    import ctypes.util
    from apps.agreements import pdf_rendering

    monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    with pytest.raises(RuntimeError):
        pdf_rendering.shadow_renderer_provenance()


@pytest.mark.django_db
def test_worker_refuses_changed_native_version(shadow_row):
    from apps.agreements.shadow_tasks import render_agreement_pdf_shadow

    altered = dict(shadow_row.provenance["renderer"])
    altered["harfbuzz"] = altered["harfbuzz"] + "-changed"
    with patch("apps.agreements.shadow_tasks.shadow_renderer_provenance", return_value=altered):
        with patch("apps.agreements.shadow_tasks.render_shadow_pdf") as render:
            render_agreement_pdf_shadow(shadow_row.pk)
    shadow_row.refresh_from_db()
    assert shadow_row.status == "failed"
    assert shadow_row.error_code == "version_mismatch"
    assert not render.called


@pytest.mark.django_db
def test_primary_identity_is_nonsecret_and_normalized(settings):
    from apps.agreements.shadow import primary_provider_identity

    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = (
        "https://User:Passw0rd@Docs.Example.test:443/api/v1/?token=query-secret#frag"
    )
    identity = primary_provider_identity()
    assert identity["mode"] == "docuseal"
    assert set(identity) == {"mode", "api_base_fingerprint"}
    rendered = repr(identity)
    assert "example.test" not in rendered
    assert "Passw0rd" not in rendered
    assert "query-secret" not in rendered

    settings.DOCUSEAL_API_URL = "https://docs.example.test/api/v1"
    assert primary_provider_identity() == identity

    settings.DOCUSEAL_API_URL = "https://docs.example.test/other"
    assert primary_provider_identity() != identity


def test_stub_identity_is_deterministic(settings):
    from apps.agreements.shadow import primary_provider_identity

    settings.AGREEMENT_PROVIDER_MODE = "stub"
    settings.DOCUSEAL_API_URL = "https://unused.invalid/private"
    first = primary_provider_identity()
    settings.DOCUSEAL_API_URL = "https://other.invalid/another"
    assert primary_provider_identity() == first
    assert first["mode"] == "stub"
    assert "invalid" not in repr(first)


def _store_primary_identity(shadow_row, settings, *, mode="docuseal", url):
    from apps.agreements.models import AgreementPDFShadow
    from apps.agreements.shadow import primary_provider_identity

    settings.AGREEMENT_PROVIDER_MODE = mode
    settings.DOCUSEAL_API_URL = url
    provenance = dict(shadow_row.provenance)
    provenance["primary_provider"] = mode
    provenance["primary_provider_identity"] = primary_provider_identity()
    AgreementPDFShadow.objects.filter(pk=shadow_row.pk).update(provenance=provenance)
    shadow_row.refresh_from_db()


@pytest.mark.django_db
def test_primary_comparison_allows_normalized_same_endpoint(shadow_row, actor, client, settings):
    from django.urls import reverse
    from apps.integrations.agreement_platform import DocumentStream

    _store_primary_identity(shadow_row, settings, url="https://Provider.Example.test:443/api/")
    settings.DOCUSEAL_API_URL = "https://provider.example.test/api"
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "primary"])
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        return_value=DocumentStream("primary.pdf", "application/pdf", iter([b"%PDF-primary"])),
    ) as fetch:
        response = client.get(url)
        assert b"".join(response.streaming_content) == b"%PDF-primary"
    assert fetch.call_args.args == ("original-submission",)


@pytest.mark.django_db
def test_primary_comparison_rejects_changed_endpoint_without_fetch(
    shadow_row, actor, client, settings,
):
    from django.urls import reverse

    _store_primary_identity(shadow_row, settings, url="https://provider.example.test/api")
    settings.DOCUSEAL_API_URL = "https://other.example.test/api"
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "primary"])
    with patch("apps.integrations.agreement_platform.stream_submission_document") as fetch:
        assert client.get(url).status_code == 404
    assert not fetch.called


@pytest.mark.django_db
def test_primary_comparison_fails_closed_without_identity(shadow_row, actor, client):
    from django.urls import reverse
    from apps.agreements.models import AgreementPDFShadow

    provenance = dict(shadow_row.provenance)
    provenance.pop("primary_provider_identity", None)
    AgreementPDFShadow.objects.filter(pk=shadow_row.pk).update(provenance=provenance)
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "primary"])
    with patch("apps.integrations.agreement_platform.stream_submission_document") as fetch:
        assert client.get(url).status_code == 404
    assert not fetch.called


@pytest.mark.django_db
def test_forwarding_records_safe_primary_identity(shadow_agreement, settings):
    from apps.agreements.models import AgreementPDFShadow
    from apps.agreements.shadow import enqueue_agreement_pdf_shadow, primary_provider_identity
    from apps.integrations.agreement_platform import SubmissionResult

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = "https://User:Passw0rd@Provider.Example.test:443/api/?token=q"
    result = SubmissionResult(
        "submission-identity", "", "pending", snapshot_for(shadow_agreement),
    )
    with patch("apps.agreements.shadow.async_task"):
        enqueue_agreement_pdf_shadow(shadow_agreement, result)
    row = AgreementPDFShadow.objects.get()
    expected = primary_provider_identity()
    assert row.provenance["primary_provider"] == "docuseal"
    assert row.provenance["primary_provider_identity"] == expected
    assert expected["mode"] == "docuseal"
    rendered = repr(row.provenance["primary_provider_identity"])
    assert "example.test" not in rendered
    assert "Passw0rd" not in rendered
    assert "token=q" not in rendered


@pytest.mark.django_db
def test_ready_detail_renders_paired_preview_and_download_actions(shadow_row, actor, client):
    from django.urls import reverse

    _render_ready(shadow_row)
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_change", args=[shadow_row.pk])
    response = client.get(url)
    assert response.status_code == 200
    text = response.content.decode()
    local = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "local"])
    primary = reverse("admin:agreements_agreementpdfshadow_pdf", args=[shadow_row.pk, "primary"])
    assert f'<iframe src="{local}"' in text
    assert f'<iframe src="{primary}"' in text
    assert f"{local}?disposition=attachment" in text
    assert f"{primary}?disposition=attachment" in text
    assert "Atkārtot salīdzinājumu" not in text


@pytest.mark.django_db
def test_failed_detail_renders_post_retry_control(shadow_row, actor, client, settings):
    from django.urls import reverse
    from apps.agreements.models import AgreementPDFShadow

    settings.AGREEMENT_PDF_SHADOW_ENABLED = True
    AgreementPDFShadow.objects.filter(pk=shadow_row.pk).update(
        status="failed", error_code="render_failed",
    )
    client.force_login(actor)
    url = reverse("admin:agreements_agreementpdfshadow_change", args=[shadow_row.pk])
    response = client.get(url)
    assert response.status_code == 200
    text = response.content.decode()
    retry = reverse("admin:agreements_agreementpdfshadow_retry", args=[shadow_row.pk])
    assert "Atkārtot salīdzinājumu" in text
    assert f'formaction="{retry}"' in text
    assert 'formmethod="post"' in text
