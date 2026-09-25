import { formatDate } from './date-format.js';

const SVG = 'http://www.w3.org/2000/svg';
const BLUE = '#4fc3f7', ORANGE = '#ffb74d', TARGET = '#dce775';

export function renderRecoveryChart(container, model, currency = '') {
  container.replaceChildren();
  if (model.unavailable) { container.textContent = model.unavailable; return; }
  const element = (tag, attrs = {}, text) => {
    const node = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const W = 860, H = 370, left = 76, right = 24, top = 36, bottom = 52;
  const plotW = W - left - right, plotH = H - top - bottom;
  const start = model.history[0]?.date || model.now;
  const from = start.getTime(), to = model.end.getTime();
  const x = (date) => left + (date.getTime() - from) / (to - from) * plotW;
  const values = [model.current, model.target, ...model.history.map(p => p.price), ...model.stockProjection.map(p => p.price), ...model.benchmarkProjection.map(p => p.price)];
  const low = Math.min(...values), high = Math.max(...values);
  const pad = Math.max((high - low) * 0.12, high * 0.02);
  const min = Math.max(0, low - pad), max = high + pad;
  const y = (price) => top + (max - price) / (max - min) * plotH;
  const priceLabel = (price) => `${currency} ${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`.trim();
  const scroll = document.createElement('div');
  scroll.className = 'recovery-chart-scroll';
  const svg = element('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Historical stock prices and two hypothetical recovery projections toward the buy price', class: 'recovery-chart' });
  svg.append(element('desc', {}, 'Solid blue is historical adjusted close. Dashed blue is the stock-history growth scenario; dashed orange is the equal-weight Top 20 growth scenario. Both start at the latest quote today. The horizontal line is the buy price. Exact estimates are listed above the graph.'));
  svg.append(element('rect', { x: x(model.now), y: top, width: W - right - x(model.now), height: plotH, fill: '#24394d', opacity: '.5' }));
  for (let i = 0; i <= 4; i++) {
    const price = min + (max - min) * i / 4;
    svg.append(element('line', { x1: left, x2: W - right, y1: y(price), y2: y(price), stroke: '#365065' }));
    svg.append(element('text', { x: left - 9, y: y(price) + 4, fill: '#b0bec5', 'text-anchor': 'end', 'font-size': 12 }, price.toLocaleString('en-US', { maximumFractionDigits: 2 })));
  }
  for (let i = 0; i <= 5; i++) {
    const date = new Date(from + (to - from) * i / 5);
    svg.append(element('text', { x: x(date), y: H - bottom + 24, fill: '#b0bec5', 'text-anchor': i === 0 ? 'start' : i === 5 ? 'end' : 'middle', 'font-size': 12 }, formatDate(date)));
  }
  svg.append(element('text', { x: left, y: 18, fill: '#b0bec5', 'font-size': 12 }, `Price (${currency || 'holding currency'})`));
  svg.append(element('line', { x1: left, x2: W - right, y1: y(model.target), y2: y(model.target), stroke: TARGET, 'stroke-dasharray': '7 5' }));
  svg.append(element('text', { x: W - right, y: y(model.target) - 7, fill: TARGET, 'font-size': 12, 'text-anchor': 'end' }, `Buy price ${priceLabel(model.target)}`));
  svg.append(element('line', { x1: x(model.now), x2: x(model.now), y1: top, y2: H - bottom, stroke: '#cfd8dc', 'stroke-dasharray': '3 5' }));
  svg.append(element('text', { x: x(model.now) + 5, y: top + 12, fill: '#e0e0e0', 'font-size': 12 }, 'Today'));
  const line = (points, color, dash) => {
    if (!points.length) return;
    svg.append(element('path', { d: points.map((p,i) => `${i ? 'L' : 'M'}${x(p.date).toFixed(2)},${y(p.price).toFixed(2)}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2.5, ...(dash ? { 'stroke-dasharray': dash } : {}) }));
  };
  line(model.history, BLUE);
  line(model.stockProjection, BLUE, '8 5');
  line(model.benchmarkProjection, ORANGE, '4 5');
  const marker = (date, price, color, title) => {
    const circle = element('circle', { cx: x(date), cy: y(price), r: 5, fill: color, stroke: '#10212e', 'stroke-width': 2 });
    circle.append(element('title', {}, title)); svg.append(circle);
  };
  marker(model.now, model.current, BLUE, `Latest available price: ${priceLabel(model.current)}`);
  for (const [scenario,color,label] of [[model.stockScenario,BLUE,'Stock-history'],[model.benchmarkScenario,ORANGE,'Top 20']]) {
    if (scenario.date && scenario.days <= model.horizonDays) marker(scenario.date, model.target, color, `${label} estimated recovery: ${formatDate(scenario.date)}`);
  }
  const cursor = element('line', { x1: x(model.now), x2: x(model.now), y1: top, y2: H - bottom, stroke: '#fff', opacity: '.4' });
  svg.append(cursor); scroll.append(svg); container.append(scroll);
  const legend = document.createElement('div'); legend.className = 'recovery-legend';
  for (const [label,color,dash] of [['Stock history',BLUE,false],['Stock projection',BLUE,true],['Top 20 projection',ORANGE,true],['Buy price',TARGET,true]]) {
    const item = document.createElement('span');
    const swatch = document.createElement('i'); swatch.style.borderTop = `3px ${dash ? 'dashed' : 'solid'} ${color}`;
    item.append(swatch, document.createTextNode(label)); legend.append(item);
  }
  container.append(legend);
  const control = document.createElement('label'); control.className = 'recovery-inspector';
  control.append(document.createTextNode('Inspect date'));
  const slider = document.createElement('input'); slider.type = 'range';
  slider.min = -Math.floor((model.now.getTime() - from) / 86400000);
  slider.max = model.horizonDays; slider.value = 0;
  slider.setAttribute('aria-label', 'Inspect date on recovery graph');
  const output = document.createElement('output'); output.className = 'subtle'; output.setAttribute('aria-live','polite');
  const inspect = () => {
    const dayOffset = Number(slider.value);
    const date = new Date(model.now); date.setDate(date.getDate() + dayOffset);
    cursor.setAttribute('x1', x(date)); cursor.setAttribute('x2', x(date));
    let message = `${formatDate(date)} — `;
    if (date < model.now) {
      const point = model.history.filter(p => p.date <= date).at(-1);
      message += point ? `Adjusted close: ${priceLabel(point.price)} (${formatDate(point.date)})` : 'History unavailable';
    } else {
      const days = dayOffset;
      const value = (metrics) => !Number.isFinite(metrics?.dailyReturn) || metrics.dailyReturn <= -1 ? 'unavailable' : priceLabel(Math.min(model.target, model.current * Math.exp(Math.log1p(metrics.dailyReturn) * days)));
      message += `Stock scenario: ${value(model.stock)}; Top 20 scenario: ${value(model.benchmark)}. Lines end at the buy price.`;
    }
    output.textContent = message;
  };
  slider.addEventListener('input',inspect); control.append(slider); container.append(control,output); inspect();
}
