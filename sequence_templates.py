"""
Sequence Templates - Voyage Concierge

Industry-backed nurture sequence definitions for each lead classification tier.
Based on research from Brevo, AWeber, Braze, Bloomreach, Attentive, Dynamic Yield:
  - Welcome series: 5 emails over 14 days
  - B2B/travel nurture: 8-12 emails over 6-9 weeks
  - Cart abandonment: 3 emails over 72 hours (recovers 14-22%)
  - Re-engagement: 4 emails over 30 days
  - Cold/Path B: 3+ follow-ups boost response 28%

Each template defines:
  - touches: ordered list of touchpoints
  - branching: behavioral logic per touch
  - exit_triggers: what stops the sequence
"""

# ============================================================
# CHANNEL DEFINITIONS - cost, throughput, performance norms
# ============================================================

CHANNEL_CATALOG = {
    "email": {
        "label": "Email",
        "emoji": "📧",
        "cost_per_send": 0.0001,   # Klaviyo blended rate
        "vendor": "Klaviyo",
        "consent_required": True,
        "path_b_allowed": False,
        "avg_open": 0.22,
        "avg_ctr": 0.035,
        "tooltip": "Detailed content, longer attention spans, low cost",
    },
    "sms": {
        "label": "SMS",
        "emoji": "📱",
        "cost_per_send": 0.0079,   # Twilio US rate
        "vendor": "Twilio",
        "consent_required": True,
        "path_b_allowed": False,
        "avg_open": 0.98,
        "avg_ctr": 0.19,
        "tooltip": "High urgency, immediate visibility, premium cost",
    },
    "retargeting": {
        "label": "Pixel retargeting",
        "emoji": "🎯",
        "cost_per_send": 0.00085,  # Meta CPM-based, normalized per impression
        "vendor": "Meta Marketing API",
        "consent_required": False,
        "path_b_allowed": True,
        "avg_open": 0.55,           # Impression rate
        "avg_ctr": 0.012,
        "tooltip": "Cookie-based, anonymous, GDPR compliant via consent banner",
    },
    "ig_dm": {
        "label": "Instagram DM",
        "emoji": "💬",
        "cost_per_send": 0.00,
        "vendor": "Meta Direct API",
        "consent_required": True,
        "path_b_allowed": False,    # Cold DMs violate platform terms
        "avg_open": 0.60,
        "avg_ctr": 0.12,
        "tooltip": "Warm follow-up only - requires prior interaction or opt-in",
    },
    "ig_reply": {
        "label": "Instagram public reply",
        "emoji": "💭",
        "cost_per_send": 0.00,
        "vendor": "Manual / Meta API",
        "consent_required": False,
        "path_b_allowed": True,
        "avg_open": 0.40,           # Estimated engagement
        "avg_ctr": 0.05,
        "tooltip": "Public engagement on prospect's own post - no consent needed",
    },
    "lookalike_ad": {
        "label": "Meta lookalike ad",
        "emoji": "📣",
        "cost_per_send": 0.0007,
        "vendor": "Meta Marketing API",
        "consent_required": False,
        "path_b_allowed": True,
        "avg_open": 0.45,
        "avg_ctr": 0.018,
        "tooltip": "Anonymous audience extension - no PII exposure",
    },
    "push": {
        "label": "Push notification",
        "emoji": "🔔",
        "cost_per_send": 0.00,
        "vendor": "Internal (app)",
        "consent_required": True,
        "path_b_allowed": False,
        "avg_open": 0.07,
        "avg_ctr": 0.03,
        "tooltip": "Requires app install and notification permission",
    },
}


# ============================================================
# SEQUENCE TEMPLATES - per classification tier
# ============================================================
# Each touch has:
#   day:              when it fires (days after enrollment)
#   hour:             local hour of day (24h) - optimal send time
#   channel:          key from CHANNEL_CATALOG
#   purpose:          short descriptor of what this touch does
#   subject_template: starter subject line (LLM may refine)
#   body_hint:        short instruction for the LLM to generate body
#   cta_template:     starter call-to-action
#   branching:        dict of next-step rules based on engagement outcome

SEQUENCE_TEMPLATES = {
    # ============================================================
    # HOT TIER
    # ============================================================
    "ready_to_book": {
        "name": "Booking-imminent acceleration",
        "description": "3-touch rapid sequence over 72h. Industry pattern: cart abandonment style. Recovery rate target 14-22%.",
        "duration_days": 3,
        "exit_triggers": [
            "User books -> exit, route to confirmation flow",
            "User replies -> pause, route to human agent",
            "User unsubscribes -> permanent suppression",
        ],
        "touches": [
            {
                "id": 1,
                "day": 0,
                "hour": 10,
                "channel": "email",
                "purpose": "Immediate quote / hold-the-spot",
                "subject_template": "Your {destination} trip - quote ready",
                "body_hint": "Acknowledge their stated needs, offer a 24-hour price hold, include 1-2 quick options matching their criteria",
                "cta_template": "View itinerary",
                "branching": {
                    "opened_clicked": "Skip to Touch 3 (close)",
                    "opened_no_click": "Send Touch 2 with social proof",
                    "unopened_48h": "Switch to SMS for Touch 2",
                }
            },
            {
                "id": 2,
                "day": 1,
                "hour": 14,
                "channel": "sms",
                "purpose": "Time-sensitive nudge with social proof",
                "subject_template": None,
                "body_hint": "SMS-length (max 160 chars). Reference price hold expiry + one customer testimonial element",
                "cta_template": "Book now",
                "branching": {
                    "clicked": "Skip to Touch 3 immediately",
                    "no_response_24h": "Trigger Touch 3",
                }
            },
            {
                "id": 3,
                "day": 2,
                "hour": 9,
                "channel": "email",
                "purpose": "Close - urgency + concession",
                "subject_template": "Last chance: {destination} hold expires today",
                "body_hint": "Strong urgency framing, include a small concession (free upgrade, flexible cancellation, or human agent call), one clear CTA",
                "cta_template": "Reserve now",
                "branching": {
                    "clicked": "Route to live agent for close",
                    "no_response": "Move to long-tail retargeting + drop sequence",
                }
            },
        ],
    },

    "switching_intent": {
        "name": "Brand-switch winback play",
        "description": "5-touch sequence over 14 days. Winback conversion rate target 8-15% (industry: 20-30% for own lapsed, ~10% for competitive switches).",
        "duration_days": 14,
        "exit_triggers": [
            "User books -> exit",
            "User replies -> route to human agent (high-value rescue conversation)",
            "User opts out -> suppression",
            "30 days inactivity -> move to dormant tier",
        ],
        "touches": [
            {
                "id": 1, "day": 0, "hour": 11, "channel": "email",
                "purpose": "Empathy + acknowledgment",
                "subject_template": "Sorry to hear about your {competitor} experience",
                "body_hint": "Acknowledge their frustration without trashing competitor. Offer one specific differentiator we deliver. NO push to buy yet.",
                "cta_template": "See how we're different",
                "branching": {"opened": "Send Touch 2 on Day 3", "unopened_48h": "Delay Touch 2 to Day 5"}
            },
            {
                "id": 2, "day": 3, "hour": 10, "channel": "email",
                "purpose": "Social proof from similar switchers",
                "subject_template": "How 1,200+ travelers made the switch",
                "body_hint": "Real testimonial structure from customers who switched from competitors. Quantified benefit.",
                "cta_template": "Read their stories",
                "branching": {"clicked": "Fast-track Touch 4", "opened_no_click": "Send Touch 3 as scheduled"}
            },
            {
                "id": 3, "day": 7, "hour": 13, "channel": "retargeting",
                "purpose": "Stay top-of-mind during decision window",
                "subject_template": None,
                "body_hint": "Display ad: clear value prop + destination imagery aligned to their interest",
                "cta_template": "Plan your next trip",
                "branching": {"impressed_3x_no_click": "Increase frequency to Touch 4 trigger"}
            },
            {
                "id": 4, "day": 10, "hour": 9, "channel": "email",
                "purpose": "Switching offer - meaningful incentive",
                "subject_template": "A switching credit just for you",
                "body_hint": "$100-200 first-booking credit with clear conditions. Show comparison: 'You'd pay X with old provider, Y with us'",
                "cta_template": "Claim credit",
                "branching": {"clicked": "Route to agent", "opened_no_click": "Send Touch 5"}
            },
            {
                "id": 5, "day": 14, "hour": 11, "channel": "email",
                "purpose": "Last-touch with human option",
                "subject_template": "One question before we go quiet",
                "body_hint": "Soft, no offer. Just 'what would have made the switch worth it?' Single reply CTA.",
                "cta_template": "Tell us what would change your mind",
                "branching": {"replied": "Route to retention specialist", "no_response": "Move to long-tail nurture"}
            },
        ],
    },

    # ============================================================
    # WARM TIER
    # ============================================================
    "active_research": {
        "name": "Research-phase nurture",
        "description": "6-touch sequence over 21 days. Pattern: B2B nurture (lifts MQL->SQL 35-50%). Education-first, gradual conversion.",
        "duration_days": 21,
        "exit_triggers": [
            "User books -> exit",
            "User replies / engages directly -> hand to agent",
            "90 days inactivity -> dormant nurture",
        ],
        "touches": [
            {
                "id": 1, "day": 0, "hour": 9, "channel": "email",
                "purpose": "Welcome + destination guide",
                "subject_template": "Your {destination} planning starts here",
                "body_hint": "Brief, value-first. Link to a destination guide (not a sales pitch). Set expectation of future emails.",
                "cta_template": "Read the guide",
                "branching": {"opened": "Continue", "unopened_48h": "Send Touch 2 anyway, add subject re-test"}
            },
            {
                "id": 2, "day": 4, "hour": 10, "channel": "email",
                "purpose": "Itinerary inspiration",
                "subject_template": "5 itineraries for your {trip_type} in {destination}",
                "body_hint": "Concrete itinerary ideas matching their stated parameters. Mix of budgets/styles.",
                "cta_template": "Explore itineraries",
                "branching": {"clicked": "Add itinerary preference to profile, fast-track Touch 4"}
            },
            {
                "id": 3, "day": 8, "hour": 11, "channel": "email",
                "purpose": "Authority content - destination expert",
                "subject_template": "Inside tips from our {destination} specialists",
                "body_hint": "Position as expert. Share 3-5 insider tips. Soft CTA to talk to specialist.",
                "cta_template": "Chat with a specialist",
                "branching": {"clicked": "Route to specialist", "opened_no_click": "Continue sequence"}
            },
            {
                "id": 4, "day": 12, "hour": 13, "channel": "retargeting",
                "purpose": "Visual reinforcement during decision window",
                "subject_template": None,
                "body_hint": "Display ad with destination imagery and one strong proof point",
                "cta_template": "See packages",
                "branching": {"clicked_3x": "Trigger Touch 5 next day"}
            },
            {
                "id": 5, "day": 15, "hour": 10, "channel": "email",
                "purpose": "Social proof + offer",
                "subject_template": "What other {destination} travelers booked",
                "body_hint": "Show 2-3 booked itineraries + customer testimonials. Introduce flexible booking terms.",
                "cta_template": "Build your trip",
                "branching": {"clicked": "Send Touch 6 same week with promo", "opened_no_click": "Touch 6 standard"}
            },
            {
                "id": 6, "day": 21, "hour": 9, "channel": "email",
                "purpose": "Soft close - personalized recommendation",
                "subject_template": "Ready when you are - {trip_type} ideas saved for you",
                "body_hint": "Recap their interests, present one curated package. Easy reply path.",
                "cta_template": "Get a personalized quote",
                "branching": {"clicked": "Route to agent", "no_response": "Move to monthly newsletter"}
            },
        ],
    },

    "advocacy": {
        "name": "UGC amplification + referral activation",
        "description": "4-touch sequence over 10 days. Not direct conversion - turns advocates into a referral pipeline.",
        "duration_days": 10,
        "exit_triggers": [
            "User shares referral -> route to ambassador program",
            "User replies -> nurture relationship",
        ],
        "touches": [
            {
                "id": 1, "day": 0, "hour": 14, "channel": "ig_reply",
                "purpose": "Thank-you public reply",
                "subject_template": None,
                "body_hint": "Warm, brand-voiced public response to their post. Acknowledge specifics from their share.",
                "cta_template": None,
                "branching": {"engaged": "Send Touch 2"}
            },
            {
                "id": 2, "day": 2, "hour": 10, "channel": "ig_dm",
                "purpose": "Repost permission + thank-you gift",
                "subject_template": None,
                "body_hint": "Ask permission to feature their post. Offer small token (credit, gift card).",
                "cta_template": "Allow feature",
                "branching": {"yes": "Send Touch 3", "no_response": "Skip Touch 3"}
            },
            {
                "id": 3, "day": 5, "hour": 11, "channel": "email",
                "purpose": "Ambassador invite",
                "subject_template": "Want to earn travel credits sharing trips you love?",
                "body_hint": "Invite to ambassador/referral program. Explain credit structure simply.",
                "cta_template": "Join ambassador program",
                "branching": {"clicked": "Enroll + send onboarding"}
            },
            {
                "id": 4, "day": 10, "hour": 12, "channel": "email",
                "purpose": "Share their trip again - next destination teaser",
                "subject_template": "Where to next?",
                "body_hint": "Recommend 2 destinations similar to their last trip. Mention referral credits.",
                "cta_template": "Plan next trip",
                "branching": {"clicked": "Move to active_research sequence"}
            },
        ],
    },

    # ============================================================
    # COOL TIER
    # ============================================================
    "competitor_mention": {
        "name": "Soft competitive positioning",
        "description": "4-touch over 30 days. Light touch - we don't have strong intent yet, just brand interest.",
        "duration_days": 30,
        "exit_triggers": [
            "User books -> exit",
            "User replies -> hand to agent",
            "120 days inactivity -> drop",
        ],
        "touches": [
            {
                "id": 1, "day": 0, "hour": 11, "channel": "retargeting",
                "purpose": "Awareness - position vs competitor mentioned",
                "subject_template": None,
                "body_hint": "Display ad emphasizing one differentiator vs their named competitor",
                "cta_template": "See how we compare",
                "branching": {"clicked": "Trigger Touch 2 next day"}
            },
            {
                "id": 2, "day": 7, "hour": 10, "channel": "email",
                "purpose": "Comparison guide",
                "subject_template": "How we compare on travel bookings",
                "body_hint": "Honest comparison content. 3-column: us vs competitor A vs competitor B. No trash talk.",
                "cta_template": "Read the comparison",
                "branching": {"clicked": "Send Touch 3 in 5 days"}
            },
            {
                "id": 3, "day": 16, "hour": 13, "channel": "email",
                "purpose": "Inspiration content",
                "subject_template": "Trending destinations this season",
                "body_hint": "Seasonal/trending destinations - inspire. Soft brand awareness, not pitch.",
                "cta_template": "Browse destinations",
                "branching": {"clicked": "Add destination to profile, route to active_research"}
            },
            {
                "id": 4, "day": 30, "hour": 11, "channel": "email",
                "purpose": "Conditional offer trial",
                "subject_template": "Your first trip with us - here's something extra",
                "body_hint": "Small first-booking incentive. Easy decline path.",
                "cta_template": "Claim offer",
                "branching": {"clicked": "Route to agent", "no_response": "Drop to monthly newsletter"}
            },
        ],
    },

    "dreaming": {
        "name": "Slow inspiration drip",
        "description": "5-touch over 8 weeks. Long horizon - aspirational content, no conversion pressure.",
        "duration_days": 56,
        "exit_triggers": [
            "User books -> exit",
            "User replies -> hand to agent",
            "180 days inactivity -> archive",
        ],
        "touches": [
            {
                "id": 1, "day": 0, "hour": 10, "channel": "email",
                "purpose": "Welcome to inspiration list",
                "subject_template": "Your dream trip ideas, monthly",
                "body_hint": "Set expectation: monthly inspiration, not sales pressure. Tease next month's content.",
                "cta_template": "See this month's picks",
                "branching": {"opened": "Continue", "unopened_3x": "Reduce frequency to bi-monthly"}
            },
            {
                "id": 2, "day": 14, "hour": 11, "channel": "email",
                "purpose": "Inspiration content #1",
                "subject_template": "Hidden gems: {destination_alternative_1}",
                "body_hint": "Storytelling about a lesser-known destination they might love based on their dreaming hints",
                "cta_template": "Read the story",
                "branching": {"clicked": "Note interest, accelerate to Touch 3"}
            },
            {
                "id": 3, "day": 28, "hour": 10, "channel": "email",
                "purpose": "Inspiration content #2",
                "subject_template": "Budget travel ideas: do it for less than you think",
                "body_hint": "Address budget hesitation - show price-conscious options",
                "cta_template": "See affordable trips",
                "branching": {"clicked": "Add 'budget-conscious' tag to profile"}
            },
            {
                "id": 4, "day": 42, "hour": 14, "channel": "email",
                "purpose": "Social proof + light CTA",
                "subject_template": "When dreams become trips: this month's travelers",
                "body_hint": "Customer stories of dreamers who booked. Quiet, encouraging tone.",
                "cta_template": "Start planning",
                "branching": {"clicked": "Move to active_research sequence"}
            },
            {
                "id": 5, "day": 56, "hour": 11, "channel": "email",
                "purpose": "Soft commitment ask",
                "subject_template": "Ready to talk about your dream trip?",
                "body_hint": "Optional - planning session offer. Easy decline. Reaffirm low-pressure newsletter continuance.",
                "cta_template": "Book a free planning chat",
                "branching": {"clicked": "Route to specialist", "no_response": "Continue monthly newsletter"}
            },
        ],
    },
}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_template(classification):
    """Get the sequence template for a given classification."""
    return SEQUENCE_TEMPLATES.get(classification)


def get_channel_meta(channel_key):
    """Get channel metadata."""
    return CHANNEL_CATALOG.get(channel_key, {
        "label": channel_key, "emoji": "📨", "cost_per_send": 0.0,
        "avg_open": 0.20, "avg_ctr": 0.03, "tooltip": "Unknown channel",
        "consent_required": True, "path_b_allowed": False, "vendor": "Unknown",
    })


def get_allowed_channels(path):
    """
    Returns set of channel keys allowed for this path.
    Path A has full mix. Path B is restricted to retargeting + lookalike + ig_reply.
    """
    if path == "A":
        return set(CHANNEL_CATALOG.keys())
    return {k for k, v in CHANNEL_CATALOG.items() if v.get("path_b_allowed", False)}


def filter_touches_for_path(touches, path):
    """
    Filter a touch sequence to only include channels available on this path.
    For Path B, replace email/SMS touches with retargeting or drop them.
    """
    allowed = get_allowed_channels(path)
    filtered = []
    for t in touches:
        if t["channel"] in allowed:
            filtered.append(t)
        elif path == "B":
            # For Path B, substitute disallowed channels with retargeting where possible
            replacement = dict(t)
            replacement["channel"] = "retargeting"
            replacement["purpose"] = f"[Substituted - Path B] {t['purpose']}"
            replacement["subject_template"] = None
            replacement["body_hint"] = "Display ad equivalent of the original touchpoint - cookie-based, anonymous"
            filtered.append(replacement)
    return filtered


def predict_touch_performance(touch, channel_meta, lead_classification, tier_multiplier=1.0):
    """
    Predict open rate, CTR, and conversion for a single touch.
    Factors: channel baseline + classification tier multiplier.
    """
    open_rate = channel_meta["avg_open"] * tier_multiplier
    ctr = channel_meta["avg_ctr"] * tier_multiplier
    # Open rate capped at 0.98 (SMS), CTR at 0.30
    open_rate = min(0.98, open_rate)
    ctr = min(0.30, ctr)
    return {
        "open_rate": open_rate,
        "ctr": ctr,
        "click_through_open": ctr / max(open_rate, 0.01),
    }


def calculate_sequence_cost(touches, channel_catalog=CHANNEL_CATALOG):
    """Total cost to run this sequence for one lead."""
    total = 0.0
    breakdown = {}
    for t in touches:
        cost = channel_catalog.get(t["channel"], {}).get("cost_per_send", 0.0)
        total += cost
        breakdown[t["channel"]] = breakdown.get(t["channel"], 0.0) + cost
    return total, breakdown
