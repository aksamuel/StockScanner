# StockScanner v2.12.0

[![Stock Scanner](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml/badge.svg)](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml)

StockScanner scans a watchlist or the NYSE universe, calculates technical and
analyst signals, sizes positions, and produces Excel and GitHub Pages reports.

**Stable release: v2.12.0** — Supabase-backed current market data, personal
portfolio profit/loss, and production-responsive dashboards.

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
- Per-user exception and bought-selection lists protected by RLS
- On-demand user portfolio imports from IBKR Flex or a broker CSV
- Rule-based portfolio profit/loss, holding-time, target, and stop reviews
- Current profit/loss percentage for purchased positions
- Bought-position time-to-profit status and benchmark-based breakeven-day scenarios
- Daily Supabase NYSE universe refresh at 8:07 AM New York time
- Latest-only hourly market-hours price storage
- Responsive desktop and mobile dashboards with a collapsible left navigation drawer
- Clickable KPI cards with searchable Strong Buy, Buy, Accumulate, Watch, Avoid,
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
| `portfolio-analysis.html` | User-owned IBKR/CSV holdings and review signals |
| `admin.html` | Admin-only activity and usage metrics |
| `users.html` | Admin-only accept, block, and delete controls |
| `login.html` | Sign-in and approved-user registration |

On every protected page, use the compact **Menu** button at the upper left to
open or close the shared navigation drawer. The drawer replaces the former
header button rows, shows the signed-in user, includes personal-list and
portfolio links, and shows administration links only to the configured admin.
It closes from its close button, the page overlay, the Escape key, or after a
page is selected.

On the KPI Dashboard, select **Stocks Scanned**, **Strong Buy**, **Buy**,
**Accumulate**, **Watch**, or **Avoid** to open the matching stock list. The
drill-down includes rank, symbol, current price, sector, recommendation, and
score, plus a text filter. Average Score and Best Score remain display-only.

The personal Exception List and Bought Selection are intentionally separate:

- **Exception List** means a ticker must not be considered by that user.
- **Bought Selection** records a position the user owns or tracks, including
  quantity, buy price, and current profit/loss.

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
| NYSE universe | `public.nyse_tickers` | Current rows only | Weekdays at 8:07 AM New York time |
| Hourly prices | `public.price_snapshots` | Latest `hourly_yahoo` row only | Weekdays at :47 during market hours |
| Personal exceptions | `public.user_exceptions` | Per user | User managed |
| Purchased positions | `public.user_bought_selections` | Per user | User managed |
| Imported broker holdings | `public.user_portfolio_holdings` | Latest per user and broker | On demand |
| Portfolio import status | `public.user_portfolio_imports` | Latest per user and broker | On demand |

Each CSV or IBKR import is an atomic replacement for the signed-in user and the
selected broker. It deletes that user's older rows for the same broker, inserts
the new file, and refreshes the analysis. Holdings for other users and brokers
are never truncated or changed.

IBKR download uses a server-side Flex Web Service token and query ID. Those
secrets belong only in Supabase Edge Function secrets. The browser never
receives them. The IBKR query should return Open Positions in CSV format and use
tax-lot detail when buy dates are required.

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

The production universe scan is scheduled for 9:17 AM New York time. Candidate
UTC hours plus New York-time gates keep both daily jobs correct across daylight
saving changes; non-zero minutes reduce GitHub's top-of-hour scheduling delays.

Live site: <https://aksamuel.github.io/StockScanner/>

## Testing

```powershell
cd C:\StockScanner
.\.venv\Scripts\python.exe -m pytest -q
```

The current local `v2.12.0` package passes 101 tests.

## License

MIT
