'use strict';
// fnOS adaptation, independent of the upstream release bundle. No dependencies.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const http = require('node:http');

const CONTROL = '/_fnos';
const INTERNAL = '/path';
const SENTINEL = '/__fnos_backend_not_configured__';
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const matches = (pathname, prefix) => pathname === prefix || pathname.startsWith(prefix + '/');

function validatePrefix(value, legacy = false) {
  if (legacy && value === INTERNAL) return value;
  if (typeof value !== 'string' || !/^\/[A-Za-z0-9_-]{16,128}$/.test(value) ||
      value.startsWith('/_fnos') || value === SENTINEL) {
    throw new Error('API 路径必须为 / 加 16–128 个字母、数字、下划线或连字符；不允许使用 /path 或系统保留路径');
  }
  return value;
}
function validateOrigins(value) {
  if (!Array.isArray(value) || value.length > 32) throw new Error('最多允许 32 个明确来源');
  return [...new Set(value.map(item => {
    if (typeof item !== 'string') throw new Error('来源必须为字符串');
    const text = item.trim();
    let url;
    try { url = new URL(text); } catch { throw new Error('来源必须包含 http:// 或 https://'); }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
        url.search || url.hash || url.pathname !== '/' || text.includes('*') || text.endsWith('/')) {
      throw new Error('来源只能包含协议、主机和必要端口，不允许路径、通配符或末尾 /');
    }
    return url.origin;
  }))];
}
function atomicWrite(filename, data) {
  const temporary = filename + '.' + crypto.randomBytes(8).toString('hex') + '.tmp';
  try {
    const fd = fs.openSync(temporary, 'wx', 0o600);
    try { fs.writeFileSync(fd, data); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, filename);
  } finally { try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; } }
}
function loadState(directory, baseOrigins) {
  fs.mkdirSync(directory, { recursive: true });
  const filename = path.join(directory, 'fnos-server-settings.json');
  const keyfile = path.join(directory, 'fnos-settings.key');
  let key;
  try { key = fs.readFileSync(keyfile, 'utf8').trim(); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    const generated = crypto.randomBytes(32).toString('hex');
    try { fs.writeFileSync(keyfile, generated + '\n', { flag: 'wx', mode: 0o600 }); }
    catch (race) { if (race.code !== 'EEXIST') throw race; }
    key = fs.readFileSync(keyfile, 'utf8').trim();
  }
  if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('Invalid fnOS settings key; refusing to start');
  fs.chmodSync(keyfile, 0o600);
  const base = new Set((baseOrigins || '').split(',').map(x => x.trim()).filter(Boolean));
  if (base.has('*')) throw new Error('Wildcard CORS override is incompatible with protected server settings');
  let config = { version: 1, apiPrefix: INTERNAL, allowedOrigins: [] };
  try {
    const stored = JSON.parse(fs.readFileSync(filename, 'utf8'));
    if (stored.version !== 1) throw new Error('Unsupported settings version');
    config = { version: 1, apiPrefix: validatePrefix(stored.apiPrefix, true), allowedOrigins: validateOrigins(stored.allowedOrigins) };
    fs.chmodSync(filename, 0o600);
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  return {
    get config() { return config; },
    authenticate(authorization) {
      if (typeof authorization !== 'string' || !authorization.startsWith('Bearer ')) return false;
      const candidate = Buffer.from(authorization.slice(7));
      const expected = Buffer.from(key);
      return candidate.length === expected.length && crypto.timingSafeEqual(candidate, expected);
    },
    allowed(origin) { return !origin || base.has(origin) || config.allowedOrigins.includes(origin); },
    update(input) {
      if (!input || typeof input !== 'object' || Array.isArray(input) ||
          Object.keys(input).some(k => !['apiPrefix', 'allowedOrigins'].includes(k)) ||
          !own(input, 'apiPrefix') || !own(input, 'allowedOrigins')) throw new Error('Invalid settings payload');
      const next = { version: 1, apiPrefix: validatePrefix(input.apiPrefix, input.apiPrefix === config.apiPrefix), allowedOrigins: validateOrigins(input.allowedOrigins) };
      atomicWrite(filename, JSON.stringify(next, null, 2) + '\n');
      config = next; // Switch only after the durable write succeeds. No old route alias.
      return config;
    },
  };
}
function send(res, status, value, type = 'application/json; charset=utf-8') {
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' });
  res.end(type.startsWith('application/json') ? JSON.stringify(value) : value);
}
function sameControlOrigin(req) {
  if (!req.headers.origin) return !['cross-site'].includes(req.headers['sec-fetch-site']);
  try { return new URL(req.headers.origin).host === req.headers.host; } catch { return false; }
}
function createGateway(upstream, state, assets = __dirname) {
  return (req, res) => {
    const raw = req.url || '/';
    const pathname = raw.split('?')[0];
    if (!pathname.startsWith('/') || pathname.includes('\\') || pathname.startsWith('//') ||
        pathname.split('/').some(part => part === '.' || part === '..')) {
      send(res, 400, { error: 'Invalid request target' }); return;
    }
    if (pathname === CONTROL + '/client.js' && req.method === 'GET') {
      send(res, 200, fs.readFileSync(path.join(assets, 'client.js'), 'utf8'), 'application/javascript; charset=utf-8'); return;
    }
    if (pathname === CONTROL + '/settings' && req.method === 'GET') {
      res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
      send(res, 200, fs.readFileSync(path.join(assets, 'settings.html'), 'utf8'), 'text/html; charset=utf-8'); return;
    }
    if (pathname === CONTROL + '/settings.js' && req.method === 'GET') {
      send(res, 200, fs.readFileSync(path.join(assets, 'settings.js'), 'utf8'), 'application/javascript; charset=utf-8'); return;
    }
    if (pathname === CONTROL + '/health') {
      if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress) || !state.authenticate(req.headers.authorization)) {
        send(res, 403, { error: 'Forbidden' }); return;
      }
      req.url = INTERNAL + '/api/utils/env';
      delete req.headers.origin;
      upstream(req, res); return;
    }
    if (pathname === CONTROL + '/config') {
      if (!sameControlOrigin(req) || !state.authenticate(req.headers.authorization)) { send(res, 403, { error: '管理密钥错误或请求来源不符' }); return; }
      if (req.method === 'GET') { send(res, 200, state.config); return; }
      if (req.method !== 'PUT') { send(res, 405, { error: 'Method not allowed' }); return; }
      if (!(req.headers['content-type'] || '').startsWith('application/json')) { send(res, 415, { error: 'JSON required' }); return; }
      const chunks = [];
      let size = 0;
      let ended = false;
      req.on('data', chunk => {
        size += chunk.length;
        if (ended) return;
        if (size > 8192) { ended = true; send(res, 413, { error: 'Payload too large' }); return; }
        chunks.push(chunk);
      });
      req.on('end', () => {
        if (ended) return;
        try { send(res, 200, state.update(JSON.parse(Buffer.concat(chunks).toString('utf8')))); }
        catch (error) {
          const validation = !error.code;
          send(res, validation ? 400 : 500, { error: validation ? error.message : '保存失败，原配置保留；检查应用数据目录权限' });
        }
      });
      req.on('error', () => { if (!res.writableEnded) send(res, 400, { error: 'Request interrupted' }); });
      return;
    }
    if (matches(pathname, CONTROL)) { send(res, 404, { error: 'Not found' }); return; }
    const origin = req.headers.origin;
    if (!state.allowed(origin)) { send(res, 403, 'CORS origin not allowed', 'text/plain; charset=utf-8'); return; }
    if (origin) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
      res.setHeader('Access-Control-Allow-Methods', 'POST,GET,OPTIONS,PATCH,PUT,DELETE');
      res.setHeader('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept');
      // Remove Origin only AFTER our exact persistent policy passed. Upstream
      // captures its own static CORS policy at startup; the adapter owns updates.
      delete req.headers.origin;
    }
    if (origin && req.method === 'OPTIONS') { send(res, 204, '', 'text/plain'); return; }
    const prefix = state.config.apiPrefix;
    if (pathname.includes('%')) {
      let decoded;
      try { decoded = decodeURIComponent(pathname); } catch { send(res, 400, { error: 'Invalid encoding' }); return; }
      if (matches(decoded, INTERNAL) || matches(decoded, prefix) || matches(decoded, CONTROL) ||
          decoded.includes('..') || /^\/[A-Za-z0-9_-]{16,128}(\/|$)/.test(decoded)) {
        send(res, 404, { error: 'Not found' }); return;
      }
    }
    if (matches(pathname, prefix)) {
      req.url = INTERNAL + raw.slice(prefix.length);
      upstream(req, res); return;
    }
    // Retired random prefixes must not fall through to SPA index.html with 200.
    // Reserve the namespace of configurable prefixes, including after restart.
    if (matches(pathname, INTERNAL) || matches(pathname, SENTINEL) ||
        /^\/(api|download)(\/|$)/.test(pathname) ||
        /^\/[A-Za-z0-9_-]{16,128}(\/|$)/.test(pathname)) {
      send(res, 404, { error: 'Not found' }); return;
    }
    upstream(req, res); // Public frontend; /share keeps upstream token semantics.
  };
}
function install() {
  const directory = process.env.SUB_STORE_DATA_BASE_PATH;
  if (!directory) throw new Error('SUB_STORE_DATA_BASE_PATH required');
  const state = loadState(directory, process.env.SUB_STORE_CORS_ALLOWED_ORIGINS);
  process.env.SUB_STORE_FRONTEND_BACKEND_PATH = INTERNAL;
  const originalEmit = http.Server.prototype.emit;
  const gateways = new WeakMap();
  http.Server.prototype.emit = function(event, ...args) {
    if (event !== 'request') return originalEmit.call(this, event, ...args);
    if (!gateways.has(this)) gateways.set(this, createGateway((req, res) => originalEmit.call(this, 'request', req, res), state));
    gateways.get(this)(...args);
    return true;
  };
}
module.exports = { validatePrefix, validateOrigins, atomicWrite, loadState, createGateway, matches, install };
if (process.env.SUBSTORE_FNOS_SETTINGS === '1') install();
