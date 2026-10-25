// PLACEHOLDER: the starter kit was not in the workspace when this file was written.
// Run `npm run sample -- <path to sample_test_input.csv>` to replace it with the real first 24 rows.
export const IS_PLACEHOLDER = true;

const p = (n) => String(n).padStart(2, '0');
export const SAMPLE_ROWS = Array.from({ length: 24 }, (_, i) => {
  const dt = new Date(Date.UTC(2015, 5, 16, 15 + i));
  const h = dt.getUTCHours();
  const sun = Math.max(0, Math.sin(((h - 6) / 12) * Math.PI));
  return {
    timestamp: `${dt.getUTCFullYear()}-${p(dt.getUTCMonth() + 1)}-${p(dt.getUTCDate())} ${p(h)}:00:00`,
    ambient_temp_c: Math.round((26 + 10 * Math.sin(((h - 9) / 24) * 2 * Math.PI)) * 100) / 100,
    humidity_pct: Math.round((62 - 18 * Math.sin(((h - 9) / 24) * 2 * Math.PI)) * 100) / 100,
    solar_irradiance_wm2: Math.round(sun * 780),
  };
});
