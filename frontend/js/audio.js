// Plays the AI voices and local SFX in the browser.
// Owner: Person B. Format: raw 16-bit 24 kHz mono PCM (Higgs TTS 3 `response_format: "pcm"`,
// and Realtime `response.output_audio.delta` after base64 decode).

const SAMPLE_RATE = 24000;

export function createPlayer() {
  const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });

  function enqueue(pcmBytes) {
    // TODO(B): Int16 → Float32, AudioBuffer, gapless scheduling from a running `nextAt`.
  }

  function cancel() {
    // TODO(B): barge-in / Skip — stop every scheduled source and reset the queue.
  }

  function playSfx(url) {
    const el = document.getElementById('sfx');
    if (el && url) { el.src = url; el.play().catch(() => {}); }
  }

  return { enqueue, cancel, playSfx, resume: () => ctx.resume(), get busy() { return false; } };
}
