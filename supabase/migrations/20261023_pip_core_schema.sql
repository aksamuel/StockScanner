-- Portfolio Intelligence Platform schema for StockScanner
-- Purpose: add modular analytics, recommendations, and trading approval support
-- while keeping the existing stock scanner tables and UI intact.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON public.portfolios(user_id);

CREATE TABLE IF NOT EXISTS public.ibkr_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    account_name TEXT NOT NULL,
    account_number TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ibkr_accounts_portfolio_id ON public.ibkr_accounts(portfolio_id);

CREATE TABLE IF NOT EXISTS public.positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.ibkr_accounts(id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    average_cost NUMERIC NOT NULL DEFAULT 0,
    market_price NUMERIC NOT NULL DEFAULT 0,
    market_value NUMERIC NOT NULL DEFAULT 0,
    cost_basis NUMERIC NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    entry_date TIMESTAMPTZ,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_positions_portfolio_symbol ON public.positions(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_positions_account_id ON public.positions(account_id);

CREATE TABLE IF NOT EXISTS public.transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    price NUMERIC NOT NULL DEFAULT 0,
    trade_date TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_transactions_portfolio_symbol ON public.transactions(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.dividends (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    dividend_amount NUMERIC NOT NULL DEFAULT 0,
    ex_date TIMESTAMPTZ,
    pay_date TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_dividends_portfolio_symbol ON public.dividends(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.daily_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    price NUMERIC NOT NULL DEFAULT 0,
    market_value NUMERIC NOT NULL DEFAULT 0,
    score NUMERIC,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (portfolio_id, symbol, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_snapshots_portfolio_symbol ON public.daily_snapshots(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.analyst_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol TEXT NOT NULL,
    analyst_rating TEXT,
    target_price NUMERIC,
    target_upside NUMERIC,
    revisions NUMERIC,
    signal_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_analyst_signals_symbol ON public.analyst_signals(symbol);

CREATE TABLE IF NOT EXISTS public.stock_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    cps NUMERIC NOT NULL DEFAULT 0,
    sell_score NUMERIC NOT NULL DEFAULT 0,
    tsr NUMERIC NOT NULL DEFAULT 0,
    relative_performance NUMERIC NOT NULL DEFAULT 0,
    dividend_growth NUMERIC NOT NULL DEFAULT 0,
    earnings_growth NUMERIC NOT NULL DEFAULT 0,
    analyst_revisions NUMERIC NOT NULL DEFAULT 0,
    dividend_quality NUMERIC NOT NULL DEFAULT 0,
    technical_health NUMERIC NOT NULL DEFAULT 0,
    opportunity_cost NUMERIC NOT NULL DEFAULT 0,
    revisions NUMERIC NOT NULL DEFAULT 0,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (portfolio_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_stock_scores_portfolio_symbol ON public.stock_scores(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.sell_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    recommendation TEXT NOT NULL,
    rationale JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by UUID REFERENCES public.users(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sell_recommendations_portfolio_symbol ON public.sell_recommendations(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.replacement_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    current_symbol TEXT NOT NULL,
    candidate_symbol TEXT NOT NULL,
    score NUMERIC NOT NULL DEFAULT 0,
    expected_benefit NUMERIC NOT NULL DEFAULT 0,
    confidence NUMERIC NOT NULL DEFAULT 0,
    rationale JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_replacement_candidates_portfolio_symbol ON public.replacement_candidates(portfolio_id, current_symbol);

CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID REFERENCES public.portfolios(id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL,
    entity_id UUID,
    event_type TEXT NOT NULL,
    event_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_portfolio_id ON public.audit_logs(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_type ON public.audit_logs(entity_type);
