import { j } from './api.js';
import { toast, bindPasswordToggles } from './ui.js';

// Текущее состояние учётки (кэш последнего ответа /api/auth/account).
let account = { auth_enabled: false, username: 'admin' };

// ---------------- Тема (dark / light / auto) ----------------
const THEME_KEY = 'bot4vps_theme';
const THEME_COLOR = { dark: '#0d1117', light: '#f6f8fa' };
const mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

function storedTheme() {
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === 'dark' || t === 'light') return t;
    // миграция со старого 'auto'/пусто → системное предпочтение, сохраняем один раз
    const resolved = (mql && mql.matches) ? 'light' : 'dark';
    try { localStorage.setItem(THEME_KEY, resolved); } catch (_) {}
    return resolved;
  } catch (_) { return 'dark'; }
}

function resolvedTheme(t) {
  return t === 'light' ? 'light' : 'dark';
}

function applyTheme(t) {
  const html = document.documentElement;
  const resolved = resolvedTheme(t);
  if (resolved === 'light') html.setAttribute('data-theme', 'light');
  else html.removeAttribute('data-theme');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', THEME_COLOR[resolved]);
  const tog = document.getElementById('theme-toggle');
  if (tog) tog.textContent = resolved === 'light' ? '🌙' : '☀️';
  // оповещаем подписчиков (xterm и проч.) о смене resolved-темы
  window.dispatchEvent(new CustomEvent('bot4vps:theme', { detail: { resolved } }));
}

function setTheme(t) {
  try { localStorage.setItem(THEME_KEY, t); } catch (_) {}
  applyTheme(t);
}

export function initTheme() {
  applyTheme(storedTheme());
  // быстрый переключатель в шапке: dark ↔ light
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    setTheme(storedTheme() === 'light' ? 'dark' : 'light');
  });
}

// ---------------- Учётная запись ----------------
export async function loadAccount() {
  try {
    account = await j('/api/auth/account');
  } catch (_) { /* локальный режим — всегда доступно */ }
  const user = document.getElementById('acc-user');
  if (user && account.username) user.value = account.username;
  const status = document.getElementById('acc-status');
  if (status) status.textContent = account.auth_enabled
    ? '🔒 Защита включена — для входа нужен пароль'
    : '🏠 Локальный режим — вход без пароля';
  const oldHint = document.getElementById('acc-old-hint');
  if (oldHint) oldHint.textContent = account.auth_enabled
    ? '(обязателен при смене пароля)'
    : '(не нужен в локальном режиме)';
  const toggle = document.getElementById('acc-toggle');
  if (toggle) toggle.textContent = account.auth_enabled
    ? '🔓 Выключить защиту'
    : '🔒 Включить защиту';
}

export async function saveAccount() {
  const username = (document.getElementById('acc-user').value || '').trim();
  const newPass = document.getElementById('acc-pass').value;
  if (!username) { toast('Логин не может быть пустым', false); return; }
  const body = { username };
  if (newPass) {
    if (newPass.length < 6) { toast('Пароль не короче 6 символов', false); return; }
    body.new_password = newPass;
    // При включённой защите смена пароля требует подтверждения старым.
    if (account.auth_enabled) body.old = document.getElementById('acc-old').value;
  }
  try {
    const r = await j('/api/auth/account', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    toast('Сохранено', true);
    document.getElementById('acc-pass').value = '';
    document.getElementById('acc-old').value = '';
    account = { auth_enabled: !!r.auth_enabled, username: r.username };
    await loadAccount();
  } catch (e) { toast(e.message, false); }
}

export async function toggleAuth() {
  const next = !account.auth_enabled;
  const msg = next
    ? 'Включить защиту входа? После этого потребуется логин и пароль.'
    : 'Выключить защиту? Вход станет открытым без пароля.';
  if (!confirm(msg)) return;
  try {
    const r = await j('/api/auth/account', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auth_enabled: next }),
    });
    toast(next ? 'Защита включена' : 'Защита выключена', true);
    account = { auth_enabled: !!r.auth_enabled, username: r.username };
    // Состояние сессии/доступа изменилось — чистая перезагрузка.
    setTimeout(() => location.reload(), 500);
  } catch (e) { toast(e.message, false); }
}

export function bindSettingsUI() {
  initTheme();
  document.getElementById('acc-save')?.addEventListener('click', saveAccount);
  document.getElementById('acc-toggle')?.addEventListener('click', toggleAuth);
  bindPasswordToggles();
  bindGroupsAdmin();
  // Сразу заполнить список (элемент в DOM есть даже на другой вкладке)
  loadGroupsAdmin();
}

// ---------------- Группы серверов ----------------
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

export async function loadGroupsAdmin() {
  const box = document.getElementById('groups-list');
  if (!box) {
    console.warn('[groups] #groups-list not found');
    return;
  }
  box.innerHTML = '<div class="acc-note">Загрузка групп…</div>';
  try {
    const data = await j('/api/groups');
    console.log('[groups] API response', data);
    const groups = Array.isArray(data?.groups) ? data.groups : [];
    if (!groups.length) {
      box.innerHTML = '<div class="acc-note">Групп пока нет — создайте первую ниже</div>';
      return;
    }
    box.innerHTML = groups.map(g => {
      const name = (g && g.name) != null ? String(g.name) : String(g);
      const ssl = g && g.ssl_monitor ? 'checked' : '';
      const n = (g && g.servers != null) ? g.servers : 0;
      return `<div class="group-row" data-name="${esc(name)}">
        <input class="grp-name" value="${esc(name)}" title="Переименовать"/>
        <label class="grp-ssl" title="SSL-проверка для группы">
          <input type="checkbox" class="grp-ssl-cb" ${ssl}/> SSL
        </label>
        <span class="grp-count">${n} серв.</span>
        <button type="button" class="secondary grp-save" title="Сохранить">💾</button>
        <button type="button" class="secondary grp-del" title="Удалить" ${n > 0 ? 'disabled' : ''}>🗑</button>
      </div>`;
    }).join('');
  } catch (e) {
    console.error('[groups] load failed', e);
    box.innerHTML = `<div class="acc-note" style="color:var(--err)">Ошибка загрузки: ${esc(e.message || e)}</div>`;
  }
}

async function saveGroupRow(row) {
  const oldName = row.dataset.name;
  const newName = (row.querySelector('.grp-name').value || '').trim();
  const ssl = row.querySelector('.grp-ssl-cb').checked;
  if (!newName) { toast('Название пустое', false); return; }
  try {
    const body = { ssl_monitor: ssl };
    if (newName !== oldName) body.name = newName;
    await j(`/api/groups/${encodeURIComponent(oldName)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    toast('Группа сохранена', true);
    await loadGroupsAdmin();
  } catch (e) {
    toast(e.message || String(e), false);
  }
}

async function deleteGroupRow(row) {
  const name = row.dataset.name;
  if (!confirm(`Удалить группу «${name}»?`)) return;
  try {
    await j(`/api/groups/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast('Группа удалена', true);
    await loadGroupsAdmin();
  } catch (e) {
    toast(e.message || String(e), false);
  }
}

async function createGroup() {
  const name = (document.getElementById('grp-new-name').value || '').trim();
  const ssl = !!document.getElementById('grp-new-ssl')?.checked;
  if (!name) { toast('Введите название', false); return; }
  try {
    await j('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ssl_monitor: ssl }),
    });
    const inp = document.getElementById('grp-new-name');
    if (inp) inp.value = '';
    const cb = document.getElementById('grp-new-ssl');
    if (cb) cb.checked = false;
    toast('Группа создана', true);
    await loadGroupsAdmin();
  } catch (e) {
    toast(e.message || String(e), false);
  }
}

export function bindGroupsAdmin() {
  const box = document.getElementById('groups-list');
  if (box && !box.dataset.bound) {
    box.dataset.bound = '1';
    box.addEventListener('click', (ev) => {
      const row = ev.target.closest('.group-row');
      if (!row) return;
      if (ev.target.closest('.grp-save')) saveGroupRow(row);
      if (ev.target.closest('.grp-del')) deleteGroupRow(row);
    });
  }
  const btn = document.getElementById('grp-create');
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = '1';
    btn.addEventListener('click', createGroup);
  }
  // При каждом показе страницы «Настройки» — перезагрузка списка
  const page = document.getElementById('page-settings');
  if (page && !page.dataset.groupsObs) {
    page.dataset.groupsObs = '1';
    new MutationObserver(() => {
      if (page.classList.contains('on')) loadGroupsAdmin();
    }).observe(page, { attributes: true, attributeFilter: ['class'] });
  }
}

