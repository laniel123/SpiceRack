# SpiceRack
**DS Club Project — Spring 2026**

Tell us what spices you have, we tell you what you can cook.

[![SpiceRack Demo](https://img.youtube.com/vi/q3erh9lnYGU/maxresdefault.jpg)](https://youtu.be/q3erh9lnYGU?si=QYqmMikjBPr1kx1P)

---

## What it does

SpiceRack is a recipe recommendation web app built on the [RecipeNLG dataset](https://recipenlg.cs.put.poznan.pl/) (~2.2 million recipes). You add the spices in your pantry, and the model finds recipes that match your flavor profile — not just salt and pepper, but the spices that actually make the dish.

The system learns which spices are rare and distinctive (saffron, galangal, za'atar) vs common and uninformative (salt, pepper), so recommendations are driven by what makes your pantry unique.

---

## Features

### ➕ Add Spices to Your Pantry
Type in the spices you have and SpiceRack validates them against a 179-spice canonical vocabulary with 319+ aliases (`jeera` → `cumin`, `haldi` → `turmeric`). You can also scan barcodes on spice jars to add them automatically.

![Adding spices](https://github.com/user-attachments/assets/87c49159-aae1-4e2f-a306-9f94669479c2)

### 🌶️ Spice Recommendation Bar
See which spice to buy next to unlock the most new recipes from the 2.2M dataset.

![Spice bar](https://github.com/user-attachments/assets/4be0340b-5086-4e14-969c-8d13f1fd9e27)

### 🔍 Search Recipes
Search the full 2.2M recipe database by title.

![Search recipes](https://github.com/user-attachments/assets/5f2e196c-83c9-4ec2-8048-de8fc28b7173)

### 🥗 Dietary Filters
Filter recommendations by dietary preference — vegetarian, vegan, gluten-free, keto, paleo, halal, kosher, dairy-free, and hindu-friendly.

![Dietary filters](https://github.com/user-attachments/assets/6d5a54ce-f136-4609-a10f-9430d2be35fa)

### 📚 Saved Recipe Library
Heart any recipe to save it to your personal collection.

![Saved library](https://github.com/user-attachments/assets/e1111d3a-8162-499d-bb83-4fc19163d0e9)

### 🎲 Random Recipe
Feeling adventurous? Discover something new with a random recipe.

![Random recipe](https://github.com/user-attachments/assets/584256eb-88b8-493b-8e3b-4d13802f77da)

---

## The Model

Trained in `main.ipynb` on the RecipeNLG dataset.

### Training pipeline

1. **Load** — parse the NER column (pre-extracted ingredient tokens) rather than raw ingredient strings
2. **Spice extraction** — match tokens against a 179-spice canonical vocabulary, resolving 319 aliases (`jeera` → `cumin`, `haldi` → `turmeric`, `pizza oregano` → `oregano`)
3. **Filter** — drop recipes with fewer than 2 matched spices
4. **TF-IDF weighting** — downweight common spices (salt: ~0.24 weight) and upweight rare ones
5. **IDF boost** — square the IDF weights so rare spices dominate the flavor space
6. **SVD** — `TruncatedSVD(n_components=100)` compresses 179 binary spice dims to 100 dense dims
7. **Clustering** — `MiniBatchKMeans(n_clusters=100)` discovers natural flavor families. Silhouette score: **0.667**
8. **Save** — everything saved to `spicerack_model.joblib`

### How recommendations work

```
pantry → mlb.transform() → tfidf.transform() → × idf_boost → normalize
       → svd.transform() → normalize → user_vec
       → kmeans.transform() → top 5–9 nearest clusters
       → scores = recipe_matrix @ user_vec → rank → top 12
```

Small pantries (1–2 spices) search up to 9 nearest clusters to avoid missing relevant recipes from sparse vector misrouting.

---

## The Dataset

The final dataset (`full_recipes_with_restrictions.csv`) extends the base RecipeNLG columns with engineered features:

| Column | Description |
|--------|-------------|
| `spices` | Canonical spice set extracted from NER tokens |
| `cluster` | K-Means cluster ID |
| `course_category` | Rule-based course label (Mains & Sides, Dessert & Sweets, Other) |
| `is_vegetarian` | No meat, poultry, or seafood detected |
| `is_vegan` | No animal products detected |
| `is_dairy_free` | No dairy detected |
| `is_gluten_free` | No gluten-containing ingredients detected |
| `is_keto` | Low-carb profile — no grains, sugar, or starchy vegetables |
| `is_paleo` | No grains, legumes, dairy, or refined sugar |
| `is_halal` — No pork or alcohol detected |
| `is_kosher` | No pork or shellfish detected |
| `is_hindu_friendly` | No beef detected |
| `allergens_present` | Comma-separated list of detected allergens |

See `SpiceRack_Codebook.docx` for full column definitions, data types, sample rates, and known limitations.

---

## Setup

### 1. Download the dataset

Download `full_dataset.csv` from [RecipeNLG on Kaggle](https://www.kaggle.com/datasets/saloni1712/recipenlg) and place it in the project root.

### 2. Train the model

Open `main.ipynb` and run all cells in order. This generates:
- `spicerack_model.joblib` (~974 MB) — the trained model
- `full_recipes_with_restrictions.csv` — the full dataset with dietary flags

Both files are too large for GitHub and must be generated locally.

### 3. Install dependencies

```bash
pip install flask scikit-learn scipy joblib numpy pandas requests
pip install pyzbar opencv-python   # barcode scanner
pip install -r requirements.txt

brew install zbar                   # Mac only — required for pyzbar
```

If you get `Unable to find zbar shared library` on Mac, add this to `~/.zshrc`:

```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/Cellar/zbar/0.23.93_2/lib:$DYLD_LIBRARY_PATH
```

### 4. Run the website

```bash
cd SpiceRack-website-main
python3 app.py
```

Open `http://127.0.0.1:5000`

---

## Large Files (not in git)

These files must be generated locally — they are excluded from version control:

| File | Size | How to generate |
|------|------|-----------------|
| `spicerack_model.joblib` | ~974 MB | Run `main.ipynb` |
| `full_recipes_with_restrictions.csv` | ~2 GB | Run `main.ipynb` |
| `full_dataset.csv` | ~2.2M rows | Download from Kaggle |

---

## Tech Stack

- **Python 3.11**
- **scikit-learn** — MiniBatchKMeans, TruncatedSVD, TfidfTransformer, MultiLabelBinarizer
- **Flask** — web server
- **SQLite** — user pantry and saved recipes
- **joblib** — model serialization
- **pandas / numpy** — data processing
- **Unsplash API** — recipe photos (disk-cached)
- **pyzbar + OpenCV** — barcode scanning
- **Open Food Facts API** — barcode product lookup

---

## Team

SpiceRack: Daniel Larson, Elijah Ret, Arya Moghadam, Ethan Rao, Luke Maldonado, Austin Pak, Emanuel Rodriguez — Spring 2026
