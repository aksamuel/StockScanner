-- Approval transitions and their audit event are one atomic, authenticated
-- operation. The API never receives a Supabase service-role credential.

REVOKE UPDATE, DELETE ON public.sell_recommendations FROM anon, authenticated;
REVOKE INSERT ON public.audit_logs FROM anon, authenticated;

DROP POLICY IF EXISTS "PIP owners append audit logs" ON public.audit_logs;
DROP POLICY IF EXISTS "PIP owners manage sell_recommendations" ON public.sell_recommendations;
CREATE POLICY "PIP owners manage sell_recommendations" ON public.sell_recommendations
    FOR ALL TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.portfolios p
        WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
          AND EXISTS (SELECT 1 FROM public.user_access ua
                      WHERE ua.user_id = (SELECT auth.uid()) AND ua.status = 'approved')
    ))
    WITH CHECK (
        status = 'draft' AND approved_by IS NULL AND EXISTS (
            SELECT 1 FROM public.portfolios p
            WHERE p.id = portfolio_id AND p.user_id = (SELECT auth.uid())
              AND EXISTS (SELECT 1 FROM public.user_access ua
                          WHERE ua.user_id = (SELECT auth.uid()) AND ua.status = 'approved')
        )
    );

ALTER TABLE public.sell_recommendations
    ADD CONSTRAINT pip_approval_requires_approver
    CHECK (status NOT IN ('approved', 'submitted') OR approved_by IS NOT NULL);

CREATE OR REPLACE FUNCTION public.pip_transition_sell_recommendation(
    p_recommendation_id UUID,
    p_expected_status TEXT,
    p_next_status TEXT,
    p_actor TEXT,
    p_reason TEXT
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    current_portfolio_id UUID;
    current_status TEXT;
    current_user_id UUID := auth.uid();
    transition_allowed BOOLEAN := FALSE;
BEGIN
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication is required' USING ERRCODE = '42501';
    END IF;

    SELECT r.portfolio_id, r.status
    INTO current_portfolio_id, current_status
    FROM public.sell_recommendations AS r
    WHERE r.id = p_recommendation_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Recommendation not found' USING ERRCODE = 'P0002';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.portfolios AS p
        JOIN public.user_access AS ua ON ua.user_id = p.user_id
        WHERE p.id = current_portfolio_id
          AND p.user_id = current_user_id
          AND ua.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Approved portfolio ownership is required' USING ERRCODE = '42501';
    END IF;

    IF p_expected_status IS NULL THEN
        transition_allowed := current_status = 'draft' AND p_next_status = 'proposed';
    ELSE
        transition_allowed := current_status = p_expected_status AND (
            (p_expected_status = 'proposed' AND p_next_status IN ('under_review', 'cancelled', 'expired'))
            OR (p_expected_status = 'under_review' AND p_next_status IN ('approved', 'rejected', 'escalated', 'cancelled', 'expired'))
            OR (p_expected_status = 'approved' AND p_next_status IN ('submitted', 'escalated', 'cancelled'))
            OR (p_expected_status = 'escalated' AND p_next_status IN ('under_review', 'approved', 'rejected', 'cancelled', 'expired'))
        );
    END IF;

    IF NOT transition_allowed THEN
        RAISE EXCEPTION 'Invalid approval transition' USING ERRCODE = '23514';
    END IF;
    IF p_next_status = 'approved' AND (
        NULLIF(btrim(p_actor), '') IS NULL OR NULLIF(btrim(p_reason), '') IS NULL
    ) THEN
        RAISE EXCEPTION 'Explicit human approval requires an actor and reason' USING ERRCODE = '23514';
    END IF;

    UPDATE public.sell_recommendations
    SET status = p_next_status,
        approved_by = CASE WHEN p_next_status = 'approved' THEN current_user_id ELSE approved_by END
    WHERE id = p_recommendation_id;

    INSERT INTO public.audit_logs (
        portfolio_id,
        user_id,
        entity_type,
        entity_id,
        event_type,
        event_details
    )
    VALUES (
        current_portfolio_id,
        current_user_id,
        'sell_recommendation',
        p_recommendation_id,
        'approval_transition',
        jsonb_build_object(
            'from_status', p_expected_status,
            'to_status', p_next_status,
            'actor', p_actor,
            'reason', p_reason
        )
    );

    RETURN p_next_status;
END;
$$;

REVOKE ALL ON FUNCTION public.pip_transition_sell_recommendation(UUID, TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.pip_transition_sell_recommendation(UUID, TEXT, TEXT, TEXT, TEXT)
    TO authenticated;

COMMENT ON FUNCTION public.pip_transition_sell_recommendation(UUID, TEXT, TEXT, TEXT, TEXT) IS
    'Atomically changes an owner-approved PIP recommendation state and appends its audit event; records auth.uid() as approver.';
