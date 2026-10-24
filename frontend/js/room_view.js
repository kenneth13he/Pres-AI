import { assignPortraits } from './portraits.js';
import { layout, loadSessionMeta, PRESET_SETTING, settingById } from './rooms.js';

// Room rendering and accessible controls. All audience/transcript text is plain text.
export function createRoomView(doc = document, win = doc.defaultView) {
  const $ = (id) => doc.getElementById(id);
  const tiles = new Map(), bubbles = new Map();
  let session, phase = 'setup', heldPointer = null, handlers, lastControls = {}, activeSpeaker = null;
  const text = (id, value) => { if ($(id)) $(id).textContent = value; };
  function notice(value) { text('room-notice', value || ''); $('room-notice').hidden = !value; }
  function renderRoomState() {
    let message;
    if (phase === 'paused') message = 'Paused — timer frozen. Press Resume to continue.';
    else if (phase === 'report') message = 'Session finished. Open your report.';
    else if (phase === 'setup') message = 'Microphone is off. Start when ready.';
    else if (lastControls.pending) message = 'Updating the room…';
    else if (activeSpeaker) {
      const name = session?.config?.personas?.find((person) => person.id === activeSpeaker)?.name
        || (activeSpeaker === 'moderator' ? 'the moderator' : activeSpeaker);
      message = `Audience turn — listen to ${name}.`;
    } else message = ({ presenting: 'Your turn to present.', recovering: 'Your turn to present.',
      answering: 'Your turn to answer the audience.', qna: 'Q&A — waiting for the next audience question.',
      interruption: 'Waiting for the audience’s question.', curveball: 'A curveball is in progress. Follow the room’s prompt.' })[phase] || 'The room is ready.';
    text('room-state', message);
  }
  function finishHeld(submit) {
    if (heldPointer == null) return;
    const pointer = heldPointer; heldPointer = null;
    if (submit) handlers.endTurn(); else handlers.cancelTurn();
    text('btn-talk', 'Hold to talk');
    if ($('btn-talk').hasPointerCapture(pointer)) $('btn-talk').releasePointerCapture(pointer);
  }
  const cancelHeld = () => finishHeld(false);
  function controls(next = {}) {
    Object.assign(lastControls, next);
    const c = lastControls, ended = phase === 'report', inQna = phase === 'qna' || Boolean(c.inQna);
    $('btn-start').disabled = !c.canPresent || c.connecting || (c.listening && c.started) || ended;
    text('btn-start', c.connecting ? 'Connecting audio…' : c.started ? 'Reconnect microphone' : 'Start presenting');
    for (const id of ['btn-pause', 'btn-skip']) $(id).disabled = !c.started || ended || c.pending;
    $('prev').disabled = $('next').disabled = ended;
    const canEnd = c.started && !ended && (!c.pending || c.canEndWhileConnecting);
    $('btn-end').disabled = !canEnd || inQna;
    text('btn-end', ended ? 'Session finished' : inQna ? 'Q&A in progress' : 'End → Q&A');
    $('btn-finish-session').hidden = !inQna || ended;
    $('btn-finish-session').disabled = !canEnd;
    $('qna-hint').hidden = !inQna || ended;
    text('qna-hint', `${phase === 'paused' ? 'Q&A is paused. Resume when ready. ' : ''}Answer with Hold to talk. The report becomes ready automatically when Q&A is complete.`);
    $('btn-talk').hidden = !c.ptt;
    $('ptt-hint').hidden = !c.ptt;
    $('btn-talk').disabled = !c.listening || !c.started || !c.canTalk || c.busy || c.pending || ended || phase === 'paused';
    $('btn-stop-reply').disabled = !c.started || ended || !c.busy;
    text('audio-mode', c.ptt ? 'Hold to talk' : 'Hands-free');
    text('ptt-hint', 'Hold the button or Space, including thinking pauses. Release when finished.');
    if ($('btn-talk').disabled) finishHeld(false);
    renderRoomState();
  }
  const view = {
    bind(value) {
      handlers = value;
      const bind = (id, action) => { const button = $(id); button.onclick = () => {
        if (button.disabled || button.hidden) return Promise.resolve();
        return Promise.resolve(action()).catch((e) => view.error(e.message));
      }; };
      for (const [id, name] of Object.entries({ 'btn-start': 'start', 'btn-pause': 'pause',
        'btn-skip': 'skip', 'btn-end': 'end', 'btn-finish-session': 'end',
        'btn-restore': 'restore', prev: 'previous',
        next: 'next', 'btn-stop-reply': 'stopReply' })) bind(id, handlers[name]);
      const button = $('btn-talk');
      button.onpointerdown = (event) => {
        if (event.button !== 0 || button.disabled || heldPointer != null) return;
        event.preventDefault();
        if (!handlers.beginTurn()) return;
        heldPointer = event.pointerId; button.setPointerCapture(event.pointerId);
        button.textContent = 'Listening — release when finished';
      };
      button.onpointerup = (event) => { if (event.pointerId === heldPointer) finishHeld(true); };
      button.onpointercancel = button.onlostpointercapture = () => finishHeld(false);
      win?.addEventListener('blur', cancelHeld);
    },
    configure(value) {
      session = value; notice(''); text('preset-name', value.preset?.name || 'Presentation room');
      const peopleCount = value.config?.personas?.length || 0;
      const setting = settingById(loadSessionMeta(value.session_id)?.setting
        || PRESET_SETTING[value.config?.preset_id] || 'video');
      const arrangement = layout(setting.id, Math.max(1, peopleCount));
      text('guest-count', `${peopleCount} ${peopleCount === 1 ? 'guest' : 'guests'}`);
      text('room-setting', setting.name); $('stage').style.background = arrangement.bg;
      const position = (node, box) => {
        Object.assign(node.style, { left: `${box.x}%`, top: `${box.y}%`,
          width: `${box.w}%`, height: `${box.h}%` });
      };
      position($('slide-viewer'), arrangement.slide); $('stage-decor').replaceChildren();
      for (const decoration of arrangement.decor) {
        const node = doc.createElement('div'); position(node, decoration);
        node.style.borderRadius = decoration.r; node.style.background = decoration.c;
        $('stage-decor').append(node);
      }
      activeSpeaker = null; tiles.clear(); bubbles.clear(); $('tiles').replaceChildren(); $('host').replaceChildren();
      const portraits = assignPortraits(value.config?.personas || []);
      const people = [{ id: 'moderator', name: 'Moderator', role: 'Guides the room' }, ...(value.config?.personas || [])];
      const element = (tag, className, content) => {
        const node = doc.createElement(tag); node.className = className;
        if (content != null) node.textContent = content;
        return node;
      };
      for (const [index, person] of people.entries()) {
        const host = person.id === 'moderator', face = portraits.get(person.id);
        const tile = element('article', host ? 'seat tile host-seat' : 'seat tile');
        tile.dataset.persona = person.id;
        if (!host) position(tile, arrangement.seats[index - 1]);
        const slot = element('div', 'speech-slot'), bubble = element('div', 'speech-bubble');
        const tag = element('small', 'bubble-tag'), line = element('p', 'bubble-text');
        bubble.hidden = true; tag.hidden = true; bubble.append(tag, line); slot.append(bubble);
        const portrait = element('div', 'portrait');
        const initials = String(person.name || '?').split(/\s+/).filter(Boolean)
          .slice(0, 2).map((word) => word[0]).join('').toUpperCase();
        const fallback = element('div', 'portrait-fallback', initials);
        fallback.hidden = Boolean(face?.src); portrait.append(fallback);
        if (face?.src) {
          const fill = element('img', 'portrait-fill');
          fill.alt = ''; fill.setAttribute('aria-hidden', 'true'); fill.decoding = 'async';
          const image = element('img', 'portrait-image');
          image.alt = `${person.name} · fictional ${host ? 'moderator' : 'audience member'}`;
          image.decoding = 'async'; tile.dataset.character = face.character;
          image.onerror = fill.onerror = () => {
            image.hidden = fill.hidden = true; fallback.hidden = false;
            tile.classList.add('portrait-unavailable');
          };
          // Both layers use the same trusted local cast image, never API-provided URLs.
          fill.src = image.src = face.src; portrait.append(fill, image);
        }
        const waves = element('div', 'speaking-waves');
        waves.setAttribute('aria-hidden', 'true');
        for (let i = 0; i < 3; i++) waves.append(element('i', ''));
        portrait.append(waves);
        const nameplate = element('div', 'seat-label');
        nameplate.append(element('strong', 'seat-name', person.name),
          element('p', 'seat-role', person.role), element('small', 'fiction-label', host
            ? 'Moderator voice' : person.custom ? 'Custom · fictional' : 'Fictional audience member'));
        if (host) tile.append(portrait, nameplate, slot); else tile.append(slot, portrait, nameplate);
        $(host ? 'host' : 'tiles').append(tile);
        tiles.set(person.id, tile); bubbles.set(person.id, { bubble, tag, line });
      }
    },
    phase(value) {
      phase = value; text('phase', value === 'qna' ? 'Q&A' : value);
      text('btn-pause', value === 'paused' ? 'Resume' : 'Pause');
      doc.body.classList.toggle('room-paused', value === 'paused');
      $('phase').classList.toggle('hot', ['curveball', 'recovering'].includes(value));
      $('phase').classList.toggle('mint', ['presenting', 'answering', 'interruption', 'qna', 'report'].includes(value)); controls();
    },
    controls, notice,
    connection: (value) => text('conn', value),
    audio: (value) => text('audio-status', value),
    error(value) { text('room-error', value || ''); $('room-error').hidden = !value; },
    meter(value) { $('mic-level').style.width = `${Math.min(100, Math.max(0, value) * 400)}%`; },
    speaking(id) {
      activeSpeaker = id || null;
      for (const [key, tile] of tiles) {
        tile.classList.toggle('speaking', key === id);
        const entry = bubbles.get(key);
        entry.bubble.hidden = key !== id || !entry.line.textContent;
      }
      renderRoomState();
    },
    caption(speaker, value, tag) {
      if (!value) return;
      const person = session?.config?.personas?.find((p) => p.id === speaker);
      const name = person?.name || (speaker === 'presenter' || speaker === 'you' ? 'You'
        : speaker === 'moderator' ? 'Moderator' : speaker || 'Moderator');
      const row = doc.createElement('div'); row.className = `caption ${speaker === 'presenter' || speaker === 'you' ? 'presenter' : speaker === 'moderator' ? 'moderator' : 'audience'}`;
      row.textContent = `${name}: ${value}${tag ? ` [${tag}]` : ''}`;
      $('captions').append(row); $('captions').scrollTop = $('captions').scrollHeight;
      const entry = bubbles.get(speaker);
      if (entry) {
        for (const other of bubbles.values()) other.bubble.hidden = true;
        entry.line.textContent = value; entry.tag.textContent = String(tag || '').replace(/_/g, ' ');
        entry.tag.hidden = !tag; entry.bubble.hidden = speaker !== activeSpeaker;
      }
    },
    slide(number) {
      const slide = session?.deck?.slides?.find((s) => s.number === number);
      text('slide-no', `Slide ${number}${session?.deck ? ` / ${session.deck.page_count}` : ''}`);
      const image = $('slide-img'), fallback = $('slide-text');
      image.hidden = !slide?.image_url; image.alt = slide ? `Slide ${number}` : '';
      image.onerror = () => { image.hidden = true; fallback.classList.remove('hidden'); };
      if (slide?.image_url) image.src = slide.image_url; else image.removeAttribute('src');
      fallback.textContent = slide?.text || 'Your audience is listening. Present with or without slides.';
      fallback.classList.toggle('hidden', Boolean(slide?.image_url));
    },
    curveball(value) {
      const effect = value?.ui_effect;
      $('slide-viewer').classList.toggle('black', effect === 'slides_black');
      $('slide-viewer').classList.toggle('dim', effect === 'slides_dim');
      $('btn-restore').classList.toggle('hidden', !['slides_black', 'slides_dim'].includes(effect));
      text('overlay-title', effect === 'slides_dim' ? 'Keep it short' : 'Projector disconnected');
      text('overlay-sub', value?.line || 'Keep going. You can restore the slides at any time.');
      for (const [id, tile] of tiles) {
        tile.classList.toggle('flash', effect === 'tile_flash' && id === value.persona_id);
        tile.classList.toggle('blank', effect === 'tiles_blank');
      }
    },
    timer({ elapsed_ms, remaining_ms, paused }) {
      const ms = remaining_ms == null ? elapsed_ms : remaining_ms;
      const seconds = Math.max(0, remaining_ms == null ? Math.floor(ms / 1000) : Math.ceil(ms / 1000));
      text('timer', `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`);
      $('timer').classList.toggle('urgent', remaining_ms != null);
      $('timer').classList.toggle('paused', Boolean(paused));
    },
    ended(url) {
      text('audio-status', 'Session finished. Microphone and audio stopped.');
      $('report-ready').hidden = false; $('report-link').href = url;
    },
    dispose() {
      finishHeld(false); $('prev').disabled = $('next').disabled = true;
      win?.removeEventListener('blur', cancelHeld);
    },
  };
  return view;
}
