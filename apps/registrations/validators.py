"""Shared field-format rules for registration data.

The personal-id pattern lived twice inside ``forms.py``'s two clean methods.
The Admin Hub's inline editor needs the same rule, and a third copy is how
two validators end up disagreeing about what a valid personal id is — a
divergence this codebase has already produced more than once.
"""

from __future__ import annotations

import re

PERSONAL_ID_RE = re.compile(r"^\d{6}-\d{5}$")
PERSONAL_ID_FORMAT_MESSAGE = "Ievadiet personas kodu formātā DDDDDD-DDDDD."


def is_valid_personal_id(value: str) -> bool:
    """Whether *value* matches the accepted personal-id format.

    An empty value is valid: the field is optional throughout registration."""
    return not value or bool(PERSONAL_ID_RE.match(value))
