// Local stand-in for the backend, following the shared API CONTRACT exactly.
// Used only when API_BASE_URL is empty (or ?mock). The demand model here is a toy
// formula, not the QuickML model; the grid rules and battery follow the team contract.
import { SAMPLE_ROWS } from './sample';
import { hourOf } from './utils';
import { parseCsv } from './csv';

const CAPACITY_KWH = 2000;
const START_SOC = 0.9;
const GRID_CHARGE_KW = 150;
const SOLAR_ARRAY_KW = 200;

const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const r2 = (n) => Math.round(n * 100) / 100;
const pad = (n) => String(n).padStart(2, '0');

export class MockApiError extends Error {
  constructor(message, status, details) {
    super(message);
    this.status = status;
    this.details = details || [];
  }
}

function toyDemand(row) {
  const h = hourOf(row.timestamp);
  const t = row.ambient_temp_c ?? 28;
  const irr = row.solar_irradiance_wm2 ?? 0;
  const diurnal = 24 * Math.sin(((h - 9) / 24) * 2 * Math.PI) + (h >= 18 && h <= 22 ? 26 : 0);
  return 150 + (t - 28) * 3.4 + diurnal - irr * 0.012;
}

function control(kw, hour) {
  const over = kw > 160;
  const evening = hour >= 18 && hour <= 22;
  return {
    grid_mode: over || evening ? 'RENEWABLE_STORAGE' : 'MAIN_GRID',
    mode_reason: over && evening ? 'both' : over ? 'demand_over_160' : evening ? 'evening_window' : 'normal',
    overload_alert: kw >= 200,
  };
}

function build(rows, source) {
  const now = new Date();
  const forecastId = `f_${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}_${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}`;
  let soc = CAPACITY_KWH * START_SOC;
  const hours = rows.map((r) => {
    const kw = r2(toyDemand(r));
    const c = control(kw, hourOf(r.timestamp));
    soc += c.grid_mode === 'RENEWABLE_STORAGE' ? -kw : GRID_CHARGE_KW;
    soc += ((r.solar_irradiance_wm2 ?? 0) / 1000) * SOLAR_ARRAY_KW;
    soc = Math.min(CAPACITY_KWH, Math.max(0, soc));
    const pct = r2((soc / CAPACITY_KWH) * 100);
    return { ...r, predicted_kw: kw, ...c, battery_soc_pct: pct, battery_low: pct < 20 };
  });

  const events = [];
  hours.forEach((h, i) => {
    if (i > 0 && h.grid_mode !== hours[i - 1].grid_mode) {
      events.push({
        timestamp: h.timestamp,
        type: 'MODE_SWITCH',
        message: `${hours[i - 1].grid_mode} -> ${h.grid_mode} (${h.mode_reason})`,
      });
    }
  });
  const peak = hours.reduce((a, b) => (b.predicted_kw > a.predicted_kw ? b : a), hours[0]);
  return {
    forecast_id: forecastId,
    generated_at: now.toISOString().replace(/\.\d+Z$/, 'Z'),
    model_source: source,
    hours,
    events,
    summary: {
      peak_kw: peak.predicted_kw,
      peak_timestamp: peak.timestamp,
      storage_hours: hours.filter((h) => h.grid_mode === 'RENEWABLE_STORAGE').length,
      main_grid_hours: hours.filter((h) => h.grid_mode === 'MAIN_GRID').length,
      overload_hours: hours.filter((h) => h.overload_alert).length,
      min_soc_pct: Math.min(...hours.map((h) => h.battery_soc_pct)),
    },
    warnings: rows.flatMap((r, i) =>
      ['ambient_temp_c', 'humidity_pct', 'solar_irradiance_wm2']
        .filter((f) => r[f] === null)
        .map((f) => `row ${i + 1}: ${f} missing, interpolated`)
    ),
  };
}

let latest = null;
let logs = [];
const log = (level, event, message, forecast_id) =>
  logs.unshift({ time: new Date().toISOString(), level, event, message, forecast_id });

function commit(rows, note) {
  const f = build(rows, 'fallback');
  latest = f;
  log('INFO', 'UPLOAD', `${note}: ${rows.length} rows, ${f.hours.length} forecast hours`, f.forecast_id);
  f.events.forEach((e) => log('INFO', 'MODE_SWITCH', `${e.timestamp.slice(11, 16)} ${e.message}`, f.forecast_id));
  if (f.summary.overload_hours) {
    log('CRITICAL', 'OVERLOAD', `${f.summary.overload_hours} overload hour(s), peak ${f.summary.peak_kw} kW`, f.forecast_id);
  }
  const low = f.hours.find((h) => h.battery_low);
  if (low) log('WARN', 'BATTERY_LOW', `Battery below 20% at ${low.timestamp.slice(11, 16)} (${low.battery_soc_pct}%)`, f.forecast_id);
  return f;
}

export const mockApi = {
  async health() {
    await delay(120);
    return { status: 'ok', quickml: 'unreachable', mock: true };
  },
  async latest() {
    await delay(200);
    if (!latest) commit(SAMPLE_ROWS, 'Demo data');
    return latest;
  },
  async logs(limit = 50) {
    await delay(150);
    return { logs: logs.slice(0, limit) };
  },
  async forecast({ rows, file, all, window = 24 }) {
    await delay(500);
    let data = rows;
    if (file) {
      const parsed = parseCsv(await file.text());
      if (parsed.errors.length) throw new MockApiError('Invalid CSV', 400, parsed.errors);
      data = parsed.rows;
    }
    if (!data || !data.length) throw new MockApiError('No rows supplied', 400, ['rows must contain at least one entry']);
    const bad = data.map((r, i) => (!r.timestamp ? `row ${i + 1}: timestamp missing` : null)).filter(Boolean);
    if (bad.length) throw new MockApiError('Validation failed', 400, bad);
    const used = all ? data : data.slice(0, window);
    return commit(used, file ? 'CSV upload' : 'Manual entry');
  },
};
