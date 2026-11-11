import { j, esc } from '../../api.js?v=20260821-telegram-health-v1';
import { toast, confirmAction, infoModal } from '../../ui.js';

const ROOT = '/api/settings/mobile-access';
let closePairCode = null;
let statusView = null;
export function closeMobilePairCode() { closePairCode?.(); }
export function stopMobileAccess() {
  if (!statusView) return;
  clearTimeout(statusView.timer);
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
  view.data = data;
  const badge = view.content.querySelector('#mobile-api-status');
  badge.textContent = view.unavailable ? 'Статус недоступен' : data.error ? 'Ошибка применения' : data.restart_required ? 'Настройки не применены' : data.running ? 'API работает' : 'API выключен';
  badge.className = `set-badge${view.unavailable ? ' warn' : data.error ? ' error' : data.restart_required ? ' warn' : data.running ? ' ok' : ''}`;
  view.content.querySelector('#mobile-pair-form button[type=submit]').disabled = view.unavailable || view.saving || view.pairing || !data.running || data.restart_required || !!data.error;
  const toggle = view.content.querySelector('input[name="enabled"]');
  if (toggle && !view.saving) toggle.checked = data.settings.enabled;
  if (toggle) toggle.disabled = view.unavailable || view.saving;
  view.refreshSaveButton?.();
  const result = view.content.querySelector('#mobile-api-result');
  if (data.error || view.lastError) result.textContent = data.error || '';
  view.lastError = data.error || '';
  const devices = view.content.querySelector('#mobile-device-list');
  const snapshot = JSON.stringify(data.devices);
  if (devices && view.deviceSnapshot !== snapshot) {
    view.deviceSnapshot = snapshot;
    devices.innerHTML = deviceList(data.devices);
    bindDeviceActions(view);
  }
}

function deviceList(devices) {
  return devices.length ? devices.map(device => `<div class="mobile-device"><div><strong>${esc(device.name)}</strong><small>Привязан ${esc(new Date(device.created * 1000).toLocaleString('ru-RU'))}</small></div><button class="secondary" type="button" data-revoke="${esc(device.id)}">Отозвать доступ</button></div>`).join('') : '<p class="mobile-empty">Привязанных телефонов пока нет.<br>Создайте привязку, чтобы подключить первое устройство.</p>';
}

function bindDeviceActions(view) {
  view.content.querySelectorAll('[data-revoke]').forEach(button => {
    button.onclick = async () => {
      if (!await confirmAction({ title: 'Отозвать доступ телефона?', message: 'Соединения этого телефона закроются. Для повторного подключения понадобится новый код.', confirmFirst: true })) return;
      button.disabled = true;
      try {
        await request('/revoke/' + encodeURIComponent(button.dataset.revoke), {});
        toast('Доступ телефона отозван', true);
        const data = await request('', undefined, { signal: view.controller.signal });
        updateStatus(view, data);
      } catch (error) { toast(error.message, false); button.disabled = false; }
    };
  });
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
  modal.id = 'mobile-pair-dialog'; modal.className = 'modal-bg open';
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
  const view = { content, controller: new AbortController(), pairing: false, saving: false };
  statusView = view;
  const results = await Promise.allSettled([
    request('', undefined, { signal: view.controller.signal }),
    j('/api/mobile-app', { signal: view.controller.signal }),
  ]);
  if (statusView !== view) return;
  const data = results[0].status === 'fulfilled' ? results[0].value : null;
  const release = results[1].status === 'fulfilled' ? results[1].value : { available: false, message: 'Не удалось проверить файл приложения. Повторите проверку; если ошибка останется, обновите и перезапустите Bot4VPS.' };
  const appCard = `<div class="set-form-card mobile-app-card">
    <div class="mobile-app-heading"><div class="mobile-app-mark"><img src="/static/logo.png?v=20260905-logo-v2" alt=""></div><div><h3>Bot4VPS Mobile ${release.available ? '<span class="set-badge">' + esc(release.version) + '</span>' : ''}</h3><p>Ваши серверы и сервисы на Android</p></div><button type="button" class="icon-btn mobile-apk-check" id="mobile-check-apk" title="Проверить обновление APK и восстановить файл, если он удалён" aria-label="Проверить обновление APK"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 6.1a8 8 0 0 1 13.4 3.4M4.5 14.5a8 8 0 0 0 13.4 3.4"/></svg><span>Проверить обновление APK</span></button></div>
    <div class="mobile-app-meta"><span>Android 8.0 и новее</span>${release.available ? '<span>APK · ' + esc((release.size / 1048576).toFixed(1)) + ' МБ</span>' : ''}</div>
    <p class="set-desc">Скачайте APK на телефон и откройте файл для установки. Приложение обновляется из репозитория Bot4VPS-Mobile независимо от панели. Telegram для скачивания не нужен.</p>
    ${release.installation_note ? '<p class="set-desc" role="note">' + esc(release.installation_note) + '</p>' : ''}
    <div class="set-form-actions mobile-install-actions">${release.available ? '<a class="btn" id="mobile-download-apk" href="/api/mobile-app/download" download>Скачать APK</a>' : '<button type="button" id="mobile-download-apk" disabled>Скачать APK</button>'}
      <button type="button" class="secondary" id="mobile-send-apk" ${release.available && release.telegram_available ? '' : 'disabled'}>Получить в Telegram</button></div>
    ${release.available ? '<p class="set-desc">' + (release.telegram_hint ? esc(release.telegram_hint) + '. Скачайте APK кнопкой выше.' : 'Через Telegram файл отправится получателю из настроек панели.') + '</p>' : '<p class="set-desc" role="status">' + esc(release.message || 'Файл приложения недоступен. Проверьте целостность установки Bot4VPS.') + '</p><button type="button" class="secondary mobile-apk-retry" id="mobile-apk-retry">Повторить проверку APK</button>'}
  </div>`;
  const guide = `<details class="mobile-quick-guide"><summary>Как подключить телефон</summary><ol><li>Укажите порт сервиса и доступный телефону IP или домен. Сохраните подключение, затем включите «Разрешить подключение».</li><li>Укажите название в блоке «Добавить телефон» и нажмите «Создать QR-код».</li><li>Отсканируйте QR в Bot4VPS Mobile. Для ручного ввода нажмите «Получить код» в Web и «Ввести код» в приложении. После привязки приложение откроется автоматически, без Web-логина.</li></ol><button type="button" class="faq-help-link" id="mobile-guide-help">Полная инструкция в справочнике</button></details>`;
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
    content.innerHTML = `<section class="set-section mobile-access"><div class="set-section-head"><h2>Мобильное приложение</h2><p>Установка и подключение Bot4VPS Mobile</p></div>${appCard}
      <div class="set-form-card"><div class="set-form-title"><div><h3>Подключение <button type="button" class="faq-help-link" id="mobile-connect-help">Подробнее</button></h3><p>Настройка подключения недоступна</p></div></div><p class="set-desc">Войдите в Web-панель. Если вход выключен, включите его в «Настройки → Безопасность» для привязки из внешней сети.</p>${onOpenSecurity ? '<button type="button" class="secondary" id="mobile-security-settings">Настройки входа</button>' : ''}<button type="button" class="secondary" id="mobile-refresh">Повторить проверку</button></div>${guide}</section>`;
    bindApk();
    const security = content.querySelector('#mobile-security-settings');
    if (security) security.onclick = () => onOpenSecurity();
    content.querySelector('#mobile-refresh').onclick = () => rerender().catch(error => toast(error.message, false));
    return;
  }
  const cfg = data.settings;
  content.innerHTML = `<section class="set-section mobile-access"><div class="set-section-head"><h2>Мобильное приложение</h2><p>Приложение для Android и разрешённые телефоны</p></div>${appCard}
    <div class="mobile-setup-grid">
    <div class="set-form-card mobile-connection-card"><div class="set-form-title"><div><h3>Подключение <button type="button" class="faq-help-link" id="mobile-connect-help" aria-label="Подробнее: подключение приложения">Подробнее</button></h3><p>Отдельный защищённый доступ для телефона</p></div><span id="mobile-api-status" class="set-badge" role="status" aria-live="polite"></span></div>
      <form class="set-form" id="mobile-api-settings">
        <div class="mobile-api-controls"><label class="mobile-service-port" title="На этом порту Bot4VPS принимает запросы приложения. Выберите порт, отличный от порта Web-панели.">Порт для сервиса<input name="port" type="number" min="1" max="65535" required value="${esc(cfg.port)}" inputmode="numeric" aria-describedby="mobile-api-port-hint"><small id="mobile-api-port-hint">На этой машине</small></label>
        <div class="mobile-api-toggle"><div class="set-tls-toggle-text" title="Сразу включает или выключает подключение по сохранённым адресу и порту. Изменения в полях применяются кнопкой «Сохранить подключение»."><b>Разрешить подключение</b><small id="mobile-api-toggle-hint">Сразу по сохранённым настройкам</small></div><label class="set-switch" title="Сразу включает или выключает подключение по сохранённым адресу и порту."><input name="enabled" type="checkbox" ${cfg.enabled ? 'checked' : ''} aria-label="Разрешить подключение приложения" aria-describedby="mobile-api-toggle-hint"><span class="set-switch-track"><span></span></span></label></div></div>
        <div class="mobile-connection-fields"><label>Адрес для приложения<input name="public_url" type="text" inputmode="url" placeholder="IP или домен" value="${esc(cfg.public_address ?? cfg.public_url)}" spellcheck="false" autocomplete="url" aria-describedby="mobile-api-address-hint"><small id="mobile-api-address-hint">IP или домен, доступный телефону. HTTPS и сертификат настраиваются автоматически. Без порта используется «Порт для сервиса». Если внешний порт отличается, добавьте его к адресу: api.example.com:9444.</small></label></div>
        <input name="host" type="hidden" value="${esc(cfg.host)}">
        <div class="set-form-actions"><button type="submit">Сохранить подключение</button></div><p class="set-desc mobile-result" id="mobile-api-result" role="status" aria-live="polite">${esc(data.error || '')}</p>
      </form></div>
    <div class="set-form-card mobile-add-phone-card"><div class="set-form-title"><div><h3>Добавить телефон <button type="button" class="faq-help-link" id="mobile-phones-help" aria-label="Подробнее: привязка телефона">Подробнее</button></h3><p>Привязка через QR-код или ручной ввод</p></div></div>
      <form id="mobile-pair-form" class="set-form"><label>Название телефона<input id="mobile-phone-name" name="name" maxlength="80" value="Мой телефон" autocomplete="off" aria-describedby="mobile-phone-name-hint"><small id="mobile-phone-name-hint">Поможет найти телефон в списке устройств.</small></label><p class="set-desc">Откройте Bot4VPS Mobile и отсканируйте созданный QR-код. Для ручного ввода выберите «Получить код» в окне привязки.</p><p class="set-desc">QR и код действуют 10 минут и используются один раз. После подключения телефон появится в списке ниже.</p><div class="set-form-actions"><button type="submit" ${!data.running || data.restart_required ? 'disabled' : ''}>Создать QR-код</button></div></form>
    </div></div>
    <div class="set-form-card mobile-devices-card">
      <div class="mobile-devices-head"><div><h3>Привязанные устройства</h3><p>Управление доступом добавленных телефонов</p></div><button type="button" class="secondary" id="mobile-refresh">Обновить</button></div>
      <div id="mobile-device-list">${deviceList(data.devices)}</div>
    </div>${guide}</section>`;
  bindApk();
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
  toggle.onchange = async () => {
    if (view.saving || statusView !== view) return;
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
      const result = await request('/settings', { public_url: httpsAddress(enteredAddress, Number(fields.get('port'))), public_address: enteredAddress, port: Number(fields.get('port')), host: fields.get('host'), enabled: view.data.settings.enabled });
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
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
    view.pairing = true;
    try { const code = await request('/pair', { name: new FormData(form).get('name') }); if (statusView === view) showPairCode(code); }
    catch (error) { toast(error.message, false); }
    finally { view.pairing = false; updateStatus(view, view.data); }
  };
  content.querySelector('#mobile-refresh').onclick = () => rerender().catch(error => toast(error.message, false));
  updateStatus(view, data);
  watchStatus(view);
}
