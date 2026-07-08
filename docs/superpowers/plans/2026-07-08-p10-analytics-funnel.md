# P10 Analytics Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add privacy-aware analytics for the Django parent registration and portal funnel, with referral-code attribution and no admin/PII tracking.

**Architecture:** Add a small `apps.analytics` boundary with config, sanitization, and a provider adapter. Browser analytics is injected only into parent templates; server milestone events are emitted from existing registration/account flows and fail closed. Referral codes are sanitized from `/register/?ref=...`, carried in session, persisted on `RegistrationApplication`, and sent only as an allowlisted analytics property.

**Tech Stack:** Django 5, server-rendered templates, vanilla JavaScript, `requests` already installed, pytest/pytest-django, ruff, mypy, uv.

---

## 1. Design decisions

### 1.1 Provider boundary

Use `apps/analytics/` instead of placing helpers in `apps/registrations/`.

**Why:** Analytics crosses accounts, registrations, templates, and docs. A small app boundary keeps provider-specific code away from business services and lets Plausible be swapped for Umami if the platform comparison rejects it.

Runtime API:

```python
# apps/analytics/services.py
from collections.abc import Mapping
from django.http import HttpRequest


def track_event(
    name: str,
    props: Mapping[str, object] | None = None,
    *,
    request: HttpRequest | None = None,
) -> None:
    """Send a sanitized analytics event when server analytics is enabled.

    This function never raises into caller flows.
    """
```

### 1.2 Allowlist sanitizer

Drop every event property that is not explicitly allowlisted.

**Why:** PII detection is brittle. Allowlisting fixed enum-like properties is smaller and safer.

Allowed keys:

```python
ALLOWED_PROP_KEYS = {
    "page_area",
    "event_source",
    "application_status",
    "referral_code",
    "error_kind",
}
```

### 1.3 Hybrid browser + server tracking

Use browser script for pageviews, referrers, CTA clicks, empty/error markers. Use server events for milestone state changes: `registration_start`, `email_verified`, `application_submitted`.

**Why:** Page/referrer data belongs in the analytics script. Business milestones are more reliable server-side because redirects, validation, and disabled JS can hide browser events.

### 1.4 Separate flags

Use two independent flags:

```python
ANALYTICS_BROWSER_ENABLED = False
ANALYTICS_SERVER_ENABLED = False
```

**Why:** Lets production enable pageviews first and server events later if provider/API config needs validation.

### 1.5 No analytics models

Add only `RegistrationApplication.referral_code`.

**Why:** Native analytics dashboard is the reporting surface for P10. Django storage is needed only to preserve referral attribution for future reporting.

---

## 2. File-by-file plan

### Create

- `apps/analytics/__init__.py` — package marker.
- `apps/analytics/apps.py` — `AnalyticsConfig`.
- `apps/analytics/config.py` — reads settings and validates provider config.
- `apps/analytics/sanitize.py` — referral code sanitizer and property allowlist.
- `apps/analytics/providers.py` — stub + Plausible event sender.
- `apps/analytics/services.py` — public `track_event` + milestone helper functions.
- `apps/analytics/templatetags/__init__.py` — template tag package marker.
- `apps/analytics/templatetags/analytics_tags.py` — inclusion tag for browser analytics partial.
- `static/js/analytics_events.js` — tiny declarative browser event tracker.
- `templates/analytics/browser.html` — parent-only analytics script partial.
- `tests/analytics/test_config.py` — settings/config behavior tests.
- `tests/analytics/test_sanitize.py` — sanitizer unit tests.
- `tests/analytics/test_services.py` — server helper/provider behavior tests.
- `tests/analytics/test_browser_template.py` — script/JS hook rendering tests.
- `tests/registrations/test_referral_code.py` — referral session carry + persistence tests.
- `docs/analytics.md` — operator/privacy guide.

### Modify

- `fk_cesis_mms/settings.py` — add `apps.analytics` and analytics env settings.
- `.env.example` — add analytics flags/provider env vars.
- `apps/registrations/models.py` — add `referral_code` field.
- `apps/registrations/migrations/` — add migration for `referral_code`.
- `apps/registrations/views.py` — capture `?ref=...`, pass referral to draft creation, track `registration_start` and `application_submitted`.
- `apps/registrations/services.py` — persist `referral_code` on new application only.
- `apps/accounts/views.py` — track `email_verified`.
- `templates/parent_ui/base_parent_page.html` — include analytics partial on parent surfaces only.
- `templates/registrations/start_registration.html` — CTA event hook.
- `templates/registrations/parent_portal.html` — portal event, CTA hooks, empty-state event.
- `templates/registrations/application_workspace.html` — submit CTA and validation-summary hooks.
- `templates/parent_ui/includes/hero_card.html` — portal hero CTA hooks.
- `templates/parent_ui/includes/empty_state.html` — optional analytics attrs for empty-state impression.
- `templates/parent_ui/includes/error_state.html` — optional analytics attrs for error-state impression.
- `docs/superpowers/specs/2026-07-02-p11-family-admin-hub-design.md` — already renamed/relabelled during brainstorming; no implementation change.
- `docs/superpowers/specs/2026-07-08-p10-analytics-funnel-design.md` — source spec; no implementation change.

---

## 3. Test strategy

Framework: `pytest` + `pytest-django`.

Test only contract-level analytics behavior. Do not test vendor dashboard internals.

### Test

- Sanitizer:
  - valid referral codes normalize to lowercase and survive;
  - invalid referral codes return empty string;
  - overlong codes are truncated to 64 chars;
  - non-allowlisted props are dropped.
- Provider/services:
  - disabled server analytics sends nothing;
  - `stub` provider records no external calls;
  - Plausible provider payload uses sanitized props;
  - provider failure is swallowed and logged.
- Referral flow:
  - `/register/?ref=coach-a` stores session referral;
  - `/applications/new/` persists referral on new `RegistrationApplication`;
  - no ref produces blank `referral_code`;
  - invalid ref is ignored.
- Template/browser:
  - browser script absent by default;
  - browser script present on parent pages when enabled/configured;
  - admin page never renders analytics script;
  - fixed `data-analytics-event` hooks appear on CTAs and empty/error states.
- Milestones:
  - successful email verification calls `track_email_verified`;
  - new application creation calls `track_registration_start`;
  - successful submit calls `track_application_submitted`;
  - failures/invalid forms do not emit submit milestone.

### Do not test

- Plausible/Umami/Matomo/PostHog dashboard UI.
- Referrer ranking in vendor dashboard.
- Browser network delivery to real analytics provider.
- Admin reporting for referral codes; out of P10 first slice.

---

## 4. Acceptance criteria per unit

### Analytics app

- `track_event()` never raises.
- Server analytics disabled by default.
- Only allowlisted props are sent.
- Provider config missing means no send, not crash.

### Referral code

- `?ref=coach-a` persists as `coach-a` on the created application.
- Code is lowercase, max 64 chars, and contains only `[a-z0-9_-]`.
- Invalid code is ignored silently.

### Browser tracking

- Parent pages render analytics script only when `ANALYTICS_BROWSER_ENABLED=true` and provider config is present.
- Admin pages render no analytics script.
- CTA/empty/error hooks use fixed event names only.

### Server milestones

- `registration_start`, `email_verified`, and `application_submitted` emit when `ANALYTICS_SERVER_ENABLED=true`.
- They do not emit when disabled.
- Analytics provider failures do not break user flows.

### Docs

- `docs/analytics.md` documents platform choice, env vars, event catalog, privacy/GDPR posture, referral rules, and production enablement.

---

## 5. Documentation scope

Create `docs/analytics.md` with these sections:

1. Selected platform and comparison result.
2. Environment variables.
3. Event catalog.
4. Referral-code attribution.
5. Privacy/GDPR posture.
6. Production enablement checklist.
7. Explicit forbidden payloads and forbidden surfaces.

Update `.env.example` only. Do not update deployment repo from this app plan.

---

## 6. Implementation tasks

### Task 1: Analytics settings and app skeleton

**Files:**
- Create: `apps/analytics/__init__.py`
- Create: `apps/analytics/apps.py`
- Create: `apps/analytics/config.py`
- Modify: `fk_cesis_mms/settings.py`
- Modify: `.env.example`
- Test: `tests/analytics/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/analytics/test_config.py`:

```python
from django.test import override_settings

from apps.analytics.config import analytics_browser_configured, analytics_server_configured


@override_settings(
    ANALYTICS_BROWSER_ENABLED=False,
    ANALYTICS_SERVER_ENABLED=False,
    ANALYTICS_PROVIDER="stub",
    ANALYTICS_DOMAIN="",
    ANALYTICS_API_URL="",
)
def test_analytics_disabled_by_default():
    assert analytics_browser_configured() is False
    assert analytics_server_configured() is False


@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_browser_config_requires_provider_domain_and_api_url():
    assert analytics_browser_configured() is True


@override_settings(
    ANALYTICS_SERVER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_server_configured_for_plausible_without_api_key():
    assert analytics_server_configured() is True
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/analytics/test_config.py -q
```

Expected: fail because `apps.analytics` does not exist.

- [ ] **Step 3: Create analytics app skeleton**

Create `apps/analytics/__init__.py` empty.

Create `apps/analytics/apps.py`:

```python
from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
```

Create `apps/analytics/config.py`:

```python
from django.conf import settings


SUPPORTED_PROVIDERS = {"stub", "plausible"}


def analytics_provider() -> str:
    provider = str(getattr(settings, "ANALYTICS_PROVIDER", "stub") or "stub").lower()
    if provider not in SUPPORTED_PROVIDERS:
        return "stub"
    return provider


def analytics_domain() -> str:
    return str(getattr(settings, "ANALYTICS_DOMAIN", "") or "").strip()


def analytics_api_url() -> str:
    return str(getattr(settings, "ANALYTICS_API_URL", "") or "").rstrip("/")


def analytics_browser_configured() -> bool:
    if not bool(getattr(settings, "ANALYTICS_BROWSER_ENABLED", False)):
        return False
    if analytics_provider() == "stub":
        return True
    return bool(analytics_domain() and analytics_api_url())


def analytics_server_configured() -> bool:
    if not bool(getattr(settings, "ANALYTICS_SERVER_ENABLED", False)):
        return False
    if analytics_provider() == "stub":
        return True
    return bool(analytics_domain() and analytics_api_url())
```

Modify `fk_cesis_mms/settings.py`:

```python
INSTALLED_APPS = [
    "apps.core.apps.FkAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # FK Cēsis MMS domain apps
    "apps.core",
    "apps.accounts",
    "apps.registrations",
    "apps.members",
    "apps.agreements",
    "apps.billing",
    "apps.documents",
    "apps.integrations",
    "apps.addresses",
    "apps.analytics",
    # Background-job runner (P3.5)
    "django_q",
]
```

Add near other integration settings in `fk_cesis_mms/settings.py`:

```python
# Analytics (P10). Disabled by default; enable browser/server channels separately.
ANALYTICS_PROVIDER = os.environ.get("ANALYTICS_PROVIDER") or "stub"
ANALYTICS_BROWSER_ENABLED = os.environ.get("ANALYTICS_BROWSER_ENABLED", "false").lower() in {"1", "true", "yes"}
ANALYTICS_SERVER_ENABLED = os.environ.get("ANALYTICS_SERVER_ENABLED", "false").lower() in {"1", "true", "yes"}
ANALYTICS_DOMAIN = os.environ.get("ANALYTICS_DOMAIN", "")
ANALYTICS_API_URL = os.environ.get("ANALYTICS_API_URL", "")
ANALYTICS_API_KEY = os.environ.get("ANALYTICS_API_KEY", "")
ANALYTICS_TIMEOUT_SECONDS = float(os.environ.get("ANALYTICS_TIMEOUT_SECONDS", "2"))
```

Append to `.env.example`:

```dotenv
# Analytics (P10). Keep disabled until privacy/GDPR setup is reviewed.
ANALYTICS_PROVIDER=stub
ANALYTICS_BROWSER_ENABLED=false
ANALYTICS_SERVER_ENABLED=false
ANALYTICS_DOMAIN=
ANALYTICS_API_URL=
ANALYTICS_API_KEY=
ANALYTICS_TIMEOUT_SECONDS=2
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/analytics/test_config.py -q
```

Expected: pass.

---

### Task 2: Sanitizer and referral-code rules

**Files:**
- Create: `apps/analytics/sanitize.py`
- Test: `tests/analytics/test_sanitize.py`

- [ ] **Step 1: Write failing sanitizer tests**

Create `tests/analytics/test_sanitize.py`:

```python
from apps.analytics.sanitize import sanitize_event_props, sanitize_referral_code


def test_sanitize_referral_code_accepts_safe_code():
    assert sanitize_referral_code(" Coach-A_42 ") == "coach-a_42"


def test_sanitize_referral_code_rejects_unsafe_code():
    assert sanitize_referral_code("coach@example.com") == ""
    assert sanitize_referral_code("../secret") == ""
    assert sanitize_referral_code("Jānis") == ""


def test_sanitize_referral_code_caps_length():
    assert sanitize_referral_code("a" * 100) == "a" * 64


def test_sanitize_event_props_keeps_allowlisted_values_only():
    props = sanitize_event_props(
        {
            "page_area": "portal",
            "event_source": "hero",
            "application_status": "draft",
            "referral_code": "coach-a",
            "error_kind": "empty_state",
            "email": "parent@example.com",
            "guardian_id": 123,
        }
    )
    assert props == {
        "page_area": "portal",
        "event_source": "hero",
        "application_status": "draft",
        "referral_code": "coach-a",
        "error_kind": "empty_state",
    }


def test_sanitize_event_props_sanitizes_referral_code_value():
    assert sanitize_event_props({"referral_code": "BAD CODE!"}) == {}
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/analytics/test_sanitize.py -q
```

Expected: fail because sanitizer does not exist.

- [ ] **Step 3: Implement sanitizer**

Create `apps/analytics/sanitize.py`:

```python
from collections.abc import Mapping
import re

REFERRAL_CODE_MAX_LENGTH = 64
_REFERRAL_RE = re.compile(r"^[a-z0-9_-]+$")

ALLOWED_PROP_KEYS = {
    "page_area",
    "event_source",
    "application_status",
    "referral_code",
    "error_kind",
}


def sanitize_referral_code(value: object) -> str:
    code = str(value or "").strip().lower()
    if not code:
        return ""
    code = code[:REFERRAL_CODE_MAX_LENGTH]
    if not _REFERRAL_RE.fullmatch(code):
        return ""
    return code


def sanitize_event_props(props: Mapping[str, object] | None) -> dict[str, str]:
    if not props:
        return {}
    clean: dict[str, str] = {}
    for key, value in props.items():
        if key not in ALLOWED_PROP_KEYS:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if key == "referral_code":
            text = sanitize_referral_code(text)
            if not text:
                continue
        clean[key] = text[:128]
    return clean
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/analytics/test_sanitize.py -q
```

Expected: pass.

---

### Task 3: Analytics provider and service helper

**Files:**
- Create: `apps/analytics/providers.py`
- Create: `apps/analytics/services.py`
- Test: `tests/analytics/test_services.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/analytics/test_services.py`:

```python
from unittest.mock import Mock

from django.test import RequestFactory, override_settings

from apps.analytics import providers
from apps.analytics.services import (
    track_application_submitted,
    track_email_verified,
    track_event,
    track_registration_start,
)


@override_settings(ANALYTICS_SERVER_ENABLED=False, ANALYTICS_PROVIDER="stub")
def test_track_event_disabled_does_not_send(monkeypatch):
    send = Mock()
    monkeypatch.setattr(providers, "send_event", send)

    track_event("registration_start", {"page_area": "registration"})

    send.assert_not_called()


@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_track_event_sanitizes_props(monkeypatch):
    send = Mock()
    monkeypatch.setattr(providers, "send_event", send)

    track_event(
        "registration_start",
        {"page_area": "registration", "email": "parent@example.com"},
    )

    send.assert_called_once_with(
        "registration_start",
        {"page_area": "registration"},
        request=None,
    )


@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_track_event_swallows_provider_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("analytics down")

    monkeypatch.setattr(providers, "send_event", fail)

    track_event("registration_start", {"page_area": "registration"})


@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_milestone_helpers_emit_fixed_events(monkeypatch):
    send = Mock()
    monkeypatch.setattr(providers, "send_event", send)
    request = RequestFactory().get("/register/?ref=coach-a")

    track_registration_start(request, referral_code="coach-a")
    track_email_verified(request, referral_code="coach-a")
    track_application_submitted(request, referral_code="coach-a", application_status="submitted")

    assert [call.args[0] for call in send.call_args_list] == [
        "registration_start",
        "email_verified",
        "application_submitted",
    ]
    assert send.call_args_list[0].args[1]["referral_code"] == "coach-a"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/analytics/test_services.py -q
```

Expected: fail because services/providers do not exist.

- [ ] **Step 3: Implement provider and service**

Create `apps/analytics/providers.py`:

```python
from collections.abc import Mapping

from django.conf import settings
from django.http import HttpRequest
import requests

from apps.analytics.config import analytics_api_url, analytics_domain, analytics_provider


def send_event(
    name: str,
    props: Mapping[str, str],
    *,
    request: HttpRequest | None = None,
) -> None:
    provider = analytics_provider()
    if provider == "plausible":
        _send_plausible_event(name, props, request=request)


def _send_plausible_event(
    name: str,
    props: Mapping[str, str],
    *,
    request: HttpRequest | None = None,
) -> None:
    api_url = analytics_api_url()
    domain = analytics_domain()
    if not api_url or not domain:
        return

    url = f"{api_url}/api/event"
    page_url = "/"
    if request is not None:
        page_url = request.build_absolute_uri(request.path)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": request.META.get("HTTP_USER_AGENT", "FK-Cesis-MMS") if request is not None else "FK-Cesis-MMS",
    }
    payload: dict[str, object] = {
        "name": name,
        "domain": domain,
        "url": page_url,
    }
    if props:
        payload["props"] = dict(props)
    if request is not None and request.META.get("REMOTE_ADDR"):
        headers["X-Forwarded-For"] = request.META["REMOTE_ADDR"]

    requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=float(getattr(settings, "ANALYTICS_TIMEOUT_SECONDS", 2)),
    ).raise_for_status()
```

Create `apps/analytics/services.py`:

```python
from collections.abc import Mapping
import logging

from django.http import HttpRequest

from apps.analytics.config import analytics_server_configured
from apps.analytics import providers
from apps.analytics.sanitize import sanitize_event_props, sanitize_referral_code

logger = logging.getLogger(__name__)


def track_event(
    name: str,
    props: Mapping[str, object] | None = None,
    *,
    request: HttpRequest | None = None,
) -> None:
    if not analytics_server_configured():
        return
    clean_props = sanitize_event_props(props)
    try:
        providers.send_event(name, clean_props, request=request)
    except Exception:
        logger.warning("analytics_event_failed", extra={"event_name": name}, exc_info=True)


def track_registration_start(request: HttpRequest | None, *, referral_code: object = "") -> None:
    track_event(
        "registration_start",
        {
            "page_area": "registration",
            "event_source": "new_application",
            "referral_code": sanitize_referral_code(referral_code),
        },
        request=request,
    )


def track_email_verified(request: HttpRequest | None, *, referral_code: object = "") -> None:
    track_event(
        "email_verified",
        {
            "page_area": "registration",
            "event_source": "email_verification",
            "referral_code": sanitize_referral_code(referral_code),
        },
        request=request,
    )


def track_application_submitted(
    request: HttpRequest | None,
    *,
    referral_code: object = "",
    application_status: object = "submitted",
) -> None:
    track_event(
        "application_submitted",
        {
            "page_area": "application",
            "event_source": "submit",
            "application_status": application_status,
            "referral_code": sanitize_referral_code(referral_code),
        },
        request=request,
    )
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/analytics/test_services.py -q
```

Expected: pass.

---

### Task 4: Referral code persistence

**Files:**
- Modify: `apps/registrations/models.py`
- Create: `apps/registrations/migrations/0011_registrationapplication_referral_code.py`
- Modify: `apps/registrations/services.py`
- Modify: `apps/registrations/views.py`
- Test: `tests/registrations/test_referral_code.py`

- [ ] **Step 1: Write failing referral tests**

Create `tests/registrations/test_referral_code.py`:

```python
import pytest
from django.urls import reverse

from apps.registrations.models import RegistrationApplication


@pytest.mark.django_db
def test_register_ref_query_param_is_stored_in_session(client):
    response = client.get(reverse("registrations:start-registration") + "?ref=Coach-A_42")

    assert response.status_code == 200
    assert client.session["registration_referral_code"] == "coach-a_42"


@pytest.mark.django_db
def test_invalid_register_ref_query_param_is_ignored(client):
    response = client.get(reverse("registrations:start-registration") + "?ref=parent@example.com")

    assert response.status_code == 200
    assert "registration_referral_code" not in client.session


@pytest.mark.django_db
def test_new_application_persists_referral_code(verified_client, parent_account, kit_sizes):
    session = verified_client.session
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    application = RegistrationApplication.objects.get(parent_account=parent_account)
    assert application.referral_code == "coach-a"


@pytest.mark.django_db
def test_new_application_without_referral_code_stores_blank(verified_client, parent_account, kit_sizes):
    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    application = RegistrationApplication.objects.get(parent_account=parent_account)
    assert application.referral_code == ""
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/registrations/test_referral_code.py -q
```

Expected: fail because field/session logic does not exist.

- [ ] **Step 3: Add model field and migration**

Modify `apps/registrations/models.py` after `preferred_payment_mode`:

```python
    referral_code = models.CharField(max_length=64, blank=True, default="")
```

Create migration with:

```bash
uv run python manage.py makemigrations registrations
```

Expected: new migration adds `referral_code` field.

- [ ] **Step 4: Persist referral code on draft creation**

Modify `apps/registrations/services.py` function signature:

```python
def create_or_update_draft(
    *,
    data: Mapping[str, Any],
    files: Mapping[str, Any],
    application: RegistrationApplication | None = None,
    verified_account: ParentAccount | None = None,
    reusable_guardian_document: Document | None = None,
    referral_code: str = "",
) -> RegistrationApplication:
```

Inside `if application is None:` block:

```python
    if application is None:
        application = RegistrationApplication()
        application.claimed_email = email
        application.referral_code = referral_code
```

- [ ] **Step 5: Capture referral from `/register/?ref=...`**

Modify `apps/registrations/views.py` imports:

```python
from apps.analytics.sanitize import sanitize_referral_code
```

Add module constant near imports:

```python
REFERRAL_SESSION_KEY = "registration_referral_code"
```

At start of `start_registration()` before account lookup:

```python
    ref = sanitize_referral_code(request.GET.get("ref", ""))
    if ref:
        request.session[REFERRAL_SESSION_KEY] = ref
    elif "ref" in request.GET:
        request.session.pop(REFERRAL_SESSION_KEY, None)
```

Pass referral in `new_application()` GET and POST `create_or_update_draft(...)` calls:

```python
                referral_code=str(request.session.get(REFERRAL_SESSION_KEY, "")),
```

and:

```python
        referral_code=str(request.session.get(REFERRAL_SESSION_KEY, "")),
```

Do not pass referral on updates to existing applications.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/registrations/test_referral_code.py -q
```

Expected: pass.

---

### Task 5: Server milestone hooks

**Files:**
- Modify: `apps/accounts/views.py`
- Modify: `apps/registrations/views.py`
- Test: `tests/analytics/test_milestone_hooks.py`

- [ ] **Step 1: Write failing milestone tests**

Create `tests/analytics/test_milestone_hooks.py`:

```python
from unittest.mock import Mock

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.services import issue_one_time_code
from apps.analytics import services as analytics_services
from apps.registrations.models import RegistrationApplication


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_email_verified_milestone_emitted(client, monkeypatch):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_email_verified", send)
    code = issue_one_time_code("parent@example.com")
    session = client.session
    session["pending_verification_email"] = "parent@example.com"
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = client.post(reverse("accounts:verify-one-time-code"), {"code": code})

    assert response.status_code == 302
    send.assert_called_once()
    assert send.call_args.kwargs["referral_code"] == "coach-a"


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_registration_start_milestone_emitted(verified_client, monkeypatch, kit_sizes):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_registration_start", send)
    session = verified_client.session
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    send.assert_called_once()
    assert send.call_args.kwargs["referral_code"] == "coach-a"


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_application_submitted_milestone_emitted(verified_client, draft_with_documents, submit_payload, monkeypatch):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_application_submitted", send)
    draft_with_documents.referral_code = "coach-a"
    draft_with_documents.save(update_fields=["referral_code", "updated_at"])

    response = verified_client.post(
        reverse("registrations:application-workspace", args=[draft_with_documents.pk]),
        {**submit_payload, "submit_action": "submit"},
    )

    assert response.status_code == 302
    draft_with_documents.refresh_from_db()
    assert draft_with_documents.status == RegistrationApplication.Status.SUBMITTED
    send.assert_called_once()
    assert send.call_args.kwargs["referral_code"] == "coach-a"
    assert send.call_args.kwargs["application_status"] == "submitted"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/analytics/test_milestone_hooks.py -q
```

Expected: fail because views do not call milestone helpers.

- [ ] **Step 3: Add milestone calls**

Modify `apps/accounts/views.py` imports:

```python
from apps.analytics import services as analytics_services
```

After successful code verification and before redirect:

```python
        analytics_services.track_email_verified(
            request,
            referral_code=request.session.get("registration_referral_code", ""),
        )
```

Modify `apps/registrations/views.py` imports:

```python
from apps.analytics import services as analytics_services
```

After `create_or_update_draft(...)` succeeds in `new_application()` GET and POST branches:

```python
            analytics_services.track_registration_start(
                request,
                referral_code=application.referral_code,
            )
```

and:

```python
    analytics_services.track_registration_start(
        request,
        referral_code=application.referral_code,
    )
```

After `submit_application(application, account)` succeeds in `application_workspace()` submit branch:

```python
                analytics_services.track_application_submitted(
                    request,
                    referral_code=application.referral_code,
                    application_status=application.status,
                )
```

After `submit_application(application, account)` succeeds in `submit_registration()`:

```python
        analytics_services.track_application_submitted(
            request,
            referral_code=application.referral_code,
            application_status=application.status,
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/analytics/test_milestone_hooks.py -q
```

Expected: pass.

---

### Task 6: Browser analytics template and script

**Files:**
- Create: `templates/analytics/browser.html`
- Create: `static/js/analytics_events.js`
- Modify: `templates/parent_ui/base_parent_page.html`
- Test: `tests/analytics/test_browser_template.py`

- [ ] **Step 1: Write failing browser template tests**

Create `tests/analytics/test_browser_template.py`:

```python
import pytest
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(ANALYTICS_BROWSER_ENABLED=False, ANALYTICS_PROVIDER="stub")
def test_parent_page_does_not_render_analytics_when_disabled(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"analytics_events.js" not in response.content
    assert b"data-analytics-browser" not in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_parent_page_renders_analytics_when_enabled(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"analytics_events.js" in response.content
    assert b"data-analytics-browser" in response.content
    assert b"mms.fkcesis.lv" in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_admin_page_never_renders_parent_analytics(admin_client):
    response = admin_client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert b"analytics_events.js" not in response.content
    assert b"data-analytics-browser" not in response.content
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/analytics/test_browser_template.py -q
```

Expected: fail because analytics partial/script do not exist.

- [ ] **Step 3: Add template context helper**

Add to `apps/analytics/config.py`:

```python

def browser_template_context() -> dict[str, object]:
    return {
        "analytics_browser_enabled": analytics_browser_configured(),
        "analytics_provider": analytics_provider(),
        "analytics_domain": analytics_domain(),
        "analytics_api_url": analytics_api_url(),
    }
```

- [ ] **Step 4: Expose context in parent base view context**

Simplest safe path: create a tiny inclusion tag.

Create `apps/analytics/templatetags/__init__.py` empty.

Create `apps/analytics/templatetags/analytics_tags.py`:

```python
from django import template

from apps.analytics.config import browser_template_context

register = template.Library()


@register.inclusion_tag("analytics/browser.html")
def analytics_browser():
    return browser_template_context()
```

- [ ] **Step 5: Create browser partial**

Create `templates/analytics/browser.html`:

```django
{% load static %}
{% if analytics_browser_enabled %}
  {% if analytics_provider == "plausible" %}
    <script defer data-domain="{{ analytics_domain }}" src="{{ analytics_api_url }}/js/script.js" data-analytics-browser></script>
    <script>window.plausible = window.plausible || function(){(window.plausible.q=window.plausible.q||[]).push(arguments)}</script>
  {% elif analytics_provider == "stub" %}
    <script data-analytics-browser>window.plausible = window.plausible || function(){}</script>
  {% endif %}
  <script src="{% static 'js/analytics_events.js' %}" defer></script>
{% endif %}
```

- [ ] **Step 6: Include only in parent base**

Modify `templates/parent_ui/base_parent_page.html`. Put the include inside `body_content`, not `extra_js`, so child templates that override `extra_js` cannot accidentally drop analytics.

```django
{% extends "base.html" %}
{% load static %}
{% load analytics_tags %}

{% block body_content %}
<div class="fk-parent-page">

  {# Site header #}
  {% include "parent_ui/includes/header.html" %}

  <div class="fk-page-wrapper">
    {% block page_content %}{% endblock %}
  </div>

</div>
{% analytics_browser %}
{% endblock %}
```

- [ ] **Step 7: Create JS tracker**

Create `static/js/analytics_events.js`:

```javascript
(function () {
  function send(name, props) {
    if (!name || typeof window.plausible !== 'function') return;
    window.plausible(name, { props: props || {} });
  }

  function propsFrom(el) {
    var props = {};
    ['pageArea', 'eventSource', 'applicationStatus', 'referralCode', 'errorKind'].forEach(function (key) {
      var value = el.dataset['analytics' + key.charAt(0).toUpperCase() + key.slice(1)];
      if (value) {
        var propName = key.replace(/[A-Z]/g, function (letter) { return '_' + letter.toLowerCase(); });
        props[propName] = value;
      }
    });
    return props;
  }

  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-analytics-event]');
    if (!target) return;
    send(target.getAttribute('data-analytics-event'), propsFrom(target));
  });

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-analytics-impression]').forEach(function (el) {
      send(el.getAttribute('data-analytics-impression'), propsFrom(el));
    });
  });
})();
```

- [ ] **Step 8: Run tests**

Run:

```bash
uv run pytest tests/analytics/test_browser_template.py -q
```

Expected: pass.

---

### Task 7: Browser event hooks on parent templates

**Files:**
- Modify: `templates/registrations/start_registration.html`
- Modify: `templates/registrations/parent_portal.html`
- Modify: `templates/registrations/application_workspace.html`
- Modify: `templates/parent_ui/includes/empty_state.html`
- Modify: `templates/parent_ui/includes/error_state.html`
- Test: `tests/analytics/test_browser_hooks.py`

- [ ] **Step 1: Write failing hook tests**

Create `tests/analytics/test_browser_hooks.py`:

```python
import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_start_registration_has_start_cta_hook(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b'data-analytics-event="cta_start_registration"' in response.content


@pytest.mark.django_db
def test_portal_has_visit_impression(verified_client):
    response = verified_client.get(reverse("registrations:parent-portal"))

    assert response.status_code == 200
    assert b'data-analytics-impression="portal_visit"' in response.content


@pytest.mark.django_db
def test_empty_portal_has_empty_state_impression(verified_client):
    response = verified_client.get(reverse("registrations:parent-portal"))

    assert response.status_code == 200
    assert b'data-analytics-impression="portal_empty_state_shown"' in response.content
    assert b'data-analytics-event="cta_new_application"' in response.content


@pytest.mark.django_db
def test_portal_application_card_has_continue_or_view_hook(verified_client, draft_application):
    response = verified_client.get(reverse("registrations:parent-portal"))

    assert response.status_code == 200
    assert b'data-analytics-event="cta_continue_application"' in response.content


@pytest.mark.django_db
def test_application_workspace_has_submit_hook(verified_client, draft_application):
    response = verified_client.get(reverse("registrations:application-workspace", args=[draft_application.pk]))

    assert response.status_code == 200
    assert b'data-analytics-event="cta_submit_application"' in response.content
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/analytics/test_browser_hooks.py -q
```

Expected: fail because hooks are absent.

- [ ] **Step 3: Add hooks**

Modify submit button in `templates/registrations/start_registration.html`:

```django
      <button type="submit"
              class="fk-button fk-button--primary fk-button--full"
              data-analytics-event="cta_start_registration"
              data-analytics-page-area="registration"
              data-analytics-event-source="email_entry">Turpināt</button>
```

Add a portal visit marker near the top of `templates/registrations/parent_portal.html` after the intro paragraph:

```django
<div data-analytics-impression="portal_visit" data-analytics-page-area="portal" data-analytics-event-source="portal_page"></div>
```

Modify `templates/parent_ui/includes/empty_state.html` root div:

```django
<div class="fk-empty-state" data-empty-state
     {% if analytics_impression %}data-analytics-impression="{{ analytics_impression }}"{% endif %}
     {% if analytics_page_area %}data-analytics-page-area="{{ analytics_page_area }}"{% endif %}
     {% if analytics_error_kind %}data-analytics-error-kind="{{ analytics_error_kind }}"{% endif %}>
```

Modify CTA anchor inside same file:

```django
    <a href="{{ cta_url }}" class="fk-button fk-button--primary fk-button--full fk-empty-state__cta"
       {% if analytics_cta_event %}data-analytics-event="{{ analytics_cta_event }}"{% endif %}
       {% if analytics_page_area %}data-analytics-page-area="{{ analytics_page_area }}"{% endif %}
       {% if analytics_event_source %}data-analytics-event-source="{{ analytics_event_source }}"{% endif %}>{{ cta_label }}</a>
```

Modify `templates/parent_ui/includes/error_state.html` root div:

```django
<div class="fk-error-state" role="alert" data-error-state
     {% if analytics_impression %}data-analytics-impression="{{ analytics_impression }}"{% endif %}
     {% if analytics_page_area %}data-analytics-page-area="{{ analytics_page_area }}"{% endif %}
     {% if analytics_error_kind %}data-analytics-error-kind="{{ analytics_error_kind }}"{% endif %}>
```

Modify empty-state include in `templates/registrations/parent_portal.html`:

```django
{% include "parent_ui/includes/empty_state.html" with title="Nav pieteikumu" body="Jums vēl nav neviena pieteikuma." cta_url=new_application_url cta_label="Sākt jaunu reģistrāciju" analytics_impression="portal_empty_state_shown" analytics_cta_event="cta_new_application" analytics_page_area="portal" analytics_event_source="empty_state" analytics_error_kind="empty_state" %}
```

Add to editable app action link in `templates/registrations/parent_portal.html`:

```django
        <a href="{% url 'registrations:application-workspace' app.pk %}" class="fk-button fk-button--primary fk-button--full" data-analytics-event="cta_continue_application" data-analytics-page-area="portal" data-analytics-event-source="application_card" data-analytics-application-status="{{ app.status }}">Turpināt pieteikumu</a>
```

Add to read-only app action link:

```django
        <a href="{% url 'registrations:application-workspace' app.pk %}" class="fk-button fk-button--secondary fk-button--full" data-analytics-event="cta_continue_application" data-analytics-page-area="portal" data-analytics-event-source="application_card" data-analytics-application-status="{{ app.status }}">Skatīt pieteikumu</a>
```

Modify `templates/parent_ui/includes/hero_card.html` portal actions:

```django
      {% if primary_application %}<a href="{% url 'registrations:application-workspace' primary_application.pk %}" class="fk-button fk-button--primary" data-analytics-event="cta_continue_application" data-analytics-page-area="portal" data-analytics-event-source="hero">Turpināt pieteikumu</a>{% endif %}
      <a href="{% url 'registrations:new-application' %}" class="fk-button fk-button--red" data-analytics-event="cta_new_application" data-analytics-page-area="portal" data-analytics-event-source="hero">＋ Sākt jaunu reģistrāciju</a>
```

Add to helper-card email-check link:

```django
  <a href="{% url 'registrations:start-registration' %}" class="fk-button fk-button--secondary fk-button--full" data-analytics-event="cta_start_registration" data-analytics-page-area="portal" data-analytics-event-source="check_other_email">✉ Pārbaudīt citu e-pastu</a>
```

Modify submit button in `templates/registrations/application_workspace.html`:

```django
          <button type="submit" name="submit_action" value="submit" class="fk-button fk-button--primary fk-button--full" data-analytics-event="cta_submit_application" data-analytics-page-area="application" data-analytics-event-source="review_step" data-analytics-application-status="{{ application.status }}">Iesniegt pieteikumu</button>
```

Add validation-summary impression by wrapping existing error summary include in `templates/registrations/application_workspace.html`:

```django
{% if form.errors %}
<div data-analytics-impression="application_validation_error_summary_shown"
     data-analytics-page-area="application"
     data-analytics-error-kind="validation_summary"></div>
{% endif %}
{% include "parent_ui/includes/error_summary.html" with items=form.error_summary_items %}
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/analytics/test_browser_hooks.py -q
```

Expected: pass.

---

### Task 8: Platform comparison and operator docs

**Files:**
- Create: `docs/analytics.md`
- Modify: `docs/superpowers/specs/2026-07-08-p10-analytics-funnel-design.md` only if implementation discovers a necessary correction
- Test: none beyond markdown review

- [ ] **Step 1: Write `docs/analytics.md`**

Create `docs/analytics.md`:

```markdown
# Analytics and registration funnel

## Selected platform

P10 uses Plausible by default, with the app code isolated behind `apps.analytics` so Umami can replace it if needed.

| Platform | Privacy/GDPR | Funnel/events | Ops burden | Decision |
|---|---|---|---|---|
| Plausible | Privacy-first, cookie-free mode, EU/self-host options, DPA path | Pageviews, referrers, top pages, custom events, event props, server events | Low | Selected |
| Umami | Privacy-focused, self-host-friendly | Pageviews, custom events, server `/api/send` | Low/medium if self-hosted | Fallback |
| Matomo | Mature, configurable privacy | Strong but broad | Higher | Too heavy for P10 |
| PostHog | EU/self-host options, but product suite needs careful disabling | Strong funnels | Higher; session replay/autocapture risk | Too broad for P10 |

## Environment variables

- `ANALYTICS_PROVIDER=plausible`
- `ANALYTICS_BROWSER_ENABLED=false`
- `ANALYTICS_SERVER_ENABLED=false`
- `ANALYTICS_DOMAIN=mms.fkcesis.lv`
- `ANALYTICS_API_URL=https://plausible.example.lv`
- `ANALYTICS_API_KEY=` — unused for Plausible event API unless deployment requires proxy/auth
- `ANALYTICS_TIMEOUT_SECONDS=2`

## Event catalog

### Browser events

- `portal_visit`
- `cta_start_registration`
- `cta_continue_application`
- `cta_new_application`
- `cta_submit_application`
- `portal_empty_state_shown`
- `portal_error_state_shown`
- `application_validation_error_summary_shown`

### Server events

- `registration_start`
- `email_verified`
- `application_submitted`

## Allowed properties

- `page_area`
- `event_source`
- `application_status`
- `referral_code`
- `error_kind`

## Referral codes

Referral code enters through `/register/?ref=<code>`. Codes are lowercased, limited to 64 characters, and may contain only ASCII letters, numbers, dash, and underscore. Valid codes are stored on `RegistrationApplication.referral_code` and sent to analytics as `referral_code`.

## Forbidden data

Never send names, emails, phone numbers, personal IDs, document metadata, document filenames, free-text form values, or model primary keys to analytics.

## Forbidden surfaces

Admin pages must not render analytics scripts and must not emit analytics events.

## Production enablement checklist

1. Confirm provider DPA or self-host responsibility.
2. Confirm cookie mode, IP handling, and retention in provider settings.
3. Set provider env vars.
4. Enable `ANALYTICS_BROWSER_ENABLED=true`.
5. Verify dashboard pageviews on parent pages.
6. Enable `ANALYTICS_SERVER_ENABLED=true`.
7. Submit a test application and verify funnel events.
8. Confirm no admin pages include analytics script.
```

- [ ] **Step 2: Review docs for PII leak**

Run:

```bash
uv run python -m json.tool opencode.json >/dev/null
```

Expected: pass. This command does not validate markdown; it is the repo's lightweight config sanity check. Manually scan `docs/analytics.md` for accidental real domains/secrets.

---

### Task 9: Full verification

**Files:**
- No new files.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
uv run pytest tests/analytics tests/registrations/test_referral_code.py -q
```

Expected: pass.

- [ ] **Step 2: Run migration check**

Run:

```bash
uv run python manage.py makemigrations --check
```

Expected: `No changes detected`.

- [ ] **Step 3: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: pass.

- [ ] **Step 5: Run type check**

Run:

```bash
uv run mypy .
```

Expected: pass.

---

## 7. Final notes for implementer

- Do not add a new dependency. Use existing `requests` for server event calls.
- Do not track admin pages.
- Do not send raw request/session/user/application objects to analytics.
- Do not add a Django analytics dashboard in P10.
- Do not commit unless the user explicitly requests it in the current session.
