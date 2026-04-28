// Lazy-loaded extras for js/flashcards.js — see js/flashcards.js bottom for
// the stub layer that triggers this dynamic import.
//
// Functions exported on `window` here overwrite the lazy stubs installed by
// core flashcards.js, so subsequent calls hit the real implementation
// directly. State (flashcards, currentIndex, currentUser, etc.) and helpers
// like flagWord come through the globalThis proxy installed by state.js /
// auth.js — no imports needed.

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
window.showCardMetaPopover = showCardMetaPopover;
window.hideCardMetaPopover = hideCardMetaPopover;
window.toggleCardMetaPopover = toggleCardMetaPopover;
window.refreshCardMetaPopoverIfOpen = refreshCardMetaPopoverIfOpen;
