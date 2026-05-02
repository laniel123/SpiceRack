import json
import os
import threading
import time
import urllib.request
import urllib.parse

ACCESS_KEY = "n5oAXLrI1Jyo2dGik1PjYZZEvejVeY0z8s8oGBjhTL0"
BASE       = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE, "data", "photo_cache.json")
# NEW: Track usage across restarts
LIMIT_FILE = os.path.join(BASE, "data", "api_usage.json") 

HOURLY_LIMIT = 50
_cache_lock  = threading.Lock()

def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path) as f: return json.load(f)
        except: pass
    return {}

_cache = _load_json(CACHE_FILE)
_usage = _load_json(LIMIT_FILE)

# Initialize usage state
_api_count = _usage.get("count", 0)
_last_reset_time = _usage.get("reset_at", time.time())

def _save_usage():
    with open(LIMIT_FILE, "w") as f:
        json.dump({"count": _api_count, "reset_at": _last_reset_time}, f)

def get_photo_url(recipe_title: str, spices: list = [], force_cache_only: bool = False) -> str:
    global _api_count, _last_reset_time

    # 1. Immediate Cache Check
    with _cache_lock:
        if recipe_title in _cache:
            val = _cache[recipe_title]
            return "" if val == "NOT_FOUND" else val

    # 2. Check if we are allowed to hit the network
    if force_cache_only: return ""

    current_time = time.time()
    if current_time - _last_reset_time > 3600:
        _api_count = 0
        _last_reset_time = current_time
        _save_usage()

    if _api_count >= HOURLY_LIMIT:
        print(f"[unsplash] Hourly limit reached. Skipping network for: {recipe_title}")
        return "" 

    # 3. API Fetch
    photo_url = "NOT_FOUND"
    try:
        # Construct search... (same as your current logic)
        query = urllib.parse.quote(f"{recipe_title} food recipe")
        url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1"
        
        req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {ACCESS_KEY}"})
        _api_count += 1 # Increment before the call
        _save_usage()

        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            if data.get("results"):
                photo_url = data["results"][0]["urls"]["regular"]
    except Exception as e:
        print(f"[unsplash] API error: {e}")
        return ""

    # 4. Save result
    with _cache_lock:
        _cache[recipe_title] = photo_url
        with open(CACHE_FILE, "w") as f: json.dump(_cache, f)

    return "" if photo_url == "NOT_FOUND" else photo_url