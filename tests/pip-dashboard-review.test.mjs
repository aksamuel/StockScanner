import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

const REVIEW_PATH = "/api/pip/portfolios/portfolio-1/review";
const READ_ONLY_STATUS = "Review complete. It is read-only: nothing was saved and no orders were placed.";

function hurdleFor(overrides = {}) {
  return {
    symbol: "AAA",
    required_annual_return_percent: 7,
    status: "unavailable",
    outlook_status: "unavailable",
    lot_count: 1,
    days_held: 730,
    return_basis: "price_only",
    return_percent: 4.2,
    hurdle_return_percent: 14.49,
    excess_return_percentage_points: -10.29,
    annualized_return_percent: 2.08,
    shortfall_amount: 123.45,
    required_return_by_horizon: [{ years: 1, required_annual_return_percent: 11.3 }],
    forward_return_percent: null,
    holding_assumed_return_percent: null,
    years_to_catch_up: null,
    replacement_assumed_return_percent: null,
    replacement_months_to_hurdle_gain: null,
    reasons: ["Dividends received are unavailable or invalid."],
    note: "Scenario figures are arithmetic from the assumed returns, not forecasts.",
    ...overrides,
  };
}

function holdingFor(overrides = {}) {
  return {
    rank: 1,
    symbol: "AAA",
    currency: "USD",
    hurdle: hurdleFor(),
    cps: 35,
    dead_money: {
      symbol: "AAA",
      is_dead_money: null,
      confidence: 0.6,
      reasons: ["A verdict is withheld until dividends received are entered."],
    },
    replacements: {
      compared: true,
      reasons: [],
      candidates: [{ symbol: "BBB", score: 82, rationale: ["Hidden rationale."], expected_benefit: 47, confidence: 0.82 }],
    },
    ...overrides,
  };
}

function reviewFor({ summary = {}, ...overrides } = {}) {
  return {
    review: {
      required_annual_return_percent: 7,
      minimum_holding_days: 365,
      top_n: 5,
      summary: {
        holdings: 4,
        not_analysable: 1,
        held_under_minimum: 1,
        meeting_hurdle: 1,
        behind_hurdle: 1,
        truncated: false,
        ...summary,
      },
      top: [holdingFor()],
      skipped: [{
        reason: "no_entry_date",
        message: "Entry date is unavailable for at least one lot, so holding time cannot be measured.",
        count: 1,
        symbols: ["CCC"],
      }],
      notes: [
        "Ranking is a comparison, not a forecast.",
        "This review only reads saved data. PIP never places or transmits orders.",
      ],
      ...overrides,
    },
  };
}

function createHarness({
  health = { status: "ok", hurdle_analysis: 1, portfolio_review: 1 },
  review = reviewFor(),
} = {}) {
  const elements = new Map();
  const get = (selector) => {
    if (!elements.has(selector)) {
      elements.set(selector, new Element(selector.endsWith("Select") ? "select" : "div"));
    }
    return elements.get(selector);
  };
  const requests = [];
  const control = {
    health,
    review,
    reviewFailure: null,
    reviewQueue: [],
    healthGate: null,
    signalHealth: null,
    reviewGate: null,
    signalReview: null,
  };
  const response = (data) => ({ ok: true, status: 200, json: async () => data });

  get("#runReview").textContent = "Review portfolio";
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
    if (path.endsWith("/review")) {
      const next = control.reviewQueue.shift() ?? {};
      const waitFor = next.gate ?? control.reviewGate;
      if (waitFor) {
        (next.signal ?? control.signalReview)();
        await waitFor;
      }
      const failure = next.failure ?? control.reviewFailure;
      if (failure) {
        return { ok: false, status: failure.status, json: async () => ({ detail: failure.detail }) };
      }
      return response(next.data ?? control.review);
    }
    if (path.endsWith("/recommendations")) return response([]);
    if (path.endsWith("/events")) return response([]);
    if (path.endsWith("/ibkr-flex-connections")) return response([]);
    throw new Error(`Unexpected request: ${path}`);
  };

  return {
    get,
    requests,
    control,
    reviewRequests: () => requests.filter((request) => request.path.endsWith("/review")),
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

function walk(element) {
  return [element, ...element.children.flatMap(walk)];
}

function renderedText(element) {
  return walk(element).map((node) => node.textContent).filter(Boolean);
}

function gate() {
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  let signal;
  const requested = new Promise((resolve) => { signal = resolve; });
  return { promise, release, signal, requested };
}

async function startStaleThenNewReview(harness, firstOverrides) {
  const { get, control } = harness;
  const first = gate();
  const second = gate();
  control.reviewQueue.push(
    { gate: first.promise, signal: first.signal, ...firstOverrides },
    { gate: second.promise, signal: second.signal, data: reviewFor({ top: [holdingFor({ symbol: "NEW" })] }) },
  );
  const firstPending = get("#runReview").fire("click");
  await first.requested;
  get("#portfolioSelect").value = "portfolio-2";
  await get("#portfolioSelect").fire("change");
  const secondPending = get("#runReview").fire("click");
  await second.requested;
  return { first, second, firstPending, secondPending };
}

test("review sends the default request and renders ranked holdings, skipped holdings and notes", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-default");
    await connectAndSelect(harness);
    assert.equal(get("#reviewRequiredReturn").value, "7");
    assert.equal(get("#reviewTopN").value, "5");
    assert.equal(get("#reviewReplacementLimit").value, "5");
    assert.equal(get("#reviewCandidates").value, "");

    const before = requests.length;
    await get("#runReview").fire("click");

    assert.deepEqual(requests.slice(before).map((request) => request.path), ["/healthz", REVIEW_PATH]);
    const reviewRequest = harness.reviewRequests()[0];
    assert.equal(reviewRequest.options.method, "POST");
    assert.equal(reviewRequest.options.headers.Authorization, "Bearer synthetic-test-token");
    assert.equal(reviewRequest.options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(reviewRequest.options.body), {
      required_annual_return_percent: 7,
      top_n: 5,
      replacement_limit: 5,
      peer_scores: [],
    });

    assert.equal(get("#reviewStatus").textContent, READ_ONLY_STATUS);
    assert.equal(get("#reviewResult").hidden, false);
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");

    const result = get("#reviewResult");
    const text = renderedText(result);
    assert.deepEqual(text.slice(0, 4), [
      "Portfolio review",
      "Reviewed 4 open holdings against 7% per year.",
      "1 behind the hurdle path; 1 on or ahead of it; 1 held under 365 days; 1 could not be compared.",
      "Advice is shown for the holding behind the hurdle path.",
    ]);
    const cards = result.children.filter((child) => child.className === "review-holding");
    assert.equal(cards.length, 1);
    assert.equal(cards[0].children[0].tagName, "H3");
    assert.equal(cards[0].children[0].textContent, "1. AAA (USD)");
    const cardText = renderedText(cards[0]).join("\n");
    assert.match(cardText, /Behind the hurdle path by 10\.3 percentage points \(price-only\)\./);
    assert.match(cardText, /Return hurdle \(7% per year\): cannot be judged yet\./);
    assert.match(cardText, /Saved CPS: 35\.0 \/ 100\./);
    assert.match(cardText, /Dead money: verdict withheld \(60% input confidence\)\./);
    assert.match(cardText, /Replacement candidate BBB: score 82\.0, 47\.0 points above this holding's CPS\./);
    assert.doesNotMatch(cardText, /82%|Hidden rationale/);

    assert.ok(text.includes("Not compared"));
    assert.ok(text.includes(
      "1 holding not compared. Entry date is unavailable for at least one lot, so holding time cannot be measured. Affected: CCC.",
    ));
    assert.ok(text.includes("Notes"));
    assert.ok(text.includes("This review only reads saved data. PIP never places or transmits orders."));
    assert.deepEqual(
      [...new Set(requests.map((request) => request.path))].filter((path) => /order|trade|transmit/i.test(path)),
      [],
    );
  } finally {
    harness.cleanup();
  }
});

test("review sends custom values and candidate scores, and omits blank number fields", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-custom");
    await connectAndSelect(harness);
    get("#reviewRequiredReturn").value = "8.5";
    get("#reviewTopN").value = "3";
    get("#reviewReplacementLimit").value = "2";
    get("#reviewCandidates").value = "bbb:82, EEE : 90.5";
    await get("#runReview").fire("click");

    assert.deepEqual(JSON.parse(harness.reviewRequests()[0].options.body), {
      required_annual_return_percent: 8.5,
      top_n: 3,
      replacement_limit: 2,
      peer_scores: [{ symbol: "BBB", score: 82 }, { symbol: "EEE", score: 90.5 }],
    });

    for (const id of ["#reviewRequiredReturn", "#reviewTopN", "#reviewReplacementLimit", "#reviewCandidates"]) {
      get(id).value = "";
    }
    await get("#runReview").fire("click");
    assert.deepEqual(JSON.parse(harness.reviewRequests()[1].options.body), { peer_scores: [] });
    assert.equal(get("#reviewStatus").textContent, READ_ONLY_STATUS);

    get("#reviewRequiredReturn").value = "0";
    await get("#runReview").fire("click");
    assert.deepEqual(JSON.parse(harness.reviewRequests()[2].options.body), {
      required_annual_return_percent: 0,
      peer_scores: [],
    });
  } finally {
    harness.cleanup();
  }
});

test("review is refused when the API does not report portfolio review support", async () => {
  const healthResponses = [
    { status: "ok" },
    { status: "ok", portfolio_review: 0 },
    { status: "ok", hurdle_analysis: 1 },
  ];
  for (const [index, health] of healthResponses.entries()) {
    const harness = createHarness({ health });
    const { get } = harness;
    try {
      await import(`../pip-dashboard.js?review-ui-old-api-${index}`);
      await connectAndSelect(harness);
      await get("#runReview").fire("click");

      assert.equal(harness.reviewRequests().length, 0);
      assert.equal(get("#reviewStatus").textContent, "The PIP API must be updated before portfolio review is available.");
      assert.equal(get("#reviewResult").hidden, true);
      assert.equal(get("#runReview").disabled, false);
      assert.equal(get("#runReview").textContent, "Review portfolio");
    } finally {
      harness.cleanup();
    }
  }
});

test("review requires a selected portfolio before any request is sent", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-no-portfolio");
    await get("#connectApi").fire("click");
    const before = requests.length;
    await get("#runReview").fire("click");

    assert.equal(get("#reviewStatus").textContent, "Select a portfolio first.");
    assert.equal(requests.length, before);
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#runReview").disabled, false);
  } finally {
    harness.cleanup();
  }
});

test("invalid review inputs are rejected before any request, and an earlier result is cleared", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-invalid");
    await connectAndSelect(harness);
    await get("#runReview").fire("click");
    assert.equal(get("#reviewResult").hidden, false);

    const duplicate = "AAA:50, aaa:60";
    const tooMany = Array.from({ length: 501 }, (_, index) => `S${index}:50`).join(",");
    const cases = [
      ["#reviewRequiredReturn", "-1", "Required annual return must be at least 0."],
      ["#reviewRequiredReturn", "100.5", "Required annual return must be no more than 100."],
      ["#reviewRequiredReturn", "abc", "Required annual return must be a number."],
      ["#reviewTopN", "0", "Number of holdings must be at least 1."],
      ["#reviewTopN", "21", "Number of holdings must be no more than 20."],
      ["#reviewTopN", "2.5", "Number of holdings must be a whole number."],
      ["#reviewReplacementLimit", "0", "Replacements per holding must be at least 1."],
      ["#reviewReplacementLimit", "11", "Replacements per holding must be no more than 10."],
      ["#reviewReplacementLimit", "1.5", "Replacements per holding must be a whole number."],
      ["#reviewCandidates", "AAA", "Invalid replacement candidate: AAA. Use SYMBOL:score from 0 to 100."],
      ["#reviewCandidates", "AAA:", "Invalid replacement candidate: AAA:. Use SYMBOL:score from 0 to 100."],
      ["#reviewCandidates", "AAA:101", "Invalid replacement candidate: AAA:101. Use SYMBOL:score from 0 to 100."],
      ["#reviewCandidates", "AAA:-1", "Invalid replacement candidate: AAA:-1. Use SYMBOL:score from 0 to 100."],
      ["#reviewCandidates", "AAA:50:1", "Invalid replacement candidate: AAA:50:1. Use SYMBOL:score from 0 to 100."],
      ["#reviewCandidates", "<b>:50", "Invalid replacement candidate: <b>:50. Use SYMBOL:score from 0 to 100."],
      ["#reviewCandidates", duplicate, "Each replacement candidate symbol may appear only once."],
      ["#reviewCandidates", tooMany, "Enter at most 500 replacement candidates."],
    ];
    const defaults = {
      "#reviewRequiredReturn": "7",
      "#reviewTopN": "5",
      "#reviewReplacementLimit": "5",
      "#reviewCandidates": "",
    };
    for (const [id, value, message] of cases) {
      const before = requests.length;
      get(id).value = value;
      await get("#runReview").fire("click");
      assert.equal(get("#reviewStatus").textContent, message);
      assert.equal(requests.length, before);
      assert.equal(get("#reviewResult").hidden, true);
      assert.equal(get("#reviewResult").children.length, 0);
      assert.equal(get("#runReview").disabled, false);
      get(id).value = defaults[id];
    }
    assert.equal(harness.reviewRequests().length, 1);

    get("#reviewCandidates").value = "AAA:50, BBB:60";
    await get("#runReview").fire("click");
    assert.equal(harness.reviewRequests().length, 2);
  } finally {
    harness.cleanup();
  }
});

test("the shared candidate parser also rejects a blank score for the single-holding analysis", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-analysis-candidates");
    await connectAndSelect(harness);
    get("#analysisSymbol").value = "test";
    get("#pipPeerScores").value = "BBB:";
    const before = requests.length;
    await get("#analyzePosition").fire("click");

    assert.equal(get("#analysisStatus").textContent, "Invalid replacement candidate: BBB:. Use SYMBOL:score from 0 to 100.");
    assert.equal(requests.length, before);
  } finally {
    harness.cleanup();
  }
});

test("review is discarded when the selection changes during the compatibility check", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-stale-health");
    await connectAndSelect(harness);
    const health = gate();
    harness.control.healthGate = health.promise;
    const healthRequested = new Promise((resolve) => { harness.control.signalHealth = resolve; });
    const pending = get("#runReview").fire("click");
    await healthRequested;
    get("#portfolioSelect").value = "portfolio-2";
    health.release();
    await pending;
    harness.control.healthGate = null;

    assert.equal(harness.reviewRequests().length, 0);
    assert.match(get("#reviewStatus").textContent, /portfolio changed/i);
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#runReview").disabled, false);
  } finally {
    harness.cleanup();
  }
});

test("a portfolio switch during the compatibility check cancels the review silently", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-switch-health");
    await connectAndSelect(harness);
    const health = gate();
    harness.control.healthGate = health.promise;
    const healthRequested = new Promise((resolve) => { harness.control.signalHealth = resolve; });
    const pending = get("#runReview").fire("click");
    await healthRequested;
    get("#portfolioSelect").value = "portfolio-2";
    await get("#portfolioSelect").fire("change");
    health.release();
    await pending;
    harness.control.healthGate = null;

    assert.equal(harness.reviewRequests().length, 0);
    assert.equal(get("#reviewStatus").textContent, "");
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");
  } finally {
    harness.cleanup();
  }
});

test("a portfolio switch while the review is running discards the late response", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-switch-review");
    await connectAndSelect(harness);
    const review = gate();
    harness.control.reviewGate = review.promise;
    const reviewRequested = new Promise((resolve) => { harness.control.signalReview = resolve; });
    const pending = get("#runReview").fire("click");
    await reviewRequested;
    assert.equal(get("#runReview").disabled, true);
    get("#portfolioSelect").value = "portfolio-2";
    await get("#portfolioSelect").fire("change");
    review.release();
    await pending;
    harness.control.reviewGate = null;

    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#reviewResult").children.length, 0);
    assert.equal(get("#reviewStatus").textContent, "");
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");
  } finally {
    harness.cleanup();
  }
});

test("a selection change that arrives with the response is reported and the result is not shown", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-stale-response");
    await connectAndSelect(harness);
    const review = gate();
    harness.control.reviewGate = review.promise;
    const reviewRequested = new Promise((resolve) => { harness.control.signalReview = resolve; });
    const pending = get("#runReview").fire("click");
    await reviewRequested;
    get("#portfolioSelect").value = "portfolio-2";
    review.release();
    await pending;
    harness.control.reviewGate = null;

    assert.match(get("#reviewStatus").textContent, /portfolio changed/i);
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#reviewResult").children.length, 0);
    assert.equal(get("#runReview").disabled, false);
  } finally {
    harness.cleanup();
  }
});

test("a stale review finishing late does not re-enable the button or show over a newer review", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-race-success");
    await connectAndSelect(harness);
    const { first, second, firstPending, secondPending } = await startStaleThenNewReview(harness, {
      data: reviewFor({ top: [holdingFor({ symbol: "OLD" })] }),
    });
    assert.equal(get("#runReview").disabled, true);

    first.release();
    await firstPending;
    assert.equal(get("#runReview").disabled, true, "the newer review is still running");
    assert.equal(get("#runReview").textContent, "Reviewing…");
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#reviewStatus").textContent, "Reviewing saved positions…");

    second.release();
    await secondPending;
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");
    assert.equal(get("#reviewStatus").textContent, READ_ONLY_STATUS);
    const titles = renderedText(get("#reviewResult")).filter((line) => /^\d+\. /.test(line));
    assert.deepEqual(titles, ["1. NEW (USD)"]);
  } finally {
    harness.cleanup();
  }
});

test("a stale review failing late does not overwrite the status of a newer review", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-race-failure");
    await connectAndSelect(harness);
    const { first, second, firstPending, secondPending } = await startStaleThenNewReview(harness, {
      failure: { status: 502, detail: "The PIP data service request failed." },
    });

    first.release();
    await firstPending;
    assert.equal(get("#reviewStatus").textContent, "Reviewing saved positions…");
    assert.equal(get("#runReview").disabled, true);
    assert.equal(get("#reviewResult").hidden, true);

    second.release();
    await secondPending;
    assert.equal(get("#reviewStatus").textContent, READ_ONLY_STATUS);
    assert.equal(get("#reviewResult").hidden, false);
    assert.equal(get("#runReview").disabled, false);
  } finally {
    harness.cleanup();
  }
});

test("switching away and back during the compatibility check still cancels the stale review", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-away-and-back-health");
    await connectAndSelect(harness);
    const health = gate();
    harness.control.healthGate = health.promise;
    const healthRequested = new Promise((resolve) => { harness.control.signalHealth = resolve; });
    const pending = get("#runReview").fire("click");
    await healthRequested;
    get("#portfolioSelect").value = "portfolio-2";
    await get("#portfolioSelect").fire("change");
    get("#portfolioSelect").value = "portfolio-1";
    await get("#portfolioSelect").fire("change");
    health.release();
    await pending;
    harness.control.healthGate = null;

    assert.equal(harness.reviewRequests().length, 0, "a stale run must not send the review request");
    assert.equal(get("#reviewStatus").textContent, "");
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");
  } finally {
    harness.cleanup();
  }
});

test("switching away and back while the review is running still discards the late response", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-away-and-back-review");
    await connectAndSelect(harness);
    const review = gate();
    harness.control.reviewGate = review.promise;
    const reviewRequested = new Promise((resolve) => { harness.control.signalReview = resolve; });
    const pending = get("#runReview").fire("click");
    await reviewRequested;
    get("#portfolioSelect").value = "portfolio-2";
    await get("#portfolioSelect").fire("change");
    get("#portfolioSelect").value = "portfolio-1";
    await get("#portfolioSelect").fire("change");
    review.release();
    await pending;
    harness.control.reviewGate = null;

    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#reviewResult").children.length, 0);
    assert.equal(get("#reviewStatus").textContent, "");
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");
  } finally {
    harness.cleanup();
  }
});

test("the latest run wins when an earlier run on the same portfolio is still in flight", async () => {
  const harness = createHarness();
  const { get, control } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-latest-wins");
    await connectAndSelect(harness);
    const first = gate();
    const second = gate();
    control.reviewQueue.push(
      { gate: first.promise, signal: first.signal, data: reviewFor({ top: [holdingFor({ symbol: "OLD" })] }) },
      { gate: second.promise, signal: second.signal, data: reviewFor({ top: [holdingFor({ symbol: "NEW" })] }) },
    );
    // The button is disabled while a run is in flight, so a second run is not reachable by a user.
    // This pins the invariant for a programmatic call: only the latest run may touch the result.
    const firstPending = get("#runReview").fire("click");
    await first.requested;
    const secondPending = get("#runReview").fire("click");
    await second.requested;

    first.release();
    await firstPending;
    assert.equal(get("#reviewResult").hidden, true, "the superseded run must not render");
    assert.equal(get("#reviewStatus").textContent, "Reviewing saved positions…");
    assert.equal(get("#runReview").disabled, true);

    second.release();
    await secondPending;
    assert.equal(get("#reviewStatus").textContent, READ_ONLY_STATUS);
    assert.equal(get("#runReview").disabled, false);
    const titles = renderedText(get("#reviewResult")).filter((line) => /^\d+\. /.test(line));
    assert.deepEqual(titles, ["1. NEW (USD)"]);
  } finally {
    harness.cleanup();
  }
});

test("an API failure is shown as an error, with no result and no fallback", async () => {
  const harness = createHarness();
  const { get, requests } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-failure");
    await connectAndSelect(harness);
    await get("#runReview").fire("click");
    assert.equal(get("#reviewResult").hidden, false);

    harness.control.reviewFailure = { status: 502, detail: "The PIP data service request failed." };
    const before = requests.length;
    await get("#runReview").fire("click");

    assert.equal(get("#reviewStatus").textContent, "The PIP data service request failed.");
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#reviewResult").children.length, 0);
    assert.deepEqual(requests.slice(before).map((request) => request.path), ["/healthz", REVIEW_PATH]);
    assert.equal(get("#runReview").disabled, false);
    assert.equal(get("#runReview").textContent, "Review portfolio");

    harness.control.reviewFailure = { status: 500, detail: null };
    await get("#runReview").fire("click");
    assert.equal(get("#reviewStatus").textContent, "PIP API request failed (500).");
    assert.equal(get("#reviewResult").hidden, true);
  } finally {
    harness.cleanup();
  }
});

test("a malformed review response is reported instead of shown as a success", async () => {
  for (const [index, review] of [null, {}, { review: null }, { review: "done" }].entries()) {
    const harness = createHarness({ review });
    const { get } = harness;
    try {
      await import(`../pip-dashboard.js?review-ui-malformed-${index}`);
      await connectAndSelect(harness);
      await get("#runReview").fire("click");

      assert.equal(get("#reviewStatus").textContent, "The PIP API returned an unexpected review response.");
      assert.equal(get("#reviewResult").hidden, true);
      assert.equal(get("#runReview").disabled, false);
    } finally {
      harness.cleanup();
    }
  }
});

test("a review with nothing ranked says so, and a truncated review warns that it may be incomplete", async () => {
  const empty = createHarness({
    review: reviewFor({
      summary: { holdings: 2, not_analysable: 0, held_under_minimum: 1, meeting_hurdle: 1, behind_hurdle: 0 },
      top: [],
      skipped: [],
    }),
  });
  try {
    await import("../pip-dashboard.js?review-ui-empty");
    await connectAndSelect(empty);
    await empty.get("#runReview").fire("click");
    const text = renderedText(empty.get("#reviewResult"));
    assert.ok(text.includes("No holding is ranked as behind the hurdle path."));
    assert.equal(empty.get("#reviewResult").children.filter((child) => child.className === "review-holding").length, 0);
    assert.ok(!text.includes("Not compared"));
    assert.equal(empty.get("#reviewStatus").textContent, READ_ONLY_STATUS);
  } finally {
    empty.cleanup();
  }

  const truncated = createHarness({
    review: reviewFor({
      summary: { behind_hurdle: 7, truncated: true },
      top: [holdingFor(), holdingFor({ rank: 2, symbol: "DDD" })],
    }),
  });
  try {
    await import("../pip-dashboard.js?review-ui-truncated");
    await connectAndSelect(truncated);
    await truncated.get("#runReview").fire("click");
    const text = renderedText(truncated.get("#reviewResult"));
    assert.ok(text.includes("Advice is shown for the 2 holdings furthest behind the hurdle path."));
    assert.ok(text.some((line) => /may be incomplete/.test(line)));
    const titles = truncated.get("#reviewResult").children
      .filter((child) => child.className === "review-holding")
      .map((card) => card.children[0].textContent);
    assert.deepEqual(titles, ["1. AAA (USD)", "2. DDD (USD)"]);
  } finally {
    truncated.cleanup();
  }
});

test("review content from the API is rendered as text only", async () => {
  const markup = "<img src=x onerror=alert(1)>";
  const review = reviewFor({
    top: [holdingFor({
      symbol: markup,
      hurdle: hurdleFor({ reasons: [markup] }),
      dead_money: { is_dead_money: true, confidence: 0.9, reasons: [markup] },
      replacements: {
        compared: true,
        reasons: [],
        candidates: [{ symbol: markup, score: 80, expected_benefit: 45, confidence: 0.8 }],
      },
    })],
    skipped: [{ reason: "no_entry_date", message: markup, count: 3, symbols: [markup] }],
    notes: [markup],
  });
  const harness = createHarness({ review });
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-text-only");
    await connectAndSelect(harness);
    await get("#runReview").fire("click");

    const nodes = walk(get("#reviewResult"));
    assert.ok(nodes.length > 10);
    assert.deepEqual([...new Set(nodes.map((node) => node.tagName))].sort(), ["DIV", "H3", "LI", "P", "UL"]);
    for (const node of nodes) {
      for (const property of ["innerHTML", "outerHTML", "insertAdjacentHTML"]) {
        assert.equal(Object.hasOwn(node, property), false, `${property} must never be assigned`);
      }
    }
    const text = renderedText(get("#reviewResult")).join("\n");
    assert.ok(text.includes(`1. ${markup} (USD)`));
    assert.ok(text.includes(`Dead-money evidence: ${markup}`));
    assert.ok(text.includes(`Affected: ${markup} and 2 more.`));
    assert.ok(text.includes(`Replacement candidate ${markup}: score 80.0`));
  } finally {
    harness.cleanup();
  }
});

test("switching portfolios restores the review defaults and clears the review", async () => {
  const harness = createHarness();
  const { get } = harness;
  try {
    await import("../pip-dashboard.js?review-ui-reset");
    await connectAndSelect(harness);
    get("#reviewRequiredReturn").value = "9";
    get("#reviewTopN").value = "3";
    get("#reviewReplacementLimit").value = "2";
    get("#reviewCandidates").value = "BBB:80";
    await get("#runReview").fire("click");
    assert.equal(get("#reviewResult").hidden, false);
    assert.equal(get("#reviewStatus").textContent, READ_ONLY_STATUS);

    get("#portfolioSelect").value = "portfolio-2";
    await get("#portfolioSelect").fire("change");

    assert.equal(get("#reviewRequiredReturn").value, "7");
    assert.equal(get("#reviewTopN").value, "5");
    assert.equal(get("#reviewReplacementLimit").value, "5");
    assert.equal(get("#reviewCandidates").value, "");
    assert.equal(get("#reviewResult").hidden, true);
    assert.equal(get("#reviewResult").children.length, 0);
    assert.equal(get("#reviewStatus").textContent, "");
    assert.equal(get("#runReview").disabled, false);

    get("#portfolioSelect").value = "portfolio-2";
    get("#analysisSymbol").value = "abc";
    get("#reviewCandidates").value = "BBB:80";
    await get("#runReview").fire("click");
    assert.equal(get("#reviewResult").hidden, false);
    get("#analysisSymbol").value = "abcd";
    await get("#analysisSymbol").fire("input");
    assert.equal(get("#reviewResult").hidden, false, "editing the single-holding symbol must not clear the portfolio review");
    assert.equal(get("#reviewCandidates").value, "BBB:80");
  } finally {
    harness.cleanup();
  }
});

test("every selector the workbench script uses exists on the page, and the review controls mirror the API bounds", () => {
  const html = readFileSync(new URL("../portfolio-intelligence.html", import.meta.url), "utf8");
  const script = readFileSync(new URL("../pip-dashboard.js", import.meta.url), "utf8");
  const ids = new Set([...script.matchAll(/(?:querySelector|get)\(\s*"#([A-Za-z0-9_-]+)"/g)].map((match) => match[1]));
  for (const id of ["reviewRequiredReturn", "reviewTopN", "reviewReplacementLimit", "reviewCandidates", "runReview", "reviewStatus", "reviewResult"]) {
    assert.ok(ids.has(id), `${id} should be used by the script`);
  }
  const missing = [...ids].filter((id) => !new RegExp(`\\bid="${id}"`).test(html));
  assert.deepEqual(missing, []);

  const tag = (id) => html.match(new RegExp(`<[^>]*\\bid="${id}"[^>]*>`))[0];
  for (const [id, min, max] of [
    ["reviewRequiredReturn", "0", "100"],
    ["reviewTopN", "1", "20"],
    ["reviewReplacementLimit", "1", "10"],
  ]) {
    assert.match(tag(id), new RegExp(`\\bmin="${min}"`), `${id} min`);
    assert.match(tag(id), new RegExp(`\\bmax="${max}"`), `${id} max`);
  }
  assert.match(tag("runReview"), /\btype="button"/);
  assert.match(tag("reviewResult"), /\bhidden\b/);
  assert.match(tag("reviewStatus"), /role="status"/);
});
