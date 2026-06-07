"""
Demo Personas - Voyage Concierge

Pre-defined personas for closing the loop in live demos.

CRITICAL DESIGN PRINCIPLE:
The demo simulates "real prospects" by having you (the demo operator)
play multiple roles via verified Reddit accounts you control. All
messages route to YOUR test channels, never to actual third parties.

Persona structure:
  - reddit_handle: Reddit username that will appear in posts
  - first_name: used in personalization variables
  - last_name: used in personalization variables
  - email_tag: plus-alias suffix ([email protected])
  - sms_prefix: text prepended to SMS body ([PRIYA] ...)
  - tier_intent: which classification this persona is designed to land in
  - simulated_posts: fallback Reddit-style posts if real posts not found

Recipient routing:
  - email: uses Gmail/Outlook plus-aliasing - YOUR base email + +persona_tag
  - sms: ONE phone number for all personas, persona name prepended to body
  - discord/slack: same webhook, persona name tagged in title
"""

import os
import re
from datetime import datetime, timezone


# ============================================================
# THE 3 PRE-BUILT DEMO PERSONAS
# ============================================================

DEMO_PERSONAS = {
    "priya": {
        "id": "priya",
        "reddit_handle": "u/priya_wanderlust",  # Will be matched case-insensitively
        "first_name": "Priya",
        "last_name": "Sharma",
        "email_tag": "priya",
        "sms_prefix": "[PRIYA]",
        "tier_intent": "ready_to_book",
        "designed_classification": "Hot · Ready to Book",
        "emoji": "🔥",
        "color": "#dc2626",
        "description": "Decisive solo traveler with concrete dates and budget. Designed to land as Hot · Ready to Book.",
        "simulated_posts": [
            {
                "title": "Japan trip in 3 weeks - need help finalizing the last 2 nights",
                "body": "I'm flying into Tokyo on October 24 and have most of the trip planned (Tokyo Oct 24-27, Kyoto Oct 28-30, Osaka Oct 31). Budget is $5,500 for the remaining 2 nights (Nov 1-2) plus return flight. Should I do Hakone for onsen or Nara for the deer park temples? Need to book this week.",
                "subreddit": "JapanTravel",
            },
        ],
    },

    "marcus": {
        "id": "marcus",
        "reddit_handle": "u/marcus_travelplanner",
        "first_name": "Marcus",
        "last_name": "Chen",
        "email_tag": "marcus",
        "sms_prefix": "[MARCUS]",
        "tier_intent": "active_research",
        "designed_classification": "Warm · Active Research",
        "emoji": "🌟",
        "color": "#ca8a04",
        "description": "Methodical researcher narrowing options. Has destination + window, exploring itinerary depth. Designed to land as Warm · Active Research.",
        "simulated_posts": [
            {
                "title": "Iceland in summer 2026 - 10 days, mix of nature and Reykjavik?",
                "body": "Planning a 10-day Iceland trip for July or August 2026. First-time visitor, mid-range budget (~$4K solo). Want to do the Ring Road but worried about driving 10 hours/day. Should I base in Reykjavik and do day trips, or do a full circle with multiple stops? Also wondering about midnight sun impact on sleep.",
                "subreddit": "IcelandTravel",
            },
        ],
    },

    "sarah": {
        "id": "sarah",
        "reddit_handle": "u/sarah_switchedairlines",
        "first_name": "Sarah",
        "last_name": "Mitchell",
        "email_tag": "sarah",
        "sms_prefix": "[SARAH]",
        "tier_intent": "switching_intent",
        "designed_classification": "Hot · Switching Intent",
        "emoji": "⭐",
        "color": "#ea580c",
        "description": "Frustrated with current provider AND explicitly considering alternatives. Has named the competitor. Designed to land as Hot · Switching Intent.",
        "simulated_posts": [
            {
                "title": "Done with Delta after that 14-hour delay nightmare - which airline for SFO-NRT?",
                "body": "Booked Delta to Tokyo for honeymoon last month, got stranded 14 hours in Seattle, lost half a day in Japan. Done with them. Looking at ANA, Singapore Air, or JAL for our anniversary trip next May. Budget is flexible (up to $4K/person business class). What's been everyone's experience switching from Delta? Specifically interested in seat width and ground crew responsiveness during disruptions.",
                "subreddit": "travel",
            },
        ],
    },
}


# ============================================================
# IDENTITY RESOLUTION
# ============================================================

def is_demo_persona_handle(handle):
    """Check if a Reddit user handle matches any configured persona."""
    if not handle:
        return None
    handle_lower = handle.lower().strip().lstrip("u/")
    for persona_id, persona in DEMO_PERSONAS.items():
        persona_handle_clean = persona["reddit_handle"].lower().lstrip("u/")
        if handle_lower == persona_handle_clean:
            return persona
    return None


def get_persona_by_id(persona_id):
    return DEMO_PERSONAS.get(persona_id)


def list_personas():
    return list(DEMO_PERSONAS.values())


# ============================================================
# RECIPIENT ROUTING (with plus-aliasing for email)
# ============================================================

def get_persona_email_recipient(persona):
    """
    Returns persona-tagged email using Gmail/Outlook plus-aliasing.
    [email protected] + tag=priya => [email protected]
    """
    base_email = os.getenv("DEMO_RECIPIENT_EMAIL", "").strip()
    if not base_email or "@" not in base_email:
        return base_email or ""

    tag = persona.get("email_tag", "")
    if not tag:
        return base_email

    local, domain = base_email.split("@", 1)
    return f"{local}+{tag}@{domain}"


def get_persona_sms_recipient(persona):
    """SMS doesn't support plus-aliasing; all personas share the one verified phone."""
    return os.getenv("DEMO_RECIPIENT_PHONE", "").strip()


def get_persona_sms_prefix(persona):
    """Prefix to prepend to SMS body so you can identify which persona it's for."""
    return persona.get("sms_prefix", "")


def get_persona_social_label(persona):
    """Label used in Discord/Slack post title to identify the persona."""
    return f"{persona.get('emoji', '🎭')} {persona.get('first_name', 'Persona')} {persona.get('last_name', '')}".strip()


# ============================================================
# SIMULATED POST INJECTION (hybrid mode)
# ============================================================

def get_simulated_persona_signal(persona, post_index=0):
    """
    Build a Reddit-style signal for a persona's simulated post.
    Used as fallback when the real Reddit post isn't found in the feed
    (e.g. removed by AutoMod, posted too recently to be cached, etc.)
    """
    posts = persona.get("simulated_posts", [])
    if not posts:
        return None
    post = posts[post_index % len(posts)]

    handle = persona["reddit_handle"]
    title = post["title"]
    body = post["body"]
    subreddit = post["subreddit"]

    content = f"{title}\n\n{body}"

    return {
        "id": f"persona_{persona['id']}_post_{post_index}",
        "platform": "Reddit",
        "user_handle": handle,
        "user_profile": f"r/{subreddit} Reddit user (demo persona)",
        "post_time": "recently",
        "engagement": "controlled - demo persona post",
        "post_content": content,
        # No _reddit_url means it won't show the verifiable banner.
        # We'll add a different "demo persona" banner instead.
        "_demo_persona_id": persona["id"],
        "_simulated_subreddit": subreddit,
        "_reddit_score": 25,
    }


def inject_personas_into_feed(real_signals, personas_to_include=None, only_if_missing=True):
    """
    Add persona signals to a feed of real Reddit posts.

    Args:
      real_signals:        list of signals already fetched from Reddit
      personas_to_include: list of persona IDs (default: all)
      only_if_missing:     if True, only add simulated post when persona's
                           real handle is NOT already in real_signals
                           (hybrid mode - real first, simulated fallback)

    Returns:
      (combined_signals, injection_log)
      injection_log is a list of strings describing what was injected/skipped
    """
    if personas_to_include is None:
        personas_to_include = list(DEMO_PERSONAS.keys())

    log = []
    combined = list(real_signals)
    existing_handles = {s.get("user_handle", "").lower() for s in real_signals}

    for persona_id in personas_to_include:
        persona = DEMO_PERSONAS.get(persona_id)
        if not persona:
            continue

        handle_lower = persona["reddit_handle"].lower()
        already_in_feed = handle_lower in existing_handles

        if only_if_missing and already_in_feed:
            log.append(f"✓ {persona['first_name']} ({persona['reddit_handle']}) - REAL post found, using it")
            continue

        sim_signal = get_simulated_persona_signal(persona)
        if sim_signal:
            combined.append(sim_signal)
            log.append(f"+ {persona['first_name']} ({persona['reddit_handle']}) - injected simulated post (real not found)")

    return combined, log


# ============================================================
# CONVERSATION THREAD TRACKING (for chat-bubble UI)
# ============================================================
# In-memory conversation log keyed by persona_id. Each entry:
#   {"direction": "outbound|inbound", "channel": "email|sms|social",
#    "subject": str, "body": str, "timestamp": iso, "message_id": str}

_conversation_threads = {}


def record_outbound(persona_id, channel, subject, body, message_id=None, success=True):
    """Record an outbound message for a persona's conversation thread."""
    thread = _conversation_threads.setdefault(persona_id, [])
    thread.append({
        "direction": "outbound",
        "channel": channel,
        "subject": subject,
        "body": body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": message_id or f"out_{int(datetime.now().timestamp())}",
        "success": success,
    })


def record_inbound(persona_id, channel, subject, body, message_id=None):
    """Record an inbound reply for a persona's conversation thread."""
    thread = _conversation_threads.setdefault(persona_id, [])
    thread.append({
        "direction": "inbound",
        "channel": channel,
        "subject": subject,
        "body": body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": message_id or f"in_{int(datetime.now().timestamp())}",
        "success": True,
    })


def get_conversation_thread(persona_id):
    """Return list of conversation entries for a persona, oldest first."""
    return list(_conversation_threads.get(persona_id, []))


def get_all_conversation_threads():
    """Return dict of all persona threads."""
    return {pid: list(thread) for pid, thread in _conversation_threads.items()}


def clear_conversation_thread(persona_id=None):
    """Clear a specific persona's thread or all threads."""
    if persona_id:
        _conversation_threads.pop(persona_id, None)
    else:
        _conversation_threads.clear()


# ============================================================
# IDENTIFY PERSONA FROM INBOUND MESSAGE (for webhook routing)
# ============================================================

def identify_persona_from_email(to_address):
    """Extract persona from an inbound email's To address."""
    if not to_address or "+" not in to_address:
        return None
    # [email protected] -> tag=priya
    match = re.search(r"\+([a-z0-9_-]+)@", to_address.lower())
    if not match:
        return None
    tag = match.group(1)
    for persona in DEMO_PERSONAS.values():
        if persona.get("email_tag", "").lower() == tag:
            return persona
    return None


def identify_persona_from_sms(body):
    """
    Extract persona from an inbound SMS body.
    Since all personas share one phone, we look for tags the user typed
    OR fall back to the most recent outbound recipient.
    """
    if not body:
        return None
    body_upper = body.upper()
    # Look for [PRIYA], [MARCUS], [SARAH] etc as user reply prefix
    for persona in DEMO_PERSONAS.values():
        prefix = persona.get("sms_prefix", "").upper()
        if prefix and prefix in body_upper:
            return persona
    return None
