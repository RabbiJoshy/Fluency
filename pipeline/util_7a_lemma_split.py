"""Shared utilities for splitting surface-word assignments onto word|lemma keys.

Extracted from artist/step_7a_map_senses_to_lemmas.py so both normal-mode and
artist-mode pipelines can share the same split logic.
"""

from copy import deepcopy
import unicodedata


_PLURAL_POS = frozenset({"NOUN", "ADJ", "DET", "PRON", "PROPN"})


def _fold_form(value):
    text = unicodedata.normalize("NFD", (value or "").strip().lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def is_regular_plural_form(plural, singular):
    """Return True for an unambiguous regular Spanish plural relationship.

    Accent changes are ignored (canción→canciones), while the fixed z→ces
    alternation is handled explicitly. This only establishes morphology; the
    caller must still require both headwords to be present in the same sense
    menu before redirecting either identity.
    """
    plural_f = _fold_form(plural)
    singular_f = _fold_form(singular)
    if not plural_f or not singular_f or plural_f == singular_f:
        return False
    if singular_f.endswith("z"):
        return plural_f == singular_f[:-1] + "ces"
    if singular_f[-1] in "aeiou":
        return plural_f == singular_f + "s"
    return plural_f == singular_f + "es"


def plural_lemma_redirects(analyses):
    """Return {plural_headword: singular_headword} for one surface menu.

    Requiring both analyses and nominal/adjectival POS on both sides avoids
    guessing from a suffix alone. The analyses and their sense IDs remain
    untouched; only their downstream lemma-group identity is consolidated.
    """
    candidates = []
    for analysis in analyses or []:
        if not isinstance(analysis, dict):
            continue
        headword = analysis.get("headword") or analysis.get("lemma")
        if not isinstance(headword, str) or not headword.strip():
            continue
        senses = analysis.get("senses") or {}
        sense_values = senses.values() if isinstance(senses, dict) else senses
        poses = {
            (sense.get("pos") or "").strip().upper()
            for sense in sense_values or [] if isinstance(sense, dict)
        }
        if poses and poses <= _PLURAL_POS:
            candidates.append(headword.strip())

    redirects = {}
    for plural in candidates:
        singulars = [
            singular for singular in candidates
            if singular != plural and is_regular_plural_form(plural, singular)
        ]
        if singulars:
            # A regular plural should have one base. Keep the choice stable if
            # malformed source data happens to present more than one.
            redirects[plural] = sorted(singulars, key=lambda value: (len(value), value))[0]
    return redirects


def normalize_assignment_methods(raw_value):
    """Normalise a raw assignment value to {method: [items]} dict."""
    if isinstance(raw_value, dict):
        return {method: list(items or []) for method, items in raw_value.items()}
    if isinstance(raw_value, list):
        return {"legacy": list(raw_value)}
    return {}


def merge_items(existing, incoming):
    """Merge two lists of assignment items, deduplicating by sense ID.

    Union the ``examples`` lists per sense; carry through every other field
    (``pos``/``translation``/``lemma``/``example_ids``/``prompt_id``/``run_ts``
    for discovery + provenance) from the first item that defines each key, so a
    same-sense collision no longer silently strips the inline sense definition or
    provenance stamps down to bare ``{sense, examples}``.
    """
    merged = {}
    order = []
    for item in list(existing) + list(incoming):
        sense = item.get("sense")
        if not sense:
            continue
        if sense not in merged:
            merged[sense] = {"sense": sense, "_evidence": {}}
            # Preserve all non-example fields from the first item seen.
            for k, v in item.items():
                if k not in (
                    "sense", "examples", "example_ids",
                    "occurrence_refs", "occurrence_ids",
                ):
                    merged[sense][k] = v
            order.append(sense)
        else:
            # Backfill any field the earlier item lacked (don't overwrite).
            for k, v in item.items():
                if k not in (
                    "sense", "examples", "example_ids",
                    "occurrence_refs", "occurrence_ids",
                ) and k not in merged[sense]:
                    merged[sense][k] = v

        # Numeric indices are compatibility coordinates, not identity. Keep the
        # aligned stable ID when present so a reorder cannot attach it to a
        # different example. Repeated observations of the same stable ID merge
        # even if their legacy numeric indices differ.
        examples = item.get("examples") or []
        example_ids = item.get("example_ids") or []
        evidence = merged[sense]["_evidence"]
        for position, ex_idx in enumerate(examples):
            ex_id = example_ids[position] if position < len(example_ids) else None
            key = ("example", ex_id) if ex_id else ("index", ex_idx)
            evidence.setdefault(key, {"ex_idx": ex_idx, "ex_id": ex_id})

        refs = merged[sense].setdefault("occurrence_refs", [])
        seen_occurrences = {
            ref.get("occurrence_id") for ref in refs if isinstance(ref, dict)
        }
        for ref in item.get("occurrence_refs") or []:
            occurrence_id = ref.get("occurrence_id") if isinstance(ref, dict) else None
            if occurrence_id and occurrence_id not in seen_occurrences:
                refs.append(deepcopy(ref))
                seen_occurrences.add(occurrence_id)

        occurrence_ids = merged[sense].setdefault("occurrence_ids", [])
        for occurrence_id in item.get("occurrence_ids") or []:
            if occurrence_id and occurrence_id not in occurrence_ids:
                occurrence_ids.append(occurrence_id)

    result = []
    for sense in order:
        item = merged[sense]
        evidence = list(item.pop("_evidence").values())
        evidence.sort(key=lambda row: (
            row["ex_idx"] if isinstance(row.get("ex_idx"), int) else -1,
            str(row.get("ex_id") or ""),
        ))
        item["examples"] = [row["ex_idx"] for row in evidence]
        if any(row.get("ex_id") for row in evidence):
            item["example_ids"] = [row.get("ex_id") for row in evidence]
        for ref in item.get("occurrence_refs") or []:
            occurrence_id = ref.get("occurrence_id") if isinstance(ref, dict) else None
            if occurrence_id and occurrence_id not in item.setdefault("occurrence_ids", []):
                item["occurrence_ids"].append(occurrence_id)
        if not item.get("occurrence_refs"):
            item.pop("occurrence_refs", None)
        if not item.get("occurrence_ids"):
            item.pop("occurrence_ids", None)
        result.append(item)
    return result


def merge_method_maps(existing, incoming):
    """Merge two method-keyed assignment dicts."""
    out = {method: list(items) for method, items in existing.items()}
    for method, items in incoming.items():
        if method not in out:
            out[method] = list(items)
        else:
            out[method] = merge_items(out[method], items)
    return out


def _is_phrase_only_self_analysis(word, analysis):
    """True if analysis's headword equals the surface word AND all its senses are PHRASE.

    SpanishDict publishes a "phrasebook" analysis for common conjugated forms
    (e.g. ``está`` with senses "he's", "she's" all tagged POS=PHRASE) alongside
    the real verb analysis (headword=``estar``). The phrasebook headword is the
    surface form itself, which is not a true lemma.
    """
    headword = (analysis.get("headword") or "").strip().lower()
    if not headword or headword != word.lower():
        return False
    senses = analysis.get("senses", {})
    if not isinstance(senses, dict) or not senses:
        return False
    return all(
        isinstance(s, dict) and s.get("pos") == "PHRASE"
        for s in senses.values()
    )


def analysis_key(word, analysis, known_lemmas=None):
    """Build a word|lemma key from a word and an analysis dict.

    If the analysis is a phrasebook self-analysis (headword == surface word,
    all senses POS=PHRASE) and the inventory's ``known_lemmas`` contain a real
    lemma distinct from the surface word, the phrase senses are routed under
    that lemma instead (so e.g. ``está`` phrase senses merge into ``está|estar``
    rather than creating a dead ``está|está`` entry).
    """
    headword = analysis.get("headword") or analysis.get("lemma")
    default_lemma = headword if isinstance(headword, str) and headword.strip() else word

    if known_lemmas:
        lemmas_lower = {kl.lower() for kl in known_lemmas if isinstance(kl, str) and kl.strip()}
        if (default_lemma.lower() not in lemmas_lower
                and _is_phrase_only_self_analysis(word, analysis)):
            # Use the first real lemma from the inventory (corpus-derived,
            # so it reflects how this surface word is actually used).
            for kl in known_lemmas:
                if isinstance(kl, str) and kl.strip():
                    return "%s|%s" % (word, kl)

    return "%s|%s" % (word, default_lemma)


def split_word_assignments(word, analyses, raw_value, known_lemmas=None):
    """Split a surface-word assignment into per-analysis (word|lemma) keys.

    Uses sense IDs to determine which analysis owns each assignment item.
    Falls back to word|word (or word|inline_lemma) if no analyses are provided.

    Args:
        word: surface word string
        analyses: list of analysis dicts, each with {headword, senses: {id: ...}}
        raw_value: raw assignment value (dict or list)
        known_lemmas: optional list of corpus-derived lemmas for the surface
            word (from word_inventory.json). When provided, phrasebook
            self-analyses are folded into the first known lemma instead of
            creating a ``word|word`` entry.

    Returns:
        dict mapping word|lemma keys to method-keyed assignments
    """
    methods = normalize_assignment_methods(raw_value)
    if not methods:
        return {}

    # Check for inline lemma hint from assignment items
    inline_lemma = None
    for items in methods.values():
        for item in items:
            lemma = item.get("lemma")
            if isinstance(lemma, str) and lemma.strip():
                inline_lemma = lemma.strip()
                break
        if inline_lemma:
            break

    if not analyses:
        fallback_lemma = inline_lemma or word
        return {"%s|%s" % (word, fallback_lemma): deepcopy(methods)}

    # Build mapping: analysis_key -> (set of sense IDs, analysis dict)
    analysis_maps = []
    for a in analyses:
        sense_map = a.get("senses", {})
        sense_ids = set(sense_map.keys()) if isinstance(sense_map, dict) else set()
        analysis_maps.append((analysis_key(word, a, known_lemmas=known_lemmas), sense_ids, a))

    # SpanishDict can expose a plural as both a lexical self-headword and an
    # explicit singular-headword inflection (`besitos|besitos` plus
    # `besitos|besito`). Keep every sense ID, but consolidate both analysis
    # branches onto the singular lemma identity. The same rule removes reverse
    # duplicates on a singular query (`beso|besos` → `beso|beso`).
    plural_redirects = plural_lemma_redirects(analyses)
    if plural_redirects:
        analysis_maps = [
            (
                "%s|%s" % (
                    word,
                    plural_redirects.get(
                        key.split("|", 1)[1], key.split("|", 1)[1]
                    ),
                ),
                sense_ids,
                analysis,
            )
            for key, sense_ids, analysis in analysis_maps
        ]

    # Collapse reflexive/pronominal analyses into base form when both exist.
    # E.g. fumar|fumarse -> fumar|fumar when fumar is also a lemma in this set.
    all_lemmas = {key.split('|', 1)[1] for key, _, _ in analysis_maps}
    redirects = {lem: lem[:-2] for lem in all_lemmas if lem.endswith('se') and lem[:-2] in all_lemmas}
    if redirects:
        analysis_maps = [
            ('%s|%s' % (word, redirects.get(key.split('|', 1)[1], key.split('|', 1)[1])), sids, a)
            for key, sids, a in analysis_maps
        ]

    # Collapse PHRASE-only self-analyses (word|word, all senses POS=PHRASE)
    # into the first real lemma when other lemmas exist. Gated on the phrase
    # predicate so legitimate noun/adverb/interjection analyses whose canonical
    # lemma equals the surface (bebé, sangre, papa, así, ojalá…) are preserved.
    self_key = '%s|%s' % (word, word)
    other_lemmas = [key.split('|', 1)[1] for key, _, _ in analysis_maps if key != self_key]
    if other_lemmas:
        analysis_maps = [
            ('%s|%s' % (word, other_lemmas[0])
             if key == self_key and _is_phrase_only_self_analysis(word, a) else key, sids, a)
            for key, sids, a in analysis_maps
        ]

    # Split assignments by sense ID ownership. Multiple analyses can resolve
    # to the same key (e.g. a phrasebook analysis folded into its verb lemma's
    # key), so merge rather than overwrite on collision.
    split = {}
    for target_key, sense_ids, _ in analysis_maps:
        target_methods = {}
        for method, items in methods.items():
            kept = []
            for item in items:
                sid = item.get("sense")
                if sid and sid in sense_ids:
                    # Preserve every field (provenance prompt_id/run_ts,
                    # example_ids, and any inline pos/translation/lemma) — only
                    # `examples` is normalized. Rebuilding as bare
                    # {sense, examples} previously stripped provenance and
                    # example_ids on every menu-pick during lemma remapping.
                    new_item = deepcopy(item)
                    new_item["examples"] = sorted(set(item.get("examples", [])))
                    kept.append(new_item)
            if kept:
                target_methods[method] = kept
        if target_methods:
            if target_key in split:
                split[target_key] = merge_method_maps(split[target_key], target_methods)
            else:
                split[target_key] = target_methods

    # Off-menu discoveries (gap-fill / sense-discovery) invent senses that live
    # in no analysis's sense_ids, so the menu-based split above skips them. They
    # carry their own inline definition (translation, pos, lemma, type, ...) and
    # must survive consolidation or step_8b can never surface them — route each
    # to word|<inline lemma> (or word|word), preserving all inline fields.
    #
    # Gate on a non-empty inline translation: a genuine discovery always carries
    # one. A stale menu-pick whose sense left the menu has no inline gloss, so it
    # would render blank — leave those dropped, as before.
    placed_sense_ids = set()
    for _, sense_ids, _ in analysis_maps:
        placed_sense_ids |= sense_ids
    for method, items in methods.items():
        leftover_by_key = {}
        for item in items:
            sid = item.get("sense")
            if not sid or sid in placed_sense_ids:
                continue
            if not (item.get("translation") or "").strip():
                continue
            item_lemma = item.get("lemma")
            lemma = (item_lemma.strip()
                     if isinstance(item_lemma, str) and item_lemma.strip() else word)
            kept = dict(item)
            kept["examples"] = sorted(set(item.get("examples", [])))
            leftover_by_key.setdefault("%s|%s" % (word, lemma), []).append(kept)
        for target_key, kept_items in leftover_by_key.items():
            if target_key in split:
                split[target_key] = merge_method_maps(split[target_key], {method: kept_items})
            else:
                split[target_key] = {method: kept_items}

    if split:
        return split

    # No sense IDs matched any analysis — fall back
    fallback_key = "%s|%s" % (word, inline_lemma or word)
    return {fallback_key: deepcopy(methods)}
