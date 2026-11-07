"""Configuration for the PaidOnTime demo.

Only sandbox PayPal credentials are accepted. The app refuses to start against
the live PayPal API so a demo can never move real money.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv(ROOT / ".env")

PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET", "").strip()
PAYPAL_API_BASE = os.environ.get(
    "PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com"
).rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PORT = int(os.environ.get("PORT", "8000"))
DATABASE_PATH = Path(
    os.environ.get("DATABASE_PATH", str(ROOT / "data" / "paidontime.db"))
)

AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek-chat").strip()

# Abuse limits for the public demo. These are deliberately low.
EXTRACT_PER_HOUR = int(os.environ.get("EXTRACT_PER_HOUR", "12"))
EXTRACT_DAILY = int(os.environ.get("EXTRACT_DAILY", "80"))
INVOICE_PER_HOUR = int(os.environ.get("INVOICE_PER_HOUR", "20"))
INVOICE_DAILY = int(os.environ.get("INVOICE_DAILY", "60"))
REMINDER_PER_HOUR = int(os.environ.get("REMINDER_PER_HOUR", "30"))
DEMO_PAUSED = os.environ.get("DEMO_PAUSED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if "sandbox" not in PAYPAL_API_BASE.lower():
    raise RuntimeError(
        "Refusing to start: PAYPAL_API_BASE is not a sandbox URL. "
        "This project only supports PayPal sandbox credentials."
    )


def paypal_configured() -> bool:
    return bool(
        PAYPAL_CLIENT_ID
        and PAYPAL_SECRET
        and not PAYPAL_CLIENT_ID.startswith("your_")
        and not PAYPAL_SECRET.startswith("your_")
    )


def ai_configured() -> bool:
    return bool(AI_API_KEY and not AI_API_KEY.startswith("your_"))

