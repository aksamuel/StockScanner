import { createClient } from "npm:@supabase/supabase-js@2.112.3";

const ADMIN_EMAIL = "aaksamuel@zohomail.com";
const REPOSITORY = "aksamuel/StockScanner";
const ALLOWED_ORIGINS = new Set([
  "https://aksamuel.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
]);

function defaultKey(jsonVariable: string, legacyVariable: string) {
  const namedKeys = Deno.env.get(jsonVariable);
  if (namedKeys) {
    try {
      const parsed = JSON.parse(namedKeys) as Record<string, string>;
      if (parsed.default) return parsed.default;
    } catch {
      // Fall through while projects migrate from legacy keys.
    }
  }
  return Deno.env.get(legacyVariable);
}

function corsHeaders(request: Request) {
  const origin = request.headers.get("origin") || "";
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin)
      ? origin
      : "https://aksamuel.github.io",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

function json(request: Request, body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(request), "Content-Type": "application/json" },
  });
}

type RunKind = "daily" | "hourly";

const workflows: Record<RunKind, { file: string; inputs: Record<string, string> }> = {
  daily: {
    file: "scan.yml",
    inputs: { mode: "universe", limit: "0", workers: "8", force: "true" },
  },
  hourly: {
    file: "price-snapshot.yml",
    inputs: { mode: "hourly" },
  },
};

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders(request) });
  }
  if (request.method !== "POST") return json(request, { error: "Method not allowed." }, 405);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const publishableKey = defaultKey("SUPABASE_PUBLISHABLE_KEYS", "SUPABASE_ANON_KEY");
  const authorization = request.headers.get("authorization");
  if (!supabaseUrl || !publishableKey || !authorization) {
    return json(request, { error: "Server authentication is not configured." }, 500);
  }

  const userClient = createClient(supabaseUrl, publishableKey, {
    global: { headers: { Authorization: authorization } },
    auth: { persistSession: false },
  });
  const { data: { user }, error: userError } = await userClient.auth.getUser();
  if (userError || !user) return json(request, { error: "Authentication required." }, 401);
  if ((user.email || "").toLowerCase() !== ADMIN_EMAIL) {
    return json(request, { error: "Administrator access required." }, 403);
  }

  let payload: { kind?: RunKind };
  try {
    payload = await request.json();
  } catch {
    return json(request, { error: "Invalid JSON request." }, 400);
  }
  if (!payload.kind || !(payload.kind in workflows)) {
    return json(request, { error: "Run kind must be daily or hourly." }, 400);
  }

  const githubToken = Deno.env.get("GITHUB_ACTIONS_TOKEN");
  if (!githubToken) {
    return json(request, {
      error: "Manual runs are not configured. Add GITHUB_ACTIONS_TOKEN to the Edge Function secrets.",
    }, 503);
  }

  const workflow = workflows[payload.kind];
  const response = await fetch(
    `https://api.github.com/repos/${REPOSITORY}/actions/workflows/${workflow.file}/dispatches`,
    {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${githubToken}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "StockScanner-admin",
      },
      body: JSON.stringify({ ref: "main", inputs: workflow.inputs }),
      signal: AbortSignal.timeout(15_000),
    },
  );
  if (!response.ok) {
    const requestId = response.headers.get("x-github-request-id");
    return json(request, {
      error: `GitHub rejected the workflow request (${response.status}).${requestId ? ` Request ID: ${requestId}` : ""}`,
    }, 502);
  }

  return json(request, {
    message: payload.kind === "daily"
      ? "Daily scanner requested. Follow its progress in GitHub Actions."
      : "Hourly price update requested. It will collect only during the valid New York market window.",
  }, 202);
});
