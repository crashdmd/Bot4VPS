// Фильтр статусов в списках сервисов (Docker/WireGuard/3x-ui): кнопка у
// заголовка «Статус», по клику — попап с чекбоксами. Снятая галочка скрывает
// серверы этого статуса; выбор живёт в localStorage (свой ключ на сервис).
// Кнопка позиционируется абсолютно внутри th, поэтому не сдвигает
// центрированный заголовок (важно на мобильной сетке).

import { esc } from './api.js';

const LS_PREFIX = 'bot4vps_status_filter_';
const states = {};   // id -> Set скрытых ключей
let pop = null;      // открытый попап

function load(id, statuses) {
  if (states[id]) return states[id];
  const hidden = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem(LS_PREFIX + id) || '[]');
    if (Array.isArray(saved)) statuses.forEach(s => { if (saved.includes(s.key)) hidden.add(s.key); });
  } catch (_) { /* битый localStorage — просто полный набор */ }
  states[id] = hidden;
  return hidden;
}

function save(id) {
  try { localStorage.setItem(LS_PREFIX + id, JSON.stringify([...(states[id] || [])])); } catch (_) {}
}

/** Кнопка-воронка для вставки в th «Статус» (после сортировочной шапки). */
export function statusFilterBtn(id) {
  return `<button type="button" class="status-filter-btn" data-status-filter="${esc(id)}"
    aria-haspopup="true" aria-expanded="false" title="Фильтр по статусу">▾</button>`;
}

/** Скрытые статусы — для фильтрации строк при рендере. */
export function statusFilterHidden(id, statuses) {
  return load(id, statuses);
}

/** Повесить поведение кнопки; вызывается после каждого рендера таблицы
 *  (кнопка пересоздаётся вместе с thead). onChange — перерисовать список. */
export function bindStatusFilter(id, statuses, onChange) {
  const btn = document.querySelector(`[data-status-filter="${CSS.escape(id)}"]`);
  if (!btn) return;
  syncBtn(btn, load(id, statuses));
  btn.onclick = e => {
    e.stopPropagation();
    if (pop && pop.dataset.for === id) { closePop(); return; }
    openPop(btn, id, statuses, onChange);
  };
}

function syncBtn(btn, hidden) {
  btn.classList.toggle('on', hidden.size > 0);
  btn.setAttribute('aria-expanded', pop && pop.dataset.for === btn.dataset.statusFilter ? 'true' : 'false');
}

function openPop(btn, id, statuses, onChange) {
  closePop();
  const hidden = load(id, statuses);
  pop = document.createElement('div');
  pop.className = 'status-filter-pop';
  pop.dataset.for = id;
  pop.innerHTML = statuses.map(s => `
    <label class="status-filter-item">
      <input type="checkbox" data-key="${esc(s.key)}"${hidden.has(s.key) ? '' : ' checked'}>
      <span>${esc(s.label)}</span>
    </label>`).join('');
  document.body.appendChild(pop);
  // position:fixed — не зависит от overflow/transform предков (thead sticky)
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + 'px';
  pop.style.top = Math.min(r.bottom + 6, window.innerHeight - pop.offsetHeight - 8) + 'px';
  pop.addEventListener('change', e => {
    const key = e.target.dataset.key;
    if (!key) return;
    if (e.target.checked) hidden.delete(key); else hidden.add(key);
    save(id);
    syncBtn(btn, hidden);
    onChange();
  });
  syncBtn(btn, hidden);
}

function closePop() {
  pop?.remove();
  pop = null;
}

// Клик мимо попапа (и не по кнопке-воронке) и Esc закрывают
document.addEventListener('click', e => {
  if (pop && !pop.contains(e.target) && !e.target.closest('.status-filter-btn')) closePop();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePop(); });
