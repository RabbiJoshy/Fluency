// Granular sense / expression knowledge layered over whole-card progress.
// Whole-card answers are the baseline; only explicit row-level answers create
// ItemProgress records. The newest card-level or item-level event wins.
import './state.js?v=20260805h';
import { sendOrQueue } from './sync-queue.js?v=20260805h';

const KNOWLEDGE_SCHEMA_VERSION = 1;

let indexedItemProgressSource = null;
let indexedItemProgressSize = -1;
let itemProgressByParent = new Map();

function normalizeKnowledgeText(value) {
    return String(value || '')
        .normalize('NFKC')
        .trim()
        .toLowerCase()
        .replace(/\s+/g, ' ');
}

function hashKnowledgeSignature(value) {
    let hash = 0x811c9dc5;
    const text = String(value || '');
    for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

function makeKnowledgeItem(
    card,
    type,
    signature,
    label,
    meaningIndex,
    cycleIndex = 0,
    legacySignatures = []
) {
    const itemKey = `k${KNOWLEDGE_SCHEMA_VERSION}:${type}:${hashKnowledgeSignature(signature)}`;
    const legacyItemIds = legacySignatures
        .filter(Boolean)
        .map(legacySignature =>
            `${card.fullId}~k${KNOWLEDGE_SCHEMA_VERSION}:${type}:${hashKnowledgeSignature(legacySignature)}`)
        .filter(itemId => itemId !== `${card.fullId}~${itemKey}`);
    return {
        itemId: `${card.fullId}~${itemKey}`,
        legacyItemIds: Array.from(new Set(legacyItemIds)),
        itemKey,
        parentWordId: card.fullId,
        type,
        label: String(label || ''),
        meaningIndex,
        cycleIndex,
        schemaVersion: KNOWLEDGE_SCHEMA_VERSION
    };
}

function knowledgeItemsForMeaning(card, meaning, meaningIndex) {
    if (!meaning || meaning.exampleOnly) return [];
    if (meaning.allMWEs?.length) {
        return meaning.allMWEs.map((mwe, cycleIndex) => {
            const identity = normalizeKnowledgeText(mwe.id || mwe.family || mwe.expression);
            return {
                ...makeKnowledgeItem(
                    card,
                    'expression',
                    `expression|${identity}`,
                    mwe.expression || mwe.family || 'Expression',
                    meaningIndex,
                    cycleIndex
                ),
                detail: mwe.translation || '',
                pos: 'MWE'
            };
        });
    }
    if (meaning.allClitics?.length) {
        return meaning.allClitics.map((clitic, cycleIndex) => ({
            ...makeKnowledgeItem(
                card,
                'clitic',
                `clitic|${normalizeKnowledgeText(clitic.form)}`,
                clitic.form || 'Clitic form',
                meaningIndex,
                cycleIndex
            ),
            detail: clitic.translation || '',
            pos: 'CLITIC'
        }));
    }
    if (meaning.pos === 'SENSE_CYCLE' && meaning.allSenses?.length) {
        return meaning.allSenses.map((sense, cycleIndex) => {
            const pos = sense.pos || meaning.cycle_pos || 'X';
            const translation = sense.translation || meaning.meaning || '';
            const context = sense.context || '';
            const stableSenseId = sense.senseId || sense.sense_id || sense.id || '';
            const stableAliases = sense.senseIdAliases || sense.sense_id_aliases || [];
            const fallbackSignature = `sense|${normalizeKnowledgeText(pos)}|${normalizeKnowledgeText(translation)}|${normalizeKnowledgeText(context)}`;
            return {
                ...makeKnowledgeItem(
                    card,
                    'sense',
                    stableSenseId
                        ? `sense-id|${normalizeKnowledgeText(stableSenseId)}`
                        : fallbackSignature,
                    translation,
                    meaningIndex,
                    cycleIndex,
                    stableSenseId
                        ? [fallbackSignature, ...stableAliases.map(id => `sense-id|${normalizeKnowledgeText(id)}`)]
                        : []
                ),
                detail: context,
                pos
            };
        });
    }

    const pos = meaning.pos || 'X';
    const translation = meaning.meaning || meaning.translation || '';
    const context = meaning.context || '';
    const stableSenseId = meaning.senseId || meaning.sense_id || meaning.id || '';
    const stableAliases = meaning.senseIdAliases || meaning.sense_id_aliases || [];
    const fallbackSignature = `sense|${normalizeKnowledgeText(pos)}|${normalizeKnowledgeText(translation)}|${normalizeKnowledgeText(context)}`;
    return [{
        ...makeKnowledgeItem(
            card,
            'sense',
            stableSenseId
                ? `sense-id|${normalizeKnowledgeText(stableSenseId)}`
                : fallbackSignature,
            translation || pos,
            meaningIndex,
            0,
            stableSenseId
                ? [fallbackSignature, ...stableAliases.map(id => `sense-id|${normalizeKnowledgeText(id)}`)]
                : []
        ),
        detail: context,
        pos
    }];
}

function getCardKnowledgeItems(card) {
    if (!card?.fullId || !Array.isArray(card.meanings)) return [];
    const unique = new Map();
    card.meanings
        .flatMap((meaning, index) => knowledgeItemsForMeaning(card, meaning, index))
        .forEach(item => {
            // Identical sense content or the same durable pipeline sense ID can
            // legitimately appear in more than one rendered group. It remains
            // one learnable item rather than inflating the card summary.
            if (!unique.has(item.itemId)) unique.set(item.itemId, item);
        });
    return Array.from(unique.values());
}

function getActiveKnowledgeItems(card) {
    if (!card?.meanings?.length) return [];
    if (currentGroupSelection?.members?.length) {
        return currentGroupSelection.members.flatMap(index =>
            knowledgeItemsForMeaning(card, card.meanings[index], index));
    }
    const meaning = card.meanings[currentMeaningIndex];
    const items = knowledgeItemsForMeaning(card, meaning, currentMeaningIndex);
    if (items.length <= 1) return items;
    return [items[currentMWEIndex % items.length]];
}

function newestIso(first, second) {
    const firstTime = parseProgressTimestamp(first);
    const secondTime = parseProgressTimestamp(second);
    if (!firstTime && !secondTime) return null;
    return firstTime >= secondTime ? first : second;
}

function mergeKnowledgeProgress(parent, item) {
    if (!parent && !item) return null;
    const parentTime = Math.max(
        parseProgressTimestamp(parent?.lastSeen),
        parseProgressTimestamp(parent?.lastCorrect),
        parseProgressTimestamp(parent?.lastWrong)
    );
    const itemTime = Math.max(
        parseProgressTimestamp(item?.lastSeen),
        parseProgressTimestamp(item?.lastCorrect),
        parseProgressTimestamp(item?.lastWrong)
    );
    const newest = itemTime > parentTime ? item : parent;
    return {
        correct: (Number(parent?.correct) || 0) + (Number(item?.correct) || 0),
        wrong: (Number(parent?.wrong) || 0) + (Number(item?.wrong) || 0),
        lastCorrect: newestIso(parent?.lastCorrect, item?.lastCorrect),
        lastWrong: newestIso(parent?.lastWrong, item?.lastWrong),
        lastSeen: newestIso(parent?.lastSeen, item?.lastSeen),
        // The schedule belongs to the newest answer source. Combined lifetime
        // counts are retained for history but must not inflate its interval.
        srsStage: newest ? getSrsStage(newest) : undefined
    };
}

function getSpecificItemProgress(item) {
    const primary = itemProgressData?.[item?.itemId];
    if (primary) return primary;
    const legacy = (item?.legacyItemIds || [])
        .map(itemId => itemProgressData?.[itemId])
        .filter(Boolean);
    if (legacy.length === 0) return null;
    return legacy.reduce((latest, candidate) => {
        const latestTime = Math.max(
            parseProgressTimestamp(latest?.lastSeen),
            parseProgressTimestamp(latest?.lastCorrect),
            parseProgressTimestamp(latest?.lastWrong)
        );
        const candidateTime = Math.max(
            parseProgressTimestamp(candidate?.lastSeen),
            parseProgressTimestamp(candidate?.lastCorrect),
            parseProgressTimestamp(candidate?.lastWrong)
        );
        return candidateTime > latestTime ? candidate : latest;
    });
}

function getKnowledgeItemState(card, item) {
    const parent = progressData?.[card?.fullId || item?.parentWordId];
    const specific = getSpecificItemProgress(item);
    return getProgressState(mergeKnowledgeProgress(parent, specific));
}

function getCardKnowledgeSummary(card) {
    const items = getCardKnowledgeItems(card);
    const states = items.map(item => getKnowledgeItemState(card, item));
    return {
        total: items.length,
        learned: states.filter(state => state.learned).length,
        review: states.filter(state => state.needsReview).length,
        unseen: states.filter(state => !state.seen).length
    };
}

function getItemProgressForParent(parentWordId) {
    const source = itemProgressData || {};
    const sourceSize = Object.keys(source).length;
    if (indexedItemProgressSource !== source || indexedItemProgressSize !== sourceSize) {
        itemProgressByParent = new Map();
        for (const item of Object.values(source)) {
            if (!item?.parentWordId) continue;
            if (!itemProgressByParent.has(item.parentWordId)) {
                itemProgressByParent.set(item.parentWordId, []);
            }
            itemProgressByParent.get(item.parentWordId).push(item);
        }
        indexedItemProgressSource = source;
        indexedItemProgressSize = sourceSize;
    }
    return itemProgressByParent.get(parentWordId) || [];
}

function wordHasKnowledgeProgress(parentWordId) {
    return getItemProgressForParent(parentWordId).some(item => getProgressState(item).seen);
}

function getWordKnowledgeReviewInfo(parentWordId) {
    const parent = progressData?.[parentWordId] || null;
    const parentState = getProgressState(parent);
    const itemRows = getItemProgressForParent(parentWordId);
    const itemStates = itemRows.map(item => ({
        row: item,
        state: getProgressState(mergeKnowledgeProgress(parent, item))
    }));
    const allStates = [parentState, ...itemStates.map(item => item.state)];
    const hasIncorrect = allStates.some(state =>
        state.needsReview && state.reviewReason === 'incorrect');
    const hasDue = allStates.some(state => state.isDue);
    // A sparse item answer makes the card seen, but it does not silently make
    // the whole word known. Until every item is resolved (which promotes the
    // parent below), its never-marked siblings belong in Review, not Learn new.
    const isPartial = !parentState.seen
        && itemRows.some(item => getProgressState(item).seen);
    const needsReview = hasIncorrect || isPartial || hasDue;
    const relevantTimes = [];
    if (hasIncorrect) {
        allStates.forEach(state => {
            if (state.reviewReason === 'incorrect' && state.reviewAt) {
                relevantTimes.push(state.reviewAt);
            }
        });
    } else if (hasDue) {
        allStates.forEach(state => {
            if (state.isDue && state.nextReviewAt) relevantTimes.push(state.nextReviewAt);
        });
    } else if (isPartial) {
        itemRows.forEach(item => {
            const state = getProgressState(item);
            if (state.lastSeen) relevantTimes.push(state.lastSeen);
        });
    }
    return {
        needsReview,
        reason: hasIncorrect ? 'incorrect' : (hasDue ? 'due' : (isPartial ? 'partial' : null)),
        reviewAt: relevantTimes.length ? Math.min(...relevantTimes) : 0
    };
}

function wordNeedsKnowledgeReview(parentWordId) {
    return getWordKnowledgeReviewInfo(parentWordId).needsReview;
}

function buildFocusedReviewCard(card) {
    if (!card?.meanings?.length) return card;
    const focusedMeanings = [];
    for (let meaningIndex = 0; meaningIndex < card.meanings.length; meaningIndex++) {
        const meaning = card.meanings[meaningIndex];
        const items = knowledgeItemsForMeaning(card, meaning, meaningIndex);
        // A partially answered card reviews every item that is not currently
        // known: explicit mistakes plus untouched sibling senses/expressions.
        // A newer whole-card correct is inherited by every item, so it still
        // resolves the complete card in one action.
        const unresolved = items.filter(item => !getKnowledgeItemState(card, item).learned);
        if (unresolved.length === 0) continue;

        if (meaning.allMWEs?.length) {
            const keep = new Set(unresolved.map(item => item.cycleIndex));
            focusedMeanings.push({
                ...meaning,
                allMWEs: meaning.allMWEs.filter((_, index) => keep.has(index))
            });
        } else if (meaning.allClitics?.length) {
            const keep = new Set(unresolved.map(item => item.cycleIndex));
            focusedMeanings.push({
                ...meaning,
                allClitics: meaning.allClitics.filter((_, index) => keep.has(index))
            });
        } else if (meaning.pos === 'SENSE_CYCLE' && meaning.allSenses?.length) {
            const keep = new Set(unresolved.map(item => item.cycleIndex));
            const allSenses = meaning.allSenses.filter((_, index) => keep.has(index));
            focusedMeanings.push({
                ...meaning,
                allSenses,
                meaning: allSenses[0]?.translation || meaning.meaning
            });
        } else {
            focusedMeanings.push({ ...meaning });
        }
    }
    if (focusedMeanings.length === 0) return null;
    return {
        ...card,
        meanings: focusedMeanings,
        translation: focusedMeanings[0]?.meaning || card.translation,
        targetSentence: focusedMeanings[0]?.targetSentence || card.targetSentence,
        englishSentence: focusedMeanings[0]?.englishSentence || card.englishSentence,
        reviewFocused: true,
        _grouping: null
    };
}

function cacheItemProgress() {
    window.cacheProgressLocally?.();
}

async function saveKnowledgeProgress(card, items, isCorrect) {
    if (!currentUser || currentUser.isGuest || !card?.fullId || !items?.length) return;
    const parentWasLearned = getProgressState(progressData?.[card.fullId]).learned;
    const timestamp = new Date().toISOString();
    for (const item of items) {
        const previous = getSpecificItemProgress(item);
        const existing = itemProgressData[item.itemId] || (previous ? {
            ...previous,
            itemId: item.itemId,
            parentWordId: card.fullId,
            itemType: item.type,
            label: item.label,
            schemaVersion: KNOWLEDGE_SCHEMA_VERSION
        } : {
            itemId: item.itemId,
            parentWordId: card.fullId,
            itemType: item.type,
            label: item.label,
            language: selectedLanguage,
            correct: 0,
            wrong: 0,
            lastCorrect: null,
            lastWrong: null,
            lastSeen: null,
            srsStage: 0,
            schemaVersion: KNOWLEDGE_SCHEMA_VERSION
        });
        existing.srsStage = advanceSrsStage(existing, isCorrect);
        if (isCorrect) {
            existing.correct = (Number(existing.correct) || 0) + 1;
            existing.lastCorrect = timestamp;
        } else {
            existing.wrong = (Number(existing.wrong) || 0) + 1;
            existing.lastWrong = timestamp;
        }
        existing.lastSeen = timestamp;
        existing.label = item.label;
        itemProgressData[item.itemId] = existing;

        sendOrQueue({
            action: 'saveItem',
            sheet: 'Progress',
            mode: window.getProgressMode?.() || (activeArtist ? 'artist' : 'normal'),
            user: currentUser.initials,
            itemId: existing.itemId,
            parentWordId: existing.parentWordId,
            itemType: existing.itemType === 'expression' ? 'mwe' : existing.itemType,
            label: existing.label,
            language: existing.language,
            correct: existing.correct,
            wrong: existing.wrong,
            lastCorrect: existing.lastCorrect,
            lastWrong: existing.lastWrong,
            lastSeen: existing.lastSeen,
            srsStage: existing.srsStage,
            schemaVersion: existing.schemaVersion
        }, `saveItem|Progress|${existing.itemId}`);
    }
    cacheItemProgress();

    // Completing every sense/expression explicitly is equivalent to knowing
    // the card. Persist one parent correct so setup progress, coverage, and
    // future review filtering can recognise completion without downloading
    // the card schema merely to count its sparse ItemProgress rows.
    const summary = getCardKnowledgeSummary(card);
    if (!parentWasLearned && summary.total > 0 && summary.learned === summary.total) {
        await window.saveWordProgress?.(card, true);
    }
}

function escapeKnowledgeHTML(value) {
    return String(value || '').replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    })[character]);
}

function knowledgeSectionLabel(type) {
    if (type === 'expression') return 'Expressions';
    if (type === 'clitic') return 'Attached forms';
    return 'Meanings';
}

function renderKnowledgeOverviewButton(card) {
    if (!currentUser || currentUser.isGuest) return '';
    const summary = getCardKnowledgeSummary(card);
    if (summary.total === 0) return '';
    const label = `${summary.learned} of ${summary.total} known`;
    return `<button type="button" class="ref-tile knowledge-overview-trigger" aria-label="Open meanings and expressions knowledge: ${label}" onclick="showKnowledgeOverview(event)">
        <svg class="ref-tile-icon" viewBox="10 10 26 26" aria-hidden="true">
            <path d="M12 13.5h18M12 21h18M12 28.5h11" class="knowledge-overview-icon-lines"/>
            <path d="m27 29 2.4 2.4L34 26.8" class="knowledge-overview-icon-check"/>
        </svg>
        <span class="ref-tile-label">${summary.learned}/${summary.total} known</span>
    </button>`;
}

function ensureKnowledgeOverviewModal() {
    let modal = document.getElementById('knowledgeOverviewModal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'knowledgeOverviewModal';
    modal.className = 'knowledge-overview-modal';
    modal.hidden = true;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'knowledgeOverviewTitle');
    modal.innerHTML = `
        <div class="knowledge-overview-sheet">
            <header class="knowledge-overview-header">
                <div>
                    <span class="knowledge-overview-kicker">Card knowledge</span>
                    <h2 id="knowledgeOverviewTitle">Meanings and expressions</h2>
                </div>
                <button type="button" class="knowledge-overview-close" aria-label="Close knowledge overview" onclick="closeKnowledgeOverview(event)">×</button>
            </header>
            <div id="knowledgeOverviewSummary" class="knowledge-overview-summary"></div>
            <div id="knowledgeOverviewList" class="knowledge-overview-list"></div>
        </div>`;
    modal.addEventListener('click', event => {
        if (event.target === modal) closeKnowledgeOverview(event);
    });
    document.body.appendChild(modal);
    return modal;
}

function renderKnowledgeOverview(card) {
    const modal = ensureKnowledgeOverviewModal();
    const items = getCardKnowledgeItems(card);
    const summary = getCardKnowledgeSummary(card);
    const summaryEl = modal.querySelector('#knowledgeOverviewSummary');
    const listEl = modal.querySelector('#knowledgeOverviewList');
    const reviewLabel = summary.review === 1 ? '1 review' : `${summary.review} review`;
    const unseenLabel = summary.unseen === 1 ? '1 unmarked' : `${summary.unseen} unmarked`;
    summaryEl.innerHTML = `
        <strong>${summary.learned}/${summary.total} known</strong>
        <span class="knowledge-overview-summary-review">${reviewLabel}</span>
        <span>${unseenLabel}</span>`;

    const sections = new Map();
    items.forEach((item, index) => {
        const label = knowledgeSectionLabel(item.type);
        if (!sections.has(label)) sections.set(label, []);
        sections.get(label).push({ item, index });
    });

    listEl.innerHTML = Array.from(sections, ([label, rows]) => `
        <section class="knowledge-overview-section">
            <h3>${label}<span>${rows.length}</span></h3>
            <div class="knowledge-overview-rows">
                ${rows.map(({ item, index }) => {
                    const state = getKnowledgeItemState(card, item);
                    const status = state.learned ? 'known' : (state.needsReview ? 'review' : 'unseen');
                    const statusText = status === 'known' ? 'Known' : (status === 'review' ? 'Review' : 'Unmarked');
                    const pos = item.pos && item.type === 'sense'
                        ? `<span class="knowledge-overview-pos">${escapeKnowledgeHTML(item.pos)}</span>`
                        : '';
                    const detail = item.detail
                        ? `<small>${escapeKnowledgeHTML(item.detail)}</small>`
                        : '';
                    return `<div class="knowledge-overview-row is-${status}">
                        <button type="button" class="knowledge-overview-focus" onclick="focusKnowledgeOverviewItem(event, ${index})" title="Show this item on the card">
                            <span class="knowledge-overview-status" aria-label="${statusText}"></span>
                            <span class="knowledge-overview-copy">${pos}<strong>${escapeKnowledgeHTML(item.label)}</strong>${detail}</span>
                        </button>
                        <div class="knowledge-overview-actions" aria-label="Knowledge for ${escapeKnowledgeHTML(item.label)}">
                            <button type="button" class="knowledge-overview-mark mark-review${status === 'review' ? ' is-active' : ''}" onclick="markKnowledgeOverviewItem(event, ${index}, false)" aria-label="Mark for review" title="Mark for review">×</button>
                            <button type="button" class="knowledge-overview-mark mark-known${status === 'known' ? ' is-active' : ''}" onclick="markKnowledgeOverviewItem(event, ${index}, true)" aria-label="Mark known" title="Mark known">✓</button>
                        </div>
                    </div>`;
                }).join('')}
            </div>
        </section>`).join('');
}

function showKnowledgeOverview(event) {
    event?.stopPropagation();
    const card = flashcards[currentIndex];
    if (!card) return;
    const modal = ensureKnowledgeOverviewModal();
    renderKnowledgeOverview(card);
    modal.hidden = false;
    document.body.classList.add('knowledge-overview-open');
    modal.querySelector('.knowledge-overview-close')?.focus();
}

function closeKnowledgeOverview(event) {
    event?.stopPropagation();
    const modal = document.getElementById('knowledgeOverviewModal');
    if (modal) modal.hidden = true;
    document.body.classList.remove('knowledge-overview-open');
}

function focusKnowledgeOverviewItem(event, index) {
    event?.stopPropagation();
    const card = flashcards[currentIndex];
    const item = getCardKnowledgeItems(card)[index];
    if (!card || !item) return;
    closeKnowledgeOverview();
    window.focusKnowledgeCardItem?.(item.meaningIndex, item.cycleIndex || 0);
}

async function markKnowledgeOverviewItem(event, index, isCorrect) {
    event?.stopPropagation();
    const card = flashcards[currentIndex];
    const item = getCardKnowledgeItems(card)[index];
    if (!card || !item) return;
    await saveKnowledgeProgress(card, [item], isCorrect);
    updateCard();
    renderKnowledgeOverview(card);
}

// Kept as an empty compatibility hook for cached flashcards.js versions.
// Granular actions now live in the explicit overview instead of taking a
// permanent strip of vertical space from every card.
function renderKnowledgeControl() {
    return '';
}

async function markCurrentKnowledge(event, isCorrect) {
    event?.stopPropagation();
    const card = flashcards[currentIndex];
    const items = getActiveKnowledgeItems(card);
    if (!card || items.length === 0) return;
    await saveKnowledgeProgress(card, items, isCorrect);
    updateCard();
}

window.knowledgeItemsForMeaning = knowledgeItemsForMeaning;
window.getCardKnowledgeItems = getCardKnowledgeItems;
window.getActiveKnowledgeItems = getActiveKnowledgeItems;
window.getKnowledgeItemState = getKnowledgeItemState;
window.getCardKnowledgeSummary = getCardKnowledgeSummary;
window.wordHasKnowledgeProgress = wordHasKnowledgeProgress;
window.wordNeedsKnowledgeReview = wordNeedsKnowledgeReview;
window.getWordKnowledgeReviewInfo = getWordKnowledgeReviewInfo;
window.buildFocusedReviewCard = buildFocusedReviewCard;
window.saveKnowledgeProgress = saveKnowledgeProgress;
window.renderKnowledgeControl = renderKnowledgeControl;
window.renderKnowledgeOverviewButton = renderKnowledgeOverviewButton;
window.markCurrentKnowledge = markCurrentKnowledge;
window.showKnowledgeOverview = showKnowledgeOverview;
window.closeKnowledgeOverview = closeKnowledgeOverview;
window.focusKnowledgeOverviewItem = focusKnowledgeOverviewItem;
window.markKnowledgeOverviewItem = markKnowledgeOverviewItem;
window.cacheItemProgress = cacheItemProgress;

document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const modal = document.getElementById('knowledgeOverviewModal');
    if (modal && !modal.hidden) closeKnowledgeOverview(event);
});
