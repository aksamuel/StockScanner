# StockScanner v2.15.0 release notes

Released as the stable scheduling and database-visibility release.

## Scheduling

- Refreshes the current NYSE ticker universe at 3:07 AM New York time on
  weekdays, with daylight-saving-aware candidates and database date guards.
- Starts hourly price collection at 8:45 AM New York time and continues at
  60-minute intervals through 3:45 PM.
- Keeps the post-close price collection separate from intraday slots.
- Retains Supabase leases so delayed or duplicate GitHub events cannot publish
  the same logical slot twice.

## Database overview and logs

- Adds `database.html` for all approved users.
- Shows the latest shared market-data status and RLS-filtered counts for the
  signed-in user's portfolio, imports, exception list, and bought list.
- Shows recent login, page-view, and logout events only to
  `aaksamuel@zohomail.com`.
- Links the administrator to Supabase Logs Explorer without exposing a
  management token or backend secret in browser code.

## Reliability

- Allows the 8:45 AM pre-market snapshot while preserving the 9:30 AM regular
  market-session definition used elsewhere.
- Keeps daily analysis based on completed daily candles; at 3:07 AM the latest
  price is normally the previous completed trading-day close.
- Preserves the existing free-provider failover and purchased-symbol coverage
  checks.

## Verification

- Complete Python test suite passes: 141 tests.
- GitHub workflow YAML parses successfully.
- Documentation and package version references are synchronized to v2.15.0.
