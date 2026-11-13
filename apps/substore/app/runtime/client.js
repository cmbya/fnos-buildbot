/* fnOS adapter: no secret path is embedded in public frontend assets. */
(() => {
  'use strict';
  const key = 'fnos-substore-api-prefix';
  let prefix;
  try { prefix = localStorage.getItem(key); } catch (_) { /* storage disabled */ }
  if (prefix && !/^\/[A-Za-z0-9_-]{16,128}$/.test(prefix)) prefix = null;
  const legacy = '/path';
  function rewrite(input) {
    const url = new URL(input, location.href);
    if (url.origin === location.origin && (url.pathname === legacy || url.pathname.startsWith(legacy + '/')) && prefix) {
      url.pathname = prefix + url.pathname.slice(legacy.length);
    }
    return url.href;
  }
  // Covers upstream frontend default /path as well as API / download links.
  const fetchOriginal = window.fetch.bind(window);
  window.fetch = function(input, init) {
    const mapped = rewrite(input instanceof Request ? input.url : input);
    if (input instanceof Request) return fetchOriginal(mapped === input.url ? input : new Request(mapped, input), init);
    return fetchOriginal(mapped, init);
  };
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) { return open.call(this, method, rewrite(url), ...rest); };
  document.addEventListener('click', event => {
    const anchor = event.target.closest && event.target.closest('a[href]');
    if (!anchor) return;
    try {
      const rewritten = rewrite(anchor.href);
      if (rewritten !== anchor.href) anchor.href = rewritten;
    } catch (_) { /* non-HTTP link */ }
  }, true);
  function addSettingsLink() {
    const link = document.createElement('a');
    link.href = '/_fnos/settings';
    link.textContent = '服务器设置 / 连接后端';
    link.title = '配置 API 路径、额外来源，或为当前浏览器填写已有路径';
    link.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483646;padding:8px 12px;background:#17394f;color:white;border-radius:8px;font:13px sans-serif;text-decoration:none';
    document.body.append(link);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addSettingsLink, { once: true });
  else addSettingsLink();
})();
