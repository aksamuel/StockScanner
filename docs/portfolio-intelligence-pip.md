# Portfolio Intelligence Platform (PIP)

This document captures the implementation plan and architecture for the StockScanner portfolio intelligence layer.

## Objective
Add a modular portfolio intelligence layer to StockScanner without disturbing the current stock scanner discovery, reporting, and dashboard workflows.

## Scope
The PIP modules are additive and focused on:
- IBKR portfolio synchronization
- position lifecycle analysis
- score calculation and ranking
- dead money detection
- opportunity cost evaluation
- dividend and growth analysis
- replacement candidate generation
- sell recommendation advice
- approval workflow and audit trail

## Architectural direction
The existing StockScanner repository already has the correct core ingredients:
- data persistence via Supabase
- user and portfolio concepts
- market data ingestion
- report generation and dashboard conventions
- AI-assisted analysis and evaluation patterns

The PIP layer should therefore be implemented as an adjacent service layer rather than a rewrite of the core scanner.

## Recommended package layout
- `stockscanner/pip/__init__.py`
- `stockscanner/pip/models.py`
- `stockscanner/pip/scoring.py`
- `stockscanner/pip/ibkr_sync.py`
- `stockscanner/pip/replacement_engine.py`
- `stockscanner/pip/sell_advisor.py`
- `stockscanner/pip/approval_workflow.py`

## Planned module responsibilities
### 1. IBKR Portfolio Sync
Load IBKR positions, transactions, and account metadata into normalized forms suitable for scoring and analysis.

### 2. Position Lifecycle Analysis
Track entry dates, holding duration, cost basis, market value and age-related performance drift.

### 3. Dead Money Detector
Identify holdings with weak score quality, low expected upside, or persistent drag on portfolio productivity.

### 4. Opportunity Cost Engine
Compare current positions to alternative candidates and quantify the cost of keeping weak holdings.

### 5. Dividend Analysis
Evaluate dividend consistency, payout quality and dividend growth for the holding.

### 6. Growth Analysis
Measure earnings growth and growth quality relative to expectations and forward-looking fundamentals.

### 7. Forward Looking Analysis
Use expected future catalysts to inform confidence bands and risk-adjusted decision support.

### 8. Capital Productivity Score (CPS)
Formula:
- 40% TSR
- 20% Relative Performance vs SPY
- 15% Dividend Growth
- 15% Earnings Growth
- 10% Analyst Revisions

### 9. Sell Confidence Score
Formula:
- 20% TSR
- 20% Relative Performance
- 20% Revisions
- 15% Dividend Quality
- 15% Technical Health
- 10% Earnings Growth
- 15% Opportunity Cost

### 10. Replacement Candidate Engine
Generate replacement options that may produce stronger score quality and better capital efficiency.

### 11. Sell Advisor
Convert score outputs into clear recommendations such as `sell`, `watch`, or `hold` with supporting rationale.

### 12. Order Approval Workflow
Require review and auditability before a recommendation becomes an actionable decision.

## Supabase tables
The migration in `supabase/migrations/20261023_pip_core_schema.sql` creates:
- users
- portfolios
- ibkr_accounts
- positions
- transactions
- dividends
- daily_snapshots
- analyst_signals
- stock_scores
- sell_recommendations
- replacement_candidates
- audit_logs

## Decision quality guidance
The PIP layer helps by giving better evidence, not by guaranteeing a right decision. It is most useful when it answers:
- Why is this holding weak?
- What is the opportunity cost?
- What is the better alternative?
- How confident is the recommendation?
- Who reviewed and approved it?

## Recommended implementation sequence
1. Schema and normalization
2. IBKR sync and data ingestion
3. Position lifecycle
4. Analytics and score components
5. Candidate generation and recommendations
6. Approval workflow and audits
7. Tests and documentation

## Guardrails
- Do not modify the existing scanner logic in place.
- Treat an automated recommendation as advisory evidence, not certainty.
- Keep every recommendation tied to source data and audit records.
- Score calculations should be deterministic and versioned.
