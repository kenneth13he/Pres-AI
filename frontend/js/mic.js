// Microphone capture: level meter, push-to-talk, and a transcript source.
// Owner: Person B (bridge) with Person A (meter UI). Nothing here is recorded or stored.
//
// Hour-5 fallback (CLAUDE.md §4): if Higgs Realtime isn't carrying the audio yet, the
// Web Speech API (Chrome/Edge/Safari) can produce `transcript_segment`s so the question/
// answer loop still works. Person B's bridge replaces `onSegment` with real STT.

export async function startMic({ onLevel, onSegment, pushToTalk = false, pttKey = 'Space' }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });

  // Level meter: RMS of the time-domain signal, eased, once per animation frame.
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  let level = 0;
  let running = true;
  const meter = () => {
    if (!running) return;
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    level = Math.max(Math.min(1, Math.sqrt(sum / buf.length) * 4), level * 0.85);
    onLevel?.(level);
    requestAnimationFrame(meter);
  };
  requestAnimationFrame(meter);

  // TODO(B): Shape 1 → stream PCM16 @ 24 kHz to the Realtime WebSocket (ephemeral key from
  //          POST /api/.../client_secret, to be added by B); forward
  //          conversation.item.input_audio_transcription.completed as a segment.
  //          Fallback → window.SpeechRecognition / webkitSpeechRecognition, final results
  //          only → onSegment({ start_ms, end_ms, text, speaker: 'presenter', confidence }).
  // TODO(A): pushToTalk → only forward audio/segments while pttKey is held.

  return {
    hasSTT: false,
    stream,
    stop() { running = false; stream.getTracks().forEach((t) => t.stop()); ctx.close(); },
  };
}
