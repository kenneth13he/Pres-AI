import { getReport, getSession } from '/js/api.js';
import { bootReport } from '/js/report_controller.js';
import { createReportView } from '/js/report_view.js';

const page = new AbortController();
window.addEventListener('pagehide', () => page.abort(), { once: true });
await bootReport({ view: createReportView(document), location: window.location, signal: page.signal,
  getReport: (id) => getReport(encodeURIComponent(id)),
  getSession: (id) => getSession(encodeURIComponent(id)) });
