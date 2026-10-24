// Homepage: self-playing demo room, hide-on-scroll nav, reveal-on-scroll, interactive setup cards.
// Design: docs/design/Home A - Premium Dark.dc.html. The demo is a scripted illustration, not a
// live session; sound uses the browser's speechSynthesis as a stand-in for Higgs TTS voices.

import { CORAL, KINDS, MAX_GUESTS, MIN_GUESTS, MINT, SETTINGS, fmtS, shapesHtml, thumbShapes } from '/js/rooms.js?v=adaptive-room-1';

const $ = (id) => document.getElementById(id);
const PEOPLE = [
  { id: 'vc', name: 'Dana', role: 'Skeptical VC', bg: 'linear-gradient(160deg,#1a2220,#121615)' },
  { id: 'student', name: 'Sam', role: 'Confused Student', bg: 'linear-gradient(160deg,#1b1d24,#121418)' },
  { id: 'professor', name: 'Prof. Okafor', role: 'Picky Professor', bg: 'linear-gradient(160deg,#221d1b,#161312)' },
];
const BEATS = [
  { d: 2600, phase: 'presenting', who: 'You', text: 'We can get 100,000 customers in six months.' },
  { d: 3000, phase: 'interruption', speak: 'vc', who: 'Dana', text: 'What evidence supports reaching 100,000 users?' },
  { d: 2800, phase: 'answering', who: 'You', text: 'Two campus pilots, three hundred weekly actives and growing.' },
  { d: 1800, phase: 'answering', speak: 'vc', who: 'Dana', text: 'Fair enough, go on.' },
  { d: 3200, phase: 'curveball', cb: 'SLIDES DOWN', black: true, who: 'Moderator', text: 'Sorry — the projector just disconnected. Can you keep going?' },
  { d: 2600, phase: 'recovering', cb: 'SLIDES DOWN', black: true, who: 'You', text: 'So, the problem again is onboarding.' },
  { d: 2000, phase: 'presenting', who: 'Moderator', text: 'Back on track after 3.4 s.' },
  { d: 3000, phase: 'presenting', speak: 'student', who: 'Sam', text: "Wait — what does 'weekly actives' mean?" },
  { d: 3800, phase: 'curveball', cb: 'TIME CRUNCH', crunch: true, who: 'Moderator', text: "Sorry — we're running behind. You've got sixty seconds." },
];
const VOICE = { You: { pitch: 1, rate: 1.05, vi: 0 }, Dana: { pitch: 0.82, rate: 1.12, vi: 1 }, Sam: { pitch: 1.35, rate: 1.05, vi: 2 }, Moderator: { pitch: 1, rate: 0.98, vi: 3 } };
const CURVEBALL_COPY = {
  time_crunch: "“We're running behind — 60 seconds.” The timer turns red.", slides_down: 'The screen goes black. Keep going until it comes back.',
  heckler: 'A guest challenges the core idea, bluntly.', latecomer: '“Give me the 20-second version?”', bait: 'A plausible question just outside what you covered.',
  distraction: 'A phone, a door, a cough mid-sentence.', vip_arrives: 'The decision-maker joins for two minutes.', crosstalk: 'Two guests disagree. Take the room back.',
  fact_check: 'A guest cites a number that contradicts yours.', elevator: '“30 seconds, no slides.” The slides dim.',
  plain_language: '“Explain it to someone with no background.”', dead_room: 'Blank faces for 45 seconds. No feedback.',
};
const ROOM_SUB = { video: 'Grid of faces, shared screen', classroom: 'Board up front, desks in rows', boardroom: 'Long table, decision makers', lecture: 'Stage, tiered seating', interview: 'Three across the table' };

// ---- demo room ------------------------------------------------------------------------------
const synth = window.speechSynthesis ?? null;
let voices = [];
const loadVoices = () => { const v = synth.getVoices(); const en = v.filter((x) => /^en/i.test(x.lang)); voices = en.length ? en : v; };
if (synth) { loadVoices(); synth.onvoiceschanged = loadVoices; }

const D = { beat: 0, t: 72, crunch: 60, tick: 0, log: [], playing: true, sound: false };
let timer = null;

$('d-tiles').innerHTML = PEOPLE.map((p) => `
  <div data-id="${p.id}" style="position:relative;border-radius:12px;overflow:hidden;background:${p.bg};border:1px solid #1f2426;transition:box-shadow .25s;min-height:56px">
    <div style="position:absolute;inset:0;background:repeating-linear-gradient(135deg,rgba(255,255,255,.035) 0 8px,transparent 8px 16px)"></div>
    <div style="position:absolute;left:10px;bottom:8px;display:flex;align-items:center;gap:8px;font-size:13px"><span style="font-weight:700">${p.name}</span><span style="color:#8a9190">${p.role}</span></div>
    <div class="bars" style="position:absolute;right:10px;bottom:10px;height:14px">${'<span style="height:3px"></span>'.repeat(4)}</div>
  </div>`).join('');

function renderDemo() {
  const b = BEATS[D.beat];
  const hot = b.phase === 'curveball' || b.phase === 'recovering';
  const ph = $('d-phase');
  ph.textContent = b.phase;
  ph.className = `phase-pill ${hot ? 'hot' : b.phase === 'presenting' ? '' : 'mint'}`;
  $('d-timer').textContent = b.crunch ? `00:${String(D.crunch).padStart(2, '0')}` : fmtS(D.t);
  $('d-timer').style.color = b.crunch ? CORAL : '';
  $('d-progress').style.width = `${((D.beat + 1) / BEATS.length) * 100}%`;
  $('d-slide').style.opacity = b.black ? 0 : 1;
  $('d-black').style.opacity = b.black ? 1 : 0;
  const cb = $('d-cb');
  cb.style.opacity = b.cb ? 1 : 0; cb.style.transform = `translateY(${b.cb ? 0 : -8}px)`;
  if (b.cb) cb.textContent = `CURVEBALL · ${b.cb}`;
  document.querySelectorAll('#d-tiles > div').forEach((el) => {
    el.style.boxShadow = b.speak === el.dataset.id ? `0 0 0 2px ${MINT}, 0 0 32px oklch(0.82 0.15 150 / .35)` : 'none';
  });
  $('d-captions').innerHTML = D.log.map((c, i, a) => `<div style="display:flex;gap:12px;font-size:15px;line-height:1.4;opacity:${i === a.length - 1 ? 1 : 0.45}">
    <span style="flex:none;width:92px;font-weight:700;color:${c.who === 'You' ? '#eceeed' : c.who === 'Moderator' ? CORAL : MINT}">${c.who}</span><span style="color:#d2d6d5">${c.text}</span></div>`).join('');
  $('d-veil').style.background = `rgba(10,11,13,${D.playing ? 0 : 0.45})`;
  const vp = $('d-veil-pill'); vp.style.opacity = D.playing ? 0 : 1; vp.style.transform = `scale(${D.playing ? 0.92 : 1})`;
  $('d-play').innerHTML = D.playing
    ? '<span style="display:flex;gap:3px"><span style="width:3px;height:11px;border-radius:1px;background:currentColor"></span><span style="width:3px;height:11px;border-radius:1px;background:currentColor"></span></span>Pause'
    : '<span style="width:0;height:0;border-top:6px solid transparent;border-bottom:6px solid transparent;border-left:9px solid currentColor"></span>Play';
  $('d-play').title = D.playing ? 'Pause the demo' : 'Resume the demo';
  $('d-sound').classList.toggle('on', D.sound);
  $('d-slabel').textContent = !synth ? 'No audio' : D.sound ? 'Sound on' : 'Sound off';
  $('d-sound').title = D.sound ? 'Mute the room' : 'Hear the room';
}
function animate() {
  const b = BEATS[D.beat], k = D.tick;
  document.querySelectorAll('#d-tiles > div').forEach((el, i) => {
    const on = b.speak === el.dataset.id && D.playing;
    el.querySelectorAll('.bars > span').forEach((s, j) => { s.style.height = `${on ? 4 + ((k * 7 + j * 5 + i * 3) % 11) : 3}px`; });
  });
  $('d-sbars').innerHTML = [0, 1, 2].map((j) => `<span style="width:2px;border-radius:1px;background:currentColor;height:${D.sound && D.playing ? 3 + ((k * 5 + j * 7) % 9) : 3}px;transition:height .15s"></span>`).join('');
}
function schedule(ms, i) { clearTimeout(timer); timer = setTimeout(() => { if (D.playing && D.beat === i) advance((i + 1) % BEATS.length); }, ms); }
function speak(i) {
  const b = BEATS[i]; if (!synth) return false;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(b.text), cfg = VOICE[b.who] || VOICE.You;
  if (voices.length) u.voice = voices[cfg.vi % voices.length];
  u.pitch = cfg.pitch; u.rate = cfg.rate;
  u.onend = () => { if (D.sound && D.playing && D.beat === i) schedule(380, i); };
  synth.speak(u);
  return true;
}
function advance(i) {
  const b = BEATS[i];
  if (i === 0) { D.t = 72; D.log = []; }
  D.beat = i; D.crunch = b.crunch ? D.crunch : 60;
  D.log = D.log.concat([{ who: b.who, text: b.text }]).slice(-3);
  renderDemo();
  if (D.sound && speak(i)) schedule(b.d + 9000, i); else schedule(b.d, i);
}
$('d-play').onclick = () => {
  if (D.playing) { clearTimeout(timer); synth?.cancel(); D.playing = false; renderDemo(); }
  else { D.playing = true; advance((D.beat + 1) % BEATS.length); }
};
$('d-sound').onclick = () => {
  if (!synth) return;
  D.sound = !D.sound; renderDemo();
  if (!D.playing) return;
  if (D.sound) { speak(D.beat); schedule(BEATS[D.beat].d + 9000, D.beat); }
  else { synth.cancel(); schedule(1200, D.beat); }
};
setInterval(() => { if (D.playing) { D.tick++; animate(); } }, 140);
setInterval(() => {
  if (!D.playing) return;
  D.t++;
  if (BEATS[D.beat].crunch) D.crunch = Math.max(0, D.crunch - 1);
  renderDemo();
}, 1000);
advance(0);

// ---- nav: solid past 24px, hides on scroll down past 140px, shows on scroll up ---------------
const nav = $('nav');
let lastY = window.scrollY, raf = null;
window.addEventListener('scroll', () => {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = null;
    const y = window.scrollY, dy = y - lastY;
    nav.classList.toggle('solid', y > 24);
    if (Math.abs(dy) > 6) { nav.classList.toggle('hide', dy > 0 && y > 140); lastY = y; }
    if (y < 140) nav.classList.remove('hide');
  });
}, { passive: true });

// ---- reveal on scroll -----------------------------------------------------------------------
const reveal = [...document.querySelectorAll('[data-reveal]')];
if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
  reveal.forEach((el) => { el.style.opacity = '0'; });
  const io = new IntersectionObserver((entries) => {
    let n = 0;
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      io.unobserve(e.target);
      e.target.style.opacity = '';
      e.target.animate([{ opacity: 0, translate: '0 32px' }, { opacity: 1, translate: '0 0' }], { duration: 900, delay: (n++) * 90, easing: 'cubic-bezier(.22,.8,.24,1)', fill: 'backwards' });
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
  reveal.forEach((el) => io.observe(el));
}

// ---- "Three clicks" cards -------------------------------------------------------------------
const HW = { profile: 'default', deck: false, guests: MAX_GUESTS };
function renderHow() {
  $('hw-profiles').innerHTML = [['default', 'Default'], ['mine', 'My profile']].map(([id, label]) =>
    `<button data-hw="${id}" class="${HW.profile === id ? 'on' : ''}" style="padding:8px;border-radius:7px;font-size:13px">${label}</button>`).join('');
  $('hw-note').textContent = HW.profile === 'default' ? 'Start with a ready-made audience.' : 'Save your audience, room and pacing for the next deck.';
  const deck = $('hw-deck');
  deck.textContent = HW.deck ? 'Example · pitch-deck.pdf · 12 slides' : 'Preview a PDF deck';
  deck.style.borderColor = HW.deck ? 'oklch(0.82 0.15 150 / .7)' : '#2f3437';
  deck.style.background = HW.deck ? 'oklch(0.82 0.15 150 / .07)' : 'transparent';
  $('hw-deck-note').textContent = HW.deck ? 'Upload your PDF in the setup wizard.' : 'Optional. No deck? The room listens only.';
  $('hw-guests').textContent = HW.guests;
  $('hw-seats').innerHTML = Array.from({ length: MAX_GUESTS }, (_, i) => `<span style="width:28px;height:16px;border-radius:4px;background:${i < HW.guests ? 'oklch(0.82 0.15 150 / .75)' : '#1f2426'};transition:background .3s ease"></span>`).join('');
}
$('hw-profiles').onclick = (e) => { const b = e.target.closest('[data-hw]'); if (b) { HW.profile = b.dataset.hw; renderHow(); } };
$('hw-deck').onclick = () => { HW.deck = !HW.deck; renderHow(); };
$('hw-down').onclick = () => { HW.guests = Math.max(MIN_GUESTS, HW.guests - 1); renderHow(); };
$('hw-up').onclick = () => { HW.guests = Math.min(MAX_GUESTS, HW.guests + 1); renderHow(); };
renderHow();

// ---- rooms and curveballs -------------------------------------------------------------------
$('rooms-grid').innerHTML = SETTINGS.map((r) => `
  <div class="room-card">
    <div style="position:relative;aspect-ratio:16/10;border-radius:10px;background:#131617;border:1px solid #1c2022;overflow:hidden">${shapesHtml(thumbShapes(r.id), 9)}</div>
    <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px 12px;font-size:12px;color:#8a9190">
      <span style="display:flex;align-items:center;gap:5px"><span style="width:10px;height:8px;border-radius:2px;background:oklch(0.82 0.15 150 / .16);border:1px solid oklch(0.82 0.15 150 / .6)"></span>Screen</span>
      <span style="display:flex;align-items:center;gap:5px"><span style="width:10px;height:8px;border-radius:2px;background:oklch(0.74 0.1 75)"></span>Guests</span>
      <span style="display:flex;align-items:center;gap:5px"><span style="width:8px;height:8px;border-radius:50%;background:${CORAL}"></span>You</span>
    </div>
    <div style="margin-top:14px;font-size:18px;font-weight:700">${r.name}</div>
    <div style="margin-top:4px;font-size:14px;color:#8a9190">${ROOM_SUB[r.id]}</div>
  </div>`).join('');

$('cb-grid').innerHTML = KINDS.map((k) => `
  <div class="cb-cell">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><span style="font-size:17px;font-weight:700">${k.name}</span><span class="mono" style="font-size:11px;color:#6f7775">${k.tests}</span></div>
    <div style="margin-top:10px;font-size:15px;line-height:1.5;color:#a3aaa8">${CURVEBALL_COPY[k.kind]}</div>
  </div>`).join('');

window.addEventListener('pagehide', () => { D.playing = false; clearTimeout(timer); synth?.cancel(); });
