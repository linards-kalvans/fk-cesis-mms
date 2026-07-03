# P5 Slice D — DocuSeal Adapter + Signed-State Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the electronic agreement signing path to a self-hosted DocuSeal instance so a guardian signs online and `Agreement.state` advances to `signed` via webhook, with a stub provider for dev/tests.

**Architecture:** Mirror the existing OCR adapter shape — a boundary module (`apps/integrations/agreement_platform.py`) that switches between a deterministic stub and a real DocuSeal provider (`apps/integrations/docuseal.py`) on `settings.AGREEMENT_PROVIDER_MODE`. Three django-q2 background jobs (create/sync/archive) carry external calls off the request thread. Electronic-path side-effects layer onto the existing Slice C `apps/agreements/services.py` transitions without rewriting them; paper path is untouched. A HMAC-verified webhook drives `signed`.

**Tech Stack:** Django 5.x, django-q2, `requests`, pytest + pytest-django, `responses` (HTTP mocking), ruff, mypy, uv. Branch: `dev`. All work lands on `dev`; nothing is pushed by tasks below.

---

## Context the implementer needs

- **Spec:** `docs/superpowers/specs/2026-05-29-p5-slice-d-docuseal-adapter-design.md` — read it first.
- **Pattern to mirror:** `apps/integrations/ocr.py` (boundary + stub + mode dispatch), `apps/integrations/tiny_idp.py` (real HTTP provider + exception hierarchy), `apps/integrations/tasks.py` (django-q2 job + enqueue helper + transient-retry classification).
- **What you extend, not rewrite:** `apps/agreements/services.py` (Slice C transitions), `apps/registrations/views.py::admin_review_detail` (the staff "Līgums module", ~line 760+), `templates/registrations/admin/_agreement_module.html`.
- **Test harness facts:**
  - Tests run with `Q_CLUSTER_SYNC=1` (`tests/conftest.py:12`), so `django_q.tasks.async_task` runs **in-process synchronously**. To assert "X was enqueued", patch the enqueue helper and assert it was called; to assert job *behavior*, call the job function directly.
  - `tests/agreements/conftest.py` provides fixtures: `actor` (staff user), `agreement_guardian` (Guardian with email `anna@example.test`), `agreement_member` (Member, guardian=agreement_guardian).
  - `tests/registrations/conftest.py` provides `submitted_application` and the `reviewer` fixture pattern (see `tests/registrations/test_agreement_admin_polish.py` for `approve_application(submitted_application, reviewer)` usage).
  - `django.core.mail.outbox` is available because `EMAIL_BACKEND` defaults to the locmem/console backend in tests.
- **Model fields already present** (`apps/agreements/models.py`): `external_provider`, `external_id`, `external_state`, `external_url` (all `blank=True, default=""`). `Agreement.SigningPath.ELECTRONIC == "electronic"`, `.PAPER == "paper"`. `Agreement.State.GENERATED/SENT/SIGNED/VOID`.
- **Member/Guardian fields** (`apps/members/models.py`): `Member.full_name/personal_id/birth_date`, `Guardian.full_name/personal_id/email/address`.

---

## File structure

| File | Responsibility |
|---|---|
| `apps/agreements/models.py` | +`external_error_code` field |
| `apps/agreements/migrations/0003_agreement_external_error_code.py` | schema migration |
| `apps/integrations/agreement_platform.py` (new) | boundary: exceptions, `SubmissionResult`, stub provider, mode dispatch, `verify_webhook_signature` |
| `apps/integrations/docuseal.py` (new) | real provider: HTTP create/sync/archive, HMAC verify, field-payload builders |
| `apps/agreements/messages.py` (new) | Latvian error-code → message map |
| `apps/integrations/tasks.py` (extend) | `create_agreement_submission`, `sync_agreement_submission`, `archive_agreement_submission` jobs + enqueue helpers |
| `apps/agreements/services.py` (extend) | `_should_send_email` gate + electronic side-effects on `mark_agreement_sent`/`void_agreement` |
| `apps/agreements/webhooks.py` (new) + `apps/agreements/urls.py` (new) | HMAC-verified `submission.completed` → `mark_agreement_signed` |
| `fk_cesis_mms/urls.py` (extend) | mount `apps.agreements.urls` |
| `fk_cesis_mms/settings.py` (extend) | +5 settings |
| `apps/registrations/views.py` (extend) | 2 new POST actions in `admin_review_detail` |
| `templates/registrations/admin/_agreement_module.html` (extend) | error/retry/sync/link UI |
| `docs/deployment.md`, `AGENTS.md`, `docs/milestones.md` | docs |

---

## Task 1: Add `external_error_code` field + migration

**Files:**
- Modify: `apps/agreements/models.py` (after the `external_url` field, ~line 58)
- Create: `apps/agreements/migrations/0003_agreement_external_error_code.py`
- Test: `tests/agreements/test_agreement_model.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/agreements/test_agreement_model.py`:

```python
@pytest.mark.django_db
def test_agreement_has_external_error_code_field(agreement_member):
    from apps.agreements.models import Agreement
    from django.utils import timezone

    a = Agreement.objects.create(
        member=agreement_member, generated_at=timezone.now()
    )
    assert a.external_error_code == ""
    a.external_error_code = "auth_failed"
    a.save(update_fields=["external_error_code"])
    a.refresh_from_db()
    assert a.external_error_code == "auth_failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_agreement_model.py::test_agreement_has_external_error_code_field -v`
Expected: FAIL — `AttributeError: 'Agreement' object has no attribute 'external_error_code'` (or migration mismatch).

- [ ] **Step 3: Add the model field**

In `apps/agreements/models.py`, directly after the `external_url` field:

```python
    external_url = models.URLField(blank=True, default="")
    external_error_code = models.CharField(max_length=64, blank=True, default="")
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations agreements`
Expected: creates `apps/agreements/migrations/0003_agreement_external_error_code.py` adding one `AddField`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_agreement_model.py::test_agreement_has_external_error_code_field -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/agreements/models.py apps/agreements/migrations/0003_agreement_external_error_code.py tests/agreements/test_agreement_model.py
git commit -m "feat(agreements): add external_error_code reservation field (P5 Slice D)"
```

---

## Task 2: Boundary module — exceptions, stub, dispatch, `AGREEMENT_PROVIDER_MODE`

**Files:**
- Create: `apps/integrations/agreement_platform.py`
- Modify: `fk_cesis_mms/settings.py` (after the OCR settings block, ~line 169)
- Test: `tests/integrations/test_agreement_platform_adapter.py` (new)

The boundary owns the exception taxonomy; the real provider (Task 3) imports and raises these. Stub mode returns deterministic values and never fires a webhook.

- [ ] **Step 1: Add the setting**

In `fk_cesis_mms/settings.py`, after `OCR_ENCRYPTION_KEY` (~line 169):

```python
# Agreement-platform integration (P5 Slice D — DocuSeal self-hosted).
AGREEMENT_PROVIDER_MODE = os.environ.get("AGREEMENT_PROVIDER_MODE") or "stub"
```

- [ ] **Step 2: Write the failing test**

Create `tests/integrations/test_agreement_platform_adapter.py`:

```python
"""Boundary-level tests for the agreement-platform adapter (stub mode +
exception taxonomy). Real-provider HTTP behavior is tested separately in
test_docuseal_provider.py."""

from __future__ import annotations

import pytest

from apps.integrations import agreement_platform as ap


pytestmark = pytest.mark.django_db


class _FakeAgreement:
    id = 42


def test_stub_create_submission_is_deterministic(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    result = ap.create_submission(_FakeAgreement())
    assert result.external_id == "stub-42"
    assert result.external_url == "https://stub.invalid/42"
    assert result.external_state == "pending"


def test_stub_sync_submission_returns_completed(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    result = ap.sync_submission("stub-42")
    assert result.external_id == "stub-42"
    assert result.external_state == "completed"


def test_stub_archive_submission_is_noop(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    assert ap.archive_submission("stub-42") is None


def test_unknown_mode_raises_config_error(settings):
    settings.AGREEMENT_PROVIDER_MODE = "bogus"
    with pytest.raises(ap.AgreementPlatformConfigError):
        ap.create_submission(_FakeAgreement())


def test_docuseal_mode_dispatches_to_provider(settings, mocker):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    fake = ap.SubmissionResult(
        external_id="ds-1", external_url="https://sign/x", external_state="pending"
    )
    spy = mocker.patch(
        "apps.integrations.docuseal.create_submission", return_value=fake
    )
    result = ap.create_submission(_FakeAgreement())
    assert result is fake
    spy.assert_called_once()


def test_exception_hierarchy():
    assert issubclass(ap.AgreementPlatformConfigError, ap.AgreementPlatformError)
    assert issubclass(ap.AgreementPlatformAuthError, ap.AgreementPlatformError)
    assert issubclass(ap.AgreementPlatformNotFoundError, ap.AgreementPlatformError)
    assert issubclass(ap.AgreementPlatformTransientError, ap.AgreementPlatformError)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_agreement_platform_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.integrations.agreement_platform'`.

- [ ] **Step 4: Implement the boundary**

Create `apps/integrations/agreement_platform.py`:

```python
"""Agreement-platform boundary — stub + DocuSeal dispatch.

Mirrors apps/integrations/ocr.py. The boundary owns the exception
taxonomy; the real provider (apps/integrations/docuseal.py) imports and
raises these. Mode is selected by settings.AGREEMENT_PROVIDER_MODE
("stub" default, "docuseal" in production).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Normalized result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubmissionResult:
    external_id: str
    external_url: str
    external_state: str  # "pending" | "completed" | "archived"


# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public API (mode dispatch)
# ---------------------------------------------------------------------------

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
```

Note: stub `verify_webhook_signature` returns `True` so webhook tests in stub mode exercise the routing logic; signature-rejection tests (Task 8) run against the docuseal verifier directly (Task 3).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_agreement_platform_adapter.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/integrations/agreement_platform.py fk_cesis_mms/settings.py tests/integrations/test_agreement_platform_adapter.py
git commit -m "feat(integrations): agreement-platform boundary + stub provider (P5 Slice D)"
```

---

## Task 3: DocuSeal real provider — HTTP + HMAC + field builders

**Files:**
- Create: `apps/integrations/docuseal.py`
- Modify: `fk_cesis_mms/settings.py` (after the `AGREEMENT_PROVIDER_MODE` line from Task 2)
- Test: `tests/integrations/test_docuseal_provider.py` (new)

Assumed DocuSeal HTTP contract (adjust endpoint paths to the live instance during real-mode smoke, but the request shape below is what the tests pin):
- Create: `POST {DOCUSEAL_API_URL}/submissions` with header `X-Auth-Token: {DOCUSEAL_API_KEY}`, JSON body `{"template_id": <int>, "submitters": [submitter], "fields": [{"name": k, "default_value": v}, ...]}`. Success `201` → `{"id": <id>, "submitters": [{"slug": "..."}], "status": "pending"}`.
- Sync: `GET {DOCUSEAL_API_URL}/submissions/{external_id}` → `{"id": ..., "status": "completed", "audit_log_url": "..."}`.
- Archive: `DELETE {DOCUSEAL_API_URL}/submissions/{external_id}` → `204`.
- `external_url` is built as `{DOCUSEAL_API_URL_PUBLIC or DOCUSEAL_API_URL}/s/{slug}` — for the plan we store the response's submission URL when present, else build from the first submitter slug.

Status normalization: DocuSeal `"completed"` → `"completed"`; `"archived"`/`"expired"` → `"archived"`; anything else → `"pending"`.

- [ ] **Step 1: Add the DocuSeal settings**

In `fk_cesis_mms/settings.py`, after the `AGREEMENT_PROVIDER_MODE` line:

```python
DOCUSEAL_API_URL = os.environ.get("DOCUSEAL_API_URL", "")
DOCUSEAL_API_KEY = os.environ.get("DOCUSEAL_API_KEY", "")
DOCUSEAL_TEMPLATE_ID = os.environ.get("DOCUSEAL_TEMPLATE_ID", "")
DOCUSEAL_WEBHOOK_SECRET = os.environ.get("DOCUSEAL_WEBHOOK_SECRET", "")
```

- [ ] **Step 2: Write the failing test**

Create `tests/integrations/test_docuseal_provider.py`:

```python
"""Real-mode DocuSeal provider tests with mocked HTTP."""

from __future__ import annotations

import hashlib
import hmac

import pytest
import responses

from apps.integrations import agreement_platform as ap
from apps.integrations import docuseal


pytestmark = pytest.mark.django_db


@pytest.fixture
def docuseal_settings(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = "https://sign.example/api"
    settings.DOCUSEAL_API_KEY = "secret-key"
    settings.DOCUSEAL_TEMPLATE_ID = "7"
    settings.DOCUSEAL_WEBHOOK_SECRET = "whsecret"
    return settings


class _FakeGuardian:
    full_name = "Anna Bērziņa"
    personal_id = "111111-11111"
    email = "anna@example.test"
    address = "Rīgas iela 1"


class _FakeMember:
    id = 5
    full_name = "Jānis Bērziņš"
    personal_id = "151210-22222"

    class _D:
        @staticmethod
        def isoformat():
            return "2015-12-10"

    birth_date = _D()
    guardian = _FakeGuardian()


class _FakeAgreement:
    id = 42
    member = _FakeMember()

    class _G:
        @staticmethod
        def date():
            class _DD:
                @staticmethod
                def isoformat():
                    return "2026-05-29"

            return _DD()

    generated_at = _G()


@responses.activate
def test_create_submission_request_shape_and_normalization(docuseal_settings):
    responses.add(
        responses.POST,
        "https://sign.example/api/submissions",
        json={"id": 1001, "submitters": [{"slug": "abc"}], "status": "pending"},
        status=201,
    )
    result = docuseal.create_submission(_FakeAgreement())
    assert isinstance(result, ap.SubmissionResult)
    assert result.external_id == "1001"
    assert result.external_state == "pending"
    assert "abc" in result.external_url

    sent = responses.calls[0].request
    assert sent.headers["X-Auth-Token"] == "secret-key"
    import json

    body = json.loads(sent.body)
    assert body["template_id"] == 7
    assert body["submitters"][0]["email"] == "anna@example.test"
    field_names = {f["name"] for f in body["fields"]}
    assert {"child_name", "guardian_name", "agreement_date"} <= field_names
    assert "training_group" not in field_names


@responses.activate
def test_create_submission_auth_error(docuseal_settings):
    responses.add(
        responses.POST,
        "https://sign.example/api/submissions",
        json={"error": "unauthorized"},
        status=401,
    )
    with pytest.raises(ap.AgreementPlatformAuthError):
        docuseal.create_submission(_FakeAgreement())


@responses.activate
def test_create_submission_transient_on_5xx(docuseal_settings):
    responses.add(
        responses.POST,
        "https://sign.example/api/submissions",
        json={"error": "boom"},
        status=502,
    )
    with pytest.raises(ap.AgreementPlatformTransientError):
        docuseal.create_submission(_FakeAgreement())


def test_create_submission_config_error_when_unconfigured(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = ""
    settings.DOCUSEAL_API_KEY = ""
    with pytest.raises(ap.AgreementPlatformConfigError):
        docuseal.create_submission(_FakeAgreement())


@responses.activate
def test_sync_submission_not_found(docuseal_settings):
    responses.add(
        responses.GET,
        "https://sign.example/api/submissions/ds-9",
        json={"error": "not found"},
        status=404,
    )
    with pytest.raises(ap.AgreementPlatformNotFoundError):
        docuseal.sync_submission("ds-9")


@responses.activate
def test_sync_submission_normalizes_completed(docuseal_settings):
    responses.add(
        responses.GET,
        "https://sign.example/api/submissions/ds-9",
        json={"id": "ds-9", "status": "completed"},
        status=200,
    )
    result = docuseal.sync_submission("ds-9")
    assert result.external_state == "completed"


def test_verify_webhook_signature_accepts_valid(docuseal_settings):
    body = b'{"event_type":"submission.completed"}'
    sig = hmac.new(b"whsecret", body, hashlib.sha256).hexdigest()
    assert docuseal.verify_webhook_signature(body, sig) is True


def test_verify_webhook_signature_rejects_tampered(docuseal_settings):
    body = b'{"event_type":"submission.completed"}'
    assert docuseal.verify_webhook_signature(body, "deadbeef") is False


def test_verify_webhook_signature_rejects_empty_header(docuseal_settings):
    assert docuseal.verify_webhook_signature(b"x", "") is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_docuseal_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.integrations.docuseal'`. (If `responses` is missing, install it first: `uv add --dev responses`.)

- [ ] **Step 4: Implement the provider**

Create `apps/integrations/docuseal.py`:

```python
"""DocuSeal self-hosted provider — HTTP transport, HMAC verify, field maps.

Raises the boundary exception taxonomy from
apps.integrations.agreement_platform directly (no second mapping layer).
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import requests
from django.conf import settings

from apps.integrations.agreement_platform import (
    AgreementPlatformAuthError,
    AgreementPlatformConfigError,
    AgreementPlatformNotFoundError,
    AgreementPlatformTransientError,
    SubmissionResult,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _require_config() -> tuple[str, str, int]:
    api_url = getattr(settings, "DOCUSEAL_API_URL", "")
    api_key = getattr(settings, "DOCUSEAL_API_KEY", "")
    template_id = getattr(settings, "DOCUSEAL_TEMPLATE_ID", "")
    if not api_url or not api_key:
        raise AgreementPlatformConfigError("DocuSeal API URL/key not configured")
    try:
        template_int = int(template_id)
    except (TypeError, ValueError) as exc:
        raise AgreementPlatformConfigError(
            f"DOCUSEAL_TEMPLATE_ID is not an integer: {template_id!r}"
        ) from exc
    return api_url.rstrip("/"), api_key, template_int


# ---------------------------------------------------------------------------
# Field payload builders
# ---------------------------------------------------------------------------

def _build_submitter(agreement) -> dict:
    guardian = agreement.member.guardian
    return {
        "email": guardian.email,
        "name": guardian.full_name,
        "role": "Vecāks",
    }


def _build_field_payload(agreement) -> dict:
    member = agreement.member
    guardian = member.guardian
    return {
        "child_name": member.full_name,
        "child_personal_id": member.personal_id,
        "child_birth_date": (
            member.birth_date.isoformat() if member.birth_date else ""
        ),
        "guardian_name": guardian.full_name,
        "guardian_personal_id": guardian.personal_id,
        "guardian_address": guardian.address,
        "agreement_date": agreement.generated_at.date().isoformat(),
    }


def _normalize_state(raw: str) -> str:
    if raw == "completed":
        return "completed"
    if raw in {"archived", "expired"}:
        return "archived"
    return "pending"


def _submission_url(api_url: str, payload: dict) -> str:
    submitters = payload.get("submitters") or []
    if submitters and submitters[0].get("slug"):
        return f"{api_url}/s/{submitters[0]['slug']}"
    return payload.get("url", "")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    headers = {"X-Auth-Token": api_key, **kwargs.pop("headers", {})}
    try:
        resp = requests.request(
            method, url, headers=headers, timeout=_TIMEOUT, **kwargs
        )
    except requests.Timeout as exc:
        raise AgreementPlatformTransientError(f"timeout: {exc}") from exc
    except requests.RequestException as exc:
        raise AgreementPlatformTransientError(f"connection error: {exc}") from exc

    status = resp.status_code
    if status in (401, 403):
        raise AgreementPlatformAuthError(f"auth failed: {status}")
    if status == 404:
        raise AgreementPlatformNotFoundError(f"not found: {url}")
    if status >= 500:
        raise AgreementPlatformTransientError(f"server error: {status}")
    if status >= 400:
        # Other 4xx are permanent config/request problems.
        raise AgreementPlatformConfigError(f"request rejected: {status} {resp.text}")
    return resp


# ---------------------------------------------------------------------------
# Public provider API
# ---------------------------------------------------------------------------

def create_submission(agreement) -> SubmissionResult:
    api_url, api_key, template_int = _require_config()
    body = {
        "template_id": template_int,
        "submitters": [_build_submitter(agreement)],
        "fields": [
            {"name": k, "default_value": v}
            for k, v in _build_field_payload(agreement).items()
        ],
    }
    resp = _request("POST", f"{api_url}/submissions", api_key, json=body)
    payload = resp.json()
    return SubmissionResult(
        external_id=str(payload["id"]),
        external_url=_submission_url(api_url, payload),
        external_state=_normalize_state(payload.get("status", "pending")),
    )


def sync_submission(external_id: str) -> SubmissionResult:
    api_url, api_key, _ = _require_config()
    resp = _request("GET", f"{api_url}/submissions/{external_id}", api_key)
    payload = resp.json()
    return SubmissionResult(
        external_id=str(payload.get("id", external_id)),
        external_url=_submission_url(api_url, payload),
        external_state=_normalize_state(payload.get("status", "pending")),
    )


def archive_submission(external_id: str) -> None:
    api_url, api_key, _ = _require_config()
    _request("DELETE", f"{api_url}/submissions/{external_id}", api_key)


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    secret = getattr(settings, "DOCUSEAL_WEBHOOK_SECRET", "")
    if not secret or not signature_header:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_docuseal_provider.py -v`
Expected: PASS (9 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/integrations/docuseal.py fk_cesis_mms/settings.py tests/integrations/test_docuseal_provider.py
git commit -m "feat(integrations): DocuSeal HTTP provider + HMAC verify (P5 Slice D)"
```

---

## Task 4: Latvian error-message map

**Files:**
- Create: `apps/agreements/messages.py`
- Test: `tests/agreements/test_agreement_messages.py` (new)

Error codes stored in `external_error_code`: `"auth_failed"`, `"misconfigured"`, `"not_found"`, `"provider_error"`, `"unavailable"`.

- [ ] **Step 1: Write the failing test**

Create `tests/agreements/test_agreement_messages.py`:

```python
from apps.agreements.messages import get_agreement_error_message


def test_known_code_returns_latvian():
    assert get_agreement_error_message("auth_failed") == (
        "DocuSeal autentifikācija neizdevās. Pārbaudiet API atslēgu."
    )


def test_unknown_code_returns_generic_latvian():
    msg = get_agreement_error_message("something_unexpected")
    assert msg == "Radās kļūda saziņā ar DocuSeal. Mēģiniet vēlreiz."


def test_empty_code_returns_generic():
    assert get_agreement_error_message("") == (
        "Radās kļūda saziņā ar DocuSeal. Mēģiniet vēlreiz."
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_agreement_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.agreements.messages'`.

- [ ] **Step 3: Implement the message map**

Create `apps/agreements/messages.py`:

```python
"""Latvian copy for DocuSeal integration error codes (P5 Slice D)."""

from __future__ import annotations

_GENERIC = "Radās kļūda saziņā ar DocuSeal. Mēģiniet vēlreiz."

_MESSAGES: dict[str, str] = {
    "auth_failed": "DocuSeal autentifikācija neizdevās. Pārbaudiet API atslēgu.",
    "misconfigured": "DocuSeal konfigurācija nav pilnīga. Sazinieties ar administratoru.",
    "not_found": "DocuSeal dokuments nav atrasts.",
    "provider_error": _GENERIC,
    "unavailable": "DocuSeal pašlaik nav pieejams. Mēģiniet vēlāk.",
}


def get_agreement_error_message(error_code: str) -> str:
    """Return Latvian copy for a stored external_error_code, generic fallback."""
    return _MESSAGES.get(error_code, _GENERIC)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_agreement_messages.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/agreements/messages.py tests/agreements/test_agreement_messages.py
git commit -m "feat(agreements): Latvian DocuSeal error-message map (P5 Slice D)"
```

---

## Task 5: django-q2 jobs + enqueue helpers

**Files:**
- Modify: `apps/integrations/tasks.py` (append new jobs + helpers)
- Test: `tests/integrations/test_agreement_tasks.py` (new)

Error-code mapping used by the create/sync jobs when they catch a boundary exception:

| Exception | stored `external_error_code` | retry? |
|---|---|---|
| `AgreementPlatformTransientError` | `"unavailable"` | yes (re-raise) |
| `AgreementPlatformAuthError` | `"auth_failed"` | no |
| `AgreementPlatformConfigError` | `"misconfigured"` | no |
| `AgreementPlatformNotFoundError` | `"not_found"` | no |

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/test_agreement_tasks.py`:

```python
"""Jobs for the agreement-platform pipeline (stub mode + classified failures)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.integrations import agreement_platform as ap
from apps.integrations import tasks


pytestmark = pytest.mark.django_db


@pytest.fixture
def electronic_agreement(agreement_member):
    return Agreement.objects.create(
        member=agreement_member,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        state=Agreement.State.SENT,
        generated_at=timezone.now(),
    )


def test_create_job_stores_external_fields(settings, electronic_agreement):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    tasks.create_agreement_submission(electronic_agreement.id)
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.external_provider == "docuseal"
    assert electronic_agreement.external_id == f"stub-{electronic_agreement.id}"
    assert electronic_agreement.external_url.endswith(str(electronic_agreement.id))
    assert electronic_agreement.external_state == "pending"
    assert electronic_agreement.external_error_code == ""


def test_create_job_missing_agreement_is_noop(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    tasks.create_agreement_submission(999999)  # no raise


def test_create_job_auth_failure_marks_failed_no_retry(
    settings, electronic_agreement, mocker
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    mocker.patch(
        "apps.integrations.tasks.agreement_platform.create_submission",
        side_effect=ap.AgreementPlatformAuthError("bad key"),
    )
    tasks.create_agreement_submission(electronic_agreement.id)  # no raise
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.external_state == "failed"
    assert electronic_agreement.external_error_code == "auth_failed"


def test_create_job_transient_failure_marks_failed_and_raises(
    settings, electronic_agreement, mocker
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    mocker.patch(
        "apps.integrations.tasks.agreement_platform.create_submission",
        side_effect=ap.AgreementPlatformTransientError("5xx"),
    )
    with pytest.raises(tasks.RetryableAgreementError):
        tasks.create_agreement_submission(electronic_agreement.id)
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.external_state == "failed"
    assert electronic_agreement.external_error_code == "unavailable"


def test_sync_job_completed_drives_signed(settings, electronic_agreement):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    electronic_agreement.external_id = f"stub-{electronic_agreement.id}"
    electronic_agreement.save(update_fields=["external_id"])
    tasks.sync_agreement_submission(electronic_agreement.id)
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.state == Agreement.State.SIGNED


def test_archive_job_calls_provider(settings, mocker):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    spy = mocker.patch(
        "apps.integrations.tasks.agreement_platform.archive_submission"
    )
    tasks.archive_agreement_submission("stub-1")
    spy.assert_called_once_with("stub-1")


def test_enqueue_helpers_call_async_task(mocker):
    spy = mocker.patch("apps.integrations.tasks.async_task")
    tasks.enqueue_create_agreement_submission(1)
    tasks.enqueue_sync_agreement_submission(2)
    tasks.enqueue_archive_agreement_submission("x")
    assert spy.call_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_agreement_tasks.py -v`
Expected: FAIL — `AttributeError: module 'apps.integrations.tasks' has no attribute 'create_agreement_submission'`.

- [ ] **Step 3: Append the jobs to `apps/integrations/tasks.py`**

Add these imports near the top of `apps/integrations/tasks.py` (with the existing imports):

```python
from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_signed
from apps.integrations import agreement_platform
```

Then append at the end of the file:

```python
# ---------------------------------------------------------------------------
# Agreement-platform (DocuSeal) pipeline — P5 Slice D
# ---------------------------------------------------------------------------


class RetryableAgreementError(Exception):
    """Raised for transient agreement-platform failures so django-q2 retries."""


_AGREEMENT_ERROR_CODES: dict[type[Exception], tuple[str, bool]] = {
    agreement_platform.AgreementPlatformTransientError: ("unavailable", True),
    agreement_platform.AgreementPlatformAuthError: ("auth_failed", False),
    agreement_platform.AgreementPlatformConfigError: ("misconfigured", False),
    agreement_platform.AgreementPlatformNotFoundError: ("not_found", False),
}


def _classify_agreement_error(exc: Exception) -> tuple[str, bool]:
    for exc_type, mapping in _AGREEMENT_ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return mapping
    return ("provider_error", False)


def _mark_agreement_failed(agreement: Agreement, code: str) -> None:
    agreement.external_state = "failed"
    agreement.external_error_code = code
    agreement.save(update_fields=["external_state", "external_error_code", "updated_at"])


def enqueue_create_agreement_submission(agreement_id: int) -> None:
    try:
        async_task(
            "apps.integrations.tasks.create_agreement_submission", agreement_id
        )
    except RetryableAgreementError:
        return


def enqueue_sync_agreement_submission(agreement_id: int) -> None:
    try:
        async_task(
            "apps.integrations.tasks.sync_agreement_submission", agreement_id
        )
    except RetryableAgreementError:
        return


def enqueue_archive_agreement_submission(external_id: str) -> None:
    async_task(
        "apps.integrations.tasks.archive_agreement_submission", external_id
    )


def create_agreement_submission(agreement_id: int) -> None:
    try:
        agreement = Agreement.objects.select_related("member__guardian").get(
            pk=agreement_id
        )
    except Agreement.DoesNotExist:
        return
    try:
        result = agreement_platform.create_submission(agreement)
    except Exception as exc:
        code, retry = _classify_agreement_error(exc)
        _mark_agreement_failed(agreement, code)
        if retry:
            raise RetryableAgreementError(code) from exc
        return
    agreement.external_provider = "docuseal"
    agreement.external_id = result.external_id
    agreement.external_url = result.external_url
    agreement.external_state = result.external_state
    agreement.external_error_code = ""
    agreement.save(
        update_fields=[
            "external_provider",
            "external_id",
            "external_url",
            "external_state",
            "external_error_code",
            "updated_at",
        ]
    )


def sync_agreement_submission(agreement_id: int) -> None:
    try:
        agreement = Agreement.objects.get(pk=agreement_id)
    except Agreement.DoesNotExist:
        return
    if not agreement.external_id:
        return
    try:
        result = agreement_platform.sync_submission(agreement.external_id)
    except Exception as exc:
        code, retry = _classify_agreement_error(exc)
        _mark_agreement_failed(agreement, code)
        if retry:
            raise RetryableAgreementError(code) from exc
        return
    agreement.external_state = result.external_state
    agreement.external_error_code = ""
    agreement.save(
        update_fields=["external_state", "external_error_code", "updated_at"]
    )
    if result.external_state == "completed":
        mark_agreement_signed(agreement, actor=None)


def archive_agreement_submission(external_id: str) -> None:
    try:
        agreement_platform.archive_submission(external_id)
    except Exception:
        logger.warning("DocuSeal archive failed for %s", external_id, exc_info=True)
```

If `logger` is not already defined at module top, add `import logging` and `logger = logging.getLogger(__name__)` near the top of the file.

Note on `mark_agreement_signed` being idempotent for sync: it raises `ValueError` if state is already `signed`/`void`. Guard the call:

```python
    if result.external_state == "completed" and agreement.state in (
        Agreement.State.GENERATED,
        Agreement.State.SENT,
    ):
        mark_agreement_signed(agreement, actor=None)
```

Use that guarded form in the implementation.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integrations/test_agreement_tasks.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/integrations/tasks.py tests/integrations/test_agreement_tasks.py
git commit -m "feat(integrations): DocuSeal create/sync/archive jobs (P5 Slice D)"
```

---

## Task 6: Email suppression gate in services

**Files:**
- Modify: `apps/agreements/services.py` (add `_should_send_email`, gate `_render_and_send_agreement_email`)
- Test: `tests/agreements/test_electronic_email_suppression.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/agreements/test_electronic_email_suppression.py`:

```python
"""Electronic path suppresses sent/signed emails; void always sends; paper
sends on all transitions (P5 Slice D)."""

from __future__ import annotations

import pytest
from django.core import mail
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import (
    mark_agreement_signed,
    void_agreement,
)


pytestmark = pytest.mark.django_db


def _agreement(member, path, state=Agreement.State.GENERATED):
    return Agreement.objects.create(
        member=member,
        signing_path=path,
        state=state,
        generated_at=timezone.now(),
    )


def test_electronic_signed_suppresses_email(agreement_member, actor):
    a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mail.outbox.clear()
    mark_agreement_signed(a, actor)
    assert len(mail.outbox) == 0


def test_electronic_void_still_emails(agreement_member, actor):
    a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mail.outbox.clear()
    void_agreement(a, actor, "duplicate")
    assert len(mail.outbox) == 1


def test_paper_signed_emails(agreement_member, actor):
    a = _agreement(agreement_member, Agreement.SigningPath.PAPER)
    mail.outbox.clear()
    mark_agreement_signed(a, actor)
    assert len(mail.outbox) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_electronic_email_suppression.py -v`
Expected: FAIL — `test_electronic_signed_suppresses_email` fails (1 email sent, expected 0).

- [ ] **Step 3: Add the suppression gate**

In `apps/agreements/services.py`, add the helper above `_render_and_send_agreement_email`:

```python
def _should_send_email(agreement: Agreement, template_name: str) -> bool:
    """Electronic path suppresses `sent`/`signed` (DocuSeal notifies the
    signer). `void` always sends; paper sends on all transitions."""
    if (
        agreement.signing_path == Agreement.SigningPath.ELECTRONIC
        and template_name in {"sent", "signed"}
    ):
        return False
    return True
```

Then, at the top of `_render_and_send_agreement_email`, add the early return:

```python
def _render_and_send_agreement_email(
    agreement: Agreement,
    template_name: str,
) -> None:
    """Render an agreement plain-text email and send to the guardian."""
    if not _should_send_email(agreement, template_name):
        return
    member = agreement.member
    # ... rest unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_electronic_email_suppression.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the existing agreements suite to confirm no regression**

Run: `uv run pytest tests/agreements/ -v`
Expected: PASS (existing Slice C email tests use the paper default path, unaffected — but verify; if any existing test created an electronic agreement and asserted a `sent`/`signed` email, update that test to use paper or to assert suppression).

- [ ] **Step 6: Commit**

```bash
git add apps/agreements/services.py tests/agreements/test_electronic_email_suppression.py
git commit -m "feat(agreements): suppress sent/signed email on electronic path (P5 Slice D)"
```

---

## Task 7: Service wiring — electronic `mark_agreement_sent` + void archive

**Files:**
- Modify: `apps/agreements/services.py` (`mark_agreement_sent`, `void_agreement`)
- Test: `tests/agreements/test_electronic_flow_integration.py` (new)

`mark_agreement_sent` electronic branch: if guardian email empty → fall back to paper via `set_signing_path`, do NOT enqueue DocuSeal. Else enqueue create. `void_agreement` electronic branch with `external_id` → enqueue archive.

To avoid a circular import (`tasks.py` imports from `services.py`), import the enqueue helpers **lazily inside the functions**, not at module top.

- [ ] **Step 1: Write the failing test**

Create `tests/agreements/test_electronic_flow_integration.py`:

```python
"""Electronic mark-sent enqueues DocuSeal create; paper does not; empty
guardian email falls back to paper; void archives (P5 Slice D)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_sent, void_agreement


pytestmark = pytest.mark.django_db


def _agreement(member, path):
    return Agreement.objects.create(
        member=member,
        signing_path=path,
        state=Agreement.State.GENERATED,
        generated_at=timezone.now(),
    )


def test_electronic_mark_sent_enqueues_create(agreement_member, actor, mocker):
    spy = mocker.patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    )
    a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_sent(a, actor)
    a.refresh_from_db()
    assert a.state == Agreement.State.SENT
    spy.assert_called_once_with(a.id)


def test_paper_mark_sent_does_not_enqueue(agreement_member, actor, mocker):
    spy = mocker.patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    )
    a = _agreement(agreement_member, Agreement.SigningPath.PAPER)
    mark_agreement_sent(a, actor)
    spy.assert_not_called()


def test_electronic_no_email_falls_back_to_paper(
    agreement_member, actor, mocker
):
    spy = mocker.patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    )
    agreement_member.guardian.email = ""
    agreement_member.guardian.save(update_fields=["email"])
    a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_sent(a, actor)
    a.refresh_from_db()
    assert a.signing_path == Agreement.SigningPath.PAPER
    spy.assert_not_called()


def test_electronic_void_enqueues_archive(agreement_member, actor, mocker):
    spy = mocker.patch(
        "apps.integrations.tasks.enqueue_archive_agreement_submission"
    )
    a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.external_id = "ds-1"
    a.state = Agreement.State.SENT
    a.save(update_fields=["external_id", "state"])
    void_agreement(a, actor, "duplicate")
    spy.assert_called_once_with("ds-1")


def test_paper_void_does_not_enqueue_archive(agreement_member, actor, mocker):
    spy = mocker.patch(
        "apps.integrations.tasks.enqueue_archive_agreement_submission"
    )
    a = _agreement(agreement_member, Agreement.SigningPath.PAPER)
    a.state = Agreement.State.SENT
    a.save(update_fields=["state"])
    void_agreement(a, actor, "duplicate")
    spy.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_electronic_flow_integration.py -v`
Expected: FAIL — `test_electronic_mark_sent_enqueues_create` fails (enqueue not called).

- [ ] **Step 3: Wire `mark_agreement_sent`**

Replace the body of `mark_agreement_sent` in `apps/agreements/services.py` with:

```python
def mark_agreement_sent(
    agreement: Agreement,
    actor,  # AUTH_USER_MODEL — plumbed for P7 audit hook
) -> Agreement:
    """generated → sent. Paper path: Latvian email to guardian. Electronic
    path: optimistic sent, suppress email, enqueue DocuSeal create. When
    electronic but guardian has no email, fall back to paper first."""
    if agreement.state != Agreement.State.GENERATED:
        raise ValueError(f"cannot mark sent from state {agreement.state}")

    # Electronic requires a guardian email to send the signing request.
    # Without one, degrade to the paper (staff-managed) path before sending.
    if (
        agreement.signing_path == Agreement.SigningPath.ELECTRONIC
        and not agreement.member.guardian.email
    ):
        set_signing_path(agreement, Agreement.SigningPath.PAPER, actor)

    agreement.state = Agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])
    _render_and_send_agreement_email(agreement, template_name="sent")

    if agreement.signing_path == Agreement.SigningPath.ELECTRONIC:
        from apps.integrations.tasks import enqueue_create_agreement_submission

        enqueue_create_agreement_submission(agreement.id)
    return agreement
```

- [ ] **Step 4: Wire `void_agreement`**

Replace the body of `void_agreement` with:

```python
def void_agreement(
    agreement: Agreement,
    actor,  # noqa: ARG001
    reason: str,
) -> Agreement:
    """Any non-void state → void. Keeps is_current=True. Sends a Latvian
    plain-text notification to the guardian (both paths). For an electronic
    agreement with a live DocuSeal submission, also enqueues an archive job.
    Idempotent on void → void."""
    if agreement.state == Agreement.State.VOID:
        return agreement
    agreement.state = Agreement.State.VOID
    agreement.voided_at = timezone.now()
    agreement.void_reason = reason
    agreement.save(update_fields=["state", "voided_at", "void_reason"])
    _render_and_send_agreement_email(agreement, template_name="void")

    if (
        agreement.signing_path == Agreement.SigningPath.ELECTRONIC
        and agreement.external_id
    ):
        from apps.integrations.tasks import enqueue_archive_agreement_submission

        enqueue_archive_agreement_submission(agreement.external_id)
    return agreement
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_electronic_flow_integration.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the full agreements + integrations suites**

Run: `uv run pytest tests/agreements/ tests/integrations/ -v`
Expected: PASS. (Watch for any existing `mark_agreement_sent` test that assumed an electronic email — update to paper or suppression assertion if found.)

- [ ] **Step 7: Commit**

```bash
git add apps/agreements/services.py tests/agreements/test_electronic_flow_integration.py
git commit -m "feat(agreements): wire electronic mark-sent + void to DocuSeal jobs (P5 Slice D)"
```

---

## Task 8: Webhook handler + URL mount

**Files:**
- Create: `apps/agreements/webhooks.py`
- Create: `apps/agreements/urls.py`
- Modify: `fk_cesis_mms/urls.py`
- Test: `tests/agreements/test_docuseal_webhook.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/agreements/test_docuseal_webhook.py`:

```python
"""DocuSeal webhook: HMAC-verified submission.completed drives signed."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement


pytestmark = pytest.mark.django_db


@pytest.fixture
def webhook_settings(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_WEBHOOK_SECRET = "whsecret"
    return settings


@pytest.fixture
def sent_electronic(agreement_member):
    return Agreement.objects.create(
        member=agreement_member,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        state=Agreement.State.SENT,
        external_id="ds-100",
        generated_at=timezone.now(),
    )


def _sign(body: bytes, secret: str = "whsecret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client, payload: dict, signature: str | None):
    body = json.dumps(payload).encode()
    headers = {}
    if signature is not None:
        headers["HTTP_X_DOCUSEAL_SIGNATURE"] = signature
    return client.post(
        reverse("agreements:docuseal-webhook"),
        data=body,
        content_type="application/json",
        **headers,
    )


def test_valid_completed_drives_signed(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SIGNED


def test_bad_signature_rejected(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    resp = _post(client, payload, "deadbeef")
    assert resp.status_code == 403
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SENT


def test_wrong_event_is_noop_200(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.viewed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SENT


def test_unknown_external_id_is_noop_200(client, webhook_settings):
    payload = {"event_type": "submission.completed", "data": {"id": "ghost"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200


def test_already_signed_is_idempotent_200(client, webhook_settings, sent_electronic):
    sent_electronic.state = Agreement.State.SIGNED
    sent_electronic.signed_at = timezone.now()
    sent_electronic.save(update_fields=["state", "signed_at"])
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200


def test_get_not_allowed(client, webhook_settings):
    resp = client.get(reverse("agreements:docuseal-webhook"))
    assert resp.status_code == 405
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_docuseal_webhook.py -v`
Expected: FAIL — `NoReverseMatch: 'agreements' is not a registered namespace`.

- [ ] **Step 3: Implement the webhook handler**

Create `apps/agreements/webhooks.py`:

```python
"""DocuSeal webhook endpoint — HMAC-verified submission.completed → signed."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_signed
from apps.integrations import agreement_platform

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def docuseal_webhook(request: HttpRequest) -> HttpResponse:
    raw = request.body
    signature = request.headers.get("X-Docuseal-Signature", "")
    if not agreement_platform.verify_webhook_signature(raw, signature):
        return HttpResponseForbidden("invalid signature")

    try:
        payload = json.loads(raw.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=200)  # ack malformed; don't trigger retries

    if payload.get("event_type") != "submission.completed":
        return HttpResponse(status=200)

    external_id = str((payload.get("data") or {}).get("id", ""))
    if not external_id:
        return HttpResponse(status=200)

    agreement = Agreement.objects.filter(external_id=external_id).first()
    if agreement is None:
        logger.info("DocuSeal webhook for unknown submission %s", external_id)
        return HttpResponse(status=200)

    if agreement.state in (Agreement.State.GENERATED, Agreement.State.SENT):
        try:
            mark_agreement_signed(agreement, actor=None)
        except ValueError:
            logger.warning(
                "DocuSeal webhook could not sign agreement %s", agreement.id,
                exc_info=True,
            )
    return HttpResponse(status=200)
```

- [ ] **Step 4: Create `apps/agreements/urls.py`**

```python
"""URL routes for the agreements app."""

from django.urls import path

from apps.agreements import webhooks

app_name = "agreements"

urlpatterns = [
    path(
        "integrations/docuseal/webhook/",
        webhooks.docuseal_webhook,
        name="docuseal-webhook",
    ),
]
```

- [ ] **Step 5: Mount in `fk_cesis_mms/urls.py`**

Add the include to `urlpatterns` (before the catch-all `path("", include("apps.registrations.urls"))` so the explicit prefix matches first):

```python
    path("healthz", healthz, name="healthz"),
    path("admin/documents/", include("apps.documents.urls")),
    path("", include("apps.agreements.urls")),
    path("", include("apps.registrations.urls")),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_docuseal_webhook.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/agreements/webhooks.py apps/agreements/urls.py fk_cesis_mms/urls.py tests/agreements/test_docuseal_webhook.py
git commit -m "feat(agreements): HMAC-verified DocuSeal webhook → signed (P5 Slice D)"
```

---

## Task 9: Līgums module UI — view actions + template

**Files:**
- Modify: `apps/registrations/views.py` (`admin_review_detail` — add 2 POST actions; import enqueue helpers + message map)
- Modify: `templates/registrations/admin/_agreement_module.html`
- Test: `tests/registrations/test_agreement_module_docuseal.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/registrations/test_agreement_module_docuseal.py`:

```python
"""Līgums module DocuSeal UI: error surface, retry, sync, external link."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import get_current_agreement
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


def _approved_agreement(submitted_application, reviewer, **fields):
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    for k, v in fields.items():
        setattr(agreement, k, v)
    if fields:
        agreement.save(update_fields=list(fields))
    return agreement


def test_failed_state_renders_latvian_error_and_retry(
    client, submitted_application, reviewer
):
    _approved_agreement(
        submitted_application,
        reviewer,
        external_state="failed",
        external_error_code="auth_failed",
    )
    client.force_login(reviewer)
    resp = client.get(
        reverse(
            "registrations:admin-review-detail",
            args=[submitted_application.id],
        )
    )
    html = resp.content.decode()
    assert "DocuSeal autentifikācija neizdevās" in html
    assert 'value="retry_docuseal"' in html


def test_external_url_renders_open_link(
    client, submitted_application, reviewer
):
    _approved_agreement(
        submitted_application,
        reviewer,
        external_id="ds-1",
        external_url="https://sign.example/s/abc",
    )
    client.force_login(reviewer)
    resp = client.get(
        reverse(
            "registrations:admin-review-detail",
            args=[submitted_application.id],
        )
    )
    html = resp.content.decode()
    assert "https://sign.example/s/abc" in html
    assert 'value="sync_docuseal"' in html


def test_retry_action_re_enqueues_create(
    client, submitted_application, reviewer, mocker
):
    agreement = _approved_agreement(
        submitted_application,
        reviewer,
        external_state="failed",
        external_error_code="unavailable",
    )
    spy = mocker.patch(
        "apps.registrations.views.enqueue_create_agreement_submission"
    )
    client.force_login(reviewer)
    client.post(
        reverse(
            "registrations:admin-review-detail",
            args=[submitted_application.id],
        ),
        {"action": "retry_docuseal"},
    )
    spy.assert_called_once_with(agreement.id)


def test_sync_action_enqueues_sync(
    client, submitted_application, reviewer, mocker
):
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    spy = mocker.patch(
        "apps.registrations.views.enqueue_sync_agreement_submission"
    )
    client.force_login(reviewer)
    client.post(
        reverse(
            "registrations:admin-review-detail",
            args=[submitted_application.id],
        ),
        {"action": "sync_docuseal"},
    )
    spy.assert_called_once_with(agreement.id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_agreement_module_docuseal.py -v`
Expected: FAIL — error copy / `retry_docuseal` not present; spies not called.

- [ ] **Step 3: Add imports + context to `apps/registrations/views.py`**

Add to the imports near the existing agreement imports (~line 22):

```python
from apps.agreements.messages import get_agreement_error_message
from apps.integrations.tasks import (
    enqueue_create_agreement_submission,
    enqueue_sync_agreement_submission,
)
```

In `admin_review_detail`, after `agreement = get_current_agreement(...)` and the `context = {...}` dict is built, add the error message to context:

```python
    agreement_error_message = None
    if agreement is not None and agreement.external_state == "failed":
        agreement_error_message = get_agreement_error_message(
            agreement.external_error_code
        )
    context["agreement_error_message"] = agreement_error_message
```

- [ ] **Step 4: Add the two POST branches**

In the POST handling block of `admin_review_detail`, after the `regenerate_agreement` branch, add:

```python
        elif action == "retry_docuseal":
            if agreement is None:
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": "Līgums nav sagatavots."},
                    status=400,
                )
            enqueue_create_agreement_submission(agreement.id)
            return redirect(
                "registrations:admin-review-detail",
                application_id=application.id,
            )

        elif action == "sync_docuseal":
            if agreement is None:
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": "Līgums nav sagatavots."},
                    status=400,
                )
            enqueue_sync_agreement_submission(agreement.id)
            return redirect(
                "registrations:admin-review-detail",
                application_id=application.id,
            )
```

- [ ] **Step 5: Extend the template**

In `templates/registrations/admin/_agreement_module.html`, after the `<p>Stāvoklis: ...</p>` line, add the DocuSeal status block:

```django
  {% if agreement_error_message %}
  <p class="errornote">{{ agreement_error_message }}</p>
  <form method="post" class="mms-review-actions__form">
    {% csrf_token %}
    <button type="submit" name="action" value="retry_docuseal" class="default">Mēģināt vēlreiz</button>
  </form>
  {% endif %}

  {% if agreement.external_url %}
  <p><a href="{{ agreement.external_url }}" target="_blank" rel="noopener">Atvērt DocuSeal ↗</a></p>
  {% endif %}

  {% if agreement.external_id %}
  <form method="post" class="mms-review-actions__form">
    {% csrf_token %}
    <button type="submit" name="action" value="sync_docuseal">Pārbaudīt DocuSeal statusu</button>
  </form>
  {% endif %}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_agreement_module_docuseal.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/registrations/views.py templates/registrations/admin/_agreement_module.html tests/registrations/test_agreement_module_docuseal.py
git commit -m "feat(registrations): DocuSeal status, retry, sync, link in Līgums module (P5 Slice D)"
```

---

## Task 10: Documentation

**Files:**
- Modify: `docs/deployment.md` (required-secrets pre-flight)
- Modify: `AGENTS.md` (Current Status + "P5 Slice D delivered")
- Modify: `docs/milestones.md` (mark Slice D delivered)

- [ ] **Step 1: Add the required-secrets pre-flight to `docs/deployment.md`**

Read `docs/deployment.md`, locate (or create) a "Required secrets" / pre-flight section, and add the five Slice D settings with a one-line note that they are only needed when `AGREEMENT_PROVIDER_MODE=docuseal`:

```markdown
### Agreement platform (DocuSeal) — required when AGREEMENT_PROVIDER_MODE=docuseal
- `AGREEMENT_PROVIDER_MODE` — `stub` (default) or `docuseal`.
- `DOCUSEAL_API_URL` — base API URL of the self-hosted DocuSeal instance.
- `DOCUSEAL_API_KEY` — DocuSeal API token (sent as `X-Auth-Token`).
- `DOCUSEAL_TEMPLATE_ID` — integer id of the agreement template configured in DocuSeal.
- `DOCUSEAL_WEBHOOK_SECRET` — shared secret for HMAC-SHA256 verification of the `submission.completed` webhook.

Webhook endpoint to register in DocuSeal: `POST https://<host>/integrations/docuseal/webhook/`, event `submission.completed`.
```

- [ ] **Step 2: Update `AGENTS.md`**

Read `AGENTS.md`, update the "Current Status" line to note P5 Slice D delivered, and add a Slice D entry mirroring the existing slice-summary style (electronic path wired to DocuSeal: boundary+provider adapter, optimistic sent, webhook-driven signed + manual sync, void-archive, sent/signed email suppression, electronic→paper fallback).

- [ ] **Step 3: Update `docs/milestones.md`**

Read `docs/milestones.md`, mark P5 Slice D (acceptance items 6, 8, 9, 10) delivered under the P5 status block.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment.md AGENTS.md docs/milestones.md
git commit -m "docs: P5 Slice D — DocuSeal secrets, status, milestone (P5 Slice D)"
```

---

## Final verification

- [ ] **Run the full suite**

Run: `uv run pytest -q`
Expected: all green, ≥ current baseline + the ~40 new tests added here.

- [ ] **Lint + type-check**

Run: `uv run ruff check .` then `uv run ruff format --check .` then `uv run mypy .`
Expected: clean. (If mypy flags `actor=None` into `mark_agreement_signed`, confirm the `actor` param is untyped/`ARG001` as in the existing signature; no annotation change needed.)

- [ ] **Stub-mode manual LAN smoke** (`AGREEMENT_PROVIDER_MODE=stub`, server at `192.168.3.245:8000`)
  - Approve an electronic-preference application → open the review detail → click "Atzīmēt kā nosūtītu". Confirm: state `Nosūtīts`, `external_id`/`external_url` populated (stub values), **no** `sent` email in the console backend, "Atvērt DocuSeal ↗" + "Pārbaudīt DocuSeal statusu" visible.
  - `curl` a signed webhook with a valid HMAC (compute `hmac-sha256(DOCUSEAL_WEBHOOK_SECRET, body)`; in stub mode `verify_webhook_signature` returns True so any header passes — to exercise the real verifier set `AGREEMENT_PROVIDER_MODE=docuseal` + `DOCUSEAL_WEBHOOK_SECRET`). Confirm state → `Parakstīts`, no `signed` email.
  - Void the agreement → confirm `void` email IS sent and (electronic + external_id) an archive job is enqueued (check qcluster log / no error).
  - Approve a second application, set its guardian email empty, mark sent → confirm it flips to paper and no DocuSeal enqueue.
  - Paper agreement → emails on sent/signed, no DocuSeal UI.

- [ ] **Finish the branch** via `superpowers:finishing-a-development-branch`.
