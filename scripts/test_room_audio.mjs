// Real split bridge + STT controller under deterministic microphone/socket substitutes.
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
const dataModule = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const read = (name) => readFile(new URL(`../frontend/js/${name}`, import.meta.url), 'utf8');
const vad = dataModule(await read('voice_vad.js'));
const realtime = dataModule((await read('realtime.js'))
  .replace("import { startMic } from './mic.js';", 'const startMic = (...args) => globalThis.roomTestMic(...args);')
  .replace("'./voice_vad.js'", `'${vad}'`));
const { connectVoice } = await import(dataModule((await read('voice.js'))
  .replace("'/js/realtime.js'", `'${realtime}'`)));
const { startMic } = await import(dataModule(await read('mic.js')));
function environment({ pushToTalk = true, canBeginTurn = () => true } = {}) {
  const sockets = [], signals = [], states = [], trace = [], segments = [], statuses = [];
  const listeners = new Map(); let callbacks, now = 1000, micCalls = 0;
  const mic = { active: true, enabled: true, held: false,
    beginTurn() {
      if (!this.active || !this.enabled || this.held || callbacks.canBeginTurn?.() === false) return false;
      this.held = true; callbacks.onTurnStart?.(); return true;
    },
    endTurn() {
      if (!this.held || !this.active) return false;
      this.held = false; callbacks.onCommit(); return true;
    },
    cancelTurn() {
      if (!this.held || !this.active) return false;
      this.held = false; callbacks.onDiscard(); return true;
    },
    setEnabled(value) { this.enabled = value; if (!value) this.held = false; },
    stop() { this.active = false; this.enabled = false; this.held = false; },
  };
  globalThis.roomTestMic = async (options) => { callbacks = options; micCalls++; return mic; };
  globalThis.window = { addEventListener: (n,c) => listeners.set(n,c), removeEventListener: (n) => listeners.delete(n) };
  globalThis.location = { protocol: 'http:', host: 'localhost:8000' };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ value: 'temporary-room-test',
    url: 'wss://room-test.invalid', config: { type: 'session.update', session: {
      model: 'higgs-realtime', audio: { input: { turn_detection: null } },
    } } }) });
  globalThis.WebSocket = class {
    static OPEN = 1;
    constructor(url, protocols) {
      this.url = url; this.protocols = protocols; this.readyState = 0; this.sent = []; sockets.push(this);
      queueMicrotask(() => { this.readyState = 1; this.onopen?.();
        if (!protocols) this.event({ type: 'ready' }); });
    }
    send(raw) {
      const event = JSON.parse(raw); this.sent.push(event); trace.push(event.type);
      if (event.type === 'session.update') queueMicrotask(() => this.event({ type: 'session.created' }));
    }
    event(message) { return this.onmessage?.({ data: message instanceof ArrayBuffer ? message : JSON.stringify(message) }); }
    close() { this.readyState = 3; this.closed = true; this.onclose?.(); }
  };
  const player = { bytes: [], cancelled: 0, enqueue(bytes) { this.bytes.push(bytes); },
    cancel() { this.cancelled++; }, whenIdle: async () => {} };
  const options = { sessionId: 'room-test', player, pushToTalk, canBeginTurn, clock: () => now,
    onTurnStart(id) { signals.push(['start', id]); trace.push('start'); },
    onTurnEnd(id) { signals.push(['end', id]); trace.push('end'); },
    onTurnDiscard(id) { signals.push(['discard', id]); trace.push('discard'); },
    onSegment(segment, id) { segments.push({ segment, id }); },
    onListeningState(active) { states.push(active); }, onStatus(text) { statuses.push(text); },
  };
  return { mic, sockets, signals, states, trace, segments, statuses, listeners, player,
    get binary() { return sockets[0]; }, get stt() { return sockets.find((socket) => socket.protocols); },
    get micCalls() { return micCalls; }, get micOptions() { return callbacks; },
    connect: () => connectVoice(options),
    feed(ms = 100, level = 0.2) {
      for (let left = ms; left > 0;) {
        const part = Math.min(left, 20); left -= part; now += part;
        callbacks.onLevel(level); callbacks.onPcm(new Uint8Array(part * 48));
      }
    },
    final(item, text) {
      this.stt.event({ type: 'input_audio_buffer.committed', item_id: item });
      this.stt.event({ type: 'conversation.item.input_audio_transcription.completed', item_id: item, transcript: text });
    },
    commits() { return this.stt.sent.filter((event) => event.type === 'input_audio_buffer.commit'); },
  };
}
test('room hold emits floor start before PCM and end after commit with one matching transcript ID', async () => {
  const env = environment(), voice = await env.connect();
  try {
    assert.equal(voice.connected, true); assert.equal(voice.listening, false);
    await Promise.all([voice.startListening(), voice.startListening()]);
    assert.equal(env.micCalls, 1); assert.deepEqual(env.states, [true]);
    assert.equal(voice.beginTurn(), true); const id = env.signals[0][1];
    assert.equal(typeof id, 'string'); assert.ok(id.length);
    env.feed(); voice.endTurn();
    assert.deepEqual(env.signals, [['start', id], ['end', id]]);
    assert.ok(env.trace.indexOf('start') < env.trace.indexOf('input_audio_buffer.append'));
    assert.ok(env.trace.indexOf('input_audio_buffer.commit') < env.trace.indexOf('end'));
    assert.equal(voice.beginTurn(), false, 'Final transcription holds off the next press.');
    env.final('input-one', 'The full held question.');
    assert.equal(env.segments[0].id, id); assert.equal(env.segments[0].segment.text, 'The full held question.');
    assert.equal(voice.beginTurn(), true);
  } finally { voice.stop(); }
  assert.equal(voice.active, false); assert.equal(voice.connected, false); assert.equal(voice.listening, false);
  assert.deepEqual(env.states, [true, false]); assert.ok(env.sockets.every((socket) => socket.closed));
});
test('too-short release discards its floor rather than leaving the backend waiting for final STT', async () => {
  const env = environment(), voice = await env.connect();
  try {
    await voice.startListening(); voice.beginTurn(); env.feed(40); voice.endTurn();
    const id = env.signals[0][1];
    assert.deepEqual(env.signals, [['start', id], ['discard', id]]);
    assert.equal(env.commits().length, 0); assert.equal(voice.beginTurn(), true);
  } finally { voice.stop(); }
});
test('Pause discards a held floor and a cancellation acknowledgement cannot reopen capture', async () => {
  const env = environment(), voice = await env.connect();
  try {
    await voice.startListening(); voice.beginTurn(); env.feed();
    const id = env.signals[0][1]; voice.setPaused(true);
    assert.deepEqual(env.signals, [['start', id], ['discard', id]]);
    assert.equal(voice.endTurn(), false); assert.equal(env.commits().length, 0);
    env.binary.event({ type: 'cancel' }); assert.equal(env.mic.enabled, false);
    assert.equal(voice.beginTurn(), false);
    voice.setPaused(false); assert.equal(voice.beginTurn(), true);
    assert.notEqual(env.signals.at(-1)[1], id);
  } finally { voice.stop(); }
});
test('Skip invalidates a pending final while commit FIFO keeps the next turn matched', async () => {
  const env = environment(), voice = await env.connect();
  try {
    await voice.startListening(); voice.beginTurn(); env.feed(); voice.endTurn();
    const oldId = env.signals[0][1]; voice.cancel();
    assert.ok(env.signals.some(([kind,id]) => kind === 'discard' && id === oldId));
    voice.beginTurn(); env.feed(); voice.endTurn(); const newId = env.signals.at(-1)[1];
    env.final('old-final', 'This cancelled result must not enter the backend.');
    assert.equal(env.segments.length, 0);
    env.final('new-final', 'Only the current answer.');
    assert.equal(env.segments.length, 1); assert.equal(env.segments[0].id, newId);
  } finally { voice.stop(); }
});
test('stop while a key is held discards the floor before closing both transports', async () => {
  const env = environment(), voice = await env.connect();
  await voice.startListening(); voice.beginTurn(); env.feed(); const id = env.signals[0][1];
  voice.stop(); voice.endTurn();
  assert.deepEqual(env.signals, [['start', id], ['discard', id]]);
  assert.equal(env.commits().length, 0); assert.equal(env.mic.active, false);
  assert.ok(env.sockets.every((socket) => socket.closed)); assert.deepEqual(env.states, [true, false]);
});
test('transcription failure closes binary audio too and reports listening inactive', async () => {
  const env = environment(), voice = await env.connect();
  await voice.startListening();
  env.stt.event({ type: 'error', error: { message: 'private-vendor-body' } });
  assert.equal(voice.active, false); assert.equal(voice.listening, false);
  assert.ok(env.sockets.every((socket) => socket.closed)); assert.deepEqual(env.states, [true, false]);
  assert.equal(env.statuses.some((status) => status.includes('private-vendor-body')), false);
});
test('an overlong live input emits one discarded floor and does not start a residual floor', async () => {
  const env = environment({ pushToTalk: false }), voice = await env.connect();
  try {
    await voice.startListening(); env.feed(60020);
    assert.equal(env.signals.filter(([kind]) => kind === 'start').length, 1);
    assert.equal(env.signals.filter(([kind]) => kind === 'discard').length, 1);
    env.feed(2000); assert.equal(env.signals.length, 2); assert.equal(env.commits().length, 0);
    env.feed(1100, 0); env.feed(200); env.feed(1100, 0);
    assert.equal(env.signals.filter(([kind]) => kind === 'start').length, 2);
    assert.equal(env.commits().length, 1);
  } finally { voice.stop(); }
});

test('actual mic signals screen and Space starts before capture and ends exactly once after flush', async () => {
  const listeners = new Map(), messages = [], signals = []; let worklet;
  globalThis.window = { addEventListener: (n,c) => listeners.set(n,c), removeEventListener: (n) => listeners.delete(n) };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } } });
  class AudioNode { connect() {} disconnect() {} }
  globalThis.AudioContext = class {
    state = 'running'; destination = {}; audioWorklet = { addModule: async () => {} };
    createMediaStreamSource() { return new AudioNode(); }
    createGain() { const node = new AudioNode(); node.gain = { value: 0 }; return node; }
    async resume() {} async close() { this.state = 'closed'; }
  };
  globalThis.AudioWorkletNode = class extends AudioNode {
    constructor() { super(); worklet = this; this.port = {
      postMessage: (message) => { messages.push(message); signals.push('capture'); }, close() {} }; }
  };
  const mic = await startMic({ pushToTalk: true, onTurnStart: () => signals.push('start'),
    onTurnEnd: () => signals.push('end'), onCommit: () => signals.push('commit') });
  try {
    signals.length = 0; mic.beginTurn();
    assert.deepEqual(signals, ['start', 'capture']);
    mic.endTurn(); assert.equal(signals.includes('end'), false);
    const commit = { type: 'commit', epoch: messages.at(-1).epoch };
    worklet.port.onmessage({ data: commit }); worklet.port.onmessage({ data: commit });
    assert.deepEqual(signals.slice(-2), ['commit', 'end']);
    const key = { code: 'Space', target: {}, preventDefault() {} };
    listeners.get('keydown')(key); listeners.get('keydown')(key); listeners.get('keyup')(key);
    worklet.port.onmessage({ data: { type: 'commit', epoch: messages.at(-1).epoch } });
    assert.equal(signals.filter((signal) => signal === 'start').length, 2);
    assert.equal(signals.filter((signal) => signal === 'end').length, 2);
  } finally { await mic.stop(); }
});

test('room phase predicate reaches raw capture and denies a Space-equivalent start without floor events', async () => {
  let allowed = false;
  const env = environment({ canBeginTurn: () => allowed }), voice = await env.connect();
  try {
    await voice.startListening();
    assert.equal(env.mic.enabled, true, 'Input admission is separate from microphone/voice transport state.');
    assert.equal(typeof env.micOptions.canBeginTurn, 'function');
    assert.equal(env.micOptions.canBeginTurn(), false);
    const cancelled = env.player.cancelled;
    assert.equal(voice.beginTurn(), false);
    assert.equal(env.mic.beginTurn(), false, 'Raw keyboard capture must not bypass room admission.');
    assert.deepEqual(env.signals, []); assert.equal(env.commits().length, 0);
    assert.equal(env.player.cancelled, cancelled);
    allowed = true; assert.equal(env.micOptions.canBeginTurn(), true);
    assert.equal(voice.beginTurn(), true); env.feed(); voice.endTurn();
    const id = env.signals[0][1];
    assert.deepEqual(env.signals, [['start', id], ['end', id]]);
    env.final('admitted-turn', 'A permitted answer.');
    assert.equal(env.segments[0].id, id);
  } finally { voice.stop(); }
});

test('denying new turns preserves an already held turn and its matching final transcript', async () => {
  let allowed = true;
  const env = environment({ canBeginTurn: () => allowed }), voice = await env.connect();
  try {
    await voice.startListening(); voice.beginTurn(); env.feed(); const id = env.signals[0][1];
    allowed = false;
    assert.equal(voice.endTurn(), true, 'The predicate guards starts, not release/flush.');
    assert.deepEqual(env.signals, [['start', id], ['end', id]]);
    assert.equal(env.commits().length, 1);
    env.final('held-before-admission-change', 'Finish the turn already in progress.');
    assert.equal(env.segments[0].id, id); assert.equal(voice.beginTurn(), false);
    assert.equal(env.signals.some(([kind]) => kind === 'discard'), false);
  } finally { voice.stop(); }
});

test('a denied capture attempt never cancels a normal audience audio reply', async () => {
  let allowed = true;
  const env = environment({ canBeginTurn: () => allowed }), voice = await env.connect();
  try {
    await voice.startListening(); allowed = false;
    await env.binary.event({ type: 'speech_started', play_id: 'normal-question' });
    const cancelled = env.player.cancelled;
    assert.equal(voice.beginTurn(), false); assert.equal(env.mic.beginTurn(), false);
    await env.binary.event(new Uint8Array([0, 64]).buffer);
    assert.equal(env.player.bytes.length, 1); assert.equal(env.player.cancelled, cancelled);
    assert.equal(voice.speaking, true);
    assert.equal(env.binary.sent.some((event) => event.type === 'cancel'), false);
    assert.deepEqual(env.signals, []);
    await env.binary.event({ type: 'speech_complete', play_id: 'normal-question' });
    assert.equal(voice.speaking, false);
    assert.deepEqual(env.binary.sent.filter((event) => event.type === 'played'),
      [{ type: 'played', play_id: 'normal-question' }]);
  } finally { voice.stop(); }
});

test('voice and transcription admission reaches the actual Space microphone handler end to end', async () => {
  let allowed = false, worklet;
  const env = environment({ canBeginTurn: () => allowed }), commands = [];
  const track = { stop() { this.stopped = true; } };
  globalThis.roomTestMic = startMic;
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    mediaDevices: { getUserMedia: async () => ({ getTracks: () => [track] }) },
  } });
  class AudioNode { connect() {} disconnect() {} }
  globalThis.AudioContext = class {
    state = 'running'; destination = {}; audioWorklet = { addModule: async () => {} };
    createMediaStreamSource() { return new AudioNode(); }
    createGain() { const node = new AudioNode(); node.gain = { value: 0 }; return node; }
    async resume() {} async close() { this.state = 'closed'; }
  };
  globalThis.AudioWorkletNode = class extends AudioNode {
    constructor() { super(); worklet = this; this.port = {
      postMessage: (command) => commands.push(command), close() {} }; }
  };
  const voice = await env.connect();
  try {
    await voice.startListening();
    const key = { code: 'Space', target: {}, preventDefault() {} };
    const count = commands.length;
    env.listeners.get('keydown')(key); env.listeners.get('keyup')(key);
    assert.equal(voice.beginTurn(), false);
    assert.equal(commands.length, count); assert.deepEqual(env.signals, []);
    allowed = true;
    env.listeners.get('keydown')(key);
    assert.equal(env.signals.length, 1); assert.equal(env.signals[0][0], 'start');
    const epoch = commands.at(-1).epoch;
    worklet.port.onmessage({ data: { type: 'pcm', epoch, pcm: new Uint8Array(4800).buffer, level: 0.2 } });
    allowed = false; env.listeners.get('keyup')(key);
    worklet.port.onmessage({ data: { type: 'commit', epoch } });
    assert.deepEqual(env.signals.map(([kind]) => kind), ['start', 'end']);
    env.final('real-mic-capture', 'The already-held turn remains complete.');
    assert.equal(env.segments.length, 1); assert.equal(env.segments[0].id, env.signals[0][1]);
  } finally { voice.stop(); }
  assert.equal(track.stopped, true);
});
