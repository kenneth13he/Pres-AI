// /room: slide viewer, persona tiles, captions, timer, controls, curveball effects.
// Owner: Person A (P0-7, P0-10). Events: spec/contracts.schema.json (SessionEvent).
// Build every state against the mock first: /room.html?mock=1 replays frontend/mocks/demo_session.json.

import { connect, getSession, isMock } from '/js/api.js';
import { createPlayer } from '/js/audio.js';
import { startMic } from '/js/mic.js';
import { playMock } from '/js/mock_player.js';

const qs = new URLSearchParams(location.search);
const sessionId = qs.get('session');
const $ = (id) => document.getElementById(id);

const state = {
  phase: 'setup', startedAt: null, slide: 1, deck: null, personas: [], preset: null,
  timerOverrideUntil: null, activeCurveball: null, speaking: null, link: null, inputMode: 'live',
};
const player = createPlayer();

// ---- render (TODO A) ------------------------------------------------------------------
function renderTiles() {
  // TODO(A): one .tile per persona (name, role, "fictional" / "Custom · fictional", focus),
  //          plus a Moderator tile. States: .speaking, .flash + tag text, .blank, "thinking…".
  $('tiles').innerHTML = state.personas.map((p) =>
    `<div class="tile rounded-xl border border-slate-800 p-3" data-persona="${p.id}">${p.name} · ${p.role}</div>`).join('');
}
function caption(speaker, text, tag) {
  // TODO(A): styled caption row with speaker name and optional curveball tag; autoscroll.
  const el = document.createElement('div');
  el.className = 'caption';
  el.textContent = `${speaker}: ${text}${tag ? ` [${tag}]` : ''}`;
  $('captions').append(el);
  $('captions').scrollTop = $('captions').scrollHeight;
}
function renderSlide() {
  // TODO(A): show deck.slides[slide-1].image_url, or the slide text / "listening" placeholder.
  $('slide-no').textContent = `Slide ${state.slide}${state.deck ? ` / ${state.deck.page_count}` : ''}`;
}
function setPhase(p) {
  state.phase = p;
  $('phase').textContent = p;
  // TODO(A): Pause ↔ Resume label; on "report" navigate to /report.html?session=…
}
// TODO(A): timer loop — elapsed mm:ss; during timer_override count DOWN in red (.urgent).

// ---- events: one case per SessionEvent type -------------------------------------------
function onEvent(ev) {
  const p = ev.payload ?? {};
  switch (ev.type) {
    case 'session_started':   /* TODO(A): personas/preset from p.config, start timer, hide Start */ break;
    case 'phase_changed':     setPhase(p.to); break;
    case 'slide_changed':     state.slide = p.slide_number; renderSlide(); break;
    case 'transcript_segment':/* TODO(A): presenter caption */ break;
    case 'question_queued':   caption(p.persona_id, p.question, p.follow_up_of ? 'follow-up' : null); break;
    case 'ai_speech_started': /* TODO(A): tile .speaking; moderator line → caption */ break;
    case 'ai_speech_ended':   /* TODO(A): clear .speaking */ break;
    case 'curveball_triggered': onCurveball(p); break;
    case 'curveball_resolved':  clearCurveball(p); break;
    case 'timer_override':    /* TODO(A): remaining_ms > 0 → red countdown; 0 → expired */ break;
    case 'paused':            /* TODO(A): dim the room */ break;
    case 'resumed':           break;
    case 'skipped':           caption('moderator', 'Skipped — carry on.'); break;
    case 'audio_status':      $('conn').textContent = `audio: ${p.status}`; break;
    case 'avatar_status':     break; // P2
    case 'error':             caption('moderator', `(something failed quietly: ${p.message})`); break;
    case 'session_ended':     setPhase('report'); break;
  }
}

function onCurveball(p) {
  state.activeCurveball = p;
  // TODO(A) per p.ui_effect (CLAUDE.md §11 Person A):
  //   slides_black → #slide-viewer.black + overlay "Projector disconnected", show #btn-restore
  //   timer_red    → handled by timer_override
  //   tile_flash   → tile(p.persona_id).flash + tag p.kind
  //   sfx          → player.playSfx(p.sfx_url) + phone/door icon
  //   tile_add     → slide in a VIP tile
  //   slides_dim   → dim + 30 s ring (elevator)
  //   tiles_blank  → all tiles .blank (dead_room)
  caption(p.persona_id ?? 'moderator', p.line || p.kind, p.kind);
}

function clearCurveball(p) {
  state.activeCurveball = null;
  // TODO(A): remove black/dim/blank/flash, hide #btn-restore; if p.recovery?.resume_after_ms
  //          != null → caption "Back on track after X s."
}

// ---- controls (wired; keep) -----------------------------------------------------------
const send = (msg) => state.link?.send(msg);
$('btn-start').onclick = async () => {
  await player.resume();
  send({ type: 'presentation_started' });
  send({ type: 'slide_changed', slide_number: state.slide });
  try {
    const mic = await startMic({
      pushToTalk: state.inputMode === 'push_to_talk',
      onLevel: (v) => { $('mic-level').style.width = `${Math.round(v * 100)}%`; },
      onSegment: (segment) => send({ type: 'transcript_segment', segment }),
    });
    $('mic-label').textContent = mic.hasSTT ? 'mic + STT' : 'mic';
  } catch (e) { $('mic-label').textContent = `mic blocked: ${e.message}`; }
};
$('btn-pause').onclick = () => send({ type: 'control', action: state.phase === 'paused' ? 'resume' : 'pause' });
$('btn-skip').onclick = () => { player.cancel(); send({ type: 'control', action: 'skip' }); };
$('btn-restore').onclick = () => send({ type: 'control', action: 'restore_slides' });
$('btn-end').onclick = () => send({ type: 'presentation_ended' });
$('prev').onclick = () => { if (state.slide > 1) { state.slide--; renderSlide(); send({ type: 'slide_changed', slide_number: state.slide }); } };
$('next').onclick = () => { if (!state.deck || state.slide < state.deck.page_count) { state.slide++; renderSlide(); send({ type: 'slide_changed', slide_number: state.slide }); } };
// TODO(A, P1-1): keyboard shortcuts — ←/→ slides, P pause, S skip, Space push-to-talk.

// ---- boot -------------------------------------------------------------------------------
if (isMock() || !sessionId) {
  $('conn').textContent = 'mocked session (no backend)';
  $('btn-start').classList.add('hidden');
  state.link = await playMock('demo_session', onEvent);
  state.personas = state.link.config.personas; state.preset = state.link.preset;
  renderTiles(); renderSlide();
} else {
  const s = await getSession(sessionId);
  state.personas = s.config.personas; state.preset = s.preset; state.deck = s.deck; state.inputMode = s.config.input_mode;
  $('preset-name').textContent = s.preset.name;
  renderTiles(); renderSlide();
  state.link = connect(sessionId, onEvent, (st) => { $('conn').textContent = st; });
}
