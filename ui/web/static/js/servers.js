import { j, esc } from './api.js';
import { ansiToHtml } from './ansi.js';
import { toast, showPage, onlineBadge, onlineBadgeWithPing, sslBadge, metricTile, bindPasswordToggles, parseEmoji, confirmAction } from './ui.js';
import { state, setServers, setGroups, setKeys, setOpenServer, setPage, setServerTab } from './state.js';
import { openTerminal, closeTerminal } from './terminal.js';
import { openEventDetail, applyEventsSnapshot } from './monitor.js?v=20260816-task-history-v3';
import { openTaskLog, cancelTaskAPI } from './tasks.js?v=20260816-task-history-v3';

/** @deprecated use state.servers */
export let lastServers = state.servers;
export let lastGroups = state.groups;
export let lastKeys = state.keys;
export let openServerId = null;
export let watchTaskId = null;
let metricsTimer = null;
let logTimer = null;
// Наблюдение за running_task карточки сервера: id последней замеченной задачи.
// Нужно, чтобы поймать МОМЕНТ её завершения — установка/удаление сервиса меняет
// Quick Actions, но поллинг wireguard.js/docker.js к этому времени уже погашен
// stopWgTimers/stopDockerTimers при уходе со страницы сервиса.
let taskWatchTimer = null;
let lastRunningTaskId = null;
let historyRenderRevision = 0;
let quickActionsRevision = 0;

// История метрик для графиков (последние 20 значений)
const metricsHistory = {
  cpu: [],
  ram: [],
  disk: []
};
const HISTORY_MAX = 20;

// Форматирование uptime в русском формате (5д 6ч 8м)
function formatUptime(uptime) {
  if (!uptime || uptime === 'N/A') return '—';

  const dMatch = uptime.match(/(\d+)\s+day/);
  const hMatch = uptime.match(/(\d+)\s+hour/);
  const mMatch = uptime.match(/(\d+)\s+minute/);

  const parts = [];
  if (dMatch) parts.push(dMatch[1] + 'д');
  if (hMatch) parts.push(hMatch[1] + 'ч');
  if (mMatch) parts.push(mMatch[1] + 'м');

  return parts.length > 0 ? parts.join(' ') : uptime;
}

// Копирование в буфер обмена (как в monitor.js)
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

function copyServerIp() {
  const btn = document.getElementById('btn-copy-srv-ip');
  const ipEl = document.getElementById('srv-ip');
  if (!ipEl) return;
  const ip = ipEl.textContent.trim();
  if (!ip || ip === '—') {
    toast('IP-адрес недоступен', false);
    return;
  }
  writeClipboard(ip).then(() => {
    toast('Скопировано', true);
    if (btn) {
      btn.classList.add('copied');
      setTimeout(() => btn.classList.remove('copied'), 1200);
    }
  }).catch(() => {
    toast('Не удалось скопировать', false);
  });
}

export async function loadGroupsAndKeys() {
  try { setGroups((await j('/api/groups')).groups || []); } catch { setGroups([]); }
  try { setKeys((await j('/api/keys')).keys || []); } catch { setKeys([]); }
  lastGroups = state.groups;
  lastKeys = state.keys;
}

export async function loadServers() {
  try {
    const data = await j('/api/servers');
    setServers(data.servers || []);
    lastServers = state.servers;
    renderServers();
  } catch (e) {
    document.getElementById('servers').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function filteredServers() {
  const q = (state.serverQuery || '').trim().toLowerCase();
  const list = state.servers;
  if (!q) return list;
  return list.filter(s => {
    const blob = [s.name, s.host, s.group, s.user, s.id].map(x => String(x || '').toLowerCase()).join(' ');
    return q.split(/\s+/).every(part => blob.includes(part));
  });
}

function pluralizeServers(n) {
  if (n % 10 === 1 && n % 100 !== 11) return 'сервер';
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return 'сервера';
  return 'серверов';
}

export function renderServersFromState() { renderServers(); }

export function renderServers() {
  const el = document.getElementById('servers');
  const list = filteredServers();
  const hint = document.getElementById('server-search-hint');
  if (hint) hint.textContent = state.serverQuery.trim() ? `${list.length} из ${state.servers.length}` : '';
  if (!state.servers.length) { el.innerHTML = '<div class="empty">Нет серверов</div>'; return; }
  if (!list.length) { el.innerHTML = '<div class="empty">Ничего не найдено</div>'; return; }
  const by = {};
  list.forEach(s => { const g = s.group || '(без группы)'; (by[g] = by[g] || []).push(s); });

  // Получаем настройки отображения групп из localStorage
  let groupOrder = [];
  let visibleGroups = null;
  try {
    const savedOrder = localStorage.getItem('bot4vps_group_order');
    const savedVisible = localStorage.getItem('bot4vps_visible_groups');
    if (savedOrder) groupOrder = JSON.parse(savedOrder);
    if (savedVisible) visibleGroups = new Set(JSON.parse(savedVisible));
  } catch (_) {}

  // Формируем список групп для отображения
  const allGroups = Object.keys(by);
  let orderedGroups = [];

  // Сначала добавляем группы в сохранённом порядке
  groupOrder.forEach(g => {
    if (by[g]) orderedGroups.push(g);
  });

  // Добавляем новые группы, которых нет в сохранённом порядке
  allGroups.forEach(g => {
    if (!orderedGroups.includes(g)) orderedGroups.push(g);
  });

  // Фильтруем по видимости, если настройка задана
  if (visibleGroups) {
    orderedGroups = orderedGroups.filter(g => visibleGroups.has(g));
  }

  let h = '';
  orderedGroups.forEach(g => {
    const count = by[g].length;
    h += `<div class="group-title">Группа ${esc(g)} · ${count} ${pluralizeServers(count)}</div><div class="grid">`;
    h += by[g].map(s => `<div class="card clickable" data-sid="${esc(s.id)}">
      <h3>${esc(s.name)}</h3>
      <div class="row">${esc(s.host || '—')}</div>
      <div class="row" style="margin-top:.4rem;gap:.5rem;flex-wrap:nowrap">
        ${onlineBadgeWithPing(s.online, s.id)}
        ${s.certificate_check ? sslBadge(s) : ''}
      </div>
      ${s.has_running ? '<div class="row">▶ идёт задача</div>' : ''}
    </div>`).join('');
    h += '</div>';
  });
  el.innerHTML = h;
  el.querySelectorAll('[data-sid]').forEach(c => c.onclick = () => openServer(c.dataset.sid));
  list.forEach(s => fillPing(s.id));
}

async function fillPing(id) {
  const el = document.getElementById('ping-' + id);
  if (!el) return;
  try {
    const r = await j('/api/servers/' + encodeURIComponent(id) + '/ping');
    if (r.ok) { el.textContent = r.ms + ' ms'; el.className = 'ping ok'; }
    else { el.textContent = 'timeout'; el.className = 'ping bad'; }
  } catch { el.textContent = '—'; el.className = 'ping'; }
}

export function setServerQuery(q) {
  state.serverQuery = q;
  renderServers();
}

export function stopWatchers() {
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
  if (logTimer) { clearInterval(logTimer); logTimer = null; }
  if (taskWatchTimer) { clearInterval(taskWatchTimer); taskWatchTimer = null; }
  lastRunningTaskId = null;
}

/**
 * Следит за running_task открытого сервера и перерисовывает «Быстрые действия»,
 * когда задача завершилась.
 *
 * Зачем: установка/удаление сервиса ставится в очередь сервера, а поллинг задачи
 * в wireguard.js/docker.js гасится stopWgTimers/stopDockerTimers, как только
 * пользователь уходит со страницы сервиса (app.js). Уйдя в карточку сервера до
 * конца удаления, о завершении узнать больше некому — этот наблюдатель закрывает
 * пробел, не возвращая поллинг сервисов.
 *
 * /api/services/{sid}/status запрашивается ТОЛЬКО в момент смены задачи (id стал
 * другим или задач больше нет), а не на каждом тике.
 */
async function watchRunningTask() {
  if (!openServerId) return;
  try {
    const d = await j('/api/servers/' + encodeURIComponent(openServerId));
    const id = d.running_task?.id || null;
    const changed = id !== lastRunningTaskId;
    if (changed) {
      const finished = lastRunningTaskId !== null;   // была задача — теперь другая/нет
      lastRunningTaskId = id;
      if (finished) await renderQuickActions(openServerId);
    }
    // События журнала — в том же цикле watcher'а (раз в ~3 с),
    // без отдельного polling: старт/ход/финиш задачи и прочие события сервера.
    refreshOpenServerEvents();
  } catch { /* повторим на следующем тике */ }
}

function startWatchers() {
  stopWatchers();
  refreshMetrics();
  metricsTimer = setInterval(refreshMetrics, 5000);
  watchRunningTask();                              // зафиксировать текущую задачу + события
  taskWatchTimer = setInterval(watchRunningTask, 3000);
}

/**
 * Блок «Быстрые действия» карточки сервера.
 *
 * Порядок кнопок фиксирован: статусы WG/Docker ждём через await ДО отрисовки,
 * иначе кнопки сервисов дорисовывались бы позже остальных и прыгали.
 * Вынесено из openServer(), чтобы после установки/удаления сервиса можно было
 * перерисовать только этот блок — без showPage('server'), который выдернул бы
 * пользователя со страницы WireGuard/Docker.
 */
async function renderQuickActions(id) {
  const qa = document.getElementById('srv-quick-actions');
  if (!qa) return;

  // Несколько источников могут запросить обновление одновременно (openServer,
  // watcher задачи, refreshAfterServiceChange). Собираем кнопки вне DOM и
  // публикуем только результат последнего вызова, чтобы stale-render не дописал
  // дубли после своих await.
  const revision = ++quickActionsRevision;
  const fragment = document.createDocumentFragment();
  const addAction = (text, icon, cls, fn, styles) => {
    const b = document.createElement('button');
    b.innerHTML = icon ? `${icon} ${text}` : text;
    if (cls) b.className = cls;
    b.onclick = fn;
    b.style.textAlign = 'left';
    if (styles) Object.assign(b.style, styles);
    fragment.appendChild(b);
  };

  const [wireGuardInstalled, dockerInstalled] = await Promise.all([
    checkWireGuardStatus(id),
    checkDockerStatus(id),
  ]);
  if (revision !== quickActionsRevision) return;

  // 1. Запустить скрипт
  addAction('Запустить скрипт', '▶', 'secondary',
    () => import('./scripts.js?v=20260816-server-singleton-v1').then(m => m.openRunModal(id, null)));

  // 2. WireGuard
  if (wireGuardInstalled) {
    addAction('Панель управления WireGuard', '🔒', 'secondary', () => openWireGuardServer(id));
  } else {
    addAction('Установить WireGuard', '🔒', 'secondary', () => confirmInstallWireGuard(id));
  }

  // 3. Docker
  if (dockerInstalled) {
    addAction('Панель управления Docker', '🐳', 'secondary', () => openDockerServer(id));
  } else {
    addAction('Установить Docker', '🐳', 'secondary', () => confirmInstallDocker(id));
  }

  // 4. Изменить настройки
  addAction('Изменить настройки', '⚙', 'secondary', openEditServerModal);

  // 5. Перезагрузить сервер
  addAction('Перезагрузить сервер', '🔄', 'secondary', async () => {
    const approved = await confirmAction({
      title: 'Перезагрузить сервер?',
      message: 'Сервер будет перезагружен.',
      confirmText: 'Перезагрузить',
    });
    if (!approved) return;
    try {
      const r = await j('/api/servers/' + encodeURIComponent(id) + '/reboot', { method: 'POST' });
      toast(r.ok ? 'Сервер перезагружается' : 'Ошибка', r.ok);
    } catch (e) { toast(e.message, false); }
  });

  // 6. Удалить сервер
  addAction('Удалить сервер', '🗑', '', deleteServer,
    { background: 'rgba(255, 59, 92, 0.1)', color: '#ff5c7c' });

  if (revision !== quickActionsRevision) return;
  qa.replaceChildren(fragment);
}


// ---------------------------------------------------------------
// Недавние события сервера (фильтр журнала по server_id)
// ---------------------------------------------------------------
let _srvEventsExpanded = false;
let _srvEventsList = [];
let _srvEventsServerId = null;

function _formatEventTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) {
    // ISO без таймзоны / уже строка
    const s = String(ts).replace('T', ' ');
    return s.length >= 16 ? s.slice(11, 16) : s.slice(0, 16);
  }
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startThat = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((startToday - startThat) / 86400000);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  if (diffDays === 0) return `${hh}:${mm}`;
  if (diffDays === 1) return 'вчера';
  const dd = String(d.getDate()).padStart(2, '0');
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  if (d.getFullYear() === now.getFullYear()) return `${dd}.${mo}`;
  return `${dd}.${mo}.${d.getFullYear()}`;
}

function _eventMatchesServer(e, serverId) {
  if (!e || !serverId) return false;
  const d = e.details || {};
  if (d.server_id != null && String(d.server_id) === String(serverId)) return true;
  // некоторые события кладут id только в корень
  if (e.server_id != null && String(e.server_id) === String(serverId)) return true;
  return false;
}

function _paintServerEvents() {
  const el = document.getElementById('srv-recent-events');
  if (!el) return;
  const list = _srvEventsList;
  if (!list.length) {
    el.innerHTML = '<div class="empty">Недавних событий нет</div>';
    return;
  }
  const visible = _srvEventsExpanded ? list : list.slice(0, 5);
  const rows = visible.map(e => {
    const eid = e.id || '';
    const title = e.title || 'Событие';
    const time = _formatEventTime(e.timestamp);
    return `<div class="srv-event-row" data-event-id="${esc(eid)}" title="Открыть детали">
      <span class="srv-event-title">${esc(title)}</span>
      <span class="srv-event-time">${esc(time)}</span>
    </div>`;
  }).join('');
  let toggle = '';
  if (list.length > 5) {
    toggle = `<button type="button" class="srv-events-toggle" id="srv-events-toggle">
      ${_srvEventsExpanded ? 'Свернуть ↑' : 'Развернуть ↓'}
    </button>`;
  }
  el.innerHTML = `<div class="srv-event-list">${rows}</div>${toggle}`;
  el.querySelectorAll('[data-event-id]').forEach(node => {
    node.onclick = () => openEventDetail(node.dataset.eventId);
  });
  const btn = document.getElementById('srv-events-toggle');
  if (btn) {
    btn.onclick = () => {
      _srvEventsExpanded = !_srvEventsExpanded;
      _paintServerEvents();
    };
  }
}

async function loadServerRecentEvents(serverId, { silent = false } = {}) {
  const el = document.getElementById('srv-recent-events');
  if (!el) return;
  _srvEventsServerId = serverId;
  if (!silent) {
    _srvEventsExpanded = false;
    el.innerHTML = '<div class="empty">Загрузка…</div>';
  }
  try {
    // Берём с запасом: потом фильтруем по server_id
    const data = await j('/api/events?limit=100');
    const all = data.events || [];
    // чтобы openEventDetail нашёл событие в общем кэше журнала
    applyEventsSnapshot(all);
    const filtered = all
      .filter(e => _eventMatchesServer(e, serverId))
      .sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
    if (_srvEventsServerId !== serverId) return; // устаревший ответ
    // silent: не мигаем UI, если набор id не изменился
    if (silent) {
      const newIds = filtered.map(e => e.id).join(',');
      const oldIds = _srvEventsList.map(e => e.id).join(',');
      if (newIds === oldIds) return;
    }
    _srvEventsList = filtered;
    _paintServerEvents();
  } catch (e) {
    if (!silent && _srvEventsServerId === serverId) {
      el.innerHTML = '<div class="empty">' + esc(e.message || 'Ошибка') + '</div>';
    }
  }
}

/** Тихое обновление блока событий открытой карточки (без сброса «Развернуть»). */

export function refreshOpenServerEvents() {
  if (!openServerId) return;
  loadServerRecentEvents(openServerId, { silent: true });
}

/** Обновить индикатор SSH в карточке и на странице терминала. */
export function renderSshStatus(ssh, error) {
  const label = (ok) => {
    if (ok === true) return 'SSH: <span class="ssh-dot ok"></span> OK';
    if (ok === false) {
      const tip = error ? ` title="${esc(String(error).slice(0, 120))}"` : '';
      return `SSH: <span class="ssh-dot err"${tip}></span> недоступен`;
    }
    return 'SSH: <span class="ssh-dot"></span> …';
  };
  const html = label(ssh);
  const card = document.getElementById('srv-ssh-status');
  if (card) card.innerHTML = html;
  const badge = document.getElementById('term-ssh-badge');
  if (badge) badge.innerHTML = html;

  const sep = document.getElementById('srv-term-sep');
  const btn = document.getElementById('btn-open-terminal');
  const showTerm = ssh === true;
  if (sep) sep.classList.toggle('hidden', !showTerm);
  if (btn) {
    const sid = currentOpenServerId();
    if (sid) btn.dataset.serverId = String(sid);
    btn.classList.toggle('hidden', !showTerm);
  }
}

/**
 * Полноэкранный терминал в области контента (page-terminal).
 * Тот же openTerminal() / WebSocket / xterm — без новой реализации.
 */
function currentOpenServerId() {
  const terminalButton = document.getElementById('btn-open-terminal');
  return openServerId
    || state.openServerId
    || state.openServerData?.server?.id
    || window._openServerData?.server?.id
    || terminalButton?.dataset.serverId
    || null;
}

export function openServerTerminal() {
  const sid = currentOpenServerId();
  if (!sid) {
    toast('Сначала откройте сервер', false);
    return;
  }

  // Карточка уже может быть отрисована, даже если module-level binding
  // потерялся после перерисовки. Восстанавливаем его перед openTerminal().
  openServerId = sid;
  const data = state.openServerData || window._openServerData;
  const name = data?.server?.name || sid;
  const el = document.getElementById('term-server-name');
  if (el) el.textContent = name;
  // ssh badge уже выставлен renderSshStatus
  setPage('terminal');
  showPage('terminal');
  // xterm fit после показа страницы
  requestAnimationFrame(() => openTerminal());
}

export function backFromTerminal() {
  closeTerminal();
  if (openServerId) {
    setPage('server');
    showPage('server');
    // возобновить метрики карточки
    startWatchers();
  } else {
    setPage('servers');
    showPage('servers');
  }
}


export async function openServer(id) {
  openServerId = id;
  setOpenServer(id, null);
  const terminalButton = document.getElementById('btn-open-terminal');
  if (terminalButton) terminalButton.dataset.serverId = String(id);

  // Очищаем историю метрик для нового сервера
  metricsHistory.cpu = [];
  metricsHistory.ram = [];
  metricsHistory.disk = [];

  try {
    const data = await j('/api/servers/' + encodeURIComponent(id));
    const s = data.server || {}, mon = data.monitor || {};
    const sys = mon.system || {};
    state.openServerData = data; window._openServerData = data;

    // Заголовок и IP
    document.getElementById('srv-title').textContent = s.name || id;
    const ipEl = document.getElementById('srv-ip');
    if (ipEl) ipEl.textContent = mon.host_ip || s.host || '—';

    // Информация о системе
    const infoEl = document.getElementById('srv-info');
    if (infoEl) {
      // Объединяем OS и OS Version
      const osName = sys.os || '—';
      const osVer = sys.os_version || '';
      const osFull = osVer && osVer !== '—' ? `${osName.charAt(0).toUpperCase() + osName.slice(1)} ${osVer}` : osName;

      let rows = `
        <div class="info-row">
          <span class="info-label">Имя сервера</span>
          <span class="info-value">${esc(sys.hostname || s.name || '—')}</span>
        </div>
        <div class="info-row">
          <span class="info-label">IP</span>
          <span class="info-value">
            <span id="srv-info-ip" class="copyable-value" title="Нажмите, чтобы скопировать">
              ${esc(mon.host_ip || s.host || '—')}
            </span>
          </span>
        </div>
        <div class="info-row">
          <span class="info-label">Порт</span>
          <span class="info-value">${esc(s.port || 22)}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Пользователь</span>
          <span class="info-value">${esc(s.user || '—')}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Группа</span>
          <span class="info-value">${esc(s.group || '—')}</span>
        </div>
        <div class="info-row">
          <span class="info-label">ОС</span>
          <span class="info-value">${esc(osFull)}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Ядро</span>
          <span class="info-value">${esc(sys.kernel || '—')}</span>
        </div>
      `;

      // Добавляем SSL если есть сертификат
      const cert = mon.certificate;
      if (cert && mon.ssl_host) {
        rows += `
          <div class="info-row">
            <span class="info-label">Домен</span>
            <span class="info-value">${esc(mon.ssl_host)}</span>
          </div>
          <div class="info-row">
            <span class="info-label">SSL</span>
            <span class="info-value">${cert.days_left ? cert.days_left + ' дней' : '—'}</span>
          </div>
        `;
      }

      infoEl.innerHTML = rows;
      const infoIp = document.getElementById('srv-info-ip');
      if (infoIp) {
        infoIp.onclick = () => {
          const ip = infoIp.textContent.trim();

          if (!ip || ip === '—') {
            toast('IP-адрес недоступен', false);
            return;
          }

          writeClipboard(ip)
            .then(() => toast('Скопировано', true))
            .catch(() => toast('Не удалось скопировать', false));
        };
      }
    }

    await renderQuickActions(id);
    loadServerRecentEvents(id);

    if (data.running_task) { watchTaskId = data.running_task.id; state.watchTaskId = watchTaskId; }
    await loadGroupsAndKeys();
    // SSH-статус из monitor (сетевой online — ещё не SSH); уточним probe ниже
    renderSshStatus(null);
    showPage('server');
    setPage('server');
    metricsNA('загрузка...');
    startWatchers();
    // Точный SSH — существующий /probe (как в refreshMetrics)
    j('/api/servers/' + encodeURIComponent(id) + '/probe').then(p => {
      if (openServerId !== id) return;
      const info = p.info || {};
      renderSshStatus(!!info.ssh, info.ssh_error || p.ssh_error_human || '');
    }).catch(() => {
      if (openServerId === id) renderSshStatus(false, 'probe failed');
    });
  } catch (e) { toast(e.message, false); }
}

// Установлен ли сервис на сервере. installed лежит в s.status (см. checkCard
// в wireguard.js/docker.js), не в корне объекта сервера.
// cache:'no-store' обязателен: кнопки перерисовываются сразу после установки или
// удаления, а браузер иначе отдаёт сохранённый ответ того же GET.
async function checkServiceInstalled(serviceId, serverId) {
  try {
    const r = await j(`/api/services/${serviceId}/status`, { cache: 'no-store' });
    const srv = r.servers?.find(s => s.id === serverId);
    return srv?.status?.installed === true;
  } catch {
    return false;
  }
}

const checkWireGuardStatus = id => checkServiceInstalled('wireguard', id);
const checkDockerStatus = id => checkServiceInstalled('docker', id);

// Открыть панель WireGuard для сервера
function openWireGuardServer(serverId) {
  import('./wireguard.js?v=20260816-service-singleton-v1').then(m => m.openWgServerById(serverId));
}

// Открыть модальное окно установки WireGuard
function confirmInstallWireGuard(serverId) {
  import('./wireguard.js?v=20260816-service-singleton-v1')
    .then(m => m.openInstall(serverId))
    .catch(err => console.error('Ошибка загрузки модуля WireGuard:', err));
}

// Открыть панель Docker для сервера
function openDockerServer(serverId) {
  import('./docker.js?v=20260816-service-singleton-v1').then(m => m.openDockerServerById(serverId));
}

// Открыть модальное окно установки Docker
function confirmInstallDocker(serverId) {
  import('./docker.js?v=20260816-service-singleton-v1')
    .then(m => m.openInstall(serverId))
    .catch(err => console.error('Ошибка загрузки модуля Docker:', err));
}

// Открыть модальное окно редактирования сервера
function openEditServerModal() {
  const modal = document.getElementById('edit-server-modal');
  if (modal) {
    fillSettingsForm();
    modal.classList.add('open');
  }
}

/** @deprecated вкладки карточки убраны; terminal → openServerTerminal() */
export function showTab(tab) {
  if (tab === 'terminal') {
    openServerTerminal();
    return;
  }
  // log/queue/status — просто карточка сервера
  if (openServerId) {
    setPage('server');
    showPage('server');
  }
}

export function lastServerTab() {
  return 'status';
}

function metricsNA(reason) {
  const box = document.getElementById('srv-widgets');
  if (box) {
    box.innerHTML = `
      <div class="sys-widget" data-metric="cpu">
        <div class="sw-head">
          <span class="sw-label">CPU</span>
          <span class="sw-icon">📊</span>
        </div>
        <div class="sw-value">—</div>
        <svg class="sw-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
        <div class="sw-stats"><span></span></div>
      </div>

      <div class="sys-widget" data-metric="ram">
        <div class="sw-head">
          <span class="sw-label">Память</span>
          <span class="sw-icon">💾</span>
        </div>
        <div class="sw-value">—</div>
        <svg class="sw-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
        <div class="sw-stats"><span></span></div>
      </div>

      <div class="sys-widget" data-metric="disk">
        <div class="sw-head">
          <span class="sw-label">Диск</span>
          <span class="sw-icon">💿</span>
        </div>
        <div class="sw-value">—</div>
        <svg class="sw-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
        <div class="sw-stats"><span></span></div>
      </div>

      <div class="sys-widget" data-metric="ping">
        <div class="sw-head">
          <span class="sw-label">Ping</span>
          <span class="sw-icon">📡</span>
        </div>
        <div class="sw-value">—</div>
        <div class="sw-graph-empty"></div>
        <div class="sw-stats"><span></span></div>
      </div>

      <div class="sys-widget" data-metric="uptime">
        <div class="sw-head">
          <span class="sw-label">Время работы</span>
          <span class="sw-icon">⏱</span>
        </div>
        <div class="sw-value">—</div>
        <div class="sw-graph-empty"></div>
        <div class="sw-stats"><span></span></div>
      </div>
    `;
    parseEmoji(box);
  }
}

function updateGraph(containerId, data, color) {
  const svg = document.querySelector(`[data-metric="${containerId}"] .sw-graph`);
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

export async function refreshMetrics() {
  if (!openServerId) return;
  const box = document.getElementById('srv-widgets');
  try {
    const m = await j('/api/servers/' + encodeURIComponent(openServerId) + '/metrics');

    // Получаем ping для сервера
    let pingMs = null;
    let pingType = 'none';
    try {
      const probe = await j('/api/servers/' + encodeURIComponent(openServerId) + '/probe');
      if (probe.info) {
        pingMs = probe.info.ping;
        pingType = probe.info.network || 'none';
      }
    } catch {}

    if (!m.ok) {
      metricsNA(m.error || 'Нет данных метрик');
      return;
    }

    const empty = m.cpu == null && m.ram_pct == null && m.disk_pct == null
      && (!m.load || m.load === 'N/A') && (!m.uptime || m.uptime === 'N/A');
    if (empty) {
      metricsNA('нет данных');
      return;
    }

    // Добавляем в историю для графиков
    if (m.cpu != null) {
      metricsHistory.cpu.push(m.cpu);
      if (metricsHistory.cpu.length > HISTORY_MAX) metricsHistory.cpu.shift();
    }
    if (m.ram_pct != null) {
      metricsHistory.ram.push(m.ram_pct);
      if (metricsHistory.ram.length > HISTORY_MAX) metricsHistory.ram.shift();
    }
    if (m.disk_pct != null) {
      metricsHistory.disk.push(m.disk_pct);
      if (metricsHistory.disk.length > HISTORY_MAX) metricsHistory.disk.shift();
    }

    // Определяем цвет и статус ping
    let pingColor = '#ef4444'; // красный по умолчанию
    let pingStatus = 'Timeout';
    if (pingMs !== null && pingMs > 0) {
      if (pingMs <= 500) {
        pingColor = '#22c55e'; // зеленый
        pingStatus = 'Отлично';
      } else if (pingMs <= 700) {
        pingColor = '#eab308'; // желтый
        pingStatus = 'Норма';
      } else {
        pingStatus = 'Медленно';
      }
    }
    const pingLabel = pingType === 'http' ? 'HTTP' : pingType === 'ping' ? 'ICMP' : 'Ping';

    if (box) {
      box.innerHTML = `
        <div class="sys-widget" data-metric="cpu">
          <div class="sw-head">
            <span class="sw-label">CPU</span>
            <span class="sw-icon">📊</span>
          </div>
          <div class="sw-value">${m.cpu != null ? m.cpu + '%' : '—'}</div>
          <svg class="sw-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
          <div class="sw-stats"><span></span></div>
        </div>

        <div class="sys-widget" data-metric="ram">
          <div class="sw-head">
            <span class="sw-label">Память</span>
            <span class="sw-icon">💾</span>
          </div>
          <div class="sw-value">${m.ram_pct != null ? m.ram_pct + '%' : '—'}</div>
          <svg class="sw-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
          <div class="sw-stats"><span>${m.ram || '—'}</span></div>
        </div>

        <div class="sys-widget" data-metric="disk">
          <div class="sw-head">
            <span class="sw-label">Диск</span>
            <span class="sw-icon">💿</span>
          </div>
          <div class="sw-value">${m.disk_pct != null ? m.disk_pct + '%' : '—'}</div>
          <svg class="sw-graph" viewBox="0 0 200 44" preserveAspectRatio="none"></svg>
          <div class="sw-stats"><span>${m.disk || '—'}</span></div>
        </div>

        <div class="sys-widget" data-metric="ping" style="--ping-color: ${pingColor}">
          <div class="sw-head">
            <span class="sw-label">Ping (${pingLabel})</span>
            <span class="sw-icon">📡</span>
          </div>
          <div class="sw-value" style="color: ${pingColor}">${pingMs !== null && pingMs > 0 ? pingMs + ' ms' : '—'}</div>
          <div class="sw-graph-empty"></div>
          <div class="sw-stats"><span style="color: ${pingColor}">${pingStatus}</span></div>
        </div>

        <div class="sys-widget" data-metric="uptime">
          <div class="sw-head">
            <span class="sw-label">Время работы</span>
            <span class="sw-icon">⏱</span>
          </div>
          <div class="sw-value" style="font-size:1.2rem">${formatUptime(m.uptime)}</div>
          <div class="sw-graph-empty"></div>
          <div class="sw-stats"><span></span></div>
        </div>
      `;
      parseEmoji(box);

      // Рисуем графики
      updateGraph('cpu', metricsHistory.cpu, '#60a5fa');
      updateGraph('ram', metricsHistory.ram, '#f472b6');
      updateGraph('disk', metricsHistory.disk, '#fb923c');
    }
  } catch (e) {
    metricsNA(e.message || 'ошибка');
  }
}

export async function refreshTaskLog() {
  const box = document.getElementById('task-log');
  if (!box) return;
  if (!watchTaskId && openServerId) {
    try {
      const d = await j('/api/servers/' + encodeURIComponent(openServerId));
      if (d.running_task) watchTaskId = d.running_task.id;
    } catch {}
  }
  if (!watchTaskId) { box.textContent = 'Нет активной задачи'; return; }
  try {
    const t = await j('/api/tasks/' + encodeURIComponent(watchTaskId));
    const lines = t.output_lines || [];
    const head = `${esc(t.emoji || '')} ${esc(t.name)} · ${esc(t.status)} · ${esc(t.duration || '')}`;
    const body = lines.length ? lines.map(ansiToHtml).join('\n') : esc('(нет вывода)');
    box.innerHTML = `<div class="tasklog-head">${head}</div><div class="tasklog-body">${'─'.repeat(36)}\n${body}</div>`;
    box.scrollTop = box.scrollHeight;
  } catch (e) { box.textContent = e.message; }
}

async function loadSrvQueue() {
  if (!openServerId) return;
  try {
    const d = await j('/api/servers/' + encodeURIComponent(openServerId));
    const el = document.getElementById('srv-queue');
    const run = d.running_task, q = d.queue || [], st = d.queue_state || {};
    el.innerHTML = `<div class="card" style="min-height:0">
      <div class="row">${run ? esc(run.emoji || '') + ' <b>' + esc(run.name) + '</b>' : 'Нет активной'}</div>
      <div class="progress ${st.paused ? 'paused' : ''}"><i></i></div>
      ${q.map(t => `<div class="row">⏳ ${esc(t.name)}</div>`).join('') || '<div class="row">очередь пуста</div>'}
      <div class="actions">
        <button type="button" class="secondary" data-a="continue">▶</button>
        <button type="button" class="secondary" data-a="retry">🔄</button>
        <button type="button" class="secondary" data-a="clear">⏹</button>
      </div></div>`;
    el.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => {
      try {
        await j('/api/queues/' + encodeURIComponent(openServerId) + '/' + b.dataset.a, { method: 'POST' });
        loadSrvQueue();
      } catch (e) { toast(e.message, false); }
    });
  } catch (e) {
    document.getElementById('srv-queue').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

export async function loadQueues() {
  try {
    const data = await j('/api/queues');
    const el = document.getElementById('queues');
    if (!data.queues.length) { el.innerHTML = '<div class="empty">Нет активных</div>'; return; }
    el.innerHTML = data.queues.map(q => {
      const run = q.running;
      const runningCard = run ? `<div class="card" style="margin-bottom:.5rem;min-height:0;background:var(--hover)">
        <h4 style="margin:0 0 .3rem">${esc(run.emoji || '')} ${esc(run.name)}</h4>
        <div class="row" style="color:var(--muted);font-size:.82rem">⏳ выполняется</div>
        <div class="actions" style="margin-top:.5rem">
          <button type="button" class="secondary" data-task-log="${esc(run.id)}" style="font-size:.8rem">📄 Лог</button>
          <button type="button" class="danger" data-task-cancel="${esc(run.id)}" style="font-size:.8rem">✕ Отменить</button>
        </div>
      </div>` : '';
      const queueCards = (q.queue || []).map(t => `<div class="card" style="margin-bottom:.5rem;min-height:0">
        <h4 style="margin:0 0 .3rem">${esc(t.emoji || '')} ${esc(t.name)}</h4>
        <div class="row" style="color:var(--muted);font-size:.82rem">⏸ в очереди</div>
        <div class="actions" style="margin-top:.5rem">
          <button type="button" class="danger" data-task-cancel="${esc(t.id)}" style="font-size:.8rem">✕ Отменить</button>
        </div>
      </div>`).join('');
      return `<div class="card" style="margin-bottom:1rem"><h3>${esc(q.server_name)}</h3>
        <div class="progress ${q.paused ? 'paused' : ''}"><i></i></div>
        ${runningCard}${queueCards}
        <div class="actions" style="margin-top:.8rem;border-top:1px solid var(--border);padding-top:.8rem">
          <button type="button" class="secondary" data-q="${esc(q.server_id)}" data-a="continue">▶ Возобновить</button>
          <button type="button" class="secondary" data-q="${esc(q.server_id)}" data-a="retry">🔄 Повтор</button>
          <button type="button" class="secondary" data-q="${esc(q.server_id)}" data-a="clear">⏹ Очистить очередь</button>
        </div></div>`;
    }).join('');
    el.querySelectorAll('[data-q]').forEach(b => b.onclick = async () => {
      try {
        await j('/api/queues/' + encodeURIComponent(b.dataset.q) + '/' + b.dataset.a, { method: 'POST' });
        loadQueues();
      } catch (e) { toast(e.message, false); }
    });
    el.querySelectorAll('[data-task-log]').forEach(b => b.onclick = () => openTaskLog(b.dataset.taskLog));
    el.querySelectorAll('[data-task-cancel]').forEach(b => b.onclick = async () => {
      // §27: для задачи в очереди отмена снимает её до старта. Для уже
      // выполняющейся отменяется ожидание — запущенная на сервере команда
      // может дойти до конца. Не обещаем пользователю большего.
      const approved = await confirmAction({
        title: 'Отменить эту задачу?',
        message: 'Задача в очереди не будет запущена. Для уже выполняющейся задачи Bot4VPS перестанет её ждать, но команда на сервере может завершиться сама. Остальные задачи продолжат работу.',
        confirmText: 'Отменить',
      });
      if (!approved) return;
      try {
        await cancelTaskAPI(b.dataset.taskCancel);
        loadQueues();
      } catch (e) { toast(e.message, false); }
    });
  } catch (e) {
    document.getElementById('queues').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

const HISTORY_STATUS = {
  success: { label: 'Выполнено', cls: 'success' },
  success_warn: { label: 'С предупреждениями', cls: 'warning' },
  failed: { label: 'Ошибка', cls: 'failed' },
  cancelled: { label: 'Отменена', cls: 'warning' },
};

function formatTaskHistoryDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const pad = n => String(n).padStart(2, '0');
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function renderTaskHistoryEmpty(message = 'История задач пуста') {
  const el = document.getElementById('history');
  if (el) el.innerHTML = `<div class="empty">${esc(message)}</div>`;
}

async function deleteTaskHistoryRow(task, row) {
  const approved = await confirmAction({
    title: 'Удалить запись истории?',
    message: `Запись задачи «${task.name}» будет удалена из истории задач.`,
    confirmText: 'Удалить',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved) return;
  try {
    await j(`/api/tasks/history/${encodeURIComponent(task.id)}`, { method: 'DELETE' });
    historyRenderRevision += 1;
    row?.remove();
    if (!document.querySelector('#history tbody tr')) renderTaskHistoryEmpty();
    toast('Запись истории удалена', true);
  } catch (e) {
    toast(e.message, false);
  }
}

export async function clearTaskHistory() {
  const approved = await confirmAction({
    title: 'Очистить историю задач?',
    message: 'Все завершённые задачи будут удалены из истории Task Manager. Это действие нельзя отменить.',
    confirmText: 'Очистить историю',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved) return;
  try {
    await j('/api/tasks/history', { method: 'DELETE' });
    historyRenderRevision += 1;
    renderTaskHistoryEmpty();
    toast('История задач очищена', true);
  } catch (e) {
    toast(e.message, false);
  }
}

export async function loadHistory() {
  const renderRevision = ++historyRenderRevision;
  try {
    const data = await j('/api/tasks/history?limit=100');
    if (renderRevision !== historyRenderRevision) return;
    const tasks = data.tasks || [];
    const el = document.getElementById('history');
    if (!tasks.length) { renderTaskHistoryEmpty(); return; }
    el.innerHTML = `<table class="task-history-table">
      <thead><tr><th>Дата</th><th>Задача</th><th>Статус</th><th>Действие</th></tr></thead>
      <tbody>${tasks.map(t => {
        const status = HISTORY_STATUS[t.status] || { label: 'Завершена', cls: 'warning' };
        return `<tr data-history-id="${esc(t.id)}">
          <td class="task-history-date" data-label="Дата">${esc(formatTaskHistoryDate(t.finished_at || t.created_at))}</td>
          <td class="task-history-name" data-label="Задача">${esc(t.name)}</td>
          <td class="task-history-status" data-label="Статус"><span class="task-status ${status.cls}">${esc(status.label)}</span></td>
          <td class="task-history-actions" data-label="Действие">
            <button type="button" class="secondary task-history-log" data-history-log="${esc(t.id)}">Лог</button>
            <button type="button" class="secondary task-history-delete" data-history-delete="${esc(t.id)}" title="Удалить запись" aria-label="Удалить запись задачи ${esc(t.name)}">🗑</button>
          </td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
    const byId = new Map(tasks.map(t => [String(t.id), t]));
    el.querySelectorAll('[data-history-log]').forEach(button => {
      button.onclick = () => openTaskLog(button.dataset.historyLog);
    });
    el.querySelectorAll('[data-history-delete]').forEach(button => {
      button.onclick = () => {
        const task = byId.get(String(button.dataset.historyDelete));
        if (task) deleteTaskHistoryRow(task, button.closest('tr'));
      };
    });
  } catch (e) {
    if (renderRevision === historyRenderRevision) renderTaskHistoryEmpty(e.message);
  }
}

function toggleAuthFields() {
  const isKey = document.getElementById('sf-auth').value === 'key';
  document.getElementById('sf-pass-wrap').classList.toggle('hidden', isKey);
  document.getElementById('sf-key-wrap').classList.toggle('hidden', !isKey);
  document.getElementById('sf-sudo-control').classList.toggle('hidden', !isKey);
}

function toggleSslFields() {
  const enabled = document.getElementById('sf-cert')?.checked === true;
  document.getElementById('sf-ssl-host-wrap')?.classList.toggle('hidden', !enabled);
}

function enableSudoPasswordEditor() {
  const toggle = document.getElementById('sf-sudo-change');
  const wrap = document.getElementById('sf-sudo-wrap');
  if (!toggle || !wrap) return;
  toggle.classList.add('hidden');
  wrap.classList.remove('hidden');
  document.getElementById('sf-sudo-password')?.focus();
}

export function fillSettingsForm() {
  const data = state.openServerData || window._openServerData;
  if (!data || !data.server) return;
  const s = data.server;
  document.getElementById('sf-name').value = s.name || '';
  document.getElementById('sf-host').value = s.host || '';
  document.getElementById('sf-port').value = s.port || 22;
  document.getElementById('sf-user').value = s.user || '';
  document.getElementById('sf-auth').value = s.auth_type || 'password';
  document.getElementById('sf-password').value = '';
  document.getElementById('sf-sudo-password').value = '';
  document.getElementById('sf-sudo-wrap').classList.add('hidden');
  document.getElementById('sf-sudo-change').classList.remove('hidden');
  document.getElementById('sf-ssl-host').value = s.ssl_host || '';
  document.getElementById('sf-cert').checked = !!s.certificate_check;
  const gsel = document.getElementById('sf-group');
  gsel.innerHTML = state.groups.map(g =>
    `<option value="${esc(g.name)}" ${g.name === s.group ? 'selected' : ''}>${esc(g.name)}</option>`
  ).join('') || `<option value="${esc(s.group || '')}">${esc(s.group || '')}</option>`;
  const ksel = document.getElementById('sf-key');
  ksel.innerHTML = state.keys.map(k => {
    const sel = (s.key_path || '').endsWith(k.name) || s.key_path === k.path;
    return `<option value="${esc(k.path)}" ${sel ? 'selected' : ''}>${esc(k.name)}</option>`;
  }).join('') || '<option value="">— нет ключей —</option>';
  toggleAuthFields();
  toggleSslFields();
  bindPasswordToggles();
}

export async function saveServerSettings() {
  if (!openServerId) return;
  const body = {
    name: document.getElementById('sf-name').value.trim(),
    host: document.getElementById('sf-host').value.trim(),
    port: +document.getElementById('sf-port').value,
    user: document.getElementById('sf-user').value.trim(),
    group: document.getElementById('sf-group').value,
    auth_type: document.getElementById('sf-auth').value,
    certificate_check: document.getElementById('sf-cert').checked,
    ssl_host: document.getElementById('sf-ssl-host').value.trim() || null,
  };
  const pass = document.getElementById('sf-password').value;
  if (body.auth_type === 'password' && pass) body.password = pass;
  if (body.auth_type === 'key') {
    body.key_path = document.getElementById('sf-key').value || null;
    const sudoWrap = document.getElementById('sf-sudo-wrap');
    const sudoPass = document.getElementById('sf-sudo-password').value;
    if (!sudoWrap.classList.contains('hidden') && sudoPass) body.password = sudoPass;
  }
  try {
    await j('/api/servers/' + encodeURIComponent(openServerId), {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    toast('Сохранено', true);
    document.getElementById('edit-server-modal')?.classList.remove('open');
    await openServer(openServerId);
    loadServers();
  } catch (e) { toast(e.message, false); }
}

/**
 * Тест SSH строго по полям формы (host/port/user/auth).
 * Пароль/ключ: из формы, если пусто — с сохранённого сервера (тот же id).
 * Никогда не тестирует «старый» host/port из БД, если в форме другие.
 */
export async function testServerForm() {
  if (!openServerId) {
    toast('Нет открытого сервера', false);
    return;
  }
  const auth = document.getElementById('sf-auth').value;
  const host = document.getElementById('sf-host').value.trim();
  const port = +document.getElementById('sf-port').value || 22;
  const user = document.getElementById('sf-user').value.trim();
  if (!host) { toast('Укажите host', false); return; }

  const body = {
    server_id: openServerId,
    host,
    port,
    user,
    auth_type: auth,
  };
  if (auth === 'password') {
    const pass = document.getElementById('sf-password').value;
    if (pass) body.password = pass;
  } else {
    const key_path = document.getElementById('sf-key').value || '';
    if (key_path) body.key_path = key_path;
  }

  try {
    const r = await j('/api/ssh/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const where = r.tested
      ? ` (${r.tested.host}:${r.tested.port})`
      : ` (${host}:${port})`;
    toast((r.ok ? 'SSH OK' : (r.message || 'Ошибка')) + where, r.ok);
  } catch (e) {
    toast(e.message, false);
  }
}

export async function deleteServer() {
  if (!openServerId) return;
  const name = state.openServerData?.server?.name || window._openServerData?.server?.name || 'сервер';
  const approved = await confirmAction({
    title: 'Удалить сервер?',
    message: `Сервер «${name}» будет удалён из Bot4VPS.`,
    confirmText: 'Удалить',
  });
  if (!approved) return;
  try {
    await j('/api/servers/' + encodeURIComponent(openServerId), { method: 'DELETE' });
    toast('Удалён', true);
    openServerId = null;
    setOpenServer(null, null);
    stopWatchers();
    try { localStorage.setItem('bot4vps_page', 'servers'); localStorage.removeItem('bot4vps_server_id'); } catch (_) {}
    showPage('servers');
    loadServers();
  } catch (e) { toast(e.message, false); }
}

export function openAddServerModal() {
  loadGroupsAndKeys().then(() => {
    const gsel = document.getElementById('af-group');
    gsel.innerHTML = state.groups.map(g => `<option value="${esc(g.name)}">${esc(g.name)}</option>`).join('')
      || '<option value="vps">vps</option>';
    const ksel = document.getElementById('af-key');
    ksel.innerHTML = state.keys.map(k => `<option value="${esc(k.path)}">${esc(k.name)}</option>`).join('')
      || '<option value="">—</option>';
    document.getElementById('add-server-modal').classList.add('open');
    toggleAddAuth();
    bindPasswordToggles();
  });
}

function toggleAddAuth() {
  const isKey = document.getElementById('af-auth').value === 'key';
  document.getElementById('af-pass-wrap').classList.toggle('hidden', isKey);
  document.getElementById('af-key-wrap').classList.toggle('hidden', !isKey);
}

export async function submitAddServer() {
  const body = {
    name: document.getElementById('af-name').value.trim(),
    host: document.getElementById('af-host').value.trim(),
    port: +document.getElementById('af-port').value || 22,
    user: document.getElementById('af-user').value.trim() || 'root',
    group: document.getElementById('af-group').value,
    auth_type: document.getElementById('af-auth').value,
    password: document.getElementById('af-password').value || null,
    key_path: document.getElementById('af-key').value || null,
    ssl_host: document.getElementById('af-ssl').value.trim() || null,
    certificate_check: document.getElementById('af-cert').checked,
    test: document.getElementById('af-test').checked,
  };
  if (!body.name || !body.host) { toast('Имя и host обязательны', false); return; }
  try {
    const r = await j('/api/servers', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    document.getElementById('add-server-modal').classList.remove('open');
    toast('Сервер добавлен', true);
    await loadServers();
    if (r.id) openServer(r.id);
  } catch (e) { toast(e.message, false); }
}

export function bindServerUI() {
  const search = document.getElementById('server-search');
  if (search) {
    search.addEventListener('input', () => setServerQuery(search.value));
    search.addEventListener('keydown', e => {
      if (e.key === 'Escape') { search.value = ''; setServerQuery(''); }
    });
  }
  document.getElementById('btn-add-server')?.addEventListener('click', openAddServerModal);
  document.getElementById('btn-task-history-clear')?.addEventListener('click', clearTaskHistory);
  document.getElementById('btn-groups-panel')?.addEventListener('click', openGroupsPanel);
  document.getElementById('btn-back-servers')?.addEventListener('click', () => {
    openServerId = null;
    setOpenServer(null, null);
    stopWatchers();
    try { localStorage.setItem('bot4vps_page', 'servers'); localStorage.removeItem('bot4vps_server_id'); } catch (_) {}
    showPage('servers');
  });
  document.getElementById('btn-copy-srv-ip')?.addEventListener('click', copyServerIp);
  document.getElementById('btn-open-terminal')?.addEventListener('click', () => openServerTerminal());
  document.getElementById('btn-back-from-terminal')?.addEventListener('click', () => backFromTerminal());
  document.getElementById('sf-auth')?.addEventListener('change', toggleAuthFields);
  document.getElementById('sf-cert')?.addEventListener('change', toggleSslFields);
  document.getElementById('sf-sudo-change')?.addEventListener('click', enableSudoPasswordEditor);
  document.getElementById('sf-save')?.addEventListener('click', saveServerSettings);
  document.getElementById('sf-test')?.addEventListener('click', testServerForm);
  document.getElementById('esm-cancel')?.addEventListener('click', () =>
    document.getElementById('edit-server-modal').classList.remove('open'));
  document.getElementById('edit-server-modal')?.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.getElementById('edit-server-modal').classList.remove('open');
  });
  document.getElementById('af-auth')?.addEventListener('change', toggleAddAuth);
  document.getElementById('af-save')?.addEventListener('click', submitAddServer);
  document.getElementById('af-cancel')?.addEventListener('click', () =>
    document.getElementById('add-server-modal').classList.remove('open'));
  bindPasswordToggles();
}

function openGroupsPanel() {
  const panel = document.getElementById('groups-panel');
  if (panel) {
    panel.classList.add('open');
    // Загружаем списки групп при открытии панели
    import('./settings.js').then(m => {
      m.loadGroupsAdmin();
      m.loadGroupsDisplayOrder();
    });
  }
}

export function closeGroupsPanel() {
  const panel = document.getElementById('groups-panel');
  if (panel) panel.classList.remove('open');
}

// Установка/удаление сервиса меняет кнопки «Быстрых действий» — вызывается из
// wireguard.js / docker.js. Перерисовываем только этот блок: openServer() внутри
// делает showPage('server') и выдернул бы пользователя со страницы WG/Docker.
// Карточка остаётся в DOM после ухода на страницу сервиса, поэтому обновляем её
// и когда она не на экране — вернувшись, пользователь увидит актуальные кнопки.
//
// Состояние кнопок берётся только из /api/services/{sid}/status: вызывающий модуль
// сообщает лишь ФАКТ изменения, но не результат. Иначе кнопка переключилась бы и
// после неудавшегося удаления, разойдясь с реальным состоянием сервиса.
window.refreshAfterServiceChange = (serverId) => {
  if (serverId && openServerId === serverId) renderQuickActions(serverId);
};