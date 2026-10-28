// Timestamps travel as "YYYY-MM-DD HH:MM:SS" strings. Slicing avoids timezone surprises.
export const hourOf = (ts) => Number(String(ts).slice(11, 13));
export const timeOf = (ts) => String(ts).slice(11, 16);
export const dateOf = (ts) => String(ts).slice(0, 10);

export function labelOf(ts, multiDay) {
  return multiDay ? `${String(ts).slice(5, 10)} ${timeOf(ts)}` : timeOf(ts);
}

export const fmt = (n, d = 1) => (n === null || n === undefined || Number.isNaN(n) ? '–' : Number(n).toFixed(d));

export const MODE_LABEL = { MAIN_GRID: 'Main grid', RENEWABLE_STORAGE: 'Renewable storage' };
export const REASON_LABEL = {
  demand_over_160: 'Demand over 160 kW',
  evening_window: 'Evening window 18-22',
  both: 'Demand and evening window',
  normal: 'Normal operation',
};

// "2015-06-16T15:00" (datetime-local) <-> "2015-06-16 15:00:00" (API)
export const toApiTs = (v) => (v ? `${v.replace('T', ' ')}${v.length === 16 ? ':00' : ''}` : '');
export const fromApiTs = (v) => (v ? String(v).slice(0, 16).replace(' ', 'T') : '');

export function addHours(localTs, h) {
  // localTs "YYYY-MM-DDTHH:mm"; work in UTC so DST never shifts the result.
  const [d, t] = localTs.split('T');
  const [y, mo, da] = d.split('-').map(Number);
  const [hh, mm] = t.split(':').map(Number);
  const dt = new Date(Date.UTC(y, mo - 1, da, hh + h, mm));
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())}T${p(dt.getUTCHours())}:${p(dt.getUTCMinutes())}`;
}

export function relTime(iso) {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return String(iso);
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(t).toLocaleString();
}

export const EVENT_LABEL = { MODE_SWITCH: 'Switch', OVERLOAD: 'Overload', BATTERY_LOW: 'Battery low' };

// "MAIN_GRID -> RENEWABLE_STORAGE (evening_window)" -> "Main grid → Renewable storage (Evening window 18-22)"
export function prettyEvent(message) {
  return String(message || '')
    .replace(/RENEWABLE_STORAGE|MAIN_GRID/g, (m) => MODE_LABEL[m])
    .replace(/\((demand_over_160|evening_window|both|normal)\)/g, (_, r) => `(${REASON_LABEL[r]})`)
    .replace(/\s*->\s*/g, ' → ');
}
