"""DocuSeal provider — PLACEHOLDER.

Minimal stubs so the agreement-platform boundary's lazy imports and the
boundary tests' patch targets resolve. The real self-hosted DocuSeal HTTP
implementation replaces this module in a later task (P5 Slice D).
"""

from __future__ import annotations


def create_submission(agreement):
    raise NotImplementedError("DocuSeal provider not yet implemented")


def sync_submission(external_id: str):
    raise NotImplementedError("DocuSeal provider not yet implemented")


def archive_submission(external_id: str) -> None:
    raise NotImplementedError("DocuSeal provider not yet implemented")


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    raise NotImplementedError("DocuSeal provider not yet implemented")
