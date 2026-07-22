# Python environment setup

Windows PowerShell commands to create and activate a virtual environment, install dependencies from `requirements.txt`, and verify installation.

1. Create a venv and activate (PowerShell):

```powershell
python -m venv .venv
./.venv/Scripts/Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Quick verification:

```powershell
python -c "import pandas; import yfinance; import ta; import openpyxl; print('OK')"
```

If the last command prints `OK`, the environment is set up.

## Run the app

Use the existing launcher from the repo root:

```cmd
cd C:\StockScanner
run.bat
```

or run the package CLI directly:

```cmd
cd C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli
```

### Scan the watchlist

```cmd
cd C:\StockScanner
run.bat
```

### Scan the full NYSE universe by descending market cap

```cmd
cd C:\StockScanner
run.bat --universe --limit 50
```

This scans the universe starting from the highest market capitalization tickers.

### Skip Excel report export

```cmd
cd C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 20 --no-report
```

### Force download the latest NYSE ticker universe file

```cmd
cd C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download
```

### View CLI help

```cmd
cd C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --help
```

## Run tests

Install developer dependencies:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Then run:

```cmd
.venv\Scripts\python.exe -m pytest
```
