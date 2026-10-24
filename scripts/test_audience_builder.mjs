// Actual setup model/controller/view under deterministic seams. No browser or API calls.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { audienceSummary, buildSessionRequest, createSetupState, validateSetup }
  from '../frontend/js/setup_model.js';
import { createSetupController } from '../frontend/js/setup_controller.js';
import { createSetupView } from '../frontend/js/setup_view.js';
import { assignPortraits } from '../frontend/js/portraits.js';
import { createSetupWizard } from '../frontend/js/setup_wizard.js';
import { loadSetupProfiles } from '../frontend/js/setup_profiles.js';

const data = JSON.parse(await readFile(new URL('../frontend/mocks/presets.json', import.meta.url), 'utf8'));
const fresh = () => structuredClone(data);
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
};
function harness(overrides = {}) {
  const calls = [], uploads = [], routes = [];
  let latest;
  const controller = createSetupController({ data: fresh(), presetId: 'startup_pitch',
    view: { bind() {}, render(value) { latest = value; } },
    uploadSlides: async (file) => {
      uploads.push(file); return { deck_id: 'deck-a', page_count: 3 };
    },
    createSession: async (...args) => { calls.push(args); return { session_id: 'new-room' }; },
    navigate: (url) => routes.push(url), ...overrides });
  return { controller, calls, uploads, routes, get latest() { return latest; } };
}

test('presets serialize complete snake_case session requests with hold-to-talk by default', () => {
  for (const preset of data.presets) {
    const state = createSetupState(fresh(), preset.id), { config, custom_personas } = buildSessionRequest(state);
    assert.deepEqual(config.personas.map((person) => person.id), preset.personas);
    assert.equal(config.preset_id, preset.id);
    assert.equal(config.duration_target_s, preset.duration_target_s);
    assert.equal(config.input_mode, 'push_to_talk'); assert.equal(config.deck_id, null);
    assert.deepEqual(custom_personas, []);
    assert.deepEqual(Object.keys(config).sort(), ['curveballs', 'deck_id', 'difficulty',
      'duration_target_s', 'input_mode', 'interruption_frequency', 'personas', 'preset_id', 'qna_questions']);
  }
});

test('custom third seat never silently replaces a selected person or submits four seats', async () => {
  const run = harness(), { controller } = run;
  const original = [...controller.state.chosen];
  controller.custom('  a fictional thesis chair who asks for evidence  ');
  assert.deepEqual([...controller.state.chosen], original);
  assert.equal(run.latest.audience.length, 4); assert.match(run.latest.errors[0], /exactly two/);
  await controller.submit(); assert.equal(run.calls.length, 0);
  controller.choosePersona(original[2], false);
  assert.equal(run.latest.audience.length, 3); assert.deepEqual(run.latest.errors, []);
  await controller.submit();
  assert.deepEqual(run.calls[0][0].personas.map((person) => person.id), original.slice(0, 2));
  assert.deepEqual(run.calls[0][1], ['a fictional thesis chair who asks for evidence']);
  assert.equal(run.routes[0], '/room.html?session=new-room');
});

test('a custom person still requires two roster people; selection and skepticism stay faithful', () => {
  const run = harness({ presetId: 'custom' }), { controller } = run;
  controller.custom('A curious customer');
  const first = [...controller.state.chosen][0], other = [...controller.state.chosen][1];
  controller.choosePersona(other, false);
  assert.throws(() => buildSessionRequest(controller.state), /exactly two/);
  controller.choosePersona(other, true); controller.skepticism(first, '0.15');
  assert.equal(buildSessionRequest(controller.state).config.personas[0].skepticism, 0.15);
  assert.notEqual(data.personas.find((person) => person.id === first).skepticism, 0.15);
  controller.skepticism(first, 'not-a-number');
  assert.match(validateSetup(controller.state).join(' '), /Skepticism/);
  controller.skepticism(first, 0.5); controller.choosePersona('unknown-id', true);
  assert.equal(controller.state.chosen.size, 2);
});

test('curveball choose is limited to the preset, while Off/Surprise clear wire selections', () => {
  const run = harness(), { controller } = run;
  controller.option('curveball_mode', 'choose');
  const [keep, ...others] = controller.state.allowed;
  others.forEach((kind) => controller.curveball(kind, false));
  controller.curveball('not-in-catalogue', true);
  assert.deepEqual(buildSessionRequest(controller.state).config.curveballs, { mode: 'choose', kinds: [keep] });
  for (const mode of ['off', 'surprise']) {
    controller.option('curveball_mode', mode);
    assert.deepEqual(buildSessionRequest(controller.state).config.curveballs, { mode, kinds: [] });
  }
  controller.option('curveball_mode', 'choose'); controller.curveball(keep, false);
  assert.throws(() => buildSessionRequest(controller.state), /at least one/);
});

test('numeric and mode validation rejects invalid configurations before calling the backend', async () => {
  const run = harness(), { controller } = run;
  controller.option('duration_minutes', '1.5'); controller.option('qna_questions', '4');
  controller.option('input_mode', 'unsupported'); await controller.submit();
  assert.equal(run.calls.length, 0); assert.equal(run.latest.errors.length, 3);
  controller.option('duration_minutes', '5'); controller.option('qna_questions', '0');
  controller.option('input_mode', 'live');
  const config = buildSessionRequest(controller.state).config;
  assert.equal(config.duration_target_s, 300); assert.equal(config.qna_questions, 0);
  assert.equal(config.input_mode, 'live');
});

test('choosing a new failed file clears the old deck and requires an explicit remove/retry', async () => {
  const pending = deferred();
  const run = harness({ uploadSlides: async (file) => file.name === 'first.pdf'
    ? { deck_id: 'first-deck', page_count: 2 } : pending.promise });
  await run.controller.upload({ name: 'first.pdf' });
  assert.equal(buildSessionRequest(run.controller.state).config.deck_id, 'first-deck');
  const second = run.controller.upload({ name: 'second.pdf' });
  assert.equal(run.controller.state.deckId, null);
  await run.controller.submit(); assert.equal(run.calls.length, 0);
  pending.reject(new Error('private upstream response body')); await second;
  assert.equal(run.controller.state.deckId, null); assert.equal(run.latest.upload.status, 'error');
  assert.equal(run.latest.upload.message.includes('private'), false);
  await run.controller.submit(); assert.equal(run.calls.length, 0);
  await run.controller.upload(null); await run.controller.submit();
  assert.equal(run.calls[0][0].deck_id, null);
});

test('out-of-order upload successes/failures and removal never resurrect stale decks', async () => {
  const a = deferred(), b = deferred();
  const run = harness({ uploadSlides: (file) => file.name === 'a.pdf' ? a.promise : b.promise });
  const first = run.controller.upload({ name: 'a.pdf' });
  const second = run.controller.upload({ name: 'b.pdf' });
  b.resolve({ deck_id: 'newest', page_count: 4 }); await second;
  a.reject(new Error('stale failure')); await first;
  assert.equal(run.controller.state.deckId, 'newest'); assert.equal(run.latest.upload.status, 'ready');
  const late = deferred(), newer = deferred();
  const retry = harness({ uploadSlides: (file) => file.name === 'old.pdf' ? late.promise : newer.promise });
  const old = retry.controller.upload({ name: 'old.pdf' });
  const latest = retry.controller.upload({ name: 'new.pdf' });
  newer.reject(new Error('bad PDF')); await latest;
  late.resolve({ deck_id: 'old', page_count: 2 }); await old;
  assert.equal(retry.controller.state.deckId, null); assert.equal(retry.latest.upload.status, 'error');
  const cancelled = deferred(), clear = harness({ uploadSlides: () => cancelled.promise });
  const uploading = clear.controller.upload({ name: 'removed.pdf' });
  await clear.controller.upload(null); cancelled.resolve({ deck_id: 'removed', page_count: 1 });
  await uploading; assert.equal(clear.controller.state.deckId, null);
  assert.equal(clear.latest.upload.status, 'idle');
});

test('duplicate Start is coalesced, choices freeze during creation, and failures remain retryable', async () => {
  const pending = deferred(), calls = [], routes = [];
  const run = harness({ createSession: (...args) => { calls.push(args); return pending.promise; },
    navigate: (url) => routes.push(url) });
  const first = run.controller.submit(), second = run.controller.submit();
  run.controller.option('input_mode', 'live'); run.controller.custom('Too late');
  assert.equal(calls.length, 1); assert.equal(calls[0][0].input_mode, 'push_to_talk');
  assert.equal(run.controller.state.customDescription, '');
  pending.resolve({ session_id: 'room with spaces' }); await Promise.all([first, second]);
  assert.deepEqual(routes, ['/room.html?session=room%20with%20spaces']);
  let failures = 0;
  const retry = harness({ createSession: async () => { failures++; throw new Error('private vendor error'); } });
  await retry.controller.submit(); await retry.controller.submit();
  assert.equal(failures, 2); assert.equal(retry.controller.state.submitting, false);
  assert.equal(retry.latest.status.includes('private'), false);
});

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attributes = new Map(); this.classes = new Set();
    this.classList = { add: (...values) => values.forEach((value) => this.classes.add(value)),
      remove: (...values) => values.forEach((value) => this.classes.delete(value)),
      contains: (value) => this.classes.has(value),
      toggle: (value, force) => {
        const add = force ?? !this.classes.has(value);
        if (add) this.classes.add(value); else this.classes.delete(value); return add;
      } };
  }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get className() { return [...this.classes].join(' '); }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text ?? '') + this.children.map((child) => child.textContent).join(''); }
  set innerHTML(_) { throw new Error('Setup must render API strings with textContent.'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  click() { this.onclick?.(); }
}

async function setupDocument() {
  const html = await readFile(new URL('../frontend/setup.html', import.meta.url), 'utf8');
  const elements = new Map(), nodes = [];
  for (const [, tag, attributes] of html.matchAll(/<(\w+)\b([^>]*)>/g)) {
    const id = attributes.match(/\bid="([^"]+)"/)?.[1];
    if (!id) continue;
    const element = new FakeElement(tag); element.id = id;
    element.className = attributes.match(/\bclass="([^"]+)"/)?.[1] ?? '';
    elements.set(id, element);
  }
  const document = { getElementById: (id) => elements.get(id),
    createElement(tag) { const element = new FakeElement(tag); nodes.push(element); return element; } };
  return { html, elements, nodes, document };
}

test('real setup view uses text nodes for hostile names/descriptions and displays exact seat conflicts', async () => {
  const { html, elements, nodes, document } = await setupDocument();
  const hostile = '<img src=x onerror="unexpected()">';
  const choices = fresh(); choices.personas.find((person) => person.id === 'vc').name = hostile;
  const view = createSetupView({ document });
  const run = harness({ data: choices, view });
  assert.ok(elements.get('audience-summary').textContent.includes(hostile));
  assert.equal(nodes.some((node) => node.tagName === 'SCRIPT'), false);
  run.controller.custom(hostile);
  assert.equal(elements.get('seat-count').textContent, '4 requested · maximum 3');
  assert.equal(elements.get('start').disabled, true);
  run.controller.choosePersona('professor', false);
  assert.equal(elements.get('seat-count').textContent, '3 of 3 audience seats');
  assert.equal(elements.get('start').disabled, false);
  assert.ok(elements.get('audience-summary').textContent.includes('Custom · fictional'));
  elements.get('customise').click();
  assert.equal(elements.get('customise').attributes.get('aria-expanded'), 'true');
  assert.match(html, /value="push_to_talk" selected/);
  assert.match(elements.get('mic-consent').tagName, /P/);
});

test('selected roster portraits match the actual audience and broken images show initials', async () => {
  const { elements, document } = await setupDocument();
  const view = createSetupView({ document, assignPortraits });
  const run = harness({ presetId: 'job_interview', view });
  const walk = (element) => [element, ...element.children.flatMap(walk)];
  const images = (element) => walk(element).filter((node) => node.tagName === 'IMG');
  const matching = (root, id) => walk(root).find((node) => node.attributes.get('data-persona') === id);
  const expected = assignPortraits(audienceSummary(run.controller.state));
  for (const id of run.controller.state.chosen) {
    const summary = matching(elements.get('audience-summary'), id);
    const roster = matching(elements.get('roster'), id);
    assert.equal(images(summary)[0].src, expected.get(id).src);
    assert.equal(images(roster)[0].src, expected.get(id).src);
  }
  const unchecked = matching(elements.get('roster'), 'vc');
  assert.equal(images(unchecked).length, 0, 'Unchecked people should not borrow a seated identity.');
  const selectedId = [...run.controller.state.chosen][0];
  for (const root of [elements.get('audience-summary'), elements.get('roster')]) {
    const card = matching(root, selectedId), image = images(card)[0];
    image.onerror();
    assert.equal(images(card).length, 0);
    assert.ok(card.textContent.includes(run.controller.state.roster.get(selectedId).name[0]));
  }
});

function memoryStorage(initial = []) {
  const values = new Map([['presai.profiles', JSON.stringify(initial)]]);
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}
async function wizardHarness({ storage = memoryStorage(), initialProfile = '', ...overrides } = {}) {
  const env = await setupDocument(), routes = [];
  const view = createSetupWizard({ document: env.document,
    view: createSetupView({ document: env.document, assignPortraits }), assignPortraits,
    storage, presets: fresh().presets, initialProfile, navigate: (url) => routes.push(url) });
  return { ...env, ...harness({ view, ...overrides }), storage, profileRoutes: routes, view };
}

test('design wizard navigates real steps and blocks Continue until the current PDF is ready', async () => {
  const pending = deferred();
  const env = await wizardHarness({ uploadSlides: () => pending.promise });
  const el = (id) => env.elements.get(id);
  assert.equal(el('wizard-panel-0').hidden, false);
  assert.equal(el('wizard-step-4').disabled, true);
  el('wizard-step-4').click(); assert.equal(el('wizard-panel-4').hidden, true);
  el('profile-name').value = 'My research rehearsal'; el('profile-continue').click();
  assert.equal(el('wizard-panel-1').hidden, false);
  const upload = env.controller.upload({ name: 'research.pdf', size: 1200 });
  assert.equal(el('wizard-next-1').disabled, true);
  el('wizard-next-1').click(); assert.equal(el('wizard-panel-2').hidden, true);
  pending.resolve({ deck_id: 'new-design-deck', page_count: 3 }); await upload;
  assert.equal(el('wizard-next-1').disabled, false);
  el('wizard-next-1').click(); assert.equal(el('wizard-panel-2').hidden, false);
  assert.equal(el('profile-name').value, 'My research rehearsal');
  assert.equal(el('preview-input').textContent, 'Hold to talk');
  assert.equal(el('preview-stage').children.length, 4);
  el('wizard-next-2').click(); el('wizard-next-3').click();
  assert.equal(el('wizard-panel-4').hidden, false);
  await env.controller.submit();
  assert.equal(env.calls[0][0].input_mode, 'push_to_talk');
  assert.equal(env.calls[0][0].deck_id, 'new-design-deck');
});

test('saved design profiles restore safe preferences with hold-to-talk and no stale deck', async () => {
  const storage = memoryStorage(), env = await wizardHarness({ storage });
  const el = (id) => env.elements.get(id);
  const name = '<img src=x onerror="unexpected()">';
  el('profile-name').value = name;
  env.controller.option('duration_minutes', '7'); env.controller.option('qna_questions', '1');
  env.controller.option('input_mode', 'live');
  await env.controller.upload({ name: 'private-deck.pdf', size: 100 });
  el('save-profile').click();
  const profiles = loadSetupProfiles(storage);
  assert.equal(profiles.length, 1); assert.equal(profiles[0].name, name);
  assert.equal(profiles[0].options.input_mode, 'push_to_talk');
  assert.equal(profiles[0].options.duration_minutes, 7);
  assert.equal('deckId' in profiles[0], false); assert.equal('deck_id' in profiles[0], false);
  assert.equal(el('profiles').children[0].children[0].textContent, name);
  const restored = await wizardHarness({ storage, initialProfile: profiles[0].id });
  assert.equal(restored.controller.state.options.input_mode, 'push_to_talk');
  assert.equal(restored.controller.state.options.duration_minutes, 7);
  assert.equal(restored.controller.state.options.qna_questions, 1);
  assert.equal(restored.controller.state.deckId, null);
  assert.equal(restored.elements.get('wizard-panel-1').hidden, false);
});

test('malformed or unavailable profile storage cannot prevent a real rehearsal', async () => {
  for (const value of ['null', '{}', '"wrong type"', '{bad']) {
    assert.deepEqual(loadSetupProfiles({ getItem: () => value }), []);
  }
  const storage = { getItem() { throw new Error('private mode'); }, setItem() { throw new Error('quota'); } };
  const env = await wizardHarness({ storage });
  env.elements.get('save-profile').click();
  assert.match(env.elements.get('start-status').textContent, /could not save/);
  await env.controller.submit(); assert.equal(env.calls.length, 1);
});

test('restoring old or hostile profiles clamps seats, modes and curveballs to the current contract', () => {
  const env = harness();
  env.controller.profile({ chosen: ['unknown', 'vc', 'vc', 'student', 'professor'],
    customDescription: 'A fictional skeptical methods chair',
    skepticism: { vc: 3, student: 0.25 }, options: { input_mode: 'live', difficulty: 'evil',
      duration_minutes: 90, qna_questions: 20, curveball_mode: 'choose' },
    chosenCurveballs: ['not-supported'] });
  const { config, custom_personas } = buildSessionRequest(env.controller.state);
  assert.equal(config.input_mode, 'push_to_talk'); assert.equal(config.personas.length, 2);
  assert.equal(config.personas[1].skepticism, 0.25); assert.equal(config.difficulty, 'normal');
  assert.equal(config.duration_target_s, 180); assert.equal(config.qna_questions, 2);
  assert.equal(config.curveballs.mode, 'surprise'); assert.equal(custom_personas.length, 1);
});

test('all current presets remain reachable and unknown saved presets never redirect in a loop', async () => {
  const profile = { id: 'old-profile', name: 'Old', presetId: 'deleted-preset', chosen: ['vc', 'student'] };
  const env = await wizardHarness({ storage: memoryStorage([profile]), initialProfile: profile.id });
  assert.deepEqual(env.profileRoutes, []);
  const choice = env.elements.get('preset-choice');
  assert.deepEqual(choice.children.map((o) => o.value), [...data.presets.map((p) => p.id), 'custom']);
  choice.value = 'class_presentation'; choice.onchange();
  assert.deepEqual(env.profileRoutes, ['/setup.html?preset=class_presentation']);
  const classroom = await wizardHarness({ presetId: 'class_presentation' });
  assert.equal(classroom.elements.get('preset-choice').value, 'class_presentation');
  assert.equal(classroom.controller.state.options.duration_minutes, 5);
  assert.equal(classroom.elements.get('preview-room-name').textContent, 'Classroom');
  assert.equal(classroom.elements.get('pdf').classList.contains('hidden'), false);
  assert.match(classroom.html, /id="pdf"[^>]+class="sr-only"[^>]+aria-describedby="pdf-status"/);
});

test('opening setup as a file redirects to the working app while HTTP setup stays in place', async () => {
  const html = await readFile(new URL('../frontend/setup.html', import.meta.url), 'utf8');
  const inline = html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
  assert.ok(inline, 'File startup must work before any app module loads.');
  const replaced = [], attributes = new Map();
  const document = { documentElement: { setAttribute: (k, v) => attributes.set(k, v) } };
  const location = { protocol: 'file:', search: '?preset=research_defense', hash: '#slides',
    replace: (url) => replaced.push(url) };
  runInNewContext(inline, { window: { location }, document });
  assert.deepEqual(replaced, ['http://127.0.0.1:8000/setup.html?preset=research_defense#slides']);
  assert.equal(attributes.has('data-local-app'), false);
  location.protocol = 'http:';
  runInNewContext(inline, { window: { location }, document });
  assert.equal(replaced.length, 1); assert.equal(attributes.get('data-local-app'), 'true');
  assert.match(html, /id="file-open-help"[\s\S]*?href="http:\/\/127\.0\.0\.1:8000\/setup\.html"/);
});

test('Continue announces why it is blocked and focuses new headings only on step changes', async () => {
  const pending = deferred(), env = await wizardHarness({ uploadSlides: () => pending.promise });
  const el = (id) => env.elements.get(id), focus = [], scroll = [];
  for (const id of ['slides-heading', 'room-heading', 'title', 'pacing-heading']) {
    el(id).focus = () => focus.push(id);
  }
  env.document.defaultView = { scrollTo: (options) => scroll.push(options.top) };
  assert.equal(el('profile-continue').disabled, false);
  assert.match(el('wizard-hint-0').textContent, /optional/);
  el('profile-continue').click(); assert.deepEqual(focus, ['slides-heading']);
  const upload = env.controller.upload({ name: 'slides.pdf', size: 100 });
  assert.match(el('wizard-hint-1').textContent, /Reading your PDF/);
  assert.equal(el('wizard-next-1').attributes.get('aria-busy'), 'true');
  assert.deepEqual(focus, ['slides-heading'], 'Upload updates must not move keyboard focus.');
  pending.reject(new Error('unreadable')); await upload;
  assert.equal(el('wizard-next-1').disabled, true);
  assert.match(el('wizard-hint-1').textContent, /Remove the file or choose another PDF/);
  await env.controller.upload(null); assert.equal(el('wizard-next-1').disabled, false);
  assert.match(el('wizard-hint-1').textContent, /optional/);
  el('wizard-next-1').click(); assert.deepEqual(focus, ['slides-heading', 'room-heading']);
  env.controller.option('duration_minutes', 5);
  assert.deepEqual(focus, ['slides-heading', 'room-heading']); assert.deepEqual(scroll, [0, 0]);
  env.controller.custom('A fictional committee chair');
  assert.match(el('wizard-hint-3').textContent, /exactly two/);
  env.view.failed(); assert.equal(el('profile-continue').disabled, true);
  assert.match(el('wizard-hint-0').textContent, /could not load/);
});
