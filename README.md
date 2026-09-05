# StockScanner v2.17.0

[![Stock Scanner](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml/badge.svg)](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml)

StockScanner scans a watchlist or the NYSE universe, calculates technical and
analyst signals, sizes positions, and produces Excel and GitHub Pages reports.

**Stable release: v2.17.0** — searchable stock dropdowns, purchase-price labels,
and profit/loss percentages beneath technical targets and support/resistance.
Portfolio recovery timelines, the unified strength score and New York clocks
remain available.
Daily scanning, market-price collection, and owner-scoped portfolio storage
continue through the existing services.

[Help & FAQ](https://aksamuel.github.io/StockScanner/help.html) explains the
screens and recovery estimates. [Release notes](RELEASE_NOTES.md) describe this
release; [setup and deployment](README_SETUP.md) covers maintenance.

AI-powered features with ChatGPT integration were introduced in v2.11.0. 🤖

## Features

- Full NYSE universe and custom watchlist scanning
- Split Alpaca Basic/IEX and Yahoo hourly price collection with bounded failover
- Technical scoring, signals, trends, RSI, MACD, and moving averages
- Support and resistance zones based on completed daily candles
- Intraday price overlays without changing daily indicators
- Analyst ratings and target upside as confirmation data
- Percentage-based position sizing and risk controls
- Excel reports and linked HTML dashboards
- Supabase Auth with administrator-controlled account approval
- Admin-only activity and user-management pages
- Admin-only manual daily-scan and hourly-price workflow controls
- Per-user exception and bought-selection lists protected by RLS
- On-demand user portfolio imports from broker CSV files, including native IBKR exports
- Rule-based portfolio profit/loss, holding-time, target, and stop reviews, with a 7% profit-review threshold and conservative automatic targets from technical, resistance, analyst-proxy, and return-objective inputs
- Current profit/loss percentage for purchased positions
- Bought-position time-to-profit status and benchmark-based breakeven-day scenarios
- Daily Supabase NYSE universe refresh at 03:07 New York time
- One-market-day intraday price storage, including the latest hourly quote,
  previous close, and current market close
- Hourly price collection from 08:45 through 15:45 New York time
- Authenticated database overview with RLS-safe personal counts and an
  administrator-only application activity log
- Daily scanner health counts for downloads, history, price/liquidity filters,
  and analysis failures
- Responsive desktop and mobile dashboards with a collapsible left navigation drawer
- Sortable columns across market-data, administration, personal-list, portfolio,
  and generated scanner tables
- Clickable KPI cards with stock dropdowns for Strong Buy, Buy, Accumulate, Watch, Avoid,
  and complete scanned-stock lists
- AI-powered stock analysis with ChatGPT 🎯
  - Individual stock analysis and recommendations
  - AI-generated executive summaries for scan reports
  - Interactive chat interface for Q&A about stocks
  - Automated trading idea generation
  - AI-assisted documentation and docstring generation
  - Comparative stock analysis

## AI Features (ChatGPT Integration)

### 1. Stock Analysis Enhancement

ChatGPT generates contextual analysis for each stock:

```python
from stockscanner.ai_analysis import AIAnalyzer

analyzer = AIAnalyzer()
analysis = analyzer.analyze_stock(
    symbol="AAPL",
    latest_data={"Score": 85, "RSI": 65},
    trade_plan={"Trend": "Strong Uptrend", "Entry": 150, "Stop": 145},
    analyst_data={"Analyst Rating": "Buy", "Target Upside": 12.5}
)
print(analysis)  # AI-powered analysis
```

### 2. Report Generation with AI Commentary

Auto-generate executive summaries and stock commentary:

```python
from stockscanner.ai_report import AIReportGenerator

report_gen = AIReportGenerator()
summary = report_gen.generate_executive_summary(
    scan_date="2026-08-22",
    total_scanned=500,
    qualified_count=23,
    top_3_symbols=["NVDA", "MSFT", "TSLA"]
)
print(summary)
```

### 3. Interactive Chat Interface

Ask questions about stocks and market conditions:

```python
from stockscanner.ai_chat import StockAnalysisChat

chat = StockAnalysisChat()
answer = chat.ask_about_stock(
    symbol="AAPL",
    question="Should I buy AAPL if it breaks above 155?",
    stock_data={"Current Price": 151, "RSI": 65}
)
print(answer)
```

## Setup for AI Features

### 1. Install Dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

### 2. Get OpenAI API Key

1. Sign up at [OpenAI Platform](https://platform.openai.com)
2. Generate an API key from [API Keys](https://platform.openai.com/api-keys)
3. Copy the key

### 3. Configure Environment

Copy `.env.example` to `.env`:

```bash
OPENAI_API_KEY=sk-your-actual-api-key-here
OPENAI_MODEL=gpt-4-turbo-preview
CHATGPT_ENABLED=true
```

### 4. Test the Integration

```powershell
.\.venv\Scripts\python.exe -c "from stockscanner.openai_client import get_chatgpt_client; client = get_chatgpt_client(); print(client.chat('What is technical analysis?'))"
```

## Windows Setup

Requirements:

- Windows 10 or later
- Python 3.11 or later
- Git
- OpenAI API key (for AI features)

Open PowerShell and run:

```powershell
cd C:\StockScanner
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

## Run a Full Local Scan

```powershell
cd C:\StockScanner
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --universe-source download --parallel --workers 20 --portfolio 50000 --position-size 5 --risk 1 --html
```

Production automation uses `--universe-source supabase`. The local `download`
mode is retained for development and recovery tests.

## CLI Options

| Option | Description | Default |
|---|---|---:|
| `--universe` | Scan NYSE universe | Off |
| `--limit N` | Limit universe for test | All |
| `--universe-source download\|supabase` | Select local/live download or Supabase universe | `download` |
| `--force-download` | Bypass a cached local universe file | Off |
| `--parallel` | Enable parallel processing | Off |
| `--workers N` | Parallel worker count | 10 |
| `--batch-reports` | Generate batch and combined Excel reports | Off |
| `--no-report` | Skip report files | Off |
| `--html` | Generate HTML dashboards | Off |
| `--quiet` | Suppress per-ticker output | Off |

## Reports

Each run creates files under `reports\\YYYY-MM-DD\\`:

| Page | Purpose |
|---|---|
| `index.html` | KPI Dashboard |
| `technical.html` | Technical Analysis |
| `analysts.html` | Analyst ratings |
| `bought-selection.html` | Scanner-generated bought candidates |
| `exceptions.html` | Compatibility redirect to the signed-in user's exceptions |
| `my-exceptions.html` | Signed-in user's personal exclusions |
| `my-bought-selection.html` | Signed-in user's purchased positions and profit/loss |
| `portfolio-analysis.html` | User-owned CSV-imported holdings and review signals |
| `database.html` | Approved-user database overview with RLS-scoped counts |
| `admin.html` | Admin-only activity, usage metrics, and manual workflow controls |
| `users.html` | Admin-only accept, block, and delete controls |
| `login.html` | Sign-in and approved-user registration |

On every protected page, use the compact **Menu** button at the upper left to
open or close the shared navigation drawer. The drawer replaces the former
header button rows, shows the signed-in user, includes personal-list and
portfolio links, and shows administration links only to the configured admin.
It closes from its close button, the page overlay, the Escape key, or after a
page is selected.

On the KPI Dashboard, select **Successfully Analysed**, **Strong Buy**, **Buy**,
**Accumulate**, **Watch**, or **Avoid** to open the matching stock list. The
drill-down includes rank, symbol, current price, sector, recommendation, and
score, plus a stock dropdown. Average Score and Best Score remain display-only.

Table filters use searchable dropdowns with sorted, unique stock symbols and an
**All stocks** option. Type a ticker or part of it to narrow the populated list;
prefix matches appear first. Click a choice or use the arrow keys and Enter.
Clearing the field restores all stocks, and Escape cancels an unfinished search.
Scanner choices follow the active table; KPI and portfolio
choices follow the selected category or portfolio scope. On Hourly and Daily
Stock Prices, choosing a symbol also opens its chart. User management uses an
email dropdown with **All users**.

On Technical Analysis and Analysts Rating, owned stocks show **Bought @ $price**
in both Top 20 and All Results. Technical Targets 1–3 and the analyst Support
Low/High and Resistance Low/High prices have a return label underneath: green
for profit, red for loss and grey for breakeven or an unavailable comparison.
The percentage is `(level - buy price) / buy price × 100`, before fees, taxes,
dividends and currency conversion. Existing arrows still compare levels with
the current market price.

Multiple portfolio lots use their quantity-weighted average purchase price.
Portfolio holdings take precedence over a duplicate My Bought List entry;
the bought list supplies the price when no portfolio lots exist for the symbol.
Missing purchase prices, mixed currencies and short positions do not produce a
misleading average. Non-USD purchase prices remain labelled in their currency,
with returns against USD report levels unavailable. Labels survive price
refreshes and table sorting and use only the signed-in user's purchases.

The personal Exception List and Bought Selection are intentionally separate:

- **Exception List** means a ticker must not be considered by that user.
- **Bought Selection** records a position the user owns or tracks, including
  quantity, buy price, and current profit/loss.

Table headers are interactive throughout the protected application. Select a
header to sort ascending and select it again to sort descending. The Technical
Analysis page keeps Entry and Targets 1–3 immediately beside Symbol.

The bought list also shows days held and an estimated breakeven period for a
losing position. The scenario compounds the Equal-weight Top 20's observed
one-year daily return until the position would recover its buy price. It is a
transparent reference scenario—not a forecast—and excludes fees, taxes,
dividends, and company-specific risk. The exact first profitable date is not
claimed because individual daily ticker histories are not retained.

After authentication, the Top 20 applies the signed-in user's lists. Active
personal exceptions and already-bought symbols are hidden by default, with
separate controls to show them. The complete All Results table remains shared
and unfiltered. Candidate-page actions write directly to Supabase; they no
longer create GitHub issues.

## Production data and schedules

| Data | Supabase table | Retention | Schedule |
|---|---|---|---|
| NYSE universe | `public.nyse_tickers` | Current rows only | Weekdays at 03:07 New York time |
| Hourly prices | `public.price_snapshots` | One singleton row; one New York market day | Weekdays during market hours plus a closing-price window |
| Price-run telemetry | `public.price_collection_runs` | Operational slot records | Every hourly or close attempt |
| Scanner-run telemetry | `public.scanner_run_state` | Operational daily lease | Every universe-scan attempt |
| Personal exceptions | `public.user_exceptions` | Per user | User managed |
| Purchased positions | `public.user_bought_selections` | Per user | User managed |
| Imported broker holdings | `public.user_portfolio_holdings` | Latest per user and broker | On demand |
| Portfolio import status | `public.user_portfolio_imports` | Latest per user and broker | On demand |

Each CSV import is an atomic replacement for the signed-in user and the
selected broker. It deletes that user's older rows for the same broker, inserts
the new file, and refreshes the analysis. Holdings for other users and brokers
are never truncated or changed.

### Portfolio analysis guide

- The first four columns are **Symbol → Action review → Recovery scenario /
  days held → Profit / Loss %**. Quantity, buy price/date, present price, review
  target, concentration, price update time, and management controls follow.
- Upload broker CSV files; the direct IBKR download box and Flex download scripts
  have been removed. Native IBKR CSV exports remain supported.
- Use **Analyze portfolio** to select one broker or all brokers. Holdings counts,
  action reviews, concentration, and the last-import timestamp follow this scope.
  Changing brokers resets the stock dropdown and action filter. The redundant Broker
  column has been removed, while broker section headings remain visible.
- **Technical strength** shows Weak in red below 40, Moderate in orange from 40
  through 70 inclusive, and Strong in green above 70. Missing scores are grey.
  These descriptive bands do not change the daily scanner's underlying ratings
  or the separate action-review rules.
  The coloured strength badge and `/100` score appear once per holding, inside
  **Action review**, replacing labels such as `Avoid (35)` with `Weak · 35/100`.
  The separate Technical strength column is removed. Strength remains visible
  for every action review, including when price data is missing.
- **Recovery scenario / days held** keeps the estimated breakeven date visible
  alongside calendar days and the percentage gain required to recover cost.
  Recovered positions say "Buy price recovered". Each estimated date assumes
  its stock-history or Equal-weight Top 20 historical compound rate continues
  from today. Non-positive or unavailable growth produces no date for that
  scenario. Short positions are not given this long-position recovery estimate.
- Recovery scenarios exclude transaction costs, taxes, dividends, and currency
  conversion. They are not promises and do not trigger an action review.
- Choose **View recovery graph** on a losing long position to compare solid blue
  historical adjusted closes with two dashed growth scenarios: blue uses that
  stock's historical compound rate and orange uses the existing Equal-weight
  Top 20 benchmark (each constituent has the same weight). Both start at the
  holding's latest available quote today and aim at the horizontal buy-price
  target. The Top 20 line is rescaled to the holding's price, not its raw index
  level. The quote timestamp and both sample windows are shown in the dialog.
  Both estimated dates remain visible above the graph. The table uses a compact
  timeline: a grey Today dot without today's date, then blue stock-history and
  orange Top 20 milestones in date order, each labelled with its date and days
  to recovery. Missing estimates remain explicit messages rather than dated dots.
  A disclaimer above the table and in the graph states that recovery dates are
  estimates without a guarantee, and recovery may happen earlier, later, or never.
  Use **Inspect date** to read historical prices and projected values.
- The stock's rate is the compound return between the first and last valid
  closes in its one-year sample, measured in calendar days. Zero or negative
  rates draw flat or falling lines and show **No recovery under this assumption**.
  The graph shows up to five future years and each projection stops at the buy
  price; later estimated dates remain listed. These constant-growth scenarios
  are not forecasts, confidence intervals, or recommendations to switch stocks.
- Expand **Historical recovery statistics** inside the graph for comparable drawdown context when
  authenticated stock history is available. The calculation counts non-overlapping
  declines at least as deep as the current loss, reports completed and unresolved
  recoveries, and shows median calendar days for completed recoveries only.
  Historical data is retrieved through an authenticated function using ticker-only
  Yahoo Finance lookups for losing long positions. No account details, quantities,
  or purchase prices are sent to Yahoo. The benchmark breakeven date remains
  available independently. Missing history never creates a recovery prediction.
- Displayed dates and manual date entry use **dd/mmm/yyyy**, for example
  `05/Sep/2026`. CSV templates use the same format; ISO dates remain supported
  for native exports. Database values, chart source data, and file paths retain
  their machine-readable date format.
- All displayed clocks use **New York time, 24-hour HH:mm**, with no seconds;
  for example `05/Sep/2026, 14:07 EDT` or `05/Jan/2026, 13:07 EST`.
  New York daylight saving and the corresponding calendar date are handled
  automatically, independently of the browser's location. This includes portfolio
  quote/import times, administration, market-data charts, reports, and new Excel
  exports. Timestamp data retains its original precision for calculations.

Backend workflows use `SUPABASE_SECRET_KEY` from the protected GitHub
`github-pages` environment. That secret must never be placed in HTML,
JavaScript, documentation examples, or source control.

The daily scanner remains NYSE-only. The hourly price universe is broader: it
combines the latest scanner symbols with the distinct symbols in every user's
`user_portfolio_holdings`, so existing NASDAQ and AMEX positions can receive a
present price without becoming daily scan candidates. The backend query reads
only the `symbol` column and does not expose portfolio details to the browser.

The hourly job assigns alternating symbols to Alpaca Basic/IEX and Yahoo. Any
missing or timed-out symbol is retried once through the other primary provider.
Up to eight remaining symbols can use Twelve Data, matching its free
eight-credit-per-minute allowance. Add `ALPACA_API_KEY_ID`,
`ALPACA_API_SECRET_KEY`, and optionally `TWELVE_DATA_API_KEY` as protected
`github-pages` environment secrets; none belongs in browser code. If a key is
absent, that provider is skipped and the remaining configured providers run.

Hourly collection writes directly to Supabase and does not commit generated
price JSON or redeploy GitHub Pages. Each run first reads the singleton row,
updates it, and writes it back. When the New York market date changes, prior
intraday samples are discarded while the prior close is retained as the new
day's comparison baseline. A separate close run records today's market close.
The first hourly run is scheduled for 08:45 New York time, followed by runs
at 60-minute intervals through 15:45. Per-slot database leases make delayed
or duplicate GitHub cron events safe. A separate post-close candidate records
the market close.

The production universe scan normally starts immediately after the confirmed
03:07 ticker refresh. A 09:17 schedule remains as the primary safety net,
with a 10:47 fallback if GitHub delays or misses an earlier cron event. An
atomic Supabase daily-run lease prevents these triggers from producing duplicate
reports. The scanner refuses a stale universe or fewer than 2,000 NYSE rows,
batch-caches one year of daily history, and reports why symbols were excluded.
Failed runs release the date for the next fallback; partial reports are kept
only as workflow artifacts and never replace the last successful site.

Live site: <https://aksamuel.github.io/StockScanner/>

Approved users can inspect current market-data status and counts for their own
Supabase records from `database.html`. The administrator additionally sees the
latest StockScanner activity events there. Supabase infrastructure, API, Auth,
Postgres, and Edge Function logs remain in the protected Supabase Logs Explorer;
the management credential required for those logs is never exposed in the
static site.

## Testing

```powershell
cd C:\StockScanner
.\.venv\Scripts\python.exe -m pytest -q
```

The deployment workflow runs the Python suite and JavaScript date, recovery,
and history checks before publishing. A successful Pages deployment publishes
the versioned stable release and its release notes. Browser checks cover the
portfolio timeline, the single strength badge, column order, mobile layout, and
New York clock formatting from different browser timezones.

## License

MIT
