// /setup: five-step wizard (Profile → Slides → Room → Audience → Curveballs) with a live room preview.
// Owner: Person A. Design: docs/design/Pres AI App.dc.html. Wire names: spec/contracts.schema.json.
//
// Only SessionConfig fields reach the backend. Profile details (role, goal, level, tone), the room
// setting, presentation context and guest photos stay in this browser (localStorage) until the
// contract grows fields for them.

import { createSession, getPresets, isMock, uploadSlides } from '/js/api.js';
import {
  KINDS, MAX_GUESTS, MIN_GUESTS, MINT, PRESET_SETTING, SETTINGS, cq, esc, layout, rect,
  saveSessionMeta, settingById, shapesHtml, thumbShapes, tileBg,
} from '/js/rooms.js';

const $ = (id) => document.getElementById(id);
const qs = new URLSearchParams(location.search);
const { presets, personas: ROSTER } = await getPresets();
const BY = Object.fromEntries(ROSTER.map((p) => [p.id, p]));

const LS_KEY = 'presai.profiles', LS_ACTIVE = 'presai.activeProfile';
const STEPS = ['Profile', 'Slides', 'Room', 'Audience', 'Curveballs'];
const GOALS = ['Pitch an idea', 'Teach a class', 'Defend research', 'Job interview', 'Team update', 'Conference talk'];
const VOICES = [['chloe', 'Friendly, clear'], ['eleanor', 'Calm, professional'], ['jake', 'Energetic, dramatic'], ['marcus', 'Confident, professorial'], ['nora', 'Calm, narrative'], ['oliver', 'Thoughtful, reflective']];
const DEFAULT_ME = { pname: '', role: '', goal: 'Pitch an idea', level: 'Some practice', tone: 'Balanced' };
const DEFAULT_ROOM = { setting: 'video', chosen: ['vc', 'student', 'professor'], skep: {}, input: 'live', preset: 'startup_pitch', customs: [] };
const PROFILE_KEYS = ['pname', 'role', 'goal', 'level', 'tone', 'setting', 'chosen', 'skep', 'input', 'customs'];
const BLANK_CG = { id: null, name: '', role: '', focus: '', img: '', imgErr: '', photoConsent: false, vmode: 'preset', preset: 'marcus', voiceId: '', clipName: '', clipErr: '', refText: '', consent: false };
const DIFFS = [['friendly', 'Friendly', 'No curveballs', 0], ['normal', 'Normal', '1 curveball', 1], ['brutal', 'Brutal', '2 curveballs', 2]];

const loadProfiles = () => { try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch { return []; } };
const persist = (profiles) => { try { localStorage.setItem(LS_KEY, JSON.stringify(profiles)); } catch { /* quota or private mode */ } };
const setActive = (id) => { try { id ? localStorage.setItem(LS_ACTIVE, id) : localStorage.removeItem(LS_ACTIVE); } catch { /* ignore */ } };

const S = {
  step: 0, profiles: loadProfiles(), profileId: null, ...DEFAULT_ME, ...DEFAULT_ROOM,
  deck: null, drag: false, uploading: false, deckErr: null, link: '', ctx: '', ctxFiles: [],
  cg: null, difficulty: 'normal', cbMode: 'surprise', kinds: ['time_crunch', 'slides_down', 'heckler'],
  freq: 'normal', length: 3, qna: 2, starting: false, startErr: null,
};
let snapStr = null;

// ---- people ---------------------------------------------------------------------------------
const cgValid = (c) => !!(c && c.name.trim() && c.img && c.photoConsent && (c.vmode === 'preset' ? c.preset : c.vmode === 'id' ? c.voiceId.trim() : c.clipName && c.consent));
const voiceLabel = (c) => c.vmode === 'preset' ? `voice · ${c.preset}` : c.vmode === 'id' ? `voice · ${c.voiceId}` : 'voice · cloned';
function person(id) {
  if (BY[id]) return { ...BY[id], sk: Math.round(BY[id].skepticism * 100), img: null, idx: ROSTER.indexOf(BY[id]) };
  const c = S.customs.find((x) => x.id === id);
  return c ? { id: c.id, name: c.name, role: c.role || 'Custom guest', sk: 50, img: c.img, custom: true, idx: 0 } : null;
}
const people = () => S.chosen.map(person).filter(Boolean);
const clampChosen = (chosen) => {
  const c = chosen.filter((id) => person(id)).slice(0, MAX_GUESTS);
  for (const p of ROSTER) { if (c.length >= MIN_GUESTS) break; if (!c.includes(p.id)) c.push(p.id); }
  return c;
};

// ---- profiles -------------------------------------------------------------------------------
const snap = () => Object.fromEntries(PROFILE_KEYS.map((k) => [k, S[k]]));
function loadProfile(p) {
  snapStr = null;
  Object.assign(S, { profileId: p.id, ...DEFAULT_ME, ...DEFAULT_ROOM, ...p, preset: null });
  S.chosen = clampChosen(S.chosen);
  setActive(p.id);
}
function createProfile() {
  const id = `p${Date.now()}`;
  const rec = { id, ...snap(), pname: S.pname.trim() || S.role.trim() || `Profile ${S.profiles.length + 1}` };
  S.profiles = S.profiles.concat(rec); persist(S.profiles); setActive(id);
  Object.assign(S, { profileId: id, pname: rec.pname });
}
function autosave() {
  if (!S.profileId || S.profileId === 'new') { snapStr = null; return; }
  const str = JSON.stringify(snap());
  if (snapStr === str) return;
  const first = snapStr == null; snapStr = str;
  if (!first) { S.profiles = S.profiles.map((p) => (p.id === S.profileId ? { ...p, ...JSON.parse(str) } : p)); persist(S.profiles); }
}
function goStep(i) {
  if (S.step === 0 && S.profileId === 'new') createProfile();
  S.step = i; render(); window.scrollTo({ top: 0 });
}

// ---- small renderers ------------------------------------------------------------------------
const seg = (act, list, cur, cls = '') => `<div class="seg ${cls}">${list.map(([v, label]) => `<button data-act="${act}" data-arg="${v}" class="${v === cur ? 'on' : ''}">${label}</button>`).join('')}</div>`;
const stepper = (act, val, color = '') => `<div style="display:flex;align-items:center;gap:6px"><button class="step-btn" data-act="${act}" data-arg="-1">−</button><div class="step-val" style="${color ? `color:${color}` : ''}">${val}</div><button class="step-btn" data-act="${act}" data-arg="1">+</button></div>`;
const saveNote = () => {
  const saved = S.profileId && S.profileId !== 'new';
  return `<div class="save-note" style="margin-top:14px"><span class="dot ${saved ? 'mint' : ''}"></span>${saved ? `Saved to ${esc(S.pname)}` : 'Default profile · applies to this session only'}</div>`;
};
const field = (label, model, val, ph, extra = '') => `<label class="field"><span>${label}</span><input class="input" data-model="${model}" value="${esc(val)}" placeholder="${esc(ph)}" ${extra}></label>`;

function stepProfile() {
  const cards = S.profiles.map((p, i) => {
    const cnt = (p.chosen || []).length;
    return `<button data-act="pick-profile" data-arg="${esc(p.id)}" class="pick ${p.id === S.profileId ? 'on' : ''}" style="padding:16px;border-radius:14px;display:flex;flex-direction:column;gap:10px">
      <span style="width:34px;height:34px;border-radius:10px;background:oklch(0.82 0.12 ${(i * 67 + 150) % 360});display:grid;place-items:center;font-weight:800;font-size:15px;color:var(--bg)">${esc((p.pname || '?').trim().charAt(0).toUpperCase())}</span>
      <span style="display:flex;flex-direction:column;gap:3px"><span style="font-size:16px;font-weight:700">${esc(p.pname)}</span><span style="font-size:13px;line-height:1.4;color:var(--muted)">${esc(p.role || p.goal)} · ${settingById(p.setting).name} · ${cnt} ${cnt === 1 ? 'guest' : 'guests'}</span></span></button>`;
  }).join('');
  const isNew = S.profileId === 'new';
  const form = S.profileId === null ? '' : `
    <div class="panel" style="margin-top:16px;gap:22px;padding:24px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px">
        <span style="font-size:13px;color:var(--muted)">${isNew ? 'New profile · saved when you continue' : 'Changes save automatically'}</span>
        ${isNew ? '' : '<button class="btn-text danger" data-act="delete-profile">Delete profile</button>'}
      </div>
      ${field('Profile name', 'pname', S.pname, 'e.g. Kenneth · Startup pitches')}
      ${field('Role or occupation', 'role', S.role, 'e.g. Final-year CS student')}
      <div class="field"><span>Presentation goal</span><div style="display:flex;flex-wrap:wrap;gap:8px">${GOALS.map((g) => `<button class="pill ${g === S.goal ? 'on' : ''}" data-act="goal" data-arg="${g}">${g}</button>`).join('')}</div></div>
      <div class="field"><span>Experience level</span>${seg('level', [['First time', 'First time'], ['Some practice', 'Some practice'], ['Seasoned', 'Seasoned']], S.level)}</div>
      <div class="field"><span>Feedback tone</span>${seg('tone', [['Encouraging', 'Encouraging'], ['Balanced', 'Balanced'], ['Blunt', 'Blunt']], S.tone)}</div>
    </div>`;
  return `<h1 class="title">Choose a profile</h1>
    <p class="lede">A profile keeps your details, room and audience, so you can reuse them with any deck.</p>
    <div class="grid-cards" style="margin-top:28px">${cards}
      <button data-act="new-profile" class="pick ${isNew ? 'on' : ''}" style="padding:16px;border-radius:14px;border-style:dashed;${isNew ? '' : 'border-color:#3a4043;background:transparent'};display:flex;flex-direction:column;gap:10px">
        <span style="width:34px;height:34px;border-radius:10px;border:1px dashed #3a4043;display:grid;place-items:center;font-size:18px;color:var(--muted)">+</span>
        <span style="display:flex;flex-direction:column;gap:3px"><span style="font-size:16px;font-weight:700">New profile</span><span style="font-size:13px;line-height:1.4;color:var(--muted)">Saved for future sessions</span></span>
      </button>
    </div>${form}`;
}

function stepSlides() {
  const d = S.deck;
  const icon = d ? 'PDF' : 'DECK';
  const thumbs = d ? Array.from({ length: Math.min(12, d.page_count) }, (_, i) => {
    const img = d.slides?.[i]?.image_url;
    return `<div style="aspect-ratio:16/9;border-radius:6px;background:var(--raised) ${img ? `url('${esc(img)}') center / cover` : ''};border:1px solid #262a2d;display:grid;place-items:center;font:400 10px var(--mono);color:var(--faint)">${img ? '' : i + 1}</div>`;
  }).join('') : '';
  return `<h1 class="title">Your slides</h1>
    <p class="lede">Optional. Upload your deck and questions point at what's on screen. Without a deck, the room listens only.</p>
    <div id="drop" class="drop ${S.drag ? 'drag' : ''}" data-act="pick-deck">
      <div style="width:48px;height:48px;margin:0 auto;border-radius:14px;background:var(--raised);display:grid;place-items:center;font:500 12px var(--mono);color:${d ? MINT : 'var(--muted)'}">${icon}</div>
      <div style="margin-top:16px;font-size:18px;font-weight:700">${S.uploading ? 'Uploading…' : d ? 'Replace deck' : 'Drop your slides here'}</div>
      <div style="margin-top:6px;font-size:14px;color:${S.deckErr ? 'var(--coral)' : 'var(--muted)'}">${esc(S.deckErr || (S.uploading ? 'Reading your slides' : 'or click to browse'))}</div>
      <div style="margin-top:16px;display:flex;flex-wrap:wrap;justify-content:center;gap:6px"><span class="chip">PDF</span></div>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input class="input" data-model="link" value="${esc(S.link)}" placeholder="Or paste a Google Slides, Canva or OneDrive link" style="flex:1;min-width:240px;width:auto">
      <button data-act="import-link" class="btn-sq" style="background:var(--surface);color:var(--muted);font-weight:700">Import</button>
    </div>
    ${d ? `<div style="margin-top:16px;padding:16px;border-radius:16px;border:1px solid var(--border);background:var(--surface)">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
        <div style="font-size:15px;font-weight:600">${esc(d.filename)} <span style="color:var(--muted);font-weight:500">· ${d.page_count} slides ready</span></div>
        <button class="btn-text" style="font-size:14px" data-act="remove-deck">Remove</button>
      </div>
      <div style="margin-top:14px;display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px">${thumbs}</div></div>`
    : `<div style="margin-top:16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <button data-act="sample" class="pill" style="background:transparent;border-color:var(--border-input)">Use the sample deck</button>
      <span style="font-size:14px;color:var(--faint)">or just press Continue to present without slides.</span></div>`}
    <div class="panel" style="margin-top:28px;gap:12px">
      <div><div class="panel-title">Presentation context</div><div class="hint">Optional. Background the audience should know: the occasion, your speaker notes, what's at stake.</div></div>
      <textarea class="input" data-model="ctx" rows="5" placeholder="e.g. Seed pitch to a campus-focused fund. We're asking for $500k. Pilots ran at two universities this spring; the second one is still ongoing.">${esc(S.ctx)}</textarea>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <button data-act="attach" style="padding:8px 14px;border-radius:999px;border:1px dashed #3a4043;background:transparent;font-size:13px;font-weight:600;cursor:pointer">Attach file</button>
        ${S.ctxFiles.map((n, i) => `<span style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:8px;background:var(--raised);font:400 12px var(--mono);color:#c5cac9">${esc(n)}<button data-act="unattach" data-arg="${i}" class="btn-text" style="font-size:14px;color:var(--faint)">×</button></span>`).join('')}
        <span style="font-size:12px;color:var(--faint)">.txt .md .pdf .docx · speaker notes, script, brief</span>
      </div>
    </div>`;
}

function stepRoom() {
  const n = people().length;
  return `<h1 class="title">Set the room</h1>
    <p class="lede">Pick where you're presenting and how many people are in it.</p>${saveNote()}
    <div class="grid-cards" style="margin-top:28px">${SETTINGS.map((r) => `
      <button data-act="setting" data-arg="${r.id}" class="pick ${r.id === S.setting ? 'on' : ''}" style="padding:12px;border-radius:14px">
        <div style="position:relative;aspect-ratio:16/9;border-radius:8px;background:var(--bg);overflow:hidden">${shapesHtml(thumbShapes(r.id))}</div>
        <div style="margin-top:10px;font-size:15px;font-weight:700">${r.name}</div><div style="margin-top:2px;font-size:13px;color:var(--muted)">${r.sub}</div>
      </button>`).join('')}</div>
    <div class="panel" style="margin-top:22px;gap:20px">
      <div class="row"><div><div class="panel-title">Guests</div><div class="hint">${MIN_GUESTS} to ${MAX_GUESTS} people in the room</div></div>${stepper('guests', n)}</div>
      <input type="range" min="${MIN_GUESTS}" max="${MAX_GUESTS}" value="${n}" data-range="guests">
      <div class="divider"></div>
      <div class="row"><div><div class="panel-title">Microphone</div><div class="hint">We ask for access when the room opens</div></div>${seg('input', [['live', 'Live mic'], ['push_to_talk', 'Push to talk']], S.input, 'fit')}</div>
    </div>`;
}

function cgPanel() {
  const c = S.cg;
  const voiceBody = c.vmode === 'preset'
    ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px">${VOICES.map(([id, style]) => `<button data-act="cg-voice" data-arg="${id}" class="pick ${c.preset === id ? 'on' : ''}" style="padding:11px 13px;border-radius:11px;display:flex;flex-direction:column;gap:3px"><span style="font:500 14px var(--mono)">${id}</span><span style="font-size:12px;color:var(--muted)">${style}</span></button>`).join('')}</div>`
    : c.vmode === 'id'
      ? `<label class="field"><span>Voice ID</span><input class="input mono" data-cg="voiceId" value="${esc(c.voiceId)}" placeholder="voice_abc123…" style="font:400 14px var(--mono)"><span style="font-size:12px;color:var(--faint);font-weight:400">A custom voice saved in your Boson account.</span></label>`
      : `<div style="display:flex;flex-direction:column;gap:12px">
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><button data-act="pick-clip" class="btn-sq" style="background:var(--bg);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.clipName || 'Upload voice clip')}</button><span style="font-size:12px;color:var(--faint)">5–30 seconds of clean speech, no music. WAV, MP3, Opus, PCM or FLAC.</span></div>
          <span class="err">${esc(c.clipErr)}</span>
          <label class="field"><span>Transcript of the clip <span style="font-weight:500;color:var(--faint)">· recommended</span></span><textarea class="input" data-cg="refText" rows="3" placeholder="Type exactly what's said in the clip, filler words included.">${esc(c.refText)}</textarea></label>
          <button data-act="cg-consent" style="align-self:flex-start;display:flex;align-items:center;gap:10px;padding:0;border:0;background:none;font-size:14px;cursor:pointer;text-align:left"><span class="tick ${c.consent ? 'on' : ''}">${c.consent ? '✓' : ''}</span>I own the right to use this voice.</button>
          <span style="font-size:12px;color:var(--faint)">Cloning isn't connected to the backend yet; until it is, this guest speaks in the default voice.</span>
        </div>`;
  return `<div class="panel" style="margin-top:12px;border-color:oklch(0.82 0.15 150 / .45);gap:22px">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px">
      <div><div style="font-size:18px;font-weight:800;letter-spacing:-0.01em">${c.id ? 'Edit custom guest' : 'New custom guest'}</div>
      <div style="margin-top:4px;font-size:13px;line-height:1.5;color:var(--muted);max-width:560px">Powered by Boson AI. Higgs Avatar turns the photo into a talking face; Higgs TTS 3 gives them a voice.</div></div>
      <button data-act="cg-close" style="flex:none;width:34px;height:34px;border-radius:9px;border:1px solid var(--border-input);background:var(--bg);color:var(--muted);font-size:18px;cursor:pointer">×</button>
    </div>
    <div style="display:flex;flex-wrap:wrap;gap:22px">
      <div style="flex:none;width:168px;display:flex;flex-direction:column;gap:8px">
        <span class="kicker">Portrait · Higgs Avatar</span>
        <div id="portrait" class="portrait" data-act="pick-portrait" style="${c.img ? 'border-color:transparent' : ''}">
          ${c.img ? `<div style="position:absolute;inset:0;background:url('${c.img}') center / cover no-repeat"></div><span style="position:absolute;left:8px;bottom:8px;padding:4px 9px;border-radius:999px;background:rgba(12,13,15,.8);font-size:12px;font-weight:600">Replace</span>`
          : `<div style="display:flex;flex-direction:column;align-items:center;gap:8px;padding:0 14px;text-align:center"><span style="width:40px;height:40px;border-radius:50%;background:var(--raised);display:grid;place-items:center;font-size:20px;color:var(--mint)">+</span><span style="font-size:14px;font-weight:700">Upload photo</span><span style="font-size:12px;color:var(--faint)">or drop it here</span></div>`}
        </div>
        <span style="font-size:12px;line-height:1.45;color:var(--faint)">One clear, front-facing photo. PNG, JPEG or WebP. Stays in this browser.</span>
        <button data-act="cg-photo-consent" style="display:flex;align-items:flex-start;gap:8px;padding:0;border:0;background:none;font-size:12px;line-height:1.45;cursor:pointer;text-align:left"><span class="tick ${c.photoConsent ? 'on' : ''}" style="width:16px;height:16px;font-size:11px">${c.photoConsent ? '✓' : ''}</span>I have the right to use this photo.</button>
        <span class="err">${esc(c.imgErr)}</span>
      </div>
      <div style="flex:1;min-width:260px;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;align-content:start">
        <label class="field"><span>Name</span><input class="input" data-cg="name" value="${esc(c.name)}" placeholder="e.g. Priya"></label>
        <label class="field"><span>Role</span><input class="input" data-cg="role" value="${esc(c.role)}" placeholder="e.g. Head of Procurement"></label>
        <label class="field" style="grid-column:1 / -1"><span>What they push on <span style="font-weight:500;color:var(--faint)">· optional</span></span><input class="input" data-cg="focus" value="${esc(c.focus)}" placeholder="e.g. pricing and contract length"></label>
      </div>
    </div>
    <div class="divider"></div>
    <div style="display:flex;flex-direction:column;gap:12px">
      <div class="row" style="gap:12px"><span class="kicker">Voice · Higgs TTS 3</span>${seg('cg-vmode', [['preset', 'Preset voice'], ['id', 'Voice ID'], ['clone', 'Clone from clip']], c.vmode, 'fit')}</div>
      ${voiceBody}
    </div>
    <div id="cg-foot"></div>
  </div>`;
}
function cgFoot() {
  const c = S.cg, ok = cgValid(c);
  const missing = ok ? [] : [!c.img && 'a photo', c.img && !c.photoConsent && 'photo consent', !c.name.trim() && 'a name', c.vmode === 'id' && !c.voiceId.trim() && 'a voice ID', c.vmode === 'clone' && !c.clipName && 'a voice clip', c.vmode === 'clone' && c.clipName && !c.consent && 'voice consent'].filter(Boolean);
  return `<div style="display:flex;justify-content:flex-end;align-items:center;gap:12px;flex-wrap:wrap">
    <span style="margin-right:auto;font-size:13px;color:var(--faint)">${missing.length ? `Still needs ${missing.join(', ')}.` : ''}</span>
    <button data-act="cg-close" style="padding:11px 18px;border-radius:10px;border:1px solid var(--border-input);background:transparent;font-size:14px;font-weight:600;cursor:pointer">Cancel</button>
    <button data-act="cg-save" class="btn-save" ${ok ? '' : 'disabled'}>${c.id ? 'Save changes' : 'Add to roster'}</button></div>`;
}

function stepAudience() {
  const n = S.chosen.length;
  const tile = (p, on) => `<button data-act="toggle" data-arg="${esc(p.id)}" class="pick ${on ? 'on' : ''}" style="padding:12px 14px;border-radius:12px;display:flex;gap:10px;align-items:flex-start">
      <span class="check"></span><span style="display:flex;flex-direction:column;gap:2px;min-width:0"><span style="font-size:15px;font-weight:700">${esc(p.name)}</span><span style="font-size:13px;color:var(--muted)">${esc(p.role)}</span></span></button>`;
  const customTile = (c) => {
    const on = S.chosen.includes(c.id);
    return `<div class="pick ${on ? 'on' : ''}" style="border-radius:12px;display:flex;flex-direction:column;min-width:0;cursor:default">
      <button data-act="toggle" data-arg="${esc(c.id)}" style="min-width:0;text-align:left;padding:12px 14px 6px;background:none;border:0;cursor:pointer;display:flex;gap:10px;align-items:flex-start">
        <span class="check"></span><span style="flex:none;width:32px;height:32px;border-radius:50%;background:var(--raised) url('${c.img}') center / cover no-repeat"></span>
        <span style="display:flex;flex-direction:column;gap:2px;min-width:0"><span style="font-size:15px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.name)}</span><span style="font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.role || 'Custom guest')}</span><span style="font:400 11px var(--mono);color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(voiceLabel(c))}</span></span>
      </button>
      <div style="display:flex;gap:2px;padding:0 8px 8px 34px"><button data-act="cg-edit" data-arg="${esc(c.id)}" class="btn-text" style="padding:4px 8px;font-size:12px;font-weight:600">Edit</button><button data-act="cg-remove" data-arg="${esc(c.id)}" class="btn-text danger" style="padding:4px 8px;font-size:12px;font-weight:600">Remove</button></div>
    </div>`;
  };
  return `<h1 class="title">Who's in the room?</h1>
    <p class="lede">Start from a preset, pick from the roster, or add your own guest.</p>${saveNote()}
    <div style="margin-top:24px;display:flex;flex-wrap:wrap;gap:8px">${presets.map((p) => `<button data-act="preset" data-arg="${p.id}" class="pill ${S.preset === p.id ? 'on' : ''}">${esc(p.name)}</button>`).join('')}</div>
    <div style="margin-top:18px;display:flex;justify-content:space-between;align-items:baseline"><span class="label">Roster</span><span style="font:400 13px var(--mono);color:var(--muted)">${n} / ${MAX_GUESTS} selected</span></div>
    <div style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px">
      ${ROSTER.map((p) => tile(p, S.chosen.includes(p.id))).join('')}
      ${S.customs.map(customTile).join('')}
      <button data-act="cg-open" class="add-tile"><span style="flex:none;width:18px;height:18px;border-radius:6px;background:var(--mint);color:var(--mint-ink);display:grid;place-items:center;font-size:15px;font-weight:800;line-height:1">+</span>
        <span style="display:flex;flex-direction:column;gap:2px"><span style="font-size:15px;font-weight:700">Custom guest</span><span style="font-size:13px;color:var(--muted)">Your own photo and voice</span></span></button>
    </div>
    ${S.cg ? cgPanel() : ''}
    <div class="panel" style="margin-top:22px;padding:20px 22px;gap:0">
      <div class="panel-title">Skepticism</div><div class="hint">How hard each guest pushes back</div>
      <div style="margin-top:14px;display:flex;flex-direction:column;gap:12px">${people().map((p) => {
        const v = S.skep[p.id] ?? p.sk;
        return `<div style="display:grid;grid-template-columns:150px 1fr 40px;gap:14px;align-items:center">
          <span style="font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(p.name)} <span style="color:var(--faint);font-weight:500">${esc(p.role)}</span></span>
          <input type="range" min="0" max="100" value="${v}" data-skep="${esc(p.id)}"><span data-skep-val="${esc(p.id)}" style="font:400 13px var(--mono);color:var(--muted);text-align:right">${v}</span></div>`;
      }).join('')}</div>
    </div>`;
}

function stepCurve() {
  const count = DIFFS.find((d) => d[0] === S.difficulty)[3];
  return `<h1 class="title">Curveballs &amp; pacing</h1>
    <p class="lede">Curveballs challenge the idea, never the person. You can pause or skip any of them.</p>
    <div class="field" style="margin-top:26px"><span>Difficulty</span>
      <div class="seg" style="background:var(--surface)">${DIFFS.map(([id, label, sub]) => `<button data-act="difficulty" data-arg="${id}" class="${S.difficulty === id ? 'on' : ''}" style="padding:10px 8px;display:flex;flex-direction:column;gap:2px;align-items:center"><span style="font-size:14px;font-weight:700">${label}</span><span style="font-size:12px;opacity:.7;font-weight:500">${sub}</span></button>`).join('')}</div></div>
    <div class="panel" style="margin-top:18px">
      <div class="row"><div><div class="panel-title">Number of curveballs</div><div class="hint">Thrown during the talk</div></div>${stepper('cb-count', count, count ? 'var(--coral)' : '')}</div>
      <div class="row"><div class="panel-title">Which ones</div>${seg('cb-mode', [['surprise', 'Surprise me'], ['choose', 'Let me choose']], S.cbMode, 'fit')}</div>
      ${S.cbMode === 'choose' ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px">${KINDS.map((k) => `<button data-act="kind" data-arg="${k.kind}" title="${esc(k.what)}" class="pick ${S.kinds.includes(k.kind) ? 'coral-on' : ''}" style="padding:10px 12px;border-radius:10px;${S.kinds.includes(k.kind) ? '' : 'background:var(--bg)'};display:flex;flex-direction:column;gap:2px"><span style="font-size:14px;font-weight:700">${k.name}</span><span style="font-size:12px;color:var(--muted)">${k.tests}</span></button>`).join('')}</div>` : ''}
    </div>
    <div class="panel" style="margin-top:18px">
      <div class="row"><div class="panel-title">Interruptions</div>${seg('freq', [['rare', 'Rare'], ['normal', 'Normal'], ['often', 'Often']], S.freq, 'fit')}</div>
      <div class="row"><div><div class="panel-title">Talk length</div><div class="hint">Target, in minutes</div></div>${stepper('length', S.length)}</div>
      <div class="row"><div><div class="panel-title">Q&amp;A at the end</div><div class="hint">Questions after you finish</div></div>${stepper('qna', S.qna)}</div>
    </div>
    ${S.startErr ? `<p class="err" style="margin-top:16px;font-size:14px">${esc(S.startErr)} <a href="/room.html?mock=1" style="color:var(--text);text-decoration:underline">Watch a mocked session instead</a>.</p>` : ''}`;
}

function renderFoot() {
  const last = S.step === 4;
  const nextLabel = last ? (S.starting ? 'Opening the room…' : 'Start presenting') : S.step === 1 && !S.deck ? 'Continue without slides' : 'Continue';
  $('foot').innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
    <button data-act="back" class="btn-ghost" style="color:${S.step === 0 ? 'var(--off)' : 'var(--text)'}">Back</button>
    <div style="display:flex;align-items:center;gap:10px">
      ${S.step === 0 ? `<button data-act="use-default" title="Skip the profile and use the neutral default" style="display:flex;align-items:center;gap:8px;padding:9px 13px 9px 9px;border-radius:999px;border:1px solid var(--border-input);background:transparent;color:#c5cac9;font-size:13px;font-weight:600;cursor:pointer"><span style="width:22px;height:22px;border-radius:50%;background:var(--raised-3);display:grid;place-items:center"><span style="width:8px;height:8px;border-radius:50%;background:var(--muted)"></span></span>Use default profile</button>` : ''}
      <button data-act="next" class="btn-mint" ${S.starting || S.uploading ? 'disabled' : ''} style="${last ? 'box-shadow:0 8px 30px oklch(0.82 0.15 150 / .35)' : ''}">${nextLabel}</button>
    </div></div>`;
}

function renderPreview() {
  const P = people(), n = P.length, L = layout(S.setting, n);
  const prof = S.profileId === null ? 'Default (neutral)' : S.profileId === 'new' ? (S.pname.trim() || 'New profile') : S.pname;
  const ctx = [S.ctx.trim() ? 'Notes' : null, S.ctxFiles.length ? `${S.ctxFiles.length} ${S.ctxFiles.length === 1 ? 'file' : 'files'}` : null].filter(Boolean).join(' · ') || 'None';
  const count = DIFFS.find((d) => d[0] === S.difficulty)[3];
  const rows = [
    ['Profile', prof],
    ['Slides', S.deck ? `${S.deck.filename} · ${S.deck.page_count}` : 'None — listening only'],
    ['Context', ctx],
    ['Curveballs', count ? `${count} · ${S.cbMode === 'choose' ? `${S.kinds.length} types` : 'surprise'}` : 'Off'],
    ['Length', `${S.length} min · ${S.qna} Q&A`],
  ];
  $('preview').innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:2px 4px 12px"><span style="font:500 12px var(--mono);color:var(--muted);letter-spacing:.06em">LIVE PREVIEW</span><span style="font-size:14px;font-weight:600">${settingById(S.setting).name} · ${n} ${n === 1 ? 'guest' : 'guests'}</span></div>
    <div class="stage" style="background:${L.bg}">
      ${L.decor.map((d) => `<div style="${rect(d)};border-radius:${d.r};background:${d.c}"></div>`).join('')}
      <div style="${rect(L.slide)};border-radius:1.2cqw;background:#1d2124;border:1px solid #2c3134;display:grid;place-items:center"><span style="font:500 max(8px,1.4cqw) var(--mono);color:var(--faint)">${esc(S.deck ? S.deck.filename : 'no slides')}</span></div>
      ${L.seats.map((t, i) => `<div class="tile ${P[i]?.img ? 'photo' : ''}" style="${rect(t)};border-radius:0.9cqw;background:${tileBg(P[i]?.img, P[i]?.idx ?? 0)}"><div style="position:absolute;left:6%;bottom:6%;font-weight:700;font-size:${cq(t.w, 0.075, 7)};white-space:nowrap;text-shadow:0 1px 4px rgba(0,0,0,.6)">${esc(P[i]?.name ?? '')}</div></div>`).join('')}
    </div>
    <div style="margin-top:14px;display:flex;flex-direction:column">${rows.map(([k, v]) => `<div class="sum-row"><span style="color:var(--muted)">${k}</span><span style="font-weight:600;text-align:right">${esc(v)}</span></div>`).join('')}</div>`;
}

function render() {
  autosave();
  $('steps').innerHTML = STEPS.map((label, i) => `<button data-act="go" data-arg="${i}" class="${i === S.step ? 'cur' : ''} ${i <= S.step ? 'reached' : ''} ${i < S.step ? 'done' : ''}"><span class="num">${i < S.step ? '✓' : i + 1}</span>${label}</button>`).join('');
  $('body').innerHTML = [stepProfile, stepSlides, stepRoom, stepAudience, stepCurve][S.step]();
  if (S.cg && S.step === 3) $('cg-foot').innerHTML = cgFoot();
  renderFoot();
  renderPreview();
}

// ---- actions --------------------------------------------------------------------------------
function setGuests(n) {
  n = Math.min(MAX_GUESTS, Math.max(MIN_GUESTS, n));
  const c = S.chosen.slice(0, n);
  for (const p of ROSTER) { if (c.length >= n) break; if (!c.includes(p.id)) c.push(p.id); }
  Object.assign(S, { chosen: c, preset: null });
}
function toggle(id) {
  const on = S.chosen.includes(id);
  if (on && S.chosen.length > MIN_GUESTS) S.chosen = S.chosen.filter((i) => i !== id);
  else if (!on && S.chosen.length < MAX_GUESTS) S.chosen = S.chosen.concat(id);
  else return;
  S.preset = null;
}
function saveCustom() {
  const c = S.cg; if (!cgValid(c)) return;
  const id = c.id || `custom_${Date.now()}`;
  const rec = { ...c, id, name: c.name.trim(), role: c.role.trim(), focus: c.focus.trim(), imgErr: '', clipErr: '' };
  S.customs = c.id ? S.customs.map((x) => (x.id === id ? rec : x)) : S.customs.concat(rec);
  if (!c.id && S.chosen.length < MAX_GUESTS) { S.chosen = S.chosen.concat(id); S.preset = null; }
  S.cg = null;
}
function removeCustom(id) {
  const skep = { ...S.skep }; delete skep[id];
  Object.assign(S, { customs: S.customs.filter((x) => x.id !== id), chosen: clampChosen(S.chosen.filter((i) => i !== id)), skep, cg: S.cg?.id === id ? null : S.cg });
}
function readPortrait(f) {
  if (!f) return;
  if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { S.cg.imgErr = 'Use a PNG, JPEG or WebP image.'; render(); return; }
  const r = new FileReader();
  r.onload = () => {
    const im = new Image();
    im.onload = () => {
      const N = 320, cv = document.createElement('canvas'); cv.width = cv.height = N;
      const k = Math.min(im.width, im.height);
      cv.getContext('2d').drawImage(im, (im.width - k) / 2, (im.height - k) / 2, k, k, 0, 0, N, N);
      Object.assign(S.cg, { img: cv.toDataURL('image/jpeg', 0.85), imgErr: '' });
      render();
    };
    im.src = r.result;
  };
  r.readAsDataURL(f);
}
async function tryDeck(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (ext !== 'pdf') { S.deckErr = `.${ext} isn't supported yet. Export the deck as PDF and drop it here.`; render(); return; }
  Object.assign(S, { deckErr: null, uploading: true }); render();
  try { S.deck = await uploadSlides(file); }
  catch (e) { S.deckErr = `Couldn't read that deck (${e.message.slice(0, 120)}). You can still present without slides.`; }
  S.uploading = false; render();
}
async function useSample() {
  const r = await fetch('/demo/sample_pitch.pdf');
  if (!r.ok) { S.deckErr = "The sample deck isn't in demo/ yet. Drop your own PDF, or continue without slides."; render(); return; }
  tryDeck(new File([await r.blob()], 'sample_pitch.pdf', { type: 'application/pdf' }));
}

function toPersona(id) {
  const sk = (v) => Math.min(1, Math.max(0, v / 100));
  if (BY[id]) return { ...BY[id], skepticism: sk(S.skep[id] ?? Math.round(BY[id].skepticism * 100)) };
  const c = S.customs.find((x) => x.id === id);
  return {
    id: c.id, name: c.name, role: c.role || 'Custom guest', focus: c.focus ? [c.focus] : [],
    skepticism: sk(S.skep[id] ?? 50), style_hint: null,
    // Cloned voices need the backend's voice route (Person B); until then they use the default voice.
    voice_id: c.vmode === 'preset' ? c.preset : c.vmode === 'id' ? c.voiceId.trim() : null,
    avatar_url: null, plays: [], custom: true,
  };
}
async function start() {
  if (S.cbMode === 'choose' && !S.kinds.length && S.difficulty !== 'friendly') { S.startErr = 'Pick at least one curveball, or switch to Surprise me.'; render(); return; }
  const count = DIFFS.find((d) => d[0] === S.difficulty)[3];
  const config = {
    preset_id: S.preset ?? 'custom',
    personas: S.chosen.map(toPersona),
    difficulty: S.difficulty,
    interruption_frequency: S.freq,
    curveballs: count === 0 ? { mode: 'off', kinds: [] } : S.cbMode === 'choose' ? { mode: 'choose', kinds: S.kinds } : { mode: 'surprise', kinds: [] },
    duration_target_s: S.length * 60,
    qna_questions: S.qna,
    input_mode: S.input,
    deck_id: S.deck?.deck_id ?? null,
  };
  const meta = { setting: S.setting, images: Object.fromEntries(S.customs.map((c) => [c.id, c.img])), config };
  if (isMock()) { saveSessionMeta('mock', meta); location.href = '/room.html?mock=1'; return; }
  Object.assign(S, { starting: true, startErr: null }); render();
  try {
    const { session_id } = await createSession(config);
    saveSessionMeta(session_id, meta);
    location.href = `/room.html?session=${session_id}`;
  } catch (e) {
    Object.assign(S, { starting: false, startErr: `Could not create the room (${e.message.slice(0, 160)}).` }); render();
  }
}

const ACTIONS = {
  go: (a) => goStep(Number(a)),
  back: () => { if (S.step > 0) goStep(S.step - 1); },
  next: () => (S.step === 4 ? start() : goStep(S.step + 1)),
  'pick-profile': (id) => loadProfile(S.profiles.find((p) => p.id === id)),
  'new-profile': () => Object.assign(S, { profileId: 'new', ...DEFAULT_ME, ...DEFAULT_ROOM }),
  'delete-profile': () => { S.profiles = S.profiles.filter((p) => p.id !== S.profileId); persist(S.profiles); setActive(null); Object.assign(S, { profileId: S.profiles.length ? null : 'new', ...DEFAULT_ME, ...DEFAULT_ROOM }); },
  'use-default': () => { setActive(null); Object.assign(S, { profileId: null, ...DEFAULT_ME, ...DEFAULT_ROOM }); goStep(1); },
  goal: (g) => { S.goal = g; }, level: (v) => { S.level = v; }, tone: (v) => { S.tone = v; },
  'pick-deck': () => $('deck-file').click(),
  'remove-deck': () => { S.deck = null; },
  'import-link': () => { if (S.link.trim()) S.deckErr = "Importing from links isn't connected yet. Export the deck as PDF and drop it above."; },
  sample: () => useSample(),
  attach: () => $('ctx-file').click(),
  unattach: (i) => { S.ctxFiles = S.ctxFiles.filter((_, j) => j !== Number(i)); },
  setting: (id) => { S.setting = id; },
  guests: (d) => setGuests(S.chosen.length + Number(d)),
  input: (v) => { S.input = v; },
  preset: (id) => { const p = presets.find((x) => x.id === id); Object.assign(S, { chosen: clampChosen(p.personas), preset: id, setting: PRESET_SETTING[id] ?? S.setting }); },
  toggle: (id) => toggle(id),
  'cg-open': () => { S.cg = { ...BLANK_CG }; },
  'cg-close': () => { S.cg = null; },
  'cg-edit': (id) => { S.cg = { ...BLANK_CG, ...S.customs.find((c) => c.id === id), imgErr: '', clipErr: '' }; },
  'cg-remove': (id) => removeCustom(id),
  'cg-save': () => saveCustom(),
  'cg-vmode': (m) => { S.cg.vmode = m; },
  'cg-voice': (v) => { S.cg.preset = v; },
  'cg-consent': () => { S.cg.consent = !S.cg.consent; },
  'cg-photo-consent': () => { S.cg.photoConsent = !S.cg.photoConsent; },
  'pick-portrait': () => $('portrait-file').click(),
  'pick-clip': () => $('clip-file').click(),
  difficulty: (d) => { S.difficulty = d; S.startErr = null; },
  'cb-count': (d) => { const i = Math.min(2, Math.max(0, DIFFS.findIndex((x) => x[0] === S.difficulty) + Number(d))); S.difficulty = DIFFS[i][0]; },
  'cb-mode': (m) => { S.cbMode = m; S.startErr = null; },
  kind: (k) => { S.kinds = S.kinds.includes(k) ? S.kinds.filter((x) => x !== k) : S.kinds.concat(k); S.startErr = null; },
  freq: (f) => { S.freq = f; },
  length: (d) => { S.length = Math.min(20, Math.max(1, S.length + Number(d))); },
  qna: (d) => { S.qna = Math.min(3, Math.max(0, S.qna + Number(d))); },
};
const ASYNC = new Set(['next', 'go', 'back', 'use-default', 'pick-deck', 'attach', 'pick-portrait', 'pick-clip', 'sample']);

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act;
  ACTIONS[act]?.(el.dataset.arg);
  if (!ASYNC.has(act)) render();
});
document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.dataset.model) { S[t.dataset.model] = t.value; if (t.dataset.model === 'link') S.deckErr = null; renderPreview(); autosave(); }
  else if (t.dataset.cg) { S.cg[t.dataset.cg] = t.value; $('cg-foot').innerHTML = cgFoot(); }
  else if (t.dataset.skep) { S.skep = { ...S.skep, [t.dataset.skep]: Number(t.value) }; document.querySelector(`[data-skep-val="${CSS.escape(t.dataset.skep)}"]`).textContent = t.value; autosave(); }
  else if (t.dataset.range === 'guests') { setGuests(Number(t.value)); render(); }
});
$('deck-file').onchange = (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) tryDeck(f); };
$('ctx-file').onchange = (e) => { const names = [...e.target.files].map((f) => f.name); e.target.value = ''; if (names.length) { S.ctxFiles = S.ctxFiles.concat(names); render(); } };
$('portrait-file').onchange = (e) => { readPortrait(e.target.files[0]); e.target.value = ''; };
$('clip-file').onchange = (e) => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  const ext = (f.name.split('.').pop() || '').toLowerCase();
  Object.assign(S.cg, ['wav', 'mp3', 'opus', 'pcm', 'flac'].includes(ext) ? { clipName: f.name, clipErr: '' } : { clipErr: `.${ext} isn't supported. Use WAV, MP3, Opus, PCM or FLAC.` });
  render();
};
// Drag and drop: the deck zone and the portrait zone are re-rendered, so delegate on document.
document.addEventListener('dragover', (e) => {
  const z = e.target.closest('#drop, #portrait'); if (!z) return;
  e.preventDefault();
  if (z.id === 'drop' && !S.drag) { S.drag = true; z.classList.add('drag'); }
});
document.addEventListener('dragleave', (e) => { if (e.target.id === 'drop') { S.drag = false; e.target.classList.remove('drag'); } });
document.addEventListener('drop', (e) => {
  const z = e.target.closest('#drop, #portrait'); if (!z) return;
  e.preventDefault(); S.drag = false;
  const f = e.dataTransfer.files[0]; if (!f) return;
  if (z.id === 'drop') tryDeck(f); else readPortrait(f);
});

// ---- boot -----------------------------------------------------------------------------------
const active = S.profiles.find((p) => p.id === localStorage.getItem(LS_ACTIVE));
if (active) loadProfile(active); else if (!S.profiles.length) S.profileId = 'new';
const presetParam = presets.find((p) => p.id === qs.get('preset'));
if (presetParam) ACTIONS.preset(presetParam.id);
render();
