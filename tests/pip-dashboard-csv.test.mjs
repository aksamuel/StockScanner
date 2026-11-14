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
    this.checked = false;
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

  querySelectorAll() {
    return [];
  }

  get selectedOptions() {
    return this.children.filter((child) => child.value === this.value).slice(0, 1);
  }

  async fire(type) {
    await this.listeners.get(type)?.({ currentTarget: this, target: this });
  }
}

const CSV = "Symbol,Quantity,CostBasis,TradeDate,Currency\nAAA,2,240,2025-01-02,USD";
const SAVED = "Saved 1 positions, 0 transactions, 0 dividends, and 0 masked accounts to Supabase.";
const WARNING = "Market value is missing for 1 of 1 position; returns and the portfolio review skip positions without one.";
const COUNTS = { accounts: 0, positions: 1, transactions: 0, dividends: 0 };

let importRuns = 0;

async function importCsv(importResponse) {
  const elements = new Map();
  const get = (selector) => {
    if (!elements.has(selector)) {
      elements.set(selector, new Element(selector.endsWith("Select") ? "select" : "div"));
    }
    return elements.get(selector);
  };
  const requests = [];
  const response = (data) => ({ ok: true, status: 200, json: async () => data });

  globalThis.document = {
    querySelector: get,
    querySelectorAll: () => [],
    createElement: (tag) => new Element(tag),
    addEventListener: () => {},
  };
  globalThis.window = {
    stockscannerPipAuth: { getAccessToken: async () => "synthetic-test-token" },
    confirm: () => false,
    addEventListener: () => {},
  };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.fetch = async (url, options) => {
    const path = new URL(url).pathname;
    requests.push({ path, options });
    if (path === "/healthz") return response({ status: "ok", service: "pip" });
    if (path === "/api/pip/portfolios") {
      return response([{ id: "portfolio-1", name: "Test", currency: "USD" }]);
    }
    if (path.endsWith("/recommendations")) return response([]);
    if (path.endsWith("/ibkr-flex-connections")) return response([]);
    if (path.endsWith("/sync/csv")) return response(importResponse);
    throw new Error(`Unexpected request: ${path}`);
  };

  try {
    importRuns += 1;
    await import(`../pip-dashboard.js?csv-ui-test-${importRuns}`);
    await get("#connectApi").fire("click");
    get("#portfolioSelect").value = "portfolio-1";
    await get("#portfolioSelect").fire("change");
    get("#csvFile").files = [{ size: CSV.length, name: "positions.csv", text: async () => CSV }];
    await get("#csvFile").fire("change");
    assert.match(
      get("#csvStatus").textContent,
      /^1 position, 0 transactions, 0 dividends validated locally from positions\.csv\./,
    );
    await get("#importCsv").fire("click");
    return { status: get("#csvStatus").textContent, requests };
  } finally {
    delete globalThis.document;
    delete globalThis.window;
    delete globalThis.localStorage;
    delete globalThis.fetch;
  }
}

test("a CSV import shows the API's warnings after what was saved", async () => {
  const { status, requests } = await importCsv({
    counts: COUNTS,
    warnings: [WARNING, "A second warning."],
  });

  assert.equal(status, `${SAVED} ${WARNING} A second warning.`);
  const upload = requests.find((request) => request.path.endsWith("/sync/csv"));
  assert.equal(upload.path, "/api/pip/portfolios/portfolio-1/sync/csv");
  assert.equal(upload.options.method, "POST");
  assert.equal(upload.options.body, CSV);
});

test("a CSV import with no warnings, or an API that predates them, shows only what was saved", async () => {
  for (const body of [{ counts: COUNTS, warnings: [] }, { counts: COUNTS }]) {
    const { status } = await importCsv(body);
    assert.equal(status, SAVED);
  }
});
