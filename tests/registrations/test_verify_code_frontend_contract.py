"""RED tests — verification-code auto-check frontend contract.

Two halves (kept out of the visual-contract module so the source-level JS
sniffing follows the established ``test_wizard_js_contract.py`` pattern
instead of mixing with rendered-page visual tests):

1. Rendered ``/register/verify/`` template hooks — the form and code input
   gain semantic ``data-*`` hooks, a dedicated empty inline-error live
   region appears, and the page loads its own script through the existing
   ``extra_js`` block. Manual submit stays as the no-JS fallback.

2. Source-level contract of ``static/js/verify_code.js`` — listens to the
   code input's ``input`` event (typing + paste + OTP autofill), preflights
   exactly six ASCII digits before hitting the check endpoint, guards
   overlapping/duplicate checks, keeps the input, surfaces a Latvian inline
   error on invalid/network failure, and calls ``form.requestSubmit()`` only
   when the endpoint answers ``{"valid": true}``.

Hook names pinned here (implementation must match):
    form  → data-verify-form
    input → data-verify-code-input
    error → data-verify-error (empty live region, carries aria-live)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.core import mail
from django.test import Client

JS_PATH = Path(__file__).resolve().parents[2] / "static" / "js" / "verify_code.js"

pytestmark = pytest.mark.django_db


def _source() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _render_verify_page(email: str) -> str:
    client = Client()
    client.post("/register/", {"email": email})
    resp = client.get("/register/verify/")
    assert resp.status_code == 200, f"verify page setup failed: {resp.status_code}"
    return str(resp.content.decode("utf-8"))


def _extract_code_from_email() -> str:
    """Extract the 6-digit code from the latest sent email."""
    body = mail.outbox[-1].body
    match = re.search(r"\b\d{6}\b", body)
    assert match is not None, f"No 6-digit code found in email body: {body[:300]}"
    return match.group(0)


# ---------------------------------------------------------------------------
# 1. Template hooks on the rendered verification page
# ---------------------------------------------------------------------------

class TestVerifyPageTemplateHooks:
    def test_form_carries_verify_hook(self):
        content = _render_verify_page("hooksform@example.com")
        assert "data-verify-form" in content, (
            "verification form must expose a data-verify-form hook"
        )

    def test_code_input_carries_hook(self):
        content = _render_verify_page("hooksinput@example.com")
        assert "data-verify-code-input" in content, (
            "code input must expose a data-verify-code-input hook"
        )

    def test_dedicated_error_live_region_is_empty_on_render(self):
        content = _render_verify_page("hookserror@example.com")
        match = re.search(r"<[^>]*data-verify-error[^>]*>", content)
        assert match is not None, (
            "page must render a dedicated data-verify-error element"
        )
        tag = match.group(0)
        assert "aria-live" in tag, (
            f"error region must be an ARIA live region, got: {tag}"
        )
        following = content[match.end():]
        assert following.lstrip().startswith("</"), (
            "error live region must render empty (JS fills it on failure)"
        )

    def test_page_script_loaded_via_extra_js_block(self):
        content = _render_verify_page("hooksscript@example.com")
        assert "js/verify_code.js" in content, (
            "page must load static/js/verify_code.js through the extra_js block"
        )
        # Rendered inside the body (extra_js), not in <head>.
        assert re.search(
            r"<script[^>]+verify_code\.js[^>]*>\s*</script>", content
        ), "script must be included as a plain <script src> tag"

    def test_manual_submit_remains_as_no_js_fallback(self):
        """Progressive enhancement: the existing manual submit path must
        stay untouched on the page (native form POST still works without
        the script)."""
        content = _render_verify_page("hookssubmit@example.com")
        assert 'type="submit"' in content
        assert "Apstiprināt" in content
        assert 'method="post"' in content, (
            "form must keep its native POST fallback"
        )


# ---------------------------------------------------------------------------
# 1b. Manual-submit fallback: failed verification POST must echo the entered code
# ---------------------------------------------------------------------------

class TestVerifyFailureEchoesEnteredCode:
    """Regression for review finding 1.

    ``verify_one_time_code_view`` renders failed manual submissions with the
    entered code under the context key ``code`` (not a bound ``form``). The
    re-rendered ``#id_code`` must therefore retain what the parent typed —
    the current template reads ``form.code.value``, which silently resolves
    to "" in that context and wipes the digits on every error round-trip.
    """

    def test_invalid_code_post_retains_entered_code_in_id_code_value(self):
        email = "echo-invalid-code@example.com"
        client = Client()
        client.post("/register/", {"email": email})
        real_code = _extract_code_from_email()
        wrong_code = "000000" if real_code != "000000" else "000001"
        assert wrong_code != real_code

        resp = client.post("/register/verify/", {"code": wrong_code})
        content = resp.content.decode("utf-8")

        match = re.search(r'<input[^>]*id="id_code"[^>]*>', content, re.S)
        assert match is not None, "verify page must render the #id_code input"
        tag = match.group(0)
        assert f'value="{wrong_code}"' in tag, (
            "failed manual submission must re-render the entered code in "
            f"#id_code so the parent's digits survive the error round-trip; "
            f"got input tag: {tag}"
        )


# ---------------------------------------------------------------------------
# 2. Source-level contract of static/js/verify_code.js
# ---------------------------------------------------------------------------

class TestVerifyCodeJsExists:
    def test_script_file_exists(self):
        assert JS_PATH.exists(), f"{JS_PATH} must exist"


class TestVerifyCodeJsContract:
    @pytest.fixture
    def src(self) -> str:
        assert JS_PATH.exists(), f"{JS_PATH} must exist"
        return _source()

    def test_listens_to_input_event_not_keyboard_only(self, src: str):
        """input fires for typing, paste, AND browser/mobile OTP autofill —
        keyboard events alone miss paste and autofill."""
        assert re.search(r"""addEventListener\(\s*['"]input['"]""", src), (
            "must bind the code input's `input` event (typing/paste/autofill)"
        )
        for keyboard_event in ("keydown", "keyup", "keypress"):
            assert f"'{keyboard_event}'" not in src and (
                f'"{keyboard_event}"' not in src
            ), f"must not rely on {keyboard_event} for the check trigger"

    def test_preflights_exactly_six_ascii_digits(self, src: str):
        assert "[0-9]{6}" in src or r"\d{6}" in src, (
            "must validate exactly six digits before preflighting"
        )

    def test_targets_check_endpoint_path(self, src: str):
        assert "/register/verify/check/" in src, (
            "JS must POST to the dedicated check endpoint"
        )

    def test_sends_csrf_token(self, src: str):
        assert "X-CSRFToken" in src or "csrfmiddlewaretoken" in src, (
            "endpoint is CSRF-protected; the script must carry the token"
        )

    def test_submits_via_request_submit_only(self, src: str):
        assert "requestSubmit" in src, (
            "must use form.requestSubmit() so the native submit contract "
            "(hidden CSRF field included) is preserved"
        )
        # form.submit() bypasses submit listeners/interception semantics —
        # requestSubmit is the required call.
        assert ".submit(" not in src, (
            "must call form.requestSubmit(), never raw form.submit()"
        )

    def test_guards_overlapping_and_duplicate_checks(self, src: str):
        assert re.search(r"(inflight|in-flight|busy|checking|pending)", src, re.I), (
            "must track an in-flight check so requests never overlap"
        )
        assert re.search(r"last(?:Code|Value|Checked|Submitted)", src, re.I), (
            "must remember the last checked value so the same code is not "
            "re-preflighted on every keystroke after six digits"
        )

    def test_keeps_the_code_input(self, src: str):
        assert not re.search(r"""\.value\s*=\s*['"]\s*['"]""", src), (
            "must retain the user's input on failure — never clear it"
        )

    def test_surfaces_latvian_inline_error(self, src: str):
        assert "data-verify-error" in src, (
            "must write into the dedicated data-verify-error live region"
        )
        assert re.search(r"[āčēģīķļņšūžĀČĒ]", src), (
            "network-failure fallback message must be Latvian"
        )

    def test_reads_json_verdict_valid(self, src: str):
        assert re.search(r"""['"]?valid['"]?\s*(===|==|\.|\b)""", src) or ".valid" in src, (
            "must branch on the JSON `valid` flag from the endpoint"
        )

    def test_targets_page_hooks(self, src: str):
        assert "data-verify-form" in src
        assert "data-verify-code-input" in src, (
            "must bind through the template hooks, not brittle ids"
        )


# ---------------------------------------------------------------------------
# 3. Source-level stale-response guard contract (review finding 2)
# ---------------------------------------------------------------------------

# An identifier that carries the request's checked code (``code``,
# ``checkedCode``, ``requestedCode``, ``lastCheckedCode`` …).
_IDENT_WITH_CODE = r"[A-Za-z_$][A-Za-z0-9_$]*[Cc]ode[A-Za-z0-9_$]*"

# A strict/equality comparison between the *live* ``input.value`` (optionally
# ``.trim()``-ed) and that identifier, either operand order. A plain
# assignment (``var code = input.value.trim();``) must not match — only
# ``==``/``===``/``!=``/``!==`` do.
_STALE_GUARD_RE = re.compile(
    rf"{_IDENT_WITH_CODE}\s*[!=]==?\s*input\.value"
    rf"|input\.value(?:\.trim\(\))?\s*[!=]==?\s*{_IDENT_WITH_CODE}"
)


class TestVerifyCodeJsStaleResponseGuard:
    """Regression for review finding 2.

    An AJAX preflight response for code A can land after the parent has
    edited/pasted code B. The response path must compare the current input
    value against the code it actually checked before it calls
    ``form.requestSubmit()`` or writes the invalid error — a stale verdict
    must neither submit the changed digits nor label an input the parent has
    since edited.
    """

    @pytest.fixture
    def src(self) -> str:
        assert JS_PATH.exists(), f"{JS_PATH} must exist"
        return _source()

    def test_compares_live_input_value_against_checked_code(self, src: str):
        match = _STALE_GUARD_RE.search(src)
        assert match is not None, (
            "response path must compare input.value with the request's "
            "checked code before acting on the verdict (e.g. "
            "`if (code !== input.value.trim()) return;`)"
        )

    def test_guard_precedes_request_submit(self, src: str):
        """A stale valid:true verdict must not submit the form."""
        match = _STALE_GUARD_RE.search(src)
        assert match is not None, "stale-response guard missing"
        assert "requestSubmit" in src
        assert match.start() < src.index("requestSubmit"), (
            "the value-vs-checked-code guard must sit in the response path "
            "before form.requestSubmit(), not after it"
        )

    def test_guard_precedes_invalid_error_write(self, src: str):
        """A stale valid:false verdict must not label a since-edited input."""
        match = _STALE_GUARD_RE.search(src)
        assert match is not None, "stale-response guard missing"
        assert "GENERIC_INVALID" in src
        # The last occurrence is the invalid-verdict write in the response
        # path (the first is the constant declaration at the top).
        assert match.start() < src.rindex("GENERIC_INVALID"), (
            "the value-vs-checked-code guard must precede the "
            "GENERIC_INVALID error write in the response path"
        )
