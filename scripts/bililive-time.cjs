// Strict monitor-time semantics retained from fnOS native3, using Beijing time.
exports.allowed = function allowed(range, date = new Date()) {
  if (!Array.isArray(range) || range.length !== 2 || range.some(x => x == null || String(x).trim() === '')) return true;
  const parse = x => {
    const m = String(x).trim().match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
    if (!m) return null;
    const [h, min, s] = [Number(m[1]), Number(m[2]), Number(m[3] || 0)];
    return h < 24 && min < 60 && s < 60 ? h * 3600 + min * 60 + s : null;
  };
  const [start, end] = range.map(parse);
  if (start == null || end == null) return false;
  if (start === end) return true;
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(date).map(x => [x.type,x.value]));
  const now = Number(p.hour)*3600 + Number(p.minute)*60 + Number(p.second);
  return start < end ? now >= start && now <= end : now >= start || now <= end;
};
