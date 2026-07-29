# StockScanner

StockScanner is a Python-based stock scanning package for watchlists and the NYSE universe.
It supports:

- Watchlist scanning via `watchlists/watchlist.csv`
- NYSE universe scanning with sorted market-cap prioritization
- Excel report export into dated `reports/YYYY-MM-DD/` folders
- **Interactive HTML dashboard** (static, opens in any browser)
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
- Default TTL: 7 days. The scanner will use a cached file while it's newer than the TTL.
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
