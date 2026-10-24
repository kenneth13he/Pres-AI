import { PRESET_SETTING, saveSessionMeta } from './rooms.js?v=adaptive-room-1';
import { createSetupPreview } from './setup_preview.js?v=adaptive-room-1';
import { captureSetupProfile, loadSetupProfiles, saveSetupProfiles } from './setup_profiles.js?v=adaptive-room-1';

// Decorates the tested setup controller/view: uploads, validation and Start still have one owner.
export function createSetupWizard({ document, view, assignPortraits, storage,
  presets = [], initialProfile = '', navigate = () => {} }) {
  const $ = (id) => document.getElementById(id);
  const preview = createSetupPreview({ document, assignPortraits });
  let controller, state, initialized = false, step = 0, reached = 0, setting = 'video';
  const validPresets = new Set([...presets.map((p) => p.id), 'custom']);
  let profiles = loadSetupProfiles(storage).filter((p) => validPresets.has(p.presetId));
  let activeId = null, defaults;
  const node = (tag, cls, text) => {
    const el = document.createElement(tag); if (cls) el.className = cls;
    if (text != null) el.textContent = text; return el;
  };
  function show(next) {
    if (state?.submitting) return;
    const previous = step;
    step = Math.max(0, Math.min(4, next)); reached = Math.max(step, reached);
    for (let i = 0; i < 5; i++) {
      const panel = $(`wizard-panel-${i}`), button = $(`wizard-step-${i}`);
      panel.hidden = i !== step; button.disabled = i > reached;
      button.className = `${i === step ? 'cur' : ''} ${i <= reached ? 'reached' : ''} ${i < step ? 'done' : ''}`;
      button.setAttribute('aria-current', i === step ? 'step' : 'false');
    }
    if (step !== previous) {
      const heading = $(['profile-title', 'slides-heading', 'room-heading', 'title', 'pacing-heading'][step]);
      heading.setAttribute('tabindex', '-1'); heading.focus?.({ preventScroll: true });
      document.defaultView?.scrollTo?.({ top: 0, behavior: 'auto' });
    }
  }
  function rooms() {
    preview.rooms(setting, (value) => {
      if (state.submitting) return;
      setting = value; rooms(); preview.render(state, setting);
    });
  }
  function chooseProfile(profile) {
    if (state.submitting) return;
    if (profile.presetId !== (state.preset?.id ?? 'custom')) {
      navigate(`/setup.html?preset=${encodeURIComponent(profile.presetId)}&profile=${encodeURIComponent(profile.id)}`);
      return;
    }
    activeId = profile.id; setting = profile.setting; $('profile-name').value = profile.name;
    controller.profile(profile); rooms(); renderProfiles(); show(1);
    $('profile-status').textContent = `Loaded ${profile.name}`;
  }
  function renderProfiles() {
    const cards = profiles.map((profile) => {
      const button = node('button', `pick ${activeId === profile.id ? 'on' : ''}`);
      button.type = 'button'; button.setAttribute('style', 'padding:16px;border-radius:14px;display:flex;flex-direction:column;gap:8px');
      const count = profile.chosen.length
        + (typeof profile.customDescription === 'string' && profile.customDescription.trim() ? 1 : 0);
      button.append(node('span', 'panel-title', profile.name),
        node('span', 'hint', `${count} guest${count === 1 ? '' : 's'} · ${profile.setting}`));
      button.onclick = () => chooseProfile(profile); return button;
    });
    const add = node('button', 'pick', '+ New profile'); add.type = 'button';
    add.setAttribute('style', 'padding:22px 16px;border-radius:14px;border-style:dashed');
    add.onclick = () => {
      if (state.submitting) return;
      activeId = null; $('profile-name').value = ''; $('profile-name').focus?.();
      $('profile-status').textContent = 'Name your profile, then save it after choosing your audience.';
    };
    $('profiles').replaceChildren(...cards, add);
  }
  return {
    bind(value) {
      controller = value; view.bind(value);
      const choices = presets.map((p) => {
        const option = node('option', '', p.name); option.value = p.id; return option;
      });
      const custom = node('option', '', 'Custom audience'); custom.value = 'custom';
      $('preset-choice').replaceChildren(...choices, custom);
      $('preset-choice').onchange = () => {
        const id = $('preset-choice').value;
        if (!state.submitting && validPresets.has(id) && id !== (state.preset?.id ?? 'custom')) {
          navigate(`/setup.html?preset=${encodeURIComponent(id)}`);
        }
      };
      for (let i = 0; i < 5; i++) {
        $(`wizard-step-${i}`).onclick = () => { if (i <= reached) show(i); };
        if (i) $(`wizard-back-${i}`).onclick = () => show(i - 1);
        if (i && i < 4) $(`wizard-next-${i}`).onclick = () => {
          if (i === 1 && ['uploading', 'error'].includes(state.upload.status)) return;
          if (i === 3 && state.errors.some((e) => /people|person|roster|description/.test(e))) return;
          show(i + 1);
        };
      }
      $('use-default').onclick = () => {
        if (state.submitting) return;
        activeId = null; setting = PRESET_SETTING[state.preset?.id] ?? 'video';
        controller.profile(defaults); rooms(); $('profile-name').value = ''; show(1);
        $('profile-status').textContent = 'Default profile · applies to this session only';
      };
      $('profile-continue').onclick = () => show(1);
      $('save-profile').onclick = () => {
        if (state.submitting) return;
        const id = activeId ?? `profile-${Date.now()}`;
        const profile = captureSetupProfile(state, { id, name: $('profile-name').value, setting });
        const updated = [...profiles.filter((p) => p.id !== id), profile].slice(-12);
        if (!saveSetupProfiles(storage, updated)) {
          $('start-status').textContent = 'This browser could not save the profile. You can still start your rehearsal.'; return;
        }
        profiles = updated; activeId = id; renderProfiles();
        $('start-status').textContent = `Saved ${profile.name}. Your room is ready.`;
        $('profile-status').textContent = `Saved ${profile.name}`;
      };
    },
    render(value) {
      state = value; view.render(value);
      $('preset-choice').value = state.preset?.id ?? 'custom';
      if (!initialized) {
        initialized = true; setting = PRESET_SETTING[state.preset?.id] ?? 'video';
        defaults = captureSetupProfile(state, { id: 'default', name: 'Default', setting });
        renderProfiles(); rooms();
        const profile = profiles.find((p) => p.id === initialProfile);
        if (profile) chooseProfile(profile);
      }
      preview.render(state, setting); show(step);
      $('profile-continue').disabled = state.submitting; $('use-default').disabled = state.submitting;
      $('wizard-hint-0').textContent = 'Your profile is optional. You can continue right away.';
      $('wizard-hint-1').textContent = state.upload.status === 'uploading'
        ? 'Reading your PDF. Continue will be ready when the upload finishes.'
        : state.upload.status === 'error' ? `${state.upload.message} Remove the file or choose another PDF.`
          : state.deckId ? 'Your slides are ready. Continue to choose your room.'
            : 'Slides are optional. You can continue without a PDF.';
      $('wizard-hint-3').textContent = state.errors.find((e) => /people|person|roster|description/.test(e))
        || `${state.audience.length} audience member${state.audience.length === 1 ? ' is' : 's are'} ready. Continue to set the pacing.`;
      for (const i of [1, 2, 3]) {
        $(`wizard-next-${i}`).disabled = state.submitting
          || (i === 1 && ['uploading', 'error'].includes(state.upload.status))
          || (i === 3 && state.errors.some((e) => /people|person|roster|description/.test(e)));
        $(`wizard-next-${i}`).setAttribute('aria-busy',
          String(state.submitting || (i === 1 && state.upload.status === 'uploading')));
      }
      if (state.submitting) for (let i = 0; i < 5; i++) $(`wizard-step-${i}`).disabled = true;
    },
    remember(result) {
      saveSessionMeta(result.session_id, { setting, config: result.config });
    },
    failed() {
      view.failed(); $('wizard-notice').hidden = false;
      $('wizard-notice').textContent = 'We could not load your audience. Refresh this page to try again.';
      $('wizard-hint-0').textContent = 'Setup could not load. Refresh the page to try again.';
      $('profile-continue').disabled = true; $('use-default').disabled = true;
    },
  };
}
