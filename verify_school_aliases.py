r"""
   One Shining Grid — verify school_aliases.csv (multi-year)
   READ-ONLY on every input file.

   Auto-discovers all consolidated CSVs across all years and checks that
   school_aliases.csv covers every team-file string and every player-file
   string from every loaded season.

   Schema rules:
     - canonical_name populated on every row (REQUIRED)
     - team_file_name unique across rows where populated  (bijection)
     - player_file_name unique across rows where populated (bijection)
     - canonical_name MAY repeat — these are name-change cases where two
       source strings refer to the same physical school. Verifier lists
       them as information, not failures.
     - rows with match_method=needs_review are flagged as incomplete
     - rows with one side blank are flagged as incomplete UNLESS the year
       data legitimately only has that side (e.g. a school only ever
       appeared in team data, never in player data — possible if we have
       a year's team CSV but not its player CSV yet)
"""

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT      = Path(__file__).parent
ALIAS_CSV = ROOT / "school_aliases.csv"

TEAM_CSV_PATTERN   = re.compile(r"^(\d{4})_teams_consolidated\.csv$")
PLAYER_CSV_PATTERN = re.compile(r"^(\d{4})_players_consolidated\.csv$")
MASTER_PLAYER_CSV  = "cbb_player_seasons_master.csv"

REQUIRED_COLS = {"canonical_name", "team_file_name", "player_file_name"}

# ----- LOAD HELPERS ------------------------------------------------------

def load_team_names_from_team_csv(csv_path):
    with open(csv_path, encoding="utf-8") as f:
        f.readline()  # group-labels row
        return {row["Team"] for row in csv.DictReader(f) if row.get("Team")}

def load_team_names_from_player_csv(csv_path):
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

# ----- CHECKS ------------------------------------------------------------

def main():
    if not ALIAS_CSV.exists():
        print(f"ERROR: {ALIAS_CSV.name} not found"); sys.exit(1)

    team_csvs   = sorted([p for p in ROOT.iterdir() if TEAM_CSV_PATTERN.match(p.name)],
                         key=lambda p: p.name)
    player_csvs = sorted([p for p in ROOT.iterdir() if PLAYER_CSV_PATTERN.match(p.name)],
                         key=lambda p: p.name)
    master_path = ROOT / MASTER_PLAYER_CSV
    if not team_csvs and not player_csvs and not master_path.exists():
        print("ERROR: no consolidated CSVs found"); sys.exit(1)

    # Union of strings across all loaded years, plus per-year breakdown for diagnostics.
    team_strings_by_year   = {}
    player_strings_by_year = {}
    all_team_strings   = set()
    all_player_strings = set()
    for p in team_csvs:
        year = int(TEAM_CSV_PATTERN.match(p.name).group(1))
        s = load_team_names_from_team_csv(p)
        team_strings_by_year[year] = s
        all_team_strings |= s
    for p in player_csvs:
        year = int(PLAYER_CSV_PATTERN.match(p.name).group(1))
        s = load_team_names_from_player_csv(p)
        player_strings_by_year[year] = s
        all_player_strings |= s
    if master_path.exists():
        for name, year in load_team_year_pairs_from_master(master_path):
            player_strings_by_year.setdefault(year, set()).add(name)
            all_player_strings.add(name)

    with open(ALIAS_CSV, encoding="utf-8") as f:
        aliases = list(csv.DictReader(f))

    print(f"Team CSVs:   {[p.name for p in team_csvs]}")
    print(f"Player CSVs: {[p.name for p in player_csvs]}")
    print(f"Master file: {MASTER_PLAYER_CSV if master_path.exists() else '(none)'}")
    print(f"Union of team_file_name strings:   {len(all_team_strings)}")
    print(f"Union of player_file_name strings: {len(all_player_strings)}")
    print(f"Alias file:  {len(aliases)} rows")
    print()

    issues = 0
    notes  = 0

    # ----- CHECK 1: schema -------------------------------------------------
    print("CHECK 1 — Alias file has required columns")
    actual_cols = set(aliases[0].keys()) if aliases else set()
    missing = REQUIRED_COLS - actual_cols
    if missing:
        issues += 1
        print(f"  FAIL: missing column(s): {missing}")
    else:
        print(f"  PASS: required columns present")
    print()

    # ----- CHECK 2: canonical_name populated everywhere -------------------
    print("CHECK 2 — canonical_name populated on every row")
    missing_canon = [(i, r) for i, r in enumerate(aliases) if not r.get("canonical_name")]
    if not missing_canon:
        print(f"  PASS: all {len(aliases)} rows have canonical_name")
    else:
        issues += 1
        print(f"  FAIL: {len(missing_canon)} rows have blank canonical_name:")
        for i, r in missing_canon[:10]:
            print(f"    line {i+2}: team={r.get('team_file_name')!r}  player={r.get('player_file_name')!r}")
    print()

    # ----- CHECK 3: zero needs_review rows (if match_method column exists) -
    print("CHECK 3 — Zero needs_review rows")
    if aliases and "match_method" in aliases[0]:
        nr = [r for r in aliases if r.get("match_method") == "needs_review"]
        if not nr:
            print(f"  PASS: no rows still flagged needs_review")
        else:
            issues += 1
            print(f"  FAIL: {len(nr)} rows still need user review:")
            for r in nr[:10]:
                side = r["team_file_name"] or "(player-only)"
                print(f"    {side}  player={r['player_file_name']!r}")
    else:
        print(f"  SKIP: alias file has no match_method column (fully confirmed)")
    print()

    # ----- CHECK 4: bijection on team_file_name (where populated) ---------
    print("CHECK 4 — Each team_file_name appears at most once")
    t_counts = Counter(r["team_file_name"] for r in aliases if r.get("team_file_name"))
    t_dupes = [(n, c) for n, c in t_counts.items() if c > 1]
    if not t_dupes:
        print(f"  PASS: {len(t_counts)} distinct team_file_name values, no duplicates")
    else:
        issues += 1
        print(f"  FAIL: {len(t_dupes)} team_file_name strings appear more than once:")
        for n, c in t_dupes[:10]:
            paired = [r["player_file_name"] for r in aliases if r["team_file_name"] == n]
            print(f"    {n!r} x{c}  → paired with {paired}")
    print()

    # ----- CHECK 5: bijection on player_file_name (where populated) -------
    print("CHECK 5 — Each player_file_name appears at most once")
    p_counts = Counter(r["player_file_name"] for r in aliases if r.get("player_file_name"))
    p_dupes = [(n, c) for n, c in p_counts.items() if c > 1]
    if not p_dupes:
        print(f"  PASS: {len(p_counts)} distinct player_file_name values, no duplicates")
    else:
        issues += 1
        print(f"  FAIL: {len(p_dupes)} player_file_name strings appear more than once:")
        for n, c in p_dupes[:10]:
            paired = [r["team_file_name"] for r in aliases if r["player_file_name"] == n]
            print(f"    {n!r} x{c}  → paired with {paired}")
    print()

    # ----- CHECK 6: coverage on team-file side ---------------------------
    print("CHECK 6 — Every team-file string from every year is in the alias")
    alias_team = {r["team_file_name"] for r in aliases if r.get("team_file_name")}
    missing_t = sorted(all_team_strings - alias_team)
    extra_t   = sorted(alias_team - all_team_strings)
    if not missing_t and not extra_t:
        print(f"  PASS: all {len(all_team_strings)} team-file strings represented")
    else:
        if missing_t:
            issues += 1
            print(f"  FAIL: {len(missing_t)} team-file strings NOT in alias:")
            for t in missing_t[:10]:
                years_in = sorted(y for y, s in team_strings_by_year.items() if t in s)
                print(f"    {t!r}  (years: {years_in})")
        if extra_t:
            notes += 1
            # Could be from years we've removed; show as info, not fail.
            print(f"  NOTE: {len(extra_t)} alias team_file_name values are not in any current CSV:")
            for t in extra_t[:10]:
                print(f"    {t!r}  (was in a previous load — keep if still meaningful, delete otherwise)")
    print()

    # ----- CHECK 7: coverage on player-file side -------------------------
    print("CHECK 7 — Every player-file string from every year is in the alias")
    alias_player = {r["player_file_name"] for r in aliases if r.get("player_file_name")}
    missing_p = sorted(all_player_strings - alias_player)
    extra_p   = sorted(alias_player - all_player_strings)
    if not missing_p and not extra_p:
        print(f"  PASS: all {len(all_player_strings)} player-file strings represented")
    else:
        if missing_p:
            issues += 1
            print(f"  FAIL: {len(missing_p)} player-file strings NOT in alias:")
            for t in missing_p[:10]:
                years_in = sorted(y for y, s in player_strings_by_year.items() if t in s)
                print(f"    {t!r}  (years: {years_in})")
        if extra_p:
            notes += 1
            print(f"  NOTE: {len(extra_p)} alias player_file_name values are not in any current CSV:")
            for t in extra_p[:10]:
                print(f"    {t!r}")
    print()

    # ----- CHECK 8: round-trip via every player CSV ----------------------
    print("CHECK 8 — Round-trip: every player.Team in every year maps via alias")
    p_to_canon = {r["player_file_name"]: r["canonical_name"]
                  for r in aliases if r.get("player_file_name")}
    unmapped_total = 0
    for player_csv in player_csvs:
        year = int(PLAYER_CSV_PATTERN.match(player_csv.name).group(1))
        unmapped = set()
        with open(player_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = row.get("Team")
                if t and t not in p_to_canon:
                    unmapped.add(t)
        if unmapped:
            issues += 1
            unmapped_total += len(unmapped)
            print(f"  FAIL ({year}): {len(unmapped)} player.Team values can't be mapped:")
            for t in sorted(unmapped)[:5]:
                print(f"    {t!r}")
    if master_path.exists():
        unmapped = set()
        with open(master_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = row.get("Team")
                if t and t not in p_to_canon:
                    unmapped.add(t)
        if unmapped:
            issues += 1
            unmapped_total += len(unmapped)
            print(f"  FAIL (master): {len(unmapped)} player.Team values can't be mapped:")
            for t in sorted(unmapped)[:10]:
                print(f"    {t!r}")
    if unmapped_total == 0:
        srcs = f"{len(player_csvs)} per-year file(s)" + (" + master" if master_path.exists() else "")
        print(f"  PASS: every player.Team resolves to a canonical ({srcs})")
    print()

    # ----- CHECK 9: canonical-name duplicates (informational) ------------
    # Allowed and intentional for name-change cases (East Texas A&M ↔
    # Texas A&M-Commerce). List them so you can verify each one is
    # intentional, not an accidental alias collision.
    print("CHECK 9 — canonical_name duplicates (expected for name-change cases)")
    canon_to_rows = defaultdict(list)
    for r in aliases:
        canon_to_rows[r["canonical_name"]].append(r)
    multi_canon = {c: rs for c, rs in canon_to_rows.items() if len(rs) > 1 and c}
    if not multi_canon:
        print(f"  PASS: every canonical_name appears exactly once (no name-change cases)")
    else:
        notes += 1
        print(f"  NOTE: {len(multi_canon)} canonical_name(s) appear on multiple rows.")
        print(f"  Allowed for name changes; CHECK 10 fails any whose names co-occur in a season:")
        for canon in sorted(multi_canon.keys()):
            rs = multi_canon[canon]
            sources = [(r['team_file_name'], r['player_file_name']) for r in rs]
            print(f"    {canon!r} x{len(rs)}:")
            for tfn, pfn in sources:
                print(f"      team={tfn!r}  player={pfn!r}")
    print()

    # ----- CHECK 10: canonical collisions — distinct schools merged ------
    # A repeated canonical is legitimate ONLY for a rename: the old and new
    # source names are ONE school, so they never appear in the same season.
    # If two source strings under one canonical DO co-occur in a season, they
    # are two DIFFERENT schools wrongly merged (e.g. Southeast Missouri State
    # folded into 'Missouri State'). CHECK 9 lists repeats but can't tell a
    # rename from a collision — this check does, and fails the collisions.
    #
    # The test uses PLAYER-side seasons only. The team CSVs label every season
    # with a school's CURRENT name (retroactive), so a team string would overlap
    # its own pre-rename player string and raise false alarms. Player data keeps
    # the historical name, so its season span is the reliable signal.
    print("CHECK 10 — No canonical shared by schools that co-occur in a season")
    player_years_by_string = defaultdict(set)
    for yr, strings in player_strings_by_year.items():
        for s in strings:
            player_years_by_string[s].add(yr)

    def _season_label(y):
        return f"{y}-{(y + 1) % 100:02d}"

    collisions = []
    for canon, rs in sorted(multi_canon.items()):
        spans = [(r, player_years_by_string.get(r.get("player_file_name") or "", set()))
                 for r in rs]
        for i in range(len(spans)):
            for j in range(i + 1, len(spans)):
                (ri, yi), (rj, yj) = spans[i], spans[j]
                shared = yi & yj
                if shared:
                    collisions.append((canon, ri.get("player_file_name"),
                                       rj.get("player_file_name"), sorted(shared)))
    if not collisions:
        print(f"  PASS: every repeated canonical is a clean rename (no shared seasons)")
    else:
        issues += 1
        bad_canons = sorted({c for c, *_ in collisions})
        print(f"  FAIL: {len(bad_canons)} canonical(s) merge schools that share a season "
              f"({len(collisions)} conflicting pair(s)):")
        for canon, a, b, shared in collisions:
            span = f"{_season_label(shared[0])}..{_season_label(shared[-1])}"
            print(f"    canonical {canon!r}: {a!r} ↔ {b!r}")
            print(f"      {len(shared)} shared season(s) {span} "
                  f"→ give one its own canonical_name if they're different schools")
    print()

    # ----- SUMMARY -------------------------------------------------------
    print("=" * 60)
    if issues == 0:
        print(f"VERIFICATION PASSED — alias map covers every loaded season cleanly")
        if notes:
            print(f"({notes} informational note(s) above — review for intentionality)")
    else:
        print(f"VERIFICATION FOUND {issues} ISSUE(S) — see details above")

if __name__ == "__main__":
    main()
