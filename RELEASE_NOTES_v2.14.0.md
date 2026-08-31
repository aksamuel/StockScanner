# StockScanner v2.14.0 release notes

Released as the stable reliability and market-data release.

## Daily scanner

- Requires the current New York date's Supabase ticker universe and at least
  2,000 NYSE symbols before a production scan can start.
- Batch-caches one year of daily price history before analysis.
- Uses a backend-only daily lease so ticker dispatch, primary schedule, and
  fallback schedule cannot publish duplicate reports.
- Preserves the last successful site when a scan or deployment fails.
- Reports successfully analysed symbols separately from download, history,
  price, liquidity, indicator, analysis, and trade-plan exclusions.

## Hourly and close prices

- Stores the singleton price payload directly in Supabase; scheduled price
  collection no longer commits generated JSON or redeploys GitHub Pages.
- Retains only the current New York market day's intraday samples.
- Separates previous close, current price, and today's recorded market close.
- Includes purchased NASDAQ and AMEX symbols without adding them to the
  NYSE-only daily scanner.
- Records provider attribution, stale symbols, purchased-position coverage,
  and idempotent collection slots.
- Opens one operational GitHub issue when purchased symbols remain unpriced.

## Database

- Adds `public.scanner_run_state` and `public.price_collection_runs` as
  backend-only operational tables.
- Extends `public.price_snapshots` with comparison, provider, freshness, and
  portfolio-coverage fields while retaining one singleton row.
- Adds explicit deny policies to backend-only tables.

## Verification

- Complete Python test suite passes.
- GitHub workflow YAML parses successfully.
- Supabase schema, RLS, function grants, and migration history are checked
  before production deployment.
