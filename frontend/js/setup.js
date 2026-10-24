// /setup: PDF drop, audience builder (P0-3b), Advanced drawer, Start.
// Owner: Person A. Wire names: spec/contracts.schema.json (SessionConfig).

import { createSession, getPresets, uploadSlides } from '/js/api.js';

const qs = new URLSearchParams(location.search);
const presetId = qs.get('preset') ?? 'startup_pitch';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const { presets, personas, curveballs } = await getPresets();
const byId = Object.fromEntries(personas.map((p) => [p.id, p]));
const preset = presets.find((p) => p.id === presetId) ?? null; // null → "custom"

$('title').textContent = preset ? preset.name : 'Custom audience';
if (preset) $('duration').value = Math.round(preset.duration_target_s / 60);

const state = {
  chosen: new Set(preset ? preset.personas : ['vc', 'student']), // 2..3 persona ids
  skepticism: {},
  deckId: null,
};

// ---- audience builder (P0-3b) -------------------------------------------------------
function renderSummary() {
  const custom = $('custom-persona').value.trim();
  $('audience-summary').innerHTML = [...state.chosen].map((id) => {
    const p = byId[id];
    return `<span class="rounded-full bg-slate-800 px-3 py-1">${esc(p.role)} <span class="text-slate-500">· ${esc(p.name)}</span></span>`;
  }).join('') + (custom ? `<span class="rounded-full border border-dashed border-cyan-700 px-3 py-1 text-cyan-300">Custom · fictional</span>` : '');
}

function renderRoster() {
  $('roster').innerHTML = personas.map((p) => `
    <label class="flex items-start gap-2 rounded-lg border p-2 text-sm ${state.chosen.has(p.id) ? 'border-cyan-500' : 'border-slate-800'}">
      <input type="checkbox" data-id="${p.id}" ${state.chosen.has(p.id) ? 'checked' : ''} class="mt-1" />
      <span class="flex-1">
        <span class="font-medium">${esc(p.role)}</span> <span class="text-slate-500">· ${esc(p.name)}</span>
        <span class="block text-xs text-slate-500">${esc(p.focus.join(' · '))}</span>
        <span class="mt-1 flex items-center gap-2 text-xs text-slate-400">skepticism
          <input type="range" min="0" max="1" step="0.05" value="${state.skepticism[p.id] ?? p.skepticism}" data-slider="${p.id}" class="w-24" />
        </span>
      </span>
    </label>`).join('');
  $('roster').querySelectorAll('input[type=checkbox]').forEach((cb) => { cb.onchange = () => {
    if (cb.checked) { if (state.chosen.size >= 3) { cb.checked = false; return; } state.chosen.add(cb.dataset.id); }
    else state.chosen.delete(cb.dataset.id);
    renderRoster(); renderSummary();
  }; });
  $('roster').querySelectorAll('input[type=range]').forEach((r) => { r.oninput = () => { state.skepticism[r.dataset.slider] = Number(r.value); }; });
}

$('customise').onclick = () => { $('builder').classList.toggle('hidden'); renderRoster(); };
$('custom-persona').oninput = renderSummary;
renderSummary();
if (!preset) { $('builder').classList.remove('hidden'); renderRoster(); }

// ---- curveball picker ------------------------------------------------------------------
const allowed = preset ? preset.curveballs_allowed : curveballs.map((c) => c.kind);
$('cb-choose').innerHTML = allowed.map((k) => `
  <label class="rounded-full border border-slate-700 px-3 py-1 text-xs">
    <input type="checkbox" value="${k}" checked class="mr-1" />${k.replace('_', ' ')}
  </label>`).join('');
$('cb-mode').onchange = () => $('cb-choose').classList.toggle('hidden', $('cb-mode').value !== 'choose');

// ---- slides ----------------------------------------------------------------------------
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

// ---- start -----------------------------------------------------------------------------
$('start').onclick = async () => {
  $('start').disabled = true;
  $('start-status').textContent = 'Creating room…';
  const custom = $('custom-persona').value.trim();
  let ids = [...state.chosen];
  if (custom && ids.length >= 3) ids = ids.slice(0, 2); // the custom persona takes the third seat
  const config = {
    preset_id: preset ? preset.id : 'custom',
    personas: ids.map((id) => ({ ...byId[id], skepticism: state.skepticism[id] ?? byId[id].skepticism })),
    difficulty: $('difficulty').value,
    interruption_frequency: $('frequency').value,
    curveballs: $('cb-mode').value === 'choose'
      ? { mode: 'choose', kinds: [...$('cb-choose').querySelectorAll('input:checked')].map((i) => i.value) }
      : { mode: $('cb-mode').value },
    duration_target_s: Number($('duration').value) * 60,
    qna_questions: Number($('qna').value),
    input_mode: $('input-mode').value,
    deck_id: state.deckId,
  };
  try {
    const { session_id } = await createSession(config, custom ? [custom] : []);
    location.href = `/room.html?session=${session_id}`;
  } catch (e) {
    $('start').disabled = false;
    $('start-status').textContent = `Could not create the room: ${e.message}`;
  }
};
