#!/usr/bin/env python3
"""Routing-tag dashboard generator (multi-source).

Gathers, for every word each source's pipeline routes, the tags it currently
carries from EACH source layer (word_routing bucket, english_loanwords,
cognates, detected_proper_nouns, spanish_forms, en_50k, corpus_count,
translation), flags the interesting conflicts, and writes ONE self-contained
interactive HTML with a source dropdown (artist decks + normal/"speech" mode
per language). Switch source instantly; sort/filter/search; toggle ANY number
of "should-be" tags per word (multi-evidence); export a per-source corrections
JSON that the next routing audit reads.

Usage:
  .venv/bin/python3 pipeline/artist/tool_4a_tag_dashboard.py            # all sources
  .venv/bin/python3 pipeline/artist/tool_4a_tag_dashboard.py --only "Bad Bunny"
"""
import argparse, json, os, html, datetime
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# What the user can assert a word SHOULD be (multi-select; resolves to a bucket later).
CORRECTION_TAGS = ["spanish_word", "loanword", "english", "cognate", "proper_noun", "noise"]


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _as_set(x):
    if isinstance(x, dict):
        return set(x.keys())
    if isinstance(x, list):
        return set(x)
    return set()


def _load_en50k():
    s = set()
    p = os.path.join(ROOT, "Data", "English", "en_50k_wordlist.txt")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                tok = line.strip().split()
                if tok:
                    s.add(tok[0].lower())
    return s


def discover_sources():
    """Return [{key,label,mode,routing,layers,shared,deck}] for every source
    that has a word_routing.json (the thing this dashboard audits)."""
    out = []
    # Artist decks
    artists_cfg = _load(os.path.join(ROOT, "config", "artists.json"), {})
    for slug, cfg in (artists_cfg.items() if isinstance(artists_cfg, dict) else []):
        lang = (cfg.get("language") or "spanish").title()
        adir = None
        # config paths vary; find the artist dir by walking Artists/<lang>/<Name>
        base = os.path.join(ROOT, "Artists", (cfg.get("language") or "spanish"))
        name = cfg.get("name") or slug
        cand = os.path.join(base, name)
        if os.path.isdir(cand):
            adir = cand
        if not adir:
            continue
        routing = os.path.join(adir, "data", "known_vocab", "word_routing.json")
        if not os.path.isfile(routing):
            continue
        acfg = _load(os.path.join(adir, "artist.json"), {})
        deck = os.path.join(adir, acfg.get("vocabulary_file", ""))
        out.append({
            "key": "artist:%s" % slug, "label": "%s (lyrics)" % name, "mode": "lyrics",
            "routing": routing, "layers": os.path.join(adir, "data", "layers"),
            "shared": os.path.join(ROOT, "Data", lang, "layers"), "deck": deck,
        })
    # Normal / speech mode per language
    for lang in ("Spanish", "French", "Dutch"):
        routing = os.path.join(ROOT, "Data", lang, "layers", "word_routing.json")
        if not os.path.isfile(routing):
            continue
        out.append({
            "key": "speech:%s" % lang.lower(), "label": "%s (speech)" % lang, "mode": "speech",
            "routing": routing, "layers": os.path.join(ROOT, "Data", lang, "layers"),
            "shared": os.path.join(ROOT, "Data", lang, "layers"),
            "deck": os.path.join(ROOT, "Data", lang, "vocabulary.json"),
        })
    return out


def gather(src, en50k):
    routing = _load(src["routing"])
    excl = routing.get("exclude", {}) or {}
    clf = routing.get("classifier", {}) or {}

    bucket = {}
    for name, words in excl.items():
        for w in _as_set(words):
            bucket[w] = "exclude." + name
    for name, words in clf.items():
        for w in _as_set(words):
            bucket.setdefault(w, "classifier." + name)
    for w in _as_set(routing.get("sense_discovery")):
        bucket.setdefault(w, "sense_discovery")
    for w in _as_set(routing.get("clitic_merge")):
        bucket.setdefault(w, "clitic_merge")

    loanwords = _as_set(_load(os.path.join(src["layers"], "english_loanwords.json"))) \
        or _as_set(_load(os.path.join(src["shared"], "english_loanwords.json")))
    cognates = _as_set(_load(os.path.join(src["layers"], "cognates.json")))
    detected_pn = _as_set(_load(os.path.join(src["layers"], "detected_proper_nouns.json")))
    spanish_forms = _load(os.path.join(src["shared"], "spanish_forms.json"), {})

    counts, trans = {}, {}
    deck = _load(src["deck"], [])
    if isinstance(deck, dict):
        deck = list(deck.values())
    for e in deck if isinstance(deck, list) else []:
        if not isinstance(e, dict):
            continue
        w = e.get("word")
        if not w:
            continue
        counts[w] = e.get("corpus_count", counts.get(w, 0))
        if w not in trans:
            m = (e.get("meanings") or [{}])[0]
            trans[w] = e.get("translation") or m.get("meaning") or m.get("translation") or ""

    rows = []
    for w in sorted(bucket, key=lambda x: -counts.get(x, 0)):
        wl = w.lower()
        sf_pos = spanish_forms.get(wl) or spanish_forms.get(w)
        t = trans.get(w, "")
        row = {
            "word": w, "count": counts.get(w, 0), "bucket": bucket.get(w, ""),
            "loanword": wl in loanwords, "cognate": wl in cognates,
            "detected_pn": wl in detected_pn or w in detected_pn,
            "spanish_form": bool(sf_pos),
            "sf_pos": ",".join(sf_pos) if isinstance(sf_pos, (list, set)) else (sf_pos or ""),
            "en50k": wl in en50k, "translation": t,
            "word_eq_trans": bool(t) and t.strip().lower() == wl,
        }
        flags = []
        is_excl = row["bucket"].startswith("exclude")
        is_clf = row["bucket"].startswith("classifier") or row["bucket"] == "sense_discovery"
        if row["loanword"] and row["bucket"] != "exclude.english":
            flags.append("loanword-layer-unrouted")
        if is_clf and (row["loanword"] or (row["en50k"] and row["word_eq_trans"])):
            flags.append("missed-loanword")
        if row["en50k"] and row["spanish_form"] and (row["loanword"] or row["word_eq_trans"]):
            flags.append("homograph-en-es")
        if row["detected_pn"] and row["bucket"] != "exclude.proper_nouns":
            flags.append("propn-detected-unrouted")
        if row["bucket"] == "exclude.proper_nouns" and row["spanish_form"]:
            flags.append("propn-maybe-wrong")
        if is_excl and row["count"] >= 10:
            flags.append("high-count-excluded")
        row["flags"] = flags
        rows.append(row)
    buckets = sorted({b for b in bucket.values()})
    return rows, buckets


HTML_TMPL = """<!doctype html><html><head><meta charset="utf-8"><title>Routing tags</title>
<style>
:root{{color-scheme:dark}}
body{{font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;background:#14151a;color:#e6e6ea;margin:0;padding:16px}}
h1{{font-size:17px;margin:0 0 10px;display:flex;gap:10px;align-items:center}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}}
button,select,input{{background:#23252e;color:#e6e6ea;border:1px solid #363a45;border-radius:6px;padding:5px 9px;font:inherit}}
button:hover{{border-color:#5b6270;cursor:pointer}} button.on{{background:#3a4a6b;border-color:#5b74b0}}
select#src{{font-size:15px;padding:6px 10px}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:4px 8px;border-bottom:1px solid #262932;text-align:left;white-space:nowrap;vertical-align:top}}
th{{position:sticky;top:0;background:#1b1d24;cursor:pointer;user-select:none}} tr:hover td{{background:#1a1c22}}
.tag{{display:inline-block;padding:1px 6px;border-radius:10px;font-size:11px;margin:1px 3px 1px 0}}
.t-loan{{background:#5a3a1a;color:#ffcf9e}} .t-cog{{background:#1a4a3a;color:#9effcf}} .t-pn{{background:#3a1a4a;color:#e0aeff}}
.t-sf{{background:#1a2a4a;color:#9ec3ff}} .t-en{{background:#4a3a1a;color:#ffe09e}} .t-eq{{background:#4a1a1a;color:#ff9e9e}}
.flag{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px;background:#5a1a1a;color:#ffbdbd;margin:1px 3px 1px 0}}
.chip{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;margin:1px 3px 1px 0;border:1px solid #3a3f4b;background:#20222a;color:#aab;cursor:pointer;user-select:none}}
.chip.on{{background:#2f7d4f;border-color:#4fbf7f;color:#dfffe9}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}} .muted{{color:#8a909a}}
tr.edited td{{background:#20261f!important}} .cnt{{color:#9aa0aa;font-size:12px}}
</style></head><body>
<h1>Routing tags · <select id="src"></select> <span id="meta" class="muted" style="font-size:12px"></span></h1>
<div class="bar">
  <input id="q" placeholder="filter word / translation…" style="min-width:200px">
  <button data-f="all" class="on">All</button>
  <button data-f="flagged">Conflicts</button>
  <span class="muted">|</span>
  <button data-f="missed-loanword">missed-loanword</button>
  <button data-f="homograph-en-es">homograph en/es</button>
  <button data-f="loanword-layer-unrouted">loanword-unrouted</button>
  <button data-f="propn-detected-unrouted">propn-unrouted</button>
  <button data-f="propn-maybe-wrong">propn-maybe-wrong</button>
  <button data-f="high-count-excluded">high-count-excluded</button>
  <span style="flex:1"></span>
  <button id="export">Export corrections (<span id="c-edit">0</span>)</button>
</div>
<div style="overflow:auto;max-height:calc(100vh - 130px)">
<table id="tbl"><thead><tr>
  <th data-k="corr">✎</th><th data-k="word">word</th><th data-k="count" class="num">count</th>
  <th data-k="bucket">current bucket</th><th data-k="tags">tags now</th><th data-k="flags">conflicts</th>
  <th data-k="translation">translation</th><th>should be (toggle any)</th>
</tr></thead><tbody id="tb"></tbody></table>
</div>
<script>
const ALL={all};                 // {{sourceKey: {{label, rows}}}}
const CORR={corr};               // correction tag vocabulary
const state={{src:Object.keys(ALL)[0],f:"all",q:"",sort:"count",dir:-1,edits:{{}}}};
// edits: {{sourceKey: {{word: [tags]}}}}
const tb=document.getElementById("tb"), sel=document.getElementById("src");
Object.entries(ALL).forEach(([k,v])=>{{const o=document.createElement("option");o.value=k;o.textContent=v.label+" · "+v.rows.length+" words, "+v.rows.filter(r=>r.flags.length).length+" flagged";sel.appendChild(o);}});
function rows(){{return ALL[state.src].rows;}}
function edits(){{return state.edits[state.src]||(state.edits[state.src]={{}});}}
function tagsHtml(r){{let s="";if(r.loanword)s+='<span class="tag t-loan">loanword</span>';if(r.cognate)s+='<span class="tag t-cog">cognate</span>';if(r.detected_pn)s+='<span class="tag t-pn">detected-PN</span>';if(r.spanish_form)s+='<span class="tag t-sf">es-form'+(r.sf_pos?":"+r.sf_pos:"")+'</span>';if(r.en50k)s+='<span class="tag t-en">en-50k</span>';if(r.word_eq_trans)s+='<span class="tag t-eq">word=trans</span>';return s||'<span class="muted">—</span>';}}
function match(r){{if(state.q){{const q=state.q.toLowerCase();if(!(r.word.toLowerCase().includes(q)||(r.translation||"").toLowerCase().includes(q)))return false;}}if(state.f==="all")return true;if(state.f==="flagged")return r.flags.length>0;return r.flags.includes(state.f);}}
function sortVal(r,k){{if(k==="tags")return (r.loanword?8:0)+(r.cognate?4:0)+(r.detected_pn?2:0)+(r.en50k?1:0);if(k==="flags")return r.flags.length;if(k==="corr")return (edits()[r.word]||[]).length;return r[k];}}
function render(){{
  let rs=rows().filter(match);
  rs.sort((a,b)=>{{let x=sortVal(a,state.sort),y=sortVal(b,state.sort);if(x<y)return -state.dir;if(x>y)return state.dir;return 0;}});
  const E=edits();
  tb.innerHTML=rs.slice(0,4000).map(r=>{{
    const chips=CORR.map(c=>`<span class="chip ${{(E[r.word]||[]).includes(c)?'on':''}}" data-tag="${{c}}" data-w="${{r.word}}">${{c}}</span>`).join("");
    const fl=r.flags.map(f=>`<span class="flag">${{f}}</span>`).join("")||'<span class="muted">—</span>';
    return `<tr class="${{(E[r.word]||[]).length?'edited':''}}">
      <td class="num">${{(E[r.word]||[]).length||''}}</td><td><b>${{r.word}}</b></td><td class="num">${{r.count}}</td>
      <td class="cnt">${{r.bucket}}</td><td>${{tagsHtml(r)}}</td><td>${{fl}}</td>
      <td class="muted">${{(r.translation||"").slice(0,40)}}</td><td>${{chips}}</td></tr>`;
  }}).join("");
  document.getElementById("c-edit").textContent=Object.keys(E).length;
  document.getElementById("meta").textContent="— toggle any number of should-be tags per word";
}}
tb.addEventListener("click",e=>{{const chip=e.target.closest(".chip");if(!chip)return;const w=chip.dataset.w,t=chip.dataset.tag,E=edits();const s=new Set(E[w]||[]);s.has(t)?s.delete(t):s.add(t);if(s.size)E[w]=[...s];else delete E[w];render();}});
sel.onchange=()=>{{state.src=sel.value;render();}};
document.querySelectorAll(".bar button[data-f]").forEach(b=>b.onclick=()=>{{state.f=b.dataset.f;document.querySelectorAll(".bar button[data-f]").forEach(x=>x.classList.toggle("on",x===b));render();}});
document.getElementById("q").oninput=e=>{{state.q=e.target.value;render();}};
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{{const k=th.dataset.k;if(state.sort===k)state.dir*=-1;else{{state.sort=k;state.dir=-1;}}render();}});
document.getElementById("export").onclick=()=>{{
  const E=edits(),R=rows();
  const out={{source:state.src,label:ALL[state.src].label,generated:"{stamp}",corrections:Object.entries(E).map(([word,should_be])=>{{const r=R.find(d=>d.word===word)||{{}};return {{word,current_bucket:r.bucket,tags_now:{{loanword:!!r.loanword,cognate:!!r.cognate,detected_pn:!!r.detected_pn,spanish_form:!!r.spanish_form,en50k:!!r.en50k}},should_be,flags:r.flags||[]}};}})}};
  const blob=new Blob([JSON.stringify(out,null,2)],{{type:"application/json"}});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="routing_corrections_"+state.src.replace(/[^a-z0-9]+/gi,"_")+".json";a.click();
}};
render();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="Substring filter on source label")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "routing_tags_dashboard.html"))
    args = ap.parse_args()
    en50k = _load_en50k()
    sources = discover_sources()
    if args.only:
        sources = [s for s in sources if args.only.lower() in s["label"].lower()]
    all_data = {}
    for s in sources:
        rows, buckets = gather(s, en50k)
        all_data[s["key"]] = {"label": s["label"], "rows": rows}
        flagged = sum(1 for r in rows if r["flags"])
        print("%-24s %5d words  %4d flagged" % (s["label"], len(rows), flagged))
        c = Counter(f for r in rows for f in r["flags"])
        for k, v in c.most_common():
            print("    %-26s %d" % (k, v))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    page = HTML_TMPL.format(
        all=json.dumps(all_data, ensure_ascii=False),
        corr=json.dumps(CORRECTION_TAGS),
        stamp=datetime.date.today().isoformat(),
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print("\nWrote %s (%d sources)" % (args.out, len(all_data)))


if __name__ == "__main__":
    main()
