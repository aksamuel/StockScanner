// Pure helpers shared by the PIP workbench and the PIP module runner.
// This file must stay free of DOM access so both pages and the Node tests can import it.

export const PIP_DEFAULT_API_URL = "https://stockscanner-pip-api.onrender.com";

const LOCAL_API_HOSTS = new Set(["localhost", "127.0.0.1"]);
const DEFAULT_API_ORIGIN = new URL(PIP_DEFAULT_API_URL).origin;
export const PIP_SYMBOL_PATTERN = /^[A-Z0-9][A-Z0-9.-]{0,29}$/;
const VALIDATION_PREFIX = /^(?:Value|Assertion) error,\s*/i;
const LOCATION_ROOTS = new Set(["body", "query", "path", "header", "cookie"]);
const MAX_VALIDATION_MESSAGES = 3;
const MAX_VALIDATION_MESSAGE_LENGTH = 200;

export function normalizePipApiUrl(value) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) return { ok: false, error: "Enter the PIP API URL." };
  let url;
  try {
    url = new URL(text);
  } catch {
    return { ok: false, error: "Enter a full PIP API URL that starts with https://." };
  }
  const isLocal = LOCAL_API_HOSTS.has(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLocal)) {
    return { ok: false, error: "Use HTTPS for the PIP API URL." };
  }
  if (url.username || url.password || url.search || url.hash) {
    return { ok: false, error: "The PIP API URL must not contain credentials, a query string or a fragment." };
  }
  return {
    ok: true,
    url: `${url.origin}${url.pathname}`.replace(/\/+$/, ""),
    origin: url.origin,
    isLocal,
    isDefault: url.origin === DEFAULT_API_ORIGIN,
  };
}

function validationMessage(item) {
  if (!item || typeof item !== "object" || typeof item.msg !== "string" || !item.msg.trim()) return null;
  const message = item.msg.trim().replace(VALIDATION_PREFIX, "").replace(/[.\s]+$/, "")
    .slice(0, MAX_VALIDATION_MESSAGE_LENGTH);
  if (!message) return null;
  const parts = (Array.isArray(item.loc) ? item.loc : [])
    .filter((part) => typeof part === "string" || Number.isInteger(part));
  if (LOCATION_ROOTS.has(parts[0])) parts.shift();
  const field = parts.reduce((text, part) => {
    if (typeof part === "number") return `${text}[${part}]`;
    return text ? `${text}.${part}` : part;
  }, "");
  return field ? `${field}: ${message}` : message;
}

// Never echo `input` or `ctx` from a validation error: only the field and the rule.
export function pipApiErrorMessage(payload, status) {
  const detail = payload && typeof payload === "object" ? payload.detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(validationMessage).filter(Boolean);
    if (messages.length) {
      const shown = messages.slice(0, MAX_VALIDATION_MESSAGES).join("; ");
      const hidden = messages.length - MAX_VALIDATION_MESSAGES;
      return `The API rejected these values: ${shown}${hidden > 0 ? `; and ${hidden} more` : ""}.`;
    }
  }
  return status ? `PIP API request failed (${status}).` : "PIP API request failed.";
}

export function parseOptionalNumber(label, value, { min = null, max = null } = {}) {
  const text = String(value ?? "").trim();
  if (text === "") return null;
  const number = Number(text);
  if (!Number.isFinite(number)) throw new Error(`${label} must be a number.`);
  if (min !== null && number < min) throw new Error(`${label} must be at least ${min}.`);
  if (max !== null && number > max) throw new Error(`${label} must be no more than ${max}.`);
  return number;
}

export function parsePipCandidates(text, { unique = false, max = null } = {}) {
  const entries = String(text ?? "")
    .split(/[,\n]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
  const scores = entries.map((entry) => {
    const [symbolValue, scoreValue, ...extra] = entry.split(":");
    const symbol = symbolValue.trim().toUpperCase();
    const score = Number(scoreValue);
    if (extra.length || !PIP_SYMBOL_PATTERN.test(symbol)
      || !scoreValue?.trim() || !Number.isFinite(score) || score < 0 || score > 100) {
      throw new Error(`Invalid replacement candidate: ${entry}. Use SYMBOL:score from 0 to 100.`);
    }
    return { symbol, score };
  });
  if (max !== null && scores.length > max) throw new Error(`Enter at most ${max} replacement candidates.`);
  if (unique && new Set(scores.map((candidate) => candidate.symbol)).size !== scores.length) {
    throw new Error("Each replacement candidate symbol may appear only once.");
  }
  return scores;
}

const HURDLE_VERDICTS = Object.freeze({
  below: "below the hurdle path",
  meets: "on or ahead of the hurdle path",
  unavailable: "cannot be judged yet",
});

export function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function trimmedPercent(value) {
  return `${Number(value.toFixed(2))}%`;
}

export function nonEmptyStrings(values) {
  return (Array.isArray(values) ? values : []).filter((value) => typeof value === "string" && value.trim());
}

export function pluralize(count, singular) {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

export function describePipHurdle(hurdle) {
  if (!hurdle || typeof hurdle !== "object") {
    return ["Return hurdle: unavailable from this API version."];
  }
  const required = finiteNumber(hurdle.required_annual_return_percent);
  const rate = required === null ? "required annual return" : `${trimmedPercent(required)} per year`;
  const lines = [`Return hurdle (${rate}): ${HURDLE_VERDICTS[hurdle.status] || HURDLE_VERDICTS.unavailable}.`];

  const returnPercent = finiteNumber(hurdle.return_percent);
  const pathPercent = finiteNumber(hurdle.hurdle_return_percent);
  if (returnPercent !== null && pathPercent !== null) {
    const days = finiteNumber(hurdle.days_held);
    const lots = finiteNumber(hurdle.lot_count);
    const basis = hurdle.return_basis === "total"
      ? "Total return (price plus dividends received)"
      : "Price-only return";
    const period = days === null
      ? ""
      : ` after ${days} days${lots !== null && lots > 1 ? ` (cost-weighted across ${lots} lots)` : ""}`;
    lines.push(`${basis} is ${returnPercent.toFixed(1)}% against ${pathPercent.toFixed(1)}% needed to match the hurdle path${period}.`);
  }
  const annualized = finiteNumber(hurdle.annualized_return_percent);
  if (annualized !== null) lines.push(`Annualized return: ${annualized.toFixed(1)}% per year.`);
  const shortfall = finiteNumber(hurdle.shortfall_amount);
  if (shortfall !== null && shortfall > 0) lines.push(`Shortfall against the hurdle path: ${shortfall.toFixed(2)}.`);

  const needed = (Array.isArray(hurdle.required_return_by_horizon) ? hurdle.required_return_by_horizon : [])
    .map((item) => [finiteNumber(item?.years), finiteNumber(item?.required_annual_return_percent)])
    .filter(([years, percent]) => years !== null && percent !== null)
    .map(([years, percent]) => `${percent.toFixed(1)}% per year for ${years} year${years === 1 ? "" : "s"}`);
  if (needed.length) lines.push(`Return needed to reach the hurdle path: ${needed.join(", ")}.`);

  const forward = finiteNumber(hurdle.forward_return_percent);
  if (forward !== null && (hurdle.outlook_status === "below" || hurdle.outlook_status === "meets")) {
    lines.push(`Analyst target upside of ${forward.toFixed(1)}% ${hurdle.outlook_status === "below" ? "is below" : "meets or exceeds"} the hurdle.`);
  }

  const scenarios = [];
  const holdingAssumed = finiteNumber(hurdle.holding_assumed_return_percent);
  const yearsToCatchUp = finiteNumber(hurdle.years_to_catch_up);
  if (holdingAssumed !== null && yearsToCatchUp !== null) {
    scenarios.push(yearsToCatchUp === 0
      ? `Scenario: at an assumed ${trimmedPercent(holdingAssumed)} per year this holding is already on or ahead of the hurdle path.`
      : `Scenario: at an assumed ${trimmedPercent(holdingAssumed)} per year this holding would catch up with the hurdle path in about ${yearsToCatchUp.toFixed(1)} years.`);
  }
  const replacementAssumed = finiteNumber(hurdle.replacement_assumed_return_percent);
  const replacementMonths = finiteNumber(hurdle.replacement_months_to_hurdle_gain);
  if (replacementAssumed !== null && replacementMonths !== null && required !== null) {
    scenarios.push(`Scenario: a replacement assumed to earn ${trimmedPercent(replacementAssumed)} per year would take about ${replacementMonths.toFixed(1)} months to gain ${trimmedPercent(required)}.`);
  }
  lines.push(...scenarios);
  if (scenarios.length) {
    lines.push(typeof hurdle.note === "string" && hurdle.note
      ? hurdle.note
      : "Scenario figures are arithmetic from the assumed returns, not forecasts.");
  }

  const reasons = (Array.isArray(hurdle.reasons) ? hurdle.reasons : [])
    .filter((reason) => typeof reason === "string" && reason);
  if (reasons.length) lines.push(`Notes: ${reasons.join(" ")}`);
  return lines;
}
