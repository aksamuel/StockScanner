-- Additive Portfolio Intelligence Platform schema. Existing scanner and import
-- tables remain unchanged; Auth identities and approval state are reused.

CREATE TABLE IF NOT EXISTS public.pip_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
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
    masked_account_id TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ibkr_accounts_portfolio_masked_id_key UNIQUE (portfolio_id, masked_account_id)
);

CREATE INDEX IF NOT EXISTS idx_ibkr_accounts_portfolio_id ON public.ibkr_accounts(portfolio_id);

CREATE TABLE IF NOT EXISTS public.positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.ibkr_accounts(id) ON DELETE SET NULL,
    symbol TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    average_cost NUMERIC,
    market_price NUMERIC,
    market_value NUMERIC,
    cost_basis NUMERIC,
    currency TEXT NOT NULL DEFAULT 'USD',
    source_key TEXT NOT NULL,
    entry_date TIMESTAMPTZ,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT positions_portfolio_source_key UNIQUE (portfolio_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_positions_portfolio_symbol ON public.positions(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_positions_account_id ON public.positions(account_id);
CREATE INDEX IF NOT EXISTS idx_positions_source_key ON public.positions(portfolio_id, source_key);

CREATE TABLE IF NOT EXISTS public.transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    price NUMERIC,
    trade_date TIMESTAMPTZ NOT NULL,
    source_key TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT transactions_portfolio_source_key UNIQUE (portfolio_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_transactions_portfolio_symbol ON public.transactions(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_transactions_trade_date ON public.transactions(portfolio_id, trade_date);

CREATE TABLE IF NOT EXISTS public.dividends (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    dividend_amount NUMERIC NOT NULL DEFAULT 0,
    ex_date DATE,
    pay_date DATE,
    source_key TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT dividends_portfolio_source_key UNIQUE (portfolio_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_dividends_portfolio_symbol ON public.dividends(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_dividends_pay_date ON public.dividends(portfolio_id, pay_date);

CREATE TABLE IF NOT EXISTS public.daily_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    price NUMERIC,
    market_value NUMERIC,
    score NUMERIC,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT daily_snapshots_portfolio_symbol_date_key UNIQUE (portfolio_id, symbol, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_snapshots_portfolio_symbol ON public.daily_snapshots(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_daily_snapshots_date ON public.daily_snapshots(portfolio_id, snapshot_date);

CREATE TABLE IF NOT EXISTS public.analyst_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    analyst_rating TEXT,
    target_price NUMERIC,
    target_upside NUMERIC,
    revisions NUMERIC,
    signal_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analyst_signals_portfolio_symbol ON public.analyst_signals(portfolio_id, symbol);
CREATE INDEX IF NOT EXISTS idx_analyst_signals_date ON public.analyst_signals(portfolio_id, signal_date);

CREATE TABLE IF NOT EXISTS public.stock_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    cps NUMERIC,
    sell_score NUMERIC,
    tsr NUMERIC,
    relative_performance NUMERIC,
    dividend_growth NUMERIC,
    earnings_growth NUMERIC,
    analyst_revisions NUMERIC,
    dividend_quality NUMERIC,
    technical_health NUMERIC,
    opportunity_cost NUMERIC,
    revisions NUMERIC,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT stock_scores_portfolio_symbol_key UNIQUE (portfolio_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_stock_scores_portfolio_symbol ON public.stock_scores(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.sell_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    score NUMERIC,
    recommendation TEXT NOT NULL,
    rationale JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sell_recommendations_portfolio_symbol ON public.sell_recommendations(portfolio_id, symbol);

CREATE TABLE IF NOT EXISTS public.replacement_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    current_symbol TEXT NOT NULL,
    candidate_symbol TEXT NOT NULL,
    score NUMERIC,
    expected_benefit NUMERIC,
    confidence NUMERIC,
    rationale JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT replacement_candidates_portfolio_symbols_key UNIQUE (portfolio_id, current_symbol, candidate_symbol)
);

CREATE INDEX IF NOT EXISTS idx_replacement_candidates_portfolio_symbol ON public.replacement_candidates(portfolio_id, current_symbol);

CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    entity_type TEXT NOT NULL,
    entity_id UUID,
    event_type TEXT NOT NULL,
    event_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_portfolio_id ON public.audit_logs(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_type ON public.audit_logs(entity_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON public.audit_logs(portfolio_id, created_at);

CREATE OR REPLACE FUNCTION public.pip_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'pip_profiles', 'portfolios', 'ibkr_accounts', 'positions', 'transactions',
        'dividends', 'daily_snapshots', 'analyst_signals', 'stock_scores',
        'sell_recommendations', 'replacement_candidates', 'audit_logs'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', 'pip_set_updated_at', table_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.pip_set_updated_at()',
            'pip_set_updated_at', table_name
        );
    END LOOP;
END;
$$;

ALTER TABLE public.pip_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ibkr_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dividends ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analyst_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stock_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sell_recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.replacement_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.pip_profiles, public.portfolios, public.ibkr_accounts, public.positions,
    public.transactions, public.dividends, public.daily_snapshots, public.analyst_signals,
    public.stock_scores, public.sell_recommendations, public.replacement_candidates,
    public.audit_logs FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.pip_profiles, public.portfolios,
    public.ibkr_accounts, public.positions, public.transactions, public.dividends,
    public.daily_snapshots, public.analyst_signals, public.stock_scores,
    public.sell_recommendations, public.replacement_candidates TO authenticated;
GRANT SELECT, INSERT ON public.audit_logs TO authenticated;
GRANT ALL ON public.pip_profiles, public.portfolios, public.ibkr_accounts, public.positions,
    public.transactions, public.dividends, public.daily_snapshots, public.analyst_signals,
    public.stock_scores, public.sell_recommendations, public.replacement_candidates,
    public.audit_logs TO service_role;
REVOKE UPDATE, DELETE ON public.audit_logs FROM anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.audit_logs TO service_role;

DROP POLICY IF EXISTS "PIP users read own profile" ON public.pip_profiles;
CREATE POLICY "PIP users read own profile" ON public.pip_profiles
    FOR SELECT TO authenticated
    USING (id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ));
DROP POLICY IF EXISTS "PIP users create own profile" ON public.pip_profiles;
CREATE POLICY "PIP users create own profile" ON public.pip_profiles
    FOR INSERT TO authenticated
    WITH CHECK (id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ));
DROP POLICY IF EXISTS "PIP users update own profile" ON public.pip_profiles;
CREATE POLICY "PIP users update own profile" ON public.pip_profiles
    FOR UPDATE TO authenticated
    USING (id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ))
    WITH CHECK (id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ));
DROP POLICY IF EXISTS "PIP users delete own profile" ON public.pip_profiles;
CREATE POLICY "PIP users delete own profile" ON public.pip_profiles
    FOR DELETE TO authenticated
    USING (id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ));

DROP POLICY IF EXISTS "PIP users manage own portfolios" ON public.portfolios;
CREATE POLICY "PIP users manage own portfolios" ON public.portfolios
    FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ))
    WITH CHECK (user_id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.user_access
        WHERE user_id = (SELECT auth.uid()) AND status = 'approved'
    ));

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'ibkr_accounts', 'positions', 'transactions', 'dividends', 'daily_snapshots',
        'analyst_signals', 'stock_scores', 'sell_recommendations', 'replacement_candidates'
    ]
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'PIP owners manage ' || table_name, table_name);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO authenticated
             USING (EXISTS (
                 SELECT 1 FROM public.portfolios p
                 WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
                   AND EXISTS (SELECT 1 FROM public.user_access ua
                               WHERE ua.user_id = (SELECT auth.uid()) AND ua.status = ''approved'')
             ))
             WITH CHECK (EXISTS (
                 SELECT 1 FROM public.portfolios p
                 WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
                   AND EXISTS (SELECT 1 FROM public.user_access ua
                               WHERE ua.user_id = (SELECT auth.uid()) AND ua.status = ''approved'')
             ))',
            'PIP owners manage ' || table_name, table_name
        );
    END LOOP;
END;
$$;

DROP POLICY IF EXISTS "PIP owners read audit logs" ON public.audit_logs;
CREATE POLICY "PIP owners read audit logs" ON public.audit_logs
    FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.portfolios p
        WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
          AND EXISTS (SELECT 1 FROM public.user_access ua
                      WHERE ua.user_id = (SELECT auth.uid()) AND ua.status = 'approved')
    ));
DROP POLICY IF EXISTS "PIP owners append audit logs" ON public.audit_logs;
CREATE POLICY "PIP owners append audit logs" ON public.audit_logs
    FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT auth.uid()) AND EXISTS (
        SELECT 1 FROM public.portfolios p
        WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
          AND EXISTS (SELECT 1 FROM public.user_access ua
                      WHERE ua.user_id = (SELECT auth.uid()) AND ua.status = 'approved')
    ));

COMMENT ON TABLE public.pip_profiles IS
    'Optional PIP metadata keyed directly to auth.users; user access status remains in public.user_access.';
COMMENT ON COLUMN public.ibkr_accounts.masked_account_id IS
    'Optional masked identifier only; never store a raw account number, credential, or token.';
COMMENT ON TABLE public.audit_logs IS
    'Append-only, owner-scoped PIP audit history; authenticated users have no update/delete policies.';
