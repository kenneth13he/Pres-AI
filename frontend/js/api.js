// The one REST/WebSocket client. Names are the snake_case wire names from spec/contracts.py.
// With ?mock=1 (or when the API is unreachable) the pages fall back to frontend/mocks/.

const MOCK = new URLSearchParams(location.search).has('mock');

export class ApiError extends Error {
  constructor(status, detail, request) {
    const message = typeof detail === 'string' ? detail
      : typeof detail?.message === 'string' ? detail.message : '';
    super(`${request} → ${status}${message ? ` ${message}` : ''}`);
    this.status = status;
    this.code = typeof detail?.code === 'string' && /^[a-z0-9_]{1,80}$/.test(detail.code)
      ? detail.code : null;
  }
}

async function json(url, init) {
  const r = await fetch(url, init);
  if (!r.ok) {
    let body;
    try { body = await r.json(); } catch { /* Non-JSON response bodies are not user messages. */ }
    throw new ApiError(r.status, body?.detail, `${init?.method ?? 'GET'} ${url}`);
  }
  return r.json();
}

export async function getPresets() {
  if (MOCK) return (await json('/mocks/presets.json'));
  try { return await json('/api/presets'); }
  catch { return json('/mocks/presets.json'); }
}

export function uploadSlides(file) {
  const form = new FormData();
  form.append('file', file);
  return json('/api/slides', { method: 'POST', body: form });
}

export function createSession(config, custom_personas = []) {
  return json('/api/sessions', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ config, custom_personas }),
  });
}

export const getSession = (id) => json(`/api/sessions/${id}`);
export const getReport = (id) => MOCK ? json('/mocks/report.json') : json(`/api/sessions/${id}/report`);
export const control = (id, action) => json(`/api/sessions/${id}/control`, {
  method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ action }),
});
export const forceCurveball = (id, kind) => json(`/api/sessions/${id}/curveball`, {
  method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kind }),
});

/** Open the event stream. onEvent receives SessionEvent objects; returns {send, close}. */
export function connect(sessionId, onEvent, onStatus = () => {}) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/sessions/${sessionId}`);
  ws.onopen = () => onStatus('live');
  ws.onclose = () => onStatus('disconnected');
  ws.onerror = () => onStatus('error');
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  return {
    send: (msg) => ws.readyState === 1 && ws.send(JSON.stringify(msg)),
    close: () => ws.close(),
  };
}

export const isMock = () => MOCK;
