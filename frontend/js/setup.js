// Preset → audience builder → the real presentation room, using the shared API contract.
import { createSession, getPresets, uploadSlides } from '/js/api.js';
import { assignPortraits } from './portraits.js';
import { createSetupController } from './setup_controller.js';
import { createSetupView } from './setup_view.js';

const view = createSetupView({ document, assignPortraits });
try {
  createSetupController({ data: await getPresets(),
    presetId: new URLSearchParams(location.search).get('preset') ?? 'startup_pitch',
    view, createSession, uploadSlides, navigate: (url) => { location.href = url; } });
} catch { view.failed(); }
