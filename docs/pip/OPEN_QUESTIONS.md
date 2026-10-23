# PIP Open Questions

- **Sell Score weights:** supplied components total 115%. Current code preserves
  each weight and normalizes by the total. See `SCORING.md` for the maintainer
  decision.
- **Portfolio policy:** confirm default review thresholds, replacement minimum
  score gap, and concentration cap before making recommendations user-facing.
- **Data cadence:** confirm how often CSV/Flex imports and historical snapshots
  should be refreshed; no automatic or live sync is enabled.
- **Approval retention:** confirm audit retention and who may review an account's
  approval history. The current schema scopes access to the approved portfolio
  owner and leaves the audit log append-only for that user.
- **External order execution:** not implemented. Any future integration must be
  disabled by default, require explicit human approval, and never execute in CI
  or tests.
- **Financial-data quality:** choose trusted sources and freshness requirements
  for dividend sustainability, earnings growth, analyst revisions, and target
  prices before relying on the scores.
