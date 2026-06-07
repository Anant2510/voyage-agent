"""
Simulated customer database for Path A demos.

In production this would be a real CDP (Customer Data Platform) — Segment,
mParticle, Salesforce CDP, Adobe Real-Time CDP, etc. — backed by a database
of millions of customer profiles with marketing consent records.

For the demo, we simulate three customers whose social handles we recognize.
These are the "Path A" identities. Anyone else from the firehose is Path B.

The three personas exercise different path scenarios:
  - Sarah:     Full consent (Path A complete) → best case
  - Marcus:    Partial consent (SMS opted out) → channel-aware
  - Emma:      Family advocate (high LTV) → value-aware
"""


# ============================================================
# CUSTOMER RECORDS
# ============================================================

CUSTOMERS = {
    "VC_8472": {
        "customer_id": "VC_8472",
        "name": "Sarah Mitchell",
        "email": "sarah.mitchell92@gmail.com",
        "phone": "+1 512-555-0184",
        "city": "Austin, TX",
        "zip": "78704",
        "social_handles": {
            "instagram": "@sarah.wanders",
            "twitter": "@sarahmwanders"
        },
        "segment": "Premium Solo Traveler",
        "ltv_estimate_usd": 8500,
        "lifetime_value_tier": "premium",
        "relationship": "Newsletter subscriber since 2023 · Booked Cancun trip Jan 2023",
        "consent": {
            "email_marketing":  {"status": True,  "captured": "2023-01-14", "source": "Booking flow"},
            "sms_marketing":    {"status": True,  "captured": "2023-01-14", "source": "Booking flow"},
            "instagram_dm":     {"status": True,  "captured": "2024-06-02", "source": "Story tap-back"},
            "retargeting":      {"status": True,  "captured": "2023-01-10", "source": "Cookie accept"}
        },
        "booking_history": [
            {"destination": "Cancun, MX", "date": "2023-01-22", "spend_usd": 2400},
            {"destination": "Park City, UT", "date": "2022-03-15", "spend_usd": 1850}
        ]
    },

    "VC_3391": {
        "customer_id": "VC_3391",
        "name": "Marcus Chen",
        "email": "marcus.chen@gmail.com",
        "phone": "+1 415-555-0211",
        "city": "San Francisco, CA",
        "zip": "94107",
        "social_handles": {
            "instagram": "@marcuschen",
            "twitter": "@marcuschen_sf"
        },
        "segment": "Premium Frequent Traveler",
        "ltv_estimate_usd": 12000,
        "lifetime_value_tier": "premium",
        "relationship": "VIP customer · 4 trips in past 24 months",
        "consent": {
            "email_marketing":  {"status": True,  "captured": "2022-08-04", "source": "Booking flow"},
            "sms_marketing":    {"status": False, "captured": "2024-03-19", "source": "Preferences page (opted out)"},
            "instagram_dm":     {"status": True,  "captured": "2023-09-11", "source": "DM opt-in flow"},
            "retargeting":      {"status": True,  "captured": "2022-08-04", "source": "Cookie accept"}
        },
        "booking_history": [
            {"destination": "Tokyo, JP", "date": "2024-09-18", "spend_usd": 4200},
            {"destination": "Reykjavik, IS", "date": "2024-02-08", "spend_usd": 3100},
            {"destination": "Lisbon, PT", "date": "2023-05-22", "spend_usd": 2800},
            {"destination": "Bali, ID", "date": "2022-11-14", "spend_usd": 3600}
        ]
    },

    "VC_5527": {
        "customer_id": "VC_5527",
        "name": "Emma Rodriguez",
        "email": "emma.r.travel@gmail.com",
        "phone": "+1 305-555-0145",
        "city": "Miami, FL",
        "zip": "33133",
        "social_handles": {
            "instagram": "@emmarodriguez_",
            "tiktok": "@emmarodriguez_travel"
        },
        "segment": "Family Adventure",
        "ltv_estimate_usd": 18500,
        "lifetime_value_tier": "vip",
        "relationship": "Travel blogger partner · Brand ambassador · 22K Instagram followers",
        "consent": {
            "email_marketing":  {"status": True,  "captured": "2021-05-12", "source": "Partnership agreement"},
            "sms_marketing":    {"status": True,  "captured": "2021-05-12", "source": "Partnership agreement"},
            "instagram_dm":     {"status": True,  "captured": "2021-05-12", "source": "Partnership agreement"},
            "retargeting":      {"status": True,  "captured": "2021-05-12", "source": "Cookie accept"}
        },
        "booking_history": [
            {"destination": "Costa Rica family safari", "date": "2024-07-04", "spend_usd": 6200},
            {"destination": "Disney World", "date": "2024-03-15", "spend_usd": 4100},
            {"destination": "Galápagos", "date": "2023-08-22", "spend_usd": 8200}
        ]
    }
}


# ============================================================
# LOOKUP — by social handle
# ============================================================

def find_customer_by_social_handle(platform, handle):
    """
    Look up a customer by their social handle on a given platform.
    Returns the customer record dict, or None if no match.

    Platform names are case-insensitive ('Instagram', 'instagram' both work).
    Handle matching is also case-insensitive.
    """
    if not handle:
        return None

    platform_key = platform.lower() if platform else ""
    handle_lower = handle.lower().strip()

    for customer in CUSTOMERS.values():
        social = customer.get("social_handles", {})
        for plat, h in social.items():
            if plat.lower() == platform_key and h.lower() == handle_lower:
                return customer

    return None


def get_customer_summary(customer):
    """One-line summary of a customer record (for logs / debug)."""
    if not customer:
        return "Unknown (Path B — anonymous)"
    return (
        f"{customer['name']} ({customer['customer_id']}) · "
        f"{customer['segment']} · "
        f"LTV ${customer['ltv_estimate_usd']:,}"
    )


# ============================================================
# PATH CLASSIFICATION — A vs B
# ============================================================

def has_active_consent(customer, channel):
    """Check whether a customer has given consent for a specific marketing channel."""
    if not customer:
        return False
    consent = customer.get("consent", {})
    record = consent.get(channel)
    return bool(record and record.get("status"))


def get_available_channels(customer):
    """
    Return a list of channel availability objects given a customer record.
    Each item: {channel, label, available, rationale}.
    """
    if not customer:
        # Path B — anonymous net-new
        return [
            {"channel": "instagram_organic", "label": "Instagram public reply",  "available": True,  "rationale": "Public engagement — no consent required"},
            {"channel": "retargeting",       "label": "Pixel retargeting ads",   "available": True,  "rationale": "Cookie-based, anonymous, GDPR-compliant via consent banner"},
            {"channel": "meta_lookalike",    "label": "Meta lookalike audience", "available": True,  "rationale": "Anonymous audience extension via past customer modeling"},
            {"channel": "email",             "label": "Email direct",            "available": False, "rationale": "No email on file"},
            {"channel": "sms",               "label": "SMS direct",              "available": False, "rationale": "No phone on file"},
            {"channel": "instagram_dm",      "label": "Instagram DM",            "available": False, "rationale": "Cold DM violates platform terms — not permitted"},
        ]

    # Path A — known customer
    channels = []
    channel_specs = [
        ("email",             "Email direct"),
        ("sms",               "SMS direct"),
        ("instagram_dm",      "Instagram DM"),
        ("retargeting",       "Pixel retargeting ads"),
    ]
    for ch_key, ch_label in channel_specs:
        if has_active_consent(customer, ch_key):
            channels.append({
                "channel": ch_key,
                "label": ch_label,
                "available": True,
                "rationale": f"Active consent on file ({customer['consent'][ch_key]['captured']})"
            })
        else:
            channels.append({
                "channel": ch_key,
                "label": ch_label,
                "available": False,
                "rationale": "No consent or opted out"
            })

    # Public channels are always available
    channels.append({"channel": "instagram_organic", "label": "Instagram public reply", "available": True, "rationale": "Public engagement — no consent required"})
    channels.append({"channel": "meta_lookalike",    "label": "Meta lookalike audience", "available": True, "rationale": "Anonymous audience extension"})

    return channels


def classify_lead_path(customer):
    """
    Given a customer lookup result, return the full Path A/B classification object.
    """
    if customer:
        return {
            "path": "A",
            "label": "Path A — Known customer (full channel mix)",
            "description": (
                f"Identity stitched to **{customer['name']}** (`{customer['customer_id']}`) — "
                f"{customer['segment']}, LTV ${customer['ltv_estimate_usd']:,}. "
                f"{customer['relationship']}."
            ),
            "lawful_basis": "Consent (explicit opt-in on file) — GDPR Art. 6(1)(a) / CCPA opt-in",
            "channels_available": get_available_channels(customer),
            "customer_record": customer
        }
    else:
        return {
            "path": "B",
            "label": "Path B — Net-new anonymous (organic + retargeting only)",
            "description": (
                "No identity match in CDP. This is a net-new prospect from public social. "
                "We have NO PII (email, phone, address) and NO consent record. "
                "Reachable only via public organic engagement + anonymous lookalike ads."
            ),
            "lawful_basis": "Legitimate interest (public post engagement) + aggregated/anonymous audiences",
            "channels_available": get_available_channels(None),
            "customer_record": None
        }
