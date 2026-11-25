"""Best-effort shadow forwarding, isolated from primary generation."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django_q.tasks import async_task

from apps.agreements.models import AgreementPDFShadow
from apps.agreements.pdf_rendering import (
    TEMPLATE_VERSION, shadow_renderer_provenance, validate_snapshot,
)

logger = logging.getLogger(__name__)


def _canonical_provider_base(raw_url: str) -> str:
    """Canonical scheme/host/port/path only; credentials and query dropped."""
    parts = urlsplit((raw_url or "").strip())
    if not parts.scheme or not parts.hostname:
        raise ValueError("invalid_provider_base")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    port = parts.port
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = parts.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def primary_provider_identity() -> dict:
    """Nonsecret fingerprint of the active provider mode + canonical API base.

    Stores no raw URL and never touches API keys/tokens. Missing or invalid
    configuration raises so callers can fail closed.
    """
    mode = getattr(settings, "AGREEMENT_PROVIDER_MODE", "stub")
    if mode == "stub":
        canonical = "stub"
    else:
        canonical = _canonical_provider_base(getattr(settings, "DOCUSEAL_API_URL", ""))
    return {"mode": mode,
            "api_base_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def primary_identity_matches(provenance) -> bool:
    """Fail closed for legacy rows and for changed/corrupt configuration."""
    stored = provenance.get("primary_provider_identity") if isinstance(provenance, dict) else None
    if not isinstance(stored, dict):
        return False
    try:
        current = primary_provider_identity()
    except (TypeError, ValueError):
        return False
    return stored == current


def _queue(row) -> None:
    try:
        # Savepoint keeps a broker DB failure from poisoning caller transaction.
        with transaction.atomic():
            async_task("apps.agreements.shadow_tasks.render_agreement_pdf_shadow", row.pk)
    except Exception:
        AgreementPDFShadow.objects.filter(pk=row.pk, status="pending").update(
            status="failed", error_code="queue_failed", updated_at=timezone.now(),
        )
        logger.warning("Agreement PDF shadow queue unavailable")


def enqueue_agreement_pdf_shadow(agreement, result) -> None:
    if not getattr(settings, "AGREEMENT_PDF_SHADOW_ENABLED", False):
        return
    try:
        snapshot = getattr(result, "generation_snapshot", None)
        if snapshot is None or not result.external_id:
            return
        snapshot = validate_snapshot(snapshot)
        provenance = shadow_renderer_provenance()
        identity = primary_provider_identity()
        with transaction.atomic():
            row, created = AgreementPDFShadow.objects.get_or_create(
                agreement=agreement, primary_external_id=result.external_id,
                template_version=TEMPLATE_VERSION,
                defaults={"snapshot": snapshot, "signing_path": snapshot["signing_path"],
                          "provenance": {"renderer": provenance,
                                         "primary_provider": identity["mode"],
                                         "primary_provider_identity": identity}},
            )
            if created:
                _queue(row)
    except Exception:
        # Never log exception text: validation/storage/provider errors may hold PII.
        logger.warning("Agreement PDF shadow forwarding unavailable")


def retry_pdf_shadow(shadow, actor=None) -> None:
    if not getattr(settings, "AGREEMENT_PDF_SHADOW_ENABLED", False):
        raise ValueError("shadow_disabled")
    with transaction.atomic():
        row = AgreementPDFShadow.objects.select_for_update().get(pk=shadow.pk)
        if not row.can_retry:
            raise ValueError("shadow_not_retryable")
        row.status = "pending"
        row.error_code = ""
        row.save(update_fields=["status", "error_code", "updated_at"])
        _queue(row)


def delete_shadow_file(storage, name) -> None:
    try:
        storage.delete(name)
    except Exception:
        logger.warning("Agreement PDF shadow file cleanup unavailable")


@receiver(post_delete, sender=AgreementPDFShadow)
def _remove_shadow_file(sender, instance, **kwargs):
    if instance.file.name:
        storage, name = instance.file.storage, instance.file.name
        transaction.on_commit(lambda: delete_shadow_file(storage, name))
