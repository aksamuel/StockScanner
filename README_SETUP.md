# Python environment setup

Windows PowerShell commands to create and activate a virtual environment, install dependencies from `requirements.txt`, and verify installation.

1. Create a venv and activate (PowerShell):

```powershell
cd C:\StockScanner
python -m venv .venv
./.venv/Scripts/Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Install in editable mode:

```powershell
pip install -e .
```

4. Quick verification:

```powershell
python -c "import pandas; import yfinance; import ta; import openpyxl; print('OK')"
```

If the last command prints `OK`, the environment is set up.

## Run the app

Use the existing launcher from the repo root:

```cmd
cd /d C:\StockScanner
run.bat
```

or run the package CLI directly:

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli
```

## Common commands

### Full NYSE scan with HTML dashboard (recommended)

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --parallel --workers 20 --html
```

### Watchlist scan with HTML dashboard

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --parallel --workers 20 --html
```

### Quick test (limited tickers + progress)

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 20 --parallel --workers 20 --html --progress
```

### NYSE scan with batch Excel reports + HTML

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --batch-reports --parallel --workers 20 --html
```

### Custom position sizing

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --parallel --workers 20 --html --portfolio 100000 --position-size 5 --risk 1
```

### Force download the latest NYSE ticker universe

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download
```

### Skip all report export (console output only)

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --limit 10 --no-report
```

### View CLI help

```cmd
cd /d C:\StockScanner
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

## Activate invite-only Supabase authentication

The application migration creates `public.signup_allowlist` and the
`private.hook_require_admin_permission` Auth hook. After applying the migration
to the StockScanner Supabase project:

1. Open **Authentication → Hooks → Before User Created**.
2. Select the Postgres hook in schema `private` named
   `hook_require_admin_permission`.
3. Enable and save the hook before deploying the updated login page.

The administrator `aaksamuel@zohomail.com` can then open `admin.html` and permit
an email address. Only permitted email addresses can create an account. Supabase
Auth manages password hashes; StockScanner never stores user passwords.
