# Handoff: NexusAI — AI Financial Advisor & Stock Picker

## Overview
NexusAI is a personal investing dashboard that replaces a cold Streamlit prototype with a warm, "Apple-like" web app. It has five connected sections:

1. **Overview** — net-worth tracking over time, editable accounts, allocation donut, top movers, sector breakdown
2. **Analyze** — single-stock deep dive with an AI BUY/HOLD/SELL verdict, price + moving-average chart, fundamentals, risks, catalysts, news
3. **Portfolio** — all 44 holdings with P/L, weights, sparklines, plus risk metrics & concentration
4. **Watchlist** — tracked tickers with buy/sell price targets and alert status, plus a news feed
5. **Advisor** — an AI-generated allocation plan (current vs target), prioritized action items, suggested tickers, risks, and a live chat surface

The signature features the user cares about: **net-worth growth over time** (Overview hero chart with range toggle) and **updating account balances** (add / edit / remove accounts on the Overview tab, with net worth recomputing live).

## About the Design Files
The files in `design/` are a **design reference created in HTML/CSS/vanilla JS** — a working prototype that demonstrates the intended look, layout, and interactions. **They are not meant to be shipped as-is.** The task is to **recreate these designs inside the target codebase** (the existing app this replaces is a Python/Streamlit app — see "Backend context" below), using that environment's established framework and patterns. If a fresh front-end is being stood up, React (with a charting lib like Recharts/visx, or keeping the hand-rolled SVG approach) is a natural fit, but any framework can reproduce this faithfully.

The prototype uses **mock/synthetic data** (`data.js`) derived from the user's real holdings. In production this data comes from the existing Python services (see below).

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, radii, shadows, and interaction states are all specified and should be reproduced pixel-faithfully. Exact tokens are in `design/styles.css` (`:root` and `[data-theme="dark"]`) and summarized under **Design Tokens**.

## Backend context (existing code being replaced)
The original app is Streamlit. The deterministic logic and AI advisory already exist in Python and should be reused as the API layer behind this UI:
- `advisory.py` — deterministic technical signal + numeric score (RSI thresholds etc.)
- `analyst.py` — AI advisor: Ollama (local) → Anthropic fallback → rule-based. Produces the verdict, thesis, technical/fundamental/news breakdowns, and the chat responses.
- `portfolio.json` / `combined_holdings.csv` — holdings (ticker, shares, avg_cost)
- `profile.json` — risk tolerance, horizon, goals, age

The front-end should call these (wrapped in a REST/JSON API) rather than reimplementing them. Every AI string in the prototype (verdict thesis, advisor plan `fit`, action items, chat replies) is a **placeholder** for `analyst.py` output.

## Global Layout & Shell
- **Two-column app shell**: fixed 240px left sidebar + scrollable main column. Grid: `grid-template-columns: 240px 1fr; height: 100vh`.
- **Sidebar**: brand mark (gradient rounded square) + "NexusAI" wordmark; nav list grouped under "INVESTING" and "AI" eyebrow labels; bottom area has a light/dark segmented toggle and a profile chip (avatar + name + "Aggressive · 30yr horizon").
- **Main**: sticky top bar (section title on the left, a ⌘K search trigger, bell & settings icon buttons) above a scrolling content area (`max-width: 1400px`, padding `28px 32px 60px`).
- **Section switching** is client-side: all five sections are rendered once into `#section-*` containers; nav toggles a single `.active` class (`display:none`/`block`). In a SPA this maps to routes/tabs.
- **Background**: subtle multi-radial mesh gradient behind everything (very low-saturation blue/pink/lavander). Cards are solid surfaces (NOT translucent — translucency was intentionally removed because it rendered poorly; keep cards opaque with soft shadows for the "glass-adjacent" feel).
- **Responsive**: breakpoints at 1100px (overview/analyze 2-col → 1-col), 900px (all multi-col grids → 1-col), 820px (sidebar collapses to a 64px icon rail; labels hidden).

## Screens / Views

### 1. Overview
**Purpose:** See total net worth, how it's grown, and manage accounts.
**Layout:** Two-column grid (`2fr 1fr`) — left = Net Worth hero card; right = Allocation donut card. Below: a 2-col grid of Accounts + Movers, then a full-width Sector breakdown card.
**Components:**
- **Net Worth hero** (`.hero`): eyebrow "NET WORTH · ALL ACCOUNTS" (11px, uppercase, letter-spacing .06em, muted); value is huge — `56px / 700 / -0.035em`, tabular-nums, with a `28px` muted cents suffix on its own baseline. Below: a delta row — green pill "▲ +$147.1K all-time" (`--green-soft` bg, `--green` text, pill radius 999px) + "YTD +4.4%". Then a range pill group `1M 3M 6M YTD 1Y 2Y ALL` (segmented, active = solid surface w/ shadow). Then a 220px-tall **area chart** (smooth monotone cubic, gradient fill from `--accent` @ 0.32 alpha → 0, 2.2px stroke, dashed gridlines, hover crosshair with a floating tooltip showing value + date).
- **Allocation donut** (right): title "Allocation / By account type", a 200px donut (20px stroke) with center label "NET WORTH" + compact value, and a legend listing each account with a color dot and % of net worth.
- **Accounts card**: header "Accounts" + ghost "+ Add account" button. Rows: 38px rounded-square colored icon (per type: taxable=blue, retirement=green, cash=amber, crypto=purple gradient), name + "institution · type" meta, right-aligned balance + "Updated today", and two icon buttons (edit pencil / trash). **Edit** swaps the balance for an inline number input (Enter commits, Esc cancels). **Add** prepends an inline form (name, institution, type select, balance). **Remove** fades the row out (220ms) then deletes. Every change recomputes net worth + repaints hero + donut.
- **Movers card**: "Top 3 each" — Gainers then Losers, each row = ticker glyph, ticker + sector, a 60×18 sparkline, and a colored % delta pill.
- **Sector breakdown**: up to 8 rows, each = sector name, animated horizontal bar (fills on load, color per sector), right % value.

### 2. Analyze
**Purpose:** Deep-dive one stock with an AI verdict.
**Layout:** `2fr 1fr` grid. Left column = verdict banner, price chart, risks/catalysts (2-col), analyst breakdown. Right column = 4 stat tiles (2×2), Fundamentals list, News list.
**Components:**
- **Verdict banner** (`.verdict.buy/.sell/.hold`): colored left-to-right tint overlay (green for buy). Top row: bold pill "BUY" (solid `--green`, white text), "CONFIDENCE · MEDIUM", "✦ Claude advisor". Ticker `26px/700`, name muted. Meta row: price (bold), green % pill, "Analyst target $275.00 (6.5% upside)". Thesis paragraph (14px, line-height 1.55) separated by a top border.
- **Price chart card**: header has title + a **color-coded legend** (Price = solid `--accent`, SMA 50 = dashed `#ff9f0a`, SMA 200 = dashed `#b14aff`) + a range pill group. 280px multi-line chart: filled gradient area under the close line + two dashed MA lines.
- **Risks / Catalysts**: two cards; risk items have an amber alert icon, catalyst items a green check on a green-tinted row.
- **Analyst breakdown**: three labeled blocks (TECHNICAL / FUNDAMENTAL / NEWS), each an uppercase accent micro-label + body copy.
- **Stat tiles** (right): Market Cap, P/E (FWD), Beta, Div Yield — label + `22px/700` value.
- **Fundamentals**: key/value rows (Sector, Industry, P/E trailing, 52w high/low, Annual div, Street rating, Next earnings).
- **News**: ticker tag chip + headline + "source · time".

### 3. Portfolio
**Purpose:** Full holdings ledger + risk.
**Layout:** 3 stat tiles (Total value, Cost basis, Unrealized P/L), then a full-width Holdings table, then a 2-col grid (Risk metrics, Concentration).
**Components:**
- **Holdings table** (`.tbl`): columns Ticker (glyph + ticker + sector), Account, Shares (4dp), Avg cost, Price, Value, Weight %, P/L (% bold + compact $ underneath, green/red), Trend (64×18 sparkline). Sticky header, row hover tint. Rows carry `data-row-ticker` for deep-linking from search.
- **Risk metrics**: 3 mini stat tiles (Sharpe 1.28, Max drawdown −18.4%, Sortino 1.82) + explanatory copy.
- **Concentration**: top-6 weight bars (bar color escalates: >7% red, >4% amber, else accent) + an amber callout.

### 4. Watchlist
**Purpose:** Track candidates with price targets + alerts.
**Layout:** 3 stat tiles (Watching, Alerts triggered, Avg time held), full-width Watchlist card, full-width news card.
**Components:**
- **Watchlist rows** (grid `1.4fr 1fr 1.4fr 1fr`, `data-row-ticker`): ticker glyph + ticker + note; price + change pill; target pills ("BUY ≤ $x", "SELL ≥ $x") + distance %; status with a colored dot ("BUY target hit" green / "SELL target hit" red / "Monitoring" amber). NB: data is tuned so exactly one ticker (VNQ) is below its buy target → matches the "1 alert triggered" stat.

### 5. Advisor
**Purpose:** The AI plan + conversation.
**Layout:** `1.5fr 1fr` grid. Left = profile chip, "PLAN GENERATED" fit summary, target allocation, action items, suggested tickers, risks. Right = a sticky chat panel (520px).
**Components:**
- **Target allocation rows**: category, a current-fill bar with a black target tick mark, gap % (green if under-target = buy, amber if over), and an action chip (Buy/Trim/Hold).
- **Action items**: numbered priority chip, action tag (buy/trim/hold/sell), ticker, description, reason, and a contextual button ("Set buy alert" / "Set sell alert" / "Mark done").
- **Suggested tickers**: 2-col cards (ticker, category · target %, rationale, + button).
- **Chat panel**: assistant/user bubbles (assistant = neutral surface, left-aligned, "✦ Claude" source; user = solid accent, right-aligned). Input + send button. Typing sends a bubble and, after ~700ms, appends a canned assistant reply — **replace with streaming `analyst.py` output**.

## Interactions & Behavior
- **Navigation**: sidebar items + ⌘K palette + ticker deep-links all route through one `navigateTo(section)` function. Switching re-runs that section's chart hydration.
- **⌘K Command palette** (`command.js`): opens on ⌘K/Ctrl+K or clicking the top-bar search; fuzzy/prefix filter over Sections, Tickers (holdings + watchlist), and Accounts; ↑/↓ to move, Enter/click to select, Esc/backdrop to close. Selecting a ticker navigates to Portfolio (or Watchlist) and **flashes the matching row** (`.row-flash`, 1.6s accent pulse). Backdrop uses blur.
- **Account editing**: inline edit/add/remove as described; net worth, hero number, donut, legend, and the palette index all update live.
- **Tweaks panel** (`tweaks.js`): a small floating panel (toggled by the host toolbar via postMessage protocol — see note) with **Accent** (5 swatches; accent shade adapts to light/dark), **Density** (compact/regular/comfy → adjusts paddings & gaps), **Theme** (light/dark, synced with the sidebar toggle). Persists to `localStorage` (`nexus_tweaks_v1`). In a real app, expose these as user Settings; the postMessage host protocol can be dropped.
- **Charts**: hand-rolled SVG (`charts.js`) — area, multi-line, donut, sparkline. They read CSS variables at draw time, so they're **redrawn on theme/accent change and on window resize** (debounced 160ms). Area chart has a mousemove crosshair + tooltip.
- **Theme**: `data-theme="light|dark"` on `<body>`; all colors are CSS variables that swap. **Density**: `data-density="compact|regular|comfy"`.
- **Animations**: bars fill via width transition (`0.8s cubic-bezier(0.2,0.8,0.2,1)`); section fade-in; account row removal fade/slide; palette + tweaks panel scale/opacity in.

## State Management
- `activeSection` (which tab).
- `accounts[]` (mutable: balance edits, adds, removes) → derived `netWorth`.
- `tweaks` = `{ accent, density, theme }` persisted to localStorage.
- Per-chart `currentRange` (Overview net-worth range toggle).
- Chat message list (append-only).
- **Data fetching (production)**: holdings + profile from the portfolio service; per-ticker analysis, the advisor plan, and chat replies from `analyst.py`; quotes/news from whatever market-data provider the backend uses. Everything in `data.js` is the shape the UI expects — treat it as the API contract.

## Design Tokens
Source of truth: `design/styles.css`. Light theme `:root`, dark theme `[data-theme="dark"]`.

**Colors — Light**
- bg `#e4e4e9`; mesh accents `#d6dae2 / #e8d8de / #d2dde9`
- surface `#ffffff`; surface-2 `#f1f1f4`; surface-soft `rgba(252,252,253,.85)`
- border `rgba(0,0,0,.10)`; border-strong `rgba(0,0,0,.16)`
- text `#1d1d1f`; text-2 `#6e6e73`; text-3 `#a1a1a6`
- accent `#0066ff` (+ accent-soft `rgba(0,102,255,.10)`)
- green `#00a96e` / green-soft `rgba(0,169,110,.12)`
- red `#e84a4a` / red-soft `rgba(232,74,74,.12)`
- amber `#ff9f0a` / amber-soft `rgba(255,159,10,.12)`

**Colors — Dark**
- bg `#000000`; mesh `#0c0c10 / #160a12 / #08121f`
- surface `#1c1c1e`; surface-2 `#2c2c2e`
- border `rgba(255,255,255,.10)`; border-strong `rgba(255,255,255,.18)`
- text `#f5f5f7`; text-2 `#98989d`; text-3 `#6c6c70`
- accent `#0a84ff`; green `#30d158`; red `#ff453a`; amber `#ffd60a`

**Accent options (Tweaks)** — light / dark pairs: Blue `#0066ff`/`#0a84ff`, Purple `#8b5cf6`/`#a78bfa`, Green `#00a96e`/`#30d158`, Amber `#f5810a`/`#ff9f0a`, Pink `#f5396b`/`#ff476f`.

**Radii**: sm 10 / md 14 / lg 20 / xl 28 (px). **Pills**: 999px.
**Shadows**: card = `0 1px 2px rgba(0,0,0,.06), 0 6px 20px rgba(0,0,0,.08), 0 18px 50px rgba(0,0,0,.08)`; pop (palette/tweaks/tooltip) = `0 4px 12px rgba(0,0,0,.10), 0 16px 48px rgba(0,0,0,.14)`.
**Spacing**: grid gaps 16px (regular), 12 (compact), 22 (comfy); content padding `28px 32px`.

**Typography**
- Family: system `-apple-system, BlinkMacSystemFont, "SF Pro Display", Inter, system-ui` for UI; `"JetBrains Mono"` available for monospace; tabular-nums on all numbers (`font-feature-settings: "tnum"`).
- Hero net worth `56px/700/-0.035em`; section title `22px/700`; card title `15px/600`; stat-tile value `22px/700`; body `13–14px`; eyebrows/labels `10–11px uppercase, letter-spacing .06–.08em, 600`.

## Assets
- **Icons**: inline SVG, Lucide-style, defined in `design/icons.js` via `Icon(name, size)`. No external icon dependency — in React, swap for `lucide-react` (same icon names/shapes: home, chart→line-chart, wallet, eye, sparkles, search, bell, settings, sun, moon, trending-up, plus, edit, trash, send, target, alert-triangle, check, bank→landmark, coin→circle-dollar, x, sliders, corner-down-left).
- **Brand mark**: pure CSS gradient rounded square (no image).
- **Fonts**: Google Fonts — Inter (400/500/600/700) + JetBrains Mono. The print report also uses them.
- No raster images or photos are used.

## Files (in `design/`)
- `index.html` — app shell, section containers, init/navigation wiring, ⌘K + Tweaks bootstrapping. **Start here.**
- `styles.css` — all styling + design tokens (light/dark/density) + responsive breakpoints.
- `data.js` — mock data + `fmt$ / fmtPct / fmtNum` formatting helpers. **This is the API contract.**
- `icons.js` — `Icon(name, size)` inline-SVG factory.
- `charts.js` — `renderAreaChart / renderMultiLineChart / renderDonut / renderSparkline` (SVG).
- `sections-1.js` — Overview + Analyze render + hydrate (incl. account add/edit/remove, donut, net-worth chart).
- `sections-2.js` — Portfolio + Watchlist + Advisor render + hydrate (incl. chat).
- `command.js` — ⌘K command palette.
- `tweaks.js` — accent/density/theme panel + persistence.
- `index-print.html` — print/PDF report variant (all five sections stacked, auto-print). Reference only.

## Implementation notes / gotchas
- Keep cards **opaque** — translucent `backdrop-filter` cards were tried and removed (poor contrast over the mesh background).
- Charts read CSS variables at render time → must re-render on theme/accent change and resize. If you adopt a charting library, pass the resolved color values explicitly.
- All AI copy is placeholder for `analyst.py`. Wire the verdict, advisor plan, and chat to real model output (with streaming for chat).
- The number formatting in `data.js` (`fmt$`, `fmtPct`) defines exact display rules (compact $K/$M, signed deltas, tabular alignment) — match these.
