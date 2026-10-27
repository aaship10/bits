// API_BASE_URL is read at runtime from public/config.js (window.__APP_CONFIG__),
// then from VITE_API_BASE_URL at build time. It is never hard-coded.
const runtime = (typeof window !== 'undefined' && window.__APP_CONFIG__) || {};

export const API_BASE_URL = String(runtime.API_BASE_URL || import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

// Empty base URL, or ?mock in the page URL, switches to the built-in mock API.
export const USE_MOCK =
  !API_BASE_URL || (typeof location !== 'undefined' && new URLSearchParams(location.search).has('mock'));

export const REFRESH_MS = 30000;
export const THRESHOLDS = { mode: 160, overload: 200, lowBattery: 20 };
export const EVENING = { from: 18, to: 22 };
