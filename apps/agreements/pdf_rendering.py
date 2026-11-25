"""Comparison-only PDF rendering. No models, mail or lifecycle mutations."""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
from importlib.metadata import version
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string

TEMPLATE_VERSION = "shadow-v1-2026-11"
FIELD_NAMES = (
    "agreement_number", "child_name", "child_personal_id", "child_birth_date",
    "child_address", "guardian_name", "guardian_personal_id", "guardian_address",
    "guardian_email", "guardian_phone",
)


def validate_snapshot(snapshot: dict) -> dict:
    fields = snapshot.get("fields")
    path = snapshot.get("signing_path")
    if not isinstance(fields, dict) or path not in {"paper", "electronic"}:
        raise ValueError("invalid_snapshot")
    if set(fields) != set(FIELD_NAMES) or any(
        not isinstance(fields[key], str) or len(fields[key]) > 5000 for key in FIELD_NAMES
    ):
        raise ValueError("invalid_snapshot")
    return {"fields": {key: fields[key] for key in FIELD_NAMES}, "signing_path": path}


def _assets() -> tuple[Path, Path, Path, Path, Path, Path]:
    base = Path(settings.BASE_DIR)
    fonts = Path("/usr/share/fonts/truetype/dejavu")
    return (
        base / "templates/agreements/pdf/shadow_v1.html",
        base / "apps/agreements/pdf_assets/shadow_v1.css",
        fonts / "DejaVuSans.ttf", fonts / "DejaVuSans-Bold.ttf",
        fonts / "DejaVuSansMono-Bold.ttf", base / "static/img/fk-cesis-logo.png",
    )


def _harfbuzz_version() -> str:
    """Safe independent version probe for the system HarfBuzz library.

    WeasyPrint's FFI cdef does not expose ``hb_version_string``, so read the
    same soname through plain ctypes without mutating upstream declarations.
    Provenance is mandatory: callers fail closed when this is unavailable.
    """
    library = ctypes.util.find_library("harfbuzz")
    if not library:
        raise RuntimeError("harfbuzz_unavailable")
    try:
        harfbuzz = ctypes.CDLL(library)
        harfbuzz.hb_version_string.restype = ctypes.c_char_p
        version_bytes: bytes = harfbuzz.hb_version_string()
    except (AttributeError, OSError):
        raise RuntimeError("harfbuzz_unavailable") from None
    if not version_bytes:
        raise RuntimeError("harfbuzz_unavailable")
    return version_bytes.decode("ascii")


def shadow_renderer_provenance() -> dict:
    # Called only for enabled shadowing, not at Django/admin import time.
    from weasyprint.text.ffi import pango

    return {
        "template_version": TEMPLATE_VERSION,
        "weasyprint": version("weasyprint"),
        "pango": pango.pango_version(),
        "harfbuzz": _harfbuzz_version(),
        "assets": {asset.name: hashlib.sha256(asset.read_bytes()).hexdigest()
                   for asset in _assets()},
    }


class AssetFetcher:
    """Lazy WeasyPrint 70 URLFetcher wrapper: exact assets or fatal rejection."""

    _fail_on_errors = True

    def __init__(self, allowed: set[str]):
        from weasyprint.urls import URLFetcher

        self.allowed = frozenset(allowed)
        self.fetcher = URLFetcher(allowed_protocols={"file"}, allow_redirects=False,
                                  fail_on_errors=True)

    def fetch(self, url, headers=None):
        from weasyprint.urls import FatalURLFetchingError

        if url not in self.allowed:
            raise FatalURLFetchingError("Resource outside PDF asset allowlist")
        return self.fetcher.fetch(url, headers)

    def __call__(self, url):
        return self.fetch(url)


def render_shadow_pdf(snapshot: dict, *, template_version: str) -> bytes:
    import pymupdf
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import FatalURLFetchingError

    if template_version != TEMPLATE_VERSION:
        raise ValueError("unknown_template")
    snapshot = validate_snapshot(snapshot)
    _, css_path, regular, bold, mono, logo = _assets()
    fetcher = AssetFetcher({p.as_uri() for p in (regular, bold, mono, logo)})
    fonts = FontConfiguration()
    font_css = (
        f"@font-face {{font-family: Body; src:url('{regular.as_uri()}')}}"
        f"@font-face {{font-family: Body; font-weight:bold; src:url('{bold.as_uri()}')}}"
        f"@font-face {{font-family: Fill; font-weight:bold; src:url('{mono.as_uri()}')}}"
    )
    html = render_to_string("agreements/pdf/shadow_v1.html", {
        "fields": snapshot["fields"], "electronic": snapshot["signing_path"] == "electronic",
        "logo": logo.as_uri(),
    })
    try:
        css = CSS(string=font_css + css_path.read_text(), url_fetcher=fetcher, font_config=fonts)
        pdf = HTML(string=html, url_fetcher=fetcher).write_pdf(
            stylesheets=[css], font_config=fonts,
        )
    except FatalURLFetchingError:
        # WeasyPrint 70's fatal resource error derives from BaseException, so it
        # would escape ordinary worker handling. Translate it at the renderer
        # boundary only; the original asset allowlist is unchanged.
        raise RuntimeError("resource_rejected") from None
    if len(pdf) > 20 * 1024 * 1024:
        raise ValueError("output_limits")
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        if not 1 <= len(document) <= 20:
            raise ValueError("output_limits")
    return bytes(pdf)
