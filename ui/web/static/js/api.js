export async function j(url, opts) {
  const r = await fetch(url, opts);
  const t = await r.text();
  let d;
  try { d = t ? JSON.parse(t) : {}; } catch {
    const error = new Error(nonJsonReason(r));
    error.status = r.status;
    error.detail = '';
    error.body = t.slice(0, 140);
    error.code = r.headers.get('X-Backup-Error') || '';
    error.hint = nonJsonHint(r);
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

/**
 * Сообщение об ответе, который не разобрался как JSON.
 *
 * Раньше сюда попадали первые байты тела, и пользователь читал
 * «499 �PNG IHDR…» вместо причины: сырые байты не объясняют ничего. Статус и
 * тип в ответе говорят больше — по ним видно, что это вообще не наш JSON.
 */
function nonJsonReason(r) {
  const type = (r.headers.get('content-type') || '').split(';')[0].trim() || 'тип не указан';
  return `HTTP ${r.status}, в ответе не JSON (${type})`;
}

/**
 * Подсказка, если ответ пришёл не от панели.
 *
 * Все ответы панели несут заголовок `server` (uvicorn). Запрос может не
 * дойти до неё: на пути встаёт веб-защита антивируса или прокси, и отвечает
 * сам — чаще всего картинкой-заглушкой вместо тела. Панель тут ни при чём, и
 * пользователю надо сказать это прямо, иначе причину искать негде.
 */
function nonJsonHint(r) {
  if (r.headers.get('server')) return '';
  return 'Ответ пришёл не от панели: запрос перехвачен на этом устройстве — так делают '
    + 'веб-защита антивируса или прокси. Добавьте адрес панели в его исключения.';
}

/** Текст ошибки для интерфейса: сообщение и, если есть, подсказка о причине. */
export function errorHtml(e) {
  const hint = e?.hint ? `<div class="err-hint">${esc(e.hint)}</div>` : '';
  return esc(e?.message || String(e)) + hint;
}
