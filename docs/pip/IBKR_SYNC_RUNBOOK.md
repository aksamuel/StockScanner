# IBKR Sync Runbook

PIP's current sync path is read-only. It accepts an offline fixture or a local
IBKR CSV/Flex export through `CSVPortfolioDataSource`; it does not authenticate
to IBKR or make network requests. Tests use recorded fixture sources only.

1. Export the existing holdings/Flex CSV locally from IBKR.
2. Pass the file to `CSVPortfolioDataSource(path)` and call
   `IBKRPortfolioSyncService(SupabasePortfolioRepository(server_client)).sync(source, portfolio_id)`
   from a server-side integration.
3. Validate normalized symbols, quantities, dates, currencies, and row counts
   before persisting through a server-side repository.
4. Compare the PIP output with existing `user_portfolio_holdings`; do not replace,
   delete, or otherwise alter those existing imports.
5. Review ingestion errors without printing source rows. Raw IBKR account
   identifiers are reduced to a masked suffix; credentials and tokens must never
   be included in portfolio metadata, logs, or audit data.

If live Flex retrieval is introduced later, keep its token in Supabase secrets or
an environment variable, not a table, fixture, source file, or log. Live network
retrieval is not enabled by this implementation.
