// Plays the panel's voices (Higgs TTS clips announced by `audio_status`) strictly one at a
// time in arrival order — only one AI voice ever speaks (CLAUDE.md §8). Owner: Person B.

export function createPlayer({ onClipStart = () => {}, onClipEnd = () => {} } = {}) {
  const queue = [];
  let current = null; // {audio, clip}
  let enabled = true;
  const sfxEl = document.getElementById('sfx');

  function next() {
    if (current || !queue.length) return;
    const clip = queue.shift();
    const audio = new Audio(clip.url);
    current = { audio, clip };
    const done = () => {
      if (current?.audio !== audio) return;
      current = null;
      onClipEnd(clip);
      next();
    };
    audio.onended = done;
    audio.onerror = done;
    onClipStart(clip);
    audio.play().catch(done);
  }

  return {
    playClip(clip) { if (enabled) { queue.push(clip); next(); } },
    cancel() { // Skip / Pause: stop the voice and drop what is queued
      queue.length = 0;
      if (current) { const { audio, clip } = current; current = null; audio.pause(); onClipEnd(clip); }
    },
    playSfx(url) { if (sfxEl && url) { sfxEl.src = url; sfxEl.play().catch(() => {}); } },
    setEnabled(v) { enabled = v; if (!v) this.cancel(); },
    get busy() { return Boolean(current) || queue.length > 0; },
  };
}
