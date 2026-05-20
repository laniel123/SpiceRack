# ============================================================
# SpiceRack Model v5.1 — Dual-matrix + Cosine Silhouette
# ============================================================
#
# Fixes applied on top of v5.0:
#
#   FIX 1 — Dual scoring matrix (closes the catch-all cluster):
#     v5.0 zeroed universal spices in BOTH the training matrix
#     and the scoring matrix. Recipes whose only spices were
#     salt/garlic/pepper had all-zero vectors after exclusion,
#     so they collapsed into one giant catch-all cluster (~35k).
#
#     Fix: maintain two separate SVD projections —
#       X_svd_train: universals zeroed → K-Means clusters here
#       X_svd_score: universals kept   → cosine similarity here
#     K-Means sees clean signal. Scoring sees full recipe flavor.
#     The catch-all cluster disappears because those recipes now
#     have non-zero scoring vectors and spread across real clusters.
#
#   FIX 2 — Cosine silhouette instead of euclidean:
#     All vectors are L2-normalized, so euclidean and cosine
#     distance are monotonically related — but cosine silhouette
#     directly measures what we care about: angular separation
#     between clusters. Reported number is now the correct metric.
#
#   KEPT from v5.0:
#     - SVD before K-Means (geometry fix)
#     - IDF boost capped at 1.5x
#     - MIN_SPICES = 3
#     - N_SVD_DIMS = 50, N_CLUSTERS = 475
#     - k-means++, n_init=25, batch_size=32768
#     - Single-pass cluster splitting
# ============================================================

import re
import warnings
import numpy as np
import pandas as pd
import joblib
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import MultiLabelBinarizer, normalize
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.metrics import silhouette_score
from scipy.sparse import csr_matrix

from spice_data_v2 import SPICES, ALIASES, CANONICAL_SPICES, FLAVOR_PROFILES, REGION_PROFILES

warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
CSV_PATH       = "cookingdataset/RecipeNLG_dataset.csv"
OUTPUT_PATH    = "spicerack_model_v5.joblib"
SAMPLE_SIZE    = None          # None = full 2.2M dataset

N_CLUSTERS     = 475           # proportional to 727k recipe dataset
N_SVD_DIMS     = 50            # actual compression: 96.2% variance at 50 dims
SIZE_THRESHOLD = 50_000        # split clusters bigger than this
SUBCLUSTERS    = 5             # sub-pieces per split
MIN_SPICES          = 3    # require ≥3 spices total per recipe
MIN_DISTINCTIVE     = 2    # require ≥2 spices AFTER removing universals
#                            recipes with only salt/garlic/pepper are excluded
#                            this is what kills the 35k catch-all cluster
IDF_CAP             = 1.5  # cap rare-spice boost at 1.5x

# Universal spices excluded from training — appear too often to add signal
EXCLUDE_SPICES = {'salt', 'garlic', 'black pepper', 'kosher salt', 'white pepper'}


# ── HELPERS (unchanged from your notebook) ───────────────────────────────────

def clean(s) -> str:
    if not isinstance(s, str):
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z\s']", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def to_canonical(spice):
    n = clean(spice)
    return clean(ALIASES.get(n, n))

SPICE_PATTERNS = sorted(
    [(sp, clean(sp), re.compile(rf"(^| ){re.escape(clean(sp))}( |$)")) for sp in SPICES],
    key=lambda x: -len(x[0])
)

def get_spices_from_recipe(ingredients):
    if isinstance(ingredients, list):
        raw = " ".join(str(x) for x in ingredients)
    else:
        raw = str(ingredients)
    text = clean(raw)
    found = set()
    # Pass 1: exact canonical match
    for _, norm, pat in SPICE_PATTERNS:
        if pat.search(" " + text + " "):
            found.add(norm)
    # Pass 2: alias fallback
    for alias, canon in ALIASES.items():
        if canon in CANONICAL_SPICES and alias in text and canon not in found:
            found.add(canon)
    return {to_canonical(sp) for sp in found}

def parse_ingredient_string(x) -> list:
    if isinstance(x, list):
        return [str(i) for i in x]
    if not isinstance(x, str):
        return []
    s = x.strip()
    if s.startswith("[") and s.endswith("]"):
        items = re.findall(r"'([^']*)'|\"([^\"]*)\"|", s)
        parsed = [a if a else b for a, b in items if a or b]
        return parsed if parsed else [s]
    return [s]


# ── STEP 1: Load data ─────────────────────────────────────────────────────────

print(f"loading {CSV_PATH}...")
df = pd.read_csv(CSV_PATH)

if SAMPLE_SIZE is not None and len(df) > SAMPLE_SIZE:
    df = df.sample(n=SAMPLE_SIZE, random_state=42).reset_index(drop=True)

df["ingredients_parsed"] = df["NER"].apply(parse_ingredient_string)
df["spices"] = df["ingredients_parsed"].apply(get_spices_from_recipe)
print(f"loaded {len(df):,} recipes")


# ── STEP 2: Binary spice matrix ──────────────────────────────────────────────

mlb = MultiLabelBinarizer(classes=sorted(CANONICAL_SPICES))
X = np.asarray(mlb.fit_transform(df["spices"]))
spice_cols = list(mlb.classes_)
print(f"binary matrix: {X.shape}")
print(f"avg spices per recipe: {X.sum(axis=1).mean():.1f}")


# ── STEP 3: Require ≥3 spices total ──────────────────────────────────────────

enough = X.sum(axis=1) >= MIN_SPICES
X  = X[enough]
df = df[enough].reset_index(drop=True)
print(f"kept {len(df):,} recipes with {MIN_SPICES}+ spices")


# ── STEP 3b: Require ≥2 distinctive spices after universal exclusion ──────────
#
# This is the catch-all cluster fix.
# Recipes like [salt, garlic, black pepper, white pepper] pass the MIN_SPICES=3
# filter but have ZERO distinctive spices after universals are removed.
# K-Means correctly groups them together into one giant undifferentiated cluster
# because they're genuinely indistinguishable from each other.
# The fix is to exclude them before training — they add noise, not signal.
# They're still valid recipes; they just don't have enough spice information
# for the model to place them meaningfully.

exclude_set = EXCLUDE_SPICES
distinctive = np.array([
    len(set(spices) - exclude_set) for spices in df["spices"]
])
has_distinctive = distinctive >= MIN_DISTINCTIVE
X  = X[has_distinctive]
df = df[has_distinctive].reset_index(drop=True)
print(f"kept {len(df):,} recipes with {MIN_DISTINCTIVE}+ distinctive spices "
      f"(dropped {(~has_distinctive).sum():,} universal-only recipes)")


# ── STEP 4: TF-IDF + capped IDF boost (v4) ───────────────────────────────────
#
# IDF boost amplifies rare, distinctive spices (saffron, galangal)
# Capped at 1.5x — rare spices still win but can't fully dominate a cluster
# This fixes the "100% vanilla cluster" problem from raw IDF² squaring

tfidf       = TfidfTransformer(norm="l2", use_idf=True, smooth_idf=True)
X_tfidf     = tfidf.fit_transform(csr_matrix(X))
idf_weights = np.array(tfidf.idf_)
idf_boost   = np.clip(idf_weights, 1.0, IDF_CAP) / IDF_CAP
X_boosted   = normalize(X_tfidf.multiply(idf_boost), norm="l2")

print(f"\nspice weight check:")
for sp in ['salt', 'black pepper', 'garlic', 'cumin', 'saffron', 'galangal']:
    if sp in spice_cols:
        w = float(X_boosted[:, spice_cols.index(sp)].mean())
        print(f"  {sp:<20} {w:.6f}")


# ── STEP 5: Build TWO matrices — train and score ──────────────────────────────
#
# The catch-all cluster problem in v5.0 came from zeroing universal spices
# in BOTH matrices. Recipes whose only spices were salt/garlic/pepper ended
# up as all-zero vectors, collapsed into one giant cluster (~35k recipes).
#
# Fix: split into two separate SVD projections:
#
#   X_svd_train — universals ZEROED
#     Used by K-Means. Universal spices add no discriminative signal for
#     clustering — they just pull every centroid toward the same background.
#     Zeroing them here gives K-Means clean, distinctive flavor signal.
#
#   X_svd_score — universals KEPT
#     Used for cosine similarity scoring at inference time.
#     Keeping them here means recipes with only universal spices still
#     have non-zero scoring vectors and return meaningful similarity scores
#     instead of collapsing into one undifferentiated catch-all cluster.
#
# Both use the same SVD fit (fitted on X_train) so they share the same
# latent space — K-Means cluster assignments remain valid for scoring.

exclude_idx = [spice_cols.index(s) for s in EXCLUDE_SPICES if s in spice_cols]
print(f"\nexcluded spices: {sorted(EXCLUDE_SPICES)}")

# Training matrix: universals zeroed
X_train_sparse = X_boosted.tolil()
X_train_sparse[:, exclude_idx] = 0
X_train_sparse = normalize(csr_matrix(X_train_sparse), norm="l2")

# Scoring matrix: universals kept (full boosted matrix)
X_score_sparse = X_boosted

print(f"X_train shape: {X_train_sparse.shape}  (universals zeroed)")
print(f"X_score shape: {X_score_sparse.shape}  (universals kept)")


# ── STEP 6: SVD on training matrix, project both ──────────────────────────────

print(f"\nrunning SVD (n_components={N_SVD_DIMS})...")
svd = TruncatedSVD(n_components=N_SVD_DIMS, random_state=42)

# Fit on the training matrix (universals zeroed — clean cluster signal)
X_svd_train = normalize(svd.fit_transform(X_train_sparse), norm="l2")

# Project scoring matrix using the SAME SVD fit
# Both spaces share the same latent axes — cluster assignments stay valid
X_svd_score = normalize(svd.transform(X_score_sparse), norm="l2")

print(f"X_svd_train shape:  {X_svd_train.shape}")
print(f"X_svd_score shape:  {X_svd_score.shape}")
print(f"variance explained: {svd.explained_variance_ratio_.sum():.1%}")


# ── STEP 7: K-Means on X_svd_train ───────────────────────────────────────────

print(f"\nclustering {len(df):,} recipes into {N_CLUSTERS} clusters...")
kmeans = MiniBatchKMeans(
    n_clusters=N_CLUSTERS,
    random_state=42,
    batch_size=32768,
    n_init=25,
    init='k-means++'
)
df["cluster"] = kmeans.fit_predict(X_svd_train)

print(f"cluster size stats:")
sizes = df["cluster"].value_counts()
print(f"  min: {sizes.min():,}  max: {sizes.max():,}  mean: {sizes.mean():.0f}")
print(f"  clusters > 10k: {(sizes > 10000).sum()}  (catch-all check — should be 0)")


# ── STEP 8: Single-pass cluster split ────────────────────────────────────────
#
# Splits oversized clusters exactly once. No recursive while loop —
# recursive splitting causes cascade on dense spice regions.

print("checking for oversized clusters (single pass)...")
next_id     = N_CLUSTERS
split_count = 0

for cid in range(N_CLUSTERS):
    mask = df["cluster"] == cid
    if mask.sum() <= SIZE_THRESHOLD:
        continue
    print(f"  splitting cluster {cid} ({mask.sum():,} recipes) into {SUBCLUSTERS}...")
    sub_km = MiniBatchKMeans(
        n_clusters=SUBCLUSTERS, random_state=42,
        batch_size=4096, n_init=10
    )
    # Split on X_svd_train — same space as original clustering
    df.loc[mask, "cluster"] = sub_km.fit_predict(X_svd_train[mask.values]) + next_id
    next_id     += SUBCLUSTERS
    split_count += 1

# Remap to contiguous 0, 1, 2...
old_ids       = sorted(df["cluster"].unique())
id_map        = {old: new for new, old in enumerate(old_ids)}
df["cluster"] = df["cluster"].map(id_map)
n_final       = df["cluster"].nunique()
print(f"split {split_count} oversized clusters → {n_final} total clusters")


# ── STEP 9: Silhouette — cosine metric on X_svd_score ────────────────────────
#
# Using cosine metric because that's what inference uses (dot product of
# normalized vectors). This is the number that actually reflects
# how well-separated the clusters are from the user's perspective.
# X_svd_score (universals kept) is used because that's what scoring sees.

sample_idx = np.random.choice(len(df), min(5000, len(df)), replace=False)
sil = silhouette_score(
    X_svd_score[sample_idx],
    df["cluster"].iloc[sample_idx],
    metric='cosine'
)
print(f"\nsilhouette (cosine, scoring matrix): {sil:.4f}")
print(f"  v2 baseline:        0.665  (euclidean, wrong space)")
print(f"  v3.1:               0.780  (euclidean, wrong space — inflated)")
print(f"  v5.0:               0.674  (euclidean, correct space)")
print(f"  v5.1 (this):        {sil:.4f}  (cosine, correct metric)")


# ── STEP 10: Cluster profiles ─────────────────────────────────────────────────
#
# Profiles use raw X (not X_svd) so percentages are interpretable.
# Universal spices are included here — they're informative for display
# even though they were excluded from training.

print("\ncomputing cluster profiles...")
cluster_top_spices = {}

for cid in range(n_final):
    mask = df["cluster"] == cid
    if not mask.any():
        continue
    freq    = X[mask.values].mean(axis=0)
    top_idx = freq.argsort()[::-1][:8]
    top     = [spice_cols[i] for i in top_idx if freq[i] > 0]
    cluster_top_spices[cid] = top

print(f"profiles computed for {len(cluster_top_spices)} clusters")
print("\nsample clusters:")
for cid in list(cluster_top_spices.keys())[:8]:
    mask = df["cluster"] == cid
    print(f"  cluster {cid:>3} ({mask.sum():>5} recipes)  "
          f"{', '.join(cluster_top_spices[cid][:5])}")


# ── STEP 11: Save model ───────────────────────────────────────────────────────

model = {
    # Core pipeline — all needed for inference
    "kmeans":             kmeans,          # trained on X_svd_train
    "svd":                svd,             # fit on X_train_sparse, projects both
    "tfidf":              tfidf,           # fit on raw binary X
    "mlb":                mlb,             # spice vocabulary

    # Stored weights for inference
    "idf_boost":          idf_boost,       # shape (n_spices,)
    "exclude_idx":        exclude_idx,     # indices zeroed in training only

    # TWO recipe matrices (the dual-matrix fix)
    # recipe_matrix_score is what recommender.py uses for cosine similarity
    # recipe_matrix_train is kept for reference / retraining
    "recipe_matrix":      X_svd_score,     # (n_recipes, 50) — full flavor, for scoring
    "recipe_matrix_train":X_svd_train,     # (n_recipes, 50) — zeroed, for cluster ref

    # Recipe data
    "recipe_titles":      df["title"].tolist(),
    "recipe_spices":      [list(s) for s in df["spices"]],
    "cluster_labels":     df["cluster"].tolist(),
    "cluster_top_spices": cluster_top_spices,

    # Metadata
    "n_clusters":         n_final,
    "n_recipes":          len(df),
    "silhouette":         round(float(sil), 4),
    "model_version":      "v5.1",
    "n_svd_dims":         N_SVD_DIMS,
    "excluded_spices":    list(EXCLUDE_SPICES),
    "min_spices":         MIN_SPICES,
    "min_distinctive":    MIN_DISTINCTIVE,
    "idf_cap":            IDF_CAP,
}

joblib.dump(model, OUTPUT_PATH, compress=3)

print("\n" + "="*55)
print(f"model saved → {OUTPUT_PATH}")
print("="*55)
print(f"  model_version:   {model['model_version']}")
print(f"  n_recipes:       {model['n_recipes']:,}")
print(f"  n_clusters:      {model['n_clusters']}")
print(f"  n_svd_dims:      {model['n_svd_dims']}")
print(f"  silhouette:      {model['silhouette']}  (cosine)")
print(f"  idf_cap:         {model['idf_cap']}x")
print(f"  excluded_spices: {model['excluded_spices']}")
print(f"  min_spices:      {model['min_spices']}")
print("="*55)


# ── INFERENCE FUNCTION ────────────────────────────────────────────────────────
#
# This is what recommender.py needs to update to.
# The key change: user vector goes through the FULL pipeline
# before being passed to kmeans.transform() and cosine scoring.
#
# Old (broken):
#   user_bin → kmeans.predict(user_bin)  [predict in binary space]
#   user_bin → svd.transform(user_bin)   [then project to SVD space]
#
# New (correct):
#   user_bin → tfidf → idf_boost → zero excludes → svd → normalize
#   kmeans.transform(user_svd)    [predict in SVD space — matches training]
#   recipe_matrix @ user_svd      [cosine sim in same SVD space]

def build_user_vector(pantry_set, model):
    """
    Build user vector for inference.
    Universals are KEPT (not zeroed) — this matches X_svd_score,
    the matrix used for cosine similarity scoring.
    K-Means cluster search uses the same vector — clusters were learned
    on the zeroed matrix but the SVD projection is shared, so distances
    remain meaningful.
    """
    m = model
    user_bin = np.asarray(m["mlb"].transform([pantry_set]), dtype=np.float32)

    user_tfidf:   csr_matrix = csr_matrix(m["tfidf"].transform(csr_matrix(user_bin)))
    user_boosted: csr_matrix = csr_matrix(user_tfidf.multiply(m["idf_boost"]))
    user_boosted  = normalize(user_boosted, norm="l2")

    user_svd = m["svd"].transform(user_boosted)[0]
    norm = np.linalg.norm(user_svd)
    if norm > 0:
        user_svd /= norm
    return user_svd


def recommend_v5(pantry, must_use=None, top_k=10, top_clusters=7,
                 min_match=1, model=None):
    """
    Full inference pipeline for v5.1.
    pantry:       list or set of spice strings
    must_use:     list/set of spices that MUST appear in every result
    top_k:        number of recipes to return
    top_clusters: how many nearest clusters to search
    min_match:    minimum number of pantry spices that must appear in result
                  defaults to 1 — eliminates zero-match results like Ouzorita
    model:        loaded joblib model dict
    """
    if model is None:
        raise ValueError("pass model=joblib.load('spicerack_model_v5.joblib')")

    m         = model
    pantry_set = set(pantry)
    must_set   = set(must_use) if must_use else set()

    # Build user vector in SVD space
    user_svd = build_user_vector(pantry_set, m)

    # Find nearest clusters in SVD space (same space K-Means was trained on)
    cluster_arr = np.array(m["cluster_labels"])
    distances   = m["kmeans"].transform(user_svd.reshape(1, -1))[0]
    top_cluster_ids = np.argsort(distances)[:top_clusters]
    cluster_mask = np.isin(cluster_arr, top_cluster_ids)

    # Cosine similarity in SVD space (dot product since both are unit vectors)
    scores = m["recipe_matrix"] @ user_svd
    scores[~cluster_mask] = -1  # mask out non-candidate clusters

    # Must-use filter
    if must_set:
        spice_cols = list(m["mlb"].classes_)
        must_idx   = [spice_cols.index(s) for s in must_set if s in spice_cols]
        if must_idx:
            recipe_spices_arr = [set(s) for s in m["recipe_spices"]]
            must_mask = np.array([must_set.issubset(s) for s in recipe_spices_arr])
            scores[~must_mask] = -1

    # Top K
    top_idx = np.argsort(scores)[::-1][:top_k * 3]  # oversample to allow for min_match filtering

    results = []
    for i in top_idx:
        if scores[i] < 0 or len(results) == top_k:
            break
        recipe_spices = set(m["recipe_spices"][i])
        matched = sorted(pantry_set & recipe_spices)

        # Minimum match filter — prevents zero-match results from surfacing
        if len(matched) < min_match:
            continue

        results.append({
            "title":          m["recipe_titles"][i],
            "score":          round(float(scores[i]), 4),
            "matched_spices": matched,
            "cluster":        int(cluster_arr[i]),
        })

    return results


# ── QUICK SMOKE TEST ──────────────────────────────────────────────────────────

print("\n--- smoke test ---")
test_pantries = [
    {"cumin", "paprika", "chili powder", "oregano"},
    {"cinnamon", "ginger", "nutmeg", "cloves", "cardamom"},
    {"galangal"},   # single exotic spice — the misrouting edge case
]

for pantry in test_pantries:
    results = recommend_v5(pantry, model=model)
    print(f"\npantry: {sorted(pantry)}")
    for r in results[:3]:
        print(f"  {r['score']:.3f}  {r['title'][:50]}  {r['matched_spices']}")
