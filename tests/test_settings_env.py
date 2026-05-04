"""Tests for .env auto-loading and tunnel-safe CSRF/host config.

These tests verify that:
1. `.env` at the project root is auto-loaded during Django settings bootstrap.
2. `SITE_URL` from `.env` is available without manual `source .env`.
3. `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` derive correct entries from `SITE_URL`.
4. Other env vars from `.env` (e.g. `DJANGO_SECRET_KEY`) are picked up.

These tests are expected to FAIL (RED) because the current settings.py
does not auto-load `.env` and does not derive ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent


def _unset_env_vars(*names):
    """Remove env vars so tests prove .env auto-load, not pre-exported vars."""
    originals = {}
    for name in names:
        if name in os.environ:
            originals[name] = os.environ.pop(name, None)
    return originals


def _restore_env_vars(originals):
    """Restore previously saved env vars."""
    os.environ.update(originals)


# ---------------------------------------------------------------------------
# Test: .env auto-loads SITE_URL
# ---------------------------------------------------------------------------

class TestEnvAutoLoadSiteUrl:
    """SITE_URL from .env should be available without manual export."""

    @pytest.fixture(autouse=True)
    def _ensure_clean_env(self):
        """Unset SITE_URL so we prove it comes from .env, not env var."""
        originals = _unset_env_vars("SITE_URL")
        yield
        _restore_env_vars(originals)

    def test_site_url_is_set_from_dotenv(self):
        """settings.SITE_URL should be non-empty after .env is loaded."""
        # The current settings.py only does os.environ.get("SITE_URL", ...)
        # which returns "http://localhost" if SITE_URL is not exported.
        # After .env auto-load, it should pick up the value from .env.
        assert settings.SITE_URL != "http://localhost"

    def test_site_url_matches_dotenv_value(self):
        """settings.SITE_URL should match the SITE_URL in .env."""
        dotenv_path = _ROOT / ".env"
        if not dotenv_path.exists():
            pytest.skip(".env file not present")
        dotenv_content = dotenv_path.read_text()
        expected_url = None
        for line in dotenv_content.splitlines():
            line = line.strip()
            if line.startswith("SITE_URL="):
                expected_url = line.split("=", 1)[1].strip()
                break
        if expected_url is None:
            pytest.skip("SITE_URL not found in .env")
        assert settings.SITE_URL == expected_url


# ---------------------------------------------------------------------------
# Test: .env auto-loads DJANGO_SECRET_KEY
# ---------------------------------------------------------------------------

class TestEnvAutoLoadSecretKey:
    """DJANGO_SECRET_KEY from .env should override the hardcoded default."""

    @pytest.fixture(autouse=True)
    def _ensure_clean_env(self):
        originals = _unset_env_vars("DJANGO_SECRET_KEY")
        yield
        _restore_env_vars(originals)

    def test_secret_key_from_dotenv_not_placeholder(self):
        """SECRET_KEY should not be the hardcoded placeholder after .env load."""
        # Current default: "django-insecure-task1-placeholder-change-in-production-abc123"
        # .env contains: DJANGO_SECRET_KEY=change-me
        assert settings.SECRET_KEY != "django-insecure-task1-placeholder-change-in-production-abc123"

    def test_secret_key_matches_dotenv_value(self):
        """SECRET_KEY should match the DJANGO_SECRET_KEY in .env."""
        dotenv_path = _ROOT / ".env"
        if not dotenv_path.exists():
            pytest.skip(".env file not present")
        dotenv_content = dotenv_path.read_text()
        expected_key = None
        for line in dotenv_content.splitlines():
            line = line.strip()
            if line.startswith("DJANGO_SECRET_KEY="):
                expected_key = line.split("=", 1)[1].strip()
                break
        if expected_key is None:
            pytest.skip("DJANGO_SECRET_KEY not found in .env")
        assert settings.SECRET_KEY == expected_key


# ---------------------------------------------------------------------------
# Test: ALLOWED_HOSTS derived from SITE_URL
# ---------------------------------------------------------------------------

class TestAllowedHosts:
    """ALLOWED_HOSTS should derive host entries from SITE_URL."""

    def test_allowed_hosts_is_not_empty(self):
        """After .env load + derivation, ALLOWED_HOSTS should have derived entries, not just testserver."""
        # Django test runner injects "testserver" — we need actual derived entries.
        # Filter out the test runner's default.
        derived = [h for h in settings.ALLOWED_HOSTS if h not in ("testserver", "localhost", "*")]
        assert len(derived) > 0, (
            f"ALLOWED_HOSTS should contain derived entries from SITE_URL, got: {settings.ALLOWED_HOSTS}"
        )

    def test_allowed_hosts_contains_site_hostname(self):
        """ALLOWED_HOSTS should contain the hostname extracted from SITE_URL."""
        site_url = getattr(settings, "SITE_URL", None)
        if not site_url:
            pytest.skip("SITE_URL not set")
        # Parse hostname from URL (strip scheme)
        from urllib.parse import urlparse
        parsed = urlparse(site_url)
        hostname = parsed.hostname or ""
        assert hostname in settings.ALLOWED_HOSTS, (
            f"ALLOWED_HOSTS={settings.ALLOWED_HOSTS} should contain {hostname}"
        )


# ---------------------------------------------------------------------------
# Test: CSRF_TRUSTED_ORIGINS derived from SITE_URL
# ---------------------------------------------------------------------------

class TestCsrfTrustedOrigins:
    """CSRF_TRUSTED_ORIGINS should contain the full SITE_URL origin."""

    def test_csrf_trusted_origins_defined_in_settings(self):
        """settings should define CSRF_TRUSTED_ORIGINS as a derived list (not Django default)."""
        # Django 6.x defines CSRF_TRUSTED_ORIGINS = [] by default.
        # Our settings must override it with derived entries from SITE_URL.
        # We check that the value is not the Django default empty list.
        assert settings.CSRF_TRUSTED_ORIGINS != [], (
            "CSRF_TRUSTED_ORIGINS should be derived from SITE_URL, not Django default []"
        )

    def test_csrf_trusted_origins_is_not_empty(self):
        """CSRF_TRUSTED_ORIGINS should contain derived entries from SITE_URL, not be empty."""
        # Django defaults CSRF_TRUSTED_ORIGINS to [] — we need actual entries.
        assert len(settings.CSRF_TRUSTED_ORIGINS) > 0, (
            f"CSRF_TRUSTED_ORIGINS should contain derived entries from SITE_URL, got: {settings.CSRF_TRUSTED_ORIGINS}"
        )

    def test_csrf_trusted_origins_contains_site_url(self):
        """CSRF_TRUSTED_ORIGINS should contain the full SITE_URL."""
        site_url = getattr(settings, "SITE_URL", None)
        if not site_url:
            pytest.skip("SITE_URL not set")
        assert site_url in settings.CSRF_TRUSTED_ORIGINS, (
            f"CSRF_TRUSTED_ORIGINS={settings.CSRF_TRUSTED_ORIGINS} should contain {site_url}"
        )

    def test_csrf_trusted_origins_has_https_for_tunnel(self):
        """For tunnel URLs (kimaki.dev), CSRF_TRUSTED_ORIGINS must use https.

        Reads .env directly to check the tunnel URL even if settings hasn't loaded it yet.
        """
        dotenv_path = _ROOT / ".env"
        if not dotenv_path.exists():
            pytest.skip(".env file not present")
        dotenv_content = dotenv_path.read_text()
        expected_site_url = None
        for line in dotenv_content.splitlines():
            line = line.strip()
            if line.startswith("SITE_URL="):
                expected_site_url = line.split("=", 1)[1].strip()
                break
        if not expected_site_url:
            pytest.skip("SITE_URL not found in .env")

        # Tunnel URLs are HTTPS — CSRF_TRUSTED_ORIGINS must have matching https origins
        if expected_site_url.startswith("https://"):
            https_origins = [o for o in settings.CSRF_TRUSTED_ORIGINS if o.startswith("https://")]
            assert len(https_origins) > 0, (
                f"CSRF_TRUSTED_ORIGINS should have https:// entries when SITE_URL is https, got: {settings.CSRF_TRUSTED_ORIGINS}"
            )
            if "kimaki.dev" in expected_site_url:
                tunnel_origins = [o for o in settings.CSRF_TRUSTED_ORIGINS if "kimaki.dev" in o]
                assert len(tunnel_origins) > 0, (
                    f"CSRF_TRUSTED_ORIGINS should have a kimaki.dev entry, got: {settings.CSRF_TRUSTED_ORIGINS}"
                )
                for origin in tunnel_origins:
                    assert origin.startswith("https://"), (
                        f"CSRF_TRUSTED_ORIGINS entry for tunnel must use https://, got: {origin}"
                    )


# ---------------------------------------------------------------------------
# Test: ALLOWED_HOSTS includes local dev hosts for tunnel/proxy traffic
# ---------------------------------------------------------------------------

class TestAllowedHostsLocalDev:
    """ALLOWED_HOSTS must include localhost and 127.0.0.1 for tunnel/proxy traffic.

    Bug: when SITE_URL is a tunnel URL (e.g. https://...kimaki.dev),
    Django receives HTTP_HOST=localhost:8000 on the incoming tunnel path.
    If ALLOWED_HOSTS lacks 'localhost' and '127.0.0.1', Django raises
    DisallowedHost and blocks the request.

    Fix: ALLOWED_HOSTS must always include local dev hosts regardless of SITE_URL.
    """

    def test_allowed_hosts_contains_localhost(self):
        """ALLOWED_HOSTS must include 'localhost' to accept tunnel/proxy traffic."""
        assert "localhost" in settings.ALLOWED_HOSTS, (
            f"ALLOWED_HOSTS={settings.ALLOWED_HOSTS} must include 'localhost' "
            "for tunnel/proxy traffic"
        )

    def test_allowed_hosts_contains_127_0_0_1(self):
        """ALLOWED_HOSTS must include '127.0.0.1' to accept tunnel/proxy traffic."""
        assert "127.0.0.1" in settings.ALLOWED_HOSTS, (
            f"ALLOWED_HOSTS={settings.ALLOWED_HOSTS} must include '127.0.0.1' "
            "for tunnel/proxy traffic"
        )


# ---------------------------------------------------------------------------
# Test: SECURE_PROXY_SSL_HEADER for HTTPS tunnel traffic
# ---------------------------------------------------------------------------

class TestSecureProxySslHeader:
    """Django must trust the proxy's X-Forwarded-Proto header.

    Bug: tunnel/proxy terminates HTTPS and forwards requests as HTTP.
    Django sees plain HTTP, so SecurityMiddleware does not mark cookies
    secure and does not enforce HTTPS redirects. The real browser over
    the tunnel gets redirected back to the login page because the session
    cookie is not sent (not marked secure on an apparent HTTP connection).

    Fix: set SECURE_PROXY_SSL_HEADER so Django knows the original request
    was HTTPS.
    """

    def test_secure_proxy_ssl_header_is_set(self):
        """SECURE_PROXY_SSL_HEADER must be set to trust proxy HTTPS."""
        assert hasattr(settings, "SECURE_PROXY_SSL_HEADER"), (
            "SECURE_PROXY_SSL_HEADER is not defined in settings. "
            "Django cannot trust the proxy's X-Forwarded-Proto header."
        )

    def test_secure_proxy_ssl_header_value(self):
        """SECURE_PROXY_SSL_HEADER must match ('HTTP_X_FORWARDED_PROTO', 'https')."""
        expected = ("HTTP_X_FORWARDED_PROTO", "https")
        actual = getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
        assert actual == expected, (
            f"SECURE_PROXY_SSL_HEADER={actual}, expected {expected}"
        )


# ---------------------------------------------------------------------------
# Test: USE_X_FORWARDED_HOST for proxy host forwarding
# ---------------------------------------------------------------------------

class TestUseXForwardedHost:
    """Django must respect the Host header forwarded by the proxy.

    Bug: the tunnel proxy may rewrite the Host header. Without
    USE_X_FORWARDED_HOST=True, Django ignores the forwarded host and
    may generate wrong absolute URLs (e.g. for redirect targets),
    causing the browser to land back at the login page.

    Fix: set USE_X_FORWARDED_HOST = True.
    """

    def test_use_x_forwarded_host_is_true(self):
        """USE_X_FORWARDED_HOST must be True to trust forwarded Host header."""
        assert getattr(settings, "USE_X_FORWARDED_HOST", False) is True, (
            f"USE_X_FORWARDED_HOST={getattr(settings, 'USE_X_FORWARDED_HOST', 'not set')}, "
            "expected True for tunnel/proxy host forwarding"
        )


# ---------------------------------------------------------------------------
# Test: SESSION_COOKIE_SECURE for HTTPS tunnel traffic
# ---------------------------------------------------------------------------

class TestSessionCookieSecure:
    """Session cookie must be marked secure for HTTPS tunnel traffic.

    Bug: when SITE_URL is https://, the session cookie should be
    secure=True so the browser sends it over HTTPS. Without this,
    the cookie is not sent and the browser sees an unauthenticated
    state, redirecting back to the login page.

    Fix: set SESSION_COOKIE_SECURE = True when SITE_URL is https.
    """

    def test_session_cookie_secure_is_true_for_https_site(self):
        """SESSION_COOKIE_SECURE must be True when SITE_URL starts with https."""
        site_url = getattr(settings, "SITE_URL", None)
        if not site_url:
            pytest.skip("SITE_URL not set")
        if not site_url.startswith("https://"):
            pytest.skip(f"SITE_URL is {site_url}, not https")
        assert getattr(settings, "SESSION_COOKIE_SECURE", False) is True, (
            f"SESSION_COOKIE_SECURE={getattr(settings, 'SESSION_COOKIE_SECURE', 'not set')}, "
            "expected True when SITE_URL is https://"
        )

    def test_session_cookie_secure_set_in_settings(self):
        """SESSION_COOKIE_SECURE must be explicitly defined in settings."""
        assert hasattr(settings, "SESSION_COOKIE_SECURE"), (
            "SESSION_COOKIE_SECURE is not defined in settings. "
            "Browser may reject the session cookie over HTTPS tunnel."
        )


# ---------------------------------------------------------------------------
# Test: CSRF_COOKIE_SECURE for HTTPS tunnel traffic
# ---------------------------------------------------------------------------

class TestCsrfCookieSecure:
    """CSRF cookie must be marked secure for HTTPS tunnel traffic.

    Bug: CSRF cookie not marked secure means the browser won't send
    it over HTTPS, causing CSRF validation to fail on POST requests
    (like login). The user gets redirected back to the login page.

    Fix: set CSRF_COOKIE_SECURE = True when SITE_URL is https.
    """

    def test_csrf_cookie_secure_is_true_for_https_site(self):
        """CSRF_COOKIE_SECURE must be True when SITE_URL starts with https."""
        site_url = getattr(settings, "SITE_URL", None)
        if not site_url:
            pytest.skip("SITE_URL not set")
        if not site_url.startswith("https://"):
            pytest.skip(f"SITE_URL is {site_url}, not https")
        assert getattr(settings, "CSRF_COOKIE_SECURE", False) is True, (
            f"CSRF_COOKIE_SECURE={getattr(settings, 'CSRF_COOKIE_SECURE', 'not set')}, "
            "expected True when SITE_URL is https://"
        )

    def test_csrf_cookie_secure_set_in_settings(self):
        """CSRF_COOKIE_SECURE must be explicitly defined in settings."""
        assert hasattr(settings, "CSRF_COOKIE_SECURE"), (
            "CSRF_COOKIE_SECURE is not defined in settings. "
            "CSRF validation may fail over HTTPS tunnel."
        )


# ---------------------------------------------------------------------------
# Test: SESSION_COOKIE_SAMESITE for HTTPS tunnel traffic
# ---------------------------------------------------------------------------

class TestSessionCookieSameSite:
    """Session cookie SameSite must be None for HTTPS tunnel traffic.

    Bug: Django defaults SESSION_COOKIE_SAMESITE to 'Lax'.
    Lax cookies are not sent on cross-site requests. A tunnel proxy
    (kimaki.dev) terminates HTTPS and forwards the request — the browser
    treats the tunnel as a cross-site context. With SameSite=Lax the
    session cookie is stripped, the admin login POST gets no session,
    and the browser lands back at the login page.

    Fix: set SESSION_COOKIE_SAMESITE = 'None' when SITE_URL is https://.
    """

    def test_session_cookie_samesite_is_none_for_https_site(self):
        """SESSION_COOKIE_SAMESITE must be 'None' when SITE_URL starts with https."""
        site_url = getattr(settings, "SITE_URL", None)
        if not site_url:
            pytest.skip("SITE_URL not set")
        if not site_url.startswith("https://"):
            pytest.skip(f"SITE_URL is {site_url}, not https")
        actual = getattr(settings, "SESSION_COOKIE_SAMESITE", None)
        assert actual == "None", (
            f"SESSION_COOKIE_SAMESITE={actual!r}, expected 'None' when SITE_URL is https://"
        )

    def test_session_cookie_samesite_set_in_settings(self):
        """SESSION_COOKIE_SAMESITE must be explicitly defined in settings."""
        assert hasattr(settings, "SESSION_COOKIE_SAMESITE"), (
            "SESSION_COOKIE_SAMESITE is not defined in settings. "
            "Browser may strip session cookie over HTTPS tunnel due to default Lax."
        )


# ---------------------------------------------------------------------------
# Test: CSRF_COOKIE_SAMESITE for HTTPS tunnel traffic
# ---------------------------------------------------------------------------

class TestCsrfCookieSameSite:
    """CSRF cookie SameSite must be None for HTTPS tunnel traffic.

    Bug: Django defaults CSRF_COOKIE_SAMESITE to 'Lax'.
    Lax cookies are not sent on cross-site requests. A tunnel proxy
    (kimaki.dev) terminates HTTPS and forwards the request — the browser
    treats the tunnel as a cross-site context. With SameSite=Lax the
    CSRF cookie is stripped, POST login fails CSRF validation, and the
    user gets redirected back to the login page.

    Fix: set CSRF_COOKIE_SAMESITE = 'None' when SITE_URL is https://.
    """

    def test_csrf_cookie_samesite_is_none_for_https_site(self):
        """CSRF_COOKIE_SAMESITE must be 'None' when SITE_URL starts with https."""
        site_url = getattr(settings, "SITE_URL", None)
        if not site_url:
            pytest.skip("SITE_URL not set")
        if not site_url.startswith("https://"):
            pytest.skip(f"SITE_URL is {site_url}, not https")
        actual = getattr(settings, "CSRF_COOKIE_SAMESITE", None)
        assert actual == "None", (
            f"CSRF_COOKIE_SAMESITE={actual!r}, expected 'None' when SITE_URL is https://"
        )

    def test_csrf_cookie_samesite_set_in_settings(self):
        """CSRF_COOKIE_SAMESITE must be explicitly defined in settings."""
        assert hasattr(settings, "CSRF_COOKIE_SAMESITE"), (
            "CSRF_COOKIE_SAMESITE is not defined in settings. "
            "CSRF validation may fail over HTTPS tunnel due to default Lax."
        )
