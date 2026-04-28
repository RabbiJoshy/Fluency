// Lazy-loaded extras for js/flashcards.js — see js/flashcards.js bottom for
// the stub layer that triggers this dynamic import.
//
// Functions exported on `window` here overwrite the lazy stubs installed by
// core flashcards.js, so subsequent calls hit the real implementation
// directly. State (flashcards, currentIndex, currentUser, etc.) and helpers
// like flagWord and getPosColorClass come through the globalThis proxy
// installed by state.js / auth.js / flashcards.js — no imports needed.

// ---------------------------------------------------------------------------
// Part-of-speech popup
// ---------------------------------------------------------------------------

// Part-of-speech lookup shown when a user taps the POS pill on a sense
// row. Full name + one-sentence plain-language description targeted at
// language learners, not grammarians. Keys match the UPOS / Kaikki POS
// values produced by the pipeline (see util_5c_sense_menu_format.py
// and util_5c_spanishdict.py).
const POS_INFO = {
    NOUN: { name: "Noun",
            description: "Names a person, place, thing, or idea (e.g. casa, amor, tiempo)." },
    VERB: { name: "Verb",
            description: "An action, state, or occurrence (e.g. correr, ser, tener)." },
    ADJ:  { name: "Adjective",
            description: "Describes or modifies a noun (e.g. grande, feliz, rápido)." },
    ADV:  { name: "Adverb",
            description: "Modifies a verb, adjective, or another adverb (e.g. rápidamente, muy, siempre)." },
    ADP:  { name: "Preposition",
            description: "Shows a relationship between words — usually place, time, or direction (e.g. a, de, en, con)." },
    DET:  { name: "Determiner",
            description: "Introduces or specifies a noun (e.g. el, una, este, mi)." },
    PRON: { name: "Pronoun",
            description: "Replaces a noun (e.g. él, ella, esto, nosotros)." },
    CCONJ: { name: "Conjunction",
             description: "Connects words, phrases, or clauses (e.g. y, pero, o, porque)." },
    SCONJ: { name: "Conjunction",
             description: "Introduces a subordinate clause (e.g. si, cuando, aunque)." },
    INTJ: { name: "Interjection",
            description: "An exclamation or sudden expression of emotion (e.g. ¡ay!, ¡oh!, ¡vale!)." },
    NUM:  { name: "Number",
            description: "Expresses a quantity or order (e.g. uno, dos, primero)." },
    PART: { name: "Particle",
            description: "A small grammatical marker with a specific role — doesn't always translate cleanly (e.g. no, sí, se)." },
    PROPN: { name: "Proper Noun",
             description: "The specific name of a person, place, or thing (e.g. María, Madrid, Spotify)." },
    PHRASE: { name: "Phrase",
              description: "A fixed group of words that function together (e.g. por favor, sin embargo)." },
    CONTRACTION: { name: "Contraction",
                   description: "Two words fused together into one written form (e.g. al = a + el, del = de + el, c'est = ce + est)." },
    X:    { name: "Unclassified",
            description: "Part of speech couldn't be determined for this sense." },
};

// Show an info popover describing a part of speech. The pill is tappable;
// a tap on the pill opens a full-screen semi-transparent overlay holding
// a small card with the POS name + description. If a percentage is
// passed and is a real sub-100 frequency, the popover also explains
// what that percentage means. Any subsequent click (or Escape) closes
// the overlay. The pill's own click stops propagation so the row's
// selectMeaning handler doesn't also fire.
function showPOSInfo(event, pos, pct) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const info = POS_INFO[pos] || {
        name: pos || "Unknown",
        description: "No description available for this part of speech.",
    };
    // Show the percentage-explainer only when a meaningful pct was
    // passed: integer between 1 and 99. 100% / missing / zero means
    // there's nothing to explain (either implicit or irrelevant).
    const pctNum = Number(pct);
    const showPct = Number.isFinite(pctNum) && pctNum > 0 && pctNum < 100;
    const pctSection = showPct ? `
            <div class="pos-info-divider"></div>
            <div class="pos-info-pct-label">Frequency on this card</div>
            <div class="pos-info-pct-value">${pctNum}%</div>
            <div class="pos-info-pct-description">
                Of the example sentences we have for this word, about
                ${pctNum}% use this meaning. The other ${100 - pctNum}%
                split between the other meanings shown on the card.
            </div>
    ` : '';
    const overlay = document.createElement('div');
    overlay.className = 'pos-info-overlay';
    // Inline the popover's colour accent so it matches the pill that
    // was tapped — the .pos-* classes on the pill carry the colour;
    // mirror them on the popover so the pairing is obvious.
    const posColorClass = getPosColorClass(pos) || '';
    overlay.innerHTML = `
        <div class="pos-info-popover ${posColorClass}" role="dialog" aria-label="${info.name}">
            <div class="pos-info-name">${info.name}</div>
            <div class="pos-info-description">${info.description}</div>
            ${pctSection}
            <div class="pos-info-hint">Tap anywhere to close</div>
        </div>
    `;
    document.body.appendChild(overlay);
    const close = () => {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    // Any click on the overlay (including the popover) closes. The user
    // asked for "press anywhere to close" — pairs cleanly with the
    // one-glance nature of the info.
    overlay.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
}

// ---------------------------------------------------------------------------
// Card metadata popover (debug info — per-sense source + per-example method)
// ---------------------------------------------------------------------------

function _escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

function _renderCardMetaBody(card) {
    if (!card) return '<div class="card-meta-empty">No card selected.</div>';
    const showFlags = !!(currentUser && !currentUser.isGuest && currentUser.initials === 'JST');
    const flagBtn = (path, value) => showFlags
        ? `<button class="card-meta-flag-row" type="button" data-path="${_escapeHtml(path)}" data-value="${_escapeHtml(value == null ? '' : String(value))}" title="Flag this field">flag</button>`
        : '';

    const lines = [];
    const id = card.fullId || card.id || '';
    lines.push('<div class="card-meta-section">');
    lines.push('<dl class="card-meta-kv">');
    const wordVal = card.targetWord || card.word || '';
    lines.push(`<dt>word</dt><dd>${_escapeHtml(wordVal)}${flagBtn('word', wordVal)}</dd>`);
    if (card.lemma && card.lemma !== wordVal) {
        lines.push(`<dt>lemma</dt><dd>${_escapeHtml(card.lemma)}${flagBtn('lemma', card.lemma)}</dd>`);
    }
    if (id) lines.push(`<dt>id</dt><dd>${_escapeHtml(id)}</dd>`);
    if (card.rank) lines.push(`<dt>rank</dt><dd>${_escapeHtml(card.rank)}</dd>`);
    if (card.corpusCount != null) lines.push(`<dt>corpus</dt><dd>${_escapeHtml(card.corpusCount)}</dd>`);
    lines.push('</dl></div>');

    const meanings = card.meanings || [];
    lines.push('<div class="card-meta-section"><h4>Meanings</h4>');
    if (!meanings.length) {
        lines.push('<div class="card-meta-empty">No meanings.</div>');
    } else {
        lines.push('<ul class="card-meta-list">');
        meanings.forEach((m, i) => {
            const isCurrent = (typeof currentMeaningIndex === 'number' && i === currentMeaningIndex);
            const tags = [];
            if (m.source) tags.push(`<span class="card-meta-tag source">src: ${_escapeHtml(m.source)}</span>`);
            if (m.assignment_method) tags.push(`<span class="card-meta-tag method">m: ${_escapeHtml(m.assignment_method)}</span>`);
            if (m.unassigned) tags.push('<span class="card-meta-tag flag">unassigned</span>');
            if (m.pos === 'SENSE_CYCLE') tags.push('<span class="card-meta-tag flag">SENSE_CYCLE</span>');
            const pctText = (typeof m.percentage === 'number') ? (m.percentage * 100).toFixed(0) + '%' : '';
            const meaningText = m.meaning || m.translation || '';
            const label = `${_escapeHtml(m.pos || '?')} · ${_escapeHtml(meaningText)}${pctText ? ' · ' + pctText : ''}`;
            lines.push(`<li${isCurrent ? ' class="card-meta-current"' : ''}>${label}${flagBtn(`sense:${i}`, meaningText)}<div>${tags.join(' ') || '<span class="card-meta-empty">no tags</span>'}</div></li>`);
        });
        lines.push('</ul>');
    }
    lines.push('</div>');

    // Per-example methods for the currently displayed meaning.
    const curMeaning = meanings[currentMeaningIndex] || meanings[0];
    const exs = (curMeaning && curMeaning.allExamples) || [];
    const senseIdx = (typeof currentMeaningIndex === 'number') ? currentMeaningIndex : 0;
    lines.push('<div class="card-meta-section"><h4>Examples (current meaning)</h4>');
    if (!exs.length) {
        lines.push('<div class="card-meta-empty">No examples.</div>');
    } else {
        lines.push('<ul class="card-meta-list">');
        exs.forEach((ex, i) => {
            const isCurrent = (typeof currentExampleIndex === 'number' && i === (currentExampleIndex % exs.length));
            const method = ex.assignment_method ? `<span class="card-meta-tag method">m: ${_escapeHtml(ex.assignment_method)}</span>` : '<span class="card-meta-empty">no method</span>';
            const tsrc = ex.translation_source ? `<span class="card-meta-tag source">t: ${_escapeHtml(ex.translation_source)}</span>` : '';
            const spanish = ex.spanish || ex.targetSentence || ex.original || '';
            lines.push(`<li${isCurrent ? ' class="card-meta-current"' : ''}>${method} ${tsrc}${flagBtn(`example:${senseIdx}:${i}`, spanish)}<div class="card-meta-ex">${_escapeHtml(spanish)}</div></li>`);
        });
        lines.push('</ul>');
    }
    lines.push('</div>');

    return lines.join('');
}

function showCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    const body = document.getElementById('cardMetaBody');
    const title = document.getElementById('cardMetaTitle');
    const footer = document.getElementById('cardMetaFooter');
    if (!pop || !body) return;
    const card = (typeof flashcards !== 'undefined' && flashcards) ? flashcards[currentIndex] : null;
    if (title) title.textContent = card ? `${card.targetWord || card.word || 'Card'} — info` : 'Card info';
    body.innerHTML = _renderCardMetaBody(card);
    body.querySelectorAll('.card-meta-flag-row').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const path = btn.dataset.path;
            const value = btn.dataset.value;
            if (card && typeof flagWord === 'function') flagWord(card, path, value);
            btn.classList.add('flagged');
        });
    });
    if (footer) {
        const showFlagBtn = !!(currentUser && !currentUser.isGuest && currentUser.initials === 'JST');
        footer.style.display = showFlagBtn ? '' : 'none';
    }
    pop.hidden = false;
    pop.setAttribute('aria-hidden', 'false');
}

function hideCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop) return;
    pop.hidden = true;
    pop.setAttribute('aria-hidden', 'true');
}

function toggleCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop) return;
    if (pop.hidden) showCardMetaPopover();
    else hideCardMetaPopover();
}

function refreshCardMetaPopoverIfOpen() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop || pop.hidden) return;
    showCardMetaPopover();
}

// Close button + outside-click dismiss + flag button. The toggle button
// (#cardMetaBtn) is wired by core flashcards.js's _initCardMetaButton IIFE,
// which calls window.toggleCardMetaPopover() — i.e. the lazy stub that
// triggered this module's load. Handlers here only matter when the popover
// is OPEN, which can only happen after this module has loaded, so attaching
// at module-load time is correct.
(function _initCardMetaPopoverInternals() {
    const pop = document.getElementById('cardMetaPopover');
    const closeBtn = document.getElementById('cardMetaClose');
    const flagBtn = document.getElementById('cardMetaFlagBtn');
    const content = document.getElementById('cardMetaContent');
    const btn = document.getElementById('cardMetaBtn');
    if (!pop) return;
    if (closeBtn) closeBtn.addEventListener('click', hideCardMetaPopover);
    if (flagBtn) {
        flagBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const card = (typeof flashcards !== 'undefined' && flashcards) ? flashcards[currentIndex] : null;
            if (card && typeof flagWord === 'function') flagWord(card);
            hideCardMetaPopover();
        });
    }
    document.addEventListener('click', (e) => {
        if (pop.hidden) return;
        if ((content && content.contains(e.target)) || (btn && btn.contains(e.target))) return;
        hideCardMetaPopover();
    });
})();

// Window exports — the lazy stubs in core flashcards.js look these up after
// the dynamic import resolves. The stub layer's post-resolve check verifies
// each name was reassigned to the real function (otherwise it would recurse
// into itself, since the stub is also on window).
window.showPOSInfo = showPOSInfo;
window.showCardMetaPopover = showCardMetaPopover;
window.hideCardMetaPopover = hideCardMetaPopover;
window.toggleCardMetaPopover = toggleCardMetaPopover;
window.refreshCardMetaPopoverIfOpen = refreshCardMetaPopoverIfOpen;
