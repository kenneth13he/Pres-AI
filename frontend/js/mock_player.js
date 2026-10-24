// Replays frontend/mocks/<name>.json with its real timing so every room state can be built
// and demoed without a backend. Timestamps in the fixture are ms since session start.

export async function playMock(name, onEvent, { speed = 1 } = {}) {
  const data = await (await fetch(`/mocks/${name}.json`)).json();
  const t0 = performance.now();
  let i = 0;
  let stopped = false;
  const step = () => {
    if (stopped) return;
    const elapsed = (performance.now() - t0) * speed;
    while (i < data.events.length && data.events[i].timestamp_ms <= elapsed) onEvent(data.events[i++]);
    if (i < data.events.length) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
  return {
    config: data.config,
    preset: data.preset,
    send: (msg) => console.debug('[mock] client →', msg),
    close: () => { stopped = true; },
  };
}
