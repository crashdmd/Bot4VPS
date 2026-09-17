// Страница Docker: тонкий слой отображения над обобщённым services-роутером.
//
// Вся бизнес-логика — на бэке (core.integrator + services/docker): здесь нет
// сборки docker/compose-команд, разбора вывода Docker и работы с путями на
// сервере. Модуль только запрашивает API, рендерит и собирает поля форм.
//
// Экраны: таблица серверов (паттерн «Серверов»/WG) + экран сервера
// с вкладками Контейнеры | Образы | Compose.
import { j, esc } from './api.js';
import { openTaskModal } from './taskmodal.js?v=20260914-v3';
import { statusFilterBtn, statusFilterHidden, bindStatusFilter } from './statusfilter.js?v=20260915-v1';
import { toast, showPage, serverDateTimeParts, serverDayDifference } from './ui.js';
import { ansiToHtml } from './ansi.js';

const SID = 'docker';

// Регэкспы — ТОЛЬКО для мгновенной подсказки в форме (§25).
// Единственный authoritative-валидатор — services/docker/impl/validation.py;
// бэкенд проверяет всё повторно. Держим правила синхронными с PORT_RE/ENV_KEY_RE,
// чтобы форма не отклоняла то, что Core принимает.
const RE_PORT = /^(?:\d{1,3}(?:\.\d{1,3}){3}:)?(\d{1,5}):(\d{1,5})(?:\/(?:tcp|udp))?$/;
const RE_ENV = /^[A-Za-z_][A-Za-z0-9_]*=.*$/;
const HINT_PORT = 'Порт: host:container, можно с IP и протоколом (8080:80, 127.0.0.1:8080:80/tcp)';
const HINT_ENV = 'Переменная окружения: KEY=VALUE (ключ — буквы, цифры, подчёркивание)';

// Формат + диапазон портов — как validate_port в validation.py.
function portOk(val) {
  const m = RE_PORT.exec(val);
  if (!m) return false;
  return [m[1], m[2]].every(p => {
    const n = Number(p);
    return n >= 1 && n <= 65535;
  });
}
const timers = {};                  // taskId -> polling-интервал
let statusMap = {};                 // id -> {name, host, online, status}

// Сортировка таблицы списка — локальное состояние страницы.
let dkSort = { key: 'name', descending: false };

// Экран конкретного сервера
let dockerServerId = null;          // id открытого сервера
let dockerEntryContext = 'list';    // 'list' | 'server' — откуда открыли панель
let dockerServerState = null;       // последний live-state
let dockerCurrentTab = 'containers'; // активная вкладка: containers | images | compose
let dockerContainerSearch = '';
let dockerContainerFilter = 'all';
let dockerImageSearch = '';
let dockerComposeCounts = { local: 0, server: 0, diverged: 0 };
let logsCtx = null;                 // {name} — контейнер в открытой модалке логов

const PORT_PREFS_KEY = 'bot4vps_docker_service_ports';

function serviceUrls(c) {
  const rows = Array.isArray(c?.service_urls) ? c.service_urls : [];
  const urls = rows.filter(x => x && x.port && x.url)
    .map(x => ({ port: String(x.port), url: String(x.url) }));
  // Совместимость с уже запущенным backend/старым кэшем: до первого рестарта
  // там есть только authoritative service_url и published_port.
  if (!urls.length && c?.service_url) {
    const port = String(c.published_port || '').trim()
      || (() => {
        try { return new URL(String(c.service_url)).port; } catch (_) { return ''; }
      })();
    if (port) urls.push({ port, url: String(c.service_url) });
  }
  return urls;
}

function readPortPrefs() {
  try { return JSON.parse(localStorage.getItem(PORT_PREFS_KEY) || '{}') || {}; }
  catch (_) { return {}; }
}

function selectedServiceUrl(c) {
  const urls = serviceUrls(c);
  if (!urls.length) return null;
  const prefs = readPortPrefs();
  const serverPrefs = prefs[dockerServerId] || {};
  const saved = String(serverPrefs[c.id] || '');
  const selected = urls.find(x => x.port === saved) || urls[0];
  if (saved && saved !== selected.port) {
    serverPrefs[c.id] = selected.port;
    prefs[dockerServerId] = serverPrefs;
    try { localStorage.setItem(PORT_PREFS_KEY, JSON.stringify(prefs)); } catch (_) {}
  }
  return selected;
}

function saveServicePort(c, port) {
  if (!c?.id || !dockerServerId) return;
  const valid = serviceUrls(c).some(x => x.port === String(port));
  if (!valid) return;
  const prefs = readPortPrefs();
  prefs[dockerServerId] = prefs[dockerServerId] || {};
  prefs[dockerServerId][c.id] = String(port);
  try { localStorage.setItem(PORT_PREFS_KEY, JSON.stringify(prefs)); } catch (_) {}
}

const srvBase = id => `/api/services/${SID}/${encodeURIComponent(id)}`;
const stateUrl = id => `${srvBase(id)}/state`;
const nameOf = id => (statusMap[id] && statusMap[id].name) || id;

function shortVer(v) {
  const m = String(v || '').match(/\d+\.\d+[\w.-]*/);
  return m ? m[0] : '';
}
function fmtSync(iso) {
  const parts = serverDateTimeParts(iso);
  if (!parts) return '';
  const hm = `${parts.hour}:${parts.minute}`;
  if (serverDayDifference(iso) === 0) return 'сегодня, ' + hm;
  return `${parts.day}.${parts.month}, ${hm}`;
}
// ---------------- in-UI диалог (вместо браузерного confirm) ----------------

let dialogResolve = null;
function dockerConfirm(title, message, okText = 'ОК', cancelText = 'Отмена') {
  return new Promise(resolve => {
    dialogResolve = resolve;
    document.getElementById('docker-dialog-title').textContent = title || '';
    const msg = document.getElementById('docker-dialog-msg');
    if (message) { msg.textContent = message; msg.classList.remove('hidden'); }
    else { msg.classList.add('hidden'); }
    document.getElementById('docker-dialog-ok').textContent = okText;
    document.getElementById('docker-dialog-cancel').textContent = cancelText;
    // Альтернативная кнопка — только у диалога расхождения (§6).
    document.getElementById('docker-dialog-alt').classList.add('hidden');
    document.getElementById('docker-dialog').classList.add('open');
  });
}
function closeDockerDialog(val) {
  document.getElementById('docker-dialog').classList.remove('open');
  const r = dialogResolve; dialogResolve = null;
  if (r) r(val);
}

// ---------------- список серверов (таблица в паттерне WG) ----------------

/** Состояние Docker на сервере. «Не проверен» не существует (как в WG):
 *  пустой кэш = «не установлен» (актуализация — забота фоновой проверки). */
function dkState(st) {
  return st && st.installed ? 'installed' : 'absent';
}

/** Работа с сервисом на этом сервере невозможна (availability-кэш — тот же
 *  источник, что страница «Серверы»): строка некликабельна, вместо колонок
 *  сервиса — сообщение. Критерий — SSH-порт (port_ok): без него управлять
 *  сервисом всё равно нечем, даже если сеть в целом жива. Пока порт не
 *  проверяли (null), смотрим сетевую доступность. null ≠ заблокировано. */
function serviceBlocked(s) {
  const portOk = (s || {}).port_ok;
  if (portOk === false) return (s || {}).online === false ? 'down' : 'ssh';
  if (portOk == null && (s || {}).online === false) return 'down';
  return null;
}

const DK_BLOCKED_NOTE = {
  down: ['⛔ Сервер оффлайн — работа с сервисом невозможна', '⛔ Оффлайн'],
  ssh: ['⛔ SSH-порт недоступен — работа с сервисом невозможна', '⛔ Нет SSH'],
};

export async function loadDocker() {
  const el = document.getElementById('docker-servers');
  if (!el) return;
  try {
    const d = await j(`/api/services/${SID}/status`);
    statusMap = {};
    (d.servers || []).forEach(s => { statusMap[s.id] = s; });
    renderDockerServers();
  } catch (e) {
    el.innerHTML = '<div class="empty" style="color:var(--err)">' + esc(e.message || e) + '</div>';
  }
}

/** Сравнение версий по числовым сегментам («29.8.0» и т.п.), независимо
 *  от суффиксов сборки — как в WG. */
function compareVersions(a, b) {
  const pa = String(a || '').match(/\d+/g) || [];
  const pb = String(b || '').match(/\d+/g) || [];
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const na = i < pa.length ? +pa[i] : -1;
    const nb = i < pb.length ? +pb[i] : -1;
    if (na !== nb) return na - nb;
  }
  return 0;
}

function sortedDockerServers(list) {
  const byName = [...list].sort((a, b) =>
    String(a.name || '').localeCompare(String(b.name || ''), 'ru', { sensitivity: 'base', numeric: true })
      || String(a.id).localeCompare(String(b.id)));
  const key = dkSort.key;
  if (key === 'status') {
    // Запущенные сверху ↔ остановленные сверху; без сервиса — всегда внизу.
    const rank = s => {
      const st = (s || {}).status || {};
      if (!st.installed) return 2;
      return String(st.active || '').toLowerCase() === 'active' ? 0 : 1;
    };
    const d = dkSort.descending ? -1 : 1;
    return byName.sort((a, b) => {
      const ra = rank(a), rb = rank(b);
      if (ra === 2 || rb === 2) return ra - rb;
      return (ra - rb) * d;
    });
  }
  if (key === 'version') {
    // Свежая → старая (первый клик) и обратно; без версии — всегда внизу.
    const has = s => String((((s || {}).status || {}).version) || '').trim() !== '';
    return byName.sort((a, b) => {
      if (has(a) !== has(b)) return has(a) ? -1 : 1;
      if (!has(a)) return 0;
      const va = a.status.version, vb = b.status.version;
      return dkSort.descending ? compareVersions(vb, va) : compareVersions(va, vb);
    });
  }
  if (key === 'containers') {
    // Больше контейнеров ↔ меньше; без сервиса — всегда внизу.
    const has = s => dkState((s || {}).status || {}) === 'installed';
    const cnt = s => Number((((s || {}).status || {}).stats || {}).total || 0);
    const d = dkSort.descending ? -1 : 1;
    return byName.sort((a, b) =>
      has(a) !== has(b) ? (has(a) ? -1 : 1) : (cnt(a) - cnt(b)) * d);
  }
  return dkSort.descending ? byName.reverse() : byName;
}

function dkStatusCell(st) {
  return String(st.active || '').toLowerCase() === 'active'
    ? '<span class="badge on" title="Запущен">🟢 Запущен</span>'
    : '<span class="badge off" title="Демон остановлен">🔴 Остановлен</span>';
}

function dkRowCells(s) {
  const st = s.status || {};
  const name = `<td class="server-name-cell" data-label="Имя сервера"><strong>${esc(s.name || '—')}</strong></td>`;
  // Недоступный сервер: колонки сервиса не показываем — работа невозможна
  // (строка некликабельна). Причина — оффлайн или закрытый SSH-порт.
  const blocked = serviceBlocked(s);
  if (blocked) {
    const [full, short] = DK_BLOCKED_NOTE[blocked];
    return `${name}
      <td colspan="3" class="svc-offline-cell"><span class="svc-offline-note">
        <span class="svc-offline-note-full">${full}</span>
        <span class="svc-offline-note-short">${short}</span>
      </span></td>`;
  }
  if (dkState(st) === 'installed') {
    const stats = st.stats || {};
    return `${name}
      <td class="dk-status-cell" data-label="Статус">${dkStatusCell(st)}</td>
      <td class="wg-version-cell" data-label="Версия">${esc(shortVer(st.version) || '—')}</td>
      <td class="dk-containers-cell" data-label="Контейнеры">${Number(stats.running || 0)}/${Number(stats.total || 0)}</td>`;
  }
  // Не установлен: статус-бейдж на своём месте (как у WG), кнопка
  // «Установить» — в столбце Версия (Контейнеры остаётся пустой).
  // svc-badge-absent — на мобиле превращается в красный крест (маркер).
  return `${name}
    <td class="dk-status-cell" data-label="Статус"><span class="badge off svc-badge-absent" title="Не установлен">⚪ Не установлен</span></td>
    <td class="wg-row-action-cell"><button type="button" class="wg-row-action" data-install="${esc(s.id)}"><span class="dk-btn-emoji">🟢 </span>Установить</button></td>
    <td class="dk-fill-cell"></td>`;
}

// ---------------- заголовки таблицы ----------------

/** Статус строки для фильтра (см. DK_STATUS_FILTERS). */
function dkFilterKey(s) {
  if (serviceBlocked(s)) return 'blocked';
  const st = s.status || {};
  if (dkState(st) !== 'installed') return 'absent';
  return String(st.active || '').toLowerCase() === 'active' ? 'running' : 'stopped';
}

const DK_STATUS_FILTERS = [
  { key: 'running', label: '🟢 Запущен' },
  { key: 'stopped', label: '🔴 Демон остановлен' },
  { key: 'absent', label: '⚪ Не установлен' },
  { key: 'blocked', label: '⛔ Недоступен (оффлайн/SSH)' },
];

function dkSortHeader(key, label, extra = '') {
  const active = dkSort.key === key;
  const descending = active && dkSort.descending;
  const ariaSort = active ? (descending ? 'descending' : 'ascending') : 'none';
  return `<th aria-sort="${ariaSort}">
    <span class="wg-col-head">
      <button type="button" class="server-column-sort${active ? ' on' : ''}" data-dk-sort="${esc(key)}"
              aria-pressed="${active ? 'true' : 'false'}"
              title="Сортировать по столбцу «${esc(label)}»">
        <span>${esc(label)}</span>
        <span class="server-sort-arrow" aria-hidden="true">${active ? (descending ? '↓' : '↑') : ''}</span>
      </button>${extra}
    </span>
  </th>`;
}

// ---------------- рендер ----------------

function renderDockerRows() {
  const all = sortedDockerServers(Object.values(statusMap));
  if (!all.length) return '<tr><td colspan="4" class="wg-empty-row">Нет серверов</td></tr>';
  // Фильтр статусов (кнопка у заголовка «Статус»)
  const hidden = statusFilterHidden('docker', DK_STATUS_FILTERS);
  const list = hidden.size ? all.filter(s => !hidden.has(dkFilterKey(s))) : all;
  if (!list.length) return '<tr><td colspan="4" class="wg-empty-row">Все серверы скрыты фильтром статуса</td></tr>';
  return list.map(s => {
    // Кликабельна только установленная строка на доступном сервере
    // (остальные подсвечиваются, но без перехода)
    const interactive = dkState(s.status || {}) === 'installed' && !serviceBlocked(s);
    return `<tr class="server-table-row${interactive ? '' : ' wg-row-static'}"
                data-sid="${esc(s.id)}"${interactive ? ' tabindex="0" role="button"' : ''}>${dkRowCells(s)}</tr>`;
  }).join('');
}

function renderDockerServers() {
  const el = document.getElementById('docker-servers');
  if (!el) return;
  if (!Object.keys(statusMap).length) {
    el.innerHTML = '<div class="empty">Нет серверов</div>';
    return;
  }
  el.innerHTML = `<div class="server-table-wrap">
    <table class="server-table dk-server-table">
      <thead><tr>
        ${dkSortHeader('name', 'Имя сервера')}
        ${dkSortHeader('status', 'Статус', statusFilterBtn('docker'))}
        ${dkSortHeader('version', 'Версия')}
        ${dkSortHeader('containers', 'Контейнеры')}
      </tr></thead>
      <tbody>${renderDockerRows()}</tbody>
    </table>
  </div>`;
  bindStatusFilter('docker', DK_STATUS_FILTERS, renderDockerServers);
}

/** Клик по строке — только установленленный Docker на доступном сервере:
 *  открывается экран этого сервера. «Не установлен» и оффлайн никуда не ведут
 *  (действие неустановленного — кнопка в объединённой области). */
async function openDockerRow(id) {
  const srv = statusMap[id] || {};
  if (serviceBlocked(srv) || dkState(srv.status || {}) !== 'installed') return;
  openDockerServer(id);
}

// ---------------- события таблицы списка ----------------

function bindDockerServersList() {
  const el = document.getElementById('docker-servers');
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';
  el.addEventListener('click', async event => {
    const sortBtn = event.target.closest('[data-dk-sort]');
    if (sortBtn) {
      event.preventDefault(); event.stopPropagation();
      const key = sortBtn.dataset.dkSort;
      // «Версия» — первый клик сразу от свежей к старой (как в WG)
      dkSort = dkSort.key === key
        ? { key, descending: !dkSort.descending }
        : { key, descending: key === 'version' };
      renderDockerServers();
      return;
    }
    const installBtn = event.target.closest('[data-install]');
    if (installBtn) {
      event.preventDefault(); event.stopPropagation();
      installServer(installBtn.dataset.install);
      return;
    }
    const row = event.target.closest('tr[data-sid]');
    if (row) openDockerRow(row.dataset.sid);
  });
  el.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const row = event.target.closest('tr[data-sid]');
    if (!row) return;
    event.preventDefault();
    openDockerRow(row.dataset.sid);
  });
}

async function installServer(id) {
  const srv = statusMap[id];
  const name = srv && srv.name ? srv.name : (srv && srv.host ? srv.host : id);
  if (!(await dockerConfirm('Установка Docker',
    `Вы действительно хотите установить Docker на сервер «${name}»?\n\n` +
    `Будет установлен Docker Engine через официальный скрипт get.docker.com ` +
    `. Процесс необратим.`,
    'Установить'))) return;
  // Живой прогресс в модалке (паттерн установки 3x-ui): get.docker.com
  // шумный, ~15 минут — без окна было не видно, что происходит.
  await enqueueAction(id, 'install', {}, null, task => openTaskModal({
    title: `Установка Docker — ${name}`,
    taskId: task.id,
    doneLabel: 'Готово — Docker установлен',
    onDone: t => { if (t.success) window.refreshAfterServiceChange?.(id); },
    onClose: () => { loadDocker(); },
  }));
}


// ---------------- отдельный экран сервера ----------------

let _liveTimer = null;
function startLivePoll(id) {
  stopLivePoll();
  _liveTimer = setInterval(() => {
    if (dockerServerId !== id) { stopLivePoll(); return; }
    if (document.querySelector('.modal-bg.open')) return;  // не мешаем формам/логам
    loadServerDetail(id).catch(() => {});
    // Обновить активную вкладку (Phase 4 — образы, Phase 5 — стеки)
    if (dockerCurrentTab === 'images') loadImages().catch(() => {});
    else if (dockerCurrentTab === 'compose') loadStacks().catch(() => {});
  }, 5000);
}
function stopLivePoll() {
  if (_liveTimer) { clearInterval(_liveTimer); _liveTimer = null; }
}

async function openDockerServer(id, opts = {}) {
  dockerServerId = id;
  dockerEntryContext = opts.from === 'server' ? 'server' : 'list';
  dockerServerState = null;
  dockerCurrentTab = 'containers';
  try {
    localStorage.setItem('bot4vps_page', 'docker-server');
    localStorage.setItem('bot4vps_docker_server_id', id);
  } catch (_) {}
  // Иконка в h1 живёт отдельно — текст пишем в span, чтобы не затирать SVG.
  const titleEl = document.querySelector('#docker-srv-title .srv-title-name');
  if (titleEl) titleEl.textContent = 'Docker · ' + nameOf(id);
  const subEl0 = document.getElementById('docker-srv-subtitle');
  if (subEl0) subEl0.textContent = '';
  const widgets = document.getElementById('docker-srv-widgets');
  if (widgets) widgets.innerHTML = '';
  const actionsEl0 = document.getElementById('docker-srv-actions');
  if (actionsEl0) actionsEl0.innerHTML = '';
  document.getElementById('docker-srv-body').innerHTML = '<div class="empty">Загрузка…</div>';
  document.getElementById('docker-images-body').innerHTML = '<div class="empty">Загрузка…</div>';
  document.getElementById('docker-compose-body').innerHTML = '<div class="empty">Загрузка…</div>';
  document.querySelectorAll('#docker-srv-tabs [data-dstab]').forEach(tab => {
    tab.classList.toggle('on', tab.dataset.dstab === 'containers');
    tab.onclick = () => switchDockerTab(tab.dataset.dstab);
  });
  Object.entries(DOCKER_TAB_BODIES).forEach(([key, elId]) => {
    document.getElementById(elId)?.classList.toggle('hidden', key !== 'containers');
  });
  showPage('docker-server');
  await loadServerDetail(id);
  startLivePoll(id);
  // Прогресс загрузки образов — на любой вкладке: начнётся докачка (хоть из ТГ),
  // сами откроем «Образы», а по запуску контейнера вернём на «Контейнеры».
  startPullPoll();
}

function backToDockerList() {
  stopLivePoll();
  stopPullPoll();
  dockerPulling = [];
  _hadPulling = false;
  _pullAutoShown = false;
  _pullContainerArmed = null;
  _pullCancelledSeen = false;
  dockerServerId = null;
  try {
    localStorage.setItem('bot4vps_page', 'docker');
    localStorage.removeItem('bot4vps_docker_server_id');
  } catch (_) {}
  showPage('docker');
  loadDocker();
}

/** Docker не установлен, а пользователь оказался на странице сервиса
 *  (восстановление сессии, устаревшая ссылка, завершившееся удаление) —
 *  уходим туда, откуда пришли: в карточку сервера или в список Docker. */
async function leaveUninstalledPage(id) {
  const returnToServer = dockerEntryContext === 'server' && id;
  stopLivePoll();
  dockerServerId = null;
  try { localStorage.removeItem('bot4vps_docker_server_id'); } catch (_) {}
  if (returnToServer) {
    try {
      const { openServer } = await import('./servers.js?v=20260915-sysfix-v2');
      await openServer(id);
      return;
    } catch (_) { /* модуль не загрузился — fallback в список ниже */ }
  }
  backToDockerList();
}

async function loadServerDetail(id) {
  try {
    const d = await j(stateUrl(id));
    dockerServerState = d.state || {};
    // Не установлен — на этой странице делать нечего: уводим пользователя
    // туда, откуда он пришёл (карточка сервера / список Docker). Покрывает и
    // восстановление сессии, и устаревшую вкладку.
    if (dockerServerState.installed === false) {
      await leaveUninstalledPage(id); return;
    }
    try {
      const stacks = await j(`${srvBase(id)}/stacks`);
      const rows = Array.isArray(stacks.rows) ? stacks.rows : [];
      dockerComposeCounts = {
        local: rows.filter(r => r.in_library).length,
        server: rows.filter(r => r.source === 'server').length,
        diverged: rows.filter(r => r.in_library && r.source === 'server' && r.lib_match === false).length,
      };
    } catch (_) {
      dockerComposeCounts = { local: 0, server: 0, diverged: 0 };
    }
    renderServerDetail(dockerServerState);
  } catch (e) {
    document.getElementById('docker-srv-body').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function renderServerDetail(st) {
  const body = document.getElementById('docker-srv-body');
  const widgetsEl = document.getElementById('docker-srv-widgets');
  if (!body) return;
  const s = st || {};
  if (!s.installed) {
    if (widgetsEl) widgetsEl.innerHTML = '';
    const actionsEl = document.getElementById('docker-srv-actions');
    if (actionsEl) actionsEl.innerHTML = '';
    const badgeOff = document.getElementById('docker-srv-badge');
    if (badgeOff) badgeOff.innerHTML = '<span class="badge off">Не установлен</span>';
    body.innerHTML = '<div class="empty">Docker не установлен на этом сервере.</div>';
    return;
  }
  const containers = Array.isArray(s.containers) ? s.containers : [];
  const stats = s.stats || { total: containers.length, running: 0, managed: 0, images: 0, volumes: 0 };

  const daemonOk = String(s.active || '').toLowerCase() === 'active';

  const daemonHtml = daemonOk
    ? '<span class="ssh-dot ok"></span> Запущен'
    : `<span class="ssh-dot err"></span> ${esc(s.active ? 'Остановлен' : '—')}`;

  // ── Верхний грид в стиле WireGuard: Демон / Статистика / Compose ──
  const infoRow = (label, value) =>
    `<div class="info-row"><span class="info-label">${esc(label)}</span><span class="info-value">${value}</span></div>`;

  const daemonCard = `
    <div class="info-block svc-card">
      <h2>Демон Docker</h2>
      ${infoRow('Статус', daemonHtml)}
      ${infoRow('Версия', esc(shortVer(s.version) || s.version || '—'))}
      ${infoRow('Дата последней синхронизации', esc(fmtSync(s.synced_at) || '—'))}
    </div>`;

  const total = stats.total || containers.length;
  const statTile = (icon, value, label) => `
    <div class="svc-stat-card">
      <div class="svc-stat-icon">${icon}</div>
      <div class="svc-stat-val">${esc(String(value))}</div>
      <div class="svc-stat-label">${esc(label)}</div>
    </div>`;
  const statsCard = `
    <div class="info-block svc-card">
      <h2>Статистика</h2>
      <div class="svc-stats-grid-3">
        ${statTile('▦', `${stats.running || 0} / ${total}`, 'Запущено / Всего')}
        ${statTile('💿', stats.images ?? '—', 'Образы')}
        ${statTile('🗄', stats.volumes ?? '—', 'Тома')}
      </div>
    </div>`;

  const composeCard = `
    <div class="info-block svc-card">
      <h2>Compose проекты</h2>
      ${infoRow('Локальных (библиотека)', esc(String(dockerComposeCounts.local)))}
      ${infoRow('На сервере', esc(String(dockerComposeCounts.server)))}
      ${infoRow('Расходится', esc(String(dockerComposeCounts.diverged)))}
    </div>`;

  if (widgetsEl) {
    widgetsEl.innerHTML = `<div class="svc-top-grid">${daemonCard}${statsCard}${composeCard}</div>`;
  }

  renderSideActions(s);

  // ── Вкладка «Контейнеры»: широкая карточка в левой колонке ──
  // Каркас создаём один раз — иначе поиск теряет фокус на каждый ввод
  let card = body.querySelector('.docker-ct-card');
  if (!card) {
    body.innerHTML = `
      <div class="info-block svc-card docker-ct-card">
        <div class="svc-card-head svc-card-head-one-line">
          <h2>Контейнеры <span class="hint" data-ct-count>(${containers.length})</span></h2>
          <div class="svc-card-actions">
            <input type="search" id="docker-ct-search" placeholder="🔍 Поиск контейнера…" autocomplete="off"/>
            <select id="docker-ct-filter" title="Статус">
              <option value="all">Все</option>
              <option value="running">Запущенные</option>
              <option value="stopped">Остановленные</option>
            </select>
            <button type="button" id="docker-ct-create">＋ Создать контейнер</button>
          </div>
        </div>
        <div class="docker-ct-scroll" id="docker-ct-list"></div>
      </div>`;
    card = body.querySelector('.docker-ct-card');
    const search = body.querySelector('#docker-ct-search');
    const filter = body.querySelector('#docker-ct-filter');
    if (search) {
      search.value = dockerContainerSearch;
      search.addEventListener('input', (e) => {
        dockerContainerSearch = e.target.value;
        fillContainerList(dockerServerState);
      });
    }
    if (filter) {
      filter.value = dockerContainerFilter;
      filter.addEventListener('change', (e) => {
        dockerContainerFilter = e.target.value;
        fillContainerList(dockerServerState);
      });
    }
    body.querySelector('#docker-ct-create')?.addEventListener('click', openRunModal);
  } else {
    // синхронизировать контролы без пересоздания (live-poll)
    const search = body.querySelector('#docker-ct-search');
    const filter = body.querySelector('#docker-ct-filter');
    if (search && document.activeElement !== search) search.value = dockerContainerSearch;
    if (filter && document.activeElement !== filter) filter.value = dockerContainerFilter;
    const countEl = card.querySelector('[data-ct-count]');
    if (countEl) countEl.textContent = `(${containers.length})`;
  }

  fillContainerList(s);
}

// ── «Дополнительные действия»: постоянная карточка справа от вкладок ──
// Пересобирается на каждом рендере (live-poll): кнопка демона меняется на
// состояние из свежего стейта. Полей ввода внутри нет — фокус терять нечему.
function renderSideActions(s) {
  const el = document.getElementById('docker-srv-actions');
  if (!el) return;
  const daemonOk = String(s.active || '').toLowerCase() === 'active';
  const daemonBtn = daemonOk
    ? `<button type="button" class="svc-action svc-action-warn" data-dk-side="daemon-stop">
         <b>⏹ Остановить Docker</b>
         <span>Выключить демон Docker на сервере</span>
       </button>`
    : `<button type="button" class="svc-action" data-dk-side="daemon-start">
         <b>▶ Запустить Docker</b>
         <span>Включить демон Docker на сервере</span>
       </button>`;
  el.innerHTML = `
    <h2>Дополнительные действия</h2>
    <button type="button" class="svc-action" data-dk-side="pull">
      <b>⬇️ Загрузить образ</b>
      <span>Скачать образ из реестра (Docker Hub и др.)</span>
    </button>
    <button type="button" class="svc-action" data-dk-side="prune">
      <b>🧹 Очистить неиспользуемые образы</b>
      <span>Удалить образы без привязанных контейнеров</span>
    </button>
    <button type="button" class="svc-action" data-dk-side="sync">
      <b>⟳ Синхронизировать</b>
      <span>Обновить состояние с сервера</span>
    </button>
    ${daemonBtn}
    <button type="button" class="svc-action svc-action-danger" data-dk-side="remove">
      <b>🗑 Удалить Docker</b>
      <span>Удалить пакеты Docker с сервера</span>
    </button>`;

  const bind = (sel, fn) => el.querySelector(sel)?.addEventListener('click', fn);
  bind('[data-dk-side="pull"]', openPullModal);
  bind('[data-dk-side="prune"]', pruneImages);
  bind('[data-dk-side="sync"]', async () => {
    if (!dockerServerId) return;
    try {
      await j(`${srvBase(dockerServerId)}/sync`, { method: 'POST' });
      await loadServerDetail(dockerServerId);
      if (dockerCurrentTab === 'images') await loadImages();
      else if (dockerCurrentTab === 'compose') await loadStacks();
      toast('Синхронизация выполнена', true);
    } catch (e) {
      toast(e.message, false);
    }
  });
  bind('[data-dk-side="daemon-stop"]', async () => {
    if (!dockerServerId) return;
    if (!(await dockerConfirm('Остановить Docker',
      'Выключить демон Docker на этом сервере?\n\n' +
      'Запущенные контейнеры продолжат работать (ими управляет containerd), ' +
      'но панель не сможет управлять ими до включения демона.',
      'Остановить'))) return;
    await enqueueAction(dockerServerId, 'daemon_stop', {}, 'Остановка демона в очереди');
  });
  bind('[data-dk-side="daemon-start"]', async () => {
    if (!dockerServerId) return;
    await enqueueAction(dockerServerId, 'daemon_start', {}, 'Запуск демона в очереди');
  });
  // Удаление сервиса — как у WG: подтверждение → задача в очереди (do_remove).
  bind('[data-dk-side="remove"]', async () => {
    if (!dockerServerId) return;
    if (!(await dockerConfirm('Удалить Docker',
      `Удалить Docker с этого сервера?\n\n` +
      `Будут удалены пакеты Docker Engine; данные в /var/lib/docker ` +
      `(образы, контейнеры, тома) сохранятся.`,
      'Удалить'))) return;
    await enqueueAction(dockerServerId, 'remove', {}, 'Удаление в очереди');
  });
}

function fillContainerList(st) {
  const listEl = document.getElementById('docker-ct-list');
  if (!listEl) return;
  const s = st || dockerServerState || {};
  const containers = Array.isArray(s.containers) ? s.containers : [];
  const q = dockerContainerSearch.trim().toLowerCase();
  const stFilter = dockerContainerFilter;
  let list = containers;
  if (q) {
    list = list.filter(c =>
      String(c.name || '').toLowerCase().includes(q) ||
      String(c.image || '').toLowerCase().includes(q));
  }
  if (stFilter === 'running') list = list.filter(c => c.state === 'running');
  if (stFilter === 'stopped') list = list.filter(c => c.state !== 'running');

  const statusBadge = (c) => {
    if (c.state === 'running') return '<span class="badge on">running</span>';
    if (c.state === 'exited') return '<span class="badge off">exited</span>';
    return `<span class="badge ssl-warn">${esc(c.state || '—')}</span>`;
  };

  const rows = list.map(c => {
    const portsArr = Array.isArray(c.ports) ? c.ports : (c.ports ? [c.ports] : []);
    const ports = portsArr.length ? portsArr.join(', ') : '—';
    const uptime = c.uptime_seconds != null ? formatUptime(c.uptime_seconds) : (c.status || '—');
    // service_urls строит backend. Кнопка открытия — рядом с «⋯», в один клик;
    // выбор порта, когда их несколько, — в меню «⋯».
    const selected = selectedServiceUrl(c);
    const openBtn = selected
      ? `<button type="button" class="secondary docker-ct-open" data-cid="${esc(c.id)}" title="Открыть сервис (порт ${esc(selected.port)})">↗ Открыть</button>`
      : '';
    return `<tr>
      <td class="col-name"><span class="docker-ct-cell"><b>${esc(c.name)}</b>${c.managed ? ' <span class="badge on">Bot4VPS</span>' : ''}</span></td>
      <td class="col-image"><span class="docker-ct-cell mono trunc" title="${esc(c.image || '')}">${esc(c.image || '—')}</span></td>
      <td class="col-status"><span class="docker-ct-cell">${statusBadge(c)}</span></td>
      <td class="col-ports"><span class="docker-ct-cell mono trunc" title="${esc(String(ports))}">${esc(String(ports))}</span></td>
      <td class="col-up"><span class="docker-ct-cell">${esc(String(uptime))}</span></td>
      <td class="col-act">
        <div class="docker-ct-actions">
          ${openBtn}
          <button type="button" class="secondary docker-ct-more" data-cmenu="${esc(c.name)}" title="Действия">⋯</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  if (!list.length) {
    listEl.innerHTML = `<div class="empty svc-empty">Контейнеров нет<br><span class="hint">Запустите контейнер или создайте новый.</span></div>`;
  } else {
    listEl.innerHTML = `<table class="svc-table docker-ct-table">
      <thead><tr>
        <th class="col-name">Имя</th>
        <th class="col-image">Образ</th>
        <th class="col-status">Статус</th>
        <th class="col-ports">Порты</th>
        <th class="col-up">Запущен</th>
        <th class="col-act">Действия</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  listEl.querySelectorAll('[data-cmenu]').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      openContainerMenu(btn, btn.dataset.cmenu);
    };
  });
  listEl.querySelectorAll('[data-cid]').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const c = containers.find(x => String(x.id) === String(btn.dataset.cid));
      const selected = c ? selectedServiceUrl(c) : null;
      if (selected?.url) window.open(selected.url, '_blank', 'noopener');
    };
  });
}

function openContainerMenu(anchor, name) {
  const pop = document.getElementById('docker-ct-pop');
  if (!pop || !dockerServerState) return;
  const c = (dockerServerState.containers || []).find(x => x.name === name);
  if (!c) return;
  const running = c.state === 'running';
  const startStop = running
    ? `<button type="button" data-cact="stop">Остановить контейнер</button>`
    : `<button type="button" data-cact="start">Запустить контейнер</button>`;
  const urls = serviceUrls(c);
  const selected = selectedServiceUrl(c);
  // Кнопка «↗ Открыть» живёт в строке рядом с «⋯»; в меню остаётся только
  // выбор порта, когда сервисов/портов несколько.
  const portMenu = urls.length > 1 && selected
    ? `<button type="button" class="docker-ct-port-entry" data-cport-menu
         aria-haspopup="menu" aria-expanded="false">
         <span>Порт открытия: ${esc(selected.port)}</span><span aria-hidden="true">›</span>
       </button>
       <div class="wg-prof-pop docker-ct-port-submenu hidden" role="menu">
         ${urls.map(x => `<button type="button" data-cport-choice="${esc(x.port)}" role="menuitem">
           <span class="docker-ct-port-check" aria-hidden="true">${x.port === selected.port ? '✓' : ''}</span>
           <span>${esc(x.port)}</span>
         </button>`).join('')}
       </div>`
    : '';
  pop.innerHTML = `
    ${startStop}
    <button type="button" data-cact="restart">Перезапустить контейнер</button>
    <button type="button" data-cact="logs">Логи</button>
    ${portMenu}
    <hr/>
    <button type="button" class="danger docker-ct-danger" data-cact="rm">Удалить контейнер</button>`;
  pop.classList.remove('hidden');
  const r = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth || 200;
  let left = r.right - pw;
  let top = r.bottom + 4;
  left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
  if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, r.top - pop.offsetHeight - 4);
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  pop.style.position = 'fixed';

  const portTrigger = pop.querySelector('[data-cport-menu]');
  const portSubmenu = pop.querySelector('.docker-ct-port-submenu');
  let onDoc = null;
  const hidePortSubmenu = () => {
    portSubmenu?.classList.add('hidden');
    portTrigger?.setAttribute('aria-expanded', 'false');
  };
  const close = () => {
    hidePortSubmenu();
    pop.classList.add('hidden');
    if (onDoc) document.removeEventListener('click', onDoc, true);
  };
  const showPortSubmenu = () => {
    if (!portTrigger || !portSubmenu) return;
    portSubmenu.classList.remove('hidden');
    portTrigger.setAttribute('aria-expanded', 'true');
    const triggerRect = portTrigger.getBoundingClientRect();
    const sw = portSubmenu.offsetWidth || 120;
    const sh = portSubmenu.offsetHeight || 40;
    const gap = 4;
    const margin = 8;
    const spaceRight = window.innerWidth - triggerRect.right - margin;
    const spaceLeft = triggerRect.left - margin;
    let subLeft = (spaceRight >= sw + gap || spaceRight >= spaceLeft)
      ? triggerRect.right + gap
      : triggerRect.left - sw - gap;
    subLeft = Math.max(margin, Math.min(subLeft, window.innerWidth - sw - margin));
    const subTop = Math.max(
      margin,
      Math.min(triggerRect.top, window.innerHeight - sh - margin),
    );
    portSubmenu.style.position = 'fixed';
    portSubmenu.style.left = subLeft + 'px';
    portSubmenu.style.top = subTop + 'px';
  };

  pop.querySelectorAll('[data-cact]').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation();
      close();
      await containerAction(name, b.dataset.cact);
    };
  });
  if (portTrigger && portSubmenu) {
    portTrigger.onmouseenter = showPortSubmenu;
    portTrigger.onfocus = showPortSubmenu;
    portTrigger.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (portSubmenu.classList.contains('hidden')) showPortSubmenu();
      else hidePortSubmenu();
    };
    portSubmenu.querySelectorAll('[data-cport-choice]').forEach(b => {
      b.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        saveServicePort(c, b.dataset.cportChoice);
        close();
      };
    });
  }
  onDoc = (ev) => {
    if (!pop.contains(ev.target) && ev.target !== anchor) close();
  };
  setTimeout(() => document.addEventListener('click', onDoc, true), 0);
}

// ---------------- вкладка "Образы" (Phase 4) ----------------

const DOCKER_TAB_BODIES = {
  containers: 'docker-srv-body',
  images: 'docker-images-body',
  compose: 'docker-compose-body',
};

function switchDockerTab(tab) {
  if (!DOCKER_TAB_BODIES[tab]) return;
  dockerCurrentTab = tab;
  document.querySelectorAll('#docker-srv-tabs [data-dstab]').forEach(t =>
    t.classList.toggle('on', t.dataset.dstab === tab));
  Object.entries(DOCKER_TAB_BODIES).forEach(([key, id]) => {
    document.getElementById(id)?.classList.toggle('hidden', key !== tab);
  });
  if (tab === 'images') loadImages();
  else if (tab === 'compose') loadStacks();
}

async function loadImages() {
  const body = document.getElementById('docker-images-body');
  if (!body || !dockerServerId) return;
  try {
    const d = await j(`${srvBase(dockerServerId)}/images`);
    lastImages = d.images || [];
    renderImages(lastImages);
  } catch (e) {
    body.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

// ---------------- прогресс загрузки образов (pull_progress на бэке) ----------------
// Задача (docker pull / предзагрузка compose и контейнеров) пишет проценты в
// реестр на бэке; экран Docker-сервера опрашивает лёгкий in-memory эндпоинт
// без SSH — на любой вкладке, не только «Образы».
//
// Сценарий пользователя: началась загрузка (вдруг откуда — контейнер, compose,
// ТГ, другое окно) → один раз открываем вкладку «Образы» с живым баром.
// Докачка кончилась запуском контейнера/стека → переходим на «Контейнеры»;
// просто набор образов (image_pull) — остаёмся на «Образах».

let dockerPulling = [];   // [{image, percent, detail, cancelled}, ...]
let lastImages = [];
let _pullTimer = null;
let _hadPulling = false;
let _pullAutoShown = false;     // вкладку «Образы» для этой пачки уже открывали
let _pullContainerArmed = null; // свой enqueue запуска стека/контейнера ждёт конца докачки
let _pullCancelledSeen = false; // в этой пачке была отмена — на «Контейнеры» не уходим

function stopPullPoll() {
  if (_pullTimer) { clearInterval(_pullTimer); _pullTimer = null; }
}

function startPullPoll() {
  stopPullPoll();
  pullTick();
  _pullTimer = setInterval(pullTick, 2000);
}

// Контейнерный запуск идёт прямо сейчас (очередь задач)? Понимаем по именам
// задач: «запуск стека» матчит и «перезапуск стека». Покрывает ТГ и другие
// окна — там своего enqueue-флага у нас нет.
async function containerTaskRunning() {
  try {
    const r = await j('/api/queues');
    const row = (r.queues || []).find(q => q.server_id === dockerServerId);
    if (!row) return false;
    return [row.running, ...(row.queue || [])].some(t => t && t.name && (
      String(t.name).includes('запуск стека')
      || String(t.name).includes('запуск контейнера')));
  } catch { return false; }
}

// Докачка закончилась: это был запуск контейнера/стека?
async function afterPullsFinished() {
  let containerStart = !!_pullContainerArmed;
  _pullContainerArmed = null;
  if (!containerStart) containerStart = await containerTaskRunning();
  if (containerStart && dockerCurrentTab !== 'containers') switchDockerTab('containers');
}

async function pullTick() {
  if (!dockerServerId) { stopPullPoll(); return; }
  try {
    const d = await j(`${srvBase(dockerServerId)}/images/pulling`);
    const pulling = d.pulling || [];
    // Отмена в пачке (кнопка ✕): контейнер НЕ запустится, значит и перенос
    // на «Контейнеры» после исчезновения строки — ложный. Запоминаем до
    // конца пачки: флаг cancelled приходит и через in-place обновление.
    if (pulling.some(p => p.cancelled)) _pullCancelledSeen = true;
    // Менялись только проценты — не дёргаем весь рендер, обновляем бары на месте.
    if (dockerPulling.length === pulling.length
        && pulling.every((p, i) => p.image === dockerPulling[i].image)) {
      pulling.forEach((p, i) => {
        const row = document.querySelector(`[data-pull-row="${CSS.escape(p.image)}"]`);
        if (!row) return;
        row.querySelector('.img-pull-fill').style.width = `${p.percent}%`;
        row.querySelector('.img-pull-text').textContent = p.cancelled
          ? 'отменяется…'
          : `${p.percent}%${p.detail ? ' · ' + p.detail : ''}`;
        row.classList.toggle('img-pulling-cancelled', !!p.cancelled);
        const btn = row.querySelector('.img-pull-cancel');
        if (btn) btn.disabled = !!p.cancelled;
      });
      dockerPulling = pulling;
      return;
    }
    dockerPulling = pulling;
    renderImages(lastImages);
    if (pulling.length) {
      _hadPulling = true;
      // Один раз за пачку открываем «Образы»; открытая модалка — не под ней же
      // дёргать вкладки, подождём закрытия (следующий тик это доиграет).
      if (!_pullAutoShown && dockerCurrentTab !== 'images'
          && !document.querySelector('.modal-bg.open')) {
        _pullAutoShown = true;
        switchDockerTab('images');
      }
    } else if (_hadPulling) {
      // Последняя загрузка закончилась — в списке появился новый образ.
      const wasCancelled = _pullCancelledSeen;
      _hadPulling = false;
      _pullAutoShown = false;
      _pullCancelledSeen = false;
      loadImages().catch(() => {});
      // После отмены остаёмся на «Образах»: контейнер не запустился, задача
      // вот-вот завершится «Отменено» — переносить некуда и незачем.
      if (!wasCancelled) afterPullsFinished().catch(() => {});
    }
  } catch { /* повторим на следующем тике */ }
}

function renderImages(images) {
  const body = document.getElementById('docker-images-body');
  if (!body) return;
  const filtered = images.filter(img => {
    const full = `${img.repository}:${img.tag}`.toLowerCase();
    return !dockerImageSearch || full.includes(dockerImageSearch.trim().toLowerCase());
  });
  const pullingRows = dockerPulling
    .filter(p => !dockerImageSearch
      || p.image.toLowerCase().includes(dockerImageSearch.trim().toLowerCase()))
    .map(p => {
      const parts = String(p.image || '').split('/');
      const name = parts[parts.length - 1] || p.image;
      const text = p.cancelled
        ? 'отменяется…'
        : `${p.percent}%${p.detail ? ' · ' + p.detail : ''}`;
      return `<tr class="img-pulling-row${p.cancelled ? ' img-pulling-cancelled' : ''}" data-pull-row="${esc(p.image)}">
      <td><b>${esc(name)}</b></td>
      <td colspan="4"><div class="img-pulling-cell">
        <div class="img-pull-track"><div class="img-pull-fill" style="width:${p.percent}%"></div></div>
        <span class="img-pull-text">${esc(text)}</span>
        <button type="button" class="img-pull-cancel" data-pull-cancel="${esc(p.image)}" title="Отменить загрузку"${p.cancelled ? ' disabled' : ''}>✕</button>
      </div></td>
    </tr>`;
    }).join('');
  const toolbar = `<div class="svc-card-head svc-card-head-one-line">
    <h2>Образы <span class="hint">(${images.length})</span></h2>
    <div class="svc-card-actions">
      <input type="search" id="docker-image-search" placeholder="🔍 Поиск образа…" value="${esc(dockerImageSearch)}"/>
      <button type="button" id="docker-pull-open">⬇️ Загрузить образ</button>
    </div>
  </div>`;
  const rows = filtered.map(img => {
    const fullName = `${img.repository}:${img.tag}`;
    const parts = String(img.repository || '').split('/');
    const name = parts[parts.length - 1] || img.repository || '—';
    return `<tr>
      <td><b>${esc(name)}</b></td>
      <td class="mono">${esc(img.tag || '—')}</td>
      <td>${esc(img.size || '—')}</td>
      <td>${esc(img.created || '—')}</td>
      <td><button type="button" class="danger" data-img-rm="${esc(fullName)}">Удалить</button></td>
    </tr>`;
  }).join('');
  const content = (filtered.length || pullingRows)
    ? `<div class="svc-table-wrap docker-images-table-wrap"><table class="svc-table docker-images-table"><thead><tr><th>Имя</th><th>Версия</th><th>Размер</th><th>Дата загрузки</th><th>Действие</th></tr></thead><tbody>${pullingRows}${rows}</tbody></table></div>`
    : `<div class="empty svc-empty">${images.length ? 'Ничего не найдено' : 'Образов нет'}</div>`;
  body.innerHTML = `<div class="info-block docker-images-card">${toolbar}${content}</div>`;
  body.querySelector('#docker-pull-open')?.addEventListener('click', openPullModal);
  body.querySelector('#docker-prune-images')?.addEventListener('click', pruneImages);
  body.querySelector('#docker-image-search')?.addEventListener('input', (e) => {
    dockerImageSearch = e.target.value;
    renderImages(images);
    const input = document.getElementById('docker-image-search');
    if (input) { input.focus(); input.setSelectionRange(dockerImageSearch.length, dockerImageSearch.length); }
  });
  body.querySelectorAll('[data-img-rm]').forEach(b => b.onclick = () => removeImage(b.dataset.imgRm));
  body.querySelectorAll('[data-pull-cancel]').forEach(b => b.onclick = () => cancelPull(b.dataset.pullCancel));
}

// Кнопка «✕» на строке загрузки: убить процесс загрузки на сервере. Задача,
// которая качала (docker run / compose up / просто pull), завершится
// «Отменено пользователем» — запуск контейнера/стека прерывается.
async function cancelPull(image) {
  if (!(await dockerConfirm('Отмена загрузки',
    `Отменить загрузку образа «${image}»?` +
    ' Если образ качался для запуска контейнера или compose-стека — запуск будет прерван.',
    'Отменить загрузку'))) return;
  try {
    const r = await j(`${srvBase(dockerServerId)}/images/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image }),
    });
    if (r.cancelled) toast('Загрузка отменяется', true);
    else toast('Загрузка уже завершилась', false);
  } catch (e) {
    toast(e.message, false);
  }
}

async function removeImage(image) {
  if (!(await dockerConfirm('Удаление образа', `Удалить образ «${image}»?`, 'Удалить'))) return;
  await enqueueAction(dockerServerId, 'image_rm', { image }, 'Удаление образа в очереди');
}

async function pruneImages() {
  if (!(await dockerConfirm('Очистка образов',
    'Удалить все образы, не используемые контейнерами?\n\nЭто удалит образы с тегами, если к ним нет привязанных контейнеров.', 'Очистить'))) return;
  await enqueueAction(dockerServerId, 'image_prune', {}, 'Очистка в очереди');
}

function openPullModal() {
  const input = document.getElementById('docker-pull-image');
  const warn = document.getElementById('docker-pull-warn');
  if (input) input.value = '';
  if (warn) warn.textContent = '';
  const modal = document.getElementById('docker-pull-modal');
  modal.classList.add('open');
}

async function confirmPull() {
  const warn = document.getElementById('docker-pull-warn');
  const input = document.getElementById('docker-pull-image');
  const image = (input?.value || '').trim();
  if (!image) {
    warn.textContent = 'Укажите образ.';
    return;
  }
  document.getElementById('docker-pull-modal').classList.remove('open');
  await enqueueAction(dockerServerId, 'image_pull', { image }, 'Загрузка образа в очереди');
}

// ---------------- вкладка «Compose» (Phase 5) ----------------
// Стек живёт в локальной библиотеке Bot4VPS и разворачивается на сервер при
// запуске. Вся логика (валидация, деплой, статусы) — на бэке; здесь только
// запросы к API и рендер.

const stackBase = id => `${srvBase(id)}/stacks`;

// Последний ответ /stacks (docs/compose-model.md §4-5): rows — единая таблица
// проектов, ignored — игнор-ключи. Нужен меню и диалогам (lib_match, key).
let lastStacks = { rows: [], ignored: [] };
// Поиск по имени/сервисам (фильтра источников больше нет — модель не делит
// проекты на «наши/внешние»).
let dockerStackSearch = '';
let dockerStackRows = [];        // нормализованные строки для рендера/меню
let dockerServerAccessible = false;

async function loadStacks() {
  const body = document.getElementById('docker-compose-body');
  if (!body || !dockerServerId) return;
  try {
    const d = await j(stackBase(dockerServerId));
    lastStacks = d || { rows: [], ignored: [] };
    renderStacks(d);
  } catch (e) {
    body.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function renderStacks(data) {
  const body = document.getElementById('docker-compose-body');
  if (!body) return;
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const serverAccessible = !!data.server_accessible;
  dockerServerAccessible = serverAccessible;

  // Нормализация строк таблицы под нужды рендера/меню:
  //   status: running | stopped | absent | conflict (§4)
  //   libMatch: true|false|null — сверка конфиг-наборов (§3)
  dockerStackRows = rows.map(r => {
    const lib = r.library || {};
    const srv = r.server || {};
    return {
      name: r.name,
      status: r.status,
      source: r.source,                       // server | library
      services: (lib.services && lib.services.length ? lib.services : srv.services) || [],
      hasEnv: !!lib.has_env,
      extraFiles: Array.isArray(lib.extra_files) ? lib.extra_files : [],
      running: Number(r.containers_running) || 0,
      total: Number(r.containers_total) || 0,
      deployed: r.source === 'server',        // развёртывание есть на сервере
      workingDir: srv.working_dir || '',
      configFiles: srv.config_files || [],
      libMatch: r.lib_match,
      inLibrary: !!r.in_library,
      nameConflict: !!r.name_conflict,
      conflictCount: Number(r.conflict_count) || 0,
      key: srv.key || '',
    };
  });
  dockerStackRows.sort((a, b) =>
    String(a.name).localeCompare(String(b.name)) || String(a.workingDir).localeCompare(String(b.workingDir)));

  // Каркас вкладки строим один раз — иначе поиск теряет фокус на каждый ввод.
  let card = body.querySelector('.docker-ct-card');
  if (!card) {
    body.innerHTML = `
      <div class="info-block docker-ct-card docker-stack-card">
        <div class="svc-card-head svc-card-head-one-line">
          <h2>Compose проекты <span class="hint" data-stack-count>(${rows.length})</span></h2>
          <div class="svc-card-actions">
            <input type="search" id="docker-stack-search" placeholder="🔍 Поиск проекта…" autocomplete="off"/>
            <button type="button" class="secondary" id="docker-stack-ignored-btn" title="Игнорируемые проекты">🚫 Игнорируемые</button>
            <button type="button" id="docker-stack-new">➕ Новый проект</button>
          </div>
        </div>
        <div class="err-hint hidden" id="docker-stack-srv-warn" style="margin:0 0 .5rem"></div>
        <div class="docker-ct-scroll" id="docker-stack-list"></div>
      </div>`;
    card = body.querySelector('.docker-stack-card');
    const search = body.querySelector('#docker-stack-search');
    if (search) {
      search.value = dockerStackSearch;
      search.addEventListener('input', (e) => {
        dockerStackSearch = e.target.value;
        fillStackList();
      });
    }
    body.querySelector('#docker-stack-ignored-btn')?.addEventListener('click', openIgnoredModal);
    body.querySelector('#docker-stack-new')?.addEventListener('click', openStackNewModal);
  } else {
    // Синхронизировать контролы без пересоздания (live-poll) — фокус не сбиваем.
    // Обработчики назначены один раз при создании каркаса выше.
    const search = body.querySelector('#docker-stack-search');
    if (search && document.activeElement !== search) search.value = dockerStackSearch;
    const countEl = body.querySelector('[data-stack-count]');
    if (countEl) countEl.textContent = `(${rows.length})`;
  }

  // Плашка «Сервер недоступен» — общая для обеих веток (обновляется на
  // каждом рендере, live-poll).
  const warnEl = body.querySelector('#docker-stack-srv-warn');
  if (warnEl) {
    warnEl.textContent = serverAccessible ? '' : '⚠️ Сервер недоступен — показаны только проекты библиотеки.';
    warnEl.classList.toggle('hidden', serverAccessible);
  }

  fillStackList();
}

// Колонка «Локальная копия» (§5): ✅ совпадает / ⚠ расходится / — нет копии.
// Клик по ⚠ открывает диалог расхождения (§6).
function stackCopyCell(r) {
  if (!r.inLibrary) {
    return '<span class="stack-src">—</span><span class="stack-src-sub">нет копии</span>';
  }
  if (r.status === 'conflict') {
    return '<span class="stack-src">📚</span><span class="stack-src-sub">конфликт имён</span>';
  }
  if (r.libMatch === true) {
    return '<span class="stack-src">✅</span><span class="stack-src-sub">совпадает</span>';
  }
  if (r.libMatch === false) {
    return `<button type="button" class="stack-copy-warn" data-copy-warn="${esc(r.name)}" title="Локальная копия расходится с сервером — нажмите, чтобы выбрать действие">⚠️ расходится</button>`;
  }
  if (r.status === 'absent') {
    return '<span class="stack-src">📚</span><span class="stack-src-sub">нет на сервере</span>';
  }
  return '<span class="stack-src">📚</span><span class="stack-src-sub">не сравнено</span>';
}

// Главная кнопка строки (§4): всегда source=server, кроме «Отсутствует» →
// установка из библиотеки. Конфликт имён — установка заблокирована.
function stackMainBtn(r) {
  const k = r.key ? ` data-key="${esc(r.key)}"` : '';
  if (r.status === 'absent') {
    return `<button type="button" class="stack-main" data-stack-act="up" data-stack-name="${esc(r.name)}" data-source="library"${k}>▶ Установить</button>`;
  }
  if (r.status === 'conflict') {
    return '<button type="button" class="secondary stack-main" disabled title="Имя занято несколькими развёртываниями — разберитесь на сервере или проигнорируйте лишние">⚠ Конфликт имён</button>';
  }
  if (r.status === 'running') {
    return `<button type="button" class="secondary stack-main" data-stack-act="restart" data-stack-name="${esc(r.name)}" data-source="server"${k}>🔄 Перезапустить</button>`;
  }
  return `<button type="button" class="stack-main" data-stack-act="up" data-stack-name="${esc(r.name)}" data-source="server"${k}>▶ Запустить</button>`;
}

function fillStackList() {
  const listEl = document.getElementById('docker-stack-list');
  if (!listEl) return;
  const q = dockerStackSearch.trim().toLowerCase();
  let list = dockerStackRows;
  if (q) {
    list = list.filter(r =>
      String(r.name || '').toLowerCase().includes(q) ||
      (r.services || []).some(s => String(s).toLowerCase().includes(q)));
  }

  const rowsHtml = list.map(r => {
    const name = esc(r.name);
    const badge = r.status === 'running'
      ? '<span class="badge on">🟢 запущен</span>'
      : r.status === 'stopped'
        ? '<span class="badge off">⚪ не запущен</span>'
        : r.status === 'absent'
          ? '<span class="badge unk">⚫ нет на сервере</span>'
          : `<span class="badge ssl-warn">⚠️ конфликт имён${r.conflictCount > 1 ? ` (${r.conflictCount})` : ''}</span>`;
    const services = (r.services && r.services.length)
      ? r.services.map(x => esc(x)).join(', ') : '—';
    const ct = r.deployed ? `${r.running} / ${r.total}` : '—';
    const dir = r.workingDir
      ? `<span class="mono trunc" style="display:block;font-size:.85em;opacity:.75" title="${esc(r.workingDir)}">${esc(r.workingDir)}</span>`
      : '';
    return `<tr>
      <td class="col-name"><span class="stack-name"><b>${name}</b></span>
        ${dir}
        <span class="stack-services mono trunc" title="${esc(services)}">${services}</span></td>
      <td class="col-src">${stackCopyCell(r)}</td>
      <td class="col-status"><span class="stack-status">${badge}</span></td>
      <td class="col-ct"><span class="mono">${esc(String(ct))}</span></td>
      <td class="col-act">
        <div class="docker-ct-actions">
          ${stackMainBtn(r)}
          <button type="button" class="secondary docker-ct-more" data-smenu="${name}" title="Действия">⋯</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  if (!list.length) {
    listEl.innerHTML = `<div class="empty svc-empty">Проектов не найдено<br><span class="hint">Создайте новый или измените поиск.</span></div>`;
  } else {
    listEl.innerHTML = `<table class="svc-table docker-ct-table docker-stack-table">
      <thead><tr>
        <th class="col-name">Проект</th>
        <th class="col-src">Локальная копия</th>
        <th class="col-status">Статус</th>
        <th class="col-ct">Контейнеры</th>
        <th class="col-act">Действия</th>
      </tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;
  }

  // Главная кнопка (up/restart) — напрямую через stackAction.
  listEl.querySelectorAll('.stack-main[data-stack-act]').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      stackAction({
        name: btn.dataset.stackName,
        act: btn.dataset.stackAct,
        source: btn.dataset.source || 'library',
        key: btn.dataset.key || null,
      });
    };
  });
  // Клик по «⚠️ расходится» — диалог расхождения (§6).
  listEl.querySelectorAll('[data-copy-warn]').forEach(btn => {
    btn.onclick = async (e) => {
      e.preventDefault(); e.stopPropagation();
      const name = btn.dataset.copyWarn;
      const res = await openDivergeDialog(name);
      if (res === 'import') {
        const r = dockerStackRows.find(x => x.name === name && x.deployed);
        await importStackFromServer(name, r ? r.key : null);
      }
      // true (применить библиотеку прямо из ячейки) — не делаем: у ячейки
      // нет key контекста меню; применение доступно из меню «⋯».
    };
  });
  // Меню «⋯» — контекстный список действий.
  listEl.querySelectorAll('[data-smenu]').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      openStackMenu(btn, btn.dataset.smenu);
    };
  });
}

// Выпадающее меню действий compose-проекта (§6). Переиспользует попап
// #docker-ct-pop (тот же виджет, что у контейнеров).
function openStackMenu(anchor, name) {
  const pop = document.getElementById('docker-ct-pop');
  if (!pop) return;
  // Конфликт имён даёт библиотечную заглушку + серверные строки; «⋯» всегда
  // берёт СЕРВЕРНУЮ строку этого имени (у неё есть key).
  const r = dockerStackRows.find(x => x.name === name && x.deployed)
        || dockerStackRows.find(x => x.name === name);
  if (!r) return;
  const key = r.key || null;
  const items = [];
  if (r.deployed) {
    if (r.status === 'running') items.push(['down', '⏹ Остановить']);
    items.push(['logs', '📄 Логи']);
    items.push(['ignore', '🚫 Игнорировать проект']);
    if (r.inLibrary && r.libMatch === false) {
      items.push(['replace-lib', '⬆️ Заменить серверную библиотечной']);
    }
  }
  if (!r.inLibrary || r.libMatch === false) {
    items.push(['import', r.inLibrary ? '⬇️ Обновить копию с сервера' : '⬇️ Импортировать в библиотеку']);
  }
  items.push(['edit', '✏️ Изменить']);
  const danger = [];
  if (r.deployed) danger.push(['delete-remote', '🗑 Удалить с сервера']);
  if (r.inLibrary) danger.push(['delete-lib', '🗑 Удалить локальную копию']);

  const itemBtn = (act, label, cls = '') =>
    `<button type="button" class="${cls}" data-sact="${act}">${label}</button>`;
  pop.innerHTML = items.map(([a, l]) => itemBtn(a, l)).join('')
    + (danger.length ? '<hr/>' + danger.map(([a, l]) => itemBtn(a, l, 'danger docker-ct-danger')).join('') : '');
  pop.classList.remove('hidden');

  const rect = anchor.getBoundingClientRect();
  const pw = pop.offsetWidth || 220;
  let left = rect.right - pw;
  let top = rect.bottom + 4;
  left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
  if (top + pop.offsetHeight > window.innerHeight - 8) top = Math.max(8, rect.top - pop.offsetHeight - 4);
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  pop.style.position = 'fixed';

  pop.querySelectorAll('[data-sact]').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation();
      pop.classList.add('hidden');
      await stackAction({ name, act: b.dataset.sact, key });
    };
  });
  const onDoc = (ev) => {
    if (!pop.contains(ev.target) && ev.target !== anchor) {
      pop.classList.add('hidden');
      document.removeEventListener('click', onDoc, true);
    }
  };
  setTimeout(() => document.addEventListener('click', onDoc, true), 0);
}

// Единая точка действий (§6). source вычисляется по статусу строки (§4),
// никакого выбора источника на фронте больше нет.
async function stackAction({ name, act, key }) {
  const r = dockerStackRows.find(x => x.name === name);
  if (!r && act !== 'import') return;
  const source = r && r.status === 'absent' ? 'library' : 'server';
  if (act === 'edit') return openStackEditModal(name);
  if (act === 'logs') return openStackLogs(name, source, key);
  if (act === 'delete-lib') return deleteStackFromLibrary(name);
  if (act === 'delete-remote') return deleteStackFromServer(name, key);
  if (act === 'import') return importStackFromServer(name, key);
  if (act === 'ignore') return ignoreStack(name, key);
  if (act === 'replace-lib') {
    // ⬆️ Заменить серверную библиотечной: перезапись через диалог §6.
    const res = await openDivergeDialog(name, { apply: true });
    if (!res) return;
    if (res === 'import') return importStackFromServer(name, key);
    await enqueueAction(dockerServerId, 'compose_restart',
      { stack: name, source: 'library', key }, 'Применение библиотеки в очереди');
    return;
  }
  if (act === 'down') {
    if (!(await dockerConfirm('Остановка проекта',
      `Остановить проект «${name}»?\n\nКонтейнеры будут удалены, ` +
      `тома с данными сохранятся.`,
      'Остановить'))) return;
  }
  const labels = { up: 'Запуск', down: 'Остановка', restart: 'Перезапуск' };
  await enqueueAction(dockerServerId, `compose_${act}`, { stack: name, source, key },
    `${labels[act] || act} проекта в очереди`);
}

async function deleteStackFromLibrary(name) {
  if (!(await dockerConfirm('Удаление локальной копии',
    `Удалить локальную копию проекта «${name}» из библиотеки Bot4VPS?\n\n` +
    `Запущенные контейнеры на сервере НЕ будут остановлены. ` +
    `Чтобы убрать проект и с сервера, используйте «🗑 Удалить с сервера».`,
    'Удалить копию'))) return;
  try {
    await j(`${stackBase(dockerServerId)}/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast('Локальная копия удалена', true);
    await loadStacks();
  } catch (e) { toast(e.message, false); }
}

async function deleteStackFromServer(name, key) {
  if (!(await dockerConfirm('Удаление с сервера',
    `Удалить проект «${name}» с сервера?\n\n` +
    `Сначала будет выполнена остановка (тома сохранятся), и только при её ` +
    `успехе каталог проекта удалится. Библиотека Bot4VPS не изменится.`,
    'Удалить с сервера'))) return;
  await enqueueAction(dockerServerId, 'compose_delete_remote',
    { stack: name, source: 'server', key }, 'Удаление с сервера в очереди');
}

async function importStackFromServer(name, key) {
  // Проект в библиотеке уже есть → предупреждаем о перезаписи локальной копии.
  const r = dockerStackRows.find(x => x.name === name && x.deployed)
        || dockerStackRows.find(x => x.name === name);
  const inLib = !!(r && r.inLibrary);
  const diff = r && r.libMatch === false
    ? 'Серверная версия отличается от локальной.'
    : 'Сравнить версии не удалось.';
  const text = inLib
    ? `Проект «${name}» уже есть в библиотеке Bot4VPS.\n${diff}\n\n` +
      `Локальная копия будет заменена версией с сервера.`
    : `Импортировать проект «${name}» в библиотеку Bot4VPS?\n\n` +
      `Будет перенесён конфиг-набор проекта: Compose-файл, .env и другие файлы.`;
  if (!(await dockerConfirm(
    inLib ? 'Перезапись в библиотеке' : 'Импорт в библиотеку',
    text, inLib ? 'Да, импортировать' : 'Импортировать'))) return;
  await enqueueAction(dockerServerId, 'compose_import',
    { stack: name, key, overwrite: inLib }, 'Импорт в очереди');
}

// Диалог расхождения (§6): локальная копия ≠ сервер. Три исхода:
// true — применить библиотеку (перезапись сервера), false — отменить,
// 'import' — сначала импортировать с сервера.
function openDivergeDialog(name, opts = {}) {
  return new Promise(resolve => {
    const dlg = document.getElementById('docker-dialog');
    dialogResolve = resolve;
    document.getElementById('docker-dialog-title').textContent =
      opts.apply ? 'Применить локальную копию?' : 'Локальная копия расходится';
    const msg = document.getElementById('docker-dialog-msg');
    msg.textContent =
      `На сервере есть изменения, которых нет в локальной копии «${name}».\n\n` +
      (opts.apply
        ? 'Применить локальную копию? (правки на сервере будут заменены)'
        : 'Что сделать?');
    msg.classList.remove('hidden');
    const okBtn = document.getElementById('docker-dialog-ok');
    const altBtn = document.getElementById('docker-dialog-alt');
    okBtn.textContent = 'Применить библиотеку';
    altBtn.textContent = 'Сначала импортировать с сервера';
    altBtn.classList.remove('hidden');
    dlg.classList.add('open');
  });
}

async function ignoreStack(name, key) {
  if (!(await dockerConfirm('Игнорирование проекта',
    `Скрыть проект «${name}» из списка Compose-проектов и списка контейнеров?\n\n` +
    `Проект продолжит работать. Его контейнеры не будут учитываться в статистике Docker.`,
    'Игнорировать'))) return;
  try {
    await j(`${srvBase(dockerServerId)}/ignored-stacks`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stack: name, key }),
    });
    toast('Проект скрыт (игнорируется)', true);
    await loadStacks();
    await loadServerDetail(dockerServerId);
  } catch (e) { toast(e.message, false); }
}

// Модалка «Игнорируемые» (§11): список скрытых развёртываний с сервера.
async function openIgnoredModal() {
  if (!dockerServerId) return;
  const listEl = document.getElementById('docker-ignored-list');
  document.getElementById('docker-ignored-modal').classList.add('open');
  listEl.innerHTML = '<div class="empty">Загрузка…</div>';
  try {
    const r = await j(`${srvBase(dockerServerId)}/ignored-stacks`);
    const items = r.items || [];
    if (!items.length) {
      listEl.innerHTML = '<div class="empty">Игнорируемых проектов нет</div>';
      return;
    }
    listEl.innerHTML = items.map(it => `<div class="row" style="gap:.4rem;align-items:center">
      <span style="flex:1"><b>${esc(it.name)}</b>
        <span class="mono" style="display:block;font-size:.85em;opacity:.75">${esc(it.working_dir || '')}</span></span>
      ${it.status === 'running'
        ? '<span class="badge on">🟢</span>'
        : '<span class="badge off">⚪</span>'}
      <button type="button" class="secondary" data-unignore="${esc(it.ignore_key)}">Перестать игнорировать</button>
    </div>`).join('');
    listEl.querySelectorAll('[data-unignore]').forEach(b => {
      b.onclick = async () => {
        try {
          const qs = new URLSearchParams({ ignore_key: b.dataset.unignore });
          await j(`${srvBase(dockerServerId)}/ignored-stacks?${qs}`, { method: 'DELETE' });
          toast('Проект снова виден', true);
          await openIgnoredModal();
          await loadStacks();
        } catch (e) { toast(e.message, false); }
      };
    });
  } catch (e) {
    listEl.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

// ---------------- модалка создания стека ----------------

function openStackNewModal() {
  document.getElementById('docker-stack-name').value = '';
  document.getElementById('docker-stack-new-yaml').value = '';
  document.getElementById('docker-stack-new-env').value = '';
  document.getElementById('docker-stack-new-warn').textContent = '';
  document.getElementById('docker-stack-file-name').textContent = '';
  const fileInput = document.getElementById('docker-stack-file-input');
  if (fileInput) fileInput.value = '';
  const zipInput = document.getElementById('docker-stack-zip-input');
  if (zipInput) zipInput.value = '';
  pendingZip = null;
  document.getElementById('docker-stack-new-modal').classList.add('open');
}

// Имя проекта, выведенное из имени файла (только если поле пустое).
function suggestStackName(fileName, stripExt) {
  const nameInput = document.getElementById('docker-stack-name');
  if (!nameInput || nameInput.value.trim()) return;
  const base = fileName.replace(stripExt, '')
    .toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  if (base && base !== 'docker-compose' && base !== 'compose') nameInput.value = base;
}

function readStackFile(file) {
  if (!file) return;
  const nameEl = document.getElementById('docker-stack-file-name');
  const warn = document.getElementById('docker-stack-new-warn');
  const reader = new FileReader();
  reader.onload = () => {
    document.getElementById('docker-stack-new-yaml').value = String(reader.result || '');
    if (nameEl) nameEl.textContent = file.name;
    warn.textContent = '';
    pendingZip = null;
    suggestStackName(file.name, /\.(ya?ml)$/i);
  };
  reader.onerror = () => { warn.textContent = 'Не удалось прочитать файл.'; };
  reader.readAsText(file);
}

// ZIP не разбираем на фронте — отправляем как есть, распаковка и защита от
// path traversal живут в Core (§1.2, §5).
let pendingZip = null;

function pickStackZip(file) {
  if (!file) return;
  pendingZip = file;
  const nameEl = document.getElementById('docker-stack-file-name');
  if (nameEl) nameEl.textContent = `${file.name} (ZIP-проект)`;
  document.getElementById('docker-stack-new-warn').textContent = '';
  suggestStackName(file.name, /\.zip$/i);
}

async function saveNewStack() {
  const warn = document.getElementById('docker-stack-new-warn');
  const name = document.getElementById('docker-stack-name').value.trim();
  if (!name) { warn.textContent = 'Укажите имя проекта.'; return; }

  const base = `${stackBase(dockerServerId)}/${encodeURIComponent(name)}`;
  try {
    if (pendingZip) {
      const fd = new FormData();
      fd.append('file', pendingZip);
      await j(`${base}/zip`, { method: 'POST', body: fd });
    } else {
      const content = document.getElementById('docker-stack-new-yaml').value;
      if (!content.trim()) {
        warn.textContent = 'Вставьте Compose-файл, загрузите YAML или ZIP-проект.';
        return;
      }
      await j(`${base}/file`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      const env = document.getElementById('docker-stack-new-env').value;
      if (env.trim()) {
        await j(`${base}/files`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: '.env', content: env }),
        });
      }
    }
    toast('Проект сохранён', true);
    document.getElementById('docker-stack-new-modal').classList.remove('open');
    pendingZip = null;
    await loadStacks();
  } catch (e) {
    // Ошибка валидации с бэка — показываем в модалке, не закрывая её.
    warn.textContent = e.message;
  }
}

// ---------------- модалка файлов проекта (§9) ----------------
// Цель = сервер (remote), кроме статуса «Отсутствует» — тогда библиотечная
// копия (правим то, что будет установлено). Изображения — превью <img>.

let stackFilesCtx = null;    // {name, key, remote, status}
let editingFilePath = null;  // редактируемый файл

// Разворачиваемый контекст по имени: серверная строка (remote) или absent.
function stackFilesTarget(name) {
  const r = dockerStackRows.find(x => x.name === name && x.deployed)
        || dockerStackRows.find(x => x.name === name);
  if (!r) return { name, key: null, remote: false, status: 'absent' };
  return {
    name,
    key: r.key || null,
    remote: r.status !== 'absent',
    status: r.status,
  };
}

export async function openDockerProjectFile(name, path) {
  stackFilesCtx = { name, key: null, remote: false, status: 'absent' };
  editingFilePath = null;
  document.getElementById('docker-stack-files-title').textContent =
    '📂 ' + name + ' (локальная копия)';
  document.getElementById('docker-stack-files-warn').textContent = '';
  document.getElementById('docker-stack-files-editor').classList.add('hidden');
  document.getElementById('docker-stack-files-list').innerHTML = '';
  document.getElementById('docker-stack-files-modal').classList.add('open');
  await openFileEditor(path);
}

async function openStackFilesModal(name) {
  stackFilesCtx = stackFilesTarget(name);
  editingFilePath = null;
  const where = stackFilesCtx.remote ? ' (сервер)' : ' (локальная копия)';
  document.getElementById('docker-stack-files-title').textContent = '📂 ' + name + where;
  document.getElementById('docker-stack-files-warn').textContent = '';
  document.getElementById('docker-stack-files-close')?.classList.remove('hidden');
  document.getElementById('docker-stack-files-editor').classList.add('hidden');
  document.getElementById('docker-stack-files-list').innerHTML = '<div class="empty">Загрузка…</div>';
  document.getElementById('docker-stack-files-modal').classList.add('open');
  await refreshStackFiles();
}

function stackFilesUrl(suffix = '') {
  const qs = new URLSearchParams();
  if (stackFilesCtx.remote) qs.set('remote', '1');
  if (stackFilesCtx.key) qs.set('key', stackFilesCtx.key);
  const q = qs.toString();
  const targetServerId = stackFilesCtx.remote ? dockerServerId : '-';
  return `${stackBase(targetServerId)}/${encodeURIComponent(stackFilesCtx.name)}/files${suffix}${q ? '?' + q : ''}`;
}

const IMAGE_RE = /\.(jpe?g|png|webp|gif)$/i;

async function refreshStackFiles() {
  if (!stackFilesCtx || (stackFilesCtx.remote && !dockerServerId)) return;
  const listEl = document.getElementById('docker-stack-files-list');
  try {
    const r = await j(stackFilesUrl());
    const files = r.files || [];
    if (!files.length) { listEl.innerHTML = '<div class="empty">Файлов нет</div>'; return; }
    listEl.innerHTML = files.map(f => {
      const isImage = IMAGE_RE.test(String(f.path || ''));
      const actionIcon = isImage ? '👁' : '✏️';
      const actionTitle = isImage ? 'Просмотреть' : 'Редактировать';
      return `<div class="row" style="gap:.4rem;align-items:center">
        <span class="mono" style="flex:1">${f.is_compose ? '🧩 ' : '📄 '}${esc(f.path)}</span>
        <span class="hint">${Number(f.size) || 0} Б</span>
        <button type="button" class="secondary" data-file-edit="${esc(f.path)}" title="${actionTitle}" style="padding:.2rem .5rem">${actionIcon}</button>
      </div>`;
    }).join('');
    listEl.querySelectorAll('[data-file-edit]').forEach(b =>
      b.onclick = () => openFileEditor(b.dataset.fileEdit));
  } catch (e) {
    listEl.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

// Открыть файл: изображение → превью <img>, иначе — текстовый редактор.
async function openFileEditor(path) {
  const warn = document.getElementById('docker-stack-files-warn');
  const area = document.getElementById('docker-stack-files-content');
  const editorEl = document.getElementById('docker-stack-files-editor');
  const labelEl = document.getElementById('docker-stack-files-editing');
  warn.textContent = '';
  const qs = new URLSearchParams({ path });
  if (stackFilesCtx.remote) qs.set('remote', '1');
  if (stackFilesCtx.key) qs.set('key', stackFilesCtx.key);
  try {
    const targetServerId = stackFilesCtx.remote ? dockerServerId : '-';
    const r = await j(
      `${stackBase(targetServerId)}/${encodeURIComponent(stackFilesCtx.name)}/files/content?${qs}`);
    if (r.binary) {
      // Превью (§9): только whitelist mime и ≤5 МиБ (больше — бэк сам откажет).
      if (!String(r.mime || '').startsWith('image/')) {
        warn.textContent = 'Бинарный файл — превью недоступно.';
        return;
      }
      editingFilePath = null;
      area.value = '';
      labelEl.textContent = path;
      editorEl.classList.remove('hidden');
      area.classList.add('hidden');
      document.getElementById('docker-stack-files-save')?.classList.add('hidden');
      document.getElementById('docker-stack-files-cancel')?.classList.add('hidden');
      document.getElementById('docker-stack-files-close')?.classList.remove('hidden');
      let img = editorEl.querySelector('img.stack-file-preview');
      if (!img) {
        img = document.createElement('img');
        img.className = 'stack-file-preview';
        img.style.cssText = 'max-width:100%;max-height:50vh;display:block;margin:.4rem auto;border-radius:6px';
        area.insertAdjacentElement('beforebegin', img);
      }
      img.src = `data:${r.mime};base64,${r.b64}`;
      img.classList.remove('hidden');
      return;
    }
    editingFilePath = path;
    area.value = r.text || '';
    labelEl.textContent = path;
    editorEl.classList.remove('hidden');
    area.classList.remove('hidden');
    document.getElementById('docker-stack-files-save')?.classList.remove('hidden');
    document.getElementById('docker-stack-files-cancel')?.classList.remove('hidden');
    document.getElementById('docker-stack-files-close')?.classList.add('hidden');
    editorEl.querySelector('img.stack-file-preview')?.classList.add('hidden');
  } catch (e) {
    warn.textContent = e.message;
  }
}

async function saveProjectFile() {
  if (!editingFilePath) return;
  const warn = document.getElementById('docker-stack-files-warn');
  const content = document.getElementById('docker-stack-files-content').value;
  try {
    await j(stackFilesUrl(), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: editingFilePath, content, key: stackFilesCtx.key || null }),
    });
    toast(stackFilesCtx.remote
      ? 'Сохранено на сервере. Вступит в силу после перезапуска.'
      : 'Файл сохранён в локальной копии.', true);
    document.getElementById('docker-stack-files-editor').classList.add('hidden');
    document.getElementById('docker-stack-files-save')?.classList.remove('hidden');
    document.getElementById('docker-stack-files-close')?.classList.remove('hidden');
    editingFilePath = null;
    await refreshStackFiles();
    if (stackFilesCtx.remote) await loadStacks();
    else window.dispatchEvent(new Event('docker-project-file-saved'));
  } catch (e) {
    warn.textContent = e.message;
  }
}

// ---------------- модалка редактирования стека (§8) ----------------
// Редактируется СЕРВЕРНАЯ версия (файлы на сервере); единственный случай
// библиотечной — статус «Отсутствует» (правим то, что будет установлено).
// После сохранения — «вступит в силу после перезапуска» (кнопка в тосте
// не заводилась: перезапуск — в строке таблицы и в меню).

let stackEditCtx = null;   // {name, key, remote}

function stackEditTarget(name) {
  const r = dockerStackRows.find(x => x.name === name && x.deployed)
        || dockerStackRows.find(x => x.name === name);
  if (!r) return { name, key: null, remote: false };
  return { name, key: r.key || null, remote: r.status !== 'absent' };
}

async function openStackEditModal(name) {
  stackEditCtx = stackEditTarget(name);
  const warn = document.getElementById('docker-stack-edit-warn');
  const area = document.getElementById('docker-stack-edit-yaml');
  const where = stackEditCtx.remote ? ' (сервер)' : ' (локальная копия)';
  document.getElementById('docker-stack-edit-title').textContent = '✏️ ' + name + where;
  warn.textContent = '';
  area.value = 'Загрузка…';
  document.getElementById('docker-stack-edit-modal').classList.add('open');
  try {
    if (stackEditCtx.remote) {
      // Серверная версия: сначала узнаём настоящее имя compose-файла
      // развёртывания (может быть нестандартным), затем читаем его.
      const cfg = await findRemoteComposeName(name, stackEditCtx.key);
      stackEditCtx.composePath = cfg;
      const qs = new URLSearchParams({ path: cfg, remote: '1' });
      if (stackEditCtx.key) qs.set('key', stackEditCtx.key);
      const f = await j(
        `${stackBase(dockerServerId)}/${encodeURIComponent(name)}/files/content?${qs}`);
      const text = (f && f.binary === false && f.text) || '';
      area.value = text;
      if (!text) warn.textContent = 'Не удалось прочитать Compose-файл на сервере.';
    } else {
      const d = await j(`${stackBase(dockerServerId)}/${encodeURIComponent(name)}/file`);
      area.value = d.content || '';
    }
  } catch (e) {
    area.value = '';
    warn.textContent = e.message;
  }
}

// Имя основного compose-файла развёртывания (может быть нестандартным).
async function findRemoteComposeName(name, key) {
  const qs = new URLSearchParams();
  qs.set('remote', '1');
  if (key) qs.set('key', key);
  try {
    const r = await j(`${stackBase(dockerServerId)}/${encodeURIComponent(name)}/files?${qs}`);
    const files = r.files || [];
    const main = files.find(f => f.is_compose);
    if (main) return main.path;
  } catch (_) {}
  return 'docker-compose.yml';
}

async function saveStackEdit() {
  if (!stackEditCtx) return;
  const warn = document.getElementById('docker-stack-edit-warn');
  const content = document.getElementById('docker-stack-edit-yaml').value;
  if (!content.trim()) { warn.textContent = 'Файл не может быть пустым.'; return; }
  try {
    if (stackEditCtx.remote) {
      // Сервер: пишем через файловую ручку по запомненному пути compose-файла.
      const path = stackEditCtx.composePath || 'docker-compose.yml';
      await j(`${stackBase(dockerServerId)}/${encodeURIComponent(stackEditCtx.name)}/files?remote=1`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content, key: stackEditCtx.key || null }),
      });
      toast('Сохранено на сервере. Вступит в силу после перезапуска.', true);
    } else {
      await j(`${stackBase(dockerServerId)}/${encodeURIComponent(stackEditCtx.name)}/file`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      toast('Сохранено в локальной копии.', true);
    }
    document.getElementById('docker-stack-edit-modal').classList.remove('open');
    stackEditCtx = null;
    await loadStacks();
  } catch (e) {
    warn.textContent = e.message;
  }
}

// ---------------- модалка логов стека ----------------

let stackLogsCtx = null;   // {name, source, key}

async function openStackLogs(name, source = 'library', key = null) {
  stackLogsCtx = { name, source, key };
  document.getElementById('docker-stack-logs-title').textContent = '📄 ' + name;
  document.getElementById('docker-stack-logs-body').textContent = 'Загрузка…';
  document.getElementById('docker-stack-logs-modal').classList.add('open');
  await refreshStackLogs();
}

async function refreshStackLogs() {
  if (!stackLogsCtx || !dockerServerId) return;
  const bodyEl = document.getElementById('docker-stack-logs-body');
  const { name, source, key } = stackLogsCtx;
  try {
    const qs = new URLSearchParams({ tail: '200', source: source || 'library' });
    if (key) qs.set('key', key);
    const r = await j(
      `${stackBase(dockerServerId)}/${encodeURIComponent(name)}/logs?${qs}`);
    const text = (r && r.logs) || '';
    bodyEl.innerHTML = text ? text.split('\n').map(ansiToHtml).join('\n') : esc('(логи пусты)');
    bodyEl.scrollTop = bodyEl.scrollHeight;
  } catch (e) {
    bodyEl.textContent = e.message || 'Не удалось получить логи';
  }
}

function formatUptime(sec) {
  if (sec < 60) return sec + 'с';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m < 60) return `${m}м ${s}с`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h < 24) return `${h}ч ${mm}м`;
  const d = Math.floor(h / 24);
  const hh = h % 24;
  return `${d}д ${hh}ч`;
}

// ---------------- действия над контейнером ----------------

async function containerAction(name, act) {
  if (act === 'logs') return openLogs(name);
  const id = dockerServerId;
  const labels = { start: 'Старт', stop: 'Стоп', restart: 'Перезапуск', rm: 'Удаление' };
  if (act === 'rm') {
    if (!(await dockerConfirm('Удаление контейнера',
      `Удалить контейнер «${name}»? Он будет остановлен и удалён.`, 'Удалить'))) return;
  }
  await enqueueAction(id, `container_${act}`, { name }, `${labels[act] || act}: в очереди`);
}

// ---------------- модалка запуска контейнера ----------------

let runModalPorts = [];
let runModalEnv = [];

function openRunModal() {
  runModalPorts = [];
  runModalEnv = [];
  document.getElementById('docker-run-image').value = '';
  document.getElementById('docker-run-name').value = '';
  document.getElementById('docker-run-port-input').value = '';
  document.getElementById('docker-run-env-input').value = '';
  document.getElementById('docker-run-restart').value = 'unless-stopped';
  document.getElementById('docker-run-warn').textContent = '';
  document.getElementById('docker-run-ports-list').style.display = 'none';
  document.getElementById('docker-run-env-list').style.display = 'none';
  // Скрыть кнопки "Добавить" до первого добавления
  const portBtn = document.getElementById('docker-run-port-add');
  const envBtn = document.getElementById('docker-run-env-add');
  if (portBtn) portBtn.style.display = 'none';
  if (envBtn) envBtn.style.display = 'none';
  document.getElementById('docker-run-modal').classList.add('open');
}

function renderRunModalList(container, items, removeCallback) {
  const el = document.getElementById(container);
  if (!items.length) {
    el.style.display = 'none';
    return;
  }
  el.style.display = 'block';
  el.innerHTML = items.map((item, idx) =>
    `<div class="row" style="gap:.4rem;margin-top:.2rem">
      <span style="flex:1;font-family:monospace">${esc(item)}</span>
      <button type="button" class="secondary" data-idx="${idx}" style="padding:.2rem .5rem">✕</button>
    </div>`
  ).join('');
  el.querySelectorAll('[data-idx]').forEach(b => {
    b.onclick = () => {
      removeCallback(+b.dataset.idx);
      const isPort = container === 'docker-run-ports-list';
      renderRunModalList(container, isPort ? runModalPorts : runModalEnv, removeCallback);
      // Скрыть кнопку "Добавить" если список опустел
      if (isPort && !runModalPorts.length) {
        document.getElementById('docker-run-port-add').style.display = 'none';
      }
      if (!isPort && !runModalEnv.length) {
        document.getElementById('docker-run-env-add').style.display = 'none';
      }
    };
  });
}

function addRunModalPort() {
  const input = document.getElementById('docker-run-port-input');
  const val = input.value.trim();
  const warn = document.getElementById('docker-run-warn');
  if (!val) return;
  if (!portOk(val)) { warn.textContent = HINT_PORT; return; }
  warn.textContent = '';
  runModalPorts.push(val);
  input.value = '';
  renderRunModalList('docker-run-ports-list', runModalPorts, idx => { runModalPorts.splice(idx, 1); });
  // Показать кнопку "Добавить" после первого добавления
  document.getElementById('docker-run-port-add').style.display = 'inline-block';
}

function addRunModalEnv() {
  const input = document.getElementById('docker-run-env-input');
  const val = input.value.trim();
  const warn = document.getElementById('docker-run-warn');
  if (!val) return;
  if (!RE_ENV.test(val)) { warn.textContent = HINT_ENV; return; }
  warn.textContent = '';
  runModalEnv.push(val);
  input.value = '';
  renderRunModalList('docker-run-env-list', runModalEnv, idx => { runModalEnv.splice(idx, 1); });
  // Показать кнопку "Добавить" после первого добавления
  document.getElementById('docker-run-env-add').style.display = 'inline-block';
}

async function confirmRun() {
  const warn = document.getElementById('docker-run-warn');
  const image = document.getElementById('docker-run-image').value.trim();
  const name = document.getElementById('docker-run-name').value.trim();
  const restart = document.getElementById('docker-run-restart').value;
  if (!image) { warn.textContent = 'Укажите образ.'; return; }
  if (!name) { warn.textContent = 'Укажите имя контейнера.'; return; }

  // Введённое, но не добавленное кнопкой, тоже учитываем — те же правила.
  const portInput = document.getElementById('docker-run-port-input').value.trim();
  if (portInput) {
    if (!portOk(portInput)) { warn.textContent = HINT_PORT; return; }
    runModalPorts.push(portInput);
  }

  const envInput = document.getElementById('docker-run-env-input').value.trim();
  if (envInput) {
    if (!RE_ENV.test(envInput)) { warn.textContent = HINT_ENV; return; }
    runModalEnv.push(envInput);
  }

  const params = { image, name, restart };
  if (runModalPorts.length) params.ports = runModalPorts;
  if (runModalEnv.length) params.env = runModalEnv;
  document.getElementById('docker-run-modal').classList.remove('open');
  await enqueueAction(dockerServerId, 'container_run', params, 'Запуск контейнера в очереди');
}

// ---------------- модалка логов ----------------

async function openLogs(name) {
  logsCtx = { name };
  document.getElementById('docker-logs-title').textContent = '📄 ' + name;
  document.getElementById('docker-logs-body').textContent = 'Загрузка…';
  document.getElementById('docker-logs-modal').classList.add('open');
  await refreshLogs();
}

async function refreshLogs() {
  if (!logsCtx || !dockerServerId) return;
  const bodyEl = document.getElementById('docker-logs-body');
  try {
    const r = await j(`${srvBase(dockerServerId)}/logs/${encodeURIComponent(logsCtx.name)}?tail=200`);
    const text = (r && r.logs) || '';
    bodyEl.innerHTML = text ? text.split('\n').map(ansiToHtml).join('\n') : esc('(логи пусты)');
    bodyEl.scrollTop = bodyEl.scrollHeight;
  } catch (e) {
    bodyEl.textContent = e.message || 'Не удалось получить логи';
  }
}

// ---------------- тяжёлые действия (через очередь → polling /api/tasks/{id}) ----------------

async function enqueueAction(id, action, params, msg, onTask) {
  // Запуск стека/контейнера после докачки образов возвращает на «Контейнеры»
  // (просто набор образов через image_pull — остаёмся на «Образах»).
  if (id === dockerServerId
      && (action === 'compose_up' || action === 'compose_restart'
          || action === 'container_run')) {
    _pullContainerArmed = action;
  }
  try {
    const r = await j(`${srvBase(id)}/enqueue/${encodeURIComponent(action)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params }),
    });
    if (onTask && r.task) { onTask(r.task); return; }
    toast(msg || 'В очереди', true);
    if (r.task) watchTask(r.task.id, id, action);
  } catch (e) { toast(e.message, false); }
}

// ---------------- live-вывод задачи ----------------

// На экране сервера лог показываем в его блоке; из списка — тихо
// (как в WG): без блока вывода, по завершении тост и обновление таблицы.
function watchTask(taskId, serverId, action) {
  const onDetailPage = () =>
    document.getElementById('page-docker-server')?.classList.contains('on');
  const tick = async () => {
    try {
      const t = await j('/api/tasks/' + encodeURIComponent(taskId));
      if (t.is_done) {
        clearInterval(timers[taskId]); delete timers[taskId];
        // Удаление сервиса уводит со страницы: откуда пришли — туда и вернём
        // (карточка сервера / список Docker). Как у WG.
        if (action === 'remove') {
          if (t.success) {
            await leaveUninstalledPage(serverId);
            toast('Docker удалён', true);
          } else {
            toast(t.error || 'Удаление Docker завершилось с ошибкой', false);
            // При ошибке остаёмся на странице — обновляем состояние.
            if (onDetailPage() && serverId) await loadServerDetail(serverId);
            else await loadDocker();
          }
          return;
        }
        const lines = t.output_lines || [];
        // Показываем user-friendly toast при ошибке (не технические детали из лога)
        if (!t.success) {
          const errMsg = t.error || (lines.length ? lines[0] : 'Ошибка выполнения задачи');
          toast(errMsg, false);
        } else {
          toast(`${t.emoji || '✅'} ${t.name || 'Задача'} — выполнена`, true);
        }
        if (onDetailPage() && serverId) {
          await loadServerDetail(serverId);
          // Обновить активную вкладку, если задача могла изменить её данные
          if (dockerCurrentTab === 'images'
              && (action.startsWith('image_') || action === 'container_run')) {
            await loadImages();
          }
          if (dockerCurrentTab === 'compose' && action.startsWith('compose_')) {
            await loadStacks();
          }
        } else {
          await loadDocker();
        }
        // Кнопки «Быстрых действий» зависят от статуса сервиса — обновляем их.
        if (action === 'install' && t.success) window.refreshAfterServiceChange?.(serverId);
      }
    } catch { /* повторим на следующем тике */ }
  };
  if (timers[taskId]) clearInterval(timers[taskId]);
  tick();
  timers[taskId] = setInterval(tick, 1500);
}

export function stopDockerTimers() {
  stopLivePoll();
  stopPullPoll();
  Object.keys(timers).forEach(k => { clearInterval(timers[k]); delete timers[k]; });
}

export function bindDockerUI() {
  bindDockerServersList();

  // Лёгкие пробы доступности идут фоном, пока панель открыта (SSE);
  // при смене online/offline перечитываем таблицу (экран сервера не трогаем —
  // там свой live-poll).
  window.addEventListener('bot4vps:availability-changed', () => {
    if (document.getElementById('page-docker')?.classList.contains('on')) loadDocker();
  });

  // экран конкретного сервера
  document.getElementById('btn-back-docker')?.addEventListener('click', backToDockerList);
  document.getElementById('btn-back-docker-server')?.addEventListener('click', async () => {
    if (!dockerServerId) return;
    try {
      const { openServer } = await import('./servers.js?v=20260915-sysfix-v2');
      await openServer(dockerServerId);
    } catch (e) {
      console.error(e);
      showPage('servers');
    }
  });

  // диалог подтверждения
  document.getElementById('docker-dialog-ok')?.addEventListener('click', () => closeDockerDialog(true));
  document.getElementById('docker-dialog-alt')?.addEventListener('click', () => closeDockerDialog('import'));
  document.getElementById('docker-dialog-cancel')?.addEventListener('click', () => closeDockerDialog(false));
  // Закрытие по Escape, но НЕ по клику на фон (проблема mousedown-mouseup)
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const dialogEl = document.getElementById('docker-dialog');
      if (dialogEl?.classList.contains('open')) closeDockerDialog(false);
    }
  });

  // модалка запуска контейнера
  document.getElementById('docker-run-port-add')?.addEventListener('click', addRunModalPort);
  document.getElementById('docker-run-env-add')?.addEventListener('click', addRunModalEnv);
  document.getElementById('docker-run-port-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); addRunModalPort(); }
  });
  document.getElementById('docker-run-env-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); addRunModalEnv(); }
  });
  document.getElementById('docker-run-confirm')?.addEventListener('click', confirmRun);
  document.getElementById('docker-run-cancel')?.addEventListener('click', () =>
    document.getElementById('docker-run-modal').classList.remove('open'));
  // Закрытие только по Escape, НЕ по клику на фон
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const runEl = document.getElementById('docker-run-modal');
      if (runEl?.classList.contains('open')) runEl.classList.remove('open');
    }
  });

  // модалка логов
  document.getElementById('docker-logs-refresh')?.addEventListener('click', refreshLogs);
  document.getElementById('docker-logs-close')?.addEventListener('click', () => {
    logsCtx = null;
    document.getElementById('docker-logs-modal').classList.remove('open');
  });
  // Закрытие только по Escape, НЕ по клику на фон
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      const logsEl = document.getElementById('docker-logs-modal');
      if (logsEl?.classList.contains('open')) {
        logsCtx = null;
        logsEl.classList.remove('open');
      }
    }
  });

  // модалка pull образа (Phase 4)
  document.getElementById('docker-pull-confirm')?.addEventListener('click', confirmPull);
  document.getElementById('docker-pull-cancel')?.addEventListener('click', () =>
    document.getElementById('docker-pull-modal').classList.remove('open'));
  document.getElementById('docker-pull-image')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); confirmPull(); }
  });

  // модалки Compose-проектов
  document.getElementById('docker-stack-new-save')?.addEventListener('click', saveNewStack);
  document.getElementById('docker-stack-new-cancel')?.addEventListener('click', () =>
    document.getElementById('docker-stack-new-modal').classList.remove('open'));
  document.getElementById('docker-stack-file-input')?.addEventListener('change', e =>
    readStackFile(e.target.files && e.target.files[0]));
  document.getElementById('docker-stack-zip-input')?.addEventListener('change', e =>
    pickStackZip(e.target.files && e.target.files[0]));

  // модалка файлов проекта
  const closeStackFiles = () => {
    document.getElementById('docker-stack-files-modal').classList.remove('open');
    document.getElementById('docker-stack-files-cancel')?.classList.remove('hidden');
    document.getElementById('docker-stack-files-close')?.classList.remove('hidden');
    stackFilesCtx = null;
    editingFilePath = null;
  };
  document.getElementById('docker-stack-files-close')?.addEventListener('click', closeStackFiles);
  document.getElementById('docker-stack-files-save')?.addEventListener('click', saveProjectFile);
  document.getElementById('docker-stack-files-cancel')?.addEventListener('click', closeStackFiles);

  document.getElementById('docker-stack-edit-save')?.addEventListener('click', saveStackEdit);
  const closeStackEdit = () => {
    document.getElementById('docker-stack-edit-modal').classList.remove('open');
    stackEditCtx = null;
  };
  document.getElementById('docker-stack-edit-cancel')?.addEventListener('click', closeStackEdit);
  document.getElementById('docker-stack-edit-close')?.addEventListener('click', closeStackEdit);

  document.getElementById('docker-stack-logs-refresh')?.addEventListener('click', refreshStackLogs);
  document.getElementById('docker-stack-logs-close')?.addEventListener('click', () => {
    stackLogsCtx = null;
    document.getElementById('docker-stack-logs-modal').classList.remove('open');
  });

  // модалка «Игнорируемые» (§11)
  document.getElementById('docker-ignored-close')?.addEventListener('click', () =>
    document.getElementById('docker-ignored-modal').classList.remove('open'));

  // Единый обработчик Escape для docker-модалок (закрытие по клику на фон
  // намеренно не делаем — легко потерять введённый YAML).
  // Модалка лога задачи общая — её Escape живёт в tasks.js.
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const close = (id, after) => {
      const el = document.getElementById(id);
      if (el?.classList.contains('open')) { el.classList.remove('open'); if (after) after(); }
    };
    close('docker-pull-modal');
    close('docker-stack-new-modal');
    close('docker-stack-edit-modal', () => { stackEditCtx = null; });
    close('docker-stack-logs-modal', () => { stackLogsCtx = null; });
    close('docker-stack-files-modal', () => { stackFilesCtx = null; editingFilePath = null; });
    close('docker-ignored-modal');
  });
}

// Публичный API для навигации app.js (восстановление сессии).
export function openDockerServerById(id) { return openDockerServer(id, { from: 'server' }); }

// Публичный API для установки из внешних модулей (servers.js).
export function openInstall(id) { return installServer(id); }

// Фоновая задача Docker (например, подхваченная резюмом после перезагрузки
// страницы) завершилась — обновляем список, если открыта страница Docker.
document.addEventListener('bot4vps:task-done', e => {
  const t = e.detail || {};
  if (!String(t.name || '').startsWith('Docker:')) return;
  const on = id => document.getElementById(id)?.classList.contains('on');
  if (on('page-docker') || on('page-docker-server')) loadDocker();
});
