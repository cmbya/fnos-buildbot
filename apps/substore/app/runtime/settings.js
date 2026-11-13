(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const status = text => { get('status').textContent = text; };
  let current;
  let busy = false;
  const valid = p => p === '/path' || /^\/[A-Za-z0-9_-]{4,128}$/.test(p);
  try { get('connect').value = localStorage.getItem('fnos-substore-api-prefix') || ''; } catch (_) { /* optional */ }
  async function copyPath(id) {
    const field = get(id);
    const value = field.value.trim();
    if (!value) { status('请先填写或生成路径'); return; }
    if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try { await navigator.clipboard.writeText(value); status('路径已复制，请妥善保存；不要分享截图或剪贴板内容'); return; }
      catch (_) { /* Clipboard permission denied; fall back to selected plaintext. */ }
    }
    field.focus();
    field.select();
    field.setSelectionRange(0, field.value.length);
    try {
      if (document.execCommand('copy')) { status('路径已复制，请妥善保存'); return; }
    } catch (_) { /* HTTP LAN and mobile browsers may not allow programmatic copy. */ }
    status('浏览器未允许自动复制，已选中明文路径，请按 Ctrl+C 或长按复制');
  }
  get('prefixCopy').onclick = () => copyPath('prefix');
  get('connectCopy').onclick = () => copyPath('connect');
  async function request(method, body) {
    const response = await fetch('/_fnos/config', {
      method, cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer',
      headers: { Authorization: 'Bearer ' + get('key').value.trim(), 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '请求失败');
    return result;
  }
  async function connect(prefix) {
    if (!valid(prefix)) throw new Error('API 路径格式不正确：/ 后需要 4–128 个字母、数字、下划线或连字符');
    const response = await fetch(prefix + '/api/utils/env', { cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer' });
    const result = await response.json();
    if (!response.ok || result.status !== 'success') throw new Error('路径无法连接；若提示 CORS，请从允许的内网地址进入服务器设置');
    localStorage.setItem('fnos-substore-api-prefix', prefix);
  }
  get('connectButton').onclick = async () => {
    try { await connect(get('connect').value.trim()); location.replace('/'); }
    catch (error) { status(error.message); }
  };
  get('load').onclick = async () => {
    try {
      current = await request('GET');
      get('prefix').value = current.apiPrefix;
      get('origins').value = current.allowedOrigins.join('\n');
      get('editor').hidden = false;
      status('设置已读取，路径以明文显示。管理密钥仅保存在当前输入框，离开页面即丢弃。');
    } catch (error) { status(error.message); }
  };
  get('generate').onclick = () => {
    get('prefix').value = '/' + Array.from(crypto.getRandomValues(new Uint8Array(24)), x => x.toString(16).padStart(2, '0')).join('');
    get('prefix').focus();
    get('prefix').select();
    status('随机路径已在输入框显示，尚未保存。可点击“复制路径”，安全记录后再保存。');
  };
  get('save').onclick = async () => {
    if (busy || !current) return;
    const next = { apiPrefix: get('prefix').value.trim(), allowedOrigins: get('origins').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean) };
    if (!valid(next.apiPrefix)) { status('API 路径格式不正确：/ 后需要 4–128 个字母、数字、下划线或连字符'); return; }
    if (next.apiPrefix !== current.apiPrefix && !get('confirm').checked) { status('请确认已记录新路径及旧链接影响'); return; }
    busy = true; get('save').disabled = true;
    try {
      current = await request('PUT', next);
      // Remember durable result before connectivity checks; origin removal may be intentional.
      localStorage.setItem('fnos-substore-api-prefix', current.apiPrefix);
      get('connect').value = current.apiPrefix;
      get('confirm').checked = false;
      status('服务器配置已保存并立即生效，无需重启。旧 API 路径已失效。若刚移除了当前来源，请改用内网入口。');
    } catch (error) { status(error.message + '。如网络中断导致保存结果不明，请重新读取设置核对，不要继续使用旧路径。'); }
    finally { busy = false; get('save').disabled = false; }
  };
})();
