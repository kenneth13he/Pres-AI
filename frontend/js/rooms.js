// Shared by home, setup, room and report: room settings, seat layouts, curveball names, helpers.
// Layouts are ported from docs/design/Pres AI App.dc.html (`layout()`); all values are % of a 16:9 stage.

export const MINT = 'oklch(0.82 0.15 150)';
export const CORAL = 'oklch(0.78 0.17 22)';

// SessionConfig.personas is min 1 / max 3 (spec/contracts.py). The design allows 1–10; raising
// the max is a contract change for the team (docs/design/README.md, Step 3).
export const MIN_GUESTS = 1;
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

// The guests fill whatever space the room leaves them: tiles grow as guests leave, so one
// guest gets the whole region. The grid is the one whose cells come closest to the faces'
// 3:4 portrait shape (the stage is 16:9, so a cell's real aspect is w·16 / h·9).
const GAP_X = 1.2, GAP_Y = GAP_X * 16 / 9;
const FACE = 3 / 4;
function fillSeats(r, n) {
  if (n <= 0) return [];
  let best = null;
  for (let cols = 1; cols <= n; cols++) {
    const rowsN = Math.ceil(n / cols);
    const w = (r.w - (cols - 1) * GAP_X) / cols, h = (r.h - (rowsN - 1) * GAP_Y) / rowsN;
    const miss = Math.abs(Math.log((w * 16) / (h * 9) / FACE));
    if (!best || miss < best.miss) best = { cols, rowsN, w, h, miss };
  }
  const { cols, rowsN, w, h } = best;
  return Array.from({ length: n }, (_, i) => {
    const row = Math.floor(i / cols), inRow = row === rowsN - 1 ? n - row * cols : cols;
    const x0 = r.x + (r.w - (inRow * w + (inRow - 1) * GAP_X)) / 2; // a short last row is centred
    return { x: x0 + (i % cols) * (w + GAP_X), y: r.y + row * (h + GAP_Y), w, h };
  });
}
// The presenter's own camera (4:3): 12% of the stage wide.
const you = (x, y) => ({ x, y, w: 12, h: 16 });

/** Stage background, slide rect (null without a deck), decor, n seat rects and the presenter's
 *  seat for a room setting. Without slides every setting is a gallery: the guests fill the stage. */
export function layout(setting, n, deck = true) {
  if (!deck) {
    return { bg: '#101214', slide: null, decor: [], seats: fillSeats({ x: 1.5, y: 2.5, w: 97, h: 95 }, n), you: you(85, 5) };
  }
  if (setting === 'classroom') {
    return { bg: '#111315', slide: { x: 30, y: 4, w: 40, h: 40 }, decor: [{ x: 27, y: 2.5, w: 46, h: 43, c: '#1a1d20', r: '1cqw' }, { x: 0, y: 48, w: 100, h: 52, c: '#0e1012', r: '0' }], seats: fillSeats({ x: 3, y: 51, w: 94, h: 46 }, n), you: you(9, 14) };
  }
  if (setting === 'boardroom') {
    return { bg: '#101214', slide: { x: 34, y: 3, w: 32, h: 32 }, decor: [{ x: 5, y: 39, w: 90, h: 59, c: '#191c1f', r: '1.4cqw' }], seats: fillSeats({ x: 7, y: 42, w: 86, h: 53 }, n), you: you(8, 8) };
  }
  if (setting === 'lecture') {
    return { bg: '#0f1113', slide: { x: 30, y: 3, w: 40, h: 40 }, decor: [0, 1, 2].map((r) => ({ x: 3, y: 46 + r * 17.5, w: 94, h: 16.5, c: `rgba(255,255,255,${0.02 + r * 0.012})`, r: '0.6cqw' })), seats: fillSeats({ x: 4, y: 47, w: 92, h: 50 }, n), you: you(13, 14) };
  }
  if (setting === 'interview') {
    return { bg: '#101214', slide: { x: 36, y: 55, w: 28, h: 28 }, decor: [{ x: 4, y: 51, w: 92, h: 0.6, c: '#2a2f32', r: '0' }], seats: fillSeats({ x: 5, y: 3, w: 90, h: 45 }, n), you: you(14, 62) };
  }
  // video call: the shared screen on the left, the guests fill the right
  return { bg: '#101214', slide: { x: 1.5, y: 10, w: 62, h: 62 }, decor: [], seats: fillSeats({ x: 65, y: 2.5, w: 33.5, h: 95 }, n), you: you(1.5, 78) };
}

/** Thumbnail shapes for a setting card (4 seats, the presenter dot, the screen). */
export function thumbShapes(id) {
  const l = layout(id, 4);
  return [
    ...l.decor.map((d) => ({ ...d, c: d.c === '#191c1f' || d.c === '#2a2f32' ? '#2f2a24' : d.c, r: d.r === '0' ? '1px' : '3px' })),
    { ...l.slide, c: 'oklch(0.82 0.15 150 / .16)', b: `1px solid ${'oklch(0.82 0.15 150 / .6)'}`, r: '3px', label: id === 'interview' ? 'Laptop' : id === 'classroom' ? 'Board' : 'Screen', lc: MINT },
    ...l.seats.map((t, j) => ({ ...t, c: `oklch(0.74 0.1 ${SEAT_HUES[j]})`, r: '3px' })),
    { ...l.you, c: CORAL, r: '999px', label: 'You', lc: '#1a0705' },
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
export const cq = (w, k, min, max) => (max ? `clamp(${min}px, ${(w * k).toFixed(2)}cqw, ${max}px)` : `max(${min}px, ${(w * k).toFixed(2)}cqw)`);

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
