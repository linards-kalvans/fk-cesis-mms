"""Template filters for the Admin Hub."""

from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Dict lookup by a variable key - Django templates cannot do this."""
    if not hasattr(mapping, "get"):
        return ""
    return mapping.get(key, "")
