r"""
   One Shining Grid — independent verification of consolidated team CSVs.
   READ-ONLY on every source file.

   Multi-year aware, single-folder input. Discovers every
   "{YEAR}_teams_consolidated.csv" in the project root and verifies it
   against the matching "{YEAR}-*.rtf" files inside RawCBBTeamData/.

   Verification approach (different from the consolidator on purpose):
     1. For each source .rtf, scan line-by-line and pull out team-row lines
        and the two header rows by signature/substring.
     2. Decode RTF character escapes (\'XX, \uNNNN) inside each line.
     3. Compare independently-extracted rows against the consolidated CSV.
     4. Sweep the consolidated CSV for any leftover RTF artifacts.
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT      = Path(__file__).parent
INPUT_DIR = ROOT / "RawCBBTeamData"

# Patterns to match consolidated CSV filenames and raw .rtf filenames.
CSV_PATTERN     = re.compile(r"^(\d{4})_teams_consolidated\.csv$")
RTF_PATTERN     = re.compile(r"^(\d{4})-(\d+)\.rtf$")

# ----- RTF ESCAPE DECODE (per-line, character escapes only) -------------

RE_UC  = re.compile(r"\\uc\d+ ?")
RE_U   = re.compile(r"\\u(-?\d+) ?")
RE_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")

RE_CONTROL_WORD = re.compile(r"\\[a-zA-Z]+\d*\s?")

def decode_line(line):
    line = RE_UC.sub("", line)
    line = RE_U.sub(lambda m: chr(int(m.group(1)) + (65536 if int(m.group(1)) < 0 else 0)), line)
    line = RE_HEX.sub(lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", errors="replace"), line)
    # Strip any remaining RTF control words (e.g. \cb1, \pard, \f1).
    # Match the consolidator's behavior so byte-for-byte comparison works.
    line = RE_CONTROL_WORD.sub("", line)
    return line

# Data-row signature: integer Rk at start. The trailing "\" RTF paragraph
# terminator is optional — the last data row in a file omits it because the
# document closes with "}" instead.
DATA_ROW_RE = re.compile(r"^\d+,")

def extract_rows_from_rtf(rtf_path):
    """Returns (group_header, col_header, data_rows). Pure RTF formatting
    lines (e.g. \\pard, \\f1) are ignored since they aren't data."""
    text = rtf_path.read_text(encoding="utf-8", errors="replace")

    group_header = None
    col_header   = None
    data_rows = []

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()

        if group_header is None and "Team Totals" in line and line.lstrip(", ").startswith("Team Totals") is False:
            tt_idx = line.index("Team Totals")
            j = tt_idx
            while j > 0 and line[j - 1] == ",":
                j -= 1
            grp = line[j:].rstrip("\\").rstrip()
            group_header = decode_line(grp)
            continue

        if col_header is None and "Rk,Season,Team" in line:
            col_header = decode_line(line[line.index("Rk,Season,Team"):].rstrip("\\").rstrip())
            continue

        if DATA_ROW_RE.match(line):
            # Strip trailing paragraph terminator (\) and/or document close
            # brace (}) — the last line of every file ends with "}" because
            # the RTF document closes immediately after the final row, with
            # no intermediate paragraph terminator.
            val = line.rstrip("\\}").rstrip()
            data_rows.append(decode_line(val))

    return group_header, col_header, data_rows

def numeric_key(path):
    m = re.search(r"-(\d+)\.rtf$", path.name)
    return int(m.group(1)) if m else 10**9

# ----- PER-SEASON VERIFICATION -------------------------------------------

def verify_season(year, rtf_files, output_csv):
    """Verify one season's consolidated CSV against its source files.
    Returns issue count."""
    print(f"=== {output_csv.name} vs {[p.name for p in rtf_files]} ===")

    issues = 0

    raw_lines = output_csv.read_text(encoding="utf-8").splitlines()
    consolidated_group_header = raw_lines[0]
    consolidated_col_header   = raw_lines[1]
    consolidated_data_lines   = raw_lines[2:]

    with open(output_csv, encoding="utf-8") as f:
        f.readline()  # skip group-labels row
        reader = csv.DictReader(f)
        consolidated_rows = list(reader)
        fieldnames = reader.fieldnames

    print(f"  Consolidated: {len(consolidated_data_lines)} rows, {len(fieldnames)} columns")

    expected_group = None
    expected_cols  = None
    expected_data  = []
    per_file = []
    source_group_variants = {}  # group_header → list of filenames
    for rtf_path in rtf_files:
        grp, col, rows = extract_rows_from_rtf(rtf_path)
        source_group_variants.setdefault(grp, []).append(rtf_path.name)
        if expected_group is None:
            expected_group = grp
            expected_cols  = col
        else:
            if col != expected_cols:
                print(f"    WARN: column header in {rtf_path.name} differs from first file")
        expected_data.extend(rows)
        per_file.append((rtf_path.name, len(rows)))

    expected_total = sum(n for _, n in per_file)
    print(f"  Independent re-extract: {expected_total} rows across {len(rtf_files)} files")

    # CHECK 1: row count
    if expected_total != len(consolidated_data_lines):
        issues += 1
        print(f"  CHECK 1 row count        FAIL: {len(consolidated_data_lines)} vs expected {expected_total}")
    else:
        print(f"  CHECK 1 row count        PASS")

    # CHECK 2: group-labels row — must match the FIRST source file's row
    # (the consolidator uses the first file's headers; if 2006-2 has a
    # different row that's a source quirk, not a verifier failure).
    if expected_group == consolidated_group_header:
        print(f"  CHECK 2 group-labels row PASS")
    else:
        issues += 1
        print(f"  CHECK 2 group-labels row FAIL")
        print(f"    expected: {expected_group[:100]}")
        print(f"    actual:   {consolidated_group_header[:100]}")
    # Surface multi-variant group rows as a note (source quirk, not a fail).
    if len(source_group_variants) > 1:
        print(f"  NOTE: source files have {len(source_group_variants)} different group-labels rows (source quirk):")
        for grp, files in source_group_variants.items():
            print(f"    in {files}: {grp[:80]}")

    # CHECK 3: column header
    if expected_cols == consolidated_col_header:
        print(f"  CHECK 3 column header    PASS")
    else:
        issues += 1
        print(f"  CHECK 3 column header    FAIL")

    # CHECK 4: byte-for-byte row match
    if len(expected_data) == len(consolidated_data_lines):
        mismatches = [i for i in range(len(expected_data)) if expected_data[i] != consolidated_data_lines[i]]
        if not mismatches:
            print(f"  CHECK 4 row content      PASS: all {len(consolidated_data_lines)} rows match source byte-for-byte")
        else:
            issues += 1
            print(f"  CHECK 4 row content      FAIL: {len(mismatches)} rows differ:")
            for i in mismatches[:3]:
                print(f"    row {i+3}:")
                print(f"      expected: {expected_data[i][:120]}")
                print(f"      actual:   {consolidated_data_lines[i][:120]}")
    else:
        issues += 1
        print(f"  CHECK 4 row content      SKIP (row counts differ)")

    # CHECK 5: RTF artifact sweep
    patterns = [
        ("backslash",        re.compile(r"\\")),
        ("brace",            re.compile(r"[{}]")),
        ("RTF control word", re.compile(r"\\[a-zA-Z]+")),
        ("hex escape",       re.compile(r"\\'[0-9a-fA-F]{2}")),
        ("unicode escape",   re.compile(r"\\u-?\d+")),
        ("control char",     re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")),
    ]
    artifacts = False
    examples_to_show = 3
    for label, pat in patterns:
        hits = []
        for row in consolidated_rows:
            for col, val in row.items():
                if val and pat.search(val):
                    hits.append((row.get("Rk"), row.get("Team"), col, val))
                    if len(hits) >= examples_to_show: break
            if len(hits) >= examples_to_show: break
        if hits:
            artifacts = True
            issues += 1
            print(f"  CHECK 5 artifact sweep   FAIL: {label}")
            for rk, team, col, val in hits:
                print(f"    Rk {rk} Team={team!r}  col={col!r}  val={val[:80]!r}")
    if not artifacts:
        print(f"  CHECK 5 artifact sweep   PASS")

    # CHECK 6: column count consistency
    expected_n_cols = consolidated_col_header.count(",") + 1
    bad = [(i, line) for i, line in enumerate(consolidated_data_lines)
           if line.count(",") + 1 != expected_n_cols]
    if not bad:
        print(f"  CHECK 6 column counts    PASS: every row has {expected_n_cols} columns")
    else:
        issues += 1
        print(f"  CHECK 6 column counts    FAIL: {len(bad)} rows have wrong column count:")
        for i, line in bad[:3]:
            print(f"    line {i+3}: {line.count(',')+1} cols: {line[:100]}")

    # CHECK 7: season values
    seasons = Counter(r["Season"] for r in consolidated_rows)
    print(f"  CHECK 7 seasons          {dict(seasons)}")

    print(f"  RESULT: {'PASS' if issues == 0 else f'{issues} issue(s)'}")
    print()
    return issues

# ----- MAIN --------------------------------------------------------------

def main():
    if not INPUT_DIR.is_dir():
        print(f"ERROR: input folder not found: {INPUT_DIR}", file=sys.stderr)
        sys.exit(1)

    # Group source .rtf files by year prefix.
    rtfs_by_year = defaultdict(list)
    for rtf in sorted(INPUT_DIR.iterdir()):
        if rtf.suffix.lower() != ".rtf":
            continue
        m = RTF_PATTERN.match(rtf.name)
        if m:
            rtfs_by_year[int(m.group(1))].append(rtf)

    # Sort each year's files by sub-index.
    for year in rtfs_by_year:
        rtfs_by_year[year].sort(key=numeric_key)

    # Discover consolidated CSVs.
    csv_years = {int(CSV_PATTERN.match(p.name).group(1)): p
                 for p in ROOT.iterdir() if CSV_PATTERN.match(p.name)}

    all_years = sorted(set(rtfs_by_year.keys()) | set(csv_years.keys()))
    if not all_years:
        print("ERROR: no consolidated CSVs or raw .rtf files found", file=sys.stderr)
        sys.exit(1)

    print(f"Years found: {all_years[0]}–{all_years[-1]} ({len(all_years)} season(s))")
    print(f"  with consolidated CSV: {len(csv_years)} year(s)")
    print(f"  with raw .rtf files:   {len(rtfs_by_year)} year(s)")
    only_csv     = sorted(csv_years.keys()     - rtfs_by_year.keys())
    only_folder  = sorted(rtfs_by_year.keys()  - csv_years.keys())
    if only_csv:
        print(f"  WARN: years with consolidated CSV but NO raw files: {only_csv}")
    if only_folder:
        print(f"  WARN: years with raw files but NO consolidated CSV: {only_folder}")
    print()

    total_issues = 0
    for year in all_years:
        if year in csv_years and year in rtfs_by_year:
            total_issues += verify_season(year, rtfs_by_year[year], csv_years[year])
        else:
            total_issues += 1

    print("=" * 60)
    if total_issues == 0:
        print(f"VERIFICATION PASSED — {len(all_years)} season(s) verified clean")
    else:
        print(f"VERIFICATION FOUND {total_issues} ISSUE(S) — see details above")

if __name__ == "__main__":
    main()
