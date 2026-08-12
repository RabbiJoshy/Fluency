#!/usr/bin/env python3
"""util_6a_prompt_registry.py — Sense-assignment provenance registry helpers.

Loads ``config/prompt_registry.json`` and resolves ``prompt_id`` join keys that
assignment items carry into human-readable model/family/capability info.

The registry is the single source of truth for "which prompt/model produced this
assignment". Assignment items store only a tiny join key (``prompt_id`` +
``run_ts``); this module resolves the key to the rest of the story.

See docs/design/sense_provenance.md for the design.
"""

import json
import os

# Backfill: the only assignment items we can PROVABLY attribute to the 3.1
# classify-or-propose run are the off-menu proposals, which live under the
# ``gap-fill`` method key (they carry an inline pos/translation/lemma). Bare
# menu-picks look identical across 2.5 and 3.1, so they get ``legacy-unknown``.
BACKFILL_GAPFILL_PROMPT_ID = "sd-cop-v2"
BACKFILL_DEFAULT_PROMPT_ID = "legacy-unknown"

# Go-forward: the current SpanishDict classify-or-propose path. Overridable via
# step_6c's --prompt-id when a new model/prompt lands (mint a registry entry first).
# Lexical WSD only: tagging/entity/construction decisions now belong to their
# own evidence layers.  The model may still propose a missing lexical slang
# gloss, but it no longer owns those routing tags.
CURRENT_SD_PROMPT_ID = "sd-lexical-v2-g31"
CURRENT_SD_POLICY_ID = "artist-lexical-wsd-current"

_DEFAULT_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "prompt_registry.json")

_LEGACY_TIER = 0
def registry_path(explicit=None):
    """Resolve the registry path (explicit arg wins, else the repo default)."""
    return explicit or _DEFAULT_REGISTRY_PATH


def load_registry_document(path=None):
    """Load the complete prompt registry document."""
    p = registry_path(path)
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_registry(path=None):
    """Load the prompt registry, returning ``{prompt_id: {family, capability_tier, model, ...}}``.

    Returns ``{}`` if the file is missing or malformed so callers degrade
    gracefully (assignments still carry their raw prompt_id join keys).
    """
    raw = load_registry_document(path)
    prompts = raw.get("prompts") if isinstance(raw, dict) else None
    return prompts if isinstance(prompts, dict) else {}


def load_prompt_policy(policy_id=CURRENT_SD_POLICY_ID, path=None):
    """Load one named deployment policy from the registry document."""
    policies = load_registry_document(path).get("acceptance_policies") or {}
    policy = policies.get(policy_id) if isinstance(policies, dict) else None
    return policy if isinstance(policy, dict) else {}


def accepted_prompt_ids(policy_id=CURRENT_SD_POLICY_ID, path=None):
    """Return the explicit prompt allowlist for a named deployment policy."""
    return frozenset(load_prompt_policy(policy_id, path).get(
        "accepted_prompt_ids") or [])


def prompt_is_accepted(prompt_id, policy_id=CURRENT_SD_POLICY_ID, path=None):
    return bool(prompt_id and prompt_id in accepted_prompt_ids(policy_id, path))


def backfill_prompt_id_for_method(method):
    """Map a historical method key to a best-effort prompt_id for backfill.

    ``gap-fill`` items are provably the 3.1 classify-or-propose run's off-menu
    proposals; everything else is unrecoverable -> ``legacy-unknown``.
    """
    return (BACKFILL_GAPFILL_PROMPT_ID if method == "gap-fill"
            else BACKFILL_DEFAULT_PROMPT_ID)


def capability_tier(prompt_id, registry=None):
    """Return the integer capability tier for a prompt_id (0 if unknown)."""
    reg = registry if registry is not None else load_registry()
    entry = reg.get(prompt_id) if isinstance(reg, dict) else None
    if isinstance(entry, dict):
        try:
            return int(entry.get("capability_tier", _LEGACY_TIER))
        except (TypeError, ValueError):
            return _LEGACY_TIER
    return _LEGACY_TIER
