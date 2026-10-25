import { useEffect, useRef } from 'react';
import Chart from 'chart.js/auto';
import { THRESHOLDS } from '../config';
import { MODE_LABEL, REASON_LABEL, hourOf, labelOf, dateOf } from '../utils';

export const COLORS = {
  ink: '#14130f',
  muted: '#6b675e',
  grid: 'rgba(20,19,15,0.08)',
  main: '#2b5c8a', // main grid
  storage: '#b8690c', // renewable storage
  critical: '#c62828', // reserved for overload / low battery
  shade: 'rgba(184,105,12,0.10)',
  surface: '#fbfaf7',
};

Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = COLORS.muted;
Chart.defaults.animation = false;

// Create the chart when `hours` changes, and cheaply redraw when the selected hour moves.
function useChart(build, hours, selected, onSelect) {
  const canvas = useRef(null);
  const chartRef = useRef(null);
  const sel = useRef(selected);
  const pick = useRef(onSelect);
  sel.current = selected;
  pick.current = onSelect;

  useEffect(() => {
    if (!canvas.current || !hours?.length) return undefined;
    const chart = new Chart(canvas.current, build(hours, sel, pick));
    chartRef.current = chart;
    return () => chart.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours]);

  useEffect(() => {
    chartRef.current?.update('none');
  }, [selected]);

  return canvas;
}

// Contiguous index ranges whose hour is inside 18:00-22:00.
function eveningBlocks(hours) {
  const blocks = [];
  let start = null;
  hours.forEach((h, i) => {
    const inside = hourOf(h.timestamp) >= 18 && hourOf(h.timestamp) <= 22;
    if (inside && start === null) start = i;
    if (!inside && start !== null) {
      blocks.push([start, i - 1]);
      start = null;
    }
  });
  if (start !== null) blocks.push([start, hours.length - 1]);
  return blocks;
}

const hsPlugin = (hours, sel) => ({
  id: 'hs',
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea: a, scales } = chart;
    const x = scales.x;
    const step = hours.length > 1 ? (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2 : 20;
    ctx.save();
    ctx.fillStyle = COLORS.shade;
    eveningBlocks(hours).forEach(([s, e]) => {
      const x0 = Math.max(a.left, x.getPixelForValue(s) - step);
      const x1 = Math.min(a.right, x.getPixelForValue(e) + step);
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
    });
    ctx.restore();
  },
  afterDatasetsDraw(chart) {
    const { ctx, chartArea: a, scales } = chart;
    const y = scales.y;
    ctx.save();
    ctx.font = "500 11px 'Inter', sans-serif";
    [
      [THRESHOLDS.mode, COLORS.muted, '160 kW'],
      [THRESHOLDS.overload, COLORS.critical, '200 kW overload'],
    ].forEach(([v, color, text]) => {
      const py = y.getPixelForValue(v);
      if (py < a.top || py > a.bottom) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.25;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(a.left, py);
      ctx.lineTo(a.right, py);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.textAlign = 'right';
      ctx.fillText(text, a.right - 4, py - 5);
    });
    const i = sel.current;
    if (i >= 0 && i < hours.length) {
      const px = scales.x.getPixelForValue(i);
      ctx.strokeStyle = COLORS.ink;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(px, a.top);
      ctx.lineTo(px, a.bottom);
      ctx.stroke();
    }
    ctx.restore();
  },
});

const baseScales = (labels, yTitle, extra = {}) => ({
  x: {
    grid: { display: false },
    border: { color: COLORS.grid },
    ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
  },
  y: {
    grid: { color: COLORS.grid },
    border: { display: false },
    title: { display: true, text: yTitle, color: COLORS.muted },
    ...extra,
  },
});

function loadConfig(hours, sel, pick) {
  const multiDay = new Set(hours.map((h) => dateOf(h.timestamp))).size > 1;
  const labels = hours.map((h) => labelOf(h.timestamp, multiDay));
  const isSel = (c) => c.dataIndex === sel.current;
  const dense = hours.length > 48;
  return {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Predicted demand',
          data: hours.map((h) => h.predicted_kw),
          borderColor: COLORS.ink,
          borderWidth: 2,
          tension: 0.25,
          // Mode is encoded twice: colour and marker shape (circle vs diamond).
          pointStyle: (c) => (hours[c.dataIndex].grid_mode === 'RENEWABLE_STORAGE' ? 'rectRot' : 'circle'),
          pointBackgroundColor: (c) => (hours[c.dataIndex].grid_mode === 'RENEWABLE_STORAGE' ? COLORS.storage : COLORS.main),
          pointBorderColor: (c) => (hours[c.dataIndex].overload_alert ? COLORS.critical : COLORS.surface),
          pointBorderWidth: (c) => (hours[c.dataIndex].overload_alert ? 3 : 2),
          pointRadius: (c) => (isSel(c) ? 9 : dense ? 0 : 6),
          pointHoverRadius: 9,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 12, right: 8 } },
      interaction: { mode: 'index', intersect: false },
      onClick: (_e, els) => els.length && pick.current?.(els[0].index),
      scales: baseScales(labels, 'Demand (kW)', {
        suggestedMin: 100,
        suggestedMax: Math.max(220, Math.ceil(Math.max(...hours.map((h) => h.predicted_kw)) / 10) * 10 + 10),
      }),
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: COLORS.ink,
          padding: 10,
          displayColors: false,
          callbacks: {
            title: (items) => hours[items[0].dataIndex].timestamp.slice(0, 16),
            label: (item) => `${item.parsed.y.toFixed(2)} kW`,
            afterLabel: (item) => {
              const h = hours[item.dataIndex];
              return [`${MODE_LABEL[h.grid_mode]} (${REASON_LABEL[h.mode_reason] || h.mode_reason})`, ...(h.overload_alert ? ['Overload alert'] : [])];
            },
          },
        },
      },
    },
    plugins: [hsPlugin(hours, sel)],
  };
}

function socConfig(hours, sel, pick) {
  const multiDay = new Set(hours.map((h) => dateOf(h.timestamp))).size > 1;
  const labels = hours.map((h) => labelOf(h.timestamp, multiDay));
  const lowLine = {
    id: 'lowLine',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales } = chart;
      const py = scales.y.getPixelForValue(THRESHOLDS.lowBattery);
      ctx.save();
      ctx.strokeStyle = COLORS.critical;
      ctx.lineWidth = 1.25;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(a.left, py);
      ctx.lineTo(a.right, py);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = COLORS.critical;
      ctx.font = "500 11px 'Inter', sans-serif";
      ctx.textAlign = 'right';
      ctx.fillText('20% low battery', a.right - 4, py - 5);
      const i = sel.current;
      if (i >= 0 && i < hours.length) {
        const px = scales.x.getPixelForValue(i);
        ctx.strokeStyle = COLORS.ink;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(px, a.top);
        ctx.lineTo(px, a.bottom);
        ctx.stroke();
      }
      ctx.restore();
    },
  };
  return {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Battery SoC',
          data: hours.map((h) => h.battery_soc_pct),
          borderColor: COLORS.ink,
          borderWidth: 2,
          tension: 0.25,
          fill: true,
          backgroundColor: 'rgba(20,19,15,0.05)',
          pointBackgroundColor: (c) => (hours[c.dataIndex].battery_low ? COLORS.critical : COLORS.ink),
          pointBorderColor: COLORS.surface,
          pointBorderWidth: 2,
          pointRadius: (c) => (c.dataIndex === sel.current ? 8 : hours.length > 48 ? 0 : 4),
          pointHoverRadius: 8,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 12, right: 8 } },
      interaction: { mode: 'index', intersect: false },
      onClick: (_e, els) => els.length && pick.current?.(els[0].index),
      scales: baseScales(labels, 'State of charge (%)', { min: 0, max: 100 }),
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: COLORS.ink,
          padding: 10,
          displayColors: false,
          callbacks: {
            title: (items) => hours[items[0].dataIndex].timestamp.slice(0, 16),
            label: (item) => `${item.parsed.y.toFixed(1)}% state of charge`,
            afterLabel: (item) => (hours[item.dataIndex].battery_low ? 'Low battery' : ''),
          },
        },
      },
    },
    plugins: [lowLine],
  };
}

export function LoadChart({ hours, selected, onSelect }) {
  const ref = useChart(loadConfig, hours, selected, onSelect);
  return (
    <div className="chart-box" role="img" aria-label="Predicted demand in kilowatts over the forecast window, with 160 and 200 kilowatt thresholds">
      <canvas ref={ref} />
    </div>
  );
}

export function SocChart({ hours, selected, onSelect }) {
  const ref = useChart(socConfig, hours, selected, onSelect);
  return (
    <div className="chart-box chart-box--short" role="img" aria-label="Battery state of charge over the forecast window">
      <canvas ref={ref} />
    </div>
  );
}
