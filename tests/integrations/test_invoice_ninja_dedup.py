import pytest
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings

pytestmark = pytest.mark.django_db

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
)


@override_settings(**INVOICE_NINJA)
def test_ensure_product_reuses_existing_by_product_key(active_plan):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"id": "prod-existing"}]}, text=""
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=lookup
    ) as m:
        result = invoice_ninja.ensure_product(active_plan)
    assert result.external_id == "prod-existing"
    # Only the GET lookup happened — no POST create.
    assert all(call.args[0] == "GET" for call in m.call_args_list)


@override_settings(**INVOICE_NINJA)
def test_ensure_product_creates_when_absent(active_plan):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")
    create = SimpleNamespace(status_code=200, json=lambda: {"id": "prod-new"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, create],
    ) as m:
        result = invoice_ninja.ensure_product(active_plan)
    assert result.external_id == "prod-new"
    assert m.call_args_list[0].args[0] == "GET"
    assert m.call_args_list[1].args[0] == "POST"


@override_settings(**INVOICE_NINJA)
def test_ensure_client_reuses_existing_by_guardian_pk(guardian):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"id": "client-existing"}]}, text=""
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=lookup
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-existing"
    assert all(call.args[0] == "GET" for call in m.call_args_list)


@override_settings(**INVOICE_NINJA)
def test_ensure_client_creates_with_custom_value1_when_absent(guardian):
    from apps.integrations import invoice_ninja

    lookup = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")
    create = SimpleNamespace(status_code=200, json=lambda: {"id": "client-new"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, create],
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-new"
    post_call = m.call_args_list[1]
    assert post_call.args[0] == "POST"
    assert post_call.kwargs["json"]["custom_value1"] == str(guardian.pk)
