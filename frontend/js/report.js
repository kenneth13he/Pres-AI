// /report: dimensions, metrics (with caveats), Recovery cards, key moments, improvements.
// Owner: Person A with C (P0-12). Shape: spec/contracts.schema.json (Report).
// Build against /report.html?mock=1 (frontend/mocks/report.json) first.

import { getReport } from '/js/api.js';

const qs = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);
const fmt = (v, unit = '') => (v == null ? '<span class="text-slate-600">—</span>' : `${v}${unit}`);
const t = (ms) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

let r;
try { r = await getReport(qs.get('session') ?? ''); }
catch (e) { document.body.innerHTML = `<main class="p-10 text-slate-400">No report yet (${e.message}). <a class="underline" href="/">Start over</a>.</main>`; throw e; }

$('caveats').textContent = r.metric_caveats.join(' ');

// TODO(A): #dimensions — one tile per r.dimensions entry; null renders as "—", never 0.
// TODO(A): #metrics — chips for r.metrics.
// TODO(A): #curveballs — one card per r.curveballs: kind, at_ms, resolution, recovery.score,
//          "Resumed after X s" (or "not measured"), evidence quote, suggestion.
//          Empty → "No curveball fired this session."
// TODO(A): #moments — timeline of r.key_moments (t(at_ms), type badge, summary).
// TODO(A): #improvements — observation, evidence quote, suggestion.
// TODO(A): #personas — one line per r.persona_feedback.
$('moments').innerHTML = r.key_moments.map((m) => `<li>${t(m.at_ms)} · ${m.type} · ${m.summary}</li>`).join('');
void fmt;
