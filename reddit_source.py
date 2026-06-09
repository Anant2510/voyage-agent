"""
Reddit Source - Live social listening with cache control.

Two fetch paths, tried in order:
  1. RSS feed (/r/X/new.rss)  - works reliably from datacenter IPs (Azure VM)
  2. JSON endpoint (/r/X/new.json) - legacy, often blocked from datacenters

Three modes (controlled by force_fresh parameter):
  - force_fresh=False (default): use cache if available and fresh (<48h),
    else attempt live fetch, else use stale cache with warning
  - force_fresh=True: always attempt live fetch first, save to cache,
    fall back to cache only if live fetch fails completely

Cache settings:
  - TTL warning at 48 hours (Option B: warn but still use)
  - Max 500 signals stored
"""

import json
import os
import re
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

# curl_cffi as last-resort fallback for the JSON path
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False


DEFAULT_SUBREDDITS = [
    "travel",
    "solotravel",
    "digitalnomad",
    "travelpartners",
    "awardtravel",
    "flights",
    "honeymoons",
    "JapanTravel",
    "IcelandTravel",
    "MexicoTravel",
    "europetravel",
]

POSTS_PER_SUBREDDIT = 10
MAX_CACHE_POSTS = 500
CACHE_FILE = "reddit_cache.json"
CACHE_TTL_HOURS = 48

# Rotating browser-like User-Agents (RSS endpoint is more forgiving than JSON,
# but a real-looking UA still helps)
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


# ============================================================
# CACHE FUNCTIONS
# ============================================================

def load_cache():
    """Load cached signals from disk. Returns (signals_list, metadata_dict) or ([], {})."""
    if not os.path.exists(CACHE_FILE):
        return [], {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        signals = data.get("signals", [])
        metadata = {
            "fetched_at": data.get("fetched_at"),
            "subreddits": data.get("subreddits", []),
            "post_count": len(signals),
        }
        return signals, metadata
    except (json.JSONDecodeError, IOError) as e:
        print(f"Cache load error: {e}")
        return [], {}


def save_cache(signals, subreddits):
    """Persist signals to disk. Caps at MAX_CACHE_POSTS."""
    if len(signals) > MAX_CACHE_POSTS:
        signals = signals[:MAX_CACHE_POSTS]
    data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "subreddits": subreddits,
        "signals": signals,
    }
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        print(f"Cache save error: {e}")
        return False


def cache_age_human(fetched_at_iso):
    """Format cache age as human-readable string."""
    if not fetched_at_iso:
        return "unknown"
    try:
        fetched = datetime.fromisoformat(fetched_at_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - fetched
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)} min ago"
        if hours < 24:
            return f"{int(hours)} hr ago"
        return f"{int(hours / 24)} day(s) ago"
    except (ValueError, TypeError):
        return "unknown"


def has_cache():
    """Return True if cache file exists with at least one signal."""
    signals, _ = load_cache()
    return len(signals) > 0


# ============================================================
# RSS FETCH PATH (primary - works from datacenter IPs)
# ============================================================

class _HtmlStripper(HTMLParser):
    """Strip HTML tags from RSS <content> field. Returns plain text."""
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)
    def get_text(self):
        return "".join(self.parts)


def _strip_html(html_str):
    """Convert HTML content to plain text."""
    if not html_str:
        return ""
    s = _HtmlStripper()
    try:
        s.feed(unescape(html_str))
    except Exception:
        return html_str
    text = s.get_text()
    # Collapse runs of whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_rss_to_signals(xml_bytes, subreddit, limit):
    """Parse Reddit Atom RSS feed bytes into our signal dict format."""
    signals = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"   RSS parse error for r/{subreddit}: {e}")
        return signals

    # Atom namespace
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)

    for entry in entries[:limit]:
        try:
            title_el = entry.find("atom:title", ns)
            title = title_el.text if title_el is not None else ""

            content_el = entry.find("atom:content", ns)
            body_html = content_el.text if content_el is not None else ""
            body = _strip_html(body_html)

            # Author handle
            author_el = entry.find("atom:author/atom:name", ns)
            handle = author_el.text if author_el is not None else "unknown"
            # Reddit RSS already prefixes /u/ but normalize to u/
            handle = handle.replace("/u/", "u/")
            if not handle.startswith("u/"):
                handle = f"u/{handle}"

            # Permalink
            link_el = entry.find("atom:link", ns)
            url = link_el.get("href") if link_el is not None else ""

            # ID for de-dup
            id_el = entry.find("atom:id", ns)
            post_id = id_el.text if id_el is not None else f"{subreddit}_{len(signals)}"

            # Timestamp - RSS uses <updated>
            updated_el = entry.find("atom:updated", ns)
            updated = updated_el.text if updated_el is not None else ""
            post_time_human = _humanize_time(updated)

            # Combined content
            full_content = title
            if body and body != title:
                full_content = f"{title}\n\n{body}"

            signals.append({
                "id": post_id,
                "platform": "Reddit",
                "user_handle": handle,
                "user_profile": f"r/{subreddit} Reddit user",
                "post_time": post_time_human,
                "engagement": "live Reddit post",
                "post_content": full_content,
                "_reddit_url": url,
                "_reddit_score": 0,  # RSS doesn't include upvote count
                "_source_method": "rss",
            })
        except Exception as e:
            # Skip malformed entries, don't fail the whole feed
            print(f"   Entry parse skip: {e}")
            continue

    return signals


def _humanize_time(iso_ts):
    """Convert an ISO timestamp to a relative time string."""
    if not iso_ts:
        return "recently"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)} min ago"
        if hours < 24:
            return f"{int(hours)} hr ago"
        days = int(hours / 24)
        return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return "recently"


def _fetch_subreddit_via_rss(subreddit, limit):
    """
    Fetch a subreddit's recent posts via Reddit's Atom RSS feed.
    Returns list of signals or raises an exception on failure.
    """
    url = f"https://www.reddit.com/r/{subreddit}/new.rss"
    last_err = None

    for ua in _USER_AGENTS:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": ua, "Accept": "application/atom+xml,application/rss+xml,*/*"},
                timeout=15,
            )
            if resp.status_code == 200:
                signals = _parse_rss_to_signals(resp.content, subreddit, limit)
                if signals:
                    return signals
                last_err = "RSS parsed but returned 0 entries (empty subreddit?)"
            elif resp.status_code == 403:
                last_err = "403 Forbidden"
            elif resp.status_code == 404:
                # Subreddit doesn't exist or is private - don't retry with other UAs
                raise RuntimeError(f"r/{subreddit} returned 404 (not found or private)")
            elif resp.status_code == 429:
                last_err = "429 rate-limited"
                # Brief backoff before next UA attempt
                time.sleep(2)
            else:
                last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            continue

    raise RuntimeError(f"RSS fetch failed: {last_err}")


# ============================================================
# JSON FETCH PATH (legacy fallback - often 403 from datacenters)
# ============================================================

def _try_standard_requests(url, headers, params):
    """First attempt - plain requests library."""
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        pass
    return None


def _try_cffi_with_warmup(url, params):
    """Second attempt - curl_cffi mimicking Safari (gets past some bot defenses)."""
    if not HAS_CFFI:
        return None
    try:
        session = cffi_requests.Session(impersonate="safari17_0")
        # Warmup hit on root - establishes cookies
        session.get("https://www.reddit.com/", timeout=10)
        time.sleep(1.0)
        # Real request
        resp = session.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        raise RuntimeError(f"Session warmup failed: status {resp.status_code}")
    except Exception:
        return None


def _fetch_subreddit_via_json(subreddit, limit):
    """Legacy JSON endpoint. Often blocked from datacenter IPs."""
    url = f"https://www.reddit.com/r/{subreddit}/new.json"
    params = {"limit": limit, "raw_json": 1}
    headers = {
        "User-Agent": _USER_AGENTS[0],
        "Accept": "application/json",
    }

    # Try standard requests first
    data = _try_standard_requests(url, headers, params)
    if data and "data" in data and "children" in data["data"]:
        posts = data["data"]["children"]
        signals = []
        for child in posts[:limit]:
            sig = reddit_post_to_signal(child.get("data", {}), subreddit)
            if sig:
                signals.append(sig)
        if signals:
            return signals

    # Fall back to curl_cffi with Safari impersonation
    data = _try_cffi_with_warmup(url, params)
    if data and "data" in data and "children" in data["data"]:
        posts = data["data"]["children"]
        signals = []
        for child in posts[:limit]:
            sig = reddit_post_to_signal(child.get("data", {}), subreddit)
            if sig:
                signals.append(sig)
        if signals:
            return signals

    raise RuntimeError("JSON endpoint blocked (likely 403)")


# ============================================================
# UNIFIED PER-SUBREDDIT FETCH
# ============================================================

def fetch_subreddit_new(subreddit, limit=POSTS_PER_SUBREDDIT):
    """
    Fetch recent posts from a subreddit. Tries RSS first, falls back to JSON.
    Returns list of signals (may be empty if both methods fail).
    """
    # Try RSS first - works from datacenter IPs
    try:
        signals = _fetch_subreddit_via_rss(subreddit, limit)
        if signals:
            return signals
    except Exception as e:
        rss_err = str(e)
        print(f"   RSS failed for r/{subreddit}: {rss_err}")

    # Fall back to JSON
    try:
        signals = _fetch_subreddit_via_json(subreddit, limit)
        if signals:
            return signals
    except Exception as e:
        print(f"   JSON also failed for r/{subreddit}: {e}")

    return []


def reddit_post_to_signal(post, subreddit):
    """
    Convert a JSON post dict (from /new.json) into our signal format.
    Only used by the JSON fallback path.
    """
    if not post:
        return None
    try:
        title = post.get("title", "")
        body = post.get("selftext", "") or ""
        full_content = title
        if body and body != title:
            full_content = f"{title}\n\n{body[:1500]}"

        author = post.get("author", "unknown")
        handle = f"u/{author}" if author and not author.startswith("u/") else author

        created_utc = post.get("created_utc", 0)
        post_time_human = _humanize_time(
            datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
        ) if created_utc else "recently"

        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else ""

        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)

        return {
            "id": post.get("id", f"{subreddit}_{int(time.time())}"),
            "platform": "Reddit",
            "user_handle": handle,
            "user_profile": f"r/{subreddit} Reddit user",
            "post_time": post_time_human,
            "engagement": f"{score} upvotes, {num_comments} comments",
            "post_content": full_content,
            "_reddit_url": url,
            "_reddit_score": score,
            "_source_method": "json",
        }
    except Exception as e:
        print(f"   Signal conversion error: {e}")
        return None


# ============================================================
# MULTI-SUBREDDIT LIVE FETCH
# ============================================================

def fetch_live_reddit_signals(subreddits, posts_per_sub, max_total, progress_callback):
    """
    Fetch fresh posts across multiple subreddits.
    Returns list of signals. Reports progress via callback(msg) if provided.
    """
    all_signals = []
    seen_ids = set()
    rss_count = 0
    json_count = 0
    fail_count = 0

    for i, sub in enumerate(subreddits, 1):
        if progress_callback:
            progress_callback(f"  Fetching r/{sub} ({i}/{len(subreddits)})...")

        signals = fetch_subreddit_new(sub, limit=posts_per_sub)

        if not signals:
            fail_count += 1
            if progress_callback:
                progress_callback(f"     No posts from r/{sub}")
            continue

        # Track which method worked (for status reporting)
        method = signals[0].get("_source_method", "unknown")
        if method == "rss":
            rss_count += 1
        elif method == "json":
            json_count += 1

        # De-dup by id across subs
        new_added = 0
        for sig in signals:
            sid = sig.get("id")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                all_signals.append(sig)
                new_added += 1

        if progress_callback:
            progress_callback(f"     +{new_added} posts from r/{sub} ({method})")

        if len(all_signals) >= max_total:
            break

        # Polite spacing between subreddit hits
        time.sleep(0.3)

    if progress_callback:
        progress_callback(f"  Total: {len(all_signals)} posts | RSS: {rss_count} subs | JSON: {json_count} subs | Failed: {fail_count} subs")

    return all_signals[:max_total]


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def fetch_reddit_signals(subreddits=None, posts_per_sub=POSTS_PER_SUBREDDIT,
                         max_total=MAX_CACHE_POSTS, progress_callback=None,
                         force_fresh=False, inject_personas=False):
    """
    Get Reddit signals.

    Args:
      subreddits:       list of subreddit names (defaults to DEFAULT_SUBREDDITS)
      posts_per_sub:    per-subreddit fetch limit
      max_total:        cap on signals returned (also cap on cache size)
      progress_callback: optional fn(msg) for streaming progress
      force_fresh:      if True, attempt live fetch first; cache becomes fallback only
      inject_personas:  if True, hybrid mode - real posts used if persona handle
                        is in feed, simulated persona posts injected if not
    """
    if subreddits is None:
        subreddits = DEFAULT_SUBREDDITS
    if not progress_callback:
        progress_callback = lambda m: None

    cached_signals, cache_meta = load_cache()
    fetched_at = cache_meta.get("fetched_at")
    age_str = cache_age_human(fetched_at)

    if force_fresh:
        progress_callback(f"📡 Force-fresh mode: attempting live fetch...")
        live_signals = fetch_live_reddit_signals(subreddits, posts_per_sub, max_total, progress_callback)
        if live_signals:
            save_cache(live_signals, subreddits)
            progress_callback(f"✅ Fresh fetch successful: {len(live_signals)} signals saved to cache")
            return _filter_and_inject(live_signals, subreddits, max_total, inject_personas, progress_callback)
        elif cached_signals:
            progress_callback(f"⚠️ Live fetch returned nothing - falling back to cache ({age_str})")
            return _filter_and_inject(cached_signals, subreddits, max_total, inject_personas, progress_callback)
        else:
            progress_callback("❌ No live data and no cache available")
            return _filter_and_inject([], subreddits, max_total, inject_personas, progress_callback)

    # Default mode: use cache if fresh, else try live, else stale cache
    if cached_signals and fetched_at:
        try:
            fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - fetched_dt).total_seconds() / 3600
            if age_hours < CACHE_TTL_HOURS:
                progress_callback(f"📦 Using cached signals ({age_str}, {len(cached_signals)} posts)")
                return _filter_and_inject(cached_signals, subreddits, max_total, inject_personas, progress_callback)
            else:
                progress_callback(f"⚠️ Cache is stale ({age_str} - older than {CACHE_TTL_HOURS}h)")
        except (ValueError, TypeError):
            pass

    progress_callback("📡 Attempting live fetch...")
    live_signals = fetch_live_reddit_signals(subreddits, posts_per_sub, max_total, progress_callback)
    if live_signals:
        save_cache(live_signals, subreddits)
        progress_callback(f"✅ Live fetch successful: {len(live_signals)} signals")
        return _filter_and_inject(live_signals, subreddits, max_total, inject_personas, progress_callback)

    if cached_signals:
        progress_callback(f"⚠️ Live fetch failed - using stale cache ({age_str})")
        return _filter_and_inject(cached_signals, subreddits, max_total, inject_personas, progress_callback)

    progress_callback("❌ No Reddit data available (no cache, live fetch blocked)")
    return _filter_and_inject([], subreddits, max_total, inject_personas, progress_callback)


# ============================================================
# FILTER + PERSONA INJECTION
# ============================================================

def _filter_and_inject(signals, requested_subreddits, max_total, inject_personas, progress_callback):
    """
    Filter signals by requested subreddits AND optionally inject demo personas.
    Hybrid mode: persona's real post used if found in feed, simulated injected if not.
    """
    # Filter first
    if requested_subreddits:
        filtered = [s for s in signals
                    if any(f"r/{sub}" in s.get("user_profile", "") for sub in requested_subreddits)]
        result = filtered if filtered else signals
    else:
        result = signals

    # Inject personas if requested
    if inject_personas:
        try:
            from demo_personas import inject_personas_into_feed
            result, injection_log = inject_personas_into_feed(result, only_if_missing=True)
            for line in injection_log:
                progress_callback(f"   Persona: {line}")
        except ImportError as e:
            progress_callback(f"   demo_personas import failed: {e}")

    return result[:max_total]


def _filter_signals(signals, requested_subreddits, max_total):
    """Legacy alias for any external callers."""
    return _filter_and_inject(signals, requested_subreddits, max_total, False, lambda m: None)
