#!/usr/bin/env python3
"""Self-contained HTML for AUDITING THE TEST HARNESS ITSELF.

Shows every panel sentence, its full sense menu, and which leaves are marked
acceptable — so the labels can be checked. No model, no predictions, no scores.
"""

from __future__ import annotations

import json
import sys

from common import DATA, HERE, LABEL_DIR, load_menu, read_corpus

sys.path.insert(0, str(HERE))
PANELS = ("spanishdict", "opensubtitles", "badbunny")


def build():
    data = {}
    for corpus in PANELS:
        try:
            rows = read_corpus(corpus)
        except SystemExit:
            continue
        menu = load_menu("Bad Bunny" if corpus == "badbunny" else None)
        lp = LABEL_DIR / f"{corpus}.acceptable.jsonl"
        labels = ({r["word"]: r for r in
                   (json.loads(l) for l in open(lp, encoding="utf-8") if l.strip())}
                  if lp.exists() else {})
        items = []
        for r in rows:
            lab = labels.get(r["word"], {})
            acc = lab.get("acceptable", [])
            items.append({
                "word": r["word"], "sentence": r["sentence"], "split": r["split"],
                "gold": r.get("gold"), "acceptable": acc,
                "exclude": bool(lab.get("exclude")),
                "no_answer": bool(lab.get("no_answer")),
                "note": lab.get("note", ""),
                "menu": [{"id": k, "pos": v.get("pos", ""),
                          "tr": (v.get("translation") or "").strip() or "(EMPTY)",
                          "ctx": (v.get("context") or "").strip()}
                         for k, v in menu.get(r["word"], {}).items()],
            })
        items.sort(key=lambda x: x["word"])
        data[corpus] = items
    return data


CSS = """
:root{
 --paper:#f7f6f3; --ink:#141a24; --mut:#646b78; --line:#e2e0da; --card:#fffefb;
 --ok:#1f6b4a; --okbg:#e8f2ec; --okbd:#a8ccb8;
 --warn:#9a5b12; --warnbg:#f8efe2; --warnbd:#dcbb8a;
 --gold:#8a6d1f; --goldbg:#f7f1dd;
 --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
 --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
 --paper:#101319; --ink:#e6e8ee; --mut:#8b93a3; --line:#252a34; --card:#171b23;
 --ok:#5fd39a; --okbg:#122a20; --okbd:#2e5c46;
 --warn:#e2a563; --warnbg:#2a1e10; --warnbd:#5c4526;
 --gold:#d8bd72; --goldbg:#282213;}}
:root[data-theme=dark]{
 --paper:#101319; --ink:#e6e8ee; --mut:#8b93a3; --line:#252a34; --card:#171b23;
 --ok:#5fd39a; --okbg:#122a20; --okbd:#2e5c46;
 --warn:#e2a563; --warnbg:#2a1e10; --warnbd:#5c4526;
 --gold:#d8bd72; --goldbg:#282213;}
:root[data-theme=light]{
 --paper:#f7f6f3; --ink:#141a24; --mut:#646b78; --line:#e2e0da; --card:#fffefb;
 --ok:#1f6b4a; --okbg:#e8f2ec; --okbd:#a8ccb8;
 --warn:#9a5b12; --warnbg:#f8efe2; --warnbd:#dcbb8a;
 --gold:#8a6d1f; --goldbg:#f7f1dd;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--sans);
-webkit-font-smoothing:antialiased}
.wrap{max-width:880px;margin:0 auto;padding:34px 20px 100px}
h1{font:600 25px/1.2 var(--serif);margin:0 0 6px;letter-spacing:-.01em;
text-wrap:balance}
.sub{color:var(--mut);font-size:14px;margin:0 0 22px;max-width:60ch}
.legend{display:flex;flex-direction:column;gap:5px;color:var(--mut);font-size:12.5px;
margin-bottom:20px;padding-left:2px}
.sw{display:inline-block;width:22px;height:12px;border-radius:3px;
vertical-align:-1px;margin-right:8px;border:1px solid transparent}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:0;
position:sticky;top:0;background:var(--paper);padding:12px 0;z-index:5;
border-bottom:1px solid var(--line)}
select,button,input{font:inherit;font-size:13.5px;padding:7px 11px;
border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
select,button{cursor:pointer}
button:hover,select:hover{border-color:var(--mut)}
:focus-visible{outline:2px solid var(--ok);outline-offset:2px}
input{min-width:180px}
.count{color:var(--mut);font-size:12.5px;margin-left:auto;
font-variant-numeric:tabular-nums}
.stats{display:flex;gap:26px;flex-wrap:wrap;margin:18px 0 22px;color:var(--mut);
font-size:11.5px;letter-spacing:.05em;text-transform:uppercase}
.stats b{display:block;color:var(--ink);font:600 21px/1.15 var(--serif);
letter-spacing:0;text-transform:none;font-variant-numeric:tabular-nums}
.item{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:11px 14px;margin-bottom:7px}
.item.flag{border-color:var(--warnbd);background:linear-gradient(
 to right,var(--warnbg) 0 3px,var(--card) 3px)}
.hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;cursor:pointer}
.w{font:600 15px/1.4 var(--serif);min-width:96px}
.sent{flex:1;min-width:210px;font-family:var(--serif);font-size:15px}
.tag{font-size:10.5px;padding:2px 8px;border-radius:4px;font-weight:600;
white-space:nowrap;letter-spacing:.03em;text-transform:uppercase}
.t-ok{background:var(--okbg);color:var(--ok)}
.t-warn{background:var(--warnbg);color:var(--warn)}
.t-mut{background:var(--line);color:var(--mut)}
.menu{margin-top:11px;border-top:1px solid var(--line);padding-top:9px;display:none}
.item.open .menu{display:block}
.leaf{display:flex;gap:10px;padding:4px 9px;border-radius:6px;font-size:13.5px;
align-items:baseline;border:1px solid transparent;margin-left:8px}
.leaf.acc{background:var(--okbg);border-color:var(--okbd)}
.leaf.gold{background:var(--goldbg)}
.leaf.acc.gold{background:var(--okbg);border-color:var(--gold)}
.leaf .pos{color:var(--mut);font-size:10px;min-width:46px;text-transform:uppercase;
letter-spacing:.05em}
.leaf .ctx{color:var(--mut)}
.leaf .mk{margin-left:auto;font-size:10.5px;color:var(--mut);white-space:nowrap}
.note{color:var(--warn);font-size:12.5px;margin:9px 0 0 8px;font-style:italic}
@media (prefers-reduced-motion:no-preference){.item{transition:border-color .12s}}
"""

JS = """
const D=DATA;let cur=Object.keys(D)[0],filt='all',q='';
const $=s=>document.querySelector(s);
function render(){
 const items=D[cur]||[];
 const lab=items.filter(i=>i.acceptable.length||i.no_answer);
 const exc=items.filter(i=>i.exclude);
 const dis=items.filter(i=>i.gold&&i.acceptable.length&&!i.acceptable.includes(i.gold));
 const avg=lab.length?(lab.reduce((a,i)=>a+i.acceptable.length,0)/lab.length).toFixed(1):'-';
 const men=items.length?(items.reduce((a,i)=>a+i.menu.length,0)/items.length).toFixed(1):'-';
 $('#stats').innerHTML=[['sentences',items.length],['labelled',lab.length],
  ['excluded',exc.length],['no right answer',items.filter(i=>i.no_answer).length],['acceptable per sentence',avg],['menu size',men],
  ['differ from dict gold',dis.length]]
  .map(([k,v])=>`<div><b>${v}</b><br>${k}</div>`).join('');
 let show=items;
 if(filt==='unlabelled')show=items.filter(i=>!i.acceptable.length&&!i.no_answer);
 if(filt==='noans')show=items.filter(i=>i.no_answer);
 if(filt==='excluded')show=items.filter(i=>i.exclude);
 if(filt==='differ')show=items.filter(i=>i.gold&&i.acceptable.length&&!i.acceptable.includes(i.gold));
 if(filt==='single')show=items.filter(i=>i.acceptable.length===1);
 if(filt==='wide')show=items.filter(i=>i.acceptable.length>=4);
 if(q)show=show.filter(i=>(i.word+' '+i.sentence).toLowerCase().includes(q));
 $('#list').innerHTML=show.map(i=>{
  const dgold=i.gold&&i.acceptable.length&&!i.acceptable.includes(i.gold);
  const tag=i.exclude?'<span class="tag t-mut">excluded</span>':
   i.no_answer?'<span class="tag t-warn">no right answer in menu</span>':
   !i.acceptable.length?'<span class="tag t-warn">unlabelled</span>':
   `<span class="tag t-ok">${i.acceptable.length} acceptable</span>`;
  const dt=dgold?'<span class="tag t-warn">differs from dict</span>':'';
  const leaves=i.menu.map(m=>{
   const c=['leaf'];const a=i.acceptable.includes(m.id);
   if(a)c.push('acc'); if(m.id===i.gold)c.push('gold');
   const mk=[a?'acceptable':'',m.id===i.gold?'&#9733; dict gold':''].filter(Boolean).join(' &middot; ');
   return `<div class="${c.join(' ')}"><span class=pos>${m.pos}</span>`+
    `<span>${m.tr}${m.ctx?` <span class=ctx>(${m.ctx})</span>`:''}</span>`+
    `${mk?`<span class=mk>${mk}</span>`:''}</div>`;
  }).join('');
  const needsEye=dgold||(!i.acceptable.length&&!i.no_answer&&!i.exclude);
  return `<div class="item ${needsEye?'flag':''}">
   <div class=hd onclick="this.parentNode.classList.toggle('open')">
    <span class=w>${i.word}</span><span class=sent>${i.sentence}</span>${tag}${dt}</div>
   <div class=menu>${leaves}${i.note?`<div class=note>${i.note}</div>`:''}</div></div>`;
 }).join('')||'<p style="color:var(--mut)">nothing matches</p>';
 $('#count').textContent=show.length+' shown';
}
$('#corpus').onchange=e=>{cur=e.target.value;render()};
$('#filter').onchange=e=>{filt=e.target.value;render()};
$('#q').oninput=e=>{q=e.target.value.toLowerCase();render()};
$('#expand').onclick=()=>document.querySelectorAll('.item').forEach(x=>x.classList.add('open'));
$('#collapse').onclick=()=>document.querySelectorAll('.item').forEach(x=>x.classList.remove('open'));
$('#theme').onclick=()=>{const r=document.documentElement;
 r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'};
render();
"""


def main():
    data = build()
    opts = "".join(f'<option value="{c}">{c}</option>' for c in data)
    body = f"""<div class=wrap>
<h1>Test harness &mdash; label audit</h1>
<div class=sub>Every panel sentence with its full sense menu. Green = marked
<b>acceptable</b> for that sentence; anything not green counts as BAD when a method
picks it. This page is for checking the labels, not for looking at results.</div>
<div class=legend>
<span class=sw style="background:var(--okbg);border:1px solid var(--okbd)"></span>acceptable for this sentence<br>
<span class=sw style="background:var(--goldbg)"></span>&#9733; the leaf SpanishDict filed the example under<br>
<b>differs from dict</b> &mdash; I judged the dictionary's own leaf unacceptable. Check these first.
</div>
<div class=bar>
<select id=corpus>{opts}</select>
<select id=filter>
<option value=all>all</option>
<option value=differ>differs from dict gold</option>
<option value=noans>no right answer in menu</option>
<option value=unlabelled>unlabelled</option>
<option value=excluded>excluded</option>
<option value=single>only 1 acceptable</option>
<option value=wide>4+ acceptable</option>
</select>
<input id=q placeholder="search word or sentence">
<button id=expand>expand all</button><button id=collapse>collapse</button>
<button id=theme>theme</button><span class=conf id=count></span>
</div>
<div class=stats id=stats></div>
<div id=list></div>
</div>
<style>{CSS}</style>
<script>const DATA={json.dumps(data, ensure_ascii=True)};{JS}</script>"""
    # ensure_ascii=True escapes every accent to \uXXXX inside the JS string, so the
    # page renders correctly whatever charset the browser guesses. The charset meta
    # is belt and braces for opening the file straight off disk.
    out = DATA / "viewer.html"
    out.write_text('<meta charset="utf-8">\n'
                   "<title>WSD harness &mdash; label audit</title>\n" + body,
                   encoding="utf-8")
    for c, v in data.items():
        print(f"  {c}: {len(v)} sentences, "
              f"{sum(1 for i in v if i['acceptable'])} labelled")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
