import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  CONFIDENCE_NOTE,
  HOLDING_COLUMNS,
  PIP_COMPONENT_FIELDS,
  PIP_MODULES,
  PIP_MODULE_FIELDS,
  REPLACEMENT_LIMIT,
  buildModuleRequest,
  describeHolding,
  describeHoldingsFlags,
  describeHoldingsSummary,
  describeHoldingsTotals,
  describeModuleResult,
  describePortfolio,
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
} from "../pip-modules-core.js";

const UNEXPECTED = "The API returned an unexpected response, so no result is shown.";
const READ_ONLY = "Read-only result: nothing was saved and no orders were placed.";
const REPLACEMENT_RULE = "Candidates are listed only when they score above this holding's capital productivity score and are not already held in this portfolio.";

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

test("the sell confidence score notes its weights, hints at missing inputs, and carries the direction caveat", () => {
  const description = describe("sell_score", {
    score: 41.5,
    confidence: 0.55,
    weights: { tsr: 20, relative_performance: 20, revisions: 20, dividend_quality: 15, technical_health: 15, earnings_growth: 10, opportunity_cost: 15 },
    component_scores: { tsr: 50, relative_performance: 40, technical_health: 30 },
    missing_components: ["revisions", "dividend_quality", "earnings_growth", "opportunity_cost"],
    reasons: ["Revisions data is missing."],
  });
  assert.equal(description.headline, "Sell confidence score: 41.5 out of 100.");
  assert.deepEqual(description.details, ["Weights total 115; the score is normalized by the weights of the available inputs."]);
  assert.equal(description.rows[2][0], "Revisions");
  assert.deepEqual(description.hints, [
    "Add Forward revisions score (0–100) to include revisions.",
    "Add Dividend payout ratio, Dividend growth rate, Dividend consistency (0–1) or Current share price to include dividend quality.",
    "Add Earnings growth (%) or Revenue growth (%) to include earnings growth.",
    "Add Opportunity cost score (0–100) to include opportunity cost.",
  ]);
  assert.equal(description.caveats.length, 1);
  assert.match(description.caveats[0], /scores of 65 or more are read as 'sell'.*open question/);
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

  const sell = describe("sell_score", { ...cps, ...from("revenue_only") }).caveats;
  assert.equal(sell.length, 2);
  assert.match(sell[0], /scores of 65 or more are read as 'sell'.*open question/);
  assert.equal(sell[1], revenueOnly);
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
  assert.equal(describe("sell_score", { ...cps, earnings_growth_input: inputs[0] }).caveats.length, 1);
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
      recommendation, confidence: 0.8, sell_score: 70.04, cps: 55.5,
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
    assert.equal(description.caveats.length, 1);
    assert.match(description.caveats[0], /open question/);
  }
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

test("the core stays free of DOM, network and storage access", async () => {
  const source = await readFile(new URL("../pip-modules-core.js", import.meta.url), "utf8");
  for (const word of ["document", "window", "fetch", "localStorage", "XMLHttpRequest", "innerHTML", "navigator"]) {
    assert.equal(new RegExp(`\\b${word}\\b`).test(source), false, word);
  }
});
