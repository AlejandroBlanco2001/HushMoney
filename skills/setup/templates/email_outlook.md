📧 **Outlook / Microsoft 365 — forwarding rule setup**

Outlook IMAP requires an Azure Active Directory app to enable — that's too complex for our purposes. Instead, we'll set up an **automatic forwarding rule** that sends your bank emails to a Gmail or Yahoo account. This takes about 2 minutes and works permanently without any manual effort.

⚠️ **Important — use a forwarding rule, not manual forwarding.**
When you manually click "Forward" on an email, the original bank sender is lost and I can't tell which bank it came from. A server-side rule preserves all the original headers automatically.

---

**Step 1: Create a Gmail or Yahoo account to receive forwarded emails**
If you already have one, skip this step.
- Gmail: accounts.google.com/signup
- Yahoo: login.yahoo.com/account/create

---

**Step 2: Set up the forwarding rule in Outlook**

1. Open Outlook Web (outlook.live.com or your Microsoft 365 portal)
2. Click ⚙️ → **View all Outlook settings** → **Mail** → **Rules**
3. Click **+ Add new rule**
4. Name it: `HushMoney — bank forwarding`
5. **Condition:** *From* → type your bank's sender domain (e.g. `notificacionesbancolombia.com`)
   - Add one condition per bank if you have multiple banks
6. **Action:** *Forward to* → enter your Gmail or Yahoo address
7. Click **Save**

---

**Step 3: Test it**
Wait for your next bank notification email, or ask your bank to resend a recent one.
It should appear in your Gmail/Yahoo inbox within a few seconds.

---

Once the rule is active, tell me which Gmail or Yahoo address will receive the forwarded emails and we'll finish the setup from there.
