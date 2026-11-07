"""SQLite persistence for PaidOnTime."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DATABASE_PATH

STATUS_LABELS = {
    "DRAFT": "Draft",
    "CREATED": "Awaiting payment",
    "APPROVED": "Approved",
    "COMPLETED": "Paid",
    "CANCELLED": "Cancelled",
    "FAILED": "Failed",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                client_email TEXT NOT NULL DEFAULT '',
                invoice_number TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL,
                due_date TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'DRAFT',
                paypal_order_id TEXT NOT NULL DEFAULT '',
                approval_url TEXT NOT NULL DEFAULT '',
                capture_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                paid_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)"
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(invoices)").fetchall()}
        if "due_date" not in columns:
            conn.execute(
                "ALTER TABLE invoices ADD COLUMN due_date TEXT NOT NULL DEFAULT ''"
            )


def create_invoice(
    *,
    client_name: str,
    client_email: str,
    invoice_number: str,
    description: str,
    amount_cents: int,
    currency: str,
    due_date: str = "",
) -> int:
    stamp = now_iso()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO invoices (
                client_name, client_email, invoice_number, description,
                amount_cents, currency, due_date, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?)
            """,
            (
                client_name,
                client_email,
                invoice_number,
                description,
                amount_cents,
                currency,
                due_date,
                stamp,
                stamp,
            ),
        )
        return int(cursor.lastrowid)


def get_invoice(invoice_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()


def list_invoices() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM invoices ORDER BY created_at DESC, id DESC"
        ).fetchall()


def invoice_number_exists(invoice_number: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM invoices WHERE invoice_number = ?",
            (invoice_number,),
        ).fetchone()
        return row is not None


def set_order(invoice_id: int, order_id: str, approval_url: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE invoices
            SET status = 'CREATED', paypal_order_id = ?, approval_url = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (order_id, approval_url, now_iso(), invoice_id),
        )


def set_status(
    invoice_id: int,
    status: str,
    *,
    capture_id: str | None = None,
) -> None:
    stamp = now_iso()
    paid_at = stamp if status == "COMPLETED" else ""
    with connect() as conn:
        if capture_id:
            conn.execute(
                """
                UPDATE invoices
                SET status = ?, capture_id = ?, paid_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, capture_id, paid_at, stamp, invoice_id),
            )
        elif status == "COMPLETED":
            conn.execute(
                """
                UPDATE invoices
                SET status = ?, paid_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, paid_at, stamp, invoice_id),
            )
        else:
            conn.execute(
                "UPDATE invoices SET status = ?, updated_at = ? WHERE id = ?",
                (status, stamp, invoice_id),
            )


def stats() -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT currency, status, COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS cents "
            "FROM invoices GROUP BY currency, status"
        ).fetchall()
        overdue = conn.execute(
            "SELECT COUNT(*) AS n FROM invoices "
            "WHERE status IN ('CREATED', 'APPROVED') "
            "AND due_date != '' AND date(due_date) < date('now')"
        ).fetchone()["n"]
    by_currency: dict[str, dict[str, int]] = {}
    awaiting = 0
    for row in rows:
        currency = row["currency"]
        bucket = by_currency.setdefault(
            currency, {"outstanding_cents": 0, "paid_cents": 0, "count": 0}
        )
        bucket["count"] += int(row["n"])
        if row["status"] in ("CREATED", "APPROVED"):
            bucket["outstanding_cents"] += int(row["cents"])
            awaiting += int(row["n"])
        elif row["status"] == "COMPLETED":
            bucket["paid_cents"] += int(row["cents"])
    return {
        "count": sum(item["count"] for item in by_currency.values()),
        "awaiting_count": awaiting,
        "overdue_count": int(overdue),
        "by_currency": by_currency,
    }



def money(cents: int, currency: str = "MYR") -> str:
    return f"{cents / 100:,.2f} {currency}"


def is_overdue(invoice: sqlite3.Row) -> bool:
    if invoice["status"] not in ("CREATED", "APPROVED"):
        return False
    due = invoice["due_date"]
    return bool(due and due < datetime.now().date().isoformat())

