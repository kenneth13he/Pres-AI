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
    audio.preload = 'auto';
    audio.load();
    current = { audio, clip };
    const done = () => {
      if (current?.audio !== audio) return;
      current = null;
      // Keep the face exactly where the line ended: switch to this clip's own rest loop,
      // which starts on its last frame. Until it's ready, hold the last frame. The tile never
      // goes back to the photo.
      const tile = clip.el?.closest('.tile-call');
      const idle = tile?.querySelector('video.idle');
      if (tile && idle && clip.rest) {
        idle.src = clip.rest;
        idle.addEventListener('loadeddata', () => {
          idle.currentTime = 0;
          idle.play().catch(() => {});
          tile.classList.add('idle-on');
          tile.classList.remove('live');
        }, { once: true });
      }
      onClipEnd(clip);
      next();
    };
    audio.onended = done;
    audio.onerror = done;
    const begin = () => {
      if (current?.audio !== audio) return;          // skipped while we waited
      onClipStart(clip);
      if (clip.kind === 'video' && clip.el) clip.el.closest('.tile-call')?.classList.add('live');
      audio.play().catch(done);
    };
    // One continuous shot: the new line was rendered from the frame the resting loop starts
    // on, so wait for the loop to come round to that frame and cut exactly there.
    const idle = clip.el?.closest('.tile-call')?.querySelector('video.idle');
    if (clip.kind === 'video' && idle && !idle.paused && idle.duration) waitForLoopStart(idle, begin);
    else begin();
  }

  function waitForLoopStart(loop, go) {
    let last = loop.currentTime;
    let fired = false;
    const fire = () => { if (!fired) { fired = true; go(); } };
    const tick = () => {
      if (fired) return;
      const t = loop.currentTime;
      if (t + 0.05 < last || t < 0.04) return fire();  // wrapped back to frame 0
      last = t;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    setTimeout(fire, (loop.duration / (loop.playbackRate || 1)) * 1000 + 150);  // never wait longer than one loop
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
      // Skip/Pause mid-line: freeze on the current frame rather than jumping anywhere.
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
