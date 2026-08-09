"""Persistent opaque identities for learner-facing cards.

Display properties such as surface form, lemma, gloss, and POS are aliases or
claims, not primary keys. The registry preserves an existing card ID across an
exact alias change when occurrence evidence (or an unambiguous surface alias)
shows that the logical card is the same. Ambiguous splits require an explicit
reconciliation instead of silently moving learner progress.
"""

import json
from pathlib import Path

from pipeline.util_evidence_store import canonical_json


SCHEMA = "fluency.card_identity_registry.v1"
SENSE_SCHEMA = "fluency.sense_identity_registry.v1"


def _alias(surface, lemma):
    return {
        "surface": str(surface or "").strip().lower(),
        "lemma": str(lemma or "").strip().lower(),
    }


def _alias_key(surface, lemma):
    value = _alias(surface, lemma)
    return value["surface"], value["lemma"]


class CardIdentityRegistry:
    def __init__(self, language, records=None, migrations=None):
        self.language = str(language or "und").strip().lower()
        self.records = records or {}
        self.migrations = migrations or []

    @classmethod
    def load(cls, path, language):
        path = Path(path)
        if not path.exists():
            return cls(language)
        with open(path, encoding="utf-8") as file:
            payload = json.load(file)
        if payload.get("schema") != SCHEMA:
            raise ValueError("Unsupported card identity registry schema")
        stored_language = payload.get("language") or language
        if str(stored_language).lower() != str(language).lower():
            raise ValueError("Card identity registry language mismatch")
        return cls(stored_language, payload.get("records"), payload.get("migrations"))

    def _active_records(self):
        return {
            card_id: record for card_id, record in self.records.items()
            if record.get("status", "active") == "active"
        }

    def _alias_index(self):
        result = {}
        for card_id, record in self._active_records().items():
            for value in record.get("aliases") or []:
                result[_alias_key(value.get("surface"), value.get("lemma"))] = card_id
        return result

    def seed(self, card_id, surface, lemma, evidence_ids=None):
        """Register an existing externally visible ID without renumbering it."""
        card_id = str(card_id)
        key = _alias_key(surface, lemma)
        owner = self._alias_index().get(key)
        if owner and owner != card_id:
            raise ValueError("Card alias %r already belongs to %s" % (key, owner))
        record = self.records.setdefault(card_id, {
            "card_id": card_id,
            "status": "active",
            "aliases": [],
            "evidence_ids": [],
        })
        alias_value = _alias(surface, lemma)
        if alias_value not in record["aliases"]:
            record["aliases"].append(alias_value)
        for evidence_id in evidence_ids or []:
            if evidence_id and evidence_id not in record["evidence_ids"]:
                record["evidence_ids"].append(evidence_id)
        return card_id

    def resolve(self, surface, lemma, evidence_ids=None, claimed_ids=None,
                allow_inference=True):
        """Resolve a candidate conservatively; return ``None`` if ambiguous."""
        claimed_ids = set(claimed_ids or [])
        exact = self._alias_index().get(_alias_key(surface, lemma))
        if exact:
            return exact
        if not allow_inference:
            return None

        evidence = set(evidence_ids or [])
        if evidence:
            overlaps = []
            for card_id, record in self._active_records().items():
                overlap = len(evidence & set(record.get("evidence_ids") or []))
                if overlap and card_id not in claimed_ids:
                    overlaps.append((overlap, card_id))
            if overlaps:
                best_overlap = max(score for score, _ in overlaps)
                winners = [card_id for score, card_id in overlaps if score == best_overlap]
                if len(winners) == 1:
                    return winners[0]

        surface_key = _alias(surface, "")["surface"]
        surface_matches = {
            card_id
            for card_id, record in self._active_records().items()
            if card_id not in claimed_ids and any(
                _alias(value.get("surface"), "")["surface"] == surface_key
                for value in record.get("aliases") or []
            )
        }
        return next(iter(surface_matches)) if len(surface_matches) == 1 else None

    def assign(self, surface, lemma, evidence_ids, preferred_id,
               claimed_ids=None, allow_inference=True):
        """Resolve or seed one candidate, preserving a caller-minted fallback."""
        card_id = self.resolve(
            surface, lemma, evidence_ids=evidence_ids, claimed_ids=claimed_ids,
            allow_inference=allow_inference)
        card_id = card_id or str(preferred_id)
        self.seed(card_id, surface, lemma, evidence_ids=evidence_ids)
        return card_id

    def merge(self, source_id, target_id, reason):
        """Explicitly merge identities while retaining a progress migration."""
        if source_id == target_id:
            return
        source = self.records[source_id]
        target = self.records[target_id]
        # Retire the source before rebinding its aliases so the active alias
        # index no longer reports the source as their owner.
        source["status"] = "merged"
        source["superseded_by"] = target_id
        for value in source.get("aliases") or []:
            self.seed(target_id, value.get("surface"), value.get("lemma"))
        for evidence_id in source.get("evidence_ids") or []:
            if evidence_id not in target.setdefault("evidence_ids", []):
                target["evidence_ids"].append(evidence_id)
        self.migrations.append({
            "kind": "merge",
            "from": source_id,
            "to": target_id,
            "reason": reason,
        })

    def to_dict(self):
        return {
            "schema": SCHEMA,
            "language": self.language,
            "records": self.records,
            "migrations": self.migrations,
        }

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as file:
            file.write(canonical_json(self.to_dict()))
            file.write("\n")
        temp_path.replace(path)


def _sense_descriptor(card_id, pos, translation, context):
    normalize = lambda value: " ".join(str(value or "").strip().casefold().split())
    return {
        "card_id": str(card_id),
        "pos": normalize(pos).upper(),
        "translation": normalize(translation),
        "context": normalize(context),
    }


class SenseIdentityRegistry:
    """Persist sense IDs while treating gloss/POS/context as mutable labels."""

    def __init__(self, language, records=None):
        self.language = str(language or "und").strip().lower()
        self.records = records or {}

    @classmethod
    def load(cls, path, language):
        path = Path(path)
        if not path.exists():
            return cls(language)
        with open(path, encoding="utf-8") as file:
            payload = json.load(file)
        if payload.get("schema") != SENSE_SCHEMA:
            raise ValueError("Unsupported sense identity registry schema")
        if str(payload.get("language") or language).lower() != str(language).lower():
            raise ValueError("Sense identity registry language mismatch")
        return cls(payload.get("language") or language, payload.get("records"))

    @staticmethod
    def _entity_key(card_id, sense_id):
        return "%s::%s" % (card_id, sense_id)

    def _active_for_card(self, card_id):
        return {
            key: record for key, record in self.records.items()
            if record.get("status", "active") == "active"
            and record.get("card_id") == str(card_id)
        }

    def seed(self, sense_id, card_id, pos, translation, context=None,
             external_ids=None, evidence_ids=None):
        sense_id = str(sense_id)
        key = self._entity_key(card_id, sense_id)
        record = self.records.setdefault(key, {
            "sense_id": sense_id,
            "card_id": str(card_id),
            "status": "active",
            "labels": [],
            "external_ids": [],
            "evidence_ids": [],
        })
        descriptor = _sense_descriptor(card_id, pos, translation, context)
        label = {key: value for key, value in descriptor.items() if key != "card_id"}
        if label not in record["labels"]:
            record["labels"].append(label)
        for external_id in [sense_id] + list(external_ids or []):
            external_id = str(external_id or "").strip()
            if external_id and external_id not in record["external_ids"]:
                record["external_ids"].append(external_id)
        for evidence_id in evidence_ids or []:
            if evidence_id and evidence_id not in record["evidence_ids"]:
                record["evidence_ids"].append(evidence_id)
        return sense_id

    def _resolve_exact(self, candidate):
        records = self._active_for_card(candidate["card_id"])
        external_ids = set(candidate.get("external_ids") or [])
        if external_ids:
            matches = [
                record["sense_id"] for record in records.values()
                if external_ids & set(record.get("external_ids") or [])
            ]
            if len(set(matches)) == 1:
                return matches[0]
        descriptor = _sense_descriptor(
            candidate["card_id"], candidate.get("pos"),
            candidate.get("translation"), candidate.get("context"))
        label = {key: value for key, value in descriptor.items() if key != "card_id"}
        matches = [
            record["sense_id"] for record in records.values()
            if label in (record.get("labels") or [])
        ]
        return matches[0] if len(set(matches)) == 1 else None

    def reconcile(self, card_id, candidates):
        """Resolve a batch one-to-one; ambiguous splits get new preferred IDs."""
        card_id = str(card_id)
        normalized = []
        for candidate in candidates:
            row = dict(candidate)
            row["card_id"] = card_id
            row["external_ids"] = list(dict.fromkeys(
                [row.get("preferred_id")] + list(row.get("external_ids") or [])
            ))
            normalized.append(row)

        resolved = {}
        claimed = set()
        for index, candidate in enumerate(normalized):
            exact = self._resolve_exact(candidate)
            if exact and exact not in claimed:
                resolved[index] = exact
                claimed.add(exact)

        # Evidence reconciliation is accepted only when candidate and prior
        # sense choose each other uniquely. This prevents a changed classifier
        # from arbitrarily handing a split sense's progress to the first row.
        proposals = {}
        for index, candidate in enumerate(normalized):
            if index in resolved:
                continue
            evidence = set(candidate.get("evidence_ids") or [])
            scores = []
            for record in self._active_for_card(card_id).values():
                if record["sense_id"] in claimed:
                    continue
                overlap = len(evidence & set(record.get("evidence_ids") or []))
                if overlap:
                    scores.append((overlap, record["sense_id"]))
            if scores:
                best = max(score for score, _sense_id in scores)
                winners = [sense_id for score, sense_id in scores if score == best]
                if len(winners) == 1:
                    proposals[index] = winners[0]
        reverse = {}
        for index, sense_id in proposals.items():
            reverse.setdefault(sense_id, []).append(index)
        for sense_id, indices in reverse.items():
            if len(indices) == 1:
                resolved[indices[0]] = sense_id
                claimed.add(sense_id)

        results = []
        for index, candidate in enumerate(normalized):
            sense_id = resolved.get(index) or str(candidate["preferred_id"])
            self.seed(
                sense_id,
                card_id,
                candidate.get("pos"),
                candidate.get("translation"),
                candidate.get("context"),
                external_ids=candidate.get("external_ids"),
                evidence_ids=candidate.get("evidence_ids"),
            )
            results.append(sense_id)
        return results

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SENSE_SCHEMA,
            "language": self.language,
            "records": self.records,
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        temp_path.replace(path)
