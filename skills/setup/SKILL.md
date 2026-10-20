---
name: setup
description: One-time guided onboarding via Telegram
version: 0.2.0
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

1. Run: `python3 skills/setup/scripts/seed_defaults.py`
2. Parse the JSON output. If `setup_complete` is `"true"`:
   - Reply: "You're already set up! Send me a transaction or ask for a summary."
   - Stop.
3. Read `setup_step` from output to resume a partial setup (values: `start`,
   `email_provider`, `email_credentials`, `email_senders`, `sms`, `done`).

---

### Step 1 — Welcome

Send the contents of `skills/setup/templates/welcome.md` verbatim.
Wait for the user to reply with any message before proceeding.

---

### Step 2 — Email channel

Save progress: `python3 skills/setup/scripts/save_setting.py setup_step email_provider`

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

Save progress: `python3 skills/setup/scripts/save_setting.py setup_step email_senders`

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
python3 skills/setup/scripts/check_imap.py \
  --host [host] --port [port] \
  --username [username] --password [password] \
  --senders "[comma-separated senders]"
```

Parse JSON output:
- `success: true` → tell user: "✅ Connected successfully! I can see your inbox."
  - If `unseen_from_bank > 0`: "I can already see [N] unread bank emails. I'll process them now."
- `success: false, error: "auth"` → "❌ Login failed. Double-check your App Password is correct and IMAP is enabled."
  Offer to retry (go back to password question, max 3 attempts then abort).
- `success: false, error: "connection"` → "❌ Could not reach [host]. Check the hostname and try again."
- `success: false, error: "sender_not_found"` → "⚠️ Connected, but I didn't find any emails from those senders in your inbox.
  That's OK — I'll start capturing them as they arrive. If you want, forward yourself a recent bank email to test."

On success, run:
```
python3 skills/setup/scripts/save_email_config.py \
  --provider [gmail|yahoo|outlook_forward|other] \
  --host [host] --port [port] \
  --username [username] \
  --bank-senders "[comma-separated senders]"
```

Then tell the user:
> ✅ Email channel is configured. Add these values to your `.env` file:
> ```
> IMAP_HOST=[host]
> IMAP_PORT=[port]
> IMAP_USERNAME=[username]
> IMAP_PASSWORD=<the App Password you entered>
> BANK_SENDER_EMAILS=[senders]
> ```
> Then run `./scripts/setup.sh` to apply.

---

### Step 3 — SMS channel

Save progress: `python3 skills/setup/scripts/save_setting.py setup_step sms`

Ask:
> Would you also like to set up SMS forwarding? This lets me capture bank
> text messages automatically, without you having to do anything.
>
> 1. Yes — set it up now
> 2. Skip — I'll do this later

If skip → go to Step 4.

Ask: "What phone do you use?"
> 1. iPhone
> 2. Android
> 3. Both

#### iPhone

Send `skills/setup/templates/sms_iphone.md`.
After sending, ask: "Reply when you've set up the Shortcut and I'll confirm it's
working by asking you to trigger it."
Wait for confirmation, then say: "Great — if you triggered the Shortcut and I
received a message, SMS forwarding is active."

#### Android

Send `skills/setup/templates/sms_android.md`.

---

### Step 4 — Complete

Run: `python3 skills/setup/scripts/mark_setup_complete.py`

Send:
> 🎉 Setup complete! Here's what's active:
> - **Email**: watching [username] for emails from [senders]
> - **SMS**: [configured / not configured]
>
> I'll notify you on Telegram when I capture a transaction. You can also ask me:
> - "How much did I spend this week?"
> - "I paid dinner for João — he owes me $35"
> - "Show my monthly summary"

## Pitfalls

- **Never log or repeat passwords.** The IMAP password is used once for
  `check_imap.py` and `save_email_config.py` does NOT store it. If Hermes
  needs to test again, ask the user to re-enter it.
- **Outlook IMAP is disabled by default** and requires an Azure AD app to
  enable — far too complex for this setup. Always redirect Outlook users to
  set up a forwarding rule to Gmail or Yahoo. Do not suggest enabling
  Outlook IMAP directly.
- **Manual forwarding breaks sender detection.** When a user manually clicks
  "Forward" in their email client, the original bank sender headers are
  lost and the forwarder sees the user's own address. Only server-side
  forwarding rules (Outlook rules, Gmail filters) preserve the headers.
  Make this clear if the user asks.
- **iPhone Shortcuts "Send Message" action sends iMessage**, not Telegram.
  The correct action is "Get Contents of URL" calling the Telegram Bot API.
  See `sms_iphone.md` for the exact configuration.

## Verification

After setup:
- `user_settings.setup_complete == "true"`
- `user_settings.email_provider` is set
- `user_settings.imap_username` is set
- `user_settings.bank_sender_emails` is set
