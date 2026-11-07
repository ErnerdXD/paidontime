"""AI invoice extraction with a DeepSeek/OpenAI-compatible chat endpoint."""

from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

import config

# The local sandbox installs pypdf here; on Render, pip installs it normally.
_DEPS = config.ROOT / ".deps"
if _DEPS.exists():
    sys.path.insert(0, str(_DEPS))

try:
    from pypdf import PdfReader
except ImportError:  # surfaced as a clear message at request time
    PdfReader = None


class AIError(RuntimeError):
    pass


SYSTEM_PROMPT = """You extract accounts-receivable data from invoice text.
Return ONLY a JSON object with exactly these keys:
{
  "client_name": string,
  "client_email": string,
  "invoice_number": string,
  "description": string,
  "amount": string,
  "currency": string,
  "due_date": string,
  "confidence": number,
  "warnings": array of strings
}

Rules:
- client_name is the party being billed ("Bill to"), not the sender.
- amount is the total amount due, as a plain decimal string with two places. No symbols or commas.
- currency is an ISO 4217 code. RM means MYR. $ is ambiguous: use USD and add a warning.
- invoice_number is the printed invoice/reference number.
- due_date is ISO YYYY-MM-DD. Leave it empty when the invoice does not show a due date.
- description is a short summary of the services or goods, not the full line-item table.
- Do not invent a value. Use an empty string when the invoice does not show it.
- confidence is 0.0 to 1.0 for the overall extraction.
- warnings lists missing, ambiguous or inconsistent fields.
- Return JSON only. No markdown, no commentary.
"""


def is_configured() -> bool:
    return config.ai_configured()


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AIError("The AI response did not contain a JSON object.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"The AI returned invalid JSON: {exc}") from exc


def _clean_amount(value: object) -> str:
    raw = str(value or "").strip()
    raw = re.sub(r"[^0-9.,-]", "", raw)
    if not raw:
        return ""
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        # Treat a single comma as a decimal separator only when it looks like one.
        raw = raw.replace(",", ".") if raw.count(",") == 1 and len(raw.split(",")[-1]) <= 2 else raw.replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        return ""
    if amount <= 0:
        return ""
    return f"{amount:.2f}"


def _clean_currency(value: object) -> str:
    raw = str(value or "").strip().upper()
    aliases = {
        "RM": "MYR",
        "MYR": "MYR",
        "USD": "USD",
        "SGD": "SGD",
        "EUR": "EUR",
        "GBP": "GBP",
        "AUD": "AUD",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
    }
    return aliases.get(raw, raw if len(raw) == 3 and raw.isalpha() else "")


def _clean_date(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _clean_fields(data: dict) -> dict:
    warnings = data.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    warnings = [str(item).strip() for item in warnings if str(item).strip()]
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "client_name": str(data.get("client_name", "")).strip()[:120],
        "client_email": str(data.get("client_email", "")).strip()[:160],
        "invoice_number": str(data.get("invoice_number", "")).strip()[:60],
        "description": str(data.get("description", "")).strip()[:127],
        "amount": _clean_amount(data.get("amount")),
        "currency": _clean_currency(data.get("currency")),
        "due_date": _clean_date(data.get("due_date")),
        "confidence": round(confidence, 2),
        "warnings": warnings[:8],
    }


def _chat(messages: list[dict], max_tokens: int = 900) -> str:
    if not config.ai_configured():
        raise AIError("AI_API_KEY is not configured. Add it to .env and restart.")
    payload = {
        "model": config.AI_MODEL,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    req = urllib.request.Request(
        f"{config.AI_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise AIError(f"AI request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise AIError(f"Could not reach the AI service: {exc.reason}") from exc

    content = (
        body.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not content:
        raise AIError("The AI service returned an empty response.")
    return content


def extract_invoice_from_text(text: str) -> dict:
    text = text.strip()
    if len(text) < 20:
        raise AIError("The invoice text is too short to extract.")
    content = _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Invoice text:\n\n{text[:24000]}"},
        ]
    )
    return _clean_fields(_extract_json(content))


def extract_pdf_text(data: bytes) -> str:
    if PdfReader is None:
        raise AIError("pypdf is not installed. Run: pip install -r requirements.txt")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = []
        for page in reader.pages[:10]:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
    except Exception as exc:  # noqa: BLE001
        raise AIError(f"Could not read that PDF: {exc}") from exc
    if len(text) < 20:
        raise AIError(
            "This PDF has no extractable text. It may be a scan; "
            "use a text-based PDF for this demo."
        )
    return text


def extract_invoice_from_pdf(data: bytes) -> dict:
    return extract_invoice_from_text(extract_pdf_text(data))


REMINDER_PROMPT = """You write a short payment follow-up for a freelancer.
Return ONLY a JSON object with exactly two keys:
{"subject": string, "body": string}

Rules:
- The body is a polite, direct email of at most 90 words.
- Mention the invoice number, amount and due date.
- If a payment link is provided, include it once.
- No legal threats, no guilt-tripping, no invented facts, no fake urgency.
- Write in the freelancer's voice, first person.
- Keep the subject under 80 characters.
- Return JSON only. No markdown, no commentary.
"""


def draft_reminder(invoice: dict) -> dict:
    due_raw = str(invoice.get("due_date") or "").strip()
    if not due_raw:
        raise AIError("Add a due date before drafting a follow-up.")
    try:
        due = date.fromisoformat(due_raw)
    except ValueError as exc:
        raise AIError("The invoice due date is not valid.") from exc
    days = (date.today() - due).days
    context = {
        "client_name": invoice.get("client_name", ""),
        "invoice_number": invoice.get("invoice_number", ""),
        "description": invoice.get("description", ""),
        "amount": f"{int(invoice.get('amount_cents', 0)) / 100:.2f}",
        "currency": invoice.get("currency", ""),
        "due_date": due_raw,
        "days_overdue": max(days, 0),
        "payment_link": invoice.get("approval_url", ""),
    }
    content = _chat(
        [
            {"role": "system", "content": REMINDER_PROMPT},
            {
                "role": "user",
                "content": "Invoice context:\n" + json.dumps(context, ensure_ascii=False),
            },
        ],
        max_tokens=500,
    )
    data = _extract_json(content)
    subject = str(data.get("subject", "")).strip()[:120]
    body = str(data.get("body", "")).strip()
    if not subject or not body:
        raise AIError("The AI did not return a complete subject and body.")
    return {"subject": subject, "body": body[:2500]}
