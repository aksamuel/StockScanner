const MAX_REQUEST_BYTES = 4_096;
const MAX_FLEX_RESPONSE_BYTES = 5_000_000;
const FLEX_SEND_REQUEST_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest";
const FLEX_GET_STATEMENT_PATH = "/AccountManagement/FlexWebService/GetStatement";
const FLEX_ALLOWED_HOSTS = new Set([
  "ndcdyn.interactivebrokers.com",
  "gdcdyn.interactivebrokers.com",
]);
const FLEX_RETRY_CODES = new Set(["1001", "1004", "1005", "1006", "1007", "1008", "1009", "1019", "1021"]);
const ALLOWED_ORIGINS = new Set([
  "https://aksamuel.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "http://localhost:8001",
  "http://127.0.0.1:8001",
]);

function defaultKey(jsonVariable, legacyVariable, env) {
  const named = env(jsonVariable);
  if (named) {
    try {
      const parsed = JSON.parse(named);
      if (typeof parsed.default === "string" && parsed.default) return parsed.default;
    } catch {
      // Fall back to the legacy key format while projects migrate.
    }
  }
  return env(legacyVariable) || "";
}

function constantTimeEqual(left, right) {
  if (!left || !right || left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function corsHeaders(request) {
  const origin = request.headers.get("origin") || "";
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin)
      ? origin
      : "https://aksamuel.github.io",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-pip-internal-key",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Cache-Control": "private, no-store",
    "Vary": "Origin",
  };
}

function json(request, body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(request), "Content-Type": "application/json" },
  });
}

function xmlValue(xml, name) {
  const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = xml.match(new RegExp(
    `<(?:[A-Za-z0-9_-]+:)?${escapedName}\\b[^>]*>\\s*([^<]*?)\\s*<\\/(?:[A-Za-z0-9_-]+:)?${escapedName}\\s*>`,
    "i",
  ));
  return match?.[1]?.trim() || null;
}

function decodeXmlText(value) {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">");
}

function isFlexQueryResponse(xml) {
  return /<(?:[A-Za-z0-9_-]+:)?FlexQueryResponse\b/i.test(xml);
}

function validatedStatementUrl(rawValue) {
  if (!rawValue) return null;
  let url;
  try {
    url = new URL(decodeXmlText(rawValue));
  } catch {
    return null;
  }
  if (
    url.protocol !== "https:"
    || !FLEX_ALLOWED_HOSTS.has(url.hostname.toLowerCase())
    || url.pathname !== FLEX_GET_STATEMENT_PATH
    || url.username
    || url.password
  ) return null;
  return url;
}

async function boundedUtf8Text(value, maxBytes) {
  const declaredSize = Number(value.headers.get("content-length") || 0);
  if (Number.isFinite(declaredSize) && declaredSize > maxBytes) {
    await value.body?.cancel();
    return null;
  }
  if (!value.body) return "";
  const reader = value.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maxBytes) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

async function tokenFingerprint(token) {
  const bytes = new TextEncoder().encode(token);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function validUuid(value) {
  return typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function safeConnection(data) {
  const row = Array.isArray(data) ? data[0] : data;
  if (!row || typeof row !== "object") return null;
  return {
    id: row.id,
    portfolio_id: row.portfolio_id,
    connection_name: row.connection_name,
    last_synced_at: row.last_synced_at || null,
    created_at: row.created_at || null,
  };
}

export function createFlexHandler({
  createClient,
  env,
  fetcher = fetch,
  sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
}) {
  return async (request) => {
    const origin = request.headers.get("origin") || "";
    if (origin && !ALLOWED_ORIGINS.has(origin)) return json(request, { error: "Origin not allowed." }, 403);
    if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders(request) });
    if (request.method !== "POST") return json(request, { error: "Method not allowed." }, 405);

    const internalSecret = env("PIP_FLEX_INTERNAL_KEY") || "";
    if (internalSecret.length < 32) return json(request, { error: "Flex service is not configured." }, 503);
    if (!constantTimeEqual(request.headers.get("x-pip-internal-key") || "", internalSecret)) {
      return json(request, { error: "Server authentication required." }, 401);
    }

    const authorization = request.headers.get("authorization");
    if (!authorization?.startsWith("Bearer ")) return json(request, { error: "Authentication required." }, 401);

    const supabaseUrl = env("SUPABASE_URL") || "";
    const publishableKey = defaultKey("SUPABASE_PUBLISHABLE_KEYS", "SUPABASE_ANON_KEY", env);
    const serviceRoleKey = defaultKey("SUPABASE_SECRET_KEYS", "SUPABASE_SERVICE_ROLE_KEY", env);
    if (!supabaseUrl || !publishableKey || !serviceRoleKey) {
      return json(request, { error: "Flex service is not configured." }, 503);
    }

    try {
      const userClient = createClient(supabaseUrl, publishableKey, {
        global: { headers: { Authorization: authorization } },
        auth: { persistSession: false, autoRefreshToken: false },
      });
      const { data: authData, error: authError } = await userClient.auth.getUser();
      const caller = authData?.user;
      if (authError || !caller?.id) return json(request, { error: "Authentication required." }, 401);

      const { data: access, error: accessError } = await userClient
        .from("user_access")
        .select("status")
        .eq("user_id", caller.id)
        .maybeSingle();
      if (accessError || access?.status !== "approved") {
        return json(request, { error: "Approved access required." }, 403);
      }

      const text = await boundedUtf8Text(request, MAX_REQUEST_BYTES);
      if (text === null) {
        return json(request, { error: "Request is too large." }, 413);
      }
      let payload;
      try {
        payload = JSON.parse(text);
      } catch {
        return json(request, { error: "Invalid JSON request." }, 400);
      }
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        return json(request, { error: "Invalid JSON request." }, 400);
      }
      const action = payload.action;
      const portfolioId = payload.portfolio_id;
      if (!["connect", "sync", "disconnect"].includes(action) || !validUuid(portfolioId)) {
        return json(request, { error: "Invalid Flex request." }, 400);
      }

      const { data: portfolio, error: portfolioError } = await userClient
        .from("portfolios")
        .select("id")
        .eq("id", portfolioId)
        .eq("user_id", caller.id)
        .maybeSingle();
      if (portfolioError) return json(request, { error: "Unable to verify portfolio ownership." }, 503);
      if (!portfolio) return json(request, { error: "Portfolio not found." }, 404);

      const adminClient = createClient(supabaseUrl, serviceRoleKey, {
        auth: { persistSession: false, autoRefreshToken: false },
      });

      if (action === "connect") {
        const name = typeof payload.connection_name === "string" ? payload.connection_name.trim() : "";
        const token = typeof payload.token === "string" ? payload.token.trim() : "";
        const queryId = typeof payload.query_id === "string" ? payload.query_id.trim() : "";
        if (
          !name
          || name.length > 80
          || /[\u0000-\u001f\u007f]/.test(name)
          || !/^[-A-Za-z0-9._~]{1,256}$/.test(token)
          || !/^[0-9]{1,20}$/.test(queryId)
        ) return json(request, { error: "Enter a valid connection name, Flex token, and numeric Query ID." }, 400);

        const { data, error } = await adminClient.rpc("pip_flex_store_connection", {
          p_user_id: caller.id,
          p_portfolio_id: portfolioId,
          p_connection_name: name,
          p_token: token,
          p_query_id: queryId,
        });
        if (error) return json(request, { error: "Unable to save the encrypted Flex connection." }, 503);
        const connection = safeConnection(data);
        if (!connection?.id) return json(request, { error: "Unable to save the encrypted Flex connection." }, 503);
        return json(request, { connection }, 201);
      }

      const connectionId = payload.connection_id;
      if (!validUuid(connectionId)) return json(request, { error: "Invalid Flex connection." }, 400);
      const { data: connection, error: connectionError } = await userClient
        .from("pip_ibkr_connections")
        .select("id,portfolio_id,connection_name")
        .eq("id", connectionId)
        .eq("portfolio_id", portfolioId)
        .eq("user_id", caller.id)
        .maybeSingle();
      if (connectionError) return json(request, { error: "Unable to verify Flex connection ownership." }, 503);
      if (!connection) return json(request, { error: "Flex connection not found." }, 404);

      if (action === "disconnect") {
        const { error } = await adminClient.rpc("pip_flex_delete_connection", {
          p_user_id: caller.id,
          p_connection_id: connectionId,
        });
        if (error) return json(request, { error: "Unable to disconnect the Flex connection." }, 503);
        return json(request, { removed: true });
      }

      const { data: credentials, error: credentialsError } = await adminClient.rpc(
        "pip_flex_get_connection",
        { p_user_id: caller.id, p_connection_id: connectionId },
      );
      if (
        credentialsError
        || !/^[-A-Za-z0-9._~]{1,256}$/.test(credentials?.token || "")
        || !/^[0-9]{1,20}$/.test(credentials?.query_id || "")
      ) {
        return json(request, { error: "Saved Flex credentials are unavailable." }, 503);
      }

      const fingerprint = await tokenFingerprint(credentials.token);
      const reserveRequest = async () => {
        const { error } = await adminClient.rpc("pip_flex_reserve_request", {
          p_user_id: caller.id,
          p_connection_id: connectionId,
          p_token_fingerprint: fingerprint,
        });
        if (error?.code === "P4290") return "rate_limited";
        if (error) return "unavailable";
        return null;
      };

      const sendLimit = await reserveRequest();
      if (sendLimit === "rate_limited") {
        return json(request, { error: "IBKR Flex is rate-limited. Wait before syncing again." }, 429);
      }
      if (sendLimit) return json(request, { error: "Unable to prepare the IBKR Flex request." }, 503);

      const sendUrl = new URL(FLEX_SEND_REQUEST_URL);
      sendUrl.searchParams.set("t", credentials.token);
      sendUrl.searchParams.set("q", credentials.query_id);
      sendUrl.searchParams.set("v", "3");
      const sendResponse = await fetcher(sendUrl, {
        method: "GET",
        headers: { "User-Agent": "StockScanner-PIP/1.0" },
        redirect: "error",
        signal: AbortSignal.timeout(15_000),
      });
      const sendXml = await boundedUtf8Text(sendResponse, MAX_FLEX_RESPONSE_BYTES);
      if (!sendResponse.ok || sendXml === null) {
        return json(request, { error: "IBKR Flex could not start the statement request." }, 502);
      }
      const sendStatus = xmlValue(sendXml, "Status");
      if (sendStatus?.toLowerCase() !== "success") {
        const code = xmlValue(sendXml, "ErrorCode");
        if (code === "1018") {
          return json(request, { error: "IBKR Flex is rate-limited. Wait before syncing again." }, 429);
        }
        return json(request, { error: "IBKR rejected the Flex request. Verify the saved token and Query ID." }, 422);
      }
      const referenceCode = xmlValue(sendXml, "ReferenceCode");
      const statementUrl = validatedStatementUrl(xmlValue(sendXml, "Url") || xmlValue(sendXml, "url"));
      if (!referenceCode || !/^[0-9]{1,20}$/.test(referenceCode) || !statementUrl) {
        return json(request, { error: "IBKR returned an invalid Flex statement reference." }, 502);
      }

      await sleep(3_000);
      for (let attempt = 0; attempt < 5; attempt += 1) {
        const getLimit = await reserveRequest();
        if (getLimit === "rate_limited") {
          return json(request, { error: "IBKR Flex is rate-limited. Wait before syncing again." }, 429);
        }
        if (getLimit) return json(request, { error: "Unable to prepare the IBKR Flex request." }, 503);

        statementUrl.searchParams.set("t", credentials.token);
        statementUrl.searchParams.set("q", referenceCode);
        statementUrl.searchParams.set("v", "3");
        const statementResponse = await fetcher(statementUrl, {
          method: "GET",
          headers: { "User-Agent": "StockScanner-PIP/1.0" },
          redirect: "error",
          signal: AbortSignal.timeout(15_000),
        });
        const statementXml = await boundedUtf8Text(statementResponse, MAX_FLEX_RESPONSE_BYTES);
        if (!statementResponse.ok || statementXml === null) {
          return json(request, { error: "IBKR Flex could not retrieve the generated statement." }, 502);
        }
        if (isFlexQueryResponse(statementXml)) {
          return json(request, { statement_xml: statementXml });
        }

        const errorCode = xmlValue(statementXml, "ErrorCode");
        if (errorCode === "1018") {
          return json(request, { error: "IBKR Flex is rate-limited. Wait before syncing again." }, 429);
        }
        if (!FLEX_RETRY_CODES.has(errorCode || "")) {
          return json(request, { error: "IBKR Flex could not retrieve the generated statement." }, 502);
        }
        if (attempt < 4) await sleep(2_000);
      }
      return json(request, { error: "The IBKR Flex statement is still being generated. Retry shortly." }, 504);
    } catch {
      return json(request, { error: "IBKR Flex is temporarily unavailable." }, 502);
    }
  };
}
