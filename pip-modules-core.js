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
// Mirrors SELL_SCORE_DIRECTION in stockscanner/pip/scoring.py; a Python test compares them.
export const SELL_SCORE_DIRECTION = "higher_means_sell";

const MAX_RESULT_ROWS = 10;
const NOT_AVAILABLE = "not available";
const UNEXPECTED_RESPONSE = "The API returned an unexpected response, so no result is shown.";
// Shown when a result lacks the direction tag, for example from an API that predates the flipped sell score.
const LEGACY_DIRECTION_CAVEAT = "This result does not say which way the sell score runs, so it may use the earlier direction, where healthier holdings scored higher. Treat it as unverified.";
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
  const description = describeWeightedScore(result, "Sell confidence score");
  const note = flippedInputsNote(result);
  if (note) description.details.push(note);
  return { ...description, caveats: [...directionCaveats(result), ...earningsGrowthCaveats(result)] };
}

function hasKnownDirection(result) {
  return result.sell_score_direction === SELL_SCORE_DIRECTION;
}

function directionCaveats(result) {
  return hasKnownDirection(result) ? [] : [LEGACY_DIRECTION_CAVEAT];
}

function joinLabels(labels) {
  return labels.length > 1 ? `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}` : labels[0];
}

// The sell score counts healthier-is-higher inputs as 100 minus their score, so the values shown are not the ones entered.
function flippedInputsNote(result) {
  if (!hasKnownDirection(result)) return null;
  const components = isObject(result.component_scores) ? result.component_scores : {};
  const names = [...new Set(nonEmptyStrings(result.inverted_components))].filter((name) => finiteNumber(components[name]) !== null);
  if (!names.length) return null;
  const [verb, effect] = names.length === 1
    ? ["rises", "it counts as 100 minus its score"]
    : ["rise", "they count as 100 minus their score"];
  return `Each value shows how strongly that input argues for selling. ${joinLabels(names.map(componentLabel))} ${verb} as a holding gets healthier, so ${effect}. A higher score is a stronger case to sell.`;
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
    caveats: directionCaveats(result),
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

// ---- Filling inputs from research -------------------------------------------------------------

const RESEARCH_UNEXPECTED = "The API returned an unexpected research response, so nothing was filled.";
const RESEARCH_NO_SCORES = "This PIP API version does not return research scores.";
const RESEARCH_NO_VALUE = "Yahoo did not provide this value.";
const RESEARCH_NOT_A_NUMBER = "Yahoo returned a value that is not a usable number.";
const RESEARCH_GENERAL_TAIL = "from Yahoo research";
const RESEARCH_PROVENANCE_NOTE = "A module uses only the inputs it needs. Values you edited after loading are your own and are not listed.";

// One input per line: a Python test parses this table and resolves every path against a real research answer.
// `from` is the path of the value, `why` the path of the reason the API gives when that value is missing, and
// `evidence` the paths of the numbers it was built from, which are read by the last name in each path.
export const PIP_RESEARCH_INPUTS = Object.freeze([
  { key: "position.market_price", name: "Share price", from: "price.price", evidence: ["price.source", "price.as_of", "price.stale"] },
  { key: "scores.tsr", name: "Total shareholder return score", from: "scores.tsr.score", why: "scores.tsr.reason", evidence: ["scores.tsr.raw.return_percent", "scores.tsr.raw.history_days", "returns.basis"] },
  { key: "scores.relative_performance", name: "Relative performance score", from: "scores.relative_performance.score", why: "scores.relative_performance.reason", evidence: ["scores.relative_performance.raw.gap_points", "scores.relative_performance.raw.history_days"] },
  { key: "scores.technical_health", name: "Technical health score", from: "scores.technical_health.score", why: "scores.technical_health.reason", evidence: ["scores.technical_health.raw.long_average_days", "scores.technical_health.raw.close_vs_long_average_percent", "scores.technical_health.raw.short_average_days", "scores.technical_health.raw.close_vs_short_average_percent", "scores.technical_health.raw.high_window_days", "scores.technical_health.raw.below_high_percent"] },
  { key: "growth.earnings_growth_percent", name: "Earnings growth", from: "growth.earnings_growth_percent", why: "unavailable_metrics.earnings_growth_percent", evidence: ["growth.source"] },
  { key: "growth.revenue_growth_percent", name: "Revenue growth", from: "growth.revenue_growth_percent", why: "unavailable_metrics.revenue_growth_percent", evidence: ["growth.source"] },
  { key: "forward.target_upside_percent", name: "Target upside", from: "analyst.target_upside_percent", evidence: ["analyst.target_price", "analyst.rating"] },
  { key: "forward.analyst_revisions_score", name: "Forward revisions score", from: "scores.revisions.score", why: "scores.revisions.reason", evidence: ["scores.revisions.raw.up", "scores.revisions.raw.down", "scores.revisions.raw.breadth", "scores.revisions.raw.periods_counted"] },
]);

function plainText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

// The text put in an input: four decimals at most, no trailing zeros, and never "-0".
function plainNumber(value) {
  return String(Number(value.toFixed(4)));
}

function signedNumber(value, digits) {
  const text = value.toFixed(digits);
  if (Number(text) === 0) return (0).toFixed(digits);
  return value > 0 ? `+${text}` : text;
}

function endSentence(text) {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function calendarDate(text) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
  const date = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === text ? text : null;
}

// The calendar date a research timestamp or date starts with, or null when it does not start with one.
function leadingDate(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return /^\d{4}-\d{2}-\d{2}(?:$|[T ])/.test(text) ? calendarDate(text.slice(0, 10)) : null;
}

function priceMoment(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return calendarDate(text) ?? (/^\d{4}-\d{2}-\d{2}T/.test(text) ? formatAsOf(text) : null);
}

function valueAt(payload, path) {
  let node = payload;
  for (const name of path.split(".")) {
    if (!isObject(node)) return undefined;
    node = node[name];
  }
  return node;
}

function evidenceOf(payload, entry) {
  return Object.fromEntries(entry.evidence.map((path) => [path.slice(path.lastIndexOf(".") + 1), valueAt(payload, path)]));
}

function numbersOf(evidence, ...names) {
  const values = names.map((name) => finiteNumber(evidence[name]));
  return values.includes(null) ? null : values;
}

function levelText(percent, name) {
  const text = Math.abs(percent).toFixed(1);
  if (Number(text) === 0) return `at its ${name}`;
  return `${text}% ${percent > 0 ? "above" : "below"} its ${name}`;
}

function explainGrowth(evidence) {
  const source = plainText(evidence.source);
  return source ? `reported by ${source}` : "source not stated";
}

// Each returns the numbers behind an input in words, or null when the evidence is incomplete.
const RESEARCH_EXPLAINERS = new Map(Object.entries({
  "position.market_price": (evidence) => {
    const date = priceMoment(evidence.as_of);
    return `${plainText(evidence.source) ?? "source unavailable"}${date ? `, as of ${date}` : ""}${evidence.stale === true ? ", marked stale" : ""}`;
  },
  "scores.tsr": (evidence) => {
    const numbers = numbersOf(evidence, "return_percent", "history_days");
    if (!numbers) return null;
    const basis = evidence.basis === "adjusted_close" ? "adjusted closes" : "daily closes";
    return `${formatPercent(numbers[0])} return on ${basis} over ${pluralize(numbers[1], "day")}`;
  },
  "scores.relative_performance": (evidence) => {
    const numbers = numbersOf(evidence, "gap_points", "history_days");
    return numbers && `${signedNumber(numbers[0], 1)} points against SPY over ${pluralize(numbers[1], "shared day")}`;
  },
  "scores.technical_health": (evidence) => {
    const numbers = numbersOf(evidence, "long_average_days", "close_vs_long_average_percent", "short_average_days", "close_vs_short_average_percent", "high_window_days", "below_high_percent");
    if (!numbers) return null;
    const [longDays, vsLong, shortDays, vsShort, highDays, belowHigh] = numbers;
    return `last close is ${levelText(vsLong, `${longDays}-day average`)}, ${levelText(vsShort, `${shortDays}-day average`)} and ${levelText(-belowHigh, `${highDays}-day high`)}`;
  },
  "growth.earnings_growth_percent": explainGrowth,
  "growth.revenue_growth_percent": explainGrowth,
  "forward.target_upside_percent": (evidence) => {
    const rating = plainText(evidence.rating);
    const price = finiteNumber(evidence.target_price);
    const parts = [];
    if (rating) parts.push(`rating ${rating}`);
    if (price !== null) parts.push(`target price ${plainNumber(price)}`);
    return `analyst ${parts.length ? parts.join(", ") : "data"}`;
  },
  "forward.analyst_revisions_score": (evidence) => {
    const numbers = numbersOf(evidence, "up", "down", "breadth");
    if (!numbers || !Array.isArray(evidence.periods_counted)) return null;
    const [up, down, breadth] = numbers;
    return `${up} upward and ${down} downward EPS estimate revisions in the last 30 days across ${pluralize(evidence.periods_counted.length, "period")} (breadth ${signedNumber(breadth, 2)})`;
  },
}));

function researchLine(entry, payload, text) {
  const unit = labelOf(entry.key).endsWith("(%)") ? "%" : "";
  const tail = RESEARCH_EXPLAINERS.get(entry.key)?.(evidenceOf(payload, entry)) || RESEARCH_GENERAL_TAIL;
  return `${entry.name} ${text}${unit} — ${endSentence(tail)}`;
}

function researchSkipReason(entry, payload, raw, hasScores) {
  if (entry.from.startsWith("scores.") && !hasScores) return RESEARCH_NO_SCORES;
  if (raw !== null && raw !== undefined) return RESEARCH_NOT_A_NUMBER;
  return plainText(entry.why && valueAt(payload, entry.why)) ?? RESEARCH_NO_VALUE;
}

function symbolText(symbol) {
  return String(symbol ?? "").trim().toUpperCase();
}

// Reads the research answer for `symbol` into the inputs it can fill, as the text to put in each box.
// Anything missing, not a number or outside a field's range is listed in `skipped` with the reason, never filled.
export function parseResearchResponse(payload, symbol) {
  if (!isObject(payload) || typeof payload.symbol !== "string") throw new Error(RESEARCH_UNEXPECTED);
  const wanted = symbolText(symbol);
  if (!wanted || symbolText(payload.symbol) !== wanted) {
    throw new Error(`The API returned research for a different symbol than ${wanted}, so nothing was filled.`);
  }
  const scores = isObject(payload.scores) ? payload.scores : null;
  const inputs = [];
  const skipped = [];
  for (const entry of PIP_RESEARCH_INPUTS) {
    const raw = valueAt(payload, entry.from);
    const value = finiteNumber(raw);
    const skip = (reason) => skipped.push({ key: entry.key, name: entry.name, reason });
    if (value === null) {
      skip(researchSkipReason(entry, payload, raw, scores !== null));
      continue;
    }
    const text = plainNumber(value);
    try {
      parseFieldValue(FIELD_BY_KEY.get(entry.key), text);
    } catch (error) {
      skip(`${String(error.message).replace(/\.$/, "")} (Yahoo returned ${text}).`);
      continue;
    }
    inputs.push({ key: entry.key, name: entry.name, text, line: researchLine(entry, payload, text) });
  }
  return {
    asOf: leadingDate(valueAt(payload, "returns.end_date")) ?? leadingDate(payload.fetched_at),
    version: plainText(scores?.version),
    hasScores: scores !== null,
    inputs,
    skipped,
    warnings: nonEmptyStrings(payload.warnings).map((text) => text.trim()),
  };
}

// The inputs whose boxes still hold exactly the text research put there; edited or cleared boxes are the user's own.
export function unchangedResearchInputs(inputs, values) {
  return inputs.filter((input) => String(values?.[input.key] ?? "").trim() === input.text);
}

export function describeResearchLoad(research, symbol) {
  const name = symbolText(symbol);
  const filled = research.inputs.length;
  const notes = [
    ...research.inputs.map((input) => input.line),
    ...research.skipped.map((item) => `${item.name} was not filled: ${endSentence(item.reason)}`),
    ...research.warnings,
  ];
  if (!filled) return { headline: `Yahoo research did not give any usable values for ${name}.`, filled, notes };
  const date = research.asOf ? ` (data as of ${research.asOf})` : "";
  return {
    headline: `Filled ${filled} of ${PIP_RESEARCH_INPUTS.length} inputs for ${name} from Yahoo research${date}. Every value stays editable; nothing was saved.`,
    filled,
    notes,
  };
}

// `research` needs only asOf and version. Returns null when no loaded input is still unchanged.
export function describeResearchProvenance(research, unchanged) {
  if (!unchanged.length) return null;
  const parts = [research.asOf ? `data as of ${research.asOf}` : "", research.version ? `score rules ${research.version}` : ""].filter(Boolean);
  return {
    heading: `Inputs from Yahoo research${parts.length ? ` (${parts.join("; ")})` : ""}`,
    lines: unchanged.map((input) => input.line),
    note: RESEARCH_PROVENANCE_NOTE,
  };
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
