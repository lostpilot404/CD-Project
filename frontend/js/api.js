/**
 * HTTP client for the CodeTrace API.
 *
 * The interface talks to its own origin using relative URLs: the page is served
 * by the same process as the API, and a plain relative path also works when the
 * application is reached through a proxy or a forwarded port.  Nothing here
 * reaches for a hard-coded host, so the interface never assumes where it runs.
 *
 * Errors are surfaced as `ApiError` with the structured fields the API returns
 * (`code`, `message`, `detail`) so views can show a precise reason instead of a
 * generic failure.
 */

export class ApiError extends Error {
  constructor(status, payload) {
    const body = payload && payload.error ? payload.error : {};
    super(body.message || `request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code || 'unknown';
    this.detail = body.detail || '';
  }
}

const DEFAULT_TIMEOUT_MS = 30000;

async function request(path, { method = 'GET', body = null, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const contentType = response.headers.get('Content-Type') || '';
    const isJson = contentType.includes('json');
    const payload = isJson ? await response.json() : await response.text();
    if (!response.ok) {
      throw new ApiError(response.status, typeof payload === 'string' ? null : payload);
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === 'AbortError') {
      throw new ApiError(0, { error: { code: 'timeout', message: 'the request timed out' } });
    }
    throw new ApiError(0, {
      error: { code: 'network', message: 'could not reach the analysis API', detail: String(error.message || error) },
    });
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request('api/health'),
  language: () => request('api/language'),
  grammar: (mode = 'lalr') => request(`api/grammar?mode=${encodeURIComponent(mode)}`),
  schemas: () => request('api/schemas'),
  rules: () => request('api/rules'),
  examples: () => request('api/examples'),
  // Example ids are paths (`vulnerable/command_injection.ctc`): encode each
  // segment so names with spaces or other reserved characters still resolve,
  // while keeping the slashes the API routes on.
  example: (id) => {
    const path = String(id).split('/').map(encodeURIComponent).join('/');
    return request(`api/examples/${path}`);
  },
  analyze: (payload) => request('api/analyze', { method: 'POST', body: payload, timeoutMs: 60000 }),
  validateRules: (rules) => request('api/rules/validate', { method: 'POST', body: { rules } }),
  run: (id) => request(`api/runs/${id}`),
  findings: (id, query = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== '') params.set(key, value);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request(`api/runs/${id}/findings${suffix}`);
  },
  finding: (id, findingId) => request(`api/runs/${id}/findings/${findingId}`),
  findingSlice: (id, findingId) => request(`api/runs/${id}/findings/${findingId}/slice`),
  ast: (id) => request(`api/runs/${id}/ast`),
  cfg: (id, fn = null) => request(fn ? `api/runs/${id}/cfg?function=${encodeURIComponent(fn)}` : `api/runs/${id}/cfg`),
  dataflow: (id, fn, analysis) =>
    request(`api/runs/${id}/dataflow?function=${encodeURIComponent(fn)}&analysis=${encodeURIComponent(analysis)}`),
  statement: (id, sid) => request(`api/runs/${id}/statements/${sid}`),
  graph: (id, { kinds = [], limit = 4000 } = {}) => {
    const params = new URLSearchParams();
    if (kinds.length) params.set('kinds', kinds.join(','));
    params.set('limit', String(limit));
    return request(`api/runs/${id}/graph?${params.toString()}`);
  },
  slice: (id, sid, direction) =>
    request(`api/runs/${id}/slice?sid=${encodeURIComponent(sid)}&direction=${encodeURIComponent(direction)}`),
  reportUrl: (id, format) => `api/runs/${id}/report?format=${format}`,
  report: (id, format = 'json') => request(`api/runs/${id}/report?format=${format}`),
  compare: (before, after) => request('api/compare', { method: 'POST', body: { before, after } }),
};
