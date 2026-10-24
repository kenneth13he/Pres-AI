// Ephemeral browser STT; each presenter turn has an ID independent of vendor item IDs.
import { startMic } from './mic.js';
import { createUtteranceGate } from './voice_vad.js';

export async function connectTranscription({ sessionId, onSegment = () => {},
  onStatus = () => {}, onUtteranceEnd = () => {}, onActivity = () => {},
  onTurnStart = () => {}, onTurnEnd = () => {}, onTurnDiscard = () => {},
  canBeginTurn = () => true,
  onListeningState = () => {}, clock = () => performance.now(),
  onLevel = () => {}, pushToTalk = false } = {}) {
  let ws, mic, gate, stopped = false, enabled = true, level = 0, ready = false;
  let hardTimer, idleTimer, activityAt = -Infinity, lastActivity = performance.now();
  let captureTurn = null, sequence = 0;
  const waiting = [], items = new Map(), pending = new Map();
  const controller = new AbortController();
  const requestTimer = setTimeout(() => controller.abort(), 10000);
  const send = (message) => {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  };
  const canCapture = () => enabled && !stopped && pending.size === 0;
  function updateCapture() { mic?.setEnabled(canCapture()); }
  function clearInput() { send({ type: 'input_audio_buffer.clear' }); }
  function beginCapture() {
    if (!canCapture() || captureTurn) return;
    captureTurn = globalThis.crypto?.randomUUID?.() ?? `turn-${Math.round(clock())}-${++sequence}`;
    onTurnStart(captureTurn);
  }
  function discardCapture(resetGate = true) {
    const id = captureTurn; captureTurn = null;
    if (resetGate) gate?.reset();
    clearInput();
    if (id) onTurnDiscard(id);
  }
  function discardAll() {
    const ids = new Set(pending.keys());
    if (captureTurn) ids.add(captureTurn);
    captureTurn = null; pending.clear(); waiting.fill(null); items.clear();
    mic?.setEnabled(false); gate?.reset(); clearInput();
    for (const id of ids) onTurnDiscard(id);
  }
  async function stop() {
    if (stopped) return;
    stopped = true; enabled = false; discardAll();
    clearTimeout(requestTimer); clearTimeout(hardTimer); clearInterval(idleTimer);
    controller.abort(); waiting.length = 0;
    window.removeEventListener('pagehide', stop);
    if (ws) { ws.onopen = null; ws.onmessage = null; ws.onerror = null; ws.onclose = null; ws.close(); }
    if (ready) { ready = false; onListeningState(false); }
    await mic?.stop();
  }
  function onMessage(event) {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === 'input_audio_buffer.committed') {
      const metadata = waiting.shift();
      if (metadata && data.item_id) items.set(data.item_id, metadata);
    } else if (data.type === 'conversation.item.input_audio_transcription.completed') {
      const metadata = items.get(data.item_id); items.delete(data.item_id);
      if (!enabled || !metadata || !pending.delete(metadata.turnId)) return;
      if (data.transcript?.trim()) {
        onSegment({ ...metadata.interval, text: data.transcript.trim(), speaker: 'presenter',
          confidence: null }, metadata.turnId);
      } else onTurnDiscard(metadata.turnId);
      updateCapture();
    } else if (data.type === 'error' || data.type === 'conversation.item.input_audio_transcription.failed') {
      onStatus('Transcription failed. Restart the microphone to reconnect.'); void stop();
    }
  }
  try {
    onStatus('Connecting transcription…');
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/voice/client_secret`, {
      method: 'POST', signal: controller.signal,
    });
    if (!response.ok) throw new Error('Could not authorize voice.');
    const secret = await response.json(); clearTimeout(requestTimer);
    if (!secret.value || !secret.url || !secret.config) throw new Error('Voice setup is incomplete.');
    ws = new WebSocket(secret.url, ['realtime', `bai-client-secret.${secret.value}`]);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Transcription connection timed out.')), 12000);
      function fail() { clearTimeout(timer); reject(new Error('Could not connect to transcription.')); }
      ws.onerror = fail; ws.onclose = fail;
      ws.onopen = () => {
        const session = secret.config.session ?? secret.config;
        send({ type: 'session.update', session: { ...session, audio: { ...session.audio,
          input: { ...session.audio?.input, turn_detection: null } } } });
      };
      ws.onmessage = (event) => {
        let data;
        try { data = JSON.parse(event.data); } catch { return; }
        if (data.type === 'session.created' || data.type === 'session.updated') {
          clearTimeout(timer); resolve();
        } else if (data.type === 'error') fail();
      };
    });
    ws.onopen = null; ws.onmessage = onMessage;
    ws.onerror = () => { onStatus('Transcription connection failed.'); void stop(); };
    ws.onclose = () => { onStatus('Transcription disconnected. Restart the microphone.'); void stop(); };
    gate = createUtteranceGate({ clock, pushToTalk,
      onClear() { if (captureTurn) discardCapture(false); else clearInput(); },
      onLimit: () => onStatus('Question exceeded one minute and was discarded. Release and try a shorter question.'),
      onAppend(bytes) {
        if (!captureTurn) beginCapture();
        let raw = '';
        for (const byte of bytes) raw += String.fromCharCode(byte);
        send({ type: 'input_audio_buffer.append', audio: btoa(raw) });
      },
      onCommit(interval) {
        if (!captureTurn) beginCapture();
        const turnId = captureTurn; captureTurn = null;
        const metadata = { turnId, interval }; pending.set(turnId, metadata); waiting.push(metadata);
        onUtteranceEnd(interval.end_ms); lastActivity = performance.now();
        send({ type: 'input_audio_buffer.commit' }); onTurnEnd(turnId); updateCapture();
      },
    });
    hardTimer = setTimeout(() => {
      onStatus('Microphone closed after the ten-minute limit. Restart to continue.'); void stop();
    }, 600000);
    idleTimer = setInterval(() => {
      if (performance.now() - lastActivity >= 60000) {
        onStatus('Microphone closed after one minute without speech. Restart to continue.'); void stop();
      }
    }, 5000);
    window.addEventListener('pagehide', stop);
    mic = await startMic({ pushToTalk, onTurnStart: beginCapture,
      canBeginTurn: () => canCapture() && canBeginTurn(),
      onLevel(value) { level = value; onLevel(value); },
      onPcm(bytes) {
        if (!canCapture()) return;
        const timestamp = clock();
        if (pushToTalk || level >= 0.008) {
          lastActivity = performance.now();
          if (timestamp - activityAt >= 250) { activityAt = timestamp; onActivity(timestamp); }
        }
        gate.feed(bytes, level);
      },
      onCommit() { if (canCapture()) gate.commit(); }, onDiscard: discardCapture,
    });
    if (stopped) { await mic?.stop(); throw new Error('Transcription connection closed during setup.'); }
    ready = true; onListeningState(true); updateCapture();
    onStatus('Listening · final transcripts · browser capture timestamps');
    return {
      hasSTT: true, stop,
      beginTurn: () => canCapture() && (mic?.beginTurn() ?? false),
      endTurn: () => mic?.endTurn() ?? false,
      cancelTurn() {
        const hadTurn = Boolean(captureTurn || pending.size);
        discardAll(); updateCapture(); return hadTurn;
      },
      get active() { return !stopped; },
      get listening() { return ready && !stopped; },
      get pending() { return pending.size > 0; },
      setEnabled(value) {
        const next = Boolean(value);
        if (stopped || enabled === next) return;
        enabled = next;
        if (!enabled) discardAll();
        level = 0; activityAt = -Infinity; updateCapture();
        if (enabled) lastActivity = performance.now();
      },
    };
  } catch {
    await stop();
    const message = 'Could not start transcription. Check the microphone and Boson connection.';
    onStatus(message); throw new Error(message);
  }
}
