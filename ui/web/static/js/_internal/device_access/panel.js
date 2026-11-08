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

function updateStatus(view, data) {
  if (statusView !== view) return;
  view.data = data;
  const badge = view.content.querySelector('#mobile-api-status');
  badge.textContent = view.unavailable ? 'Статус недоступен' : data.error ? 'Ошибка применения' : data.restart_required ? 'Настройки не применены' : data.running ? 'API работает' : 'API выключен';
  badge.className = `set-badge${view.unavailable ? ' warn' : data.error ? ' error' : data.restart_required ? ' warn' : data.running ? ' ok' : ''}`;
  view.content.querySelector('#mobile-pair-form button[type=submit]').disabled = view.unavailable || view.pairing || !data.running || data.restart_required || !!data.error;
  const result = view.content.querySelector('#mobile-api-result');
  if (data.error || view.lastError) result.textContent = data.error || '';
  view.lastError = data.error || '';
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
  modal.innerHTML = `<div class="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="mobile-pair-title">
    <div class="modal-head"><h2 id="mobile-pair-title">Привязать телефон</h2><button type="button" class="modal-close" aria-label="Закрыть">×</button></div>
    <p class="set-desc">Вставьте полный код в первое поле подключения приложения. Адрес и ключ сервера подставятся автоматически. Код действует 10 минут и используется один раз.</p>
    <p class="set-desc">Адрес API в коде: <strong>${esc(data.public_url)}</strong></p>
    <label class="set-form">Код привязки<textarea readonly rows="4" autocomplete="off" spellcheck="false">${esc(data.code)}</textarea></label>
    <p class="set-desc">После привязки доступ телефона можно отозвать в этом разделе.</p>
    <div class="set-form-actions"><button type="button" data-copy>Скопировать код</button><button type="button" class="secondary" data-close>Закрыть</button></div></div>`;
  const returnFocus = document.activeElement;
  function close() { modal.remove(); document.removeEventListener('keydown', onKey); closePairCode = null; returnFocus?.focus(); }
  function onKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); }
    if (event.key === 'Tab') {
      const controls = [...modal.querySelectorAll('button,textarea')];
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  modal.querySelector('.modal-close').onclick = close;
  modal.querySelector('[data-close]').onclick = close;
  modal.querySelector('[data-copy]').onclick = () => copy(data.code);
  modal.onclick = event => { if (event.target === modal) close(); };
  document.body.append(modal); document.addEventListener('keydown', onKey);
  closePairCode = close;
  modal.querySelector('[data-copy]').focus();
}

export async function renderMobileAccess(content) {
  stopMobileAccess();
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
    <div class="mobile-app-heading"><div class="mobile-app-mark"><img src="/static/logo.png?v=20260905-logo-v2" alt=""></div><div><h3>Bot4VPS Mobile ${release.available ? '<span class="set-badge">' + esc(release.version) + '</span>' : ''}</h3><p>Ваши серверы и сервисы на Android</p></div></div>
    <div class="mobile-app-meta"><span>Android 8.0 и новее</span>${release.available ? '<span>APK · ' + esc((release.size / 1048576).toFixed(1)) + ' МБ</span>' : ''}</div>
    <p class="set-desc">Скачайте APK на телефон и откройте файл для установки. Telegram для скачивания не нужен.</p>
    <div class="set-form-actions mobile-install-actions">${release.available ? '<a class="btn" id="mobile-download-apk" href="/api/mobile-app/download" download>Скачать APK</a>' : '<button type="button" id="mobile-download-apk" disabled>Скачать APK</button>'}
      <button type="button" class="secondary" id="mobile-send-apk" ${release.available && release.telegram_available ? '' : 'disabled'}>Получить в Telegram</button></div>
    ${release.available ? '<p class="set-desc">' + (release.telegram_hint ? esc(release.telegram_hint) + '. Скачайте APK кнопкой выше.' : 'Через Telegram файл отправится получателю из настроек панели.') + '</p>' : '<p class="set-desc" role="status">' + esc(release.message || 'Файл приложения недоступен. Проверьте целостность установки Bot4VPS.') + '</p><button type="button" class="secondary mobile-apk-retry" id="mobile-apk-retry">Повторить проверку APK</button>'}
  </div>`;
  const guide = `<details class="mobile-quick-guide"><summary>Как подключить телефон</summary><ol><li>Укажите доступный телефону HTTPS-адрес и отдельный порт. Включите подключение и сохраните.</li><li>Создайте код в блоке «Телефоны» и скопируйте его целиком.</li><li>Вставьте код в первое поле подключения приложения. При включённом входе используйте учётную запись панели.</li></ol><button type="button" class="faq-help-link" id="mobile-guide-help">Полная инструкция в справочнике</button></details>`;
  function bindApk() {
    const retry = content.querySelector('#mobile-apk-retry');
    if (retry) retry.onclick = () => renderMobileAccess(content).catch(error => toast(error.message, false));
    const hints = {
      'mobile-connect-help': { title: 'Подключение мобильного приложения', message: 'Укажите HTTPS-адрес и отдельный порт, доступные телефону. Для доступа извне пробросьте на роутере TCP-порт к машине с Bot4VPS; Web-порт можно оставить внутри доверенной сети. API создаёт свой TLS-сертификат, поэтому HTTPS локальной Web-панели включать не требуется. При сохранении Bot4VPS открывает только свой порт в поддерживаемом локальном файрволле; при выключении останавливает API и удаляет своё правило. Настройки добавленных VPS и роутера не меняются.', handbookAnchor: 'mobile-connection' },
      'mobile-phones-help': { title: 'Привязка телефона и отзыв доступа', message: 'Создайте код и вставьте его целиком в первое поле подключения приложения. Адрес и отпечаток ключа подставятся автоматически. Код живёт 10 минут и используется один раз. API разрешает работу только привязанным устройствам, даже если пароль Web выключен. Первую привязку через HTTP выполняйте только в доверенной сети. Если телефон потерян, отзовите его доступ в этом списке.', handbookAnchor: 'mobile-pairing' },
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
      <div class="set-form-card"><div class="set-form-title"><div><h3>Подключение <button type="button" class="faq-help-link" id="mobile-connect-help">Подробнее</button></h3><p>Настройка доступна из доверенной сети</p></div></div><p class="set-desc">Для привязки откройте Web-панель по локальному IP сервера или разрешённому доверенному DNS-имени.</p><button type="button" class="secondary" id="mobile-refresh">Повторить проверку</button></div>${guide}</section>`;
    bindApk();
    content.querySelector('#mobile-refresh').onclick = () => renderMobileAccess(content).catch(error => toast(error.message, false));
    return;
  }
  const cfg = data.settings;
  content.innerHTML = `<section class="set-section mobile-access"><div class="set-section-head"><h2>Мобильное приложение</h2><p>Приложение для Android и разрешённые телефоны</p></div>${appCard}
    <div class="set-form-card"><div class="set-form-title"><div><h3>Подключение <button type="button" class="faq-help-link" id="mobile-connect-help" aria-label="Подробнее: подключение приложения">Подробнее</button></h3><p>Отдельный защищённый доступ для телефона</p></div><span id="mobile-api-status" class="set-badge" role="status" aria-live="polite"></span></div>
      <form class="set-form" id="mobile-api-settings">
        <div class="mobile-api-toggle"><div class="set-tls-toggle-text"><b>Разрешить подключение</b><small>Сохраните настройки, чтобы применить изменение</small></div><label class="set-switch" title="Разрешить подключение приложения"><input name="enabled" type="checkbox" ${cfg.enabled ? 'checked' : ''} aria-label="Разрешить подключение приложения"><span class="set-switch-track"><span></span></span></label></div>
        <div class="mobile-connection-fields"><label>Адрес для приложения<input name="public_url" type="url" placeholder="https://api.example.com:8444" value="${esc(cfg.public_url)}" spellcheck="false" autocomplete="url"><small>Доступный телефону IP или домен с внешним портом.</small></label>
        <label>Порт на сервере<input name="port" type="number" min="1" max="65535" required value="${esc(cfg.port)}" inputmode="numeric"><small>Отдельно от Web-порта.</small></label></div>
        <input name="host" type="hidden" value="${esc(cfg.host)}">
        <div class="set-form-actions"><button type="submit">Сохранить подключение</button></div><p class="set-desc mobile-result" id="mobile-api-result" role="status" aria-live="polite">${esc(data.error || '')}</p>
      </form></div>
    <div class="set-form-card"><div class="set-form-title"><div><h3>Телефоны <button type="button" class="faq-help-link" id="mobile-phones-help" aria-label="Подробнее: привязка телефона">Подробнее</button></h3><p>Доступ только для ваших привязанных устройств</p></div></div>
      <form id="mobile-pair-form" class="set-form"><label for="mobile-phone-name">Название телефона</label><div class="mobile-pair-row"><input id="mobile-phone-name" name="name" maxlength="80" value="Мой телефон" autocomplete="off"><button type="submit" ${!data.running || data.restart_required ? 'disabled' : ''}>Привязать телефон</button></div><p class="set-desc">Код действует 10 минут и используется один раз.</p></form>
      <div class="mobile-devices-head"><span>Привязанные устройства</span><button type="button" class="secondary" id="mobile-refresh">Обновить</button></div>
      <div id="mobile-device-list">${data.devices.length ? data.devices.map(device => `<div class="mobile-device"><div><strong>${esc(device.name)}</strong><small>Привязан ${esc(new Date(device.created * 1000).toLocaleString('ru-RU'))}</small></div><button class="secondary" type="button" data-revoke="${esc(device.id)}">Отозвать доступ</button></div>`).join('') : '<p class="mobile-empty">Привязанных телефонов пока нет.<br>Создайте код, чтобы подключить первое устройство.</p>'}</div>
    </div>${guide}</section>`;
  bindApk();
  content.querySelector('#mobile-api-settings').onsubmit = async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
    view.saving = true;
    try {
      const fields = new FormData(form);
      const result = await request('/settings', { public_url: fields.get('public_url'), port: Number(fields.get('port')), host: fields.get('host'), enabled: fields.has('enabled') });
      if (statusView !== view) return;
      await renderMobileAccess(content);
      if (!content.querySelector('#mobile-api-result')) return;
      content.querySelector('#mobile-api-result').textContent = result.message;
      toast(result.running ? 'API включён' : 'API выключен', true);
    } catch (error) {
      toast(error.message, false);
      if (statusView === view) await renderMobileAccess(content).catch(() => {});
    }
    finally { button.disabled = false; view.saving = false; }
  };
  content.querySelector('#mobile-pair-form').onsubmit = async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
    view.pairing = true;
    try { const code = await request('/pair', { name: new FormData(form).get('name') }); if (statusView === view) showPairCode(code); }
    catch (error) { toast(error.message, false); }
    finally { view.pairing = false; updateStatus(view, view.data); }
  };
  content.querySelector('#mobile-refresh').onclick = () => renderMobileAccess(content).catch(error => toast(error.message, false));
  content.querySelectorAll('[data-revoke]').forEach(button => {
    button.onclick = async () => {
      if (!await confirmAction({ title: 'Отозвать доступ телефона?', message: 'Соединения этого телефона закроются. Для повторного подключения понадобится новый код.', confirmFirst: true })) return;
      button.disabled = true;
      try { await request('/revoke/' + encodeURIComponent(button.dataset.revoke), {}); toast('Доступ телефона отозван', true); if (statusView === view) await renderMobileAccess(content); }
      catch (error) { toast(error.message, false); button.disabled = false; }
    };
  });
  updateStatus(view, data);
  watchStatus(view);
}
