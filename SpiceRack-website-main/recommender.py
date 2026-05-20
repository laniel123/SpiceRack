"""
recommender.py - SpiceRack v5
=============================================================

Two recommendation layers:

  1. Content-based (geometry-corrected):
       pantry -> binary -> TF-IDF -> IDF boost -> zero universals
       -> SVD -> normalize -> K-Means cluster search -> cosine sim

  2. Implicit feedback personalization (NEW):
       Saved recipes in saved_recipes.db tell us which clusters
       the user gravitates toward. Those clusters get a distance
       bonus so they rank higher in the top-cluster search.
       This is "implicit feedback" from your lecture slides -
       listening patterns / browsing behaviour, applied to cooking.
       Zero model retraining required.

Built for model keys (v5):
  kmeans, svd, mlb, tfidf, idf_boost, exclude_idx,
  recipe_matrix, recipe_titles, recipe_spices,
  cluster_labels, cluster_top_spices, n_clusters, n_recipes, silhouette
"""

import os
import re
import ast
import sqlite3
import joblib
import numpy as np
import pandas as pd
from collections import Counter
from sklearn.preprocessing import normalize
from scipy.sparse import csr_matrix

BASE       = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE, "spicerack_model_v5.joblib")
CSV_PATH   = os.path.join(BASE, "data", "full_recipes_with_restrictions.csv")
DB_PATH    = os.path.join(BASE, "data", "saved_recipes.db")

DIET_COLS = [
    'is_vegetarian', 'is_vegan', 'is_dairy_free', 'is_gluten_free',
    'is_keto', 'is_paleo', 'is_halal', 'is_kosher', 'is_hindu_friendly',
]

_model     = None
_recipe_df = None
TOP_CLUSTERS = 7

# Precomputed at load() time
_diet_masks    = {}
_course_arr    = None
_norm_titles   = None
_lower_titles  = None
_recipe_lookup = None
_suggest_cache = {}

# Personalization config
# SAVE_BOOST: distance reduction per saved recipe in a cluster (10% per save)
# SAVE_BOOST_CAP: maximum total reduction for any cluster (40% max)
SAVE_BOOST     = 0.10
SAVE_BOOST_CAP = 0.40

_DESSERT_KEYWORDS = {
    "cake", "cookie", "cookies", "pie", "tart", "brownie", "brownies",
    "pudding", "custard", "mousse", "cheesecake", "cupcake", "cupcakes",
    "muffin", "muffins", "donut", "donuts", "doughnut", "fudge", "candy",
    "truffle", "truffles", "macaroon", "macarons", "eclair", "cream puff",
    "ice cream", "sorbet", "gelato", "parfait", "cobbler", "crisp",
    "shortbread", "biscotti", "tiramisu", "baklava", "crepe", "crepes",
    "waffle", "waffles", "pancake", "pancakes", "sweet roll", "cinnamon roll",
    "dessert", "sweet", "sweets", "chocolate", "candy bar", "lollipop",
    "meringue", "praline", "caramel", "butterscotch", "toffee", "nougat",
    "brittle", "bark", "popsicle", "smoothie bowl", "fruit salad",
}

_MAINS_KEYWORDS = {
    "chicken", "beef", "pork", "lamb", "turkey", "salmon", "tuna", "shrimp",
    "pasta", "spaghetti", "lasagna", "fettuccine", "penne", "rigatoni",
    "rice", "risotto", "pilaf", "fried rice", "stir fry", "stir-fry",
    "soup", "stew", "chili", "chilli", "curry", "casserole", "roast",
    "burger", "sandwich", "wrap", "taco", "burrito", "enchilada", "quesadilla",
    "pizza", "quiche", "frittata", "omelette", "omelet", "steak", "meatball",
    "meatloaf", "pot pie", "pot roast", "brisket", "ribs", "wings",
    "salad", "grain bowl", "bowl", "bake", "baked", "grilled", "roasted",
    "braised", "sauteed", "sauted", "pan-fried", "deep-fried", "poached",
    "side dish", "stuffing", "dressing", "mashed", "potatoes", "coleslaw",
    "noodle", "noodles", "ramen", "udon", "soba", "pho", "gumbo", "jambalaya",
    "paella", "biryani", "tagine", "moussaka", "shakshuka", "fajita",
    "fish", "seafood", "crab", "lobster", "scallop", "clam", "mussel",
}


def _classify_course(title) -> str:
    if not isinstance(title, str):
        return "Other/Miscellaneous"
    t = title.lower()
    words = set(t.replace("-", " ").split())
    for kw in _DESSERT_KEYWORDS:
        if kw in t:
            return "Dessert & Sweets"
    for kw in _MAINS_KEYWORDS:
        if kw in t or kw in words:
            return "Mains & Sides"
    return "Other/Miscellaneous"


def _precompute(model, df):
    global _diet_masks, _course_arr, _norm_titles, _lower_titles, _recipe_lookup

    _norm_titles = pd.Series([
        t.strip().lower() if isinstance(t, str) else ''
        for t in model['recipe_titles']
    ])

    title_lower = df['title'].str.strip().str.lower()
    agg_spec = {c: 'min' for c in DIET_COLS if c in df.columns}
    agg_spec['course_category'] = 'first'
    grouped = df.groupby(title_lower).agg(agg_spec)

    for col in DIET_COLS:
        if col in grouped.columns:
            lookup = grouped[col].to_dict()
            _diet_masks[col] = (
                _norm_titles.map(lookup)
                .fillna(False)
                .astype(bool)
                .values
            )

    course_lookup = grouped['course_category'].to_dict()
    _course_arr = _norm_titles.map(course_lookup).fillna('').values
    _lower_titles = df['title'].str.lower().fillna('').values

    dedup = df.drop_duplicates(subset='title', keep='first')
    _recipe_lookup = dict(zip(dedup['title'].str.strip(), dedup.itertuples(index=False)))

    print("[recommender] precomputation done")


def load():
    global _model, _recipe_df
    if _model is None and os.path.exists(MODEL_PATH):
        _model = joblib.load(MODEL_PATH)
        print(f"[recommender] loaded - {_model['n_recipes']:,} recipes, "
              f"{_model['n_clusters']} clusters, "
              f"silhouette {_model.get('silhouette', '?')}")

    if _recipe_df is None and os.path.exists(CSV_PATH):
        _recipe_df = pd.read_csv(CSV_PATH)
        print(f"[recommender] recipe data - {len(_recipe_df):,} rows")
        if "course_category" not in _recipe_df.columns or _recipe_df["course_category"].isna().all():
            print("[recommender] classifying course categories...")
            _recipe_df["course_category"] = _recipe_df["title"].apply(_classify_course)
        if _model is not None:
            _precompute(_model, _recipe_df)

    return _model


# ── User vector (v5 geometry-corrected) ──────────────────────────────────────
#
# Pylance flags .multiply() on the result of tfidf.transform() because the
# return type is annotated as a generic sparse matrix base class, which does
# not expose .multiply() in the stub. The fix is to explicitly cast to
# csr_matrix after each transform step so Pylance knows the concrete type.
#
# This is NOT a logic change - csr_matrix(x) on an already-csr matrix is
# a zero-copy no-op. It is purely a type annotation hint for the linter.

def _user_vector(pantry: list, model) -> np.ndarray:
    """
    pantry -> binary -> TF-IDF -> IDF boost -> SVD -> normalize

    Universals (salt, garlic, black pepper) are KEPT here.
    This matches X_svd_score — the scoring matrix in v5.1.
    K-Means cluster search uses the same vector: the SVD projection
    is shared between train and score matrices so distances are valid.

    Note: exclude_idx is stored in the model but intentionally not applied
    at inference. Applying it here would cause the same zero-vector collapse
    that created the 35k catch-all cluster in v5.0.
    """
    user_bin = np.asarray(
        model["mlb"].transform([set(pantry)]), dtype=np.float32
    )
    user_tfidf:   csr_matrix = csr_matrix(
        model["tfidf"].transform(csr_matrix(user_bin))
    )
    user_boosted: csr_matrix = csr_matrix(
        user_tfidf.multiply(model["idf_boost"])
    )
    user_boosted = normalize(user_boosted, norm="l2")
    user_svd     = model["svd"].transform(user_boosted)
    user_svd     = normalize(user_svd, norm="l2")
    return user_svd[0]


# ── Implicit feedback: saved recipe cluster weights ───────────────────────────

def _get_saved_cluster_counts(model, db_path: str = DB_PATH) -> dict:
    """
    Read saved recipe titles from SQLite, find which cluster each belongs to,
    return {cluster_id: save_count}.

    This is the implicit feedback signal. More saves in a cluster means a
    stronger pull toward that cluster during the next recommendation request.
    Returns empty dict if DB is missing, empty, or the query fails.
    """
    if not os.path.exists(db_path):
        return {}
    try:
        conn  = sqlite3.connect(db_path)
        cur   = conn.cursor()
        cur.execute("SELECT title FROM saved_recipes")
        saved_titles = {row[0].strip() for row in cur.fetchall()}
        conn.close()
    except Exception as e:
        print(f"[recommender] DB read failed: {e}")
        return {}

    if not saved_titles:
        return {}

    cluster_counts: Counter = Counter()
    title_to_cluster = dict(zip(model["recipe_titles"], model["cluster_labels"]))

    for title in saved_titles:
        cid = title_to_cluster.get(title)
        if cid is not None:
            cluster_counts[int(cid)] += 1

    return dict(cluster_counts)


def _apply_save_boost(distances: np.ndarray, cluster_counts: dict) -> np.ndarray:
    """
    Reduce distances for clusters the user has saved recipes in.
    Lower distance = ranked higher in top-cluster search.

    Formula: new_dist = dist * (1 - min(n_saves * SAVE_BOOST, SAVE_BOOST_CAP))

    With defaults (SAVE_BOOST=0.10, SAVE_BOOST_CAP=0.40):
      1 save  -> 10% closer
      3 saves -> 30% closer
      5 saves -> 40% closer (capped)
    """
    if not cluster_counts:
        return distances

    boosted = distances.copy()
    for cid, count in cluster_counts.items():
        if cid < len(boosted):
            reduction = min(count * SAVE_BOOST, SAVE_BOOST_CAP)
            boosted[cid] = boosted[cid] * (1.0 - reduction)
    return boosted


def _nearest_clusters(pantry: list, model, db_path: str = DB_PATH) -> list:
    """
    Return top N nearest cluster IDs, adjusted by save history.

    Without saves: pure content-based cluster ranking.
    With saves:    saved clusters get distance bonus and rank higher.
    """
    u         = _user_vector(pantry, model)
    distances = model["kmeans"].transform(u.reshape(1, -1))[0]

    # Personalization: pull saved clusters closer
    cluster_counts = _get_saved_cluster_counts(model, db_path)
    if cluster_counts:
        distances = _apply_save_boost(distances, cluster_counts)
        print(f"[recommender] personalization active - "
              f"{sum(cluster_counts.values())} saved recipes across "
              f"{len(cluster_counts)} clusters")

    n_look = 9 if len(pantry) < 3 else TOP_CLUSTERS
    return np.argsort(distances)[:n_look].tolist()


# ── Main recommendation function ──────────────────────────────────────────────

def recommend(user_spices: list, filters=None, courses=None,
              top_n=20, favorite_spices=None) -> list:
    """
    Recommend recipes using v5 ML pipeline + implicit feedback personalization.

    user_spices:     canonical spice strings from the user's pantry
    filters:         diet filter strings e.g. ['is_vegan', 'is_gluten_free']
    courses:         course strings e.g. ['Mains & Sides']
    top_n:           number of results to return
    favorite_spices: per-spice boost (legacy, kept for backwards compat)
    """
    model = load()
    if model is None or not user_spices:
        return []

    pantry_set   = set(user_spices)
    favorite_set = set(favorite_spices) if favorite_spices else set()

    # Dietary + course filter mask from precomputed arrays
    filter_mask = None
    if (filters and len(filters) > 0) or (courses and len(courses) > 0):
        if _norm_titles is None:
            return []
        filter_mask = np.ones(len(model["recipe_titles"]), dtype=bool)
        for f in (filters or []):
            if f in _diet_masks:
                filter_mask &= _diet_masks[f]
        if courses and len(courses) > 0 and _course_arr is not None:
            filter_mask &= np.isin(np.asarray(_course_arr, dtype=str), courses)
        if not filter_mask.any():
            return []

    u                = _user_vector(user_spices, model)
    nearest_clusters = _nearest_clusters(user_spices, model)

    cluster_arr  = np.array(model["cluster_labels"])
    cluster_mask = np.zeros(len(cluster_arr), dtype=bool)
    for cid in nearest_clusters:
        cluster_mask |= (cluster_arr == cid)

    scores = model["recipe_matrix"] @ u
    scores[~cluster_mask] = 0
    if filter_mask is not None:
        scores[~filter_mask] = 0

    # Legacy favorite spice boost
    if favorite_set:
        BOOST_PER_MATCH = 0.15
        MAX_BOOST       = 0.60
        for i, sp_list in enumerate(model["recipe_spices"]):
            if scores[i] <= 0:
                continue
            matches = len(favorite_set & set(sp_list))
            if matches:
                boost = min(matches * BOOST_PER_MATCH, MAX_BOOST)
                scores[i] = min(scores[i] * (1 + boost), 1.0)

    top_idx = np.argsort(scores)[::-1]
    results = []

    diet_col_map = {
        "vegetarian": "is_vegetarian", "vegan": "is_vegan",
        "dairy-free": "is_dairy_free", "gluten-free": "is_gluten_free",
        "keto": "is_keto", "paleo": "is_paleo",
        "halal": "is_halal", "kosher": "is_kosher", "hindu": "is_hindu_friendly"
    }

    for i in top_idx:
        if scores[i] <= 0 or len(results) == top_n:
            break
        sp      = set(model["recipe_spices"][i])
        matched = sorted(pantry_set & sp)

        # Require at least 1 pantry spice in every result
        # Prevents geometrically-close but ingredient-irrelevant results
        if len(matched) == 0:
            continue

        cid     = int(cluster_arr[i])
        profile = ", ".join(model["cluster_top_spices"].get(cid, [])[:3])
        course  = str(_course_arr[i]) if _course_arr is not None else "Unknown"
        diets   = [name for name, col in diet_col_map.items()
                   if col in _diet_masks and _diet_masks[col][i]]

        results.append({
            "title":      model["recipe_titles"][i],
            "score":      round(float(scores[i]), 3),
            "profile":    profile,
            "matched":    matched,
            "missing":    sorted(sp - pantry_set),
            "all_spices": list(sp),
            "saved":      False,
            "course":     course,
            "diets":      diets,
        })

    return results


# ── Unchanged utility functions ───────────────────────────────────────────────

def get_recipe_details(title: str) -> dict | None:
    load()
    if _recipe_lookup is None:
        return None
    row = _recipe_lookup.get(title.strip())
    if row is None:
        return None
    try:
        ings = ast.literal_eval(str(row.ingredients))
        if not isinstance(ings, list):
            ings = str(row.ingredients).split(",")
    except Exception:
        ings = str(row.ingredients).split(",")
    try:
        dirs = ast.literal_eval(str(row.directions))
        if not isinstance(dirs, list):
            dirs = str(row.directions).split(",")
    except Exception:
        dirs = str(row.directions).split(",")
    return {
        "ingredients": [i.strip() for i in ings if str(i).strip()],
        "directions":  [d.strip() for d in dirs if str(d).strip()],
    }


def search_recipes(query: str, filters=None, courses=None,
                   max_results: int = 50) -> pd.DataFrame:
    load()
    if _recipe_df is None or _lower_titles is None:
        return pd.DataFrame()

    filter_mask = np.ones(len(_lower_titles), dtype=bool)
    if filters:
        for f in filters:
            if f in _diet_masks:
                filter_mask &= _diet_masks[f]
    if courses:
        filter_mask &= np.isin(_recipe_df['course_category'].values, courses)

    lower_q    = query.lower().strip()
    pattern    = rf'\b{re.escape(lower_q)}\b'
    mask_exact = (
        pd.Series(_lower_titles).str.contains(pattern, regex=True, na=False).values
        & filter_mask
    )
    exact_matches = _recipe_df[mask_exact]

    if len(exact_matches) < max_results:
        mask_sub = (
            pd.Series(_lower_titles).str.contains(lower_q, regex=False, na=False).values
            & filter_mask
            & ~mask_exact
        )
        sub_matches = _recipe_df[mask_sub].head(max_results - len(exact_matches))
        return pd.concat([exact_matches, sub_matches]).head(max_results)

    return exact_matches.head(max_results)


def get_recipe_meta(title: str) -> dict:
    load()
    meta = {"course": "", "diets": []}
    if _norm_titles is None or _course_arr is None:
        return meta

    t = title.strip().lower()
    matches = _norm_titles[_norm_titles == t]
    if matches.empty:
        return meta

    i = matches.index[0]
    meta["course"] = str(_course_arr[i])

    diet_col_map = {
        "vegetarian": "is_vegetarian", "vegan": "is_vegan",
        "dairy-free": "is_dairy_free", "gluten-free": "is_gluten_free",
        "keto": "is_keto", "paleo": "is_paleo",
        "halal": "is_halal", "kosher": "is_kosher", "hindu": "is_hindu_friendly"
    }
    meta["diets"] = [name for name, col in diet_col_map.items()
                     if col in _diet_masks and _diet_masks[col][i]]
    return meta


def suggest_spices(user_spices: list, top_n: int = 5) -> list:
    model = load()
    if model is None:
        return []
    pantry_set = set(user_spices)
    unlock: Counter = Counter()
    for sp_list in model["recipe_spices"]:
        missing = set(sp_list) - pantry_set
        if len(missing) == 1:
            unlock[next(iter(missing))] += 1
    return unlock.most_common(top_n)
