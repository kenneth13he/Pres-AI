// Microphone capture: level meter, push-to-talk, and utterances for speech-to-text.
// Owner: Person B (bridge) with Person A (meter UI). Nothing here is recorded or stored.
//
// Transcript source: Higgs STT on the server. Here the mic is cut into utterances by loudness
// (speech starts above the room's noise floor, ends after END_MS of quiet); each is sent as a
// 16 kHz WAV to `transcribe`, and its text becomes one `transcript_segment`. Chrome's own
// speech recognition is not used: on 24 Oct it ended instantly, silently, and heard nothing.
// The mic is always on: the server ignores what it hears while a panelist is talking.

const RATE = 16000;
const END_MS = 800;        // this much quiet ends an utterance
const MIN_MS = 350;        // shorter is a cough or a click
const MAX_MS = 15000;      // a long run-on is sent in pieces
const PREROLL = 3;         // buffers kept from just before speech started (~250 ms)

export async function startMic({ onLevel, transcribe, onSegment, onInterim = () => {},
  pushToTalk = false, pttKey = 'Space' }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const t0 = performance.now();
  let live = !pushToTalk;
  let stopped = false;

  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const mute = ctx.createGain();
  mute.gain.value = 0;
  source.connect(proc); proc.connect(mute); mute.connect(ctx.destination);

  let floor = 0.01;          // the room's noise level, tracked while nobody speaks
  let speaking = false;
  let quietMs = 0;
  let chunks = [];
  let pre = [];
  let startMs = 0;
  const bufMs = (4096 / ctx.sampleRate) * 1000;

  const flush = () => {
    const voiced = chunks.length * bufMs - quietMs;
    const pcm = chunks; chunks = [];
    speaking = false; quietMs = 0;
    if (voiced < MIN_MS || !transcribe) return;
    const start = startMs, end = Math.round(performance.now() - t0);
    transcribe(wav(pcm, ctx.sampleRate), start, end).then((text) => {
      if (text && onSegment) onSegment({ start_ms: start, end_ms: end, text, speaker: 'presenter', confidence: null });
    }).catch((e) => console.warn('[mic] stt', e));
  };

  proc.onaudioprocess = (e) => {
    if (stopped) return;
    const x = new Float32Array(e.inputBuffer.getChannelData(0));
    let sum = 0;
    for (const v of x) sum += v * v;
    const rms = Math.sqrt(sum / x.length);
    onLevel(live ? Math.min(1, rms * 8) : 0);
    if (!live) { if (speaking) flush(); pre = []; return; }
    const loud = rms > Math.max(0.012, floor * 3);
    if (!speaking) {
      floor = loud ? floor : floor * 0.95 + rms * 0.05;
      pre.push(x); if (pre.length > PREROLL) pre.shift();
      if (loud) {
        speaking = true; quietMs = 0; chunks = pre; pre = [];
        startMs = Math.max(0, Math.round(performance.now() - t0 - chunks.length * bufMs));
        onInterim('…');
      }
      return;
    }
    chunks.push(x);
    quietMs = loud ? 0 : quietMs + bufMs;
    if (quietMs >= END_MS || chunks.length * bufMs >= MAX_MS) flush();
  };

  // ---- push-to-talk ----------------------------------------------------------------
  const onKey = (down) => (e) => {
    if (!pushToTalk || e.code !== pttKey || e.repeat) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    e.preventDefault();
    live = down;
  };
  const kd = onKey(true), ku = onKey(false);
  if (pushToTalk) { addEventListener('keydown', kd); addEventListener('keyup', ku); }

  return {
    hasSTT: true,
    stream,
    stop() {
      stopped = true;
      if (speaking) flush();
      proc.disconnect(); source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      removeEventListener('keydown', kd); removeEventListener('keyup', ku);
    },
  };
}

// Float32 chunks at `rate` → a 16 kHz 16-bit mono WAV blob.
function wav(chunks, rate) {
  const n = chunks.reduce((a, c) => a + c.length, 0);
  const all = new Float32Array(n);
  let o = 0;
  for (const c of chunks) { all.set(c, o); o += c.length; }
  const step = rate / RATE;
  const out = new Int16Array(Math.floor(n / step));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(i * step), b = Math.min(n, Math.floor((i + 1) * step));
    let s = 0;
    for (let j = a; j < b; j++) s += all[j];
    const v = Math.max(-1, Math.min(1, s / Math.max(1, b - a)));
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  const head = new DataView(new ArrayBuffer(44));
  const str = (off, t) => { for (let i = 0; i < t.length; i++) head.setUint8(off + i, t.charCodeAt(i)); };
  str(0, 'RIFF'); head.setUint32(4, 36 + out.byteLength, true); str(8, 'WAVEfmt ');
  head.setUint32(16, 16, true); head.setUint16(20, 1, true); head.setUint16(22, 1, true);
  head.setUint32(24, RATE, true); head.setUint32(28, RATE * 2, true);
  head.setUint16(32, 2, true); head.setUint16(34, 16, true);
  str(36, 'data'); head.setUint32(40, out.byteLength, true);
  return new Blob([head, out], { type: 'audio/wav' });
}
