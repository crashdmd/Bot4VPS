import { j, esc } from '../../api.js?v=20260821-telegram-health-v1';
import { toast, confirmAction, infoModal } from '../../ui.js';

const ROOT = '/api/settings/mobile-access';
let closePairCode = null;
let statusView = null;
const settledPrimaryTransfers = new Set();
let closeSecurityDialog = null;
let requiredPrimaryDialog = false;
let connectionChangeDialog = null;
let connectionChangeId = null;
const CONNECTION_CHANGE_KEY = 'bot4vps_pending_mobile_connection_change';

export function resumePendingMobileConnectionChange() {
  if (connectionChangeDialog) return;
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(CONNECTION_CHANGE_KEY) || 'null'); }
  catch (_) { return; }
  if (!saved || typeof saved.id !== 'string' || !Number.isFinite(saved.expires)) return;
  // Restore the blocking window immediately, even when another page opens.
  // Only the service can tell us whether the operation finished during reload.
  confirmConnectionChange({ ...saved, state: 'pending', recovering: true,
    remaining: Math.min(120, Math.max(0, saved.expires - Date.now() / 1000)),
    message: 'Проверяем состояние подтверждения…',
  }, () => statusView?.rerender?.()).then(result => toast(result.message, result.state === 'approved'));
}
export function closeMobilePairCode() { closePairCode?.(); }
export function stopMobileAccess() {
  if (!requiredPrimaryDialog) closeSecurityDialog?.();
  if (!statusView) return;
  clearTimeout(statusView.timer);
  clearTimeout(statusView.primaryTimer);
  statusView.controller.abort();
  document.removeEventListener('visibilitychange', statusView.onVisibility);
  statusView = null;
}
function request(path = '', body, options = {}) {
  return j(ROOT + path, {
    ...options,
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'X-Bot4VPS-Pairing-Web': '1', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

function httpsAddress(value, servicePort) {
  const address = String(value || '').trim();
  if (!address) return '';
  const secure = /^https:\/\//i.test(address) ? address : 'https://' + address.replace(/^http:\/\//i, '');
  try {
    const url = new URL(secure);
    const authority = secure.split('://')[1].split(/[/?#]/)[0];
    const explicitPort = /:\d+$/.test(authority);
    if (explicitPort) return secure;
    url.port = String(servicePort);
    const start = secure.indexOf('://') + 3;
    return secure.slice(0, start + authority.length) + ':' + servicePort + secure.slice(start + authority.length);
  } catch {
    throw new Error('Введите IP или домен; если внешний порт отличается от порта сервиса, добавьте его после двоеточия.');
  }
}

function updateStatus(view, data) {
  if (statusView !== view) return;
  const previousPrimary = view.data?.devices.find(device => device.is_primary);
  view.data = data;
  const badge = view.content.querySelector('#mobile-api-status');
  badge.textContent = view.unavailable ? 'Статус недоступен' : data.error ? 'Ошибка применения' : data.restart_required ? 'Настройки не применены' : data.running ? 'API работает' : 'API выключен';
  badge.className = `set-badge${view.unavailable ? ' warn' : data.error ? ' error' : data.restart_required ? ' warn' : data.running ? ' ok' : ''}`;
  view.content.querySelector('#mobile-pair-form button[type=submit]').disabled = view.unavailable || view.saving || view.pairing || !data.running || data.restart_required || !!data.error;
  const toggle = view.content.querySelector('input[name="enabled"]');
  const locked = !!data.enabled_locked || data.devices.length > 0;
  if (toggle && !view.saving) toggle.checked = locked || data.running;
  if (toggle) toggle.disabled = locked || view.unavailable || view.saving;
  const start = view.content.querySelector('#mobile-api-start');
  if (start) {
    start.hidden = data.running || !data.settings.enabled && !locked;
    start.disabled = view.unavailable || view.saving || !!data.settings_change;
  }
  const toggleHint = view.content.querySelector('#mobile-api-toggle-hint');
  if (toggleHint) toggleHint.textContent = locked ? 'API нельзя выключить, пока есть привязанный телефон' : 'Сразу по сохранённым настройкам';
  view.refreshSaveButton?.();
  const result = view.content.querySelector('#mobile-api-result');
  if (data.error || view.lastError) result.textContent = data.error || '';
  view.lastError = data.error || '';
  const devices = view.content.querySelector('#mobile-device-list');
  const protection = view.content.querySelector('#mobile-unlink-protection');
  if (protection) protection.checked = !!data.unlink_protected;
  const snapshot = JSON.stringify([data.devices, data.procedures]);
  if (devices && view.deviceSnapshot !== snapshot) {
    view.deviceSnapshot = snapshot;
    devices.innerHTML = deviceList(data.devices, data.procedures);
    bindDeviceActions(view);
  }
  const primaryRemoved = previousPrimary && !data.devices.some(device => device.id === previousPrimary.id);
  if (data.primary_selection_pending && !view.selectionPromptShown && devices) {
    view.selectionPromptShown = true;
    primarySelectionDialog(view);
  } else if (primaryRemoved) {
    const chief = data.devices.find(device => device.is_primary);
    infoModal({ title: 'Основной телефон отвязан', message: chief ? `Телефон «${chief.name}» автоматически назначен основным.` : 'Привязанных телефонов больше нет.' });
  }
  if (!data.primary_selection_pending) view.selectionPromptShown = false;
  const primaryTransfer = data.primary_transfer && !settledPrimaryTransfers.has(data.primary_transfer.id) ? data.primary_transfer : null;
  const transfer = view.content.querySelector('#mobile-primary-transfer');
  if (transfer) {
    transfer.hidden = !primaryTransfer;
    transfer.innerHTML = primaryTransfer ? `<p class="set-desc" data-primary-status>${esc(primaryDeliveryHint(primaryTransfer))}</p><p class="set-desc">Прежний основной телефон сохраняет права до завершения переноса. Ожидающий запрос сохраняется при перезапуске панели.</p><button type="button" class="secondary" data-primary-cancel>Отменить перенос</button>` : '';
    transfer.querySelector('[data-primary-cancel]')?.addEventListener('click', async () => {
      try {
        const result = await j('/api/auth/two-factor/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: primaryTransfer.id }) });
        if (!result.ok) throw new Error('Панель не подтвердила отмену переноса');
        settledPrimaryTransfers.add(primaryTransfer.id);
        if (view.primaryPendingId === primaryTransfer.id) { view.primaryPendingId = null; clearTimeout(view.primaryTimer); }
        await refreshDevices(view);
        toast('Перенос отменён', true);
      }
      catch (error) { toast(error.message, false); }
    });
    if (primaryTransfer && view.primaryPendingId !== primaryTransfer.id) {
      clearTimeout(view.primaryTimer);
      view.primaryPendingId = primaryTransfer.id;
      pollPrimaryTransfer(view, primaryTransfer.id);
    }
  }
}

function primaryDeliveryHint(transfer) {
  const waiting = ['approved', 'confirming'].includes(transfer.state)
    ? 'Телефон подтвердил запрос. Ожидаем завершения установки TOTP.'
    : transfer.received_at != null ? 'Телефон получил запрос. Ожидаем вашего решения на телефоне.'
      : 'Получение запроса телефоном ещё не подтверждено. После восстановления связи ожидающий запрос будет доступен приложению.';
  const remaining = transfer.expires_in ?? Math.max(0, Math.ceil((transfer.expires ?? Date.now() / 1000) - Date.now() / 1000));
  return `${waiting} До окончания запроса: ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}.`;
}

async function pollPrimaryTransfer(view, id) {
  const current = () => statusView === view && !view.controller.signal.aborted && view.primaryPendingId === id && !settledPrimaryTransfers.has(id);
  if (!current()) return;
  try {
    const result = await j('/api/auth/two-factor/status', { method: 'POST', signal: view.controller.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
    if (!current()) return;
    const status = view.content.querySelector('#mobile-primary-transfer')?.querySelector('[data-primary-status]');
    if (status && !result.ok && result.state !== 'rejected') status.textContent = primaryDeliveryHint(result);
    if (result.ok || result.state === 'rejected') {
      // Mark completion before refreshing: an in-flight settings response may
      // still contain this transfer and must not start another status request.
      settledPrimaryTransfers.add(id);
      view.primaryPendingId = null;
      clearTimeout(view.primaryTimer);
      try { await refreshDevices(view); }
      catch (_) { /* The regular settings poll will retry the refresh. */ }
      if (statusView === view && !view.controller.signal.aborted) {
        toast(result.ok ? 'Основной телефон изменён. TOTP перенесён.' : 'Перенос отменён', !!result.ok);
      }
      return;
    }
  } catch (error) {
    if (!current()) return;
    if ([401, 403, 404, 410].includes(error.status)) {
      settledPrimaryTransfers.add(id);
      view.primaryPendingId = null;
      clearTimeout(view.primaryTimer);
      toast(error.message, false);
      return;
    }
  }
  if (current()) view.primaryTimer = setTimeout(() => pollPrimaryTransfer(view, id), 2000);
}

function confirmConnectionChange(initial, refresh) {
  if (connectionChangeDialog) return initial.id === connectionChangeId ? connectionChangeDialog
    : connectionChangeDialog.then(() => confirmConnectionChange(initial, refresh));
  connectionChangeId = initial.id;
  try { sessionStorage.setItem(CONNECTION_CHANGE_KEY, JSON.stringify({ id: initial.id, public_url: initial.public_url, expires: initial.expires })); }
  catch (_) {}
  connectionChangeDialog = new Promise(resolve => {
    const modal = document.createElement('div');
    modal.className = 'modal-bg open mobile-connection-change';
    modal.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="mobile-change-title">
      <h3 id="mobile-change-title">Подтвердите новое подключение телефоном</h3>
      <p class="set-desc">Прежний адрес работает до подтверждения. Отсканируйте QR в Bot4VPS Mobile: телефон проверит новый адрес и подтвердит смену.</p>
      <div class="mobile-change-grid"><div class="mobile-change-qr"><div data-qr>${initial.qr ? `<img src="${esc(initial.qr)}" alt="QR новых данных подключения">` : initial.recovering ? '<p>Получаем QR из панели…</p>' : '<p>Подтверждение открыто в другом браузере.</p>'}</div><p class="set-desc">Новый адрес: <strong>${esc(initial.public_url)}</strong></p></div>
      <div class="mobile-change-state"><p data-status role="status" aria-live="polite"></p><strong data-timer aria-label="Время для подтверждения"></strong><p class="set-desc">Если телефон не подтвердит подключение за две минуты, прежние параметры сохранятся.</p><p data-error class="err-hint" role="alert"></p></div></div>
      <div class="set-form-actions"><button type="button" class="secondary" data-cancel>Отмена</button></div></div>`;
    const focus = document.activeElement;
    const inert = new Map([...document.body.children].map(element => [element, element.inert]));
    inert.forEach((_, element) => { element.inert = true; });
    const background = new MutationObserver(mutations => {
      for (const mutation of mutations) for (const element of mutation.addedNodes) {
        if (element instanceof HTMLElement && element !== modal && element.parentElement === document.body) {
          if (!inert.has(element)) inert.set(element, element.inert);
          element.inert = true;
        }
      }
    });
    background.observe(document.body, { childList: true });
    document.body.append(modal);
    const cancel = modal.querySelector('[data-cancel]');
    let state = initial;
    let deadline = performance.now() + initial.remaining * 1000;
    let timer, pollTimer, finished = false;
    const close = async result => {
      if (finished) return;
      finished = true; clearInterval(timer); clearTimeout(pollTimer);
      cancel.disabled = true;
      // Keep the background blocked until it shows the service's final settings.
      try { await refresh?.(); }
      catch (error) { toast(error.message, false); }
      background.disconnect();
      document.removeEventListener('keydown', key, true);
      modal.remove(); inert.forEach((value, element) => { element.inert = value; });
      try { sessionStorage.removeItem(CONNECTION_CHANGE_KEY); } catch (_) {}
      connectionChangeDialog = null; connectionChangeId = null; focus?.focus(); resolve(result);
    };
    const key = event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); }
      if (event.key === 'Tab') { event.preventDefault(); cancel.focus(); }
    };
    document.addEventListener('keydown', key, true);
    const draw = () => {
      modal.querySelector('[data-status]').textContent = state.message;
      if (state.qr && !modal.querySelector('[data-qr] img')) {
        modal.querySelector('[data-qr]').innerHTML = `<img src="${esc(state.qr)}" alt="QR новых данных подключения">`;
      }
      const seconds = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      modal.querySelector('[data-timer]').textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
      if (state.state !== 'pending') cancel.textContent = 'Закрыть';
    };
    const poll = async () => {
      try {
        state = await request('/settings/status', { id: initial.id });
        deadline = performance.now() + state.remaining * 1000;
        modal.querySelector('[data-error]').textContent = '';
        draw();
        if (state.state === 'approved') { await close(state); return; }
      } catch (error) {
        modal.querySelector('[data-error]').textContent = error.message;
        if (error.status === 404) { state = { ...state, state: 'unavailable', message: 'Панель перезапущена или запрос завершён. Проверьте итоговые параметры подключения.' }; draw(); }
        else if ([401, 403].includes(error.status) && performance.now() >= deadline) {
          state = { ...state, state: 'session_ended', message: 'Время ожидания истекло, а веб-сеанс завершился. Войдите снова, чтобы проверить итоговые параметры.' };
          draw();
        }
      }
      if (!finished && state.state === 'pending') pollTimer = setTimeout(poll, 1000);
    };
    cancel.onclick = async () => {
      if (state.state !== 'pending') { await close(state); return; }
      cancel.disabled = true;
      try {
        state = await request('/settings/cancel', { id: initial.id });
        // A simultaneous phone confirmation wins only if the service committed it.
        if (state.state !== 'pending') await close(state);
      } catch (error) { modal.querySelector('[data-error]').textContent = error.message; }
      finally { cancel.disabled = false; }
    };
    draw(); cancel.focus(); timer = setInterval(draw, 250); pollTimer = setTimeout(poll, initial.recovering ? 0 : 1000);
  });
  return connectionChangeDialog;
}

function remainingTime(seconds) {
  const total = Math.max(0, Math.ceil(seconds));
  return [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60].map(v => String(v).padStart(2, '0')).join(':');
}
function deviceList(devices, procedures = []) {
  if (!devices.length) return '<p class="mobile-empty">Привязанных телефонов пока нет.<br>Создайте привязку, чтобы подключить первое устройство.</p>';
  return devices.map(device => {
    const flow = procedures.find(p => p.device_id === device.id);
    let controls = `<button class="secondary" type="button" data-revoke="${esc(device.id)}">Отвязать</button>`;
    if (flow) {
      const status = flow.state === 'code' ? 'Ожидаем одноразовый код' : flow.state === 'phone' ? 'Ожидаем подтверждение телефона' : flow.can_finish ? '72 часа прошли. Можно завершить отвязку.' :
        flow.method === 'delayed' ? `До возможности отвязки: ${remainingTime(flow.remaining)}` : `Устройство будет отвязано через: ${remainingTime(flow.remaining)}`;
      controls = `<div><p role="status">${esc(status)}</p><div class="set-form-actions">${flow.state === 'code' ? `<button type="button" data-unlink-code="${esc(flow.id)}">Ввести код</button>` : ''}${flow.can_finish ? `<button type="button" data-unlink-finish="${esc(flow.id)}">Отвязать</button>` : ''}<button type="button" class="secondary" data-unlink-cancel="${esc(flow.id)}">Отмена отвязки</button></div></div>`;
    }
    return `<div class="mobile-device"><div class="mobile-device-identity"><div class="mobile-device-heading"><strong>${esc(device.name)}</strong></div><small>Привязан ${esc(new Date(device.created * 1000).toLocaleString('ru-RU'))}</small></div><div class="mobile-device-role">${device.is_primary ? '<span class="set-badge ok">Основной телефон</span>' : `<button class="secondary" type="button" data-primary="${esc(device.id)}">Назначить основным</button>`}</div><div class="mobile-device-actions">${controls}</div></div>`;
  }).join('');
}
async function refreshDevices(view) {
  if (statusView === view) updateStatus(view, await request('', undefined, { signal: view.controller.signal }));
}
function securityDialog(title, body, { required = false } = {}) {
  if (requiredPrimaryDialog) throw new Error('Сначала назначьте основной телефон');
  closeSecurityDialog?.();
  const modal = document.createElement('div');
  modal.className = 'modal-bg open mobile-security-dialog';
  modal.innerHTML = `<div class="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="mobile-security-title"><h3 id="mobile-security-title">${esc(title)}</h3><div class="set-form">${body}</div><p data-error class="err-hint" role="alert"></p><div class="set-form-actions"><button type="button" data-confirm>Подтвердить</button><button type="button" class="secondary" data-close ${required ? 'hidden disabled' : ''}>Закрыть</button></div></div>`;
  const focus = document.activeElement;
  const close = () => { modal.remove(); document.removeEventListener('keydown', key); closeSecurityDialog = null; requiredPrimaryDialog = false; focus?.focus(); };
  const key = event => {
    if (event.key === 'Escape') { event.preventDefault(); if (!required) close(); }
    if (event.key === 'Tab') {
      const nodes = [...modal.querySelectorAll('button,input,select')].filter(el => !el.closest('[hidden]') && !el.disabled);
      const first = nodes[0], last = nodes.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  };
  document.body.append(modal);
  document.addEventListener('keydown', key);
  modal.querySelector('[data-close]').onclick = required ? () => {} : close;
  requiredPrimaryDialog = required;
  closeSecurityDialog = close;
  modal.querySelector('input,select,button')?.focus();
  return { modal, close };
}
function codeDialog(view, flowId) {
  const { modal, close } = securityDialog('Подтверждение отвязки', '<label>Одноразовый код<input data-code inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label><p>После проверки начнётся ожидание в один час. Отменить процедуру можно в панели или на телефоне.</p>');
  modal.querySelector('[data-confirm]').onclick = async event => {
    event.currentTarget.disabled = true;
    try {
      await request('/unlink/' + encodeURIComponent(flowId) + '/code', { code: modal.querySelector('[data-code]').value.trim() });
      close(); await refreshDevices(view);
    } catch (error) { modal.querySelector('[data-error]').textContent = error.message; modal.querySelector('[data-confirm]').disabled = false; }
  };
}
function unlinkDialog(view, deviceId) {
  const data = view.data;
  const { modal, close } = securityDialog('Отвязать телефон', `<label>Способ подтверждения<select data-method><option value="mobile">Подтвердить на основном телефоне — сразу</option><option value="totp" ${data.totp_registered ? '' : 'disabled'}>TOTP — ожидание один час</option><option value="telegram" ${data.telegram_available ? '' : 'disabled'}>Telegram OTP — ожидание один час</option><option value="delayed">Отложенная отвязка — 72 часа</option></select></label><p>Через час отвязка завершится автоматически. После 72 часов завершить её нужно вручную. Отменить процедуру можно в панели или на телефоне.</p>${unlinkRoleHint(data, deviceId) ? `<p class="set-desc">${esc(unlinkRoleHint(data, deviceId))}</p>` : ''}`);
  modal.querySelector('[data-confirm]').onclick = async event => {
    event.currentTarget.disabled = true;
    try {
      const result = await request('/unlink/' + encodeURIComponent(deviceId), { method: modal.querySelector('[data-method]').value });
      close(); await refreshDevices(view);
      if (result.state === 'code') codeDialog(view, result.id);
    } catch (error) { modal.querySelector('[data-error]').textContent = error.message; modal.querySelector('[data-confirm]').disabled = false; }
  };
}
function unlinkRoleHint(data, deviceId) {
  if (!data.devices.some(device => device.id === deviceId && device.is_primary)) return '';
  const remaining = data.devices.length - 1;
  return 'Вы отвязываете основной телефон. ' + (remaining === 1
    ? 'Оставшийся телефон автоматически станет основным.' : remaining > 1
      ? 'После отвязки выберите новый основной телефон, подтвердив выбор только паролем администратора.'
      : 'Привязанных телефонов больше не останется.') + ' Код 2FA этого телефона отключится; при доступном Telegram второй фактор переключится на него.';
}
function primarySelectionDialog(view) {
  if (requiredPrimaryDialog) return;
  const { modal, close } = securityDialog('Выберите основной телефон', `<p>Основной телефон отвязан. Выберите новый основной телефон и подтвердите выбор только паролем администратора.</p><label>Телефон<select data-device>${view.data.devices.map(device => `<option value="${esc(device.id)}">${esc(device.name)}</option>`).join('')}</select></label><label>Пароль администратора<input data-password type="password" autocomplete="current-password"></label>`, { required: true });
  modal.querySelector('[data-confirm]').onclick = async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const name = view.data.devices.find(device => device.id === modal.querySelector('[data-device]').value)?.name;
      const result = await request('/primary', { device_id: modal.querySelector('[data-device]').value, password: modal.querySelector('[data-password]').value });
      if (!result.ok) throw new Error('Сервис не подтвердил назначение основного телефона');
      close(); await refreshDevices(view);
      infoModal({ title: 'Основной телефон назначен', message: `Телефон «${name}» назначен основным.` });
    } catch (error) { modal.querySelector('[data-error]').textContent = error.message; button.disabled = false; }
  };
}
export async function resumeRequiredPrimarySelection() {
  if (requiredPrimaryDialog) return;
  const data = await request();
  if (statusView) updateStatus(statusView, data);
  else if (data.primary_selection_pending && data.devices.length > 1) primarySelectionDialog({ data });
}
function bindDeviceActions(view) {
  view.content.querySelectorAll('[data-primary]').forEach(button => {
    button.onclick = () => {
      const passwordOnly = view.data.primary_selection_pending && !view.data.primary_device_id;
      const needsCode = !passwordOnly && (view.data.totp_registered || view.data.telegram_available);
      const { modal, close } = securityDialog('Назначить основной телефон', `<p>Основной телефон подтверждает вход при 2FA, отзыв устройств и смену Mobile API. При переносе кода прежний телефон сохраняет права до установки нового TOTP.</p><label>Пароль администратора<input data-password type="password" autocomplete="current-password"></label>${needsCode ? `<label><span data-code-label>${view.data.totp_registered ? 'TOTP-код' : 'Код из Telegram'}</span><input data-code inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label>` : ''}${!passwordOnly && view.data.telegram_available ? '<button type="button" class="secondary" data-telegram>Получить код Telegram</button>' : ''}`);
      let telegramId = null;
      modal.querySelector('[data-telegram]')?.addEventListener('click', async event => {
        const trigger = event.currentTarget;
        const codeInput = modal.querySelector('[data-code]');
        const submit = modal.querySelector('[data-confirm]');
        trigger.disabled = true;
        codeInput.value = '';
        codeInput.disabled = true;
        submit.disabled = true;
        try {
          const result = await request('/primary/telegram', { device_id: button.dataset.primary, password: modal.querySelector('[data-password]').value });
          telegramId = result.id;
          modal.querySelector('[data-code-label]').textContent = 'Код из Telegram';
          codeInput.disabled = false;
          codeInput.focus();
          modal.querySelector('[data-error]').textContent = '';
        } catch (error) { modal.querySelector('[data-error]').textContent = error.message; }
        finally { trigger.disabled = false; codeInput.disabled = false; submit.disabled = false; }
      });
      modal.querySelector('[data-confirm]').onclick = async event => {
        const submit = event.currentTarget;
        submit.disabled = true;
        try {
          const result = await request('/primary', { device_id: button.dataset.primary, password: modal.querySelector('[data-password]').value,
            code: modal.querySelector('[data-code]')?.value || '', telegram_id: telegramId });
          close(); await refreshDevices(view); toast(result.message || 'Основной телефон назначен', !!result.ok);
        } catch (error) { modal.querySelector('[data-error]').textContent = error.message; submit.disabled = false; }
      };
    };
  });
  view.content.querySelectorAll('[data-revoke]').forEach(button => {
    button.onclick = async () => {
      if (view.data.unlink_protected) { unlinkDialog(view, button.dataset.revoke); return; }
      if (!await confirmAction({ title: 'Отвязать телефон?', message: 'Соединения этого телефона закроются. Для повторного подключения понадобится новый код. ' + unlinkRoleHint(view.data, button.dataset.revoke), confirmFirst: true })) return;
      button.disabled = true;
      try { await request('/revoke/' + encodeURIComponent(button.dataset.revoke), {}); await refreshDevices(view); toast('Телефон отвязан', true); }
      catch (error) { toast(error.message, false); button.disabled = false; }
    };
  });
  view.content.querySelectorAll('[data-unlink-code]').forEach(button => { button.onclick = () => codeDialog(view, button.dataset.unlinkCode); });
  for (const action of ['cancel', 'finish']) {
    view.content.querySelectorAll(`[data-unlink-${action}]`).forEach(button => {
      button.onclick = async () => {
        button.disabled = true;
        try { await request('/unlink/' + encodeURIComponent(button.dataset[action === 'cancel' ? 'unlinkCancel' : 'unlinkFinish']) + '/' + action, {}); await refreshDevices(view); }
        catch (error) { toast(error.message, false); button.disabled = false; }
      };
    });
  }
}
function disableProtectionDialog(view) {
  const primary = view.data.devices.find(device => device.is_primary);
  const telegram = view.data.two_factor_channel === 'telegram';
  const totp = view.data.two_factor_enabled && !telegram;
  const { modal, close } = securityDialog('Отключить защиту от отвязки', `<label>Подтверждение<select data-method><option value="web">Пароль администратора${telegram ? ' и код Telegram' : totp ? ' и TOTP' : ''}</option><option value="mobile" ${primary ? '' : 'disabled'}>На основном телефоне</option></select></label><div data-web><label>Пароль администратора<input type="password" data-password autocomplete="current-password"></label>${totp ? '<label>TOTP-код<input data-code inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label>' : ''}</div><p data-phone hidden>Запрос будет отправлен на основной телефон «${esc(primary?.name || 'не назначен')}».</p><p>После отключения защиты отвязка из веб-панели будет выполняться сразу.</p>`);
  modal.querySelector('[data-method]').onchange = event => {
    modal.querySelector('[data-web]').hidden = event.target.value === 'mobile';
    modal.querySelector('[data-phone]').hidden = event.target.value !== 'mobile';
  };
  modal.querySelector('[data-confirm]').onclick = async event => {
    event.currentTarget.disabled = true;
    try {
      const result = await request('/protection', { enabled: false, method: modal.querySelector('[data-method]').value,
        password: modal.querySelector('[data-password]').value, code: modal.querySelector('[data-code]')?.value || '', device_id: primary?.id });
      if (result.pending && telegram && modal.querySelector('[data-method]').value === 'web') {
        if (!modal.querySelector('[data-code]')) {
          modal.querySelector('[data-web]').insertAdjacentHTML('beforeend', '<label>Код из Telegram<input data-code inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label>');
        }
        modal.querySelector('[data-error]').textContent = result.message;
        modal.querySelector('[data-code]').focus();
        modal.querySelector('[data-confirm]').disabled = false;
        return;
      }
      close(); await refreshDevices(view);
      if (result.pending) toast('Подтвердите отключение защиты на телефоне', true);
    } catch (error) { modal.querySelector('[data-error]').textContent = error.message; modal.querySelector('[data-confirm]').disabled = false; }
  };
}

function watchStatus(view) {
  async function refresh() {
    clearTimeout(view.timer);
    if (statusView !== view) return;
    if (!view.content.isConnected) { stopMobileAccess(); return; }
    if (view.refreshing) return;
    if (!document.hidden && !view.saving) {
      view.refreshing = true;
      try {
        const data = await request('', undefined, { signal: view.controller.signal });
        if (!view.saving) { view.unavailable = false; updateStatus(view, data); }
      } catch (error) {
        if (statusView === view && !view.saving && error.name !== 'AbortError') {
          view.unavailable = true;
          updateStatus(view, view.data);
        }
      } finally { view.refreshing = false; }
    }
    if (statusView === view) view.timer = setTimeout(refresh, 3000);
  }
  view.onVisibility = () => { if (!document.hidden) refresh(); };
  document.addEventListener('visibilitychange', view.onVisibility);
  view.timer = setTimeout(refresh, 3000);
}

async function copy(value) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else {
      // The private Web panel can be HTTP, where Clipboard API is unavailable.
      const input = document.createElement('textarea');
      input.value = value; input.style.position = 'fixed'; input.style.opacity = '0';
      document.body.append(input); input.select();
      try { if (!document.execCommand('copy')) throw new Error('Выделите код и скопируйте его вручную'); }
      finally { input.remove(); }
    }
    toast('Код привязки скопирован', true);
  } catch (error) { toast(error.message || 'Не удалось скопировать код', false); }
}

function showPairCode(data) {
  closeMobilePairCode();
  const modal = document.createElement('div');
  modal.id = 'mobile-pair-dialog'; modal.className = 'modal-bg open mobile-security-dialog';
  modal.innerHTML = `<div class="modal confirm-modal mobile-pair-modal" role="dialog" aria-modal="true" aria-labelledby="mobile-pair-title">
    <div class="modal-head"><h2 id="mobile-pair-title">Привязать телефон</h2><button type="button" class="modal-close" aria-label="Закрыть">×</button></div>
    <p class="set-desc" data-pair-instructions>Отсканируйте QR в Bot4VPS Mobile. Привязка действует 10 минут и используется один раз.</p>
    <p class="set-desc">Адрес API в коде: <strong>${esc(data.public_url)}</strong></p>
    <div data-invitation><img class="mobile-pair-qr" src="${esc(data.qr)}" alt="QR-код для привязки телефона">
      <button type="button" class="secondary" data-reveal>Получить код</button>
      <div data-manual hidden><label class="set-form">Код привязки<textarea readonly rows="4" autocomplete="off" spellcheck="false">${esc(data.code)}</textarea></label>
      <div class="set-form-actions"><button type="button" data-copy>Скопировать код</button><button type="button" class="secondary" data-show-qr>Показать QR</button></div></div></div>
    <p class="set-desc" data-pair-status role="status" aria-live="polite">Ожидаем привязку телефона…</p>
    <div class="set-form-actions"><button type="button" class="secondary" data-close>Закрыть</button></div></div>`;
  const returnFocus = document.activeElement;
  const controller = new AbortController();
  let timer, closed = false;
  const deadline = Date.now() + data.expires_in * 1000;
  function clearInvitation() { modal.querySelector('[data-invitation]').replaceChildren(); data.code = ''; data.qr = ''; }
  function fitCode() {
    const input = modal.querySelector('textarea');
    if (!input || input.closest('[hidden]')) return;
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight + 2}px`;
  }
  function close() {
    closed = true; clearTimeout(timer); controller.abort(); clearInvitation();
    modal.remove(); document.removeEventListener('keydown', onKey); closePairCode = null; returnFocus?.focus();
    window.removeEventListener('resize', fitCode);
  }
  async function poll() {
    if (closed) return;
    const label = modal.querySelector('[data-pair-status]');
    if (Date.now() >= deadline) { clearInvitation(); label.textContent = 'Привязка истекла. Закройте окно и создайте новую.'; return; }
    try {
      const result = await request('/pair/status', { status_token: data.status_token }, { signal: controller.signal });
      if (closed) return;
      if (result.state === 'paired') {
        clearInvitation(); label.textContent = `Телефон «${result.name}» успешно привязан.`;
        toast('Телефон привязан', true);
        if (statusView) {
          const view = statusView;
          const state = await request('', undefined, { signal: controller.signal });
          updateStatus(view, state);
        }
        return;
      }
      if (result.state === 'expired') { clearInvitation(); label.textContent = 'Привязка истекла или отозвана. Создайте новую.'; return; }
      label.textContent = 'Ожидаем привязку телефона…';
    } catch (error) {
      if (closed) return;
      label.textContent = 'Не удалось проверить привязку. Повторяем подключение…';
    }
    timer = setTimeout(poll, 2000);
  }
  function onKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const controls = [...modal.querySelectorAll('button,textarea')].filter(el => !el.closest('[hidden]'));
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  modal.querySelector('.modal-close').onclick = close;
  modal.querySelector('[data-close]').onclick = close;
  modal.querySelector('[data-copy]').onclick = () => copy(data.code);
  modal.querySelector('[data-reveal]').onclick = event => {
    modal.querySelector('[data-pair-instructions]').textContent = 'Вставьте код в Bot4VPS Mobile: «Ввести код». Привязка действует 10 минут и используется один раз.';
    modal.querySelector('.mobile-pair-qr').hidden = true;
    modal.querySelector('[data-manual]').hidden = false;
    event.currentTarget.hidden = true;
    const input = modal.querySelector('textarea');
    fitCode();
    input.focus();
  };
  modal.querySelector('[data-show-qr]').onclick = () => {
    modal.querySelector('[data-pair-instructions]').textContent = 'Отсканируйте QR в Bot4VPS Mobile. Привязка действует 10 минут и используется один раз.';
    modal.querySelector('[data-manual]').hidden = true;
    modal.querySelector('.mobile-pair-qr').hidden = false;
    modal.querySelector('[data-reveal]').hidden = false;
    modal.querySelector('[data-reveal]').focus();
  };
  modal.onclick = event => { if (event.target === modal) close(); };
  document.body.append(modal); document.addEventListener('keydown', onKey);
  window.addEventListener('resize', fitCode);
  closePairCode = close;
  modal.querySelector('[data-reveal]').focus();
  timer = setTimeout(poll, 1000);
}

export async function renderMobileAccess(content, { onOpenSecurity } = {}) {
  stopMobileAccess();
  const rerender = () => renderMobileAccess(content, { onOpenSecurity });
  const view = { content, rerender, controller: new AbortController(), pairing: false, saving: false };
  statusView = view;
  const results = await Promise.allSettled([
    request('', undefined, { signal: view.controller.signal }),
    j('/api/mobile-app', { signal: view.controller.signal }),
  ]);
  if (statusView !== view) return;
  const data = results[0].status === 'fulfilled' ? results[0].value : null;
  const release = results[1].status === 'fulfilled' ? results[1].value : { available: false, message: 'Не удалось проверить файл приложения. Повторите проверку; если ошибка останется, обновите и перезапустите Bot4VPS.' };
  const installationNote = String(release.installation_note || '');
  const noteParts = installationNote.match(/^([\s\S]+?[.!?])\s+([\s\S]+)$/);
  const noteHtml = noteParts
    ? `<details class="mobile-install-note"><summary>${esc(noteParts[1])}</summary><p class="set-desc">${esc(noteParts[2])}</p></details>`
    : (installationNote ? `<p class="set-desc" role="note">${esc(installationNote)}</p>` : '');
  const appCard = `<div class="set-form-card mobile-app-card">
    <div class="mobile-app-heading"><div class="mobile-app-mark"><img src="/static/logo.png?v=20260905-logo-v2" alt=""></div><div><h3>Bot4VPS Mobile ${release.available ? '<span class="set-badge">' + esc(release.version) + '</span>' : ''}</h3><p>Ваши серверы и сервисы на Android</p></div><button type="button" class="icon-btn mobile-apk-check" id="mobile-check-apk" title="Проверить обновление APK и восстановить файл, если он удалён" aria-label="Проверить обновление APK"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 6.1a8 8 0 0 1 13.4 3.4M4.5 14.5a8 8 0 0 0 13.4 3.4"/></svg><span>Проверить обновление APK</span></button></div>
    <div class="mobile-app-meta"><span>Android 8.0 и новее</span>${release.available ? '<span>APK · ' + esc((release.size / 1048576).toFixed(1)) + ' МБ</span>' : ''}</div>
    <p class="set-desc">Скачайте APK на телефон и откройте файл для установки. Приложение обновляется из репозитория Bot4VPS-Mobile независимо от панели. Telegram для скачивания не нужен.</p>
    ${noteHtml}
    <div class="set-form-actions mobile-install-actions">${release.available ? '<a class="btn" id="mobile-download-apk" href="/api/mobile-app/download" download>Скачать APK</a>' : '<button type="button" id="mobile-download-apk" disabled>Скачать APK</button>'}
      <button type="button" class="secondary" id="mobile-send-apk" ${release.available && release.telegram_available ? '' : 'disabled'}>Получить в Telegram</button></div>
    ${release.available ? '<p class="set-desc">' + (release.telegram_hint ? esc(release.telegram_hint) + '. Скачайте APK кнопкой выше.' : 'Через Telegram файл отправится получателю из настроек панели.') + '</p>' : '<p class="set-desc" role="status">' + esc(release.message || 'Файл приложения недоступен. Проверьте целостность установки Bot4VPS.') + '</p><button type="button" class="secondary mobile-apk-retry" id="mobile-apk-retry">Повторить проверку APK</button>'}
  </div>`;
  const pairingGuide = `<div class="mobile-pair-guide"><ol><li>Укажите порт и доступный телефону IP или домен. Сохраните подключение и включите «Разрешить подключение».</li><li>Нажмите «Создать QR-код». В Bot4VPS Mobile откройте «Ещё → Подключение → Создать связь с сервисом» и отсканируйте QR.</li><li>Для ручной привязки нажмите «Получить код» в окне QR, затем «Ввести код» в приложении.</li></ol><p class="set-desc">QR и код действуют 10 минут, используются один раз. После привязки вход в приложение выполняется автоматически.</p><button type="button" class="faq-help-link" id="mobile-guide-help">Полная инструкция в справочнике</button></div>`;
  const guide = `<details class="mobile-quick-guide"><summary>Как подключить телефон</summary>${pairingGuide}</details>`;
  function bindApk() {
    const check = content.querySelector('#mobile-check-apk');
    if (check) check.onclick = async () => {
      check.disabled = true;
      check.setAttribute('aria-busy', 'true');
      const title = check.title;
      check.title = 'Проверка APK…';
      try {
        const result = await j('/api/mobile-app/check', { method: 'POST', headers: { 'X-Bot4VPS-Pairing-Web': '1' } });
        toast(result.ok ? (result.updated ? 'APK приложения обновлён до ' + result.version : 'Сохранён актуальный APK ' + result.version) : result.error, !!result.ok);
        await rerender();
      } catch (error) { toast(error.message, false); }
      finally { check.disabled = false; check.removeAttribute('aria-busy'); check.title = title; }
    };
    const retry = content.querySelector('#mobile-apk-retry');
    if (retry) retry.onclick = () => rerender().catch(error => toast(error.message, false));
    const hints = {
      'mobile-connect-help': { title: 'Подключение мобильного приложения', message: 'В «Порте для сервиса» укажите порт, на котором Bot4VPS принимает запросы приложения. В адресе достаточно IP или домена, доступного телефону: HTTPS и сертификат настраиваются автоматически. Можно вставить и полный адрес с https://. Если внешний порт отличается от порта сервиса, добавьте его к адресу, например api.example.com:9444. Для доступа извне пробросьте TCP-порт на роутере к машине с Bot4VPS. Web-порт можно оставить внутри доверенной сети; HTTPS Web-панели включать не требуется. При сохранении Bot4VPS открывает только свой порт в поддерживаемом локальном файрволле; при выключении останавливает API и удаляет своё правило. Настройки добавленных VPS и роутера не меняются.', handbookAnchor: 'mobile-connection' },
      'mobile-phones-help': { title: 'Привязка телефона и отзыв доступа', message: 'Создайте привязку и отсканируйте QR в приложении. Для ручного ввода нажмите «Получить код». Адрес и отпечаток ключа подставятся автоматически. QR и код действуют 10 минут и используются один раз вместе. Web подтвердит успешную привязку. API разрешает работу только привязанным устройствам, даже если пароль Web выключен. Первую привязку через HTTP выполняйте только в доверенной сети. Если телефон потерян, отзовите его доступ в этом списке.', handbookAnchor: 'mobile-pairing' },
      'mobile-guide-help': { title: 'Bot4VPS Mobile: установка и подключение', message: 'Скачайте APK или получите его через Telegram, включите отдельное подключение и привяжите телефон кодом из Web. Подробные шаги, защита приложения и устранение ошибок — в справочнике.', handbookAnchor: 'mobile-app' },
    };
    for (const [id, hint] of Object.entries(hints)) {
      const help = content.querySelector('#' + id);
      if (help) help.onclick = () => infoModal(hint);
    }
    const button = content.querySelector('#mobile-send-apk');
    if (!button) return;
    button.onclick = async () => {
      button.disabled = true;
      try { const result = await j('/api/mobile-app/send', { method: 'POST', headers: { 'X-Bot4VPS-Pairing-Web': '1' } }); toast(result.message, true); }
      catch (error) { toast(error.message, false); }
      finally { button.disabled = !release.available || !release.telegram_available; }
    };
  }
  if (!data) {
    const error = results[0].reason;
    const hint = error?.status === 401
      ? 'Войдите в Web-панель и повторите проверку.'
      : error?.status === 404
        ? 'Без Web-авторизации привязка доступна из локальной сети: откройте панель по локальному IP или имени .local. Для привязки из внешней сети включите авторизацию.'
        : error?.message || 'Не удалось получить состояние подключения. Повторите проверку.';
    const needsLogin = error?.status === 401 || error?.status === 404;
    content.innerHTML = `<section class="set-section mobile-access"><div class="set-section-head"><h2>Мобильное приложение</h2><p>Установка и подключение Bot4VPS Mobile</p></div>${appCard}
      <div class="set-form-card"><div class="set-form-title"><div><h3>Подключение <button type="button" class="faq-help-link" id="mobile-connect-help">Подробнее</button></h3><p>Настройка подключения недоступна</p></div></div><p class="set-desc" role="status">${esc(hint)}</p>${onOpenSecurity && needsLogin ? '<button type="button" class="secondary" id="mobile-security-settings">Настройки входа</button>' : ''}<button type="button" class="secondary" id="mobile-refresh">Повторить проверку</button></div>${guide}</section>`;
    bindApk();
    const security = content.querySelector('#mobile-security-settings');
    if (security) security.onclick = () => onOpenSecurity();
    content.querySelector('#mobile-refresh').onclick = () => rerender().catch(error => toast(error.message, false));
    return;
  }
  const cfg = data.settings;
  content.innerHTML = `<section class="set-section mobile-access"><div class="set-section-head"><h2>Мобильное приложение</h2><p>Приложение для Android и разрешённые телефоны</p></div>${appCard}
    <div class="mobile-setup-grid">
    <div class="set-form-card mobile-connection-card"><div class="mobile-connection-columns"><div class="mobile-connection-settings"><div class="set-form-title"><div><h3>Подключение <button type="button" class="faq-help-link" id="mobile-connect-help" aria-label="Подробнее: подключение приложения">Подробнее</button></h3><p>Отдельный защищённый доступ для телефона</p></div><span id="mobile-api-status" class="set-badge" role="status" aria-live="polite"></span></div>
      <form class="set-form" id="mobile-api-settings">
        <div class="mobile-api-controls"><label class="mobile-service-port" title="На этом порту Bot4VPS принимает запросы приложения. Выберите порт, отличный от порта Web-панели.">Порт для сервиса<input name="port" type="number" min="1" max="65535" required value="${esc(cfg.port)}" inputmode="numeric" aria-describedby="mobile-api-port-hint"><small id="mobile-api-port-hint">На этой машине</small></label>
        <div class="mobile-api-toggle"><div class="set-tls-toggle-text" title="Сразу включает или выключает подключение по сохранённым адресу и порту. Изменения в полях применяются кнопкой «Сохранить подключение»."><b>Разрешить подключение</b><small id="mobile-api-toggle-hint">Сразу по сохранённым настройкам</small></div><label class="set-switch" title="Сразу включает или выключает подключение по сохранённым адресу и порту."><input name="enabled" type="checkbox" ${cfg.enabled ? 'checked' : ''} aria-label="Разрешить подключение приложения" aria-describedby="mobile-api-toggle-hint"><span class="set-switch-track"><span></span></span></label></div></div>
        <div class="mobile-connection-fields"><label>Адрес для приложения<input name="public_url" type="text" inputmode="url" placeholder="IP или домен" value="${esc(cfg.public_address ?? cfg.public_url)}" spellcheck="false" autocomplete="url" aria-describedby="mobile-api-address-hint"><small id="mobile-api-address-hint">IP или домен, доступный телефону. HTTPS и сертификат настраиваются автоматически. Без порта используется «Порт для сервиса». Если внешний порт отличается, добавьте его к адресу: api.example.com:9444.</small></label></div>
        <input name="host" type="hidden" value="${esc(cfg.host)}">
        <p class="set-desc mobile-result" id="mobile-api-result" role="status" aria-live="polite">${esc(data.error || '')}</p><div class="set-form-actions"><button type="submit">Сохранить подключение</button><button type="button" class="secondary" id="mobile-api-start" hidden>Запустить API</button></div>
      </form></div>
      <div class="mobile-pair-section"><div class="set-form-title"><div><h3>Подключить телефон <button type="button" class="faq-help-link" id="mobile-phones-help" aria-label="Подробнее: привязка телефона">Подробнее</button></h3><p>Имя устройства приложение передаст автоматически</p></div></div>
        <form id="mobile-pair-form" class="set-form">${pairingGuide}<div class="set-form-actions"><button type="submit" ${!data.running || data.restart_required ? 'disabled' : ''}>Создать QR-код</button></div></form>
      </div>
    </div></div></div>
    <div class="set-form-card mobile-devices-card">
      <div class="mobile-devices-head"><h3>Привязанные устройства</h3><label class="mobile-unlink-control"><span>Защита от отвязки устройства</span><span class="set-switch"><input type="checkbox" id="mobile-unlink-protection" aria-label="Защита от отвязки устройства"><span class="set-switch-track"><span></span></span></span></label><button type="button" class="secondary" id="mobile-refresh">Обновить</button><p>Управление доступом добавленных телефонов</p></div>
      <p class="set-desc">${data.devices.length && !data.primary_device_id ? 'Выберите основной телефон. Подтверждения безопасности доступны только ему.' : 'Основной телефон отвечает за подтверждения безопасности и TOTP панели.'}</p>
      <div id="mobile-device-list">${deviceList(data.devices, data.procedures)}</div>
      <div id="mobile-primary-transfer" hidden></div>
    </div></section>`;
  bindApk();
  content.querySelector('#mobile-unlink-protection').onchange = async event => {
    const toggle = event.currentTarget;
    if (!toggle.checked) { toggle.checked = !!view.data.unlink_protected; disableProtectionDialog(view); return; }
    toggle.disabled = true;
    try { await request('/protection', { enabled: true }); await refreshDevices(view); }
    catch (error) { toggle.checked = !!view.data.unlink_protected; toast(error.message, false); }
    finally { toggle.disabled = false; }
  };
  const connectionForm = content.querySelector('#mobile-api-settings');
  const toggle = content.querySelector('input[name="enabled"]');
  const saveButton = connectionForm.querySelector('button');
  view.refreshSaveButton = () => {
    const fields = new FormData(connectionForm);
    const saved = view.data.settings;
    const changed = Number(fields.get('port')) !== saved.port || fields.get('public_url') !== (saved.public_address ?? saved.public_url);
    saveButton.disabled = view.saving || !changed;
  };
  connectionForm.oninput = view.refreshSaveButton;
  const startSaved = content.querySelector('#mobile-api-start');
  if (startSaved) startSaved.onclick = async () => {
    if (view.saving || statusView !== view) return;
    view.saving = true;
    updateStatus(view, view.data);
    try {
      const result = await request('/start', {});
      await refreshDevices(view);
      if (statusView === view) content.querySelector('#mobile-api-result').textContent = result.message;
    } catch (error) {
      if (statusView === view) { content.querySelector('#mobile-api-result').textContent = error.message; toast(error.message, false); }
    } finally {
      view.saving = false;
      if (statusView === view) updateStatus(view, view.data);
    }
  };
  toggle.onchange = async () => {
    if (view.saving || statusView !== view) return;
    if (view.data.enabled_locked || view.data.devices.length) { toggle.checked = true; toggle.disabled = true; return; }
    const saved = { ...view.data.settings };
    const enabled = toggle.checked;
    if (enabled && !saved.public_url) {
      toggle.checked = saved.enabled;
      toast('Сначала укажите адрес и сохраните подключение.', false);
      return;
    }
    view.saving = true;
    toggle.disabled = true;
    view.refreshSaveButton();
    updateStatus(view, view.data);
    try {
      const result = await request('/settings', { ...saved, enabled });
      if (statusView !== view) return;
      updateStatus(view, { ...view.data, settings: { ...saved, enabled }, running: result.running,
        error: '', restart_required: !!result.restart_required });
      const current = await request('', undefined, { signal: view.controller.signal });
      view.unavailable = false;
      updateStatus(view, current);
      content.querySelector('#mobile-api-result').textContent = result.message;
      toast(result.running ? 'Подключение включено' : 'Подключение выключено', true);
    } catch (error) {
      if (statusView !== view) return;
      try {
        const current = await request('', undefined, { signal: view.controller.signal });
        view.unavailable = false;
        updateStatus(view, current);
      } catch { view.unavailable = true; }
      content.querySelector('#mobile-api-result').textContent = error.message;
      toast(error.message, false);
    } finally {
      view.saving = false;
      if (statusView === view) updateStatus(view, view.data);
    }
  };
  content.querySelector('#mobile-api-settings').onsubmit = async event => {
    event.preventDefault();
    if (view.saving) return;
    const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
    view.saving = true;
    toggle.disabled = true;
    updateStatus(view, view.data);
    const fields = new FormData(form);
    const enteredAddress = fields.get('public_url') || '';
    try {
      let result = await request('/settings', { public_url: httpsAddress(enteredAddress, Number(fields.get('port'))), public_address: enteredAddress, port: Number(fields.get('port')), host: fields.get('host'), enabled: view.data.settings.enabled });
      if (result.confirmation_required) {
        result = await confirmConnectionChange(result.change, rerender);
        toast(result.message, result.state === 'approved');
        return;
      }
      if (statusView !== view) return;
      await rerender();
      if (!content.querySelector('#mobile-api-result')) return;
      content.querySelector('input[name="public_url"]').value = enteredAddress;
      content.querySelector('#mobile-api-result').textContent = result.message;
      toast('Настройки подключения сохранены', true);
    } catch (error) {
      toast(error.message, false);
      if (statusView === view) {
        await rerender().catch(() => {});
        const address = content.querySelector('input[name="public_url"]');
        if (address) address.value = enteredAddress;
      }
    }
    finally {
      view.saving = false;
      if (statusView === view) updateStatus(view, view.data);
    }
  };
  content.querySelector('#mobile-pair-form').onsubmit = async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button[type=submit]'); button.disabled = true;
    view.pairing = true;
    try { const code = await request('/pair', {}); if (statusView === view) showPairCode(code); }
    catch (error) { toast(error.message, false); }
    finally { view.pairing = false; updateStatus(view, view.data); }
  };
  content.querySelector('#mobile-refresh').onclick = () => rerender().catch(error => toast(error.message, false));
  updateStatus(view, data);
  watchStatus(view);
  if (data.settings_change) {
    confirmConnectionChange(data.settings_change, rerender).then(result => {
      toast(result.message, result.state === 'approved');
    }).catch(error => toast(error.message, false));
  }
}
