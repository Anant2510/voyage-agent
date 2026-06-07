"""
Reddit Connection Probe
=======================

Tries every known method of accessing Reddit's public data and reports
which one (if any) works on your current network.

This is a diagnostic tool — run it whenever Reddit fetching fails to
identify a path that works.

Usage:
    python probe_reddit.py
"""

import sys
import time

# Try importing curl_cffi
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False
    print("⚠️  curl_cffi not installed. Some tests will be skipped.")
    print("   Install with: pip install curl_cffi")
    print()

import requests as std_requests


BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TEST_SUBREDDIT = "travel"


def show_result(name, success, status, snippet, error=None):
    """Print test result in a readable format."""
    icon = "✅" if success else "❌"
    print(f"{icon} {name}")
    if error:
        print(f"   Error: {error}")
    else:
        print(f"   Status: {status}")
        if snippet:
            # Detect if it's JSON or HTML
            is_json = snippet.lstrip().startswith("{") or snippet.lstrip().startswith("[")
            label = "JSON ✓" if is_json else "HTML (likely block page) ✗"
            print(f"   Content: {label}")
            print(f"   First 80 chars: {snippet[:80]}")
    print()


def test_std_requests_json():
    """Test 1: Plain requests library, JSON endpoint."""
    name = "1. Standard requests → www.reddit.com/.json"
    try:
        r = std_requests.get(
            f"https://www.reddit.com/r/{TEST_SUBREDDIT}/new.json?limit=2",
            headers={"User-Agent": BROWSER_UA},
            timeout=10
        )
        is_json = r.text.lstrip().startswith("{")
        show_result(name, r.status_code == 200 and is_json, r.status_code, r.text)
        return r.status_code == 200 and is_json
    except Exception as e:
        show_result(name, False, "?", "", str(e))
        return False


def test_cffi_chrome131():
    """Test 2: curl_cffi with Chrome 131 impersonation."""
    name = "2. curl_cffi (chrome131) → www.reddit.com/.json"
    if not HAS_CFFI:
        show_result(name, False, "?", "", "curl_cffi not installed")
        return False
    try:
        r = cffi_requests.get(
            f"https://www.reddit.com/r/{TEST_SUBREDDIT}/new.json?limit=2",
            impersonate="chrome131",
            timeout=10
        )
        is_json = r.text.lstrip().startswith("{")
        show_result(name, r.status_code == 200 and is_json, r.status_code, r.text)
        return r.status_code == 200 and is_json
    except Exception as e:
        show_result(name, False, "?", "", str(e))
        return False


def test_cffi_safari():
    """Test 3: curl_cffi with Safari impersonation."""
    name = "3. curl_cffi (safari17_0) → www.reddit.com/.json"
    if not HAS_CFFI:
        show_result(name, False, "?", "", "curl_cffi not installed")
        return False
    try:
        r = cffi_requests.get(
            f"https://www.reddit.com/r/{TEST_SUBREDDIT}/new.json?limit=2",
            impersonate="safari17_0",
            timeout=10
        )
        is_json = r.text.lstrip().startswith("{")
        show_result(name, r.status_code == 200 and is_json, r.status_code, r.text)
        return r.status_code == 200 and is_json
    except Exception as e:
        show_result(name, False, "?", "", str(e))
        return False


def test_cffi_session_warmup():
    """Test 4: curl_cffi with session warmup (visit homepage first, then JSON)."""
    name = "4. curl_cffi session warmup → homepage → JSON"
    if not HAS_CFFI:
        show_result(name, False, "?", "", "curl_cffi not installed")
        return False
    try:
        session = cffi_requests.Session(impersonate="chrome131")

        # Step 1: warm up by visiting the homepage (like a browser would)
        warm = session.get("https://www.reddit.com/", timeout=10)
        if warm.status_code != 200:
            show_result(name, False, warm.status_code, warm.text, "Warmup failed")
            return False

        time.sleep(0.5)

        # Step 2: now request the JSON
        r = session.get(
            f"https://www.reddit.com/r/{TEST_SUBREDDIT}/new.json?limit=2",
            timeout=10
        )
        is_json = r.text.lstrip().startswith("{")
        show_result(name, r.status_code == 200 and is_json, r.status_code, r.text)
        return r.status_code == 200 and is_json
    except Exception as e:
        show_result(name, False, "?", "", str(e))
        return False


def test_rss_endpoint():
    """Test 5: RSS endpoint (often less protected than JSON)."""
    name = "5. curl_cffi → reddit.com/.rss (RSS feed)"
    if not HAS_CFFI:
        # try with standard requests
        try:
            r = std_requests.get(
                f"https://www.reddit.com/r/{TEST_SUBREDDIT}/new.rss?limit=2",
                headers={"User-Agent": BROWSER_UA},
                timeout=10
            )
            is_rss = "<rss" in r.text[:500] or "<feed" in r.text[:500]
            show_result(name + " (std requests)", r.status_code == 200 and is_rss, r.status_code, r.text)
            return r.status_code == 200 and is_rss
        except Exception as e:
            show_result(name, False, "?", "", str(e))
            return False
    try:
        r = cffi_requests.get(
            f"https://www.reddit.com/r/{TEST_SUBREDDIT}/new.rss?limit=2",
            impersonate="chrome131",
            timeout=10
        )
        is_rss = "<rss" in r.text[:500] or "<feed" in r.text[:500]
        show_result(name, r.status_code == 200 and is_rss, r.status_code, r.text)
        return r.status_code == 200 and is_rss
    except Exception as e:
        show_result(name, False, "?", "", str(e))
        return False


def test_old_reddit():
    """Test 6: old.reddit.com (uses different infrastructure)."""
    name = "6. curl_cffi → old.reddit.com/.json"
    if not HAS_CFFI:
        show_result(name, False, "?", "", "curl_cffi not installed")
        return False
    try:
        r = cffi_requests.get(
            f"https://old.reddit.com/r/{TEST_SUBREDDIT}/new.json?limit=2",
            impersonate="chrome131",
            timeout=10
        )
        is_json = r.text.lstrip().startswith("{")
        show_result(name, r.status_code == 200 and is_json, r.status_code, r.text)
        return r.status_code == 200 and is_json
    except Exception as e:
        show_result(name, False, "?", "", str(e))
        return False


def main():
    print("=" * 70)
    print("  Reddit Connection Probe")
    print("=" * 70)
    print()
    print(f"Testing access to r/{TEST_SUBREDDIT}")
    print(f"curl_cffi available: {HAS_CFFI}")
    print()
    print("-" * 70)
    print()

    results = []
    results.append(("Standard requests", test_std_requests_json()))
    results.append(("curl_cffi chrome131", test_cffi_chrome131()))
    results.append(("curl_cffi safari17_0", test_cffi_safari()))
    results.append(("curl_cffi session warmup", test_cffi_session_warmup()))
    results.append(("RSS endpoint", test_rss_endpoint()))
    results.append(("old.reddit.com", test_old_reddit()))

    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    for name, success in results:
        icon = "✅" if success else "❌"
        print(f"  {icon} {name}")
    print()

    working = [name for name, success in results if success]
    if working:
        print(f"✅ {len(working)} method(s) work on your network:")
        for name in working:
            print(f"     - {name}")
        print()
        print("Next step: I'll update reddit_source.py to use the working method.")
    else:
        print("❌ No methods work. Your network blocks Reddit entirely.")
        print()
        print("Options:")
        print("  - Switch to phone hotspot (mobile data)")
        print("  - Use home WiFi")
        print("  - Skip live Reddit integration")


if __name__ == "__main__":
    main()
