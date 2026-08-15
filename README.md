# StockScanner v2.9.1

[![Stock Scanner](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml/badge.svg)](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml)

StockScanner is a Python-based stock scanning package for watchlists and the NYSE universe.
It supports:

- Watchlist scanning via `watchlists/watchlist.csv`
- NYSE universe scanning with sorted market-cap prioritization
- Excel report export into dated `reports/YYYY-MM-DD/` folders
- **Interactive HTML dashboard** (static, opens in any browser)
- **Percentage-based position sizing** (portfolio %, risk %)
- Parallel scanning with configurable worker threads
- Separate NYSE ticker downloader

## Setup

1. Create and activate the virtual environment:

```cmd
cd /d C:\StockScanner
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```cmd
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. Install the package in editable mode:

```cmd
.venv\Scripts\python.exe -m pip install -e .
```

## Run the package

Use the default launcher:

```cmd
cd /d C:\StockScanner
run.bat
```

Or invoke the package CLI directly:

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli
```

## Commands

### Full NYSE universe scan with HTML dashboard (recommended)

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --parallel --workers 20 --html
```

This will:
1. Download the latest NYSE ticker list
2. Scan the full universe in parallel (20 threads)
3. Generate an Excel report **and** an interactive HTML dashboard

### Watchlist scan with HTML dashboard

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --parallel --workers 20 --html
```

### NYSE universe with batch Excel reports + HTML

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --batch-reports --parallel --workers 20 --html
```

### Quick test run (limited tickers)

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 20 --parallel --workers 20 --html --progress
```

## CLI flags reference

| Flag | Description |
|------|-------------|
| `--universe` | Scan the full NYSE universe instead of the watchlist |
| `--force-download` | Refresh the NYSE ticker list before scanning |
| `--html` | Generate an interactive HTML dashboard report |
| `--batch-reports` | Produce Top-10 + 50-item batch Excel files + combined report |
| `--parallel` | Enable parallel scanning |
| `--workers N` | Number of parallel threads (default 10) |
| `--progress` | Show progress updates during long scans |
| `--limit N` | Scan only the first N tickers (for testing) |
| `--no-report` | Skip Excel and HTML report export |
| `--quiet` | Suppress per-ticker console output |

The scanner generates HTML report pages alongside the Excel workbooks. Each run creates:
- `reports/YYYY-MM-DD/index.html` for the date folder
- `reports/index.html` for the root report index
- HTML versions of combined, top, and batch reports matching the Excel output

## GitHub Pages reports

Published reports are served from the repository root on GitHub Pages:

- Site root: `https://aksamuel.github.io/StockScanner/`
- Reports index: `https://aksamuel.github.io/StockScanner/reports/index.html`
- Dated report index: `https://aksamuel.github.io/StockScanner/reports/YYYY-MM-DD/index.html`

The repository root `index.html` redirects to `reports/index.html` so the site never lands on a dead-end 404. The Pages deployment workflow publishes the repository root and commits generated `reports/**` artifacts back to the published branch.

## Scheduled scan (GitHub Actions)

The scanner runs automatically at **9:00 AM New York time** on NYSE trading days (Mon-Fri) via GitHub Actions. It performs a full universe scan with default position sizing and deploys the HTML dashboard to GitHub Pages.

During weekday NYSE regular hours, a separate hourly workflow runs
`python -m stockscanner.price_snapshot`. It refreshes only the symbols in
`prices.json`, preserves the prior value for any symbol Yahoo fails to return,
and redeploys the static site. The Technical page's **Refresh Latest Prices**
button fetches this public snapshot; it does not call Yahoo or GitHub APIs.

You can also trigger a scan manually from the **GitHub mobile app** or the **Actions tab**:

1. Go to **Actions** > **Stock Scanner** > **Run workflow**
2. Configure inputs: mode, limit, workers, portfolio, position size, risk
3. Tap **Run workflow**

The workflow supports these configurable inputs:

| Input | Default | Description |
|-------|---------|-------------|
| Mode | universe | `universe` or `watchlist` |
| Limit | 0 (all) | Max tickers to scan |
| Workers | 20 | Parallel threads |
| Portfolio | 50000 | Total portfolio value ($) |
| Position size | 5 | Max % of portfolio per position |
| Risk | 1 | Risk % per trade |

### Local preview

From the repository root:

```bash
python -m http.server 8000
```

Then open:

- `http://localhost:8000/`
- `http://localhost:8000/reports/index.html`

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 20 --parallel --workers 20 --html --progress
```

### Excel report only (no HTML)

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --parallel --workers 20
```

### Skip all report export

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 10 --no-report
```

### Download only NYSE tickers

```cmd
download_nyse.bat --force-download
```

Or use the fallback yfinance downloader:

```cmd
download_nyse.bat --force-yfinance --limit 1000
```

## CLI flags reference

| Flag | Description |
|------|-------------|
| `--universe` | Scan the full NYSE universe instead of the watchlist |
| `--force-download` | Refresh the NYSE ticker list before scanning |
| `--html` | Generate an interactive HTML dashboard report |
| `--batch-reports` | Produce Top-10 + 50-item batch Excel files + combined report |
| `--parallel` | Enable parallel scanning |
| `--workers N` | Number of parallel threads (default 10) |
| `--progress` | Show progress updates during long scans |
| `--limit N` | Scan only the first N tickers (for testing) |
| `--no-report` | Skip Excel export entirely |
| `--quiet` | Suppress per-ticker console output |
| `--portfolio N` | Total portfolio value in dollars (default: 50000) |
| `--position-size N` | Max % of portfolio per position (default: 5) |
| `--risk N` | Risk % per trade (default: 1) |

## Position Sizing

The scanner uses percentage-based position sizing to calculate suggested shares and investment per stock:

```
available_cash = portfolio * (position_size / 100)
```

**Examples:**

| Style | Command | Per-Position Cash |
|-------|---------|-------------------|
| Default | `--portfolio 50000 --position-size 5` | $2,500 |
| Conservative | `--portfolio 100000 --position-size 2` | $2,000 |
| Moderate | `--portfolio 100000 --position-size 5` | $5,000 |
| Aggressive | `--portfolio 50000 --position-size 10 --risk 2` | $5,000 (2% risk) |

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --parallel --workers 20 --html --portfolio 100000 --position-size 5 --risk 1
```

## Support and Resistance Zones

Each scan reports informational support and resistance zones without changing
the technical score or ranking. Zones cluster repeated swing highs/lows, MA20,
MA50, MA200, and recent breakout or breakdown levels. The cluster tolerance is
half of 14-day ATR, with a 1% price fallback when ATR is unavailable. Repeated
tests and volume-confirmed breaks increase the displayed confidence, and broken
resistance/support is identified as role-reversed support/resistance.

Levels and indicators use completed daily candles only. A current intraday
price, when available, is used only to label price as At Support, At Resistance,
Between Zones, Breakout Above Resistance, or Breakdown Below Support. Reports
include each zone's bounds, distance, test count, confidence, sources, and
tolerance; unavailable history is shown explicitly.

## HTML Dashboard

The `--html` flag generates a self-contained HTML file in `reports/YYYY-MM-DD/` that you can:

- **Open locally** in any browser (no server required)
- **Deploy to GitHub Pages** for private team access
- **Share** via email, Teams, or Slack

Features:
- Dark-themed responsive dashboard with summary cards
- Interactive bar chart (recommendation breakdown)
- Sortable and filterable results tables (Top 20 + All)
- Color-coded scores and recommendations
- A filterable exception-list page at `exceptions.html`, regenerated from `watchlists/exceptions.csv`
- Exception entries are kept in alphabetical ticker order after additions and removals
- Expired `Date To` values are highlighted in red on the exception dashboard
- Authorized collaborators can select multiple exception rows and submit one GitHub removal request; the `Remove Exception` Action validates the request, updates the CSV atomically, and republishes the page
- The Top 20 and All Results tables support selecting up to 50 tickers and submitting one authorized request to exclude them for 30 days

Screening requires a share price of at least **$1.00** and average daily dollar volume of at least **$5 million**.

Analyst consensus and mean target upside are displayed as confirmation data.
They only break ties after Score, setup quality, Risk/Reward, and Relative
Strength; they do not change the technical score. Yahoo Finance analyst targets
are generally longer-horizon estimates, while the scanner's technical factors
remain the short-term selection method.

During market hours, the scanner overlays Yahoo Finance's latest one-minute
extended-hours price and cumulative session volume. Moving averages, RSI, and
MACD continue to use completed daily candles only. Before the first quote of
the current session is available, the scanner falls back to the latest
completed close.

## Folder layout

- `stockscanner/` — package source
- `download_nyse.py` — NYSE ticker downloader
- `download_nyse.bat` — downloader launcher
- `run.bat`, `run.cmd`, `run.ps1` — Windows launchers
- `reports/YYYY-MM-DD/` — generated Excel and HTML output
- `data/nyse_tickers.csv` — cached NYSE ticker universe
- `data/history/` — cached historical market data

## Data cache

- Historical market data is cached on-disk to avoid repeated downloads and speed up scans.
- Cache location: `data/history/` (files named `{SYMBOL}.csv`).
- Default TTL: 1 day. The scanner will use a cached file while it's newer than the TTL.
- To force-refresh cached data for a symbol, either delete its CSV in `data/history/` or run a quick Python call:

```py
from stockscanner.market_data import download_data
download_data("AAPL", force=True)
```

## Performance tips

- Use `--quiet` to suppress per-ticker console output and reduce I/O overhead when running large scans.
- Increase `--workers N` when using `--parallel` to allow more concurrent network requests (yfinance is I/O-bound).
- Use `--limit N` for quick tests before running a full universe scan.
- Combine flags for maximum speed: `--universe --parallel --workers 20 --quiet --html`

## Testing

Install developer dependencies:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run tests:

```cmd
.venv\Scripts\python.exe -m pytest
```
