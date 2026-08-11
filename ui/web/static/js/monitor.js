import { j, esc } from './api.js';
import { toast } from './ui.js';

export function renderMonitor(m) {
  m = m || {};
  const o = m.online || {}, s = m.ssl || {};
  const el = document.getElementById('monitor-cfg');
  if (!el) return;
  el.innerHTML = `
    <div class="card" style="min-height:0"><h3>📡 Online</h3>
      <div class="row">${o.enabled ? '🟢 Включён' : '⚪ Выключен'} · <b>${o.interval ?? '—'} мин</b></div>
      <div class="actions">
        <button type="button" class="secondary" data-m="online" data-en="${o.enabled ? 0 : 1}">${o.enabled ? 'Выкл' : 'Вкл'}</button>
        <button type="button" class="secondary" data-mi="online" data-iv="1">1м</button>
        <button type="button" class="secondary" data-mi="online" data-iv="5">5м</button>
        <button type="button" class="secondary" data-mi="online" data-iv="15">15м</button>
        <button type="button" data-check="online">▶ Проверить сейчас</button>
      </div></div>
    <div class="card" style="min-height:0"><h3>🔒 SSL</h3>
      <div class="row">${s.enabled ? '🟢 Включён' : '⚪ Выключен'} · <b>${s.interval ?? '—'} мин</b></div>
      <div class="actions">
        <button type="button" class="secondary" data-m="ssl" data-en="${s.enabled ? 0 : 1}">${s.enabled ? 'Выкл' : 'Вкл'}</button>
        <button type="button" class="secondary" data-mi="ssl" data-iv="60">1ч</button>
        <button type="button" class="secondary" data-mi="ssl" data-iv="1440">1д</button>
        <button type="button" data-check="ssl">▶ Проверить сейчас</button>
      </div></div>`;
  el.querySelectorAll('[data-m]').forEach(b => b.onclick = async () => {
    try {
      await j('/api/monitor/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: b.dataset.m, enabled: b.dataset.en === '1' }),
      });
      toast('Сохранено', true);
      const { loadSummary } = await import('./dashboard.js');
      loadSummary();
    } catch (e) { toast(e.message, false); }
  });
  el.querySelectorAll('[data-mi]').forEach(b => b.onclick = async () => {
    try {
      await j('/api/monitor/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: b.dataset.mi, interval: +b.dataset.iv }),
      });
      toast('Сохранено', true);
      const { loadSummary } = await import('./dashboard.js');
      loadSummary();
    } catch (e) { toast(e.message, false); }
  });
  el.querySelectorAll('[data-check]').forEach(b => b.onclick = () => runCheck(b));
}

async function runCheck(b) {
  const kind = b.dataset.check;
  const box = document.getElementById('monitor-result');
  b.disabled = true;
  if (box) box.innerHTML = '<div class="empty">Проверка ' + kind + '…</div>';
  try {
    const r = await j('/api/monitor/check/' + kind, { method: 'POST' });
    const servers = r.servers || [];
    let html = '<div class="card" style="margin-top:.5rem;min-height:0">';
    if (kind === 'online') {
      const s = r.summary || {};
      html += `<div class="row" style="font-size:.95rem;margin-bottom:.35rem">🟢 online <b>${s.online ?? 0}</b> · 🔴 offline <b>${s.offline ?? 0}</b> · всего ${s.total ?? servers.length}</div>`;
      html += '<div class="result-grid">';
      servers.forEach(row => {
        const mark = row.status === 'online' ? '🟢' : (row.status === 'offline' ? '🔴' : '⚪');
        let right = '—';
        if (row.status === 'offline') right = row.error ? esc(row.error) : 'offline';
        else if (row.ms != null) right = esc(row.ms + ' ms') + ' <span style="opacity:.7">(' + esc(row.method || 'Ping') + ')</span>';
        html += `<div class="ri"><span class="n">${mark} ${esc(row.name)}</span><span class="m">${right}</span></div>`;
      });
      html += '</div>';
    } else {
      const s = r.summary || {};
      html += `<div class="row" style="margin-bottom:.35rem">🟢 valid ${s.valid || 0} · 🟡 warning ${s.warning || 0} · 🔴 expired/error ${(s.expired || 0) + (s.error || 0)}</div>`;
      const rows = servers.filter(x => x.status !== 'skip');
      if (!rows.length) html += '<div class="row">Нет серверов с проверкой SSL-сертификатов</div>';
      else {
        html += '<table class="ssl-table"><thead><tr><th>Сервер</th><th>Осталось дней</th><th>Проверено</th></tr></thead><tbody>';
        rows.forEach(row => {
          const mark = row.status === 'valid' ? '🟢' : (row.status === 'warning' ? '🟡' : '🔴');
          html += `<tr><td data-label="Сервер">${mark} ${esc(row.name)}</td><td data-label="Дней">${esc(row.days_left != null ? row.days_left : '—')}</td><td data-label="Проверено">${esc(row.checked || '—')}</td></tr>`;
        });
        html += '</tbody></table>';
      }
    }
    html += '</div>';
    if (box) box.innerHTML = html;
    toast('Проверка ' + kind + ' завершена', true);
    const { loadEvents } = await import('./dashboard.js').catch(() => ({}));
  } catch (e) {
    if (box) box.innerHTML = '<div class="empty" style="color:var(--err)">' + esc(e.message) + '</div>';
    toast(e.message, false);
  } finally {
    b.disabled = false;
  }
}

// Сколько событий показывать. «Все» НЕ схлопывается при polling:
// SSE-снапшот мержит свежие события в кэш (dedup/sort/cap), а рендер всегда
// идёт из кэша с учётом _eventsLimit — поэтому раскрытый список не перетирается
// коротким (8) серверным срезом и скролл не отбрасывается наверх.
const EVENTS_LIMIT_KEY = 'bot4vps_events_limit';
const EVENTS_CACHE_MAX = 200;

function _loadLimit() {
  try {
    const v = parseInt(localStorage.getItem(EVENTS_LIMIT_KEY), 10);
    return v > 0 ? v : 5;
  } catch { return 5; }
}
function _saveLimit() {
  try { localStorage.setItem(EVENTS_LIMIT_KEY, String(_eventsLimit)); } catch {}
}

let _eventsLimit = _loadLimit();
let _eventsCache = [];

export async function loadEvents(limit) {
  if (typeof limit === 'number') { _eventsLimit = limit; _saveLimit(); }
  try {
    const data = await j('/api/events?limit=' + _eventsLimit);
    _eventsCache = data.events || [];
    renderEvents(_eventsCache.slice(0, _eventsLimit), 'events');
  } catch (e) {
    document.getElementById('events').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

// SSE отдаёт короткий срез (8). Мержим его в кэш (по id, без дублей; свежие
// сверху по timestamp; cap EVENTS_CACHE_MAX), а показываем столько, сколько
// раскрыл пользователь. Так live-обновление не схлопывает «Все».
export function applyEventsSnapshot(events) {
  if (!Array.isArray(events) || !events.length) return;
  const byId = new Map();
  for (const e of events) { if (e && e.id != null) byId.set(String(e.id), e); }
  for (const e of _eventsCache) { const k = String(e.id); if (!byId.has(k)) byId.set(k, e); }
  _eventsCache = Array.from(byId.values())
    .sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''))
    .slice(0, EVENTS_CACHE_MAX);
  renderEvents(_eventsCache.slice(0, _eventsLimit), 'events');
}

export function renderEvents(list, id) {
  const el = document.getElementById(id);
  if (!el) return;
  // Сохраняем scroll, чтобы polling не «отбрасывал» вверх
  const prevScroll = el.scrollTop;
  if (!list.length) { el.innerHTML = '<div class="empty">Нет</div>'; return; }
  el.innerHTML = list.map((e, i) => {
    const lvl = e.level || 'info';
    const sn = (e.details && (e.details.server_name || e.details.name)) || '';
    const reason = (e.details && e.details.reason) || '';
    const ok = /online|renewed|finished|queued|started/.test(reason) || lvl === 'info';
    const eid = e.id || String(i);
    return `<div class="event ${esc(lvl)}" data-event-id="${esc(eid)}" title="Открыть детали">
      <div class="barline ${ok && lvl !== 'critical' && lvl !== 'warning' ? 'ok' : ''}"></div>
      <div class="body"><div class="title">${esc(e.title)}</div>
      <div class="meta">${esc((e.timestamp || '').slice(0, 19).replace('T', ' '))}${sn ? ' · ' + esc(sn) : ''}</div></div></div>`;
  }).join('');
  el.scrollTop = prevScroll;
  el.querySelectorAll('[data-event-id]').forEach(node => {
    node.onclick = () => openEventDetail(node.dataset.eventId);
  });
}

function openEventDetail(eventId) {
  const e = _eventsCache.find(x => x.id === eventId);
  if (!e) { toast('Событие не найдено', false); return; }
  const d = e.details || {};
  const ts = (e.timestamp || '').slice(0, 19).replace('T', ' ');
  const lines = [
    ['Время', ts],
    ['Уровень', (e.level || '').toUpperCase()],
    ['Тип', e.type || '—'],
    ['Сервер', d.server_name || d.name || '—'],
    ['Task ID', d.task_id || '—'],
    ['Статус', d.status || '—'],
    ['Попытка', d.attempt != null ? d.attempt : '—'],
    ['Длительность', d.duration_seconds != null ? (Number(d.duration_seconds).toFixed(2) + ' с') : '—'],
    ['Причина', d.reason || '—'],
  ];
  const kv = lines.map(([k, v]) => `<div class="row"><b>${esc(k)}:</b> ${esc(String(v))}</div>`).join('');
  const msg = e.message ? `<div class="row" style="margin-top:.5rem;white-space:pre-wrap">${esc(e.message)}</div>` : '';
  // details JSON без дублирования message
  const detailsJson = JSON.stringify(d, null, 2);
  const detailsBlock = detailsJson && detailsJson !== '{}'
    ? `<div class="row" style="margin-top:.6rem"><b>Подробности</b></div>
       <pre class="event-detail-pre">${esc(detailsJson)}</pre>`
    : '';
  const output = d.output
    ? `<div class="row" style="margin-top:.6rem"><b>Вывод задачи</b></div>
       <pre class="event-detail-pre">${esc(String(d.output))}</pre>`
    : '';

  let modal = document.getElementById('event-detail-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'event-detail-modal';
    modal.className = 'modal-bg';
    modal.innerHTML = `<div class="modal" style="width:min(560px,100%)">
      <h3 id="event-detail-title" style="margin:0 0 .6rem"></h3>
      <div id="event-detail-body"></div>
      <div class="actions" style="margin-top:.8rem">
        <button type="button" class="secondary" id="event-detail-close">Закрыть</button>
      </div>
    </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', ev => {
      if (ev.target === modal) closeEventDetail();
    });
    modal.querySelector('#event-detail-close').onclick = closeEventDetail;
  }
  modal.querySelector('#event-detail-title').textContent = e.title || 'Событие';
  modal.querySelector('#event-detail-body').innerHTML = kv + msg + output + detailsBlock;
  // z-index поверх других
  modal.style.zIndex = '200';
  modal.classList.add('open');
}

function closeEventDetail() {
  const modal = document.getElementById('event-detail-modal');
  if (modal) modal.classList.remove('open');
}
