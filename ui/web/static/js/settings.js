import { j, esc } from './api.js?v=20260821-telegram-health-v1';
import { toast, bindPasswordToggles, confirmAction, infoModal, syncServerClock, parseEmoji } from './ui.js';
import { loadUpdateState, showUpdateModal, showHistoryModal } from './monitor.js?v=20260915-taskfail-v2';
import { openBackupPasswordModal } from './backup-password.js?v=20260911-bpw-v16';

let account = { auth_enabled: false, username: 'admin' };
let selectedCategory = 'common';
let updateState = null;
let portPollTimer = null;
const numberTimers = new Map();

const THEME_KEY = 'bot4vps_theme';
const THEME_COLOR = { dark: '#0d1117', light: '#eaeff5', glass: '#0f233b' };
const THEMES = ['dark', 'light', 'glass'];

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (THEMES.includes(value)) return value;
    localStorage.setItem(THEME_KEY, 'dark');
  } catch (_) {}
  return 'dark';
}

function updateThemeChoices(resolved) {
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    const active = button.dataset.themeChoice === resolved;
    button.classList.toggle('on', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function applyTheme(value) {
  const resolved = ['light', 'glass'].includes(value) ? value : 'dark';
  if (resolved === 'dark') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', resolved);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[resolved]);
  updateThemeIcon(resolved);
  updateThemeChoices(resolved);
  window.dispatchEvent(new CustomEvent('bot4vps:theme', { detail: { resolved } }));
}

function updateThemeIcon(resolved) {
  const button = document.getElementById('theme-toggle');
  if (!button) return;
  const stroke = resolved === 'light' ? '#1a1a1a' : '#ffffff';
  // Три темы — три иконки: солнце / луна / капля («Синяя»)
  const icons = {
    light: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`,
    dark: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`,
    glass: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"></path></svg>`,
  };
  button.innerHTML = icons[resolved] || icons.dark;
  const titles = { dark: 'Тема: тёмная', light: 'Тема: светлая', glass: 'Тема: синяя' };
  button.title = titles[resolved] || 'Переключить тему';
}

function setTheme(value) {
  // localStorage — кэш мгновенной отрисовки; сервер (config.json) — источник
  // истины, тема переживает сброс кеша браузера. POST best-effort: косметика.
  try { localStorage.setItem(THEME_KEY, value); } catch (_) {}
  applyTheme(value);
  j('/api/settings/theme', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme: value }),
  }).catch(() => {});
}

function handleThemeToggle() {
  // Три темы по кругу: тёмная → светлая → синяя → тёмная.
  // Текущую берём из data-theme (dark = атрибута нет), а не из
  // бинарного hasAttribute — иначе «синяя» считалась бы светлой.
  const attr = document.documentElement.getAttribute('data-theme');
  const current = (attr === 'light' || attr === 'glass') ? attr : 'dark';
  setTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
}

export function initTheme() {
  applyTheme(storedTheme());
  // Локальное значение рисуется сразу (без FOUC); серверная тема подтягивается
  // следом — после сброса кеша браузера именно она восстановит выбор.
  j('/api/settings/theme')
    .then(data => {
      const theme = data?.theme;
      if (THEMES.includes(theme) && theme !== storedTheme()) {
        try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
        applyTheme(theme);
      }
    })
    .catch(() => {});
  const button = document.getElementById('theme-toggle');
  if (button && !button.dataset.themeBound) {
    button.dataset.themeBound = '1';
    button.addEventListener('click', handleThemeToggle);
  }
}

const categories = [
  { id: 'common', icon: '◉', title: 'Общие', subtitle: 'Мониторинг и интерфейс', render: renderCommon },
  { id: 'web', icon: '🛡', title: 'Безопасность', subtitle: 'Вход, 2FA, мастер-ключ, порт', render: renderWeb },
  { id: 'telegram', icon: '↗', title: 'Telegram', subtitle: 'Бот и получатель', render: renderTelegram },
  { id: 'data', icon: '▤', title: 'История и данные', subtitle: 'Лимиты хранения', render: renderData },
  { id: 'updates', icon: '⇧', title: 'Обновления', subtitle: 'Проверка и установка', render: renderUpdates },
  { id: 'about', icon: 'i', title: 'О программе', subtitle: 'Версия и проект', render: renderAbout },
];

function settingRow(spec) {
  let control = '';
  if (spec.type === 'toggle') {
    control = `<label class="set-switch"><input id="${spec.id}" type="checkbox" ${spec.value ? 'checked' : ''}><span class="set-switch-track"><span></span></span></label>`;
  } else if (spec.type === 'number') {
    control = `<input class="set-number" id="${spec.id}" type="number" value="${esc(spec.value)}" min="${spec.min ?? 1}" max="${spec.max ?? 10000}" inputmode="numeric">`;
  } else if (spec.type === 'theme') {
    control = `<div class="set-theme-choices" role="group" aria-label="Тема интерфейса"><button type="button" class="secondary" id="set-theme-light" data-theme-choice="light" aria-pressed="${spec.value === 'light'}">Светлая</button><button type="button" class="secondary" id="set-theme-dark" data-theme-choice="dark" aria-pressed="${spec.value === 'dark'}">Тёмная</button><button type="button" class="secondary" id="set-theme-glass" data-theme-choice="glass" aria-pressed="${spec.value === 'glass'}">Синяя</button></div>`;
  } else if (spec.type === 'select') {
    // Часовые пояса приходят группами по смещению («UTC-3» → все города пояса),
    // прочие списки — плоским options.
    const inner = Array.isArray(spec.groups) && spec.groups.length
      ? spec.groups.map(group => `<optgroup label="${esc(group.offset)}">${(group.zones || []).map(o => `<option value="${esc(o.value)}" ${o.value === spec.value ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</optgroup>`).join('')
      : (spec.options || []).map(o => `<option value="${esc(o.value)}" ${o.value === spec.value ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
    control = `<select id="${spec.id}" class="set-select ${esc(spec.controlClass || '')}">${inner}</select>`;
  } else if (spec.type === 'action') {
    control = `<button type="button" id="${spec.id}" class="${spec.danger ? 'danger' : 'secondary'}">${esc(spec.label)}</button>`;
  } else if (spec.type === 'badge') {
    control = `<span id="${spec.id}" class="set-badge ${esc(spec.tone || '')}">${esc(spec.value)}</span>`;
  }
  const dependency = spec.dependsOn
    ? ` data-depends-on="${esc(spec.dependsOn.id)}" data-depends-value="${esc(String(spec.dependsOn.value))}"`
    : '';
  const descriptionId = spec.descId ? ` id="${esc(spec.descId)}"` : '';
  return `<div class="set-row" data-setting="${esc(spec.id)}"${dependency}><div class="set-copy"><div class="set-name">${esc(spec.title)}</div><div class="set-desc"${descriptionId}>${esc(spec.desc || '')}</div></div><div class="set-ctrl">${control}</div></div>`;
}

function section(title, lead, rows, extra = '') {
  return `<section class="set-section"><div class="set-section-head"><h2>${esc(title)}</h2>${lead ? `<p>${esc(lead)}</p>` : ''}</div><div class="set-list">${rows.join('')}</div>${extra}</section>`;
}

function renderNav() {
  const nav = document.getElementById('settings-nav');
  if (!nav) return;
  nav.innerHTML = categories.map(c => `<button type="button" data-settings-category="${c.id}" class="${c.id === selectedCategory ? 'on' : ''}"><span class="settings-nav-icon">${c.icon}</span><span><strong>${esc(c.title)}</strong><small>${esc(c.subtitle)}</small></span></button>`).join('');
}

function setContentLoading() {
  const content = document.getElementById('settings-content');
  if (content) content.innerHTML = '<div class="set-loading">Загрузка настроек…</div>';
}

function clearNumberTimers() {
  numberTimers.forEach(timer => clearTimeout(timer));
  numberTimers.clear();
}

async function openCategory(id) {
  clearNumberTimers();
  const category = categories.find(item => item.id === id) || categories[0];
  selectedCategory = category.id;
  renderNav();
  setContentLoading();
  try {
    await category.render();
  } catch (error) {
    const content = document.getElementById('settings-content');
    if (content) content.innerHTML = `<div class="set-error"><strong>Не удалось загрузить раздел</strong><span>${esc(error.message || error)}</span><button type="button" class="secondary" id="settings-retry">Повторить</button></div>`;
    document.getElementById('settings-retry')?.addEventListener('click', () => openCategory(category.id));
  }
}

function updateDependentRows(sourceId, root = document) {
  const source = document.getElementById(sourceId);
  if (!source) return;
  const current = source.type === 'checkbox' ? String(source.checked) : String(source.value);
  root.querySelectorAll('[data-depends-on]').forEach(row => {
    if (row.dataset.dependsOn === sourceId) {
      row.hidden = current !== row.dataset.dependsValue;
    }
  });
}

function initializeSettingDependencies(root = document) {
  const sourceIds = new Set();
  root.querySelectorAll('[data-depends-on]').forEach(row => {
    if (row.dataset.dependsOn) sourceIds.add(row.dataset.dependsOn);
  });
  sourceIds.forEach(id => updateDependentRows(id, root));
}

function bindToggle(id, apply) {
  const input = document.getElementById(id);
  if (!input) return;
  let previous = input.checked;
  input.addEventListener('change', async () => {
    const next = input.checked;
    updateDependentRows(id);
    input.disabled = true;
    try {
      await apply(next);
      previous = next;
      flashRow(input, true);
    } catch (error) {
      input.checked = previous;
      toast(error.message || String(error), false);
      flashRow(input, false);
    } finally {
      input.disabled = false;
      updateDependentRows(id);
    }
  });
}

function bindNumber(id, apply, delay = 600) {
  const input = document.getElementById(id);
  if (!input) return;
  let previous = input.value;
  input.addEventListener('input', () => {
    clearTimeout(numberTimers.get(id));
    numberTimers.set(id, setTimeout(async () => {
      const value = Number(input.value);
      if (!Number.isInteger(value) || value < Number(input.min) || value > Number(input.max)) {
        input.value = previous;
        toast(`Допустимое значение: ${input.min}–${input.max}`, false);
        return;
      }
      input.disabled = true;
      try {
        await apply(value);
        previous = String(value);
        flashRow(input, true);
      } catch (error) {
        input.value = previous;
        toast(error.message || String(error), false);
        flashRow(input, false);
      } finally { input.disabled = false; }
    }, delay));
  });
}

function flashRow(control, ok) {
  const row = control.closest('.set-row');
  if (!row) return;
  row.classList.remove('set-row-ok', 'set-row-error');
  // Успешное сохранение больше не подсвечиваем — только ошибку.
  if (ok) return;
  void row.offsetWidth;
  row.classList.add('set-row-error');
  setTimeout(() => row.classList.remove('set-row-error'), 900);
}

async function patchMonitor(name, patch) {
  const result = await j('/api/monitor/config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, ...patch }),
  });
  return result.monitor;
}

function applyTimezoneMetadata(select, metadata, { replaceOptions = false } = {}) {
  if (!select || !metadata?.timezone) return;
  if (replaceOptions && Array.isArray(metadata.options)) {
    // Группы по смещению («UTC-3» → города пояса), как при первом рендере.
    select.innerHTML = metadata.options.map(group =>
      `<optgroup label="${esc(group.offset)}">${(group.zones || []).map(option =>
        `<option value="${esc(option.value)}">${esc(option.label)}</option>`).join('')}</optgroup>`).join('');
  }
  select.value = metadata.timezone;
  const selected = select.options[select.selectedIndex];
  if (selected && metadata.label) selected.textContent = metadata.label;
  select.title = selected?.textContent || metadata.timezone;
  syncServerClock(metadata);
}

function bindTimezoneSelect(initialMetadata) {
  const select = document.getElementById('set-timezone');
  const description = document.getElementById('set-timezone-desc');
  if (!select) return;
  const idleDescription = 'Меняет часовую зону локального хоста Bot4VPS.';
  let confirmed = initialMetadata.timezone;
  applyTimezoneMetadata(select, initialMetadata);

  select.addEventListener('change', async () => {
    const requested = select.value;
    select.disabled = true;
    select.setAttribute('aria-busy', 'true');
    if (description) description.textContent = 'Изменение часового пояса…';
    try {
      const result = await j('/api/settings/timezone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: requested }),
      });
      confirmed = result.timezone;
      applyTimezoneMetadata(select, result);
      flashRow(select, true);
      toast(`Часовой пояс сервера изменён: ${result.label}`, true);
    } catch (error) {
      try {
        const actual = await j('/api/settings/timezone');
        confirmed = actual.timezone;
        applyTimezoneMetadata(select, actual, { replaceOptions: true });
      } catch (_) {
        select.value = confirmed;
        select.title = select.options[select.selectedIndex]?.textContent || confirmed;
      }
      flashRow(select, false);
      toast(
        error?.message || 'Не удалось изменить часовой пояс сервера. Настройка не сохранена.',
        false,
      );
    } finally {
      if (description) description.textContent = idleDescription;
      select.disabled = false;
      select.removeAttribute('aria-busy');
    }
  });
}

async function renderCommon() {
  const [cfg, timezoneMetadata] = await Promise.all([
    j('/api/monitor/config'),
    j('/api/settings/timezone'),
  ]);
  const content = document.getElementById('settings-content');
  content.innerHTML = section('Общие', 'Параметры применяются сразу после изменения.', [
    settingRow({ id: 'set-online-enabled', type: 'toggle', title: 'Проверка доступности', desc: 'Автоматически проверять серверы по расписанию.', value: !!cfg.online?.enabled }),
    settingRow({ id: 'set-online-interval', type: 'number', title: 'Интервал Online', desc: 'Период между проверками, в минутах.', value: cfg.online?.interval ?? 5, min: 1, max: 10080, dependsOn: { id: 'set-online-enabled', value: true } }),
    '<div class="set-divider" role="separator"></div>',
    settingRow({ id: 'set-ssl-enabled', type: 'toggle', title: 'Проверка SSL', desc: 'Следить за сроком действия сертификатов.', value: !!cfg.ssl?.enabled }),
    settingRow({ id: 'set-ssl-interval', type: 'number', title: 'Интервал SSL', desc: 'Период между проверками, в минутах.', value: cfg.ssl?.interval ?? 60, min: 1, max: 10080, dependsOn: { id: 'set-ssl-enabled', value: true } }),
    '<div class="set-divider" role="separator"></div>',
    settingRow({ id: 'set-timezone', type: 'select', title: 'Часовой пояс сервера', desc: 'Меняет часовую зону локального хоста Bot4VPS.', descId: 'set-timezone-desc', value: timezoneMetadata.timezone, groups: timezoneMetadata.options, controlClass: 'set-timezone-select' }),
    '<div class="set-divider" role="separator"></div>',
    settingRow({ id: 'set-theme', type: 'theme', title: 'Тема интерфейса', desc: 'Сохраняется на сервере и восстанавливается в любом браузере.', value: storedTheme() }),
  ]);
  bindToggle('set-online-enabled', enabled => patchMonitor('online', { enabled }));
  bindNumber('set-online-interval', interval => patchMonitor('online', { interval }));
  bindToggle('set-ssl-enabled', enabled => patchMonitor('ssl', { enabled }));
  bindNumber('set-ssl-interval', interval => patchMonitor('ssl', { interval }));
  bindTimezoneSelect(timezoneMetadata);
  initializeSettingDependencies(content);
  document.getElementById('set-theme-light')?.addEventListener('click', () => { setTheme('light'); flashRow(document.getElementById('set-theme-light'), true); });
  document.getElementById('set-theme-dark')?.addEventListener('click', () => { setTheme('dark'); flashRow(document.getElementById('set-theme-dark'), true); });
  document.getElementById('set-theme-glass')?.addEventListener('click', () => { setTheme('glass'); flashRow(document.getElementById('set-theme-glass'), true); });
}

export async function loadAccount() {
  try { account = await j('/api/auth/account'); } catch (_) {}
  const userLabel = document.getElementById('acc-user-label');
  if (userLabel) userLabel.textContent = account.username || 'admin';
  const status = document.getElementById('acc-status');
  if (status) {
    status.textContent = account.auth_enabled ? 'Защита включена' : 'Локальный режим';
    status.className = `set-badge ${account.auth_enabled ? 'ok' : ''}`;
  }
  const toggle = document.getElementById('acc-auth-toggle');
  if (toggle && document.activeElement !== toggle) toggle.checked = !!account.auth_enabled;
  const desc = document.getElementById('acc-auth-desc');
  if (desc) {
    desc.textContent = account.auth_enabled
      ? 'Вход в панель по логину и паролю'
      : 'Вход без пароля — панель доступна всем, у кого есть адрес';
  }
}

// ── Учётная запись: смена пароля / смена логина / защита ─────────────

let accountModalClose = null;

/** Каркас модалки учётной записи: Esc + Отмена, без клика по фону. */
function accountModal(title, bodyHtml, onOk, okText = 'Сохранить') {
  document.getElementById('settings-acc-modal')?.remove();
  const modal = document.createElement('div');
  modal.id = 'settings-acc-modal';
  modal.className = 'modal-bg open';
  modal.innerHTML = `<div class="modal set-tls-form-modal" role="dialog" aria-modal="true">
      <h3>${esc(title)}</h3>
      <div class="set-tls-upload">${bodyHtml}</div>
      <div class="set-form-actions"><button type="button" id="acc-modal-ok">${esc(okText)}</button><button type="button" class="secondary" id="acc-modal-cancel">Отмена</button></div>
    </div>`;
  document.body.appendChild(modal);
  const close = () => {
    modal.remove();
    document.removeEventListener('keydown', onKey);
    accountModalClose = null;
  };
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  document.getElementById('acc-modal-cancel')?.addEventListener('click', close);
  document.getElementById('acc-modal-ok')?.addEventListener('click', () => onOk(close));
  modal.querySelectorAll('input').forEach(input => {
    input.addEventListener('keydown', e => { if (e.key === 'Enter') onOk(close); });
  });
  bindPasswordToggles();
  accountModalClose = close;
  setTimeout(() => modal.querySelector('input')?.focus(), 30);
  return close;
}

/** «Изменить пароль»: старый (когда пароль задан — даже при выключенной
    защите) + новый дважды (подтверждение против опечаток). */
function accountPasswordModal() {
  const needOld = !!(account.has_password || account.auth_enabled);
  const rows = `
    ${needOld ? `<label>Старый пароль<span class="pw-wrap"><input id="acc-old" type="password" autocomplete="current-password"><button type="button" class="eye" data-pw-toggle="acc-old">👁</button></span></label>` : ''}
    <label>Новый пароль<span class="pw-wrap"><input id="acc-pass" type="password" autocomplete="new-password"><button type="button" class="eye" data-pw-toggle="acc-pass">👁</button></span><small>Не короче 6 символов.</small></label>
    <label>Новый пароль ещё раз<span class="pw-wrap"><input id="acc-pass2" type="password" autocomplete="new-password"><button type="button" class="eye" data-pw-toggle="acc-pass2">👁</button></span><small>Чтобы исключить опечатки.</small></label>`;
  accountModal('Изменить пароль', rows, async close => {
    const newPassword = document.getElementById('acc-pass')?.value || '';
    const repeat = document.getElementById('acc-pass2')?.value || '';
    if (newPassword.length < 6) return toast('Пароль не короче 6 символов', false);
    if (newPassword !== repeat) return toast('Пароли не совпадают — проверьте ввод', false);
    const body = { new_password: newPassword };
    if (needOld) body.old = document.getElementById('acc-old')?.value || '';
    try {
      account = await j('/api/auth/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      close();
      toast('Пароль изменён', true);
    } catch (error) { toast(error.message, false); }
  }, 'Сохранить');
}

/** Клик по логину: смена логина с подтверждением и финальной
    подсказкой про новый логин для входа. */
function accountLoginModal() {
  const current = account.username || 'admin';
  const rows = `
    <p class="set-desc">Ваш текущий логин — <b>${esc(current)}</b></p>
    <label>Новый логин<input id="acc-user" type="text" autocomplete="username" spellcheck="false"></label>
    <p class="set-desc">Логин чувствителен к регистру: <b>Admin</b> и <b>admin</b> — разные логины.</p>`;
  accountModal('Хотите изменить логин?', rows, async close => {
    const username = (document.getElementById('acc-user')?.value || '').trim();
    if (!username) return toast('Логин не может быть пустым', false);
    if (username === current) return toast('Новый логин совпадает с текущим', false);
    try {
      account = await j('/api/auth/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
      close();
      await loadAccount();
      await infoModal({
        title: 'Логин изменён',
        message: `Для авторизации теперь используйте новый логин: ${username}`,
        okText: 'Ок',
      });
    } catch (error) { toast(error.message, false); }
  }, 'Изменить');
}

export async function toggleAuth(e) {
  const input = document.getElementById('acc-auth-toggle');
  // Тумблер уже переключился визуально — при отмене возвращаем назад.
  if (e?.target?.type === 'checkbox') e.target.checked = !e.target.checked;
  const next = !account.auth_enabled;
  if (next) {
    // Включение ничего не срезает — обычное подтверждение.
    const message = 'Включить защиту входа? После этого потребуется логин и пароль.';
    if (!await confirmAction({ message, confirmFirst: true })) return;
    try {
      await j('/api/auth/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auth_enabled: true }) });
      // Сервер сжёг текущую сессию — перезагрузка откроет экран входа.
      toast('Защита включена — войдите с логином и паролем', true);
      setTimeout(() => location.reload(), 800);
    } catch (error) {
      if (input) input.checked = account.auth_enabled;
      toast(error.message, false);
    }
    return;
  }
  // Выключение срезает всю защиту (включая 2FA де-факто) — подтверждение
  // владельца: старый пароль + код второго фактора, если тот настроен.
  accountDisableAuthModal();
}

/** Шаг 1 отключения защиты: старый пароль → код второго фактора (если есть). */
function accountDisableAuthModal() {
  const rows = `
    <p class="set-desc">Панель станет доступна без пароля всем, у кого есть доступ к сети сервера.</p>
    <label>Старый пароль<span class="pw-wrap"><input id="dis-old" type="password" autocomplete="current-password"><button type="button" class="eye" data-pw-toggle="dis-old">👁</button></span></label>`;
  accountModal('Выключить защиту входа', rows, async close => {
    const old = document.getElementById('dis-old')?.value || '';
    let resp;
    try {
      resp = await j('/api/auth/disable', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ old }) });
    } catch (error) { toast(error.message, false); return; }
    close();
    if (resp.disabled) {
      toast('Защита выключена', true);
      setTimeout(() => location.reload(), 500);
      return;
    }
    accountDisableCodeModal(resp.channel);
  }, 'Продолжить');
}

/** Шаг 2: код из приложения-аутентификатора (totp) или из Telegram. */
function accountDisableCodeModal(channel) {
  const isTotp = channel === 'totp';
  const hint = isTotp
    ? 'Код из приложения-аутентификатора'
    : 'Код подтверждения отправлен в Telegram';
  const rows = `
    <p class="set-desc">${esc(hint)}. Действует 10 минут.</p>
    <label>Код подтверждения<span class="pw-wrap"><input id="dis-code" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="000000"></span></label>
    ${isTotp ? '' : `<p class="set-desc"><a href="#" id="dis-resend">Не пришёл код? Отправить ещё раз</a></p>`}`;
  accountModal('Подтвердите отключение', rows, async close => {
    const code = document.getElementById('dis-code')?.value || '';
    try {
      await j('/api/auth/disable/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
      close();
      toast('Защита выключена', true);
      setTimeout(() => location.reload(), 500);
    } catch (error) { toast(error.message, false); }
  }, 'Выключить защиту');
  document.getElementById('dis-resend')?.addEventListener('click', async event => {
    event.preventDefault();
    try {
      await j('/api/auth/disable/resend', { method: 'POST' });
      toast('Новый код отправлен в Telegram', true);
    } catch (error) { toast(error.message, false); }
  });
}

// ---------------- Мастер-ключ (enc1:) ----------------
// Состояние-зависимая карточка: ok → просмотр с подтверждением;
// missing_with_data / mismatch → восстановление (ввести/создать новый);
// missing_no_data → ключа ещё нет (штатно, создастся при первом секрете).

const MK_FIELD_LABELS = {
  server_passwords: 'пароли серверов',
  bot_token: 'Telegram Bot Token',
  totp_secret: 'секрет 2FA',
};

let mkState = null;

function mkFieldList(fields) {
  return (fields || []).map(f => MK_FIELD_LABELS[f] || f).join(', ');
}

async function loadMasterKey() {
  const body = document.getElementById('mk-body');
  if (!body) return;
  try {
    mkState = await j('/api/masterkey/status');
  } catch (error) {
    body.innerHTML = `<p class="set-desc">${esc(error.message || 'Не удалось загрузить состояние мастер-ключа')}</p>`;
    return;
  }
  const state = mkState.state;
  if (state === 'ok') {
    body.innerHTML = `
      <p class="set-desc">Мастер-ключ на месте, зашифрованные данные расшифровываются.</p>
      <div class="set-form-actions"><button type="button" class="secondary" id="mk-view-btn">Посмотреть мастер-ключ</button></div>`;
    document.getElementById('mk-view-btn')?.addEventListener('click', openMasterKeyView);
  } else if (state === 'missing_no_data') {
    body.innerHTML = `<p class="set-desc">Зашифрованных данных пока нет — ключ будет создан автоматически при первом сохранении секрета.</p>`;
  } else {
    // missing_with_data / mismatch — нужен recovery
    const isMismatch = state === 'mismatch';
    body.innerHTML = `
      <p class="set-desc mk-restore-note" style="color:var(--err)">⚠️ ${isMismatch
        ? 'Ключ не подходит к зашифрованным данным:'
        : 'Ключ отсутствует, зашифрованы:'} ${esc(mkFieldList(mkState.encrypted_fields))}.</p>
      <div class="set-form mk-restore-form">
        <label>Мастер-ключ<span class="pw-wrap"><input id="mk-restore-key" type="password" autocomplete="off" spellcheck="false" placeholder="Fernet-ключ (base64)"><button type="button" class="eye" data-pw-toggle="mk-restore-key">👁</button></span></label>
        <div id="mk-restore-err" class="err-hint"></div>
        <div class="set-form-actions"><button type="button" id="mk-restore-btn">Ввести мастер-ключ</button><button type="button" class="danger" id="mk-new-btn">Создать новый</button></div>
      </div>`;
    bindPasswordToggles();
    document.getElementById('mk-restore-btn')?.addEventListener('click', masterKeyRestore);
    document.getElementById('mk-restore-key')?.addEventListener('keydown', e => { if (e.key === 'Enter') masterKeyRestore(); });
    document.getElementById('mk-new-btn')?.addEventListener('click', masterKeyNewConfirm);
  }
  // Незашифрованные секреты (например, перенесённые файлами со старой
  // установки). Кнопка — только когда ключ жив (иначе сначала recovery):
  // шифровать нечем. После успеха скан пуст и кнопка исчезает.
  const plain = mkState.plaintext;
  if (plain?.found && (state === 'ok' || state === 'missing_no_data')) {
    body.insertAdjacentHTML('beforeend', `
      <p class="set-desc mk-plaintext-note" style="color:var(--err)">⚠️ Обнаружены незашифрованные секреты: ${esc(mkPlaintextList(plain.items))}.</p>
      <button type="button" class="modest-link" id="mk-encrypt-btn" title="Зашифровать все найденные секреты мастер-ключом">Зашифровать все секреты</button>`);
    document.getElementById('mk-encrypt-btn')?.addEventListener('click', encryptAllSecrets);
  }
}

function mkPlaintextList(items) {
  return (items || [])
    .map(it => it.count > 1 ? `${it.label} (${it.count})` : it.label)
    .join(', ');
}

async function encryptAllSecrets() {
  const btn = document.getElementById('mk-encrypt-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await j('/api/masterkey/encrypt-secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
    const list = mkPlaintextList((res?.plaintext?.items) || []);
    // Инвариант: после успеха повторный скан показывает 0 находок —
    // кнопка исчезает при перерисовке loadMasterKey().
    toast(list ? `Остались незашифрованные секреты: ${list}` : 'Все секреты зашифрованы', !list);
    await loadMasterKey();
  } catch (error) {
    toast(error.message || 'Не удалось зашифровать секреты', false);
    if (btn) btn.disabled = false;
  }
}

async function masterKeyRestore() {
  const key = (document.getElementById('mk-restore-key')?.value || '').trim();
  const err = document.getElementById('mk-restore-err');
  if (err) err.textContent = '';
  if (!key) {
    if (err) err.textContent = 'Введите мастер-ключ';
    return;
  }
  const btn = document.getElementById('mk-restore-btn');
  if (btn) btn.disabled = true;
  try {
    await j('/api/masterkey/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key }) });
    toast('Мастер-ключ восстановлен — данные снова расшифровываются', true);
    await loadMasterKey();
    window.dispatchEvent(new CustomEvent('bot4vps:masterkey-changed'));
  } catch (error) {
    if (err) err.textContent = error.message || 'Не удалось восстановить';
    const field = document.getElementById('mk-restore-key');
    if (field) { field.value = ''; field.focus(); }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function masterKeyNewConfirm() {
  const fields = mkFieldList(mkState?.encrypted_fields);
  const ok = await confirmAction({
    message: `⚠️ ВНИМАНИЕ!\n\nОбнаружены зашифрованные данные (${fields}), для которых отсутствует подходящий мастер-ключ.\n\nСоздание нового мастер-ключа приведёт к потере доступа к ним. После создания может потребоваться заново указать:\n• пароли доступа к серверам;\n• Telegram Bot Token;\n• настройки двухфакторной аутентификации.\n\nЭто действие нельзя отменить без восстановления старого мастер-ключа.\n\nПродолжить?`,
    confirmFirst: true,
    confirmLabel: 'Создать новый мастер-ключ',
    danger: true,
  });
  if (!ok) return;
  const err = document.getElementById('mk-restore-err');
  try {
    const res = await j('/api/masterkey/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true }) });
    toast(`Создан новый мастер-ключ${res.cleared?.length ? ' — очищено: ' + res.cleared.join(', ') : ''}`, true);
    await loadMasterKey();
    window.dispatchEvent(new CustomEvent('bot4vps:masterkey-changed'));
  } catch (error) {
    if (err) err.textContent = error.message || 'Не удалось создать ключ';
  }
}

// ---------------- Пароль резервных копий (B4VE) ----------------
// Один общий пароль: он защищает архивы тех целей, у которых во вкладке
// «Настройки» страницы Резервные копии включена галочка защиты. Здесь —
// только управление самим паролем (задать/изменить/удалить). Смена и
// удаление требуют ввода текущего пароля: тот, кто просто попал в панель,
// не должен молча отключить шифрование архивов.

let backupPasswordConfigured = false;

async function loadBackupPassword() {
  const body = document.getElementById('bpw-body');
  const status = document.getElementById('bpw-status');
  if (!body) return;
  let data = null;
  try {
    data = await j('/api/settings/backup-password');
  } catch (error) {
    body.innerHTML = `<p class="set-desc">${esc(error.message || 'Не удалось загрузить настройки пароля резервных копий')}</p>`;
    if (status) status.textContent = 'Ошибка';
    return;
  }
  backupPasswordConfigured = data?.configured === true;
  const protectedTargets = Number(data?.protected_targets || 0);
  if (status) {
    status.textContent = backupPasswordConfigured ? 'Задан' : 'Не задан';
    status.className = `set-badge ${backupPasswordConfigured ? 'ok' : ''}`;
  }
  if (!backupPasswordConfigured) {
    body.innerHTML = `
      <div class="set-form-actions"><span class="set-desc">Пароль не задан — новые резервные копии создаются без шифрования.</span><button type="button" id="bpw-set">Задать пароль</button></div>
      <p class="set-desc">Пароль постоянный: он потребуется для распаковки архива на другом сервере. Защита включается отдельно для каждой цели во вкладке «Настройки» страницы Резервные копии.</p>`;
  } else {
    body.innerHTML = `
      <div class="set-form-actions"><span class="set-desc">Пароль: ••••••••</span><button type="button" class="secondary" id="bpw-change">Изменить пароль</button><button type="button" class="secondary" id="bpw-remove">Удалить пароль</button></div>
      <p class="set-desc">Применяется к новым резервным копиям целей с включённой защитой${protectedTargets ? ` (сейчас: ${protectedTargets})` : ''}. Старые архивы открываются своим паролем.</p>`;
  }
  document.getElementById('bpw-set')?.addEventListener('click', () => openBackupPasswordModal({ mode: 'set' }));
  document.getElementById('bpw-change')?.addEventListener('click', () => openBackupPasswordModal({ mode: 'change' }));
  document.getElementById('bpw-remove')?.addEventListener('click', () => removeBackupPassword());
}

// Модалка пароля шлёт событие после успешного сохранения — карточка
// перерисовывается сразу, без обновления страницы (loadBackupPassword сама
// выходит, если карточки нет в DOM).
window.addEventListener('bot4vps:backup-password-changed', () => { loadBackupPassword(); });
// Пароль могли удалить и из консоли (CLI: Безопасность → «Очистить пароль
// резервных копий»), а секреты — зашифровать из CLI/TG — при возврате к
// Web-вкладке перечитываем карточки (кнопка «Зашифровать все секреты»
// должна исчезнуть; обе функции сами выходят, если карточек нет в DOM).
window.addEventListener('focus', () => { loadBackupPassword(); loadMasterKey(); });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { loadBackupPassword(); loadMasterKey(); }
});
// Вкладка не теряла фокус (CLI по SSH рядом, вторая сессия Web) — focus
// не сработает. SSE присылает сигнатуру файлов секретов: изменилась —
// перечитываем карточки, не дожидаясь переключения окон. Не мешаем
// пользователю: при открытой модалке или фокусе в поле карточки пропускаем
// (перерисовка стёрла бы ввод; следующий цикл подтянет изменения).
window.addEventListener('bot4vps:security-changed', () => {
  if (document.hidden) return;
  if (document.querySelector('.modal-bg.open')) return;
  const active = document.activeElement;
  if (active && (active.closest('#mk-body') || active.closest('#bpw-body'))) return;
  loadBackupPassword();
  loadMasterKey();
});

async function removeBackupPassword() {
  const approved = await confirmAction({
    title: 'Удалить пароль резервных копий?',
    message: '⚠️ Вы действительно хотите удалить пароль резервных копий?\n'
      + 'После очистки новые архивы защищённых целей не смогут быть зашифрованы, пока не будет задан новый пароль.\n'
      + 'Старые зашифрованные архивы продолжат требовать свои пароли.',
    confirmText: 'Удалить',
    confirmFirst: true,
    danger: true,
  });
  if (!approved) return;
  // Ослабление защиты подтверждается текущим паролем — он вводится прямо
  // в модалке удаления.
  openBackupPasswordModal({ mode: 'remove' });
}

// Просмотр ключа: пароль → (код 2FA | код в Telegram) → ключ.
// Ключ не уходит ни в логи, ни в историю, ни в TG.
async function openMasterKeyView() {
  const modal = document.getElementById('mk-view-modal');
  if (!modal) return;
  document.getElementById('mk-view-pass')?.focus();
  modal.classList.add('open');
}

function closeMasterKeyView() {
  document.getElementById('mk-view-modal')?.classList.remove('open');
  // Очистка: пароль и ключ не остаются в DOM дольше нужного
  const pass = document.getElementById('mk-view-pass');
  const code = document.getElementById('mk-view-code');
  const keyOut = document.getElementById('mk-view-key');
  if (pass) pass.value = '';
  if (code) code.value = '';
  if (keyOut) keyOut.textContent = '';
  const err = document.getElementById('mk-view-err');
  if (err) err.textContent = '';
  mkViewChannel = null;
  hideNoCodeHint();
  hideMasterKeyResult();
}

let mkViewChannel = null;
let mkKeyValue = null;
let mkNoCodeTimer = null;
let mkResendTimer = null;
// Момент (Date.now) первой/последней отправки TG-кода — resend-кнопка
// активна через 2 минуты (сервер дублирует проверку).
let mkCodeSentAt = 0;

/* «Не пришёл код?» + «Отправить код ещё раз»: появляются через 10 секунд
   после отправки TG-кода (если код пришёл, кнопки просто не замечаются).
   Resend активен через 2 минуты: раньше новый код бессмыслен, старый мог
   просто задержаться в доставке. Никаких советов включить 2FA: вводящий
   пароль не обязательно владелец. */
function hideNoCodeHint() {
  if (mkNoCodeTimer) { clearTimeout(mkNoCodeTimer); mkNoCodeTimer = null; }
  if (mkResendTimer) { clearTimeout(mkResendTimer); mkResendTimer = null; }
  document.getElementById('mk-view-nocode-actions')?.classList.add('hidden');
  document.getElementById('mk-view-nocode-hint')?.classList.add('hidden');
  const resend = document.getElementById('mk-view-resend-btn');
  if (resend) { resend.disabled = true; resend.textContent = 'Отправить код ещё раз'; }
}

function scheduleNoCodeHint(resent) {
  hideNoCodeHint();
  if (mkViewChannel !== 'telegram') return;
  if (resent) mkCodeSentAt = Date.now();
  if (!mkCodeSentAt) mkCodeSentAt = Date.now();
  mkNoCodeTimer = setTimeout(() => {
    mkNoCodeTimer = null;
    document.getElementById('mk-view-nocode-actions')?.classList.remove('hidden');
    // Resend-кнопка активируется через 2 минуты от отправки кода
    const resend = document.getElementById('mk-view-resend-btn');
    if (resend) {
      const updateResend = () => {
        const left = 120 - Math.floor((Date.now() - mkCodeSentAt) / 1000);
        if (left > 0) {
          resend.disabled = true;
          resend.textContent = `Отправить код ещё раз (через ${left} с)`;
          mkResendTimer = setTimeout(updateResend, 1000);
        } else {
          resend.disabled = false;
          resend.textContent = 'Отправить код ещё раз';
        }
      };
      updateResend();
    }
  }, 10000);
}

/** Повторная отправка TG-кода: новый код стирает старый (на сервере). */
async function masterKeyResendCode() {
  const resend = document.getElementById('mk-view-resend-btn');
  if (resend) resend.disabled = true;
  const err = document.getElementById('mk-view-err');
  try {
    const res = await j('/api/masterkey/view/resend', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
    if (err) err.textContent = '';
    if (res.resent) {
      toast('Новый код отправлен в Telegram — предыдущий больше не действует', true);
      scheduleNoCodeHint(true);
    }
  } catch (error) {
    if (resend) resend.disabled = false;
    if (err) err.textContent = error.message;
  }
}

function hideMasterKeyResult() {
  document.getElementById('mk-view-confirm-step')?.classList.add('hidden');
  document.getElementById('mk-view-result')?.classList.add('hidden');
  const step1 = document.getElementById('mk-view-step1');
  if (step1) step1.classList.remove('hidden');
  // Кнопки обратно к шагу 1: «Продолжить» видна, «Подтвердить» скрыта
  document.getElementById('mk-view-start-btn')?.classList.remove('hidden');
  document.getElementById('mk-view-confirm-btn')?.classList.add('hidden');
  // Ширина — стандартная (расширение только на финальном шаге с ключом)
  document.querySelector('#mk-view-modal .mk-view-modal')?.classList.remove('wide');
  // Ключ спрятан, иконка — исходная
  mkKeyRevealed = false;
  const revealBtn = document.getElementById('mk-view-reveal-btn');
  if (revealBtn) { revealBtn.textContent = '👁'; revealBtn.title = 'Показать ключ'; parseEmoji(revealBtn); }
}

async function masterKeyViewStart() {
  const pass = (document.getElementById('mk-view-pass')?.value || '').trim();
  const err = document.getElementById('mk-view-err');
  if (err) err.textContent = '';
  if (!pass) {
    if (err) err.textContent = 'Введите пароль';
    return;
  }
  const btn = document.getElementById('mk-view-start-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await j('/api/masterkey/view', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pass }) });
    mkViewChannel = res.channel;
    const step1 = document.getElementById('mk-view-step1');
    const step2 = document.getElementById('mk-view-confirm-step');
    if (step1) step1.classList.add('hidden');
    if (step2) step2.classList.remove('hidden');
    // Переключаем и кнопки: «Подтвердить» вместо «Продолжить»
    document.getElementById('mk-view-start-btn')?.classList.add('hidden');
    document.getElementById('mk-view-confirm-btn')?.classList.remove('hidden');
    const codeInput = document.getElementById('mk-view-code');
    if (codeInput) { codeInput.value = ''; codeInput.focus(); }
    const codeLabel = document.getElementById('mk-view-code-label');
    if (codeLabel) {
      codeLabel.textContent = mkViewChannel === 'totp'
        ? 'Код из приложения-аутентификатора'
        : 'Код из Telegram (отправлен вам в личку)';
    }
    // Пароль больше не нужен в DOM
    const passField = document.getElementById('mk-view-pass');
    if (passField) passField.value = '';
    // res.resent=false — живой код переиспользован (окно открыли заново):
    // таймеры продолжают считать от исходной отправки, код не дублем.
    scheduleNoCodeHint(res.resent !== false);
  } catch (error) {
    // 403 «каналов подтверждения нет» — не ошибка поля ввода, а вердикт:
    // закрываем окно просмотра и показываем отдельную модалку с «Ок»
    if (error.status === 403) {
      closeMasterKeyView();
      await infoModal({ title: 'Просмотр мастер-ключа недоступен', message: error.message });
    } else if (err) {
      err.textContent = error.message || 'Не удалось начать просмотр';
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function masterKeyViewConfirm() {
  const code = (document.getElementById('mk-view-code')?.value || '').trim();
  const err = document.getElementById('mk-view-err');
  if (err) err.textContent = '';
  if (!code) {
    if (err) err.textContent = 'Введите код подтверждения';
    return;
  }
  const btn = document.getElementById('mk-view-confirm-btn');
  if (btn) btn.disabled = true;
  try {
    const res = await j('/api/masterkey/view/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    mkKeyValue = res.key;
    hideNoCodeHint();
    const step2 = document.getElementById('mk-view-confirm-step');
    const result = document.getElementById('mk-view-result');
    if (step2) step2.classList.add('hidden');
    if (result) result.classList.remove('hidden');
    // Широким становится только финальный шаг с ключом (одна строка);
    // шаги пароля/кода остаются стандартной ширины.
    document.querySelector('#mk-view-modal .mk-view-modal')?.classList.add('wide');
    // Ключ стартует скрытым
    mkKeyRevealed = false;
    const revealBtn = document.getElementById('mk-view-reveal-btn');
    if (revealBtn) { revealBtn.textContent = '👁'; revealBtn.title = 'Показать ключ'; parseEmoji(revealBtn); }
    const keyOut = document.getElementById('mk-view-key');
    if (keyOut) keyOut.textContent = '•'.repeat(44);  // типичная длина Fernet-ключа
    const codeInput = document.getElementById('mk-view-code');
    if (codeInput) codeInput.value = '';
  } catch (error) {
    if (err) err.textContent = error.message || 'Неверный код';
    const codeInput = document.getElementById('mk-view-code');
    if (codeInput) { codeInput.value = ''; codeInput.focus(); }
  } finally {
    if (btn) btn.disabled = false;
  }
}

let mkKeyRevealed = false;

function masterKeyReveal() {
  const keyOut = document.getElementById('mk-view-key');
  const btn = document.getElementById('mk-view-reveal-btn');
  if (!keyOut || !mkKeyValue) return;
  // Переключатель: показал — прячет обратно (иконка, как глазки паролей)
  mkKeyRevealed = !mkKeyRevealed;
  keyOut.textContent = mkKeyRevealed ? mkKeyValue : '•'.repeat(mkKeyValue.length);
  if (btn) {
    btn.textContent = mkKeyRevealed ? '🙈' : '👁';
    btn.title = mkKeyRevealed ? 'Скрыть ключ' : 'Показать ключ';
    // Twemoji: иначе после клика системный шрифт рисует эмодзи крупнее
    parseEmoji(btn);
  }
}

async function masterKeyCopy() {
  if (!mkKeyValue) return;
  try { await writeClipboard(mkKeyValue); toast('Мастер-ключ скопирован', true); }
  catch (_) { toast('Не удалось скопировать — выделите ключ вручную', false); }
}

/* Копирование в буфер: navigator.clipboard есть только в защищённом
   контексте (HTTPS/localhost), панель обычно открыта по http://<ip>:порт —
   там используем скрытый textarea + execCommand (как в monitor.js). */
function writeClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, ta.value.length);
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('execCommand failed'));
    } catch (e) { reject(e); }
  });
}

function bindMasterKeyUI() {
  const modal = document.getElementById('mk-view-modal');
  if (!modal) return;
  // onclick (не addEventListener) — idempotent при повторном рендере
  document.getElementById('mk-view-start-btn').onclick = masterKeyViewStart;
  document.getElementById('mk-view-confirm-btn').onclick = masterKeyViewConfirm;
  document.getElementById('mk-view-cancel-btn').onclick = closeMasterKeyView;
  // «Не пришёл код?» → раскрыть подсказку про консоль (повторный клик прячет)
  document.getElementById('mk-view-nocode-btn').onclick = () => {
    document.getElementById('mk-view-nocode-hint')?.classList.toggle('hidden');
  };
  // Повторная отправка TG-кода (новый стирает старый)
  document.getElementById('mk-view-resend-btn').onclick = masterKeyResendCode;
  document.getElementById('mk-view-reveal-btn').onclick = masterKeyReveal;
  document.getElementById('mk-view-copy-btn').onclick = masterKeyCopy;
  document.getElementById('mk-view-pass').onkeydown = e => { if (e.key === 'Enter') masterKeyViewStart(); };
  document.getElementById('mk-view-code').onkeydown = e => { if (e.key === 'Enter') masterKeyViewConfirm(); };
  // Закрытие кликом мимо окна запрещено: только явная кнопка «Закрыть»
  // (или Esc ниже) — случайный клик по фону не должен прервать флоу
  // подтверждения и скрыть только что показанный ключ.
  modal.onmousedown = e => { if (e.target === modal) e.preventDefault(); };
  modal.onkeydown = e => { if (e.key === 'Escape') closeMasterKeyView(); };
}

// ---------------- Двухфакторная аутентификация (TOTP) ----------------
// Состояние карточки: {enabled} или {unavailable} (авторизация выключена).

async function loadTotp() {
  let state;
  try {
    state = await j('/api/auth/totp');
  } catch (_) {
    // 400 «Авторизация выключена»: без пароля 2FA не имеет смысла
    state = { unavailable: true };
  }
  const body = document.getElementById('totp-body');
  const badge = document.getElementById('totp-status');
  if (!body || !badge) return;

  if (state.unavailable) {
    badge.textContent = 'Недоступна';
    badge.className = 'set-badge';
    body.innerHTML = `<p class="set-desc">Сначала включите защиту входа (пароль) — без неё двухфакторная аутентификация не нужна.</p>`;
    return;
  }
  if (state.enabled) {
    badge.textContent = 'Включена';
    badge.className = 'set-badge ok';
    body.innerHTML = `
      <p class="set-desc">Вход требует пароль <b>и</b> код из приложения-аутентификатора. Потеряли телефон? Сбросьте 2FA в консоли на сервере: bot4vps → 2. Безопасность → 4. Сбросить двухфакторную аутентификацию.</p>
      <div class="set-form-actions"><button type="button" class="secondary" id="totp-disable-btn">Отключить</button></div>`;
    document.getElementById('totp-disable-btn')?.addEventListener('click', renderTotpDisableForm);
    return;
  }
  badge.textContent = 'Выключена';
  badge.className = 'set-badge';
  body.innerHTML = `
    <p class="set-desc">Второй фактор помимо пароля: одноразовый код из приложения (Google Authenticator, Aegis, 2FAS). Без него пароль сам по себе вход не откроет.</p>
    <div class="set-form-actions"><button type="button" id="totp-enable-btn">Включить</button></div>`;
  document.getElementById('totp-enable-btn')?.addEventListener('click', openTotpSetup);
}

function renderTotpDisableForm() {
  const body = document.getElementById('totp-body');
  if (!body) return;
  body.innerHTML = `
    <p class="set-desc">Отключение требует действующий код из приложения — защита от случайного клика.</p>
    <label>Код из приложения<input id="totp-disable-code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="000000"></label>
    <div class="set-form-actions"><button type="button" class="secondary" id="totp-disable-confirm">Отключить</button><button type="button" class="secondary" id="totp-disable-cancel">Отмена</button></div>`;
  document.getElementById('totp-disable-cancel')?.addEventListener('click', loadTotp);
  document.getElementById('totp-disable-confirm')?.addEventListener('click', confirmTotpDisable);
  setTimeout(() => document.getElementById('totp-disable-code')?.focus(), 50);
}

async function confirmTotpDisable() {
  const code = (document.getElementById('totp-disable-code')?.value || '').trim();
  if (!code) return toast('Введите код из приложения', false);
  try {
    await j('/api/auth/totp/disable', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    toast('Двухфакторная аутентификация отключена', true);
    await loadTotp();
  } catch (error) { toast(error.message, false); }
}

async function openTotpSetup() {
  try {
    const data = await j('/api/auth/totp/setup', { method: 'POST' });
    document.getElementById('totp-qr').src = data.qr;
    document.getElementById('totp-secret').textContent = data.secret || '';
    document.getElementById('totp-code').value = '';
    document.getElementById('totp-setup-err').textContent = '';
    document.getElementById('totp-setup-modal')?.classList.add('open');
    setTimeout(() => document.getElementById('totp-code')?.focus(), 50);
  } catch (error) { toast(error.message, false); }
}

function closeTotpSetup() {
  document.getElementById('totp-setup-modal')?.classList.remove('open');
}

async function confirmTotpSetup() {
  const btn = document.getElementById('totp-setup-confirm');
  const field = document.getElementById('totp-code');
  const code = (field?.value || '').trim();
  const err = document.getElementById('totp-setup-err');
  if (err) err.textContent = '';
  if (!code) {
    if (err) err.textContent = 'Введите код из приложения';
    return;
  }
  if (btn) btn.disabled = true;
  try {
    await j('/api/auth/totp/enable', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    closeTotpSetup();
    toast('Двухфакторная аутентификация включена', true);
    await loadTotp();
  } catch (e) {
    if (err) err.textContent = e.message || 'Не удалось включить';
    // Поле очищаем: автоподтверждение на 6-й цифре сработает на повтор
    // без ручного стирания неверного кода
    if (field) {
      field.value = '';
      field.focus();
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Модалка 2FA — один экземпляр на страницу: везде onclick (не
// addEventListener), чтобы повторные вызовы bindTotpUI не плодили
// обработчики на одних и тех же кнопках.
function bindTotpUI() {
  const confirmBtn = document.getElementById('totp-setup-confirm');
  if (confirmBtn) confirmBtn.onclick = confirmTotpSetup;
  const cancelBtn = document.getElementById('totp-setup-cancel');
  if (cancelBtn) cancelBtn.onclick = closeTotpSetup;
  const copyBtn = document.getElementById('totp-secret-copy');
  if (copyBtn) copyBtn.onclick = async () => {
    const secret = document.getElementById('totp-secret')?.textContent || '';
    try { await writeClipboard(secret); toast('Ключ скопирован', true); }
    catch (_) { toast('Не удалось скопировать — выделите ключ вручную', false); }
  };
  const codeInput = document.getElementById('totp-code');
  if (codeInput) {
    codeInput.onkeydown = e => {
      if (e.key === 'Enter') confirmTotpSetup();
    };
    // Автоподтверждение как на экране входа: 6-я цифра отправляет код.
    // В setup это безопасно: неверный код не жжёт попытки и не трогает
    // pending-секрет — просто ждём следующий код.
    codeInput.oninput = () => {
      if ((codeInput.value || '').length >= 6) confirmTotpSetup();
    };
  }
}

const TLS_MODE_LABELS = {
  off: 'Выключен',
  letsencrypt: "Let's Encrypt",
  'self-signed': 'Самоподписанный',
  custom: 'Свой сертификат',
  proxy: 'За реверс-прокси',
};

let tlsState = null;   // последний ответ /api/settings/web/tls

async function renderWeb() {
  const [web, tls] = await Promise.all([
    j('/api/settings/web'),
    j('/api/settings/web/tls').catch(() => null),
    loadAccount(),
  ]);
  tlsState = tls;
  const portValue = web.port ?? location.port ?? 8000;
  const portReason = web.changeable ? 'Изменение перезапустит Bot4VPS и перенаправит браузер.' : (web.reason || 'Смена порта недоступна в этой среде.');
  const content = document.getElementById('settings-content');
  // Порт + HTTPS — одна карточка «Сеть и доступ» в правом столбце;
  // «Пароль резервных копий» уехал вниз на его прежнее полноширинное место.
  const netCard = `<div class="set-form-card"><div class="set-form-title"><div><h3>🌐 Сеть и доступ</h3><p>Порт панели и шифрование трафика (HTTPS).</p></div><span id="set-tls-state" class="set-badge">${tls ? '…' : 'Недоступно'}</span></div>
      <div id="set-tls-body" class="set-tls-body">${tls ? '' : '<p class="set-desc">Состояние HTTPS недоступно.</p>'}</div>
    </div>`;
  content.innerHTML = section('Безопасность', 'Вход в панель, 2FA, мастер-ключ и сетевой доступ Web-панели.', [], `
    <div class="set-web-cards">
      <div class="set-web-col">
        <div class="set-form-card"><div class="set-form-title"><div><h3>👤 Учётная запись</h3><p>Логин и пароль для входа в Web UI.</p></div><span id="acc-status" class="set-badge">…</span></div>
          <div class="set-acc-auth">
            <div class="set-acc-auth-head">
              <div class="set-acc-auth-text"><b>Авторизация по паролю</b><small id="acc-auth-desc">…</small></div>
              <label class="set-switch" id="acc-auth-wrap" title="${esc('Защита входа логином и паролем')}"><input type="checkbox" id="acc-auth-toggle"><span class="set-switch-track"><span></span></span></label>
            </div>
            <div class="set-tls-row"><span>Логин</span><button type="button" id="acc-user-label" class="modest-link" title="Нажмите, чтобы изменить логин">…</button></div>
            <div class="set-form-actions"><button type="button" class="secondary" id="acc-edit">Изменить пароль</button></div>
          </div>
        </div>
        <div class="set-form-card"><div class="set-form-title"><div><h3>🔒 Пароль резервных копий</h3><p>Общий пароль для защищённых архивов. Хранится зашифрованным мастер-ключом.</p></div><span id="bpw-status" class="set-badge">…</span></div>
          <div class="set-form" id="bpw-body"><p class="set-desc">Загрузка…</p></div>
        </div>
        <div class="set-form-card"><div class="set-form-title"><div><h3>🔑 Мастер-ключ</h3><p>Ключ шифрования секретов (пароли серверов, Telegram, 2FA).</p></div></div>
          <div class="set-form" id="mk-body"><p class="set-desc">Загрузка…</p></div>
        </div>
      </div>
      <div class="set-web-col">
        <div class="set-form-card"><div class="set-form-title"><div><h3>Двухфакторная аутентификация</h3><p>Код из приложения-аутентификатора при входе.</p></div><span id="totp-status" class="set-badge">…</span></div>
          <div class="set-form" id="totp-body"><p class="set-desc">Загрузка…</p></div>
        </div>
        ${netCard}
      </div>
    </div>`);
  await loadAccount();
  bindPasswordToggles();
  document.getElementById('acc-edit')?.addEventListener('click', accountPasswordModal);
  document.getElementById('acc-user-label')?.addEventListener('click', accountLoginModal);
  document.getElementById('acc-auth-toggle')?.addEventListener('change', toggleAuth);
  if (tls) renderTlsBody(tls, web);
  await loadTotp();
  bindTotpUI();
  await loadMasterKey();
  bindMasterKeyUI();
  await loadBackupPassword();
}

async function applyWebPort() {
  const input = document.getElementById('set-web-port');
  const port = Number(input?.value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return toast('Порт должен быть от 1 до 65535', false);
  if (!await confirmAction({ message: `Перезапустить Bot4VPS и перенести Web UI на порт ${port}?`, confirmFirst: true })) return;
  try {
    await j('/api/settings/web/port', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ port }) });
    showPortProgress(port);
  } catch (error) { toast(error.message, false); }
}

function showPortProgress(port) {
  document.getElementById('settings-port-progress')?.remove();
  const modal = document.createElement('div');
  modal.id = 'settings-port-progress';
  modal.className = 'modal-bg open';
  modal.innerHTML = `<div class="modal set-port-modal" role="dialog" aria-modal="true"><div class="set-spinner"></div><h3>Перезапуск Web UI</h3><p>Проверяем новый адрес…</p><code>${esc(`${location.protocol}//${location.hostname}:${port}`)}</code><div id="set-port-progress-note" class="hint">Не закрывайте эту вкладку.</div></div>`;
  document.body.appendChild(modal);
  const target = `${location.protocol}//${location.hostname}:${port}`;
  const started = Date.now();
  clearInterval(portPollTimer);
  portPollTimer = setInterval(async () => {
    try {
      await fetch(`${target}/api/upd/health?port_probe=${Date.now()}`, { mode: 'no-cors', cache: 'no-store' });
      clearInterval(portPollTimer);
      portPollTimer = null;
      location.replace(target);
    } catch (_) {
      if (Date.now() - started > 90000) {
        clearInterval(portPollTimer);
        portPollTimer = null;
        const note = document.getElementById('set-port-progress-note');
        if (note) note.innerHTML = `Автоматическое подключение не удалось. Откройте <a href="${esc(target)}">${esc(target)}</a>. Если запуск не удался, Bot4VPS вернёт прежний порт.`;
        modal.querySelector('.set-spinner')?.remove();
      }
    }
  }, 1800);
}

// ── HTTPS (Сеть и доступ) ──────────────────────────────────────────

function tlsCurrentMode(tls) {
  // Фактический режим: юнит — единственная правда о схеме; config может
  // отставать после сбоя (раннер откатывает юнит, config — нет).
  const cfgMode = tls?.config?.mode || 'off';
  const unitActive = !!(tls?.unit?.ssl || tls?.unit?.proxy);
  return unitActive ? cfgMode : 'off';
}

function renderTlsBody(tls, web) {
  const badge = document.getElementById('set-tls-state');
  const body = document.getElementById('set-tls-body');
  if (!body) return;
  const portValue = web?.port ?? location.port ?? 8000;
  const portDisabled = !(web?.changeable && !web?.busy) ? 'disabled' : '';
  if (!tls?.changeable) {
    if (badge) { badge.textContent = 'Недоступно'; badge.className = 'set-badge'; }
    body.innerHTML = `
      <div class="set-port-line"><label class="set-mini-label" for="set-web-port">Порт</label><input id="set-web-port" type="number" min="1" max="65535" value="${esc(portValue)}" ${portDisabled}><button type="button" id="set-web-port-apply" ${portDisabled}>Применить</button></div>
      <p class="set-desc">${esc(tls?.reason || 'Управление HTTPS недоступно в этой среде.')}</p>`;
    document.getElementById('set-web-port-apply')?.addEventListener('click', applyWebPort);
    return;
  }
  const mode = tlsCurrentMode(tls);
  const https = mode !== 'off';
  if (badge) {
    badge.textContent = https ? (TLS_MODE_LABELS[mode] || mode) : 'HTTP';
    badge.className = `set-badge ${https ? 'ok' : ''}`;
  }
  const cert = tls.cert;
  // Поля путей: текущая пара. Внешние пути — как есть; управляемые
  // режимы (LE/self-signed/upload) — пути в keys/web/.
  const cfgPaths = (tls.config.mode === 'custom' && tls.config.cert_path)
    ? tls.config
    : (https && tls.unit?.cert_path ? { cert_path: tls.unit.cert_path, key_path: tls.unit.key_path } : {});
  const busy = !!tls.busy;
  const toggleTitle = https
    ? 'Трафик шифруется: пароль и кука сессии защищены.'
    : 'Пароль и кука сессии ходят по сети открытым текстом.';
  let rows = '';
  if (https) {
    if (tls.config.domain) rows += `<div class="set-tls-row"><span>Домен</span><b>${esc(tls.config.domain)}</b></div>`;
    if (tls.config.trusted_proxies?.length) rows += `<div class="set-tls-row"><span>Доверенные proxy</span><b>${esc(tls.config.trusted_proxies.join(', '))}</b></div>`;
    // «Сертификат» живёт у тумблера, «Действует до» — у строки порта
    if (mode !== tls.config.mode) {
      rows += `<p class="set-desc tls-mismatch">⚠ Режим «${esc(TLS_MODE_LABELS[tls.config.mode] || tls.config.mode)}» задан, но панель сейчас работает без HTTPS — включите режим заново.</p>`;
    }
  }
  const expiry = cert
    ? `<span class="set-tls-expiry"><small>Действует</small> <b>до ${esc(String(cert.not_after || '').slice(0, 10))}</b> <small class="${(cert.days_left ?? 0) < 14 ? 'tls-days-warn' : ''}">(осталось ${cert.days_left ?? 0} дн.)</small></span>`
    : '';
  body.innerHTML = `
    <div class="set-tls-top">
      <div class="set-tls-toggle-row">
        <label class="set-switch" title="${esc(toggleTitle)}"><input type="checkbox" id="set-tls-toggle" ${https ? 'checked' : ''} ${busy ? 'disabled' : ''}><span class="set-switch-track"><span></span></span></label>
        <div class="set-tls-toggle-text" title="${esc(toggleTitle)}"><b>${https ? 'HTTPS' : 'HTTP'}</b><small>${https ? 'Трафик шифруется' : 'Без шифрования'}</small></div>
      </div>
      <div class="set-port-line"><label class="set-mini-label" for="set-web-port">Порт</label><input id="set-web-port" type="number" min="1" max="65535" value="${esc(portValue)}" ${portDisabled}><button type="button" id="set-web-port-apply" ${portDisabled}>Применить</button></div>
      ${cert ? `<span class="set-tls-toggle-cert" title="Субъект сертификата"><span>Сертификат</span><b>${esc(cert.subject || '—')}</b></span>` : ''}
      ${expiry}
    </div>
    ${rows}
    <div class="set-tls-paths">
      <p class="set-desc">Укажите адреса сертификата и ключа на сервере, чтобы включить HTTPS — или нажмите «Получить сертификат».</p>
      <label>Сертификат (PEM)<input id="set-tls-cert-path" type="text" placeholder="/etc/ssl/panel/cert.pem" value="${esc(cfgPaths.cert_path || '')}" spellcheck="false" autocomplete="off"></label>
      <label>Закрытый ключ (PEM)<input id="set-tls-key-path" type="text" placeholder="/etc/ssl/panel/key.pem" value="${esc(cfgPaths.key_path || '')}" spellcheck="false" autocomplete="off"></label>
    </div>
    <div class="set-form-actions set-tls-actions">
      <button type="button" id="set-tls-apply-paths" ${busy ? 'disabled' : ''}>Применить</button>
      <button type="button" class="secondary" id="set-tls-obtain" ${busy ? 'disabled' : ''}>Получить сертификат</button>
      <button type="button" class="secondary" id="set-tls-upload" ${busy ? 'disabled' : ''}>Загрузить сертификат</button>
      ${https ? `<button type="button" class="secondary" id="set-tls-renew" ${busy ? 'disabled' : ''}>Перевыпустить</button>` : ''}
    </div>
    ${busy ? '<p class="set-desc">Операция выполняется…</p>' : ''}`;
  document.getElementById('set-web-port-apply')?.addEventListener('click', applyWebPort);
  document.getElementById('set-tls-toggle')?.addEventListener('change', tlsToggleFlow);
  document.getElementById('set-tls-apply-paths')?.addEventListener('click', tlsApplyPathsFlow);
  document.getElementById('set-tls-obtain')?.addEventListener('click', tlsObtainFlow);
  document.getElementById('set-tls-upload')?.addEventListener('click', tlsUploadFlow);
  document.getElementById('set-tls-renew')?.addEventListener('click', tlsRenewFlow);
}

async function refreshTlsBody() {
  try {
    const [tls, web] = await Promise.all([
      j('/api/settings/web/tls'),
      j('/api/settings/web'),
    ]);
    tlsState = tls;
    renderTlsBody(tls, web);
  } catch (_) { /* карточка останется в прежнем состоянии */ }
}

async function tlsCall(path, body, progressTitle, progressHint, targetScheme = null) {
  try {
    await j(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    showTlsProgress(progressTitle, progressHint, targetScheme);
  } catch (error) { toast(error.message, false); }
}

/** Модалка с полями ввода (замена браузерных prompt): fields —
    [{id, label, placeholder, value, type}], возвращает значения или null. */
function tlsFormModal({ title, desc = '', fields = [], confirmText = 'Ок', danger = false }) {
  return new Promise(resolve => {
    document.getElementById('settings-tls-form')?.remove();
    const modal = document.createElement('div');
    modal.id = 'settings-tls-form';
    modal.className = 'modal-bg open';
    const inputs = fields.map(f => `
      <label>${esc(f.label)}<input id="${f.id}" type="${f.type || 'text'}" placeholder="${esc(f.placeholder || '')}" value="${esc(f.value || '')}" spellcheck="false" autocomplete="off"></label>`).join('');
    modal.innerHTML = `<div class="modal set-tls-form-modal" role="dialog" aria-modal="true">
        <h3>${esc(title)}</h3>
        ${desc ? `<p class="set-desc">${esc(desc)}</p>` : ''}
        <div class="set-tls-upload">${inputs}</div>
        <div class="set-form-actions">
          <button type="button" id="set-tls-form-ok" ${danger ? '' : 'class=""'}>${esc(confirmText)}</button>
          <button type="button" class="secondary" id="set-tls-form-cancel">Отмена</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    const close = result => {
      modal.remove();
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const submit = () => {
      const values = {};
      for (const f of fields) values[f.id] = document.getElementById(f.id)?.value?.trim() ?? '';
      close(values);
    };
    const onKey = e => { if (e.key === 'Escape') close(null); };
    document.addEventListener('keydown', onKey);
    document.getElementById('set-tls-form-cancel')?.addEventListener('click', () => close(null));
    document.getElementById('set-tls-form-ok')?.addEventListener('click', submit);
    modal.querySelectorAll('input').forEach(input => {
      input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    });
    // confirmText-кнопка слева — как во всех диалогах панели
    const okBtn = document.getElementById('set-tls-form-ok');
    if (danger && okBtn) okBtn.className = 'danger';
    setTimeout(() => modal.querySelector('input')?.focus(), 30);
  });
}

/** Тумблер HTTP<->HTTPS: выключение — подтверждение; включение — если
    поля путей заполнены, предлагаем применить их, иначе «Получить». */
async function tlsToggleFlow(e) {
  const wantHttps = e.target.checked;
  if (!wantHttps) {
    // визуально возвращаем тумблер, пока не подтвердили
    e.target.checked = true;
    const ok = await confirmAction({
      title: 'Выключить HTTPS?',
      message: 'Панель вернётся на HTTP: пароль и кука сессии будут ходить по сети открытым текстом.',
      confirmText: 'Выключить',
      confirmFirst: true,
    });
    if (!ok) return;
    await tlsCall('/api/settings/web/tls/off', null, 'Выключаем HTTPS', 'Возврат на HTTP…', 'http:');
    return;
  }
  e.target.checked = false;
  const cert = document.getElementById('set-tls-cert-path')?.value?.trim();
  const key = document.getElementById('set-tls-key-path')?.value?.trim();
  if (cert && key) {
    const ok = await confirmAction({
      title: 'Включить HTTPS?',
      message: `Включить HTTPS с парой сертификат+ключ по путям:${'\n'}${cert}${'\n'}${key}${'\n'}Панель перезапустится.`,
      confirmText: 'Включить',
      confirmFirst: true,
    });
    if (!ok) return;
    await tlsCall('/api/settings/web/tls/custom', { cert_path: cert, key_path: key }, 'Применяем сертификат', 'Проверка пары и перезапуск панели…', 'https:');
  } else {
    tlsObtainFlow();
  }
}

/** «Применить» под полями путей: включает HTTPS по указанной паре.
    Стирание адреса при работающем HTTPS — это отказ от сертификата:
    юнит с флагами на пустые пути не стартует, поэтому честно
    предлагаем переключение на HTTP, а не молчаливый отказ. */
async function tlsApplyPathsFlow() {
  const cert = document.getElementById('set-tls-cert-path')?.value?.trim();
  const key = document.getElementById('set-tls-key-path')?.value?.trim();
  if (!cert || !key) {
    if (tlsCurrentMode(tlsState) !== 'off') {
      const ok = await confirmAction({
        title: 'Стереть адрес сертификата?',
        message: 'Панель работает по HTTPS — без адреса сертификата она сможет работать только по HTTP. Переключить панель на HTTP?',
        confirmText: 'Переключить на HTTP',
        confirmFirst: true,
      });
      if (ok) await tlsCall('/api/settings/web/tls/off', null, 'Выключаем HTTPS', 'Возврат на HTTP…', 'http:');
    } else {
      toast('Укажите оба пути: сертификат и закрытый ключ', false);
    }
    return;
  }
  const ok = await confirmAction({
    title: 'Включить HTTPS с этой парой?',
    message: `Сертификат: ${cert}${'\n'}Ключ: ${key}${'\n'}Файлы не копируются — панель будет использовать их по этим путям. Панель перезапустится.`,
    confirmText: 'Включить',
    confirmFirst: true,
  });
  if (!ok) return;
  await tlsCall('/api/settings/web/tls/custom', { cert_path: cert, key_path: key }, 'Применяем сертификат', 'Проверка пары и перезапуск панели…', 'https:');
}

/** «Получить сертификат»: модалка выбора способа (за прокси — отдельная
    настройка, сертификат там управляется прокси-сервером). */
function tlsObtainFlow() {
  return new Promise(resolve => {
    document.getElementById('settings-tls-obtain')?.remove();
    const modal = document.createElement('div');
    modal.id = 'settings-tls-obtain';
    modal.className = 'modal-bg open';
    modal.innerHTML = `<div class="modal set-tls-form-modal" role="dialog" aria-modal="true">
        <h3>Получить сертификат</h3>
        <p class="set-desc">Панель сама создаст или получит сертификат и включит HTTPS.</p>
        <div class="set-tls-choices">
          <button type="button" data-mode="self-signed"><b>Самоподписанный</b><small>Сгенерировать на этом сервере. Браузер будет предупреждать о нём, но трафик шифруется.</small></button>
          <button type="button" data-mode="letsencrypt"><b>Let's Encrypt</b><small>Бесплатный доверенный сертификат. Нужен домен, указывающий на этот сервер, и свободный порт 80.</small></button>
          <button type="button" data-mode="proxy"><b>Настроить HTTPS за прокси</b><small>Сертификат устанавливается и обновляется на reverse proxy, Bot4VPS работает за ним по HTTP.</small></button>
        </div>
        <div class="set-form-actions"><button type="button" class="secondary" id="set-tls-obtain-cancel">Отмена</button></div>
      </div>`;
    document.body.appendChild(modal);
    const close = () => { modal.remove(); document.removeEventListener('keydown', onKey); resolve(); };
    const onKey = e => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    document.getElementById('set-tls-obtain-cancel')?.addEventListener('click', close);
    modal.querySelectorAll('[data-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        close();
        if (btn.dataset.mode === 'self-signed') tlsSelfSignedFlow();
        else if (btn.dataset.mode === 'letsencrypt') tlsLetsEncryptFlow();
        else tlsProxyFlow();
      });
    });
    setTimeout(() => modal.querySelector('[data-mode]')?.focus(), 30);
  });
}

async function tlsSelfSignedFlow() {
  const values = await tlsFormModal({
    title: 'Самоподписанный сертификат',
    desc: 'Имя (CN) — домен или IP, к которому подключаетсяесь. Пусто — адрес этого сервера. Браузер будет предупреждать о сертификате, но трафик шифруется.',
    fields: [{ id: 'cn', label: 'Имя в сертификате (CN)', placeholder: 'panel.example.com или 203.0.113.10' }],
    confirmText: 'Создать',
  });
  if (!values) return;
  const ok = await confirmAction({
    title: 'Создать самоподписанный сертификат?',
    message: 'Панель сгенерирует новую пару и перезапустится с HTTPS.',
    confirmText: 'Создать',
    confirmFirst: true,
  });
  if (!ok) return;
  await tlsCall('/api/settings/web/tls/self-signed', { common_name: values.cn || null }, 'Создаём сертификат', 'Генерация и перезапуск панели…', 'https:');
}

async function tlsLetsEncryptFlow() {
  const values = await tlsFormModal({
    title: "Сертификат Let's Encrypt",
    desc: "Домен должен указывать на публичный IP этого сервера, порт 80 — быть свободным и достижимым из интернета.",
    fields: [
      { id: 'domain', label: 'Домен', placeholder: 'panel.example.com' },
      { id: 'email', label: "E-mail для Let's Encrypt (можно пропустить)", placeholder: 'admin@example.com' },
    ],
    confirmText: 'Выпустить',
  });
  if (!values) return;
  if (!values.domain) return toast('Домен обязателен', false);
  const ok = await confirmAction({
    title: `Выпустить сертификат для ${values.domain}?`,
    message: "Проверка домена займёт до минуты, панель перезапустится. Если проверка не пройдёт — конфигурация вернётся, панель продолжит работать как раньше.",
    confirmText: 'Выпустить',
    confirmFirst: true,
  });
  if (!ok) return;
  await tlsCall('/api/settings/web/tls/letsencrypt', { domain: values.domain, email: values.email || null }, "Выпускаем сертификат Let's Encrypt", 'Проверка домена и перезапуск панели…', 'https:');
}

/** «Настроить HTTPS за прокси»: сертификат живёт на reverse proxy. */
async function tlsProxyFlow() {
  const values = await tlsFormModal({
    title: 'Настроить HTTPS за прокси',
    desc: 'Сертификат устанавливается и обновляется на reverse proxy. Bot4VPS работает за ним по HTTP. Укажите адреса доверенных proxy, чтобы панель корректно определяла HTTPS-запросы и защищала cookie.',
    fields: [{ id: 'proxies', label: 'Доверенные proxy — IP или подсеть, через запятую', placeholder: '192.168.1.10, 192.168.1.0/24' }],
    confirmText: 'Настроить',
  });
  if (!values) return;
  const proxies = values.proxies.split(',').map(s => s.trim()).filter(Boolean);
  if (!proxies.length) return toast('Укажите хотя бы один IP или подсеть', false);
  await tlsCall('/api/settings/web/tls/proxy', { trusted_proxies: proxies }, 'Настраиваем режим за прокси', 'Перезапуск панели…');
}

function tlsUploadFlow() {
  // Загрузка пары с этого компьютера. Сервер сам определит по
  // содержимому, где сертификат, а где ключ (порядок выбора не важен),
  // проверит пару и сохранит в keys/web/ — БЕЗ перезапуска панели.
  // Пути возвращаются и вписываются в поля; HTTPS включает «Применить».
  document.getElementById('settings-tls-upload')?.remove();
  const modal = document.createElement('div');
  modal.id = 'settings-tls-upload';
  modal.className = 'modal-bg open';
  modal.innerHTML = `<div class="modal set-tls-form-modal" role="dialog" aria-modal="true">
      <h3>Загрузка сертификата</h3>
      <p class="set-desc">Выберите два файла — сертификат (PEM) и закрытый ключ (PEM). Порядок не важен: панель сама определит, где что. Копия ляжет в keys/web/ с правами 0600.</p>
      <div class="set-tls-upload">
        <label>Файл сертификата<input type="file" id="tls-up-cert" accept=".pem,.crt,.cer,.cert"></label>
        <label>Файл закрытого ключа<input type="file" id="tls-up-key" accept=".pem,.key"></label>
        <div class="set-form-actions"><button type="button" id="tls-up-ok">Загрузить</button><button type="button" class="secondary" id="tls-up-cancel">Отмена</button></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const close = () => { modal.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  document.getElementById('tls-up-cancel')?.addEventListener('click', close);
  document.getElementById('tls-up-ok')?.addEventListener('click', async () => {
    const cert = document.getElementById('tls-up-cert')?.files?.[0];
    const key = document.getElementById('tls-up-key')?.files?.[0];
    if (!cert || !key) return toast('Выберите оба файла', false);
    const okBtn = document.getElementById('tls-up-ok');
    if (okBtn) okBtn.disabled = true;
    try {
      const fd = new FormData();
      fd.append('cert', cert);
      fd.append('key', key);
      const result = await j('/api/settings/web/tls/upload', { method: 'POST', body: fd });
      close();
      // Проверенная пара сохранена: вписываем пути в поля карточки.
      const certInput = document.getElementById('set-tls-cert-path');
      const keyInput = document.getElementById('set-tls-key-path');
      if (certInput && result?.cert_path) certInput.value = result.cert_path;
      if (keyInput && result?.key_path) keyInput.value = result.key_path;
      toast('Пара проверена и сохранена — нажмите «Применить», чтобы включить HTTPS', true);
    } catch (error) {
      if (okBtn) okBtn.disabled = false;
      toast(error.message, false);
    }
  });
  document.getElementById('tls-up-cert')?.focus();
}

async function tlsRenewFlow() {
  const ok = await confirmAction({
    title: 'Перевыпустить сертификат?',
    message: "Let's Encrypt — принудительно, самоподписанный — новой генерацией. Панель перезапустится.",
    confirmText: 'Перевыпустить',
    confirmFirst: true,
  });
  if (!ok) return;
  await tlsCall('/api/settings/web/tls/renew', { force: true }, 'Перевыпускаем сертификат', 'Выпуск и перезапуск панели…');
}

let tlsPollTimer = null;

function showTlsProgress(title, hint, targetScheme = null) {
  document.getElementById('settings-tls-progress')?.remove();
  const modal = document.createElement('div');
  modal.id = 'settings-tls-progress';
  modal.className = 'modal-bg open';
  modal.innerHTML = `<div class="modal set-port-modal" role="dialog" aria-modal="true"><div class="set-spinner"></div><h3>${esc(title)}</h3><p>${esc(hint || '')}</p><div id="set-tls-progress-note" class="hint">Не закрывайте эту вкладку.</div></div>`;
  document.body.appendChild(modal);
  clearInterval(tlsPollTimer);
  let finished = false;
  let failures = 0;
  const targetUrl = scheme => `${scheme}//${location.host}${location.pathname}`;
  const switchScheme = scheme => {
    const note = document.getElementById('set-tls-progress-note');
    if (note) note.textContent = scheme === 'https:'
      ? 'Панель перезапущена по HTTPS — переключаем страницу. Если браузер предупредит о сертификате (самоподписанный/Let’s Encrypt ещё не доверен) — подтвердите переход.'
      : 'Панель перезапущена по HTTP — переключаем страницу…';
    clearInterval(tlsPollTimer);
    tlsPollTimer = null;
    finished = true;
    setTimeout(() => location.replace(targetUrl(scheme)), 900);
  };
  tlsPollTimer = setInterval(async () => {
    try {
      const state = await j('/api/settings/web/tls/status');
      failures = 0;
      if (state?.status === 'done' || state?.status === 'failed') {
        clearInterval(tlsPollTimer);
        tlsPollTimer = null;
        finished = true;
        const note = document.getElementById('set-tls-progress-note');
        if (state.status === 'done') {
          if (note) note.textContent = 'Готово — страница перезагрузится…';
          // Схема могла смениться (http<->https): перезагружаемся целиком,
          // кука Secure живёт только на той же схеме.
          setTimeout(() => location.replace(targetUrl(targetScheme || location.protocol)), 900);
        } else {
          const err = state.error || {};
          modal.querySelector('.set-spinner')?.remove();
          if (note) note.innerHTML = `<b>${esc(err.title || 'Не удалось')}</b><br>${esc(err.hint || '')}<br>Конфигурация возвращена — панель работает как раньше.`;
          await refreshTlsBody();
        }
      }
    } catch (_) {
      // Рестарт панели — обычное дело во время операции; ждём дальше.
      // Но если операция меняет схему (http->https или обратно), старый
      // протокол после перезапуска мёртв — статуса по нему не дождаться
      // никогда. Ответа нет достаточно долго — переключаем страницу сами.
      failures += 1;
      if (targetScheme && failures >= 8) switchScheme(targetScheme);
    }
  }, 2000);
  // Общий таймаут: раннер сам ограничен и пишет failed при сбое, но если
  // процесс умер молча — не крутить спиннер вечно.
  setTimeout(() => {
    if (!finished && tlsPollTimer) {
      clearInterval(tlsPollTimer);
      tlsPollTimer = null;
      const note = document.getElementById('set-tls-progress-note');
      if (note) note.textContent = 'Ответа нет дольше обычного — проверьте состояние карточки HTTPS.';
      modal.querySelector('.set-spinner')?.remove();
      refreshTlsBody();
    }
  }, 300000);
}

// Telegram включён в общих настройках (cfg.enabled). Кнопка «Проверить
// Telegram» доступна только в этом состоянии: при выключенном Telegram health
// endpoint всё равно вернул бы DISABLED, поэтому проверка не имеет смысла.
let telegramEnabled = false;
// Последний известный сохранённый ID (для детекта несохранённых правок
// в поле при выключении бота тумблером).
let telegramUserId = '';

function applyTelegramHealthAvailability() {
  const button = document.getElementById('tg-health');
  if (button) button.disabled = !telegramEnabled;
  // Перезапуск выключенного бота не имеет смысла (и API не позволит)
  const restart = document.getElementById('tg-restart');
  if (restart) restart.disabled = !telegramEnabled;
}

function formatTgStatus(data) {
  const state = data?.status?.state || '';
  const detail = data?.status?.detail || '';
  if (state === 'disabled' || detail === 'Выключен') return { text: 'Выключен', tone: '' };
  if (state === 'running' || detail === 'Работает') return { text: 'Работает', tone: 'ok' };
  return { text: data?.status?.error ? `Ошибка · ${data.status.error}` : 'Ошибка', tone: 'error' };
}

function applyTelegramUi(data) {
  if (!data) return;
  telegramEnabled = !!data.enabled;
  telegramUserId = data.user_id == null ? '' : String(data.user_id);
  const formatted = formatTgStatus(data);
  const badge = document.getElementById('tg-status-line');
  if (badge) { badge.textContent = formatted.text; badge.className = `set-badge ${formatted.tone}`; }
  const user = document.getElementById('tg-user-id');
  if (user && document.activeElement !== user) user.value = data.user_id ?? '';
  const hint = document.getElementById('tg-token-hint');
  if (hint) hint.textContent = data.masterkey_missing
    ? 'Токен зашифрован, но мастер-ключ недоступен — восстановите его в разделе «Безопасность».'
    : data.status?.state === 'running' ? 'Токен принят Telegram. Пустое поле не изменяет токен.' : data.token_set ? 'Токен сохранён. Пустое поле не изменяет его.' : 'Токен ещё не задан.';
  const token = document.getElementById('tg-bot-token');
  if (token && document.activeElement !== token) token.value = '';
  applyTelegramHealthAvailability();
}

export async function loadTelegramSettings() {
  const data = await j('/api/telegram/status');
  applyTelegramUi(data);
  return data;
}

async function tgAction(path) {
  const buttons = ['tg-start', 'tg-stop', 'tg-restart', 'tg-save'].map(id => document.getElementById(id)).filter(Boolean);
  buttons.forEach(button => { button.disabled = true; });
  try {
    const result = await j(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    applyTelegramUi(result);
    toast(result.ok === false ? (result.error || 'Ошибка') : (result.message || 'Готово'), result.ok !== false);
  } catch (error) { toast(error.message, false); }
  finally { buttons.forEach(button => { button.disabled = false; }); }
}

async function tgSave() {
  const user_id = (document.getElementById('tg-user-id')?.value || '').trim();
  const raw = document.getElementById('tg-bot-token')?.value || '';
  const bot_token = raw.trim();
  if (raw && !bot_token) return toast('Bot Token не может состоять из пробелов', false);
  if (bot_token && (bot_token.toUpperCase().startsWith('YOUR_') || bot_token.toUpperCase().includes('YOUR_BOT_TOKEN'))) return toast('Укажите действительный Bot Token', false);
  const body = { user_id };
  if (bot_token) body.bot_token = bot_token;
  const button = document.getElementById('tg-save');
  if (button) button.disabled = true;
  try {
    const result = await j('/api/telegram/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    applyTelegramUi(result);
    toast(result.ok === false ? (result.error || 'Ошибка сохранения') : 'Настройки Telegram сохранены', result.ok !== false);
  } catch (error) { toast(error.message, false); }
  finally { if (button) button.disabled = false; }
}

async function tgCheckHealth() {
  const chat_id = (document.getElementById('tg-user-id')?.value || '').trim();
  const raw = document.getElementById('tg-bot-token')?.value || '';
  const bot_token = raw.trim();
  if (raw && !bot_token) {
    toast('Токен Telegram-бота не может состоять из пробелов.', false, { multiline: true });
    return;
  }

  // Пустой Token означает «проверить сохранённый». Непустой Token и текущий
  // chat ID отправляются только в health endpoint и никогда не сохраняются им.
  const body = { chat_id };
  if (bot_token) body.bot_token = bot_token;
  const button = document.getElementById('tg-health');
  if (button) {
    button.disabled = true;
    button.textContent = 'Проверяем…';
  }
  try {
    const result = await j('/api/telegram/health', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const health = result?.health || result;
    const ok = health?.code === 'OK';
    // Результат проверки — тостом внизу (не модалкой): текст диагностики
    // многострочный, живёт дольше обычных уведомлений
    toast(ok
      ? '✓ Telegram работает.\nБот доступен, тестовое сообщение успешно отправлено.'
      : `✕ Telegram недоступен.\n${health?.reason || 'Причина не определена.'}`,
      ok, { multiline: true, timeout: 8000 });
    window.dispatchEvent(new CustomEvent('bot4vps:telegram-health', {
      detail: { ...health, applies_to_saved_config: !!result?.applies_to_saved_config },
    }));
  } catch (error) {
    const status = error?.status ? `HTTP ${error.status}` : '';
    const detailValue = error?.detail || error?.body || error?.message;
    const detail = typeof detailValue === 'string'
      ? detailValue.trim()
      : (detailValue ? JSON.stringify(detailValue) : '');
    toast(`✕ Telegram недоступен.\n${status && detail
      ? `${status}: ${detail}`
      : (status || detail || 'Запрос проверки завершился без диагностического ответа.')}`,
      false, { multiline: true, timeout: 8000 });
  } finally {
    if (button) {
      button.textContent = 'Проверить Telegram';
      button.disabled = !telegramEnabled;
    }
  }
}

async function renderTelegram() {
  const data = await j('/api/telegram/status');
  const status = formatTgStatus(data);
  document.getElementById('settings-content').innerHTML = section('Telegram', 'Управление ботом и данными получателя.', [], `
    <div class="set-form-card"><div class="set-form-title"><div><h3>Telegram-бот</h3><p>Сервис работает в одном процессе с Web UI.</p></div><span id="tg-status-line" class="set-badge ${status.tone}">${esc(status.text)}</span></div>
      <div class="set-tls-toggle-row tg-toggle-row">
        <span class="tg-toggle-left">
          <label class="set-switch" id="tg-toggle-wrap" title="${esc('Работа Telegram-бота')}"><input type="checkbox" id="tg-toggle"><span class="set-switch-track"><span></span></span></label>
          <span class="set-tls-toggle-text" title="${esc('Работа Telegram-бота')}"><b>${data.enabled ? 'Включён' : 'Выключен'}</b><small>${data.enabled ? 'Бот принимает команды и шлёт уведомления' : 'Команды и уведомления не работают'}</small></span>
        </span>
        <button type="button" class="secondary tg-health-action" id="tg-health">Проверить Telegram</button>
      </div>
      <div class="tg-auth-row"><div class="set-tls-toggle-text" title="${esc('Токен бота создаёт @BotFather (/newbot). ID получателя — ваш числовой Telegram ID, его подскажет @userinfobot.')}"><b>Авторизация Telegram-бота</b><small>Токен и ID получателя от BotFather</small></div><button type="button" class="secondary" id="tg-restart">Перезапустить</button></div>
      <form class="set-form" onsubmit="return false;"><label>Token <small id="tg-token-hint"></small><span class="pw-wrap"><input id="tg-bot-token" type="password" autocomplete="new-password" placeholder="Введите новый токен, чтобы заменить"><button type="button" class="eye" data-pw-toggle="tg-bot-token">👁</button></span></label><label>ID пользователя / чата<span class="pw-wrap tg-id-wrap"><input id="tg-user-id" type="password" inputmode="numeric" autocomplete="off" placeholder="123456789" spellcheck="false"><button type="button" class="eye" data-pw-toggle="tg-user-id">👁</button></span></label><div class="set-form-actions"><button type="button" id="tg-save">Сохранить</button></div></form>
    </div>`);
  const toggle = document.getElementById('tg-toggle');
  if (toggle) toggle.checked = !!data.enabled;
  applyTelegramUi(data);
  bindPasswordToggles();
  document.getElementById('tg-toggle')?.addEventListener('change', tgToggleFlow);
  document.getElementById('tg-restart')?.addEventListener('click', () => tgAction('/api/telegram/restart'));
  document.getElementById('tg-save')?.addEventListener('click', tgSave);
  document.getElementById('tg-health')?.addEventListener('click', tgCheckHealth);
}

/** Тумблер Telegram: включение/выключение бота с подтверждением.
    Учитывает несохранённый токен в поле — предупреждает о потере. */
async function tgToggleFlow(e) {
  const input = document.getElementById('tg-toggle');
  // Тумблер уже переключился визуально — при отмене возвращаем назад.
  if (e?.target?.type === 'checkbox') e.target.checked = !e.target.checked;
  const next = !telegramEnabled;
  const unsaved = !!(document.getElementById('tg-bot-token')?.value || '').trim()
    || (document.getElementById('tg-user-id')?.value || '').trim() !== String(telegramUserId || '');
  const message = next
    ? 'Включить Telegram-бота?'
    : 'Выключить Telegram-бота? Команды и уведомления перестанут работать.';
  if (!await confirmAction({ message: unsaved ? `${message}${'\n\n'}Внимание: в форме есть несохранённые изменения — они не будут применены.` : message, confirmFirst: true })) return;
  try {
    await j(next ? '/api/telegram/start' : '/api/telegram/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    toast(next ? 'Telegram включён' : 'Telegram выключен', true);
    const data = await j('/api/telegram/status');
    applyTelegramUi(data);
    const t = document.getElementById('tg-toggle');
    if (t) t.checked = !!data.enabled;
    const text = t?.closest('.set-tls-toggle-row')?.querySelector('.set-tls-toggle-text');
    if (text) {
      text.querySelector('b').textContent = data.enabled ? 'Включён' : 'Выключен';
      text.querySelector('small').textContent = data.enabled ? 'Бот принимает команды и шлёт уведомления' : 'Команды и уведомления не работают';
    }
  } catch (error) {
    toast(error.message, false);
  }
}

function updateBadgeText(state) {
  if (!state) return { text: 'Нет данных', tone: '' };
  if (['downloading', 'installing', 'rolling_back'].includes(state.status)) return { text: 'Выполняется', tone: 'warn' };
  if (state.status === 'failed') return { text: 'Ошибка', tone: 'error' };
  if (state.available?.version) return { text: `Доступна ${state.available.version}`, tone: 'warn' };
  return { text: `Версия ${state.current_version || '—'}`, tone: 'ok' };
}

function applyUpdateAction(state) {
  const button = document.getElementById('set-update-action');
  if (!button) return;
  const busy = ['downloading', 'installing', 'rolling_back'].includes(state?.status);
  if (busy) {
    button.textContent = 'Выполняется…';
    button.disabled = true;
    button.onclick = null;
  } else if (state?.available?.version) {
    button.textContent = 'Установить';
    button.disabled = false;
    button.onclick = showUpdateModal;
  } else {
    button.textContent = 'Проверить';
    button.disabled = false;
    button.onclick = runUpdateCheck;
  }
}

function applyUpdateBadge(state) {
  updateState = state;
  const badge = document.getElementById('set-update-status');
  if (badge) {
    const value = updateBadgeText(state);
    badge.textContent = value.text;
    badge.className = `set-badge ${value.tone}`;
  }
  applyUpdateAction(state);
}

async function runUpdateCheck() {
  const button = document.getElementById('set-update-action');
  if (button) button.disabled = true;
  try {
    const result = await j('/api/update/check', { method: 'POST' });
    toast(result.available ? 'Найдено обновление' : 'Установлена актуальная версия', true);
    await loadUpdateState();
  } catch (error) { toast(error.message, false); }
  finally { applyUpdateAction(updateState); }
}

async function renderUpdates() {
  const [monitor, state] = await Promise.all([j('/api/monitor/config'), j('/api/update/state')]);
  updateState = state;
  const status = updateBadgeText(state);
  document.getElementById('settings-content').innerHTML = section('Обновления', 'Используется только существующий встроенный механизм обновлений.', [
    settingRow({ id: 'set-update-enabled', type: 'toggle', title: 'Автоматическая проверка', desc: 'Проверять наличие новых версий в фоне.', value: !!monitor.update?.enabled }),
    settingRow({ id: 'set-update-status', type: 'badge', title: 'Текущая версия', desc: state.last_error || 'Состояние встроенного updater.', value: status.text, tone: status.tone }),
  ], `<div class="set-inline-actions"><button type="button" id="set-update-action">Проверить</button></div>`);
  bindToggle('set-update-enabled', enabled => patchMonitor('update', { enabled }));
  applyUpdateAction(state);
}

async function renderData() {
  const limits = await j('/api/settings/history');
  document.getElementById('settings-content').innerHTML = section('История и данные', 'Лимиты применяются сразу. Старые записи сверх лимита удаляются.', [
    settingRow({ id: 'set-history-tasks', type: 'number', title: 'История задач', desc: 'Максимальное количество сохранённых задач.', value: limits.tasks, min: 1, max: 10000 }),
    settingRow({ id: 'set-history-events', type: 'number', title: 'Журнал событий', desc: 'Максимальное количество сохранённых событий.', value: limits.events, min: 1, max: 10000 }),
  ]) + section('Очистка', 'Действия удаляют записи без возможности восстановления.', [
    settingRow({ id: 'set-clear-tasks', type: 'action', title: 'Очистить историю задач', desc: 'Удалить завершённые задачи и их сохранённые логи.', label: 'Очистить', danger: true }),
    settingRow({ id: 'set-clear-events', type: 'action', title: 'Очистить журнал событий', desc: 'Удалить все события и уведомления журнала.', label: 'Очистить', danger: true }),
  ]);
  bindNumber('set-history-tasks', tasks => j('/api/settings/history', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tasks }) }));
  bindNumber('set-history-events', events => j('/api/settings/history', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ events }) }));
  document.getElementById('set-clear-tasks')?.addEventListener('click', () => clearHistory('tasks'));
  document.getElementById('set-clear-events')?.addEventListener('click', () => clearHistory('events'));
}

async function clearHistory(kind) {
  const tasks = kind === 'tasks';
  if (!await confirmAction({ message: tasks ? 'Очистить историю задач и сохранённые логи?' : 'Очистить журнал событий?', confirmFirst: true })) return;
  try {
    await j(tasks ? '/api/tasks/history' : '/api/events', { method: 'DELETE' });
    toast(tasks ? 'История задач очищена' : 'Журнал событий очищен', true);
  } catch (error) { toast(error.message, false); }
}

async function renderAbout() {
  const ping = await j('/api/ping');
  document.getElementById('settings-content').innerHTML = `<section class="set-about"><div class="set-about-mark">B4</div><div><span class="set-kicker">SERVER CONTROL PLANE</span><h2>Bot4VPS</h2><p>Telegram-бот и Web UI для управления VPS и домашними серверами через SSH.</p><div class="set-about-version">Версия <strong>${esc(ping.version || '—')}</strong></div><div class="set-inline-actions"><button type="button" class="secondary" id="set-about-changelog">Описание версии</button><a class="btn secondary" href="https://github.com/crashdmd/Bot4VPS" target="_blank" rel="noopener noreferrer">GitHub ↗</a></div><div class="set-about-author">Автор — <a href="https://github.com/crashdmd" target="_blank" rel="noopener noreferrer">crashdmd</a></div></div></section>`;
  document.getElementById('set-about-changelog')?.addEventListener('click', showHistoryModal);
}

export async function selectSettingsCategory(id) {
  await openCategory(id);
}

export async function loadSettings() {
  renderNav();
  await openCategory(selectedCategory);
}

export function stopSettingsTimers() {
  clearInterval(portPollTimer);
  portPollTimer = null;
  clearNumberTimers();
  document.getElementById('settings-port-progress')?.remove();
}

export function bindSettingsUI() {
  const nav = document.getElementById('settings-nav');
  if (nav && !nav.dataset.bound) {
    nav.dataset.bound = '1';
    nav.addEventListener('click', event => {
      const button = event.target.closest('[data-settings-category]');
      if (button) openCategory(button.dataset.settingsCategory);
    });
  }
  if (!window.__settingsUpdateBound) {
    window.__settingsUpdateBound = true;
    window.addEventListener('bot4vps:update-state', event => applyUpdateBadge(event.detail));
  }
}
