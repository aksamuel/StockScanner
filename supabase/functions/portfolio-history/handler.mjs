const allowedOrigins = new Set(["https://aksamuel.github.io", "http://localhost:8000", "http://127.0.0.1:8000"]);

export function parseHistory(payload, now = new Date()) {
  const result = payload?.chart?.result?.[0];
  const timestamps = result?.timestamp;
  const closes = result?.indicators?.adjclose?.[0]?.adjclose;
  if (!Array.isArray(timestamps) || !Array.isArray(closes)) return { points: [] };
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: result?.meta?.exchangeTimezoneName || "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit",
  });
  const dateValue = (date) => {
    const parts = Object.fromEntries(formatter.formatToParts(date).map(({ type, value }) => [type, value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const today = dateValue(now);
  const oldest = new Date(now);
  oldest.setUTCFullYear(oldest.getUTCFullYear() - 1);
  const firstDate = dateValue(oldest);
  const points = new Map();
  timestamps.forEach((timestamp, index) => {
    if (!Number.isFinite(timestamp) || !Number.isFinite(closes[index]) || closes[index] <= 0) return;
    const instant = new Date(timestamp * 1000);
    if (!Number.isFinite(instant.getTime())) return;
    const date = dateValue(instant);
    // Exclude today's candle conservatively to avoid partial-session comparisons.
    if (date < today && date >= firstDate) points.set(date, closes[index]);
  });
  return { points: [...points].sort(([a], [b]) => a.localeCompare(b)),
    source: "Yahoo Finance adjusted daily closes", period: "1y", generated_at: now.toISOString() };
}

export function createHistoryHandler({ createClient, env, fetcher = fetch, clock = () => new Date() }) {
  const cache = new Map();
  return async (request) => {
    const origin = request.headers.get("origin") || "";
    const headers = {
      "Access-Control-Allow-Origin": allowedOrigins.has(origin) ? origin : "https://aksamuel.github.io",
      "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
      "Access-Control-Allow-Methods": "POST, OPTIONS", "Content-Type": "application/json",
      "Cache-Control": "private, no-store", "Vary": "Origin",
    };
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers });
    if (request.method === "OPTIONS") return new Response("ok", { headers });
    if (request.method !== "POST") return json({ error: "Method not allowed." }, 405);
    const authorization = request.headers.get("authorization");
    if (!authorization?.startsWith("Bearer ")) return json({ error: "Authentication required." }, 401);
    try {
      let key = env("SUPABASE_ANON_KEY") || "";
      try { key = JSON.parse(env("SUPABASE_PUBLISHABLE_KEYS") || "{}").default || key; } catch { /* Legacy key fallback. */ }
      const client = createClient(env("SUPABASE_URL"), key, {
        global: { headers: { Authorization: authorization } }, auth: { persistSession: false, autoRefreshToken: false },
      });
      const { data: { user }, error: authError } = await client.auth.getUser();
      if (authError || !user) return json({ error: "Authentication required." }, 401);
      const { data: access, error: accessError } = await client.from("user_access")
        .select("status").eq("user_id", user.id).maybeSingle();
      if (accessError || access?.status !== "approved") return json({ error: "Approved access required." }, 403);
      const body = await request.json().catch(() => null);
      const symbol = typeof body?.symbol === "string" ? body.symbol.trim().toUpperCase() : "";
      if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(symbol)) return json({ error: "Invalid symbol." }, 400);
      // Ownership is checked on every request before the market-data cache.
      // Caller JWT and existing RLS apply; no service-role key is used.
      const { data: holdings, error: holdingError } = await client.from("user_portfolio_holdings")
        .select("id").eq("user_id", user.id).eq("symbol", symbol).limit(1);
      if (holdingError || !holdings?.length) return json({ error: "Holding not available." }, 403);
      const now = clock();
      const cached = cache.get(symbol);
      if (cached && cached.expires > now.getTime()) return json(cached.data);
      // Only the ticker is sent to Yahoo; never forward the caller's headers/body.
      const response = await fetcher(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=1y&interval=1d`, {
        signal: AbortSignal.timeout(15000), headers: { "User-Agent": "StockScanner/1.0" },
      });
      if (!response.ok) return json({ error: "Stock history is temporarily unavailable." }, 502);
      const data = parseHistory(await response.json(), now);
      if (!data.points.length) return json({ error: "No completed daily history available." }, 502);
      if (cache.size >= 500) cache.clear();
      cache.set(symbol, { expires: now.getTime() + 3600000, data });
      return json(data);
    } catch {
      return json({ error: "Stock history is temporarily unavailable." }, 502);
    }
  };
}
