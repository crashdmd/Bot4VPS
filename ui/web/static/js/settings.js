import { j } from './api.js';
import { toast, bindPasswordToggles, confirmAction } from './ui.js';

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
    // По умолчанию всегда темная тема
    try { localStorage.setItem(THEME_KEY, 'dark'); } catch (_) {}
    return 'dark';
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

  // Обновляем SVG иконку переключателя темы
  updateThemeIcon(resolved);

  // оповещаем подписчиков (xterm и проч.) о смене resolved-темы
  window.dispatchEvent(new CustomEvent('bot4vps:theme', { detail: { resolved } }));
}

function updateThemeIcon(resolved) {
  const tog = document.getElementById('theme-toggle');
  if (!tog) return;

  // Определяем цвет stroke
  const strokeColor = resolved === 'light' ? '#1a1a1a' : '#ffffff';

  const svg = resolved === 'light'
    ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
       </svg>`
    : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
         <circle cx="12" cy="12" r="5"></circle>
         <line x1="12" y1="1" x2="12" y2="3"></line>
         <line x1="12" y1="21" x2="12" y2="23"></line>
         <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
         <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
         <line x1="1" y1="12" x2="3" y2="12"></line>
         <line x1="21" y1="12" x2="23" y2="12"></line>
         <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
         <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
       </svg>`;
  tog.innerHTML = svg;

  // Переподключаем обработчик клика после изменения innerHTML
  const newTog = document.getElementById('theme-toggle');
  if (newTog && !newTog.dataset.listenerAttached) {
    newTog.addEventListener('click', handleThemeToggle);
    newTog.dataset.listenerAttached = 'true';
  }
}

function handleThemeToggle() {
  setTheme(storedTheme() === 'light' ? 'dark' : 'light');
}

function setTheme(t) {
  try { localStorage.setItem(THEME_KEY, t); } catch (_) {}
  applyTheme(t);
}

export function initTheme() {
  applyTheme(storedTheme());
  // быстрый переключатель в шапке: dark ↔ light
  const tog = document.getElementById('theme-toggle');
  if (tog) {
    tog.addEventListener('click', handleThemeToggle);
    tog.dataset.listenerAttached = 'true';
  }
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
  if (!await confirmAction({ message: msg })) return;
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


// ---------------- Telegram ----------------

function formatTgStatus(st) {
  const state = (st && st.state) || '';
  const detail = (st && st.detail) || '';
  // Выключен — только telegram_enabled=false
  if (state === 'disabled' || detail === 'Выключен') {
    return { emoji: '⚪', text: 'Выключен' };
  }
  if (state === 'running' || detail === 'Работает') {
    return { emoji: '🟢', text: 'Работает' };
  }
  const reason = (st && st.error) || '';
  return { emoji: '🔴', text: reason ? `Ошибка · ${reason}` : 'Ошибка' };
}

function applyTelegramUi(data) {
  const line = document.getElementById('tg-status-line');
  const hint = document.getElementById('tg-token-hint');
  const user = document.getElementById('tg-user-id');
  if (!data) return;
  const fmt = formatTgStatus(data.status || {});
  if (line) {
    // token ✓ не показываем: «сохранён в config» ≠ «валидный».
    // Валидность видна только по статусу Работает / Ошибка с причиной.
    let t = `Статус: ${fmt.emoji} ${fmt.text}`;
    if (data.user_id != null) t += ` · id ${data.user_id}`;
    line.textContent = t;
  }
  if (user && document.activeElement !== user) {
    user.value = data.user_id != null ? String(data.user_id) : '';
  }
  if (hint) {
    const st = data.status || {};
    if (st.state === 'running') {
      hint.textContent = 'Токен принят Telegram. Поле пустое — токен не меняется.';
    } else if (data.token_set) {
      hint.textContent = 'В config.json есть значение токена (не проверялось, пока бот не запущен). Поле пустое — токен не меняется.';
    } else {
      hint.textContent = 'Токен ещё не задан в config.json.';
    }
  }
  const tok = document.getElementById('tg-bot-token');
  if (tok && document.activeElement !== tok) tok.value = '';
}

export async function loadTelegramSettings() {
  try {
    const data = await j('/api/telegram/status');
    applyTelegramUi(data);
  } catch (e) {
    const line = document.getElementById('tg-status-line');
    if (line) line.textContent = 'Статус: 🔴 Ошибка · ' + (e.message || e);
  }
}

async function tgAction(path) {
  const btns = ['tg-start', 'tg-stop', 'tg-restart', 'tg-save']
    .map(id => document.getElementById(id)).filter(Boolean);
  btns.forEach(b => { b.disabled = true; });
  try {
    const r = await j(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    applyTelegramUi(r);
    if (r.ok === false) toast(r.error || 'Ошибка', false);
    else toast(r.message || 'Готово', true);
  } catch (e) {
    toast(e.message || String(e), false);
    await loadTelegramSettings();
  } finally {
    btns.forEach(b => { b.disabled = false; });
  }
}

async function tgSave() {
  const user_id = (document.getElementById('tg-user-id')?.value || '').trim();
  const rawToken = document.getElementById('tg-bot-token')?.value || '';
  const bot_token = rawToken.trim();
  // В поле что-то ввели, но после trim пусто (пробелы) — это ошибка, не «ок»
  if (rawToken.length > 0 && !bot_token) {
    toast('Bot Token не может состоять из пробелов', false);
    return;
  }
  if (bot_token) {
    const u = bot_token.toUpperCase();
    if (u.startsWith('YOUR_') || u.includes('YOUR_BOT_TOKEN')) {
      toast('Укажите действительный Bot Token, не placeholder', false);
      return;
    }
  }
  const body = { user_id };
  if (bot_token) body.bot_token = bot_token;
  const btn = document.getElementById('tg-save');
  if (btn) btn.disabled = true;
  try {
    const r = await j('/api/telegram/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    applyTelegramUi(r);
    if (r.ok === false) toast(r.error || 'Ошибка сохранения', false);
    else {
      const msg = bot_token
        ? (r.message || 'Сохранено')
        : (r.message || 'Сохранено') + (rawToken ? '' : ' (токен не менялся)');
      toast(msg, true);
      const tok = document.getElementById('tg-bot-token');
      if (tok) tok.value = '';
    }
  } catch (e) {
    toast(e.message || String(e), false);
  } finally {
    if (btn) btn.disabled = false;
  }
}


export function bindSettingsUI() {
  const bind = (id, fn) => {
    const el = document.getElementById(id);
    if (!el) { console.warn('[settings] missing #' + id); return; }
    el.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); fn(); });
  };
  bind('tg-start', () => tgAction('/api/telegram/start'));
  bind('tg-stop', () => tgAction('/api/telegram/stop'));
  bind('tg-restart', () => tgAction('/api/telegram/restart'));
  bind('tg-save', tgSave);
  initTheme();
  document.getElementById('acc-save')?.addEventListener('click', saveAccount);
  document.getElementById('acc-toggle')?.addEventListener('click', toggleAuth);
  document.getElementById('groups-panel-close')?.addEventListener('click', closeGroupsPanel);
  bindPasswordToggles();
  bindGroupsAdmin();
  // Сразу заполнить список (элемент в DOM есть даже на другой вкладке)
  loadGroupsAdmin();
  // Статус Telegram при первом заходе / после F5
  loadTelegramSettings().catch(() => {});

  // Повторная загрузка каждый раз, когда страница «Настройки» становится видимой
  const ps = document.getElementById('page-settings');
  if (ps && !ps.dataset.tgObs) {
    ps.dataset.tgObs = '1';
    new MutationObserver(() => {
      if (ps.classList.contains('on')) loadTelegramSettings().catch(() => {});
    }).observe(ps, { attributes: true, attributeFilter: ['class'] });
  }
}

function closeGroupsPanel() {
  const panel = document.getElementById('groups-panel');
  if (panel) panel.classList.remove('open');
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
      const canDelete = n === 0;
      return `<div class="group-row" data-name="${esc(name)}">
        <input class="grp-name" value="${esc(name)}" placeholder="Название"/>
        <label class="grp-ssl-label">
          <input type="checkbox" class="grp-ssl-cb" ${ssl}/>
          <span>SSL</span>
        </label>
        <span class="grp-count">${n}</span>
        <button type="button" class="icon-btn grp-save" title="Сохранить">💾</button>
        <button type="button" class="icon-btn grp-del" title="${canDelete ? 'Удалить' : 'Нельзя удалить группу с серверами'}" ${canDelete ? '' : 'disabled'}>🗑</button>
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
  if (!await confirmAction({ message: `Удалить группу «${name}»?` })) return;
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
  bindGroupsDisplayOrder();
}

// ---------------- Настройка отображения меню серверов ----------------
let draggedElement = null;

export async function loadGroupsDisplayOrder() {
  const box = document.getElementById('groups-display-list');
  if (!box) return;

  box.innerHTML = '<div class="acc-note">Загрузка…</div>';

  try {
    const data = await j('/api/groups');
    const groups = Array.isArray(data?.groups) ? data.groups : [];

    if (!groups.length) {
      box.innerHTML = '<div class="acc-note">Групп пока нет</div>';
      return;
    }

    // Получаем сохранённые настройки
    let savedOrder = [];
    let visibleGroups = null;
    try {
      const orderStr = localStorage.getItem('bot4vps_group_order');
      const visibleStr = localStorage.getItem('bot4vps_visible_groups');
      if (orderStr) savedOrder = JSON.parse(orderStr);
      if (visibleStr) visibleGroups = new Set(JSON.parse(visibleStr));
    } catch (_) {}

    // Формируем список групп с учётом сохранённого порядка
    const groupNames = groups.map(g => (g && g.name) != null ? String(g.name) : String(g));
    let orderedNames = [];

    savedOrder.forEach(name => {
      if (groupNames.includes(name)) orderedNames.push(name);
    });

    groupNames.forEach(name => {
      if (!orderedNames.includes(name)) orderedNames.push(name);
    });

    // Если нет сохранённых настроек видимости, все группы видимы по умолчанию
    if (!visibleGroups) {
      visibleGroups = new Set(orderedNames);
    }

    box.innerHTML = orderedNames.map(name => {
      const isVisible = visibleGroups.has(name);
      return `<div class="group-display-row" draggable="true" data-name="${esc(name)}">
        <span class="drag-handle">☰</span>
        <label class="group-display-label">
          <input type="checkbox" class="group-visible-cb" ${isVisible ? 'checked' : ''}/>
          <span>${esc(name)}</span>
        </label>
      </div>`;
    }).join('');

    // Обработчики изменения видимости
    box.querySelectorAll('.group-visible-cb').forEach(cb => {
      cb.addEventListener('change', saveGroupsDisplaySettings);
    });

  } catch (e) {
    box.innerHTML = `<div class="acc-note" style="color:var(--err)">Ошибка: ${esc(e.message || e)}</div>`;
  }
}

function bindGroupsDisplayOrder() {
  const box = document.getElementById('groups-display-list');
  if (!box || box.dataset.dragBound) return;
  box.dataset.dragBound = '1';

  box.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.group-display-row');
    if (row) {
      draggedElement = row;
      row.classList.add('dragging');
    }
  });

  box.addEventListener('dragend', (e) => {
    const row = e.target.closest('.group-display-row');
    if (row) {
      row.classList.remove('dragging');
      draggedElement = null;
      saveGroupsDisplaySettings();
    }
  });

  box.addEventListener('dragover', (e) => {
    e.preventDefault();
    const afterElement = getDragAfterElement(box, e.clientY);
    if (afterElement == null) {
      box.appendChild(draggedElement);
    } else {
      box.insertBefore(draggedElement, afterElement);
    }
  });
}

function getDragAfterElement(container, y) {
  const draggableElements = [...container.querySelectorAll('.group-display-row:not(.dragging)')];

  return draggableElements.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;

    if (offset < 0 && offset > closest.offset) {
      return { offset: offset, element: child };
    } else {
      return closest;
    }
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function saveGroupsDisplaySettings() {
  const box = document.getElementById('groups-display-list');
  if (!box) return;

  const rows = box.querySelectorAll('.group-display-row');
  const order = [];
  const visible = [];

  rows.forEach(row => {
    const name = row.dataset.name;
    order.push(name);
    const cb = row.querySelector('.group-visible-cb');
    if (cb && cb.checked) visible.push(name);
  });

  try {
    localStorage.setItem('bot4vps_group_order', JSON.stringify(order));
    localStorage.setItem('bot4vps_visible_groups', JSON.stringify(visible));

    // Обновляем отображение серверов, если страница серверов открыта
    if (window.renderServers && typeof window.renderServers === 'function') {
      window.renderServers();
    }
    // Альтернативно через импорт, если доступен
    import('./servers.js').then(m => m.renderServers()).catch(() => {});
  } catch (e) {
    console.error('Failed to save group display settings', e);
  }
}

