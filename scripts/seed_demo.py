"""
Seed the HushMoney SQLite database with realistic demo data.

Run inside the hermes container:
  docker exec hermes python3 /tmp/seed_demo.py

Or via seed_demo.sh from the repo root (handles the copy + exec).

Idempotent: safe to run multiple times — existing rows are skipped.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime

DB_PATH = os.environ.get("HUSHMONEY_DB", os.path.expanduser("~/.hermes/hushmoney.db"))
SCHEMA_PATH = os.environ.get("HUSHMONEY_SCHEMA", "/app/config/schema.sql")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash(*parts: object) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()


def _ensure_schema(con: sqlite3.Connection) -> None:
    if os.path.isfile(SCHEMA_PATH):
        con.executescript(open(SCHEMA_PATH).read())


def _upsert_setting(con: sqlite3.Connection, key: str, value: str, now: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, now),
    )


def _find_or_create_account(
    con: sqlite3.Connection,
    bank: str,
    account_type: str,
    currency: str,
    alias: str,
    masked_number: str,
    now: str,
) -> str:
    row = con.execute(
        "SELECT id FROM accounts WHERE bank = ? AND type = ? AND currency = ? LIMIT 1",
        (bank, account_type, currency),
    ).fetchone()
    if row:
        return str(row[0])
    account_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO accounts (id, bank, alias, type, currency, masked_number, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account_id, bank, alias, account_type, currency, masked_number, now),
    )
    return account_id


def _insert_tx(
    con: sqlite3.Connection,
    account_id: str,
    amount: float,
    tx_type: str,
    date: str,
    merchant: str | None,
    category: str | None,
    channel: str,
    is_recurring: int,
    description: str | None,
    now: str,
    card_id: str | None = None,
) -> None:
    h = _hash(amount, date, tx_type, account_id, merchant or "")
    exists = con.execute(
        "SELECT 1 FROM transactions WHERE message_hash = ? LIMIT 1", (h,)
    ).fetchone()
    if exists:
        return
    con.execute(
        """INSERT INTO transactions
           (id, account_id, card_id, amount, currency, merchant, date,
            transaction_type, channel, category, description, is_recurring,
            message_hash, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'COP', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()), account_id, card_id, amount, merchant, date,
            tx_type, channel, category, description, is_recurring, h, now, now,
        ),
    )


def _insert_debt(
    con: sqlite3.Connection,
    person: str,
    amount: float,
    currency: str,
    direction: str,
    description: str,
    created_at: str,
    settled_at: str | None = None,
) -> None:
    exists = con.execute(
        "SELECT 1 FROM debts WHERE person = ? AND amount = ? AND direction = ? AND description = ? LIMIT 1",
        (person, amount, direction, description),
    ).fetchone()
    if exists:
        return
    con.execute(
        """INSERT INTO debts (id, person, amount, currency, direction, description, created_at, settled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), person, amount, currency, direction, description, created_at, settled_at),
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    _ensure_schema(con)
    now = datetime.now(UTC).isoformat()

    with con:
        # ── Accounts ──────────────────────────────────────────────────────────
        checking_id = _find_or_create_account(
            con, "bancolombia", "checking", "COP",
            "Cuenta de Ahorros", "****3421", now,
        )
        credit_id = _find_or_create_account(
            con, "bancolombia", "credit", "COP",
            "Tarjeta Visa", "****8874", now,
        )
        nequi_id = _find_or_create_account(
            con, "nequi", "digital_wallet", "COP",
            "Nequi", "****1190", now,
        )

        # ── Settings ──────────────────────────────────────────────────────────
        _upsert_setting(con, "setup_complete", "true", now)
        _upsert_setting(con, "setup_step", "done", now)
        _upsert_setting(con, "accounts_configured", "true", now)
        _upsert_setting(con, "sms_channel_enabled", "true", now)
        _upsert_setting(con, "locale", "es-CO", now)

        # ── Transactions — August 2026 ─────────────────────────────────────
        _insert_tx(con, checking_id, 3_800_000, "credit", "2026-08-01T08:00:00Z",
                   None, "other", "email", 0, "Nómina agosto", now)
        _insert_tx(con, credit_id,   18_500,   "debit",  "2026-08-02T13:22:00Z",
                   "STARBUCKS", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   8_900,    "debit",  "2026-08-03T07:48:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, credit_id,   17_900,   "debit",  "2026-08-04T02:00:00Z",
                   "NETFLIX", "entertainment", "email", 1, None, now)
        _insert_tx(con, credit_id,   10_900,   "debit",  "2026-08-04T03:00:00Z",
                   "SPOTIFY", "entertainment", "email", 1, None, now)
        _insert_tx(con, credit_id,   89_900,   "debit",  "2026-08-05T10:00:00Z",
                   "SMARTFIT", "health", "email", 1, None, now)
        _insert_tx(con, credit_id,   124_500,  "debit",  "2026-08-07T18:30:00Z",
                   "EXITO", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   34_200,   "debit",  "2026-08-09T12:15:00Z",
                   "RAPPI", "food", "sms", 0, None, now)
        _insert_tx(con, checking_id, 200_000,  "transfer_out", "2026-08-10T16:00:00Z",
                   None, "transfers", "email", 0, "Transferencia a Nequi", now)
        _insert_tx(con, nequi_id,    200_000,  "transfer_in",  "2026-08-10T16:01:00Z",
                   None, "transfers", "sms", 0, "Recibido de Bancolombia", now)
        _insert_tx(con, credit_id,   15_000,   "debit",  "2026-08-11T08:10:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, checking_id, 300_000,  "cash",   "2026-08-12T11:00:00Z",
                   "CAJERO BANCOLOMBIA", "cash", "sms", 0, None, now)
        _insert_tx(con, credit_id,   45_000,   "debit",  "2026-08-13T20:00:00Z",
                   "CLARO", "services", "email", 1, "Plan de datos", now)
        _insert_tx(con, credit_id,   28_000,   "debit",  "2026-08-14T13:45:00Z",
                   "EL CORRAL", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   67_500,   "debit",  "2026-08-16T17:20:00Z",
                   "D1", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   189_900,  "debit",  "2026-08-18T15:00:00Z",
                   "ZARA", "shopping", "sms", 0, None, now)
        _insert_tx(con, credit_id,   22_000,   "debit",  "2026-08-20T19:30:00Z",
                   "RAPPI", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   12_500,   "debit",  "2026-08-22T07:55:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, credit_id,   156_000,  "debit",  "2026-08-25T18:00:00Z",
                   "JUMBO", "food", "sms", 0, None, now)
        _insert_tx(con, nequi_id,    35_000,   "debit",  "2026-08-28T21:10:00Z",
                   None, "transfers", "sms", 0, "Pago a Carlos - cena", now)

        # ── Transactions — September 2026 ─────────────────────────────────
        _insert_tx(con, checking_id, 3_800_000, "credit", "2026-09-01T08:00:00Z",
                   None, "other", "email", 0, "Nómina septiembre", now)
        _insert_tx(con, credit_id,   17_900,   "debit",  "2026-09-04T02:00:00Z",
                   "NETFLIX", "entertainment", "email", 1, None, now)
        _insert_tx(con, credit_id,   10_900,   "debit",  "2026-09-04T03:00:00Z",
                   "SPOTIFY", "entertainment", "email", 1, None, now)
        _insert_tx(con, credit_id,   89_900,   "debit",  "2026-09-05T10:00:00Z",
                   "SMARTFIT", "health", "email", 1, None, now)
        _insert_tx(con, credit_id,   11_000,   "debit",  "2026-09-06T09:20:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, credit_id,   42_000,   "debit",  "2026-09-07T13:00:00Z",
                   "RESTAURANTE ANDRÉS DC", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   98_700,   "debit",  "2026-09-09T19:00:00Z",
                   "EXITO", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   45_000,   "debit",  "2026-09-13T20:00:00Z",
                   "CLARO", "services", "email", 1, "Plan de datos", now)
        _insert_tx(con, checking_id, 150_000,  "transfer_out", "2026-09-15T10:00:00Z",
                   None, "transfers", "email", 0, "Transferencia a Nequi", now)
        _insert_tx(con, nequi_id,    150_000,  "transfer_in",  "2026-09-15T10:01:00Z",
                   None, "transfers", "sms", 0, "Recibido de Bancolombia", now)
        _insert_tx(con, credit_id,   320_000,  "debit",  "2026-09-17T16:30:00Z",
                   "ALKOSTO", "shopping", "sms", 0, "Audífonos Sony", now)
        _insert_tx(con, credit_id,   18_000,   "debit",  "2026-09-19T08:05:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, checking_id, 200_000,  "cash",   "2026-09-20T11:30:00Z",
                   "CAJERO BANCOLOMBIA", "cash", "sms", 0, None, now)
        _insert_tx(con, credit_id,   55_000,   "debit",  "2026-09-21T14:00:00Z",
                   "RAPPI", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   134_000,  "debit",  "2026-09-24T17:45:00Z",
                   "D1", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   75_000,   "debit",  "2026-09-26T21:00:00Z",
                   "CINE COLOMBIA", "entertainment", "sms", 0, "Entradas cine x2", now)
        _insert_tx(con, nequi_id,    120_000,  "debit",  "2026-09-28T17:00:00Z",
                   None, "transfers", "sms", 0, "Pago a María - entrada concierto", now)

        # ── Transactions — October 2026 ────────────────────────────────────
        _insert_tx(con, checking_id, 3_800_000, "credit", "2026-10-01T08:00:00Z",
                   None, "other", "email", 0, "Nómina octubre", now)
        _insert_tx(con, credit_id,   17_900,   "debit",  "2026-10-04T02:00:00Z",
                   "NETFLIX", "entertainment", "email", 1, None, now)
        _insert_tx(con, credit_id,   10_900,   "debit",  "2026-10-04T03:00:00Z",
                   "SPOTIFY", "entertainment", "email", 1, None, now)
        _insert_tx(con, credit_id,   89_900,   "debit",  "2026-10-05T10:00:00Z",
                   "SMARTFIT", "health", "email", 1, None, now)
        _insert_tx(con, credit_id,   45_000,   "debit",  "2026-10-05T20:00:00Z",
                   "CLARO", "services", "email", 1, "Plan de datos", now)
        _insert_tx(con, credit_id,   9_500,    "debit",  "2026-10-06T08:30:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, credit_id,   22_000,   "debit",  "2026-10-07T13:10:00Z",
                   "STARBUCKS", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   112_000,  "debit",  "2026-10-08T18:00:00Z",
                   "JUMBO", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   38_000,   "debit",  "2026-10-10T13:30:00Z",
                   "RAPPI", "food", "sms", 0, None, now)
        _insert_tx(con, checking_id, 100_000,  "transfer_out", "2026-10-12T09:00:00Z",
                   None, "transfers", "email", 0, "Transferencia a Nequi", now)
        _insert_tx(con, nequi_id,    100_000,  "transfer_in",  "2026-10-12T09:01:00Z",
                   None, "transfers", "sms", 0, "Recibido de Bancolombia", now)
        _insert_tx(con, credit_id,   16_000,   "debit",  "2026-10-14T07:50:00Z",
                   "UBER", "transport", "sms", 0, None, now)
        _insert_tx(con, credit_id,   87_500,   "debit",  "2026-10-15T17:30:00Z",
                   "EXITO", "food", "sms", 0, None, now)
        _insert_tx(con, credit_id,   24_000,   "debit",  "2026-10-17T19:00:00Z",
                   "EL CORRAL", "food", "sms", 0, None, now)
        _insert_tx(con, checking_id, 200_000,  "cash",   "2026-10-18T10:45:00Z",
                   "CAJERO BANCOLOMBIA", "cash", "sms", 0, None, now)
        _insert_tx(con, credit_id,   14_500,   "debit",  "2026-10-20T08:20:00Z",
                   "UBER", "transport", "sms", 0, None, now)

        # ── Debts ──────────────────────────────────────────────────────────
        _insert_debt(con, "Carlos", 50_000, "COP", "they_owe",
                     "Mitad del almuerzo — La Fragata", "2026-10-14T14:00:00Z")
        _insert_debt(con, "María", 120_000, "COP", "i_owe",
                     "Entrada concierto Feid", "2026-09-28T17:00:00Z")
        _insert_debt(con, "Sofía", 200_000, "COP", "they_owe",
                     "Préstamo fin de semana", "2026-10-05T20:00:00Z")

    # ── Summary ────────────────────────────────────────────────────────────────
    row = con.execute("SELECT COUNT(*) FROM transactions").fetchone()
    print(json.dumps({
        "ok": True,
        "transactions": row[0],
        "accounts": con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
        "debts": con.execute("SELECT COUNT(*) FROM debts").fetchone()[0],
    }))
    con.close()


if __name__ == "__main__":
    main()
