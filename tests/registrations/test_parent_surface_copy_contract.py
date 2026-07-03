"""Latvian copy contract for parent-facing surfaces (P4 Slice E)."""

import re
from html.parser import HTMLParser

import pytest
from django.conf import settings
from django.urls import reverse

# English tokens that should never appear in user-visible copy on parent surfaces.
# Match is word-boundary, case-insensitive, against visible text only.
ENGLISH_TOKENS = (
    "submit", "save", "continue", "back", "next", "cancel",
    "loading", "error", "success", "please", "required",
    "yes", "no", "warning", "delete", "edit",
)

# Allowlisted fragments — legitimate English that must pass through, OR
# Latvian phrases that share letters with an English token (e.g. the
# Latvian preposition "no" meaning "from"). Stripped from rendered HTML
# *before* extracting visible text, so the token scan never sees them.
# When adding a new guard for a Latvian phrase containing "no", add the
# whole phrase here (e.g. "no pieteikuma"), not the bare word "no" —
# the bare token would mask real English "no" leaks.
ALLOWED_FRAGMENTS = (
    "FK Cēsis",            # brand
    "no pieteikuma",       # Latvian "from the application"
    "no iepriekšējā",      # Latvian "from previous"
    "no tiem",             # Latvian "from them"
)

_TOKEN_RE = re.compile(
    r"\b(" + "|".join(ENGLISH_TOKENS) + r")\b",
    re.IGNORECASE,
)


class _VisibleTextExtractor(HTMLParser):
    """Collect text nodes outside <script>, <style>, and HTML attributes."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):  # noqa: ANN001
        if self._skip_depth == 0:
            self._parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self._parts)


def _visible_text(html: str) -> str:
    stripped = html
    for fragment in ALLOWED_FRAGMENTS:
        stripped = stripped.replace(fragment, " ")
    parser = _VisibleTextExtractor()
    parser.feed(stripped)
    return parser.text


def _assert_no_english_leakage(html: str, surface: str) -> None:
    text = _visible_text(html)
    leaks = sorted({m.group(0).lower() for m in _TOKEN_RE.finditer(text)})
    assert not leaks, (
        f"English tokens leaked into {surface}: {leaks}\n"
        f"Sample text around first leak:\n"
        f"{text[: text.lower().find(leaks[0]) + 80] if leaks else ''}"
    )


@pytest.mark.django_db
@pytest.mark.slow
class TestParentSurfaceCopyContract:
    def test_start_registration_has_no_english_leakage(self, client):
        url = reverse("registrations:start-registration")
        response = client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/register/"
        )

    def test_verify_code_has_no_english_leakage(self, client):
        session = client.session
        session["pending_verification_email"] = "parent@example.com"
        session.save()
        url = reverse("accounts:verify-one-time-code")
        response = client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/register/verify/"
        )

    def test_parent_portal_empty_has_no_english_leakage(self, verified_client):
        url = reverse("registrations:parent-portal")
        response = verified_client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/portal/ (empty)"
        )

    def test_parent_portal_with_apps_has_no_english_leakage(
        self, verified_client, parent_account
    ):
        from apps.registrations.models import RegistrationApplication

        # verified_client depends on parent_account in conftest.py (function-scoped),
        # so the application is correctly owned by the logged-in user.
        RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
            member_full_name="Jānis Bērziņš",
        )
        url = reverse("registrations:parent-portal")
        response = verified_client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/portal/ (with apps)"
        )

    def test_application_workspace_has_no_english_leakage(
        self, verified_client, parent_account
    ):
        from apps.registrations.models import RegistrationApplication

        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
        )
        url = reverse("registrations:application-workspace", args=[app.id])
        response = verified_client.get(url)
        assert response.status_code == 200
        _assert_no_english_leakage(
            response.content.decode("utf-8"), "/applications/<id>/"
        )


class TestNewRegistrationTemplateCopy:
    """Static scan for /applications/new/ — its only render path is the
    no-JS POST-invalid fallback, which is impractical to render in a unit
    test. Scan the template source instead, stripping Django comment
    blocks first so legitimate developer comments don't trip the audit,
    then running the same visible-text extractor used at runtime so HTML
    tag names and attributes (e.g. ``data-wizard-next``, ``value="submit"``)
    don't trip the audit either — only user-visible copy is checked."""

    def test_new_registration_template_has_no_english_tokens(self):
        from pathlib import Path

        source = (
            Path(settings.BASE_DIR)
            / "templates/registrations/new_registration.html"
        ).read_text(encoding="utf-8")
        # Strip {% comment %}…{% endcomment %} blocks (multiline).
        cleaned = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}",
            " ",
            source,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Strip {# … #} single-line comments.
        cleaned = re.sub(r"\{#.*?#\}", " ", cleaned)
        # Drop Django template tags ({% … %}) and variable references
        # ({{ … }}) before feeding the result to the HTML parser; otherwise
        # the parser sees raw braces and may misclassify content.
        cleaned = re.sub(r"\{%.*?%\}", " ", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"\{\{.*?\}\}", " ", cleaned, flags=re.DOTALL)
        # Reuse the same visible-text extractor as the runtime tests — it
        # skips <script>/<style> bodies and HTML attributes, so we only
        # scan user-visible copy.
        visible = _visible_text(cleaned)
        leaks = sorted({m.group(0).lower() for m in _TOKEN_RE.finditer(visible)})
        assert not leaks, (
            f"English tokens in new_registration.html (static scan): {leaks}"
        )
