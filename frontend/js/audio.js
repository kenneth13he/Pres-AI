// Plays the AI voices and local SFX in the browser.
// Owner: Person B. Clips (Higgs TTS mp3s announced by `audio_status`) play strictly one at a
// time in arrival order — only one AI voice ever speaks (CLAUDE.md §8). `enqueuePcm` is the
// raw 16-bit 24 kHz path for the Realtime/streaming shape later.

const SAMPLE_RATE = 24000;

export function createPlayer({ onClipStart = () => {}, onClipEnd = () => {}, onIdle = () => {} } = {}) {
  const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
  const queue = [];        // [{url, speaker, text}]
  let current = null;      // {audio, clip}
  let enabled = true;
  const sfxEl = document.getElementById('sfx');

  function next() {
    if (current || !queue.length) { if (!current) onIdle(); return; }
    const clip = queue.shift();
    // A talking-head clip plays in the speaker's seat (its own <video>, audio included);
    // a voice-only clip plays through a detached <audio>.
    const audio = clip.kind === 'video' && clip.el ? clip.el : new Audio();
    audio.src = clip.url;
    current = { audio, clip };
    onClipStart(clip);
    if (clip.kind === 'video' && clip.el) clip.el.closest('.tile-call')?.classList.add('live');
    const done = () => {
      if (current?.audio !== audio) return;
      current = null;
      // The clip ends at rest (silent tail), so rewind the listening loop to its rest pose
      // and blend into it slowly. Without a loop, hold the last frame (never the still).
      const portrait = clip.el?.closest('.tile-call');
      if (portrait?.classList.contains('idle-on')) {
        const idle = portrait.querySelector('video.idle');
        if (idle) { idle.currentTime = 0; idle.play().catch(() => {}); }
        portrait.classList.remove('live');
      }
      onClipEnd(clip);
      next();
    };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
  }

  function playClip(clip) {
    if (!enabled) return;
    queue.push(clip);
    next();
  }

  function cancel() {           // Skip / Pause: stop the voice and drop what is queued
    queue.length = 0;
    if (current) {
      const { audio, clip } = current; current = null; audio.pause();
      const portrait = clip.el?.closest('.tile-call');
      if (portrait?.classList.contains('idle-on')) portrait.classList.remove('live');
      onClipEnd(clip);
    }
    onIdle();
  }

  let nextAt = 0;
  function enqueuePcm(pcmBytes) {
    const int16 = new Int16Array(pcmBytes.buffer, pcmBytes.byteOffset, Math.floor(pcmBytes.byteLength / 2));
    const f32 = Float32Array.from(int16, (v) => v / 32768);
    const buf = ctx.createBuffer(1, f32.length, SAMPLE_RATE);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf; src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, nextAt);
    src.start(at); nextAt = at + buf.duration;
  }

  function playSfx(url) {
    if (!sfxEl || !url) return;
    sfxEl.src = url;
    sfxEl.play().catch(() => {});
  }

  return {
    playClip, cancel, enqueuePcm, playSfx,
    resume: () => ctx.resume(),
    setEnabled(v) { enabled = v; if (!v) cancel(); },
    get busy() { return Boolean(current) || queue.length > 0; },
    get speaker() { return current?.clip.speaker ?? null; },
  };
}
