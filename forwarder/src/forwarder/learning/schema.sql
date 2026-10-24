PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS learned_banks (
    slug                TEXT PRIMARY KEY,
    country             TEXT NOT NULL,
    currency            TEXT NOT NULL,
    thousands_separator TEXT NOT NULL,
    decimal_separator   TEXT NOT NULL,
    utc_offset_minutes  INTEGER NOT NULL,
    sms_prefix          TEXT,
    email_senders       TEXT NOT NULL DEFAULT '[]',
    app_names           TEXT NOT NULL DEFAULT '[]',
    date_regex          TEXT NOT NULL,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learned_patterns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_slug         TEXT NOT NULL,
    channel           TEXT NOT NULL,
    template_key      TEXT NOT NULL,
    transaction_type  TEXT NOT NULL,
    account_type      TEXT NOT NULL,
    regex             TEXT NOT NULL,
    date_regex        TEXT,
    synthetic_sample  TEXT NOT NULL,
    synthetic_expected TEXT NOT NULL,
    fingerprint       TEXT NOT NULL,
    status            TEXT NOT NULL,
    uses              INTEGER NOT NULL DEFAULT 0,
    distinct_uses     INTEGER NOT NULL DEFAULT 0,
    last_use_hash     TEXT,
    corrections       INTEGER NOT NULL DEFAULT 0,
    proposal_id       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE (bank_slug, channel, template_key)
);
CREATE INDEX IF NOT EXISTS idx_lp_status ON learned_patterns(status);

CREATE TABLE IF NOT EXISTS fingerprints (
    fingerprint    TEXT PRIMARY KEY,
    bank_slug      TEXT,
    channel        TEXT NOT NULL,
    state          TEXT NOT NULL,
    hits           INTEGER NOT NULL DEFAULT 1,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    last_forwarded TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    codes       TEXT NOT NULL,
    received_at TEXT NOT NULL
);

-- Append-only log of learning forwards, used to rate-limit per hour. Survives
-- restarts (the previous in-memory counter did not). Pruned to the last hour on
-- each insert.
CREATE TABLE IF NOT EXISTS forward_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    forwarded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forward_log_ts ON forward_log(forwarded_at);
