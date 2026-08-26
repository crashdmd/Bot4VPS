import { j, esc } from './api.js?v=20260821-telegram-health-v1';
import { toast, showPage, confirmAction, showTelegramHealthDialog, plural, formatServerTime, serverNow, serverDateTimeParts } from './ui.js';
import { setPage } from './state.js';

const BOT_TARGET = '__bot4vps__';
const terminal = new Set(['completed', 'failed', 'cancelled']);
const stageLabels = {
  preflight: 'Подготовка', scanning_sources: 'Сканирование', creating_archive: 'Создание архива',
  streaming_source: 'Передача данных', verifying_staging: 'Проверка архива', publishing_artifact: 'Публикация',
  completed: 'Завершено', failed: 'Ошибка', cancelled: 'Отменено', queued: 'В очереди',
};

let snapshot = { catalog: [], imported_archives: [], operations: [], servers: [], server_id: null, bot4vps: null };
let selectedTarget = BOT_TARGET;
let activeTab = 'backups';
let selectedBackupId = null;
let selectedArchiveKey = null;
let importedRestoreSelection = null;
let importedRestoreSelectionRevision = 0;
let selectedImportFilename = '';
let pendingImport = null;
let renameState = null;
let importConflict = null;
let restoreMode = false;
let restoreState = null;
// Открыто вложенное подтверждение поверх Restore-диалога (отказ от защитной
// копии или применение плана). Флаг нужен document-обработчику Escape:
// подтверждение закрывает себя само, но событие продолжает всплывать, и без
// флага тот же Escape унёс бы и основную модалку вместе с заполненной формой.
let restoreConfirm = false;
let restoreWatch = null;
let previewState = null;
let profile = null;
let draftSources = [];
let profileLoading = false;
let profileSaveGeneration = 0;
let profileSaveRunning = false;
const profileSaveQueue = [];
let sourcePickerState = null;
let sourcePickerGeneration = 0;
let exclusionSourcePath = null;
let exclusionScope = null;
let profileSourceMutationPending = false;
let telegramHealth = {
  ok: false,
  code: 'NOT_CONFIGURED',
  reason: 'Telegram для сохранённых настроек ещё не проверен.',
};
let timer = null;
let loading = false;

const SOURCE_TREE_PAGE_LIMIT = 100;
const SOURCE_TREE_MAX_REQUESTS = 256;
const SOURCE_TREE_MAX_NODES = 4096;
const SOURCE_TREE_MAX_RENDERED_ROWS = 2500;
const SOURCE_TREE_MAX_DEPTH = 256;
const RESTORE_TREE_PAGE_LIMIT = 100;
const RESTORE_TREE_SEARCH_DELAY_MS = 250;
const PREVIEW_TREE_PAGE_LIMIT = 100;
const PREVIEW_MAX_RENDERED_ROWS = 5000;

const restoreTimingEnabled = typeof window !== 'undefined'
  && new URLSearchParams(window.location.search).get('backup_restore_timing') === '1';
const restoreTimingTrace = restoreTimingEnabled ? {
  schema_version: 1,
  started_at: new Date().toISOString(),
  max_concurrent_backup_requests: 0,
  dropped_events: 0,
  events: [],
} : null;
const RESTORE_TIMING_EVENT_LIMIT = 500;
const RESTORE_BACKEND_DIAGNOSTIC_FIELDS = new Set([
  'schema_version',
  'inventory_hit',
  'inventory_lookup_validation_ms',
  'tar_scan_ms',
  'archive_member_count',
  'member_validation_ms',
  'inventory_cache_write_ms',
  'import_lock_wait_ms',
  'bundle_resolution_ms',
  'readiness_ms',
  'response_member_count',
  'manifest_validation_ms',
  'restore_plan_ms',
  'full_preview_tree_ms',
  'planned_member_count',
  'planning_context_ms',
  'directory_tree_ms',
  'directory_tree_included',
  'directory_tree_nodes',
  'effective_plan_ms',
  'effective_policy_ms',
  'effective_preview_tree_ms',
  'manager_total_ms',
  'router_before_serialization_ms',
  'serialization_estimate_ms',
  'response_json_bytes_estimate',
]);
let activeBackupRequests = 0;

function timingNow() {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

function traceRestoreTiming(event, details = {}) {
  if (!restoreTimingTrace) return;
  if (restoreTimingTrace.events.length >= RESTORE_TIMING_EVENT_LIMIT) {
    restoreTimingTrace.events.shift();
    restoreTimingTrace.dropped_events += 1;
  }
  restoreTimingTrace.events.push({
    at_ms: Number(timingNow().toFixed(3)),
    event,
    ...details,
  });
}

function restoreTimingEndpoint(endpoint) {
  if (!restoreTimingEnabled) return endpoint;
  return `${endpoint}${endpoint.includes('?') ? '&' : '?'}diagnostics=true`;
}

function traceRestoreBackendDiagnostics(event, diagnostics, details, frontendTotalMs) {
  if (!restoreTimingTrace || !diagnostics || typeof diagnostics !== 'object') return;
  const safe = {};
  Object.entries(diagnostics).forEach(([key, value]) => {
    if (!RESTORE_BACKEND_DIAGNOSTIC_FIELDS.has(key)) return;
    if (typeof value === 'boolean') {
      safe[key] = value;
    } else if (typeof value === 'number' && Number.isFinite(value)) {
      safe[key] = value;
    }
  });
  const frontendMs = Number(frontendTotalMs.toFixed(3));
  const routerMs = Number(safe.router_before_serialization_ms);
  traceRestoreTiming(event, {
    ...details,
    ...safe,
    frontend_total_ms: frontendMs,
    frontend_after_router_ms: Number.isFinite(routerMs)
      ? Number(Math.max(0, frontendMs - routerMs).toFixed(3))
      : null,
  });
}

async function tracedBackupRequest(event, details, request) {
  const started = timingNow();
  activeBackupRequests += 1;
  if (restoreTimingTrace) {
    restoreTimingTrace.max_concurrent_backup_requests = Math.max(
      restoreTimingTrace.max_concurrent_backup_requests,
      activeBackupRequests,
    );
  }
  traceRestoreTiming(`${event}.start`, {
    ...details,
    active_requests: activeBackupRequests,
  });
  try {
    const value = await request();
    const durationMs = timingNow() - started;
    traceRestoreTiming(`${event}.end`, {
      ...details,
      duration_ms: Number(durationMs.toFixed(3)),
      active_requests: activeBackupRequests,
    });
    traceRestoreBackendDiagnostics(
      `${event}.backend`,
      value?.diagnostics,
      details,
      durationMs,
    );
    return value;
  } catch (error) {
    traceRestoreTiming(`${event}.error`, {
      ...details,
      duration_ms: Number((timingNow() - started).toFixed(3)),
      error_type: String(error?.name || 'Error').slice(0, 80),
      active_requests: activeBackupRequests,
    });
    throw error;
  } finally {
    activeBackupRequests -= 1;
  }
}

if (restoreTimingTrace && typeof window !== 'undefined') {
  window.backupRestoreTiming = Object.freeze({
    export: () => JSON.parse(JSON.stringify(restoreTimingTrace)),
    exportJSON: () => JSON.stringify(restoreTimingTrace, null, 2),
  });
}

let restorePlanRequestsActive = 0;

function bytes(value) {
  const n = Number(value || 0);
  if (!n) return '0 Б';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / (1024 ** i)).toFixed(i ? 1 : 0)} ${units[i]}`;
}

const ARCHIVE_SUFFIX = '.tar.gz';

/* Расширение — это последний сегмент имени, похожий на настоящий суффикс файла:
   после последней точки идут только буквы и цифры и есть хотя бы одна буква
   (`tar`, `gz`, `tgz`, `zip`, `7z`, `txt`). Вводить его нельзя, потому что
   `.tar.gz` добавляет система и получилось бы `name.tar.gz.tar.gz`.
   Точки внутри имени при этом легальны: в `test-22.08.2026_12-27` последний
   сегмент — `2026_12-27` (есть разделители), в `test-22.08.2026` — `2026`
   (одни цифры), и ни то, ни другое расширением не является. */
function looksLikeExtension(base) {
  const cut = base.lastIndexOf('.');
  if (cut < 0) return false;
  const tail = base.slice(cut + 1);
  return /^[\p{L}\p{N}]+$/u.test(tail) && /\p{L}/u.test(tail);
}

export function archiveDisplayName(value) {
  const filename = typeof value === 'object' && value !== null ? value.filename : value;
  const text = String(filename || '');
  return text.replace(/\.tar\.gz$/i, '') || 'Без имени';
}

export function archiveUiText(value) {
  return String(value ?? '').replace(/\.tar\.gz/gi, '');
}

export function archiveTechnicalFilename(value) {
  const base = String(value ?? '').trim();
  if (!base || base === '.' || base === '..' || /[\\/\x00-\x1f\x7f]/u.test(base)) {
    throw new Error('Укажите корректное имя backup без расширения.');
  }
  if (base.endsWith('.') || looksLikeExtension(base)) {
    throw new Error('Расширение задавать нельзя: укажите только имя backup.');
  }
  const filename = `${base}${ARCHIVE_SUFFIX}`;
  if (filename.length > 255) {
    throw new Error('Имя backup слишком длинное.');
  }
  return filename;
}

function backupDateTime(item) {
  if (item?._archive_kind === 'imported') {
    return item.display_created_at || item.display_imported_at || '—';
  }
  return item?.display_created_at || '—';
}

export function restoreSourcePath(sourceKind, backupId, entryKey) {
  return sourceKind === 'imported'
    ? `/api/backups/imported/${encodeURIComponent(entryKey)}/restore`
    : `/api/backups/${encodeURIComponent(backupId)}/restore`;
}

export function restorePlanPath(sourceKind, backupId, entryKey) {
  return `${restoreSourcePath(sourceKind, backupId, entryKey)}/plan`;
}

function selectedServer() {
  return snapshot.servers.find(server => String(server.id) === String(selectedTarget)) || null;
}

function targetName() {
  return selectedTarget === BOT_TARGET ? 'Bot4VPS' : (selectedServer()?.name || 'Сервер');
}

function targetCatalog() {
  return snapshot.catalog.filter(item => selectedTarget === BOT_TARGET
    ? item.type === 'bot4vps'
    : item.type === 'server' && String(item.source?.server_id) === String(selectedTarget));
}

function targetImportedArchives() {
  return (snapshot.imported_archives || []).filter(item => selectedTarget === BOT_TARGET
    ? item.destination?.scope === 'bot4vps'
    : item.destination?.scope === 'server'
      && String(item.destination?.server_id) === String(selectedTarget));
}

function targetArchives() {
  const managed = targetCatalog().map(item => ({ ...item, _archive_kind: 'managed' }));
  const imported = targetImportedArchives().map(item => ({ ...item, _archive_kind: 'imported' }));
  return [...managed, ...imported].sort((left, right) => {
    const leftDate = left._archive_kind === 'imported' ? left.imported_at : left.published_at;
    const rightDate = right._archive_kind === 'imported' ? right.imported_at : right.published_at;
    return String(rightDate || '').localeCompare(String(leftDate || ''));
  });
}

function importedNamespaceQuery(target) {
  const item = typeof target === 'string'
    ? targetImportedArchives().find(entry => entry.entry_key === target)
    : target;
  const serverId = item?.destination?.scope === 'server' ? item.destination.server_id : null;
  return serverId ? `?server_id=${encodeURIComponent(serverId)}` : '';
}

/* Namespace карточки для операций над одним артефактом. Один и тот же backup_id
   законно существует в разных namespace, поэтому verify/delete/download/preview
   обязаны адресовать (server_id, backup_id). targetCatalog() уже отфильтрован
   namespace открытой вкладки, значит это явный выбор пользователя, а не догадка
   backend. Карточка Bot4VPS server_id не имеет и параметр не посылает: там
   backup_id разрешается однозначно сам. */
function namespaceQuery(target) {
  const item = typeof target === 'string'
    ? targetCatalog().find(entry => entry.backup_id === target)
    : target;
  const serverId = item?.type === 'server' ? item.source?.server_id : null;
  return serverId ? `?server_id=${encodeURIComponent(serverId)}` : '';
}

function targetOperations() {
  return snapshot.operations.filter(operation => selectedTarget === BOT_TARGET
    ? operation.target?.kind !== 'server'
    : String(operation.target?.server_id) === String(selectedTarget));
}

function defaultProfile() {
  return {
    schema_version: 1,
    sources: [],
    automatic: { enabled: false, daily_time: '02:30', timezone: 'Europe/Kaliningrad', keep_last: 7 },
    limits: { max_source_bytes: null, max_archive_bytes: null },
    notifications: {
      backup: { enabled: false, success: false, error: true },
      restore: { enabled: true, success: false, error: true },
    },
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/* Геометрия скролл-контейнеров.
   Высоты считаются по фактически отрендеренным строкам, а не по rem-константам:
   иначе в списке остаётся «половина» строки, а вся страница получает вертикальный
   scroll из-за угаданного calc(100vh - N). */
const TARGET_VISIBLE_ROWS = 10;
const HISTORY_VISIBLE_ROWS = 5;
/* Минимум «Истории» — одна запись (журнал отсортирован свежими вперёд, так что это
   последняя операция) плюс её собственный scroll. Минимум взят предельно низким
   намеренно: по приоритету высоты каталог не должен терять строку, пока «Историю»
   ещё можно сжать. Одна запись остаётся только в самом тесном случае — прогресс и
   подсказка Restore одновременно на невысоком окне; уступка идёт по одной записи и
   ровно до устранения дефицита. */
const HISTORY_MIN_VISIBLE_ROWS = 1;
const SOURCE_VISIBLE_ROWS = 3;
const CATALOG_VISIBLE_ROWS = 3;
const STACKED_LAYOUT = '(max-width:760px)';
const MIN_LAYOUT_HEIGHT = 360;

function outerHeight(element) {
  if (!element) return 0;
  const style = getComputedStyle(element);
  return element.getBoundingClientRect().height
    + (parseFloat(style.marginTop) || 0)
    + (parseFloat(style.marginBottom) || 0);
}

// Свободная высота внутри родителя, доступная именно этому элементу.
function innerSpaceFor(element) {
  const parent = element.parentElement;
  if (!parent) return Infinity;
  const style = getComputedStyle(parent);
  let space = parent.clientHeight
    - (parseFloat(style.paddingTop) || 0)
    - (parseFloat(style.paddingBottom) || 0);
  for (const child of parent.children) {
    if (child !== element) space -= outerHeight(child);
  }
  return space;
}

/* Чистая арифметика viewport: сколько целых строк влезает в доступную высоту
   (не больше maxRows) и какая высота контейнера им нужна вместе с head. */
export function fitWholeRows(rowHeights, { head = 0, available = Infinity, maxRows = Infinity } = {}) {
  let used = 0;
  let visible = 0;
  for (const height of rowHeights) {
    if (visible >= maxRows) break;
    if (visible > 0 && head + used + height > available + 0.5) break;
    used += height;
    visible += 1;
  }
  return { visible, height: head + used };
}

function stackedLayout() {
  return typeof window.matchMedia === 'function' && window.matchMedia(STACKED_LAYOUT).matches;
}

// Высота .backup-layout = фактическое место до низа viewport, без угадывания
// высоты шапки, заголовка страницы и padding контента.
function syncLayoutHeight() {
  const layout = document.querySelector('.backup-layout');
  if (!layout) return;
  layout.style.height = '';
  if (stackedLayout() || !layout.offsetParent) return;
  const content = layout.closest('.content');
  const bottom = content ? (parseFloat(getComputedStyle(content).paddingBottom) || 0) : 0;
  const top = layout.getBoundingClientRect().top + window.scrollY;
  const available = Math.floor(window.innerHeight - top - bottom);
  if (available >= MIN_LAYOUT_HEIGHT) layout.style.height = `${available}px`;
}

/* Резерв последней строки. Список — последний элемент панели, а панель клиппит
   overflow, поэтому строка может занять часть нижнего padding панели: это пустое
   место, и 10-я строка остаётся целиком видимой даже когда до свободной высоты
   не хватает пары пикселей. Размеры строк и шрифтов при этом не меняются. */
function bottomReserve(element) {
  const parent = element.parentElement;
  if (!parent || parent.children[parent.children.length - 1] !== element) return 0;
  return parseFloat(getComputedStyle(parent).paddingBottom) || 0;
}

// Bot4VPS + разделитель + не более 10 полных строк серверов, без «половины» строки.
function syncTargetViewport() {
  const host = document.getElementById('backup-target-list');
  if (!host) return;
  host.style.maxHeight = '';
  if (stackedLayout() || !host.offsetParent) return;
  const rows = [...host.querySelectorAll('.backup-target:not(.backup-target-bot)')];
  if (!rows.length) return;
  const head = outerHeight(host.querySelector('.backup-target-bot'))
    + outerHeight(host.querySelector('.backup-target-separator'));
  const fit = fitWholeRows(rows.map(outerHeight), {
    head,
    available: innerSpaceFor(host) + bottomReserve(host),
    maxRows: TARGET_VISIBLE_ROWS,
  });
  /* max-height ставится всегда (в паре с flex:0 0 auto в pages.css), иначе flex
     сжал бы список ниже расчётной высоты и последняя строка снова обрезалась бы.
     Влезли все строки — ceil, чтобы полпикселя округления не дали ложную полосу
     прокрутки; часть строк за кадром — round: floor терял бы нижнюю границу
     последней видимой, ceil мог бы приоткрыть следующую. */
  host.style.maxHeight = fit.visible >= rows.length
    ? `${Math.ceil(fit.height)}px`
    : `${Math.round(fit.height)}px`;
}

// Источники в профиле: 3 видимые строки, остальные — внутренним scroll.
function syncSourceViewport() {
  const host = document.querySelector('.backup-source-list');
  if (!host) return;
  host.style.maxHeight = '';
  if (!host.offsetParent) return;
  const rows = [...host.querySelectorAll('.backup-source-row')];
  if (rows.length <= SOURCE_VISIBLE_ROWS) return;
  const fit = fitWholeRows(rows.map(outerHeight), { maxRows: SOURCE_VISIBLE_ROWS });
  host.style.maxHeight = `${Math.round(fit.height)}px`;
}

/* Приоритет высоты в рабочей области: каталог backup — основной рабочий список,
   «История» — вторичный блок. Оба замера опираются на один и тот же запрос
   каталога: заголовок секции + до CATALOG_VISIBLE_ROWS целых строк. `catalogRoom`
   отвечает на встречный вопрос — сколько места секции достаётся прямо сейчас:
   `innerSpaceFor` вычитает высоту всех соседей каталога (панель кнопок, подсказка
   Restore, будущие служебные блоки), а высота самого `.backup-tab-body` — это
   flex-остаток столбца, уже уменьшенный на полосу прогресса и на «Историю».

   Циклической зависимости нет: `.backup-tab-body` заполняет остаток столбца
   независимо от собственного содержимого, поэтому замер по родителю корректен. */
function catalogDemand() {
  const host = document.querySelector('.backup-catalog-list');
  if (!host) return null;
  const section = host.closest('.backup-catalog');
  if (!section || stackedLayout() || !host.offsetParent) return null;
  const rows = [...host.querySelectorAll('.backup-history-row')];
  if (!rows.length) return null;
  let head = 0;
  for (const child of section.children) {
    if (child !== host) head += outerHeight(child);
  }
  const rowHeights = rows.map(outerHeight);
  const wanted = fitWholeRows(rowHeights, { head, maxRows: CATALOG_VISIBLE_ROWS });
  return { host, section, rowHeights, head, wanted: wanted.height };
}

function catalogRoom(section) {
  return innerSpaceFor(section) + bottomReserve(section);
}

// Ровно maxRows целых строк; когда ограничивать нечего — ограничение снимается.
function capRows(host, rowHeights, maxRows) {
  if (maxRows >= rowHeights.length) {
    host.style.maxHeight = '';
    return;
  }
  host.style.maxHeight = `${Math.round(fitWholeRows(rowHeights, { maxRows }).height)}px`;
}

/* «История» уступает высоту первой: не более HISTORY_VISIBLE_ROWS записей, а при
   нехватке места в столбце — ровно столько, сколько нужно, чтобы каталог сохранил
   свои CATALOG_VISIBLE_ROWS строк, но не меньше HISTORY_MIN_VISIBLE_ROWS. Раньше
   приоритет был обратным, причём не по замыслу, а по CSS: секция истории стоит
   `flex:0 0 auto` и всегда забирала свою натуральную высоту, уступал же
   `flex:1 1 auto` рабочего тела вкладки — то есть каталог, из-за чего третий и
   четвёртый backup уходили в scroll при появлении прогресса или подсказки Restore.

   Уступка считается не арифметикой, а повторным замером свободного места после
   каждой снятой записи: так border/padding/margin секции истории учитываются сами
   и не дублируются в JS. Итераций максимум
   HISTORY_VISIBLE_ROWS - HISTORY_MIN_VISIBLE_ROWS. */
function syncHistoryViewport() {
  const host = document.querySelector('.backup-history-events');
  if (!host) return;
  host.style.maxHeight = '';
  if (!host.offsetParent) return;
  const rows = [...host.querySelectorAll('.backup-history-event')];
  if (!rows.length) return;
  const rowHeights = rows.map(outerHeight);
  let maxRows = Math.min(HISTORY_VISIBLE_ROWS, rowHeights.length);
  /* Обычный режим выставляется до замера дефицита: со снятым ограничением история
     раскрыта на все записи, столбец отдал бы ей всё, и дефицит вышел бы фиктивно
     большим — история сжималась бы до минимума всегда. */
  capRows(host, rowHeights, maxRows);
  const demand = catalogDemand();
  if (!demand) return;
  while (maxRows > HISTORY_MIN_VISIBLE_ROWS && demand.wanted - catalogRoom(demand.section) > 0.5) {
    maxRows -= 1;
    capRows(host, rowHeights, maxRows);
  }
}

/* Каталог измеряется последним: к этому моменту «История» уже уступила ему всё,
   что могла. Остаточный дефицит (если уступать было нечем) каталог отдаёт своему
   существующему внутреннему scroll — целыми строками, поэтому ни одна строка с
   checkbox не остаётся за границей области выбора. Так же было и до введения
   приоритета; изменилось только то, что дефицит теперь почти всегда нулевой. */
function syncCatalogViewport() {
  const host = document.querySelector('.backup-catalog-list');
  if (!host) return;
  host.style.maxHeight = '';
  const demand = catalogDemand();
  if (!demand) return;
  const fit = fitWholeRows(demand.rowHeights, {
    head: demand.head,
    available: catalogRoom(demand.section),
    maxRows: CATALOG_VISIBLE_ROWS,
  });
  // Округление — как у списка серверов: всё влезло — ceil (полпикселя не должны
  // давать ложную полосу прокрутки), часть строк за кадром — round.
  const height = fit.height - demand.head;
  host.style.maxHeight = fit.visible >= demand.rowHeights.length
    ? `${Math.ceil(height)}px`
    : `${Math.round(height)}px`;
}

/* Замеры сами обнуляют прокрутку. Чтобы измерить строки, height и max-height
   снимаются — и на первом же чтении layout (offsetParent, getBoundingClientRect)
   контейнер перестаёт переполняться, а браузер синхронно обрезает scrollTop до
   нуля. Поэтому позиция снимается до замеров и возвращается после того, как
   ограничения выставлены заново: иначе фоновое обновление раз в 2.5с выбрасывало
   пользователя в начало истории и списка управляемых серверов даже тогда, когда
   разметка не менялась и paint ничего не переписывал. */
function syncBackupGeometry() {
  const scroll = captureScroll();
  syncLayoutHeight();
  syncTargetViewport();
  syncSourceViewport();
  syncHistoryViewport();
  /* Порядок задаёт приоритет высоты: «История» первой узнаёт, сколько строк нужно
     каталогу, и уступает ему место, а каталог измеряется последним — по уже
     освободившемуся остатку столбца. Обратный порядок вернул бы прежнее поведение,
     когда каталог считался по ещё не сжатой «Истории». */
  syncCatalogViewport();
  restoreScroll(scroll);
}

let geometryPending = false;
let pendingScroll = null;
function scheduleGeometry() {
  if (geometryPending) return;
  // Флаг ставится до requestAnimationFrame: если callback выполнится
  // синхронно, порядок присваиваний не должен заблокировать замеры навсегда.
  geometryPending = true;
  requestAnimationFrame(() => {
    geometryPending = false;
    syncBackupGeometry();
    /* max-height скроллеров появляется только здесь, а до этого контейнер может
       быть непрокручиваемым и присвоенный scrollTop сбрасывается в 0 — поэтому
       позицию возвращаем ещё раз после замеров. */
    if (pendingScroll) {
      restoreScroll(pendingScroll);
      pendingScroll = null;
    }
  });
}

/* Сохранение позиции прокрутки.
   Фоновое обновление (loadBackups раз в 2.5с) перерисовывает разметку целиком, а
   присваивание innerHTML сбрасывает scrollTop: пользователя, пролиставшего список
   источников или каталог backup, выбрасывало в начало. Поэтому неизменившуюся
   разметку не переписываем вовсе, а при реальном изменении возвращаем прокрутку. */
const SCROLLERS = ['#backup-target-list', '.backup-source-list', '#backup-source-tree', '.backup-catalog-list', '.backup-history-events'];

function captureScroll() {
  const state = [];
  for (const selector of SCROLLERS) {
    const node = document.querySelector(selector);
    if (node && node.scrollTop) state.push({ selector, top: node.scrollTop });
  }
  return state;
}

function restoreScroll(state) {
  for (const { selector, top } of state) {
    const node = document.querySelector(selector);
    // Если содержимое стало короче, браузер сам обрежет значение до максимума.
    if (node && node.scrollTop !== top) node.scrollTop = top;
  }
}

/* Позиции для отложенного возврата копятся, а не перезаписываются: за один рендер
   paint вызывается для нескольких контейнеров, и второй вызов снял бы у уже
   перерисованного скроллера ноль, потеряв настоящую позицию. Побеждает первое
   значение для селектора — оно и снято до перерисовки. Чистая функция,
   экспортируется для проверки правила без DOM. */
export function mergeScrollState(previous, next) {
  const merged = previous ? previous.slice() : [];
  for (const entry of next || []) {
    if (!merged.some(item => item.selector === entry.selector)) merged.push(entry);
  }
  return merged;
}

const paintedHtml = new WeakMap();

/* Возвращает true, только если разметка действительно изменилась и была записана.
   Экспортируется, чтобы путь «скип неизменившейся разметки + возврат прокрутки»
   можно было прогнать без браузера. */
export function paint(host, html) {
  if (!host || paintedHtml.get(host) === html) return false;
  const scroll = captureScroll();
  paintedHtml.set(host, html);
  host.innerHTML = html;
  restoreScroll(scroll);
  if (scroll.length) pendingScroll = mergeScrollState(pendingScroll, scroll);
  /* Замер планируется на любой изменившейся разметке, а не только там, где вызов
     дописан руками. Вертикальную раскладку меняет каждый динамический блок —
     полоса прогресса, подсказка Restore, имя выбранного файла, лишняя запись
     «Истории», — и все они появляются через paint. Раньше scheduleGeometry стоял
     в отдельных render-функциях, поэтому часть путей (renderOperations и прямые
     вызовы renderBackupTab) меняла высоту молча, а каталог оставался с прежней и
     ронял последнюю строку за границу области до следующего опроса. rAF-дебаунс
     сводит несколько paint одного кадра к одному замеру, поэтому это не дороже.
     max-height скроллеров появляется только в замере, поэтому прокрутку он
     возвращает ещё раз — уже после того, как ограничения выставлены. */
  scheduleGeometry();
  return true;
}

// Замер фактической геометрии для проверки в консоли браузера.
function geometryReport() {
  const box = element => {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      top: Number(rect.top.toFixed(2)),
      bottom: Number(rect.bottom.toFixed(2)),
      height: Number(rect.height.toFixed(2)),
      padding: `${style.paddingTop} ${style.paddingBottom}`,
      border: `${style.borderTopWidth} ${style.borderBottomWidth}`,
      lineHeight: style.lineHeight,
      fontSize: style.fontSize,
      display: style.display,
      alignSelf: style.alignSelf,
    };
  };
  const scroller = element => element && {
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    scrolls: element.scrollHeight > element.clientHeight,
  };
  const list = document.getElementById('backup-target-list');
  const sources = document.querySelector('.backup-source-list');
  const events = document.querySelector('.backup-history-events');
  const catalog = document.querySelector('.backup-catalog-list');
  const create = document.querySelector('.backup-tab-actions > button');
  const upload = document.querySelector('.backup-tab-actions [data-import-backup]');
  const root = document.documentElement;
  return {
    page: {
      clientHeight: root.clientHeight,
      scrollHeight: root.scrollHeight,
      scrolls: root.scrollHeight > root.clientHeight,
    },
    layout: box(document.querySelector('.backup-layout')),
    targets: list && {
      ...scroller(list),
      rows: list.querySelectorAll('.backup-target:not(.backup-target-bot)').length,
      rowHeight: Number(outerHeight(list.querySelector('.backup-target:not(.backup-target-bot)')).toFixed(2)),
    },
    /* У истории отдельно виден `maxHeight`: по нему проверяется приоритет высоты —
       сколько записей журнал уступил каталогу при появлении прогресса/подсказки. */
    history: events && { ...scroller(events), rows: events.querySelectorAll('.backup-history-event').length, maxHeight: events.style.maxHeight || null },
    sources: sources && { ...scroller(sources), rows: sources.querySelectorAll('.backup-source-row').length },
    /* Каталог, тело вкладки и блок операций рядом: по ним видно, уступил ли каталог
       место появившемуся блоку (visibleRows уменьшился, scrolls=true) или снова
       переполняет вкладку — тогда tabBody.bottom окажется выше catalog.bottom. */
    catalog: catalog && {
      ...scroller(catalog),
      rows: catalog.querySelectorAll('.backup-history-row').length,
      rowHeight: Number(outerHeight(catalog.querySelector('.backup-history-row')).toFixed(2)),
      maxHeight: catalog.style.maxHeight || null,
      box: box(catalog),
    },
    tabBody: box(document.getElementById('backup-tab-body')),
    operations: box(document.getElementById('backup-operations')),
    note: box(document.querySelector('.backup-restore-note')),
    actions: { create: box(create), import: box(upload) },
  };
}

function renderTargets() {
  const host = document.getElementById('backup-target-list');
  if (!host) return;
  const botSelected = selectedTarget === BOT_TARGET ? ' selected' : '';
  const bot = `<button type="button" class="backup-target backup-target-bot${botSelected}" data-backup-target="${BOT_TARGET}">
    <span class="backup-target-mark">B4</span><span><strong>Bot4VPS</strong><small>Системный backup</small></span>
  </button><div class="backup-target-separator" role="separator"></div>`;
  const servers = snapshot.servers.map(server => {
    const selected = String(selectedTarget) === String(server.id) ? ' selected' : '';
    return `<button type="button" class="backup-target${selected}" data-backup-target="${esc(server.id)}">
      <span class="backup-target-mark">VPS</span><span><strong>${esc(server.name)}</strong><small>${server.configured ? 'Профиль настроен' : 'Backup не настроен'}</small></span>
    </button>`;
  }).join('');
  paint(host, bot + (servers || '<div class="empty">Управляемых серверов нет</div>'));
  scheduleGeometry();
}

function activeOperation() {
  return targetOperations().find(operation => !terminal.has(operation.status)) || null;
}

function operationTypeLabel(operation) {
  return ({ create: 'Backup', verify: 'Проверка backup', delete: 'Удаление backup', import: 'Импорт backup', restore: 'Restore' })[operation.type]
    || operation.type || 'Операция';
}

function operationTargetMatches(operation) {
  if (selectedTarget === BOT_TARGET) return operation.target?.kind === 'bot4vps' || operation.type === 'import';
  if (operation.target?.server_id && String(operation.target.server_id) === String(selectedTarget)) return true;
  if (operation.target?.kind === 'server' && String(operation.target.server_id) === String(selectedTarget)) return true;
  const backupId = operation.target?.backup_id || operation.result_backup_id;
  return Boolean(backupId && targetCatalog().some(item => item.backup_id === backupId));
}

function targetHistory() {
  return snapshot.operations.filter(operation => terminal.has(operation.status) && operationTargetMatches(operation))
    .sort((a, b) => String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at)));
}

function operationProgress(operation) {
  const progress = operation.progress || {};
  const numericPercent = progress.percent == null ? null : Number(progress.percent);
  const percent = Number.isFinite(numericPercent) ? Math.max(0, Math.min(100, numericPercent)) : null;
  const processed = bytes(progress.processed_bytes);
  const estimated = progress.estimated_total_bytes == null ? null : bytes(progress.estimated_total_bytes);
  const files = Number(progress.processed_files || 0);
  const archive = Number(progress.archive_bytes || 0);
  return { percent, processed, estimated, files, archive };
}

function renderHeading() {
  const host = document.getElementById('backup-target-heading');
  if (!host) return;
  const subtitle = selectedTarget === BOT_TARGET
    ? 'Резервная копия установки и конфигурации'
    : (selectedServer()?.configured ? 'Профиль резервного копирования настроен' : 'Backup не настроен');
  paint(host, `<div><h2>${esc(targetName())}</h2><p>${esc(subtitle)}</p></div>`);
}

function renderOperations() {
  const host = document.getElementById('backup-operations');
  if (!host) return;
  const operation = activeOperation();
  if (!operation) {
    paint(host, '');
    return;
  }
  const progress = operationProgress(operation);
  const hasPercent = progress.percent !== null;
  const shownPercent = hasPercent ? Math.floor(progress.percent) : null;
  const title = operation.type === 'create'
    ? (hasPercent ? `Создание backup — ${shownPercent}%` : 'Подготовка backup…')
    : `${operationTypeLabel(operation)}${hasPercent ? ` — ${shownPercent}%` : '…'}`;
  const progressBar = hasPercent
    ? `<div class="backup-progress"><i style="width:${progress.percent}%"></i></div>`
    : '';
  paint(host, `<div class="backup-live-progress" aria-live="polite">
      <div class="backup-live-top"><strong>${esc(title)}</strong></div>
      ${progressBar}
      <small>${progress.estimated !== null ? `${progress.processed} / ${progress.estimated}` : progress.processed} · ${progress.files} файлов${progress.archive ? ` · архив ${bytes(progress.archive)}` : ''}</small>
      <button type="button" class="ghost" data-cancel-op="${esc(operation.operation_id)}">Отменить</button>
    </div>`);
}

function renderBackupTab() {
  const host = document.getElementById('backup-tab-body');
  const server = selectedServer();
  const configured = selectedTarget === BOT_TARGET || Boolean(server?.configured);
  const archives = targetArchives();
  const importFilename = selectedImportFilename
    ? `<small class="backup-import-filename" title="${esc(archiveDisplayName(selectedImportFilename))}">Выбран файл: ${esc(archiveDisplayName(selectedImportFilename))}</small>`
    : '';
  /* Экран «Backup не настроен» показывается только когда показывать нечего. Если
     профиль опустошили, а опубликованные архивы остались, обычный экран сохраняется —
     иначе пропали бы просмотр, скачивание и удаление уже существующих архивов. */
  if (!configured && !archives.length) {
    paint(host, `<div class="backup-tab-actions">
      <button type="button" disabled title="Сначала настройте профиль">＋ Создать backup</button>
      <button type="button" class="secondary" data-import-backup>↑ Импортировать backup</button>
      <input id="backup-import-file" type="file" accept=".tar,.tar.gz,.tgz,application/x-tar,application/gzip" hidden>
      ${importFilename}
    </div><div class="backup-unconfigured"><h3>Backup не настроен</h3>
      <p>Сначала добавьте файлы или папки,<br>которые необходимо резервировать.</p>
      <button type="button" data-go-profile>Перейти в профиль</button></div>`);
    return;
  }
  const restoreText = restoreMode ? 'Отменить выбор' : 'Восстановить из backup';
  /* «Продолжить» живёт в той же панели действий, что и её триггер: панель вкладки
     клиппит overflow и высота колонки фиксирована, поэтому блок под списком
     архивов просто обрезался бы и кнопка была бы недоступна. Условный рендер, а
     не display:none — сброс выбора обязан убирать её из потока целиком. */
  const importedContinue = selectedArchiveKey
    && importedRestoreSelection?.entryKey === selectedArchiveKey
    ? importedRestoreSelection
    : null;
  const importedContinueLabels = {
    pending: 'Проверяем импортированный backup…',
    unavailable: 'Восстановление недоступно',
    error: 'Ошибка проверки backup',
  };
  const restoreContinue = restoreMode && (selectedBackupId || selectedArchiveKey)
    ? `<button type="button" data-restore-continue ${selectedArchiveKey && importedContinue?.status !== 'ready' ? 'disabled' : ''}>${esc(selectedArchiveKey ? (importedContinueLabels[importedContinue?.status] || 'Продолжить') : 'Продолжить')}</button>`
    : '';
  const archiveMarkup = `<section class="backup-catalog" aria-label="Доступные backup">
    <h3>Доступные backup</h3>
    <div class="backup-catalog-list">${archives.length ? archives.map(renderArchiveRow).join('') : '<div class="empty">Доступных архивов пока нет.</div>'}</div>
  </section>`;
  paint(host, `<div class="backup-tab-actions">
      ${configured
    ? '<button type="button" data-create-backup>＋ Создать backup</button>'
    : '<button type="button" disabled title="Сначала настройте профиль">＋ Создать backup</button>'}
      <button type="button" class="secondary" data-import-backup>↑ Импортировать backup</button>
      <input id="backup-import-file" type="file" accept=".tar,.tar.gz,.tgz,application/x-tar,application/gzip" hidden>
      ${importFilename}
      ${restoreContinue}
      <button type="button" class="secondary backup-restore-button" data-restore-mode>${restoreText}</button>
    </div>
    ${restoreMode ? '<div class="backup-restore-note">Выберите ровно один доступный backup и нажмите «Продолжить».</div>' : ''}
    ${archiveMarkup}`);
}

function renderArchiveRow(item) {
  const imported = item._archive_kind === 'imported';
  const selected = imported
    ? item.entry_key === selectedArchiveKey
    : item.backup_id === selectedBackupId;
  const selectedClass = selected ? ' selected' : '';
  const status = imported ? 'Импортированный' : 'Созданный';
  const select = restoreMode
    ? `<span class="backup-choice" aria-hidden="true">${selected ? '●' : '○'}</span>`
    : '';
  const preview = `<div class="backup-row-preview" data-label="Просмотр">
      <button type="button" class="ghost" data-archive-action="preview" title="Просмотреть">Просмотр</button>
    </div>`;
  const actions = imported
    ? `<a class="btn ghost" href="/api/backups/imported/${encodeURIComponent(item.entry_key)}/download${importedNamespaceQuery(item)}" title="Скачать">↓ Скачать</a>
      <button type="button" class="ghost" data-archive-action="rename" title="Переименовать">Переименовать</button>
      <button type="button" class="ghost danger" data-archive-action="delete">Удалить</button>`
    : `<a class="btn ghost" href="/api/backups/${encodeURIComponent(item.backup_id)}/download${namespaceQuery(item)}" title="Скачать">↓ Скачать</a>
      <button type="button" class="ghost" data-archive-action="rename" title="Переименовать">Переименовать</button>
      <button type="button" class="ghost danger" data-archive-action="delete">Удалить</button>`;
  return `<article class="backup-history-row${selectedClass}" ${imported ? `data-imported-key="${esc(item.entry_key)}"` : `data-backup-id="${esc(item.backup_id)}"`}>
    ${select}<div class="backup-history-main"><strong>${esc(archiveDisplayName(item))}</strong><small>${esc(backupDateTime(item))}</small></div>
    ${preview}
    <span data-label="Размер">${bytes(imported ? item.bytes : item.archive?.bytes)}</span>
    <span class="backup-status" data-label="Статус">${status}</span>
    <div class="backup-row-actions">${actions}</div>
  </article>`;
}

function previewIsCurrent(state, generation = state?.generation) {
  return previewState === state && state.generation === generation;
}

function previewAbortRequests(state) {
  if (!state) return;
  for (const controller of state.controllers) controller.abort();
  state.controllers.clear();
  if (state.pollTimer != null) clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function previewRequest(state, endpoint, options = {}) {
  const controller = new AbortController();
  state.controllers.add(controller);
  return j(endpoint, { ...options, signal: controller.signal })
    .finally(() => state.controllers.delete(controller));
}

function previewEndpoint(state, suffix, parameters = {}) {
  const imported = state.sourceKind === 'imported';
  const base = imported
    ? `/api/backups/imported/${encodeURIComponent(state.sourceId)}${suffix}`
    : `/api/backups/${encodeURIComponent(state.sourceId)}${suffix}`;
  const params = new URLSearchParams(String(state.sourceQuery || '').replace(/^\?/u, ''));
  Object.entries(parameters).forEach(([key, value]) => {
    if (value != null && value !== '') params.set(key, String(value));
  });
  const query = params.toString();
  return `${base}${query ? `?${query}` : ''}`;
}

function previewRetryDelay(status) {
  const requested = Number(status?.retry_after_ms);
  if (!Number.isFinite(requested)) return 1000;
  return Math.max(500, Math.min(requested, 60_000));
}

function previewPage(state, parent = null) {
  return state?.pages instanceof Map ? state.pages.get(parent == null ? '' : String(parent)) : null;
}

function previewInventoryMessage(status) {
  const value = String(status?.status || '');
  if (value === 'ready') {
    const count = Number(status?.root_count);
    return Number.isFinite(count)
      ? `Индекс содержимого готов. Элементов верхнего уровня: ${count}.`
      : 'Индекс содержимого готов.';
  }
  if (value === 'missing') return 'Индекс содержимого отсутствует. Проведите инвентаризацию архива.';
  if (value === 'queued') return 'Инвентаризация архива поставлена в очередь.';
  if (value === 'indexing') return 'Выполняется инвентаризация архива…';
  if (value === 'failed') return status?.error?.message || 'Не удалось провести инвентаризацию архива.';
  if (value === 'unavailable') return status?.error?.message || 'Инвентаризация этого архива недоступна.';
  return 'Состояние индекса содержимого неизвестно.';
}

function previewInventoryTone(status) {
  const value = String(status?.status || '');
  if (value === 'ready') return 'is-ready';
  if (value === 'failed' || value === 'unavailable') return 'is-error';
  if (value === 'queued' || value === 'indexing') return 'is-busy';
  return 'is-missing';
}

function renderPreviewPage(state, parent, depth, budget) {
  const key = parent == null ? '' : String(parent);
  const page = state.pages.get(key);
  if (!page) return '';
  let markup = '';
  for (const item of page.items) {
    if (budget.remaining <= 0) {
      budget.truncated = true;
      break;
    }
    budget.remaining -= 1;
    const path = String(item?.path || '');
    const name = String(item?.name || path || '—');
    const displayName = parent == null && path.startsWith('/') ? path : name;
    const directory = item?.type === 'directory';
    const expandable = directory && item?.has_children === true;
    const expanded = expandable && state.expanded.has(path);
    const toggle = expandable
      ? `<button type="button" class="backup-preview-tree-toggle" data-preview-toggle="${esc(path)}" aria-expanded="${expanded ? 'true' : 'false'}" aria-label="${expanded ? 'Свернуть' : 'Развернуть'} ${esc(displayName)}">${expanded ? '▾' : '▸'}</button>`
      : '<span class="backup-preview-tree-toggle-spacer"></span>';
    markup += `<div class="backup-preview-tree-row${directory ? '' : ' is-file'}" style="--preview-tree-depth:${depth}">
      ${toggle}<span class="backup-preview-tree-icon" aria-hidden="true">${directory ? '📁' : '📄'}</span>
      <code class="backup-preview-tree-name" title="${esc(path)}">${esc(displayName)}</code>
    </div>`;
    if (!expanded) continue;
    const child = state.pages.get(path);
    if (!child) {
      markup += `<div class="backup-preview-tree-page-state" style="--preview-tree-depth:${depth + 1}">Загрузка…</div>`;
    } else {
      markup += `<div class="backup-preview-tree-children">${renderPreviewPage(state, path, depth + 1, budget)}</div>`;
    }
  }
  if (page.loading) {
    markup += `<div class="backup-preview-tree-page-state" style="--preview-tree-depth:${depth}">Загрузка…</div>`;
  } else if (page.error) {
    markup += `<div class="backup-preview-tree-page-state is-error" style="--preview-tree-depth:${depth}">${esc(page.error)}
      <button type="button" class="backup-preview-tree-retry" data-preview-page-retry="${esc(key)}">Повторить</button></div>`;
  } else if (page.hasMore) {
    markup += `<button type="button" class="backup-preview-tree-more" style="--preview-tree-depth:${depth}" data-preview-more="${esc(key)}">Показать ещё</button>`;
  }
  return markup;
}

function renderPreviewModal() {
  const state = previewState;
  const body = document.getElementById('backup-preview-body');
  if (!state || !body) return;
  const title = document.getElementById('backup-preview-title');
  if (title) title.textContent = state.name || 'Содержимое архива';

  let content = '';
  if (state.loadingDescriptor) {
    content = '<div class="backup-preview-loading">Загрузка состояния архива…</div>';
  } else if (state.descriptorError) {
    content = `<div class="backup-preview-lifecycle is-error">${esc(state.descriptorError)}</div>`;
  } else if (state.inventory) {
    const descriptor = state.descriptor || {};
    const meta = [
      descriptor.format ? String(descriptor.format) : null,
      Number.isFinite(Number(descriptor.bytes)) ? bytes(descriptor.bytes) : null,
      descriptor.display_created_at || null,
    ].filter(Boolean).join(' · ');
    content = `${meta ? `<div class="backup-preview-meta">${esc(meta)}</div>` : ''}
      <div class="backup-preview-lifecycle ${previewInventoryTone(state.inventory)}" role="status">${esc(previewInventoryMessage(state.inventory))}</div>`;
    if (state.jobError) {
      content += `<div class="backup-preview-lifecycle is-error" role="alert">${esc(state.jobError)}</div>`;
    }
    const root = previewPage(state);
    if (root || state.inventory.status === 'ready') {
      if (!root) {
        content += '<div class="backup-preview-tree backup-preview-loading">Загрузка верхнего уровня…</div>';
      } else if (root.loaded && root.items.length === 0 && !root.loading && !root.error) {
        content += '<div class="backup-preview-tree"><div class="empty">Архив не содержит доступных элементов.</div></div>';
      } else {
        const budget = { remaining: PREVIEW_MAX_RENDERED_ROWS, truncated: false };
        const tree = renderPreviewPage(state, null, 0, budget);
        content += `<div class="backup-preview-tree" aria-label="Содержимое архива">${tree}${budget.truncated
          ? '<div class="backup-preview-tree-limit">Достигнут предел отображения. Сверните часть каталогов, чтобы продолжить навигацию.</div>'
          : ''}</div>`;
      }
    }
  }
  body.innerHTML = content || '<div class="empty">Предварительный просмотр недоступен.</div>';
  const action = document.getElementById('backup-preview-inventory-action');
  if (action) {
    const status = state.inventory || {};
    const actions = status.actions || {};
    const actionable = actions.prepare === true || actions.retry === true || actions.rebuild === true;
    const indexing = ['queued', 'indexing'].includes(status.status);
    action.disabled = state.loadingDescriptor || state.busy || indexing || !actionable;
    action.classList.toggle('is-busy', state.busy || indexing);
  }
  const refresh = document.getElementById('backup-preview-refresh');
  if (refresh) refresh.disabled = state.loadingDescriptor || state.busy;
}

function schedulePreviewInventoryStatus(state, status) {
  if (!previewIsCurrent(state)) return;
  if (state.pollTimer != null) clearTimeout(state.pollTimer);
  const generation = state.generation;
  state.pollTimer = setTimeout(() => {
    state.pollTimer = null;
    if (previewIsCurrent(state, generation)) pollPreviewInventoryStatus(state);
  }, previewRetryDelay(status));
}

async function applyPreviewInventoryStatus(state, status, { watched = false } = {}) {
  if (!previewIsCurrent(state)) return;
  state.inventory = status;
  const value = String(status?.status || '');
  if (value === 'queued' || value === 'indexing') {
    state.jobId = status.job_id || state.jobId;
    renderPreviewModal();
    schedulePreviewInventoryStatus(state, status);
    return;
  }
  if (value === 'ready') {
    state.jobId = null;
    state.jobError = null;
    state.revision = status.revision || null;
    state.pages = new Map();
    state.expanded = new Set();
    renderPreviewModal();
    await loadPreviewPage(state, null);
    return;
  }
  state.jobId = null;
  if (watched && previewPage(state)?.loaded) {
    state.jobError = previewInventoryMessage(status);
    await loadPreviewDescriptor(state, { preserveTree: true });
    return;
  }
  renderPreviewModal();
}

async function loadPreviewDescriptor(state, { preserveTree = false } = {}) {
  if (!previewIsCurrent(state)) return;
  const generation = state.generation;
  state.loadingDescriptor = true;
  state.descriptorError = '';
  renderPreviewModal();
  try {
    const descriptor = await previewRequest(state, previewEndpoint(state, '/preview'));
    if (!previewIsCurrent(state, generation)) return;
    state.descriptor = descriptor;
    state.inventory = descriptor.inventory || { status: 'unavailable', actions: {} };
    state.loadingDescriptor = false;
    if (!preserveTree || (state.revision && state.inventory.revision
        && state.revision !== state.inventory.revision)) {
      state.pages = new Map();
      state.expanded = new Set();
    }
    state.revision = state.inventory.revision || state.revision;
    renderPreviewModal();
    if (state.inventory.status === 'ready') {
      if (!previewPage(state)) await loadPreviewPage(state, null);
    } else if (['queued', 'indexing'].includes(state.inventory.status)) {
      state.jobId = state.inventory.job_id || null;
      schedulePreviewInventoryStatus(state, state.inventory);
    }
  } catch (error) {
    if (!previewIsCurrent(state, generation) || error?.name === 'AbortError') return;
    state.loadingDescriptor = false;
    state.descriptorError = archiveUiText(error.message);
    renderPreviewModal();
  }
}

async function pollPreviewInventoryStatus(state) {
  if (!previewIsCurrent(state)) return;
  const generation = state.generation;
  try {
    const status = await previewRequest(state, previewEndpoint(state, '/restore/inventory/status', {
      view: 'archive',
      job_id: state.jobId,
    }));
    if (!previewIsCurrent(state, generation)) return;
    await applyPreviewInventoryStatus(state, status, { watched: Boolean(state.jobId) });
  } catch (error) {
    if (!previewIsCurrent(state, generation) || error?.name === 'AbortError') return;
    state.jobError = archiveUiText(error.message);
    state.jobId = null;
    await loadPreviewDescriptor(state, { preserveTree: true });
  }
}

async function recoverPreviewInventory(state) {
  if (!previewIsCurrent(state)) return;
  previewAbortRequests(state);
  state.generation += 1;
  state.descriptor = null;
  state.inventory = null;
  state.revision = null;
  state.pages = new Map();
  state.expanded = new Set();
  state.jobId = null;
  state.jobError = null;
  state.descriptorError = '';
  await loadPreviewDescriptor(state);
}

async function loadPreviewPage(state, parent = null, { append = false } = {}) {
  if (!previewIsCurrent(state) || state.inventory?.status !== 'ready') return;
  const key = parent == null ? '' : String(parent);
  const existing = state.pages.get(key) || null;
  if (existing?.loading || (append && !existing?.hasMore)) return;
  const page = append && existing
    ? existing
    : { items: [], nextCursor: null, hasMore: false, loading: false, loaded: false, error: '' };
  page.loading = true;
  page.error = '';
  state.pages.set(key, page);
  renderPreviewModal();
  const generation = state.generation;
  try {
    const response = await previewRequest(state, previewEndpoint(state, '/restore/tree/children'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        view: 'archive',
        target_root: null,
        parent,
        cursor: append ? existing?.nextCursor || null : null,
        limit: PREVIEW_TREE_PAGE_LIMIT,
      }),
    });
    if (!previewIsCurrent(state, generation)) return;
    if (state.revision && response.revision && state.revision !== response.revision) {
      await recoverPreviewInventory(state);
      return;
    }
    const previous = append && existing ? existing.items : [];
    const paths = new Set(previous.map(item => String(item?.path || '')));
    const added = (Array.isArray(response.items) ? response.items : [])
      .filter(item => !paths.has(String(item?.path || '')));
    page.items = [...previous, ...added];
    page.nextCursor = response.next_cursor || null;
    page.hasMore = response.has_more === true;
    page.loading = false;
    page.loaded = true;
    state.revision = response.revision || state.revision;
    renderPreviewModal();
  } catch (error) {
    if (!previewIsCurrent(state, generation) || error?.name === 'AbortError') return;
    const kind = String(error?.details?.inventory_error || '');
    if (kind === 'cursor_stale' || kind === 'not_ready') {
      await recoverPreviewInventory(state);
      return;
    }
    page.loading = false;
    page.error = archiveUiText(error.message);
    renderPreviewModal();
  }
}

async function runPreviewInventoryAction() {
  const state = previewState;
  if (!state || state.busy || state.loadingDescriptor) return;
  const actions = state.inventory?.actions || {};
  let operation = null;
  if (actions.rebuild === true) operation = 'rebuild';
  else if (actions.retry === true) operation = 'retry';
  else if (actions.prepare === true) operation = 'prepare';
  if (!operation) return;
  if (operation === 'rebuild') {
    const approved = await confirmAction({
      title: 'Индекс содержимого уже существует. Провести инвентаризацию заново?',
      confirmText: 'Провести инвентаризацию',
      cancelText: 'Отмена',
      danger: false,
      confirmFirst: true,
    });
    if (!approved || previewState !== state) return;
  }

  state.busy = true;
  state.jobError = null;
  renderPreviewModal();
  const generation = state.generation;
  try {
    const status = await previewRequest(state, previewEndpoint(state, '/restore/inventory/prepare'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        view: 'archive',
        target_root: null,
        retry: operation === 'retry',
        rebuild: operation === 'rebuild',
      }),
    });
    if (!previewIsCurrent(state, generation)) return;
    state.jobId = status.job_id || null;
    await applyPreviewInventoryStatus(state, status, { watched: true });
  } catch (error) {
    if (!previewIsCurrent(state, generation) || error?.name === 'AbortError') return;
    state.jobError = archiveUiText(error.message);
    renderPreviewModal();
  } finally {
    if (previewIsCurrent(state, generation)) {
      state.busy = false;
      renderPreviewModal();
    }
  }
}

function openPreviewModal(sourceKind, sourceId, item) {
  closePreviewModal();
  const imported = sourceKind === 'imported';
  const state = {
    sourceKind,
    sourceId,
    sourceQuery: imported ? importedNamespaceQuery(item) : namespaceQuery(item),
    sourceIdentity: imported
      ? String(item?.checksum || `${item?.bytes || ''}:${item?.imported_at || ''}`)
      : String(item?.checksum?.value || item?.published_at || ''),
    name: archiveDisplayName(item),
    generation: 1,
    controllers: new Set(),
    pollTimer: null,
    descriptor: null,
    inventory: null,
    revision: null,
    pages: new Map(),
    expanded: new Set(),
    jobId: null,
    jobError: null,
    loadingDescriptor: false,
    descriptorError: '',
    busy: false,
  };
  previewState = state;
  document.getElementById('backup-preview-modal')?.classList.add('open');
  renderPreviewModal();
  loadPreviewDescriptor(state);
}

function refreshPreviewModal() {
  const state = previewState;
  if (!state || state.busy) return;
  previewAbortRequests(state);
  state.generation += 1;
  state.descriptor = null;
  state.inventory = null;
  state.revision = null;
  state.pages = new Map();
  state.expanded = new Set();
  state.jobId = null;
  state.jobError = null;
  state.descriptorError = '';
  renderPreviewModal();
  loadPreviewDescriptor(state);
}

function handlePreviewModalClick(event) {
  if (event.target.id === 'backup-preview-modal') {
    closePreviewModal();
    return;
  }
  const state = previewState;
  if (!state) return;

  const toggle = event.target.closest('[data-preview-toggle]');
  if (toggle) {
    const path = String(toggle.dataset.previewToggle || '');
    if (!path) return;
    if (state.expanded.has(path)) {
      state.expanded.delete(path);
      renderPreviewModal();
      return;
    }
    state.expanded.add(path);
    renderPreviewModal();
    if (!previewPage(state, path) && state.inventory?.status === 'ready') {
      loadPreviewPage(state, path);
    }
    return;
  }

  const more = event.target.closest('[data-preview-more]');
  if (more) {
    const parent = String(more.dataset.previewMore || '');
    loadPreviewPage(state, parent || null, { append: true });
    return;
  }

  const retry = event.target.closest('[data-preview-page-retry]');
  if (retry) {
    const parent = String(retry.dataset.previewPageRetry || '');
    loadPreviewPage(state, parent || null);
  }
}

function closePreviewModal() {
  const state = previewState;
  if (state) {
    previewAbortRequests(state);
    state.generation += 1;
  }
  previewState = null;
  document.getElementById('backup-preview-modal')?.classList.remove('open');
}

function renderHistoryRow(operation) {
  const progress = operationProgress(operation);
  const icon = operation.status === 'completed' ? '✓' : operation.status === 'failed' ? '⚠' : operation.status === 'cancelled' ? '⚠' : 'ℹ';
  const title = operation.status === 'completed'
    ? `${operationTypeLabel(operation)} завершён`
    : operation.status === 'failed' ? `${operationTypeLabel(operation)} завершён с ошибкой`
      : operation.status === 'cancelled' ? `${operationTypeLabel(operation)} отменён`
        : `${operationTypeLabel(operation)} запущен`;
  const detail = archiveUiText(operation.error?.message || (operation.type === 'create' && progress.archive ? `${bytes(progress.archive)}` : ''));
  return `<div class="backup-history-event"><time>${esc(formatServerTime(operation.updated_at || operation.created_at))}</time>
    <span class="backup-history-icon">${icon}</span><span class="backup-history-event-text"><strong>${esc(title)}</strong>${detail ? `<small>${esc(detail)}</small>` : ''}</span></div>`;
}

function renderHistory() {
  const host = document.getElementById('backup-history');
  if (!host) return;
  const events = targetHistory();
  paint(host, `<div class="backup-history-head"><h3 id="backup-history-title">История</h3>
    <button type="button" class="secondary" data-clear-history>Очистить</button></div>
    <div class="backup-history-events">${events.length ? events.map(renderHistoryRow).join('') : '<div class="empty">История операций пока пуста.</div>'}</div>`);
  scheduleGeometry();
}

function handleHistoryClick(event) {
  if (event.target.closest('[data-clear-history]')) clearHistory();
}

function renderProfileTab() {
  const host = document.getElementById('backup-tab-body');
  if (selectedTarget === BOT_TARGET) {
    paint(host, `<div class="backup-profile"><h3>Профиль резервного копирования</h3>
      <p class="hint">Источники Bot4VPS определены централизованно существующей политикой Backup core и недоступны для изменения.</p>
      <div class="backup-fixed-sources"><span>Текущая установка Bot4VPS</span><span>Текущий systemd unit Bot4VPS</span></div>
    </div>`);
    return;
  }
  if (profileLoading) {
    paint(host, '<div class="empty">Загрузка профиля…</div>');
    return;
  }
  const sourceControlsDisabled = profileSourceMutationPending ? 'disabled' : '';
  paint(host, `<div class="backup-profile"><h3>Профиль резервного копирования</h3>
    <div class="backup-profile-label">Источники</div>
    <div class="backup-source-list">${draftSources.length ? draftSources.map(source => `<div class="backup-source-row">
      <div><code>${esc(source.path)}</code><small>Исключений: ${source.exclusions?.length || 0}</small></div>
      <button type="button" class="secondary" data-source-exclusions="${esc(source.path)}" title="Исключения" aria-label="Настроить исключения" ${sourceControlsDisabled}>⚙</button>
      <button type="button" class="secondary" data-source-remove="${esc(source.path)}" title="Удалить источник" aria-label="Удалить источник" ${sourceControlsDisabled}>×</button>
    </div>`).join('') : '<div class="empty">Источники не выбраны</div>'}</div>
    <div class="backup-profile-actions"><button type="button" class="secondary" data-add-source ${sourceControlsDisabled}>Выбрать данные для backup</button></div>
  </div>`);
  scheduleGeometry();
}

function nullableNumber(value) {
  const text = String(value ?? '').trim();
  return text === '' ? null : Number(text);
}

function settingsValue(settings, group, key, fallback = '') {
  const value = settings?.[group]?.[key];
  return value == null ? fallback : value;
}

function megabytes(value) {
  const bytesValue = Number(value);
  return Number.isFinite(bytesValue) && bytesValue > 0 ? String(bytesValue / (1024 * 1024)) : '';
}

function megabytesToBytes(value) {
  const mb = nullableNumber(value);
  return mb == null ? null : Math.round(mb * 1024 * 1024);
}

function normalizedTelegramHealth(value) {
  if (!value || typeof value.code !== 'string') return null;
  return {
    ok: value.code === 'OK',
    code: value.code,
    reason: String(value.reason || 'Не удалось определить причину ошибки.'),
  };
}

function setTelegramHealth(value) {
  const normalized = normalizedTelegramHealth(value);
  if (normalized) telegramHealth = normalized;
}

function renderTelegramHealthIndicator() {
  const warning = document.querySelector('[data-telegram-health-warning]');
  if (!warning) return;
  const notificationsEnabled = [
    document.querySelector('[name="notify_backup_enabled"]'),
    document.querySelector('[name="notify_restore_enabled"]'),
  ].some(checkbox => checkbox?.checked);
  const health = telegramHealth;
  const healthy = health.code === 'OK';
  const visible = notificationsEnabled && !healthy;
  warning.classList.toggle('hidden', !visible);
  warning.title = visible ? health.reason : '';
  warning.setAttribute('aria-label', healthy
    ? 'Уведомления в Telegram доступны'
    : `Уведомления в Telegram недоступны. ${health.reason}`);
}

async function openTelegramHealthWarning() {
  let health = telegramHealth;
  if (health.code === 'NOT_CONFIGURED' || health.code === 'API_ERROR') {
    try {
      const result = await j('/api/telegram/health', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      health = result?.health || result;
      setTelegramHealth(health);
      renderTelegramHealthIndicator();
    } catch (error) {
      const status = error?.status ? `HTTP ${error.status}` : '';
      const detailValue = error?.detail || error?.body || error?.message;
      const detail = typeof detailValue === 'string'
        ? detailValue.trim()
        : (detailValue ? JSON.stringify(detailValue) : '');
      health = {
        ok: false,
        code: 'API_ERROR',
        reason: status && detail
          ? `${status}: ${detail}`
          : (status || detail || 'Запрос проверки Telegram завершился без диагностического ответа.'),
      };
    }
  }
  showTelegramHealthDialog({
    ok: health.code === 'OK',
    code: health.code,
    reason: health.reason,
    source: 'backup',
    onOpenSettings: () => window.dispatchEvent(new CustomEvent('bot4vps:open-settings-category', {
      detail: { category: 'telegram' },
    })),
  });
}

async function loadTelegramHealth() {
  try {
    const status = await j('/api/telegram/status');
    setTelegramHealth(status?.health);
  } catch (_) {
    setTelegramHealth({
      code: 'API_ERROR',
      reason: 'Не удалось получить состояние Telegram.',
    });
  }
  renderTelegramHealthIndicator();
}

/* Вложенная модель уведомлений: мастер-тумблер категории (backup/restore) гейтит
   обе подкатегории. Читаем с дефолтами — на случай частичного объекта. */
function notificationSettings(settings) {
  const source = settings?.notifications || {};
  const read = (cat, defEnabled) => {
    const value = source[cat] || {};
    return {
      enabled: typeof value.enabled === 'boolean' ? value.enabled : defEnabled,
      success: typeof value.success === 'boolean' ? value.success : false,
      error: typeof value.error === 'boolean' ? value.error : true,
    };
  };
  return { backup: read('backup', false), restore: read('restore', true) };
}

const NOTIFY_LABELS = {
  backup: {
    row: 'Уведомлять об операциях бэкапа',
    modal: 'Уведомления о бэкапах',
    success: 'Успешные бэкапы',
    error: 'Ошибки бэкапа',
  },
  restore: {
    row: 'Уведомлять об операциях восстановления',
    modal: 'Уведомления о восстановлении',
    success: 'Успешное восстановление',
    error: 'Ошибки восстановления',
  },
};

/* Строка блока уведомлений: слева чекбокс общего включения категории + подпись,
   справа шестерёнка. Отдельные операции (успех/ошибки) — в модалке по ⚙. */
function notificationRowMarkup(cat, values) {
  const labels = NOTIFY_LABELS[cat];
  return `<div class="backup-notification-row">
      <label class="backup-check backup-notification-row-label"><input name="notify_${cat}_enabled" id="notify_${cat}_enabled" type="checkbox" ${values.enabled ? 'checked' : ''}> <span class="backup-notification-row-text">${labels.row}</span></label>
      <button type="button" class="secondary backup-notification-gear" data-notify-gear="${cat}" title="${esc(labels.modal)}" aria-label="${esc(labels.modal)}">⚙</button>
    </div>`;
}

/* Модалка категории: только отдельные операции (успех/ошибки) тумблерами. Мастер
   включения живёт снаружи, в строке. Тумблеры на существующем autosave (input'ы в
   форме настроек), кнопки «Сохранить» нет. Мастер off → тумблеры неактивны. */
function notificationModalMarkup(cat, values) {
  const labels = NOTIFY_LABELS[cat];
  const dis = values.enabled ? '' : ' disabled';
  const toggle = (kind, checked, disabled, text) => `<div class="backup-notify-switch">
          <label class="set-switch"><input name="notify_${cat}_${kind}" id="notify_${cat}_${kind}" type="checkbox" ${checked ? 'checked' : ''}${disabled}><span class="set-switch-track"><span></span></span></label>
          <label for="notify_${cat}_${kind}" class="backup-notify-switch-text">${text}</label>
        </div>`;
  return `<div class="modal-bg backup-notification-modal" id="backup-notify-modal-${cat}" data-notify-modal="${cat}">
      <div class="modal backup-notify-modal-card" role="dialog" aria-modal="true">
        <h3 class="backup-notify-modal-title">${labels.modal}</h3>
        <div class="backup-notify-switch-list">
          ${toggle('success', values.success, dis, labels.success)}
          ${toggle('error', values.error, dis, labels.error)}
        </div>
        <div class="actions"><button type="button" class="secondary" data-notify-close>Закрыть</button></div>
      </div>
    </div>`;
}

function renderSettingsTab() {
  const host = document.getElementById('backup-tab-body');
  if (selectedTarget !== BOT_TARGET && profileLoading) {
    paint(host, '<div class="empty">Загрузка настроек…</div>');
    return;
  }
  const settings = selectedTarget === BOT_TARGET ? snapshot.bot4vps : (profile || defaultProfile());
  const health = telegramHealth;
  const automaticEnabled = Boolean(settingsValue(settings, 'automatic', 'enabled', false));
  const notify = notificationSettings(settings);
  const telegramWarningVisible = health.code !== 'OK'
    && (notify.backup.enabled || notify.restore.enabled);
  const automaticFields = () => automaticEnabled ? `<label>Время<input name="daily_time" type="time" value="${esc(settingsValue(settings, 'automatic', 'daily_time', '02:30'))}"></label>
      <label>Хранить последних backup<input name="keep_last" type="number" min="1" value="${esc(settingsValue(settings, 'automatic', 'keep_last', 7))}"></label>` : '';
  const repainted = paint(host, `<form class="backup-settings" id="backup-settings-form" onsubmit="return false">
    <div class="backup-settings-grid">
      <div class="backup-settings-limit">
        <label class="backup-settings-limit-title" for="backup-max-archive-mb">Максимальный размер архива, МБ</label>
        <div class="backup-settings-limit-row">
          <div class="backup-settings-limit-field">
            <input id="backup-max-archive-mb" name="max_archive_mb" type="number" min="1" step="1" placeholder="Без ограничений" value="${esc(megabytes(settingsValue(settings, 'limits', 'max_archive_bytes')))}">

          </div>
          <label class="backup-check"><input name="automatic_enabled" type="checkbox" ${automaticEnabled ? 'checked' : ''}> Включить автоматическое резервное копирование</label>
        </div>
      </div>
      <div id="backup-automatic-fields" class="backup-automatic-fields">${automaticFields()}</div>
      <div class="backup-telegram-notifications">
        <div class="backup-telegram-heading">
          <span>Уведомления в Телеграмм</span>
          <button type="button" class="backup-telegram-warning${telegramWarningVisible ? '' : ' hidden'}" data-telegram-health-warning title="${telegramWarningVisible ? esc(health.reason) : ''}" aria-label="Уведомления в Telegram недоступны. ${esc(health.reason)}">!</button>
        </div>
        <div class="backup-notification-groups">
          ${notificationRowMarkup('backup', notify.backup)}
          ${notificationRowMarkup('restore', notify.restore)}
        </div>
      </div>
    </div>
    ${notificationModalMarkup('backup', notify.backup)}
    ${notificationModalMarkup('restore', notify.restore)}
  </form>`);
  // Разметка не изменилась — форма и слушатели остались прежними, второй раз
  // подписываться нельзя.
  if (!repainted) return;
  bindSettingsAutosave(host);
}

function renderTabs({ keepSettingsForm = false } = {}) {
  document.querySelectorAll('[data-backup-tab]').forEach(button => {
    const on = button.dataset.backupTab === activeTab;
    button.classList.toggle('on', on);
    button.setAttribute('aria-selected', String(on));
  });
  /* Форма настроек хранит несохранённые правки только в DOM, поэтому фоновое
     обновление (loadBackups раз в 2.5с) её не перерисовывает — иначе снятый или
     поставленный checkbox сбрасывался бы до сохранения. */
  const keepForm = keepSettingsForm && activeTab === 'settings' && document.getElementById('backup-settings-form');
  if (keepForm) return;
  if (activeTab === 'profile') renderProfileTab();
  else if (activeTab === 'settings') renderSettingsTab();
  else renderBackupTab();
  scheduleGeometry();
}

function changeBackupTab(nextTab, { reloadProfile = false } = {}) {
  // Выбор архива относится только к вкладке «Резервные копии». Уход в профиль
  // или настройки начинает следующий визит с обычного списка, а не с зависшего
  // приглашения «Выберите backup».
  if (nextTab !== 'backups') cancelRestoreStart({ renderSelection: false });
  activeTab = nextTab;
  renderTabs();
  const profileNeeded = (activeTab === 'profile' || activeTab === 'settings')
    && selectedTarget !== BOT_TARGET && !profile && !profileLoading;
  if (reloadProfile || profileNeeded) loadProfile();
}

function render({ keepSettingsForm = false } = {}) {
  renderTargets();
  renderHeading();
  renderOperations();
  renderTabs({ keepSettingsForm });
  renderTelegramHealthIndicator();
  renderHistory();
}

async function loadProfile() {
  if (selectedTarget === BOT_TARGET) {
    profile = null;
    draftSources = [];
    profileLoading = false;
    renderTabs();
    return;
  }
  const requested = String(selectedTarget);
  profileLoading = true;
  renderTabs();
  try {
    const response = await j(`/api/backups/profiles/${encodeURIComponent(requested)}`);
    if (String(selectedTarget) !== requested) return;
    profile = response.profile || defaultProfile();
  } catch (_) {
    if (String(selectedTarget) !== requested) return;
    profile = defaultProfile();
  } finally {
    if (String(selectedTarget) === requested) {
      draftSources = clone(profile.sources || []);
      profileLoading = false;
      renderTabs();
    }
  }
}

export async function loadBackups({ serverId } = {}) {
  if (serverId !== undefined) {
    const requested = serverId || BOT_TARGET;
    if (String(requested) !== String(selectedTarget)) selectTarget(requested, { load: false });
  }
  const requestedTarget = String(selectedTarget);
  if (loading) {
    traceRestoreTiming('poll.skip', { restore_open: Boolean(restoreState) });
    return;
  }
  const pollStarted = timingNow();
  traceRestoreTiming('poll.start', { restore_open: Boolean(restoreState) });
  loading = true;
  try {
    const query = requestedTarget !== BOT_TARGET ? `?server_id=${encodeURIComponent(requestedTarget)}` : '';
    const [backupSnapshot] = await Promise.all([
      tracedBackupRequest(
        'poll.snapshot_request',
        { restore_open: Boolean(restoreState) },
        () => j('/api/backups' + query),
      ),
      loadTelegramHealth(),
    ]);
    // The overview intentionally filters operations by server_id. Verify/delete
    // records target only backup_id, so fetch the existing operations endpoint
    // without a server filter to keep the selected target's journal complete.
    if (requestedTarget !== BOT_TARGET) {
      const allOperations = await tracedBackupRequest(
        'poll.operations_request',
        { restore_open: Boolean(restoreState) },
        () => j('/api/backups/operations?limit=200'),
      );
      backupSnapshot.operations = allOperations.operations || [];
    }
    if (String(selectedTarget) !== requestedTarget) return;
    snapshot = backupSnapshot;
    if (previewState?.sourceKind === 'managed'
        && !targetCatalog().some(item => item.backup_id === previewState.sourceId)) {
      closePreviewModal();
    }
    if (previewState?.sourceKind === 'imported'
        && !targetImportedArchives().some(item => item.entry_key === previewState.sourceId)) {
      closePreviewModal();
    }
    if (selectedBackupId && !targetCatalog().some(item => item.backup_id === selectedBackupId)) {
      if (previewState?.sourceKind === 'managed'
          && previewState.sourceId === selectedBackupId) closePreviewModal();
      selectedBackupId = null;
    }
    if (selectedArchiveKey) {
      const current = targetImportedArchives().find(item => item.entry_key === selectedArchiveKey);
      if (current && importedRestoreSelection?.entryKey === selectedArchiveKey) {
        importedRestoreSelection.item = current;
      }
    }
    render({ keepSettingsForm: true });
    checkRestoreResult();
    stopBackupTimers();
    timer = setInterval(() => loadBackups(), 2500);
  } catch (error) {
    if (String(selectedTarget) === requestedTarget) toast(archiveUiText(error.message), false);
  } finally {
    const targetChanged = String(selectedTarget) !== requestedTarget;
    loading = false;
    traceRestoreTiming('poll.end', {
      restore_open: Boolean(restoreState),
      duration_ms: Number((timingNow() - pollStarted).toFixed(3)),
    });
    if (targetChanged) queueMicrotask(() => loadBackups());
  }
}

export function stopBackupTimers() {
  if (timer) clearInterval(timer);
  timer = null;
}

export function openBackupsForServer(serverId) {
  selectTarget(serverId, { load: false });
  setPage('backups');
  showPage('backups');
  loadBackups({ serverId });
}

function selectTarget(target, { load = true } = {}) {
  stopBackupTimers();
  closeSourcePicker({ force: true });
  closeExclusions();
  invalidateProfileSaveQueue();
  settingsNumberTimers.forEach(timeout => clearTimeout(timeout));
  settingsNumberTimers.clear();
  profileSourceMutationPending = false;
  selectedTarget = target || BOT_TARGET;
  activeTab = 'backups';
  selectedBackupId = null;
  selectedArchiveKey = null;
  importedRestoreSelection = null;
  importedRestoreSelectionRevision += 1;
  restoreMode = false;
  closePreviewModal();
  profile = null;
  draftSources = [];
  render();
  loadProfile();
  if (load) loadBackups({ serverId: selectedTarget === BOT_TARGET ? null : selectedTarget });
}

async function createBackup() {
  const target = selectedTarget === BOT_TARGET ? 'bot4vps' : 'server';
  try {
    const response = await j('/api/backups/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, server_id: target === 'server' ? selectedTarget : null, label: null }),
    });
    snapshot.operations.unshift(response.operation);
    toast('Backup поставлен в очередь', true);
    renderOperations();
    loadBackups();
  } catch (error) { toast(archiveUiText(error.message), false); }
}

async function cancelOperation(id) {
  try {
    await j(`/api/backups/operations/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
    toast('Отмена запрошена', true);
    loadBackups();
  } catch (error) { toast(archiveUiText(error.message), false); }
}

async function remove(id) {
  const approved = await confirmAction({
    title: 'Удалить backup?', message: 'Архив и checksum будут удалены.', confirmText: 'Удалить', confirmFirst: true,
  });
  if (!approved) return;
  try {
    await j(`/api/backups/${encodeURIComponent(id)}${namespaceQuery(id)}`, { method: 'DELETE' });
    if (selectedBackupId === id) selectedBackupId = null;
    if (previewState?.sourceKind === 'managed' && previewState.sourceId === id) {
      closePreviewModal();
    }
    toast('Backup удалён', true);
    loadBackups();
  } catch (error) { toast(archiveUiText(error.message), false); }
}

function preview(id) {
  const item = targetCatalog().find(entry => entry.backup_id === id);
  if (item) openPreviewModal('managed', id, item);
}

/* Restore использует один modal shell, но каждый вопрос мастера живёт на
   отдельном экране. План и дерево не читаются до явного выбора пользователя. */
const RESTORE_MODE_OPTIONS = [
  {
    value: 'merge',
    title: 'Обычное восстановление',
    detail: 'Файлы из backup записываются поверх текущих: совпадающие пути заменяются, '
      + 'отсутствующие создаются. То, чего в backup нет, остаётся на месте — ничего не удаляется.',
  },
  {
    value: 'clean',
    title: '«Чистое» восстановление',
    detail: 'Явно выбранные каталоги приводятся к точной копии из backup: всё лишнее внутри них удаляется. '
      + 'Отдельно выбранные файлы только заменяются или создаются и не расширяют область удаления. '
      + 'Например, для /var/www/html лишний old.html будет удалён, а /var/www и /var не затрагиваются.',
  },
];

function restoreProtectiveName(name) {
  // Само имя формирует backend; предпросмотр использует те же часы хоста.
  const now = serverDateTimeParts(serverNow());
  return `${String(name || 'server')}_before.restore_${now.day}.${now.month}.${now.year}`;
}

const FULL_RESTORE_UNAVAILABLE_MESSAGE = 'В этом backup присутствуют системно-критические данные, '
  + 'изменение которых при онлайн-восстановлении может нарушить работу сервера.';

function restorePathWithin(path, root) {
  return path === root || path.startsWith(`${root.replace(/\/$/u, '')}/`);
}

function restorePathOrder(left, right) {
  const leftDepth = left.split('/').filter(Boolean).length;
  const rightDepth = right.split('/').filter(Boolean).length;
  if (leftDepth !== rightDepth) return leftDepth - rightDepth;
  return left < right ? -1 : left > right ? 1 : 0;
}

function restoreSelectionContext() {
  const direct = Array.isArray(restoreState?.selectedPaths)
    ? restoreState.selectedPaths
    : [];
  const types = restoreState?.selectedPathTypes instanceof Map
    ? restoreState.selectedPathTypes
    : new Map();
  return {
    direct,
    // A path returned by backend Select All can be outside the pages opened in
    // the browser. Unknown paths are therefore treated as directories: a file
    // cannot have inventory descendants, while a directory still covers its
    // complete subtree under the existing Restore contract.
    directories: direct.filter(path => types.get(path) !== 'file'),
    types,
  };
}

function restoreNodeSelection(path, directory, context) {
  const direct = context.direct.includes(path);
  const covered = context.directories.some(root => root !== path && restorePathWithin(path, root));
  const hasDirectDescendant = directory && context.direct.some(
    item => item !== path && restorePathWithin(item, path),
  );
  return {
    direct,
    covered,
    hasDirectDescendant,
    checked: direct || covered || hasDirectDescendant,
  };
}

function updateRestorePathSelection(path, checked, type) {
  if (!restoreState || restoreState.result) return;
  const current = Array.isArray(restoreState.selectedPaths)
    ? restoreState.selectedPaths
    : [];
  const types = restoreState.selectedPathTypes instanceof Map
    ? restoreState.selectedPathTypes
    : new Map();
  restoreState.selectedPathTypes = types;
  if (!checked) {
    // Снятие обычной ancestor-галочки очищает только direct selection внутри
    // этого поддерева. Derived ancestors никогда не попадают в HTTP contract.
    restoreState.selectedPaths = current
      .filter(item => !restorePathWithin(item, path))
      .sort(restorePathOrder);
    [...types.keys()].forEach(item => {
      if (restorePathWithin(item, path)) types.delete(item);
    });
    return;
  }
  if (type === 'directory') {
    const context = restoreSelectionContext();
    if (context.directories.some(root => restorePathWithin(path, root))) return;
    const next = [
      ...current.filter(item => !restorePathWithin(item, path)),
      path,
    ].sort(restorePathOrder);
    if (next.length > 512) {
      restoreState.planError = 'Можно выбрать не более 512 отдельных элементов.';
      renderRestoreModal();
      return;
    }
    [...types.keys()].forEach(item => {
      if (restorePathWithin(item, path)) types.delete(item);
    });
    types.set(path, 'directory');
    restoreState.selectedPaths = next;
    return;
  }
  const next = [...new Set([...current, path])].sort(restorePathOrder);
  if (next.length > 512) {
    restoreState.planError = 'Можно выбрать не более 512 отдельных элементов.';
    renderRestoreModal();
    return;
  }
  types.set(path, 'file');
  restoreState.selectedPaths = next;
}

function restoreNodePolicyState(node) {
  if (node?.blocked !== true && node?.selectable === true) return 'selectable';
  if (node?.type !== 'file' && node?.has_selectable_descendants === true) return 'mixed';
  return 'blocked';
}

function restoreInventoryPage(parent = null) {
  if (!(restoreState?.inventoryPages instanceof Map)) return null;
  return restoreState.inventoryPages.get(parent == null ? '' : String(parent)) || null;
}

function restoreDirectoryNodeView(node, context, depth = 0, ancestors = new Set(), showCanonicalPath = false) {
  const path = String(node?.path || '');
  if (!path || ancestors.has(path)) return '';
  const name = showCanonicalPath ? path : String(node?.name || path);
  const type = node?.type === 'file' ? 'file' : 'directory';
  const directory = type === 'directory';
  const selection = restoreNodeSelection(path, directory, context);
  const policyState = restoreNodePolicyState(node);
  const policyBlocked = policyState !== 'selectable';
  const disabled = selection.covered || policyBlocked;
  const expanded = (restoreState?.expandedDirectories || []).includes(path);
  const canExpand = directory && node?.has_children === true;
  const disclosure = canExpand
    ? `<button type="button" class="backup-restore-tree-toggle" data-restore-tree-toggle="${esc(path)}" aria-label="${expanded ? 'Свернуть' : 'Развернуть'} ${esc(path)}" aria-expanded="${expanded ? 'true' : 'false'}">${expanded ? '▾' : '▸'}</button>`
    : '<span class="backup-restore-tree-toggle-spacer" aria-hidden="true"></span>';
  const checkbox = `<input type="checkbox" name="restore-path" value="${esc(path)}" data-restore-path-type="${type}" ${selection.checked ? 'checked' : ''} ${disabled ? 'disabled' : ''} aria-label="Выбрать ${esc(path)}">`;
  const marker = policyState === 'mixed'
    ? '<span class="backup-restore-tree-policy-marker is-mixed" role="img" aria-label="Частично доступно для онлайн-восстановления" title="Каталог содержит разрешённые и запрещённые элементы">⚠️</span>'
    : (policyState === 'blocked'
      ? '<span class="backup-restore-tree-policy-marker is-blocked" role="img" aria-label="Запрещено для онлайн-восстановления" title="Элемент запрещён для онлайн-восстановления">⛔</span>'
      : '<span class="backup-restore-tree-blocked-spacer" aria-hidden="true"></span>');
  const icon = directory ? '📁' : '📄';
  const meta = directory
    ? `${Number(node?.file_count || 0)} файлов · ${bytes(node?.bytes || 0)}`
    : bytes(node?.size || 0);
  const row = `<div class="backup-restore-tree-row backup-restore-tree-${type}" role="treeitem" style="--restore-tree-depth:${depth}"${canExpand ? ` aria-expanded="${expanded ? 'true' : 'false'}"` : ''}>
    ${disclosure}${checkbox}${marker}<span class="backup-restore-tree-icon" aria-hidden="true">${icon}</span>
    <span class="backup-restore-tree-name">${esc(name)}</span><small>${esc(meta)}</small>
  </div>`;
  if (!canExpand || !expanded) return `<div class="backup-restore-tree-node">${row}</div>`;

  const page = restoreInventoryPage(path);
  let childRows = '';
  if (page) {
    ancestors.add(path);
    childRows = (Array.isArray(page.items) ? page.items : [])
      .map(child => restoreDirectoryNodeView(child, context, depth + 1, ancestors))
      .join('');
    ancestors.delete(path);
  }
  const loading = page?.loading
    ? '<div class="backup-restore-tree-page-state" role="status">Загрузка…</div>'
    : '';
  const error = page?.error
    ? `<div class="backup-restore-tree-page-state is-error">${esc(page.error)} <button type="button" class="backup-restore-tree-retry" data-restore-tree-retry="${esc(path)}">Повторить</button></div>`
    : '';
  const more = page?.hasMore && !page.loading
    ? `<button type="button" class="backup-restore-tree-more" data-restore-tree-more="${esc(path)}">Показать ещё</button>`
    : '';
  const empty = page && !page.loading && !page.error && !childRows
    ? '<div class="backup-restore-tree-page-state">Каталог пуст.</div>'
    : '';
  const pending = !page
    ? '<div class="backup-restore-tree-page-state" role="status">Загрузка…</div>'
    : '';
  return `<div class="backup-restore-tree-node">${row}<div class="backup-restore-tree-children" role="group">${childRows}${loading}${error}${empty}${pending}${more}</div></div>`;
}

function restoreInventoryStatusMessage(status) {
  const value = String(status?.status || '');
  if (value === 'queued') {
    const position = Number(status?.position || 0);
    return position > 0
      ? `Структура поставлена в очередь (позиция ${position}).`
      : 'Структура поставлена в очередь.';
  }
  if (value === 'indexing') return 'Подготавливаем структуру backup…';
  if (value === 'failed') return archiveUiText(status?.error?.message || 'Не удалось подготовить структуру backup.');
  if (value === 'unavailable' || value === 'compatibility_only') {
    return archiveUiText(status?.error?.message || 'Для этого backup навигация по структуре недоступна.');
  }
  return 'Подготавливаем структуру backup…';
}

function restoreDirectoryTreeView() {
  const state = restoreState;
  const rootPage = restoreInventoryPage(null);
  const status = state?.inventoryStatus;
  const terminalStatus = ['failed', 'unavailable', 'compatibility_only'].includes(String(status?.status || ''));
  if (!rootPage && terminalStatus) {
    return `<div class="backup-restore-tree-loading is-error" role="status"><strong>${esc(restoreInventoryStatusMessage(status))}</strong></div>`;
  }
  if (!rootPage) {
    return `<div class="backup-restore-tree-loading" role="status">
      <strong>${esc(restoreInventoryStatusMessage(status))}</strong>
      <p>Содержимое каталогов будет загружаться только по мере их раскрытия.</p>
    </div>`;
  }

  const context = restoreSelectionContext();
  const query = String(state?.treeSearch || '').trim();
  if (query) {
    const search = state?.inventorySearch;
    if (!search || search.query !== query) {
      return '<div class="backup-restore-tree-loading" role="status"><strong>Поиск…</strong></div>';
    }
    const rows = (Array.isArray(search.items) ? search.items : [])
      .map(node => restoreDirectoryNodeView(node, context, 0, new Set(), true))
      .join('');
    const loading = search.loading
      ? '<div class="backup-restore-tree-page-state" role="status">Поиск…</div>'
      : '';
    const error = search.error
      ? `<div class="backup-restore-tree-page-state is-error">${esc(search.error)} <button type="button" class="backup-restore-tree-retry" data-restore-search-retry>Повторить</button></div>`
      : '';
    const more = search.hasMore && !search.loading
      ? '<button type="button" class="backup-restore-tree-more" data-restore-search-more>Показать ещё результаты</button>'
      : '';
    const empty = !search.loading && !search.error && !rows
      ? '<p class="hint">Элементы по этому запросу не найдены.</p>'
      : '';
    return `${rows}${loading}${error}${empty}${more}`;
  }

  const rows = (Array.isArray(rootPage.items) ? rootPage.items : [])
    .map(node => restoreDirectoryNodeView(node, context))
    .join('');
  const loading = rootPage.loading
    ? '<div class="backup-restore-tree-page-state" role="status">Загрузка…</div>'
    : '';
  const error = rootPage.error
    ? `<div class="backup-restore-tree-page-state is-error">${esc(rootPage.error)} <button type="button" class="backup-restore-tree-retry" data-restore-tree-retry="">Повторить</button></div>`
    : '';
  const more = rootPage.hasMore && !rootPage.loading
    ? '<button type="button" class="backup-restore-tree-more" data-restore-tree-more="">Показать ещё</button>'
    : '';
  return `${rows || (!rootPage.loading && !rootPage.error ? '<p class="hint">В backup нет доступных элементов.</p>' : '')}${loading}${error}${more}`;
}

function restoreStepHasBackAction(state) {
  return Boolean(
    state
    && !state.result
    && state.step !== 'scope'
    && state.step !== 'full-unavailable'
  );
}

function restoreStepNeedsActionSpacing(state) {
  return Boolean(state && !state.result && state.step !== 'protective');
}

const RESTORE_INVENTORY_ACTION_EXCLUDED_ERRORS = new Set([
  'inventory_not_indexable',
  'inventory_source_obsolete',
  'inventory_resource_limit',
]);

function restoreInventoryActionAvailable(state) {
  if (!state || state.result || state.step !== 'tree') return false;
  const status = state.inventoryStatus;
  const value = String(status?.status || '');
  if (value === 'failed') return true;
  if (value !== 'unavailable' || !status?.error || typeof status.error !== 'object') return false;
  const code = String(status.error.code || '');
  const message = String(status.error.message || '').trim();
  return Boolean(code || message) && !RESTORE_INVENTORY_ACTION_EXCLUDED_ERRORS.has(code);
}

function syncRestoreActions() {
  const submit = document.getElementById('backup-restore-submit');
  const cancel = document.getElementById('backup-restore-cancel');
  const abort = document.getElementById('backup-restore-abort');
  const inventoryAction = document.getElementById('backup-restore-inventory-action');
  if (!restoreState || !submit || !cancel || !abort) return;
  const result = restoreState.result;
  const gate = Boolean(result?.gate);
  const hasBackAction = restoreStepHasBackAction(restoreState);
  const inventoryActionAvailable = restoreInventoryActionAvailable(restoreState);
  let label = 'Продолжить';
  let cancelLabel = 'Назад';
  let disabled = Boolean(restoreState.submitting || restoreState.planLoading);
  const hidden = Boolean(result && !gate);

  if (result) {
    cancelLabel = gate ? 'Отмена' : 'Закрыть';
  } else if (restoreState.step === 'scope') {
    disabled ||= !restoreState.scopeChoice;
    cancelLabel = 'Отмена';
  } else if (restoreState.step === 'tree') {
    disabled ||= !(restoreState.selectedPaths || []).length;
  } else if (restoreState.step === 'mode') {
    disabled ||= !restoreState.mode;
  } else if (restoreState.step === 'full-unavailable') {
    label = 'Выбрать данные';
    cancelLabel = 'Отмена';
  }

  submit.textContent = label;
  submit.classList.toggle('hidden', hidden);
  submit.disabled = disabled;
  cancel.textContent = cancelLabel;
  cancel.disabled = Boolean(restoreState.submitting || restoreState.planLoading);
  abort.classList.toggle('hidden', !hasBackAction);
  abort.disabled = Boolean(restoreState.submitting);
  if (inventoryAction) {
    inventoryAction.classList.toggle('hidden', !inventoryActionAvailable);
    inventoryAction.disabled = !inventoryActionAvailable || Boolean(
      restoreState.inventoryPreparing
      || restoreState.submitting
      || restoreState.planLoading
    );
  }
}

function syncRestoreSelectionTools() {
  const clear = document.querySelector('[data-restore-clear-all]');
  if (!clear) return;
  clear.disabled = Boolean(
    !restoreState
    || restoreState.result
    || !(restoreState.selectedPaths || []).length
  );
}

function renderRestoreDirectoryTree() {
  const target = document.getElementById('backup-restore-tree');
  if (target) target.innerHTML = restoreDirectoryTreeView();
  const count = document.getElementById('backup-restore-selection-count');
  if (count) count.textContent = `Выбрано: ${(restoreState?.selectedPaths || []).length}`;
  syncRestoreSelectionTools();
  syncRestoreActions();
}

function restoreScopeView() {
  return `<p class="hint">Backup <strong>${esc(restoreState.name)}</strong> будет восстановлен в <strong>${esc(restoreState.targetName)}</strong>.</p>
    <div class="backup-restore-step-options">
      <label class="backup-restore-option">
        <input type="radio" name="restore-scope" value="full" ${restoreState.scopeChoice === 'full' ? 'checked' : ''}>
        <span><strong>Полностью</strong></span>
      </label>
      <label class="backup-restore-option">
        <input type="radio" name="restore-scope" value="selected" ${restoreState.scopeChoice === 'selected' ? 'checked' : ''}>
        <span><strong>Выборочно</strong></span>
      </label>
    </div>`;
}

function restoreTargetRootView() {
  return `<p class="hint">В импортированном архиве нет пригодного manifest. До чтения структуры укажите безопасный каталог назначения.</p>
    <label class="backup-restore-root">
      <span>Абсолютный путь на target</span>
      <input type="text" name="restore-target-root" value="${esc(restoreState.targetRoot || '')}" placeholder="/srv/imported" autocomplete="off" spellcheck="false">
      <small>Каталог назначения будет зафиксирован сервером при подготовке и не изменится перед применением.</small>
    </label>`;
}

function restoreTreeView() {
  const policy = restoreState?.inventoryPolicySummary || {};
  const policyEntries = [
    policy.has_mixed
      ? `<div class="backup-restore-tree-policy-entry is-mixed">
          <strong>⚠️ Частично доступно для онлайн-восстановления</strong>
          <p>Каталог нельзя выбрать целиком, но его можно раскрыть и выбрать разрешённые вложенные элементы.</p>
        </div>`
      : '',
    policy.has_blocked
      ? `<div class="backup-restore-tree-policy-entry is-blocked">
          <strong>⛔ Запрещено для онлайн-восстановления</strong>
          <p>Эти элементы доступны для просмотра, но их нельзя выбрать, поскольку изменение системных файлов может привести к неработоспособности сервера.</p>
        </div>`
      : '',
  ].filter(Boolean).join('');
  const policyNotice = policyEntries
    ? `<div class="backup-restore-tree-notice" role="note">${policyEntries}</div>`
    : '';
  const ready = restoreInventoryPage(null)?.loaded === true;
  const busy = !ready || Boolean(restoreState?.inventorySearch?.loading);
  return `<div class="backup-restore-selection-tools">
      <label for="backup-restore-tree-search">Поиск</label>
      <input id="backup-restore-tree-search" name="restore-tree-search" type="search" value="${esc(restoreState.treeSearch || '')}" placeholder="/etc, /home, myapp" autocomplete="off" ${ready ? '' : 'disabled'}>
      <div class="backup-restore-selection-actions">
        <button type="button" class="secondary" data-restore-select-all ${restoreState.inventorySelectAll ? '' : 'disabled'}>Выбрать всё</button>
        <button type="button" class="secondary" data-restore-clear-all ${restoreState.selectedPaths?.length ? '' : 'disabled'}>Снять все</button>
      </div>
      <small id="backup-restore-selection-count">Выбрано: ${(restoreState.selectedPaths || []).length}</small>
    </div>
    ${policyNotice}
    <div id="backup-restore-tree" class="backup-restore-tree" role="tree" aria-label="Содержимое backup" aria-busy="${busy ? 'true' : 'false'}">${restoreDirectoryTreeView()}</div>`;
}

function restoreModeView() {
  const options = RESTORE_MODE_OPTIONS.map(option => {
    const disabled = restoreState.bot && option.value === 'clean';
    const checked = restoreState.mode === option.value;
    const note = disabled
      ? '<small class="backup-restore-disabled">Для Bot4VPS недоступно: «чистое» восстановление удалило бы файлы работающей установки.</small>'
      : '';
    return `<label class="backup-restore-option${disabled ? ' disabled' : ''}">
      <input type="radio" name="restore-mode" value="${option.value}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
      <span><strong>${esc(option.title)}</strong><small>${esc(option.detail)}</small>${note}</span>
    </label>`;
  }).join('');
  const loading = restoreState.planLoading
    ? '<p class="backup-restore-step-loading" role="status">Проверяем выбранный объём восстановления…</p>'
    : '';
  return `<div class="backup-restore-step-options">${options}</div>${loading}`;
}

function restoreProtectiveView() {
  return `<label class="backup-restore-option">
      <input type="radio" name="restore-protective" value="yes" ${restoreState.protective ? 'checked' : ''}>
      <span><strong>Да</strong><small>Будет создан обычный backup с именем ${esc(restoreProtectiveName(restoreState.targetName))}. В него попадут только данные, которые затронет это восстановление. Прежняя копия с таким именем заменяется.</small></span>
    </label>
    <label class="backup-restore-option">
      <input type="radio" name="restore-protective" value="no" ${restoreState.protective ? '' : 'checked'}>
      <span><strong>Нет</strong><small>Восстановление начнётся сразу.</small></span>
    </label>`;
}

function restoreFullUnavailableView() {
  return `<div class="backup-restore-warning backup-restore-policy-warning" role="alert">
      <p>${esc(FULL_RESTORE_UNAVAILABLE_MESSAGE)}</p>
      <p>Можно выполнить выборочное восстановление разрешённых данных.</p>
    </div>`;
}

function restoreStepPresentation() {
  if (restoreState.result) {
    return { title: restoreState.result.title, html: restoreState.result.html };
  }
  const screens = {
    scope: ['Восстановление из backup', restoreScopeView],
    'target-root': ['Каталог восстановления', restoreTargetRootView],
    tree: ['Выбор данных для восстановления', restoreTreeView],
    mode: ['Режим восстановления', restoreModeView],
    protective: ['Сделать бэкап перед восстановлением?', restoreProtectiveView],
    'full-unavailable': ['Полное восстановление недоступно', restoreFullUnavailableView],
  };
  const [title, view] = screens[restoreState.step] || screens.scope;
  return { title, html: view() };
}

function renderRestoreModal() {
  const body = document.getElementById('backup-restore-body');
  const title = document.getElementById('backup-restore-title');
  const error = document.getElementById('backup-restore-error');
  const actions = document.getElementById('backup-restore-actions');
  const modal = document.querySelector('#backup-restore-modal .backup-restore-modal');
  if (!body || !restoreState) return;
  const state = restoreState;
  const renderStarted = timingNow();
  const measureTreePaint = state.step === 'tree'
    && state.pendingTreePaint
    && restoreTreeIsCurrent(state);
  const screen = restoreStepPresentation();
  if (title) title.textContent = screen.title;
  if (error) error.textContent = state.planError || '';
  body.innerHTML = screen.html;
  modal?.classList.toggle('tree-step', state.step === 'tree');
  modal?.classList.toggle('result-step', Boolean(state.result));
  actions?.classList.toggle(
    'backup-restore-actions-spaced',
    restoreStepNeedsActionSpacing(state),
  );
  syncRestoreActions();
  if (!measureTreePaint) return;
  state.pendingTreePaint = false;
  const domDuration = timingNow() - renderStarted;
  traceRestoreTiming('restore.tree_dom_insert', {
    duration_ms: Number(domDuration.toFixed(3)),
    since_tree_open_ms: state.treeOpenedAt == null
      ? null
      : Number((timingNow() - state.treeOpenedAt).toFixed(3)),
  });
  if (typeof requestAnimationFrame !== 'function') return;
  const identity = state.inventoryIdentity;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (restoreState !== state || state.inventoryIdentity !== identity) return;
    traceRestoreTiming('restore.tree_painted', {
      since_tree_open_ms: state.treeOpenedAt == null
        ? null
        : Number((timingNow() - state.treeOpenedAt).toFixed(3)),
    });
  }));
}

function importedRestoreSelectionReady(entryKey) {
  return Boolean(
    entryKey
    && importedRestoreSelection?.entryKey === entryKey
    && importedRestoreSelection.status === 'ready'
  );
}

function openRestoreModal() {
  const managed = selectedBackupId
    ? targetCatalog().find(entry => entry.backup_id === selectedBackupId)
    : null;
  const imported = selectedArchiveKey
    ? (targetImportedArchives().find(entry => entry.entry_key === selectedArchiveKey)
      || (importedRestoreSelection?.entryKey === selectedArchiveKey ? importedRestoreSelection.item : null))
    : null;
  if (!managed && !imported) {
    toast('Выберите доступный backup для восстановления', false);
    return;
  }
  if (imported && !importedRestoreSelectionReady(imported.entry_key)) {
    toast(importedRestoreSelection?.notice || 'Сначала дождитесь проверки импортированного backup', false);
    return;
  }
  const sourceKind = imported ? 'imported' : 'managed';
  const destination = imported?.destination || null;
  const bot = imported ? destination?.scope === 'bot4vps' : managed.type === 'bot4vps';
  const serverId = imported
    ? (destination?.scope === 'server' ? destination.server_id : null)
    : (bot ? null : managed.source?.server_id || null);
  restoreState = {
    step: 'scope',
    sourceKind,
    backupId: managed?.backup_id || null,
    entryKey: imported?.entry_key || null,
    sourceQuery: imported ? importedNamespaceQuery(imported) : namespaceQuery(managed),
    archiveIdentity: String(
      (imported || managed)?.checksum
      || (imported ? imported.imported_at : managed?.published_at)
      || '',
    ),
    name: archiveDisplayName(imported || managed),
    targetName: targetName(),
    serverId,
    bot,
    requiresTargetRoot: Boolean(importedRestoreSelection?.requiresTargetRoot),
    targetRoot: '',
    scopeChoice: null,
    mode: null,
    protective: true,
    selectionMode: null,
    selectedPaths: [],
    selectedPathTypes: new Map(),
    expandedDirectories: [],
    treeSearch: '',
    treeBackStep: 'scope',
    planData: null,
    planLoading: false,
    fullPolicy: null,
    planTargetRoot: null,
    inventoryIdentity: null,
    inventoryStatus: null,
    inventoryRevision: null,
    inventoryPages: new Map(),
    inventorySearch: null,
    inventorySelectAll: null,
    inventoryPolicySummary: null,
    inventoryPreparing: false,
    inventoryEpoch: 0,
    inventoryPollTimer: null,
    inventorySearchTimer: null,
    pendingTreePaint: false,
    treeOpenedAt: null,
    planError: '',
    preparedOperationId: null,
    submitting: false,
    result: null,
  };
  renderRestoreModal();
  document.getElementById('backup-restore-modal')?.classList.add('open');
}

function closeRestoreModal() {
  clearRestoreInventoryTimers(restoreState);
  document.getElementById('backup-restore-modal')?.classList.remove('open');
  restoreState = null;
}

function cancelRestoreStart({ renderSelection = true } = {}) {
  // После отправки Restore запрос уже принадлежит backend: смена вкладки или
  // Escape не должны маскировать его под локальную отмену.
  if (restoreState?.submitting) return false;
  const changed = Boolean(
    restoreState
    || restoreMode
    || selectedBackupId
    || selectedArchiveKey
    || importedRestoreSelection
  );
  if (!changed) return true;
  closeRestoreModal();
  restoreMode = false;
  selectedBackupId = null;
  selectedArchiveKey = null;
  importedRestoreSelection = null;
  importedRestoreSelectionRevision += 1;
  closePreviewModal();
  if (renderSelection && activeTab === 'backups') {
    renderBackupTab();
    renderHistory();
  }
  return true;
}

function validateRestoreTargetRoot() {
  if (!restoreState?.requiresTargetRoot) return true;
  const input = document.querySelector('[name="restore-target-root"]');
  const value = String(input?.value || restoreState.targetRoot || '').trim();
  restoreState.targetRoot = value;
  const unsafeSegment = value.split('/').some(part => part === '.' || part === '..');
  if (value.startsWith('/') && !value.includes('\\') && !unsafeSegment) return true;
  restoreState.planError = 'Укажите безопасный абсолютный путь без «.» и «..».';
  const error = document.getElementById('backup-restore-error');
  if (error) error.textContent = restoreState.planError;
  input?.focus();
  return false;
}

function restoreTreeIdentity(state) {
  if (!state) return null;
  return JSON.stringify({
    schema_version: 2,
    source_kind: state.sourceKind,
    source_id: state.sourceKind === 'imported' ? state.entryKey : state.backupId,
    source_revision: state.archiveIdentity,
    namespace: state.sourceQuery || '',
    target_root: state.requiresTargetRoot ? state.targetRoot : null,
  });
}

function restoreTreeIsCurrent(state) {
  const rootPage = state?.inventoryPages instanceof Map
    ? state.inventoryPages.get('')
    : null;
  return Boolean(
    state?.inventoryIdentity === restoreTreeIdentity(state)
    && rootPage?.loaded === true
  );
}

function clearRestoreInventoryTimers(state) {
  if (!state) return;
  if (state.inventoryPollTimer != null) clearTimeout(state.inventoryPollTimer);
  if (state.inventorySearchTimer != null) clearTimeout(state.inventorySearchTimer);
  state.inventoryPollTimer = null;
  state.inventorySearchTimer = null;
}

function resetRestoreInventory(state, { clearSelection = false } = {}) {
  if (!state) return;
  clearRestoreInventoryTimers(state);
  state.inventoryEpoch = Number(state.inventoryEpoch || 0) + 1;
  state.inventoryIdentity = null;
  state.inventoryStatus = null;
  state.inventoryRevision = null;
  state.inventoryPages = new Map();
  state.inventorySearch = null;
  state.inventorySelectAll = null;
  state.inventoryPolicySummary = null;
  state.inventoryPreparing = false;
  state.expandedDirectories = [];
  state.treeSearch = '';
  if (clearSelection) {
    state.selectedPaths = [];
    state.selectedPathTypes = new Map();
  }
}

function restoreInventoryEndpoint(state, suffix, { includeTargetRoot = false } = {}) {
  const base = `${restoreSourcePath(state.sourceKind, state.backupId, state.entryKey)}${suffix}`;
  const params = new URLSearchParams(String(state.sourceQuery || '').replace(/^\?/u, ''));
  if (includeTargetRoot && state.requiresTargetRoot) params.set('target_root', state.targetRoot);
  const query = params.toString();
  return `${base}${query ? `?${query}` : ''}`;
}

function restoreInventoryRequestBody(state) {
  return { target_root: state.requiresTargetRoot ? state.targetRoot : null };
}

function restoreInventoryRetryDelay(status) {
  const requested = Number(status?.retry_after_ms);
  if (!Number.isFinite(requested)) return 1000;
  return Math.max(500, Math.min(requested, 60_000));
}

function restoreInventoryErrorKind(error) {
  return String(error?.details?.inventory_error || '');
}

function renderRestoreInventoryState(state, { controls = false } = {}) {
  if (restoreState !== state || state.step !== 'tree') return;
  if (controls) renderRestoreModal();
  else renderRestoreDirectoryTree();
}

function scheduleRestoreInventoryStatus(state, status) {
  if (restoreState !== state) return;
  if (state.inventoryPollTimer != null) clearTimeout(state.inventoryPollTimer);
  const epoch = state.inventoryEpoch;
  state.inventoryPollTimer = setTimeout(() => {
    state.inventoryPollTimer = null;
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    pollRestoreInventoryStatus(state);
  }, restoreInventoryRetryDelay(status));
}

async function applyRestoreInventoryStatus(state, status) {
  if (restoreState !== state) return;
  state.inventoryStatus = status;
  const value = String(status?.status || '');
  if (value === 'ready') {
    if (state.inventoryRevision && state.inventoryRevision !== status.revision) {
      state.inventoryPages = new Map();
      state.inventorySearch = null;
      state.inventorySelectAll = null;
      state.expandedDirectories = [];
    }
    state.inventoryRevision = status.revision || null;
    state.inventoryPolicySummary = status.policy_summary || null;
    if (!restoreInventoryPage(null)) await loadRestoreInventoryPage(null);
    else renderRestoreInventoryState(state, { controls: true });
    return;
  }
  renderRestoreInventoryState(state);
  if (value === 'queued' || value === 'indexing') scheduleRestoreInventoryStatus(state, status);
  else if (value === 'missing') await prepareRestoreInventory(state);
}

async function prepareRestoreInventory(state, { retry = false } = {}) {
  if (restoreState !== state || state.inventoryPreparing) return;
  state.inventoryPreparing = true;
  const epoch = state.inventoryEpoch;
  renderRestoreInventoryState(state);
  try {
    const response = await j(restoreInventoryEndpoint(state, '/inventory/prepare'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...restoreInventoryRequestBody(state), retry }),
    });
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    await applyRestoreInventoryStatus(state, response);
  } catch (error) {
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    state.inventoryStatus = {
      status: 'failed',
      retryable: true,
      error: { message: archiveUiText(error.message) },
    };
    renderRestoreInventoryState(state);
  } finally {
    if (restoreState === state && state.inventoryEpoch === epoch) {
      state.inventoryPreparing = false;
      syncRestoreActions();
    }
  }
}

async function pollRestoreInventoryStatus(state) {
  if (restoreState !== state) return;
  const epoch = state.inventoryEpoch;
  try {
    const response = await j(restoreInventoryEndpoint(
      state,
      '/inventory/status',
      { includeTargetRoot: true },
    ));
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    await applyRestoreInventoryStatus(state, response);
  } catch (error) {
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    state.inventoryStatus = {
      status: 'failed',
      retryable: true,
      error: { message: archiveUiText(error.message) },
    };
    renderRestoreInventoryState(state);
  }
}

async function recoverRestoreInventory(state, status = null) {
  if (restoreState !== state) return;
  clearRestoreInventoryTimers(state);
  state.inventoryEpoch += 1;
  state.inventoryPages = new Map();
  state.inventorySearch = null;
  state.inventorySelectAll = null;
  state.inventoryRevision = null;
  state.inventoryPolicySummary = null;
  state.inventoryStatus = status;
  state.inventoryPreparing = false;
  state.expandedDirectories = [];
  renderRestoreInventoryState(state, { controls: true });
  if (status) await applyRestoreInventoryStatus(state, status);
  else await prepareRestoreInventory(state);
}

async function handleRestoreInventoryQueryError(state, error) {
  const kind = restoreInventoryErrorKind(error);
  if (kind === 'cursor_stale') {
    await recoverRestoreInventory(state);
    return true;
  }
  if (kind === 'not_ready') {
    await recoverRestoreInventory(state, error?.details?.inventory_status || null);
    return true;
  }
  return false;
}

async function loadRestoreInventoryPage(parent = null, { append = false } = {}) {
  const state = restoreState;
  if (!state || state.result || state.inventoryIdentity !== restoreTreeIdentity(state)) return;
  const key = parent == null ? '' : String(parent);
  const existing = state.inventoryPages.get(key) || null;
  if (existing?.loading || (append && !existing?.hasMore)) return;
  const page = append && existing
    ? existing
    : { items: [], nextCursor: null, hasMore: false, loading: false, loaded: false, error: '' };
  page.loading = true;
  page.error = '';
  state.inventoryPages.set(key, page);
  const refreshRootControls = parent == null && !append;
  renderRestoreInventoryState(state);
  const epoch = state.inventoryEpoch;
  try {
    const response = await j(restoreInventoryEndpoint(state, '/tree/children'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...restoreInventoryRequestBody(state),
        parent,
        cursor: append ? existing?.nextCursor || null : null,
        limit: RESTORE_TREE_PAGE_LIMIT,
      }),
    });
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    if (state.inventoryRevision && response.revision
        && state.inventoryRevision !== response.revision) {
      await recoverRestoreInventory(state);
      return;
    }
    const oldItems = append && existing ? existing.items : [];
    const paths = new Set(oldItems.map(item => String(item?.path || '')));
    const added = (Array.isArray(response.items) ? response.items : [])
      .filter(item => !paths.has(String(item?.path || '')));
    page.items = [...oldItems, ...added];
    page.nextCursor = response.next_cursor || null;
    page.hasMore = response.has_more === true;
    page.loading = false;
    page.loaded = true;
    page.revision = response.revision || null;
    state.inventoryRevision = response.revision || state.inventoryRevision;
    if (parent == null) {
      state.inventorySelectAll = response.select_all || null;
      state.inventoryPolicySummary = response.policy_summary || state.inventoryPolicySummary;
      state.inventoryStatus = {
        ...(state.inventoryStatus || {}),
        status: 'ready',
        revision: response.revision || state.inventoryRevision,
      };
    }
    renderRestoreInventoryState(state, { controls: refreshRootControls });
  } catch (error) {
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    if (await handleRestoreInventoryQueryError(state, error)) return;
    page.loading = false;
    page.error = archiveUiText(error.message);
    renderRestoreInventoryState(state);
  }
}

async function loadRestoreInventorySearch({ append = false } = {}) {
  const state = restoreState;
  if (!state || state.result || !restoreTreeIsCurrent(state)) return;
  const query = String(state.treeSearch || '').trim();
  if (!query) {
    state.inventorySearch = null;
    renderRestoreInventoryState(state);
    return;
  }
  const existing = state.inventorySearch?.query === query ? state.inventorySearch : null;
  if (existing?.loading || (append && !existing?.hasMore)) return;
  const search = append && existing
    ? existing
    : { query, items: [], nextCursor: null, hasMore: false, loading: false, error: '' };
  search.loading = true;
  search.error = '';
  state.inventorySearch = search;
  renderRestoreInventoryState(state);
  const epoch = state.inventoryEpoch;
  try {
    const response = await j(restoreInventoryEndpoint(state, '/tree/search'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...restoreInventoryRequestBody(state),
        query,
        cursor: append ? existing?.nextCursor || null : null,
        limit: RESTORE_TREE_PAGE_LIMIT,
      }),
    });
    if (restoreState !== state || state.inventoryEpoch !== epoch
        || state.inventorySearch !== search
        || String(state.treeSearch || '').trim() !== query) return;
    if (state.inventoryRevision && response.revision
        && state.inventoryRevision !== response.revision) {
      await recoverRestoreInventory(state);
      return;
    }
    const oldItems = append && existing ? existing.items : [];
    const paths = new Set(oldItems.map(item => String(item?.path || '')));
    const added = (Array.isArray(response.items) ? response.items : [])
      .filter(item => !paths.has(String(item?.path || '')));
    search.items = [...oldItems, ...added];
    search.nextCursor = response.next_cursor || null;
    search.hasMore = response.has_more === true;
    search.loading = false;
    search.revision = response.revision || null;
    state.inventoryRevision = response.revision || state.inventoryRevision;
    state.inventoryPolicySummary = response.policy_summary || state.inventoryPolicySummary;
    renderRestoreInventoryState(state);
  } catch (error) {
    if (restoreState !== state || state.inventoryEpoch !== epoch
        || state.inventorySearch !== search
        || String(state.treeSearch || '').trim() !== query) return;
    if (await handleRestoreInventoryQueryError(state, error)) return;
    search.loading = false;
    search.error = archiveUiText(error.message);
    renderRestoreInventoryState(state);
  }
}

function scheduleRestoreInventorySearch(state) {
  if (state.inventorySearchTimer != null) clearTimeout(state.inventorySearchTimer);
  state.inventorySearchTimer = null;
  const query = String(state.treeSearch || '').trim();
  if (!query) {
    state.inventorySearch = null;
    renderRestoreInventoryState(state);
    return;
  }
  const epoch = state.inventoryEpoch;
  state.inventorySearchTimer = setTimeout(() => {
    state.inventorySearchTimer = null;
    if (restoreState !== state || state.inventoryEpoch !== epoch) return;
    loadRestoreInventorySearch();
  }, RESTORE_TREE_SEARCH_DELAY_MS);
}

async function loadRestorePlan(selectionMode) {
  const state = restoreState;
  if (!state || state.result || state.planLoading) return null;
  if (!validateRestoreTargetRoot()) return null;
  const mode = selectionMode === 'selected' ? 'selected' : 'full';
  const selected = mode === 'selected' ? [...state.selectedPaths] : [];
  if (mode === 'selected' && !selected.length) {
    state.planError = 'Выберите хотя бы один разрешённый элемент.';
    renderRestoreModal();
    return null;
  }
  state.planLoading = true;
  state.planError = '';
  renderRestoreModal();
  restorePlanRequestsActive += 1;
  traceRestoreTiming('restore.plan_wait', {
    selection_mode: mode,
    include_directory_tree: false,
    active_plan_requests: restorePlanRequestsActive,
  });
  try {
    const endpoint = restorePlanPath(state.sourceKind, state.backupId, state.entryKey);
    const requestEndpoint = restoreTimingEndpoint(`${endpoint}${state.sourceQuery || ''}`);
    const response = await tracedBackupRequest(
      'restore.plan_request',
      {
        source_kind: state.sourceKind,
        selection_mode: mode,
        include_directory_tree: false,
      },
      () => j(requestEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_root: state.requiresTargetRoot ? state.targetRoot : null,
          selection_mode: mode,
          selected_paths: selected,
          include_directory_tree: false,
        }),
      }),
    );
    if (restoreState !== state) return null;
    state.planData = response;
    if (mode === 'selected' && Array.isArray(response.selected_paths)) {
      state.selectedPaths = [...response.selected_paths];
    }
    state.planTargetRoot = state.requiresTargetRoot ? state.targetRoot : null;
    state.fullPolicy = response.full_restore_unavailable === true
      ? (response.policy || { message: FULL_RESTORE_UNAVAILABLE_MESSAGE })
      : null;
    return response;
  } catch (err) {
    if (restoreState !== state) return null;
    state.planError = archiveUiText(err.message);
    return null;
  } finally {
    restorePlanRequestsActive -= 1;
    if (restoreState === state) {
      state.planLoading = false;
      renderRestoreModal();
    }
  }
}

async function openRestoreTree({ backStep = 'scope', reuse = false } = {}) {
  const state = restoreState;
  if (!state || state.result) return;
  state.step = 'tree';
  state.treeBackStep = backStep;
  state.planError = '';
  state.treeOpenedAt = timingNow();
  traceRestoreTiming('restore.tree_open', {
    source_kind: state.sourceKind,
    reuse_requested: reuse,
  });
  if (reuse && restoreTreeIsCurrent(state)) {
    traceRestoreTiming('restore.tree_reuse', { source_kind: state.sourceKind });
    state.pendingTreePaint = true;
    renderRestoreModal();
    return;
  }
  if (state.inventoryIdentity !== restoreTreeIdentity(state)) resetRestoreInventory(state);
  state.inventoryIdentity = restoreTreeIdentity(state);
  state.pendingTreePaint = true;
  renderRestoreModal();
  await prepareRestoreInventory(state);
}

function handleRestoreModalChange(event) {
  if (!restoreState || restoreState.result) return;
  const input = event.target;
  restoreState.planError = '';
  if (input.name === 'restore-scope') restoreState.scopeChoice = input.value === 'selected' ? 'selected' : 'full';
  if (input.name === 'restore-mode') restoreState.mode = input.value === 'clean' ? 'clean' : 'merge';
  if (input.name === 'restore-protective') restoreState.protective = input.value === 'yes';
  if (input.name === 'restore-target-root') {
    const value = input.value;
    if (value !== restoreState.targetRoot) {
      restoreState.targetRoot = value;
      restoreState.planData = null;
      restoreState.fullPolicy = null;
      restoreState.planTargetRoot = null;
      resetRestoreInventory(restoreState, { clearSelection: true });
      restoreState.pendingTreePaint = false;
    }
  }
  if (input.name === 'restore-path' && input.type === 'checkbox') {
    updateRestorePathSelection(input.value, input.checked, input.dataset.restorePathType);
    renderRestoreDirectoryTree();
  }
  if (input.name === 'restore-tree-search') {
    const value = input.value;
    if (value !== restoreState.treeSearch) {
      restoreState.treeSearch = value;
      restoreState.inventorySearch = null;
      renderRestoreDirectoryTree();
      scheduleRestoreInventorySearch(restoreState);
    }
  }
  syncRestoreActions();
}

async function toggleRestoreDirectory(path) {
  if (!restoreState || restoreState.result) return;
  const state = restoreState;
  const expanded = new Set(state.expandedDirectories || []);
  if (expanded.has(path)) {
    expanded.delete(path);
    state.expandedDirectories = [...expanded];
    renderRestoreDirectoryTree();
    return;
  }
  expanded.add(path);
  state.expandedDirectories = [...expanded];
  renderRestoreDirectoryTree();
  if (!restoreInventoryPage(path)) await loadRestoreInventoryPage(path);
}

function restoreKnownInventoryNodeType(state, path) {
  if (state?.inventoryPages instanceof Map) {
    for (const page of state.inventoryPages.values()) {
      const node = (page?.items || []).find(item => String(item?.path || '') === path);
      if (node) return node.type === 'file' ? 'file' : 'directory';
    }
  }
  const result = (state?.inventorySearch?.items || [])
    .find(item => String(item?.path || '') === path);
  return result?.type === 'file' ? 'file' : result ? 'directory' : null;
}

function selectAllRestorePaths() {
  const state = restoreState;
  const selection = state?.inventorySelectAll;
  if (!state || !selection) return;
  if (selection.available !== true || !Array.isArray(selection.paths)) {
    const required = Number(selection.required_count || 0);
    state.planError = archiveUiText(
      selection.error?.message
      || (required > 512
        ? `Нельзя выбрать всё: требуется ${required} отдельных элементов, а допустимо не более 512.`
        : 'В backup нет разрешённых элементов для выбора.'),
    );
    renderRestoreModal();
    return;
  }
  const selected = [...selection.paths].map(String).sort(restorePathOrder);
  if (selected.length > 512) {
    state.planError = 'Нельзя выбрать всё: сервер вернул больше 512 отдельных элементов.';
    renderRestoreModal();
    return;
  }
  state.planError = '';
  state.selectedPaths = selected;
  state.selectedPathTypes = new Map(selected.map(path => [
    path,
    restoreKnownInventoryNodeType(state, path) || 'directory',
  ]));
  renderRestoreDirectoryTree();
}

function clearRestorePathSelection() {
  const state = restoreState;
  if (!state || state.result) return;
  state.planError = '';
  state.selectedPaths = [];
  state.selectedPathTypes = new Map();
  renderRestoreDirectoryTree();
}

function handleRestoreModalClick(event) {
  const toggle = event.target.closest('[data-restore-tree-toggle]');
  if (toggle) {
    toggleRestoreDirectory(toggle.dataset.restoreTreeToggle);
    return;
  }
  const retryPage = event.target.closest('[data-restore-tree-retry]');
  if (retryPage) {
    const value = retryPage.getAttribute('data-restore-tree-retry');
    loadRestoreInventoryPage(value || null);
    return;
  }
  if (event.target.closest('[data-restore-search-retry]')) {
    loadRestoreInventorySearch();
    return;
  }
  const more = event.target.closest('[data-restore-tree-more]');
  if (more) {
    const value = more.getAttribute('data-restore-tree-more');
    loadRestoreInventoryPage(value || null, { append: true });
    return;
  }
  if (event.target.closest('[data-restore-search-more]')) {
    loadRestoreInventorySearch({ append: true });
    return;
  }
  if (event.target.closest('[data-restore-inventory-retry]')) {
    if (restoreState) prepareRestoreInventory(restoreState, { retry: true });
    return;
  }
  if (event.target.closest('[data-restore-clear-all]')) {
    clearRestorePathSelection();
    return;
  }
  if (event.target.closest('[data-restore-select-all]')) {
    selectAllRestorePaths();
    return;
  }
}

const RESTORE_NO_PROTECTIVE_WARNING = 'Без защитной копии вернуть текущее состояние будет нечем: '
  + 'заменённые и удалённые файлы восстановить не получится.';

async function continueRestoreBranch() {
  if (!restoreState) return;
  if (restoreState.selectionMode === 'selected') {
    await openRestoreTree({ backStep: restoreState.requiresTargetRoot ? 'target-root' : 'scope' });
  } else {
    restoreState.step = 'mode';
    renderRestoreModal();
  }
}

async function submitRestore() {
  if (!restoreState || restoreState.submitting || restoreState.planLoading) return;
  // Итоговый экран подготовки: та же кнопка ведёт к подтверждению применения.
  if (restoreState.result) {
    if (restoreState.result.gate) await confirmRestoreApply();
    return;
  }

  if (restoreState.step === 'scope') {
    if (!restoreState.scopeChoice) return;
    restoreState.selectionMode = restoreState.scopeChoice;
    if (restoreState.requiresTargetRoot) {
      restoreState.step = 'target-root';
      renderRestoreModal();
    } else {
      await continueRestoreBranch();
    }
    return;
  }
  if (restoreState.step === 'target-root') {
    if (!validateRestoreTargetRoot()) return;
    await continueRestoreBranch();
    return;
  }
  if (restoreState.step === 'tree') {
    if (!restoreState.selectedPaths.length) return;
    restoreState.step = 'mode';
    renderRestoreModal();
    return;
  }
  if (restoreState.step === 'mode') {
    if (!restoreState.mode) return;
    const plan = await loadRestorePlan(restoreState.selectionMode);
    if (!restoreState || !plan) return;
    if (restoreState.selectionMode === 'full' && plan.full_restore_unavailable === true) {
      restoreState.step = 'full-unavailable';
      renderRestoreModal();
      return;
    }
    restoreState.step = 'protective';
    renderRestoreModal();
    return;
  }
  if (restoreState.step === 'full-unavailable') {
    restoreState.selectionMode = 'selected';
    restoreState.selectedPaths = [];
    restoreState.selectedPathTypes = new Map();
    await openRestoreTree({ backStep: 'full-unavailable', reuse: true });
    return;
  }
  if (restoreState.step !== 'protective') return;

  // Отказ от защитной копии подтверждается отдельно и поверх основного диалога:
  // «Отмена» обязана вернуть пользователя к уже заполненному safety-шагу.
  if (!restoreState.protective) {
    if (restoreConfirm) return;
    restoreConfirm = true;
    let approved = false;
    try {
      approved = await confirmAction({
        title: '⚠️ Восстановление без защитной копии',
        message: RESTORE_NO_PROTECTIVE_WARNING,
        confirmText: 'Продолжить',
        cancelText: 'Отмена',
        confirmFirst: true,
      });
    } finally {
      restoreConfirm = false;
    }
    if (!approved || !restoreState || restoreState.result || restoreState.submitting) return;
  }
  await startRestore();
}

/* Один и тот же запрос обслуживает оба шага: safety-step запускает подготовку,
   итоговый экран подготовки (result.gate) — применение уже рассчитанного плана. */
async function startRestore() {
  const error = document.getElementById('backup-restore-error');
  const submit = document.getElementById('backup-restore-submit');
  const apply = Boolean(restoreState.result?.gate);
  restoreState.submitting = true;
  syncRestoreActions();
  try {
    let payload;
    if (apply) {
      if (!restoreState.preparedOperationId) {
        throw new Error('Prepared Restore устарел: выполните подготовку заново.');
      }
      payload = {
        apply: true,
        prepared_operation_id: restoreState.preparedOperationId,
        confirm: true,
        // Выбор защитной копии зафиксирован в server-owned prepare contract;
        // браузер повторно его не посылает и подтверждает только отказ, если он был.
        confirm_without_protective: !restoreState.protective,
      };
    } else {
      payload = {
        restore_mode: restoreState.mode,
        protective_backup: restoreState.protective,
        target_root: restoreState.requiresTargetRoot ? restoreState.targetRoot : null,
        selection_mode: restoreState.selectionMode,
        selected_paths: restoreState.selectionMode === 'selected'
          ? [...restoreState.selectedPaths]
          : [],
        apply: false,
      };
    }
    const endpoint = restoreSourcePath(
      restoreState.sourceKind,
      restoreState.backupId,
      restoreState.entryKey,
    );
    const response = await j(`${endpoint}${restoreState.sourceQuery || ''}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    // Source kind, identity, namespace и target root переносятся в watch: с
    // итогового экрана подготовки запускается применение того же bundle с тем же
    // выбором пользователя.
    restoreWatch = {
      operationId: response.operation?.operation_id || null,
      sourceKind: restoreState.sourceKind,
      bot: restoreState.bot,
      serverId: restoreState.serverId,
      backupId: restoreState.backupId,
      entryKey: restoreState.entryKey,
      sourceQuery: restoreState.sourceQuery,
      requiresTargetRoot: restoreState.requiresTargetRoot,
      targetRoot: restoreState.targetRoot,
      mode: restoreState.mode,
      protective: restoreState.protective,
    };
    closeRestoreModal();
    restoreMode = false;
    selectedBackupId = null;
    selectedArchiveKey = null;
    importedRestoreSelection = null;
    importedRestoreSelectionRevision += 1;
    if (response.operation) snapshot.operations.unshift(response.operation);
    toast(apply ? 'Применение восстановления запущено' : 'Restore запущен', true);
    renderOperations();
    renderBackupTab();
    loadBackups();
  } catch (err) {
    if (error) error.textContent = archiveUiText(err.message);
    if (restoreState) {
      restoreState.submitting = false;
      syncRestoreActions();
    } else if (submit) {
      submit.disabled = false;
    }
  }
}

/* Последний шаг перед изменением сервера: за этим подтверждением уже следует
   реальное применение, и оно необратимо. */
async function confirmRestoreApply() {
  if (restoreConfirm) return;
  const clean = restoreState.result?.mode === 'clean';
  restoreConfirm = true;
  let approved = false;
  try {
    approved = await confirmAction({
      title: 'Применить восстановление?',
      message: clean
        ? 'Перечисленные объекты будут перезаписаны, а лишние данные удалены только внутри явно '
          + 'выбранных каталогов. Отдельно выбранные файлы не расширяют область удаления. После начала изменений отмена невозможна.'
        : 'Перечисленные объекты будут перезаписаны и добавлены, ничего не удаляется. '
          + 'После начала изменений отмена невозможна.',
      confirmText: 'Применить',
      cancelText: 'Отмена',
      danger: true,
      confirmFirst: true,
    });
  } finally {
    restoreConfirm = false;
  }
  // Пока висело подтверждение, диалог мог быть закрыт или уже отправлен.
  if (!approved || !restoreState || !restoreState.result?.gate || restoreState.submitting) return;
  await startRestore();
}

/* Secondary action возвращает на предыдущий экран мастера; на первом экране и
   policy fallback она отменяет весь ещё не отправленный Restore flow. */
function cancelRestore() {
  if (restoreState?.submitting || restoreState?.planLoading) return;
  const gate = Boolean(restoreState?.result?.gate);
  if (!restoreState || restoreState.result || restoreState.step === 'scope'
      || restoreState.step === 'full-unavailable') {
    if (cancelRestoreStart() && gate) {
      toast('Восстановление отменено: данные на сервере не изменялись', true);
    }
    return;
  }
  if (restoreState.step === 'target-root') restoreState.step = 'scope';
  else if (restoreState.step === 'tree') restoreState.step = restoreState.treeBackStep || 'scope';
  else if (restoreState.step === 'mode') {
    restoreState.step = restoreState.selectionMode === 'selected'
      ? 'tree'
      : (restoreState.requiresTargetRoot ? 'target-root' : 'scope');
  } else if (restoreState.step === 'protective') restoreState.step = 'mode';
  restoreState.planError = '';
  renderRestoreModal();
}

/* Отдельная «Отмена» на промежуточных шагах сбрасывает также выбор архива,
   тогда как соседняя secondary action остаётся обычной кнопкой «Назад». */
function abortRestore() {
  if (!restoreState || restoreState.submitting) return;
  cancelRestoreStart();
}

/* Сводка плана из Operation. Backend уже урезал списки до лимита и сохранил
   полные количества, поэтому «и ещё N» считается по counts, а не по длине
   показанного списка. */
function restorePlanLines(paths, total, truncated, forms) {
  const shown = Array.isArray(paths) ? paths : [];
  const rows = shown.map(path => `<div><code>${esc(path)}</code></div>`).join('');
  const rest = Math.max(0, Number(total || 0) - shown.length);
  const more = truncated && rest > 0
    ? `<div class="backup-restore-plan-more">… и ещё ${rest} ${plural(rest, forms[0], forms[1], forms[2])}</div>`
    : '';
  return `<div class="backup-restore-plan">${rows}${more}</div>`;
}

function restorePlanView(plan) {
  if (!plan) return '';
  const block = (title, body) => `<div class="backup-restore-block"><h4>${title}</h4>${body}</div>`;
  const list = (title, paths, total, truncated, forms, empty) => {
    const count = Number(total || 0);
    return block(title, count
      ? restorePlanLines(paths, count, truncated, forms)
      : `<p class="hint">${empty}</p>`);
  };
  const parts = [list(
    'Будут заменены:',
    plan.replace,
    plan.counts?.replace,
    plan.truncated?.replace,
    ['файл', 'файла', 'файлов'],
    'Ни один из объектов архива на сервере пока не существует — заменять нечего.',
  )];
  // add появился позже: у ранних сводок ключа нет вовсе, и выдумывать блок
  // «будут добавлены» из ничего нельзя.
  if (Array.isArray(plan.add)) {
    parts.push(list(
      'Будут добавлены:',
      plan.add,
      plan.counts?.add,
      plan.truncated?.add,
      ['файл', 'файла', 'файлов'],
      'Все объекты архива на сервере уже есть — добавлять нечего.',
    ));
  }
  // Блока удаления у merge нет вообще: режим ничего не удаляет, и delete-list для
  // него не считается (null). У clean он посчитан и может быть пуст.
  if (Array.isArray(plan.delete)) {
    parts.push(list(
      'Будут удалены:',
      plan.delete,
      plan.counts?.delete,
      plan.truncated?.delete,
      ['объект', 'объекта', 'объектов'],
      'Лишних объектов внутри явно выбранных каталогов нет — удалять нечего.',
    ));
  }
  return parts.join('');
}

function restorePreflightView(advisory) {
  if (!advisory || typeof advisory !== 'object') return '';
  const status = String(advisory.status || 'unavailable');
  const matches = Array.isArray(advisory.matches) ? advisory.matches : [];
  const count = Number(advisory.match_count || 0);
  const stored = Number(advisory.stored_match_count || matches.length);
  const title = 'Предварительная проверка executable (advisory-снимок)';
  const rows = matches.map(item => {
    const path = esc(item?.path || 'неизвестный путь');
    const process = esc(item?.process || 'процесс без имени');
    const pid = esc(String(item?.pid ?? 'неизвестный PID'));
    return `<li><code>${path}</code> — PID ${pid}, ${process}</li>`;
  }).join('');
  const disclaimer = '<p>Это только point-in-time advisory: target мог измениться между проверкой и extraction. Результат не означает, что файл уже будет пропущен.</p>';
  if (status === 'complete' && count === 0) {
    return `<div class="backup-restore-warning"><strong>${title}</strong>
      <p>Совпадений с executable, используемыми работающими процессами, не обнаружено.</p>
      ${disclaimer}</div>`;
  }
  if (status === 'complete' || status === 'truncated') {
    const incomplete = status === 'truncated'
      ? `<p>Сканирование ограничено: показаны ${esc(String(stored))} из ${esc(String(count))} обнаруженных совпадений; результат неполный.</p>`
      : `<p>Обнаружено совпадений: ${esc(String(count))}.</p>`;
    return `<div class="backup-restore-warning"><strong>${title}</strong>
      ${incomplete}
      ${rows ? `<ul>${rows}</ul>` : ''}
      <p>Перед применением проверьте работающие процессы и при необходимости остановите соответствующий сервис вручную. Автоматическая остановка не выполняется.</p>
      ${disclaimer}</div>`;
  }
  const diagnostic = advisory.diagnostic
    ? `<p>Диагностика: <code>${esc(advisory.diagnostic)}</code></p>`
    : '';
  return `<div class="backup-restore-warning"><strong>${title}</strong>
    <p>Снимок executable не удалось надёжно получить (статус: <code>${esc(status)}</code>). Restore не блокируется этой advisory-проверкой.</p>
    ${diagnostic}
    ${disclaimer}</div>`;
}

function restoreSelectionContractView(selection) {
  if (!selection || typeof selection !== 'object') return '';
  const selective = selection.selection_mode === 'selected';
  const modernSelection = Array.isArray(selection.selected_paths);
  const selected = modernSelection
    ? selection.selected_paths
    : (Array.isArray(selection.selected_directories) ? selection.selected_directories : []);
  const roots = Array.isArray(selection.effective_roots) ? selection.effective_roots : [];
  const rootRows = roots.map(path => `<div><code>${esc(path)}</code></div>`).join('');
  const hidden = Math.max(0, Number(selection.effective_root_count || 0) - roots.length);
  const more = selection.effective_roots_truncated && hidden
    ? `<div class="backup-restore-plan-more">… и ещё ${hidden}</div>`
    : '';
  const selectedRows = selective
    ? `<p><strong>${modernSelection ? 'Выбрано элементов' : 'Выбрано каталогов'}:</strong> ${selected.length}.</p>`
    : '<p><strong>Объём:</strong> полностью.</p>';
  return `<div class="backup-restore-block">
    <h4>Зафиксированный сервером выбор</h4>
    ${selectedRows}
    <p><strong>Режим:</strong> ${selection.restore_mode === 'clean' ? 'чистое восстановление' : 'обычное восстановление'}.</p>
    <p><strong>Защитная копия:</strong> ${selection.protective_backup ? 'да' : 'нет'}.</p>
    <div class="backup-restore-plan">${rootRows}${more}</div>
  </div>`;
}

function restoreResultView(operation) {
  const selection = operation.restore?.selection;
  const selectionSummary = restoreSelectionContractView(selection);
  const preflight = restorePreflightView(operation.restore?.preflight_conflicts);
  const applied = Boolean(operation.restore?.mutation_started);
  const protectiveId = operation.restore?.protective_backup_id || null;
  const protective = protectiveId
    ? snapshot.catalog.find(item => item.backup_id === protectiveId)
    : null;
  const protectiveLine = protectiveId
    ? `<p>Защитная копия: <strong>${esc(archiveDisplayName(protective || protectiveId))}</strong>.</p>`
    : '<p>Защитная копия не создавалась.</p>';
  if (operation.status !== 'completed') {
    const reason = esc(archiveUiText(operation.error?.message || 'Операция Restore завершилась без результата.'));
    // Незавершённая операция после пересечения границы мутации — не «ничего не
    // произошло»: часть файлов на target уже заменена или удалена, и молчать об
    // этом нельзя. Именно здесь защитная копия и нужна пользователю.
    if (applied) {
      return {
        title: 'Восстановление применено не полностью',
        html: `<p>${reason}</p>
          <div class="backup-restore-warning">Данные на сервере уже изменялись: состояние может быть неполным. Проверьте сервер и при необходимости восстановитесь из защитной копии.</div>
          ${protectiveLine}`,
      };
    }
    return {
      title: 'Восстановление не выполнено',
      html: `<p>${reason}</p>
        ${protectiveLine}
        <p class="backup-restore-untouched">Данные на сервере не изменялись.</p>`,
    };
  }
  if (!applied) {
    // Сводка плана есть только у операций, подготовленных после её появления:
    // у ранних записей поля нет вовсе, и текст остаётся общим.
    const planned = restorePlanView(operation.restore?.plan);
    return {
      title: 'Восстановление подготовлено',
      // gate: подготовка закончена, применение — отдельный шаг и отдельное
      // подтверждение. Кнопка ведёт к подтверждению, а за ним — к применению
      // того же плана.
      gate: true,
      mode: selection?.restore_mode || operation.restore?.plan?.mode || 'merge',
      html: `${protectiveLine}
        ${selectionSummary}
        ${preflight}
        ${planned || '<p>План восстановления построен, защитная копия обработана.</p>'}
        <p class="backup-restore-untouched">Данные на сервере пока не изменялись.</p>`,
    };
  }
  const skipped = Array.isArray(operation.restore?.skipped_members)
    ? operation.restore.skipped_members
    : [];
  if (skipped.length) {
    const rows = skipped.map(item => {
      const path = esc(item.path || item.member_name || 'неизвестный путь');
      const reason = item.reason === 'hardlink_dependency'
        ? 'зависит от пропущенного hardlink-источника'
        : 'используется работающим процессом';
      return `<li><code>${path}</code> — ${esc(reason)}</li>`;
    }).join('');
    return {
      title: 'Восстановление завершено с предупреждениями.',
      html: `<p>Данные восстановлены из backup, но некоторые файлы пропущены.</p>
        ${protectiveLine}
        <div class="backup-restore-warning">
          <strong>Не восстановлены файлы:</strong>
          <ul>${rows}</ul>
          <p>Чтобы восстановить эти файлы, остановите соответствующий сервис вручную и повторите восстановление.</p>
          <p>Предварительная проверка была advisory-снимком: состояние target могло измениться между проверкой и распаковкой.</p>
        </div>`,
    };
  }
  return {
    title: 'Восстановление выполнено',
    html: `<p>Данные восстановлены из backup.</p>
      ${protectiveLine}
      <div class="backup-restore-warning">Автоматическая остановка процессов, перезапуск служб и перезагрузка не выполняются. Проверьте target и выполните необходимые действия вручную.</div>`,
  };
}

function showRestoreResult(operation, watch) {
  const view = restoreResultView(operation);
  const sourceKind = watch?.sourceKind === 'imported' ? 'imported' : 'managed';
  const backupId = watch?.backupId || null;
  const entryKey = watch?.entryKey || null;
  // Без identity выбранного source применить нечего: предложить «Продолжить» и
  // ничего за ним не сделать хуже, чем честно закрыть экран и подготовить заново.
  if (view.gate && !(sourceKind === 'imported' ? entryKey : backupId)) view.gate = false;
  const selection = operation.restore?.selection || null;
  restoreState = {
    step: 'result',
    sourceKind,
    backupId,
    entryKey,
    sourceQuery: watch?.sourceQuery || '',
    name: '',
    targetName: targetName(),
    serverId: watch?.serverId || null,
    bot: Boolean(watch?.bot),
    requiresTargetRoot: Boolean(watch?.requiresTargetRoot),
    targetRoot: selection?.target_root || operation.restore?.plan?.target_root || watch?.targetRoot || '',
    // Apply получает только prepared_operation_id. Все параметры ниже показываются
    // из immutable selection contract, а watch остаётся лишь fallback для старых
    // завершённых операций без такого контракта.
    mode: selection?.restore_mode || view.mode || watch?.mode || 'merge',
    protective: selection ? selection.protective_backup === true : Boolean(watch?.protective),
    selectionMode: selection?.selection_mode || 'full',
    selectedPaths: Array.isArray(selection?.selected_paths)
      ? [...selection.selected_paths]
      : (Array.isArray(selection?.selected_directories)
        ? [...selection.selected_directories]
        : []),
    treeSearch: '',
    planData: null,
    fullPolicy: null,
    planLoading: false,
    planTargetRoot: selection?.target_root || null,
    preparedOperationId: view.gate ? operation.operation_id : null,
    submitting: false,
    result: view,
  };
  renderRestoreModal();
  document.getElementById('backup-restore-modal')?.classList.add('open');
}

function checkRestoreResult() {
  if (!restoreWatch?.operationId) return;
  const operation = (snapshot.operations || []).find(item => item.operation_id === restoreWatch.operationId);
  if (!operation || !terminal.has(operation.status)) return;
  // Пока открыт какой-то Restore-диалог, подменять его результатом нельзя:
  // покажем на следующем опросе.
  if (restoreState) return;
  const watch = restoreWatch;
  restoreWatch = null;
  showRestoreResult(operation, watch);
}

function openRenameModal({ kind, id, item }) {
  renameState = { kind, id, item };
  const modal = document.getElementById('backup-rename-modal');
  const title = document.getElementById('backup-rename-title');
  const message = document.getElementById('backup-rename-message');
  const input = document.getElementById('backup-rename-input');
  const error = document.getElementById('backup-rename-error');
  if (!modal || !input) return;
  title.textContent = kind === 'import-pending' ? 'Имя импортируемого backup' : 'Переименовать backup';
  message.textContent = kind === 'import-pending'
    ? 'Задайте имя импортируемому backup без расширения и продолжите Import.'
    : 'Имя backup без расширения должно быть уникальным на выбранном сервере.';
  error.textContent = '';
  input.value = kind === 'import-pending'
    ? archiveDisplayName(pendingImport?.filename || '')
    : archiveDisplayName(item || '');
  modal.classList.add('open');
  requestAnimationFrame(() => { input.focus(); input.select(); });
}

function closeRenameModal({ resumeImportConflict = true } = {}) {
  const wasPendingImport = renameState?.kind === 'import-pending';
  renameState = null;
  document.getElementById('backup-rename-modal')?.classList.remove('open');
  if (resumeImportConflict && wasPendingImport && pendingImport && importConflict) {
    openStoredImportConflict();
  }
}

async function submitRename() {
  if (!renameState) return;
  const input = document.getElementById('backup-rename-input');
  const errorHost = document.getElementById('backup-rename-error');
  const value = String(input?.value || '').trim();
  if (!value) {
    if (errorHost) errorHost.textContent = 'Укажите имя backup.';
    input?.focus();
    return;
  }
  let filename;
  try {
    filename = archiveTechnicalFilename(value);
  } catch (error) {
    if (errorHost) errorHost.textContent = error.message;
    input?.focus();
    input?.select();
    return;
  }
  const state = renameState;
  const button = document.getElementById('backup-rename-save');
  if (button) button.disabled = true;
  try {
    if (state.kind === 'import-pending') {
      if (!pendingImport) return;
      pendingImport.filename = filename;
      selectedImportFilename = filename;
      const imported = await runPendingImport({ conflictInRename: true });
      if (imported) closeRenameModal({ resumeImportConflict: false });
      return;
    }
    const imported = state.kind === 'imported';
    const query = imported ? importedNamespaceQuery(state.item) : namespaceQuery(state.item);
    const url = imported
      ? `/api/backups/imported/${encodeURIComponent(state.id)}/filename${query}`
      : `/api/backups/${encodeURIComponent(state.id)}/filename${query}`;
    await j(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }),
    });
    closeRenameModal();
    toast('Имя файла сохранено', true);
    loadBackups();
  } catch (error) {
    if (error.code === 'ARCHIVE_FILENAME_CONFLICT') {
      if (errorHost) errorHost.textContent = `Backup с именем ${archiveDisplayName(filename)} уже существует на этом сервере.`;
      input?.focus();
      input?.select();
    } else {
      toast(archiveUiText(error.message), false);
    }
  } finally {
    if (button) button.disabled = false;
  }
}

function rememberImportConflict(error) {
  if (!pendingImport) return;
  const details = error.details || {};
  importConflict = {
    filename: details.filename || pendingImport.filename,
    requiresConfirmation: Boolean(details.requires_confirmation),
  };
}

function openStoredImportConflict() {
  if (!pendingImport || !importConflict) return;
  const modal = document.getElementById('backup-import-conflict-modal');
  const message = document.getElementById('backup-import-conflict-message');
  if (!modal || !message) return;
  message.textContent = `Backup с именем ${archiveDisplayName(importConflict.filename)} уже существует на этом сервере.`;
  modal.classList.add('open');
}

function showImportConflict(error) {
  rememberImportConflict(error);
  openStoredImportConflict();
}

function closeImportConflict({ discard = false } = {}) {
  document.getElementById('backup-import-conflict-modal')?.classList.remove('open');
  if (discard) {
    importConflict = null;
    pendingImport = null;
    selectedImportFilename = '';
    renderBackupTab();
  }
}

function chooseImportRename() {
  if (!pendingImport) return;
  closeImportConflict();
  openRenameModal({ kind: 'import-pending', id: null, item: null });
}

async function replaceImport() {
  if (!pendingImport) return;
  const needsConfirmation = Boolean(importConflict?.requiresConfirmation);
  const conflictFilename = importConflict?.filename || pendingImport.filename;
  closeImportConflict();
  if (needsConfirmation) {
    const approved = await confirmAction({
      title: 'Заменить backup Bot4VPS?',
      message: `Существующий backup «${archiveDisplayName(conflictFilename)}» создан Bot4VPS и будет заменён импортируемым архивом. Продолжить?`,
      confirmText: 'Заменить',
      cancelText: 'Отмена',
      confirmFirst: true,
    });
    if (!approved) {
      openStoredImportConflict();
      return;
    }
  }
  await runPendingImport({ replace: true, confirmBot4VpsReplace: needsConfirmation });
}

function cancelImportConflict() {
  closeImportConflict({ discard: true });
}

async function renameManaged(id) {
  const item = targetCatalog().find(entry => entry.backup_id === id);
  if (item) {
    closePreviewModal();
    openRenameModal({ kind: 'managed', id, item });
  }
}

async function renameImported(entryKey) {
  const item = targetImportedArchives().find(entry => entry.entry_key === entryKey);
  if (item) {
    closePreviewModal();
    openRenameModal({ kind: 'imported', id: entryKey, item });
  }
}

async function clearHistory() {
  const approved = await confirmAction({
    title: "Очистить историю?",
    message:
      "Все записи истории Backup Manager будут удалены.\n" +
      "Сами backup и файлы хранилища затронуты не будут.",
    confirmText: "Ок",
    cancelText: "Отмена",
    confirmFirst: true,
  });
  if (!approved) return;
  try {
    await j('/api/backups/operations/history', { method: 'DELETE' });
    toast('История Backup Manager очищена', true);
    loadBackups();
  } catch (error) { toast(archiveUiText(error.message), false); }
}

async function removeImported(entryKey) {
  const approved = await confirmAction({
    title: 'Удалить импортированный архив?',
    message: 'Архив, checksum и publication metadata будут удалены вместе.',
    confirmText: 'Удалить',
    confirmFirst: true,
  });
  if (!approved) return;
  try {
    await j(`/api/backups/imported/${encodeURIComponent(entryKey)}${importedNamespaceQuery(entryKey)}`, { method: 'DELETE' });
    if (previewState?.sourceKind === 'imported' && previewState.sourceId === entryKey) {
      closePreviewModal();
    }
    if (selectedArchiveKey === entryKey) {
      selectedArchiveKey = null;
      importedRestoreSelection = null;
      importedRestoreSelectionRevision += 1;
      closePreviewModal();
    }
    toast('Импортированный архив удалён', true);
    loadBackups();
  } catch (error) { toast(archiveUiText(error.message), false); }
}

async function selectImportedForRestore(entryKey) {
  if (!entryKey) return;
  closePreviewModal();
  if (selectedArchiveKey === entryKey) {
    selectedArchiveKey = null;
    importedRestoreSelection = null;
    importedRestoreSelectionRevision += 1;
    renderBackupTab();
    return;
  }
  const item = targetImportedArchives().find(entry => entry.entry_key === entryKey);
  if (!item) return;
  const revision = ++importedRestoreSelectionRevision;
  selectedBackupId = null;
  selectedArchiveKey = entryKey;
  importedRestoreSelection = {
    entryKey,
    status: 'pending',
    requiresTargetRoot: true,
    notice: '',
    item,
  };
  renderBackupTab();
  traceRestoreTiming('restore.imported_select', { archive_kind: 'imported' });
  try {
    const data = await j(
      `/api/backups/imported/${encodeURIComponent(entryKey)}/restore/readiness${importedNamespaceQuery(item)}`,
    );
    if (revision !== importedRestoreSelectionRevision
        || selectedArchiveKey !== entryKey || !restoreMode) return;
    if (data.eligible !== true) {
      importedRestoreSelection = {
        entryKey,
        status: 'unavailable',
        requiresTargetRoot: true,
        notice: 'Этот импортированный backup нельзя восстановить.',
        item,
      };
      renderBackupTab();
      return;
    }
    importedRestoreSelection = {
      entryKey,
      status: 'ready',
      requiresTargetRoot: data.requires_target_root === true,
      notice: '',
      item,
    };
    renderBackupTab();
  } catch (error) {
    if (revision !== importedRestoreSelectionRevision || selectedArchiveKey !== entryKey) return;
    importedRestoreSelection = {
      entryKey,
      status: 'error',
      requiresTargetRoot: true,
      notice: archiveUiText(error.message),
      item,
    };
    renderBackupTab();
    toast(importedRestoreSelection.notice, false);
  }
}

function previewImported(entryKey) {
  if (!entryKey) return;
  const item = targetImportedArchives().find(entry => entry.entry_key === entryKey);
  if (item) openPreviewModal('imported', entryKey, item);
}

/* Одна и та же копия файла (имя + размер + mtime) всегда даёт тот же id, поэтому повторный
   выбор того же файла попадает в ТУ ЖЕ Operation на сервере (dedup по
   request_id) и не создаёт второй импорт. Имя не подставляем в id целиком —
   сворачиваем в хеш, чтобы уложиться в лимит request_id (256 символов). */
const importRequestIds = new Map();
let importInFlight = false;

function importRequestId(file) {
  const key = `${file.name}|${file.size}|${file.lastModified}`;
  let id = importRequestIds.get(key);
  if (!id) {
    let hash = 5381;
    for (let index = 0; index < key.length; index += 1) {
      hash = (((hash << 5) + hash) ^ key.charCodeAt(index)) >>> 0;
    }
    id = `web-import-${file.size}-${file.lastModified}-${hash.toString(36)}`;
    importRequestIds.set(key, id);
  }
  return id;
}

/* Защита от повторного клика во время активной операции. Функциональная защита —
   importInFlight (кнопку могут перерисовать в любой момент), disabled — её
   видимое отражение. */
function setImportBusy(busy) {
  document.querySelectorAll('[data-import-backup]').forEach(button => { button.disabled = busy; });
}

async function runPendingImport({
  replace = false,
  confirmBot4VpsReplace = false,
  conflictInRename = false,
} = {}) {
  if (!pendingImport || importInFlight) return false;
  const { file, filename } = pendingImport;
  const form = new FormData();
  form.append('file', file);
  const destination = selectedTarget === BOT_TARGET ? null : String(selectedTarget);
  const parts = [];
  if (destination) parts.push(`destination_server_id=${encodeURIComponent(destination)}`);
  parts.push(`request_id=${encodeURIComponent(importRequestId(file))}`);
  parts.push(`filename=${encodeURIComponent(filename)}`);
  if (replace) parts.push('replace=true');
  if (confirmBot4VpsReplace) parts.push('confirm_bot4vps_replace=true');
  const query = `?${parts.join('&')}`;
  importInFlight = true;
  setImportBusy(true);
  try {
    await j(`/api/backups/import${query}`, { method: 'POST', body: form });
    pendingImport = null;
    importConflict = null;
    selectedImportFilename = '';
    toast('Backup импортирован', true);
    loadBackups();
    return true;
  } catch (error) {
    if (error.code === 'ARCHIVE_FILENAME_CONFLICT'
        || error.code === 'ARCHIVE_REPLACE_CONFIRMATION_REQUIRED') {
      if (conflictInRename) {
        rememberImportConflict(error);
        const errorHost = document.getElementById('backup-rename-error');
        if (errorHost) {
          errorHost.textContent = `Backup с именем ${archiveDisplayName(filename)} уже существует на этом сервере.`;
        }
        document.getElementById('backup-rename-input')?.focus();
        document.getElementById('backup-rename-input')?.select();
      } else {
        showImportConflict(error);
      }
    } else {
      toast(archiveUiText(error.message), false);
      if (replace) openStoredImportConflict();
    }
    return false;
  } finally {
    importInFlight = false;
    setImportBusy(false);
  }
}

async function importFile(file) {
  if (importInFlight) return;
  let filename;
  try {
    const selectedName = String(file?.name || '');
    if (!/\.(?:tar\.gz|tgz|tar)$/i.test(selectedName)) {
      throw new Error('Можно импортировать только TAR-архив backup.');
    }
    const base = selectedName.replace(/\.(?:tar\.gz|tgz|tar)$/i, '');
    filename = archiveTechnicalFilename(base);
  } catch (error) {
    pendingImport = null;
    selectedImportFilename = '';
    renderBackupTab();
    toast(archiveUiText(error.message), false);
    return;
  }
  pendingImport = { file, filename };
  selectedImportFilename = filename;
  renderBackupTab();
  await runPendingImport();
}

/* Тело PUT для профиля. Профиль без источников сохранять можно — это единственный
   способ убрать все адреса; автоматический backup при этом принудительно
   выключается, потому что core запрещает расписание без источников. Ручной запуск
   блокируется отдельно — через configured, чтобы случайный клик по «Создать
   backup» не создал бесполезный архив. Экспортируется, чтобы правило проверялось
   без DOM и сети. */
export function profileSaveBody(base, sources) {
  const body = clone(base);
  body.sources = clone(sources || []);
  if (!body.sources.length) body.automatic = { ...body.automatic, enabled: false };
  return body;
}

/* Все server-profile изменения проходят через одну очередь. Элемент хранит только
   задуманную мутацию полей, а полный schema-v1 профиль собирается в момент отправки
   из последнего подтверждённого backend состояния. Поэтому более ранний autosave
   настроек не может затереть более поздний выбор sources и наоборот. */
function staleProfileMutationError() {
  const error = new Error('Изменение относится к уже закрытому профилю.');
  error.stale = true;
  return error;
}

function invalidateProfileSaveQueue() {
  profileSaveGeneration += 1;
  while (profileSaveQueue.length) profileSaveQueue.shift().reject(staleProfileMutationError());
}

function profileMutationBody(base, mutation) {
  if (mutation.kind === 'sources') return profileSaveBody(base, mutation.value);
  const body = clone(base);
  body.automatic = clone(mutation.value.automatic);
  body.limits = clone(mutation.value.limits);
  body.notifications = clone(mutation.value.notifications);
  return body;
}

async function reloadProfileAfterConflict(serverId, generation) {
  if (String(selectedTarget) !== String(serverId) || profileSaveGeneration !== generation) return;
  profileLoading = true;
  renderTabs();
  try {
    const response = await j(`/api/backups/profiles/${encodeURIComponent(serverId)}`);
    if (String(selectedTarget) !== String(serverId) || profileSaveGeneration !== generation) return;
    profile = response.profile || defaultProfile();
    draftSources = clone(profile.sources || []);
  } catch (_) {
    if (String(selectedTarget) !== String(serverId) || profileSaveGeneration !== generation) return;
    profile = null;
    draftSources = [];
  } finally {
    if (String(selectedTarget) === String(serverId) && profileSaveGeneration === generation) {
      profileLoading = false;
      renderTabs();
    }
  }
}

async function pumpProfileSaveQueue() {
  if (profileSaveRunning) return;
  profileSaveRunning = true;
  try {
    while (profileSaveQueue.length) {
      const mutation = profileSaveQueue.shift();
      if (mutation.generation !== profileSaveGeneration
          || String(mutation.serverId) !== String(selectedTarget)) {
        mutation.reject(staleProfileMutationError());
        continue;
      }
      const body = profileMutationBody(profile || defaultProfile(), mutation);
      try {
        const response = await j(`/api/backups/profiles/${encodeURIComponent(mutation.serverId)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profile: body }),
        });
        if (mutation.generation === profileSaveGeneration
            && String(mutation.serverId) === String(selectedTarget)) {
          profile = response.profile || defaultProfile();
          draftSources = clone(profile.sources || []);
          const server = selectedServer();
          if (server) server.configured = draftSources.length > 0;
          if (mutation.kind === 'sources' && activeTab === 'profile') renderProfileTab();
        }
        mutation.resolve(response.profile);
      } catch (error) {
        if (error?.status === 409 && mutation.generation === profileSaveGeneration
            && String(mutation.serverId) === String(selectedTarget)) {
          invalidateProfileSaveQueue();
          const conflictGeneration = profileSaveGeneration;
          error.message = 'Профиль изменился в другом запросе. Данные обновлены; повторите изменение.';
          await reloadProfileAfterConflict(mutation.serverId, conflictGeneration);
        }
        mutation.reject(error);
      }
    }
  } finally {
    profileSaveRunning = false;
    if (profileSaveQueue.length) pumpProfileSaveQueue();
  }
}

function enqueueServerProfileMutation(kind, value) {
  if (selectedTarget === BOT_TARGET) return Promise.reject(new Error('Server profile не выбран.'));
  const mutation = {
    kind,
    value: clone(value),
    serverId: String(selectedTarget),
    generation: profileSaveGeneration,
  };
  const promise = new Promise((resolve, reject) => {
    profileSaveQueue.push({ ...mutation, resolve, reject });
  });
  pumpProfileSaveQueue();
  return promise;
}

function showProfileMutationError(error, prefix = '') {
  if (error?.stale) return;
  const message = error?.message && error.message !== 'Internal Server Error'
    ? archiveUiText(error.message)
    : 'Проверьте права доступа и попробуйте ещё раз';
  toast(prefix ? `${prefix}: ${message}` : message, false);
}

function commitSources(sources) {
  return enqueueServerProfileMutation('sources', sources);
}

/* Тело настроек строим из form.elements (не FormData): коммитящийся контрол на
   момент сборки disabled, а FormData исключает disabled-поля — значение потерялось
   бы. .value/.checked читаются и на disabled-контролах. */
function buildSettingsBase() {
  const form = document.getElementById('backup-settings-form');
  const el = form.elements;
  const base = clone(selectedTarget === BOT_TARGET ? snapshot.bot4vps : (profile || defaultProfile()));
  base.limits.max_archive_bytes = megabytesToBytes(el.max_archive_mb.value);
  base.automatic.enabled = el.automatic_enabled.checked;
  if (base.automatic.enabled) {
    base.automatic.daily_time = String((el.daily_time && el.daily_time.value) || '02:30');
    base.automatic.keep_last = Number((el.keep_last && el.keep_last.value) || 7);
  }
  const readCat = cat => ({
    enabled: el[`notify_${cat}_enabled`].checked,
    success: el[`notify_${cat}_success`].checked,
    error: el[`notify_${cat}_error`].checked,
  });
  base.notifications = { backup: readCat('backup'), restore: readCat('restore') };
  return base;
}

/* Отправка настроек. bot4vps → существующий PATCH, server → полевая мутация в
   общей profile-save queue. Источники к настройкам не приклеиваются заранее: очередь
   возьмёт их из последнего подтверждённого profile непосредственно перед PUT. */
async function commitSettings() {
  const base = buildSettingsBase();
  if (selectedTarget === BOT_TARGET) {
    const response = await j('/api/backups/bot4vps-settings', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: base }),
    });
    snapshot.bot4vps = response.bot4vps;
  } else {
    await enqueueServerProfileMutation('settings', {
      automatic: base.automatic,
      limits: base.limits,
      notifications: base.notifications,
    });
  }
}

const settingsNumberTimers = new Map();

/* Тумблер настроек: оптимистично коммитим, при ошибке возвращаем сам контрол
   (paint() пропустил бы ре-рендер с неизменившейся строкой — откат обязан быть
   на самом input). */
function bindSettingsToggle(input, after) {
  if (!input) return;
  let previous = input.checked;
  input.addEventListener('change', async () => {
    input.disabled = true;
    try {
      await commitSettings();
      previous = input.checked;
    } catch (error) {
      input.checked = previous;
      toast(archiveUiText(error.message), false);
    } finally {
      input.disabled = false;
    }
    if (typeof after === 'function') after();
  });
}

/* Числовое поле настроек с debounce 600мс, валидацией и откатом. nullable —
   пустое значение допустимо (лимит «без ограничений»). */
function bindSettingsNumber(input, key, { nullable = false, min = 1 } = {}) {
  if (!input) return;
  let previous = input.value;
  input.addEventListener('input', () => {
    clearTimeout(settingsNumberTimers.get(key));
    settingsNumberTimers.set(key, setTimeout(async () => {
      const raw = String(input.value).trim();
      if (!(nullable && raw === '')) {
        const value = Number(raw);
        if (!Number.isInteger(value) || value < min) {
          input.value = previous;
          toast(`Допустимо целое число ≥ ${min}${nullable ? ' или пусто' : ''}`, false);
          return;
        }
      }
      input.disabled = true;
      try {
        await commitSettings();
        previous = input.value;
      } catch (error) {
        input.value = previous;
        toast(archiveUiText(error.message), false);
      } finally {
        input.disabled = false;
      }
    }, 600));
  });
}

/* Поля расписания появляются/исчезают вместе с тумблером automatic. Значения
   берём из модели (last-known-good): при откате выключения расписание не должно
   схлопываться до дефолтов и затирать сохранённое время/счётчик. */
function applyAutomaticFields(host, enabled) {
  const fields = host.querySelector('#backup-automatic-fields');
  if (!fields) return;
  if (enabled) {
    if (!fields.children.length) {
      const settings = selectedTarget === BOT_TARGET ? snapshot.bot4vps : (profile || defaultProfile());
      const time = esc(settingsValue(settings, 'automatic', 'daily_time', '02:30'));
      const keep = esc(settingsValue(settings, 'automatic', 'keep_last', 7));
      fields.innerHTML = `<label>Время<input name="daily_time" type="time" value="${time}"></label><label>Хранить последних backup<input name="keep_last" type="number" min="1" value="${keep}"></label>`;
    }
    bindAutomaticFields(host);
  } else {
    fields.innerHTML = '';
  }
}

function bindAutomaticFields(host) {
  const form = document.getElementById('backup-settings-form');
  if (!form) return;
  const daily = form.elements.daily_time;
  if (daily && !daily.dataset.bound) {
    daily.dataset.bound = '1';
    let previous = daily.value;
    daily.addEventListener('change', async () => {
      daily.disabled = true;
      try {
        await commitSettings();
        previous = daily.value;
      } catch (error) {
        daily.value = previous;
        toast(archiveUiText(error.message), false);
      } finally {
        daily.disabled = false;
      }
    });
  }
  const keep = form.elements.keep_last;
  if (keep && !keep.dataset.bound) {
    keep.dataset.bound = '1';
    bindSettingsNumber(keep, 'keep_last', { min: 1 });
  }
}

/* Мастер-тумблер категории уведомлений off → подкатегории игнорируются: в UI их
   делаем неактивными. */
function setCategoryEnabled(host, cat, enabled) {
  host.querySelectorAll(`[name="notify_${cat}_success"], [name="notify_${cat}_error"]`)
    .forEach(input => { input.disabled = !enabled; });
}

function bindSettingsAutosave(host) {
  const form = document.getElementById('backup-settings-form');
  if (!form) return;

  bindSettingsNumber(form.elements.max_archive_mb, 'max_archive_mb', { nullable: true, min: 1 });

  const auto = form.elements.automatic_enabled;
  if (auto) {
    let previous = auto.checked;
    auto.addEventListener('change', async () => {
      // Инвариант core: расписание без источников на сервере запрещено.
      if (auto.checked && selectedTarget !== BOT_TARGET && !draftSources.length) {
        auto.checked = false;
        toast('Автоматический backup без источников включить нельзя — добавьте их во вкладке «Профиль»', false);
        return;
      }
      applyAutomaticFields(host, auto.checked);
      auto.disabled = true;
      try {
        await commitSettings();
        previous = auto.checked;
      } catch (error) {
        auto.checked = previous;
        applyAutomaticFields(host, previous);
        toast(archiveUiText(error.message), false);
      } finally {
        auto.disabled = false;
      }
    });
  }
  bindAutomaticFields(host);

  ['backup', 'restore'].forEach(cat => {
    const master = form.elements[`notify_${cat}_enabled`];
    if (master) {
      let previous = master.checked;
      master.addEventListener('change', async () => {
        setCategoryEnabled(host, cat, master.checked);
        master.disabled = true;
        try {
          await commitSettings();
          previous = master.checked;
        } catch (error) {
          master.checked = previous;
          setCategoryEnabled(host, cat, previous);
          toast(archiveUiText(error.message), false);
        } finally {
          master.disabled = false;
        }
        renderTelegramHealthIndicator();
      });
    }
    ['success', 'error'].forEach(kind => {
      bindSettingsToggle(form.elements[`notify_${cat}_${kind}`], renderTelegramHealthIndicator);
    });
  });
}

function sourcePathIsStrictDescendant(path, parent) {
  return path !== parent && path.startsWith(`${parent}/`);
}

function sourcePickerSelectionState(state, path) {
  const direct = state.selections.has(path);
  let covered = false;
  let hasDescendant = false;
  for (const selectedPath of state.selections.keys()) {
    if (sourcePathIsStrictDescendant(path, selectedPath)) covered = true;
    if (sourcePathIsStrictDescendant(selectedPath, path)) hasDescendant = true;
  }
  return { direct, covered, hasDescendant, checked: direct || covered || hasDescendant };
}

function sourcePickerParentPath(path) {
  const parts = String(path).split('/').filter(Boolean);
  return parts.length <= 1 ? '/' : `/${parts.slice(0, -1).join('/')}`;
}

function sourcePickerPathDepth(path) {
  return Math.max(0, String(path).split('/').filter(Boolean).length - 1);
}

function sourcePickerResponsePath(rawPath, parentPath) {
  const path = String(rawPath || '');
  const components = path.split('/').slice(1);
  if (!path.startsWith('/') || path === '/' || path.endsWith('/')
      || components.some(component => !component || component === '.' || component === '..'
        || component.includes('\\') || [...component].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127))
      || sourcePickerParentPath(path) !== parentPath) {
    throw new Error('Сервер вернул некорректный путь элемента дерева источников.');
  }
  return path;
}

function sourcePickerCurrent(state) {
  return Boolean(
    state
    && state === sourcePickerState
    && state.generation === sourcePickerGeneration
    && String(state.serverId) === String(selectedTarget)
    && document.getElementById('backup-source-picker-modal')?.classList.contains('open')
  );
}

function sourcePickerSortedPaths(state) {
  return [...state.selections.keys()].sort((left, right) => left.localeCompare(right, 'ru'));
}

function sourcePickerAddNode(state, item, parentPath = sourcePickerParentPath(item?.path)) {
  const path = sourcePickerResponsePath(item?.path, parentPath);
  const kind = item?.kind;
  const name = path.split('/').at(-1);
  if (!['directory', 'file'].includes(kind) || item?.selectable !== true
      || item?.name !== name) {
    throw new Error('Сервер вернул некорректный элемент дерева источников.');
  }
  const parentNode = parentPath === '/' ? null : state.nodes.get(parentPath);
  if (parentPath !== '/' && (!parentNode || parentNode.kind !== 'directory')) {
    throw new Error('Сервер вернул элемент без родительского каталога.');
  }
  if (sourcePickerPathDepth(path) >= SOURCE_TREE_MAX_DEPTH) {
    throw new Error(`Достигнут предел глубины дерева (${SOURCE_TREE_MAX_DEPTH}).`);
  }
  let node = state.nodes.get(path);
  if (!node) {
    if (state.nodes.size >= SOURCE_TREE_MAX_NODES) {
      throw new Error(`Достигнут предел элементов дерева (${SOURCE_TREE_MAX_NODES}).`);
    }
    node = {
      path,
      name: String(item.name || path.split('/').filter(Boolean).at(-1) || path),
      kind,
      size: Number(item.size || 0),
      mtime: Number(item.mtime || 0),
      parent: parentPath,
      children: new Set(),
      expanded: false,
      loaded: false,
      loading: false,
      nextCursor: null,
      complete: false,
      error: '',
    };
    state.nodes.set(path, node);
  } else {
    if (node.parent !== parentPath || node.kind !== kind) {
      throw new Error('Сервер вернул противоречивую цепочку пути.');
    }
    node.name = String(item.name || node.name);
    node.size = Number(item.size || 0);
    node.mtime = Number(item.mtime || 0);
  }
  if (parentPath !== '/') state.nodes.get(parentPath).children.add(path);
  return node;
}

function sourcePickerIntegrateChain(state, chain, expectedPath) {
  if (!Array.isArray(chain) || !chain.length || chain.length > SOURCE_TREE_MAX_DEPTH) {
    throw new Error('Сервер вернул некорректную цепочку пути.');
  }
  if (chain.slice(0, -1).some(item => item?.kind !== 'directory')) {
    throw new Error('Сервер вернул файл как родительский каталог.');
  }
  let parent = '/';
  for (const item of chain) {
    const node = sourcePickerAddNode(state, item, parent);
    parent = node.path;
  }
  if (parent !== expectedPath) {
    throw new Error('Сервер вернул цепочку другого пути.');
  }
}

function sourcePickerRequest(state, key, url) {
  if (state.inflight.has(key)) return state.inflight.get(key);
  if (state.requestCount >= SOURCE_TREE_MAX_REQUESTS) {
    return Promise.reject(new Error(`Достигнут предел запросов дерева (${SOURCE_TREE_MAX_REQUESTS}).`));
  }
  state.requestCount += 1;
  const controller = new AbortController();
  state.controllers.add(controller);
  const request = j(url, { signal: controller.signal }).finally(() => {
    state.controllers.delete(controller);
    state.inflight.delete(key);
  });
  state.inflight.set(key, request);
  return request;
}

function sourcePickerTreeUrl(state, path, cursor = 0) {
  return `/api/backups/source-tree/${encodeURIComponent(state.serverId)}`
    + `?path=${encodeURIComponent(path)}&cursor=${encodeURIComponent(cursor)}`
    + `&limit=${SOURCE_TREE_PAGE_LIMIT}`;
}

function sourcePickerLocateUrl(state, path) {
  return `/api/backups/source-tree/${encodeURIComponent(state.serverId)}/locate`
    + `?path=${encodeURIComponent(path)}`;
}

async function loadSourcePickerRoot(state) {
  state.rootLoading = true;
  renderSourcePicker();
  try {
    const data = await sourcePickerRequest(state, 'tree:/#0', sourcePickerTreeUrl(state, '/', 0));
    if (!sourcePickerCurrent(state)) return false;
    if (data?.path !== '/' || data?.complete !== true || data?.truncated === true
        || data?.next_cursor != null || !Array.isArray(data?.items)) {
      throw new Error('Список корневых источников получен не полностью.');
    }
    const roots = [];
    const seenRoots = new Set();
    for (const item of data.items) {
      if (item?.kind !== 'directory' || item?.path === '/') {
        throw new Error('Сервер вернул некорректный корневой источник.');
      }
      const node = sourcePickerAddNode(state, item, '/');
      if (seenRoots.has(node.path)) {
        throw new Error('Сервер вернул повторяющийся корневой источник.');
      }
      seenRoots.add(node.path);
      roots.push(node.path);
      if (state.selections.has(node.path)) {
        state.resolved.add(node.path);
        state.unresolved.delete(node.path);
        state.unresolvedReasons.delete(node.path);
      }
    }
    state.rootPaths = roots;
    state.rootComplete = true;
    state.rootError = '';
    return true;
  } catch (error) {
    if (!sourcePickerCurrent(state) || error?.name === 'AbortError') return false;
    state.rootComplete = false;
    state.rootError = archiveUiText(error.message);
    return false;
  } finally {
    if (sourcePickerCurrent(state)) {
      state.rootLoading = false;
      renderSourcePicker();
    }
  }
}

async function locateSourcePickerPath(state, rawPath, { reveal = true, saved = false } = {}) {
  const path = String(rawPath ?? '');
  if (!path.startsWith('/') || path === '/') {
    if (!saved && sourcePickerCurrent(state)) {
      state.error = path === '/'
        ? 'Корень / служит только для навигации. Выберите один или несколько реальных путей.'
        : 'Укажите точный абсолютный путь источника.';
      renderSourcePicker();
    }
    return false;
  }
  state.locating.add(path);
  renderSourcePicker();
  try {
    const data = await sourcePickerRequest(
      state,
      `locate:${path}`,
      sourcePickerLocateUrl(state, path),
    );
    if (!sourcePickerCurrent(state)) return false;
    const locatedPath = String(data?.path || '');
    const locatedKind = data?.kind;
    if (locatedPath !== path) throw new Error('Сервер вернул найденный путь для другого запроса.');
    if (!['directory', 'file'].includes(locatedKind)) {
      throw new Error('Сервер вернул некорректный тип найденного пути.');
    }
    sourcePickerIntegrateChain(state, data?.chain, path);
    if (!state.nodes.has(path) || state.nodes.get(path).kind !== locatedKind) {
      throw new Error('Сервер не вернул найденный путь.');
    }
    if (state.selections.has(path)) {
      state.resolved.add(path);
      state.unresolved.delete(path);
      state.unresolvedReasons.delete(path);
    }
    if (reveal) {
      for (const item of data.chain.slice(0, -1)) {
        const node = state.nodes.get(item.path);
        if (node?.kind === 'directory') node.expanded = true;
      }
      state.focusPath = locatedPath;
    }
    state.error = '';
    return true;
  } catch (error) {
    if (!sourcePickerCurrent(state) || error?.name === 'AbortError') return false;
    if (saved) {
      state.unresolved.add(path);
      state.unresolvedReasons.set(path, archiveUiText(error.message));
    } else {
      state.error = archiveUiText(error.message);
    }
    return false;
  } finally {
    if (sourcePickerCurrent(state)) {
      state.locating.delete(path);
      renderSourcePicker();
    }
  }
}

async function hydrateSourcePicker(state) {
  try {
    const rootReady = await loadSourcePickerRoot(state);
    if (!sourcePickerCurrent(state) || !rootReady) return;
    const paths = sourcePickerSortedPaths(state).filter(path => !state.resolved.has(path));
    let cursor = 0;
    const workers = Array.from({ length: Math.min(4, paths.length) }, async () => {
      while (cursor < paths.length && sourcePickerCurrent(state)) {
        const path = paths[cursor];
        cursor += 1;
        await locateSourcePickerPath(state, path, { reveal: true, saved: true });
      }
    });
    await Promise.all(workers);
  } finally {
    if (sourcePickerCurrent(state)) {
      state.initializing = false;
      renderSourcePicker();
    }
  }
}

async function loadSourcePickerDirectory(state, path, { more = false } = {}) {
  const node = state.nodes.get(path);
  if (!node || node.kind !== 'directory' || node.loading) return;
  const cursor = more ? node.nextCursor : 0;
  if (more && cursor == null) return;
  if (!more && node.loaded) return;
  node.loading = true;
  node.error = '';
  renderSourcePicker();
  try {
    const key = `tree:${path}#${cursor}`;
    const data = state.pages.get(key)
      || await sourcePickerRequest(state, key, sourcePickerTreeUrl(state, path, cursor));
    if (!sourcePickerCurrent(state)) return;
    if (data?.path !== path || data?.parent !== sourcePickerParentPath(path)
        || !Array.isArray(data?.items) || data.items.length > SOURCE_TREE_PAGE_LIMIT) {
      throw new Error('Сервер вернул страницу другого каталога.');
    }
    const next = data.next_cursor == null ? null : Number(data.next_cursor);
    if (next != null && (!Number.isInteger(next) || next <= Number(cursor))) {
      throw new Error('Сервер вернул некорректный cursor дерева.');
    }
    if (typeof data.complete !== 'boolean' || typeof data.truncated !== 'boolean'
        || data.complete !== (next == null) || data.truncated !== (next != null)) {
      throw new Error('Сервер вернул противоречивое состояние страницы дерева.');
    }
    state.pages.set(key, data);
    const pagePaths = data.items.map(item => String(item?.path || ''));
    if (new Set(pagePaths).size !== pagePaths.length) {
      throw new Error('Сервер вернул повторяющийся элемент страницы дерева.');
    }
    const newPaths = pagePaths.filter(itemPath => !state.nodes.has(itemPath));
    if (state.nodes.size + newPaths.length > SOURCE_TREE_MAX_NODES) {
      throw new Error(`Достигнут предел элементов дерева (${SOURCE_TREE_MAX_NODES}).`);
    }
    for (const item of data.items) sourcePickerAddNode(state, item, path);
    node.loaded = true;
    node.nextCursor = next;
    node.complete = data.complete;
  } catch (error) {
    if (!sourcePickerCurrent(state) || error?.name === 'AbortError') return;
    node.error = archiveUiText(error.message);
  } finally {
    if (sourcePickerCurrent(state)) {
      node.loading = false;
      renderSourcePicker();
    }
  }
}

function sourcePickerNodeMarkup(state, node, depth, budget) {
  if (!node || budget.count >= SOURCE_TREE_MAX_RENDERED_ROWS) return '';
  budget.count += 1;
  const selection = sourcePickerSelectionState(state, node.path);
  const disabled = selection.covered || state.applying;
  const status = selection.direct
    ? 'выбран'
    : selection.covered ? 'входит в выбранный каталог'
      : selection.hasDescendant ? 'есть выбранные вложенные пути' : '';
  const directory = node.kind === 'directory';
  const toggle = directory
    ? `<button type="button" class="backup-source-tree-toggle" data-source-tree-toggle="${esc(node.path)}" aria-expanded="${node.expanded ? 'true' : 'false'}" aria-label="${node.expanded ? 'Свернуть' : 'Развернуть'} ${esc(node.path)}">${node.expanded ? '▾' : '▸'}</button>`
    : '<span class="backup-source-tree-toggle-spacer"></span>';
  const row = `<div class="backup-source-tree-row${state.focusPath === node.path ? ' focused' : ''}${selection.direct ? ' direct' : ''}${selection.covered ? ' covered' : ''}" style="--source-tree-depth:${depth}" data-source-tree-row="${esc(node.path)}">
    ${toggle}<label class="backup-source-tree-choice" title="${esc(status)}"><input type="checkbox" data-source-tree-check="${esc(node.path)}" ${selection.checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}> <span class="backup-source-tree-icon" aria-hidden="true">${directory ? '📁' : '📄'}</span><span class="backup-source-tree-name">${esc(node.name)}</span></label>${status ? `<small>${esc(status)}</small>` : ''}
  </div>`;
  if (!directory || !node.expanded) return row;
  const children = [...node.children]
    .map(childPath => state.nodes.get(childPath))
    .filter(Boolean)
    .sort((left, right) => Number(left.kind !== 'directory') - Number(right.kind !== 'directory')
      || left.name.localeCompare(right.name, 'ru', { sensitivity: 'base' }));
  const childRows = children.map(child => sourcePickerNodeMarkup(state, child, depth + 1, budget)).join('');
  const loading = node.loading ? '<div class="backup-source-tree-note">Загрузка…</div>' : '';
  const error = node.error ? `<div class="backup-source-tree-note error">${esc(node.error)}</div>` : '';
  const more = node.loaded && !node.complete && node.nextCursor != null
    ? `<button type="button" class="secondary backup-source-tree-more" data-source-tree-more="${esc(node.path)}" ${node.loading || state.applying ? 'disabled' : ''}>Показать ещё</button>` : '';
  const empty = node.loaded && node.complete && !children.length
    ? '<div class="backup-source-tree-note">Каталог пуст</div>' : '';
  return row + childRows + loading + error + more + empty;
}

function sourcePickerTreeMarkup(state) {
  if (state.rootLoading && !state.rootPaths.length) return '<div class="empty">Загрузка корневых каталогов…</div>';
  if (state.rootError && !state.rootPaths.length) return `<div class="empty">${esc(state.rootError)}</div>`;
  const budget = { count: 0 };
  const roots = state.rootPaths
    .map(path => state.nodes.get(path))
    .filter(Boolean)
    .sort((left, right) => left.name.localeCompare(right.name, 'ru', { sensitivity: 'base' }));
  const rows = roots.map(node => sourcePickerNodeMarkup(state, node, 0, budget)).join('');
  const limited = budget.count >= SOURCE_TREE_MAX_RENDERED_ROWS
    ? `<div class="backup-source-tree-limit">Показаны первые ${SOURCE_TREE_MAX_RENDERED_ROWS} строк. Сверните ветки.</div>` : '';
  return rows + limited || '<div class="empty">Разрешённые источники не найдены.</div>';
}

function renderSourcePicker() {
  const state = sourcePickerState;
  if (!sourcePickerCurrent(state)) return;
  const tree = document.getElementById('backup-source-tree');
  const selected = document.getElementById('backup-source-picker-selected');
  const count = document.getElementById('backup-source-picker-count');
  const error = document.getElementById('backup-source-picker-error');
  paint(tree, sourcePickerTreeMarkup(state));
  const selectedPaths = sourcePickerSortedPaths(state);
  paint(selected, selectedPaths.length ? selectedPaths.map(path => {
    const unresolved = state.unresolved.has(path);
    const reason = state.unresolvedReasons.get(path) || 'Путь пока не удалось проверить.';
    return `<div class="backup-source-picker-selected-row${unresolved ? ' unresolved' : ''}">
      <div><code>${esc(path)}</code><small>${unresolved ? `<span title="${esc(reason)}">Недоступен при загрузке</span> · ` : ''}Исключений: ${state.selections.get(path)?.length || 0}</small></div>
      <button type="button" class="secondary" data-picker-exclusions="${esc(path)}" title="Исключения" ${state.applying ? 'disabled' : ''}>⚙</button>
      <button type="button" class="secondary" data-picker-remove="${esc(path)}" title="Убрать источник" ${state.applying ? 'disabled' : ''}>×</button>
    </div>`;
  }).join('') : '<div class="empty">Источники не выбраны</div>');
  if (count) count.textContent = `Выбрано источников: ${selectedPaths.length}`;
  if (error) error.textContent = state.error || state.rootError || '';
  const selectAll = document.getElementById('backup-source-picker-select-all');
  if (selectAll) selectAll.disabled = !state.rootComplete || state.initializing || state.applying;
  const clearAll = document.getElementById('backup-source-picker-clear-all');
  if (clearAll) clearAll.disabled = state.initializing || state.applying || selectedPaths.length === 0;
  const apply = document.getElementById('backup-source-picker-apply');
  if (apply) {
    apply.disabled = state.initializing || state.applying;
    apply.textContent = state.applying ? 'Сохранение…' : 'Применить';
  }
  const cancel = document.getElementById('backup-source-picker-cancel');
  if (cancel) cancel.disabled = state.applying;
  tree?.setAttribute('aria-busy', String(state.rootLoading || state.locating.size > 0));
}

function openSourcePicker() {
  if (selectedTarget === BOT_TARGET || profileSourceMutationPending || sourcePickerState?.applying) return;
  closeSourcePicker();
  const generation = ++sourcePickerGeneration;
  const selections = new Map(
    draftSources.map(source => [String(source.path), clone(source.exclusions || [])]),
  );
  sourcePickerState = {
    generation,
    serverId: String(selectedTarget),
    selections,
    nodes: new Map(),
    rootPaths: [],
    rootComplete: false,
    rootLoading: false,
    rootError: '',
    resolved: new Set(),
    unresolved: new Set(selections.keys()),
    unresolvedReasons: new Map(),
    pages: new Map(),
    inflight: new Map(),
    controllers: new Set(),
    locating: new Set(),
    requestCount: 0,
    focusPath: null,
    initializing: true,
    applying: false,
    error: '',
  };
  document.getElementById('backup-source-picker-modal')?.classList.add('open');
  renderSourcePicker();
  hydrateSourcePicker(sourcePickerState);
}

function closeSourcePicker({ force = false } = {}) {
  const state = sourcePickerState;
  if (state?.applying && !force) return;
  if (state) {
    state.controllers.forEach(controller => controller.abort());
    state.controllers.clear();
  }
  sourcePickerGeneration += 1;
  sourcePickerState = null;
  document.getElementById('backup-source-picker-modal')?.classList.remove('open');
}

function updateSourcePickerSelection(path) {
  const state = sourcePickerState;
  if (!sourcePickerCurrent(state) || state.applying) return;
  const selection = sourcePickerSelectionState(state, path);
  if (selection.covered) return;
  if (selection.direct) {
    state.selections.delete(path);
  } else {
    const exclusions = state.selections.get(path) || [];
    for (const selectedPath of [...state.selections.keys()]) {
      if (sourcePathIsStrictDescendant(selectedPath, path)) state.selections.delete(selectedPath);
    }
    state.selections.set(path, exclusions);
    state.resolved.add(path);
    state.unresolved.delete(path);
    state.unresolvedReasons.delete(path);
  }
  state.error = '';
  renderSourcePicker();
}

function selectAllSourcePickerRoots() {
  const state = sourcePickerState;
  if (!sourcePickerCurrent(state) || !state.rootComplete || state.initializing || state.applying) return;
  const selected = new Map();
  for (const path of state.rootPaths) selected.set(path, clone(state.selections.get(path) || []));
  state.selections = selected;
  state.resolved = new Set(state.rootPaths);
  state.unresolved.clear();
  state.unresolvedReasons.clear();
  state.error = '';
  renderSourcePicker();
}

function clearAllSourcePickerSelections() {
  const state = sourcePickerState;
  if (!sourcePickerCurrent(state) || state.initializing || state.applying) return;
  state.selections.clear();
  state.resolved.clear();
  state.unresolved.clear();
  state.unresolvedReasons.clear();
  state.error = '';
  state.focusPath = null;
  renderSourcePicker();
}

async function applySourcePicker() {
  const state = sourcePickerState;
  if (!sourcePickerCurrent(state) || state.initializing || state.applying) return;
  const sources = sourcePickerSortedPaths(state).map(path => ({
    path,
    exclusions: clone(state.selections.get(path) || []),
  }));
  state.applying = true;
  state.error = '';
  renderSourcePicker();
  try {
    await commitSources(sources);
    if (sourcePickerCurrent(state)) closeSourcePicker({ force: true });
  } catch (error) {
    if (!sourcePickerCurrent(state)) return;
    state.applying = false;
    state.error = error?.stale
      ? ''
      : (error?.message && error.message !== 'Internal Server Error'
        ? archiveUiText(error.message) : 'Проверьте права доступа и попробуйте ещё раз');
    renderSourcePicker();
  }
}

function exclusionSource(scope, path) {
  if (scope === 'picker') {
    const exclusions = sourcePickerState?.selections.get(path);
    return exclusions ? { path, exclusions } : null;
  }
  return draftSources.find(source => source.path === path) || null;
}

function openExclusions(path, scope = 'profile') {
  const source = exclusionSource(scope, path);
  if (!source || (scope === 'profile' && profileSourceMutationPending)) return;
  exclusionSourcePath = path;
  exclusionScope = scope;
  document.getElementById('backup-exclusions-source').textContent = source.path;
  document.getElementById('backup-exclusions-input').value = (source.exclusions || []).join('\n');
  document.getElementById('backup-exclusions-apply').disabled = false;
  document.getElementById('backup-exclusions-modal').classList.add('open');
}

function closeExclusions() {
  document.getElementById('backup-exclusions-modal')?.classList.remove('open');
  exclusionSourcePath = null;
  exclusionScope = null;
}

async function applyExclusions() {
  const path = exclusionSourcePath;
  const scope = exclusionScope;
  if (!path || !scope) return;
  const exclusions = document.getElementById('backup-exclusions-input').value
    .split('\n').map(value => value.trim()).filter(Boolean);
  if (scope === 'picker') {
    const state = sourcePickerState;
    if (!sourcePickerCurrent(state) || !state.selections.has(path)) {
      closeExclusions();
      return;
    }
    state.selections.set(path, exclusions);
    closeExclusions();
    renderSourcePicker();
    return;
  }
  if (profileSourceMutationPending) return;
  const next = draftSources.map(source => source.path === path
    ? { path: source.path, exclusions }
    : clone(source));
  profileSourceMutationPending = true;
  document.getElementById('backup-exclusions-apply').disabled = true;
  renderProfileTab();
  try {
    await commitSources(next);
    closeExclusions();
  } catch (error) {
    showProfileMutationError(error, 'Не удалось сохранить исключения');
  } finally {
    profileSourceMutationPending = false;
    document.getElementById('backup-exclusions-apply').disabled = false;
    renderProfileTab();
  }
}

async function removeProfileSource(path) {
  if (profileSourceMutationPending) return;
  const next = draftSources.filter(source => source.path !== path).map(clone);
  if (next.length === draftSources.length) return;
  profileSourceMutationPending = true;
  renderProfileTab();
  try {
    await commitSources(next);
  } catch (error) {
    showProfileMutationError(error, 'Не удалось удалить источник');
  } finally {
    profileSourceMutationPending = false;
    renderProfileTab();
  }
}

async function handleTabBodyClick(event) {
  const create = event.target.closest('[data-create-backup]');
  if (create) { createBackup(); return; }
  if (event.target.closest('[data-import-backup]')) {
    document.getElementById('backup-import-file')?.click();
    return;
  }
  if (event.target.closest('[data-go-profile]')) {
    changeBackupTab('profile', { reloadProfile: true });
    return;
  }
  if (event.target.closest('[data-restore-mode]')) {
    if (restoreMode) {
      cancelRestoreStart();
      return;
    }
    restoreMode = true;
    selectedBackupId = null;
    selectedArchiveKey = null;
    importedRestoreSelection = null;
    importedRestoreSelectionRevision += 1;
    closePreviewModal();
    renderBackupTab();
    renderHistory();
    return;
  }
  if (event.target.closest('[data-restore-continue]')) { openRestoreModal(); return; }
  const archiveAction = event.target.closest('[data-archive-action]');
  const archiveRow = event.target.closest('[data-backup-id], [data-imported-key]');
  if (archiveAction && archiveRow) {
    const action = archiveAction.dataset.archiveAction;
    if (archiveRow.dataset.importedKey) {
      const key = archiveRow.dataset.importedKey;
      if (action === 'preview') previewImported(key);
      if (action === 'rename') renameImported(key);
      if (action === 'delete') removeImported(key);
    } else {
      const id = archiveRow.dataset.backupId;
      if (action === 'preview') preview(id);
      if (action === 'rename') renameManaged(id);
      if (action === 'delete') remove(id);
    }
    return;
  }
  if (archiveRow && restoreMode && archiveRow.dataset.importedKey) {
    await selectImportedForRestore(archiveRow.dataset.importedKey);
    return;
  }
  if (archiveRow && restoreMode && archiveRow.dataset.backupId) {
    // Повторный клик по выбранной строке снимает выбор: тогда «Продолжить»
    // исчезает из панели действий, и случайно выбранный архив не остаётся
    // выбранным до переключения цели.
    const clicked = archiveRow.dataset.backupId;
    selectedBackupId = selectedBackupId === clicked ? null : clicked;
    selectedArchiveKey = null;
    importedRestoreSelection = null;
    importedRestoreSelectionRevision += 1;
    closePreviewModal();
    renderBackupTab();
    return;
  }
  const exclusions = event.target.closest('[data-source-exclusions]');
  if (exclusions) { openExclusions(exclusions.dataset.sourceExclusions, 'profile'); return; }
  const removeSource = event.target.closest('[data-source-remove]');
  if (removeSource) { removeProfileSource(removeSource.dataset.sourceRemove); return; }
  if (event.target.closest('[data-add-source]')) { openSourcePicker(); return; }
  const gear = event.target.closest('[data-notify-gear]');
  if (gear) {
    document.getElementById(`backup-notify-modal-${gear.dataset.notifyGear}`)?.classList.add('open');
    return;
  }
  if (event.target.closest('[data-notify-close]')) {
    event.target.closest('.backup-notification-modal')?.classList.remove('open');
    return;
  }
  // Клик по фону модалки уведомлений закрывает её.
  if (event.target.classList?.contains('backup-notification-modal')) {
    event.target.classList.remove('open');
    return;
  }
  if (event.target.closest('[data-telegram-health-warning]')) { openTelegramHealthWarning(); return; }
}

export function bindBackupUI() {
  document.getElementById('backup-target-list')?.addEventListener('click', event => {
    const row = event.target.closest('[data-backup-target]');
    if (row) selectTarget(row.dataset.backupTarget);
  });
  document.querySelectorAll('[data-backup-tab]').forEach(button => button.addEventListener('click', () => {
    changeBackupTab(button.dataset.backupTab);
  }));
  document.getElementById('backup-operations')?.addEventListener('click', event => {
    const button = event.target.closest('[data-cancel-op]');
    if (button) cancelOperation(button.dataset.cancelOp);
  });
  document.getElementById('backup-tab-body')?.addEventListener('click', handleTabBodyClick);
  document.getElementById('backup-history')?.addEventListener('click', handleHistoryClick);
  document.getElementById('backup-tab-body')?.addEventListener('change', event => {
    if (event.target.id !== 'backup-import-file') return;
    const file = event.target.files?.[0];
    if (file) importFile(file);
    event.target.value = '';
  });
  document.getElementById('backup-source-tree')?.addEventListener('click', event => {
    const state = sourcePickerState;
    if (!sourcePickerCurrent(state) || state.applying) return;
    const more = event.target.closest('[data-source-tree-more]');
    if (more) {
      loadSourcePickerDirectory(state, more.dataset.sourceTreeMore, { more: true });
      return;
    }
    const toggle = event.target.closest('[data-source-tree-toggle]');
    if (!toggle) return;
    const node = state.nodes.get(toggle.dataset.sourceTreeToggle);
    if (!node || node.kind !== 'directory') return;
    node.expanded = !node.expanded;
    renderSourcePicker();
    if (node.expanded && !node.loaded) loadSourcePickerDirectory(state, node.path);
  });
  document.getElementById('backup-source-tree')?.addEventListener('change', event => {
    const checkbox = event.target.closest('[data-source-tree-check]');
    if (checkbox) updateSourcePickerSelection(checkbox.dataset.sourceTreeCheck);
  });
  document.getElementById('backup-source-picker-selected')?.addEventListener('click', event => {
    const state = sourcePickerState;
    if (!sourcePickerCurrent(state) || state.applying) return;
    const exclusions = event.target.closest('[data-picker-exclusions]');
    if (exclusions) {
      openExclusions(exclusions.dataset.pickerExclusions, 'picker');
      return;
    }
    const remove = event.target.closest('[data-picker-remove]');
    if (!remove) return;
    const path = remove.dataset.pickerRemove;
    state.selections.delete(path);
    state.unresolved.delete(path);
    state.unresolvedReasons.delete(path);
    renderSourcePicker();
  });
  document.getElementById('backup-source-picker-clear-all')?.addEventListener('click', clearAllSourcePickerSelections);
  document.getElementById('backup-source-picker-select-all')?.addEventListener('click', selectAllSourcePickerRoots);
  document.getElementById('backup-source-picker-apply')?.addEventListener('click', applySourcePicker);
  document.getElementById('backup-source-picker-cancel')?.addEventListener('click', closeSourcePicker);
  document.getElementById('backup-exclusions-apply')?.addEventListener('click', applyExclusions);
  document.getElementById('backup-exclusions-cancel')?.addEventListener('click', closeExclusions);
  document.getElementById('backup-preview-close')?.addEventListener('click', closePreviewModal);
  document.getElementById('backup-preview-refresh')?.addEventListener('click', refreshPreviewModal);
  document.getElementById('backup-preview-inventory-action')?.addEventListener(
    'click',
    runPreviewInventoryAction,
  );
  document.getElementById('backup-preview-modal')?.addEventListener('click', handlePreviewModalClick);
  document.getElementById('backup-restore-submit')?.addEventListener('click', submitRestore);
  document.getElementById('backup-restore-cancel')?.addEventListener('click', cancelRestore);
  document.getElementById('backup-restore-abort')?.addEventListener('click', abortRestore);
  // Клик по фону Restore-диалог не закрывает: шаг мастера слишком значим,
  // чтобы терять его случайным промахом мимо окна.
  document.getElementById('backup-restore-modal')?.addEventListener('click', handleRestoreModalClick);
  document.getElementById('backup-restore-modal')?.addEventListener('change', handleRestoreModalChange);
  document.getElementById('backup-restore-modal')?.addEventListener('input', handleRestoreModalChange);
  document.getElementById('backup-rename-save')?.addEventListener('click', submitRename);
  document.getElementById('backup-rename-cancel')?.addEventListener('click', closeRenameModal);
  document.getElementById('backup-rename-input')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') submitRename();
  });
  document.getElementById('backup-import-rename')?.addEventListener('click', chooseImportRename);
  document.getElementById('backup-import-replace')?.addEventListener('click', replaceImport);
  document.getElementById('backup-import-cancel')?.addEventListener('click', cancelImportConflict);
  document.getElementById('backup-import-conflict-modal')?.addEventListener('click', event => {
    if (event.target.id === 'backup-import-conflict-modal') cancelImportConflict();
  });
  ['backup-source-picker-modal', 'backup-exclusions-modal'].forEach(id => {
    document.getElementById(id)?.addEventListener('click', event => {
      if (event.target.id === id) id === 'backup-source-picker-modal' ? closeSourcePicker() : closeExclusions();
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    // Флаг снимается уже после этого события (resolve промиса — микротаска),
    // поэтому здесь он ещё поднят: Escape достаётся только подтверждению.
    if (restoreConfirm) return;
    closeSourcePicker();
    closeExclusions();
    closePreviewModal();
    closeRenameModal();
    cancelRestoreStart();
    cancelImportConflict();
    document.querySelectorAll('.backup-notification-modal.open').forEach(modal => modal.classList.remove('open'));
  });
  window.addEventListener('bot4vps:telegram-health', event => {
    if (!event.detail?.applies_to_saved_config) return;
    setTelegramHealth(event.detail);
    renderTelegramHealthIndicator();
  });
  window.addEventListener('resize', scheduleGeometry);
  // Диагностика: console.log(window.__backupGeometry()) отдаёт фактические
  // clientHeight/scrollHeight списков и rendered geometry Create/Import.
  window.__backupGeometry = geometryReport;
}
