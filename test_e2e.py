"""
End-to-End Test Script
======================

Runs the full Voyage Concierge pipeline on a sample of signals from both
data sources (simulated and Reddit cache) and validates:

  1. Each signal gets classified successfully
  2. Path A/B resolution works correctly
  3. Every analysis has _sources metadata (stated/inferred labels)
  4. Source labels are within expected vocabulary
  5. Sample distribution across classification tiers
  6. Cache loading works correctly

Run from project root:
    python test_e2e.py
"""

import os
import sys
import json
import traceback
from collections import defaultdict, Counter

# Imports from the app
from lead_discovery import LeadDiscoveryAgent, SOCIAL_SIGNALS
from hashtag_config import get_preset, signal_matches_config
from customer_database import find_customer_by_social_handle
from reddit_source import load_cache, has_cache, DEFAULT_SUBREDDITS


# ============================================================
# COLOR OUTPUT
# ============================================================

class C:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def ok(msg):    print(f"  {C.GREEN}OK{C.RESET}    {msg}")
def warn(msg):  print(f"  {C.YELLOW}WARN{C.RESET}  {msg}")
def fail(msg):  print(f"  {C.RED}FAIL{C.RESET}  {msg}")
def info(msg):  print(f"  {C.DIM}{msg}{C.RESET}")
def header(msg):
    print()
    print(f"{C.BOLD}{C.BLUE}{'=' * 70}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}  {msg}{C.RESET}")
    print(f"{C.BOLD}{C.BLUE}{'=' * 70}{C.RESET}")


# ============================================================
# VALIDATORS
# ============================================================

REQUIRED_ANALYSIS_KEYS = [
    "classification", "classification_reason", "intent_score",
    "trip_type", "suggested_destinations", "estimated_budget",
    "travel_window", "urgency", "lead_value_tier",
    "personalization_hooks", "recommended_first_message",
]

VALID_CLASSIFICATIONS = {
    "ready_to_book", "switching_intent", "active_research", "advocacy",
    "competitor_mention", "dreaming", "venting_only", "off_topic"
}

VALID_SOURCES = {"stated", "inferred", "unknown"}

STRUCTURED_FIELDS = ["trip_type", "suggested_destinations", "estimated_budget", "travel_window"]

REQUIRED_BANT_KEYS = {
    "destination_specific", "timeline_concrete", "budget_stated",
    "authority_clear", "action_language", "switching_language", "competitor_named"
}


def validate_analysis_structure(analysis, label):
    """Check that the analysis dict has all required keys + source metadata + BANT signals."""
    errors = []

    # Required keys
    missing = [k for k in REQUIRED_ANALYSIS_KEYS if k not in analysis]
    if missing:
        errors.append(f"missing keys: {missing}")

    # Classification value
    cls = analysis.get("classification")
    if cls not in VALID_CLASSIFICATIONS:
        errors.append(f"invalid classification: {cls!r}")

    # Score is integer 0-100
    score = analysis.get("intent_score")
    if not isinstance(score, int) or not (0 <= score <= 100):
        errors.append(f"intent_score not 0-100 int: {score!r}")

    # Confidence score
    conf = analysis.get("confidence_score")
    if conf is not None and (not isinstance(conf, int) or not (0 <= conf <= 100)):
        errors.append(f"confidence_score not 0-100 int: {conf!r}")

    # _sources should exist for new pipeline
    sources = analysis.get("_sources")
    if sources is None:
        errors.append("missing _sources metadata (source labeling)")
    else:
        for field in STRUCTURED_FIELDS:
            if field not in sources:
                errors.append(f"_sources missing entry for {field!r}")
            elif sources[field] not in VALID_SOURCES:
                errors.append(f"_sources[{field!r}] not in {VALID_SOURCES}: {sources[field]!r}")

    # BANT signals must be present with boolean values
    bant = analysis.get("bant_signals")
    if not isinstance(bant, dict):
        errors.append("missing or invalid bant_signals dict")
    else:
        missing_bant = REQUIRED_BANT_KEYS - set(bant.keys())
        if missing_bant:
            errors.append(f"bant_signals missing keys: {missing_bant}")
        for key in REQUIRED_BANT_KEYS:
            if key in bant and not isinstance(bant[key], bool):
                errors.append(f"bant_signals[{key!r}] not a boolean: {bant[key]!r}")

    # _quality_gates should be set
    gates = analysis.get("_quality_gates")
    if gates is None:
        errors.append("missing _quality_gates metadata")
    elif "bant_signal_count" not in gates:
        errors.append("_quality_gates missing bant_signal_count")

    return errors


def validate_path(path, label):
    """Check path resolution structure."""
    errors = []
    if "path" not in path:
        errors.append("path missing 'path' field")
    elif path["path"] not in ("A", "B"):
        errors.append(f"invalid path letter: {path['path']!r}")
    if "channels_available" not in path:
        errors.append("path missing channels_available")
    elif not isinstance(path["channels_available"], list):
        errors.append("channels_available not a list")
    return errors


# ============================================================
# TESTS
# ============================================================

def test_imports():
    header("TEST 1: Imports & module health")
    try:
        from agent import VoyageAgent
        from nurturing import NurturingAgent
        from tools import TOOLS
        ok("All core modules import cleanly")
        ok(f"SOCIAL_SIGNALS has {len(SOCIAL_SIGNALS)} simulated signals")
        ok(f"DEFAULT_SUBREDDITS has {len(DEFAULT_SUBREDDITS)} subreddits")
        return True
    except Exception as e:
        fail(f"Import failed: {e}")
        traceback.print_exc()
        return False


def test_cache_loading():
    header("TEST 2: Reddit cache state")
    if not has_cache():
        warn("No reddit_cache.json found - skipping cache tests")
        info("Run: python fetch_reddit_cache.py to populate")
        return None  # Skip, not fail

    signals, metadata, age_hours = load_cache()
    ok(f"Cache loaded: {len(signals)} posts")
    if age_hours is not None:
        if age_hours < 48:
            ok(f"Cache age: {age_hours:.1f}h (fresh, under 48h TTL)")
        else:
            warn(f"Cache age: {age_hours:.1f}h (STALE - over 48h TTL)")
    info(f"Cached subreddits: {', '.join('r/' + s for s in metadata.get('subreddits', []))}")
    info(f"Fetched at: {metadata.get('fetched_at_human')}")

    # Spot-check signal shape
    if signals:
        sample = signals[0]
        required_signal_keys = ["id", "platform", "user_handle", "post_content", "engagement", "post_time"]
        missing = [k for k in required_signal_keys if k not in sample]
        if missing:
            fail(f"First cached signal missing keys: {missing}")
            return False
        ok("First cached signal has all required fields")
        info(f"  Sample: [{sample['user_handle']}] {sample['post_content'][:60]}...")

    return True


def test_scope_filtering():
    header("TEST 3: Scope filtering (hashtag_config)")
    config = get_preset("travel_booking")
    info(f"Using 'travel_booking' preset: {len(config['include_hashtags'])} hashtags, {len(config['include_keywords'])} keywords")

    matched = 0
    skipped = 0
    for signal in SOCIAL_SIGNALS:
        m = signal_matches_config(signal, config)
        if m["matched"]:
            matched += 1
        else:
            skipped += 1
    ok(f"Filter ran on all {len(SOCIAL_SIGNALS)} simulated signals")
    info(f"  Matched: {matched}, Skipped: {skipped}")
    if matched == 0:
        fail("Scope filter rejected EVERY signal — check hashtag_config")
        return False
    if skipped == 0:
        warn("Scope filter accepted EVERY signal — try adjusting exclusions")
    return True


def test_simulated_classification(sample_size=3):
    header(f"TEST 4: Live LLM classification on {sample_size} simulated signals")

    agent = LeadDiscoveryAgent()
    config = get_preset("travel_booking")
    config_name = config["name"]

    # Pick first 3 that match the filter
    matched_signals = [s for s in SOCIAL_SIGNALS if signal_matches_config(s, config)["matched"]]
    if len(matched_signals) < sample_size:
        warn(f"Only {len(matched_signals)} match the filter; using all of them")
        sample = matched_signals
    else:
        sample = matched_signals[:sample_size]

    classification_dist = Counter()
    source_dist = defaultdict(Counter)
    all_passed = True

    for i, signal in enumerate(sample, 1):
        info(f"[{i}/{len(sample)}] Classifying {signal['user_handle']}...")
        try:
            analysis = agent.classify_and_score(signal, config_name)
            path = agent.resolve_identity(signal)

            # Validate analysis
            errs = validate_analysis_structure(analysis, signal["user_handle"])
            if errs:
                fail(f"  Analysis validation failed: {errs}")
                all_passed = False
                continue

            # Validate path
            errs = validate_path(path, signal["user_handle"])
            if errs:
                fail(f"  Path validation failed: {errs}")
                all_passed = False
                continue

            cls = analysis["classification"]
            score = analysis["intent_score"]
            classification_dist[cls] += 1

            # Track source distribution
            for field, source in analysis.get("_sources", {}).items():
                source_dist[field][source] += 1

            ok(f"  {signal['user_handle']}: {cls} · {score}/100 · Path {path['path']}")

            # Show source labels
            sources = analysis.get("_sources", {})
            info(f"    Sources: " + " · ".join(f"{f}={s}" for f, s in sources.items()))

        except Exception as e:
            fail(f"  Classification crashed: {e}")
            traceback.print_exc()
            all_passed = False

    print()
    info(f"Classification distribution: {dict(classification_dist)}")
    print()
    info("Source labeling distribution across the sample:")
    for field, counter in source_dist.items():
        info(f"  {field}: {dict(counter)}")

    return all_passed


def test_reddit_classification(sample_size=3):
    header(f"TEST 5: Live LLM classification on {sample_size} Reddit signals")

    if not has_cache():
        warn("No cache to test against. Skipping.")
        return None

    signals, _, _ = load_cache()
    if not signals:
        warn("Cache empty. Skipping.")
        return None

    config = get_preset("travel_booking")
    matched = [s for s in signals if signal_matches_config(s, config)["matched"]]
    if not matched:
        warn("No Reddit signals match the travel_booking scope. Skipping.")
        info("This is unusual - your cache may need refreshing or scope is too narrow")
        return None

    sample = matched[:sample_size]
    info(f"{len(matched)} of {len(signals)} cached posts match the scope filter")

    agent = LeadDiscoveryAgent()
    classification_dist = Counter()
    all_passed = True

    for i, signal in enumerate(sample, 1):
        info(f"[{i}/{len(sample)}] Classifying {signal['user_handle']}...")
        try:
            analysis = agent.classify_and_score(signal, config["name"])
            path = agent.resolve_identity(signal)

            errs = validate_analysis_structure(analysis, signal["user_handle"]) + validate_path(path, signal["user_handle"])
            if errs:
                fail(f"  Validation failed: {errs}")
                all_passed = False
                continue

            cls = analysis["classification"]
            classification_dist[cls] += 1
            ok(f"  {signal['user_handle']} ({signal['platform']}): {cls} · {analysis['intent_score']}/100 · Path {path['path']}")
            info(f"    Post excerpt: {signal['post_content'][:80]}...")

            # Show what was stated vs inferred
            sources = analysis.get("_sources", {})
            stated = [f for f, s in sources.items() if s == "stated"]
            inferred = [f for f, s in sources.items() if s == "inferred"]
            if stated:
                info(f"    User explicitly stated: {', '.join(stated)}")
            if inferred:
                info(f"    AI inferred from context: {', '.join(inferred)}")

        except Exception as e:
            fail(f"  Classification crashed: {e}")
            traceback.print_exc()
            all_passed = False

    print()
    info(f"Reddit classification distribution: {dict(classification_dist)}")
    return all_passed


def test_path_a_resolution():
    header("TEST 6: Path A (known customer) resolution")

    # Sarah is in customer_database — should resolve to Path A
    sarah_signal = {
        "id": "test_sarah",
        "platform": "Instagram",
        "user_handle": "@sarah.wanders",
        "user_profile": "Travel enthusiast - Austin TX",
        "post_time": "1 hour ago",
        "engagement": "47 likes",
        "post_content": "Q4 broke me. Need to disappear into the mountains.",
    }

    agent = LeadDiscoveryAgent()
    path = agent.resolve_identity(sarah_signal)
    if path["path"] == "A":
        ok("Sarah (@sarah.wanders) correctly resolved to Path A")
        info(f"  Label: {path['label']}")
        info(f"  Channels available: {sum(1 for c in path['channels_available'] if c['available'])} of {len(path['channels_available'])}")
        return True
    else:
        fail(f"Sarah should be Path A but got Path {path['path']}")
        return False


def test_path_b_resolution():
    header("TEST 7: Path B (anonymous) resolution")
    # Random Reddit-style handle that doesn't match the customer DB
    unknown_signal = {
        "id": "test_unknown",
        "platform": "Reddit",
        "user_handle": "u/random_traveler_99",
        "user_profile": "r/travel Reddit user",
        "post_time": "2 hours ago",
        "engagement": "5 upvotes, 2 comments",
        "post_content": "Looking for budget Europe tips for a 2 week trip in September",
    }

    agent = LeadDiscoveryAgent()
    path = agent.resolve_identity(unknown_signal)
    if path["path"] == "B":
        ok("Unknown Reddit handle correctly resolved to Path B")
        info(f"  Label: {path['label']}")
        return True
    else:
        fail(f"Unknown user should be Path B but got Path {path['path']}")
        return False


# ============================================================
# RUNNER
# ============================================================

def main():
    print()
    print(f"{C.BOLD}Voyage Concierge — End-to-End Test{C.RESET}")
    print(f"{C.DIM}Tests imports, scope filtering, classification with source labeling,")
    print(f"path resolution, and cache loading.{C.RESET}")
    print()

    results = {}
    results["1. Imports"] = test_imports()
    if not results["1. Imports"]:
        print()
        print(f"{C.RED}Cannot proceed — core imports failed.{C.RESET}")
        sys.exit(1)

    results["2. Cache loading"] = test_cache_loading()
    results["3. Scope filtering"] = test_scope_filtering()
    results["4. Simulated classification (3 samples)"] = test_simulated_classification(3)
    results["5. Reddit classification (3 samples)"] = test_reddit_classification(3)
    results["6. Path A resolution"] = test_path_a_resolution()
    results["7. Path B resolution"] = test_path_b_resolution()

    header("SUMMARY")
    for name, status in results.items():
        if status is True:
            print(f"  {C.GREEN}PASS{C.RESET}    {name}")
        elif status is False:
            print(f"  {C.RED}FAIL{C.RESET}    {name}")
        else:
            print(f"  {C.YELLOW}SKIP{C.RESET}    {name}")

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    print()
    print(f"  Passed: {passed} · Failed: {failed} · Skipped: {skipped}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
