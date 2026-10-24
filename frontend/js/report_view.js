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
  const card = () => node('article', '', 'report-card');
  const empty = (id, message, tag = 'p') => $(id).append(node(tag, message, 'report-muted'));
  function quote(parent, value) {
    if (value) parent.append(node('blockquote', `“${value}”`, 'report-quote'));
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
      $('session-label').textContent = `Session ${report.session_id}${people.size ? ` · ${people.size} guests` : ''}`;
      $('overall-score').textContent = score(report.overall_score);
      $('report-mode').hidden = !mock;
      for (const [key, value] of Object.entries(report.dimensions)) {
        const tile = card(); tile.className += ' report-dimension';
        tile.append(node('h3', label(key)),
          node('p', score(value), `report-score${value == null ? ' unassessed' : ''}`));
        $('dimensions').append(tile);
      }
      if (!Object.keys(report.dimensions).length) empty('dimensions', 'No dimension scores were recorded.');
      for (const [key, value] of Object.entries(report.metrics)) {
        $('metrics').append(node('li', `${label(key)}: ${value == null ? 'Not measured' : value}`,
          'report-metric'));
      }
      if (!Object.keys(report.metrics).length) empty('metrics', 'No metrics were recorded.', 'li');
      for (const caveat of report.metric_caveats) $('caveats').append(node('li', caveat));
      if (!report.metric_caveats.length) empty('caveats', 'Unmeasured values are labelled. Recognition-dependent metrics are approximate.', 'li');
      for (const item of report.curveballs) {
        const box = card(), skipped = item.resolution === 'skipped', recovery = skipped ? null : item.recovery;
        box.append(node('h3', label(item.kind), 'report-title-small'),
          node('p', `${time(item.at_ms)} · ${human(item.resolution)}`, 'report-small mono'));
        if (skipped) {
          box.append(node('p', 'Skipped — no penalty. Recovery was not scored.', 'report-positive'));
        } else {
          box.append(node('p', `Recovery score: ${score(recovery?.score)}`, 'report-recovery-score'),
            node('p', `Speech resumed after: ${recovery?.resume_after_ms == null ? 'Not measured'
              : `${(recovery.resume_after_ms / 1000).toFixed(1)} s`}`, 'report-detail'));
          if (recovery?.notes) box.append(node('p', recovery.notes, 'report-small'));
          quote(box, recovery?.evidence);
          if (recovery?.suggestion) box.append(node('p', recovery.suggestion, 'report-positive'));
        }
        $('curveballs').append(box);
      }
      if (!report.curveballs.length) empty('curveballs', 'No curveball fired this session.');
      for (const moment of [...report.key_moments].sort((a, b) => a.at_ms - b.at_ms)) {
        const row = node('li', '', 'report-moment');
        const speaker = moment.persona_id ? people.get(moment.persona_id)?.name || label(moment.persona_id) : null;
        const accent = ['question', 'curveball'].includes(moment.type) ? ` ${moment.type}` : '';
        row.append(node('span', time(moment.at_ms), 'report-time'),
          node('span', human(moment.type), `report-badge${accent}`),
          node('span', `${speaker ? `${speaker}: ` : ''}${moment.summary}`));
        $('moments').append(row);
      }
      if (!report.key_moments.length) empty('moments', 'No key moments were recorded.', 'li');
      for (const strength of report.strengths) $('strengths').append(node('li', strength, 'report-detail'));
      if (!report.strengths.length) empty('strengths', 'No strengths were recorded.', 'li');
      for (const item of report.improvements) {
        const box = card(); box.append(node('h3', item.observation, 'report-title-small'));
        quote(box, item.evidence); box.append(node('p', item.suggestion, 'report-positive'));
        $('improvements').append(box);
      }
      if (!report.improvements.length) empty('improvements', 'No specific improvements were recorded.');
      for (const person of report.persona_feedback) {
        const box = card();
        const profile = people.get(person.persona_id);
        box.append(node('h3', profile?.name || label(person.persona_id), 'report-title-small'),
          node('p', person.comment, 'report-detail'),
          node('p', `Persona score: ${score(person.score)}`, 'report-small'));
        if (profile?.role) box.append(node('p', profile.role, 'report-small'));
        $('personas').append(box);
      }
      if (!report.persona_feedback.length) empty('personas', 'No audience feedback was recorded.');
    },
  };
}
