-- HushMoney — SQLite Schema
-- Managed by Hermes Agent. Apply via: sqlite3 $DB_PATH < config/schema.sql
-- All timestamps are ISO 8601 UTC strings.
-- All amounts are stored as REAL in the account's native currency (no conversion).

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ── Accounts ───────────────────────────────────────────────────────────────
-- A user's bank accounts, digital wallets, and credit lines.
-- Cards are linked to accounts; transactions are linked to accounts (and
-- optionally to a specific card).

CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    bank          TEXT NOT NULL,        -- slug: 'bancolombia', 'davivienda', 'nequi'
    alias         TEXT,                 -- user label: "Mi cuenta de ahorros"
    type          TEXT NOT NULL,        -- checking | savings | credit | digital_wallet
    currency      TEXT NOT NULL,        -- 'COP', 'USD'
    masked_number TEXT,                 -- as it appears in notifications: '****1234'
    created_at    TEXT NOT NULL
);

-- ── Cards ──────────────────────────────────────────────────────────────────
-- Physical or virtual cards linked to an account.
-- One account can have many cards; each card belongs to exactly one account.

CREATE TABLE IF NOT EXISTS cards (
    id            TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    type          TEXT NOT NULL,        -- debit | credit
    masked_number TEXT,                 -- '****5678'
    alias         TEXT,                 -- "Visa débito verde"
    created_at    TEXT NOT NULL
);

-- ── Transactions ───────────────────────────────────────────────────────────
-- Every financial movement captured by the system.
-- Always linked to an account; linked to a card only when the notification
-- identifies one (purchases). Wire transfers and direct account operations
-- leave card_id NULL.

CREATE TABLE IF NOT EXISTS transactions (
    id               TEXT PRIMARY KEY,  -- UUID v4
    account_id       TEXT NOT NULL REFERENCES accounts(id),
    card_id          TEXT REFERENCES cards(id),     -- NULL for account-level ops
    amount           REAL NOT NULL,
    currency         TEXT NOT NULL,
    merchant         TEXT,                           -- NULL for transfers
    date             TEXT NOT NULL,                 -- ISO 8601 UTC
    transaction_type TEXT NOT NULL,                 -- debit | credit | cash |
                                                    -- transfer_in | transfer_out |
                                                    -- payment | top_up
    channel          TEXT NOT NULL,                 -- email | sms | telegram
    category         TEXT REFERENCES categories(slug), -- set by categorizer skill
    description      TEXT,                          -- user-provided or inferred
    is_recurring     INTEGER NOT NULL DEFAULT 0,    -- 1 if categorizer flags as subscription
    message_hash     TEXT UNIQUE,                   -- SHA256(amount+date+type+masked_number)
                                                    -- prevents duplicate entries from
                                                    -- notification retries or double-forwards
    template_id      TEXT,                          -- e.g. "bancolombia.debit_checking" or
                                                    -- "learned:42"; NULL for legacy rows
    pattern_status   TEXT NOT NULL DEFAULT 'active', -- 'active' | 'candidate'
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL                  -- updated when user corrects a field
);

CREATE INDEX IF NOT EXISTS idx_transactions_account  ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_card     ON transactions(card_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date     ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);

-- ── Debts ──────────────────────────────────────────────────────────────────
-- People the user owes money to, or who owe the user money.
-- When settled via a tracked transfer, settled_by_transaction_id links to it
-- so summaries can say "settled via transfer on DD/MM" instead of just a date.

CREATE TABLE IF NOT EXISTS debts (
    id                        TEXT PRIMARY KEY,
    person                    TEXT NOT NULL,
    amount                    REAL NOT NULL,
    currency                  TEXT NOT NULL,
    direction                 TEXT NOT NULL,    -- 'i_owe' | 'they_owe'
    description               TEXT,
    created_at                TEXT NOT NULL,
    settled_at                TEXT,             -- NULL = still active
    settled_by_transaction_id TEXT REFERENCES transactions(id)
                                                -- NULL if settled outside the system
                                                -- or not yet settled
);

CREATE INDEX IF NOT EXISTS idx_debts_person ON debts(person);

-- ── Learned Patterns ───────────────────────────────────────────────────────
-- Bank notification patterns discovered at runtime by the bank_learning skill.
-- These extend the community patterns compiled from tests/fixtures/ at deploy time.
-- 'active = 0' disables a pattern when a bank changes its notification template
-- without deleting the history of what the pattern was.

CREATE TABLE IF NOT EXISTS learned_patterns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_slug   TEXT NOT NULL,          -- 'davivienda', 'bbva', etc.
    country     TEXT NOT NULL,          -- 'CO', 'US'
    channel     TEXT NOT NULL,          -- 'email' | 'sms'
    pattern     TEXT NOT NULL,          -- JSON: field extraction rules
    confirmed   INTEGER NOT NULL DEFAULT 0,  -- 1 = user confirmed at least once
    uses        INTEGER NOT NULL DEFAULT 0,  -- successful applications
    active      INTEGER NOT NULL DEFAULT 1,  -- 0 = disabled (bank changed format)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_patterns_bank    ON learned_patterns(bank_slug, country, channel);
CREATE INDEX IF NOT EXISTS idx_patterns_active  ON learned_patterns(active);

-- ── Categories ─────────────────────────────────────────────────────────────────
-- Canonical spending category list. Seeded on first run from default_categories.json.
-- Users can add/remove via Telegram: "hermes add category gambling".

CREATE TABLE IF NOT EXISTS categories (
    slug        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL
);

-- ── Merchants ──────────────────────────────────────────────────────────────────
-- Merchant → category cache. Populated on first transaction from each merchant
-- via LLM inference. The cache key is the normalized bank-emitted string
-- (UPPER + whitespace-collapsed), so "UBER RIDES" and "UBER EATS" are separate
-- entries — each bank emits a consistent string for the same merchant.
--
-- needs_clarification=1: merchant is a payment gateway or multi-service platform
--   (e.g. RAPPI, PEXTO CAPITAL SAS). Each transaction prompts the user to confirm.
-- last_category: most recent user-confirmed category for ambiguous merchants,
--   used to pre-fill the clarification prompt.

CREATE TABLE IF NOT EXISTS merchants (
    name                TEXT PRIMARY KEY,
    category            TEXT REFERENCES categories(slug),
    needs_clarification INTEGER NOT NULL DEFAULT 0,
    last_category       TEXT REFERENCES categories(slug),
    is_recurring        INTEGER NOT NULL DEFAULT 0,  -- set once ≥4 months of same-day charges seen
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_merchants_category ON merchants(category);

-- ── User Settings ──────────────────────────────────────────────────────────────
-- Key/value store for user preferences and setup state.
-- Keys: setup_complete, setup_step, email_provider, imap_host, imap_port,
--       imap_username, bank_sender_emails, locale, sms_channel_enabled.

CREATE TABLE IF NOT EXISTS user_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
