# IBKR Sync Runbook

PIP's current sync path is read-only. It accepts an offline fixture or a local
IBKR CSV/Flex export through `CSVPortfolioDataSource`; it does not authenticate
to IBKR or make network requests. The authenticated API exposes the same
normalizer for explicit browser-uploaded CSV/Flex files.

1. Export the existing holdings/Flex CSV locally from IBKR.
2. From the Portfolio Intelligence page, choose the target portfolio and
   explicitly import the CSV. The API validates and persists normalized records
   through the caller's Supabase JWT and owner RLS.
3. Validate normalized symbols, quantities, dates, currencies, and row counts
   before persisting through a server-side repository.
4. Compare the PIP output with existing `user_portfolio_holdings`; do not replace,
   delete, or otherwise alter those existing imports.
5. Review ingestion errors without printing source rows. Raw IBKR account
   identifiers are reduced to a masked suffix; credentials and tokens must never
   be included in portfolio metadata, logs, or audit data.

The browser/API upload limit is 1 MB and 1,000 data rows. Existing scanner
portfolio imports are not modified by this PIP import path.

If live Flex retrieval is introduced later, keep its token in Supabase secrets or
an environment variable, not a table, fixture, source file, or log. Live network
retrieval is not enabled by this implementation.
