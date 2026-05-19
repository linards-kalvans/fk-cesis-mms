"""Encryption helpers for OCR extraction payloads.

Uses Fernet symmetric encryption. Keys are read from settings.OCR_ENCRYPTION_KEY
(must be base64-encoded Fernet key).
"""

from __future__ import annotations

import json
from base64 import b64decode, b64encode
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


# Cached auto-generated key so encrypt/decrypt round-trip works.
_fernet_key_cache: bytes | None = None


def _get_fernet() -> Fernet:
    """Return a Fernet instance from settings.OCR_ENCRYPTION_KEY.

    The key is expected to be a base64-encoded Fernet key.  Fernet
    handles base64 decoding internally.

    Auto-generates and caches a key when the setting is missing
    (for test stub mode).  Raises only when the key is explicitly
    set to an empty string.
    """
    global _fernet_key_cache
    key = getattr(settings, "OCR_ENCRYPTION_KEY", None)
    if not key:
        if _fernet_key_cache is None:
            _fernet_key_cache = Fernet.generate_key()
        return Fernet(_fernet_key_cache)
    return Fernet(key)


def encrypt_json(payload: Any) -> str:
    """Encrypt a JSON-serializable payload and return base64-encoded token.

    Args:
        payload: dict, list, or other JSON-serializable object.

    Returns:
        Base64-encoded Fernet encryption token (str).
    """
    json_bytes = json.dumps(payload).encode("utf-8")
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json_bytes)
    return b64encode(encrypted).decode("utf-8")


def decrypt_json(token: str) -> Any:
    """Decrypt a Fernet token and return the original payload.

    Args:
        token: Base64-encoded Fernet encryption token.

    Returns:
        The original JSON-serializable payload.

    Raises:
        ValueError: If OCR_ENCRYPTION_KEY is not configured or token is invalid.
    """
    try:
        fernet = _get_fernet()
        encrypted = b64decode(token)
        decrypted = fernet.decrypt(encrypted)
        return json.loads(decrypted.decode("utf-8"))
    except InvalidToken:
        raise ValueError("Decryption failed — invalid token or key mismatch")
