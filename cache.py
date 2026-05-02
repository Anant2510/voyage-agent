"""
Simple file-based cache for tool results.
Persists between runs, auto-expires after TTL.
"""

import json
import os
import hashlib
from datetime import datetime, timedelta

# ============================================================
# CONFIGURATION
# ============================================================

CACHE_DIR = ".cache"
DEFAULT_TTL_HOURS = 2  # 2 hours as requested

# Per-tool TTL overrides (some data changes faster than others)
TOOL_TTL_OVERRIDES = {
    "search_flights": 2,      # Flight prices change, but 2hrs is fine for demos
    "search_hotels": 2,        # Hotel availability is fairly stable
    "check_weather": 6,        # Weather forecasts don't change much hourly
    "create_booking": 0,       # NEVER cache bookings (always fresh)
}


# ============================================================
# CACHE OPERATIONS
# ============================================================

def _ensure_cache_dir():
    """Create cache directory if it doesn't exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _generate_cache_key(tool_name, tool_input):
    """
    Generate a unique, deterministic cache key from tool name + inputs.
    Same inputs always produce the same key.
    """
    # Sort keys for deterministic hashing (input order doesn't matter)
    normalized_input = json.dumps(tool_input, sort_keys=True)
    combined = f"{tool_name}::{normalized_input}"
    hash_str = hashlib.md5(combined.encode()).hexdigest()
    return f"{tool_name}_{hash_str}"


def _get_ttl_for_tool(tool_name):
    """Get the TTL in hours for a specific tool."""
    return TOOL_TTL_OVERRIDES.get(tool_name, DEFAULT_TTL_HOURS)


def get_cached(tool_name, tool_input):
    """
    Retrieve a cached result if it exists and is still valid.
    Returns None if cache miss or expired.
    """
    _ensure_cache_dir()
    
    # Don't cache certain tools (like bookings)
    ttl_hours = _get_ttl_for_tool(tool_name)
    if ttl_hours == 0:
        return None
    
    key = _generate_cache_key(tool_name, tool_input)
    cache_file = os.path.join(CACHE_DIR, f"{key}.json")
    
    if not os.path.exists(cache_file):
        return None
    
    try:
        with open(cache_file, "r") as f:
            cached = json.load(f)
        
        # Check if cache has expired
        cached_time = datetime.fromisoformat(cached["timestamp"])
        age = datetime.now() - cached_time
        
        if age > timedelta(hours=ttl_hours):
            # Cache expired - delete and return None
            os.remove(cache_file)
            return None
        
        return cached["data"]
    
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # Corrupted cache - delete and return None
        try:
            os.remove(cache_file)
        except:
            pass
        return None


def set_cached(tool_name, tool_input, data):
    """
    Save a tool result to the cache.
    Skips caching for tools with TTL=0 (like bookings).
    """
    _ensure_cache_dir()
    
    # Don't cache certain tools
    ttl_hours = _get_ttl_for_tool(tool_name)
    if ttl_hours == 0:
        return False
    
    key = _generate_cache_key(tool_name, tool_input)
    cache_file = os.path.join(CACHE_DIR, f"{key}.json")
    
    try:
        with open(cache_file, "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "tool_name": tool_name,
                "tool_input": tool_input,
                "data": data
            }, f, indent=2)
        return True
    except Exception as e:
        print(f"   ⚠️  Cache write failed: {e}")
        return False


def clear_cache():
    """Delete all cached entries. Useful for fresh demos."""
    _ensure_cache_dir()
    
    count = 0
    for filename in os.listdir(CACHE_DIR):
        if filename.endswith(".json"):
            try:
                os.remove(os.path.join(CACHE_DIR, filename))
                count += 1
            except:
                pass
    
    return count


def cache_stats():
    """Get statistics about the current cache."""
    _ensure_cache_dir()
    
    total_files = 0
    total_size_bytes = 0
    by_tool = {}
    expired = 0
    
    for filename in os.listdir(CACHE_DIR):
        if not filename.endswith(".json"):
            continue
        
        filepath = os.path.join(CACHE_DIR, filename)
        try:
            total_files += 1
            total_size_bytes += os.path.getsize(filepath)
            
            with open(filepath, "r") as f:
                cached = json.load(f)
            
            tool_name = cached.get("tool_name", "unknown")
            by_tool[tool_name] = by_tool.get(tool_name, 0) + 1
            
            # Check if expired
            cached_time = datetime.fromisoformat(cached["timestamp"])
            ttl = _get_ttl_for_tool(tool_name)
            if datetime.now() - cached_time > timedelta(hours=ttl):
                expired += 1
        except:
            pass
    
    return {
        "total_entries": total_files,
        "total_size_kb": round(total_size_bytes / 1024, 2),
        "by_tool": by_tool,
        "expired_entries": expired
    }
