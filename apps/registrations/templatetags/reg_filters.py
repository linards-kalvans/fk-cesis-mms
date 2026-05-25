"""Template filters for parent-facing registration workspace."""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key] for use in templates.

    Returns None for missing variables (which Django resolves as ``""``)
    so partials can reference context that has not yet been provided
    without crashing on a non-dict value.
    """
    if dictionary is None or not hasattr(dictionary, "get"):
        return None
    return dictionary.get(key)
