---
name: setup
description: One-time guided onboarding via Telegram
version: 0.3.0
author: hushmoney
metadata:
  hermes:
    tags: [Setup, Onboarding]
    category: hushmoney
    requires_tools: [terminal]
---

# Setup

## When to Use

Triggered by `/start` or any message from a user whose `setup_complete` setting
is not `"true"`. Run `seed_defaults.py` first to ensure the settings rows exist.
Skip the entire skill if `setup_complete == "true"` (setup already done).
The user can restart by sending `/reset-setup`.

## Procedure

### Step 0 — Init and guard

1. Run: `python3 /root/.hermes/skills/hushmoney/setup/scripts/seed_defaults.py`
2. Parse the JSON output. If `setup_complete` is `"true"`:
   - Reply: "You're already set up! Send me a transaction or ask for a summary."
   - Stop.
3. Read `setup_step` from output to resume a partial setup (values: `start`,
   `email_provider`, `email_credentials`, `email_senders`, `accounts`, `sms`, `done`).
4. Run: `python3 /root/.hermes/skills/hushmoney/setup/scripts/load_accounts_md.py`
   - If `ready: false` → continue normally (user will fill accounts interactively in Step 3).
   - If `ready: true` → tell the user:
     > ✅ Found your pre-filled accounts file — loaded [N] account(s) automatically.
     > [List each: bank / type / alias]
     Then run: `python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py accounts_configured true`
     Skip Step 3 entirely (jump to Step 4).

---

### Step 1 — Welcome

Send the contents of `skills/setup/templates/welcome.md` verbatim, then add:

> How would you like to get started?
>
> 1. Full setup — configure email + accounts + SMS
> 2. Accounts only — skip email, just register your accounts
>
> Reply 1 or 2.

- If the user replies **2**: skip directly to Step 3 (Accounts).
- Otherwise: continue to Step 2.

---

### Step 2 — Email channel

Save progress: `python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py setup_step email_provider`

Ask the user (send exactly this, as a numbered list):

> Which email provider receives your bank's notification emails?
>
> 1. Gmail
> 2. Yahoo Mail
> 3. Outlook / Microsoft 365
> 4. Other

Wait for the reply. Match loosely: "1", "gmail", "Google" → Gmail, etc.

#### Branch: Gmail or Yahoo

- Gmail → host: `imap.gmail.com`, port: `993`
- Yahoo → host: `imap.mail.yahoo.com`, port: `993`

1. Send the appropriate template:
   - Gmail: `skills/setup/templates/email_gmail.md`
   - Yahoo: `skills/setup/templates/email_yahoo.md`
2. Ask: "What is your email address?"
3. Ask: "Paste your App Password here. It's 16 characters with no spaces."
   - **Do not log or repeat the password back to the user.**
4. Proceed to Step 2c (bank senders).

#### Branch: Outlook / Microsoft 365

Send `skills/setup/templates/email_outlook.md`.

Ask: "Once the forwarding rule is active, which Gmail or Yahoo address will
receive the forwarded bank emails?"

When they reply with an email address, detect the provider from the domain
(`gmail.com` → Gmail, `yahoo.com` / `ymail.com` → Yahoo) and branch into
the Gmail or Yahoo flow above for that address.

#### Branch: Other

Ask: "What is your IMAP server hostname? (e.g. `imap.example.com`)"
Ask: "What port does it use? (Press Enter to use the default: 993)"
Ask: "What is your email address?"
Ask: "What is your password or App Password?"

#### Step 2c — Bank sender emails

Save progress: `python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py setup_step email_senders`

Ask:
> What are the sender addresses your bank uses for email notifications?
> Separate multiple addresses with commas.
>
> Example: `alertasynotificaciones@ayn.notificacionesbancolombia.com`
>
> Tip: forward yourself a bank email, open it, and check the "From" field.

#### Step 2d — Test the connection

Run:
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/check_imap.py \
  --host [host] --port [port] \
  --username [username] --password [password] \
  --senders "[comma-separated senders]"
```

Parse JSON output:
- `success: true` → tell user: "✅ Connected successfully! I can see your inbox."
  - If `unseen_from_bank > 0`: "I can already see [N] unread bank emails."
- `success: false, error: "auth"` → "❌ Login failed. Check your App Password and try again."
  Offer to retry (max 3 attempts then abort).
- `success: false, error: "connection"` → "❌ Could not reach [host]. Check the hostname."
- `success: false, error: "sender_not_found"` → "⚠️ Connected, but no emails from those senders yet. I'll capture them as they arrive."

On success, run:
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/save_email_config.py \
  --provider [gmail|yahoo|outlook_forward|other] \
  --host [host] --port [port] \
  --username [username] \
  --bank-senders "[comma-separated senders]"
```

Then tell the user:
> ✅ Email channel configured. I've saved your settings and will start watching
> [username] for emails from your bank.

Do NOT tell the user to run any commands or edit any files. The configuration
is already saved internally.

---

### Step 3 — Accounts

Save progress: `python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py setup_step accounts`

Tell the user:
> Now let's map your bank accounts. I'll use this to match transaction notifications
> to the right account and give you cleaner summaries.

Ask (send as a numbered list):
> Which banks do you have accounts with? Reply with the numbers separated by commas.
>
> 1. Bancolombia
> 2. Davivienda
> 3. Nequi
> 4. BBVA Colombia
> 5. Other

Map answers to slugs: `bancolombia`, `davivienda`, `nequi`, `bbva`. For "Other", ask for
the bank name and use it lowercased with no spaces as the slug.

For **each selected bank**, ask:
> What types of accounts do you have with [Bank]? (Reply with numbers, comma-separated)
>
> 1. Checking / Savings (cuenta de ahorros / corriente)
> 2. Credit card
> 3. Digital wallet (Nequi, Daviplata, etc.)

Map to type values: `1` → `checking`, `2` → `credit`, `3` → `digital_wallet`.

For **each account**, collect the following — ask each question separately, one at a time:

**Question A — Account number (last 4)**
> What are the last 4 digits of the account number shown in [Bank] notifications?
> (e.g. if transfers show "Cta ****1234", type 1234 — type "skip" to leave blank)

Store as `masked_account`.

**Question B — Card number (last 4), only for `checking` and `credit` types**
> What are the last 4 digits of the card linked to this account?
> (e.g. if purchases show "Tarjeta ****5678", type 5678 — type "skip" to leave blank)
>
> Note: these are usually different from the account digits above. Both are
> needed to match purchases (card) vs. transfers (account).

Store as `masked_card`.

**Question C — Currency**
> What currency is this account in? (Press Enter for COP)
>
> Common options: COP, USD, EUR

Use the user's answer uppercased, defaulting to `COP` if blank.

**Question D — Nickname**
> Give this account a nickname so I can refer to it in summaries.
> (e.g. "Bancolombia débito", "Visa gold", or press Enter to skip)

For each account, run:
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/save_accounts.py \
  --bank <slug> \
  --type <type> \
  --currency <currency> \
  [--masked-number "****XXXX"] \
  [--card-masked-number "****YYYY"] \
  [--alias "<nickname>"]
```

- Use `--masked-number` for the account number (Question A). Omit if skipped.
- Use `--card-masked-number` for the card number (Question B). Omit if skipped.
- Omit `--alias` if blank.

After all accounts are saved, run:
```
python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py accounts_configured true
```

Tell the user:
> ✅ Saved [N] account(s). I'll automatically match incoming transactions to these.

---

### Step 4 — SMS channel

Save progress: `python3 /root/.hermes/skills/hushmoney/setup/scripts/save_setting.py setup_step sms`

Ask:
> Would you also like to set up SMS forwarding? This lets me capture bank
> text messages automatically, without you having to do anything.
>
> 1. Yes — set it up now
> 2. Skip — I'll do this later

If skip → go to Step 5.

Ask: "What phone do you use?"
> 1. iPhone
> 2. Android
> 3. Both

#### iPhone

Send `skills/setup/templates/sms_iphone.md`.
After sending, ask: "Reply when you've set up the Shortcut and I'll confirm it's working."
Wait for confirmation, then say: "Great — SMS forwarding is active."

#### Android

Send `skills/setup/templates/sms_android.md`.

---

### Step 5 — Complete

Run: `python3 /root/.hermes/skills/hushmoney/setup/scripts/mark_setup_complete.py`

Send:
> 🎉 Setup complete! Here's what's active:
> - **Email**: watching [username] for emails from [senders]
> - **Accounts**: [N] account(s) registered
> - **SMS**: [configured / not configured]
>
> I'll notify you on Telegram when I capture a transaction. You can also ask me:
> - "How much did I spend this week?"
> - "I paid dinner for João — he owes me $35"
> - "Show my monthly summary"

## Pitfalls

- **Never tell the user to run shell commands or edit config files.** All
  configuration is saved internally. The user never needs to touch `.env`,
  run scripts, or restart services.
- **Ask each question ONCE.** Do not send the same question twice. Use a
  single message per question — never repeat if the model already sent it.
- **Never log or repeat passwords.** The IMAP password is used once for
  `check_imap.py` and not stored.
- **Checking/savings accounts have two separate masked numbers**: the account
  number (used for transfers) and the card number (used for purchases). Both
  are needed to match all transaction types. Always ask for both for `checking`
  and `credit` types.
- **Outlook IMAP is disabled by default.** Always redirect Outlook users to
  set up a forwarding rule to Gmail or Yahoo.
- **iPhone Shortcuts "Send Message" sends iMessage**, not Telegram. The correct
  action is "Get Contents of URL" calling the Telegram Bot API.

## Verification

After setup:
- `user_settings.setup_complete == "true"`
- `user_settings.email_provider` is set (unless user chose accounts-only)
- `user_settings.accounts_configured == "true"`
- At least one row exists in the `accounts` table
