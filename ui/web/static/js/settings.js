import { j, esc } from './api.js?v=20260821-telegram-health-v1';
import { toast, bindPasswordToggles, confirmAction, showTelegramHealthDialog, syncServerClock } from './ui.js';
import { loadUpdateState, showUpdateModal, showHistoryModal } from './monitor.js?v=20260826-host-timezone-v2';

let account = { auth_enabled: false, username: 'admin' };
let selectedCategory = 'common';
let updateState = null;
let portPollTimer = null;
const numberTimers = new Map();

const THEME_KEY = 'bot4vps_theme';
const THEME_COLOR = { dark: '#0d1117', light: '#f6f8fa' };

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (value === 'dark' || value === 'light') return value;
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
  const resolved = value === 'light' ? 'light' : 'dark';
  if (resolved === 'light') document.documentElement.setAttribute('data-theme', 'light');
  else document.documentElement.removeAttribute('data-theme');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[resolved]);
  updateThemeIcon(resolved);
  updateThemeChoices(resolved);
  window.dispatchEvent(new CustomEvent('bot4vps:theme', { detail: { resolved } }));
}

function updateThemeIcon(resolved) {
  const button = document.getElementById('theme-toggle');
  if (!button) return;
  const stroke = resolved === 'light' ? '#1a1a1a' : '#ffffff';
  button.innerHTML = resolved === 'light'
    ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`
    : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
}

function setTheme(value) {
  try { localStorage.setItem(THEME_KEY, value); } catch (_) {}
  applyTheme(value);
}

function handleThemeToggle() {
  const current = document.documentElement.hasAttribute('data-theme') ? 'light' : 'dark';
  setTheme(current === 'light' ? 'dark' : 'light');
}

export function initTheme() {
  applyTheme(storedTheme());
  const button = document.getElementById('theme-toggle');
  if (button && !button.dataset.themeBound) {
    button.dataset.themeBound = '1';
    button.addEventListener('click', handleThemeToggle);
  }
}

const categories = [
  { id: 'common', icon: '◉', title: 'Общие', subtitle: 'Мониторинг и интерфейс', render: renderCommon },
  { id: 'web', icon: '⌘', title: 'Web', subtitle: 'Доступ и порт панели', render: renderWeb },
  { id: 'telegram', icon: '↗', title: 'Telegram', subtitle: 'Бот и получатель', render: renderTelegram },
  { id: 'updates', icon: '⇧', title: 'Обновления', subtitle: 'Проверка и установка', render: renderUpdates },
  { id: 'data', icon: '▤', title: 'История и данные', subtitle: 'Лимиты хранения', render: renderData },
  { id: 'about', icon: 'i', title: 'О программе', subtitle: 'Версия и проект', render: renderAbout },
];

function settingRow(spec) {
  let control = '';
  if (spec.type === 'toggle') {
    control = `<label class="set-switch"><input id="${spec.id}" type="checkbox" ${spec.value ? 'checked' : ''}><span class="set-switch-track"><span></span></span></label>`;
  } else if (spec.type === 'number') {
    control = `<input class="set-number" id="${spec.id}" type="number" value="${esc(spec.value)}" min="${spec.min ?? 1}" max="${spec.max ?? 10000}" inputmode="numeric">`;
  } else if (spec.type === 'theme') {
    control = `<div class="set-theme-choices" role="group" aria-label="Тема интерфейса"><button type="button" class="secondary" id="set-theme-light" data-theme-choice="light" aria-pressed="${spec.value === 'light'}">Светлая</button><button type="button" class="secondary" id="set-theme-dark" data-theme-choice="dark" aria-pressed="${spec.value === 'dark'}">Тёмная</button></div>`;
  } else if (spec.type === 'select') {
    control = `<select id="${spec.id}" class="set-select ${esc(spec.controlClass || '')}">${(spec.options || []).map(o => `<option value="${esc(o.value)}" ${o.value === spec.value ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
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
    select.innerHTML = metadata.options.map(option =>
      `<option value="${esc(option.value)}">${esc(option.label)}</option>`).join('');
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
    settingRow({ id: 'set-timezone', type: 'select', title: 'Часовой пояс сервера', desc: 'Меняет часовую зону локального хоста Bot4VPS.', descId: 'set-timezone-desc', value: timezoneMetadata.timezone, options: timezoneMetadata.options, controlClass: 'set-timezone-select' }),
    '<div class="set-divider" role="separator"></div>',
    settingRow({ id: 'set-theme', type: 'theme', title: 'Тема интерфейса', desc: 'Сохраняется только в этом браузере.', value: storedTheme() }),
  ]);
  bindToggle('set-online-enabled', enabled => patchMonitor('online', { enabled }));
  bindNumber('set-online-interval', interval => patchMonitor('online', { interval }));
  bindToggle('set-ssl-enabled', enabled => patchMonitor('ssl', { enabled }));
  bindNumber('set-ssl-interval', interval => patchMonitor('ssl', { interval }));
  bindTimezoneSelect(timezoneMetadata);
  initializeSettingDependencies(content);
  document.getElementById('set-theme-light')?.addEventListener('click', () => { setTheme('light'); flashRow(document.getElementById('set-theme-light'), true); });
  document.getElementById('set-theme-dark')?.addEventListener('click', () => { setTheme('dark'); flashRow(document.getElementById('set-theme-dark'), true); });
}

export async function loadAccount() {
  try { account = await j('/api/auth/account'); } catch (_) {}
  const user = document.getElementById('acc-user');
  if (user) user.value = account.username || 'admin';
  const status = document.getElementById('acc-status');
  if (status) {
    status.textContent = account.auth_enabled ? 'Защита включена' : 'Локальный режим';
    status.className = `set-badge ${account.auth_enabled ? 'ok' : ''}`;
  }
  const hint = document.getElementById('acc-old-hint');
  if (hint) hint.textContent = account.auth_enabled ? 'Обязателен при смене пароля.' : 'Не нужен в локальном режиме.';
  const toggle = document.getElementById('acc-toggle');
  if (toggle) toggle.textContent = account.auth_enabled ? 'Выключить защиту' : 'Включить защиту';
}

export async function saveAccount() {
  const username = (document.getElementById('acc-user')?.value || '').trim();
  const newPassword = document.getElementById('acc-pass')?.value || '';
  if (!username) return toast('Логин не может быть пустым', false);
  if (newPassword && newPassword.length < 6) return toast('Пароль не короче 6 символов', false);
  const body = { username };
  if (newPassword) {
    body.new_password = newPassword;
    if (account.auth_enabled) body.old = document.getElementById('acc-old')?.value || '';
  }
  try {
    account = await j('/api/auth/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    document.getElementById('acc-pass').value = '';
    document.getElementById('acc-old').value = '';
    toast('Настройки учётной записи сохранены', true);
    await loadAccount();
  } catch (error) { toast(error.message, false); }
}

export async function toggleAuth() {
  const next = !account.auth_enabled;
  const message = next ? 'Включить защиту входа? После этого потребуется логин и пароль.' : 'Выключить защиту? Вход станет доступен без пароля.';
  if (!await confirmAction({ message, confirmFirst: true })) return;
  try {
    await j('/api/auth/account', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ auth_enabled: next }) });
    toast(next ? 'Защита включена' : 'Защита выключена', true);
    setTimeout(() => location.reload(), 500);
  } catch (error) { toast(error.message, false); }
}

async function renderWeb() {
  const [web] = await Promise.all([j('/api/settings/web'), loadAccount()]);
  const portValue = web.port ?? location.port ?? 8000;
  const portReason = web.changeable ? 'Изменение перезапустит Bot4VPS и перенаправит браузер.' : (web.reason || 'Смена порта недоступна в этой среде.');
  const content = document.getElementById('settings-content');
  const portSection = section('Порт Web UI', '', [
    settingRow({ id: 'set-web-port-state', type: 'badge', title: 'Состояние', desc: portReason, value: web.busy ? 'Изменение выполняется' : (web.changeable ? 'Доступно' : 'Недоступно'), tone: web.changeable ? 'ok' : '' }),
    `<div class="set-port-line"><input id="set-web-port" type="number" min="1" max="65535" value="${esc(portValue)}" ${web.changeable && !web.busy ? '' : 'disabled'}><button type="button" id="set-web-port-apply" ${web.changeable && !web.busy ? '' : 'disabled'}>Применить</button></div>`,
  ]);
  content.innerHTML = section('Web', 'Доступ к панели и параметры HTTP-сервиса.', [], `
    <div class="set-form-card"><div class="set-form-title"><div><h3>Учётная запись</h3><p>Логин и пароль для входа в Web UI.</p></div><span id="acc-status" class="set-badge">…</span></div>
      <form id="acc-form" class="set-form" onsubmit="return false;">
        <label>Логин<input id="acc-user" autocomplete="username"></label>
        <label>Старый пароль <small id="acc-old-hint"></small><span class="pw-wrap"><input id="acc-old" type="password" autocomplete="current-password"><button type="button" class="eye" data-pw-toggle="acc-old">👁</button></span></label>
        <label>Новый пароль <small>Пусто — не менять.</small><span class="pw-wrap"><input id="acc-pass" type="password" autocomplete="new-password"><button type="button" class="eye" data-pw-toggle="acc-pass">👁</button></span></label>
        <div class="set-form-actions"><button type="button" id="acc-save">Сохранить</button><button type="button" class="secondary" id="acc-toggle">…</button></div>
      </form>
    </div>
    ${portSection}`);
  await loadAccount();
  bindPasswordToggles();
  document.getElementById('acc-save')?.addEventListener('click', saveAccount);
  document.getElementById('acc-toggle')?.addEventListener('click', toggleAuth);
  document.getElementById('set-web-port-apply')?.addEventListener('click', applyWebPort);
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

// Telegram включён в общих настройках (cfg.enabled). Кнопка «Проверить
// Telegram» доступна только в этом состоянии: при выключенном Telegram health
// endpoint всё равно вернул бы DISABLED, поэтому проверка не имеет смысла.
let telegramEnabled = false;

function applyTelegramHealthAvailability() {
  const button = document.getElementById('tg-health');
  if (button) button.disabled = !telegramEnabled;
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
  const formatted = formatTgStatus(data);
  const badge = document.getElementById('tg-status-line');
  if (badge) { badge.textContent = formatted.text; badge.className = `set-badge ${formatted.tone}`; }
  const user = document.getElementById('tg-user-id');
  if (user && document.activeElement !== user) user.value = data.user_id ?? '';
  const hint = document.getElementById('tg-token-hint');
  if (hint) hint.textContent = data.status?.state === 'running' ? 'Токен принят Telegram. Пустое поле не изменяет токен.' : data.token_set ? 'Токен сохранён. Пустое поле не изменяет его.' : 'Токен ещё не задан.';
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
    showTelegramHealthDialog({
      ok: false,
      reason: 'Токен Telegram-бота не может состоять из пробелов.',
    });
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
    showTelegramHealthDialog({
      ok: health?.code === 'OK',
      code: health?.code || '',
      reason: health?.reason || 'Не удалось определить причину ошибки.',
    });
    window.dispatchEvent(new CustomEvent('bot4vps:telegram-health', {
      detail: { ...health, applies_to_saved_config: !!result?.applies_to_saved_config },
    }));
  } catch (error) {
    const status = error?.status ? `HTTP ${error.status}` : '';
    const detailValue = error?.detail || error?.body || error?.message;
    const detail = typeof detailValue === 'string'
      ? detailValue.trim()
      : (detailValue ? JSON.stringify(detailValue) : '');
    showTelegramHealthDialog({
      ok: false,
      reason: status && detail
        ? `${status}: ${detail}`
        : (status || detail || 'Запрос проверки Telegram завершился без диагностического ответа.'),
    });
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
      <div class="set-inline-actions tg-telegram-actions"><button type="button" id="tg-start">Включить</button><button type="button" class="secondary" id="tg-stop">Выключить</button><button type="button" class="secondary" id="tg-restart">Перезапустить</button><button type="button" class="secondary tg-health-action" id="tg-health">Проверить Telegram</button></div>
      <form class="set-form" onsubmit="return false;"><label>Token <small id="tg-token-hint"></small><span class="pw-wrap"><input id="tg-bot-token" type="password" autocomplete="new-password" placeholder="Введите новый токен, чтобы заменить"><button type="button" class="eye" data-pw-toggle="tg-bot-token">👁</button></span></label><label>ID пользователя / чата<input id="tg-user-id" inputmode="numeric" autocomplete="off" placeholder="123456789"></label><div class="set-form-actions"><button type="button" id="tg-save">Сохранить</button></div></form>
    </div>`);
  applyTelegramUi(data);
  bindPasswordToggles();
  document.getElementById('tg-start')?.addEventListener('click', () => tgAction('/api/telegram/start'));
  document.getElementById('tg-stop')?.addEventListener('click', () => tgAction('/api/telegram/stop'));
  document.getElementById('tg-restart')?.addEventListener('click', () => tgAction('/api/telegram/restart'));
  document.getElementById('tg-save')?.addEventListener('click', tgSave);
  document.getElementById('tg-health')?.addEventListener('click', tgCheckHealth);
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
  document.getElementById('settings-content').innerHTML = `<section class="set-about"><div class="set-about-mark">B4</div><div><span class="set-kicker">SERVER CONTROL PLANE</span><h2>Bot4VPS</h2><p>Telegram-бот и Web UI для управления VPS и домашними серверами через SSH.</p><div class="set-about-version">Версия <strong>${esc(ping.version || '—')}</strong></div><div class="set-inline-actions"><button type="button" class="secondary" id="set-about-changelog">История версий</button><a class="btn secondary" href="https://github.com/crashdmd/Bot4VPS" target="_blank" rel="noopener noreferrer">GitHub ↗</a></div></div></section>`;
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
