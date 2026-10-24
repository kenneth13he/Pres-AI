// Offline rendering/control tests. This fake DOM does not open or inspect a browser.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const portraits = await readFile(new URL('../frontend/js/portraits.js', import.meta.url), 'utf8');
const portraitUrl = `data:text/javascript;base64,${Buffer.from(portraits).toString('base64')}`;
const rooms = await readFile(new URL('../frontend/js/rooms.js', import.meta.url), 'utf8');
const roomsUrl = `data:text/javascript;base64,${Buffer.from(rooms).toString('base64')}`;
const source = (await readFile(new URL('../frontend/js/room_view.js', import.meta.url), 'utf8'))
  .replace("'./portraits.js'", `'${portraitUrl}'`)
  .replace("'./rooms.js'", `'${roomsUrl}'`);
const { createRoomView } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const { assignPortraits } = await import(portraitUrl);
const previewSource = (await readFile(new URL('../frontend/js/setup_preview.js', import.meta.url), 'utf8'))
  .replace("'./rooms.js'", `'${roomsUrl}'`);
const { createSetupPreview } = await import(`data:text/javascript;base64,${Buffer.from(previewSource).toString('base64')}`);
const controller = await readFile(new URL('../frontend/js/room_controller.js', import.meta.url), 'utf8');
const { bootRoom } = await import(`data:text/javascript;base64,${Buffer.from(controller).toString('base64')}`);

class FakeWindow {
  listeners = new Map();
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(handler);
  }
  removeEventListener(type, handler) { this.listeners.get(type)?.delete(handler); }
  emit(type) { for (const handler of [...(this.listeners.get(type) || [])]) handler(); }
}

class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName; this.children = []; this.dataset = {}; this.style = {};
    this.disabled = false; this.hidden = false; this.captures = new Set(); this.content = '';
    const classes = new Set();
    Object.defineProperty(this, 'className', { get: () => [...classes].join(' '),
      set: (value) => { classes.clear(); String(value).split(/\s+/).filter(Boolean).forEach((name) => classes.add(name)); } });
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle(name, force) {
        const value = force == null ? !classes.has(name) : force;
        if (value) classes.add(name); else classes.delete(name);
        return value;
      },
    };
  }
  set innerHTML(_) { throw new Error('Room content must use plain text, not HTML.'); }
  set textContent(value) { this.content = String(value ?? ''); this.children = []; }
  get textContent() { return this.content + this.children.map((child) => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.content = ''; this.children = [...children]; }
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { delete this[name]; }
  setPointerCapture(id) { this.captures.add(id); }
  hasPointerCapture(id) { return this.captures.has(id); }
  releasePointerCapture(id) {
    this.captures.delete(id);
    // Browsers dispatch this after release. Synchronous dispatch is a stricter regression
    // for clearing the held pointer before calling releasePointerCapture.
    this.onlostpointercapture?.({ pointerId: id });
  }
}

function find(node, className) {
  if (node.classList.contains(className)) return node;
  for (const child of node.children) { const result = find(child, className); if (result) return result; }
  return null;
}

function setup(snapshot = { config: { personas: [] }, preset: { name: 'Practice' } }) {
  const nodes = new Map(), window = new FakeWindow();
  const document = {
    defaultView: window, body: new Element('body'),
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id);
    },
    createElement: (name) => new Element(name),
  };
  const calls = { begin: 0, end: 0, discard: 0 };
  const noop = () => {};
  const view = createRoomView(document);
  view.bind({ start: noop, pause: noop, skip: noop, end: noop, restore: noop,
    previous: noop, next: noop, stopReply: noop,
    beginTurn() { calls.begin++; return true; },
    endTurn() { calls.end++; }, cancelTurn() { calls.discard++; },
  });
  view.configure(snapshot); view.phase('presenting');
  view.controls({ started: true, listening: true, canTalk: true, ptt: true,
    busy: false, pending: false, connecting: false, canPresent: true });
  const node = (id) => document.getElementById(id);
  const down = (id) => node('btn-talk').onpointerdown({ button: 0, pointerId: id, preventDefault() {} });
  const up = (id) => node('btn-talk').onpointerup({ pointerId: id });
  return { view, node, window, calls, down, up };
}

test('blur discards once and allows a new pointer hold after release outside the app', () => {
  const env = setup();
  env.down(1); assert.equal(env.calls.begin, 1);
  env.window.emit('blur'); env.window.emit('blur');
  assert.equal(env.calls.discard, 1);
  assert.equal(env.node('btn-talk').hasPointerCapture(1), false);
  assert.equal(env.node('btn-talk').textContent, 'Hold to talk');
  // Deliberately omit pointerup for 1: the mouse was released outside the application.
  env.down(2); assert.equal(env.calls.begin, 2);
  env.up(2); assert.equal(env.calls.end, 1);
  assert.equal(env.calls.discard, 1);
  env.view.dispose();
  assert.equal(env.window.listeners.get('blur').size, 0);
});

test('normal pointer release submits once and lost capture cannot discard that submission', () => {
  const env = setup();
  env.down(7); env.up(7);
  env.node('btn-talk').onlostpointercapture({ pointerId: 7 });
  assert.equal(env.calls.end, 1);
  assert.equal(env.calls.discard, 0);
  assert.equal(env.node('btn-talk').hasPointerCapture(7), false);
  env.view.dispose();
});

test('disabling controls while held discards and releases capture without submitting', () => {
  const env = setup();
  env.down(4); env.view.controls({ busy: true }); env.view.controls({ busy: true });
  assert.equal(env.calls.discard, 1);
  assert.equal(env.calls.end, 0);
  assert.equal(env.node('btn-talk').hasPointerCapture(4), false);
  env.view.controls({ busy: false }); env.down(5);
  assert.equal(env.calls.begin, 2);
  env.view.dispose();
  assert.equal(env.calls.discard, 2);
});

test('custom persona names and transcript markup remain literal text', () => {
  const name = '<img src=x onerror=alert(1)>', quote = '<script>untrusted words</script>';
  const env = setup({ config: { personas: [{ id: 'custom', name, role: 'Reviewer', custom: true }] } });
  const tiles = env.node('tiles').children;
  assert.equal(tiles.length, 1);
  assert.equal(find(tiles[0], 'seat-name').textContent, name);
  assert.equal(find(tiles[0], 'fiction-label').textContent, 'Custom · fictional');
  env.view.caption('custom', quote);
  assert.equal(env.node('captions').children[0].textContent, `${name}: ${quote}`);
  env.view.dispose();
});

test('deck slide selection uses its actual PNG and image failure reveals slide text', () => {
  const env = setup({ config: { personas: [] }, deck: { page_count: 2, slides: [
    { number: 1, text: 'Problem', image_url: '/decks/real-deck/1.png' },
    { number: 2, text: 'Evidence from our pilot', image_url: '/decks/real-deck/2.png' },
  ] } });
  env.view.slide(2);
  assert.equal(env.node('slide-img').src, '/decks/real-deck/2.png');
  assert.equal(env.node('slide-img').hidden, false);
  assert.equal(env.node('slide-no').textContent, 'Slide 2 / 2');
  assert.equal(env.node('slide-text').classList.contains('hidden'), true);
  env.node('slide-img').onerror();
  assert.equal(env.node('slide-img').hidden, true);
  assert.equal(env.node('slide-text').classList.contains('hidden'), false);
  assert.equal(env.node('slide-text').textContent, 'Evidence from our pilot');
  env.view.slide(99);
  assert.equal(env.node('slide-img').src, undefined);
  assert.equal(env.node('slide-img').hidden, true);
  assert.match(env.node('slide-text').textContent, /without slides/);
  env.view.dispose();
});

test('audience shares the table while the moderator has a separate host seat and labels stay explicit', () => {
  const env = setup({ config: { personas: [
    { id: 'vc', name: 'Dana', role: 'Skeptical VC' },
    { id: 'custom-1', name: 'A careful reviewer', role: 'Methods reviewer', custom: true },
  ] }, preset: { name: 'Research rehearsal' } });
  const host = env.node('host').children[0], people = env.node('tiles').children;
  assert.equal(env.node('host').children.length, 1); assert.equal(host.dataset.persona, 'moderator');
  assert.equal(find(host, 'seat-name').textContent, 'Moderator');
  assert.equal(find(host, 'fiction-label').textContent, 'Moderator voice');
  assert.equal(people.length, 2); assert.equal(people[0].dataset.persona, 'vc');
  assert.equal(find(people[0], 'fiction-label').textContent, 'Fictional audience member');
  assert.equal(find(people[1], 'fiction-label').textContent, 'Custom · fictional');
  assert.match(find(host, 'portrait-image').src, /^\/demo\/faces\/.+\.jpg$/);
  assert.match(find(people[0], 'portrait-image').src, /^\/demo\/faces\/.+\.jpg$/);
  assert.notEqual(host.dataset.character, people[0].dataset.character);
  env.view.dispose();
});

test('moderator captions and speaking cues work under host independently of persona bubbles', () => {
  const env = setup({ config: { personas: [{ id: 'vc', name: 'Dana', role: 'VC' }] } });
  const host = env.node('host').children[0], audience = env.node('tiles').children[0];
  const hostBubble = find(host, 'speech-bubble'), audienceBubble = find(audience, 'speech-bubble');
  env.view.caption('moderator', 'You have sixty seconds.', 'time_crunch');
  env.view.speaking('moderator');
  assert.equal(host.classList.contains('speaking'), true); assert.equal(hostBubble.hidden, false);
  assert.equal(find(host, 'bubble-text').textContent, 'You have sixty seconds.');
  assert.equal(find(host, 'bubble-tag').textContent, 'time crunch');
  assert.equal(audience.classList.contains('speaking'), false); assert.equal(audienceBubble.hidden, true);
  env.view.caption('vc', 'What supports that forecast?', 'follow-up'); env.view.speaking('vc');
  assert.equal(host.classList.contains('speaking'), false); assert.equal(hostBubble.hidden, true);
  assert.equal(audience.classList.contains('speaking'), true); assert.equal(audienceBubble.hidden, false);
  env.view.speaking(null);
  assert.equal(audience.classList.contains('speaking'), false); assert.equal(audienceBubble.hidden, true);
  env.view.speaking('vc');
  assert.equal(audienceBubble.hidden, false, 'Queued/deduplicated caption remains available when speech starts.');
  assert.equal(find(audience, 'bubble-text').textContent, 'What supports that forecast?');
  assert.equal(env.node('captions').children.length, 2, 'Speaker changes do not duplicate transcript rows.');
  env.view.dispose();
});

test('unavailable portraits show safe initials without losing the person or their fictional label', () => {
  const env = setup({ config: { personas: [{ id: 'vc', name: 'Dana Reviewer', role: 'VC' }] } });
  const person = env.node('tiles').children[0], image = find(person, 'portrait-image');
  const fill = find(person, 'portrait-fill'), fallback = find(person, 'portrait-fallback');
  assert.equal(fallback.hidden, true); assert.equal(image.alt, 'Dana Reviewer · fictional audience member');
  image.onerror();
  assert.equal(image.hidden, true); assert.equal(fill.hidden, true);
  assert.equal(fallback.hidden, false); assert.equal(fallback.textContent, 'DR');
  assert.equal(person.classList.contains('portrait-unavailable'), true);
  assert.equal(find(person, 'seat-name').textContent, 'Dana Reviewer');
  assert.equal(find(person, 'fiction-label').textContent, 'Fictional audience member');
  env.view.caption('vc', '<b>This remains literal.</b>');
  assert.equal(find(person, 'bubble-text').textContent, '<b>This remains literal.</b>');
  env.view.dispose();
});

test('static portrait layers use trusted local cast images and either failure reveals initials', () => {
  for (const failedLayer of ['portrait-image', 'portrait-fill']) {
    const env = setup({ config: { personas: [{ id: 'vc', name: 'Dana Reviewer', role: 'VC',
      image_url: 'https://untrusted.example/image.jpg', portrait: 'url(javascript:alert(1))',
    }] } });
    for (const person of [env.node('host').children[0], env.node('tiles').children[0]]) {
      const fill = find(person, 'portrait-fill'), image = find(person, 'portrait-image');
      assert.match(image.src, /^\/demo\/faces\/.+\.jpg$/);
      assert.equal(fill.src, image.src); assert.equal(fill.alt, '');
      assert.equal(fill['aria-hidden'], 'true', 'The fill must not repeat the accessible image description.');
      find(person, failedLayer).onerror();
      assert.equal(image.hidden, true); assert.equal(fill.hidden, true);
      assert.equal(find(person, 'portrait-fallback').hidden, false);
      env.view.speaking(person.dataset.persona);
      assert.equal(person.classList.contains('speaking'), true, 'A missing picture must not disable speaker feedback.');
    }
    env.view.dispose();
  }
});

test('portrait framing contains the whole static image and keeps labels and speaking cues above it', async () => {
  const html = await readFile(new URL('../frontend/room.html', import.meta.url), 'utf8');
  assert.match(html, /\.portrait-image\s*\{[^}]*object-fit:contain/);
  assert.match(html, /\.portrait-fill\s*\{[^}]*filter:blur\([^)]*\) brightness\(\.45\)/);
  assert.match(html, /\.portrait-image\s*\{[^}]*z-index:1/);
  assert.match(html, /\.seat-label\s*\{[^}]*z-index:2/);
  assert.match(html, /\.speaking-waves\s*\{[^}]*z-index:2/);
  assert.match(html, /prefers-reduced-motion:reduce/);
});

function previewEnvironment(portraits = assignPortraits) {
  const nodes = new Map(), document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id);
    },
    createElement: (name) => new Element(name),
  };
  const preview = createSetupPreview({ document, assignPortraits: portraits });
  const state = { audience: [{ id: 'vc', name: '<b>Dana Reviewer</b>',
    image_url: 'https://untrusted.example/image.jpg' }],
  options: { duration_minutes: 5, difficulty: 'standard', input_mode: 'push_to_talk' } };
  preview.render(state, 'video');
  return { tile: document.getElementById('preview-stage').children.find((child) => child.classList.contains('tile')) };
}

test('wizard preview preserves whole portraits, safe names and initials when either image layer fails', () => {
  for (const failedLayer of ['preview-portrait-image', 'preview-portrait-fill']) {
    const { tile } = previewEnvironment();
    const image = find(tile, 'preview-portrait-image'), fill = find(tile, 'preview-portrait-fill');
    assert.match(image.style, /object-fit:contain/); assert.match(fill.style, /filter:blur/);
    assert.match(image.src, /^\/demo\/faces\/.+\.jpg$/); assert.equal(fill.src, image.src);
    assert.equal(fill.alt, ''); assert.equal(fill['aria-hidden'], 'true');
    assert.equal(tile.children.at(-1).textContent, '<b>Dana Reviewer</b>');
    assert.match(tile.children.at(-1).style, /z-index:2/);
    assert.equal(find(tile, 'preview-portrait-fallback').hidden, true);
    find(tile, failedLayer).onerror();
    assert.equal(image.hidden, true); assert.equal(fill.hidden, true);
    assert.equal(find(tile, 'preview-portrait-fallback').hidden, false);
    assert.equal(tile.children.at(-1).textContent, '<b>Dana Reviewer</b>');
  }
  const { tile } = previewEnvironment(() => new Map());
  assert.equal(find(tile, 'preview-portrait-image'), null);
  assert.equal(find(tile, 'preview-portrait-fill'), null);
  assert.equal(find(tile, 'preview-portrait-fallback').hidden, false);
});

test('curveball states and ending preserve the live-room view contract', () => {
  const env = setup({ config: { personas: [{ id: 'vc', name: 'Dana', role: 'VC' }] } });
  const audience = env.node('tiles').children[0];
  env.view.curveball({ ui_effect: 'slides_black', line: 'Keep going without slides.' });
  assert.equal(env.node('slide-viewer').classList.contains('black'), true);
  assert.equal(env.node('btn-restore').classList.contains('hidden'), false);
  env.view.curveball({ ui_effect: 'tile_flash', persona_id: 'vc' });
  assert.equal(audience.classList.contains('flash'), true);
  env.view.curveball({ ui_effect: 'tiles_blank' }); assert.equal(audience.classList.contains('blank'), true);
  env.view.curveball(null);
  assert.equal(audience.classList.contains('blank'), false); assert.equal(audience.classList.contains('flash'), false);
  env.view.ended('/report.html?session=done');
  assert.equal(env.node('report-ready').hidden, false);
  assert.equal(env.node('report-link').href, '/report.html?session=done');
  env.view.dispose();
});

test('slide arrows stay available before presenting and while paused, then disable at report or disposal', () => {
  const env = setup();
  env.view.phase('setup');
  assert.equal(env.node('prev').disabled, false); assert.equal(env.node('next').disabled, false);
  env.view.phase('paused');
  assert.equal(env.node('prev').disabled, false); assert.equal(env.node('next').disabled, false);
  env.view.phase('report');
  assert.equal(env.node('prev').disabled, true); assert.equal(env.node('next').disabled, true);
  env.view.dispose();
  const leaving = setup(); leaving.view.dispose();
  assert.equal(leaving.node('prev').disabled, true); assert.equal(leaving.node('next').disabled, true);
});

test('new room markup retains hold, consent, errors and report controls without avatar or mute transports', async () => {
  const html = await readFile(new URL('../frontend/room.html', import.meta.url), 'utf8');
  const css = await readFile(new URL('../frontend/css/app.css', import.meta.url), 'utf8');
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'Control IDs must remain unique.');
  for (const id of ['host', 'tiles', 'captions', 'btn-talk', 'btn-stop-reply', 'ptt-hint',
    'audio-mode', 'audio-status', 'mic-consent', 'room-error', 'report-ready', 'report-link',
    'btn-end', 'btn-finish-session', 'qna-hint', 'conn']) {
    assert.ok(ids.includes(id), `Missing room contract element ${id}`);
  }
  assert.match(html, /Speech goes to Boson for transcription/);
  assert.match(html, /id="btn-finish-session"[^>]*aria-describedby="qna-hint"[^>]*hidden>Finish session early/);
  const sidebar = html.slice(html.indexOf('<aside'), html.indexOf('</aside>'));
  assert.match(sidebar, /id="btn-finish-session"/, 'Early finish is separate from the main header control.');
  assert.doesNotMatch(sidebar, /id="btn-end"/);
  assert.doesNotMatch(html, /<video\b/); assert.ok(!ids.includes('voice-on'));
  assert.match(css, /\[hidden\]\s*\{\s*display:\s*none\s*!important/);
  assert.doesNotMatch(css, /\.table-scene\s*\{[^}]*overflow:\s*hidden/);
});

test('replayed or queued captions stay hidden until their speaker actually speaks', () => {
  const env = setup({ config: { personas: [{ id: 'vc', name: 'Dana', role: 'VC' }] } });
  const person = env.node('tiles').children[0], bubble = find(person, 'speech-bubble');
  env.view.caption('vc', 'A question from session history.');
  assert.equal(bubble.hidden, true, 'History replay must not create a current speaking bubble.');
  env.view.caption('vc', 'The next queued question.');
  assert.equal(bubble.hidden, true);
  env.view.speaking('vc');
  assert.equal(bubble.hidden, false); assert.equal(find(person, 'bubble-text').textContent, 'The next queued question.');
  env.view.speaking(null); env.view.caption('vc', 'Another inactive caption.');
  assert.equal(bubble.hidden, true);
  env.view.speaking('vc');
  assert.equal(bubble.hidden, false); assert.equal(find(person, 'bubble-text').textContent, 'Another inactive caption.');
  env.view.dispose();
});

test('current room state distinguishes presenting, answering, active audience and frozen pause', () => {
  const env = setup({ config: { personas: [{ id: 'vc', name: 'Dana', role: 'VC' }] } });
  assert.equal(env.node('room-state').textContent, 'Your turn to present.');
  env.view.phase('answering'); assert.equal(env.node('room-state').textContent, 'Your turn to answer the audience.');
  env.view.speaking('vc'); assert.equal(env.node('room-state').textContent, 'Audience turn — listen to Dana.');
  env.view.phase('paused');
  assert.equal(env.node('room-state').textContent, 'Paused — timer frozen. Press Resume to continue.');
  assert.doesNotMatch(env.node('room-state').textContent, /Your turn/);
  env.view.speaking(null);
  assert.match(env.node('room-state').textContent, /Paused.*timer frozen/);
  env.view.notice('<b>Keep this literal.</b>');
  assert.equal(env.node('room-notice').textContent, '<b>Keep this literal.</b>');
  assert.equal(env.node('room-notice').hidden, false);
  env.view.dispose();
});

async function feedbackRoom(events = [], options = {}) {
  const snapshot = { session_id: 'feedback-room', phase: options.phase || 'answering', session_clock_ms: 10000,
    elapsed_ms: 10000, slide_number: 1, events,
    config: { input_mode: 'push_to_talk', personas: [
      { id: 'vc', name: 'Dana', role: 'VC' }, { id: 'student', name: 'Sam', role: 'Student' },
    ] }, preset: { name: 'Pitch rehearsal' } };
  const env = setup(snapshot), requests = [], sent = []; let onEvent, sequence = 20000;
  let inQna = snapshot.phase === 'qna' || events.some((event) => event.type === 'phase_changed' && event.payload?.to === 'qna');
  const emit = (type, payload) => onEvent({ type, payload, session_id: snapshot.session_id, timestamp_ms: sequence++ });
  const app = await bootRoom({ view: env.view, window: env.window,
    location: { search: '?session=feedback-room' }, now: () => 10000,
    getSession: async () => snapshot, isMock: () => false,
    createPlayer: () => ({ resume: async () => {}, close: async () => {}, cancel() {} }),
    connectVoice: options.connectVoice || (async () => { throw new Error('This feedback test must not open audio.'); }),
    connect(_id, event, status) {
      onEvent = event; queueMicrotask(() => status('live'));
      return { send(message) { sent.push(message); }, close() {} };
    },
    fetch: async (url, init = {}) => {
      if (url === '/health') return { json: async () => ({ adapters: { voice: 'higgs', orchestrator: 'mock' } }) };
      const { action } = JSON.parse(init.body); requests.push(action);
      if (action === 'skip') { emit('skipped', {}); emit('phase_changed', { to: 'presenting' }); }
      if (action === 'pause') emit('phase_changed', { to: 'paused' });
      let phase = action === 'pause' ? 'paused' : 'presenting';
      if (action === 'end') {
        phase = inQna ? 'report' : 'qna'; inQna = true;
        emit('phase_changed', { to: phase });
        if (phase === 'report') emit('session_ended', {});
      }
      return { ok: true, json: async () => ({ phase }) };
    },
    setInterval: () => 1, clearInterval() {},
  });
  return { ...env, app, requests, sent, emit };
}

test('actual Skip controller action shows explicit success while keeping transcript history, then Pause stays clear', async () => {
  const quote = 'Is this just another wrapper?', env = await feedbackRoom([
    { type: 'question_queued', timestamp_ms: 5000, payload: { persona_id: 'vc', question: quote } },
  ]);
  try {
    assert.equal(env.node('room-state').textContent, 'Your turn to answer the audience.');
    await env.node('btn-skip').onclick();
    assert.deepEqual(env.requests, ['skip']);
    assert.equal(env.node('room-notice').hidden, false);
    assert.equal(env.node('room-notice').textContent,
      'Question skipped. No penalty. The transcript keeps what was said.');
    assert.equal(env.node('room-state').textContent, 'Your turn to present.');
    assert.match(env.node('captions').textContent, /Is this just another wrapper\?/);
    assert.match(env.node('captions').textContent, /Skipped — carry on/);
    await env.node('btn-pause').onclick();
    assert.equal(env.node('room-state').textContent, 'Paused — timer frozen. Press Resume to continue.');
    assert.equal(env.node('btn-pause').textContent, 'Resume');
    assert.doesNotMatch(env.node('room-state').textContent, /Your turn/);
  } finally { await env.app.stop(); }
});

test('history does not show an old Skip success notice and fresh audience actions clear current notices', async () => {
  const env = await feedbackRoom([{ type: 'skipped', timestamp_ms: 4000, payload: {} }]);
  try {
    assert.equal(env.node('room-notice').hidden, true);
    assert.match(env.node('captions').textContent, /Skipped — carry on/, 'Past Skip remains part of history.');
    env.emit('skipped', {}); assert.equal(env.node('room-notice').hidden, false);
    env.emit('question_queued', { persona_id: 'vc', question: 'What evidence supports that?' });
    assert.equal(env.node('room-notice').hidden, true);
    env.emit('skipped', {}); env.emit('curveball_triggered', { ui_effect: 'slides_black', kind: 'slides_down' });
    assert.equal(env.node('room-notice').hidden, true);
    env.emit('skipped', {}); env.emit('session_ended', {});
    assert.equal(env.node('room-notice').hidden, true);
    assert.equal(env.node('room-state').textContent, 'Session finished. Open your report.');
  } finally { await env.app.stop(); }
});

test('End stays available during a Resume microphone wait but not after the closing command begins', () => {
  const env = setup(); env.view.phase('paused');
  env.view.controls({ pending: true, connecting: true, canEndWhileConnecting: true });
  assert.equal(env.node('btn-end').disabled, false);
  assert.equal(env.node('btn-pause').disabled, true); assert.equal(env.node('btn-skip').disabled, true);
  assert.match(env.node('room-state').textContent, /Paused.*timer frozen/);
  env.view.controls({ canEndWhileConnecting: false });
  assert.equal(env.node('btn-end').disabled, true);
  env.view.dispose();
});

test('restored closing-round context guards the primary button and exposes distinct early finish while paused', () => {
  const env = setup(); env.view.phase('paused');
  env.view.controls({ inQna: true });
  assert.equal(env.node('btn-end').textContent, 'Q&A in progress');
  assert.equal(env.node('btn-end').disabled, true);
  assert.equal(env.node('btn-finish-session').hidden, false);
  assert.equal(env.node('btn-finish-session').disabled, false);
  assert.match(env.node('qna-hint').textContent, /Q&A is paused\. Resume when ready/);
  env.view.controls({ pending: true, connecting: true, canEndWhileConnecting: true });
  assert.equal(env.node('btn-end').disabled, true, 'Reconnecting never reactivates the Q&A entry button.');
  assert.equal(env.node('btn-finish-session').disabled, false, 'Intentional End escape remains available.');
  env.view.controls({ canEndWhileConnecting: false });
  assert.equal(env.node('btn-finish-session').disabled, true, 'Closing command cannot be submitted twice.');
  env.view.controls({ pending: false }); env.view.phase('answering');
  assert.equal(env.node('btn-end').textContent, 'Q&A in progress');
  assert.equal(env.node('qna-hint').textContent,
    'Answer with Hold to talk. The report becomes ready automatically when Q&A is complete.');
  env.view.controls({ inQna: false }); env.view.phase('presenting');
  assert.equal(env.node('btn-end').textContent, 'End → Q&A');
  assert.equal(env.node('btn-end').disabled, false);
  assert.equal(env.node('btn-finish-session').hidden, true);
  assert.equal(env.node('qna-hint').hidden, true);
  env.view.dispose();
});

test('actual primary End starts Q&A once; repeat clicks cannot finish but distinct early finish can', async () => {
  const env = await feedbackRoom();
  try {
    assert.equal(env.node('btn-finish-session').hidden, true);
    await env.node('btn-finish-session').onclick();
    assert.deepEqual(env.requests, [], 'The hidden early-exit action is unavailable before Q&A.');
    const first = env.node('btn-end').onclick();
    const repeated = env.node('btn-end').onclick();
    await Promise.all([first, repeated]);
    assert.deepEqual(env.requests, ['end']);
    assert.equal(env.app.state.phase, 'qna');
    assert.equal(env.node('btn-end').textContent, 'Q&A in progress');
    assert.equal(env.node('btn-end').disabled, true);
    await env.node('btn-end').onclick();
    assert.deepEqual(env.requests, ['end'], 'A second click at the same position never ends Q&A.');
    assert.equal(env.node('btn-finish-session').hidden, false);
    await env.node('btn-finish-session').onclick();
    assert.deepEqual(env.requests, ['end', 'end']);
    assert.equal(env.app.state.phase, 'report');
    assert.equal(env.node('btn-end').disabled, true);
    assert.equal(env.node('btn-end').textContent, 'Session finished');
    assert.equal(env.node('btn-finish-session').hidden, true);
    assert.equal(env.node('btn-finish-session').disabled, true);
    assert.equal(env.node('qna-hint').hidden, true);
    await env.node('btn-end').onclick(); await env.node('btn-finish-session').onclick();
    assert.deepEqual(env.requests, ['end', 'end']);
  } finally { await env.app.stop(); }
});

test('paused Q&A early finish remains an intentional escape while Resume waits for audio', async () => {
  let resolveVoice, requested = false, stops = 0;
  const opening = new Promise((resolve) => { resolveVoice = resolve; });
  const env = await feedbackRoom([{ type: 'phase_changed', timestamp_ms: 1000, payload: { to: 'qna' } }], {
    phase: 'paused', connectVoice: () => { requested = true; return opening; },
  });
  const resume = env.node('btn-pause').onclick();
  try {
    for (let i = 0; i < 10 && !requested; i++) await Promise.resolve();
    assert.equal(requested, true);
    assert.equal(env.node('btn-end').disabled, true);
    assert.equal(env.node('btn-finish-session').hidden, false);
    assert.equal(env.node('btn-finish-session').disabled, false);
    await env.node('btn-finish-session').onclick();
    assert.equal(env.app.state.phase, 'report');
    resolveVoice({ stop: async () => { stops++; }, cancelTurn() {}, setPaused() {}, active: true, listening: true });
    await resume;
    assert.deepEqual(env.requests, ['end'], 'Finishing during reconnect never sends a late Resume.');
    assert.ok(stops >= 1);
    assert.equal(env.node('btn-finish-session').hidden, true);
  } finally {
    resolveVoice({ stop: async () => {}, cancelTurn() {}, setPaused() {}, active: true, listening: true });
    await resume; await env.app.stop();
  }
});

test('saved room setting changes the stage while authoritative personas and static portraits stay intact', () => {
  const previous = globalThis.sessionStorage;
  globalThis.sessionStorage = { getItem(key) {
    assert.equal(key, 'presai.session.designed-room');
    return JSON.stringify({ setting: 'boardroom', config: { personas: [{ id: 'stale', name: 'Stale guest' }] } });
  } };
  try {
    const env = setup({ session_id: 'designed-room', config: { preset_id: 'startup_pitch', personas: [
      { id: 'vc', name: 'Dana', role: 'Skeptical VC' },
      { id: 'student', name: 'Sam', role: 'Student' },
    ] } });
    assert.equal(env.node('room-setting').textContent, 'Boardroom');
    assert.equal(env.node('guest-count').textContent, '2 guests');
    assert.equal(env.node('slide-viewer').style.left, '32%');
    const people = env.node('tiles').children;
    assert.equal(people.length, 2);
    assert.deepEqual(people.map((person) => person.dataset.persona), ['vc', 'student']);
    assert.notEqual(people[0].style.left, people[1].style.left);
    for (const person of people) assert.match(find(person, 'portrait-image').src, /^\/demo\/faces\/.+\.jpg$/);
    env.view.dispose();
  } finally {
    if (previous === undefined) delete globalThis.sessionStorage; else globalThis.sessionStorage = previous;
  }
});

test('missing room metadata falls back to the preset layout and retains visible turn feedback', () => {
  const previous = globalThis.sessionStorage;
  globalThis.sessionStorage = { getItem() { return null; } };
  try {
    const env = setup({ session_id: 'new-room', config: { preset_id: 'class_presentation', personas: [
      { id: 'professor', name: 'Professor', role: 'Reviewer' },
    ] } });
    assert.equal(env.node('room-setting').textContent, 'Classroom');
    assert.equal(env.node('slide-viewer').style.left, '27%');
    assert.equal(env.node('guest-count').textContent, '1 guest');
    env.view.phase('recovering'); assert.equal(env.node('phase').classList.contains('hot'), true);
    env.view.phase('answering'); assert.equal(env.node('phase').classList.contains('hot'), false);
    assert.equal(env.node('phase').classList.contains('mint'), true);
    assert.equal(env.node('room-state').textContent, 'Your turn to answer the audience.');
    env.view.dispose();
  } finally {
    if (previous === undefined) delete globalThis.sessionStorage; else globalThis.sessionStorage = previous;
  }
});
