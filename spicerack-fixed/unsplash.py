"""
unsplash.py
Fetches recipe photos from Unsplash API.
Caches results to data/photo_cache.json so URLs persist across restarts.
Uses recipe title + top spices for more accurate photo matching.
Free tier: 50 requests/hour — cached URLs never hit the API again.

Fixes applied:
- Thread-safe cache access via threading.Lock (prevents "dictionary changed
  size during iteration" crash when Flask handles concurrent requests)
- Batched cache saves: disk is only written every SAVE_INTERVAL new fetches,
  not after every single API call
"""

import json
import os
import threading
import urllib.request
import urllib.parse

ACCESS_KEY = "n5oAXLrI1Jyo2dGik1PjYZZEvejVeY0z8s8oGBjhTL0"

BASE       = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE, "data", "photo_cache.json")

# Write to disk every N new API fetches (not every single one)
SAVE_INTERVAL = 10

_cache_lock    = threading.Lock()
_unsaved_count = 0


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    """Write cache to disk. Must be called while holding _cache_lock."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"[unsplash] could not save cache: {e}")


_cache = _load_cache()
print(f"[unsplash] loaded photo cache — {len(_cache)} cached photos")


def get_photo_url(recipe_title: str, spices: list = []) -> str:
    """
    Return a photo URL for the recipe title.
    Checks memory cache first — only hits the API if not cached.
    Thread-safe. Saves to disk every SAVE_INTERVAL new fetches.
    """
    global _unsaved_count

    # Fast path: already in cache
    with _cache_lock:
        if recipe_title in _cache:
            val = _cache[recipe_title]
            return "" if val == "NOT_FOUND" else val

    # Slow path: fetch from Unsplash
    try:
        spice_hint = " ".join(spices[:2]) if spices else ""
        search     = f"{recipe_title} {spice_hint} food recipe".strip()
        query      = urllib.parse.quote(search)
        url        = (f"https://api.unsplash.com/search/photos"
                      f"?query={query}&per_page=1&orientation=landscape")
        req = urllib.request.Request(url, headers={
            "Authorization":  f"Client-ID {ACCESS_KEY}",
            "Accept-Version": "v1",
            "User-Agent":     "SpiceRack/1.0"
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data      = json.loads(resp.read())
            results   = data.get("results", [])
            photo_url = results[0]["urls"]["regular"] if results else "NOT_FOUND"

    except Exception as e:
        print(f"[unsplash] error for '{recipe_title}': {e}")
        return ""

    # Store result and maybe flush to disk
    with _cache_lock:
        if recipe_title not in _cache:
            _cache[recipe_title] = photo_url
            _unsaved_count += 1
            if _unsaved_count >= SAVE_INTERVAL:
                _save_cache(_cache)
                _unsaved_count = 0

    return "" if photo_url == "NOT_FOUND" else photo_url


def flush_cache():
    """Force an immediate disk write — call on shutdown or after bulk fetches."""
    global _unsaved_count
    with _cache_lock:
        if _unsaved_count > 0:
            _save_cache(_cache)
            _unsaved_count = 0
