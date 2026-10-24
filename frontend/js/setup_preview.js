import { layout, rect, settingById, thumbShapes } from './rooms.js';

// Layout geometry is trusted design data; names and descriptions always use text nodes.
export function createSetupPreview({ document, assignPortraits }) {
  const $ = (id) => document.getElementById(id);
  const node = (tag, cls, text) => {
    const el = document.createElement(tag); if (cls) el.className = cls;
    if (text != null) el.textContent = text; return el;
  };
  function shape(s) {
    const el = node('div', '', s.label ?? '');
    el.setAttribute('style', `position:absolute;${rect(s)};border-radius:${s.r ?? '4px'};background:${s.c};border:${s.b ?? '0'};display:grid;place-items:center;color:${s.lc ?? 'transparent'};font:600 8px var(--mono);overflow:hidden`);
    return el;
  }
  return {
    rooms(current, choose) {
      const options = ['video', 'classroom', 'boardroom', 'lecture', 'interview'].map((id) => {
        const room = settingById(id), button = node('button', `pick ${id === current ? 'on' : ''}`);
        button.type = 'button'; button.setAttribute('aria-pressed', String(id === current));
        button.setAttribute('style', 'padding:12px;border-radius:14px');
        const picture = node('div', 'stage'); picture.setAttribute('aria-hidden', 'true');
        picture.setAttribute('style', 'background:var(--bg);border-radius:8px');
        picture.append(...thumbShapes(id).map(shape));
        const name = node('p', 'panel-title', room.name); name.setAttribute('style', 'margin:10px 0 2px');
        button.append(picture, name, node('span', 'hint', room.sub)); button.onclick = () => choose(id);
        return button;
      });
      $('room-settings').replaceChildren(...options);
    },
    render(state, setting) {
      const people = state.audience.slice(0, 3), images = assignPortraits(people);
      const plan = layout(setting, people.length), stage = $('preview-stage');
      const parts = plan.decor.map((d) => shape(d));
      parts.push(shape({ ...plan.slide, c: 'var(--mint-tint)', b: '1px solid var(--mint-line)',
        label: state.deckId ? 'Your slides' : 'Slides optional', lc: 'var(--mint)' }));
      people.forEach((person, i) => {
        const tile = node('div', 'tile'), image = images.get(person.id);
        tile.setAttribute('style', `position:absolute;${rect(plan.seats[i])};border-radius:6px;background:var(--raised);overflow:hidden;isolation:isolate`);
        const initials = String(person.name || '?').split(/\s+/).filter(Boolean)
          .slice(0, 2).map((word) => word[0]).join('').toUpperCase();
        const fallback = node('div', 'preview-portrait-fallback', initials);
        fallback.setAttribute('style', 'position:absolute;inset:0;z-index:1;display:grid;place-items:center;color:var(--mint);font-size:12px;font-weight:800');
        fallback.hidden = Boolean(image?.src); tile.append(fallback);
        if (image?.src) {
          const fill = node('img', 'preview-portrait-fill'), img = node('img', 'preview-portrait-image');
          fill.alt = img.alt = ''; fill.setAttribute('aria-hidden', 'true');
          fill.decoding = img.decoding = 'async';
          fill.setAttribute('style', 'position:absolute;inset:-12%;z-index:0;width:124%;height:124%;object-fit:cover;filter:blur(10px) brightness(.45) saturate(.9);pointer-events:none');
          img.setAttribute('style', 'position:absolute;inset:0;z-index:1;width:100%;height:100%;object-fit:contain;object-position:center');
          img.onerror = fill.onerror = () => {
            img.hidden = fill.hidden = true; fallback.hidden = false;
          };
          fill.src = img.src = image.src; tile.append(fill, img);
        }
        const name = node('span', '', person.name);
        name.setAttribute('style', 'position:absolute;bottom:0;left:0;right:0;z-index:2;padding:3px;background:#0c0d0fcc;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap');
        tile.append(name); parts.push(tile);
      });
      stage.setAttribute('style', `background:${plan.bg}`); stage.replaceChildren(...parts);
      $('preview-room-name').textContent = settingById(setting).name;
      $('preview-count').textContent = `${state.audience.length} guests`;
      $('preview-pacing').textContent = `${state.options.duration_minutes} min · ${state.options.difficulty}`;
      $('preview-input').textContent = state.options.input_mode === 'live' ? 'Hands-free mic' : 'Hold to talk';
    },
  };
}
