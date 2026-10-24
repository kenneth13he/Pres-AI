// Safe DOM rendering: persona names, custom descriptions and API text never become HTML.
export function createSetupView({ document, assignPortraits = () => new Map() }) {
  const $ = (id) => document.getElementById(id);
  const rows = new Map(), curveRows = new Map();
  let controller, initialized = false;
  const node = (tag, classes, text) => {
    const element = document.createElement(tag);
    if (classes) element.className = classes;
    if (text != null) element.textContent = text;
    return element;
  };
  function portrait(person, image) {
    const frame = node('div', 'h-12 w-12 shrink-0 overflow-hidden rounded-full border border-slate-700 bg-slate-800');
    const fallback = () => {
      frame.replaceChildren();
      frame.classList.add('grid', 'place-items-center', 'text-lg', 'text-cyan-300');
      frame.textContent = person.custom ? '+' : String(person.name ?? '?').slice(0, 1);
    };
    if (image?.src) {
      const img = node('img', 'h-full w-full object-cover');
      img.onerror = fallback;
      img.src = image.src; img.alt = `${person.name} · fictional`; img.loading = 'lazy'; frame.append(img);
    } else fallback();
    return frame;
  }
  function buildRoster(state) {
    let index = 0;
    for (const person of state.roster.values()) {
      const card = node('article', 'rounded-xl border border-slate-700 bg-slate-950/50 p-4 transition');
      card.setAttribute('data-persona', person.id);
      const top = node('div', 'flex items-start gap-3');
      const checkbox = node('input', 'mt-4 h-4 w-4 shrink-0 accent-cyan-400');
      checkbox.type = 'checkbox'; checkbox.id = `roster-person-${index}`;
      checkbox.onchange = () => controller.choosePersona(person.id, checkbox.checked);
      const label = node('label', 'min-w-0 flex-1 cursor-pointer'); label.htmlFor = checkbox.id;
      label.append(node('span', 'block text-sm font-semibold text-slate-100', person.role),
        node('span', 'block text-xs text-slate-400', `${person.name} · fictional`));
      const avatar = node('div', 'shrink-0');
      top.append(checkbox, avatar, label);
      const focus = node('p', 'mt-3 text-xs leading-relaxed text-slate-400', person.focus.join(' · '));
      const setting = node('div', 'mt-3 flex items-center gap-3');
      const sliderLabel = node('label', 'text-xs text-slate-400', 'Skepticism');
      const slider = node('input', 'min-w-0 flex-1 accent-cyan-400');
      slider.type = 'range'; slider.min = '0'; slider.max = '1'; slider.step = '0.05';
      slider.id = `roster-skepticism-${index++}`; sliderLabel.htmlFor = slider.id;
      slider.oninput = () => controller.skepticism(person.id, slider.value);
      const amount = node('output', 'w-10 text-right text-xs tabular-nums text-cyan-300');
      amount.setAttribute('for', slider.id);
      setting.append(sliderLabel, slider, amount); card.append(top, focus, setting);
      rows.set(person.id, { card, checkbox, slider, amount, avatar }); $('roster').append(card);
    }
  }
  function buildCurveballs(state) {
    state.allowed.forEach((kind, index) => {
      const label = node('label', 'flex cursor-pointer items-start gap-2 rounded-lg border border-slate-700 bg-slate-950/40 p-3');
      const input = node('input', 'mt-1 accent-cyan-400');
      input.type = 'checkbox'; input.id = `curveball-${index}`;
      input.onchange = () => controller.curveball(kind, input.checked);
      const text = node('span', 'text-sm');
      text.append(node('span', 'block capitalize text-slate-200', kind.replaceAll('_', ' ')),
        node('span', 'mt-1 block text-xs leading-relaxed text-slate-500', state.catalogue.get(kind)?.line ?? ''));
      label.append(input, text); $('cb-choose').append(label); curveRows.set(kind, input);
    });
  }
  return {
    bind(value) {
      controller = value;
      $('customise').onclick = () => {
        const open = $('builder').classList.contains('hidden');
        $('builder').classList.toggle('hidden', !open);
        $('customise').setAttribute('aria-expanded', String(open));
        $('customise').textContent = open ? 'Done customising' : 'Customise audience';
      };
      $('custom-persona').oninput = () => controller.custom($('custom-persona').value);
      $('remove-custom').onclick = () => controller.custom('');
      const options = { difficulty: 'difficulty', frequency: 'interruption_frequency',
        'cb-mode': 'curveball_mode', duration: 'duration_minutes', qna: 'qna_questions',
        'input-mode': 'input_mode' };
      for (const [id, option] of Object.entries(options)) {
        const input = $(id), handler = () => controller.option(option, input.value);
        if (input.tagName === 'INPUT') input.oninput = handler; else input.onchange = handler;
      }
      $('pdf').onchange = () => {
        const file = $('pdf').files?.[0]; $('pdf').value = ''; void controller.upload(file);
      };
      $('remove-pdf').onclick = () => { $('pdf').value = ''; void controller.upload(null); };
      const drop = $('pdf-drop');
      drop.ondragover = (event) => { event.preventDefault(); drop.classList.add('border-cyan-500'); };
      drop.ondragleave = () => drop.classList.remove('border-cyan-500');
      drop.ondrop = (event) => {
        event.preventDefault(); drop.classList.remove('border-cyan-500');
        void controller.upload(event.dataTransfer?.files?.[0]);
      };
      $('start').onclick = () => controller.submit();
    },
    render(state) {
      if (!initialized) {
        $('title').textContent = state.preset?.name ?? 'Build your audience';
        $('preset-description').textContent = state.preset?.tagline ?? 'Choose who listens, what they question, and how much pressure to add.';
        buildRoster(state); buildCurveballs(state); initialized = true;
        if (!state.preset) $('customise').click();
      }
      const people = state.audience, images = assignPortraits(people);
      $('audience-summary').replaceChildren(...people.map((person) => {
        const card = node('div', `flex min-w-0 items-center gap-3 rounded-xl border p-3 ${person.custom
          ? 'border-dashed border-cyan-700 bg-cyan-950/20' : 'border-slate-700 bg-slate-900'}`);
        card.setAttribute('data-persona', person.id);
        const text = node('div', 'min-w-0');
        text.append(node('p', 'truncate text-sm font-semibold text-slate-100', person.custom ? 'Custom · fictional' : person.name),
          node('p', 'truncate text-xs text-slate-400', person.role));
        card.append(portrait(person, images.get(person.id)), text); return card;
      }));
      $('seat-count').textContent = people.length > 3 ? `${people.length} requested · maximum 3`
        : `${people.length} of 3 audience seats`;
      $('seat-count').classList.toggle('text-amber-300', people.length > 3 || people.length < 2);
      $('selection-help').textContent = state.customDescription.trim()
        ? 'Your custom person takes one seat. Keep exactly two roster people checked.'
        : 'Choose two or three fictional audience members. The moderator hosts separately.';
      const seatError = state.customDescription.trim() ? state.chosen.size !== 2
        : state.chosen.size < 2 || state.chosen.size > 3;
      $('selection-error').textContent = seatError ? state.errors[0] : '';
      $('selection-error').classList.toggle('hidden', !seatError);
      const limit = state.customDescription.trim() ? 2 : 3;
      for (const [id, row] of rows) {
        const selected = state.chosen.has(id), person = state.roster.get(id);
        row.checkbox.checked = selected;
        row.checkbox.disabled = state.submitting || (!selected && state.chosen.size >= limit);
        row.card.classList.toggle('border-cyan-500', selected);
        row.card.classList.toggle('border-slate-700', !selected);
        row.slider.value = String(state.skepticism.get(id) ?? person.skepticism);
        row.slider.disabled = state.submitting || !selected;
        row.amount.textContent = `${Math.round(Number(row.slider.value) * 100)}%`;
        const image = selected ? images.get(id) : null;
        const portraitKey = image?.src ?? 'initials';
        if (row.portraitKey !== portraitKey) {
          row.avatar.replaceChildren(portrait(person, image)); row.portraitKey = portraitKey;
        }
      }
      $('custom-persona').value = state.customDescription;
      $('remove-custom').classList.toggle('hidden', !state.customDescription);
      $('custom-count').textContent = `${state.customDescription.length} / 600`;
      const o = state.options;
      for (const [id, value] of Object.entries({ difficulty: o.difficulty,
        frequency: o.interruption_frequency, 'cb-mode': o.curveball_mode,
        duration: o.duration_minutes, qna: o.qna_questions, 'input-mode': o.input_mode })) $(id).value = value;
      $('cb-choose').classList.toggle('hidden', o.curveball_mode !== 'choose');
      for (const [kind, input] of curveRows) input.checked = state.chosenCurveballs.has(kind);
      $('curveball-note').textContent = o.difficulty === 'friendly'
        ? 'Friendly sessions ask questions without curveballs.'
        : o.curveball_mode === 'off' ? 'No curveballs. Your audience can still ask questions.'
          : o.curveball_mode === 'choose' ? `${state.chosenCurveballs.size} kinds selected. Each kind can happen at most once.`
            : 'The room picks from this preset’s curveballs when a natural moment comes.';
      $('pdf-status').textContent = state.upload.message || 'Optional · PDF only · up to 50 MB';
      $('pdf-status').classList.toggle('text-amber-300', state.upload.status === 'error');
      $('remove-pdf').classList.toggle('hidden', !state.upload.filename);
      $('setup-fields').disabled = state.submitting;
      $('start').disabled = state.submitting || state.errors.length > 0;
      $('start').textContent = state.submitting ? 'Creating your room…' : 'Start rehearsal →';
      $('start').setAttribute('aria-busy', String(state.submitting));
      $('start-status').textContent = state.status || state.errors[0]
        || 'Your microphone stays off until you start presenting.';
    },
    failed() {
      $('start').disabled = true;
      $('start-status').textContent = 'We could not load the audience choices. Refresh this page to try again.';
    },
  };
}
