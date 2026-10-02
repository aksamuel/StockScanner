import { collectEvidence, normalizeSymbol } from './core.mjs';

export function createCatalystHandler({ createClient, env, collect = collectEvidence, clock = () => new Date() }) {
  return async request => {
    const origin = request.headers.get('origin');
    const allowed = new Set(['https://aksamuel.github.io', 'http://localhost:8000', 'http://127.0.0.1:8000']);
    const headers = { 'Content-Type': 'application/json', 'Cache-Control': 'private, no-store', Vary: 'Origin',
      'Access-Control-Allow-Origin': allowed.has(origin) ? origin : 'https://aksamuel.github.io',
      'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
      'Access-Control-Allow-Methods': 'POST, OPTIONS' };
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers });
    if (origin && !allowed.has(origin)) return json({ error: 'Origin not allowed.' }, 403);
    if (request.method === 'OPTIONS') return new Response('ok', { headers });
    if (request.method !== 'POST') return json({ error: 'POST required.' }, 405);
    const authorization = request.headers.get('authorization');
    if (!authorization?.startsWith('Bearer ')) return json({ error: 'Sign in first.' }, 401);
    try {
      let key = env('SUPABASE_ANON_KEY');
      try { key = JSON.parse(env('SUPABASE_PUBLISHABLE_KEYS') || '{}').default || key; } catch { /* fallback */ }
      const client = createClient(env('SUPABASE_URL'), key, {
        global: { headers: { Authorization: authorization } }, auth: { persistSession: false, autoRefreshToken: false },
      });
      const { data: { user }, error } = await client.auth.getUser();
      if (error || !user) return json({ error: 'Sign in first.' }, 401);
      const { data: access, error: accessError } = await client.from('user_access').select('status').eq('user_id', user.id).maybeSingle();
      if (accessError || access?.status !== 'approved') return json({ error: 'Approved access required.' }, 403);
      const text = await request.text();
      if (text.length > 500) return json({ error: 'Request too large.' }, 400);
      let symbol;
      try { symbol = normalizeSymbol(JSON.parse(text).symbol); } catch { return json({ error: 'Enter a valid NYSE ticker.' }, 400); }
      // Only after authenticating and checking approval may the backend key be used.
      let secret = env('SUPABASE_SERVICE_ROLE_KEY');
      try { secret = JSON.parse(env('SUPABASE_SECRET_KEYS') || '{}').default || secret; } catch { /* fallback */ }
      const backend = createClient(env('SUPABASE_URL'), secret, { auth: { persistSession: false, autoRefreshToken: false } });
      const { data: issuer, error: issuerError } = await backend.from('nyse_tickers').select('symbol,exchange')
        .eq('symbol', symbol).maybeSingle();
      if (issuerError) return json({ error: 'NYSE universe is unavailable.' }, 503);
      if (!issuer || !['NYQ', 'NYSE', 'N'].includes(issuer.exchange)) return json({ error: 'Ticker is not in the current NYSE universe.' }, 400);
      const { data: cached, error: cacheError } = await backend.from('catalyst_beta_cache').select('*').eq('symbol', symbol).maybeSingle();
      if (cacheError) return json({ error: 'Beta storage is unavailable.' }, 503);
      if (cached && clock().getTime() - Date.parse(cached.collected_at) < 3600000) return json({ ...cached.payload, cached: true });
      // Atomic, database-backed global + per-user throttle across function instances.
      const { data: granted, error: rateError } = await backend.rpc('claim_catalyst_beta_refresh', { p_user: user.id });
      if (rateError || !granted) return json({ error: 'Refresh is busy. Retry in 15 seconds; cached results remain visible.' }, 429);
      let payload;
      try { payload = await collect(symbol, { now: clock(), userAgent: env('SEC_USER_AGENT') || undefined }); }
      catch (e) { return json({ error: e.message, previous: cached?.payload || null }, 502); }
      const { error: saveError } = await backend.from('catalyst_beta_cache').upsert({ symbol,
        collected_at: payload.collected_at, payload }, { onConflict: 'symbol' });
      if (saveError) return json({ error: 'Evidence collected but could not be saved. Please retry.' }, 503);
      return json(payload);
    } catch { return json({ error: 'Beta service is temporarily unavailable. Existing scanner is unaffected.' }, 503); }
  };
}
