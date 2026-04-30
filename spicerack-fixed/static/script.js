// ── GLOBALS ───────────────────────────────────────────────────────────────────
let searchTimer;
let currentModalRecipe = { title: '', profile: '', matched: [] };

// ── TAB SYSTEM ────────────────────────────────────────────────────────────────

function switchTab(tabId, clickedElement) {
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.user-tab, .recipe-tab').forEach(t => t.classList.remove('active-tab'));
    const target = document.getElementById(tabId);
    if (target) target.style.display = 'block';
    if (clickedElement) clickedElement.classList.add('active-tab');
}

async function openRecipeTab(title) {
    const safeTitle = title.replace(/[^a-zA-Z0-9]/g, '-');
    const tabId     = 'recipe-tab-' + safeTitle;
    const contentId = 'recipe-content-' + safeTitle;

    if (document.getElementById(tabId)) {
        switchTab(contentId, document.getElementById(tabId));
        return;
    }

    const tabsContainer = document.querySelector('.recipe-tabs');
    const newTab = document.createElement('div');
    newTab.id = tabId;
    newTab.className = 'recipe-tab user-tab';
    newTab.innerHTML = `
        <h1 class="recipe-header-title" style="font-size:0.8rem;">${title}</h1>
        <button class="close-tab" onclick="closeRecipeTab(event,'${contentId}','${tabId}')">×</button>
    `;
    newTab.onclick = () => switchTab(contentId, newTab);
    tabsContainer.appendChild(newTab);

    const recipeBox = document.querySelector('.recipe-box');
    const newContent = document.createElement('div');
    newContent.id = contentId;
    newContent.className = 'body-r tab-content recipe-detail-view';
    newContent.style.display = 'none';
    newContent.innerHTML = `<div class="loading-recipe">Loading ${title}...</div>`;
    recipeBox.appendChild(newContent);

    switchTab(contentId, newTab);

    try {
        const response = await fetch(`/get_recipe_details/${encodeURIComponent(title)}`);
        const data     = await response.json();
        if (data.error) throw new Error(data.error);

        const ingHtml  = data.ingredients.map(i => `<li>${i.trim()}</li>`).join('');
        const stepHtml = data.directions.map(d => `<li>${d.trim()}</li>`).join('');
        const imgHtml  = data.image
            ? `<img src="${data.image}" alt="${title}" class="recipe-detail-img">`
            : '';

        const isSaved    = data.saved || false;
        const profile    = data.profile || '';
        const matched    = data.matched || [];
        const heartClass = isSaved ? 'detail-heart saved' : 'detail-heart';
        const heartChar  = isSaved ? '♥' : '♡';

        newContent.innerHTML = `
            <div class="recipe-detail-header">
                <h2>${title}</h2>
                <button class="${heartClass}"
                    data-title="${title.replace(/"/g, '&quot;')}"
                    data-profile="${profile.replace(/"/g, '&quot;')}"
                    data-matched='${JSON.stringify(matched)}'
                    onclick="toggleSave(event, this)"
                    title="${isSaved ? 'Saved' : 'Save to Your Recipes'}">
                    ${heartChar}
                </button>
            </div>
            <div class="recipe-detail-body">
                ${imgHtml}
                <div class="recipe-detail-columns">
                    <div class="ingredients-col">
                        <h3>Ingredients</h3>
                        <ul>${ingHtml}</ul>
                    </div>
                    <div class="directions-col">
                        <h3>Directions</h3>
                        <ol>${stepHtml}</ol>
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        newContent.innerHTML = `<div class="error-msg">Could not load recipe details.</div>`;
    }
}

function closeRecipeTab(event, contentId, tabId) {
    event.stopPropagation();
    const tab     = document.getElementById(tabId);
    const content = document.getElementById(contentId);
    const wasActive = tab && tab.classList.contains('active-tab');
    if (tab)     tab.remove();
    if (content) content.remove();
    if (wasActive) {
        const recommendsBtn = document.querySelector('.user-tab[onclick*="tab-recommends"]');
        switchTab('tab-recommends', recommendsBtn);
    }
}

document.addEventListener('click', function(e) {
    if (e.target.classList.contains('recipe-title')) {
        openRecipeTab(e.target.getAttribute('data-title'));
    }
});


// ── FILTER PANEL ──────────────────────────────────────────────────────────────

function toggleFilters() {
    const panel = document.getElementById('filter-bar-panel');
    const btn   = document.getElementById('filters-toggle');
    panel.classList.toggle('open');
    btn.classList.toggle('active');
}

function clearFilters() {
    document.querySelectorAll('input[name="pref"], input[name="course_pref"]')
        .forEach(cb => cb.checked = false);
    applyFilters();
}

// ── SPICE FAVORITE ────────────────────────────────────────────────────────────

function toggleSpiceFav(event, spiceId) {
    event.preventDefault();
    event.stopPropagation();

    const btn  = event.currentTarget;
    const card = btn.closest('.spice-item, .spice-card, [data-spice-id]');

    // Optimistic UI toggle — flip the star immediately, no reload
    const isFav = btn.classList.contains('fav-active');
    btn.classList.toggle('fav-active', !isFav);
    btn.title = isFav ? 'Mark as favorite' : 'Remove favorite';

    fetch('/toggle_spice_favorite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spice_id: spiceId })
    }).catch(err => {
        // Roll back on failure
        btn.classList.toggle('fav-active', isFav);
        console.error('toggleSpiceFav error:', err);
    });
}


// ── FILTER APPLICATION (AJAX — no page reload) ────────────────────────────────

let filterTimer;

/**
 * Gathers checked preferences and fetches fresh recommendations via AJAX.
 * Swaps only the recipe cards — no full page reload, no Unsplash tsunami.
 */
async function applyFilters() {
    const prefs   = Array.from(document.querySelectorAll('input[name="pref"]:checked'))
                         .map(i => `pref=${encodeURIComponent(i.value)}`);
    const courses = Array.from(document.querySelectorAll('input[name="course_pref"]:checked'))
                         .map(i => `course_pref=${encodeURIComponent(i.value)}`);
    const queryString = [...prefs, ...courses].join('&');
    const url = queryString ? `/api/recommendations?${queryString}` : '/api/recommendations';

    // Show a lightweight loading state in the recommendations grid
    const grid = document.getElementById('recommendations-grid');
    if (grid) grid.style.opacity = '0.4';

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const recipes = await response.json();
        renderRecommendations(recipes);
    } catch (err) {
        console.error('applyFilters error:', err);
    } finally {
        if (grid) grid.style.opacity = '1';
    }
}

/**
 * Re-renders the recommendations grid from a JSON array.
 * Matches the card HTML your Jinja template produces — adjust class names if needed.
 */
function renderRecommendations(recipes) {
    const grid = document.getElementById('recommendations-grid');
    if (!grid) return;

    if (!recipes || recipes.length === 0) {
        grid.innerHTML = '<p class="empty-sub">No recipes match those filters.</p>';
        // Update counter
        const counter = document.getElementById('rec-count');
        if (counter) counter.textContent = '0';
        return;
    }

    grid.innerHTML = recipes.map(r => {
        const imgHtml = r.image
            ? `<div class="card-img-wrap"><img src="${r.image}" alt="${r.title}" class="card-img" loading="lazy"></div>`
            : '';
        const matchedHtml = r.matched.length
            ? `<div class="card-matched">${r.matched.map(s => `<span class="spice-tag">${s}</span>`).join('')}</div>`
            : '';
        const heartClass = r.saved ? 'card-heart saved' : 'card-heart';
        const heartChar  = r.saved ? '♥' : '♡';
        const dietBadges = r.diets.map(d => `<span class="diet-badge">${d}</span>`).join('');

        return `
        <article class="recipe-card" data-title="${r.title}">
            ${imgHtml}
            <div class="card-body">
                <div class="card-top-row">
                    <p class="card-profile">${r.profile}</p>
                    <button class="${heartClass}"
                        onclick="toggleSave(event, this)"
                        data-title="${r.title.replace(/"/g, '&quot;')}"
                        data-profile="${r.profile.replace(/"/g, '&quot;')}"
                        data-matched='${JSON.stringify(r.matched)}'
                        title="${r.saved ? 'Saved' : 'Save to Your Recipes'}">
                        ${heartChar}
                    </button>
                </div>
                <h3 class="card-title recipe-title" data-title="${r.title}">${r.title}</h3>
                ${matchedHtml}
                ${dietBadges}
            </div>
        </article>`;
    }).join('');

    // Update the "X recipes found" counter if it exists in your template
    const counter = document.getElementById('rec-count');
    if (counter) counter.textContent = recipes.length;
}

// Auto-apply filters when any checkbox changes
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[name="pref"], input[name="course_pref"]').forEach(cb => {
        cb.addEventListener('change', () => {
            clearTimeout(filterTimer);
            filterTimer = setTimeout(applyFilters, 300);
        });
    });
});


// ── MODAL ─────────────────────────────────────────────────────────────────────

async function openModal(title) {
    const modal = document.getElementById('recipe-modal');
    const img   = document.getElementById('modal-image');
    const ings  = document.getElementById('modal-ingredients');
    const steps = document.getElementById('modal-steps');
    const heart = document.getElementById('modal-heart');

    document.getElementById('modal-title').innerText = title;
    ings.innerHTML  = '<li>Loading...</li>';
    steps.innerHTML = '<li>Loading...</li>';
    img.style.display = 'none';
    modal.classList.add('open');

    currentModalRecipe.title = title;

    try {
        const r    = await fetch(`/get_recipe_details/${encodeURIComponent(title)}`);
        const data = await r.json();
        if (data.error) throw new Error(data.error);

        currentModalRecipe.profile = data.profile || '';
        currentModalRecipe.matched = data.matched || [];
        currentModalRecipe.saved   = data.saved || false;

        if (heart) {
            heart.classList.toggle('saved', data.saved);
            heart.innerHTML = data.saved ? '♥' : '♡';
        }

        if (data.image) {
            img.src = data.image;
            img.style.display = 'block';
        }

        ings.innerHTML  = data.ingredients.map(i => `<li>${i.trim()}</li>`).join('');
        steps.innerHTML = data.directions.map(d => `<li>${d.trim()}</li>`).join('');
    } catch (e) {
        ings.innerHTML  = '<li>Could not load ingredients.</li>';
        steps.innerHTML = '<li>Could not load directions.</li>';
        console.error("Modal Error:", e);
    }
}

function closeModal() {
    document.getElementById('recipe-modal').classList.remove('open');
}

function toggleSaveFromModal(event) {
    event.stopPropagation();
    event.preventDefault();
    const btn     = document.getElementById('modal-heart');
    const isSaved = btn.classList.contains('saved');
    btn.classList.toggle('saved', !isSaved);
    btn.innerHTML = isSaved ? '♡' : '♥';
    if (!isSaved) {
        btn.style.transform = 'scale(1.4)';
        setTimeout(() => btn.style.transform = '', 200);
    }
    fetch(isSaved ? '/unsave_recipe' : '/save_recipe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            title:   currentModalRecipe.title,
            profile: currentModalRecipe.profile,
            matched: currentModalRecipe.matched
        })
    });
}


// ── SEARCH ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('search-input');
    if (!input) return;

    input.addEventListener('focus', () => {
        switchTab('tab-search-all', null);
    });

    input.addEventListener('input', function() {
        const query = this.value.trim();
        clearTimeout(searchTimer);
        if (query.length < 2) return;
        searchTimer = setTimeout(async () => {
            try {
                const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                const recipes  = await response.json();
                renderSearchResults(recipes);
            } catch (error) {
                console.error("Search failed:", error);
            }
        }, 400);
    });
});

function renderSearchResults(recipes) {
    const grid = document.getElementById('global-search-results');
    if (!grid) return;
    if (!Array.isArray(recipes)) {
        grid.innerHTML = '<p class="empty-sub">Server error. Please check your backend.</p>';
        return;
    }
    if (recipes.length === 0) {
        grid.innerHTML = '<p class="empty-sub">No recipes found matching your search.</p>';
        return;
    }
    grid.innerHTML = recipes.map(r => `
        <article class="recipe-card text-only-card" data-title="${r.title}" onclick="openRecipeTab(this.dataset.title)">
            <div class="card-body">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <p class="card-profile">GLOBAL DATABASE</p>
                    <button class="card-heart ${r.saved ? 'saved' : ''}"
                            onclick="toggleSave(event, this)"
                            data-title="${r.title}"
                            style="position: static; width: 24px; height: 24px; font-size: 14px;">
                        ${r.saved ? '♥' : '♡'}
                    </button>
                </div>
                <h3 class="card-title">${r.title}</h3>
            </div>
        </article>
    `).join('');
}

function clearSearch() {
    const input = document.getElementById('search-input');
    if (input) input.value = '';
    const recommendsBtn = document.querySelector('.user-tab[onclick*="tab-recommends"]');
    switchTab('tab-recommends', recommendsBtn);
}


// ── RANDOMIZER ────────────────────────────────────────────────────────────────

async function randomRecipe() {
    const btn = document.getElementById('random-btn');
    if (btn) btn.style.transform = 'rotate(360deg)';
    try {
        const response = await fetch('/api/random_recipe');
        const data     = await response.json();
        if (data.title) openRecipeTab(data.title);
    } catch (error) {
        console.error("Could not fetch random recipe:", error);
    } finally {
        if (btn) setTimeout(() => btn.style.transform = 'none', 500);
    }
}


// ── HEART / SAVE ──────────────────────────────────────────────────────────────

function toggleSave(event, btn) {
    event.stopPropagation();
    event.preventDefault();

    const title   = btn.getAttribute('data-title');
    const profile = btn.getAttribute('data-profile') || "";
    const raw     = btn.getAttribute('data-matched');
    const matched = (raw && raw.trim() && raw !== "undefined") ? JSON.parse(raw) : [];
    const isSaved = btn.classList.contains('saved');

    btn.classList.toggle('saved', !isSaved);
    btn.innerHTML = isSaved ? '♡' : '♥';
    btn.title     = isSaved ? 'Save to Your Recipes' : 'Saved';

    if (!isSaved) {
        btn.style.transform = 'scale(1.4)';
        setTimeout(() => btn.style.transform = '', 200);
    }

    if (isSaved) {
        fetch('/unsave_recipe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        const card = btn.closest('.recipe-card');
        const tab  = card?.closest('.tab-content');
        if (tab && tab.id === 'tab-saved') {
            card.style.transition = 'opacity 0.3s';
            card.style.opacity    = '0';
            setTimeout(() => card.remove(), 300);
        }
    } else {
        fetch('/save_recipe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, profile, matched })
        });
    }
}


// ── BARCODE SCANNER ───────────────────────────────────────────────────────────

function openBarcodeModal() {
    document.getElementById('barcode-modal').style.display = 'flex';
}

function closeBarcodeModal() {
    document.getElementById('barcode-modal').style.display = 'none';
    document.getElementById('barcode-result').innerText = '';
    document.getElementById('barcode-file').value = '';
}

async function submitBarcode() {
    const file   = document.getElementById('barcode-file');
    const result = document.getElementById('barcode-result');
    if (!file.files.length) { result.innerText = 'Choose a photo first.'; return; }

    result.innerText   = 'Scanning...';
    result.style.color = '#888';

    const fd = new FormData();
    fd.append('barcode_image', file.files[0]);

    try {
        const r    = await fetch('/scan_barcode', { method: 'POST', body: fd });
        const data = await r.json();
        result.innerText   = data.message;
        result.style.color = data.success ? '#3D5A3E' : '#c0392b';
        if (data.success) setTimeout(() => { closeBarcodeModal(); location.reload(); }, 1500);
    } catch (e) {
        result.innerText   = 'Something went wrong.';
        result.style.color = '#c0392b';
    }
}
