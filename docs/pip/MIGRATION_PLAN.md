# PIP Supabase Migration Plan

## Findings and decisions

The existing schema already provides `auth.users`, approved-user status in
`public.user_access`, imported positions in `user_portfolio_holdings`, import
metadata in `user_portfolio_imports`, the `replace_my_portfolio_holdings` RPC, and
the scanner's singleton `price_snapshots`. `portfolio-signals` and
`portfolio-history` are authenticated screening/data functions. These objects
remain unchanged.

| Object | Action | Ownership/security |
| --- | --- | --- |
| `users` | Reuse `auth.users`; optional `pip_profiles` references it | No duplicate credentials, auth identity, or approval state |
| `portfolios` | Create | `user_id` references `auth.users`; owner must be approved |
| `ibkr_accounts` | Create | Portfolio-owned, masked account identifier only |
| `positions`, `transactions`, `dividends`, `daily_snapshots` | Create | Portfolio-owned and indexed by portfolio/symbol/date |
| `analyst_signals` | Create | Portfolio/user-owned; no cross-user client reads |
| `stock_scores`, `sell_recommendations`, `replacement_candidates` | Create | Portfolio-owned, RLS checked through the portfolio owner |
| `audit_logs` | Create | Owner-scoped append-only rows; no client update/delete policy |
| Existing import and market-price objects | Reuse as input only | No schema changes or destructive replacement |

Every new table must use `CREATE TABLE IF NOT EXISTS`, stable primary/foreign keys,
owner and symbol/date indexes, and `created_at`/`updated_at` timestamps. Constraints
added to already-created PIP tables must be guarded by dropping/re-adding their
named constraint or checking catalog state. Enable RLS on every PIP table.
Authenticated policies must check both `auth.uid()` ownership and an approved
`public.user_access` row. Service-role ingestion remains server-side; no service
role key belongs in browser code or fixtures.

Credentials and tokens must never be stored in PIP columns. Keep connection
configuration in environment variables or Supabase secrets. Account identifiers
must be masked in any persisted metadata, logs, and audit events. Audit history is append-only: authenticated owners can read events but cannot
insert, update, or delete them directly. The narrowly scoped approval RPC writes
each event atomically with the corresponding recommendation transition.

## Rollout order

1. Confirm the existing auth, approval, portfolio import, and price snapshot
   migrations are deployed.
2. Apply the additive PIP core schema migration; verify all requested tables,
   keys, timestamps, and indexes.
3. Apply/verify RLS policies and approval RPC grants as the authenticated owner, another approved user,
   a pending user, and an anonymous user. Confirm cross-owner operations fail.
4. Deploy the authenticated API with caller-token PostgREST access. Keep any IBKR live transport
   and order transmission absent.
5. Validate imported CSV/Flex records and reconcile PIP snapshots against the
   existing holdings import before enabling scheduled/manual ingestion.
6. Enable analytics and advisory recommendations after verifying missing-data
   confidence and audit records.
7. Retain the existing portfolio UI and scanner behavior throughout rollout; do
   not migrate or delete existing holdings/import rows as part of this release.

## Risks and rollback

- The existing data model is per-user imports; PIP's normalized records add a
  second representation. Treat imports as source data and use idempotent,
  portfolio-scoped upserts to avoid duplicates.
- `price_snapshots` does not contain a historical portfolio series. PIP
  `daily_snapshots` is separate and must not change scanner cache semantics.
- Policy mistakes could expose portfolio data. Test RLS with multiple owners
  before enabling client reads; default to no access when approval is absent.
- Roll back by disabling PIP entry points and stopping new ingestion. Preserve
  append-only audit evidence and all existing scanner/import tables.
