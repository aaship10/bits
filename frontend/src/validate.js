// Basic client-side checks. The backend stays the authority; these catch typos early.
const LIMITS = {
  ambient_temp_c: { min: -50, max: 70, label: 'Temperature' },
  humidity_pct: { min: 0, max: 100, label: 'Humidity' },
  solar_irradiance_wm2: { min: 0, max: 1500, label: 'Irradiance' },
};

const TS = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/;

// rows: [{timestamp, ambient_temp_c, humidity_pct, solar_irradiance_wm2}] (values may be null/"")
// returns { errors: [{row, field, msg}], warnings: [string] }  (row is 0-based)
export function validateRows(rows) {
  const errors = [];
  const warnings = [];
  if (!rows.length) return { errors: [{ row: -1, field: null, msg: 'Add at least one hourly row.' }], warnings };

  const seen = new Map();
  let prev = null;
  rows.forEach((r, i) => {
    if (!r.timestamp || !TS.test(String(r.timestamp)) || Number.isNaN(Date.parse(String(r.timestamp).replace(' ', 'T')))) {
      errors.push({ row: i, field: 'timestamp', msg: `Row ${i + 1}: timestamp is missing or invalid.` });
    } else {
      const key = String(r.timestamp).slice(0, 16);
      if (seen.has(key)) errors.push({ row: i, field: 'timestamp', msg: `Row ${i + 1}: duplicate timestamp (also row ${seen.get(key) + 1}).` });
      seen.set(key, i);
      if (prev && key < prev) warnings.push(`Row ${i + 1}: timestamps are not in ascending order.`);
      prev = key;
    }
    for (const [f, lim] of Object.entries(LIMITS)) {
      const v = r[f];
      if (v === null || v === undefined || v === '') {
        warnings.push(`Row ${i + 1}: ${lim.label.toLowerCase()} is blank and will be interpolated by the backend.`);
      } else if (Number.isNaN(Number(v))) {
        errors.push({ row: i, field: f, msg: `Row ${i + 1}: ${lim.label.toLowerCase()} is not a number.` });
      } else if (Number(v) < lim.min || Number(v) > lim.max) {
        errors.push({ row: i, field: f, msg: `Row ${i + 1}: ${lim.label.toLowerCase()} must be between ${lim.min} and ${lim.max}.` });
      }
    }
  });
  return { errors, warnings: warnings.slice(0, 6).concat(warnings.length > 6 ? [`...and ${warnings.length - 6} more warnings.`] : []) };
}

export function rowsToPayload(rows) {
  const n = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
  return rows.map((r) => ({
    timestamp: r.timestamp,
    ambient_temp_c: n(r.ambient_temp_c),
    humidity_pct: n(r.humidity_pct),
    solar_irradiance_wm2: n(r.solar_irradiance_wm2),
  }));
}
