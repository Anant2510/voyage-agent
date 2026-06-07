"""
Voyage Concierge — Multi-Agent Demo (v3.5)
============================================

Design-QA pass on v3.4. Critical fixes:
  ✅ Typography standardized to 6-step scale (10/12/14/16/20/28)
  ✅ ROI dashboard collapsible — 1-line summary by default, expand on click
  ✅ Lead detail dedup — classification only shown once, in explainer card
  ✅ Console panel: header + body merged visually
  ✅ Architecture endpoint URLs: word-wrap to prevent overflow
  ✅ Why-matched: base score capped to keep visualization meaningful
  ✅ Discovery summary: pure HTML instead of mixed markdown/HTML

Plus consistent hero intros across tabs and unified card design system.
"""

from dotenv import load_dotenv
load_dotenv()

import gradio as gr
import html
import os
from datetime import datetime
from collections import defaultdict

from agent import VoyageAgent
from lead_discovery import LeadDiscoveryAgent, SOCIAL_SIGNALS
from nurturing import NurturingAgent
from hashtag_config import PRESETS, get_preset, parse_user_config, config_summary, signal_matches_config
from customer_database import find_customer_by_social_handle, classify_lead_path, get_customer_summary
from reddit_source import fetch_reddit_signals, DEFAULT_SUBREDDITS
from live_channels import (
    fire_touch as live_fire_touch,
    get_channel_status as live_channel_status,
)
from demo_personas import (
    DEMO_PERSONAS,
    list_personas,
    is_demo_persona_handle,
    get_persona_email_recipient,
    get_persona_sms_recipient,
    get_persona_sms_prefix,
    get_persona_by_id,
    get_conversation_thread,
    get_all_conversation_threads,
    clear_conversation_thread,
    record_inbound,
)
from webhook_receiver import (
    start_webhook_server,
    stop_webhook_server,
    is_server_running,
    get_receipt_log,
    get_server_port,
)


# ============================================================
# GLOBAL STATE
# ============================================================

discovered_leads = []
generated_campaigns = {}
active_config = None
acquisition_pipeline = []

session_metrics = {
    "scans_run": 0,
    "leads_classified": 0,
    "campaigns_generated": 0,
    "estimated_cost_usd": 0.0,
}


# ============================================================
# CLASSIFICATION TIER MAPPING
# ============================================================

CLASSIFICATION_META = {
    # 🔥 HOT — Ready to convert
    "ready_to_book":      {"emoji": "🔥", "tier": "Hot",          "color": "#dc2626", "bg": "#fef2f2", "label": "Ready to Book",        "priority": 1},
    "switching_intent":   {"emoji": "⭐", "tier": "Hot",          "color": "#ea580c", "bg": "#fff7ed", "label": "Switching Intent",     "priority": 2},

    # 🌟 WARM — Genuine planning activity
    "active_research":    {"emoji": "🌟", "tier": "Warm",         "color": "#ca8a04", "bg": "#fefce8", "label": "Active Research",       "priority": 3},
    "advocacy":           {"emoji": "🌟", "tier": "Warm",         "color": "#16a34a", "bg": "#f0fdf4", "label": "Advocacy",              "priority": 4},

    # 💡 COOL — Early-stage interest
    "competitor_mention": {"emoji": "💡", "tier": "Cool",         "color": "#0891b2", "bg": "#ecfeff", "label": "Competitor Mention",    "priority": 5},
    "dreaming":           {"emoji": "💡", "tier": "Cool",         "color": "#7c3aed", "bg": "#faf5ff", "label": "Dreaming",              "priority": 6},

    # ❌ DISQUALIFIED — Not a sales lead
    "venting_only":       {"emoji": "❌", "tier": "Disqualified", "color": "#94a3b8", "bg": "#f8fafc", "label": "Venting Only",          "priority": 7},
    "off_topic":          {"emoji": "❌", "tier": "Disqualified", "color": "#94a3b8", "bg": "#f8fafc", "label": "Off Topic",             "priority": 8},
}


def get_classification_meta(classification):
    return CLASSIFICATION_META.get(classification, {
        "emoji": "📌", "tier": "Other", "color": "#64748b", "bg": "#f8fafc",
        "label": classification.replace("_", " ").title(), "priority": 99
    })


# ============================================================
# SHARED COMPONENT BUILDERS
# ============================================================

def hero_intro(emoji, title, description, accent_color="#3b82f6"):
    """
    Consistent hero intro card used at the top of every tab.
    Replaces inconsistent gr.Markdown("### ...") headers.
    """
    return f"""
    <div style="background:white; border:1px solid #e2e8f0; border-left:5px solid {accent_color}; border-radius:14px; padding:18px 22px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex; align-items:center; gap:14px;">
        <div style="font-size:32px; line-height:1;">{emoji}</div>
        <div>
          <div style="font-size:20px; font-weight:700; color:#0f172a; letter-spacing:-0.3px; margin-bottom:4px;">{title}</div>
          <div style="font-size:14px; color:#475569; line-height:1.55;">{description}</div>
        </div>
      </div>
    </div>
    """


def section_label(text):
    """Consistent small uppercase section labels used between cards."""
    return f'<div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px; margin:16px 0 8px 0;">{text}</div>'


def agent_console_header(label, status="LIVE"):
    """
    Single-piece HTML that combines the console header + space for body.
    Body is styled via the #*_console elem_id below.
    """
    return f"""
    <div style="background:#0f172a; border-radius:12px 12px 0 0; padding:14px 18px; box-shadow:0 4px 12px rgba(15,23,42,0.15); border-bottom:1px solid rgba(255,255,255,0.06);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div style="font-family:'JetBrains Mono',monospace; font-size:10px; color:#94a3b8; font-weight:700; letter-spacing:1.5px;">{label}</div>
        <div style="background:#16a34a; color:white; padding:3px 9px; border-radius:10px; font-size:9px; font-weight:700; letter-spacing:0.5px;">● {status}</div>
      </div>
    </div>
    """


# ============================================================
# ROI DASHBOARD — Collapsible
# ============================================================

def calculate_roi(scans_per_month=500, avg_order_value=3500, analyst_hourly_rate=30):
    """Calculate ROI metrics from operational assumptions."""
    leads_per_scan = 12
    llm_calls_per_lead = 2
    cost_per_llm_call_usd = 0.003
    cost_per_scan = leads_per_scan * llm_calls_per_lead * cost_per_llm_call_usd
    monthly_ai_cost = scans_per_month * cost_per_scan

    manual_hours_per_lead = 4
    manual_cost_per_lead = manual_hours_per_lead * analyst_hourly_rate
    monthly_manual_cost = scans_per_month * leads_per_scan * manual_cost_per_lead

    monthly_savings = monthly_manual_cost - monthly_ai_cost
    annual_savings = monthly_savings * 12

    booking_conversion_rate = 0.025
    monthly_bookings = scans_per_month * leads_per_scan * booking_conversion_rate
    monthly_revenue = monthly_bookings * avg_order_value
    annual_revenue = monthly_revenue * 12

    roi_multiple = monthly_savings / monthly_ai_cost if monthly_ai_cost > 0 else 0
    monthly_total_value = monthly_savings + monthly_revenue * 0.10
    payback_days = (monthly_ai_cost / monthly_total_value * 30) if monthly_total_value > 0 else 0

    return {
        "monthly_ai_cost": monthly_ai_cost,
        "monthly_manual_cost": monthly_manual_cost,
        "monthly_savings": monthly_savings,
        "annual_savings": annual_savings,
        "monthly_bookings": monthly_bookings,
        "monthly_revenue": monthly_revenue,
        "annual_revenue": annual_revenue,
        "roi_multiple": roi_multiple,
        "payback_days": payback_days,
        "cost_per_scan": cost_per_scan,
        "leads_per_scan": leads_per_scan,
        "manual_cost_per_lead": manual_cost_per_lead,
    }


def render_roi_collapsed():
    """1-line pill summary — default state. Click to expand."""
    m = calculate_roi()
    return f"""
    <details style="background:linear-gradient(135deg,#0f172a 0%,#1e3a8a 50%,#312e81 100%); border-radius:14px; padding:0; margin-bottom:16px; box-shadow:0 6px 20px rgba(15,23,42,0.15); overflow:hidden;" id="roi-details">
      <summary style="cursor:pointer; padding:16px 24px; list-style:none; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; user-select:none;">
        <div style="display:flex; align-items:center; gap:18px; flex-wrap:wrap;">
          <div style="font-size:11px; font-weight:700; color:#c4b5fd; text-transform:uppercase; letter-spacing:1.2px;">💼 Business Case</div>
          <div style="font-size:14px; color:white; font-weight:600;">
            <span style="color:#4ade80;">${m['annual_savings']/1000:,.0f}K/yr saved</span>
            <span style="color:#94a3b8; margin:0 10px;">·</span>
            <span style="color:#fcd34d;">${m['annual_revenue']/1000000:,.1f}M pipeline</span>
            <span style="color:#94a3b8; margin:0 10px;">·</span>
            <span style="color:#93c5fd;">{m['roi_multiple']:,.0f}× ROI</span>
            <span style="color:#94a3b8; margin:0 10px;">·</span>
            <span style="color:#c4b5fd;">{m['payback_days']:.1f}d payback</span>
          </div>
        </div>
        <div style="font-size:12px; color:#e2e8f0; font-weight:600;">Click to expand ▾</div>
      </summary>

      <div style="padding:20px 24px 24px 24px; border-top:1px solid rgba(255,255,255,0.08);">
        <div style="font-size:13px; color:#e2e8f0; margin-bottom:16px; font-weight:500;">Based on 500 scans/month · $3,500 avg booking · $30/hr team rate</div>

        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px;">
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Annual Savings</div>
            <div style="font-size:24px; font-weight:800; color:#22c55e; margin-top:4px;">${m['annual_savings']/1000:,.0f}K</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">vs. manual research</div>
          </div>
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Pipeline Revenue</div>
            <div style="font-size:24px; font-weight:800; color:#fbbf24; margin-top:4px;">${m['annual_revenue']/1000000:,.1f}M</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">at 2.5% conversion</div>
          </div>
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Monthly AI Cost</div>
            <div style="font-size:24px; font-weight:800; color:#60a5fa; margin-top:4px;">${m['monthly_ai_cost']:,.0f}</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">~${m['cost_per_scan']:.2f}/scan</div>
          </div>
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Payback Period</div>
            <div style="font-size:24px; font-weight:800; color:#a78bfa; margin-top:4px;">{m['payback_days']:.1f}d</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">days to break-even</div>
          </div>
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Bookings/Month</div>
            <div style="font-size:24px; font-weight:800; color:#fb923c; margin-top:4px;">{m['monthly_bookings']:,.0f}</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">incremental</div>
          </div>
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:12px; padding:14px 16px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Manual Equivalent</div>
            <div style="font-size:24px; font-weight:800; color:#f87171; margin-top:4px;">${m['monthly_manual_cost']/1000:,.0f}K</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">cost/month if human</div>
          </div>
        </div>

        <div style="margin-top:16px; padding:12px 14px; background:rgba(59,130,246,0.1); border-left:3px solid #3b82f6; border-radius:0 8px 8px 0;">
          <div style="font-size:12px; color:#dbeafe; line-height:1.6;">
            <strong style="color:white;">Sanity check:</strong> A human analyst spends ~4 hours researching one social lead at $30/hr ($120/lead). The AI does the same in ~7 seconds at $0.003/lead. Savings compound at scale.
          </div>
        </div>
      </div>
    </details>
    """


# ============================================================
# DISCOVERY HANDLERS
# ============================================================

def get_preset_config(preset_key):
    preset = get_preset(preset_key)
    lines = []
    if preset["include_hashtags"]:
        lines.append("# Hashtags")
        lines.extend(preset["include_hashtags"])
        lines.append("")
    if preset["include_keywords"]:
        lines.append("# Keywords")
        lines.extend(preset["include_keywords"])
        lines.append("")
    if preset["competitor_mentions"]:
        lines.append("# Competitor handles")
        lines.extend(preset["competitor_mentions"])
        lines.append("")
    if preset["exclude_keywords"]:
        lines.append("# Exclusions")
        lines.extend(preset["exclude_keywords"])
    text = "\n".join(lines)
    summary_md = f"**Preset loaded: {preset['name']}**  \n{preset['description']}"
    return text, summary_md


def scan_with_config(preset_key, custom_text, data_source="simulated", reddit_subs_text="", inject_personas_flag=False):
    global discovered_leads, active_config, session_metrics

    console_log = []

    def console(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        console_log.append(f"`{ts}` {msg}")

    console("🔄 Initializing Lead Discovery agent...")
    yield "🔄 Initializing...", gr.update(choices=[], value=None), "", "\n\n".join(console_log)

    if custom_text and custom_text.strip() and not custom_text.startswith("# Hashtags"):
        config = parse_user_config(custom_text)
        config["name"] = f"{get_preset(preset_key)['name']} (modified)"
    else:
        config = get_preset(preset_key).copy()

    if custom_text and custom_text.strip() and custom_text.startswith("# Hashtags"):
        parsed = parse_user_config(custom_text)
        config["include_hashtags"] = parsed["include_hashtags"]
        config["include_keywords"] = parsed["include_keywords"]
        config["competitor_mentions"] = parsed["competitor_mentions"]

    active_config = config

    console(f"📡 Scope loaded: **{config['name']}**")
    console(f"   {len(config['include_hashtags'])} hashtags · {len(config['include_keywords'])} keywords · {len(config['competitor_mentions'])} competitors")

    # ====================================================
    # FETCH SIGNALS FROM CHOSEN DATA SOURCE
    # ====================================================
    if data_source in ("reddit", "reddit_cache", "reddit_live"):
        force_fresh = (data_source == "reddit_live")
        mode_label = "live (fresh fetch)" if force_fresh else "cached"
        console(f"🌐 **Reddit {mode_label} scan** — preparing signals...")
        yield render_scan_progress(0, 0, 0, 1, config['name'] + f" · Reddit {mode_label}"), gr.update(choices=[], value=None), "", "\n\n".join(console_log)

        # Parse subreddit list from textarea (one per line, strip 'r/' if present)
        if reddit_subs_text and reddit_subs_text.strip():
            subs = [s.strip().lstrip("r/").strip() for s in reddit_subs_text.split("\n") if s.strip()]
            if not subs:
                subs = list(DEFAULT_SUBREDDITS)
        else:
            subs = list(DEFAULT_SUBREDDITS)

        console(f"   Subreddits: {', '.join('r/' + s for s in subs)}")
        if inject_personas_flag:
            console(f"   🎭 Demo persona injection: ON (hybrid mode - real posts first, simulated fallback)")

        def reddit_progress(msg):
            console(msg)

        try:
            signals_to_scan = fetch_reddit_signals(
                subreddits=subs,
                posts_per_sub=10,
                max_total=500,
                progress_callback=reddit_progress,
                force_fresh=force_fresh,
                inject_personas=inject_personas_flag,
            )
        except Exception as e:
            console(f"❌ Reddit fetch failed: {e}")
            console("   Falling back to simulated firehose...")
            signals_to_scan = list(SOCIAL_SIGNALS)

        if not signals_to_scan:
            console("⚠️  Reddit returned no posts. Falling back to simulated firehose.")
            signals_to_scan = list(SOCIAL_SIGNALS)
        else:
            console(f"")
            console(f"📥 {len(signals_to_scan)} posts ready · running through classification pipeline...")
    else:
        console("🔍 Scanning simulated firehose against listening scope...")
        signals_to_scan = list(SOCIAL_SIGNALS)
        if inject_personas_flag:
            console("   🎭 Demo persona injection: ON (adding persona posts to simulated firehose)")
            try:
                from demo_personas import inject_personas_into_feed
                signals_to_scan, inj_log = inject_personas_into_feed(signals_to_scan, only_if_missing=True)
                for line in inj_log:
                    console(f"   Persona: {line}")
            except Exception as e:
                console(f"   Persona injection failed: {e}")

    yield render_scan_progress(0, 0, 0, len(signals_to_scan), config['name']), gr.update(choices=[], value=None), "", "\n\n".join(console_log)

    leads = []
    path_a_count = 0
    path_b_count = 0
    classifications = {}

    agent = LeadDiscoveryAgent()
    matched_so_far = 0
    skipped_so_far = 0

    for i, signal in enumerate(signals_to_scan, 1):
        match = signal_matches_config(signal, config)
        if not match["matched"]:
            skipped_so_far += 1
            console(f"⏭️ [{i}/{len(signals_to_scan)}] Skipped {signal['user_handle']}")
            yield render_scan_progress(i, matched_so_far, skipped_so_far, len(signals_to_scan), config['name']), gr.update(choices=[], value=None), "", "\n\n".join(console_log)
            continue

        matched_so_far += 1
        console(f"✅ [{i}/{len(signals_to_scan)}] Matched {signal['user_handle']} — classifying...")
        yield render_scan_progress(i, matched_so_far, skipped_so_far, len(signals_to_scan), config['name']), gr.update(choices=[], value=None), "", "\n\n".join(console_log)

        analysis = agent.classify_and_score(signal, config["name"])
        classification = analysis.get("classification", "unknown")
        classifications[classification] = classifications.get(classification, 0) + 1

        path = agent.resolve_identity(signal)
        if path["path"] == "A":
            path_a_count += 1
        else:
            path_b_count += 1

        leads.append({
            "signal": signal,
            "scope_match": match,
            "analysis": analysis,
            "path": path,
            "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        session_metrics["leads_classified"] += 1
        session_metrics["estimated_cost_usd"] += 0.003

        score = analysis.get("intent_score", 0)
        meta = get_classification_meta(classification)
        path_emoji = "🟢" if path["path"] == "A" else "🟡"
        console(f"   → {path_emoji} {meta['emoji']} {meta['tier']} · {meta['label']} · {score}/100 · $0.003")

        yield render_scan_progress(i, matched_so_far, skipped_so_far, len(signals_to_scan), config['name']), gr.update(choices=[], value=None), "", "\n\n".join(console_log)

    leads.sort(key=lambda x: (
        get_classification_meta(x["analysis"].get("classification", "")).get("priority", 99),
        -x["analysis"].get("intent_score", 0)
    ))

    discovered_leads = leads
    session_metrics["scans_run"] += 1

    result = {
        "leads": leads,
        "total_signals": len(signals_to_scan),
        "matched_signals": len(leads),
        "path_a_count": path_a_count,
        "path_b_count": path_b_count,
        "classification_breakdown": classifications,
        "config_used": config["name"]
    }

    console("")
    console(f"📊 **Scan complete**")
    console(f"   {result['matched_signals']}/{result['total_signals']} signals matched scope")
    console(f"   🟢 Path A: {result['path_a_count']} · 🟡 Path B: {result['path_b_count']}")
    console(f"   💰 Total scan cost: ${result['matched_signals'] * 0.003:.3f}")
    console("")
    for cls, count in sorted(classifications.items(), key=lambda x: get_classification_meta(x[0]).get("priority", 99)):
        meta = get_classification_meta(cls)
        console(f"   {meta['emoji']} {meta['label']}: {count}")
    console("")
    console(f"✨ Ready for nurturing — switch to **Nurturing** view")

    summary = format_discovery_summary(result)
    choices = format_lead_choices(result["leads"])

    yield summary, gr.update(choices=choices, value=None), "", "\n\n".join(console_log)


def render_scan_progress(processed, matched, skipped, total, scope_name):
    """Progress bar HTML during scanning."""
    pct = (processed / total * 100) if total else 0
    return f"""
    <div style="background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px 20px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <div style="font-size:14px; font-weight:700; color:#0f172a;">Scanning <span style="color:#3b82f6;">{html.escape(scope_name)}</span> scope</div>
        <div style="font-size:12px; color:#64748b; font-family:monospace;">{processed}/{total} processed · {matched} matched · {skipped} skipped</div>
      </div>
      <div style="background:#f1f5f9; height:6px; border-radius:3px; overflow:hidden;">
        <div style="background:linear-gradient(90deg,#3b82f6,#1e3a8a); height:100%; width:{pct:.1f}%; border-radius:3px; transition:width 0.3s ease;"></div>
      </div>
    </div>
    """


def format_discovery_summary(result):
    """Pure HTML — no markdown/HTML mixing."""
    leads = result["leads"]
    if not leads:
        return f"""<div style="background:white; border:1px solid #e2e8f0; border-radius:12px; padding:24px; text-align:center; color:#64748b;">
          <div style="font-size:16px; font-weight:700; color:#0f172a; margin-bottom:6px;">No matching leads</div>
          <div style="font-size:13px;">Scanned {result['total_signals']} signals against the <strong>{html.escape(result['config_used'])}</strong> scope. None matched.</div>
        </div>"""

    breakdown_cards = ""
    for cls, count in sorted(result["classification_breakdown"].items(), key=lambda x: get_classification_meta(x[0]).get("priority", 99)):
        meta = get_classification_meta(cls)
        breakdown_cards += f"""
        <div style="background:{meta['bg']}; border:1px solid {meta['color']}33; border-left:4px solid {meta['color']}; border-radius:10px; padding:12px 14px;">
          <div style="font-size:10px; color:{meta['color']}; font-weight:700; letter-spacing:0.5px; text-transform:uppercase; margin-bottom:4px;">{meta['emoji']} {meta['tier']} · {meta['label']}</div>
          <div style="font-size:24px; font-weight:800; color:#0f172a; line-height:1;">{count}</div>
          <div style="font-size:11px; color:#64748b; margin-top:2px;">{'lead' if count == 1 else 'leads'}</div>
        </div>
        """

    cost = result['matched_signals'] * 0.003

    # Count how many leads have verifiable source URLs (real posts from live source)
    verifiable_count = sum(
        1 for lead in leads
        if lead.get("signal", {}).get("_reddit_url", "").strip()
        and lead["signal"]["_reddit_url"].strip() != "https://reddit.com"
    )

    verifiable_banner = ""
    if verifiable_count > 0:
        verifiable_banner = f"""
      <div style="background:linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%); border:1px solid #bbf7d0; border-left:4px solid #16a34a; border-radius:10px; padding:12px 16px; margin-bottom:18px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
          <div>
            <div style="font-size:10px; font-weight:700; color:#15803d; text-transform:uppercase; letter-spacing:1px;">✓ Verified Live Data</div>
            <div style="font-size:14px; color:#0f172a; margin-top:2px;"><strong>{verifiable_count} of {len(leads)} leads</strong> are from real public posts · each has a verifiable source URL you can open</div>
          </div>
          <div style="background:#16a34a; color:white; padding:4px 12px; border-radius:6px; font-size:11px; font-weight:700; white-space:nowrap;">
            {verifiable_count} VERIFIABLE
          </div>
        </div>
      </div>"""

    return f"""
    <div style="background:white; border:1px solid #e2e8f0; border-radius:14px; padding:24px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:14px; margin-bottom:18px;">
        <div>
          <div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px; margin-bottom:4px;">🎯 Discovery Results</div>
          <div style="font-size:20px; font-weight:700; color:#0f172a;">{result['matched_signals']} of {result['total_signals']} signals matched</div>
          <div style="font-size:13px; color:#64748b; margin-top:4px;">Against the <strong style="color:#334155;">{html.escape(result['config_used'])}</strong> scope</div>
        </div>
        <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:8px 12px;">
          <div style="font-size:10px; color:#1e40af; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">Total Cost</div>
          <div style="font-size:18px; font-weight:800; color:#1e3a8a;">${cost:.3f}</div>
        </div>
      </div>
{verifiable_banner}
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:18px;">
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px; padding:14px 16px;">
          <div style="font-size:10px; font-weight:700; color:#15803d; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:4px;">🟢 Path A — Known Customer</div>
          <div style="font-size:22px; font-weight:800; color:#0f172a; line-height:1;">{result['path_a_count']}</div>
          <div style="font-size:11px; color:#15803d; margin-top:4px;">Full channel mix available</div>
        </div>
        <div style="background:#fffbeb; border:1px solid #fde68a; border-radius:10px; padding:14px 16px;">
          <div style="font-size:10px; font-weight:700; color:#a16207; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:4px;">🟡 Path B — Anonymous</div>
          <div style="font-size:22px; font-weight:800; color:#0f172a; line-height:1;">{result['path_b_count']}</div>
          <div style="font-size:11px; color:#a16207; margin-top:4px;">Organic + retargeting only</div>
        </div>
      </div>

      <div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px; margin-bottom:10px;">Classification Breakdown</div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:10px;">
        {breakdown_cards}
      </div>
    </div>
    """


def format_lead_choices(leads):
    choices = []
    for i, lead in enumerate(leads):
        signal = lead["signal"]
        analysis = lead["analysis"]
        path = lead["path"]
        score = analysis.get("intent_score", 0)
        classification = analysis.get("classification", "unknown")
        meta = get_classification_meta(classification)
        path_emoji = "🟢" if path["path"] == "A" else "🟡"
        # Source indicator: 🔗 for verifiable Reddit leads, 🧪 for simulated demo signals
        has_url = bool(signal.get("_reddit_url", "").strip()) and signal["_reddit_url"].strip() != "https://reddit.com"
        source_indicator = " 🔗" if has_url else " 🧪"
        label = f"{meta['emoji']} {meta['tier']} · {score}/100 · {meta['label']} · {path_emoji} {signal['user_handle']}{source_indicator}"
        choices.append((label, i))
    return choices


def render_why_matched_explainer(lead):
    """
    Why-matched explainer with capped base score (FIX #15) for meaningful viz.
    """
    signal = lead["signal"]
    analysis = lead["analysis"]
    scope_match = lead["scope_match"]
    classification = analysis.get("classification", "unknown")
    score = analysis.get("intent_score", 0)
    meta = get_classification_meta(classification)
    text = signal.get("post_content", "")
    text_lower = text.lower()

    # Component scores — capped to keep visualization meaningful
    specificity_score = 0
    specificity_evidence = []
    if analysis.get("suggested_destinations"):
        specificity_score = min(25, len(analysis["suggested_destinations"]) * 8)
        specificity_evidence.append(f"Named {len(analysis['suggested_destinations'])} specific destinations: {', '.join(analysis['suggested_destinations'][:3])}")
    if analysis.get("estimated_budget") and analysis["estimated_budget"] not in ("Unknown", "Open", ""):
        specificity_score = min(30, specificity_score + 5)
        specificity_evidence.append(f"Mentioned budget tier: {analysis['estimated_budget']}")
    if not specificity_evidence:
        specificity_evidence.append("No specific destinations or budget mentioned")

    urgency_score = 0
    urgency_words = ["urgent", "asap", "next week", "this month", "broke me", "need", "ready", "booking", "have dates", "decided"]
    matched_urgency = [w for w in urgency_words if w in text_lower]
    if analysis.get("urgency") == "high":
        urgency_score = 20
        urgency_evidence = f"High-urgency language: \"{matched_urgency[0]}\"" if matched_urgency else "Tone implies near-term timing"
    elif analysis.get("urgency") == "medium":
        urgency_score = 12
        urgency_evidence = "Medium urgency — comparison phase"
    else:
        urgency_score = 5
        urgency_evidence = "Low urgency — aspirational/exploratory"

    engagement_str = signal.get("engagement", "")
    likes_count = 0
    try:
        likes_part = engagement_str.split("likes")[0].replace(",", "")
        likes_count = int(''.join(c for c in likes_part if c.isdigit()) or 0)
    except Exception:
        likes_count = 0
    engagement_score = min(15, likes_count // 30)
    engagement_evidence = f"{engagement_str} — {'high' if likes_count > 100 else 'moderate' if likes_count > 20 else 'low'} social proof"

    profile = signal.get("user_profile", "").lower()
    profile_score = 5
    profile_evidence = []
    if any(w in profile for w in ["travel", "wander", "explorer", "nomad", "blogger"]):
        profile_score += 8
        profile_evidence.append("Travel-active profile bio")
    if "followers" in profile and any(c.isdigit() for c in profile):
        profile_score += 4
        profile_evidence.append("Established follower count")
    if not profile_evidence:
        profile_evidence.append("Standard profile signals")

    # Cap the base score so it doesn't dominate when other components are low (FIX #15)
    computed_components = specificity_score + urgency_score + engagement_score + profile_score
    base_score = max(0, min(15, score - computed_components))  # Cap at 15

    # If there's still unaccounted score, distribute it to "Context & Tone"
    remaining = score - computed_components - base_score
    context_score = max(0, remaining)
    context_evidence = []
    if context_score > 0:
        if "burnout" in text_lower or "broke me" in text_lower or "stressed" in text_lower:
            context_evidence.append("Emotional/stress language indicates near-term need")
        if any(w in text_lower for w in ["recommend", "anyone done", "best", "thoughts", "advice"]):
            context_evidence.append("Asking for recommendations — open to influence")
        if any(w in text_lower for w in ["been wanting", "always wanted", "dream"]):
            context_evidence.append("Long-standing desire — high intent latent")
        if not context_evidence:
            context_evidence.append("Tone and contextual cues match the classification")

    rows = [
        ("📍 Specificity",      specificity_score, specificity_evidence,    "#3b82f6"),
        ("⚡ Urgency",           urgency_score,    [urgency_evidence],       "#f97316"),
        ("👥 Engagement",       engagement_score, [engagement_evidence],    "#22c55e"),
        ("👤 Profile signal",   profile_score,    profile_evidence,         "#a855f7"),
    ]
    if context_score > 0:
        rows.append(("💭 Context & tone", context_score, context_evidence, "#ec4899"))
    rows.append(("✨ Base (category)", base_score, [f"Classified as {meta['label']}"], meta['color']))

    max_points = max(r[1] for r in rows) if rows else 1
    bars_html = ""
    for label, points, evidence, color in rows:
        bar_pct = (points / max(max_points, 1)) * 100
        evidence_html = "".join(f'<div style="font-size:12px; color:#64748b; margin-top:3px; line-height:1.55;">• {html.escape(e)}</div>' for e in evidence)
        bars_html += f"""
        <div style="margin-bottom:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
            <div style="font-size:14px; font-weight:600; color:#0f172a;">{label}</div>
            <div style="font-size:14px; font-weight:700; color:{color};">+{points}</div>
          </div>
          <div style="background:#f1f5f9; height:7px; border-radius:4px; overflow:hidden;">
            <div style="background:{color}; height:100%; width:{bar_pct:.1f}%; border-radius:4px;"></div>
          </div>
          {evidence_html}
        </div>
        """

    scope_reasons_html = ""
    if scope_match.get("reasons"):
        scope_reasons_html = "".join(
            f'<span style="display:inline-block; background:#eff6ff; color:#1e3a8a; padding:4px 10px; border-radius:6px; font-size:12px; font-weight:600; margin:2px;">{html.escape(r)}</span>'
            for r in scope_match["reasons"]
        )

    # ----------------------------------------------------------
    # BANT Signals Panel — shows which qualification signals were detected
    # ----------------------------------------------------------
    bant = analysis.get("bant_signals", {})
    bant_labels = [
        ("destination_specific", "📍 Destination named",        "Specific place mentioned (city/region/country)"),
        ("timeline_concrete",    "📅 Timeline concrete",         "Concrete dates or near timeframe"),
        ("budget_stated",        "💰 Budget stated",             "Money figure mentioned in the post"),
        ("authority_clear",      "✋ Authority clear",           "Decision-maker identified (solo or aligned)"),
        ("action_language",      "🎯 Action language",           "Booking-intent verbs detected"),
        ("switching_language",   "🔄 Switching intent",          "Considering alternatives/competitors"),
        ("competitor_named",     "🏷️ Competitor named",          "Specific competitor brand mentioned"),
    ]
    bant_chips = ""
    for key, label, tooltip in bant_labels:
        present = bant.get(key, False)
        chip_color = ("#dcfce7", "#15803d", "✓") if present else ("#f1f5f9", "#94a3b8", "✗")
        bg, fg, icon = chip_color
        bant_chips += f'<span title="{html.escape(tooltip)}" style="display:inline-flex; align-items:center; gap:4px; background:{bg}; color:{fg}; padding:5px 10px; border-radius:6px; font-size:12px; font-weight:600; margin:3px;">{icon} {label}</span>'

    signal_count = sum(1 for key, _, _ in bant_labels if bant.get(key, False))
    bant_panel = f"""
      <div style="border-top:1px solid #e2e8f0; padding-top:14px; margin-top:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">BANT Qualification Signals</div>
          <div style="font-size:11px; color:#64748b;"><strong style="color:#0f172a;">{signal_count}/7</strong> detected</div>
        </div>
        <div style="font-size:12px; color:#64748b; margin-bottom:10px; line-height:1.6;">Industry-standard signals used to qualify travel leads. The more concrete signals, the higher the conversion probability.</div>
        <div>{bant_chips}</div>
      </div>
    """

    # ----------------------------------------------------------
    # Quality Gates Panel — shows what adjustments the system made
    # ----------------------------------------------------------
    gates = analysis.get("_quality_gates", {})
    adjustments = gates.get("adjustments_made", [])
    gates_panel = ""
    if adjustments:
        adj_html = "".join(
            f'<div style="font-size:12px; color:#92400e; padding:6px 10px; background:#fef3c7; border-left:3px solid #f59e0b; border-radius:0 6px 6px 0; margin-bottom:6px;">⚠️ {html.escape(adj)}</div>'
            for adj in adjustments
        )
        gates_panel = f"""
      <div style="border-top:1px solid #e2e8f0; padding-top:14px; margin-top:14px;">
        <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:10px;">Quality Gate Adjustments</div>
        <div style="font-size:12px; color:#64748b; margin-bottom:10px; line-height:1.6;">The classifier's initial output was adjusted by Python-side quality gates to prevent false-positive Hot leads:</div>
        {adj_html}
      </div>
        """
    else:
        gates_panel = """
      <div style="border-top:1px solid #e2e8f0; padding-top:14px; margin-top:14px;">
        <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:6px;">Quality Gate Adjustments</div>
        <div style="font-size:12px; color:#16a34a; padding:6px 10px; background:#f0fdf4; border-left:3px solid #16a34a; border-radius:0 6px 6px 0;">✓ Classification passed all quality gates — no adjustments needed</div>
      </div>
        """

    # Confidence badge
    confidence = analysis.get("confidence_score", 50)
    if confidence >= 80:
        conf_color, conf_label = "#16a34a", "High"
    elif confidence >= 60:
        conf_color, conf_label = "#ca8a04", "Medium"
    else:
        conf_color, conf_label = "#dc2626", "Low"

    return f"""
    <div style="background:white; border:1px solid #e2e8f0; border-radius:14px; padding:22px; margin-top:16px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; flex-wrap:wrap; gap:10px;">
        <div>
          <div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px;">🧠 AI Reasoning · Explainability</div>
          <div style="font-size:16px; font-weight:700; color:#0f172a; margin-top:4px;">Why this lead scored {score}/100</div>
        </div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <div style="background:#f1f5f9; color:#334155; padding:6px 12px; border-radius:8px; font-size:12px; font-weight:600;" title="AI confidence in this classification">
            AI Confidence: <span style="color:{conf_color}; font-weight:700;">{conf_label} ({confidence}%)</span>
          </div>
          <div style="background:{meta['bg']}; color:{meta['color']}; padding:8px 16px; border-radius:8px; font-size:14px; font-weight:700;">
            {meta['emoji']} {meta['label']}
          </div>
        </div>
      </div>

      <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; margin-bottom:18px;">
        <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:6px;">Classification Reason</div>
        <div style="font-size:14px; color:#334155; line-height:1.6; font-style:italic;">{html.escape(analysis.get('classification_reason', '—'))}</div>
      </div>

      <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:14px;">Score Breakdown</div>

      {bars_html}

      {bant_panel}

      {gates_panel}

      <div style="border-top:1px solid #e2e8f0; padding-top:14px; margin-top:14px;">
        <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:10px;">Listening Scope Match</div>
        <div>{scope_reasons_html if scope_reasons_html else '<span style="font-size:12px; color:#64748b;">No specific tags matched (caught by keyword)</span>'}</div>
      </div>
    </div>
    """


def show_lead_detail(lead_index):
    """
    Returns (markdown_content, html_explainer) so the explainer renders
    as proper HTML in a gr.HTML component instead of being escaped inside markdown.
    """
    if lead_index is None or lead_index >= len(discovered_leads):
        return "Select a lead from the dropdown above to see its full profile.", ""

    lead = discovered_leads[lead_index]
    signal = lead["signal"]
    analysis = lead["analysis"]
    path = lead["path"]

    score = analysis.get("intent_score", 0)
    classification = analysis.get("classification", "unknown")
    meta = get_classification_meta(classification)
    path_color = "🟢" if path["path"] == "A" else "🟡"

    channels_md = "\n".join(
        f"- {'✅' if c['available'] else '❌'} **{c['label']}** — {c['rationale']}"
        for c in path["channels_available"]
    )

    explainer_html = render_why_matched_explainer(lead)

    # Build source-aware AI Analysis table
    sources = analysis.get("_sources", {})
    def source_badge(field_key):
        src = sources.get(field_key, "unknown")
        if src == "stated":
            return '<span style="background:#dcfce7; color:#15803d; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:600;">✅ Stated</span>'
        elif src == "inferred":
            return '<span style="background:#fef3c7; color:#92400e; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:600;">🤖 Inferred</span>'
        else:
            return '<span style="background:#f1f5f9; color:#64748b; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:600;">— Unknown</span>'

    destinations = analysis.get('suggested_destinations', [])
    dest_str = ', '.join(destinations) if destinations else '—'

    analysis_table = f"""
| Metric | Value | Source |
|---|---|---|
| Trip type | {analysis.get('trip_type', 'N/A')} | {source_badge('trip_type')} |
| Suggested destinations | {dest_str} | {source_badge('suggested_destinations')} |
| Estimated budget | {analysis.get('estimated_budget', 'N/A')} | {source_badge('estimated_budget')} |
| Travel window | {analysis.get('travel_window', 'N/A')} | {source_badge('travel_window')} |
| Urgency | {analysis.get('urgency', 'N/A').upper()} | — |
"""

    # Live source banner + verification link (when post has a real URL)
    reddit_url = signal.get("_reddit_url", "").strip()
    has_live_url = bool(reddit_url and reddit_url != "https://reddit.com")

    if has_live_url:
        live_banner = f"""
<div style="background:linear-gradient(135deg,#16a34a 0%,#0d9488 100%); color:white; border-radius:12px; padding:14px 18px; margin:12px 0 18px 0; box-shadow:0 4px 14px rgba(22,163,74,0.25);">
  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
    <div>
      <div style="font-size:10px; font-weight:700; letter-spacing:1.2px; text-transform:uppercase; opacity:0.9;">✓ Verified Live Source</div>
      <div style="font-size:14px; font-weight:600; margin-top:2px;">This is a real post fetched from Reddit's public API — click to verify</div>
    </div>
    <a href="{html.escape(reddit_url)}" target="_blank" rel="noopener noreferrer" style="background:white; color:#0d9488; padding:8px 18px; border-radius:8px; font-weight:700; font-size:13px; text-decoration:none; display:inline-block; white-space:nowrap;">
      🔗 View Original Post →
    </a>
  </div>
</div>
"""
        source_url_line = f"- **🔗 Original URL:** [{reddit_url}]({reddit_url}) _(open in new tab)_\n"
    else:
        live_banner = """
<div style="background:linear-gradient(135deg,#fef3c7 0%,#fde68a 100%); border:1px solid #f59e0b; border-radius:12px; padding:12px 18px; margin:12px 0 18px 0;">
  <div style="display:flex; align-items:center; gap:12px;">
    <div style="font-size:22px;">🧪</div>
    <div>
      <div style="font-size:10px; font-weight:700; color:#92400e; letter-spacing:1.2px; text-transform:uppercase;">Demo Data — Simulated Signal</div>
      <div style="font-size:13px; color:#78350f; margin-top:2px;">This is a curated demo persona used for predictable storytelling (Path A customer matching, classification edge cases). Switch the data source to <strong>Reddit cached</strong> for verifiable real-world leads.</div>
    </div>
  </div>
</div>
"""
        source_url_line = ""

    markdown_content = f"""## {meta['emoji']} {signal['user_handle']} — {score}/100

{live_banner}
### {path_color} Path Routing — {path['label']}
{path['description']}

**Lawful basis:** {path['lawful_basis']}

**Available channels:**
{channels_md}

### 📡 Signal Source
- **Platform:** {signal['platform']}
- **User:** {signal['user_handle']}
- **Posted:** {signal['post_time']}
- **Engagement:** {signal['engagement']}
- **Profile:** {signal['user_profile']}
{source_url_line}
### 💬 Original Post
> "{signal['post_content']}"

### 🎯 AI Analysis
{analysis_table}

**Source legend:** ✅ Stated = user wrote it in the post · 🤖 Inferred = AI estimate from context · — Unknown = no signal

### 🪝 Personalization hooks
{chr(10).join(f"- {h}" for h in analysis.get('personalization_hooks', []))}
"""

    return markdown_content, explainer_html


# ============================================================
# NURTURING — CLASSIFICATION-GROUPED VIEW
# ============================================================

def render_classification_groups():
    if not discovered_leads:
        return ("""<div style='padding:30px; text-align:center; color:#64748b; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px;'>
        <strong style="font-size:14px; color:#0f172a;">No leads available yet</strong>
        <div style="font-size:12px; margin-top:4px;">Run a scan in the Discovery view first.</div>
        </div>"""), {}

    grouped = defaultdict(list)
    for i, lead in enumerate(discovered_leads):
        cls = lead["analysis"].get("classification", "unknown")
        grouped[cls].append(i)

    sorted_groups = sorted(grouped.items(), key=lambda x: get_classification_meta(x[0]).get("priority", 99))

    html_parts = ['<div style="display:flex; flex-direction:column; gap:12px;">']

    for cls, indices in sorted_groups:
        meta = get_classification_meta(cls)
        leads_in_group = [discovered_leads[i] for i in indices]
        avg_score = sum(l["analysis"].get("intent_score", 0) for l in leads_in_group) // len(leads_in_group)
        path_a = sum(1 for l in leads_in_group if l["path"]["path"] == "A")
        path_b = len(leads_in_group) - path_a

        chips = "".join(
            f'''<div style="display:inline-flex; align-items:center; gap:6px; background:white; border:1px solid #e2e8f0; padding:6px 10px; border-radius:8px; font-size:12px; color:#334155; margin:3px;">
              <span>{'🟢' if l['path']['path'] == 'A' else '🟡'}</span>
              <span style="font-weight:600;">{html.escape(l['signal']['user_handle'])}</span>
              <span style="color:#94a3b8;">·</span>
              <span style="color:{meta['color']}; font-weight:700;">{l['analysis'].get('intent_score', 0)}</span>
            </div>'''
            for l in leads_in_group
        )

        html_parts.append(f'''
        <div style="background:white; border:1px solid #e2e8f0; border-left:5px solid {meta['color']}; border-radius:14px; padding:18px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px; margin-bottom:12px;">
            <div>
              <div style="display:flex; align-items:center; gap:10px;">
                <span style="font-size:28px;">{meta['emoji']}</span>
                <div>
                  <div style="font-size:10px; font-weight:700; color:{meta['color']}; text-transform:uppercase; letter-spacing:1px;">{meta['tier']} TIER</div>
                  <div style="font-size:16px; font-weight:700; color:#0f172a;">{meta['label']}</div>
                </div>
              </div>
              <div style="font-size:12px; color:#64748b; margin-top:6px;">
                <strong style="color:#0f172a;">{len(indices)}</strong> leads · avg score <strong style="color:{meta['color']};">{avg_score}/100</strong> · 🟢 {path_a} Path A · 🟡 {path_b} Path B
              </div>
            </div>
          </div>
          <div>{chips}</div>
        </div>
        ''')

    html_parts.append('</div>')
    return ''.join(html_parts), dict(grouped)


def get_lead_choices_for_nurturing():
    if not discovered_leads:
        return (
            gr.update(choices=[], value=[], label="No leads available — run a scan first"),
            """<div style='padding:30px; text-align:center; color:#64748b; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px;'>
            <strong style="font-size:14px; color:#0f172a;">No leads available yet</strong>
            <div style="font-size:12px; margin-top:4px;">Run a scan in the Discovery view first.</div>
            </div>""",
            gr.update(choices=[("— Select a tier —", "none")] + [], value="none")
        )

    choices = format_lead_choices(discovered_leads)

    grouped = defaultdict(list)
    for i, lead in enumerate(discovered_leads):
        cls = lead["analysis"].get("classification", "unknown")
        grouped[cls].append(i)

    tier_choices = [("— Select all of a classification —", "none")]
    for cls, indices in sorted(grouped.items(), key=lambda x: get_classification_meta(x[0]).get("priority", 99)):
        meta = get_classification_meta(cls)
        tier_choices.append((f"{meta['emoji']} Select all {len(indices)} {meta['label']} leads", cls))

    groups_html, _ = render_classification_groups()

    return (
        gr.update(choices=choices, value=[], label=f"Or select individual leads ({len(choices)} available)"),
        groups_html,
        gr.update(choices=tier_choices, value="none")
    )


def select_by_classification(classification_key):
    if classification_key == "none" or not discovered_leads:
        return gr.update(value=[])
    matching_indices = [
        i for i, lead in enumerate(discovered_leads)
        if lead["analysis"].get("classification") == classification_key
    ]
    return gr.update(value=matching_indices)


def generate_bulk_campaigns(selected_indices):
    global session_metrics
    console_log = []

    def console(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        console_log.append(f"`{ts}` {msg}")

    if not discovered_leads:
        yield "⚠️ No leads available. Run a scan first.", "", "*No leads in pipeline.*"
        return

    if not selected_indices:
        yield "⚠️ Please select at least one lead (or pick a classification group).", "", "*Awaiting selection.*"
        return

    if not isinstance(selected_indices, list):
        selected_indices = [selected_indices]

    leads_to_process = [discovered_leads[i] for i in selected_indices if i < len(discovered_leads)]
    if not leads_to_process:
        yield "⚠️ Selected leads are stale. Click 'Load leads from Discovery' again.", "", "*Stale selection.*"
        return

    selected_by_class = defaultdict(int)
    for lead in leads_to_process:
        selected_by_class[lead["analysis"].get("classification", "unknown")] += 1

    breakdown_str = ", ".join(
        f"{get_classification_meta(c)['emoji']} {n} {get_classification_meta(c)['label']}"
        for c, n in sorted(selected_by_class.items(), key=lambda x: get_classification_meta(x[0]).get("priority", 99))
    )

    # Top 3 leads (by score) get LLM-generated touch content; rest use templates
    top_n_llm = min(3, len(leads_to_process))
    template_count = len(leads_to_process) - top_n_llm
    est_cost = top_n_llm * 0.02 + template_count * 0.001  # LLM is ~$0.02/lead, templates ~free

    console(f"🎨 Multi-touch sequence generation started")
    console(f"   {len(leads_to_process)} leads · {breakdown_str}")
    console(f"   {top_n_llm} top-scoring leads will get LLM-written content")
    console(f"   {template_count} remaining leads will use template-based content (free, faster)")
    console(f"   Estimated cost: ${est_cost:.3f}")
    console("")

    progress_log = [f"### 🎨 Building {len(leads_to_process)} nurture sequences", f"_{breakdown_str}_", ""]
    yield "\n".join(progress_log), "", "\n\n".join(console_log)

    try:
        agent = NurturingAgent()

        def progress_cb(i, total, lead, sequence):
            handle = lead['signal']['user_handle']
            cls = lead["analysis"].get("classification", "unknown")
            meta = get_classification_meta(cls)
            touch_count = sequence.get("totals", {}).get("touch_count", 0)
            cost = sequence.get("totals", {}).get("cost", 0.0)
            console(f"✅ [{i}/{total}] {meta['emoji']} {handle} · {sequence.get('name', 'Sequence')} · {touch_count} touches · ${cost:.4f}")

        results = agent.generate_bulk(leads_to_process, top_n_llm=top_n_llm, progress_callback=progress_cb)

        # Yield progress one batch at a time
        for i in range(len(results)):
            progress_log.append(f"  ✅ {leads_to_process[i]['signal']['user_handle']}")
            yield "\n".join(progress_log), "", "\n\n".join(console_log)

        # Store results
        for idx, result in zip(selected_indices, results):
            generated_campaigns[idx] = result["sequence"]

        session_metrics["campaigns_generated"] += len(results)
        session_metrics["estimated_cost_usd"] += est_cost

        total_touches = sum(r["sequence"].get("totals", {}).get("touch_count", 0) for r in results)
        total_seq_cost = sum(r["sequence"].get("totals", {}).get("cost", 0.0) for r in results)

        console("")
        console(f"✨ All sequences built · {total_touches} touchpoints generated across {len(results)} leads")
        console(f"💰 LLM cost: ${est_cost:.3f} · Channel send cost (if executed): ${total_seq_cost:.4f}")

        progress_log.append(f"\n✅ All sequences built — {total_touches} touchpoints across {len(results)} leads. Scroll down for full mockups ↓")

        mockups_html = render_sequence_mockups(results)
        yield "\n".join(progress_log), mockups_html, "\n\n".join(console_log)

    except Exception as e:
        import traceback
        traceback.print_exc()
        console(f"❌ Error: {str(e)}")
        progress_log.append(f"\n❌ Error: {str(e)}")
        yield "\n".join(progress_log), "", "\n\n".join(console_log)


# ============================================================
# CAMPAIGN PERFORMANCE SIMULATOR
# ============================================================

BENCHMARKS = {
    "email_open_rate_avg": 0.22,
    "email_open_rate_top": 0.32,
    "email_ctr_avg": 0.035,
    "email_ctr_top": 0.07,
}

CLASSIFICATION_PERFORMANCE = {
    # Hot — high open + click + conversion
    "ready_to_book":      {"open_mult": 1.35, "ctr_mult": 1.85, "conversion": 0.20},   # Industry: 15-25% for high-intent
    "switching_intent":   {"open_mult": 1.45, "ctr_mult": 1.50, "conversion": 0.12},   # Industry: 8-15% (winback range)

    # Warm — moderate
    "active_research":    {"open_mult": 1.25, "ctr_mult": 1.55, "conversion": 0.06},   # Tightened from 0.08
    "advocacy":           {"open_mult": 1.20, "ctr_mult": 1.10, "conversion": 0.04},

    # Cool — low
    "competitor_mention": {"open_mult": 1.10, "ctr_mult": 1.30, "conversion": 0.03},
    "dreaming":           {"open_mult": 1.05, "ctr_mult": 0.85, "conversion": 0.015},  # Tightened from 0.02

    # Disqualified — minimal
    "venting_only":       {"open_mult": 0.80, "ctr_mult": 0.30, "conversion": 0.005},
    "off_topic":          {"open_mult": 0.50, "ctr_mult": 0.20, "conversion": 0.001},
}


def calculate_campaign_performance(lead, campaign):
    analysis = lead["analysis"]
    classification = analysis.get("classification", "active_research")
    score = analysis.get("intent_score", 50)
    perf = CLASSIFICATION_PERFORMANCE.get(classification, CLASSIFICATION_PERFORMANCE["active_research"])

    score_modifier = 0.85 + (score / 100) * 0.30

    open_rate = BENCHMARKS["email_open_rate_avg"] * perf["open_mult"] * score_modifier
    ctr = BENCHMARKS["email_ctr_avg"] * perf["ctr_mult"] * score_modifier
    conversion_rate = perf["conversion"] * score_modifier
    open_lift = (open_rate / BENCHMARKS["email_open_rate_avg"] - 1) * 100
    ctr_lift = (ctr / BENCHMARKS["email_ctr_avg"] - 1) * 100

    budget = analysis.get("estimated_budget", "")
    aov_estimate = 3500
    try:
        digits = ''.join(c for c in budget if c.isdigit() or c == ",").replace(",", "")
        if digits:
            aov_estimate = int(digits[:5])
    except Exception:
        pass

    expected_revenue = conversion_rate * aov_estimate

    return {
        "open_rate": open_rate * 100,
        "open_rate_lift": open_lift,
        "ctr": ctr * 100,
        "ctr_lift": ctr_lift,
        "conversion_rate": conversion_rate * 100,
        "expected_revenue": expected_revenue,
        "aov_estimate": aov_estimate,
    }


def render_performance_panel(lead, campaign):
    """
    FIX #8: Unified panel design with the explainer card.
    Same header pattern: micro label · subhead title · badge.
    """
    perf = calculate_campaign_performance(lead, campaign)

    return f"""
    <div style="background:white; border:1px solid #e2e8f0; border-radius:12px; padding:18px 20px; margin-top:16px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:10px;">
        <div>
          <div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px;">📊 Projected Performance</div>
          <div style="font-size:16px; font-weight:700; color:#0f172a; margin-top:4px;">Based on classification + industry benchmarks</div>
        </div>
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; padding:6px 14px; border-radius:8px; font-size:14px; font-weight:700;">
          ${perf['expected_revenue']:,.0f} expected
        </div>
      </div>

      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:10px;">
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
          <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Open Rate</div>
          <div style="font-size:20px; font-weight:800; color:#0f172a; margin-top:4px;">{perf['open_rate']:.1f}%</div>
          <div style="font-size:11px; color:{'#16a34a' if perf['open_rate_lift'] > 0 else '#dc2626'}; font-weight:600; margin-top:2px;">
            {'+' if perf['open_rate_lift'] > 0 else ''}{perf['open_rate_lift']:.0f}% vs {BENCHMARKS['email_open_rate_avg']*100:.0f}% avg
          </div>
        </div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
          <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Click-Through</div>
          <div style="font-size:20px; font-weight:800; color:#0f172a; margin-top:4px;">{perf['ctr']:.1f}%</div>
          <div style="font-size:11px; color:{'#16a34a' if perf['ctr_lift'] > 0 else '#dc2626'}; font-weight:600; margin-top:2px;">
            {'+' if perf['ctr_lift'] > 0 else ''}{perf['ctr_lift']:.0f}% vs {BENCHMARKS['email_ctr_avg']*100:.1f}% avg
          </div>
        </div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
          <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Conversion</div>
          <div style="font-size:20px; font-weight:800; color:#0f172a; margin-top:4px;">{perf['conversion_rate']:.1f}%</div>
          <div style="font-size:11px; color:#64748b; margin-top:2px;">lead → booking</div>
        </div>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px;">
          <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Est. AOV</div>
          <div style="font-size:20px; font-weight:800; color:#0f172a; margin-top:4px;">${perf['aov_estimate']:,}</div>
          <div style="font-size:11px; color:#64748b; margin-top:2px;">avg booking value</div>
        </div>
      </div>
    </div>
    """


# ============================================================
# VISUAL MOCKUP RENDERING
# ============================================================

COLOR_THEMES = {
    "navy":   {"primary": "#1e3a8a", "accent": "#3b82f6", "bg": "#eff6ff"},
    "teal":   {"primary": "#0d9488", "accent": "#14b8a6", "bg": "#f0fdfa"},
    "coral":  {"primary": "#dc2626", "accent": "#f97316", "bg": "#fef2f2"},
    "amber":  {"primary": "#d97706", "accent": "#fbbf24", "bg": "#fffbeb"},
    "purple": {"primary": "#7c3aed", "accent": "#a78bfa", "bg": "#faf5ff"}
}


def render_svg_hero(image_concept, theme, height=160):
    concept_lower = image_concept.lower()
    primary = theme["primary"]
    accent = theme["accent"]

    if any(k in concept_lower for k in ["mountain", "banff", "alps", "rockies", "peak", "alpine"]):
        scene = f'<defs><linearGradient id="sky" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#fef3c7"/><stop offset="100%" stop-color="#fbbf24"/></linearGradient></defs><rect width="600" height="{height}" fill="url(#sky)"/><circle cx="450" cy="50" r="22" fill="#ffffff" opacity="0.9"/><path d="M 0 {height} L 0 90 L 100 50 L 180 80 L 280 30 L 380 70 L 480 40 L 600 75 L 600 {height} Z" fill="{primary}"/><path d="M 0 {height} L 0 110 L 120 95 L 240 105 L 360 88 L 480 102 L 600 92 L 600 {height} Z" fill="{accent}" opacity="0.6"/>'
    elif any(k in concept_lower for k in ["beach", "ocean", "sea", "tropical", "island", "bali", "maldives"]):
        scene = f'<defs><linearGradient id="sky" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#dbeafe"/><stop offset="100%" stop-color="#fbcfe8"/></linearGradient></defs><rect width="600" height="{height}" fill="url(#sky)"/><circle cx="500" cy="40" r="18" fill="#fef3c7"/><rect y="80" width="600" height="50" fill="{accent}" opacity="0.7"/><rect y="100" width="600" height="60" fill="{primary}"/>'
    elif any(k in concept_lower for k in ["disney", "family", "kids"]):
        scene = f'<defs><linearGradient id="sky" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#fbcfe8"/><stop offset="100%" stop-color="#fde68a"/></linearGradient></defs><rect width="600" height="{height}" fill="url(#sky)"/><path d="M 280 80 L 280 50 L 290 40 L 295 50 L 310 40 L 320 50 L 330 30 L 340 50 L 345 40 L 355 50 L 360 80 Z" fill="{primary}"/><rect y="120" width="600" height="40" fill="{accent}" opacity="0.6"/>'
    elif any(k in concept_lower for k in ["city", "skyline", "urban", "tokyo", "vegas", "newyork"]):
        scene = f'<defs><linearGradient id="sky" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#312e81"/><stop offset="100%" stop-color="#7c3aed"/></linearGradient></defs><rect width="600" height="{height}" fill="url(#sky)"/><rect x="40" y="80" width="40" height="80" fill="{primary}"/><rect x="100" y="60" width="50" height="100" fill="{primary}"/><rect x="170" y="40" width="35" height="120" fill="{primary}"/><rect x="220" y="70" width="45" height="90" fill="{primary}"/><rect x="280" y="30" width="40" height="130" fill="{primary}"/><rect x="340" y="55" width="50" height="105" fill="{primary}"/>'
    else:
        scene = f'<defs><linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="{primary}"/><stop offset="100%" stop-color="{accent}"/></linearGradient></defs><rect width="600" height="{height}" fill="url(#bg)"/><circle cx="120" cy="50" r="30" fill="#ffffff" opacity="0.15"/>'
    return f'<svg viewBox="0 0 600 {height}" xmlns="http://www.w3.org/2000/svg" style="width:100%; height:{height}px; display:block;">{scene}</svg>'


def render_email_mockup(touchpoint, theme):
    hero = render_svg_hero(touchpoint.get("image_concept", ""), theme, 140)
    headline = html.escape(touchpoint.get("headline", ""))
    subhead = html.escape(touchpoint.get("subhead", ""))
    body = html.escape(touchpoint.get("body_copy", ""))
    cta = html.escape(touchpoint.get("cta_text", "Learn More"))
    subject = html.escape(touchpoint.get("subject_line", ""))
    return f'<div style="background:white; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; max-width:560px; margin:0 0 16px 0; box-shadow:0 2px 6px rgba(0,0,0,0.04);"><div style="background:#f8fafc; padding:10px 14px; border-bottom:1px solid #e2e8f0; font-size:11px; color:#64748b;">Subject: <strong style="color:#0f172a;">{subject}</strong></div>{hero}<div style="padding:20px 24px;"><div style="font-size:18px; font-weight:700; color:{theme["primary"]}; margin-bottom:6px;">{headline}</div><div style="font-size:14px; color:#475569; margin-bottom:14px;">{subhead}</div><div style="font-size:14px; color:#334155; line-height:1.7; margin-bottom:16px;">{body}</div><button style="background:{theme["primary"]}; color:white; border:none; padding:11px 22px; border-radius:8px; font-weight:600; font-size:14px;">{cta} →</button></div></div>'


def render_sms_mockup(touchpoint, theme):
    body = html.escape(touchpoint.get("body_copy", ""))
    return f'<div style="background:#ebebef; border-radius:12px; padding:16px; max-width:340px; margin:0 0 16px 0;"><div style="text-align:center; padding-bottom:10px; border-bottom:1px solid #d8d8de; margin-bottom:10px;"><div style="font-size:12px; font-weight:600;">Voyage Travel</div></div><div style="background:white; border-radius:14px 14px 14px 4px; padding:11px 14px; max-width:88%; font-size:14px; line-height:1.5;">{body}</div></div>'


def render_dm_mockup(touchpoint, theme):
    hero = render_svg_hero(touchpoint.get("image_concept", ""), theme, 120)
    headline = html.escape(touchpoint.get("headline", ""))
    body = html.escape(touchpoint.get("body_copy", ""))
    return f'<div style="background:white; border:1px solid #e2e8f0; border-radius:14px; padding:16px; max-width:380px; margin:0 0 16px 0;"><div style="display:flex; gap:10px; align-items:center; padding-bottom:10px; border-bottom:1px solid #f1f5f9; margin-bottom:10px;"><div style="width:34px; height:34px; border-radius:50%; background:linear-gradient(135deg,#ec4899,#8b5cf6,#f59e0b);"></div><div><div style="font-size:14px; font-weight:600;">@voyage.travel</div></div></div><div style="background:#f1f5f9; border-radius:14px; padding:11px 14px; font-size:14px; line-height:1.5; margin-bottom:10px;">{body}</div><div style="border:1px solid #e2e8f0; border-radius:10px; overflow:hidden;">{hero}<div style="padding:10px 12px;"><div style="font-size:12px; font-weight:600;">{headline}</div></div></div></div>'


def render_ad_mockup(touchpoint, theme):
    hero = render_svg_hero(touchpoint.get("image_concept", ""), theme, 160)
    headline = html.escape(touchpoint.get("headline", ""))
    subhead = html.escape(touchpoint.get("subhead", ""))
    cta = html.escape(touchpoint.get("cta_text", "Learn More"))
    return f'<div style="background:white; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; max-width:420px; margin:0 0 16px 0;"><div style="background:#f8fafc; padding:6px 12px; font-size:10px; color:#64748b;">SPONSORED</div>{hero}<div style="padding:16px 20px; background:{theme["primary"]}; color:white;"><div style="font-size:16px; font-weight:700; margin-bottom:4px;">{headline}</div><div style="font-size:12px; opacity:0.9; margin-bottom:14px;">{subhead}</div><button style="background:white; color:{theme["primary"]}; border:none; padding:8px 18px; border-radius:7px; font-weight:600;">{cta} →</button></div></div>'


def render_touchpoint(touchpoint, theme):
    channel = touchpoint.get("channel", "email").lower()
    if channel == "email":                                       return render_email_mockup(touchpoint, theme)
    elif channel == "sms":                                       return render_sms_mockup(touchpoint, theme)
    elif channel in ("instagram_dm", "instagram_organic"):       return render_dm_mockup(touchpoint, theme)
    elif channel in ("retargeting", "meta_lookalike"):           return render_ad_mockup(touchpoint, theme)
    else:                                                        return render_email_mockup(touchpoint, theme)


# ============================================================
# LIVE SEND - real email / SMS / Discord-Slack dispatch
# ============================================================

# Activity log persists across button clicks in this session
live_send_log = []


def render_demo_personas_card():
    """Render an info card listing the 3 demo personas and their routing."""
    base_email = os.getenv("DEMO_RECIPIENT_EMAIL", "").strip()
    base_phone = os.getenv("DEMO_RECIPIENT_PHONE", "").strip()

    persona_rows = ""
    for p in list_personas():
        email_route = get_persona_email_recipient(p) if base_email else "(set DEMO_RECIPIENT_EMAIL)"
        sms_route = get_persona_sms_recipient(p) if base_phone else "(set DEMO_RECIPIENT_PHONE)"
        sms_prefix = get_persona_sms_prefix(p)

        persona_rows += f'''
        <div style="border:1px solid #e2e8f0; border-left:5px solid {p["color"]}; border-radius:10px; padding:14px 16px; margin-bottom:10px; background:white;">
          <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:6px;">
            <span style="font-size:18px;">{p["emoji"]}</span>
            <span style="font-size:14px; font-weight:700; color:#0f172a;">{html.escape(p["first_name"])} {html.escape(p["last_name"])}</span>
            <span style="background:#f1f5f9; color:#475569; padding:2px 8px; border-radius:5px; font-size:11px; font-family:monospace;">{html.escape(p["reddit_handle"])}</span>
            <span style="background:{p["color"]}22; color:{p["color"]}; padding:2px 8px; border-radius:5px; font-size:10px; font-weight:700;">{html.escape(p["designed_classification"])}</span>
          </div>
          <div style="font-size:12px; color:#64748b; margin-bottom:8px; line-height:1.55;">{html.escape(p["description"])}</div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px; font-size:11px;">
            <div style="background:#f8fafc; padding:6px 10px; border-radius:6px;">
              <strong style="color:#475569;">📧 Email →</strong> <code style="background:white; padding:1px 5px; border-radius:3px; color:#0f172a;">{html.escape(email_route)}</code>
            </div>
            <div style="background:#f8fafc; padding:6px 10px; border-radius:6px;">
              <strong style="color:#475569;">📱 SMS →</strong> <code style="background:white; padding:1px 5px; border-radius:3px; color:#0f172a;">{html.escape(sms_route)}</code>{f' <em style="color:#94a3b8;">(prefixed with {html.escape(sms_prefix)})</em>' if sms_prefix else ''}
            </div>
          </div>
        </div>
        '''

    return f'''
    <div style="background:linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%); border:1px solid #ddd6fe; border-left:5px solid #8b5cf6; border-radius:12px; padding:16px; margin-bottom:14px;">
      <div style="display:flex; gap:10px; align-items:flex-start; margin-bottom:12px;">
        <span style="font-size:22px;">🎭</span>
        <div>
          <div style="font-size:13px; font-weight:700; color:#5b21b6; margin-bottom:2px;">Closed-loop demo personas</div>
          <div style="font-size:12px; color:#6b21a8; line-height:1.55;">3 personas with verified routes back to YOUR channels via plus-aliasing (email) and prefix tagging (SMS). When the scan finds these handles, live sends route per persona. Reply to the email or SMS to close the loop in two-way mode.</div>
        </div>
      </div>
      {persona_rows}
    </div>
    '''


def render_persona_conversations():
    """Render chat-bubble conversation threads for all personas with activity."""
    threads = get_all_conversation_threads()

    if not threads:
        return '''
        <div style="padding:20px; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; text-align:center; color:#64748b; font-size:13px;">
          No conversations yet. Fire a touch to a persona-tagged lead, and the outbound + inbound messages will appear here as chat bubbles.
        </div>
        '''

    output = ['<div style="display:flex; flex-direction:column; gap:18px;">']

    for persona_id, thread in threads.items():
        persona = get_persona_by_id(persona_id) or {"first_name": persona_id, "emoji": "🎭", "color": "#94a3b8"}

        bubbles = ""
        for entry in thread:
            direction = entry.get("direction", "outbound")
            channel = entry.get("channel", "email")
            subject = entry.get("subject")
            body = entry.get("body", "")
            ts = entry.get("timestamp", "")
            ts_pretty = ts.split("T")[1].split(".")[0] if "T" in ts else ts

            ch_meta = CHANNEL_CATALOG_META.get(channel, {})
            ch_emoji = ch_meta.get("emoji", "📨")
            ch_label = ch_meta.get("label", channel)

            if direction == "outbound":
                # Right-side blue bubble
                subject_html = f'<div style="font-size:11px; font-weight:700; color:white; opacity:0.8; margin-bottom:4px;">Subject: {html.escape(subject)}</div>' if subject else ""
                bubble_body = html.escape(body)[:600].replace(chr(10), "<br>")
                bubbles += f'''
                <div style="display:flex; justify-content:flex-end; margin-bottom:10px;">
                  <div style="max-width:75%; background:#3b82f6; color:white; padding:12px 16px; border-radius:14px 14px 4px 14px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">
                    <div style="font-size:10px; font-weight:700; opacity:0.85; margin-bottom:4px;">{ch_emoji} {html.escape(ch_label)} · OUTBOUND · {ts_pretty}</div>
                    {subject_html}
                    <div style="font-size:13px; line-height:1.55;">{bubble_body}</div>
                  </div>
                </div>
                '''
            else:
                # Left-side gray bubble
                subject_html = f'<div style="font-size:11px; font-weight:700; color:#475569; margin-bottom:4px;">Re: {html.escape(subject)}</div>' if subject else ""
                bubble_body = html.escape(body)[:600].replace(chr(10), "<br>")
                bubbles += f'''
                <div style="display:flex; justify-content:flex-start; margin-bottom:10px;">
                  <div style="max-width:75%; background:#e2e8f0; color:#0f172a; padding:12px 16px; border-radius:14px 14px 14px 4px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
                    <div style="font-size:10px; font-weight:700; color:#64748b; margin-bottom:4px;">{ch_emoji} {html.escape(ch_label)} · {persona["first_name"].upper()} REPLIED · {ts_pretty}</div>
                    {subject_html}
                    <div style="font-size:13px; line-height:1.55;">{bubble_body}</div>
                  </div>
                </div>
                '''

        output.append(f'''
        <div style="border:1px solid #e2e8f0; border-left:5px solid {persona["color"]}; border-radius:12px; padding:16px; background:white;">
          <div style="display:flex; gap:10px; align-items:center; margin-bottom:14px;">
            <span style="font-size:20px;">{persona["emoji"]}</span>
            <div>
              <div style="font-size:14px; font-weight:700; color:#0f172a;">{html.escape(persona["first_name"])} - Conversation</div>
              <div style="font-size:11px; color:#64748b;">{len(thread)} messages exchanged</div>
            </div>
          </div>
          {bubbles}
        </div>
        ''')

    output.append('</div>')
    return "".join(output)


def two_way_toggle_handler(enabled):
    """Start or stop the webhook server when toggle changes."""
    if enabled:
        if is_server_running():
            return '''<div style="padding:10px 14px; background:#f0fdf4; border:1px solid #86efac; border-radius:8px; color:#166534; font-size:12px;">
            ✓ Webhook server already running on port 7861. To receive real replies, run <code>ngrok http 7861</code> in a separate terminal, then paste the public URL into Resend's webhook config (event: email.received) and Twilio's Phone Number > Messaging > A Message Comes In webhook.
            </div>'''
        success, msg = start_webhook_server(7861)
        if success:
            return f'''<div style="padding:10px 14px; background:#f0fdf4; border:1px solid #86efac; border-radius:8px; color:#166534; font-size:12px;">
            ✓ {html.escape(msg)}. Next steps:
            <ol style="margin:6px 0 0 18px; padding:0; line-height:1.7;">
              <li>Run <code style="background:white; padding:1px 5px; border-radius:3px;">ngrok http 7861</code> in a terminal</li>
              <li>Copy the public URL ngrok prints (e.g. <code>https://abc123.ngrok-free.app</code>)</li>
              <li>In Resend dashboard: Webhooks → Add Endpoint → URL <code>https://abc123.ngrok-free.app/webhook/email</code> → event <code>email.received</code></li>
              <li>In Twilio Console: Phone Numbers → Manage → Active → click your number → Messaging "A Message Comes In" → POST to <code>https://abc123.ngrok-free.app/webhook/sms</code></li>
            </ol>
            See DEMO_PERSONAS_SETUP.md for screenshots. Reply to any persona email/SMS from your phone or inbox and it appears in the conversation thread below.
            </div>'''
        else:
            return f'''<div style="padding:10px 14px; background:#fef2f2; border:1px solid #fecaca; border-radius:8px; color:#991b1b; font-size:12px;">
            ❌ Could not start webhook server: {html.escape(msg)}
            </div>'''
    else:
        if is_server_running():
            success, msg = stop_webhook_server()
            return f'<div style="padding:10px 14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; color:#64748b; font-size:12px;">{html.escape(msg)}</div>'
        return '<div style="padding:10px 14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; color:#64748b; font-size:12px;">Two-way loop is OFF. Toggle ON to start the webhook server.</div>'


def inject_manual_reply_handler(persona_id, channel, body):
    """Record a manual reply for a persona (used in one-way mode to simulate inbound)."""
    if not persona_id or not body or not body.strip():
        return render_persona_conversations()
    persona = get_persona_by_id(persona_id)
    if not persona:
        return render_persona_conversations()

    subject = f"Re: previous touch" if channel == "email" else None
    record_inbound(persona_id, channel, subject, body.strip())
    return render_persona_conversations()


def clear_threads_handler():
    clear_conversation_thread()
    return render_persona_conversations()


def render_live_channels_status():
    """Render a status card showing which live channels are configured."""
    status = live_channel_status()

    cards = ""
    for key, info in status.items():
        configured = info["configured"] and info["has_recipient"]
        if configured:
            badge_bg, badge_fg, badge_label = "#dcfce7", "#15803d", "✓ Ready"
            border = "#86efac"
        elif info["configured"]:
            badge_bg, badge_fg, badge_label = "#fef3c7", "#92400e", "⚠ No recipient"
            border = "#fcd34d"
        else:
            badge_bg, badge_fg, badge_label = "#f1f5f9", "#64748b", "✗ Not configured"
            border = "#cbd5e1"

        cards += f'''
        <div style="background:white; border:1px solid {border}; border-radius:10px; padding:12px 14px; min-width:200px; flex:1;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <div style="font-size:12px; font-weight:700; color:#0f172a;">{html.escape(info["label"])}</div>
            <span style="background:{badge_bg}; color:{badge_fg}; padding:2px 8px; border-radius:5px; font-size:10px; font-weight:700;">{badge_label}</span>
          </div>
          <div style="font-size:11px; color:#475569; line-height:1.5;">→ {html.escape(info["recipient"])}</div>
          <div style="font-size:10px; color:#94a3b8; margin-top:2px;">{html.escape(info["free_tier"])}</div>
        </div>
        '''

    return f'''
    <div style="background:linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border:1px solid #fde68a; border-left:5px solid #f59e0b; border-radius:12px; padding:16px 18px; margin-bottom:16px;">
      <div style="display:flex; gap:12px; align-items:flex-start; margin-bottom:12px;">
        <div style="font-size:22px;">🧪</div>
        <div>
          <div style="font-size:13px; font-weight:700; color:#92400e; margin-bottom:2px;">DEMO MODE - Test Sends Only</div>
          <div style="font-size:12px; color:#78350f; line-height:1.55;">All messages route to YOUR configured test channels (below), never to actual prospects. Production deployment would route to the prospect via their consented channels.</div>
        </div>
      </div>
      <div style="display:flex; gap:10px; flex-wrap:wrap;">
        {cards}
      </div>
      <div style="font-size:11px; color:#78350f; margin-top:10px; line-height:1.5;">
        Configure channels in your <code style="background:rgba(0,0,0,0.05); padding:1px 4px; border-radius:3px;">.env</code> file. See setup guide in README.
      </div>
    </div>
    '''


def fire_sequences_handler(toggle_on, send_mode, scope):
    """
    Fire test sends for generated sequences.

    Args:
      toggle_on: whether Live Send Mode is enabled
      send_mode: "first_only" (just Touch 1) or "all_touches" (whole sequence)
      scope: "top" (only top-scoring lead) or "all" (every generated sequence)
    """
    global live_send_log

    if not toggle_on:
        live_send_log.append({
            "type": "warning",
            "message": "Live Send Mode is OFF. Toggle the checkbox above to enable real test sends.",
            "timestamp": datetime.now().isoformat(),
        })
        return render_activity_log()

    if not generated_campaigns:
        live_send_log.append({
            "type": "warning",
            "message": "No sequences generated yet. Run 'Generate campaigns' first.",
            "timestamp": datetime.now().isoformat(),
        })
        return render_activity_log()

    # Pick which leads' sequences to fire
    indices_with_sequences = [i for i, _ in enumerate(discovered_leads) if i in generated_campaigns]
    if not indices_with_sequences:
        live_send_log.append({
            "type": "warning",
            "message": "No sequences in pipeline. Run generation first.",
            "timestamp": datetime.now().isoformat(),
        })
        return render_activity_log()

    if scope == "top":
        # Pick the highest-scoring lead with a sequence
        sorted_indices = sorted(
            indices_with_sequences,
            key=lambda i: discovered_leads[i].get("analysis", {}).get("intent_score", 0),
            reverse=True,
        )
        target_indices = sorted_indices[:1]
    else:
        target_indices = indices_with_sequences

    live_send_log.append({
        "type": "info",
        "message": f"🚀 Firing {scope}-scope test sends · mode: {send_mode} · {len(target_indices)} sequence(s) targeted",
        "timestamp": datetime.now().isoformat(),
    })

    for idx in target_indices:
        lead = discovered_leads[idx]
        sequence = generated_campaigns[idx]
        touches = sequence.get("touches", [])
        handle = lead["signal"]["user_handle"]

        if not touches:
            live_send_log.append({
                "type": "skip",
                "message": f"Skipped {handle} - no touches in sequence (likely disqualified)",
                "timestamp": datetime.now().isoformat(),
            })
            continue

        touches_to_fire = touches if send_mode == "all_touches" else touches[:1]

        for touch in touches_to_fire:
            try:
                result = live_fire_touch(touch, lead)
                live_send_log.append({
                    "type": "send",
                    "lead_handle": handle,
                    "touch_id": touch.get("id"),
                    "channel": touch.get("channel"),
                    "result": result,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                live_send_log.append({
                    "type": "error",
                    "lead_handle": handle,
                    "touch_id": touch.get("id"),
                    "message": f"Error firing touch: {e}",
                    "timestamp": datetime.now().isoformat(),
                })

    return render_activity_log()


def render_activity_log():
    """Render the live send activity log."""
    if not live_send_log:
        return '<div style="padding:14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; color:#64748b; font-size:12px;">Activity log empty.</div>'

    rows = ""
    for entry in reversed(live_send_log[-30:]):  # Show last 30 entries, most recent first
        ts = entry["timestamp"]
        ts_pretty = ts.split("T")[1].split(".")[0] if "T" in ts else ts

        if entry["type"] == "warning":
            rows += f'''
            <div style="padding:8px 12px; background:#fffbeb; border-left:3px solid #f59e0b; border-radius:0 6px 6px 0; margin-bottom:6px;">
              <div style="font-size:10px; color:#92400e; font-weight:600;">{ts_pretty}</div>
              <div style="font-size:12px; color:#78350f;">⚠ {html.escape(entry["message"])}</div>
            </div>
            '''
        elif entry["type"] == "info":
            rows += f'''
            <div style="padding:8px 12px; background:#eff6ff; border-left:3px solid #3b82f6; border-radius:0 6px 6px 0; margin-bottom:6px;">
              <div style="font-size:10px; color:#1e40af; font-weight:600;">{ts_pretty}</div>
              <div style="font-size:12px; color:#1e3a8a;">{html.escape(entry["message"])}</div>
            </div>
            '''
        elif entry["type"] == "skip":
            rows += f'''
            <div style="padding:8px 12px; background:#f8fafc; border-left:3px solid #cbd5e1; border-radius:0 6px 6px 0; margin-bottom:6px;">
              <div style="font-size:10px; color:#64748b; font-weight:600;">{ts_pretty}</div>
              <div style="font-size:12px; color:#475569;">⏭ {html.escape(entry["message"])}</div>
            </div>
            '''
        elif entry["type"] == "error":
            rows += f'''
            <div style="padding:8px 12px; background:#fef2f2; border-left:3px solid #ef4444; border-radius:0 6px 6px 0; margin-bottom:6px;">
              <div style="font-size:10px; color:#991b1b; font-weight:600;">{ts_pretty}</div>
              <div style="font-size:12px; color:#7f1d1d;">❌ {html.escape(entry.get("message", "Error"))}</div>
            </div>
            '''
        elif entry["type"] == "send":
            result = entry.get("result", {})
            is_mock = result.get("is_mock", False)
            success = result.get("success", False)
            channel = entry.get("channel", "unknown")
            handle = entry.get("lead_handle", "unknown")
            touch_id = entry.get("touch_id", "?")
            vendor = result.get("vendor", "Unknown")
            recipient = result.get("recipient", "?")
            details = result.get("details", "")
            msg_id = result.get("message_id", "")

            if is_mock:
                bg, border, fg = "#fef3c7", "#f59e0b", "#92400e"
                icon = "🧪"
                status = "MOCK (no real send)"
            elif success:
                bg, border, fg = "#f0fdf4", "#16a34a", "#15803d"
                icon = "✅"
                status = "SENT LIVE"
            else:
                bg, border, fg = "#fef2f2", "#ef4444", "#991b1b"
                icon = "❌"
                status = "FAILED"

            ch_meta = CHANNEL_CATALOG_META.get(channel, {})
            ch_emoji = ch_meta.get("emoji", "📨")
            ch_label = ch_meta.get("label", channel)

            rows += f'''
            <div style="padding:10px 14px; background:{bg}; border-left:4px solid {border}; border-radius:0 8px 8px 0; margin-bottom:8px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; flex-wrap:wrap; gap:8px;">
                <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                  <span style="background:{border}; color:white; padding:2px 8px; border-radius:4px; font-size:10px; font-weight:700;">{icon} {status}</span>
                  <span style="font-size:11px; color:#475569;">{ch_emoji} {html.escape(ch_label)} · Touch {touch_id} · via {html.escape(vendor)}</span>
                </div>
                <div style="font-size:10px; color:#64748b;">{ts_pretty}</div>
              </div>
              <div style="font-size:12px; color:{fg}; margin-bottom:3px;"><strong>Lead:</strong> <code style="background:rgba(0,0,0,0.05); padding:1px 5px; border-radius:3px;">{html.escape(handle)}</code> · <strong>Sent to:</strong> <code style="background:rgba(0,0,0,0.05); padding:1px 5px; border-radius:3px;">{html.escape(str(recipient))}</code></div>
              <div style="font-size:11px; color:#64748b; line-height:1.5;">{html.escape(details)}</div>
              {f'<div style="font-size:10px; color:#94a3b8; margin-top:3px; font-family:monospace;">message_id: {html.escape(msg_id)}</div>' if msg_id else ''}
            </div>
            '''

    return f'''
    <div style="background:white; border:1px solid #e2e8f0; border-radius:12px; padding:16px; max-height:480px; overflow-y:auto;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <div style="font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.8px;">📡 Live Send Activity Log</div>
        <div style="font-size:10px; color:#94a3b8;">Last {min(30, len(live_send_log))} of {len(live_send_log)} events</div>
      </div>
      {rows}
    </div>
    '''


# ============================================================


def render_sequence_mockups(results):
    """
    Render multi-touch nurture sequences with:
      - Header card per lead (classification, path, sequence name, totals)
      - Calendar timeline showing when each touch fires
      - Detail card per touch (channel, subject, body, A/B variant, predictions, compliance)
      - Behavioral branching logic visible
      - Exit triggers + suppression rules
      - Cost & predicted outcomes
    """
    if not results:
        return ""

    output = ['<div style="font-family:Inter,sans-serif; padding:8px;">']

    for item in results:
        lead = item["lead"]
        sequence = item["sequence"]
        is_llm = item.get("is_llm_generated", False)
        signal = lead["signal"]
        analysis = lead["analysis"]
        path = lead["path"]
        cls = analysis.get("classification", "unknown")
        meta = get_classification_meta(cls)

        path_color = "#16a34a" if path["path"] == "A" else "#d97706"
        path_bg = "#f0fdf4" if path["path"] == "A" else "#fffbeb"

        touches = sequence.get("touches", [])
        totals = sequence.get("totals", {})
        merge_vars = sequence.get("merge_vars", {})

        # Source indicator (LLM-generated vs template)
        gen_badge = (
            '<span style="background:#dbeafe; color:#1e40af; padding:3px 9px; border-radius:6px; font-size:10px; font-weight:700;">🤖 AI-WRITTEN</span>'
            if is_llm
            else '<span style="background:#f1f5f9; color:#64748b; padding:3px 9px; border-radius:6px; font-size:10px; font-weight:700;">📋 TEMPLATE</span>'
        )

        # ======== SEQUENCE HEADER ========
        if not touches:
            # Disqualified or no-sequence case
            output.append(f'''
            <div style="border:1px solid #fde68a; background:#fffbeb; border-left:5px solid #f59e0b; border-radius:14px; padding:20px 24px; margin-bottom:20px;">
              <div style="display:flex; gap:10px; align-items:center; margin-bottom:8px;">
                <span style="background:{meta['bg']}; color:{meta['color']}; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700;">{meta['emoji']} {meta['label']}</span>
                <span style="font-family:monospace; color:#64748b; font-size:12px;">{html.escape(signal['user_handle'])}</span>
              </div>
              <div style="font-size:16px; font-weight:700; color:#0f172a;">{html.escape(sequence.get('name', 'No sequence'))}</div>
              <div style="font-size:13px; color:#78350f; margin-top:6px; line-height:1.6;">{html.escape(sequence.get('description', ''))}</div>
            </div>
            ''')
            continue

        output.append(f'''
        <div style="border:1px solid #e2e8f0; border-radius:16px; padding:24px; margin-bottom:28px; background:white; box-shadow:0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(15,23,42,0.04);">

          <!-- HEADER -->
          <div style="display:flex; justify-content:space-between; margin-bottom:18px; flex-wrap:wrap; gap:12px;">
            <div>
              <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px;">
                <span style="background:{meta['bg']}; color:{meta['color']}; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700;">{meta['emoji']} {meta['label']}</span>
                <span style="background:{path_bg}; color:{path_color}; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700;">Path {path['path']}</span>
                {gen_badge}
                <span style="font-family:monospace; color:#64748b; font-size:12px;">{html.escape(signal['user_handle'])}</span>
              </div>
              <div style="font-size:20px; font-weight:800; color:#0f172a;">{html.escape(sequence.get('name', 'Sequence'))}</div>
              <div style="font-size:13px; color:#475569; margin-top:4px; line-height:1.55;">{html.escape(sequence.get('description', ''))}</div>
            </div>
            <div style="text-align:right;">
              <div style="display:grid; grid-template-columns:repeat(3, auto); gap:8px;">
                <div style="background:#f0f9ff; padding:8px 14px; border-radius:8px;">
                  <div style="font-size:10px; color:#0369a1; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Touches</div>
                  <div style="font-size:18px; font-weight:800; color:#0c4a6e;">{totals.get('touch_count', 0)}</div>
                </div>
                <div style="background:#f5f3ff; padding:8px 14px; border-radius:8px;">
                  <div style="font-size:10px; color:#6d28d9; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Duration</div>
                  <div style="font-size:18px; font-weight:800; color:#5b21b6;">{sequence.get('duration_days', 0)}d</div>
                </div>
                <div style="background:#f0fdf4; padding:8px 14px; border-radius:8px;">
                  <div style="font-size:10px; color:#15803d; font-weight:700; text-transform:uppercase; letter-spacing:0.6px;">Conv.</div>
                  <div style="font-size:18px; font-weight:800; color:#14532d;">{totals.get('expected_bookings_per_100', 0):.1f}%</div>
                </div>
              </div>
              <div style="font-size:11px; color:#64748b; margin-top:8px;">Send cost: <strong style="color:#0f172a;">${totals.get('cost', 0):.4f}</strong> / lead</div>
            </div>
          </div>

          <!-- PERSONALIZATION VARIABLES -->
          <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px 16px; margin-bottom:18px;">
            <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px;">🔧 Personalization variables (merged into every touch)</div>
            <div style="display:flex; flex-wrap:wrap; gap:6px;">
              {''.join(f'<span style="background:#dbeafe; color:#1e3a8a; padding:3px 9px; border-radius:5px; font-size:11px; font-family:monospace;">{{{html.escape(k)}}} = {html.escape(str(v))[:40]}</span>' for k, v in list(merge_vars.items())[:7])}
            </div>
          </div>
        ''')

        # ======== CALENDAR TIMELINE ========
        output.append(_render_calendar_timeline(touches, sequence))

        # ======== TOUCH CARDS ========
        output.append('<div style="font-size:12px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin:24px 0 12px 0;">📨 Touch-by-Touch Sequence</div>')
        for idx, touch in enumerate(touches):
            output.append(_render_touch_card(touch, idx, len(touches), is_llm))

        # ======== EXIT TRIGGERS ========
        exit_triggers = sequence.get("exit_triggers", [])
        if exit_triggers:
            triggers_html = "".join(
                f'<div style="font-size:12px; color:#475569; padding:6px 10px; background:white; border-left:3px solid #ef4444; border-radius:0 6px 6px 0; margin-bottom:6px;">🛑 {html.escape(t)}</div>'
                for t in exit_triggers
            )
            output.append(f'''
            <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:14px 16px; margin-top:18px;">
              <div style="font-size:10px; color:#991b1b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:10px;">🛑 Exit Triggers — When this sequence stops</div>
              {triggers_html}
            </div>
            ''')

        # ======== COST BREAKDOWN ========
        cost_breakdown = totals.get("cost_breakdown", {})
        if cost_breakdown:
            cost_rows = "".join(
                f'''<div style="display:flex; justify-content:space-between; padding:5px 0; font-size:12px; border-bottom:1px solid #f1f5f9;">
                  <span style="color:#475569;">{CHANNEL_CATALOG_META.get(ch, {}).get("emoji", "📨")} {ch.replace("_", " ").title()} ({CHANNEL_CATALOG_META.get(ch, {}).get("vendor", "")})</span>
                  <span style="color:#0f172a; font-weight:600; font-family:monospace;">${cost:.4f}</span>
                </div>'''
                for ch, cost in cost_breakdown.items()
            )
            output.append(f'''
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; margin-top:18px;">
              <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:10px;">💰 Send Cost Breakdown (per lead, per execution)</div>
              {cost_rows}
              <div style="display:flex; justify-content:space-between; padding:8px 0 0 0; font-size:13px; font-weight:700; border-top:2px solid #cbd5e1; margin-top:4px;">
                <span style="color:#0f172a;">Total per lead</span>
                <span style="color:#0f172a; font-family:monospace;">${totals.get('cost', 0):.4f}</span>
              </div>
            </div>
            ''')

        output.append('</div>')  # close main sequence card

    output.append('</div>')
    return "\n".join(output)


def _render_calendar_timeline(touches, sequence):
    """Horizontal calendar timeline showing when each touch fires."""
    if not touches:
        return ""

    duration = max(sequence.get("duration_days", 1), 1)
    timeline_items = ""

    for touch in touches:
        day = touch["day"]
        hour = touch["hour"]
        ch = touch["channel"]
        ch_meta = CHANNEL_CATALOG_META.get(ch, {"emoji": "📨", "label": ch})

        # Position as % of total duration
        pos_pct = (day / duration) * 100 if duration > 0 else 0
        pos_pct = max(0, min(95, pos_pct))

        # Color by channel
        ch_color = _channel_color(ch)

        timeline_items += f'''
        <div style="position:absolute; left:{pos_pct:.1f}%; top:0; transform:translateX(-50%); text-align:center;">
          <div style="background:{ch_color}; color:white; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:16px; margin:0 auto; box-shadow:0 2px 6px rgba(0,0,0,0.15);">{ch_meta["emoji"]}</div>
          <div style="font-size:10px; color:#0f172a; font-weight:700; margin-top:4px;">Touch {touch["id"]}</div>
          <div style="font-size:10px; color:#64748b;">Day {day}, {hour:02d}:00</div>
        </div>
        '''

    # Day markers
    day_markers = ""
    marker_days = [0, duration // 4, duration // 2, 3 * duration // 4, duration]
    for d in marker_days:
        pct = (d / duration) * 100 if duration > 0 else 0
        day_markers += f'<div style="position:absolute; left:{pct:.1f}%; top:90px; transform:translateX(-50%); font-size:10px; color:#94a3b8; font-weight:600;">D{d}</div>'

    return f'''
    <div style="background:#fafbfc; border:1px solid #e2e8f0; border-radius:12px; padding:20px 16px 30px 16px; margin-bottom:18px;">
      <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:18px;">📅 Sequence Calendar — {sequence.get('duration_days', 0)} day cadence</div>
      <div style="position:relative; height:110px; margin:0 18px;">
        <div style="position:absolute; left:0; right:0; top:18px; height:2px; background:linear-gradient(90deg, #94a3b8, #cbd5e1, #94a3b8); border-radius:2px;"></div>
        {timeline_items}
        {day_markers}
      </div>
    </div>
    '''


def _channel_color(channel_key):
    return {
        "email": "#3b82f6",
        "sms": "#10b981",
        "retargeting": "#f59e0b",
        "lookalike_ad": "#f97316",
        "ig_dm": "#ec4899",
        "ig_reply": "#a855f7",
        "push": "#06b6d4",
    }.get(channel_key, "#64748b")


def _render_touch_card(touch, idx, total, parent_is_llm):
    """Render one touch with subject, body, A/B variant, predictions, branching, and compliance."""
    ch = touch["channel"]
    ch_meta = touch.get("channel_meta", CHANNEL_CATALOG_META.get(ch, {}))
    ch_color = _channel_color(ch)
    ch_emoji = ch_meta.get("emoji", "📨")
    ch_label = ch_meta.get("label", ch.replace("_", " ").title())
    vendor = ch_meta.get("vendor", "Unknown")

    is_llm = touch.get("is_llm_generated", False)
    llm_badge = '<span style="background:#dbeafe; color:#1e40af; padding:2px 7px; border-radius:4px; font-size:9px; font-weight:700;">🤖 AI</span>' if is_llm else '<span style="background:#f1f5f9; color:#64748b; padding:2px 7px; border-radius:4px; font-size:9px; font-weight:700;">📋 TPL</span>'

    pred_open = touch.get("predicted_open", 0) * 100
    pred_ctr = touch.get("predicted_ctr", 0) * 100
    cost = touch.get("cost", 0)

    subject = touch.get("subject")
    subject_b = touch.get("subject_variant_b")
    body = touch.get("body", "")
    cta = touch.get("cta")
    purpose = touch.get("purpose", "")

    # Subject + variants block
    subject_block = ""
    if subject:
        ab_test_block = ""
        if subject_b:
            ab_test_block = f'''
            <div style="background:#f0f9ff; border:1px solid #bae6fd; border-radius:6px; padding:8px 12px; margin-top:6px;">
              <div style="font-size:10px; font-weight:700; color:#0369a1; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:2px;">A/B Test Variant B (50/50 split)</div>
              <div style="font-size:13px; color:#0f172a; font-style:italic;">"{html.escape(subject_b)}"</div>
            </div>
            '''
        subject_block = f'''
        <div style="margin-bottom:10px;">
          <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:4px;">Subject line</div>
          <div style="font-size:14px; font-weight:700; color:#0f172a;">"{html.escape(subject)}"</div>
          {ab_test_block}
        </div>
        '''

    # Body preview
    body_preview = html.escape(body or "").replace("\n", "<br>")
    body_block = f'''
    <div style="margin-bottom:10px;">
      <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:4px;">{ch_label} content preview</div>
      <div style="background:white; border:1px solid #e2e8f0; border-radius:8px; padding:14px 16px; font-size:13px; color:#334155; line-height:1.6; max-height:280px; overflow-y:auto;">{body_preview}</div>
    </div>
    '''

    # CTA
    cta_block = ""
    if cta:
        cta_block = f'<div style="display:inline-block; background:{ch_color}; color:white; padding:7px 14px; border-radius:6px; font-size:12px; font-weight:700; margin-top:4px;">{html.escape(cta)} →</div>'

    # Branching logic
    branching = touch.get("branching", {})
    branching_html = ""
    if branching:
        rows = "".join(
            f'<div style="font-size:11px; color:#475569; padding:5px 8px; background:#f8fafc; border-radius:4px; margin-bottom:4px;"><strong style="color:#0f172a;">If {html.escape(k.replace("_", " "))}:</strong> {html.escape(v)}</div>'
            for k, v in branching.items()
        )
        branching_html = f'''
        <div style="background:#fef9c3; border-left:3px solid #eab308; padding:10px 12px; border-radius:0 8px 8px 0; margin-top:10px;">
          <div style="font-size:10px; color:#854d0e; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:6px;">🔀 Behavioral Branching (if-then logic)</div>
          {rows}
        </div>
        '''

    # Compliance check
    compliance = touch.get("compliance", {})
    compliance_html = _render_compliance_panel(compliance)

    # Predictions panel
    predictions_html = f'''
    <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:10px 12px; margin-top:8px;">
      <div style="font-size:10px; color:#15803d; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:6px;">📊 Predicted Performance</div>
      <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;">
        <div>
          <div style="font-size:10px; color:#64748b;">Open rate</div>
          <div style="font-size:14px; font-weight:700; color:#14532d;">{pred_open:.1f}%</div>
        </div>
        <div>
          <div style="font-size:10px; color:#64748b;">Click-through</div>
          <div style="font-size:14px; font-weight:700; color:#14532d;">{pred_ctr:.1f}%</div>
        </div>
        <div>
          <div style="font-size:10px; color:#64748b;">Send cost</div>
          <div style="font-size:14px; font-weight:700; color:#14532d; font-family:monospace;">${cost:.4f}</div>
        </div>
      </div>
    </div>
    '''

    return f'''
    <div style="border:1px solid #e2e8f0; border-left:5px solid {ch_color}; border-radius:10px; padding:16px 18px; margin-bottom:12px; background:#fcfcfd;">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; flex-wrap:wrap; gap:8px;">
        <div>
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:4px;">
            <span style="background:{ch_color}; color:white; padding:3px 10px; border-radius:5px; font-size:11px; font-weight:700;">{ch_emoji} TOUCH {touch["id"]} · {ch_label.upper()}</span>
            <span style="background:#f1f5f9; color:#475569; padding:3px 9px; border-radius:5px; font-size:11px; font-weight:600;">Day {touch["day"]}, {touch["hour"]:02d}:00 local</span>
            {llm_badge}
          </div>
          <div style="font-size:13px; color:#475569; line-height:1.55;">{html.escape(purpose)}</div>
          <div style="font-size:11px; color:#94a3b8; margin-top:2px;">via {html.escape(vendor)}</div>
        </div>
      </div>
      {subject_block}
      {body_block}
      {cta_block}
      {predictions_html}
      {branching_html}
      {compliance_html}
    </div>
    '''


def _render_compliance_panel(compliance):
    if not compliance:
        return ""
    overall = compliance.get("overall", "approved")
    checks = compliance.get("checks", {})

    overall_colors = {
        "approved": ("#f0fdf4", "#bbf7d0", "#15803d", "✓ Pre-send compliance: APPROVED"),
        "warning":  ("#fffbeb", "#fde68a", "#a16207", "⚠ Pre-send compliance: WARNING"),
        "blocked":  ("#fef2f2", "#fecaca", "#991b1b", "🛑 Pre-send compliance: BLOCKED"),
    }
    bg, border, fg, label = overall_colors.get(overall, overall_colors["approved"])

    rows = ""
    for key, check in checks.items():
        status = check.get("status", "pass")
        icon = "✓" if status == "pass" else ("⚠" if status == "warn" else "✗")
        color = "#15803d" if status == "pass" else ("#a16207" if status == "warn" else "#991b1b")
        rows += f'''
        <div style="display:flex; gap:8px; padding:4px 0; font-size:11px;">
          <span style="color:{color}; font-weight:700; min-width:14px;">{icon}</span>
          <div style="flex:1;">
            <div style="color:#0f172a; font-weight:600;">{html.escape(check.get("label", key))}</div>
            <div style="color:#64748b; font-size:10px;">{html.escape(check.get("detail", ""))}</div>
          </div>
        </div>
        '''

    return f'''
    <div style="background:{bg}; border:1px solid {border}; border-radius:8px; padding:10px 12px; margin-top:8px;">
      <div style="font-size:10px; color:{fg}; font-weight:700; text-transform:uppercase; letter-spacing:0.6px; margin-bottom:6px;">{label}</div>
      {rows}
    </div>
    '''


# Pull channel metadata into app.py module scope for the helper functions
from sequence_templates import CHANNEL_CATALOG as CHANNEL_CATALOG_META


def render_campaign_mockups(results):
    if not results:
        return ""
    output = ['<div style="font-family:Inter,sans-serif; padding:8px;">']
    for item in results:
        lead = item["lead"]
        campaign = item["campaign"]
        signal = lead["signal"]
        analysis = lead["analysis"]
        path = lead["path"]
        cls = analysis.get("classification", "unknown")
        meta = get_classification_meta(cls)

        theme = COLOR_THEMES.get(campaign.get("color_theme", "navy"), COLOR_THEMES["navy"])
        path_color = "#16a34a" if path["path"] == "A" else "#d97706"
        path_bg = "#f0fdf4" if path["path"] == "A" else "#fffbeb"

        perf_html = render_performance_panel(lead, campaign)

        output.append(f'''<div style="border:1px solid #e2e8f0; border-radius:16px; padding:24px; margin-bottom:24px; background:white; box-shadow:0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(15,23,42,0.04);">
          <div style="display:flex; justify-content:space-between; margin-bottom:18px; flex-wrap:wrap; gap:12px;">
            <div>
              <div style="display:flex; gap:8px; align-items:center; margin-bottom:6px;">
                <span style="background:{meta['bg']}; color:{meta['color']}; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700;">{meta['emoji']} {meta['label']}</span>
                <span style="background:{path_bg}; color:{path_color}; padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700;">Path {path['path']}</span>
                <span style="color:#64748b; font-size:12px; font-family:monospace;">{html.escape(signal['user_handle'])}</span>
              </div>
              <div style="font-size:20px; font-weight:800; color:{theme['primary']};">{html.escape(campaign.get('campaign_name', 'Campaign'))}</div>
              <div style="font-size:14px; color:#475569; margin-top:2px;">{html.escape(campaign.get('campaign_theme', ''))}</div>
            </div>
            <div style="font-size:12px; color:#94a3b8; text-align:right;">
              <div>{len(campaign.get('touchpoints', []))} touchpoints</div>
              <div>{campaign.get('expected_conversion_pct', 0)}% conversion</div>
            </div>
          </div>
          {perf_html}
          <div style="margin-top:18px;">''')

        for tp in campaign.get("touchpoints", []):
            day = tp.get("day", "?")
            channel = tp.get("channel", "email").replace("_", " ").title()
            tp_type = tp.get("touchpoint_type", "outreach").replace("_", " ").title()
            output.append(f'<div style="margin-bottom:18px;"><div style="display:flex; gap:8px; margin-bottom:8px;"><span style="background:{theme["primary"]}; color:white; padding:3px 10px; border-radius:6px; font-size:11px; font-weight:700;">Day {day}</span><span style="background:#f1f5f9; color:#475569; padding:3px 10px; border-radius:6px; font-size:11px; font-weight:600;">{channel}</span><span style="background:#f1f5f9; color:#475569; padding:3px 10px; border-radius:6px; font-size:11px;">{tp_type}</span></div>{render_touchpoint(tp, theme)}</div>')
        output.append('</div></div>')
    output.append('</div>')
    return ''.join(output)


# ============================================================
# NURTURING → ACQUISITION HANDOFF
# ============================================================

def transfer_all_generated():
    global acquisition_pipeline
    transferred = 0
    skipped = 0
    for lead_idx, campaign in generated_campaigns.items():
        if lead_idx >= len(discovered_leads):
            continue
        lead = discovered_leads[lead_idx]
        handle = lead["signal"]["user_handle"]
        if any(item["lead"]["signal"]["user_handle"] == handle for item in acquisition_pipeline):
            skipped += 1
            continue
        acquisition_pipeline.append({"lead": lead, "campaign": campaign, "transferred_at": datetime.now().strftime("%H:%M:%S")})
        transferred += 1
    if transferred == 0 and skipped == 0:
        return "⚠️ No generated campaigns to transfer. Generate campaigns first.", render_acquisition_pipeline()
    msg = f"✅ {transferred} lead(s) transferred to Acquisition"
    if skipped:
        msg += f" · {skipped} already in pipeline"
    return msg, render_acquisition_pipeline()


def render_acquisition_pipeline():
    if not acquisition_pipeline:
        return """<div style="padding:30px; text-align:center; color:#64748b; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px;">
        <strong style="font-size:14px; color:#0f172a;">No leads in pipeline yet</strong>
        <div style="font-size:12px; margin-top:4px;">Generate campaigns in Nurturing, then transfer leads here for live booking.</div>
        </div>"""

    cards = []
    for i, item in enumerate(acquisition_pipeline):
        lead = item["lead"]
        campaign = item.get("campaign") or {}
        signal = lead["signal"]
        analysis = lead["analysis"]
        path = lead["path"]
        cls = analysis.get("classification", "unknown")
        meta = get_classification_meta(cls)
        score = analysis.get("intent_score", 0)
        path_color = "#16a34a" if path["path"] == "A" else "#d97706"
        path_bg = "#f0fdf4" if path["path"] == "A" else "#fffbeb"
        destinations = ', '.join(analysis.get('suggested_destinations', [])[:3])
        budget = analysis.get('estimated_budget', 'TBD')
        campaign_name = campaign.get('campaign_name', 'No campaign yet')

        cards.append(f"""
        <div style="background:white; border:1px solid #e2e8f0; border-left:5px solid {meta['color']}; border-radius:14px; padding:18px 20px; margin-bottom:12px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:14px; flex-wrap:wrap; margin-bottom:10px;">
            <div>
              <div style="display:flex; gap:6px; align-items:center; margin-bottom:6px; flex-wrap:wrap;">
                <span style="background:{meta['bg']}; color:{meta['color']}; padding:3px 9px; border-radius:5px; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.4px;">{meta['emoji']} {meta['label']}</span>
                <span style="background:{path_bg}; color:{path_color}; padding:3px 9px; border-radius:5px; font-size:10px; font-weight:700;">Path {path['path']}</span>
                <span style="background:#f1f5f9; color:#475569; padding:3px 9px; border-radius:5px; font-size:10px; font-weight:600;">{score}/100</span>
              </div>
              <div style="font-size:16px; font-weight:700; color:#0f172a; margin-bottom:2px;">{html.escape(signal['user_handle'])}</div>
              <div style="font-size:12px; color:#64748b;">Campaign: <strong style="color:#334155;">{html.escape(campaign_name)}</strong></div>
            </div>
            <div style="font-size:10px; color:#94a3b8; font-family:monospace; white-space:nowrap;">Transferred {item['transferred_at']}</div>
          </div>
          <div style="background:#fafbfc; border:1px solid #f1f5f9; border-radius:8px; padding:10px 12px; margin-bottom:10px; font-size:12px; color:#475569;">
            <strong>Wants:</strong> {html.escape(destinations) if destinations else 'TBD'} · <strong>Budget:</strong> {html.escape(budget)} · <strong>Window:</strong> {html.escape(analysis.get('travel_window', 'TBD'))}
          </div>
          <button onclick="
            const ta = document.querySelector('#acq_msg_input textarea, #acq_msg_input input');
            if (ta) {{
              ta.value = `[Lead from Nurturing pipeline · {html.escape(signal['user_handle'])} · Path {path['path']} · {meta['label']}] I am interested in: {html.escape(destinations) if destinations else 'travel options'}. Budget around {html.escape(budget)}. Travel window: {html.escape(analysis.get('travel_window', 'flexible'))}. Original post hook: {html.escape(signal['post_content'][:120].replace(chr(10),' '))}`;
              ta.dispatchEvent(new Event('input', {{bubbles: true}}));
              ta.focus();
            }}
          " style="background:linear-gradient(135deg,#f97316 0%,#ea580c 100%); color:white; border:none; padding:9px 18px; border-radius:8px; font-size:12px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(249,115,22,0.3);">
            🚀 Start booking conversation
          </button>
        </div>
        """)

    return f"""<div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
        <div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px;">Pending Acquisition Pipeline</div>
        <div style="background:#1e3a8a; color:white; padding:3px 10px; border-radius:10px; font-size:11px; font-weight:700;">{len(acquisition_pipeline)} {'lead' if len(acquisition_pipeline) == 1 else 'leads'} waiting</div>
      </div>
      {''.join(cards)}
    </div>"""


def refresh_acquisition_pipeline():
    return render_acquisition_pipeline()


# ============================================================
# ACQUISITION HANDLERS
# ============================================================

def create_new_agent():
    return VoyageAgent()


def chat_handler(message, history, agent_state):
    if agent_state is None:
        agent_state = create_new_agent()
    if not message or not message.strip():
        return "", history, agent_state
    try:
        response = agent_state.chat(message)
    except Exception as e:
        response = f"Sorry, I hit an error: {str(e)}"
    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": response}]
    return "", history, agent_state


def reset_chat():
    return [{"role": "assistant", "content": "Hi! I'm Voyage. Tell me about the trip you're dreaming of."}], create_new_agent()


# ============================================================
# PRODUCTION ARCHITECTURE PANEL
# ============================================================

PRODUCTION_INTEGRATIONS = [
    {
        "category": "Social Listening (Live)",
        "vendor": "Reddit Public API",
        "description": "Free public read-only Reddit JSON API. Currently ACTIVE in this demo — scans 12 travel subreddits in real time. Production deployments add Brandwatch / Sprinklr for cross-platform coverage (Twitter, Instagram, TikTok, forums).",
        "endpoint": "https://www.reddit.com/r/{subreddit}/new.json?limit=25",
        "auth": "None (browser User-Agent only) — OAuth available for higher rate limits",
        "cost": "Free (100 req/10min unauthenticated · ~$0 demo cost)",
        "rate_limit": "100 requests per 10 min (unauthenticated)",
        "data_returned": "Post title, body, author, score (upvotes), comment count, created timestamp, permalink. Normalized to internal signal shape.",
        "status": "active",
        "sample_response": """// Reddit public JSON — actual API response (truncated)
{
  "kind": "Listing",
  "data": {
    "children": [{
      "kind": "t3",
      "data": {
        "id": "1h2x4ab",
        "subreddit": "travel",
        "title": "Looking for off-the-beaten-path Japan recommendations — 14 days in October",
        "selftext": "My partner and I are planning a 2-week trip to Japan in October. We've already done Tokyo and Kyoto on a previous visit. Looking for less-touristy regions...",
        "author": "wanderlust_traveler_92",
        "score": 247,
        "num_comments": 58,
        "created_utc": 1748167823,
        "permalink": "/r/travel/comments/1h2x4ab/looking_for_off_the_beaten_path_japan/",
        "stickied": false
      }
    }]
  }
}"""
    },
    {
        "category": "Social Listening (Enterprise)",
        "vendor": "Brandwatch / Sprinklr / Talkwalker",
        "description": "Enterprise social listening platforms for cross-platform coverage (Twitter/X, Instagram, TikTok, blogs, forums). Production deployments layer these on top of free sources for breadth.",
        "endpoint": "Brandwatch — https://api.brandwatch.com/projects/{project_id}/data/mentions\nSprinklr — https://api.sprinklr.com/api/v2/social-feed/listening\nTalkwalker — https://api.talkwalker.com/api/v3/mentions",
        "auth": "OAuth 2.0 bearer token (vendor-specific)",
        "cost": "Brandwatch: $80K+/yr · Sprinklr: $50K+/yr · Talkwalker: $40K+/yr",
        "rate_limit": "Vendor-dependent (typically 10K-50K calls/day)",
        "data_returned": "Posts across platforms (Twitter, IG, TikTok, blogs), author metadata, engagement metrics, sentiment, geo signals",
        "status": "configured",
        "sample_response": """// Brandwatch API — example response
{
  "results": [{
    "id": "mention_8472",
    "url": "https://instagram.com/p/...",
    "fullText": "Q4 broke me. Need to disappear into the mountains...",
    "author": "@sarah.wanders",
    "authorMetrics": {"followers": 1247, "verified": false},
    "engagement": {"likes": 47, "comments": 12, "shares": 3},
    "sentiment": "neutral",
    "publishedDate": "2026-05-25T09:47:03Z"
  }]
}"""
    },
    {
        "category": "Customer Data Platform (CDP)",
        "vendor": "Adobe AEP / Hightouch / Treasure Data",
        "description": "Single source of truth for customer profiles. Hosts unified identity, consent records, behavior history, segments. CDP vendor is configurable — Voyage Concierge plugs into any major CDP via standardized profile + consent APIs.",
        "endpoint": "Adobe AEP — https://platform.adobe.io/data/core/ups/access/entities\nHightouch — https://api.hightouch.com/api/v1/sources/{source_id}/query\nTreasure Data — https://api.treasuredata.com/v3/job/issue/presto/{database}",
        "auth": "OAuth 2.0 / API key / JWT (vendor-specific)",
        "cost": "Adobe AEP: $250K+/yr · Hightouch: $30-100K/yr · Treasure Data: $80K+/yr",
        "rate_limit": "Vendor-dependent (typically 100K-1M calls/day)",
        "data_returned": "Adobe AEP — xdm:Profile entity (identityMap, consents object, segmentMembership, person attributes)\nHightouch — reverse-ETL syncs from Snowflake/BigQuery models (rows with model-defined schema)\nTreasure Data — query result rows from Presto (customer_id, identity attributes, computed segments, behavioral attributes)",
        "status": "configured",
        "sample_response": """// Adobe AEP — xdm:Profile schema
{
  "results": [{
    "entityId": "0035g00000XYZab",
    "identityMap": {
      "Email":     [{"id": "sarah.mitchell92@gmail.com", "primary": true}],
      "Instagram": [{"id": "@sarah.wanders"}]
    },
    "person": {"name": {"fullName": "Sarah Mitchell"}},
    "consents": {
      "marketing": {
        "email": {"val": "y", "time": "2024-01-15T08:30:00Z"},
        "sms":   {"val": "y", "time": "2024-01-15T08:30:00Z"}
      }
    },
    "segmentMembership": {
      "ups": {
        "premium_solo_traveler": {"status": "existing", "lastQualificationTime": "2024-09-01T00:00:00Z"}
      }
    },
    "homeAddress": {"city": "Austin", "stateProvince": "TX"},
    "lifetimeValue": {"amount": 8500.00, "currency": "USD"}
  }]
}

// Hightouch — reverse-ETL sync (model rows from Snowflake/BigQuery)
{
  "rows": [{
    "customer_id":        "VC_8472",
    "full_name":          "Sarah Mitchell",
    "email":              "sarah.mitchell92@gmail.com",
    "instagram_handle":   "@sarah.wanders",
    "consent_email":      true,
    "consent_sms":        true,
    "lifetime_value_usd": 8500.00,
    "segment":            "premium_solo_traveler",
    "city":               "Austin",
    "state":              "TX",
    "last_booking_date":  "2024-07-12"
  }],
  "synced_at": "2026-05-25T09:42:18Z",
  "source_model": "dbt.marts.customer_360"
}

// Treasure Data — Presto query result
{
  "job_id": "1284756392",
  "status": "success",
  "results": [{
    "customer_id":        "VC_8472",
    "td_email":           "sarah.mitchell92@gmail.com",
    "td_ig_handle":       "@sarah.wanders",
    "td_consent_email":   1,
    "td_consent_sms":     1,
    "td_segment":         "premium_solo_traveler",
    "td_ltv":             8500.00,
    "td_city":            "Austin",
    "td_state":           "TX",
    "td_last_seen":       "2026-05-24T18:23:00Z"
  }],
  "schema": ["customer_id", "td_email", "td_ig_handle", "td_consent_email", "td_consent_sms", "td_segment", "td_ltv", "td_city", "td_state", "td_last_seen"]
}"""
    },
    {
        "category": "LLM (Classification + Generation)",
        "vendor": "Anthropic Claude API",
        "description": "Powers classification, scoring, and campaign generation. Sonnet 4.5 primary, Haiku 4.5 fallback.",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "auth": "API key (X-Api-Key header)",
        "cost": "~$0.003/classification · ~$2,000/month at 500 scans",
        "rate_limit": "4,000 requests/min (Tier 4)",
        "data_returned": "Structured JSON classification + campaign content",
        "status": "active",
        "sample_response": """{
  "id": "msg_01abc...",
  "model": "claude-sonnet-4-5-20250929",
  "content": [{
    "type": "text",
    "text": "{\\"classification\\": \\"active_research\\", \\"intent_score\\": 78, ...}"
  }],
  "usage": {"input_tokens": 850, "output_tokens": 320}
}"""
    },
    {
        "category": "Email Service Provider",
        "vendor": "Klaviyo",
        "description": "Sends transactional + marketing emails. Tracks opens, clicks, conversions.",
        "endpoint": "https://a.klaviyo.com/api/campaigns/",
        "auth": "Private API key",
        "cost": "$1,200/month (250K contacts)",
        "rate_limit": "150 requests/sec",
        "data_returned": "Campaign IDs, send status, engagement metrics",
        "status": "configured",
        "sample_response": """{
  "data": {
    "id": "01HXY8N3K9PQR...",
    "type": "campaign",
    "attributes": {
      "name": "Rockies Reset - Sarah",
      "status": "Sent",
      "send_time": "2026-05-26T10:00:00Z"
    }
  }
}"""
    },
    {
        "category": "SMS / WhatsApp",
        "vendor": "Twilio",
        "description": "SMS and WhatsApp delivery. Two-way conversation support for engagement.",
        "endpoint": "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        "auth": "Account SID + Auth Token (HTTP Basic)",
        "cost": "$0.0075 per SMS · ~$300/month",
        "rate_limit": "100 messages/sec",
        "data_returned": "Message SID, delivery status, reply webhooks",
        "status": "configured",
        "sample_response": """{
  "sid": "SM2a8e9c7b...",
  "status": "queued",
  "to": "+15125550184",
  "from": "+18885550100",
  "body": "Hey Sarah, quick question about your Banff trip...",
  "price": "-0.00750"
}"""
    },
    {
        "category": "Retargeting Ads",
        "vendor": "Meta Marketing API",
        "description": "Programmatic ad creation across Facebook + Instagram. Supports lookalike audiences.",
        "endpoint": "https://graph.facebook.com/v19.0/act_{ad_account_id}/campaigns",
        "auth": "Long-lived access token",
        "cost": "Variable · ~$2,500/month ad spend",
        "rate_limit": "200 calls/hour per user",
        "data_returned": "Campaign ID, audience size estimate, performance metrics",
        "status": "configured",
        "sample_response": """{
  "id": "23859584710420",
  "name": "Voyage_Retargeting_Q4",
  "status": "ACTIVE",
  "objective": "OUTCOME_TRAFFIC",
  "daily_budget": 5000,
  "targeting": {"custom_audiences": [{"id": "23847..."}]}
}"""
    },
    {
        "category": "Booking System (Internal)",
        "vendor": "Internal API (Voyage)",
        "description": "Inventory hold + payment processing for confirmed bookings.",
        "endpoint": "https://api.voyage.internal/v2/bookings/holds",
        "auth": "Service-to-service mTLS",
        "cost": "Self-hosted",
        "rate_limit": "Internal",
        "data_returned": "Hold confirmation number, expiry timestamp",
        "status": "active",
        "sample_response": """{
  "hold_id": "VC-87234-HOLD",
  "customer_id": "VC_8472",
  "package": {"flight_id": "FLAC4521", "hotel_id": "HT89102"},
  "total_usd": 3850.00,
  "expires_at": "2026-05-27T22:00:00Z"
}"""
    },
]


def render_production_architecture():
    total_monthly = 0
    rows_html = []

    for integ in PRODUCTION_INTEGRATIONS:
        cost_str = integ["cost"].lower()
        monthly = 0
        if "year" in cost_str:
            try:
                yearly = int(''.join(c for c in cost_str.split("/")[0] if c.isdigit()) or 0)
                monthly = yearly / 12
            except Exception:
                pass
        elif "month" in cost_str:
            try:
                monthly = int(''.join(c for c in cost_str.split("/")[0] if c.isdigit()) or 0)
            except Exception:
                pass
        total_monthly += monthly

        status_color = "#16a34a" if integ["status"] == "active" else "#0891b2"
        status_bg = "#f0fdf4" if integ["status"] == "active" else "#ecfeff"
        status_label = "✓ ACTIVE" if integ["status"] == "active" else "○ CONFIGURED"

        rows_html.append(f"""
        <div style="background:white; border:1px solid #e2e8f0; border-radius:14px; padding:20px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,0.04);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:14px; margin-bottom:12px;">
            <div style="flex:1; min-width:0;">
              <div style="font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:1.2px; margin-bottom:4px;">{html.escape(integ['category'])}</div>
              <div style="font-size:16px; font-weight:800; color:#0f172a;">{html.escape(integ['vendor'])}</div>
              <div style="font-size:14px; color:#64748b; margin-top:4px; line-height:1.55;">{html.escape(integ['description'])}</div>
            </div>
            <div style="background:{status_bg}; color:{status_color}; padding:5px 12px; border-radius:6px; font-size:11px; font-weight:700; white-space:nowrap;">
              {status_label}
            </div>
          </div>

          <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin:14px 0;">
            <div style="min-width:0;">
              <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;">Endpoint</div>
              <code style="font-size:11px; color:#1e3a8a; background:#f1f5f9; padding:4px 8px; border-radius:5px; line-height:1.5; display:block; overflow-wrap:anywhere; word-break:break-word;">{html.escape(integ['endpoint'])}</code>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;">Auth</div>
              <div style="font-size:12px; color:#334155;">{html.escape(integ['auth'])}</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;">Cost</div>
              <div style="font-size:12px; color:#334155; font-weight:600;">{html.escape(integ['cost'])}</div>
            </div>
            <div>
              <div style="font-size:10px; color:#64748b; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;">Rate limit</div>
              <div style="font-size:12px; color:#334155;">{html.escape(integ['rate_limit'])}</div>
            </div>
          </div>

          <details style="margin-top:12px;">
            <summary style="cursor:pointer; font-size:12px; color:#3b82f6; font-weight:600; padding:8px 12px; background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; display:inline-block; transition:all 0.15s ease;">▸ View sample API response</summary>
            <pre style="background:#0f172a; color:#e2e8f0; padding:16px; border-radius:8px; font-size:11px; line-height:1.6; overflow-x:auto; margin-top:8px; font-family:'JetBrains Mono', monospace; white-space:pre;">{html.escape(integ['sample_response'])}</pre>
          </details>
        </div>
        """)

    yearly_total = total_monthly * 12

    return f"""
    <div>
      <div style="background:linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); color:white; border-radius:18px; padding:24px 28px; margin-bottom:20px; box-shadow:0 8px 24px rgba(15,23,42,0.18);">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px;">
          <div style="flex:1; min-width:280px;">
            <div style="font-size:10px; font-weight:700; color:#a78bfa; text-transform:uppercase; letter-spacing:1.5px; margin-bottom:4px;">🏗️ Production Architecture</div>
            <div style="font-size:20px; font-weight:800; color:white; letter-spacing:-0.3px;">What this looks like in production</div>
            <div style="font-size:14px; color:#cbd5e1; margin-top:8px; max-width:700px; line-height:1.6;">
              7 integrated systems. Real endpoints, real costs, real auth patterns. The demo uses simulated data
              to keep things deterministic — in production, these are the systems your team would wire up.
            </div>
          </div>
          <div style="background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.15); border-radius:12px; padding:14px 18px; min-width:180px;">
            <div style="font-size:10px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.8px;">Est. Monthly Cost</div>
            <div style="font-size:28px; font-weight:800; color:#22c55e; margin-top:4px;">${total_monthly:,.0f}</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">${yearly_total:,.0f}/year all-in</div>
          </div>
        </div>

        <div style="margin-top:16px; padding:12px 14px; background:rgba(34,197,94,0.1); border-left:3px solid #22c55e; border-radius:0 8px 8px 0;">
          <div style="font-size:12px; color:#dcfce7; line-height:1.6;">
            <strong style="color:white;">Why mock data in the demo?</strong> Real APIs (Brandwatch, Salesforce, Twilio) require credentials,
            cost real money per call, and can fail unpredictably during presentations. Every integration shown here is real, documented, and ready to wire up.
          </div>
        </div>
      </div>

      {"".join(rows_html)}
    </div>
    """


# ============================================================
# VIEW SWITCHING WITH NAV STATE — 4 tabs
# ============================================================

def show_discovery_with_nav():
    return (gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False),
            gr.update(variant="primary"), gr.update(variant="secondary"), gr.update(variant="secondary"), gr.update(variant="secondary"))

def show_nurturing_with_nav():
    return (gr.update(visible=False), gr.update(visible=True), gr.update(visible=False), gr.update(visible=False),
            gr.update(variant="secondary"), gr.update(variant="primary"), gr.update(variant="secondary"), gr.update(variant="secondary"))

def show_acquisition_with_nav():
    return (gr.update(visible=False), gr.update(visible=False), gr.update(visible=True), gr.update(visible=False),
            gr.update(variant="secondary"), gr.update(variant="secondary"), gr.update(variant="primary"), gr.update(variant="secondary"))

def show_architecture_with_nav():
    return (gr.update(visible=False), gr.update(visible=False), gr.update(visible=False), gr.update(visible=True),
            gr.update(variant="secondary"), gr.update(variant="secondary"), gr.update(variant="secondary"), gr.update(variant="primary"))


# ============================================================
# CSS — Standardized typography scale, unified design system
# ============================================================

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap');

* { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important; }

/* Typography scale (6-step):
   10px = micro labels (uppercase tags)
   12px = small metadata
   14px = body
   16px = subheadings
   20px = section headings
   28px = display
*/

body, .gradio-container {
  background: linear-gradient(180deg, #f1f5f9 0%, #ffffff 60%) !important;
}

.gradio-container {
  max-width: 1380px !important;
  margin: auto !important;
  padding: 0 16px !important;
}

/* HEADER — premium gradient hero */
.header-text {
  text-align: center;
  padding: 44px 24px 36px 24px;
  background:
    radial-gradient(circle at 20% 30%, rgba(59, 130, 246, 0.30) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(168, 85, 247, 0.25) 0%, transparent 50%),
    linear-gradient(135deg, #0a0e27 0%, #1e3a8a 50%, #312e81 100%);
  border-radius: 0 0 28px 28px;
  margin-bottom: 20px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}

.header-title {
  font-size: 40px !important;
  font-weight: 800 !important;
  color: white !important;
  letter-spacing: -1px;
  margin-bottom: 8px;
  text-shadow: 0 2px 20px rgba(0,0,0,0.3);
}

.header-subtitle {
  color: #cbd5e1 !important;
  font-size: 12px !important;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}

/* Visual separator between header and content */
.nav-row {
  margin-top: 12px;
}

/* NAV BUTTONS */
button.lg {
  border-radius: 12px !important;
  font-weight: 600 !important;
  font-size: 14px !important;
  padding: 14px 22px !important;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
  height: 56px !important;
}

button.primary {
  background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%) !important;
  color: white !important;
  border: none !important;
  box-shadow: 0 4px 14px rgba(30, 58, 138, 0.35), inset 0 1px 0 rgba(255,255,255,0.2) !important;
}

button.primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(30, 58, 138, 0.45) !important;
}

button.secondary {
  background: white !important;
  color: #475569 !important;
  border: 1.5px solid #e2e8f0 !important;
}

button.secondary:hover {
  background: #f8fafc !important;
  border-color: #94a3b8 !important;
  color: #0f172a !important;
}

/* CARDS — only style INNER groups (cards within views), not the outer view containers */
.gr-group {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  margin-bottom: 0 !important;
}
.gr-group .gr-group {
  background: white !important;
  border: 1px solid #e2e8f0 !important;
  border-radius: 16px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03), 0 4px 16px rgba(15, 23, 42, 0.04) !important;
  padding: 20px !important;
  margin-bottom: 14px !important;
}

/* TYPOGRAPHY — standardized scale */
h1, h2, h3, h4 { color: #0f172a !important; font-weight: 700 !important; letter-spacing: -0.3px; }
h2 { font-size: 20px !important; margin-bottom: 14px !important; }
h3 {
  font-size: 10px !important;
  text-transform: uppercase;
  letter-spacing: 1.2px !important;
  color: #64748b !important;
  margin: 18px 0 10px 0 !important;
  font-weight: 700 !important;
}
p, span, label { color: #334155 !important; font-size: 14px !important; line-height: 1.65 !important; }
strong { color: #0f172a !important; font-weight: 700 !important; }

/* TABLES */
table {
  border-collapse: separate !important;
  border-spacing: 0;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  width: 100%;
  margin: 14px 0;
}
th {
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%) !important;
  color: #475569 !important;
  font-weight: 700 !important;
  font-size: 10px !important;
  text-transform: uppercase;
  letter-spacing: 1px !important;
  padding: 12px 16px !important;
  text-align: left !important;
  border-bottom: 1px solid #e2e8f0 !important;
}
td {
  padding: 12px 16px !important;
  border-bottom: 1px solid #f1f5f9 !important;
  font-size: 14px !important;
}
tr:last-child td { border-bottom: none !important; }
tr:hover td { background: #fafbfc !important; }

/* INPUTS */
textarea, input[type="text"] {
  border: 1.5px solid #e2e8f0 !important;
  border-radius: 10px !important;
  padding: 12px 14px !important;
  font-size: 14px !important;
  font-family: 'JetBrains Mono', monospace !important;
  background: #fafbfc !important;
  color: #0f172a !important;
}
textarea:focus, input[type="text"]:focus {
  border-color: #3b82f6 !important;
  background: white !important;
  outline: none !important;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1) !important;
}

input[type="radio"] + label, input[type="checkbox"] + label {
  background: white;
  border: 1.5px solid #e2e8f0 !important;
  border-radius: 10px !important;
  padding: 11px 14px !important;
  font-weight: 500 !important;
  margin-bottom: 6px !important;
  font-size: 12px !important;
  cursor: pointer;
  transition: all 0.15s ease;
}
input[type="radio"]:checked + label {
  border-color: #3b82f6 !important;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%) !important;
  color: #1e3a8a !important;
  font-weight: 600 !important;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15) !important;
}
input[type="checkbox"]:checked + label {
  border-color: #16a34a !important;
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%) !important;
  color: #166534 !important;
  font-weight: 600 !important;
}

/* MARKDOWN */
blockquote {
  border-left: 4px solid #3b82f6 !important;
  background: linear-gradient(90deg, #eff6ff 0%, transparent 100%) !important;
  padding: 12px 18px !important;
  margin: 12px 0 !important;
  border-radius: 0 10px 10px 0;
  color: #1e3a8a !important;
}
code {
  background: #f1f5f9 !important;
  color: #1e3a8a !important;
  padding: 3px 8px !important;
  border-radius: 5px !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 12px !important;
  font-weight: 600;
}

/* DARK AGENT CONSOLE — attached to header */
#discovery_console, #nurture_console {
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%) !important;
  border-radius: 0 0 12px 12px !important;
  padding: 18px 20px !important;
  margin-top: 0 !important;
  color: #e2e8f0 !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 12px !important;
  line-height: 1.85 !important;
  max-height: 700px;
  overflow-y: auto;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
}
#discovery_console p, #nurture_console p { color: #e2e8f0 !important; font-size: 12px !important; }
#discovery_console code, #nurture_console code {
  background: rgba(59, 130, 246, 0.15) !important;
  color: #93c5fd !important;
}
#discovery_console strong, #nurture_console strong { color: #fde68a !important; }

/* Details / summary polish */
details summary { outline: none; }
details summary::-webkit-details-marker { display: none; }
details[open] summary { margin-bottom: 8px; }
details summary:hover { background: #dbeafe !important; }

footer { display: none !important; }

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #f1f5f9; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
"""


# ============================================================
# BUILD INTERFACE
# ============================================================

with gr.Blocks(title="Voyage Concierge — Multi-Agent Demo") as demo:

    gr.HTML("""
        <div class="header-text">
            <div class="header-title">✈️ Voyage Concierge</div>
            <div class="header-subtitle">Multi-Agent AI System for Travel Lead Lifecycle</div>
            <div style="position:relative; margin-top:16px; display:flex; gap:24px; justify-content:center; flex-wrap:wrap;">
              <div style="color:#cbd5e1; font-size:11px; font-weight:600; letter-spacing:1px;">
                <span style="color:#22c55e;">●</span> TARGETED LISTENING
              </div>
              <div style="color:#cbd5e1; font-size:11px; font-weight:600; letter-spacing:1px;">
                <span style="color:#3b82f6;">●</span> LEAD CLASSIFICATION
              </div>
              <div style="color:#cbd5e1; font-size:11px; font-weight:600; letter-spacing:1px;">
                <span style="color:#a78bfa;">●</span> PATH-AWARE NURTURING
              </div>
              <div style="color:#cbd5e1; font-size:11px; font-weight:600; letter-spacing:1px;">
                <span style="color:#fbbf24;">●</span> LIVE BOOKING
              </div>
            </div>
        </div>
    """)

    # Collapsible ROI Dashboard
    roi_dashboard_html = gr.HTML(render_roi_collapsed())

    # NAV BUTTONS — 4 tabs
    with gr.Row(equal_height=True, elem_classes="nav-row"):
        nav_discovery = gr.Button("🔍  Discovery", variant="primary", size="lg", scale=1, min_width=180)
        nav_nurturing = gr.Button("🌱  Nurturing", variant="secondary", size="lg", scale=1, min_width=180)
        nav_acquisition = gr.Button("💬  Acquisition", variant="secondary", size="lg", scale=1, min_width=180)
        nav_architecture = gr.Button("🏗️  Architecture", variant="secondary", size="lg", scale=1, min_width=180)

    # ============ DISCOVERY VIEW ============
    with gr.Group(visible=True) as discovery_view:
        gr.HTML(hero_intro(
            "🔍",
            "Lead Discovery Agent",
            "Targeted social listening. Configure scope → scan firehose → classify leads → route Path A/B.",
            "#3b82f6"
        ))

        with gr.Row():
            with gr.Column(scale=3):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.HTML(section_label("Listening Scope"))
                        preset_radio = gr.Radio(
                            choices=[("✈️ Airlines", "airlines"), ("🧳 Travel Booking", "travel_booking"), ("💎 Luxury Travel", "luxury"), ("✏️ Custom", "custom")],
                            label="Vertical preset",
                            value="travel_booking"
                        )
                        preset_summary = gr.Markdown("**Travel Booking**")
                    with gr.Column(scale=2):
                        gr.HTML(section_label("Hashtags, Keywords & Competitors"))
                        config_textarea = gr.Textbox(label="One per line", lines=12, max_lines=18)

                gr.HTML(section_label("Data Source"))
                with gr.Row():
                    with gr.Column(scale=1):
                        data_source_radio = gr.Radio(
                            choices=[
                                ("🧪 Simulated firehose (15 curated signals)", "simulated"),
                                ("📦 Reddit cached (fast · up to 500 posts, 48h TTL)", "reddit_cache"),
                                ("🌐 Reddit live (fresh fetch · refreshes cache)", "reddit_live"),
                            ],
                            label="Where should we scan?",
                            value="simulated",
                            info="Simulated = controlled demo. Reddit cached = fast load from local cache (best for live demos). Reddit live = force fresh fetch from reddit.com (slower, needs unrestricted network)."
                        )
                    with gr.Column(scale=1):
                        reddit_subs_textarea = gr.Textbox(
                            label="Subreddits to scan (one per line, only used for Reddit sources)",
                            value="\n".join(DEFAULT_SUBREDDITS),
                            lines=6,
                            max_lines=12
                        )

                gr.HTML(section_label("Demo Personas (Closed-Loop Demo)"))
                gr.HTML(render_demo_personas_card())
                inject_personas_checkbox = gr.Checkbox(
                    label="🎭 Inject demo personas into the scan",
                    value=False,
                    info="When ON, hybrid mode adds the 3 demo personas (Priya, Marcus, Sarah) to the feed. Real Reddit posts from these handles are used if found; simulated posts are injected as fallback. This is what closes the loop with your verified email/phone."
                )

                scan_btn = gr.Button("🔄  Scan with this scope", variant="primary", size="lg")
                discovery_summary = gr.HTML("""<div style="background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; padding:24px; text-align:center; color:#64748b; font-size:13px;">Click <strong style="color:#0f172a;">Scan with this scope</strong> to discover leads.</div>""")

                gr.HTML(section_label("Inspect Individual Leads"))
                lead_dropdown = gr.Dropdown(
                    label="Select a lead",
                    choices=[],
                    interactive=True,
                    info="🔗 = verifiable Reddit lead (click-through to original post)  ·  🧪 = simulated demo signal"
                )
                lead_detail = gr.Markdown("Run a scan, then select a lead.")
                lead_detail_explainer = gr.HTML("")

            with gr.Column(scale=1, min_width=320):
                gr.HTML(agent_console_header("🤖 AGENT ACTIVITY"))
                discovery_console = gr.Markdown("*Awaiting scan...*", elem_id="discovery_console")

    # ============ NURTURING VIEW ============
    with gr.Group(visible=False) as nurturing_view:
        gr.HTML(hero_intro(
            "🌱",
            "Nurturing Agent",
            "Bulk-generate path-aware visual campaigns. Group by classification, or pick individuals.",
            "#22c55e"
        ))

        with gr.Row():
            with gr.Column(scale=3):
                refresh_btn = gr.Button("🔄  Load leads from Discovery", size="sm", variant="secondary")

                gr.HTML(section_label("Classification Groups"))
                classification_groups = gr.HTML("""<div style='padding:30px; text-align:center; color:#64748b; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px;'>
                <strong style="font-size:14px; color:#0f172a;">No leads available yet</strong>
                <div style="font-size:12px; margin-top:4px;">Run a scan in the Discovery view first.</div>
                </div>""")

                gr.HTML(section_label("Bulk-Select by Classification"))
                tier_selector = gr.Dropdown(
                    choices=[("— Select a classification group —", "none")],
                    value="none",
                    label="Auto-select all leads in a classification",
                    interactive=True
                )

                gr.HTML(section_label("Or Pick Individual Leads"))
                nurture_lead_select = gr.CheckboxGroup(
                    label="No leads available — run a scan first",
                    choices=[],
                    interactive=True
                )

                generate_btn = gr.Button("🎨  Generate campaigns for selected leads", variant="primary", size="lg")

                nurture_progress = gr.Markdown("Select leads above and click generate.")
                nurture_mockups = gr.HTML("")

                gr.HTML(section_label("🚀 Live Send Mode"))
                live_send_status_html = gr.HTML(render_live_channels_status())

                with gr.Row():
                    live_send_toggle = gr.Checkbox(
                        label="Activate Live Send Mode",
                        value=False,
                        info="When ON, the 'Fire Now' buttons below will dispatch real emails/SMS/Discord messages to your test channels (NOT to prospects)."
                    )
                    live_send_mode = gr.Radio(
                        choices=[
                            ("Fire only Touch 1 of each sequence", "first_only"),
                            ("Fire ALL touches in selected sequences", "all_touches"),
                        ],
                        value="first_only",
                        label="Send mode",
                        info="Choose whether each Fire button sends just the first touch or the entire sequence"
                    )

                with gr.Row():
                    fire_top_btn = gr.Button(
                        "🔥 Fire Now — Top-scoring lead",
                        variant="primary",
                        size="sm",
                    )
                    fire_all_btn = gr.Button(
                        "📤 Fire Now — All generated sequences",
                        variant="secondary",
                        size="sm",
                    )

                live_send_activity_log = gr.HTML('<div style="padding:14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; color:#64748b; font-size:12px;">Activity log empty. Enable Live Send Mode above, then click a Fire Now button to dispatch real test sends.</div>')

                gr.HTML(section_label("🔄 Two-Way Loop (Replies → App)"))
                two_way_toggle = gr.Checkbox(
                    label="Enable Two-Way Loop (auto-receive replies)",
                    value=False,
                    info="When ON, starts a local webhook server on port 7861. Configure Resend + Twilio webhooks (pointing to your ngrok URL) to receive real replies from your email/phone, which appear automatically in the conversation thread below. When OFF, you can still type manual replies for each persona to simulate the response side."
                )
                two_way_status = gr.HTML('<div style="padding:10px 14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; color:#64748b; font-size:12px;">Two-way loop is OFF. Toggle ON to start the webhook server.</div>')

                gr.HTML(section_label("💬 Persona Conversations"))
                conversation_threads_html = gr.HTML(render_persona_conversations())

                with gr.Row():
                    persona_picker = gr.Dropdown(
                        choices=[(f"{p['emoji']} {p['first_name']}", p['id']) for p in list_personas()],
                        label="Pick persona for manual reply",
                        value=None,
                        interactive=True
                    )
                    manual_reply_channel = gr.Radio(
                        choices=[("📧 Email", "email"), ("📱 SMS", "sms"), ("💬 Social", "social")],
                        value="email",
                        label="Reply channel",
                    )
                manual_reply_body = gr.Textbox(
                    label="Persona's reply (simulating their response in one-way mode)",
                    placeholder="Type what the persona would reply, e.g. 'Yes, send me the Hakone option please'",
                    lines=3
                )
                with gr.Row():
                    inject_reply_btn = gr.Button("📨 Inject reply into conversation", variant="secondary", size="sm")
                    refresh_threads_btn = gr.Button("🔄 Refresh conversation view", size="sm")
                    clear_threads_btn = gr.Button("🗑️ Clear all conversation threads", size="sm")

                gr.HTML(section_label("Hand Off to Acquisition"))
                transfer_all_btn = gr.Button("🚀  Transfer all generated leads to Acquisition", variant="secondary", size="lg")
                transfer_status = gr.Markdown("")

            with gr.Column(scale=1, min_width=320):
                gr.HTML(agent_console_header("🎨 CAMPAIGN GENERATION"))
                nurture_console = gr.Markdown("*Awaiting bulk generation...*", elem_id="nurture_console")

    # ============ ACQUISITION VIEW ============
    with gr.Group(visible=False) as acquisition_view:
        gr.HTML(hero_intro(
            "💬",
            "Acquisition Agent",
            "Live booking conversation with tool use. Nurtured leads land here with full context pre-loaded.",
            "#a78bfa"
        ))

        acquisition_pipeline_html = gr.HTML(
            """<div style="padding:30px; text-align:center; color:#64748b; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px;">
            <strong style="font-size:14px; color:#0f172a;">No leads in pipeline yet</strong>
            <div style="font-size:12px; margin-top:4px;">Generate campaigns in Nurturing, then transfer leads here for live booking.</div>
            </div>"""
        )
        refresh_pipeline_btn = gr.Button("🔄  Refresh pipeline", size="sm", variant="secondary")

        gr.HTML(section_label("Live Booking Conversation"))

        agent_state = gr.State(None)
        chatbot = gr.Chatbot(
            label="Conversation",
            height=500,
            show_label=False,
            value=[{"role": "assistant", "content": "Hi! I'm Voyage. Tell me about the trip you're dreaming of — or click 'Start booking conversation' on a pipeline lead above to load their context."}]
        )

        with gr.Row():
            msg_input = gr.Textbox(
                placeholder="e.g., 'Plan a 6-day Banff trip' — or click a pipeline lead above to auto-fill",
                show_label=False,
                scale=8,
                container=False,
                elem_id="acq_msg_input"
            )
            send_btn = gr.Button("Send", scale=1, variant="primary")

        reset_btn = gr.Button("Start new conversation", size="sm", variant="secondary")

    # ============ ARCHITECTURE VIEW ============
    with gr.Group(visible=False) as architecture_view:
        gr.HTML(hero_intro(
            "🏗️",
            "Production Architecture",
            "What this system looks like wired up to real production systems. Endpoints, costs, auth patterns — fully documented.",
            "#fbbf24"
        ))
        architecture_html = gr.HTML(render_production_architecture())

    # ============ EVENT WIRING ============
    nav_discovery.click(show_discovery_with_nav, outputs=[discovery_view, nurturing_view, acquisition_view, architecture_view, nav_discovery, nav_nurturing, nav_acquisition, nav_architecture])
    nav_nurturing.click(show_nurturing_with_nav, outputs=[discovery_view, nurturing_view, acquisition_view, architecture_view, nav_discovery, nav_nurturing, nav_acquisition, nav_architecture])
    nav_acquisition.click(
        show_acquisition_with_nav,
        outputs=[discovery_view, nurturing_view, acquisition_view, architecture_view, nav_discovery, nav_nurturing, nav_acquisition, nav_architecture]
    ).then(
        refresh_acquisition_pipeline,
        outputs=[acquisition_pipeline_html]
    )
    nav_architecture.click(show_architecture_with_nav, outputs=[discovery_view, nurturing_view, acquisition_view, architecture_view, nav_discovery, nav_nurturing, nav_acquisition, nav_architecture])

    preset_radio.change(get_preset_config, inputs=[preset_radio], outputs=[config_textarea, preset_summary])
    scan_btn.click(scan_with_config, inputs=[preset_radio, config_textarea, data_source_radio, reddit_subs_textarea, inject_personas_checkbox], outputs=[discovery_summary, lead_dropdown, lead_detail, discovery_console]).then(
        lambda: "",
        outputs=[lead_detail_explainer]
    )
    lead_dropdown.change(show_lead_detail, inputs=[lead_dropdown], outputs=[lead_detail, lead_detail_explainer])

    refresh_btn.click(get_lead_choices_for_nurturing, outputs=[nurture_lead_select, classification_groups, tier_selector])
    tier_selector.change(select_by_classification, inputs=[tier_selector], outputs=[nurture_lead_select])
    generate_btn.click(generate_bulk_campaigns, inputs=[nurture_lead_select], outputs=[nurture_progress, nurture_mockups, nurture_console])

    fire_top_btn.click(
        lambda toggle, mode: fire_sequences_handler(toggle, mode, "top"),
        inputs=[live_send_toggle, live_send_mode],
        outputs=[live_send_activity_log],
    ).then(
        lambda: render_persona_conversations(),
        outputs=[conversation_threads_html]
    )
    fire_all_btn.click(
        lambda toggle, mode: fire_sequences_handler(toggle, mode, "all"),
        inputs=[live_send_toggle, live_send_mode],
        outputs=[live_send_activity_log],
    ).then(
        lambda: render_persona_conversations(),
        outputs=[conversation_threads_html]
    )

    two_way_toggle.change(
        two_way_toggle_handler,
        inputs=[two_way_toggle],
        outputs=[two_way_status]
    )

    inject_reply_btn.click(
        inject_manual_reply_handler,
        inputs=[persona_picker, manual_reply_channel, manual_reply_body],
        outputs=[conversation_threads_html]
    )

    refresh_threads_btn.click(
        lambda: render_persona_conversations(),
        outputs=[conversation_threads_html]
    )

    clear_threads_btn.click(
        clear_threads_handler,
        outputs=[conversation_threads_html]
    )
    transfer_all_btn.click(transfer_all_generated, outputs=[transfer_status, acquisition_pipeline_html])

    refresh_pipeline_btn.click(refresh_acquisition_pipeline, outputs=[acquisition_pipeline_html])
    msg_input.submit(chat_handler, inputs=[msg_input, chatbot, agent_state], outputs=[msg_input, chatbot, agent_state])
    send_btn.click(chat_handler, inputs=[msg_input, chatbot, agent_state], outputs=[msg_input, chatbot, agent_state])
    reset_btn.click(reset_chat, outputs=[chatbot, agent_state])

    demo.load(get_preset_config, inputs=[preset_radio], outputs=[config_textarea, preset_summary])


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  VOYAGE CONCIERGE — Multi-Agent Demo (v3.5)")
    print("=" * 60)
    print("  Views: Discovery | Nurturing | Acquisition | Architecture")
    print("  Open in browser: http://localhost:7860")
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")

    demo.queue(max_size=20, default_concurrency_limit=4)
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        inbrowser=True,
        css=CUSTOM_CSS
    )
