"""Shadow-only worker. Never imports signing, notifications or billing services."""

import hashlib
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.agreements.models import AgreementPDFShadow
from apps.agreements.pdf_rendering import render_shadow_pdf, shadow_renderer_provenance
from apps.agreements.shadow import delete_shadow_file


def _failed(pk, code):
    AgreementPDFShadow.objects.filter(pk=pk, status="pending").update(
        status="failed", error_code=code, updated_at=timezone.now(),
    )


def render_agreement_pdf_shadow(shadow_id: int) -> None:
    row = AgreementPDFShadow.objects.filter(pk=shadow_id).first()
    if row is None or row.status != "pending":
        return
    if not getattr(settings, "AGREEMENT_PDF_SHADOW_ENABLED", False):
        _failed(row.pk, "disabled")
        return
    temporary_name = ""
    published = False
    storage = row.file.storage
    try:
        if row.provenance.get("renderer") != shadow_renderer_provenance():
            _failed(row.pk, "version_mismatch")
            return
        pdf = render_shadow_pdf(row.snapshot, template_version=row.template_version)
        if not pdf.startswith(b"%PDF-") or len(pdf) > 20 * 1024 * 1024:
            raise ValueError("invalid_output")
        temporary_name = storage.save(
            f"agreements/shadow/{uuid.uuid4().hex}.pdf", ContentFile(pdf),
        )
        with transaction.atomic():
            winner = AgreementPDFShadow.objects.select_for_update().filter(pk=shadow_id).first()
            if winner is None or winner.status != "pending":
                return
            if not getattr(settings, "AGREEMENT_PDF_SHADOW_ENABLED", False):
                _failed(row.pk, "disabled")
                return
            winner.file.name = temporary_name
            winner.file_size = len(pdf)
            winner.sha256 = hashlib.sha256(pdf).hexdigest()
            winner.completed_at = timezone.now()
            winner.snapshot = {}
            winner.status = "ready"
            winner.error_code = ""
            winner.save(update_fields=["file", "file_size", "sha256", "completed_at",
                                       "snapshot", "status", "error_code", "updated_at"])
        published = True
    except Exception:
        _failed(row.pk, "render_failed")
    finally:
        if temporary_name and not published:
            delete_shadow_file(storage, temporary_name)
