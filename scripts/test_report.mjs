// Pure Node tests of the actual report loader and DOM renderer. No browser or API calls.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

async function moduleAt(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  return import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
}
const { createReportView } = await moduleAt('../frontend/js/report_view.js');
const { bootReport, validateReport } = await moduleAt('../frontend/js/report_controller.js');
const fixture = JSON.parse(await readFile(new URL('../frontend/mocks/report.json', import.meta.url), 'utf8'));
const html = await readFile(new URL('../frontend/report.html', import.meta.url), 'utf8');

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName; this.children = []; this.attributes = {}; this.content = '';
    this.hidden = false; this.disabled = false;
  }
  set textContent(value) { this.content = String(value ?? ''); this.children = []; }
  get textContent() { return [this.content, ...this.children.map((child) => child.textContent)].join('\n'); }
  set innerHTML(_) { throw new Error('Untrusted report data must never be written as HTML.'); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.content = ''; this.children = [...children]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
}

function setup() {
  const nodes = new Map();
  // Only IDs that actually exist in report.html are available: rendering a mistyped or
  // missing composition target fails instead of silently inventing an element.
  for (const [, tag, attributes, id] of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const element = new Element(tag); element.hidden = /\bhidden(?:\s|>|$)/.test(attributes);
    nodes.set(id, element);
  }
  const document = { getElementById: (id) => nodes.get(id), createElement: (tag) => new Element(tag) };
  return { view: createReportView(document), node: (id) => nodes.get(id),
    text: (id) => nodes.get(id).textContent };
}
const copy = () => structuredClone(fixture);
const minimal = () => ({ session_id: 'unit', dimensions: {}, metrics: {} });
const tick = () => new Promise((resolve) => setImmediate(resolve));
const preparing = () => Object.assign(new Error('Your session has ended. Preparing feedback.'),
  { status: 409, code: 'report_preparing' });
class Clock {
  time = 0; next = 0; jobs = new Map();
  now = () => this.time;
  setTimeout = (callback, ms) => { const id = ++this.next; this.jobs.set(id, { callback, at: this.time + ms }); return id; };
  clearTimeout = (id) => this.jobs.delete(id);
  advance(ms) {
    this.time += ms;
    for (const [id, job] of [...this.jobs]) {
      if (job.at <= this.time) { this.jobs.delete(id); job.callback(); }
    }
  }
  options() { return { now: this.now, setTimeout: this.setTimeout, clearTimeout: this.clearTimeout }; }
}

test('actual mock report fixture renders every section and is explicitly illustrative', async () => {
  const env = setup(); let sessionLookups = 0;
  await bootReport({ view: env.view, location: { search: '?mock=1' }, getReport: async () => copy(),
    getSession: async () => { sessionLookups++; throw new Error('Mock must not query a live session.'); } });
  assert.equal(env.node('report-content').hidden, false);
  assert.equal(env.node('report-mode').hidden, false);
  assert.match(env.text('report-state'), /Illustrative/);
  assert.equal(env.node('dimensions').children.length, 5);
  assert.match(env.text('dimensions'), /71\/100/);
  assert.equal(env.node('metrics').children.length, 5);
  assert.equal(env.node('caveats').children.length, 2);
  assert.match(env.text('caveats'), /recognition accuracy/);
  assert.match(env.text('curveballs'), /3\.4 s/);
  assert.match(env.text('moments'), /00:04/);
  assert.match(env.text('strengths'), /Clearly explained the problem/);
  assert.match(env.text('improvements'), /100,000 customers/);
  assert.equal(env.node('personas').children.length, 3);
  assert.equal(sessionLookups, 0);
  assert.equal(env.node('report-shell').getAttribute('aria-busy'), 'false');
});

test('zero scores and measurements are distinct from unassessed or unmeasured values', () => {
  const env = setup(), report = minimal();
  report.overall_score = 0;
  report.dimensions = { clarity: null, evidence: 0 };
  report.metrics = { filler_words: 0, words_per_minute: null };
  report.curveballs = [
    { kind: 'slides_down', at_ms: 0, resolution: 'presenter_restored',
      recovery: { score: 0, resume_after_ms: 0 } },
    { kind: 'time_crunch', at_ms: 1000, resolution: 'timed_out', recovery: null },
  ];
  report.persona_feedback = [{ persona_id: 'vc', score: 0, comment: 'Measured result.' },
    { persona_id: 'student', score: null, comment: 'No assessment.' }];
  env.view.render(validateReport(report));
  assert.equal(env.text('overall-score').trim(), '0/100');
  assert.match(env.node('dimensions').children[0].textContent, /Not assessed/);
  assert.match(env.node('dimensions').children[1].textContent, /0\/100/);
  assert.match(env.text('metrics'), /Filler words: 0/);
  assert.match(env.text('metrics'), /Words per minute: Not measured/);
  assert.match(env.node('curveballs').children[0].textContent, /00:00[\s\S]*0\.0 s/);
  assert.match(env.node('curveballs').children[1].textContent, /Not assessed[\s\S]*Not measured/);
  assert.doesNotMatch(env.node('curveballs').children[1].textContent, /0\.0 s/);
  assert.match(env.node('personas').children[0].textContent, /0\/100/);
  assert.match(env.node('personas').children[1].textContent, /Not assessed/);
});

test('skipped curveballs have no penalty or rendered recovery score even with stale recovery data', () => {
  const env = setup(), report = minimal();
  report.curveballs = [{ kind: 'heckler', at_ms: 5000, resolution: 'skipped', recovery: {
    score: 0, resume_after_ms: 0, evidence: 'stale evidence must not appear',
    suggestion: 'stale penalty must not appear',
  } }];
  env.view.render(validateReport(report));
  assert.match(env.text('curveballs'), /Skipped — no penalty/);
  assert.doesNotMatch(env.text('curveballs'), /Recovery score|0\/100|0\.0 s|stale/);
});

test('malicious labels, evidence and persona names are literal text rather than markup', async () => {
  const env = setup(), report = copy(), malicious = '<img src=x onerror="alert(1)">';
  report.dimensions = { [malicious]: null };
  report.improvements[0].evidence = malicious;
  report.key_moments[0].summary = malicious;
  report.persona_feedback[0].comment = malicious;
  await bootReport({ view: env.view, location: { search: '?session=unit' },
    getReport: async () => report,
    getSession: async () => ({ config: { personas: [{ id: 'vc', name: malicious, role: 'Custom reviewer' }] } }),
  });
  for (const id of ['dimensions', 'improvements', 'moments', 'personas']) assert.ok(env.text(id).includes(malicious));
  const evidence = env.node('improvements').children[0].children.find((item) => item.tagName === 'blockquote');
  assert.equal(evidence.textContent.trim(), `“${malicious}”`);
  assert.equal(evidence.children.length, 0);
});

test('real session feedback resolves persona names and gracefully falls back without its snapshot', async () => {
  const env = setup();
  await bootReport({ view: env.view, location: { search: '?session=abc' }, getReport: async () => copy(),
    getSession: async () => ({ config: { personas: [{ id: 'vc', name: 'Dana', role: 'Investor' },
      { id: 'custom_1', name: 'My reviewer', role: 'Methods skeptic' }] } }),
  });
  await tick(); // Optional persona names can arrive just after the completed report is visible.
  assert.match(env.text('personas'), /Dana[\s\S]*Investor/);
  assert.match(env.text('personas'), /My reviewer[\s\S]*Methods skeptic/);
  const fallback = setup();
  await bootReport({ view: fallback.view, location: { search: '?session=abc' }, getReport: async () => copy(),
    getSession: async () => { throw new Error('Snapshot unavailable'); } });
  assert.equal(fallback.node('report-content').hidden, false);
  assert.match(fallback.text('personas'), /VC/);
});

test('a valid report is ready even if its optional persona lookup is still pending', async () => {
  const env = setup(); let resolve;
  const details = new Promise((done) => { resolve = done; });
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' },
    getReport: async () => copy(), getSession: () => details });
  await tick();
  const wasReady = !env.node('report-content').hidden;
  const wasBusy = env.node('report-shell').getAttribute('aria-busy');
  resolve({ config: { personas: [{ id: 'vc', name: 'Dana', role: 'Investor' }] } });
  await loading; await tick();
  assert.equal(wasReady, true, 'Optional names must not hold a completed report behind Loading.');
  assert.equal(wasBusy, 'false');
  assert.match(env.text('personas'), /Dana/);
  assert.equal(env.node('personas').children.length, 3, 'Enrichment replaces rather than duplicates cards.');
});

test('late optional persona results cannot overwrite a newer report reload', async () => {
  const env = setup(); let resolve, count = 0;
  const stale = new Promise((done) => { resolve = done; });
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' },
    getReport: async () => copy(), getSession: () => ++count === 1 ? stale
      : Promise.resolve({ config: { personas: [{ id: 'vc', name: 'Current Dana' }] } }) });
  await tick();
  if (env.node('report-content').hidden) {
    resolve(null); // Let the old implementation exit instead of leaving this regression hanging.
  }
  const app = await loading;
  await app.reload(); await tick();
  resolve({ config: { personas: [{ id: 'vc', name: 'Outdated Dana' }] } }); await tick();
  assert.match(env.text('personas'), /Current Dana/);
  assert.doesNotMatch(env.text('personas'), /Outdated Dana/);
});

test('loading is accessible and a missing session does not issue a report request', async () => {
  const env = setup(); let resolve;
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' },
    getReport: () => new Promise((done) => { resolve = done; }) });
  assert.equal(env.node('report-shell').getAttribute('aria-busy'), 'true');
  assert.equal(env.node('report-state').getAttribute('role'), 'status');
  assert.equal(env.node('report-content').hidden, true);
  resolve(copy()); await loading;
  assert.equal(env.node('report-shell').getAttribute('aria-busy'), 'false');
  const missing = setup(); let calls = 0;
  await bootReport({ view: missing.view, location: { search: '' }, getReport: () => { calls++; } });
  assert.equal(calls, 0);
  assert.match(missing.text('report-state'), /Choose a session/);
  assert.equal(missing.node('back-room').hidden, true);
  assert.equal(missing.node('new-session').href, '/');
});

test('unfinished reports offer the room and retry successfully without duplicate rendering', async () => {
  const env = setup(); let calls = 0;
  await bootReport({ view: env.view, location: { search: '?session=a%2Fb' }, getReport: async () => {
    if (++calls === 1) throw Object.assign(new Error('HTTP 409'), { status: 409 });
    return copy();
  } });
  assert.match(env.text('report-state'), /still in progress/);
  assert.equal(env.node('back-room').href, '/room.html?session=a%2Fb');
  assert.equal(env.node('retry-report').hidden, false);
  assert.equal(env.node('report-content').hidden, true);
  await env.node('retry-report').onclick();
  assert.equal(env.node('report-content').hidden, false);
  assert.equal(env.node('dimensions').children.length, 5);
  assert.equal(env.node('retry-report').hidden, true);
});

test('only ended-session preparing responses poll, then render automatically without waiting for names', async () => {
  const env = setup(), clock = new Clock(); let calls = 0;
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' }, ...clock.options(),
    getReport: async () => { if (++calls < 3) throw preparing(); return copy(); },
    getSession: () => new Promise(() => {}),
  });
  await tick();
  assert.equal(calls, 1); assert.match(env.text('report-state'), /session has ended.*Preparing feedback/);
  assert.doesNotMatch(env.text('report-state'), /Finish Q&A|still in progress/);
  assert.equal(env.node('report-shell').getAttribute('aria-busy'), 'true');
  clock.advance(999); await tick(); assert.equal(calls, 1);
  clock.advance(1); await tick(); assert.equal(calls, 2);
  clock.advance(1000); await loading;
  assert.equal(calls, 3); assert.equal(env.node('report-content').hidden, false);
  assert.equal(env.node('report-shell').getAttribute('aria-busy'), 'false');
  assert.equal(clock.jobs.size, 0);
});

test('ordinary unfinished reports and unrelated preparing-looking errors never auto-poll', async () => {
  for (const error of [Object.assign(new Error('session not finished'), { status: 409 }),
    Object.assign(new Error('report_preparing is unavailable'), { status: 503, code: 'report_preparing' }),
    Object.assign(new Error('Upstream 409 report_preparing'), { status: 503, code: 'report_preparing' })]) {
    const env = setup(), clock = new Clock(); let calls = 0;
    await bootReport({ view: env.view, location: { search: '?session=abc' }, ...clock.options(),
      getReport: async () => { calls++; throw error; } });
    clock.advance(45000); await tick();
    assert.equal(calls, 1); assert.equal(clock.jobs.size, 0);
    assert.equal(env.node('retry-report').hidden, false);
  }
});

test('preparing polling has a deadline, exposes Retry and a later retry can succeed', async () => {
  const env = setup(), clock = new Clock(); let calls = 0, ready = false;
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' },
    ...clock.options(), maxWaitMs: 3000,
    getReport: async () => { calls++; if (!ready) throw preparing(); return copy(); },
  });
  await tick();
  for (let i = 0; i < 3; i++) { clock.advance(1000); await tick(); }
  await loading;
  assert.equal(calls, 3);
  assert.match(env.text('report-state'), /session has ended.*still being prepared.*Try again/);
  assert.equal(env.node('retry-report').hidden, false);
  assert.equal(clock.jobs.size, 0);
  ready = true; await env.node('retry-report').onclick();
  assert.equal(env.node('report-content').hidden, false);
});

test('Retry cancels an older preparing wait and stale responses cannot replace the new report', async () => {
  const env = setup(), clock = new Clock(); let mode = 'ready', resolve;
  const app = await bootReport({ view: env.view, location: { search: '?session=abc' }, ...clock.options(),
    getReport: () => {
      if (mode === 'preparing') return Promise.reject(preparing());
      if (mode === 'held') return new Promise((done) => { resolve = done; });
      return { ...copy(), strengths: [mode] };
    },
  });
  mode = 'preparing'; const waiting = app.reload(); await tick();
  mode = 'current'; await app.reload(); await waiting;
  assert.equal(clock.jobs.size, 0); assert.match(env.text('strengths'), /current/);
  mode = 'held'; const stale = app.reload();
  mode = 'newest'; await app.reload();
  resolve({ ...copy(), strengths: ['outdated'] }); await stale;
  assert.match(env.text('strengths'), /newest/); assert.doesNotMatch(env.text('strengths'), /outdated/);
  assert.equal(clock.jobs.size, 0);
});

test('a hung report request cannot outlive the preparing deadline or update after disposal', async () => {
  const env = setup(), clock = new Clock(); let calls = 0, resolve;
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' },
    ...clock.options(), maxWaitMs: 3000, getReport: () => {
      if (++calls === 1) return Promise.reject(preparing());
      return new Promise((done) => { resolve = done; });
    },
  });
  await tick(); clock.advance(1000); await tick();
  clock.advance(2000); const app = await loading;
  assert.match(env.text('report-state'), /Feedback is still being prepared/);
  assert.equal(clock.jobs.size, 0);
  app.dispose(); const message = env.text('report-state');
  resolve(copy()); await tick();
  assert.equal(env.text('report-state'), message); assert.equal(env.node('report-content').hidden, true);
});

test('leaving during initial report preparation cancels polling before boot returns', async () => {
  const env = setup(), clock = new Clock(), page = new AbortController(); let calls = 0;
  const loading = bootReport({ view: env.view, location: { search: '?session=abc' },
    ...clock.options(), signal: page.signal,
    getReport: async () => { calls++; throw preparing(); },
  });
  await tick(); const message = env.text('report-state');
  page.abort(); const app = await loading;
  clock.advance(60000); await tick(); await app.reload();
  assert.equal(calls, 1); assert.equal(clock.jobs.size, 0);
  assert.equal(env.text('report-state'), message);
});

test('missing, network and incomplete reports expose useful safe errors', async () => {
  const env404 = setup();
  await bootReport({ view: env404.view, location: { search: '?session=missing' },
    getReport: async () => { throw new Error('GET report → 404 private response'); } });
  assert.match(env404.text('report-state'), /could not be found/);
  const network = setup();
  await bootReport({ view: network.view, location: { search: '?session=abc' },
    getReport: async () => { throw new Error('private response <script>'); } });
  assert.match(network.text('report-state'), /local app is running/);
  assert.doesNotMatch(network.text('report-state'), /private|script/);
  assert.equal(network.node('report-state').getAttribute('role'), 'alert');
  assert.equal(network.node('retry-report').hidden, false);
  const incomplete = setup();
  await bootReport({ view: incomplete.view, location: { search: '?session=abc' },
    getReport: async () => ({ session_id: 'abc', metrics: {}, dimensions: null }) });
  assert.match(incomplete.text('report-state'), /incomplete/);
  assert.equal(incomplete.node('report-content').hidden, true);
});

test('minimal valid reports show honest empty states without invented measurements', () => {
  const env = setup(); env.view.render(validateReport(minimal()));
  assert.match(env.text('overall-score'), /Not assessed/);
  assert.match(env.text('curveballs'), /No curveball fired/);
  assert.match(env.text('moments'), /No key moments/);
  assert.match(env.text('improvements'), /No specific improvements/);
  assert.match(env.text('personas'), /No audience feedback/);
  assert.throws(() => validateReport({ ...minimal(), metrics: { fillers: 'not a number' } }), /incomplete/);
});
