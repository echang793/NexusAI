# NexusAI

## Purpose
Personal stock-picker + portfolio/net-worth advisor. Pulls market data, computes
technical indicators, and produces AI or rule-based buy/sell/hold verdicts and
portfolio rebalancing plans across brokerage/Roth IRA/HSA holdings.

## Stack
Python 3.14 (`.venv`), Flask backend (`server.py`) serving a static JS/HTML
dashboard (`design_handoff_nexusai/design/`), `yfinance` for market data,
`finnhub-python` for news/fundamentals (optional), `anthropic` SDK / local
Ollama for the AI advisor, `plaid-python` for balance/holdings sync,
`python-dotenv` for config. Legacy Streamlit UI (`app.py`) still present from
before the Flask migration — see Gotchas.

## Where it runs
Production is the Mac mini, in `~/Developer/NexusAI` (a git clone with its own
`.venv`, `.env` and data files). **Keep it out of iCloud / Desktop / Documents:**
iCloud evicts files to cloud-only placeholders that launchd jobs can't read
(`OSError: [Errno 11] Resource deadlock avoided`), which silently killed the
daily job for about a week in Sep 2026. The MacBook is secondary — `git pull` for
code work only, and never load the launchd jobs there (two machines would write
the same data).

Fresh clone checklist: `./scripts/install-hooks.sh`;
`python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest`;
copy `.env` and the gitignored data files over by hand (never via git);
install the launchd plists (see Gotchas).

## Entry points
- **`server.py`** — current Flask app, the live UI. Run it with
  `./scripts/run_server.sh [port]`: it kills whatever is already on the port,
  starts a detached server, logs to `server.log`, PID in `.server.pid`.
  Default port 5001 (macOS AirPlay squats on 5000). Don't start it with a bare
  `python3 server.py &` — that leaves stale servers serving old code.
  Serves `/`, `/data.js`, `/api/*`.
- **`app.py`** — older Streamlit dashboard, launched by `run.sh`
  (`streamlit run app.py --server.port 8502`). Appears superseded by
  `server.py` per commit "Migrate from Streamlit to Flask..." — confirm with
  the user before assuming it's dead; don't delete without asking.
- **`scripts/daily_refresh.py`** — headless refresh: folds in `imports/`, prices,
  risk, Plaid balance sync + Plaid HSA holdings sync, net-worth snapshot.
  **Scheduled via launchd** (`com.nexusai.dailyrefresh`, 07:30 daily).
- **`scripts/monthly_snapshot.py`** — records the net-worth snapshot.
  **Scheduled via launchd** (`com.nexusai.snapshot`, 1st of month 09:00).
- **`scripts/webull_import.py`** — loads Webull data (pulled through the Claude Webull
  connector, which only works in an interactive session) into the Webull holdings CSVs,
  Webull cash, `combined_holdings.csv` and `portfolio.json`. Validates every position and
  total against Webull's own numbers and writes nothing on a mismatch; both the taxable and
  Roth accounts must be present; backs up to `backups/` first (gitignored).
- **`scripts/monthly_report.py`** — plain-text month-over-month report (net worth, CoastFIRE
  progress, per-account changes, stale-data warnings) built only from stored files
  (`nw_history.json` snapshots + `accounts.json` dates); never recomputes net worth. Writes
  `reports/YYYY-MM.txt` (gitignored).
- **Monthly report task** — a Claude scheduled task, `nexusai-monthly-report` (manage it in the
  app's Scheduled section, not in this repo), runs ~08:40 on the 1st and emails the report.
  The scheduled session cannot see the Webull connector (confirmed in a test run), so Webull
  holdings are NOT refreshed automatically: refresh them in an interactive session ("update
  NexusAI for <month>"), which also re-records the month with `monthly_snapshot.py --force`.
  The task only runs while the Claude desktop app is open (otherwise on next launch), and its
  tool approvals must be granted once via "Run now" or runs stall on a permission prompt.
- **`scripts/plaid_link.py`** — one-time local tool to link one institution via
  Plaid Link and print its access token (run once per institution).
- **`scripts/install-hooks.sh`** — installs the pre-commit guard (blocks
  committing `.env`, data files, or hardcoded key-shaped strings).

## Commands
- Run server: `./scripts/run_server.sh` → http://localhost:5001
- Run legacy Streamlit UI: `./run.sh` → http://localhost:8502
- Test: `.venv/bin/python3 -m pytest tests/ -q` — 20 passed. `pytest` is not in
  `requirements.txt`; install it. The suite is hermetic: a session fixture
  redirects the price/period/risk caches and `nw_history.json` to a temp dir,
  and Plaid is forced to "unconfigured". yfinance stderr noise for fake tickers
  is normal.
- Verify a scheduled job actually ran: check `scripts/daily_refresh.log`
  timestamps and `launchctl print gui/$(id -u)/com.nexusai.dailyrefresh | grep
  "last exit"` (0 = ok) — a loaded job can still be silently failing.
- No lint config found (no `pyproject.toml`/`ruff.toml` in repo).
- AI advisor with real Claude calls needs `ANTHROPIC_API_KEY` (currently empty →
  rule-based fallback). Finnhub news/fundamentals uses `FINNHUB_API_KEY` (set).
- Plaid: working. Needs `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`,
  `PLAID_ACCESS_TOKENS` (comma-separated, one per institution) in `.env`. Link
  each institution once with `.venv/bin/python3 scripts/plaid_link.py` (product
  `investments`, read-only; login happens in Plaid's own widget, never here).
  Runs on Plaid's free Trial plan (10 real Items) — re-check pricing at
  plaid.com/pricing before relying on it beyond that.

## Architecture
- `data.py` / `indicators.py` / `news.py` — market data fetch (yfinance),
  technical indicators, news aggregation.
- `analyst.py` / `advisory.py` — AI advisor logic: tries Ollama (local/free) →
  Anthropic (paid) → deterministic rule-based fallback, per `config.LLM_BACKEND`.
- `portfolio.py` / `accounts.py` / `profile.py` / `watchlist.py` — user state,
  persisted as JSON (`portfolio.json`, `accounts.json`, `profile.json`) and
  CSVs (`*_holdings.csv`); all gitignored (contain real financial data).
- `plaid_sync.py` — `pull_balances()` merges account-level balances into
  `accounts.json` by `plaid_account_id` (never overwrites manual accounts);
  `pull_investment_holdings()` syncs ticker-level HSA positions into
  `hsa_holdings.csv` plus a cash-sleeve row. Webull has no Plaid support, so
  its accounts (roughly two thirds of net worth) stay manually refreshed.
- `nw_snapshots.py` — monthly net-worth history (`nw_history.json`). One bucket per
  month and the FIRST reading of the month wins (the daily job and dashboard can't
  overwrite it). To re-record after manually updating Webull holdings, run
  `.venv/bin/python3 scripts/monthly_snapshot.py --force`. Jul-Sep 2026 buckets are
  month-end readings from before this rule; from Oct 2026 on they're first-of-month.
  Each snapshot also stores `details` (per-account balances + CoastFIRE numbers) for the report.
- `scripts/import_holdings.py` / `scripts/apply_snapshot.py` — brokerage
  CSV import pipeline (drop exports in `imports/`).
- `config.py` — central env-driven config/thresholds; loads `.env` via
  python-dotenv.

## Gotchas
- `app.py` (Streamlit) and `server.py` (Flask) both exist and both work
  standalone — verify which one the user actually wants before editing UI
  logic; changes to one won't affect the other.
- `*_cache.json` (price/period/risk), `nw_history.json`, `portfolio.json`,
  `accounts.json`, `profile.json` are real user financial data, gitignored —
  don't commit them, don't fabricate/reset values.
- **Price failures understate net worth.** A held ticker with no price is valued
  at `avg_cost` by the dashboard. `server.batch_prices()` therefore retries each
  ticker the bulk download misses one at a time, never overwrites a good price
  with `None`, and treats a `None` as fresh for only 60s. `/data.js` exposes
  `pricesIncomplete` (tickers still unpriced) and the monthly snapshot is NOT
  written while any held ticker is unpriced — so a ticker that can never price
  will freeze that month's snapshot; fix or remove the ticker. FFLEX/FXAIX
  (mutual funds) always log "no price data" from the bulk `yf.download`; that's
  harmless, the per-ticker fallback prices them.
- **Plaid first-sync duplicates.** Linking a new institution creates NEW rows in
  `accounts.json`; delete the hand-entered manual row for the same real account
  or net worth double-counts it. New account subtypes must map to
  `Taxable`/`Retirement`/`Crypto` (`server._INVESTED_MANUAL_TYPES`) or CoastFIRE
  silently excludes them; `401k Cash`/`IRA Cash` mean just a cash sleeve.
  Proprietary plan fund codes (e.g. `NON40*`) can't be priced by yfinance —
  track those as a lump-sum `Retirement` account, not as holdings.
- **launchd plists.** The templates in `scripts/` still contain the absolute
  path from the old iCloud location. The installed copies in
  `~/Library/LaunchAgents/` are generated from them with a path swap
  (`sed "s#OLD#NEW#g" template > ~/Library/LaunchAgents/<label>.plist`), then
  `xattr -c`, `plutil -lint`, `launchctl unload`/`load`. Redo this on any new
  machine. Logs go to `scripts/*.log`; Python stdout is buffered, so a log only
  updates when the run finishes.
- The daily/monthly jobs fail silently until the next scheduled run if
  `scripts/daily_refresh.py` or `scripts/monthly_snapshot.py` break.
- yfinance's cache dir (`~/Library/Caches/py-yfinance`) doesn't exist on a fresh
  machine; the first bulk fetch races on creating it (`unable to open database
  file`). The per-ticker fallback covers it, but expect noisy first-run logs.

## Do NOT touch
- `scripts/com.nexusai.dailyrefresh.plist`, `scripts/com.nexusai.snapshot.plist`
  — live launchd schedules; edits require re-running `launchctl unload`/`load`.
- `portfolio.json`, `accounts.json`, `profile.json`, `*_holdings.csv`,
  `nw_history.json`, `*_cache.json` — real financial data, gitignored.
- `.env` — holds Plaid credentials and API keys; keep it `chmod 600`, never
  commit (the pre-commit hook blocks it).
