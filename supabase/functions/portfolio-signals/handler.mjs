const allowedOrigins = new Set([
  "https://aksamuel.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
]);

export function createPortfolioSignalsHandler({ createClient, env }) {
  return async (request) => {
    const origin = request.headers.get("origin") || "";
    const headers = {
      "Access-Control-Allow-Origin": allowedOrigins.has(origin)
        ? origin : "https://aksamuel.github.io",
      "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Cache-Control": "private, no-store",
      "Content-Type": "application/json",
      "Vary": "Origin",
    };
    const json = (body, status = 200) => new Response(
      JSON.stringify(body), { status, headers },
    );
    if (request.method === "OPTIONS") return new Response("ok", { headers });
    if (request.method !== "POST") return json({ error: "Method not allowed." }, 405);
    const authorization = request.headers.get("authorization");
    if (!authorization?.startsWith("Bearer ")) {
      return json({ error: "Authentication required." }, 401);
    }
    try {
      let key = env("SUPABASE_ANON_KEY") || "";
      try {
        key = JSON.parse(env("SUPABASE_PUBLISHABLE_KEYS") || "{}").default || key;
      } catch { /* Legacy key fallback. */ }
      const client = createClient(env("SUPABASE_URL"), key, {
        global: { headers: { Authorization: authorization } },
        auth: { persistSession: false, autoRefreshToken: false },
      });
      const { data: { user }, error: authError } = await client.auth.getUser();
      if (authError || !user) return json({ error: "Authentication required." }, 401);
      const { data: access, error: accessError } = await client.from("user_access")
        .select("status").eq("user_id", user.id).maybeSingle();
      if (accessError || access?.status !== "approved") {
        return json({ error: "Approved access required." }, 403);
      }
      const { data, error } = await client.rpc("get_my_portfolio_technical_signals");
      if (error) return json({ error: "Technical signals are temporarily unavailable." }, 502);
      return json({ signals: Array.isArray(data) ? data : [] });
    } catch {
      return json({ error: "Technical signals are temporarily unavailable." }, 502);
    }
  };
}
