"""The parent preview exposes blank template images, never a signing session/PDF."""

from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, Mock, patch

import pymupdf
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

LOCAL_TEMPLATE_VERSION = "v1-2026-11"


@pytest.fixture
def preview_cache(settings, tmp_path):
    settings.PRIVATE_DOCUMENTS_ROOT = tmp_path
    from apps.agreements import template_preview

    return template_preview


def pdf_bytes(pages=2):
    with pymupdf.open() as document:
        for number in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"Agreement template page {number + 1}")
        return document.tobytes()


def test_refresh_renders_all_pages_and_caches_without_submission(preview_cache):
    with patch("apps.integrations.agreement_platform.fetch_template_documents", return_value=[pdf_bytes()]) as fetch:
        preview_cache.refresh_template_preview()
        preview_cache.refresh_template_preview()
    result = preview_cache.get_preview()
    assert len(result["pages"]) == 2
    assert all(page.startswith(b"\x89PNG") for page in result["pages"])
    assert len(result["version"]) == 64
    fetch.assert_called_once()


def test_multiple_documents_preserve_page_order(preview_cache):
    with patch("apps.integrations.agreement_platform.fetch_template_documents", return_value=[pdf_bytes(2), pdf_bytes(1)]):
        preview_cache.refresh_template_preview()
    pages = preview_cache.get_preview()["pages"]
    assert len(pages) == 3
    assert pages[0] == pages[2]
    assert pages[0] != pages[1]


@pytest.mark.parametrize("payload", [b"not a PDF", pdf_bytes(21)])
def test_invalid_or_oversized_page_count_fails_closed(preview_cache, payload):
    with patch("apps.integrations.agreement_platform.fetch_template_documents", return_value=[payload]):
        preview_cache.refresh_template_preview()
    assert preview_cache.get_preview() is None
    assert preview_cache.preview_failed()


def test_provider_identity_separates_cached_templates(preview_cache, settings):
    with patch("apps.integrations.agreement_platform.fetch_template_documents", return_value=[pdf_bytes()]):
        preview_cache.refresh_template_preview()
    settings.DOCUSEAL_TEMPLATE_ID = "another-template"
    assert preview_cache.get_preview() is None


@pytest.mark.django_db
def test_manifest_requires_verified_parent(client, preview_cache):
    with patch("django_q.tasks.async_task") as enqueue:
        response = client.get(reverse("registrations:agreement-template-preview"))
    assert response.status_code == 404
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_inactive_parent_cannot_access_preview(verified_client, parent_account, preview_cache):
    parent_account.is_active = False
    parent_account.save()
    assert verified_client.get(reverse("registrations:agreement-template-preview")).status_code == 404


@pytest.mark.django_db
def test_manifest_returns_image_urls_only(verified_client, preview_cache):
    preview_cache.refresh_template_preview()
    response = verified_client.get(reverse("registrations:agreement-template-preview"))
    assert response.status_code == 200
    data = response.json()
    assert data["pages"]
    assert all(url.startswith("/register/agreement-preview/") for url in data["pages"])
    assert "no-store" in response["Cache-Control"]
    assert "docuseal" not in response.content.decode().lower()
    image = verified_client.get(data["pages"][0])
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    assert "attachment" not in image.get("Content-Disposition", "")
    assert "no-store" in image["Cache-Control"]


@pytest.mark.django_db
def test_page_denies_anonymous_and_invalid_version_or_page(verified_client, client, preview_cache):
    preview_cache.refresh_template_preview()
    data = verified_client.get(reverse("registrations:agreement-template-preview")).json()
    assert client.get(data["pages"][0]).status_code == 404
    version = preview_cache.get_preview()["version"]
    for version_value, page in [(version, 0), (version, 999), ("0" * 64, 1)]:
        url = reverse("registrations:agreement-template-page", args=[version_value, page])
        assert verified_client.get(url).status_code == 404


@pytest.mark.django_db
def test_pending_queues_background_fetch_once(verified_client, preview_cache):
    with patch("django_q.tasks.async_task") as enqueue:
        for _ in range(2):
            response = verified_client.get(reverse("registrations:agreement-template-preview"))
            assert response.status_code == 202
    enqueue.assert_called_once()


@pytest.mark.django_db
def test_broker_failure_returns_localized_unavailable(verified_client, preview_cache):
    with patch("django_q.tasks.async_task", side_effect=RuntimeError("secret")):
        response = verified_client.get(reverse("registrations:agreement-template-preview"))
    assert response.status_code == 503
    assert "secret" not in response.content.decode()


@pytest.mark.django_db
def test_post_cannot_trigger_refresh(verified_client, preview_cache):
    with patch("django_q.tasks.async_task") as enqueue:
        assert verified_client.post(reverse("registrations:agreement-template-preview")).status_code == 405
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_provider_error_is_localized_and_does_not_leak(verified_client, preview_cache):
    with patch("apps.integrations.agreement_platform.fetch_template_documents", side_effect=RuntimeError("secret-provider-url")):
        preview_cache.refresh_template_preview()
    response = verified_client.get(reverse("registrations:agreement-template-preview"))
    assert response.status_code == 503
    assert "secret-provider-url" not in response.content.decode()
    assert "nav pieejams" in response.json()["message"]


@pytest.mark.django_db
def test_preview_above_preferences_and_not_on_readonly_workspace(verified_client, draft_application):
    url = reverse("registrations:application-workspace", args=[draft_application.pk])
    html = verified_client.get(url).content.decode()
    assert 'data-agreement-preview' in html
    assert html.index('data-agreement-preview') < html.index('id_preferred_agreement_signing')
    assert 'agreement_preview.js' in html
    assert 'data-preview-expand' in html
    draft_application.status = "submitted"
    draft_application.save()
    assert 'data-agreement-preview' not in verified_client.get(url).content.decode()


@pytest.fixture
def docuseal_config(settings):
    settings.DOCUSEAL_API_URL = "https://docuseal.example/api"
    settings.DOCUSEAL_API_KEY = "test-key"
    settings.DOCUSEAL_TEMPLATE_ID = "42"
    settings.DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS = []


@pytest.mark.parametrize("origin", ["https://agreements.mplytics.eu", "https://agreements.mplytics.eu:443/"])
def test_internal_api_can_download_explicit_public_origin(docuseal_config, settings, origin):
    from apps.integrations import docuseal

    settings.DOCUSEAL_API_URL = "http://docuseal:3000/api"
    settings.DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS = [origin]
    metadata = Mock()
    metadata.json.return_value = {"documents": [{"url": "https://agreements.mplytics.eu/file/sample.pdf"}]}
    blob = MagicMock(status_code=200)
    blob.__enter__.return_value = blob
    payload = pdf_bytes()
    blob.iter_content.return_value = [payload]
    with patch("apps.integrations.docuseal._request", return_value=metadata) as api, patch("requests.get", return_value=blob) as download:
        assert docuseal.fetch_template_documents() == [payload]
    api.assert_called_once_with("GET", "http://docuseal:3000/api/templates/42", "test-key", allow_redirects=False)
    assert download.call_args.args == ("https://agreements.mplytics.eu/file/sample.pdf",)
    assert download.call_args.kwargs["allow_redirects"] is False
    assert "headers" not in download.call_args.kwargs


@pytest.mark.parametrize("url", [
    "http://agreements.mplytics.eu/file/sample.pdf",
    "https://agreements.mplytics.eu:444/file/sample.pdf",
    "https://agreements.mplytics.eu:0/file/sample.pdf",
    "https://agreements.mplytics.eu.evil.example/file/sample.pdf",
    "https://evil.agreements.mplytics.eu/file/sample.pdf",
    "https://user:pass@agreements.mplytics.eu/file/sample.pdf",
    "https://agreements.mplytics.eu@evil.example/file/sample.pdf",
    "//agreements.mplytics.eu/file/sample.pdf",
])
def test_extra_origin_is_exact_not_a_wildcard(docuseal_config, settings, url):
    from apps.integrations import docuseal
    from apps.integrations.agreement_platform import AgreementPlatformConfigError

    settings.DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS = ["https://agreements.mplytics.eu"]
    response = Mock()
    response.json.return_value = {"documents": [{"url": url}]}
    with patch("apps.integrations.docuseal._request", return_value=response), patch("requests.get") as download:
        with pytest.raises(AgreementPlatformConfigError):
            docuseal.fetch_template_documents()
    download.assert_not_called()


@pytest.mark.parametrize("origin", ["*", "https://*.mplytics.eu", "https://agreements.mplytics.eu/path", "https://agreements.mplytics.eu?q=1", "https://agreements.mplytics.eu#fragment", "https://user@agreements.mplytics.eu"])
def test_invalid_configured_origins_fail_closed(docuseal_config, settings, origin):
    from apps.integrations import docuseal
    from apps.integrations.agreement_platform import AgreementPlatformConfigError

    settings.DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS = [origin]
    response = Mock()
    response.json.return_value = {"documents": [{"url": "https://docuseal.example/sample.pdf"}]}
    with patch("apps.integrations.docuseal._request", return_value=response), patch("requests.get") as download:
        with pytest.raises(AgreementPlatformConfigError):
            docuseal.fetch_template_documents()
    download.assert_not_called()


def test_trust_configuration_change_invalidates_failed_preview(preview_cache, settings):
    with patch("apps.integrations.agreement_platform.fetch_template_documents", side_effect=RuntimeError()):
        preview_cache.refresh_template_preview()
    assert preview_cache.preview_failed()
    settings.DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS = ["https://agreements.mplytics.eu"]
    assert not preview_cache.preview_failed()


@pytest.mark.django_db
def test_split_origin_template_renders_through_parent_endpoints(docuseal_config, settings, preview_cache, verified_client):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = "http://docuseal:3000/api"
    settings.DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS = ["https://agreements.mplytics.eu"]
    metadata = Mock()
    metadata.json.return_value = {"documents": [{"url": "https://agreements.mplytics.eu/file/sample.pdf"}]}
    blob = MagicMock(status_code=200)
    blob.__enter__.return_value = blob
    blob.iter_content.return_value = [pdf_bytes()]
    with patch("apps.integrations.docuseal._request", return_value=metadata), patch("requests.get", return_value=blob):
        preview_cache.refresh_template_preview()
    manifest = verified_client.get(reverse("registrations:agreement-template-preview"))
    assert manifest.status_code == 200
    assert len(manifest.json()["pages"]) == 2
    for url in manifest.json()["pages"]:
        image = verified_client.get(url)
        assert image.status_code == 200
        assert image.content.startswith(b"\x89PNG")


def test_fetches_blank_template_documents_without_post_or_key_on_blob(docuseal_config):
    from apps.integrations import docuseal

    metadata = Mock(status_code=200)
    metadata.json.return_value = {"documents": [{"url": "https://docuseal.example/blobs/sample.pdf"}]}
    document = MagicMock(status_code=200)
    document.__enter__.return_value = document
    document.iter_content.return_value = [pdf_bytes()]
    with patch("apps.integrations.docuseal._request", return_value=metadata) as api, patch("requests.get", return_value=document) as download:
        result = docuseal.fetch_template_documents()
    assert result[0].startswith(b"%PDF")
    api.assert_called_once_with("GET", "https://docuseal.example/api/templates/42", "test-key", allow_redirects=False)
    assert "headers" not in download.call_args.kwargs
    assert download.call_args.kwargs["allow_redirects"] is False
    document.__exit__.assert_called_once()


@pytest.mark.parametrize("url", ["http://docuseal.example/a.pdf", "https://evil.example/a.pdf", "https://user:pass@docuseal.example/a.pdf"])
def test_template_download_rejects_untrusted_urls(docuseal_config, url):
    from apps.integrations import docuseal
    from apps.integrations.agreement_platform import AgreementPlatformConfigError

    response = Mock(status_code=200)
    response.json.return_value = {"documents": [{"url": url}]}
    with patch("apps.integrations.docuseal._request", return_value=response), patch("requests.get") as download:
        with pytest.raises(AgreementPlatformConfigError):
            docuseal.fetch_template_documents()
    download.assert_not_called()


@pytest.mark.parametrize("payload", [None, [], {}, {"documents": []}, {"documents": [None]}, {"documents": [{"url": 123}]}])
def test_template_metadata_must_contain_documents(docuseal_config, payload):
    from apps.integrations import docuseal
    from apps.integrations.agreement_platform import AgreementPlatformConfigError

    response = Mock(status_code=200)
    response.json.return_value = payload
    with patch("apps.integrations.docuseal._request", return_value=response):
        with pytest.raises(AgreementPlatformConfigError):
            docuseal.fetch_template_documents()


@pytest.mark.parametrize("status", [302, 404, 500])
def test_blob_redirects_and_failures_are_not_followed(docuseal_config, status):
    from apps.integrations import docuseal
    from apps.integrations.agreement_platform import AgreementPlatformTransientError

    metadata = Mock()
    metadata.json.return_value = {"documents": [{"url": "https://docuseal.example/sample.pdf"}]}
    blob = MagicMock(status_code=status)
    blob.__enter__.return_value = blob
    with patch("apps.integrations.docuseal._request", return_value=metadata), patch("requests.get", return_value=blob):
        with pytest.raises(AgreementPlatformTransientError):
            docuseal.fetch_template_documents()
    blob.iter_content.assert_not_called()
    blob.__exit__.assert_called_once()


def test_oversized_blob_is_rejected_and_closed(docuseal_config):
    from apps.integrations import docuseal
    from apps.integrations.agreement_platform import AgreementPlatformConfigError

    metadata = Mock()
    metadata.json.return_value = {"documents": [{"url": "https://docuseal.example/sample.pdf"}]}
    blob = MagicMock(status_code=200)
    blob.__enter__.return_value = blob
    blob.iter_content.return_value = iter([b"x" * (1024 * 1024)] * 21)
    with patch("apps.integrations.docuseal._request", return_value=metadata), patch("requests.get", return_value=blob):
        with pytest.raises(AgreementPlatformConfigError):
            docuseal.fetch_template_documents()
    blob.__exit__.assert_called_once()


# ---------------------------------------------------------------------------
# Task 5 — backend/version/signing-path preview identity.
#
# Proposed interface (tests only; implementation pending):
#   template_preview.refresh_template_preview(backend=..., signing_path=...)
#   template_preview.get_preview(backend=..., signing_path=...)
#   template_preview.preview_failed(backend=..., signing_path=...)
#   template_preview.enqueue_template_preview(backend=..., signing_path=...)
#   manifest: /register/agreement-preview/?backend=<b>&signing_path=<p>
#   image:    /register/agreement-preview/<content-version>/<page>/
#             ?backend=<b>&signing_path=<p>
# Legacy no-argument callers keep their current DocuSeal/electronic identity.
# ---------------------------------------------------------------------------


def _manifest(backend="local", signing_path="electronic"):
    return (
        reverse("registrations:agreement-template-preview")
        + f"?backend={backend}&signing_path={signing_path}"
    )


def _query(url):
    return parse_qs(urlparse(url).query)


def _real_renderer():
    from apps.agreements import pdf_rendering

    return pdf_rendering.render_agreement_pdf


def _run_queued_identity(preview_cache, queued_kwargs):
    """Run the worker for an identity captured while it was configured.

    Failing closed may be raised as a configuration/identity error or be a
    silent no-op; both are acceptable. Any other exception is a real defect.
    """
    try:
        preview_cache.refresh_template_preview(**queued_kwargs)
    except (ValueError, ImproperlyConfigured):
        pass


def test_cache_separates_backend_signing_path_and_content(preview_cache, settings):
    # Each worker invocation uses the backend configured at that moment; a
    # legitimate mode change never asks one worker to serve another mode.
    with (
        patch(
            "apps.integrations.agreement_platform.fetch_template_documents",
            return_value=[pdf_bytes(1)],
        ) as provider,
        patch(
            "apps.agreements.template_preview.render_agreement_pdf",
            side_effect=lambda *args, **kwargs: pdf_bytes(2),
        ) as renderer,
    ):
        settings.AGREEMENT_DOCUMENT_MODE = "docuseal"
        preview_cache.refresh_template_preview(
            backend="docuseal", signing_path="electronic"
        )
        settings.AGREEMENT_DOCUMENT_MODE = "local"
        preview_cache.refresh_template_preview(
            backend="local", signing_path="electronic"
        )
        preview_cache.refresh_template_preview(backend="local", signing_path="paper")

    docuseal = preview_cache.get_preview(
        backend="docuseal", signing_path="electronic"
    )
    local_electronic = preview_cache.get_preview(
        backend="local", signing_path="electronic"
    )
    local_paper = preview_cache.get_preview(backend="local", signing_path="paper")

    assert docuseal is not None
    assert local_electronic is not None
    assert local_paper is not None
    assert docuseal["pages"] != local_electronic["pages"]
    assert local_electronic["version"] != local_paper["version"]
    assert preview_cache.get_preview(backend="docuseal", signing_path="paper") is None
    provider.assert_called_once()
    assert renderer.call_count == 2


def test_worker_queue_carries_the_validated_identity(preview_cache, settings):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch("django_q.tasks.async_task") as enqueue:
        preview_cache.enqueue_template_preview(
            backend="local", signing_path="paper"
        )

    enqueue.assert_called_once()
    args, kwargs = enqueue.call_args
    assert args[0] == "apps.agreements.template_preview.refresh_template_preview"
    assert kwargs["backend"] == "local"
    assert kwargs["signing_path"] == "paper"
    assert kwargs["template_version"] == LOCAL_TEMPLATE_VERSION


def test_queued_docuseal_identity_cannot_call_provider_after_switch_to_local(
    preview_cache, settings
):
    """A DocuSeal render queued before local mode takes effect must not fetch."""
    settings.AGREEMENT_DOCUMENT_MODE = "docuseal"
    with patch("django_q.tasks.async_task") as enqueue:
        preview_cache.enqueue_template_preview(signing_path="electronic")

    _args, queued = enqueue.call_args
    assert queued["backend"] == "docuseal"
    assert queued["template_version"] == "docuseal"

    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with (
        patch(
            "apps.integrations.agreement_platform.fetch_template_documents"
        ) as provider,
        patch(
            "apps.agreements.template_preview.render_agreement_pdf"
        ) as renderer,
    ):
        _run_queued_identity(preview_cache, queued)

    provider.assert_not_called()
    renderer.assert_not_called()
    assert (
        preview_cache.get_preview(
            backend="docuseal",
            signing_path="electronic",
            template_version="docuseal",
        )
        is None
    )
    assert not preview_cache.preview_failed(
        backend="docuseal",
        signing_path="electronic",
        template_version="docuseal",
    )


def test_queued_local_identity_cannot_render_after_switch_to_docuseal(
    preview_cache, settings
):
    """A local render queued before legacy mode takes effect must not render."""
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch("django_q.tasks.async_task") as enqueue:
        preview_cache.enqueue_template_preview(
            backend="local", signing_path="paper"
        )

    _args, queued = enqueue.call_args
    assert queued["backend"] == "local"
    assert queued["template_version"] == LOCAL_TEMPLATE_VERSION

    settings.AGREEMENT_DOCUMENT_MODE = "docuseal"
    with (
        patch(
            "apps.agreements.template_preview.render_agreement_pdf"
        ) as renderer,
        patch(
            "apps.integrations.agreement_platform.fetch_template_documents"
        ) as provider,
    ):
        _run_queued_identity(preview_cache, queued)

    renderer.assert_not_called()
    provider.assert_not_called()
    assert preview_cache.get_preview(backend="local", signing_path="paper") is None
    assert not preview_cache.preview_failed(backend="local", signing_path="paper")


@pytest.mark.django_db
def test_invalid_configured_mode_fails_closed_over_http(
    verified_client, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "unsupported"
    with patch("django_q.tasks.async_task") as enqueue:
        manifest = verified_client.get(
            reverse("registrations:agreement-template-preview")
        )
        page = verified_client.get(
            reverse(
                "registrations:agreement-template-page", args=["0" * 64, 1]
            )
        )
    assert manifest.status_code == 400
    assert page.status_code == 400
    enqueue.assert_not_called()


@pytest.mark.parametrize(
    ("backend", "signing_path"),
    [("other", "electronic"), ("local", "wet-ink"), ("", "paper")],
)
def test_refresh_rejects_unlisted_identity(preview_cache, backend, signing_path):
    with patch(
        "apps.integrations.agreement_platform.fetch_template_documents"
    ) as provider:
        with pytest.raises(ValueError):
            preview_cache.refresh_template_preview(
                backend=backend, signing_path=signing_path
            )
    provider.assert_not_called()


@pytest.mark.parametrize(
    ("backend", "signing_path", "template_version"),
    [
        ("local", "electronic", "shadow-v1-2026-11"),
        ("local", "paper", "v2-2027-01"),
        ("docuseal", "electronic", LOCAL_TEMPLATE_VERSION),
    ],
)
def test_worker_job_with_a_mismatched_version_fails_closed_before_render(
    preview_cache, settings, backend, signing_path, template_version
):
    # Isolate the version check: the configured mode matches the queued backend.
    settings.AGREEMENT_DOCUMENT_MODE = backend
    with (
        patch(
            "apps.integrations.agreement_platform.fetch_template_documents"
        ) as provider,
        patch("apps.agreements.template_preview.render_agreement_pdf") as renderer,
    ):
        with pytest.raises(ValueError):
            preview_cache.refresh_template_preview(
                backend=backend,
                signing_path=signing_path,
                template_version=template_version,
            )
    provider.assert_not_called()
    renderer.assert_not_called()


@pytest.mark.django_db
def test_manifest_and_image_urls_carry_the_selected_identity(
    verified_client, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        side_effect=lambda *args, **kwargs: pdf_bytes(2),
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="paper"
        )

    response = verified_client.get(_manifest(signing_path="paper"))
    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "local"
    assert data["signing_path"] == "paper"
    assert data["template_version"] == LOCAL_TEMPLATE_VERSION
    assert len(data["version"]) == 64
    assert data["pages"]
    for url in data["pages"]:
        query = _query(url)
        assert query["backend"] == ["local"]
        assert query["signing_path"] == ["paper"]
        assert url.startswith(
            f"/register/agreement-preview/{data['version']}/"
        )
        assert "pdf" not in url.lower()

    image = verified_client.get(data["pages"][0])
    assert image.status_code == 200
    assert image["Content-Type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")
    assert "no-store" in image["Cache-Control"]
    assert "attachment" not in image.get("Content-Disposition", "")


@pytest.mark.django_db
def test_stale_image_version_is_rejected_after_a_newer_render(
    verified_client, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        side_effect=lambda *args, **kwargs: pdf_bytes(1),
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="electronic"
        )
    stale = verified_client.get(_manifest()).json()
    stale_url = stale["pages"][0]

    preview_cache._cache().clear()
    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        side_effect=lambda *args, **kwargs: pdf_bytes(2),
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="electronic"
        )
    fresh = verified_client.get(_manifest()).json()
    assert fresh["version"] != stale["version"]
    assert verified_client.get(fresh["pages"][0]).status_code == 200
    assert verified_client.get(stale_url).status_code == 404


@pytest.mark.django_db
def test_unlisted_query_identity_is_rejected_without_enqueue(
    verified_client, preview_cache
):
    with patch("django_q.tasks.async_task") as enqueue:
        for url in (
            _manifest(backend="other"),
            _manifest(signing_path="wet-ink"),
        ):
            response = verified_client.get(url)
            assert response.status_code == 400
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_http_cannot_override_the_configured_backend_or_template_version(
    verified_client, preview_cache, settings
):
    # Defaults to the legacy backend; a caller cannot force local preview.
    settings.AGREEMENT_DOCUMENT_MODE = "docuseal"
    with patch("django_q.tasks.async_task") as enqueue:
        assert verified_client.get(_manifest(backend="local")).status_code == 400
        assert verified_client.get(_manifest(backend="other")).status_code == 400
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_http_rejects_a_mismatched_template_version(
    verified_client, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch("django_q.tasks.async_task") as enqueue:
        response = verified_client.get(
            _manifest() + "&template_version=shadow-v1-2026-11"
        )
        assert response.status_code == 400
    enqueue.assert_not_called()


@pytest.mark.django_db
def test_image_url_cannot_assert_a_different_backend(
    verified_client, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        side_effect=lambda *args, **kwargs: pdf_bytes(1),
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="paper"
        )
    page_url = verified_client.get(_manifest(signing_path="paper")).json()["pages"][0]
    tampered = page_url.replace("backend=local", "backend=docuseal")
    assert verified_client.get(tampered).status_code == 400


@pytest.mark.django_db
def test_pending_and_failure_are_bounded_per_identity(
    verified_client, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch("django_q.tasks.async_task") as enqueue:
        assert verified_client.get(_manifest(signing_path="paper")).status_code == 202
        assert (
            verified_client.get(_manifest(signing_path="electronic")).status_code
            == 202
        )
    assert enqueue.call_count == 2
    assert enqueue.call_args_list[0].kwargs["signing_path"] == "paper"
    assert enqueue.call_args_list[1].kwargs["signing_path"] == "electronic"

    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        side_effect=RuntimeError("secret-render-path"),
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="paper"
        )

    failed = verified_client.get(_manifest(signing_path="paper"))
    assert failed.status_code == 503
    assert "secret-render-path" not in failed.content.decode()
    assert "nav pieejams" in failed.json()["message"]
    assert (
        verified_client.get(_manifest(signing_path="electronic")).status_code == 202
    )


@pytest.mark.parametrize("payload", [b"not a PDF", pdf_bytes(21)])
def test_local_render_limits_fail_closed_per_identity(
    preview_cache, settings, payload
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        return_value=payload,
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="paper"
        )

    assert preview_cache.get_preview(backend="local", signing_path="paper") is None
    assert preview_cache.preview_failed(backend="local", signing_path="paper")
    assert not preview_cache.preview_failed(
        backend="local", signing_path="electronic"
    )


@pytest.mark.django_db
def test_anonymous_and_inactive_parents_cannot_select_a_preview_identity(
    client, verified_client, parent_account, preview_cache, settings
):
    settings.AGREEMENT_DOCUMENT_MODE = "local"
    with patch(
        "apps.agreements.template_preview.render_agreement_pdf",
        side_effect=lambda *args, **kwargs: pdf_bytes(1),
    ):
        preview_cache.refresh_template_preview(
            backend="local", signing_path="paper"
        )
    pages = verified_client.get(_manifest(signing_path="paper")).json()["pages"]

    assert client.get(_manifest(signing_path="paper")).status_code == 404
    assert client.get(pages[0]).status_code == 404

    parent_account.is_active = False
    parent_account.save()
    assert verified_client.get(_manifest(signing_path="paper")).status_code == 404
    assert verified_client.get(pages[0]).status_code == 404


@pytest.mark.django_db
def test_local_blank_preview_is_real_png_only_without_pii_or_provider(
    preview_cache, settings
):
    from apps.agreements.models import Agreement

    settings.AGREEMENT_DOCUMENT_MODE = "local"
    render = _real_renderer()
    with (
        patch(
            "apps.agreements.template_preview.render_agreement_pdf", side_effect=render
        ) as renderer,
        patch(
            "apps.integrations.agreement_platform.fetch_template_documents"
        ) as provider_fetch,
        patch(
            "apps.integrations.agreement_platform.create_submission"
        ) as provider_create,
    ):
        for signing_path in ("paper", "electronic"):
            preview_cache.refresh_template_preview(
                backend="local", signing_path=signing_path
            )

    provider_fetch.assert_not_called()
    provider_create.assert_not_called()
    assert not Agreement.objects.exists()

    paper = preview_cache.get_preview(backend="local", signing_path="paper")
    electronic = preview_cache.get_preview(
        backend="local", signing_path="electronic"
    )
    assert paper is not None
    assert electronic is not None
    assert paper["pages"]
    assert electronic["pages"]
    assert all(page.startswith(b"\x89PNG") for page in paper["pages"])
    assert all(page.startswith(b"\x89PNG") for page in electronic["pages"])
    assert paper["pages"] != electronic["pages"]
    assert paper["version"] != electronic["version"]
    assert paper["template_version"] == LOCAL_TEMPLATE_VERSION
    assert electronic["template_version"] == LOCAL_TEMPLATE_VERSION

    snapshots = [call.args[0] for call in renderer.call_args_list]
    assert [snapshot["signing_path"] for snapshot in snapshots] == [
        "paper",
        "electronic",
    ]
    for snapshot in snapshots:
        assert snapshot["fields"]
        assert all(value == "" for value in snapshot["fields"].values())
    assert [call.kwargs["template_version"] for call in renderer.call_args_list] == [
        LOCAL_TEMPLATE_VERSION,
        LOCAL_TEMPLATE_VERSION,
    ]
