// A research answer shaped like POST /api/pip/portfolios/{id}/research, for the placeholder symbol AAA.
// A Python test checks that every path the page reads exists in a real result, so this only has to be plausible.

const FULL = {
  symbol: "AAA",
  fetched_at: "2025-12-31T21:00:00+00:00",
  price: { price: 112, source: "Yahoo Finance historical close", as_of: "2025-12-31", stale: false },
  returns: {
    start_date: "2025-01-01",
    end_date: "2025-12-31",
    history_days: 364,
    aligned_history_days: 364,
    price_return_percent: 12,
    spy_return_percent: 18,
    relative_performance_percentage_points: -6,
    basis: "adjusted_close",
  },
  dividends: { trailing_365_days_per_share: null, history_complete: false, events: [], note: "Yahoo dividend amounts are per share, not portfolio cash income." },
  analyst: { rating: "Buy", target_price: 130, target_upside_percent: 16.07 },
  growth: { earnings_growth_percent: 12.5, revenue_growth_percent: 8.1, source: "Yahoo Finance" },
  analyst_revisions: { source: "Yahoo Finance", periods: {}, note: "Raw EPS estimate revision counts." },
  scores: {
    version: "research-1",
    tsr: { score: 65, raw: { return_percent: 12, history_days: 364 }, reason: null },
    relative_performance: { score: 35, raw: { gap_points: -6, history_days: 364 }, reason: null },
    revisions: { score: 80, raw: { up: 4, down: 1, breadth: 0.6, periods_counted: ["0q", "+1q"] }, reason: null },
    technical_health: {
      score: 58.9,
      raw: {
        closes: 261,
        long_average_days: 200,
        close_vs_long_average_percent: 5,
        short_average_days: 50,
        close_vs_short_average_percent: -2,
        high_window_days: 365,
        below_high_percent: 12,
        parts: { long_average: 66.7, short_average: 40, high: 70 },
      },
      reason: null,
    },
  },
  unavailable_metrics: {
    earnings_growth_percent: null,
    revenue_growth_percent: null,
    tsr_score: null,
    relative_performance_score: null,
    analyst_revisions_score: null,
    technical_health_score: null,
  },
  warnings: [],
};

const isPlain = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

// What the page should fill and say for researchFixture() when nothing is changed.
export const FULL_RESEARCH_TEXTS = Object.freeze({
  "position.market_price": "112",
  "scores.tsr": "65",
  "scores.relative_performance": "35",
  "scores.technical_health": "58.9",
  "growth.earnings_growth_percent": "12.5",
  "growth.revenue_growth_percent": "8.1",
  "forward.target_upside_percent": "16.07",
  "forward.analyst_revisions_score": "80",
});

export const FULL_RESEARCH_LINES = Object.freeze([
  "Share price 112 — Yahoo Finance historical close, as of 2025-12-31.",
  "Total shareholder return score 65 — +12.0% return on adjusted closes over 364 days.",
  "Relative performance score 35 — -6.0 points against SPY over 364 shared days.",
  "Technical health score 58.9 — last close is 5.0% above its 200-day average, 2.0% below its 50-day average and 12.0% below its 365-day high.",
  "Earnings growth 12.5% — reported by Yahoo Finance.",
  "Revenue growth 8.1% — reported by Yahoo Finance.",
  "Target upside 16.07% — analyst rating Buy, target price 130.",
  "Forward revisions score 80 — 4 upward and 1 downward EPS estimate revisions in the last 30 days across 2 periods (breadth +0.60).",
]);

function merge(base, patch) {
  const result = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    result[key] = isPlain(value) && isPlain(base[key]) ? merge(base[key], value) : value;
  }
  return result;
}

// Objects in `patch` are merged into the full answer; arrays and other values replace it.
export function researchFixture(patch = {}) {
  return structuredClone(merge(FULL, patch));
}

// The same answer with every value the page can fill taken away, each with the reason the API gives.
export function emptyResearchFixture(patch = {}) {
  return researchFixture(merge({
    price: { price: null, source: null, as_of: null },
    analyst: { rating: null, target_price: null, target_upside_percent: null },
    growth: { earnings_growth_percent: null, revenue_growth_percent: null },
    scores: {
      tsr: { score: null, reason: "Yahoo history covers 30 days; at least 330 are needed to score a 1-year total return." },
      relative_performance: { score: null, reason: "This symbol and SPY share 30 days of price history; at least 330 are needed to score performance against SPY." },
      revisions: { score: null, reason: "Yahoo did not provide 30-day EPS revision counts for this symbol." },
      technical_health: { score: null, reason: "Yahoo returned 2 daily closes; at least 200 are needed to score technical health." },
    },
    unavailable_metrics: {
      earnings_growth_percent: "Yahoo Finance did not expose earnings growth for this symbol.",
      revenue_growth_percent: "Yahoo Finance did not expose revenue growth for this symbol.",
    },
  }, patch));
}
