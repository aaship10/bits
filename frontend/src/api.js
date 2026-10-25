import { API_BASE_URL, USE_MOCK } from './config';
import { mockApi } from './mock';

export class ApiError extends Error {
  constructor(message, { status = 0, details = [] } = {}) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function request(path, { method = 'GET', body, timeout = 25000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body && !isForm ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
      signal: ctrl.signal,
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      /* non-JSON body */
    }
    if (!res.ok) {
      throw new ApiError(data?.error || `Request failed (${res.status})`, { status: res.status, details: data?.details || [] });
    }
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e.name === 'AbortError') throw new ApiError('The backend did not respond in time.');
    throw new ApiError('Could not reach the backend. Check API_BASE_URL and CORS.');
  } finally {
    clearTimeout(timer);
  }
}

function wrapMock(fn) {
  return async (...a) => {
    try {
      return await fn(...a);
    } catch (e) {
      throw new ApiError(e.message, { status: e.status || 0, details: e.details || [] });
    }
  };
}

const live = {
  health: () => request('/api/health', { timeout: 8000 }),
  async latest() {
    try {
      return await request('/api/forecast/latest');
    } catch (e) {
      if (e.status === 404) return null; // no forecast yet
      throw e;
    }
  },
  logs: (limit = 50) => request(`/api/logs?limit=${limit}`),
  forecast({ rows, file, all, window = 24 }) {
    const q = all ? '?all=true' : `?window=${window}`;
    if (file) {
      const fd = new FormData();
      fd.append('file', file);
      return request(`/api/forecast${q}`, { method: 'POST', body: fd, timeout: 60000 });
    }
    return request(`/api/forecast${q}`, { method: 'POST', body: { rows }, timeout: 60000 });
  },
};

export const api = USE_MOCK
  ? {
      health: wrapMock(mockApi.health),
      latest: wrapMock(mockApi.latest),
      logs: wrapMock(mockApi.logs),
      forecast: wrapMock(mockApi.forecast),
    }
  : live;
