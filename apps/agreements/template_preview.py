"""Shared private image cache for the blank agreement template.

    Only the worker fetches PDFs. Parents receive raster pages, not PDFs,
    provider URLs, tokens, fields, or signing sessions. Cache lives under the
    private volume so web/worker processes share it without a new model.
"""

import hashlib
import logging
from pathlib import Path

import pymupdf
from django.conf import settings
from django.core.cache.backends.filebased import FileBasedCache

from apps.integrations import agreement_platform

logger = logging.getLogger(__name__)


def _cache() -> FileBasedCache:
    return FileBasedCache(
        str(Path(settings.PRIVATE_DOCUMENTS_ROOT) / "agreement-template-preview"),
        {"TIMEOUT": 3600, "OPTIONS": {"MAX_ENTRIES": 100}},
    )


def _key() -> str:
    identity = "|".join(str(getattr(settings, name, "")) for name in (
        "AGREEMENT_PROVIDER_MODE", "DOCUSEAL_API_URL", "DOCUSEAL_TEMPLATE_ID",
    ))
    return hashlib.sha256(identity.encode()).hexdigest()


def get_preview() -> dict | None:
    result: dict | None = _cache().get(_key())
    return result


def preview_failed() -> bool:
    return bool(_cache().get(_key() + ":failed"))


def enqueue_template_preview() -> None:
    from django_q.tasks import async_task

    cache = _cache()
    # Best-effort coalescing only: duplicate jobs are safe, read-only, and
    # publish a complete cache value. This is not a business-state lock.
    if cache.add(_key() + ":pending", True, timeout=90):
        try:
            async_task("apps.agreements.template_preview.refresh_template_preview")
        except Exception:
            cache.delete(_key() + ":pending")
            cache.set(_key() + ":failed", True, timeout=60)
            logger.warning("Agreement template preview queue unavailable")


def refresh_template_preview() -> None:
    cache, key = _cache(), _key()
    try:
        if cache.get(key):
            return
        pages: list[bytes] = []
        digest = hashlib.sha256()
        for pdf in agreement_platform.fetch_template_documents():
            digest.update(pdf)
            with pymupdf.open(stream=pdf, filetype="pdf") as document:
                if document.needs_pass or not document.page_count or len(pages) + document.page_count > 20:
                    raise ValueError("invalid template page count or encryption")
                for page in document:
                    rect = page.rect
                    if not 0 < rect.width <= 14400 or not 0 < rect.height <= 14400:
                        raise ValueError("invalid template dimensions")
                    zoom = min(1400 / rect.width, 1800 / rect.height, 2)
                    image = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    pages.append(image.tobytes("png"))
        if not pages:
            raise ValueError("empty template")
        cache.set(key, {"version": digest.hexdigest(), "pages": pages})
        cache.delete(key + ":failed")
    except Exception:
        # Provider errors may contain URLs/keys. Never log their text/payload.
        cache.set(key + ":failed", True, timeout=60)
        logger.warning("Agreement template preview unavailable")
    finally:
        cache.delete(key + ":pending")
