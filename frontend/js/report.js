// /report: dimensions, metrics (with caveats), Recovery cards, key moments, improvements, audience.
// Owner: Person A with C (P0-12). Shape: spec/contracts.schema.json (Report).
// Design: docs/design/Pres AI App.dc.html (report step). Nulls render as "—", never 0.

import { createSession, getReport, getSession, isMock } from '/js/api.js';
import { CORAL, MINT, esc, fmtMs, fmtS, kindName, loadSessionMeta, saveSessionMeta, settingById } from '/js/rooms.js';

const qs = new URLSearchParams(location.search);
const sessionId = qs.get('session') ?? '';
const $ = (id) => document.getElementById(id);
const dash = '<span style="color:var(--off)">—</span>';

// The panel grades the talk after the call ends (up to ~30 s); wait for it.
let r;
for (let i = 0; ; i++) {
  try { r = await getReport(sessionId); break; }
  catch (e) {
    if (i >= 25) {
      $('meta').textContent = 'NO REPORT YET';
      $('caveats').innerHTML = `The session hasn't produced a report (${esc(e.message.slice(0, 160))}). <a href="/setup.html" style="color:var(--mint)">Start a new session</a>.`;
      throw e;
    }
    $('meta').textContent = 'GRADING';
    $('caveats').textContent = 'The panel is writing your report…';
    await new Promise((ok) => setTimeout(ok, 2000));
  }
}

const meta = loadSessionMeta(isMock() ? 'mock' : sessionId);
let config = meta?.config;
if (!config && isMock()) config = (await (await fetch('/mocks/demo_session.json')).json()).config;
if (!config && !isMock()) config = await getSession(sessionId).then((s) => s.config).catch(() => null); // opened without /setup (another tab, a shared link)
const personas = config?.personas ?? [];
const nameOf = (id) => personas.find((p) => p.id === id) ?? { name: id, role: '' };

const n = personas.length;
const lastMoment = Math.max(0, ...r.key_moments.map((m) => m.at_ms));
const duration = meta?.elapsed_s != null ? fmtS(meta.elapsed_s) : fmtMs(lastMoment);
$('meta').textContent = `${settingById(meta?.setting ?? 'video').name.toUpperCase()} · ${n} ${n === 1 ? 'GUEST' : 'GUESTS'} · ${duration}`;
$('caveats').textContent = r.metric_caveats.join(' ');
$('overall').innerHTML = r.overall_score == null ? '' : `${r.overall_score}<span style="font-size:18px;color:var(--muted)">/100</span>`;

const DIMS = [['clarity', 'Clarity'], ['evidence', 'Evidence'], ['structure', 'Structure'], ['question_handling', 'Question handling'], ['recovery', 'Recovery']];
$('dimensions').innerHTML = DIMS.map(([k, label]) => {
  const v = r.dimensions[k];
  return `<div style="padding:18px;border-radius:14px;border:1px solid var(--border);background:var(--surface)"><div style="font-size:13px;color:var(--muted)">${label}</div><div class="mono" style="margin-top:10px;font-size:34px;font-weight:500;color:${v == null ? 'var(--off)' : MINT}">${v ?? '—'}</div></div>`;
}).join('');

const METRICS = [['words_per_minute', 'words per minute'], ['filler_words', 'filler words'], ['unanswered_questions', 'unanswered questions'], ['curveballs_faced', 'curveballs faced'], ['skipped', 'skipped']];
$('metrics').innerHTML = METRICS.map(([k, label]) => `<span style="padding:8px 12px;border-radius:10px;background:var(--surface);border:1px solid var(--border);font-size:14px;white-space:nowrap"><span class="mono">${r.metrics[k] ?? dash}</span> <span style="color:var(--muted)">${label}</span></span>`).join('');

$('curveballs').innerHTML = r.curveballs.length ? r.curveballs.map((c) => {
  const rec = c.recovery;
  const resume = rec?.resume_after_ms != null ? `Resumed after ${(rec.resume_after_ms / 1000).toFixed(1)} s` : c.resolution === 'skipped' ? 'Skipped · not scored' : 'Timing not measured';
  return `<div class="card" style="display:grid;grid-template-columns:1fr auto;gap:8px 20px">
    <div><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span style="font-size:17px;font-weight:700">${esc(kindName(c.kind))}</span><span class="mono" style="font-size:12px;color:var(--muted)">at ${fmtMs(c.at_ms)} · ${esc(c.resolution.replace(/_/g, ' '))}</span></div>
    <div style="margin-top:6px;font-size:14px;color:var(--muted)">${resume}</div></div>
    <div class="mono" style="font-size:30px;font-weight:500;color:${rec?.score != null ? MINT : 'var(--off)'}">${rec?.score ?? '—'}</div>
    ${rec?.evidence ? `<div class="quote" style="grid-column:1 / -1;margin-top:6px">“${esc(rec.evidence)}”</div>` : ''}
    ${rec?.suggestion ? `<div style="grid-column:1 / -1;font-size:14px;color:#c5cac9">${esc(rec.suggestion)}</div>` : ''}
  </div>`;
}).join('') : '<div class="card" style="font-size:15px;color:var(--muted)">No curveball fired this session.</div>';

const typeColor = (t) => (t === 'question' ? MINT : t === 'curveball' ? CORAL : 'var(--muted)');
$('moments').innerHTML = r.key_moments.length ? r.key_moments.map((m) => `<li class="moment">
  <span class="mono" style="font-size:13px;color:var(--muted)">${fmtMs(m.at_ms)}</span>
  <span class="badge" style="color:${typeColor(m.type)}">${esc(m.type)}</span>
  <span>${m.persona_id ? `${esc(nameOf(m.persona_id).name)}: ` : ''}${esc(m.summary)}</span></li>`).join('')
  : '<li class="moment" style="grid-template-columns:1fr;color:var(--muted)">Nothing to show yet.</li>';

$('strengths').innerHTML = r.strengths.length
  ? r.strengths.map((s) => `<div class="card" style="font-size:15px;line-height:1.45;color:#d6dad9">${esc(s)}</div>`).join('')
  : '<div class="card" style="font-size:15px;color:var(--muted)">Nothing assessed.</div>';

$('improvements').innerHTML =r.improvements.length ? r.improvements.map((i) => `<div class="card">
  <div style="font-size:17px;font-weight:700">${esc(i.observation)}</div>
  <div class="quote" style="margin-top:10px">“${esc(i.evidence)}”</div>
  <div style="margin-top:10px;font-size:14px;color:#c5cac9">${esc(i.suggestion)}</div></div>`).join('')
  : '<div class="card" style="font-size:15px;color:var(--muted)">No improvements with a quote to back them up.</div>';

$('personas').innerHTML = r.persona_feedback.map((f) => {
  const p = nameOf(f.persona_id);
  return `<div style="padding:16px;border-radius:14px;border:1px solid var(--border);background:var(--surface)">
    <div style="font-size:14px;font-weight:700">${esc(p.name)} <span style="color:var(--muted);font-weight:500">· ${esc(p.role)}${p.custom ? ' · Custom' : ''}</span></div>
    <div style="margin-top:6px;font-size:15px;line-height:1.45;color:#d6dad9">${esc(f.comment)}</div></div>`;
}).join('');

// "Run it again": same config, same room, fresh session.
$('again').onclick = async () => {
  if (isMock() || !config) { location.href = isMock() ? '/room.html?mock=1' : '/setup.html'; return; }
  $('again').disabled = true;
  try {
    const { session_id } = await createSession(config);
    saveSessionMeta(session_id, { setting: meta?.setting, images: meta?.images ?? {}, config });
    location.href = `/room.html?session=${session_id}`;
  } catch { location.href = '/setup.html'; }
};
