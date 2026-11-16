import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  CONFIDENCE_NOTE,
  HOLDING_COLUMNS,
  PIP_COMPONENT_FIELDS,
  PIP_MODULES,
  PIP_MODULE_FIELDS,
  PIP_RESEARCH_INPUTS,
  REPLACEMENT_LIMIT,
  SELL_SCORE_DIRECTION,
  buildModuleRequest,
  describeHolding,
  describeHoldingsFlags,
  describeHoldingsSummary,
  describeHoldingsTotals,
  describeModuleResult,
  describePortfolio,
  describeResearchLoad,
  describeResearchProvenance,
  fieldInputId,
  fieldKey,
  filterHoldings,
  formatAmount,
  formatAsOf,
  formatPercent,
  formatQuantity,
  holdingCells,
  holdingInputHints,
  labelOf,
  parseHoldingsResponse,
  parsePortfolioList,
  parseResearchResponse,
  unchangedResearchInputs,
} from "../pip-modules-core.js";
import { FULL_RESEARCH_LINES as FULL_LINES, emptyResearchFixture, researchFixture } from "./pip-research-fixture.mjs";

const UNEXPECTED = "The API returned an unexpected response, so no result is shown.";
const READ_ONLY = "Read-only result: nothing was saved and no orders were placed.";
const REPLACEMENT_RULE = "Candidates are listed only when they score above this holding's capital productivity score and are not already held in this portfolio.";
const LEGACY_DIRECTION = "This result does not say which way the sell score runs, so it may use the earlier direction, where healthier holdings scored higher. Treat it as unverified.";
const SELL_WEIGHTS = { tsr: 20, relative_performance: 20, revisions: 20, dividend_quality: 15, technical_health: 15, earnings_growth: 10, opportunity_cost: 15 };
const SELL_DIRECTION_FIELDS = {
  sell_score_direction: SELL_SCORE_DIRECTION,
  inverted_components: ["tsr", "relative_performance", "revisions", "dividend_quality", "technical_health", "earnings_growth"],
};
const FLIPPED_NOTE = "Each value shows how strongly that input argues for selling.";

const response = (module, result, extra = {}) => ({ module, symbol: "AAA", currency: "USD", saved: false, result, ...extra });
const describe = (module, result, extra) => describeModuleResult(module, response(module, result, extra));
const readPath = (body, path) => path.reduce((node, part) => node?.[part], body);

test("the module list follows the API order and every module has a label and a hint", () => {
  assert.deepEqual(PIP_MODULES.map((module) => module.id), [
    "lifecycle", "hurdle", "dead_money", "dividends", "growth", "forward_looking",
    "opportunity_cost", "cps", "sell_score", "replacements", "sell_advisor",
  ]);
  for (const module of PIP_MODULES) {
    assert.ok(module.label && module.needs, module.id);
  }
  assert.equal(new Set(PIP_MODULES.map((module) => module.label)).size, PIP_MODULES.length);
  assert.match(CONFIDENCE_NOTE, /not how strong the signal is/);
});

test("the field list is consistent", () => {
  const keys = PIP_MODULE_FIELDS.map(fieldKey);
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(new Set(PIP_MODULE_FIELDS.map(fieldInputId)).size, keys.length);
  assert.equal(new Set(PIP_MODULE_FIELDS.map((field) => field.label)).size, keys.length);
  for (const field of PIP_MODULE_FIELDS) {
    assert.ok(["number", "date", "candidates"].includes(field.type), field.label);
    assert.ok(["holding", "shared"].includes(field.scope), field.label);
    assert.ok(field.group && field.help && field.label, fieldKey(field));
    if (field.min !== undefined && field.max !== undefined) assert.ok(field.min < field.max, field.label);
    if (field.positive) assert.equal(field.min, undefined, field.label);
  }
  assert.deepEqual(
    PIP_MODULE_FIELDS.filter((field) => field.scope === "shared").map(fieldKey),
    ["hurdle.required_annual_return_percent", "hurdle.replacement_assumed_return_percent", "peer_scores"],
  );
  assert.deepEqual(PIP_MODULE_FIELDS.filter((field) => field.value !== undefined).map(fieldKey), ["hurdle.required_annual_return_percent"]);
  assert.equal(fieldInputId(PIP_MODULE_FIELDS[0]), "moduleInput-position-market_price");
  assert.equal(fieldInputId(PIP_MODULE_FIELDS.at(-1)), "moduleInput-peer_scores");
  for (const fields of PIP_COMPONENT_FIELDS.values()) {
    for (const key of fields) assert.ok(keys.includes(key), key);
  }
  assert.equal(labelOf("position.entry_date"), "Entry date");
  assert.equal(labelOf("nothing.here"), "nothing.here");
});

test("a request holds only the symbol when nothing is entered", () => {
  assert.deepEqual(buildModuleRequest(" aaa "), { symbol: "AAA" });
  assert.deepEqual(buildModuleRequest("AAA", null), { symbol: "AAA" });
  assert.deepEqual(buildModuleRequest("BRK.B", { "position.market_price": "", "hurdle.required_annual_return_percent": "   " }), { symbol: "BRK.B" });
});

test("a request needs a usable symbol", () => {
  assert.throws(() => buildModuleRequest(""), { message: "Select a holding first." });
  assert.throws(() => buildModuleRequest(null), { message: "Select a holding first." });
  for (const symbol of ["A B", "AAA/BBB", "-AAA", "A".repeat(31)]) {
    assert.throws(() => buildModuleRequest(symbol), /symbol cannot be analyzed/, symbol);
  }
});

test("a request nests every entered value under its API path", () => {
  const values = {
    "position.market_price": "12.5",
    "position.cost_basis": "1000",
    "position.entry_date": "2024-02-29",
    "position.dividends_received": "0",
    "hurdle.required_annual_return_percent": "7",
    "hurdle.holding_assumed_return_percent": "-5.5",
    "hurdle.replacement_assumed_return_percent": "12",
    "scores.tsr": "70",
    "scores.relative_performance": "60",
    "scores.technical_health": "50",
    "scores.opportunity_cost": "40",
    "growth.earnings_growth_percent": "-3",
    "growth.revenue_growth_percent": "4.5",
    "forward.target_upside_percent": "10",
    "forward.analyst_revisions_score": "55",
    "dividends.payout_ratio": "0.6",
    "dividends.dividend_growth_rate": "0.05",
    "dividends.consistency_score": "0.9",
    peer_scores: "bbb:82, CCC:90.5\nDDD:70",
  };
  assert.deepEqual(buildModuleRequest("aaa", values), {
    symbol: "AAA",
    position: { market_price: 12.5, cost_basis: 1000, entry_date: "2024-02-29", dividends_received: 0 },
    hurdle: { required_annual_return_percent: 7, holding_assumed_return_percent: -5.5, replacement_assumed_return_percent: 12 },
    scores: { tsr: 70, relative_performance: 60, technical_health: 50, opportunity_cost: 40 },
    growth: { earnings_growth_percent: -3, revenue_growth_percent: 4.5 },
    forward: { target_upside_percent: 10, analyst_revisions_score: 55 },
    dividends: { payout_ratio: 0.6, dividend_growth_rate: 0.05, consistency_score: 0.9 },
    peer_scores: [{ symbol: "BBB", score: 82 }, { symbol: "CCC", score: 90.5 }, { symbol: "DDD", score: 70 }],
  });
});

test("a request leaves out groups that have no entered values", () => {
  const body = buildModuleRequest("AAA", { "scores.tsr": "70", "growth.earnings_growth_percent": "" });
  assert.deepEqual(body, { symbol: "AAA", scores: { tsr: 70 } });
  assert.equal("growth" in body, false);
});

test("a request ignores keys that are not input fields", () => {
  const body = buildModuleRequest("AAA", { __proto__: "x", "constructor.prototype": "x", portfolio_id: "p", "position.unknown": "1" });
  assert.deepEqual(body, { symbol: "AAA" });
  assert.equal({}.polluted, undefined);
});

test("every number field accepts its bounds and rejects values outside them", () => {
  for (const field of PIP_MODULE_FIELDS.filter((item) => item.type === "number")) {
    const key = fieldKey(field);
    const read = (text) => readPath(buildModuleRequest("AAA", { [key]: text }), field.path);
    assert.equal(read(""), undefined, key);
    assert.throws(() => read("abc"), { message: `${field.label} must be a number.` }, key);
    assert.throws(() => read("Infinity"), { message: `${field.label} must be a number.` }, key);
    assert.equal(read(" 1.5 ".replace("1.5", field.positive ? "0.01" : String(field.min ?? 1.5))), field.positive ? 0.01 : field.min ?? 1.5, key);
    if (field.min !== undefined) {
      assert.equal(read(String(field.min)), field.min, key);
      assert.throws(() => read(String(field.min - 1)), { message: `${field.label} must be at least ${field.min}.` }, key);
    }
    if (field.max !== undefined) {
      assert.equal(read(String(field.max)), field.max, key);
      assert.throws(() => read(String(field.max + 1)), { message: `${field.label} must be no more than ${field.max}.` }, key);
    }
    if (field.positive) {
      for (const text of ["0", "-1", "-0"]) {
        assert.throws(() => read(text), { message: `${field.label} must be greater than 0.` }, `${key} ${text}`);
      }
    }
    if (field.min === undefined && field.max === undefined && !field.positive) {
      assert.equal(read("-500"), -500, key);
    }
  }
});

test("dates must be real calendar dates written as YYYY-MM-DD", () => {
  const entry = (text) => buildModuleRequest("AAA", { "position.entry_date": text }).position?.entry_date;
  assert.equal(entry("2024-02-29"), "2024-02-29");
  assert.equal(entry(" 2024-12-31 "), "2024-12-31");
  assert.equal(entry(""), undefined);
  for (const text of ["2023-02-29", "2024-13-01", "2024-00-10", "2024-1-1", "24-01-01", "01/02/2024", "2024-01-01T00:00:00Z", "tomorrow"]) {
    assert.throws(() => entry(text), { message: "Entry date must be a date in YYYY-MM-DD format." }, text);
  }
});

test("replacement candidates are parsed, upper-cased and checked", () => {
  const request = (text) => buildModuleRequest("AAA", { peer_scores: text });
  assert.deepEqual(request("bbb:82").peer_scores, [{ symbol: "BBB", score: 82 }]);
  assert.equal(request("  ").peer_scores, undefined);
  assert.throws(() => request("BBB"), { message: "Invalid replacement candidate: BBB. Use SYMBOL:score from 0 to 100." });
  assert.throws(() => request("BBB:101"), /Invalid replacement candidate: BBB:101/);
  assert.throws(() => request("BBB:-1"), /Invalid replacement candidate/);
  assert.throws(() => request("BBB:1:2"), /Invalid replacement candidate/);
  assert.throws(() => request("BBB:80, bbb:90"), { message: "Each replacement candidate symbol may appear only once." });
  const many = Array.from({ length: 501 }, (_, index) => `S${index}:50`).join(",");
  assert.throws(() => request(many), { message: "Enter at most 500 replacement candidates." });
  assert.equal(request(many.split(",").slice(0, 500).join(",")).peer_scores.length, 500);
});

test("an unexpected or mismatched response is never described", () => {
  const bad = [
    null, undefined, "text", 5, [], {}, { module: "cps" }, response("cps", null), response("cps", []), response("cps", "x"),
    response("growth", { score: 50 }),
  ];
  for (const value of bad) {
    const description = describeModuleResult("cps", value);
    assert.equal(description.headline, UNEXPECTED);
    assert.equal(description.unexpected, true);
    assert.deepEqual([description.rows, description.details, description.hints, description.caveats], [[], [], [], []]);
    assert.equal(description.footer, "");
    assert.equal(description.title, "Capital productivity score");
  }
  const unknown = describeModuleResult("nothing", response("nothing", { score: 1 }));
  assert.equal(unknown.headline, UNEXPECTED);
  assert.equal(unknown.title, "Module result");
});

test("the footer says whether the API confirmed that nothing was saved", () => {
  assert.equal(describe("growth", { score: 50, confidence: 1 }).footer, READ_ONLY);
  assert.equal(describe("growth", { score: 50, confidence: 1 }).unexpected, false);
  assert.equal(describe("growth", { score: 50, confidence: 1 }, { saved: true }).footer, "The API did not confirm that nothing was saved.");
  assert.equal(describe("growth", { score: 50, confidence: 1 }, { saved: undefined }).footer, "The API did not confirm that nothing was saved.");
});

test("lifecycle shows the holding period and returns, and never the echoed inputs", () => {
  const description = describe("lifecycle", {
    days_held: 400, price_return_percent: 12.34, total_return_percent: -0.04, metadata: { account: "SECRET-ACCOUNT" }, tsl: 50,
  });
  assert.equal(description.headline, "Held 400 days; price return +12.3%; total return 0.0%.");
  assert.deepEqual(description.rows, [["Days held", "400"], ["Price return", "+12.3%"], ["Total return", "0.0%"]]);
  assert.deepEqual(description.hints, []);
  assert.equal(JSON.stringify(description).includes("SECRET-ACCOUNT"), false);
  assert.equal(describe("lifecycle", { days_held: 1, price_return_percent: -3.21 }).headline, "Held 1 day; price return -3.2%.");
});

test("lifecycle asks for the missing values by their field names", () => {
  const description = describe("lifecycle", {});
  assert.equal(description.headline, "Not enough data to describe this position's lifecycle.");
  assert.deepEqual(description.rows.map((row) => row[1]), ["not available", "not available", "not available"]);
  assert.equal(description.hints.length, 3);
  assert.match(description.hints[0], /Entry date/);
  assert.match(description.hints[1], /Current share price and the Cost basis/);
  assert.match(description.hints[2], /Dividends received since entry \(enter 0 if none\)/);
  assert.equal(describe("lifecycle", { total_return_percent: 5 }).hints.length, 2);
});

test("the return hurdle reuses the workbench wording", () => {
  const description = describe("hurdle", {
    status: "below", required_annual_return_percent: 7, return_percent: 2, hurdle_return_percent: 5, days_held: 100, lot_count: 1, return_basis: "price",
  });
  assert.equal(description.headline, "Return hurdle (7% per year): below the hurdle path.");
  assert.deepEqual(description.details, ["Price-only return is 2.0% against 5.0% needed to match the hurdle path after 100 days."]);
  assert.deepEqual(description.hints, []);
});

test("an unavailable return hurdle says which values would help", () => {
  const description = describe("hurdle", {
    status: "unavailable", required_annual_return_percent: 7, return_percent: null, reasons: ["Enter dividends received (0 if none)."],
  });
  assert.equal(description.headline, "Return hurdle (7% per year): cannot be judged yet.");
  assert.deepEqual(description.details, ["Notes: Enter dividends received (0 if none)."]);
  assert.equal(description.hints.length, 1);
  assert.match(description.hints[0], /Current share price, the Cost basis and the Entry date/);
  assert.deepEqual(describe("hurdle", { status: "unavailable", return_percent: 3 }).hints, []);
});

test("dead money reports a flag, a clear result, or a withheld verdict", () => {
  const flagged = describe("dead_money", { is_dead_money: true, confidence: 0.6667, reasons: ["below the hurdle."] });
  assert.equal(flagged.headline, "Flagged for review as dead money.");
  assert.deepEqual(flagged.rows, [["Input confidence", "67%"]]);
  assert.deepEqual(flagged.details, ["Below the hurdle."]);
  assert.deepEqual(flagged.hints, []);
  assert.equal(describe("dead_money", { is_dead_money: false, confidence: 1 }).headline, "Not flagged as dead money.");
  for (const result of [{ is_dead_money: null, confidence: 0 }, { confidence: 0 }]) {
    const withheld = describe("dead_money", result);
    assert.equal(withheld.headline, "Verdict withheld: there is not enough evidence.");
    assert.equal(withheld.hints.length, 1);
    assert.match(withheld.hints[0], /Current share price, Cost basis, Entry date or Dividends received since entry/);
  }
  assert.equal(describe("dead_money", { is_dead_money: "yes" }).headline, UNEXPECTED);
});

test("confidence is clamped to 0-100% and unavailable when missing", () => {
  assert.deepEqual(describe("dead_money", { is_dead_money: false, confidence: 7 }).rows, [["Input confidence", "100%"]]);
  assert.deepEqual(describe("dead_money", { is_dead_money: false, confidence: -1 }).rows, [["Input confidence", "0%"]]);
  assert.deepEqual(describe("dead_money", { is_dead_money: false }).rows, [["Input confidence", "not available"]]);
});

test("dividends show trailing income with its currency", () => {
  const description = describe("dividends", {
    trailing_twelve_month_income: 1234.5, current_yield_pct: 3.456, dividend_quality_score: 71.23, growth_score: 50, confidence: 1, reasons: [],
  });
  assert.equal(description.headline, "Trailing 12-month dividend income: 1,234.50 USD.");
  assert.deepEqual(description.rows, [
    ["Trailing 12-month income", "1,234.50 USD"],
    ["Current yield", "3.46%"],
    ["Dividend quality score", "71.2 out of 100"],
    ["Dividend growth score", "50.0 out of 100"],
    ["Input confidence", "100%"],
  ]);
  assert.deepEqual(description.hints, []);
  assert.equal(describe("dividends", { trailing_twelve_month_income: 5 }, { currency: null }).headline, "Trailing 12-month dividend income: 5.00.");
});

test("dividends explain what is missing without repeating the API's missing-data notes", () => {
  const description = describe("dividends", {
    trailing_twelve_month_income: null,
    current_yield_pct: null,
    dividend_quality_score: null,
    growth_score: null,
    confidence: 0,
    reasons: ["dividend yield data is missing or invalid.", "Dividend growth data is invalid."],
  });
  assert.equal(description.headline, "No dividend payments from the last 12 months are saved for this holding.");
  assert.equal(description.rows[0][1], "none saved");
  assert.deepEqual(description.rows.slice(1, 4).map((row) => row[1]), ["not available", "not available", "not available"]);
  assert.deepEqual(description.details, ["Dividend growth data is invalid."]);
  assert.equal(description.hints.length, 3);
  assert.match(description.hints[1], /Dividend payout ratio, Dividend growth rate or Dividend consistency \(0–1\)/);
  const noYield = describe("dividends", { trailing_twelve_month_income: 10, current_yield_pct: null, dividend_quality_score: 50, growth_score: 50 });
  assert.deepEqual(noYield.hints, ["Add the Current share price to calculate the yield."]);
});

test("growth and forward-looking results are scores out of 100", () => {
  const growth = describe("growth", { score: 72.46, confidence: 0.5, reasons: ["Revenue or earnings growth data is missing; confidence is reduced."] });
  assert.equal(growth.headline, "Growth score: 72.5 out of 100.");
  assert.deepEqual(growth.rows, [["Growth score", "72.5 out of 100"], ["Input confidence", "50%"]]);
  assert.deepEqual(growth.details, ["Revenue or earnings growth data is missing; confidence is reduced."]);
  assert.deepEqual(growth.hints, []);
  assert.deepEqual(growth.caveats, []);

  const forward = describe("forward_looking", { score: 61, confidence: 1, reasons: [] });
  assert.equal(forward.headline, "Forward-looking indicator: 61.0 out of 100.");
  assert.deepEqual(forward.caveats, ["An indicator built from the inputs you supplied, not a forecast."]);
});

test("growth and forward-looking results without a score name the fields to add", () => {
  const growth = describe("growth", { score: null, confidence: 0, reasons: [] });
  assert.equal(growth.headline, "Growth score not available: no growth data was supplied.");
  assert.deepEqual(growth.hints, ["Add Earnings growth (%) or Revenue growth (%) to calculate a growth score."]);
  const forward = describe("forward_looking", { score: null, confidence: 0, reasons: [] });
  assert.equal(forward.headline, "Forward-looking indicator not available: no outlook data was supplied.");
  assert.deepEqual(forward.hints, ["Add Target upside (%) or Forward revisions score (0–100) to calculate an indicator."]);
  assert.equal(forward.caveats.length, 1);
});

test("opportunity cost without a capital productivity score lists what would give it one", () => {
  const description = describe("opportunity_cost", { available: false, items: [], reasons: ["Current holding CPS is unavailable."] });
  assert.equal(description.headline, "Opportunity cost is not available for this holding.");
  assert.deepEqual(description.details, ["Current holding CPS is unavailable."]);
  assert.match(description.hints[0], /Total shareholder return score \(0–100\), Relative performance score \(0–100\).*or Forward revisions score \(0–100\)/);
  assert.deepEqual(description.rows ?? [], []);
  assert.deepEqual(description.caveats, []);
});

test("opportunity cost without candidates asks for them", () => {
  const description = describe("opportunity_cost", { available: true, items: [], reasons: ["No replacement candidate scores were supplied."] });
  assert.equal(description.headline, "No replacement candidates were supplied, so there is nothing to compare.");
  assert.deepEqual(description.hints, ["Add Replacement candidates (for example AAA:82, BBB:90) to compare with this holding."]);
});

test("opportunity cost names the best alternative and calls the benefit a score estimate", () => {
  const description = describe("opportunity_cost", {
    available: true,
    reasons: [],
    items: [
      { alternative_symbol: "BBB", current_value: 1000, expected_benefit: 6.2, rationale: "BBB is stronger than AAA by 12.40 score points.", confidence: 0.9 },
      { alternative_symbol: "CCC", current_value: 1000, expected_benefit: 0, rationale: "CCC is stronger than AAA by -3.00 score points.", confidence: 0.9 },
    ],
  });
  assert.equal(description.headline, "Best alternative: BBB, an estimated benefit of 6.2 points.");
  assert.deepEqual(description.rows, [
    ["BBB", "12.4 score points above this holding; estimated benefit 6.2 points."],
    ["CCC", "3.0 score points below this holding; estimated benefit 0.0 points."],
  ]);
  assert.deepEqual(description.hints, []);
  assert.equal(description.caveats.length, 1);
  assert.match(description.caveats[0], /not a return forecast or an amount of money/);
});

test("opportunity cost says when no candidate is stronger", () => {
  const description = describe("opportunity_cost", {
    available: true, reasons: [],
    items: [{ alternative_symbol: "BBB", current_value: 500, expected_benefit: 0, rationale: "BBB is stronger than AAA by -8.00 score points." }],
  });
  assert.equal(description.headline, "None of the supplied candidates is stronger than this holding.");
  assert.deepEqual(description.rows, [["BBB", "8.0 score points below this holding; estimated benefit 0.0 points."]]);
});

test("opportunity cost does not size a benefit for a holding with no market value", () => {
  const description = describe("opportunity_cost", {
    available: true, reasons: [],
    items: [{ alternative_symbol: "BBB", current_value: 0, expected_benefit: 0, rationale: "BBB is stronger than AAA by 12.00 score points." }],
  });
  assert.equal(description.headline, "The benefit cannot be sized because this holding has no market value.");
  assert.deepEqual(description.rows, [["BBB", "12.0 score points above this holding."]]);
  assert.deepEqual(description.hints, ["Add the Current share price so this holding has a market value."]);
  assert.equal(description.caveats.length, 1);
});

test("opportunity cost shows the API's own wording when it cannot read a score gap, and caps long lists", () => {
  const odd = describe("opportunity_cost", {
    available: true, reasons: [],
    items: [
      { alternative_symbol: "BBB", current_value: 100, expected_benefit: 1, rationale: "Custom text." },
      { current_value: 100, expected_benefit: 0 },
      "not an item",
    ],
  });
  assert.deepEqual(odd.rows, [["BBB", "Custom text; estimated benefit 1.0 points."], ["Candidate", "Estimated benefit 0.0 points."]]);

  const items = Array.from({ length: 12 }, (_, index) => ({
    alternative_symbol: `S${index}`, current_value: 100, expected_benefit: 12 - index, rationale: `S${index} is stronger than AAA by 2.00 score points.`,
  }));
  const many = describe("opportunity_cost", { available: true, items, reasons: [] });
  assert.equal(many.rows.length, 10);
  assert.deepEqual(many.details, ["Showing the first 10 of 12 candidates."]);
  assert.equal(many.headline, "Best alternative: S0, an estimated benefit of 12.0 points.");
});

test("capital productivity score lists each component with its weight", () => {
  const description = describe("cps", {
    score: 66,
    confidence: 0.6,
    weights: { tsr: 40, relative_performance: 20, dividend_growth: 15, earnings_growth: 15, analyst_revisions: 10 },
    component_scores: { tsr: 72, relative_performance: 60 },
    missing_components: ["dividend_growth", "earnings_growth", "analyst_revisions"],
    reasons: ["Dividend Growth data is missing.", "Earnings Growth data is missing.", "Analyst Revisions data is missing."],
  });
  assert.equal(description.headline, "Capital productivity score: 66.0 out of 100.");
  assert.deepEqual(description.rows, [
    ["Total shareholder return", "72.0 (weight 40)"],
    ["Relative performance", "60.0 (weight 20)"],
    ["Dividend growth", "missing (weight 15)"],
    ["Earnings growth", "missing (weight 15)"],
    ["Analyst revisions", "missing (weight 10)"],
    ["Input confidence", "60%"],
  ]);
  assert.deepEqual(description.details, []);
  assert.deepEqual(description.hints, [
    "Add Dividend growth rate to include dividend growth.",
    "Add Earnings growth (%) or Revenue growth (%) to include earnings growth.",
    "Add Forward revisions score (0–100) to include analyst revisions.",
  ]);
  assert.deepEqual(description.caveats, []);
});

test("a score with no inputs says so and keeps invalid-data reasons", () => {
  const weights = { tsr: 40, relative_performance: 20, dividend_growth: 15, earnings_growth: 15, analyst_revisions: 10 };
  const empty = describe("cps", { score: null, confidence: 0, weights, component_scores: {}, missing_components: Object.keys(weights), reasons: ["No score inputs are available."] });
  assert.equal(empty.headline, "Capital productivity score not available: no score inputs were available.");
  assert.deepEqual(empty.details, ["No score inputs are available."]);
  assert.deepEqual(empty.rows, [
    ["Total shareholder return", "missing (weight 40)"],
    ["Relative performance", "missing (weight 20)"],
    ["Dividend growth", "missing (weight 15)"],
    ["Earnings growth", "missing (weight 15)"],
    ["Analyst revisions", "missing (weight 10)"],
    ["Input confidence", "0%"],
  ]);
  assert.equal(empty.hints.length, 5);
  assert.equal(empty.hints[0], "Add Total shareholder return score (0–100) to include total shareholder return.");
  assert.equal(empty.hints[1], "Add Relative performance score (0–100) to include relative performance.");

  const invalid = describe("cps", { score: 50, confidence: 0.5, weights: {}, component_scores: {}, missing_components: [], reasons: ["Tsr data is invalid."] });
  assert.deepEqual(invalid.details, ["Tsr data is invalid."]);
  assert.deepEqual(invalid.rows, [["Input confidence", "50%"]]);
});

test("the sell confidence score notes its weights, hints at missing inputs and explains the flipped inputs", () => {
  const description = describe("sell_score", {
    score: 41.5,
    confidence: 0.55,
    weights: SELL_WEIGHTS,
    component_scores: { tsr: 50, relative_performance: 40, technical_health: 70 },
    missing_components: ["revisions", "dividend_quality", "earnings_growth", "opportunity_cost"],
    reasons: ["Revisions data is missing."],
    ...SELL_DIRECTION_FIELDS,
  });
  assert.equal(description.headline, "Sell confidence score: 41.5 out of 100.");
  assert.deepEqual(description.details, [
    "Weights total 115; the score is normalized by the weights of the available inputs.",
    `${FLIPPED_NOTE} Total shareholder return, Relative performance and Technical health rise as a holding gets healthier, so they count as 100 minus their score. A higher score is a stronger case to sell.`,
  ]);
  assert.equal(description.rows[2][0], "Revisions");
  assert.deepEqual(description.hints, [
    "Add Forward revisions score (0–100) to include revisions.",
    "Add Dividend payout ratio, Dividend growth rate, Dividend consistency (0–1) or Current share price to include dividend quality.",
    "Add Earnings growth (%) or Revenue growth (%) to include earnings growth.",
    "Add Opportunity cost score (0–100) to include opportunity cost.",
  ]);
  assert.deepEqual(description.caveats, []);
});

test("the flipped-inputs note names only the scored inputs the API lists", () => {
  const base = { score: 30, confidence: 1, weights: { tsr: 100 }, missing_components: [], reasons: [], sell_score_direction: SELL_SCORE_DIRECTION };
  const details = (extra) => describe("sell_score", { ...base, ...extra }).details;

  assert.deepEqual(details({ component_scores: { tsr: 30 }, inverted_components: ["tsr"] }), [
    `${FLIPPED_NOTE} Total shareholder return rises as a holding gets healthier, so it counts as 100 minus its score. A higher score is a stronger case to sell.`,
  ]);
  // Order follows the API's list; duplicates, unscored and unlisted components are ignored.
  const ordered = details({
    component_scores: { tsr: 30, technical_health: 40, opportunity_cost: 70 },
    inverted_components: ["technical_health", "tsr", "tsr", "earnings_growth"],
  });
  assert.deepEqual(ordered, [
    `${FLIPPED_NOTE} Technical health and Total shareholder return rise as a holding gets healthier, so they count as 100 minus their score. A higher score is a stronger case to sell.`,
  ]);
  // A perfectly healthy input counts as 0 after the flip, and it is still listed.
  assert.deepEqual(details({ component_scores: { tsr: 0 }, inverted_components: ["tsr"] }), [
    `${FLIPPED_NOTE} Total shareholder return rises as a holding gets healthier, so it counts as 100 minus its score. A higher score is a stronger case to sell.`,
  ]);
  // Nothing was flipped, or the list is missing or malformed, so there is nothing to explain.
  for (const extra of [
    { component_scores: { opportunity_cost: 70 }, inverted_components: ["tsr"] },
    { component_scores: { tsr: 30 }, inverted_components: [] },
    { component_scores: { tsr: 30 } },
    { component_scores: { tsr: 30 }, inverted_components: "tsr" },
    { component_scores: { tsr: "30" }, inverted_components: ["tsr"] },
    { component_scores: { tsr: Number.NaN }, inverted_components: ["tsr"] },
    { component_scores: null, inverted_components: ["tsr"] },
    { component_scores: [30], inverted_components: ["0"] },
    { component_scores: { tsr: 30 }, inverted_components: [5, "", null, {}] },
  ]) {
    assert.deepEqual(details(extra), [], String(Object.keys(extra)));
  }
  // The note is only written for the direction this page understands.
  for (const sell_score_direction of [undefined, null, "", "higher_means_hold", "HIGHER_MEANS_SELL"]) {
    assert.deepEqual(details({ component_scores: { tsr: 30 }, inverted_components: ["tsr"], sell_score_direction }), [], String(sell_score_direction));
  }
});

test("a sell score that does not carry the direction tag is flagged as possibly using the earlier direction", () => {
  const base = { score: 70, confidence: 1, weights: { tsr: 100 }, component_scores: { tsr: 70 }, missing_components: [], reasons: [] };
  assert.deepEqual(describe("sell_score", base).caveats, [LEGACY_DIRECTION]);
  for (const sell_score_direction of [null, "", "higher_means_hold", "HIGHER_MEANS_SELL", 1, true, [SELL_SCORE_DIRECTION]]) {
    const description = describe("sell_score", { ...base, sell_score_direction, inverted_components: ["tsr"] });
    assert.deepEqual(description.caveats, [LEGACY_DIRECTION], String(sell_score_direction));
    assert.deepEqual(description.details, [], String(sell_score_direction));
  }
  assert.deepEqual(describe("sell_score", { ...base, sell_score_direction: SELL_SCORE_DIRECTION }).caveats, []);
});

const GROWTH_ANALYSIS_NOTE = "The earnings growth input was not supplied, so it was taken from the growth analysis, which used";

test("a score that took its earnings growth from the growth analysis says which growth data that used", () => {
  const cps = {
    score: 66,
    confidence: 0.6,
    weights: { tsr: 40, relative_performance: 20, dividend_growth: 15, earnings_growth: 15, analyst_revisions: 10 },
    component_scores: { tsr: 72, earnings_growth: 75 },
    missing_components: ["relative_performance", "dividend_growth", "analyst_revisions"],
    reasons: [],
  };
  const from = (basis) => ({ earnings_growth_input: { source: "growth_analysis", basis } });
  const revenueOnly = `${GROWTH_ANALYSIS_NOTE} revenue growth only.`;
  const blend = `${GROWTH_ANALYSIS_NOTE} a blend of earnings and revenue growth.`;

  assert.deepEqual(describe("cps", { ...cps, ...from("revenue_only") }).caveats, [revenueOnly]);
  assert.deepEqual(describe("cps", { ...cps, ...from("earnings_and_revenue") }).caveats, [blend]);

  const sell = (extra) => describe("sell_score", { ...cps, ...from("revenue_only"), ...extra }).caveats;
  assert.deepEqual(sell(SELL_DIRECTION_FIELDS), [revenueOnly]);
  assert.deepEqual(sell({}), [LEGACY_DIRECTION, revenueOnly]);
});

test("no growth note is shown when the earnings growth input was supplied, saved, earnings-only or unknown", () => {
  const cps = { score: 66, confidence: 0.6, weights: { tsr: 40 }, component_scores: { tsr: 72 }, missing_components: [], reasons: [] };
  const inputs = [
    { source: "request", basis: null },
    { source: "saved_score", basis: null },
    { source: "unavailable", basis: null },
    { source: "growth_analysis", basis: "earnings_only" },
    { source: "growth_analysis", basis: "none" },
    { source: "growth_analysis", basis: null },
    { source: "growth_analysis", basis: "something_new" },
    { source: "request", basis: "revenue_only" },
    "growth_analysis",
    null,
    [],
  ];
  for (const earnings_growth_input of inputs) {
    assert.deepEqual(describe("cps", { ...cps, earnings_growth_input }).caveats, [], JSON.stringify(earnings_growth_input));
  }
  assert.deepEqual(describe("cps", cps).caveats, []);
  assert.deepEqual(describe("sell_score", { ...cps, earnings_growth_input: inputs[0] }).caveats, [LEGACY_DIRECTION]);
  assert.deepEqual(describe("sell_score", { ...cps, ...SELL_DIRECTION_FIELDS, earnings_growth_input: inputs[0] }).caveats, []);
});

test("unknown score components and malformed score parts are handled", () => {
  const description = describe("cps", {
    score: 10, confidence: 1, weights: { new_thing: 100, bad: "x" }, component_scores: { new_thing: "nope" }, missing_components: ["new_thing", 5, ""], reasons: [],
  });
  assert.deepEqual(description.rows, [["New thing", "missing (weight 100)"], ["Bad", "missing"], ["Input confidence", "100%"]]);
  assert.deepEqual(description.hints, []);
  assert.deepEqual(description.details, []);
});

test("replacement candidates are compared with the holding's capital productivity score", () => {
  const description = describe("replacements", {
    compared: true,
    reasons: [],
    candidates: [
      { symbol: "BBB", score: 82, expected_benefit: 9.5, rationale: ["boilerplate"], confidence: 0.82 },
      { symbol: "CCC", score: 75.25, expected_benefit: 2.25, rationale: [], confidence: 0.75 },
    ],
  });
  assert.equal(description.headline, "2 candidates score above this holding's capital productivity score.");
  assert.deepEqual(description.rows, [
    ["BBB", "Score 82.0, 9.5 points above this holding's capital productivity score."],
    ["CCC", "Score 75.3, 2.3 points above this holding's capital productivity score."],
  ]);
  assert.deepEqual(description.details, []);
  assert.deepEqual(description.caveats, [REPLACEMENT_RULE]);
  assert.equal(JSON.stringify(description).includes("boilerplate"), false);
  const single = describe("replacements", { compared: true, reasons: [], candidates: [{ symbol: "BBB", score: 82, expected_benefit: 9.5 }] });
  assert.equal(single.headline, "1 candidate scores above this holding's capital productivity score.");
});

test("replacement candidates say that held symbols are skipped and that the list is capped", () => {
  assert.equal(REPLACEMENT_LIMIT, 5);
  const candidates = (count) => Array.from({ length: count }, (_, index) => ({ symbol: `S${index}`, score: 90 - index, expected_benefit: 10 - index }));
  const below = describe("replacements", { compared: true, reasons: [], candidates: candidates(REPLACEMENT_LIMIT - 1) });
  assert.deepEqual(below.details, []);
  const atLimit = describe("replacements", { compared: true, reasons: [], candidates: candidates(REPLACEMENT_LIMIT) });
  assert.deepEqual(atLimit.details, [`At most ${REPLACEMENT_LIMIT} candidates are listed, strongest first.`]);
  assert.match(REPLACEMENT_RULE, /not already held in this portfolio/);
  assert.match(REPLACEMENT_RULE, /score above this holding's capital productivity score/);
});

test("replacement candidates explain why nothing was compared or found", () => {
  const none = describe("replacements", { compared: true, candidates: [], reasons: ["No supplied candidate scores are above this holding's CPS."] });
  assert.equal(none.headline, "No supplied candidate qualifies as a replacement.");
  assert.deepEqual(none.details, ["No supplied candidate scores are above this holding's CPS."]);
  assert.deepEqual(none.caveats, [REPLACEMENT_RULE]);
  assert.deepEqual(none.rows ?? [], []);

  const notCompared = describe("replacements", { compared: false, candidates: [], reasons: ["No replacement candidate scores were supplied."] });
  assert.equal(notCompared.headline, "Candidates could not be compared with this holding.");
  assert.deepEqual(notCompared.details, ["No replacement candidate scores were supplied."]);
  assert.match(notCompared.hints[0], /^Add Replacement candidates and at least one capital productivity input \(/);
  assert.deepEqual(notCompared.caveats ?? [], []);

  const items = Array.from({ length: 11 }, (_, index) => ({ symbol: `S${index}`, score: 90 - index, expected_benefit: 10 - index }));
  const capped = describe("replacements", { compared: true, reasons: [], candidates: items });
  assert.equal(capped.rows.length, 10);
  assert.deepEqual(capped.details, [`At most ${REPLACEMENT_LIMIT} candidates are listed, strongest first.`, "Showing the first 10 of 11 candidates."]);
  const sparse = describe("replacements", { compared: true, reasons: [], candidates: [{ symbol: "BBB" }, { score: 80 }, 3] });
  assert.deepEqual(sparse.rows, [["BBB", "not available"], ["Candidate", "Score 80.0."]]);
});

test("the sell advisor shows its recommendation, scores, candidates and reasons", () => {
  const labels = { hold: "Hold", watch: "Watch", sell: "Sell", "partial-sell": "Partial sell" };
  for (const [recommendation, label] of Object.entries(labels)) {
    const description = describe("sell_advisor", {
      recommendation, confidence: 0.8, sell_score: 70.04, cps: 55.5, sell_score_direction: SELL_SCORE_DIRECTION,
      rationale: ["sell score is strong enough."], replacement_candidates: [{ symbol: "BBB", expected_benefit: 4.56, score: 80 }],
    });
    assert.equal(description.headline, `Recommendation: ${label}.`, recommendation);
    assert.deepEqual(description.rows, [
      ["Sell confidence score", "70.0 out of 100"],
      ["Capital productivity score", "55.5 out of 100"],
      ["Input confidence", "80%"],
      ["BBB", "+4.6 points"],
    ]);
    assert.deepEqual(description.details, ["Sell score is strong enough."]);
    assert.deepEqual(description.hints, []);
    assert.deepEqual(description.caveats, []);
  }
});

test("a sell advisor result that does not carry the direction tag is flagged as possibly using the earlier direction", () => {
  const result = { recommendation: "hold", confidence: 0.8, sell_score: 70, cps: 55, rationale: [], replacement_candidates: [] };
  assert.deepEqual(describe("sell_advisor", result).caveats, [LEGACY_DIRECTION]);
  for (const sell_score_direction of [null, "", "higher_means_hold", "HIGHER_MEANS_SELL", 1, true]) {
    assert.deepEqual(describe("sell_advisor", { ...result, sell_score_direction }).caveats, [LEGACY_DIRECTION], String(sell_score_direction));
  }
  assert.deepEqual(describe("sell_advisor", { ...result, sell_score_direction: SELL_SCORE_DIRECTION }).caveats, []);
});

test("the sell advisor says why it can only suggest Watch", () => {
  const lowConfidence = describe("sell_advisor", { recommendation: "watch", confidence: 0.49, sell_score: 80, cps: null, rationale: [], replacement_candidates: [] });
  assert.equal(lowConfidence.hints.length, 1);
  assert.match(lowConfidence.hints[0], /only suggest Watch/);
  assert.deepEqual(lowConfidence.rows[1], ["Capital productivity score", "not available"]);
  const noScore = describe("sell_advisor", { recommendation: "watch", confidence: 1, sell_score: null, cps: 50, rationale: [] });
  assert.equal(noScore.hints.length, 1);
  assert.equal(describe("sell_advisor", { recommendation: "hold", confidence: 0.5, sell_score: 10, cps: 50, rationale: [] }).hints.length, 0);
  assert.equal(describe("sell_advisor", { recommendation: "buy", confidence: 1, sell_score: 10 }).headline, UNEXPECTED);
  assert.equal(describe("sell_advisor", { confidence: 1 }).headline, UNEXPECTED);
});

test("the sell advisor caps long candidate lists", () => {
  const replacement_candidates = Array.from({ length: 12 }, (_, index) => ({ symbol: `S${index}`, expected_benefit: index }));
  const description = describe("sell_advisor", { recommendation: "hold", confidence: 1, sell_score: 10, cps: 50, rationale: [], replacement_candidates });
  assert.equal(description.rows.length, 3 + 10);
  assert.deepEqual(description.details, ["Showing the first 10 of 12 candidates."]);
});

test("money, quantity, percentage and date formatting", () => {
  assert.equal(formatAmount(1234.5), "1,234.50");
  assert.equal(formatAmount(-0.5), "-0.50");
  assert.equal(formatAmount(null), "—");
  assert.equal(formatAmount("12"), "—");
  assert.equal(formatAmount(Number.NaN), "—");
  assert.equal(formatQuantity(12.34567), "12.3457");
  assert.equal(formatQuantity(10), "10");
  assert.equal(formatQuantity(1234.5), "1,234.5");
  assert.equal(formatQuantity(undefined), "—");
  assert.equal(formatPercent(12.34), "+12.3%");
  assert.equal(formatPercent(-3.21), "-3.2%");
  assert.equal(formatPercent(0), "0.0%");
  assert.equal(formatPercent(-0.04), "0.0%");
  assert.equal(formatPercent(0.04), "0.0%");
  assert.equal(formatPercent(null), "—");
  assert.equal(formatPercent(null, "not available"), "not available");
  assert.equal(formatAsOf("2026-11-02T10:15:30+00:00"), "2026-11-02 10:15 UTC");
  assert.equal(formatAsOf("2026-11-02T23:59:59-05:00"), "2026-11-03 04:59 UTC");
  assert.equal(formatAsOf("not a date"), null);
  assert.equal(formatAsOf(null), null);
  assert.equal(formatAsOf(20261102), null);
});

test("the portfolio list is validated and labelled", () => {
  const portfolios = parsePortfolioList([
    { id: "p1", name: "  Main  ", currency: "USD", created_at: "2026-10-29T10:00:00+00:00" },
    { id: "p2", name: "", currency: null },
    { name: "No id" },
    null,
    "text",
  ]);
  assert.deepEqual(portfolios, [
    { id: "p1", name: "Main", currency: "USD", created: "2026-10-29" },
    { id: "p2", name: "Unnamed portfolio", currency: "", created: "" },
  ]);
  assert.equal(describePortfolio(portfolios[0]), "Main (USD, created 2026-10-29)");
  assert.equal(describePortfolio(portfolios[1]), "Unnamed portfolio");
  assert.deepEqual(parsePortfolioList([]), []);
  for (const value of [null, {}, "x", 5]) assert.throws(() => parsePortfolioList(value), { message: "The API returned an unexpected portfolio list." });
});

test("a holdings response is validated and normalised", () => {
  const overview = parseHoldingsResponse({
    as_of: "2026-11-02T10:15:30+00:00",
    lots: 3,
    holdings: [{ symbol: "AAA" }, { symbol: "" }, { quantity: 1 }, null, "x"],
    totals: [{ currency: "USD" }, null],
    flags: [{ flag: "short_position", message: "m", count: 1 }, 7],
    notes: ["a", "", 5, "b"],
    truncated: "yes",
  });
  assert.deepEqual(overview, {
    holdings: [{ symbol: "AAA" }],
    totals: [{ currency: "USD" }],
    flags: [{ flag: "short_position", message: "m", count: 1 }],
    notes: ["a", "b"],
    truncated: false,
    lots: 3,
    asOf: "2026-11-02 10:15 UTC",
  });
  assert.equal(parseHoldingsResponse({ holdings: [], truncated: true }).truncated, true);
  const bare = parseHoldingsResponse({ holdings: [] });
  assert.deepEqual([bare.totals, bare.flags, bare.notes, bare.lots, bare.asOf], [[], [], [], null, null]);
  for (const value of [null, {}, [], { holdings: "x" }, "x"]) {
    assert.throws(() => parseHoldingsResponse(value), { message: "The API returned an unexpected holdings response." });
  }
});

test("holding rows have one cell per column", () => {
  const holding = {
    symbol: "AAA", currency: "USD", quantity: 12.5, lot_count: 2, cost_basis: 1000, market_value: 1250.5, price_return_percent: 25.05,
    entry_date: "2025-01-02", days_held: 300, flags: [],
  };
  assert.deepEqual(holdingCells(holding), ["AAA", "USD", "12.5", "2", "1,000.00", "1,250.50", "+25.1%", "2025-01-02", "300", ""]);
  assert.equal(holdingCells(holding).length, HOLDING_COLUMNS.length);
  assert.deepEqual(HOLDING_COLUMNS.map((column) => column.label), [
    "Symbol", "Currency", "Shares", "Lots", "Cost basis", "Market value", "Price return", "Held since", "Days held", "Notes",
  ]);
});

test("holding rows show placeholders and short flag labels", () => {
  const sparse = { symbol: "BBB", currency: null, quantity: -3, lot_count: 1, cost_basis: null, market_value: null, price_return_percent: null, entry_date: null, days_held: null, flags: [
    "short_position", "missing_cost_basis", "missing_entry_date", "missing_market_value", "odd_new_flag",
  ] };
  assert.deepEqual(holdingCells(sparse), [
    "BBB", "—", "-3", "1", "—", "—", "—", "—", "—",
    "short position, no cost basis, no entry date, no market value, odd new flag",
  ]);
  assert.equal(holdingCells({ symbol: "CCC", currency: null, flags: ["mixed_currency"] })[1], "mixed");
  assert.equal(holdingCells({ symbol: "CCC", currency: "EUR", flags: ["mixed_currency"] })[1], "EUR");
  assert.equal(holdingCells({ symbol: "CCC", flags: "x" })[9], "");
});

test("holdings can be filtered by symbol", () => {
  const holdings = [{ symbol: "AAA" }, { symbol: "ABC" }, { symbol: "BRK.B" }];
  assert.deepEqual(filterHoldings(holdings, "a").map((item) => item.symbol), ["AAA", "ABC"]);
  assert.deepEqual(filterHoldings(holdings, " brk.").map((item) => item.symbol), ["BRK.B"]);
  assert.equal(filterHoldings(holdings, ""), holdings);
  assert.equal(filterHoldings(holdings, null), holdings);
  assert.deepEqual(filterHoldings(holdings, "zzz"), []);
});

test("totals are described per currency and never added across currencies", () => {
  assert.deepEqual(describeHoldingsTotals([
    { currency: "USD", holdings: 12, market_value: 1234.5, priced_holdings: 10, cost_basis: 1000, costed_holdings: 12 },
    { currency: "EUR", holdings: 1, market_value: 0, priced_holdings: 0, cost_basis: null, costed_holdings: 0 },
    { currency: null, holdings: 2, market_value: 5, priced_holdings: 1, cost_basis: 4, costed_holdings: 1 },
  ]), [
    "USD: 12 holdings; market value 1,234.50 (10 of 12 priced); cost basis 1,000.00 (12 of 12 with a cost basis).",
    "EUR: 1 holding; market value not available (none priced); cost basis not available (no cost basis).",
    "No currency: 2 holdings; market value 5.00 (1 of 2 priced); cost basis 4.00 (1 of 2 with a cost basis).",
  ]);
  assert.deepEqual(describeHoldingsTotals(null), []);
  assert.deepEqual(describeHoldingsTotals([null, "x"]), []);
});

test("flags are described with their API message and holding count", () => {
  assert.deepEqual(describeHoldingsFlags([
    { flag: "short_position", message: "Short positions are listed but not given a return.", count: 1 },
    { flag: "missing_cost_basis", message: "", count: 3 },
    { flag: "x", message: "No count." },
  ]), [
    "1 holding: Short positions are listed but not given a return.",
    "3 holdings: Missing cost basis",
    "No count.",
  ]);
  assert.deepEqual(describeHoldingsFlags(undefined), []);
});

test("the holdings summary mentions lots and the as-of time when known", () => {
  const overview = (holdings, lots, asOf) => ({ holdings, lots, asOf });
  assert.equal(describeHoldingsSummary(overview([], 0, null)), "This portfolio has no saved holdings.");
  assert.equal(describeHoldingsSummary(overview([{}], 1, "2026-11-02 10:15 UTC")), "1 holding from 1 lot, as of 2026-11-02 10:15 UTC.");
  assert.equal(describeHoldingsSummary(overview([{}, {}], 5, null)), "2 holdings from 5 lots.");
  assert.equal(describeHoldingsSummary(overview([{}, {}], null, "2026-11-02 10:15 UTC")), "2 holdings, as of 2026-11-02 10:15 UTC.");
});

test("a selected holding is summarised with the facts that are known", () => {
  assert.equal(
    describeHolding({ quantity: 10, currency: "USD", cost_basis: 1000, market_value: 1200, price_return_percent: 20, days_held: 1 }),
    "10 shares; cost basis 1,000.00 USD; market value 1,200.00 USD; price return +20.0%; held 1 day.",
  );
  assert.equal(describeHolding({ quantity: 2.5, currency: null, cost_basis: null, market_value: null }), "2.5 shares.");
});

test("input hints follow a holding's data flags and use real field names", () => {
  assert.deepEqual(holdingInputHints({ flags: [] }), []);
  assert.deepEqual(holdingInputHints(null), []);
  const hints = holdingInputHints({ flags: ["missing_market_value", "missing_cost_basis", "missing_entry_date", "short_position", "mixed_currency"] });
  assert.equal(hints.length, 5);
  assert.match(hints[0], /does not convert currencies.*cannot run until the lots share one currency/);
  assert.match(hints[1], /short position/);
  assert.match(hints[2], /Enter the Current share price/);
  assert.match(hints[3], /Enter the Cost basis/);
  assert.match(hints[4], /Enter the Entry date/);
});

// ---- Loading research ----------------------------------------------------------------------------

const parseResearch = (patch) => parseResearchResponse(researchFixture(patch), "AAA");
const lineFor = (research, key) => research.inputs.find((input) => input.key === key)?.line;
const textFor = (research, key) => research.inputs.find((input) => input.key === key)?.text;

test("research inputs are number fields of one holding, listed once each in field order", () => {
  const keys = PIP_RESEARCH_INPUTS.map((input) => input.key);
  assert.deepEqual(keys, [
    "position.market_price",
    "scores.tsr",
    "scores.relative_performance",
    "scores.technical_health",
    "growth.earnings_growth_percent",
    "growth.revenue_growth_percent",
    "forward.target_upside_percent",
    "forward.analyst_revisions_score",
  ]);
  const order = PIP_MODULE_FIELDS.map(fieldKey);
  assert.deepEqual(keys, [...keys].sort((a, b) => order.indexOf(a) - order.indexOf(b)), "the same order as the field list");
  for (const input of PIP_RESEARCH_INPUTS) {
    const field = PIP_MODULE_FIELDS.find((item) => fieldKey(item) === input.key);
    assert.ok(field && field.type === "number" && field.scope === "holding", input.key);
    assert.ok(input.name && input.from && Array.isArray(input.evidence), input.key);
    const names = input.evidence.map((path) => path.split(".").at(-1));
    assert.equal(new Set(names).size, names.length, `${input.key} evidence ends in distinct names`);
  }
  assert.equal(new Set(PIP_RESEARCH_INPUTS.map((input) => input.name)).size, keys.length, "names are distinct");
  assert.equal(Object.isFrozen(PIP_RESEARCH_INPUTS), true);
});

test("a full research answer fills eight inputs and explains each with the numbers behind it", () => {
  const research = parseResearch();
  assert.deepEqual(research.inputs.map(({ key, name, text }) => [key, name, text]), [
    ["position.market_price", "Share price", "112"],
    ["scores.tsr", "Total shareholder return score", "65"],
    ["scores.relative_performance", "Relative performance score", "35"],
    ["scores.technical_health", "Technical health score", "58.9"],
    ["growth.earnings_growth_percent", "Earnings growth", "12.5"],
    ["growth.revenue_growth_percent", "Revenue growth", "8.1"],
    ["forward.target_upside_percent", "Target upside", "16.07"],
    ["forward.analyst_revisions_score", "Forward revisions score", "80"],
  ]);
  assert.deepEqual(research.inputs.map((input) => input.line), FULL_LINES);
  assert.deepEqual(research.skipped, []);
  assert.deepEqual(research.warnings, []);
  assert.equal(research.asOf, "2025-12-31");
  assert.equal(research.version, "research-1");
  assert.equal(research.hasScores, true);
});

test("box text is the value to four decimals without trailing zeros", () => {
  const research = parseResearch({
    price: { price: 112.123456 },
    growth: { earnings_growth_percent: -6.5, revenue_growth_percent: -0.00001 },
    analyst: { target_upside_percent: 0 },
  });
  assert.equal(textFor(research, "position.market_price"), "112.1235");
  assert.equal(textFor(research, "growth.earnings_growth_percent"), "-6.5");
  assert.equal(textFor(research, "growth.revenue_growth_percent"), "0");
  assert.equal(textFor(research, "forward.target_upside_percent"), "0");
  assert.equal(lineFor(research, "growth.earnings_growth_percent"), "Earnings growth -6.5% — reported by Yahoo Finance.");
  assert.equal(lineFor(research, "position.market_price"), "Share price 112.1235 — Yahoo Finance historical close, as of 2025-12-31.");
});

test("a value Yahoo could not give is left blank with the API's reason, or a general one", () => {
  const research = parseResearch({
    growth: { earnings_growth_percent: null },
    unavailable_metrics: { earnings_growth_percent: "Yahoo Finance did not expose earnings growth for this symbol." },
    analyst: { target_upside_percent: null },
    scores: { revisions: { score: null, reason: "Yahoo did not provide 30-day EPS revision counts for this symbol." } },
  });
  assert.deepEqual(research.inputs.map((input) => input.key), [
    "position.market_price",
    "scores.tsr",
    "scores.relative_performance",
    "scores.technical_health",
    "growth.revenue_growth_percent",
  ]);
  assert.deepEqual(research.skipped, [
    { key: "growth.earnings_growth_percent", name: "Earnings growth", reason: "Yahoo Finance did not expose earnings growth for this symbol." },
    { key: "forward.target_upside_percent", name: "Target upside", reason: "Yahoo did not provide this value." },
    { key: "forward.analyst_revisions_score", name: "Forward revisions score", reason: "Yahoo did not provide 30-day EPS revision counts for this symbol." },
  ]);
});

test("research with nothing usable fills nothing and keeps every reason", () => {
  const research = parseResearchResponse(emptyResearchFixture(), "AAA");
  assert.deepEqual(research.inputs, []);
  assert.deepEqual(research.skipped.map((item) => item.key), PIP_RESEARCH_INPUTS.map((input) => input.key));
  const reasonOf = (key) => research.skipped.find((item) => item.key === key).reason;
  assert.equal(reasonOf("scores.tsr"), "Yahoo history covers 30 days; at least 330 are needed to score a 1-year total return.");
  assert.equal(reasonOf("scores.technical_health"), "Yahoo returned 2 daily closes; at least 200 are needed to score technical health.");
  assert.equal(reasonOf("growth.revenue_growth_percent"), "Yahoo Finance did not expose revenue growth for this symbol.");
  assert.equal(reasonOf("position.market_price"), "Yahoo did not provide this value.");
  assert.equal(research.hasScores, true);
});

test("a reason that already ends in ! or ? is not given a full stop as well", () => {
  const research = parseResearch({
    growth: { earnings_growth_percent: null, revenue_growth_percent: null },
    unavailable_metrics: { earnings_growth_percent: "Was it reported?", revenue_growth_percent: "It was not reported!" },
  });
  const notes = describeResearchLoad(research, "AAA").notes;
  assert.ok(notes.includes("Earnings growth was not filled: Was it reported?"), notes.join(" | "));
  assert.ok(notes.includes("Revenue growth was not filled: It was not reported!"), notes.join(" | "));
});

test("an answer from an API without research scores still fills what it has", () => {
  const payload = researchFixture();
  delete payload.scores;
  const research = parseResearchResponse(payload, "AAA");
  assert.equal(research.hasScores, false);
  assert.equal(research.version, null);
  assert.deepEqual(research.inputs.map((input) => input.key), [
    "position.market_price",
    "growth.earnings_growth_percent",
    "growth.revenue_growth_percent",
    "forward.target_upside_percent",
  ]);
  assert.deepEqual(research.skipped.map((item) => item.key), [
    "scores.tsr",
    "scores.relative_performance",
    "scores.technical_health",
    "forward.analyst_revisions_score",
  ]);
  for (const item of research.skipped) assert.equal(item.reason, "This PIP API version does not return research scores.");
});

test("a scores block that is not an object counts as no scores at all", () => {
  for (const scores of ["n/a", 5, ["research-1"], null]) {
    const payload = researchFixture();
    payload.scores = scores;
    const research = parseResearchResponse(payload, "AAA");
    assert.equal(research.hasScores, false, JSON.stringify(scores));
    assert.equal(research.version, null, JSON.stringify(scores));
    assert.equal(research.inputs.length, 4, JSON.stringify(scores));
    assert.deepEqual(research.skipped.map((item) => item.reason), Array(4).fill("This PIP API version does not return research scores."), JSON.stringify(scores));
  }
});

test("without research scores, only the score inputs are blamed on the API version", () => {
  const payload = researchFixture({ growth: { earnings_growth_percent: null }, analyst: { target_upside_percent: null } });
  delete payload.scores;
  const research = parseResearchResponse(payload, "AAA");
  const reasonOf = (key) => research.skipped.find((item) => item.key === key).reason;
  assert.equal(reasonOf("growth.earnings_growth_percent"), "Yahoo did not provide this value.");
  assert.equal(reasonOf("forward.target_upside_percent"), "Yahoo did not provide this value.");
  assert.equal(reasonOf("scores.tsr"), "This PIP API version does not return research scores.");
});

test("an answer that is not an object with a symbol is rejected", () => {
  for (const payload of [null, undefined, [], "AAA", 5, {}, { symbol: 5 }, { symbol: null }]) {
    assert.throws(() => parseResearchResponse(payload, "AAA"), /^Error: The API returned an unexpected research response, so nothing was filled\.$/, String(payload));
  }
});

test("research for another symbol is never used, whatever the case or spacing", () => {
  assert.throws(() => parseResearch({ symbol: "BBB" }), /different symbol than AAA, so nothing was filled\./);
  assert.throws(() => parseResearchResponse(researchFixture({ symbol: "" }), "AAA"), /different symbol/);
  assert.doesNotThrow(() => parseResearchResponse(researchFixture({ symbol: " aaa " }), " Aaa "));
  assert.throws(() => parseResearchResponse(researchFixture(), ""), /different symbol/);
  assert.throws(() => parseResearchResponse(researchFixture({ symbol: " " }), " "), /different symbol/, "a blank symbol matches nothing, not even a blank answer");
});

test("values outside a field's range are left blank instead of filled", () => {
  const research = parseResearch({
    price: { price: 0 },
    scores: { tsr: { score: 120 }, revisions: { score: -1 } },
    analyst: { target_upside_percent: -120 },
  });
  assert.deepEqual(research.inputs.map((input) => input.key), [
    "scores.relative_performance",
    "scores.technical_health",
    "growth.earnings_growth_percent",
    "growth.revenue_growth_percent",
  ]);
  assert.deepEqual(research.skipped.map(({ key, reason }) => [key, reason]), [
    ["position.market_price", "Current share price must be greater than 0 (Yahoo returned 0)."],
    ["scores.tsr", "Total shareholder return score (0–100) must be no more than 100 (Yahoo returned 120)."],
    ["forward.target_upside_percent", "Target upside (%) must be at least -100 (Yahoo returned -120)."],
    ["forward.analyst_revisions_score", "Forward revisions score (0–100) must be at least 0 (Yahoo returned -1)."],
  ]);
});

test("values that are not finite numbers are left blank", () => {
  const research = parseResearch({
    price: { price: "112" },
    growth: { earnings_growth_percent: Number.NaN, revenue_growth_percent: Number.POSITIVE_INFINITY },
    scores: { tsr: { score: true } },
  });
  assert.deepEqual(research.inputs.map((input) => input.key), [
    "scores.relative_performance",
    "scores.technical_health",
    "forward.target_upside_percent",
    "forward.analyst_revisions_score",
  ]);
  assert.deepEqual(research.skipped.map((item) => item.key), [
    "position.market_price",
    "scores.tsr",
    "growth.earnings_growth_percent",
    "growth.revenue_growth_percent",
  ]);
  for (const item of research.skipped) assert.equal(item.reason, "Yahoo returned a value that is not a usable number.");
});

test("the lines say 'at' for a level that is matched, and above or below otherwise", () => {
  const research = parseResearch({
    scores: {
      tsr: { raw: { return_percent: -3.26, history_days: 1 } },
      relative_performance: { raw: { gap_points: 0.04, history_days: 330 } },
      technical_health: { raw: { close_vs_long_average_percent: 0.04, close_vs_short_average_percent: -0.04, below_high_percent: 0 } },
      revisions: { raw: { up: 0, down: 2, breadth: -1, periods_counted: ["0q"] } },
    },
  });
  assert.equal(lineFor(research, "scores.tsr"), "Total shareholder return score 65 — -3.3% return on adjusted closes over 1 day.");
  assert.equal(lineFor(research, "scores.relative_performance"), "Relative performance score 35 — 0.0 points against SPY over 330 shared days.");
  assert.equal(lineFor(research, "scores.technical_health"), "Technical health score 58.9 — last close is at its 200-day average, at its 50-day average and at its 365-day high.");
  assert.equal(lineFor(research, "forward.analyst_revisions_score"), "Forward revisions score 80 — 0 upward and 2 downward EPS estimate revisions in the last 30 days across 1 period (breadth -1.00).");
  const ahead = parseResearch({ scores: { relative_performance: { raw: { gap_points: 6 } }, technical_health: { raw: { close_vs_long_average_percent: -5, close_vs_short_average_percent: 2.04 } } } });
  assert.equal(lineFor(ahead, "scores.relative_performance"), "Relative performance score 35 — +6.0 points against SPY over 364 shared days.");
  assert.equal(lineFor(ahead, "scores.technical_health"), "Technical health score 58.9 — last close is 5.0% below its 200-day average, 2.0% above its 50-day average and 12.0% below its 365-day high.");
});

test("the return line names its price basis and says plain daily closes when it is not stated", () => {
  assert.equal(lineFor(parseResearch({ returns: { basis: "close" } }), "scores.tsr"), "Total shareholder return score 65 — +12.0% return on daily closes over 364 days.");
  assert.equal(lineFor(parseResearch({ returns: { basis: null } }), "scores.tsr"), "Total shareholder return score 65 — +12.0% return on daily closes over 364 days.");
});

test("the share price line states its source, date and staleness", () => {
  const line = (price) => lineFor(parseResearch({ price }), "position.market_price");
  assert.equal(line({ source: "Alpaca", as_of: "2026-01-01T14:59:00Z", stale: true }), "Share price 112 — Alpaca, as of 2026-01-01 14:59 UTC, marked stale.");
  assert.equal(line({ source: "Twelve Data", as_of: "2026-01-02", stale: true }), "Share price 112 — Twelve Data, as of 2026-01-02, marked stale.");
  assert.equal(line({ source: null, as_of: null }), "Share price 112 — source unavailable.");
  assert.equal(line({ source: "  ", as_of: "not a date" }), "Share price 112 — source unavailable.");
  assert.equal(line({ as_of: "not a date" }), "Share price 112 — Yahoo Finance historical close.");
  assert.equal(line({ stale: "yes" }), "Share price 112 — Yahoo Finance historical close, as of 2025-12-31.", "only a true stale flag is shown");
});

test("the target upside line names the rating and target price it has", () => {
  const line = (analyst) => lineFor(parseResearch({ analyst }), "forward.target_upside_percent");
  assert.equal(line({ rating: null }), "Target upside 16.07% — analyst target price 130.");
  assert.equal(line({ target_price: null }), "Target upside 16.07% — analyst rating Buy.");
  assert.equal(line({ target_price: 130.5 }), "Target upside 16.07% — analyst rating Buy, target price 130.5.");
  assert.equal(line({ target_price: 0 }), "Target upside 16.07% — analyst rating Buy, target price 0.");
  assert.equal(line({ rating: " ", target_price: null }), "Target upside 16.07% — analyst data.");
});

test("a growth line without a stated source says so, and an explanation without evidence stays general", () => {
  assert.equal(lineFor(parseResearch({ growth: { source: null } }), "growth.earnings_growth_percent"), "Earnings growth 12.5% — source not stated.");
  assert.equal(lineFor(parseResearch({ growth: { source: "  Yahoo Finance " } }), "growth.revenue_growth_percent"), "Revenue growth 8.1% — reported by Yahoo Finance.");
  const thin = parseResearch({ scores: { technical_health: { raw: { long_average_days: null } }, revisions: { raw: { periods_counted: null } }, tsr: { raw: { history_days: null } } } });
  assert.equal(lineFor(thin, "scores.technical_health"), "Technical health score 58.9 — from Yahoo research.");
  assert.equal(lineFor(thin, "forward.analyst_revisions_score"), "Forward revisions score 80 — from Yahoo research.");
  assert.equal(lineFor(thin, "scores.tsr"), "Total shareholder return score 65 — from Yahoo research.");
});

test("the as-of date comes from the end of the history, then from the fetch time, else nothing", () => {
  assert.equal(parseResearch().asOf, "2025-12-31");
  assert.equal(parseResearch({ returns: { end_date: null }, fetched_at: "2026-01-02T09:30:00.123456+00:00" }).asOf, "2026-01-02");
  assert.equal(parseResearch({ returns: { end_date: "2025-12-30T23:00:00Z" }, fetched_at: "2026-01-02T09:30:00+00:00" }).asOf, "2025-12-30");
  assert.equal(parseResearch({ returns: { end_date: "soon" }, fetched_at: "later" }).asOf, null);
  assert.equal(parseResearch({ returns: { end_date: 20251231 }, fetched_at: null }).asOf, null);
  assert.equal(parseResearch({ returns: { end_date: ["2025-12-30"] }, fetched_at: ["2026-01-02"] }).asOf, null, "only text is read as a date");
});

test("a date that does not exist on the calendar is not shown", () => {
  const fetched = "2026-01-02T09:30:00+00:00";
  assert.equal(parseResearch({ returns: { end_date: "2025-02-30" }, fetched_at: fetched }).asOf, "2026-01-02", "30 February rolls over to March, so it is rejected");
  assert.equal(parseResearch({ returns: { end_date: "2025-13-45" }, fetched_at: fetched }).asOf, "2026-01-02");
  assert.equal(parseResearch({ returns: { end_date: "2025-04-31T10:00:00Z" }, fetched_at: null }).asOf, null);
  assert.equal(parseResearch({ returns: { end_date: "2024-02-29" }, fetched_at: fetched }).asOf, "2024-02-29", "a leap day is a real date");
  assert.equal(lineFor(parseResearch({ price: { as_of: "2025-02-30" } }), "position.market_price"), "Share price 112 — Yahoo Finance historical close.");
  assert.equal(lineFor(parseResearch({ price: { as_of: "2024-02-29" } }), "position.market_price"), "Share price 112 — Yahoo Finance historical close, as of 2024-02-29.");
});

test("the score rule version is passed on only when it is text", () => {
  assert.equal(parseResearch({ scores: { version: "research-2" } }).version, "research-2");
  assert.equal(parseResearch({ scores: { version: "" } }).version, null);
  assert.equal(parseResearch({ scores: { version: 1 } }).version, null);
});

test("API warnings are passed on as text, with blank and non-text ones dropped", () => {
  const research = parseResearch({ warnings: ["Alpaca quote was unavailable.", "  ", 5, null, " The shared snapshot is old. "] });
  assert.deepEqual(research.warnings, ["Alpaca quote was unavailable.", "The shared snapshot is old."]);
  assert.deepEqual(parseResearch({ warnings: "not a list" }).warnings, []);
});

test("research inputs count as unchanged only while their box still holds the loaded text", () => {
  const { inputs } = parseResearch();
  const values = Object.fromEntries(inputs.map((input) => [input.key, input.text]));
  assert.equal(unchangedResearchInputs(inputs, values).length, 8);
  assert.deepEqual(
    unchangedResearchInputs(inputs, { ...values, "scores.tsr": "66", "growth.revenue_growth_percent": "" }).map((input) => input.key),
    inputs.map((input) => input.key).filter((key) => key !== "scores.tsr" && key !== "growth.revenue_growth_percent"),
  );
  assert.equal(unchangedResearchInputs(inputs, { ...values, "scores.tsr": " 65 " }).length, 8, "spaces around the same text are not an edit");
  assert.equal(unchangedResearchInputs(inputs, { ...values, "scores.tsr": "65.0" }).length, 7, "retyped text is the user's own");
  assert.deepEqual(unchangedResearchInputs(inputs, {}), []);
  assert.deepEqual(unchangedResearchInputs([], values), []);
});

test("the load summary counts what was filled, then lists the numbers, the blanks and the warnings", () => {
  const full = parseResearch();
  const summary = describeResearchLoad(full, " aaa ");
  assert.equal(summary.headline, "Filled 8 of 8 inputs for AAA from Yahoo research (data as of 2025-12-31). Every value stays editable; nothing was saved.");
  assert.equal(summary.filled, 8);
  assert.deepEqual(summary.notes, FULL_LINES);

  const partial = parseResearch({
    growth: { earnings_growth_percent: null },
    unavailable_metrics: { earnings_growth_percent: "Yahoo Finance did not expose earnings growth for this symbol" },
    analyst: { target_upside_percent: null },
    warnings: ["Careful."],
  });
  const some = describeResearchLoad(partial, "AAA");
  assert.equal(some.headline, "Filled 6 of 8 inputs for AAA from Yahoo research (data as of 2025-12-31). Every value stays editable; nothing was saved.");
  assert.equal(some.filled, 6);
  assert.deepEqual(some.notes, [
    ...partial.inputs.map((input) => input.line),
    "Earnings growth was not filled: Yahoo Finance did not expose earnings growth for this symbol.",
    "Target upside was not filled: Yahoo did not provide this value.",
    "Careful.",
  ]);

  const undated = describeResearchLoad(parseResearch({ returns: { end_date: null }, fetched_at: null }), "AAA");
  assert.equal(undated.headline, "Filled 8 of 8 inputs for AAA from Yahoo research. Every value stays editable; nothing was saved.");
});

test("a load with nothing usable says so and still lists why", () => {
  const none = describeResearchLoad(parseResearchResponse(emptyResearchFixture({ warnings: ["Yahoo was slow."] }), "AAA"), "AAA");
  assert.equal(none.headline, "Yahoo research did not give any usable values for AAA.");
  assert.equal(none.filled, 0);
  assert.equal(none.notes.length, 9);
  assert.ok(none.notes.slice(0, 8).every((note) => note.includes(" was not filled: ")));
  assert.equal(none.notes[8], "Yahoo was slow.");
});

test("the result provenance lists only inputs that still hold the loaded text", () => {
  const research = parseResearch();
  assert.equal(describeResearchProvenance(research, []), null);
  assert.deepEqual(describeResearchProvenance(research, research.inputs.slice(0, 2)), {
    heading: "Inputs from Yahoo research (data as of 2025-12-31; score rules research-1)",
    lines: [FULL_LINES[0], FULL_LINES[1]],
    note: "A module uses only the inputs it needs. Values you edited after loading are your own and are not listed.",
  });
  const heading = (meta) => describeResearchProvenance(meta, research.inputs).heading;
  assert.equal(heading({ asOf: "2025-12-31", version: null }), "Inputs from Yahoo research (data as of 2025-12-31)");
  assert.equal(heading({ asOf: null, version: "research-1" }), "Inputs from Yahoo research (score rules research-1)");
  assert.equal(heading({ asOf: null, version: null }), "Inputs from Yahoo research");
});

test("the core stays free of DOM, network and storage access", async () => {
  const source = await readFile(new URL("../pip-modules-core.js", import.meta.url), "utf8");
  for (const word of ["document", "window", "fetch", "localStorage", "XMLHttpRequest", "innerHTML", "navigator"]) {
    assert.equal(new RegExp(`\\b${word}\\b`).test(source), false, word);
  }
});
