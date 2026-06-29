"""Task 4 — autocomplete JSON endpoint behavior and access control."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_autocomplete_requires_authenticated_parent(client):
    response = client.get(reverse("addresses:autocomplete"), {"q": "Raiņa"})

    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_autocomplete_returns_empty_for_short_query(verified_client):
    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "Ra"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.django_db
def test_autocomplete_returns_results(verified_client):
    from apps.addresses.models import AddressGroup

    group = AddressGroup.objects.create(
        label="Raiņa iela, Cēsis",
        normalized_label="raina iela cesis",
        street_code="100",
        street_name="Raiņa iela",
        locality_code="200",
        locality_name="Cēsis",
        region_code="300",
        region_name="Cēsu nov.",
    )

    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "Raiņa"})

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "kind": "group",
                "id": str(group.id),
                "label": "Raiņa iela, Cēsis",
                "hint": "Cēsu nov.",
            }
        ]
    }


@pytest.mark.django_db
def test_autocomplete_empty_dataset_returns_empty(verified_client):
    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "Raiņa"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


# ---------------------------------------------------------------------------
# Selected-group house-number suffix endpoint (refinement)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_autocomplete_supports_group_house_number_suffix(verified_client):
    """GET /addresses/autocomplete/?q=12&group=<id> returns building entries."""
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
    )
    AddressEntry.objects.create(
        vzd_code="4012",
        label="Raiņa iela 12, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 cesis cesu nov",
        group=group,
        postal_code="LV-4101",
        region_code="300",
        region_name="Cēsu nov.",
    )

    response = verified_client.get(
        reverse("addresses:autocomplete"), {"q": "12", "group": str(group.id)}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) >= 1
    assert data["results"][0]["kind"] == "address"
    assert data["results"][0]["label"] == "Raiņa iela 12, Cēsis, Cēsu nov."


# ---------------------------------------------------------------------------
# Building-scoped apartment endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_autocomplete_supports_building_apartment_suffix(verified_client):
    from apps.addresses.models import AddressApartment, AddressEntry, AddressGroup

    group = AddressGroup.objects.create(label="Raiņa iela, Cēsis", normalized_label="raina iela cesis")
    building = AddressEntry.objects.create(
        vzd_code="401",
        label="Raiņa iela 12, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 cesis cesu nov",
        group=group,
        postal_code="LV-4101",
    )
    AddressApartment.objects.create(
        vzd_code="9001",
        building=building,
        label="Raiņa iela 12-3, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 3 cesis cesu nov",
        postal_code="LV-4101",
    )

    response = verified_client.get(
        reverse("addresses:autocomplete"), {"q": "3", "building": str(building.id)}
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "kind": "apartment",
            "id": "9001",
            "label": "Raiņa iela 12-3, Cēsis, Cēsu nov.",
            "hint": "LV-4101",
        }
    ]
