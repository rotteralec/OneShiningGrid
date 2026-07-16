#!/usr/bin/env python3
"""
build_womens_placeholder.py — SAMPLE women's data for One Shining Grid.

Emits the three files the frontend fetches when the WOMEN'S league is on
(?w in the URL), in exactly the shape build_game_data.py produces:

    public/player_index_w.json   search index  {meta, players[{slug,name,team,season}]}
    public/daily_grid_w.json     single-day legacy shape {day, date, modes, meta}
    public/test_grids_w.json     ?test preview shape {test, day, count, modes:{m:[...]}}

This is a HAND-CURATED PLACEHOLDER (~50 famous players, 3 fixed grids) so the
women's frontend is playable while the real stat database is being gathered.
meta.placeholder = true makes the frontend show a "sample puzzle" banner.
Facts are approximate — good enough to demo, not authoritative.

Once the real women's CSVs exist, a women's build in build_game_data.py
replaces these files and this script retires. Run: python3 build_womens_placeholder.py
"""

import json
from datetime import date
from pathlib import Path

EPOCH = date(2026, 1, 1)  # day 1 — must mirror build_game_data.py / the frontend

# ---- criteria (columns) ----------------------------------------------------

CRITERIA = {
    "w20ppg":     {"id": "w20ppg",     "type": "stat",  "label": "Avg 20+ PPG",      "kicker": "Per-Game"},
    "w10rpg":     {"id": "w10rpg",     "type": "stat",  "label": "Avg 10+ RPG",      "kicker": "Per-Game"},
    "w5apg":      {"id": "w5apg",      "type": "stat",  "label": "Avg 5+ APG",       "kicker": "Per-Game"},
    "wpos_g":     {"id": "wpos_g",     "type": "pos",   "label": "Guard",            "kicker": "Position"},
    "wdraft":     {"id": "wdraft",     "type": "draft", "label": "WNBA Draft Pick",  "kicker": "Pro Career"},
    "wdraft_no1": {"id": "wdraft_no1", "type": "draft", "label": "WNBA #1 Overall",  "kicker": "Pro Career"},
}

# ---- schools (rows) — real brand colors, fg picked for contrast ------------

SCHOOLS = {
    "uconn":          {"id": "school_uconn",          "type": "school", "label": "UConn",          "kicker": "Played For", "bg": "#000E2F", "accent": "#E4002B", "fg": "#f5ecd7"},
    "tennessee":      {"id": "school_tennessee",      "type": "school", "label": "Tennessee",      "kicker": "Played For", "bg": "#FF8200", "accent": "#FFFFFF", "fg": "#1a1f3a"},
    "south_carolina": {"id": "school_south_carolina", "type": "school", "label": "South Carolina", "kicker": "Played For", "bg": "#73000A", "accent": "#000000", "fg": "#f5ecd7"},
    "iowa":           {"id": "school_iowa",           "type": "school", "label": "Iowa",           "kicker": "Played For", "bg": "#000000", "accent": "#FFCD00", "fg": "#f5ecd7"},
    "lsu":            {"id": "school_lsu",            "type": "school", "label": "LSU",            "kicker": "Played For", "bg": "#461D7C", "accent": "#FDD023", "fg": "#f5ecd7"},
    "stanford":       {"id": "school_stanford",       "type": "school", "label": "Stanford",       "kicker": "Played For", "bg": "#8C1515", "accent": "#FFFFFF", "fg": "#f5ecd7"},
    "notre_dame":     {"id": "school_notre_dame",     "type": "school", "label": "Notre Dame",     "kicker": "Played For", "bg": "#0C2340", "accent": "#C99700", "fg": "#f5ecd7"},
    "usc":            {"id": "school_usc",            "type": "school", "label": "USC",            "kicker": "Played For", "bg": "#990000", "accent": "#FFCC00", "fg": "#f5ecd7"},
    "baylor":         {"id": "school_baylor",         "type": "school", "label": "Baylor",         "kicker": "Played For", "bg": "#154734", "accent": "#FFB81C", "fg": "#f5ecd7"},
}

# ---- players ---------------------------------------------------------------
# (name, display team, season span, [school tags], [criterion tags])
# Tags are "ever" facts like the men's model: any school ever + any criterion ever.

PLAYERS = [
    # UConn
    ("Sue Bird",            "UConn",          "1998-02", ["uconn"],               ["wpos_g", "wdraft", "wdraft_no1"]),
    ("Diana Taurasi",       "UConn",          "2000-04", ["uconn"],               ["wpos_g", "wdraft", "wdraft_no1"]),
    ("Maya Moore",          "UConn",          "2007-11", ["uconn"],               ["w20ppg", "wdraft", "wdraft_no1"]),
    ("Breanna Stewart",     "UConn",          "2012-16", ["uconn"],               ["w20ppg", "wdraft", "wdraft_no1"]),
    ("Tina Charles",        "UConn",          "2006-10", ["uconn"],               ["w10rpg", "wdraft", "wdraft_no1"]),
    ("Napheesa Collier",    "UConn",          "2015-19", ["uconn"],               ["w20ppg", "w10rpg", "wdraft"]),
    ("Paige Bueckers",      "UConn",          "2020-25", ["uconn"],               ["w20ppg", "wpos_g", "wdraft", "wdraft_no1"]),
    ("Azzi Fudd",           "UConn",          "2021-25", ["uconn"],               ["wpos_g", "wdraft"]),
    ("Rebecca Lobo",        "UConn",          "1991-95", ["uconn"],               ["w10rpg", "wdraft"]),
    ("Kaleena Mosqueda-Lewis", "UConn",       "2011-15", ["uconn"],               ["wpos_g", "wdraft"]),
    ("Moriah Jefferson",    "UConn",          "2012-16", ["uconn"],               ["wpos_g", "wdraft"]),
    # Tennessee
    ("Chamique Holdsclaw",  "Tennessee",      "1995-99", ["tennessee"],           ["w20ppg", "w10rpg", "wdraft", "wdraft_no1"]),
    ("Candace Parker",      "Tennessee",      "2005-08", ["tennessee"],           ["w20ppg", "wdraft", "wdraft_no1"]),
    ("Tamika Catchings",    "Tennessee",      "1997-01", ["tennessee"],           ["wdraft"]),
    ("Kara Lawson",         "Tennessee",      "1999-03", ["tennessee"],           ["wpos_g", "wdraft"]),
    ("Diamond DeShields",   "Tennessee",      "2013-18", ["tennessee"],           ["wpos_g", "wdraft"]),
    ("Rickea Jackson",      "Tennessee",      "2019-24", ["tennessee"],           ["w20ppg", "wdraft"]),
    ("Bridgette Gordon",    "Tennessee",      "1985-89", ["tennessee"],           ["w20ppg", "wdraft"]),
    # South Carolina
    ("A'ja Wilson",         "South Carolina", "2014-18", ["south_carolina"],      ["w20ppg", "w10rpg", "wdraft", "wdraft_no1"]),
    ("Aliyah Boston",       "South Carolina", "2019-23", ["south_carolina"],      ["w10rpg", "wdraft", "wdraft_no1"]),
    ("Zia Cooke",           "South Carolina", "2019-23", ["south_carolina"],      ["wpos_g", "wdraft"]),
    ("Tiffany Mitchell",    "South Carolina", "2012-16", ["south_carolina"],      ["wpos_g", "wdraft"]),
    ("Kamilla Cardoso",     "South Carolina", "2020-24", ["south_carolina"],      ["wdraft"]),
    ("Ty Harris",           "South Carolina", "2016-20", ["south_carolina"],      ["wpos_g", "wdraft"]),
    ("Sheila Foster",       "South Carolina", "1978-82", ["south_carolina"],      ["w20ppg", "w10rpg"]),
    # Iowa
    ("Caitlin Clark",       "Iowa",           "2020-24", ["iowa"],                ["w20ppg", "w5apg", "wpos_g", "wdraft", "wdraft_no1"]),
    ("Megan Gustafson",     "Iowa",           "2015-19", ["iowa"],                ["w20ppg", "w10rpg", "wdraft"]),
    ("Kathleen Doyle",      "Iowa",           "2016-20", ["iowa"],                ["w5apg", "wpos_g", "wdraft"]),
    ("Monika Czinano",      "Iowa",           "2018-23", ["iowa"],                ["wdraft"]),
    ("Samantha Logic",      "Iowa",           "2011-15", ["iowa"],                ["w5apg", "wpos_g", "wdraft"]),
    # LSU
    ("Seimone Augustus",    "LSU",            "2002-06", ["lsu"],                 ["w20ppg", "wdraft", "wdraft_no1"]),
    ("Sylvia Fowles",       "LSU",            "2004-08", ["lsu"],                 ["w10rpg", "wdraft"]),
    ("Angel Reese",         "LSU",            "2020-24", ["lsu"],                 ["w20ppg", "w10rpg", "wdraft"]),
    ("Temeka Johnson",      "LSU",            "2001-05", ["lsu"],                 ["w5apg", "wpos_g", "wdraft"]),
    ("Flau'jae Johnson",    "LSU",            "2022-26", ["lsu"],                 ["wpos_g"]),
    # Stanford
    ("Nneka Ogwumike",      "Stanford",       "2008-12", ["stanford"],            ["w20ppg", "w10rpg", "wdraft", "wdraft_no1"]),
    ("Chiney Ogwumike",     "Stanford",       "2010-14", ["stanford"],            ["w20ppg", "w10rpg", "wdraft", "wdraft_no1"]),
    ("Candice Wiggins",     "Stanford",       "2004-08", ["stanford"],            ["w20ppg", "wpos_g", "wdraft"]),
    ("Jennifer Azzi",       "Stanford",       "1986-90", ["stanford"],            ["w5apg", "wpos_g", "wdraft"]),
    ("Kate Starbird",       "Stanford",       "1993-97", ["stanford"],            ["w20ppg", "wpos_g", "wdraft"]),
    ("Haley Jones",         "Stanford",       "2019-23", ["stanford"],            ["wdraft"]),
    # Notre Dame
    ("Skylar Diggins",      "Notre Dame",     "2009-13", ["notre_dame"],          ["w5apg", "wpos_g", "wdraft"]),
    ("Arike Ogunbowale",    "Notre Dame",     "2015-19", ["notre_dame"],          ["w20ppg", "wpos_g", "wdraft"]),
    ("Jewell Loyd",         "Notre Dame",     "2012-15", ["notre_dame"],          ["wpos_g", "wdraft", "wdraft_no1"]),
    ("Jackie Young",        "Notre Dame",     "2016-19", ["notre_dame"],          ["wpos_g", "wdraft", "wdraft_no1"]),
    ("Ruth Riley",          "Notre Dame",     "1997-01", ["notre_dame"],          ["w10rpg", "wdraft"]),
    ("Natalie Achonwa",     "Notre Dame",     "2010-14", ["notre_dame"],          ["wdraft"]),
    # USC
    ("Cheryl Miller",       "USC",            "1982-86", ["usc"],                 ["w20ppg", "w10rpg"]),
    ("Lisa Leslie",         "USC",            "1990-94", ["usc"],                 ["w20ppg", "w10rpg", "wdraft"]),
    ("Tina Thompson",       "USC",            "1993-97", ["usc"],                 ["w10rpg", "wdraft", "wdraft_no1"]),
    ("Cynthia Cooper",      "USC",            "1982-86", ["usc"],                 ["w5apg", "wpos_g", "wdraft"]),
    ("JuJu Watkins",        "USC",            "2023-26", ["usc"],                 ["w20ppg", "wpos_g"]),
    # Baylor
    ("Brittney Griner",     "Baylor",         "2009-13", ["baylor"],              ["w20ppg", "wdraft", "wdraft_no1"]),
    ("Odyssey Sims",        "Baylor",         "2010-14", ["baylor"],              ["w20ppg", "w5apg", "wpos_g", "wdraft"]),
    ("NaLyssa Smith",       "Baylor",         "2018-22", ["baylor"],              ["w10rpg", "wdraft"]),
    ("Sophia Young",        "Baylor",         "2002-06", ["baylor"],              ["w20ppg", "w10rpg", "wdraft"]),
    ("Nina Davis",          "Baylor",         "2013-17", ["baylor"],              ["w10rpg"]),
]

# ---- the three fixed sample grids (rows x cols per mode) --------------------

GRIDS = {
    "easy":   {"rows": ["uconn", "tennessee", "south_carolina"], "cols": ["w20ppg", "wdraft", "wpos_g"]},
    "medium": {"rows": ["iowa", "lsu", "stanford"],              "cols": ["w10rpg", "w5apg", "w20ppg"]},
    "hard":   {"rows": ["notre_dame", "usc", "baylor"],          "cols": ["wdraft_no1", "w10rpg", "w5apg"]},
}


def slugify(name):
    import re
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")
    return f"{s}-1"


def main():
    players = []
    for name, team, span, schools, tags in PLAYERS:
        players.append({
            "slug": slugify(name), "name": name, "team": team, "season": span,
            "_schools": set(schools), "_tags": set(tags),
        })
    slugs = [p["slug"] for p in players]
    assert len(slugs) == len(set(slugs)), "duplicate slug"

    def build_mode(spec):
        rows = [SCHOOLS[r] for r in spec["rows"]]
        cols = [CRITERIA[c] for c in spec["cols"]]
        valid = []
        for rk in spec["rows"]:
            for ck in spec["cols"]:
                cell = sorted(p["slug"] for p in players if rk in p["_schools"] and ck in p["_tags"])
                valid.append(cell)
        return {"rows": rows, "cols": cols, "valid_per_cell": valid,
                "min_per_cell": 1, "achieved_min": min(len(v) for v in valid)}

    modes = {m: build_mode(spec) for m, spec in GRIDS.items()}
    for m, md in modes.items():
        counts = [len(v) for v in md["valid_per_cell"]]
        assert all(counts), f"{m}: empty cell {counts}"
        print(f"  {m:7s} valid-per-cell: {counts}")

    today = date.today()
    day = (today - EPOCH).days + 1
    meta = {
        "placeholder": True,   # frontend shows the "sample puzzle" banner
        "league": "w",
        "min_games_for_average": 15, "min_fga_for_pct": 200,
        "min_3pa_for_pct": 100, "min_fta_for_pct": 50,
    }

    out = Path(__file__).parent / "public"
    out.mkdir(exist_ok=True)

    # Single-day legacy shape: no `grids` horizon, so the frontend shows this
    # puzzle regardless of the date — it never "expires" while it's a sample.
    daily = {"day": day, "date": today.isoformat(), "modes": modes, "meta": meta,
             "generated": f"{today.isoformat()} build_womens_placeholder.py"}
    (out / "daily_grid_w.json").write_text(json.dumps(daily, indent=1))

    # ?test preview shape (arrays per mode; just 1 sample puzzle each for now).
    test = {"test": True, "day": day, "date": today.isoformat(), "count": 1,
            "modes": {m: [md] for m, md in modes.items()}, "meta": meta}
    (out / "test_grids_w.json").write_text(json.dumps(test, indent=1))

    idx = {
        "meta": {
            "placeholder": True, "league": "w",
            "player_count": len(players),
            "school_count": len(SCHOOLS),
            "seasons": ["1978-79", "2025-26"],
        },
        "players": [{k: p[k] for k in ("slug", "name", "team", "season")}
                    for p in sorted(players, key=lambda p: p["name"])],
    }
    (out / "player_index_w.json").write_text(json.dumps(idx, indent=1))

    print(f"wrote public/daily_grid_w.json (day {day}), test_grids_w.json, "
          f"player_index_w.json ({len(players)} players)")


if __name__ == "__main__":
    main()
