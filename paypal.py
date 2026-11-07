"""Small PayPal Orders v2 client using only the Python standard library."""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from config import PAYPAL_API_BASE, PAYPAL_CLIENT_ID, PAYPAL_SECRET, paypal_configured

_token_lock = threading.Lock()
_token_cache: dict[str, float | str] = {"token": "", "expires_at": 0.0}


class PayPalError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 0, debug_id: str = "", issues: list | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.debug_id = debug_id
        self.issues = issues or []


def _parse_error(exc: urllib.error.HTTPError) -> PayPalError:
    raw = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    details = payload.get("details") or []
    issues = [item.get("issue", "") for item in details if item.get("issue")]
    message = payload.get("message") or raw[:300] or "PayPal request failed."
    if "ORDER_NOT_APPROVED" in issues:
        message = "The buyer has not approved this order yet. Open the PayPal checkout and complete it first."
    elif "INSTRUMENT_DECLINED" in issues:
        message = "The sandbox buyer's funding source was declined. Try another funding source."
    return PayPalError(
        message,
        status_code=exc.code,
        debug_id=payload.get("debug_id", ""),
        issues=issues,
    )


def _token() -> str:
    if not paypal_configured():
        raise PayPalError("PayPal sandbox credentials are not configured in .env.")
    with _token_lock:
        token = str(_token_cache["token"])
        if token and float(_token_cache["expires_at"]) > time.time() + 30:
            return token
        credentials = base64.b64encode(
            f"{PAYPAL_CLIENT_ID}:{PAYPAL_SECRET}".encode()
        ).decode()
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            f"{PAYPAL_API_BASE}/v1/oauth2/token",
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
            raise _parse_error(exc) from exc
        except urllib.error.URLError as exc:
            raise PayPalError(f"Could not reach PayPal: {exc.reason}") from exc
        token = payload.get("access_token", "")
        if not token:
            raise PayPalError("PayPal did not return an access token.")
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + int(payload.get("expires_in", 3000))
        return token


def _request(method: str, path: str, body: dict | None = None) -> dict:
    token = _token()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{PAYPAL_API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            "PayPal-Request-Id": str(uuid.uuid4()),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _parse_error(exc) from exc
    except urllib.error.URLError as exc:
        raise PayPalError(f"Could not reach PayPal: {exc.reason}") from exc


def approve_link(order: dict) -> str:
    for link in order.get("links", []):
        if link.get("rel") == "approve":
            return link.get("href", "")
    return ""


def create_order(
    *,
    invoice_id: int,
    invoice_number: str,
    amount_cents: int,
    currency: str,
    description: str,
    return_url: str,
    cancel_url: str,
) -> tuple[str, str]:
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": f"invoice-{invoice_id}",
                "invoice_id": invoice_number[:127],
                "description": description[:127] or f"Invoice {invoice_number}",
                "amount": {
                    "currency_code": currency,
                    "value": f"{amount_cents / 100:.2f}",
                },
            }
        ],
        "application_context": {
            "brand_name": "PaidOnTime",
            "locale": "en-US",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    order = _request("POST", "/v2/checkout/orders", payload)
    order_id = order.get("id", "")
    url = approve_link(order)
    if not order_id or not url:
        raise PayPalError("PayPal created an order but did not return an approval link.")
    return order_id, url


def get_order(order_id: str) -> dict:
    return _request("GET", f"/v2/checkout/orders/{order_id}")


def capture_order(order_id: str) -> dict:
    return _request("POST", f"/v2/checkout/orders/{order_id}/capture", {})


def capture_id(capture: dict) -> str:
    for unit in capture.get("purchase_units", []):
        for item in unit.get("payments", {}).get("captures", []):
            return item.get("id", "")
    return ""
