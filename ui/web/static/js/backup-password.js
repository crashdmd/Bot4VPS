/* Общий модал пароля резервных копий. Используется из двух мест:
   - Настройки → Безопасность (задать/сменить/удалить пароль);
   - страница Резервные копии (задать пароль при включении галочки защиты
     цели; подтвердить текущим паролем её снятие).
   Пароль живёт только в поле ввода на время модалки: в URL не попадает,
   в логи не пишется, из API не возвращается. ОК — всегда слева. */

import { j } from './api.js?v=20260910-backupenc-v15';
import { toast, bindPasswordToggles } from './ui.js';

const TITLES = {
  set: 'Задайте пароль для резервных копий',
  change: 'Изменить пароль резервных копий',
  remove: 'Удалить пароль резервных копий',
  verify: 'Подтверждение паролем',
  forgot: 'Удалить пароль резервных копий',
  forgotCode: 'Удалить пароль резервных копий',
};

const NOTES = {
  set: 'Постоянный пароль: он потребуется для распаковки архива на другом сервере.',
  change: 'Новые резервные копии целей с включённой защитой будут создаваться с новым паролем. Старые архивы открываются своим прежним паролем.',
  // remove — без примечания: предупреждение показывается отдельной
  // confirm-модалкой ДО ввода пароля (settings.js removeBackupPassword).
  remove: '',
  verify: 'Введите текущий пароль резервных копий для подтверждения.',
  forgot: 'Пароль резервных копий утерян? Подтвердите владение учётной записью: введите пароль для входа в Web-панель — на втором шаге потребуется код подтверждения.',
  forgotCode: '',
};

let bound = false;
let active = null; // { mode, onSaved, onVerified }

function modalEl() {
  return document.getElementById('backup-password-modal');
}

function fieldCurrent() {
  return document.getElementById('bpw-modal-current');
}

function fieldInput() {
  return document.getElementById('bpw-modal-input');
}

function fieldRepeat() {
  return document.getElementById('bpw-modal-repeat');
}

function forgotBtn() {
  return document.getElementById('bpw-modal-forgot');
}

function errEl() {
  return document.getElementById('bpw-modal-err');
}

function fail(message) {
  const err = errEl();
  if (err) err.textContent = message;
}

function closeBackupPasswordModal() {
  const modal = modalEl();
  if (!modal) return;
  modal.classList.remove('open');
  const wasActive = active;
  active = null;
  fieldCurrent().value = '';
  fieldInput().value = '';
  fieldRepeat().value = '';
  if (errEl()) errEl().textContent = '';
  if (wasActive?.mode === 'verify' && typeof wasActive?.onCancelled === 'function') {
    wasActive.onCancelled();
  }
}

async function submitBackupPasswordModal() {
  const modal = modalEl();
  if (!modal || !active) return;
  const current = fieldCurrent().value;
  const password = fieldInput().value;
  if (errEl()) errEl().textContent = '';
  const mode = active.mode;
  try {
    // «Забыл пароль», фаза 1: пароль Web-учётной записи → код подтверждения
    if (mode === 'forgot') {
      if (!current) {
        fail('Введите пароль Web-учётной записи');
        fieldCurrent().focus();
        return;
      }
      const response = await j('/api/settings/backup-password/forgot', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: current }),
      });
      const channel = response?.channel;
      const onSaved = active.onSaved;
      openBackupPasswordModalBase({ mode: 'forgotCode', onSaved });
      const note = document.getElementById('bpw-modal-note');
      if (note) {
        note.textContent = channel === 'totp'
          ? 'Введите код из приложения-аутентификатора.'
          : 'Код подтверждения отправлен в Telegram. Введите его — он действует 10 минут.';
        note.classList.remove('hidden');
      }
      return;
    }
    // «Забыл пароль», фаза 2: код 2FA/TG → пароль удалён
    if (mode === 'forgotCode') {
      if (!password) {
        fail('Введите код подтверждения');
        fieldInput().focus();
        return;
      }
      await j('/api/settings/backup-password/forgot/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: password }),
      });
      const onSaved = active.onSaved;
      closeBackupPasswordModal();
      toast('Пароль резервных копий удалён', true);
      window.dispatchEvent(new CustomEvent('bot4vps:backup-password-changed'));
      if (typeof onSaved === 'function') onSaved();
      return;
    }
    if (mode === 'verify') {
      if (!password) {
        fail('Введите пароль резервных копий');
        fieldInput().focus();
        return;
      }
      const response = await j('/api/settings/backup-password/verify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (response?.ok === true) {
        const onVerified = active.onVerified;
        closeBackupPasswordModal();
        if (typeof onVerified === 'function') onVerified();
      } else {
        fail('Неверный пароль резервных копий');
        fieldInput().select();
      }
      return;
    }
    if (mode === 'change' && !current) {
      fail('Введите текущий пароль резервных копий');
      fieldCurrent().focus();
      return;
    }
    if (mode === 'remove' && !current) {
      fail('Введите пароль резервных копий');
      fieldCurrent().focus();
      return;
    }
    if (mode !== 'remove' && !password) {
      fail('Пароль не может быть пустым');
      fieldInput().focus();
      return;
    }
    // Задание первого пароля — повтор обязателен: опечатка фатальна,
    // архив этим паролем потом не распаковать.
    if (mode === 'set') {
      const repeat = fieldRepeat().value;
      if (!repeat) {
        fail('Повторите пароль');
        fieldRepeat().focus();
        return;
      }
      if (repeat !== password) {
        fail('Пароли не совпадают');
        fieldRepeat().select();
        return;
      }
    }
    const body = { password: mode === 'remove' ? '' : password };
    if (mode === 'change' || mode === 'remove') body.current_password = current;
    const response = await j('/api/settings/backup-password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const onSaved = active.onSaved;
    closeBackupPasswordModal();
    toast(mode === 'remove'
      ? 'Пароль резервных копий удалён'
      : (response?.configured ? 'Пароль резервных копий сохранён' : 'Готово'), true);
    window.dispatchEvent(new CustomEvent('bot4vps:backup-password-changed'));
    if (typeof onSaved === 'function') onSaved();
  } catch (error) {
    fail(error.message || 'Не удалось сохранить пароль');
  }
}

/* Режимы:
   set    — задать первый пароль (поле нового пароля);
   change — сменить (текущий + новый);
   remove — удалить (текущий);
   verify — только сверить текущий (без изменений). */
function openBackupPasswordModalBase({ mode, onSaved, onVerified, onCancelled }) {
  const modal = modalEl();
  if (!modal) return;
  active = { mode, onSaved, onVerified, onCancelled };
  document.getElementById('bpw-modal-title').textContent = TITLES[mode] || TITLES.set;
  const noteEl = document.getElementById('bpw-modal-note');
  if (noteEl) {
    // Примечание — только там, где оно что-то объясняет (remove/forgotCode —
    // без него: предупреждение удаления живёт в confirm-модалке до ввода).
    noteEl.textContent = NOTES[mode] || '';
    noteEl.classList.toggle('hidden', !noteEl.textContent);
  }
  // change — два поля (текущий + новый); remove — единственное поле
  // подтверждения «Введите пароль резервных копий», поле нового пароля
  // скрыто (удалять — не вводить новый дважды); set — новый пароль +
  // обязательный повтор (опечатка фатальна); verify — единственное поле
  // «Текущий пароль»; forgot — пароль Web-учётной записи (фаза 1 «Забыл
  // пароль»); forgotCode — код подтверждения (фаза 2).
  const needCurrent = mode === 'change' || mode === 'remove' || mode === 'forgot';
  const singleField = mode === 'verify' || mode === 'remove'
    || mode === 'forgot' || mode === 'forgotCode';
  // Единственное поле remove/forgot — «текущий пароль», а verify/forgotCode —
  // как раз ПОЛЕ ВВОДА (пароль/код подтверждения), его прятать нельзя.
  const needInput = mode === 'set' || mode === 'change'
    || mode === 'verify' || mode === 'forgotCode';
  const needRepeat = mode === 'set';
  const currentLabel = document.getElementById('bpw-modal-current-label');
  if (currentLabel) {
    currentLabel.textContent = mode === 'remove'
      ? 'Введите пароль резервных копий'
      : (mode === 'forgot' ? 'Пароль Web-учётной записи' : 'Текущий пароль резервных копий');
    currentLabel.classList.toggle('hidden', !needCurrent);
  }
  document.getElementById('bpw-modal-current-wrap')?.classList.toggle('hidden', !needCurrent);
  const inputLabel = document.getElementById('bpw-modal-input-label');
  if (inputLabel) {
    inputLabel.textContent = mode === 'verify' ? 'Текущий пароль'
      : (mode === 'forgotCode' ? 'Код подтверждения'
      : (mode === 'change' ? 'Новый пароль резервных копий' : 'Пароль резервных копий'));
    inputLabel.classList.toggle('hidden', !needInput);
  }
  document.getElementById('bpw-modal-input-wrap')?.classList.toggle('hidden', !needInput);
  document.getElementById('bpw-modal-repeat-label')?.classList.toggle('hidden', !needRepeat);
  document.getElementById('bpw-modal-repeat-wrap')?.classList.toggle('hidden', !needRepeat);
  // Подсказка под полем повтора показывается вместе с самим полем
  document.getElementById('bpw-modal-repeat-hint')?.classList.toggle('hidden', !needRepeat);
  fieldInput().setAttribute('autocomplete', mode === 'forgotCode' ? 'one-time-code'
    : (singleField ? 'current-password' : 'new-password'));
  if (mode === 'forgotCode') fieldInput().setAttribute('inputmode', 'numeric');
  else fieldInput().removeAttribute('inputmode');
  document.getElementById('bpw-modal-hint')?.classList.toggle('hidden', singleField);
  forgotBtn()?.classList.toggle('hidden', mode !== 'remove');
  fieldCurrent().value = '';
  fieldInput().value = '';
  fieldRepeat().value = '';
  if (errEl()) errEl().textContent = '';
  bindPasswordToggles(modal);
  modal.classList.add('open');
  setTimeout(() => (needCurrent ? fieldCurrent() : fieldInput())?.focus(), 30);
}

export function openBackupPasswordModal(options = {}) {
  openBackupPasswordModalBase(options);
}

/* Сверка пароля без изменения (подтверждение снятия галочки защиты). */
export function openPasswordConfirmModal({ onVerified, onCancelled } = {}) {
  openBackupPasswordModalBase({ mode: 'verify', onVerified, onCancelled });
}

function bindBackupPasswordModal() {
  if (bound) return;
  const modal = modalEl();
  if (!modal) return;
  bound = true;
  document.getElementById('bpw-modal-ok')?.addEventListener('click', submitBackupPasswordModal);
  document.getElementById('bpw-modal-cancel')?.addEventListener('click', closeBackupPasswordModal);
  // «Забыл пароль» (только в режиме удаления): переход к подтверждению
  // владельца — пароль Web-учётной записи + код 2FA/Telegram.
  forgotBtn()?.addEventListener('click', () => {
    if (!active || active.mode !== 'remove') return;
    const onSaved = active.onSaved;
    openBackupPasswordModalBase({ mode: 'forgot', onSaved });
  });
  [fieldCurrent(), fieldInput(), fieldRepeat()].forEach(input => {
    input?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitBackupPasswordModal();
      }
    });
  });
  // Клик по фону НЕ закрывает модалку (любой режим): пароль — значимое
  // действие, случайный промах мимо окна не должен терять ввод.
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeBackupPasswordModal();
    }
  });
}

document.addEventListener('DOMContentLoaded', bindBackupPasswordModal);
bindBackupPasswordModal();
