// /room: stage (room layout, slide viewer, guest tiles), captions, timer, controls, curveball effects.
// Owner: Person A (P0-7, P0-10). Events: spec/contracts.schema.json (SessionEvent).
// Design: docs/design/Pres AI App.dc.html (live step). Everything here is driven by SessionEvents;
// /room.html?mock=1 replays frontend/mocks/demo_session.json.
// Live call (feat/voice-room): each panelist's Higgs face streams into their tile over LiveKit once
// it has joined (a still until then), lines without a live face play as clips, the mic is cut into
// utterances that Higgs STT transcribes on the server, and your webcam sits in the "You" seat.

import { connect, getSession, isMock } from '/js/api.js';
import { createPlayer } from '/js/audio.js';
import { startMic } from '/js/mic.js';
import { playMock } from '/js/mock_player.js';
import {
  CORAL, MINT, PRESET_SETTING, YOU_AT, cq, esc, fmtS, kindName, layout, loadSessionMeta, rect,
  saveSessionMeta, settingById, tileBg,
} from '/js/rooms.js';

const qs = new URLSearchParams(location.search);
const sessionId = qs.get('session');
const MOCK = isMock() || !sessionId;
const $ = (id) => document.getElementById(id);

// Placeholder slide titles for the mocked session only (the mock has no deck).
const MOCK_SLIDES = ['Campus onboarding, solved.', 'The problem: onboarding takes weeks.', 'Growth plan: 100,000 customers in six months.', 'Two campus pilots.', 'How it works', 'Who pays', 'Competition', 'Go-to-market', 'Team', 'Roadmap', 'The ask', 'Thank you'];
const BUDGET = { friendly: 0, normal: 1, brutal: 2 };
const VIP = { id: '__vip', name: 'The Sponsor', role: 'Executive Sponsor', custom: false };

const state = {
  phase: 'setup', started: false, done: false, paused: false, elapsedS: 0,
  crunchEnd: null, crunchExpired: false, slide: 1, deck: null, personas: [], images: {},
  setting: 'video', config: null, speaking: null, flash: null, flashTag: null, blank: false,
  vip: false, black: false, dim: false, cbActive: null, cbFired: 0, lastLine: {}, link: null,
  reportUrl: null, lastError: null,
  joined: false, faces: {}, liveVoice: false, thinking: null, joinedAtMs: null,
  live: {}, liveEls: {}, seatRoom: {}, mic: null, cam: null,
};
// The panel's voices, one clip at a time; the tile lights up while its clip plays.
const player = createPlayer({
  onClipStart: (clip) => speak(clip.speaker),
  onClipEnd: (clip) => quiet(clip.speaker),
});
function speak(id) { state.speaking = id; if (state.thinking === id) state.thinking = null; renderEffects(); }
function quiet(id) { if (state.speaking === id) { state.speaking = null; renderEffects(); } }

// ---- names ----------------------------------------------------------------------------------
const nameOf = (id) => (id === 'moderator' ? 'Moderator' : id === 'presenter' ? 'You' : id === VIP.id ? VIP.name : state.personas.find((p) => p.id === id)?.name ?? id);
const colorOf = (who) => (who === 'You' ? '#eceeed' : who === 'Moderator' ? CORAL : who === 'System' ? 'var(--faint)' : MINT);
const tiles = () => state.personas.concat(state.vip ? [VIP] : []);

// ---- render ---------------------------------------------------------------------------------
function buildStage() {
  const T = tiles(), L = layout(state.setting, T.length);
  const st = $('stage');
  st.style.background = L.bg;
  st.innerHTML = `
    ${L.decor.map((d) => `<div style="${rect(d)};border-radius:${d.r};background:${d.c}"></div>`).join('')}
    <div id="slide" class="slide" style="${rect(L.slide)}"></div>
    <div class="black" style="${rect(L.slide)}"><div><div style="font-size:${cq(L.slide.w, 0.05, 13)};font-weight:700">Projector disconnected</div><div style="margin-top:4%;color:#8a9190;font-size:${cq(L.slide.w, 0.022, 10)}">Keep going.</div></div></div>
    ${L.seats.map((t, i) => {
      const p = T[i]; if (!p) return '';
      const img = state.images[p.id] ?? state.faces[p.id];
      // A face is shown whole (contain) whatever the tile's shape; a blurred copy fills the sides.
      const face = img ? `<div class="tile-fill" style="background-image:url('${esc(img)}')"></div><div class="tile-img" style="background-image:url('${esc(img)}')"></div>` : '';
      return `<div class="tile ${img ? 'photo' : ''} ${p.id === VIP.id ? 'vip-in' : ''}" data-id="${esc(p.id)}" style="${rect(t)};border-radius:0.8cqw;background:${img ? '#0e1012' : tileBg(null, i + 1)}">
        ${face}
        <span class="tile-tag hidden" style="font-size:${cq(t.w, 0.055, 8)}"></span>
        <div style="position:absolute;left:5%;right:5%;bottom:6%;display:flex;justify-content:space-between;align-items:flex-end;gap:6px">
          <div style="min-width:0;text-shadow:0 1px 4px rgba(0,0,0,.6)"><div style="font-size:${cq(t.w, 0.075, 9)};font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(p.name)}</div><div style="font-size:${cq(t.w, 0.055, 8)};color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(p.role)}${p.custom && p.role !== 'Custom guest' ? ' · Custom' : ''}</div></div>
          <div class="bars" style="height:1.2cqw">${'<span style="height:20%"></span>'.repeat(4)}</div>
        </div></div>`;
    }).join('')}
    <div class="tile you ${state.cam ? 'cam-on' : ''}" style="${rect(YOU_AT[state.setting] ?? YOU_AT.video)};border-radius:0.8cqw;background:#181b1e">
      <video id="selfcam" autoplay playsinline muted></video>
      <div class="cam-off" style="font-size:${cq(14, 0.07, 8)}">You</div>
    </div>
    <div id="cb-pill"></div>
    <div id="veil" class="veil hidden"></div>`;
  $('guest-count').textContent = `${T.length} ${T.length === 1 ? 'guest' : 'guests'}`;
  if (state.cam) $('selfcam').srcObject = state.cam;
  Object.entries(state.liveEls).forEach(([id, el]) => attachFeed(id, el));
  renderSlide(); renderEffects(); renderVeil();
}

function renderSlide() {
  const el = $('slide'); if (!el) return;
  const s = state.deck?.slides?.[state.slide - 1];
  const w = parseFloat(el.style.width);
  if (!state.deck) el.innerHTML = `<div style="position:absolute;inset:0;display:grid;place-items:center;text-align:center;color:var(--faint);font-size:${cq(w, 0.022, 10)}">Listening · no slides</div>`;
  else if (s?.image_url) el.innerHTML = `<img src="${esc(s.image_url)}" alt="Slide ${state.slide}">`;
  else {
    const title = (s?.text || '').trim().split('\n')[0] || `Slide ${state.slide}`;
    el.innerHTML = `<div style="position:absolute;inset:0;padding:8%;display:flex;flex-direction:column;justify-content:center">
      <div style="font:500 ${cq(w, 0.022, 10)} var(--mono);color:var(--faint);letter-spacing:.08em">SLIDE ${state.slide}</div>
      <div style="margin-top:4%;font-size:${cq(w, 0.07, 14)};font-weight:800;letter-spacing:-0.03em;line-height:1.05;text-wrap:balance">${esc(title)}</div></div>`;
  }
  $('slide-no').textContent = state.deck ? `Slide ${state.slide} / ${state.deck.page_count}` : `Slide ${state.slide}`;
}

function renderEffects() {
  const st = $('stage');
  st.classList.toggle('black', state.black);
  st.classList.toggle('dim', state.dim);
  $('btn-restore').classList.toggle('hidden', !(state.black || state.dim));
  st.querySelectorAll('.tile[data-id]').forEach((t) => {
    const id = t.dataset.id, tag = t.querySelector('.tile-tag');
    t.classList.toggle('speaking', state.speaking === id);
    t.classList.toggle('thinking', state.thinking === id && state.speaking !== id);
    t.classList.toggle('flash', state.flash === id);
    t.classList.toggle('blank', state.blank);
    const label = state.flash === id ? state.flashTag : id === VIP.id ? 'VIP' : null;
    tag.classList.toggle('hidden', !label); tag.textContent = label ?? '';
  });
  const pill = $('cb-pill');
  pill.classList.toggle('show', !!state.cbActive);
  if (state.cbActive) pill.textContent = `CURVEBALL · ${kindName(state.cbActive.kind).toUpperCase()}`;
  const budget = state.config?.curveballs?.mode === 'off' ? 0 : BUDGET[state.config?.difficulty] ?? 1;
  $('cb-left').textContent = `${state.cbFired} / ${Math.max(budget, state.cbFired)} curveballs`;
}

function renderVeil() {
  const v = $('veil'); if (!v) return;
  if (!state.joined && !MOCK && !state.done) {
    v.classList.remove('hidden');
    v.innerHTML = `<div style="text-align:center;max-width:420px;padding:0 20px">
      <div style="font-size:max(18px,2.4cqw);font-weight:800;letter-spacing:-0.02em">${state.started ? 'Rejoin the room.' : 'Ready when you are.'}</div>
      <p style="margin:10px 0 18px;font-size:14px;line-height:1.5;color:var(--muted)">We'll ask for your microphone so the room can hear you, and your camera so you can see yourself (it never leaves this screen). Nothing is recorded or stored; the transcript lives in this session only. Use headphones: the mic stays on.</p>
      <button id="btn-start" class="btn-mint">${state.started ? 'Rejoin' : 'Start presenting'}</button></div>`;
    $('btn-start').onclick = begin;
  } else if (state.paused) {
    v.classList.remove('hidden');
    v.innerHTML = '<div style="font-size:max(18px,2.6cqw);font-weight:800">Paused</div>';
  } else v.classList.add('hidden');
}

function setPhase(p) {
  state.phase = p;
  const el = $('phase');
  el.textContent = p;
  el.className = `phase-pill ${p === 'curveball' || p === 'recovering' ? 'hot' : ['interruption', 'answering', 'qna', 'report'].includes(p) ? 'mint' : ''}`;
  if (p === 'qna') { state.crunchEnd = null; state.crunchExpired = false; }
  renderControls();
}

function renderControls() {
  $('btn-pause').textContent = state.paused ? 'Resume' : 'Pause';
  const end = $('btn-end');
  end.textContent = state.done ? 'View report →' : state.phase === 'qna' ? 'End Q&A' : 'End → Q&A';
  end.classList.toggle('done', state.done);
}

function caption(who, text, tag = null, tagColor = null) {
  if (!text) return;
  const el = document.createElement('div');
  el.className = 'caption';
  el.style.cssText = 'display:flex;flex-direction:column;gap:3px';
  el.innerHTML = `<div style="display:flex;align-items:center;gap:8px"><span class="cap-who" style="color:${colorOf(who)}">${esc(who)}</span>${tag ? `<span class="cap-tag" style="color:${tagColor ?? CORAL}">${esc(tag)}</span>` : ''}</div>
    <div style="font-size:15px;line-height:1.45;color:#d6dad9">${esc(text)}</div>`;
  $('captions').append(el);
  $('captions').scrollTop = $('captions').scrollHeight;
}

// Clock: elapsed counts up while live; a time_crunch override counts down in coral.
setInterval(() => {
  if (state.started && !state.paused && !state.done) state.elapsedS++;
  const t = $('timer');
  if (state.crunchEnd != null || state.crunchExpired) {
    const left = state.crunchExpired ? 0 : Math.max(0, Math.ceil((state.crunchEnd - Date.now()) / 1000));
    t.textContent = fmtS(left); t.style.color = CORAL;
  } else { t.textContent = fmtS(state.elapsedS); t.style.color = ''; }
}, 1000);
// Speaking bars on the active tile.
setInterval(() => {
  document.querySelectorAll('#stage .tile').forEach((t) => {
    const on = t.dataset.id === state.speaking && !state.paused;
    t.querySelectorAll('.bars > span').forEach((b) => { b.style.height = on ? `${30 + Math.random() * 70}%` : '20%'; });
  });
}, 150);

// ---- events: one case per SessionEvent type -------------------------------------------------
function onEvent(ev) {
  const p = ev.payload ?? {};
  // After a reload the server replays history: show it, but don't re-speak old lines.
  const old = state.joinedAtMs != null && ev.timestamp_ms < state.joinedAtMs - 3000;
  switch (ev.type) {
    case 'session_started': state.started = true; renderVeil(); break;
    case 'phase_changed': setPhase(p.to); break;
    case 'slide_changed': state.slide = p.slide_number; renderSlide(); break;
    case 'transcript_segment': if (p.speaker !== 'ai') caption('You', p.text); break;
    case 'question_queued': {
      const tag = p.follow_up_of ? 'follow-up' : state.phase === 'qna' ? 'Q&A' : 'question';
      caption(nameOf(p.persona_id), p.question, tag, 'var(--faint)');
      state.lastLine[p.persona_id] = p.question;
      break;
    }
    case 'ai_speech_started':
      // With Higgs voices the line is still rendering: "thinking" until its audio starts.
      if (state.liveVoice && !old) state.thinking = p.speaker; else if (!state.liveVoice) state.speaking = p.speaker;
      if (p.line && p.line !== state.lastLine[p.speaker]) caption(nameOf(p.speaker), p.line);
      state.lastLine[p.speaker] = p.line;
      renderEffects(); break;
    case 'ai_speech_ended': if (!state.liveVoice) { state.speaking = null; renderEffects(); } break;
    case 'answer_received': break;
    case 'curveball_triggered': onCurveball(p, old); break;
    case 'curveball_resolved': clearCurveball(p); break;
    case 'timer_override':
      if (p.remaining_ms > 0) { state.crunchEnd = Date.now() + p.remaining_ms; state.crunchExpired = false; }
      else { state.crunchEnd = null; state.crunchExpired = true; }
      break;
    case 'paused': state.paused = true; player.cancel(); renderVeil(); renderControls(); break;
    case 'resumed': state.paused = false; renderVeil(); renderControls(); break;
    case 'skipped':
      caption('Moderator', 'Skipped — carry on.');
      state.speaking = null; clearCurveball({}); break;
    case 'audio_status': onAudio(p, old); break;
    case 'avatar_status': break; // P2
    case 'error': // the ticker can repeat one failure every second; show it once
      if (p.message !== state.lastError) caption('System', `Something failed quietly: ${p.message || 'a backend step is not implemented yet'}`, 'error', 'var(--faint)');
      state.lastError = p.message; break;
    case 'session_ended':
      state.done = true; state.speaking = null; state.reportUrl = p.report_url ?? null;
      saveSessionMeta(sessionId ?? 'mock', { ...(loadSessionMeta(sessionId ?? 'mock') ?? {}), setting: state.setting, images: state.images, config: state.config, elapsed_s: state.elapsedS });
      caption('Moderator', 'Thanks, everyone. Your report card is ready.');
      state.mic?.stop(); state.mic = null; $('mic-label').textContent = 'mic off';
      renderControls(); renderEffects(); renderVeil(); break;
  }
}

function onAudio(p, old) {
  switch (p.status) {
    case 'ready': // the Higgs adapter is on: voices are real, faces are its stills until live
      state.liveVoice = true; $('conn').textContent = 'live · Higgs voices';
      if (p.faces) { state.faces = p.faces; buildStage(); }
      break;
    case 'live_seat': joinLive(p).catch((e) => console.warn('[room] live face', e)); break;
    case 'live_line': state.liveVoice = true; if (!old) speak(p.speaker); break;
    case 'live_done': quiet(p.speaker); break;
    case 'clip': state.liveVoice = true; if (!old) player.playClip({ url: p.url, speaker: p.speaker, text: p.text }); break;
    case 'tts_failed': if (state.thinking === p.speaker) { state.thinking = null; renderEffects(); } break;
    default: if (!state.liveVoice) $('conn').textContent = `audio: ${p.status}`;
  }
}

function onCurveball(p, old = false) {
  state.cbActive = p; state.cbFired++;
  const who = p.speaker === 'persona' ? p.persona_id : 'moderator';
  switch (p.ui_effect) {
    case 'slides_black': state.black = true; break;
    case 'slides_dim': state.dim = true; break;
    case 'tile_flash': state.flash = p.persona_id; state.flashTag = kindName(p.kind); break;
    case 'tiles_blank': state.blank = true; break;
    case 'tile_add': if (!state.vip) { state.vip = true; buildStage(); } break;
    case 'sfx': if (!old) player.playSfx(p.sfx_url); break;
  }
  const line = p.line || (p.kind === 'distraction' ? '(A phone rings at the back of the room.)' : p.kind === 'dead_room' ? '(The room goes quiet. No reactions.)' : '');
  caption(nameOf(who), line, kindName(p.kind));
  if (p.line) state.lastLine[who] = p.line;
  renderEffects();
}

function clearCurveball(p) {
  if (state.cbActive?.kind === 'vip_arrives' || p.kind === 'vip_arrives') { state.vip = false; buildStage(); }
  Object.assign(state, { cbActive: null, black: false, dim: false, blank: false, flash: null, flashTag: null });
  if (p.resolution === 'presenter_restored') caption('Moderator', 'Slides restored.');
  const ms = p.recovery?.resume_after_ms;
  if (ms != null) caption('Moderator', `Back on track after ${(ms / 1000).toFixed(1)} s.`);
  renderEffects();
}

// ---- controls -------------------------------------------------------------------------------
const send = (msg) => state.link?.send(msg);
function control(action) {
  if (!MOCK) { send({ type: 'control', action }); return; }
  // The mock has no engine; answer controls locally with the events the engine would send.
  const L = state.link;
  if (action === 'pause') { L.pause(); L.emit('paused'); }
  else if (action === 'resume') { L.resume(); L.emit('resumed'); }
  else if (action === 'skip') L.emit('skipped');
  else if (action === 'restore_slides' && state.cbActive) L.emit('curveball_resolved', { curveball_id: state.cbActive.curveball_id, kind: state.cbActive.kind, resolution: 'presenter_restored', recovery: null });
}
async function begin() {
  if (!state.started) {
    send({ type: 'presentation_started' });
    send({ type: 'slide_changed', slide_number: state.slide });
  }
  state.started = true; state.joined = true; renderVeil();
  Object.values(state.live).forEach((room) => room?.startAudio?.().catch(() => {}));
  camOn();
  try {
    // Each utterance goes to Higgs STT on the server, which feeds it into the session; the
    // transcript comes back as a transcript_segment event like everything else.
    state.mic = await startMic({
      pushToTalk: state.config?.input_mode === 'push_to_talk',
      onLevel: (v) => { $('mic-level').style.width = `${Math.round(v * 100)}%`; },
      transcribe: async (wav, start, end) => {
        const res = await fetch(`/api/sessions/${sessionId}/speech?start_ms=${start}&end_ms=${end}`,
          { method: 'POST', headers: { 'content-type': 'audio/wav' }, body: wav });
        return res.ok ? (await res.json()).text : null;
      },
    });
    $('mic-label').textContent = state.config?.input_mode === 'push_to_talk' ? 'hold Space to talk' : 'mic · listening';
  } catch (e) { $('mic-label').textContent = `mic blocked: ${e.message}`; }
}

// ---- live faces: one LiveKit room per Higgs avatar; a renewed face takes over the tile -------
function loadScript(src) {
  return new Promise((ok, fail) => {
    const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = fail;
    document.head.append(s);
  });
}
function attachFeed(id, el) {
  const tile = document.querySelector(`#stage .tile[data-id="${CSS.escape(id)}"]`);
  if (!tile) return;
  tile.querySelectorAll('video.live-feed').forEach((x) => { if (x !== el) x.remove(); });
  tile.prepend(el);
  tile.classList.add('photo', 'live-on');
}
async function joinLive(p) {
  if (state.live[p.room]) return;
  state.live[p.room] = 'joining';
  if (!window.LivekitClient) await loadScript('https://cdn.jsdelivr.net/npm/livekit-client@2.15.0/dist/livekit-client.umd.js');
  const { Room, RoomEvent, Track } = window.LivekitClient;
  const room = new Room({ adaptiveStream: false });
  room.on(RoomEvent.TrackSubscribed, (track) => {
    const el = track.attach();
    if (track.kind === Track.Kind.Video) {
      el.className = 'live-feed'; el.muted = true; el.playsInline = true;
      state.liveEls[p.speaker] = el;
      attachFeed(p.speaker, el);
      const before = state.seatRoom[p.speaker];
      state.seatRoom[p.speaker] = room;
      if (before && before !== room) before.disconnect();
    } else if (track.kind === Track.Kind.Audio) {
      el.style.display = 'none'; document.body.append(el);
    }
  });
  room.on(RoomEvent.TrackUnsubscribed, (track) => {
    track.detach().forEach((el) => {
      el.remove();
      if (state.liveEls[p.speaker] === el) {
        delete state.liveEls[p.speaker];
        document.querySelector(`#stage .tile[data-id="${CSS.escape(p.speaker)}"]`)?.classList.remove('live-on');
      }
    });
  });
  await room.connect(p.url, p.token);
  room.startAudio().catch(() => {});
  state.live[p.room] = room;
}

// Your webcam: only ever shown to you, never sent anywhere.
async function camOn() {
  try {
    state.cam = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
    if ($('selfcam')) $('selfcam').srcObject = state.cam;
    document.querySelector('#stage .tile.you')?.classList.add('cam-on');
  } catch { /* camera blocked or absent: the seat stays a placeholder */ }
}
function hangUp() {
  state.mic?.stop(); state.mic = null;
  state.cam?.getTracks().forEach((t) => t.stop()); state.cam = null;
  Object.values(state.live).forEach((room) => room?.disconnect?.());
}
addEventListener('beforeunload', hangUp);
addEventListener('click', () => Object.values(state.live).forEach((room) => room?.startAudio?.().catch(() => {})));
const togglePause = () => { if (!state.done && state.started) control(state.paused ? 'resume' : 'pause'); };
const skip = () => { if (!state.done && state.started) { player.cancel(); control('skip'); } };
function moveSlide(d) {
  const max = state.deck ? state.deck.page_count : 99;
  const n = Math.min(max, Math.max(1, state.slide + d));
  if (n === state.slide) return;
  state.slide = n; renderSlide();
  send({ type: 'slide_changed', slide_number: n });
}
function end() {
  if (state.done) { location.href = MOCK ? '/report.html?mock=1' : `/report.html?session=${sessionId}`; return; }
  if (MOCK) { location.href = '/report.html?mock=1'; return; }
  player.cancel();
  if (state.phase === 'qna') send({ type: 'control', action: 'end' });
  else send({ type: 'presentation_ended' });
}
$('btn-pause').onclick = togglePause;
$('btn-skip').onclick = skip;
$('btn-restore').onclick = () => control('restore_slides');
$('btn-end').onclick = end;
$('prev').onclick = () => moveSlide(-1);
$('next').onclick = () => moveSlide(1);
window.addEventListener('keydown', (e) => {
  if (/INPUT|TEXTAREA/.test(e.target.tagName)) return;
  if (e.key === 'ArrowRight') moveSlide(1);
  else if (e.key === 'ArrowLeft') moveSlide(-1);
  else if (e.key === 'p' || e.key === 'P') togglePause();
  else if (e.key === 's' || e.key === 'S') skip();
});

// ---- boot -----------------------------------------------------------------------------------
function adopt(config, preset, meta) {
  state.config = config;
  state.personas = config.personas;
  state.images = meta?.images ?? {};
  state.setting = meta?.setting ?? PRESET_SETTING[preset?.id] ?? 'video';
  $('room-name').textContent = settingById(state.setting).name;
  document.title = `Pres AI · ${preset?.name ?? 'Room'}`;
}
if (MOCK) {
  $('conn').textContent = 'mocked session (no backend)';
  state.link = await playMock('demo_session', onEvent);
  adopt(state.link.config, state.link.preset, loadSessionMeta('mock'));
  state.deck = { page_count: MOCK_SLIDES.length, slides: MOCK_SLIDES.map((text, i) => ({ number: i + 1, text, image_url: null })) };
  $('mic-label').textContent = 'mic off (mock)';
  buildStage(); renderControls();
} else {
  try {
    const s = await getSession(sessionId);
    adopt(s.config, s.preset, loadSessionMeta(sessionId));
    state.deck = s.deck;
    state.faces = s.faces ?? {};
    if (s.phase !== 'setup' && s.elapsed_ms > 0) { // reload mid-call: the clock carries on
      state.started = true; state.elapsedS = Math.floor(s.elapsed_ms / 1000); state.joinedAtMs = s.elapsed_ms;
      state.slide = s.slide_number ?? state.slide;
    }
    buildStage(); renderControls();
    state.link = connect(sessionId, onEvent, (st) => { $('conn').textContent = st; });
  } catch (e) {
    $('stage').innerHTML = `<div class="veil"><div style="text-align:center;font-size:15px;color:var(--muted)">This room isn't available (${esc(e.message.slice(0, 120))}).<br><a href="/setup.html" style="color:var(--mint)">Set up a new one</a> or <a href="/room.html?mock=1" style="color:var(--mint)">watch a mocked session</a>.</div></div>`;
  }
}
