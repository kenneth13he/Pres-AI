// /room: slide viewer, persona tiles, captions, timer, controls, curveball effects.
// Owner: Person A (P0-7, P0-10). Events: spec/contracts.schema.json (SessionEvent).
// Works against the mock (/room.html?mock=1) and against a live session (/room.html?session=ID).

import { connect, getSession, isMock } from '/js/api.js';
import { createPlayer } from '/js/audio.js';
import { startMic } from '/js/mic.js';
import { playMock } from '/js/mock_player.js';

const qs = new URLSearchParams(location.search);
const sessionId = qs.get('session');
const $ = (id) => document.getElementById(id);

const state = {
  phase: 'setup', startedAt: null, pausedAt: null, slide: 1, deck: null, personas: [], preset: null,
  timerOverrideUntil: null, activeCurveball: null, link: null, inputMode: 'live', mic: null,
};
const player = createPlayer();

// ---- render --------------------------------------------------------------------------
const LABEL = { vc: 'VC', student: 'Student', professor: 'Prof', moderator: 'Mod' };
const initial = (p) => (p.name || '?').trim()[0].toUpperCase();

function renderTiles() {
  $('tiles').innerHTML = state.personas.map((p) => `
    <div class="tile rounded-xl border border-slate-800 bg-slate-900/60 p-3" data-persona="${p.id}">
      <div class="flex items-center gap-3">
        <div class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-slate-800 text-lg font-medium">${initial(p)}</div>
        <div class="min-w-0">
          <div class="truncate font-medium">${esc(p.name)} <span class="text-xs text-slate-500">· ${esc(p.role)}</span></div>
          <div class="truncate text-xs text-slate-500">${p.custom ? 'Custom · fictional' : 'fictional'} · ${esc((p.focus || []).slice(0, 2).join(', '))}</div>
        </div>
        <div class="ml-auto hidden shrink-0 text-xs text-cyan-400" data-thinking>thinking…</div>
      </div>
      <div class="mt-2 hidden w-fit rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-300" data-tag></div>
    </div>`).join('') + `
    <div class="tile rounded-xl border border-dashed border-slate-800 p-3 text-sm text-slate-500" data-persona="moderator">
      <span class="font-medium text-slate-400">Moderator</span> <span class="text-xs">· runs the room</span>
    </div>`;
}
const tile = (id) => $('tiles').querySelector(`[data-persona="${id}"]`);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

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
  if (p === 'report') setTimeout(() => { location.href = `/report.html?session=${sessionId ?? ''}${isMock() ? '&mock=1' : ''}`; }, 1200);
}

function tickTimer() {
  if (!state.startedAt) return;
  let ms;
  if (state.timerOverrideUntil) {
    ms = Math.max(0, state.timerOverrideUntil - Date.now());
    $('timer').classList.add('urgent');
  } else {
    ms = (state.pausedAt ?? Date.now()) - state.startedAt;
    $('timer').classList.remove('urgent');
  }
  const s = Math.floor(ms / 1000);
  $('timer').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
setInterval(tickTimer, 250);

// ---- events: one case per SessionEvent type -------------------------------------------
function onEvent(ev) {
  const p = ev.payload ?? {};
  switch (ev.type) {
    case 'session_started':
      state.startedAt = Date.now() - (isMock() ? ev.timestamp_ms : 0);
      if (p.config?.personas) state.personas = p.config.personas;
      if (p.preset) { state.preset = p.preset; $('preset-name').textContent = p.preset.name; }
      renderTiles(); $('btn-start').classList.add('hidden'); break;
    case 'phase_changed':
      if (p.to === 'paused') state.pausedAt = Date.now();
      if (p.from === 'paused') { state.startedAt += Date.now() - (state.pausedAt ?? Date.now()); if (state.timerOverrideUntil) state.timerOverrideUntil += Date.now() - (state.pausedAt ?? Date.now()); state.pausedAt = null; }
      setPhase(p.to); break;
    case 'slide_changed': state.slide = p.slide_number; renderSlide(); break;
    case 'transcript_segment': if (p.speaker === 'presenter') caption('presenter', p.text); break;
    case 'question_queued':
      if (p.curveball_id) break; // the curveball_triggered event already captioned this line
      tile(p.persona_id)?.querySelector('[data-thinking]')?.classList.add('hidden');
      caption(p.persona_id, p.question, p.follow_up_of ? 'follow-up' : null); break;
    case 'ai_speech_started':
      tile(p.speaker)?.classList.add('speaking');
      if (!state.personas.find((x) => x.id === p.speaker) && !state.activeCurveball) caption('moderator', p.line);
      break;
    case 'ai_speech_ended': tile(p.speaker)?.classList.remove('speaking'); break;
    case 'curveball_triggered': onCurveball(p); break;
    case 'curveball_resolved': clearCurveball(p); break;
    case 'timer_override':
      state.timerOverrideUntil = p.remaining_ms > 0 ? Date.now() + p.remaining_ms : null;
      if (p.remaining_ms === 0) caption('moderator', 'Time. Let’s go to questions.'); break;
    case 'paused': $('slide-viewer').classList.add('opacity-50'); break;
    case 'resumed': $('slide-viewer').classList.remove('opacity-50'); break;
    case 'skipped': caption('moderator', p.reason ? 'Out of time for that one — no penalty.' : 'Skipped — carry on.'); break;
    case 'audio_status': $('conn').textContent = `audio: ${p.status}`; if (p.url) player.playUrl(p.url); break;
    case 'avatar_status': break;
    case 'error': console.warn('[room] error event', p); break;
    case 'session_ended': setPhase('report'); break;
  }
}

function onCurveball(p) {
  state.activeCurveball = p;
  const viewer = $('slide-viewer');
  switch (p.ui_effect) {
    case 'slides_black': viewer.classList.add('black'); $('overlay-title').textContent = 'Projector disconnected'; $('overlay-sub').textContent = 'Keep going.'; $('btn-restore').classList.remove('hidden'); break;
    case 'slides_dim': viewer.classList.add('dim'); $('overlay-title').textContent = 'Elevator'; $('overlay-sub').textContent = '30 seconds. No slides.'; break;
    case 'tiles_blank': $('tiles').querySelectorAll('.tile').forEach((t) => t.classList.add('blank')); break;
    case 'tile_add': state.personas.push({ id: 'vip', name: 'VIP', role: 'Decision-maker', focus: ['the ask', 'why now'] }); renderTiles(); tile('vip')?.classList.add('flash'); break;
  }
  if (p.persona_id) {
    const t = tile(p.persona_id); t?.classList.add('flash');
    const tag = t?.querySelector('[data-tag]'); if (tag) { tag.textContent = p.kind.replace('_', ' '); tag.classList.remove('hidden'); }
    caption(p.persona_id, p.line, p.kind);
  } else if (p.line) caption('moderator', p.line, p.kind);
  if (p.sfx_url) player.playSfx(p.sfx_url);
}

function clearCurveball(p) {
  $('slide-viewer').classList.remove('black', 'dim'); $('btn-restore').classList.add('hidden');
  $('tiles').querySelectorAll('.tile').forEach((t) => { t.classList.remove('blank', 'flash'); t.querySelector('[data-tag]')?.classList.add('hidden'); });
  state.activeCurveball = null;
  const r = p.recovery;
  if (r && r.resume_after_ms != null) caption('moderator', `Back on track after ${(r.resume_after_ms / 1000).toFixed(1)} s${r.score != null ? ` · recovery ${r.score}/100` : ''}.`);
}

// ---- controls --------------------------------------------------------------------------
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
    $('mic-label').textContent = state.mic.hasSTT ? 'mic · browser STT' : 'mic (no STT in this browser)';
  } catch (e) { $('mic-label').textContent = `mic blocked: ${e.message}`; }
};
$('btn-pause').onclick = () => send({ type: 'control', action: state.phase === 'paused' ? 'resume' : 'pause' });
$('btn-skip').onclick = () => { player.cancel(); send({ type: 'control', action: 'skip' }); };
$('btn-restore').onclick = () => send({ type: 'control', action: 'restore_slides' });
$('btn-end').onclick = () => send({ type: 'presentation_ended' });
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
  $('preset-name').textContent = s.preset.name;
  renderTiles(); renderSlide();
  state.link = connect(sessionId, onEvent, (st) => { $('conn').textContent = st; });
}
