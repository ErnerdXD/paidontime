#!/usr/bin/env python3
"""PaidOnTime — a small invoice-to-PayPal web app.

Run locally:
    python server.py
Then open http://127.0.0.1:8000

Only PayPal sandbox credentials are accepted.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import traceback
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import ai
import config
import db
import paypal
import views

INVOICE_PATH = re.compile(r"^/invoices/(\d+)$")
REFRESH_PATH = re.compile(r"^/invoices/(\d+)/refresh$")
CAPTURE_PATH = re.compile(r"^/invoices/(\d+)/capture$")
RETRY_PATH = re.compile(r"^/invoices/(\d+)/retry$")

ALLOWED_CURRENCIES = {"MYR", "USD", "SGD", "EUR", "GBP", "AUD"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_form(raw: str) -> dict[str, str]:
    parsed = parse_qs(raw, keep_blank_values=True)
    return {key: values[0].strip() for key, values in parsed.items()}


def flash_redirect(path: str, *, notice: str = "", error: str = "") -> str:
    params = []
    if notice:
        params.append(f"notice={quote(notice)}")
    if error:
        params.append(f"error={quote(error)}")
    return f"{path}?{'&'.join(params)}" if params else path


class Handler(BaseHTTPRequestHandler):
    server_version = "PaidOnTime/0.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_html(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _invoice_id(self, path: str) -> int | None:
        match = INVOICE_PATH.fullmatch(path)
        return int(match.group(1)) if match else None

    def _render_invoice(self, invoice_id: int, status: int = 200, notice: str = "", error: str = "") -> None:
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_html(views.not_found(), 404)
            return
        self._send_html(views.detail(invoice, notice=notice, error=error), status)

    # ---------------------------------------------------------------- GET

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        notice = query.get("notice", [""])[0]
        error = query.get("error", [""])[0]

        try:
            if path == "/":
                self._send_html(
                    views.dashboard(db.list_invoices(), db.stats(), notice=notice, error=error)
                )
                return
            if path == "/invoices/new":
                self._send_html(views.new_invoice(error=error))
                return
            if path == "/healthz":
                self._send_json({"ok": True, "paypal_configured": config.paypal_configured()})
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path == "/static/style.css":
                css = (config.ROOT / "static" / "style.css").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(css)))
                self.send_header("Cache-Control", "public, max-age=300")
                self.end_headers()
                self.wfile.write(css)
                return
            if path == "/samples/sample_invoice.pdf":
                sample = (config.ROOT / "samples" / "sample_invoice.pdf").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(sample)))
                self.send_header("Content-Disposition", 'inline; filename="sample_invoice.pdf"')
                self.end_headers()
                self.wfile.write(sample)
                return
            if path == "/paypal/return":
                self._handle_return(query)
                return
            if path == "/paypal/cancel":
                self._handle_cancel(query)
                return

            invoice_id = self._invoice_id(path)
            if invoice_id is not None:
                self._render_invoice(invoice_id, notice=notice, error=error)
                return

            self._send_html(views.not_found(), 404)
        except paypal.PayPalError as exc:
            self.log_message("PayPal error: %s", exc.message)
            self._send_html(views.server_error(exc.message), 502)
        except Exception as exc:  # noqa: BLE001
            self.log_message("Unhandled GET error: %s", exc)
            traceback.print_exc()
            self._send_html(views.server_error("The server hit an unexpected error."), 500)

    def _handle_return(self, query: dict[str, list[str]]) -> None:
        invoice_id_raw = query.get("invoice_id", [""])[0]
        if not invoice_id_raw.isdigit():
            self._send_html(views.not_found(), 404)
            return
        invoice_id = int(invoice_id_raw)
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_html(views.not_found(), 404)
            return
        if not invoice["paypal_order_id"]:
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error="No PayPal order is attached to this invoice."))
            return
        token = query.get("token", [""])[0]
        if token and token != invoice["paypal_order_id"]:
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error="The PayPal return token does not match this invoice."))
            return
        try:
            capture = paypal.capture_order(invoice["paypal_order_id"])
            db.set_status(invoice_id, "COMPLETED", capture_id=paypal.capture_id(capture))
            self._redirect(
                flash_redirect(f"/invoices/{invoice_id}", notice="Payment captured. This invoice is paid.")
            )
        except paypal.PayPalError as exc:
            # The buyer may have approved but the capture call can race. Refresh first.
            try:
                order = paypal.get_order(invoice["paypal_order_id"])
                if order.get("status") == "APPROVED":
                    db.set_status(invoice_id, "APPROVED")
                elif order.get("status") == "COMPLETED":
                    db.set_status(invoice_id, "COMPLETED")
            except paypal.PayPalError:
                pass
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error=exc.message))

    def _handle_cancel(self, query: dict[str, list[str]]) -> None:
        invoice_id_raw = query.get("invoice_id", [""])[0]
        if not invoice_id_raw.isdigit():
            self._send_html(views.not_found(), 404)
            return
        invoice_id = int(invoice_id_raw)
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_html(views.not_found(), 404)
            return
        if invoice["status"] != "COMPLETED":
            db.set_status(invoice_id, "CANCELLED")
        self._redirect(flash_redirect(f"/invoices/{invoice_id}", notice="Payment cancelled. No money moved."))

    # ---------------------------------------------------------------- POST

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        if path == "/api/extract":
            self._handle_extract(raw)
            return
        if path == "/api/reminder":
            self._handle_reminder(raw)
            return
        form = parse_form(raw)

        try:
            if path == "/invoices":
                self._handle_create(form)
                return

            match = REFRESH_PATH.fullmatch(path)
            if match:
                self._handle_refresh(int(match.group(1)))
                return

            match = CAPTURE_PATH.fullmatch(path)
            if match:
                self._handle_capture(int(match.group(1)))
                return

            match = RETRY_PATH.fullmatch(path)
            if match:
                self._handle_retry(int(match.group(1)))
                return

            self._send_html(views.not_found(), 404)
        except paypal.PayPalError as exc:
            self.log_message("PayPal error: %s", exc.message)
            self._send_html(views.server_error(exc.message), 502)
        except Exception as exc:  # noqa: BLE001
            self.log_message("Unhandled POST error: %s", exc)
            traceback.print_exc()
            self._send_html(views.server_error("The server hit an unexpected error."), 500)

    def _handle_extract(self, raw: str) -> None:
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "Invalid JSON body."}, 400)
            return

        try:
            if payload.get("text"):
                fields = ai.extract_invoice_from_text(str(payload["text"]))
            else:
                encoded = str(payload.get("pdf_base64", ""))
                if "," in encoded:
                    encoded = encoded.split(",", 1)[1]
                try:
                    data = base64.b64decode(encoded, validate=True)
                except Exception:
                    self._send_json({"ok": False, "error": "The upload was not valid base64."}, 400)
                    return
                if len(data) > 8 * 1024 * 1024:
                    self._send_json({"ok": False, "error": "The PDF is larger than 8 MB."}, 400)
                    return
                if not data.startswith(b"%PDF-"):
                    self._send_json({"ok": False, "error": "Upload a PDF file."}, 400)
                    return
                self.log_message("AI extraction: PDF %s bytes", len(data))
                fields = ai.extract_invoice_from_pdf(data)
            self._send_json({"ok": True, "fields": fields})
        except ai.AIError as exc:
            self.log_message("AI extraction failed: %s", exc)
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            self.log_message("Unexpected extraction error: %s", exc)
            traceback.print_exc()
            self._send_json({"ok": False, "error": "Extraction failed unexpectedly."}, 500)

    def _handle_reminder(self, raw: str) -> None:
        try:
            payload = json.loads(raw or "{}")
            invoice_id = int(payload.get("invoice_id", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            self._send_json({"ok": False, "error": "Invalid invoice request."}, 400)
            return
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_json({"ok": False, "error": "Invoice not found."}, 404)
            return
        if invoice["status"] not in ("CREATED", "APPROVED"):
            self._send_json({"ok": False, "error": "Only unpaid invoices need a follow-up."}, 400)
            return
        try:
            reminder = ai.draft_reminder(dict(invoice))
            self._send_json({"ok": True, "reminder": reminder})
        except ai.AIError as exc:
            self.log_message("Reminder draft failed: %s", exc)
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            self.log_message("Unexpected reminder error: %s", exc)
            traceback.print_exc()
            self._send_json({"ok": False, "error": "Could not draft a follow-up."}, 500)

    def _handle_create(self, form: dict[str, str]) -> None:
        values = {
            "client_name": form.get("client_name", ""),
            "client_email": form.get("client_email", ""),
            "invoice_number": form.get("invoice_number", ""),
            "description": form.get("description", ""),
            "amount": form.get("amount", ""),
            "currency": form.get("currency", "MYR").upper(),
            "due_date": form.get("due_date", ""),
        }

        def fail(message: str) -> None:
            self._send_html(views.new_invoice(values, error=message), 400)

        if not values["client_name"]:
            return fail("Client name is required.")
        if len(values["client_name"]) > 120:
            return fail("Client name is too long.")
        if values["client_email"] and not EMAIL_RE.match(values["client_email"]):
            return fail("That client email does not look valid.")
        if not values["invoice_number"]:
            return fail("Invoice number is required.")
        if len(values["invoice_number"]) > 60:
            return fail("Invoice number is too long.")
        if db.invoice_number_exists(values["invoice_number"]):
            return fail("That invoice number already exists. Use a unique number.")
        if values["currency"] not in ALLOWED_CURRENCIES:
            return fail("Choose a supported currency.")
        if values["due_date"]:
            try:
                date.fromisoformat(values["due_date"])
            except ValueError:
                return fail("Enter the due date as YYYY-MM-DD.")
        try:
            amount = Decimal(values["amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return fail("Enter a valid amount, for example 1250.00.")
        if amount <= 0:
            return fail("The amount must be greater than zero.")
        if amount > Decimal("1000000"):
            return fail("The amount is too large for this demo.")
        amount_cents = int(amount * 100)

        if not config.paypal_configured():
            return fail("PayPal sandbox credentials are missing. Add them to .env and restart.")

        invoice_id = db.create_invoice(
            client_name=values["client_name"],
            client_email=values["client_email"],
            invoice_number=values["invoice_number"],
            description=values["description"],
            amount_cents=amount_cents,
            currency=values["currency"],
            due_date=values["due_date"],
        )

        try:
            return_url = f"{config.PUBLIC_BASE_URL}/paypal/return?invoice_id={invoice_id}"
            cancel_url = f"{config.PUBLIC_BASE_URL}/paypal/cancel?invoice_id={invoice_id}"
            order_id, approval_url = paypal.create_order(
                invoice_id=invoice_id,
                invoice_number=values["invoice_number"],
                amount_cents=amount_cents,
                currency=values["currency"],
                description=values["description"] or f"Invoice {values['invoice_number']}",
                return_url=return_url,
                cancel_url=cancel_url,
            )
            db.set_order(invoice_id, order_id, approval_url)
            self._redirect(f"/invoices/{invoice_id}")
        except paypal.PayPalError as exc:
            db.set_status(invoice_id, "FAILED")
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error=exc.message))

    def _handle_refresh(self, invoice_id: int) -> None:
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_html(views.not_found(), 404)
            return
        if not invoice["paypal_order_id"]:
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error="No PayPal order is attached."))
            return
        order = paypal.get_order(invoice["paypal_order_id"])
        status = order.get("status", "")
        mapped = {
            "CREATED": "CREATED",
            "APPROVED": "APPROVED",
            "COMPLETED": "COMPLETED",
            "VOIDED": "CANCELLED",
        }.get(status, invoice["status"])
        db.set_status(invoice_id, mapped)
        self._redirect(flash_redirect(f"/invoices/{invoice_id}", notice=f"PayPal status: {status or 'unknown'}."))

    def _handle_capture(self, invoice_id: int) -> None:
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_html(views.not_found(), 404)
            return
        if not invoice["paypal_order_id"]:
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error="No PayPal order is attached."))
            return
        capture = paypal.capture_order(invoice["paypal_order_id"])
        db.set_status(invoice_id, "COMPLETED", capture_id=paypal.capture_id(capture))
        self._redirect(flash_redirect(f"/invoices/{invoice_id}", notice="Payment captured. This invoice is paid."))

    def _handle_retry(self, invoice_id: int) -> None:
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            self._send_html(views.not_found(), 404)
            return
        if invoice["status"] == "COMPLETED":
            self._redirect(flash_redirect(f"/invoices/{invoice_id}", error="This invoice is already paid."))
            return
        return_url = f"{config.PUBLIC_BASE_URL}/paypal/return?invoice_id={invoice_id}"
        cancel_url = f"{config.PUBLIC_BASE_URL}/paypal/cancel?invoice_id={invoice_id}"
        order_id, approval_url = paypal.create_order(
            invoice_id=invoice_id,
            invoice_number=invoice["invoice_number"],
            amount_cents=invoice["amount_cents"],
            currency=invoice["currency"],
            description=invoice["description"] or f"Invoice {invoice['invoice_number']}",
            return_url=return_url,
            cancel_url=cancel_url,
        )
        db.set_order(invoice_id, order_id, approval_url)
        self._redirect(flash_redirect(f"/invoices/{invoice_id}", notice="A new PayPal link was created."))


def main() -> None:
    db.init_db()
    server = ThreadingHTTPServer(("0.0.0.0", config.PORT), Handler)
    print(f"PaidOnTime running at http://127.0.0.1:{config.PORT}")
    print(f"Public base URL: {config.PUBLIC_BASE_URL}")
    print(f"PayPal sandbox configured: {config.paypal_configured()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
