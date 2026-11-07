#!/usr/bin/env python3
"""Minimal PayPal Orders v2 sandbox smoke test.

This proves the full loop before we build any UI:
  create order -> buyer approves -> capture payment -> status COMPLETED

It uses only sandbox credentials and the Python standard library.

Setup:
  1. Copy .env.example to .env and fill in the sandbox Client ID and Secret.
  2. Run: python scripts/paypal_smoke_test.py
  3. Open the printed approval URL, log in as the sandbox *personal* buyer,
     approve the payment, then press Enter in the terminal.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict | None = None,
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"PayPal error {exc.code}:\n{detail}") from exc


def get_access_token(base: str, client_id: str, secret: str) -> str:
    credentials = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        f"{base}/v1/oauth2/token",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Token error {exc.code}:\n{detail}") from exc
    token = payload.get("access_token")
    if not token:
        raise SystemExit(f"No access_token in response: {payload}")
    print("1/3  OAuth token acquired")
    return token


def main() -> None:
    load_dotenv(ROOT / ".env")
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    secret = os.environ.get("PAYPAL_SECRET", "").strip()
    base = os.environ.get("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com").rstrip("/")
    currency = os.environ.get("PAYPAL_CURRENCY", "MYR").upper()
    amount_value = os.environ.get("PAYPAL_AMOUNT", "25.00")

    if not client_id or not secret or client_id.startswith("your_"):
        raise SystemExit(
            "Set PAYPAL_CLIENT_ID and PAYPAL_SECRET in .env first.\n"
            "Use the sandbox app credentials, not your live PayPal login."
        )

    token = get_access_token(base, client_id, secret)
    auth = {"Authorization": f"Bearer {token}"}
    json_headers = {**auth, "Content-Type": "application/json"}

    order_payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {"currency_code": currency, "value": amount_value},
                "description": "Invoice payment sandbox test",
            }
        ],
        "application_context": {
            "brand_name": "Invoice Autopilot",
            "user_action": "PAY_NOW",
            "shipping_preference": "NO_SHIPPING",
        },
    }
    order = request_json(
        "POST",
        f"{base}/v2/checkout/orders",
        headers={**json_headers, "PayPal-Request-Id": str(uuid.uuid4())},
        body=order_payload,
    )
    order_id = order.get("id")
    approve = next(
        (link["href"] for link in order.get("links", []) if link.get("rel") == "approve"),
        None,
    )
    if not order_id or not approve:
        raise SystemExit(f"Unexpected order response: {json.dumps(order, indent=2)[:2000]}")

    print(f"2/3  Order created: {order_id}")
    print(f"     Status: {order.get('status')}")
    print(f"     Approve URL: {approve}")
    print("\nOpen the URL, pay with the sandbox personal buyer account, then come back.")
    input("Press Enter after approving the payment... ")

    capture = request_json(
        "POST",
        f"{base}/v2/checkout/orders/{order_id}/capture",
        headers={**json_headers, "Prefer": "return=representation", "PayPal-Request-Id": str(uuid.uuid4())},
        body={},
    )
    status = capture.get("status")
    print(f"3/3  Capture status: {status}")
    if status != "COMPLETED":
        print(json.dumps(capture, indent=2)[:3000])
        raise SystemExit("Capture did not complete; inspect the response above.")

    capture_id = None
    for unit in capture.get("purchase_units", []):
        payments = unit.get("payments", {})
        captures = payments.get("captures", [])
        if captures:
            capture_id = captures[0].get("id")
            amount = captures[0].get("amount", {})
            print(f"     Capture ID: {capture_id}")
            print(f"     Amount: {amount.get('value')} {amount.get('currency_code')}")
            break

    print("\nSandbox loop works: order -> approval -> capture -> COMPLETED.")


if __name__ == "__main__":
    main()
