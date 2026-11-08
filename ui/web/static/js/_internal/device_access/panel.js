import { j, esc } from '../../api.js?v=20260821-telegram-health-v1';
import { toast, confirmAction } from '../../ui.js';

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
    <p class="set-desc">Скопируйте код и вставьте в приложение на экране подключения. Адрес сервера подставится автоматически. Код действует 10 минут и становится недействительным после первой успешной привязки, даже для того же телефона. При создании нового кода ключ сервера остаётся прежним.</p>
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
  let data;
  try { data = await request('', undefined, { signal: view.controller.signal }); }
  catch (error) { if (statusView !== view) return; stopMobileAccess(); throw error; }
  if (statusView !== view) return;
  const cfg = data.settings;
  content.innerHTML = `<section class="set-section"><div class="set-section-head"><h2>Мобильное приложение</h2><p>Подключение к Bot4VPS и разрешённые телефоны</p></div>
    <div class="set-form-card"><div class="set-form-title"><div><h3>Подключение</h3><p>На роутере пробросьте только порт API на LXC. Веб-панель остаётся в домашней сети.</p></div><span id="mobile-api-status" class="set-badge" role="status" aria-live="polite"></span></div>
      <form class="set-form" id="mobile-api-settings">
        <label>Адрес для приложения<input name="public_url" type="url" placeholder="https://белый-IP:8444" value="${esc(cfg.public_url)}"><small>Белый IP или домен с внешним портом API, настроенным на роутере. Без указанного порта HTTPS использует 443.</small></label>
        <label>Порт API на LXC<input name="port" type="number" min="1" max="65535" required value="${esc(cfg.port)}"></label>
        <input name="host" type="hidden" value="${esc(cfg.host)}">
        <label><span><input name="enabled" type="checkbox" ${cfg.enabled ? 'checked' : ''}> Разрешить подключение приложения</span></label>
        <p class="set-desc">Ключ сервера создаётся автоматически. Сертификаты NPM и включение HTTPS веб-панели не требуются.</p>
        <p class="set-desc">При сохранении порт открывается в локальном файрволле LXC. При выключении API останавливается и его правило удаляется. Настройки VPS не меняются.</p>
        <div class="set-form-actions"><button type="submit">Сохранить</button><span class="set-desc" id="mobile-api-result">${esc(data.error || '')}</span></div>
      </form></div>
    <div class="set-form-card" style="margin-top:1rem"><div class="set-form-title"><div><h3>Телефоны</h3><p>Доступ получает только телефон, привязанный вашим кодом.</p></div></div>
      <form id="mobile-pair-form" class="set-form"><label>Название телефона<input name="name" maxlength="80" value="Мой телефон" autocomplete="off"></label>
      <div class="set-form-actions"><button type="submit" ${!data.running || data.restart_required ? 'disabled' : ''}>Привязать телефон</button><button type="button" class="secondary" id="mobile-refresh">Обновить список</button></div></form>
      <div id="mobile-device-list">${data.devices.length ? data.devices.map(device => `<div class="set-port-line"><span style="flex:1"><strong>${esc(device.name)}</strong><small class="set-desc" style="display:block">Привязан ${esc(new Date(device.created * 1000).toLocaleString('ru-RU'))}</small></span><button class="secondary" type="button" data-revoke="${esc(device.id)}">Отозвать доступ</button></div>`).join('') : '<p class="set-desc">Привязанных телефонов пока нет.</p>'}</div>
    </div></section>`;
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
