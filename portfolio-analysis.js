import { parseDateInput } from "./date-format.js";

export const DEFAULT_PROFIT_REVIEW_PERCENT = 7;
export const DEFAULT_LOSS_REVIEW_PERCENT = -10;

export function isPriceStale(value, now = Date.now(), maxAgeMinutes = 75) {
  const timestamp = Date.parse(value || "");
  const current = now instanceof Date ? now.getTime() : Number(now);
  return Number.isFinite(timestamp) && Number.isFinite(current)
    && current - timestamp > maxAgeMinutes * 60 * 1000;
}

export function technicalStrength(score) {
  if (score === null || score === undefined || score === '' || !Number.isFinite(Number(score))) {
    return { label: 'Unavailable', tone: 'unavailable', score: null };
  }
  const value = Number(score);
  if (value < 0 || value > 100) return { label: 'Unavailable', tone: 'unavailable', score: null };
  return { label: value < 40 ? 'Weak' : value <= 70 ? 'Moderate' : 'Strong',
    tone: value < 40 ? 'weak' : value <= 70 ? 'moderate' : 'strong', score: value };
}

export function filterPortfolioHoldings(holdings, filter = "all") {
  return (holdings || []).filter((holding) => {
    if (filter === "profitable") return holding.returnPercent > 0;
    if (filter === "sell") return holding.decision?.code === "sell";
    if (filter === "partial-sell") return holding.decision?.code === "partial-sell";
    if (filter === "hold") return holding.decision?.code === "hold";
    return true;
  });
}

export function parseCsv(source) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  const text = String(source || "").replace(/^\uFEFF/, "");
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted && character === '"' && text[index + 1] === '"') {
      field += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (quoted) throw new Error("The CSV contains an unclosed quoted value.");
  if (field || row.length) {
    row.push(field);
    if (row.some((value) => value.trim())) rows.push(row);
  }
  return rows;
}

function numberValue(value, label, rowNumber, { required = false, nonzero = false } = {}) {
  const text = String(value || "").replace(/[,$%]/g, "").trim();
  if (!text) {
    if (!required) return null;
    throw new Error(`Row ${rowNumber}: ${label} is required.`);
  }
  const parsed = Number(text);
  if (!Number.isFinite(parsed) || (nonzero && parsed === 0)) {
    throw new Error(`Row ${rowNumber}: ${label} must be ${nonzero ? "a non-zero" : "a valid"} number.`);
  }
  return parsed;
}

function dateValue(value, rowNumber) {
  const text = String(value || "").trim();
  if (!text) return null;
  const displayDate = parseDateInput(text);
  if (displayDate) return displayDate;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T\s,].*)?$/.exec(text)
    || /^(\d{4})(\d{2})(\d{2})(?:[T\s,].*)?$/.exec(text);
  if (match) {
    const [, year, month, day] = match;
    const iso = `${year}-${month}-${day}`;
    const parsed = new Date(`${iso}T00:00:00Z`);
    if (!Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso) return iso;
  }
  throw new Error(`Row ${rowNumber}: buy_date must use dd/mmm/yyyy, YYYY-MM-DD, or an IBKR YYYYMMDD date.`);
}

export function portfolioRowsFromCsv(source, missingCurrency = "") {
  const rows = parseCsv(source);
  if (rows.length < 2) throw new Error("The CSV must contain a header and at least one holding.");
  if (rows.length > 1001) throw new Error("A CSV import is limited to 1000 holdings.");
  const normalizeHeader = (value) => value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  const headers = rows[0].map(normalizeHeader);
  const columnAliases = {
    symbol: ["symbol"],
    quantity: ["quantity"],
    buy_price: ["buyprice", "costbasisprice", "costbasis"],
    buy_date: ["buydate", "opendatetime", "tradedate"],
  };
  const columnIndexes = Object.fromEntries(Object.entries(columnAliases).map(([name, aliases]) => [
    name,
    aliases.map((alias) => headers.indexOf(alias)).find((index) => index >= 0) ?? -1,
  ]));
  for (const required of ["symbol", "quantity", "buy_price"]) {
    if (columnIndexes[required] < 0) throw new Error(`Missing required CSV column: ${required}`);
  }
  const get = (row, name) => {
    const index = columnIndexes[name] ?? headers.indexOf(normalizeHeader(name));
    return index >= 0 ? row[index] || "" : "";
  };
  return rows.slice(1).map((row, index) => {
    const rowNumber = index + 2;
    const symbol = get(row, "symbol").trim().toUpperCase().replace(/\s+/g, "-");
    if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) {
      throw new Error(`Row ${rowNumber}: invalid ticker symbol.`);
    }
    const boughtOn = dateValue(get(row, "buy_date"), rowNumber);
    const currency = String(get(row, "currency") || missingCurrency).trim().toUpperCase();
    if (!currency) throw new Error(`Row ${rowNumber}: currency is missing; provide a currency column or select a currency for missing rows.`);
    if (!/^[A-Z]{3}$/.test(currency)) throw new Error(`Row ${rowNumber}: invalid currency code.`);
    const notes = get(row, "notes").trim();
    if (notes.length > 500) throw new Error(`Row ${rowNumber}: notes exceed 500 characters.`);
    return {
      position_key: `${symbol}:${boughtOn || "SUMMARY"}:${index + 1}`,
      symbol,
      description: null,
      asset_class: "STK",
      currency,
      quantity: numberValue(get(row, "quantity"), "quantity", rowNumber, { required: true, nonzero: true }),
      buy_price: numberValue(get(row, "buy_price"), "buy_price", rowNumber, { required: true }),
      bought_on: boughtOn,
      current_price: null,
      current_price_at: null,
      market_value: null,
      unrealized_pnl: null,
      target_price: numberValue(get(row, "target_price"), "target_price", rowNumber),
      stop_loss: numberValue(get(row, "stop_loss"), "stop_loss", rowNumber),
      notes: notes || null,
    };
  });
}

export function portfolioImportPreviewFromCsv(source, missingCurrency = "") {
  const rows = parseCsv(source);
  if (rows.length < 2) throw new Error("The CSV must contain a header and at least one record.");
  if (rows.length > 1001) throw new Error("A CSV import is limited to 1000 rows.");
  const normalizeHeader = (value) => value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  const headers = rows[0].map(normalizeHeader);
  const column = (...aliases) => aliases.map((alias) => headers.indexOf(alias)).find((index) => index >= 0) ?? -1;
  const columns = {
    symbol: column("symbol", "ticker"),
    quantity: column("quantity", "position"),
    buyPrice: column("buyprice", "costbasisprice", "costbasis", "averagecost"),
    buyDate: column("buydate", "opendatetime", "tradedate", "entrydate"),
    currency: column("currency"),
    transactionDate: column("tradedate", "date"),
    transactionType: column("transactiontype", "type"),
    dividendAmount: column("dividendamount", "amount"),
    exDate: column("exdate"),
    payDate: column("paydate"),
  };
  const get = (row, index) => index >= 0 ? String(row[index] || "").trim() : "";
  const records = { positions: [], transactions: 0, dividends: 0 };
  for (const [index, row] of rows.slice(1).entries()) {
    const rowNumber = index + 2;
    const symbolValue = get(row, columns.symbol);
    const quantity = get(row, columns.quantity);
    const transactionDate = get(row, columns.transactionDate);
    const transactionType = get(row, columns.transactionType);
    const dividendAmount = get(row, columns.dividendAmount);
    const exDate = get(row, columns.exDate);
    const payDate = get(row, columns.payDate);
    const isPosition = Boolean(symbolValue && quantity);
    const isTransaction = Boolean(symbolValue && transactionDate && transactionType);
    const isDividend = Boolean(symbolValue && dividendAmount && (exDate || payDate));
    const currency = (get(row, columns.currency) || String(missingCurrency || "")).toUpperCase();
    if (!/^[A-Z]{3}$/.test(currency)) {
      throw new Error(`Row ${rowNumber}: currency is missing or invalid.`);
    }
    if (!isPosition && !isTransaction && !isDividend) continue;

    const symbol = symbolValue.toUpperCase().replace(/\s+/g, "-");
    if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) {
      throw new Error(`Row ${rowNumber}: invalid ticker symbol.`);
    }
    if (isPosition) {
      const normalizedQuantity = numberValue(quantity, "quantity", rowNumber, { required: true, nonzero: true });
      const buyDate = dateValue(get(row, columns.buyDate), rowNumber);
      records.positions.push({
        symbol,
        quantity: normalizedQuantity,
        buy_price: numberValue(get(row, columns.buyPrice), "buy_price", rowNumber),
        bought_on: buyDate,
        currency,
      });
    }
    if (isTransaction) {
      dateValue(transactionDate, rowNumber);
      records.transactions += 1;
    }
    if (isDividend) {
      numberValue(dividendAmount, "dividend amount", rowNumber, { required: true });
      dateValue(payDate || exDate, rowNumber);
      records.dividends += 1;
    }
  }
  if (!records.positions.length && !records.transactions && !records.dividends) {
    throw new Error("The CSV contains no supported position, transaction, or dividend records.");
  }
  return records;
}

export function portfolioCsvRecordTypes(source) {
  const rows = parseCsv(source);
  if (rows.length < 2) throw new Error("The CSV must contain a header and at least one supported record.");
  if (rows.length > 1001) throw new Error("A CSV import is limited to 1000 records.");

  const normalizeHeader = (value) => value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  const headers = rows[0].map(normalizeHeader);
  const column = (...aliases) => aliases
    .map((alias) => headers.indexOf(normalizeHeader(alias)))
    .find((index) => index >= 0) ?? -1;
  const symbol = column("symbol", "ticker");
  const quantity = column("quantity", "position");
  const tradeDate = column("tradeDate", "date");
  const transactionType = column("transactionType", "type");
  const dividendAmount = column("dividendAmount", "amount");
  const dividendDate = column("exDate", "payDate");
  const hasValue = (row, index) => index >= 0 && Boolean(row[index]?.trim());
  const recordTypes = new Set();

  for (const row of rows.slice(1)) {
    if (!hasValue(row, symbol)) continue;
    if (hasValue(row, quantity)) recordTypes.add("positions");
    if (hasValue(row, tradeDate) && hasValue(row, transactionType)) recordTypes.add("transactions");
    if (hasValue(row, dividendAmount) && hasValue(row, dividendDate)) recordTypes.add("dividends");
  }

  if (!recordTypes.size) {
    throw new Error("The CSV must contain supported position, transaction, or dividend records.");
  }
  return ["positions", "transactions", "dividends"].filter((type) => recordTypes.has(type));
}

export function detectedPortfolioBroker(source) {
  const [header = []] = parseCsv(source);
  const headers = header.map((value) => value.trim().toLowerCase().replace(/[^a-z0-9]/g, ""));
  return ["symbol", "quantity", "costbasisprice", "opendatetime"]
    .every((column) => headers.includes(column)) ? "IBKR" : null;
}

export function holdingReturnPercent(holding, currentPrice) {
  const buyPrice = Number(holding.buy_price);
  const quantity = Number(holding.quantity);
  if (!Number.isFinite(currentPrice) || currentPrice < 0 || !Number.isFinite(buyPrice) || buyPrice <= 0) {
    return null;
  }
  return (quantity < 0 ? buyPrice - currentPrice : currentPrice - buyPrice) / buyPrice * 100;
}

function profitReviewThreshold(value) {
  const threshold = Number(value);
  return Number.isFinite(threshold) && threshold >= 0 && threshold <= 100
    ? threshold
    : DEFAULT_PROFIT_REVIEW_PERCENT;
}

export function recommendedTargetPrice(holding, context = {}) {
  const optionalNumber = (value) => value === null || value === undefined || value === ""
    ? Number.NaN
    : Number(value);
  const manualTarget = optionalNumber(holding.target_price);
  if (Number.isFinite(manualTarget) && manualTarget > 0) {
    return {
      price: manualTarget,
      type: "manual",
      source: "Manual target",
      candidates: [{ price: manualTarget, source: "Manual target" }],
    };
  }

  const buyPrice = optionalNumber(holding.buy_price);
  if (!Number.isFinite(buyPrice) || buyPrice <= 0) return null;
  const isShort = Number(holding.quantity) < 0;
  const profitPercent = profitReviewThreshold(context.profitReviewPercent);
  const reviewTarget = buyPrice * (1 + (isShort ? -1 : 1) * profitPercent / 100);
  const candidates = [
    { price: reviewTarget, source: `${profitPercent}% return objective` },
    { price: optionalNumber(context.technicalTarget), source: "Technical Target 1" },
    { price: optionalNumber(context.resistanceTarget), source: "Technical resistance" },
    { price: optionalNumber(context.analystTarget), source: "Analyst target proxy" },
  ].filter(({ price }) => (
    Number.isFinite(price) && price > 0 && (isShort ? price <= buyPrice : price >= buyPrice)
  ));
  if (!candidates.length) return null;

  const selectedPrice = isShort
    ? Math.max(...candidates.map(({ price }) => price))
    : Math.min(...candidates.map(({ price }) => price));
  const tolerance = Math.max(0.000001, selectedPrice * 0.000001);
  const selectedSources = candidates
    .filter(({ price }) => Math.abs(price - selectedPrice) <= tolerance)
    .map(({ source }) => source);
  return {
    price: selectedPrice,
    type: "automatic",
    source: selectedSources.join(" + "),
    candidates,
  };
}

export function daysHeld(boughtOn, now = new Date()) {
  if (!boughtOn) return null;
  const bought = new Date(`${boughtOn}T00:00:00Z`);
  if (Number.isNaN(bought.getTime())) return null;
  return Math.max(0, Math.floor((now.getTime() - bought.getTime()) / 86_400_000));
}

export function marketDaysHeld(boughtOn, now = new Date()) {
  if (!boughtOn) return null;
  const start = new Date(`${boughtOn}T00:00:00Z`);
  const end = now instanceof Date ? now : new Date(now);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
  let marketDays = 0;
  const cursor = new Date(start);
  cursor.setUTCDate(cursor.getUTCDate() + 1);
  while (cursor <= end) {
    const weekday = cursor.getUTCDay();
    if (weekday !== 0 && weekday !== 6) marketDays += 1;
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return marketDays;
}

export function annualizedTargetReturnPercent(annualTargetPercent, marketDays) {
  const annualTarget = Number(annualTargetPercent);
  if (!Number.isFinite(annualTarget) || annualTarget < 0 || annualTarget > 100
    || !Number.isFinite(marketDays) || marketDays < 0) return null;
  return (Math.pow(1 + annualTarget / 100, marketDays / 252) - 1) * 100;
}

export function equalWeightTopTwentyMetrics(chartData) {
  const labels = Array.isArray(chartData?.labels) ? chartData.labels : [];
  const values = Array.isArray(chartData?.top20) ? chartData.top20 : [];
  if (labels.length < 2 || labels.length !== values.length) return null;
  const firstDate = new Date(`${labels[0]}T00:00:00Z`);
  const lastDate = new Date(`${labels.at(-1)}T00:00:00Z`);
  const firstValue = Number(values[0]);
  const lastValue = Number(values.at(-1));
  const elapsedDays = Math.round((lastDate.getTime() - firstDate.getTime()) / 86_400_000);
  if (
    Number.isNaN(firstDate.getTime()) || Number.isNaN(lastDate.getTime())
    || elapsedDays <= 0 || !Number.isFinite(firstValue) || firstValue <= 0
    || !Number.isFinite(lastValue) || lastValue <= 0
  ) return null;
  const growthFactor = lastValue / firstValue;
  const dailyReturn = growthFactor ** (1 / elapsedDays) - 1;
  const annualizedReturn = (1 + dailyReturn) ** 365.25 - 1;
  return {
    startDate: labels[0],
    endDate: labels.at(-1),
    elapsedDays,
    totalReturnPercent: (growthFactor - 1) * 100,
    annualizedReturnPercent: annualizedReturn * 100,
    dailyReturn,
  };
}

export function estimatedBreakevenDays(buyPrice, currentPrice, benchmarkMetrics) {
  const purchased = Number(buyPrice);
  const current = Number(currentPrice);
  const dailyReturn = Number(benchmarkMetrics?.dailyReturn);
  if (!Number.isFinite(purchased) || purchased <= 0 || !Number.isFinite(current) || current <= 0) {
    return null;
  }
  if (current >= purchased) return 0;
  if (!Number.isFinite(dailyReturn) || dailyReturn <= 0) return null;
  const days = Math.log(purchased / current) / Math.log(1 + dailyReturn);
  return Number.isFinite(days) && days >= 0 ? Math.ceil(days) : null;
}

export function profitTimingLabel(returnPercent, heldDays) {
  if (returnPercent === null) return "Price unavailable";
  const duration = heldDays === null ? "buy date needed" : `${heldDays} day${heldDays === 1 ? "" : "s"} held`;
  if (returnPercent > 0) return `Profitable · ${duration}`;
  if (returnPercent < 0) return `Not profitable · ${duration}`;
  return `Break-even · ${duration}`;
}

export function sellReviewSignal(holding, currentPrice, returnPercent, requestedProfitPercent = DEFAULT_PROFIT_REVIEW_PERCENT) {
  if (!Number.isFinite(currentPrice) || returnPercent === null) {
    return { code: "unavailable", label: "Price unavailable" };
  }
  const isShort = Number(holding.quantity) < 0;
  const target = Number(holding.target_price);
  const stop = Number(holding.stop_loss);
  if (Number.isFinite(target) && target > 0 && (isShort ? currentPrice <= target : currentPrice >= target)) {
    return { code: "sell-review", label: "Sell review · target reached" };
  }
  if (Number.isFinite(stop) && stop > 0 && (isShort ? currentPrice >= stop : currentPrice <= stop)) {
    return { code: "risk-review", label: "Risk review · stop reached" };
  }
  const profitPercent = profitReviewThreshold(requestedProfitPercent);
  if (returnPercent >= profitPercent) {
    return { code: "sell-review", label: `Profit review · +${profitPercent}% rule` };
  }
  if (returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT) {
    return { code: "risk-review", label: `Risk review · ${DEFAULT_LOSS_REVIEW_PERCENT}% rule` };
  }
  return { code: "monitor", label: "Hold / monitor" };
}

export function portfolioConcentrationPercent(holdings) {
  const bySymbol = {};
  let grossMarketValue = 0;
  for (const holding of holdings || []) {
    const price = Number(holding?.quote?.price);
    const quantity = Number(holding?.quantity);
    if (!Number.isFinite(price) || price < 0 || !Number.isFinite(quantity)) continue;
    const marketValue = Math.abs(price * quantity);
    bySymbol[holding.symbol] = (bySymbol[holding.symbol] || 0) + marketValue;
    grossMarketValue += marketValue;
  }
  if (grossMarketValue <= 0) return {};
  return Object.fromEntries(Object.entries(bySymbol).map(([symbol, value]) => [
    symbol,
    value / grossMarketValue * 100,
  ]));
}

export function portfolioActionDecision(holding, context = {}) {
  const optionalNumber = (value) => value === null || value === undefined || value === "" ? Number.NaN : Number(value);
  const currentPrice = optionalNumber(context.currentPrice);
  const returnPercent = optionalNumber(context.returnPercent);
  const heldDays = optionalNumber(context.heldDays);
  const heldMarketDays = optionalNumber(context.heldMarketDays);
  const concentrationPercent = optionalNumber(context.concentrationPercent);
  const scannerRecommendation = String(context.scannerRecommendation || "unavailable")
    .trim().toLowerCase().replace(/\s+/g, "-");
  const scannerScore = optionalNumber(context.scannerScore);
  const profitPercent = profitReviewThreshold(context.profitReviewPercent);
  const requiredReturnPercent = annualizedTargetReturnPercent(profitPercent, heldMarketDays);
  const isShort = Number(holding.quantity) < 0;
  const targetDetails = context.recommendedTarget || recommendedTargetPrice(holding, context);
  const target = Number(targetDetails?.price);
  const stop = Number(holding.stop_loss);
  const hasPrice = Number.isFinite(currentPrice) && currentPrice >= 0;
  const hasReturn = Number.isFinite(returnPercent);
  const targetHit = hasPrice && Number.isFinite(target) && target > 0
    && (isShort ? currentPrice <= target : currentPrice >= target);
  const stopHit = hasPrice && Number.isFinite(stop) && stop > 0
    && (isShort ? currentPrice >= stop : currentPrice <= stop);
  const strength = technicalStrength(scannerScore);
  const scannerReason = `Technical strength: ${strength.label}${strength.score === null ? "" : ` · ${strength.score.toFixed(0)}/100`}`;
  const decision = (code, label, reasons, priority) => ({ code, label, reasons, priority, technicalReason: scannerReason });

  if (!hasPrice || !hasReturn) {
    return decision("unavailable", "Data needed", ["Present price or buy price is unavailable."], -1);
  }
  if (stopHit) {
    return decision("sell", "Sell review", [`Stop-loss ${stop.toFixed(2)} has been reached.`, scannerReason], 3);
  }
  if (targetHit) {
    const targetKind = targetDetails?.type === "manual" ? "Manual target" : "Automatic target";
    return decision("sell", "Sell review", [
      `${targetKind} ${target.toFixed(2)} has been reached (${targetDetails?.source || "target rule"}).`,
      scannerReason,
    ], 3);
  }
  if (scannerRecommendation === "avoid" && returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT) {
    return decision("sell", "Sell review", [
      `${returnPercent.toFixed(2)}% return is below the ${DEFAULT_LOSS_REVIEW_PERCENT}% risk threshold.`,
      scannerReason,
    ], 3);
  }
  if (Number.isFinite(concentrationPercent) && concentrationPercent >= 20) {
    return decision("partial-sell", "Partial sell review", [
      `${concentrationPercent.toFixed(1)}% portfolio concentration exceeds the 20% high-concentration threshold.`,
      scannerReason,
    ], 2);
  }
  if (scannerRecommendation === "avoid" && returnPercent > 0) {
    return decision("partial-sell", "Partial sell review", [
      `Protect a ${returnPercent.toFixed(2)}% gain; review the position's technical strength.`,
      scannerReason,
    ], 2);
  }
  if (Number.isFinite(requiredReturnPercent) && returnPercent < requiredReturnPercent
    && Number.isFinite(heldMarketDays) && heldMarketDays >= 21
    && (scannerRecommendation === "avoid" || scannerRecommendation === "watch"
      || strength.tone === "weak" || Number.isFinite(concentrationPercent) && concentrationPercent >= 10)) {
    return decision("partial-sell", "Review · below return target", [
      `Return is ${returnPercent.toFixed(2)}%; the ${profitPercent}% annual target compounds to ${requiredReturnPercent.toFixed(2)}% over ${heldMarketDays} market days.`,
      scannerRecommendation === "avoid" || scannerRecommendation === "watch" || strength.tone === "weak"
        ? scannerReason
        : `${concentrationPercent.toFixed(1)}% portfolio concentration.`,
      "Consider selling or replacing only after reviewing fundamentals, costs, tax and alternatives.",
    ], 2);
  }
  if (
    returnPercent >= profitPercent
    && (
      ["watch", "avoid"].includes(scannerRecommendation)
      || (Number.isFinite(heldDays) && heldDays >= 180)
      || (Number.isFinite(concentrationPercent) && concentrationPercent >= 10)
    )
  ) {
    const secondaryReason = Number.isFinite(concentrationPercent) && concentrationPercent >= 10
      ? `${concentrationPercent.toFixed(1)}% portfolio concentration.`
      : Number.isFinite(heldDays) && heldDays >= 180
        ? `${heldDays} days held.`
        : scannerReason;
    return decision("partial-sell", "Partial sell review", [
      `${returnPercent.toFixed(2)}% return exceeds the ${profitPercent}% profit-review threshold.`,
      secondaryReason,
    ], 2);
  }
  if (
    returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT
    && (scannerRecommendation === "watch" || (Number.isFinite(heldDays) && heldDays >= 180))
  ) {
    return decision("partial-sell", "Partial sell review", [
      `${returnPercent.toFixed(2)}% return is below the ${DEFAULT_LOSS_REVIEW_PERCENT}% risk threshold.`,
      Number.isFinite(heldDays) ? `${heldDays} days held; reassess capital efficiency.` : scannerReason,
    ], 2);
  }

  const holdReasons = [scannerReason];
  if (Number.isFinite(concentrationPercent)) {
    holdReasons.push(`${concentrationPercent.toFixed(1)}% of known portfolio market value.`);
  }
  return decision("hold", "Hold / monitor", holdReasons, 1);
}
