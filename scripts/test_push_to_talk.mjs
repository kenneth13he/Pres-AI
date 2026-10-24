// Deterministic hold-to-talk lifecycle tests; no browser, microphone, or paid calls.
// Run with node --test scripts/test_push_to_talk.mjs.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const root = new URL('../', import.meta.url);
const micSource = await readFile(new URL('frontend/js/mic.js', root), 'utf8');
const workletSource = await readFile(new URL('frontend/js/mic_worklet.js', root), 'utf8');
const { startMic } = await import(`data:text/javascript;base64,${Buffer.from(micSource).toString('base64')}`);

function environment() {
  const listeners = new Map(), commands = [], pendingCommands = [], pendingOutput = [];
  const callbacks = [], chunks = [];
  let processor, worklet, context, commits = 0, discards = 0;
  const track = { stopped: false, stop() { this.stopped = true; } };
  const stream = { getTracks: () => [track] };
  class Node {
    connect() { return this; }
    disconnect() { this.disconnected = true; }
  }
  globalThis.window = {
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name) { listeners.delete(name); },
  };
  Object.defineProperty(globalThis, 'navigator', { configurable: true,
    value: { mediaDevices: { getUserMedia: async () => stream } } });
  globalThis.AudioContext = class {
    constructor() {
      context = this; this.state = 'running'; this.destination = {};
      this.audioWorklet = { addModule: async () => {} };
    }
    createMediaStreamSource() { return new Node(); }
    createGain() { const node = new Node(); node.gain = { value: 1 }; return node; }
    async resume() { this.state = 'running'; }
    async close() { this.state = 'closed'; }
  };
  let Processor;
  vm.runInNewContext(workletSource, {
    sampleRate: 48000, Int16Array, Math,
    AudioWorkletProcessor: class {
      constructor() { this.port = { postMessage: (message) => pendingOutput.push(message) }; }
    },
    registerProcessor(_name, constructor) { Processor = constructor; },
  });
  globalThis.AudioWorkletNode = class extends Node {
    constructor() {
      super(); worklet = this; processor = new Processor();
      this.port = {
        postMessage(message) { commands.push(message); pendingCommands.push(message); },
        close() { worklet.closed = true; },
      };
    }
  };
  function applyCommands() {
    while (pendingCommands.length) processor.port.onmessage({ data: pendingCommands.shift() });
  }
  function deliverOutput() {
    while (pendingOutput.length) worklet.port.onmessage?.({ data: pendingOutput.shift() });
  }
  return {
    commands, chunks, callbacks, track, listeners,
    get commits() { return commits; }, get discards() { return discards; },
    get context() { return context; }, get worklet() { return worklet; },
    applyCommands, deliverOutput,
    feed(milliseconds, level = 0.2) {
      const samples = new Float32Array(milliseconds * 48).fill(level);
      for (let offset = 0; offset < samples.length; offset += 128) {
        processor.process([[samples.subarray(offset, offset + 128)]]);
      }
    },
    async open(options = {}) {
      const mic = await startMic({ pushToTalk: true, ...options,
        onPcm(bytes) { chunks.push([...bytes]); callbacks.push('pcm'); },
        onCommit() { commits++; callbacks.push('commit'); },
        onDiscard() { discards++; callbacks.push('discard'); },
      });
      applyCommands(); deliverOutput();
      return mic;
    },
    key(name, target = {}, { repeat = false, code = 'Space' } = {}) {
      let prevented = false;
      listeners.get(name)?.({ code, target, repeat, preventDefault() { prevented = true; } });
      return prevented;
    },
    blur() { listeners.get('blur')?.(); },
  };
}

test('button-held turn survives a long pause and commits once only after release', async () => {
  const env = environment(), mic = await env.open();
  try {
    assert.equal(typeof mic.beginTurn, 'function');
    assert.equal(typeof mic.endTurn, 'function');
    mic.beginTurn(); env.applyCommands();
    env.feed(40); env.feed(5000, 0); env.feed(40); env.deliverOutput();
    assert.equal(env.commits, 0, 'Silence while the button stays held must not end the turn.');
    mic.endTurn(); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 1);
    assert.equal(env.callbacks.at(-1), 'commit');
    assert.equal(env.chunks.reduce((total, bytes) => total + bytes.length, 0), 5080 * 48);
  } finally { await mic.stop(); }
});

test('repeated press/release is harmless and partial PCM arrives before commit', async () => {
  const env = environment(), mic = await env.open();
  try {
    mic.beginTurn(); mic.beginTurn(); mic.beginTurn(); env.applyCommands();
    env.feed(7); // Less than the worklet's normal 20ms frame: must flush on release.
    assert.equal(env.chunks.length, 0);
    mic.endTurn(); mic.endTurn();
    assert.equal(env.commits, 0, 'Commit must wait for the processor flush acknowledgement.');
    env.applyCommands(); env.deliverOutput();
    assert.deepEqual(env.callbacks, ['pcm', 'commit']);
    assert.equal(env.chunks[0].length, 7 * 48);
    assert.equal(env.commands.filter((message) => message.value === true).length, 1);
    env.feed(1000); env.deliverOutput();
    assert.equal(env.commits, 1); assert.equal(env.chunks.length, 1);
  } finally { await mic.stop(); }
});

test('keyboard Space uses the same hold lifecycle and ignores editing fields', async () => {
  const env = environment(), mic = await env.open();
  try {
    for (const target of [{ tagName: 'INPUT' }, { tagName: 'TEXTAREA' },
      { tagName: 'SELECT' }, { isContentEditable: true }]) {
      assert.equal(env.key('keydown', target), false);
    }
    assert.equal(env.commands.filter((message) => message.value === true).length, 0);
    assert.equal(env.key('keydown'), true); assert.equal(env.key('keydown'), true);
    env.applyCommands(); env.feed(25);
    assert.equal(env.key('keyup'), true); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 1);
    mic.beginTurn(); env.applyCommands(); env.feed(25); mic.endTurn();
    env.applyCommands(); env.deliverOutput(); assert.equal(env.commits, 2);
  } finally { await mic.stop(); }
});

test('cancel discards queued old PCM and a new turn keeps only its own audio', async () => {
  const env = environment(), mic = await env.open();
  try {
    mic.beginTurn(); env.applyCommands(); env.feed(40, 0.7); // Output waits in the port queue.
    assert.equal(env.chunks.length, 0);
    mic.cancelTurn(); mic.beginTurn();
    env.deliverOutput();
    assert.equal(env.chunks.length, 0, 'Old queued PCM must not leak into the next turn.');
    env.applyCommands(); env.feed(7, 0.1); mic.endTurn();
    env.applyCommands(); env.deliverOutput();
    assert.equal(env.discards, 1); assert.equal(env.commits, 1);
    assert.equal(env.chunks.reduce((total, bytes) => total + bytes.length, 0), 7 * 48);
  } finally { await mic.stop(); }
});

test('focus loss discards capture without a commit and ignores a later key release', async () => {
  const env = environment(), mic = await env.open();
  try {
    env.key('keydown'); env.applyCommands(); env.feed(30);
    env.blur(); env.key('keyup'); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 0); assert.equal(env.chunks.length, 0);
    assert.equal(env.discards, 1);
    mic.beginTurn(); env.applyCommands(); env.feed(10); mic.cancelTurn();
    mic.cancelTurn(); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 0); assert.equal(env.discards, 2);
  } finally { await mic.stop(); }
});

test('pause drops a held turn, disabled capture cannot start, and stop releases resources', async () => {
  const env = environment(), mic = await env.open();
  mic.beginTurn(); env.applyCommands(); env.feed(40);
  mic.setEnabled(false); mic.beginTurn(); mic.endTurn();
  env.applyCommands(); env.deliverOutput();
  assert.equal(env.chunks.length, 0); assert.equal(env.commits, 0);
  const commandCount = env.commands.length;
  mic.beginTurn(); env.key('keydown'); env.feed(1000);
  assert.equal(env.commands.length, commandCount);
  await mic.resume(); mic.beginTurn(); env.applyCommands(); env.feed(7);
  await mic.stop();
  mic.beginTurn(); mic.endTurn(); mic.cancelTurn(); await mic.resume(); await mic.stop();
  env.applyCommands(); env.deliverOutput();
  assert.equal(env.commits, 0); assert.equal(env.chunks.length, 0);
  assert.equal(env.track.stopped, true); assert.equal(env.worklet.closed, true);
  assert.equal(env.context.state, 'closed'); assert.equal(env.listeners.size, 0);
});

test('hold-only methods cannot alter continuous capture mode', async () => {
  const env = environment(), mic = await env.open({ pushToTalk: false });
  try {
    const commandCount = env.commands.length;
    mic.beginTurn(); mic.endTurn();
    assert.equal(env.commands.length, commandCount);
    env.feed(40); env.deliverOutput();
    assert.equal(env.chunks.length, 2); assert.equal(env.commits, 0);
    assert.equal(env.listeners.has('keydown'), false);
  } finally { await mic.stop(); }
});

// The visible button reaches the microphone through these wrappers. Exercise that seam
// with a minimal mic; processor flush/cancellation behavior is tested above with real code.
const gateSource = await readFile(new URL('frontend/js/voice_vad.js', root), 'utf8');
const gateUrl = `data:text/javascript;base64,${Buffer.from(gateSource).toString('base64')}`;
async function loadWrapper(path, name) {
  let source = await readFile(new URL(path, root), 'utf8');
  source = source.replace("import { startMic } from './mic.js';",
    'const startMic = (...args) => globalThis.testOpenMic(...args);')
    .replace("'./voice_vad.js'", `'${gateUrl}'`)
    .replace("import { connectTranscription } from '/js/realtime.js';",
      'const connectTranscription = (...args) => globalThis.testTranscription(...args);');
  const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  return module[name];
}
const connectTranscription = await loadWrapper('frontend/js/realtime.js', 'connectTranscription');
const connectConversation = await loadWrapper('frontend/js/conversation.js', 'connectConversation');
const connectVoice = await loadWrapper('frontend/js/voice.js', 'connectVoice');

function wrapperEnvironment() {
  const listeners = new Map();
  let callbacks, socket, now = 1000;
  const mic = {
    active: true, enabled: true, held: false, starts: 0,
    beginTurn() {
      if (!this.active || !this.enabled || this.held) return false;
      this.held = true; this.starts++; return true;
    },
    endTurn() {
      if (!this.active || !this.enabled || !this.held) return false;
      this.held = false; callbacks?.onCommit?.(); return true;
    },
    cancelTurn() {
      if (!this.active || !this.held) return false;
      this.held = false; callbacks?.onDiscard?.(); return true;
    },
    setEnabled(value) { this.enabled = value; if (!value) this.held = false; },
    async stop() { this.active = false; this.enabled = false; this.held = false; },
  };
  globalThis.window = {
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener: (name) => listeners.delete(name),
  };
  globalThis.location = { protocol: 'http:', host: 'localhost:8000' };
  globalThis.testOpenMic = async (options) => { callbacks = options; return mic; };
  globalThis.testTranscription = async () => mic;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({
    value: 'temporary-test-key', url: 'wss://test.invalid',
    config: { type: 'session.update', session: { model: 'higgs-realtime',
      output_modalities: ['text'], audio: { input: { turn_detection: null },
        output: { voice: 'default' } } } },
  }) });
  globalThis.WebSocket = class {
    static OPEN = 1;
    constructor() {
      socket = this; this.readyState = 0; this.sent = [];
      queueMicrotask(() => {
        this.readyState = 1; this.onopen?.(); this.event({ type: 'ready' });
      });
    }
    send(raw) {
      const data = JSON.parse(raw); this.sent.push(data);
      if (data.type === 'session.update') {
        queueMicrotask(() => this.event({ type: 'session.created' }));
      }
    }
    event(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
    close() { this.readyState = 3; this.onclose?.(); }
  };
  const player = { cancel() {}, enqueue() {}, whenIdle: async () => {} };
  return {
    mic, listeners, player, get socket() { return socket; },
    clock: () => now,
    feed() { now += 100; callbacks.onLevel(0.2); callbacks.onPcm(new Uint8Array(4800)); },
    commits() { return socket.sent.filter((event) => event.type === 'input_audio_buffer.commit'); },
  };
}

test('native conversation button delegates holding, discards cancelled audio, and obeys lifecycle', async () => {
  const env = wrapperEnvironment();
  const conversation = await connectConversation({ sessionId: 'ptt', pushToTalk: true,
    player: env.player, clock: env.clock });
  try {
    assert.equal(conversation.beginTurn(), false, 'Button must not open the microphone implicitly.');
    await conversation.startListening();
    assert.equal(conversation.beginTurn(), true); env.feed();
    conversation.cancelTurn();
    assert.equal(env.commits().length, 0);
    assert.ok(env.socket.sent.some((event) => event.type === 'input_audio_buffer.clear'));
    assert.equal(conversation.beginTurn(), true); env.feed(); conversation.endTurn();
    assert.equal(env.commits().length, 1);
    assert.equal(conversation.beginTurn(), false, 'Do not capture while awaiting a reply.');
    conversation.setPaused(true); assert.equal(conversation.beginTurn(), false);
    conversation.setPaused(false); assert.equal(conversation.beginTurn(), true);
  } finally { await conversation.stop(); }
  assert.equal(conversation.beginTurn(), false); assert.equal(env.mic.active, false);
  assert.equal(env.listeners.size, 0);
});

test('transcription button clears a cancelled turn, commits a fresh one, and respects disabled/closed', async () => {
  const env = wrapperEnvironment();
  const transcription = await connectTranscription({ sessionId: 'ptt', pushToTalk: true,
    clock: env.clock });
  try {
    assert.equal(transcription.beginTurn(), true); env.feed(); transcription.cancelTurn();
    assert.equal(env.commits().length, 0);
    assert.ok(env.socket.sent.some((event) => event.type === 'input_audio_buffer.clear'));
    assert.equal(transcription.beginTurn(), true); env.feed(); transcription.endTurn();
    assert.equal(env.commits().length, 1);
    transcription.setEnabled(false); assert.equal(transcription.beginTurn(), false);
    transcription.setEnabled(true); assert.equal(transcription.beginTurn(), true);
  } finally { await transcription.stop(); }
  assert.equal(transcription.beginTurn(), false); assert.equal(env.listeners.size, 0);
});

test('split speech wrapper exposes hold controls without opening a mic and gates speech/pause/stop', async () => {
  const env = wrapperEnvironment();
  const voice = await connectVoice({ sessionId: 'ptt', pushToTalk: true, player: env.player });
  try {
    assert.equal(voice.beginTurn(), false);
    await voice.startListening();
    assert.equal(voice.beginTurn(), true); voice.cancelTurn();
    assert.equal(voice.beginTurn(), true); voice.endTurn();
    env.socket.event({ type: 'speech_started', play_id: 'speaker' });
    assert.equal(voice.beginTurn(), false);
    voice.setPaused(true); assert.equal(voice.beginTurn(), false);
    voice.setPaused(false); assert.equal(voice.beginTurn(), true);
  } finally { await voice.stop(); }
  assert.equal(voice.beginTurn(), false); assert.equal(env.mic.active, false);
  assert.equal(env.listeners.size, 0);
});

test('input-only predicate blocks both visible and raw Space starts while microphone remains enabled', async () => {
  let allowed = false, starts = 0;
  const env = environment(), mic = await env.open({
    canBeginTurn: () => allowed, onTurnStart: () => { starts++; },
  });
  try {
    const controls = env.commands.length;
    assert.equal(mic.beginTurn(), false);
    env.key('keydown'); env.key('keyup'); env.applyCommands(); env.feed(40); env.deliverOutput();
    assert.equal(env.commands.length, controls, 'A denied start must not change physical capture state.');
    assert.equal(env.chunks.length, 0); assert.equal(env.commits, 0); assert.equal(env.discards, 0);
    assert.equal(starts, 0);
    allowed = true; assert.equal(mic.beginTurn(), true);
    env.applyCommands(); env.feed(7); mic.endTurn(); env.applyCommands(); env.deliverOutput();
    assert.equal(starts, 1); assert.equal(env.commits, 1);
    env.key('keydown'); env.applyCommands(); env.feed(7);
    env.key('keyup'); env.applyCommands(); env.deliverOutput();
    assert.equal(starts, 2); assert.equal(env.commits, 2);
  } finally { await mic.stop(); }
});

test('a changed begin predicate cannot cancel a held turn or prevent its final flush', async () => {
  let allowed = true;
  const env = environment(), mic = await env.open({ canBeginTurn: () => allowed });
  try {
    env.key('keydown'); env.applyCommands(); env.feed(7);
    allowed = false;
    assert.equal(env.commits, 0);
    env.key('keyup'); env.applyCommands(); env.deliverOutput();
    assert.deepEqual(env.callbacks, ['pcm', 'commit']);
    assert.equal(env.chunks[0].length, 7 * 48); assert.equal(env.discards, 0);
    assert.equal(mic.beginTurn(), false);
    env.key('keydown'); env.key('keyup'); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 1);
  } finally { await mic.stop(); }
});

test('a busy-denied Space press cannot start later from auto-repeat after admission reopens', async () => {
  let allowed = false;
  const env = environment(), mic = await env.open({ canBeginTurn: () => allowed });
  try {
    const initial = env.commands.length;
    assert.equal(env.key('keydown'), true);
    allowed = true;
    for (let i = 0; i < 5; i++) env.key('keydown', {}, { repeat: true });
    assert.equal(env.commands.length, initial, 'Only a fresh release/press may admit a formerly denied turn.');
    assert.equal(env.key('keyup'), true);
    env.applyCommands(); env.deliverOutput(); assert.equal(env.commits, 0);
    env.key('keydown'); env.applyCommands(); env.feed(7); env.key('keyup');
    env.applyCommands(); env.deliverOutput(); assert.equal(env.commits, 1);
  } finally { await mic.stop(); }
});

test('Space ownership suppresses focused-button activation during disabled capture and its paired release', async () => {
  const env = environment(), mic = await env.open();
  try {
    const pauseButton = { tagName: 'BUTTON' };
    mic.setEnabled(false); const initial = env.commands.length;
    assert.equal(env.key('keydown', pauseButton), true, 'Pause/Skip/End must not activate from PTT Space.');
    assert.equal(env.key('keyup', pauseButton), true, 'The matching keyup must also remain owned by PTT.');
    assert.equal(env.commands.length, initial); assert.equal(env.commits, 0);
    assert.equal(env.key('keydown', pauseButton, { code: 'Enter' }), false);
    assert.equal(env.key('keyup', pauseButton, { code: 'Enter' }), false);
    for (const editable of [{ tagName: 'TEXTAREA' }, { tagName: 'INPUT' },
      { tagName: 'SELECT' }, { isContentEditable: true }]) {
      assert.equal(env.key('keydown', editable), false); assert.equal(env.key('keyup', editable), false);
    }
    mic.setEnabled(true); env.key('keydown', pauseButton); env.applyCommands(); env.feed(7);
    env.key('keyup', pauseButton); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 1);
  } finally { await mic.stop(); }
});

test('a first observed auto-repeat from an already-held key requires a fresh keyup before capture', async () => {
  const env = environment(), mic = await env.open();
  try {
    const initial = env.commands.length;
    assert.equal(env.key('keydown', {}, { repeat: true }), true);
    assert.equal(env.commands.length, initial);
    assert.equal(env.key('keyup'), true);
    env.applyCommands(); env.deliverOutput(); assert.equal(env.commits, 0);
    env.key('keydown'); env.applyCommands(); env.feed(7); env.key('keyup');
    env.applyCommands(); env.deliverOutput(); assert.equal(env.commits, 1);
  } finally { await mic.stop(); }
});

test('blur clears the owned keyboard turn and a continued held key cannot revive it', async () => {
  const env = environment(), mic = await env.open();
  try {
    env.key('keydown'); env.applyCommands(); env.feed(20); env.blur();
    const afterBlur = env.commands.length;
    env.key('keydown', {}, { repeat: true });
    assert.equal(env.commands.length, afterBlur);
    env.key('keyup'); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 0); assert.equal(env.discards, 1); assert.equal(env.chunks.length, 0);
    env.key('keydown'); env.applyCommands(); env.feed(7); env.key('keyup');
    env.applyCommands(); env.deliverOutput(); assert.equal(env.commits, 1);
  } finally { await mic.stop(); }
});

test('a keyboard press denied by an existing pointer hold cannot release that pointer turn', async () => {
  const env = environment(), mic = await env.open();
  try {
    mic.beginTurn(); env.applyCommands(); env.feed(7);
    env.key('keydown'); env.key('keyup'); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 0, 'Space did not begin this turn, so it cannot end the pointer hold.');
    mic.endTurn(); env.applyCommands(); env.deliverOutput();
    assert.equal(env.commits, 1); assert.equal(env.chunks[0].length, 7 * 48);
  } finally { await mic.stop(); }
});

test('an invalidated keyboard capture cannot later release a newer pointer-held turn', async (t) => {
  for (const invalidate of ['disable', 'cancel', 'direct-end']) {
    await t.test(invalidate, async () => {
      const env = environment(), mic = await env.open();
      try {
        env.key('keydown'); env.applyCommands(); env.feed(7);
        if (invalidate === 'disable') { mic.setEnabled(false); mic.setEnabled(true); }
        else if (invalidate === 'cancel') mic.cancelTurn();
        else mic.endTurn();
        env.applyCommands(); env.deliverOutput();
        const beforePointer = env.commits;
        assert.equal(mic.beginTurn(), true); env.applyCommands(); env.feed(7);
        env.key('keydown', {}, { repeat: true });
        assert.equal(env.key('keyup'), true, 'PTT still owns the original Space release.');
        env.applyCommands(); env.deliverOutput();
        assert.equal(env.commits, beforePointer, 'Old keyboard ownership must not commit the new pointer hold.');
        mic.endTurn(); env.applyCommands(); env.deliverOutput();
        assert.equal(env.commits, beforePointer + 1);
      } finally { await mic.stop(); }
    });
  }
});
