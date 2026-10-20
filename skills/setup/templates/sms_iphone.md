📱 **iPhone SMS forwarding — Shortcuts automation**

This automation runs silently in the background. When your bank sends you an SMS, it automatically forwards the text to this bot — no tapping required.

**What you need:** iPhone with the Shortcuts app (pre-installed on iOS 13+) and Telegram.

---

**Step 1: Find your bank's SMS sender name or number**
Look at a recent bank SMS. The sender appears at the top — it's either a short number (e.g. `32424`) or a name (e.g. `Bancolombia`). Note it down.

---

**Step 2: Create the automation**

1. Open the **Shortcuts** app
2. Tap **Automation** (bottom tab) → **+** → **New Automation**
3. Scroll down and tap **Message**
4. Under *From*, tap **Choose** and enter your bank's sender name or number
5. Enable **Run Immediately** (toggle off "Ask Before Running")
6. Tap **Next**
7. Tap **Add Action** → search for **Get Contents of URL**
8. Configure the action:
   - **URL:** `https://api.telegram.org/bot[YOUR_BOT_TOKEN]/sendMessage`
     *(Replace `[YOUR_BOT_TOKEN]` with your bot token from `.env`)*
   - **Method:** POST
   - **Request Body:** JSON
   - Add key `chat_id` → value: `[YOUR_CHAT_ID]` *(your Telegram user ID from `.env`)*
   - Add key `text` → tap the field → tap the ✦ variable icon → choose **Message** → **Body**
9. Tap **Done**

---

**Step 3: Test it**
Trigger the shortcut manually by sending yourself a test message from the bank sender name, or wait for the next real bank SMS. You should receive it in this Telegram chat automatically.

---

💡 **Repeat Step 2 for each bank** if you have multiple banks that use different sender names or numbers.
