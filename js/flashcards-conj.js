// Lazy-loaded conjugation table for js/flashcards.js. Loaded on first
// click of the conjugation toggle. The data cache (window._conjugationData)
// is populated by core's loadConjugationData on Spanish boot; this module
// reads it through globalThis.
//
// Render-on-toggle pattern: updateCard renders only an empty placeholder
// `<div id="conjugationTable" data-lemma="..." data-related="..." data-target="...">`
// for every verb card. The first time the user clicks the toggle, this
// module reads those data attributes, looks up the verb's paradigm, calls
// buildConjugationTableHTML, and injects the result into the placeholder.
// The built panel is cached by (ownerLemma, targetWord, isRelatedParadigm)
// so re-opening the same card's panel skips the rebuild — and so does
// re-opening a sibling card with the same lemma but different target form
// (e.g. "soy" → "eres" for ser). Cards are torn down on every updateCard,
// so the cache lives in this module's scope, not on the DOM.

const CONJ_PRONOUNS_FULL = ['yo', 'tú', 'él / ella', 'nosotros', 'vosotros', 'ellos / ellas'];

// Tense → mood mapping. Tenses we currently ship are just the first six;
// the Imperative + compound entries are scaffolded so future data slots in
// without a renderer change. Unknown tenses fall under "Other".
//
// Mood keys are display labels (English). Tense keys must match the Spanish
// labels in `conjEntry.tenses` (the conjugation data is keyed by Spanish
// tense names from verbecc). `CONJ_TENSE_DISPLAY` below maps each Spanish
// key to a short English label for the toggle buttons.
const CONJ_MOOD_GROUPS = {
    'Indicative': {
        tenses: ['Presente', 'Pretérito', 'Imperfecto', 'Futuro', 'Condicional'],
        accent: 'rgba(74, 158, 255, 0.6)',   // blue
    },
    'Subjunctive': {
        tenses: ['Subj. Presente', 'Subj. Imperfecto', 'Subj. Futuro'],
        accent: 'rgba(168, 85, 247, 0.6)',   // purple
    },
    'Imperative': {
        tenses: ['Imperativo', 'Imp. Negativo'],
        accent: 'rgba(236, 72, 153, 0.6)',   // pink
    },
};
const CONJ_MOOD_ORDER = ['Indicative', 'Subjunctive', 'Imperative'];

const CONJ_TENSE_DISPLAY = {
    'Presente': 'pres',
    'Pretérito': 'pret',
    'Imperfecto': 'imperf',
    'Futuro': 'fut',
    'Condicional': 'cond',
    'Subj. Presente': 'pres',
    'Subj. Imperfecto': 'imperf',
    'Subj. Futuro': 'fut',
    'Imperativo': 'affirm',
    'Imp. Negativo': 'neg',
};

// Built-panel HTML cache, keyed by `${ownerLemma}::${targetWord}::${isRelated}`.
// targetWord is part of the key because buildConjugationTableHTML picks the
// default open-tense based on which tense contains targetWord, AND highlights
// individual cells where form === targetWord — two cards sharing lemma but
// different target forms need different built HTML.
const _builtPanelCache = new Map();

// Split a form into (stem, ending) using longest-common-prefix vs the
// infinitive's STEM (infinitive minus the -ar/-er/-ir ending). For regular
// verbs this gives the expected pattern ("habl|o", "habl|as", "habl|a"...).
// For stem-changing irregulars the shared prefix stops earlier, so more
// of the word lands in the accent-colored "ending" span — which surfaces
// the stem change (e.g. "t|engo" from "tener", showing only the "t" as
// the preserved stem).
//
// Using the full infinitive as the reference was wrong: the "a" in the
// middle of "hablar" matched the "a" ending of "habla", stealing it into
// the stem.
function splitStemEnding(form, infinitive) {
    if (!form) return { stem: '', ending: '' };
    const src = (infinitive || '').toLowerCase();
    const dst = form.toLowerCase();
    // Spanish infinitives always end in -ar / -er / -ir. Strip those two
    // chars to get the stem reference; fall back to the full infinitive if
    // it's shorter than 2 chars (defensive — shouldn't happen in practice).
    const stemLen = src.length >= 2 ? src.length - 2 : src.length;
    let i = 0;
    while (i < stemLen && i < dst.length && src[i] === dst[i]) i++;
    return { stem: form.slice(0, i), ending: form.slice(i) };
}

function buildConjugationTableHTML(conjEntry, targetWord, lemma, opts) {
    opts = opts || {};
    const relatedLemma = opts.relatedLemma || null;
    const isRelatedParadigm = !!opts.isRelatedParadigm;

    // No inline data (conjEntry absent or empty): render a small
    // "no-data" panel with the card's own lemma + a prominent SpanishDict
    // link. If the card has a `relatedLemma` pointer (SpanishDict flagged
    // it as a conjugation of another verb), surface that relationship so
    // the user knows where to go for the paradigm.
    const hasData = conjEntry && Object.keys(conjEntry.tenses || {}).length > 0;
    if (!hasData) {
        const displayLemma = (lemma || targetWord || '').toLowerCase();
        const sdTarget = relatedLemma || displayLemma;
        const sdUrl = `https://www.spanishdict.com/conjugate/${encodeURIComponent(sdTarget)}`;
        const emptyMsg = relatedLemma
            ? `<strong>${displayLemma}</strong> is a lexicalised form related to <strong>${relatedLemma}</strong>. We don't have its conjugation inline.`
            : `No conjugation data available for this verb.`;
        const sdLabel = relatedLemma
            ? `Conjugate ${relatedLemma} on SpanishDict`
            : `Conjugate on SpanishDict`;
        return `
            <div id="conjugationTable" class="conjugation-panel">
                <button class="conj-close-btn" onclick="toggleConjugationTable()" aria-label="Close">&times;</button>
                <div class="conj-header">
                    <div class="conj-title">
                        <span class="conj-infinitive">${displayLemma}</span>
                    </div>
                </div>
                <div class="conj-empty-msg">
                    ${emptyMsg}
                </div>
                <a href="${sdUrl}" target="_blank" class="conj-sd-link conj-sd-link-prominent" title="${sdLabel}">
                    <img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="18" height="18" alt="" style="border-radius:3px">
                    <span>${sdLabel}</span>
                </a>
            </div>
        `;
    }
    const tenses = conjEntry.tenses;
    const tenseNames = Object.keys(tenses);
    const targetLower = targetWord.toLowerCase();
    // Prefer an explicit infinitive on the conj entry; fall back to
    // the lemma (or relatedLemma when we're rendering a related
    // verb's paradigm), then targetWord as a last resort.
    const conjOwnerLemma = isRelatedParadigm ? (relatedLemma || lemma || targetWord || '') : (lemma || targetWord || '');
    const infinitive = (conjEntry.infinitive || conjOwnerLemma).toLowerCase();

    // Pick the tense containing targetWord as the default; Presente otherwise.
    let defaultTense = tenses['Presente'] ? 'Presente' : tenseNames[0];
    for (const [tenseName, forms] of Object.entries(tenses)) {
        if (forms.some(f => f.toLowerCase() === targetLower)) {
            defaultTense = tenseName;
            break;
        }
    }

    // Group tenses by mood (Indicativo / Subjuntivo / Imperativo / Otras).
    // Tenses not covered by the known groups slot under "Otras" so the UI
    // never drops data on the floor.
    const grouped = [];
    const seen = new Set();
    for (const moodName of CONJ_MOOD_ORDER) {
        const cfg = CONJ_MOOD_GROUPS[moodName];
        const present = cfg.tenses.filter(t => tenses[t]);
        if (!present.length) continue;
        grouped.push({ mood: moodName, accent: cfg.accent, tenses: present });
        present.forEach(t => seen.add(t));
    }
    const orphanTenses = tenseNames.filter(t => !seen.has(t));
    if (orphanTenses.length) {
        grouped.push({ mood: 'Other', accent: 'rgba(255,255,255,0.3)', tenses: orphanTenses });
    }

    // The mood that owns the default tense is the one we open on.
    const defaultMood = (grouped.find(g => g.tenses.includes(defaultTense)) || grouped[0] || {}).mood;

    // Mood toggle — segmented control, rendered only when more than one
    // mood is present. When there's just one (e.g. only Indicativo tenses
    // shipped), the toggle is redundant and hidden.
    const moodToggleHTML = grouped.length > 1 ? `
        <div class="conj-mood-toggle">
            ${grouped.map(g => {
                const active = g.mood === defaultMood ? ' conj-mood-toggle-active' : '';
                return `<button class="conj-mood-toggle-btn${active}" data-mood="${g.mood}" style="--mood-accent: ${g.accent};" onclick="switchConjMood('${g.mood}')">${g.mood}</button>`;
            }).join('')}
        </div>` : '';

    // One tense-toggle row per mood; only the active mood's row is
    // visible (display toggled by switchConjMood). This keeps the tense
    // list to a single horizontal row instead of stacking a label +
    // buttons for every mood.
    //
    // The hide-inactive-rows logic merges into one style attribute:
    // putting `display:none` in a second `style` silently drops it
    // (browsers take the first `style` attribute only), which is why
    // subjunctive tenses were showing at initial render.
    const tenseToggleHTML = grouped.map(g => {
        const isActiveMood = g.mood === defaultMood;
        const styleStr = `--mood-accent: ${g.accent};${isActiveMood ? '' : ' display: none;'}`;
        const btns = g.tenses.map(t => {
            const active = t === defaultTense ? ' conj-tense-active' : '';
            const display = CONJ_TENSE_DISPLAY[t] || t;
            return `<button class="conj-tense-btn${active}" data-tense="${t}" onclick="switchConjTense('${t}')">${display}</button>`;
        }).join('');
        return `<div class="conj-tense-toggle" data-mood="${g.mood}" style="${styleStr}">${btns}</div>`;
    }).join('');

    // Per-tense table. Each form is split stem/ending so the pattern pops.
    let tenseTables = '';
    for (const [tenseName, forms] of Object.entries(tenses)) {
        const hidden = tenseName !== defaultTense ? ' style="display:none"' : '';
        let rows = '';
        for (let i = 0; i < forms.length; i++) {
            const form = forms[i];
            const isActive = form.toLowerCase() === targetLower;
            const cls = isActive ? ' conj-active' : '';
            const { stem, ending } = splitStemEnding(form, infinitive);
            // Stem is muted; ending is accent-colored — makes regular
            // patterns rhyme and irregular stems stand out.
            const formHTML = stem
                ? `<span class="conj-stem">${stem}</span><span class="conj-ending">${ending}</span>`
                : `<span class="conj-ending conj-ending-full">${ending}</span>`;
            rows += `<tr class="${cls}"><td class="conj-pronoun">${CONJ_PRONOUNS_FULL[i]}</td><td class="conj-form">${formHTML}</td></tr>`;
        }
        tenseTables += `<table class="conj-table" data-tense="${tenseName}"${hidden}>${rows}</table>`;
    }

    // --- Header block ---
    // Infinitive + translation on top; -ar/-er/-ir type badge on the right;
    // non-finite forms (gerund + past participle) pinned underneath so
    // they're visible regardless of which tense is currently showing.
    const infEnd = infinitive.slice(-2).toUpperCase();
    const typeBadge = ['AR', 'ER', 'IR'].includes(infEnd)
        ? `<span class="conj-type-badge">-${infEnd}</span>`
        : '';
    const translation = conjEntry.translation || '';
    const gerActive = conjEntry.gerund && conjEntry.gerund.toLowerCase() === targetLower ? ' is-active' : '';
    const ppActive = conjEntry.past_participle && conjEntry.past_participle.toLowerCase() === targetLower ? ' is-active' : '';
    const nonFiniteHTML = (conjEntry.gerund || conjEntry.past_participle) ? `
        <div class="conj-nonfinite">
            ${conjEntry.gerund ? `<div class="conj-nf-item${gerActive}">
                <span class="conj-nf-label">gerund</span>
                <span class="conj-nf-form">${conjEntry.gerund}</span>
            </div>` : ''}
            ${conjEntry.past_participle ? `<div class="conj-nf-item${ppActive}">
                <span class="conj-nf-label">past participle</span>
                <span class="conj-nf-form">${conjEntry.past_participle}</span>
            </div>` : ''}
        </div>` : '';

    // Link to SpanishDict's full paradigm page — the in-app panel covers
    // the high-frequency tenses; this covers "I want to see every tense
    // incl. compound + imperative forms we don't ship locally".
    const sdUrl = `https://www.spanishdict.com/conjugate/${encodeURIComponent(infinitive)}`;
    const sdLinkHTML = `
        <a href="${sdUrl}" target="_blank" class="conj-sd-link" title="Full paradigm on SpanishDict">
            <img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="16" height="16" alt="" style="border-radius:3px">
            <span>Full paradigm on SpanishDict</span>
        </a>`;

    // When we're rendering a related verb's paradigm (e.g. haber for a
    // hay card), add a note above the header so the user knows the
    // table isn't the card's own verb. Keeps the panel honest: the
    // paradigm belongs to the related verb, not the lexicalised word
    // on the card.
    const relatedNoteHTML = isRelatedParadigm && lemma && relatedLemma ? `
        <div class="conj-related-note">
            <strong>${lemma.toLowerCase()}</strong> is a lexicalised form related to <strong>${relatedLemma.toLowerCase()}</strong>. Showing <strong>${relatedLemma.toLowerCase()}</strong>'s full paradigm below.
        </div>` : '';

    return `
        <div id="conjugationTable" class="conjugation-panel">
            <button class="conj-close-btn" onclick="toggleConjugationTable()" aria-label="Close">&times;</button>
            ${relatedNoteHTML}
            <div class="conj-header">
                <div class="conj-title">
                    <span class="conj-infinitive">${infinitive}</span>
                    ${typeBadge}
                </div>
                ${translation ? `<div class="conj-translation">${translation}</div>` : ''}
                ${nonFiniteHTML}
            </div>
            ${moodToggleHTML}
            <div class="conj-tense-toggles">
                ${tenseToggleHTML}
            </div>
            <div class="conj-tables-wrap">
                ${tenseTables}
            </div>
            ${sdLinkHTML}
        </div>
    `;
}

function switchConjTense(tenseName) {
    const panel = document.getElementById('conjugationTable');
    if (!panel) return;
    // Match tables + buttons by data-tense (button text now has the
    // "Subj."/"Imp." prefix stripped for display under the mood label, so
    // text-based matching no longer works).
    panel.querySelectorAll('.conj-table').forEach(t => {
        t.style.display = t.dataset.tense === tenseName ? '' : 'none';
    });
    panel.querySelectorAll('.conj-tense-btn').forEach(b => {
        b.classList.toggle('conj-tense-active', b.dataset.tense === tenseName);
    });
}

function switchConjMood(moodName) {
    const panel = document.getElementById('conjugationTable');
    if (!panel) return;
    // Swap mood-toggle active state.
    panel.querySelectorAll('.conj-mood-toggle-btn').forEach(b => {
        b.classList.toggle('conj-mood-toggle-active', b.dataset.mood === moodName);
    });
    // Show only the active mood's tense-toggle row.
    panel.querySelectorAll('.conj-tense-toggle').forEach(t => {
        t.style.display = t.dataset.mood === moodName ? '' : 'none';
    });
    // Switch the visible tense to the mood's first (or already-active) one.
    const activeRow = panel.querySelector(`.conj-tense-toggle[data-mood="${moodName}"]`);
    if (activeRow) {
        const active = activeRow.querySelector('.conj-tense-active') || activeRow.querySelector('.conj-tense-btn');
        if (active) switchConjTense(active.dataset.tense);
    }
}

// Render-on-toggle. The placeholder (rendered by core's updateCard) is an
// empty #conjugationTable div carrying data-lemma / data-related /
// data-target attributes. First open builds the panel from those attrs +
// window._conjugationData, caches the inner HTML by (lemma, target,
// isRelated), and slides the panel in. Subsequent opens of the same panel
// (without a card change) are pure CSS toggle. Card changes blow away the
// DOM, so the next open hits the cache and rebuilds-from-cache instead of
// re-running the templating.
async function toggleConjugationTable() {
    const panel = document.getElementById('conjugationTable');
    if (!panel) return;
    if (panel.classList.contains('visible')) {
        panel.classList.remove('visible');
        return;
    }
    if (!panel.firstChild) {
        // Defensive: a fast click on a verb card before the boot-time
        // prefetch completes should wait for the in-flight load instead
        // of rendering an empty cache as "no data". loadConjugationData
        // returns the in-flight promise so concurrent callers share it.
        if (typeof window.loadConjugationData === 'function') {
            await window.loadConjugationData();
        }
        const lemma = panel.dataset.lemma || '';
        const related = panel.dataset.related || '';
        const target = panel.dataset.target || '';
        const data = window._conjugationData;
        let conjEntry = null;
        let isRelated = false;
        if (data) {
            if (data[lemma]) {
                conjEntry = data[lemma];
            } else if (related && data[related]) {
                conjEntry = data[related];
                isRelated = true;
            }
        }
        const ownerLemma = isRelated ? (related || lemma) : lemma;
        const cacheKey = `${ownerLemma}::${target}::${isRelated ? 1 : 0}`;
        let inner = _builtPanelCache.get(cacheKey);
        if (inner == null) {
            const fullHtml = buildConjugationTableHTML(conjEntry, target, lemma,
                { relatedLemma: related, isRelatedParadigm: isRelated });
            // buildConjugationTableHTML returns a wrapper `<div id="conjugationTable">…</div>`.
            // The existing placeholder IS the #conjugationTable element — strip the
            // wrapper and inject just the inner content so we don't nest divs.
            const wrapper = document.createElement('div');
            wrapper.innerHTML = fullHtml;
            const built = wrapper.firstElementChild;
            inner = built ? built.innerHTML : fullHtml;
            _builtPanelCache.set(cacheKey, inner);
        }
        panel.innerHTML = inner;
    }
    // requestAnimationFrame guards against browsers optimising away the
    // slide-in transition on a freshly-injected node (no committed layout
    // means the transition's "from" state isn't observed).
    requestAnimationFrame(() => panel.classList.add('visible'));
}

window.toggleConjugationTable = toggleConjugationTable;
window.switchConjMood = switchConjMood;
window.switchConjTense = switchConjTense;
