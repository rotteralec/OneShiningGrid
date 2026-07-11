"""
   One Shining Grid — independent verification of cbb_team_seasons_master.csv.
   READ-ONLY on every file.

   Re-derives the EXPECTED master directly from the 27 per-season source files
   (1999_teams_consolidated.csv … 2025_teams_consolidated.csv) using a separate
   parse path — Python's csv.reader, not the raw string-splitting the builder
   uses — then compares it to the master the builder produced. The two tools
   parse differently on purpose: a bug shared by both would otherwise hide.

   Checks:
     1  row count          master == sum of source data rows
     2  header             master == Rk,Season,Team,G,W,L,W/L%,... (31 cols)
     3  row content        every master row == its source row (W-dup removed), in order
     4  column counts      every master row has exactly 31 fields
     5  seasons            exactly the 27 expected labels; per-season counts match sources
     6  duplicates         no repeated (Season, Team)
     7  W-dedup lossless   the two W columns were identical in every source row
     8  artifact sweep     no RTF leftovers (\\, {}, control words/chars) in the master

   Exit code 0 = clean, 1 = at least one issue.
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT       = Path(__file__).parent
MASTER_CSV = ROOT / "cbb_team_seasons_master.csv"
SOURCE_PATTERN = re.compile(r"^(\d{4})_teams_consolidated\.csv$")

EXPECTED_MASTER_HEADER = [
    "Rk", "Season", "Team", "G", "W", "L", "W/L%", "MP", "FG", "FGA", "2P", "2PA",
    "3P", "3PA", "FT", "FTA", "ORB", "DRB", "TRB", "AST", "STL", "BLK", "TOV", "PF",
    "PTS", "FG%", "2P%", "3P%", "FT%", "TS%", "eFG%",
]
DUP_W_IDX, KEEP_W_IDX = 3, 5      # positions in the 32-column SOURCE layout


def read_source(path):
    """(season_label, [expected_master_row, ...], w_lossless) via csv.reader.
    Drops the banner row and the header row; for each data row, records whether
    the two W columns match, then removes the duplicate leading W."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        sys.exit(f"  source {path.name}: too few rows ({len(rows)})")
    data = rows[2:]                                  # rows[0]=banner, rows[1]=header
    expected, w_lossless = [], True
    for r in data:
        if len(r) != 32:
            sys.exit(f"  source {path.name}: a row has {len(r)} cols, expected 32")
        if r[DUP_W_IDX] != r[KEEP_W_IDX]:
            w_lossless = False
        expected.append(r[:DUP_W_IDX] + r[DUP_W_IDX + 1:])
    season = data[0][1] if data else "?"
    return season, expected, w_lossless


def main():
    if not MASTER_CSV.exists():
        sys.exit(f"ERROR: {MASTER_CSV.name} not found — run consolidate_team_seasons.py first.")

    sources = sorted(
        (p for p in ROOT.iterdir() if SOURCE_PATTERN.match(p.name)),
        key=lambda p: int(SOURCE_PATTERN.match(p.name).group(1)),
    )
    if not sources:
        sys.exit("ERROR: no {YEAR}_teams_consolidated.csv source files found.")

    # Build the expectation independently from the sources.
    expected_rows, per_season_expected, w_lossless = [], [], True
    for p in sources:
        season, rows, w_ok = read_source(p)
        per_season_expected.append((season, len(rows)))
        expected_rows.extend(rows)
        w_lossless = w_lossless and w_ok

    # Read the master under test.
    with open(MASTER_CSV, encoding="utf-8", newline="") as f:
        master = list(csv.reader(f))
    master_header, master_rows = master[0], master[1:]

    issues = 0
    def check(name, ok, detail=""):
        nonlocal issues
        line = f"  {'PASS' if ok else 'FAIL'}  {name}"
        if detail and not ok:
            line += f"  — {detail}"
        print(line)
        if not ok:
            issues += 1

    print(f"Master: {MASTER_CSV.name}")
    print(f"  {len(master_rows)} rows, {len(master_header)} columns")
    print(f"  rebuilt expectation from {len(sources)} source files "
          f"({per_season_expected[0][0]} … {per_season_expected[-1][0]})\n")

    # 1 — row count
    check(f"row count == {len(expected_rows)}",
          len(master_rows) == len(expected_rows),
          f"master {len(master_rows)} vs expected {len(expected_rows)}")

    # 2 — header
    check("header == expected 31-col schema",
          master_header == EXPECTED_MASTER_HEADER, f"{master_header}")

    # 3 — row content, field-for-field, in order
    if len(master_rows) == len(expected_rows):
        mism = [i for i in range(len(expected_rows)) if master_rows[i] != expected_rows[i]]
        check("every row matches its source (in order)", not mism,
              f"{len(mism)} differ; first at master line {mism[0] + 2 if mism else '-'}")
        if mism:
            i = mism[0]
            print(f"        expected: {expected_rows[i]}")
            print(f"        master:   {master_rows[i]}")
    else:
        check("every row matches its source (in order)", False, "row counts differ")

    # 4 — column counts
    bad = [i for i, r in enumerate(master_rows) if len(r) != 31]
    check("every row has 31 columns", not bad,
          f"{len(bad)} rows off, first at master line {bad[0] + 2 if bad else '-'}")

    # 5 — seasons present + per-season counts
    expected_labels = [f"{y}-{(y + 1) % 100:02d}" for y in range(1999, 2026)]
    season_counts = Counter(r[1] for r in master_rows)
    check("seasons == 27 expected labels (1999-00 … 2025-26)",
          sorted(season_counts) == expected_labels, f"got {sorted(season_counts)}")
    check("per-season counts match each source file",
          all(season_counts.get(s, 0) == n for s, n in per_season_expected))

    # 6 — duplicate (Season, Team)
    pair = Counter((r[1], r[2]) for r in master_rows)
    dups = [p for p, c in pair.items() if c > 1]
    check("no duplicate (Season, Team)", not dups, f"{len(dups)} dups, e.g. {dups[:3]}")

    # 7 — W-dedup losslessness
    check("W de-dup lossless (both W columns equal in every source row)", w_lossless)

    # 8 — RTF artifact sweep
    pats = [("backslash", re.compile(r"\\")),
            ("brace", re.compile(r"[{}]")),
            ("RTF control word", re.compile(r"\\[a-zA-Z]+")),
            ("control char", re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"))]
    art = None
    for r in master_rows:
        for v in r:
            for label, pat in pats:
                if v and pat.search(v):
                    art = (label, r[1], r[2], v)
                    break
            if art:
                break
        if art:
            break
    check("no RTF artifacts in master", art is None, f"{art}")

    # ----- season breakdown (informational) -----
    print("\n  Season breakdown:")
    for s in expected_labels:
        print(f"    {s}  {season_counts.get(s, 0):>4d}")

    print("\n" + "=" * 56)
    print("VERIFICATION PASSED" if issues == 0 else f"VERIFICATION FOUND {issues} ISSUE(S)")
    sys.exit(0 if issues == 0 else 1)


if __name__ == "__main__":
    main()
