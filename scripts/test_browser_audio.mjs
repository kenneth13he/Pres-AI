// Deterministic browser-audio tests. Run with node --test scripts/test_browser_audio.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);
async function load(relative) {
  const text = await readFile(new URL(relative, root), 'utf8');
  return import(`data:text/javascript;base64,${Buffer.from(text).toString('base64')}`);
}
class FakeNode {
  connect() { return this; }
  disconnect() { this.disconnected = true; }
}
class FakeContext {
  static instances = [];
  constructor() {
    this.currentTime = 0; this.state = 'running'; this.destination = {};
    this.sources = []; this.audioWorklet = { addModule: async () => {} };
    FakeContext.instances.push(this);
  }
  createBuffer(_channels, count, rate) {
    const samples = new Float32Array(count);
    return { duration: count / rate, getChannelData: () => samples };
  }
  createBufferSource() {
    const source = new FakeNode();
    source.start = (at) => { source.at = at; };
    source.stop = () => { source.stopped = true; };
    this.sources.push(source); return source;
  }
  createGain() { const node = new FakeNode(); node.gain = { value: 1 }; return node; }
  createMediaStreamSource() { this.input = new FakeNode(); return this.input; }
  async resume() { this.resumed = true; }
  async close() { this.state = 'closed'; }
}
globalThis.AudioContext = FakeContext;
globalThis.document = { getElementById: () => null };
const { createPlayer } = await load('frontend/js/audio.js');
const { startMic } = await load('frontend/js/mic.js');

function pcm(samples) {
  const out = new Uint8Array(samples.length * 2), view = new DataView(out.buffer);
  samples.forEach((value, i) => view.setInt16(i * 2, value, true)); return out;
}
test('PCM playback preserves arbitrary byte splits, signs and gapless scheduling', async () => {
  const player = createPlayer(), ctx = FakeContext.instances.at(-1);
  const bytes = pcm([-32768, -1, 0, 32767]);
  player.enqueue(bytes.subarray(0, 1));
  assert.equal(player.busy, false);
  player.enqueue(bytes.subarray(1, 5));
  player.enqueue(bytes.subarray(5));
  assert.deepEqual(ctx.sources.flatMap((source) => [...source.buffer.getChannelData(0)]),
    [-1, -1 / 32768, 0, 32767 / 32768]);
  assert.equal(ctx.sources[1].at, ctx.sources[0].at + ctx.sources[0].buffer.duration);
  let idle = false; const drained = player.whenIdle().then(() => { idle = true; });
  ctx.sources[0].onended(); await Promise.resolve(); assert.equal(idle, false);
  ctx.sources[1].onended(); await drained; assert.equal(player.busy, false);
  await player.close();
});
test('cancel stops all playback, releases waiters and drops an incomplete sample', async () => {
  const player = createPlayer(), ctx = FakeContext.instances.at(-1);
  player.enqueue(new Uint8Array([0, 64, 99]));
  const drained = player.whenIdle(); player.cancel(); await drained;
  assert.equal(ctx.sources[0].stopped, true); assert.equal(ctx.sources[0].disconnected, true);
  player.enqueue(new Uint8Array([0, 0]));
  assert.deepEqual([...ctx.sources[1].buffer.getChannelData(0)], [0]);
  await player.close(); player.enqueue(pcm([100]));
  assert.equal(ctx.sources.length, 2); assert.equal(ctx.state, 'closed');
});

const workletSource = await readFile(new URL('frontend/js/mic_worklet.js', root), 'utf8');
function processor(rate = 48000) {
  let Processor;
  vm.runInNewContext(workletSource, {
    sampleRate: rate, Int16Array, Math,
    AudioWorkletProcessor: class {
      constructor() {
        this.messages = [];
        this.port = { postMessage: (message) => this.messages.push(message) };
      }
    },
    registerProcessor: (_name, cls) => { Processor = cls; },
  });
  const instance = new Processor();
  instance.port.onmessage({ data: { type: 'enabled', value: true } });
  return instance;
}
test('worklet resamples 48 kHz across render blocks and reports actual RMS', () => {
  const worklet = processor();
  const input = Float32Array.from({ length: 960 }, (_, i) => Math.sin(i / 30) * 0.5);
  for (let i = 0; i < input.length; i += 128) worklet.process([[input.subarray(i, i + 128)]]);
  const frames = worklet.messages.filter((message) => message.type === 'pcm');
  assert.equal(frames.length, 1);
  const output = new Int16Array(frames[0].pcm);
  assert.equal(output.length, 480);
  for (let i = 0; i < output.length; i++) {
    const value = input[i * 2];
    assert.equal(output[i], Math.round(value * (value < 0 ? 32768 : 32767)));
  }
  assert.ok(frames[0].level > 0.3 && frames[0].level < 0.4);
});
test('worklet preserves fractional phase at 44.1 kHz and flushes before PTT commit', () => {
  const worklet = processor(44100);
  const input = Float32Array.from({ length: 4410 }, (_, i) => Math.sin(i / 30) * 0.5);
  for (let i = 0; i < input.length; i += 128) worklet.process([[input.subarray(i, i + 128)]]);
  worklet.port.onmessage({ data: { type: 'enabled', value: false, flush: true, commit: true } });
  const output = worklet.messages.filter((m) => m.type === 'pcm').flatMap((m) => [...new Int16Array(m.pcm)]);
  assert.equal(output.length, 2400);
  for (let i = 0; i < output.length; i++) {
    const at = i * 44100 / 24000, left = Math.floor(at), frac = at - left;
    const expected = input[left] + ((input[left + 1] ?? input[left]) - input[left]) * frac;
    assert.ok(Math.abs(output[i] / 32768 - expected) < 0.00006);
  }
  assert.equal(worklet.messages.at(-1).type, 'commit');
  const count = worklet.messages.length; worklet.process([[input]]);
  assert.equal(worklet.messages.length, count);
});

function micEnvironment({ failWorklet = false } = {}) {
  const listeners = new Map(), track = { stop() { this.stopped = true; } };
  const stream = { getTracks: () => [track] };
  globalThis.window = {
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener: (name) => listeners.delete(name),
  };
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true, value: { mediaDevices: { getUserMedia: async () => stream } },
  });
  let node;
  globalThis.AudioWorkletNode = class extends FakeNode {
    constructor() {
      super(); node = this; this.messages = [];
      this.port = { postMessage: (m) => this.messages.push(m), close: () => { this.closed = true; } };
      if (failWorklet) throw new Error('worklet unavailable');
    }
  };
  return { listeners, track, get node() { return node; } };
}
test('microphone PTT gates capture, commits on release and cleans up', async () => {
  const env = micEnvironment(); const chunks = []; let commits = 0;
  const mic = await startMic({ pushToTalk: true, onPcm: (chunk) => chunks.push(chunk),
    onCommit: () => { commits++; } });
  assert.equal(env.node.messages[0].value, false);
  const key = { code: 'Space', target: {}, preventDefault() {} };
  env.listeners.get('keydown')(key); assert.equal(env.node.messages.at(-1).value, true);
  env.listeners.get('keyup')(key);
  const epoch = env.node.messages.at(-1).epoch;
  assert.deepEqual(env.node.messages.at(-1), { type: 'enabled', value: false, flush: true, commit: true, epoch });
  env.node.port.onmessage({ data: { type: 'pcm', pcm: pcm([1]).buffer, level: 0.2, epoch } });
  env.node.port.onmessage({ data: { type: 'commit', epoch } });
  assert.equal(chunks.length, 1); assert.equal(commits, 1);
  mic.pause(); env.listeners.get('keydown')(key);
  assert.equal(env.node.messages.at(-1).value, false);
  await mic.stop(); assert.equal(env.track.stopped, true); assert.equal(env.listeners.size, 0);
  assert.equal(env.node.closed, true); assert.equal(FakeContext.instances.at(-1).state, 'closed');
});
test('microphone initialization failure releases track and audio context', async () => {
  const env = micEnvironment({ failWorklet: true });
  await assert.rejects(startMic(), /worklet unavailable/);
  assert.equal(env.track.stopped, true); assert.equal(FakeContext.instances.at(-1).state, 'closed');
});

const { createUtteranceGate } = await load('frontend/js/voice_vad.js');
function utterances(options = {}) {
  let now = 0, cleared = 0;
  const appended = [], committed = [];
  const gate = createUtteranceGate({ ...options, clock: () => now,
    onAppend: (bytes) => appended.push(bytes), onCommit: (interval) => committed.push(interval),
    onClear: () => { cleared++; } });
  return { gate, appended, committed, get cleared() { return cleared; },
    feed(level, ms = 20) { now += ms; gate.feed(new Uint8Array(ms * 48), level); } };
}
test('manual VAD sends no silence, bounds pre-roll and commits final speech after silence', () => {
  const run = utterances();
  for (let i = 0; i < 25; i++) run.feed(0);
  assert.equal(run.appended.length, 0); assert.equal(run.committed.length, 0);
  for (let i = 0; i < 10; i++) run.feed(0.1);
  assert.equal(run.appended.length, 20); // 200 ms pre-roll + 200 ms speech.
  for (let i = 0; i < 54; i++) run.feed(0);
  assert.equal(run.committed.length, 0);
  run.feed(0);
  assert.deepEqual(run.committed, [{ start_ms: 500, end_ms: 700 }]);
});
test('manual VAD discards short noise and disabling never commits buffered audio', () => {
  const run = utterances();
  run.feed(0.1); for (let i = 0; i < 55; i++) run.feed(0);
  assert.equal(run.cleared, 1); assert.equal(run.committed.length, 0);
  for (let i = 0; i < 10; i++) run.feed(0.1);
  run.gate.setEnabled(false); run.gate.commit();
  assert.equal(run.cleared, 2); assert.equal(run.committed.length, 0);
  const count = run.appended.length; run.feed(0.2);
  assert.equal(run.appended.length, count);
});
test('PTT commits only on release, rejects under 100 ms and continuous speech stays open', () => {
  const ptt = utterances({ pushToTalk: true });
  for (let i = 0; i < 4; i++) ptt.feed(0.1);
  ptt.gate.commit(); assert.equal(ptt.committed.length, 0); assert.equal(ptt.cleared, 1);
  for (let i = 0; i < 5; i++) ptt.feed(0.1);
  assert.equal(ptt.committed.length, 0); ptt.gate.commit();
  assert.deepEqual(ptt.committed, [{ start_ms: 80, end_ms: 180 }]);
  const live = utterances();
  for (let i = 0; i < 1000; i++) live.feed(0.2);
  assert.deepEqual(live.committed, []);
  for (let i = 0; i < 55; i++) live.feed(0);
  assert.deepEqual(live.committed, [{ start_ms: 0, end_ms: 20000 }]);
});

let realtimeSource = await readFile(new URL('frontend/js/realtime.js', root), 'utf8');
const gateSource = await readFile(new URL('frontend/js/voice_vad.js', root), 'utf8');
realtimeSource = realtimeSource.replace("import { startMic } from './mic.js';",
  'const startMic = (...args) => globalThis.__startMic(...args);')
  .replace("'./voice_vad.js'", `'data:text/javascript;base64,${Buffer.from(gateSource).toString('base64')}'`);
const { connectTranscription } = await import(`data:text/javascript;base64,${Buffer.from(realtimeSource).toString('base64')}`);
function realtimeEnvironment() {
  const events = [], statuses = [], segments = [], activities = [], endings = [];
  let callbacks, stoppedMic = false, micEnabled = true, now = 1000;
  globalThis.__startMic = async (options) => {
    callbacks = options;
    return { setEnabled: (value) => { micEnabled = value; }, stop: async () => { stoppedMic = true; } };
  };
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ value: 'ephemeral-test-value',
    url: 'wss://test.invalid/realtime', config: { type: 'session.update', session: {
      model: 'higgs-realtime', audio: { input: { turn_detection: { type: 'server_vad' } } },
    } } }) });
  class FakeSocket {
    static OPEN = 1;
    constructor(url, protocols) {
      this.url = url; this.protocols = protocols; this.readyState = 0;
      FakeSocket.instance = this;
      queueMicrotask(() => { this.readyState = 1; this.onopen?.(); });
    }
    send(raw) {
      const message = JSON.parse(raw); events.push(message);
      if (message.type === 'session.update') queueMicrotask(() => this.emit({ type: 'session.created' }));
    }
    emit(message) { this.onmessage?.({ data: JSON.stringify(message) }); }
    close() { this.closed = true; this.readyState = 3; this.onclose?.(); }
  }
  globalThis.WebSocket = FakeSocket;
  return {
    events, statuses, segments, activities, endings,
    get socket() { return FakeSocket.instance; },
    get stoppedMic() { return stoppedMic; }, get micEnabled() { return micEnabled; },
    feed(ms = 20) { now += ms; callbacks.onLevel(0.2); callbacks.onPcm(new Uint8Array(ms * 48)); },
    commit() { callbacks.onCommit(); },
    connect: () => connectTranscription({ sessionId: 'session-test', pushToTalk: true,
      clock: () => now, onStatus: (status) => statuses.push(status),
      onSegment: (segment) => segments.push(segment), onActivity: (at) => activities.push(at),
      onUtteranceEnd: (at) => endings.push(at) }),
  };
}
test('Realtime handshake uses ephemeral subprotocol, manual commits and capture timestamps', async () => {
  const env = realtimeEnvironment(), connection = await env.connect();
  assert.deepEqual(env.socket.protocols, ['realtime', 'bai-client-secret.ephemeral-test-value']);
  assert.equal(env.events[0].session.audio.input.turn_detection, null);
  for (let i = 0; i < 5; i++) env.feed();
  env.commit();
  env.socket.emit({ type: 'input_audio_buffer.committed', item_id: 'turn1' });
  env.socket.emit({ type: 'conversation.item.input_audio_transcription.completed',
    item_id: 'turn1', transcript: '  A grounded statement.  ' });
  assert.deepEqual(env.segments, [{ start_ms: 1000, end_ms: 1100,
    text: 'A grounded statement.', speaker: 'presenter', confidence: null }]);
  assert.deepEqual(env.endings, [1100]); assert.equal(env.activities.length, 1);
  assert.equal(env.events.some((message) => message.type === 'response.create'), false);
  await connection.stop(); assert.equal(env.stoppedMic, true); assert.equal(env.socket.closed, true);
});
test('Pause invalidates pending STT without assigning old commit ACK to a new utterance', async () => {
  const env = realtimeEnvironment(), connection = await env.connect();
  for (let i = 0; i < 5; i++) env.feed(); env.commit();
  connection.setEnabled(false); assert.equal(env.micEnabled, false);
  connection.setEnabled(true);
  for (let i = 0; i < 5; i++) env.feed(); env.commit();
  env.socket.emit({ type: 'input_audio_buffer.committed', item_id: 'before-pause' });
  env.socket.emit({ type: 'input_audio_buffer.committed', item_id: 'after-pause' });
  env.socket.emit({ type: 'conversation.item.input_audio_transcription.completed',
    item_id: 'before-pause', transcript: 'This must be discarded.' });
  env.socket.emit({ type: 'conversation.item.input_audio_transcription.completed',
    item_id: 'after-pause', transcript: 'This is current.' });
  assert.deepEqual(env.segments, [{ start_ms: 1100, end_ms: 1200,
    text: 'This is current.', speaker: 'presenter', confidence: null }]);
  assert.ok(env.events.some((message) => message.type === 'input_audio_buffer.clear'));
  await connection.stop();
});
test('Vendor errors are generic and release mic and socket', async () => {
  const env = realtimeEnvironment(), connection = await env.connect();
  env.socket.emit({ type: 'error', error: { message: 'private-vendor-error-body' } });
  await Promise.resolve();
  assert.equal(env.stoppedMic, true); assert.equal(env.socket.closed, true);
  assert.equal(env.statuses.some((status) => status.includes('private-vendor-error-body')), false);
  await connection.stop();
});

test('Repeated enabled state preserves the current utterance and repeated pause is harmless', async () => {
  const env = realtimeEnvironment(), connection = await env.connect();
  for (let i = 0; i < 2; i++) env.feed();
  connection.setEnabled(true);
  for (let i = 0; i < 3; i++) env.feed(); env.commit();
  env.socket.emit({ type: 'input_audio_buffer.committed', item_id: 'whole-utterance' });
  env.socket.emit({ type: 'conversation.item.input_audio_transcription.completed',
    item_id: 'whole-utterance', transcript: 'Preserved.' });
  assert.equal(env.segments.length, 1);
  assert.deepEqual([env.segments[0].start_ms, env.segments[0].end_ms], [1000, 1100]);
  connection.setEnabled(false); connection.setEnabled(false);
  assert.equal(env.events.filter((message) => message.type === 'input_audio_buffer.clear').length, 1);
  await connection.stop(); assert.equal(connection.active, false);
});
