"""
   One Shining Grid — team-season master builder (all years → one file).
   READ-ONLY on every source CSV. Writes ONE new file; never touches a source.

   Combines the per-season team files

       1999_teams_consolidated.csv ... 2025_teams_consolidated.csv

   (each: one season, all teams) into a single tidy master

       cbb_team_seasons_master.csv

   one row per (season, team), ready to load straight into a database.

   Two clean-ups vs. the per-season files (both confirmed lossless):
     1. The per-season files carry TWO header rows — a column-group banner
        (",,,,Team Totals,...,Team Shooting") sitting on top of the real
        column names. Only the real column row is kept; the banner is dropped.
     2. The source column header is "Rk,Season,Team,W,G,W,L,W/L%,..." — the
        leading W duplicates the W inside the G/W/L record (verified identical
        in every source row). The duplicate leading W is dropped, leaving the
        standard "Rk,Season,Team,G,W,L,W/L%,..." order (31 columns).

   Re-runnable: rebuilds the master from whatever {YEAR}_teams_consolidated.csv
   files are present. If a future season's two W columns ever disagree, or a
   source header drifts, the build ABORTS rather than silently dropping or
   merging bad data.
"""

import re
import sys
from pathlib import Path

ROOT        = Path(__file__).parent
OUTPUT_NAME = "cbb_team_seasons_master.csv"
OUTPUT_CSV  = ROOT / OUTPUT_NAME

# Per-season source files look like "{YEAR}_teams_consolidated.csv".
SOURCE_PATTERN = re.compile(r"^(\d{4})_teams_consolidated\.csv$")

# Row 2 (the real column header) of every per-season file. The build aborts if a
# source file's header differs from this — schema drift must not be merged.
EXPECTED_SOURCE_HEADER = (
    "Rk,Season,Team,W,G,W,L,W/L%,MP,FG,FGA,2P,2PA,3P,3PA,FT,FTA,ORB,DRB,TRB,"
    "AST,STL,BLK,TOV,PF,PTS,FG%,2P%,3P%,FT%,TS%,eFG%"
)

# In the 32-column source layout, index 3 is the duplicate leading W; index 5 is
# the W of the W/L record that we keep.
DUP_W_IDX  = 3
KEEP_W_IDX = 5


def drop_dup_w(fields):
    """Remove the duplicate leading W (index 3). Caller has already confirmed
    fields[DUP_W_IDX] == fields[KEEP_W_IDX], so this never loses information."""
    return fields[:DUP_W_IDX] + fields[DUP_W_IDX + 1:]


def load_season_file(path):
    """Return list of data-row field-lists for one per-season file.

    Sources contain no quoted/embedded-comma fields — every row is exactly 32
    plain comma-separated fields (asserted below), so a simple split is exact
    and faithful. Aborts on any header drift, wrong column count, or W mismatch.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 3:
        sys.exit(f"ERROR: {path.name} has too few lines ({len(lines)}); expected "
                 f"a banner row, a header row, and at least one data row.")

    # lines[0] = column-group banner (dropped); lines[1] = the real column header.
    header = lines[1]
    if header != EXPECTED_SOURCE_HEADER:
        sys.exit(
            f"ERROR: column header in {path.name} differs from the expected "
            f"schema — refusing to merge.\n  expected: {EXPECTED_SOURCE_HEADER}\n"
            f"  found:    {header}"
        )

    ncols = header.count(",") + 1            # 32
    data = []
    for i, line in enumerate(lines[2:], start=3):
        fields = line.split(",")
        if len(fields) != ncols:
            sys.exit(f"ERROR: {path.name} line {i} has {len(fields)} fields "
                     f"(expected {ncols}): {line[:80]}")
        if fields[DUP_W_IDX] != fields[KEEP_W_IDX]:
            sys.exit(f"ERROR: {path.name} line {i} — the two W columns disagree "
                     f"({fields[DUP_W_IDX]!r} vs {fields[KEEP_W_IDX]!r}); dropping "
                     f"the duplicate would lose a real value. Aborting.")
        data.append(fields)
    return data


def main():
    sources = sorted(
        (p for p in ROOT.iterdir() if SOURCE_PATTERN.match(p.name)),
        key=lambda p: int(SOURCE_PATTERN.match(p.name).group(1)),
    )
    if not sources:
        sys.exit(f"ERROR: no {{YEAR}}_teams_consolidated.csv files found in {ROOT}")

    # Safety: never write over a source file.
    if SOURCE_PATTERN.match(OUTPUT_CSV.name) or OUTPUT_CSV in sources:
        sys.exit(f"ERROR: refusing to write to a source-shaped name: {OUTPUT_NAME}")

    out_header = drop_dup_w(EXPECTED_SOURCE_HEADER.split(","))   # 31 columns
    all_rows   = []
    per_season = []
    for path in sources:
        data = load_season_file(path)
        rows = [drop_dup_w(f) for f in data]
        season = rows[0][1] if rows else "?"
        all_rows.extend(rows)
        per_season.append((season, path.name, len(rows)))

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(out_header) + "\n")
        for fields in all_rows:
            f.write(",".join(fields) + "\n")

    # ----- summary -----
    print(f"Sources: {len(sources)} per-season files "
          f"({per_season[0][0]} … {per_season[-1][0]})")
    for season, name, n in per_season:
        print(f"  {season}  {name:32s} {n:>4d} rows")
    print()
    print(f"Wrote {OUTPUT_NAME} — {len(all_rows)} team-season rows, "
          f"{len(out_header)} columns")
    print(f"Header: {','.join(out_header)}")


if __name__ == "__main__":
    main()
