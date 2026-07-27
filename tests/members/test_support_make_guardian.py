"""P13 cleanup — tests/support.make_guardian owns its own local split,
does not import production split_guardian_full_name or call sync_full_name."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_make_guardian_full_name_shorthand_sets_first_and_family():
    from tests.support import make_guardian

    g = make_guardian(full_name="Anna Ozola")
    assert g.first_name == "Anna"
    assert g.family_name == "Ozola"
    assert g.display_name == "Anna Ozola"


def test_make_guardian_multi_token_first_name():
    from tests.support import make_guardian

    g = make_guardian(full_name="Anna Marija Ozola")
    assert g.first_name == "Anna Marija"
    assert g.family_name == "Ozola"


def test_make_guardian_single_token():
    from tests.support import make_guardian

    g = make_guardian(full_name="Jānis")
    assert g.first_name == "Jānis"
    assert g.family_name == ""


def test_make_guardian_explicit_parts_override_full_name():
    from tests.support import make_guardian

    g = make_guardian(
        full_name="Ignored Name",
        first_name="Explicit",
        family_name="Parts",
    )
    assert g.first_name == "Explicit"
    assert g.family_name == "Parts"


def test_make_guardian_does_not_import_production_splitter():
    """The test helper must NOT import split_guardian_full_name from production."""
    import inspect

    from tests import support

    source = inspect.getsource(support)
    assert "from apps.members.models import split_guardian_full_name" not in source
    assert "split_guardian_full_name" not in source


def test_make_guardian_does_not_call_sync_full_name():
    """The test helper must NOT call sync_full_name()."""
    import inspect

    from tests import support

    source = inspect.getsource(support)
    assert "sync_full_name" not in source
