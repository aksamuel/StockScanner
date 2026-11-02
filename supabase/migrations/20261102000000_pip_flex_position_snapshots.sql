-- Replace only complete, owner-scoped Flex position snapshots. CSV/manual
-- positions and transaction/dividend history are not part of this operation.

CREATE TABLE IF NOT EXISTS public.pip_flex_position_snapshots (
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES public.ibkr_accounts(id) ON DELETE CASCADE,
    statement_date DATE NOT NULL,
    sync_started_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (portfolio_id, account_id)
);

DROP TRIGGER IF EXISTS pip_set_updated_at ON public.pip_flex_position_snapshots;
CREATE TRIGGER pip_set_updated_at
    BEFORE UPDATE ON public.pip_flex_position_snapshots
    FOR EACH ROW EXECUTE FUNCTION public.pip_set_updated_at();

ALTER TABLE public.pip_flex_position_snapshots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.pip_flex_position_snapshots FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE ON public.pip_flex_position_snapshots TO authenticated;

DROP POLICY IF EXISTS "PIP owners manage Flex snapshots" ON public.pip_flex_position_snapshots;
CREATE POLICY "PIP owners manage Flex snapshots" ON public.pip_flex_position_snapshots
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.ibkr_accounts AS a
            JOIN public.portfolios AS p ON p.id = a.portfolio_id
            JOIN public.user_access AS ua ON ua.user_id = p.user_id
            WHERE a.id = pip_flex_position_snapshots.account_id
              AND a.portfolio_id = pip_flex_position_snapshots.portfolio_id
              AND p.user_id = (SELECT auth.uid())
              AND ua.status = 'approved'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.ibkr_accounts AS a
            JOIN public.portfolios AS p ON p.id = a.portfolio_id
            JOIN public.user_access AS ua ON ua.user_id = p.user_id
            WHERE a.id = pip_flex_position_snapshots.account_id
              AND a.portfolio_id = pip_flex_position_snapshots.portfolio_id
              AND p.user_id = (SELECT auth.uid())
              AND ua.status = 'approved'
        )
    );

CREATE OR REPLACE FUNCTION public.pip_replace_flex_positions(
    p_portfolio_id UUID,
    p_accounts JSONB,
    p_positions JSONB,
    p_sync_started_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    matched_accounts INTEGER;
    saved_positions INTEGER;
BEGIN
    IF auth.uid() IS NULL OR NOT EXISTS (
        SELECT 1
        FROM public.portfolios AS p
        JOIN public.user_access AS ua ON ua.user_id = p.user_id
        WHERE p.id = p_portfolio_id
          AND p.user_id = auth.uid()
          AND ua.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Approved portfolio ownership required' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_accounts) IS DISTINCT FROM 'array'
       OR jsonb_typeof(p_positions) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Invalid Flex snapshot' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_accounts) NOT BETWEEN 1 AND 10000
       OR jsonb_array_length(p_positions) > 10000
       OR p_sync_started_at IS NULL
       OR p_sync_started_at > now() + INTERVAL '5 minutes' THEN
        RAISE EXCEPTION 'Invalid Flex snapshot' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_accounts) AS a(item)
        WHERE jsonb_typeof(a.item) IS DISTINCT FROM 'object'
           OR COALESCE(a.item ->> 'account_fingerprint', '') !~ '^[0-9a-f]{64}$'
           OR COALESCE(a.item ->> 'statement_date', '') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    ) OR (
        SELECT count(DISTINCT a.item ->> 'account_fingerprint')
        FROM jsonb_array_elements(p_accounts) AS a(item)
    ) <> jsonb_array_length(p_accounts) THEN
        RAISE EXCEPTION 'Invalid Flex snapshot accounts' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_accounts) AS a(item)
        WHERE (a.item ->> 'statement_date')::DATE > (now() AT TIME ZONE 'UTC')::DATE + 1
    ) THEN
        RAISE EXCEPTION 'Invalid Flex statement date' USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('pip:flex-positions:' || p_portfolio_id::TEXT, 0));

    SELECT count(*) INTO matched_accounts
    FROM jsonb_array_elements(p_accounts) AS input(item)
    JOIN public.ibkr_accounts AS a
      ON a.portfolio_id = p_portfolio_id
     AND a.account_fingerprint = input.item ->> 'account_fingerprint';
    IF matched_accounts <> jsonb_array_length(p_accounts) THEN
        RAISE EXCEPTION 'Flex snapshot account not found' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_accounts) AS input(item)
        JOIN public.ibkr_accounts AS a
          ON a.portfolio_id = p_portfolio_id
         AND a.account_fingerprint = input.item ->> 'account_fingerprint'
        JOIN public.pip_flex_position_snapshots AS snapshot
          ON snapshot.portfolio_id = p_portfolio_id AND snapshot.account_id = a.id
        WHERE snapshot.statement_date > (input.item ->> 'statement_date')::DATE
           OR (
               snapshot.statement_date = (input.item ->> 'statement_date')::DATE
               AND snapshot.sync_started_at > p_sync_started_at
           )
    ) THEN
        RAISE EXCEPTION 'A newer Flex snapshot is already saved' USING ERRCODE = 'PPS01';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_positions) AS input(item)
        WHERE jsonb_typeof(input.item) IS DISTINCT FROM 'object'
           OR input.item ->> 'portfolio_id' IS DISTINCT FROM p_portfolio_id::TEXT
           OR input.item -> 'metadata' ->> 'source' IS DISTINCT FROM 'ibkr_flex'
           OR COALESCE(input.item ->> 'symbol', '') !~ '^[A-Z0-9][A-Z0-9.-]{0,29}$'
           OR COALESCE(input.item ->> 'currency', '') !~ '^[A-Z]{3}$'
           OR COALESCE(input.item ->> 'source_key', '') = ''
           OR input.item ->> 'quantity' IS NULL
           OR NOT EXISTS (
               SELECT 1
               FROM public.ibkr_accounts AS a
               JOIN jsonb_array_elements(p_accounts) AS account_input(item)
                 ON a.account_fingerprint = account_input.item ->> 'account_fingerprint'
               WHERE a.portfolio_id = p_portfolio_id
                 AND a.id::TEXT = input.item ->> 'account_id'
                 AND a.account_fingerprint = input.item -> 'metadata' ->> 'account_fingerprint'
           )
    ) OR (
        SELECT count(DISTINCT input.item ->> 'source_key')
        FROM jsonb_array_elements(p_positions) AS input(item)
    ) <> jsonb_array_length(p_positions) THEN
        RAISE EXCEPTION 'Invalid Flex snapshot positions' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.positions AS existing
        JOIN jsonb_array_elements(p_positions) AS input(item)
          ON existing.source_key = input.item ->> 'source_key'
        WHERE existing.portfolio_id = p_portfolio_id
          AND (
              existing.metadata ->> 'source' IS DISTINCT FROM 'ibkr_flex'
              OR NOT COALESCE(
                  existing.metadata ->> 'account_fingerprint'
                      = input.item -> 'metadata' ->> 'account_fingerprint'
                  OR (
                      existing.metadata ->> 'account_fingerprint' IS NULL
                      AND existing.account_id::TEXT = input.item ->> 'account_id'
                  ),
                  FALSE
              )
          )
    ) THEN
        RAISE EXCEPTION 'Flex position conflicts with another import' USING ERRCODE = '22023';
    END IF;

    DELETE FROM public.positions AS existing
    WHERE existing.portfolio_id = p_portfolio_id
      AND existing.metadata ->> 'source' = 'ibkr_flex'
      AND (
          existing.metadata ->> 'account_fingerprint' IN (
              SELECT input.item ->> 'account_fingerprint'
              FROM jsonb_array_elements(p_accounts) AS input(item)
          )
          OR (
              existing.metadata ->> 'account_fingerprint' IS NULL
              AND existing.account_id IN (
                  SELECT a.id
                  FROM public.ibkr_accounts AS a
                  JOIN jsonb_array_elements(p_accounts) AS input(item)
                    ON a.account_fingerprint = input.item ->> 'account_fingerprint'
                  WHERE a.portfolio_id = p_portfolio_id
              )
          )
      )
      AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(p_positions) AS input(item)
          WHERE input.item ->> 'source_key' = existing.source_key
      );

    INSERT INTO public.positions (
        portfolio_id, account_id, symbol, quantity, average_cost, market_price,
        market_value, cost_basis, currency, source_key, entry_date, last_updated, metadata
    )
    SELECT
        p_portfolio_id,
        (input.item ->> 'account_id')::UUID,
        input.item ->> 'symbol',
        (input.item ->> 'quantity')::NUMERIC,
        NULLIF(input.item ->> 'average_cost', '')::NUMERIC,
        NULLIF(input.item ->> 'market_price', '')::NUMERIC,
        NULLIF(input.item ->> 'market_value', '')::NUMERIC,
        NULLIF(input.item ->> 'cost_basis', '')::NUMERIC,
        input.item ->> 'currency',
        input.item ->> 'source_key',
        NULLIF(input.item ->> 'entry_date', '')::TIMESTAMPTZ,
        COALESCE(NULLIF(input.item ->> 'last_updated', '')::TIMESTAMPTZ, now()),
        input.item -> 'metadata'
    FROM jsonb_array_elements(p_positions) AS input(item)
    ON CONFLICT (portfolio_id, source_key) DO UPDATE SET
        account_id = EXCLUDED.account_id,
        symbol = EXCLUDED.symbol,
        quantity = EXCLUDED.quantity,
        average_cost = EXCLUDED.average_cost,
        market_price = EXCLUDED.market_price,
        market_value = EXCLUDED.market_value,
        cost_basis = EXCLUDED.cost_basis,
        currency = EXCLUDED.currency,
        entry_date = EXCLUDED.entry_date,
        last_updated = EXCLUDED.last_updated,
        metadata = EXCLUDED.metadata;
    GET DIAGNOSTICS saved_positions = ROW_COUNT;

    INSERT INTO public.pip_flex_position_snapshots (
        portfolio_id, account_id, statement_date, sync_started_at
    )
    SELECT p_portfolio_id, a.id, (input.item ->> 'statement_date')::DATE, p_sync_started_at
    FROM jsonb_array_elements(p_accounts) AS input(item)
    JOIN public.ibkr_accounts AS a
      ON a.portfolio_id = p_portfolio_id
     AND a.account_fingerprint = input.item ->> 'account_fingerprint'
    ON CONFLICT (portfolio_id, account_id) DO UPDATE SET
        statement_date = EXCLUDED.statement_date,
        sync_started_at = EXCLUDED.sync_started_at;

    RETURN saved_positions;
END;
$$;

REVOKE ALL ON FUNCTION public.pip_replace_flex_positions(UUID, JSONB, JSONB, TIMESTAMPTZ)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.pip_replace_flex_positions(UUID, JSONB, JSONB, TIMESTAMPTZ)
    TO authenticated;
