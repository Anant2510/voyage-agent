# Demo Personas + Two-Way Loop Setup Guide

This guide walks through closing the loop in your Voyage Concierge demo — making it look like real Reddit prospects are being nurtured and replying to you in real time.

## What This Solves

Out of the box, Discovery finds anonymous Reddit users. They have no email or phone, so the Live Send feature can't deliver to them. We bridge this gap with **demo personas** — Reddit accounts YOU control, routed to YOUR verified channels via plus-aliasing.

The result: scan finds the personas, sequences fire to your email/phone with persona tags, and you (playing the prospect) can reply back. In two-way mode, those replies appear automatically in the app's conversation thread view.

---

## Quick Concept

| | What it looks like to the audience | What actually happens |
|---|---|---|
| **Reddit user** | An unknown traveler "Priya" posted on r/JapanTravel | You posted as `u/priya_wanderlust` (a Reddit account you control) |
| **AI nurture** | AI dispatches email to Priya's verified address | Email goes to `[email protected]` (a plus-alias of your inbox) |
| **Priya replies** | Priya answers from her phone | You reply to the email from your phone |
| **App receives reply** | Reply appears in conversation thread | Resend webhook → your local app via ngrok |

This is a legitimate **demo persona pattern** used by sales engineering teams everywhere. You're playing both roles in a controlled demo. No spam, no impersonation of real strangers.

---

## The 3 Pre-Built Personas

| Persona | Reddit Handle | Designed Classification | Email Route | SMS Tag |
|---------|---------------|-------------------------|-------------|---------|
| 🔥 Priya Sharma | `u/priya_wanderlust` | Hot · Ready to Book | `youremail+priya@...` | `[PRIYA]` |
| 🌟 Marcus Chen | `u/marcus_travelplanner` | Warm · Active Research | `youremail+marcus@...` | `[MARCUS]` |
| ⭐ Sarah Mitchell | `u/sarah_switchedairlines` | Hot · Switching Intent | `youremail+sarah@...` | `[SARAH]` |

All three personas share ONE phone number (Twilio trial only allows one). The `[PRIYA]` / `[MARCUS]` / `[SARAH]` prefix is prepended to outbound SMS so you can identify which persona an inbound reply is for.

---

## Setup Stage 1 — Make The Personas Real On Reddit

You can choose REAL Reddit posts OR fully simulated. Hybrid mode (default) tries real first, falls back to simulated.

### Option A — Real Reddit Posts (Recommended)

1. **Create 3 Reddit accounts** with these usernames (or close variants):
   - `priya_wanderlust`
   - `marcus_travelplanner`
   - `sarah_switchedairlines`

   Reddit allows multiple accounts per person for legitimate use. Use different emails (or `youremail+reddit1@gmail.com` plus-aliases). No karma needed for posts (AutoMod may hold them in some subreddits — that's fine, they're still in the API feed).

2. **Post the seed content** for each persona. Copy the body from `demo_personas.py` → `simulated_posts` field. Post Priya to r/JapanTravel, Marcus to r/IcelandTravel, Sarah to r/travel.

3. **Wait 5–10 minutes** for the post to propagate, then refresh your Reddit cache:
   ```bash
   cd ~/voyage-agent
   python fetch_reddit_cache.py
   ```

4. The scanner should now find your real posts.

### Option B — Simulated Posts Only (Faster Setup)

Skip account creation. Just enable the **🎭 Inject demo personas into the scan** checkbox in the Discovery tab. The app injects the 3 persona posts directly into the firehose. The leads will be tagged 🎭 instead of 🔗, but everything else (Live Send, conversation threads) works identically.

---

## Setup Stage 2 — Configure Your Recipients

Edit your `.env` file (you should have set these up already in the previous Live Channels setup):

```
DEMO_RECIPIENT_EMAIL=youremail@gmail.com
DEMO_RECIPIENT_PHONE=+15551234567
```

The app will automatically generate per-persona routes:
- Email: `youremail+priya@gmail.com`, `youremail+marcus@gmail.com`, etc.
- SMS: all to `+15551234567` with `[PRIYA]`, `[MARCUS]`, `[SARAH]` body prefix

**Gmail and Outlook both support plus-aliasing natively.** If you use a different provider, check whether they do. If not, all persona emails will still land in your main inbox — just without filtering ability.

### Set up Gmail filters (optional but recommended)

To visually separate persona emails in your inbox:

1. Gmail → Settings → Filters and Blocked Addresses → Create new filter
2. **To** field: `[email protected]`
3. Create filter → Apply label "Priya"
4. Repeat for Marcus and Sarah

Now persona emails are color-coded in your inbox.

---

## Setup Stage 3 — Try The One-Way Loop First

Before setting up webhooks, prove the basic flow works:

1. **Launch the app:**
   ```bash
   lsof -ti:7860 | xargs kill -9 2>/dev/null
   python app.py
   ```

2. **Discovery tab:**
   - Pick data source: 📦 Reddit cached (or 🧪 Simulated firehose if you skipped Stage 1)
   - **Check the 🎭 Inject demo personas into the scan checkbox**
   - Click Scan
   - Confirm the 3 personas appear in the lead dropdown with the 🎭 emoji

3. **Nurturing tab:**
   - Load leads from Discovery
   - Select Priya, Marcus, Sarah
   - Click Generate campaigns
   - Watch the sequences appear

4. **Scroll to 🚀 Live Send Mode:**
   - Confirm channels are ✓ Ready (or ✗ Not configured)
   - Flip **Activate Live Send Mode** ON
   - Click **🔥 Fire Now — Top-scoring lead**
   - Within 10 seconds: check `youremail+priya@gmail.com` inbox — Priya's first touch email should arrive

5. **Scroll to 💬 Persona Conversations:**
   - Priya's outbound bubble should appear (blue, right-side)

6. **Test manual reply (one-way mode):**
   - Pick Priya from the dropdown
   - Channel: Email
   - Type a reply like "Yes, send me option 2 — the Hakone onsen package"
   - Click 📨 Inject reply into conversation
   - A gray inbound bubble appears with Priya's "reply"

That's the one-way loop. You're playing both sides manually but the audience sees a coherent conversation in the UI.

---

## Setup Stage 4 — Activate The Two-Way Loop (Auto-Reply Detection)

Two-way mode requires exposing your local app to the internet so Resend and Twilio can deliver webhooks to it. We use **ngrok** (free).

### Step 1 — Install ngrok

```bash
# Mac
brew install ngrok

# Or download from https://ngrok.com/download
```

### Step 2 — Sign up for ngrok (free)

1. https://ngrok.com/signup
2. After signup, you'll see your authtoken on the dashboard
3. Run:
   ```bash
   ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
   ```

### Step 3 — Start the webhook server inside the app

1. In the running app, go to Nurturing tab
2. Scroll to **🔄 Two-Way Loop (Replies → App)**
3. Check **Enable Two-Way Loop**
4. The app prints instructions and starts the webhook server on port 7861

### Step 4 — Expose port 7861 via ngrok

Open a **new terminal window** (keep the app running) and run:

```bash
ngrok http 7861
```

ngrok will print something like:
```
Forwarding   https://abc123def456.ngrok-free.app -> http://localhost:7861
```

**Copy that `https://...ngrok-free.app` URL.** This is your public webhook endpoint.

### Step 5 — Configure Resend to forward replies

> NOTE: Resend's **inbound email** feature requires a custom domain with MX records. On the free tier sandbox sender (`onboarding@resend.dev`), inbound webhooks aren't supported. There are two options:

**Option A — Configure on the delivery webhook (recommended for demo):**
This receives delivery/bounce/open events but NOT actual reply content. You can still see receipt confirmations.

1. Resend dashboard → Webhooks → Add Endpoint
2. URL: `https://abc123def456.ngrok-free.app/webhook/email`
3. Events: `email.sent`, `email.delivered`, `email.opened`, `email.clicked`
4. Save

**Option B — Use a custom domain (production-style):**
1. Add a domain to Resend (e.g. `voyage-demo.yourdomain.com`)
2. Add the MX records they specify
3. Once verified, enable Inbound on that domain
4. Set the inbound webhook to your ngrok URL
5. Update `live_channels.py` to send FROM `[email protected]` instead of `[email protected]`

For most demos, Option A is enough — the proof point is "the system tracked delivery in real-time." Option B is needed for true reply detection.

### Step 6 — Configure Twilio to forward replies (this one works on trial)

Twilio's inbound webhook **works on the trial account**, which is great.

1. Twilio Console → Phone Numbers → Manage → Active Numbers
2. Click your trial number
3. Scroll to "Messaging" section
4. **A Message Comes In:** Webhook
   - URL: `https://abc123def456.ngrok-free.app/webhook/sms`
   - HTTP: POST
5. Save

Now when you reply to a Twilio SMS from your phone, the reply hits the webhook → the app sees it → it appears in the conversation thread.

### Step 7 — Test the loop

1. In the app, Fire Now to Priya
2. SMS arrives on your phone with `[PRIYA]` prefix
3. **Reply to that SMS from your phone**, keeping the `[PRIYA]` prefix at the start of your message (this is how the app knows which persona it's for):
   - `[PRIYA] Yes please send me option 2`
4. Wait 5 seconds, click the 🔄 Refresh conversation view button in the app
5. The inbound bubble appears under Priya's thread

**Boom — closed loop.** Audience sees: AI fired SMS → "Priya" replied from her phone → app captured the reply → conversation visible.

---

## Demo Script (What To Say On Stage)

> *"Let me show you the full nurturing loop. I've configured 3 demo personas representing different lead tiers. Watch what happens when I scan."*
>
> [Scan with persona injection ON]
>
> *"Found all 3 — Priya as Hot Ready-to-Book, Marcus as Warm Researching, Sarah as Hot Switching Intent. Each is a real Reddit post (or simulated demo signal) routed to a verified inbox I control."*
>
> [Switch to Nurturing, generate, Fire Now]
>
> *"AI built the sequence, fired Touch 1 to Priya's email. Watch my phone."*
>
> [Email landing notification on phone]
>
> *"There's the real email. Now I'll reply from my phone, playing Priya — 'Send me option 2.'"*
>
> [Reply via phone]
>
> [Click Refresh in app]
>
> *"And the reply lands back in the conversation thread. Closed loop. In production this would be the actual prospect's actual inbox."*

This is the moment that sells the product.

---

## Troubleshooting

**"I clicked scan and the personas don't appear"**
- Confirm the 🎭 Inject demo personas checkbox is ON
- For real Reddit posts: confirm your post is visible at reddit.com/r/<sub>/new (refresh the cache via `python fetch_reddit_cache.py`)
- For simulated posts: confirm `demo_personas.py` was uploaded to your folder

**"Live Send fires but I get a MOCK badge"**
- The credentials for that channel aren't set in `.env`
- Verify variables: `RESEND_API_KEY`, `DEMO_RECIPIENT_EMAIL`, `TWILIO_ACCOUNT_SID`, etc.
- Restart the app after editing `.env`

**"Email arrives but goes to spam"**
- Resend's `[email protected]` is a shared sender — some inboxes are skeptical
- For a clean demo: add your inbox to the safe-sender list temporarily
- Or follow Option B in Stage 4 to use a custom domain

**"SMS shows [PRIYA] prefix in the audience's view — looks fake"**
- That's intentional for identification. You can mention it on stage: "In production, each persona has their own number. In this trial demo, we route to one Twilio trial number with persona tags."
- Or rephrase the prefix to look like a subject line: edit `demo_personas.py` → `sms_prefix` field

**"Two-way: I replied to email but nothing appeared in the conversation thread"**
- Resend free tier sandbox doesn't support inbound webhooks (see Stage 4 Step 5)
- For email replies to work, you need a custom domain. For demo purposes, use manual reply injection instead (one-way mode in the UI)

**"Two-way: SMS reply isn't showing up"**
- Check ngrok is still running (free tier expires after 2 hours of inactivity — restart it)
- Confirm Twilio webhook URL matches your current ngrok URL (it changes every restart unless you pay)
- Check `http://localhost:7861/webhook/status` returns JSON — that confirms server is up
- Did you include `[PRIYA]` prefix in your reply? Without it the persona can't be identified

**"ngrok URL keeps changing"**
- Free tier rotates URLs on each restart. For demos, restart ngrok once and don't kill it.
- For a stable URL, upgrade to ngrok paid ($8/mo) — gives you a fixed subdomain

---

## What Production Would Look Like

For real product deployment (not a demo):
- Real consented prospects, real emails/phones, real DM permissions
- No plus-aliasing tricks — each prospect has their own contact info
- No SMS prefixes — each touch is dispatched to the prospect's verified number
- Resend on a verified production domain with inbound enabled
- Webhooks deployed to a real cloud host (not ngrok)
- Compliance: opt-in records, opt-out handling, GDPR/TCPA verification before every send

The demo simulates all of this with you playing the prospect roles. The architecture is identical to production.
