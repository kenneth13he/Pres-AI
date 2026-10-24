// Separate binary speech channel. Presenter turn IDs travel only on the room event bus.
import { connectTranscription } from '/js/realtime.js';

export async function connectVoice({ sessionId, player, onSegment = () => {},
  onStatus = () => {}, onLevel = () => {}, onSpeaking = () => {},
  onLatency = () => {}, onActivity = () => {}, onTurnStart = () => {},
  onTurnEnd = () => {}, onTurnDiscard = () => {}, onListeningState = () => {},
  canBeginTurn = () => true,
  clock = () => 0, pushToTalk = false }) {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${scheme}://${location.host}/ws/voice/${sessionId}`);
  ws.binaryType = 'arraybuffer';
  let mic = null, paused = false, speaking = false, stopped = false, playId = null;
  let first = false, utteranceEnd = null, listening = null, listeningReady = false;
  const cancelledPlays = new Set();
  const send = (data) => { if (ws.readyState === 1) ws.send(JSON.stringify(data)); };
  const gate = () => mic?.setEnabled(!paused && !speaking && !stopped);
  function markListening(value) {
    if (listeningReady === value) return;
    listeningReady = value; onListeningState(value);
  }
  function markSpeaking(value) {
    const changed = speaking !== value;
    speaking = value; gate(); if (changed) onSpeaking(value);
  }
  function rememberCancelled(id) {
    if (!id) return;
    cancelledPlays.add(id);
    if (cancelledPlays.size > 32) cancelledPlays.delete(cancelledPlays.values().next().value);
  }
  function discardInput() {
    // Invalidate worklet frames and vendor transcript mappings before cancelling speech.
    mic?.cancelTurn?.(); mic?.setEnabled(false);
    utteranceEnd = null;
  }
  function cancel() {
    discardInput(); rememberCancelled(playId); playId = null;
    player.cancel(); send({ type: 'cancel' }); markSpeaking(false);
  }
  const stop = () => {
    if (stopped) return;
    stopped = true; discardInput(); player.cancel(); playId = null;
    markSpeaking(false); markListening(false); void mic?.stop();
    send({ type: 'realtime_stopped' }); ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.close();
    window.removeEventListener('pagehide', stop); clearTimeout(hardLimit);
  };
  const hardLimit = setTimeout(() => { onStatus('Audio time limit reached. Reconnect to continue.'); stop(); }, 600000);
  window.addEventListener('pagehide', stop);

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { reject(new Error('Audio connection timed out.')); stop(); }, 10000);
    const fail = () => { clearTimeout(timeout); reject(new Error('Could not connect audio.')); stop(); };
    ws.onerror = fail; ws.onclose = fail;
    ws.onmessage = ({ data }) => {
      let event;
      try { event = typeof data === 'string' ? JSON.parse(data) : null; } catch { return; }
      if (event?.type === 'ready') { clearTimeout(timeout); resolve(); }
    };
  });

  ws.onmessage = async ({ data }) => {
    if (stopped) return;
    if (data instanceof ArrayBuffer) {
      if (!playId) return;
      if (!first) {
        first = true;
        onLatency({ speech_to_playback_ms: utteranceEnd == null ? null :
          Math.max(0, Math.round(clock() - utteranceEnd)) });
        utteranceEnd = null;
      }
      player.enqueue(data); return;
    }
    let event;
    try { event = JSON.parse(data); } catch { return; }
    if (event.type === 'speech_started' && event.play_id) {
      if (cancelledPlays.has(event.play_id)) return;
      player.cancel(); playId = event.play_id; first = false; markSpeaking(true);
    } else if (event.type === 'speech_complete') {
      const id = event.play_id;
      await player.whenIdle();
      if (!stopped && id === playId) {
        send({ type: 'played', play_id: id }); playId = null; markSpeaking(false);
      }
    } else if (event.type === 'cancel') {
      rememberCancelled(playId); playId = null; player.cancel(); markSpeaking(false);
    }
  };
  ws.onclose = () => { if (!stopped) { onStatus('Audio disconnected. Reconnect before continuing.'); stop(); } };
  ws.onerror = () => { onStatus('Audio connection failed.'); stop(); };

  async function startListening() {
    if (stopped) throw new Error('Audio is closed. Reconnect before opening the microphone.');
    if (mic?.active) return;
    if (listening) return listening;
    listening = openMicrophone();
    try { await listening; } finally { listening = null; }
  }
  async function openMicrophone() {
    try {
      mic = await connectTranscription({ sessionId, clock, pushToTalk, onLevel, onActivity,
        onSegment, onTurnStart, onTurnEnd, onTurnDiscard,
        canBeginTurn: () => !paused && !speaking && !stopped && canBeginTurn(),
        onListeningState(value) {
          if (!value && !stopped) { markListening(false); stop(); }
        },
        onStatus,
        onUtteranceEnd: (ms) => { utteranceEnd = ms; },
      });
      if (stopped) { void mic.stop(); return; }
      send({ type: 'realtime_started' }); gate(); markListening(true);
    } catch (error) { stop(); throw error; }
  }
  onStatus('Speech connected. Microphone is off.');
  return {
    startListening, stop, cancel,
    beginTurn: () => !paused && !speaking && !stopped && listeningReady && (mic?.beginTurn?.() ?? false),
    endTurn: () => !stopped && (mic?.endTurn?.() ?? false),
    cancelTurn: () => mic?.cancelTurn?.() ?? false,
    trackRealtime(started) { send({ type: started ? 'realtime_started' : 'realtime_stopped' }); },
    setPaused(value) {
      const next = Boolean(value);
      if (paused === next || stopped) return;
      paused = next; if (paused) cancel(); gate();
    },
    get speaking() { return speaking; },
    get listening() { return listeningReady && !stopped && mic?.active !== false; },
    get connected() { return !stopped && ws.readyState === 1; },
    get active() { return !stopped && ws.readyState === 1; },
  };
}
