"""Live sandbox probe for Invoice Ninja credit-note API.

Run manually with real sandbox env:
uv run python -m scripts.validate_invoice_ninja_credit

Safe mode (default) only reads the credits list. Set P8_CREDIT_PROBE_MUTATE=1
and supply P8_CREDIT_PROBE_CLIENT_ID plus P8_CREDIT_PROBE_AMOUNT to attempt a
single credit-note create + an apply probe.
"""

from __future__ import annotations

import json
import os

import requests

TIMEOUT = 15


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    env_path = os.environ.get("ENV_PATH", ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path, override=False)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    headers = {
        "X-Api-Token": api_key,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        **kwargs.pop("headers", {}),
    }
    response = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    print(method, url, response.status_code)
    try:
        payload = response.json()
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:4000])
    except ValueError:
        print(response.text[:1000])
    return response


def _credit_id_from_response(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    data = payload.get("data", payload)
    if isinstance(data, dict):
        return str(data.get("id", ""))
    return ""


def _mutate_probe(api_url: str, api_key: str) -> None:
    client_id = _env("P8_CREDIT_PROBE_CLIENT_ID")
    amount = _env("P8_CREDIT_PROBE_AMOUNT")
    prefix = os.environ.get("INVOICE_NINJA_NUMBER_PREFIX", "MMS-PROBE")

    print("\n--- POST /credits (create) ---")
    body = {
        "client_id": client_id,
        "number": f"{prefix}-credit-probe",
        "date": "2026-06-30",
        "public_notes": "Sandbox credit probe",
        "line_items": [
            {
                "product_key": "sandbox-probe",
                "notes": "Sandbox credit",
                "cost": amount,
                "quantity": 1,
            }
        ],
    }
    resp = _request("POST", f"{api_url}/credits", api_key, json=body)
    if resp.status_code >= 400:
        print("Credit create failed; skipping apply probe.")
        return

    credit_id = _credit_id_from_response(resp)
    if not credit_id:
        print("Could not read credit id from response; skipping apply probe.")
        return

    print("\n--- POST /credits/bulk (apply) ---")
    apply_body = {
        "action": "apply",
        "ids": [credit_id],
        "data": {"invoices": [{"invoice_id": "nonexistent", "amount": amount}]},
    }
    _request("POST", f"{api_url}/credits/bulk", api_key, json=apply_body)
    print("\nExpected: apply action unsupported (422). Staff must apply credits manually.")


def main() -> None:
    _load_env()
    api_url = _env("INVOICE_NINJA_API_URL").rstrip("/")
    api_key = _env("INVOICE_NINJA_API_KEY")

    print("--- GET /credits ---")
    _request("GET", f"{api_url}/credits?per_page=1", api_key)

    if os.environ.get("P8_CREDIT_PROBE_MUTATE") == "1":
        _mutate_probe(api_url, api_key)
    else:
        print(
            "\nSafe mode. To run a mutate probe (create credit + apply attempt), set:\n"
            "P8_CREDIT_PROBE_MUTATE=1 P8_CREDIT_PROBE_CLIENT_ID=<id> P8_CREDIT_PROBE_AMOUNT=<amount>"
        )


if __name__ == "__main__":
    main()
