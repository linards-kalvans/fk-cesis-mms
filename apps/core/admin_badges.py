"""Reusable Django-admin status badge.

``status_badge`` renders a CSS-classed span; pair it with the
``static/admin/fk_badges.css`` stylesheet via a ModelAdmin ``Media`` class.
"""

from django.utils.html import format_html

_LEVELS = {"ok", "fail", "pending", "muted"}


def status_badge(text, level, *, tooltip=""):
    """Coloured badge span. ``level`` is one of ok|fail|pending|muted."""
    css_level = level if level in _LEVELS else "muted"
    if tooltip:
        return format_html(
            '<span class="fk-badge fk-badge--{}" title="{}">{}</span>',
            css_level, tooltip, text,
        )  # type: ignore[return-value,no-any-return]
    return format_html(
        '<span class="fk-badge fk-badge--{}">{}</span>', css_level, text
    )  # type: ignore[return-value,no-any-return]
