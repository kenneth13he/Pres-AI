// All report strings are rendered as text. Null measurements never become zero scores.
export function createReportView(doc = document) {
  const $ = (id) => doc.getElementById(id);
  const human = (value) => String(value ?? '').replace(/_/g, ' ');
  const label = (value) => ({ vc: 'VC', question_handling: 'Question handling',
    filler_words: 'Filler words', words_per_minute: 'Words per minute',
    unanswered_questions: 'Unanswered questions', curveballs_faced: 'Curveballs faced',
    skipped: 'Skipped events' })[value] || human(value);
  const score = (value) => value == null ? 'Not assessed' : `${value}/100`;
  const time = (ms) => ms == null ? 'Time not measured'
    : `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
  const node = (tag, text, className = '') => {
    const el = doc.createElement(tag); el.textContent = text ?? ''; el.className = className; return el;
  };
  const card = () => node('article', '', 'rounded-xl border border-slate-800 bg-slate-900/40 p-4');
  const empty = (id, message, tag = 'p') => $(id).append(node(tag, message, 'text-sm text-slate-400'));
  function quote(parent, value) {
    if (value) parent.append(node('blockquote', `“${value}”`, 'mt-3 border-l-2 border-cyan-800 pl-3 text-sm text-slate-300'));
  }
  return {
    links({ room, home, mock }) {
      $('new-session').href = home; $('back-room').hidden = !room;
      if (room) $('back-room').href = room;
      $('report-mode').hidden = !mock;
    },
    bindRetry(handler) { $('retry-report').onclick = () => handler(); },
    state(kind, message) {
      $('report-state').textContent = message;
      $('report-state').setAttribute('role', kind === 'error' || kind === 'missing' ? 'alert' : 'status');
      $('report-state').setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');
      $('report-content').hidden = kind !== 'ready';
      $('retry-report').hidden = !['error', 'unfinished'].includes(kind);
      $('retry-report').disabled = kind === 'loading';
      $('report-shell').setAttribute('aria-busy', String(kind === 'loading'));
    },
    render(report, { mock = false, personas = [] } = {}) {
      const people = new Map((Array.isArray(personas) ? personas : [])
        .filter((person) => person && typeof person.id === 'string')
        .map((person) => [person.id, person]));
      for (const id of ['dimensions', 'metrics', 'caveats', 'curveballs', 'moments', 'strengths', 'improvements', 'personas']) $(id).replaceChildren();
      $('session-label').textContent = `Session ${report.session_id}`;
      $('overall-score').textContent = score(report.overall_score);
      $('report-mode').hidden = !mock;
      for (const [key, value] of Object.entries(report.dimensions)) {
        const tile = card();
        tile.append(node('h3', label(key), 'text-sm capitalize text-slate-400'),
          node('p', score(value), 'mt-2 text-2xl font-semibold'));
        $('dimensions').append(tile);
      }
      if (!Object.keys(report.dimensions).length) empty('dimensions', 'No dimension scores were recorded.');
      for (const [key, value] of Object.entries(report.metrics)) {
        $('metrics').append(node('li', `${label(key)}: ${value == null ? 'Not measured' : value}`,
          'rounded-full border border-slate-800 bg-slate-900 px-3 py-2 text-sm'));
      }
      if (!Object.keys(report.metrics).length) empty('metrics', 'No metrics were recorded.', 'li');
      for (const caveat of report.metric_caveats) $('caveats').append(node('li', caveat));
      if (!report.metric_caveats.length) empty('caveats', 'Unmeasured values are labelled. Recognition-dependent metrics are approximate.', 'li');
      for (const item of report.curveballs) {
        const box = card(), skipped = item.resolution === 'skipped', recovery = skipped ? null : item.recovery;
        box.append(node('h3', label(item.kind), 'font-medium capitalize'),
          node('p', `${time(item.at_ms)} · ${human(item.resolution)}`, 'mt-1 text-xs text-slate-400'));
        if (skipped) {
          box.append(node('p', 'Skipped — no penalty. Recovery was not scored.', 'mt-3 text-sm text-cyan-200'));
        } else {
          box.append(node('p', `Recovery score: ${score(recovery?.score)}`, 'mt-3 text-lg font-medium'),
            node('p', `Speech resumed after: ${recovery?.resume_after_ms == null ? 'Not measured'
              : `${(recovery.resume_after_ms / 1000).toFixed(1)} s`}`, 'mt-1 text-sm text-slate-300'));
          if (recovery?.notes) box.append(node('p', recovery.notes, 'mt-2 text-sm text-slate-400'));
          quote(box, recovery?.evidence);
          if (recovery?.suggestion) box.append(node('p', recovery.suggestion, 'mt-3 text-sm text-cyan-200'));
        }
        $('curveballs').append(box);
      }
      if (!report.curveballs.length) empty('curveballs', 'No curveball fired this session.');
      for (const moment of [...report.key_moments].sort((a, b) => a.at_ms - b.at_ms)) {
        const row = node('li', '', 'rounded-lg border border-slate-800 p-3');
        const speaker = moment.persona_id ? people.get(moment.persona_id)?.name || label(moment.persona_id) : null;
        row.append(node('span', `${time(moment.at_ms)} · ${human(moment.type)}${speaker ? ` · ${speaker}` : ''}`, 'mr-3 font-mono text-xs text-slate-400'),
          node('span', moment.summary));
        $('moments').append(row);
      }
      if (!report.key_moments.length) empty('moments', 'No key moments were recorded.', 'li');
      for (const strength of report.strengths) $('strengths').append(node('li', strength, 'text-sm text-slate-300'));
      if (!report.strengths.length) empty('strengths', 'No strengths were recorded.', 'li');
      for (const item of report.improvements) {
        const box = card(); box.append(node('h3', item.observation, 'font-medium'));
        quote(box, item.evidence); box.append(node('p', item.suggestion, 'mt-3 text-sm text-cyan-200'));
        $('improvements').append(box);
      }
      if (!report.improvements.length) empty('improvements', 'No specific improvements were recorded.');
      for (const person of report.persona_feedback) {
        const box = card();
        const profile = people.get(person.persona_id);
        box.append(node('h3', profile?.name || label(person.persona_id), 'font-medium capitalize'),
          node('p', person.comment, 'mt-2 text-sm text-slate-300'),
          node('p', `Persona score: ${score(person.score)}`, 'mt-2 text-xs text-slate-400'));
        if (profile?.role) box.append(node('p', profile.role, 'mt-2 text-xs text-slate-400'));
        $('personas').append(box);
      }
      if (!report.persona_feedback.length) empty('personas', 'No audience feedback was recorded.');
    },
  };
}
