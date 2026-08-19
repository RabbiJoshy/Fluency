// English-first cards use several dictionary senses as a compact fingerprint
// for one exact target-language surface. Keep selection and English inflection
// pure here so homographs can be regression-tested without the card DOM.

const REVERSE_CUE_LIMIT = 4;
const SPECIAL_POS = new Set(['MWE', 'CLITIC', 'SENSE_CYCLE', 'EXAMPLE_ONLY']);
const VERB_POS = new Set(['VERB', 'AUX']);

const PERSON_TO_INDEX = { '1s': 0, '2s': 1, '3s': 2, '1p': 3, '2p': 4, '3p': 5 };
const ENGLISH_PRONOUNS = ['I', 'you', 'he', 'we', 'you (pl)', 'they'];
const NONFINITE_MOODS = new Set(['gerundio', 'participo']);

const IRREGULAR_ENGLISH_PLURALS = {
    child: 'children',
    foot: 'feet',
    goose: 'geese',
    louse: 'lice',
    man: 'men',
    mouse: 'mice',
    ox: 'oxen',
    person: 'people',
    tooth: 'teeth',
    woman: 'women',
};

const INVARIANT_ENGLISH_PLURALS = new Set([
    'deer', 'fish', 'means', 'offspring', 'series', 'sheep', 'species',
]);

function cueText(meaning) {
    return String(meaning?.meaning ?? meaning?.translation ?? '').trim();
}

function cueTextKey(meaning) {
    return cueText(meaning).toLocaleLowerCase('en');
}

function cueGroupKey(meaning) {
    const lemma = String(meaning?.headword || '').trim().toLocaleLowerCase('es');
    const pos = String(meaning?.pos || '').trim().toUpperCase();
    return `${lemma}\u0000${pos}`;
}

function cueWeight(candidate) {
    const value = Number(candidate.meaning?.percentage ?? candidate.meaning?.frequency ?? 0);
    return Number.isFinite(value) ? value : 0;
}

function byWeightThenSource(a, b) {
    return cueWeight(b) - cueWeight(a) || a.index - b.index;
}

function cardHasFiniteVerbMorphology(card) {
    const rows = (Array.isArray(card?.morphology) ? card.morphology : [card?.morphology]).filter(Boolean);
    return rows.some(row => row?.mood && !['infinitivo', 'participio', 'participo'].includes(row.mood));
}

function isNominalSurfaceOf(surface, lemma) {
    const target = String(surface || '').trim().toLocaleLowerCase('es');
    const base = String(lemma || '').trim().toLocaleLowerCase('es');
    if (!target || !base) return false;
    if (target === base) return true;

    const forms = new Set([`${base}s`, `${base}es`]);
    if (base.endsWith('z')) forms.add(`${base.slice(0, -1)}ces`);
    if (base.endsWith('o')) {
        const stem = base.slice(0, -1);
        forms.add(`${stem}a`);
        forms.add(`${stem}os`);
        forms.add(`${stem}as`);
    }
    // SpanishDict groups the article/determiner family under un or uno.
    if (base === 'un' || base === 'uno') {
        ['un', 'una', 'unos', 'unas'].forEach(form => forms.add(form));
    }
    return forms.has(target);
}

function meaningMatchesSurfaceReading(card, meaning) {
    if (!card || !cardHasFiniteVerbMorphology(card)) return true;
    const pos = String(meaning?.pos || '').toUpperCase();
    if (VERB_POS.has(pos)) return true;
    const lemma = meaning?.headword;
    if (!lemma) return true;
    const surface = card.productionAnswer || card.displaySurface || card.targetWord || '';
    return isNominalSurfaceOf(surface, lemma);
}

/**
 * Choose a bounded semantic fingerprint for an English-first card.
 *
 * A representative from each (lemma, POS) reading is considered before extra
 * senses from a frequent reading. Duplicate English text adds no useful clue,
 * so it is shown only once even when two dictionary leaves share it.
 */
export function selectReverseCueMeanings(meanings, options = {}) {
    const card = options?.card || null;
    const max = Math.max(0, Number(options?.limit ?? REVERSE_CUE_LIMIT) || 0);
    if (!max || !Array.isArray(meanings)) return [];

    const available = meanings
        .map((meaning, index) => ({ meaning, index }))
        .filter(({ meaning }) => {
            const pos = String(meaning?.pos || '').toUpperCase();
            return cueText(meaning) && !SPECIAL_POS.has(pos);
        });
    const compatible = available.filter(({ meaning }) => meaningMatchesSurfaceReading(card, meaning));
    // Compatibility removes lemma-menu leakage such as the noun `power` from
    // finite `puedes`. Older/incomplete decks can lack a compatible gloss
    // entirely; retain their best packaged gloss rather than render a blank
    // English-first face.
    const candidates = compatible.length ? compatible : available;

    const groups = new Map();
    for (const candidate of candidates) {
        const key = cueGroupKey(candidate.meaning);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(candidate);
    }

    const rankedGroups = [...groups.values()]
        .map(group => [...group].sort(byWeightThenSource))
        .sort((a, b) => byWeightThenSource(a[0], b[0]));
    const selected = [];
    const selectedIndexes = new Set();
    const seenText = new Set();

    const add = candidate => {
        const textKey = cueTextKey(candidate.meaning);
        if (!textKey || seenText.has(textKey) || selected.length >= max) return false;
        selected.push(candidate);
        selectedIndexes.add(candidate.index);
        seenText.add(textKey);
        return true;
    };

    // Cover each distinct lemma/POS reading while there is room. If a group's
    // strongest gloss duplicates an earlier one, try its next distinct sense.
    for (const group of rankedGroups) {
        if (selected.length >= max) break;
        group.some(add);
    }

    // Then add the strongest remaining senses, preserving useful polysemy
    // without turning the front into an exhaustive dictionary dump.
    for (const candidate of [...candidates].sort(byWeightThenSource)) {
        if (selected.length >= max) break;
        if (!selectedIndexes.has(candidate.index)) add(candidate);
    }

    // Dictionary/source order is the clearest display order once selection is
    // complete; ranking affects inclusion, not the learner-facing sequence.
    return selected.sort((a, b) => a.index - b.index).map(({ meaning }) => meaning);
}

function isRegularSpanishPlural(surface, lemma) {
    const target = String(surface || '').trim().toLocaleLowerCase('es');
    const base = String(lemma || '').trim().toLocaleLowerCase('es');
    if (!target || !base || target === base) return false;
    const candidates = new Set([`${base}s`, `${base}es`]);
    if (base.endsWith('z')) candidates.add(`${base.slice(0, -1)}ces`);
    return candidates.has(target);
}

function pluralizeEnglishWord(gloss) {
    const word = String(gloss || '').trim();
    if (!/^[A-Za-z]+$/u.test(word)) return null;
    const lower = word.toLocaleLowerCase('en');
    let plural;
    if (IRREGULAR_ENGLISH_PLURALS[lower]) {
        plural = IRREGULAR_ENGLISH_PLURALS[lower];
    } else if (INVARIANT_ENGLISH_PLURALS.has(lower)) {
        plural = lower;
    } else if (/[^aeiou]y$/u.test(lower)) {
        plural = `${lower.slice(0, -1)}ies`;
    } else if (/(?:s|x|z|ch|sh)$/u.test(lower)) {
        plural = `${lower}es`;
    } else {
        plural = `${lower}s`;
    }
    if (/^[A-Z]/u.test(word)) return plural[0].toUpperCase() + plural.slice(1);
    return plural;
}

function nounProductionCue(card, meaning, translation) {
    if (String(meaning?.pos || '').toUpperCase() !== 'NOUN') return null;
    const surface = card?.productionAnswer || card?.displaySurface || card?.targetWord || '';
    const lemma = meaning?.headword || card?.lemma || '';
    if (!isRegularSpanishPlural(surface, lemma)) return null;
    return pluralizeEnglishWord(translation);
}

function normalizeAnalysis(morph) {
    let mood = String(morph?.mood || '').toLocaleLowerCase('es');
    let tense = String(morph?.tense || '').toLocaleLowerCase('es');
    if (mood === 'participio' || mood === 'participio-pasado') mood = 'participo';
    if (tense === 'participio' || tense === 'participio-pasado') tense = 'participo';
    return { mood, tense, key: mood && tense ? `${mood}/${tense}` : '' };
}

function expandThirdSingular(form) {
    if (/^he\s/iu.test(form)) return form.replace(/^he\s/iu, 'he/she/it ');
    if (/^he'/iu.test(form)) return form.replace(/^he'/iu, "he/she/it'");
    return form;
}

function infinitiveParts(translation) {
    const value = String(translation || '').trim();
    if (!value.startsWith('to ')) return null;
    const body = value.slice(3).trim();
    if (!body) return null;
    const splitAt = body.indexOf(' ');
    return splitAt === -1
        ? { head: body, rest: '' }
        : { head: body.slice(0, splitAt), rest: body.slice(splitAt) };
}

function deriveRegularAnalysisCue(translation, analysis, personIdx) {
    const parts = infinitiveParts(translation);
    if (!parts || personIdx === undefined) return null;
    const verb = `${parts.head}${parts.rest}`;
    if (analysis.mood === 'condicional' && analysis.tense === 'presente') {
        return `${ENGLISH_PRONOUNS[personIdx]} would ${verb}`;
    }
    if (analysis.mood !== 'imperativo' || personIdx === 0) return null;
    if (analysis.tense === 'negativo') {
        return personIdx === 3 ? `let's not ${verb}!` : `don't ${verb}!`;
    }
    if (analysis.tense !== 'afirmativo') return null;
    return personIdx === 3 ? `let's ${verb}!` : `${verb}!`;
}

function cueForAnalysis(analysisRows, morph, translation) {
    const analysis = normalizeAnalysis(morph);
    if (!analysis.key) return null;

    // Step 5e v3 uses full mood/tense keys. Retain the indicative-tense
    // fallback so an already-open client with the v2 data layer still works
    // while the cache update arrives.
    const row = analysisRows?.[analysis.key]
        || (analysis.mood === 'indicativo' ? analysisRows?.[analysis.tense] : null);
    const personIdx = PERSON_TO_INDEX[morph?.person];
    if (!Array.isArray(row)) {
        const derived = deriveRegularAnalysisCue(translation, analysis, personIdx);
        return derived && personIdx === 2 && analysis.mood !== 'imperativo'
            ? expandThirdSingular(derived)
            : derived;
    }

    if (NONFINITE_MOODS.has(analysis.mood)) return row[0] || null;
    if (personIdx === undefined) return null;
    const form = row[personIdx] || null;
    if (!form) return null;

    // Spanish indicative/conditional 3sg covers he, she, it, and formal you.
    // Imperative 3sg is instead an usted command, so its subject stays implicit.
    return personIdx === 2 && analysis.mood !== 'imperativo'
        ? expandThirdSingular(form)
        : form;
}

/**
 * Return a surface-appropriate English cue, or null when the available data
 * cannot support one confidently. Each meaning's own lemma is authoritative;
 * card.lemma is only a legacy fallback for decks without sense-level identity.
 */
export function englishProductionCue(card, meaningOrTranslation, conjugatedEnglishData, options = {}) {
    if (!card || !meaningOrTranslation) return null;
    const meaning = typeof meaningOrTranslation === 'object' ? meaningOrTranslation : null;
    const translation = meaning ? cueText(meaning) : String(meaningOrTranslation || '').trim();
    if (!translation) return null;

    // Merged reverse cards ask for the lemma rather than the visible surface,
    // so surface morphology would be a misleading prompt in that direction.
    if (card.mergedLemma && options.reverseDirection) return null;

    const nounCue = meaning ? nounProductionCue(card, meaning, translation) : null;
    if (nounCue) return nounCue;

    const pos = String(meaning?.pos || '').toUpperCase();
    if (pos && !VERB_POS.has(pos)) return null;
    if (!conjugatedEnglishData) return null;

    const lemma = String(meaning?.headword || card.lemma || '').toLocaleLowerCase('es');
    const analysisRows = conjugatedEnglishData?.[lemma]?.[translation];
    if (!analysisRows) return null;

    const rawMorph = card.mergedLemma ? card._activeExampleMorphology : card.morphology;
    const morphCandidates = (Array.isArray(rawMorph) ? rawMorph : [rawMorph]).filter(Boolean);
    const forms = morphCandidates
        .map(morph => cueForAnalysis(analysisRows, morph, translation))
        .filter((form, index, all) => form && all.indexOf(form) === index);
    if (!forms.length) return null;

    // Some Spanish surfaces genuinely encode more than one supported reading
    // (da = indicative "gives" or command "give!"). Showing both compactly is
    // more useful than reverting the entire card to an uninflected dictionary
    // gloss; unsupported/context-sensitive analyses simply abstain.
    return forms.join(' / ');
}

/**
 * Split one real target-language sentence around an exact answer occurrence.
 * The renderer escapes the returned text and substitutes its own blank, so
 * this helper stays presentation-neutral and straightforward to test.
 */
export function splitProductionCloze(sentence, answerSurface) {
    const text = String(sentence || '');
    const answer = String(answerSurface || '').trim();
    if (!text || !answer) return null;
    const body = answer
        .replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')
        .replace(/[’']/gu, "[’']")
        .replace(/\s+/gu, '\\s+');
    let match;
    try {
        match = text.match(new RegExp(`(?<![\\p{L}\\p{N}])(${body})(?![\\p{L}\\p{N}])`, 'iu'));
    } catch (_) {
        return null;
    }
    if (!match || match.index === undefined) return null;
    return {
        before: text.slice(0, match.index),
        matched: match[0],
        after: text.slice(match.index + match[0].length),
    };
}

/**
 * Keep the sentence prompt immutable for one card attempt. Back-side example
 * browsing rerenders the card, but only a new entry or direction change may
 * capture a different prompt.
 */
export function retainProductionPromptAttempt(previous, {
    direction,
    reset = false,
    createHTML,
} = {}) {
    const normalizedDirection = Boolean(direction);
    if (previous && !reset && previous.direction === normalizedDirection) return previous;
    return {
        direction: normalizedDirection,
        html: normalizedDirection && typeof createHTML === 'function'
            ? String(createHTML() || '')
            : '',
    };
}
