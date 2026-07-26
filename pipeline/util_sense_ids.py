"""Helpers for carrying durable sense identity into learner-facing decks.

Sense-menu IDs are the authoritative identity. Assembly may merge duplicate
display rows or union senses across artists; in those cases the first existing
ID remains canonical and every additional source ID is retained as an alias.
"""

import hashlib


def _clean_ids(values):
    seen = set()
    cleaned = []
    for value in values or []:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def carry_sense_identity(target, sense_id=None, aliases=None):
    """Attach an ID without replacing identity already persisted on target."""
    candidates = _clean_ids(
        [target.get("sense_id"), sense_id]
        + list(target.get("sense_id_aliases") or [])
        + list(aliases or [])
    )
    if not candidates:
        return target

    existing = str(target.get("sense_id") or "").strip()
    incoming = str(sense_id or "").strip()
    # Generated IDs stabilize legacy master-only senses immediately. A later
    # authoritative source-menu ID supersedes one, while the generated value
    # remains an alias so existing learner progress still resolves.
    if existing.startswith("generated:") and incoming and not incoming.startswith("generated:"):
        canonical = incoming
    else:
        canonical = existing or candidates[0]
    target["sense_id"] = canonical
    remaining = [value for value in candidates if value != canonical]
    if remaining:
        target["sense_id_aliases"] = remaining
    else:
        target.pop("sense_id_aliases", None)
    return target


def make_generated_sense_id(namespace, *identity_parts):
    """Mint a reproducible fallback ID for a sense with no source-menu ID."""
    normalized = "|".join(
        " ".join(str(value or "").strip().lower().split())
        for value in identity_parts
    )
    digest = hashlib.sha1(f"{namespace}|{normalized}".encode("utf-8")).hexdigest()[:12]
    return f"generated:{namespace}:{digest}"


def merge_sense_identity(target, incoming):
    """Merge canonical/alias IDs from one equivalent sense into another."""
    return carry_sense_identity(
        target,
        incoming.get("sense_id"),
        incoming.get("sense_id_aliases") or [],
    )
