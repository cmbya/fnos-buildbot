(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const status = text => { get('status').textContent = text; };
  let current;
  let busy = false;
  const valid = p => p === '/path' || /^\/[A-Za-z0-9_-]{16,128}$/.test(p);
  try { get('connect').value = localStorage.getItem('fnos-substore-api-prefix') || ''; } catch (_) { /* optional */ }
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
    if (!valid(prefix)) throw new Error('API 路径格式不正确');
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
      status('设置已读取。管理密钥仅保存在当前输入框，离开页面即丢弃。');
    } catch (error) { status(error.message); }
  };
  get('generate').onclick = () => {
    get('prefix').value = '/' + Array.from(crypto.getRandomValues(new Uint8Array(24)), x => x.toString(16).padStart(2, '0')).join('');
    status('随机路径已生成，请自行安全记录后保存。');
  };
  get('save').onclick = async () => {
    if (busy || !current) return;
    const next = { apiPrefix: get('prefix').value.trim(), allowedOrigins: get('origins').value.split(/[,\n]/).map(x => x.trim()).filter(Boolean) };
    if (next.apiPrefix !== current.apiPrefix && !get('confirm').checked) { status('请确认已记录新路径及旧链接影响'); return; }
    busy = true; get('save').disabled = true;
    try {
      current = await request('PUT', next);
      // Remember the durable result before checking connectivity: removing the
      // current origin may intentionally prevent the subsequent verification.
      localStorage.setItem('fnos-substore-api-prefix', current.apiPrefix);
      get('connect').value = current.apiPrefix;
      get('confirm').checked = false;
      status('服务器配置已保存并立即生效，无需重启。旧 API 路径已失效。若刚移除了当前来源，请改用内网入口。');
    } catch (error) { status(error.message + '。如网络中断导致保存结果不明，请重新读取设置核对，不要继续使用旧路径。'); }
    finally { busy = false; get('save').disabled = false; }
  };
})();
