import { toApiTs } from './utils';

export const COLUMNS = ['timestamp', 'ambient_temp_c', 'humidity_pct', 'solar_irradiance_wm2'];

const cell = (s) => s.trim().replace(/^"|"$/g, '');

// Small CSV reader for the four telemetry columns. Extra columns (e.g. target) are ignored.
export function parseCsv(text) {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return { rows: [], errors: ['File needs a header line and at least one data row.'] };
  const head = lines[0].split(',').map((h) => cell(h).toLowerCase());
  const missing = COLUMNS.filter((c) => !head.includes(c));
  if (missing.length) return { rows: [], errors: [`Missing column(s): ${missing.join(', ')}`] };
  const idx = Object.fromEntries(COLUMNS.map((c) => [c, head.indexOf(c)]));
  const num = (v) => (v === undefined || cell(v) === '' ? null : Number(cell(v)));
  const rows = lines.slice(1).map((l) => {
    const p = l.split(',');
    const ts = cell(p[idx.timestamp] ?? '');
    return {
      timestamp: ts.includes('T') ? toApiTs(ts.slice(0, 19)) : ts,
      ambient_temp_c: num(p[idx.ambient_temp_c]),
      humidity_pct: num(p[idx.humidity_pct]),
      solar_irradiance_wm2: num(p[idx.solar_irradiance_wm2]),
    };
  });
  return { rows, errors: [] };
}
