import { j } from './api.js';
import { toast, bindPasswordToggles } from './ui.js';

// authed = true, если авторизация выключена ИЛИ пользователь залогинен.
let authed = true;
export function isAuthed() { return authed; }

function showLogin() {
  authed = false;
  const ov = document.getElementById('login-overlay');
  if (!ov) return;
  ov.classList.add('open');
  bindPasswordToggles(ov);
  const pass = document.getElementById('li-pass');
  if (pass) setTimeout(() => pass.focus(), 50);
}

function hideLogin() {
  authed = true;
  const ov = document.getElementById('login-overlay');
  if (ov) ov.classList.remove('open');
}

/**
 * Проверяет /api/me. Возвращает true, если приложение можно грузить дальше
 * (авторизация выключена либо пользователь уже в сессии). Иначе показывает
 * оверлей логина и вернёт false — boot() остановится до перезагрузки после входа.
 */
export async function initAuth() {
  try {
    const me = await j('/api/me');
    if (me.auth_enabled && !me.user) { showLogin(); return false; }
  } catch (_) {
    // 401 — авторизация включена, сессии нет
    showLogin();
    return false;
  }
  hideLogin();
  return true;
}

export async function doLogin() {
  const username = (document.getElementById('li-user')?.value || '').trim();
  const password = document.getElementById('li-pass')?.value || '';
  const err = document.getElementById('li-err');
  if (err) err.textContent = '';
  try {
    await j('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    toast('Вход выполнен', true);
    hideLogin();
    location.reload(); // чистая реинициализация состояния после входа
  } catch (e) {
    if (err) err.textContent = e.message || 'Ошибка входа';
  }
}

export function bindAuthUI() {
  document.getElementById('li-go')?.addEventListener('click', doLogin);
  document.getElementById('li-pass')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });
  document.getElementById('li-user')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('li-pass')?.focus();
  });
}
