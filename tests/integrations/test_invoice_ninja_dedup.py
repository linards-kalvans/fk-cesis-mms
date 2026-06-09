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

# active_plan fixture has season "2026/2027" -> product_key "biedra-maksa-2026-2027".
PRODUCT_KEY = "biedra-maksa-2026-2027"


@override_settings(**INVOICE_NINJA)
def test_ensure_product_reuses_existing_by_product_key(active_plan):
    from apps.integrations import invoice_ninja

    # The lookup must verify product_key, not blindly take rows[0].
    lookup = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": [{"id": "prod-existing", "product_key": PRODUCT_KEY}]},
        text="",
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=lookup
    ) as m:
        result = invoice_ninja.ensure_product(active_plan)
    assert result.external_id == "prod-existing"
    # Only the GET lookup happened — no POST create.
    assert all(call.args[0] == "GET" for call in m.call_args_list)
    # The lookup uses the fuzzy ?filter= (not the ignored ?product_key=) and
    # restricts to active records (archived/soft-deleted must not be reused).
    assert "filter=" in m.call_args_list[0].args[1]
    assert "status=active" in m.call_args_list[0].args[1]


@override_settings(**INVOICE_NINJA)
def test_ensure_product_ignores_non_matching_product_key(active_plan):
    from apps.integrations import invoice_ninja

    # A fuzzy ?filter= hit whose product_key does NOT match must NOT be reused.
    lookup = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": [{"id": "some-other", "product_key": "kaut-kas-cits"}]},
        text="",
    )
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
        status_code=200,
        json=lambda: {"data": [{"id": "client-existing", "custom_value1": str(guardian.pk)}]},
        text="",
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=lookup
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-existing"
    assert all(call.args[0] == "GET" for call in m.call_args_list)
    assert "filter=" in m.call_args_list[0].args[1]
    assert "status=active" in m.call_args_list[0].args[1]


@override_settings(**INVOICE_NINJA)
def test_ensure_client_ignores_soft_deleted_match(guardian):
    from apps.integrations import invoice_ninja

    # Regression: a row whose custom_value1 matches but which is archived/
    # soft-deleted must NOT be reused (its id is invalid on a new invoice —
    # this is what broke a re-push after the IN test data was wiped).
    lookup = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "data": [
                {"id": "dead-client", "custom_value1": str(guardian.pk),
                 "is_deleted": True, "archived_at": 1781012696}
            ]
        },
        text="",
    )
    create = SimpleNamespace(status_code=200, json=lambda: {"id": "client-new"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, create],
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-new"
    assert m.call_args_list[1].args[0] == "POST"


@override_settings(**INVOICE_NINJA)
def test_ensure_client_ignores_non_matching_client(guardian):
    from apps.integrations import invoice_ninja

    # Regression: IN ignores ?custom_value1= and returns foreign clients; a row
    # whose custom_value1 != guardian.pk must NOT be reused (the bug that mapped
    # every guardian's invoices onto one manually-created client).
    lookup = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": [{"id": "someone-else", "custom_value1": "999"}]},
        text="",
    )
    create = SimpleNamespace(status_code=200, json=lambda: {"id": "client-new"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, create],
    ) as m:
        result = invoice_ninja.ensure_client(guardian)
    assert result.external_id == "client-new"
    assert m.call_args_list[0].args[0] == "GET"
    assert m.call_args_list[1].args[0] == "POST"


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
