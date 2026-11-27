"""Shared private image cache for the blank agreement template.

Only the worker renders/fetches PDFs. Parents receive raster pages, not PDFs,
provider URLs, tokens, fields, or signing sessions. Cache lives under the
private volume so web/worker processes share it without a new model.

Identity is explicit: every cache entry, manifest URL and queued job carries a
validated ``(backend, signing_path, template_version)``. HTTP callers may pick
the signing path, but the backend and template version are always asserted
against the configured deployment — never taken from the query string. A stale
or configuration-mismatched worker job fails closed before any provider call or
local render.
"""

import hashlib
import logging
from pathlib import Path
from urllib.parse import urlencode

import pymupdf
from django.conf import settings
from django.core.cache.backends.filebased import FileBasedCache
from django.core.exceptions import ImproperlyConfigured

from apps.agreements.pdf_rendering import (
    FIELD_NAMES,
    PRODUCTION_TEMPLATE_VERSION,
    render_agreement_pdf,
)
from apps.integrations import agreement_platform

logger = logging.getLogger(__name__)

DOCUSEAL_BACKEND = "docuseal"
LOCAL_BACKEND = "local"
# Legacy DocuSeal preview identity. Kept symbolic so provider configuration is
# never exposed to the parent surface; the DocuSeal settings stay in the key.
LEGACY_TEMPLATE_VERSION = "docuseal"
_BACKENDS = frozenset({DOCUSEAL_BACKEND, LOCAL_BACKEND})
_SIGNING_PATHS = frozenset({"electronic", "paper"})
_LEGACY_KEY_SETTINGS = (
    "AGREEMENT_PROVIDER_MODE",
    "DOCUSEAL_API_URL",
    "DOCUSEAL_TEMPLATE_ID",
    "DOCUSEAL_TEMPLATE_ALLOWED_ORIGINS",
)


def _cache() -> FileBasedCache:
    return FileBasedCache(
        str(Path(settings.PRIVATE_DOCUMENTS_ROOT) / "agreement-template-preview"),
        {"TIMEOUT": 3600, "OPTIONS": {"MAX_ENTRIES": 100}},
    )


def configured_backend() -> str:
    """Return the deployment-selected preview backend, or fail closed."""
    mode = getattr(settings, "AGREEMENT_DOCUMENT_MODE", None)
    if mode not in _BACKENDS:
        raise ImproperlyConfigured("invalid AGREEMENT_DOCUMENT_MODE")
    return str(mode)


def template_version_for(backend: str) -> str:
    """Return the immutable template identity for a validated backend."""
    if backend == LOCAL_BACKEND:
        return PRODUCTION_TEMPLATE_VERSION
    if backend == DOCUSEAL_BACKEND:
        return LEGACY_TEMPLATE_VERSION
    raise ValueError("invalid_preview_identity")


def validate_identity(
    backend: str, signing_path: str, template_version: str | None = None
) -> str:
    """Validate a preview identity and return its canonical template version.

    Raises ``ValueError`` for an unlisted backend/path or an asserted version
    that does not match the deployment's immutable identity. Callers must run
    this before touching the cache, a provider or the renderer.
    """
    if backend not in _BACKENDS or signing_path not in _SIGNING_PATHS:
        raise ValueError("invalid_preview_identity")
    expected = template_version_for(backend)
    if template_version is not None and template_version != expected:
        raise ValueError("template_version_mismatch")
    return expected


def _cache_identity(
    backend: str, signing_path: str, template_version: str
) -> str:
    parts = [backend, signing_path, template_version]
    if backend == DOCUSEAL_BACKEND:
        parts.extend(str(getattr(settings, name, "")) for name in _LEGACY_KEY_SETTINGS)
    return "|".join(parts)


def _key(backend: str, signing_path: str, template_version: str) -> str:
    identity = _cache_identity(backend, signing_path, template_version)
    return hashlib.sha256(identity.encode()).hexdigest()


def browser_query() -> str:
    """Query string the parent surface may assert for the configured backend.

    Legacy mode keeps the historic URL shape (no identity) to avoid exposing a
    provider name; local mode advertises the fixed backend/template version.
    """
    backend = configured_backend()
    if backend != LOCAL_BACKEND:
        return ""
    return "?" + urlencode(
        {"backend": backend, "template_version": template_version_for(backend)}
    )


def get_preview(
    backend: str = DOCUSEAL_BACKEND,
    signing_path: str = "electronic",
    template_version: str | None = None,
) -> dict | None:
    version = validate_identity(backend, signing_path, template_version)
    result: dict | None = _cache().get(_key(backend, signing_path, version))
    return result


def preview_failed(
    backend: str = DOCUSEAL_BACKEND,
    signing_path: str = "electronic",
    template_version: str | None = None,
) -> bool:
    version = validate_identity(backend, signing_path, template_version)
    return bool(_cache().get(_key(backend, signing_path, version) + ":failed"))


def enqueue_template_preview(
    backend: str = DOCUSEAL_BACKEND,
    signing_path: str = "electronic",
    template_version: str | None = None,
) -> None:
    from django_q.tasks import async_task

    version = validate_identity(backend, signing_path, template_version)
    cache = _cache()
    key = _key(backend, signing_path, version)
    # Best-effort coalescing only: duplicate jobs are safe, read-only, and
    # publish a complete cache value. This is not a business-state lock.
    if cache.add(key + ":pending", True, timeout=90):
        try:
            async_task(
                "apps.agreements.template_preview.refresh_template_preview",
                backend=backend,
                signing_path=signing_path,
                template_version=version,
            )
        except Exception:
            cache.delete(key + ":pending")
            cache.set(key + ":failed", True, timeout=60)
            logger.warning("Agreement template preview queue unavailable")


def _blank_snapshot(signing_path: str) -> dict:
    """No personal data: every inserted value is empty for the parent preview."""
    return {
        "fields": {name: "" for name in FIELD_NAMES},
        "signing_path": signing_path,
    }


def _rasterize(pdfs: list[bytes]) -> list[bytes]:
    pages: list[bytes] = []
    for pdf in pdfs:
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            if (
                document.needs_pass
                or not document.page_count
                or len(pages) + document.page_count > 20
            ):
                raise ValueError("invalid template page count or encryption")
            for page in document:
                rect = page.rect
                if not 0 < rect.width <= 14400 or not 0 < rect.height <= 14400:
                    raise ValueError("invalid template dimensions")
                zoom = min(1400 / rect.width, 1800 / rect.height, 2)
                image = page.get_pixmap(
                    matrix=pymupdf.Matrix(zoom, zoom), alpha=False
                )
                pages.append(image.tobytes("png"))
    if not pages:
        raise ValueError("empty template")
    return pages


def _content_version(
    backend: str,
    signing_path: str,
    template_version: str,
    pages: list[bytes],
) -> str:
    """Content digest bound to the full identity.

    Two identities always receive distinct versions even when their raster
    bytes happen to be identical, so an image URL from one backend/path can
    never be replayed against another.
    """
    digest = hashlib.sha256()
    digest.update(f"{backend}|{signing_path}|{template_version}|".encode())
    for page in pages:
        digest.update(hashlib.sha256(page).digest())
    return digest.hexdigest()


def refresh_template_preview(
    backend: str = DOCUSEAL_BACKEND,
    signing_path: str = "electronic",
    template_version: str | None = None,
) -> None:
    # Validate before any cache/provider/render work: a stale or mismatched
    # worker identity must fail closed rather than publish the wrong raster.
    version = validate_identity(backend, signing_path, template_version)
    # A worker queued under one mode must not fetch or render after the
    # deployment switches to the other mode. Check configuration before any
    # cache write so the rejected job leaves no ready or failed entry.
    if backend != configured_backend():
        raise ValueError("backend_mode_mismatch")
    cache = _cache()
    key = _key(backend, signing_path, version)
    try:
        if cache.get(key):
            return
        if backend == LOCAL_BACKEND:
            pdfs = [
                render_agreement_pdf(
                    _blank_snapshot(signing_path), template_version=version
                )
            ]
        else:
            pdfs = agreement_platform.fetch_template_documents()
        pages = _rasterize(pdfs)
        cache.set(
            key,
            {
                "version": _content_version(
                    backend, signing_path, version, pages
                ),
                "pages": pages,
                "backend": backend,
                "signing_path": signing_path,
                "template_version": version,
            },
        )
        cache.delete(key + ":failed")
    except Exception:
        # Provider/renderer errors may contain URLs, keys or data. Never log
        # their text/payload.
        cache.set(key + ":failed", True, timeout=60)
        logger.warning("Agreement template preview unavailable")
    finally:
        cache.delete(key + ":pending")
