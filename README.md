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

## Testing

Install developer dependencies:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run tests:

```cmd
.venv\Scripts\python.exe -m pytest
```
