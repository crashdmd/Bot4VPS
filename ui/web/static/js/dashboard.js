// Bot4VPS Dashboard — Modern UI
import { j, esc } from './api.js';
import { showPage, plural, toast, bindPasswordToggles } from './ui.js';
import { setPage } from './state.js';
import { loadEvents, openEventDetail, applyEventsSnapshot, showUpdateModal } from './monitor.js?v=20260815-fixes-v1';


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
    // Дата и время с днём недели
    const now = new Date();
    const dateStr = now.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', weekday: 'long' });
    const timeStr = now.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    document.getElementById('dash-date').textContent = dateStr;
    document.getElementById('dash-time').textContent = timeStr;

    // Приветствие по времени суток
    const hour = now.getHours();
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
    const [summary, servers, events, dockerStatus, sys, updaterState] = await Promise.all([
      j('/api/summary'),
      j('/api/servers'),
      j('/api/events?limit=4').catch(() => ({ events: [] })),
      j('/api/services/docker/status').catch(() => ({ servers: [] })),
      j('/api/system').catch(() => null),
      j('/api/update/state').catch(() => null)
    ]);

    // Подсчёт контейнеров
    let totalContainers = 0;
    (dockerStatus.servers || []).forEach(s => {
      if (s.status && s.status.containers) {
        totalContainers += s.status.containers.length;
      }
    });

    renderMetrics(summary, servers.servers || [], totalContainers);
    renderServers(servers.servers || []);
    renderEvents(events.events || []);
    renderSystem(sys, updaterState);
    await checkTelegramSetup();
  } catch (e) {
    console.error('[DASH]', e);
  }
}

// Обновление только данных (без перерисовки списков)
export async function updateDashboardData() {
  try {
    const [sys, updaterState] = await Promise.all([
      j('/api/system').catch(() => null),
      j('/api/update/state').catch(() => null)
    ]);

    renderSystem(sys, updaterState);
  } catch (e) {
    console.error('[DASH UPDATE]', e);
  }
}

function renderMetrics(summary, servers, containersCount) {
  const totalServers = servers.length;
  const onlineServers = servers.filter(s => s.status === 'online' || s.online).length;
  const offlineServers = servers.filter(s => s.status !== 'online' && !s.online);

  // Серверы - показываем только онлайн
  document.getElementById('m-servers').textContent = String(onlineServers);

  // Статус серверов
  const serversStatusEl = document.getElementById('m-servers-status');
  if (offlineServers.length === 0) {
    serversStatusEl.innerHTML = '<span class="metric-status ok">Все онлайн</span>';
  } else {
    const firstOffline = offlineServers[0].name || offlineServers[0].host || 'Сервер';
    serversStatusEl.innerHTML = `<span class="metric-status warn">${esc(firstOffline)} недоступен</span>`;
  }

  // Задачи
  const tasksCount = (summary.running_tasks || 0) + (summary.queued_tasks || 0);
  document.getElementById('m-tasks').textContent = String(tasksCount);

  // Статус задач
  const tasksStatusEl = document.getElementById('m-tasks-status');
  if (tasksCount === 0) {
    tasksStatusEl.innerHTML = '<span class="metric-status ok">Нет активных</span>';
  } else {
    const running = summary.running_tasks || 0;
    const queued = summary.queued_tasks || 0;
    if (running > 0) {
      tasksStatusEl.innerHTML = `<span class="metric-status ok">Выполняется: ${running}</span>`;
    } else {
      tasksStatusEl.innerHTML = `<span class="metric-status warn">В очереди: ${queued}</span>`;
    }
  }

  // Контейнеры
  document.getElementById('m-containers').textContent = String(containersCount || 0);

  // Статус контейнеров
  const containersStatusEl = document.getElementById('m-containers-status');
  if (containersCount === 0) {
    containersStatusEl.innerHTML = '<span class="metric-status ok">Нет контейнеров</span>';
  } else {
    containersStatusEl.innerHTML = `<span class="metric-status ok">Активно: ${containersCount}</span>`;
  }
}

const WIDGET_LIMIT = 3;
const SPARK_POINTS = 20;     // сколько замеров держит график (20 × 3с ≈ минута)
let widgetServers = [];      // случайная выборка, живёт до следующего loadDashboard
let metricsTimer = null;
const cpuHistory = new Map();  // id сервера -> массив последних значений CPU

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const k = Math.floor(Math.random() * (i + 1));
    [a[i], a[k]] = [a[k], a[i]];
  }
  return a;
}

const SPARK_W = 96, SPARK_H = 32, SPARK_PAD = 2;

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

/**
 * Классический линейный график нагрузки CPU с заливкой.
 * `hist` — история значений 0..100, свежие в конце.
 */
function cpuSpark(hist, offline) {
  const stroke = offline ? 'var(--err)' : 'var(--accent)';
  const grid = `<line x1="0" y1="${(SPARK_H / 2).toFixed(1)}" x2="${SPARK_W}" y2="${(SPARK_H / 2).toFixed(1)}"
      stroke="var(--border)" stroke-width="1" stroke-dasharray="2 3"/>`;

  if (!hist || !hist.length) {
    return `<svg width="${SPARK_W}" height="${SPARK_H}" viewBox="0 0 ${SPARK_W} ${SPARK_H}"
      style="display:block;overflow:visible">${grid}</svg>`;
  }

  // пока замеров мало — прижимаем график к правому краю
  const step = SPARK_W / (SPARK_POINTS - 1);
  const y = v => SPARK_PAD + (1 - Math.min(100, Math.max(0, v)) / 100) * (SPARK_H - SPARK_PAD * 2);
  const pts = hist.map((v, i) => ({
    x: +(SPARK_W - (hist.length - 1 - i) * step).toFixed(1),
    y: +y(v).toFixed(1),
  }));
  if (hist.length === 1) pts.unshift({ x: pts[0].x - step, y: pts[0].y });

  const line = smoothPath(pts);
  const area = `${line} L${pts[pts.length - 1].x} ${SPARK_H} L${pts[0].x} ${SPARK_H} Z`;
  const last = pts[pts.length - 1];

  return `
    <svg width="${SPARK_W}" height="${SPARK_H}" viewBox="0 0 ${SPARK_W} ${SPARK_H}"
         style="display:block;overflow:visible">
      ${grid}
      <path d="${area}" fill="${stroke}" fill-opacity="0.14"/>
      <path d="${line}" fill="none" stroke="${stroke}" stroke-width="1.6"
            stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${last.x}" cy="${last.y}" r="2.1" fill="${stroke}"/>
    </svg>`;
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
    const m = await import('./servers.js');
    m.openAddServerModal();
  });
}

function renderServers(servers) {
  const box = document.getElementById('dash-servers');
  stopDashMetrics();
  if (!servers.length) {
    widgetServers = [];
    cpuHistory.clear();
    // серверов нет — кнопка добавления здесь нужнее всего
    box.innerHTML = `
      <div class="empty" style="padding:1.25rem 1rem">Нет серверов</div>
      <div class="dash-srv-actions">
        <button type="button" class="ghost" style="flex:1" data-dash-add="1">＋ Добавить сервер</button>
      </div>`;
    bindDashAdd(box);
    return;
  }

  // случайная выборка серверов, а не всегда одни и те же
  widgetServers = shuffle(servers).slice(0, WIDGET_LIMIT);
  // история от серверов, выпавших из выборки, больше не нужна
  const shown = new Set(widgetServers.map(s => s.id));
  [...cpuHistory.keys()].forEach(k => { if (!shown.has(k)) cpuHistory.delete(k); });

  box.innerHTML = widgetServers.map(s => {
    const online = s.status === 'online' || s.online;
    return `
      <div class="dash-srv" data-sid="${esc(s.id)}">
        <div data-f="dot" class="dash-srv-dot">${online ? '🟢' : '🔴'}</div>
        <div style="min-width:0">
          <div class="dash-srv-name">${esc(s.name)}</div>
          <div class="dash-srv-host">${esc(s.host || '')}</div>
          <div class="dash-srv-meta"><span data-f="uptime">Uptime: …</span></div>
        </div>
        <div class="dash-srv-chart">
          <div data-f="chart">${cpuSpark(cpuHistory.get(s.id), !online)}</div>
          <div class="dash-srv-cpu"><span data-f="cpu">…</span> CPU</div>
        </div>
      </div>`;
  }).join('');

  const showAll = servers.length > WIDGET_LIMIT
    ? `<button type="button" class="ghost" style="flex:1" data-dash-all="1">Показать все →</button>`
    : '';
  box.insertAdjacentHTML('beforeend',
    `<div class="dash-srv-actions">
       ${showAll}
       <button type="button" class="ghost" style="flex:1" data-dash-add="1">＋ Добавить сервер</button>
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
    const draw = offline => {
      if (chart) chart.innerHTML = cpuSpark(cpuHistory.get(s.id), offline);
    };
    // недоступен: иконка краснеет сразу же, история обрывается
    const na = () => {
      set('dot', '🔴');
      set('cpu', 'N/A');
      set('uptime', 'Uptime: N/A');
      cpuHistory.delete(s.id);
      draw(true);
    };
    try {
      const m = await j('/api/servers/' + encodeURIComponent(s.id) + '/metrics');
      if (!m.ok) { na(); return; }
      // тот же критерий «нет данных», что и в карточке сервера
      const empty = m.cpu == null && m.ram_pct == null && m.disk_pct == null
        && (!m.load || m.load === 'N/A') && (!m.uptime || m.uptime === 'N/A');
      if (empty) { na(); return; }
      const pct = m.cpu != null ? Math.round(m.cpu) : null;
      set('dot', '🟢');
      set('cpu', pct != null ? pct + '%' : 'N/A');
      set('uptime', 'Uptime: ' + uptimeRu(m.uptime));
      const hist = cpuHistory.get(s.id) || [];
      hist.push(pct || 0);
      if (hist.length > SPARK_POINTS) hist.splice(0, hist.length - SPARK_POINTS);
      cpuHistory.set(s.id, hist);
      draw(false);
    } catch {
      na();
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
  const m = await import('./servers.js');
  setPage('servers');
  showPage('servers');
  m.openServer(id);
}

function renderEvents(events) {
  const box = document.getElementById('dash-events');
  if (!events.length) {
    box.innerHTML = '<div class="empty" style="padding:2rem 1rem">Нет событий</div>';
    return;
  }

  // Синхронизируем события с кэшом monitor.js
  applyEventsSnapshot(events);

  box.innerHTML = events.map((e, i) => {
    const level = e.level || 'info';
    const icon = level === 'error' ? '❌' : level === 'warning' ? '⚠️' : level === 'success' ? '✅' : 'ℹ️';
    return `
      <div class="dash-ev" data-ev-idx="${i}">
        <span style="font-size:0.9rem;line-height:1.4">${icon}</span>
        <div style="flex:1;min-width:0">
          <div class="dash-ev-msg">${esc(e.message || '')}</div>
          <div class="dash-ev-time">${esc(e.timestamp || '')}</div>
        </div>
      </div>`;
  }).join('');

  // Общая карточка из monitor.js — она же помечает событие прочитанным
  box.querySelectorAll('[data-ev-idx]').forEach(node => {
    node.onclick = () => openEventDetail(events[Number(node.dataset.evIdx)].id);
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

function bindSystemUpdate(box) {
  box.querySelector('[data-dash-update]')?.addEventListener('click', showUpdateModal);
}

function renderSystem(sys, updaterState) {
  const box = document.getElementById('dash-system');

  // /api/system не ответил — значит и веб-часть недоступна
  if (!sys || !sys.ok) {
    box.innerHTML =
      statusPill('Web', { ok: false, detail: 'нет ответа' }) +
      statusPill('Telegram-бот', { ok: false, detail: 'неизвестно' }) +
      systemUpdateNotice(updaterState) +
      sysFooter();
    bindSystemUpdate(box);
    return;
  }

  const bars = [
    { label: 'CPU', pct: sys.cpu, value: sys.cpu != null ? sys.cpu + '%' : 'N/A', color: 'var(--cpu-icon)' },
    { label: 'RAM', pct: sys.ram_pct, value: sys.ram && sys.ram !== 'N/A' ? sys.ram : 'N/A', color: 'var(--memory-icon)' },
    { label: 'Диск', pct: sys.disk_pct, value: sys.disk && sys.disk !== 'N/A' ? sys.disk : 'N/A', color: 'var(--disk-icon)' },
  ];

  box.innerHTML =
    bars.map(b => {
      const pct = b.pct != null ? Math.max(0, Math.min(100, b.pct)) : 0;
      return `
        <div class="dash-sys-row">
          <div class="dash-sys-head">
            <span class="lbl">${esc(b.label)}</span>
            <span class="val">${esc(b.value)}</span>
          </div>
          <div class="dash-sys-track">
            <div class="dash-sys-fill" style="background:${b.color};width:${pct}%"></div>
          </div>
        </div>`;
    }).join('') +
    statusPill('Web', sys.web) +
    statusPill('Telegram-бот', sys.bot) +
    systemUpdateNotice(updaterState) +
    sysFooter();
  bindSystemUpdate(box);
}

function sysFooter() {
  return `<div class="dash-srv-actions">
    <button type="button" class="ghost" style="flex:1" onclick="window.dashShowPage('monitor')">⚙️ Подробная информация</button>
  </div>`;
}

export function bindDashboard() {
  document.getElementById('dash-refresh')?.addEventListener('click', loadDashboard);
  document.getElementById('tg-setup-save')?.addEventListener('click', tgSetupSave);
  bindPasswordToggles(document.getElementById('tg-setup-modal') || document);

  document.getElementById('tg-setup-disable')?.addEventListener('click', tgSetupDisable);
  // backdrop не закрывает — нужно явное действие

  document.getElementById('dash-events-all')?.addEventListener('click', () => {
    setPage('events');
    showPage('events');
    loadEvents(100);
  });

  // Клик на метрики-карточки → навигация
  document.addEventListener('click', (e) => {
    const metricCard = e.target.closest('.metric-card[data-nav]');
    if (metricCard) {
      const page = metricCard.dataset.nav;
      setPage(page);
      showPage(page);

      // Для Docker переключаем на вкладку «Управление»
      if (page === 'docker') {
        setTimeout(() => {
          const manageTab = document.querySelector('#docker-tabs [data-dktab="manage"]');
          if (manageTab) manageTab.click();
        }, 50);
      }
    }
  });
}

// Хелпер для inline onclick (кнопка «Открыть мониторинг»)
window.dashShowPage = (page) => { setPage(page); showPage(page); };

// Старая функция loadSummary — заглушка для совместимости
export async function loadSummary() {
  // Старый код мог вызывать эту функцию; теперь делегируем на дашборд
  await loadDashboard();
}
