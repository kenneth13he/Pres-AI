// Regressions for patient end-of-turn detection and safe long-input limits.
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../frontend/js/voice_vad.js', import.meta.url), 'utf8');
const { createUtteranceGate } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
function capture(options = {}) {
  let now = 0, appended = 0, clears = 0;
  const commits = [], limits = [];
  const gate = createUtteranceGate({ ...options, clock: () => now,
    onAppend: (bytes) => { appended += bytes.byteLength; },
    onCommit: (interval) => commits.push(interval), onClear: () => { clears++; },
    onLimit: (limit) => limits.push(limit),
  });
  return { gate, commits, limits,
    get clears() { return clears; }, get appended() { return appended; },
    feed(ms, level = 0.2) {
      for (let remaining = ms; remaining > 0;) {
        const chunk = Math.min(20, remaining); remaining -= chunk; now += chunk;
        gate.feed(new Uint8Array(chunk * 48), level);
      }
    },
  };
}
test('an 800 ms mid-question pause and quieter continuation remain one complete turn', () => {
  const run = capture();
  run.feed(1000); run.feed(800, 0);
  assert.equal(run.commits.length, 0);
  run.feed(500, 0.01); // Below onset threshold, above release threshold.
  run.feed(1080, 0); assert.equal(run.commits.length, 0);
  run.feed(20, 0);
  assert.deepEqual(run.commits, [{ start_ms: 0, end_ms: 2300 }]);
});
test('20+ seconds of continuous live speech never commits before the presenter pauses', () => {
  const run = capture(); run.feed(30000);
  assert.equal(run.commits.length, 0); assert.equal(run.limits.length, 0);
  run.feed(1100, 0);
  assert.deepEqual(run.commits, [{ start_ms: 0, end_ms: 30000 }]);
});
test('exceeding 60 seconds clears once and discards the entire residual live turn', () => {
  const run = capture(); run.feed(60000);
  assert.equal(run.commits.length, 0); assert.equal(run.limits.length, 0);
  run.feed(20);
  assert.equal(run.clears, 1);
  assert.deepEqual(run.limits, [{ max_turn_ms: 60000, push_to_talk: false }]);
  const sent = run.appended;
  run.feed(10000); run.feed(800, 0); run.feed(1000); // Still the same ongoing question.
  assert.equal(run.appended, sent); assert.equal(run.commits.length, 0); assert.equal(run.clears, 1);
  run.feed(1100, 0); // A fresh complete pause unlocks; no discarded question is sent.
  assert.equal(run.commits.length, 0);
  run.feed(200); run.feed(1100, 0);
  assert.deepEqual(run.commits, [{ start_ms: 72920, end_ms: 73120 }]);
});
test('PTT holds through long pauses and over 20 seconds, then submits once on release', () => {
  const run = capture({ pushToTalk: true });
  run.feed(25000); run.feed(5000, 0); run.feed(1000);
  assert.equal(run.commits.length, 0); assert.equal(run.limits.length, 0);
  run.feed(500, 0); run.gate.commit(); run.gate.commit();
  assert.deepEqual(run.commits, [{ start_ms: 0, end_ms: 31000 }]);
});
test('an overlong PTT hold cannot auto-restart or submit a truncated question on release', () => {
  const run = capture({ pushToTalk: true }); run.feed(60020);
  assert.deepEqual(run.limits, [{ max_turn_ms: 60000, push_to_talk: true }]);
  const sent = run.appended; run.feed(20000, 0); run.feed(1000);
  assert.equal(run.appended, sent); assert.equal(run.clears, 1); assert.equal(run.commits.length, 0);
  run.gate.commit(); assert.equal(run.commits.length, 0); // Releases the blocked hold only.
  run.feed(200); run.gate.commit();
  assert.deepEqual(run.commits, [{ start_ms: 81020, end_ms: 81220 }]);
});
test('patient endpoint and duration limit can be tuned without forcing a commit', () => {
  const run = capture({ silenceMs: 1500, maxTurnMs: 2000 });
  run.feed(200); run.feed(1200, 0); assert.equal(run.commits.length, 0);
  run.feed(100); run.feed(520, 0); // Cross the bound; discard rather than force an endpoint.
  assert.equal(run.commits.length, 0); assert.equal(run.clears, 1);
  assert.deepEqual(run.limits, [{ max_turn_ms: 2000, push_to_talk: false }]);
});
test('deactivation drops partial input and an overlong latch without submitting either', () => {
  const run = capture({ pushToTalk: true, maxTurnMs: 200 });
  run.feed(220); run.gate.setEnabled(false); run.gate.commit();
  assert.equal(run.commits.length, 0); assert.equal(run.limits.length, 1);
  run.feed(1000); run.gate.setEnabled(true); run.feed(200); run.gate.setEnabled(false); run.gate.commit();
  assert.equal(run.commits.length, 0); assert.equal(run.limits.length, 1);
});

test('PTT recovery timestamps begin with detected speech, not a silent held button', () => {
  const run = capture({ pushToTalk: true });
  run.feed(2000, 0); run.feed(200); run.feed(1000, 0); run.gate.commit();
  assert.deepEqual(run.commits, [{ start_ms: 2000, end_ms: 2200 }]);
});
test('a silent held turn is discarded without generating a transcript or reply', () => {
  const run = capture({ pushToTalk: true }); run.feed(5000, 0); run.gate.commit();
  assert.equal(run.commits.length, 0); assert.equal(run.clears, 1);
});
