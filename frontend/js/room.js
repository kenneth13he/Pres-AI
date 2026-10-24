// /room: the room — screen on the wall, the audience seated around a table, voices, bubbles.
// Owner: Person A (P0-7, P0-10). Events: spec/contracts.schema.json (SessionEvent).
// Works against the mock (/room.html?mock=1) and against a live session (/room.html?session=ID).

import { connect, getSession, isMock } from '/js/api.js';
import { createPlayer } from '/js/audio.js';
import { startMic } from '/js/mic.js';
import { playMock } from '/js/mock_player.js';

const qs = new URLSearchParams(location.search);
const sessionId = qs.get('session');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = {
  phase: 'setup', startedAt: null, pausedAt: null, slide: 1, deck: null, personas: [], preset: null,
  timerOverrideUntil: null, activeCurveball: null, link: null, inputMode: 'live', mic: null,
  voices: true, lineTag: {},
};

// ---- people at the table ------------------------------------------------------------
const PALETTE = [
  ['#fbbf24', '#b45309'], ['#a78bfa', '#5b21b6'], ['#34d399', '#047857'],
  ['#f472b6', '#9d174d'], ['#60a5fa', '#1d4ed8'], ['#fb923c', '#c2410c'],
];
const colourFor = (i) => PALETTE[i % PALETTE.length];
const initials = (name) => (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

function seatHtml(p, i, extra = '') {
  const [skin, shirt] = p.id === 'moderator' ? ['#94a3b8', '#334155'] : colourFor(i);
  return `
    <div class="seat tile ${extra}" data-persona="${p.id}">
      <div class="bubble"><span class="tag"></span><span class="text"></span></div>
      <div class="person">
        <span class="thinking">thinking…</span>
        <div class="body" style="background:${shirt}"></div>
        <div class="head" style="background:${skin}">${esc(initials(p.name))}</div>
        <div class="waves"><i></i><i></i><i></i></div>
      </div>
    </div>`;
}

function renderTiles() {
  const people = state.personas;
  const mid = Math.ceil(people.length / 2);
  // moderator sits at the end of the table; the panel fills the middle
  const ordered = [...people.slice(0, mid).map((p, i) => [p, i]), ...people.slice(mid).map((p, i) => [p, mid + i])];
  $('tiles').innerHTML = ordered.map(([p, i]) => seatHtml(p, i)).join('') +
    seatHtml({ id: 'moderator', name: 'Moderator' }, 0, 'moderator');
  $('plates').innerHTML = ordered.map(([p]) => `
    <div class="plate"><b>${esc(p.name)}</b><br>${esc(p.role)}${p.custom ? ' · custom' : ''}</div>`).join('') +
    '<div class="plate" style="opacity:.6"><b>Moderator</b><br>runs the room</div>';
}
const seat = (id) => $('tiles').querySelector(`[data-persona="${id}"]`);

const bubbleTimers = {};
function say(speaker, text, tag, holdMs = 0) {
  const s = seat(speaker);
  if (!s) return;
  clearTimeout(bubbleTimers[speaker]);
  s.querySelector('.bubble .text').textContent = text;
  const t = s.querySelector('.bubble .tag');
  t.textContent = tag ? tag.replace('_', ' ') : '';
  t.style.display = tag ? 'block' : 'none';
  s.querySelector('.bubble').classList.add('show');
  if (holdMs) bubbleTimers[speaker] = setTimeout(() => quiet(speaker), holdMs);
}
function quiet(speaker, after = 0) {
  clearTimeout(bubbleTimers[speaker]);
  bubbleTimers[speaker] = setTimeout(() => {
    const s = seat(speaker);
    s?.querySelector('.bubble').classList.remove('show');
    s?.classList.remove('speaking');
  }, after);
}
const readingMs = (text) => Math.min(9000, 1800 + text.split(/\s+/).length * 330);

// ---- voice: clips play one at a time; the mic is muted while the room talks -------------
const player = createPlayer({
  onClipStart: (clip) => {
    state.mic?.setMuted(true);
    $('tiles').querySelectorAll('.seat.speaking').forEach((x) => x.classList.remove('speaking'));
    seat(clip.speaker)?.classList.add('speaking');
    say(clip.speaker, clip.text, state.lineTag[clip.text]);
  },
  onClipEnd: (clip) => quiet(clip.speaker, 1200),
  onIdle: () => state.mic?.setMuted(false),
});
$('voice-on').onchange = (e) => { state.voices = e.target.checked; player.setEnabled(state.voices); };

// ---- captions -----------------------------------------------------------------------
function caption(speaker, text, tag) {
  const p = state.personas.find((x) => x.id === speaker);
  const who = p ? p.name : speaker === 'presenter' ? 'You' : 'Moderator';
  const mine = speaker === 'presenter';
  const el = document.createElement('div');
  el.className = `caption rounded-lg p-2 ${mine ? 'bg-slate-900/40 text-slate-300' : 'bg-slate-900'}`;
  el.innerHTML = `<span class="text-xs ${mine ? 'text-slate-600' : 'text-cyan-500'}">${esc(who)}${tag ? ` · <span class="text-amber-300">${esc(tag.replace('_', ' '))}</span>` : ''}</span><div>${esc(text)}</div>`;
  $('captions').append(el);
  $('captions').scrollTop = $('captions').scrollHeight;
}

// ---- slides, phase, timer -------------------------------------------------------------
function renderSlide() {
  const s = state.deck?.slides?.[state.slide - 1];
  $('slide-no').textContent = `Slide ${state.slide}${state.deck ? ` / ${state.deck.page_count}` : ''}`;
  const img = $('slide-img'), txt = $('slide-text');
  if (s?.image_url) { img.src = s.image_url; img.classList.remove('hidden'); txt.classList.add('hidden'); txt.classList.remove('grid'); }
  else {
    img.removeAttribute('src'); img.classList.add('hidden');
    txt.textContent = s?.text || 'No deck — the room is listening to you.';
    txt.classList.remove('hidden'); txt.classList.add('grid');
  }
}

function setPhase(p) {
  state.phase = p;
  $('phase').textContent = p.replace('_', ' ');
  $('phase').className = `ml-3 rounded-full px-2 py-0.5 text-xs ${
    p === 'answering' ? 'bg-cyan-500/20 text-cyan-300' : p === 'paused' ? 'bg-amber-500/20 text-amber-300'
    : p === 'qna' ? 'bg-violet-500/20 text-violet-300' : 'bg-slate-800 text-slate-300'}`;
  $('btn-pause').textContent = p === 'paused' ? 'Resume' : 'Pause';
  $('btn-end').textContent = p === 'qna' ? 'Finish → Report' : 'End → Q&A';
  if (p === 'report') {
    const go = () => { location.href = `/report.html?session=${sessionId ?? ''}${isMock() ? '&mock=1' : ''}`; };
    const wait = () => (player.busy ? setTimeout(wait, 400) : setTimeout(go, 1200));
    wait(); // let the last line finish speaking
  }
}

setInterval(() => {
  if (!state.startedAt) return;
  let ms;
  if (state.timerOverrideUntil) { ms = Math.max(0, state.timerOverrideUntil - Date.now()); $('timer').classList.add('urgent'); }
  else { ms = (state.pausedAt ?? Date.now()) - state.startedAt; $('timer').classList.remove('urgent'); }
  const s = Math.floor(ms / 1000);
  $('timer').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}, 250);

// ---- events ---------------------------------------------------------------------------
function onEvent(ev) {
  const p = ev.payload ?? {};
  switch (ev.type) {
    case 'session_started':
      if (state.startedAt == null) state.startedAt = Date.now() - (isMock() ? ev.timestamp_ms : 0);
      if (p.config?.personas) state.personas = p.config.personas;
      if (p.preset) { state.preset = p.preset; $('preset-name').textContent = p.preset.name; }
      renderTiles(); $('btn-start').classList.add('hidden'); break;
    case 'phase_changed':
      if (p.to === 'paused') { state.pausedAt = Date.now(); player.cancel(); }
      if (p.from === 'paused') {
        const d = Date.now() - (state.pausedAt ?? Date.now());
        state.startedAt += d; if (state.timerOverrideUntil) state.timerOverrideUntil += d; state.pausedAt = null;
      }
      setPhase(p.to); break;
    case 'slide_changed': state.slide = p.slide_number; renderSlide(); break;
    case 'transcript_segment': if (p.speaker === 'presenter') caption('presenter', p.text); break;
    case 'question_queued':
      if (p.curveball_id) break; // curveball_triggered already captioned this line
      if (p.follow_up_of) state.lineTag[p.question] = 'follow-up';
      caption(p.persona_id, p.question, p.follow_up_of ? 'follow-up' : null); break;
    case 'ai_speech_started': {
      const isPersona = state.personas.some((x) => x.id === p.speaker);
      if (!isPersona && !state.activeCurveball) caption('moderator', p.line);
      if (!state.voices || isMock()) { // no audio: show the bubble for a reading time instead
        seat(p.speaker)?.classList.add('speaking');
        say(p.speaker, p.line, state.lineTag[p.line], readingMs(p.line));
      } else {
        seat(p.speaker)?.classList.add('thinking'); // TTS is rendering (~2 s)
      }
      break;
    }
    case 'ai_speech_ended': seat(p.speaker)?.classList.remove('thinking'); break;
    case 'audio_status':
      if (p.status === 'clip' && state.voices) {
        seat(p.speaker)?.classList.remove('thinking');
        player.playClip({ url: p.url, speaker: p.speaker, text: p.text });
      } else if (p.status === 'tts_failed') {
        seat(p.speaker)?.classList.remove('thinking');
      }
      $('conn').textContent = p.status === 'ready' ? 'live · voices on' : $('conn').textContent;
      break;
    case 'curveball_triggered': onCurveball(p); break;
    case 'curveball_resolved': clearCurveball(p); break;
    case 'timer_override':
      state.timerOverrideUntil = p.remaining_ms > 0 ? Date.now() + p.remaining_ms : null;
      if (p.remaining_ms === 0) caption('moderator', 'Time. Let’s go to questions.'); break;
    case 'paused': $('slide-viewer').classList.add('opacity-50'); break;
    case 'resumed': $('slide-viewer').classList.remove('opacity-50'); break;
    case 'skipped': caption('moderator', p.reason ? 'Out of time for that one — no penalty.' : 'Skipped — carry on.'); break;
    case 'error': console.warn('[room] error event', p); break;
    case 'session_ended': setPhase('report'); break;
  }
}

function onCurveball(p) {
  state.activeCurveball = p;
  if (p.line) state.lineTag[p.line] = p.kind;
  const viewer = $('slide-viewer');
  switch (p.ui_effect) {
    case 'slides_black': viewer.classList.add('black'); $('overlay-title').textContent = 'Projector disconnected'; $('overlay-sub').textContent = 'Keep going.'; $('btn-restore').classList.remove('hidden'); break;
    case 'slides_dim': viewer.classList.add('dim'); $('overlay-title').textContent = 'Elevator'; $('overlay-sub').textContent = '30 seconds. No slides.'; break;
    case 'tiles_blank': $('tiles').querySelectorAll('.seat').forEach((t) => t.classList.add('blank')); break;
    case 'tile_add':
      if (!state.personas.some((x) => x.id === 'vip')) {
        state.personas.push({ id: 'vip', name: 'The Sponsor', role: 'Decision-maker', focus: ['the ask'] });
        renderTiles();
      }
      seat('vip')?.classList.add('flash'); break;
  }
  if (p.persona_id) { seat(p.persona_id)?.classList.add('flash'); caption(p.persona_id, p.line, p.kind); }
  else if (p.line) caption('moderator', p.line, p.kind);
  if (p.sfx_url) player.playSfx(p.sfx_url);
}

function clearCurveball(p) {
  $('slide-viewer').classList.remove('black', 'dim'); $('btn-restore').classList.add('hidden');
  $('tiles').querySelectorAll('.seat').forEach((t) => t.classList.remove('blank', 'flash'));
  state.activeCurveball = null;
  const r = p.recovery;
  if (r && r.resume_after_ms != null) caption('moderator', `Back on track after ${(r.resume_after_ms / 1000).toFixed(1)} s${r.score != null ? ` · recovery ${r.score}/100` : ''}.`);
}

// ---- controls -------------------------------------------------------------------------
const send = (msg) => state.link?.send(msg);
$('btn-start').onclick = async () => {
  await player.resume();
  send({ type: 'presentation_started' });
  send({ type: 'slide_changed', slide_number: state.slide });
  try {
    const ptt = state.inputMode === 'push_to_talk';
    $('ptt-hint').classList.toggle('hidden', !ptt);
    state.mic = await startMic({
      pushToTalk: ptt,
      onLevel: (v) => { $('mic-level').style.width = `${Math.round(v * 100)}%`; },
      onSegment: (segment) => send({ type: 'transcript_segment', segment }),
    });
    $('mic-label').textContent = state.mic.hasSTT ? 'mic · listening' : 'mic (no STT in this browser)';
  } catch (e) { $('mic-label').textContent = `mic blocked: ${e.message}`; }
};
$('btn-pause').onclick = () => send({ type: 'control', action: state.phase === 'paused' ? 'resume' : 'pause' });
$('btn-skip').onclick = () => { player.cancel(); send({ type: 'control', action: 'skip' }); };
$('btn-restore').onclick = () => send({ type: 'control', action: 'restore_slides' });
$('btn-end').onclick = () => { player.cancel(); send({ type: 'presentation_ended' }); };
const go = (n) => { state.slide = n; renderSlide(); send({ type: 'slide_changed', slide_number: n }); };
$('prev').onclick = () => { if (state.slide > 1) go(state.slide - 1); };
$('next').onclick = () => { if (!state.deck || state.slide < state.deck.page_count) go(state.slide + 1); };
addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'ArrowRight') $('next').click();
  if (e.key === 'ArrowLeft') $('prev').click();
  if (e.key === 'p') $('btn-pause').click();
  if (e.key === 's') $('btn-skip').click();
});
addEventListener('beforeunload', () => state.mic?.stop());

// ---- boot -------------------------------------------------------------------------------
if (isMock() || !sessionId) {
  $('conn').textContent = 'mocked session (no backend)';
  $('btn-start').classList.add('hidden');
  state.link = await playMock('demo_session', onEvent);
  state.personas = state.link.config.personas; state.preset = state.link.preset;
  $('preset-name').textContent = state.preset?.name ?? 'Room';
  renderTiles(); renderSlide();
} else {
  const s = await getSession(sessionId);
  state.personas = s.config.personas; state.preset = s.preset; state.deck = s.deck; state.inputMode = s.config.input_mode;
  state.slide = s.slide_number || 1;
  // Reconnect/reload mid-session: the server replays events and the clock carries on.
  if (s.phase !== 'setup' && s.elapsed_ms > 0) { state.startedAt = Date.now() - s.elapsed_ms; $('btn-start').classList.add('hidden'); }
  $('preset-name').textContent = s.preset.name;
  renderTiles(); renderSlide();
  state.link = connect(sessionId, onEvent, (st) => { $('conn').textContent = st; });
}
