import { j } from './api.js';
import { toast, bindPasswordToggles } from './ui.js';

// Первичная настройка (Этап 2): мастер создания администратора.
// Опрашивает /api/setup/status ДО логина: пока действует код установки
// и админа нет, всё остальное закрыто бэкендом — фронт показывает
// мастер или заглушку вместо экрана логина.

const THEMES = ['dark', 'light', 'glass'];

function applyServerTheme(theme) {
  if (!THEMES.includes(theme)) return;
  try { localStorage.setItem('bot4vps_theme', theme); } catch (_) {}
  if (theme === 'dark') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
}

function showSetup(existing) {
  document.body.classList.remove('boot');
  document.body.classList.add('login-open');
  const ov = document.getElementById('setup-overlay');
  if (!ov) return;
  ov.classList.add('open');
  bindPasswordToggles(ov);
  const warn = document.getElementById('su-existing');
  if (warn) warn.hidden = !existing;
  // Шире — только когда под логотипом есть предупреждение о данных
  // существующей установки (без него левая колонка компактнее)
  ov.querySelector('.login-card')?.classList.toggle('with-existing', existing);
  setTimeout(() => document.getElementById('su-user')?.focus(), 50);
}

function showStub() {
  document.body.classList.remove('boot');
  document.body.classList.add('login-open');
  document.getElementById('setup-stub-overlay')?.classList.add('open');
}

function showExpired() {
  // Код выдан, но истёк (TTL 10 минут): панель закрыта, пока код не
  // перевыпущен из CLI — форма мастера не показывается
  document.body.classList.remove('boot');
  document.body.classList.add('login-open');
  document.getElementById('setup-expired-overlay')?.classList.add('open');
}

/**
 * Проверяет /api/setup/status. Возвращает true, если можно грузить
 * приложение дальше (обычный режим — логин или открытая панель).
 * Иначе показывает мастер/заглушку и вернёт false — boot() остановится;
 * после создания администратора страница перезагрузится на логин.
 */
export async function initSetup() {
  let st;
  try {
    st = await j('/api/setup/status');
  } catch (_) {
    // Статус недоступен (например, аварийный режим отдаёт страницу
    // напрямую) — продолжаем обычную загрузку, её разберёт initAuth
    return true;
  }
  applyServerTheme(st.theme);
  if (st.wizard) {
    showSetup(!!st.existing_installation);
    const n = document.getElementById('su-servers');
    if (n) n.textContent = String(st.servers || 0);
    return false;
  }
  if (st.expired) {
    showExpired();
    return false;
  }
  if (st.stub) {
    showStub();
    return false;
  }
  return true;
}

async function completeSetup() {
  const btn = document.getElementById('su-go');
  const err = document.getElementById('su-err');
  const username = (document.getElementById('su-user')?.value || '').trim();
  const pass1 = document.getElementById('su-pass')?.value || '';
  const pass2 = document.getElementById('su-pass2')?.value || '';
  const code = (document.getElementById('su-code')?.value || '').trim();
  if (err) err.textContent = '';
  if (!username) {
    if (err) err.textContent = 'Логин не может быть пустым';
    return;
  }
  if (pass1 !== pass2) {
    if (err) err.textContent = 'Пароли не совпадают';
    return;
  }
  if (pass1.length < 6) {
    if (err) err.textContent = 'Пароль не короче 6 символов';
    return;
  }
  if (!code) {
    if (err) err.textContent = 'Введите код первичной установки';
    return;
  }
  if (btn) btn.disabled = true;
  try {
    await j('/api/setup/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: pass1, code }),
    });
    // Бэкенд создал админа и сразу выдал сессию — перезагрузка
    // попадает прямо в панель (без повторного ввода логина/пароля)
    toast('Администратор создан — выполняется вход', true);
    location.reload();
  } catch (e) {
    if (err) err.textContent = e.message || 'Не удалось создать администратора';
    if (btn) btn.disabled = false;
  }
}

export function bindSetupUI() {
  document.getElementById('su-go')?.addEventListener('click', completeSetup);
  const enter = e => { if (e.key === 'Enter') completeSetup(); };
  document.getElementById('su-user')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('su-pass')?.focus();
  });
  document.getElementById('su-pass')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('su-pass2')?.focus();
  });
  document.getElementById('su-pass2')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('su-code')?.focus();
  });
  document.getElementById('su-code')?.addEventListener('keydown', enter);
}
