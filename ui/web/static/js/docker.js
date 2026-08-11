// Страница Docker: тонкий слой отображения над обобщённым services-роутером.
//
// Вся бизнес-логика — на бэке (core.integrator + services/docker): здесь нет
// сборки docker/compose-команд, разбора вывода Docker и работы с путями на
// сервере. Модуль только запрашивает API, рендерит и собирает поля форм.
//
// Экраны: список серверов + экран сервера с вкладками
// Контейнеры | Образы | Compose.
import { j, esc } from './api.js';
import { toast, showPage } from './ui.js';
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
let statusMap = {};                 // id -> {name, host, status}

// Экран конкретного сервера
let dockerServerId = null;          // id открытого сервера
let dockerServerState = null;       // последний live-state
let dockerCurrentTab = 'containers'; // активная вкладка: containers | images (Phase 4)
let logsCtx = null;                 // {name} — контейнер в открытой модалке логов

const srvBase = id => `/api/services/${SID}/${encodeURIComponent(id)}`;
const stateUrl = id => `${srvBase(id)}/state`;
const nameOf = id => (statusMap[id] && statusMap[id].name) || id;

function pad(n) { return String(n).padStart(2, '0'); }
function shortVer(v) {
  const m = String(v || '').match(/\d+\.\d+[\w.-]*/);
  return m ? m[0] : '';
}
function fmtSync(iso) {
  if (!iso) return '';
  const d = new Date(iso.replace(' ', 'T'));
  if (isNaN(d)) return esc(iso);
  const now = new Date();
  const hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
  if (d.toDateString() === now.toDateString()) return 'сегодня, ' + hm;
  return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + ', ' + hm;
}
function stateBadge(st) {
  if (!st || !Object.keys(st).length) return '<span class="badge unk">⚪ не проверен</span>';
  if (st.installed) {
    return st.active === 'active'
      ? '<span class="badge on">🟢 Docker запущен</span>'
      : '<span class="badge off">🔴 демон остановлен</span>';
  }
  return '<span class="badge off">⚪ не установлен</span>';
}

function containerCount(st) {
  return (st && st.stats && Number(st.stats.total)) || 0;
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
    document.getElementById('docker-dialog').classList.add('open');
  });
}
function closeDockerDialog(val) {
  document.getElementById('docker-dialog').classList.remove('open');
  const r = dialogResolve; dialogResolve = null;
  if (r) r(val);
}

// ---------------- загрузка списка серверов ----------------

export async function loadDocker() {
  const box = document.getElementById('docker-grid');
  if (!box) return;
  try {
    const d = await j(`/api/services/${SID}/status`);
    const servers = d.servers || [];
    statusMap = {};
    servers.forEach(s => { statusMap[s.id] = s; });
    if (!servers.length) { box.innerHTML = '<div class="empty">Серверов нет</div>'; return; }
    box.innerHTML = servers.map(card).join('');
    bindCards();
  } catch (e) {
    box.innerHTML = '<div class="empty" style="color:var(--err)">' + esc(e.message || e) + '</div>';
  }
}

function card(s) {
  const st = s.status || {};
  const installed = !!st.installed;
  const known = !!Object.keys(st).length;
  const v = shortVer(st.version);
  let body = `<h3>🐳 ${esc(s.name)} <span class="hint">${esc(s.host || '')}</span></h3>`;
  body += `<div class="row" style="margin-top:.3rem">${stateBadge(st)}</div>`;
  if (known) {
    body += `<div class="wg-card-info">Версия: <b>${installed && v ? esc(v) : '—'}</b></div>`;
    body += `<div class="wg-card-info">Демон: <b>${installed ? esc(st.active || '—') : '—'}</b></div>`;
    if (installed) body += `<div class="wg-card-info">Контейнеров: <b>${containerCount(st)}</b></div>`;
    body += `<div class="wg-card-info">Проверено: ${fmtSync(st.synced_at) || '—'}</div>`;
  } else {
    body += `<div class="wg-note">Статус неизвестен — нажмите «Синхронизировать».</div>`;
  }
  const actions = installed
    ? `<button type="button" data-open="${esc(s.id)}">Открыть</button>`
      + `<button type="button" class="secondary" data-sync="${esc(s.id)}">🔄 Синхр.</button>`
      + `<button type="button" class="danger" data-rm="${esc(s.id)}">🗑 Удалить</button>`
    : `<button type="button" data-install="${esc(s.id)}">🟢 Установить</button>`
      + `<button type="button" class="secondary" data-sync="${esc(s.id)}">🔄 Синхр.</button>`;
  return `<div class="card"><div class="card-body">${body}</div><div class="card-actions">${actions}</div></div>`;
}

function bindCards() {
  const box = document.getElementById('docker-grid');
  if (!box) return;
  box.querySelectorAll('[data-open]').forEach(b =>
    b.onclick = () => openDockerServer(b.dataset.open));
  box.querySelectorAll('[data-install]').forEach(b =>
    b.onclick = () => installServer(b.dataset.install));
  box.querySelectorAll('[data-sync]').forEach(b =>
    b.onclick = () => syncServer(b.dataset.sync));
  box.querySelectorAll('[data-rm]').forEach(b =>
    b.onclick = () => removeServer(b.dataset.rm));
}

async function installServer(id) {
  const srv = statusMap[id];
  const name = srv && srv.name ? srv.name : (srv && srv.host ? srv.host : id);
  if (!(await dockerConfirm('Установка Docker',
    `Вы действительно хотите установить Docker на сервер «${name}»?\n\n` +
    `Будет установлен Docker Engine через официальный скрипт get.docker.com ` +
    `(~15 минут). Процесс необратим.`,
    'Установить'))) return;
  await enqueueAction(id, 'install', {}, 'Установка в очереди');
}

async function syncServer(id) {
  try {
    await j(`${srvBase(id)}/sync`, { method: 'POST' });
    toast('Статус обновлён', true);
    await loadDocker();
  } catch (e) { toast(e.message, false); }
}

async function removeServer(id) {
  if (!(await dockerConfirm(
    'Удаление Docker',
    `Удалить Docker Engine с сервера «${nameOf(id)}»?\n\n` +
    `Пакеты docker-ce/containerd будут удалены, но /var/lib/docker ` +
    `(образы, тома, контейнеры) сохранится.`,
    'Удалить'))) return;
  await enqueueAction(id, 'remove', {}, 'Удаление в очереди');
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

async function openDockerServer(id) {
  dockerServerId = id;
  dockerServerState = null;
  dockerCurrentTab = 'containers'; // сброс на контейнеры при открытии
  try {
    localStorage.setItem('bot4vps_page', 'docker-server');
    localStorage.setItem('bot4vps_docker_server_id', id);
  } catch (_) {}
  document.getElementById('docker-srv-title').textContent = 'Docker · ' + nameOf(id);
  document.getElementById('docker-srv-body').innerHTML = '<div class="empty">Загрузка…</div>';
  document.getElementById('docker-images-body').innerHTML = '<div class="empty">Загрузка…</div>';
  document.getElementById('docker-compose-body').innerHTML = '<div class="empty">Загрузка…</div>';
  // Привязка табов + показ только вкладки «Контейнеры»
  document.querySelectorAll('#page-docker-server .tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === 'containers');
    tab.onclick = () => switchDockerTab(tab.dataset.tab);
  });
  Object.entries(DOCKER_TAB_BODIES).forEach(([key, elId]) => {
    document.getElementById(elId)?.classList.toggle('hidden', key !== 'containers');
  });
  showPage('docker-server');
  await loadServerDetail(id);
  startLivePoll(id);
}

function backToDockerList() {
  stopLivePoll();
  dockerServerId = null;
  try {
    localStorage.setItem('bot4vps_page', 'docker');
    localStorage.removeItem('bot4vps_docker_server_id');
  } catch (_) {}
  showPage('docker');
  loadDocker();
}

async function loadServerDetail(id) {
  try {
    const d = await j(stateUrl(id));
    dockerServerState = d.state || {};
    renderServerDetail(dockerServerState);
  } catch (e) {
    document.getElementById('docker-srv-body').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function renderServerDetail(st) {
  const body = document.getElementById('docker-srv-body');
  if (!body) return;
  const s = st || {};
  if (!s.installed) {
    body.innerHTML = '<div class="empty">Docker не установлен на этом сервере.</div>';
    return;
  }
  const containers = Array.isArray(s.containers) ? s.containers : [];
  const stats = s.stats || { total: containers.length, running: 0, managed: 0, images: 0 };

  const tile = (label, val) => `<div class="metric"><div class="v">${esc(String(val))}</div><div class="l">${esc(label)}</div></div>`;
  const statsHtml = `<div class="metrics">${
    tile('Версия', shortVer(s.version) || '—')
  }${tile('Демон', s.active || '—')}${tile('Запущено', `${stats.running} / ${stats.total}`)}${tile('Образов', stats.images)}</div>`;

  const runBtn = `<div class="actions" style="margin:.4rem 0 .8rem"><button type="button" id="docker-add-container">➕ Запустить контейнер</button></div>`;

  const cards = containers.length
    ? containers.map(containerCard).join('')
    : '<div class="empty">Контейнеров нет</div>';
  const listHtml = `<div class="wg-section-title">Контейнеры</div>` +
    `<div class="grid wg-profile-grid">${cards}</div>`;

  const admin = `<div class="wg-admin"><div class="wg-section-title">⚠️ Дополнительные действия</div>` +
    `<div class="actions"><button type="button" class="danger" data-rm-svc>🗑 Удалить сервис</button></div></div>`;

  body.innerHTML = statsHtml + runBtn + listHtml + admin;

  body.querySelector('#docker-add-container')?.addEventListener('click', openRunModal);
  body.querySelectorAll('[data-cact]').forEach(b => b.onclick = () =>
    containerAction(b.dataset.name, b.dataset.cact));
  body.querySelector('[data-rm-svc]')?.addEventListener('click', async () => {
    if (!(await dockerConfirm('Удаление сервиса',
      `Удалить Docker с сервера «${nameOf(dockerServerId)}»?\n\nОбразы и тома (/var/lib/docker) сохранятся.`,
      'Удалить'))) return;
    enqueueAction(dockerServerId, 'remove', {}, 'Удаление в очереди');
  });
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
  document.querySelectorAll('#page-docker-server .tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === tab));
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
    const images = d.images || [];
    renderImages(images);
  } catch (e) {
    body.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function renderImages(images) {
  const body = document.getElementById('docker-images-body');
  if (!body) return;
  const pullBtn = `<div class="actions" style="margin:.4rem 0 .8rem">
    <button type="button" id="docker-pull-open">⬇️ Загрузить образ</button>
    <button type="button" class="secondary" id="docker-prune-images">🧹 Очистить неиспользуемые</button>
  </div>`;
  if (!images.length) {
    body.innerHTML = pullBtn + '<div class="empty">Образов нет</div>';
    const pullOpenBtn = body.querySelector('#docker-pull-open');
    pullOpenBtn?.addEventListener('click', openPullModal);
    body.querySelector('#docker-prune-images')?.addEventListener('click', pruneImages);
    return;
  }
  const cards = images.map(img => {
    const fullName = `${img.repository}:${img.tag}`;
    return `<div class="card wg-prof-card">
      <div class="card-body">
        <h3 style="font-size:.95rem">${esc(fullName)}</h3>
        <div class="wg-prof-field"><span class="wg-prof-label">ID</span><span class="mono wg-prof-val">${esc(img.id || '—')}</span></div>
        <div class="wg-prof-field"><span class="wg-prof-label">Размер</span><span class="wg-prof-val">${esc(img.size || '—')}</span></div>
        <div class="wg-prof-field"><span class="wg-prof-label">Создан</span><span class="wg-prof-val">${esc(img.created || '—')}</span></div>
      </div>
      <div class="card-actions">
        <button type="button" class="danger" data-img-rm="${esc(fullName)}">🗑 Удалить</button>
      </div>
    </div>`;
  }).join('');
  body.innerHTML = pullBtn + `<div class="wg-section-title">Образы (${images.length})</div>` +
    `<div class="grid wg-profile-grid">${cards}</div>`;
  const pullOpenBtn = body.querySelector('#docker-pull-open');
  pullOpenBtn?.addEventListener('click', openPullModal);
  body.querySelector('#docker-prune-images')?.addEventListener('click', pruneImages);
  body.querySelectorAll('[data-img-rm]').forEach(b =>
    b.onclick = () => removeImage(b.dataset.imgRm));
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

// Последний ответ /stacks: нужен диалогу импорта, чтобы понять, перезапись это
// или новый проект (in_library / lib_match).
let lastStacks = { library: [], server: [] };

async function loadStacks() {
  const body = document.getElementById('docker-compose-body');
  if (!body || !dockerServerId) return;
  try {
    const d = await j(stackBase(dockerServerId));
    lastStacks = d || { library: [], server: [] };
    renderStacks(d);
  } catch (e) {
    body.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function renderStacks(data) {
  const body = document.getElementById('docker-compose-body');
  if (!body) return;
  const reconciled = data.reconciled || {};
  const both = reconciled.both || [];
  const libraryOnly = reconciled.library_only || [];
  const serverOnly = reconciled.server_only || [];
  const serverAccessible = data.server_accessible;

  const head = `<div class="actions" style="margin:.4rem 0 .8rem">
    <button type="button" id="docker-stack-new">➕ Новый стек</button>
  </div>`;
  const hint = `<div class="wg-hint">📚 Библиотека — шаблоны для развёртывания на любой сервер.
🖥 На сервере — реальное состояние (включая внешние проекты).</div>`;

  // Библиотека (both + library_only). _match — результат сравнения версий (§23).
  const libItems = [
    ...both.map(b => ({
      ...b.library, _onServer: true, _serverState: b.server, _match: b.project_match,
    })),
    ...libraryOnly,
  ];
  const libCards = libItems.length > 0
    ? libItems.map(stackCardLibrary).join('')
    : '<div class="empty">Стеков нет</div>';
  const libSection = `<div class="compose-col">
    <div class="wg-section-title">📚 Библиотека (${libItems.length})</div>
    <div class="grid wg-profile-grid">${libCards}</div>
  </div>`;

  // Сервер (both + server_only)
  // in_library / lib_match приходят из Core — на фронте их не досчитываем.
  const srvItems = [...both.map(b => b.server), ...serverOnly];
  let srvCards = '';
  if (!serverAccessible) {
    srvCards = '<div class="empty">Сервер недоступен (SSH)</div>';
  } else if (srvItems.length > 0) {
    srvCards = srvItems.map(stackCardServer).join('');
  } else {
    srvCards = '<div class="empty">Проектов не обнаружено</div>';
  }
  const srvSection = `<div class="compose-col">
    <div class="wg-section-title">🖥 На сервере «${esc(nameOf(dockerServerId))}» (${srvItems.length})</div>
    <div class="grid wg-profile-grid">${srvCards}</div>
  </div>`;

  body.innerHTML = hint + head + `<div class="compose-two-col">${libSection}${srvSection}</div>`;
  bindStackHead(body);
  body.querySelectorAll('[data-stack-act]').forEach(b => b.onclick = () => stackAction({
    name: b.dataset.stackName,
    act: b.dataset.stackAct,
    source: b.dataset.source || 'library',
    key: b.dataset.key || null,
  }));
}

function bindStackHead(body) {
  body.querySelector('#docker-stack-new')?.addEventListener('click', openStackNewModal);
}

// Статус развёртывания по числу контейнеров.
function deployBadge(running, total, deployed) {
  if (!deployed) return '<span class="badge unk">⚪ не запущен</span>';
  if (running > 0 && running === total) return '<span class="badge on">🟢 запущен</span>';
  if (running > 0) return '<span class="badge ssl-warn">🟡 частично</span>';
  return '<span class="badge off">🔴 остановлен</span>';
}

// Совпадение локальной версии проекта с развёрнутой (§23).
function matchRow(match) {
  if (match === true) {
    return `<div class="wg-prof-field"><span class="wg-prof-label">Версия</span><span class="wg-prof-val">🟢 совпадает</span></div>`;
  }
  if (match === false) {
    return `<div class="wg-prof-field"><span class="wg-prof-label">Версия</span><span class="wg-prof-val">⚠ на сервере отличается</span></div>`;
  }
  return '';
}

function filesRow(s) {
  const extra = Array.isArray(s.extra_files) ? s.extra_files.length : 0;
  if (!extra) return '';
  const label = s.has_env ? `${extra} (вкл. .env)` : String(extra);
  return `<div class="wg-prof-field"><span class="wg-prof-label">Доп. файлов</span><span class="wg-prof-val">${esc(label)}</span></div>`;
}

function stackCardLibrary(s) {
  const onServer = s._onServer;
  const srv = s._serverState || {};
  const running = onServer ? (Number(srv.containers_running) || 0) : 0;
  const total = onServer ? (Number(srv.containers_total) || 0) : 0;
  const badge = !onServer
    ? '<span class="badge unk">⚪ только в библиотеке</span>'
    : deployBadge(running, total, !!srv.deployed);
  const services = (s.services && s.services.length)
    ? s.services.map(x => esc(x)).join(', ') : '—';
  const name = esc(s.name);
  const act = (a, label, cls) =>
    `<button type="button" class="${cls}" data-stack-act="${a}" data-stack-name="${name}" data-source="library">${label}</button>`;
  const counters = onServer
    ? `<div class="wg-prof-field"><span class="wg-prof-label">Контейнеры</span><span class="wg-prof-val">${running} / ${total}</span></div>`
    : '';
  return `<div class="card wg-prof-card">
    <div class="card-body">
      <h3>🧩 ${name}</h3>
      <div class="row" style="margin-top:.3rem">${badge}</div>
      <div class="wg-prof-field"><span class="wg-prof-label">Сервисы</span><span class="mono wg-prof-val">${services}</span></div>
      ${filesRow(s)}
      ${counters}
      ${matchRow(s._match)}
    </div>
    <div class="card-actions">
      ${total === 0 ? act('up', '▶ Развернуть', '') : act('restart', '🔄 Перезапустить / применить', 'secondary')}
      ${total > 0 ? act('down', '⏹ Остановить', 'secondary') : ''}
      ${act('files', '📂 Файлы', 'secondary')}
      ${act('edit', '✏️ Изменить', 'secondary')}
      ${total > 0 ? act('logs', '📄 Логи', 'secondary') : ''}
      ${act('delete-lib', '🗑 Удалить из библиотеки', 'danger')}
    </div>
  </div>`;
}

function stackCardServer(s) {
  const running = Number(s.containers_running) || 0;
  const total = Number(s.containers_total) || 0;
  const deployed = !!s.deployed;
  const badge = s.managed
    ? '<span class="badge on">🟢 Bot4VPS</span>'
    : '<span class="badge ssl-warn">🟡 Внешний</span>';
  const name = esc(s.name);
  // Все действия внешнего проекта идут по его реальному пути: key однозначно
  // выбирает развёртывание, даже если имя проекта неуникально (§14, §16).
  const act = (a, label, cls) =>
    `<button type="button" class="${cls}" data-stack-act="${a}" data-stack-name="${name}" data-source="server" data-key="${esc(s.key || '')}">${label}</button>`;
  const counters = deployed
    ? `<div class="wg-prof-field"><span class="wg-prof-label">Контейнеры</span><span class="wg-prof-val">${running} / ${total}</span></div>`
    : '';
  const cfg = Array.isArray(s.config_files) && s.config_files.length
    ? s.config_files.map(c => esc(c.split('/').pop())).join(', ')
    : '—';
  // Сверка с библиотекой определяет, показывать ли импорт: при полном
  // совпадении он лишний и рискует затереть локальную копию.
  const inLib = !!s.in_library;
  const match = s.lib_match;
  const libRow = (() => {
    if (!inLib) return '<span class="wg-prof-val">📚 нет в библиотеке</span>';
    if (match === true) return '<span class="wg-prof-val">🟢 совпадает</span>';
    if (match === false) return '<span class="wg-prof-val">🟡 отличается</span>';
    return '<span class="wg-prof-val">📚 есть одноимённый</span>';
  })();
  const importBtn = match === true
    ? ''
    : act('import', inLib ? '⬇️ Импортировать (перезапись)' : '⬇️ Импортировать', 'secondary');
  return `<div class="card wg-prof-card">
    <div class="card-body">
      <h3>🧩 ${name}</h3>
      <div class="row" style="margin-top:.3rem">${badge} ${deployBadge(running, total, deployed)}</div>
      <div class="wg-prof-field"><span class="wg-prof-label">Каталог</span><span class="mono wg-prof-val">${esc(s.working_dir || '—')}</span></div>
      <div class="wg-prof-field"><span class="wg-prof-label">Compose</span><span class="mono wg-prof-val">${cfg}</span></div>
      <div class="wg-prof-field"><span class="wg-prof-label">Библиотека</span>${libRow}</div>
      ${counters}
    </div>
    <div class="card-actions">
      ${total === 0 ? act('up', '▶ Запустить', '') : act('restart', '🔄 Перезапустить / применить', 'secondary')}
      ${total > 0 ? act('down', '⏹ Остановить', 'secondary') : ''}
      ${total > 0 ? act('logs', '📄 Логи', 'secondary') : ''}
      ${importBtn}
      ${act('delete-remote', '🗑 Удалить с сервера', 'danger')}
    </div>
  </div>`;
}

// Единая точка действий: source/key передаются в Core как параметры (§19),
// никакого выбора *_remote на фронте больше нет.
async function stackAction({ name, act, source, key }) {
  if (act === 'edit') return openStackEditModal(name);
  if (act === 'files') return openStackFilesModal(name);
  if (act === 'logs') return openStackLogs(name, source, key);
  if (act === 'delete-lib') return deleteStackFromLibrary(name);
  if (act === 'delete-remote') return deleteStackFromServer(name, source, key);
  if (act === 'import') return importStackFromServer(name, key);
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
  if (!(await dockerConfirm('Удаление из библиотеки',
    `Удалить проект «${name}» из библиотеки Bot4VPS?\n\n` +
    `Запущенные контейнеры на сервере НЕ будут остановлены. ` +
    `Чтобы убрать проект и с сервера, используйте «🗑 Удалить с сервера».`,
    'Удалить из библиотеки'))) return;
  try {
    await j(`${stackBase(dockerServerId)}/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast('Проект удалён из библиотеки', true);
    await loadStacks();
  } catch (e) { toast(e.message, false); }
}

async function deleteStackFromServer(name, source, key) {
  if (!(await dockerConfirm('Удаление с сервера',
    `Удалить проект «${name}» с сервера?\n\n` +
    `Сначала будет выполнена остановка (тома сохранятся), и только при её ` +
    `успехе каталог проекта удалится. Библиотека Bot4VPS не изменится.`,
    'Удалить с сервера'))) return;
  await enqueueAction(dockerServerId, 'compose_delete_remote',
    { stack: name, source, key }, 'Удаление с сервера в очереди');
}

async function importStackFromServer(name, key) {
  // Проект в библиотеке уже есть → предупреждаем о перезаписи локальной копии.
  const rec = (lastStacks.server || []).find(r => r.key === key);
  const inLib = !!(rec && rec.in_library);
  const diff = rec && rec.lib_match === false
    ? 'Серверная версия отличается от локальной.'
    : 'Сравнить версии не удалось.';
  const text = inLib
    ? `Проект «${name}» уже есть в библиотеке Bot4VPS.\n${diff}\n\n` +
      `Локальная копия будет заменена версией с сервера.`
    : `Импортировать проект «${name}» в библиотеку Bot4VPS?\n\n` +
      `Будет перенесён весь каталог проекта: Compose-файл, .env и другие файлы.`;
  if (!(await dockerConfirm(
    inLib ? 'Перезапись в библиотеке' : 'Импорт в библиотеку',
    text, inLib ? 'Да, импортировать' : 'Импортировать'))) return;
  await enqueueAction(dockerServerId, 'compose_import',
    { stack: name, key, overwrite: inLib }, 'Импорт в очереди');
}

async function deleteStack(name) {
  // Старая функция — теперь не используется, заменена на deleteStackFromLibrary
  return deleteStackFromLibrary(name);
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

// ---------------- модалка файлов проекта ----------------

let stackFilesCtx = null;    // имя проекта
let editingFilePath = null;  // редактируемый файл

async function openStackFilesModal(name) {
  stackFilesCtx = name;
  editingFilePath = null;
  document.getElementById('docker-stack-files-title').textContent = '📂 ' + name;
  document.getElementById('docker-stack-files-warn').textContent = '';
  document.getElementById('docker-stack-files-editor').classList.add('hidden');
  document.getElementById('docker-stack-files-list').innerHTML = '<div class="empty">Загрузка…</div>';
  document.getElementById('docker-stack-files-modal').classList.add('open');
  await refreshStackFiles();
}

async function refreshStackFiles() {
  if (!stackFilesCtx || !dockerServerId) return;
  const listEl = document.getElementById('docker-stack-files-list');
  try {
    const r = await j(
      `${stackBase(dockerServerId)}/${encodeURIComponent(stackFilesCtx)}/files`);
    const files = r.files || [];
    if (!files.length) { listEl.innerHTML = '<div class="empty">Файлов нет</div>'; return; }
    listEl.innerHTML = files.map(f => `<div class="row" style="gap:.4rem;align-items:center">
      <span class="mono" style="flex:1">${f.is_compose ? '🧩 ' : '📄 '}${esc(f.path)}</span>
      <span class="hint">${Number(f.size) || 0} Б</span>
      <button type="button" class="secondary" data-file-edit="${esc(f.path)}" style="padding:.2rem .5rem">✏️</button>
      ${f.is_compose ? '' : `<button type="button" class="danger" data-file-del="${esc(f.path)}" style="padding:.2rem .5rem">✕</button>`}
    </div>`).join('');
    listEl.querySelectorAll('[data-file-edit]').forEach(b =>
      b.onclick = () => openFileEditor(b.dataset.fileEdit));
    listEl.querySelectorAll('[data-file-del]').forEach(b =>
      b.onclick = () => deleteProjectFile(b.dataset.fileDel));
  } catch (e) {
    listEl.innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

async function openFileEditor(path) {
  const warn = document.getElementById('docker-stack-files-warn');
  const area = document.getElementById('docker-stack-files-content');
  warn.textContent = '';
  try {
    const qs = new URLSearchParams({ path });
    const r = await j(
      `${stackBase(dockerServerId)}/${encodeURIComponent(stackFilesCtx)}/files/content?${qs}`);
    editingFilePath = path;
    area.value = r.content || '';
    document.getElementById('docker-stack-files-editing').textContent = path;
    document.getElementById('docker-stack-files-editor').classList.remove('hidden');
  } catch (e) {
    warn.textContent = e.message;
  }
}

async function saveProjectFile() {
  if (!editingFilePath) return;
  const warn = document.getElementById('docker-stack-files-warn');
  const content = document.getElementById('docker-stack-files-content').value;
  try {
    await j(`${stackBase(dockerServerId)}/${encodeURIComponent(stackFilesCtx)}/files`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: editingFilePath, content }),
    });
    toast('Файл сохранён. Нажмите «Перезапустить / применить», чтобы применить на сервере.', true);
    document.getElementById('docker-stack-files-editor').classList.add('hidden');
    editingFilePath = null;
    await refreshStackFiles();
    await loadStacks();
  } catch (e) {
    warn.textContent = e.message;
  }
}

async function deleteProjectFile(path) {
  if (!(await dockerConfirm('Удаление файла',
    `Удалить «${path}» из проекта «${stackFilesCtx}»?`, 'Удалить'))) return;
  try {
    const qs = new URLSearchParams({ path });
    await j(`${stackBase(dockerServerId)}/${encodeURIComponent(stackFilesCtx)}/files?${qs}`,
      { method: 'DELETE' });
    toast('Файл удалён', true);
    await refreshStackFiles();
    await loadStacks();
  } catch (e) {
    document.getElementById('docker-stack-files-warn').textContent = e.message;
  }
}

// ---------------- модалка редактирования стека ----------------

let stackEditCtx = null;   // имя стека в открытом редакторе

async function openStackEditModal(name) {
  stackEditCtx = name;
  const warn = document.getElementById('docker-stack-edit-warn');
  const area = document.getElementById('docker-stack-edit-yaml');
  document.getElementById('docker-stack-edit-title').textContent = '✏️ ' + name;
  warn.textContent = '';
  area.value = 'Загрузка…';
  document.getElementById('docker-stack-edit-modal').classList.add('open');
  try {
    const d = await j(`${stackBase(dockerServerId)}/${encodeURIComponent(name)}/file`);
    area.value = d.content || '';
  } catch (e) {
    area.value = '';
    warn.textContent = e.message;
  }
}

async function saveStackEdit() {
  if (!stackEditCtx) return;
  const warn = document.getElementById('docker-stack-edit-warn');
  const content = document.getElementById('docker-stack-edit-yaml').value;
  if (!content.trim()) { warn.textContent = 'Файл не может быть пустым.'; return; }
  try {
    await j(`${stackBase(dockerServerId)}/${encodeURIComponent(stackEditCtx)}/file`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    toast('Сохранено. Нажмите «Перезапустить», чтобы применить на сервере.', true);
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

function containerCard(c) {
  const dot = c.state === 'running' ? '🟢' : (c.state === 'exited' ? '⚪' : '🟡');
  const kind = c.managed ? '<span class="badge on">🤖 Bot4VPS</span>' : '<span class="badge unk">внешний</span>';
  const ports = (c.ports && c.ports.length) ? c.ports.map(p => esc(p)).join('<br>') : '—';
  const running = c.state === 'running';
  const net = (c.net_in || c.net_out) ? `↓ ${esc(c.net_in || '—')} · ↑ ${esc(c.net_out || '—')}` : '—';
  // §3: uptime_seconds поступает с бэкенда, форматируем для человека (1м 23с).
  const uptime = running && c.uptime_seconds != null
    ? formatUptime(c.uptime_seconds)
    : '—';
  const startStop = running
    ? `<button type="button" class="secondary" data-cact="stop" data-name="${esc(c.name)}">⏹ Стоп</button>`
    : `<button type="button" class="secondary" data-cact="start" data-name="${esc(c.name)}">▶ Старт</button>`;
  const openService = (c.service_url && running)
    ? `<a href="${esc(c.service_url)}" target="_blank" class="btn secondary" style="text-decoration:none">🌐 Открыть сервис</a>`
    : '';
  return `<div class="card wg-prof-card">
    <div class="card-body">
      <h3>${esc(c.name)} ${kind}</h3>
      <div class="wg-card-info">${dot} ${esc(c.status || c.state || '—')}</div>
      <div class="wg-prof-field"><span class="wg-prof-label">Образ</span><span class="mono wg-prof-val">${esc(c.image || '—')}</span></div>
      <div class="wg-prof-field"><span class="wg-prof-label">Порты</span><span class="mono wg-prof-val">${ports}</span></div>
      <div class="wg-prof-field"><span class="wg-prof-label">CPU / MEM</span><span class="mono wg-prof-val">${esc(c.cpu || '—')} · ${esc(c.mem || '—')}</span></div>
      <div class="wg-prof-field"><span class="wg-prof-label">⏱ Uptime</span><span class="mono wg-prof-val">${uptime}</span></div>
      <div class="wg-prof-traffic"><span>${net}</span></div>
    </div>
    <div class="card-actions">
      ${openService}
      ${startStop}
      <button type="button" class="secondary" data-cact="restart" data-name="${esc(c.name)}">🔄</button>
      <button type="button" class="secondary" data-cact="logs" data-name="${esc(c.name)}">📄 Логи</button>
      <button type="button" class="danger" data-cact="rm" data-name="${esc(c.name)}">🗑</button>
    </div>
  </div>`;
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

async function enqueueAction(id, action, params, msg) {
  try {
    const r = await j(`${srvBase(id)}/enqueue/${encodeURIComponent(action)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params }),
    });
    toast(msg || 'В очереди', true);
    if (r.task) watchTask(r.task.id, id, action);
  } catch (e) { toast(e.message, false); }
}

// ---------------- live-вывод задачи ----------------

// На экране сервера лог показываем в его блоке; в списке — в общем.
function watchTask(taskId, serverId, action) {
  const onDetail = document.getElementById('page-docker-server')?.classList.contains('on');
  const wrap = document.getElementById(onDetail ? 'docker-srv-log-wrap' : 'docker-task-log-wrap');
  const log = document.getElementById(onDetail ? 'docker-srv-log' : 'docker-task-log');
  if (wrap) wrap.classList.remove('hidden');
  if (!log) return;
  const tick = async () => {
    try {
      const t = await j('/api/tasks/' + encodeURIComponent(taskId));
      const head = `${esc(t.emoji || '')} ${esc(t.name || '')} · ${esc(t.status || '')} · ${esc(t.duration || '')}`;
      const lines = t.output_lines || [];
      const bodyHtml = lines.length ? lines.map(ansiToHtml).join('\n') : esc('(нет вывода)');
      log.innerHTML = `<div class="tasklog-head">${head}</div><div class="tasklog-body">${bodyHtml}</div>`;
      log.scrollTop = log.scrollHeight;
      if (t.is_done) {
        clearInterval(timers[taskId]); delete timers[taskId];
        // Показываем user-friendly toast при ошибке (не технические детали из лога)
        if (!t.success) {
          const errMsg = t.error || (lines.length ? lines[0] : 'Ошибка выполнения задачи');
          toast(errMsg, false);
        }
        if (action === 'remove') { backToDockerList(); return; }  // сервис удалён — к списку
        const stillDetail = document.getElementById('page-docker-server')?.classList.contains('on');
        if (stillDetail && serverId) {
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
      }
    } catch { /* повторим на следующем тике */ }
  };
  if (timers[taskId]) clearInterval(timers[taskId]);
  tick();
  timers[taskId] = setInterval(tick, 1500);
}

export function stopDockerTimers() {
  stopLivePoll();
  Object.keys(timers).forEach(k => { clearInterval(timers[k]); delete timers[k]; });
}

export function bindDockerUI() {
  document.getElementById('docker-sync-all')?.addEventListener('click', async () => {
    try {
      const r = await j(`/api/services/${SID}/bulk-check`, { method: 'POST' });
      toast('Проверка запущена', true);
      if (r.task) watchTask(r.task.id, null);
    } catch (e) { toast(e.message, false); }
  });
  document.getElementById('docker-live-log-close')?.addEventListener('click', () =>
    document.getElementById('docker-task-log-wrap')?.classList.add('hidden'));

  // экран конкретного сервера
  document.getElementById('btn-back-docker')?.addEventListener('click', backToDockerList);
  document.getElementById('docker-srv-refresh')?.addEventListener('click', () => {
    if (dockerServerId) {
      loadServerDetail(dockerServerId);
      // Обновить активную вкладку (Phase 4 — образы, Phase 5 — стеки)
      if (dockerCurrentTab === 'images') loadImages();
      else if (dockerCurrentTab === 'compose') loadStacks();
    }
  });
  document.getElementById('docker-srv-log-close')?.addEventListener('click', () =>
    document.getElementById('docker-srv-log-wrap')?.classList.add('hidden'));

  // диалог подтверждения
  document.getElementById('docker-dialog-ok')?.addEventListener('click', () => closeDockerDialog(true));
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
    stackFilesCtx = null;
    editingFilePath = null;
  };
  document.getElementById('docker-stack-files-close')?.addEventListener('click', closeStackFiles);
  document.getElementById('docker-stack-files-save')?.addEventListener('click', saveProjectFile);
  document.getElementById('docker-stack-files-cancel')?.addEventListener('click', () => {
    document.getElementById('docker-stack-files-editor').classList.add('hidden');
    editingFilePath = null;
  });

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
  });
}

// Публичный API для навигации app.js (восстановление сессии).
export function openDockerServerById(id) { return openDockerServer(id); }
