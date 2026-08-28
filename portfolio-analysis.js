export const DEFAULT_PROFIT_REVIEW_PERCENT = 20;
export const DEFAULT_LOSS_REVIEW_PERCENT = -10;

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
  if (!text && !required) return null;
  const parsed = Number(text);
  if (!Number.isFinite(parsed) || (nonzero && parsed === 0)) {
    throw new Error(`Row ${rowNumber}: ${label} must be ${nonzero ? "a non-zero" : "a valid"} number.`);
  }
  return parsed;
}

function dateValue(value, rowNumber) {
  const text = String(value || "").trim();
  if (!text) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || Number.isNaN(Date.parse(`${text}T00:00:00Z`))) {
    throw new Error(`Row ${rowNumber}: buy_date must use YYYY-MM-DD.`);
  }
  return text;
}

export function portfolioRowsFromCsv(source) {
  const rows = parseCsv(source);
  if (rows.length < 2) throw new Error("The CSV must contain a header and at least one holding.");
  if (rows.length > 1001) throw new Error("A CSV import is limited to 1000 holdings.");
  const headers = rows[0].map((value) => value.trim().toLowerCase());
  for (const required of ["symbol", "quantity", "buy_price", "buy_date"]) {
    if (!headers.includes(required)) throw new Error(`Missing required CSV column: ${required}`);
  }
  const get = (row, name) => row[headers.indexOf(name)] || "";
  return rows.slice(1).map((row, index) => {
    const rowNumber = index + 2;
    const symbol = get(row, "symbol").trim().toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) {
      throw new Error(`Row ${rowNumber}: invalid ticker symbol.`);
    }
    const boughtOn = dateValue(get(row, "buy_date"), rowNumber);
    const currency = (get(row, "currency") || "USD").trim().toUpperCase();
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

export function holdingReturnPercent(holding, currentPrice) {
  const buyPrice = Number(holding.buy_price);
  const quantity = Number(holding.quantity);
  if (!Number.isFinite(currentPrice) || currentPrice < 0 || !Number.isFinite(buyPrice) || buyPrice <= 0) {
    return null;
  }
  return (quantity < 0 ? buyPrice - currentPrice : currentPrice - buyPrice) / buyPrice * 100;
}

export function daysHeld(boughtOn, now = new Date()) {
  if (!boughtOn) return null;
  const bought = new Date(`${boughtOn}T00:00:00Z`);
  if (Number.isNaN(bought.getTime())) return null;
  return Math.max(0, Math.floor((now.getTime() - bought.getTime()) / 86_400_000));
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

export function sellReviewSignal(holding, currentPrice, returnPercent) {
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
  if (returnPercent >= DEFAULT_PROFIT_REVIEW_PERCENT) {
    return { code: "sell-review", label: `Profit review · +${DEFAULT_PROFIT_REVIEW_PERCENT}% rule` };
  }
  if (returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT) {
    return { code: "risk-review", label: `Risk review · ${DEFAULT_LOSS_REVIEW_PERCENT}% rule` };
  }
  return { code: "monitor", label: "Hold / monitor" };
}
