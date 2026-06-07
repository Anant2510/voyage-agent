"""
Hashtag / Scope Configuration for the Lead Discovery agent.

Defines the "listening scope" — what should and shouldn't count as a relevant
travel signal. The agent filters the social firehose against this scope BEFORE
making any LLM call (cheap rules-based filter, no AI cost).

Four presets:
  - airlines:        miles/points/award booking community
  - travel_booking:  broad mass-market travel intent (DEFAULT)
  - luxury:          high-budget premium travel
  - custom:          user pastes their own config

Each preset has:
  - include_hashtags    list of # tags (case-insensitive substring match)
  - include_keywords    list of free-text intent phrases
  - competitor_mentions list of @ handles or brand names
  - exclude_keywords    veto list — any match here rejects the signal
"""


# ============================================================
# PRESETS
# ============================================================

PRESETS = {
    "airlines": {
        "name": "Airlines",
        "description": "Miles/points/award travel community + flight-search intent.",
        "include_hashtags": [
            "#flightdeals", "#milesandpoints", "#awardtravel", "#travelhacks",
            "#aviation", "#avgeek", "#firstclass", "#businessclass",
            "#frequentflyer", "#statusmatching", "#redemption"
        ],
        "include_keywords": [
            "miles", "points", "award booking", "business class", "first class",
            "transfer partners", "elite status", "lounge access", "upgrade",
            "saver award", "open jaw", "stopover", "fuel surcharge"
        ],
        "competitor_mentions": [
            "@delta", "@united", "@americanair", "@britishairways", "@lufthansa",
            "@aircanada", "@emirates", "@qatarairways", "@singaporeair"
        ],
        "exclude_keywords": [
            "flight school", "pilot training", "ppl exam", "aviation career",
            "aircraft mechanic", "atc", "model airplane"
        ]
    },

    "travel_booking": {
        "name": "Travel Booking",
        "description": "Mass-market travel: trip planning, recommendations, vacation intent.",
        "include_hashtags": [
            "#wanderlust", "#travelplanning", "#vacation", "#honeymoon",
            "#familytravel", "#solofemaletravel", "#bucketlist", "#travelgram",
            "#adventuretravel", "#mountainsareclose", "#beachvacation",
            "#cruise", "#allinclusive", "#weekendgetaway", "#luxurytravel",
            "#flightdeals", "#travel"
        ],
        "include_keywords": [
            "need a vacation", "planning a trip", "recommendations for", "anyone done",
            "where should I", "best time to visit", "looking at", "booking",
            "thinking about going", "budget around", "we want to go",
            "ready to book", "deciding between", "comparing"
        ],
        "competitor_mentions": [
            "@expedia", "@booking.com", "@kayak", "@tripadvisor", "@airbnb",
            "@vrbo", "@hotwire", "@priceline", "@orbitz", "@momondo",
            "@hopper", "@trivago"
        ],
        "exclude_keywords": [
            "job", "relocating", "moving to", "permanent residence",
            "visa application", "immigration", "h1b", "green card",
            "real estate", "buying a house"
        ]
    },

    "luxury": {
        "name": "Luxury Travel",
        "description": "Premium / ultra-high-end travel: private villas, FBO, charter.",
        "include_hashtags": [
            "#luxurytravel", "#privatevilla", "#fivestarhotel", "#fourseasons",
            "#aman", "#peninsulahotels", "#privatejet", "#yachtcharter",
            "#sevenstar", "#destinationwedding", "#exclusiveexperiences"
        ],
        "include_keywords": [
            "private villa", "five star", "concierge", "butler", "private jet",
            "yacht charter", "destination wedding", "presidential suite",
            "ultra luxury", "all inclusive luxury", "exclusive use",
            "private island", "michelin"
        ],
        "competitor_mentions": [
            "@fourseasons", "@aman", "@peninsulahotels", "@ritzcarlton",
            "@stregishotels", "@mandarinoriental", "@belmond", "@rosewood"
        ],
        "exclude_keywords": [
            "hostel", "backpacking", "budget", "cheap", "deal hunting",
            "free", "discount code", "extreme couponing"
        ]
    },

    "custom": {
        "name": "Custom",
        "description": "Paste your own hashtags, keywords, and competitor handles.",
        "include_hashtags": [],
        "include_keywords": [],
        "competitor_mentions": [],
        "exclude_keywords": []
    }
}


# ============================================================
# ACCESSORS
# ============================================================

def get_preset(key):
    """Return a deep copy of a preset by key. Returns travel_booking if key unknown."""
    preset = PRESETS.get(key, PRESETS["travel_booking"])
    # Deep copy via dict comprehension (lists need explicit copy)
    return {
        "name": preset["name"],
        "description": preset["description"],
        "include_hashtags": list(preset["include_hashtags"]),
        "include_keywords": list(preset["include_keywords"]),
        "competitor_mentions": list(preset["competitor_mentions"]),
        "exclude_keywords": list(preset["exclude_keywords"])
    }


def parse_user_config(text):
    """
    Parse a user-edited config textarea back into a config dict.
    Supports section headers like '# Hashtags', '# Keywords', '# Competitor handles',
    '# Exclusions'. Lines without a header default to hashtags if they start with '#',
    otherwise keywords.
    """
    config = {
        "name": "Custom",
        "description": "User-defined scope",
        "include_hashtags": [],
        "include_keywords": [],
        "competitor_mentions": [],
        "exclude_keywords": []
    }

    section = "include_hashtags"  # default if no header

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        if lower.startswith("# hashtag"):
            section = "include_hashtags"
            continue
        if lower.startswith("# keyword"):
            section = "include_keywords"
            continue
        if lower.startswith("# competitor"):
            section = "competitor_mentions"
            continue
        if lower.startswith("# exclus"):
            section = "exclude_keywords"
            continue
        if line.startswith("#") and not lower.startswith("# "):
            # It's a hashtag line, not a section header
            config["include_hashtags"].append(line)
            continue
        if line.startswith("@"):
            config["competitor_mentions"].append(line)
            continue

        # Fall through — add to current section
        config[section].append(line)

    return config


def config_summary(config):
    """Return a one-line summary of a config."""
    return (
        f"{config.get('name', 'Custom')}: "
        f"{len(config['include_hashtags'])} hashtags · "
        f"{len(config['include_keywords'])} keywords · "
        f"{len(config['competitor_mentions'])} competitors · "
        f"{len(config['exclude_keywords'])} exclusions"
    )


# ============================================================
# SCOPE MATCHING — rules-based filter (no LLM)
# ============================================================

def signal_matches_config(signal, config):
    """
    Test whether a social signal matches a listening config.

    Returns:
      {
        "matched": True / False,
        "reasons": list of reasons why it matched,
        "excluded_by": exclusion keyword if rejected, else None
      }

    Logic:
      1. Build the searchable text (post content + user handle)
      2. Check exclusions FIRST — any match rejects the signal
      3. Then check hashtags, keywords, competitor handles in any order
      4. ANY positive match → matched = True
    """
    text = (signal.get("post_content", "") + " " + signal.get("user_handle", "")).lower()

    # Veto pass — exclusions
    for excl in config.get("exclude_keywords", []):
        if excl.lower() in text:
            return {"matched": False, "reasons": [], "excluded_by": excl}

    reasons = []

    # Hashtags
    for tag in config.get("include_hashtags", []):
        if tag.lower() in text:
            reasons.append(f"hashtag {tag}")

    # Keywords
    for kw in config.get("include_keywords", []):
        if kw.lower() in text:
            reasons.append(f"keyword '{kw}'")

    # Competitor handles
    for comp in config.get("competitor_mentions", []):
        if comp.lower() in text:
            reasons.append(f"competitor mention {comp}")

    return {
        "matched": len(reasons) > 0,
        "reasons": reasons,
        "excluded_by": None
    }
