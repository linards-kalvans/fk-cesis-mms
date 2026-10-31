"""The parent preview exposes blank template images, never a signing session/PDF."""

from unittest.mock import MagicMock, Mock, patch

import pymupdf
import pytest
from django.urls import reverse


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
