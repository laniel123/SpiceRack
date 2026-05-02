import json
import os
import threading
import time
import urllib.request
import urllib.parse

ACCESS_KEY = "n5oAXLrI1Jyo2dGik1PjYZZEvejVeY0z8s8oGBjhTL0"
BASE       = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE, "data", "photo_cache.json")
SAVE_INTERVAL = 10

# Rate Limiting Settings
HOURLY_LIMIT = 50
_api_count = 0
_last_reset_time = time.time()

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
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"[unsplash] could not save cache: {e}")

_cache = _load_cache()

def get_photo_url(recipe_title: str, spices: list = []) -> str:
    global _unsaved_count, _api_count, _last_reset_time

    # 1. Check Memory Cache (Handles both valid URLs and "NOT_FOUND")
    with _cache_lock:
        if recipe_title in _cache:
            val = _cache[recipe_title]
            return "" if val == "NOT_FOUND" else val

    # 2. Check Hourly Rate Limit
    current_time = time.time()
    if current_time - _last_reset_time > 3600:
        _api_count = 0
        _last_reset_time = current_time

    if _api_count >= HOURLY_LIMIT:
        return "" # Silently stop querying if over limit to preserve speed

    # 3. Fetch from Unsplash
    photo_url = "NOT_FOUND" # Default to negative result
    try:
        _api_count += 1
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
        
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            if results:
                photo_url = results[0]["urls"]["regular"]

    except Exception as e:
        print(f"[unsplash] API error for '{recipe_title}': {e}")
        # Note: We don't cache as NOT_FOUND on network errors, 
        # only when the API explicitly returns 0 results.
        return ""

    # 4. Update Cache (Always stores, even if "NOT_FOUND")
    with _cache_lock:
        _cache[recipe_title] = photo_url
        _unsaved_count += 1
        if _unsaved_count >= SAVE_INTERVAL:
            _save_cache(_cache)
            _unsaved_count = 0

    return "" if photo_url == "NOT_FOUND" else photo_url