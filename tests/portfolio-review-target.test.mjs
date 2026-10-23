import assert from "node:assert/strict";
import {
  portfolioActionDecision,
  recommendedTargetPrice,
  sellReviewSignal,
  portfolioRowsFromCsv,
} from "../portfolio-analysis.js";

const longHolding = { symbol: "LONG", quantity: 2, buy_price: 100, target_price: null, stop_loss: null };
const shortHolding = { symbol: "SHORT", quantity: -2, buy_price: 100, target_price: null, stop_loss: null };

assert.equal(recommendedTargetPrice(longHolding).price, 107);
assert.equal(recommendedTargetPrice(longHolding, { profitReviewPercent: 0 }).price, 100);
assert.equal(recommendedTargetPrice(longHolding, { profitReviewPercent: 100 }).price, 200);
assert.equal(recommendedTargetPrice(shortHolding, { profitReviewPercent: 12 }).price, 88);
assert.equal(recommendedTargetPrice(longHolding, { profitReviewPercent: 120 }).price, 107);
assert.equal(recommendedTargetPrice({ ...longHolding, target_price: 123 }, { profitReviewPercent: 12 }).price, 123);

const decisionContext = {
  currentPrice: 108,
  returnPercent: 8,
  scannerRecommendation: "watch",
  recommendedTarget: { price: 120, type: "automatic", source: "test" },
};
assert.equal(portfolioActionDecision(longHolding, { ...decisionContext, profitReviewPercent: 7 }).code, "partial-sell");
assert.equal(portfolioActionDecision(longHolding, { ...decisionContext, profitReviewPercent: 10 }).code, "hold");
assert.equal(sellReviewSignal(longHolding, 108, 8, 7).code, "sell-review");
assert.equal(sellReviewSignal(longHolding, 108, 8, 10).code, "monitor");
assert.throws(
  () => portfolioRowsFromCsv("symbol,quantity,buy_price,buy_date\nABC,1,10,2026-01-01"),
  /currency is missing/,
);
assert.equal(
  portfolioRowsFromCsv("symbol,quantity,buy_price,buy_date\nABC,1,10,2026-01-01", "SAR")[0].currency,
  "SAR",
);

console.log("Portfolio review target range, long/short target, and recalculation checks passed");
