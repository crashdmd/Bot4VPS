import { esc } from './api.js';

let serverTimeOffset = 0;
let serverTimezone = 'UTC';
const serverTimeFormatters = new Map();
let confirmResolve = null;
let confirmReturnFocus = null;
let telegramHealthReturnFocus = null;
let telegramHealthSettingsAction = null;

function closeConfirmDialog(result) {
  const modal = document.getElementById('confirm-modal');
  modal?.classList.remove('open');
  const resolve = confirmResolve;
  confirmResolve = null;
  if (resolve) resolve(result);
  const returnFocus = confirmReturnFocus;
  confirmReturnFocus = null;
  setTimeout(() => returnFocus?.focus?.(), 0);
}

/** Единое подтверждение опасных действий через общую модалку. */
export function confirmAction({
  title,
  message = '',
  confirmText = 'Подтвердить',
  cancelText = 'Отмена',
  danger = true,
  confirmFirst = true,
  checkbox = null,
} = {}) {
  const modal = document.getElementById('confirm-modal');
  if (!modal) return Promise.resolve(false);
  if (confirmResolve) closeConfirmDialog(false);

  confirmReturnFocus = document.activeElement;
  document.getElementById('confirm-modal-title').textContent = title || 'Подтвердите действие';
  const messageEl = document.getElementById('confirm-modal-message');
  messageEl.textContent = message;
  messageEl.classList.toggle('hidden', !message && !checkbox);
  let checkboxInput = null;
  if (checkbox) {
    const row = document.createElement('label');
    row.style.cssText = 'display:flex;align-items:flex-start;gap:.45rem;margin-top:.7rem;cursor:pointer';
    checkboxInput = document.createElement('input');
    checkboxInput.type = 'checkbox';
    checkboxInput.checked = !!checkbox.checked;
    const text = document.createElement('span');
    text.textContent = checkbox.label || '';
    row.append(checkboxInput, text);
    messageEl.append(row);
  }

  const ok = document.getElementById('confirm-modal-ok');
  const cancel = document.getElementById('confirm-modal-cancel');
  // infoModal прячет «Отмену» — возвращаем её для обычных подтверждений
  cancel.classList.remove('hidden');
  ok.textContent = confirmText;
  ok.className = danger ? 'danger' : 'secondary';
  cancel.textContent = cancelText;
  const actions = ok.parentElement;
  if (actions) {
    if (confirmFirst) actions.insertBefore(ok, cancel);
    else actions.insertBefore(cancel, ok);
  }
  ok.onclick = () => {
    if (checkboxInput) checkbox.checked = checkboxInput.checked;
    closeConfirmDialog(true);
  };
  cancel.onclick = () => closeConfirmDialog(false);
  modal.onkeydown = e => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeConfirmDialog(false);
    }
  };

  modal.classList.add('open');
  setTimeout(() => cancel.focus(), 30);
  return new Promise(resolve => { confirmResolve = resolve; });
}

/** Информационная модалка: единственная кнопка «Ок», без отмены.
    Переиспользует разметку confirm-modal (confirmAction снимает
    hidden с «Отмены» при следующем открытии). */
export function infoModal({ title, message = '', okText = 'Ок' } = {}) {
  const modal = document.getElementById('confirm-modal');
  if (!modal) return Promise.resolve(true);
  if (confirmResolve) closeConfirmDialog(false);
  confirmReturnFocus = document.activeElement;
  document.getElementById('confirm-modal-title').textContent = title || 'Внимание';
  const messageEl = document.getElementById('confirm-modal-message');
  messageEl.textContent = message;
  messageEl.classList.toggle('hidden', !message);
  const ok = document.getElementById('confirm-modal-ok');
  const cancel = document.getElementById('confirm-modal-cancel');
  ok.textContent = okText;
  ok.className = 'secondary';
  cancel.classList.add('hidden');
  ok.onclick = () => closeConfirmDialog(true);
  modal.onkeydown = e => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeConfirmDialog(true);
    }
  };
  modal.classList.add('open');
  setTimeout(() => ok.focus(), 30);
  return new Promise(resolve => { confirmResolve = resolve; });
}

export function showTelegramHealthDialog({ ok = false, code = '', reason = '', source = 'settings', onOpenSettings = null } = {}) {
  const modal = document.getElementById('telegram-health-modal');
  if (!modal) return;
  telegramHealthReturnFocus = document.activeElement;
  telegramHealthSettingsAction = typeof onOpenSettings === 'function' ? onOpenSettings : null;

  const fromBackup = source === 'backup';
  const notChecked = fromBackup && code === 'NOT_CONFIGURED';
  document.getElementById('telegram-health-title').textContent = ok
    ? '✓ Telegram работает'
    : (notChecked ? 'Уведомления в ТГ не проверены'
      : (fromBackup ? 'Уведомления в ТГ недоступны' : '✕ Telegram недоступен'));
  document.getElementById('telegram-health-summary').textContent = ok
    ? 'Бот доступен.\nТестовое сообщение успешно отправлено.'
    : (notChecked
      ? 'Доставка уведомлений через Telegram для сохранённых настроек ещё не проверена.'
      : (fromBackup ? 'Отправка уведомлений в Telegram в данный момент не работает.' : ''));

  const reasonBlock = document.getElementById('telegram-health-reason');
  reasonBlock?.classList.toggle('hidden', ok);
  document.getElementById('telegram-health-reason-text').textContent = reason || 'Причина не определена.';

  const settings = document.getElementById('telegram-health-settings');
  settings?.classList.toggle('hidden', !fromBackup);
  modal.classList.add('open');
  setTimeout(() => document.getElementById('telegram-health-ok')?.focus(), 30);
}

export function closeTelegramHealthDialog({ openSettings = false } = {}) {
  const modal = document.getElementById('telegram-health-modal');
  modal?.classList.remove('open');
  const action = telegramHealthSettingsAction;
  telegramHealthSettingsAction = null;
  const returnFocus = telegramHealthReturnFocus;
  telegramHealthReturnFocus = null;
  if (openSettings && action) action();
  else setTimeout(() => returnFocus?.focus?.(), 0);
}

export function bindTelegramHealthDialog() {
  const modal = document.getElementById('telegram-health-modal');
  if (!modal || modal.dataset.bound) return;
  modal.dataset.bound = '1';
  document.getElementById('telegram-health-ok')?.addEventListener('click', () => closeTelegramHealthDialog());
  document.getElementById('telegram-health-settings')?.addEventListener('click', () => closeTelegramHealthDialog({ openSettings: true }));
  modal.addEventListener('click', event => {
    if (event.target === modal) closeTelegramHealthDialog();
  });
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeTelegramHealthDialog();
    }
  });
}

export function toast(m, ok, opts = {}) {
  const e = document.createElement('div');
  e.className = 'toast ' + (ok ? 'ok' : 'err');
  // Многострочные сообщения (диагностика Telegram): переносы строк видны
  e.style.whiteSpace = opts.multiline ? 'pre-line' : '';
  e.textContent = m;
  document.getElementById('toasts').appendChild(e);
  setTimeout(() => e.remove(), opts.timeout || 3000);
}

export function syncServerTime(server_ts) {
  if (typeof server_ts === 'number' && !Number.isNaN(server_ts)) {
    serverTimeOffset = server_ts * 1000 - Date.now();
  }
}

export function syncServerTimezone(timezoneName) {
  if (typeof timezoneName !== 'string' || !timezoneName) return false;
  try {
    new Intl.DateTimeFormat('ru-RU', { timeZone: timezoneName }).format(new Date());
  } catch (_) {
    return false;
  }
  if (serverTimezone !== timezoneName) {
    serverTimezone = timezoneName;
    serverTimeFormatters.clear();
  }
  return true;
}

export function syncServerClock({ server_ts, timezone } = {}) {
  syncServerTime(server_ts);
  syncServerTimezone(timezone);
  tickClock();
}

export function serverNow() {
  return new Date(Date.now() + serverTimeOffset);
}

function serverFormatter(key, options) {
  let formatter = serverTimeFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('ru-RU', {
      ...options,
      timeZone: serverTimezone,
    });
    serverTimeFormatters.set(key, formatter);
  }
  return formatter;
}

const naiveServerTimestamp = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/;

function timestampParts(value) {
  if (typeof value === 'string') {
    const match = naiveServerTimestamp.exec(value.trim());
    if (match) {
      return {
        year: match[1], month: match[2], day: match[3],
        hour: match[4], minute: match[5], second: match[6] || '00',
      };
    }
  }

  let date;
  if (value instanceof Date) {
    date = value;
  } else if (typeof value === 'number') {
    date = new Date(value < 1_000_000_000_000 ? value * 1000 : value);
  } else {
    date = new Date(value);
  }
  if (Number.isNaN(date.getTime())) return null;

  const parts = serverFormatter('timestamp-parts', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return {
    year: byType.year, month: byType.month, day: byType.day,
    hour: byType.hour, minute: byType.minute, second: byType.second,
  };
}

/**
 * Разобрать timestamp как время локального хоста. Старые naive ISO-строки уже
 * содержат host wall-clock и не должны ошибочно интерпретироваться браузером.
 */
export function serverDateTimeParts(value) {
  if (value == null || value === '') return null;
  return timestampParts(value);
}

export function serverDayDifference(value, reference = serverNow()) {
  const valueParts = serverDateTimeParts(value);
  const referenceParts = serverDateTimeParts(reference);
  if (!valueParts || !referenceParts) return null;
  const valueDay = Date.UTC(Number(valueParts.year), Number(valueParts.month) - 1, Number(valueParts.day));
  const referenceDay = Date.UTC(Number(referenceParts.year), Number(referenceParts.month) - 1, Number(referenceParts.day));
  return Math.round((referenceDay - valueDay) / 86400000);
}

export function formatServerTime(value, { seconds = false } = {}) {
  const parts = serverDateTimeParts(value);
  if (!parts) return '—';
  return `${parts.hour}:${parts.minute}${seconds ? `:${parts.second}` : ''}`;
}

export function formatServerDateTime(value, { seconds = false } = {}) {
  const parts = serverDateTimeParts(value);
  if (!parts) return '—';
  return `${parts.day}.${parts.month}.${parts.year} ${formatServerTime(value, { seconds })}`;
}

export function formatServerTimestamp(value) {
  const parts = serverDateTimeParts(value);
  if (!parts) return '—';
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function formatClock(d) {
  return serverFormatter('side-clock', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(d);
}

export function formatDate(d) {
  return serverFormatter('side-date', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  }).format(d);
}

export function serverHour(d = serverNow()) {
  const part = serverFormatter('hour', {
    hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(d).find(item => item.type === 'hour');
  return Number(part?.value ?? 0);
}

export function tickClock() {
  const d = serverNow();
  const headerTime = document.getElementById('header-time');
  const headerDate = document.getElementById('header-date');
  if (headerTime) {
    headerTime.textContent = serverFormatter('header-time', {
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).format(d);
    headerTime.dateTime = d.toISOString();
  }
  if (headerDate) {
    headerDate.textContent = serverFormatter('header-date', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    }).format(d);
  }

  const sideClock = document.getElementById('side-clock');
  const sideDate = document.getElementById('side-date');
  if (sideClock) sideClock.textContent = formatClock(d);
  if (sideDate) sideDate.textContent = formatDate(d);
}

/** Русское склонение числительных: 1 день / 2 дня / 5 дней.
 *  Живёт здесь, а не в dashboard.js: dashboard.js импортирует monitor.js,
 *  поэтому обратный импорт был бы циклическим. Из ui.js читают оба. */
export function plural(n, one, few, many) {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  const mod10 = n % 10;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

export function showPage(name, { onShow } = {}) {
  document.querySelectorAll('.page').forEach(p =>
    p.classList.toggle('on', p.id === 'page-' + name));
  document.querySelectorAll('.side [data-page]').forEach(b =>
    b.classList.toggle('on', b.dataset.page === name));
  // активная страница внутри .nav-sub → раскрыть группу и подсветить голову
  document.querySelectorAll('.side .nav-group').forEach(g => {
    const head = g.querySelector('.nav-group-head');
    const active = g.querySelector('.nav-sub [data-page].on');
    if (active) g.classList.add('open');
    head?.classList.toggle('on', !!active);
  });
  if (onShow) onShow(name);
}

export function parseEmoji(element) {
  if (typeof twemoji !== 'undefined') {
    twemoji.parse(element || document.body);
  }
}

// Глобальный наблюдатель за изменениями DOM для автоматического парсинга эмодзи
export function initEmojiObserver() {
  if (typeof twemoji === 'undefined') return;

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType === 1) { // Element node
          twemoji.parse(node);
        }
      });
    });
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });
}

export function onlineBadge(v) {
  if (v === true) return '<span class="badge on">🟢 Online</span>';
  if (v === false) return '<span class="badge off">🔴 Offline</span>';
  return '<span class="badge unk">⚪ Нет данных</span>';
}

export function onlineBadgeWithPing(v, serverId) {
  const statusIcon = v === true ? '🟢' : v === false ? '🔴' : '⚪';
  const statusText = v === true ? 'Online' : v === false ? 'Offline' : 'Нет данных';
  const badgeClass = v === true ? 'on' : v === false ? 'off' : 'unk';
  return `<span class="badge ${badgeClass}">${statusIcon} ${statusText} · <span class="ping" id="ping-${esc(serverId)}">…</span></span>`;
}

export function sslBadge(s) {
  if (!s.certificate_check) return '<span class="badge unk">SSL —</span>';
  const st = s.ssl_status;
  if (st === 'valid')
    return `<span class="badge ssl-ok">🔵 SSL OK${s.ssl_days_left != null ? ' · ' + s.ssl_days_left + 'д' : ''}</span>`;
  if (st === 'warning')
    return `<span class="badge ssl-warn">🟡 SSL скоро${s.ssl_days_left != null ? ' · ' + s.ssl_days_left + 'д' : ''}</span>`;
  if (st === 'expired' || st === 'error')
    return '<span class="badge ssl-bad">🔴 SSL проблема</span>';
  return '<span class="badge unk">SSL …</span>';
}

export function barClass(p) {
  if (p == null) return '';
  if (p >= 90) return 'bad';
  if (p >= 75) return 'warn';
  return '';
}

export function metricTile(l, v, p) {
  const b = p == null ? '' : `<div class="bar ${barClass(p)}"><i style="width:${Math.min(100, Math.max(0, p))}%"></i></div>`;
  return `<div class="metric"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div>${b}</div>`;
}

export function bindPasswordToggles(root = document) {
  root.querySelectorAll('[data-pw-toggle]').forEach(btn => {
    btn.onclick = () => {
      const id = btn.getAttribute('data-pw-toggle');
      const input = document.getElementById(id);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? '🙈' : '👁';
      // Возвращаем twemoji: сырой юникод-эмодзи системный шрифт рисует
      // крупнее img.emoji (1em) — иконка «распухала» после первого клика.
      parseEmoji(btn);
    };
  });
}
