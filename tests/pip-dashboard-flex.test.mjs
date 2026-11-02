import assert from "node:assert/strict";
import test from "node:test";

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.value = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
    if (this.tagName === "SELECT") this.value = "";
  }

  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }

  setAttribute() {}

  querySelectorAll(selector) {
    const matches = [];
    for (const child of this.children) {
      if (selector === "button" && child.tagName === "BUTTON") matches.push(child);
      matches.push(...child.querySelectorAll(selector));
    }
    return matches;
  }

  get selectedOptions() {
    return this.children.filter((child) => child.value === this.value).slice(0, 1);
  }

  async fire(type) {
    await this.listeners.get(type)?.({ currentTarget: this, target: this });
  }
}

test("Flex sync requires confirmation, a compatible API, and a stable portfolio selection", async () => {
  const elements = new Map();
  const get = (selector) => {
    if (!elements.has(selector)) {
      elements.set(selector, new Element(selector.endsWith("Select") ? "select" : "div"));
    }
    return elements.get(selector);
  };
  const requests = [];
  const confirmations = [];
  let confirmed = false;
  let snapshotVersion = 1;
  let healthGate = null;
  let healthRequested = null;
  let releaseHealth = null;
  let signalHealth = null;
  let syncError = null;
  const response = (data) => ({ ok: true, status: 200, json: async () => data });

  globalThis.document = {
    querySelector: get,
    querySelectorAll: () => [],
    createElement: (tag) => new Element(tag),
    addEventListener: () => {},
  };
  globalThis.window = {
    stockscannerPipAuth: { getAccessToken: async () => "synthetic-test-token" },
    confirm: (message) => {
      confirmations.push(message);
      return confirmed;
    },
    addEventListener: () => {},
  };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.fetch = async (url, options) => {
    const path = new URL(url).pathname;
    requests.push({ path, options });
    if (path === "/healthz") {
      if (healthGate) {
        signalHealth();
        await healthGate;
      }
      return response({ status: "ok", service: "pip", flex_position_snapshot_sync: snapshotVersion });
    }
    if (path === "/api/pip/portfolios") {
      return response([{ id: "portfolio-1", name: "Test", currency: "USD" }]);
    }
    if (path.endsWith("/recommendations")) return response([]);
    if (path.endsWith("/ibkr-flex-connections")) {
      return response([{ id: "connection-1", connection_name: "Test", last_synced_at: null }]);
    }
    if (path.endsWith("/sync")) {
      if (syncError) {
        return { ok: false, status: 413, json: async () => ({ detail: syncError }) };
      }
      return response({
        counts: { accounts: 1, positions: 1, transactions: 0, dividends: 0 },
        accounts: [{ masked_account_id: "***4567", currency: "USD", statement_date: "2025-01-31" }],
        warnings: ["No Trades section was returned for at least one account."],
      });
    }
    throw new Error(`Unexpected request: ${path}`);
  };

  try {
    await import("../pip-dashboard.js?flex-ui-test");
    await get("#connectApi").fire("click");
    get("#portfolioSelect").value = "portfolio-1";
    await get("#portfolioSelect").fire("change");
    const syncButton = get("#flexConnectionList").querySelectorAll("button")
      .find((button) => button.textContent === "Sync statement");
    assert.ok(syncButton);

    await syncButton.fire("click");
    assert.equal(requests.filter((request) => request.path.endsWith("/sync")).length, 0);
    assert.match(confirmations[0], /unfiltered/i);
    assert.match(confirmations[0], /CSV\/manual imports and history are retained/);

    confirmed = true;
    snapshotVersion = 0;
    await syncButton.fire("click");
    assert.equal(requests.filter((request) => request.path.endsWith("/sync")).length, 0);
    assert.match(get("#flexStatus").textContent, /API must be updated/);

    snapshotVersion = 1;
    healthGate = new Promise((resolve) => { releaseHealth = resolve; });
    healthRequested = new Promise((resolve) => { signalHealth = resolve; });
    const pending = syncButton.fire("click");
    await healthRequested;
    get("#portfolioSelect").value = "portfolio-2";
    releaseHealth();
    await pending;
    healthGate = null;
    assert.equal(requests.filter((request) => request.path.endsWith("/sync")).length, 0);
    assert.match(get("#flexStatus").textContent, /portfolio changed/i);

    get("#portfolioSelect").value = "portfolio-1";
    await syncButton.fire("click");
    const syncRequests = requests.filter((request) => request.path.endsWith("/sync"));
    assert.equal(syncRequests.length, 1);
    assert.equal(syncRequests[0].path, "/api/pip/portfolios/portfolio-1/ibkr-flex-connections/connection-1/sync");
    assert.deepEqual(JSON.parse(syncRequests[0].options.body), { confirm_unfiltered: true });
    assert.match(get("#flexStatus").textContent, /Synced 1 positions/);
    assert.match(get("#flexStatus").textContent, /statement 2025-01-31/);
    assert.match(get("#flexStatus").textContent, /No Trades section was returned/);

    syncError = "The IBKR Flex statement exceeds 5 MB. Reduce selected fields or the report period.";
    const refreshedSyncButton = get("#flexConnectionList").querySelectorAll("button")
      .find((button) => button.textContent === "Sync statement");
    await refreshedSyncButton.fire("click");
    assert.equal(get("#flexStatus").textContent, syncError);
  } finally {
    delete globalThis.document;
    delete globalThis.window;
    delete globalThis.localStorage;
    delete globalThis.fetch;
  }
});
