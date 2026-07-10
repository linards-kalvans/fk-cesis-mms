"""Agreement-platform boundary — stub + DocuSeal dispatch.

Mirrors apps/integrations/ocr.py. The boundary owns the exception
taxonomy; the real provider (apps/integrations/docuseal.py) imports and
raises these. Mode is selected by settings.AGREEMENT_PROVIDER_MODE
("stub" default, "docuseal" in production).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


class AgreementPlatformError(Exception):
    """Base for all agreement-platform errors."""


class AgreementPlatformConfigError(AgreementPlatformError):
    """Missing/invalid config or unknown provider mode — permanent."""


class AgreementPlatformAuthError(AgreementPlatformError):
    """Authentication failed (401/403) — permanent."""


class AgreementPlatformNotFoundError(AgreementPlatformError):
    """Submission not found (404 on sync/archive) — permanent."""


class AgreementPlatformTransientError(AgreementPlatformError):
    """5xx / timeout / connection error — retryable."""


@dataclass(frozen=True)
class SubmissionResult:
    external_id: str
    external_url: str
    external_state: str  # "pending" | "completed" | "archived"


@dataclass(frozen=True)
class DocumentResult:
    filename: str
    url: str
    content_type: str


def _stub_create(agreement) -> SubmissionResult:
    return SubmissionResult(
        external_id=f"stub-{agreement.id}",
        external_url=f"https://stub.invalid/{agreement.id}",
        external_state="pending",
    )


def _stub_sync(external_id: str) -> SubmissionResult:
    return SubmissionResult(
        external_id=external_id,
        external_url=f"https://stub.invalid/{external_id}",
        external_state="completed",
    )


def _stub_documents(external_id: str) -> list[DocumentResult]:
    return [
        DocumentResult(
            filename=f"agreement-{external_id}.pdf",
            url=f"https://stub.invalid/{external_id}/agreement.pdf",
            content_type="application/pdf",
        )
    ]


def _mode() -> str:
    return getattr(settings, "AGREEMENT_PROVIDER_MODE", "stub")


def create_submission(agreement) -> SubmissionResult:
    mode = _mode()
    if mode == "stub":
        return _stub_create(agreement)
    if mode == "docuseal":
        from apps.integrations import docuseal

        return docuseal.create_submission(agreement)
    raise AgreementPlatformConfigError(f"unknown agreement provider mode: {mode}")


def sync_submission(external_id: str) -> SubmissionResult:
    mode = _mode()
    if mode == "stub":
        return _stub_sync(external_id)
    if mode == "docuseal":
        from apps.integrations import docuseal

        return docuseal.sync_submission(external_id)
    raise AgreementPlatformConfigError(f"unknown agreement provider mode: {mode}")


def archive_submission(external_id: str) -> None:
    mode = _mode()
    if mode == "stub":
        return None
    if mode == "docuseal":
        from apps.integrations import docuseal

        docuseal.archive_submission(external_id)
        return None
    raise AgreementPlatformConfigError(f"unknown agreement provider mode: {mode}")


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    mode = _mode()
    if mode == "stub":
        return True
    from apps.integrations import docuseal

    return docuseal.verify_webhook_signature(raw_body, signature_header)


def list_submission_documents(external_id: str) -> list[DocumentResult]:
    mode = _mode()
    if mode == "stub":
        return _stub_documents(external_id)
    if mode == "docuseal":
        from apps.integrations import docuseal

        return docuseal.list_submission_documents(external_id)
    raise AgreementPlatformConfigError(f"unknown agreement provider mode: {mode}")
