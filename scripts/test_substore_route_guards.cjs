'use strict';
// Source-only regression tests. Not executed in this change by user request.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { reservedRoute, matches } = require('../apps/substore/app/runtime/settings.cjs');
test('upstream prefix lookalikes and retired random paths stay reserved', () => {
  for (const route of ['/path', '/path/api/subs', '/pathanything/api/subs', '/pathology/api/subs', '/_fnossecret/config', '/abcdefghijklmnop01', '/abcdefghijklmnop01/api/utils/env', '/api/subs', '/download/sub/example']) {
    assert.equal(reservedRoute(route), true, route);
  }
  for (const route of ['/', '/subs', '/assets/main.js', '/share/sub/example', '/settings', '/favicon.ico']) assert.equal(reservedRoute(route), false, route);
  assert.equal(matches('/abcdefghijklmnop01/api/subs', '/abcdefghijklmnop01'), true);
  assert.equal(matches('/abcdefghijklmnop01evil/api/subs', '/abcdefghijklmnop01'), false);
});
