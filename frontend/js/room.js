// /room: the rehearsal as a video call — the panel's faces and your own webcam, live captions,
// call controls. Owner: Person A. Works against the mock (/room.html?mock=1) and a live
// session (/room.html?session=ID). You present from another device; this screen is the room.

import { connect, getSession, isMock } from '/js/api.js';
import { createPlayer } from '/js/audio.js?v=lean1';
import { startMic } from '/js/mic.js?v=lean1';
import { playMock } from '/js/mock_player.js';

const qs = new URLSearchParams(location.search);
const sessionId = qs.get('session');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = {
  phase: 'setup', startedAt: null, pausedAt: null, slide: 1, personas: [], preset: null,
  timerOverrideUntil: null, link: null, inputMode: 'live', mic: null, voices: true,
  lineTag: {}, faces: {}, cam: null, joinedAtMs: null,
};

// ---- participant tiles ----------------------------------------------------------------
const PALETTE = ['#e37400', '#7b1fa2', '#0b8043'];
const initials = (name) => (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

function renderTiles() {
  $('tiles').innerHTML = state.personas.map((p, i) => `
    <div class="tile-call seat" data-persona="${p.id}">
      ${state.faces[p.id] ? `<img src="${esc(state.faces[p.id])}" alt="${esc(p.name)}" />`
        : `<div class="avatar-fallback"><span style="background:${PALETTE[i % PALETTE.length]}">${esc(initials(p.name))}</span></div>`}
      <span class="hand">✋</span>
      <div class="waves"><i></i><i></i><i></i></div>
      <div class="name-tag">${esc(p.name)} <span class="role">· ${esc(p.role)}</span></div>
    </div>`).join('');
}
const seat = (id) => $('tiles').querySelector(`[data-persona="${id}"]`);
const nameOf = (id) => state.personas.find((x) => x.id === id)?.name ?? (id === 'presenter' ? 'You' : 'Host');

// ---- live caption: whoever is talking right now, you included ---------------------------
let captionTimer;
function say(who, text, tag, holdMs = 0) {
  $('lc-who').textContent = `${who}${tag ? ` (${tag.replace('_', ' ')})` : ''}:`;
  $('lc-text').textContent = text;
  $('live-caption').classList.add('show');
  clearTimeout(captionTimer);
  if (holdMs) captionTimer = setTimeout(() => $('live-caption').classList.remove('show'), holdMs);
}

// ---- the panel's voices: one at a time; the face lights up while it talks ---------------
const player = createPlayer({
  onClipStart: (clip) => {
    seat(clip.speaker)?.classList.remove('thinking');
    seat(clip.speaker)?.classList.add('speaking');
    say(nameOf(clip.speaker), clip.text, state.lineTag[clip.text]);
  },
  onClipEnd: (clip) => {
    seat(clip.speaker)?.classList.remove('speaking');
    captionTimer = setTimeout(() => $('live-caption').classList.remove('show'), 1500);
  },
});
$('voice-on').onchange = (e) => { state.voices = e.target.checked; player.setEnabled(state.voices); };

// ---- transcript drawer ------------------------------------------------------------------
function caption(speaker, text, tag) {
  const mine = speaker === 'presenter';
  const el = document.createElement('div');
  el.className = `caption rounded-lg p-2 ${mine ? 'bg-slate-900/40 text-slate-300' : 'bg-slate-900'}`;
  el.innerHTML = `<span class="text-xs ${mine ? 'text-slate-600' : 'text-cyan-500'}">${esc(nameOf(speaker))}${tag ? ` · <span class="text-amber-300">${esc(tag.replace('_', ' '))}</span>` : ''}</span><div>${esc(text)}</div>`;
  $('captions').append(el);
  $('captions').scrollTop = $('captions').scrollHeight;
}

// ---- phase and timer ----------------------------------------------------------------------
function setPhase(p) {
  state.phase = p;
  $('phase').textContent = p;
  $('btn-pause').textContent = p === 'paused' ? 'Resume' : 'Pause';
  $('btn-end').textContent = p === 'qna' ? 'Finish → Report' : 'End → Q&A';
  if (p === 'report') {
    const go = () => { location.href = `/report.html?session=${sessionId ?? ''}${isMock() ? '&mock=1' : ''}`; };
    const wait = () => (player.busy ? setTimeout(wait, 400) : setTimeout(go, 1200));
    wait(); // let the last line finish
  }
}
setInterval(() => {
  if (!state.startedAt) return;
  const urgent = Boolean(state.timerOverrideUntil);
  const ms = urgent ? Math.max(0, state.timerOverrideUntil - Date.now())
    : (state.pausedAt ?? Date.now()) - state.startedAt;
  $('timer').classList.toggle('urgent', urgent);
  const s = Math.floor(ms / 1000);
  $('timer').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}, 250);

// ---- events ---------------------------------------------------------------------------
function onEvent(ev) {
  const p = ev.payload ?? {};
  // After a reload the server replays history: show it, but don't re-speak old lines.
  const old = state.joinedAtMs != null && ev.timestamp_ms < state.joinedAtMs - 3000;
  switch (ev.type) {
    case 'session_started':
      if (state.startedAt == null) state.startedAt = Date.now() - (isMock() ? ev.timestamp_ms : 0);
      if (p.config?.personas) state.personas = p.config.personas;
      if (p.preset) $('preset-name').textContent = p.preset.name;
      renderTiles(); $('btn-start').classList.add('hidden'); break;
    case 'phase_changed':
      if (p.to === 'paused') { state.pausedAt = Date.now(); player.cancel(); }
      if (p.from === 'paused') {
        const d = Date.now() - (state.pausedAt ?? Date.now());
        state.startedAt += d; if (state.timerOverrideUntil) state.timerOverrideUntil += d; state.pausedAt = null;
      }
      setPhase(p.to); break;
    case 'transcript_segment': caption('presenter', p.text); break;
    case 'question_queued': if (p.follow_up_of) state.lineTag[p.question] = 'follow-up'; break;
    case 'ai_speech_started':
      caption(p.speaker, p.line, state.lineTag[p.line]);
      if (old) break;
      if (!state.voices || isMock()) { // no audio: show the line for a reading time instead
        say(nameOf(p.speaker), p.line, state.lineTag[p.line], Math.min(9000, 1800 + p.line.split(/\s+/).length * 330));
      } else {
        seat(p.speaker)?.classList.add('thinking'); // about to speak: the voice is rendering
      }
      break;
    case 'audio_status':
      if (p.status === 'ready') {
        $('conn').textContent = 'live · Higgs voices';
        if (p.faces) { state.faces = p.faces; renderTiles(); }
      } else if (p.status === 'clip' && state.voices && !old) {
        player.playClip({ url: p.url, speaker: p.speaker, text: p.text });
      } else if (p.status === 'tts_failed') {
        seat(p.speaker)?.classList.remove('thinking');
      }
      break;
    case 'curveball_triggered':
      if (p.line) state.lineTag[p.line] = p.kind;
      if (p.ui_effect === 'tiles_blank') $('tiles').querySelectorAll('.seat').forEach((t) => t.classList.add('blank'));
      if (p.persona_id) seat(p.persona_id)?.classList.add('flash');
      if (p.sfx_url && !old) player.playSfx(p.sfx_url);
      break;
    case 'curveball_resolved':
      $('tiles').querySelectorAll('.seat').forEach((t) => t.classList.remove('blank', 'flash'));
      break;
    case 'timer_override':
      state.timerOverrideUntil = p.remaining_ms > 0 ? Date.now() + p.remaining_ms : null; break;
    case 'error': console.warn('[room] error event', p); break;
    case 'session_ended': setPhase('report'); break;
  }
}

// ---- controls -------------------------------------------------------------------------
const send = (msg) => state.link?.send(msg);
$('btn-start').onclick = async () => {
  camOn();
  send({ type: 'presentation_started' });
  try {
    const ptt = state.inputMode === 'push_to_talk';
    $('ptt-hint').classList.toggle('hidden', !ptt);
    state.mic = await startMic({
      pushToTalk: ptt,
      onLevel: (v) => { $('mic-level').style.width = `${Math.round(v * 100)}%`; },
      onInterim: (text) => { if (!player.busy) say('You', text, null, 2500); },
      onSegment: (segment) => send({ type: 'transcript_segment', segment }),
    });
    $('mic-label').textContent = state.mic.hasSTT ? 'mic · listening' : 'mic (no speech recognition in this browser — use Chrome)';
  } catch (e) { $('mic-label').textContent = `mic blocked: ${e.message}`; }
};

// your webcam: only ever shown to you, never sent anywhere
async function camOn() {
  try {
    state.cam = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    $('selfcam').srcObject = state.cam;
    document.querySelector('.tile-call.you').classList.add('cam-on');
    $('btn-cam').classList.remove('off');
  } catch (e) { $('selfcam-off').textContent = `Camera blocked: ${e.message}`; }
}
function camOff() {
  state.cam?.getTracks().forEach((t) => t.stop()); state.cam = null;
  $('selfcam').srcObject = null;
  document.querySelector('.tile-call.you').classList.remove('cam-on');
  $('btn-cam').classList.add('off');
}
$('btn-cam').onclick = () => (state.cam ? camOff() : camOn());
$('btn-drawer').onclick = () => $('drawer').classList.toggle('hidden');
$('btn-pause').onclick = () => send({ type: 'control', action: state.phase === 'paused' ? 'resume' : 'pause' });
$('btn-skip').onclick = () => { player.cancel(); send({ type: 'control', action: 'skip' }); };
$('btn-end').onclick = () => { player.cancel(); send({ type: 'presentation_ended' }); };
addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'p') $('btn-pause').click();
  if (e.key === 's') $('btn-skip').click();
});
addEventListener('beforeunload', () => { state.mic?.stop(); camOff(); });

// ---- boot -------------------------------------------------------------------------------
if (isMock() || !sessionId) {
  $('conn').textContent = 'mocked session (no backend)';
  $('btn-start').classList.add('hidden');
  state.link = await playMock('demo_session', onEvent);
  state.personas = state.link.config.personas;
  $('preset-name').textContent = state.link.preset?.name ?? 'Room';
  renderTiles();
} else {
  const s = await getSession(sessionId);
  state.personas = s.config.personas; state.inputMode = s.config.input_mode;
  state.faces = s.faces ?? {};
  if (s.phase !== 'setup' && s.elapsed_ms > 0) { // reload mid-call: the clock carries on
    state.startedAt = Date.now() - s.elapsed_ms; state.joinedAtMs = s.elapsed_ms;
    $('btn-start').classList.add('hidden');
  }
  $('preset-name').textContent = s.preset.name;
  renderTiles();
  state.link = connect(sessionId, onEvent, (st) => { $('conn').textContent = st; });
}
