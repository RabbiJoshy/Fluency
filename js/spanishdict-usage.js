// Pure helpers for presenting SpanishDict's sense-level usage notes.
//
// This module deliberately describes metadata; it does not claim that a
// companion found in the same sentence is syntactically attached to the card
// word. WSD can consume a future evidence layer once attachment is measured.

const USED_WITH_RE = /\b(?:(often|frequently)\s+)?used with\s+(.+)$/iu;
const QUOTED_TERM_RE = /["“]([^"”]+)["”]/gu;

function cleanTerm(value) {
    return String(value || '').trim().replace(/[,.;:]+$/u, '').trim();
}

function compactUsageBody(rawTail) {
    let body = String(rawTail || '').trim().replace(/[.;]+$/u, '');
    body = body.replace(QUOTED_TERM_RE, (_whole, term) => cleanTerm(term));
    body = body
        .replace(/\s*,\s*/gu, ' / ')
        .replace(/\s+(?:or|o)\s+/giu, ' / ')
        .replace(/\s+and sometimes preceded by\s+/giu, ' · sometimes preceded by ')
        .replace(/\s+(?:and|plus)\s+(?:an?\s+|the\s+)?(?=(?:infinitive|gerund|participle|adjective)\b)/giu, ' + ')
        .replace(/^an?\s+(?=(?:infinitive|gerund|participle|adjective|form)\b)/iu, '')
        .replace(/^adjectives\b/iu, 'adjective')
        .replace(/^negatives\b/iu, 'negative')
        .replace(/\s*;\s*/gu, ' · ')
        .replace(/\s*\/\s*/gu, ' / ')
        .replace(/\s*·\s*/gu, ' · ')
        .replace(/\s*\+\s*/gu, ' + ')
        .replace(/\s+/gu, ' ')
        .trim();
    return body;
}

/**
 * Split a SpanishDict context such as
 *   "to tolerate; used with \"con\""
 * into ordinary sense detail plus a compact, source-faithful usage label.
 * Unknown/non-usage contexts return null so callers retain the raw text.
 */
export function parseSpanishDictUsageContext(context) {
    if (typeof context !== 'string') return null;
    const raw = context.trim();
    if (!raw) return null;
    const match = USED_WITH_RE.exec(raw);
    if (!match) return null;

    const qualifier = (match[1] || '').toLocaleLowerCase('en');
    const rawTail = (match[2] || '').trim();
    const detail = raw.slice(0, match.index).replace(/[\s;:,]+$/u, '').trim();
    const body = compactUsageBody(rawTail);
    if (!body) return null;

    // Only immediately quoted companions are literal candidates. A note such
    // as `used with verbs of perception as an equivalent of "que"` quotes a
    // gloss, not a companion. `a form of "mismo"` is the one structural shape
    // whose quoted lemma intentionally supplies candidate surface forms.
    const immediateQuoted = /^["“]/u.test(rawTail);
    const formOfMatch = rawTail.match(/^a form of\s+["“]([^"”]+)["”]/iu);
    const terms = [];
    if (immediateQuoted) {
        for (const termMatch of rawTail.matchAll(QUOTED_TERM_RE)) {
            const term = cleanTerm(termMatch[1]);
            if (term) terms.push(term);
        }
    } else if (formOfMatch) {
        const term = cleanTerm(formOfMatch[1]);
        if (term) terms.push(term);
    }

    const label = `${qualifier ? `${qualifier} ` : ''}+ ${body}`;
    return {
        raw,
        detail,
        qualifier: qualifier || null,
        label,
        terms: [...new Set(terms)],
        structural: !immediateQuoted,
    };
}

const SPANISH_SURFACE_VARIANTS = {
    a: ['a', 'al'],
    de: ['de', 'del'],
    con: ['con', 'conmigo', 'contigo', 'consigo'],
    mismo: ['mismo', 'misma', 'mismos', 'mismas'],
};

/**
 * Candidate spellings for a transparent UI "possible match". These are not
 * WSD evidence: the caller must label them as unverified attachment.
 */
export function spanishDictUsageCandidateForms(usage) {
    if (!usage || !Array.isArray(usage.terms)) return [];
    const forms = [];
    const seen = new Set();
    for (const rawTerm of usage.terms) {
        const term = cleanTerm(rawTerm);
        if (!term) continue;
        const variants = SPANISH_SURFACE_VARIANTS[term.toLocaleLowerCase('es')] || [term];
        for (const variant of variants) {
            const key = variant.toLocaleLowerCase('es');
            if (seen.has(key)) continue;
            seen.add(key);
            forms.push(variant);
        }
    }
    // Match longer contractions/phrases before their shorter components.
    return forms.sort((a, b) => b.length - a.length);
}
