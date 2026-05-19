"""
unsplash.py
───────────────────────────────────────────────────────────────────────────────
Fetches recipe photos from the Unsplash API.
  • Caches URLs to data/photo_cache.json so hits never repeat across restarts
  • Tracks API usage in data/api_usage.json (50 req/hour free tier)
  • Auto-resets the hourly counter on startup if the window has expired
  • Thread-safe via a single lock — safe under Flask's threaded server
  • Batched disk writes (every 10 new fetches) — no per-request I/O blocking

Usage:
    from unsplash import get_photo_url
    url = get_photo_url("Spicy Thai Basil Chicken", ["basil", "chili"])
"""

import json
import os
import threading
import time
import urllib.request
import urllib.parse

# ── Config ────────────────────────────────────────────────────────────────────

ACCESS_KEY   = "n5oAXLrI1Jyo2dGik1PjYZZEvejVeY0z8s8oGBjhTL0"
BASE         = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE   = os.path.join(BASE, "data", "photo_cache.json")
LIMIT_FILE   = os.path.join(BASE, "data", "api_usage.json")

HOURLY_LIMIT  = 50    # Unsplash free tier
SAVE_INTERVAL = 10    # write cache to disk every N new fetches

# ── Internals ─────────────────────────────────────────────────────────────────

_cache_lock    = threading.Lock()
_unsaved_count = 0


def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    """Write photo cache to disk. Call while holding _cache_lock."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"[unsplash] could not save cache: {e}")


def _save_usage():
    try:
        os.makedirs(os.path.dirname(LIMIT_FILE), exist_ok=True)
        with open(LIMIT_FILE, "w") as f:
            json.dump({"count": _api_count, "reset_at": _last_reset_time}, f)
    except Exception as e:
        print(f"[unsplash] could not save usage: {e}")


# ── Initialise ────────────────────────────────────────────────────────────────

_cache = _load_json(CACHE_FILE)
_usage = _load_json(LIMIT_FILE)

# Auto-reset the hourly counter on startup if the window has expired
_saved_reset = _usage.get("reset_at", 0)

if time.time() - _saved_reset > 3600:
    # More than an hour since last reset — start fresh
    _api_count       = 0
    _last_reset_time = time.time()
    _save_usage()
    print(f"[unsplash] loaded photo cache — {len(_cache)} cached photos "
          f"(hourly limit reset)")
else:
    # Still within the same hour — restore saved count
    _api_count       = _usage.get("count", 0)
    _last_reset_time = _saved_reset
    remaining        = HOURLY_LIMIT - _api_count
    print(f"[unsplash] loaded photo cache — {len(_cache)} cached photos "
          f"({_api_count}/{HOURLY_LIMIT} used this hour, {remaining} remaining)")


# ── Public API ────────────────────────────────────────────────────────────────

def get_photo_url(recipe_title: str,
                  spices: list = [],
                  force_cache_only: bool = False) -> str:
    """
    Return a photo URL for the recipe title.

    Args:
        recipe_title:     Recipe name used as the search query.
        spices:           Optional spice list — top 2 added to query for
                          better image relevance.
        force_cache_only: If True, never hit the network (used on initial
                          page load to avoid exhausting the rate limit).

    Returns:
        A URL string, or "" if no image is available.
    """
    global _api_count, _last_reset_time, _unsaved_count

    # ── Fast path: already cached ─────────────────────────────────────────────
    with _cache_lock:
        if recipe_title in _cache:
            val = _cache[recipe_title]
            return "" if val == "NOT_FOUND" else val

    # ── Skip network if caller asked for cache-only ───────────────────────────
    if force_cache_only:
        return ""

    # ── Hourly rate-limit check ───────────────────────────────────────────────
    current_time = time.time()
    if current_time - _last_reset_time > 3600:
        _api_count       = 0
        _last_reset_time = current_time
        _save_usage()

    if _api_count >= HOURLY_LIMIT:
        print(f"[unsplash] hourly limit reached — skipping: {recipe_title}")
        return ""

    # ── Fetch from Unsplash ───────────────────────────────────────────────────
    photo_url = "NOT_FOUND"
    try:
        spice_hint = " ".join(spices[:2]) if spices else ""
        search     = f"{recipe_title} {spice_hint} food recipe".strip()
        query      = urllib.parse.quote(search)
        url        = (f"https://api.unsplash.com/search/photos"
                      f"?query={query}&per_page=1&orientation=landscape")

        req = urllib.request.Request(url, headers={
            "Authorization":  f"Client-ID {ACCESS_KEY}",
            "Accept-Version": "v1",
            "User-Agent":     "SpiceRack/1.0",
        })

        # Count the request before sending so we never go over limit
        # even if multiple threads hit here simultaneously
        _api_count += 1
        _save_usage()

        with urllib.request.urlopen(req, timeout=5) as resp:
            data    = json.loads(resp.read())
            results = data.get("results", [])
            if results:
                photo_url = results[0]["urls"]["regular"]

    except Exception as e:
        print(f"[unsplash] error for '{recipe_title}': {e}")
        # Don't cache the failure — let it retry next time
        return ""

    # ── Store in cache ────────────────────────────────────────────────────────
    with _cache_lock:
        # Double-check: another thread may have fetched the same title
        if recipe_title not in _cache:
            _cache[recipe_title] = photo_url
            _unsaved_count += 1
            if _unsaved_count >= SAVE_INTERVAL:
                _save_cache(_cache)
                _unsaved_count = 0

    return "" if photo_url == "NOT_FOUND" else photo_url


def flush_cache():
    """
    Force an immediate disk write of any unsaved cache entries.
    Call this on app shutdown or after a bulk prefetch.
    """
    global _unsaved_count
    with _cache_lock:
        if _unsaved_count > 0:
            _save_cache(_cache)
            _unsaved_count = 0