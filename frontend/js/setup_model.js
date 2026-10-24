// Audience choices and the shared snake_case request, independent of the DOM/network.
export function createSetupState(data, presetId = 'startup_pitch') {
  const roster = new Map(data.personas.map((person) => [person.id, person]));
  if (roster.size < 2) throw new Error('At least two audience choices are needed.');
  const preset = data.presets.find((item) => item.id === presetId) ?? null;
  const defaults = preset?.personas ?? ['vc', 'student'];
  const chosen = defaults.filter((id) => roster.has(id)).slice(0, 3);
  for (const id of roster.keys()) {
    if (chosen.length >= 2) break;
    if (!chosen.includes(id)) chosen.push(id);
  }
  const catalogue = new Map(data.curveballs.map((item) => [item.kind, item]));
  const allowed = [...new Set(preset?.curveballs_allowed ?? catalogue.keys())]
    .filter((kind) => catalogue.has(kind));
  return {
    roster, preset, catalogue, allowed, chosen: new Set(chosen), skepticism: new Map(),
    customDescription: '', chosenCurveballs: new Set(allowed), deckId: null,
    options: { difficulty: preset?.default_difficulty ?? 'normal',
      interruption_frequency: 'normal', curveball_mode: 'surprise',
      duration_minutes: Math.max(1, Math.round((preset?.duration_target_s ?? 180) / 60)),
      qna_questions: 2, input_mode: 'push_to_talk' },
    upload: { status: 'idle', filename: '', message: '' }, submitting: false, status: '',
  };
}

export function selectedPersonas(state) {
  return [...state.chosen].map((id) => {
    const person = state.roster.get(id);
    return { ...person, focus: [...person.focus], plays: [...(person.plays ?? [])],
      skepticism: state.skepticism.get(id) ?? person.skepticism };
  });
}

export function audienceSummary(state) {
  const people = selectedPersonas(state);
  const custom = state.customDescription.trim();
  if (custom) people.push({ id: 'custom_1', name: 'Custom audience member',
    role: custom, custom: true, focus: [], plays: [], skepticism: 0.5 });
  return people;
}

export function validateSetup(state) {
  const errors = [];
  const custom = state.customDescription.trim();
  if (custom && state.chosen.size !== 2) {
    errors.push('Choose exactly two people from the roster to leave the third seat for your custom person.');
  } else if (!custom && (state.chosen.size < 2 || state.chosen.size > 3)) {
    errors.push('Choose two or three people for your audience.');
  }
  if (custom.length > 600) errors.push('Keep the custom description to 600 characters.');
  const o = state.options;
  if (!['friendly', 'normal', 'brutal'].includes(o.difficulty)) errors.push('Choose a difficulty.');
  if (!['rare', 'normal', 'often'].includes(o.interruption_frequency)) errors.push('Choose an interruption frequency.');
  if (!['push_to_talk', 'live'].includes(o.input_mode)) errors.push('Choose an input mode.');
  if (!Number.isInteger(Number(o.duration_minutes)) || o.duration_minutes < 1 || o.duration_minutes > 20) {
    errors.push('Choose a whole session length from 1 to 20 minutes.');
  }
  if (!Number.isInteger(Number(o.qna_questions)) || o.qna_questions < 0 || o.qna_questions > 3) {
    errors.push('Choose zero to three closing questions.');
  }
  if (!['off', 'surprise', 'choose'].includes(o.curveball_mode)) errors.push('Choose a curveball mode.');
  if (o.curveball_mode === 'choose' && !state.chosenCurveballs.size) {
    errors.push('Pick at least one curveball, or switch curveballs Off.');
  }
  if ([...state.chosenCurveballs].some((kind) => !state.allowed.includes(kind))) {
    errors.push('Choose curveballs available for this preset.');
  }
  if (selectedPersonas(state).some((p) => !Number.isFinite(p.skepticism)
    || p.skepticism < 0 || p.skepticism > 1)) errors.push('Skepticism must be between 0% and 100%.');
  if (state.upload.status === 'uploading') errors.push('Wait for your slides to finish uploading.');
  if (state.upload.status === 'error') errors.push('Choose another PDF or remove this file to continue without slides.');
  return errors;
}

export function buildSessionRequest(state) {
  const errors = validateSetup(state);
  if (errors.length) throw new Error(errors[0]);
  const o = state.options, custom = state.customDescription.trim();
  return {
    config: { preset_id: state.preset?.id ?? 'custom', personas: selectedPersonas(state),
      difficulty: o.difficulty, interruption_frequency: o.interruption_frequency,
      curveballs: { mode: o.curveball_mode,
        kinds: o.curveball_mode === 'choose' ? [...state.chosenCurveballs] : [] },
      duration_target_s: Number(o.duration_minutes) * 60,
      qna_questions: Number(o.qna_questions), input_mode: o.input_mode, deck_id: state.deckId },
    custom_personas: custom ? [custom] : [],
  };
}
