-- Store each user's IBKR Flex credentials in Vault and expose only narrow,
-- service-role RPCs to the authenticated Edge Function.

DO $$
BEGIN
    IF to_regclass('vault.secrets') IS NULL
       OR to_regclass('vault.decrypted_secrets') IS NULL
       OR to_regprocedure('vault.create_secret(text,text,text,uuid)') IS NULL
       OR to_regprocedure('vault.update_secret(uuid,text,text,text,uuid)') IS NULL THEN
        RAISE EXCEPTION 'Supabase Vault must be enabled before applying the PIP Flex migration';
    END IF;
END;
$$;

REVOKE ALL ON TABLE vault.secrets FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE vault.decrypted_secrets FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS public.pip_ibkr_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    connection_name TEXT NOT NULL,
    vault_secret_id UUID NOT NULL UNIQUE,
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pip_ibkr_connections_name_key
        UNIQUE (user_id, portfolio_id, connection_name),
    CONSTRAINT pip_ibkr_connections_name_check
        CHECK (
            length(btrim(connection_name)) BETWEEN 1 AND 80
            AND connection_name !~ '[[:cntrl:]]'
        )
);

CREATE INDEX IF NOT EXISTS idx_pip_ibkr_connections_owner
    ON public.pip_ibkr_connections(user_id, portfolio_id, created_at DESC);

ALTER TABLE public.pip_ibkr_connections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.pip_ibkr_connections FROM PUBLIC, anon, authenticated;
GRANT SELECT (id, user_id, portfolio_id, connection_name, last_synced_at, created_at)
    ON public.pip_ibkr_connections TO authenticated;
GRANT UPDATE (last_synced_at)
    ON public.pip_ibkr_connections TO authenticated;

DROP POLICY IF EXISTS "PIP users read own Flex connections" ON public.pip_ibkr_connections;
CREATE POLICY "PIP users read own Flex connections"
    ON public.pip_ibkr_connections
    FOR SELECT TO authenticated
    USING (
        user_id = (SELECT auth.uid())
        AND EXISTS (
            SELECT 1
            FROM public.portfolios AS p
            JOIN public.user_access AS ua ON ua.user_id = p.user_id
            WHERE p.id = portfolio_id
              AND p.user_id = (SELECT auth.uid())
              AND ua.status = 'approved'
        )
    );

DROP POLICY IF EXISTS "PIP users record own Flex sync time" ON public.pip_ibkr_connections;
CREATE POLICY "PIP users record own Flex sync time"
    ON public.pip_ibkr_connections
    FOR UPDATE TO authenticated
    USING (
        user_id = (SELECT auth.uid())
        AND EXISTS (
            SELECT 1
            FROM public.portfolios AS p
            JOIN public.user_access AS ua ON ua.user_id = p.user_id
            WHERE p.id = portfolio_id
              AND p.user_id = (SELECT auth.uid())
              AND ua.status = 'approved'
        )
    )
    WITH CHECK (
        user_id = (SELECT auth.uid())
        AND EXISTS (
            SELECT 1
            FROM public.portfolios AS p
            JOIN public.user_access AS ua ON ua.user_id = p.user_id
            WHERE p.id = portfolio_id
              AND p.user_id = (SELECT auth.uid())
              AND ua.status = 'approved'
        )
    );

CREATE TABLE IF NOT EXISTS public.pip_ibkr_flex_rate_limits (
    token_fingerprint TEXT NOT NULL,
    request_times TIMESTAMPTZ[] NOT NULL DEFAULT ARRAY[]::TIMESTAMPTZ[],
    PRIMARY KEY (token_fingerprint),
    CONSTRAINT pip_ibkr_flex_rate_limit_fingerprint_check
        CHECK (token_fingerprint ~ '^[0-9a-f]{64}$')
);

ALTER TABLE public.pip_ibkr_flex_rate_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.pip_ibkr_flex_rate_limits FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.pip_delete_ibkr_flex_secret()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    DELETE FROM vault.secrets WHERE id = OLD.vault_secret_id;
    RETURN OLD;
END;
$$;

REVOKE ALL ON FUNCTION public.pip_delete_ibkr_flex_secret() FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS pip_delete_ibkr_flex_secret ON public.pip_ibkr_connections;
CREATE TRIGGER pip_delete_ibkr_flex_secret
    BEFORE DELETE ON public.pip_ibkr_connections
    FOR EACH ROW EXECUTE FUNCTION public.pip_delete_ibkr_flex_secret();

CREATE OR REPLACE FUNCTION public.pip_flex_store_connection(
    p_user_id UUID,
    p_portfolio_id UUID,
    p_connection_name TEXT,
    p_token TEXT,
    p_query_id TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    connection_row public.pip_ibkr_connections%ROWTYPE;
    new_connection_id UUID;
    new_secret_id UUID;
    normalized_name TEXT;
    secret_payload TEXT;
BEGIN
    normalized_name := btrim(p_connection_name);
    IF p_user_id IS NULL
       OR p_portfolio_id IS NULL
       OR normalized_name IS NULL
       OR length(normalized_name) NOT BETWEEN 1 AND 80
       OR normalized_name ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'Invalid Flex connection details' USING ERRCODE = '22023';
    END IF;
    IF p_token IS NULL OR p_token !~ '^[-A-Za-z0-9._~]{1,256}$' THEN
        RAISE EXCEPTION 'Invalid Flex credentials' USING ERRCODE = '22023';
    END IF;
    IF p_query_id IS NULL OR p_query_id !~ '^[0-9]{1,20}$' THEN
        RAISE EXCEPTION 'Invalid Flex credentials' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.portfolios AS p
        JOIN public.user_access AS ua ON ua.user_id = p.user_id
        WHERE p.id = p_portfolio_id
          AND p.user_id = p_user_id
          AND ua.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Approved portfolio ownership is required' USING ERRCODE = '42501';
    END IF;

    secret_payload := jsonb_build_object('token', p_token, 'query_id', p_query_id)::TEXT;
    SELECT *
    INTO connection_row
    FROM public.pip_ibkr_connections AS c
    WHERE c.user_id = p_user_id
      AND c.portfolio_id = p_portfolio_id
      AND c.connection_name = normalized_name
    FOR UPDATE;

    IF FOUND THEN
        PERFORM vault.update_secret(
            connection_row.vault_secret_id,
            secret_payload,
            NULL,
            NULL
        );
        UPDATE public.pip_ibkr_connections
        SET last_synced_at = NULL
        WHERE id = connection_row.id;
        RETURN jsonb_build_object(
            'id', connection_row.id,
            'portfolio_id', p_portfolio_id,
            'connection_name', normalized_name,
            'last_synced_at', NULL,
            'created_at', connection_row.created_at
        );
    END IF;

    new_connection_id := gen_random_uuid();
    new_secret_id := vault.create_secret(
        secret_payload,
        'pip-flex-' || new_connection_id::TEXT,
        'PIP IBKR Flex connection credentials'
    );
    INSERT INTO public.pip_ibkr_connections (
        id,
        user_id,
        portfolio_id,
        connection_name,
        vault_secret_id
    )
    VALUES (
        new_connection_id,
        p_user_id,
        p_portfolio_id,
        normalized_name,
        new_secret_id
    )
    RETURNING * INTO connection_row;

    RETURN jsonb_build_object(
        'id', connection_row.id,
        'portfolio_id', connection_row.portfolio_id,
        'connection_name', connection_row.connection_name,
        'last_synced_at', connection_row.last_synced_at,
        'created_at', connection_row.created_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.pip_flex_get_connection(
    p_user_id UUID,
    p_connection_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    connection_row public.pip_ibkr_connections%ROWTYPE;
    secret_payload JSONB;
BEGIN
    SELECT c.*
    INTO connection_row
    FROM public.pip_ibkr_connections AS c
    JOIN public.portfolios AS p ON p.id = c.portfolio_id
    JOIN public.user_access AS ua ON ua.user_id = p.user_id
    WHERE c.id = p_connection_id
      AND c.user_id = p_user_id
      AND p.user_id = p_user_id
      AND ua.status = 'approved';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Flex connection not found' USING ERRCODE = 'P0002';
    END IF;

    SELECT s.decrypted_secret::JSONB
    INTO secret_payload
    FROM vault.decrypted_secrets AS s
    WHERE s.id = connection_row.vault_secret_id;
    IF NOT FOUND
       OR secret_payload->>'token' IS NULL
       OR secret_payload->>'query_id' IS NULL THEN
        RAISE EXCEPTION 'Flex credentials are unavailable' USING ERRCODE = 'P0002';
    END IF;

    RETURN jsonb_build_object(
        'id', connection_row.id,
        'portfolio_id', connection_row.portfolio_id,
        'token', secret_payload->>'token',
        'query_id', secret_payload->>'query_id'
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.pip_flex_delete_connection(
    p_user_id UUID,
    p_connection_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    DELETE FROM public.pip_ibkr_connections AS c
    USING public.portfolios AS p, public.user_access AS ua
    WHERE c.id = p_connection_id
      AND c.user_id = p_user_id
      AND p.id = c.portfolio_id
      AND p.user_id = p_user_id
      AND ua.user_id = p.user_id
      AND ua.status = 'approved';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Flex connection not found' USING ERRCODE = 'P0002';
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.pip_flex_reserve_request(
    p_user_id UUID,
    p_connection_id UUID,
    p_token_fingerprint TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    request_started_at TIMESTAMPTZ := clock_timestamp();
    request_times TIMESTAMPTZ[];
    recent_requests TIMESTAMPTZ[];
BEGIN
    IF p_token_fingerprint IS NULL OR p_token_fingerprint !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Invalid Flex rate-limit key' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.pip_ibkr_connections AS c
        JOIN public.portfolios AS p ON p.id = c.portfolio_id
        JOIN public.user_access AS ua ON ua.user_id = p.user_id
        WHERE c.id = p_connection_id
          AND c.user_id = p_user_id
          AND p.user_id = p_user_id
          AND ua.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Flex connection not found' USING ERRCODE = 'P0002';
    END IF;

    INSERT INTO public.pip_ibkr_flex_rate_limits (token_fingerprint)
    VALUES (p_token_fingerprint)
    ON CONFLICT (token_fingerprint) DO NOTHING;

    SELECT r.request_times
    INTO request_times
    FROM public.pip_ibkr_flex_rate_limits AS r
    WHERE r.token_fingerprint = p_token_fingerprint
    FOR UPDATE;

    SELECT COALESCE(
        array_agg(requested_at ORDER BY requested_at),
        ARRAY[]::TIMESTAMPTZ[]
    )
    INTO recent_requests
    FROM unnest(request_times) AS request_rows(requested_at)
    WHERE requested_at > request_started_at - INTERVAL '60 seconds';

    IF cardinality(recent_requests) >= 10
       OR (
           cardinality(recent_requests) > 0
           AND recent_requests[cardinality(recent_requests)] > request_started_at - INTERVAL '1 second'
       ) THEN
        RAISE EXCEPTION 'IBKR Flex request rate limit reached' USING ERRCODE = 'P4290';
    END IF;

    UPDATE public.pip_ibkr_flex_rate_limits
    SET request_times = array_append(recent_requests, request_started_at)
    WHERE token_fingerprint = p_token_fingerprint;
    RETURN TRUE;
END;
$$;

REVOKE ALL ON FUNCTION public.pip_flex_store_connection(UUID, UUID, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.pip_flex_get_connection(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.pip_flex_delete_connection(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.pip_flex_reserve_request(UUID, UUID, TEXT)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.pip_flex_store_connection(UUID, UUID, TEXT, TEXT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.pip_flex_get_connection(UUID, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.pip_flex_delete_connection(UUID, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.pip_flex_reserve_request(UUID, UUID, TEXT)
    TO service_role;

COMMENT ON TABLE public.pip_ibkr_connections IS
    'Owner-scoped IBKR Flex query references; credentials live in Supabase Vault and are never exposed by this table.';
COMMENT ON COLUMN public.pip_ibkr_connections.vault_secret_id IS
    'Private pointer to the Vault-encrypted Flex token and query ID; not selectable by authenticated users.';
COMMENT ON TABLE public.pip_ibkr_flex_rate_limits IS
    'Server-only, per-user hashed-token request timestamps for IBKR Flex Web Service rate-limit compliance.';
