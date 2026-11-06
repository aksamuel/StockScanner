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

function analysisFor(hurdle) {
  return {
    recommendation: { id: "recommendation-1", symbol: "TEST", recommendation: "watch", replacement_candidates: [] },
    analysis: { cps: null, sell_score: null, confidence: 0, rationale: ["Insufficient data."] },
    modules: {
      lifecycle: { days_held: 730, total_return_percent: null },
      dead_money: { is_dead_money: null, confidence: 0 },
      dividends: { trailing_twelve_month_income: null, current_yield_pct: null },
      growth: { score: null, confidence: 0 },
      forward_looking: { score: null, confidence: 0 },
      opportunity_cost: { available: false, reasons: ["No alternatives supplied."], items: [] },
      hurdle,
    },
  };
}

function hurdleResult(overrides = {}) {
  return {
    required_annual_return_percent: 7,
    status: "below",
    outlook_status: "unavailable",
    lot_count: 1,
    days_held: 730,
    return_basis: "total",
    return_percent: 10,
    hurdle_return_percent: 14.49,
    annualized_return_percent: 4.88,
    shortfall_amount: 4.49,
    required_return_by_horizon: [{ years: 1, required_annual_return_percent: 11.3 }],
    forward_return_percent: null,
    holding_assumed_return_percent: null,
    years_to_catch_up: null,
    replacement_assumed_return_percent: null,
    replacement_months_to_hurdle_gain: null,
    reasons: [],
    note: "Scenario figures are arithmetic from the assumed returns, not forecasts.",
    ...overrides,
  };
}

function createHarness({ health = { status: "ok", hurdle_analysis: 1 }, analysis = analysisFor(hurdleResult()) } = {}) {
  const elements = new Map();
  const get = (selector) => {
    if (!elements.has(selector)) {
      elements.set(selector, new Element(selector.endsWith("Select") ? "select" : "div"));
    }
    return elements.get(selector);
  };
  const requests = [];
  const control = { health, analysis, analysisFailure: null, healthGate: null, signalHealth: null };
  const response = (data) => ({ ok: true, status: 200, json: async () => data });

  globalThis.document = {
    querySelector: get,
    querySelectorAll: () => [],
    createElement: (tag) => new Element(tag),
    addEventListener: () => {},
  };
  globalThis.window = {
    stockscannerPipAuth: { getAccessToken: async () => "synthetic-test-token" },
    confirm: () => true,
    addEventListener: () => {},
  };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.fetch = async (url, options) => {
    const path = new URL(url).pathname;
    requests.push({ path, options });
    if (path === "/healthz") {
      if (control.healthGate) {
        control.signalHealth();
        await control.healthGate;
      }
      return response(control.health);
    }
    if (path === "/api/pip/portfolios") {
      return response([
        { id: "portfolio-1", name: "First", currency: "USD" },
        { id: "portfolio-2", name: "Second", currency: "USD" },
      ]);
    }
    if (path === "/api/pip/analysis") {
      if (control.analysisFailure) {
        return { ok: false, status: control.analysisFailure.status, json: async () => ({ detail: control.analysisFailure.detail }) };
      }
      return response(control.analysis);
    }
    if (path.endsWith("/recommendations")) {
      return response([{ id: "recommendation-1", symbol: "TEST", recommendation: "watch", status: "proposed" }]);
    }
    if (path.endsWith("/events")) return response([]);
    if (path.endsWith("/ibkr-flex-connections")) return response([]);
    throw new Error(`Unexpected request: ${path}`);
  };

  return {
    get,
    requests,
    control,
    analysisRequests: () => requests.filter((request) => request.path === "/api/pip/analysis"),
    cleanup() {
      delete globalThis.document;
      delete globalThis.window;
      delete globalThis.localStorage;
      delete globalThis.fetch;
    },
  };
}

async function connectAndSelect({ get }, portfolioId = "portfolio-1") {
  await get("#connectApi").fire("click");
  get("#portfolioSelect").value = portfolioId;
  await get("#portfolioSelect").fire("change");
}

test("analysis sends the 7% default hurdle and shows the returned hurdle result", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?analysis-ui-default");
    await connectAndSelect(harness);
    get("#analysisSymbol").value = "test";
    await get("#analyzePosition").fire("click");

    const analysisRequests = harness.analysisRequests();
    assert.equal(analysisRequests.length, 1);
    const paths = requests.map((request) => request.path);
    assert.equal(paths[paths.indexOf("/api/pip/analysis") - 1], "/healthz");
    const body = JSON.parse(analysisRequests[0].options.body);
    assert.equal(body.portfolio_id, "portfolio-1");
    assert.equal(body.symbol, "TEST");
    assert.deepEqual(body.hurdle, {
      required_annual_return_percent: 7,
      holding_assumed_return_percent: null,
      replacement_assumed_return_percent: null,
    });

    assert.equal(get("#analysisStatus").textContent, "Analysis saved. The recommendation is available in the human approval workflow.");
    assert.equal(get("#analysisResult").hidden, false);
    const rendered = get("#analysisResult").children.map((child) => child.textContent);
    assert.ok(rendered.some((text) => text.startsWith("Return hurdle (7% per year): below the hurdle path.")));
    assert.equal(get("#analyzePosition").disabled, false);
  } finally {
    harness.cleanup();
  }
});

test("analysis sends custom hurdle and what-if returns, and omits a blank required return", async () => {
  const analysis = analysisFor(hurdleResult({
    required_annual_return_percent: 7.5,
    holding_assumed_return_percent: 12,
    years_to_catch_up: 3.9,
    replacement_assumed_return_percent: 15.25,
    replacement_months_to_hurdle_gain: 5.8,
  }));
  const harness = createHarness({ analysis });
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?analysis-ui-custom");
    await connectAndSelect(harness);
    get("#analysisSymbol").value = "test";
    get("#pipRequiredReturn").value = "7.5";
    get("#pipHoldingAssumedReturn").value = "12";
    get("#pipReplacementAssumedReturn").value = "15.25";
    await get("#analyzePosition").fire("click");

    assert.deepEqual(JSON.parse(harness.analysisRequests()[0].options.body).hurdle, {
      required_annual_return_percent: 7.5,
      holding_assumed_return_percent: 12,
      replacement_assumed_return_percent: 15.25,
    });
    const rendered = get("#analysisResult").children.map((child) => child.textContent).join(" ");
    assert.match(rendered, /Return hurdle \(7\.5% per year\): below the hurdle path\./);
    assert.match(rendered, /Scenario: at an assumed 12% per year this holding would catch up with the hurdle path in about 3\.9 years\./);
    assert.match(rendered, /Scenario: a replacement assumed to earn 15\.25% per year would take about 5\.8 months to gain 7\.5%\./);
    assert.match(rendered, /not forecasts/);

    get("#pipRequiredReturn").value = "";
    get("#pipHoldingAssumedReturn").value = "";
    get("#pipReplacementAssumedReturn").value = "";
    await get("#analyzePosition").fire("click");
    assert.deepEqual(JSON.parse(harness.analysisRequests()[1].options.body).hurdle, {
      holding_assumed_return_percent: null,
      replacement_assumed_return_percent: null,
    });
  } finally {
    harness.cleanup();
  }
});

test("analysis is refused when the API does not report return hurdle support", async () => {
  for (const [index, health] of [{ status: "ok" }, { status: "ok", hurdle_analysis: 0 }].entries()) {
    const harness = createHarness({ health });
    const { get } = harness;
    try {
      await import(`../pip-dashboard.js?analysis-ui-old-api-${index}`);
      await connectAndSelect(harness);
      get("#analysisSymbol").value = "test";
      await get("#analyzePosition").fire("click");

      assert.equal(harness.analysisRequests().length, 0);
      assert.equal(get("#analysisStatus").textContent, "The PIP API must be updated before return hurdle analysis is available.");
      assert.equal(get("#analysisResult").hidden, true);
      assert.equal(get("#analyzePosition").disabled, false);
    } finally {
      harness.cleanup();
    }
  }
});

test("invalid hurdle inputs are rejected before any request is sent", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?analysis-ui-invalid");
    await connectAndSelect(harness);
    get("#analysisSymbol").value = "test";
    const cases = [
      ["#pipRequiredReturn", "-1", "Required annual return must be at least 0."],
      ["#pipRequiredReturn", "100.5", "Required annual return must be no more than 100."],
      ["#pipRequiredReturn", "abc", "Required annual return must be a number."],
      ["#pipHoldingAssumedReturn", "-100", "What-if return for this holding must be at least -99.99."],
      ["#pipReplacementAssumedReturn", "1000.5", "What-if return for a replacement must be no more than 1000."],
    ];
    for (const [id, value, message] of cases) {
      const before = requests.length;
      get(id).value = value;
      await get("#analyzePosition").fire("click");
      assert.equal(get("#analysisStatus").textContent, message);
      assert.equal(requests.length, before);
      assert.equal(get("#analysisResult").hidden, true);
      get(id).value = id === "#pipRequiredReturn" ? "7" : "";
    }
    assert.equal(harness.analysisRequests().length, 0);
  } finally {
    harness.cleanup();
  }
});

test("analysis is discarded when the portfolio selection changes during the compatibility check", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?analysis-ui-stale");
    await connectAndSelect(harness);
    get("#analysisSymbol").value = "test";
    let releaseHealth;
    harness.control.healthGate = new Promise((resolve) => { releaseHealth = resolve; });
    const healthRequested = new Promise((resolve) => { harness.control.signalHealth = resolve; });
    const pending = get("#analyzePosition").fire("click");
    await healthRequested;
    get("#portfolioSelect").value = "portfolio-2";
    releaseHealth();
    await pending;
    harness.control.healthGate = null;

    assert.equal(harness.analysisRequests().length, 0);
    assert.match(get("#analysisStatus").textContent, /portfolio changed/i);
    assert.equal(get("#analysisResult").hidden, true);
  } finally {
    harness.cleanup();
  }
});

test("an API failure is shown as an error and no analysis result is displayed", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?analysis-ui-failure");
    await connectAndSelect(harness);
    get("#analysisSymbol").value = "test";
    harness.control.analysisFailure = { status: 502, detail: "The PIP data service request failed." };
    const before = requests.length;
    await get("#analyzePosition").fire("click");

    assert.equal(get("#analysisStatus").textContent, "The PIP data service request failed.");
    assert.equal(get("#analysisResult").hidden, true);
    assert.deepEqual(requests.slice(before).map((request) => request.path), ["/healthz", "/api/pip/analysis"]);
    assert.equal(get("#analyzePosition").disabled, false);
  } finally {
    harness.cleanup();
  }
});

test("switching portfolios restores the 7% default and clears the what-if returns", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?analysis-ui-reset");
    await connectAndSelect(harness);
    assert.equal(get("#pipRequiredReturn").value, "7");

    get("#pipRequiredReturn").value = "9";
    get("#pipHoldingAssumedReturn").value = "5";
    get("#pipReplacementAssumedReturn").value = "11";
    get("#portfolioSelect").value = "portfolio-2";
    await get("#portfolioSelect").fire("change");

    assert.equal(get("#pipRequiredReturn").value, "7");
    assert.equal(get("#pipHoldingAssumedReturn").value, "");
    assert.equal(get("#pipReplacementAssumedReturn").value, "");
    assert.equal(get("#analysisResult").hidden, true);
  } finally {
    harness.cleanup();
  }
});
