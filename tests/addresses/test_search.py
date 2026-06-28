"""Task 3 — grouped search service behavior."""

from __future__ import annotations

import pytest


@pytest.fixture
def raina_group(db):
    """One AddressGroup with building entries including 1, 3, 12, 120."""
    from apps.addresses.models import AddressEntry, AddressGroup

    group = AddressGroup.objects.create(
        label="Raiņa iela, Cēsis",
        normalized_label="raina iela cesis",
        street_code="100",
        street_name="Raiņa iela",
        locality_code="200",
        locality_name="Cēsis",
        region_code="300",
        region_name="Cēsu nov.",
        entry_count=4,
    )
    for number in ("1", "3", "12", "120"):
        AddressEntry.objects.create(
            vzd_code=f"40{number}",
            label=f"Raiņa iela {number}, Cēsis, Cēsu nov.",
            normalized_label=f"raina iela {number} cesis cesu nov",
            group=group,
            postal_code="LV-4101",
            region_code="300",
            region_name="Cēsu nov.",
        )
    return group


@pytest.mark.django_db
def test_search_returns_group_before_house_number_spam(raina_group):
    from apps.addresses.services import search_addresses

    results = search_addresses("Raiņa")

    assert results[0] == {
        "kind": "group",
        "id": str(raina_group.id),
        "label": "Raiņa iela, Cēsis",
        "hint": "Cēsu nov.",
    }
    assert all(result["kind"] == "group" for result in results)


@pytest.mark.django_db
def test_search_with_group_returns_building_entries(raina_group):
    from apps.addresses.services import search_addresses

    results = search_addresses("Raiņa iela, Cēsis", group_id=raina_group.id)

    assert [result["kind"] for result in results] == ["address", "address", "address", "address"]
    assert results[0]["label"] == "Raiņa iela 1, Cēsis, Cēsu nov."
    assert results[0]["hint"] == "LV-4101"


@pytest.mark.django_db
def test_search_requires_three_characters(raina_group):
    from apps.addresses.services import search_addresses

    assert search_addresses("Ra") == []


@pytest.mark.django_db
def test_search_limits_results(db):
    from apps.addresses.models import AddressGroup
    from apps.addresses.services import search_addresses

    for index in range(12):
        AddressGroup.objects.create(
            label=f"Raiņa iela, Vieta {index}",
            normalized_label=f"raina iela vieta {index}",
            street_code=str(index),
            street_name="Raiņa iela",
            locality_code=f"2{index}",
            locality_name=f"Vieta {index}",
            region_code="300",
            region_name="Cēsu nov.",
        )

    assert len(search_addresses("Raiņa", limit=10)) == 10


# ---------------------------------------------------------------------------
# Building-number search (refinement)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_search_returns_entry_for_street_then_house_number(raina_group):
    """Query "Raiņa iela 12" must return the building entry first."""
    from apps.addresses.services import search_addresses

    results = search_addresses("Raiņa iela 12")

    assert len(results) >= 1
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."


@pytest.mark.django_db
def test_search_returns_entry_for_house_number_then_street(raina_group):
    """Query "12 Raiņa iela" must return the same building entry."""
    from apps.addresses.services import search_addresses

    results = search_addresses("12 Raiņa iela")

    assert len(results) >= 1
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."


@pytest.mark.django_db
def test_search_selected_group_accepts_house_number_only(raina_group):
    """Selected-group search must accept a 2-char number query like "12"."""
    from apps.addresses.services import search_addresses

    results = search_addresses("12", group_id=raina_group.id)

    assert len(results) >= 1
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."


# ---------------------------------------------------------------------------
# House-number vs postal-code collision (bug repro)
# ---------------------------------------------------------------------------


@pytest.fixture
def postal_collision_group(db):
    """Two entries where house-number token matches postal-code digits.

    Entry 1:  Raiņa iela 1, … LV-4125  (normalized includes ``lv 4125``)
    Entry 12: Raiņa iela 12, … LV-4101

    Query ``12 Raiņa iela`` should return #12 first, but token ``12``
    false-matches ``4125`` in the postal code, pushing #1 up alphabetically.
    """
    from apps.addresses.models import AddressEntry, AddressGroup

    group = AddressGroup.objects.create(
        label="Raiņa iela",
        normalized_label="raina iela",
        street_code="100",
        street_name="Raiņa iela",
        locality_code="200",
        locality_name="Cēsis",
        region_code="300",
        region_name="Cēsu nov.",
        entry_count=2,
    )
    AddressEntry.objects.create(
        vzd_code="40001",
        label="Raiņa iela 1, Jaunpiebalga, Jaunpiebalgas pag., Cēsu nov., LV-4125",
        normalized_label="raina iela 1 jaunpiebalga jaunpiebalgas pag cesu nov lv 4125",
        group=group,
        postal_code="LV-4125",
        region_code="300",
        region_name="Cēsu nov.",
    )
    AddressEntry.objects.create(
        vzd_code="40012",
        label="Raiņa iela 12, Cēsis, Cēsu nov., LV-4101",
        normalized_label="raina iela 12 cesis cesu nov",
        group=group,
        postal_code="LV-4101",
        region_code="300",
        region_name="Cēsu nov.",
    )
    return group


@pytest.mark.django_db
def test_search_house_number_does_not_match_postal_code_digits(
    postal_collision_group,
):
    """``12 Raiņa iela`` must rank #12 above the #1/LV-4125 false-positive."""
    from apps.addresses.services import search_addresses

    results = search_addresses("12 Raiņa iela")

    assert len(results) >= 2
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov., LV-4101"
    # The false-positive must not steal the top slot.
    assert results[1]["label"] != "Raiņa iela 12, Cēsis, Cēsu nov., LV-4101"


@pytest.mark.django_db
def test_search_house_number_vs_postal_still_works_for_group(
    postal_collision_group,
):
    """Selected-group search is unchanged — #12 still found."""
    from apps.addresses.services import search_addresses

    results = search_addresses("12", group_id=postal_collision_group.id)

    assert len(results) == 1
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov., LV-4101"


# ---------------------------------------------------------------------------
# Global house-number search must not be capped by the DB page limit
# before the house-number boost.  (Pony-tailed regression from live VZD smoke.)
# ---------------------------------------------------------------------------


@pytest.fixture
def postal_flood_group(db):
    """One group with 12 false-positives (postal-code collisions) + 1 real entry.

    False positives outnumber the default limit (10), so the real entry
    (Raiņa iela 12) is never fetched by the DB slice and gets lost.
    """
    from apps.addresses.models import AddressEntry, AddressGroup

    group = AddressGroup.objects.create(
        label="Raiņa iela",
        normalized_label="raina iela",
        street_code="100",
        street_name="Raiņa iela",
        locality_code="200",
        locality_name="Cēsis",
        region_code="300",
        region_name="Cēsu nov.",
        entry_count=13,
    )
    for idx in range(12):
        AddressEntry.objects.create(
            vzd_code=f"90{idx:03d}",
            label=f"Raiņa iela 1, Vieta {idx:02d}, Cēsu nov., LV-4125",
            normalized_label=f"raina iela 1 vieta {idx:02d} cesu nov lv 4125",
            group=group,
            postal_code="LV-4125",
            region_code="300",
            region_name="Cēsu nov.",
        )
    AddressEntry.objects.create(
        vzd_code="90012",
        label="Raiņa iela 12, Cēsis, Cēsu nov., LV-4101",
        normalized_label="raina iela 12 cesis cesu nov lv 4101",
        group=group,
        postal_code="LV-4101",
        region_code="300",
        region_name="Cēsu nov.",
    )
    return group


@pytest.mark.django_db
def test_search_global_house_number_not_lost_in_postal_flood(
    postal_flood_group,
):
    """``12 Raiņa iela`` must return #12 first even when false positives
    outnumber the DB limit."""
    from apps.addresses.services import search_addresses

    results = search_addresses("12 Raiņa iela", limit=10)

    assert len(results) >= 1
    assert results[0]["kind"] == "address"
    assert results[0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov., LV-4101"
