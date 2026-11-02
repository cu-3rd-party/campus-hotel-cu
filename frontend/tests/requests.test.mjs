import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, LatestRequest, requestJSON } from '../src/request.mjs';
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

test('an older search can never replace a later search, even without transport cancellation', async () => {
  const slot = new LatestRequest(), old = deferred(), current = deferred(), results = [];
  const first = slot.run(() => old.promise, value => results.push(value), assert.fail);
  const second = slot.run(() => current.promise, value => results.push(value), assert.fail);
  current.resolve('new'); await second; old.resolve('old'); await first;
  assert.deepEqual(results, ['new']);
});

test('slow room loading does not block people, and unmount cancels publication', async () => {
  const people = new LatestRequest(), rooms = new LatestRequest(), slow = deferred(), result = [];
  const roomJob = rooms.run(() => slow.promise, value => result.push(value), assert.fail);
  await people.run(async () => 'people', value => result.push(value), assert.fail);
  assert.deepEqual(result, ['people']); rooms.cancel(); slow.resolve('rooms'); await roomJob;
  assert.deepEqual(result, ['people']);
});

test('deadline includes JSON decoding and never retries a timed-out write', async () => {
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async (url, options) => { calls++; return { ok: true, status: 200, json: () => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))) }; };
  try {
    await assert.rejects(requestJSON('/api/invites', 'Ошибка', { method: 'POST' }, 8), /проверь результат/);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = original; }
});

test('errors preserve HTTP status so a temporary outage cannot be mistaken for a deleted profile', async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [404, 503]) {
      globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Попробуй позже' }), { status });
      await assert.rejects(requestJSON('/api/profiles/1', 'Ошибка'), error => error instanceof ApiError && error.status === status);
    }
  } finally { globalThis.fetch = original; }
});

test('cancelled requests are not shown as server errors', async () => {
  const controller = new AbortController(), original = globalThis.fetch;
  globalThis.fetch = async (url, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError'))));
  try { const pending = requestJSON('/api/profiles', 'Ошибка', { signal: controller.signal }); controller.abort(); await assert.rejects(pending, error => error.name === 'AbortError'); }
  finally { globalThis.fetch = original; }
});


test('a successful HTTP status with malformed JSON is an actionable error, never a null feed', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('<html>proxy page</html>', { status: 200 });
  try { await assert.rejects(requestJSON('/api/profiles', 'Не удалось загрузить анкеты'), /Не удалось загрузить анкеты/); }
  finally { globalThis.fetch = original; }
});

test('real invite and room actions use the deadline and never repeat a POST', { timeout: 1000 }, async () => {
  const originalFetch = globalThis.fetch, originalTimer = globalThis.setTimeout, originalWindow = globalThis.window;
  let calls = [];
  globalThis.window = {};
  globalThis.setTimeout = (callback, delay, ...args) => delay === 12000 ? originalTimer(callback, 2, ...args) : originalTimer(callback, delay, ...args);
  globalThis.fetch = async (url, options) => {
    calls.push({url, method: options.method, signal: Boolean(options.signal)});
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError'))));
  };
  try {
    const { createGroup, createInvite } = await import('../src/api.js');
    await assert.rejects(createGroup(3, 1), /проверь результат/);
    await assert.rejects(createInvite(1, 2, 3), /проверь результат/);
    assert.deepEqual(calls.map(call => [call.method, call.signal]), [['POST', true], ['POST', true]]);
    assert.equal(calls.length, 2);
  } finally { globalThis.fetch = originalFetch; globalThis.setTimeout = originalTimer; globalThis.window = originalWindow; }
});

test('a WebView with readable storage and exhausted write quota keeps the current profile for this visit', async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null, setItem() { throw Error('quota'); }, removeItem() { throw Error('blocked'); } } });
  try {
    const { writeStored, readStored, removeStored } = await import('../src/storage.mjs');
    writeStored('fixture-profile-id', 42); assert.equal(readStored('fixture-profile-id'), '42');
    removeStored('fixture-profile-id'); assert.equal(readStored('fixture-profile-id'), null);
  } finally { if (original) Object.defineProperty(globalThis, 'localStorage', original); else delete globalThis.localStorage; }
});
