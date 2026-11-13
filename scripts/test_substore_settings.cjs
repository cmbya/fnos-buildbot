'use strict';
// Run with an existing Node >=24: node --test scripts/test_substore_settings.cjs
// Source only: not executed during authoring; no packages/network needed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { once } = require('node:events');
const { loadState, createGateway, validatePrefix, validateOrigins } = require('../apps/substore/app/runtime/settings.cjs');
const P1 = '/abcdefghijklmnop01';
const P2 = '/abcdefghijklmnop02';

test('strict settings input, no wildcard or shell/path injection', () => {
  for (const bad of ['/path', '/', '/short', '/../../etc/passwd', '/abc;echo hello', '/abcdefghijklmnop?', '/_fnosabcdefghijklm']) assert.throws(() => validatePrefix(bad));
  assert.equal(validatePrefix(P1), P1);
  for (const bad of ['*', 'example.com', 'https://example.com/', 'https://a:b@example.com', 'https://example.com/path', 'https://example.com?secret=1']) assert.throws(() => validateOrigins([bad]));
  assert.deepEqual(validateOrigins(['https://sub.example.com', 'https://sub.example.com']), ['https://sub.example.com']);
});

test('persistent changes, failed writes preserve old state, exact origins and private key', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'substore-settings-test-'));
  try {
    const s = loadState(dir, 'http://127.0.0.1:21678');
    assert.equal(s.config.apiPrefix, '/path');
    const key = fs.readFileSync(path.join(dir, 'fnos-settings.key'), 'utf8').trim();
    assert.equal(fs.statSync(path.join(dir, 'fnos-settings.key')).mode & 0o777, 0o600);
    assert.equal(s.authenticate('Bearer ' + key), true);
    assert.equal(s.authenticate('Bearer wrong'), false);
    s.update({ apiPrefix: P1, allowedOrigins: ['https://sub.example.com'] });
    assert.equal(s.allowed('http://127.0.0.1:21678'), true);
    assert.equal(s.allowed('https://sub.example.com'), true);
    assert.equal(s.allowed('https://sub.example.com.evil.test'), false);
    assert.throws(() => s.update({ apiPrefix: '/bad', allowedOrigins: [] }));
    assert.equal(s.config.apiPrefix, P1);
    const filename = path.join(dir, 'fnos-server-settings.json');
    const backup = filename + '.test-backup';
    fs.renameSync(filename, backup);
    fs.mkdirSync(filename); // Deterministic rename failure, even when tests run as root.
    assert.throws(() => s.update({ apiPrefix: P2, allowedOrigins: [] }));
    assert.equal(s.config.apiPrefix, P1);
    fs.rmdirSync(filename); fs.renameSync(backup, filename);
    s.update({ apiPrefix: P2, allowedOrigins: [] });
    const restored = loadState(dir, 'http://127.0.0.1:21678');
    assert.equal(restored.config.apiPrefix, P2);
    assert.equal(restored.allowed('https://sub.example.com'), false);
    assert.equal(restored.authenticate('Bearer ' + key), true);
    fs.writeFileSync(filename, '{broken');
    assert.throws(() => loadState(dir, '')); // Never silently reopen /path.
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('HTTP: authorization, CORS, repeat rotation, old paths, health and no path disclosure', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'substore-gateway-test-'));
  const s = loadState(dir, 'http://127.0.0.1:21678');
  const calls = [];
  const server = http.createServer(createGateway((req, res) => {
    calls.push({ url: req.url, origin: req.headers.origin });
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ status: 'success', url: req.url }));
  }, s));
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const port = server.address().port;
  const key = fs.readFileSync(path.join(dir, 'fnos-settings.key'), 'utf8').trim();
  const origin = 'http://127.0.0.1:' + port;
  async function request(route, method = 'GET', headers = {}, data) {
    return new Promise((resolve, reject) => {
      const req = http.request({ host: '127.0.0.1', port, path: route, method, headers }, res => {
        let body = ''; res.on('data', c => { body += c; }); res.on('end', () => resolve({ status: res.statusCode, body, headers: res.headers }));
      });
      req.on('error', reject); req.end(data === undefined ? undefined : JSON.stringify(data));
    });
  }
  const auth = { Authorization: 'Bearer ' + key, Origin: origin, 'Content-Type': 'application/json' };
  try {
    assert.equal((await request('/path/api/utils/env')).status, 200);
    assert.equal((await request('/path/api/utils/env', 'GET', { Origin: 'https://sub.example.com' })).status, 403);
    assert.equal((await request('/_fnos/config')).status, 403);
    assert.equal((await request('/_fnos/config', 'PUT', { ...auth, Origin: 'https://evil.example' }, { apiPrefix: P1, allowedOrigins: [] })).status, 403);
    const saved = await request('/_fnos/config', 'PUT', auth, { apiPrefix: P1, allowedOrigins: ['https://sub.example.com'] });
    assert.equal(saved.status, 200);
    assert.equal(saved.headers['cache-control'], 'no-store');
    assert.equal((await request('/path/api/utils/env')).status, 404);
    assert.equal((await request('/api/utils/env')).status, 404);
    assert.equal((await request('/%70ath/api/utils/env')).status, 404);
    assert.equal((await request(P1 + '/api/utils/env', 'GET', { Origin: 'https://sub.example.com' })).status, 200);
    assert.deepEqual(calls.at(-1), { url: '/path/api/utils/env', origin: undefined });
    assert.equal((await request(P1 + '/api/utils/env', 'GET', { Origin: 'https://evil.example' })).status, 403);
    assert.equal((await request(P1 + '/api/utils/env', 'OPTIONS', { Origin: 'https://sub.example.com' })).status, 204);
    assert.equal((await request('/_fnos/health')).status, 403);
    assert.equal((await request('/_fnos/health', 'GET', { Authorization: 'Bearer ' + key })).status, 200);
    assert.equal((await request('/_fnos/config', 'PUT', auth, { apiPrefix: P2, allowedOrigins: [] })).status, 200);
    assert.equal((await request(P1 + '/api/utils/env')).status, 404);
    assert.equal((await request(P1)).status, 404);
    assert.equal((await request(P2 + '/api/utils/env')).status, 200);
    assert.equal((await request('/path/../api/utils/env')).status, 400);
    const publicPage = await request('/_fnos/settings');
    assert.equal(publicPage.status, 200);
    assert.equal(publicPage.body.includes(P2), false);
    assert.equal(publicPage.body.includes(key), false);
    assert.equal((await request('/_fnos/client.js')).body.includes(P2), false);
    assert.equal((await request('/share/sub/example?token=test')).status, 200);
    assert.equal(calls.at(-1).url, '/share/sub/example?token=test');
  } finally { await new Promise(resolve => server.close(resolve)); fs.rmSync(dir, { recursive: true, force: true }); }
});
