// Страница 3x-ui: тонкий слой отображения над обобщённым services-роутером.
//
// Бизнес-логика — на бэке (services/3x-ui): источник артефакта, валидация,
// SSL-режимы, креды. Здесь — рендер списка серверов и визард установки:
//   шаг 1 «Доступ»  → логин/пароль (генератор), порт, web base path;
//   шаг 2 «SSL»     → LE домен / LE IP / свои пути / без SSL (bind 127.0.0.1);
//   шаг 3 «Превью»  → версия, источник, arch → «Установить»;
//   прогресс        → live-вывод задачи;
//   финал           → Access URL, логин/пароль, API-токен, копирование.
//
// Клиентская валидация — ТОЛЬКО мгновенная подсказка (как docker.js §25):
// авторитет — impl/validation.py, бэкенд проверяет всё повторно.
import { j, esc } from './api.js';
import { toast, showPage, confirmAction } from './ui.js';
import { ansiToHtml } from './ansi.js';
import { statusFilterBtn, statusFilterHidden, bindStatusFilter } from './statusfilter.js?v=20260915-v1';

const SID = '3x-ui';
const srvBase = id => `/api/services/${SID}/${encodeURIComponent(id)}`;

// ---------------- генераторы (дефолты шага 1) ----------------
const ALPHA = 'abcdefghijkmnpqrstuvwxyz23456789';
const TOKEN = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';

function randStr(len, alphabet) {
  const buf = new Uint32Array(len);
  crypto.getRandomValues(buf);
  return Array.from(buf, n => alphabet[n % alphabet.length]).join('');
}
const genPassword = () => randStr(16, TOKEN);
const genPath = () => randStr(18, ALPHA);
const genPort = () => 10000 + Math.floor(Math.random() * 55000);

// ---------------- состояние ----------------
let statusMap = {};        // id -> {name, host, status}
let xuiTimers = {};        // taskId -> polling-интервал
let wizardCtx = null;      // открытый визард {serverId, resolve, arch}
let xuiSort = { key: 'name', descending: false };
let xuiUrlRevealed = new Set();   // id серверов с раскрытым URL панели
let xuiRevealAllUrls = false;     // глаз в заголовке: показать URL всех панелей
// карточка сервиса (этап 4)
let xuiServerId = null;    // открытая карточка
let xuiCardState = null;   // последний state карточки
let xuiLiveTimer = null;   // live-poll карточки (3с)
let xuiMutationRefreshPending = false;
let xuiEntryContext = 'list';      // откуда пришли: список | карточка сервера
let xuiCardBusy = false;   // card_*-запрос в полёте (защита от двойного клика)

window.addEventListener('bot4vps:xui-cache-changed', () => {
  if (xuiMutationRefreshPending) return;
  if (document.getElementById('page-xui-server')?.classList.contains('on') && xuiServerId) {
    loadXuiServerDetail(xuiServerId);
  } else if (document.getElementById('page-xui')?.classList.contains('on')) {
    loadXui();
  }
});

const nameOf = id => (statusMap[id] && statusMap[id].name) || id;

function xuiServerIpv4(id) {
  const server = statusMap[id] || {};
  for (const raw of [server.host_ip, server.host]) {
    const value = String(raw || '').trim();
    const parts = value.split('.');
    if (parts.length === 4 && parts.every(part => /^\d{1,3}$/.test(part)
        && Number(part) >= 0 && Number(part) <= 255)) return value;
  }
  return '';
}

export function stopXuiTimers() {
  Object.values(xuiTimers).forEach(clearInterval);
  xuiTimers = {};
  // ватчеры сняты (уход с xui*/смена карточки) — лок больше не снимется
  // колбэком задачи, сбрасываем вручную
  xuiCardBusy = false;
  document.getElementById('xui-srv-body')?.classList.remove('xui-card-busy');
}

/** Live-poll карточки живёт отдельно от таймеров задач: уход с xui-server
 *  останавливает опрос состояния, но установка «в фон» продолжает
 *  сопровождаться (её останавливает stopXuiTimers при уходе с xui*). */
export function stopXuiCardPoll() {
  if (xuiLiveTimer) { clearInterval(xuiLiveTimer); xuiLiveTimer = null; }
}

export async function loadXui() {
  bindXuiServersList();
  bindXuiCardUI();   // статичные кнопки карточки (back/refresh) — идемпотентно
  const el = document.getElementById('xui-servers');
  if (!el) return;
  try {
    const r = await j(`/api/services/${SID}/status`);
    statusMap = {};
    (r.servers || []).forEach(s => { statusMap[s.id] = s; });
    renderXuiServers();
  } catch (e) {
    el.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`;
  }
}

// ---------------- сортировка (паттерн WG) ----------------

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

function sortedXuiServers() {
  const list = Object.values(statusMap).sort((a, b) =>
    String(a.name || '').localeCompare(String(b.name || ''), 'ru',
      { sensitivity: 'base', numeric: true })
    || String(a.id).localeCompare(String(b.id)));
  if (xuiSort.key === 'status') {
    // установленные сверху/снизу (toggle); sort стабилен — алфавит внутри
    const d = xuiSort.descending ? -1 : 1;
    return list.sort((a, b) =>
      ((!!(a.status || {}).installed === !!(b.status || {}).installed) ? 0
        : (a.status || {}).installed ? -d : d));
  }
  if (xuiSort.key === 'version') {
    // свежая → старая по умолчанию; без версии — всегда внизу
    const has = s => String(((s || {}).status || {}).version || '').trim() !== '';
    return list.sort((a, b) => {
      if (has(a) !== has(b)) return has(a) ? -1 : 1;
      if (!has(a)) return 0;
      const va = a.status.version, vb = b.status.version;
      return xuiSort.descending ? compareVersions(va, vb)
                                : compareVersions(vb, va);
    });
  }
  return xuiSort.descending ? list.reverse() : list;
}

// ---------------- ячейки ----------------

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

const XUI_BLOCKED_NOTE = {
  down: ['⛔ Сервер оффлайн — работа с сервисом невозможна', '⛔ Оффлайн'],
  ssh: ['⛔ SSH-порт недоступен — работа с сервисом невозможна', '⛔ Нет SSH'],
};

function xuiStatusCell(s) {
  const st = s.status || {};
  return st.installed
    ? '<span class="badge on" title="Установлен">Установлен</span>'
    : '<span class="badge off svc-badge-absent" title="Не установлен">Не установлен</span>';
}

/** URL панели содержит секретный web base path: ••• → клик (показать) и
 *  показанный адрес → клик (скрыть) — построчный тогл. Глобального глаза
 *  в заголовке нет (убран по решению пользователя), поэтому обратное
 *  скрытие — кликом по самому адресу. ⧉ — копирование (классы те же,
 *  что Endpoint в списке WireGuard). */
function xuiPanelCell(s) {
  const st = s.status || {};
  const url = String(st.panel_url || '').trim();
  if (!url) return '<span class="server-host-empty">—</span>';
  const id = String(s.id ?? '');
  const value = xuiRevealAllUrls || xuiUrlRevealed.has(id)
    ? `<button type="button" class="server-host-value" data-xui-url-hide="${esc(id)}"
               title="Скрыть адрес панели" aria-label="Скрыть адрес панели сервера «${esc(s.name || '')}»"
               style="border:0;background:transparent;box-shadow:none;color:inherit;font:inherit;padding:0;cursor:pointer;text-align:left;text-decoration:none">${esc(url)}</button>`
    : `<button type="button" class="server-host-reveal" data-xui-url-reveal="${esc(id)}"
               title="Показать адрес панели" aria-label="Показать адрес панели сервера «${esc(s.name || '')}»">
         <span aria-hidden="true">••••••••</span>
       </button>`;
  // URL и ⧉ — слева ячейки, «Перейти ↗» — прижата вправо с отступом
  // (justify-content:space-between у .xui-panel-content), между Версией
  // и Панелью — разрыв шириной колонки Версия (padding-left ячейки).
  return `<span class="server-host-content xui-panel-content">
    <span class="server-host-content" style="min-width:0">
      ${value}
      <button type="button" class="server-host-copy" data-xui-url-copy="${esc(id)}"
              title="Копировать адрес" aria-label="Копировать адрес панели сервера «${esc(s.name || '')}»">
        <span aria-hidden="true">⧉</span>
      </button>
    </span>
    <button type="button" class="xui-open-btn" data-xui-open="${esc(id)}" data-xui-url="${esc(url)}"
            title="Открыть панель" aria-label="Открыть панель сервера «${esc(s.name || '')}»">Перейти ↗</button>
  </span>`;
}

function xuiRowCells(s) {
  const st = s.status || {};
  const name = `<td class="server-name-cell" data-label="Имя"><strong>${esc(s.name || '—')}</strong></td>`;
  // Недоступный сервер (оффлайн или закрытый SSH-порт): колонки сервиса не
  // показываем, «Установить» не предлагаем — работа невозможна.
  const blocked = serviceBlocked(s);
  if (blocked) {
    const [full, short] = XUI_BLOCKED_NOTE[blocked];
    return `${name}
      <td colspan="3" class="svc-offline-cell"><span class="svc-offline-note">
        <span class="svc-offline-note-full">${full}</span>
        <span class="svc-offline-note-short">${short}</span>
      </span></td>`;
  }
  const status = `<td class="wg-status-cell" data-label="Статус">${xuiStatusCell(s)}</td>`;
  if (st.installed) {
    return `${name}${status}
      <td class="wg-version-cell" data-label="Версия">${esc(st.version || '—')}</td>
      <td class="server-host-cell wg-endpoint-cell xui-panel-cell" data-label="Панель">${xuiPanelCell(s)}</td>`;
  }
  // не установлен: объединённая область с центрированным «Установить»
  const action = `<button type="button" class="wg-row-action" data-install="${esc(s.id)}">🟢 Установить</button>`;
  return `${name}${status}
    <td colspan="2" class="wg-row-action-cell">${action}</td>`;
}

// ---------------- заголовки таблицы ----------------

/** Статус строки для фильтра (см. XUI_STATUS_FILTERS). */
function xuiFilterKey(s) {
  if (serviceBlocked(s)) return 'blocked';
  return (s || {}).status?.installed ? 'installed' : 'absent';
}

const XUI_STATUS_FILTERS = [
  { key: 'installed', label: 'Установлен' },
  { key: 'absent', label: 'Не установлен' },
  { key: 'blocked', label: '⛔ Недоступен (оффлайн/SSH)' },
];

function xuiSortHeader(key, label, extra = '') {
  const active = xuiSort.key === key;
  const descending = active && xuiSort.descending;
  return `<th aria-sort="${active ? (descending ? 'descending' : 'ascending') : 'none'}">
    <span class="wg-col-head">
      <button type="button" class="server-column-sort${active ? ' on' : ''}" data-xui-sort="${esc(key)}"
              aria-pressed="${active ? 'true' : 'false'}"
              title="Сортировать по столбцу «${esc(label)}»">
        <span>${esc(label)}</span>
        <span class="server-sort-arrow" aria-hidden="true">${active ? (descending ? '↓' : '↑') : ''}</span>
      </button>${extra}
    </span>
  </th>`;
}

function xuiPanelHeader() {
  const label = xuiRevealAllUrls
    ? 'Скрыть адреса всех панелей'
    : 'Показать адреса всех панелей';
  return `<th>
    <span class="server-host-heading">
      <span>Панель</span>
      <button type="button" class="server-host-visibility${xuiRevealAllUrls ? ' on' : ''}"
              data-xui-url-visibility-toggle aria-pressed="${xuiRevealAllUrls ? 'true' : 'false'}"
              title="${label}" aria-label="${label}">
        <span aria-hidden="true">👁</span>
      </button>
    </span>
  </th>`;
}

// ---------------- рендер ----------------

function renderXuiServers() {
  const el = document.getElementById('xui-servers');
  if (!el) return;
  if (!Object.keys(statusMap).length) {
    el.innerHTML = '<div class="empty">Нет серверов. Добавьте сервер в разделе «Серверы».</div>';
    return;
  }
  const rows = sortedXuiServers().filter(s => {
    // Фильтр статусов (кнопка у заголовка «Статус»)
    const hidden = statusFilterHidden('xui', XUI_STATUS_FILTERS);
    return !hidden.size || !hidden.has(xuiFilterKey(s));
  }).map(s => {
    // Установленный доступный сервис → клик по строке открывает карточку
    // (этап 4); прочие строки (не установлен / заблокирован) статичны.
    const blocked = serviceBlocked(s);
    const clickable = (s.status || {}).installed && !blocked;
    const cls = clickable ? 'server-table-row' : 'server-table-row wg-row-static';
    const attr = clickable ? ` data-xui-srv="${esc(s.id)}" title="Открыть карточку сервиса"` : '';
    return `<tr class="${cls}"${attr}>${xuiRowCells(s)}</tr>`;
  }).join('');
  // Класс wg-server-table включает готовую мобильную раскладку (карточками)
  // и мобильные твики ячеек — общие css не трогаем, паттерн WG переиспользуем.
  el.innerHTML = `<div class="server-table-wrap">
    <table class="server-table wg-server-table">
      <thead><tr>
        ${xuiSortHeader('name', 'Имя сервера')}
        ${xuiSortHeader('status', 'Статус', statusFilterBtn('xui'))}
        ${xuiSortHeader('version', 'Версия')}
        ${xuiPanelHeader()}
      </tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="wg-empty-row">${statusFilterHidden('xui', XUI_STATUS_FILTERS).size ? 'Все серверы скрыты фильтром статуса' : 'Нет серверов'}</td></tr>`}</tbody>
    </table>
  </div>`;
  bindStatusFilter('xui', XUI_STATUS_FILTERS, () => loadXui());
}

function bindXuiServersList() {
  const el = document.getElementById('xui-servers');
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';
  // Лёгкие пробы доступности идут фоном, пока панель открыта (SSE);
  // при смене online/offline или SSH-порта перечитываем список.
  window.addEventListener('bot4vps:availability-changed', () => {
    if (document.getElementById('page-xui')?.classList.contains('on')) loadXui();
  });
  el.addEventListener('click', async event => {
    const sortBtn = event.target.closest('[data-xui-sort]');
    if (sortBtn) {
      event.preventDefault();
      event.stopPropagation();
      const key = sortBtn.dataset.xuiSort;
      if (xuiSort.key === key) {
        xuiSort = { key, descending: !xuiSort.descending };
      } else {
        // Версия: descending=false = от свежей к старой (дефолт первого клика)
        xuiSort = { key, descending: false };
      }
      renderXuiServers();
      return;
    }
    const reveal = event.target.closest('[data-xui-url-reveal]');
    if (reveal) {
      event.preventDefault();
      event.stopPropagation();
      xuiUrlRevealed.add(reveal.dataset.xuiUrlReveal);
      renderXuiServers();
      return;
    }
    // глаз в заголовке: показать/скрыть адреса всех панелей
    const visToggle = event.target.closest('[data-xui-url-visibility-toggle]');
    if (visToggle) {
      event.preventDefault();
      event.stopPropagation();
      xuiRevealAllUrls = !xuiRevealAllUrls;
      if (!xuiRevealAllUrls) xuiUrlRevealed.clear();
      renderXuiServers();
      return;
    }
    // обратное скрытие: клик по показанному адресу
    const hide = event.target.closest('[data-xui-url-hide]');
    if (hide) {
      event.preventDefault();
      event.stopPropagation();
      xuiUrlRevealed.delete(hide.dataset.xuiUrlHide);
      renderXuiServers();
      return;
    }
    const copy = event.target.closest('[data-xui-url-copy]');
    if (copy) {
      event.preventDefault();
      event.stopPropagation();
      const st = (statusMap[copy.dataset.xuiUrlCopy] || {}).status || {};
      copyText(String(st.panel_url || ''), copy);
      return;
    }
    // «Перейти ↗» — открыть панель в новой вкладке, не заходя в карточку
    const open = event.target.closest('[data-xui-open]');
    if (open) {
      event.preventDefault();
      event.stopPropagation();
      const url = String(open.dataset.xuiUrl || '').trim();
      if (url) window.open(url, '_blank', 'noopener');
      return;
    }
    const install = event.target.closest('[data-install]');
    if (install) {
      event.preventDefault();
      event.stopPropagation();
      openInstallWizard(install.dataset.install);
      return;
    }
    // клик по строке установленного сервиса → карточка
    const row = event.target.closest('[data-xui-srv]');
    if (row) {
      event.preventDefault();
      openXuiServer(row.dataset.xuiSrv);
    }
  });
}

// ---------------- визард установки ----------------

function wizardShell(serverName) {
  // Модалка визарда живёт в JS (общий index.html не разрастаем).
  let bg = document.getElementById('xui-install-modal');
  if (bg) bg.remove();
  bg = document.createElement('div');
  bg.className = 'modal-bg open';
  bg.id = 'xui-install-modal';
  bg.innerHTML = `
  <div class="modal" style="width:min(680px,100%)">
    <div class="section-head" style="margin-bottom:.6rem">
      <h3 style="margin:0">Установка 3x-ui — <span id="xui-wiz-server">${esc(serverName)}</span></h3>
      <button type="button" id="xui-wiz-bg" class="hidden" title="Свернуть окно: установка продолжится в фоне, уведомлю по завершении"
              style="padding:.2rem .55rem;font-size:.78rem">в фон ↓</button>
    </div>
    <div class="tabs-hint" id="xui-wiz-steptitle" style="margin:0 0 .6rem"></div>
    <div id="xui-wiz-step1"></div>
    <div id="xui-wiz-step2" class="hidden"></div>
    <div id="xui-wiz-step3" class="hidden"></div>
    <div id="xui-wiz-progress" class="hidden"></div>
    <div id="xui-wiz-final" class="hidden"></div>
    <div class="err-hint" id="xui-wiz-warn" style="white-space:pre-wrap;color:var(--err);font-size:.78rem"></div>
    <div class="actions" style="margin-top:.8rem;justify-content:space-between" id="xui-wiz-actions"></div>
  </div>`;
  document.body.appendChild(bg);
  // Клик мимо окна НЕ закрывает визард: случайный клик по затемнению
  // посреди установки не должен терять прогресс. Закрытие — кнопками
  // в подвале шага или Escape.
  bg.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); closeWizard(); }
  });
  return bg;
}

function closeWizard() {
  const bg = document.getElementById('xui-install-modal');
  if (bg) bg.remove();
  wizardCtx = null;
}

function warn(text) {
  const el = document.getElementById('xui-wiz-warn');
  if (el) el.textContent = text || '';
}

function showStep(n) {
  ['step1', 'step2', 'step3', 'progress', 'final'].forEach(k => {
    document.getElementById(`xui-wiz-${k}`)?.classList.toggle('hidden', k !== n);
  });
}

function setActions(buttons) {
  const box = document.getElementById('xui-wiz-actions');
  box.innerHTML = '';
  buttons.forEach(({ label, cls = 'secondary', onclick, disabled }) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = label;
    if (disabled) b.disabled = true;
    b.onclick = onclick;
    box.appendChild(b);
  });
}

const STEP_TITLES = {
  step1: 'Шаг 1 из 3 · Доступ — логин, пароль, порт и путь панели',
  step2: 'Шаг 2 из 3 · SSL — как панель будет доступна извне',
  step3: 'Шаг 3 из 3 · Превью — версия и источник артефакта',
};

function renderStep1() {
  document.getElementById('xui-wiz-steptitle').textContent = STEP_TITLES.step1;
  const box = document.getElementById('xui-wiz-step1');
  box.innerHTML = `
    <label class="row">Логин</label>
    <div class="actions" style="margin:0 0 .4rem;display:flex;gap:.4rem">
      <input id="xui-f-username" autocomplete="off" style="flex:1"/>
    </div>
    <label class="row">Пароль <span class="hint">генерируется, можно ввести свой</span></label>
    <div class="actions" style="margin:0 0 .4rem;display:flex;gap:.4rem">
      <input id="xui-f-password" autocomplete="off" style="flex:1"/>
      <button type="button" class="secondary" id="xui-f-passregen" title="Перегенерировать">🎲</button>
    </div>
    <div class="tabs-hint" style="margin:0 0 .6rem">Минимум 8 символов.</div>
    <label class="row">Порт панели <span class="hint">80 занят под выпуск сертификата</span></label>
    <div class="actions" style="margin:0 0 .4rem;display:flex;gap:.4rem">
      <input id="xui-f-port" inputmode="numeric" style="flex:1"/>
      <button type="button" class="secondary" id="xui-f-portregen" title="Случайный порт">🎲</button>
    </div>
    <label class="row">Web base path <span class="hint">путь в URL панели после порта</span></label>
    <div class="actions" style="margin:0 0 .2rem;display:flex;gap:.4rem">
      <input id="xui-f-path" autocomplete="off" style="flex:1"/>
      <button type="button" class="secondary" id="xui-f-pathregen" title="Случайный путь">🎲</button>
    </div>
    <div class="tabs-hint" style="margin:0">4-64 символа, латиница, цифры, дефис и подчёркивание. Адрес панели: http(s)://host:порт/этот-путь</div>`;
  box.querySelector('#xui-f-username').value = 'admin';
  box.querySelector('#xui-f-password').value = genPassword();
  box.querySelector('#xui-f-port').value = genPort();
  box.querySelector('#xui-f-path').value = genPath();
  box.querySelector('#xui-f-passregen').onclick = () => {
    box.querySelector('#xui-f-password').value = genPassword();
  };
  box.querySelector('#xui-f-portregen').onclick = () => {
    box.querySelector('#xui-f-port').value = genPort();
  };
  box.querySelector('#xui-f-pathregen').onclick = () => {
    box.querySelector('#xui-f-path').value = genPath();
  };
  // Возврат «← Назад» со 2-го шага: введённые значения НЕ перегенерируем —
  // восстанавливаем то, что пользователь оставил (генераторы только при
  // первом открытии визарда).
  const saved = wizardCtx?.step1;
  if (saved) {
    if (saved.username) box.querySelector('#xui-f-username').value = saved.username;
    if (saved.password) box.querySelector('#xui-f-password').value = saved.password;
    if (saved.port) box.querySelector('#xui-f-port').value = saved.port;
    if (saved.web_base_path) box.querySelector('#xui-f-path').value = saved.web_base_path;
  }
  showStep('step1');
  warn('');
  setActions([
    { label: 'Отмена', onclick: closeWizard },
    { label: 'Далее →', cls: '', onclick: () => {
      if (!validateStep1()) return;
      wizardCtx.step1 = step1Values();  // запомнить перед уходом
      renderStep2();
    } },
  ]);
}

function step1Values() {
  return {
    username: document.getElementById('xui-f-username')?.value.trim(),
    password: document.getElementById('xui-f-password')?.value,
    port: document.getElementById('xui-f-port')?.value.trim(),
    web_base_path: document.getElementById('xui-f-path')?.value.trim(),
  };
}

// Мгновенная подсказка (авторитет — бэкенд):
const RE_USER = /^[A-Za-z0-9_.-]{3,32}$/;
const RE_PATH = /^[A-Za-z0-9_-]{4,64}$/;
const RE_DOMAIN = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$/;

function validateStep1() {
  const v = step1Values();
  if (!RE_USER.test(v.username || '')) { warn('Логин: 3-32 симв., латиница/цифры/._-'); return false; }
  if ((v.password || '').length < 8) { warn('Пароль: минимум 8 символов'); return false; }
  const port = Number(v.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) { warn('Порт: целое число 1-65535'); return false; }
  if (port === 80) { warn('Порт 80 зарезервирован под выпуск сертификата'); return false; }
  if (!RE_PATH.test(v.web_base_path || '')) { warn('Web base path: 4-64 симв., латиница, цифры, дефис и подчёркивание'); return false; }
  warn('');
  return true;
}

function renderStep2() {
  document.getElementById('xui-wiz-steptitle').textContent = STEP_TITLES.step2;
  const box = document.getElementById('xui-wiz-step2');
  const host = wizardCtx?.host || '';
  box.innerHTML = `
    <label class="row"><input type="radio" name="xui-ssl" value="domain" checked/>&nbsp;Let's Encrypt — домен
      <span class="hint">90 дней, автопродление; нужен порт 80</span></label>
    <div id="xui-ssl-domain-box" style="margin:.3rem 0 .6rem .2rem">
      <input id="xui-f-domain" placeholder="panel.example.com" autocomplete="off"/>
    </div>
    <label class="row"><input type="radio" name="xui-ssl" value="ip"/>&nbsp;Let's Encrypt — IP
      <span class="hint">~6 дней, автопродление; нужен порт 80</span></label>
    <div id="xui-ssl-ip-box" class="hidden" style="margin:.3rem 0 .6rem .2rem">
      <div class="tabs-hint" style="margin:0 0 .3rem">Сертификат будет выпущен для <b>${esc(host)}</b></div>
      <input id="xui-f-ipv6" placeholder="IPv6 (необязательно, напр. 2001:db8::1)" autocomplete="off"/>
    </div>
    <label class="row"><input type="radio" name="xui-ssl" value="custom"/>&nbsp;Свой сертификат
      <span class="hint">пути до файлов на сервере</span></label>
    <div id="xui-ssl-custom-box" class="hidden" style="margin:.3rem 0 .6rem .2rem">
      <input id="xui-f-certdomain" placeholder="Домен, на который выпущен сертификат" autocomplete="off"/>
      <input id="xui-f-certfile" placeholder="Путь к fullchain (.crt/.pem) на сервере" autocomplete="off" style="margin-top:.4rem"/>
      <input id="xui-f-keyfile" placeholder="Путь к приватному ключу (.key) на сервере" autocomplete="off" style="margin-top:.4rem"/>
    </div>
    <label class="row"><input type="radio" name="xui-ssl" value="none"/>&nbsp;Без SSL
      <span class="hint">reverse proxy или SSH-туннель</span></label>
    <div id="xui-ssl-none-box" class="hidden" style="margin:.3rem 0 .2rem .2rem">
      <div class="err-hint" style="margin:0 0 .4rem;color:var(--err);font-size:.78rem">Панель будет на HTTP: логин и пароль ходят открытым текстом. Безопасно только за reverse proxy (nginx/Caddy) или по SSH-туннелю.</div>
      <label><input type="checkbox" id="xui-f-bindlocal"/>&nbsp;Слушать только 127.0.0.1 (доступ через туннель ssh -L)</label>
    </div>`;
  const radios = box.querySelectorAll('input[name=xui-ssl]');
  const sync = () => {
    const mode = box.querySelector('input[name=xui-ssl]:checked')?.value;
    box.querySelector('#xui-ssl-domain-box').classList.toggle('hidden', mode !== 'domain');
    box.querySelector('#xui-ssl-ip-box').classList.toggle('hidden', mode !== 'ip');
    box.querySelector('#xui-ssl-custom-box').classList.toggle('hidden', mode !== 'custom');
    box.querySelector('#xui-ssl-none-box').classList.toggle('hidden', mode !== 'none');
    warn('');
  };
  radios.forEach(r => r.onchange = sync);
  // Возврат «← Назад» с 3-го шага: восстановить выбор SSL-режима и поля —
  // рендер пересоздаёт DOM, без восстановления радио сбрасывается на domain.
  const saved = wizardCtx?.step2;
  if (saved) {
    const r = box.querySelector(`input[name=xui-ssl][value="${saved.ssl_mode}"]`);
    if (r) r.checked = true;
    if (saved.domain) {
      const domainInput = saved.ssl_mode === 'custom'
        ? box.querySelector('#xui-f-certdomain') : box.querySelector('#xui-f-domain');
      if (domainInput) domainInput.value = saved.domain;
    }
    if (saved.ipv6) {
      const ipv6 = box.querySelector('#xui-f-ipv6');
      if (ipv6) ipv6.value = saved.ipv6;
    }
    if (saved.cert_file) {
      const el = box.querySelector('#xui-f-certfile');
      if (el) el.value = saved.cert_file;
    }
    if (saved.key_file) {
      const el = box.querySelector('#xui-f-keyfile');
      if (el) el.value = saved.key_file;
    }
    if (saved.ssl_mode === 'none') {
      box.querySelector('#xui-f-bindlocal').checked = !!saved.bind_local;
    }
  }
  sync();
  showStep('step2');
  setActions([
    { label: '← Назад', onclick: renderStep1 },
    { label: 'Далее →', cls: '', onclick: () => {
      if (!validateStep2()) return;
      wizardCtx.step2 = step2Values();  // запомнить перед уходом
      renderStep3();
    } },
  ]);
}

function step2Values() {
  const mode = document.querySelector('#xui-wiz-step2 input[name=xui-ssl]:checked')?.value || 'none';
  const v = { ssl_mode: mode };
  if (mode === 'domain') v.domain = document.getElementById('xui-f-domain')?.value.trim();
  if (mode === 'ip') v.ipv6 = document.getElementById('xui-f-ipv6')?.value.trim() || undefined;
  if (mode === 'custom') {
    v.domain = document.getElementById('xui-f-certdomain')?.value.trim();
    v.cert_file = document.getElementById('xui-f-certfile')?.value.trim();
    v.key_file = document.getElementById('xui-f-keyfile')?.value.trim();
  }
  if (mode === 'none') v.bind_local = !!document.getElementById('xui-f-bindlocal')?.checked;
  return v;
}

function validateStep2() {
  const v = step2Values();
  if (v.ssl_mode === 'domain' && !RE_DOMAIN.test(v.domain || '')) {
    warn('Домен: например panel.example.com'); return false;
  }
  if (v.ssl_mode === 'custom') {
    if (!RE_DOMAIN.test(v.domain || '')) { warn('Укажите домен, на который выпущен сертификат'); return false; }
    if (!(v.cert_file || '').startsWith('/')) { warn('Путь к сертификату: абсолютный путь от /'); return false; }
    if (!(v.key_file || '').startsWith('/')) { warn('Путь к ключу: абсолютный путь от /'); return false; }
  }
  warn('');
  return true;
}

const SOURCE_LABELS = {
  github: 'GitHub — на сервере свежее, качает сам сервер',
  push: 'Локальный кэш Bot4VPS — быстрый scp, без GitHub',
  push_fallback: 'Кэш Bot4VPS (fallback после недоступности GitHub)',
};

async function renderStep3() {
  document.getElementById('xui-wiz-steptitle').textContent = STEP_TITLES.step3;
  const box = document.getElementById('xui-wiz-step3');
  box.innerHTML = '<div class="empty">Определяю версию и источник…</div>';
  showStep('step3');
  setActions([{ label: '← Назад', onclick: renderStep2 }]);
  try {
    const r = await j(`${srvBase(wizardCtx.serverId)}/resolve-source`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: { arch: wizardCtx.arch } }),
    });
    wizardCtx.resolve = r;
    const v = { ...step1Values(), ...step2Values() };
    const rows = [
      ['Версия', r.tag || '—'],
      ['Источник', SOURCE_LABELS[r.source] || r.source || '—'],
      ['Архитектура', r.arch + (r.arch_match === false
        ? ' (не совпадает с дефолтом Bot4VPS — GitHub; эта arch пойдёт в кэш)' : '')],
      ['Порт', v.port],
      ['Web base path', '/' + v.web_base_path],
      ['SSL', { domain: `Let's Encrypt: ${v.domain}`,
                ip: `Let's Encrypt IP${v.ipv6 ? ` + ${v.ipv6}` : ''}`,
                custom: `свой сертификат (${v.domain})`,
                none: v.bind_local ? 'без SSL, слушает 127.0.0.1' : 'без SSL' }[v.ssl_mode]],
    ];
    const notes = [];
    if (r.cache_stale) notes.push('GitHub недоступен — свежесть кэша не проверена');
    if (r.fallback_tag) notes.push(`Fallback при сбое GitHub: кэш ${r.fallback_tag}`);
    if (r.latest_error) notes.push(`GitHub: ${r.latest_error}`);
    box.innerHTML = `
      <table style="width:100%;border-collapse:collapse">
        ${rows.map(([k, val]) =>
          `<tr><td class="hint" style="padding:.2rem .6rem .2rem 0;white-space:nowrap">${esc(k)}</td>
              <td style="padding:.2rem 0">${esc(String(val))}</td></tr>`).join('')}
      </table>
      ${notes.length ? `<div class="wg-note" style="margin:.5rem 0 0">${notes.map(esc).join('<br/>')}</div>` : ''}`;
    warn('');
    setActions([
      { label: '← Назад', onclick: renderStep2 },
      { label: 'Установить', cls: '', onclick: startInstall },
    ]);
  } catch (e) {
    box.innerHTML = '';
    warn(`Не удалось определить источник: ${e.message}`);
    setActions([{ label: '← Назад', onclick: renderStep2 }]);
  }
}

// ---------------- установка: прогресс → финал ----------------

async function startInstall() {
  const v = { ...step1Values(), ...step2Values(), arch: wizardCtx.arch };
  document.getElementById('xui-wiz-steptitle').textContent =
    'Установка — это может занять несколько минут';
  showStep('progress');
  warn('');
  setActions([]);  // во время установки управление — кнопкой «в фон» и Escape
  // «в фон»: свернуть окно, установка продолжается (поллинг жив, пока
  // открыта вкладка), по завершении — тост; таблица обновится сама.
  const bgBtn = document.getElementById('xui-wiz-bg');
  bgBtn.classList.remove('hidden');
  bgBtn.onclick = () => { wizardCtx.background = true; closeWizard(); };
  try {
    const sid = wizardCtx.serverId;
    const r = await j(`${srvBase(sid)}/enqueue/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params: v }),
    });
    if (r.task) watchInstallTask(r.task.id, v, sid);
    else throw new Error(r.error || 'очередь не вернула задачу');
  } catch (e) {
    warn(`Не удалось запустить установку: ${e.message}`);
    setActions([{ label: '← Назад', onclick: renderStep3 }]);
  }
}

function watchInstallTask(taskId, params, serverId) {
  const log = document.getElementById('xui-wiz-progress');
  log.innerHTML = '<div class="empty">Ожидание очереди…</div>';
  const tick = async () => {
    let t;
    try { t = await j('/api/tasks/' + encodeURIComponent(taskId)); }
    catch (e) { return; }
    // Окно свернуто «в фон» — поллинг жив, результат приедет тостом.
    // Статусы task_manager: queued/running/success/success_warn/
    // failed/cancelled («done» не существует — раньше финал не рендерился).
    const ok = t.status === 'success' || t.status === 'success_warn';
    if (!document.getElementById('xui-install-modal')) {
      const done = ok || t.status === 'failed' || t.status === 'cancelled';
      if (done) {
        clearInterval(xuiTimers[taskId]); delete xuiTimers[taskId];
        const err = t.result?.error || t.error;
        toast(ok
          ? '3x-ui установлен — креды в карточке сервиса'
          : `Установка не удалась${err ? `: ${err}` : ''}`, ok);
        loadXui();
        // Кнопка «Быстрых действий» в карточке сервера зависит от статуса
        // сервиса — обновляем её (как install-хуки Docker/WG).
        if (ok && serverId) window.refreshAfterServiceChange?.(serverId);
      }
      return;
    }
    const head = `${esc(t.emoji || '')} ${esc(t.name || '')} · ${esc(t.status || '')} · ${esc(t.duration || '')}`;
    const lines = t.output_lines || [];
    const body = lines.length
      ? lines.map(ansiToHtml).join('\n')
      : ansiToHtml(t.result?.output || t.result?.error || t.error || '(нет вывода)');
    log.innerHTML = `<div class="tasklog-head">${head}</div>
      <div class="logbox" style="max-height:40vh">${body}</div>`;
    // Stick-to-bottom: прилипает к низу, только пока пользователь не уехал
    // вверх сам; вернулся к низу (или новый логбокс) — прилипание снова
    // включено. Свободная прокрутка вверх не дёргается новыми строками.
    const box = log.querySelector('.logbox');
    if (box) {
      const stick = box.__stick !== false;
      box.onscroll = () => {
        box.__stick = box.scrollHeight - box.scrollTop - box.clientHeight < 4;
      };
      if (stick) box.scrollTop = box.scrollHeight;
    }
    const done = ok || t.status === 'failed' || t.status === 'cancelled';
    if (!done) return;
    clearInterval(xuiTimers[taskId]); delete xuiTimers[taskId];
    // Финал: кнопки «в фон» больше не нужно, управление — «Закрыть»
    document.getElementById('xui-wiz-bg')?.classList.add('hidden');
    if (ok) {
      renderFinal(params);
      if (serverId) window.refreshAfterServiceChange?.(serverId);
    }
    else {
      // Провал любой глубины — окно остаётся: в нём live-лог и причина
      // (пользователь смотрит установку прямо в модалке).
      document.getElementById('xui-wiz-steptitle').textContent =
        'Установка не удалась';
      warn(t.result?.error || t.error || 'Задача завершена с ошибкой');
      setActions([{ label: 'Закрыть', onclick: closeWizard }]);
      loadXui();
    }
  };
  xuiTimers[taskId] = setInterval(tick, 1500);
  tick();
}

async function renderFinal(params) {
  document.getElementById('xui-wiz-steptitle').textContent =
    'Готово — 3x-ui установлен';
  const box = document.getElementById('xui-wiz-final');
  showStep('final');
  let res = {};
  try {
    const r = await j(`${srvBase(wizardCtx.serverId)}/install-result`);
    res = r || {};
  } catch (e) { /* финал покажет то, что есть */ }
  const url = res.panel_url || '';
  const values = {
    'xui-copy-url': url,
    'xui-copy-user': res.username || '',
    'xui-copy-pass': res.password || '',
    'xui-copy-token': res.api_token || '',
  };
  const row = (label, copyId) => values[copyId] ? `
    <tr>
      <td class="hint" style="padding:.3rem .8rem .3rem 0;white-space:nowrap">${label}</td>
      <td id="${copyId}" style="padding:.3rem .6rem .3rem 0;font-family:monospace;word-break:break-all">
        ${esc(values[copyId])}
      </td>
      <td style="padding:.3rem 0">
        <button type="button" class="secondary" data-copy="${copyId}" title="Скопировать">⧉</button>
      </td>
    </tr>` : '';
  box.innerHTML = `
    <div class="wg-note" style="margin:0 0 .6rem">
      Сохраните данные доступа — они также лежат на сервере в
      /etc/x-ui/install-result.env (root 600). Логин и пароль можно сменить позже из карточки сервиса.<br/>
      Порт панели открыт в firewall сервера — панель доступна из интернета.
    </div>
    <table style="width:100%">
      ${row('Access URL', 'xui-copy-url')}
      ${row('Логин', 'xui-copy-user')}
      ${row('Пароль', 'xui-copy-pass')}
      ${row('API-токен', 'xui-copy-token')}
    </table>
    ${!res.creds_present ? '<div class="err-hint">Креды недоступны: панель могла не успеть подняться — синхронизируйте позже.</div>' : ''}`;
  box.querySelectorAll('[data-copy]').forEach(b => {
    b.onclick = () => copyText(values[b.dataset.copy] || '', b);
  });
  setActions([
    { label: 'Закрыть', onclick: () => { closeWizard(); loadXui(); } },
    url ? { label: 'Открыть панель ↗', cls: '', onclick: () => window.open(url, '_blank', 'noopener') } : null,
  ].filter(Boolean));
  loadXui();
}

function copyText(text, btn) {
  const done = () => {
    toast('Скопировано', true);
    if (btn) {
      btn.classList.add('copied');
      setTimeout(() => btn.classList.remove('copied'), 1200);
    }
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  } else fallbackCopy(text, done);
}

function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); done(); } catch (_) { toast('Не удалось скопировать', false); }
  ta.remove();
}

// ---------------- карточка сервиса (этап 4) ----------------
//
// Скелет — паттерн WG-карточки (back-кнопки, badge, live-poll 3с, restore
// из localStorage), наполнение — домен 3x-ui: панель/креды, systemd-юнит,
// аккаунт (x-ui setting), BBR и geo-файлы. Быстрые действия идут через
// POST /action/{action} (card_* контракт бэка), удаление — через очередь.

async function openXuiServer(id, opts = {}) {
  bindXuiCardUI();  // при restore сессии loadXui мог ещё не выполниться
  xuiServerId = id;
  xuiEntryContext = opts.from === 'server' ? 'server' : 'list';
  xuiCardState = null;
  try {
    localStorage.setItem('bot4vps_page', 'xui-server');
    localStorage.setItem('bot4vps_xui_server_id', id);
  } catch (_) {}
  // Иконка в h1 живёт отдельно — текст пишем в span, чтобы не затирать SVG.
  const titleEl = document.querySelector('#xui-srv-title .srv-title-name');
  if (titleEl) titleEl.textContent = '3x-ui · ' + nameOf(id);
  // Вход со страницы сервера: списка ещё нет в statusMap — подтянем фоном
  // (нужно для заголовка и возврата «К списку»).
  if (!statusMap[id]) loadXui().catch(() => {});
  document.getElementById('xui-srv-body').innerHTML = '<div class="empty">Загрузка…</div>';
  showPage('xui-server');
  await loadXuiServerDetail(id);
  startXuiLivePoll(id);
}

function backToXuiList() {
  stopXuiLivePoll();
  xuiServerId = null;
  xuiCardState = null;
  xuiEntryContext = 'list';
  try {
    localStorage.setItem('bot4vps_page', 'xui');
    localStorage.removeItem('bot4vps_xui_server_id');
  } catch (_) {}
  showPage('xui');
  loadXui();
}

function startXuiLivePoll(id) {
  stopXuiLivePoll();
  xuiLiveTimer = setInterval(() => {
    if (xuiServerId !== id) { stopXuiLivePoll(); return; }
    // не конкурируем с первым live-снимком после мутации
    if (xuiMutationRefreshPending || document.querySelector('.modal-bg.open')) return;
    loadXuiServerDetail(id).catch(() => {});
  }, 3000);
}
function stopXuiLivePoll() {
  if (xuiLiveTimer) { clearInterval(xuiLiveTimer); xuiLiveTimer = null; }
}

let xuiStateSeq = 0;  // порядок /state-запросов: опоздавший ответ не затирает свежий
let xuiStateInFlight = null;
let xuiMutationRefreshSeq = 0;

function loadXuiServerDetail(id, { force = false } = {}) {
  if (!force && xuiStateInFlight?.id === id) return xuiStateInFlight.promise;
  const seq = ++xuiStateSeq;
  const promise = (async () => {
    try {
      const d = await j(`${srvBase(id)}/state`);
      // Ответ мог опоздать: карточку уже сменили (test↔fin при сравнении) или
      // закрыли, ИЛИ параллельный запрос вернулся раньше (медленный SSH:
      // ответ, начатый до операции, приходил после свежего и затирал его
      // старыми данными — бейдж «прыгал»). Рендерим только последний.
      if (id !== xuiServerId || seq !== xuiStateSeq) return;
      xuiCardState = d.state || {};
      renderXuiServerDetail(xuiCardState);
    } catch (e) {
      if (id !== xuiServerId || seq !== xuiStateSeq) return;
      document.getElementById('xui-srv-body').innerHTML =
        `<div class="empty">${esc(e.message || e)}</div>`;
    }
  })();
  xuiStateInFlight = { id, promise };
  promise.finally(() => {
    if (xuiStateInFlight?.promise === promise) xuiStateInFlight = null;
  });
  return promise;
}
function refreshXuiServerDetailAfterMutation(id = xuiServerId) {
  if (!id || id !== xuiServerId
      || !document.getElementById('page-xui-server')?.classList.contains('on')) {
    return Promise.resolve();
  }
  const refreshSeq = ++xuiMutationRefreshSeq;
  xuiMutationRefreshPending = true;
  const firstRefresh = loadXuiServerDetail(id, { force: true });
  const finishRefresh = () => {
    if (refreshSeq === xuiMutationRefreshSeq) xuiMutationRefreshPending = false;
  };
  // Быстрые sysctl-изменения уже видны в ответе action; restart/выдача
  // сертификата может стать видимой чуть позже. Одно повторное live-чтение
  // не заставляет пользователя обновлять страницу вручную.
  setTimeout(() => {
    if (id === xuiServerId
        && document.getElementById('page-xui-server')?.classList.contains('on')) {
      loadXuiServerDetail(id).finally(finishRefresh);
    } else {
      finishRefresh();
    }
  }, 1000);
  return firstRefresh;
}

/** «осталось N дней» для бейджа сертификата: дата 'YYYY-MM-DD' от openssl.
 *  Просрочен/сегодня → '0 дней'; не разобралась — пусто (показываем только дату). */
function daysLeft(dateStr) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || '').trim());
  if (!m) return '';
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const days = Math.floor((d - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  if (days < 0) return '0 дней';
  const mod10 = days % 10, mod100 = days % 100;
  const word = mod10 === 1 && mod100 !== 11 ? 'день'
    : (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) ? 'дня' : 'дней';
  return `${days} ${word}`;
}

/** Кнопка-копия в info-row (классы те же, что в карточке WG). */
const iconCopy = val => (val == null || val === '' ? '' :
  ` <button type="button" class="icon-copy" data-copy="${esc(String(val))}" title="Копировать">⧉</button>`);

function renderXuiServerDetail(st) {
  const body = document.getElementById('xui-srv-body');
  if (!body) return;
  const s = st || {};
  const bbr = s.bbr || {};
  const geo = s.geo || {};

  const badgeEl = document.getElementById('xui-srv-badge');
  if (badgeEl) {
    badgeEl.innerHTML = s.installed
      ? (s.active
        ? '<span class="badge on">Установлен · активен</span>'
        : '<span class="badge off">Установлен · остановлен</span>')
      : '<span class="badge off">Не установлен</span>';
  }
  const titleEl = document.querySelector('#xui-srv-title .srv-title-name');
  if (titleEl && xuiServerId) titleEl.textContent = '3x-ui · ' + nameOf(xuiServerId);

  if (!s.installed) {
    body.innerHTML = `<div class="empty">3x-ui на этом сервере не установлен<br><br>
      <button type="button" class="wg-row-action" data-xui-install>🟢 Установить</button></div>`;
    return;
  }

  const url = String(s.panel_url || '').trim();
  const statusHtml = s.active
    ? '<span class="ssh-dot ok"></span> Активен'
    : '<span class="ssh-dot err"></span> Остановлен';
  const path = String(s.web_base_path || '').replace(/^\/+|\/+$/g, '');
  const row = (label, value) =>
    `<div class="info-row"><span class="info-label">${label}</span><span class="info-value">${value}</span></div>`;

  // -- Панель: адрес и параметры доступа самой панели 3x-ui --------------
  const panelCard = `
    <div class="info-block svc-card">
      <h2>Панель</h2>
      ${row('Статус', statusHtml)}
      ${row('Версия', esc(s.version || '—'))}
      ${row('Порт', s.port != null ? `<span class="mono">${esc(String(s.port))}</span>${iconCopy(s.port)}` : '—')}
      ${row('Web base path', path ? `<span class="mono">/${esc(path)}</span>${iconCopy(path)}` : '/')}
      <div class="info-row xui-url-row">
        <span class="info-label">Access URL</span>
        <span class="info-value">
          ${url
            ? `<span class="mono" style="word-break:break-all">${esc(url)}</span>${iconCopy(url)}
               <button type="button" class="secondary" data-xui-go="${esc(url)}">Перейти ↗</button>`
            : '—'}
        </span>
      </div>
    </div>`;

  // Креды панели (логин/пароль/API-токен) на карточке не показываем —
  // как в CLI x-ui: старые не смотрим и не спрашиваем, смена = задать
  // новый («Аккаунт панели»). Единственный показ — финал установки.

  // -- Сертификат: зеркало их CLI SSL-меню (x-ui.sh, опция 20) ----------
  const cert = s.cert || {};
  const certDomains = Object.entries(cert.domains || {});
  const anyCertDomain = certDomains.length || (cert.certbot_domains || []).length;
  const https = url.startsWith('https://');
  const certCard = `
    <div class="info-block svc-card xui-stack-card">
      <h2 class="xui-cert-head">Сертификат
        ${https
          ? `<span class="badge on">https${cert.panel_expires ? ' · до ' + esc(cert.panel_expires)
              + ' (осталось ' + daysLeft(cert.panel_expires) + ')' : ''}</span>`
          : '<span class="badge off">http</span>'}
      </h2>
      <button type="button" class="svc-action" data-xui-cert="issue_domain">
        <b>🔒 Выпустить Let's Encrypt</b><span>по домену — acme.sh или certbot, авто-renew, порт 80</span></button>
      <button type="button" class="svc-action" data-xui-cert="issue_ip"${certDomains.length && ('ip' in (cert.domains || {})) ? ' title="Сертификат для IP уже выпущен (/root/cert/ip)"' : ''}>
        <b>📍 Выпустить для IP</b><span>короткоживущий ~6 дней, обновляется сам</span></button>
      <button type="button" class="svc-action" data-xui-cert="renew"${anyCertDomain ? '' : ' disabled'}>
        <b>⟳ Продлить принудительно</b><span>${anyCertDomain ? 'перевыпуск выбранного домена' : 'нет выпущенных сертификатов'}</span></button>
      <button type="button" class="svc-action svc-action-warn" data-xui-cert="remove"${anyCertDomain ? '' : ' disabled'}>
        <b>✖ Отозвать и удалить</b><span>${anyCertDomain ? 'revoke в CA + файлы; сброс путей панели, если ссылались' : 'нет выпущенных сертификатов'}</span></button>
    </div>`;

  // -- Сервис: systemd-юнит x-ui (Xray — дочерний процесс) ---------------
  const serviceCard = `
    <div class="info-block svc-card">
      <h2>Сервис</h2>
      ${row('Автозагрузка', s.enabled
        ? '<span class="badge on">включена</span>'
        : '<span class="badge off">выключена</span>')}
      <div class="actions xui-svc-btns" style="margin:.2rem 0 0">
        <button type="button" class="secondary" data-xui-autostart title="Автозапуск юнита x-ui при загрузке сервера">${s.enabled ? '⏹ Выключить' : '▶ Включить'}</button>
        <button type="button" class="secondary" data-xui-unit="${s.active ? 'stop' : 'start'}">${s.active ? '⏹ Остановить' : '▶ Запустить'}</button>
        <button type="button" class="secondary" data-xui-unit="restart">⟳ Рестарт</button>
        <button type="button" class="secondary" data-xui-logs>📄 Логи</button>
        <button type="button" class="secondary" data-xui-update title="Проверить GitHub и обновить до последней версии">⬆ Обновить</button>
        <button type="button" class="secondary" data-xui-version title="Установить конкретную версию с GitHub (legacy CLI)">⬇ Другая версия</button>
      </div>
    </div>`;

  // -- Аккаунт панели: x-ui setting … -------------------------------------
  const accCard = `
    <div class="info-block svc-card xui-stack-card">
      <h2>Аккаунт панели</h2>
      <button type="button" class="svc-action" data-xui-acc="username">
        <b>Сменить логин</b><span>имя для входа в панель</span></button>
      <button type="button" class="svc-action" data-xui-acc="password">
        <b>Сменить пароль</b><span>новый пароль — генератор или свой</span></button>
      <button type="button" class="svc-action" data-xui-acc="port">
        <b>Сменить порт</b><span>порт, на котором слушает панель</span></button>
      <button type="button" class="svc-action" data-xui-acc="path">
        <b>Изменить web base path</b><span>свой путь или случайный — старые ссылки перестанут работать</span></button>
    </div>`;

  // -- Система: BBR и geo-файлы -------------------------------------------
  const geoRows = ['geoip.dat', 'geosite.dat'].map(name =>
    row(name, geo[name] ? `<span class="mono">${esc(geo[name])}</span>` : '<span class="hint">нет файла</span>')
  ).join('');
  const systemCard = `
    <div class="info-block svc-card">
      <h2>Система</h2>
      ${row('BBR', `${bbr.enabled
        ? '<span class="badge on">включён</span>'
        : '<span class="badge off">выключен</span>'}
        <button type="button" class="secondary" data-xui-bbr style="margin-left:.4rem">${bbr.enabled ? 'Отключить' : 'Включить'}</button>`)}
      ${geoRows}
      <button type="button" class="svc-action" data-xui-geo style="margin-top:.5rem">
        <b>⬇ Обновить geo-файлы</b><span>свежие geoip/geosite (Loyalsoldier) + рестарт панели</span></button>
    </div>`;

  const sideActions = `
    <div class="info-block svc-card svc-side-actions">
      <h2>Дополнительные действия</h2>
      <button type="button" class="svc-action" data-xui-db-export>
        <b>⬇ Экспорт базы данных</b><span>файл .db — резервная копия текущей базы на ваше устройство</span></button>
      <button type="button" class="svc-action" data-xui-db-import>
        <b>⬆ Импорт базы данных</b><span>загрузить резервную копию .db или миграционный дамп (.dump)</span></button>
      <button type="button" class="svc-action" data-xui-fakesite>
        <b>🌐 Сайт-заглушка (SelfSNI)</b><span>HTTPS-сайт для Reality Dest на 127.0.0.1:9000</span></button>
      <button type="button" class="svc-action svc-action-danger" data-xui-remove>
        <b>🗑 Удалить 3x-ui</b><span>бинарник, CLI и юнит</span></button>
    </div>`;

  body.innerHTML = `
    <div class="svc-main-grid">
      <div class="xui-srv-left">
        <div class="xui-srv-pair">${panelCard}${serviceCard}</div>
        <div class="xui-srv-pair">${accCard}${certCard}</div>
      </div>
      <div class="xui-srv-side">${systemCard}${sideActions}</div>
    </div>`;
}

/** Разовое подключение статичных элементов карточки (back/refresh) +
 *  делегирование кликов по телу — DOM пересоздаётся live-poll'ом. */
function bindXuiCardUI() {
  const body = document.getElementById('xui-srv-body');
  if (!body || body.dataset.bound) return;
  body.dataset.bound = '1';

  document.getElementById('btn-back-xui')?.addEventListener('click', backToXuiList);
  document.getElementById('btn-back-xui-server')?.addEventListener('click', async () => {
    if (!xuiServerId) return;
    try {
      const { openServer } = await import('./servers.js?v=20260915-sysfix-v2');
      await openServer(xuiServerId);
    } catch (e) {
      console.error('Не удалось открыть карточку сервера:', e);
      showPage('servers');
    }
  });

  body.addEventListener('click', async event => {
    const copy = event.target.closest('[data-copy]');
    if (copy) {
      event.preventDefault();
      copyText(copy.dataset.copy, copy);
      return;
    }
    const go = event.target.closest('[data-xui-go]');
    if (go) {
      event.preventDefault();
      const u = String(go.dataset.xuiGo || '').trim();
      if (u) window.open(u, '_blank', 'noopener');
      return;
    }
    const unit = event.target.closest('[data-xui-unit]');
    if (unit) { event.preventDefault(); unitAction(unit.dataset.xuiUnit); return; }
    const logs = event.target.closest('[data-xui-logs]');
    if (logs) { event.preventDefault(); openXuiLogs(); return; }
    const auto = event.target.closest('[data-xui-autostart]');
    if (auto) {
      event.preventDefault();
      cardAction('set_autostart', { enabled: !(xuiCardState || {}).enabled });
      return;
    }
    const acc = event.target.closest('[data-xui-acc]');
    if (acc) { event.preventDefault(); accAction(acc.dataset.xuiAcc); return; }
    const updBtn = event.target.closest('[data-xui-update]');
    if (updBtn) { event.preventDefault(); updateModal(); return; }
    const verBtn = event.target.closest('[data-xui-version]');
    if (verBtn) { event.preventDefault(); installVersionModal(); return; }
    const certBtn = event.target.closest('[data-xui-cert]');
    if (certBtn) { event.preventDefault(); certAction(certBtn.dataset.xuiCert); return; }
    const bbrBtn = event.target.closest('[data-xui-bbr]');
    if (bbrBtn) { event.preventDefault(); toggleBbr(); return; }
    const geoBtn = event.target.closest('[data-xui-geo]');
    if (geoBtn) { event.preventDefault(); updateGeoModal(); return; }
    const fakesite = event.target.closest('[data-xui-fakesite]');
    if (fakesite) { event.preventDefault(); fakesiteActionMenu(); return; }
    const rm = event.target.closest('[data-xui-remove]');
    if (rm) { event.preventDefault(); removeXuiModal(); return; }
    const dbExport = event.target.closest('[data-xui-db-export]');
    if (dbExport) { event.preventDefault(); exportDbModal(); return; }
    const dbImport = event.target.closest('[data-xui-db-import]');
    if (dbImport) { event.preventDefault(); importDbModal(); return; }
    const inst = event.target.closest('[data-xui-install]');
    if (inst) { event.preventDefault(); if (xuiServerId) openInstallWizard(xuiServerId); }
  });
}

// ---------------- быстрые действия (card_* контракт) ----------------

/** POST /action/{action}: быстрое действие без очереди. Один запрос в
 *  полёте (xuiCardBusy): сразу тост «команда отправлена», кнопки карточки
 *  блокируются до результата — по завершении тост с output и рефреш. */
const XUI_ACTION_TITLES = {
  unit_action: 'Команда юниту отправлена',
  set_autostart: 'Команда отправлена',
  set_bbr: 'Команда отправлена',
  update_geo: 'Команда отправлена',
  change_username: 'Команда отправлена',
  change_password: 'Команда отправлена',
  change_port: 'Команда отправлена',
  change_path: 'Команда отправлена',
};
async function cardAction(action, params = {}) {
  if (!xuiServerId || xuiCardBusy) return;
  xuiCardBusy = true;
  const card = document.getElementById('xui-srv-body');
  if (card) card.classList.add('xui-card-busy');  // кнопки неактивны до результата
  toast(XUI_ACTION_TITLES[action] || 'Команда отправлена', true);
  try {
    const r = await j(`${srvBase(xuiServerId)}/action/${encodeURIComponent(action)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params }),
    });
    if (r && r.output) toast(r.output, true);
    // разблокируем сразу по ответу действия — рефреш /state по SSH может
    // идти ещё ~10с (fin), кнопки не должны висеть всё это время;
    // карточку обновит этот же запрос в фоне + live-poll 3с
    xuiCardBusy = false;
    document.getElementById('xui-srv-body')?.classList.remove('xui-card-busy');
    if (r && r.status && xuiCardState) {
      // Router уже выполнил sync после quick-action; используем этот свежий
      // снимок сразу, не ждём следующего SSH /state-запроса.
      xuiCardState = r.status;
      renderXuiServerDetail(xuiCardState);
    } else if (action === 'set_bbr' && xuiCardState && r && r.cc) {
      xuiCardState = {
        ...xuiCardState,
        bbr: { cc: r.cc, qdisc: r.qdisc || null, enabled: r.cc === 'bbr', managed: r.cc === 'bbr' },
      };
      renderXuiServerDetail(xuiCardState);
    }
    refreshXuiServerDetailAfterMutation(xuiServerId);
  } catch (e) {
    toast(e.message || String(e), false);
    xuiCardBusy = false;
    const c = document.getElementById('xui-srv-body');
    if (c) c.classList.remove('xui-card-busy');
  }
}

async function unitAction(action) {
  if (action === 'stop') {
    const ok = await confirmAction({
      title: 'Остановить панель 3x-ui?',
      message: 'Панель и Xray перестанут отвечать; существующие подключения прокси оборвутся после рестарта клиентов. Запустить можно будет из карточки.',
      confirmText: 'Остановить', cancelText: 'Отмена',
    });
    if (!ok) return;
  }
  await cardAction('unit_action', { action });
}

async function toggleBbr() {
  const bbr = (xuiCardState || {}).bbr || {};
  const enable = !bbr.enabled;
  if (!enable && bbr.enabled && !bbr.managed) {
    // BBR включён вне Bot4VPS: откатывать нечем — честно предупреждаем
    const ok = await confirmAction({
      title: 'Отключить BBR?',
      message: 'BBR включён не через Bot4VPS — исходные значения неизвестны, вернём стандартные fq_cubic/cubic.',
      confirmText: 'Отключить', cancelText: 'Отмена',
    });
    if (ok) await cardAction('set_bbr', { enabled: false });
    return;
  }
  const ok = await confirmAction({
    title: enable ? 'Включить BBR?' : 'Отключить BBR?',
    message: enable
      ? 'Алгоритм контроля перегрузки TCP переключится на BBR (файл /etc/sysctl.d/99-bbr-x-ui.conf). Текущий алгоритм сохранится и вернётся при отключении.'
      : 'Вернуть алгоритм, который был до включения BBR (сохранён в конфиге Bot4VPS).',
    confirmText: enable ? 'Включить' : 'Отключить',
    cancelText: 'Отмена', danger: false,
  });
  if (ok) await cardAction('set_bbr', { enabled: enable });
}

// ---------------- модалки действий (JS, как визард установки) ---------

function openXuiModal({
  title,
  bodyHtml,
  okText = 'Применить',
  cancelText = 'Отмена',
  hideCancel = false,
  danger = false,
  bind = null,
  onOk,
}) {
  let bg = document.getElementById('xui-card-modal');
  if (bg) bg.remove();
  bg = document.createElement('div');
  bg.className = 'modal-bg open';
  bg.id = 'xui-card-modal';
  bg.innerHTML = `
  <div class="modal" style="width:min(520px,100%)">
    <div class="section-head" style="margin-bottom:.6rem"><h3 style="margin:0">${esc(title)}</h3></div>
    <div id="xui-card-modal-body">${bodyHtml}</div>
    <div class="err-hint" id="xui-card-modal-warn" style="color:var(--err);font-size:.78rem;white-space:pre-wrap"></div>
    <div class="actions confirm-modal-actions">
      <button type="button" class="${danger ? 'danger' : ''}" id="xui-card-modal-ok">${esc(okText)}</button>
      <button type="button" class="secondary" id="xui-card-modal-cancel"${hideCancel ? ' hidden' : ''}>${esc(cancelText)}</button>
    </div>
  </div>`;
  document.body.appendChild(bg);
  // Клик мимо окна и backdrop НЕ закрывают: ввод не теряется (как визард).
  const close = () => bg.remove();
  bg.querySelector('#xui-card-modal-cancel').onclick = close;
  bg.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  });
  bg.querySelector('#xui-card-modal-ok').onclick = () => { onOk(close); };
  if (bind) bind(bg);
  return bg;
}

const modalWarn = text => {
  const el = document.getElementById('xui-card-modal-warn');
  if (el) el.textContent = text || '';
};
const modalField = () => String(document.getElementById('xui-modal-field')?.value ?? '').trim();
const modalRestart = () => !!document.getElementById('xui-modal-restart')?.checked;

/** Чекбокс «рестартовать сейчас» — общий для действий аккаунта (x-ui
 *  применяет креды/порт только после рестарта панели). Чекбокс и подпись
 *  на одной строке (по центру строки), подсказка — отдельной строкой ниже
 *  (в одну flex-строку с двухстрочной подписью чекбокс «плавал»). */
const restartBox = (checked = true) => `
  <div class="xui-restart-box" style="margin:.6rem 0 0;display:grid;grid-template-columns:auto 1fr;column-gap:.45rem;align-items:center">
    <input type="checkbox" id="xui-modal-restart" style="grid-row:1"${checked ? ' checked' : ''}/>
    <label for="xui-modal-restart" style="grid-row:1;grid-column:2;font-size:.82rem;cursor:pointer;margin:0">Рестартовать панель сейчас</label>
    <div class="hint" style="grid-row:2;grid-column:2;margin:0;font-size:.72rem;line-height:1.4;color:var(--text-muted)">иначе изменения применятся после следующего рестарта панели</div>
  </div>`;

function accAction(kind) {
  const st = xuiCardState || {};
  if (kind === 'username') {
    openXuiModal({
      title: 'Смена логина панели',
      bodyHtml: `
        <label class="row">Новый логин</label>
        <input id="xui-modal-field" autocomplete="off" style="width:100%"/>
        <div class="tabs-hint" style="margin:.3rem 0 0">3-32 символа, латиница/цифры/точка/дефис/подчёркивание</div>
        ${restartBox()}`,
      okText: 'Сменить логин',
      onOk: close => {
        const v = modalField();
        if (!RE_USER.test(v)) { modalWarn('Логин: 3-32 симв., латиница/цифры/._-'); return; }
        cardAction('change_username', { username: v, restart: modalRestart() });
        close();
      },
    });
  } else if (kind === 'password') {
    openXuiModal({
      title: 'Смена пароля панели',
      bodyHtml: `
        <label class="row">Новый пароль <span class="hint">генерируется, можно ввести свой</span></label>
        <div class="actions" style="margin:0;display:flex;gap:.4rem">
          <input id="xui-modal-field" autocomplete="off" style="flex:1"/>
          <button type="button" class="secondary" id="xui-modal-regen" title="Перегенерировать">🎲</button>
        </div>
        <div class="tabs-hint" style="margin:.3rem 0 0">Минимум 8 символов.</div>
        ${restartBox()}`,
      okText: 'Сменить пароль',
      bind: bg => {
        const f = bg.querySelector('#xui-modal-field');
        f.value = genPassword();
        bg.querySelector('#xui-modal-regen').onclick = () => { f.value = genPassword(); };
      },
      onOk: close => {
        const v = modalField();
        if (v.length < 8) { modalWarn('Пароль: минимум 8 символов'); return; }
        cardAction('change_password', { password: v, restart: modalRestart() });
        close();
      },
    });
  } else if (kind === 'port') {
    openXuiModal({
      title: 'Смена порта панели',
      bodyHtml: `
        <label class="row">Новый порт</label>
        <input id="xui-modal-field" inputmode="numeric" value="${esc(st.port != null ? String(st.port) : '')}" style="width:100%"/>
        <div class="tabs-hint" style="margin:.3rem 0 0">1-65535. Порт 80 зарезервирован под выпуск сертификата (ACME).</div>
        <div class="xui-restart-box" style="margin:.6rem 0 0;display:grid;grid-template-columns:auto 1fr;column-gap:.45rem;align-items:center">
          <input type="checkbox" id="xui-modal-fw" checked style="grid-row:1"/>
          <label for="xui-modal-fw" style="grid-row:1;grid-column:2;font-size:.82rem;cursor:pointer;margin:0">Закрыть старый порт в firewall</label>
          <div class="hint" style="grid-row:2;grid-column:2;margin:0;font-size:.72rem;line-height:1.4;color:var(--text-muted)">новый порт откроем всегда; снимите, чтобы старый остался открытым</div>
        </div>
        ${restartBox()}`,
      okText: 'Сменить порт',
      onOk: close => {
        const port = Number(modalField());
        if (!Number.isInteger(port) || port < 1 || port > 65535) { modalWarn('Порт: целое число 1-65535'); return; }
        if (port === 80) { modalWarn('Порт 80 зарезервирован под выпуск сертификата'); return; }
        cardAction('change_port', { port, restart: modalRestart(),
          close_old_port: !!document.getElementById('xui-modal-fw')?.checked });
        close();
      },
    });
  } else if (kind === 'path') {
    openXuiModal({
      title: 'Изменение web base path',
      bodyHtml: `
        <label class="row">Новый путь <span class="hint">свой или сгенерировать — как при установке</span></label>
        <div class="actions" style="margin:0;display:flex;gap:.4rem">
          <input id="xui-modal-field" autocomplete="off" style="flex:1"/>
          <button type="button" class="secondary" id="xui-modal-regen" title="Случайный путь">🎲</button>
        </div>
        <div class="tabs-hint" style="margin:.3rem 0 0">4-64 символа, латиница, цифры, дефис и подчёркивание. Старые ссылки на панель перестанут работать — новый адрес появится в карточке.</div>
        ${restartBox()}`,
      okText: 'Изменить путь',
      bind: bg => {
        const f = bg.querySelector('#xui-modal-field');
        f.value = genPath();
        bg.querySelector('#xui-modal-regen').onclick = () => { f.value = genPath(); };
      },
      onOk: close => {
        const v = modalField();
        if (!RE_PATH.test(v)) { modalWarn('Путь: 4-64 симв., латиница/цифры/_-'); return; }
        cardAction('change_path', { path: v, restart: modalRestart() });
        close();
      },
    });
  }
}

function updateGeoModal() {
  openXuiModal({
    title: 'Обновление geo-файлов',
    bodyHtml: `
      <div class="tabs-hint">Скачает свежие geoip.dat и geosite.dat (Loyalsoldier/v2ray-rules-dat) на сервер — канал сервера. Правила маршрутизации Xray подхватят их после рестарта.</div>
      ${restartBox()}`,
    okText: 'Обновить',
    onOk: close => {
      cardAction('update_geo', { restart: modalRestart() });
      close();
    },
  });
}

// ---------------- обновление версии (их CLI: x-ui update / legacy) -------

/** «2.6.4» → [2,6,4]; не-semver → null. */
const parseVer = t => {
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(String(t || '').trim());
  return m ? [+m[1], +m[2], +m[3]] : null;
};
/** a строго новее b (b не semver → любая semver-версия новее). */
const newerVer = (a, b) => {
  const va = parseVer(a), vb = parseVer(b);
  return !!va && (!vb || va > vb);
};

/** «Обновить»: сначала проверяем версию (GitHub latest через resolve-source,
 *  как в визарде), показываем установленную/последнюю — и только потом
 *  даём обновиться. /etc/x-ui сохраняется (тот же путь, что установка). */
function updateModal() {
  const cur = String((xuiCardState || {}).version || '').trim();
  openXuiModal({
    title: 'Обновление 3x-ui',
    bodyHtml: `
      <div class="info-row"><span class="info-label">Установлена</span><span class="info-value mono">${esc(cur || '—')}</span></div>
      <div class="info-row"><span class="info-label">Последняя</span><span class="info-value" id="xui-update-latest"><span class="hint">проверяю GitHub…</span></span></div>
      <div class="tabs-hint" id="xui-update-note" style="margin:.5rem 0 0">База и настройки (/etc/x-ui) сохраняются. Скачивание — канал сервера.</div>`,
    okText: 'Обновить',
    bind: async bg => {
      const ok = bg.querySelector('#xui-card-modal-ok');
      ok.disabled = true;
      const latestEl = bg.querySelector('#xui-update-latest');
      const noteEl = bg.querySelector('#xui-update-note');
      let latest = '';
      try {
        const r = await j(`${srvBase(xuiServerId)}/resolve-source`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ params: {} }),
        });
        if (!bg.isConnected) return;
        latest = String(r.tag || '').trim();
        latestEl.innerHTML = `<span class="mono">${esc(latest || '—')}</span>`;
        const notes = [];
        if (r.cache_stale) notes.push('GitHub недоступен — свежесть не проверена, источник: локальный кэш Bot4VPS');
        else if (r.source === 'push') notes.push('Источник: локальный кэш Bot4VPS (GitHub свежее нет)');
        if (!latest) {
          notes.push('Не удалось определить последнюю версию');
        } else if (!newerVer(latest, cur)) {
          notes.push('Установлена последняя версия — обновление не требуется');
        } else {
          notes.push(`Доступно обновление: ${cur || '—'} → ${latest}`);
        }
        noteEl.innerHTML = notes.map(esc).join('<br/>');
        if (latest && newerVer(latest, cur)) ok.disabled = false;
      } catch (e) {
        if (!bg.isConnected) return;
        latestEl.textContent = '—';
        noteEl.innerHTML = `<span style="color:var(--err)">${esc(e.message)}</span>`;
      }
    },
    onOk: close => {
      enqueueCardTask('update', {}, 'Обновление в очереди');
      close();
    },
  });
}

/** «Установить другую версию» (их CLI legacy): версия руками, тянется
 *  с GitHub. Можно понизить или поставить конкретный релиз. */
function installVersionModal() {
  const cur = String((xuiCardState || {}).version || '').trim();
  openXuiModal({
    title: 'Установка другой версии',
    bodyHtml: `
      <label class="row">Версия <span class="hint">например 2.5.0 — тянется с GitHub</span></label>
      <input id="xui-modal-field" autocomplete="off" placeholder="2.5.0" style="width:100%"/>
      <div class="tabs-hint" style="margin:.3rem 0 0">Формат X.Y.Z. Понижение или конкретный релиз; база и настройки (/etc/x-ui) сохраняются.${cur ? ` Сейчас установлена ${esc(cur)}.` : ''}</div>`,
    okText: 'Установить версию',
    onOk: close => {
      const v = modalField().replace(/^v/i, '');
      if (!/^\d+\.\d+\.\d+$/.test(v)) { modalWarn('Версия: формат X.Y.Z, например 2.5.0'); return; }
      enqueueCardTask('update', { tag: v }, 'Установка версии в очереди');
      close();
    },
  });
}


// ---------------- сертификат (зеркало их CLI SSL-меню) ----------------

/** Селект доменов из /root/cert — для продления/удаления. */
const certDomainOptions = domains => domains
  .map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('');

/** Движок сертификата панели для модалок: что сейчас назначено панели.
 *  panel_engine: 'acme' | 'certbot' | 'other' | null (http). */
const ENGINE_LABELS = {
  acme: 'acme.sh (/root/cert)',
  certbot: 'certbot (/etc/letsencrypt)',
  other: 'свой путь (движок неизвестен)',
};

function certPanelNowLine(cert) {
  const eng = cert.panel_engine;
  if (!eng) {
    return `<div class="tabs-hint" style="margin:0 0 .6rem">Сейчас панель: <b>http</b> — сертификат не назначен</div>`;
  }
  const label = ENGINE_LABELS[eng] || eng;
  return `<div class="tabs-hint" style="margin:0 0 .6rem">Сейчас панель: <b>${esc(label)}</b>${cert.panel_expires ? ` · до ${esc(cert.panel_expires)}` : ''}</div>`;
}

/** Выбор движка для выпуска: radio acme | certbot. Дефолт — движок
 *  серта панели (продолжаем тем же), иначе acme (как их CLI). */
const engineChoiceHtml = cert => {
  const def = cert.panel_engine === 'certbot' ? 'certbot' : 'acme';
  const cbOk = cert.certbot !== false;  // бэкенд доустановит, если нет
  return `
    <label class="row" style="margin-top:.6rem">Движок</label>
    <div style="display:flex;gap:1rem;flex-wrap:wrap">
      <label style="display:flex;align-items:baseline;gap:.35rem;cursor:pointer;font-weight:normal">
        <input type="radio" name="xui-modal-engine" value="acme"${def === 'acme' ? ' checked' : ''}/>
        <span>acme.sh <span class="hint">— как CLI 3x-ui, /root/cert, крон</span></span>
      </label>
      <label style="display:flex;align-items:baseline;gap:.35rem;cursor:pointer;font-weight:normal">
        <input type="radio" name="xui-modal-engine" value="certbot"${def === 'certbot' ? ' checked' : ''}/>
        <span>certbot <span class="hint">— /etc/letsencrypt, systemd-таймер${cbOk ? '' : ' (доустановим)'}</span></span>
      </label>
    </div>`;
};

const modalEngine = () =>
  document.querySelector('input[name="xui-modal-engine"]:checked')?.value || 'acme';

function certAction(kind) {
  const cert = (xuiCardState || {}).cert || {};
  const domains = Object.keys(cert.domains || {});
  if (kind === 'issue_domain') {
    openXuiModal({
      title: "Сертификат Let's Encrypt (домен)",
      bodyHtml: `
        ${certPanelNowLine(cert)}
        <label class="row">Домен</label>
        <input id="xui-modal-field" autocomplete="off" placeholder="panel.example.com" style="width:100%"/>
        <label class="row" style="margin-top:.6rem">Порт выпуска <span class="hint">должен смотреть в интернет — по нему ACME проверит домен</span></label>
        <input id="xui-modal-port" inputmode="numeric" value="80" style="width:100%"/>
        ${engineChoiceHtml(cert)}
        <label style="display:flex;align-items:baseline;gap:.4rem;margin:.7rem 0 0;cursor:pointer">
          <input type="checkbox" id="xui-modal-setpanel" checked/>
          <span>Назначить сертификат панели <span class="hint">— https + рестарт</span></span>
        </label>
        <div class="tabs-hint" style="margin:.4rem 0 0">Порт 80 откроем в firewall и освободим (остановив мешающий сервис) на время выпуска, потом вернём как было. Занятый порт 80 чужим не-systemd процессом — повод для отказа.</div>`,
      okText: 'Выпустить',
      onOk: close => {
        const domain = modalField();
        if (!RE_DOMAIN.test(domain)) { modalWarn('Домен: например panel.example.com'); return; }
        const port = Number(String(document.getElementById('xui-modal-port')?.value || '').trim() || '80');
        if (!Number.isInteger(port) || port < 1 || port > 65535) { modalWarn('Порт: целое число 1-65535'); return; }
        enqueueCardTask('cert_issue_domain', {
          domain, port, engine: modalEngine(),
          set_panel: !!document.getElementById('xui-modal-setpanel')?.checked,
        }, 'Выпуск сертификата в очереди');
        close();
      },
    });
  } else if (kind === 'issue_ip') {
    const ip = xuiServerIpv4(xuiServerId);
    openXuiModal({
      title: 'Сертификат для IP-адреса',
      bodyHtml: `
        <label class="row">Публичный IPv4 сервера</label>
        <input id="xui-modal-field" autocomplete="off" inputmode="text" value="${esc(ip)}" placeholder="203.0.113.10" style="width:100%"/>
        <label class="row" style="margin-top:.6rem">IPv6 <span class="hint">необязательно — включить в сертификат</span></label>
        <input id="xui-modal-ipv6" autocomplete="off" placeholder="2001:db8::1" style="width:100%"/>
        <div class="tabs-hint" style="margin:.4rem 0 0">Короткоживущий профиль Let's Encrypt (~6 дней), обновляется кроном acme.sh автоматически. Порт 80 должен смотреть в интернет. Положит в /root/cert/ip/ и назначит панели.</div>`,
      okText: 'Выпустить',
      onOk: close => {
        const ip = modalField();
        if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) { modalWarn('IPv4: например 203.0.113.10'); return; }
        const ipv6 = String(document.getElementById('xui-modal-ipv6')?.value || '').trim();
        if (ipv6 && !ipv6.includes(':')) { modalWarn('IPv6: например 2001:db8::1'); return; }
        enqueueCardTask('cert_issue_ip', { ip, ipv6: ipv6 || null, set_panel: true },
          'Выпуск сертификата в очереди');
        close();
      },
    });
  } else if (kind === 'renew') {
    // домены обоих движков с пометкой: продлевает владелец серта
    const allDomains = [
      ...domains.map(d => [d, 'acme']),
      ...(cert.certbot_domains || []).map(d => [d, 'certbot']),
    ];
    openXuiModal({
      title: 'Принудительное продление',
      bodyHtml: `
        ${certPanelNowLine(cert)}
        <label class="row">Домен</label>
        <select id="xui-modal-field" style="width:100%">${allDomains
          .map(([d, eng]) => `<option value="${esc(d)}" data-engine="${eng}">${esc(d)} — ${eng === 'certbot' ? 'certbot' : 'acme.sh'}</option>`)
          .join('')}</select>
        <div class="tabs-hint" style="margin:.4rem 0 0">Перевыпустит сертификат тем движком, который им владеет; хук обновит файлы и перезапустит панель. Порт 80 на время проверки подготовим и вернём как было.</div>`,
      okText: 'Продлить',
      onOk: close => {
        const sel = document.getElementById('xui-modal-field');
        enqueueCardTask('cert_renew', {
          domain: modalField(),
          engine: sel?.selectedOptions?.[0]?.dataset?.engine || undefined,
        }, 'Продление в очереди');
        close();
      },
    });
  } else if (kind === 'remove') {
    const allDomains = [
      ...domains.map(d => [d, 'acme']),
      ...(cert.certbot_domains || []).map(d => [d, 'certbot']),
    ];
    openXuiModal({
      title: 'Отозвать и удалить сертификат',
      bodyHtml: `
        ${certPanelNowLine(cert)}
        <label class="row">Домен</label>
        <select id="xui-modal-field" style="width:100%">${allDomains
          .map(([d, eng]) => `<option value="${esc(d)}" data-engine="${eng}">${esc(d)} — ${eng === 'certbot' ? 'certbot' : 'acme.sh'}</option>`)
          .join('')}</select>
        <div class="err-hint" style="color:var(--err);font-size:.8rem;margin:.5rem 0 0">Сертификат будет отозван в Let's Encrypt и удалён с сервера тем движком, который им владеет. Если панель использовала его — сбросим пути сертификата и перезапустим панель (она станет http).</div>`,
      okText: 'Отозвать и удалить', danger: true,
      onOk: close => {
        const sel = document.getElementById('xui-modal-field');
        enqueueCardTask('cert_remove', {
          domain: modalField(),
          engine: sel?.selectedOptions?.[0]?.dataset?.engine || undefined,
        }, 'Удаление в очереди');
        close();
      },
    });
  }
}

async function removeXuiModal() {
  const options = {
    checked: false,
    label: 'Удалить все данные (база, инбаунды, пользователи)',
  };
  const ok = await confirmAction({
    title: 'Удалить 3x-ui?',
    message: 'Удалит бинарник /usr/local/x-ui, CLI /usr/bin/x-ui и systemd-юнит. Клиентские подключения перестанут работать.',
    confirmText: 'Удалить', cancelText: 'Отмена', checkbox: options,
  });
  if (!ok) return;
  enqueueCardTask('remove', { remove_data: options.checked }, 'Удаление в очереди');
}

// -- SelfSNI: сайт-заглушка Reality (блок «Доп. действия») ------------

/** Получает только сохранённый fakesite-блок. В отличие от cardAction это
 * не вызывает live /state после ответа и поэтому не открывает SSH. */
async function fakesiteCachedInfo() {
  if (!xuiServerId) return { present: false };
  const r = await j(`${srvBase(xuiServerId)}/action/fakesite_info`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params: {} }),
  });
  return (r && r.fakesite && typeof r.fakesite === 'object')
    ? r.fakesite : { present: false };
}

function fakesiteUsageRows(site, rows) {
  return rows.map(([label, key]) => {
    const text = String(site[key] ?? '—');
    return `<div class="info-row"><span class="info-label">${esc(label)}</span>
      <span class="info-value mono" style="display:flex;align-items:center;gap:.35rem;min-width:0">
        <span style="overflow-wrap:anywhere">${esc(text)}</span>
        <button type="button" class="secondary" data-fakesite-copy="${esc(text)}" title="Копировать" style="padding:.13rem .32rem;line-height:1">⧉</button>
      </span></div>`;
  }).join('');
}

function fakesitePathBoxes(site) {
  return [['Сертификат', 'certificate'], ['Ключ', 'certificate_key']].map(([label, key]) => {
    const text = String(site[key] ?? '—');
    return `<div class="fakesite-path">
      <span class="info-label fakesite-path-label">${esc(label)}</span>
      <div class="fakesite-path-box">
        <span class="mono">${esc(text)}</span>
        <button type="button" class="secondary" data-fakesite-copy="${esc(text)}" title="Копировать">⧉</button>
      </div>
    </div>`;
  }).join('');
}

function bindFakesiteCopy(bg) {
  bg.querySelectorAll('[data-fakesite-copy]').forEach(button => {
    button.addEventListener('click', () => copyText(button.dataset.fakesiteCopy || '', button));
  });
}

function openFakesiteUsage(site, title = 'Информация для использования') {
  if (!site || !site.present) {
    openXuiModal({
      title: 'Информация для использования',
      bodyHtml: '<div class="tabs-hint" style="margin:0">SelfSNI ещё не установлен. Сначала установите сайт-заглушку.</div>',
      okText: 'Закрыть', hideCancel: true, onOk: close => close(),
    });
    return;
  }
  openXuiModal({
    title,
    bodyHtml: `
      <div class="tabs-hint" style="margin:0 0 .7rem">В инбаунде Reality укажите значения вручную. Bot4VPS инбаунды не меняет.</div>
      <div class="tabs-hint" style="margin:.4rem 0 .55rem;text-align:center;font-weight:600">Параметры для inbound'a</div>
      ${fakesiteUsageRows(site, [
        ['Dest', 'dest'], ['SNI', 'sni'], ['Xver', 'xver'],
      ])}
      <div class="tabs-hint" style="margin:.8rem 0 .55rem;text-align:center;font-weight:600">Расположение сертификата и ключа для панели</div>
      ${fakesitePathBoxes(site)}`,
    okText: 'Закрыть', hideCancel: true, bind: bindFakesiteCopy,
    onOk: close => close(),
  });
}

function openFakesiteDomainForm(initialDomain = '') {
  const modal = openXuiModal({
    title: 'Установка SelfSNI',
    bodyHtml: `
      <label class="row">Домен</label>
      <input id="xui-modal-field" autocomplete="off" placeholder="site.example.com" value="${esc(initialDomain)}" style="width:100%"/>
      <div class="tabs-hint" style="margin:.35rem 0 0">A-запись домена должна указывать на этот сервер.</div>`,
    okText: 'Установить',
    onOk: async close => {
      const domain = modalField().replace(/\.$/, '');
      if (!RE_DOMAIN.test(domain)) { modalWarn('Домен: например site.example.com'); return; }
      // Общая confirm-модалка находится под xui-модалкой по z-index. Сначала
      // убираем форму, поэтому вопрос подтверждения не оказывается за ней.
      close();
      const ok = await confirmAction({
        title: 'Установить сайт-заглушку?',
        message: `Для ${domain} будет создан локальный HTTPS-сайт. Настройки Reality останутся без изменений.`,
        confirmText: 'Установить', cancelText: 'Отмена', danger: false,
      });
      if (!ok) return;
      enqueueCardTask('fakesite_install', { domain }, 'Установка SelfSNI в очереди');
    },
  });
  modal.querySelector('#xui-modal-field').addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.isComposing) return;
    event.preventDefault();
    modal.querySelector('#xui-card-modal-ok').click();
  });
}

function openFakesiteIntro() {
  openXuiModal({
    title: 'Сайт-заглушка (SelfSNI)',
    bodyHtml: `
      <div class="tabs-hint" style="margin:0 0 .65rem">Создаёт обычный HTTPS-сайт для трафика, который не прошёл Reality handshake.</div>
      <div class="tabs-hint" style="margin:.35rem 0;white-space:pre-line">Успешный Reality handshake → VLESS / Reality\nНе прошёл → Dest → 127.0.0.1:9000 → HTTPS-сайт</div>
      <div class="tabs-hint" style="margin:.65rem 0">Используется сертификат Let’s Encrypt. Шаблон выбирается случайно из <a href="https://github.com/learning-zone/website-templates" target="_blank" rel="noopener">learning-zone/website-templates ↗</a> и не сохраняется в Bot4VPS.</div>
      <div class="tabs-hint" style="margin:.65rem 0;white-space:pre-line">После установки настройте Reality вручную:\nDest = 127.0.0.1:9000\nXver = 1\nSNI = ваш домен</div>
      <div class="tabs-hint" style="margin:.65rem 0 0">Существующие инбаунды Reality не изменяются.</div>`,
    okText: 'ОК, продолжить установку', cancelText: 'Отмена',
    onOk: close => { close(); openFakesiteDomainForm(); },
  });
}

async function removeFakesite() {
  const ok = await confirmAction({
    title: 'Удалить заглушку?',
    message: 'Удалит конфигурацию SelfSNI и восстановит прежний сайт, если он не менялся после установки. Сертификат Let’s Encrypt останется на сервере.',
    confirmText: 'Удалить заглушку', cancelText: 'Отмена',
  });
  if (ok) enqueueCardTask('fakesite_remove', {}, 'Удаление SelfSNI в очереди');
}

async function fakesiteActionMenu() {
  if (!xuiServerId || xuiCardBusy) return;
  // Сразу открываем локальную модалку: это останавливает обычный live-poll,
  // пока cache-only запрос получает фейк-сайт. Сам запрос SSH не делает.
  const loading = openXuiModal({
    title: 'Сайт-заглушка (SelfSNI)',
    bodyHtml: '<div class="tabs-hint" style="margin:0">Загрузка сохранённой информации…</div>',
    okText: 'Закрыть', hideCancel: true, onOk: close => close(),
  });
  let site;
  try { site = await fakesiteCachedInfo(); }
  catch (e) { loading.remove(); toast(e.message || String(e), false); return; }
  if (!loading.isConnected) return;
  loading.remove();
  const present = !!site.present;
  openXuiModal({
    title: 'Сайт-заглушка (SelfSNI)',
    bodyHtml: `
      <div class="actions" style="display:grid;grid-template-columns:1fr;gap:.45rem;margin:0">
        <button type="button" class="secondary" id="xui-fakesite-install"${present ? ' disabled' : ''}>Установить</button>
        <button type="button" class="secondary" id="xui-fakesite-info">Информация для использования</button>
        <button type="button" class="svc-action svc-action-danger" id="xui-fakesite-remove" style="align-items:center;text-align:center"${present ? '' : ' disabled'}>
          <b>🗑 Удалить заглушку</b>
        </button>
      </div>`,
    okText: 'Закрыть', hideCancel: true,
    bind: bg => {
      bg.querySelector('#xui-fakesite-install')?.addEventListener('click', () => { bg.remove(); openFakesiteIntro(); });
      bg.querySelector('#xui-fakesite-info')?.addEventListener('click', () => { bg.remove(); openFakesiteUsage(site); });
      bg.querySelector('#xui-fakesite-remove')?.addEventListener('click', () => { bg.remove(); removeFakesite(); });
    },
    onOk: close => close(),
  });
}


/** Экспорт: скачивание через браузер (fetch → blob → a.download),
 *  т.к. карточка блокируется, а прямой <a href> не даст ошибку при
 *  провале. Кнопка блокируется на время (не enqueue — только чтение). */
async function exportDbModal() {
  if (!xuiServerId || xuiCardBusy) return;
  const ok = await confirmAction({
    title: 'Экспорт базы данных',
    message: 'Скачает файл .db — резервную копию вашей текущей базы данных на ваше устройство.',
    confirmText: 'Скачать', cancelText: 'Отмена',
  });
  if (!ok) return;
  xuiCardBusy = true;
  const card = document.getElementById('xui-srv-body');
  card?.classList.add('xui-card-busy');
  try {
    const r = await fetch(`${srvBase(xuiServerId)}/db-export`);
    if (!r.ok) {
      let msg = 'Экспорт не удался';
      try { const e = await r.json(); msg = e.detail || e.error || msg; } catch (_) {}
      toast(msg, false);
      return;
    }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)/i.exec(cd);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = m ? decodeURIComponent(m[1]) : 'x-ui.db';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast('База скачана', true);
  } catch (e) {
    toast(e.message || String(e), false);
  } finally {
    xuiCardBusy = false;
    card?.classList.remove('xui-card-busy');
  }
}

/** Импорт: файл с устройства → upload-эндпоинт → enqueue db_import
 *  (остановка панели, замена базы, migrate, авторестарт). */
function importDbModal() {
  if (!xuiServerId || xuiCardBusy) return;
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.db,.dump';
  input.onchange = async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast('Максимальный размер — 5 МБ', false); return; }
    const go = await confirmAction({
      title: 'Восстановить базу данных?',
      message: `«${file.name}» заменит текущую базу панели: инбаунды, пользователи, настройки вернутся к состоянию из копии. Текущая база будет сохранена на сервере, панель перезапустится.`,
      confirmText: 'Восстановить', cancelText: 'Отмена',
    });
    if (!go) return;
    // файл уже выбран — upload+enqueue, карточку блокируем как на задачу
    xuiCardBusy = true;
    const card = document.getElementById('xui-srv-body');
    card?.classList.add('xui-card-busy');
    try {
      const fd = new FormData();
      fd.append('file', file, file.name);
      const r = await j(`${srvBase(xuiServerId)}/db-import`, { method: 'POST', body: fd });
      toast('Импорт базы в очереди', true);
      if (r.task) watchXuiTask(r.task.id, 'db_import');
      else { xuiCardBusy = false; card?.classList.remove('xui-card-busy'); }
    } catch (e) {
      toast(e.message || String(e), false);
      xuiCardBusy = false;
      card?.classList.remove('xui-card-busy');
    }
  };
  input.click();
}

function openFakesiteInstallProgress() {
  let bg = document.getElementById('xui-fakesite-install-modal');
  if (bg) bg.remove();
  bg = document.createElement('div');
  bg.className = 'modal-bg open';
  bg.id = 'xui-fakesite-install-modal';
  bg.tabIndex = -1;
  bg.innerHTML = `
  <div class="modal" style="width:min(680px,100%)">
    <div class="section-head" style="margin-bottom:.6rem">
      <h3 style="margin:0">Установка SelfSNI</h3>
      <button type="button" id="xui-fakesite-install-bg" title="Свернуть окно: установка продолжится в фоне"
              style="padding:.2rem .55rem;font-size:.78rem">в фон ↓</button>
    </div>
    <div class="tabs-hint" id="xui-fakesite-install-steptitle" style="margin:0 0 .6rem">
      Установка — это может занять несколько минут
    </div>
    <div id="xui-fakesite-install-progress"><div class="empty">Ожидание очереди…</div></div>
    <div class="err-hint" id="xui-fakesite-install-warn"
         style="white-space:pre-wrap;color:var(--err);font-size:.78rem"></div>
    <div class="actions" style="margin-top:.8rem;justify-content:flex-end"
         id="xui-fakesite-install-actions"></div>
  </div>`;
  document.body.appendChild(bg);
  bg.focus();
  bg.querySelector('#xui-fakesite-install-bg').onclick = () => bg.remove();
  bg.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); bg.remove(); }
  });
  return bg;
}

function renderFakesiteInstallTask(t) {
  const bg = document.getElementById('xui-fakesite-install-modal');
  if (!bg) return;
  const status = String(t.status || (t.is_done ? (t.success ? 'success' : 'failed') : 'running'));
  const done = !!t.is_done;
  const ok = !!t.success;
  const title = bg.querySelector('#xui-fakesite-install-steptitle');
  if (title) title.textContent = done
    ? (ok ? 'Установка завершена — обновляю состояние панели' : 'Установка не удалась')
    : 'Установка — это может занять несколько минут';
  const lines = Array.isArray(t.output_lines) ? t.output_lines : [];
  const body = lines.length
    ? lines.map(ansiToHtml).join('\n')
    : ansiToHtml(t.result?.output || t.result?.error || t.error || '(нет вывода)');
  const log = bg.querySelector('#xui-fakesite-install-progress');
  if (log) {
    log.innerHTML = `<div class="tasklog-head">${esc(t.emoji || '')} ${esc(t.name || 'SelfSNI')} · ${esc(status)} · ${esc(t.duration || '')}</div>
      <div class="logbox" style="max-height:40vh">${body}</div>`;
    const box = log.querySelector('.logbox');
    if (box) {
      const stick = box.__stick !== false;
      box.onscroll = () => {
        box.__stick = box.scrollHeight - box.scrollTop - box.clientHeight < 4;
      };
      if (stick) box.scrollTop = box.scrollHeight;
    }
  }
  const warn = bg.querySelector('#xui-fakesite-install-warn');
  if (warn && done && !ok) warn.textContent = t.result?.error || t.error || 'Задача завершена с ошибкой';
  const actions = bg.querySelector('#xui-fakesite-install-actions');
  if (actions && done && !ok && !actions.childElementCount) {
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'secondary';
    close.textContent = 'Закрыть';
    close.onclick = () => bg.remove();
    actions.appendChild(close);
  }
  if (done) bg.querySelector('#xui-fakesite-install-bg')?.classList.add('hidden');
}

/** Тяжёлое действие → очередь задач (do_*), сопровождение поллингом.
 *  Пока задача идёт, карточка заблокирована (как у быстрых действий):
 *  повторные команды в очередь не отправляем. */
async function enqueueCardTask(action, params, msg) {
  if (!xuiServerId || xuiCardBusy) return;
  xuiCardBusy = true;
  const card = document.getElementById('xui-srv-body');
  if (card) card.classList.add('xui-card-busy');
  try {
    const r = await j(`${srvBase(xuiServerId)}/enqueue/${encodeURIComponent(action)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ params }),
    });
    // команда принята сервером — сразу даём понять, что ушла
    toast(msg || 'Команда отправлена', true);
    if (r.task) {
      if (action === 'fakesite_install') openFakesiteInstallProgress();
      watchXuiTask(r.task.id, action);
    } else {
      xuiCardBusy = false;
      card?.classList.remove('xui-card-busy');
    }
  } catch (e) {
    toast(e.message || String(e), false);
    xuiCardBusy = false;
    card?.classList.remove('xui-card-busy');
  }
}

function watchXuiTask(taskId, action) {
  const tick = async () => {
    let t;
    try { t = await j('/api/tasks/' + encodeURIComponent(taskId)); }
    catch (_) { return; }
    if (action === 'fakesite_install') renderFakesiteInstallTask(t);
    if (!t.is_done) return;
    clearInterval(xuiTimers[taskId]); delete xuiTimers[taskId];
    // финал задачи — карточка снова активна
    xuiCardBusy = false;
    document.getElementById('xui-srv-body')?.classList.remove('xui-card-busy');
    if (action === 'remove') {
      if (t.success) {
        toast('3x-ui удалён', true);
        const returnToServer = xuiEntryContext === 'server' && xuiServerId;
        const sid = xuiServerId;
        stopXuiLivePoll();
        xuiServerId = null;
        xuiCardState = null;
        try { localStorage.removeItem('bot4vps_xui_server_id'); } catch (_) {}
        if (returnToServer) {
          try {
            const { openServer } = await import('./servers.js?v=20260915-sysfix-v2');
            await openServer(sid);
          } catch (_) { backToXuiList(); }
        } else {
          backToXuiList();
        }
      } else {
        toast(t.error || 'Удаление 3x-ui завершилось с ошибкой', false);
      }
      return;
    }
    const refresh = xuiServerId && document.getElementById('page-xui-server')?.classList.contains('on')
      ? refreshXuiServerDetailAfterMutation(xuiServerId)
      : loadXui();
    if (action === 'fakesite_install' && t.success) {
      await refresh;
      document.getElementById('xui-fakesite-install-modal')?.remove();
      toast('SelfSNI установлен', true);
      // Экран результата читает только уже записанный fakesite-кэш.
      fakesiteCachedInfo().then(site => openFakesiteUsage(site, 'SelfSNI установлен'))
        .catch(e => toast(e.message || String(e), false));
    } else if (action === 'fakesite_install') {
      const modal = document.getElementById('xui-fakesite-install-modal');
      if (!modal) {
        let failMsg = t.error || 'Установка SelfSNI завершилась с ошибкой';
        if (t.result?.output) failMsg += `\n${String(t.result.output).trim().split('\n').slice(-4).join('\n')}`;
        toast(failMsg, false);
      }
    } else if (action === 'fakesite_remove' && t.success) {
      await refresh;
      toast('SelfSNI удалён', true);
    } else {
      // при провале показываем причину: t.error — заголовок, output — вывод
      // команды на сервере (acme.sh и т.п.); без него «код 1» бесполезен
      let failMsg = t.error || `${t.name || 'Задача'} завершилась с ошибкой`;
      if (!t.success && t.result?.output) {
        const tail = String(t.result.output).trim().split('\n').slice(-4).join('\n');
        if (tail && tail !== failMsg) failMsg += `\n${tail}`;
      }
      toast(t.success
        ? `${t.emoji || '✅'} ${t.name || 'Задача'} — выполнена`
        : failMsg, t.success);
    }
  };
  if (xuiTimers[taskId]) clearInterval(xuiTimers[taskId]);
  tick();
  xuiTimers[taskId] = setInterval(tick, 1500);
}

// ---------------- логи юнита ----------------

function openXuiLogs() {
  let bg = document.getElementById('xui-logs-modal');
  if (bg) bg.remove();
  bg = document.createElement('div');
  bg.className = 'modal-bg open';
  bg.id = 'xui-logs-modal';
  bg.innerHTML = `
  <div class="modal" style="width:min(760px,100%)">
    <div class="section-head" style="margin-bottom:.5rem">
      <h3 style="margin:0">Логи x-ui</h3>
      <div class="actions" style="margin:0">
        <button type="button" class="secondary" id="xui-logs-refresh">🔄 Обновить</button>
        <button type="button" class="secondary" id="xui-logs-close">Закрыть</button>
      </div>
    </div>
    <div class="logbox" id="xui-logs-body" style="max-height:60vh"><div class="empty">Загрузка…</div></div>
    <div class="tabs-hint" style="margin:.5rem 0 0">journalctl юнита x-ui, последние 200 строк. Xray — дочерний процесс, его вывод пишется в тот же журнал.</div>
  </div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  bg.querySelector('#xui-logs-close').onclick = close;
  bg.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  });
  const load = async () => {
    const box = bg.querySelector('#xui-logs-body');
    try {
      const r = await j(`${srvBase(xuiServerId)}/logs/x-ui?tail=200`);
      box.innerHTML = ansiToHtml(String(r.logs || '') || '(журнал пуст)');
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`;
    }
  };
  bg.querySelector('#xui-logs-refresh').onclick = load;
  load();
}

// Публичный API для входа со страницы сервера и восстановления сессии.
export function openXuiServerById(id) { return openXuiServer(id, { from: 'server' }); }

// ---------------- точка входа визарда ----------------

export async function openInstallWizard(serverId) {
  const srv = statusMap[serverId];
  const name = srv?.name || srv?.host || serverId;
  wizardCtx = { serverId, host: srv?.host || '', arch: null, resolve: null };
  wizardShell(name);
  renderStep1();
  // параллельно: arch целевого сервера (для превью источника)
  j(`${srvBase(serverId)}/state`)
    .then(r => {
      if (wizardCtx?.serverId !== serverId) return;
      wizardCtx.arch = r?.state?.arch || null;
    })
    .catch(() => {});
}

// Фоновая задача 3x-ui (например, подхваченная резюмом после перезагрузки
// страницы) завершилась — обновляем карточки, если открыта страница 3x-ui.
document.addEventListener('bot4vps:task-done', e => {
  const t = e.detail || {};
  if (!String(t.name || '').startsWith('3x-ui:')) return;
  if (document.getElementById('page-xui-server')?.classList.contains('on')) {
    if (xuiServerId) refreshXuiServerDetailAfterMutation(xuiServerId);
    return;
  }
  if (document.getElementById('page-xui')?.classList.contains('on')) loadXui();
});
