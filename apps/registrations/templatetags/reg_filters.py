"""Template filters for parent-facing registration workspace."""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] for use in templates."""
    if dictionary is None:
        return None
    return dictionary.get(key)
