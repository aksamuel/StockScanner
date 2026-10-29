# IBKR Sync Runbook

PIP supports explicit CSV import and optional read-only Flex Web Service sync.
The live path is deliberately separate from the existing scanner portfolio
imports and never sends an order.

## Enable live Flex sync

1. Apply the PIP schema and approval migrations, then
   `20261026000000_pip_account_fingerprints.sql` and
   `20261027000000_pip_ibkr_flex_vault.sql`. Supabase Vault must be enabled.
2. Deploy the Edge Function with `supabase functions deploy pip-ibkr-flex`.
   Supabase's function environment must retain its normal server-side service
   role secret; do not put that key in the FastAPI service or browser.
3. Generate one high-entropy internal key (at least 32 characters) and configure
   the same value as `PIP_FLEX_INTERNAL_KEY` in Render and Supabase Edge Function
   secrets. Never commit or expose this value. Configure `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` on the API host; the API does not use a
   service-role key.
4. In IBKR Client Portal, create a Flex Query with the required accounts,
   positions, trades, and dividend sections, and configure its output as XML.
   Do not share the token or Query ID in an issue, log, or source file.
5. Sign in with an approved StockScanner account, select a PIP portfolio, save a
   named Flex connection, and choose **Sync statement**. The browser sends the
   credentials only to the authenticated API; the Edge Function stores them in
   Vault and retrieves statements on demand. The API validates the XML and
   persists masked account and normalized portfolio data using the caller's
   Supabase JWT and owner RLS.

Each user can manage multiple named Flex connections and each connection can
return multiple IBKR accounts. Account IDs are masked for display and a
non-display fingerprint distinguishes accounts that happen to share the same
last four digits. Each Flex response is limited to 5 MB and 10,000 normalized
records; the Edge Function enforces IBKR's per-token request limits.

If sync fails, check that the user is approved, the portfolio and connection
belong to that user, the matching internal keys are configured, and the Flex
Query returns XML. Credentials are cleared from the browser form after every
save attempt. They are never returned by the API, stored in browser storage, or
written to audit events. Do not log request URLs to IBKR because the Flex token
is a query parameter in the upstream protocol.

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
