import { estimatedBreakevenDays } from './portfolio-analysis.js';

export { technicalStrength } from './portfolio-analysis.js';

export function recoveryScenario(holding, benchmark, now = new Date()) {
  const cost = Number(holding.buy_price);
  const current = Number(holding.quote?.price);
  if (Number(holding.quantity) <= 0) return { label: 'Not estimated for short positions' };
  if (holding.quote?.price == null || !(cost > 0) || !(current > 0)) return { label: 'Price data needed' };
  if (current >= cost) return { label: current > cost ? 'Buy price recovered' : 'At buy price', days: 0 };
  const requiredGain = (cost / current - 1) * 100;
  const days = estimatedBreakevenDays(cost, current, benchmark);
  const date = new Date(now);
  if (days !== null) date.setDate(date.getDate() + days);
  return { label: `Needs +${requiredGain.toFixed(2)}% to recover`, requiredGain,
    days, date: days !== null && Number.isFinite(date.getTime()) ? date : null };
}

// Non-overlapping peak-to-recovery episodes. A comparable decline reaches at
// least the holding's current percentage loss; recovery means regaining its peak.
export function historicalRecovery(history, lossFraction, now = new Date()) {
  if (!(lossFraction > 0 && lossFraction < 1)) return { unavailable: 'No current loss to compare.' };
  const validated = validateHistory(history, now);
  if (validated.unavailable) return validated;
  const { points, timestamps } = validated;
  let peak = points[0][1];
  let trigger = null;
  const recoveredDays = [];
  for (let i = 1; i < points.length; i++) {
    const price = points[i][1];
    if (trigger !== null) {
      if (price >= peak) {
        recoveredDays.push(Math.round((timestamps[i] - timestamps[trigger]) / 86400000));
        trigger = null;
        peak = price;
      }
    } else if (price > peak) peak = price;
    else if ((peak - price) / peak >= lossFraction) trigger = i;
  }
  const sorted = [...recoveredDays].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const medianDays = sorted.length ? (sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2) : null;
  return { start: points[0][0], end: points.at(-1)[0], recovered: recoveredDays.length,
    unresolved: trigger !== null ? 1 : 0, medianDays,
    unresolvedDays: trigger !== null ? Math.round((timestamps.at(-1) - timestamps[trigger]) / 86400000) : null };
}

function validateHistory(history, now) {
  const points = history?.points;
  if (!Array.isArray(points) || points.length < 60) return { unavailable: 'Insufficient stock history (at least 60 daily closes needed).' };
  if (points.some((point) => !Array.isArray(point) || point.length < 2)) return { unavailable: 'Stock history could not be validated.' };
  const timestamps = points.map(([date]) => Date.parse(`${date}T00:00:00Z`));
  if (points.some(([, close], i) => !Number.isFinite(close) || close <= 0 || !Number.isFinite(timestamps[i]) || (i > 0 && timestamps[i] <= timestamps[i - 1]))) {
    return { unavailable: 'Stock history could not be validated.' };
  }
  if ((now.getTime() - timestamps.at(-1)) / 86400000 > 7) return { unavailable: 'Stock history is older than seven days; awaiting refresh.' };
  if (timestamps.at(-1) > now.getTime()) return { unavailable: 'Stock history contains future dates.' };
  return { points, timestamps };
}

export function stockGrowthMetrics(history, now = new Date()) {
  const validated = validateHistory(history, now);
  if (validated.unavailable) return validated;
  const { points, timestamps } = validated;
  const elapsedDays = (timestamps.at(-1) - timestamps[0]) / 86400000;
  const dailyReturn = Math.expm1(Math.log(points.at(-1)[1] / points[0][1]) / elapsedDays);
  return { dailyReturn, startDate: points[0][0], endDate: points.at(-1)[0],
    totalReturnPercent: (points.at(-1)[1] / points[0][1] - 1) * 100,
    points: points.map(([date, price]) => ({ date: new Date(`${date}T00:00:00`), price })) };
}

export function annualTargetCatchupEstimate(holding, metrics, annualTargetPercent, heldMarketDays) {
  if (!(Number(holding.quantity) > 0)) return { unavailable: 'Not estimated for short positions.' };
  const cost = Number(holding.buy_price);
  const current = Number(holding.quote?.price);
  const annualTarget = Number(annualTargetPercent);
  if (!(cost > 0) || !(current > 0) || !Number.isFinite(heldMarketDays)
    || !Number.isFinite(annualTarget) || annualTarget < 0 || annualTarget > 100) {
    return { unavailable: 'Buy date or price data needed.' };
  }
  const requiredReturnPercent = (Math.pow(1 + annualTarget / 100, heldMarketDays / 252) - 1) * 100;
  const currentReturnPercent = (current / cost - 1) * 100;
  const gapPercent = Math.max(0, requiredReturnPercent - currentReturnPercent);
  const targetDailyReturn = Math.pow(1 + annualTarget / 100, 1 / 252) - 1;
  const targetPrice = cost * Math.pow(1 + annualTarget / 100, heldMarketDays / 252);
  if (gapPercent === 0) return { requiredReturnPercent, currentReturnPercent, gapPercent, targetDailyReturn, targetPrice, days: 0 };
  const points = metrics?.points;
  if (!Array.isArray(points) || points.length < 200 || !Number.isFinite(metrics.dailyReturn)) {
    return { requiredReturnPercent, currentReturnPercent, gapPercent, targetDailyReturn, targetPrice,
      unavailable: 'At least 200 valid daily prices needed for a one-year trend estimate.' };
  }
  const lastYear = points.slice(-253);
  if (lastYear.length < 200 || (lastYear.at(-1).date - lastYear[0].date) / 86400000 < 300) {
    return { requiredReturnPercent, currentReturnPercent, gapPercent, targetDailyReturn, targetPrice,
      unavailable: 'At least 200 valid daily prices spanning 300 days needed.' };
  }
  const dailyReturns = lastYear.slice(1).map((point, index) => point.price / lastYear[index].price - 1);
  const averageDailyReturn = dailyReturns.reduce((sum, value) => sum + value, 0) / dailyReturns.length;
  if (!(averageDailyReturn > 0)) {
    return { requiredReturnPercent, currentReturnPercent, gapPercent, averageDailyReturn, targetDailyReturn, targetPrice,
      unavailable: 'One-year average daily return is not positive.' };
  }
  const relativeDailyReturn = Math.log1p(averageDailyReturn) - Math.log1p(targetDailyReturn);
  if (!(relativeDailyReturn > 0)) {
    return { requiredReturnPercent, currentReturnPercent, gapPercent, averageDailyReturn, targetDailyReturn,
      targetPrice, unavailable: 'The one-year average trend does not outpace the moving annual target.' };
  }
  const days = Math.max(0, Math.ceil(Math.log(targetPrice / current) / relativeDailyReturn));
  return { requiredReturnPercent, currentReturnPercent, gapPercent, averageDailyReturn, targetDailyReturn,
    targetPrice, days };
}

export function recoveryGraphModel(holding, history, benchmark, now = new Date(), annualTarget) {
  const stock = stockGrowthMetrics(history, now);
  const stockScenario = recoveryScenario(holding, stock, now);
  const benchmarkScenario = recoveryScenario(holding, benchmark, now);
  const current = Number(holding.quote?.price);
  const target = Number(holding.buy_price);
  if (!(current > 0) || !(target > current) || !(Number(holding.quantity) > 0)) return { unavailable: 'A losing long position with valid prices is required.' };
  const targetScenario = annualTargetCatchupEstimate(holding, stock, annualTarget?.percent, annualTarget?.heldMarketDays);
  const crossings = [stockScenario.days, benchmarkScenario.days, targetScenario.days]
    .filter((days) => Number.isFinite(days) && days > 0);
  const horizonDays = Math.min(1826, Math.max(365, Math.ceil(Math.max(0, ...crossings) * 1.08)));
  const dateAfter = (day) => { const date = new Date(now); date.setDate(date.getDate() + day); return date; };
  const projection = (metrics, scenario) => {
    if (!Number.isFinite(metrics?.dailyReturn) || metrics.dailyReturn <= -1) return [];
    const endDay = Math.min(horizonDays, scenario.days ?? horizonDays);
    const days = [...new Set([0, ...Array.from({ length: 80 }, (_, i) => Math.ceil((i + 1) * endDay / 80)), endDay])];
    return days.map((day) => ({ day, date: dateAfter(day), price: Math.min(target, current * Math.exp(Math.log1p(metrics.dailyReturn) * day)) }));
  };
  const dateAfterMarketDays = (days) => {
    const date = new Date(now);
    let remaining = days;
    while (remaining > 0) {
      date.setDate(date.getDate() + 1);
      if (date.getDay() !== 0 && date.getDay() !== 6) remaining -= 1;
    }
    return date;
  };
  const annualTargetProjection = (dailyRate, basePrice, initialMarketDays) => {
    if (!Number.isFinite(dailyRate) || dailyRate <= -1 || !(basePrice > 0) || !Number.isFinite(initialMarketDays)) return [];
    const maxMarketDays = Math.ceil(horizonDays * 252 / 365.25);
    const endMarketDays = Math.min(maxMarketDays, targetScenario.days ?? maxMarketDays);
    const marketDays = [...new Set([0, ...Array.from({ length: 80 }, (_, i) => Math.ceil((i + 1) * endMarketDays / 80)), endMarketDays])];
    return marketDays.map((day) => ({
      day,
      date: dateAfterMarketDays(day),
      price: basePrice * Math.exp(Math.log1p(dailyRate) * day),
      targetPrice: target * Math.pow(1 + (annualTarget?.percent ?? 0) / 100, (initialMarketDays + day) / 252),
    }));
  };
  const annualTargetStockProjection = annualTargetProjection(targetScenario.averageDailyReturn, current, annualTarget?.heldMarketDays);
  const annualTargetPriceProjection = annualTargetProjection(targetScenario.targetDailyReturn, targetScenario.targetPrice, annualTarget?.heldMarketDays)
    .map(({ day, date, targetPrice }) => ({ day, date, price: targetPrice }));
  const annualTargetDate = Number.isFinite(targetScenario.days) ? dateAfterMarketDays(targetScenario.days) : null;
  return { current, target, now, horizonDays, end: dateAfter(horizonDays), stock, targetScenario,
    stockScenario, benchmarkScenario, benchmark,
    annualTargetDate, annualTargetStockProjection, annualTargetPriceProjection,
    history: stock.points || [], stockProjection: projection(stock, stockScenario),
    benchmarkProjection: projection(benchmark, benchmarkScenario) };
}
