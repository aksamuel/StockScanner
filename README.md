# StockScanner v2.10.2

[![Stock Scanner](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml/badge.svg)](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml)

StockScanner scans a watchlist or the NYSE universe, calculates technical and
analyst signals, sizes positions, and produces Excel and GitHub Pages reports.

## Features

- Full NYSE universe and custom watchlist scanning
- Parallel Yahoo Finance market-data requests
- Technical scoring, signals, trends, RSI, MACD, and moving averages
- Support and resistance zones based on completed daily candles
- Intraday price overlays without changing daily indicators
- Analyst ratings and target upside as confirmation data
- Percentage-based position sizing and risk controls
- Excel reports and linked HTML dashboards
- Hourly market-hours price snapshots
- Time-bounded exception-list management

## Windows setup

Requirements:

- Windows 10 or later
- Python 3.11 or later
- Git

Open PowerShell and run:

```powershell
cd C:\StockScanner
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

The existing `C:\StockScanner` working copy already has this environment
configured.

## Run a full local scan

This is the recommended command using the same main parameters as the scheduled
GitHub workflow:

```powershell
cd C:\StockScanner
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --parallel --workers 20 --portfolio 50000 --position-size 5 --risk 1 --html
```

It downloads the latest NYSE universe, scans it with 20 workers, and creates
Excel and HTML reports under `reports\YYYY-MM-DD\`.

## Other useful commands

### Watchlist scan

```powershell
.\.venv\Scripts\python.exe -m stockscanner.cli --parallel --workers 20 --portfolio 50000 --position-size 5 --risk 1 --html
```

The watchlist is stored in `watchlists\watchlist.csv`.

### Quick test scan

```powershell
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 20 --parallel --workers 20 --html --progress
```

### Batch Excel reports

```powershell
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --batch-reports --parallel --workers 20 --html
```

### Excel report only

```powershell
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --parallel --workers 20
```

### Scan without report export

```powershell
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 10 --no-report
```

### Launcher

```powershell
.\run.bat
```

## CLI options

| Option | Description | Default |
|---|---|---:|
| `--universe` | Scan the NYSE universe instead of the watchlist | Off |
| `--force-download` | Refresh the NYSE ticker universe before scanning | Off |
| `--limit N` | Limit the universe for a test run | All |
| `--parallel` | Enable parallel stock processing | Off |
| `--workers N` | Parallel worker count | 10 |
| `--portfolio N` | Total portfolio value in dollars | 50000 |
| `--position-size N` | Maximum portfolio percentage per position | 5 |
| `--risk N` | Risk percentage per trade | 1 |
| `--html` | Generate linked HTML dashboards | Off |
| `--batch-reports` | Generate Top-N and batch Excel reports | Off |
| `--progress` | Display scan progress | Off |
| `--quiet` | Suppress per-ticker output | Off |
| `--no-report` | Skip Excel report export | Off |

Run `.\.venv\Scripts\python.exe -m stockscanner.cli --help` for the current
command reference.

## Reports

Each report run creates dated files under `reports\YYYY-MM-DD\`. Stable pages
are also published at the repository root:

| Page | Purpose |
|---|---|
| `index.html` | KPI Dashboard |
| `technical.html` | Technical Analysis |
| `analysts.html` | Analyst ratings and support/resistance |
| `bought-selection.html` | Position sizing and exception selection |
| `exceptions.html` | Current exception list |

Live site: <https://aksamuel.github.io/StockScanner/>

To preview the root pages locally:

```powershell
cd C:\StockScanner
.\.venv\Scripts\python.exe -m http.server 8000
```

Open <http://localhost:8000/>.

## GitHub automation

### Full scanner

`.github/workflows/scan.yml` runs the full scanner on weekdays and supports
manual runs from **Actions > Stock Scanner > Run workflow**. It commits the
generated reports and deploys GitHub Pages.

Manual workflow inputs include mode, ticker limit, workers, portfolio value,
position size, and risk percentage.

### Hourly Yahoo price snapshot

`.github/workflows/price-snapshot.yml` runs during weekday NYSE market-hour
coverage. The Python backend enforces the regular 9:30 AM-4:00 PM New York
session before publishing.

The workflow stores prices and timestamps in `prices.json`. The Technical page
loads this file when **Refresh Latest Prices** is clicked; browser code never
calls Yahoo Finance or GitHub APIs directly.

The KPI Dashboard displays:

- Latest Yahoo quote time
- Backend snapshot refresh time
- Full scanner completion time

## Exception list

`watchlists\exceptions.csv` stores ticker, start date, end date, and reason.
Exceptions are omitted from subsequent scans.

Authorized repository collaborators can:

- Select scanner results on **Bought Selection** and request a 30-day exception
- Enter any ticker and reason directly on **Exception List**
- Select existing exceptions and request removal

These controls open structured GitHub issues. The Add/Remove Exception
workflows validate the request, update the CSV atomically, regenerate
`exceptions.html`, deploy Pages, and close the completed issue.

## Position sizing

Available cash per position is calculated as:

```text
available_cash = portfolio * (position_size / 100)
```

Example:

```powershell
.\.venv\Scripts\python.exe -m stockscanner.cli --universe --parallel --workers 20 --html --portfolio 100000 --position-size 5 --risk 1
```

This permits up to $5,000 per position with a 1% risk setting.

## Market data behavior

- Moving averages, RSI, MACD, and technical scoring use completed daily candles.
- The latest Yahoo one-minute price is used as the displayed Current Price when
  available.
- Support and resistance zones cluster swing points, moving averages, and recent
  breakout/breakdown levels using ATR-based tolerance.
- Analyst ratings and targets confirm results but do not change technical scores.
- Screening requires a share price of at least $1 and average daily dollar volume
  of at least $5 million.

## Cache and rate limits

Historical market data is cached in `data\history\` for one day. The ticker
universe is cached in `data\nyse_tickers.csv`.

Yahoo Finance can rate-limit large or repeated scans. If that happens:

1. Wait before retrying.
2. Reduce `--workers`.
3. Use `--limit` for testing.
4. Avoid running full scans and hourly snapshots simultaneously.

## Project layout

```text
stockscanner\                 Python package
watchlists\watchlist.csv      Local watchlist
watchlists\exceptions.csv     Time-bounded exclusions
prices.json                   Latest published price snapshot
reports\YYYY-MM-DD\           Generated Excel and HTML reports
.github\workflows\            Scanner, snapshot, and exception automation
tests\                        Automated tests
```

## Testing

```powershell
cd C:\StockScanner
.\.venv\Scripts\python.exe -m pytest -q
```
