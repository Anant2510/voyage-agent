"""
Pre-fetch Reddit Cache for Demo Use
====================================

Run this from a network where reddit.com is reachable to populate
reddit_cache.json with real posts. The demo app loads from this cache.

Usage:
    python fetch_reddit_cache.py

Refresh whenever you want fresher data. Cache holds up to 500 posts.
"""

import json
import os
import sys
from datetime import datetime, timezone

from reddit_source import (
    fetch_live_reddit_signals,
    save_cache,
    DEFAULT_SUBREDDITS,
    MAX_CACHE_POSTS,
    CACHE_FILE,
)


def main():
    print("=" * 60)
    print("  Voyage Concierge - Reddit Cache Fetcher")
    print("=" * 60)
    print()
    print(f"Will fetch posts from {len(DEFAULT_SUBREDDITS)} subreddits:")
    for sub in DEFAULT_SUBREDDITS:
        print(f"  - r/{sub}")
    print()
    print(f"Cache cap: {MAX_CACHE_POSTS} posts maximum")
    print("Fetching... (this may take 20-30 seconds)")
    print()

    def progress(msg):
        print(f"  {msg}")

    try:
        signals, successful_subs = fetch_live_reddit_signals(
            subreddits=DEFAULT_SUBREDDITS,
            posts_per_sub=15,
            max_total=MAX_CACHE_POSTS,
            progress_callback=progress
        )
    except Exception as e:
        print()
        print(f"Fetch failed: {e}")
        print()
        print("This likely means your network blocks reddit.com.")
        print("Try home WiFi or your phone hotspot.")
        sys.exit(1)

    if not signals:
        print()
        print("Got 0 posts. Try a different network.")
        sys.exit(1)

    if save_cache(signals, successful_subs):
        print()
        print("=" * 60)
        print(f"  Saved {len(signals)} posts to {CACHE_FILE}")
        print("=" * 60)
        print()
        print("Sample of cached posts:")
        print()
        for i, signal in enumerate(signals[:5], 1):
            title = signal["post_content"].split("\n")[0][:80]
            print(f"  {i}. [{signal['user_handle']}] {title}...")
            print(f"     {signal['engagement']} - {signal['post_time']}")
            print()

        print(f"File size: {os.path.getsize(CACHE_FILE):,} bytes")
        print()
        print("Next steps:")
        print("  1. Optional: commit reddit_cache.json to your repo")
        print("  2. Run the demo app - it will auto-load from this cache")
        print("  3. Cache TTL: 48 hours (after that, app will warn and suggest refresh)")
    else:
        print("Failed to save cache file.")
        sys.exit(1)


if __name__ == "__main__":
    main()
