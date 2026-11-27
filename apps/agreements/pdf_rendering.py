"""Comparison-only PDF rendering. No models, mail or lifecycle mutations."""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import tempfile
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


# ---------------------------------------------------------------------------
# Production (operative) renderer — versioned template, verified bytes.
# The shadow renderer above stays comparison-only and is never reused here.
# ---------------------------------------------------------------------------

PRODUCTION_TEMPLATE_VERSION = "v1-2026-11"

# Immutable identity of production template version ``v1-2026-11``. A version
# names exact bytes: any content or asset change requires a new version rather
# than an in-place edit. Rendering validates these digests and then renders the
# verified bytes, so a drifted file fails closed instead of silently shipping a
# different document.
#
# Asset sources/licenses for this version:
#   * ``v1_2026_11.html`` / ``v1_2026_11.css`` — in-repo, project-authored
#     documents; the wording is club-approved and must not be edited in place.
#   * ``DejaVuSans*.ttf`` — Debian ``fonts-dejavu-core`` (DejaVu Fonts license,
#     a permissive Bitstream Vera derivative; license text ships with the distro
#     package). Recorded here because no font file is vendored into the repo.
#   * ``fk-cesis-logo.png`` — club-owned logo in ``static/img/``.
# Multi-version map restructuring is deferred until a second version exists.
PRODUCTION_ASSET_DIGESTS: dict[str, str] = {
    "v1_2026_11.html": "9ba17809ca876b8fa15e21b09c982a2ebdac0311e592f899a3e769c7a37ae128",
    "v1_2026_11.css": "4d41f58019528d76db7e1720ac456894ab9a41ff521de7cae100678e2b6188fb",
    "DejaVuSans.ttf": "ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280",
    "DejaVuSans-Bold.ttf": "5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895",
    "DejaVuSansMono-Bold.ttf": "3a3c502eeff669a231549e80df9f7c49de109bafe303170409e905d0b31a38fe",
    "fk-cesis-logo.png": "aeb1a361a28615d7dc0df0eb83377c881e8a62f8b75efc3745eef4ae0abe8244",
}

_FONT_ASSETS = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono-Bold.ttf")
_LOGO_ASSET = "fk-cesis-logo.png"


def _production_assets() -> dict[str, Path]:
    base = Path(settings.BASE_DIR)
    fonts = Path("/usr/share/fonts/truetype/dejavu")
    return {
        "v1_2026_11.html": base / "templates/agreements/pdf/v1_2026_11.html",
        "v1_2026_11.css": base / "apps/agreements/pdf_assets/v1_2026_11.css",
        "DejaVuSans.ttf": fonts / "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf": fonts / "DejaVuSans-Bold.ttf",
        "DejaVuSansMono-Bold.ttf": fonts / "DejaVuSansMono-Bold.ttf",
        "fk-cesis-logo.png": base / "static/img/fk-cesis-logo.png",
    }


def _verified_production_assets() -> dict[str, bytes]:
    """Read every production asset and require its pinned digest.

    Fails closed for a missing file or any byte drift: an unknown version is
    never rendered with substitute content.
    """
    verified: dict[str, bytes] = {}
    for name, path in _production_assets().items():
        try:
            data = path.read_bytes()
        except OSError:
            raise RuntimeError("asset_unavailable") from None
        if hashlib.sha256(data).hexdigest() != PRODUCTION_ASSET_DIGESTS[name]:
            raise RuntimeError("asset_digest_mismatch")
        verified[name] = data
    return verified


def agreement_renderer_provenance(template_version: str) -> dict:
    """Return the immutable identity of a production template version."""
    from weasyprint.text.ffi import pango

    if template_version != PRODUCTION_TEMPLATE_VERSION:
        raise ValueError("unknown_template")
    assets = _verified_production_assets()
    # ``pango_version()`` returns an integer encoded as major*10000+minor*100+micro.
    raw_pango = int(pango.pango_version())
    return {
        "template_version": template_version,
        "weasyprint": version("weasyprint"),
        "pango": f"{raw_pango // 10000}.{raw_pango // 100 % 100}.{raw_pango % 100}",
        "harfbuzz": _harfbuzz_version(),
        "assets": {
            name: hashlib.sha256(data).hexdigest() for name, data in assets.items()
        },
    }


def render_agreement_pdf(snapshot: dict, *, template_version: str) -> bytes:
    """Render the operative agreement PDF from a frozen snapshot.

    No models, mail, signing, billing or provider calls. The versioned template
    and assets are digest-verified, written to a private temporary directory and
    used as the exact render input (no second read of the on-disk originals).
    """
    import pymupdf
    from django.template import Context, Engine
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import FatalURLFetchingError

    if template_version != PRODUCTION_TEMPLATE_VERSION:
        raise ValueError("unknown_template")
    snapshot = validate_snapshot(snapshot)
    assets = _verified_production_assets()
    html_source = assets["v1_2026_11.html"].decode("utf-8")
    css_source = assets["v1_2026_11.css"].decode("utf-8")

    with tempfile.TemporaryDirectory(prefix="agreement-pdf-") as directory:
        rendered_assets = {}
        for name, data in assets.items():
            target = Path(directory) / name
            target.write_bytes(data)
            rendered_assets[name] = target

        fetched = [
            rendered_assets[name].as_uri() for name in (*_FONT_ASSETS, _LOGO_ASSET)
        ]
        fetcher = AssetFetcher(set(fetched))
        regular, bold, mono = (rendered_assets[name] for name in _FONT_ASSETS)
        logo = rendered_assets[_LOGO_ASSET]
        fonts = FontConfiguration()
        font_css = (
            f"@font-face {{font-family: Body; src:url('{regular.as_uri()}')}}"
            f"@font-face {{font-family: Body; font-weight:bold; src:url('{bold.as_uri()}')}}"
            f"@font-face {{font-family: Fill; font-weight:bold; src:url('{mono.as_uri()}')}}"
        )
        html = Engine(autoescape=True).from_string(html_source).render(
            Context(
                {
                    "fields": snapshot["fields"],
                    "electronic": snapshot["signing_path"] == "electronic",
                    "logo": logo.as_uri(),
                }
            )
        )
        try:
            css = CSS(
                string=font_css + css_source,
                url_fetcher=fetcher,
                font_config=fonts,
            )
            pdf = HTML(string=html, url_fetcher=fetcher).write_pdf(
                stylesheets=[css], font_config=fonts
            )
        except FatalURLFetchingError:
            # WeasyPrint 70's fatal resource error derives from BaseException, so
            # translate it at the renderer boundary, never leaking it to workers.
            raise RuntimeError("resource_rejected") from None

    if len(pdf) > 20 * 1024 * 1024:
        raise ValueError("output_limits")
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        if not 1 <= len(document) <= 20:
            raise ValueError("output_limits")
    return bytes(pdf)
