# Run from the project root with:  make -C "Bad Bunny"
# Or from inside Bad Bunny/:      make

ROOT   := ..
PYTHON := $(ROOT)/.venv/bin/python3

.PHONY: all translations

# ─── Main target ─────────────────────────────────────────────────────────────

all: BadBunnyvocabulary.json

# ─── Pipeline steps ──────────────────────────────────────────────────────────

# Step 2: tokenise & count words
intermediates/2_vocab_evidence.json: $(wildcard bad_bunny_genius/batch_*.json)
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/2_count_words.py" \
		--batch_glob "Bad Bunny/bad_bunny_genius/batch_*.json" \
		--out "Bad Bunny/intermediates/2_vocab_evidence.json"

# Step 3: merge Caribbean s-elisions
intermediates/3_vocab_evidence_merged.json: intermediates/2_vocab_evidence.json
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/3_merge_elisions.py"

# Step 4: spaCy lemmas + POS tags  (slow — ~10 min)
intermediates/4_spacy_output.json: intermediates/3_vocab_evidence_merged.json
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/4_add_spacy_info.py"

# Steps 5-9: translations → dedup → cognates → rerank
# Run as one block; also updates the cache so hex IDs are preserved next run.
BadBunnyvocabulary.json: intermediates/4_spacy_output.json intermediates/old_vocabulary_cache.json
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/5_add_translations.py"
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/7_dedup_same_word.py"
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/8_flag_cognates.py"
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/9_rerank.py"
	cp BadBunnyvocabulary.json intermediates/old_vocabulary_cache.json

# ─── Optional: fill translation gaps (slow, live API calls) ─────────────────

translations:
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/6_fill_translation_gaps.py"
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/7_dedup_same_word.py"
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/8_flag_cognates.py"
	cd $(ROOT) && PYTHONUNBUFFERED=1 $(PYTHON) "Bad Bunny/9_rerank.py"
	cp BadBunnyvocabulary.json intermediates/old_vocabulary_cache.json
