# Voyage Concierge — Multi-Agent Travel Lead Generation Demo

A three-stage agentic AI system for the travel customer lifecycle:

1. **Lead Discovery** — Targeted social listening with configurable scope. Filters firehose, classifies each match into 7 categories across 3 tiers (Hot/Warm/Cool), and routes to Path A (known customer) or Path B (anonymous).

2. **Nurturing** — Bulk-generates path-aware visual campaigns grouped by classification. One LLM template per tier, personalized per-lead.

3. **Acquisition** — Live booking conversation with tool use (flights, hotels, weather, booking). Receives leads from the Nurturing pipeline with full context pre-loaded.

Plus a **Production Architecture** view showing real endpoints, costs, and auth patterns for the 7 integrated systems (Reddit live + 6 enterprise integrations documented).

---

## File Inventory (10 files)

| File | Purpose |
|------|---------|
| `app.py` | Gradio UI with all 4 tabs, agent orchestration, state management |
| `agent.py` | Acquisition agent — tool-use loop with retry+fallback |
| `lead_discovery.py` | Discovery agent — classification, scoring, Path A/B routing, 15 simulated signals |
| `nurturing.py` | Nurturing agent — path-aware structured campaign generation |
| `tools.py` | Acquisition agent tools: search_flights, search_hotels, check_weather, hold_booking |
| `prompts.py` | System prompt for Acquisition agent |
| `customer_database.py` | 3 simulated customers (Sarah / Marcus / Emma) with consent records for Path A demos |
| `hashtag_config.py` | 4 vertical presets (Airlines, Travel Booking, Luxury, Custom) + scope-matching filter |
| `reddit_source.py` | Live Reddit integration — cache-first with curl_cffi Chrome impersonation |
| `fetch_reddit_cache.py` | Standalone script to pre-fetch Reddit data from a non-firewalled network |

---

## Setup

### 1. Install dependencies

**macOS / Linux:**
```bash
cd voyage-concierge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows PowerShell:**
```powershell
cd voyage-concierge
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Set environment variables

Copy `.env.example` to `.env` and add your Anthropic API key:

```bash
# macOS/Linux
cp .env.example .env

# Windows PowerShell
copy .env.example .env
```

Then edit `.env` and paste your real key.

### 3. (Optional but recommended) Pre-fetch Reddit cache

If your network blocks reddit.com (most corporate networks do), or if Reddit returns 403s due to TLS fingerprinting on your IP range, run this **once** from a non-corporate network:

```bash
python fetch_reddit_cache.py
```

This creates `reddit_cache.json` (~80KB) with real posts from 12 travel subreddits. The demo loads from this cache transparently.

### 4. Launch

```bash
python app.py
```

Opens at `http://localhost:7860`.

---

## Demo Flow

### Tab 1 — Discovery
1. Pick a vertical preset (Travel Booking is default)
2. Choose data source: Simulated firehose OR Reddit (live)
3. Click **Scan with this scope**
4. Watch the right-side console stream filter → classify → score → route
5. After scan, classification breakdown card appears with tier counts
6. Pick any lead from the dropdown to see the AI Reasoning explainer with score decomposition

### Tab 2 — Nurturing
1. Click **Load leads from Discovery**
2. See classification group cards with all leads
3. Pick a tier from the dropdown → auto-selects all leads in that classification
4. Click **Generate campaigns**
5. Visual mockups render (email / SMS / DM / ad) with projected performance metrics
6. Click **Transfer all generated leads to Acquisition**

### Tab 3 — Acquisition
1. Pipeline panel shows transferred leads
2. Click **🚀 Start booking conversation** on any lead → chat textbox pre-fills with lead context
3. Click Send → Voyage agent responds aware of destinations, budget, classification
4. Agent uses tools (flights, hotels, weather) to plan
5. Closes with `hold_booking` when user confirms

### Tab 4 — Architecture
- 7 integration cards showing real endpoints, costs, auth patterns
- Reddit Public API marked **✓ ACTIVE** (the only one truly live)
- Brandwatch / Sprinklr / Talkwalker for enterprise listening
- Adobe AEP / Hightouch / Treasure Data for CDP
- Anthropic Claude, Klaviyo, Twilio, Meta Marketing API, Internal Booking

---

## Architecture Notes

### Resilience
Every LLM call wraps Sonnet 4.5 → Haiku 4.5 with retry+exponential backoff. Demo never crashes due to API overload.

### Cost
- ~$0.003 per lead classification (Sonnet)
- ~$0.005 per campaign generation (Sonnet)
- Total per typical scan: $0.04 (12 leads classified) + $0.06 (12 campaigns) = $0.10

### Path A vs Path B
- **Path A**: Customer found in CDP. Full channel mix (email, SMS, DM, retargeting) based on consent records.
- **Path B**: Net-new anonymous. Limited to public organic engagement + Meta lookalike ads. Email/SMS/DM explicitly forbidden in nurturing prompt.

### Tier System
- 🔥 **Hot** (80-100): ready_to_book, complaint (switching opportunity)
- 🌟 **Warm** (60-79): active_research, advocacy
- 💡 **Cool** (40-59): competitor_mention, dreaming
- 🧊 **Cold** (0-39): off_topic

---

## Troubleshooting

**`python: command not found`** — activate the venv (`source venv/bin/activate` on Mac/Linux, `.\venv\Scripts\Activate.ps1` on Windows)

**Windows: only `py` works, not `python`** — use `py -m venv venv` then activate, after which `python` works inside the venv

**`Could not resolve authentication method`** — `.env` file is missing or `ANTHROPIC_API_KEY` not set

**Reddit `403 Blocked` from corporate networks** — Reddit blocks datacenter IPs (Azure, AWS) used by corporate VPNs. Three solutions in order of preference:
1. Run `fetch_reddit_cache.py` once from your home WiFi or phone hotspot — cached data works permanently
2. `curl_cffi` is included to bypass TLS fingerprinting on residential IPs
3. Skip Reddit entirely — demo works fully with simulated firehose

**Reddit shows "no cache found" + corporate network** — run `fetch_reddit_cache.py` from home/hotspot first

**Port 7860 already in use** — 
- Mac/Linux: `lsof -ti:7860 | xargs kill -9`
- Windows: `Get-NetTCPConnection -LocalPort 7860 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`

**API overload (529 error)** — Already handled: app retries 4x on Sonnet, then falls back to Haiku 4.5 automatically

**curl_cffi install fails on Python 3.14** — It's still very new. Use Python 3.12 or 3.13 if you need curl_cffi. The app works without it (just less reliable Reddit access).

---

## Built With
- [Anthropic Claude API](https://docs.claude.com) — Sonnet 4.5 / Haiku 4.5
- [Gradio](https://gradio.app/) — UI framework
- [python-dotenv](https://github.com/theskumar/python-dotenv) — environment management
- [requests](https://requests.readthedocs.io/) — HTTP basics
- [curl_cffi](https://github.com/lexiforest/curl_cffi) — Chrome TLS impersonation for Reddit
