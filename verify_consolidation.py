r"""
   One Shining Grid — independent verification of the consolidated CSV.

   READ-ONLY on every source file. The goal here is to catch any way the
   consolidator could have corrupted, lost, or invented data.

   Verification approach (different from the consolidator on purpose, so a
   shared bug is less likely):
     1. For each source .rtf, scan its bytes line-by-line and pull out the
        lines that look like CSV data rows (start with "N," for integer N).
     2. Decode RTF character escapes (\'XX, \uNNNN) inside those lines.
     3. Compare the resulting rows to the consolidated CSV — same count,
        same content, same order.
     4. Sweep the consolidated CSV for any leftover RTF artifacts.
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT       = Path(__file__).parent
INPUT_DIR  = ROOT / "2024RawCBBPlayerData"
OUTPUT_CSV = ROOT / "2024_players_consolidated.csv"

# ----- RTF ESCAPE DECODE (only the character escapes, line-by-line) ------

# Inside an individual data row the RTF uses:
#   \'XX     — single CP1252 byte (used for accents, em-dashes)
#   \uNNNN   — Unicode codepoint, may be preceded by \ucM (fallback count)
# We don't process any control words other than these — data rows don't
# contain any other RTF markup.
RE_UC   = re.compile(r"\\uc\d+ ?")           # \ucN with at most one trailing space
RE_U    = re.compile(r"\\u(-?\d+) ?")        # \uNNNN with at most one trailing space
RE_HEX  = re.compile(r"\\'([0-9a-fA-F]{2})") # \'XX

def decode_line(line):
    line = RE_UC.sub("", line)
    line = RE_U.sub(lambda m: chr(int(m.group(1)) + (65536 if int(m.group(1)) < 0 else 0)), line)
    line = RE_HEX.sub(lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", errors="replace"), line)
    return line

# A data row in the source .rtf looks like:
#   "1,Eric Dixon,815,2024-25,Villanova,...,eric-dixon-1\"
# That is: starts with a digit, ends with a trailing "\" (the RTF paragraph
# terminator). We use that combination as the signature.
DATA_ROW_RE = re.compile(r"^(\d+,.*)\\$")

def extract_rows_from_rtf(rtf_path):
    text = rtf_path.read_text(encoding="utf-8", errors="replace")

    header = None
    data_rows = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()

        # Header line — "Rk,Player" sits inline after the RTF preamble on the
        # first content line, so we find the substring rather than expecting
        # the line to start with it. The trailing "\" is the RTF paragraph
        # terminator and gets dropped.
        if header is None and "Rk,Player" in line:
            header_part = line[line.index("Rk,Player"):].rstrip("\\").rstrip()
            header = decode_line(header_part)
            continue

        # Data rows: integer prefix + trailing backslash.
        m = DATA_ROW_RE.match(line)
        if m:
            data_rows.append(decode_line(m.group(1)))

    return header, data_rows


def numeric_key(path):
    m = re.search(r"-(\d+)\.rtf$", path.name)
    return int(m.group(1)) if m else 10**9

# ----- CHECKS -------------------------------------------------------------

def main():
    if not OUTPUT_CSV.exists():
        print(f"ERROR: {OUTPUT_CSV.name} not found"); sys.exit(1)

    # Load the consolidated CSV both as raw lines and as parsed rows.
    raw_lines = OUTPUT_CSV.read_text(encoding="utf-8").splitlines()
    consolidated_header = raw_lines[0]
    consolidated_data_lines = raw_lines[1:]
    with open(OUTPUT_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        consolidated_rows = list(reader)
        fieldnames = reader.fieldnames

    print(f"Consolidated CSV: {len(consolidated_data_lines)} data rows, {len(fieldnames)} columns")
    print()

    # Independently re-extract from every source .rtf.
    rtf_files = sorted(INPUT_DIR.glob("*.rtf"), key=numeric_key)
    expected_header = None
    expected_data_lines = []
    per_file = []
    header_variants = {}
    for rtf_path in rtf_files:
        header, rows = extract_rows_from_rtf(rtf_path)
        if expected_header is None:
            expected_header = header
        if header != expected_header:
            header_variants.setdefault(header, []).append(rtf_path.name)
        expected_data_lines.extend(rows)
        per_file.append((rtf_path.name, len(rows)))

    print(f"Independently extracted: {len(expected_data_lines)} data rows")
    print()

    issues = 0
    notes = 0

    # ----- CHECK 1: per-file row counts ----------------------------------
    print("CHECK 1 — Per-file row counts (independent re-extract)")
    expected_total = sum(n for _, n in per_file)
    for name, n in per_file:
        print(f"  {name:18s} {n:>5d}")
    print(f"  TOTAL              {expected_total:>5d}")
    if expected_total != len(consolidated_data_lines):
        issues += 1
        print(f"  FAIL: consolidated has {len(consolidated_data_lines)} rows, expected {expected_total}")
    else:
        print(f"  PASS: matches consolidated ({len(consolidated_data_lines)})")
    print()

    # ----- CHECK 2: header byte-for-byte match --------------------------
    print("CHECK 2 — Header byte-for-byte match")
    if expected_header == consolidated_header:
        print("  PASS")
    else:
        issues += 1
        print("  FAIL")
        print(f"    expected: {expected_header}")
        print(f"    actual:   {consolidated_header}")
    if header_variants:
        issues += 1
        print(f"  FAIL: {len(header_variants)} different header variants across files:")
        for h, files in header_variants.items():
            print(f"    in {files[:3]}{'...' if len(files)>3 else ''}: {h[:80]}")
    print()

    # ----- CHECK 3: every data line byte-for-byte match ------------------
    print("CHECK 3 — Every data line byte-for-byte match")
    if len(expected_data_lines) != len(consolidated_data_lines):
        issues += 1
        print(f"  FAIL: row count differs (independent={len(expected_data_lines)}, consolidated={len(consolidated_data_lines)})")
    else:
        mismatches = []
        for i in range(len(expected_data_lines)):
            if expected_data_lines[i] != consolidated_data_lines[i]:
                mismatches.append(i)
        if not mismatches:
            print(f"  PASS: all {len(consolidated_data_lines)} rows match independently-extracted data")
        else:
            issues += 1
            print(f"  FAIL: {len(mismatches)} rows differ. First few:")
            for i in mismatches[:5]:
                print(f"    row {i+2}:")
                print(f"      expected: {expected_data_lines[i][:140]}")
                print(f"      actual:   {consolidated_data_lines[i][:140]}")
    print()

    # ----- CHECK 4: no leftover RTF artifacts in consolidated CSV --------
    print("CHECK 4 — No leftover RTF artifacts in any field")
    patterns = [
        ("backslash",        re.compile(r"\\")),
        ("brace",            re.compile(r"[{}]")),
        ("RTF control word", re.compile(r"\\[a-zA-Z]+")),
        ("hex escape",       re.compile(r"\\'[0-9a-fA-F]{2}")),
        ("unicode escape",   re.compile(r"\\u-?\d+")),
        ("uc control",       re.compile(r"\\uc\d+")),
        ("control char",     re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")),
    ]
    artifacts_found = False
    for label, pat in patterns:
        hits = []
        for row in consolidated_rows:
            for col, val in row.items():
                if val and pat.search(val):
                    hits.append((row.get("Rk"), row.get("Player"), col, val))
                    if len(hits) >= 5: break
            if len(hits) >= 5: break
        if hits:
            artifacts_found = True
            issues += 1
            print(f"  FAIL: {label} — examples:")
            for rk, player, col, val in hits:
                print(f"    Rk {rk} {player!r}  col={col!r}  val={val!r}")
    if not artifacts_found:
        print("  PASS: no backslashes, braces, control words, escapes, or non-printables in any cell")
    print()

    # ----- CHECK 5: numeric columns parse, percent columns valid --------
    print("CHECK 5 — Numeric columns parse as integers/floats (blanks allowed for pct cols)")
    integer_cols = ["Rk", "G", "GS", "MP", "FG", "FGA", "2P", "2PA", "3P", "3PA",
                    "FT", "FTA", "ORB", "DRB", "TRB", "AST", "STL", "BLK", "TOV", "PF"]
    pct_cols = ["FG%", "2P%", "3P%", "FT%", "TS%", "eFG%"]
    int_bad = []
    pct_bad = []
    blank_int = []
    for row in consolidated_rows:
        for col in integer_cols:
            v = row.get(col, "")
            if v == "":
                blank_int.append((row["Rk"], row["Player"], col))
            else:
                try: int(v)
                except ValueError:
                    int_bad.append((row["Rk"], row["Player"], col, v))
        for col in pct_cols:
            v = row.get(col, "")
            if v == "":
                continue
            try: float(v)
            except ValueError:
                pct_bad.append((row["Rk"], row["Player"], col, v))
    if int_bad:
        issues += 1
        print(f"  FAIL: {len(int_bad)} integer fields don't parse:")
        for rk, p, c, v in int_bad[:5]:
            print(f"    Rk {rk} {p!r} col={c} val={v!r}")
    if pct_bad:
        issues += 1
        print(f"  FAIL: {len(pct_bad)} percent fields don't parse:")
        for rk, p, c, v in pct_bad[:5]:
            print(f"    Rk {rk} {p!r} col={c} val={v!r}")
    if blank_int:
        notes += 1
        print(f"  NOTE: {len(blank_int)} blanks in integer columns (likely source-data gaps, not parsing errors):")
        for rk, p, c in blank_int[:5]:
            print(f"    Rk {rk} {p!r} col={c}")
    if not (int_bad or pct_bad):
        print("  PASS: all populated numeric cells parse cleanly")
    print()

    # ----- CHECK 6: Player-additional slug pattern -----------------------
    # BBRef slugs are lowercase, hyphen-separated, can contain digits.
    # We allow periods because names like "Jacob St. Clair" → "jacob-st.-clair-1"
    # exist in the source (a real BBRef artifact, not a bug).
    print("CHECK 6 — Player-additional slug pattern")
    slug_pat = re.compile(r"^[a-z0-9.]+(-[a-z0-9.]+)*$")
    bad_slugs = [r for r in consolidated_rows if not slug_pat.match(r["Player-additional"])]
    if not bad_slugs:
        print("  PASS: all slugs are lowercase alphanumeric (with hyphens/periods allowed)")
    else:
        issues += 1
        print(f"  FAIL: {len(bad_slugs)} slugs don't match expected pattern:")
        for r in bad_slugs[:10]:
            print(f"    Rk {r['Rk']} {r['Player']!r}  slug={r['Player-additional']!r}")
    print()

    # ----- CHECK 7: column count per row --------------------------------
    print("CHECK 7 — Every row has the same column count as the header")
    expected_cols = consolidated_header.count(",") + 1
    bad_count = [(i, line) for i, line in enumerate(consolidated_data_lines)
                 if line.count(",") + 1 != expected_cols]
    if not bad_count:
        print(f"  PASS: all {len(consolidated_data_lines)} rows have {expected_cols} columns")
    else:
        issues += 1
        print(f"  FAIL: {len(bad_count)} rows have wrong column count:")
        for i, line in bad_count[:5]:
            print(f"    line {i+2}: {line.count(',')+1} cols: {line[:120]}")
    print()

    # ----- CHECK 8: Season values ---------------------------------------
    print("CHECK 8 — Season values")
    seasons = Counter(r["Season"] for r in consolidated_rows)
    print(f"  Seasons present: {dict(seasons)}")
    if set(seasons) == {"2024-25"}:
        print("  PASS: all rows are 2024-25")
    else:
        issues += 1
        print("  FAIL: unexpected season values present")
    print()

    # ----- CHECK 9: Rk runs 1..N contiguously ---------------------------
    print("CHECK 9 — Rk sequence is contiguous 1..N")
    rks = [int(r["Rk"]) for r in consolidated_rows]
    if rks == list(range(1, len(consolidated_rows) + 1)):
        print(f"  PASS: Rk runs 1..{len(rks)}")
    else:
        notes += 1
        # Find first diff
        for i, rk in enumerate(rks):
            if rk != i + 1:
                print(f"  NOTE: first non-sequential Rk at position {i+1}: got {rk}")
                break
    print()

    # ----- CHECK 10: duplicate slugs ------------------------------------
    print("CHECK 10 — Duplicate Player-additional slugs in consolidated")
    slug_counts = Counter(r["Player-additional"] for r in consolidated_rows)
    dupes = [(s, c) for s, c in slug_counts.items() if c > 1]
    if not dupes:
        print("  PASS: every slug appears exactly once")
    else:
        notes += 1
        print(f"  NOTE: {len(dupes)} slugs appear more than once (could be legitimate mid-season transfers):")
        for s, c in dupes[:10]:
            teams = [r["Team"] for r in consolidated_rows if r["Player-additional"] == s]
            print(f"    {s} x{c}: teams={teams}")
    print()

    # ----- CHECK 11: PTS column appears twice in header (BBRef quirk) ---
    # Verify both PTS columns in every row contain the same value — if they
    # diverge that signals a parsing problem.
    print("CHECK 11 — Duplicate PTS column has consistent values across both positions")
    pts_idx = [i for i, c in enumerate(consolidated_header.split(",")) if c == "PTS"]
    if len(pts_idx) != 2:
        notes += 1
        print(f"  NOTE: expected PTS twice in header, found {len(pts_idx)}")
    else:
        bad_pts = []
        for i, line in enumerate(consolidated_data_lines):
            cells = line.split(",")
            if cells[pts_idx[0]] != cells[pts_idx[1]]:
                bad_pts.append((i, cells[pts_idx[0]], cells[pts_idx[1]], line[:120]))
        if not bad_pts:
            print(f"  PASS: both PTS columns identical in all {len(consolidated_data_lines)} rows")
        else:
            issues += 1
            print(f"  FAIL: {len(bad_pts)} rows have divergent PTS values:")
            for i, a, b, raw in bad_pts[:5]:
                print(f"    line {i+2}: pts0={a!r} pts1={b!r} :: {raw}")
    print()

    # ----- CHECK 12: total raw .rtf scan finds N data rows --------------
    # Brute count: how many lines in all the .rtf files match the data-row
    # signature? Must equal the consolidated row count.
    print("CHECK 12 — Brute count of data-shaped lines across all source files")
    total = 0
    for rtf_path in rtf_files:
        for raw_line in rtf_path.read_text(encoding="utf-8", errors="replace").split("\n"):
            if DATA_ROW_RE.match(raw_line.rstrip()):
                total += 1
    print(f"  Found {total} data-shaped lines across {len(rtf_files)} files")
    if total == len(consolidated_data_lines):
        print(f"  PASS: matches consolidated row count")
    else:
        issues += 1
        print(f"  FAIL: consolidated has {len(consolidated_data_lines)}")
    print()

    # ----- SUMMARY ------------------------------------------------------
    print("=" * 60)
    if issues == 0:
        print(f"VERIFICATION PASSED — {len(consolidated_data_lines)} rows match source byte-for-byte")
        if notes:
            print(f"({notes} informational note(s) above — not bugs, just observations)")
    else:
        print(f"VERIFICATION FOUND {issues} ISSUE(S) — see details above")

if __name__ == "__main__":
    main()
