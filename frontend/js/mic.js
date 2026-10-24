// Microphone capture: level meter, push-to-talk, and a transcript source.
// Owner: Person B (bridge) with Person A (meter UI). Nothing here is recorded or stored.
//
// Transcript source today: the browser's Web Speech API (Chrome/Edge/Safari), final results
// only → one `transcript_segment` each, timestamps relative to Start (the session clock).
// This is the CLAUDE.md hour-5 fallback; Person B's Higgs bridge replaces `onSegment`.

export async function startMic({ onLevel, onSegment, pushToTalk = false, pttKey = 'Space' }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });
  const t0 = performance.now();
  let live = !pushToTalk;
  let muted = false;     // true while an AI voice plays, so we never transcribe the room
  let stopped = false;

  // ---- level meter ------------------------------------------------------------------
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Uint8Array(analyser.frequencyBinCount);
  let raf;
  const meter = () => {
    analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) { const d = (v - 128) / 128; sum += d * d; }
    onLevel(live && !muted ? Math.min(1, Math.sqrt(sum / buf.length) * 4) : 0);
    raf = requestAnimationFrame(meter);
  };
  meter();

  // ---- browser STT ----------------------------------------------------------------
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  let segStart = null;
  if (SR && onSegment) {
    rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (segStart == null) segStart = Math.round(performance.now() - t0);
        if (r.isFinal) {
          const text = r[0].transcript.trim();
          const end = Math.round(performance.now() - t0);
          if (text && live && !muted) onSegment({ start_ms: segStart, end_ms: end, text, speaker: 'presenter', confidence: r[0].confidence ?? null });
          segStart = null;
        }
      }
    };
    rec.onend = () => { if (!stopped) { try { rec.start(); } catch { /* already running */ } } };
    rec.onerror = (e) => { if (e.error !== 'no-speech' && e.error !== 'aborted') console.warn('[mic] stt', e.error); };
    try { rec.start(); } catch { /* ignore */ }
  }

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
    hasSTT: Boolean(SR),
    stream,
    setMuted(v) { muted = v; if (v) segStart = null; },
    stop() {
      stopped = true;
      cancelAnimationFrame(raf);
      try { rec?.stop(); } catch { /* ignore */ }
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      removeEventListener('keydown', kd); removeEventListener('keyup', ku);
    },
  };
}
