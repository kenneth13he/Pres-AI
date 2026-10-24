// Native speech-to-speech sequencing without a microphone, browser, or paid API call.
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
const tick = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const gate = await readFile(new URL('../frontend/js/voice_vad.js', import.meta.url), 'utf8');
let source = await readFile(new URL('../frontend/js/conversation.js', import.meta.url), 'utf8');
source = source.replace("import { startMic } from './mic.js';", 'const startMic = (...args) => globalThis.openTestMic(...args);')
  .replace("'./voice_vad.js'", `'data:text/javascript;base64,${Buffer.from(gate).toString('base64')}'`);
const { connectConversation } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
function environment() {
  const listeners = new Map(), segments = [], statuses = [], speaking = [], latency = [], captions = [];
  let socket, micCalls = 0, callbacks, now = 1000, idle = deferred();
  const mic = { enabled: true, stopped: false, setEnabled(value) { this.enabled = value; },
    async stop() { this.stopped = true; } };
  globalThis.window = { addEventListener: (n,c) => listeners.set(n,c), removeEventListener: (n) => listeners.delete(n) };
  globalThis.openTestMic = async (options) => { micCalls++; callbacks = options; return mic; };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ value: 'ephemeral-test',
    url: 'wss://voice-test.invalid', config: { type: 'session.update', session: {
      model: 'higgs-realtime', output_modalities: ['text'], audio: { input: {
        format: { type: 'audio/pcm', rate: 24000 }, turn_detection: { type: 'server_vad' },
        transcription: { model: 'higgs-stt-3.1' } }, output: {
        format: { type: 'audio/pcm', rate: 24000 }, voice: 'default' } },
    } } }) });
  globalThis.WebSocket = class {
    static OPEN = 1;
    constructor(url, protocols) {
      socket = this; this.sent = []; this.readyState = 0; this.protocols = protocols;
      queueMicrotask(() => { this.readyState = 1; this.onopen?.(); });
    }
    send(raw) {
      const data = JSON.parse(raw); this.sent.push(data);
      if (data.type === 'session.update') queueMicrotask(() => this.event({ type: 'session.created' }));
    }
    event(data) { return this.onmessage?.({ data: JSON.stringify(data) }); }
    close() { this.readyState = 3; this.closed = true; this.onclose?.(); }
  };
  const player = { bytes: [], cancelled: 0, enqueue(bytes) { this.bytes.push([...bytes]); },
    cancel() { this.cancelled++; }, whenIdle() { return idle.promise; } };
  return { mic, player, listeners, segments, statuses, speaking, latency, captions,
    get socket() { return socket; }, get micCalls() { return micCalls; },
    advance(ms) { now += ms; }, finish() { idle.resolve(); }, resetPlayback() { idle = deferred(); },
    feed(ms = 20) { now += ms; callbacks.onLevel(0.2); callbacks.onPcm(new Uint8Array(ms * 48)); },
    commit() { callbacks.onCommit(); },
    utterance() { for (let i = 0; i < 5; i++) this.feed(); this.commit(); },
    ack(id) { socket.event({ type: 'input_audio_buffer.committed', item_id: id }); },
    added(id) { socket.event({ type: 'conversation.item.added', item: { id, role: 'user' } }); },
    created(id) { socket.event({ type: 'response.created', response: { id } }); },
    audio(id) { socket.event({ type: 'response.output_audio.delta', response_id: id, delta: btoa('\x00\x40') }); },
    done(id) { socket.event({ type: 'response.done', response: { id, status: 'completed' } }); },
    replies() { return socket.sent.filter((event) => event.type === 'response.create'); },
    connect: () => connectConversation({ sessionId: 'conversation-test', player,
      clock: () => now, pushToTalk: true, voiceId: 'marcus', personaName: 'Dana',
      onSegment: (segment) => segments.push(segment), onStatus: (text) => statuses.push(text),
      onSpeaking: (value) => speaking.push(value), onLatency: (data) => latency.push(data),
      onAssistantText: (text, info) => captions.push({ text, ...info }),
    }),
  };
}
test('native conversation authenticates for audio but starts mic only on explicit request', async () => {
  const env = environment(), conversation = await env.connect();
  try {
    assert.deepEqual(env.socket.protocols, ['realtime', 'bai-client-secret.ephemeral-test']);
    const config = env.socket.sent[0].session;
    assert.deepEqual(config.output_modalities, ['audio']); assert.equal(config.max_output_tokens, 128);
    assert.equal(config.audio.input.turn_detection, null); assert.equal(config.audio.output.voice, 'marcus');
    assert.match(config.instructions, /latest spoken words/); assert.match(config.instructions, /Dana/);
    assert.equal(env.micCalls, 0); assert.equal(env.replies().length, 0);
    await Promise.all([conversation.startListening(), conversation.startListening()]);
    assert.equal(env.micCalls, 1);
  } finally { await conversation.stop(); }
  assert.equal(env.mic.stopped, true); assert.equal(env.socket.closed, true);
  assert.equal(env.listeners.size, 0); assert.equal(conversation.active, false);
});
test('each turn waits for both commit ACK and added item and requests exactly one reply', async () => {
  const env = environment(), conversation = await env.connect();
  try {
    await conversation.startListening(); env.utterance();
    assert.equal(env.replies().length, 0); assert.equal(env.mic.enabled, false);
    env.ack('input-one'); assert.equal(env.replies().length, 0);
    // Final user STT must survive the microphone being gated for its own pending reply.
    env.socket.event({ type: 'conversation.item.input_audio_transcription.completed',
      item_id: 'input-one', transcript: 'Seven plus five?' });
    assert.deepEqual(env.segments, [{ start_ms: 1000, end_ms: 1100,
      text: 'Seven plus five?', speaker: 'presenter', confidence: null }]);
    env.added('input-one'); env.added('input-one');
    assert.equal(env.replies().length, 1);
    assert.deepEqual(env.replies()[0], { type: 'response.create' });
    assert.equal(JSON.stringify(env.replies()).includes('I heard you'), false);
  } finally { await conversation.stop(); }
});
test('item-added before commit ACK also produces one reply', async () => {
  const env = environment(), conversation = await env.connect();
  try {
    await conversation.startListening(); env.utterance();
    env.added('input-first'); assert.equal(env.replies().length, 0);
    env.ack('input-first'); assert.equal(env.replies().length, 1);
    env.added('input-first'); assert.equal(env.replies().length, 1);
  } finally { await conversation.stop(); }
});
test('native audio and generated captions stream; mic resumes only after playback drains', async () => {
  const env = environment(), conversation = await env.connect();
  try {
    await conversation.startListening(); env.utterance(); env.ack('question'); env.added('question');
    env.created('answer'); assert.equal(conversation.speaking, true); assert.equal(env.mic.enabled, false);
    env.advance(468); env.audio('answer'); env.audio('answer');
    assert.deepEqual(env.player.bytes, [[0, 64], [0, 64]]);
    assert.deepEqual(env.latency, [{ speech_to_playback_ms: 468 }]);
    env.socket.event({ type: 'response.output_audio_transcript.delta', response_id: 'answer', delta: 'The answer ' });
    env.socket.event({ type: 'response.output_audio_transcript.delta', response_id: 'answer', delta: 'is twelve.' });
    env.socket.event({ type: 'response.output_audio_transcript.done', response_id: 'answer', transcript: 'The answer is twelve.' });
    assert.equal(env.captions.at(-1).text, 'The answer is twelve.'); assert.equal(env.captions.at(-1).final, true);
    env.done('answer'); await tick();
    assert.equal(conversation.speaking, true); assert.equal(env.mic.enabled, false);
    env.finish(); await tick();
    assert.equal(conversation.speaking, false); assert.equal(env.mic.enabled, true);
    assert.deepEqual(env.speaking, [true, false]);
  } finally { await conversation.stop(); }
});
test('cancel before response-created ignores old audio and keeps a later response separate', async () => {
  const env = environment(), conversation = await env.connect();
  try {
    await conversation.startListening(); env.utterance(); env.ack('old-question'); env.added('old-question');
    conversation.cancel(); assert.equal(env.mic.enabled, true);
    env.utterance(); env.ack('new-question'); env.added('new-question');
    env.created('old-answer'); env.audio('old-answer');
    assert.equal(env.player.bytes.length, 0); assert.equal(conversation.speaking, false);
    assert.deepEqual(env.socket.sent.filter((event) => event.type === 'response.cancel'),
      [{ type: 'response.cancel', response_id: 'old-answer' }]);
    env.created('new-answer'); env.audio('new-answer');
    assert.equal(conversation.speaking, true); assert.equal(env.player.bytes.length, 1);
    env.done('old-answer'); await tick(); assert.equal(conversation.speaking, true);
  } finally { await conversation.stop(); }
});
test('pause discards unacknowledged input and emits no response until resumed speech', async () => {
  const env = environment(), conversation = await env.connect();
  try {
    await conversation.startListening(); env.utterance(); conversation.setPaused(true);
    env.ack('paused-turn'); env.added('paused-turn'); assert.equal(env.replies().length, 0);
    env.socket.event({ type: 'conversation.item.input_audio_transcription.completed',
      item_id: 'paused-turn', transcript: 'Ignore paused input.' });
    assert.equal(env.segments.length, 0); assert.equal(env.mic.enabled, false);
    conversation.setPaused(false); assert.equal(env.mic.enabled, true);
    env.utterance(); env.ack('resumed-turn'); env.added('resumed-turn');
    assert.equal(env.replies().length, 1);
  } finally { await conversation.stop(); }
});
test('vendor failure surfaces no raw body and closes mic, playback and connection', async () => {
  const env = environment(), conversation = await env.connect();
  await conversation.startListening();
  env.socket.event({ type: 'error', error: { message: 'private-vendor-body' } });
  await tick(); assert.equal(conversation.active, false); assert.equal(env.mic.stopped, true);
  assert.equal(env.socket.closed, true); assert.ok(env.player.cancelled > 0);
  assert.equal(env.statuses.some((text) => text.includes('private-vendor-body')), false);
});
