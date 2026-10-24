// Static fictional cast from feat/voice-room 4b508ee. No avatar/video requests.
// Match pictures to the existing voice adapter, without changing a tested voice.
const rosterVoices = { moderator: 'eleanor', vc: 'marcus', student: 'chloe', professor: 'oliver', mentor: 'nora' };
const presetVoices = new Set(['default', 'chloe', 'eleanor', 'jake', 'marcus', 'nora', 'oliver']);
const cast = {
  mei: 'hiring_manager--mei.jpg', layla: 'vc--layla.jpg',
  dev: 'methods--dev.jpg', mr_tan: 'professor--mr_tan.jpg',
  hannah: 'mentor--hannah.jpg', ava: 'recruiter--ava.jpg',
  finn: 'senior_eng--finn.jpg', ray: 'customer--ray.jpg',
  ken: 'student--ken.jpg', leo: 'classmate--leo.jpg',
};
const choices = {
  eleanor: ['mei', 'layla'], marcus: ['dev', 'mr_tan'], chloe: ['hannah', 'ava'],
  oliver: ['finn', 'ray'], jake: ['ken', 'leo'], nora: ['ava', 'hannah'],
  default: ['ray', 'leo'],
};

// Voice lookup mirrors HiggsVoice.start_voice_session; this helper is visual only.
export function assignedVoice(person, index = 0) {
  return presetVoices.has(person.voice_id) ? person.voice_id
    : rosterVoices[person.id] || ['marcus', 'chloe', 'oliver'][index % 3];
}

export function assignPortraits(personas = []) {
  const used = new Set(), portraits = new Map();
  const people = [{ id: 'moderator', voice_id: 'eleanor' }, ...personas];
  people.forEach((person, i) => {
    const voice = assignedVoice(person, Math.max(0, i - 1));
    const character = [...choices[voice], ...Object.keys(cast)].find((id) => !used.has(id));
    if (!character) return;
    used.add(character);
    portraits.set(person.id, { character, src: `/demo/faces/${cast[character]}` });
  });
  return portraits;
}
