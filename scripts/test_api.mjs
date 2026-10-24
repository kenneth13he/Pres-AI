// Real REST client error decoding with fake HTTP responses; no network or browser.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = (await readFile(new URL('../frontend/js/api.js', import.meta.url), 'utf8'))
  .replace(/\bexport\s+/g, '');
function client(response) {
  const context = { URLSearchParams, location: { search: '' }, fetch: async () => response };
  vm.runInNewContext(`${source}\nglobalThis.api = { getReport, getSession };`, context);
  return context.api;
}

test('REST errors expose preparing status/code and only the explicit safe detail message', async () => {
  const api = client({ ok: false, status: 409, json: async () => ({ detail: {
    code: 'report_preparing', message: 'Your session has ended. Preparing feedback.',
    internal: 'private vendor body',
  }, debug: 'secret token' }) });
  await assert.rejects(api.getReport('unit'), (error) => {
    assert.equal(error.status, 409); assert.equal(error.code, 'report_preparing');
    assert.match(error.message, /409.*Your session has ended/);
    assert.doesNotMatch(error.message, /private|secret|internal|debug/);
    return true;
  });
});

test('ordinary errors retain HTTP status and non-JSON bodies are never echoed', async () => {
  const unfinished = client({ ok: false, status: 409,
    json: async () => ({ detail: 'session not finished' }) });
  await assert.rejects(unfinished.getReport('unit'), (error) => {
    assert.equal(error.status, 409); assert.equal(error.code, null);
    assert.match(error.message, /session not finished/); return true;
  });
  const invalid = client({ ok: false, status: 502,
    json: async () => { throw new Error('private HTML body'); },
    text: async () => { throw new Error('Must not read arbitrary response bodies.'); },
  });
  await assert.rejects(invalid.getSession('unit'), (error) => {
    assert.equal(error.status, 502); assert.equal(error.code, null);
    assert.match(error.message, /502/); assert.doesNotMatch(error.message, /private|HTML/); return true;
  });
});
