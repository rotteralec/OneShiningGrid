# One Shining Grid

A daily college basketball trivia grid — nine cells, nine guesses. Match players
to schools, conferences, stats, and NBA draft history.

Live at [oneshininggrid.com](https://oneshininggrid.com).

## How it works

Each puzzle is three rows (schools or conferences) crossed with three columns
(statistical or draft criteria). A player satisfies a cell if they ever met both
the row and the column — the two need not be the same season.

Every puzzle ships in three difficulty modes. Difficulty is driven by the minimum
number of valid answers each cell must have, plus how deep the row pool reaches
past the blue bloods.

## Running locally

```
npm install
npm run dev
```

This serves the committed puzzle data in `public/` at `localhost:5173`. No Python
or stat files required.

URL flags:

- `?w` — women's edition (placeholder data for now)
- `?test` — flip through several puzzles per mode instead of waiting for the daily roll

## Data pipeline

The stat inputs are large and re-sourceable, so they are not in the repo.
`build_game_data.py` reads them and writes the two small JSON files the frontend
actually fetches:

```
cbb_player_seasons_master.csv  ─┐
cbb_conferences_master.csv     ─┼─→  build_game_data.py  ─→  public/player_index.json
nba_draft_master.csv           ─┘                            public/daily_grid.json
```

Those JSONs are committed, which is what lets the site deploy as a plain static
build with no server or database. Regenerate them with `npm run data`. Useful
flags: `--date YYYY-MM-DD`, `--days N`, `--test [N]`.

Note that because the input CSVs are gitignored, a fresh clone can run the game
but cannot rebuild the data.

Every Python script is standard library only — nothing to install.

Supporting scripts:

- `consolidate_*.py` — fold the raw per-season exports into the master CSVs
- `verify_*.py` — re-derive each master from its sources and check it row by row
- `build_school_aliases.py` — reconcile school-name spellings across sources
- `build_school_colors.py` — generate the per-school pennant colors

## Deploying

Push to `master`. GitHub Actions builds with Vite and deploys to Azure Static Web Apps.

## Third-party data

School colors in `school_colors.csv` are derived from
[ncaahoopR](https://github.com/lbenz730/ncaahoopR) by Luke Benz, used under the
MIT License:

> Copyright (c) 2021 Luke Benz
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Player, team, conference, and draft records originate with Sports Reference. That
data belongs to its original sources and appears here only to make the game
playable.
