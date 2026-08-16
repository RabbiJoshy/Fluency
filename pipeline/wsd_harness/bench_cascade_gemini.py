#!/usr/bin/env python3
"""Where should a cascade escalate? Sample across tuple-gap deciles and compare
the embedding classifier against Gemini on the same items."""
from __future__ import annotations

import json
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path("/Users/joshuathomasamar/PycharmProjects/Fluency")
S = Path("/private/tmp/claude-501/-Users-joshuathomasamar-PycharmProjects-Fluency"
         "/3fbda742-82e7-4ae2-9ed3-d7fe8df59759/scratchpad")
MODEL = "gemini-3.5-flash-lite"
PER = 30


def key():
    for line in (REPO / ".env").open(encoding="utf-8"):
        k, _, v = line.partition("=")
        if k.strip() == "GEMINI_API_KEY":
            return v.strip().strip('"').strip("'")
    raise SystemExit("no GEMINI_API_KEY")


menus_raw = json.loads((REPO / "Data/Spanish/layers/sense_menu/spanishdict.json")
                       .read_text(encoding="utf-8"))
menus = {w: {s: v for e in entries for s, v in e.get("senses", {}).items()}
         for w, entries in menus_raw.items()}


def tupof(w, s):
    return ((s.get("headword") or w).strip().lower(), (s.get("pos") or "").strip())


rows = json.loads((S / "base.json").read_text())
nt = [r for r in rows if r["n_tup"] > 1 and r["has_target"]]
nt.sort(key=lambda r: -r["tgap"])
rng = random.Random(0)
sample = []
for d in range(10):
    lo, hi = int(len(nt) * d / 10), int(len(nt) * (d + 1) / 10)
    sample += [(f"d{d}", r) for r in rng.sample(nt[lo:hi], PER)]
print(f"sampled {len(sample)} items across 10 tuple-gap deciles, {PER} each", flush=True)

from google import genai              # noqa: E402
from google.genai import types        # noqa: E402

client = genai.Client(api_key=key())
lock = threading.Lock()
done = [0]


def build_prompt(r):
    w = r["word"]
    lines = []
    for sid, s in menus[w].items():
        tr = (s.get("translation") or "").strip() or "(no gloss)"
        ctx = (s.get("context") or "").strip()
        lines.append(f'{sid}\t{s.get("headword","")} ({s.get("pos","")})\t{tr}'
                     + (f"  [{ctx}]" if ctx else ""))
    return f"""You are disambiguating one Spanish word in one sentence.

Sentence: {r['sent']}
Target word as it appears: "{w}"

Candidate senses (id, headword and part of speech, English gloss):
{chr(10).join(lines)}

Pick the single sense id that this occurrence of "{w}" has in this sentence.
The headword matters: a reflexive lemma (ending -se) is correct only if this
occurrence is genuinely reflexive or pronominal.

Reply with ONLY compact JSON: {{"id": "<sense id>", "confident": true|false}}
If no listed sense fits, reply {{"id": null, "confident": false}}."""


def ask(job):
    bucket, r = job
    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=build_prompt(r),
                config=types.GenerateContentConfig(temperature=0,
                                                   max_output_tokens=2000))
            m = re.search(r'\{.*\}', (resp.text or "").strip(), re.S)
            out = json.loads(m.group(0)) if m else {"id": None}
            with lock:
                done[0] += 1
                if done[0] % 50 == 0:
                    print(f"  {done[0]}/{len(sample)}", flush=True)
            return (bucket, r, out.get("id"), bool(out.get("confident")))
        except Exception:
            if attempt == 4:
                return (bucket, r, "__ERROR__", False)
            threading.Event().wait(3 * (attempt + 1))


with ThreadPoolExecutor(8) as ex:
    results = list(ex.map(ask, sample))

agg = {}
for bucket, r, sid, conf in results:
    a = agg.setdefault(bucket, dict(n=0, emb=0, gem=0, none=0, err=0))
    a["n"] += 1
    a["emb"] += r["ok_tup"]
    if sid == "__ERROR__":
        a["err"] += 1
    elif sid is None:
        a["none"] += 1
    elif sid in menus[r["word"]]:
        a["gem"] += tupof(r["word"], menus[r["word"]][sid]) in {tuple(g) for g in r["gold_tups"]}

print(f"\n{'decile':<8}{'n':>5}{'embeddings':>12}{'gemini':>9}{'delta':>9}{'none':>6}{'err':>5}")
cum_e = cum_g = cum_n = 0
for d in range(10):
    a = agg.get(f"d{d}")
    if not a:
        continue
    e, g = a["emb"] / a["n"], a["gem"] / a["n"]
    cum_e += a["emb"]; cum_g += a["gem"]; cum_n += a["n"]
    print(f"d{d:<7}{a['n']:>5}{e:>12.1%}{g:>9.1%}{g-e:>+9.1%}{a['none']:>6}{a['err']:>5}")
print(f"{'ALL':<8}{cum_n:>5}{cum_e/cum_n:>12.1%}{cum_g/cum_n:>9.1%}"
      f"{(cum_g-cum_e)/cum_n:>+9.1%}")
print("\nd0 = most confident by tuple gap, d9 = least.")
json.dump([(b, r["word"], r["sent"], sid, r["ok_tup"]) for b, r, sid, _ in results],
          open(S / "cascade_decile_results.json", "w"), ensure_ascii=False)
