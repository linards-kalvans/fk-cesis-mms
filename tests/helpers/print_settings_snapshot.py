"""Subprocess helper — print Django settings as JSON for env-isolation tests.

Contract:
  python tests/helpers/print_settings_snapshot.py <temp_env_dir>

  1. Loads <temp_env_dir>/.env into the process environment.
  2. Imports Django settings (fresh process, no cache).
  3. Prints a JSON snapshot of relevant settings to stdout.
  4. Exit code 0 on success, non-zero on failure.

The subprocess receives a sanitized environment: all keys in
``_ENV_ISOLATION_KEYS`` are cleared from the inherited parent
env before the temp .env is loaded. This guarantees that no value
leaks from the user's local .env or from the test runner process.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Keys that must never leak from the parent process environment.
# Tests import this constant to keep a single source of truth.
_ENV_ISOLATION_KEYS = frozenset((
    "SITE_URL",
    "DJANGO_SECRET_KEY",
    "SECRET_KEY",
    "ALLOWED_HOSTS",
    "CSRF_TRUSTED_ORIGINS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "SESSION_COOKIE_SAMESITE",
    "CSRF_COOKIE_SAMESITE",
    "SECURE_PROXY_SSL_HEADER",
    "USE_X_FORWARDED_HOST",
    "DJANGO_SETTINGS_MODULE",
))

# Ensure the project root is on sys.path so the subprocess can import
# ``fk_cesis_mms.settings`` (and all apps) in a fresh process.
# The worktree root is three levels up from this file:
#   tests/helpers/print_settings_snapshot.py
#   ^^^^^^ ^^^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^^^^
#   |
#   worktree root
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKTREE_ROOT))


def main():
    if len(sys.argv) < 2:
        print("Usage: print_settings_snapshot.py <temp_env_dir>", file=sys.stderr)
        sys.exit(1)

    env_dir = Path(sys.argv[1])
    env_file = env_dir / ".env"

    if not env_file.exists():
        print(f"Error: {env_file} not found", file=sys.stderr)
        sys.exit(1)

    # Strip all sensitive keys from inherited parent env before loading
    # the temp .env file. This makes env isolation explicit at the
    # subprocess level — no parent-process value can leak in.
    for key in _ENV_ISOLATION_KEYS:
        os.environ.pop(key, None)

    # Load .env from temp directory into process environment
    load_dotenv(dotenv_path=env_file, override=True)

    # Set Django settings module so it can be imported
    os.environ["DJANGO_SETTINGS_MODULE"] = "fk_cesis_mms.settings"

    import django

    django.setup()

    from django.conf import settings
    from urllib.parse import urlparse

    site_url = getattr(settings, "SITE_URL", "")
    parsed = urlparse(site_url)

    snapshot = {
        "site_url": site_url,
        "secret_key": getattr(settings, "SECRET_KEY", ""),
        "allowed_hosts": getattr(settings, "ALLOWED_HOSTS", []),
        "csrf_trusted_origins": getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
        "session_cookie_secure": getattr(settings, "SESSION_COOKIE_SECURE", False),
        "csrf_cookie_secure": getattr(settings, "CSRF_COOKIE_SECURE", False),
        "session_cookie_samesite": getattr(settings, "SESSION_COOKIE_SAMESITE", None),
        "csrf_cookie_samesite": getattr(settings, "CSRF_COOKIE_SAMESITE", None),
        "hostname": parsed.hostname if parsed.hostname else "",
    }

    print(json.dumps(snapshot))
    sys.exit(0)


if __name__ == "__main__":
    main()
