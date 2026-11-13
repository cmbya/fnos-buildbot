'use strict';
// VM browser stubs use Node built-ins only. Added, NOT RUN by user request.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const directory = path.join(__dirname, '../apps/substore/app/runtime');
function createUI({ secure = false, clipboard, legacyCopy = false } = {}) {
  const fields = {};
  for (const id of ['status', 'connect', 'key', 'prefix', 'origins', 'confirm', 'save', 'load', 'editor', 'generate', 'connectButton', 'prefixCopy', 'connectCopy']) {
    fields[id] = { value: '', checked: false, textContent: '', focus() { this.focused = true; }, select() { this.selected = true; }, setSelectionRange(start, end) { this.range = [start, end]; } };
  }
  const storage = new Map();
  const requests = [];
  const context = {
    document: { getElementById: id => fields[id], execCommand: () => legacyCopy },
    window: { isSecureContext: secure }, navigator: { clipboard },
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    location: { replace: value => { context.redirected = value; } },
    crypto: { getRandomValues: array => { array.fill(10); return array; } },
    fetch: async (url, init = {}) => {
      requests.push({ url, init });
      return { ok: true, json: async () => url === '/_fnos/config' ?
        (init.method === 'PUT' ? JSON.parse(init.body) : { version: 1, apiPrefix: '/path', allowedOrigins: [] }) : { status: 'success' } };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'settings.js'), 'utf8'), context);
  return { fields, requests, storage, context };
}
test('paths plaintext, key hidden, copy buttons present', () => {
  const html = fs.readFileSync(path.join(directory, 'settings.html'), 'utf8');
  assert.match(html, /id="prefix" type="text"/);
  assert.match(html, /id="connect" type="text"/);
  assert.match(html, /id="key" type="password"/);
  assert.match(html, /id="prefixCopy"/);
  assert.match(html, /id="connectCopy"/);
  assert.match(html, /4–128/);
});
test('HTTPS clipboard copies path but never key', async () => {
  const copied = [];
  const ui = createUI({ secure: true, clipboard: { writeText: async value => copied.push(value) } });
  ui.fields.key.value = 'private-key-not-for-clipboard';
  ui.fields.prefix.value = '/aB12';
  await ui.fields.prefixCopy.onclick();
  assert.deepEqual(copied, ['/aB12']);
  assert.match(ui.fields.status.textContent, /已复制/);
});
test('HTTP fallback succeeds or selects plaintext on failure', async () => {
  const success = createUI({ legacyCopy: true });
  success.fields.prefix.value = '/aB12'; await success.fields.prefixCopy.onclick();
  assert.match(success.fields.status.textContent, /已复制/);
  const failed = createUI({ secure: true, clipboard: { writeText: async () => { throw Error('denied'); } } });
  failed.fields.connect.value = '/cD34'; await failed.fields.connectCopy.onclick();
  assert.equal(failed.fields.connect.selected, true);
  assert.match(failed.fields.status.textContent, /Ctrl\+C/);
});
test('generate does not save; four characters save and reconnect, three reject', async () => {
  const ui = createUI();
  ui.fields.generate.onclick();
  assert.equal(ui.fields.prefix.value.length, 49);
  assert.equal(ui.requests.length, 0);
  await ui.fields.load.onclick();
  ui.fields.prefix.value = '/abc'; ui.fields.confirm.checked = true;
  await ui.fields.save.onclick();
  assert.equal(ui.requests.filter(r => r.init.method === 'PUT').length, 0);
  ui.fields.prefix.value = '/aB12';
  await ui.fields.save.onclick();
  assert.equal(ui.requests.filter(r => r.init.method === 'PUT').length, 1);
  assert.equal(ui.storage.get('fnos-substore-api-prefix'), '/aB12');
  ui.fields.connect.value = '/cD34';
  await ui.fields.connectButton.onclick();
  assert.equal(ui.context.redirected, '/');
});
test('client bootstrap rewrites a stored four-character prefix', () => {
  const calls = [];
  function XHR() {}
  XHR.prototype.open = function(...args) { calls.push(args); };
  const context = {
    localStorage: { getItem: () => '/aB12' },
    location: { href: 'https://sub.example.com/subs', origin: 'https://sub.example.com' },
    URL, Request,
    XMLHttpRequest: XHR,
    window: { fetch: async (...args) => { calls.push(args); } },
    document: { readyState: 'loading', addEventListener() {} },
  };
  vm.runInNewContext(fs.readFileSync(path.join(directory, 'client.js'), 'utf8'), context);
  const xhr = new context.XMLHttpRequest(); xhr.open('GET', '/path/api/utils/env');
  assert.equal(calls[0][1], 'https://sub.example.com/aB12/api/utils/env');
});
