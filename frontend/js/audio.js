// Plays the AI voices and local SFX in the browser.
// Owner: Person B. Two paths: `playUrl` for a finished clip (TTS mp3 the backend saved),
// `enqueue` for raw 16-bit 24 kHz mono PCM chunks (Higgs TTS 3 `pcm` streaming or Realtime
// `response.output_audio.delta` after base64 decode).

const SAMPLE_RATE = 24000;

export function createPlayer() {
  const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
  let nextAt = 0;
  let sources = [];
  const sfxEl = document.getElementById('sfx');
  let clip = null;

  function enqueue(pcmBytes) {
    const int16 = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, Math.floor(pcmBytes.byteLength / 2));
    const f32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;
    const buf = ctx.createBuffer(1, f32.length, SAMPLE_RATE);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, nextAt);
    src.start(at);
    nextAt = at + buf.duration;
    sources.push(src);
    src.onended = () => { sources = sources.filter((s) => s !== src); };
  }

  function playUrl(url) {
    cancel();
    clip = new Audio(url);
    clip.play().catch(() => {});
  }

  function cancel() {           // barge-in / Skip: drop everything queued
    sources.forEach((s) => { try { s.stop(); } catch { /* already stopped */ } });
    sources = [];
    nextAt = 0;
    if (clip) { clip.pause(); clip = null; }
  }

  function playSfx(url) {
    if (!sfxEl || !url) return;
    sfxEl.src = url;
    sfxEl.play().catch(() => {});
  }

  return { enqueue, playUrl, cancel, playSfx, resume: () => ctx.resume(), get busy() { return sources.length > 0 || Boolean(clip && !clip.paused); } };
}
