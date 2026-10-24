import { createSetupState, audienceSummary, validateSetup, buildSessionRequest } from './setup_model.js?v=adaptive-room-1';
import { restoreSetupProfile } from './setup_profiles.js?v=adaptive-room-1';

export function createSetupController({ data, presetId, view, uploadSlides, createSession, navigate }) {
  const state = createSetupState(data, presetId);
  let uploadVersion = 0;
  const render = () => view.render({ ...state, audience: audienceSummary(state),
    errors: validateSetup(state) });
  const change = (fn) => {
    if (state.submitting) return;
    state.status = ''; fn(); render();
  };
  const controller = {
    state,
    profile(value) { change(() => restoreSetupProfile(state, value)); },
    choosePersona(id, checked) {
      change(() => {
        if (!state.roster.has(id)) return;
        const limit = state.customDescription.trim() ? 2 : 3;
        if (checked && !state.chosen.has(id) && state.chosen.size >= limit) return;
        if (checked) state.chosen.add(id); else state.chosen.delete(id);
      });
    },
    custom(text) { change(() => { state.customDescription = String(text); }); },
    skepticism(id, value) {
      change(() => { if (state.roster.has(id)) state.skepticism.set(id, Number(value)); });
    },
    option(name, value) { change(() => { if (Object.hasOwn(state.options, name)) state.options[name] = value; }); },
    curveball(kind, checked) {
      change(() => {
        if (!state.allowed.includes(kind)) return;
        if (checked) state.chosenCurveballs.add(kind); else state.chosenCurveballs.delete(kind);
      });
    },
    async upload(file) {
      if (state.submitting) return;
      const version = ++uploadVersion;
      state.deckId = null; state.status = '';
      if (!file) {
        state.upload = { status: 'idle', filename: '', message: '' }; render(); return;
      }
      const filename = String(file.name ?? '');
      if (!filename.toLowerCase().endsWith('.pdf') || file.size > 50 * 1024 * 1024) {
        state.upload = { status: 'error', filename,
          message: 'Choose a PDF no larger than 50 MB.' }; render(); return;
      }
      state.upload = { status: 'uploading', filename, message: 'Reading your slides…' }; render();
      try {
        const deck = await uploadSlides(file);
        if (version !== uploadVersion) return;
        if (!deck?.deck_id || !Number.isInteger(deck.page_count) || deck.page_count < 1) {
          throw new Error('Incomplete deck.');
        }
        state.deckId = deck.deck_id;
        state.upload = { status: 'ready', filename,
          message: `${filename} · ${deck.page_count} slide${deck.page_count === 1 ? '' : 's'} ready` };
      } catch {
        if (version !== uploadVersion) return;
        state.deckId = null;
        state.upload = { status: 'error', filename,
          message: 'We could not read this PDF. Try another file or remove it below.' };
      }
      render();
    },
    async submit() {
      if (state.submitting) return;
      const errors = validateSetup(state);
      if (errors.length) { state.status = errors[0]; render(); return; }
      const request = buildSessionRequest(state);
      state.submitting = true; state.status = request.custom_personas.length
        ? 'Building your custom audience…' : 'Creating your room…'; render();
      try {
        const result = await createSession(request.config, request.custom_personas);
        if (!result?.session_id) throw new Error('Room ID missing.');
        navigate(`/room.html?session=${encodeURIComponent(result.session_id)}`);
      } catch {
        state.submitting = false;
        state.status = 'We could not create the room. Check your connection and try again.'; render();
      }
    },
  };
  view.bind(controller); render();
  return controller;
}
