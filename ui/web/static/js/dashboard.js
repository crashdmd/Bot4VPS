// Bot4VPS Dashboard — Modern UI
import { j, esc } from './api.js';
import { showPage, plural, toast, bindPasswordToggles, serverHour, formatServerTimestamp } from './ui.js';
import { setPage } from './state.js';
import { loadEvents, openEventDetail, applyEventsSnapshot, showUpdateModal } from './monitor.js?v=20260912-chlogwrap-v1';


// ---------- Первоначальная настройка Telegram ----------

function tgSetupNeeded(info) {
  if (!info || info.enabled === false) return false;
  if (info.needs_setup === true) return true;
  const noToken = !info.token_set;
  const noUser = info.user_id == null || info.user_id === '';
  return noToken || noUser;
}

function showTgSetupModal(info) {
  const modal = document.getElementById('tg-setup-modal');
  if (!modal) return;
  const err = document.getElementById('tg-setup-err');
  if (err) err.textContent = '';
  const user = document.getElementById('tg-setup-user');
  const tok = document.getElementById('tg-setup-token');
  if (user) user.value = info?.user_id != null ? String(info.user_id) : '';
  if (tok) tok.value = '';
  modal.classList.add('open');
}

function hideTgSetupModal() {
  document.getElementById('tg-setup-modal')?.classList.remove('open');
}

export async function checkTelegramSetup() {
  try {
    const info = await j('/api/telegram/status');
    if (tgSetupNeeded(info)) showTgSetupModal(info);
  } catch (_) { /* статус недоступен — не мешаем Dashboard */ }
}

async function tgSetupSave() {
  const err = document.getElementById('tg-setup-err');
  const user = (document.getElementById('tg-setup-user')?.value || '').trim();
  const rawTok = document.getElementById('tg-setup-token')?.value || '';
  const token = rawTok.trim();
  if (!user || !token) {
    if (err) err.textContent = 'Укажите User ID и Bot Token';
    return;
  }
  const tu = token.toUpperCase();
  if (tu.startsWith('YOUR_') || tu.includes('YOUR_BOT_TOKEN')) {
    if (err) err.textContent = 'Укажите действительный Bot Token, не placeholder';
    return;
  }
  try {
    const r = await j('/api/telegram/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: user, bot_token: token }),
    });
    if (r.ok === false) {
      if (err) err.textContent = r.error || 'Ошибка сохранения';
      return;
    }
    // запуск после успешного сохранения
    const start = await j('/api/telegram/start', { method: 'POST' }).catch(() => null);
    hideTgSetupModal();
    toast((start && start.message) || 'Telegram настроен', true);
    await loadDashboard();
  } catch (e) {
    if (err) err.textContent = e.message || String(e);
  }
}

async function tgSetupDisable() {
  try {
    await j('/api/telegram/stop', { method: 'POST' });
    hideTgSetupModal();
    toast('Telegram выключен', true);
    await loadDashboard();
  } catch (e) {
    const err = document.getElementById('tg-setup-err');
    if (err) err.textContent = e.message || String(e);
  }
}


export async function loadDashboard() {
  try {
    // Приветствие по времени локального хоста Bot4VPS
    const hour = serverHour();
    let greeting = 'Добрый день';
    if (hour >= 5 && hour < 12) greeting = 'Доброе утро';
    else if (hour >= 18 || hour < 5) greeting = 'Добрый вечер';

    // Получаем имя пользователя из /api/me
    let userName = null;
    try {
      const me = await j('/api/me');
      if (me.auth_enabled && me.user) userName = me.user;
    } catch (_) { /* игнорируем */ }

    const greetingEl = document.querySelector('.dash-greeting');
    if (greetingEl) {
      greetingEl.textContent = userName ? `${greeting}, ${userName}!` : `${greeting}!`;
    }

    // Загружаем данные параллельно
    const [servers, events, sys, updaterState] = await Promise.all([
      j('/api/servers'),
      j('/api/events?limit=5').catch(() => ({ events: [] })),
      j('/api/system').catch(() => null),
      j('/api/update/state').catch(() => null)
    ]);

    lastSys = sys;
    lastUpdaterState = updaterState;
    const allEvents = events.events || [];
    pushSysHistory(sys);
    renderServers(servers.servers || []);
    renderEvents(allEvents);
    renderSystem(sys, updaterState);
    await checkTelegramSetup();
  } catch (e) {
    console.error('[DASH]', e);
  }
}

// Последние данные для периодического пересчёта подзаголовка/системы
let lastSys = null;
let lastUpdaterState = null;

// Обновление только данных (без перерисовки списков)
export async function updateDashboardData() {
  try {
    const sys = await j('/api/system').catch(() => null);
    if (sys) lastSys = sys;
    pushSysHistory(sys);
    renderSystem(sys, lastUpdaterState);
  } catch (e) {
    console.error('[DASH UPDATE]', e);
  }
}

/**
 * Периодическое обновление «живых» частей дашборда: статус серверов
 * в заголовке виджета. Строки серверов не трогаем — их обновляет
 * refreshDashMetrics (3с). Выборка виджета меняется только при загрузке
 * страницы; здесь лишь убираем строки серверов, которые удалили из панели.
 */
export async function updateDashboardState() {
  try {
    const [servers, updaterState] = await Promise.all([
      j('/api/servers').catch(() => null),
      j('/api/update/state').catch(() => null),
    ]);
    if (!servers || !servers.servers) return;
    const list = servers.servers;
    lastUpdaterState = updaterState;
    // сервер из выборки удалён — строка обязана уйти; новые серверы
    // появляются только при следующей загрузке страницы
    if (widgetServers.length) {
      const ids = new Set(list.map(s => s.id));
      if (widgetServers.some(s => !ids.has(s.id))) {
        renderServers(list, new Set(widgetServers.map(s => s.id)));
      }
    } else if (list.length) {
      renderServers(list);
    }
  } catch (e) {
    console.error('[DASH STATE]', e);
  }
}

const WIDGET_LIMIT = 6;
const SPARK_POINTS = 20;     // сколько замеров держит график (20 × 3с ≈ минута)
const SPARK_W = 96, SPARK_H = 24, SPARK_PAD = 2;
// Компактные причины недоступности в виджете (см. classify_ssh_error в core)
const SRV_ERR_LABELS = {
  key_missing: '🔑 Ключ не найден',
  auth: '🔑 Пароль/ключ не подходят',
  port: '🔌 Порт недоступен',
  network: '🌐 Нет сети',
  timeout: '⏱ Не отвечает',
  connect: '⚠ Нет подключения',
  unknown: '⚠ Недоступен',
};
let widgetServers = [];      // текущая выборка: живёт до следующей загрузки страницы
let metricsTimer = null;
const cpuHistory = new Map();  // id сервера -> массив последних значений CPU
const ramHistory = new Map();  // id сервера -> массив последних значений RAM%

/** Компактный статус в заголовке виджета «Серверы» (справа). */

/** Сглаженная кривая через точки (Catmull-Rom → кубические Безье). */
function smoothPath(pts) {
  if (pts.length < 2) return '';
  let d = `M${pts[0].x} ${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i];
    const p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x} ${p2.y}`;
  }
  return d;
}

// plural переехал в ui.js — им пользуется и monitor.js (см. импорт выше).

/**
 * `up 4 days, 17 hours, 15 minutes` → `4 дня, 17 часов, 15 минут`.
 * Бэкенд отдаёт вывод `uptime -p`, переводим на месте (presentation layer).
 */
function uptimeRu(raw) {
  if (!raw || raw === 'N/A') return 'N/A';
  const units = [
    [/(\d+)\s*year/i, ['год', 'года', 'лет']],
    [/(\d+)\s*month/i, ['месяц', 'месяца', 'месяцев']],
    [/(\d+)\s*week/i, ['неделя', 'недели', 'недель']],
    [/(\d+)\s*day/i, ['день', 'дня', 'дней']],
    [/(\d+)\s*hour/i, ['час', 'часа', 'часов']],
    [/(\d+)\s*min/i, ['минута', 'минуты', 'минут']],
  ];
  const parts = [];
  for (const [re, forms] of units) {
    const m = raw.match(re);
    if (m) {
      const n = parseInt(m[1], 10);
      parts.push(`${n} ${plural(n, forms[0], forms[1], forms[2])}`);
    }
  }
  // строка в неизвестном формате — отдаём как есть, без «up»
  if (!parts.length) return raw.replace(/^up\s+/i, '').trim() || 'N/A';
  return parts.join(', ');
}

/** Переиспользуем модалку добавления сервера со страницы «Серверы». */
function bindDashAdd(box) {
  box.querySelector('[data-dash-add]')?.addEventListener('click', async () => {
    const m = await import('./servers.js?v=20260912-chlogwrap-v1');
    m.openAddServerModal();
  });
}

/** Разовая выборка виджета: проблемные в первую очередь, затем живые;
    внутри групп — случайно. Живёт до следующей загрузки страницы. */
function pickWidgetServers(servers) {
  const shuffle = arr => {
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
      const k = Math.floor(Math.random() * (i + 1));
      [a[i], a[k]] = [a[k], a[i]];
    }
    return a;
  };
  const isProblem = s => {
    const netOk = s.status === 'online' || s.online;
    return !netOk || (s.ssh_error && String(s.ssh_error).trim());
  };
  const problems = shuffle(servers.filter(isProblem));
  const healthy = shuffle(servers.filter(s => !isProblem(s)));
  const pCount = Math.min(problems.length, WIDGET_LIMIT);
  const hCount = Math.min(healthy.length, WIDGET_LIMIT - pCount);
  return [...problems.slice(0, pCount), ...healthy.slice(0, hCount)];
}

function renderServers(servers, keepIds = null) {
  const box = document.getElementById('dash-servers');
  stopDashMetrics();
  if (!servers.length) {
    widgetServers = [];
    cpuHistory.clear();
    ramHistory.clear();
    // серверов нет — кнопка добавления здесь нужнее всего
    box.innerHTML = `
      <div class="empty" style="padding:1.25rem 1rem">Нет серверов</div>
      <div class="dash-srv-actions">
        <button type="button" class="ghost" style="flex:1" data-dash-add="1">Добавить сервер</button>
      </div>`;
    bindDashAdd(box);
    return;
  }

  if (keepIds) {
    // состав панели изменился: прежняя выборка живёт, исчезнувшие уходят;
    // освободившиеся слоты не добираем — новые серверы увидит следующая
    // загрузка страницы
    widgetServers = servers.filter(s => keepIds.has(s.id));
    if (!widgetServers.length) widgetServers = pickWidgetServers(servers);
  } else {
    widgetServers = pickWidgetServers(servers);
  }
  // история от серверов, выпавших из выборки, больше не нужна
  const shown = new Set(widgetServers.map(s => s.id));
  [...cpuHistory.keys()].forEach(k => { if (!shown.has(k)) cpuHistory.delete(k); });
  [...ramHistory.keys()].forEach(k => { if (!shown.has(k)) ramHistory.delete(k); });

  box.innerHTML = widgetServers.map(s => {
    const online = s.status === 'online' || s.online;
    // жив, но SSH не проходит — жёлтый: зелёный обманывал бы, как и в списке
    const dot = !online ? '🔴' : (s.ssh_error && String(s.ssh_error).trim()) ? '🟡' : '🟢';
    return `
      <div class="dash-srv" data-sid="${esc(s.id)}">
        <div class="dash-srv-top">
          <span data-f="dot" class="dash-srv-dot">${dot}</span>
          <span class="dash-srv-name">${esc(s.name)}</span>
          <span class="dash-srv-ping" data-f="ping">—</span>
          <span class="dash-srv-cpu">
            <span class="m-cpu" data-f="cpu">—</span>
            <span class="m-ram" data-f="ram">—</span>
          </span>
        </div>
        <div class="dash-srv-chart" data-f="chart">${srvSpark(s.id, !online)}</div>
        <div class="dash-srv-sub">
          <span class="dash-srv-host">${esc(s.host || '')}</span>
          <span class="dash-srv-meta"><span data-f="uptime">Uptime: …</span></span>
        </div>
      </div>`;
  }).join('');

  const showAll = servers.length > widgetServers.length
    ? `<button type="button" class="ghost" style="flex:1" data-dash-all="1">Показать все →</button>`
    : '';
  box.insertAdjacentHTML('beforeend',
    `<div class="dash-srv-actions">
       ${showAll}
       <button type="button" class="ghost" style="flex:1" data-dash-add="1">Добавить сервер</button>
     </div>`);

  box.querySelectorAll('.dash-srv').forEach(row => {
    row.addEventListener('click', () => openServerFromDash(row.dataset.sid));
  });
  box.querySelector('[data-dash-all]')?.addEventListener('click', () => {
    setPage('servers');
    showPage('servers');
  });
  bindDashAdd(box);

  startDashMetrics();
}

/** Все серверы опрашиваются параллельно, не по очереди. */
async function refreshDashMetrics() {
  const box = document.getElementById('dash-servers');
  if (!widgetServers.length || !box) return;
  // страница дашборда скрыта — не дёргаем SSH
  if (!document.getElementById('page-dashboard')?.classList.contains('on')) return;

  await Promise.all(widgetServers.map(async s => {
    const row = box.querySelector(`.dash-srv[data-sid="${CSS.escape(s.id)}"]`);
    if (!row) return;
    const set = (f, txt) => {
      const el = row.querySelector(`[data-f="${f}"]`);
      if (el) el.textContent = txt;
    };
    const chart = row.querySelector('[data-f="chart"]');
    const draw = offline => { if (chart) chart.innerHTML = srvSpark(s.id, offline); };
    // недоступен: иконка краснеет, вместо спарклайна — причина
    const na = (kind) => {
      // ключ пропал/пароль не подходит — сервер жив, точка жёлтая;
      // сеть/таймаут — красная
      set('dot', (kind === 'key_missing' || kind === 'auth') ? '🟡' : '🔴');
      set('cpu', '');
      set('ram', '');
      set('uptime', 'Uptime: N/A');
      cpuHistory.delete(s.id);
      ramHistory.delete(s.id);
      if (chart) chart.innerHTML = `<span class="dash-srv-err">${SRV_ERR_LABELS[kind] || SRV_ERR_LABELS.unknown}</span>`;
    };
    try {
      // метрики и TCP-пинг параллельно: пинг живёт своей жизнью —
      // сервер может отвечать по сети, но не пускать по SSH
      const [m, ping] = await Promise.all([
        j('/api/servers/' + encodeURIComponent(s.id) + '/metrics').catch(() => null),
        j('/api/servers/' + encodeURIComponent(s.id) + '/ping').catch(() => null),
      ]);
      setPing(row, ping);
      if (!m) { na('unknown'); return; }
      if (!m.ok) { na(m.error_kind); return; }
      // тот же критерий «нет данных», что и в карточке сервера
      const empty = m.cpu == null && m.ram_pct == null && m.disk_pct == null
        && (!m.load || m.load === 'N/A') && (!m.uptime || m.uptime === 'N/A');
      if (empty) { na('unknown'); return; }
      const pct = m.cpu != null ? Math.round(m.cpu) : null;
      const ram = m.ram_pct != null ? Math.round(m.ram_pct) : null;
      set('dot', '🟢');
      // ram_pct приходит с тем же запросом метрик; CPU и RAM подписаны
      // цветами своих линий в графике
      set('cpu', pct != null ? pct + '% CPU' : '');
      set('ram', ram != null ? ram + '% RAM' : '');
      set('uptime', 'Uptime: ' + uptimeRu(m.uptime));
      const hist = cpuHistory.get(s.id) || [];
      hist.push(pct || 0);
      if (hist.length > SPARK_POINTS) hist.splice(0, hist.length - SPARK_POINTS);
      cpuHistory.set(s.id, hist);
      const ramHist = ramHistory.get(s.id) || [];
      ramHist.push(ram || 0);
      if (ramHist.length > SPARK_POINTS) ramHist.splice(0, ramHist.length - SPARK_POINTS);
      ramHistory.set(s.id, ramHist);
      draw(false);
    } catch {
      na('unknown');
    }
  }));
}

export function startDashMetrics() {
  stopDashMetrics();
  refreshDashMetrics();
  metricsTimer = setInterval(refreshDashMetrics, 3000);
}

export function stopDashMetrics() {
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
}

async function openServerFromDash(id) {
  stopDashMetrics();
  const m = await import('./servers.js?v=20260912-chlogwrap-v1');
  setPage('servers');
  showPage('servers');
  m.openServer(id);
}

const DASH_EVENTS_SHOWN = 5;

function renderEvents(events) {
  const box = document.getElementById('dash-events');
  if (!events.length) {
    box.innerHTML = '<div class="empty" style="padding:2rem 1rem">Нет событий</div>';
    return;
  }

  // Синхронизируем события с кэшом monitor.js (полный список)
  applyEventsSnapshot(events);

  // на показ — только последние; пришли они отсортированными (новые сверху)
  const shown = events.slice(0, DASH_EVENTS_SHOWN);
  box.innerHTML = shown.map((e, i) => {
    const level = e.level || 'info';
    const icon = level === 'error' ? '❌' : level === 'warning' ? '⚠️' : level === 'success' ? '✅' : 'ℹ️';
    return `
      <div class="dash-ev" data-ev-idx="${i}">
        <span style="font-size:0.9rem;line-height:1.4">${icon}</span>
        <div style="flex:1;min-width:0">
          <div class="dash-ev-msg">${esc(e.message || '')}</div>
          <div class="dash-ev-time">${esc(formatServerTimestamp(e.timestamp))}</div>
        </div>
      </div>`;
  }).join('');

  // Общая карточка из monitor.js — она же помечает событие прочитанным
  box.querySelectorAll('[data-ev-idx]').forEach(node => {
    node.onclick = () => openEventDetail(shown[Number(node.dataset.evIdx)].id);
  });
}


/** Пилюля статуса: зелёная — работает, красная — нет. */
function statusPill(label, st) {
  const ok = !!(st && st.ok);
  const state = (st && st.state) || '';
  const detail = (st && st.detail) || '';
  const err = (st && st.error) || '';
  // Выключен — только enabled=false (серый)
  let cls = 'is-bad';
  let text = detail || (ok ? 'Работает' : 'Ошибка');
  if (ok || state === 'running') {
    cls = 'is-ok';
    text = 'Работает';
  } else if (state === 'disabled' || detail === 'Выключен') {
    cls = 'is-off';
    text = 'Выключен';
  } else {
    cls = 'is-bad';
    text = err ? `Ошибка · ${err}` : (detail === 'Ошибка' ? 'Ошибка' : (detail || 'Ошибка'));
  }
  return `
    <div class="dash-sys-status">
      <span class="lbl">${esc(label)}</span>
      <span class="dash-pill ${cls}">
        <span class="dot"></span>${esc(text)}
      </span>
    </div>`;
}

function systemUpdateNotice(state) {
  if (!state || state.available == null) return '';
  const version = typeof state.available === 'object'
    ? state.available.version
    : state.available;
  return `
    <div class="dash-update-notice">
      <div class="dash-update-title">Вышла новая версия</div>
      <div class="dash-update-version">Доступна версия ${esc(version || '—')}</div>
      <button type="button" data-dash-update>Перейти к обновлению</button>
    </div>`;
}

/* История метрик системы для графиков виджета «Состояние системы»:
   наполняется опросом /api/system (раз в 3с, пока открыт дашборд).
   60 точек ≈ 3 минуты скользящего окна */
const SYS_SPARK_POINTS = 60;
const sysHistory = { cpu: [], ram: [], disk: [], net: { rx: [], tx: [] } };

function pushSysHistory(sys) {
  if (!sys || !sys.ok) return;
  const push = (arr, v) => {
    if (v == null) return;
    arr.push(Math.max(0, Math.min(100, v)));
    if (arr.length > SYS_SPARK_POINTS) arr.splice(0, arr.length - SYS_SPARK_POINTS);
  };
  push(sysHistory.cpu, sys.cpu);
  push(sysHistory.ram, sys.ram_pct);
  push(sysHistory.disk, sys.disk_pct);
  // сеть — байты/с, не проценты: без clamp, только окно
  const pushNet = (arr, v) => {
    if (v == null) return;
    arr.push(Math.max(0, v));
    if (arr.length > SYS_SPARK_POINTS) arr.splice(0, arr.length - SYS_SPARK_POINTS);
  };
  pushNet(sysHistory.net.rx, sys.net_rx);
  pushNet(sysHistory.net.tx, sys.net_tx);
}

/* Универсальный спарклайн (строки серверов + виджет системы):
   растянут на всю ширину контейнера, x масштабируется по числу
   накопленных точек — линия всегда занимает весь график (пустоты
   нет ни в первые секунды, ни после заполнения окна).
   preserveAspectRatio="none" + vector-effect держат толщину линии,
   а точка текущего значения — span поверх svg (круг в растянутом
   viewBox деформировался бы в овал) */
function sparkline(hist, color) {
  const grid = `<line x1="0" y1="${(SPARK_H / 2).toFixed(1)}" x2="${SPARK_W}" y2="${(SPARK_H / 2).toFixed(1)}"
      stroke="var(--border)" stroke-width="1" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"/>`;
  const open = `<svg viewBox="0 0 ${SPARK_W} ${SPARK_H}" preserveAspectRatio="none"
      style="display:block;width:100%;height:${SPARK_H}px;overflow:visible">`;

  if (!hist || !hist.length) return `${open}${grid}</svg>`;

  const step = SPARK_W / Math.max(1, hist.length - 1);
  const y = v => SPARK_PAD + (1 - Math.min(100, Math.max(0, v)) / 100) * (SPARK_H - SPARK_PAD * 2);
  const pts = hist.map((v, i) => ({
    x: +(i * step).toFixed(1),
    y: +y(v).toFixed(1),
  }));
  if (pts.length === 1) pts.push({ x: pts[0].x + step, y: pts[0].y });

  const line = smoothPath(pts);
  const area = `${line} L${pts[pts.length - 1].x} ${SPARK_H} L${pts[0].x} ${SPARK_H} Z`;
  const last = pts[pts.length - 1];

  return `
    <div class="dash-spark" style="--dot-y:${last.y}px;--dot-c:${color}">
      ${open}
      ${grid}
      <path d="${area}" fill="${color}" fill-opacity="0.14"/>
      <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6"
            stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
      </svg>
      <span class="spark-dot"></span>
    </div>`;
}

/* Зеркало humanRate из monitor.js: локальная копия — экспорт из
   monitor.js потянул бы пересборку версий пяти импортирующих модулей */
function fmtRate(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  const units = ['Б', 'КБ', 'МБ', 'ГБ'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}/с`;
}

/* Многосерийный растянутый спарклайн: несколько линий в одном svg.
   series — [{hist, color, dashed}]; шкала общая по всем сериям
   (фиксированная maxVal или автоподбор по максимуму — иначе линии
   несравнимы). Пунктир — опционально, для второй серии */
function sparkMulti(series, maxVal) {
  const open = `<svg viewBox="0 0 ${SPARK_W} ${SPARK_H}" preserveAspectRatio="none"
      style="display:block;width:100%;height:${SPARK_H}px;overflow:visible">`;
  const hists = series.map(s => s.hist || []);
  if (!hists.some(h => h.length)) return `${open}</svg>`;

  const cap = maxVal != null ? maxVal : Math.max(1, ...hists.flat());
  const y = v => SPARK_PAD + (1 - Math.min(cap, Math.max(0, v)) / cap) * (SPARK_H - SPARK_PAD * 2);
  const path = hist => {
    if (!hist || !hist.length) return '';
    const step = SPARK_W / Math.max(1, hist.length - 1);
    const pts = hist.map((v, i) => ({ x: +(i * step).toFixed(1), y: +y(v).toFixed(1) }));
    if (pts.length === 1) pts.push({ x: pts[0].x + step, y: pts[0].y });
    return smoothPath(pts);
  };
  const lines = series.map(s => {
    const d = path(s.hist);
    if (!d) return '';
    const dash = s.dashed ? ` stroke-dasharray="3 2"` : '';
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.6"${dash}
      stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
  }).join('');
  return `${open}${lines}</svg>`;
}

/* График плитки сервера: CPU (акцент/красный) + RAM (розовый) в одном
   svg, фиксированная шкала 0..100 — обе величины процентные */
function srvSpark(id, offline) {
  return sparkMulti([
    { hist: cpuHistory.get(id) || [], color: offline ? 'var(--err)' : 'var(--accent)' },
    { hist: ramHistory.get(id) || [], color: 'var(--memory-icon)' },
  ], 100);
}

/* Пинг-чип рядом с именем: ≤300мс зелёный, ≤500мс жёлтый,
   выше — красный, недоступен — прочерк */
function setPing(row, ping) {
  const el = row.querySelector('[data-f="ping"]');
  if (!el) return;
  if (!ping || !ping.ok || ping.ms == null) {
    el.textContent = '— (tcp)';
    el.className = 'dash-srv-ping is-bad';
    return;
  }
  el.textContent = ping.ms + ' мс (tcp)';
  el.className = 'dash-srv-ping ' + (ping.ms <= 300 ? 'is-ok' : ping.ms <= 500 ? 'is-warn' : 'is-bad');
}

function renderSystem(sys, updaterState) {
  const box = document.getElementById('dash-system');
  const notice = systemUpdateNotice(updaterState || lastUpdaterState);

  // /api/system не ответил — значит и веб-часть недоступна
  if (!sys || !sys.ok) {
    box.innerHTML = `
      <div class="dash-sys-statuses">
        ${statusPill('Web', { ok: false, detail: 'нет ответа' })}
        ${statusPill('Telegram-бот', { ok: false, detail: 'неизвестно' })}
      </div>
      ${notice}
      ${sysFooter()}`;
    box.querySelector('[data-dash-update]')?.addEventListener('click', showUpdateModal);
    return;
  }

  // Три мини-виджета: CPU / RAM / Сеть — метка, значение, живой график
  // по накопленной истории (pushSysHistory, 3с/точка) и мелкая подпись.
  const temp = sys.temp && sys.temp !== 'N/A' ? sys.temp : '';
  box.innerHTML = `
    <div class="dash-sys-tiles">
      <div class="dash-sys-tile">
        <span class="lbl">CPU</span>
        <span class="val">${sys.cpu != null ? esc(String(sys.cpu)) + '%' : 'N/A'}</span>
        <div class="tile-spark">${sparkline(sysHistory.cpu, 'var(--cpu-icon)')}</div>
        <span class="sub">${esc(temp)}</span>
      </div>
      <div class="dash-sys-tile">
        <span class="lbl">RAM</span>
        <span class="val">${sys.ram_pct != null ? esc(String(sys.ram_pct)) + '%' : 'N/A'}</span>
        <div class="tile-spark">${sparkline(sysHistory.ram, 'var(--memory-icon)')}</div>
        <span class="sub">${sys.ram && sys.ram !== 'N/A' ? esc(sys.ram) : ''}</span>
      </div>
      <div class="dash-sys-tile">
        <span class="lbl">Сеть</span>
        <span class="val">↓ ${esc(fmtRate(sys.net_rx))}</span>
        <div class="tile-spark">${sparkMulti([{ hist: sysHistory.net.rx, color: 'var(--traffic-icon)' }, { hist: sysHistory.net.tx, color: 'var(--cpu-icon)', dashed: true }])}</div>
        <span class="sub">↑ ${esc(fmtRate(sys.net_tx))}</span>
      </div>
    </div>
    <div class="dash-sys-statuses">
      ${statusPill('Web', sys.web)}
      ${statusPill('Telegram-бот', sys.bot)}
    </div>
    ${notice}
    ${sysFooter()}`;
  box.querySelector('[data-dash-update]')?.addEventListener('click', showUpdateModal);
}

function sysFooter() {
  return `<div class="dash-srv-actions">
    <button type="button" class="ghost" style="flex:1" onclick="window.dashShowPage('monitor')">⚙️ Подробная информация</button>
  </div>`;
}

export function bindDashboard() {
  document.getElementById('tg-setup-save')?.addEventListener('click', tgSetupSave);
  bindPasswordToggles(document.getElementById('tg-setup-modal') || document);

  document.getElementById('tg-setup-disable')?.addEventListener('click', tgSetupDisable);
  // backdrop не закрывает — нужно явное действие

  document.getElementById('dash-events-all')?.addEventListener('click', () => {
    setPage('events');
    showPage('events');
    loadEvents(100);
  });
}

// Хелпер для inline onclick (кнопка «Открыть мониторинг»).
// b4vNav (app.js) делает полноценную навигацию: останавливает вотчеры
// и грузит данные целевой страницы.
function navTo(page) {
  if (window.b4vNav) window.b4vNav(page);
  else { setPage(page); showPage(page); }
}
window.dashShowPage = navTo;

// Старая функция loadSummary — заглушка для совместимости
export async function loadSummary() {
  // Старый код мог вызывать эту функцию; теперь делегируем на дашборд
  await loadDashboard();
}
