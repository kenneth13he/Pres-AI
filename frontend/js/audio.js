// Person B: raw signed PCM16 little-endian, mono, 24 kHz. No audio is retained.
const SAMPLE_RATE = 24000;

export function createPlayer() {
  const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
  const sources = new Set();
  const idleWaiters = new Set();
  let nextAt = 0, trailingByte = null, closed = false;

  function notifyIdle() {
    if (sources.size) return;
    for (const resolve of idleWaiters) resolve();
    idleWaiters.clear();
  }

  function enqueue(pcmBytes) {
    if (closed) return;
    let bytes = pcmBytes instanceof Uint8Array ? pcmBytes : new Uint8Array(pcmBytes);
    if (trailingByte !== null) {
      const joined = new Uint8Array(bytes.length + 1);
      joined[0] = trailingByte; joined.set(bytes, 1); bytes = joined;
    }
    trailingByte = bytes.length % 2 ? bytes[bytes.length - 1] : null;
    const count = Math.floor(bytes.length / 2);
    if (!count) return;
    const samples = new Float32Array(count);
    const view = new DataView(bytes.buffer, bytes.byteOffset, count * 2);
    for (let i = 0; i < count; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
    const buffer = ctx.createBuffer(1, count, SAMPLE_RATE);
    buffer.getChannelData(0).set(samples);
    const source = ctx.createBufferSource();
    source.buffer = buffer; source.connect(ctx.destination); sources.add(source);
    source.onended = () => {
      sources.delete(source); source.disconnect(); notifyIdle();
    };
    nextAt = Math.max(nextAt, ctx.currentTime + 0.01);
    source.start(nextAt); nextAt += buffer.duration;
  }

  function cancel() {
    for (const source of [...sources]) {
      source.onended = null;
      try { source.stop(); } catch { /* Already ended. */ }
      source.disconnect();
    }
    sources.clear(); nextAt = 0; trailingByte = null;
    const sfx = document.getElementById('sfx');
    if (sfx) { sfx.pause(); sfx.currentTime = 0; }
    notifyIdle();
  }

  function playSfx(url) {
    const el = document.getElementById('sfx');
    if (el && url && !closed) { el.src = url; el.play().catch(() => {}); }
  }

  return {
    enqueue, cancel, playSfx,
    resume: () => closed ? Promise.resolve() : ctx.resume(),
    whenIdle: () => sources.size ? new Promise((resolve) => idleWaiters.add(resolve)) : Promise.resolve(),
    async close() {
      if (closed) return;
      closed = true; cancel(); await ctx.close();
    },
    get busy() { return sources.size > 0; },
  };
}
