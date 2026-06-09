import { useState, useMemo, useEffect, useRef } from "react";

/* ---------------------------------------------------------------
   One Shining Grid — daily college basketball grid game
   Fetches two small JSON files at runtime:
     /player_index.json — every player's display fields, for search
     /daily_grid.json   — today's 3 schools, 3 criteria, and the set
                          of valid player slugs per cell
   The frontend NEVER sees raw stats. Validation is just "is this
   player's slug in the valid set for the active cell?" — yes/no.
   Schools live on the row axis only (until we have multiple seasons).
--------------------------------------------------------------- */

// ----- ICONS -------------------------------------------------------------

// Generic icons by criterion TYPE — schools render as pennants instead.
const TYPE_ICONS = {
  stat: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 20h16" />
      <rect x="5" y="10" width="3" height="9" />
      <rect x="10" y="6" width="3" height="13" />
      <rect x="15" y="13" width="3" height="6" />
    </svg>
  ),
  pos: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="7" r="3" />
      <path d="M5 21c0-4 3-7 7-7s7 3 7 7" />
    </svg>
  ),
  class: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-5 9 5-9 5-9-5z" />
      <path d="M7 11v5c0 1.7 2.2 3 5 3s5-1.3 5-3v-5" />
    </svg>
  ),
  draft: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3.5l2.5 5 5.5.8-4 3.9.95 5.5L12 16.9l-4.9 2.6.95-5.5-4-3.9 5.5-.8L12 3.5z" />
    </svg>
  ),
};
function iconFor(crit) {
  if (crit.type === "school") return null;
  return TYPE_ICONS[crit.type] || null;
}

// Display names per mode (internal keys stay easy/medium/hard).
const MODE_LABELS = { easy: "Easy", medium: "Medium", hard: "Rothstein" };

// Accent-insensitive, lowercase key for search (é→e, č→c, ü→u, …).
const normName = (s) =>
  (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

// ----- COMPONENT ----------------------------------------------------------

export default function OneShiningGrid() {
  // Recomputed every render — cheap, and lets the displayed date label roll
  // over if someone keeps the tab open past midnight. The puzzle itself is
  // pinned by the day number baked into daily_grid.json at build time.
  const today = new Date();

  // ----- DATA LOAD ----------------------------------------------------
  // Two small fetches on mount. player_index drives the search picker;
  // daily_grid is the puzzle itself, refreshed daily by re-running
  // build_game_data.py server-side.
  const [playerIndex, setPlayerIndex] = useState(null);
  const [grid, setGrid] = useState(null);
  const [loadError, setLoadError] = useState(null);

  // Tester preview: with ?test in the URL, load test_grids.json (several grids
  // per mode) instead of the single daily puzzle. The live site is unaffected.
  const isTest = useMemo(
    () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("test"),
    []
  );

  useEffect(() => {
    let cancelled = false;
    const gridUrl = isTest ? "/test_grids.json" : "/daily_grid.json";
    Promise.all([
      fetch("/player_index.json").then(r => { if (!r.ok) throw new Error(`player_index: HTTP ${r.status}`); return r.json(); }),
      fetch(gridUrl).then(r => { if (!r.ok) throw new Error(`${gridUrl}: HTTP ${r.status}`); return r.json(); }),
    ])
      .then(([idx, g]) => { if (!cancelled) { setPlayerIndex(idx); setGrid(g); } })
      .catch(err => { if (!cancelled) setLoadError(err.message); });
    return () => { cancelled = true; };
  }, [isTest]);

  // ----- GAME STATE ---------------------------------------------------
  const [cells, setCells] = useState(Array(9).fill(null));
  const [guessesLeft, setGuessesLeft] = useState(9);
  const [activeIdx, setActiveIdx] = useState(null);
  const [showShare, setShowShare] = useState(false);
  const [showHow, setShowHow] = useState(false);
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState("");
  const [mode, setMode] = useState("easy");
  const [puzzleIdx, setPuzzleIdx] = useState(0);   // which grid within a mode (test preview)
  const searchRef = useRef(null);

  const correctCount = cells.filter(c => c && c.correct).length;
  const totalRarity = cells.reduce((s, c) => s + (c && c.correct ? c.rarity : 0), 0);
  const gameOver = guessesLeft <= 0 || cells.every(c => c);

  useEffect(() => {
    if (activeIdx !== null) {
      setQuery("");
      setTimeout(() => searchRef.current?.focus(), 30);
    }
  }, [activeIdx]);

  // Switching difficulty OR test-puzzle starts a fresh board.
  useEffect(() => {
    setCells(Array(9).fill(null));
    setGuessesLeft(9);
    setActiveIdx(null);
    setShowShare(false);
  }, [mode, puzzleIdx]);

  function submit(pick) {
    setCells(prev => {
      const next = [...prev];
      next[activeIdx] = pick;
      return next;
    });
    setGuessesLeft(g => g - 1);
    setActiveIdx(null);
  }

  useEffect(() => {
    if (gameOver && cells.some(c => c)) {
      const t = setTimeout(() => setShowShare(true), 350);
      return () => clearTimeout(t);
    }
  }, [gameOver, cells]);

  // Build a normalized search index once (accent-insensitive name + name parts).
  const searchIndex = useMemo(() => {
    if (!playerIndex) return [];
    return playerIndex.players.map(p => {
      const n = normName(p.name);
      const parts = n.split(/\s+/);
      return { p, n, first: parts[0] || "", last: parts[parts.length - 1] || "", parts };
    });
  }, [playerIndex]);

  // Player picker — relevance-ranked: exact name/word > first|last prefix >
  // any-token prefix > whole-name prefix > mid-word substring (e.g. "Glover"
  // for "love"). Sort by score, then alphabetical, then cap at 50 — so weak
  // mid-word hits drop off once there are enough better matches.
  const filteredPlayers = useMemo(() => {
    if (!searchIndex.length) return [];
    const q = normName(query);
    if (!q) return searchIndex.slice(0, 50).map(e => e.p);
    const scored = [];
    for (const e of searchIndex) {
      const idx = e.n.indexOf(q);
      if (idx === -1) continue;                                          // no match
      let score;
      if (e.n === q || e.first === q || e.last === q) score = 0;         // exact full/first/last
      else if (e.last.startsWith(q) || e.first.startsWith(q)) score = 1; // first|last prefix
      else if (e.parts.some(t => t.startsWith(q))) score = 2;            // any-token prefix
      else if (idx === 0) score = 3;                                     // whole-name prefix
      else score = 4;                                                    // mid-word substring
      scored.push({ p: e.p, score });
    }
    scored.sort((a, b) => a.score - b.score || a.p.name.localeCompare(b.p.name));
    return scored.slice(0, 50).map(x => x.p);
  }, [query, searchIndex]);

  // Each player may fill only ONE cell per board (right or wrong) — collect the
  // slugs already placed so the picker can disable them.
  const usedSlugs = useMemo(
    () => new Set(cells.filter(Boolean).map(c => c.slug)),
    [cells]
  );

  function shareString() {
    let g = "";
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        const cell = cells[r * 3 + c];
        g += cell && cell.correct ? "🟩" : "⬜";
      }
      g += "\n";
    }
    const md = grid.modes[mode];
    const pz = Array.isArray(md) ? ` · Puzzle ${Math.min(puzzleIdx, md.length - 1) + 1}` : "";
    return `One Shining Grid #${grid.day} · ${MODE_LABELS[mode].toUpperCase()}${pz}\n${correctCount}/9 · Rarity ${totalRarity}\n${g}cbb-grid.example`;
  }

  async function copyShare() {
    const text = shareString();
    try { await navigator.clipboard.writeText(text); }
    catch {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); ta.remove();
    }
    setToast("COPIED TO CLIPBOARD");
    setTimeout(() => setToast(""), 1400);
  }

  // ----- LOADING / ERROR STATES ---------------------------------------
  if (loadError) {
    return (
      <div className="min-h-screen w-full bg-amber-50 text-slate-900 flex items-center justify-center px-6">
        <div className="max-w-md text-center">
          <h1 className="font-serif font-black text-3xl mb-3">Couldn't load game data</h1>
          <p className="text-sm text-slate-600 mb-2">Tried to fetch from <code>/</code> and got: {loadError}</p>
          <p className="text-xs text-slate-500">Run <code>python3 build_game_data.py</code> to produce <code>public/player_index.json</code> and <code>public/daily_grid.json</code>, then serve via Vite (<code>npm run dev</code>).</p>
        </div>
      </div>
    );
  }
  if (!playerIndex || !grid) {
    return (
      <div className="min-h-screen w-full bg-amber-50 text-slate-900 flex items-center justify-center">
        <div className="font-serif italic text-slate-500">Loading the box scores…</div>
      </div>
    );
  }
  // A mode is either a single grid (daily) or an array of grids (?test preview).
  const modeData = grid.modes[mode];
  const isMulti = Array.isArray(modeData);
  const puzzles = isMulti ? modeData : [modeData];
  const safeIdx = Math.min(puzzleIdx, puzzles.length - 1);
  const active = puzzles[safeIdx];
  const { rows, cols } = active;

  // ---------- RENDER --------------------------------------------------

  return (
    <div className="min-h-screen w-full bg-amber-50 text-slate-900 font-sans relative overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-amber-100/40 via-transparent to-amber-200/40" />

      <div className="relative max-w-2xl mx-auto px-3 sm:px-5 py-8 pb-24">

        {/* MASTHEAD */}
        <header className="text-center border-y-4 border-double border-slate-900 py-4 mb-6">
          <div className="text-[11px] tracking-[0.32em] text-slate-600 font-semibold uppercase">
            A Daily College Hoops Puzzle
          </div>
          <h1 className="font-serif font-black text-4xl sm:text-5xl my-1 leading-none">
            One Shining Grid
          </h1>
          <div className="text-xs tracking-[0.25em] text-amber-800 mt-1">● ● ● ● ●</div>
          <div className="mt-2 flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-slate-600">
            <span>Edition <b className="text-slate-900">#{grid.day}</b></span>
            <span><b className="text-slate-900">{today.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</b></span>
            <span>Season pool: <b>{playerIndex.meta.seasons[0]} – {playerIndex.meta.seasons[playerIndex.meta.seasons.length - 1]}</b></span>
          </div>
        </header>

        {/* MODE SELECTOR */}
        <div className="flex justify-center gap-2 mb-4">
          {["easy", "medium", "hard"].map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setPuzzleIdx(0); }}
              className={`px-4 py-1.5 text-xs tracking-[0.18em] font-bold rounded border-2 border-slate-900 transition ${
                mode === m
                  ? "bg-slate-900 text-amber-50 shadow-[3px_3px_0_#92400e]"
                  : "bg-amber-100/70 text-slate-900 hover:bg-amber-200"
              }`}>
              {MODE_LABELS[m].toUpperCase()}
            </button>
          ))}
        </div>

        {/* PUZZLE SELECTOR — only in ?test preview (modes hold an array of grids) */}
        {isMulti && (
          <div className="flex justify-center items-center flex-wrap gap-1.5 mb-4">
            <span className="text-[10px] tracking-[0.18em] text-amber-800 font-bold mr-1">TEST · PUZZLE</span>
            {puzzles.map((_, k) => (
              <button
                key={k}
                onClick={() => setPuzzleIdx(k)}
                className={`w-7 h-7 text-xs font-bold rounded border-2 border-slate-900 transition ${
                  k === safeIdx
                    ? "bg-slate-900 text-amber-50 shadow-[2px_2px_0_#92400e]"
                    : "bg-amber-100/70 text-slate-900 hover:bg-amber-200"
                }`}>
                {k + 1}
              </button>
            ))}
          </div>
        )}

        {/* TOP BAR */}
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="inline-flex items-center gap-2 bg-amber-100/80 border-2 border-slate-900 rounded px-3 py-2 shadow-[3px_3px_0_#0f172a]">
            <span className="text-[11px] tracking-[0.18em] text-slate-600 font-bold">GUESSES</span>
            <span className="flex gap-1">
              {Array.from({ length: 9 }).map((_, i) => (
                <span key={i}
                  className={`w-2.5 h-2.5 rounded-full border border-slate-900 ${i < guessesLeft ? "bg-amber-700" : "bg-transparent"}`} />
              ))}
            </span>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowHow(true)}
              className="px-3 py-2 text-sm tracking-widest font-bold bg-transparent border-2 border-slate-900 rounded shadow-[3px_3px_0_#0f172a] hover:-translate-x-px hover:-translate-y-px transition">
              HOW TO PLAY
            </button>
            <button onClick={() => setShowShare(true)} disabled={!gameOver}
              className="px-3 py-2 text-sm tracking-widest font-bold bg-slate-900 text-amber-50 rounded border-2 border-slate-900 shadow-[3px_3px_0_#92400e] hover:-translate-x-px hover:-translate-y-px transition disabled:opacity-40 disabled:cursor-not-allowed">
              SHARE
            </button>
          </div>
        </div>

        {/* GRID */}
        <div className="bg-amber-100/60 border-2 border-slate-900 rounded-md p-2 sm:p-3 shadow-[6px_6px_0_#0f172a] relative">
          <div className="absolute -left-0.5 -right-0.5 -top-0.5 h-2 rounded-t-md"
            style={{ backgroundImage: "repeating-linear-gradient(90deg,#b45309 0 18px,#7c2d12 18px 20px)" }} />
          <div className="grid gap-1.5 mt-1"
            style={{ gridTemplateColumns: "84px minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr)", gridTemplateRows: "84px 1fr 1fr 1fr" }}>
            <div className="flex items-center justify-center text-xs italic font-serif text-slate-500 text-center">
              row<br/>×<br/>col
            </div>
            {cols.map((c, i) => <AxisHead key={`c${i}`} crit={c} />)}
            {rows.map((r, ri) => (
              <RowGroup key={`r${ri}`} crit={r} ri={ri} cols={cols} cells={cells} onPick={setActiveIdx} />
            ))}
          </div>
        </div>

        {/* SCORE STRIP */}
        <div className="grid grid-cols-3 gap-2 mt-4">
          <Stat label="Filled" value={`${correctCount}/9`} />
          <Stat label="Rarity" value={cells.some(c => c) ? totalRarity : "—"} />
          <Stat label="Streak" value={"—"} />
        </div>

        <footer className="mt-6 text-center text-xs text-slate-500">
          {playerIndex.meta.player_count.toLocaleString()} players · {playerIndex.meta.school_count} schools
        </footer>
      </div>

      {/* PICKER MODAL */}
      {activeIdx !== null && (
        <Scrim onClose={() => setActiveIdx(null)}>
          <h2 className="font-serif font-black text-2xl">Name a Player</h2>
          <p className="text-sm text-slate-600 mt-1 mb-3">
            Must satisfy <b className="text-slate-900">{rows[Math.floor(activeIdx / 3)].label}</b>
            <span className="mx-1">AND</span>
            <b className="text-slate-900">{cols[activeIdx % 3].label}</b>.
          </p>
          <input
            ref={searchRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Type a player name…"
            className="w-full px-3 py-2 border-2 border-slate-900 rounded bg-amber-50 text-base focus:outline-none focus:ring-2 focus:ring-amber-600"
          />
          <div className="max-h-64 overflow-auto mt-3">
            {filteredPlayers.length === 0 ? (
              <div className="p-4 text-center text-slate-500 italic text-sm">
                No players found.
              </div>
            ) : filteredPlayers.map(p => {
              const used = usedSlugs.has(p.slug);   // already placed on the board
              return (
                <button
                  key={p.slug}
                  disabled={used}
                  onClick={() => {
                    if (used) return;               // a player can only be used once per board
                    // Server-precomputed yes/no: is this slug in the valid set for the active cell?
                    const validSet = active.valid_per_cell[activeIdx] || [];
                    const correct = validSet.includes(p.slug);
                    submit({
                      slug: p.slug, name: p.name, team: p.team, correct,
                      rarity: correct ? Math.floor(8 + Math.random() * 70) : 0,
                    });
                  }}
                  className={`w-full flex justify-between items-center text-left px-3 py-2 border-b border-dashed border-slate-300 ${
                    used ? "opacity-40 cursor-not-allowed" : "hover:bg-amber-100"
                  }`}>
                  <div>
                    <div className="font-serif font-bold text-base">{p.name}</div>
                    <div className="text-[11px] tracking-widest text-slate-500">{p.season}</div>
                  </div>
                  <div className="text-[11px] tracking-widest text-slate-500">{used ? "USED" : "PICK ▸"}</div>
                </button>
              );
            })}
          </div>
        </Scrim>
      )}

      {/* SHARE MODAL */}
      {showShare && (
        <Scrim onClose={() => setShowShare(false)}>
          <h2 className="font-serif font-black text-2xl">Your Grid</h2>
          <p className="text-sm text-slate-600 mt-1 mb-3">Copy & paste anywhere — no images needed.</p>
          <pre className="bg-amber-50 border-2 border-slate-900 rounded p-3 text-sm text-center whitespace-pre font-mono leading-relaxed">{shareString()}</pre>
          <div className="flex gap-2 mt-4">
            <button onClick={copyShare}
              className="flex-1 px-3 py-2 text-sm tracking-widest font-bold bg-slate-900 text-amber-50 rounded border-2 border-slate-900 shadow-[3px_3px_0_#92400e]">
              COPY RESULT
            </button>
            <button onClick={() => setShowShare(false)}
              className="flex-1 px-3 py-2 text-sm tracking-widest font-bold bg-transparent border-2 border-slate-900 rounded shadow-[3px_3px_0_#0f172a]">
              CLOSE
            </button>
          </div>
        </Scrim>
      )}

      {/* HOW TO PLAY */}
      {showHow && (
        <Scrim onClose={() => setShowHow(false)}>
          <h2 className="font-serif font-black text-2xl">How to Play</h2>
          <p className="text-sm text-slate-600 mt-1 mb-3">
            Name a college basketball player whose season satisfies <b>both</b> the row school and the column stat for each cell.
            You get <b>9 guesses total</b>, one per cell. Rarer correct picks score lower (better) — like golf.
          </p>
          <div className="text-sm leading-relaxed">
            <b>Notes for this season:</b><br/>
            · Per-game thresholds require at least {grid.meta.min_games_for_average} games played.<br/>
            · Shooting % criteria require minimum volume: {grid.meta.min_fga_for_pct} FGA, {grid.meta.min_3pa_for_pct} 3PA, {grid.meta.min_fta_for_pct} FTA.
          </div>
        </Scrim>
      )}

      {/* TOAST */}
      {toast && (
        <div className="fixed bottom-8 left-1/2 -translate-x-1/2 bg-slate-900 text-amber-50 px-5 py-2.5 rounded tracking-widest font-bold shadow-[3px_3px_0_#92400e] z-50">
          {toast}
        </div>
      )}
    </div>
  );
}

// ----- SUBCOMPONENTS ------------------------------------------------------

// School/conf pennant labels live in a fixed 84px column (~56px usable text width, ~53px
// after a small margin). Long single words ("Massachusetts") can't break at a space, and
// multi-word names overflow on their longest word. FitLabel lays the name out on as few
// lines as possible, then condenses (squeezes glyphs, full height) only the lines that are
// too wide — so every name fits: no clipping, no mid-word wrap, no abbreviation. Short names
// render normally. Line-break decisions use the same font as the SVG so they always agree,
// and condensing guarantees the fit regardless of exact metrics.
const FIT_USABLE = 53; // target px width per line inside the pennant
const FIT_MAXLINE = 85; // a line may grow to here, then condenses down to ~0.62x
const _fitCtx =
  typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
function _fitMeasure(s) {
  if (!_fitCtx) return (s ? s.length : 0) * 6.6;
  _fitCtx.font = "italic 800 12px Georgia, ui-serif, serif";
  return _fitCtx.measureText(s).width;
}
function _fitSegments(text) {
  // split on spaces; also break after an en-dash/hyphen, keeping the dash on the left piece
  const segs = [];
  (text || "")
    .split(/\s+/)
    .filter(Boolean)
    .forEach((word, wi) => {
      let cur = "";
      const pieces = [];
      for (const ch of word) {
        cur += ch;
        if (ch === "–" || ch === "-") {
          pieces.push(cur);
          cur = "";
        }
      }
      if (cur) pieces.push(cur);
      pieces.forEach((p, pi) => segs.push({ s: p, space: pi === 0 && wi > 0 }));
    });
  return segs;
}
function _fitWrap(text) {
  const segs = _fitSegments(text);
  const lines = [];
  let cur = "";
  for (const seg of segs) {
    const trial = cur + (cur && seg.space ? " " : "") + seg.s;
    if (cur && _fitMeasure(trial) > FIT_MAXLINE) {
      lines.push(cur);
      cur = seg.s;
    } else {
      cur = trial;
    }
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [""];
}
function FitLabel({ text, fg }) {
  const W = 56;
  const lh = 13;
  const lines = _fitWrap(text);
  const H = lines.length * lh;
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      style={{ display: "block", overflow: "visible" }}
      aria-label={text}
    >
      {lines.map((ln, i) => {
        const condense = _fitMeasure(ln) > FIT_USABLE;
        return (
          <text
            key={i}
            x={W / 2}
            y={i * lh + 10.5}
            textAnchor="middle"
            {...(condense ? { textLength: FIT_USABLE, lengthAdjust: "spacingAndGlyphs" } : {})}
            fontFamily="Georgia, ui-serif, serif"
            fontWeight="800"
            fontStyle="italic"
            fontSize="12"
            fill={fg}
          >
            {ln}
          </text>
        );
      })}
    </svg>
  );
}

function AxisHead({ crit }) {
  const isSchool = crit.type === "school" || crit.type === "conf";
  const icon = iconFor(crit);
  const bg = crit.bg || "#0f172a";
  const accent = crit.accent || "#fbbf24";
  const fg = crit.fg || "#fef3c7";
  const wrapStyle = isSchool
    ? {
        background: bg,
        color: fg,
        borderLeft: `4px solid ${accent}`,
        clipPath: "polygon(0 0, 100% 0, 86% 50%, 100% 100%, 0 100%)",
      }
    : undefined;
  return (
    <div
      className={`rounded flex flex-col items-center justify-center text-center p-2 relative overflow-hidden ${
        isSchool ? "pr-4" : "bg-slate-900 text-amber-50"
      }`}
      style={wrapStyle}
    >
      {!isSchool && (
        <div className="absolute inset-1 border border-dashed border-amber-200/30 rounded pointer-events-none" />
      )}
      {isSchool && (
        <span
          className="absolute top-1.5 left-0.5 w-1 h-1 rounded-full"
          style={{ background: accent }}
          aria-hidden="true"
        />
      )}
      {icon && <div className="text-amber-300 leading-none mb-1">{icon}</div>}
      <div
        className="text-[9px] tracking-[0.22em] mt-0.5"
        style={isSchool ? { color: accent } : undefined}
      >
        {crit.kicker}
      </div>
      <div
        className={`font-serif font-bold leading-tight mt-0.5 ${isSchool ? "italic text-xs" : "text-xs sm:text-sm"}`}
        style={isSchool ? { color: fg } : undefined}
      >
        {isSchool ? <FitLabel text={crit.label} fg={fg} /> : crit.label}
      </div>
    </div>
  );
}

function RowGroup({ crit, ri, cols, cells, onPick }) {
  return (
    <>
      <AxisHead crit={crit} />
      {cols.map((_, ci) => {
        const idx = ri * 3 + ci;
        const c = cells[idx];
        const filled = !!c;
        return (
          <button
            key={idx}
            disabled={filled}
            onClick={() => !filled && onPick(idx)}
            className={`relative min-w-0 h-[92px] overflow-hidden rounded border-2 border-slate-900 p-1.5 sm:p-2 flex items-center justify-center text-center transition
              ${filled
                ? (c.correct ? "bg-green-200" : "bg-rose-100")
                : "bg-amber-200/70 hover:bg-amber-200 hover:-translate-y-px cursor-pointer"}`}>
            {filled ? (
              <div className="min-w-0 w-full break-words">
                <div className={`absolute top-1 left-2 text-[10px] tracking-widest font-bold ${c.correct ? "text-green-800" : "text-rose-800"}`}>
                  {c.correct ? "✓ MATCH" : "✗ MISS"}
                </div>
                <div className="font-serif font-bold text-xs sm:text-sm leading-tight">{c.name}</div>
                <div className="text-[10px] tracking-widest text-slate-600 mt-1 uppercase">{c.team}</div>
                {c.correct && (
                  <div className="absolute bottom-1 right-2 text-[10px] tracking-wider text-amber-800 font-bold">
                    {c.rarity}% picked
                  </div>
                )}
              </div>
            ) : (
              <span className="text-3xl font-light text-slate-400">+</span>
            )}
          </button>
        );
      })}
    </>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-amber-100/70 border-2 border-slate-900 rounded p-2 text-center">
      <div className="text-[10px] tracking-[0.22em] text-slate-500 font-bold">{label.toUpperCase()}</div>
      <div className="font-serif font-black text-2xl text-slate-900 leading-tight">{value}</div>
    </div>
  );
}

function Scrim({ onClose, children }) {
  return (
    <div
      onClick={onClose}
      className="fixed inset-0 bg-slate-900/60 flex items-center justify-center p-5 z-40">
      <div
        onClick={e => e.stopPropagation()}
        className="bg-amber-50 border-2 border-slate-900 rounded-md shadow-[8px_8px_0_#0f172a] w-full max-w-md p-5 relative">
        <button
          onClick={onClose}
          className="absolute top-2 right-3 text-2xl text-slate-900 hover:text-slate-600">×</button>
        {children}
      </div>
    </div>
  );
}
