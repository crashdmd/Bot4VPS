import { j, esc, errorHtml } from './api.js';
import {
  toast, formatServerDateTime, formatServerTime, panelCalendarToday, panelDateRangeWindow,
  serverNow, infoModal,
} from './ui.js';
import { openTaskLog } from './tasks.js?v=20261001-handbook-v3';
import { openEventDetail } from './monitor.js?v=20261001-mobile-charts-v1';
import { state } from './state.js';

const PAGE_LIMIT = 50;
const RANGES = { '24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400, '90d': 90 * 86400 };
const RESULT_CLASS = {
  ok: 'on',
  failed: 'off',
  cancelled: 'unk',
  awaiting_rule_selection: 'warn',
  incomplete: 'warn',
  started: 'unk',
};
const RESULT_TEXT = {
  ok: 'успешно',
  failed: 'ошибка',
  cancelled: 'отменено',
  awaiting_rule_selection: 'Ожидается выбор правил',
  incomplete: 'Нет записи о завершении',
  started: 'начато',
};

let facetsLoaded = false;
let nextCursor = null;
let loading = false;
let hasAppended = false;
let auditReloadTimer = null;
let newAbove = false;
let openedBy = { openMetricsAt: null };

function nowSeconds() {
  return Math.floor(serverNow().getTime() / 1000);
}

function filters() {
  if (!state.auditFilters) {
    state.auditFilters = {
      range: '7d', dateFrom: '', dateTo: '', actor: '', action: '', server: '', result: '', q: '',
    };
  }
  return state.auditFilters;
}

function dateInput() {
  return document.getElementById('audit-date');
}

function dateToInput() {
  return document.getElementById('audit-date-to');
}

function customPeriodPanel() {
  return document.getElementById('audit-custom-period');
}

function syncDateInputLimits() {
  const max = panelCalendarToday();
  for (const input of [dateInput(), dateToInput()]) {
    if (input) input.max = max;
  }
}

function setCustomPeriodUI(range, { focus = false } = {}) {
  const custom = range === 'custom';
  const panel = customPeriodPanel();
  if (panel) panel.hidden = !custom;
  if (custom && focus) dateInput()?.focus();
}

function clearDateInputs() {
  const f = filters();
  f.dateFrom = '';
  f.dateTo = '';
  if (dateInput()) dateInput().value = '';
  if (dateToInput()) dateToInput().value = '';
  syncDateInputLimits();
}

function customWindow() {
  const f = filters();
  if (f.range !== 'custom' || !f.dateFrom) return null;
  return panelDateRangeWindow(f.dateFrom, f.dateTo);
}

function applyCustomDates() {
  const f = filters();
  const fromValue = dateInput()?.value || '';
  const toValue = dateToInput()?.value || '';
  if (!fromValue) {
    f.dateFrom = '';
    f.dateTo = '';
    if (toValue && dateToInput()) dateToInput().value = '';
    loadAudit();
    return;
  }
  const window = panelDateRangeWindow(fromValue, toValue);
  if (!window) {
    toast('Эта дата ещё не наступила — данных за неё нет', false);
    syncDateInputLimits();
    return;
  }
  f.range = 'custom';
  f.dateFrom = window.start.value;
  f.dateTo = window.hasEnd ? window.end.value : '';
  if (dateInput()) dateInput().value = f.dateFrom;
  if (dateToInput()) dateToInput().value = f.dateTo;
  syncFiltersToUI();
  loadAudit();
}

export function bindAuditUI(handlers = {}) {
  openedBy = { ...openedBy, ...handlers };
  document.getElementById('audit-list')?.addEventListener('click', event => {
    const row = event.target.closest('.audit-row');
    if (row) toggleRecord(row);
  });
  const q = document.getElementById('audit-q');
  let qTimer = null;
  q?.addEventListener('input', () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(applyFiltersFromUI, 350);
  });
  document.getElementById('audit-range')?.addEventListener('change', () => {
    const range = document.getElementById('audit-range')?.value || '7d';
    if (range === 'custom') {
      filters().range = 'custom';
      setCustomPeriodUI('custom', { focus: true });
      return;
    }
    clearDateInputs();
    applyFiltersFromUI();
  });
  dateInput()?.addEventListener('change', applyCustomDates);
  dateToInput()?.addEventListener('change', applyCustomDates);
  ['audit-actor', 'audit-action', 'audit-server', 'audit-result'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', applyFiltersFromUI);
  });
  document.getElementById('audit-more')?.addEventListener('click', () => loadAudit({ append: true }));
  document.getElementById('audit-reset')?.addEventListener('click', () => {
    state.auditFilters = {
      range: '7d', dateFrom: '', dateTo: '', actor: '', action: '', server: '', result: '', q: '',
    };
    syncFiltersToUI();
    loadAudit();
  });
  syncDateInputLimits();
}

function applyFiltersFromUI() {
  const f = filters();
  f.actor = document.getElementById('audit-actor')?.value || '';
  f.action = document.getElementById('audit-action')?.value || '';
  f.server = document.getElementById('audit-server')?.value || '';
  f.result = document.getElementById('audit-result')?.value || '';
  f.range = document.getElementById('audit-range')?.value || '7d';
  f.q = document.getElementById('audit-q')?.value || '';
  if (f.range !== 'custom') clearDateInputs();
  setCustomPeriodUI(f.range);
  loadAudit();
}

function syncFiltersToUI() {
  const f = filters();
  const range = document.getElementById('audit-range');
  if (range) range.value = RANGES[f.range] || f.range === 'custom' ? f.range : '7d';
  const q = document.getElementById('audit-q');
  if (q) q.value = f.q || '';
  if (dateInput()) dateInput().value = f.dateFrom || '';
  if (dateToInput()) dateToInput().value = f.dateTo || '';
  for (const [id, value] of [
    ['audit-actor', f.actor], ['audit-action', f.action],
    ['audit-server', f.server], ['audit-result', f.result],
  ]) {
    const el = document.getElementById(id);
    if (el) el.value = value || '';
  }
  setCustomPeriodUI(f.range);
  syncDateInputLimits();
}

async function ensureFacets(force = false) {
  if (facetsLoaded && !force) {
    syncFiltersToUI();
    return;
  }
  let data;
  try {
    data = await j('/api/audit/facets');
  } catch (e) {
    toast(`Фильтры недоступны: ${e.message}`, false);
    return;
  }
  const fill = (id, empty, items, value, label) => {
    const el = document.getElementById(id);
    if (!el) return;
    const current = el.value;
    el.innerHTML = `<option value="">${esc(empty)}</option>`
      + items.map(item => `<option value="${esc(value(item))}">${esc(label(item))}</option>`).join('');
    const desired = current || filters()[id.replace('audit-', '')] || '';
    if (desired && !items.some(item => String(value(item)) === String(desired))) {
      el.insertAdjacentHTML('beforeend', `<option value="${esc(desired)}">${esc(desired)}</option>`);
    }
    el.value = desired;
  };
  fill('audit-actor', 'Все', data.actors || [],
    item => item.id ? `${item.type}:${item.id}` : item.type,
    item => `${item.label || item.id || item.type} · ${item.count}`);
  fill('audit-action', 'Все', data.actions || [],
    item => item.code,
    item => `${item.title || item.code} · ${item.count}`);
  fillServerFacets(data.servers || []);
  fill('audit-result', 'Любой', data.results || [],
    item => item.value,
    item => `${item.title || item.value} · ${item.count}`);
  facetsLoaded = true;
  syncFiltersToUI();
}

function fillServerFacets(items) {
  const el = document.getElementById('audit-server');
  if (!el) return;
  const current = [];
  const historical = [];
  const currentIds = new Set(state.servers.map(server => String(server.id)));
  for (const item of items) {
    if (!item?.id) continue;
    (currentIds.has(String(item.id)) ? current : historical).push(item);
  }
  const option = (item, includeId) => {
    const id = String(item.id);
    const name = String(item.name || '').trim();
    const title = includeId && name ? `${name} · ${id}` : (name || id);
    return `<option value="${esc(id)}">${esc(title)} · ${esc(item.count)}</option>`;
  };
  const group = (title, values, includeId) => values.length
    ? `<optgroup label="${esc(title)}">${values.map(item => option(item, includeId)).join('')}</optgroup>`
    : '';
  const desired = el.value || filters().server || '';
  el.innerHTML = '<option value="">Все</option>'
    + group('Текущие серверы', current, false)
    + group('Исторические или удалённые', historical, true);
  if (desired && !items.some(item => String(item?.id) === String(desired))) {
    el.insertAdjacentHTML('beforeend', `<option value="${esc(desired)}">${esc(desired)}</option>`);
  }
  el.value = desired;
}

function queryString(cursor) {
  const f = filters();
  const window = customWindow();
  const span = RANGES[f.range] || RANGES['7d'];
  const now = nowSeconds();
  const params = new URLSearchParams();
  params.set('from', String(window ? window.from : now - span));
  params.set('to', String(window ? window.to : now));
  params.set('limit', String(PAGE_LIMIT));
  if (f.actor) {
    const [type, ...rest] = String(f.actor).split(':');
    params.set('actor_type', type);
    const id = rest.join(':');
    if (id) params.set('actor_id', id);
  }
  if (f.action) params.set('action', f.action);
  if (f.server) params.set('server_id', f.server);
  if (f.result) params.set('result', f.result);
  if (f.q) params.set('q', f.q);
  if (cursor) params.set('cursor', cursor);
  return params.toString();
}

export async function loadAudit({ append = false } = {}) {
  if (loading) return;
  loading = true;
  await ensureFacets();
  const list = document.getElementById('audit-list');
  if (list && !append) list.innerHTML = '<div class="empty">Загрузка…</div>';
  let data;
  try {
    data = await j(`/api/audit?${queryString(append ? nextCursor : null)}`);
  } catch (e) {
    if (list && !append) list.innerHTML = `<div class="empty">Не удалось прочитать журнал: ${errorHtml(e)}</div>`;
    loading = false;
    return;
  }
  loading = false;
  nextCursor = data.next_cursor || null;
  if (!append) {
    hasAppended = false;
    newAbove = false;
  } else {
    hasAppended = true;
  }
  renderRecords(data.items || [], { append });
  const more = document.getElementById('audit-more');
  if (more) {
    if (nextCursor) more.removeAttribute('hidden');
    else more.setAttribute('hidden', '');
  }
  const reset = document.getElementById('audit-reset');
  if (reset) reset.hidden = !isFiltered();
  state.auditFilters = filters();
}

function isFiltered() {
  const f = filters();
  return !!(f.actor || f.action || f.server || f.result || f.q || f.range !== '7d');
}

function renderRecords(items, { append }) {
  const list = document.getElementById('audit-list');
  if (!list) return;
  if (!items.length && !append) {
    list.innerHTML = `<div class="empty">${isFiltered()
      ? 'За этими условиями операций нет. Снимите фильтр или расширьте период.'
      : 'Журнал пуст: действий пока не было.'}</div>`;
    document.getElementById('audit-count').textContent = '';
    return;
  }
  const html = items.map(renderRecord).join('');
  if (append) list.insertAdjacentHTML('beforeend', html);
  else list.innerHTML = html;
  countRecords();
}

function countRecords() {
  const count = document.getElementById('audit-count');
  if (!count) return;
  const shown = document.querySelectorAll('#audit-list .audit-row').length;
  count.textContent = `Показано операций: ${shown}${nextCursor ? ' (есть ещё)' : ''}${newAbove ? ' · выше есть обновления' : ''}`;
}

function durationText(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return '';
  if (total < 60) return `${Math.floor(total)} с`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours} ч${rest ? ` ${rest} мин` : ''}`;
}

function operationResult(item) {
  if (item?.status === 'incomplete') return 'incomplete';
  if (item?.status === 'waiting_rule_selection') return 'awaiting_rule_selection';
  return item?.result;
}

function endState(item) {
  if (item?.status === 'waiting_rule_selection') {
    return { label: 'Состояние', value: 'Ожидается выбор правил' };
  }
  return {
    label: 'Завершение',
    value: item?.ended_at == null
      ? 'Нет записи о завершении'
      : esc(formatServerDateTime(item.ended_at)),
  };
}

function resultText(result) {
  return RESULT_TEXT[result] || result || '—';
}

function renderRecord(item) {
  const actor = item.actor || {};
  const actorText = actor.id ? `${actor.type}: ${actor.id}` : (actor.type || 'система');
  const result = operationResult(item);
  const attach = item.attachments || {};
  const badges = [];
  if (attach.event) badges.push('событие');
  if (attach.task) badges.push('задача');
  const started = Number(item.started_at ?? item.ts);
  const end = endState(item);
  const duration = durationText(item.duration_seconds);
  const meta = [
    `<span>${esc(actorText)}${actor.role ? ` · ${esc(actor.role)}` : ''}</span>`,
    item.server ? `<span>${esc(item.server.name || item.server.id)}</span>` : '',
    badges.length ? `<span>${esc(badges.join(' · '))}</span>` : '',
  ].filter(Boolean).join('');
  return `
    <button type="button" class="audit-row" data-record-id="${esc(item.id)}" data-operation-id="${esc(item.operation_id || '')}">
      <span class="audit-operation">
        <span class="audit-title">${esc(item.title || item.action)}</span>
        <span class="audit-meta">${meta}${item.error ? ` · <span class="audit-error">${esc(item.error)}</span>` : ''}</span>
      </span>
      <span class="audit-interval">
        <span class="audit-time"><span>Начало</span>${esc(formatServerDateTime(started))}</span>
        <span class="audit-time"><span>${end.label}</span>${end.value}</span>
        ${duration ? `<span class="audit-duration">Длительность ${esc(duration)}</span>` : ''}
      </span>
      <span class="audit-result"><span class="badge ${RESULT_CLASS[result] || 'unk'}"><span class="dot"></span>${esc(resultText(result))}</span></span>
    </button>`;
}

async function toggleRecord(row) {
  const id = row.dataset.recordId;
  const existing = row.nextElementSibling;
  if (existing?.classList?.contains('audit-detail')) {
    existing.remove();
    row.classList.remove('is-open');
    if (state.auditRecordId === id) state.auditRecordId = null;
    return;
  }
  document.querySelectorAll('#audit-list .audit-detail').forEach(detail => detail.remove());
  document.querySelectorAll('#audit-list .audit-row.is-open').forEach(open => open.classList.remove('is-open'));
  row.classList.add('is-open');
  state.auditRecordId = id;
  const holder = document.createElement('div');
  holder.className = 'audit-detail';
  holder.textContent = 'Загрузка…';
  row.insertAdjacentElement('afterend', holder);
  let data;
  try {
    data = await j(`/api/audit/${encodeURIComponent(id)}`);
  } catch (e) {
    holder.innerHTML = `<div class="empty">Не удалось прочитать операцию: ${errorHtml(e)}</div>`;
    return;
  }
  if (!holder.isConnected || state.auditRecordId !== id) return;
  holder.innerHTML = renderDetail(data);
  bindDetail(holder, data);
}

function paramsHtml(params) {
  const values = Object.entries(params || {});
  if (!values.length) return '<div class="audit-technical-empty">Параметров нет.</div>';
  return `<dl>${values.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(
    typeof value === 'string' ? value : JSON.stringify(value))}</dd>`).join('')}</dl>`;
}

function technicalRecordsHtml(records) {
  if (!records.length) return '';
  return `<div class="audit-block audit-technical"><div class="audit-block-title">Технические записи</div>${records.map(record => {
    const actor = record.actor || {};
    const actorText = actor.id ? `${actor.type}: ${actor.id}` : (actor.type || 'система');
    return `<details class="audit-technical-record">
      <summary><span>${esc(formatServerDateTime(record.ts))}</span><span>${esc(record.title || record.action)}</span><span class="badge ${RESULT_CLASS[record.result] || 'unk'}"><span class="dot"></span>${esc(resultText(record.result))}</span></summary>
      <dl>
        <dt>Код</dt><dd><span class="audit-action-code">${esc(record.action)}</span></dd>
        <dt>Кто</dt><dd>${esc(actorText)}</dd>
        ${record.server ? `<dt>Сервер</dt><dd>${esc(record.server.name || record.server.id)}</dd>` : ''}
        ${record.op_id ? `<dt>Операция</dt><dd><span class="audit-action-code">${esc(record.op_id)}</span></dd>` : ''}
        ${record.task_id ? `<dt>Задача</dt><dd><span class="audit-action-code">${esc(record.task_id)}</span></dd>` : ''}
        ${record.error ? `<dt>Ошибка</dt><dd class="audit-error">${esc(record.error)}</dd>` : ''}
        ${record.failure_detail ? `<dt>Причина отказа</dt><dd class="audit-error">${esc(record.failure_detail)}</dd>` : ''}
      </dl>
      <div class="audit-params"><div class="audit-block-title">Параметры</div>${paramsHtml(record.params)}</div>
    </details>`;
  }).join('')}</div>`;
}

function renderDetail(data) {
  const record = data.record || {};
  const actor = record.actor || {};
  const result = operationResult(record);
  const end = endState(record);
  const rows = [
    ['Операция', esc(record.title || record.action || '—')],
    ['Начало', esc(formatServerDateTime(record.started_at ?? record.ts))],
    [end.label, end.value],
  ];
  if (record.duration_seconds != null) rows.push(['Длительность', esc(durationText(record.duration_seconds))]);
  rows.push(['Итог', esc(resultText(result))]);
  rows.push(['Кто', `${esc(actor.type || 'система')}${actor.id ? `: ${esc(actor.id)}` : ''}${actor.role ? ` · роль: ${esc(actor.role)}` : ''}${actor.ip ? ` · ${esc(actor.ip)}` : ''}`]);
  if (record.server) rows.push(['Сервер', esc(record.server.name || record.server.id)]);
  if (record.error) rows.push(['Ошибка', `<span class="audit-error">${esc(record.error)}</span>`]);

  const task = data.task;
  let taskHtml = '';
  if (task) {
    taskHtml = `<div class="audit-block"><div class="audit-block-title">Задача</div>
      <div>${esc(task.name || task.id)} · ${esc(task.status || '—')}${task.attempt ? ` · попытка ${esc(String(task.attempt))}` : ''}</div>
      <div class="actions" style="margin:.4rem 0 0"><button type="button" class="secondary" data-audit-task="${esc(task.id)}">Открыть вывод задачи</button></div>
    </div>`;
  } else if (record.task_id) {
    taskHtml = '<div class="audit-block"><div class="audit-block-title">Задача</div><div>Задача уже ушла из истории задач — осталась только операция.</div></div>';
  }

  const event = data.event;
  let eventHtml = '';
  if (event) {
    eventHtml = `<div class="audit-block"><div class="audit-block-title">Событие</div>
      <div>${esc(event.title || event.type || '')}</div>
      ${event.message ? `<div class="audit-event-message">${esc(event.message)}</div>` : ''}
      <div class="actions" style="margin:.4rem 0 0"><button type="button" class="secondary" data-audit-event="${esc(event.id)}">Открыть событие</button></div>
    </div>`;
  } else if (record.event_id) {
    eventHtml = '<div class="audit-block"><div class="audit-block-title">Событие</div><div>Событие уже ушло из журнала по ротации.</div></div>';
  }

  const log = data.log || {};
  const logHtml = log.available
    ? `<div class="audit-block"><div class="audit-block-title">Лог</div><div>Доступен</div></div>`
    : '';
  const actions = [];
  if (record.server?.id) {
    actions.push(`<button type="button" class="secondary" data-audit-graph="${esc(record.server.id)}" data-audit-ts="${esc(String(record.started_at ?? record.ts))}" data-audit-record="${esc(record.id || '')}">Показать на графике</button>`);
  }
  const actionsHtml = actions.length ? `<div class="actions" style="margin:.6rem 0 0">${actions.join('')}</div>` : '';
  const incomplete = record.status === 'incomplete'
    ? '<div class="audit-incomplete">Нет записи о завершении. Это не означает, что операция всё ещё выполняется. <button type="button" class="faq-help-link" data-audit-help="incomplete">ⓘ Подробнее</button></div>'
    : '';

  return `<div class="audit-detail-head">${record.server ? `${esc(record.server.name || record.server.id)} · ` : ''}${esc(formatServerTime(record.started_at ?? record.ts))}</div>
    ${incomplete}<dl>${rows.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${value}</dd>`).join('')}</dl>
    ${taskHtml}${eventHtml}${logHtml}${technicalRecordsHtml(data.technical_records || [])}${actionsHtml}`;
}

function bindDetail(holder, data) {
  holder.querySelector('[data-audit-help="incomplete"]')?.addEventListener('click', () => {
    if (document.getElementById('confirm-modal')?.classList.contains('open')) return;
    void infoModal({
      title: 'Незавершённая запись аудита',
      message: 'Такая запись означает, что аудит увидел начало операции, но не получил её финальный результат. Она не показывает, выполняется ли операция сейчас: та могла завершиться, быть прервана или не записать итог. Сопоставьте запись с задачей, логом и событиями.',
      handbookAnchor: 'audit',
    });
  });
  holder.querySelector('[data-audit-task]')?.addEventListener('click', event => {
    openTaskLog(event.currentTarget.dataset.auditTask);
  });
  holder.querySelector('[data-audit-event]')?.addEventListener('click', event => {
    openEventDetail(event.currentTarget.dataset.auditEvent);
  });
  holder.querySelector('[data-audit-graph]')?.addEventListener('click', event => {
    const serverId = event.currentTarget.dataset.auditGraph;
    const ts = Number(event.currentTarget.dataset.auditTs);
    const recordId = event.currentTarget.dataset.auditRecord;
    if (openedBy.openMetricsAt) openedBy.openMetricsAt(serverId, ts, recordId);
  });
}

export async function openAuditRecord(recordId, { serverId = null } = {}) {
  const requestedId = String(recordId ?? '').trim();
  if (!requestedId) return false;
  let detail;
  try {
    detail = await j(`/api/audit/${encodeURIComponent(requestedId)}`);
  } catch (e) {
    toast(`Не удалось прочитать операцию: ${e.message}`, false);
    return false;
  }
  const id = String(detail.record?.id || requestedId);
  const f = filters();
  f.server = serverId || detail.record?.server?.id || '';
  f.q = '';
  f.range = 'custom';
  f.dateFrom = formatServerDateTime(detail.record?.started_at ?? detail.record?.ts).slice(0, 10);
  f.dateTo = '';
  syncFiltersToUI();
  await loadAudit();
  let row = findRow(id);
  for (let page = 0; !row && nextCursor && page < 10; page += 1) {
    await loadAudit({ append: true });
    row = findRow(id);
  }
  if (!row) {
    toast('Операция не попала в окно журнала — расширьте период или снимите фильтры', false);
    return false;
  }
  row.scrollIntoView({ block: 'center' });
  await toggleRecord(row);
  return true;
}

function findRow(recordId) {
  return document.querySelector(`#audit-list .audit-row[data-record-id="${CSS.escape(String(recordId))}"]`);
}

export function auditFromUrl() {
  let params;
  try { params = new URL(window.location.href).searchParams; } catch (_) { return null; }
  if (params.get('page') !== 'history' || params.get('tab') !== 'actions') return null;
  return { recordId: (params.get('record') || '').trim() || null };
}

async function reloadCurrentAuditPage() {
  if (loading) {
    scheduleAuditReload();
    return;
  }
  if (hasAppended) {
    newAbove = true;
    countRecords();
    return;
  }
  const recordId = state.auditRecordId;
  await loadAudit();
  if (!recordId) return;
  const row = findRow(recordId);
  if (row) await toggleRecord(row);
}

function scheduleAuditReload() {
  clearTimeout(auditReloadTimer);
  auditReloadTimer = setTimeout(() => {
    auditReloadTimer = null;
    reloadCurrentAuditPage().catch(() => {});
  }, 250);
}

export function applyAuditFrame(frame) {
  if (!frame || state.page !== 'history' || state.historyTab !== 'actions') return;
  scheduleAuditReload();
}

export function reloadAuditAfterReconnect() {
  if (state.page !== 'history' || state.historyTab !== 'actions') return;
  scheduleAuditReload();
}

export function refreshAudit() {
  if (state.page !== 'history' || state.historyTab !== 'actions') return;
  if (hasAppended) {
    newAbove = true;
    countRecords();
    return;
  }
  loadAudit();
}

export function resetAuditPage() {
  clearTimeout(auditReloadTimer);
  auditReloadTimer = null;
  facetsLoaded = false;
  nextCursor = null;
  hasAppended = false;
  newAbove = false;
  state.auditRecordId = null;
}
