-- PostgreSQL limits regex repetition bounds to 255. Validate the token's
-- length separately so the documented 256-character maximum works.
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
    IF p_token IS NULL
       OR length(p_token) NOT BETWEEN 1 AND 256
       OR p_token !~ '^[-A-Za-z0-9._~]+$' THEN
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

REVOKE ALL ON FUNCTION public.pip_flex_store_connection(UUID, UUID, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.pip_flex_store_connection(UUID, UUID, TEXT, TEXT, TEXT)
    TO service_role;
