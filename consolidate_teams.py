"""
   One Shining Grid — team CSV consolidator (multi-year, single folder)
   Reads raw season team-stat .rtf files from a SINGLE folder and merges
   each season into its own clean .csv. Read-only on the inputs.

   Input folder layout (flat — one folder, all years):
       RawCBBTeamData/
           1999-1.rtf
           1999-2.rtf
           2000-1.rtf
           ...
           2025-2.rtf

   Files are grouped by their leading "{YEAR}-" filename prefix. The year is
   the first year of the season (e.g. 2024 = the 2024-25 season).

   Output (one CSV per season, in the project root):
       1999_teams_consolidated.csv
       2000_teams_consolidated.csv
       ...
       2025_teams_consolidated.csv

   Idempotent — re-running rebuilds every season from source. Safe to drop
   new .rtf files into the folder and re-run.

   The team .rtf files have TWO header-like rows on top:
     row 1 — column-group labels (",,,,,,,,Team Totals,...,Team Shooting,...")
     row 2 — actual column names (Rk,Season,Team,W,G,W,L,W/L%,...)
   Both are preserved exactly in the output by carrying both rows over from
   the first file in a season and skipping them in the rest.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT      = Path(__file__).parent
INPUT_DIR = ROOT / "RawCBBTeamData"

# Filenames look like "{YEAR}-{N}.rtf" where YEAR is the 4-digit season start
# year and N is a sub-file number (Basketball Reference splits the team list
# across multiple pages). Group(1) captures the year, group(2) the sub-index.
FILENAME_PATTERN = re.compile(r"^(\d{4})-(\d+)\.rtf$")

# ----- RTF ESCAPE DECODING -----------------------------------------------

# Same character escapes as the player data — accents, em-dashes, etc.
# encoded as \'XX (CP1252 hex byte) or \uNNNN (Unicode codepoint). \ucN is a
# fallback-count control word we drop.
def decode_rtf_escapes(text):
    # Drop the \ucN control words.
    text = re.sub(r"\\uc\d+\s?", "", text)

    # \uNNNN → Unicode codepoint (RTF allows negative 16-bit signed form).
    def _u(m):
        n = int(m.group(1))
        if n < 0:
            n += 65536
        return chr(n)
    text = re.sub(r"\\u(-?\d+)\s?", _u, text)

    # \'XX → single CP1252 byte.
    def _hex(m):
        return bytes([int(m.group(1), 16)]).decode("cp1252", errors="replace")
    text = re.sub(r"\\'([0-9a-fA-F]{2})", _hex, text)

    # Strip any remaining RTF control words (e.g. \cb1, \pard, \f1, \cf0).
    # These are formatting directives, not data. Some source files embed
    # them mid-table (Jacksonville's eFG% in 2005-2.rtf ends with \cb1)
    # and they would otherwise leak into the output CSV. The trailing
    # paragraph-terminator `\` is handled separately per line, so it
    # doesn't match this pattern (no letters follow it).
    text = re.sub(r"\\[a-zA-Z]+\d*\s?", "", text)

    return text

# ----- RTF → CSV EXTRACTION ----------------------------------------------

# The CSV portion starts at the first column-group label row (which begins
# with ",,,,,,,,Team Totals") and runs to just before the closing "}". Each
# row ends with a "\" RTF paragraph terminator that we strip off.
def extract_csv_lines(rtf_path):
    with open(rtf_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    start_marker = ",Team Totals"
    idx = text.find(start_marker)
    if idx == -1:
        raise ValueError(f"No 'Team Totals' marker found in {rtf_path.name}")
    line_start = text.rfind("\n", 0, idx)
    if line_start == -1:
        line_start = 0
    # Back up to the leading comma run on the marker line.
    j = idx
    while j > line_start and text[j - 1] == ",":
        j -= 1
    body = text[j:]

    body = body.rstrip().rstrip("}").rstrip()
    body = decode_rtf_escapes(body)

    # A valid line is either the group-labels row (starts with a comma),
    # the column header (starts with "Rk,"), or a data row (starts with a
    # digit). Anything else — typically stray RTF control words like \pard
    # or \f1 that some source files embed mid-table — gets dropped.
    # decode_rtf_escapes only normalizes character escapes; it doesn't strip
    # formatting control words, which is why this filter is necessary.
    DATA_OR_HEADER = re.compile(r"^(,|Rk,|\d)")

    lines = []
    for raw in body.split("\n"):
        raw = raw.rstrip()
        if raw.endswith("\\"):
            raw = raw[:-1].rstrip()
        if not raw:
            continue
        if not DATA_OR_HEADER.match(raw):
            # Stray RTF formatting line — skip silently. The verifier's
            # artifact sweep will catch anything that slips through.
            continue
        lines.append(raw)
    return lines

# ----- PER-SEASON CONSOLIDATION -------------------------------------------

def consolidate_season(year, rtf_files, output_csv):
    """Merge sorted rtf_files (already filtered to this year) into output_csv.
    Returns dict with row count, column count, per-file counts, mismatches."""
    if not rtf_files:
        return None

    group_header = None
    col_header   = None
    expected_cols = None
    data_rows = []
    per_file_counts = []
    column_mismatches = []

    for rtf_path in rtf_files:
        lines = extract_csv_lines(rtf_path)
        if len(lines) < 2:
            print(f"  WARN: {rtf_path.name} extracted only {len(lines)} lines")
            continue

        file_group_header, file_col_header, *file_rows = lines

        # First file establishes the two header rows + expected column count.
        if group_header is None:
            group_header = file_group_header
            col_header = file_col_header
            expected_cols = col_header.count(",") + 1
        else:
            # Subsequent files in the SAME season must match — schema drift
            # within a season would silently corrupt merged data.
            if file_group_header != group_header:
                print(f"  WARN: column-group row in {rtf_path.name} differs from first file")
            if file_col_header != col_header:
                print(f"  WARN: column header in {rtf_path.name} differs from first file")

        for i, row in enumerate(file_rows):
            if row.count(",") + 1 != expected_cols:
                column_mismatches.append((rtf_path.name, i + 3, row.count(",") + 1))

        data_rows.extend(file_rows)
        per_file_counts.append((rtf_path.name, len(file_rows)))

    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        f.write(group_header + "\n")
        f.write(col_header + "\n")
        for row in data_rows:
            f.write(row + "\n")

    return {
        "data_row_count":    len(data_rows),
        "column_count":      expected_cols,
        "per_file_counts":   per_file_counts,
        "column_mismatches": column_mismatches,
    }

# ----- MAIN ---------------------------------------------------------------

def main():
    if not INPUT_DIR.is_dir():
        print(f"ERROR: input folder not found: {INPUT_DIR}", file=sys.stderr)
        sys.exit(1)

    # Group all .rtf files by year prefix from the filename. Anything that
    # doesn't match the {YEAR}-{N}.rtf pattern gets ignored with a notice
    # (so .DS_Store and similar junk files are skipped quietly, but oddly
    # named .rtf files surface).
    by_year = defaultdict(list)
    skipped = []
    for rtf in sorted(INPUT_DIR.iterdir()):
        if rtf.suffix.lower() != ".rtf":
            continue
        m = FILENAME_PATTERN.match(rtf.name)
        if not m:
            skipped.append(rtf.name)
            continue
        year = int(m.group(1))
        by_year[year].append((int(m.group(2)), rtf))

    if not by_year:
        print(f"ERROR: no files matching {{YEAR}}-{{N}}.rtf in {INPUT_DIR.name}/", file=sys.stderr)
        sys.exit(1)

    if skipped:
        print(f"NOTE: {len(skipped)} .rtf file(s) didn't match the {{YEAR}}-{{N}}.rtf pattern and were skipped:")
        for name in skipped:
            print(f"  {name}")
        print()

    years = sorted(by_year.keys())
    print(f"Found {sum(len(v) for v in by_year.values())} .rtf files across {len(years)} season(s): {years[0]}-{years[-1]}")
    print()

    grand_total = 0
    any_mismatches = 0
    for year in years:
        # Sort the season's files by sub-index so 10 comes after 9 (not after 1).
        rtf_files = [path for _, path in sorted(by_year[year], key=lambda x: x[0])]
        output_csv = ROOT / f"{year}_teams_consolidated.csv"
        result = consolidate_season(year, rtf_files, output_csv)
        if result is None:
            continue

        files_str = ", ".join(p.name for p in rtf_files)
        print(f"{year}-{(year+1)%100:02d}  →  {output_csv.name}  ({result['data_row_count']:>4d} rows, {result['column_count']} cols)  [{files_str}]")
        if result["column_mismatches"]:
            any_mismatches += len(result["column_mismatches"])
            print(f"  WARN: {len(result['column_mismatches'])} rows had mismatched column counts:")
            for name, line_no, cols in result["column_mismatches"][:3]:
                print(f"    {name} line {line_no}: {cols} cols (expected {result['column_count']})")
        grand_total += result["data_row_count"]

    print()
    print(f"Total team-season rows across all seasons: {grand_total}")
    if any_mismatches:
        print(f"WARN: {any_mismatches} total rows had column-count issues — re-check sources")

if __name__ == "__main__":
    main()
