import { j, esc } from './api.js';
import { ansiToHtml } from './ansi.js';
import { toast, showPage, bindPasswordToggles, parseEmoji, confirmAction, formatServerDateTime, serverDateTimeParts, serverDayDifference, serverNow } from './ui.js';
import { state, setServers, setGroups, setKeys, setOpenServer, setPage, setServerGroupTab, setServerSort, setServerQuery as updateServerQuery } from './state.js';
import { WIREGUARD_ICON, DOCKER_ICON } from './icons.js?v=20260905-brandicons-v2';
import { openTerminal, closeTerminal } from './terminal.js?v=20260904-termfit-v1';
import { openEventDetail, applyEventsSnapshot } from './monitor.js?v=20260912-chlogwrap-v1';
import { openTaskLog, cancelTaskAPI } from './tasks.js?v=20260816-task-history-v3';
import { openBackupsForServer } from './backup.js?v=20260912-tzdrop-v1';

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
let quickSetupOpener = null;

// История метрик для графиков (последние 20 значений)
const metricsHistory = {
  cpu: [],
  ram: [],
  disk: []
};
const HISTORY_MAX = 20;

// Форматирование uptime в русском компактном формате.
function formatUptime(uptime, uptimeSeconds = null) {
  if (uptime == null || uptime === '' || String(uptime).toUpperCase() === 'N/A') return '—';

  let seconds = uptimeSeconds == null || uptimeSeconds === ''
    ? null
    : Number(uptimeSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) {
    const minutes = uptimeMinutes(uptime);
    seconds = minutes == null ? null : minutes * 60;
  }
  if (!Number.isFinite(seconds) || seconds < 0) return String(uptime);
  if (seconds < 60) return '<1м';

  let minutes = Math.floor(seconds / 60);
  const units = [
    ['г', 365 * 24 * 60],
    ['н', 7 * 24 * 60],
    ['д', 24 * 60],
    ['ч', 60],
    ['м', 1],
  ];
  const parts = [];
  units.forEach(([suffix, size]) => {
    const count = Math.floor(minutes / size);
    if (count) {
      parts.push(`${count}${suffix}`);
      minutes %= size;
    }
  });
  return parts.join(' ') || '0м';
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

const ALL_SERVER_GROUP = '__all__';
const revealedServerHosts = new Set();
let revealAllServerHosts = false;
const SORT_DEFAULTS = {
  name: false,
  ssl: true,
  online: false,
  uptime: false,
  group: false,
};

function serverGroupName(server) {
  const value = String(server?.group ?? '').trim();
  return value && value !== '—' ? value : '';
}

function configuredGroupNames() {
  const names = [];
  const add = name => {
    const value = String(name ?? '').trim();
    if (value && !names.includes(value)) names.push(value);
  };

  const known = new Set();
  state.groups.forEach(group => {
    const name = String(group?.name ?? group ?? '').trim();
    if (name) known.add(name);
  });
  state.servers.forEach(server => {
    const name = serverGroupName(server);
    if (name) known.add(name);
  });

  let savedOrder = [];
  let visibleGroups = null;
  try {
    const rawOrder = localStorage.getItem('bot4vps_group_order');
    const rawVisible = localStorage.getItem('bot4vps_visible_groups');
    if (rawOrder) savedOrder = JSON.parse(rawOrder);
    if (rawVisible) visibleGroups = new Set(JSON.parse(rawVisible));
  } catch (_) {}

  savedOrder.forEach(name => {
    if (known.has(String(name).trim())) add(name);
  });
  state.groups.forEach(group => add(group?.name ?? group));
  state.servers.forEach(server => add(serverGroupName(server)));

  if (!visibleGroups) return names;
  // «Все» всегда содержит все серверы. Скрытую группу можно открыть по её
  // ссылке в строке — в этом случае временно оставляем её вкладку доступной.
  return names.filter(name => visibleGroups.has(name) || name === state.serverGroupTab);
}

function groupCount(name) {
  return state.servers.filter(server => serverGroupName(server) === name).length;
}

function renderServerGroupTabs() {
  const tabs = document.getElementById('server-group-tabs');
  if (!tabs) return;

  const groups = configuredGroupNames();
  const active = state.serverGroupTab === ALL_SERVER_GROUP
    || groups.includes(state.serverGroupTab)
    ? state.serverGroupTab
    : ALL_SERVER_GROUP;
  if (active !== state.serverGroupTab) setServerGroupTab(active);

  const tab = (value, label, count) => `
    <button type="button" class="${active === value ? 'on' : ''}"
            data-group-tab="${esc(value)}" role="tab"
            aria-selected="${active === value ? 'true' : 'false'}">
      <span>${esc(label)}</span><span class="server-group-count">${count}</span>
    </button>`;

  const html = tab(ALL_SERVER_GROUP, 'Все', state.servers.length)
    + groups.map(name => tab(name, name, groupCount(name))).join('');
  // Пишем только при реальном изменении — при SSE-обновлениях вкладки
  // не должны пересоздаваться (сбивается ховер).
  const current = tabs.__html !== undefined ? tabs.__html : tabs.innerHTML;
  if (current !== html) {
    tabs.__html = html;
    tabs.innerHTML = html;
  }
}

function sslDays(server) {
  if (!server?.certificate_check || server.ssl_days_left == null) return null;
  const value = Number(server.ssl_days_left);
  return Number.isFinite(value) ? value : null;
}

function uptimeMinutes(uptime) {
  if (uptime == null || uptime === '' || String(uptime).toUpperCase() === 'N/A') {
    return null;
  }

  const value = String(uptime).trim().toLowerCase();
  const unitPatterns = [
    [365 * 24 * 60, /(\d+(?:[.,]\d+)?)\s*(?:years?|год(?:а|ов)?|лет|г)\.?(?=$|[\s,;])/giu],
    [7 * 24 * 60, /(\d+(?:[.,]\d+)?)\s*(?:weeks?|недел(?:я|и|ь)|нед)\.?(?=$|[\s,;])/giu],
    [24 * 60, /(\d+(?:[.,]\d+)?)\s*(?:days?|день|дня|дней|д)\.?(?=$|[\s,;])/giu],
    [60, /(\d+(?:[.,]\d+)?)\s*(?:hours?|час|часа|часов|ч)\.?(?=$|[\s,;])/giu],
    [1, /(\d+(?:[.,]\d+)?)\s*(?:minutes?|минута|минуты|минут|м)\.?(?=$|[\s,;])/giu],
    [1 / 60, /(\d+(?:[.,]\d+)?)\s*(?:seconds?|секунда|секунды|секунд|с)\.?(?=$|[\s,;])/giu],
  ];
  let total = 0;
  let matched = false;

  unitPatterns.forEach(([multiplier, pattern]) => {
    let match;
    while ((match = pattern.exec(value)) !== null) {
      total += Number(match[1].replace(',', '.')) * multiplier;
      matched = true;
    }
  });

  if (matched) return total;

  // Fallback `cat /proc/uptime`: первое число — секунды с запуска.
  const seconds = Number.parseFloat(value.split(/\s+/)[0]);
  return Number.isFinite(seconds) ? seconds / 60 : null;
}

function serverUptimeMinutes(server) {
  const rawSeconds = server?.uptime_seconds;
  if (rawSeconds != null && rawSeconds !== '') {
    const seconds = Number(rawSeconds);
    if (Number.isFinite(seconds) && seconds >= 0) return seconds / 60;
  }
  return uptimeMinutes(server?.uptime);
}

function sortValue(server, key) {
  if (key === 'name') return String(server?.name || '').toLocaleLowerCase('ru-RU');
  if (key === 'group') return serverGroupName(server).toLocaleLowerCase('ru-RU');
  if (key === 'ssl') return sslDays(server);
  if (key === 'uptime') return serverUptimeMinutes(server);
  if (key === 'online') {
    if (server?.online === true) return 0;
    if (server?.online === false) return 1;
    return 2;
  }
  return null;
}

function sortedServers(list) {
  const sort = state.serverSort || { key: 'name', descending: false };
  const key = SORT_DEFAULTS[sort.key] === undefined ? 'name' : sort.key;
  const direction = sort.descending ? -1 : 1;
  return list
    .map((server, index) => ({ server, index, value: sortValue(server, key) }))
    .sort((a, b) => {
      if (key === 'ssl' || key === 'uptime') {
        const aMissing = a.value == null;
        const bMissing = b.value == null;
        if (aMissing !== bMissing) return aMissing ? 1 : -1;
      }
      if (key === 'group') {
        const aMissing = !a.value;
        const bMissing = !b.value;
        if (aMissing !== bMissing) return aMissing ? direction : -direction;
      }
      let result = 0;
      if (typeof a.value === 'number' && typeof b.value === 'number') {
        result = a.value - b.value;
      } else {
        result = String(a.value ?? '').localeCompare(String(b.value ?? ''), 'ru', {
          sensitivity: 'base',
          numeric: true,
        });
      }
      return (result * direction) || (a.index - b.index);
    })
    .map(item => item.server);
}

function filteredServers() {
  const group = state.serverGroupTab || ALL_SERVER_GROUP;
  let list = state.servers;
  if (group !== ALL_SERVER_GROUP) {
    list = list.filter(server => serverGroupName(server) === group);
  }

  const query = (state.serverQuery || '').trim().toLowerCase();
  if (query) {
    list = list.filter(server => {
      const blob = [server.name, server.host, serverGroupName(server), server.user, server.id]
        .map(value => String(value || '').toLowerCase())
        .join(' ');
      return query.split(/\s+/).every(part => blob.includes(part));
    });
  }
  return sortedServers(list);
}

/**
 * Статус сервера в таблице:
 * - Online (зелёный) — сеть и SSH в порядке;
 * - Online ⚠️ (жёлтый, тултип с причиной) — сервер жив, SSH не проходит
 *   (нет ключа, пароль не подходит…);
 * - Offline (красный, тултип с причиной) — недоступен по сети;
 * - Неизвестно (серый) — ещё не проверяли.
 */
function onlineCell(value, sshError, lastError) {
  const tip = (text) => (text && String(text).trim())
    ? ` title="${esc(String(text))}"` : '';
  if (value === true) {
    if (sshError && String(sshError).trim()) {
      return `<span class="server-status server-status-warn"${tip(sshError)}>`
        + '<span class="server-status-dot"></span>Online ⚠️</span>';
    }
    return '<span class="server-status server-status-online"><span class="server-status-dot"></span>Online</span>';
  }
  if (value === false) {
    return `<span class="server-status server-status-offline"${tip(lastError)}>`
      + '<span class="server-status-dot"></span>Offline</span>';
  }
  return '<span class="server-status server-status-unknown"><span class="server-status-dot"></span>Неизвестно</span>';
}

function sslCell(server) {
  if (!server?.certificate_check) {
    return '<span class="server-ssl server-ssl-disabled">SSL: не проверяется</span>';
  }
  const days = sslDays(server);
  const daysText = days == null ? '' : ` · ${days} дн.`;
  if (server.ssl_status === 'valid') {
    return `<span class="server-ssl server-ssl-valid">SSL: норма${daysText}</span>`;
  }
  if (server.ssl_status === 'warning') {
    return `<span class="server-ssl server-ssl-warning">SSL: скоро истечёт${daysText}</span>`;
  }
  if (server.ssl_status === 'expired') {
    return '<span class="server-ssl server-ssl-expired">SSL: просрочен</span>';
  }
  if (server.ssl_status === 'error') {
    return '<span class="server-ssl server-ssl-error">SSL: ошибка проверки</span>';
  }
  return '<span class="server-ssl server-ssl-unknown">SSL: нет данных</span>';
}

function sortableServerHeader(key, label) {
  const sort = state.serverSort || { key: 'name', descending: false };
  const active = sort.key === key;
  const descending = active ? !!sort.descending : !!SORT_DEFAULTS[key];
  const ariaSort = active ? (descending ? 'descending' : 'ascending') : 'none';

  return `<th aria-sort="${ariaSort}">
    <button type="button" class="server-column-sort${active ? ' on' : ''}"
            data-sort-key="${esc(key)}" aria-pressed="${active ? 'true' : 'false'}"
            title="Сортировать по столбцу «${esc(label)}»">
      <span>${esc(label)}</span>
      <span class="server-sort-arrow" aria-hidden="true">${active ? (descending ? '↓' : '↑') : ''}</span>
    </button>
  </th>`;
}

function serverHostHeader() {
  const label = revealAllServerHosts
    ? 'Скрыть IP всех серверов'
    : 'Показать IP всех серверов';

  return `<th>
    <span class="server-host-heading">
      <span>IP</span>
      <button type="button" class="server-host-visibility${revealAllServerHosts ? ' on' : ''}"
              data-host-visibility-toggle aria-pressed="${revealAllServerHosts ? 'true' : 'false'}"
              title="${label}" aria-label="${label}">
        <span aria-hidden="true">👁</span>
      </button>
    </span>
  </th>`;
}

function serverIp(server) {
  for (const rawValue of [server?.host_ip, server?.host]) {
    const value = String(rawValue ?? '').trim();
    if (!value) continue;

    const ipv4 = value.split('.');
    if (ipv4.length === 4 && ipv4.every(part => /^\d{1,3}$/.test(part)
        && Number(part) >= 0 && Number(part) <= 255)) {
      return value;
    }

    const ipv6 = value.startsWith('[') && value.endsWith(']')
      ? value.slice(1, -1)
      : value;
    if (ipv6.includes(':')) {
      try {
        new URL(`http://[${ipv6}]/`);
        return ipv6;
      } catch (_) {}
    }
  }
  return '';
}

function serverHostCell(server) {
  const id = String(server?.id ?? '');
  const ip = serverIp(server);
  if (!ip) return '<span class="server-host-empty">—</span>';

  const value = revealAllServerHosts || revealedServerHosts.has(id)
    ? `<span class="server-host-value">${esc(ip)}</span>`
    : `<button type="button" class="server-host-reveal" data-host-reveal="${esc(id)}"
               title="Показать IP" aria-label="Показать IP сервера «${esc(server?.name || '')}»">
         <span aria-hidden="true">••••••••</span>
       </button>`;

  return `<span class="server-host-content">
    ${value}
    <button type="button" class="server-host-copy" data-host-copy="${esc(id)}"
            title="Копировать IP" aria-label="Копировать IP сервера «${esc(server?.name || '')}»">
      <span aria-hidden="true">⧉</span>
    </button>
  </span>`;
}

function copyServerListIp(serverId, button) {
  const server = state.servers.find(item => String(item?.id ?? '') === String(serverId ?? ''));
  const ip = serverIp(server);
  if (!ip) {
    toast('IP-адрес недоступен', false);
    return;
  }

  writeClipboard(ip).then(() => {
    toast('IP скопирован', true);
    button?.classList.add('copied');
    setTimeout(() => button?.classList.remove('copied'), 1200);
  }).catch(() => {
    toast('Не удалось скопировать IP', false);
  });
}

function serverRowCells(server) {
  const group = serverGroupName(server);
  const groupCell = group
    ? `<button type="button" class="server-group-link" data-group-link="${esc(group)}">${esc(group)}</button>`
    : '<span class="server-no-group">Без группы</span>';
  return `<td class="server-name-cell" data-label="Имя"><strong>${esc(server.name || '—')}</strong>${server.has_running ? '<span class="server-running-mark" title="Идёт задача">▶</span>' : ''}</td>
      <td class="server-host-cell" data-label="IP">${serverHostCell(server)}</td>
      <td data-label="Статус">${onlineCell(server.online, server.ssh_error, server.last_error)}</td>
      <td data-label="SSL">${sslCell(server)}</td>
      <td class="server-uptime-cell" data-label="Uptime">${esc(formatUptime(server.uptime, server.uptime_seconds))}</td>
      <td class="server-group-cell" data-label="Группа">${groupCell}</td>`;
}

function renderServersTable(list) {
  const rows = list.map(server =>
    `<tr class="server-table-row" data-sid="${esc(server.id)}" tabindex="0" role="button">${serverRowCells(server)}</tr>`).join('');

  return `<div class="server-table-wrap">
    <table class="server-table">
      <thead><tr>
        ${sortableServerHeader('name', 'Имя сервера')}
        ${serverHostHeader()}
        ${sortableServerHeader('online', 'Статус')}
        ${sortableServerHeader('ssl', 'SSL')}
        ${sortableServerHeader('uptime', 'Uptime')}
        ${sortableServerHeader('group', 'Группа')}
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// Точечное обновление списка при SSE-снапшотах (каждые ~3с): если состав
// и порядок строк не изменились, перезаписываем только реально изменившиеся
// <td> внутри существующих <tr> — DOM списка не пересоздаётся, скролл,
// ховер и фокус не сбрасываются. Иначе вызывающий делает полный рендер.
function patchServersTable() {
  const wrap = document.querySelector('#servers .server-table-wrap');
  if (!wrap || !state.servers.length) return false;
  const list = filteredServers();
  if (!list.length) return false;
  const rows = wrap.querySelectorAll('tbody tr[data-sid]');
  if (rows.length !== list.length) return false;
  for (let i = 0; i < list.length; i++) {
    if (String(list[i].id) !== rows[i].dataset.sid) return false;
  }
  list.forEach((server, i) => {
    const row = rows[i];
    const cells = serverRowCells(server);
    const current = row.__cells !== undefined ? row.__cells : row.innerHTML;
    if (current !== cells) {
      row.__cells = cells;
      row.innerHTML = cells;
    }
  });
  renderServerGroupTabs();
  return true;
}

export function renderServersFromState() {
  if (patchServersTable()) return;
  const currentTable = document.querySelector('#servers .server-table-wrap');
  const scrollTop = currentTable?.scrollTop || 0;
  const scrollLeft = currentTable?.scrollLeft || 0;

  renderServers();

  const nextTable = document.querySelector('#servers .server-table-wrap');
  if (nextTable) {
    nextTable.scrollTop = scrollTop;
    nextTable.scrollLeft = scrollLeft;
  }
}

export function renderServers() {
  const el = document.getElementById('servers');
  if (!el) return;
  renderServerGroupTabs();

  if (!state.servers.length) {
    el.innerHTML = '<div class="empty">Нет серверов</div>';
    return;
  }
  const list = filteredServers();
  if (!list.length) {
    el.innerHTML = '<div class="empty">Ничего не найдено</div>';
    return;
  }
  el.innerHTML = renderServersTable(list);
}

export function setServerQuery(query) {
  updateServerQuery(query);
  renderServers();
}

function selectServerGroupTab(tab) {
  setServerGroupTab(tab);
  renderServers();
}

function toggleServerSort(key) {
  if (SORT_DEFAULTS[key] === undefined) return;
  const current = state.serverSort || { key: 'name', descending: false };
  const descending = current.key === key
    ? !current.descending
    : !!SORT_DEFAULTS[key];
  setServerSort(key, descending);
  renderServers();
}

function bindServerListUI() {
  const tabs = document.getElementById('server-group-tabs');
  if (tabs && !tabs.dataset.bound) {
    tabs.dataset.bound = '1';
    tabs.addEventListener('click', event => {
      const button = event.target.closest('[data-group-tab]');
      if (button) selectServerGroupTab(button.dataset.groupTab);
    });
  }

  const list = document.getElementById('servers');
  if (list && !list.dataset.bound) {
    list.dataset.bound = '1';
    const openRow = row => {
      if (row?.dataset.sid) openServer(row.dataset.sid);
    };
    list.addEventListener('click', event => {
      const sortButton = event.target.closest('[data-sort-key]');
      if (sortButton) {
        event.preventDefault();
        event.stopPropagation();
        toggleServerSort(sortButton.dataset.sortKey);
        return;
      }

      const hostVisibility = event.target.closest('[data-host-visibility-toggle]');
      if (hostVisibility) {
        event.preventDefault();
        event.stopPropagation();
        revealAllServerHosts = !revealAllServerHosts;
        if (!revealAllServerHosts) revealedServerHosts.clear();
        renderServersFromState();
        return;
      }

      const hostCopy = event.target.closest('[data-host-copy]');
      if (hostCopy) {
        event.preventDefault();
        event.stopPropagation();
        copyServerListIp(hostCopy.dataset.hostCopy, hostCopy);
        return;
      }

      const hostReveal = event.target.closest('[data-host-reveal]');
      if (hostReveal) {
        event.preventDefault();
        event.stopPropagation();
        revealedServerHosts.add(String(hostReveal.dataset.hostReveal || ''));
        renderServersFromState();
        return;
      }

      const groupLink = event.target.closest('[data-group-link]');
      if (groupLink) {
        event.preventDefault();
        event.stopPropagation();
        selectServerGroupTab(groupLink.dataset.groupLink);
        return;
      }
      openRow(event.target.closest('[data-sid]'));
    });
    list.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const row = event.target.closest('[data-sid]');
      if (!row || event.target.closest('button,a,input,select,textarea')) return;
      event.preventDefault();
      openRow(row);
    });
  }
}

// Живые SSH-пробы: страница «Серверы» сама дёргает развёртку каждые 3с,
// пока открыта (тот же принцип, что метрики дашборда). Пробы идут на
// бэке в фоне, статус приезжает SSE-снапшотом — точечный патчинг строк
// подхватит его без пересборки списка.
let sshProbeTimer = null;

function kickSshProbe() {
  j('/api/servers/ssh-probe', { method: 'POST' }).catch(() => {});
}

export function startSshProbeLoop() {
  stopSshProbeLoop();
  kickSshProbe();
  sshProbeTimer = setInterval(kickSshProbe, 3000);
}

export function stopSshProbeLoop() {
  if (sshProbeTimer) { clearInterval(sshProbeTimer); sshProbeTimer = null; }
}

export function stopWatchers() {
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
  if (logTimer) { clearInterval(logTimer); logTimer = null; }
  if (taskWatchTimer) { clearInterval(taskWatchTimer); taskWatchTimer = null; }
  lastRunningTaskId = null;
}

/**
 * Следит за running_task открытого сервера и перерисовывает «Действия с сервером»,
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
 * Блок «Действия с сервером» карточки сервера.
 *
 * Кнопка настроек публикуется сразу, а необязательные статусы
 * WG/Docker догружаются отдельно. Так сбой вспомогательной проверки не скрывает
 * основной вход в Quick Setup.
 * Вынесено из openServer(), чтобы после установки/удаления сервиса можно было
 * перерисовать только этот блок — без showPage('server'), который выдернул бы
 * пользователя со страницы WireGuard/Docker.
 */
async function openQuickSetupFromCard(id) {
  const serverId = String(id ?? '').trim();
  if (!serverId) throw new Error('Сервер для настроек не выбран');
  if (typeof quickSetupOpener !== 'function') {
    throw new Error('Модуль настроек сервера недоступен');
  }
  await quickSetupOpener(serverId);
}

async function renderQuickActions(id) {
  const qa = document.getElementById('srv-quick-actions');
  if (!qa) return;

  // Несколько источников могут запросить обновление одновременно (openServer,
  // watcher задачи, refreshAfterServiceChange). Собираем кнопки вне DOM и
  // публикуем только результат последнего вызова, чтобы stale-render не дописал
  // дубли после своих await.
  const revision = ++quickActionsRevision;
  let fragment = document.createDocumentFragment();
  const addAction = (text, icon, cls, fn, styles) => {
    const b = document.createElement('button');
    b.innerHTML = icon ? `${icon} ${text}` : text;
    if (cls) b.className = cls;
    b.onclick = fn;
    b.style.textAlign = 'left';
    if (styles) Object.assign(b.style, styles);
    fragment.appendChild(b);
    return b;
  };

  // 1. Настройки сервера (Quick Setup)
  addAction('Настройки сервера', '⚙', 'secondary', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await openQuickSetupFromCard(id);
    } catch (error) {
      toast(error?.message || 'Не удалось открыть настройки сервера', false);
    } finally {
      if (button?.isConnected) button.disabled = false;
    }
  });
  if (revision !== quickActionsRevision) return;
  qa.replaceChildren(fragment);

  const [wireGuardResult, dockerResult] = await Promise.allSettled([
    checkWireGuardStatus(id),
    checkDockerStatus(id),
  ]);
  if (revision !== quickActionsRevision) return;
  const wireGuardInstalled = wireGuardResult.status === 'fulfilled'
    && wireGuardResult.value === true;
  const dockerInstalled = dockerResult.status === 'fulfilled'
    && dockerResult.value === true;

  fragment = document.createDocumentFragment();

  // 2. WireGuard
  if (wireGuardInstalled) {
    addAction('Панель управления WireGuard', WIREGUARD_ICON, 'secondary', () => openWireGuardServer(id));
  } else {
    addAction('Установить WireGuard', WIREGUARD_ICON, 'secondary', () => confirmInstallWireGuard(id));
  }

  // 3. Docker
  if (dockerInstalled) {
    addAction('Панель управления Docker', DOCKER_ICON, 'secondary', () => openDockerServer(id));
  } else {
    addAction('Установить Docker', DOCKER_ICON, 'secondary', () => confirmInstallDocker(id));
  }

  // 4. Запустить скрипт
  addAction('Запустить скрипт', '▶', 'secondary',
    () => import('./scripts.js?v=20260826-host-timezone-v2').then(m => m.openRunModal(id, null)));

  // 5. Перезагрузить сервер
  addAction('Перезагрузить сервер', '🔄', 'secondary', async () => {
    const approved = await confirmAction({
      title: 'Перезагрузить сервер?',
      message: 'Сервер будет перезагружен.',
      confirmText: 'Перезагрузить',
      confirmFirst: true,
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
  qa.appendChild(fragment);
}


// ---------------------------------------------------------------
// Недавние события сервера (фильтр журнала по server_id)
// ---------------------------------------------------------------
let _srvEventsExpanded = false;
let _srvEventsList = [];
let _srvEventsServerId = null;

function _formatEventTime(ts) {
  const parts = serverDateTimeParts(ts);
  if (!parts) return '—';
  const diffDays = serverDayDifference(ts);
  if (diffDays === 0) return `${parts.hour}:${parts.minute}`;
  if (diffDays === 1) return 'вчера';
  if (parts.year === serverDateTimeParts(serverNow())?.year) return `${parts.day}.${parts.month}`;
  return `${parts.day}.${parts.month}.${parts.year}`;
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
/** Красный баннер проблемы подключения в карточке сервера.
 *  null — скрыть; {title, message} — показать. */
export function renderConnWarning(warning) {
  const el = document.getElementById('srv-conn-warning');
  if (!el) return;
  if (!warning) {
    el.classList.add('hidden');
    el.innerHTML = '';
    return;
  }
  el.classList.remove('hidden');
  el.innerHTML = `<strong>${esc(warning.title)}</strong>${esc(warning.message)}`;
}

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
  closeGroupsPanel();
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

      // Добавляем SSL если есть сертификат И проверка включена:
      // после выключения certificate_check устаревшие данные monitor.json
      // не должны висеть в карточке
      const cert = mon.certificate;
      if (cert && mon.ssl_host && s.certificate_check) {
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

    renderQuickActions(id);
    loadServerRecentEvents(id);

    if (data.running_task) { watchTaskId = data.running_task.id; state.watchTaskId = watchTaskId; }
    await loadGroupsAndKeys();
    // Ключ заявлен, но файла нет: причина известна локально, probe не нужен
    const keyMissing = s.auth_type === 'key' && data.key_exists === false;
    if (keyMissing) {
      renderConnWarning({
        title: 'SSH-ключ не найден',
        message: `Файл ${s.key_path || '—'} отсутствует — подключение к серверу невозможно. `
          + 'Восстановите ключ из резервной копии или смените способ входа в настройках сервера.',
      });
    } else {
      renderConnWarning(null);
    }
    // SSH-статус из monitor (сетевой online — ещё не SSH); уточним probe ниже
    renderSshStatus(keyMissing ? false : null, keyMissing ? 'SSH-ключ не найден' : '');
    showPage('server');
    setPage('server');
    metricsNA('загрузка...');
    startWatchers();
    if (keyMissing) return;
    // Точный SSH — существующий /probe (как в refreshMetrics)
    j('/api/servers/' + encodeURIComponent(id) + '/probe').then(p => {
      if (openServerId !== id) return;
      const info = p.info || {};
      const sshOk = !!info.ssh;
      renderSshStatus(sshOk, info.ssh_error || p.ssh_error_human || '');
      // Прочие проблемы (пароль не подходит, сеть, таймаут) — в баннер
      if (!sshOk) {
        renderConnWarning({
          title: 'Не удалось подключиться по SSH',
          message: p.ssh_error_human || info.ssh_error || 'Причина неизвестна.',
        });
      } else {
        renderConnWarning(null);
      }
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
  import('./wireguard.js?v=20260911-tabhint-v2').then(m => m.openWgServerById(serverId));
}

// Открыть модальное окно установки WireGuard
function confirmInstallWireGuard(serverId) {
  import('./wireguard.js?v=20260911-tabhint-v2')
    .then(m => m.openInstall(serverId))
    .catch(err => console.error('Ошибка загрузки модуля WireGuard:', err));
}

// Открыть панель Docker для сервера
function openDockerServer(serverId) {
  import('./docker.js?v=20260911-tabhint-v2').then(m => m.openDockerServerById(serverId));
}

// Открыть модальное окно установки Docker
function confirmInstallDocker(serverId) {
  import('./docker.js?v=20260911-tabhint-v2')
    .then(m => m.openInstall(serverId))
    .catch(err => console.error('Ошибка загрузки модуля Docker:', err));
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

    // Метрики карточки — тот же свежий источник uptime, который сохраняет
    // backend в monitor.json. Синхронизируем уже загруженную строку сразу,
    // чтобы после закрытия карточки список не показывал старое значение.
    if (m.uptime && m.uptime !== 'N/A') {
      const index = state.servers.findIndex(server => server.id === openServerId);
      if (index >= 0) {
        const current = state.servers[index];
        const uptimeSeconds = m.uptime_seconds ?? current.uptime_seconds;
        if (current.uptime !== m.uptime || current.uptime_seconds !== uptimeSeconds) {
          state.servers[index] = {
            ...current,
            uptime: m.uptime,
            uptime_seconds: uptimeSeconds,
          };
          lastServers = state.servers;
          renderServers();
        }
      }
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
          <div class="sw-value" style="font-size:1.2rem">${formatUptime(m.uptime, m.uptime_seconds)}</div>
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
  return formatServerDateTime(value);
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

export async function deleteServer() {
  if (!openServerId) return;
  const name = state.openServerData?.server?.name || window._openServerData?.server?.name || 'сервер';
  const approved = await confirmAction({
    title: 'Удалить сервер?',
    message: `Сервер «${name}» будет удалён из Bot4VPS.`,
    confirmText: 'Удалить',
    confirmFirst: true,
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
    toggleAddSslHost();
    toggleAfEmojiPop(false);
    bindPasswordToggles();
  });
}

function toggleAddAuth() {
  const isKey = document.getElementById('af-auth').value === 'key';
  // В key-режиме password хранит отдельный sudo-пароль для non-root
  // (та же семантика, что в TG-редакторе): поле остаётся, меняется подпись.
  document.getElementById('af-key-wrap').classList.toggle('hidden', !isKey);
  const label = document.getElementById('af-password-label');
  const input = document.getElementById('af-password');
  if (label) label.textContent = isKey ? 'Sudo-пароль' : 'Пароль';
  if (input) input.placeholder = isKey ? 'если пользователь не root — можно оставить пустым' : '';
}

/** Эмодзи для имени сервера: кнопка 🙂 у поля ввода → всплывающая сетка.
 *  Первыми идут флаги стран (с тултипом-названием), затем обычные эмодзи. */
const AF_NAME_FLAGS = [
  ['🇩🇪', 'Германия'], ['🇳🇱', 'Нидерланды'], ['🇫🇮', 'Финляндия'], ['🇸🇪', 'Швеция'],
  ['🇳🇴', 'Норвегия'], ['🇩🇰', 'Дания'], ['🇬🇧', 'Великобритания'], ['🇮🇪', 'Ирландия'],
  ['🇫🇷', 'Франция'], ['🇧🇪', 'Бельгия'], ['🇱🇺', 'Люксембург'], ['🇦🇹', 'Австрия'],
  ['🇨🇭', 'Швейцария'], ['🇪🇸', 'Испания'], ['🇵🇹', 'Португалия'], ['🇮🇹', 'Италия'],
  ['🇵🇱', 'Польша'], ['🇨🇿', 'Чехия'], ['🇸🇰', 'Словакия'], ['🇭🇺', 'Венгрия'],
  ['🇷🇴', 'Румыния'], ['🇧🇬', 'Болгария'], ['🇬🇷', 'Греция'], ['🇭🇷', 'Хорватия'],
  ['🇸🇮', 'Словения'], ['🇷🇸', 'Сербия'], ['🇱🇹', 'Литва'], ['🇱🇻', 'Латвия'],
  ['🇪🇪', 'Эстония'], ['🇺🇦', 'Украина'], ['🇷🇺', 'Россия'], ['🇧🇾', 'Беларусь'],
  ['🇲🇩', 'Молдова'], ['🇮🇸', 'Исландия'], ['🇲🇹', 'Мальта'], ['🇨🇾', 'Кипр'],
  ['🇹🇷', 'Турция'], ['🇬🇪', 'Грузия'], ['🇦🇲', 'Армения'], ['🇦🇿', 'Азербайджан'],
  ['🇰🇿', 'Казахстан'], ['🇮🇱', 'Израиль'], ['🇦🇪', 'ОАЭ'], ['🇸🇬', 'Сингапур'],
  ['🇯🇵', 'Япония'], ['🇭🇰', 'Гонконг'], ['🇨🇳', 'Китай'], ['🇰🇷', 'Южная Корея'],
  ['🇮🇳', 'Индия'], ['🇮🇩', 'Индонезия'], ['🇹🇭', 'Таиланд'], ['🇻🇳', 'Вьетнам'],
  ['🇺🇸', 'США'], ['🇨🇦', 'Канада'], ['🇲🇽', 'Мексика'], ['🇧🇷', 'Бразилия'],
  ['🇦🇷', 'Аргентина'], ['🇨🇱', 'Чили'], ['🇦🇺', 'Австралия'], ['🇳🇿', 'Новая Зеландия'],
  ['🇿🇦', 'ЮАР'], ['🇪🇬', 'Египет'], ['🇳🇬', 'Нигерия'], ['🇰🇪', 'Кения'],
  ['🇶🇦', 'Катар'], ['🇰🇼', 'Кувейт'], ['🇸🇦', 'Саудовская Арабия'], ['🇵🇭', 'Филиппины'],
  ['🇲🇾', 'Малайзия'], ['🇹🇼', 'Тайвань'], ['🇧🇩', 'Бангладеш'], ['🇵🇰', 'Пакистан'],
];
const AF_NAME_EMOJIS = [
  '🖥', '💻', '🌐', '🌍', '🐧', '🚀', '⚡', '🔥', '🛡', '💾', '🗄', '🗃',
  '📦', '🧠', '🐳', '🔑', '🔒', '🧩', '⚙', '📡', '🛰', '🎯', '✨', '🌩',
];

function afEmojiItem(e, title = '') {
  return `<button type="button" class="af-emoji-item" data-emoji="${e}"${title ? ` title="${title}"` : ''}>${e}</button>`;
}

function toggleAfEmojiPop(force) {
  const pop = document.getElementById('af-emoji-pop');
  if (!pop) return;
  if (!pop.childElementCount) {
    pop.innerHTML = AF_NAME_FLAGS.map(([e, t]) => afEmojiItem(e, t)).join('')
      + '<div class="af-emoji-sep"></div>'
      + AF_NAME_EMOJIS.map(e => afEmojiItem(e)).join('');
  }
  const show = force === undefined ? pop.classList.contains('hidden') : force;
  pop.classList.toggle('hidden', !show);
}

function insertAfEmoji(emoji) {
  const inp = document.getElementById('af-name');
  if (!inp) return;
  const start = inp.selectionStart ?? inp.value.length;
  const end = inp.selectionEnd ?? start;
  inp.value = inp.value.slice(0, start) + emoji + inp.value.slice(end);
  const pos = start + emoji.length;
  inp.focus();
  inp.setSelectionRange(pos, pos);
  toggleAfEmojiPop(false);
}

/** Поле домена живёт в заголовке рядом с чекбоксом «Проверять SSL»:
 *  без включённой проверки домен не нужен — поле не показываем. */
function toggleAddSslHost() {
  const on = document.getElementById('af-cert')?.checked;
  document.getElementById('af-ssl-wrap')?.classList.toggle('hidden', !on);
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
    ssl_host: (document.getElementById('af-cert').checked
      && document.getElementById('af-ssl').value.trim()) || null,
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

export function bindServerUI(options = {}) {
  quickSetupOpener = typeof options.openQuickSetup === 'function'
    ? options.openQuickSetup
    : null;
  bindServerListUI();
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
  document.getElementById('btn-open-backups')?.addEventListener('click', () => {
    const sid = currentOpenServerId();
    if (sid) openBackupsForServer(sid);
  });
  document.getElementById('btn-open-terminal')?.addEventListener('click', () => openServerTerminal());
  document.getElementById('btn-back-from-terminal')?.addEventListener('click', () => backFromTerminal());
  document.getElementById('af-auth')?.addEventListener('change', toggleAddAuth);
  document.getElementById('af-cert')?.addEventListener('change', toggleAddSslHost);
  document.getElementById('af-emoji-btn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleAfEmojiPop();
  });
  document.getElementById('af-emoji-pop')?.addEventListener('click', (e) => {
    const item = e.target.closest('.af-emoji-item');
    if (item) insertAfEmoji(item.dataset.emoji);
  });
  // Клик мимо поля имени — закрыть всплывающий список эмодзи
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.af-name-wrap')) toggleAfEmojiPop(false);
  });
  document.getElementById('af-save')?.addEventListener('click', submitAddServer);
  document.getElementById('af-cancel')?.addEventListener('click', () =>
    document.getElementById('add-server-modal').classList.remove('open'));
  bindPasswordToggles();
}

function openGroupsPanel() {
  const panel = document.getElementById('groups-panel');
  if (panel) {
    panel.classList.add('open');
    // Загружаем списки групп при открытии панели.
    // Спецификатор тот же, что в app.js — единый инстанс модуля.
    import('./groups_panel.js?v=20260911-groups-v2').then(m => {
      m.loadGroupsAdmin();
      m.loadGroupsDisplayOrder();
    });
  }
}

export function closeGroupsPanel() {
  const panel = document.getElementById('groups-panel');
  if (panel) panel.classList.remove('open');
}

// Установка/удаление сервиса меняет кнопки «Действий с сервером» — вызывается из
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