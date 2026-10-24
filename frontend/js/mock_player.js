// Replays frontend/mocks/<name>.json with its real timing so every room state can be built
// and demoed without a backend. Timestamps in the fixture are ms since session start.
// pause()/resume() freeze the replay clock; emit() injects a local event (Pause/Skip/Restore).

export async function playMock(name, onEvent, { speed = 1 } = {}) {
  const data = await (await fetch(`/mocks/${name}.json`)).json();
  let t0 = performance.now();
  let pausedAt = null;
  let i = 0;
  let stopped = false;
  const elapsed = () => ((pausedAt ?? performance.now()) - t0) * speed;
  const step = () => {
    if (stopped) return;
    if (pausedAt == null) {
      while (i < data.events.length && data.events[i].timestamp_ms <= elapsed()) onEvent(data.events[i++]);
    }
    if (i < data.events.length) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
  return {
    config: data.config,
    preset: data.preset,
    send: (msg) => console.debug('[mock] client →', msg),
    emit: (type, payload = {}) => onEvent({ type, session_id: 'mock', timestamp_ms: Math.round(elapsed()), payload }),
    pause: () => { if (pausedAt == null) pausedAt = performance.now(); },
    resume: () => { if (pausedAt != null) { t0 += performance.now() - pausedAt; pausedAt = null; } },
    close: () => { stopped = true; },
  };
}
