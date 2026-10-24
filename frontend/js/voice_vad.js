// Manual boundaries: keep vendor turn_detection:null. A safety limit discards audio;
// only a natural pause or an explicit push-to-talk release may submit an utterance.
export function createUtteranceGate({ onAppend, onCommit, onClear = () => {},
  onLimit = () => {}, clock = () => performance.now(), pushToTalk = false,
  threshold = 0.015, endThreshold = 0.008, silenceMs = 1100, maxTurnMs = 60000 } = {}) {
  const releaseThreshold = Math.min(threshold, endThreshold);
  let enabled = true, before = [], beforeMs = 0, active = null, blocked = null;
  function reset() { before = []; beforeMs = 0; active = null; blocked = null; }
  function finish() {
    if (blocked) { reset(); return; } // Release acknowledges an overlong discarded turn.
    if (!active) return;
    const interval = active;
    reset();
    if (interval.start != null && interval.duration >= 100 && interval.voiced >= (pushToTalk ? 60 : 150)) {
      onCommit({ start_ms: Math.max(0, Math.round(interval.start)),
        end_ms: Math.max(0, Math.round(interval.end)) });
    } else onClear();
  }
  function discardAtLimit() {
    active = null; before = []; beforeMs = 0; blocked = { silence: 0 };
    onClear(); onLimit({ max_turn_ms: maxTurnMs, push_to_talk: pushToTalk });
  }
  function feed(bytes, level = 0) {
    if (!enabled || !bytes.byteLength) return;
    const duration = bytes.byteLength / 48, now = clock();
    if (blocked) {
      if (!pushToTalk) {
        blocked.silence = level >= releaseThreshold ? 0 : blocked.silence + duration;
        if (blocked.silence >= silenceMs) reset();
      }
      return;
    }
    const voiced = level >= (active ? releaseThreshold : threshold);
    if (!active && !pushToTalk && !voiced) {
      before.push({ bytes: bytes.slice(), duration }); beforeMs += duration;
      while (beforeMs > 200 && before.length) beforeMs -= before.shift().duration;
      return;
    }
    if (!active) {
      active = { start: null, end: now, duration: beforeMs, voiced: 0, silence: 0 };
      for (const frame of before) onAppend(frame.bytes);
      before = []; beforeMs = 0;
    }
    active.duration += duration;
    if (active.duration > maxTurnMs) { discardAtLimit(); return; }
    onAppend(bytes);
    if (voiced) {
      if (active.start == null) active.start = now - duration;
      active.end = now; active.voiced += duration; active.silence = 0;
    } else active.silence += duration;
    if (!pushToTalk && active.silence >= silenceMs) finish();
  }
  return {
    feed, commit: finish,
    setEnabled(value) {
      const next = Boolean(value);
      if (enabled === next) return;
      enabled = next; reset(); if (!enabled) onClear();
    },
    reset,
  };
}
