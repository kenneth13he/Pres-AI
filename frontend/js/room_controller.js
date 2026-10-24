// Presentation state, capture lifecycle and backend coordination; no DOM or vendor SDK.
export async function bootRoom({ view, connect, getSession, isMock, createPlayer, playMock,
  connectVoice, fetch, location, window, now = () => performance.now(),
  setInterval = globalThis.setInterval, clearInterval = globalThis.clearInterval }) {
  const sessionId = new URLSearchParams(location.search).get('session');
  const state = { sessionId, phase: 'setup', inputMode: 'push_to_talk', startedAt: null,
    started: false, startSent: false, busConnected: false, audioReady: false, connecting: false,
    disposed: false, busy: false, pending: false, transcribing: false, slide: 1, deck: null, inQna: false };
  const player = createPlayer(), seen = new Set(), captionedQuestions = new Set();
  const validTurns = new Set(), cancelledTurns = new Set();
  let voice, link, interval, elapsedBase = 0, elapsedAt = null, countdown = null, mock = false, voiceEpoch = 0, controlEpoch = 0, audioOpening = null, pendingAction = null;
  let audioSafety = null;
  const wallClock = () => state.startedAt == null ? 0 : Math.max(0, Math.round(now() - state.startedAt));
  const elapsed = () => elapsedBase + (elapsedAt == null ? 0 : now() - elapsedAt);
  const remaining = () => countdown == null ? null : Math.max(0, countdown.ms - (countdown.at == null ? 0 : now() - countdown.at));
  const send = (message) => link?.send(message);
  const canStartTurn = () => !state.disposed && state.started && state.audioReady && state.busConnected && !state.pending
    && !state.transcribing && ['presenting', 'answering', 'qna', 'recovering'].includes(state.phase) && !state.busy;
  function discardTurn(turn_id) {
    if (!turn_id || cancelledTurns.has(turn_id)) return;
    cancelledTurns.add(turn_id); validTurns.delete(turn_id);
    if (!validTurns.size) state.transcribing = false;
    send({ type: 'presenter_turn_cancelled', turn_id });
  }
  function discardTurns() { for (const id of [...validTurns]) discardTurn(id); }
  function controls() {
    view.controls({ started: state.started, busy: state.busy, listening: state.audioReady,
      ptt: state.inputMode === 'push_to_talk', canPresent: !mock && state.busConnected,
      connecting: state.connecting || state.startSent && !state.started, pending: state.pending, inQna: state.inQna,
      canEndWhileConnecting: state.connecting && pendingAction === 'resume'
        || state.pending && Boolean(audioSafety) && pendingAction !== 'end',
      canTalk: state.busConnected && !state.transcribing && ['presenting', 'answering', 'qna', 'recovering'].includes(state.phase) });
  }
  function syncCapture() {
    voice?.setPaused(['paused', 'report'].includes(state.phase) || state.pending || !state.started || !state.busConnected);
    controls();
  }
  function tick() { view.timer({ elapsed_ms: elapsed(), remaining_ms: remaining(), paused: state.phase === 'paused' }); }
  function safetyNotice(safety) {
    if (audioSafety !== safety || state.disposed || state.phase === 'report') return;
    const message = !safety.confirmed ? (safety.failed
      ? 'Audio disconnected. Local timer frozen. Press Resume to retry the connection and Pause.'
      : 'Audio disconnected. Local timer frozen while the room pauses…')
      : !state.busConnected ? 'Connection lost. Session paused. Reload the room, then press Resume to reconnect.'
        : 'Audio disconnected. Session paused. Press Resume to reconnect and continue.';
    view.notice?.(message); view.audio(message);
  }
  function suspendForAudioLoss(cause, previouslyReady = state.audioReady) {
    if (!previouslyReady || mock || state.disposed || !state.started || state.connecting
      || ['setup', 'report'].includes(state.phase) || pendingAction === 'end') return;
    const alreadyPaused = state.phase === 'paused' && pendingAction !== 'resume';
    const safety = audioSafety || { cause, confirmed: alreadyPaused,
      needsPause: !alreadyPaused && pendingAction !== 'pause', running: false, failed: false };
    if (pendingAction === 'resume') { safety.confirmed = false; safety.needsPause = true; }
    audioSafety = safety; state.audioReady = false; state.busy = false; voiceEpoch++;
    discardTurns(); voice?.cancelTurn(); void Promise.resolve(voice?.stop()).catch(() => {});
    player.cancel(); view.speaking(null); setPhase('paused'); safetyNotice(safety);
    void requestSafetyPause();
  }
  async function requestSafetyPause() {
    const safety = audioSafety;
    if (!safety || !safety.needsPause || safety.running || state.pending || state.disposed || state.phase === 'report') return;
    safety.running = true; safety.needsPause = false; safety.failed = false;
    try { await control('pause', safety); }
    finally {
      safety.running = false;
      if (audioSafety === safety && safety.needsPause) void requestSafetyPause();
    }
  }
  function setPhase(phase) {
    if (state.disposed || state.phase === 'report') return;
    if (phase === 'qna') { state.inQna = true; countdown = null; }
    if (audioSafety && !['paused', 'report'].includes(phase)) phase = 'paused';
    if (phase !== state.phase) {
      elapsedBase = elapsed(); elapsedAt = ['setup', 'paused', 'report'].includes(phase) ? null : now();
      if (countdown) { countdown.ms = remaining(); countdown.at = phase === 'paused' ? null : now(); }
    }
    state.phase = phase;
    if (phase !== 'setup') { state.started = true; state.startSent = false; }
    view.phase(phase); syncCapture(); tick();
    if (phase === 'report') {
      audioSafety = null;
      view.notice?.(''); endAudio();
      view.ended(mock ? '/report.html?mock=1' : `/report.html?session=${encodeURIComponent(sessionId)}`);
    }
  }
  function endAudio() {
    state.audioReady = false; state.busy = false;
    discardTurns(); voiceEpoch++;
    voice?.cancelTurn(); voice?.stop(); player.close();
    if (interval != null) { clearInterval(interval); interval = null; }
    controls();
  }
  function onEvent(event, historic = false) {
    if (state.disposed || !event || typeof event !== 'object') return;
    if (!mock && sessionId && event.session_id && event.session_id !== sessionId) return;
    if (!historic && state.phase === 'report' && event.type !== 'session_ended') return;
    const key = JSON.stringify(event); if (seen.has(key)) return; seen.add(key);
    const p = event.payload || {};
    switch (event.type) {
      case 'session_started':
        if (!historic) { state.started = true; state.startSent = false; syncCapture(); }
        break;
      case 'phase_changed':
        if (!historic) {
          if (p.to === 'paused' && audioSafety) {
            audioSafety.confirmed = true; audioSafety.needsPause = false;
          }
          setPhase(p.to); if (audioSafety) safetyNotice(audioSafety);
        } break;
      case 'slide_changed': state.slide = p.slide_number; view.slide(state.slide); break;
      case 'transcript_segment': view.caption('you', p.text); break;
      case 'question_queued':
        if (!historic && !audioSafety) view.notice?.('');
        captionedQuestions.add(p.question);
        view.caption(p.persona_id, p.question, p.follow_up_of ? 'follow-up' : p.curveball_id ? 'curveball' : null); break;
      case 'ai_speech_started':
        if (!historic && !audioSafety) { state.busy = true; view.speaking(p.speaker); controls(); }
        if (!captionedQuestions.delete(p.line)) view.caption(p.speaker, p.line); break;
      case 'ai_speech_ended':
        if (!historic) { state.busy = false; view.speaking(null); controls(); } break;
      case 'curveball_triggered':
        if (!historic && !audioSafety) view.notice?.('');
        view.curveball(p);
        if (p.speaker === 'ui') view.caption('moderator', p.line || p.kind, p.kind);
        if (!historic && p.sfx_url) player.playSfx?.(p.sfx_url); break;
      case 'curveball_resolved':
        view.curveball(null);
        if (p.recovery?.resume_after_ms != null) view.caption('moderator', `Speech resumed after ${(p.recovery.resume_after_ms / 1000).toFixed(1)} seconds.`);
        break;
      case 'timer_override': if (!historic) { countdown = { ms: p.remaining_ms, at: state.phase === 'paused' ? null : now() }; tick(); } break;
      case 'audio_status':
        if (!historic && p.status === 'waiting_for_audio') {
          if (audioSafety) safetyNotice(audioSafety);
          else if (state.phase === 'paused') view.notice?.('Audio disconnected. Session paused. Press Resume to reconnect and continue.');
          else view.audio('Connect your microphone to continue.');
        } break;
      case 'skipped':
        view.caption('moderator', 'Skipped — carry on.');
        if (!historic) {
          if (audioSafety) safetyNotice(audioSafety);
          else view.notice?.('Question skipped. No penalty. The transcript keeps what was said.');
        }
        break;
      case 'error': view.error(p.message || 'Something went wrong. You can pause or skip and continue.'); break;
      case 'session_ended':
        if (!historic) { setPhase('report'); link?.close(); } break;
    }
  }
  async function start() {
    if (state.disposed || state.phase === 'report' || !state.busConnected || mock) return false;
    if (audioOpening) return audioOpening;
    audioOpening = openAudio();
    try { return await audioOpening; } finally { audioOpening = null; }
  }
  async function openAudio() {
    state.connecting = true; view.error(''); controls();
    const generation = ++voiceEpoch;
    const current = () => generation === voiceEpoch && !state.disposed;
    try {
      await player.resume();
      discardTurns(); state.audioReady = false;
      await voice?.stop();
      voice = await connectVoice({ sessionId, player, clock: wallClock,
        canBeginTurn: canStartTurn,
        pushToTalk: state.inputMode === 'push_to_talk',
        onLevel: (value) => view.meter(value),
        onStatus: (text) => {
          if (current()) view.audio(/^Listening/.test(text)
            ? (state.inputMode === 'push_to_talk' ? 'Ready. Hold to speak and release when finished.' : 'Listening in hands-free mode.') : text);
        },
        onListeningState: (active) => {
          if (!current()) return;
          const previouslyReady = state.audioReady;
          state.audioReady = active;
          if (!active) { state.transcribing = false; suspendForAudioLoss('audio', previouslyReady); }
          controls();
        },
        onSpeaking: (active) => { if (current()) { state.busy = active; controls(); } },
        onActivity: () => { if (current()) send({ type: 'presenter_speech_activity' }); },
        onTurnStart: (turn_id) => {
          if (current() && state.started && !state.pending) {
            validTurns.add(turn_id); send({ type: 'presenter_turn_started', turn_id });
            view.audio('Listening — release when your point is complete.');
          }
        },
        onTurnEnd: (turn_id) => {
          if (current() && validTurns.has(turn_id)) {
            state.transcribing = true; send({ type: 'presenter_turn_ended', turn_id });
            view.audio('Turning your speech into a transcript…'); controls();
          }
        },
        onTurnDiscard: (turn_id) => { if (current()) { discardTurn(turn_id); controls(); } },
        onSegment: (segment, turn_id) => {
          if (!current() || state.pending || ['setup', 'paused', 'report'].includes(state.phase) || cancelledTurns.has(turn_id)) return;
          state.transcribing = false; validTurns.delete(turn_id);
          send({ type: 'transcript_segment', turn_id, segment }); controls();
          view.audio(state.phase === 'answering' ? 'Answer sent to your audience.' : 'Point captured. You can continue presenting.');
        },
      });
      if (!current()) { await voice.stop(); return false; }
      voice.setPaused(true); await voice.startListening();
      if (!current()) { await voice.stop(); return false; }
      if (!voice.active || !voice.listening) throw new Error('Audio disconnected while opening the microphone.');
      state.audioReady = true;
      if (!state.started) {
        state.startedAt = now(); state.startSent = true; elapsedBase = 0; elapsedAt = now();
        send({ type: 'presentation_started' });
        if (state.deck) send({ type: 'slide_changed', slide_number: state.slide });
      }
      syncCapture();
      view.audio(state.inputMode === 'push_to_talk'
        ? 'Microphone ready. Hold the button or Space, then release when finished.' : 'Listening in hands-free mode.');
      return true;
    } catch (error) {
      await voice?.stop(); state.audioReady = false;
      if (current()) view.error(`${error.message || 'Audio connection failed.'} Reconnect when ready.`);
      return false;
    } finally { state.connecting = false; controls(); }
  }
  async function postControl(action) {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/control`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ action }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The room control did not complete.');
    return result;
  }
  async function control(action, safety = null) {
    if (!state.started || state.disposed || state.phase === 'report' || mock
      || safety && audioSafety !== safety
      || state.pending && !(action === 'end' && pendingAction !== 'end'
        && (pendingAction === 'resume' && audioOpening || audioSafety))) return;
    const interrupts = action !== 'restore_slides';
    const command = ++controlEpoch, timerWasRunning = elapsedAt != null;
    if (interrupts) { state.pending = true; pendingAction = action; }
    if (action === 'end' && audioSafety) audioSafety.needsPause = false;
    if (action === 'pause') {
      elapsedBase = elapsed(); elapsedAt = null;
      if (countdown) { countdown.ms = remaining(); countdown.at = null; }
      tick();
    }
    if (interrupts) { discardTurns(); voice?.cancelTurn(); voice?.setPaused(true); voice?.cancel(); player.cancel(); }
    controls();
    try {
      if (action === 'resume') {
        if (!(state.audioReady && voice?.active && voice?.listening)) {
          const ready = await start();
          if (command !== controlEpoch || state.disposed || state.phase !== 'paused') return;
          if (!ready || !(state.audioReady && voice?.active && voice?.listening)) {
            throw new Error('Could not reconnect the microphone. The session is still paused. Click Resume to try again.');
          }
        }
        if (command !== controlEpoch || state.disposed || state.phase !== 'paused') return;
        if (!state.busConnected) throw new Error('The room connection was lost. The session is still paused. Reload to reconnect.');
        if (audioSafety && !audioSafety.confirmed) {
          const paused = await postControl('pause');
          if (command !== controlEpoch || state.disposed || state.phase === 'report') return;
          if (paused.phase !== 'paused') throw new Error('Could not confirm the room is paused. Try Resume again when connected.');
          audioSafety.confirmed = true;
        }
      }
      const result = await postControl(action);
      if (command !== controlEpoch || state.disposed || state.phase === 'report') return;
      if (safety && result.phase !== 'paused' && result.phase !== 'report') throw new Error('The room did not confirm Pause.');
      if (safety) { safety.confirmed = true; safetyNotice(safety); }
      if (action === 'pause' && audioSafety && result.phase === 'paused') {
        audioSafety.confirmed = true; audioSafety.failed = false; safetyNotice(audioSafety);
      }
      if (action === 'resume') {
        if (!(state.audioReady && voice?.active && voice?.listening && state.busConnected)) {
          suspendForAudioLoss('audio', true);
          if (audioSafety) { audioSafety.confirmed = false; audioSafety.needsPause = true; }
          throw new Error('Audio disconnected while resuming. The local timer is still frozen. Press Resume to reconnect.');
        }
        audioSafety = null; view.notice?.('');
      }
      if (action === 'end' && audioSafety && result.phase !== 'report') {
        audioSafety.confirmed = false; audioSafety.needsPause = true;
      }
      if (result.phase && command === controlEpoch) setPhase(result.phase);
    } catch (error) {
      if (command !== controlEpoch || state.disposed || state.phase === 'report') return;
      if (action === 'pause' && timerWasRunning && state.phase !== 'paused' && !audioSafety) {
        elapsedAt = now(); if (countdown) countdown.at = now();
      }
      const pauseSafety = safety || (action === 'pause' ? audioSafety : null);
      if (pauseSafety) {
        if (pauseSafety.confirmed) safetyNotice(pauseSafety);
        else {
          pauseSafety.failed = true; safetyNotice(pauseSafety);
          view.error('Audio disconnected. The local timer is frozen, but the room could not confirm Pause. Check the connection, then press Resume to retry.');
        }
      } else view.error(error.message);
    }
    finally {
      if (interrupts && command === controlEpoch) { state.pending = false; pendingAction = null; }
      if (!state.disposed) { syncCapture(); void requestSafetyPause(); }
    }
  }
  function changeSlide(delta) {
    if (!state.deck || state.disposed || state.phase === 'report') return;
    const next = Math.max(1, Math.min(state.deck?.page_count || Math.max(1, state.slide + delta), state.slide + delta));
    state.slide = next; view.slide(next); send({ type: 'slide_changed', slide_number: next });
  }
  async function stop() {
    if (state.disposed) return; state.disposed = true;
    audioSafety = null;
    discardTurns(); voiceEpoch++; voice?.cancelTurn(); await voice?.stop(); state.audioReady = false;
    link?.close(); await player.close();
    if (interval != null) clearInterval(interval);
    window.removeEventListener('pagehide', stop); view.dispose();
  }
  view.bind({ start, pause: () => control(state.phase === 'paused' ? 'resume' : 'pause'),
    skip: () => control('skip'), end: () => control('end'), restore: () => control('restore_slides'),
    previous: () => changeSlide(-1), next: () => changeSlide(1),
    beginTurn: () => canStartTurn() && (voice?.beginTurn() ?? false),
    endTurn: () => voice?.endTurn(), cancelTurn: () => voice?.cancelTurn(),
    stopReply: () => { discardTurns(); voice?.cancelTurn(); voice?.cancel(); player.cancel(); } });
  window.addEventListener('pagehide', stop);
  if (isMock() || !sessionId) {
    mock = true; link = await playMock('demo_session', onEvent);
    state.inputMode = link.config.input_mode || 'push_to_talk';
    view.configure({ config: link.config, preset: link.preset }); view.connection('Mock replay — no live microphone or audience calls.');
    view.slide(1);
  } else {
    let snapshot;
    try { snapshot = await getSession(sessionId); }
    catch (error) { await stop(); throw error; }
    if (state.disposed) return { state, onEvent, start, stop, tick };
    state.inputMode = snapshot.config.input_mode || 'push_to_talk'; state.deck = snapshot.deck;
    state.started = snapshot.phase !== 'setup';
    state.inQna = Boolean(snapshot.in_qna ?? (snapshot.phase === 'qna'
      || (snapshot.events || []).some((event) => event.type === 'phase_changed' && event.payload?.to === 'qna')));
    state.startedAt = state.started ? now() - snapshot.session_clock_ms : null;
    elapsedBase = snapshot.elapsed_ms || 0; state.slide = snapshot.slide_number || 1;
    view.configure(snapshot);
    for (const event of snapshot.events || []) onEvent(event, true);
    if (snapshot.timer_remaining_ms != null) countdown = { ms: snapshot.timer_remaining_ms, at: null };
    setPhase(snapshot.phase); view.slide(state.slide);
    if (snapshot.phase === 'report') {
      view.connection('Session finished. Your report is ready.');
      return { state, onEvent, start, stop, tick };
    }
    view.audio('Microphone is off. Start when ready.');
    let audience = snapshot.reasoning?.adapter;
    const connectionLabel = () => audience === 'mock' ? 'Connected · audience test mode'
      : audience === 'boson' ? 'Connected · live Boson audience'
        : audience === 'claude' ? 'Connected · live Claude audience' : 'Connected';
    link = connect(sessionId, onEvent, (status) => {
      if (state.disposed || state.phase === 'report') return;
      state.busConnected = status === 'live';
      view.connection(state.busConnected ? connectionLabel() : 'Room disconnected. Reload to reconnect.');
      if (!state.busConnected) {
        suspendForAudioLoss('room'); voice?.cancelTurn(); voice?.setPaused(true);
      }
      else if (state.started) syncCapture();
      controls();
    });
    // Provider metadata is optional: it must never delay an already valid session/socket.
    Promise.resolve().then(() => fetch('/health')).then((response) => response.json()).then((health) => {
      if (state.disposed || state.phase === 'report') return;
      const adapters = health?.adapters || {};
      audience ||= adapters.orchestrator || adapters.llm;
      if (state.busConnected) view.connection(connectionLabel());
      if (!voice && !state.connecting && adapters.voice && adapters.voice !== 'higgs') {
        view.audio('Live voice is unavailable. Check the local voice configuration.');
      }
    }).catch(() => {});
  }
  if (state.phase !== 'report') interval = setInterval(tick, 250);
  tick(); controls();
  return { state, onEvent, start, stop, tick };
}
