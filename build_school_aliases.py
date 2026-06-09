"""
   One Shining Grid — build school_aliases.csv (multi-year)
   READ-ONLY on every consolidated CSV. Preserves user-confirmed aliases.

   Auto-discovers EVERY consolidated CSV across all years:
     - {YEAR}_teams_consolidated.csv   (any year present)
     - {YEAR}_players_consolidated.csv (any year present)

   Builds the union of team_file_name strings and player_file_name strings
   across all loaded seasons, then produces school_aliases.csv with three
   columns:
       canonical_name, team_file_name, player_file_name

   Behavior with respect to your existing alias work:
     - If school_aliases.csv exists, every row in it is treated as already
       confirmed. We never modify, re-order, or remove those rows.
     - We add new needs_review rows ONLY for file-name strings that don't
       appear anywhere in the existing alias.
     - We do not "merge" or "guess" name-change cases. If 2024 has
       "Texas A&M–Commerce" and 2025 has "East Texas A&M", they come in as
       two separate needs_review rows. You confirm them both, optionally
       sharing the same canonical_name so the game treats them as one school.

   Schema rules (enforced by the verifier):
     - team_file_name unique across rows (when populated)
     - player_file_name unique across rows (when populated)
     - canonical_name MAY repeat — two rows with the same canonical means
       "these two source strings refer to the same physical school"
       (the name-change case).
"""

import csv
import re
import sys
import unicodedata
from pathlib import Path

ROOT       = Path(__file__).parent
OUTPUT_CSV = ROOT / "school_aliases.csv"

TEAM_CSV_PATTERN   = re.compile(r"^(\d{4})_teams_consolidated\.csv$")
PLAYER_CSV_PATTERN = re.compile(r"^(\d{4})_players_consolidated\.csv$")

# Combined all-seasons player file (one row per player-season, single header,
# has Season + Team columns). Read in addition to any per-year player CSVs.
# Same player-side naming convention as the per-year player files.
MASTER_PLAYER_CSV  = "cbb_player_seasons_master.csv"

# ----- LOAD DISTINCT TEAM NAMES ------------------------------------------

def load_team_names_from_team_csv(csv_path):
    """Team CSVs have a group-labels row above the column header — skip it."""
    with open(csv_path, encoding="utf-8") as f:
        f.readline()
        return {row["Team"] for row in csv.DictReader(f) if row.get("Team")}

def load_team_names_from_player_csv(csv_path):
    """Player CSVs have a single header row."""
    with open(csv_path, encoding="utf-8") as f:
        return {row["Team"] for row in csv.DictReader(f) if row.get("Team")}

def load_team_year_pairs_from_master(csv_path):
    """Master player file: one row per player-season with Season + Team columns.
    Yields (team_file_name, year) with year parsed from Season ('1999-00' -> 1999)."""
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row.get("Team")
            if not t:
                continue
            m = re.match(r"(\d{4})", row.get("Season") or "")
            yield t, (int(m.group(1)) if m else 0)

# ----- NORMALIZATION (for auto-matching new strings only) ----------------

# Same deterministic rules as before. Used only to auto-pair NEW strings
# against each other when their normalized form coincides. Existing
# confirmed aliases are never re-evaluated.
NORMALIZE_RULES = [
    (re.compile(r"\bSt\.?\b"),    "State"),
    (re.compile(r"\bU\.?\b"),     "University"),
    (re.compile(r"\bAla\.?\b"),   "Alabama"),
    (re.compile(r"\bAriz\.?\b"),  "Arizona"),
    (re.compile(r"\bArk\.?\b"),   "Arkansas"),
    (re.compile(r"\bCaro\.?\b"),  "Carolina"),
    (re.compile(r"\bColo\.?\b"),  "Colorado"),
    (re.compile(r"\bConn\.?\b"),  "Connecticut"),
    (re.compile(r"\bFla\.?\b"),   "Florida"),
    (re.compile(r"\bGa\.?\b"),    "Georgia"),
    (re.compile(r"\bIll\.?\b"),   "Illinois"),
    (re.compile(r"\bInd\.?\b"),   "Indiana"),
    (re.compile(r"\bKy\.?\b"),    "Kentucky"),
    (re.compile(r"\bLa\.?\b"),    "Louisiana"),
    (re.compile(r"\bMd\.?\b"),    "Maryland"),
    (re.compile(r"\bMass\.?\b"),  "Massachusetts"),
    (re.compile(r"\bMich\.?\b"),  "Michigan"),
    (re.compile(r"\bMiss\.?\b"),  "Mississippi"),
    (re.compile(r"\bMt\.?\b"),    "Mount"),
    (re.compile(r"\bTenn\.?\b"),  "Tennessee"),
    (re.compile(r"\bWash\.?\b"),  "Washington"),
    (re.compile(r"\bEast\.\b"),   "Eastern"),
]

DASH_CHARS = "‐‑‒–—―"

def normalize(name):
    s = name
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for d in DASH_CHARS:
        s = s.replace(d, "-")
    for pat, repl in NORMALIZE_RULES:
        s = pat.sub(repl, s)
    s = s.lower()
    s = re.sub(r"[.,'\"()&]", "", s)
    s = s.replace("&", "and")
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ----- LOAD EXISTING ALIAS FILE ------------------------------------------

def load_existing_aliases():
    """Return list of dict rows. Empty list if file doesn't exist yet."""
    if not OUTPUT_CSV.exists():
        return []
    with open(OUTPUT_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ----- MAIN --------------------------------------------------------------

def main():
    # Discover every consolidated CSV, split by side.
    team_csvs   = sorted([p for p in ROOT.iterdir() if TEAM_CSV_PATTERN.match(p.name)],
                         key=lambda p: p.name)
    player_csvs = sorted([p for p in ROOT.iterdir() if PLAYER_CSV_PATTERN.match(p.name)],
                         key=lambda p: p.name)
    master_path = ROOT / MASTER_PLAYER_CSV

    if not team_csvs and not player_csvs and not master_path.exists():
        print("ERROR: no consolidated CSVs found in project root", file=sys.stderr)
        sys.exit(1)

    print(f"Team CSVs:   {[p.name for p in team_csvs]}")
    print(f"Player CSVs: {[p.name for p in player_csvs]}")
    print(f"Master file: {MASTER_PLAYER_CSV if master_path.exists() else '(none)'}")
    print()

    # Collect the UNION of team-file and player-file team-name strings.
    # Track which years each string appears in (informational only).
    team_name_years   = {}   # team_file_name → set of years
    player_name_years = {}   # player_file_name → set of years

    for csv_path in team_csvs:
        year = int(TEAM_CSV_PATTERN.match(csv_path.name).group(1))
        for name in load_team_names_from_team_csv(csv_path):
            team_name_years.setdefault(name, set()).add(year)

    for csv_path in player_csvs:
        year = int(PLAYER_CSV_PATTERN.match(csv_path.name).group(1))
        for name in load_team_names_from_player_csv(csv_path):
            player_name_years.setdefault(name, set()).add(year)

    # Also fold in the combined master player file, if present. Each row carries
    # its own Season, so the year is derived per row.
    if master_path.exists():
        for name, year in load_team_year_pairs_from_master(master_path):
            player_name_years.setdefault(name, set()).add(year)

    print(f"Distinct team_file_name strings (union across all years):   {len(team_name_years)}")
    print(f"Distinct player_file_name strings (union across all years): {len(player_name_years)}")
    print()

    # Load existing aliases — these are CONFIRMED and untouched.
    existing = load_existing_aliases()
    existing_team_strings   = {r["team_file_name"]   for r in existing if r.get("team_file_name")}
    existing_player_strings = {r["player_file_name"] for r in existing if r.get("player_file_name")}
    print(f"Existing alias rows (preserved as-is):     {len(existing)}")
    print(f"  team_file_name strings already covered:  {len(existing_team_strings)}")
    print(f"  player_file_name strings already covered:{len(existing_player_strings)}")
    print()

    # What's NEW in the loaded data that the alias doesn't cover yet?
    new_team_strings   = sorted(set(team_name_years.keys())   - existing_team_strings)
    new_player_strings = sorted(set(player_name_years.keys()) - existing_player_strings)

    # Auto-pair logic for NEW strings:
    # If a new team_file_name normalizes to the SAME form as a new player_file_name
    # AND that form is unique on both sides, pair them as "normalized" — no
    # judgment involved. Anything else gets emitted as needs_review.
    new_rows = []

    # Identity matches among new strings (same exact string on both sides).
    new_team_set   = set(new_team_strings)
    new_player_set = set(new_player_strings)
    identical = new_team_set & new_player_set
    for name in sorted(identical):
        new_rows.append({
            "canonical_name":   name,
            "team_file_name":   name,
            "player_file_name": name,
            "match_method":     "identical",
        })

    # Normalized matches among NEW strings on each side, excluding the identical set.
    new_team_remaining   = sorted(new_team_set   - identical)
    new_player_remaining = sorted(new_player_set - identical)
    norm_to_player = {}
    player_collisions = set()
    for p in new_player_remaining:
        np = normalize(p)
        if np in norm_to_player:
            player_collisions.add(np)
        else:
            norm_to_player[np] = p

    norm_to_team = {}
    for t in new_team_remaining:
        nt = normalize(t)
        norm_to_team.setdefault(nt, []).append(t)

    paired_team   = set()
    paired_player = set()
    for nt, ts in norm_to_team.items():
        if len(ts) != 1: continue
        if nt in player_collisions: continue
        if nt not in norm_to_player: continue
        t = ts[0]
        p = norm_to_player[nt]
        new_rows.append({
            "canonical_name":   p,
            "team_file_name":   t,
            "player_file_name": p,
            "match_method":     "normalized",
        })
        paired_team.add(t)
        paired_player.add(p)

    # Everything still unpaired on each side gets a needs_review row.
    unresolved_team   = [t for t in new_team_remaining   if t not in paired_team]
    unresolved_player = [p for p in new_player_remaining if p not in paired_player]
    for t in unresolved_team:
        new_rows.append({
            "canonical_name":   "",
            "team_file_name":   t,
            "player_file_name": "",
            "match_method":     "needs_review",
        })
    for p in unresolved_player:
        new_rows.append({
            "canonical_name":   "",
            "team_file_name":   "",
            "player_file_name": p,
            "match_method":     "needs_review",
        })

    # ----- WRITE OUTPUT -------------------------------------------------
    # Existing rows preserved verbatim. New rows appended after.
    # Use the columns from the existing file if it had them; otherwise the
    # standard 3 columns.
    existing_cols = list(existing[0].keys()) if existing else ["canonical_name", "team_file_name", "player_file_name"]
    # Ensure required columns are present.
    for col in ("canonical_name", "team_file_name", "player_file_name"):
        if col not in existing_cols:
            existing_cols.append(col)
    # New rows include match_method only if it's already a column or we're
    # adding new ones — match_method makes the needs_review state visible.
    add_match_method_col = bool(new_rows) and "match_method" not in existing_cols
    output_cols = existing_cols + (["match_method"] if add_match_method_col else [])

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_cols)
        writer.writeheader()
        # Preserve existing rows exactly. Backfill any missing columns blank.
        for r in existing:
            writer.writerow({c: r.get(c, "") for c in output_cols})
        for r in new_rows:
            writer.writerow({c: r.get(c, "") for c in output_cols})

    # ----- SUMMARY ------------------------------------------------------
    by_method = {}
    for r in new_rows:
        by_method[r["match_method"]] = by_method.get(r["match_method"], 0) + 1

    print(f"Wrote {OUTPUT_CSV.name} — {len(existing) + len(new_rows)} total rows")
    print(f"  preserved:    {len(existing)}")
    print(f"  newly added:  {len(new_rows)}")
    if new_rows:
        for m in ("identical", "normalized", "needs_review"):
            if m in by_method:
                print(f"    {m:14s} {by_method[m]:>4d}")
    print()

    nr_rows = [r for r in new_rows if r["match_method"] == "needs_review"]
    if nr_rows:
        nr_team   = [r for r in nr_rows if r["team_file_name"]]
        nr_player = [r for r in nr_rows if not r["team_file_name"]]
        print(f"=== {len(nr_team)} NEW unpaired TEAM-file strings ===")
        for r in nr_team:
            years = sorted(team_name_years.get(r["team_file_name"], set()))
            print(f"  {r['team_file_name']:30s}  appears in: {years}")
        print()
        print(f"=== {len(nr_player)} NEW unpaired PLAYER-file strings ===")
        for r in nr_player:
            years = sorted(player_name_years.get(r["player_file_name"], set()))
            print(f"  {r['player_file_name']:30s}  appears in: {years}")
        print()
        print("To resolve a pair (workflow unchanged from single-year):")
        print("  1. Find the team-side row, fill in player_file_name + canonical_name,")
        print("     change match_method to 'confirmed'.")
        print("  2. Delete the matching player-side row.")
        print("  3. For name changes (e.g. East Texas A&M ↔ Texas A&M-Commerce),")
        print("     use the SAME canonical_name on both rows. The verifier allows")
        print("     canonical_name to repeat and will list these as info.")
        print("  4. Re-run verify_school_aliases.py.")
    else:
        print("No new strings to review — all team names already covered.")

if __name__ == "__main__":
    main()
