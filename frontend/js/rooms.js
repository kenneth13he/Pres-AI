// Shared by home, setup, room and report: room settings, seat layouts, curveball names, helpers.
// Layouts are ported from docs/design/Pres AI App.dc.html (`layout()`); all values are % of a 16:9 stage.

export const MINT = 'oklch(0.82 0.15 150)';
export const CORAL = 'oklch(0.78 0.17 22)';

// SessionConfig.personas is min 2 / max 3 (spec/contracts.py). The design allows 1–10; raising
// it is a contract change for the team (docs/design/README.md, Step 3).
export const MIN_GUESTS = 2;
export const MAX_GUESTS = 3;

export const SETTINGS = [
  { id: 'video', name: 'Video call', sub: 'Shared screen, gallery' },
  { id: 'classroom', name: 'Classroom', sub: 'Board up front, desks' },
  { id: 'boardroom', name: 'Boardroom', sub: 'Long table' },
  { id: 'lecture', name: 'Lecture hall', sub: 'Stage, tiered seats' },
  { id: 'interview', name: 'Interview panel', sub: 'Panel across a table' },
];
export const settingById = (id) => SETTINGS.find((s) => s.id === id) ?? SETTINGS[0];
export const PRESET_SETTING = { startup_pitch: 'video', class_presentation: 'classroom', research_defense: 'lecture', job_interview: 'interview' };

export const KINDS = [
  ['time_crunch', 'Time crunch', 'Prioritising', "“We're running behind — 60 seconds.”"],
  ['slides_down', 'Slides down', 'No crutch', 'Viewer goes black until restored.'],
  ['heckler', 'Heckler', 'Composure', 'A guest challenges the core idea bluntly.'],
  ['latecomer', 'Latecomer', 'Summarising', '“Give me the 20-second version?”'],
  ['bait', 'Bait', 'Honesty', 'A question just outside what you covered.'],
  ['distraction', 'Distraction', 'Focus', 'Phone, door or cough mid-sentence.'],
  ['vip_arrives', 'VIP arrives', 'Shifting', 'The decision-maker joins for two minutes.'],
  ['crosstalk', 'Crosstalk', 'Control', 'Two guests disagree.'],
  ['fact_check', 'Fact check', 'Evidence', 'A guest cites a contradicting number.'],
  ['elevator', 'Elevator', 'Compression', '“30 seconds, no slides.”'],
  ['plain_language', 'Plain language', 'Jargon', '“Explain it with no background.”'],
  ['dead_room', 'Dead room', 'Confidence', 'Blank faces for 45 seconds.'],
].map(([kind, name, tests, what]) => ({ kind, name, tests, what }));
export const kindName = (k) => KINDS.find((x) => x.kind === k)?.name ?? k;

export const SEAT_HUES = [25, 75, 200, 255, 310, 160, 45, 230, 285, 120];
export const YOU_AT = { video: { x: 2, y: 85, w: 14, h: 11 }, classroom: { x: 9, y: 22, w: 14, h: 11 }, boardroom: { x: 43, y: 46, w: 14, h: 11 }, lecture: { x: 13, y: 17, w: 14, h: 11 }, interview: { x: 16, y: 62, w: 14, h: 11 } };

function rows(counts, y0, w, gap, rowGap) {
  const out = [];
  counts.forEach((c, r) => {
    const tot = c * w + (c - 1) * gap, x0 = (100 - tot) / 2;
    for (let i = 0; i < c; i++) out.push({ x: x0 + i * (w + gap), y: y0 + r * (w + rowGap), w, h: w });
  });
  return out;
}
function split(n, cap) { const r = Math.ceil(n / cap), base = Math.floor(n / r), ex = n % r; return Array.from({ length: r }, (_, i) => base + (i < ex ? 1 : 0)); }
function fill(n, caps) { const out = []; let left = n; for (const c of caps) { if (left <= 0) break; out.push(Math.min(c, left)); left -= c; } return out; }

/** Stage background, slide rect, decor rects and n seat rects for a room setting. */
export function layout(setting, n) {
  if (setting === 'video') {
    if (n <= 2) { const w = 31, tot = n * w + (n - 1) * 2; return { bg: '#101214', slide: { x: 2, y: 17, w: 64, h: 64 }, decor: [], seats: Array.from({ length: n }, (_, i) => ({ x: 67.5, y: (100 - tot) / 2 + i * (w + 2), w, h: w })) }; }
    const w = 15.25, gap = 1.5, rs = Math.ceil(n / 2), tot = rs * w + (rs - 1) * gap, y0 = (100 - tot) / 2;
    return { bg: '#101214', slide: { x: 1.5, y: 18, w: 64, h: 64 }, decor: [], seats: Array.from({ length: n }, (_, i) => ({ x: 67 + (i % 2) * (w + gap), y: y0 + Math.floor(i / 2) * (w + gap), w, h: w })) };
  }
  if (setting === 'classroom') {
    const w = n <= 3 ? 18 : 14;
    return { bg: '#111315', slide: { x: 27, y: 4, w: 46, h: 46 }, decor: [{ x: 24, y: 2.5, w: 52, h: 49, c: '#1a1d20', r: '1cqw' }, { x: 0, y: 54, w: 100, h: 46, c: '#0e1012', r: '0' }], seats: rows(split(n, 5), 57, w, 2.5, 3) };
  }
  if (setting === 'boardroom') {
    const pos = [[16, 44], [72, 44], [16, 57.5], [72, 57.5], [16, 71], [72, 71], [16, 84.5], [72, 84.5], [16, 12], [72, 12]];
    return { bg: '#101214', slide: { x: 32, y: 3, w: 36, h: 36 }, decor: [{ x: 31, y: 43, w: 38, h: 54, c: '#191c1f', r: '1.4cqw' }], seats: pos.slice(0, n).map(([x, y]) => ({ x, y, w: 12, h: 12 })) };
  }
  if (setting === 'lecture') {
    const cs = fill(n, [3, 3, 4]);
    return { bg: '#0f1113', slide: { x: 30, y: 3, w: 40, h: 40 }, decor: cs.map((_, r) => ({ x: 4, y: 46.5 + r * 15.5, w: 92, h: 14.5, c: `rgba(255,255,255,${0.02 + r * 0.012})`, r: '0.6cqw' })), seats: rows(cs, 47.25, 13, 2.5, 2.5) };
  }
  if (n <= 3) return { bg: '#101214', slide: { x: 33, y: 46, w: 34, h: 34 }, decor: [{ x: 6, y: 40, w: 88, h: 0.6, c: '#2a2f32', r: '0' }], seats: rows([n], 5, 29, 2.5, 0) };
  return { bg: '#101214', slide: { x: 33, y: 50, w: 34, h: 34 }, decor: [{ x: 6, y: 44.5, w: 88, h: 0.6, c: '#2a2f32', r: '0' }], seats: rows(split(n, 5), 3, 17, 2, 2) };
}

/** Thumbnail shapes for a setting card (4 seats, the presenter dot, the screen). */
export function thumbShapes(id) {
  const l = layout(id, 4);
  return [
    ...l.decor.map((d) => ({ ...d, c: d.c === '#191c1f' || d.c === '#2a2f32' ? '#2f2a24' : d.c, r: d.r === '0' ? '1px' : '3px' })),
    { ...l.slide, c: 'oklch(0.82 0.15 150 / .16)', b: `1px solid ${'oklch(0.82 0.15 150 / .6)'}`, r: '3px', label: id === 'interview' ? 'Laptop' : id === 'classroom' ? 'Board' : 'Screen', lc: MINT },
    ...l.seats.map((t, j) => ({ ...t, c: `oklch(0.74 0.1 ${SEAT_HUES[j]})`, r: '3px' })),
    { ...YOU_AT[id], c: CORAL, r: '999px', label: 'You', lc: '#1a0705' },
  ];
}
export const rect = (s) => `left:${s.x}%;top:${s.y}%;width:${s.w}%;height:${s.h}%`;
export const shapesHtml = (shapes, fs = 8) => shapes.map((s) => `<div style="position:absolute;${rect(s)};border-radius:${s.r ?? '3px'};background:${s.c};border:${s.b ?? '0'};display:grid;place-items:center;font:600 ${fs}px var(--mono);letter-spacing:.05em;text-transform:uppercase;color:${s.lc ?? 'transparent'};overflow:hidden;white-space:nowrap">${s.label ?? ''}</div>`).join('');

/** Tile background: the guest's photo if they have one, else a gradient seeded by roster position. */
export function tileBg(img, i) {
  if (img) return `url('${img}') center / cover no-repeat`; // single quotes: used inside style="…"
  const h = (i * 47 + 150) % 360;
  return `linear-gradient(160deg, oklch(0.27 0.025 ${h}), oklch(0.19 0.012 ${h}))`;
}
export const cq = (w, k, min) => `max(${min}px, ${(w * k).toFixed(2)}cqw)`;

export const pad = (n) => String(n).padStart(2, '0');
export const fmtS = (s) => `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
export const fmtMs = (ms) => fmtS(Math.floor(ms / 1000));
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

// What the room and report need that the backend doesn't keep: the room setting, the guests'
// photos (kept in the browser, never uploaded) and the config for "Run it again".
const META = (id) => `presai.session.${id}`;
export function saveSessionMeta(id, meta) { try { sessionStorage.setItem(META(id), JSON.stringify(meta)); } catch { /* private mode */ } }
export function loadSessionMeta(id) { try { return JSON.parse(sessionStorage.getItem(META(id)) || 'null'); } catch { return null; } }
