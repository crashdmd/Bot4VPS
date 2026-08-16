import { j, esc } from './api.js';
import { toast, plural, confirmAction } from './ui.js';

// Кэш состояния updater'а (обновляется по кликам и во время установки;
// SSE-перерисовки блока мониторинга используют кэш, запросов не плодят).
let updateState = null;
let updatePollTimer = null;

export function renderMonitor(m) {
  m = m || {};
  const o = m.online || {}, s = m.ssl || {};
  const u = m.update || {};
  const el = document.getElementById('monitor-cfg');
  if (!el) return;
  const updAvailable = !!(updateState && updateState.available);
  const busy = !!(updateState && ['checking', 'downloading', 'installing', 'rolling_back'].includes(updateState.status));
  const failed = !!(updateState && updateState.status === 'failed');
  el.innerHTML = `
    <div class="mon-cfg-item">
      <div class="mon-cfg-title">📡 Online</div>
      <div class="mon-cfg-state">${o.enabled ? '🟢 Включён' : '⚪ Выключен'} · ${o.interval ?? '—'} мин</div>
      <div class="actions mon-cfg-actions">
        <button type="button" class="secondary" data-m="online" data-en="${o.enabled ? 0 : 1}">${o.enabled ? 'Выкл' : 'Вкл'}</button>
        <button type="button" class="secondary" data-mi="online" data-iv="1">1м</button>
        <button type="button" class="secondary" data-mi="online" data-iv="5">5м</button>
        <button type="button" class="secondary" data-mi="online" data-iv="15">15м</button>
        <button type="button" data-check="online">▶ Проверить</button>
      </div>
    </div>
    <div class="mon-cfg-item">
      <div class="mon-cfg-title">🔒 SSL</div>
      <div class="mon-cfg-state">${s.enabled ? '🟢 Включён' : '⚪ Выключен'} · ${s.interval ?? '—'} мин</div>
      <div class="actions mon-cfg-actions">
        <button type="button" class="secondary" data-m="ssl" data-en="${s.enabled ? 0 : 1}">${s.enabled ? 'Выкл' : 'Вкл'}</button>
        <button type="button" class="secondary" data-mi="ssl" data-iv="60">1ч</button>
        <button type="button" class="secondary" data-mi="ssl" data-iv="1440">1д</button>
        <button type="button" data-check="ssl">▶ Проверить</button>
      </div>
    </div>
    <div class="mon-cfg-item">
      <div class="mon-update-row">
        <label class="mon-update-label"><input type="checkbox" data-upd-en ${u.enabled ? 'checked' : ''}> Проверять обновления</label>
        <div class="actions mon-cfg-actions" ${u.enabled ? '' : 'style="display:none"'}>
          <button type="button" ${busy ? 'disabled' : ''} ${updAvailable ? 'data-upd-install' : 'data-upd-check'}>${updAvailable ? 'Обновить' : 'Проверить обновления'}</button>
          <button type="button" class="secondary" ${busy ? 'disabled' : ''} data-upd-history>История обновлений</button>
        </div>
      </div>
      ${(failed && updateState && updateState.last_error) ? `<div class="mon-cfg-state" style="margin-top:.4rem;color:var(--danger,#e5484d)">⚠ ${esc(updateState.last_error)}</div>` : ''}
    </div>`;
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
  bindUpdateControls(el);
}

// ==================== Обновления Bot4VPS ====================

/** Загрузить состояние updater'а и перерисовать блок мониторинга. */
export async function loadUpdateState() {
  try {
    updateState = await j('/api/update/state');
    const el = document.getElementById('monitor-cfg');
    if (el) {
      // Перерисовка с сохранением актуального конфига: он приходит в SSE,
      // но при ручном обновлении после клика конфиг мог не измениться.
      const cfg = await j('/api/monitor/config').catch(() => null);
      renderMonitor(cfg || {});
    }
    scheduleUpdatePolling();
  } catch { /* блок недоступен — молча */ }
}

/** Опрос состояния каждые 2с, только пока идёт установка/откат. */
function scheduleUpdatePolling() {
  if (updatePollTimer) { clearInterval(updatePollTimer); updatePollTimer = null; }
  const st = updateState && updateState.status;
  if (!st || !['downloading', 'installing', 'rolling_back'].includes(st)) return;
  updatePollTimer = setInterval(async () => {
    try {
      const prev = updateState;
      updateState = await j('/api/update/state');
      if (prev && prev.status !== updateState.status) {
        if (updateState.status === 'idle' && prev.status !== 'idle') {
          toast('Обновление установлено', true);
          const { loadSummary } = await import('./dashboard.js');
          loadSummary();
        } else if (updateState.status === 'failed') {
          toast('Ошибка обновления: ' + (updateState.last_error || 'неизвестная ошибка'), false);
        }
      }
      if (!['downloading', 'installing', 'rolling_back'].includes(updateState.status)) {
        clearInterval(updatePollTimer);
        updatePollTimer = null;
        loadUpdateState();
        return;
      }
      // Лёгкое обновление кнопок без полного ре-рендера
      const el = document.getElementById('monitor-cfg');
      if (el) {
        const checkBtn = el.querySelector('[data-upd-check],[data-upd-install]');
        if (checkBtn) {
          const map = { downloading: 'Скачивание…', installing: 'Установка… (перезапуск)', rolling_back: 'Откат…' };
          checkBtn.textContent = map[updateState.status] || checkBtn.textContent;
          checkBtn.disabled = true;
        }
      }
    } catch { /* сервер перезапускается —/network blip; продолжаем опрос */ }
  }, 2000);
}

function bindUpdateControls(el) {
  const cb = el.querySelector('[data-upd-en]');
  if (cb) cb.onchange = async () => {
    const enabled = cb.checked;
    try {
      await j('/api/monitor/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'update', enabled }),
      });
      toast('Сохранено', true);
      // Показать/скрыть кнопки на месте, без полного ре-рендера
      const actions = el.querySelector('.mon-update-row .actions');
      if (actions) actions.style.display = enabled ? '' : 'none';
    } catch (e) {
      cb.checked = !enabled;
      toast(e.message, false);
    }
  };

  const checkBtn = el.querySelector('[data-upd-check]');
  if (checkBtn) checkBtn.onclick = () => runUpdateCheck(checkBtn);

  const installBtn = el.querySelector('[data-upd-install]');
  if (installBtn) installBtn.onclick = () => showUpdateModal();

  const histBtn = el.querySelector('[data-upd-history]');
  if (histBtn) histBtn.onclick = () => showHistoryModal();
}

async function runUpdateCheck(btn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Проверка…';
  try {
    const res = await j('/api/update/check', { method: 'POST' });
    await loadUpdateState();
    if (res.update_available) {
      toast(`Доступна новая версия ${res.version}`, true);
    } else if (res.error) {
      toast('Ошибка проверки: ' + res.error, false);
    } else {
      toast('Обновлений нет', true);
    }
  } catch (e) {
    btn.disabled = false;
    btn.textContent = old;
    toast(e.message, false);
  }
}

/** Динамическая модалка (паттерн openEventDetail) с confirm/cancel. */
function openActionModal({ title, bodyHtml, okText, cancelText = 'Отмена', danger = false, onOk }) {
  const modal = document.createElement('div');
  modal.className = 'modal-bg';
  modal.innerHTML = `<div class="modal" style="width:min(640px,100%)">
    <h3 style="margin:0 0 .6rem">${title}</h3>
    <div>${bodyHtml}</div>
    <div class="actions" style="margin-top:.8rem;justify-content:flex-end">
      <button type="button" class="secondary" data-act="cancel">${cancelText}</button>
      <button type="button" ${danger ? 'class="danger"' : ''} data-act="ok">${okText}</button>
    </div>
  </div>`;
  document.body.appendChild(modal);
  // Без .open модалка невидима: .modal-bg по умолчанию display:none
  modal.classList.add('open');
  // Ниже #confirm-modal (z-index:100 в .modal-bg), чтобы подтверждающее
  // окно confirmAction при откате открывалось ПОВЕРХ этой модалки.
  // Выше контента страницы (максимум ~81 у выпадающих меню).
  modal.style.zIndex = '90';
  const close = () => modal.remove();
  modal.addEventListener('click', ev => { if (ev.target === modal) close(); });
  modal.querySelector('[data-act="cancel"]').onclick = close;
  modal.querySelector('[data-act="ok"]').onclick = async () => {
    const okBtn = modal.querySelector('[data-act="ok"]');
    okBtn.disabled = true;
    try { await onOk(okBtn); } finally { close(); }
  };
  return { close };
}

/** Модалка «Доступно обновление»: changelog_new + подтверждение (ТЗ п.9). */
export async function showUpdateModal() {
  let data;
  try {
    data = await j('/api/update/changelog_new');
  } catch (e) {
    toast(e.message, false);
    return;
  }
  openActionModal({
    title: `🆕 Доступно обновление Bot4VPS — ${esc(data.version)}`,
    bodyHtml: `<pre class="event-detail-pre" style="max-height:50vh;overflow:auto">${esc(data.changelog)}</pre>`,
    okText: 'Обновить',
    onOk: async () => {
      try {
        await j('/api/update/install', { method: 'POST' });
        toast('Обновление запущено', true);
        await loadUpdateState();
      } catch (e) { toast(e.message, false); }
    },
  });
}

/** Модалка «История обновлений»: changelog текущей + Откатить (ТЗ п.13-14). */
async function showHistoryModal() {
  let data;
  try {
    data = await j('/api/update/changelog');
  } catch (e) {
    toast(e.message, false);
    return;
  }
  openActionModal({
    title: `📋 Bot4VPS ${esc(data.version)}`,
    bodyHtml: `<pre class="event-detail-pre" style="max-height:50vh;overflow:auto">${esc(data.changelog)}</pre>`,
    okText: 'Откатить',
    cancelText: 'Закрыть',
    danger: true,
    onOk: async () => showRollbackConfirm(data.version),
  });
}

/** Подтверждение отката с текстом из ТЗ п.14 (модалка confirmAction). */
async function showRollbackConfirm(currentVersion) {
  const ok = await confirmAction({
    title: '⚠️ Откат Bot4VPS',
    message:
      `Сейчас установлена версия ${currentVersion}.\n\n` +
      'Вы собираетесь выполнить откат на предыдущую версию.\n' +
      'Версия выбирается на следующем шаге.\n\n' +
      'Для этого будет загружен соответствующий GitHub Release,\n' +
      'после чего Bot4VPS будет перезапущен.\n\n' +
      'Автоматический откат доступен только для версий 3.0 и новее.\n' +
      'Версии ниже 3.0 необходимо устанавливать вручную.',
    confirmText: 'Продолжить',
    cancelText: 'Отмена',
    danger: true,
  });
  if (!ok) return;
  await showVersionPicker(currentVersion);
}

/** Выбор версии отката (radio-список ≥ 4.0.0) и запуск отката. */
async function showVersionPicker(currentVersion) {
  let data;
  try {
    data = await j('/api/update/versions');
  } catch (e) {
    toast('Не удалось получить список версий: ' + e.message, false);
    return;
  }
  const versions = data.versions || [];
  if (!versions.length) {
    toast('Нет версий, доступных для отката', false);
    return;
  }
  const items = versions.map((v, i) => `
    <label style="display:flex;align-items:center;gap:.5rem;padding:.35rem 0;cursor:pointer">
      <input type="radio" name="upd-ver" value="${esc(v)}" ${i === 0 ? 'checked' : ''}>
      ${esc(v)}
    </label>`).join('');
  openActionModal({
    title: '⬇️ Выбор версии для отката',
    bodyHtml: `<div style="margin-bottom:.4rem;color:var(--text-muted)">Текущая версия: <b>${esc(currentVersion)}</b></div>
      <div style="max-height:50vh;overflow:auto">${items}</div>`,
    okText: 'Откатить',
    danger: true,
    onOk: async (okBtn) => {
      const sel = document.querySelector('input[name="upd-ver"]:checked');
      if (!sel) { toast('Выберите версию', false); return; }
      const ok = await confirmAction({
        title: '⚠️ Откат Bot4VPS',
        message:
          `Сейчас установлена версия ${currentVersion}.\n\n` +
          `Вы собираетесь установить версию ${sel.value}.\n\n` +
          'Для этого будет загружен соответствующий GitHub Release,\n' +
          'после чего Bot4VPS будет перезапущен.\n\n' +
          'Автоматический откат доступен только для версий 4.0 и новее.',
        confirmText: 'Откатить',
        cancelText: 'Отмена',
        danger: true,
      });
      if (!ok) { okBtn.disabled = false; return; }
      try {
        await j('/api/update/rollback', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version: sel.value }),
        });
        toast('Откат запущен', true);
        await loadUpdateState();
      } catch (e) { toast(e.message, false); }
    },
  });
}

async function runCheck(b) {
  const kind = b.dataset.check;
  const modal = document.getElementById('monitor-check-modal');
  const modalBody = document.getElementById('monitor-check-body');
  const modalTitle = document.getElementById('monitor-check-title');

  b.disabled = true;

  // Открываем модалку сразу с индикатором загрузки
  if (modalTitle) modalTitle.textContent = 'Проверка ' + kind + '…';
  if (modalBody) modalBody.innerHTML = '<div class="empty">Проверка ' + kind + '…<br><span style="opacity:.7;font-size:.9rem">Может занять до минуты</span></div>';
  if (modal) modal.style.display = 'flex';

  try {
    const r = await j('/api/monitor/check/' + kind, { method: 'POST' });
    const servers = r.servers || [];
    let html = '<div class="card" style="margin-top:.5rem;min-height:0">';
    if (kind === 'online') {
      const s = r.summary || {};
      html += `<div class="check-summary">🟢 online <b>${s.online ?? 0}</b> · 🔴 offline <b>${s.offline ?? 0}</b> · всего ${s.total ?? servers.length}</div>`;
      html += '<div class="check-results-list">';
      servers.forEach(row => {
        const mark = row.status === 'online' ? '🟢' : (row.status === 'offline' ? '🔴' : '⚪');
        let right = '—';
        if (row.status === 'offline') right = row.error ? esc(row.error) : 'offline';
        else if (row.ms != null) right = esc(row.ms + ' ms') + ' <span style="opacity:.7">(' + esc(row.method || 'Ping') + ')</span>';
        html += `<div class="check-item"><span class="check-name">${mark} ${esc(row.name)}</span><span class="check-value">${right}</span></div>`;
      });
      html += '</div>';
    } else {
      const s = r.summary || {};
      html += `<div class="check-summary">🟢 valid ${s.valid || 0} · 🟡 warning ${s.warning || 0} · 🔴 expired/error ${(s.expired || 0) + (s.error || 0)}</div>`;
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
    if (modalBody) modalBody.innerHTML = html;
    if (modalTitle) modalTitle.textContent = 'Результат проверки ' + kind;
    toast('Проверка ' + kind + ' завершена', true);
    const { loadEvents } = await import('./dashboard.js').catch(() => ({}));
  } catch (e) {
    if (modalBody) modalBody.innerHTML = '<div class="empty" style="color:var(--err)">' + esc(e.message) + '</div>';
    if (modalTitle) modalTitle.textContent = 'Ошибка проверки';
    toast(e.message, false);
  } finally {
    b.disabled = false;
  }
}

// Обработчик закрытия модалки проверки
document.addEventListener('DOMContentLoaded', () => {
  const closeBtn = document.getElementById('monitor-check-close');
  const modal = document.getElementById('monitor-check-modal');
  if (closeBtn && modal) {
    closeBtn.addEventListener('click', () => {
      modal.style.display = 'none';
    });
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.style.display = 'none';
      }
    });
  }
});

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
    const taskVisualClass = {
      task_finished: 'ok',
      task_queued: 'info',
      task_queue_paused: 'warning',
      task_failed: 'error',
      task_cancelled: 'warning',
      task_started: 'info',
    }[reason];
    const ok = /online|renewed|finished/.test(reason) || lvl === 'info';
    const visualClass = taskVisualClass
      || (ok && lvl !== 'critical' && lvl !== 'warning' ? 'ok' : lvl);
    const eid = e.id || String(i);
    const unreadClass = e.read ? '' : 'is-unread';
    const readLabel = e.read
      ? '<span class="event-read">Прочитано</span>'
      : '<span class="event-read is-unread">Не прочитано</span>';
    return `<div class="event ${esc(visualClass)} ${unreadClass}" data-event-id="${esc(eid)}" title="Открыть детали">
      <div class="barline"></div>
      <div class="body"><div class="title">${esc(e.title)}</div>
      <div class="meta">${esc((e.timestamp || '').slice(0, 19).replace('T', ' '))}${sn ? ' · ' + esc(sn) : ''}${readLabel}</div></div></div>`;
  }).join('');
  el.scrollTop = prevScroll;
  el.querySelectorAll('[data-event-id]').forEach(node => {
    node.onclick = () => openEventDetail(node.dataset.eventId);
  });
}

function historyTaskHasLog(task) {
  if (!task) return false;
  const lines = Array.isArray(task.output_lines) ? task.output_lines : [];
  if (lines.some(line => String(line || '').trim())) return true;
  if (String(task.error || '').trim()) return true;
  const result = task.result || {};
  return Boolean(String(result.output || '').trim() || String(result.error || '').trim());
}

export async function openEventDetail(eventId) {
  const e = _eventsCache.find(x => x.id === eventId);
  if (!e) { toast('Событие не найдено', false); return; }

  // Помечаем событие как прочитанное, если оно не прочитано
  if (!e.read) {
    try {
      await j('/api/events/mark-read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId }),
      });
      // Обновляем флаг в кэше
      e.read = true;
      // Перерисовываем список событий если мы на странице событий
      const eventsEl = document.getElementById('events');
      if (eventsEl) {
        renderEvents(_eventsCache.slice(0, _eventsLimit), 'events');
      }
      // Уведомляем об изменении статуса для обновления бейджа
      window.dispatchEvent(new Event('event-read'));
    } catch (err) {
      console.error('Failed to mark event as read:', err);
    }
  }

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
  const isTaskEvent = String(e.type || '').toLowerCase() === 'task';
  // Для задач подробности и полный вывод доступны в разделе «Задачи».
  // В уведомлении оставляем только краткую сводку, чтобы не дублировать лог.
  const detailsJson = isTaskEvent ? '' : JSON.stringify(d, null, 2);
  const detailsBlock = detailsJson && detailsJson !== '{}'
    ? `<div class="row" style="margin-top:.6rem"><b>Подробности</b></div>
       <pre class="event-detail-pre">${esc(detailsJson)}</pre>`
    : '';
  const output = !isTaskEvent && d.output
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
      <div class="actions" style="margin-top:.8rem;display:flex;align-items:center;justify-content:space-between;width:100%">
        <button type="button" class="secondary" id="event-detail-close">Закрыть</button>
        <button type="button" class="secondary hidden" id="event-detail-log" hidden>📜 Посмотреть лог</button>
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

  const logBtn = modal.querySelector('#event-detail-log');
  const taskId = String(d.task_id || '').trim();
  modal.dataset.taskId = taskId;
  logBtn.hidden = true;
  logBtn.classList.add('hidden');
  logBtn.onclick = null;
  // Кнопка появляется только после проверки, что запись есть именно в
  // persistent history и содержит непустой лог. При нажатии проверяем ещё
  // раз: запись или её лог могли быть удалены после открытия уведомления.
  if (isTaskEvent && taskId) {
    j(`/api/tasks/history/${encodeURIComponent(taskId)}`).then(task => {
      if (!modal.classList.contains('open') || modal.dataset.taskId !== taskId || !historyTaskHasLog(task)) return;
      logBtn.hidden = false;
      logBtn.classList.remove('hidden');
      logBtn.onclick = async () => {
        try {
          const current = await j(`/api/tasks/history/${encodeURIComponent(taskId)}`);
          if (!historyTaskHasLog(current)) {
            throw new Error('Лог этой задачи больше недоступен: запись удалена из истории или лог пуст.');
          }
          closeEventDetail();
          const { openTaskLog } = await import('./tasks.js?v=20260816-task-history-v3');
          await openTaskLog(taskId);
        } catch (err) {
          logBtn.hidden = true;
          logBtn.classList.add('hidden');
          toast('Лог этой задачи больше недоступен: запись удалена из истории или лог пуст.', false);
        }
      };
    }).catch(() => {
      // Записи нет в persistent history или лог пуст — кнопку не показываем.
      logBtn.hidden = true;
      logBtn.classList.add('hidden');
    });
  }
  // z-index поверх других
  modal.style.zIndex = '200';
  modal.classList.add('open');
}

function closeEventDetail() {
  const modal = document.getElementById('event-detail-modal');
  if (modal) modal.classList.remove('open');
}

// ==================== System Monitoring ====================

const WIDGET_COLORS = {
  cpu: '#3b82f6',
  ram: '#a855f7',
  disk: '#f97316',
  net: '#10b981',
};

let systemHistory = {
  cpu: [],
  ram: [],
  disk: [],
  netRx: [],
  netTx: [],
};

const HISTORY_MAX = 20;

let systemPollTimer = null;

// Аптайм сервиса тикает локально: /api/system опрашивается раз в 5 секунд,
// между ответами добавляем время, прошедшее с последней синхронизации.
// performance.now() монотонен — перевод часов на машине счётчик не сломает.
let svcUptimeBase = null;   // секунды, как их отдал бэкенд
let svcUptimeAt = 0;        // отметка performance.now() в момент ответа
let svcTickTimer = null;

/** Гасит таймеры страницы мониторинга при уходе с неё.
 *  Как stopDashMetrics/stopWgTimers — иначе /api/system опрашивался бы
 *  и с других страниц, а секундный тик работал бы в пустоту. */
export function stopSystemMonitor() {
  if (systemPollTimer) { clearInterval(systemPollTimer); systemPollTimer = null; }
  if (svcTickTimer) { clearInterval(svcTickTimer); svcTickTimer = null; }
}

export function initSystemMonitor() {
  const page = document.getElementById('page-monitor');
  if (!page) return;

  systemHistory = { cpu: [], ram: [], disk: [], netRx: [], netTx: [] };
  renderSystemWidgets();
  updateSystemData();
  // renderMonitor рисуется только по SSE-снапшоту, а он приходит не сразу —
  // тянем конфиг сами, чтобы блок не висел с заглушкой при первом заходе.
  loadMonitorConfig();
  // Состояние updater'а (кнопка «Обновить» vs «Проверить обновления»)
  loadUpdateState();

  if (systemPollTimer) clearInterval(systemPollTimer);
  systemPollTimer = setInterval(updateSystemData, 5000);

  if (svcTickTimer) clearInterval(svcTickTimer);
  svcTickTimer = setInterval(tickServiceUptime, 1000);

  const btnCopyIp = document.getElementById('btn-copy-ip');
  if (btnCopyIp) btnCopyIp.onclick = copyIpAddress;

  const btnRestart = document.getElementById('btn-restart-service');
  if (btnRestart) btnRestart.onclick = restartBotService;

  const btnJournal = document.getElementById('btn-view-journal');
  if (btnJournal) btnJournal.onclick = viewJournal;

  const jModal = document.getElementById('journal-modal');
  if (jModal && !jModal.dataset.bound) {
    jModal.dataset.bound = '1';
    // клик по фону — тоже закрытие, поток обязан оборваться и здесь
    jModal.addEventListener('click', ev => { if (ev.target === jModal) journalClose(); });
    const bStop = document.getElementById('btn-journal-stop');
    if (bStop) bStop.onclick = () => journalStop(true);
    const bClose = document.getElementById('btn-journal-close');
    if (bClose) bClose.onclick = journalClose;
    document.addEventListener('keydown', ev => {
      if (ev.key === 'Escape' && jModal.classList.contains('open')) journalClose();
    });
    // уход со страницы/перезагрузка — браузер закроет SSE, помогаем явно
    window.addEventListener('beforeunload', () => journalStop(false));
  }
}

function renderSystemWidgets() {
  const container = document.getElementById('system-widgets');
  if (!container) return;

  container.innerHTML = `
    <div class="sys-widget" data-metric="cpu">
      <div class="sw-head">
        <span class="sw-label">CPU</span>
        <span class="sw-icon">📊</span>
      </div>
      <div class="sw-value" id="cpu-value">—</div>
      <svg class="sw-graph" id="cpu-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      <div class="sw-stats">
        <span id="cpu-temp">—</span>
        <span id="cpu-minmax">—</span>
      </div>
    </div>

    <div class="sys-widget" data-metric="ram">
      <div class="sw-head">
        <span class="sw-label">Память</span>
        <span class="sw-icon">💾</span>
      </div>
      <div class="sw-value" id="ram-value">—</div>
      <svg class="sw-graph" id="ram-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      <div class="sw-stats">
        <span id="ram-usage">—</span>
        <span id="ram-minmax">—</span>
      </div>
    </div>

    <div class="sys-widget" data-metric="disk">
      <div class="sw-head">
        <span class="sw-label">Диск</span>
        <span class="sw-icon">💿</span>
      </div>
      <div class="sw-value" id="disk-value">—</div>
      <svg class="sw-graph" id="disk-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      <div class="sw-stats">
        <span id="disk-usage">—</span>
        <span id="disk-minmax">—</span>
      </div>
    </div>

    <div class="sys-widget" data-metric="net">
      <div class="sw-head">
        <span class="sw-label">Сеть (↓ / ↑)</span>
        <span class="sw-icon">🌐</span>
      </div>
      <div class="sw-value sw-value-sm" id="net-value">—</div>
      <svg class="sw-graph" id="net-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
      <div class="sw-stats">
        <span id="net-in">↓ —</span>
        <span id="net-out">↑ —</span>
      </div>
    </div>

    <div class="sys-widget" data-metric="uptime">
      <div class="sw-head">
        <span class="sw-label">Uptime</span>
        <span class="sw-icon">⏱</span>
      </div>
      <div class="sw-split">
        <div class="sw-part">
          <span class="sw-part-label">Uptime сервера</span>
          <span class="sw-part-value" id="uptime-value">—</span>
        </div>
        <div class="sw-part">
          <span class="sw-part-label">Uptime Bot4VPS</span>
          <span class="sw-part-value" id="uptime-service">—</span>
        </div>
      </div>
    </div>
  `;
}

async function updateSystemData() {
  try {
    const data = await j('/api/system');
    if (!data.ok) return;

    document.getElementById('cpu-value').textContent = data.cpu + '%';
    document.getElementById('cpu-temp').textContent = data.temp || '—';
    document.getElementById('ram-value').textContent = data.ram_pct + '%';
    document.getElementById('ram-usage').textContent = data.ram || '—';
    document.getElementById('disk-value').textContent = data.disk_pct + '%';
    document.getElementById('disk-usage').textContent = data.disk || '—';
    document.getElementById('net-value').textContent = data.traffic || '—';

    const ipEl = document.getElementById('host-ip');
    if (ipEl) ipEl.textContent = data.ip || '—';

    document.getElementById('uptime-value').textContent =
      formatUptime(data.uptime_seconds);
    // Синхронизируем базу счётчика; сама отрисовка — в tickServiceUptime.
    const svc = data.service_uptime_seconds;
    svcUptimeBase = (svc === null || svc === undefined) ? null : svc;
    svcUptimeAt = performance.now();
    tickServiceUptime();

    updateHistory('cpu', data.cpu);
    updateHistory('ram', data.ram_pct);
    updateHistory('disk', data.disk_pct);
    updateHistory('netRx', data.net_rx ?? 0);
    updateHistory('netTx', data.net_tx ?? 0);

    updateGraph('cpu', systemHistory.cpu, WIDGET_COLORS.cpu);
    updateGraph('ram', systemHistory.ram, WIDGET_COLORS.ram);
    updateGraph('disk', systemHistory.disk, WIDGET_COLORS.disk);
    updateNetGraph(systemHistory.netRx, systemHistory.netTx);

    updateMinMax('cpu', systemHistory.cpu);
    updateMinMax('ram', systemHistory.ram);
    updateMinMax('disk', systemHistory.disk);
    updateNetStats(data);

    renderBasicInfo(data);
    renderServices(data);
  } catch (err) {
    console.error('System data update failed:', err);
  }
}

function updateHistory(metric, value) {
  const arr = systemHistory[metric];
  arr.push(value);
  if (arr.length > HISTORY_MAX) arr.shift();
}

function updateGraph(id, data, color) {
  const svg = document.getElementById(id + '-graph');
  if (!svg || data.length === 0) return;

  const w = 200;
  const h = 44;
  const max = Math.max(...data, 10);
  const step = w / Math.max(data.length - 1, 1);

  const gridLines = [0, 22, 44].map(y =>
    `<line x1="0" y1="${y}" x2="200" y2="${y}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>`
  ).join('');

  svg.innerHTML = `
    ${gridLines}
    <polyline points="${data.map((v, i) => `${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`).join(' ')}"
              fill="none" stroke="${color}" stroke-width="1.5" />
  `;
}

function humanRate(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  const units = ['Б', 'КБ', 'МБ', 'ГБ'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}/с`;
}

function updateNetStats(data) {
  const inEl = document.getElementById('net-in');
  const outEl = document.getElementById('net-out');
  if (inEl) inEl.textContent = '↓ ' + humanRate(data.net_rx);
  if (outEl) outEl.textContent = '↑ ' + humanRate(data.net_tx);
}

function updateNetGraph(rxData, txData) {
  const svg = document.getElementById('net-graph');
  if (!svg || rxData.length === 0) return;

  const w = 200;
  const h = 44;
  const allValues = [...rxData, ...txData].filter(v => v !== null);
  const max = allValues.length > 0 ? Math.max(...allValues, 10) : 10;
  const step = w / Math.max(rxData.length - 1, 1);

  const gridLines = [0, 22, 44].map(y =>
    `<line x1="0" y1="${y}" x2="200" y2="${y}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>`
  ).join('');

  const rxPoints = rxData.map((v, i) => {
    const val = v ?? 0;
    return `${(i * step).toFixed(1)},${(h - (val / max) * h).toFixed(1)}`;
  }).join(' ');

  const txPoints = txData.map((v, i) => {
    const val = v ?? 0;
    return `${(i * step).toFixed(1)},${(h - (val / max) * h).toFixed(1)}`;
  }).join(' ');

  svg.innerHTML = `
    ${gridLines}
    <polyline points="${rxPoints}" fill="none" stroke="#10b981" stroke-width="1.5" opacity="0.8"/>
    <polyline points="${txPoints}" fill="none" stroke="#10b981" stroke-width="1.5" opacity="0.5"/>
  `;
}

/** Перерисовывает аптайм сервиса раз в секунду между ответами бэкенда. */
function tickServiceUptime() {
  const el = document.getElementById('uptime-service');
  if (!el) return;
  if (svcUptimeBase === null) { el.textContent = '—'; return; }
  const drift = (performance.now() - svcUptimeAt) / 1000;
  el.textContent = formatUptime(svcUptimeBase + drift);
}

function formatUptime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  // Первую минуту — «1 секунда … 59 секунд» словами, чтобы свежий
  // перезапуск не выглядел как «0с». С минуты и дальше — компактно
  // («5д 0ч 21м»), иначе длинная строка не влезает в плитку виджета.
  if (d === 0 && h === 0 && m === 0) {
    const sec = s % 60;
    return `${sec} ${plural(sec, 'секунда', 'секунды', 'секунд')}`;
  }
  if (d === 0 && h === 0) return `${m}м ${s % 60}с`;
  if (d === 0) return `${h}ч ${m}м`;
  return `${d}д ${h}ч ${m}м`;
}

function updateMinMax(metric, data) {
  if (data.length === 0) return;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const el = document.getElementById(metric + '-minmax');
  if (el) el.textContent = `Min: ${min.toFixed(1)}% / Max: ${max.toFixed(1)}%`;
}

function renderBasicInfo(data) {
  const el = document.getElementById('system-basic-info');
  if (!el) return;

  el.innerHTML = `
    <div class="info-row">
      <span class="info-label">Имя сервера</span>
      <span class="info-value">${esc(data.hostname || '—')}</span>
    </div>
    <div class="info-row">
      <span class="info-label">IP</span>
      <span class="info-value copy-value" data-copy="${esc(data.ip || '')}">${esc(data.ip || '—')}</span>
    </div>
    <div class="info-row">
      <span class="info-label">ОС</span>
      <span class="info-value">${esc(data.os || '—')}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Версия ОС</span>
      <span class="info-value">${esc(data.os_version || '—')}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Ядро</span>
      <span class="info-value">${esc(data.kernel || '—')}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Время сервера</span>
      <span class="info-value">${esc(data.server_time || '—')}</span>
    </div>
    <div class="info-row">
      <span class="info-label">Uptime</span>
      <span class="info-value">${formatUptime(data.uptime_seconds || 0)}</span>
    </div>
  `;

  el.querySelectorAll('.copy-value').forEach(elem => {
    elem.style.cursor = 'pointer';
    elem.onclick = () => {
      const text = elem.dataset.copy;
      if (text) writeClipboard(text)
        .then(() => toast('Скопировано', true))
        .catch(() => toast('Не удалось скопировать', false));
    };
  });
}

function renderServices(data) {
  const el = document.getElementById('system-services');
  if (!el) return;

  const bot = data.bot || {};
  const botOk = !!bot.ok;
  let botLabel;
  if (botOk) botLabel = 'Работает';
  else if (bot.state === 'disabled' || bot.detail === 'Выключен') botLabel = 'Выключен';
  else botLabel = bot.error ? `Ошибка · ${bot.error}` : 'Ошибка';
  const webOk = !!data.web?.ok;
  const webDetail = (data.web && data.web.detail) || (webOk ? 'Работает' : 'Ошибка');
  const rows = [
    { name: 'Telegram-бот', ok: botOk, label: botLabel, off: botLabel === 'Выключен' },
    { name: 'Web', ok: webOk, label: webDetail, off: false },
  ];

  el.innerHTML = rows.map(r => {
    let cls = 'err';
    if (r.ok) cls = 'ok';
    else if (r.off) cls = 'off';
    return `
    <div class="service-item">
      <span class="service-name">${esc(r.name)}</span>
      <span class="service-status ${cls}">
        <span class="svc-dot ${cls}"></span>${esc(r.label)}
      </span>
    </div>`;
  }).join('');
}

async function loadMonitorConfig() {
  const el = document.getElementById('monitor-cfg');
  if (!el) return;
  try {
    renderMonitor(await j('/api/monitor/config'));
  } catch (err) {
    el.innerHTML = '<div class="empty">Не удалось загрузить настройки</div>';
  }
}

/* navigator.clipboard существует только в защищённом контексте (HTTPS или
   localhost). Веб-панель обычно открывают по http://<ip>:порт, где этого API
   нет вовсе — прежний вызов падал синхронным TypeError. Поэтому пробуем
   современный путь, а при его отсутствии — скрытый textarea + execCommand. */
function writeClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, ta.value.length);
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('execCommand failed'));
    } catch (e) {
      reject(e);
    }
  });
}

function copyIpAddress() {
  const btn = document.getElementById('btn-copy-ip');
  const ipEl = document.getElementById('host-ip');
  if (!ipEl) return;
  const ip = ipEl.textContent.trim();
  if (!ip || ip === '—') {
    toast('IP-адрес недоступен', false);
    return;
  }
  writeClipboard(ip).then(() => {
    toast('Скопировано', true);
    // Короткая подсветка самой кнопки — подтверждение без отдельного окна.
    if (btn) {
      btn.classList.add('copied');
      setTimeout(() => btn.classList.remove('copied'), 1200);
    }
  }).catch(() => {
    toast('Не удалось скопировать', false);
  });
}

async function restartBotService() {
  if (!await confirmAction({ message: 'Перезапустить службу bot4vps?' })) return;
  try {
    const res = await j('/api/system/restart', { method: 'POST' });
    toast(res.message || 'Служба перезапускается', true);
  } catch (err) {
    toast('Ошибка при перезапуске службы', false);
  }
}

// ---------------- журнал bot4vps ----------------
// Поток — только чтение: SSE /api/system/journal отдаёт строки journalctl.
let journalSrc = null;
const JOURNAL_MAX_LINES = 2000;   // старые строки режем, чтобы DOM не пух

function journalAppend(text, cls) {
  const out = document.getElementById('journal-output');
  if (!out) return;
  // Автопрокрутка только если пользователь уже внизу — иначе не дёргаем.
  const atBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 24;
  const el = document.createElement('div');
  el.className = 'journal-line' + (cls ? ' ' + cls : '');
  el.textContent = text;
  out.appendChild(el);
  while (out.childElementCount > JOURNAL_MAX_LINES) out.firstElementChild.remove();
  if (atBottom) out.scrollTop = out.scrollHeight;
}

function journalLive(on) {
  const ind = document.getElementById('journal-live');
  if (ind) ind.hidden = !on;
  const stop = document.getElementById('btn-journal-stop');
  if (stop) stop.disabled = !on;
}

// Обрывает поток, но оставляет вывод на экране (кнопка «Остановить»).
function journalStop(note) {
  if (journalSrc) {
    journalSrc.close();
    journalSrc = null;
    if (note) journalAppend('— поток остановлен —', 'sys');
  }
  journalLive(false);
}

function journalOpen() {
  const modal = document.getElementById('journal-modal');
  if (!modal) return;
  journalStop(false);                // страховка от второго потока
  const out = document.getElementById('journal-output');
  if (out) out.textContent = '';
  journalAppend('Загрузка журнала…', 'sys');
  if (out && out.lastElementChild) out.lastElementChild.id = 'journal-placeholder';
  modal.classList.add('open');
  modal.style.zIndex = '200';

  journalSrc = new EventSource('/api/system/journal');
  journalLive(true);
  let first = true;
  journalSrc.addEventListener('hello', () => {
    // снимаем только заглушку: при переподключении накопленное не теряем
    document.getElementById('journal-placeholder')?.remove();
    journalLive(true);
  });
  journalSrc.addEventListener('line', ev => {
    if (first) { first = false; journalLive(true); }
    journalAppend(ev.data, null);
  });
  journalSrc.addEventListener('fail', ev => {
    journalAppend(ev.data || 'Не удалось прочитать журнал', 'err');
    journalStop(false);
  });
  journalSrc.addEventListener('end', ev => {
    // journalctl завершился сам — закрываем поток, чтобы EventSource
    // не переподключался и не запускал процесс снова и снова.
    journalAppend(ev.data === '0'
      ? '— журнал завершён —'
      : `— journalctl завершился с кодом ${ev.data} —`, 'err');
    journalStop(false);
  });
  journalSrc.onerror = () => {
    // EventSource сам переподключается; при закрытом соединении — стоп.
    if (journalSrc && journalSrc.readyState === EventSource.CLOSED) {
      journalAppend('— соединение прервано —', 'err');
      journalStop(false);
    }
  };
}

// Единая точка выхода: любой путь закрытия должен рвать SSE,
// иначе на сервере останется живой journalctl -f.
function journalClose() {
  journalStop(false);
  const modal = document.getElementById('journal-modal');
  if (modal) {
    modal.classList.remove('open');
    modal.style.zIndex = '';
  }
}

function viewJournal() {
  journalOpen();
}
