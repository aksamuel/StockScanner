import assert from "node:assert/strict";
import {
  portfolioActionDecision,
  filterPortfolioHoldings,
  detectedPortfolioBroker,
  recommendedTargetPrice,
  sellReviewSignal,
  portfolioRowsFromCsv,
  annualizedTargetReturnPercent,
  marketDaysHeld,
} from "../portfolio-analysis.js";

const longHolding = { symbol: "LONG", quantity: 2, buy_price: 100, target_price: null, stop_loss: null };
const shortHolding = { symbol: "SHORT", quantity: -2, buy_price: 100, target_price: null, stop_loss: null };
const recoveredHolding = { symbol: "PROFIT", returnPercent: 5, decision: { code: "hold" } };
const losingHolding = { symbol: "LOSS", returnPercent: -5, decision: { code: "sell" } };
assert.deepEqual(filterPortfolioHoldings([recoveredHolding, losingHolding]).map(({ symbol }) => symbol), ["PROFIT", "LOSS"]);
assert.deepEqual(filterPortfolioHoldings([recoveredHolding, losingHolding], "profitable").map(({ symbol }) => symbol), ["PROFIT"]);
assert.deepEqual(filterPortfolioHoldings([recoveredHolding, losingHolding], "sell").map(({ symbol }) => symbol), ["LOSS"]);
const ibkrCsv = "Symbol, Quantity, Cost Basis Price, Open Date Time, Currency\nAAPL,2,120.50,20250102,USD";
assert.equal(detectedPortfolioBroker(ibkrCsv), "IBKR");
assert.equal(portfolioRowsFromCsv(ibkrCsv)[0].bought_on, "2025-01-02");
assert.equal(portfolioRowsFromCsv("symbol,quantity,buy_price\nAAPL,2,120", "USD")[0].bought_on, null);
assert.throws(() => portfolioRowsFromCsv("symbol,quantity,buy_price\nAAPL,2,", "USD"), /buy_price is required/);

assert.equal(recommendedTargetPrice(longHolding).price, 107);
assert.equal(recommendedTargetPrice(longHolding, { profitReviewPercent: 0 }).price, 100);
assert.equal(recommendedTargetPrice(longHolding, { profitReviewPercent: 100 }).price, 200);
assert.equal(recommendedTargetPrice(shortHolding, { profitReviewPercent: 12 }).price, 88);
assert.equal(recommendedTargetPrice(longHolding, { profitReviewPercent: 120 }).price, 107);
assert.equal(recommendedTargetPrice({ ...longHolding, target_price: 123 }, { profitReviewPercent: 12 }).price, 123);
assert.equal(annualizedTargetReturnPercent(7, 126), (Math.pow(1.07, 0.5) - 1) * 100);
assert.equal(annualizedTargetReturnPercent(7, 0), 0);
assert.equal(annualizedTargetReturnPercent(7, null), null);
assert.equal(marketDaysHeld("2026-01-05", new Date("2026-01-12T12:00:00Z")), 5);
assert.equal(marketDaysHeld(null), null);

const decisionContext = {
  currentPrice: 108,
  returnPercent: 8,
  scannerRecommendation: "watch",
  recommendedTarget: { price: 120, type: "automatic", source: "test" },
};
assert.equal(portfolioActionDecision(longHolding, { ...decisionContext, profitReviewPercent: 7 }).code, "partial-sell");
assert.equal(portfolioActionDecision(longHolding, { ...decisionContext, profitReviewPercent: 10 }).code, "hold");
const weakScannerContext = { ...decisionContext, scannerRecommendation: "watch", scannerScore: 30,
  heldMarketDays: 126, profitReviewPercent: 7, returnPercent: 3 };
const belowAnnualTarget = portfolioActionDecision(longHolding, weakScannerContext);
assert.equal(belowAnnualTarget.code, "partial-sell");
assert.match(belowAnnualTarget.label, /below return target/);
assert.match(belowAnnualTarget.reasons[0], /3\.44% over 126 market days/);
assert.equal(portfolioActionDecision(longHolding, { ...weakScannerContext, returnPercent: 4 }).code, "hold");
assert.equal(sellReviewSignal(longHolding, 108, 8, 7).code, "sell-review");
assert.equal(sellReviewSignal(longHolding, 108, 8, 10).code, "monitor");
const reviewDecisions = [
  portfolioActionDecision(
    { ...longHolding, stop_loss: 90 },
    { currentPrice: 80, returnPercent: -20, recommendedTarget: { price: 100, type: "manual" } },
  ),
  portfolioActionDecision(
    longHolding,
    { currentPrice: 100, returnPercent: 0, concentrationPercent: 20, recommendedTarget: { price: 120 } },
  ),
  portfolioActionDecision(
    longHolding,
    { currentPrice: 100, returnPercent: 0, concentrationPercent: 5, scannerRecommendation: "buy",
      recommendedTarget: { price: 120 } },
  ),
  portfolioActionDecision(longHolding, { currentPrice: null, returnPercent: null }),
];
assert.deepEqual(
  reviewDecisions.sort((left, right) => right.priority - left.priority).map(({ code }) => code),
  ["sell", "partial-sell", "hold", "unavailable"],
);
assert.throws(
  () => portfolioRowsFromCsv("symbol,quantity,buy_price,buy_date\nABC,1,10,2026-01-01"),
  /currency is missing/,
);
assert.equal(
  portfolioRowsFromCsv("symbol,quantity,buy_price,buy_date\nABC,1,10,2026-01-01", "SAR")[0].currency,
  "SAR",
);

console.log("Portfolio review target range, long/short target, and recalculation checks passed");
