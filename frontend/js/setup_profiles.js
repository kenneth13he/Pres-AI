// Browser-local presentation preferences. Decks, credentials and microphone data are never saved.
const KEY = 'presai.profiles';
const clean = (value, limit) => typeof value === 'string' ? value.trim().slice(0, limit) : '';
export function loadSetupProfiles(storage) {
  try {
    const values = JSON.parse(storage?.getItem(KEY) ?? '[]');
    if (!Array.isArray(values)) return [];
    return values.filter((p) => p && typeof p === 'object' && /^[\w-]{1,80}$/.test(p.id)
      && Array.isArray(p.chosen)).slice(0, 12).map((p) => ({ ...p,
      name: clean(p.name ?? p.pname, 60) || 'My profile',
      presetId: clean(p.presetId ?? p.preset, 80) || 'startup_pitch',
      setting: ['video', 'classroom', 'boardroom', 'lecture', 'interview'].includes(p.setting)
        ? p.setting : 'video' }));
  } catch { return []; }
}
export function saveSetupProfiles(storage, profiles) {
  try {
    if (!storage) return false;
    storage.setItem(KEY, JSON.stringify(profiles.slice(0, 12))); return true;
  } catch { return false; }
}
export function captureSetupProfile(state, { id, name, setting }) {
  return { id, name: clean(name, 60) || state.preset?.name || 'My profile', setting,
    presetId: state.preset?.id ?? 'custom', chosen: [...state.chosen],
    skepticism: Object.fromEntries(state.skepticism), customDescription: state.customDescription,
    options: { ...state.options, duration_minutes: Number(state.options.duration_minutes),
      qna_questions: Number(state.options.qna_questions), input_mode: 'push_to_talk' },
    chosenCurveballs: [...state.chosenCurveballs] };
}
export function restoreSetupProfile(state, profile) {
  const chosen = [...new Set((Array.isArray(profile.chosen) ? profile.chosen : [])
    .filter((id) => state.roster.has(id)))];
  const custom = clean(profile.customDescription, 600), limit = custom ? 2 : 3;
  state.chosen = new Set(chosen.slice(0, limit));
  for (const id of state.roster.keys()) {
    if (state.chosen.size >= 2) break;
    state.chosen.add(id);
  }
  state.customDescription = custom;
  state.skepticism = new Map(Object.entries(profile.skepticism ?? {}).filter(([id, v]) =>
    state.roster.has(id) && typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1));
  const p = profile.options ?? {}, o = state.options;
  const enums = { difficulty: ['friendly', 'normal', 'brutal'],
    interruption_frequency: ['rare', 'normal', 'often'], curveball_mode: ['off', 'surprise', 'choose'] };
  for (const [key, values] of Object.entries(enums)) if (values.includes(p[key])) o[key] = p[key];
  for (const [key, low, high] of [['duration_minutes', 1, 20], ['qna_questions', 0, 3]]) {
    if (Number.isInteger(p[key]) && p[key] >= low && p[key] <= high) o[key] = p[key];
  }
  o.input_mode = 'push_to_talk';
  state.chosenCurveballs = new Set((Array.isArray(profile.chosenCurveballs)
    ? profile.chosenCurveballs : state.allowed).filter((kind) => state.allowed.includes(kind)));
  if (o.curveball_mode === 'choose' && !state.chosenCurveballs.size) o.curveball_mode = 'surprise';
}
