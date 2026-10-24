import { createPlayer } from '/js/audio.js';
import { connectVoice } from '/js/voice.js';
import { connectConversation } from '/js/conversation.js';
const $ = (id) => document.getElementById(id);
const player = createPlayer();
let voice, conversation, session, startedAt = performance.now(), heldPointer = null;
const clock = () => Math.round(performance.now() - startedAt);
const status = (text) => {
  $('status').textContent = text;
  if ((voice || conversation) && /closed|disconnected|failed|timed out|limit/i.test(text)) {
    $('mic').disabled = false; voice?.trackRealtime(false);
  }
  if (/^Audio (disconnected|connection failed|time limit)/i.test(text)) conversation?.stop();
};
const log = (speaker, text) => {
  const p = document.createElement('p'); p.textContent = `${speaker}: ${text}`; $('log').append(p);
  $('log').scrollTop = $('log').scrollHeight;
};
function latency({ speech_to_playback_ms: ms }) {
  if (ms != null) $('latency').textContent = `Speech end → first received reply audio: ${ms} ms. Device output delay is additional. Mode: ${$('reply-mode').selectedOptions[0].textContent}.`;
}
async function json(url, init) {
  const response = await fetch(url, init);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status}).`);
  return data;
}
const post = (url, body) => json(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
async function speak(text = 'Welcome to PresAI. Please begin your presentation.') {
  $('speak').disabled = true; conversation?.setPaused(true);
  try {
    await player.resume();
    await post(`/api/sessions/${session}/voice/test`, { persona_id: $('persona').value, text });
    status('Test line finished.');
  } catch (error) { status(error.message); }
  finally { $('speak').disabled = false; conversation?.setPaused(false); }
}
$('connect').onclick = async () => {
  $('connect').disabled = true;
  try {
    await player.resume();
    const health = await json('/health');
    if (health.adapters.voice !== 'higgs') throw new Error('Live voice is disabled in the local setup.');
    const roster = await json('/api/presets');
    const preset = roster.presets.find((p) => p.id === 'startup_pitch');
    const personas = preset.personas.map((id) => roster.personas.find((p) => p.id === id)).slice(0, 3);
    const data = await post('/api/sessions', { config: { preset_id: preset.id, personas } });
    session = data.session_id;
    $('persona').replaceChildren(new Option('Moderator', 'moderator'));
    for (const persona of personas) $('persona').append(new Option(`${persona.name} · ${persona.role}`, persona.id));
    startedAt = performance.now();
    voice = await connectVoice({ sessionId: session, player, clock,
      pushToTalk: $('mode').value === 'push_to_talk',
      onLevel: (value) => { $('level').style.width = `${Math.min(100, value * 400)}%`; }, onStatus: status,
      onSpeaking: (active) => { status(active ? 'Audience is speaking. Microphone paused.' : 'Ready.'); },
      onLatency: latency,
      onSegment: async (segment) => {
        log('You', segment.text);
        if ($('reply-mode').value === 'fixed') await speak('I heard you. What evidence supports that claim?');
      },
    });
    $('mode').disabled = true; $('reply-mode').disabled = true;
    $('speak').disabled = false; $('mic').disabled = false; $('stop').disabled = false;
  } catch (error) { status(error.message); voice?.stop(); $('connect').disabled = false; }
};
$('speak').onclick = () => speak();
$('mic').onclick = async () => {
  $('mic').disabled = true;
  try {
    if ($('reply-mode').value === 'live') {
      if (!conversation?.active) {
        const id = $('persona').value;
        conversation = await connectConversation({ sessionId: session, player, clock,
          pushToTalk: $('mode').value === 'push_to_talk',
          voiceId: ({ moderator: 'eleanor', vc: 'marcus', student: 'chloe', professor: 'oliver' })[id] || 'default',
          personaName: $('persona').selectedOptions[0].textContent,
          onLevel: (value) => { $('level').style.width = `${Math.min(100, value * 400)}%`; },
          onStatus: status, onLatency: latency, onSegment: (segment) => log('You', segment.text),
          onAssistantText: (text, info) => { if (info.final) log('AI', text); },
          onSpeaking: (active) => { $('speak').disabled = active; },
        });
      }
      await conversation.startListening();
      voice.trackRealtime(true);
      $('persona').disabled = true;
    } else await voice.startListening();
    $('talk').disabled = $('mode').value !== 'push_to_talk';
    $('cancel-reply').disabled = false;
    status($('mode').value === 'push_to_talk'
      ? 'Microphone ready. Hold the button or Space; release only when your question is complete.'
      : 'Listening. Hands-free mode waits for 1.1 seconds of silence; hold-to-talk gives you control.');
  } catch (error) { status(error.message); $('mic').disabled = false; }
};
$('stop').onclick = () => {
  finishHeld(false);
  voice?.stop(); conversation?.stop(); $('stop').disabled = true; $('mic').disabled = true;
  $('speak').disabled = true; $('talk').disabled = true; $('cancel-reply').disabled = true;
  status('Audio stopped. Reload to start a new check.');
};
const capture = () => conversation?.active ? conversation : voice;
function finishHeld(submit) {
  if (heldPointer == null) return;
  const id = heldPointer; heldPointer = null;
  if (submit) capture()?.endTurn(); else capture()?.cancelTurn();
  $('talk').textContent = 'Hold to ask a question';
  if ($('talk').hasPointerCapture(id)) $('talk').releasePointerCapture(id);
}
$('talk').onpointerdown = (event) => {
  if (event.button !== 0 || heldPointer != null) return;
  event.preventDefault();
  if (!capture()?.beginTurn()) { status('Wait for the current reply, or press Stop reply first.'); return; }
  heldPointer = event.pointerId; $('talk').setPointerCapture(event.pointerId);
  $('talk').textContent = 'Listening — release when finished';
};
$('talk').onpointerup = (event) => { if (event.pointerId === heldPointer) finishHeld(true); };
$('talk').onpointercancel = () => finishHeld(false);
$('talk').onlostpointercapture = () => finishHeld(false);
$('cancel-reply').onclick = () => {
  finishHeld(false); capture()?.cancelTurn(); conversation?.cancel(); voice?.cancel();
  status('Reply stopped. Hold to ask a complete question again.');
};
$('mode').onchange = () => {
  $('turn-help').textContent = $('mode').value === 'push_to_talk'
    ? 'Hold the button or Space throughout your whole question, including pauses. Release only when finished. Losing focus discards an unfinished question.'
    : 'Hands-free mode submits after 1.1 seconds of silence. Choose hold-to-talk before connecting if you pause while thinking.';
};
window.addEventListener('blur', () => finishHeld(false));
window.addEventListener('pagehide', () => { finishHeld(false); conversation?.stop(); player.close(); });
