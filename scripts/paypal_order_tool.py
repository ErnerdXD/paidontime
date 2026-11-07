#!/usr/bin/env python3
"""Inspect or capture an existing PayPal sandbox order.

Usage:
  python scripts/paypal_order_tool.py status 6NF979214U900711M
  python scripts/paypal_order_tool.py capture 6NF979214U900711M
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
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


def get_token(base: str, client_id: str, secret: str) -> str:
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
    with urllib.request.urlopen(req, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["access_token"]


def call(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"PayPal error {exc.code}:\n{detail}") from exc


def approve_link(order: dict) -> str | None:
    return next(
        (link["href"] for link in order.get("links", []) if link.get("rel") == "approve"),
        None,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "capture"])
    parser.add_argument("order_id")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
    secret = os.environ.get("PAYPAL_SECRET", "").strip()
    base = os.environ.get("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com").rstrip("/")
    if not client_id or not secret or client_id.startswith("your_"):
        raise SystemExit("Set PAYPAL_CLIENT_ID and PAYPAL_SECRET in .env first.")

    token = get_token(base, client_id, secret)
    order_url = f"{base}/v2/checkout/orders/{args.order_id}"
    order = call("GET", order_url, token)
    status = order.get("status")
    print(f"Order:  {args.order_id}")
    print(f"Status: {status}")

    link = approve_link(order)
    if link:
        print(f"Approve: {link}")

    if args.action == "status":
        if status == "CREATED":
            print("\nThe buyer has NOT approved this order yet.")
            print("Open the approve URL in an incognito window and complete the sandbox checkout.")
        elif status == "APPROVED":
            print("\nBuyer approved. Run: python scripts/paypal_order_tool.py capture <order-id>")
        elif status == "COMPLETED":
            print("\nThis order is already paid.")
        return

    if status != "APPROVED":
        if status == "CREATED":
            print("\nCannot capture yet: the buyer has not approved the order.")
            print("Complete the sandbox checkout at the approve URL, then run capture again.")
        else:
            print(f"\nCannot capture from status {status}.")
        raise SystemExit(2)

    capture = call("POST", f"{order_url}/capture", token, body={})
    print(f"\nCapture status: {capture.get('status')}")
    for unit in capture.get("purchase_units", []):
        for item in unit.get("payments", {}).get("captures", []):
            amount = item.get("amount", {})
            print(f"Capture ID: {item.get('id')}")
            print(f"Amount: {amount.get('value')} {amount.get('currency_code')}")
    if capture.get("status") != "COMPLETED":
        print(json.dumps(capture, indent=2)[:3000])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
