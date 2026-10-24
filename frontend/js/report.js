import { getReport, getSession } from '/js/api.js';
import { bootReport } from '/js/report_controller.js';
import { createReportView } from '/js/report_view.js';

await bootReport({ view: createReportView(document), location: window.location,
  getReport: (id) => getReport(encodeURIComponent(id)),
  getSession: (id) => getSession(encodeURIComponent(id)) });
