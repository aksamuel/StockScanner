# StockScanner

StockScanner is a Python-based stock scanning package for watchlists and the NYSE universe.
It supports:

- watchlist scanning via `watchlists/watchlist.csv`
- NYSE universe scanning with sorted market-cap prioritization
- Excel report export into dated `reports/YYYY-MM-DD/` folders
- parallel scanning with configurable worker threads
- separate NYSE ticker downloader

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

## Commands (quick reference)

- Basic NYSE scan (creates a combined Excel report):

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe
```

- Full NYSE scan with Top-10 + 50-item batch Excel reports (parallel):

```cmd
.venv\Scripts\python.exe -m stockscanner.cli --universe --batch-reports --parallel --workers 20
```

- Scan your watchlist (uses `watchlists/watchlist.csv`):

```cmd
.venv\Scripts\python.exe -m stockscanner.cli
```

- Useful flags:

- `--batch-reports` : produce Top-10, subsequent 50-item batch files, and a combined report
- `--parallel` / `--workers N` : enable parallel scanning with N worker threads (default 10)
- `--progress` : show progress updates during long scans
- `--limit N` : scan only the first N tickers (handy for testing)
- `--no-report` : skip Excel export
- `--force-download` : refresh ticker list / market data downloads

### NYSE universe scan

```cmd
run.bat --universe --limit 1000 --parallel --workers 20
```

### Download only NYSE tickers

```cmd
download_nyse.bat --force-download
```

Or use the fallback yfinance downloader:

```cmd
download_nyse.bat --force-yfinance --limit 1000
```

### Skip Excel export

```cmd
run.bat --universe --limit 1000 --parallel --workers 20 --no-report
```

## Folder layout

- `stockscanner/` — package source
- `download_nyse.py` — NYSE ticker downloader
- `download_nyse.bat` — downloader launcher
- `run.bat`, `run.cmd`, `run.ps1` — Windows launchers
- `reports/YYYY-MM-DD/` — generated Excel output
- `data/nyse_tickers.csv` — cached NYSE ticker universe

## Data cache

- Historical market data is cached on-disk to avoid repeated downloads and speed up scans.
- Cache location: `data/history/` (files named `{SYMBOL}.csv`).
- Default TTL: 7 days. The scanner will use a cached file while it's newer than the TTL.
- To force-refresh cached data for a symbol, either delete its CSV in `data/history/` or run a quick Python call:

```py
from stockscanner.market_data import download_data
download_data("AAPL", force=True)
```

Note: the `download_data()` function accepts `force=True` and a `period` parameter.

## Performance tips

- Use `--quiet` to suppress per-ticker console output and reduce I/O overhead when running large scans.
- Increase `--workers N` when using `--parallel` to allow more concurrent network requests (yfinance is I/O-bound).
- Use `--limit N` for quick tests before running a full universe scan.
- The code also supports `--batch-reports` to create Top-10 and batched 50-item Excel reports while scanning.

## Testing

Install developer dependencies:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run tests:

```cmd
.venv\Scripts\python.exe -m pytest
```
