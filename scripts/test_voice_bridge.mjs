// Binary playback acknowledgements and microphone gating without a browser or vendor.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
let source = await readFile(new URL('../frontend/js/voice.js', import.meta.url), 'utf8');
source = source.replace("import { connectTranscription } from '/js/realtime.js';",
  'const connectTranscription = (...args) => globalThis.transcription(...args);');
const { connectVoice } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
function environment() {
  const listeners = new Map();
  globalThis.location = { protocol:'http:', host:'localhost:8000' };
  globalThis.window = { addEventListener:(n,c) => listeners.set(n,c), removeEventListener:(n) => listeners.delete(n) };
  let socket, micCalls = 0;
  const mic = { active:true, gates:[], setEnabled(v) { this.gates.push(v); }, stop() { this.active=false; this.stopped=true; } };
  globalThis.transcription = async () => { micCalls++; return mic; };
  globalThis.WebSocket = class {
    constructor() { socket=this; this.readyState=1; this.sent=[];
      queueMicrotask(() => this.onmessage({data:JSON.stringify({type:'ready'})})); }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { this.readyState=3; }
    event(data) { return this.onmessage({data:data instanceof ArrayBuffer ? data : JSON.stringify(data)}); }
  };
  let idle = deferred();
  const player = { bytes:[], cancelled:0, cancel() { this.cancelled++; },
    enqueue(data) { this.bytes.push(data); }, whenIdle() { return idle.promise; } };
  return { mic, player, listeners, get socket() { return socket; }, get micCalls() { return micCalls; },
    finish() { idle.resolve(); }, resetIdle() { idle=deferred(); } };
}
test('one audio turn gates capture and waits for playback before acknowledging', async () => {
  const env=environment();
  const voice=await connectVoice({sessionId:'test',player:env.player});
  try {
    await Promise.all([voice.startListening(),voice.startListening()]);
    assert.equal(env.micCalls,1);
    await env.socket.event({type:'speech_started',play_id:'one'});
    assert.equal(env.mic.gates.at(-1),false);
    await env.socket.event(new Uint8Array([1,2]).buffer);
    const completing=env.socket.event({type:'speech_complete',play_id:'one'});
    await tick();
    assert.equal(env.socket.sent.some((m) => m.type==='played'),false);
    env.finish(); await completing;
    assert.equal(env.mic.gates.at(-1),true);
    assert.deepEqual(env.socket.sent.filter((m) => m.type==='played'),[{type:'played',play_id:'one'}]);
    assert.equal(env.player.bytes.length,1);
  } finally { voice.stop(); }
  assert.equal(env.mic.stopped,true); assert.equal(env.listeners.size,0);
});
test('cancelled playback never sends an acknowledgement for a later turn', async () => {
  const env=environment(); const voice=await connectVoice({sessionId:'test',player:env.player});
  try {
    await voice.startListening();
    await env.socket.event({type:'speech_started',play_id:'old'});
    const completing=env.socket.event({type:'speech_complete',play_id:'old'});
    voice.cancel(); await env.socket.event({type:'speech_started',play_id:'new'});
    env.finish(); await completing;
    assert.equal(env.socket.sent.some((m) => m.type==='played'),false);
    voice.setPaused(true); assert.equal(env.mic.gates.at(-1),false);
    voice.setPaused(false); assert.equal(env.mic.gates.at(-1),true);
  } finally { voice.stop(); }
});
test('audio transport failure releases microphone and queued playback', async () => {
  const env=environment(); const voice=await connectVoice({sessionId:'test',player:env.player});
  await voice.startListening(); env.socket.onerror();
  assert.equal(env.mic.stopped,true); assert.equal(env.socket.readyState,3);
  assert.equal(env.listeners.size,0);
});
