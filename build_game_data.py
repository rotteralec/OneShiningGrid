"""
   One Shining Grid — build the frontend JSON files.

   Reads the consolidated CSVs and emits TWO files into public/ for the
   Vite dev server to serve:

     public/player_index.json  — every player's id + display fields (name,
                                 team, season, pos, class). The frontend
                                 uses this to populate the search picker.
                                 ~5,000 records, ~300 KB. Regenerate when
                                 new player data is added.

     public/daily_grid.json    — today's 3 schools (rows) and 3 criteria
                                 (cols), plus the list of valid player
                                 slugs per cell. Tiny (~5 KB). Regenerate
                                 each day to roll the puzzle forward.

   The frontend never sees raw stats. Validation is just "is the picked
   player's slug in the valid set for this cell?" — yes/no.

   READ-ONLY on every CSV input.
"""

import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT       = Path(__file__).parent
PLAYER_CSV = ROOT / "cbb_player_seasons_master.csv"   # all 27 seasons; one row per player-season
ALIAS_CSV  = ROOT / "school_aliases.csv"
PUBLIC_DIR = ROOT / "public"

# Conference + NBA-draft inputs and their name-reconciliation maps (read-only).
CONF_CSV            = ROOT / "cbb_conferences_1999-2026" / "1999-2026-conferences.csv"
CONF_SCHOOL_ALIAS   = ROOT / "conference_school_aliases.csv"
CONF_LABELS_CSV     = ROOT / "conference_labels.csv"
DRAFT_CSV           = ROOT / "nba_draft_2000-2026" / "2000-2026-ALL.csv"
DRAFT_COLLEGE_ALIAS = ROOT / "draft_college_aliases.csv"
DRAFT_PLAYER_ALIAS  = ROOT / "draft_player_aliases.csv"

# ----- CONFIG: criteria thresholds ---------------------------------------

# Minimum games for any per-game-average criterion. Keeps a single hot game
# from satisfying e.g. "20+ PPG".
MIN_GAMES_FOR_AVERAGE = 15
MIN_FGA_FOR_PCT       = 200
MIN_3PA_FOR_PCT       = 100
MIN_FTA_FOR_PCT       = 50

# ----- DIFFICULTY MODES --------------------------------------------------
# Each daily puzzle is generated in three modes. The number below is the
# minimum count of valid answers EVERY cell must have — that's the main lever
# for difficulty. All schools always count as valid ANSWERS regardless of mode;
# the pool only controls which schools can appear as a row.
EASY_MIN_PER_CELL   = 10   # marquee schools only, very solvable
MEDIUM_MIN_PER_CELL = 8    # all schools, fair
HARD_MIN_PER_CELL   = 5    # all schools, random criteria, still tough

# ----- NO-REPEAT (cross-day variety) -------------------------------------
# Each build records the schools/criteria it used to grid_history.json (repo
# root — COMMIT IT; that's how variety persists between daily builds). A row
# (school/conference) or column (criterion) must sit out this many days before
# it can return, PER MODE. Schools matter most → longer windows; Easy's pools
# are tiny so its windows are short (it would otherwise relax every day). When a
# window can't be honored, the build relaxes gracefully (criteria first, then
# schools, then the difficulty floor). All tunable.
HISTORY_FILE = ROOT / "grid_history.json"
ROW_WINDOW   = {"easy": 6, "medium": 14, "hard": 21}   # schools + conferences
COL_WINDOW   = {"easy": 2, "medium": 3,  "hard": 4}    # criteria

# Max of a grid's 3 rows that may be CONFERENCES (the rest must be schools), per
# mode. Capped at 2 everywhere → every grid in every mode has >=1 real school.
MAX_CONF_PER_GRID = {"easy": 2, "medium": 2, "hard": 2}

# Easy mode only draws its columns from these "recallable" criteria — scoring,
# rebounding, assists, position, and (senior) class. The niche stats (block
# rate, 3P%, FT%, steals, 50/40/90) are reserved for Medium/Hard.
EASY_CRITERIA_IDS = {
    "20ppg", "15ppg", "10rpg", "7rpg", "5apg", "600pts", "250trb", "150ast",
    "pos_g", "pos_f", "pos_c", "class_sr",
}

# Class criteria are disabled except Senior for now: under the "any season"
# model a player counts as Freshman/Sophomore/Junior if ANY season was that
# class, so those match almost everyone and aren't meaningful. Senior is the
# useful one (4-year players vs early departures). Revisit with same-season
# logic later.
EXCLUDED_CRITERIA_IDS = {"class_fr", "class_so", "class_jr"}

# Easy mode draws its row schools ONLY from this curated list of recognizable
# programs (use the canonical_name spelling exactly as in school_aliases.csv).
# Conference membership churns too much to encode, so this is a hand-kept list.
# Until it has >=3 names that match the data, Easy mode falls back to all
# schools (with a warning).
MARQUEE_SCHOOLS = [
    "Connecticut", "North Carolina", "Duke", "Florida", "Michigan State",
    "Michigan", "Purdue", "Villanova", "Kentucky", "Kansas", "Gonzaga",
    "Virginia", "Arizona", "UCLA", "Houston", "Louisville", "Illinois", "Maryland", 
    "Texas",  "Indiana", "Ohio State", "Wisconsin", 

]

# Medium mode draws from a wider "recognizable" tier: the marquee list PLUS
# these extras (canonical_name spelling). Medium pool = MARQUEE_SCHOOLS UNION
# MEDIUM_SCHOOLS. Until MEDIUM_SCHOOLS is filled, Medium falls back to ALL
# schools (with a warning). Target ~100 programs total.
MEDIUM_SCHOOLS = [
    # User-curated "recognizable" tier (canonical spellings). Unioned with
    # MARQUEE_SCHOOLS to form the Medium pool.
    "St. John's (NY)", "NC State", "Kansas State", "Temple", "Notre Dame",
    "Western Kentucky", "Oklahoma State", "DePaul", "UNLV", "Minnesota",
    "Georgetown", "Seton Hall", "Washington", "Providence", "Brigham Young",
    "Texas Tech", "Missouri", "Dayton", "Louisiana State", "Stanford", "Iowa",
    "Vanderbilt", "Arizona State", "Wake Forest", "South Carolina", "New Mexico",
    "California", "Clemson", "Boston College", "Miami (FL)", "Xavier",
    "Florida State", "Georgia", "Auburn", "Iowa State", "Southern California",
    "Pittsburgh", "Wichita State", "San Diego State", "Creighton", "West Virginia", "Cincinnati",
    "Oklahoma", "Marquette", "Tennessee", "Arkansas", "Oregon",
    # additions
    "Alabama", "Texas A&M", "Mississippi State", "Ole Miss", "Georgia Tech",
    "Virginia Tech", "Penn State", "Northwestern", "Rutgers", "Nebraska",
    "TCU", "UCF", "Butler", "St. Mary's (CA)", "Loyola Chicago",
    "Florida Atlantic", "Nevada", "Memphis", "Baylor", "Syracuse", 
]

# Conference row tiers (Rothstein uses ALL conferences). Curated like the
# school tiers. "AAC" covers the American Athletic in both label eras (the
# 2025-26 "American" label is merged into AAC in conference_labels.csv).
EASY_CONFERENCES   = ["Big Ten", "Big 12", "ACC", "SEC", "Big East"]
MEDIUM_CONFERENCES = EASY_CONFERENCES + [
    "CUSA", "AAC", "MWC", "Sun Belt", "Ivy", "MAC", "Big Sky",
    "MEAC", "Southland", "Summit", "WAC",
]

# ----- HELPERS -----------------------------------------------------------

def safe_int(s, default=0):
    try: return int(s)
    except (ValueError, TypeError): return default

def safe_float(s, default=0.0):
    try: return float(s)
    except (ValueError, TypeError): return default

# ----- CRITERIA DEFINITIONS ----------------------------------------------

# Each criterion has: id, type, label, kicker, predicate(row) → bool.
# Predicates run server-side only — never shipped to the client.
CRITERIA = [
    # Per-game averages
    {"id": "20ppg", "type": "stat", "label": "Avg 20+ PPG", "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["PTS"]) / max(safe_int(r["G"]), 1) >= 20},
    {"id": "15ppg", "type": "stat", "label": "Avg 15+ PPG", "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["PTS"]) / max(safe_int(r["G"]), 1) >= 15},
    {"id": "10rpg", "type": "stat", "label": "Avg 10+ RPG", "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["TRB"]) / max(safe_int(r["G"]), 1) >= 10},
    {"id": "7rpg",  "type": "stat", "label": "Avg 7+ RPG",  "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["TRB"]) / max(safe_int(r["G"]), 1) >= 7},
    {"id": "5apg",  "type": "stat", "label": "Avg 5+ APG",  "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["AST"]) / max(safe_int(r["G"]), 1) >= 5},
    {"id": "2spg",  "type": "stat", "label": "Avg 2+ SPG",  "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["STL"]) / max(safe_int(r["G"]), 1) >= 2},
    {"id": "1bpg",  "type": "stat", "label": "Avg 1+ BPG",  "kicker": "Per-Game",
     "predicate": lambda r: safe_int(r["G"]) >= MIN_GAMES_FOR_AVERAGE
                            and safe_int(r["BLK"]) / max(safe_int(r["G"]), 1) >= 1},

    # Shooting efficiency
    {"id": "fg50",   "type": "stat", "label": "50%+ FG",          "kicker": "Shooting",
     "predicate": lambda r: safe_int(r["FGA"]) >= MIN_FGA_FOR_PCT and safe_float(r["FG%"]) >= 0.500},
    {"id": "3p40",   "type": "stat", "label": "40%+ from Three",  "kicker": "Shooting",
     "predicate": lambda r: safe_int(r["3PA"]) >= MIN_3PA_FOR_PCT and safe_float(r["3P%"]) >= 0.400},
    {"id": "ft90",   "type": "stat", "label": "90%+ FT",          "kicker": "Shooting",
     "predicate": lambda r: safe_int(r["FTA"]) >= MIN_FTA_FOR_PCT and safe_float(r["FT%"]) >= 0.900},
    {"id": "504090", "type": "stat", "label": "50/40/90 Club",    "kicker": "Shooting",
     "predicate": lambda r: (safe_int(r["FGA"]) >= MIN_FGA_FOR_PCT and safe_float(r["FG%"]) >= 0.500
                          and safe_int(r["3PA"]) >= MIN_3PA_FOR_PCT and safe_float(r["3P%"]) >= 0.400
                          and safe_int(r["FTA"]) >= MIN_FTA_FOR_PCT and safe_float(r["FT%"]) >= 0.900)},

    # Season totals
    {"id": "600pts", "type": "stat", "label": "600+ PTS (season)", "kicker": "Total",
     "predicate": lambda r: safe_int(r["PTS"]) >= 600},
    {"id": "250trb", "type": "stat", "label": "250+ REB (season)", "kicker": "Total",
     "predicate": lambda r: safe_int(r["TRB"]) >= 250},
    {"id": "150ast", "type": "stat", "label": "150+ AST (season)", "kicker": "Total",
     "predicate": lambda r: safe_int(r["AST"]) >= 150},
    {"id": "60stl",  "type": "stat", "label": "60+ STL (season)",  "kicker": "Total",
     "predicate": lambda r: safe_int(r["STL"]) >= 60},
    {"id": "50blk",  "type": "stat", "label": "50+ BLK (season)",  "kicker": "Total",
     "predicate": lambda r: safe_int(r["BLK"]) >= 50},

    # Position (hybrids G-F satisfy both G and F)
    {"id": "pos_g", "type": "pos", "label": "Guard",   "kicker": "Position",
     "predicate": lambda r: "G" in r["Pos"].split("-") if r["Pos"] else False},
    {"id": "pos_f", "type": "pos", "label": "Forward", "kicker": "Position",
     "predicate": lambda r: "F" in r["Pos"].split("-") if r["Pos"] else False},
    {"id": "pos_c", "type": "pos", "label": "Center",  "kicker": "Position",
     "predicate": lambda r: "C" in r["Pos"].split("-") if r["Pos"] else False},

    # Class
    {"id": "class_fr", "type": "class", "label": "Freshman",  "kicker": "Class",
     "predicate": lambda r: r["Class"] == "FR"},
    {"id": "class_so", "type": "class", "label": "Sophomore", "kicker": "Class",
     "predicate": lambda r: r["Class"] == "SO"},
    {"id": "class_jr", "type": "class", "label": "Junior",    "kicker": "Class",
     "predicate": lambda r: r["Class"] == "JR"},
    {"id": "class_sr", "type": "class", "label": "Senior",    "kicker": "Class",
     "predicate": lambda r: r["Class"] == "SR"},
]

# Draft criteria are membership-precomputed from the draft file (per player),
# not row-predicates. They are COLUMNS. "NBA Draft Pick" = ANY draftee (1st OR
# 2nd round) — the broadest/most-feasible tier, and what lets draft reach
# Rothstein (whose mostly-obscure rows rarely clear the stricter tiers). Floors
# are LOWER than stat cells because a drafted player is recognizable.
DRAFT_CRITERIA = [
    {"id": "draft_pick",  "type": "draft", "label": "NBA Draft Pick", "kicker": "NBA Draft"},
    {"id": "draft_top5",  "type": "draft", "label": "Top 5 Pick",     "kicker": "NBA Draft"},
    {"id": "draft_lotto", "type": "draft", "label": "Lottery Pick",   "kicker": "NBA Draft"},
    {"id": "draft_1st",   "type": "draft", "label": "1st-Round Pick", "kicker": "NBA Draft"},
    {"id": "draft_2nd",   "type": "draft", "label": "2nd-Round Pick", "kicker": "NBA Draft"},
]
# Per-tier minimum answers/cell for draft columns. Top 5 is scarcest → lowest;
# 2nd round is low enough now to actually get picked (its names skew deep, but a
# draft-rich row keeps the cell populated).
DRAFT_MIN_PER_CELL = {"draft_pick": 3, "draft_top5": 2, "draft_lotto": 3, "draft_1st": 3, "draft_2nd": 4}
# Draft tiers allowed in EASY (2nd round stays out — too obscure for easy).
EASY_DRAFT_IDS = {"draft_pick", "draft_top5", "draft_lotto", "draft_1st"}
# Column selection: every grid is 2 stats + a 3rd "variety" slot — usually another
# stat, sometimes a draft/award tier, occasionally position/Senior. So at most
# one non-stat column (slot 3); never two draft or two award columns.
DRAFT_SLOT_PROB  = 0.25   # chance the 3rd column is a draft tier (when one qualifies)
AWARD_SLOT_PROB  = 0.22   # chance the 3rd column is an award tier (when one qualifies)
FILLER_SLOT_PROB = 0.12   # chance the 3rd column is position/Senior (when one qualifies)
TOP5_WEIGHT      = 0.25   # Top 5's pick-weight vs 1.0 for other draft tiers (keeps it rare)
WOODEN_WEIGHT    = 0.25   # Wooden's pick-weight vs 1.0 for other award tiers (keeps it rare)

# Awards (membership-precomputed from cbb_awards/, like draft). Consensus
# All-American is the workhorse (~255 players); Wooden is ultra-rare/marquee.
AWARDS_AA  = ROOT / "cbb_awards" / "consensus_all_americans.csv"   # Season,Team,Player,School
AWARDS_POY = ROOT / "cbb_awards" / "poy_winners.csv"               # Award,Season,Player,…,slug(last col)
AWARD_CRITERIA = [
    {"id": "award_aa",     "type": "award", "label": "Consensus All-American", "kicker": "Honors"},
    {"id": "award_aa1",    "type": "award", "label": "1st-Team All-American",  "kicker": "Honors"},
    {"id": "award_wooden", "type": "award", "label": "Wooden Award",           "kicker": "Honors"},
]
AWARD_MIN_PER_CELL = {"award_aa": 2, "award_aa1": 2, "award_wooden": 1}
# Awards belong in EASY too — they're recognizable and the marquee rows are
# exactly the All-American-rich schools, so the columns actually qualify there.
EASY_AWARD_IDS = {"award_aa", "award_aa1", "award_wooden"}

# ----- SCHOOL PALETTES ---------------------------------------------------

# Curated palettes for marquee schools — everyone else falls back to the
# neutral default. Visually consistent, no hand-tuning required for
# obscure schools.
CURATED_PALETTES = {
    "Duke":            {"bg": "#001A57", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "North Carolina":  {"bg": "#7BAFD4", "accent": "#13294B", "fg": "#13294B"},
    "Kentucky":        {"bg": "#0033A0", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Kansas":          {"bg": "#0051BA", "accent": "#E8000D", "fg": "#f5ecd7"},
    "UCLA":            {"bg": "#2D68C4", "accent": "#FFD100", "fg": "#f5ecd7"},
    "Connecticut":     {"bg": "#000E2F", "accent": "#E4002B", "fg": "#f5ecd7"},
    "Florida":         {"bg": "#0021A5", "accent": "#FA4616", "fg": "#f5ecd7"},
    "Michigan State":  {"bg": "#18453B", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Michigan":        {"bg": "#00274C", "accent": "#FFCB05", "fg": "#f5ecd7"},
    "Indiana":         {"bg": "#990000", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Louisville":      {"bg": "#AD0000", "accent": "#000000", "fg": "#f5ecd7"},
    "Syracuse":        {"bg": "#F76900", "accent": "#FFFFFF", "fg": "#1a1f3a"},
    "Villanova":       {"bg": "#13B5EA", "accent": "#00205B", "fg": "#1a1f3a"},
    "Gonzaga":         {"bg": "#041E42", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Houston":         {"bg": "#C8102E", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Arizona":         {"bg": "#003366", "accent": "#CC0033", "fg": "#f5ecd7"},
    "Tennessee":       {"bg": "#FF8200", "accent": "#FFFFFF", "fg": "#1a1f3a"},
    "Alabama":         {"bg": "#9E1B32", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Auburn":          {"bg": "#0C2340", "accent": "#E87722", "fg": "#f5ecd7"},
    "Purdue":          {"bg": "#CEB888", "accent": "#000000", "fg": "#1a1f3a"},
    "Wisconsin":       {"bg": "#C5050C", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Texas":           {"bg": "#BF5700", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Oklahoma":        {"bg": "#841617", "accent": "#FDF9D8", "fg": "#f5ecd7"},
    "Memphis":         {"bg": "#0C2340", "accent": "#888B8D", "fg": "#f5ecd7"},
    "Maryland":        {"bg": "#E03A3E", "accent": "#FFD520", "fg": "#f5ecd7"},
    "Illinois":        {"bg": "#13294B", "accent": "#E84A27", "fg": "#f5ecd7"},
    "Ohio State":      {"bg": "#BB0000", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "Iowa State":      {"bg": "#C8102E", "accent": "#F1BE48", "fg": "#f5ecd7"},
    "Marquette":       {"bg": "#003366", "accent": "#FFCC00", "fg": "#f5ecd7"},
    "Creighton":       {"bg": "#003366", "accent": "#0066CC", "fg": "#f5ecd7"},
    "St. John's (NY)": {"bg": "#BA0C2F", "accent": "#FFFFFF", "fg": "#f5ecd7"},
}
DEFAULT_PALETTE = {"bg": "#1a1f3a", "accent": "#d4a64a", "fg": "#f5ecd7"}
# Conferences share one neutral palette for now (no per-conference branding yet).
CONF_PALETTE    = {"bg": "#3a2a18", "accent": "#d4a64a", "fg": "#f5ecd7"}

def school_id(canonical_name):
    s = unicodedata.normalize("NFKD", canonical_name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s

# ----- DAILY-GRID SEED ----------------------------------------------------

# Matches the JS dayNumber: days counted from 2026-01-01 UTC.
EPOCH = dt.date(2026, 1, 1)

def day_number_for(date):
    return (date - EPOCH).days + 1

def mulberry32(seed):
    state = [seed & 0xFFFFFFFF]
    def rand():
        state[0] = (state[0] + 0x6d2b79f5) & 0xFFFFFFFF
        t = state[0]
        t = (t ^ (t >> 15)) * (1 | t) & 0xFFFFFFFF
        t = ((t + ((t ^ (t >> 7)) * (61 | t))) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rand

def shuffled(arr, rand):
    a = list(arr)
    for i in range(len(a) - 1, 0, -1):
        j = int(rand() * (i + 1))
        a[i], a[j] = a[j], a[i]
    return a

def _norm(s):
    """Loose school-name key: drop accents/punctuation, lowercase."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("'", "")
    for ch in ".()–-/&,": s = s.replace(ch, " ")
    return " ".join(s.split())

def _pnorm(s):
    """Player-name key: drop accents, periods, and Jr/Sr/II/III/IV suffixes."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace(".", "").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return " ".join(s.split())

def _grid_conflict(rows, school_confs):
    """True if a school row sits with a conference it ever belonged to — banned
    (e.g. Kentucky + SEC), because the school's players also fill the conference
    cell, which is a bad puzzle. School+school and conf+conf are fine."""
    conf_labels = {r["label"] for r in rows if r["type"] == "conf"}
    if not conf_labels:
        return False
    for r in rows:
        if r["type"] == "school" and (school_confs.get(r["label"], set()) & conf_labels):
            return True
    return False

def _draft_floor(c, min_per_cell):
    """Per-column floor: draft tiers use their own (lower) minimum; 2nd round and
    every non-draft column use the mode's floor."""
    if c["type"] == "draft":
        f = DRAFT_MIN_PER_CELL.get(c["id"])
        return min_per_cell if f is None else f
    if c["type"] == "award":
        f = AWARD_MIN_PER_CELL.get(c["id"])
        return min_per_cell if f is None else f
    return min_per_cell

def _weighted_pick(items, weights, rand):
    x = rand() * sum(weights)
    for it, w in zip(items, weights):
        x -= w
        if x <= 0:
            return it
    return items[-1]

def _special_weight(c):
    # keep the marquee-rare tiers (Top 5, Wooden) from dominating their own group
    return 0.25 if c["id"] in ("draft_top5", "award_wooden") else 1.0

def _pick_third(rest_stats, drafts, awards, fillers, rand):
    """The 3rd 'variety' column: usually a stat, sometimes a draft or award tier
    (Top 5 / Wooden kept rare), occasionally position/Senior. Falls back if empty."""
    pick = lambda grp: _weighted_pick(grp, [_special_weight(c) for c in grp], rand)
    roll = rand()
    if drafts and roll < DRAFT_SLOT_PROB:
        return pick(drafts)
    if awards and roll < DRAFT_SLOT_PROB + AWARD_SLOT_PROB:
        return pick(awards)
    if fillers and roll < DRAFT_SLOT_PROB + AWARD_SLOT_PROB + FILLER_SLOT_PROB:
        return shuffled(fillers, rand)[0]
    if rest_stats:
        return shuffled(rest_stats, rand)[0]
    for grp in (drafts, awards):          # fallbacks if no third stat is available
        if grp:
            return pick(grp)
    if fillers:
        return shuffled(fillers, rand)[0]
    return None

def pick_grid(row_pool, row_membership, by_criterion, rand, min_per_cell,
              criteria, school_confs, attempts=600, exclude_rows=frozenset(), exclude_cols=frozenset(),
              max_conf=3):
    """Find 3 ROWS (schools and/or conferences) x 3 COLUMNS where EVERY cell clears
    its floor and no school row sits with its own conference. Columns are STAT-
    DOMINANT: slots 1-2 are always stats; slot 3 is usually another stat, sometimes
    a draft tier, occasionally position/Senior — so at most one non-stat column, and
    never two draft columns. Draft tiers may use a lower per-cell floor (_draft_floor).
    exclude_rows/exclude_cols hold ids used too recently (cross-day no-repeat)."""
    cols_pool = [c for c in criteria
                 if c["type"] not in ("school", "conf") and c["id"] not in exclude_cols]
    pool = [r for r in row_pool
            if row_membership.get(r["id"]) and r["id"] not in exclude_rows]
    if len(pool) < 3:
        return None
    for _ in range(attempts):
        rows = shuffled(pool, rand)[:3]
        if _grid_conflict(rows, school_confs):
            continue
        if sum(1 for r in rows if r["type"] == "conf") > max_conf:
            continue
        row_slugs = [row_membership.get(r["id"], set()) for r in rows]
        def usable(c):
            f = _draft_floor(c, min_per_cell)
            return all(len(rs & by_criterion[c["id"]]) >= f for rs in row_slugs)
        stats   = [c for c in cols_pool if c["type"] == "stat"            and usable(c)]
        drafts  = [c for c in cols_pool if c["type"] == "draft"           and usable(c)]
        awards  = [c for c in cols_pool if c["type"] == "award"           and usable(c)]
        fillers = [c for c in cols_pool if c["type"] in ("pos", "class")  and usable(c)]
        if len(stats) < 2:                       # need two stats for slots 1-2
            continue
        two_stats  = shuffled(stats, rand)[:2]
        rest_stats = [c for c in stats if c not in two_stats]
        third = _pick_third(rest_stats, drafts, awards, fillers, rand)
        if third is None:
            continue
        return rows, two_stats + [third]
    return None

def build_mode(row_pool, row_membership, by_criterion, rand, min_per_cell, criteria, school_confs,
               row_age=None, col_age=None, row_window=0, col_window=0, max_conf=3):
    """pick_grid with graceful relaxation, then assemble the payload for one mode.
    row_age/col_age map id -> days-since-last-used; rows/cols used within the window
    are excluded for cross-day variety. Relaxation priority (give up first -> last):
    criteria no-repeat, then school no-repeat, then the difficulty floor."""
    row_age = row_age or {}
    col_age = col_age or {}
    def excl(age_map, w):
        return frozenset(k for k, age in age_map.items() if age <= w)

    floor = min_per_cell
    picked = None
    rows_excl = excl(row_age, row_window)
    # 1) keep floor=target; relax the CRITERIA window first (least important)...
    for cw in range(col_window, -1, -1):
        picked = pick_grid(row_pool, row_membership, by_criterion, rand, floor, criteria, school_confs,
                           exclude_rows=rows_excl, exclude_cols=excl(col_age, cw), max_conf=max_conf)
        if picked is not None:
            break
    # 2) ...then the SCHOOL window (criteria fully relaxed now)...
    if picked is None:
        for rw in range(row_window, -1, -1):
            picked = pick_grid(row_pool, row_membership, by_criterion, rand, floor, criteria, school_confs,
                               exclude_rows=excl(row_age, rw), exclude_cols=frozenset(), max_conf=max_conf)
            if picked is not None:
                break
    # 3) ...only then lower the difficulty floor (no exclusions left).
    while picked is None and floor > 1:
        floor -= 1
        picked = pick_grid(row_pool, row_membership, by_criterion, rand, floor, criteria, school_confs,
                           max_conf=max_conf)
    if picked is None:                       # last resort: ignore the per-cell target
        pool = [r for r in row_pool if row_membership.get(r["id"])] or row_pool
        rows = shuffled(pool, rand)[:3]
        for _ in range(50):                  # avoid school+own conference AND the conference cap
            if not _grid_conflict(rows, school_confs) and \
               sum(1 for r in rows if r["type"] == "conf") <= max_conf:
                break
            rows = shuffled(pool, rand)[:3]
        stat_cols  = [c for c in criteria if c["type"] == "stat"]
        other_cols = [c for c in criteria if c["type"] not in ("school", "conf", "stat")]
        cols = (stat_cols + other_cols)[:3]   # stat-dominant even in the fallback
        floor = 0
    else:
        rows, cols = picked
    valid_per_cell = []
    for r in rows:
        ss = row_membership.get(r["id"], set())
        for c in cols:
            valid_per_cell.append(sorted(ss & by_criterion[c["id"]]))
    return {
        "rows": [{"id": r["id"], "type": r["type"], "label": r["label"],
                  "kicker": r["kicker"], "bg": r["bg"], "accent": r["accent"], "fg": r["fg"]}
                 for r in rows],
        "cols": [{"id": c["id"], "type": c["type"], "label": c["label"], "kicker": c["kicker"]}
                 for c in cols],
        "valid_per_cell": valid_per_cell,
        "min_per_cell": min_per_cell,
        "achieved_min": floor,
    }

# ----- NO-REPEAT HISTORY -------------------------------------------------

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            print("WARNING: grid_history.json unreadable — starting fresh.")
    return {"version": 1, "entries": []}

def recent_ages(history, day):
    """Per mode -> {row_id: days_since_last_used} and {col_id: ...}, from PRIOR days
    only (today + future entries ignored). Smallest age wins = most recent use."""
    row_age, col_age = {}, {}
    for e in history.get("entries", []):
        age = day - e.get("day", 0)
        if age <= 0:
            continue
        for mode, mm in e.get("modes", {}).items():
            ra = row_age.setdefault(mode, {})
            ca = col_age.setdefault(mode, {})
            for rid in mm.get("rows", []):
                if age < ra.get(rid, 1 << 30): ra[rid] = age
            for cid in mm.get("cols", []):
                if age < ca.get(cid, 1 << 30): ca[cid] = age
    return row_age, col_age

def record_history(history, day, date, modes):
    """Upsert today's used rows/cols (by id; labels kept for human readability)."""
    entry = {"day": day, "date": date.isoformat(), "modes": {
        name: {
            "rows":       [r["id"]    for r in m["rows"]],
            "cols":       [c["id"]    for c in m["cols"]],
            "row_labels": [r["label"] for r in m["rows"]],
            "col_labels": [c["label"] for c in m["cols"]],
        } for name, m in modes.items()}}
    entries = [e for e in history.get("entries", []) if e.get("day") != day]   # upsert
    entries.append(entry)
    entries.sort(key=lambda e: e.get("day", 0))
    history["entries"] = entries
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")

# ----- BUILD -------------------------------------------------------------

def main():
    for f in (PLAYER_CSV, ALIAS_CSV):
        if not f.exists():
            print(f"ERROR: required file missing: {f.name}", file=sys.stderr); sys.exit(1)

    PUBLIC_DIR.mkdir(exist_ok=True)

    # --- Aliases: player-file Team → canonical name, team-file Team → canonical
    with open(ALIAS_CSV, encoding="utf-8") as f:
        alias_rows       = list(csv.DictReader(f))
        player_to_canon  = {r["player_file_name"]: r["canonical_name"] for r in alias_rows}

    # --- School colors: school_colors.csv (from ncaahoopR) wins, then the
    #     hand-curated palettes, then the neutral default.
    school_colors = {}
    sc_path = ROOT / "school_colors.csv"
    if sc_path.exists():
        for r in csv.DictReader(open(sc_path, encoding="utf-8")):
            school_colors[r["canonical_name"]] = {"bg": r["bg"], "accent": r["accent"], "fg": r["fg"]}

    schools = []
    for canonical in sorted({r["canonical_name"] for r in alias_rows}):
        palette = school_colors.get(canonical) or CURATED_PALETTES.get(canonical) or DEFAULT_PALETTE
        schools.append({
            "id":             school_id(canonical),
            "canonical_name": canonical,
            **palette,
        })
    canonical_to_school_id = {s["canonical_name"]: s["id"] for s in schools}
    school_by_id = {s["id"]: s for s in schools}

    # --- Normalized resolver (alias columns + supplement maps): used to match
    #     conference-file School names and draft-file College names to canonical.
    def _load_csv(path):
        return list(csv.DictReader(open(path, encoding="utf-8-sig"))) if path.exists() else []
    alias_norm = {}
    for r in alias_rows:
        for col in ("canonical_name", "team_file_name", "player_file_name"):
            v = (r.get(col) or "").strip()
            if v: alias_norm.setdefault(_norm(v), r["canonical_name"])
    for r in _load_csv(CONF_SCHOOL_ALIAS):
        alias_norm.setdefault(_norm(r["source_school"]), r["canonical_name"])
    for r in _load_csv(DRAFT_COLLEGE_ALIAS):
        alias_norm.setdefault(_norm(r["source_college"]), r["canonical_name"])
    def resolve_school(name):
        n = _norm(name)
        if n in alias_norm: return alias_norm[n]
        for suf in (" university", " college", " univ"):
            if n.endswith(suf) and n[:-len(suf)].strip() in alias_norm:
                return alias_norm[n[:-len(suf)].strip()]
        return None

    # --- Conference table: (season, canonical school) -> final conference.
    #     Divisions collapsed; pure renames aliased via conference_labels.csv.
    conf_label = {}                          # parent label -> (final, is_criterion)
    for r in _load_csv(CONF_LABELS_CSV):
        conf_label[r["parent_conference"]] = (
            r["final_conference"], (r.get("is_criterion") or "").strip().lower() == "yes")
    season_school_conf = {}                  # (season, canonical) -> final conference
    school_conferences = {}                  # canonical -> set(conf ever in)
    conf_is_criterion  = set()
    for r in _load_csv(CONF_CSV):
        canon = resolve_school(r["School"])
        if canon is None: continue
        parent = re.sub(r"\s*\(.*\)$", "", r["Conf"]).strip()
        final, is_crit = conf_label.get(parent, (parent, True))
        season_school_conf[(r["Season"], canon)] = final
        school_conferences.setdefault(canon, set()).add(final)
        if is_crit: conf_is_criterion.add(final)
    by_conference = {}                       # final conference -> set(slug)

    # --- Walk the master player CSV (one row per player-season) ----------
    # Model (your call): a player satisfies a criterion if ANY single season
    # satisfies it, and "played for school X" if ANY season was at X. The
    # school and the stat need NOT be the same season — per-player membership
    # sets are unioned across seasons, then intersected per cell.
    #
    # Aggregating per slug also dedupes the search index to one entry/player.
    by_school    = {}                          # school_id → set(slug)
    by_criterion = {c["id"]: set() for c in CRITERIA}
    players      = {}                          # slug → aggregated record
    seasons_seen = set()
    name_school_season_slug = {}               # (pnorm name, canonical, season) → slug  (award matching)

    with open(PLAYER_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            canonical = player_to_canon.get(row["Team"])
            if canonical is None:
                continue                       # every master Team maps (verified); guard anyway
            sid    = canonical_to_school_id[canonical]
            slug   = row["Player-additional"]
            season = row["Season"]
            seasons_seen.add(season)

            p = players.get(slug)
            if p is None:
                p = players[slug] = {
                    "slug": slug, "name": row["Player"], "teams": set(),
                    "first": season, "last": season, "latest_team": canonical,
                }
            p["teams"].add(canonical)
            if season < p["first"]:
                p["first"] = season
            if season >= p["last"]:
                p["last"] = season
                p["latest_team"] = canonical

            by_school.setdefault(sid, set()).add(slug)
            name_school_season_slug[(_pnorm(row["Player"]), canonical, season)] = slug
            conf = season_school_conf.get((season, canonical))   # year-accurate
            if conf:
                by_conference.setdefault(conf, set()).add(slug)
            for c in CRITERIA:
                try:
                    if c["predicate"](row):
                        by_criterion[c["id"]].add(slug)
                except Exception:
                    pass

    # One search record per player: name, most-recent team, and season span.
    index_records = []
    for p in players.values():
        span = p["first"][:4] if p["first"] == p["last"] else f'{p["first"][:4]}–{p["last"][:4]}'
        index_records.append({
            "slug":   p["slug"],
            "name":   p["name"],
            "team":   p["latest_team"],
            "season": span,
        })
    index_records.sort(key=lambda r: r["name"])

    # --- player_index.json (frontend search list) ---
    index_data = {
        "meta": {
            "player_count":          len(index_records),
            "seasons":               sorted(seasons_seen),
            "school_count":          len(schools),
        },
        "players": index_records,
    }
    (PUBLIC_DIR / "player_index.json").write_text(
        json.dumps(index_data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    # --- NBA draft: resolve each pick to a player slug, then build tag sets ---
    namemap = {}
    for slug, p in players.items():
        namemap.setdefault(_pnorm(p["name"]), []).append(slug)
    draft_alias = {(r["draft_player"], r["draft_year"]): r["slug"]
                   for r in _load_csv(DRAFT_PLAYER_ALIAS)}
    draft_pick = {}                          # slug -> best (lowest) pick number
    for r in _load_csv(DRAFT_CSV):
        coll = (r.get("College") or "").strip()
        if not coll: continue                # non-college draftee: out of scope
        canon = resolve_school(coll)
        if canon is None: continue           # JUCO / non-D1
        slug = draft_alias.get((r["Player"], r["Draft_Yr"]))
        if slug is None:
            cand = [s for s in namemap.get(_pnorm(r["Player"]), []) if canon in players[s]["teams"]]
            slug = cand[0] if len(cand) == 1 else None
        if slug is None: continue
        pk = safe_int(r.get("Pk"), 9999)
        if slug not in draft_pick or pk < draft_pick[slug]:
            draft_pick[slug] = pk
    by_criterion["draft_pick"]  = set(draft_pick)                                  # any draftee (1st or 2nd round)
    by_criterion["draft_top5"]  = {s for s, pk in draft_pick.items() if pk <= 5}
    by_criterion["draft_lotto"] = {s for s, pk in draft_pick.items() if pk <= 14}
    by_criterion["draft_1st"]   = {s for s, pk in draft_pick.items() if pk <= 30}
    by_criterion["draft_2nd"]   = {s for s, pk in draft_pick.items() if 31 <= pk <= 60}

    # --- Awards: Consensus All-American (name+school+season → slug, season-accurate
    #     so Brandon Roy ≠ his son) + Wooden (poy_winners.csv carries the slug). ---
    def resolve_award_slug(name, school, season):
        cs = resolve_school(school)
        slug = name_school_season_slug.get((_pnorm(name), cs, season))
        if slug:
            return slug
        cand = [s for s in namemap.get(_pnorm(name), []) if cs and cs in players[s]["teams"]]
        return cand[0] if len(cand) == 1 else None
    aa, aa1 = set(), set()
    for r in _load_csv(AWARDS_AA):
        slug = resolve_award_slug(r["Player"], r["School"], (r.get("Season") or "").strip())
        if slug:
            aa.add(slug)
            if (r.get("Team") or "").strip().startswith("1st"):
                aa1.add(slug)
    by_criterion["award_aa"]  = aa
    by_criterion["award_aa1"] = aa1
    poy_rows  = _load_csv(AWARDS_POY)
    slug_col  = list(poy_rows[0].keys())[-1] if poy_rows else None          # slug is the last column
    by_criterion["award_wooden"] = {
        (r.get(slug_col) or "").strip() for r in poy_rows
        if (r.get("Award") or "").strip() == "Wooden Award" and (r.get(slug_col) or "").strip() in players
    }
    print(f"awards: All-American {len(aa)} (1st-team {len(aa1)}), Wooden {len(by_criterion['award_wooden'])}")

    # --- Row objects: schools + conferences (either can be a puzzle row) ------
    school_rows = [{"id": s["id"], "type": "school", "label": s["canonical_name"],
                    "kicker": "Played For", "bg": s["bg"], "accent": s["accent"], "fg": s["fg"]}
                   for s in schools]
    row_membership = {s["id"]: by_school.get(s["id"], set()) for s in schools}
    conf_colors = {}
    cc_path = ROOT / "conference_colors.csv"
    if cc_path.exists():
        for r in csv.DictReader(open(cc_path, encoding="utf-8")):
            conf_colors[r["conference"]] = {"bg": r["bg"], "accent": r["accent"], "fg": r["fg"]}
    conf_rows = []
    for c in sorted(conf_is_criterion):
        if not by_conference.get(c):
            continue
        rid = "conf_" + school_id(c)
        palette = conf_colors.get(c) or CONF_PALETTE
        conf_rows.append({"id": rid, "type": "conf", "label": c, "kicker": "Played In", **palette})
        row_membership[rid] = by_conference[c]

    # --- Build today's puzzle in three difficulty modes ----------------
    today = dt.date.today()
    if "--date" in sys.argv:                 # local testing: build a specific day
        di = sys.argv.index("--date")
        if di + 1 < len(sys.argv):
            today = dt.date.fromisoformat(sys.argv[di + 1])
    day = day_number_for(today)

    marquee_set = set(MARQUEE_SCHOOLS)
    medium_set  = set(MARQUEE_SCHOOLS) | set(MEDIUM_SCHOOLS)

    # Conference row tiers: Easy = a few marquee conferences, Medium = a wider
    # curated set, Rothstein = all. Schools per mode are unchanged.
    easy_conf_set   = set(EASY_CONFERENCES)
    medium_conf_set = set(MEDIUM_CONFERENCES)
    easy_conf_rows   = [cr for cr in conf_rows if cr["label"] in easy_conf_set]
    medium_conf_rows = [cr for cr in conf_rows if cr["label"] in medium_conf_set]

    marquee_rows = [r for r in school_rows if r["label"] in marquee_set and row_membership.get(r["id"])]
    if len(marquee_rows) < 3:
        print("WARNING: MARQUEE_SCHOOLS has <3 names matching the data — Easy uses all schools.")
        marquee_rows = school_rows
    easy_rows = marquee_rows + easy_conf_rows
    if len(MEDIUM_SCHOOLS) < 3:
        print("WARNING: MEDIUM_SCHOOLS not set — Medium uses all schools.")
        medium_rows = school_rows + medium_conf_rows
    else:
        medium_rows = [r for r in school_rows if r["label"] in medium_set] + medium_conf_rows
    hard_rows = school_rows + conf_rows

    # Column pools: Easy = recallable stats only (no draft). Medium/Rothstein add
    # the draft tags. Conferences are ROWS, never columns (so no degenerate cell).
    all_criteria  = [c for c in CRITERIA
                     if c["type"] != "school" and c["id"] not in EXCLUDED_CRITERIA_IDS] + DRAFT_CRITERIA + AWARD_CRITERIA
    easy_criteria = [c for c in CRITERIA if c["id"] in EASY_CRITERIA_IDS] \
                  + [d for d in DRAFT_CRITERIA if d["id"] in EASY_DRAFT_IDS] \
                  + [a for a in AWARD_CRITERIA if a["id"] in EASY_AWARD_IDS]

    mode_specs = [
        ("easy",   easy_rows,   EASY_MIN_PER_CELL,   easy_criteria),
        ("medium", medium_rows, MEDIUM_MIN_PER_CELL, all_criteria),
        ("hard",   hard_rows,   HARD_MIN_PER_CELL,   all_criteria),
    ]
    history = load_history()
    row_age, col_age = recent_ages(history, day)     # per-mode {id: days-since-last-used}
    modes = {}
    for i, (name, pool, mn, crits) in enumerate(mode_specs):
        rand = mulberry32((day * 2654435761 + i * 40503) & 0xFFFFFFFF)
        modes[name] = build_mode(pool, row_membership, by_criterion, rand, mn, crits, school_conferences,
                                 row_age.get(name, {}), col_age.get(name, {}),
                                 ROW_WINDOW[name], COL_WINDOW[name], MAX_CONF_PER_GRID[name])

    daily = {
        "day":   day,
        "date":  today.isoformat(),
        "modes": modes,
        "meta": {
            "min_games_for_average": MIN_GAMES_FOR_AVERAGE,
            "min_fga_for_pct":       MIN_FGA_FOR_PCT,
            "min_3pa_for_pct":       MIN_3PA_FOR_PCT,
            "min_fta_for_pct":       MIN_FTA_FOR_PCT,
        },
    }
    (PUBLIC_DIR / "daily_grid.json").write_text(
        json.dumps(daily, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    record_history(history, day, today, modes)       # remember today's schools/criteria

    # ----- SUMMARY ----------------------------------------------------
    idx_size = (PUBLIC_DIR / "player_index.json").stat().st_size
    grd_size = (PUBLIC_DIR / "daily_grid.json").stat().st_size
    print(f"Wrote public/player_index.json — {len(index_records)} players, {idx_size/1024:.1f} KB")
    print(f"Wrote public/daily_grid.json   — day {day} ({today.isoformat()}), {grd_size/1024:.1f} KB")
    for name in ("easy", "medium", "hard"):
        m = modes[name]
        target = f"target >={m['min_per_cell']}/cell"
        if m["achieved_min"] != m["min_per_cell"]:
            target += f" (relaxed to >={m['achieved_min']})"
        print()
        print(f"  {name.upper()} — {target}")
        print(f"    Rows: {[r['label'] for r in m['rows']]}")
        print(f"    Cols: {[c['label'] for c in m['cols']]}")
        for ri, r in enumerate(m["rows"]):
            counts = [len(m["valid_per_cell"][ri * 3 + ci]) for ci in range(3)]
            print(f"      {r['label']:24s} {counts}")

    # ----- OPTIONAL: test set — multiple grids per mode for tester preview ----
    # `python3 build_game_data.py --test [N]` ALSO writes public/test_grids.json
    # with N (default 5) DISTINCT grids per mode. The daily files above are left
    # unchanged. The frontend loads this file only when the URL has ?test.
    if "--test" in sys.argv:
        n = 5
        ti = sys.argv.index("--test")
        if ti + 1 < len(sys.argv) and sys.argv[ti + 1].isdigit():
            n = int(sys.argv[ti + 1])
        test_modes = {}
        for i, (name, pool, mn, crits) in enumerate(mode_specs):
            seen, grids, k = set(), [], 0
            while len(grids) < n and k < n * 12:          # extra seeds until N are distinct
                rand = mulberry32((0x7E57 * 2654435761 + i * 40503 + k * 2246822519) & 0xFFFFFFFF)
                g = build_mode(pool, row_membership, by_criterion, rand, mn, crits, school_conferences,
                               max_conf=MAX_CONF_PER_GRID[name])
                sig = (tuple(r["label"] for r in g["rows"]), tuple(c["label"] for c in g["cols"]))
                if sig not in seen:
                    seen.add(sig); grids.append(g)
                k += 1
            test_modes[name] = grids
        test_data = {
            "test":  True,
            "day":   day,
            "date":  today.isoformat(),
            "count": {name: len(test_modes[name]) for name in test_modes},
            "modes": test_modes,
            "meta":  daily["meta"],
        }
        (PUBLIC_DIR / "test_grids.json").write_text(
            json.dumps(test_data, ensure_ascii=False, indent=1), encoding="utf-8")
        ts = (PUBLIC_DIR / "test_grids.json").stat().st_size
        counts = ", ".join(f"{name}:{len(test_modes[name])}" for name in ("easy", "medium", "hard"))
        print(f"\nWrote public/test_grids.json — {counts} grids/mode, {ts/1024:.1f} KB  (load with ?test)")

if __name__ == "__main__":
    main()
