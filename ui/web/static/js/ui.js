import { esc } from './api.js';

let serverTimeOffset = 0;
let confirmResolve = null;
let confirmReturnFocus = null;

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
  confirmFirst = false,
} = {}) {
  const modal = document.getElementById('confirm-modal');
  if (!modal) return Promise.resolve(false);
  if (confirmResolve) closeConfirmDialog(false);

  confirmReturnFocus = document.activeElement;
  document.getElementById('confirm-modal-title').textContent = title || 'Подтвердите действие';
  const messageEl = document.getElementById('confirm-modal-message');
  messageEl.textContent = message;
  messageEl.classList.toggle('hidden', !message);

  const ok = document.getElementById('confirm-modal-ok');
  const cancel = document.getElementById('confirm-modal-cancel');
  ok.textContent = confirmText;
  ok.className = danger ? 'danger' : 'secondary';
  cancel.textContent = cancelText;
  const actions = ok.parentElement;
  if (actions) {
    if (confirmFirst) actions.insertBefore(ok, cancel);
    else actions.insertBefore(cancel, ok);
  }
  ok.onclick = () => closeConfirmDialog(true);
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

export function toast(m, ok) {
  const e = document.createElement('div');
  e.className = 'toast ' + (ok ? 'ok' : 'err');
  e.textContent = m;
  document.getElementById('toasts').appendChild(e);
  setTimeout(() => e.remove(), 3000);
}

export function syncServerTime(server_ts) {
  if (typeof server_ts === 'number' && !Number.isNaN(server_ts)) {
    serverTimeOffset = server_ts * 1000 - Date.now();
  }
}

export function serverNow() {
  return new Date(Date.now() + serverTimeOffset);
}

function pad(n) { return String(n).padStart(2, '0'); }

export function formatClock(d) {
  return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

export function formatDate(d) {
  return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear();
}

export function tickClock() {
  const d = serverNow();
  const b = document.getElementById('side-clock');
  const dt = document.getElementById('side-date');
  if (b) b.textContent = formatClock(d);
  if (dt) dt.textContent = formatDate(d);
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
    };
  });
}
