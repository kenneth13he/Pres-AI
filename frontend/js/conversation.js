// Explicit voice-check mode: actual Higgs speech-to-speech, separate from PresAI's brain.
import { startMic } from './mic.js';
import { createUtteranceGate } from './voice_vad.js';

export async function connectConversation({ sessionId, player, clock = () => performance.now(),
  pushToTalk = false, onSegment = () => {}, onStatus = () => {}, onLevel = () => {},
  onSpeaking = () => {}, onLatency = () => {}, onAssistantText = () => {},
  voiceId = 'eleanor', personaName = 'Moderator' } = {}) {
  let ws, mic, gate, starting, stopped = false, paused = false, speaking = false;
  let activeTurn = null, level = 0, sequence = 0, responseTimer, hardTimer, idleTimer;
  let lastActivity = performance.now();
  const commits = [], requests = [], items = new Map(), responses = new Map(), userItems = new Set();
  const abort = new AbortController();
  const requestTimer = setTimeout(() => abort.abort(), 10000);
  const send = (message) => {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  };
  const updateMic = () => {
    const enabled = !stopped && !paused && !activeTurn;
    gate?.setEnabled(enabled); mic?.setEnabled(enabled);
  };
  function markSpeaking(value) {
    if (speaking === value) return;
    speaking = value; onSpeaking(value);
  }
  function cancel() {
    const turn = activeTurn;
    if (turn) {
      turn.cancelled = true;
      if (turn.responseId && !turn.done) {
        send({ type: 'response.cancel', response_id: turn.responseId });
      }
    }
    for (const entry of items.values()) entry.cancelled = true;
    clearTimeout(responseTimer); activeTurn = null;
    gate?.reset(); send({ type: 'input_audio_buffer.clear' });
    player.cancel(); markSpeaking(false); updateMic();
  }
  async function stop() {
    if (stopped) return;
    stopped = true; cancel();
    clearTimeout(requestTimer); clearTimeout(hardTimer); clearInterval(idleTimer);
    abort.abort(); commits.length = 0; requests.length = 0; items.clear(); responses.clear(); userItems.clear();
    window.removeEventListener('pagehide', stop);
    if (ws) {
      ws.onopen = null; ws.onmessage = null; ws.onerror = null; ws.onclose = null; ws.close();
    }
    await mic?.stop();
  }
  function fail(message = 'Live conversation failed. Restart the microphone to reconnect.') {
    onStatus(message); void stop();
  }
  function commit(interval) {
    if (stopped || paused || activeTurn) return;
    const turn = { interval, number: ++sequence, responseId: null, requested: false,
      cancelled: false, done: false, firstAudio: false, text: '', textFinal: false };
    activeTurn = turn; commits.push(turn); lastActivity = performance.now();
    send({ type: 'input_audio_buffer.commit' }); updateMic();
    onStatus('Thinking about what you said…');
    responseTimer = setTimeout(() => fail('Live reply timed out. Restart to try again.'), 20000);
  }
  async function finish(turn) {
    await player.whenIdle();
    if (stopped || turn.cancelled || activeTurn !== turn) return;
    clearTimeout(responseTimer); responses.delete(turn.responseId); activeTurn = null;
    markSpeaking(false); updateMic(); lastActivity = performance.now();
    onStatus(paused ? 'Live conversation paused.' : 'Listening. The next reply will respond to what you say.');
  }
  function maybeRequest(turn) {
    if (!turn || turn.cancelled || turn !== activeTurn || turn.requested || paused || stopped) return;
    if (!turn.itemId || !userItems.has(turn.itemId)) return;
    userItems.delete(turn.itemId); turn.requested = true; requests.push(turn);
    send({ type: 'response.create' });
    if (turn.transcriptFinal) items.delete(turn.itemId);
  }
  function onMessage(event) {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === 'input_audio_buffer.committed') {
      const turn = commits.shift();
      if (!turn || turn.cancelled || stopped) return;
      if (data.item_id) { turn.itemId = data.item_id; items.set(data.item_id, turn); }
      maybeRequest(turn); return;
    }
    if (data.type === 'conversation.item.added' || data.type === 'conversation.item.created') {
      if (data.item?.role === 'user' && data.item.id) {
        userItems.add(data.item.id);
        if (userItems.size > 64) userItems.delete(userItems.values().next().value);
        maybeRequest(items.get(data.item.id));
      }
      return;
    }
    if (data.type === 'conversation.item.input_audio_transcription.completed') {
      const turn = items.get(data.item_id);
      if (turn) { turn.transcriptFinal = true; if (turn.requested) items.delete(data.item_id); }
      if (turn && !turn.cancelled && data.transcript?.trim()) {
        onSegment({ ...turn.interval, text: data.transcript.trim(), speaker: 'presenter', confidence: null });
      }
      return;
    }
    if (data.type === 'error' || data.type === 'conversation.item.input_audio_transcription.failed') {
      fail(); return;
    }
    if (data.type === 'response.created') {
      const id = data.response?.id, turn = requests.shift();
      if (!id) return;
      if (!turn || turn.cancelled || turn !== activeTurn || stopped || paused) {
        send({ type: 'response.cancel', response_id: id }); return;
      }
      turn.responseId = id; responses.set(id, turn);
      player.cancel(); markSpeaking(true); updateMic();
      onStatus('Audience is responding to your words. Microphone paused.'); return;
    }
    const id = data.response_id ?? data.response?.id, turn = responses.get(id);
    if (!turn || turn.cancelled || turn !== activeTurn || stopped) return;
    if (data.type === 'response.output_audio.delta' || data.type === 'response.audio.delta') {
      if (!data.delta) return;
      try {
        const raw = atob(data.delta), pcm = Uint8Array.from(raw, (char) => char.charCodeAt(0));
        if (!turn.firstAudio && pcm.length) {
          turn.firstAudio = true;
          onLatency({ speech_to_playback_ms: Math.max(0, Math.round(clock() - turn.interval.end_ms)) });
        }
        player.enqueue(pcm);
      } catch { fail('Live audio could not be played. Restart to reconnect.'); }
    } else if (data.type === 'response.output_audio_transcript.delta'
      || data.type === 'response.audio_transcript.delta') {
      turn.text += data.delta ?? '';
      onAssistantText(turn.text, { final: false, response_id: id });
    } else if (data.type === 'response.output_audio_transcript.done'
      || data.type === 'response.audio_transcript.done') {
      turn.text = data.transcript ?? turn.text; turn.textFinal = true;
      onAssistantText(turn.text, { final: true, response_id: id });
    } else if (data.type === 'response.done') {
      turn.done = true;
      if (!turn.textFinal && turn.text) {
        turn.textFinal = true; onAssistantText(turn.text, { final: true, response_id: id });
      }
      if (data.response?.status === 'failed') { fail(); return; }
      void finish(turn).catch(() => fail('Live audio playback failed. Restart to reconnect.'));
    }
  }
  async function startListening() {
    if (stopped) throw new Error('Live conversation is closed. Reconnect first.');
    if (mic) return;
    if (starting) return starting;
    starting = (async () => {
      try {
        mic = await startMic({ pushToTalk, onLevel(value) { level = value; onLevel(value); },
          onPcm(bytes) {
            if (stopped || paused || activeTurn) return;
            if (level >= 0.015) lastActivity = performance.now();
            gate.feed(bytes, level);
          },
          onCommit() { if (!stopped && !paused && !activeTurn) gate.commit(); },
          onDiscard() {
            gate.reset(); send({ type: 'input_audio_buffer.clear' });
            onStatus('Unfinished question discarded. Hold to speak again.');
          },
        });
        if (stopped) { await mic?.stop(); return; }
        updateMic(); lastActivity = performance.now();
        onStatus(paused ? 'Live conversation paused.' : 'Listening. Replies are generated from your speech.');
      } catch {
        await stop(); throw new Error('Could not start the microphone for live conversation.');
      }
    })();
    try { await starting; } finally { starting = null; }
  }
  try {
    onStatus('Connecting live speech conversation…');
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/voice/client_secret`, {
      method: 'POST', signal: abort.signal,
    });
    if (!response.ok) throw new Error('Voice authorization failed.');
    const secret = await response.json(); clearTimeout(requestTimer);
    if (!secret.url || !secret.value || !secret.config) throw new Error('Incomplete voice setup.');
    ws = new WebSocket(secret.url, ['realtime', `bai-client-secret.${secret.value}`]);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Connection timed out.')), 12000);
      const failed = () => { clearTimeout(timeout); reject(new Error('Connection failed.')); };
      ws.onerror = failed; ws.onclose = failed;
      ws.onopen = () => {
        const session = secret.config.session ?? secret.config;
        const name = String(personaName).replace(/[\r\n]/g, ' ').slice(0, 80);
        send({ type: 'session.update', session: { ...session,
          output_modalities: ['audio'], max_output_tokens: 128,
          instructions: `You are ${name}, a fictional audience member for presentation practice. `
            + 'Respond naturally to the latest spoken words in this conversation in one short sentence, '
            + 'at most twenty words. Ask a relevant follow-up if useful. Never recite a fixed template. '
            + 'Do not invent presentation claims or make personal attacks.',
          audio: { ...session.audio,
            input: { ...session.audio?.input, turn_detection: null },
            output: { ...session.audio?.output, voice: voiceId } },
        } });
      };
      ws.onmessage = ({ data: raw }) => {
        let data;
        try { data = JSON.parse(raw); } catch { return; }
        if (data.type === 'session.created' || data.type === 'session.updated') {
          clearTimeout(timeout); resolve();
        } else if (data.type === 'error') failed();
      };
    });
    ws.onopen = null; ws.onmessage = onMessage;
    ws.onerror = () => fail('Live conversation connection failed. Restart to reconnect.');
    ws.onclose = () => fail('Live conversation disconnected. Restart to reconnect.');
    gate = createUtteranceGate({ clock, pushToTalk, onCommit: commit,
      onLimit: () => onStatus('Question exceeded one minute and was discarded. Release and try a shorter question.'),
      onClear: () => send({ type: 'input_audio_buffer.clear' }),
      onAppend(bytes) {
        let raw = '';
        for (const byte of bytes) raw += String.fromCharCode(byte);
        send({ type: 'input_audio_buffer.append', audio: btoa(raw) });
      },
    });
    hardTimer = setTimeout(() => fail('Live conversation reached its ten-minute limit. Reconnect to continue.'), 600000);
    idleTimer = setInterval(() => {
      if (performance.now() - lastActivity >= 60000) {
        fail('Live conversation closed after one minute without speech. Reconnect to continue.');
      }
    }, 5000);
    window.addEventListener('pagehide', stop);
    onStatus('Live conversation connected. Microphone is off.');
    return {
      startListening, cancel, stop,
      beginTurn() { return !stopped && !paused && !activeTurn && (mic?.beginTurn() ?? false); },
      endTurn() { return mic?.endTurn() ?? false; },
      cancelTurn() { return mic?.cancelTurn() ?? false; },
      setPaused(value) {
        const next = Boolean(value);
        if (stopped || paused === next) return;
        paused = next;
        if (paused) cancel(); else { lastActivity = performance.now(); updateMic(); }
      },
      get speaking() { return speaking; },
      get active() { return !stopped; },
    };
  } catch {
    await stop();
    throw new Error('Could not connect live speech. Check the Boson connection and try again.');
  }
}
