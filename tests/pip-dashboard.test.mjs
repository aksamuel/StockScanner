import assert from "node:assert/strict";
import {
  calculatePipScore,
  describePipHurdle,
  describePipReviewHolding,
  describePipReviewSkipped,
  describePipReviewSummary,
  describePipReviewTitle,
  PIP_DEFAULT_API_URL,
  PIP_DEFAULT_REQUIRED_RETURN_PERCENT,
  PIP_DEFAULT_REVIEW_REPLACEMENT_LIMIT,
  PIP_DEFAULT_REVIEW_TOP_N,
  PIP_CPS_WEIGHTS,
  PIP_SELL_SCORE_WEIGHTS,
  portfolioImportPreviewFromCsv,
  portfolioRowsFromCsv,
} from "../pip-dashboard.js";

assert.equal(PIP_DEFAULT_API_URL, "https://stockscanner-pip-api.onrender.com");
assert.equal(PIP_DEFAULT_REQUIRED_RETURN_PERCENT, 7);
assert.equal(PIP_DEFAULT_REVIEW_TOP_N, 5);
assert.equal(PIP_DEFAULT_REVIEW_REPLACEMENT_LIMIT, 5);

assert.equal(calculatePipScore(
  Object.fromEntries(Object.keys(PIP_CPS_WEIGHTS).map((key) => [key, 100])),
  PIP_CPS_WEIGHTS,
).score, 100);

const sell = calculatePipScore(
  Object.fromEntries(Object.keys(PIP_SELL_SCORE_WEIGHTS).map((key) => [key, 100])),
  PIP_SELL_SCORE_WEIGHTS,
);
assert.equal(Object.values(PIP_SELL_SCORE_WEIGHTS).reduce((sum, value) => sum + value, 0), 115);
assert.equal(sell.score, 100);
assert.equal(sell.confidence, 1);

const missing = calculatePipScore({}, PIP_CPS_WEIGHTS);
assert.equal(missing.score, null);
assert.equal(missing.confidence, 0);
assert.equal(missing.reasons.length, Object.keys(PIP_CPS_WEIGHTS).length);

const normalized = calculatePipScore({ tsr: 120 }, { tsr: 40, relative_performance: 60 });
assert.equal(normalized.score, 100);
assert.equal(normalized.confidence, 0.4);
assert.equal(normalized.reasons.length, 1);

const positions = portfolioRowsFromCsv(
  "ClientAccountID, Symbol, Quantity, Cost Basis Price, Open Date Time, Currency\nU12345678,AAPL,2,120.50,20250102,USD",
);
assert.equal(positions[0].symbol, "AAPL");
assert.equal(positions[0].bought_on, "2025-01-02");
assert.equal(positions[0].currency, "USD");

const dividendImport = portfolioImportPreviewFromCsv(
  "Symbol,DividendAmount,PayDate,Currency\nAAPL,4,2026-01-01,USD",
);
assert.equal(dividendImport.dividends, 1);
assert.equal(dividendImport.positions.length, 0);
const transactionImport = portfolioImportPreviewFromCsv(
  "Symbol,TradeDate,TransactionType,Shares,Price,Currency\nAAPL,2026-01-01,buy,2,120,USD",
);
assert.equal(transactionImport.transactions, 1);
assert.equal(transactionImport.positions.length, 0);
const costBasisPosition = portfolioImportPreviewFromCsv(
  "Symbol,Quantity,CostBasis,TradeDate,Currency\nAAPL,2,240,2025-01-02,USD",
).positions[0];
assert.equal(costBasisPosition.buy_price, 240);
assert.equal(costBasisPosition.bought_on, "2025-01-02");

const hurdleBase = {
  required_annual_return_percent: 7,
  status: "below",
  outlook_status: "below",
  lot_count: 1,
  days_held: 730,
  return_basis: "total",
  return_percent: 10,
  hurdle_return_percent: 14.49,
  annualized_return_percent: 4.88,
  shortfall_amount: 4.49,
  required_return_by_horizon: [
    { years: 1, required_annual_return_percent: 11.3 },
    { years: 3, required_annual_return_percent: 9.2 },
    { years: 5, required_annual_return_percent: null },
  ],
  forward_return_percent: 3,
  holding_assumed_return_percent: null,
  years_to_catch_up: null,
  replacement_assumed_return_percent: null,
  replacement_months_to_hurdle_gain: null,
  reasons: [],
  note: "Scenario figures are arithmetic, not forecasts.",
};

assert.deepEqual(describePipHurdle(undefined), ["Return hurdle: unavailable from this API version."]);
assert.deepEqual(describePipHurdle(null), ["Return hurdle: unavailable from this API version."]);
assert.deepEqual(describePipHurdle(hurdleBase), [
  "Return hurdle (7% per year): below the hurdle path.",
  "Total return (price plus dividends received) is 10.0% against 14.5% needed to match the hurdle path after 730 days.",
  "Annualized return: 4.9% per year.",
  "Shortfall against the hurdle path: 4.49.",
  "Return needed to reach the hurdle path: 11.3% per year for 1 year, 9.2% per year for 3 years.",
  "Analyst target upside of 3.0% is below the hurdle.",
]);

const ahead = describePipHurdle({
  ...hurdleBase,
  status: "meets",
  outlook_status: "meets",
  forward_return_percent: 9,
  shortfall_amount: -3.2,
  required_return_by_horizon: [],
});
assert.equal(ahead[0], "Return hurdle (7% per year): on or ahead of the hurdle path.");
assert.ok(ahead.includes("Analyst target upside of 9.0% meets or exceeds the hurdle."));
assert.ok(!ahead.some((line) => line.startsWith("Shortfall")));
assert.ok(!ahead.some((line) => line.startsWith("Return needed")));

const multiLot = describePipHurdle({ ...hurdleBase, lot_count: 3, return_basis: "price_only" });
assert.match(multiLot[1], /^Price-only return is 10\.0% .* after 730 days \(cost-weighted across 3 lots\)\.$/);

const unavailable = describePipHurdle({
  ...hurdleBase,
  status: "unavailable",
  outlook_status: "unavailable",
  days_held: null,
  return_basis: null,
  return_percent: null,
  hurdle_return_percent: null,
  annualized_return_percent: null,
  shortfall_amount: null,
  required_return_by_horizon: [{ years: 1, required_annual_return_percent: null }],
  forward_return_percent: null,
  reasons: ["Entry date is unavailable, so holding time cannot be measured.", "Analyst target upside is unavailable."],
});
assert.deepEqual(unavailable, [
  "Return hurdle (7% per year): cannot be judged yet.",
  "Notes: Entry date is unavailable, so holding time cannot be measured. Analyst target upside is unavailable.",
]);

const scenarios = describePipHurdle({
  ...hurdleBase,
  required_annual_return_percent: 7.5,
  holding_assumed_return_percent: 12,
  years_to_catch_up: 3.857,
  replacement_assumed_return_percent: 15.25,
  replacement_months_to_hurdle_gain: 5.809,
});
assert.equal(scenarios[0], "Return hurdle (7.5% per year): below the hurdle path.");
assert.ok(scenarios.includes(
  "Scenario: at an assumed 12% per year this holding would catch up with the hurdle path in about 3.9 years.",
));
assert.ok(scenarios.includes(
  "Scenario: a replacement assumed to earn 15.25% per year would take about 5.8 months to gain 7.5%.",
));
assert.equal(scenarios.at(-1), hurdleBase.note);

const alreadyAhead = describePipHurdle({
  ...hurdleBase,
  holding_assumed_return_percent: 12,
  years_to_catch_up: 0,
  note: "",
});
assert.ok(alreadyAhead.includes(
  "Scenario: at an assumed 12% per year this holding is already on or ahead of the hurdle path.",
));
assert.match(alreadyAhead.at(-1), /not forecasts/);

const noScenarioNote = describePipHurdle({
  ...hurdleBase,
  holding_assumed_return_percent: 5,
  years_to_catch_up: null,
});
assert.ok(!noScenarioNote.some((line) => line.startsWith("Scenario")));
assert.ok(!noScenarioNote.includes(hurdleBase.note));

const malformed = describePipHurdle({
  status: "surprising",
  required_annual_return_percent: "7",
  return_percent: "10",
  hurdle_return_percent: Number.NaN,
  required_return_by_horizon: "none",
  reasons: [null, 4, ""],
});
assert.deepEqual(malformed, ["Return hurdle (required annual return): cannot be judged yet."]);

const reviewHurdle = {
  ...hurdleBase,
  status: "unavailable",
  outlook_status: "unavailable",
  return_basis: "price_only",
  return_percent: 4.2,
  hurdle_return_percent: 14.5,
  excess_return_percentage_points: -10.3,
  annualized_return_percent: 2.1,
  shortfall_amount: 123.45,
  required_return_by_horizon: [{ years: 1, required_annual_return_percent: 11.3 }],
  forward_return_percent: null,
  reasons: ["Dividends are unavailable.", "Enter dividends received (0 if none)."],
};
const reviewEntry = {
  rank: 1,
  symbol: "AAA",
  currency: "USD",
  hurdle: reviewHurdle,
  cps: 35,
  dead_money: { symbol: "AAA", is_dead_money: null, confidence: 0.6, reasons: ["A verdict is withheld."] },
  replacements: {
    compared: true,
    reasons: [],
    candidates: [{ symbol: "BBB", score: 82, rationale: ["Hidden rationale."], expected_benefit: 47, confidence: 0.82 }],
  },
};

const reviewLines = describePipReviewHolding(reviewEntry);
assert.deepEqual(reviewLines, [
  "Behind the hurdle path by 10.3 percentage points (price-only).",
  "Return hurdle (7% per year): cannot be judged yet.",
  "Price-only return is 4.2% against 14.5% needed to match the hurdle path after 730 days.",
  "Annualized return: 2.1% per year.",
  "Shortfall against the hurdle path: 123.45.",
  "Return needed to reach the hurdle path: 11.3% per year for 1 year.",
  "Notes: Dividends are unavailable. Enter dividends received (0 if none).",
  "Saved CPS: 35.0 / 100.",
  "Dead money: verdict withheld (60% input confidence).",
  "Dead-money evidence: A verdict is withheld.",
  "Replacement candidate BBB: score 82.0, 47.0 points above this holding's CPS.",
]);
// A candidate's derived confidence is not evidence strength, so it is never shown as confidence.
assert.ok(!reviewLines.join(" ").includes("82%"));
assert.ok(!reviewLines.join(" ").includes("Hidden rationale"));

assert.equal(
  describePipReviewHolding({ ...reviewEntry, hurdle: { ...reviewHurdle, return_basis: "total" } })[0],
  "Behind the hurdle path by 10.3 percentage points.",
);
assert.equal(
  describePipReviewHolding({ ...reviewEntry, hurdle: { ...reviewHurdle, excess_return_percentage_points: 2 } })[0],
  "Ahead of the hurdle path by 2.0 percentage points (price-only).",
);
assert.ok(!describePipReviewHolding({ ...reviewEntry, hurdle: { ...reviewHurdle, excess_return_percentage_points: null } })
  .some((line) => /hurdle path by/.test(line)));

assert.ok(describePipReviewHolding({ ...reviewEntry, dead_money: { is_dead_money: true, confidence: 0.8, reasons: [] } })
  .includes("Dead money: flagged for review (80% input confidence)."));
assert.ok(!describePipReviewHolding({ ...reviewEntry, dead_money: { is_dead_money: true, confidence: 0.8, reasons: [] } })
  .some((line) => line.startsWith("Dead-money evidence")));
assert.ok(describePipReviewHolding({ ...reviewEntry, dead_money: { is_dead_money: false, confidence: 1, reasons: [] } })
  .includes("Dead money: not flagged (100% input confidence)."));
assert.ok(describePipReviewHolding({ ...reviewEntry, dead_money: { is_dead_money: null } })
  .includes("Dead money: verdict withheld."));
assert.ok(describePipReviewHolding({ ...reviewEntry, dead_money: { is_dead_money: false, confidence: 7 } })
  .includes("Dead money: not flagged (100% input confidence)."));
assert.ok(describePipReviewHolding({ ...reviewEntry, dead_money: { is_dead_money: false, confidence: -3 } })
  .includes("Dead money: not flagged (0% input confidence)."));
assert.ok(describePipReviewHolding({ ...reviewEntry, dead_money: "yes" })
  .includes("Dead money: unavailable from this API version."));

const notCompared = describePipReviewHolding({
  ...reviewEntry,
  cps: null,
  replacements: {
    compared: false,
    reasons: ["No replacement candidate scores were supplied.", "This holding has no saved CPS."],
    candidates: [],
  },
});
assert.ok(notCompared.includes("No saved CPS for this holding; analyze it to save one."));
assert.ok(notCompared.includes("Replacements: not compared. No replacement candidate scores were supplied. This holding has no saved CPS."));
assert.ok(describePipReviewHolding({
  ...reviewEntry,
  replacements: {
    compared: true,
    reasons: ["No supplied candidate scores are above this holding's CPS."],
    candidates: [],
  },
}).includes("Replacements: none suggested. No supplied candidate scores are above this holding's CPS."));
assert.deepEqual(describePipReviewHolding({
  ...reviewEntry,
  replacements: {
    compared: true,
    reasons: [],
    candidates: [
      { symbol: "BBB", score: 82, expected_benefit: 47 },
      { symbol: "EEE", score: 60.25, expected_benefit: 25.25 },
    ],
  },
}).slice(-2), [
  "Replacement candidate BBB: score 82.0, 47.0 points above this holding's CPS.",
  "Replacement candidate EEE: score 60.3, 25.3 points above this holding's CPS.",
]);
assert.deepEqual(describePipReviewHolding({
  ...reviewEntry,
  replacements: {
    compared: true,
    reasons: [],
    candidates: [null, { symbol: 5, score: 1 }, { symbol: "EEE", score: "9" }, { symbol: "FFF", score: 70 }],
  },
}).slice(-1), ["Replacement candidate FFF: score 70.0."]);
assert.ok(describePipReviewHolding({
  ...reviewEntry,
  replacements: { compared: true, reasons: [], candidates: [null] },
}).includes("Replacements: none suggested."));
assert.ok(describePipReviewHolding({ ...reviewEntry, replacements: undefined })
  .includes("Replacements: unavailable from this API version."));

assert.deepEqual(describePipReviewHolding(null), []);
assert.deepEqual(describePipReviewHolding("AAA"), []);
assert.deepEqual(describePipReviewHolding({}), [
  "Return hurdle: unavailable from this API version.",
  "No saved CPS for this holding; analyze it to save one.",
  "Dead money: unavailable from this API version.",
  "Replacements: unavailable from this API version.",
]);

assert.equal(describePipReviewTitle(reviewEntry), "1. AAA (USD)");
assert.equal(describePipReviewTitle({ rank: 2, symbol: " BBB ", currency: " " }), "2. BBB");
assert.equal(describePipReviewTitle({ symbol: "CCC", currency: "EUR" }), "CCC (EUR)");
assert.equal(describePipReviewTitle({ rank: Number.NaN, symbol: 7 }), "Unknown holding");
assert.equal(describePipReviewTitle(null), "Unknown holding");

const reviewBase = {
  required_annual_return_percent: 7,
  minimum_holding_days: 365,
  top_n: 5,
  summary: { holdings: 6, not_analysable: 1, held_under_minimum: 2, meeting_hurdle: 1, behind_hurdle: 2, truncated: false },
  top: [reviewEntry, { ...reviewEntry, rank: 2, symbol: "DDD" }],
  skipped: [],
  notes: [],
};
assert.deepEqual(describePipReviewSummary(reviewBase), [
  "Reviewed 6 open holdings against 7% per year.",
  "2 behind the hurdle path; 1 on or ahead of it; 2 held under 365 days; 1 could not be compared.",
  "Advice is shown for all 2 holdings behind the hurdle path.",
]);
assert.equal(
  describePipReviewSummary({
    ...reviewBase,
    summary: { ...reviewBase.summary, behind_hurdle: 8 },
    top: Array.from({ length: 5 }, (_, index) => ({ ...reviewEntry, rank: index + 1 })),
  })[2],
  "Advice is shown for the 5 holdings furthest behind the hurdle path.",
);
assert.equal(
  describePipReviewSummary({ ...reviewBase, summary: { ...reviewBase.summary, behind_hurdle: 4 }, top: [reviewEntry] })[2],
  "Advice is shown for the holding furthest behind the hurdle path.",
);
assert.equal(
  describePipReviewSummary({ ...reviewBase, summary: { ...reviewBase.summary, behind_hurdle: 1 }, top: [reviewEntry] })[2],
  "Advice is shown for the holding behind the hurdle path.",
);
assert.deepEqual(describePipReviewSummary({
  ...reviewBase,
  required_annual_return_percent: 7.5,
  summary: { holdings: 1, not_analysable: 0, held_under_minimum: 1, meeting_hurdle: 0, behind_hurdle: 0, truncated: false },
  top: [],
}), [
  "Reviewed 1 open holding against 7.5% per year.",
  "0 behind the hurdle path; 0 on or ahead of it; 1 held under 365 days; 0 could not be compared.",
  "No holding is ranked as behind the hurdle path.",
]);
assert.deepEqual(describePipReviewSummary({ summary: {}, top: "none" }), [
  "Reviewed open holdings against the required annual return.",
  "No holding is ranked as behind the hurdle path.",
]);
assert.ok(describePipReviewSummary({ ...reviewBase, minimum_holding_days: null })[1].includes("held under the minimum holding period"));
for (const unavailableReview of [undefined, null, {}, { summary: "none" }, "review"]) {
  assert.deepEqual(describePipReviewSummary(unavailableReview), ["Portfolio review: unavailable from this API version."]);
}

assert.deepEqual(describePipReviewSkipped([
  {
    reason: "no_entry_date",
    message: "Entry date is unavailable for at least one lot, so holding time cannot be measured.",
    count: 3,
    symbols: ["AAA", "BBB", "CCC"],
  },
  { reason: "short_position", message: "Short positions are not compared.", count: 1, symbols: ["DDD"] },
]), [
  "3 holdings not compared. Entry date is unavailable for at least one lot, so holding time cannot be measured. Affected: AAA, BBB, CCC.",
  "1 holding not compared. Short positions are not compared. Affected: DDD.",
]);
assert.deepEqual(describePipReviewSkipped([{ message: "Message.", count: 25, symbols: ["AAA", "BBB"] }]), [
  "25 holdings not compared. Message. Affected: AAA, BBB and 23 more.",
]);
assert.deepEqual(describePipReviewSkipped([{ message: "Message.", count: 1, symbols: ["AAA", "BBB"] }]), [
  "2 holdings not compared. Message. Affected: AAA, BBB.",
]);
assert.deepEqual(describePipReviewSkipped([{ count: 2, symbols: ["AAA"] }]), [
  "2 holdings not compared. These holdings could not be compared. Affected: AAA and 1 more.",
]);
assert.deepEqual(describePipReviewSkipped([{ message: "Message.", count: 2 }]), [
  "2 holdings not compared. Message.",
]);
assert.deepEqual(describePipReviewSkipped([null, "x", {}, { count: 0, symbols: [] }, { message: "Message.", count: Number.NaN }]), []);
assert.deepEqual(describePipReviewSkipped(undefined), []);
assert.deepEqual(describePipReviewSkipped("none"), []);

console.log("PIP browser score and import previews passed");
