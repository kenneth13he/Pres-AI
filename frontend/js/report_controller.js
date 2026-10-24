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

export async function bootReport({ view, getReport, getSession, location }) {
  const query = new URLSearchParams(location.search);
  const session = query.get('session')?.trim(), mock = query.has('mock');
  let generation = 0;
  view.links({ room: session ? `/room.html?session=${encodeURIComponent(session)}` : null,
    home: '/', mock });
  async function reload() {
    const request = ++generation;
    if (!session && !mock) {
      view.state('missing', 'Choose a session to view its report. Start a new presentation, or return using a session report link.');
      return;
    }
    view.state('loading', 'Loading your session report…');
    try {
      const details = !mock && getSession
        ? Promise.resolve().then(() => getSession(session)).catch(() => null) : null;
      const report = validateReport(await getReport(session || 'demo-001'));
      const snapshot = await details;
      if (request !== generation) return;
      view.render(report, { mock, personas: snapshot?.config?.personas || [] });
      view.state('ready', mock ? 'Illustrative report loaded. These are sample values.' : 'Your session report is ready.');
    } catch (error) {
      if (request !== generation) return;
      const detail = String(error?.message ?? '');
      const status = error?.status;
      if (status === 409 || /\b409\b/.test(detail)) {
        view.state('unfinished', 'Your session is still in progress. Finish Q&A in the room to generate the report, then try again.');
      } else if (status === 404 || /\b404\b/.test(detail)) {
        view.state('missing', 'This session could not be found. Check the report link or start a new presentation.');
      } else {
        view.state('error', error instanceof ReportDataError ? error.message
          : 'Could not load this report. Check that the local app is running, then try again.');
      }
    }
  }
  view.bindRetry(reload);
  await reload();
  return { reload };
}
