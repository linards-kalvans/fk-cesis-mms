"""Subprocess-driven env-isolation tests for Django settings bootstrap.

Each test writes its own temporary .env file and spawns a fresh Python
subprocess to import Django settings. This guarantees complete isolation
from the project-root user .env and from Django's settings import cache.

No test depends on the project's .env file. All env values come from
temp files created per-test.

Helper script: tests/helpers/print_settings_snapshot.py
  Contract: python print_settings_snapshot.py <temp_env_dir>
  Output: JSON snapshot of relevant Django settings on stdout.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from tests.helpers.print_settings_snapshot import _ENV_ISOLATION_KEYS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_WORKTREE_ROOT = Path(__file__).resolve().parent.parent
_HELPER_SCRIPT = _WORKTREE_ROOT / "tests" / "helpers" / "print_settings_snapshot.py"
_PYTHON = sys.executable


def _isolated_env() -> dict:
    """Return a copy of the parent env with tested keys cleared."""
    env = os.environ.copy()
    for key in _ENV_ISOLATION_KEYS:
        env.pop(key, None)
    return env


def _run_helper(env_dir: Path) -> dict:
    """Run the subprocess helper and return parsed JSON snapshot.

    Raises RuntimeError if the helper script is missing or exits non-zero.
    """
    if not _HELPER_SCRIPT.exists():
        raise RuntimeError(
            f"Subprocess helper not found at {_HELPER_SCRIPT}. "
            "Env-isolation tests require this script."
        )

    result = subprocess.run(
        [_PYTHON, str(_HELPER_SCRIPT), str(env_dir)],
        capture_output=True,
        text=True,
        timeout=30,
        env=_isolated_env(),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Subprocess helper failed (exit {result.returncode}).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}\n"
        )

    try:
        return cast(dict[str, Any], json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Subprocess helper returned invalid JSON.\n"
            f"stdout: {result.stdout}\n"
            f"Error: {exc}\n"
        )


# ---------------------------------------------------------------------------
# Test: parent env values do NOT leak into subprocess snapshot
# ---------------------------------------------------------------------------

class TestEnvIsolationRegression:
    """Prove parent-process env vars cannot override temp .env values."""

    def test_parent_env_does_not_leak_site_url(self, tmp_path, monkeypatch):
        """Parent SITE_URL must NOT leak into subprocess snapshot."""
        parent_url = "http://PARENT-LEAK.example.com"
        temp_url = "http://temp-env-isolated.example.com:8888"

        monkeypatch.setenv("SITE_URL", parent_url)
        monkeypatch.setenv("DJANGO_SECRET_KEY", "parent-key")

        env_file = tmp_path / ".env"
        env_file.write_text(f"SITE_URL={temp_url}\nDJANGO_SECRET_KEY=temp-key\n")

        snapshot = _run_helper(tmp_path)
        assert snapshot["site_url"] == temp_url, (
            f"SITE_URL leaked from parent env: got {snapshot['site_url']}, "
            f"expected {temp_url} from temp .env."
        )

    def test_parent_env_does_not_leak_secret_key(self, tmp_path, monkeypatch):
        """Parent DJANGO_SECRET_KEY must NOT leak into subprocess snapshot."""
        parent_key = "parent-secret-key-leak"
        temp_key = "temp-secret-key-isolated"

        monkeypatch.setenv("DJANGO_SECRET_KEY", parent_key)
        monkeypatch.setenv("SITE_URL", "http://localhost")

        env_file = tmp_path / ".env"
        env_file.write_text(f"DJANGO_SECRET_KEY={temp_key}\nSITE_URL=http://temp.example.com\n")

        snapshot = _run_helper(tmp_path)
        assert snapshot["secret_key"] == temp_key, (
            f"SECRET_KEY leaked from parent env: got {snapshot['secret_key']}, "
            f"expected {temp_key} from temp .env."
        )

    def test_parent_env_does_not_leak_allowed_hosts(self, tmp_path, monkeypatch):
        """Parent ALLOWED_HOSTS must NOT leak into subprocess snapshot."""
        monkeypatch.setenv("ALLOWED_HOSTS", "parent-leak.example.com")
        monkeypatch.setenv("SITE_URL", "http://temp.example.com:7777")
        monkeypatch.setenv("DJANGO_SECRET_KEY", "test-key")

        env_file = tmp_path / ".env"
        env_file.write_text(
            "SITE_URL=http://temp.example.com:7777\n"
            "DJANGO_SECRET_KEY=test-key\n"
        )

        snapshot = _run_helper(tmp_path)
        assert "parent-leak.example.com" not in snapshot["allowed_hosts"], (
            f"ALLOWED_HOSTS leaked from parent env: {snapshot['allowed_hosts']}."
        )


# ---------------------------------------------------------------------------
# Test: subprocess helper exists and produces valid JSON
# ---------------------------------------------------------------------------

class TestSubprocessBootstrap:
    """Verify the subprocess helper path is wired correctly."""

    def test_helper_script_exists(self):
        """The subprocess helper script must exist at the expected path."""
        assert _HELPER_SCRIPT.exists(), (
            f"Subprocess helper not found at {_HELPER_SCRIPT}. "
            "Env-isolation tests require this script."
        )

    def test_helper_produces_valid_json(self, tmp_path):
        """Helper must output valid JSON when given a temp .env directory."""
        env_file = tmp_path / ".env"
        env_file.write_text("SITE_URL=http://example.com\nDJANGO_SECRET_KEY=test-key\n")

        snapshot = _run_helper(tmp_path)
        assert isinstance(snapshot, dict)
        assert "site_url" in snapshot
        assert "secret_key" in snapshot
        assert "allowed_hosts" in snapshot


# ---------------------------------------------------------------------------
# Test: SITE_URL from temp .env
# ---------------------------------------------------------------------------

class TestSiteUrlFromEnv:
    """SITE_URL must come from the temp .env file, not from user's .env."""

    def test_site_url_from_temp_dotenv(self, tmp_path):
        """settings.SITE_URL must match the SITE_URL written to temp .env."""
        temp_url = "http://isolated-test.example.com:9999"
        env_file = tmp_path / ".env"
        env_file.write_text(f"SITE_URL={temp_url}\nDJANGO_SECRET_KEY=test-key\n")

        snapshot = _run_helper(tmp_path)
        assert snapshot["site_url"] == temp_url, (
            f"Expected SITE_URL={temp_url}, got {snapshot['site_url']}. "
            "SITE_URL is not being read from the temp .env file."
        )


# ---------------------------------------------------------------------------
# Test: SECRET_KEY from temp .env
# ---------------------------------------------------------------------------

class TestSecretKeyFromEnv:
    """SECRET_KEY must come from the temp .env file, not from user's .env."""

    def test_secret_key_from_temp_dotenv(self, tmp_path):
        """settings.SECRET_KEY must match the DJANGO_SECRET_KEY written to temp .env."""
        temp_key = "super-secret-key-from-temp-env-xyz789"
        env_file = tmp_path / ".env"
        env_file.write_text(f"DJANGO_SECRET_KEY={temp_key}\nSITE_URL=http://localhost\n")

        snapshot = _run_helper(tmp_path)
        assert snapshot["secret_key"] == temp_key, (
            f"Expected SECRET_KEY={temp_key}, got {snapshot['secret_key']}. "
            "SECRET_KEY is not being read from the temp .env file."
        )


# ---------------------------------------------------------------------------
# Test: ALLOWED_HOSTS contains site hostname + local dev hosts
# ---------------------------------------------------------------------------

class TestAllowedHosts:
    """ALLOWED_HOSTS must derive from temp .env SITE_URL and include dev hosts."""

    def test_allowed_hosts_contains_site_hostname(self, tmp_path):
        """ALLOWED_HOSTS must include the hostname extracted from temp .env SITE_URL."""
        temp_url = "http://isolated-test.example.com:9999"
        env_file = tmp_path / ".env"
        env_file.write_text(f"SITE_URL={temp_url}\nDJANGO_SECRET_KEY=test-key\n")

        snapshot = _run_helper(tmp_path)
        allowed = snapshot["allowed_hosts"]
        assert "isolated-test.example.com" in allowed, (
            f"ALLOWED_HOSTS={allowed} must contain 'isolated-test.example.com' "
            "derived from temp .env SITE_URL."
        )

    def test_allowed_hosts_contains_localhost(self, tmp_path):
        """ALLOWED_HOSTS must include 'localhost' for local dev."""
        env_file = tmp_path / ".env"
        env_file.write_text("SITE_URL=http://isolated.example.com\nDJANGO_SECRET_KEY=test-key\n")

        snapshot = _run_helper(tmp_path)
        allowed = snapshot["allowed_hosts"]
        assert "localhost" in allowed, (
            f"ALLOWED_HOSTS={allowed} must include 'localhost'."
        )

    def test_allowed_hosts_contains_127_0_0_1(self, tmp_path):
        """ALLOWED_HOSTS must include '127.0.0.1' for local dev."""
        env_file = tmp_path / ".env"
        env_file.write_text("SITE_URL=http://isolated.example.com\nDJANGO_SECRET_KEY=test-key\n")

        snapshot = _run_helper(tmp_path)
        allowed = snapshot["allowed_hosts"]
        assert "127.0.0.1" in allowed, (
            f"ALLOWED_HOSTS={allowed} must include '127.0.0.1'."
        )


# ---------------------------------------------------------------------------
# Test: CSRF_TRUSTED_ORIGINS contains SITE_URL
# ---------------------------------------------------------------------------

class TestCsrfTrustedOrigins:
    """CSRF_TRUSTED_ORIGINS must contain the full SITE_URL from temp .env."""

    def test_csrf_trusted_origins_contains_site_url(self, tmp_path):
        """CSRF_TRUSTED_ORIGINS must include the full SITE_URL from temp .env."""
        temp_url = "http://isolated-test.example.com:9999"
        env_file = tmp_path / ".env"
        env_file.write_text(f"SITE_URL={temp_url}\nDJANGO_SECRET_KEY=test-key\n")

        snapshot = _run_helper(tmp_path)
        origins = snapshot["csrf_trusted_origins"]
        assert temp_url in origins, (
            f"CSRF_TRUSTED_ORIGINS={origins} must contain '{temp_url}' "
            "from temp .env SITE_URL."
        )


# ---------------------------------------------------------------------------
# Test: Secure cookie flags reflect https SITE_URL
# ---------------------------------------------------------------------------

class TestSecureCookieFlagsHttps:
    """When temp .env SITE_URL is https://, secure cookie flags must be True."""

    def _https_snapshot(self, tmp_path) -> dict:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SITE_URL=https://secure-tunnel.example.com\n"
            "DJANGO_SECRET_KEY=test-key\n"
        )
        return _run_helper(tmp_path)

    def test_session_cookie_secure_true_for_https(self, tmp_path):
        """SESSION_COOKIE_SECURE must be True when SITE_URL is https://."""
        snapshot = self._https_snapshot(tmp_path)
        assert snapshot["session_cookie_secure"] is True, (
            f"SESSION_COOKIE_SECURE={snapshot['session_cookie_secure']}, "
            "expected True for https:// SITE_URL."
        )

    def test_csrf_cookie_secure_true_for_https(self, tmp_path):
        """CSRF_COOKIE_SECURE must be True when SITE_URL is https://."""
        snapshot = self._https_snapshot(tmp_path)
        assert snapshot["csrf_cookie_secure"] is True, (
            f"CSRF_COOKIE_SECURE={snapshot['csrf_cookie_secure']}, "
            "expected True for https:// SITE_URL."
        )


# ---------------------------------------------------------------------------
# Test: SameSite cookie attributes reflect https SITE_URL
# ---------------------------------------------------------------------------

class TestSameSiteCookieAttrsHttps:
    """When temp .env SITE_URL is https://, SameSite attrs must be 'None'."""

    def _https_snapshot(self, tmp_path) -> dict:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SITE_URL=https://secure-tunnel.example.com\n"
            "DJANGO_SECRET_KEY=test-key\n"
        )
        return _run_helper(tmp_path)

    def test_session_cookie_samesite_none_for_https(self, tmp_path):
        """SESSION_COOKIE_SAMESITE must be 'None' when SITE_URL is https://."""
        snapshot = self._https_snapshot(tmp_path)
        assert snapshot["session_cookie_samesite"] == "None", (
            f"SESSION_COOKIE_SAMESITE={snapshot['session_cookie_samesite']!r}, "
            "expected 'None' for https:// SITE_URL."
        )

    def test_csrf_cookie_samesite_none_for_https(self, tmp_path):
        """CSRF_COOKIE_SAMESITE must be 'None' when SITE_URL is https://."""
        snapshot = self._https_snapshot(tmp_path)
        assert snapshot["csrf_cookie_samesite"] == "None", (
            f"CSRF_COOKIE_SAMESITE={snapshot['csrf_cookie_samesite']!r}, "
            "expected 'None' for https:// SITE_URL."
        )


# ---------------------------------------------------------------------------
# Test: OCR settings exposed as Django settings attributes
# ---------------------------------------------------------------------------

class TestOcrSettingsExposed:
    """OCR env vars must be exported as Django settings attributes.

    Bug: fk_cesis_mms.settings loads OCR env vars into os.environ via
    load_dotenv() but does NOT expose them as module-level attributes
    that django.conf.settings can read.  apps.integrations.ocr falls
    back to "stub" because getattr(settings, "OCR_PROVIDER_MODE", "stub")
    always hits the default.
    """

    def _ocr_env(self, tmp_path) -> dict:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SITE_URL=http://ocr-test.example.com\n"
            "DJANGO_SECRET_KEY=test-key\n"
            "OCR_PROVIDER_MODE=tiny_idp\n"
            "TINY_IDP_API_URL=http://tiny-idp.local/api\n"
            "TINY_IDP_API_KEY=tiny-key-12345\n"
            "OCR_ENCRYPTION_KEY=enc-key-abcdef0123456789\n"
        )
        return _run_helper(tmp_path)

    def test_ocr_provider_mode_from_env(self, tmp_path):
        """OCR_PROVIDER_MODE must be exported as settings.OCR_PROVIDER_MODE."""
        snapshot = self._ocr_env(tmp_path)
        assert snapshot["ocr_provider_mode"] == "tiny_idp", (
            f"settings.OCR_PROVIDER_MODE not exposed. Got {snapshot['ocr_provider_mode']!r}. "
            "Expected 'tiny_idp' from OCR_PROVIDER_MODE env var."
        )

    def test_tiny_idp_api_url_from_env(self, tmp_path):
        """TINY_IDP_API_URL must be exported as settings.TINY_IDP_API_URL."""
        snapshot = self._ocr_env(tmp_path)
        assert snapshot["tiny_idp_api_url"] == "http://tiny-idp.local/api", (
            f"settings.TINY_IDP_API_URL not exposed. Got {snapshot['tiny_idp_api_url']!r}. "
            "Expected 'http://tiny-idp.local/api' from TINY_IDP_API_URL env var."
        )

    def test_tiny_idp_api_key_from_env(self, tmp_path):
        """TINY_IDP_API_KEY must be exported as settings.TINY_IDP_API_KEY."""
        snapshot = self._ocr_env(tmp_path)
        assert snapshot["tiny_idp_api_key"] == "tiny-key-12345", (
            f"settings.TINY_IDP_API_KEY not exposed. Got {snapshot['tiny_idp_api_key']!r}. "
            "Expected 'tiny-key-12345' from TINY_IDP_API_KEY env var."
        )

    def test_ocr_encryption_key_from_env(self, tmp_path):
        """OCR_ENCRYPTION_KEY must be exported as settings.OCR_ENCRYPTION_KEY."""
        snapshot = self._ocr_env(tmp_path)
        assert snapshot["ocr_encryption_key"] == "enc-key-abcdef0123456789", (
            f"settings.OCR_ENCRYPTION_KEY not exposed. Got {snapshot['ocr_encryption_key']!r}. "
            "Expected 'enc-key-abcdef0123456789' from OCR_ENCRYPTION_KEY env var."
        )

    def test_ocr_settings_defaults_without_env(self, tmp_path):
        """When OCR env vars are absent, settings must export sensible defaults."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SITE_URL=http://no-ocr.example.com\n"
            "DJANGO_SECRET_KEY=test-key\n"
            # Explicitly blank OCR vars so they are present in os.environ
            # before the project .env loads; override=False preserves them.
            "OCR_PROVIDER_MODE=\n"
            "TINY_IDP_API_URL=\n"
            "TINY_IDP_API_KEY=\n"
            "OCR_ENCRYPTION_KEY=\n"
        )
        snapshot = _run_helper(tmp_path)
        assert snapshot["ocr_provider_mode"] == "stub", (
            f"Expected ocr_provider_mode='stub' default, got {snapshot['ocr_provider_mode']!r}."
        )
        assert snapshot["tiny_idp_api_url"] == "", (
            f"Expected tiny_idp_api_url='' default, got {snapshot['tiny_idp_api_url']!r}."
        )
        assert snapshot["tiny_idp_api_key"] == "", (
            f"Expected tiny_idp_api_key='' default, got {snapshot['tiny_idp_api_key']!r}."
        )
        assert snapshot["ocr_encryption_key"] == "", (
            f"Expected ocr_encryption_key='' default, got {snapshot['ocr_encryption_key']!r}."
        )


def test_billing_autosend_defaults_off():
    from django.conf import settings

    assert settings.BILLING_AUTOSEND_ENABLED is False


def test_billing_send_due_hour_default():
    from django.conf import settings

    assert isinstance(settings.BILLING_SEND_DUE_HOUR, int)
