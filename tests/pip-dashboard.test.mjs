import assert from "node:assert/strict";
import {
  calculatePipScore,
  describePipHurdle,
  PIP_DEFAULT_API_URL,
  PIP_DEFAULT_REQUIRED_RETURN_PERCENT,
  PIP_CPS_WEIGHTS,
  PIP_SELL_SCORE_WEIGHTS,
  portfolioImportPreviewFromCsv,
  portfolioRowsFromCsv,
} from "../pip-dashboard.js";

assert.equal(PIP_DEFAULT_API_URL, "https://stockscanner-pip-api.onrender.com");
assert.equal(PIP_DEFAULT_REQUIRED_RETURN_PERCENT, 7);

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

console.log("PIP browser score and import previews passed");
