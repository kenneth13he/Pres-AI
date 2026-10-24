// Preset → audience builder → the real presentation room, using the shared API contract.
import { createSession, getPresets, uploadSlides } from '/js/api.js';
import { assignPortraits } from './portraits.js';
import { createSetupController } from './setup_controller.js?v=adaptive-room-1';
import { createSetupView } from './setup_view.js?v=adaptive-room-1';
import { createSetupWizard } from './setup_wizard.js?v=adaptive-room-1';

let storage;
try { storage = window.localStorage; } catch { /* The rehearsal still works in private mode. */ }
const query = new URLSearchParams(location.search);
const baseView = createSetupView({ document, assignPortraits });
let view;
try {
  const data = await getPresets();
  view = createSetupWizard({ document, assignPortraits, storage, presets: data.presets,
    view: baseView, initialProfile: query.get('profile') ?? '',
    navigate: (url) => { location.href = url; } });
  createSetupController({ data,
    presetId: query.get('preset') ?? 'startup_pitch', view,
    createSession: async (...args) => {
      const result = await createSession(...args); view.remember(result); return result;
    }, uploadSlides, navigate: (url) => { location.href = url; } });
} catch {
  if (view) view.failed();
  else {
    baseView.failed(); const notice = document.getElementById('wizard-notice');
    notice.hidden = false; notice.textContent = 'We could not load your audience. Refresh this page to try again.';
    document.getElementById('wizard-hint-0').textContent = 'Setup could not load. Refresh the page to try again.';
  }
}
