# Live Channel Setup Guide

This guide walks through activating each of the 3 live channels for Voyage Concierge demos. **All channels are optional** — the app works fully without any of them, falling back to mock sends. Set up only the channels you want to use.

> **⚠️ DEMO SAFETY:** All messages route to YOUR test channels (your verified email, your phone, your Discord/Slack), never to actual prospects. This is enforced at code level. Production deployment would route to the prospect's verified channels with proper consent records.

---

## 1. 📧 Email via Resend (3,000 emails/month free)

**Time to set up:** ~3 minutes
**What you get:** Real emails arrive in your inbox with full HTML rendering

### Steps

1. Go to https://resend.com and click **Sign up**
   - No credit card required
   - Use the email address you want to RECEIVE demo emails on
2. After signup, check your inbox and click the verification link
3. In the Resend dashboard, go to **API Keys** (left sidebar)
4. Click **Create API Key**
   - Name: `voyage-concierge-demo`
   - Permission: **Full access** (Sending access also works)
   - Domain: leave blank for now
5. Copy the API key (starts with `re_`)
6. Open `.env` in your voyage-concierge folder and paste:
   ```
   RESEND_API_KEY=re_your_actual_key_here
   DEMO_RECIPIENT_EMAIL=your_verified_signup_email@example.com
   ```

### Why this works without a custom domain

Resend's free tier lets you send emails from `onboarding@resend.dev` to the email address you verified at signup. No DNS configuration needed.

### Testing

```bash
python -c "
import os
os.environ['RESEND_API_KEY'] = 'your_key'
os.environ['DEMO_RECIPIENT_EMAIL'] = '[email protected]'
from live_channels import send_email_via_resend
r = send_email_via_resend('Hello from Voyage Concierge', 'This is a test send.')
print(r)
"
```

Check your inbox. The email arrives with a `[DEMO]` prefix in the subject and a yellow demo banner at the top.

---

## 2. 📱 SMS via Twilio ($15 trial credit ≈ 1,500 SMS)

**Time to set up:** ~10 minutes
**What you get:** Real SMS lands on your phone with a buzz

### Steps

1. Go to https://www.twilio.com/try-twilio
   - No credit card required for trial
2. Sign up with your email and create a password
3. **Verify your mobile phone number** when prompted — this is critical because trial accounts can only SMS to verified numbers (yours)
4. Pick a use case: select **Send messages** then **SMS notifications**
5. On the dashboard, look for **Account Info** in the top-right or left sidebar. Copy:
   - **Account SID** (starts with `AC...`)
   - **Auth Token** (click "show" to reveal it, then copy)
6. Twilio assigns you a trial phone number automatically. Find it under **Phone Numbers > Manage > Active Numbers**. Copy it in `+1XXX...` format (full international format)
7. Open `.env` and paste:
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_token_here
   TWILIO_FROM_NUMBER=+15551234567
   DEMO_RECIPIENT_PHONE=+15559876543
   ```
   `DEMO_RECIPIENT_PHONE` is the same mobile number you verified during signup.

### Trial limitations to expect

- Each SMS starts with **"Sent from your Twilio trial account - "** — production removes this
- You can only send to numbers you've verified
- $15 of trial credit ≈ 1,500 SMS to US/CA numbers
- Trial accounts have a daily rate limit but it's generous for demos

### Testing

After saving `.env`, run:
```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from live_channels import send_sms_via_twilio
r = send_sms_via_twilio('Test SMS from Voyage Concierge')
print(r)
"
```

Check your phone. SMS arrives within 5-10 seconds.

---

## 3. 💬 Social proxy via Discord (or Slack)

**Time to set up:** ~2 minutes
**What you get:** Rich card posts to a Discord/Slack channel, simulating "social ops team gets notified"

This isn't a real Instagram/Twitter post (those APIs require business verification + app review). Instead, it posts to a team channel — which is what a real CRM workflow would do anyway.

### Option A: Discord (recommended — faster)

1. Open Discord. Create a new server (or use an existing one you control)
   - Click the `+` icon in the server list → "Create My Own" → "For me and my friends"
   - Name it `Voyage Concierge Demo`
2. In the server, click the gear icon next to a text channel (e.g. `#general`) → **Edit Channel**
3. Go to **Integrations** → **Create Webhook**
4. Name it `Voyage Concierge`, leave the channel as `#general` (or pick a `#leads` channel)
5. Click **Copy Webhook URL**
6. Open `.env` and paste:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   ```

### Option B: Slack

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Name: `Voyage Concierge`, pick a workspace
3. Left sidebar: **Incoming Webhooks** → toggle ON
4. Scroll down, click **Add New Webhook to Workspace**
5. Pick a channel (e.g. `#leads`), click **Allow**
6. Copy the webhook URL that appears
7. Open `.env` and paste:
   ```
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   ```

If both are configured, the app prefers Discord.

### Testing

```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from live_channels import send_to_discord_or_slack
r = send_to_discord_or_slack('Test Touch from Demo', 'Hello team, this is a test post from the Voyage Concierge nurturing pipeline.', 'u/testuser', 'Instagram DM')
print(r)
"
```

Check your Discord/Slack channel. A rich card appears with the prospect handle, channel, and message body.

---

## How the app uses these channels

When you click **🔥 Fire Now** in the Nurturing tab, the app routes each touch to the appropriate channel:

| Touch channel | Routes to | Vendor |
|---------------|-----------|--------|
| `email` | Your verified email | Resend |
| `sms` | Your verified phone | Twilio |
| `retargeting` | Your Discord/Slack channel | Webhook |
| `ig_dm` | Your Discord/Slack channel | Webhook |
| `ig_reply` | Your Discord/Slack channel | Webhook |
| `lookalike_ad` | Your Discord/Slack channel | Webhook |
| `push` | Your Discord/Slack channel | Webhook |

If a channel is unconfigured (missing API key/credentials), the touch falls back to a **mock send** — the Activity Log shows a yellow "MOCK" badge and no real message is dispatched.

## Demo flow

1. In the Nurturing tab, generate sequences for a few leads
2. Scroll down to the **🚀 Live Send Mode** section
3. Look at the channel status banner — see which channels are ✓ Ready vs ✗ Not configured
4. Check **Activate Live Send Mode** to turn it on
5. Choose mode:
   - **Fire only Touch 1 of each sequence** — safe for demos, won't blast your inbox
   - **Fire ALL touches** — fires the entire sequence at once (~5-7 messages per lead)
6. Click **🔥 Fire Now — Top-scoring lead** or **📤 Fire Now — All generated sequences**
7. Watch the Activity Log populate in real time
8. Check your inbox / phone / Discord channel — the actual message arrives in seconds

## Troubleshooting

**Resend: "Domain not verified"**
You're sending from a custom domain that hasn't passed DNS verification. The app uses `[email protected]` which doesn't require verification, so this shouldn't happen. Check the `from` address in `live_channels.py`.

**Twilio: "21608 - The number is unverified"**
Your `DEMO_RECIPIENT_PHONE` isn't on your Verified Caller IDs list. Go to Twilio Console → Phone Numbers → Verified Caller IDs → Add a new one.

**Twilio: "21211 - Invalid To phone number"**
The phone number isn't in E.164 format. Use `+1XXXXXXXXXX` (including country code with the `+`).

**Discord/Slack: no message appears**
- Check the webhook URL didn't get truncated when pasted
- Confirm the channel still exists and the webhook wasn't deleted
- Look at the Activity Log — if it says "404" the URL is wrong; "401" means the webhook was revoked

**App says "MOCK" even though I configured the channel**
- Restart the app — `.env` is only read at startup
- Verify the variable name matches exactly (no extra quotes, no trailing spaces)
- Check that the recipient variable is ALSO set, not just the API key
