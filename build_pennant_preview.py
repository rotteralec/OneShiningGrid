"""
Build pennant_preview.html — a QA sheet of EVERY school pennant rendered with the same
label-fit logic the game uses (FitLabel: wrap to fewest lines, condense only the wide
line(s)). Sorted worst-fit-first so the tightest names surface at the top. Flags any
school missing a color (would fall back to the default palette).

Re-run this whenever schools are added (new D1, or older seasons):
    python3 build_pennant_preview.py
Reads: school_aliases.csv (canonical universe) + school_colors.csv (colors).
Keep the wrap math below in sync with FitLabel in OneShiningGrid.jsx.
"""
import csv, html as H, json
from pathlib import Path
ROOT = Path(__file__).parent
DEFAULT = {"bg":"#1a1f3a","accent":"#d4a64a","fg":"#f5ecd7"}
FIT_USABLE, FIT_MAXLINE = 53, 85

# --- approximate Georgia bold-italic advance widths (em) for faithful line breaks ---
NARROW="iIjl.'!|"; THIN="ftr()[]"; MID="sczJ"; WIDE="mw"; XWIDE="MW"
def cw(ch):
    if ch in NARROW: return .30
    if ch in THIN:   return .38
    if ch in MID:    return .50
    if ch in WIDE:   return .86
    if ch in XWIDE:  return .92
    if ch == " ":    return .30
    if ch in "-–":   return .36
    if ch.isupper(): return .70
    return .56
def measure(s): return sum(cw(c) for c in s) * 12.0

def segments(text):
    segs=[]
    for wi,word in enumerate([w for w in (text or "").split() if w]):
        cur=""; pieces=[]
        for ch in word:
            cur+=ch
            if ch in "–-": pieces.append(cur); cur=""
        if cur: pieces.append(cur)
        for pi,p in enumerate(pieces): segs.append((p, pi==0 and wi>0))
    return segs
def wrap(text):
    lines=[]; cur=""
    for s,space in segments(text):
        trial = cur + ((" " if (cur and space) else "") + s)
        if cur and measure(trial) > FIT_MAXLINE: lines.append(cur); cur=s
        else: cur=trial
    if cur: lines.append(cur)
    return lines or [""]

def main():
    canon=[]; seen=set()
    for r in csv.DictReader(open(ROOT/"school_aliases.csv", encoding="utf-8-sig")):
        c=(r.get("canonical_name") or "").strip()
        if c and c not in seen: seen.add(c); canon.append(c)
    colors={r["canonical_name"]:r for r in csv.DictReader(open(ROOT/"school_colors.csv", encoding="utf-8-sig"))}

    recs=[]
    for c in canon:
        col=colors.get(c); pal = col or DEFAULT
        lines=wrap(c)
        scales=[min(1.0, FIT_USABLE/measure(l)) if measure(l)>FIT_USABLE else 1.0 for l in lines]
        recs.append({"name":c,"bg":pal["bg"],"accent":pal["accent"],"fg":pal["fg"],
                     "lines":lines,"min":round(min(scales),2),"nl":len(lines),"noColor":col is None})
    # worst-fit first: most condensed, then most lines
    recs.sort(key=lambda r:(r["min"], -r["nl"], r["name"]))

    W=56; LH=13; CLIP="polygon(0 0, 100% 0, 86% 50%, 100% 100%, 0 100%)"
    def svg(r):
        Hh=len(r["lines"])*LH; body=""
        for i,ln in enumerate(r["lines"]):
            nat=measure(ln)
            tl=' textLength="53" lengthAdjust="spacingAndGlyphs"' if nat>FIT_USABLE else ''
            body+=('<text x="28" y="%g" text-anchor="middle"%s font-family="Georgia,serif" font-weight="800" '
                   'font-style="italic" font-size="12" fill="%s">%s</text>'%(i*LH+10.5,tl,r["fg"],H.escape(ln)))
        return '<svg width="%d" height="%d" viewBox="0 0 %d %d" style="display:block;overflow:visible">%s</svg>'%(W,Hh,W,Hh,body)
    def card(r):
        cls="item"+(" cond" if r["min"]<1 else "")+(" multi" if r["nl"]>1 else "")+(" nocolor" if r["noColor"] else "")
        pen=('<div class="pen" style="background:%s;border-left:4px solid %s;clip-path:%s;-webkit-clip-path:%s">'
             '<div class="pk" style="color:%s">PLAYED FOR</div>%s</div>'%(r["bg"],r["accent"],CLIP,CLIP,r["accent"],svg(r)))
        tags=[]
        if r["min"]<1: tags.append("%d%%"%round(r["min"]*100))
        if r["nl"]>1:  tags.append("%dL"%r["nl"])
        if r["noColor"]: tags.append("no color")
        cap='<div class=cap>%s%s</div>'%(H.escape(r["name"]),(" · "+" · ".join(tags)) if tags else "")
        return '<div class="%s">%s%s</div>'%(cls,pen,cap)

    n=len(recs); cond=sum(1 for r in recs if r["min"]<1); multi=sum(1 for r in recs if r["nl"]>1); noc=sum(1 for r in recs if r["noColor"])
    doc=('<!doctype html><meta charset=utf-8><title>All school pennants — label fit QA</title><style>'
    'body{font-family:system-ui,Arial;background:#f3e9cf;margin:0;padding:22px}h1{font-size:18px;margin:0 0 2px}'
    '.sub{font-size:12px;color:#7a6a45;margin-bottom:10px}.bar{margin:8px 0 16px;font-size:12px}'
    '.bar button{font:inherit;border:1px solid #c9b888;background:#fbf4e0;color:#5a4a28;'
    'border-radius:999px;padding:4px 11px;margin-right:6px;cursor:pointer}.bar button.on{background:#3a2f18;color:#f5ecd7}'
    '.sheet{display:flex;flex-wrap:wrap;gap:16px 13px}.item{display:flex;flex-direction:column;align-items:center;width:84px}'
    '.pen{width:84px;height:84px;padding:8px;padding-right:16px;border-radius:8px;display:flex;flex-direction:column;'
    'align-items:center;justify-content:center;text-align:center;overflow:hidden;position:relative;box-sizing:border-box}'
    '.pk{font-size:7px;letter-spacing:.12em;font-weight:700;margin-bottom:3px}'
    '.cap{font-size:9px;color:#5a4a28;margin-top:5px;text-align:center;line-height:1.15;width:96px}'
    '.item.nocolor .cap{color:#b00020;font-weight:700}'
    '</style>'
    '<h1>All school pennants — label fit QA</h1>'
    '<div class=sub>%d schools, worst-fit first. Caption tags: <b>NN%%</b>=most-condensed line, <b>NL</b>=line count, <b>no color</b>=needs a color (using default). '
    'Re-run <code>build_pennant_preview.py</code> after adding schools.</div>'
    '<div class=bar>'
    '<button class=on data-f=all>All (%d)</button>'
    '<button data-f=cond>Condensed (%d)</button>'
    '<button data-f=multi>Multi-line (%d)</button>'
    '<button data-f=nocolor>No color (%d)</button></div>'
    '<div class=sheet id=sheet>%s</div>'
    '<script>var b=document.querySelectorAll(".bar button");b.forEach(function(x){x.onclick=function(){'
    'b.forEach(function(y){y.classList.remove("on")});x.classList.add("on");var f=x.dataset.f;'
    'document.querySelectorAll(".item").forEach(function(it){'
    'it.style.display=(f=="all"||it.classList.contains(f))?"flex":"none";});};});</script>'
    %(n,n,cond,multi,noc,"".join(card(r) for r in recs)))
    (ROOT/"pennant_preview.html").write_text(doc, encoding="utf-8")
    print("wrote pennant_preview.html — %d schools | %d condensed | %d multi-line | %d missing color"%(n,cond,multi,noc))
    if noc: print("MISSING COLOR:", [r["name"] for r in recs if r["noColor"]])

if __name__ == "__main__":
    main()
