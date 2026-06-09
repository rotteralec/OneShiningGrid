"""
Build school_colors.csv from ncaahoopR's ncaa_colors.rda.

  Source : lbenz730/ncaahoopR  (MIT license; colors originate from teamcolorcodes.com)
  Reader : pure-Python RDX3 parser — no R, no pyreadr required.
  Output : school_colors.csv  (canonical_name, bg, accent, fg)
             bg     = primary color
             accent = secondary color (gold fallback if missing/identical to bg)
             fg     = cream or ink, whichever has higher contrast with bg (readable text)

  build_game_data.py reads school_colors.csv; CURATED_PALETTES / DEFAULT_PALETTE remain
  the fallback for any school not present here (defunct / obscure programs).

  READ-ONLY on ncaa_colors.rda and the alias files.
"""
import csv, gzip, re, struct, unicodedata
from pathlib import Path

ROOT        = Path(__file__).parent
RDA         = ROOT / "ncaa_colors.rda"
ALIAS_CSV   = ROOT / "school_aliases.csv"
CONF_SUP    = ROOT / "conference_school_aliases.csv"
DRAFT_SUP   = ROOT / "draft_college_aliases.csv"
COLOR_ALIAS = ROOT / "school_color_aliases.csv"     # canonical_name -> ncaa_name (hand-matched)
OUT_CSV     = ROOT / "school_colors.csv"

CREAM = "#f5ecd7"          # light text — for dark backgrounds
INK   = "#1a1f3a"          # dark text  — for light backgrounds
ACCENT_FALLBACK = "#d4a64a"

# Schools absent from ncaa_colors — direct overrides (user-supplied).
MANUAL_COLORS = {
    "Florida Gulf Coast": ("#002D72", "#007749"),
}
# A handful of ncaa_colors entries store a CSS color word instead of a hex.
CSS_HEX = {
    "navy": "#000080", "gold": "#FFD700", "white": "#FFFFFF", "black": "#000000",
    "purple": "#800080", "yellow": "#FFFF00", "darkgreen": "#006400", "green": "#008000",
    "red": "#FF0000", "blue": "#0000FF", "orange": "#FFA500", "maroon": "#800000",
    "silver": "#C0C0C0", "gray": "#808080", "grey": "#808080",
}

# ----- pure-Python reader for R's RDX3/XDR serialization (a plain data.frame) -----

def read_ncaa_colors(path):
    buf = gzip.decompress(path.read_bytes())
    assert buf[:7] == b"RDX3\nX\n", buf[:10]
    pos = [7]
    def ri():  v = struct.unpack(">i", buf[pos[0]:pos[0]+4])[0]; pos[0]+=4; return v
    def rdf(): v = struct.unpack(">d", buf[pos[0]:pos[0]+8])[0]; pos[0]+=8; return v
    def rbts(n): b = buf[pos[0]:pos[0]+n]; pos[0]+=n; return b
    ri(); ri(); ri(); rbts(ri())          # 3 version ints + encoding string
    refs = []
    class Sym:
        __slots__ = ("name")
        def __init__(s, n): s.name = n
    class Pair:
        __slots__ = ("tag", "car", "cdr")
        def __init__(s, t, a, d): s.tag, s.car, s.cdr = t, a, d
    def item():
        f = ri(); t = f & 0xFF; ha = (f >> 9) & 1; ht = (f >> 10) & 1
        if t == 255: idx = f >> 8; idx = idx if idx else ri(); return refs[idx-1]
        if t in (254, 253, 242, 241, 250, 245, 246, 251, 252): return None
        if t == 1: s = Sym(item()); refs.append(s); return s
        if t in (2, 3, 4, 5, 6, 17):
            at = item() if ha else None; tg = item() if ht else None
            return Pair(tg, item(), item())
        if t == 9:
            n = ri()
            if n == -1: return None
            b = rbts(n)
            try: return b.decode("utf-8")
            except UnicodeDecodeError: return b.decode("latin1")
        if t == 16 or t == 19:
            n = ri(); v = [item() for _ in range(n)]; at = item() if ha else None
            return ("VEC", v, at) if t == 19 else v
        if t in (13, 10):
            n = ri(); v = [ri() for _ in range(n)]; (item() if ha else None); return v
        if t == 14:
            n = ri(); v = [rdf() for _ in range(n)]; (item() if ha else None); return v
        raise ValueError("unhandled R type %d" % t)
    top = item(); objs = {}; nd = top
    while isinstance(nd, Pair):
        if isinstance(nd.tag, Sym): objs[nd.tag.name] = nd.car
        nd = nd.cdr
    _, cols, attr = objs["ncaa_colors"]
    names = None; n2 = attr
    while isinstance(n2, Pair):
        if isinstance(n2.tag, Sym) and n2.tag.name == "names": names = n2.car
        n2 = n2.cdr
    D = {names[k]: cols[k] for k in range(len(names))}
    N = len(cols[0])
    return [{k: D[k][i] for k in D} for i in range(N)]

# ----- helpers -----

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("'", "")
    for ch in ".()–-/&,": s = s.replace(ch, " ")
    return " ".join(s.split())

def to_hex(v):
    if not v: return None
    v = v.strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", v): return v.upper()
    return CSS_HEX.get(v.lower())

def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
def luminance(h):
    return 0.2126*_lin(int(h[1:3],16)) + 0.7152*_lin(int(h[3:5],16)) + 0.0722*_lin(int(h[5:7],16))
def contrast(a, b):
    la, lb = luminance(a), luminance(b); hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
def best_fg(bg):
    return CREAM if contrast(bg, CREAM) >= contrast(bg, INK) else INK

# ----- main -----

def main():
    rows = read_ncaa_colors(RDA)
    by_ncaa_name = {r["ncaa_name"]: (r["primary_color"], r["secondary_color"]) for r in rows}

    alias_rows = list(csv.DictReader(open(ALIAS_CSV, encoding="utf-8-sig")))
    alias = {}
    for r in alias_rows:
        for c in ("canonical_name", "team_file_name", "player_file_name"):
            if (r.get(c) or "").strip(): alias.setdefault(norm(r[c]), r["canonical_name"])
    for fn, col in ((CONF_SUP, "source_school"), (DRAFT_SUP, "source_college")):
        if fn.exists():
            for r in csv.DictReader(open(fn, encoding="utf-8-sig")):
                alias.setdefault(norm(r[col]), r["canonical_name"])
    def resolve(x):
        n = norm(x)
        if n in alias: return alias[n]
        for s in (" university", " college", " univ"):
            if n.endswith(s) and n[:-len(s)].strip() in alias: return alias[n[:-len(s)].strip()]
        return None

    raw = {}   # canonical_name -> (primary, secondary)
    auto = 0
    for r in rows:                                   # 1) auto-match on ncaa_name / espn_name
        c = resolve(r["ncaa_name"]) or resolve(r["espn_name"])
        if c and c not in raw:
            raw[c] = (r["primary_color"], r["secondary_color"]); auto += 1
    sup = 0
    if COLOR_ALIAS.exists():                          # 2) hand-matched supplement
        for r in csv.DictReader(open(COLOR_ALIAS, encoding="utf-8-sig")):
            nn = r["ncaa_name"]
            if nn in by_ncaa_name:
                raw[r["canonical_name"]] = by_ncaa_name[nn]; sup += 1
            else:
                print("WARN: school_color_aliases ncaa_name not found in data:", nn)
    for cn, ps in MANUAL_COLORS.items():             # 3) manual overrides
        raw[cn] = ps

    out, skipped = [], []
    for cn in sorted(raw):
        primary, secondary = raw[cn]
        bg = to_hex(primary)
        if not bg:
            skipped.append((cn, primary)); continue
        accent = to_hex(secondary)
        if not accent or accent == bg: accent = ACCENT_FALLBACK
        out.append((cn, bg, accent, best_fg(bg)))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["canonical_name", "bg", "accent", "fg"])
        w.writerows(out)

    print("ncaa_colors rows read: %d" % len(rows))
    print("matched: %d auto + %d supplement + %d manual" % (auto, sup, len(MANUAL_COLORS)))
    print("wrote %s — %d schools" % (OUT_CSV.name, len(out)))
    if skipped:
        print("SKIPPED (no usable primary color):", skipped)

if __name__ == "__main__":
    main()
