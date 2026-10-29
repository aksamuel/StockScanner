import assert from "node:assert/strict";
import {
  calculatePipScore,
  PIP_CPS_WEIGHTS,
  PIP_SELL_SCORE_WEIGHTS,
  portfolioImportPreviewFromCsv,
  portfolioRowsFromCsv,
} from "../pip-dashboard.js";

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

console.log("PIP browser score and import previews passed");
