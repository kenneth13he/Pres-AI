// Real room-controller behavior with deterministic view/voice/network seams.
// No browser automation, microphone access, or vendor requests.
// Run: node --test scripts/test_presentation_room.mjs.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../frontend/js/room_controller.js', import.meta.url), 'utf8');
const { bootRoom } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((r, fail) => { resolve = r; reject = fail; });
  return { promise, resolve, reject };
};
function session(overrides = {}) {
  return {
    session_id: 'room-test', phase: 'setup', session_clock_ms: 0, elapsed_ms: 0, events: [],
    config: { input_mode: 'push_to_talk', duration_target_s: 180, qna_questions: 2,
      curveballs: { mode: 'surprise', kinds: [] }, personas: [
      { id: 'vc', name: 'Dana', role: 'Skeptical VC', custom: false },
      { id: 'student', name: 'Alex', role: 'Student', custom: false },
    ] },
    preset: { id: 'startup_pitch', name: 'Startup Pitch' },
    deck: { deck_id: 'deck-test', page_count: 2, slides: [
      { number: 1, text: 'Problem', image_url: '/data/decks/deck-test/1.png' },
      { number: 2, text: 'Solution', image_url: '/data/decks/deck-test/2.png' },
    ] },
    ...overrides,
  };
}
function environment({ saved = session(), mock = false, liveVoice = true,
  healthFailure = false, healthReply = null } = {}) {
  const calls = [], sent = [], requests = [], views = {}, listeners = new Map(), intervals = new Map();
  const voiceInstances = [], voiceOptions = [];
  let handlers, onEvent, onBusStatus, now = 10000, nextTimer = 0, nextTurn = 0;
  let failMicrophone = false, holdMicrophone = null, holdConnection = null, serverPhase = saved.phase, resumePhase = 'presenting', controlReply = null;
  const view = { bind(value) { handlers = value; } };
  for (const name of ['configure', 'phase', 'connection', 'audio', 'error', 'meter',
    'speaking', 'caption', 'slide', 'curveball', 'timer', 'ended', 'dispose', 'notice']) {
    view[name] = (...args) => { (views[name] ??= []).push(args); calls.push(`view:${name}`); };
  }
  view.controls = (value) => {
    views.currentControls = { ...views.currentControls, ...value };
    (views.controls ??= []).push([value]);
  };
  const player = {
    resumed: 0, cancelled: 0, closed: 0,
    async resume() { this.resumed++; calls.push('player:resume'); },
    cancel() { this.cancelled++; calls.push('player:cancel'); },
    async close() { this.closed++; calls.push('player:close'); },
    enqueue() {}, whenIdle: async () => {},
  };
  const link = {
    closed: false,
    send(data) { sent.push(data); calls.push(`send:${data.type}`); return true; },
    close() { this.closed = true; calls.push('bus:close'); },
  };
  const deps = {
    view, location: { search: '?session=room-test', protocol: 'http:', host: 'localhost:8000' },
    window: {
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener(name) { listeners.delete(name); },
    },
    now: () => now, isMock: () => mock,
    setInterval(callback) { const id = ++nextTimer; intervals.set(id, callback); return id; },
    clearInterval(id) { intervals.delete(id); },
    createPlayer: () => player,
    getSession: async () => structuredClone(saved),
    connect(_id, eventCallback, statusCallback) {
      calls.push('bus:connect');
      onEvent = eventCallback; onBusStatus = statusCallback;
      queueMicrotask(() => statusCallback('live'));
      return link;
    },
    async playMock(_name, eventCallback) {
      onEvent = eventCallback;
      return { ...link, config: saved.config, preset: saved.preset };
    },
    async fetch(url, init = {}) {
      calls.push(`fetch:${url}`);
      requests.push({ url, ...init, body: init.body ? JSON.parse(init.body) : undefined });
      if (url === '/health' && healthFailure) throw new Error('Health metadata unavailable.');
      if (url === '/health' && healthReply) return healthReply.promise;
      if (url.endsWith('/control')) {
        const action = JSON.parse(init.body).action;
        serverPhase = ({ pause: 'paused', resume: resumePhase, end: 'qna' })[action] ?? serverPhase;
      }
      return { ok: true, json: async () => url === '/health'
        ? { adapters: { voice: liveVoice ? 'higgs' : 'mock', stt: 'higgs', llm: 'mock' } }
        : controlReply ? controlReply.promise : { phase: serverPhase } };
    },
    async connectVoice(options) {
      calls.push('voice:connect'); voiceOptions.push(options);
      const voice = {
        active: true, listening: false, held: false, paused: false, speaking: false,
        stopped: 0, cancelled: 0, discarded: 0,
        async startListening() {
          calls.push('voice:listen');
          if (holdMicrophone) await holdMicrophone.promise;
          if (failMicrophone) throw new Error('Microphone permission denied.');
          this.listening = true; options.onListeningState?.(true);
        },
        beginTurn() {
          if (!this.active || !this.listening || this.paused || this.speaking || this.held) return false;
          if (options.canBeginTurn && !options.canBeginTurn()) return false;
          this.held = true; this.turnId = `capture-${++nextTurn}`;
          options.onTurnStart?.(this.turnId); return true;
        },
        endTurn() {
          if (!this.held) return false;
          this.held = false; options.onTurnEnd?.(this.turnId); return true;
        },
        cancelTurn() {
          calls.push('voice:discard'); this.discarded++;
          if (this.held) options.onTurnDiscard?.(this.turnId);
          this.held = false;
        },
        setPaused(value) { calls.push(`voice:paused:${value}`); this.paused = value; },
        cancel() { this.cancelled++; calls.push('voice:cancel'); this.held = false; },
        async stop() {
          this.stopped++; this.active = false; this.listening = false;
          calls.push('voice:stop'); options.onListeningState?.(false);
        },
      };
      voiceInstances.push(voice);
      if (holdConnection) await holdConnection.promise;
      return voice;
    },
  };
  return {
    deps, views, sent, requests, calls, listeners, intervals, player, link, voiceInstances, voiceOptions,
    get handlers() { return handlers; }, get voice() { return voiceInstances.at(-1); },
    get options() { return voiceOptions.at(-1); },
    advance(ms) { now += ms; }, failMicrophone(value) { failMicrophone = value; },
    holdMicrophone(value) { holdMicrophone = value; },
    holdConnection(value) { holdConnection = value; },
    resumeTo(value) { resumePhase = value; },
    holdControlReply(value) { controlReply = value; },
    event(type, payload = {}, timestamp_ms = 0) {
      if (type === 'phase_changed') serverPhase = payload.to;
      return onEvent({ type, payload, timestamp_ms, session_id: 'room-test' });
    },
    busStatus(status) { onBusStatus(status); },
    controls() { return requests.filter((r) => r.url.endsWith('/control')); },
    messages(type) { return sent.filter((message) => message.type === type); },
    latest(name) { return views[name]?.at(-1); },
  };
}

test('room loads its real session/deck and defaults to held speech without starting the mic', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    assert.equal(env.voiceInstances.length, 0);
    assert.equal(env.messages('presentation_started').length, 0);
    assert.equal(env.latest('configure')[0].deck.slides[1].image_url,
      '/data/decks/deck-test/2.png');
    assert.equal(env.latest('slide')[0], 1);
    assert.equal(env.views.currentControls.ptt, true);
    assert.equal(env.views.currentControls.listening, false);
    assert.equal(typeof env.handlers.beginTurn, 'function');
  } finally { await app.stop(); }
});

test('a failed room lookup releases the player and its page listener', async () => {
  const env = environment();
  env.deps.getSession = async () => { throw new Error('Session not found.'); };
  await assert.rejects(bootRoom(env.deps), /Session not found/);
  assert.equal(env.player.closed, 1); assert.equal(env.listeners.has('pagehide'), false);
  assert.equal(env.calls.includes('bus:connect'), false); assert.equal(env.intervals.size, 0);
});

test('a room snapshot arriving after navigation cannot configure or connect the disposed room', async () => {
  const env = environment(), snapshot = deferred();
  env.deps.getSession = () => snapshot.promise;
  const opening = bootRoom(env.deps);
  await env.listeners.get('pagehide')();
  snapshot.resolve(session()); const app = await opening;
  assert.equal(app.state.disposed, true); assert.equal(env.player.closed, 1);
  assert.equal(env.calls.includes('bus:connect'), false); assert.equal(env.views.configure, undefined);
  assert.equal(env.intervals.size, 0);
});

test('optional health failure cannot stop a valid room from connecting and starting', async () => {
  const env = environment({ healthFailure: true,
    saved: session({ reasoning: { adapter: 'boson' } }) });
  const app = await bootRoom(env.deps);
  try {
    await tick();
    assert.equal(env.calls.filter((call) => call === 'bus:connect').length, 1);
    assert.match(env.latest('connection')[0], /live Boson audience/);
    await env.handlers.start();
    assert.equal(env.messages('presentation_started').length, 1);
  } finally { await app.stop(); }
});

test('a hung health lookup cannot block room readiness or overwrite a later audio status', async () => {
  const health = deferred(), env = environment({ healthReply: health });
  let ready = false;
  const opening = bootRoom(env.deps).then((value) => { ready = true; return value; });
  await tick(); const wasReady = ready;
  const response = { json: async () => ({ adapters: { voice: 'mock', orchestrator: 'mock' } }) };
  if (!wasReady) health.resolve(response); // Release a regressed loader before asserting.
  const app = await opening;
  try {
    assert.equal(wasReady, true, 'A valid room must not await optional provider metadata.');
    await env.handlers.start();
    const status = env.latest('audio')[0]; health.resolve(response); await tick();
    assert.equal(env.latest('audio')[0], status);
    assert.match(status, /Microphone ready/);
  } finally { await app.stop(); }
});

test('a saved finished room exposes its report without live event or voice connections', async () => {
  const env = environment({ saved: session({ phase: 'report' }) });
  env.deps.connect = () => { throw new Error('A saved report must not open a live socket.'); };
  const app = await bootRoom(env.deps);
  try {
    assert.equal(app.state.phase, 'report');
    assert.equal(env.voiceInstances.length, 0);
    assert.deepEqual(env.latest('ended'), ['/report.html?session=room-test']);
    assert.match(env.latest('connection')[0], /Session finished/);
    assert.equal(env.intervals.size, 0);
  } finally { await app.stop(); }
});

test('late events cannot reopen a finished room or mutate a disposed view', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
  env.event('phase_changed', { to: 'report' });
  env.event('phase_changed', { to: 'answering' }, 4);
  env.event('ai_speech_started', { speaker: 'vc', line: 'Late question' }, 5);
  env.event('session_ended', {}, 6);
  assert.equal(app.state.phase, 'report');
  assert.equal(app.state.busy, false);
  assert.deepEqual(env.latest('ended'), ['/report.html?session=room-test']);
  assert.equal(env.views.currentControls.canTalk, false);
  await app.stop();
  const before = JSON.stringify(env.views);
  env.event('phase_changed', { to: 'presenting' }, 10);
  env.event('transcript_segment', { text: 'late transcript' }, 11);
  env.busStatus('live');
  assert.equal(JSON.stringify(env.views), before);
  assert.equal(app.state.phase, 'report');
});

test('slide navigation works before presenting and while paused, then stale handlers stop at report or disposal', async () => {
  for (const terminal of ['report', 'dispose']) {
    const env = environment(), app = await bootRoom(env.deps);
    try {
      env.handlers.next(); assert.equal(app.state.slide, 2);
      env.event('phase_changed', { to: 'paused' });
      env.handlers.previous(); assert.equal(app.state.slide, 1);
      if (terminal === 'report') env.event('phase_changed', { to: 'report' });
      else await app.stop();
      const slides = env.views.slide.length, sent = env.messages('slide_changed').length;
      env.handlers.next(); env.handlers.previous();
      assert.equal(app.state.slide, 1);
      assert.equal(env.views.slide.length, slides, `${terminal}: stale handlers cannot update the slide.`);
      assert.equal(env.messages('slide_changed').length, sent, `${terminal}: stale handlers cannot send a slide change.`);
    } finally { await app.stop(); }
  }
});

test('Start waits for microphone readiness before starting presentation/session time', async () => {
  const env = environment(), ready = deferred(); env.holdMicrophone(ready);
  const app = await bootRoom(env.deps);
  try {
    const starting = env.handlers.start(); await tick();
    assert.equal(env.messages('presentation_started').length, 0);
    assert.equal(app.state.startedAt, null);
    env.advance(5000); ready.resolve(); await starting;
    assert.equal(env.options.pushToTalk, true);
    assert.equal(env.messages('presentation_started').length, 1);
    assert.ok(env.calls.indexOf('voice:listen') < env.calls.indexOf('send:presentation_started'));
    assert.equal(env.messages('slide_changed')[0].slide_number, 1);
    assert.equal(env.views.currentControls.listening, true);
  } finally { await app.stop(); }
});

test('microphone failure leaves session unstarted and allows a clean retry', async () => {
  const env = environment(); env.failMicrophone(true);
  const app = await bootRoom(env.deps);
  try {
    await env.handlers.start();
    assert.equal(env.messages('presentation_started').length, 0);
    assert.equal(app.state.startedAt, null);
    assert.ok(env.latest('error')[0]);
    assert.ok(env.voice.stopped > 0);
    env.failMicrophone(false); await env.handlers.start();
    assert.equal(env.messages('presentation_started').length, 1);
    assert.equal(env.voiceInstances.length, 2);
  } finally { await app.stop(); }
});

test('reconnecting voice in a running session preserves elapsed time and sends no second start', async () => {
  const env = environment({ saved: session({ phase: 'presenting', session_clock_ms: 42000,
    elapsed_ms: 42000 }) });
  const app = await bootRoom(env.deps);
  try {
    app.tick(); const before = env.latest('timer')[0].elapsed_ms;
    assert.equal(before, 42000);
    await env.handlers.start(); env.advance(3000); app.tick();
    assert.equal(env.messages('presentation_started').length, 0);
    assert.equal(env.latest('timer')[0].elapsed_ms, 45000);
    env.voice.active = false; env.options.onListeningState(false);
    await env.handlers.start(); env.advance(2000); app.tick();
    assert.equal(env.messages('presentation_started').length, 0);
    assert.equal(env.latest('timer')[0].elapsed_ms, 47000);
  } finally { await app.stop(); }
});

test('held speech start/end and delayed final transcript retain the same turn id', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
    env.handlers.beginTurn(); env.advance(4000);
    assert.equal(env.messages('presenter_turn_started').length, 1);
    assert.equal(env.messages('presenter_turn_ended').length, 0);
    env.handlers.endTurn();
    const first = env.messages('presenter_turn_started')[0];
    const last = env.messages('presenter_turn_ended')[0];
    assert.equal(first.turn_id, last.turn_id);
    const segment = { start_ms: 0, end_ms: 4000, text: 'Our product reduces onboarding time.' };
    env.options.onSegment(segment, first.turn_id);
    const transcript = env.messages('transcript_segment').at(-1);
    assert.equal(transcript.turn_id, first.turn_id);
    assert.deepEqual(transcript.segment, segment);
  } finally { await app.stop(); }
});

test('an empty or discarded final transcript restores held-speech controls immediately', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
    assert.equal(env.views.currentControls.canTalk, true);
    env.handlers.beginTurn(); env.handlers.endTurn();
    const turnId = env.messages('presenter_turn_ended').at(-1).turn_id;
    assert.equal(env.views.currentControls.canTalk, false);
    env.options.onTurnDiscard(turnId);
    assert.equal(app.state.transcribing, false);
    assert.equal(env.views.currentControls.canTalk, true,
      'Discard callbacks must refresh the visible hold button, not only internal state.');
    assert.equal(env.handlers.beginTurn(), true);
  } finally { await app.stop(); }
});

test('keyboard capture predicate obeys room phases and busy state without cancelling a question', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
    assert.equal(typeof env.options.canBeginTurn, 'function');
    assert.equal(env.options.canBeginTurn(), true);
    const marker = env.calls.length, cancelCount = env.voice.cancelled;
    env.event('phase_changed', { to: 'interruption' });
    assert.equal(env.options.canBeginTurn(), false);
    assert.equal(env.voice.beginTurn(), false, 'Direct keyboard entry must use the same predicate.');
    assert.equal(env.voice.paused, false, 'Interruption must not pause/cancel normal question playback.');
    assert.equal(env.voice.cancelled, cancelCount);
    assert.equal(env.calls.slice(marker).includes('voice:paused:true'), false);
    env.event('phase_changed', { to: 'answering' });
    assert.equal(env.options.canBeginTurn(), true);
    env.options.onSpeaking(true); assert.equal(env.options.canBeginTurn(), false);
    assert.equal(env.voice.beginTurn(), false);
    env.options.onSpeaking(false); assert.equal(env.options.canBeginTurn(), true);
    env.event('phase_changed', { to: 'paused' }); assert.equal(env.options.canBeginTurn(), false);
    env.event('phase_changed', { to: 'report' }); assert.equal(env.options.canBeginTurn(), false);
  } finally { await app.stop(); }
  assert.equal(env.options.canBeginTurn(), false);
});

for (const terminal of ['stop', 'report']) {
  test(`a voice connection resolving after ${terminal} closes without opening the microphone`, async () => {
    const env = environment(), connectionReady = deferred();
    env.holdConnection(connectionReady);
    const app = await bootRoom(env.deps);
    const starting = env.handlers.start(); await tick();
    assert.equal(env.voiceInstances.length, 1);
    assert.equal(env.calls.filter((call) => call === 'voice:listen').length, 0);
    if (terminal === 'stop') await app.stop();
    else env.event('phase_changed', { to: 'report' });
    connectionReady.resolve(); await starting;
    assert.equal(env.calls.filter((call) => call === 'voice:listen').length, 0,
      'A stale returned connection must be rejected before startListening.');
    assert.ok(env.voice.stopped > 0);
    assert.equal(env.voice.listening, false);
    assert.equal(app.state.audioReady, false);
    assert.equal(env.messages('presentation_started').length, 0);
    await app.stop();
  });
}

test('Pause discards local capture before REST and the displayed session clock freezes', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
    env.advance(3000); app.tick(); env.handlers.beginTurn();
    const marker = env.calls.length; await env.handlers.pause();
    const calls = env.calls.slice(marker);
    const restAt = calls.findIndex((call) => call.includes('/control'));
    assert.ok(restAt > calls.indexOf('voice:discard'));
    assert.ok(restAt > calls.indexOf('voice:cancel'));
    assert.equal(env.controls().at(-1).body.action, 'pause');
    env.event('phase_changed', { to: 'paused' }); app.tick();
    const frozen = env.latest('timer')[0].elapsed_ms;
    env.advance(9000); app.tick(); assert.equal(env.latest('timer')[0].elapsed_ms, frozen);
    await env.handlers.pause(); assert.equal(env.controls().at(-1).body.action, 'resume');
    env.event('phase_changed', { to: 'presenting' }); env.advance(2000); app.tick();
    assert.equal(env.latest('timer')[0].elapsed_ms, frozen + 2000);
  } finally { await app.stop(); }
});

test('cancelled final transcripts cannot cross Skip/Pause, while a later turn still forwards', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
    for (const action of ['skip', 'pause']) {
      env.handlers.beginTurn(); env.handlers.endTurn();
      const cancelledId = env.messages('presenter_turn_ended').at(-1).turn_id;
      await env.handlers[action]();
      if (action === 'pause') {
        env.event('phase_changed', { to: 'paused' });
        await env.handlers.pause(); env.event('phase_changed', { to: 'presenting' });
      }
      const count = env.messages('transcript_segment').length;
      env.options.onSegment({ start_ms: 0, end_ms: 500, text: 'Cancelled old transcript.' }, cancelledId);
      assert.equal(env.messages('transcript_segment').length, count);
    }
    env.handlers.beginTurn(); env.handlers.endTurn();
    const currentId = env.messages('presenter_turn_ended').at(-1).turn_id;
    env.options.onSegment({ start_ms: 500, end_ms: 1000, text: 'Current presentation.' }, currentId);
    assert.equal(env.messages('transcript_segment').at(-1).segment.text, 'Current presentation.');
  } finally { await app.stop(); }
});

test('Skip and End discard capture before REST; End keeps the microphone for Q&A', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'presenting' });
    for (const [handler, action] of [['skip', 'skip'], ['end', 'end']]) {
      const marker = env.calls.length; env.handlers.beginTurn(); await env.handlers[handler]();
      const calls = env.calls.slice(marker), restAt = calls.findIndex((call) => call.includes('/control'));
      assert.ok(calls.indexOf('voice:discard') >= 0 && calls.indexOf('voice:discard') < restAt);
      assert.ok(calls.indexOf('voice:cancel') >= 0 && calls.indexOf('voice:cancel') < restAt);
      assert.equal(env.controls().at(-1).body.action, action);
    }
    env.event('phase_changed', { to: 'qna' });
    assert.equal(env.voice.stopped, 0);
    assert.equal(env.voice.active, true); assert.equal(env.player.closed, 0);
    assert.equal(env.views.currentControls.listening, true);
  } finally { await app.stop(); }
});

test('live events update persona/moderator speech, captions, slide and curveball effects', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  try {
    await env.handlers.start();
    env.event('ai_speech_started', { speaker: 'vc', line: 'What evidence supports that claim?' });
    assert.equal(env.latest('speaking')[0], 'vc');
    assert.match(env.latest('caption')[1], /What evidence/);
    env.event('ai_speech_ended', { speaker: 'vc' }); assert.equal(env.latest('speaking')[0], null);
    env.event('ai_speech_started', { speaker: 'moderator', line: 'You have one minute left.' });
    assert.equal(env.latest('speaking')[0], 'moderator');
    env.event('transcript_segment', { text: 'Here is our evidence.' });
    assert.equal(env.latest('caption')[1], 'Here is our evidence.');
    env.event('slide_changed', { slide_number: 2 }); assert.equal(env.latest('slide')[0], 2);
    const curveball = { kind: 'slides_down', ui_effect: 'slides_black', line: 'Keep going.' };
    env.event('curveball_triggered', curveball); assert.deepEqual(env.latest('curveball')[0], curveball);
    env.event('curveball_resolved', { kind: 'slides_down' }); assert.equal(env.latest('curveball')[0], null);
  } finally { await app.stop(); }
});

test('session ending closes voice and playback and exposes the report link', async () => {
  const env = environment(), app = await bootRoom(env.deps);
  await env.handlers.start();
  env.event('phase_changed', { to: 'report' });
  env.event('session_ended', { report_url: '/report.html?session=room-test' }); await tick();
  assert.ok(env.voice.stopped > 0); assert.ok(env.player.closed > 0);
  assert.equal(env.latest('ended')[0], '/report.html?session=room-test');
  assert.equal(env.views.currentControls.listening, false);
  await app.stop(); assert.equal(env.link.closed, true); assert.equal(env.intervals.size, 0);
});

test('room mock mode stays explicit and never opens a real microphone', async () => {
  const env = environment({ mock: true }), app = await bootRoom(env.deps);
  try {
    assert.equal(env.voiceInstances.length, 0);
    assert.equal(env.views.currentControls.canPresent, false);
    assert.match(env.latest('connection')[0], /mock/i);
  } finally { await app.stop(); }
});

test('setup selects push-to-talk by default and retains an explicit live option', async () => {
  const html = await readFile(new URL('../frontend/setup.html', import.meta.url), 'utf8');
  const select = html.match(/<select\b[^>]*\bid="input-mode"[^>]*>([\s\S]*?)<\/select>/)?.[1];
  assert.ok(select, 'Input mode selector must exist.');
  const selected = [...select.matchAll(/<option\b([^>]*)>/g)]
    .map((match) => match[1]).filter((attributes) => /\bselected\b/.test(attributes));
  assert.equal(selected.length, 1);
  assert.match(selected[0], /\bvalue="push_to_talk"/);
  assert.match(select, /\bvalue="live"/);
});

test('Resume from a paused snapshot connects microphone before REST and keeps the paused clock frozen', async () => {
  const env = environment({ saved: session({ phase: 'paused', session_clock_ms: 95000,
    elapsed_ms: 60000, timer_remaining_ms: 22000 }) }), ready = deferred();
  env.holdMicrophone(ready); const app = await bootRoom(env.deps), clockOrigin = app.state.startedAt;
  let resuming;
  try {
    resuming = env.handlers.pause(); await tick();
    assert.equal(env.controls().length, 0, 'Do not resume the backend before the microphone is ready.');
    assert.equal(env.voiceInstances.length, 1); assert.equal(app.state.phase, 'paused');
    env.advance(5000); app.tick();
    assert.equal(env.latest('timer')[0].elapsed_ms, 60000);
    assert.equal(env.latest('timer')[0].remaining_ms, 22000);
    ready.resolve(); await resuming;
    assert.deepEqual(env.controls().map((request) => request.body.action), ['resume']);
    assert.ok(env.calls.indexOf('voice:listen') < env.calls.findIndex((call) => call.includes('/control')));
    assert.equal(app.state.startedAt, clockOrigin); assert.equal(env.messages('presentation_started').length, 0);
    assert.equal(app.state.audioReady, true); assert.equal(app.state.phase, 'presenting');
    env.advance(2000); app.tick(); assert.equal(env.latest('timer')[0].elapsed_ms, 62000);
  } finally { ready.resolve(); await resuming; await app.stop(); }
});

test('Resume reconnects audio closed by the idle limit while the session was paused', async () => {
  const env = environment({ saved: session({ phase: 'presenting', session_clock_ms: 42000,
    elapsed_ms: 42000 }) }), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); env.event('phase_changed', { to: 'paused' });
    env.voice.active = false; env.voice.listening = false; env.options.onListeningState(false);
    assert.equal(app.state.audioReady, false);
    await env.handlers.pause();
    assert.equal(env.voiceInstances.length, 2); assert.equal(app.state.audioReady, true);
    assert.equal(env.voice.listening, true); assert.equal(env.controls().at(-1).body.action, 'resume');
    assert.equal(env.messages('presentation_started').length, 0);
  } finally { await app.stop(); }
});

test('failed Resume microphone readiness sends no resume and leaves a retryable paused session', async () => {
  const env = environment({ saved: session({ phase: 'paused', elapsed_ms: 42000 }) }), app = await bootRoom(env.deps);
  try {
    env.failMicrophone(true); await env.handlers.pause();
    assert.equal(env.controls().length, 0); assert.equal(app.state.phase, 'paused');
    assert.equal(app.state.pending, false); assert.equal(app.state.connecting, false);
    assert.match(env.latest('error')[0], /still paused/i); assert.match(env.latest('error')[0], /Resume/i);
    env.advance(5000); app.tick(); assert.equal(env.latest('timer')[0].elapsed_ms, 42000);
    env.failMicrophone(false); await env.handlers.pause();
    assert.deepEqual(env.controls().map((request) => request.body.action), ['resume']);
    assert.equal(env.voiceInstances.length, 2); assert.equal(app.state.audioReady, true);
  } finally { await app.stop(); }
});

for (const terminal of ['stop', 'report']) {
  test(`Resume opening audio cannot send a delayed resume after ${terminal}`, async () => {
    const env = environment({ saved: session({ phase: 'paused', elapsed_ms: 42000 }) }), ready = deferred();
    env.holdConnection(ready); const app = await bootRoom(env.deps);
    const resuming = env.handlers.pause(); await tick();
    try {
      assert.equal(env.controls().length, 0); assert.equal(env.voiceInstances.length, 1);
      if (terminal === 'stop') await app.stop(); else env.event('phase_changed', { to: 'report' });
      ready.resolve(); await resuming;
      assert.equal(env.controls().length, 0); assert.equal(env.calls.includes('voice:listen'), false);
      assert.equal(env.messages('presentation_started').length, 0); assert.equal(app.state.audioReady, false);
    } finally { ready.resolve(); await resuming; await app.stop(); }
  });
}

test('End supersedes a Resume still opening audio instead of resuming after the closing command', async () => {
  const env = environment({ saved: session({ phase: 'paused' }) }), ready = deferred();
  env.holdConnection(ready); const app = await bootRoom(env.deps);
  let resuming;
  try {
    resuming = env.handlers.pause(); await tick();
    assert.equal(env.views.currentControls.canEndWhileConnecting, true);
    const ending = env.handlers.end(), repeatedEnd = env.handlers.end();
    assert.equal(env.views.currentControls.canEndWhileConnecting, false);
    await Promise.all([ending, repeatedEnd]);
    ready.resolve(); await resuming;
    assert.deepEqual(env.controls().map((request) => request.body.action), ['end']);
    assert.equal(app.state.phase, 'qna'); assert.equal(env.messages('presentation_started').length, 0);
  } finally { ready.resolve(); await resuming; await app.stop(); }
});

test('Resume joins an existing reconnect and repeated Resume/reconnect create one microphone and one control', async () => {
  const env = environment({ saved: session({ phase: 'paused' }) }), ready = deferred();
  env.holdMicrophone(ready); const app = await bootRoom(env.deps);
  let reconnecting, resuming, repeatedResume, repeatedReconnect;
  try {
    reconnecting = env.handlers.start(); await tick();
    resuming = env.handlers.pause(); repeatedResume = env.handlers.pause(); repeatedReconnect = env.handlers.start();
    await tick(); assert.equal(env.controls().length, 0); assert.equal(env.voiceInstances.length, 1);
    ready.resolve(); await Promise.all([reconnecting, resuming, repeatedResume, repeatedReconnect]);
    assert.equal(env.voiceInstances.length, 1);
    assert.deepEqual(env.controls().map((request) => request.body.action), ['resume']);
    assert.equal(env.messages('presentation_started').length, 0);
  } finally { ready.resolve(); await Promise.all([reconnecting, resuming, repeatedResume, repeatedReconnect]); await app.stop(); }
});

test('a normal ready Resume retains its audio connection', async () => {
  const env = environment({ saved: session({ phase: 'paused' }) }), app = await bootRoom(env.deps);
  try {
    await env.handlers.start(); assert.equal(env.voiceInstances.length, 1);
    await env.handlers.pause();
    assert.equal(env.voiceInstances.length, 1); assert.equal(env.voice.stopped, 0);
    assert.equal(env.controls().at(-1).body.action, 'resume');
  } finally { await app.stop(); }
});

test('paused Q&A reload restores the closing-round context through reconnect and Resume', async () => {
  const env = environment({ saved: session({ phase: 'paused', events: [
    { type: 'phase_changed', timestamp_ms: 60000, payload: { to: 'qna' } },
    { type: 'phase_changed', timestamp_ms: 61000, payload: { to: 'answering' } },
    { type: 'phase_changed', timestamp_ms: 65000, payload: { to: 'paused' } },
  ] }) }); env.resumeTo('answering'); const app = await bootRoom(env.deps);
  try {
    assert.equal(app.state.inQna, true); assert.equal(env.views.currentControls.inQna, true);
    await env.handlers.pause();
    assert.equal(app.state.phase, 'answering'); assert.equal(env.views.currentControls.inQna, true);
    assert.equal(env.voiceInstances.length, 1); assert.equal(env.messages('presentation_started').length, 0);
  } finally { await app.stop(); }
});

test('a lost room connection during Resume readiness cannot unpause the backend', async () => {
  const env = environment({ saved: session({ phase: 'paused' }) }), ready = deferred();
  env.holdMicrophone(ready); const app = await bootRoom(env.deps);
  let resuming;
  try {
    resuming = env.handlers.pause(); await tick(); env.busStatus('disconnected');
    ready.resolve(); await resuming;
    assert.equal(env.controls().length, 0); assert.equal(app.state.phase, 'paused');
    assert.match(env.latest('error')[0], /still paused/i);
  } finally { ready.resolve(); await resuming; await app.stop(); }
});

for (const terminal of ['stop', 'report']) {
  test(`an old Resume response cannot reopen the phase after ${terminal}`, async () => {
    const env = environment({ saved: session({ phase: 'paused' }) }), reply = deferred();
    const app = await bootRoom(env.deps); let resuming;
    try {
      await env.handlers.start(); env.holdControlReply(reply);
      resuming = env.handlers.pause(); await tick();
      assert.equal(env.controls().length, 1, 'This race occurs after readiness and the actual Resume POST.');
      if (terminal === 'stop') await app.stop(); else env.event('phase_changed', { to: 'report' });
      reply.resolve({ phase: 'answering' }); await resuming;
      assert.equal(app.state.phase, terminal === 'report' ? 'report' : 'paused');
      assert.equal(app.state.audioReady, false);
    } finally { reply.resolve({ phase: 'answering' }); await resuming; await app.stop(); }
  });
}

test('a late failed Resume response cannot replace the completed report with a stale control error', async () => {
  const env = environment({ saved: session({ phase: 'paused' }) }), reply = deferred();
  const app = await bootRoom(env.deps); let resuming;
  try {
    await env.handlers.start(); env.holdControlReply(reply);
    resuming = env.handlers.pause(); await tick();
    env.event('phase_changed', { to: 'report' });
    const errors = env.views.error.length;
    reply.reject(new Error('Expired old resume request.')); await resuming;
    assert.equal(app.state.phase, 'report'); assert.equal(env.views.error.length, errors);
  } finally { reply.resolve({ phase: 'answering' }); await resuming; await app.stop(); }
});
