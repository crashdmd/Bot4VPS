/**
 * Рисунок ряда метрик: линии с разрывами, точки событий, подсказка.
 *
 * Библиотек в панели нет — ни одной, кроме xterm и codemirror, — и графики
 * здесь рисуются сами. Поэтому модуль нарочно ничего не знает ни про
 * метрики, ни про формат времени панели: подписи приходят снаружи
 * (`opts.formatTime`/`formatDateTime`), а данные — ровно в форме §10.1/§10.3.
 *
 * Два правила, ради которых этот файл существует:
 *
 * 1. **Разрыв не интерполируется** (инвариант 5 ТЗ). Линия рвётся там, где
 *    точек нет: либо между соседними точками прошло больше полутора шагов,
 *    либо промежуток накрыт разрывом из ответа. Гладкая кривая через дыру
 *    нарисовала бы ровный график у сервера, который полдня не отвечал, —
 *    то есть соврала бы именно в том месте, ради которого график открыли.
 *    По той же причине отрезки прямые, без сглаживания: сглаживание
 *    выдумывает значения между точками, а панель показывает замеры.
 * 2. **Марка — точка события** (§10.3): `ts` — когда действие началось,
 *    `ts_end` — когда закончилось (у незакрытого — кольцо вместо заливки).
 *    Полосы во всю высоту графика убраны: пользователь читает ими не
 *    длительность действия, а всплеск нагрузки, и вертикальные линии его
 *    закрывали. Длительность видна в списке действий под графиком.
 */
import { esc } from './api.js';

export const SERIES_COLORS = {
  load1: '#60a5fa',
  ram_pct: '#f472b6',
  disk_max_pct: '#fb923c',
};

const SERIES_TITLES = {
  load1: 'Загрузка / CPU',
  ram_pct: 'Память/RAM',
  disk_max_pct: 'Диск',
};

// Порядок рядов — как в ответе API (§10.3): он же порядок в легенде.
const SERIES_ORDER = ['load1', 'ram_pct', 'disk_max_pct'];

// Разрыв — просвет больше полутора номинальных интервалов (то же правило,
// что в ядре, `core/metrics._gaps`). Здесь оно повторено не для того, чтобы
// переспорить ядро, а потому что линия обязана рваться и на данных, у
// которых списка разрывов нет вовсе: у спарклайна overview он свой, а у
// часового шага — своя ширина шага.
const GAP_FACTOR = 1.5;
/** Радиус попадания в марку, пиксели: точка события узкая, но промах не должен
 *  оборачиваться «клик ни по чему» — выбор есть, и он виден. */
const MARK_HIT_PX = 14;
/** Радиус попадания в саму точку события: у неё приоритет над широкой целью. */
const DOT_HIT_PX = 7;
const SELECTED_EVENT_TIP_OFFSET = 48;
/** Уже этого окна не приближаем: проб в нём почти нет, а каждый жест мышью
 *  ходил бы в базу за новым рядом. */
const MIN_ZOOM_SECONDS = 300;
let timelineClipSequence = 0;
const MOBILE_CHART_QUERY = '(max-width:760px) and (pointer:coarse), (max-height:500px) and (orientation:landscape) and (pointer:coarse)';
const TOUCH_MOVE_PX = 8;

const RESULT_COLORS = {
  ok: 'var(--ok)',
  failed: 'var(--err)',
  cancelled: 'var(--text-dim)',
  awaiting_rule_selection: 'var(--warn)',
  incomplete: 'var(--warn)',
};

function resultLabel(result) {
  if (result === 'incomplete') return 'Нет записи о завершении';
  if (result === 'awaiting_rule_selection') return 'Ожидается выбор правил';
  return result;
}

export function resultColor(result) {
  return RESULT_COLORS[String(result || '')] || 'var(--text-dim)';
}

/**
 * Привести `gaps` к одной форме.
 *
 * В контракте (§10.1) они в двух видах: в overview — тройки
 * `[from, to, reason]`, в series и таймлайне — объекты `{from, to, reason}`.
 * Это отмечено в ТЗ как черновик; контракт заморожен, поэтому расхождение
 * разбирает фронт — ровно в одном месте, чтобы формы не расползлись по
 * страницам.
 */
export function normalizeGaps(raw) {
  const out = [];
  if (!Array.isArray(raw)) return out;
  for (const item of raw) {
    let from, to, reason;
    if (Array.isArray(item)) {
      [from, to, reason] = item;
    } else if (item && typeof item === 'object') {
      ({ from, to, reason } = item);
    } else {
      continue;
    }
    from = Number(from);
    to = Number(to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) continue;
    if (to < from) [from, to] = [to, from];
    out.push({ from, to, reason: reason || 'no_data' });
  }
  out.sort((a, b) => a.from - b.from);
  return out;
}

/**
 * Накрывает ли разрыв промежуток **между** двумя точками.
 *
 * Сравнение строгое с обеих сторон, и это не придирка. Разрывы приходят не
 * только из середины ряда: `_gaps` в ядре отдаёт разрывом и пропущенный
 * край — `[начало окна … первая точка]` или `[последняя точка … конец окна]`
 * (`core/metrics.py`). Такой разрыв касается своей точкой края промежутка,
 * но не лежит внутри него: данных между первой и второй точками он не
 * отменяет. С нестрогим сравнением он рвал бы первый же отрезок, и ряд,
 * начавшийся внутри окна (обычное дело: сутки запрошены, а сбор идёт час),
 * открывался бы точкой и только со второй пары — линией.
 */
function gapCovers(gaps, t1, t2) {
  for (const gap of gaps) {
    if (gap.from < t2 && gap.to > t1) return true;
  }
  return false;
}

/**
 * Разбить ряд на непрерывные отрезки.
 *
 * `points` — пары `[ts, value]` из ответа API. Отрезок обрывается, если
 * между соседними точками прошло больше полутора шагов или если промежуток
 * накрыт разрывом из ответа. `intentionalConnection` разрешает только явно
 * назначенную связь. Возвращает массив массивов: каждый — свой `path`, между
 * ними линия не рисуется.
 *
 * Шаг берётся как максимум из объявленного и фактического (медиана разниц):
 * у спарклайна overview корзина шире шага сбора (1800 против 900), а у
 * часового ряда — своя. Объявленный шаг, меньший фактического, порвал бы
 * линию на каждом стыке корзин и превратил бы график в пунктир из точек.
 */
/**
 * Точки ряда в числах: отбросить пустое, отсортировать по времени.
 *
 * Отдельная тонкость — `Number(null)`, `Number('')` и `Number([])` дают
 * **ноль**. Пропущенное значение, превратившееся в ноль, — это ровно тот
 * обман, ради которого инвариант «отсутствие ≠ 0» и записан: на графике
 * появился бы провал нагрузки или мгновенно освободившийся диск. Ядро
 * такие значения не отдаёт (`_append` в `core/metrics.py` пишет точку,
 * только если значение есть), но если однажды отдаст — ряд обязан
 * потерять точку, а не показать ноль. Поэтому пустое отсекается **до**
 * приведения к числу.
 */
function cleanPoints(points) {
  const out = [];
  for (const pair of Array.isArray(points) ? points : []) {
    const ts = finite(pair?.[0]);
    const value = finite(pair?.[1]);
    if (ts === null || value === null) continue;
    out.push([ts, value]);
  }
  return out.sort((a, b) => a[0] - b[0]);
}

function finite(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function splitSegments(points, stepSeconds, gaps, intentionalConnection) {
  const clean = cleanPoints(points);
  if (!clean.length) return [];

  const declared = Number(stepSeconds) > 0 ? Number(stepSeconds) : 0;
  const step = Math.max(declared, medianStep(clean));
  const list = Array.isArray(gaps) ? gaps : [];
  const segments = [[clean[0]]];
  for (let i = 1; i < clean.length; i++) {
    const [prevTs] = clean[i - 1];
    const [ts] = clean[i];
    const intentional = typeof intentionalConnection === 'function'
      && intentionalConnection(prevTs, ts);
    const broken = !intentional && (
      (step > 0 && ts - prevTs > step * GAP_FACTOR)
      || (list.length > 0 && gapCovers(list, prevTs, ts))
    );
    if (broken) segments.push([clean[i]]);
    else segments[segments.length - 1].push(clean[i]);
  }
  return segments;
}

/** Типичный интервал между точками ряда: медиана положительных разниц. */
function medianStep(points) {
  const deltas = [];
  for (let i = 1; i < points.length; i++) {
    const delta = points[i][0] - points[i - 1][0];
    if (delta > 0) deltas.push(delta);
  }
  if (!deltas.length) return 0;
  deltas.sort((a, b) => a - b);
  return deltas[Math.floor(deltas.length / 2)];
}

/** Подпись разрыва для подсказки: «12:40–13:25 · данных нет». */
export function gapLabel(gap, formatTime) {
  const time = typeof formatTime === 'function' ? formatTime : (ts => String(ts));
  return `${time(gap.from)}–${time(gap.to)} · данных нет`;
}

function pickStep(span) {
  // Ширина шага для определения разрыва: она же в ответе (`step_seconds`
  // мы не получаем) — поэтому выводим из шага API: raw = 15 мин, hour = 1 ч.
  return span > 7 * 86400 ? 3600 : 900;
}

function niceTicks(from, to, count) {
  const span = to - from;
  if (!(span > 0) || count < 2) return [from];
  const ticks = [];
  for (let i = 0; i <= count; i++) ticks.push(from + (span * i) / count);
  return ticks;
}

function loadPercent(value, cpuCount) {
  const load = Number(value);
  const cpus = Number(cpuCount);
  if (!Number.isFinite(load) || !Number.isFinite(cpus) || cpus <= 0) return null;
  return Math.max(0, load) / cpus * 100;
}

function displayLoad(value, cpuCount) {
  const percent = loadPercent(value, cpuCount);
  if (percent == null) return null;
  return percent > 100 ? '100%' : `${Math.round(percent)}%`;
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
  return `${amount.toFixed(digits).replace(/\\.0$/, '')} ${units[unit]}`;
}

function fmtValue(series, value, opts = {}, mount = null) {
  if (value == null) return '—';
  if (series === 'load1') {
    if (opts.loadPercentPoints) return value >= 100 ? '100%' : `${Math.round(value)}%`;
    return displayLoad(value, opts.cpuCount) || Number(value).toFixed(2);
  }
  const snapshot = opts.snapshot || null;
  if (series === 'ram_pct' && snapshot) {
    const used = formatKiB(snapshot.ram_used_kb);
    const total = formatKiB(snapshot.ram_total_kb);
    if (used && total) {
      const percent = Number(value);
      return Number.isFinite(percent)
        ? `${used} / ${total} · ${percent.toFixed(0)}%`
        : `${used} / ${total}`;
    }
  }
  const disk = mount && snapshot?.disks?.[mount];
  if (series === 'disk_max_pct' && disk) {
    const used = formatKiB(disk.used_kb);
    const total = formatKiB(disk.total_kb);
    if (used && total) return `${used} / ${total} · ${Number(value).toFixed(0)}%`;
  }
  return `${Number(value).toFixed(0)}%`;
}

function snapshotAt(rawValues, ts) {
  const sampleTs = Number(ts);
  if (!rawValues || !Number.isInteger(sampleTs)) return null;
  const snapshot = rawValues[String(sampleTs)];
  return Number(snapshot?.sample_ts) === sampleTs ? snapshot : null;
}

function onlineSnapshotAt(rawValues, ts) {
  const eventTs = finite(ts);
  if (eventTs === null || !rawValues) return null;
  let closest = null;
  let distance = Infinity;
  for (const snapshot of Object.values(rawValues)) {
    if (snapshot?.source !== 'online') continue;
    const sampleTs = finite(snapshot.sample_ts);
    if (sampleTs === null) continue;
    const delta = Math.abs(sampleTs - eventTs);
    if (delta < distance) {
      closest = snapshot;
      distance = delta;
    }
  }
  return distance <= 60 ? closest : null;
}

function availabilitySnapshot(data, mark) {
  if (!mark.availability?.online) return null;
  return onlineSnapshotAt(data.raw_values, mark.ts);
}

function peakMetricRows(metrics) {
  const rows = [];
  const load = finite(metrics?.load1);
  const cpuCount = finite(metrics?.cpu_count);
  if (load !== null) {
    const value = cpuCount !== null && cpuCount > 0
      ? `${load.toFixed(2)} / ${Math.round(cpuCount)} CPU · ${displayLoad(load, cpuCount)}`
      : load.toFixed(2);
    rows.push(`<div class="chart-operation-value">Загрузка / CPU: <b>${esc(value)}</b></div>`);
  }
  const ramUsed = formatKiB(metrics?.ram_used_kb);
  const ramTotal = formatKiB(metrics?.ram_total_kb);
  if (ramUsed || ramTotal) {
    rows.push(`<div class="chart-operation-value">Память / RAM: <b>${esc(ramUsed && ramTotal ? `${ramUsed} / ${ramTotal}` : (ramUsed || ramTotal))}</b></div>`);
  }
  const disk = (Array.isArray(metrics?.disks) ? metrics.disks : [])
    .map(item => ({ item, usedPct: finite(item?.used_pct) }))
    .filter(({ item, usedPct }) => usedPct !== null || formatKiB(item?.used_kb) || formatKiB(item?.total_kb))
    .sort((left, right) => (right.usedPct ?? -1) - (left.usedPct ?? -1))[0]?.item;
  if (disk) {
    const used = formatKiB(disk.used_kb);
    const total = formatKiB(disk.total_kb);
    const percent = finite(disk.used_pct);
    const capacity = used && total ? `${used} / ${total}` : (used || total || '—');
    const suffix = percent === null ? '' : ` · ${percent.toFixed(0)}%`;
    rows.push(`<div class="chart-operation-value">Диск ${esc(String(disk.mount || '—'))}: <b>${esc(`${capacity}${suffix}`)}</b></div>`);
  }
  return rows.length ? rows.join('') : '<div class="chart-operation-value">Нет числовых значений.</div>';
}

function availabilityTip(mark, opts, snapshot = null) {
  const time = opts.formatDateTime || opts.formatTime || (value => String(value));
  const online = Boolean(mark.availability?.online);
  const rows = [
    '<section class="chart-operation-observations chart-availability-observation">',
    `<div class="chart-operation-title">${esc(online ? 'Сервер снова доступен' : 'Сервер недоступен')}</div>`,
    `<div class="chart-operation-meta">${online ? 'Возврат онлайн' : 'Недоступен с'}: ${esc(time(Math.round(Number(mark.ts))))}</div>`,
  ];
  const error = String(mark.availability?.error || '').trim();
  if (error) rows.push(`<div class="chart-operation-status">Причина: ${esc(error)}</div>`);
  if (online) {
    if (!snapshot) {
      rows.push('<div class="chart-operation-status">Метрики в момент возврата не получены.</div>');
    } else {
      rows.push('<div class="chart-operation-meta">Метрики в момент возврата:</div>');
      rows.push(peakMetricRows({ ...snapshot, disks: Object.values(snapshot.disks || {}) }));
    }
  }
  rows.push('</section>');
  return rows.join('');
}

function operationPeakTip(mark, opts, availabilitySnapshot = null) {
  if (mark.availability) return availabilityTip(mark, opts, availabilitySnapshot);
  const time = opts.formatDateTime || opts.formatTime || (value => String(value));
  const rows = [
    '<section class="chart-operation-observations">',
    `<div class="chart-operation-title">${esc(mark.title || mark.action)}</div>`,
    `<div class="chart-operation-meta">Начало: ${esc(time(Math.round(Number(mark.ts))))}</div>`,
  ];
  const endedAt = finite(mark.ended_at);
  if (endedAt !== null) {
    rows.push(`<div class="chart-operation-meta">Окончание: ${esc(time(Math.round(endedAt)))}</div>`);
  }
  if (mark.result === 'incomplete') {
    rows.push('<div class="chart-operation-status">Нет записи о завершении.</div>');
  } else if (mark.result === 'awaiting_rule_selection') {
    rows.push('<div class="chart-operation-status">Ожидается выбор правил.</div>');
  }
  const peak = mark.peak;
  const capturedAt = finite(peak?.captured_at);
  if (capturedAt === null || !peak?.metrics) {
    rows.push('<div class="chart-operation-status">Фактический пик не получен.</div>');
  } else {
    rows.push(`<div class="chart-operation-meta">Пик: ${esc(time(Math.round(capturedAt)))}</div>`);
    rows.push(peakMetricRows(peak.metrics));
  }
  rows.push('</section>');
  return rows.join('');
}

function pointsToPath(points, x, y) {
  let d = '';
  points.forEach(([ts, value], index) => {
    d += `${index ? ' L' : 'M'}${x(ts).toFixed(1)} ${y(value).toFixed(1)}`;
  });
  return d;
}

function nearestPoint(points, ts) {
  if (!points || !points.length) return null;
  let best = null;
  let bestDelta = Infinity;
  for (const [pointTs, value] of points) {
    const delta = Math.abs(pointTs - ts);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = [pointTs, value];
    }
  }
  return best;
}

function interpolatedValueAt(points, ts, stepSeconds, gaps) {
  let previous = null;
  for (const point of points) {
    const [pointTs, value] = point;
    if (pointTs === ts) return value;
    if (pointTs > ts) {
      if (!previous) return null;
      const [previousTs, previousValue] = previous;
      const expectedStep = Math.max(stepSeconds, medianStep(points));
      if (pointTs - previousTs > expectedStep * GAP_FACTOR || gapCovers(gaps, previousTs, pointTs)) return null;
      return previousValue + (value - previousValue) * ((ts - previousTs) / (pointTs - previousTs));
    }
    previous = point;
  }
  return null;
}

/** Убрать прошлый рисунок и наблюдатель размера у контейнера. */
export function destroyChart(host) {
  if (!host) return;
  const state = host.__chartState;
  if (state?.gesture?.timer) clearTimeout(state.gesture.timer);
  if (state?.gesture?.loadTimer) clearTimeout(state.gesture.loadTimer);
  if (state?.observer) state.observer.disconnect();
  state?.touch?.cleanup();
  host.__chartState = null;
  host.innerHTML = '';
}

/** Touch слушает контейнер: preview и ответы API заменяют SVG прямо под пальцами. */
function bindTimelineTouch(host) {
  const media = window.matchMedia(MOBILE_CHART_QUERY);
  const touch = {
    media, pointers: new Map(), mode: null, base: null,
    noTap: false, changed: false, ignoreMouseUntil: 0,
  };
  const actions = () => host.__chartState?.touchActions;
  const release = id => {
    if (host.hasPointerCapture(id)) host.releasePointerCapture(id);
  };
  const suppressMouse = () => { touch.ignoreMouseUntil = Date.now() + 1000; };
  const rebase = () => {
    const current = actions();
    if (!current) return;
    const pointers = [...touch.pointers.values()];
    const geometry = current.geometry();
    const win = host.__chartState.window;
    const midpoint = pointers.length > 1
      ? (pointers[0].x + pointers[1].x) / 2 : pointers[0].x;
    touch.base = {
      ...win, ...geometry, x: midpoint,
      distance: pointers.length > 1
        ? Math.hypot(pointers[1].x - pointers[0].x, pointers[1].y - pointers[0].y) : 0,
    };
  };
  const finish = (notify = true) => {
    if (touch.changed) actions()?.finish();
    touch.changed = false;
    const ids = [...touch.pointers.keys()];
    touch.pointers.clear();
    for (const id of ids) release(id);
    touch.mode = null;
    touch.base = null;
    touch.noTap = false;
    suppressMouse();
    if (notify) actions()?.end();
  };
  const down = event => {
    if (!media.matches || event.pointerType !== 'touch') return;
    if (!event.target.closest('.chart-overlay')) return;
    if (touch.pointers.size >= 2 || touch.mode === 'scroll') return;
    suppressMouse();
    touch.pointers.set(event.pointerId, {
      x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY,
    });
    host.setPointerCapture(event.pointerId);
    if (touch.pointers.size === 1) {
      touch.mode = 'pending';
      touch.noTap = false;
      touch.changed = false;
    } else {
      touch.mode = 'pinch';
      touch.noTap = true;
    }
    rebase();
  };
  const move = event => {
    const pointer = touch.pointers.get(event.pointerId);
    if (!pointer) return;
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    suppressMouse();
    const dx = pointer.x - pointer.startX;
    const dy = pointer.y - pointer.startY;
    if (Math.hypot(dx, dy) >= TOUCH_MOVE_PX) touch.noTap = true;
    if (touch.mode === 'pending') {
      if (!touch.noTap) return;
      touch.mode = Math.abs(dx) > Math.abs(dy) ? 'pan' : 'scroll';
    }
    if (touch.mode === 'scroll') return; // pan-y: браузер скроллит и пришлёт cancel
    const base = touch.base;
    if (!base || !actions()) return;
    event.preventDefault();
    let length = base.to - base.from;
    let lo;
    if (touch.mode === 'pinch') {
      const [a, b] = touch.pointers.values();
      const distance = Math.hypot(b.x - a.x, b.y - a.y);
      if (!(base.distance > 0 && distance > 0)) return;
      length = Math.max(MIN_ZOOM_SECONDS, length * base.distance / distance);
      const ratio = Math.min(1, Math.max(0, (base.x - base.left) / base.width));
      const anchor = base.from + (base.to - base.from) * ratio;
      lo = anchor - length * (((a.x + b.x) / 2 - base.left) / base.width);
    } else if (touch.mode === 'pan') {
      lo = base.from + (base.x - pointer.x) / base.width * length;
    } else {
      return;
    }
    const win = host.__chartState.window;
    if (Math.round(lo) === win.from && Math.round(lo + length) === win.to) return;
    touch.changed = true;
    actions().preview(lo, lo + length);
  };
  const up = event => {
    const pointer = touch.pointers.get(event.pointerId);
    if (!pointer) return;
    if (Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) >= TOUCH_MOVE_PX) {
      touch.noTap = true;
    }
    const tap = touch.mode === 'pending' && !touch.noTap && touch.pointers.size === 1;
    release(event.pointerId);
    touch.pointers.delete(event.pointerId);
    if (tap) actions()?.tap(event.clientX);
    if (!touch.pointers.size) {
      finish();
    } else {
      // Оставшийся палец продолжает pan от текущего окна, но уже не станет tap.
      touch.mode = 'pan';
      touch.noTap = true;
      rebase();
    }
  };
  const cancel = event => {
    if (touch.pointers.has(event.pointerId)) finish();
  };
  const blockMouse = event => {
    if (!event.target.closest('.chart-svg') || Date.now() >= touch.ignoreMouseUntil) return;
    if (event.cancelable) event.preventDefault();
    event.stopImmediatePropagation();
  };
  const control = event => {
    const button = event.target.closest('[data-chart-touch]');
    if (!button || !media.matches) return;
    const current = actions();
    if (!current) return;
    if (button.dataset.chartTouch === 'clear') current.clear();
    else if (button.dataset.chartTouch === 'reset') current.reset();
    else {
      const win = host.__chartState.window;
      const factor = button.dataset.chartTouch === 'in' ? 0.5 : 2;
      const length = Math.max(MIN_ZOOM_SECONDS, (win.to - win.from) * factor);
      const center = (win.from + win.to) / 2;
      current.preview(center - length / 2, center + length / 2);
      actions()?.finish();
    }
  };
  const onMedia = () => {
    finish();
    const state = host.__chartState;
    if (state?.window) state.paint(state.window.from, state.window.to);
  };
  host.addEventListener('pointerdown', down);
  host.addEventListener('pointermove', move, { passive: false });
  host.addEventListener('pointerup', up);
  host.addEventListener('pointercancel', cancel);
  host.addEventListener('lostpointercapture', cancel);
  const mouseEvents = ['mousedown', 'mousemove', 'mouseleave', 'click'];
  for (const type of mouseEvents) host.addEventListener(type, blockMouse, true);
  host.addEventListener('click', control);
  media.addEventListener('change', onMedia);
  touch.cleanup = () => {
    // Удаление рисунка не должно отправлять новый запрос за уходящим окном.
    touch.changed = false;
    finish(false);
    host.removeEventListener('pointerdown', down);
    host.removeEventListener('pointermove', move);
    host.removeEventListener('pointerup', up);
    host.removeEventListener('pointercancel', cancel);
    host.removeEventListener('lostpointercapture', cancel);
    for (const type of mouseEvents) host.removeEventListener(type, blockMouse, true);
    host.removeEventListener('click', control);
    media.removeEventListener('change', onMedia);
  };
  return touch;
}

function watchSize(host, redraw) {
  if (typeof ResizeObserver === 'undefined') return null;
  const observer = new ResizeObserver(() => {
    const width = host.clientWidth;
    if (width && width !== host.__chartWidth) {
      host.__chartWidth = width;
      redraw();
    }
  });
  observer.observe(host);
  return observer;
}

function mountLabel(labels, ts) {
  if (!Array.isArray(labels) || !labels.length) return null;
  let best = null;
  let bestDelta = Infinity;
  for (const pair of labels) {
    const delta = Math.abs(Number(pair?.[0]) - ts);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = pair?.[1];
    }
  }
  return best || null;
}

function exactMountLabel(labels, ts) {
  const sampleTs = Number(ts);
  if (!Number.isInteger(sampleTs) || !Array.isArray(labels)) return null;
  return labels.find(pair => Number(pair?.[0]) === sampleTs)?.[1] || null;
}

function exactPoint(points, ts) {
  const sampleTs = Number(ts);
  if (!Number.isInteger(sampleTs)) return null;
  return points.find(point => Number(point?.[0]) === sampleTs) || null;
}

function isInsideGap(gaps, ts) {
  return gaps.some(gap => ts > gap.from && ts < gap.to);
}

function regularReading(data, points, ts, step, gaps, from, to) {
  const requested = finite(ts);
  if (requested === null || isInsideGap(gaps, requested)) return null;

  const raw = data.step === 'raw'
    ? Object.values(data.raw_values || {}).flatMap(snapshot => {
      const sampleTs = finite(snapshot?.sample_ts);
      return sampleTs === null || sampleTs < from || sampleTs > to
        ? [] : [[Math.round(sampleTs), snapshot]];
    })
    : [];
  const candidates = raw.length ? raw : [...new Set(
    SERIES_ORDER.flatMap(name => points[name].map(([pointTs]) => Number(pointTs))),
  )].filter(Number.isFinite).sort((a, b) => a - b).map(pointTs => [pointTs, null]);
  const nearest = nearestPoint(candidates, requested);
  if (!nearest) return null;

  const expectedStep = Math.max(step, medianStep(candidates));
  if (expectedStep > 0 && Math.abs(nearest[0] - requested) > expectedStep / 2) return null;
  return {
    ts: nearest[0],
    kind: data.step === 'hour' ? 'часовой агрегат' : 'проба',
    snapshot: nearest[1] || snapshotAt(data.raw_values, nearest[0]),
  };
}

function markTooltip(mark, opts) {
  const time = opts.formatDateTime || opts.formatTime || (ts => String(ts));
  const actor = mark.actor?.id ? `${mark.actor.type}: ${mark.actor.id}` : (mark.actor?.type || 'система');
  const end = mark.ts_end && mark.ts_end !== mark.ts ? ` — ${time(mark.ts_end)}` : '';
  const state = mark.result === 'incomplete'
    ? '\nНет записи о завершении'
    : mark.result === 'awaiting_rule_selection'
      ? '\nОжидается выбор правил'
      : '';
  return `${mark.title || mark.action} (${actor})\n${time(mark.ts)}${end}${state}`;
}

/**
 * Полный таймлайн: оси, ряды, точки-марки, подсказка.
 *
 * `data` — ответ `/api/timeline/{id}` (§10.3), `opts`:
 * `formatTime`, `formatDateTime`, `onMark(mark)`, `onGap(gap)`, `height`.
 */
export function renderTimeline(host, data, opts = {}) {
  if (!host || !data) return;
  // Состояние рисунка переживает перерисовку: выделенная марка — выбор
  // пользователя, а не часть разметки, а жест колеса начинается до неё и
  // обязан дожить до своей перерисовки.
  const kept = host.__chartState || {};
  // Сервер может прислать уточнённый ряд, пока пользователь всё ещё тащит
  // окно. В этот момент новый SVG должен разделять тот же жест, иначе он
  // потеряет курсор и отменит уже запущенную догрузку краёв.
  if (!kept.gesture?.dragging && !kept.gesture?.active && kept.gesture?.timer) {
    clearTimeout(kept.gesture.timer);
  }
  if (kept.observer) kept.observer.disconnect();
  // Жест живёт здесь, а не внутри рисунка: предпросмотр перерисовывает рисунок
  // по нескольку раз за жест, и состояние жеста обязано это пережить.
  const gesture = kept.gesture || {
    active: false, lo: 0, hi: 0, timer: null,
    dragging: false, suppressClick: false,
    loadTimer: null, loadLastAt: 0, loadPending: null,
  };
  const plotClipId = `chart-plot-clip-${++timelineClipSequence}`;

  /**
   * Нарисовать окно `from`–`to`.
   *
   * Окно — параметр, а не константа: приближение колесом перерисовывает уже
   * загруженный ряд на новом окне, и глазу не приходится ждать ответа
   * сервера. Сервер подтвердит окно, когда жест закончится (шаг ряда за
   * пределами загруженного он знает точнее).
   */
  const paint = (from, to) => {
  if (host.__chartState) host.__chartState.window = { from, to };
  const step = pickStep(to - from);
  const gaps = normalizeGaps(data.gaps);
  const diskGaps = normalizeGaps(data.disk_gaps || data.gaps);
  const series = data.series || {};
  const available = data.available || {};

  const cpuCount = Number(opts.cpuCount) > 0 ? Number(opts.cpuCount) : null;
  const points = {};
  const visiblePoints = {};
  const inWindow = ts => Number(ts) >= from && Number(ts) <= to;
  let total = 0;
  for (const name of SERIES_ORDER) {
    const clean = cleanPoints(series[name]);
    points[name] = name === 'load1' && cpuCount
      ? clean.map(([ts, value]) => [ts, Math.min(100, loadPercent(value, cpuCount))])
      : clean;
    visiblePoints[name] = points[name].filter(([ts]) => inWindow(ts));
    total += visiblePoints[name].length;
  }
  const allMarks = Array.isArray(data.marks) ? data.marks : [];
  const marks = allMarks.filter(mark => inWindow(mark.ts));
  const offlineConnection = (_prevTs, ts) => snapshotAt(data.raw_values, ts)?.source === 'offline';
  opts.onVisibleMarks?.(marks);
  const hasVisibleGeometry = SERIES_ORDER.some(name => {
    if (available[name] === false) return false;
    const gapList = name === 'disk_max_pct' ? diskGaps : gaps;
    return splitSegments(points[name], step, gapList, offlineConnection).some(segment =>
      segment.length > 1
      && Number(segment[0][0]) <= to
      && Number(segment[segment.length - 1][0]) >= from,
    );
  });

  host.classList.add('chart-host');
  const mobile = host.__chartState.touch.media.matches;
  host.classList.toggle('chart-mobile', mobile);
  const empty = !total && !marks.length && !hasVisibleGeometry;

  const width = Math.max(320, host.clientWidth || 900);
  const height = Number(opts.height) || 280;
  const pad = { left: 46, right: 46, top: 16, bottom: 28 };
  const plotW = Math.max(10, width - pad.left - pad.right);
  const plotH = Math.max(10, height - pad.top - pad.bottom);
  const span = to - from || 1;

  const x = ts => pad.left + ((Number(ts) - from) / span) * plotW;

  const percentMax = 100;
  let loadMax = cpuCount ? 100 : 1;
  if (!cpuCount) {
    for (const [, value] of visiblePoints.load1) {
      if (Number.isFinite(value)) loadMax = Math.max(loadMax, Number(value));
    }
    loadMax = Math.ceil(loadMax * 1.15 * 10) / 10;
  }

  const yPct = value => pad.top + (1 - Math.min(percentMax, Math.max(0, value)) / percentMax) * plotH;
  const yLoad = value => pad.top + (1 - Math.min(loadMax, Math.max(0, value)) / loadMax) * plotH;

  const parts = [
    `<defs><clipPath id="${plotClipId}"><rect x="${pad.left}" y="${pad.top}" width="${plotW}" height="${plotH}"/></clipPath></defs>`,
  ];

  // Сетка: проценты слева (0–100), загрузка справа — своя шкала. Две оси
  // подписаны явно: одна и та же высота у «0.52» и «52 %» иначе читалась бы
  // как одно и то же число.
  for (let i = 0; i <= 4; i++) {
    const value = (percentMax / 4) * i;
    const y = yPct(value);
    parts.push(`<line class="chart-grid" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${(pad.left + plotW).toFixed(1)}" y2="${y.toFixed(1)}"/>`);
    parts.push(`<text class="chart-axis" x="${pad.left - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end">${value}%</text>`);
  }
  for (let i = 0; i <= 2; i++) {
    const value = (loadMax / 2) * i;
    const y = yLoad(value);
    const label = cpuCount
      ? (value >= 100 ? '100%' : `${Math.round(value)}%`)
      : value.toFixed(1);
    parts.push(`<text class="chart-axis chart-axis-load" x="${(pad.left + plotW + 6).toFixed(1)}" y="${(y + 3).toFixed(1)}">${label}</text>`);
  }

  // Разрывы: полоса «тишины» от края до края графика. Только внутренние —
  // край окна это не разрыв, а граница данных.
  for (const gap of gaps) {
    const left = x(Math.max(gap.from, from));
    const right = x(Math.min(gap.to, to));
    if (right - left < 1) continue;
    parts.push(`<rect class="chart-gap" x="${left.toFixed(1)}" y="${pad.top}" width="${(right - left).toFixed(1)}" height="${plotH}"><title>${esc(gapLabel(gap, opts.formatTime))}</title></rect>`);
  }

  const ticks = niceTicks(from, to, 5);
  let previousDay = null;
  for (const [index, ts] of ticks.entries()) {
    const tickX = x(ts);
    parts.push(`<line class="chart-grid chart-grid-v" x1="${tickX.toFixed(1)}" y1="${pad.top}" x2="${tickX.toFixed(1)}" y2="${(pad.top + plotH).toFixed(1)}"/>`);
    const time = opts.formatTime ? opts.formatTime(ts) : String(ts);
    const day = opts.formatDate ? opts.formatDate(ts) : '';
    const label = day && (index === 0 || day !== previousDay) ? `${day} ${time}` : time;
    previousDay = day || previousDay;
    parts.push(`<text class="chart-axis" x="${tickX.toFixed(1)}" y="${(height - 8).toFixed(1)}" text-anchor="middle">${esc(label)}</text>`);
  }

  const drawn = [];
  for (const name of SERIES_ORDER) {
    if (available[name] === false) continue;
    const gapList = name === 'disk_max_pct' ? diskGaps : gaps;
    const visible = visiblePoints[name];
    const segments = splitSegments(points[name], step, gapList, offlineConnection);
    const y = name === 'load1' ? yLoad : yPct;
    const color = SERIES_COLORS[name];
    const edgeTimestamps = new Set();
    for (const segment of segments) {
      const first = segment[0];
      const last = segment[segment.length - 1];
      if (first[0] > to || last[0] < from) continue;
      if (segment.length > 1) {
        parts.push(`<path class="chart-line" clip-path="url(#${plotClipId})" d="${pointsToPath(segment, x, y)}" style="stroke:${color}"/>`);
      }
      if (inWindow(first[0])) edgeTimestamps.add(first[0]);
      if (inWindow(last[0])) edgeTimestamps.add(last[0]);
    }
    for (const [ts, value] of visible) {
      const edge = edgeTimestamps.has(ts);
      const isolated = visible.length === 1;
      if (!edge && !isolated) continue;
      parts.push(`<circle class="chart-point${edge ? ' chart-point-edge' : ''}${isolated ? ' chart-point-isolated' : ''}" cx="${x(ts).toFixed(1)}" cy="${y(value).toFixed(1)}" r="3.4" style="fill:${color}"/>`);
    }
    if (!visible.length) continue;
    const last = visible[visible.length - 1];
    drawn.push({
      name,
      last,
      value: last[1],
      mount: name === 'disk_max_pct' ? exactMountLabel(data.labels?.disk_max_pct, last[0]) : null,
      snapshot: snapshotAt(data.raw_values, last[0]),
    });
  }
  const legendItems = drawn.map(item => ({
    ...item,
    text: fmtValue(
      item.name,
      item.value,
      {
        ...opts,
        loadPercentPoints: Boolean(cpuCount),
        snapshot: item.snapshot,
      },
      item.mount,
    ),
  }));
  opts.onLegendValues?.(legendItems);

  const markBoxes = [];
  const eventRail = [];
  for (const mark of marks) {
    const ts = Number(mark.ts);
    const end = Math.max(ts, Number(mark.ts_end) || ts);
    const left = x(ts);
    const right = Math.max(x(end), left + 3);
    const color = resultColor(mark.result);
    const loadValue = interpolatedValueAt(points.load1, ts, step, gaps);
    let railRow = null;
    if (loadValue === null) {
      const occupied = new Set(eventRail
        .filter(item => Math.abs(item.left - left) < 18)
        .map(item => item.row));
      railRow = [0, 1, 2].find(row => !occupied.has(row)) ?? (eventRail.length % 3);
      eventRail.push({ left, row: railRow });
    }
    const markY = loadValue === null
      ? pad.top + 8 + railRow * 9
      : yLoad(loadValue);
    markBoxes.push({ mark, left, right, markY });
    // Этот прямоугольник ничего не рисует: он цель клика и попадания. У
    // мгновенного действия ширина три пикселя — мышью в такую не попасть,
    // поэтому цель растянута на всю высоту столбца.
    parts.push(`<rect class="chart-mark-hit" data-mark-id="${esc(mark.audit_id)}" x="${left.toFixed(1)}" y="${pad.top}" width="${(right - left).toFixed(1)}" height="${plotH}"><title>${esc(markTooltip(mark, opts))}</title></rect>`);
    parts.push(`<circle class="chart-mark-dot${railRow === null ? '' : ' chart-event-rail'}" data-mark-id="${esc(mark.audit_id)}" cx="${left.toFixed(1)}" cy="${markY.toFixed(1)}" r="3.6" style="--mark:${color}"><title>${esc(markTooltip(mark, opts))}</title></circle>`);
    if (railRow === null && right - left > 64 && mark.title) {
      const labelY = Math.min(pad.top + plotH - 4, Math.max(pad.top + 10, markY - 8));
      parts.push(`<text class="chart-mark-label" x="${(left + 3).toFixed(1)}" y="${labelY.toFixed(1)}">${esc(mark.title)}</text>`);
    }
  }

  const initialCrosshairTs = Number.isFinite(kept.pinnedCursor?.ts)
    && kept.pinnedCursor.ts >= from && kept.pinnedCursor.ts <= to
    ? kept.pinnedCursor.ts : null;
  parts.push(`<line class="chart-crosshair${initialCrosshairTs == null ? '' : ' is-on'}" x1="${initialCrosshairTs == null ? 0 : x(initialCrosshairTs).toFixed(1)}" y1="${pad.top}" x2="${initialCrosshairTs == null ? 0 : x(initialCrosshairTs).toFixed(1)}" y2="${(pad.top + plotH).toFixed(1)}"/>`);

  // Рамка участка: видна только при Ctrl/⌘-протяжке. Лежит под оверлеем
  // (тот прозрачный), поэтому не перехватывает подсказку и клики.
  parts.push('<rect class="chart-select" x="0" y="0" width="0" height="0"/>');

  parts.push(`<rect class="chart-overlay" x="${pad.left}" y="${pad.top}" width="${plotW}" height="${plotH}"/>`);

  const notes = [];
  if (data.marks_truncated) {
    notes.push('Слева показаны не все действия: в окне больше записей, чем помещается в марки.');
  }
  if (from > Number(data.requested_from || from) && Number.isFinite(Number(data.requested_from))) {
    notes.push('Начало окна у́же запрошенного: сырых проб за это время в базе уже нет.');
  }

  const legend = legendItems.map(item => `
    <span class="chart-legend-item">
      <span class="chart-legend-chip" style="background:${SERIES_COLORS[item.name]}"></span>
      ${esc(SERIES_TITLES[item.name])}:
      <b>${esc(item.text)}</b>
    </span>`).join('');

  host.innerHTML = `
    ${notes.length ? `<div class="chart-note">⚠ ${notes.map(esc).join(' ')}</div>` : ''}
    ${empty ? `<div class="empty chart-empty">
      <div>Данных за это окно нет.</div>
      <div class="chart-empty-hint">Первые точки появятся в течение часа после начала сбора.</div>
    </div>` : ''}
    ${mobile ? `<div class="chart-mobile-panel">
      <div class="chart-mobile-controls" role="group" aria-label="Управление графиком">
        <button type="button" class="secondary" data-chart-touch="out" aria-label="Отдалить график">−</button>
        <button type="button" class="secondary" data-chart-touch="in" aria-label="Приблизить график">+</button>
        <button type="button" class="secondary" data-chart-touch="reset">Сбросить</button>
        <button type="button" class="secondary" data-chart-touch="clear" aria-label="Снять выбор точки или события">Снять</button>
      </div>
      <div class="chart-mobile-values" aria-live="polite"><span class="chart-mobile-placeholder">Коснитесь графика, чтобы посмотреть значения.</span></div>
    </div>` : ''}
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" tabindex="0" aria-describedby="chart-interaction-hint" aria-label="История метрик сервера">${parts.join('')}</svg>
    <div id="chart-interaction-hint" class="chart-sr-only">Клик закрепляет карточку измерения. Escape снимает закрепление и выбор события.</div>
    <div class="chart-legend">${legend}</div>
    <div class="chart-tip" hidden></div>`;

  const svg = host.querySelector('.chart-svg');
  const overlay = host.querySelector('.chart-overlay');
  const crosshair = host.querySelector('.chart-crosshair');
  const selectRect = host.querySelector('.chart-select');
  const tip = host.querySelector('.chart-tip');

  const setCrosshair = ts => {
    if (!crosshair) return;
    const value = Number(ts);
    if (!Number.isFinite(value)) return;
    const visible = Math.min(to, Math.max(from, value));
    const crosshairX = x(visible).toFixed(1);
    crosshair.setAttribute('x1', crosshairX);
    crosshair.setAttribute('x2', crosshairX);
    crosshair.classList.add('is-on');
  };

  // Марка под курсором: сперва полоса, в которую попали, иначе — ближайшая
  // в пределах точки-события. Без этого второго шанса мгновенное действие
  // (полоса шириной 3 px) выбиралось бы только снайперским кликом.
  const markAt = clientX => {
    const box = svg.getBoundingClientRect();
    const px = ((clientX - box.left) / (box.width || 1)) * width;
    let dot = null;
    let inside = null;
    let near = null;
    for (const item of markBoxes) {
      // Точка события — цель первого сорта: она одна у каждого действия и не
      // зависит от того, сколько действие длилось. Широкая цель-полоса идёт
      // второй, иначе клик по точке короткого действия выбирал бы соседнюю
      // долгую операцию, чья полоса накрыла это место.
      const toDot = Math.abs(item.left - px);
      if (toDot <= DOT_HIT_PX && (!dot || toDot < dot.delta)) dot = { ...item, delta: toDot };
      const contains = px >= item.left - 2 && px <= item.right + 2;
      const delta = Math.abs((item.left + item.right) / 2 - px);
      if (contains && (!inside || delta < inside.delta)) inside = { ...item, delta };
      if (!contains && delta <= MARK_HIT_PX && (!near || delta < near.delta)) near = { ...item, delta };
    }
    return dot || inside || near;
  };


  const tsAt = clientX => {
    const box = svg.getBoundingClientRect();
    const px = ((clientX - box.left) / (box.width || 1)) * width;
    const ratio = (px - pad.left) / plotW;
    return from + Math.min(1, Math.max(0, ratio)) * span;
  };

  /**
   * Приближение: колесо (и щипок на тачпаде — он приходит тем же событием)
   * масштабирует вокруг курсора, Ctrl/⌘-протяжка выделяет точный участок,
   * а обычная протяжка сдвигает уже приближённое окно. Дата в строке окон
   * задаёт сутки целиком.
   *
   * Колесо сначала рисует новое окно **здесь** — из уже загруженного ряда
   * (`paint`), чтобы приближение было плавным, — и только потом отдаёт окно
   * наверх (`opts.onZoom`). Наверху его перечитывает сервер: сужение окна
   * означает **другой** ряд (на узком участке пробы сырые, на широком
   * часовые), и подменить его растянутой картинкой прежнего нельзя.
   */
  const zoomTo = (lo, hi) => {
    if (typeof opts.onZoom !== 'function') return false;
    const length = hi - lo;
    if (!(length >= MIN_ZOOM_SECONDS)) return false;
    opts.onZoom({ from: Math.round(lo), to: Math.round(hi) });
    return true;
  };

  /** Подсказка живёт в разметке, которую предпросмотр перерисовывает: берём её заново. */
  const showTip = (html, anchor) => {
    if (mobile) {
      const readout = host.querySelector('.chart-mobile-values');
      if (readout) readout.innerHTML = html;
      return;
    }
    const currentTip = host.querySelector('.chart-tip');
    if (!currentTip) return;
    currentTip.innerHTML = html;
    currentTip.hidden = false;
    currentTip.classList.remove('is-pinned');
    currentTip.classList.toggle('is-selected-event', anchor?.placement === 'selected-event');
    const hostBox = host.getBoundingClientRect();
    let clientX = Number(anchor?.clientX);
    let clientY = Number(anchor?.clientY);
    let svgBox = null;
    if (Number.isFinite(anchor?.x) && Number.isFinite(anchor?.y)) {
      svgBox = svg.getBoundingClientRect();
      clientX = svgBox.left + (anchor.x / width) * svgBox.width;
      clientY = svgBox.top + (anchor.y / height) * svgBox.height;
    }
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
    currentTip.style.maxHeight = anchor?.placement === 'selected-event' && svgBox
      ? `${Math.max(0, svgBox.height - 16)}px`
      : '';
    const tipWidth = currentTip.offsetWidth;
    const tipHeight = currentTip.offsetHeight;
    const clamp = (value, minimum, maximum) => Math.min(Math.max(value, minimum), maximum);
    let left = clamp(clientX - hostBox.left + 12, 0, Math.max(0, hostBox.width - tipWidth));
    let top = clamp(clientY - hostBox.top - tipHeight - 10, 0, Math.max(0, hostBox.height - tipHeight));
    if (anchor?.placement === 'selected-event' && svgBox) {
      const minLeft = Math.max(0, svgBox.left - hostBox.left + 8);
      const maxLeft = Math.max(minLeft, Math.min(
        hostBox.width - tipWidth,
        svgBox.right - hostBox.left - tipWidth - 8,
      ));
      const minTop = Math.max(0, svgBox.top - hostBox.top + 8);
      const maxTop = Math.max(minTop, Math.min(
        hostBox.height - tipHeight,
        svgBox.bottom - hostBox.top - tipHeight - 8,
      ));
      const pointX = clientX - hostBox.left;
      const pointY = clientY - hostBox.top;
      const centeredLeft = clamp(pointX - tipWidth / 2, minLeft, maxLeft);
      const centeredTop = clamp(pointY - tipHeight / 2, minTop, maxTop);
      const right = { left: pointX + SELECTED_EVENT_TIP_OFFSET, top: centeredTop };
      const leftSide = { left: pointX - SELECTED_EVENT_TIP_OFFSET - tipWidth, top: centeredTop };
      const below = { left: centeredLeft, top: pointY + SELECTED_EVENT_TIP_OFFSET };
      const above = { left: centeredLeft, top: pointY - SELECTED_EVENT_TIP_OFFSET - tipHeight };
      const horizontal = pointX < (minLeft + maxLeft + tipWidth) / 2
        ? [right, leftSide]
        : [leftSide, right];
      const vertical = pointY < (minTop + maxTop + tipHeight) / 2
        ? [below, above]
        : [above, below];
      const distanceToTip = (candidateLeft, candidateTop) => Math.hypot(
        Math.max(candidateLeft - pointX, 0, pointX - candidateLeft - tipWidth),
        Math.max(candidateTop - pointY, 0, pointY - candidateTop - tipHeight),
      );
      const candidates = [horizontal[0], vertical[0], horizontal[1], vertical[1]].map(candidate => {
        const candidateLeft = clamp(candidate.left, minLeft, maxLeft);
        const candidateTop = clamp(candidate.top, minTop, maxTop);
        return {
          left: candidateLeft,
          top: candidateTop,
          distance: distanceToTip(candidateLeft, candidateTop),
        };
      });
      const selected = candidates.find(candidate => candidate.distance >= SELECTED_EVENT_TIP_OFFSET)
        || candidates.reduce((farthest, candidate) => candidate.distance > farthest.distance ? candidate : farthest);
      left = selected.left;
      top = selected.top;
    }
    currentTip.style.left = `${left}px`;
    currentTip.style.top = `${top}px`;
  };

  const renderMetricTip = (ts, anchor) => {
    const rows = [];
    const time = opts.formatDateTime || opts.formatTime || (value => String(value));
    const reading = regularReading(data, visiblePoints, ts, step, gaps, from, to);
    const readingTs = reading?.ts ?? ts;
    rows.push(`<div class="chart-tip-time">${esc(time(Math.round(readingTs)))}</div>`);
    const source = {
      operation_peak: 'Пик операции',
      operation: 'Замер операции',
      discovery: 'Первичная проверка',
      online: 'Возврат онлайн',
      offline: 'Сервер недоступен',
    }[reading?.snapshot?.source] || 'Регулярный мониторинг';
    rows.push(`<div class="chart-tip-context">${source} · ${reading ? esc(reading.kind) : 'нет измерения в выбранной точке'}</div>`);
    for (const name of SERIES_ORDER) {
      const list = visiblePoints[name];
      if (!list.length) continue;
      const point = reading ? exactPoint(list, reading.ts) : null;
      const mount = name === 'disk_max_pct' && point
        ? exactMountLabel(data.labels?.disk_max_pct, point[0])
        : null;
      rows.push(`<div class="chart-tip-row"><span class="chart-legend-chip" style="background:${SERIES_COLORS[name]}"></span>${esc(SERIES_TITLES[name])}: <b>${esc(fmtValue(name, point?.[1] ?? null, { ...opts, loadPercentPoints: Boolean(cpuCount), snapshot: reading?.snapshot }, mount))}</b></div>`);
    }
    if (!reading && isInsideGap(gaps, Number(ts))) {
      rows.push('<div class="chart-tip-row">В разрыве регулярного мониторинга данных нет.</div>');
    }
    for (const item of markBoxes) {
      if (ts < Number(item.mark.ts) || ts > Math.max(Number(item.mark.ts), Number(item.mark.ts_end) || 0)) continue;
      rows.push(`<div class="chart-tip-mark"><span class="chart-legend-chip" style="background:${resultColor(item.mark.result)}"></span>${esc(item.mark.title || item.mark.action)} · ${esc(resultLabel(item.mark.result))}</div>`);
      rows.push(operationPeakTip(item.mark, opts, availabilitySnapshot(data, item.mark)));
    }
    showTip(rows.join(''), anchor);
    return readingTs;
  };

  const hideTip = () => {
    const readout = host.querySelector('.chart-mobile-values');
    if (readout) readout.innerHTML = '<span class="chart-mobile-placeholder">Коснитесь графика, чтобы посмотреть значения.</span>';
    const currentTip = host.querySelector('.chart-tip');
    if (currentTip) currentTip.hidden = true;
  };

  const showSelectedMark = id => {
    const selected = markBoxes.find(item => String(item.mark.audit_id) === String(id));
    if (!selected) return false;
    const ts = Number(selected.mark.ts);
    setCrosshair(ts);
    showTip(operationPeakTip(
      selected.mark, opts, availabilitySnapshot(data, selected.mark),
    ), {
      x: selected.left,
      y: selected.markY,
      placement: 'selected-event',
    });
    return true;
  };

  const showPinned = () => {
    const pinned = host.__chartState?.pinnedCursor;
    if (!pinned || !Number.isFinite(pinned.ts) || pinned.ts < from || pinned.ts > to) {
      if (host.__chartState) host.__chartState.pinnedCursor = null;
      return false;
    }
    setCrosshair(pinned.ts);
    renderMetricTip(pinned.ts, { x: x(pinned.ts), y: pad.top + 12 });
    host.querySelector('.chart-tip')?.classList.add('is-pinned');
    return true;
  };

  if (host.__chartState) {
    host.__chartState.showSelectedMark = showSelectedMark;
    host.__chartState.showPinned = showPinned;
    host.__chartState.hideTip = hideTip;
  }

  const restoreDisplay = () => {
    const id = host.__chartState?.selectedMarkId || '';
    markSelection(host, id);
    if (id && showSelectedMark(id)) return;
    if (showPinned()) return;
    hideTip();
    crosshair?.classList.remove('is-on');
  };
  restoreDisplay();

  /** Окно не уходит в будущее; нижнюю границу определяет доступная история. */
  const panLimits = () => {
    const now = Number(opts.now) > 0 ? Number(opts.now) : (Number(data.now) > 0 ? Number(data.now) : Math.round(Date.now() / 1000));
    return { max: now };
  };

  /**
   * Подгрузить текущее окно прямо во время жеста, а не после его окончания.
   * Первый запрос идёт сразу; следующие ограничены одним за 180 мс, чтобы
   * график успевал наполняться под курсором, но сервер не получал запрос на
   * каждый пиксель. Берём последнюю границу — промежуточное место уже не
   * интересно ни при сдвиге, ни при изменении масштаба.
   */
  const queueWindowFetch = (from, to) => {
    if (typeof opts.onWindowChange !== 'function') return;
    gesture.loadPending = { from: Math.round(from), to: Math.round(to) };
    const fire = () => {
      gesture.loadTimer = null;
      gesture.loadLastAt = Date.now();
      const pending = gesture.loadPending;
      gesture.loadPending = null;
      if (pending) opts.onWindowChange(pending);
    };
    const wait = Math.max(0, 180 - (Date.now() - gesture.loadLastAt));
    if (!wait && !gesture.loadTimer) {
      fire();
    } else if (!gesture.loadTimer) {
      gesture.loadTimer = setTimeout(fire, wait);
    }
  };

  // Перерисовка меняет замыкания геометрии и данных, но touch-контроллер один.
  host.__chartState.touchActions = {
    geometry: () => {
      const box = svg.getBoundingClientRect();
      return { left: box.left + pad.left / width * box.width, width: plotW / width * box.width };
    },
    preview: (lo, hi) => {
      const length = hi - lo;
      if (hi > panLimits().max) { hi = panLimits().max; lo = hi - length; }
      gesture.dragging = true;
      gesture.lo = Math.round(lo);
      gesture.hi = Math.round(hi);
      host.__chartState.paint(gesture.lo, gesture.hi);
      queueWindowFetch(gesture.lo, gesture.hi);
    },
    finish: () => {
      if (gesture.loadTimer) clearTimeout(gesture.loadTimer);
      gesture.loadTimer = null;
      gesture.loadPending = null;
      gesture.dragging = false;
      zoomTo(gesture.lo, gesture.hi);
    },
    tap: clientX => {
      const ts = tsAt(clientX);
      const readingTs = renderMetricTip(ts, { x: x(ts), y: pad.top + 12 });
      host.__chartState.pinnedCursor = { kind: 'metric', ts: readingTs };
      setCrosshair(readingTs);
      opts.onMark?.(null);
    },
    clear: () => {
      host.__chartState.pinnedCursor = null;
      selectMark(host, null);
      opts.onMark?.(null);
    },
    reset: () => opts.onResetZoom?.(),
    end: () => opts.onTouchEnd?.(),
  };

  /**
   * Протяжка мышью двигает окно влево-вправо: тянем **картинку**, а не окно —
   * движение вправо открывает то, что было раньше (как на карте). Сузить
   * участок можно колесом; для точного выбора есть протяжка с Ctrl — она
   * по-прежнему выделяет участок и приближает к нему. Ctrl нужен здесь
   * только на нажатой кнопке: колесо осталось без него, потому что Ctrl+колесо
   * заодно меняет масштаб всей страницы.
   */
  overlay.addEventListener('mousedown', event => {
    if (event.button !== 0) return;
    if (gesture.timer) clearTimeout(gesture.timer);   // жест колеса кончился здесь
    gesture.timer = null;
    gesture.active = false;
    const startX = event.clientX;
    const selecting = event.ctrlKey || event.metaKey;
    gesture.suppressClick = false;
    let moved = false;
    // Геометрия снимается один раз на жест: предпросмотр перерисовывает
    // разметку, и `svg` из этого кадра после первой же перерисовки —
    // отсоединённый узел с нулевым прямоугольником.
    const box = svg.getBoundingClientRect();
    const perPixel = ((width / (box.width || 1)) / plotW) * span;
    const startFrom = from;
    const startTo = to;
    const length = startTo - startFrom;
    let panLo = startFrom;
    let panHi = startTo;
    const onMove = move => {
      if (!moved && Math.abs(move.clientX - startX) < 4) return;
      moved = true;
      // Пока идёт протяжка, подсказку ведёт она, а не наведение на точку.
      gesture.dragging = true;
      const time = opts.formatTime || opts.formatDateTime || (ts => String(ts));
      if (selecting) {
        const lo = Math.min(tsAt(startX), tsAt(move.clientX));
        const hi = Math.max(tsAt(startX), tsAt(move.clientX));
        const left = x(lo);
        const right = x(hi);
        selectRect.setAttribute('x', left.toFixed(1));
        selectRect.setAttribute('y', pad.top);
        selectRect.setAttribute('width', Math.max(1, right - left).toFixed(1));
        selectRect.setAttribute('height', plotH);
        selectRect.classList.add('is-on');
        // Границы выделения показываем в той же подсказке: пользователь
        // выбирает окно, и должен видеть, какое именно.
        showTip(`<div class="chart-tip-time">${esc(time(Math.round(lo)))} — ${esc(time(Math.round(hi)))} · приблизить участок</div>`, move);
        panLo = lo;
        panHi = hi;
        return;
      }
      const shift = (startX - move.clientX) * perPixel;
      const limit = panLimits();
      panHi = startTo + shift;
      panLo = startFrom + shift;
      if (panHi > limit.max) { panHi = limit.max; panLo = panHi - length; }
      // Сдвиг виден сразу, на уже загруженном ряду; края, которых в нём нет,
      // дорисует ответ сервера после отпускания кнопки.
      gesture.lo = panLo;
      gesture.hi = panHi;
      if (host.__chartState?.paint) {
        host.__chartState.paint(Math.round(panLo), Math.round(panHi));
      }
      queueWindowFetch(panLo, panHi);
      showTip(`<div class="chart-tip-time">${esc(time(Math.round(panLo)))} — ${esc(time(Math.round(panHi)))} · сдвиг окна</div>`, move);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      gesture.dragging = false;
      selectRect.classList.remove('is-on');
      const tip = host.querySelector('.chart-tip');
      if (tip) tip.hidden = true;
      if (!moved) return;                       // это был клик — марку выбирает click
      // Клик после протяжки приходит тем же событием, что и клик по марке:
      // без этого конец сдвига выбирал бы действие под курсором.
      gesture.suppressClick = true;
      if (selecting) {
        if (Math.round(panHi) - Math.round(panLo) >= MIN_ZOOM_SECONDS) {
          zoomTo(Math.min(panLo, panHi), Math.max(panLo, panHi));
        }
        return;
      }
      // Последняя граница отправляется `zoomTo` ниже; отложенная промежуточная
      // больше не нужна и не должна перебить финальное окно поздним ответом.
      if (gesture.loadTimer) clearTimeout(gesture.loadTimer);
      gesture.loadTimer = null;
      gesture.loadPending = null;
      if (Math.round(panLo) !== startFrom || Math.round(panHi) !== startTo) {
        zoomTo(panLo, panHi);
      }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  });

  // Колесо над графиком приближает окно (без Ctrl: он меняет масштаб всей
  // страницы, и это слишком легко задеть). Прокрутка страницы отбирается
  // только над самим графиком — по краям панели она работает как обычно.
  svg.addEventListener('wheel', event => {
    event.preventDefault();                     // иначе страница уедет под курсором
    // Жест начинается с текущего окна и живёт, пока колесо не замолчит:
    // каждое событие — шаг приближения от предыдущего, а не от исходного.
    if (!gesture.active) {
      gesture.active = true;
      gesture.lo = from;
      gesture.hi = to;
    }
    const anchor = tsAt(event.clientX);
    const factor = Math.min(2, Math.max(0.5, Math.exp(event.deltaY * 0.0015)));
    const length = Math.max((gesture.hi - gesture.lo) * factor, MIN_ZOOM_SECONDS);
    const ratio = gesture.hi > gesture.lo
      ? Math.min(1, Math.max(0, (anchor - gesture.lo) / (gesture.hi - gesture.lo)))
      : 0.5;
    let lo = anchor - length * ratio;
    let hi = lo + length;
    const limit = panLimits();
    if (hi > limit.max) { hi = limit.max; lo = hi - length; }
    gesture.lo = lo;
    gesture.hi = hi;

    // Плавность. Пока колесо крутится, окно рисуется на уже загруженном
    // ряду — и сужение, и расширение видно сразу, а не через запрос. При
    // отдалении край окна на миг пуст: точек за пределами загруженного нет —
    // зато жест не «залипает» рывком на каждый щелчок, а следующий ответ
    // сервера просто дорисовывает края.
    if (host.__chartState?.paint) {
      host.__chartState.paint(Math.round(gesture.lo), Math.round(gesture.hi));
    }
    queueWindowFetch(gesture.lo, gesture.hi);

    // Последнее окно отправляем отдельно: отложенный промежуточный запрос
    // больше не нужен и не должен прийти после окончательного.
    if (gesture.timer) clearTimeout(gesture.timer);
    gesture.timer = setTimeout(() => {
      gesture.timer = null;
      gesture.active = false;
      if (gesture.loadTimer) clearTimeout(gesture.loadTimer);
      gesture.loadTimer = null;
      gesture.loadPending = null;
      zoomTo(gesture.lo, gesture.hi);
    }, 220);
  }, { passive: false });

  overlay.addEventListener('mousemove', event => {
    if (gesture.dragging) return;              // подсказку ведёт протяжка
    const ts = tsAt(event.clientX);
    setCrosshair(ts);
    renderMetricTip(ts, event);
    const mark = markAt(event.clientX);
    svg.style.cursor = mark ? 'pointer' : 'crosshair';
  });

  overlay.addEventListener('mouseleave', () => {
    restoreDisplay();
  });

  svg.addEventListener('click', event => {
    if (gesture.suppressClick) {
      gesture.suppressClick = false;
      return;
    }
    const box = markAt(event.clientX);
    if (box) {
      host.__chartState.pinnedCursor = null;
      setCrosshair(Number(box.mark.ts));
      renderMetricTip(Number(box.mark.ts), event);
      if (typeof opts.onMark === 'function') opts.onMark(box.mark);
      return;
    }
    const ts = tsAt(event.clientX);
    host.__chartState.pinnedCursor = { kind: 'metric', ts };
    setCrosshair(ts);
    renderMetricTip(ts, event);
    // Клик мимо марки (по пустому месту графика) снимает только выбор
    // действия: закреплённая карточка регулярного измерения остаётся на месте.
    if (typeof opts.onMark === 'function') opts.onMark(null);
  });

  svg.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    host.__chartState.pinnedCursor = null;
    host.__chartState.selectedMarkId = '';
    hideTip();
    crosshair?.classList.remove('is-on');
    if (typeof opts.onMark === 'function') opts.onMark(null);
  });

  markSelection(host, host.__chartState?.selectedMarkId || '');
  };

  const state = {
    observer: null,
    args: [host, data, opts],
    selectedMarkId: kept.selectedMarkId || '',
    pinnedCursor: kept.pinnedCursor || null,
    window: null,
    gesture,
    paint,
    touch: kept.touch || bindTimelineTouch(host),
  };
  host.__chartState = state;
  // Ответ может описывать окно, которое уже осталось за курсором: во время
  // активного жеста оставляем пользователю именно текущий предпросмотр, а ряд
  // из ответа лишь заполняет его доступными точками. Иначе каждый ответ раз в
  // 180 мс зримо отбрасывал бы окно назад.
  const activeWindow = (gesture.dragging || gesture.active) && gesture.hi > gesture.lo
    ? { from: gesture.lo, to: gesture.hi }
    : { from: Number(data.from), to: Number(data.to) };
  paint(activeWindow.from, activeWindow.to);
  // Перерисовка на смену размера идёт тем же рисунком на том же окне (не
  // через повторный вход снаружи): прошлый наблюдатель снят в начале
  // функции. Без этого на первом изменении ширины их стало бы два, на
  // втором — четыре, и график «размножался» бы с каждым изменением окна.
  state.observer = watchSize(host, () => paint(state.window.from, state.window.to));
  markSelection(host, state.selectedMarkId);
}

/**
 * Выделить марку (или снять выделение, если `auditId` пуст).
 *
 * Нужна списку действий под графиком: клик по строке списка подсвечивает
 * свою точку на графике, а не уводит со страницы. Выбор запоминается в
 * состоянии рисунка, поэтому переживает перерисовку (смена размера окна,
 * приход новой пробы).
 */
export function selectMark(host, auditId) {
  if (!host) return;
  const id = auditId == null ? '' : String(auditId);
  const state = host.__chartState;
  if (state) state.selectedMarkId = id;
  markSelection(host, id);
  if (id) {
    if (state) state.pinnedCursor = null;
    state?.showSelectedMark?.(id);
    return;
  }
  if (state?.pinnedCursor && state.showPinned?.()) return;
  state?.hideTip?.();
  host.querySelector('.chart-crosshair')?.classList.remove('is-on');
}

function markSelection(host, id) {
  const svg = host.querySelector('.chart-svg');
  if (!svg) return;
  // И цель клика, и точка события несут `data-mark-id`: выделение относится
  // к действию, а не к одной из двух его фигур на графике.
  svg.querySelectorAll('[data-mark-id].is-selected').forEach(el => el.classList.remove('is-selected'));
  if (!id) return;
  svg.querySelectorAll('[data-mark-id]').forEach(el => {
    if (el.getAttribute('data-mark-id') === id) el.classList.add('is-selected');
  });
}

/**
 * Спарклайн строки списка: без осей и подписей, форма важнее масштаба.
 *
 * Каждый ряд масштабируется по своему минимуму и максимуму — так делают все
 * спарклайны, и числа под графиком рядом. Разрывы рвут линию здесь так же,
 * как в большом графике: строка «сервер молчал» не должна выглядеть ровной.
 */
export function renderSpark(host, seriesList, opts = {}) {
  if (!host) return;
  const width = Math.max(80, opts.width || host.clientWidth || 120);
  const height = Math.max(20, opts.height || 32);
  const step = Number(opts.stepSeconds) > 0 ? Number(opts.stepSeconds) : pickStep(opts.span || 86400);
  const gaps = normalizeGaps(opts.gaps);

  const drawn = [];
  for (const item of seriesList) {
    const points = cleanPoints(item.points);
    if (!points.length) continue;
    let min = Infinity;
    let max = -Infinity;
    for (const [, value] of points) {
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
    drawn.push({ item, points, min, max });
  }

  if (!drawn.length) {
    host.innerHTML = '<div class="spark-empty" title="точек ещё нет"></div>';
    return;
  }

  const first = Math.min(...drawn.map(entry => entry.points[0][0]));
  const last = Math.max(...drawn.map(entry => entry.points[entry.points.length - 1][0]));
  const span = Math.max(1, last - first - 1);
  const x = ts => ((Number(ts) - first) / span) * (width - 2) + 1;

  const parts = [];
  for (const entry of drawn) {
    const range = entry.max - entry.min;
    const y = value => (range > 0 ? height - 3 - ((value - entry.min) / range) * (height - 6) : height / 2);
    const segments = splitSegments(entry.points, step, gaps);
    for (const segment of segments) {
      if (segment.length === 1) {
        parts.push(`<circle cx="${x(segment[0][0]).toFixed(1)}" cy="${y(segment[0][1]).toFixed(1)}" r="1.4" style="fill:${entry.item.color}"/>`);
        continue;
      }
      parts.push(`<path d="${pointsToPath(segment, x, y)}" fill="none" stroke-width="1.4" style="stroke:${entry.item.color}"/>`);
    }
  }

  host.innerHTML = `<svg class="spark-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" width="100%" height="${height}">${parts.join('')}</svg>`;
}

export function destroySpark(host) {
  if (host) host.innerHTML = '';
}
