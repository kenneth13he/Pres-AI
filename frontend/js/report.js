// /report: dimensions, metrics (with caveats), Recovery cards, key moments, improvements.
// Owner: Person A with C (P0-12). Shape: spec/contracts.schema.json (Report).

import { getReport } from '/js/api.js';

const qs = new URLSearchParams(location.search);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const dash = '<span class="text-slate-600" title="not measured">—</span>';
const fmt = (v, unit = '') => (v == null ? dash : `${v}${unit}`);
const t = (ms) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
const nice = (k) => k.replace(/_/g, ' ');

let r;
try { r = await getReport(qs.get('session') ?? ''); }
catch (e) { document.body.innerHTML = `<main class="p-10 text-slate-400">No report yet (${esc(e.message)}). <a class="underline" href="/">Start over</a>.</main>`; throw e; }

$('caveats').textContent = r.metric_caveats.join(' ');

$('dimensions').innerHTML = Object.entries(r.dimensions).map(([k, v]) => `
  <div class="rounded-xl border border-slate-800 p-3 text-center ${v == null ? 'opacity-60' : ''}">
    <div class="text-3xl font-semibold ${v != null && v >= 75 ? 'text-emerald-300' : v != null && v < 50 ? 'text-amber-300' : ''}">${fmt(v)}</div>
    <div class="text-xs uppercase tracking-wide text-slate-500">${nice(k)}</div>
  </div>`).join('');

$('metrics').innerHTML = Object.entries(r.metrics).map(([k, v]) =>
  `<span class="rounded-full bg-slate-900 px-3 py-1">${nice(k)}: ${fmt(v)}</span>`).join('');

$('curveballs').innerHTML = r.curveballs.length ? r.curveballs.map((c) => {
  const rec = c.recovery;
  const gap = rec?.resume_after_ms == null ? '<span class="text-slate-600">not measured</span>' : `${(rec.resume_after_ms / 1000).toFixed(1)} s`;
  return `
  <div class="rounded-xl border border-slate-800 p-4">
    <div class="flex items-baseline justify-between gap-4">
      <div class="font-medium">${nice(c.kind)} <span class="text-xs text-slate-500">at ${t(c.at_ms)} · ${nice(c.resolution)}</span></div>
      <div class="text-2xl font-semibold">${fmt(rec?.score)}<span class="text-xs text-slate-500">/100</span></div>
    </div>
    <div class="mt-1 text-sm text-slate-300">Resumed after: ${gap}</div>
    ${rec?.evidence ? `<blockquote class="mt-2 border-l-2 border-slate-700 pl-3 text-sm text-slate-400">“${esc(rec.evidence)}”</blockquote>` : ''}
    ${rec?.suggestion ? `<div class="mt-2 text-sm text-cyan-300">${esc(rec.suggestion)}</div>` : ''}
    ${c.resolution === 'skipped' ? '<div class="mt-2 text-xs text-slate-500">Skipped — never scored against you.</div>' : ''}
  </div>`;
}).join('') : '<p class="text-sm text-slate-500">No curveball fired this session.</p>';

$('moments').innerHTML = r.key_moments.length ? r.key_moments.map((m) => `
  <li class="flex gap-3"><span class="font-mono text-slate-500">${t(m.at_ms)}</span>
    <span class="rounded bg-slate-800 px-1.5 text-xs">${esc(m.type)}</span><span>${esc(m.summary)}</span></li>`).join('')
  : '<li class="text-slate-500">Nothing happened yet.</li>';

$('improvements').innerHTML = r.improvements.length ? r.improvements.map((i) => `
  <div class="rounded-xl border border-slate-800 p-4 text-sm">
    <div class="font-medium">${esc(i.observation)}</div>
    <blockquote class="mt-1 border-l-2 border-slate-700 pl-3 text-slate-400">“${esc(i.evidence)}”</blockquote>
    <div class="mt-2 text-cyan-300">${esc(i.suggestion)}</div>
  </div>`).join('') : '<p class="text-sm text-slate-500">Nothing flagged.</p>';

$('personas').innerHTML = r.persona_feedback.map((p) =>
  `<div><span class="text-slate-500">${esc(p.persona_id)}:</span> ${esc(p.comment)}</div>`).join('');
