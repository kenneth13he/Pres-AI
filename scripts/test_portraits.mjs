import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import test from 'node:test';
import { assignPortraits, assignedVoice } from '../frontend/js/portraits.js';

test('tested room voices select distinct static portraits and retain custom voice overrides', async () => {
  const people = [{ id: 'vc' }, { id: 'student' }, { id: 'professor' }];
  assert.deepEqual(people.map(assignedVoice), ['marcus', 'chloe', 'oliver']);
  assert.equal(assignedVoice({ id: 'custom_1', voice_id: 'jake' }, 2), 'jake');
  assert.equal(assignedVoice({ id: 'custom_1', voice_id: 'unavailable' }, 1), 'chloe');
  const portraits = assignPortraits(people);
  assert.deepEqual([...portraits.keys()], ['moderator', 'vc', 'student', 'professor']);
  assert.equal(new Set([...portraits.values()].map((p) => p.character)).size, 4);
  for (const { src } of portraits.values()) {
    assert.match(src, /^\/demo\/faces\/[a-z_]+--[a-z_]+\.jpg$/);
    const path = new URL(`..${src}`, import.meta.url);
    await access(path);
    assert.equal((await readFile(path)).subarray(0, 2).toString('hex'), 'ffd8');
  }
});

test('custom audience never repeats a face when several seats request the same voice', () => {
  const people = [0, 1, 2].map((i) => ({ id: `custom_${i}`, voice_id: 'eleanor' }));
  const first = assignPortraits(people), second = assignPortraits(people);
  assert.deepEqual([...first], [...second]);
  assert.equal(new Set([...first.values()].map((p) => p.character)).size, 4);
  assert.equal(first.get('moderator').character, 'mei');
  assert.equal(first.get('custom_0').character, 'layla');
  assert.equal(assignPortraits().size, 1);
});
