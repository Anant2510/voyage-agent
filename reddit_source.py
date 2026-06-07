"""
Reddit Source - Live social listening with cache control.

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
from datetime import datetime, timezone

# curl_cffi as fallback for tricky networks
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

REDDIT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REDDIT_BASE_URL = "https://www.reddit.com"
REQUEST_TIMEOUT_SECONDS = 15
POSTS_PER_SUBREDDIT = 10
MAX_CACHE_POSTS = 500
CACHE_TTL_HOURS = 48
CACHE_FILE = "reddit_cache.json"

_warm_session = None


# ============================================================
# CACHE HANDLING
# ============================================================

def load_cache():
    """Load cached signals from disk. Returns (signals, metadata, age_hours)."""
    if not os.path.exists(CACHE_FILE):
        return None, None, None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        signals = cache.get("signals", [])
        if not signals:
            return None, None, None

        metadata = {
            "fetched_at": cache.get("fetched_at"),
            "fetched_at_human": cache.get("fetched_at_human"),
            "subreddits": cache.get("subreddits", []),
            "signal_count": cache.get("signal_count", len(signals)),
        }

        # Calculate age in hours
        age_hours = None
        if metadata["fetched_at"]:
            try:
                cached_dt = datetime.fromisoformat(metadata["fetched_at"].replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - cached_dt).total_seconds() / 3600
            except Exception:
                pass

        return signals, metadata, age_hours
    except (json.JSONDecodeError, IOError, KeyError) as e:
        print(f"   Cache load failed: {e}")
        return None, None, None


def save_cache(signals, subreddits):
    """Persist fetched signals to disk."""
    capped = signals[:MAX_CACHE_POSTS]
    cache = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetched_at_human": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subreddits": list(subreddits),
        "signal_count": len(capped),
        "signals": capped,
    }
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"   Cache save failed: {e}")
        return False


def cache_age_human(fetched_at_iso):
    if not fetched_at_iso:
        return "unknown"
    try:
        cached_dt = datetime.fromisoformat(fetched_at_iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - cached_dt
        seconds = delta.total_seconds()
        if seconds < 3600:
            return f"{int(seconds/60)} minutes ago"
        elif seconds < 86400:
            return f"{int(seconds/3600)} hours ago"
        elif seconds < 604800:
            return f"{int(seconds/86400)} days ago"
        else:
            return f"{int(seconds/604800)} weeks ago"
    except Exception:
        return "unknown"


def has_cache():
    signals, _, _ = load_cache()
    return signals is not None and len(signals) > 0


# ============================================================
# LIVE FETCH METHODS
# ============================================================

def _try_standard_requests(url, headers, params):
    r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    r.raise_for_status()
    text = r.text.lstrip()
    if not text.startswith("{") and not text.startswith("["):
        raise ValueError("Reddit returned HTML block page, not JSON")
    return r.json()


def _try_cffi_with_warmup(url, params):
    global _warm_session
    if not HAS_CFFI:
        raise RuntimeError("curl_cffi not installed")
    if _warm_session is None:
        _warm_session = cffi_requests.Session(impersonate="safari17_0")
        warm = _warm_session.get(REDDIT_BASE_URL + "/", timeout=REQUEST_TIMEOUT_SECONDS)
        if warm.status_code != 200:
            _warm_session = None
            raise RuntimeError(f"Session warmup failed: status {warm.status_code}")
        time.sleep(0.3)
    r = _warm_session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    r.raise_for_status()
    text = r.text.lstrip()
    if not text.startswith("{") and not text.startswith("["):
        raise ValueError("Reddit returned HTML block page, not JSON")
    return r.json()


def fetch_subreddit_new(subreddit, limit=POSTS_PER_SUBREDDIT):
    url = f"{REDDIT_BASE_URL}/r/{subreddit}/new.json"
    headers = {
        "User-Agent": REDDIT_USER_AGENT,
        "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    params = {"limit": limit, "raw_json": 1}

    methods = [
        ("standard requests", lambda: _try_standard_requests(url, headers, params)),
        ("curl_cffi warmup", lambda: _try_cffi_with_warmup(url, params)),
    ]

    last_error = None
    for method_name, method in methods:
        try:
            data = method()
            children = data.get("data", {}).get("children", [])
            return [child.get("data", {}) for child in children]
        except Exception as e:
            last_error = f"[{method_name}] {e}"
            continue
    print(f"   All methods failed for r/{subreddit}: {last_error}")
    return []


def reddit_post_to_signal(post, subreddit):
    title = post.get("title", "").strip()
    selftext = post.get("selftext", "").strip()
    content = title
    if selftext:
        content = f"{title}\n\n{selftext[:800]}"
    content = re.sub(r"http\S+", "[link]", content)

    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)
    engagement = f"{score} upvotes, {num_comments} comments"

    created_utc = post.get("created_utc", 0)
    if created_utc:
        post_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        delta = datetime.now(timezone.utc) - post_dt
        seconds = delta.total_seconds()
        if seconds < 3600:
            post_time = f"{int(seconds/60)} minutes ago"
        elif seconds < 86400:
            post_time = f"{int(seconds/3600)} hours ago"
        else:
            post_time = f"{int(seconds/86400)} days ago"
    else:
        post_time = "unknown"

    author = post.get("author", "[deleted]")
    return {
        "id": f"reddit_{post.get('id', 'unknown')}",
        "platform": "Reddit",
        "user_handle": f"u/{author}",
        "user_profile": f"r/{subreddit} Reddit user",
        "post_time": post_time,
        "engagement": engagement,
        "post_content": content,
        "_reddit_url": f"https://reddit.com{post.get('permalink', '')}",
        "_reddit_score": score,
    }


def fetch_live_reddit_signals(subreddits, posts_per_sub, max_total, progress_callback):
    all_signals = []
    successful_subs = []
    for i, sub in enumerate(subreddits, 1):
        progress_callback(f"Fetching r/{sub} ({i}/{len(subreddits)})...")
        posts = fetch_subreddit_new(sub, limit=posts_per_sub)
        if not posts:
            progress_callback(f"   No posts from r/{sub}")
            continue
        text_posts = [p for p in posts if (p.get("selftext") or p.get("title")) and not p.get("stickied", False)]
        signals = [reddit_post_to_signal(p, sub) for p in text_posts[:posts_per_sub]]
        all_signals.extend(signals)
        successful_subs.append(sub)
        progress_callback(f"   Got {len(signals)} posts from r/{sub}")
        if i < len(subreddits):
            time.sleep(1.0)
    all_signals.sort(key=lambda s: s.get("_reddit_score", 0), reverse=True)
    all_signals = all_signals[:max_total]
    progress_callback(f"Total fetched: {len(all_signals)} posts from {len(successful_subs)} subreddits")
    return all_signals, successful_subs


# ============================================================
# MAIN ENTRY — cache-aware with force_fresh flag
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

    Behavior:
      Default mode (force_fresh=False):
        1. If fresh cache (<48h) exists -> use it
        2. Else if stale cache exists -> use it but warn
        3. Else attempt live fetch
        4. Save to cache on successful live fetch

      Force-fresh mode (force_fresh=True):
        1. Attempt live fetch
        2. On success: save to cache + return
        3. On failure: fall back to cache (any age) with warning
    """
    if subreddits is None:
        subreddits = DEFAULT_SUBREDDITS
    if progress_callback is None:
        progress_callback = lambda msg: None

    cached_signals, metadata, age_hours = load_cache()
    cache_is_fresh = age_hours is not None and age_hours < CACHE_TTL_HOURS

    # ---- Mode 1: force_fresh — always try live first ----
    if force_fresh:
        progress_callback("Force-fresh mode: bypassing cache, fetching live from reddit.com...")
        try:
            live_signals, successful_subs = fetch_live_reddit_signals(
                subreddits, posts_per_sub, max_total, progress_callback
            )
            if live_signals:
                if save_cache(live_signals, successful_subs):
                    progress_callback(f"Saved {len(live_signals)} fresh posts to cache ({CACHE_FILE})")
                return _filter_and_inject(live_signals, subreddits, max_total, inject_personas, progress_callback)
            else:
                progress_callback("Live fetch returned 0 posts")
        except Exception as e:
            progress_callback(f"   Live fetch failed: {e}")

        # Fall back to cache if live fails
        if cached_signals:
            age_label = cache_age_human(metadata.get("fetched_at"))
            progress_callback(f"Falling back to cached posts (fetched {age_label})")
            if not cache_is_fresh:
                progress_callback(f"   WARNING: cache is older than {CACHE_TTL_HOURS}h - consider refreshing")
            return _filter_and_inject(cached_signals, subreddits, max_total, inject_personas, progress_callback)

        progress_callback("No cache available and live fetch failed. Returning empty.")
        return []

    # ---- Mode 2: default — cache-first ----
    if cached_signals:
        age_label = cache_age_human(metadata.get("fetched_at"))
        if cache_is_fresh:
            progress_callback(f"Loaded {len(cached_signals)} real Reddit posts from cache (fetched {age_label})")
        else:
            progress_callback(f"Loaded {len(cached_signals)} posts from STALE cache (fetched {age_label})")
            progress_callback(f"   WARNING: cache is older than {CACHE_TTL_HOURS}h. Toggle 'Force fresh fetch' to refresh.")
        progress_callback(f"   Subreddits in cache: {', '.join('r/' + s for s in metadata.get('subreddits', []))}")
        return _filter_and_inject(cached_signals, subreddits, max_total, inject_personas, progress_callback)

    # No cache — try live as last resort
    progress_callback("No cache found. Attempting live fetch from reddit.com...")
    try:
        live_signals, successful_subs = fetch_live_reddit_signals(
            subreddits, posts_per_sub, max_total, progress_callback
        )
        if live_signals:
            if save_cache(live_signals, successful_subs):
                progress_callback(f"Saved {len(live_signals)} posts to cache ({CACHE_FILE})")
            return _filter_and_inject(live_signals, subreddits, max_total, inject_personas, progress_callback)
    except Exception as e:
        progress_callback(f"   Live fetch failed: {e}")

    progress_callback("Could not load Reddit posts (no cache, no network).")
    progress_callback("   Run python fetch_reddit_cache.py from a network where reddit.com is reachable.")
    return []


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


# Legacy alias for any external callers
def _filter_signals(signals, requested_subreddits, max_total):
    return _filter_and_inject(signals, requested_subreddits, max_total, False, lambda m: None)


# ============================================================
# DIAGNOSTIC
# ============================================================

if __name__ == "__main__":
    print("Testing Reddit source...")
    print()
    signals, meta, age_h = load_cache()
    if signals:
        print(f"Cache found: {len(signals)} posts")
        print(f"  Age: {age_h:.1f} hours" if age_h else "  Age: unknown")
        print(f"  Fresh: {'yes' if age_h and age_h < CACHE_TTL_HOURS else 'STALE'}")
        print()
        for s in signals[:3]:
            print(f"  [{s['user_handle']}] {s['post_content'][:100]}...")
    else:
        print("No cache file found.")
        print("Run: python fetch_reddit_cache.py")
