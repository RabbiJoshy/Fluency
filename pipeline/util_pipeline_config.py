#!/usr/bin/env python3
"""Shared helpers for reading language-level pipeline defaults from config/config.json.

The front-end config at ``config/config.json`` holds per-language metadata
(data paths, CEFR levels, color themes). It also optionally holds
``pipelineDefaults`` per language, which the builder scripts use to set
default CLI-flag values.

Example ``config.json`` slice::

    "spanish": {
      ...,
      "pipelineDefaults": {
        "minPriority": 50
      }
    }

Semantics: missing language, missing ``pipelineDefaults``, or missing
individual key → return *None*, which the caller resolves to its own
safe default. This keeps new languages showing all evidence (including
keyword-tier) until explicitly opted in.
"""

import json
import os
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "config.json")


def load_pipeline_defaults(language):
    """Return the ``pipelineDefaults`` dict for a language, or {} if absent.

    ``language`` is case-insensitive and matched against the keys under
    ``languages`` in ``config.json`` (e.g. "spanish", "french"). Missing
    config file, missing language, or missing ``pipelineDefaults`` all
    return ``{}`` so callers can `.get(key)` without a KeyError.
    """
    if not language:
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return {}
    langs = cfg.get("languages") or {}
    lang_cfg = langs.get(language.lower()) or {}
    defaults = lang_cfg.get("pipelineDefaults") or {}
    return defaults if isinstance(defaults, dict) else {}


def get_default_min_priority(language, fallback=0):
    """Return the default ``--min-priority`` for the given language.

    Spanish opts in to 50 via ``config.json``. Any language that hasn't
    added ``pipelineDefaults.minPriority`` falls back to ``fallback``
    (default 0 = keep everything, safe for new languages).
    """
    defaults = load_pipeline_defaults(language)
    val = defaults.get("minPriority")
    try:
        return int(val) if val is not None else fallback
    except (TypeError, ValueError):
        return fallback
