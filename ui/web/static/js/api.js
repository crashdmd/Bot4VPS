export async function j(url, opts) {
  const r = await fetch(url, opts);
  const t = await r.text();
  let d;
  try { d = t ? JSON.parse(t) : {}; } catch {
    throw new Error(r.status + ' ' + t.slice(0, 140));
  }
  if (!r.ok) throw new Error(d.detail || t || r.status);
  return d;
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
