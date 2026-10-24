// /setup: PDF drop, audience builder (P0-3b), Advanced drawer, Start.
// Owner: Person A. Wire names: spec/contracts.schema.json (SessionConfig).

import { createSession, getPresets, uploadSlides } from '/js/api.js';

const qs = new URLSearchParams(location.search);
const presetId = qs.get('preset') ?? 'startup_pitch';
const $ = (id) => document.getElementById(id);

const { presets, personas, curveballs } = await getPresets();
const byId = Object.fromEntries(personas.map((p) => [p.id, p]));
const preset = presets.find((p) => p.id === presetId) ?? null; // null → "custom"

$('title').textContent = preset ? preset.name : 'Custom audience';

// State the Start button serialises into a SessionConfig.
const state = {
  chosen: new Set(preset ? preset.personas : ['vc', 'student']), // 2..3 persona ids
  skepticism: {},                                                  // id → 0..1 override
  deckId: null,
};

// TODO(A): renderSummary() — chips for chosen personas (+ "Custom · fictional" when the
//          textarea has text). Presets must work with zero clicks here.
// TODO(A): renderRoster() into #roster — checkbox per persona (max 3), skepticism slider,
//          focus line; #customise toggles #builder; custom preset opens it by default.
// TODO(A): curveball picker into #cb-choose from preset.curveballs_allowed (or all
//          `curveballs` for custom); shown only when #cb-mode == "choose".

$('pdf').onchange = async () => {
  const file = $('pdf').files[0];
  if (!file) return;
  $('pdf-status').textContent = 'Uploading…';
  try {
    const deck = await uploadSlides(file);
    state.deckId = deck.deck_id;
    $('pdf-status').textContent = `${deck.filename}: ${deck.page_count} slides ready.`;
  } catch (e) {
    $('pdf-status').textContent = `Upload failed (${e.message}). You can still present without slides.`;
  }
};

$('start').onclick = async () => {
  $('start-status').textContent = 'Creating room…';
  const config = {
    preset_id: preset ? preset.id : 'custom',
    personas: [...state.chosen].map((id) => ({ ...byId[id], skepticism: state.skepticism[id] ?? byId[id].skepticism })),
    difficulty: $('difficulty').value,
    interruption_frequency: $('frequency').value,
    curveballs: { mode: $('cb-mode').value }, // TODO(A): { mode: "choose", kinds: [...] }
    duration_target_s: Number($('duration').value) * 60,
    qna_questions: Number($('qna').value),
    input_mode: $('input-mode').value,
    deck_id: state.deckId,
  };
  const custom = $('custom-persona').value.trim();
  try {
    const { session_id } = await createSession(config, custom ? [custom] : []);
    location.href = `/room.html?session=${session_id}`;
  } catch (e) {
    $('start-status').textContent = `Could not create the room: ${e.message}`;
  }
};
