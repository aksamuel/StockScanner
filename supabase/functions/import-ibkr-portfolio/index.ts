import { createClient } from "npm:@supabase/supabase-js@2.112.3";

const ALLOWED_ORIGINS = new Set([
  "https://aksamuel.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
]);
const FLEX_SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest";
const FLEX_GET_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement";

function defaultKey(jsonVariable: string, legacyVariable: string) {
  const namedKeys = Deno.env.get(jsonVariable);
  if (namedKeys) {
    try {
      const parsed = JSON.parse(namedKeys) as Record<string, string>;
      if (parsed.default) return parsed.default;
    } catch {
      // Fall through while a project migrates from legacy keys.
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

function csvRows(source: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (quoted && character === '"' && source[index + 1] === '"') {
      field += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && source[index + 1] === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (field || row.length) {
    row.push(field);
    if (row.some((value) => value.trim())) rows.push(row);
  }
  return rows;
}

function normalizedHeader(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function parseNumber(value = "") {
  const normalized = value.replace(/[,$%]/g, "").trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseIbkrDate(value = "") {
  const match = value.trim().match(/^(\d{4})(\d{2})(\d{2})/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : null;
}

function holdingsFromFlexCsv(source: string) {
  const rows = csvRows(source);
  const headerIndex = rows.findIndex((row) => {
    const headers = row.map(normalizedHeader);
    return headers.includes("symbol")
      && (headers.includes("position") || headers.includes("quantity"));
  });
  if (headerIndex < 0) {
    throw new Error("The IBKR Flex report must contain an Open Positions CSV section.");
  }

  const headers = rows[headerIndex].map(normalizedHeader);
  const value = (row: string[], ...names: string[]) => {
    for (const name of names) {
      const index = headers.indexOf(normalizedHeader(name));
      if (index >= 0) return row[index] || "";
    }
    return "";
  };
  const candidates = rows.slice(headerIndex + 1).filter((row) => {
    const symbol = value(row, "Symbol").trim().toUpperCase();
    return /^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)
      && parseNumber(value(row, "Position", "Quantity")) !== null;
  });
  const hasLots = candidates.some((row) => normalizedHeader(value(row, "LevelOfDetail")) === "lot");
  const selected = hasLots
    ? candidates.filter((row) => normalizedHeader(value(row, "LevelOfDetail")) === "lot")
    : candidates;
  const currentPriceAt = new Date().toISOString();

  return selected.map((row, index) => {
    const symbol = value(row, "Symbol").trim().toUpperCase();
    const contractId = value(row, "Conid", "ContractId").trim();
    const boughtOn = parseIbkrDate(value(row, "OpenDateTime", "OpenDate"));
    return {
      position_key: [contractId || symbol, boughtOn || "SUMMARY", index + 1].join(":"),
      symbol,
      description: value(row, "Description").trim() || null,
      asset_class: value(row, "AssetCategory", "AssetClass").trim().toUpperCase() || "STK",
      currency: value(row, "Currency").trim().toUpperCase() || "USD",
      quantity: parseNumber(value(row, "Position", "Quantity")),
      buy_price: parseNumber(value(row, "CostBasisPrice", "OpenPrice", "AveragePrice")),
      bought_on: boughtOn,
      current_price: parseNumber(value(row, "MarkPrice", "CurrentPrice")),
      current_price_at: currentPriceAt,
      market_value: parseNumber(value(row, "PositionValue", "MarketValue")),
      unrealized_pnl: parseNumber(value(row, "FifoPnlUnrealized", "UnrealizedPnl")),
      target_price: null,
      stop_loss: null,
      notes: null,
    };
  }).filter((holding) => holding.quantity !== 0);
}

function xmlValue(source: string, tag: string) {
  return source.match(new RegExp(`<${tag}>([^<]+)</${tag}>`, "i"))?.[1]?.trim() || "";
}

async function fetchFlexStatement(token: string, queryId: string) {
  const sendUrl = new URL(FLEX_SEND_URL);
  sendUrl.search = new URLSearchParams({ t: token, q: queryId, v: "3" }).toString();
  const sendResponse = await fetch(sendUrl, { signal: AbortSignal.timeout(20_000) });
  const sendBody = await sendResponse.text();
  const referenceCode = xmlValue(sendBody, "ReferenceCode");
  if (!sendResponse.ok || !referenceCode) {
    const message = xmlValue(sendBody, "ErrorMessage") || "IBKR rejected the Flex request.";
    throw new Error(message);
  }

  for (let attempt = 0; attempt < 6; attempt += 1) {
    if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, 1500));
    const getUrl = new URL(FLEX_GET_URL);
    getUrl.search = new URLSearchParams({ t: token, q: referenceCode, v: "3" }).toString();
    const response = await fetch(getUrl, { signal: AbortSignal.timeout(20_000) });
    const body = await response.text();
    if (response.ok && !body.trimStart().startsWith("<FlexStatementResponse")) return body;
    const code = xmlValue(body, "ErrorCode");
    if (code && code !== "1019") {
      throw new Error(xmlValue(body, "ErrorMessage") || `IBKR Flex error ${code}.`);
    }
  }
  throw new Error("IBKR is still preparing the Flex statement. Please try again shortly.");
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders(request) });
  }
  if (request.method !== "POST") return json(request, { error: "Method not allowed." }, 405);

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const publishableKey = defaultKey("SUPABASE_PUBLISHABLE_KEYS", "SUPABASE_ANON_KEY");
  const authorization = request.headers.get("authorization");
  if (!supabaseUrl || !publishableKey) {
    return json(request, { error: "Server authentication is not configured." }, 500);
  }
  if (!authorization) return json(request, { error: "Authentication required." }, 401);

  const userClient = createClient(supabaseUrl, publishableKey, {
    global: { headers: { Authorization: authorization } },
    auth: { persistSession: false },
  });
  const { data: { user }, error: userError } = await userClient.auth.getUser();
  if (userError || !user) return json(request, { error: "Authentication required." }, 401);
  const { data: access, error: accessError } = await userClient
    .from("user_access")
    .select("status")
    .eq("user_id", user.id)
    .maybeSingle();
  if (accessError || access?.status !== "approved") {
    return json(request, { error: "Approved user access required." }, 403);
  }

  const token = Deno.env.get("IBKR_FLEX_TOKEN");
  const queryId = Deno.env.get("IBKR_FLEX_QUERY_ID");
  if (!token || !queryId) {
    return json(request, {
      error: "IBKR import is not configured. Add IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID to the Edge Function secrets.",
    }, 503);
  }

  try {
    const statement = await fetchFlexStatement(token, queryId);
    const holdings = holdingsFromFlexCsv(statement);
    if (!holdings.length) throw new Error("The IBKR Flex statement contained no open positions.");
    const { data, error } = await userClient.rpc("replace_my_portfolio_holdings", {
      p_broker: "IBKR",
      p_source: "ibkr_flex",
      p_holdings: holdings,
    });
    if (error) throw error;
    const importResult = data?.[0] || {};
    return json(request, {
      count: importResult.replaced_count ?? holdings.length,
      downloaded_at: importResult.downloaded_at ?? new Date().toISOString(),
      missing_buy_dates: holdings.filter((holding) => !holding.bought_on).length,
    });
  } catch (error) {
    return json(request, { error: error instanceof Error ? error.message : "IBKR import failed." }, 502);
  }
});
