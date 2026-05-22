"""Admin re-OCR action enqueues a fresh OCR job.

P3.5 Phase 5 — admin can retrigger OCR on a Document by selecting it
in Django admin and running the "Re-run OCR" action. The action sets
ocr_status back to PENDING and hands the job to django-q2.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.base import ContentFile
from django.test import RequestFactory

from apps.accounts.models import ParentAccount
from apps.documents.admin import DocumentAdmin
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _make_doc(
    kind: str = "guardian_identity",
    ocr_status: str = "completed",
) -> Document:
    account = ParentAccount.objects.create(
        email=f"admin-reocr-{kind}-{ocr_status}@example.com",
        phone="+37120000099",
    )
    app = RegistrationApplication.objects.create(
        parent_account=account,
        guardian_email=account.email,
        guardian_full_name="X",
        guardian_personal_id="010101-00099",
        guardian_phone="+37120000099",
        guardian_declared_address="Riga 99",
        member_full_name="Y",
        member_personal_id="010125-00099",
        member_birth_date="2025-01-01",
    )
    doc: Document = Document.objects.create(
        application=app,
        kind=kind,
        file=ContentFile(b"x", name="x.png"),
        original_filename="x.png",
        content_type="image/png",
        file_size=1,
        ocr_status=ocr_status,
    )
    return doc


def test_admin_re_ocr_enqueues_job_and_resets_status():
    doc = _make_doc(kind="guardian_identity", ocr_status="completed")

    site = AdminSite()
    admin_instance = DocumentAdmin(Document, site)
    request = RequestFactory().post("/admin/documents/document/")
    request.session = {}  # type: ignore[attr-defined]
    setattr(request, "_messages", FallbackStorage(request))
    queryset = Document.objects.filter(pk=doc.pk)

    enqueued: list[int] = []
    with patch(
        "apps.documents.admin.enqueue_ocr_job",
        side_effect=lambda did: enqueued.append(did),
    ):
        admin_instance.re_run_ocr(request, queryset)

    doc.refresh_from_db()
    assert doc.ocr_status == Document.OcrStatus.PENDING
    assert doc.ocr_error_code == ""
    assert enqueued == [doc.id]


def test_admin_re_ocr_skips_kinds_outside_ocr_scope():
    portrait = _make_doc(kind="member_portrait", ocr_status="not_requested")

    site = AdminSite()
    admin_instance = DocumentAdmin(Document, site)
    request = RequestFactory().post("/admin/documents/document/")
    request.session = {}  # type: ignore[attr-defined]
    setattr(request, "_messages", FallbackStorage(request))
    queryset = Document.objects.filter(pk=portrait.pk)

    enqueued: list[int] = []
    with patch(
        "apps.documents.admin.enqueue_ocr_job",
        side_effect=lambda did: enqueued.append(did),
    ):
        admin_instance.re_run_ocr(request, queryset)

    assert enqueued == []
    portrait.refresh_from_db()
    assert portrait.ocr_status == Document.OcrStatus.NOT_REQUESTED


def test_admin_re_ocr_handles_multiple_docs():
    a = _make_doc(kind="guardian_identity", ocr_status="failed")
    b = _make_doc(kind="member_identity", ocr_status="completed")

    site = AdminSite()
    admin_instance = DocumentAdmin(Document, site)
    request = RequestFactory().post("/admin/documents/document/")
    request.session = {}  # type: ignore[attr-defined]
    setattr(request, "_messages", FallbackStorage(request))
    queryset = Document.objects.filter(pk__in=[a.pk, b.pk]).order_by("pk")

    enqueued: list[int] = []
    with patch(
        "apps.documents.admin.enqueue_ocr_job",
        side_effect=lambda did: enqueued.append(did),
    ):
        admin_instance.re_run_ocr(request, queryset)

    assert sorted(enqueued) == sorted([a.id, b.id])
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.ocr_status == Document.OcrStatus.PENDING
    assert b.ocr_status == Document.OcrStatus.PENDING
    assert a.ocr_error_code == ""  # cleared on retry
