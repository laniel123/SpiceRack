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
    const btn = event.currentTarget;
    fetch('/toggle_spice_favorite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spice_id: spiceId })
    })
    .then(() => {
        const isFav = btn.classList.contains('saved');
        btn.classList.toggle('saved', !isFav);
        btn.textContent = isFav ? '♡' : '♥';
    })
    .catch(err => console.error('toggleSpiceFav error:', err));
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
        const counter = document.getElementById('rec-count');
        if (counter) counter.textContent = '0';
        return;
    }

    grid.innerHTML = recipes.map(r => {
        const scoreHtml = r.score > 0
            ? `<span class="card-score">${Math.round(r.score * 100)}%</span>` : '';
        const heartClass = r.saved ? 'card-heart saved' : 'card-heart';
        const heartChar  = r.saved ? '♥' : '♡';
        const matchedEsc = JSON.stringify(r.matched).replace(/'/g, '&#39;');
        const titleEsc   = r.title.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const profileEsc = (r.profile || '').replace(/"/g, '&quot;');

        const photoHtml = r.image
            ? `<div class="card-photo" style="background-image:url('${r.image}')">
                <div class="card-photo-overlay"></div>
                ${scoreHtml}
                <button class="${heartClass}"
                    data-title="${titleEsc}"
                    data-profile="${profileEsc}"
                    data-matched='${matchedEsc}'
                    onclick="toggleSave(event, this)">${heartChar}</button>
               </div>`
            : `<div class="card-photo card-photo-empty">
                <div class="card-photo-overlay"></div>
                ${scoreHtml}
                <button class="${heartClass}"
                    data-title="${titleEsc}"
                    data-profile="${profileEsc}"
                    data-matched='${matchedEsc}'
                    onclick="toggleSave(event, this)">${heartChar}</button>
                <span class="card-placeholder-icon">🌶</span>
               </div>`;

        const courseHtml = (r.course && r.course !== 'nan' && r.course !== 'Other/Miscellaneous')
            ? `<span class="chip-course">${r.course}</span>` : '';
        const dietsHtml = (r.diets || []).slice(0, 3)
            .map(d => `<span class="chip-diet">${d}</span>`).join('');
        const metaHtml = (courseHtml || dietsHtml)
            ? `<div class="card-meta">${courseHtml}${dietsHtml}</div>` : '';

        const matchedChips = (r.matched || [])
            .map(s => s.trim() ? `<span class="chip-matched">${s.trim()}</span>` : '').join('');
        const missingChips = (r.missing || []).slice(0, 2)
            .map(s => s.trim() ? `<span class="chip-missing">${s.trim()}</span>` : '').join('');
        const spiceChipsHtml = (matchedChips || missingChips)
            ? `<div class="spice-chips">${matchedChips}${missingChips}</div>` : '';

        return `
        <article class="recipe-card" data-title="${titleEsc}" onclick="openRecipeTab(this.dataset.title)">
            ${photoHtml}
            <div class="card-body">
                <h3 class="recipe-title" data-title="${titleEsc}"
                    onclick="event.stopPropagation(); openRecipeTab('${titleEsc}')">
                    ${r.title}
                </h3>
                ${metaHtml}
                ${spiceChipsHtml}
            </div>
        </article>`;
    }).join('');

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

function renderSuggestions(suggestions) {
    const container = document.querySelector('.unlock-chips');
    const section = document.querySelector('.unlock-section');
    if (!container) return;

    // Hide the section if there are no suggestions
    if (!suggestions || suggestions.length === 0) {
        if (section) section.style.display = 'none';
        return;
    }

    // Show section and render chips
    if (section) section.style.display = 'flex';
    container.innerHTML = suggestions.map(([name, count]) => `
        <span class="unlock-chip">${name} <em>+${count}</em></span>
    `).join('');
}

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

// Intercept spice add form — AJAX instead of full page submit
document.addEventListener('DOMContentLoaded', () => {

    // Intercept spice form — prevent native POST
    const addForm = document.getElementById('spice-form');
    if (addForm) {
        addForm.addEventListener('submit', function(e) {
            e.preventDefault();
            e.stopPropagation();
            handleSpiceAdd();
        });
    }

    // Filter checkboxes
    document.querySelectorAll('input[name="pref"], input[name="course_pref"]').forEach(cb => {
        cb.addEventListener('change', () => {
            clearTimeout(filterTimer);
            filterTimer = setTimeout(applyFilters, 300);
        });
    });

    // Search input
    // Inside the DOMContentLoaded listener in script.js
const searchInput = document.getElementById('search-input');
if (searchInput) {
    searchInput.addEventListener('input', function() {
        const query = this.value.trim();
        clearTimeout(searchTimer);
        if (query.length < 2) return;

        searchTimer = setTimeout(async () => {
            try {
                // Gather currently checked filters
                const prefs = Array.from(document.querySelectorAll('input[name="pref"]:checked'))
                                   .map(i => `pref=${encodeURIComponent(i.value)}`);
                const courses = Array.from(document.querySelectorAll('input[name="course_pref"]:checked'))
                                     .map(i => `course_pref=${encodeURIComponent(i.value)}`);
                
                const filterQuery = [...prefs, ...courses].join('&');
                const url = `/api/search?q=${encodeURIComponent(query)}&${filterQuery}`;

                const response = await fetch(url);
                const recipes  = await response.json();
                renderSearchResults(recipes);
            } catch (error) {
                console.error("Search failed:", error);
            }
        }, 400);
    });
}

});

function renderSearchResults(recipes) {
    const grid = document.getElementById('global-search-results');
    if (!grid) return;

    // 1. CLEAR AND RENDER THE DATA
    if (!Array.isArray(recipes)) {
        grid.innerHTML = '<p class="empty-sub">Server error. Please check your backend.</p>';
        return;
    }
    if (recipes.length === 0) {
        grid.innerHTML = '<p class="empty-sub">No recipes found matching your search.</p>';
    } else {
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

    // 2. TRIGGER THE TAB SWITCH
    // This finds your hidden search tab button and "clicks" it via code
    const searchTabBtn = document.getElementById('search-tab-button');
    switchTab('tab-search-all', searchTabBtn);
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

function showFlash(msg, type) {
    // Reuse whatever flash element your template already has, or create one
    let el = document.getElementById('flash-msg');
    if (!el) {
        el = document.createElement('div');
        el.id = 'flash-msg';
        el.style.cssText = 'position:fixed;top:16px;left:50%;transform:translateX(-50%);'
            + 'padding:8px 18px;border-radius:20px;font-size:13px;font-family:DM Sans,sans-serif;'
            + 'z-index:9999;pointer-events:none;transition:opacity 0.4s;';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.background = type === 'success' ? '#3D5A3E' : '#c0392b';
    el.style.color = '#fff';
    el.style.opacity = '1';
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.style.opacity = '0', 2800);
}

function renderSpiceList(spices) {
    const list = document.getElementById('spice-list');
    if (!list) return;

    // Clear ALL existing content first — prevents duplicates
    list.innerHTML = '';

    const badge = document.querySelector('.header-badge-num');
    if (badge) badge.textContent = spices.length;

    if (spices.length === 0) return;

    list.innerHTML = spices.map(s => `
        <li>
            <button class="x-btn" title="Remove ${s.name}"
                onclick="removeSpice(event, ${s.id})">×</button>
            <button class="spice-heart-btn ${s.is_favorite ? 'saved' : ''}"
                onclick="toggleSpiceFav(event, ${s.id})">${s.is_favorite ? '♥' : '♡'}</button>
            ${s.name}
        </li>
    `).join('');
}

async function removeSpice(event, spiceId) {
    event.preventDefault();
    event.stopPropagation();
    const resp = await fetch('/remove_spice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spice_id: spiceId })
    });
    const data = await resp.json();
    renderSpiceList(data.spices);

    // Fetch fresh suggestions based on updated pantry
    try {
        const suggestResp = await fetch('/api/suggestions');
        const suggestions = await suggestResp.json();
        renderSuggestions(suggestions);
    } catch (e) { /* suggestions are non-critical */ }

    applyFilters();
}

// ── SPICE PANEL (no-reload add / remove) ──────────────────────────────────────

function handleSpiceAdd() {
    const textarea = document.querySelector('#spice-form textarea[name="user_spice_add"]');
    const val = textarea ? textarea.value.trim() : '';
    if (!val) return;

    const submitBox = document.querySelector('.submit-box');
    if (submitBox) submitBox.style.opacity = '0.5';

    fetch('/add_spices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spices: val })
    })
    .then(r => r.json())
    .then(data => {
        if (textarea) textarea.value = '';
        if (submitBox) submitBox.style.opacity = '1';
        if (data.accepted && data.accepted.length)
            showFlash('✓ Added: ' + data.accepted.join(', '), 'success');
        if (data.rejected && data.rejected.length)
            showFlash('✗ Not recognized: ' + data.rejected.join(', '), 'error');
        renderSpiceList(data.spices);
        if (data.suggestions) renderSuggestions(data.suggestions);
        applyFilters();
    })
    .catch(err => {
        if (submitBox) submitBox.style.opacity = '1';
        console.error('addSpices error:', err);
    });
}
