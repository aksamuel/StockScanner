# StockScanner v2.14.0 setup and operations

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

### Full local NYSE scan with HTML dashboard

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --universe-source download --parallel --workers 20 --html
```

This mode downloads the universe locally and is intended for development or
recovery testing. Production uses the Supabase command below.

### Production-style scan using the Supabase universe

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --universe-source supabase --parallel --workers 20 --html
```

Before running this command, set `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in the
current secured session. Do not put the secret value in a batch file, command
example, documentation, or source control.

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
.venv\Scripts\python.exe -m stockscanner.cli --universe --universe-source download --batch-reports --parallel --workers 20 --html
```

### Custom position sizing

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --parallel --workers 20 --html --portfolio 100000 --position-size 5 --risk 1
```

### Force-refresh the local NYSE ticker CSV

```cmd
cd /d C:\StockScanner
.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download
```

This command affects the legacy local CSV path only. The production ticker
universe is replaced by the **Daily NYSE Ticker Universe** GitHub workflow.

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

## Apply the Supabase migrations

Apply the migrations in timestamp order:

1. `20260822204558_create_price_snapshots.sql`
2. `20260828000000_add_admin_user_approval.sql`
3. `20260828085119_optimize_admin_rls.sql`
4. `20260828093000_store_latest_market_data.sql`
5. `20260828094500_fix_ticker_replace_delete.sql`
6. `20260828120000_add_user_portfolio_imports.sql`
7. `20260828123000_enable_personal_exception_updates.sql`
8. `20260831193000_add_scanner_daily_run_state.sql`
9. `20260831213000_market_price_reliability.sql`
10. `20260831214500_document_backend_only_rls.sql`

The final two migrations add backend-only daily-scan and price-collection
leases, scanner/price telemetry, previous-close and market-close fields, and
purchased-position coverage. Apply them before deploying v2.14.0 workflows.

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

User-management and activity pages are accessible only to that administrator.
Deleting a user also removes the user's exception, bought-selection, imported
portfolio, and portfolio-import-status rows through database foreign-key
cascading. Blocked or rejected users cannot use the protected application pages.

## Store the current NYSE universe in Supabase

Apply both market-data migrations listed above, then keep
`SUPABASE_SECRET_KEY` in the protected GitHub `github-pages` environment.
The **Daily NYSE Ticker Universe** workflow refreshes `public.nyse_tickers`
once each weekday at or after 8:07 AM New York time. It uses both possible UTC
hours plus database date guards so daylight-saving changes and delayed GitHub
jobs do not create duplicate downloads.

The production universe scan reads the current rows from Supabase. Each refresh
atomically replaces the table; ticker history is not retained. The market-data
migrations keep one singleton `public.price_snapshots` row. Within that row,
intraday samples are limited to the current New York market date. The workflow
writes directly to Supabase; it does not commit `prices.json` or trigger a Pages
deployment.

### Configure free hourly price providers

Create an Alpaca Basic account and store its credentials in the protected
GitHub `github-pages` environment as `ALPACA_API_KEY_ID` and
`ALPACA_API_SECRET_KEY`. The workflow explicitly requests Alpaca's free IEX
feed. Optionally add a Twelve Data Basic key as `TWELVE_DATA_API_KEY`; the code
uses no more than eight Twelve Data symbols per run so the scheduled workflow
stays below its free minute and daily quotas.

The hourly symbol list is the union of the latest scanner snapshot and all
distinct symbols in `public.user_portfolio_holdings`. This keeps the daily scan
NYSE-only while still pricing existing NASDAQ and AMEX holdings. The workflow
uses `SUPABASE_SECRET_KEY` to read only the holdings' `symbol` column; it never
places portfolio rows or the secret in the public site.

The combined list is split evenly between Alpaca and Yahoo. Missing or timed-out
prices cross over to the other provider once, then up to eight remaining gaps
use Twelve Data. Retries are intentionally bounded: an endless loop could
exceed a free quota and still cannot guarantee a current quote for an inactive
or unsupported security. A failed live symbol retains its prior stored price
and is listed in the snapshot's `failures` object.

Free-provider terms can restrict redistribution or public display. Confirm that
the selected account plan permits the way the protected StockScanner site is
used before enabling an optional provider.

The `public.nyse_tickers` table is backend-only: `anon` and `authenticated`
have no table privileges. The `service_role` can replace the current universe.
The replacement RPC uses `SECURITY INVOKER`, an empty `search_path`, and an
explicit `EXECUTE` grant only for `service_role`.

## Personal lists

The two signed-in user pages serve different purposes:

- `my-exceptions.html`: tickers the user does not want considered.
- `my-bought-selection.html`: positions the user owns or tracks, with quantity,
  buy price, present price, profit/loss percentage, days held, and an estimated
  breakeven period using the Equal-weight Top 20 as a reference scenario.
- `portfolio-analysis.html`: on-demand IBKR Flex and broker CSV holdings, current
  return, holding duration, daily scanner evidence, concentration, and
  sell/partial-sell/hold review signals. The profit-review threshold is 7%.
  Manual targets override the conservative automatic target, which selects the
  closest valid profit-side price from the return objective, Technical Target 1,
  resistance, and analyst target proxy. Each import atomically replaces only
  the signed-in user's older rows for that broker before the page recalculates
  the analysis; it never truncates another user or broker.

Do not duplicate bought positions into the Exception List. The authenticated
Top 20 hides that user's bought/imported holdings and active exceptions by
default. **Show Already Bought** and **Show My Exceptions** expose them without
altering the shared All Results table. Candidate-page add actions update
Supabase directly rather than opening GitHub issues.

All protected pages use a compact upper-left **Menu** button. It opens the same
responsive navigation drawer on PC and mobile; the close button, backdrop,
Escape key, or choosing a destination closes it. Admin links appear only for
`aaksamuel@zohomail.com`.

On the KPI Dashboard, Stocks Scanned, Strong Buy, Buy, Accumulate, Watch, and
Avoid are clickable and open searchable stock lists generated from the same
scan as their counts.

The bought-list breakeven value is an illustrative benchmark calculation. It
uses the Equal-weight Top 20's observed daily compound return over the chart
window and calculates how many calendar days that rate would need to recover
the gap from the latest price to the buy price. It is not a forecast or promise,
and it does not estimate the historical first-profit day because individual
daily ticker histories are not retained.

### Configure on-demand IBKR imports

Create an IBKR Flex Web Service Activity query that returns **Open Positions**
as CSV. Use tax-lot detail to include buy dates. Store its token and query ID as
Supabase Edge Function secrets named `IBKR_FLEX_TOKEN` and
`IBKR_FLEX_QUERY_ID`, then deploy `import-ibkr-portfolio` with caller JWT
verification handled by the function. Never put either IBKR value in browser
code or GitHub Pages.

## Production GitHub workflows

| Workflow | Purpose | Schedule |
|---|---|---|
| `ticker-universe.yml` | Atomically replaces `public.nyse_tickers` | Once per weekday at or after 8:07 AM New York time |
| `scan.yml` | Runs the universe scan and publishes GitHub Pages | After a successful ticker refresh, with 9:17 AM primary and 10:47 AM fallback schedules |
| `price-snapshot.yml` | Updates hourly/current, previous-close, and market-close prices directly in Supabase | Weekday candidate slots during market hours and the close window, plus manual dispatch |
| `invite-admin.yml` | Invites or promotes an administrator without handling a password | Manual only |

GitHub cron is UTC-only and may deliver runs several hours late. The ticker and
scan workflows schedule redundant candidate UTC hours and use New York date
and database lease guards to remain daylight-saving safe. A delayed scanner
candidate is accepted any time after 9:00 AM New York when that market date has
not already completed. The
scanner uses `public.scanner_run_state` as a backend-only atomic daily lease,
requires today's refreshed universe with at least 2,000 rows, and batch-caches
daily histories before analysis. `public.price_collection_runs` similarly
deduplicates each hourly/close slot. Failed scans can be retried by the next
fallback and never publish partial reports. Non-zero minutes avoid GitHub
Actions' busiest top-of-hour window.

### Verify a production release

1. Confirm the ticker-universe workflow replaced at least 2,000 rows for the
   current New York market date.
2. Confirm the universe scan completed and the dashboard shows exclusion
   counts rather than treating every universe symbol as successfully analysed.
3. Confirm `public.price_snapshots` has one row, current-day intraday samples,
   previous-close data, and purchased-position coverage.
4. Confirm no unresolved **StockScanner price coverage incomplete** issue was
   created by the hourly workflow.
5. Run the complete test suite and review Supabase Security and Performance
   Advisors before tagging the release.

## Security checklist

- Use a publishable/anonymous key only in browser code.
- Store `SUPABASE_SECRET_KEY` only in the protected GitHub environment.
- Store Alpaca and Twelve Data API credentials only in the protected GitHub
  environment; never add them to the repository or static site.
- Keep RLS enabled on exposed `public` tables and use ownership predicates for
  personal rows.
- Use `app_metadata`, not user-editable `user_metadata`, for authorization
  claims.
- Enable leaked-password protection in Supabase Auth.
- Review Supabase Security and Performance Advisors after schema changes.
