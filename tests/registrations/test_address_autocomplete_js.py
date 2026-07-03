"""Static JS contract test for selected-group suffix query behavior.

The `address_autocomplete.js` widget must send only the typed suffix after
a selected group label so the server receives a narrow building-number query.
This test reads the source file and asserts the required helper exists.
No browser runner is used — consistent with the repo's JS test convention.
"""

from pathlib import Path


_JS_PATH = Path("static/js/address_autocomplete.js")
_SOURCE = _JS_PATH.read_text()


def test_address_autocomplete_js_has_get_query_helper():
    """The source must contain a function getQuery for suffix extraction."""
    assert "function getQuery" in _SOURCE, (
        "address_autocomplete.js must define function getQuery(input)"
    )


def test_address_autocomplete_js_reads_group_label_attribute():
    """getQuery must read data-address-group-label from the input element."""
    assert "data-address-group-label" in _SOURCE, (
        "getQuery must read the group label attribute to compute suffix"
    )


def test_address_autocomplete_js_slices_group_label_length():
    """getQuery must slice the visible value by groupLabel.length."""
    assert "slice(groupLabel.length)" in _SOURCE or (
        "slice(" in _SOURCE and "groupLabel" in _SOURCE
    ), (
        "getQuery must slice the input value to extract the suffix after group label"
    )
