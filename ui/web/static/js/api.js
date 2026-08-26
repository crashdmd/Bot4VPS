export async function j(url, opts) {
  const r = await fetch(url, opts);
  const t = await r.text();
  let d;
  try { d = t ? JSON.parse(t) : {}; } catch {
    const error = new Error(r.status + ' ' + t.slice(0, 140));
    error.status = r.status;
    error.detail = '';
    error.body = t.slice(0, 140);
    error.code = r.headers.get('X-Backup-Error') || '';
    throw error;
  }
  if (!r.ok) {
    const error = new Error(d.detail || t || r.status);
    error.status = r.status;
    error.detail = d.detail || '';
    error.body = t.slice(0, 140);
    error.code = r.headers.get('X-Backup-Error') || '';
    const rawDetails = r.headers.get('X-Backup-Details');
    if (rawDetails) {
      try { error.details = JSON.parse(rawDetails); } catch (_) { /* safe header is optional */ }
    }
    throw error;
  }
  return d;
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
