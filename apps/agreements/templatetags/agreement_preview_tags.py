"""Template helpers for the verified-parent blank agreement preview."""

from django import template

from apps.agreements import template_preview

register = template.Library()


@register.simple_tag
def agreement_preview_query() -> str:
    """Configured identity query for the preview manifest, or ``""``.

    The parent surface may assert the deployment's backend/template version;
    it never chooses them. A misconfiguration hides the identity instead of
    rendering an unvalidated one.
    """
    try:
        return template_preview.browser_query()
    except Exception:
        return ""
