import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  HOLDING_COLUMNS,
  PIP_MODULES,
  PIP_MODULE_FIELDS,
  CONFIDENCE_NOTE,
  describeHolding,
  describeModuleResult,
  fieldInputId,
  fieldKey,
  holdingCells,
  holdingInputHints,
} from "../pip-modules-core.js";

const DEFAULT_URL = "https://stockscanner-pip-api.onrender.com";
const OTHER_URL = "https://pip.example.test";
const URL_KEY = "stockscanner-pip-api-url";
const PORTFOLIO_KEY = "stockscanner-pip-module-portfolio";
const FIELDS = new Map(PIP_MODULE_FIELDS.map((field) => [fieldKey(field), field]));
const PAGE_HTML = await readFile(new URL("../pip-modules.html", import.meta.url), "utf8");
const PAGE_SCRIPT = await readFile(new URL("../pip-modules.js", import.meta.url), "utf8");

// ---- Fixtures (placeholder symbols only) ---------------------------------------------------------

const HEALTH = { status: "ok", service: "pip", positions_list: 1, module_runner: 1 };
const portfolio = (id, name) => ({ id, name, currency: "USD", created_at: "2026-11-01T09:00:00Z", updated_at: "2026-11-01T09:00:00Z" });
const PORTFOLIOS = [portfolio("p-new", "Newest import"), portfolio("p-empty", "Second import"), portfolio("p-main", "Main account")];
const EMPTY = { as_of: null, lots: 0, holdings: [], totals: [], flags: [], truncated: false, notes: [] };
const AAA = { symbol: "AAA", currency: "USD", quantity: 10, lot_count: 2, cost_basis: 1000, market_value: 1200, price_return_percent: 20, entry_date: "2026-01-02", days_held: 300, flags: [] };
const BBB = { symbol: "BBB", currency: "USD", quantity: 5, lot_count: 1, cost_basis: null, market_value: null, price_return_percent: null, entry_date: null, days_held: null, flags: ["missing_cost_basis", "missing_market_value", "missing_entry_date"] };
const FILLED = {
  as_of: "2026-11-03T10:00:00Z",
  lots: 3,
  holdings: [AAA, BBB],
  totals: [{ currency: "USD", holdings: 2, market_value: 1200, priced_holdings: 1, cost_basis: 1000, costed_holdings: 1 }],
  flags: [{ flag: "missing_market_value", message: "A market value is unavailable for at least one lot, so the value and return are withheld.", count: 1 }],
  truncated: false,
  notes: ["Values are as of the last import or sync; PIP does not fetch live prices.", "This view only reads saved data. PIP never places or transmits orders."],
};
const GROWTH = { score: 61.5, confidence: 0.5, reasons: ["Revenue growth data is missing."] };
const moduleResponse = (module, result, extra = {}) => ({ module, symbol: "AAA", currency: "USD", saved: false, result, ...extra });
const MODULE_PATH = (id) => `POST /api/pip/portfolios/p-main/modules/${id}`;

const standardRoutes = (extra = {}) => ({
  "GET /healthz": { json: HEALTH },
  "GET /api/pip/portfolios": { json: PORTFOLIOS },
  "GET /api/pip/portfolios/p-new/positions": { json: EMPTY },
  "GET /api/pip/portfolios/p-empty/positions": { json: EMPTY },
  "GET /api/pip/portfolios/p-main/positions": { json: FILLED },
  ...extra,
});

// ---- A small fake DOM built from the real HTML ---------------------------------------------------

class TextNode {
  constructor(text) {
    this.textContent = String(text);
    this.children = [];
  }
}

class Element {
  constructor(tag = "div", id = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.value = "";
    this.type = "";
    this.className = "";
    this.ownText = "";
    this.focusCalls = [];
    this.scrollCalls = 0;
  }

  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this.ownText = String(value);
    this.children = [];
  }

  append(...nodes) {
    for (const node of nodes) this.children.push(typeof node === "string" ? new TextNode(node) : node);
  }

  replaceChildren(...nodes) {
    this.ownText = "";
    this.children = [];
    this.append(...nodes);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  addEventListener(type, listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  fire(type, event = {}) {
    Object.assign(event, { type, target: this, preventDefault() { event.defaultPrevented = true; } });
    return Promise.all((this.listeners.get(type) ?? []).map((listener) => listener(event)));
  }

  focus(options) {
    this.focusCalls.push(options);
  }

  scrollIntoView() {
    this.scrollCalls += 1;
  }
}

function findAll(root, predicate) {
  const found = [];
  const visit = (node) => {
    if (node instanceof Element && predicate(node)) found.push(node);
    node.children.forEach(visit);
  };
  visit(root);
  return found;
}

function staticElements(html) {
  const elements = new Map();
  for (const match of html.matchAll(/<([a-z0-9]+)\b([^>]*)>/gi)) {
    const attributes = ` ${match[2]}`;
    const id = /\sid="([^"]+)"/.exec(attributes)?.[1];
    if (!id) continue;
    const element = new Element(match[1], id);
    element.hidden = /\shidden(?=\s|$)/.test(attributes);
    element.disabled = /\sdisabled(?=\s|$)/.test(attributes);
    element.className = /\sclass="([^"]*)"/.exec(attributes)?.[1] ?? "";
    elements.set(id, element);
  }
  return elements;
}

function installEnvironment({ routes = {}, storage = {}, signedIn = true, getAccessToken, storageBlocked = false, origin = "https://aksamuel.github.io" } = {}) {
  const names = ["document", "window", "localStorage", "fetch", "setTimeout", "clearTimeout"];
  const saved = new Map(names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const elements = staticElements(PAGE_HTML);
  const store = new Map(Object.entries(storage));
  const listeners = new Map();
  const calls = [];
  const unexpected = [];
  const timers = new Map();
  let timerId = 0;
  const realSetTimeout = globalThis.setTimeout;
  const realClearTimeout = globalThis.clearTimeout;

  const win = {
    location: { origin },
    addEventListener(type, listener, options = {}) {
      listeners.set(type, [...(listeners.get(type) ?? []), { listener, once: options.once === true }]);
    },
    emit(type) {
      const current = listeners.get(type) ?? [];
      listeners.set(type, current.filter((item) => !item.once));
      current.forEach((item) => item.listener({ type }));
    },
  };
  const token = getAccessToken ?? (async () => "test-token");
  if (signedIn) win.stockscannerPipAuth = { getAccessToken: token };

  const define = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  define("window", win);
  define("document", {
    querySelector(selector) {
      const element = selector.startsWith("#") ? elements.get(selector.slice(1)) : undefined;
      if (!element) throw new Error(`The page asked for ${selector}, which pip-modules.html does not have.`);
      return element;
    },
    createElement: (tag) => new Element(tag),
  });
  define("localStorage", {
    getItem(key) {
      if (storageBlocked) throw new DOMException("Blocked", "SecurityError");
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      if (storageBlocked) throw new DOMException("Blocked", "SecurityError");
      store.set(key, String(value));
    },
  });
  define("setTimeout", (callback, delay, ...rest) => {
    if (delay !== 90000) return realSetTimeout(callback, delay, ...rest);
    timerId += 1;
    timers.set(`fake-${timerId}`, callback);
    return `fake-${timerId}`;
  });
  define("clearTimeout", (id) => {
    if (typeof id === "string" && id.startsWith("fake-")) timers.delete(id);
    else realClearTimeout(id);
  });
  define("fetch", (url, init = {}) => {
    const parsed = new URL(url);
    const call = {
      method: init.method ?? "GET",
      path: parsed.pathname,
      origin: parsed.origin,
      headers: { ...init.headers },
      body: init.body === undefined ? undefined : JSON.parse(init.body),
      init,
    };
    calls.push(call);
    const handler = env.routes[`${call.method} ${call.path}`];
    if (!handler) unexpected.push(`${call.method} ${call.path}`);
    return new Promise((resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")), { once: true });
      Promise.resolve(handler ? (typeof handler === "function" ? handler(call) : handler) : { status: 404, json: { detail: "Not found" } })
        .then((descriptor) => {
          if (descriptor.network) throw new TypeError("Failed to fetch");
          const status = descriptor.status ?? 200;
          resolve({
            ok: status >= 200 && status < 300,
            status,
            json: async () => {
              if (descriptor.unreadable) throw new SyntaxError("Unexpected token <");
              return structuredClone(descriptor.json);
            },
          });
        })
        .catch(reject);
    });
  });

  const env = {
    routes: { ...routes },
    calls,
    storage: store,
    window: win,
    el(id) {
      return elements.get(id) ?? assert.fail(`pip-modules.html has no #${id}`);
    },
    paths: () => calls.map((call) => `${call.method} ${call.path}`),
    signIn() {
      win.stockscannerPipAuth = { getAccessToken: token };
      win.emit("stockscanner-pip-auth-ready");
    },
    pendingTimers: () => timers.size,
    fireTimeout() {
      for (const [id, callback] of [...timers]) {
        timers.delete(id);
        callback();
      }
    },
    restore() {
      for (const [name, descriptor] of saved) {
        if (descriptor) Object.defineProperty(globalThis, name, descriptor);
        else delete globalThis[name];
      }
      assert.deepEqual(unexpected, [], "the page made requests the test did not expect");
    },
  };
  return env;
}

let importCounter = 0;

async function openPage(t, options = {}) {
  const env = installEnvironment({ ...options, routes: standardRoutes(options.routes) });
  t.after(() => env.restore());
  await import(`../pip-modules.js?case=${++importCounter}`);
  return env;
}

async function waitFor(check, what = "the page to settle") {
  for (let attempt = 0; attempt < 500; attempt += 1) {
    if (check()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail(`Timed out waiting for ${what}`);
}

async function settle() {
  for (let attempt = 0; attempt < 25; attempt += 1) await new Promise((resolve) => setImmediate(resolve));
}

function gate() {
  let release;
  const promise = new Promise((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

const loaded = (env) => !env.el("moduleConnect").disabled && !env.el("moduleHoldingsStatus").textContent.startsWith("Loading");

async function connectedPage(t, options = {}) {
  const env = await openPage(t, options);
  await waitFor(() => loaded(env), "the page to finish connecting");
  return env;
}

const rowTexts = (env) => env.el("moduleHoldingsBody").children.map((row) => row.children.map((cell) => cell.textContent));
const moduleButtons = (env) => findAll(env.el("moduleButtons"), (node) => node.tagName === "BUTTON");
const moduleButton = (env, label) => moduleButtons(env).find((button) => button.textContent === label) ?? assert.fail(`no module button ${label}`);
const inputFor = (env, key) => findAll(env.el("moduleInputGroups"), (node) => node.id === fieldInputId(FIELDS.get(key)))[0] ?? assert.fail(`no input ${key}`);
const posts = (env) => env.calls.filter((call) => call.method === "POST");
const resultText = (env) => env.el("moduleResult").textContent;
const status = (env, id) => env.el(id).textContent;

function runButton(env, symbol) {
  const row = env.el("moduleHoldingsBody").children.find((item) => item.children[0]?.textContent === symbol);
  assert.ok(row, `no row for ${symbol}`);
  return findAll(row, (node) => node.tagName === "BUTTON")[0];
}

async function openRunner(env, symbol = "AAA") {
  await runButton(env, symbol).fire("click");
}

function assertRendered(env, view, symbol = "AAA") {
  const text = resultText(env);
  assert.ok(text.startsWith(`${view.title} · ${symbol}`), "the result starts with its title and the holding");
  for (const part of [view.title, view.headline, view.footer, ...view.rows.flat(), ...view.details, ...view.hints, ...view.caveats]) {
    assert.ok(text.includes(part), `the result does not show: ${part}`);
  }
}

// ---- Connecting ----------------------------------------------------------------------------------

test("waits for sign-in, then checks health without the token before loading anything with it", async (t) => {
  const env = await openPage(t, { signedIn: false });
  assert.equal(env.el("moduleApiUrl").value, DEFAULT_URL);
  assert.equal(env.el("moduleConnect").disabled, true);
  await settle();
  assert.deepEqual(env.calls, []);
  env.signIn();
  await waitFor(() => loaded(env), "the page to finish connecting");
  assert.deepEqual(env.paths(), [
    "GET /healthz",
    "GET /api/pip/portfolios",
    "GET /api/pip/portfolios/p-new/positions",
    "GET /api/pip/portfolios/p-empty/positions",
    "GET /api/pip/portfolios/p-main/positions",
  ]);
  assert.ok(!("Authorization" in env.calls[0].headers), "the health check must not carry the sign-in token");
  for (const call of env.calls.slice(1)) assert.equal(call.headers.Authorization, "Bearer test-token");
  for (const call of env.calls) {
    assert.equal(call.origin, DEFAULT_URL);
    assert.equal(call.method, "GET");
    assert.equal(call.init.credentials, "omit");
    assert.equal(call.init.cache, "no-store");
    assert.equal(call.headers.Accept, "application/json");
    assert.ok(!("Content-Type" in call.headers), "a request without a body has no content type");
    assert.equal(call.body, undefined);
  }
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${DEFAULT_URL}. 3 portfolios found.`);
  assert.equal(env.el("moduleConnect").textContent, "Connect and load portfolios");
  assert.equal(env.pendingTimers(), 0, "every request timer is cleared");
});

test("uses a sign-in that is already ready and ignores a late duplicate event", async (t) => {
  const env = await connectedPage(t);
  const count = env.calls.length;
  assert.ok(count > 0);
  env.window.emit("stockscanner-pip-auth-ready");
  await settle();
  assert.equal(env.calls.length, count);
});

test("never connects by itself to an address other than the default one", async (t) => {
  const env = await openPage(t, { storage: { [URL_KEY]: OTHER_URL } });
  await settle();
  assert.equal(env.el("moduleApiUrl").value, OTHER_URL);
  assert.deepEqual(env.calls, []);
  assert.equal(env.el("moduleConnect").disabled, false);
  assert.equal(status(env, "moduleConnectStatus"), `Select Connect to use ${OTHER_URL}.`);
});

test("asks for a second click before sending the sign-in token to a non-default service", async (t) => {
  const env = await openPage(t, { storage: { [URL_KEY]: OTHER_URL } });
  await env.el("moduleConnect").fire("click");
  assert.deepEqual(env.calls, []);
  assert.equal(
    status(env, "moduleConnectStatus"),
    "https://pip.example.test is not the default PIP service. Connecting sends your sign-in token to it. Select Connect again only if you deployed or trust that service.",
  );
  assert.equal(env.el("moduleConnectStatus").className, "error");
  await env.el("moduleConnect").fire("click");
  assert.ok(env.calls.length > 0);
  assert.ok(env.calls.every((call) => call.origin === OTHER_URL));
  assert.ok(!("Authorization" in env.calls[0].headers));
  assert.equal(env.storage.get(URL_KEY), OTHER_URL);
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${OTHER_URL}. 3 portfolios found.`);
});

test("changing the address after the warning asks again for the new address", async (t) => {
  const env = await openPage(t, { storage: { [URL_KEY]: OTHER_URL } });
  await env.el("moduleConnect").fire("click");
  env.el("moduleApiUrl").value = "https://another.example.test/pip/";
  await env.el("moduleConnect").fire("click");
  assert.deepEqual(env.calls, []);
  assert.match(status(env, "moduleConnectStatus"), /^https:\/\/another\.example\.test is not the default/);
});

test("keeps the path of the address and drops a trailing slash", async (t) => {
  const prefixed = Object.fromEntries(Object.entries(standardRoutes()).map(([key, value]) => {
    const [method, path] = key.split(" ");
    return [`${method} /pip${path}`, value];
  }));
  const env = await openPage(t, { storage: { [URL_KEY]: "http://localhost:8000/pip/" }, routes: {} });
  env.routes = prefixed;
  await env.el("moduleConnect").fire("click");
  assert.equal(env.calls[0].origin, "http://localhost:8000");
  assert.equal(env.calls[0].path, "/pip/healthz");
  assert.equal(env.el("moduleApiUrl").value, "http://localhost:8000/pip/");
  assert.equal(status(env, "moduleConnectStatus"), "Connected to http://localhost:8000/pip. 3 portfolios found.");
  assert.equal(env.storage.get(URL_KEY), "http://localhost:8000/pip");
});

test("a local address needs one click and no warning", async (t) => {
  const env = await openPage(t, { storage: { [URL_KEY]: "http://127.0.0.1:8000" } });
  await env.el("moduleConnect").fire("click");
  assert.equal(env.calls[0].origin, "http://127.0.0.1:8000");
  assert.doesNotMatch(status(env, "moduleConnectStatus"), /not the default/);
});

for (const [address, expected] of [
  ["", "Enter the PIP API URL."],
  ["not a url", "Enter a full PIP API URL that starts with https://."],
  ["http://example.com", "Use HTTPS for the PIP API URL."],
  ["ftp://example.com", "Use HTTPS for the PIP API URL."],
  ["https://user:secret@example.com", "The PIP API URL must not contain credentials, a query string or a fragment."],
  ["https://example.com/?token=1", "The PIP API URL must not contain credentials, a query string or a fragment."],
]) {
  test(`rejects the address ${JSON.stringify(address)} without sending a request`, async (t) => {
    const env = await connectedPage(t);
    const before = env.calls.length;
    env.el("moduleApiUrl").value = address;
    await env.el("moduleConnect").fire("click");
    assert.equal(env.calls.length, before);
    assert.equal(status(env, "moduleConnectStatus"), expected);
    assert.equal(env.el("moduleConnectStatus").className, "error");
    assert.equal(env.storage.get(URL_KEY), DEFAULT_URL, "a rejected address is not remembered");
  });
}

for (const [name, health, expected] of [
  ["a PIP API without the holdings markers", { status: "ok", service: "pip" }, /out of date/],
  ["a PIP API without the module runner", { ...HEALTH, module_runner: 0 }, /out of date/],
  ["a PIP API without the holdings list", { ...HEALTH, positions_list: undefined }, /out of date/],
  ["another service", { status: "ok", service: "other" }, /did not answer like a PIP API/],
  ["a null answer", null, /did not answer like a PIP API/],
  ["a text answer", "ok", /did not answer like a PIP API/],
]) {
  test(`explains ${name} and shows nothing from it`, async (t) => {
    const env = await connectedPage(t, { routes: { "GET /healthz": { json: health } } });
    assert.match(status(env, "moduleConnectStatus"), expected);
    assert.equal(env.el("moduleConnectStatus").className, "error");
    assert.deepEqual(env.paths(), ["GET /healthz"]);
    assert.equal(env.el("modulePortfolioSection").hidden, true);
    assert.equal(env.el("moduleRunSection").hidden, true);
    assert.equal(env.el("moduleConnect").disabled, false);
  });
}

test("an unreachable service is explained with the page origin and the CORS setting, not a fallback", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /healthz": { network: true } } });
  const text = status(env, "moduleConnectStatus");
  assert.match(text, /^Could not reach the PIP API\./);
  assert.ok(text.includes("https://aksamuel.github.io"));
  assert.ok(text.includes("PIP_CORS_ORIGINS"));
  assert.equal(env.el("modulePortfolioSection").hidden, true);
  assert.deepEqual(rowTexts(env), []);
  assert.equal(env.pendingTimers(), 0);
});

test("a request that never answers is stopped after 90 seconds with a wake-up hint", async (t) => {
  const env = await openPage(t, { routes: { "GET /healthz": () => new Promise(() => {}) } });
  await waitFor(() => env.pendingTimers() === 1, "the request timer");
  assert.equal(env.el("moduleConnect").disabled, true);
  env.fireTimeout();
  await waitFor(() => loaded(env), "the timeout to be reported");
  assert.match(status(env, "moduleConnectStatus"), /did not answer within 90 seconds\. A free Render service can take about a minute to wake up\./);
  assert.equal(env.pendingTimers(), 0);
});

test("a gateway error without a body says the service is not ready", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /healthz": { status: 502, unreadable: true } } });
  assert.match(status(env, "moduleConnectStatus"), /^The PIP API is not ready \(HTTP 502\)\. A free Render service can take about a minute to wake up\./);
});

test("an answer that is not JSON is an error, not an empty success", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /healthz": { unreadable: true } } });
  assert.equal(status(env, "moduleConnectStatus"), "The PIP API answered with something that is not valid JSON.");
});

test("API errors are shown with the API's own explanation", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { status: 403, json: { detail: "Your account is not approved for PIP." } } } });
  assert.equal(status(env, "moduleConnectStatus"), "Your account is not approved for PIP.");
  assert.deepEqual(env.paths(), ["GET /healthz", "GET /api/pip/portfolios"]);
  assert.equal(env.el("modulePortfolioSection").hidden, true);
});

test("an unexpected portfolio list is rejected", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { json: { portfolios: [] } } } });
  assert.equal(status(env, "moduleConnectStatus"), "The API returned an unexpected portfolio list.");
});

test("a missing sign-in session stops before the token-carrying request and says why", async (t) => {
  const getAccessToken = async () => {
    throw new Error("Your Supabase session has expired. Sign in again.");
  };
  const env = await connectedPage(t, { getAccessToken });
  assert.equal(status(env, "moduleConnectStatus"), "Your Supabase session has expired. Sign in again.");
  assert.deepEqual(env.paths(), ["GET /healthz"]);
});

for (const [name, value] of [["an empty", ""], ["a missing", null], ["a non-text", { token: true }]]) {
  test(`${name} sign-in token is treated as an expired sign-in`, async (t) => {
    const env = await connectedPage(t, { getAccessToken: async () => value });
    assert.equal(status(env, "moduleConnectStatus"), "Your sign-in has expired. Sign in again.");
    assert.deepEqual(env.paths(), ["GET /healthz"]);
  });
}

test("shows a connecting state with a disabled button, then restores the button", async (t) => {
  const release = gate();
  const listing = gate();
  const env = await openPage(t, {
    routes: {
      "GET /healthz": async () => { await release.promise; return { json: HEALTH }; },
      "GET /api/pip/portfolios": async () => { await listing.promise; return { json: PORTFOLIOS }; },
    },
  });
  await waitFor(() => env.calls.length === 1, "the health check");
  assert.equal(env.el("moduleConnect").disabled, true);
  assert.equal(env.el("moduleConnect").textContent, "Connecting…");
  assert.match(status(env, "moduleConnectStatus"), /^Connecting to https:\/\/stockscanner-pip-api\.onrender\.com… The first request can take about a minute/);
  release.release();
  await waitFor(() => env.paths().includes("GET /api/pip/portfolios"), "the portfolio request");
  assert.equal(status(env, "moduleConnectStatus"), "Loading your portfolios…");
  assert.equal(env.el("moduleConnect").disabled, true);
  listing.release();
  await waitFor(() => loaded(env), "the page to finish connecting");
  assert.equal(env.el("moduleConnect").textContent, "Connect and load portfolios");
});

test("Enter in the address box connects, other keys and a disabled button do not", async (t) => {
  const env = await openPage(t, { signedIn: false });
  const input = env.el("moduleApiUrl");
  await input.fire("keydown", { key: "Enter" });
  assert.deepEqual(env.calls, [], "the button is disabled before sign-in");
  env.signIn();
  await waitFor(() => loaded(env), "the page to finish connecting");
  const before = env.calls.length;
  await input.fire("keydown", { key: "a" });
  assert.equal(env.calls.length, before);
  const event = { key: "Enter" };
  await input.fire("keydown", event);
  assert.equal(event.defaultPrevented, true);
  assert.ok(env.calls.length > before);
});

test("a second connect supersedes a slower first one", async (t) => {
  const release = gate();
  let healthCalls = 0;
  const env = await openPage(t, {
    routes: { "GET /healthz": async () => { healthCalls += 1; if (healthCalls === 1) await release.promise; return { json: HEALTH }; } },
  });
  await waitFor(() => env.calls.length === 1, "the first health check");
  await env.el("moduleConnect").fire("click");
  assert.equal(status(env, "moduleHoldingsStatus").startsWith("Loading"), false);
  const rows = rowTexts(env);
  const paths = env.paths();
  release.release();
  await settle();
  assert.deepEqual(rowTexts(env), rows);
  assert.deepEqual(env.paths(), paths, "the superseded connect sends nothing more");
  assert.equal(env.el("moduleConnect").disabled, false);
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${DEFAULT_URL}. 3 portfolios found.`);
});

// ---- Portfolios and holdings -----------------------------------------------------------------------

test("skips empty newer portfolios, shows the first with holdings and remembers it", async (t) => {
  const env = await connectedPage(t);
  assert.equal(env.el("modulePortfolio").value, "p-main");
  assert.equal(env.el("modulePortfolio").children.length, 3);
  assert.deepEqual(env.el("modulePortfolio").children.map((option) => option.value), ["p-new", "p-empty", "p-main"]);
  assert.deepEqual(env.el("modulePortfolio").children.map((option) => option.textContent), [
    "Newest import (USD, created 2026-11-01)",
    "Second import (USD, created 2026-11-01)",
    "Main account (USD, created 2026-11-01)",
  ]);
  assert.equal(env.el("modulePortfolioSection").hidden, false);
  assert.equal(env.storage.get(PORTFOLIO_KEY), "p-main");
  assert.equal(
    status(env, "moduleHoldingsStatus"),
    "2 holdings from 3 lots, as of 2026-11-03 10:00 UTC. Showing the newest portfolio that has holdings; 2 newer portfolios are empty.",
  );
  assert.equal(rowTexts(env).length, 2);
});

test("loads the remembered portfolio directly", async (t) => {
  const env = await connectedPage(t, { storage: { [PORTFOLIO_KEY]: "p-main" } });
  assert.deepEqual(env.paths().filter((path) => path.endsWith("/positions")), ["GET /api/pip/portfolios/p-main/positions"]);
  assert.equal(env.el("modulePortfolio").value, "p-main");
  assert.doesNotMatch(status(env, "moduleHoldingsStatus"), /newer portfolio/);
});

test("falls back to the newest portfolio with holdings when the remembered one is gone", async (t) => {
  const env = await connectedPage(t, { storage: { [PORTFOLIO_KEY]: "p-deleted" } });
  assert.equal(env.el("modulePortfolio").value, "p-main");
  assert.equal(env.storage.get(PORTFOLIO_KEY), "p-main");
});

test("when every portfolio is empty it shows the newest one and says so", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios/p-main/positions": { json: EMPTY } } });
  assert.equal(env.el("modulePortfolio").value, "p-new");
  assert.equal(status(env, "moduleHoldingsStatus"), "This portfolio has no saved holdings. None of your 3 portfolios has saved holdings.");
  assert.deepEqual(rowTexts(env), [["No holdings to show."]]);
  assert.equal(env.el("moduleHoldingsBody").children[0].children[0].getAttribute("colspan"), String(HOLDING_COLUMNS.length + 1));
  assert.equal(env.el("moduleHoldingsBody").children[0].children[0].className, "empty");
  assert.equal(env.el("moduleRunSection").hidden, true);
});

test("explains how to get holdings when there is no portfolio yet", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { json: [] } } });
  assert.match(status(env, "moduleConnectStatus"), /^Connected to .+, but you have no portfolios yet\. Import positions or sync IBKR Flex in the PIP workbench first\.$/);
  assert.equal(env.storage.get(URL_KEY), DEFAULT_URL);
  assert.equal(env.el("modulePortfolioSection").hidden, true);
  assert.deepEqual(env.paths(), ["GET /healthz", "GET /api/pip/portfolios"]);
});

test("a failed holdings request shows its error, nothing stale, and Reload holdings retries it", async (t) => {
  const failing = { status: 502, json: { detail: "Unable to load positions." } };
  const env = await connectedPage(t, { storage: { [PORTFOLIO_KEY]: "p-main" }, routes: { "GET /api/pip/portfolios/p-main/positions": failing } });
  assert.equal(status(env, "moduleHoldingsStatus"), "Unable to load positions.");
  assert.equal(env.el("moduleHoldingsStatus").className, "error");
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${DEFAULT_URL}. 3 portfolios found.`, "a failed holdings request is not a failed connection");
  assert.deepEqual(rowTexts(env), []);
  assert.equal(env.el("moduleRunSection").hidden, true);
  assert.equal(env.el("modulePortfolioSection").hidden, false);
  env.routes["GET /api/pip/portfolios/p-main/positions"] = { json: FILLED };
  await env.el("moduleReload").fire("click");
  assert.equal(rowTexts(env).length, 2);
  assert.equal(env.el("moduleHoldingsStatus").className, "subtle");
});

test("an unexpected holdings response is rejected instead of shown", async (t) => {
  const env = await connectedPage(t, { storage: { [PORTFOLIO_KEY]: "p-main" }, routes: { "GET /api/pip/portfolios/p-main/positions": { json: { rows: [] } } } });
  assert.equal(status(env, "moduleHoldingsStatus"), "The API returned an unexpected holdings response.");
  assert.deepEqual(rowTexts(env), []);
});

test("switching portfolio loads that portfolio and closes the runner for the old one", async (t) => {
  const other = { ...FILLED, holdings: [{ ...AAA, symbol: "CCC" }], lots: 1, totals: [], flags: [], notes: [] };
  const env = await connectedPage(t, {
    storage: { [PORTFOLIO_KEY]: "p-main" },
    routes: { "GET /api/pip/portfolios/p-empty/positions": { json: other } },
  });
  await openRunner(env, "AAA");
  assert.equal(env.el("moduleRunSection").hidden, false);
  env.el("modulePortfolio").value = "p-empty";
  await env.el("modulePortfolio").fire("change");
  assert.deepEqual(rowTexts(env).map((row) => row[0]), ["CCC"]);
  assert.equal(env.el("moduleRunSection").hidden, true);
  assert.equal(env.storage.get(PORTFOLIO_KEY), "p-empty");
  assert.equal(env.el("moduleTotals").hidden, true);
  assert.equal(env.el("moduleNotes").hidden, true);
  assert.equal(env.calls.at(-1).path, "/api/pip/portfolios/p-empty/positions");
});

test("a slow holdings load that was superseded is ignored", async (t) => {
  const release = gate();
  const other = { ...FILLED, holdings: [{ ...AAA, symbol: "CCC" }] };
  const env = await openPage(t, {
    storage: { [PORTFOLIO_KEY]: "p-main" },
    routes: {
      "GET /api/pip/portfolios/p-main/positions": async () => { await release.promise; return { json: FILLED }; },
      "GET /api/pip/portfolios/p-empty/positions": { json: other },
    },
  });
  await waitFor(() => env.paths().includes("GET /api/pip/portfolios/p-main/positions"), "the first holdings request");
  assert.equal(status(env, "moduleHoldingsStatus"), "Loading the holdings of Main account (USD, created 2026-11-01)…");
  env.el("modulePortfolio").value = "p-empty";
  await env.el("modulePortfolio").fire("change");
  assert.deepEqual(rowTexts(env).map((row) => row[0]), ["CCC"]);
  release.release();
  await settle();
  assert.deepEqual(rowTexts(env).map((row) => row[0]), ["CCC"]);
  assert.equal(env.el("modulePortfolio").value, "p-empty");
  assert.equal(env.storage.get(PORTFOLIO_KEY), "p-empty");
});

test("shows the saved holdings, totals, flags and notes exactly as the core describes them", async (t) => {
  const env = await connectedPage(t);
  assert.deepEqual(env.el("moduleHeadRow").children.map((cell) => cell.textContent), [...HOLDING_COLUMNS.map((column) => column.label), "Modules"]);
  assert.ok(env.el("moduleHeadRow").children.every((cell) => cell.getAttribute("scope") === "col"));
  assert.deepEqual(env.el("moduleHeadRow").children.map((cell) => cell.className), [...HOLDING_COLUMNS.map((column) => (column.numeric ? "numeric" : "")), ""]);
  assert.deepEqual(rowTexts(env), [[...holdingCells(AAA), "Run modules"], [...holdingCells(BBB), "Run modules"]]);
  assert.deepEqual(env.el("moduleTotals").children.map((item) => item.textContent), [
    "USD: 2 holdings; market value 1,200.00 (1 of 2 priced); cost basis 1,000.00 (1 of 2 with a cost basis).",
  ]);
  assert.deepEqual(env.el("moduleFlags").children.map((item) => item.textContent), [
    "1 holding: A market value is unavailable for at least one lot, so the value and return are withheld.",
  ]);
  assert.deepEqual(env.el("moduleNotes").children.map((item) => item.textContent), FILLED.notes);
  assert.equal(env.el("moduleTotals").hidden, false);
  const firstRow = env.el("moduleHoldingsBody").children[0];
  assert.deepEqual(firstRow.children.map((cell) => cell.className), ["symbol", ...HOLDING_COLUMNS.slice(1).map((column) => (column.numeric ? "numeric" : "")), ""]);
  const button = findAll(firstRow, (node) => node.tagName === "BUTTON")[0];
  assert.equal(button.getAttribute("aria-label"), "Run modules for AAA");
  assert.equal(button.type, "button");
  assert.equal(button.className, "secondary");
});

test("renders text from the API as text, never as markup", async (t) => {
  const hostile = "<img src=x onerror=alert(1)>";
  const payload = { ...FILLED, holdings: [{ ...AAA, symbol: hostile }], notes: [hostile], flags: [{ flag: "x", message: hostile, count: 1 }] };
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { json: [{ ...PORTFOLIOS[2], name: hostile }] }, "GET /api/pip/portfolios/p-main/positions": { json: payload } } });
  assert.equal(rowTexts(env)[0][0], hostile);
  assert.ok(env.el("moduleNotes").textContent.includes(hostile));
  assert.ok(env.el("modulePortfolio").textContent.includes(hostile));
  for (const id of ["moduleHoldingsBody", "moduleNotes", "moduleFlags", "modulePortfolio"]) {
    assert.deepEqual(findAll(env.el(id), (node) => node.tagName === "IMG"), []);
  }
});

test("the symbol filter narrows the rows and says how many are shown", async (t) => {
  const env = await connectedPage(t);
  const filter = env.el("moduleFilter");
  filter.value = " bb ";
  await filter.fire("input");
  assert.deepEqual(rowTexts(env).map((row) => row[0]), ["BBB"]);
  assert.equal(status(env, "moduleFilterStatus"), "Showing 1 of 2 holdings.");
  filter.value = "zzz";
  await filter.fire("input");
  assert.deepEqual(rowTexts(env), [["No holding matches this filter."]]);
  assert.equal(status(env, "moduleFilterStatus"), "Showing 0 of 2 holdings.");
  filter.value = "";
  await filter.fire("input");
  assert.equal(rowTexts(env).length, 2);
  assert.equal(status(env, "moduleFilterStatus"), "");
  filter.value = "   ";
  await filter.fire("input");
  assert.equal(rowTexts(env).length, 2);
  assert.equal(status(env, "moduleFilterStatus"), "", "blank spaces are not a filter");
});

// ---- The runner ----------------------------------------------------------------------------------

test("builds one labelled input per optional field and one button per module", async (t) => {
  const env = await connectedPage(t);
  const groups = findAll(env.el("moduleInputGroups"), (node) => node.tagName === "FIELDSET");
  assert.deepEqual(groups.map((group) => group.children[0].textContent), [...new Set(PIP_MODULE_FIELDS.map((field) => field.group))]);
  for (const field of PIP_MODULE_FIELDS) {
    const input = inputFor(env, fieldKey(field));
    assert.equal(input.tagName, field.type === "candidates" ? "TEXTAREA" : "INPUT");
    const label = findAll(env.el("moduleInputGroups"), (node) => node.tagName === "LABEL" && node.getAttribute("for") === input.id)[0];
    assert.equal(label?.textContent, field.label);
    const help = findAll(env.el("moduleInputGroups"), (node) => node.id === input.getAttribute("aria-describedby"))[0];
    assert.equal(help?.textContent, field.help);
    assert.equal(input.value, field.value ?? "");
    assert.equal(input.getAttribute("autocomplete"), "off");
    if (field.type !== "candidates") assert.equal(input.type, "text");
    if (field.type === "date") assert.equal(input.getAttribute("placeholder"), "YYYY-MM-DD");
    if (field.placeholder) assert.equal(input.getAttribute("placeholder"), field.placeholder);
  }
  for (const key of ["position.market_price", "position.cost_basis", "scores.tsr", "dividends.consistency_score", "hurdle.required_annual_return_percent"]) {
    assert.equal(inputFor(env, key).getAttribute("inputmode"), "decimal", key);
  }
  for (const key of ["growth.earnings_growth_percent", "hurdle.holding_assumed_return_percent", "forward.target_upside_percent", "dividends.dividend_growth_rate", "position.entry_date"]) {
    assert.equal(inputFor(env, key).getAttribute("inputmode"), null, `${key} may need a minus sign`);
  }
  assert.equal(inputFor(env, "peer_scores").getAttribute("rows"), "2");
  assert.equal(inputFor(env, "peer_scores").getAttribute("spellcheck"), "false");
  assert.equal(inputFor(env, "hurdle.required_annual_return_percent").value, "7");
  assert.deepEqual(moduleButtons(env).map((button) => button.textContent), PIP_MODULES.map((module) => module.label));
  for (const module of PIP_MODULES) {
    const button = moduleButton(env, module.label);
    const needs = findAll(env.el("moduleButtons"), (node) => node.id === button.getAttribute("aria-describedby"))[0];
    assert.equal(needs.textContent, module.needs);
    assert.equal(button.type, "button");
  }
  assert.equal(status(env, "moduleConfidenceNote"), CONFIDENCE_NOTE);
  const inputsWithClass = (className) => findAll(env.el("moduleInputGroups"), (node) => node.className === className).length;
  assert.equal(inputsWithClass("input-grid"), groups.length);
  assert.equal(inputsWithClass("field"), PIP_MODULE_FIELDS.length);
  assert.equal(findAll(env.el("moduleButtons"), (node) => node.className === "module-action").length, PIP_MODULES.length);
});

test("choosing a holding opens the runner, focuses it and shows what the holding lacks", async (t) => {
  const env = await connectedPage(t);
  assert.equal(env.el("moduleRunSection").hidden, true);
  await openRunner(env, "AAA");
  assert.equal(env.el("moduleRunSection").hidden, false);
  assert.equal(status(env, "moduleSelected"), "Run modules for AAA");
  assert.equal(status(env, "moduleSelectedFacts"), describeHolding(AAA));
  assert.equal(env.el("moduleHints").hidden, true);
  assert.equal(env.el("moduleInputs").open, false);
  assert.equal(env.el("moduleRunSection").scrollCalls, 1);
  assert.deepEqual(env.el("moduleSelected").focusCalls, [{ preventScroll: true }]);
  assert.equal(env.el("moduleHoldingsBody").children[0].className, "selected");
  assert.equal(env.el("moduleHoldingsBody").children[1].className, "");

  await openRunner(env, "BBB");
  assert.equal(status(env, "moduleSelected"), "Run modules for BBB");
  assert.deepEqual(env.el("moduleHints").children.map((item) => item.textContent), holdingInputHints(BBB));
  assert.equal(env.el("moduleHints").hidden, false);
  assert.equal(env.el("moduleInputs").open, true);
  assert.equal(env.el("moduleHoldingsBody").children[0].className, "");
  assert.equal(env.el("moduleHoldingsBody").children[1].className, "selected");
});

test("holding inputs reset for another holding, shared inputs stay, and the same holding keeps everything", async (t) => {
  const env = await connectedPage(t);
  await openRunner(env, "AAA");
  inputFor(env, "position.market_price").value = "150";
  inputFor(env, "growth.earnings_growth_percent").value = "12";
  inputFor(env, "hurdle.required_annual_return_percent").value = "9";
  inputFor(env, "hurdle.replacement_assumed_return_percent").value = "11";
  inputFor(env, "peer_scores").value = "BBB:80";
  await runButton(env, "AAA").fire("click");
  assert.equal(inputFor(env, "position.market_price").value, "150", "the same holding keeps its inputs");
  assert.equal(env.el("moduleRunSection").scrollCalls, 2);
  await openRunner(env, "BBB");
  assert.equal(inputFor(env, "position.market_price").value, "");
  assert.equal(inputFor(env, "growth.earnings_growth_percent").value, "");
  assert.equal(inputFor(env, "hurdle.required_annual_return_percent").value, "9");
  assert.equal(inputFor(env, "hurdle.replacement_assumed_return_percent").value, "11");
  assert.equal(inputFor(env, "peer_scores").value, "BBB:80");
});

test("runs a module with the typed values and shows what the core describes, read-only", async (t) => {
  const response = moduleResponse("growth", GROWTH);
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: { json: response } } });
  await openRunner(env, "AAA");
  inputFor(env, "growth.earnings_growth_percent").value = " 12.5 ";
  inputFor(env, "position.market_price").value = "150";
  inputFor(env, "position.entry_date").value = "2026-01-02";
  inputFor(env, "peer_scores").value = "bbb:82, ccc:90";
  await moduleButton(env, "Growth analysis").fire("click");

  assert.equal(posts(env).length, 1);
  const call = posts(env)[0];
  assert.equal(call.path, "/api/pip/portfolios/p-main/modules/growth");
  assert.equal(call.headers.Authorization, "Bearer test-token");
  assert.equal(call.headers["Content-Type"], "application/json");
  assert.equal(call.init.credentials, "omit");
  assert.deepEqual(call.body, {
    symbol: "AAA",
    position: { market_price: 150, entry_date: "2026-01-02" },
    hurdle: { required_annual_return_percent: 7 },
    growth: { earnings_growth_percent: 12.5 },
    peer_scores: [{ symbol: "BBB", score: 82 }, { symbol: "CCC", score: 90 }],
  });
  const view = describeModuleResult("growth", response);
  assert.equal(view.unexpected, false);
  assert.equal(env.el("moduleResult").hidden, false);
  assert.equal(env.el("moduleResult").scrollCalls, 1);
  assert.equal(env.el("moduleResult").className, "result");
  assertRendered(env, view);
  assert.equal(status(env, "moduleRunStatus"), "Growth analysis finished for AAA.");
  assert.equal(env.el("moduleRunStatus").className, "");
  assert.ok(resultText(env).includes("Read-only result: nothing was saved and no orders were placed."));
  assert.deepEqual(env.calls.filter((item) => item.method !== "GET" && item.method !== "POST"), []);
  assert.equal(env.pendingTimers(), 0);
});

test("a default run sends only the symbol and the default required return", async (t) => {
  const env = await connectedPage(t, { routes: { [MODULE_PATH("lifecycle")]: { json: moduleResponse("lifecycle", {}) } } });
  await openRunner(env, "BBB");
  await moduleButton(env, "Position lifecycle").fire("click");
  assert.deepEqual(posts(env)[0].body, { symbol: "BBB", hurdle: { required_annual_return_percent: 7 } });
});

test("every module button posts to its own route and reports what the core says about the answer", async (t) => {
  const routes = Object.fromEntries(PIP_MODULES.map((module) => [MODULE_PATH(module.id), { json: moduleResponse(module.id, {}) }]));
  const env = await connectedPage(t, { routes });
  await openRunner(env, "AAA");
  for (const module of PIP_MODULES) {
    const before = posts(env).length;
    await moduleButton(env, module.label).fire("click");
    assert.equal(posts(env).length, before + 1, module.label);
    assert.equal(posts(env).at(-1).path, `/api/pip/portfolios/p-main/modules/${module.id}`);
    const view = describeModuleResult(module.id, moduleResponse(module.id, {}));
    const expected = view.unexpected ? `${view.title} returned an unexpected response.` : `${view.title} finished for AAA.`;
    assert.equal(status(env, "moduleRunStatus"), expected, module.label);
    assertRendered(env, view);
  }
});

test("module buttons are disabled while one runs, and a second click sends nothing", async (t) => {
  const release = gate();
  const env = await connectedPage(t, {
    routes: { [MODULE_PATH("growth")]: async () => { await release.promise; return { json: moduleResponse("growth", GROWTH) }; } },
  });
  await openRunner(env, "AAA");
  const growth = moduleButton(env, "Growth analysis");
  const first = growth.fire("click");
  await waitFor(() => growth.disabled, "the buttons to be disabled");
  assert.ok(moduleButtons(env).every((button) => button.disabled));
  assert.equal(env.el("moduleResult").hidden, true);
  assert.equal(status(env, "moduleRunStatus"), "Running Growth analysis for AAA…");
  await growth.fire("click");
  await moduleButton(env, "Dead money").fire("click");
  assert.equal(posts(env).length, 1);
  release.release();
  await first;
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
  assert.equal(env.el("moduleResult").hidden, false);
});

test("a result for a holding that was left behind is never shown for the new one", async (t) => {
  const release = gate();
  const env = await connectedPage(t, {
    routes: { [MODULE_PATH("growth")]: async () => { await release.promise; return { json: moduleResponse("growth", GROWTH) }; } },
  });
  await openRunner(env, "AAA");
  const run = moduleButton(env, "Growth analysis").fire("click");
  await waitFor(() => moduleButtons(env).every((button) => button.disabled), "the run to start");
  await openRunner(env, "BBB");
  assert.ok(moduleButtons(env).every((button) => !button.disabled), "the new holding can run straight away");
  release.release();
  await run;
  assert.equal(env.el("moduleResult").hidden, true);
  assert.equal(status(env, "moduleRunStatus"), "");
  assert.equal(status(env, "moduleSelected"), "Run modules for BBB");
});

test("a result that arrives after the portfolio was reloaded is ignored", async (t) => {
  const release = gate();
  const env = await connectedPage(t, {
    routes: { [MODULE_PATH("growth")]: async () => { await release.promise; return { json: moduleResponse("growth", GROWTH) }; } },
  });
  await openRunner(env, "AAA");
  const run = moduleButton(env, "Growth analysis").fire("click");
  await waitFor(() => moduleButtons(env).every((button) => button.disabled), "the run to start");
  await env.el("moduleReload").fire("click");
  release.release();
  await run;
  assert.equal(env.el("moduleRunSection").hidden, true);
  assert.equal(env.el("moduleResult").hidden, true);
  assert.equal(rowTexts(env).length, 2);
  assert.ok(env.el("moduleHoldingsBody").children.every((row) => row.className === ""), "no holding stays highlighted after a reload");
  assert.ok(moduleButtons(env).every((button) => !button.disabled), "the reload released the buttons of the abandoned run");
});

test("invalid typed values stop the run with the field's own message and open the inputs", async (t) => {
  const env = await connectedPage(t);
  await openRunner(env, "AAA");
  inputFor(env, "position.market_price").value = "abc";
  await moduleButton(env, "Growth analysis").fire("click");
  assert.deepEqual(posts(env), []);
  assert.equal(status(env, "moduleRunStatus"), "Current share price must be a number.");
  assert.equal(env.el("moduleRunStatus").className, "error");
  assert.equal(env.el("moduleInputs").open, true);
  assert.ok(moduleButtons(env).every((button) => !button.disabled));

  inputFor(env, "position.market_price").value = "";
  inputFor(env, "peer_scores").value = "BBB:150";
  await moduleButton(env, "Replacement candidates").fire("click");
  assert.equal(status(env, "moduleRunStatus"), "Invalid replacement candidate: BBB:150. Use SYMBOL:score from 0 to 100.");
  assert.deepEqual(posts(env), []);

  inputFor(env, "peer_scores").value = "";
  inputFor(env, "position.entry_date").value = "2026-02-30";
  await moduleButton(env, "Position lifecycle").fire("click");
  assert.equal(status(env, "moduleRunStatus"), "Entry date must be a date in YYYY-MM-DD format.");
  assert.deepEqual(posts(env), []);
});

test("a holding whose symbol the API could not accept is stopped before any request", async (t) => {
  const payload = { ...FILLED, holdings: [{ ...AAA, symbol: "AAA/BBB" }] };
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios/p-main/positions": { json: payload } } });
  await openRunner(env, "AAA/BBB");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.deepEqual(posts(env), []);
  assert.match(status(env, "moduleRunStatus"), /^This holding's symbol cannot be analyzed/);
});

test("a 422 validation answer is summarised without echoing what was typed", async (t) => {
  const detail = [{ type: "value_error", loc: ["body", "position", "market_price"], msg: "Value error, must be greater than 0", input: "SECRET-INPUT-123", ctx: { error: "SECRET-CTX" } }];
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: { status: 422, json: { detail } } } });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(status(env, "moduleRunStatus"), "The API rejected these values: position.market_price: must be greater than 0.");
  assert.doesNotMatch(env.el("moduleRunStatus").textContent, /SECRET/);
  assert.equal(env.el("moduleRunStatus").className, "error");
  assert.equal(env.el("moduleResult").hidden, true);
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
});

test("a plain API explanation is shown as it is", async (t) => {
  const detail = "Import this holding into the selected portfolio before analyzing it.";
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: { status: 422, json: { detail } } } });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(status(env, "moduleRunStatus"), detail);
});

test("a network failure while running explains CORS and shows no result", async (t) => {
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: { network: true } } });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.match(status(env, "moduleRunStatus"), /^Could not reach the PIP API\./);
  assert.ok(status(env, "moduleRunStatus").includes("PIP_CORS_ORIGINS"));
  assert.equal(env.el("moduleResult").hidden, true);
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
});

test("a module that never answers is stopped after 90 seconds and can be run again", async (t) => {
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: () => new Promise(() => {}) } });
  await openRunner(env, "AAA");
  const run = moduleButton(env, "Growth analysis").fire("click");
  await waitFor(() => env.pendingTimers() === 1, "the run timer");
  env.fireTimeout();
  await run;
  assert.match(status(env, "moduleRunStatus"), /did not answer within 90 seconds/);
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
  assert.equal(env.pendingTimers(), 0);
});

test("a gateway error and a non-JSON success while running are both errors", async (t) => {
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: { status: 503, unreadable: true } } });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.match(status(env, "moduleRunStatus"), /^The PIP API is not ready \(HTTP 503\)/);
  env.routes[MODULE_PATH("growth")] = { unreadable: true };
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(status(env, "moduleRunStatus"), "The PIP API answered with something that is not valid JSON.");
  assert.equal(env.el("moduleResult").hidden, true);
});

test("an expired sign-in while running shows the reason and sends nothing", async (t) => {
  let valid = true;
  const getAccessToken = async () => {
    if (!valid) throw new Error("Your Supabase session has expired. Sign in again.");
    return "test-token";
  };
  const env = await connectedPage(t, { getAccessToken });
  await openRunner(env, "AAA");
  valid = false;
  await moduleButton(env, "Growth analysis").fire("click");
  assert.deepEqual(posts(env), []);
  assert.equal(status(env, "moduleRunStatus"), "Your Supabase session has expired. Sign in again.");
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
});

test("an answer for the wrong module is flagged instead of shown as a result", async (t) => {
  const env = await connectedPage(t, { routes: { [MODULE_PATH("growth")]: { json: moduleResponse("cps", GROWTH) } } });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(env.el("moduleResult").className, "result unexpected");
  assert.equal(env.el("moduleResult").hidden, false);
  assert.ok(resultText(env).includes("The API returned an unexpected response, so no result is shown."));
  assert.equal(status(env, "moduleRunStatus"), "Growth analysis returned an unexpected response.");
  assert.equal(env.el("moduleRunStatus").className, "error");
  assert.ok(!resultText(env).includes("Read-only result"));
});

test("a result is replaced by the next one and hidden again when another holding is chosen", async (t) => {
  const routes = {
    [MODULE_PATH("growth")]: { json: moduleResponse("growth", GROWTH) },
    [MODULE_PATH("dead_money")]: { json: moduleResponse("dead_money", { is_dead_money: false, confidence: 1, reasons: [] }) },
  };
  const env = await connectedPage(t, { routes });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.ok(resultText(env).includes("Growth analysis"));
  await moduleButton(env, "Dead money").fire("click");
  assert.ok(resultText(env).includes("Not flagged as dead money."));
  assert.ok(!resultText(env).includes("Growth score"));
  await openRunner(env, "BBB");
  assert.equal(env.el("moduleResult").hidden, true);
  assert.equal(resultText(env), "");
});

test("stores only the API address and the chosen portfolio in this browser", async (t) => {
  const env = await connectedPage(t);
  await openRunner(env, "AAA");
  inputFor(env, "position.cost_basis").value = "1234";
  assert.deepEqual([...env.storage.entries()].sort(), [[URL_KEY, DEFAULT_URL], [PORTFOLIO_KEY, "p-main"]]);
});

test("still works when browser storage is blocked", async (t) => {
  const env = await connectedPage(t, { storageBlocked: true });
  assert.equal(env.el("moduleApiUrl").value, DEFAULT_URL);
  assert.equal(rowTexts(env).length, 2);
  assert.equal(env.storage.size, 0);
});

// ---- Out-of-order answers and other edge cases ---------------------------------------------------

test("every connect to a non-default service needs a fresh confirmation", async (t) => {
  const env = await openPage(t, { storage: { [URL_KEY]: OTHER_URL } });
  await env.el("moduleConnect").fire("click");
  await env.el("moduleConnect").fire("click");
  const connected = env.calls.length;
  assert.ok(connected > 0);
  await env.el("moduleConnect").fire("click");
  assert.equal(env.calls.length, connected, "the first click after a connect only asks again");
  assert.match(status(env, "moduleConnectStatus"), /is not the default PIP service/);
  await env.el("moduleConnect").fire("click");
  assert.ok(env.calls.length > connected);
});

test("a remembered address that is not allowed is reported at start-up and nothing is sent", async (t) => {
  const env = await openPage(t, { storage: { [URL_KEY]: "http://example.com" } });
  await settle();
  assert.deepEqual(env.calls, []);
  assert.equal(status(env, "moduleConnectStatus"), "Use HTTPS for the PIP API URL.");
  assert.equal(env.el("moduleConnectStatus").className, "error");
  assert.equal(env.el("moduleConnect").disabled, false);
});

for (const code of [503, 504]) {
  test(`a ${code} without a body also says the service is not ready`, async (t) => {
    const env = await connectedPage(t, { routes: { "GET /healthz": { status: code, unreadable: true } } });
    assert.match(status(env, "moduleConnectStatus"), new RegExp(`^The PIP API is not ready \\(HTTP ${code}\\)`));
  });
}

test("a server error without a body is not mistaken for a service that is waking up", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /healthz": { status: 500, unreadable: true } } });
  assert.equal(status(env, "moduleConnectStatus"), "PIP API request failed (500).");
});

test("typing in the filter before anything is loaded does nothing", async (t) => {
  const env = await openPage(t, { signedIn: false });
  env.el("moduleFilter").value = "aa";
  await env.el("moduleFilter").fire("input");
  assert.deepEqual(rowTexts(env), []);
  assert.equal(status(env, "moduleFilterStatus"), "");
});

test("choosing a portfolio that is not in the list does nothing", async (t) => {
  const env = await connectedPage(t);
  const before = env.calls.length;
  const rows = rowTexts(env);
  env.el("modulePortfolio").value = "p-unknown";
  await env.el("modulePortfolio").fire("change");
  assert.equal(env.calls.length, before);
  assert.deepEqual(rowTexts(env), rows);
});

test("a failed load after a successful one leaves nothing of the old portfolio on screen", async (t) => {
  const env = await connectedPage(t, {
    storage: { [PORTFOLIO_KEY]: "p-main" },
    routes: { "GET /api/pip/portfolios/p-empty/positions": { status: 502, json: { detail: "Unable to load positions." } } },
  });
  env.el("moduleFilter").value = "aa";
  await env.el("moduleFilter").fire("input");
  assert.equal(status(env, "moduleFilterStatus"), "Showing 1 of 2 holdings.");
  await openRunner(env, "AAA");
  env.el("modulePortfolio").value = "p-empty";
  await env.el("modulePortfolio").fire("change");
  assert.equal(status(env, "moduleHoldingsStatus"), "Unable to load positions.");
  assert.deepEqual(rowTexts(env), []);
  for (const id of ["moduleTotals", "moduleFlags", "moduleNotes"]) {
    assert.equal(env.el(id).hidden, true, id);
    assert.equal(env.el(id).children.length, 0, id);
  }
  assert.equal(status(env, "moduleFilterStatus"), "");
  assert.equal(env.el("moduleRunSection").hidden, true);
});

test("the filter message is not shown for a portfolio without holdings", async (t) => {
  const env = await connectedPage(t, { storage: { [PORTFOLIO_KEY]: "p-main" } });
  env.el("moduleFilter").value = "aa";
  await env.el("moduleFilter").fire("input");
  env.el("modulePortfolio").value = "p-new";
  await env.el("modulePortfolio").fire("change");
  assert.deepEqual(rowTexts(env), [["No holdings to show."]]);
  assert.equal(status(env, "moduleFilterStatus"), "");
});

test("says how many newer portfolios were empty, in the singular too", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { json: [PORTFOLIOS[0], PORTFOLIOS[2]] } } });
  assert.equal(env.el("modulePortfolio").value, "p-main");
  assert.equal(
    status(env, "moduleHoldingsStatus"),
    "2 holdings from 3 lots, as of 2026-11-03 10:00 UTC. Showing the newest portfolio that has holdings; 1 newer portfolio is empty.",
  );
});

test("a first portfolio that has holdings gets no extra note", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { json: [PORTFOLIOS[2], PORTFOLIOS[0]] } } });
  assert.equal(status(env, "moduleHoldingsStatus"), "2 holdings from 3 lots, as of 2026-11-03 10:00 UTC.");
});

test("a single empty portfolio gets no extra note", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios": { json: [PORTFOLIOS[0]] } } });
  assert.equal(status(env, "moduleHoldingsStatus"), "This portfolio has no saved holdings.");
});

test("portfolio ids are encoded in every request path", async (t) => {
  const odd = { ...PORTFOLIOS[2], id: "a/b?c#d" };
  const env = await connectedPage(t, {
    routes: {
      "GET /api/pip/portfolios": { json: [odd] },
      "GET /api/pip/portfolios/a%2Fb%3Fc%23d/positions": { json: FILLED },
      "POST /api/pip/portfolios/a%2Fb%3Fc%23d/modules/growth": { json: moduleResponse("growth", GROWTH) },
    },
  });
  assert.equal(rowTexts(env).length, 2);
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(posts(env).length, 1);
  assert.equal(env.el("moduleResult").hidden, false);
});

test("module buttons do nothing before a holding is chosen", async (t) => {
  const env = await connectedPage(t);
  for (const button of moduleButtons(env)) await button.fire("click");
  assert.deepEqual(posts(env), []);
  assert.equal(env.el("moduleRunSection").hidden, true);
  assert.equal(status(env, "moduleRunStatus"), "");
});

test("a lost sign-in object while running is reported and sends nothing", async (t) => {
  const env = await connectedPage(t);
  await openRunner(env, "AAA");
  delete env.window.stockscannerPipAuth;
  await moduleButton(env, "Growth analysis").fire("click");
  assert.deepEqual(posts(env), []);
  assert.equal(status(env, "moduleRunStatus"), "Sign-in is not ready. Reload the page after signing in.");
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
});

test("a superseded holdings load that fails is ignored", async (t) => {
  const release = gate();
  const env = await openPage(t, {
    storage: { [PORTFOLIO_KEY]: "p-main" },
    routes: { "GET /api/pip/portfolios/p-main/positions": async () => { await release.promise; return { status: 502, json: { detail: "Unable to load positions." } }; } },
  });
  await waitFor(() => env.paths().includes("GET /api/pip/portfolios/p-main/positions"), "the first holdings request");
  env.el("modulePortfolio").value = "p-empty";
  await env.el("modulePortfolio").fire("change");
  const message = status(env, "moduleHoldingsStatus");
  assert.equal(message, "This portfolio has no saved holdings.");
  release.release();
  await settle();
  assert.equal(status(env, "moduleHoldingsStatus"), message);
  assert.equal(env.el("moduleHoldingsStatus").className, "subtle");
  assert.equal(env.el("modulePortfolio").value, "p-empty");
  assert.equal(env.el("moduleConnect").disabled, false);
});

test("an old run that fails late cannot disturb a newer run", async (t) => {
  const first = gate();
  const second = gate();
  const notFlagged = { is_dead_money: false, confidence: 1, reasons: [] };
  const env = await connectedPage(t, {
    routes: {
      [MODULE_PATH("growth")]: async () => { await first.promise; return { status: 502, json: { detail: "Old run failed." } }; },
      [MODULE_PATH("dead_money")]: async () => { await second.promise; return { json: moduleResponse("dead_money", notFlagged, { symbol: "BBB" }) }; },
    },
  });
  await openRunner(env, "AAA");
  const oldRun = moduleButton(env, "Growth analysis").fire("click");
  await waitFor(() => moduleButtons(env).every((button) => button.disabled), "the old run to start");
  await openRunner(env, "BBB");
  const newRun = moduleButton(env, "Dead money").fire("click");
  await waitFor(() => posts(env).length === 2, "the new run to start");
  first.release();
  await oldRun;
  assert.equal(status(env, "moduleRunStatus"), "Running Dead money for BBB…");
  assert.ok(moduleButtons(env).every((button) => button.disabled), "the old run must not re-enable the buttons of the new one");
  second.release();
  await newRun;
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
  assert.equal(status(env, "moduleRunStatus"), "Dead money finished for BBB.");
});

test("a holdings load still running when you connect again cannot bring old rows back", async (t) => {
  const release = gate();
  const env = await connectedPage(t, { storage: { [PORTFOLIO_KEY]: "p-main" } });
  env.routes["GET /api/pip/portfolios/p-empty/positions"] = async () => { await release.promise; return { json: FILLED }; };
  env.el("modulePortfolio").value = "p-empty";
  const slow = env.el("modulePortfolio").fire("change");
  await waitFor(() => env.paths().filter((path) => path.endsWith("/p-empty/positions")).length === 1, "the slow load to start");
  env.routes["GET /healthz"] = { network: true };
  await env.el("moduleConnect").fire("click");
  assert.equal(env.el("modulePortfolioSection").hidden, true);
  release.release();
  await slow;
  assert.deepEqual(rowTexts(env), []);
  assert.equal(env.el("modulePortfolioSection").hidden, true);
});

test("a superseded connect that fails late does not overwrite the newer status", async (t) => {
  const release = gate();
  let healthCalls = 0;
  const env = await openPage(t, {
    routes: { "GET /healthz": async () => { healthCalls += 1; if (healthCalls > 1) return { json: HEALTH }; await release.promise; return { network: true }; } },
  });
  await waitFor(() => healthCalls === 1, "the first health check");
  await env.el("moduleConnect").fire("click");
  const message = status(env, "moduleConnectStatus");
  assert.equal(message, `Connected to ${DEFAULT_URL}. 3 portfolios found.`);
  release.release();
  await settle();
  assert.equal(status(env, "moduleConnectStatus"), message);
  assert.equal(env.el("moduleConnectStatus").className, "subtle");
});

test("a superseded connect that was waiting for the portfolio list changes nothing when it finishes", async (t) => {
  const release = gate();
  let listCalls = 0;
  const env = await openPage(t, {
    routes: { "GET /api/pip/portfolios": async () => { listCalls += 1; if (listCalls === 1) await release.promise; return { json: PORTFOLIOS }; } },
  });
  await waitFor(() => listCalls === 1, "the first portfolio request");
  await env.el("moduleConnect").fire("click");
  const paths = env.paths();
  const rows = rowTexts(env);
  release.release();
  await settle();
  assert.deepEqual(env.paths(), paths);
  assert.deepEqual(rowTexts(env), rows);
  assert.equal(env.el("modulePortfolio").value, "p-main");
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${DEFAULT_URL}. 3 portfolios found.`);
});

test("a superseded connect finishing early does not re-enable the button of the newer one", async (t) => {
  const first = gate();
  const second = gate();
  let healthCalls = 0;
  let listCalls = 0;
  const env = await openPage(t, {
    routes: {
      "GET /healthz": async () => { healthCalls += 1; if (healthCalls === 2) await second.promise; return { json: HEALTH }; },
      "GET /api/pip/portfolios": async () => { listCalls += 1; if (listCalls === 1) await first.promise; return { json: PORTFOLIOS }; },
    },
  });
  await waitFor(() => listCalls === 1, "the first portfolio request");
  const again = env.el("moduleConnect").fire("click");
  await waitFor(() => healthCalls === 2, "the second health check");
  first.release();
  await settle();
  assert.equal(env.el("moduleConnect").disabled, true);
  assert.equal(env.el("moduleConnect").textContent, "Connecting…");
  second.release();
  await again;
  await waitFor(() => loaded(env), "the page to finish connecting");
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${DEFAULT_URL}. 3 portfolios found.`);
});

test("a failed holdings request while looking for the first portfolio with holdings stops there", async (t) => {
  const env = await connectedPage(t, { routes: { "GET /api/pip/portfolios/p-new/positions": { status: 502, json: { detail: "Unable to load positions." } } } });
  assert.deepEqual(env.paths().filter((path) => path.endsWith("/positions")), ["GET /api/pip/portfolios/p-new/positions"]);
  assert.equal(status(env, "moduleHoldingsStatus"), "Unable to load positions.");
  assert.equal(env.el("moduleHoldingsStatus").className, "error");
  assert.deepEqual(rowTexts(env), []);
  assert.equal(env.storage.has(PORTFOLIO_KEY), false, "a failed load remembers nothing");
  assert.equal(status(env, "moduleConnectStatus"), `Connected to ${DEFAULT_URL}. 3 portfolios found.`);
  env.routes["GET /api/pip/portfolios/p-new/positions"] = { json: EMPTY };
  await env.el("moduleReload").fire("click");
  assert.equal(env.el("modulePortfolio").value, "p-new", "Reload retries the portfolio that failed");
  assert.equal(status(env, "moduleHoldingsStatus"), "This portfolio has no saved holdings.");
});

test("Reload holdings reloads the chosen portfolio and does not skip ahead to one with holdings", async (t) => {
  const env = await connectedPage(t);
  const before = env.calls.length;
  env.el("modulePortfolio").value = "p-new";
  await env.el("modulePortfolio").fire("change");
  await env.el("moduleReload").fire("click");
  assert.deepEqual(env.paths().slice(before), ["GET /api/pip/portfolios/p-new/positions", "GET /api/pip/portfolios/p-new/positions"]);
  assert.equal(env.el("modulePortfolio").value, "p-new");
  assert.equal(status(env, "moduleHoldingsStatus"), "This portfolio has no saved holdings.");
  assert.deepEqual(rowTexts(env), [["No holdings to show."]]);
});

test("a failed reconnect leaves nothing of the previous connection on screen", async (t) => {
  const env = await connectedPage(t, {
    storage: { [PORTFOLIO_KEY]: "p-main" },
    routes: { [MODULE_PATH("growth")]: { json: moduleResponse("growth", GROWTH) } },
  });
  env.el("moduleFilter").value = "aa";
  await env.el("moduleFilter").fire("input");
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(env.el("moduleResult").hidden, false);
  assert.equal(status(env, "moduleRunStatus"), "Growth analysis finished for AAA.");

  env.routes["GET /healthz"] = { network: true };
  await env.el("moduleConnect").fire("click");

  assert.match(status(env, "moduleConnectStatus"), /^Could not reach the PIP API\./);
  assert.equal(env.el("moduleConnectStatus").className, "error");
  assert.equal(env.el("modulePortfolioSection").hidden, true);
  assert.equal(env.el("modulePortfolio").children.length, 0);
  assert.deepEqual(rowTexts(env), []);
  assert.equal(status(env, "moduleHoldingsStatus"), "");
  assert.equal(status(env, "moduleFilterStatus"), "");
  for (const id of ["moduleTotals", "moduleFlags", "moduleNotes"]) {
    assert.equal(env.el(id).hidden, true, id);
    assert.equal(env.el(id).children.length, 0, id);
  }
  assert.equal(env.el("moduleRunSection").hidden, true);
  assert.equal(env.el("moduleResult").hidden, true);
  assert.equal(resultText(env), "");
  assert.equal(status(env, "moduleRunStatus"), "");
  assert.ok(moduleButtons(env).every((button) => !button.disabled));

  const before = env.calls.length;
  env.el("moduleFilter").value = "bb";
  await env.el("moduleFilter").fire("input");
  env.el("modulePortfolio").value = "p-main";
  await env.el("modulePortfolio").fire("change");
  await env.el("moduleReload").fire("click");
  assert.equal(env.calls.length, before, "nothing is requested without a connection");
  assert.deepEqual(rowTexts(env), []);
  assert.equal(status(env, "moduleHoldingsStatus"), "");
  assert.equal(status(env, "moduleFilterStatus"), "");
});

test("starting another module hides the previous result until the new one arrives", async (t) => {
  const release = gate();
  const env = await connectedPage(t, {
    routes: {
      [MODULE_PATH("growth")]: { json: moduleResponse("growth", GROWTH) },
      [MODULE_PATH("dead_money")]: async () => {
        await release.promise;
        return { json: moduleResponse("dead_money", { is_dead_money: false, confidence: 1, reasons: [] }) };
      },
    },
  });
  await openRunner(env, "AAA");
  await moduleButton(env, "Growth analysis").fire("click");
  assert.equal(env.el("moduleResult").hidden, false);
  const second = moduleButton(env, "Dead money").fire("click");
  await waitFor(() => moduleButtons(env).every((button) => button.disabled), "the second run to start");
  assert.equal(env.el("moduleResult").hidden, true, "the previous result is not shown beside a pending run");
  assert.equal(status(env, "moduleRunStatus"), "Running Dead money for AAA…");
  release.release();
  await second;
  assert.equal(env.el("moduleResult").hidden, false);
  assert.ok(resultText(env).includes("Not flagged as dead money."));
});

test("a sign-in object without a token function is reported and sends nothing", async (t) => {
  const env = await connectedPage(t);
  await openRunner(env, "AAA");
  for (const broken of [{}, { getAccessToken: "not a function" }]) {
    env.window.stockscannerPipAuth = broken;
    await moduleButton(env, "Growth analysis").fire("click");
    assert.equal(status(env, "moduleRunStatus"), "Sign-in is not ready. Reload the page after signing in.");
    assert.equal(env.el("moduleRunStatus").className, "error");
  }
  assert.deepEqual(posts(env), []);
  assert.ok(moduleButtons(env).every((button) => !button.disabled));
});

for (const [kind, failure] of [
  ["is plain text", "boom"],
  ["has an empty message", new Error("")],
  ["has a message that is not text", { message: 42 }],
]) {
  test(`a sign-in failure that ${kind} is reported with a generic explanation`, async (t) => {
    const env = await connectedPage(t, { getAccessToken: async () => { throw failure; } });
    assert.equal(status(env, "moduleConnectStatus"), "Something went wrong. Try again.");
    assert.equal(env.el("moduleConnectStatus").className, "error");
    assert.equal(env.el("modulePortfolioSection").hidden, true);
    assert.equal(env.el("moduleConnect").disabled, false);
  });
}

test("a result is laid out as heading, headline, facts, details, hints, caveats and footer", async (t) => {
  const response = moduleResponse("sell_advisor", {
    recommendation: "watch",
    sell_score: null,
    cps: null,
    confidence: 0.2,
    replacement_candidates: [{ symbol: "BBB", expected_benefit: 4.2 }],
    rationale: ["Only a few inputs were supplied."],
  });
  const view = describeModuleResult("sell_advisor", response);
  assert.ok(view.rows.length > 1 && view.details.length && view.hints.length && view.caveats.length && view.footer, "the sample exercises every part");
  const env = await connectedPage(t, { routes: { [MODULE_PATH("sell_advisor")]: { json: response } } });
  await openRunner(env, "AAA");
  await moduleButton(env, "Sell advisor").fire("click");

  const parts = env.el("moduleResult").children;
  assert.deepEqual(
    parts.map((part) => `${part.tagName}.${part.className}`),
    ["H3.", "P.headline", "DL.facts", "UL.", "DIV.hints", "UL.caveats", "P.result-footer"],
  );
  assert.equal(parts[0].textContent, `${view.title} · AAA`);
  assert.equal(parts[1].textContent, view.headline);
  assert.deepEqual(
    parts[2].children.map((node) => [node.tagName, node.textContent]),
    view.rows.flatMap(([label, value]) => [["DT", label], ["DD", value]]),
  );
  const items = (list) => list.children.map((item) => [item.tagName, item.textContent]);
  assert.deepEqual(items(parts[3]), view.details.map((line) => ["LI", line]));
  assert.deepEqual(parts[4].children.map((node) => [node.tagName, node.className]), [["STRONG", ""], ["UL", ""]]);
  assert.equal(parts[4].children[0].textContent, "To get a fuller answer");
  assert.deepEqual(items(parts[4].children[1]), view.hints.map((line) => ["LI", line]));
  assert.deepEqual(items(parts[5]), view.caveats.map((line) => ["LI", line]));
  assert.equal(parts[6].textContent, view.footer);
});

// ---- The page and its source ---------------------------------------------------------------------

test("every element the script looks up exists in the page, and ids are unique", () => {
  const wanted = [...PAGE_SCRIPT.matchAll(/querySelector\(\s*"#([A-Za-z0-9_-]+)"\s*\)/g)].map((match) => match[1]);
  assert.ok(wanted.length >= 20);
  const ids = [...PAGE_HTML.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, "duplicate ids in pip-modules.html");
  for (const id of wanted) assert.ok(ids.includes(id), `pip-modules.html has no #${id}`);
  for (const id of ids.filter((item) => item.startsWith("module"))) {
    assert.ok(PAGE_SCRIPT.includes(`"#${id}"`) || ["moduleIntro", "moduleConnectTitle", "moduleHoldingsTitle"].includes(id), `#${id} is not used by the script`);
  }
});

test("the page is gated, noindex, signed-in only and marked as the current nav item", () => {
  assert.match(PAGE_HTML, /<meta name="robots" content="noindex">/);
  assert.match(PAGE_HTML, /<link rel="stylesheet" href="\/StockScanner\/personal-lists\.css">/);
  assert.match(PAGE_HTML, /<script type="module" src="\/StockScanner\/auth\.js" data-stockscanner-auth><\/script>/);
  assert.match(PAGE_HTML, /<script type="module" src="\/StockScanner\/pip-modules\.js\?v=[\w-]+" data-stockscanner-pip-api><\/script>/);
  assert.match(PAGE_HTML, /<a href="\/StockScanner\/pip-modules\.html" aria-current="page">Module runner<\/a>/);
  assert.match(PAGE_HTML, /<a href="\/StockScanner\/portfolio-intelligence\.html">PIP workbench<\/a>/);
  assert.equal([...PAGE_HTML.matchAll(/<script\b/g)].length, 2, "only the auth gate and the page script");
  for (const id of ["moduleRunSection", "modulePortfolioSection", "moduleResult", "moduleHints"]) {
    assert.match(PAGE_HTML, new RegExp(`id="${id}"[^>]*\\shidden`), `#${id} starts hidden`);
  }
  assert.match(PAGE_HTML, /id="moduleConnect"[^>]*\sdisabled/);
  assert.match(PAGE_HTML, /\[hidden\] \{ display: none !important; \}/);
});

test("the script can only read: four request shapes, GET and POST, no unsafe DOM", () => {
  const code = PAGE_SCRIPT.replace(/^\s*\/\/.*$/gm, "");
  const paths = [...code.matchAll(/["'`](\/(?:healthz|api\/pip)[^"'`]*)["'`]/g)].map((match) => match[1].replace(/\$\{[^}]*\}/g, "{}"));
  assert.deepEqual([...new Set(paths)].sort(), [
    "/api/pip/portfolios",
    "/api/pip/portfolios/{}/modules/{}",
    "/api/pip/portfolios/{}/positions",
    "/healthz",
  ]);
  assert.deepEqual([...code.matchAll(/\bmethod\s*[:=]\s*"([A-Z]+)"/g)].map((match) => match[1]).sort(), ["GET", "POST"]);
  assert.doesNotMatch(code, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function|\bsrcdoc\b/);
  assert.doesNotMatch(code, /\/analysis|\/transitions|\/sync|\/import|\/approv|\/order|\/audit|\/flex/i);
  assert.doesNotMatch(code, /console\.|sessionStorage|document\.cookie|indexedDB/);
  assert.doesNotMatch(code, /pip-dashboard/);
  assert.deepEqual([...code.matchAll(/writeStored\(([A-Z_]+),/g)].map((match) => match[1]).sort(), ["API_URL_KEY", "PORTFOLIO_KEY"]);
  assert.match(code, /credentials: "omit"/);
});

test("the script does nothing when there is no document", async () => {
  const before = Object.getOwnPropertyDescriptor(globalThis, "document");
  assert.equal(before, undefined, "this test expects a Node environment without a DOM");
  await import("../pip-modules.js?no-document");
});
