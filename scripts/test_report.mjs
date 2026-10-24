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
  assert.match(env.text('personas'), /Dana[\s\S]*Investor/);
  assert.match(env.text('personas'), /My reviewer[\s\S]*Methods skeptic/);
  const fallback = setup();
  await bootReport({ view: fallback.view, location: { search: '?session=abc' }, getReport: async () => copy(),
    getSession: async () => { throw new Error('Snapshot unavailable'); } });
  assert.equal(fallback.node('report-content').hidden, false);
  assert.match(fallback.text('personas'), /VC/);
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
