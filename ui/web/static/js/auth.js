import { j } from './api.js';
import { toast, bindPasswordToggles } from './ui.js';

// Логин/пароль для «Запомнить пароль»: base64 — обфускация от случайных
// глаз, не защита (пароль и так вводится в форму на этом же браузере).
const REMEMBER_KEY = 'bot4vps_saved_login';
const THEMES = ['dark', 'light', 'glass'];

// Тема сервера — источник истины (localStorage — лишь кэш отрисовки).
// Вызываем до показа экрана логина: оверлей ещё display:none, поэтому
// после сброса кеша браузера экран сразу открывается в верной теме,
// без вспышки дефолтной тёмной.
function applyServerTheme(theme) {
  if (!THEMES.includes(theme)) return;
  try { localStorage.setItem('bot4vps_theme', theme); } catch (_) {}
  if (theme === 'dark') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
}

// authed = true, если авторизация выключена ИЛИ пользователь залогинен.
let authed = true;
export function isAuthed() { return authed; }

function loadSavedLogin() {
  try {
    const raw = localStorage.getItem(REMEMBER_KEY);
    if (!raw) return null;
    const saved = JSON.parse(atob(raw));
    if (!saved || !saved.username || !saved.password) return null;
    return saved;
  } catch (_) { return null; }
}

function saveLogin(username, password) {
  try {
    localStorage.setItem(REMEMBER_KEY, btoa(JSON.stringify({ username, password })));
  } catch (_) { /* приватный режим — просто не запоминаем */ }
}

function clearSavedLogin() {
  try { localStorage.removeItem(REMEMBER_KEY); } catch (_) {}
}

function showLogin() {
  authed = false;
  // Скрываем интерфейс панели: логин — отдельный экран, без «задника»
  document.body.classList.remove('boot');
  document.body.classList.add('login-open');
  const ov = document.getElementById('login-overlay');
  if (!ov) return;
  ov.classList.add('open');
  bindPasswordToggles(ov);
  const saved = loadSavedLogin();
  if (saved) {
    const user = document.getElementById('li-user');
    const pass = document.getElementById('li-pass');
    const remember = document.getElementById('li-remember');
    if (user) user.value = saved.username;
    if (pass) pass.value = saved.password;
    if (remember) remember.checked = true;
  }
  // «Восстановить пароль» — кнопка видна всегда (если есть экран логина,
  // значит авторизация включена). Доступность Telegram отдельно: если канал
  // доставки кода не работает, клик покажет подсказку про консоль.
  j('/api/auth/recover').then(st => {
    recoverState = {
      available: !!(st && st.available),
      hint: (st && st.hint) || '',
    };
  }).catch(() => {});
  const rbtn = document.getElementById('li-recover');
  if (rbtn) rbtn.hidden = false;
  const pass = document.getElementById('li-pass');
  if (saved && pass) setTimeout(() => pass.focus(), 50);
  else {
    const user = document.getElementById('li-user');
    if (user) setTimeout(() => user.focus(), 50);
  }
}

function hideLogin() {
  authed = true;
  document.body.classList.remove('boot', 'login-open');
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
    // Тему сервера применяем до решения о логине — и для экрана входа,
    // и для панели (boot-скрытие .layout гасит вспышку смены темы).
    applyServerTheme(me.theme);
    if (me.auth_enabled && !me.user) { showLogin(); return false; }
  } catch (_) {
    // 401 — авторизация включена, сессии нет
    showLogin();
    return false;
  }
  hideLogin();
  return true;
}

// Шаг 2 при включённой 2FA: пароль уже принят, ждём код из приложения.
// На сервере в этот момент сессии НЕТ (полусессия запрещена) — просто
// переключаем форму на поле кода, не трогая введённый логин/пароль.
let otpStep = false;

function enterOtpStep() {
  otpStep = true;
  document.getElementById('li-creds')?.setAttribute('hidden', '');
  document.getElementById('li-recover')?.setAttribute('hidden', '');
  const wrap = document.getElementById('li-otp-wrap');
  if (wrap) wrap.hidden = false;
  const go = document.getElementById('li-go');
  if (go) go.textContent = 'Подтвердить';
  setTimeout(() => document.getElementById('li-otp')?.focus(), 50);
}

function leaveOtpStep() {
  otpStep = false;
  document.getElementById('li-creds')?.removeAttribute('hidden');
  const recover = document.getElementById('li-recover');
  if (recover) recover.hidden = false;
  const wrap = document.getElementById('li-otp-wrap');
  if (wrap) wrap.hidden = true;
  const otp = document.getElementById('li-otp');
  if (otp) otp.value = '';
  const go = document.getElementById('li-go');
  if (go) go.textContent = 'Войти';
  setTimeout(() => document.getElementById('li-pass')?.focus(), 50);
}

// Общий финал входа: «Запомнить пароль» сохраняем только после ПОЛНОГО
// успеха (при 2FA — после подтверждения кода), затем перезагрузка.
function finishLogin(username, password) {
  const remember = document.getElementById('li-remember');
  if (remember && remember.checked) saveLogin(username, password);
  else clearSavedLogin();
  toast('Вход выполнен', true);
  hideLogin();
  location.reload(); // чистая реинициализация состояния после входа
}

async function confirmOtp() {
  const field = document.getElementById('li-otp');
  const code = (field?.value || '').trim();
  const err = document.getElementById('li-err');
  if (err) err.textContent = '';
  try {
    await j('/api/login/otp', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
    finishLogin(
      (document.getElementById('li-user')?.value || '').trim(),
      document.getElementById('li-pass')?.value || ''
    );
  } catch (e) {
    if (err) err.textContent = e.message || 'Ошибка входа';
    // Поле очищаем: автоподтверждение сработает на новый набор 6 цифр,
    // не заставляя вручную стирать неверный код
    if (field) {
      field.value = '';
      field.focus();
    }
  }
}

export async function doLogin() {
  if (otpStep) return confirmOtp();
  const username = (document.getElementById('li-user')?.value || '').trim();
  const password = document.getElementById('li-pass')?.value || '';
  const err = document.getElementById('li-err');
  if (err) err.textContent = '';
  try {
    const data = await j('/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    // Пароль верен, но включена 2FA: сессии ещё нет — просим код
    if (data && data.otp_required) {
      enterOtpStep();
      return;
    }
    finishLogin(username, password);
  } catch (e) {
    if (err) err.textContent = e.message || 'Ошибка входа';
  }
}

// Время последнего запроса кода: пока код жив (~10 минут на сервере),
// повторный клик просто открывает окно снова, не дёргая TG и cooldown
let codeRequestedAt = 0;
// Доступность Telegram-восстановления (кэш GET /api/auth/recover):
// null — ещё не знаем; кнопка всё равно видна, клик попробует POST.
let recoverState = null;

function openRecoverModal() {
  const modal = document.getElementById('login-recover-modal');
  if (!modal) return;
  modal.classList.add('open');
  document.getElementById('li-code')?.focus();
  scheduleResendTimer();
}

function closeRecoverModal() {
  document.getElementById('login-recover-modal')?.classList.remove('open');
}

// Обратный отсчёт resend-кнопки: активна через 2 минуты после отправки
// кода (раньше новый код бессмыслен — старый жив 10 минут и мог просто
// задержаться в доставке). Сервер дублирует проверку.
let resendTimer = null;

function scheduleResendTimer() {
  if (resendTimer) { clearTimeout(resendTimer); resendTimer = null; }
  const btn = document.getElementById('li-recover-resend');
  if (!btn) return;
  if (!codeRequestedAt) { btn.disabled = true; btn.textContent = 'Отправить код ещё раз'; return; }
  const update = () => {
    const left = 120 - Math.floor((Date.now() - codeRequestedAt) / 1000);
    if (left > 0) {
      btn.disabled = true;
      btn.textContent = `Отправить код ещё раз (через ${left} с)`;
      resendTimer = setTimeout(update, 1000);
    } else {
      btn.disabled = false;
      btn.textContent = 'Отправить код ещё раз';
    }
  };
  update();
}

/** Повторная отправка кода восстановления: новый код стирает старый. */
async function resendRecoverCode() {
  const btn = document.getElementById('li-recover-resend');
  if (btn) btn.disabled = true;
  recoverError('');
  try {
    const res = await j('/api/auth/recover/resend', { method: 'POST' });
    codeRequestedAt = Date.now();
    if (res && res.resent) toast('Новый код отправлен в Telegram — предыдущий больше не действует', true);
    scheduleResendTimer();
  } catch (e) {
    recoverError(e.message || 'Не удалось отправить код');
    scheduleResendTimer();
  }
}

function recoverError(message) {
  const err = document.getElementById('li-rec-err');
  if (err) err.textContent = message || '';
}

async function recoverPassword() {
  const btn = document.getElementById('li-recover');
  const err = document.getElementById('li-err');
  if (err) err.textContent = '';
  recoverError('');
  // Telegram совсем не настроен — доставить код некому, только консоль
  if (recoverState && !recoverState.available) {
    if (err) err.textContent = recoverState.hint ||
      'Telegram не настроен — воспользуйтесь консолью на сервере (bot4vps)';
    return;
  }
  // Окно открываем сразу: подсказка про консольный путь видна с первой
  // секунды, код в Telegram уходит параллельно (доставит одноразовый
  // Bot, даже если сам бот не запущен). Ошибка доставки — в окне.
  openRecoverModal();
  // Код уже запрашивался и ещё действует — повторно не дёргаем TG
  if (Date.now() - codeRequestedAt < 9 * 60 * 1000) {
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = 'Отправляю…'; }
  try {
    await j('/api/auth/recover', { method: 'POST' });
    codeRequestedAt = Date.now();
    toast('Код отправлен в Telegram', true);
  } catch (e) {
    recoverError(e.message || 'Не удалось отправить код');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Восстановить пароль'; }
  }
}

async function confirmRecovery() {
  const btn = document.getElementById('li-recover-go');
  const code = (document.getElementById('li-code')?.value || '').trim();
  const pass1 = document.getElementById('li-newpass')?.value || '';
  const pass2 = document.getElementById('li-newpass2')?.value || '';
  recoverError('');
  if (pass1 !== pass2) {
    recoverError('Пароли не совпадают');
    return;
  }
  if (pass1.length < 6) {
    recoverError('Пароль не короче 6 символов');
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const data = await j('/api/auth/recover/confirm', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, new_password: pass1 }),
    });
    // Пароль сменился. Сохранённый старый пароль («Запомнить»)
    // больше не актуален.
    clearSavedLogin();
    closeRecoverModal();
    if (data && data.otp_required) {
      // 2FA включена: сервер НЕ залогинил (смена пароля не должна
      // обходить второй фактор) — просим войти паролем + кодом.
      toast('Пароль изменён. Войдите с ним и кодом из приложения', true);
      cancelRecovery();
      const oldPass = document.getElementById('li-pass');
      if (oldPass) oldPass.value = ''; // там прежний (уже неверный) пароль
      setTimeout(() => document.getElementById('li-pass')?.focus(), 50);
    } else {
      toast('Пароль изменён — вход выполнен', true);
      hideLogin();
      location.reload();
    }
  } catch (e) {
    recoverError(e.message || 'Не удалось сменить пароль');
    if (btn) btn.disabled = false;
  }
}

function cancelRecovery() {
  closeRecoverModal();
  for (const id of ['li-code', 'li-newpass', 'li-newpass2']) {
    const field = document.getElementById(id);
    if (field) field.value = '';
  }
  recoverError('');
}

export function bindAuthUI() {
  document.getElementById('li-go')?.addEventListener('click', doLogin);
  document.getElementById('li-recover')?.addEventListener('click', recoverPassword);
  document.getElementById('li-recover-go')?.addEventListener('click', confirmRecovery);
  document.getElementById('li-recover-resend')?.addEventListener('click', resendRecoverCode);
  document.getElementById('li-recover-cancel')?.addEventListener('click', cancelRecovery);
  // Глазки показа пароля в окне восстановления
  bindPasswordToggles(document.getElementById('login-recover-modal'));
  document.getElementById('li-pass')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') doLogin();
  });
  document.getElementById('li-user')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('li-pass')?.focus();
  });
  // Шаг 2FA: Enter в поле кода отправляет, «← Назад» возвращает
  document.getElementById('li-otp')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmOtp();
  });
  // Автоподтверждение: 6-я цифра введена — отправляем без кнопки.
  // Неверный код очистит поле (в confirmOtp) и автоподтверждение
  // сработает на следующую попытку.
  const otpInput = document.getElementById('li-otp');
  if (otpInput) otpInput.addEventListener('input', () => {
    if ((otpInput.value || '').length >= 6) confirmOtp();
  });
  document.getElementById('li-otp-back')?.addEventListener('click', leaveOtpStep);
  // В окне восстановления Enter двигает к следующему полю, из
  // последнего — отправляет
  document.getElementById('li-code')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('li-newpass')?.focus();
  });
  document.getElementById('li-newpass')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('li-newpass2')?.focus();
  });
  document.getElementById('li-newpass2')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmRecovery();
  });
}
