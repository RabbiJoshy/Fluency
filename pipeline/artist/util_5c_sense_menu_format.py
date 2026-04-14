#!/usr/bin/env python3
"""Helpers for artist sense_menu.json surface-word-first format.

Artist sense_menu.json format:
{
  "word": [
    {
      "senses": {
        "abc": {"pos": "VERB", "translation": "..."}
      }
    }
  ]
}

Optional metadata such as ``headword`` may appear on an analysis, but is not
required. Legacy artist format keyed by ``word|lemma`` is still accepted and
converted.
"""

from copy import deepcopy
import hashlib


def normalize_artist_sense_menu(data):
    """Convert legacy artist sense_menu keyed by word|lemma to word->analyses[]."""
    if not isinstance(data, dict):
        return {}
    # Already new format
    if data:
        sample_value = next(iter(data.values()))
        if isinstance(sample_value, list) and sample_value and isinstance(sample_value[0], dict) and "senses" in sample_value[0]:
            return data

    new_data = {}
    for key, value in data.items():
        if "|" in key:
            word, lemma = key.split("|", 1)
        else:
            word, lemma = key, key
        analyses = new_data.setdefault(word, [])
        analyses.append({
            "headword": lemma,
            "senses": deepcopy(value if isinstance(value, dict) else {}),
        })
    return new_data


def get_analyses(menu, word):
    """Return analyses for a word from new or legacy format."""
    if word in menu and isinstance(menu[word], list):
        analyses = menu[word]
        if analyses and isinstance(analyses[0], dict) and "senses" in analyses[0]:
            return analyses
    analyses = []
    prefix = word + "|"
    for key, value in menu.items():
        if key.startswith(prefix):
            _, lemma = key.split("|", 1)
            analyses.append({"headword": lemma, "senses": value if isinstance(value, dict) else {}})
    return analyses


def first_analysis(menu, word):
    analyses = get_analyses(menu, word)
    if analyses:
        return analyses[0]
    return {"senses": {}}


def merge_analysis(menu, word, identity, senses):
    """Merge one word analysis into a normalized artist menu dict."""
    analyses = menu.setdefault(word, [])
    for analysis in analyses:
        existing_identity = analysis.get("headword", analysis.get("lemma"))
        if identity and existing_identity == identity:
            analysis["senses"] = deepcopy(senses)
            if identity:
                analysis.setdefault("headword", identity)
            return
    new_analysis = {"senses": deepcopy(senses)}
    if identity:
        new_analysis["headword"] = identity
    analyses.append(new_analysis)


def assign_analysis_sense_ids(identity, senses_list, used_ids=None):
    """Assign stable IDs that are unique within a menu.

    ``identity`` is optional analysis metadata. If absent, IDs still derive
    from sense content and are uniquified against ``used_ids``.
    """
    result = {}
    used = set(used_ids or ())
    for s in senses_list:
        full_hash = hashlib.md5(
            ("%s|%s|%s" % (identity or "", s["pos"], s["translation"])).encode("utf-8")
        ).hexdigest()
        for length in range(3, len(full_hash) + 1):
            sid = full_hash[:length]
            if sid not in result and sid not in used:
                break
        result[sid] = deepcopy(s)
        used.add(sid)
    return result


def extend_ids_for_extra_senses(existing_ids, identity, senses_list):
    """Generate stable IDs for appended senses without colliding with existing ones."""
    used = set(existing_ids)
    new_ids = []
    for s in senses_list:
        full_hash = hashlib.md5(
            ("%s|%s|%s" % (identity or "", s["pos"], s["translation"])).encode("utf-8")
        ).hexdigest()
        sid = None
        for length in range(3, len(full_hash) + 1):
            candidate = full_hash[:length]
            if candidate not in used:
                sid = candidate
                break
        if sid is None:
            for length in range(3, len(full_hash) + 1):
                candidate = full_hash[:length]
                if candidate not in used or candidate in existing_ids:
                    sid = candidate
                    if candidate not in used:
                        break
        used.add(sid)
        new_ids.append(sid)
    return new_ids


def assign_legacy_sense_ids(senses_list):
    """Assign legacy IDs based only on pos+translation.

    These are the IDs currently referenced by existing artist sense_assignments.
    Use this only when repairing menu files without rerunning step 6.
    """
    result = {}
    for s in senses_list:
        full_hash = hashlib.md5(
            ("%s|%s" % (s["pos"], s["translation"])).encode("utf-8")
        ).hexdigest()
        for length in range(3, len(full_hash) + 1):
            sid = full_hash[:length]
            if sid not in result:
                break
        result[sid] = deepcopy(s)
    return result


def collect_surface_analyses_from_shared_menu(word, shared_menu):
    """Collect all analyses for a surface word from shared sense_menu.json."""
    analyses = []
    prefix = word + "|"
    for key, value in shared_menu.items():
        if not key.startswith(prefix):
            continue
        _, lemma = key.split("|", 1)
        if isinstance(value, dict):
            senses = list(value.values())
        else:
            senses = list(value)
        analyses.append({"headword": lemma, "senses": deepcopy(senses)})
    return analyses


def extract_form_of_targets(analyses):
    """Extract candidate target forms from analysis sense morphology."""
    targets = []
    seen = set()
    for analysis in analyses:
        senses = analysis.get("senses") or []
        if isinstance(senses, dict):
            senses = senses.values()
        for sense in senses:
            morph = sense.get("morphology") if isinstance(sense, dict) else {}
            morph = morph if isinstance(morph, dict) else {}
            for target in morph.get("form_of") or []:
                if not target or target in seen:
                    continue
                seen.add(target)
                targets.append(target)
    return targets


def _analysis_ownership_score(word, identity, sense):
    """Score how strongly a sense belongs to a given analysis identity."""
    morph = sense.get("morphology") if isinstance(sense, dict) else {}
    morph = morph if isinstance(morph, dict) else {}
    form_of = morph.get("form_of") or []
    if not isinstance(form_of, list):
        form_of = [form_of]
    morph_lemma = morph.get("lemma")
    is_form_of = bool(morph.get("is_form_of"))

    score = 0
    if identity in form_of:
        score += 6
    if morph_lemma == identity:
        score += 4
    if identity == word:
        score += 2
    if identity == word and not is_form_of:
        score += 2
    return score


def build_repaired_shared_analyses(word, shared_menu, lookup_fn=None, seed_analyses=None):
    """Build shared analyses with legacy IDs and no cross-lemma ID duplication.

    This is for repairing existing artist sense_menu.json files without
    touching sense_assignments.json. It preserves the current assignment ID
    scheme while ensuring each sense ID belongs to only one lemma analysis.
    """
    raw_analyses = collect_surface_analyses_from_shared_menu(word, shared_menu)
    if not raw_analyses and seed_analyses:
        raw_analyses = deepcopy(seed_analyses)
    if raw_analyses and lookup_fn:
        present_identities = {a.get("headword", a.get("lemma", word)) for a in raw_analyses}
        for target in extract_form_of_targets(raw_analyses):
            if target in present_identities:
                continue
            target_senses = lookup_fn(word, target) or []
            if target_senses:
                raw_analyses.append({"headword": target, "senses": deepcopy(target_senses)})
                present_identities.add(target)
    if not raw_analyses:
        return []

    owners = {}
    analyses = []
    for analysis in raw_analyses:
        identity = analysis.get("headword", analysis.get("lemma", word))
        senses = analysis.get("senses", []) or []
        if isinstance(senses, dict):
            senses = list(senses.values())
        id_map = assign_legacy_sense_ids(senses)
        analyses.append({"headword": identity, "senses": id_map})
        for sid, sense in id_map.items():
            owners.setdefault(sid, []).append((identity, sense))

    chosen_owner = {}
    for sid, candidates in owners.items():
        if len(candidates) == 1:
            chosen_owner[sid] = candidates[0][0]
            continue
        chosen_owner[sid] = max(
            candidates,
            key=lambda item: (_analysis_ownership_score(word, item[0], item[1]), item[0] == word),
        )[0]

    repaired = []
    for analysis in analyses:
        identity = analysis.get("headword", analysis.get("lemma", word))
        kept = {
            sid: deepcopy(sense)
            for sid, sense in analysis.get("senses", {}).items()
            if chosen_owner.get(sid) == identity
        }
        if kept:
            repaired.append({"headword": identity, "senses": kept})
    return repaired


def merge_artist_only_senses(repaired_analyses, existing_analyses):
    """Merge non-en-wikt local senses back into repaired analyses."""
    analysis_map = {
        analysis.get("headword", analysis.get("lemma")): {
            "headword": analysis.get("headword", analysis.get("lemma")),
            "senses": deepcopy(analysis.get("senses", {})),
        }
        for analysis in repaired_analyses
    }

    for analysis in existing_analyses:
        identity = analysis.get("headword", analysis.get("lemma"))
        if not identity:
            continue
        target = analysis_map.setdefault(identity, {"headword": identity, "senses": {}})
        for sid, sense in (analysis.get("senses", {}) or {}).items():
            if not isinstance(sense, dict):
                continue
            if sense.get("source") == "en-wikt":
                continue
            if sid not in target["senses"]:
                target["senses"][sid] = deepcopy(sense)

    return [analysis_map[k] for k in sorted(analysis_map.keys())]


def flatten_analyses_with_ids(analyses):
    """Flatten analyses into classifier menu order while preserving per-analysis IDs."""
    flat_senses = []
    flat_ids = []
    normalized_analyses = []
    used_ids = set()
    for index, analysis in enumerate(analyses):
        identity = analysis.get("headword", analysis.get("lemma")) or ("analysis-%d" % index)
        senses = analysis.get("senses", []) or []
        id_map = assign_analysis_sense_ids(identity, senses, used_ids=used_ids)
        normalized = {"senses": id_map}
        if analysis.get("headword") is not None:
            normalized["headword"] = analysis.get("headword")
        normalized_analyses.append(normalized)
        for sid, sense in id_map.items():
            flat_ids.append(sid)
            flat_senses.append(deepcopy(sense))
            used_ids.add(sid)
    return flat_senses, flat_ids, normalized_analyses


def resolve_analysis_for_assignments(menu, word, assignments):
    """Choose the analysis whose sense IDs best match the selected assignments."""
    analyses = get_analyses(menu, word)
    if not analyses:
        return {"senses": {}}
    if not assignments:
        return analyses[0]

    target_ids = set()
    if isinstance(assignments, dict):
        for items in assignments.values():
            for item in items:
                sid = item.get("sense")
                if sid:
                    target_ids.add(sid)
    elif isinstance(assignments, list):
        for item in assignments:
            sid = item.get("sense")
            if sid:
                target_ids.add(sid)
    if not target_ids:
        return analyses[0]

    def score(analysis):
        senses = analysis.get("senses", {})
        ids = set(senses.keys()) if isinstance(senses, dict) else set()
        return len(ids & target_ids)

    return max(analyses, key=score)
