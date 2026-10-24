// The one REST/WebSocket client. Names are the snake_case wire names from spec/contracts.py.
// With ?mock=1 (or when the API is unreachable) the pages fall back to frontend/mocks/.

const MOCK = new URLSearchParams(location.search).has('mock');

async function json(url, init) {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${init?.method ?? 'GET'} ${url} → ${r.status} ${await r.text()}`);
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
