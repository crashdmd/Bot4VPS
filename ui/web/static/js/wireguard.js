// Страница WireGuard: тонкий слой отображения над обобщённым services-роутером.
// Вся бизнес-логика — на бэке (core.integrator + services/wireguard).
//
// Список серверов — таблица в паттерне раздела «Серверы» (server-table):
// Имя (сорт) · Статус (цикл группировок) · Версия (сорт от свежей) ·
// Endpoint (скрыт как IP, показывается с портом) · Профили.
// Отдельного статуса «не проверен» нет: пустой кэш = «не установлен».
// Клик по строке: установлен → экран WG этого сервера; остальные строки —
// без перехода (действие только кнопкой «Установить»/«Миграция» в
// объединённой области трёх последних колонок). Фильтров нет: имя и статус
// сортируются, статус — циклом из трёх раскладок (см. WG_STATUS_ORDERS).
// Все диалоги — в стиле интерфейса (модалка #wg-dialog), без браузерных alert/prompt.
import { j, esc } from './api.js';
import { openTaskModal } from './taskmodal.js?v=20260914-v3';
import { statusFilterBtn, statusFilterHidden, bindStatusFilter } from './statusfilter.js?v=20260915-v1';
import { toast, showPage, serverDateTimeParts, serverDayDifference } from './ui.js';

const SID = 'wireguard';
const timers = {};                  // taskId -> polling-интервал
let statusMap = {};                 // id -> {name, host, status}
let installParams = null;
let installTarget = null;

// Экран конкретного сервера
let wgServerId = null;              // id открытого сервера
let wgEntryContext = 'list';        // 'list' | 'server' — откуда открыли панель
let wgServerState = null;           // последний live-state (для префиля модалки)
let wgImportedBannerHidden = false;  // состояние видимости баннера текущего сервера
const importBannerClosedKey = id => `wg_import_banner_closed_${id}`;

const srvBase = id => `/api/services/${SID}/${encodeURIComponent(id)}`;
const stateUrl = id => `${srvBase(id)}/state`;
const nameOf = id => (statusMap[id] && statusMap[id].name) || id;
const profileCount = st => Array.isArray(st && st.profiles) ? st.profiles.length : 0;

function shortVer(v) { const m = String(v || '').match(/v?\d+\.\d+[\w.-]*/); return m ? m[0] : ''; }
function fmtSync(iso) {
  const parts = serverDateTimeParts(iso);
  if (!parts) return '';
  const hm = `${parts.hour}:${parts.minute}`;
  const diffDays = serverDayDifference(iso);
  if (diffDays === 0) return 'сегодня, ' + hm;
  if (diffDays === 1) return 'вчера, ' + hm;
  return `${parts.day}.${parts.month}, ${hm}`;
}
function isPrivateHost(h) {
  const m = String(h || '').trim().match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return false;
  const a = +m[1], b = +m[2];
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || a === 127;
}

// СЫРЫЕ байты → человекочитаемые единицы. Сервис отдаёт байты; UI форматирует (ТЗ §19).
// В ГБ — 4 знака по ТЗ §5 («17.5513 ГБ»).
function fmtBytes(n) {
  n = Number(n) || 0;
  const abs = Math.abs(n);
  if (abs >= 1e12) return (n / 1e12).toFixed(4) + ' ТБ';
  if (abs >= 1e9) return (n / 1e9).toFixed(4) + ' ГБ';
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + ' МБ';
  if (abs >= 1e3) return (n / 1e3).toFixed(2) + ' КБ';
  return n + ' Б';
}

function copyToClipboard(text) {
  if (text == null || text === '') return;
  const str = String(text);
  const ok = () => toast('Скопировано', true);
  const fail = () => toast('Не удалось скопировать', false);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(str).then(ok).catch(() => {
      if (_copyFallback(str)) ok();
      else fail();
    });
    return;
  }
  if (_copyFallback(str)) ok();
  else fail();
}

function _copyFallback(str) {
  try {
    const ta = document.createElement('textarea');
    ta.value = str;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, str.length);
    const done = document.execCommand('copy');
    document.body.removeChild(ta);
    return !!done;
  } catch (_) {
    return false;
  }
}


// ---------------- modal stack (z-index) ----------------
let _modalZ = 50;
function openModalEl(el) {
  if (!el) return;
  _modalZ += 10;
  el.style.zIndex = String(_modalZ);
  el.classList.add('open');
  el.dataset.modalZ = String(_modalZ);
}
function closeModalEl(el) {
  if (!el) return;
  el.classList.remove('open');
  el.style.zIndex = '';
  delete el.dataset.modalZ;
}

// ---------------- in-UI диалог (вместо браузерных prompt/confirm) ----------------

let dialogResolve = null;
let dialogMode = 'confirm';

function showDialog({ title, message, input = false, value = '', placeholder = '', okText = 'ОК', cancelText = 'Отмена' }) {
  return new Promise(resolve => {
    dialogResolve = resolve;
    dialogMode = input ? 'prompt' : 'confirm';
    document.getElementById('wg-dialog-title').textContent = title || '';
    const msg = document.getElementById('wg-dialog-msg');
    if (message) { msg.textContent = message; msg.classList.remove('hidden'); } else { msg.classList.add('hidden'); }
    const inp = document.getElementById('wg-dialog-input');
    document.getElementById('wg-dialog-ok').textContent = okText;
    document.getElementById('wg-dialog-cancel').textContent = cancelText;
    if (input) {
      inp.classList.remove('hidden');
      inp.value = value; inp.placeholder = placeholder;
      setTimeout(() => { inp.focus(); inp.select(); }, 10);
    } else {
      inp.classList.add('hidden');
    }
    openModalEl(document.getElementById('wg-dialog'));
  });
}
function closeDialog(val) {
  closeModalEl(document.getElementById('wg-dialog'));
  const r = dialogResolve; dialogResolve = null;
  if (r) r(val);
}
const wgConfirm = (title, message, okText = 'ОК', cancelText = 'Отмена') =>
  showDialog({ title, message, okText, cancelText }).then(v => v === true);
const wgPrompt = (title, message, value = '', placeholder = '', okText = 'ОК', cancelText = 'Отмена') =>
  showDialog({ title, message, input: true, value, placeholder, okText, cancelText });

// ---------------- список серверов (таблица в паттерне «Серверов») ----------------

// Сортировка/видимость Endpoint — локальное состояние страницы.
// Статус сортируется не ↑/↓, а циклом из трёх раскладок (4-й клик = 1-му):
let wgSort = { key: 'name', descending: false };
let wgStatusRotation = 0;             // индекс в WG_STATUS_ORDERS
let wgRevealAllEndpoints = false;
const wgEndpointRevealed = new Set();

/** Состояние WG на сервере. «Не проверен» не существует: пустой кэш
 *  трактуется как «не установлен» (актуализация — забота фоновой проверки). */
function wgState(st) {
  if (st && st.needs_migration) return 'classic';
  if (st && st.installed) return 'installed';
  return 'absent';
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

const WG_BLOCKED_NOTE = {
  down: ['⛔ Сервер оффлайн — работа с сервисом невозможна', '⛔ Оффлайн'],
  ssh: ['⛔ SSH-порт недоступен — работа с сервисом невозможна', '⛔ Нет SSH'],
};

const WG_STATUS_LABEL = {
  installed: '🟢 Установлен',
  classic: '🟡 Классический конфиг',
  absent: '⚪ Не установлен',
};
// Раскладки групп статусов по клику на заголовок «Статус»:
// 1-й клик — установленные сверху, 2-й — не установленные, 3-й — классика;
// внутри каждой группы — по алфавиту.
const WG_STATUS_ORDERS = [
  ['installed', 'classic', 'absent'],
  ['absent', 'classic', 'installed'],
  ['classic', 'installed', 'absent'],
];

export async function loadWireguard() {
  const el = document.getElementById('wg-servers');
  if (!el) return;
  try {
    const d = await j(`/api/services/${SID}/status`);
    statusMap = {};
    (d.servers || []).forEach(s => { statusMap[s.id] = s; });
    renderWgServers();
  } catch (e) {
    el.innerHTML = '<div class="empty">' + esc(e.message || e) + '</div>';
  }
}

function filteredWgServers() {
  // Фильтр статусов (кнопка у заголовка «Статус»)
  const hidden = statusFilterHidden('wireguard', WG_STATUS_FILTERS);
  const all = Object.values(statusMap);
  if (!hidden.size) return all;
  return all.filter(s => !hidden.has(wgFilterKey(s)));
}

/** Статус строки для фильтра (см. WG_STATUS_FILTERS). */
function wgFilterKey(s) {
  if (serviceBlocked(s)) return 'blocked';
  return wgState((s || {}).status || {});
}

const WG_STATUS_FILTERS = [
  { key: 'installed', label: '🟢 Установлен' },
  { key: 'classic', label: '🟡 Классический конфиг' },
  { key: 'absent', label: '⚪ Не установлен' },
  { key: 'blocked', label: '⛔ Недоступен (оффлайн/SSH)' },
];

function wgProfilesTotal(st) {
  const stats = (st && st.stats) || {};
  if (stats.total != null) return Number(stats.total);
  return profileCount(st);
}

/** Сравнение версий по числовым сегментам («1.0.20210914» и т.п.),
 *  независимо от дистро-суффиксов. */
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

function sortedWgServers(list) {
  const byName = [...list].sort((a, b) =>
    String(a.name || '').localeCompare(String(b.name || ''), 'ru', { sensitivity: 'base', numeric: true })
      || String(a.id).localeCompare(String(b.id)));
  const key = wgSort.key;
  if (key === 'status') {
    // Цикл раскладок; sort стабилен — алфавит внутри групп сохраняется.
    const order = WG_STATUS_ORDERS[wgStatusRotation];
    const rank = s => order.indexOf(wgState((s || {}).status || {}));
    return byName.sort((a, b) => rank(a) - rank(b));
  }
  if (key === 'version') {
    // Свежая → старая (первый клик) и обратно; без версии — всегда внизу.
    const has = s => String(((s || {}).status || {}).version || '').trim() !== '';
    return byName.sort((a, b) => {
      if (has(a) !== has(b)) return has(a) ? -1 : 1;
      if (!has(a)) return 0;
      const va = a.status.version, vb = b.status.version;
      return wgSort.descending ? compareVersions(vb, va) : compareVersions(va, vb);
    });
  }
  if (key === 'profiles') {
    const d = wgSort.descending ? -1 : 1;
    return byName.sort((a, b) => (wgProfilesTotal(a.status) - wgProfilesTotal(b.status)) * d);
  }
  return wgSort.descending ? byName.reverse() : byName;
}

function wgStatusCell(s) {
  const st = s.status || {};
  const stateKey = wgState(st);
  const badgeCls = stateKey === 'installed' ? 'on' : (stateKey === 'classic' ? 'ssl-warn' : 'off');
  // title — подпись статуса (на мобиле бейдж превращается в цветной маркер);
  // svc-badge-absent — красный крест на мобиле
  const title = stateKey === 'classic' ? ' title="Требуется миграция в формат Bot4VPS"'
    : ` title="${WG_STATUS_LABEL[stateKey].replace(/^\S+\s/, '')}"`;
  const absentCls = stateKey === 'absent' ? ' svc-badge-absent' : '';
  // Индикатор импортированных профилей — как был у карточек управления.
  let imported = '';
  if (stateKey === 'installed') {
    const hasImported = Array.isArray(st.profiles) && st.profiles.some(pr => pr && pr.managed === false);
    if (hasImported) {
      imported = ` <button type="button" class="wg-imported-indicator" data-imported-open="${esc(s.id)}" title="Есть импортированные профили" aria-label="Есть импортированные профили">⚠</button>`;
    }
  }
  return `<span class="badge ${badgeCls}${absentCls}"${title}>${WG_STATUS_LABEL[stateKey]}</span>${imported}`;
}

/** Endpoint — «IP» этой таблицы: скрыт по умолчанию (•••), глаз в заголовке
 *  и построчное раскрытие, копирование. Показывается с портом, если он
 *  известен (client Endpoint = host:port). Классы переиспользуем от
 *  IP-колонки «Серверов», чтобы не плодить параллельные стили. */
function wgEndpointText(s) {
  const st = (s && s.status) || {};
  const ep = String(st.endpoint || '').trim();
  if (!ep) return '';
  const port = st.port != null && String(st.port).trim() !== '' ? ':' + st.port : '';
  return ep + port;
}

function wgEndpointCell(s) {
  const id = String(s.id ?? '');
  const ep = wgEndpointText(s);
  if (!ep) return '<span class="server-host-empty">—</span>';
  const value = wgRevealAllEndpoints || wgEndpointRevealed.has(id)
    ? `<span class="server-host-value">${esc(ep)}</span>`
    : `<button type="button" class="server-host-reveal" data-wg-endpoint-reveal="${esc(id)}"
               title="Показать Endpoint" aria-label="Показать Endpoint сервера «${esc(s.name || '')}»">
         <span aria-hidden="true">••••••••</span>
       </button>`;
  return `<span class="server-host-content">
    ${value}
    <button type="button" class="server-host-copy" data-wg-endpoint-copy="${esc(id)}"
            title="Копировать Endpoint" aria-label="Копировать Endpoint сервера «${esc(s.name || '')}»">
      <span aria-hidden="true">⧉</span>
    </button>
  </span>`;
}

function wgRowCells(s) {
  const st = s.status || {};
  const stateKey = wgState(st);
  const name = `<td class="server-name-cell" data-label="Имя"><strong>${esc(s.name || '—')}</strong></td>`;
  // Недоступный сервер: колонки сервиса не показываем — работа невозможна
  // (строка некликабельна). Причина — оффлайн или закрытый SSH-порт.
  const blocked = serviceBlocked(s);
  if (blocked) {
    const [full, short] = WG_BLOCKED_NOTE[blocked];
    return `${name}
      <td colspan="4" class="svc-offline-cell"><span class="svc-offline-note">
        <span class="svc-offline-note-full">${full}</span>
        <span class="svc-offline-note-short">${short}</span>
      </span></td>`;
  }
  const status = `<td class="wg-status-cell" data-label="Статус">${wgStatusCell(s)}</td>`;
  if (stateKey === 'installed') {
    const stats = st.stats || {};
    return `${name}${status}
      <td class="wg-version-cell" data-label="Версия">${esc(shortVer(st.version) || '—')}</td>
      <td class="wg-profiles-cell" data-label="Профили">${Number(stats.online || 0)}/${wgProfilesTotal(st)}</td>
      <td class="server-host-cell wg-endpoint-cell" data-label="Endpoint">${wgEndpointCell(s)}</td>`;
  }
  // Не установлен / классический конфиг: вместо Версии/Endpoint/Профилей —
  // объединённая область с центрированным действием.
  const action = stateKey === 'classic'
    ? `<button type="button" class="wg-row-action" data-migrate="${esc(s.id)}"><span class="svc-btn-emoji">♻️ </span>Миграция</button>`
    : `<button type="button" class="wg-row-action" data-install="${esc(s.id)}"><span class="svc-btn-emoji">🟢 </span>Установить</button>`;
  return `${name}${status}
    <td colspan="3" class="wg-row-action-cell">${action}</td>`;
}

// ---------------- заголовки таблицы ----------------

function wgSortHeader(key, label) {
  const active = wgSort.key === key;
  const descending = active && wgSort.descending;
  const ariaSort = active ? (descending ? 'descending' : 'ascending') : 'none';
  return `<th aria-sort="${ariaSort}">
    <span class="wg-col-head">
      <button type="button" class="server-column-sort${active ? ' on' : ''}" data-wg-sort="${esc(key)}"
              aria-pressed="${active ? 'true' : 'false'}"
              title="Сортировать по столбцу «${esc(label)}»">
        <span>${esc(label)}</span>
        <span class="server-sort-arrow" aria-hidden="true">${active ? (descending ? '↓' : '↑') : ''}</span>
      </button>
    </span>
  </th>`;
}

/** Заголовок «Статус»: цикл из трёх раскладок (4-й клик = 1-му), поэтому
 *  стрелка одна из ↑ / ↓ / ⇅ по текущей раскладке. */
function wgStatusHeader() {
  const active = wgSort.key === 'status';
  const arrow = active ? ['↑', '↓', '⇅'][wgStatusRotation] : '';
  const ariaSort = active
    ? (wgStatusRotation === 1 ? 'descending' : (wgStatusRotation === 2 ? 'other' : 'ascending'))
    : 'none';
  return `<th aria-sort="${ariaSort}">
    <span class="wg-col-head">
      <button type="button" class="server-column-sort${active ? ' on' : ''}" data-wg-sort="status"
              aria-pressed="${active ? 'true' : 'false'}"
              title="Группировать по статусу">
        <span>Статус</span>
        <span class="server-sort-arrow" aria-hidden="true">${arrow}</span>
      </button>${statusFilterBtn('wireguard')}
    </span>
  </th>`;
}

function wgEndpointHeader() {
  const label = wgRevealAllEndpoints ? 'Скрыть Endpoint всех серверов' : 'Показать Endpoint всех серверов';
  return `<th>
    <span class="server-host-heading">
      <span>Endpoint</span>
      <button type="button" class="server-host-visibility${wgRevealAllEndpoints ? ' on' : ''}"
              data-wg-endpoint-visibility-toggle aria-pressed="${wgRevealAllEndpoints ? 'true' : 'false'}"
              title="${label}" aria-label="${label}">
        <span aria-hidden="true">👁</span>
      </button>
    </span>
  </th>`;
}

// ---------------- рендер ----------------

function renderWgRows() {
  const list = sortedWgServers(filteredWgServers());
  if (!list.length) {
    return Object.keys(statusMap).length
      ? '<tr><td colspan="5" class="wg-empty-row">Все серверы скрыты фильтром статуса</td></tr>'
      : '<tr><td colspan="5" class="wg-empty-row">Нет серверов</td></tr>';
  }
  return list.map(s => {
    const stateKey = wgState(s.status || {});
    // Кликабельна только установленная строка на доступном сервере
    // (остальные подсвечиваются, но без перехода)
    const interactive = stateKey === 'installed' && !serviceBlocked(s);
    return `<tr class="server-table-row${interactive ? '' : ' wg-row-static'}"
                data-sid="${esc(s.id)}"${interactive ? ' tabindex="0" role="button"' : ''}>${wgRowCells(s)}</tr>`;
  }).join('');
}

function renderWgServers() {
  const el = document.getElementById('wg-servers');
  if (!el) return;
  if (!Object.keys(statusMap).length) {
    el.innerHTML = '<div class="empty">Нет серверов</div>';
    return;
  }
  el.innerHTML = `<div class="server-table-wrap">
    <table class="server-table wg-server-table">
      <thead><tr>
        ${wgSortHeader('name', 'Имя сервера')}
        ${wgStatusHeader()}
        ${wgSortHeader('version', 'Версия')}
        ${wgSortHeader('profiles', 'Профили')}
        ${wgEndpointHeader()}
      </tr></thead>
      <tbody>${renderWgRows()}</tbody>
    </table>
  </div>`;
  bindStatusFilter('wireguard', WG_STATUS_FILTERS, renderWgServers);
}

/** Клик по строке — только установленным сервисом: открывается экран WG
 *  этого сервера. «Классический конфиг» и «Не установлен» никуда не ведут
 *  (действие — кнопка в объединённой области). */
async function openWgRow(id) {
  const srv = statusMap[id] || {};
  if (serviceBlocked(srv) || wgState(srv.status || {}) !== 'installed') return;
  openWgServer(id);
}

// ---------------- события таблицы списка ----------------

function bindWgServersList() {
  const el = document.getElementById('wg-servers');
  if (!el || el.dataset.bound) return;
  el.dataset.bound = '1';

  el.addEventListener('click', async event => {
    // Сортировка: полный ререндер (стрелки живут в thead)
    const sortBtn = event.target.closest('[data-wg-sort]');
    if (sortBtn) {
      event.preventDefault();
      event.stopPropagation();
      const key = sortBtn.dataset.wgSort;
      if (key === 'status') {
        // Цикл из трёх раскладок, 4-й клик возвращает первую
        if (wgSort.key === 'status') wgStatusRotation = (wgStatusRotation + 1) % WG_STATUS_ORDERS.length;
        wgSort = { key: 'status', descending: false };
      } else if (wgSort.key === key) {
        wgSort = { key, descending: !wgSort.descending };
      } else {
        // Версия: первый клик — от свежей к старой, остальные — по возрастанию
        wgSort = { key, descending: key === 'version' };
      }
      renderWgServers();
      return;
    }

    // Видимость Endpoint: глаз в заголовке
    const visibility = event.target.closest('[data-wg-endpoint-visibility-toggle]');
    if (visibility) {
      event.preventDefault();
      event.stopPropagation();
      wgRevealAllEndpoints = !wgRevealAllEndpoints;
      if (!wgRevealAllEndpoints) wgEndpointRevealed.clear();
      renderWgServers();
      return;
    }

    // Построчное раскрытие Endpoint
    const reveal = event.target.closest('[data-wg-endpoint-reveal]');
    if (reveal) {
      event.preventDefault();
      event.stopPropagation();
      wgEndpointRevealed.add(String(reveal.dataset.wgEndpointReveal || ''));
      renderWgServers();
      return;
    }

    // Копирование Endpoint (с портом)
    const copy = event.target.closest('[data-wg-endpoint-copy]');
    if (copy) {
      event.preventDefault();
      event.stopPropagation();
      const ep = wgEndpointText(statusMap[copy.dataset.wgEndpointCopy]);
      if (!ep) { toast('Endpoint не задан', false); return; }
      copyToClipboard(ep);
      copy.classList.add('copied');
      setTimeout(() => copy.classList.remove('copied'), 1200);
      return;
    }

    // Действия в объединённой области — исключение из клика по строке
    const installBtn = event.target.closest('[data-install]');
    if (installBtn) {
      event.preventDefault();
      event.stopPropagation();
      openInstall(installBtn.dataset.install);
      return;
    }
    const migrateBtn = event.target.closest('[data-migrate]');
    if (migrateBtn) {
      event.preventDefault();
      event.stopPropagation();
      doMigrate(migrateBtn.dataset.migrate);
      return;
    }
    const importedBtn = event.target.closest('[data-imported-open]');
    if (importedBtn) {
      event.preventDefault();
      event.stopPropagation();
      try {
        localStorage.removeItem(importBannerClosedKey(importedBtn.dataset.importedOpen));
      } catch (_) {}
      openWgServer(importedBtn.dataset.importedOpen);
      return;
    }

    // Клик по строке
    const row = event.target.closest('tr[data-sid]');
    if (row) openWgRow(row.dataset.sid);
  });

  // Enter/Space на строке — как клик
  el.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const row = event.target.closest('tr[data-sid]');
    if (!row) return;
    event.preventDefault();
    openWgRow(row.dataset.sid);
  });
}

// ---------------- отдельный экран конкретного сервера ----------------


let _wgLiveTimer = null;
function startWgLivePoll(id) {
  stopWgLivePoll();
  _wgLiveTimer = setInterval(() => {
    if (wgServerId !== id) { stopWgLivePoll(); return; }
    // не дёргаем, если открыта модалка ввода
    if (document.querySelector('.modal-bg.open')) return;
    loadWgServerDetail(id).catch(() => {});
  }, 3000);
}
function stopWgLivePoll() {
  if (_wgLiveTimer) { clearInterval(_wgLiveTimer); _wgLiveTimer = null; }
}

async function openWgServer(id, opts = {}) {
  wgServerId = id;
  wgEntryContext = opts.from === 'server' ? 'server' : 'list';
  wgServerState = null;
  try {
    wgImportedBannerHidden = localStorage.getItem(importBannerClosedKey(id)) === '1';
  } catch (_) {
    wgImportedBannerHidden = false;
  }
  try {
    localStorage.setItem('bot4vps_page', 'wireguard-server');
    localStorage.setItem('bot4vps_wg_server_id', id);
  } catch (_) {}
  // Иконка в h1 живёт отдельно — текст пишем в span, чтобы не затирать SVG.
  const titleEl = document.querySelector('#wg-srv-title .srv-title-name');
  if (titleEl) titleEl.textContent = 'WireGuard · ' + nameOf(id);
  document.getElementById('wg-srv-body').innerHTML = '<div class="empty">Загрузка…</div>';
  showPage('wireguard-server');
  await loadWgServerDetail(id);
  startWgLivePoll(id);
}

function backToWgList() {
  stopWgLivePoll();
  wgServerId = null;
  wgEntryContext = 'list';
  wgImportedBannerHidden = false;
  const ban = document.getElementById('wg-imported-banner');
  if (ban) { ban.classList.add('hidden'); ban.innerHTML = ''; }
  const indicator = document.getElementById('wg-imported-indicator');
  if (indicator) indicator.classList.add('hidden');

  try {
    localStorage.setItem('bot4vps_page', 'wireguard');
    localStorage.removeItem('bot4vps_wg_server_id');
  } catch (_) {}
  showPage('wireguard');
  loadWireguard();
}

async function loadWgServerDetail(id) {
  try {
    const d = await j(stateUrl(id));
    wgServerState = d.state || {};
    renderWgServerDetail(wgServerState);
  } catch (e) {
    document.getElementById('wg-srv-body').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function renderWgServerDetail(st) {
  const body = document.getElementById('wg-srv-body');
  if (!body) return;
  const oldPop = document.getElementById('wg-prof-pop');
  const openProfileName = oldPop && !oldPop.classList.contains('hidden')
    ? oldPop.dataset.name
    : null;
  const s = st || {};
  const profiles = Array.isArray(s.profiles) ? s.profiles : [];
  const stats = s.stats || { online: 0, total: profiles.length, rx_bytes: 0, tx_bytes: 0 };
  const totalTraffic = (Number(stats.rx_bytes) || 0) + (Number(stats.tx_bytes) || 0);

  const badgeEl = document.getElementById('wg-srv-badge');
  if (badgeEl) {
    badgeEl.innerHTML = s.installed
      ? '<span class="badge on">Установлен</span>'
      : '<span class="badge off">Не установлен</span>';
  }

  const copyBtn = (val) => {
    if (val == null || val === '' || val === '—' || val === 'не задан') return '';
    return ' <button type="button" class="icon-copy" data-copy="' + esc(String(val)) + '" title="Копировать">⧉</button>';
  };
  const pub = s.server_public_key || '';
  const iface = s.interface || s.iface || 'wg0';
  const active = (s.active || s.status || '').toString().toLowerCase();
  const isActive = active === 'active' || active === 'running' || !!s.installed;
  const statusHtml = isActive
    ? '<span class="ssh-dot ok"></span> Активен'
    : '<span class="ssh-dot err"></span> Неактивен';

  const addr = s.address != null && s.address !== '' ? String(s.address) : '—';
  const port = s.port != null ? String(s.port) : '—';
  const endpoint = s.endpoint || 'не задан';

  const infoCard = `
    <div class="info-block svc-card">
      <h2>Основная информация</h2>
      <div class="info-row"><span class="info-label">Адрес</span><span class="info-value mono">${esc(addr)}${copyBtn(addr)}</span></div>
      <div class="info-row"><span class="info-label">Порт</span><span class="info-value mono">${esc(port)}${copyBtn(port)}</span></div>
      <div class="info-row"><span class="info-label">Endpoint</span><span class="info-value mono">${esc(endpoint)}${copyBtn(endpoint === 'не задан' ? '' : endpoint)}</span></div>
      <div class="info-row"><span class="info-label">Публичный ключ</span><span class="info-value info-value-copy"><span class="mono wg-pubkey" title="${esc(pub)}">${pub ? esc(pub) : '—'}</span>${copyBtn(pub)}</span></div>
      <div class="info-row"><span class="info-label">Интерфейс</span><span class="info-value mono">${esc(iface)}</span></div>
      <div class="info-row"><span class="info-label">Статус</span><span class="info-value">${statusHtml}</span></div>
    </div>`;

  const statCard = (icon, value, label) => `
    <div class="svc-stat-card">
      <div class="svc-stat-icon">${icon}</div>
      <div class="svc-stat-val">${esc(String(value))}</div>
      <div class="svc-stat-label">${esc(label)}</div>
    </div>`;
  const statsCard = `
    <div class="info-block svc-card">
      <h2>Статистика</h2>
      <div class="svc-stats-grid-4">
        ${statCard('👥', `${stats.online || 0} / ${stats.total || profiles.length}`, 'Онлайн / Всего')}
        ${statCard('↓', fmtBytes(stats.rx_bytes), 'Получено')}
        ${statCard('↑', fmtBytes(stats.tx_bytes), 'Отправлено')}
        ${statCard('⇅', fmtBytes(totalTraffic), 'Общий трафик')}
      </div>
    </div>`;

  const ver = shortVer(s.version) || s.version || '—';
  const confPath = s.config_path || `/etc/wireguard/${iface}.conf`;
  const syncAt = s.synced_at || '';
  const daemonCard = `
    <div class="info-block svc-card">
      <h2>Демон WireGuard</h2>
      <div class="info-row"><span class="info-label">Статус</span><span class="info-value">${statusHtml}</span></div>
      <div class="info-row"><span class="info-label">Версия</span><span class="info-value">${esc(String(ver))}</span></div>
      <div class="info-row"><span class="info-label">Дата последней синхронизации</span><span class="info-value">${esc(fmtSync(syncAt) || '—')}</span></div>
      <div class="info-row"><span class="info-label">Конфигурация</span><span class="info-value mono trunc" title="${esc(confPath)}">${esc(confPath)}</span></div>
    </div>`;

  const q = (document.getElementById('wg-prof-search')?.value || '').trim().toLowerCase();
  const filtered = q
    ? profiles.filter(pr => String(pr.name || '').toLowerCase().includes(q)
        || String((pr.allowed_ips || []).join(' ')).toLowerCase().includes(q))
    : profiles;

  const statusCell = (pr) => {
    if (!pr.enabled) return '<span class="badge off">Выключен</span>';
    if (pr.connected) return '<span class="badge on">Онлайн</span>';
    return '<span class="badge ssl-warn">Офлайн</span>';
  };
  const rows = filtered.map(pr => {
    const aip = (pr.allowed_ips && pr.allowed_ips.length) ? pr.allowed_ips.join(', ') : '—';
    const pk = pr.public_key || '';
    const pkShow = pk ? (pk.length > 24 ? pk.slice(0, 24) + '…' : pk) : '—';
    const traf = `↓ ${fmtBytes(pr.rx_bytes)} · ↑ ${fmtBytes(pr.tx_bytes)}`;
    return `<tr>
      <td class="col-name"><b>${esc(pr.name)}</b>${pr.managed ? '' : ' <span class="badge ssl-warn">import</span>'}</td>
      <td class="col-ip mono">${esc(aip)}</td>
      <td class="col-key mono" title="${esc(pk)}">${esc(pkShow)}</td>
      <td class="col-status">${statusCell(pr)}</td>
      <td class="col-traf mono">${traf}</td>
      <td class="col-act">
        <button type="button" class="secondary wg-prof-menu-btn" data-pmenu="${esc(pr.name)}" title="Действия">⋯</button>
      </td>
    </tr>`;
  }).join('');

  const table = filtered.length
    ? `<div class="svc-table-wrap wg-prof-scroll"><table class="svc-table wg-prof-table">
        <thead><tr>
          <th class="col-name">Имя профиля</th>
          <th class="col-ip">IP / Адрес</th>
          <th class="col-key">Публичный ключ</th>
          <th class="col-status">Статус</th>
          <th class="col-traf">Трафик</th>
          <th class="col-act">Действия</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`
    : `<div class="empty svc-empty">Профилей нет<br><span class="hint">Добавьте первый профиль для подключения.</span></div>`;

  const hasImported = profiles.some(pr => !pr.managed);

  if (hasImported) {
    try {
      wgImportedBannerHidden = localStorage.getItem(importBannerClosedKey(wgServerId)) === '1';
    } catch (_) {}
  } else {
    wgImportedBannerHidden = false;
    try {
      localStorage.removeItem(importBannerClosedKey(wgServerId));
    } catch (_) {}
  }

  const ban = document.getElementById('wg-imported-banner');
  const indicator = document.getElementById('wg-imported-indicator');

  if (indicator) {
    indicator.classList.toggle('hidden', !hasImported);
    indicator.title = hasImported
      ? (wgImportedBannerHidden ? 'Показать информацию об импортированном профиле' : 'Скрыть информацию об импортированном профиле')
      : '';
    indicator.setAttribute('aria-label', hasImported ? 'Информация об импортированном профиле' : '');
  }

  if (ban) {
    if (hasImported) {
      ban.innerHTML = `
        <div class="wg-imported-banner-inner">
          <button type="button" class="wg-imported-banner-close" id="wg-imported-banner-close" title="Скрыть">×</button>
          <div class="wg-imported-banner-title">⚠️ Обнаружен импортированный профиль</div>
          <div class="wg-imported-banner-text">
            Этот профиль был обнаружен во время миграции существующей конфигурации WireGuard.
            <br>
            Профиль остаётся действующим — им можно продолжать пользоваться на устройствах,
            где он уже установлен.
            <br>
            Bot4VPS знает параметры подключения этого клиента (публичный ключ, IP-адрес и другие настройки),
            однако приватный ключ клиента отсутствует и восстановить его невозможно.
            <br><br>
            Поэтому для этого профиля недоступны:
            <br>❌ Скачать конфигурацию
            <br>❌ Показать QR-код
            <br><br>
            При необходимости профиль можно перевыпустить. Будет создана новая пара ключей клиента.
            <br><br>
            После перевыпуска станут доступны:
            <br>✅ Скачать конфигурацию
            <br>✅ QR-код
          </div>
        </div>`;

      ban.classList.toggle('hidden', wgImportedBannerHidden);

      const closeBtn = document.getElementById('wg-imported-banner-close');
      if (closeBtn) {
        closeBtn.onclick = () => {
          wgImportedBannerHidden = true;
          try {
            localStorage.setItem(importBannerClosedKey(wgServerId), '1');
          } catch (_) {}
          ban.classList.add('hidden');
          if (indicator) {
            indicator.title = 'Показать информацию об импортированном профиле';
          }
        };
      }

      if (indicator) {
        indicator.onclick = () => {
          wgImportedBannerHidden = false;
          try {
            localStorage.removeItem(importBannerClosedKey(wgServerId));
          } catch (_) {}
          ban.classList.remove('hidden');
          indicator.title = 'Скрыть информацию об импортированном профиле';
        };
      }
    } else {
      wgImportedBannerHidden = false;
      ban.classList.add('hidden');
      ban.innerHTML = '';
      if (indicator) indicator.onclick = null;
    }
  }

  const searchVal = esc(document.getElementById('wg-prof-search')?.value || '');
  const profilesCard = `
    <div class="info-block svc-card svc-profiles${hasImported ? ' has-reissue' : ''}">
      <div class="svc-card-head svc-card-head-one-line">
        <h2>Профили <span class="hint">(${profiles.length})</span></h2>
        <div class="svc-card-actions">
          <input type="search" id="wg-prof-search" placeholder="🔍 Поиск профиля…" value="${searchVal}"/>
          <button type="button" class="secondary" data-padd>＋ Добавить профиль</button>
        </div>
      </div>
      ${table}
    </div>`;

  const sideActions = `
    <div class="info-block svc-card svc-side-actions">
      <h2>Дополнительные действия</h2>
      <button type="button" class="svc-action" data-wg-side="export">
        <b>Экспорт конфигурации</b>
        <span>Скачать .conf выбранных профилей</span>
      </button>
      <button type="button" class="svc-action" data-wg-side="qr">
        <b>QR-код для подключения</b>
        <span>Сгенерировать QR-код</span>
      </button>
      ${hasImported ? `<button type="button" class="svc-action svc-action-warn" data-reissue-all>
        <b>♻️ Перевыпустить все</b>
        <span>Сделать импортированные профили управляемыми</span>
      </button>` : ''}
      <button type="button" class="svc-action" data-wg-side="reset-stats">
        <b>Сбросить статистику</b>
        <span>Обнулить трафик и счётчики</span>
      </button>
      <button type="button" class="svc-action svc-action-danger" data-rm>
        <b>🗑 Удалить WireGuard</b>
        <span>Полностью удалить сервис с сервера</span>
      </button>
    </div>`;

  body.innerHTML = `
    <div class="svc-top-grid">${infoCard}${statsCard}${daemonCard}</div>
    <div class="svc-main-grid">${profilesCard}${sideActions}</div>
    <div id="wg-prof-pop" class="wg-prof-pop hidden"></div>`;

  body.querySelectorAll('[data-copy]').forEach(el => {
    el.onclick = (e) => { e.preventDefault(); e.stopPropagation(); copyToClipboard(el.dataset.copy); };
  });
  body.querySelector('[data-padd]')?.addEventListener('click', addProfile);
  body.querySelector('[data-rm]')?.addEventListener('click', async () => {
    if (!(await wgConfirm(
      'Удалить WireGuard',
      'Удалить WireGuard с этого сервера? Профили и конфигурация будут удалены.',
      'Удалить', 'Отмена',
    ))) return;
    enqueueAction(wgServerId, 'remove', {}, 'Удаление в очереди');
  });
  body.querySelector('[data-reissue-all]')?.addEventListener('click', () => reissueAllProfiles(wgServerId));
  body.querySelector('[data-wg-side="export"]')?.addEventListener('click', () => openProfilePicker('export'));
  body.querySelector('[data-wg-side="qr"]')?.addEventListener('click', () => openProfilePicker('qr'));
  body.querySelector('[data-wg-side="reset-stats"]')?.addEventListener('click', resetWgStats);
  body.querySelectorAll('[data-pmenu]').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      openProfileMenu(btn, btn.dataset.pmenu);
    };
  });
  if (openProfileName) {
    const btn = body.querySelector(`[data-pmenu="${CSS.escape(openProfileName)}"]`);
    if (btn) openProfileMenu(btn, openProfileName);
  }
  const search = body.querySelector('#wg-prof-search');
  if (search) {
    search.oninput = () => {
      const v = search.value;
      renderWgServerDetail(wgServerState);
      const again = document.getElementById('wg-prof-search');
      if (again) { again.value = v; again.focus(); again.selectionStart = again.selectionEnd = v.length; }
    };
  }
}

function openProfileMenu(anchor, name) {
  const pop = document.getElementById('wg-prof-pop');
  if (!pop) return;
  const p = (wgServerState && Array.isArray(wgServerState.profiles) ? wgServerState.profiles : [])
    .find(x => x.name === name);
  if (!p) return;
  const toggleLbl = p.enabled ? 'Выключить' : 'Включить';
  const managedItems = p.managed
    ? `<button type="button" data-pm="download">Скачать .conf</button>
       <button type="button" data-pm="qr">Показать QR</button>`
    : `<button type="button" data-pm="reissue">Перевыпустить</button>`;
  pop.innerHTML = `
    ${managedItems}
    <button type="button" data-pm="toggle">${esc(toggleLbl)}</button>
    <button type="button" data-pm="rename">Переименовать</button>
    <hr/>
    <button type="button" class="danger" data-pm="delete">Удалить</button>`;
  pop.classList.remove('hidden');
  const r = anchor.getBoundingClientRect();
  const popW = pop.offsetWidth || 200;
  // fixed-координаты (как в docker.js openContainerMenu): меню не уезжает
  // за правый край и не открывается за нижней границей viewport.
  let left = r.right - popW;
  let top = r.bottom + 4;

  left = Math.max(8, Math.min(left, window.innerWidth - popW - 8));

  const popH = pop.offsetHeight;
  if (top + popH > window.innerHeight - 8) {
    top = Math.max(8, r.top - popH - 4);
  }
  pop.style.position = 'fixed';

  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  pop.dataset.name = name;

  const close = () => {
    pop.classList.add('hidden');
    document.removeEventListener('click', onDoc, true);
  };
  const onDoc = (ev) => {
    if (pop.contains(ev.target) || anchor.contains(ev.target)) return;
    close();
  };
  setTimeout(() => document.addEventListener('click', onDoc, true), 0);

  pop.querySelectorAll('[data-pm]').forEach(b => {
    b.onclick = async (ev) => {
      ev.stopPropagation();
      const act = b.dataset.pm;
      close();
      await runProfileMenuAction(name, act);
    };
  });
}

async function runProfileMenuAction(name, act) {
  // Скачивание — только клиентский GET; остальное — существующий profileAction()
  if (act === 'download') {
    const a = document.createElement('a');
    a.href = srvBase(wgServerId) + '/config/' + encodeURIComponent(name);
    a.download = name + '.conf';
    a.click();
    return;
  }
  if (act === 'qr') {
    showQr(wgServerId, name);
    return;
  }
  if (act === 'toggle') {
    const pr = (wgServerState.profiles || []).find(x => x.name === name);
    await profileAction(name, 'toggle', { enabled: !(pr && pr.enabled) });
    return;
  }
  await profileAction(name, act);
}

async function resetWgStats() {
  if (!(await wgConfirm(
    'Сбросить статистику',
    'Обнулить счётчики трафика WireGuard на этом сервере?',
    'Сбросить', 'Отмена',
  ))) return;
  try {
    // Сначала прямой endpoint (быстрый сброс кэша + сервис), иначе enqueue
    try {
      await j(srvBase(wgServerId) + '/reset-stats', { method: 'POST' });
      toast('Статистика сброшена', true);
      await loadWgServerDetail(wgServerId);
      return;
    } catch (e1) {
      await enqueueAction(wgServerId, 'reset_stats', {}, 'Сброс статистики в очереди');
      setTimeout(() => { if (wgServerId) loadWgServerDetail(wgServerId); }, 2500);
    }
  } catch (e) {
    toast(e.message || String(e), false);
  }
}

function openProfilePicker(mode) {
  const list = (wgServerState && Array.isArray(wgServerState.profiles) ? wgServerState.profiles : [])
    .filter(pr => pr.managed !== false);
  if (!list.length) {
    toast(mode === 'qr' ? 'Нет профилей для QR' : 'Нет профилей для экспорта', false);
    return;
  }
  const modal = document.getElementById('wg-profile-picker');
  if (!modal) {
    toast('Модалка выбора профиля не найдена', false);
    return;
  }
  modal.dataset.mode = mode;
  document.getElementById('wg-picker-title').textContent =
    mode === 'qr' ? 'QR-код — выберите профиль' : 'Экспорт конфигурации';
  const multi = mode === 'export';
  const box = document.getElementById('wg-picker-list');
  box.innerHTML = list.map(pr => `
    <label class="svc-pick-row">
      <input type="${multi ? 'checkbox' : 'radio'}" name="wg-pick" value="${esc(pr.name)}"/>
      <span>${esc(pr.name)}</span>
    </label>`).join('');
  const okBtn = document.getElementById('wg-picker-ok');
  if (okBtn) okBtn.textContent = multi ? 'Скачать' : 'Выполнить';
  document.getElementById('wg-picker-search').value = '';
  openModalEl(modal);
}

function applyProfilePicker() {
  const modal = document.getElementById('wg-profile-picker');
  const mode = modal && modal.dataset.mode;
  if (mode === 'export') {
    const checked = [...(modal.querySelectorAll('input[name="wg-pick"]:checked') || [])].map(i => i.value);
    if (!checked.length) { toast('Выберите хотя бы один профиль', false); return; }
    closeModalEl(modal);
    (async () => {
      try {
        if (checked.length === 1) {
          const a = document.createElement('a');
          a.href = srvBase(wgServerId) + '/config/' + encodeURIComponent(checked[0]);
          a.download = checked[0] + '.conf';
          a.click();
          toast('Скачивание…', true);
          return;
        }
        const r = await fetch(srvBase(wgServerId) + '/export-zip', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ names: checked }),
        });
        if (!r.ok) {
          let d; try { d = await r.json(); } catch { d = {}; }
          throw new Error(d.detail || ('HTTP ' + r.status));
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'wireguard-profiles.zip';
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        toast('ZIP скачан (' + checked.length + ' проф.)', true);
      } catch (e) {
        toast(e.message || String(e), false);
      }
    })();
    return;
  }
  const sel = modal && modal.querySelector('input[name="wg-pick"]:checked');
  if (!sel) { toast('Выберите профиль', false); return; }
  closeModalEl(modal);
  if (mode === 'qr') showQr(wgServerId, sel.value);
}


function profileGridCard(p) {
  const dot = !p.enabled ? '⚪' : (p.connected ? '🟢' : '🟡');
  const statusTxt = !p.enabled ? 'Выключен' : (p.connected ? 'Подключён' : 'Не подключён');
  const kind = p.managed ? '' : '<span class="badge ssl-warn">📦 Импортированный</span>';
  const aip = (p.allowed_ips && p.allowed_ips.length) ? p.allowed_ips.map(x => esc(x)).join('<br>') : '—';
  const pub = p.public_key ? esc(p.public_key) : '—';
  return `<div class="card wg-prof-card">
    <div class="card-body">
      <h3>${esc(p.name)} ${kind}</h3>
      <div class="wg-card-info">${dot} ${esc(statusTxt)}</div>
      <div class="wg-card-info">handshake: <b>${esc(p.last_handshake || 'никогда')}</b></div>
      <div class="wg-prof-field"><span class="wg-prof-label">Публичный ключ</span><span class="mono wg-prof-val">${pub}</span></div>
      <div class="wg-prof-field"><span class="wg-prof-label">IP / AllowedIPs</span><span class="mono wg-prof-val">${aip}</span></div>
      <div class="wg-prof-traffic"><span>↓ ${fmtBytes(p.rx_bytes)}</span><span>↑ ${fmtBytes(p.tx_bytes)}</span></div>
    </div>
    <div class="card-actions"><button type="button" data-pdetail="${esc(p.name)}">Details</button></div>
  </div>`;
}

// ---------------- детали профиля (модалка) ----------------

function openProfileDetail(name) {
  const p = (wgServerState && Array.isArray(wgServerState.profiles) ? wgServerState.profiles : []).find(x => x.name === name);
  if (!p) return;
  const dot = !p.enabled ? '⚪' : (p.connected ? '🟢' : '🟡');
  const statusTxt = !p.enabled ? 'Выключен' : (p.connected ? 'Подключён' : 'Не подключён');
  const aip = (p.allowed_ips && p.allowed_ips.length) ? p.allowed_ips.map(x => esc(x)).join('<br>') : '—';
  const pub = p.public_key ? `<span class="copiable mono" data-copy="${esc(p.public_key)}" title="Нажмите, чтобы скопировать">${esc(p.public_key)}</span>` : '—';

  document.getElementById('wg-profile-title').textContent = (p.managed ? '' : '📦 ') + p.name;
  const dl = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  // Управляемый: скачать/QR. Импортированный: перевыпустить (после него станет управляемым).
  const conf = p.managed
    ? `<a class="btn" href="${srvBase(wgServerId)}/config/${encodeURIComponent(p.name)}" download>📥 Скачать .conf</a>
       <button type="button" class="secondary" data-pact="qr">📱 Показать QR</button>`
    : `<button type="button" data-pact="reissue">♻️ Перевыпустить</button>`;
  const toggleLbl = p.enabled ? 'Выключить' : 'Включить';
  const html = `<dl class="kv">
      ${dl('Статус', dot + ' ' + esc(statusTxt))}
      ${dl('Последний handshake', esc(p.last_handshake || 'никогда'))}
      ${dl('Публичный ключ', pub)}
      ${dl('Внутренний IP', aip)}
      ${dl('Получено', fmtBytes(p.rx_bytes))}
      ${dl('Отправлено', fmtBytes(p.tx_bytes))}
    </dl>
    <div class="actions" style="margin-top:.6rem">${conf}</div>
    <div class="actions" style="margin-top:.4rem">
      <button type="button" class="secondary" data-pact="toggle">${esc(toggleLbl)}</button>
      <button type="button" class="secondary" data-pact="rename">Переименовать</button>
      <button type="button" class="danger" data-pact="delete">Удалить</button>
    </div>`;
  const m = document.getElementById('wg-profile-body');
  m.innerHTML = html;
  m.querySelectorAll('[data-copy]').forEach(el => el.onclick = () => copyToClipboard(el.dataset.copy));
  m.querySelectorAll('[data-pact]').forEach(b => b.onclick = () => {
    const act = b.dataset.pact;
    if (act === 'toggle') profileAction(p.name, act, { enabled: !p.enabled });
    else profileAction(p.name, act);
  });
  openModalEl(document.getElementById('wg-profile-modal'));
}

async function profileAction(name, act, extra = {}) {
  const id = wgServerId;
  const base = srvBase(id) + '/profiles';
  const post = (url, body) => j(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const ok = r => {
    if (!r || r.success === false) throw new Error((r && r.error) || 'ошибка');
    if (r.sync_ok === false) toast('Операция выполнена, но кэш не обновлён: ' + (r.sync_error || 'sync error'), false);
  };
  try {
    if (act === 'toggle') {
      // enabled явно: не полагаемся на кэш get_profiles (баг «Включить не работает»)
      const body = (extra.enabled !== undefined) ? { enabled: !!extra.enabled } : {};
      ok(await post(`${base}/${encodeURIComponent(name)}/toggle`, body));
      toast(extra.enabled ? 'Профиль включён' : 'Профиль выключен', true);
    } else if (act === 'rename') {
      const nn = await wgPrompt('Переименование', `Новое имя для «${name}»:`, name, '', 'Переименовать');
      if (nn === null) return;
      if (!nn.trim()) { toast('Пустое имя', false); return; }
      ok(await post(`${base}/${encodeURIComponent(name)}/rename`, { new_name: nn.trim() })); toast('Переименован', true);
    } else if (act === 'delete') {
      if (!(await wgConfirm('Удаление профиля', `Удалить профиль «${name}»?`, 'Удалить'))) return;
      ok(await j(`${base}/${encodeURIComponent(name)}`, { method: 'DELETE' })); toast('Удалён', true);
      closeModalEl(document.getElementById('wg-profile-modal'));
    } else if (act === 'reissue') {
      if (!(await wgConfirm('Перевыпуск ключей', `Перевыпустить ключи профиля «${name}»?\n\nСтарый .conf и QR станут недействительными — клиенту потребуется новый конфиг. IP-адрес сохранится.`, 'Перевыпустить'))) return;
      ok(await post(`${base}/${encodeURIComponent(name)}/reissue`, {})); toast('Перевыпущен', true);
      closeModalEl(document.getElementById('wg-profile-modal'));
    } else if (act === 'qr') {
      return showQr(id, name);
    }
    await loadWgServerDetail(id);
  } catch (e) { toast(e.message, false); }
}

async function addProfile() {
  const id = wgServerId;
  const nm = await wgPrompt('Новый профиль', 'Имя (латиница, цифры, -, _):', '', 'my-phone', 'Создать');
  if (nm === null) return;
  if (!nm.trim()) { toast('Пустое имя', false); return; }
  try {
    const r = await j(srvBase(id) + '/profiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: nm.trim() }) });
    if (!r || r.success === false) throw new Error((r && r.error) || 'ошибка');
    toast('Профиль добавлен', true);
    await loadWgServerDetail(id);
  } catch (e) { toast(e.message, false); }
}

// ---------------- изменение конфигурации (частичное) ----------------

function openConfigModal() {
  const s = wgServerState || {};
  document.getElementById('wg-cfg-address').value = s.address || '';
  document.getElementById('wg-cfg-port').value = s.port != null ? s.port : '';
  document.getElementById('wg-cfg-endpoint').value = s.endpoint || '';
  document.getElementById('wg-cfg-dns').value = s.dns || '';
  const warn = document.getElementById('wg-config-warn');
  if (warn) warn.textContent = '';
  openModalEl(document.getElementById('wg-config-modal'));
}

async function saveConfig() {
  const s = wgServerState || {};
  const address = document.getElementById('wg-cfg-address').value.trim();
  const portRaw = document.getElementById('wg-cfg-port').value.trim();
  const endpoint = document.getElementById('wg-cfg-endpoint').value.trim();
  const dns = document.getElementById('wg-cfg-dns').value.trim();
  const warn = document.getElementById('wg-config-warn');

  // diff против текущего state — отправляем ТОЛЬКО изменившиеся поля (ТЗ §13).
  const body = {};
  if (address && address !== (s.address || '')) body.address = address;
  if (portRaw && portRaw !== (s.port != null ? String(s.port) : '')) body.port = Number(portRaw);
  if (endpoint !== (s.endpoint || '')) body.endpoint = endpoint;   // "" = явный сброс
  if (dns && dns !== (s.dns || '')) body.dns = dns;
  if (!Object.keys(body).length) { toast('Нет изменений', false); return; }

  // Смена адреса/порта → рестарт интерфейса: предупреждаем (ТЗ §15).
  if (('port' in body) || ('address' in body)) {
    if (!(await wgConfirm('Применение конфигурации',
      'Изменение адреса/порта перезапустит интерфейс — кратковременное прерывание активных подключений. Продолжить?',
      'Применить'))) return;
  }
  try {
    await j(srvBase(wgServerId) + '/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    toast('Конфигурация сохранена', true);
    closeModalEl(document.getElementById('wg-config-modal'));
    await loadWgServerDetail(wgServerId);
  } catch (e) {
    if (warn) warn.textContent = e.message; else toast(e.message, false);
  }
}

// ---------------- установка / миграция / перевыпуск (тяжёлые — через очередь) ----------------

async function enqueueAction(id, action, params, msg, onTask) {
  try {
    const r = await j(`${srvBase(id)}/enqueue/${encodeURIComponent(action)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params }),
    });
    if (onTask && r.task) { onTask(r.task); return; }
    toast(msg || 'В очереди', true);
    if (r.task) watchTask(r.task.id, id, action);
  } catch (e) { toast(e.message, false); }
}

async function doMigrate(id) {
  const st = (statusMap[id] && statusMap[id].status) || {};
  const ep = await wgPrompt('Миграция', 'Перевод классического конфига в формат Bot4VPS.\n\nEndpoint для клиентов (внешний IP/домен).\nПусто — без endpoint.', st.endpoint || '', 'vpn.example.com', 'Далее');
  if (ep === null) return;
  const endpoint = ep.trim();
  if (endpoint) {
    try {
      await j(srvBase(id) + '/endpoint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint }) });
    } catch (e) { toast('Endpoint не установлен: ' + e.message, false); }
  }
  const reissue = await wgConfirm(
    'Перевыпуск профилей',
    'Миграция переносит профили без смены ключей — клиентские конфиги продолжат работать.\n\nПеревыпустить ключи сейчас?\nПри «Да» старые .conf станут недействительными (IP сохранятся).',
    'Да, перевыпустить', 'Нет, оставить как есть');
  await enqueueAction(id, 'migrate', { reissue }, reissue ? 'Миграция + перевыпуск в очереди' : 'Миграция в очереди');
}

async function reissueAllProfiles(id) {
  if (!(await wgConfirm(
    'Перевыпуск профилей',
    'Будут созданы новые ключи. Старые конфигурации импортированных профилей перестанут работать.\n\nПосле операции необходимо скачать новые конфигурации. IP-адреса сохранятся.\n\nПродолжить?',
    '♻️ Перевыпустить импортированные', 'Отмена',
  ))) return;
  await enqueueAction(id, 'reissue_all', {}, 'Перевыпуск профилей в очереди');
}

// ---------------- сопровождение фоновой задачи ----------------

/** Тихое сопровождение задачи: прогресс-лога на странице больше нет —
 *  по завершении тост (успех/ошибка) и обновление данных. */
function watchTask(taskId, serverId, action) {
  const tick = async () => {
    try {
      const t = await j('/api/tasks/' + encodeURIComponent(taskId));
      if (t.is_done) {
        clearInterval(timers[taskId]); delete timers[taskId];
        if (action === 'remove') {
          if (t.success) {
            const returnToServer = wgEntryContext === 'server' && serverId;

            stopWgLivePoll();
            wgServerId = null;

            try {
              localStorage.removeItem('bot4vps_wg_server_id');
            } catch (_) {}

            if (returnToServer) {
              try {
                const { openServer } = await import('./servers.js?v=20260915-sysfix-v2');
                await openServer(serverId);
              } catch (_) {
                backToWgList();
              }
            } else {
              backToWgList();
            }
            toast('WireGuard удалён', true);
          } else {
            toast(t.error || 'Удаление WireGuard завершилось с ошибкой', false);
          }
          return;
        }
        if (t.success) {
          toast(`${t.emoji || '✅'} ${t.name || 'Задача'} — выполнена`, true);
        } else {
          toast(t.error || `${t.name || 'Задача'} завершилась с ошибкой`, false);
        }
        const onDetail = document.getElementById('page-wireguard-server')?.classList.contains('on');
        if (onDetail && serverId) {
          await loadWgServerDetail(serverId);
        } else {
          await loadWireguard();
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

export function stopWgTimers() {
  stopWgLivePoll();
  Object.keys(timers).forEach(k => { clearInterval(timers[k]); delete timers[k]; });
}

// ---------------- модалка установки ----------------

export async function openInstall(id) {
  const s = statusMap[id] || {};
  installTarget = { id, host: s.host || '', name: s.name || id };
  if (!installParams) {
    try { installParams = (await j(`/api/services/${SID}/params`)).params || []; }
    catch (e) { toast(e.message, false); return; }
  }
  buildInstallParams(installParams);
  const warn = document.getElementById('wg-install-warn');
  const epInput = document.getElementById('wg-install-endpoint');
  if (isPrivateHost(s.host)) {
    warn.textContent = '⚠️ Host сервера приватный — клиенты вне сети не смогут подключиться. Укажите публичный Endpoint.';
    epInput.value = '';
  } else {
    warn.textContent = '';
    epInput.value = s.host || '';
  }
  document.getElementById('wg-install-title').textContent = '🟢 Установка WireGuard · ' + (s.name || id);
  openModalEl(document.getElementById('wg-install-modal'));
}

function buildInstallParams(params) {
  const box = document.getElementById('wg-install-params');
  box.innerHTML = '';
  const values = {};
  params.forEach(p => {
    const wrap = document.createElement('div');
    wrap.className = 'run-param';
    const label = document.createElement('label');
    label.className = 'row';
    label.textContent = (p.description || p.name) + (p.required === false ? ' (необяз.)' : '');
    let field;
    if (p.type === 'select') {
      field = document.createElement('select');
      (p.choices || []).forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; field.appendChild(o); });
    } else {
      field = document.createElement('input');
      field.type = p.type === 'number' ? 'number' : 'text';
      if (p.min != null) field.min = p.min;
      if (p.max != null) field.max = p.max;
      if (p.pattern) field.pattern = p.pattern;
    }
    field.value = p.default != null ? p.default : '';
    values[p.name] = field.value;
    field.addEventListener('input', () => { values[p.name] = field.value; });
    wrap.appendChild(label);
    wrap.appendChild(field);
    box.appendChild(wrap);
  });
  box._values = values;
}

async function confirmInstall() {
  if (!installTarget) return;
  const box = document.getElementById('wg-install-params');
  const params = Object.assign({}, box._values || {});
  const ep = document.getElementById('wg-install-endpoint').value.trim();
  if (ep) params.WG_ENDPOINT = ep;
  closeModalEl(document.getElementById('wg-install-modal'));
  // Живой прогресс в модалке (паттерн установки 3x-ui): лог со
  // stick-to-bottom, «в фон ↓», финал с «Закрыть». Тоста-заглушки больше нет.
  await enqueueAction(
    installTarget.id, 'install', params, null,
    task => openTaskModal({
      title: `Установка WireGuard — ${installTarget.name}`,
      taskId: task.id,
      doneLabel: 'Готово — WireGuard установлен',
      onDone: t => { if (t.success) window.refreshAfterServiceChange?.(installTarget.id); },
      onClose: () => { loadWireguard(); },
    }),
  );
}

// ---------------- QR ----------------

function showQr(id, name) {
  document.getElementById('wg-qr-title').textContent = '📱 ' + name;
  document.getElementById('wg-qr-img').src = `${srvBase(id)}/qr/${encodeURIComponent(name)}`;
  openModalEl(document.getElementById('wg-qr-modal'));
}

// ---------------- bind ----------------

export function bindWireguardUI() {
  // Лёгкие пробы доступности идут фоном, пока панель открыта (SSE);
  // при смене online/offline перечитываем список — оффлайн-строки и данные
  // сервиса актуальны без захода на страницу «Серверы».
  window.addEventListener('bot4vps:availability-changed', () => {
    if (document.getElementById('page-wireguard')?.classList.contains('on')) loadWireguard();
  });

  bindWgServersList();

  // диалог (confirm/prompt) — кнопки OK/Cancel; backdrop НЕ закрывает
  const dlg = document.getElementById('wg-dialog');
  document.getElementById('wg-dialog-ok')?.addEventListener('click', () => {
    if (dialogMode === 'prompt') closeDialog(document.getElementById('wg-dialog-input').value);
    else closeDialog(true);
  });
  document.getElementById('wg-dialog-cancel')?.addEventListener('click', () =>
    closeDialog(dialogMode === 'prompt' ? null : false));
  document.getElementById('wg-dialog-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); document.getElementById('wg-dialog-ok').click(); }
    else if (e.key === 'Escape') document.getElementById('wg-dialog-cancel').click();
  });

  // экран конкретного сервера
  document.getElementById('btn-back-wg')?.addEventListener('click', backToWgList);
  document.getElementById('btn-back-server')?.addEventListener('click', async () => {
    if (!wgServerId) return;

    try {
      const { openServer } = await import('./servers.js?v=20260915-sysfix-v2');
      await openServer(wgServerId);
    } catch (e) {
      console.error('Не удалось открыть карточку сервера:', e);
      showPage('servers');
    }
  });
  document.getElementById('wg-srv-refresh')?.addEventListener('click', async () => {
    if (!wgServerId) return;

    try {
      await j(`${srvBase(wgServerId)}/sync`, { method: 'POST' });
      await loadWgServerDetail(wgServerId);
      toast('Синхронизация выполнена', true);
    } catch (e) {
      toast(e.message, false);
    }
  });
  document.getElementById('wg-srv-config')?.addEventListener('click', () => openConfigModal());
  document.getElementById('wg-picker-cancel')?.addEventListener('click', () =>
    closeModalEl(document.getElementById('wg-profile-picker')));
  document.getElementById('wg-picker-ok')?.addEventListener('click', applyProfilePicker);
  // picker: backdrop click does not close
  document.getElementById('wg-picker-search')?.addEventListener('input', e => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll('#wg-picker-list .svc-pick-row').forEach(row => {
      const name = (row.textContent || '').toLowerCase();
      row.style.display = !q || name.includes(q) ? '' : 'none';
    });
  });

  // модалка конфигурации
  document.getElementById('wg-config-save')?.addEventListener('click', saveConfig);
  document.getElementById('wg-config-cancel')?.addEventListener('click', () =>
    closeModalEl(document.getElementById('wg-config-modal')));
  // config: backdrop click does not close

  // модалка профиля
  document.getElementById('wg-profile-close')?.addEventListener('click', () =>
    closeModalEl(document.getElementById('wg-profile-modal')));
  // profile detail: backdrop click does not close

  // установка
  document.getElementById('wg-install-confirm')?.addEventListener('click', confirmInstall);
  document.getElementById('wg-install-cancel')?.addEventListener('click', () =>
    closeModalEl(document.getElementById('wg-install-modal')));
  // install: backdrop click does not close

  // QR
  document.getElementById('wg-qr-close')?.addEventListener('click', () =>
    closeModalEl(document.getElementById('wg-qr-modal')));
  // QR: backdrop click does not close
  document.getElementById('wg-qr-img')?.addEventListener('error', () => {
    toast('Не удалось сгенерировать QR (нет Endpoint, профиль неуправляемый или нет библиотеки qrcode)', false);
  });
}

// Публичный API для входа со страницы сервера и восстановления сессии.
export function openWgServerById(id) { return openWgServer(id, { from: 'server' }); }

// Фоновая задача WireGuard (например, подхваченная резюмом после перезагрузки
// страницы) завершилась — обновляем список, если открыта страница WireGuard.
document.addEventListener('bot4vps:task-done', e => {
  const t = e.detail || {};
  if (!String(t.name || '').startsWith('WireGuard:')) return;
  const on = id => document.getElementById(id)?.classList.contains('on');
  if (on('page-wireguard') || on('page-wireguard-server')) loadWireguard();
});
