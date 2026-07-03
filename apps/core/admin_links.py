"""Reusable Django-admin cross-link helpers.

``admin_link`` renders an anchor to any model instance's admin change page;
``admin_links`` renders a compact list for a to-many relation. Both fall back
to plain text when the target model is not registered in the admin.
"""

from django.urls import NoReverseMatch, reverse
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe


def admin_link(obj, label=None):
    """Anchor to ``obj``'s admin change page, or "—" when ``obj`` is None."""
    if obj is None:
        return "—"
    text = str(obj) if label is None else label
    try:
        url = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
            args=[obj.pk],
        )
    except NoReverseMatch:
        # Plain-text fallback, escaped so the result is safe to join in admin_links.
        return conditional_escape(text)
    return format_html('<a href="{}">{}</a>', url, text)  # type: ignore[return-value,no-any-return]


def admin_links(objs, *, limit=10, empty="—"):
    """Comma/`<br>`-joined anchors for an iterable of instances.

    Caps the list at ``limit`` and appends a "+N" overflow marker. Returns
    ``empty`` for an empty iterable. Each part is escaped by ``admin_link``.
    """
    items = list(objs)
    if not items:
        return empty
    parts = [str(admin_link(o)) for o in items[:limit]]
    extra = len(items) - limit
    if extra > 0:
        parts.append(f"+{extra}")
    return mark_safe("<br>".join(parts))  # noqa: S308 — parts are admin_link-escaped
