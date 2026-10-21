# setup skill

One-time guided onboarding through Telegram. Configures the email channel (IMAP) and,
optionally, SMS forwarding. Runs once; afterwards it only answers "you're already set up"
until the user sends `/reset-setup`.

## Inputs

- `/start`, or any message while `user_settings.setup_complete` is not `"true"`
- The user's answers during the conversation (provider, email address, App Password,
  bank sender addresses, phone type)

## Normal flow

1. `seed_defaults` — create the settings rows if missing and read `setup_step`, so an
   interrupted setup resumes where it stopped
2. Welcome message
3. Email provider:
   - Gmail / Yahoo → IMAP with an App Password
   - Outlook → server-side forwarding rule to a Gmail or Yahoo address (Outlook IMAP
     needs an Azure AD app — too complex)
   - Other → ask for IMAP host and port
4. Bank sender addresses (the "From" of a bank e-mail)
5. `check_imap` — test login and count unread bank e-mails
6. `save_email_config` — store the non-secret configuration
7. Optional SMS channel (iPhone Shortcut or Android template)
8. `mark_setup_complete`

## Settings

Stored in `user_settings` (key/value):

| Key | Example |
|---|---|
| `setup_complete` | `"true"` / `"false"` |
| `setup_step` | `start`, `email_provider`, `email_credentials`, `email_senders`, `sms`, `done` |
| `email_provider` | `gmail`, `yahoo`, `outlook_forward`, `other` |
| `imap_host`, `imap_port`, `imap_username` | `imap.gmail.com`, `993`, `user@gmail.com` |
| `bank_sender_emails` | comma-separated list |
| `sms_channel_enabled` | `"true"` / `"false"` |
| `locale` | ISO country code, e.g. `"CO"` — used by `bank_learning` for date formats |
| `timezone` | IANA name, default `America/Bogota` — used by `summaries` |

## Tools this skill uses

### `seed_defaults`
```sql
INSERT OR IGNORE INTO user_settings (key, value, updated_at) VALUES (?, ?, ?);
SELECT key, value FROM user_settings;
```
Also applies `config/schema.sql` on a fresh database.

### `save_setting` / `save_email_config` / `mark_setup_complete`
```sql
INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
```

### `check_imap`

Connects with the credentials the user just typed; never stores them. Returns
`success`, or `error: auth | connection | sender_not_found`.

## What NOT to do

- Do not store, log or repeat the IMAP password — it stays in `.env` only
- Do not suggest enabling Outlook IMAP directly
- Do not tell users that manual "Forward" works — it loses the bank's sender headers;
  only server-side forwarding rules preserve them
- Do not re-run setup when `setup_complete == "true"` unless the user sends `/reset-setup`
