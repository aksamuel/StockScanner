# IBKR Sync Runbook

PIP supports explicit CSV import and optional read-only Flex Web Service sync.
The live path is deliberately separate from the existing scanner portfolio
imports and never sends an order.

## Enable live Flex sync

1. Apply the PIP schema and approval migrations, then
   `20261026000000_pip_account_fingerprints.sql`,
   `20261027000000_pip_ibkr_flex_vault.sql`,
   `20261102000000_pip_flex_position_snapshots.sql`, and
   `20261102000001_pip_flex_token_validation.sql`. Supabase Vault must be enabled.
2. Deploy the Edge Function with `supabase functions deploy pip-ibkr-flex`.
   Supabase's function environment must retain its normal server-side service
   role secret; do not put that key in the FastAPI service or browser.
3. Generate one high-entropy internal key (at least 32 characters) and configure
   the same value as `PIP_FLEX_INTERNAL_KEY` in Render and Supabase Edge Function
   secrets. Never commit or expose this value. Configure `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` on the API host; the API does not use a
   service-role key.
4. In IBKR Client Portal, open **Reporting > Flex Queries**, enable **Flex Web
   Service Configuration**, and create an Activity Flex Query. Select the
   intended accounts and XML output. To backfill up to a year of available
   trades and dividend payments, choose **Last 365 Calendar Days**; a shorter
   period may legitimately contain no activity. Do not apply symbol filters:
   the Open Positions section must include all stock positions for each
   selected account. Include these fields:
   - **Account Information:** Account ID and Currency (the account's base
     currency).
   - **Open Positions:** Account ID, Currency, Asset Class, Symbol, Conid,
     Quantity, Cost Basis Price, Mark Price, Position Value, Open Date Time,
     and Level of Detail. Use either Summary or Lot detail for a holding, not both.
   - **Trades:** Account ID, Currency, Asset Class, Symbol, Trade ID, Trade Date,
     Buy/Sell, Quantity, and Trade Price.
   - **Cash Transactions:** Account ID, Currency, Symbol, Type, Amount, and
     Date/Time; this section contains dividend payments.
   Use `yyyyMMdd` or `yyyy-MM-dd` dates. The statement must identify each
   account, its end date, and an Open Positions section, including an empty
   section for an account with no open positions. Obtain the numeric Query ID
   from the query's information button. Linked-account tokens may need to be
   obtained from the IBKR master account. Do not share the token or Query ID in
   an issue, log, or source file.
5. Sign in with an approved StockScanner account, select a PIP portfolio, save a
   named Flex connection, and choose **Sync statement**. Confirm that the query
   is unfiltered when prompted. The browser sends the credentials only to the
   authenticated API; the Edge Function stores them in Vault and retrieves
   statements on demand. The API validates the XML and persists masked account
   and normalized portfolio data using the caller's Supabase JWT and owner RLS.

Each user can manage multiple named Flex connections and each connection can
return multiple IBKR accounts. Account IDs are masked for display and a
non-display fingerprint distinguishes accounts that happen to share the same
last four digits. Each Flex response is limited to 5 MB and 10,000 normalized
records; the Edge Function enforces IBKR's per-token request limits. The live
path accepts XML, not ZIP bundles. If IBKR provides only a ZIP bundle for
multiple accounts, configure a separate XML query and named connection for
each account instead.

For each included account, a complete Flex snapshot atomically replaces earlier
Flex positions, including positions no longer present. An older statement or an
earlier concurrent sync cannot overwrite a newer snapshot. Incomplete statements
are rejected without replacing positions. CSV/manual holdings and transaction
and dividend history are retained; importing the same holdings via CSV and Flex
therefore counts both copies. IBKR statements reflect their report date, not
necessarily real-time prices; the sync result displays that date for each
masked account.

If sync fails, check that the user is approved, the portfolio and connection
belong to that user, the matching internal keys are configured, and the Flex
Query returns a complete, current XML statement. If IBKR omits Open Positions
for an empty account, PIP cannot safely distinguish that from an omitted
section and will leave earlier positions unchanged. Longer reports can take
time to prepare; PIP polls within a bounded window and respects IBKR's
per-token limits. If the report is still unavailable, wait before retrying and
consult [IBKR's error-code reference](https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm)
for any code shown. Credentials are cleared from the browser form after every
save attempt. They are never returned by the API, stored in browser storage,
or written to audit events. Do not log request URLs to IBKR because the Flex
token is a query parameter in the upstream protocol.

## CSV fallback

1. Select the target portfolio and upload the IBKR CSV export.
2. Review the browser-side preview and explicitly import it. The API validates
   and persists normalized records through the caller's Supabase JWT and owner
   RLS.
3. Re-importing the same export in the same row order updates the imported
   position rows; imports do not delete rows omitted by a later export.

The browser/API CSV limit is 1 MB and 1,000 data rows. Existing scanner
portfolio imports are not modified by either PIP sync path. Never print raw
source rows or persist unmasked account identifiers.

## Flex migration regression tests

The SQL regression tests use `@electric-sql/pglite` in an isolated directory
and are skipped unless `PIP_PGLITE_PREFIX` points to that directory. Install
version `0.5.14` there, set `PIP_PGLITE_PREFIX`, and run
`node --test tests/pip-flex-snapshots-sql.test.mjs tests/pip-flex-vault-sql.test.mjs`.
They exercise the real migrations in an isolated database, including owner
isolation, default Supabase role grants, and Vault RPC token validation. The
Vault test uses a stub in place of the encrypted production Vault extension.
