"""
   One Shining Grid — player CSV consolidator
   Reads the raw season-stat .rtf files (RTF-wrapped CSV, one folder per season)
   and merges them into a single clean .csv. Read-only on the inputs.
"""

import os
import re
import sys
from pathlib import Path

# ----- CONFIG -------------------------------------------------------------

# Folder of raw .rtf files for one season. Point this at a different folder
# (e.g. 2025RawCBBPlayerData) when consolidating another season.
INPUT_DIR  = Path(__file__).parent / "2024RawCBBPlayerData"

# Where the consolidated CSV gets written. Brand new file — never overwrites
# a source CSV, never touches a .rtf.
OUTPUT_CSV = Path(__file__).parent / "2024_players_consolidated.csv"

# ----- RTF ESCAPE DECODING -----------------------------------------------

# The RTF files encode non-ASCII characters as escape sequences instead of
# raw bytes — accented letters, em-dashes in team names, etc. We have to
# decode these before treating the body as CSV, or names like "Josué" and
# team names like "Texas—Rio Grande Valley" come through as gibberish.
#
# The two relevant escape forms in these files:
#   \'XX      — single byte in the document's codepage (CP1252 here),
#               e.g. \'96 → em-dash, \'e9 → é
#   \uNNNN    — Unicode codepoint (decimal), e.g. \u263 → ć. RTF also emits
#               a \ucN control beforehand declaring how many ANSI fallback
#               chars follow each \u — we just drop the \ucN word.
def decode_rtf_escapes(text):
    # Drop the \ucN control words — they describe fallback behavior we don't need.
    text = re.sub(r"\\uc\d+\s?", "", text)

    # \uNNNN → Unicode codepoint. RTF allows negative numbers (16-bit signed);
    # convert negatives back into the positive codepoint they represent.
    def _u(m):
        n = int(m.group(1))
        if n < 0:
            n += 65536
        return chr(n)
    text = re.sub(r"\\u(-?\d+)\s?", _u, text)

    # \'XX → single CP1252 byte. Decode the byte through CP1252 to get the
    # right character (e.g. 0x96 → em-dash, 0xe9 → é).
    def _hex(m):
        return bytes([int(m.group(1), 16)]).decode("cp1252", errors="replace")
    text = re.sub(r"\\'([0-9a-fA-F]{2})", _hex, text)

    return text

# ----- RTF → CSV EXTRACTION ----------------------------------------------

# The .rtf files are CSV data wrapped in a thin RTF envelope. The CSV portion
# always starts at the header row "Rk,Player,..." and ends just before the
# closing "}". Each data row inside the RTF ends with a "\" (RTF paragraph
# terminator) that we strip back off.
def extract_csv_lines(rtf_path):
    with open(rtf_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    # Locate the CSV header — everything before it is RTF preamble we don't want.
    start = text.find("Rk,Player")
    if start == -1:
        raise ValueError(f"No CSV header found in {rtf_path.name}")
    body = text[start:]

    # Trim the trailing "}" that closes the RTF document.
    body = body.rstrip().rstrip("}").rstrip()

    # Decode RTF character escapes (accents, em-dashes, etc.) into real chars.
    body = decode_rtf_escapes(body)

    # Walk line by line, stripping the trailing "\" off each row.
    lines = []
    for raw in body.split("\n"):
        raw = raw.rstrip()
        if raw.endswith("\\"):
            raw = raw[:-1].rstrip()
        if raw:
            lines.append(raw)
    return lines

# ----- FILE ORDERING ------------------------------------------------------

# Files are named like "2024-1.rtf", "2024-2.rtf", ... "2024-26.rtf".
# Default alphabetical sort puts "2024-10" before "2024-2", which we don't
# want — pull out the trailing number and sort numerically so rows stay in
# the original Rk order (purely cosmetic, but easier to debug).
def numeric_key(path):
    m = re.search(r"-(\d+)\.rtf$", path.name)
    return int(m.group(1)) if m else 10**9

# ----- MAIN ---------------------------------------------------------------

def main():
    if not INPUT_DIR.is_dir():
        print(f"ERROR: input folder not found: {INPUT_DIR}", file=sys.stderr)
        sys.exit(1)

    rtf_files = sorted(INPUT_DIR.glob("*.rtf"), key=numeric_key)
    if not rtf_files:
        print(f"ERROR: no .rtf files in {INPUT_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(rtf_files)} .rtf files in {INPUT_DIR.name}/")

    header = None              # The CSV header line — kept from the first file
    expected_cols = None       # Column count, used to validate every row
    data_rows = []             # All non-header rows, accumulated in file order
    per_file_counts = []       # For the summary at the end
    column_mismatches = []     # (filename, row_index, actual_cols) tuples

    for rtf_path in rtf_files:
        lines = extract_csv_lines(rtf_path)
        if not lines:
            print(f"  WARN: {rtf_path.name} extracted 0 lines")
            continue

        file_header, *file_rows = lines

        # First file establishes the header + expected column count.
        if header is None:
            header = file_header
            expected_cols = header.count(",") + 1
        else:
            # Every subsequent file MUST have the same header — otherwise the
            # schema drifted and we'd be silently merging incompatible data.
            if file_header != header:
                print(f"  WARN: header in {rtf_path.name} differs from {rtf_files[0].name}")

        # Validate column counts — flag rows that don't match the header.
        for i, row in enumerate(file_rows):
            if row.count(",") + 1 != expected_cols:
                column_mismatches.append((rtf_path.name, i + 2, row.count(",") + 1))

        data_rows.extend(file_rows)
        per_file_counts.append((rtf_path.name, len(file_rows)))

    # ----- WRITE OUTPUT ---------------------------------------------------

    # Write to a NEW file. Inputs are never touched.
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        f.write(header + "\n")
        for row in data_rows:
            f.write(row + "\n")

    # ----- SUMMARY --------------------------------------------------------

    print()
    print(f"Wrote {OUTPUT_CSV.name} — {len(data_rows)} player-season rows")
    print(f"Header: {expected_cols} columns")
    print()
    print("Per-file row counts:")
    for name, n in per_file_counts:
        print(f"  {name:18s} {n:>5d} rows")

    if column_mismatches:
        print()
        print(f"WARN: {len(column_mismatches)} rows had mismatched column counts:")
        for name, line_no, cols in column_mismatches[:10]:
            print(f"  {name} line {line_no}: {cols} cols (expected {expected_cols})")
        if len(column_mismatches) > 10:
            print(f"  ... and {len(column_mismatches) - 10} more")
    else:
        print()
        print("All rows match expected column count.")

if __name__ == "__main__":
    main()
