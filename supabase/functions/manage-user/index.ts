import { createClient } from "npm:@supabase/supabase-js@2.112.3";

const ADMIN_EMAIL = "aaksamuel@zohomail.com";
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
      // Fall through to the legacy key while projects migrate key formats.
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

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders(request) });
  }
  if (request.method !== "POST") return json(request, { error: "Method not allowed." }, 405);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const publishableKey = defaultKey("SUPABASE_PUBLISHABLE_KEYS", "SUPABASE_ANON_KEY");
  const serviceRoleKey = defaultKey("SUPABASE_SECRET_KEYS", "SUPABASE_SERVICE_ROLE_KEY");
  const authorization = request.headers.get("authorization");
  if (!supabaseUrl || !publishableKey || !serviceRoleKey || !authorization) {
    return json(request, { error: "Server authentication is not configured." }, 500);
  }

  const userClient = createClient(supabaseUrl, publishableKey, {
    global: { headers: { Authorization: authorization } },
    auth: { persistSession: false },
  });
  const { data: { user: caller }, error: callerError } = await userClient.auth.getUser();
  if (callerError || !caller) return json(request, { error: "Authentication required." }, 401);
  if ((caller.email || "").toLowerCase() !== ADMIN_EMAIL) {
    return json(request, { error: "Administrator access required." }, 403);
  }

  const adminClient = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  let payload: { action?: string; user_id?: string };
  try {
    payload = await request.json();
  } catch {
    return json(request, { error: "Invalid JSON request." }, 400);
  }

  if (payload.action === "list") {
    const { data: authData, error: authError } = await adminClient.auth.admin.listUsers({
      page: 1,
      perPage: 1000,
    });
    if (authError) return json(request, { error: authError.message }, 500);
    const { data: accessRows, error: accessError } = await adminClient
      .from("user_access")
      .select("user_id,status");
    if (accessError) return json(request, { error: accessError.message }, 500);

    const accessByUser = new Map((accessRows || []).map((row) => [row.user_id, row.status]));
    const now = Date.now();
    const users = authData.users
      .map((user) => {
        const accessStatus = accessByUser.get(user.id) || "pending";
        const blocked = Boolean(user.banned_until && new Date(user.banned_until).getTime() > now);
        return {
          id: user.id,
          email: user.email || "Unknown email",
          status: blocked || accessStatus === "rejected" ? "blocked" : accessStatus,
          created_at: user.created_at,
          last_sign_in_at: user.last_sign_in_at,
        };
      })
      .sort((left, right) => {
        if (left.email.toLowerCase() === ADMIN_EMAIL) return -1;
        if (right.email.toLowerCase() === ADMIN_EMAIL) return 1;
        return left.email.localeCompare(right.email);
      });
    return json(request, { users });
  }

  if (!payload.user_id) return json(request, { error: "user_id is required." }, 400);
  if (payload.user_id === caller.id) {
    return json(request, { error: "The protected administrator cannot be changed." }, 400);
  }

  const { data: targetData, error: targetError } = await adminClient.auth.admin.getUserById(payload.user_id);
  if (targetError || !targetData.user) return json(request, { error: "User not found." }, 404);
  if ((targetData.user.email || "").toLowerCase() === ADMIN_EMAIL) {
    return json(request, { error: "The protected administrator cannot be changed." }, 400);
  }

  if (payload.action === "accept") {
    const { error: unbanError } = await adminClient.auth.admin.updateUserById(payload.user_id, {
      ban_duration: "none",
    });
    if (unbanError) return json(request, { error: unbanError.message }, 500);
    const { data: access, error: accessError } = await userClient
      .from("user_access")
      .update({ status: "approved" })
      .eq("user_id", payload.user_id)
      .select("user_id")
      .maybeSingle();
    if (accessError || !access) {
      return json(request, { error: accessError?.message || "The access record could not be approved." }, 500);
    }
    return json(request, { message: `${targetData.user.email} was accepted.` });
  }

  if (payload.action === "block") {
    const { data: access, error: accessError } = await userClient
      .from("user_access")
      .update({ status: "rejected" })
      .eq("user_id", payload.user_id)
      .select("user_id")
      .maybeSingle();
    if (accessError || !access) {
      return json(request, { error: accessError?.message || "The access record could not be blocked." }, 500);
    }
    const { error: banError } = await adminClient.auth.admin.updateUserById(payload.user_id, {
      ban_duration: "876000h",
    });
    if (banError) return json(request, { error: banError.message }, 500);
    return json(request, { message: `${targetData.user.email} was blocked.` });
  }

  if (payload.action === "delete") {
    const targetEmail = (targetData.user.email || "").toLowerCase();
    const { error: deleteError } = await adminClient.auth.admin.deleteUser(payload.user_id, false);
    if (deleteError) return json(request, { error: deleteError.message }, 500);
    if (targetEmail) {
      const { error: allowlistError } = await adminClient
        .from("signup_allowlist")
        .delete()
        .eq("email", targetEmail);
      if (allowlistError) {
        return json(request, {
          error: "The user was deleted, but their signup permission could not be revoked.",
        }, 500);
      }
    }
    return json(request, { message: `${targetData.user.email} was permanently deleted.` });
  }

  return json(request, { error: "Unknown action." }, 400);
});
