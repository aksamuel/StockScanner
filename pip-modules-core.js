// Pure logic for the PIP module runner page: request building, result descriptions and holdings formatting.
// This file must stay free of DOM and network access so the page and the Node tests can both import it.
import {
  PIP_SYMBOL_PATTERN,
  describePipHurdle,
  finiteNumber,
  nonEmptyStrings,
  parseOptionalNumber,
  parsePipCandidates,
  pluralize,
} from "./pip-shared.js";

export const MAX_MODULE_CANDIDATES = 500;
// Mirrors replacement_limit in DecisionEngine.analyze_position; a Python test compares them.
export const REPLACEMENT_LIMIT = 5;
export const CONFIDENCE_NOTE = "Input confidence is how much of the needed data was available, not how strong the signal is.";

const MAX_RESULT_ROWS = 10;
const NOT_AVAILABLE = "not available";
const UNEXPECTED_RESPONSE = "The API returned an unexpected response, so no result is shown.";
const SELL_DIRECTION_CAVEAT = "Most of these inputs rise as a holding gets healthier, yet scores of 65 or more are read as 'sell'. That direction is an open question, so treat this result as unverified.";
const OPPORTUNITY_CAVEAT = "Estimated benefit is a score-based estimate (half of the score gap, in score points). It is not a return forecast or an amount of money.";
const FORWARD_CAVEAT = "An indicator built from the inputs you supplied, not a forecast.";
const GROWTH_ANALYSIS_BASES = new Map([
  ["revenue_only", "revenue growth only"],
  ["earnings_and_revenue", "a blend of earnings and revenue growth"],
]);
const REPLACEMENT_RULE = "Candidates are listed only when they score above this holding's capital productivity score and are not already held in this portfolio.";

// Keep these ids in the same order as ModuleName in stockscanner/pip/api.py; a Python test compares them.
export const PIP_MODULES = Object.freeze([
  { id: "lifecycle", label: "Position lifecycle", needs: "Uses the saved lots. Share price, cost basis, entry date and dividends received fill gaps." },
  { id: "hurdle", label: "Return hurdle", needs: "Uses the saved lots and the required annual return. Dividends received give a total return." },
  { id: "dead_money", label: "Dead money", needs: "Works best with position values plus score or outlook inputs." },
  { id: "dividends", label: "Dividend analysis", needs: "Uses saved dividend history. Share price, payout ratio, growth rate and consistency add detail." },
  { id: "growth", label: "Growth analysis", needs: "Needs earnings growth or revenue growth." },
  { id: "forward_looking", label: "Forward-looking analysis", needs: "Needs target upside or a forward revisions score." },
  { id: "opportunity_cost", label: "Opportunity cost", needs: "Needs replacement candidates and at least one capital productivity input." },
  { id: "cps", label: "Capital productivity score", needs: "Uses whichever of its five score inputs are available." },
  { id: "sell_score", label: "Sell confidence score", needs: "Uses whichever of its seven score inputs are available." },
  { id: "replacements", label: "Replacement candidates", needs: "Needs replacement candidates and at least one capital productivity input." },
  { id: "sell_advisor", label: "Sell advisor", needs: "Combines the sell score, capital productivity score and replacement candidates." },
]);

// One field per line: a Python test parses the paths and bounds and checks them against the API schema.
export const PIP_MODULE_FIELDS = Object.freeze([
  { path: ["position", "market_price"], label: "Current share price", type: "number", positive: true, scope: "holding", group: "Position", help: "Gives the holding a market value when the saved lots have none, and a dividend yield." },
  { path: ["position", "cost_basis"], label: "Cost basis", type: "number", min: 0, scope: "holding", group: "Position", help: "Total cost of the whole position, not per share. With the entry date it replaces the saved lots in the return hurdle." },
  { path: ["position", "entry_date"], label: "Entry date", type: "date", scope: "holding", group: "Position", help: "When the position was opened. With the cost basis it replaces the saved lots in the return hurdle." },
  { path: ["position", "dividends_received"], label: "Dividends received since entry", type: "number", min: 0, scope: "holding", group: "Position", help: "Enter 0 if none. Needed to measure a total return." },
  { path: ["hurdle", "required_annual_return_percent"], label: "Required annual return (%)", type: "number", min: 0, max: 100, value: "7", scope: "shared", group: "Return hurdle", help: "The yearly return a holding should earn. Defaults to 7." },
  { path: ["hurdle", "holding_assumed_return_percent"], label: "What-if annual return for this holding (%)", type: "number", min: -99.99, max: 1000, scope: "holding", group: "Return hurdle", help: "Optional. Shows how long this holding would take to catch up with the hurdle path." },
  { path: ["hurdle", "replacement_assumed_return_percent"], label: "What-if annual return for a replacement (%)", type: "number", min: -99.99, max: 1000, scope: "shared", group: "Return hurdle", help: "Optional. Shows how long a replacement would take to gain the required return." },
  { path: ["scores", "tsr"], label: "Total shareholder return score (0–100)", type: "number", min: 0, max: 100, scope: "holding", group: "Scores", help: "A 0–100 score, higher is better. Leave blank to use a saved score, if there is one." },
  { path: ["scores", "relative_performance"], label: "Relative performance score (0–100)", type: "number", min: 0, max: 100, scope: "holding", group: "Scores", help: "Performance against the market as a 0–100 score, higher is better. Leave blank to use a saved score, if there is one." },
  { path: ["scores", "technical_health"], label: "Technical health score (0–100)", type: "number", min: 0, max: 100, scope: "holding", group: "Scores", help: "A 0–100 trend and chart health score, higher is healthier. Leave blank to use a saved score, if there is one." },
  { path: ["scores", "opportunity_cost"], label: "Opportunity cost score (0–100)", type: "number", min: 0, max: 100, scope: "holding", group: "Scores", help: "A 0–100 score where higher means capital is likely better used elsewhere. Leave blank to use a saved score, if there is one." },
  { path: ["growth", "earnings_growth_percent"], label: "Earnings growth (%)", type: "number", scope: "holding", group: "Growth", help: "Yearly earnings growth, in percent." },
  { path: ["growth", "revenue_growth_percent"], label: "Revenue growth (%)", type: "number", scope: "holding", group: "Growth", help: "Yearly revenue growth, in percent." },
  { path: ["forward", "target_upside_percent"], label: "Target upside (%)", type: "number", min: -100, scope: "holding", group: "Outlook", help: "Upside to the analyst target price, in percent." },
  { path: ["forward", "analyst_revisions_score"], label: "Forward revisions score (0–100)", type: "number", min: 0, max: 100, scope: "holding", group: "Outlook", help: "Recent analyst estimate revisions as a 0–100 score, higher is better." },
  { path: ["dividends", "payout_ratio"], label: "Dividend payout ratio", type: "number", min: 0, scope: "holding", group: "Dividends", help: "Dividends divided by earnings: 0.6 means 60%. Above 1 counts against the score." },
  { path: ["dividends", "dividend_growth_rate"], label: "Dividend growth rate", type: "number", min: -1, scope: "holding", group: "Dividends", help: "Yearly dividend growth as a fraction: 0.05 means 5%." },
  { path: ["dividends", "consistency_score"], label: "Dividend consistency (0–1)", type: "number", min: 0, max: 1, scope: "holding", group: "Dividends", help: "How reliably dividends have been paid, from 0 to 1." },
  { path: ["peer_scores"], label: "Replacement candidates", type: "candidates", scope: "shared", group: "Replacement candidates", placeholder: "AAA:82, BBB:90", help: "SYMBOL:score pairs separated by commas. Scores use the same 0–100 scale as this holding's capital productivity score." },
]);

export function fieldKey(field) {
  return field.path.join(".");
}

export function fieldInputId(field) {
  return `moduleInput-${field.path.join("-")}`;
}

const FIELD_BY_KEY = new Map(PIP_MODULE_FIELDS.map((field) => [fieldKey(field), field]));

export function labelOf(key) {
  return FIELD_BY_KEY.get(key)?.label ?? key;
}

const COMPONENT_LABELS = new Map(Object.entries({
  tsr: "Total shareholder return",
  relative_performance: "Relative performance",
  dividend_growth: "Dividend growth",
  earnings_growth: "Earnings growth",
  analyst_revisions: "Analyst revisions",
  revisions: "Revisions",
  dividend_quality: "Dividend quality",
  technical_health: "Technical health",
  opportunity_cost: "Opportunity cost",
}));

export const PIP_COMPONENT_FIELDS = new Map(Object.entries({
  tsr: ["scores.tsr"],
  relative_performance: ["scores.relative_performance"],
  dividend_growth: ["dividends.dividend_growth_rate"],
  earnings_growth: ["growth.earnings_growth_percent", "growth.revenue_growth_percent"],
  analyst_revisions: ["forward.analyst_revisions_score"],
  revisions: ["forward.analyst_revisions_score"],
  dividend_quality: ["dividends.payout_ratio", "dividends.dividend_growth_rate", "dividends.consistency_score", "position.market_price"],
  technical_health: ["scores.technical_health"],
  opportunity_cost: ["scores.opportunity_cost"],
}));

const POSITION_KEYS = ["position.market_price", "position.cost_basis", "position.entry_date", "position.dividends_received"];
const CPS_INPUT_KEYS = ["scores.tsr", "scores.relative_performance", "dividends.dividend_growth_rate", "growth.earnings_growth_percent", "growth.revenue_growth_percent", "forward.analyst_revisions_score"];

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sentence(text) {
  const value = String(text).trim();
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value;
}

function humanize(name) {
  return sentence(String(name).replace(/_/g, " "));
}

function componentLabel(name) {
  return COMPONENT_LABELS.get(name) ?? humanize(name);
}

function listLabels(keys) {
  const labels = keys.map(labelOf);
  return labels.length > 1 ? `${labels.slice(0, -1).join(", ")} or ${labels[labels.length - 1]}` : labels[0] ?? "";
}

function numberText(value, digits = 1, suffix = "") {
  const number = finiteNumber(value);
  return number === null ? NOT_AVAILABLE : `${number.toFixed(digits)}${suffix}`;
}

function confidenceText(value) {
  const number = finiteNumber(value);
  return number === null ? NOT_AVAILABLE : `${Math.round(Math.min(1, Math.max(0, number)) * 100)}%`;
}

const MISSING_REASON = /(?:\bis missing|\bmissing or invalid)\.?$/i;

function reasonLines(reasons, { dropMissing = false } = {}) {
  return nonEmptyStrings(reasons)
    .map((reason) => sentence(reason))
    .filter((reason) => !dropMissing || !MISSING_REASON.test(reason));
}

// ---- Money, percentages and dates -------------------------------------------------------------

export function formatAmount(value) {
  const number = finiteNumber(value);
  return number === null ? "—" : number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatQuantity(value) {
  const number = finiteNumber(value);
  return number === null ? "—" : number.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function formatPercent(value, empty = "—") {
  const number = finiteNumber(value);
  if (number === null) return empty;
  const text = number.toFixed(1);
  if (Number(text) === 0) return "0.0%";
  return `${number > 0 ? "+" : ""}${text}%`;
}

export function formatAsOf(value) {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

// ---- Building a module request ----------------------------------------------------------------

function parseDate(label, value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const date = /^\d{4}-\d{2}-\d{2}$/.test(text) ? new Date(`${text}T00:00:00Z`) : null;
  if (!date || Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== text) {
    throw new Error(`${label} must be a date in YYYY-MM-DD format.`);
  }
  return text;
}

function parseFieldValue(field, raw) {
  if (field.type === "candidates") {
    const candidates = parsePipCandidates(raw, { unique: true, max: MAX_MODULE_CANDIDATES });
    return candidates.length ? candidates : null;
  }
  if (field.type === "date") return parseDate(field.label, raw);
  const value = parseOptionalNumber(field.label, raw, { min: field.min ?? null, max: field.max ?? null });
  if (value !== null && field.positive && value <= 0) throw new Error(`${field.label} must be greater than 0.`);
  return value;
}

function setNested(target, path, value) {
  let node = target;
  for (const key of path.slice(0, -1)) node = node[key] ??= {};
  node[path[path.length - 1]] = value;
}

// `values` maps fieldKey(field) to the raw text of an input; blank inputs are left out of the request.
export function buildModuleRequest(symbol, values = {}) {
  const normalized = String(symbol ?? "").trim().toUpperCase();
  if (!normalized) throw new Error("Select a holding first.");
  if (!PIP_SYMBOL_PATTERN.test(normalized)) {
    throw new Error("This holding's symbol cannot be analyzed: symbols may use letters, digits, '.' and '-' only.");
  }
  const body = { symbol: normalized };
  for (const field of PIP_MODULE_FIELDS) {
    const value = parseFieldValue(field, values?.[fieldKey(field)]);
    if (value !== null) setNested(body, field.path, value);
  }
  return body;
}

// ---- Describing module results ----------------------------------------------------------------

function describeLifecycle(result) {
  const days = finiteNumber(result.days_held);
  const price = finiteNumber(result.price_return_percent);
  const total = finiteNumber(result.total_return_percent);
  const facts = [];
  if (days !== null) facts.push(`held ${pluralize(days, "day")}`);
  if (price !== null) facts.push(`price return ${formatPercent(price)}`);
  if (total !== null) facts.push(`total return ${formatPercent(total)}`);
  const hints = [];
  if (days === null) hints.push(`Add the ${labelOf("position.entry_date")} to measure how long this holding has been held.`);
  if (price === null) hints.push(`Add the ${labelOf("position.market_price")} and the ${labelOf("position.cost_basis")} if the saved lots lack them, to measure the price return.`);
  if (total === null) hints.push(`Add ${labelOf("position.dividends_received")} (enter 0 if none) to measure the total return.`);
  return {
    headline: facts.length ? sentence(`${facts.join("; ")}.`) : "Not enough data to describe this position's lifecycle.",
    rows: [
      ["Days held", days === null ? NOT_AVAILABLE : String(days)],
      ["Price return", formatPercent(price, NOT_AVAILABLE)],
      ["Total return", formatPercent(total, NOT_AVAILABLE)],
    ],
    hints,
  };
}

function describeHurdle(result) {
  const [headline, ...details] = describePipHurdle(result);
  const hints = [];
  if (result.status === "unavailable" && finiteNumber(result.return_percent) === null) {
    hints.push(`Add the ${labelOf("position.market_price")}, the ${labelOf("position.cost_basis")} and the ${labelOf("position.entry_date")} if the saved lots lack them, so the return can be compared with the hurdle.`);
  }
  return { headline, details, hints };
}

function describeDeadMoney(result) {
  const verdict = result.is_dead_money;
  if (typeof verdict !== "boolean" && verdict !== null && verdict !== undefined) return { headline: UNEXPECTED_RESPONSE };
  const headline = verdict === true
    ? "Flagged for review as dead money."
    : verdict === false
      ? "Not flagged as dead money."
      : "Verdict withheld: there is not enough evidence.";
  return {
    headline,
    rows: [["Input confidence", confidenceText(result.confidence)]],
    details: reasonLines(result.reasons),
    hints: typeof verdict === "boolean" ? [] : [`Add position values (${listLabels(POSITION_KEYS)}) and score or outlook inputs to give this check more evidence.`],
  };
}

function describeDividends(result, response) {
  const currency = typeof response.currency === "string" && response.currency ? ` ${response.currency}` : "";
  const income = finiteNumber(result.trailing_twelve_month_income);
  const yieldPercent = finiteNumber(result.current_yield_pct);
  const quality = finiteNumber(result.dividend_quality_score);
  const growth = finiteNumber(result.growth_score);
  const hints = [];
  if (income === null) hints.push("Dividend income and yield need dividend payments saved in PIP within the last 12 months.");
  else if (yieldPercent === null) hints.push(`Add the ${labelOf("position.market_price")} to calculate the yield.`);
  if (quality === null) hints.push(`Add ${listLabels(["dividends.payout_ratio", "dividends.dividend_growth_rate", "dividends.consistency_score"])} to score the dividend quality.`);
  if (growth === null) hints.push(`Add the ${labelOf("dividends.dividend_growth_rate")} to score the dividend growth.`);
  return {
    headline: income === null
      ? "No dividend payments from the last 12 months are saved for this holding."
      : `Trailing 12-month dividend income: ${formatAmount(income)}${currency}.`,
    rows: [
      ["Trailing 12-month income", income === null ? "none saved" : `${formatAmount(income)}${currency}`],
      ["Current yield", numberText(yieldPercent, 2, "%")],
      ["Dividend quality score", numberText(quality, 1, " out of 100")],
      ["Dividend growth score", numberText(growth, 1, " out of 100")],
      ["Input confidence", confidenceText(result.confidence)],
    ],
    details: reasonLines(result.reasons, { dropMissing: true }),
    hints,
  };
}

function describeGrowth(result) {
  const score = finiteNumber(result.score);
  return {
    headline: score === null ? "Growth score not available: no growth data was supplied." : `Growth score: ${score.toFixed(1)} out of 100.`,
    rows: [["Growth score", numberText(score, 1, " out of 100")], ["Input confidence", confidenceText(result.confidence)]],
    details: reasonLines(result.reasons),
    hints: score === null ? [`Add ${listLabels(["growth.earnings_growth_percent", "growth.revenue_growth_percent"])} to calculate a growth score.`] : [],
  };
}

function describeForwardLooking(result) {
  const score = finiteNumber(result.score);
  return {
    headline: score === null
      ? "Forward-looking indicator not available: no outlook data was supplied."
      : `Forward-looking indicator: ${score.toFixed(1)} out of 100.`,
    rows: [["Indicator", numberText(score, 1, " out of 100")], ["Input confidence", confidenceText(result.confidence)]],
    details: reasonLines(result.reasons),
    hints: score === null ? [`Add ${listLabels(["forward.target_upside_percent", "forward.analyst_revisions_score"])} to calculate an indicator.`] : [],
    caveats: [FORWARD_CAVEAT],
  };
}

// The API words each candidate's rationale as "X is stronger than Y by N score points."; N is negative for weaker ones.
function scoreGapText(rationale) {
  const match = /\bby (-?\d+(?:\.\d+)?) score points\.?$/.exec(typeof rationale === "string" ? rationale.trim() : "");
  const gap = match ? Number(match[1]) : Number.NaN;
  if (!Number.isFinite(gap)) return null;
  return `${Math.abs(gap).toFixed(1)} score points ${gap >= 0 ? "above" : "below"} this holding`;
}

function opportunityRow(item, sized) {
  const symbol = typeof item.alternative_symbol === "string" && item.alternative_symbol ? item.alternative_symbol : "Candidate";
  const rationale = typeof item.rationale === "string" ? item.rationale.trim().replace(/\.+$/, "") : "";
  const benefit = finiteNumber(item.expected_benefit);
  const parts = [scoreGapText(item.rationale) ?? rationale].filter(Boolean);
  if (sized && benefit !== null) parts.push(`estimated benefit ${benefit.toFixed(1)} points`);
  return [symbol, parts.length ? `${sentence(parts.join("; "))}.` : NOT_AVAILABLE];
}

function describeOpportunityCost(result) {
  const items = (Array.isArray(result.items) ? result.items : []).filter(isObject);
  const details = reasonLines(result.reasons);
  if (result.available !== true) {
    return {
      headline: "Opportunity cost is not available for this holding.",
      details,
      hints: [`Add at least one capital productivity input (${listLabels(CPS_INPUT_KEYS)}) so this holding has a score to compare with.`],
    };
  }
  if (!items.length) {
    return {
      headline: "No replacement candidates were supplied, so there is nothing to compare.",
      details,
      hints: [`Add ${labelOf("peer_scores")} (for example AAA:82, BBB:90) to compare with this holding.`],
    };
  }
  const sized = !items.every((item) => finiteNumber(item.current_value) === 0);
  const best = items.find((item) => (finiteNumber(item.expected_benefit) ?? 0) > 0);
  if (items.length > MAX_RESULT_ROWS) details.push(`Showing the first ${MAX_RESULT_ROWS} of ${items.length} candidates.`);
  let headline = "None of the supplied candidates is stronger than this holding.";
  if (!sized) headline = "The benefit cannot be sized because this holding has no market value.";
  else if (best) headline = `Best alternative: ${best.alternative_symbol}, an estimated benefit of ${finiteNumber(best.expected_benefit).toFixed(1)} points.`;
  return {
    headline,
    rows: items.slice(0, MAX_RESULT_ROWS).map((item) => opportunityRow(item, sized)),
    details,
    hints: sized ? [] : [`Add the ${labelOf("position.market_price")} so this holding has a market value.`],
    caveats: [OPPORTUNITY_CAVEAT],
  };
}

function describeWeightedScore(result, label) {
  const score = finiteNumber(result.score);
  const weights = isObject(result.weights) ? result.weights : {};
  const components = isObject(result.component_scores) ? result.component_scores : {};
  const rows = Object.entries(weights).map(([name, weight]) => {
    const value = finiteNumber(components[name]);
    const weightValue = finiteNumber(weight);
    const weightText = weightValue === null ? "" : ` (weight ${Number(weightValue.toFixed(2))})`;
    return [componentLabel(name), `${value === null ? "missing" : value.toFixed(1)}${weightText}`];
  });
  rows.push(["Input confidence", confidenceText(result.confidence)]);

  const details = reasonLines(result.reasons, { dropMissing: true });
  const total = Object.values(weights).map((weight) => finiteNumber(weight) ?? 0).reduce((sum, weight) => sum + weight, 0);
  if (total > 0 && Math.abs(total - 100) > 1e-9) {
    details.push(`Weights total ${Number(total.toFixed(2))}; the score is normalized by the weights of the available inputs.`);
  }
  const hints = new Set();
  for (const name of nonEmptyStrings(result.missing_components)) {
    const fields = PIP_COMPONENT_FIELDS.get(name);
    if (fields) hints.add(`Add ${listLabels(fields)} to include ${componentLabel(name).toLowerCase()}.`);
  }
  return {
    headline: score === null ? `${label} not available: no score inputs were available.` : `${label}: ${score.toFixed(1)} out of 100.`,
    rows,
    details,
    hints: [...hints],
  };
}

function describeCps(result) {
  return { ...describeWeightedScore(result, "Capital productivity score"), caveats: earningsGrowthCaveats(result) };
}

function describeSellScore(result) {
  return {
    ...describeWeightedScore(result, "Sell confidence score"),
    caveats: [SELL_DIRECTION_CAVEAT, ...earningsGrowthCaveats(result)],
  };
}

// The API fills a missing earnings growth input from the growth analysis. Say so unless that was earnings growth alone.
function earningsGrowthCaveats(result) {
  const input = isObject(result.earnings_growth_input) ? result.earnings_growth_input : {};
  const basis = input.source === "growth_analysis" ? GROWTH_ANALYSIS_BASES.get(input.basis) : undefined;
  if (!basis) return [];
  return [`The earnings growth input was not supplied, so it was taken from the growth analysis, which used ${basis}.`];
}

function describeReplacements(result) {
  const candidates = (Array.isArray(result.candidates) ? result.candidates : []).filter(isObject);
  const details = reasonLines(result.reasons);
  if (result.compared !== true) {
    return {
      headline: "Candidates could not be compared with this holding.",
      details,
      hints: [`Add ${labelOf("peer_scores")} and at least one capital productivity input (${listLabels(CPS_INPUT_KEYS)}).`],
    };
  }
  if (!candidates.length) {
    return { headline: "No supplied candidate qualifies as a replacement.", details, caveats: [REPLACEMENT_RULE] };
  }
  if (candidates.length >= REPLACEMENT_LIMIT) details.push(`At most ${REPLACEMENT_LIMIT} candidates are listed, strongest first.`);
  if (candidates.length > MAX_RESULT_ROWS) details.push(`Showing the first ${MAX_RESULT_ROWS} of ${candidates.length} candidates.`);
  const rows = candidates.slice(0, MAX_RESULT_ROWS).map((candidate) => {
    const parts = [];
    if (finiteNumber(candidate.score) !== null) parts.push(`score ${candidate.score.toFixed(1)}`);
    if (finiteNumber(candidate.expected_benefit) !== null) {
      parts.push(`${candidate.expected_benefit.toFixed(1)} points above this holding's capital productivity score`);
    }
    return [typeof candidate.symbol === "string" && candidate.symbol ? candidate.symbol : "Candidate", parts.length ? `${sentence(parts.join(", "))}.` : NOT_AVAILABLE];
  });
  return {
    headline: `${pluralize(candidates.length, "candidate")} ${candidates.length === 1 ? "scores" : "score"} above this holding's capital productivity score.`,
    rows,
    details,
    caveats: [REPLACEMENT_RULE],
  };
}

const ADVISOR_LABELS = new Map(Object.entries({ hold: "Hold", watch: "Watch", sell: "Sell", "partial-sell": "Partial sell" }));

function describeSellAdvisor(result) {
  const label = ADVISOR_LABELS.get(result.recommendation);
  if (!label) return { headline: UNEXPECTED_RESPONSE };
  const sellScore = finiteNumber(result.sell_score);
  const confidence = finiteNumber(result.confidence);
  const rows = [
    ["Sell confidence score", numberText(sellScore, 1, " out of 100")],
    ["Capital productivity score", numberText(result.cps, 1, " out of 100")],
    ["Input confidence", confidenceText(confidence)],
  ];
  const candidates = (Array.isArray(result.replacement_candidates) ? result.replacement_candidates : []).filter(isObject);
  for (const candidate of candidates.slice(0, MAX_RESULT_ROWS)) {
    const benefit = finiteNumber(candidate.expected_benefit);
    rows.push([typeof candidate.symbol === "string" && candidate.symbol ? candidate.symbol : "Candidate", benefit === null ? NOT_AVAILABLE : `+${benefit.toFixed(1)} points`]);
  }
  const details = reasonLines(result.rationale);
  if (candidates.length > MAX_RESULT_ROWS) details.push(`Showing the first ${MAX_RESULT_ROWS} of ${candidates.length} candidates.`);
  return {
    headline: `Recommendation: ${label}.`,
    rows,
    details,
    hints: sellScore === null || confidence === null || confidence < 0.5
      ? ["The advisor can only suggest Watch when input confidence is below 50% or no sell score can be calculated. Add more inputs to give it a firmer basis."]
      : [],
    caveats: [SELL_DIRECTION_CAVEAT],
  };
}

const DESCRIBERS = new Map(Object.entries({
  lifecycle: describeLifecycle,
  hurdle: describeHurdle,
  dead_money: describeDeadMoney,
  dividends: describeDividends,
  growth: describeGrowth,
  forward_looking: describeForwardLooking,
  opportunity_cost: describeOpportunityCost,
  cps: describeCps,
  sell_score: describeSellScore,
  replacements: describeReplacements,
  sell_advisor: describeSellAdvisor,
}));

export function describeModuleResult(moduleId, response) {
  const module = PIP_MODULES.find((item) => item.id === moduleId);
  const describe = DESCRIBERS.get(moduleId);
  const valid = Boolean(module && describe && isObject(response) && response.module === moduleId && isObject(response.result));
  const description = valid ? describe(response.result, response) : { headline: UNEXPECTED_RESPONSE };
  const unexpected = !valid || description.headline === UNEXPECTED_RESPONSE;
  let footer = "";
  if (!unexpected) {
    footer = response.saved === false
      ? "Read-only result: nothing was saved and no orders were placed."
      : "The API did not confirm that nothing was saved.";
  }
  return {
    title: module?.label ?? "Module result",
    headline: description.headline,
    unexpected,
    rows: unexpected ? [] : description.rows ?? [],
    details: unexpected ? [] : description.details ?? [],
    hints: unexpected ? [] : description.hints ?? [],
    caveats: unexpected ? [] : description.caveats ?? [],
    footer,
  };
}

// ---- Portfolios and holdings ------------------------------------------------------------------

export function parsePortfolioList(payload) {
  if (!Array.isArray(payload)) throw new Error("The API returned an unexpected portfolio list.");
  return payload
    .filter((item) => isObject(item) && typeof item.id === "string" && item.id)
    .map((item) => ({
      id: item.id,
      name: typeof item.name === "string" && item.name.trim() ? item.name.trim() : "Unnamed portfolio",
      currency: typeof item.currency === "string" ? item.currency : "",
      created: typeof item.created_at === "string" && /^\d{4}-\d{2}-\d{2}/.test(item.created_at) ? item.created_at.slice(0, 10) : "",
    }));
}

export function describePortfolio(portfolio) {
  const detail = [portfolio.currency, portfolio.created ? `created ${portfolio.created}` : ""].filter(Boolean).join(", ");
  return detail ? `${portfolio.name} (${detail})` : portfolio.name;
}

export function parseHoldingsResponse(payload) {
  if (!isObject(payload) || !Array.isArray(payload.holdings)) {
    throw new Error("The API returned an unexpected holdings response.");
  }
  return {
    holdings: payload.holdings.filter((item) => isObject(item) && typeof item.symbol === "string" && item.symbol),
    totals: (Array.isArray(payload.totals) ? payload.totals : []).filter(isObject),
    flags: (Array.isArray(payload.flags) ? payload.flags : []).filter(isObject),
    notes: nonEmptyStrings(payload.notes),
    truncated: payload.truncated === true,
    lots: finiteNumber(payload.lots),
    asOf: formatAsOf(payload.as_of),
  };
}

export const HOLDING_COLUMNS = Object.freeze([
  { key: "symbol", label: "Symbol" },
  { key: "currency", label: "Currency" },
  { key: "quantity", label: "Shares", numeric: true },
  { key: "lot_count", label: "Lots", numeric: true },
  { key: "cost_basis", label: "Cost basis", numeric: true },
  { key: "market_value", label: "Market value", numeric: true },
  { key: "price_return_percent", label: "Price return", numeric: true },
  { key: "entry_date", label: "Held since" },
  { key: "days_held", label: "Days held", numeric: true },
  { key: "flags", label: "Notes" },
]);

const FLAG_LABELS = new Map(Object.entries({
  mixed_currency: "mixed currencies",
  short_position: "short position",
  missing_cost_basis: "no cost basis",
  missing_entry_date: "no entry date",
  missing_market_value: "no market value",
}));

function holdingFlags(holding) {
  return nonEmptyStrings(holding?.flags);
}

export function holdingCells(holding) {
  const flags = holdingFlags(holding);
  const days = finiteNumber(holding.days_held);
  const lots = finiteNumber(holding.lot_count);
  const currency = typeof holding.currency === "string" && holding.currency ? holding.currency : null;
  return [
    holding.symbol,
    currency ?? (flags.includes("mixed_currency") ? "mixed" : "—"),
    formatQuantity(holding.quantity),
    lots === null ? "—" : String(lots),
    formatAmount(holding.cost_basis),
    formatAmount(holding.market_value),
    formatPercent(holding.price_return_percent),
    typeof holding.entry_date === "string" && holding.entry_date ? holding.entry_date : "—",
    days === null ? "—" : String(days),
    flags.map((flag) => FLAG_LABELS.get(flag) ?? flag.replace(/_/g, " ")).join(", "),
  ];
}

export function filterHoldings(holdings, query) {
  const text = String(query ?? "").trim().toUpperCase();
  return text ? holdings.filter((holding) => holding.symbol.toUpperCase().includes(text)) : holdings;
}

// Totals are per currency because PIP never converts currencies.
export function describeHoldingsTotals(totals) {
  return (Array.isArray(totals) ? totals : []).filter(isObject).map((total) => {
    const currency = typeof total.currency === "string" && total.currency ? total.currency : "No currency";
    const count = finiteNumber(total.holdings) ?? 0;
    const priced = finiteNumber(total.priced_holdings) ?? 0;
    const costed = finiteNumber(total.costed_holdings) ?? 0;
    const value = priced > 0 && finiteNumber(total.market_value) !== null
      ? `${formatAmount(total.market_value)} (${priced} of ${count} priced)`
      : "not available (none priced)";
    const cost = costed > 0 && finiteNumber(total.cost_basis) !== null
      ? `${formatAmount(total.cost_basis)} (${costed} of ${count} with a cost basis)`
      : "not available (no cost basis)";
    return `${currency}: ${pluralize(count, "holding")}; market value ${value}; cost basis ${cost}.`;
  });
}

export function describeHoldingsFlags(flags) {
  return (Array.isArray(flags) ? flags : []).filter(isObject).map((item) => {
    const message = typeof item.message === "string" && item.message ? item.message : humanize(String(item.flag ?? "note"));
    const count = finiteNumber(item.count);
    return count === null ? message : `${pluralize(count, "holding")}: ${message}`;
  });
}

export function describeHoldingsSummary(overview) {
  if (!overview.holdings.length) return "This portfolio has no saved holdings.";
  const lots = overview.lots === null ? "" : ` from ${pluralize(overview.lots, "lot")}`;
  return `${pluralize(overview.holdings.length, "holding")}${lots}${overview.asOf ? `, as of ${overview.asOf}` : ""}.`;
}

export function describeHolding(holding) {
  const currency = typeof holding.currency === "string" && holding.currency ? ` ${holding.currency}` : "";
  const parts = [`${formatQuantity(holding.quantity)} shares`];
  if (finiteNumber(holding.cost_basis) !== null) parts.push(`cost basis ${formatAmount(holding.cost_basis)}${currency}`);
  if (finiteNumber(holding.market_value) !== null) parts.push(`market value ${formatAmount(holding.market_value)}${currency}`);
  if (finiteNumber(holding.price_return_percent) !== null) parts.push(`price return ${formatPercent(holding.price_return_percent)}`);
  if (finiteNumber(holding.days_held) !== null) parts.push(`held ${pluralize(holding.days_held, "day")}`);
  return `${parts.join("; ")}.`;
}

export function holdingInputHints(holding) {
  const flags = new Set(holdingFlags(holding));
  const hints = [];
  if (flags.has("mixed_currency")) {
    hints.push("This holding has lots in more than one currency, or without a currency. PIP does not convert currencies, so the modules cannot run until the lots share one currency.");
  }
  if (flags.has("short_position")) hints.push("This is a short position (negative quantity). Read the results with care.");
  if (flags.has("missing_market_value")) hints.push(`No market value is saved. Enter the ${labelOf("position.market_price")} to give this holding one.`);
  if (flags.has("missing_cost_basis")) hints.push(`No cost basis is saved. Enter the ${labelOf("position.cost_basis")} to measure returns.`);
  if (flags.has("missing_entry_date")) hints.push(`No entry date is saved. Enter the ${labelOf("position.entry_date")} to measure how long it has been held.`);
  return hints;
}
