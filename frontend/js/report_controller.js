// Loading and validation are injectable so the report can be checked without a browser.
export class ReportDataError extends Error {}
const object = (value) => value != null && typeof value === 'object' && !Array.isArray(value);
const numeric = (value) => value == null || typeof value === 'number' && Number.isFinite(value);

export function validateReport(value) {
  const invalid = () => { throw new ReportDataError('The saved report is incomplete. Return to the room and finish the session, then try again.'); };
  if (!object(value) || typeof value.session_id !== 'string' || !value.session_id
    || !object(value.dimensions) || !object(value.metrics) || !numeric(value.overall_score)) invalid();
  if (![...Object.values(value.dimensions), ...Object.values(value.metrics)].every(numeric)) invalid();
  const report = { ...value };
  for (const key of ['metric_caveats', 'strengths', 'improvements', 'curveballs', 'key_moments', 'persona_feedback']) {
    if (value[key] != null && !Array.isArray(value[key])) invalid();
    report[key] = value[key] ?? [];
  }
  if (![...report.metric_caveats, ...report.strengths].every((item) => typeof item === 'string')) invalid();
  for (const item of report.improvements) {
    if (!object(item) || !['observation', 'evidence', 'suggestion'].every((key) => typeof item[key] === 'string')) invalid();
  }
  for (const item of report.curveballs) {
    if (!object(item) || typeof item.kind !== 'string' || typeof item.resolution !== 'string'
      || !Number.isFinite(item.at_ms) || item.at_ms < 0) invalid();
    if (item.recovery != null && (!object(item.recovery)
      || !numeric(item.recovery.score) || !numeric(item.recovery.resume_after_ms))) invalid();
  }
  for (const item of report.key_moments) {
    if (!object(item) || typeof item.summary !== 'string' || typeof item.type !== 'string'
      || !Number.isFinite(item.at_ms) || item.at_ms < 0) invalid();
  }
  for (const item of report.persona_feedback) {
    if (!object(item) || typeof item.persona_id !== 'string' || typeof item.comment !== 'string'
      || !numeric(item.score)) invalid();
  }
  return report;
}

export async function bootReport({ view, getReport, getSession, location,
  now = () => performance.now(), setTimeout = globalThis.setTimeout,
  clearTimeout = globalThis.clearTimeout, maxWaitMs = 45000, pollIntervalMs = 1000, signal }) {
  const query = new URLSearchParams(location.search);
  const session = query.get('session')?.trim(), mock = query.has('mock');
  let generation = 0, disposed = false;
  const timers = new Set(), cancelled = Symbol('cancelled'), timedOut = Symbol('timed out');
  function scheduled(ms, value) {
    let entry;
    const promise = new Promise((resolve) => {
      entry = { resolve, timer: setTimeout(() => { timers.delete(entry); resolve(value); }, ms) };
      timers.add(entry);
    });
    return { promise, cancel() { clearTimeout(entry.timer); timers.delete(entry); } };
  }
  function cancelPending() {
    for (const entry of timers) { clearTimeout(entry.timer); entry.resolve(cancelled); }
    timers.clear();
  }
  function dispose() {
    if (disposed) return;
    disposed = true; generation++; cancelPending(); signal?.removeEventListener('abort', dispose);
  }
  signal?.addEventListener('abort', dispose, { once: true });
  if (signal?.aborted) dispose();
  view.links({ room: session ? `/room.html?session=${encodeURIComponent(session)}` : null,
    home: '/', mock });
  async function reload() {
    if (disposed) return;
    const request = ++generation;
    cancelPending();
    if (!session && !mock) {
      view.state('missing', 'Choose a session to view its report. Start a new presentation, or return using a session report link.');
      return;
    }
    view.state('loading', 'Loading your session report…');
    let report, snapshot, preparing = false, attempts = 0;
    const deadline = now() + maxWaitMs;
    const render = () => view.render(report, { mock, personas: snapshot?.config?.personas || [] });
    const timeoutMessage = () => view.state('error', preparing
      ? 'Your session has ended. Feedback is still being prepared. Try again in a moment.'
      : 'Could not load this report. Check that the local app is running, then try again.');
    if (!mock && getSession) {
      // Names enrich a completed report; an optional snapshot must never block it.
      Promise.resolve().then(() => getSession(session)).then((value) => {
        snapshot = value;
        if (report && request === generation && !disposed) render();
      }).catch(() => {});
    }
    while (!disposed && request === generation) {
      if (now() >= deadline || attempts++ > Math.ceil(maxWaitMs / pollIntervalMs)) {
        timeoutMessage(); return;
      }
      const timeout = scheduled(Math.max(1, deadline - now()), timedOut);
      try {
        const result = await Promise.race([
          Promise.resolve(getReport(session || 'demo-001')), timeout.promise,
        ]);
        if (request !== generation || disposed || result === cancelled) return;
        if (result === timedOut) { timeoutMessage(); return; }
        report = validateReport(result); render();
        view.state('ready', mock ? 'Illustrative report loaded. These are sample values.' : 'Your session report is ready.');
        return;
      } catch (error) {
        if (request !== generation || disposed) return;
        const detail = String(error?.message ?? ''), status = error?.status;
        const conflict = status == null ? /\b409\b/.test(detail) : status === 409;
        if (conflict && (error?.code === 'report_preparing' || /\breport_preparing\b/.test(detail))) {
          preparing = true;
          view.state('loading', 'Your session has ended. Preparing feedback…');
        } else if (conflict) {
          view.state('unfinished', 'Your session is still in progress. Complete Q&A in the room to generate the report, then try again.'); return;
        } else if (status === 404 || status == null && /\b404\b/.test(detail)) {
          view.state('missing', 'This session could not be found. Check the report link or start a new presentation.'); return;
        } else {
          view.state('error', error instanceof ReportDataError ? error.message
            : 'Could not load this report. Check that the local app is running, then try again.'); return;
        }
      } finally { timeout.cancel(); }
      if (now() >= deadline) { timeoutMessage(); return; }
      await scheduled(Math.min(pollIntervalMs, deadline - now())).promise;
    }
  }
  view.bindRetry(reload);
  await reload();
  return { reload, dispose };
}
