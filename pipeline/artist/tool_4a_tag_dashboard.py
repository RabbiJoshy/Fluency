#!/usr/bin/env python3
"""Routing-tag dashboard generator.

Gathers, for every word an artist's pipeline routes, the tags it currently
carries from EACH source layer (word_routing bucket, english_loanwords,
cognates, detected_proper_nouns, spanish_forms, en_50k, corpus_count,
translation), flags the interesting conflicts, and writes a self-contained
interactive HTML table. The table sorts/filters client-side, lets you mark a
row "wrong" and pick a corrected bucket, and exports those edits to a JSON
that the next routing audit reads.

Usage:
  .venv/bin/python3 pipeline/artist/tool_4a_tag_dashboard.py \
      --artist-dir "Artists/spanish/Bad Bunny"
"""
import argparse, json, os, html

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def gather(artist_dir):
    kv = os.path.join(artist_dir, "data", "known_vocab", "word_routing.json")
    layers = os.path.join(artist_dir, "data", "layers")
    sp_layers = os.path.join(ROOT, "Data", "Spanish", "layers")

    routing = _load(kv)
    excl = routing.get("exclude", {}) or {}
    clf = routing.get("classifier", {}) or {}
    sense_disc = _as_set(routing.get("sense_discovery"))
    clitic_merge = _as_set(routing.get("clitic_merge"))

    # word -> current routing bucket (the decision today)
    bucket = {}
    for name, words in excl.items():
        for w in _as_set(words):
            bucket[w] = "exclude." + name
    for name, words in clf.items():
        for w in _as_set(words):
            bucket.setdefault(w, "classifier." + name)
    for w in sense_disc:
        bucket.setdefault(w, "sense_discovery")
    for w in clitic_merge:
        bucket.setdefault(w, "clitic_merge")

    # Tag-source layers
    loanwords = _as_set(_load(os.path.join(layers, "english_loanwords.json")))
    if not loanwords:
        loanwords = _as_set(_load(os.path.join(sp_layers, "english_loanwords.json")))
    cognates = _as_set(_load(os.path.join(layers, "cognates.json")))
    detected_pn = _as_set(_load(os.path.join(layers, "detected_proper_nouns.json")))
    spanish_forms = _load(os.path.join(sp_layers, "spanish_forms.json"), {})  # {word: [pos]}

    en50k = set()
    p = os.path.join(ROOT, "Data", "English", "en_50k_wordlist.txt")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                tok = line.strip().split()
                if tok:
                    en50k.add(tok[0].lower())

    # corpus_count + translation from the deck monolith (best-effort)
    counts, trans = {}, {}
    cfg = _load(os.path.join(artist_dir, "artist.json"), {})
    vfile = cfg.get("vocabulary_file", "")
    deck = _load(os.path.join(artist_dir, vfile)) if vfile else []
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
            "word": w,
            "count": counts.get(w, 0),
            "bucket": bucket.get(w, ""),
            "loanword": wl in loanwords,
            "cognate": wl in cognates,
            "detected_pn": wl in detected_pn or w in detected_pn,
            "spanish_form": bool(sf_pos),
            "sf_pos": ",".join(sf_pos) if isinstance(sf_pos, (list, set)) else (sf_pos or ""),
            "en50k": wl in en50k,
            "translation": t,
            "word_eq_trans": bool(t) and t.strip().lower() == wl,
        }
        flags = []
        is_excl = row["bucket"].startswith("exclude")
        is_clf = row["bucket"].startswith("classifier") or row["bucket"] == "sense_discovery"
        # loanword layer says English but routing didn't exclude it
        if row["loanword"] and row["bucket"] != "exclude.english":
            flags.append("loanword-layer-unrouted")
        # routed as teachable but looks English
        if is_clf and (row["loanword"] or (row["en50k"] and row["word_eq_trans"])):
            flags.append("missed-loanword")
        # English word that is ALSO a Spanish form AND carries a real English
        # signal (the lean class). Bare "en50k AND spanish_form" over-fires on
        # no/me/son/a/y, so require a loanword-layer hit or word==translation.
        if row["en50k"] and row["spanish_form"] and (row["loanword"] or row["word_eq_trans"]):
            flags.append("homograph-en-es")
        # detected proper noun not routed as one
        if row["detected_pn"] and row["bucket"] != "exclude.proper_nouns":
            flags.append("propn-detected-unrouted")
        # excluded as proper noun but is a known Spanish verb/adj (over-tag)
        if row["bucket"] == "exclude.proper_nouns" and row["spanish_form"]:
            flags.append("propn-maybe-wrong")
        # excluded but common
        if is_excl and row["count"] >= 10:
            flags.append("high-count-excluded")
        row["flags"] = flags
        rows.append(row)
    return rows, sorted({b for b in bucket.values()})


HTML_TMPL = """<!doctype html><html><head><meta charset="utf-8">
<title>Routing tags — {artist}</title>
<style>
:root{{color-scheme:dark}}
body{{font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;background:#14151a;color:#e6e6ea;margin:0;padding:16px}}
h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#9aa0aa;margin:0 0 12px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}}
button,select,input{{background:#23252e;color:#e6e6ea;border:1px solid #363a45;border-radius:6px;padding:5px 9px;font:inherit}}
button:hover{{border-color:#5b6270;cursor:pointer}} button.on{{background:#3a4a6b;border-color:#5b74b0}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:4px 8px;border-bottom:1px solid #262932;text-align:left;white-space:nowrap}}
th{{position:sticky;top:0;background:#1b1d24;cursor:pointer;user-select:none}} tr:hover td{{background:#1a1c22}}
.tag{{display:inline-block;padding:1px 6px;border-radius:10px;font-size:11px;margin-right:3px}}
.t-loan{{background:#5a3a1a;color:#ffcf9e}} .t-cog{{background:#1a4a3a;color:#9effcf}} .t-pn{{background:#3a1a4a;color:#e0aeff}}
.t-sf{{background:#1a2a4a;color:#9ec3ff}} .t-en{{background:#4a3a1a;color:#ffe09e}} .t-eq{{background:#4a1a1a;color:#ff9e9e}}
.flag{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px;background:#5a1a1a;color:#ffbdbd;margin-right:3px}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}} .muted{{color:#8a909a}}
tr.wrong{{background:#331a1a!important}} .cnt{{color:#9aa0aa;font-size:12px}}
select.fix{{padding:2px 4px;font-size:12px}}
</style></head><body>
<h1>Routing tags — {artist}</h1>
<p class="sub">Every routed word and the tags it carries at each source. Click a header to sort. Flag a row as wrong and pick the bucket it should be in, then <b>Export corrections</b> — that JSON feeds the next routing audit.</p>
<div class="bar">
  <input id="q" placeholder="filter word / translation…" style="min-width:200px">
  <button data-f="all" class="on">All (<span id="c-all"></span>)</button>
  <button data-f="flagged">Conflicts only (<span id="c-flag"></span>)</button>
  <span class="muted">| flag:</span>
  <button data-f="missed-loanword">missed-loanword</button>
  <button data-f="homograph-en-es">homograph en/es</button>
  <button data-f="loanword-layer-unrouted">loanword-unrouted</button>
  <button data-f="propn-detected-unrouted">propn-unrouted</button>
  <button data-f="high-count-excluded">high-count-excluded</button>
  <span style="flex:1"></span>
  <button id="export">Export corrections (<span id="c-wrong">0</span>)</button>
</div>
<div style="overflow:auto;max-height:calc(100vh - 130px)">
<table id="tbl"><thead><tr>
  <th data-k="wrong">✗</th><th data-k="word">word</th><th data-k="count" class="num">count</th>
  <th data-k="bucket">current bucket</th><th data-k="tags">tags</th><th data-k="flags">conflicts</th>
  <th data-k="translation">translation</th><th>fix → bucket</th>
</tr></thead><tbody id="tb"></tbody></table>
</div>
<script>
const DATA={data};
const BUCKETS={buckets};
const state={{f:"all",q:"",sort:"count",dir:-1,wrong:{{}}}};
const tb=document.getElementById("tb");
function tagsHtml(r){{let s="";if(r.loanword)s+='<span class="tag t-loan">loanword</span>';if(r.cognate)s+='<span class="tag t-cog">cognate</span>';if(r.detected_pn)s+='<span class="tag t-pn">detected-PN</span>';if(r.spanish_form)s+='<span class="tag t-sf">es-form'+(r.sf_pos?":"+r.sf_pos:"")+'</span>';if(r.en50k)s+='<span class="tag t-en">en-50k</span>';if(r.word_eq_trans)s+='<span class="tag t-eq">word=trans</span>';return s||'<span class="muted">—</span>';}}
function match(r){{
  if(state.q){{const q=state.q.toLowerCase();if(!(r.word.toLowerCase().includes(q)||(r.translation||"").toLowerCase().includes(q)))return false;}}
  if(state.f==="all")return true; if(state.f==="flagged")return r.flags.length>0; return r.flags.includes(state.f);
}}
function sortVal(r,k){{if(k==="tags")return (r.loanword?8:0)+(r.cognate?4:0)+(r.detected_pn?2:0)+(r.en50k?1:0);if(k==="flags")return r.flags.length;if(k==="wrong")return state.wrong[r.word]?1:0;return r[k];}}
function render(){{
  let rows=DATA.filter(match);
  rows.sort((a,b)=>{{let x=sortVal(a,state.sort),y=sortVal(b,state.sort);if(x<y)return -state.dir;if(x>y)return state.dir;return 0;}});
  tb.innerHTML=rows.slice(0,4000).map(r=>{{
    const opts=['<option value="">—</option>'].concat(BUCKETS.map(b=>`<option ${{state.wrong[r.word]===b?'selected':''}}>${{b}}</option>`)).join("");
    const fl=r.flags.map(f=>`<span class="flag">${{f}}</span>`).join("")||'<span class="muted">—</span>';
    return `<tr class="${{state.wrong[r.word]!==undefined?'wrong':''}}" data-w="${{r.word}}">
      <td><input type="checkbox" ${{state.wrong[r.word]!==undefined?'checked':''}} data-chk="${{r.word}}"></td>
      <td><b>${{r.word}}</b></td><td class="num">${{r.count}}</td>
      <td class="cnt">${{r.bucket}}</td><td>${{tagsHtml(r)}}</td><td>${{fl}}</td>
      <td class="muted">${{(r.translation||"").slice(0,40)}}</td>
      <td><select class="fix" data-fix="${{r.word}}">${{opts}}</select></td></tr>`;
  }}).join("");
  document.getElementById("c-all").textContent=DATA.length;
  document.getElementById("c-flag").textContent=DATA.filter(r=>r.flags.length).length;
  document.getElementById("c-wrong").textContent=Object.keys(state.wrong).length;
}}
tb.addEventListener("change",e=>{{
  if(e.target.dataset.chk!==undefined){{const w=e.target.dataset.chk;if(e.target.checked)state.wrong[w]=state.wrong[w]||"";else delete state.wrong[w];render();}}
  if(e.target.dataset.fix!==undefined){{const w=e.target.dataset.fix;state.wrong[w]=e.target.value;render();}}
}});
document.querySelectorAll(".bar button[data-f]").forEach(b=>b.onclick=()=>{{state.f=b.dataset.f;document.querySelectorAll(".bar button[data-f]").forEach(x=>x.classList.toggle("on",x===b));render();}});
document.getElementById("q").oninput=e=>{{state.q=e.target.value;render();}};
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{{const k=th.dataset.k;if(state.sort===k)state.dir*=-1;else{{state.sort=k;state.dir=-1;}}render();}});
document.getElementById("export").onclick=()=>{{
  const out={{artist:"{artist}",generated:"{stamp}",corrections:Object.entries(state.wrong).map(([word,should_be])=>{{const r=DATA.find(d=>d.word===word)||{{}};return {{word,current_bucket:r.bucket,should_be,flags:r.flags}};}})}};
  const blob=new Blob([JSON.stringify(out,null,2)],{{type:"application/json"}});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="routing_corrections.json";a.click();
}};
render();
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    artist_dir = os.path.abspath(args.artist_dir)
    cfg = _load(os.path.join(artist_dir, "artist.json"), {})
    artist = cfg.get("name") or os.path.basename(artist_dir)
    rows, buckets = gather(artist_dir)
    out = args.out or os.path.join(artist_dir, "data", "reports", "routing_tags_dashboard.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    import datetime
    page = HTML_TMPL.format(
        artist=html.escape(artist),
        data=json.dumps(rows, ensure_ascii=False),
        buckets=json.dumps(buckets),
        stamp=datetime.date.today().isoformat(),
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    flagged = sum(1 for r in rows if r["flags"])
    print("Wrote %s (%d words, %d flagged)" % (out, len(rows), flagged))
    # quick top-line counts per flag
    from collections import Counter
    c = Counter(f for r in rows for f in r["flags"])
    for k, v in c.most_common():
        print("  %-26s %d" % (k, v))


if __name__ == "__main__":
    main()
