/**
 * Страница «Мониторинг серверов»: история метрик и действия, которые на неё
 * повлияли.
 *
 * Что важно в этом модуле:
 *
 * * **Ни одного SSH.** Раздел исторический: он читает `/api/metrics/*` и
 *   `/api/timeline/{id}`, которые ходят только в `state.db`. Живые значения
 *   карточки (SSH) остались в `servers.js` — здесь их нет, иначе открытие
 *   истории само создавало бы нагрузку на серверы и шум в мониторинге
 *   (§10.4 ТЗ).
 * * **Список и график — одна страница.** Клик по строке раскрывает график
 *   под списком: не отдельная комната, а то же место (решение 2026-09-27).
 *   Раскрытый сервер живёт в `state.metricsOpenServerId`, адрес — в URL
 *   (`?page=metrics&server_id=…`), поэтому ссылка «Метрики →» из карточки
 *   сервера открывает нужный график, а F5 не теряет выбор.
 * * **Обновление — по SSE, догон — запросом.** Поток отдаёт «свежее», но не
 *   повторяет пропущенное: после переподключения (панель перезапустили,
 *   браузер уснул) страница перечитывает данные запросом, иначе вкладка
 *   застывает на старых числах.
 */
import { j, esc, errorHtml } from './api.js';
import { toast, showPage, serverNow, formatServerTime, formatServerDateTime, panelCalendarToday, panelDateRangeWindow, serverDateTimeParts, infoModal } from './ui.js';
import { state, setPage, setMetricsRange } from './state.js';
// Версия в спецификаторе — та же, что у `servers.js`: иначе браузер грузит
// `chart.js` дважды (с `?v=` и без) и держит **два** экземпляра модуля, а
// незаверсионированный ещё и кэширует навсегда — правка рисунка не доехала бы
// до пользователя.
import { renderTimeline, renderSpark, destroyChart, resultColor, normalizeGaps, selectMark } from './chart.js?v=20261001-mobile-charts-v1';

const RANGE_KEY = 'bot4vps_metrics_range';
const REFRESH_MS = 60000;
const AUDIT_REFRESH_MS = 250;
let metricsSearch = '';

const RANGES = {
  '24h': 86400,
  '7d': 7 * 86400,
  '30d': 30 * 86400,
  '90d': 90 * 86400,
};

const STATUS = {
  ok: { cls: 'on', text: 'свежие данные', hint: 'последняя проба не старше двух интервалов сбора' },
  stale: { cls: 'warn', text: 'данных нет', hint: 'свежих проб нет: сбор не доходит до сервера или данных ещё не накопилось' },
  unreachable: { cls: 'off', text: 'не отвечает', hint: 'проба доступности свежее последней точки: сервер не отвечает' },
};

/** Последний ответ overview: по нему SSE обновляет строку, не перечитывая список. */
let lastOverview = null;
/** Окно графика, если оно построено вокруг события (deep-link `at=`). */
let windowAround = null;
/**
 * Выделенная марка (запись аудита). Клик по действию в списке под графиком
 * подсвечивает его точку на графике, а не уводит в «Историю»: уводить
 * пользователя со страницы, на которой он читает график, — терять его место.
 * Переход в запись — отдельная кнопка у той же строки.
 */
let selectedMarkId = null;
let visibleMarksById = new Map();
/**
 * Приближенное окно (`{from, to}`, секунды панели) или `null` — тогда окно
 * задаёт выбранный диапазон. Живёт в адресе (`from=`/`to=`), поэтому F5 и
 * ссылка на приближенный участок показывают то же самое.
 */
let zoomWindow = null;
let timer = null;
let auditRefreshTimer = null;
let availabilityRefreshTimer = null;
let availabilityListenerBound = false;
// Значения раскрытой строки берём у самой легенды: overview и timeline могут
// агрегировать разные наборы точек, а пользователю важны числа на одном экране.
let openChartLegendValues = null;
// Пересборка списка вынимает detail из DOM и сбрасывает pointer capture.
let touchListRefreshPending = false;
// Ответы таймлайна могут прийти не по порядку, пока окно тащат мышью.
// Только самый свежий имеет право заменить нарисованный ряд.
let chartRequest = 0;
let openedBy = { openServer: null, openAuditRecord: null };

function openMetricsHelp() {
  if (document.getElementById('confirm-modal')?.classList.contains('open')) return;
  void infoModal({
    title: 'Мониторинг серверов',
    message: 'Период выбирает сохранённую историю и не запускает новые проверки. Отсутствие точек или разрыв линии означает отсутствие измерений, а не нулевую нагрузку. Метки показывают события рядом по времени, но не доказывают причину изменения показателей.',
    handbookAnchor: 'monitoring',
  });
}

function installMetricsHelp() {
  const row = document.querySelector('.metrics-range-row');
  if (!row || row.querySelector('[data-metrics-help]')) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'faq-help-link';
  button.dataset.metricsHelp = 'monitoring';
  button.textContent = 'ⓘ О мониторинге';
  button.addEventListener('click', openMetricsHelp);
  row.append(button);
}

export function bindMetricsUI(handlers = {}) {
  openedBy = { ...openedBy, ...handlers };
  installMetricsHelp();
  if (!availabilityListenerBound) {
    availabilityListenerBound = true;
    window.addEventListener('bot4vps:availability-changed', event => {
      const serverIds = event.detail?.serverIds;
      const serverId = state.metricsOpenServerId;
      if (state.page !== 'metrics' || !serverId || !Array.isArray(serverIds)
          || !serverIds.some(id => String(id) === serverId)) return;
      if (availabilityRefreshTimer) clearTimeout(availabilityRefreshTimer);
      availabilityRefreshTimer = setTimeout(() => {
        availabilityRefreshTimer = null;
        if (state.page === 'metrics' && state.metricsOpenServerId === serverId) {
          loadMetrics({ keepWindow: true }).catch(() => {});
        }
      }, AUDIT_REFRESH_MS);
    });
  }
  document.querySelectorAll('[data-metrics-range]').forEach(button => {
    button.addEventListener('click', () => {
      const range = button.dataset.metricsRange;
      if (range === 'custom') openCustomPeriod();
      else selectRange(range);
    });
  });
  setMetricsRangeUI(storedRange());
  syncDateInputLimits();
  dateInput()?.addEventListener('change', pickDateRange);
  dateToInput()?.addEventListener('change', pickDateRange);
  metricsSearchInput()?.addEventListener('input', event => {
    metricsSearch = event.currentTarget.value;
    const visible = filteredServers(lastOverview?.servers || []);
    if (state.metricsOpenServerId
        && !visible.some(server => server.server_id === state.metricsOpenServerId)) {
      toggleServer(state.metricsOpenServerId);
      return;
    }
    renderList();
  });
}

function dateInput() {
  return document.getElementById('metrics-date');
}

function dateToInput() {
  return document.getElementById('metrics-date-to');
}

function metricsSearchInput() {
  return document.getElementById('metrics-search');
}

function clearMetricsSearch() {
  metricsSearch = '';
  const input = metricsSearchInput();
  if (input) input.value = '';
}

function filteredServers(servers) {
  const query = metricsSearch.trim().toLowerCase();
  if (!query) return servers;
  const tokens = query.split(/\s+/);
  return servers.filter(server => {
    const blob = [server.server_name, server.server_id]
      .map(value => String(value || '').toLowerCase())
      .join(' ');
    return tokens.every(token => blob.includes(token));
  });
}

function takeDetail() {
  const detail = document.getElementById('metrics-detail');
  if (detail) detail.remove();
  return detail;
}

function parkDetail(box, detail) {
  if (!box || !detail) return;
  detail.hidden = true;
  box.after(detail);
}

function placeDetail(box, detail) {
  if (!box || !detail) return;
  const row = state.metricsOpenServerId
    ? box.querySelector(`[data-server-id="${CSS.escape(state.metricsOpenServerId)}"]`)
    : null;
  if (row) row.after(detail);
  else parkDetail(box, detail);
}

function resetOpenServerState() {
  state.metricsOpenServerId = null;
  state.metricsAt = null;
  windowAround = null;
  zoomWindow = null;
  selectedMarkId = null;
  visibleMarksById = new Map();
  openChartLegendValues = null;
}

function setOpenChartLegendValues(serverId, items) {
  if (state.metricsOpenServerId !== serverId) return;
  const values = Object.fromEntries(
    items
      .filter(item => item.name === 'load1' || item.name === 'ram_pct')
      .map(item => [item.name, item.text]),
  );
  const unchanged = openChartLegendValues?.serverId === serverId
    && openChartLegendValues.load1 === values.load1
    && openChartLegendValues.ram_pct === values.ram_pct;
  if (unchanged) return;
  openChartLegendValues = { serverId, ...values };
  queueMicrotask(() => {
    if (state.metricsOpenServerId === serverId) refreshOpenRow();
  });
}

function closeOpenServer(detail = null) {
  resetOpenServerState();
  syncUrl();
  closeChart(detail);
}

function syncDateInputLimits() {
  const max = panelCalendarToday();
  for (const input of [dateInput(), dateToInput()]) {
    if (input) input.max = max;
  }
}

function clearDateInputs() {
  if (dateInput()) dateInput().value = '';
  if (dateToInput()) dateToInput().value = '';
  syncDateInputLimits();
}

function pickDateRange() {
  const fromValue = dateInput()?.value || '';
  const toValue = dateToInput()?.value || '';
  if (!fromValue) {
    if (toValue && dateToInput()) dateToInput().value = '';
    resetZoom({ clearDates: false, closeCustom: false });
    return;
  }
  const win = panelDateRangeWindow(fromValue, toValue);
  if (!win) {
    toast('Эта дата ещё не наступила — данных за неё нет', false);
    syncDateInputLimits();
    return;
  }
  if (dateInput()) dateInput().value = win.start.value;
  if (dateToInput()) dateToInput().value = win.hasEnd ? win.end.value : '';
  setMetricsRangeUI('custom');
  if (state.metricsOpenServerId) {
    applyZoom(win);
    return;
  }
  zoomWindow = win;
  windowAround = null;
  state.metricsAt = null;
}

function storedRange() {
  try {
    const saved = localStorage.getItem(RANGE_KEY);
    return RANGES[saved] ? saved : '24h';
  } catch (_) { return '24h'; }
}

function customPeriodPanel() {
  return document.getElementById('metrics-custom-period');
}

function setMetricsRangeUI(range, { focusCustom = false } = {}) {
  const custom = range === 'custom';
  document.querySelectorAll('[data-metrics-range]').forEach(button => {
    const on = button.dataset.metricsRange === range;
    button.classList.toggle('on', on);
    button.setAttribute('aria-selected', String(on));
    if (button.dataset.metricsRange === 'custom') button.setAttribute('aria-expanded', String(custom));
  });
  const panel = customPeriodPanel();
  if (panel) panel.hidden = !custom;
  if (custom && focusCustom) dateInput()?.focus();
}

function openCustomPeriod() {
  setMetricsRangeUI('custom', { focusCustom: true });
}

export function selectRange(range) {
  if (!RANGES[range]) return;
  windowAround = null;
  clearDateInputs();
  // Окно выбрано заново — прежнее приближение к нему не относится.
  zoomWindow = null;
  // Другое окно — другие марки: в новом окне выделенного действия может уже
  // не быть, и подсветка строки без точки на графике врала бы.
  selectedMarkId = null;
  setMetricsRange(range);
  setMetricsRangeUI(range);
  loadMetrics();
}

/**
 * Окно ряда: приближенное (если пользователь приблизил), либо вокруг события,
 * либо последние `range`.
 *
 * Приближение — окно по времени, а не «растянутая картинка»: сужение окна
 * меняет шаг ряда (на узком участке приходят сырые пробы, на широком —
 * часовые), поэтому его считает сервер, а страница только помнит, что просила.
 */
function windowFor(at) {
  const moment = Number(at);
  const centered = Number.isFinite(moment) && !!moment;
  const span = centered ? RANGES['24h'] : (RANGES[state.metricsRange] || RANGES['24h']);
  // Часы панели, а не браузера (serverNow): окно считает сервер, и
  // расхождение клиентского времени сдвинуло бы его мимо данных.
  const now = nowSeconds();
  if (zoomWindow) {
    const from = Number(zoomWindow.from);
    const to = Math.min(Number(zoomWindow.to), now);
    if (to - from >= 60) return { from: Math.floor(from), to: Math.ceil(to), centered: false };
  }
  if (!centered) return { from: now - span, to: now, centered: false };
  let from = moment - span / 2;
  let to = moment + span / 2;
  // Окно не уезжает в будущее: сервер в него не смотрит, а график
  // растянулся бы пустотой справа.
  if (to > now) {
    from -= to - now;
    to = now;
  }
  // Страховка: событие обязано остаться внутри окна, иначе марка, ради
  // которой сюда пришли, оказалась бы за краем графика.
  if (from > moment) {
    from = moment - span / 2;
    to = moment + span / 2;
  }
  return { from: Math.floor(from), to: Math.ceil(to), centered: true };
}

export async function loadMetrics({ keepWindow = false } = {}) {
  const range = state.metricsRange || storedRange();
  if (!keepWindow) lastOverview = null;
  try {
    const data = await j(`/api/metrics/overview?range=${encodeURIComponent(range)}`);
    lastOverview = data;
  } catch (e) {
    const box = document.getElementById('metrics-list');
    const detail = takeDetail();
    if (box) {
      box.innerHTML = `<div class="empty">Не удалось прочитать историю: ${errorHtml(e)}</div>`;
      parkDetail(box, detail);
    }
    return;
  }
  renderList();
  if (state.metricsOpenServerId) await openServerChart(state.metricsOpenServerId);
}

function formatKiB(value) {
  let amount = Number(value);
  if (!Number.isFinite(amount) || amount < 0) return null;
  const units = ['КБ', 'МБ', 'ГБ', 'ТБ'];
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  const digits = amount >= 100 || unit === 0 ? 0 : 1;
  return `${amount.toFixed(digits).replace(/\.0$/, '')} ${units[unit]}`;
}

export function formatRam(used, total, percent) {
  const usedText = formatKiB(used);
  const totalText = formatKiB(total);
  if (!usedText || !totalText) return percent == null ? '—' : `${Number(percent).toFixed(0)} %`;
  const value = Number(percent);
  return Number.isFinite(value)
    ? `${usedText} / ${totalText} · ${value.toFixed(0)} %`
    : `${usedText} / ${totalText}`;
}

function averageSeries(points) {
  const values = (Array.isArray(points) ? points : []).flatMap(pair => {
    const raw = pair?.[1];
    if (raw === null || raw === undefined || raw === '' || typeof raw === 'boolean') return [];
    const value = Number(raw);
    return Number.isFinite(value) ? [value] : [];
  });
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatLoad(load, cpuCount) {
  const value = Number(load);
  const cpus = Number(cpuCount);
  if (!Number.isFinite(value) || !Number.isFinite(cpus) || cpus <= 0) return '—';
  return `${Math.min(100, Math.round(Math.max(0, value) / cpus * 100))}%`;
}

function lastValues(server) {
  const last = server.last || {};
  const spark = server.sparkline || {};
  const averageLoad = averageSeries(spark.load1);
  const averageRam = averageSeries(spark.ram_pct);
  const legendValues = openChartLegendValues?.serverId === server.server_id
    ? openChartLegendValues : null;
  const disk = [];
  const used = formatKiB(last.disk_used_kb);
  const total = formatKiB(last.disk_total_kb);
  if (used && total) disk.push(`${used} / ${total}`);
  if (last.disk_pct != null) disk.push(`${Number(last.disk_pct).toFixed(0)} %`);
  return {
    load1: legendValues?.load1 ?? formatLoad(
      last.load1 == null ? averageLoad : last.load1,
      last.cpu_count,
    ),
    ram: legendValues?.ram_pct ?? formatRam(
      last.ram_used_kb,
      last.ram_total_kb,
      last.ram_pct == null ? averageRam : last.ram_pct,
    ),
    disk: disk.join(' · ') || '—',
  };
}

function nowSeconds() {
  return Math.floor(serverNow().getTime() / 1000);
}

function ageLabel(ts) {
  const moment = Number(ts);
  if (!Number.isFinite(moment) || !moment) return 'точек ещё нет';
  const age = Math.max(0, nowSeconds() - moment);
  if (age < 90) return 'меньше минуты назад';
  if (age < 3600) return `${Math.round(age / 60)} мин назад`;
  if (age < 86400) return `${Math.round(age / 3600)} ч назад`;
  return `${Math.round(age / 86400)} дн назад`;
}

function renderList() {
  const box = document.getElementById('metrics-list');
  if (!box) return;
  const touch = document.getElementById('metrics-chart')?.__chartState?.touch;
  if (touch?.media.matches && touch.pointers.size) {
    touchListRefreshPending = true;
    return;
  }
  touchListRefreshPending = false;
  const detail = takeDetail();
  const allServers = lastOverview?.servers || [];
  const servers = filteredServers(allServers);
  if (state.metricsOpenServerId
      && !servers.some(server => server.server_id === state.metricsOpenServerId)) {
    closeOpenServer(detail);
  }
  if (!allServers.length) {
    box.innerHTML = '<div class="empty">Серверов нет. Добавьте сервер — и его история появится здесь.</div>';
    parkDetail(box, detail);
    return;
  }
  if (!servers.length) {
    box.innerHTML = '<div class="empty">По этому запросу серверов нет.</div>';
    parkDetail(box, detail);
    return;
  }

  const step = Number(lastOverview.sparkline_seconds) || Number(lastOverview.step_seconds)
    || (lastOverview.step === 'hour' ? 3600 : 900);
  box.innerHTML = servers.map(server => {
    const values = lastValues(server);
    const status = STATUS[server.status] || STATUS.stale;
    const open = server.server_id === state.metricsOpenServerId;
    return `
      <div class="metrics-row${open ? ' is-open' : ''}" role="button" tabindex="0"
           data-server-id="${esc(server.server_id)}" aria-expanded="${open ? 'true' : 'false'}">
        <div class="metrics-name">
          <span class="metrics-title">${esc(server.server_name || server.server_id)}</span>
          <span class="metrics-age">последняя точка: ${esc(ageLabel(server.last_ts))}</span>
        </div>
        <div class="metrics-status"><span class="badge ${status.cls}" title="${esc(status.hint)}"><span class="dot"></span>${status.text}</span></div>
        <div class="metrics-values">
          <span title="load1">${values.load1}</span>
          <span title="занятая память">${values.ram}</span>
          <span class="metrics-disk-value" title="системный раздел">${esc(values.disk)}</span>
        </div>
        <div class="metrics-spark" data-spark="${esc(server.server_id)}"
             title="форма, не масштаб: числа — слева, подсказка — в графике"></div>
        <div class="metrics-chev">${open ? '▾' : '›'}</div>
      </div>`;
  }).join('');
  placeDetail(box, detail);

  box.querySelectorAll('.metrics-row').forEach(row => {
    const serverId = row.dataset.serverId;
    const activate = () => toggleServer(serverId);
    row.addEventListener('click', activate);
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
    });
  });

  for (const server of servers) {
    const host = box.querySelector(`[data-spark="${CSS.escape(server.server_id)}"]`);
    if (!host) continue;
    const spark = server.sparkline || {};
    // Спарклайн ряда — форма, а не масштаб: три ряда с разными единицами
    // (load без потолка, проценты) масштабируются каждый по себе, а числа
    // рядом и в подсказке графика. Общая шкала здесь врала бы.
    renderSpark(host, [
      { points: spark.load1 || [], color: 'var(--accent)' },
      { points: spark.ram_pct || [], color: '#f472b6' },
      { points: spark.disk_max_pct || [], color: '#fb923c' },
    ], { stepSeconds: step, span: RANGES[state.metricsRange], gaps: normalizeGaps(server.gaps) });
  }
}

export function toggleServer(serverId) {
  const next = state.metricsOpenServerId === serverId ? null : serverId;
  if (!next) {
    closeOpenServer();
    renderList();
    return;
  }
  // Событие, вокруг которого строилось окно, относится к своему серверу:
  // у другого сервера то же окно показывало бы чужие сутки.
  if (state.metricsOpenServerId !== serverId) {
    state.metricsAt = null;
    windowAround = null;
    zoomWindow = null;
    selectedMarkId = null;            // марки живут в окне своего сервера
    visibleMarksById = new Map();
  }
  state.metricsOpenServerId = next;
  syncUrl();
  renderList();
  openServerChart(next);
}

function closeChart(detail = document.getElementById('metrics-detail')) {
  // Обесценивает ответ, который ещё летит для уже закрытого графика.
  chartRequest += 1;
  if (!detail) return;
  // Сначала рисунок, потом его контейнер: наблюдатель размера живёт на
  // `#metrics-chart`, а не на `#metrics-detail` (это его родитель), и
  // очистка родителя оставила бы наблюдателя висеть на оторванном узле.
  destroyChart(document.getElementById('metrics-chart'));
  destroyChart(detail);
  detail.hidden = true;
  detail.innerHTML = '';
}

/** Перерисовать список, не теряя раскрытый график (после кадра SSE). */
function refreshOpenRow() {
  renderList();
}

async function openServerChart(serverId) {
  const detail = document.getElementById('metrics-detail');
  if (!detail) return;
  // Тот же график уже нарисован? Тогда это уточнение окна (приближение,
  // выбор даты, новая проба) — разметку не пересобираем. Пересборка стоит
  // не только мигания: окно целиком «перезагружалось» под курсором, и
  // приближение колесом читалось как прыжок вместо приближения.
  const sameChart = !detail.hidden && detail.dataset.serverId === serverId
    && !!detail.querySelector('#metrics-chart');
  detail.hidden = false;
  windowAround = windowAround && windowAround.serverId === serverId ? windowAround : null;
  const at = state.metricsAt;
  const win = windowFor(windowAround ? windowAround.at : at);
  if (at && !windowAround) windowAround = { serverId, at };

  if (!sameChart) {
    // Прошлый рисунок снимается до замены разметки: разметка ниже создаёт
    // новый `#metrics-chart`, а наблюдатель размера остался бы на старом,
    // уже оторванном узле.
    destroyChart(document.getElementById('metrics-chart'));
    detail.innerHTML = '<div class="empty">Загрузка истории…</div>';
  }
  const query = `from=${win.from}&to=${win.to}&step=auto&line_context=true`;
  // Сдвиг и колесо запрашивают ряд прямо во время жеста. Сеть не обязана
  // сохранить порядок ответов, поэтому только последний запрос может менять
  // график или показывать ошибку.
  const requestId = ++chartRequest;
  let data;
  try {
    data = await j(`/api/timeline/${encodeURIComponent(serverId)}?${query}`);
  } catch (e) {
    if (requestId !== chartRequest || state.metricsOpenServerId !== serverId) return;
    detail.innerHTML = `<div class="empty">Не удалось прочитать ряд: ${errorHtml(e)}</div>`;
    detail.dataset.serverId = '';
    openChartLegendValues = null;
    refreshOpenRow();
    return;
  }
  // Пока грузился ряд, пользователь мог сдвинуть окно либо раскрыть другой
  // сервер. Старый ответ не имеет права вернуть предыдущий участок графика.
  if (requestId !== chartRequest || state.metricsOpenServerId !== serverId) return;

  const server = (lastOverview?.servers || []).find(item => item.server_id === serverId) || {};
  detail.dataset.serverId = serverId;
  if (sameChart) {
    // В шапке меняются только подпись окна и набор кнопок (кнопка возврата
    // появляется вместе с приближением), сам рисунок — ниже, на месте.
    const meta = detail.querySelector('.metrics-detail-meta');
    if (meta) meta.innerHTML = metaText(data, win);
    const actions = detail.querySelector('.metrics-detail-head .actions');
    if (actions) actions.innerHTML = headActions(win);
    bindDetail(detail, serverId);
    drawChart(data, win);
    return;
  }
  detail.innerHTML = `
    <div class="metrics-detail-head">
      <div class="metrics-detail-meta">${metaText(data, win)}</div>
      <div class="actions" style="margin:0">${headActions(win)}</div>
    </div>
    <div id="metrics-chart"></div>
    <div class="chart-hint chart-hint-desktop">Приблизить: покрутите колесо над графиком или протяните с Ctrl · без Ctrl протяжка двигает окно · даты задают только начальный участок</div>
    <div class="chart-hint chart-hint-touch">Касание — значения · щипок — масштаб · влево/вправо — сдвиг времени · вверх/вниз — прокрутка страницы</div>
    <div class="metrics-marks" id="metrics-marks"></div>`;

  bindDetail(detail, serverId);
  drawChart(data, win);
}

/** Подпись окна: что именно нарисовано и каким шагом. */
function metaText(data, win) {
  return `окно ${esc(formatServerDateTime(data.from))} — ${esc(formatServerDateTime(data.to))}
          · шаг ${data.step === 'hour' ? 'час' : 'проба'}
          ${win.centered ? ' · вокруг события' : ''}`;
}

/**
 * Кнопки шапки. Пересобираются вместе с окном: «Весь диапазон» существует
 * только пока окно приближено, «Последние 24 часа» — только вокруг события.
 */
function headActions(win) {
  return `${win.centered ? '<button type="button" class="secondary" data-metrics-recent>Последние 24 часа</button>' : ''}
        ${zoomWindow ? '<button type="button" class="secondary" data-metrics-full>Весь диапазон</button>' : ''}
        <button type="button" class="secondary" data-metrics-server>Открыть сервер</button>
        <button type="button" class="secondary" data-metrics-close>Свернуть</button>`;
}

function bindDetail(detail, serverId) {
  detail.querySelector('[data-metrics-close]')?.addEventListener('click', () => toggleServer(serverId));
  detail.querySelector('[data-metrics-server]')?.addEventListener('click', () => {
    if (openedBy.openServer) openedBy.openServer(serverId);
  });
  detail.querySelector('[data-metrics-recent]')?.addEventListener('click', () => {
    windowAround = null;
    state.metricsAt = null;
    zoomWindow = null;
    clearDateInputs();
    syncUrl();
    openServerChart(serverId);
  });
  detail.querySelector('[data-metrics-full]')?.addEventListener('click', () => resetZoom());
}

/** Рисунок и список действий — то, что меняется вместе с окном. */
function formatUptime(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return '—';
  const days = Math.floor(value / 86400);
  const hours = Math.floor(value % 86400 / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  return days ? `${days} д ${hours} ч` : `${hours} ч ${minutes} мин`;
}

function drawChart(data, win) {
  const marks = Array.isArray(data.marks) ? data.marks : [];
  const server = (lastOverview?.servers || []).find(
    item => item.server_id === state.metricsOpenServerId,
  ) || {};
  const sortedMarks = [...marks].sort((a, b) => Number(b.ts) - Number(a.ts));
  const host = document.getElementById('metrics-chart');
  renderTimeline(host, data, {
    formatTime: ts => formatServerTime(ts),
    formatDate: ts => {
      const parts = serverDateTimeParts(ts * 1000);
      return parts ? `${parts.day}.${parts.month}` : '';
    },
    formatDateTime: ts => formatServerDateTime(ts),
    cpuCount: server.last?.cpu_count,
    onLegendValues: items => setOpenChartLegendValues(server.server_id, items),
    onVisibleMarks: currentMarks => syncVisibleMarks(currentMarks, data.marks_truncated),
    // Клик по точке на графике — тоже выбор, а не уход со страницы: точка и
    // строка списка означают одно и то же действие.
    onMark: mark => selectMarkRow(mark?.audit_id),
    // Во время жеста подгружаем края без ожидания его конца; окончательное
    // окно всё равно приходит через onZoom после отпускания/паузы колеса.
    onWindowChange: applyZoom,
    onZoom: applyZoom,
    onResetZoom: () => resetZoom(),
    onTouchEnd: () => {
      if (touchListRefreshPending) refreshOpenRow();
    },
  });
  selectMark(host, selectedMarkId);

  const marksBox = document.getElementById('metrics-marks');
  if (!marksBox) return;
  marksBox.innerHTML = `
    <div class="metrics-marks-title"></div>
    <div class="metrics-marks-list">
      ${sortedMarks.map(mark => `
        <div class="metrics-mark-row${String(mark.audit_id) === selectedMarkId ? ' is-selected' : ''}">
          <button type="button" class="metrics-mark" data-mark-id="${esc(mark.audit_id)}"
                  aria-pressed="${String(mark.audit_id) === selectedMarkId ? 'true' : 'false'}"
                  title="Выделить событие на графике">
            <span class="metrics-mark-chip" style="background:${resultColor(mark.result)}"></span>
            <span class="metrics-mark-title">${esc(mark.title || mark.action)}</span>
            <span class="metrics-mark-meta">
              ${esc(mark.actor?.id ? `${mark.actor.type}: ${mark.actor.id}` : (mark.actor?.type || 'система'))}
              · ${esc(formatServerDateTime(mark.ts))}${mark.ts_end && mark.ts_end !== mark.ts ? `–${esc(formatServerDateTime(mark.ts_end))}` : ''}
              · ${esc(mark.availability
                ? (mark.availability.online ? 'онлайн' : 'недоступен')
                : (mark.result === 'incomplete'
                  ? 'Нет записи о завершении'
                  : (mark.result === 'awaiting_rule_selection'
                    ? 'Ожидается выбор правил'
                    : mark.result)))}
            </span>
          </button>
          ${mark.availability ? '' : `<button type="button" class="metrics-mark-open" data-mark-open="${esc(mark.audit_id)}"
                  title="Открыть запись в журнале действий">Открыть запись</button>`}
        </div>`).join('')}
    </div>
    <div class="metrics-marks-empty" hidden>Действий в этом окне не было.</div>`;

  marksBox.querySelectorAll('.metrics-mark').forEach(button => {
    button.addEventListener('click', () => chooseMark(button.dataset.markId));
  });
  marksBox.querySelectorAll('[data-mark-open]').forEach(button => {
    button.addEventListener('click', () => openMark({ audit_id: button.dataset.markOpen }));
  });
  syncVisibleMarks(marks, data.marks_truncated);
}

function syncVisibleMarks(marks, truncated) {
  const visible = Array.isArray(marks) ? marks : [];
  visibleMarksById = new Map(visible.map(mark => [String(mark.audit_id), mark]));
  const marksBox = document.getElementById('metrics-marks');
  if (!marksBox) return;
  const title = marksBox.querySelector('.metrics-marks-title');
  const list = marksBox.querySelector('.metrics-marks-list');
  const empty = marksBox.querySelector('.metrics-marks-empty');
  if (!title || !list || !empty) return;
  const ids = new Set(visibleMarksById.keys());
  title.textContent = `События в окне (${visible.length}${truncated ? ', показаны не все' : ''})`;
  list.hidden = !visible.length;
  empty.hidden = !!visible.length;
  marksBox.querySelectorAll('.metrics-mark-row').forEach(row => {
    const id = row.querySelector('.metrics-mark')?.dataset.markId;
    row.hidden = !ids.has(id);
  });
}

/**
 * Приближение к выделенному участку.
 *
 * Марку не сбрасываем: действие, выбранное до приближения, может остаться в
 * новом окне — и останется подсвеченным. А вот окно вокруг события теряет
 * смысл: пользователь только что задал окно сам.
 */
function applyZoom({ from, to }) {
  if (!state.metricsOpenServerId) return;
  zoomWindow = { from: Number(from), to: Number(to) };
  windowAround = null;
  state.metricsAt = null;
  syncUrl();
  openServerChart(state.metricsOpenServerId);
}

function resetZoom({ clearDates = true, closeCustom = true } = {}) {
  if (clearDates) clearDateInputs();
  if (closeCustom) setMetricsRangeUI(state.metricsRange || storedRange());
  if (!state.metricsOpenServerId) return;
  zoomWindow = null;
  windowAround = null;
  state.metricsAt = null;
  syncUrl();
  openServerChart(state.metricsOpenServerId);
}

/**
 * Выделить действие. Возвращает выбор к `auditId`; без него — снимает выбор.
 *
 * Так ведёт себя клик по марке на графике: у точки есть невидимая широкая
 * цель, но попасть можно и мимо, поэтому повторный клик не должен «отменять» показанное —
 * гасит выделение клик по пустому месту графика (тогда `onMark` зовётся без
 * марки). Список действий устроен иначе (см. `chooseMark`) — там клик по
 * строке переключает.
 *
 * Подсвечивает точку на графике и строку в списке, но **никуда не уводит**:
 * пользователь читает окно, и переход в «Историю» вырывал бы его из этого
 * чтения. Запись аудита открывается кнопкой рядом со строкой.
 */
function selectMarkRow(auditId) {
  selectedMarkId = auditId ? String(auditId) : null;
  selectMark(document.getElementById('metrics-chart'), selectedMarkId);
  const marksBox = document.getElementById('metrics-marks');
  if (!marksBox) return;
  marksBox.querySelectorAll('.metrics-mark-row').forEach(row => {
    const chip = row.querySelector('.metrics-mark');
    const on = !!selectedMarkId && chip?.dataset.markId === selectedMarkId;
    row.classList.toggle('is-selected', on);
    if (chip) chip.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  // Выделение видно на графике, а список действий может быть длиннее экрана:
  // без этого клик по дальней строке подсветил бы то, чего не видно.
  if (selectedMarkId) {
    document.getElementById('metrics-chart')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

/** Клик по строке списка действий: повторный клик по той же строке снимает выбор. */
function chooseMark(auditId) {
  if (!auditId) return;
  const id = String(auditId);
  if (selectedMarkId === id) {
    selectMarkRow(null);
    return;
  }
  const at = Number(visibleMarksById.get(id)?.ts);
  selectMarkRow(id);
  if (!state.metricsOpenServerId || !Number.isFinite(at) || !at) return;
  zoomWindow = null;
  state.metricsAt = at;
  windowAround = { serverId: state.metricsOpenServerId, at };
  syncUrl();
  openServerChart(state.metricsOpenServerId);
}

/** Переход в запись журнала — явное действие кнопки, а не выбор строки. */
function openMark(mark) {
  if (!mark?.audit_id) return;
  if (openedBy.openAuditRecord) {
    openedBy.openAuditRecord(mark.audit_id, { server_id: state.metricsOpenServerId });
    return;
  }
  // Обработчик не подключён (страница открыта вне app.js) — ведём адресом,
  // чтобы переход всё равно работал.
  window.location.href = `/?page=history&tab=actions&record=${encodeURIComponent(mark.audit_id)}`;
}

/**
 * Адрес страницы: раскрытый сервер, окно вокруг события и приближение
 * переживают F5.
 *
 * Адрес описывает **эту** страницу и только её: параметры, по которым
 * открывают другие разделы (`tab`, `record`), отсюда уходят. Иначе ссылка
 * вида `?page=metrics&tab=actions` рассказывала бы о двух страницах сразу, а
 * скопированная из строки браузера — открывала бы третью.
 */
function syncUrl() {
  try {
    const url = new URL(window.location.href);
    if (state.page !== 'metrics') return;
    url.searchParams.set('page', 'metrics');
    for (const foreign of ['tab', 'record']) url.searchParams.delete(foreign);
    if (state.metricsOpenServerId) url.searchParams.set('server_id', state.metricsOpenServerId);
    else url.searchParams.delete('server_id');
    // Приближенное окно уточняет окно события: одновременно их не бывает
    // (приближение снимает `at`), поэтому в адрес идёт что-то одно.
    const at = windowAround?.at || state.metricsAt;
    if (state.metricsOpenServerId && zoomWindow) {
      url.searchParams.set('from', String(zoomWindow.from));
      url.searchParams.set('to', String(zoomWindow.to));
    } else {
      url.searchParams.delete('from');
      url.searchParams.delete('to');
    }
    if (state.metricsOpenServerId && at && !zoomWindow) url.searchParams.set('at', String(at));
    else url.searchParams.delete('at');
    if (state.metricsOpenServerId && selectedMarkId) url.searchParams.set('audit_id', selectedMarkId);
    else url.searchParams.delete('audit_id');
    history.replaceState(null, '', `${url.pathname}${url.search}`);
  } catch (_) { /* адрес — удобство, не условие работы */ }
}

/** Разбор адреса при входе на страницу (в т.ч. переход с марки аудита). */
export function metricsFromUrl() {
  let params;
  try {
    params = new URL(window.location.href).searchParams;
  } catch (_) { return null; }
  if (params.get('page') !== 'metrics') return null;
  const serverId = params.get('server_id');
  const auditId = params.get('audit_id');
  const at = Number(params.get('at'));
  const from = Number(params.get('from'));
  const to = Number(params.get('to'));
  const zoomed = Number.isFinite(from) && Number.isFinite(to) && from > 0 && to > from;
  return {
    serverId: serverId || null,
    auditId: auditId || null,
    at: Number.isFinite(at) && at > 0 ? at : null,
    zoom: zoomed ? { from, to } : null,
  };
}

/** Вход на страницу: из навигации или по адресу. */
export async function openMetricsPage({ serverId = null, auditId = null, at = null, zoom = null } = {}) {
  setPage('metrics');
  showPage('metrics');
  if (serverId) clearMetricsSearch();
  if (serverId || auditId || at || zoom) {
    // Пришли по ссылке (карточка сервера, марка графика, запись аудита,
    // приближенный участок): цель из адреса главнее того, что страница
    // помнила.
    state.metricsOpenServerId = serverId || state.metricsOpenServerId;
    state.metricsAt = at;
    selectedMarkId = auditId ? String(auditId) : null;
    zoomWindow = zoom;
    windowAround = serverId && at && !zoom ? { serverId, at } : null;
  }
  // Без цели (обычный клик по меню) раскрытый сервер не сбрасывается:
  // пользователь уходил в аудит и вернулся, и сворачивать график, который он
  // только что смотрел, — терять его выбор. `syncUrl` ниже дописывает адрес,
  // так что «что открыто» и «что в адресе» снова совпадают.
  const range = state.metricsRange || storedRange();
  setMetricsRange(range);
  setMetricsRangeUI(range);
  syncDateInputLimits();
  await loadMetrics({ keepWindow: true });
  if (serverId) {
    const row = document.querySelector(
      `.metrics-row[data-server-id="${CSS.escape(String(serverId))}"]`,
    );
    row?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  syncUrl();
  startMetricsPolling();
}

export function stopMetricsPolling() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/**
 * Уход со страницы: погасить таймер и снять рисунок.
 *
 * Рисунок не остаётся «на память». Он построен для своего окна, а после
 * перехода с марки — вокруг своего события, и при возвращении на страницу
 * висел бы до ответа сервера: чужое окно под текущим адресом, да ещё с
 * подписью «вокруг события» там, где окно уже обычное. Пусть лучше будет
 * видно «Загрузка истории…» — это правда.
 */
export function closeMetricsView() {
  stopMetricsPolling();
  if (auditRefreshTimer) {
    clearTimeout(auditRefreshTimer);
    auditRefreshTimer = null;
  }
  if (availabilityRefreshTimer) {
    clearTimeout(availabilityRefreshTimer);
    availabilityRefreshTimer = null;
  }
  windowAround = null;
  state.metricsAt = null;
  selectedMarkId = null;
  closeChart();
}

function startMetricsPolling() {
  stopMetricsPolling();
  timer = setInterval(() => {
    if (state.page !== 'metrics') return;
    loadMetrics({ keepWindow: true }).catch(() => {});
  }, REFRESH_MS);
}

export function applyAuditFrame(frame) {
  if (!frame || state.page !== 'metrics') return;
  const serverId = String(frame.server_id ?? '').trim();
  if (!serverId || state.metricsOpenServerId !== serverId) return;
  if (auditRefreshTimer) clearTimeout(auditRefreshTimer);
  auditRefreshTimer = setTimeout(() => {
    auditRefreshTimer = null;
    if (state.page !== 'metrics' || state.metricsOpenServerId !== serverId) return;
    openServerChart(serverId).catch(() => {});
  }, AUDIT_REFRESH_MS);
}

/**
 * Кадр `event: metrics` (§11): одна проба одного сервера.
 *
 * Строку списка обновляем на месте, а раскрытый график перечитываем: в кадре
 * нет исторического максимума по всем монтированиям и остальных точек ряда,
 * поэтому ряд диска из него не дорисовываем.
 */
export function applyMetricsFrame(frame) {
  if (!frame || state.page !== 'metrics' || !lastOverview) return;
  const servers = lastOverview.servers || [];
  const server = servers.find(item => item.server_id === frame.server_id);
  if (!server) return;
  const point = [Number(frame.ts), null];
  const push = (list, value, rounded) => {
    if (value == null || !Array.isArray(list)) return;
    list.push([point[0], rounded ? Number(Number(value).toFixed(rounded)) : Number(value)]);
    // Спарклайн окна не растёт бесконечно: держим его в тех же границах,
    // что и сервер (окно / ширина корзины), иначе точка сдвинула бы форму.
    const limit = Math.max(16, Number(lastOverview.sparkline_points) || 48);
    while (list.length > limit) list.shift();
  };
  server.last_ts = Number(frame.ts);
  server.last = {
    ...(server.last || {}),
    load1: frame.load1 ?? server.last?.load1 ?? null,
    cpu_count: frame.cpu_count ?? server.last?.cpu_count ?? null,
    ram_pct: frame.ram_pct ?? server.last?.ram_pct ?? null,
    ram_used_kb: frame.ram_used_kb ?? null,
    ram_total_kb: frame.ram_total_kb ?? null,
    disk_pct: frame.disk_pct ?? null,
    disk_used_kb: frame.disk_used_kb ?? null,
    disk_total_kb: frame.disk_total_kb ?? null,
    disk_mount: frame.disk_mount ?? null,
  };
  server.status = 'ok';
  server.sparkline = server.sparkline || { load1: [], ram_pct: [], disk_max_pct: [] };
  push(server.sparkline.load1, frame.load1, 3);
  push(server.sparkline.ram_pct, frame.ram_pct, 1);
  refreshOpenRow();
  if (state.metricsOpenServerId === frame.server_id) {
    openServerChart(frame.server_id).catch(() => {});
  }
}

/**
 * Поток переподключился (`hello`): поток отдаёт только свежее и пропущенное
 * не досылает, поэтому историю перечитываем запросом — иначе вкладка
 * осталась бы на данных до разрыва.
 */
export function reloadMetricsAfterReconnect() {
  if (state.page !== 'metrics') return;
  loadMetrics({ keepWindow: true }).catch(e => toast(e.message, false));
}

export function metricsIsOpen() {
  return state.page === 'metrics';
}
