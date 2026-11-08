import { j, esc } from './api.js';
import { confirmAction } from './ui.js';

const STORAGE_KEY = 'bot4vps:panel-maintenance';
const BUSY = ['downloading', 'installing', 'rolling_back'];
const TITLES = { restart: 'Перезапуск панели', update: 'Обновление панели', rollback: 'Откат панели' };
let active = null;

export function maintenanceActive() { return !!active; }

function remember(operation) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(operation)); } catch { /* хранилище необязательно */ }
}

function forget() {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* хранилище необязательно */ }
}

async function read(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try { return await j(url, { cache: 'no-store', signal: controller.signal }); }
  finally { clearTimeout(timer); }
}

function taskWarning(tasks) {
  const running = tasks.running || [];
  if (!running.length && !tasks.queued) return '';
  if (!running.length) return `В очереди задач: ${tasks.queued}. При остановке они будут отменены и автоматически не возобновятся.`;
  const lines = [`Сейчас выполняется задач: ${running.length}. В очереди: ${tasks.queued}.`];
  running.slice(0, 5).forEach(task => lines.push(`• ${task.name} — ${task.server_name}`));
  if (running.length > 5) lines.push(`И ещё: ${running.length - 5}.`);
  lines.push('', `Дадим выполняющимся задачам до ${tasks.grace_seconds} секунд на завершение, затем начнём принудительную остановку и операцию с панелью. Ожидающие задачи будут отменены.`,
    'Отмена не откатывает уже сделанные изменения на серверах. Задачи автоматически не возобновятся.',
    'Отмена прекращает ожидание задачи в панели; команда на сервере может завершиться сама.');
  return lines.join('\n');
}

export async function confirmPanelMaintenance({ kind, message, confirmText }) {
  if (active) return null;
  // Ошибка чтения не должна превращаться в ложное «нет работающих задач».
  let preview;
  try { preview = await read('/api/system/maintenance'); }
  catch (error) {
    throw new Error(error.status === 401 || error.status === 403
      ? 'Для проверки задач требуется повторный вход в панель.'
      : 'Не удалось проверить выполняющиеся задачи. Проверьте связь с панелью и повторите попытку.');
  }
  if (!preview.instance_id || !Array.isArray(preview.tasks?.running)) {
    throw new Error('Не удалось проверить выполняющиеся задачи. Повторите попытку.');
  }
  const ok = await confirmAction({
    title: TITLES[kind],
    message: [message, taskWarning(preview.tasks)].filter(Boolean).join('\n\n'),
    confirmText,
    cancelText: 'Отмена',
    danger: true,
  });
  return ok ? preview : null;
}

function createProgress(operation) {
  const modal = document.createElement('div');
  modal.className = 'modal-bg open';
  modal.style.zIndex = '110';
  modal.innerHTML = `<div class="modal set-port-modal" role="dialog" aria-modal="true" aria-labelledby="panel-maintenance-title">
    <div class="set-spinner"></div>
    <h3 id="panel-maintenance-title">${esc(TITLES[operation.kind])}</h3>
    <p data-phase role="status" aria-live="polite">Запускаем операцию…</p>
    <p data-tasks class="hint" style="white-space:pre-line"></p>
    <p data-elapsed class="hint"></p>
    <p data-note class="hint">Окно останется открытым, пока проверяем результат.</p>
    <div class="actions">
      <button type="button" class="danger" data-force hidden>Остановить принудительно</button>
      <button type="button" class="secondary" data-cancel hidden style="margin-left:auto">Отмена</button>
      <button type="button" class="secondary" data-finish hidden>Закрыть</button>
    </div>
  </div>`;
  document.body.append(modal);
  modal.tabIndex = -1;
  modal.focus();
  // Escape и клик по фону не прячут ожидание запущенной операции.
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); }
    if (event.key === 'Tab') {
      event.preventDefault();
      const buttons = [...modal.querySelectorAll('button')].filter(button => !button.hidden && !button.disabled);
      const index = buttons.indexOf(document.activeElement);
      const next = index < 0 ? (event.shiftKey ? buttons.length - 1 : 0)
        : (index + (event.shiftKey ? buttons.length - 1 : 1)) % buttons.length;
      (buttons.length ? buttons[next] : modal).focus();
    }
  });
  return modal;
}

function setPhase(message) { active?.modal.querySelector('[data-phase]').replaceChildren(message); }

function renderWait() {
  if (!active) return;
  const operation = active.operation;
  const waiting = operation.stage === 'waiting';
  const elapsed = Math.max(0, Math.floor((Date.now() - (operation.executingAt || operation.started)) / 1000));
  const tasksEl = active.modal.querySelector('[data-tasks]');
  tasksEl.hidden = !waiting;
  tasksEl.textContent = waiting ? operation.preview.tasks.running.map(task => `• ${task.name} — ${task.server_name}`).join('\n') : '';
  active.modal.querySelector('[data-elapsed]').textContent = waiting
    ? `Осталось: ${Math.max(0, Math.ceil(((operation.deadline || Date.now()) - Date.now()) / 1000))} с`
    : `Прошло: ${elapsed} с`;
  active.modal.querySelector('[data-force]').hidden = !waiting;
  active.modal.querySelector('[data-cancel]').hidden = !waiting;
  const note = active.modal.querySelector('[data-note]');
  if (!waiting && operation.stage !== 'starting' && elapsed >= (operation.kind === 'restart' ? 60 : 120)) {
    note.textContent = 'Ожидание затянулось. Продолжаем проверять связь и результат. Не запускайте операцию повторно; при необходимости проверьте журнал сервиса через SSH. Закрытие окна не отменяет операцию.';
    const current = active;
    const button = current.modal.querySelector('[data-finish]');
    button.hidden = false;
    button.textContent = 'Закрыть окно ожидания';
    button.onclick = () => {
      clearTimeout(current.pollTimer);
      clearInterval(current.clockTimer);
      forget();
      if (active === current) active = null;
      current.modal.remove();
    };
  }
}

function closeProgress(current) {
  clearTimeout(current.pollTimer);
  clearInterval(current.clockTimer);
  forget();
  if (active === current) active = null;
  current.modal.remove();
}

function applyPreparation(current, state) {
  if (!state || state.id !== current.operation.id) return false;
  const operation = current.operation;
  const previousStage = operation.stage;
  operation.stage = state.phase;
  if (state.phase === 'cancelled') { closeProgress(current); return true; }
  if (state.phase === 'failed') { finish(`Не удалось выполнить операцию: ${state.error || 'причина не указана'}`); return true; }
  if (state.phase === 'waiting') {
    operation.deadline = Date.now() + state.remaining_seconds * 1000;
    setPhase('Ожидаем окончания текущих задач…');
    current.modal.querySelector('[data-note]').textContent =
      'После отсчёта начнём принудительную остановку оставшихся задач. Можно остановить их сейчас или отменить подготовку.';
  } else if (state.phase === 'stopping') {
    operation.executingAt ||= Date.now();
    const hasTasks = operation.preview.tasks.running.length || operation.preview.tasks.queued;
    setPhase(hasTasks ? 'Останавливаем задачи перед операцией с панелью…' : 'Запускаем операцию с панелью…');
    current.modal.querySelector('[data-note]').textContent = hasTasks
      ? 'Остановка началась. Ожидающие задачи отменяются.'
      : 'Окно останется открытым, пока проверяем результат.';
  } else {
    operation.executingAt ||= Date.now();
    operation.accepted = true;
    operation.seenBusy ||= BUSY.includes(state.result?.status);
    operation.target = state.result?.target || operation.target;
    current.modal.querySelector('[data-note]').textContent = 'Окно останется открытым, пока проверяем результат.';
  }
  renderWait();
  if (previousStage !== operation.stage) {
    (operation.stage === 'waiting' ? current.modal.querySelector('[data-cancel]') : current.modal).focus();
  }
  remember(operation);
  return state.phase === 'waiting' || state.phase === 'stopping';
}

async function post(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    return await j(url, {
      method: 'POST', signal: controller.signal,
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
  } finally { clearTimeout(timer); }
}

async function preparationControl(current, command) {
  if (active !== current || current.controlBusy || current.operation.stage !== 'waiting') return;
  current.controlBusy = true;
  const buttons = ['[data-force]', '[data-cancel]'].map(selector => current.modal.querySelector(selector));
  buttons.forEach(button => { button.disabled = true; });
  try {
    const result = await post(`/api/system/maintenance/${encodeURIComponent(current.operation.id)}/${command}`);
    if (active !== current) return;
    applyPreparation(current, result.maintenance);
  } catch (error) {
    if (active === current) current.modal.querySelector('[data-note]').textContent =
      error.status === 409 ? 'Остановка уже началась. Проверяем состояние операции…'
        : 'Не удалось получить подтверждение. Проверяем состояние; запрос можно повторить.';
  } finally {
    current.controlBusy = false;
    buttons.forEach(button => { button.disabled = false; });
  }
}

function finish(message, { success = false, login = false } = {}) {
  if (!active) return;
  const current = active;
  clearTimeout(current.pollTimer);
  clearInterval(current.clockTimer);
  forget();
  active = null;
  current.modal.querySelector('.set-spinner')?.remove();
  current.modal.querySelector('[data-tasks]').hidden = true;
  current.modal.querySelector('[data-tasks]').textContent = '';
  current.modal.querySelector('[data-force]').hidden = true;
  current.modal.querySelector('[data-cancel]').hidden = true;
  current.modal.querySelector('[data-phase]').textContent = message;
  current.modal.querySelector('[data-note]').textContent = success
    ? 'Связь с панелью восстановлена.'
    : '';
  const button = current.modal.querySelector('[data-finish]');
  if (success && !login && current.operation.kind === 'restart') {
    button.hidden = true;
    setTimeout(() => current.modal.remove(), 1000);
    return;
  }
  button.hidden = false;
  button.textContent = login ? 'Войти в панель' : (success ? 'Открыть панель' : 'Закрыть');
  button.onclick = () => {
    current.modal.remove();
    if (success || login) location.reload();
  };
  button.focus();
}

function sameVersion(a, b) {
  const normalize = value => String(value || '').replace(/^v/i, '').split('.').map(Number).concat([0, 0]).slice(0, 3).join('.');
  return !!a && !!b && normalize(a) === normalize(b);
}

async function poll(current) {
  if (active !== current) return;
  const operation = current.operation;
  try {
    let panel;
    try { panel = await read('/api/system/maintenance'); }
    catch (error) {
      // При откате старая версия может ещё не иметь нового endpoint.
      if (error.status !== 404) throw error;
      panel = await read('/api/ping');
    }
    if (active !== current) return;
    const changed = !!panel.instance_id && panel.instance_id !== operation.preview.instance_id;
    if (panel.tasks) operation.preview.tasks = panel.tasks;
    if (changed) {
      operation.stage = 'executing';
      operation.executingAt ||= Date.now();
      renderWait();
    }
    if (!changed && applyPreparation(current, panel.maintenance)) {
      if (active === current) current.pollTimer = setTimeout(() => poll(current), 1500);
      return;
    }
    if (operation.kind === 'restart') {
      if (changed) {
        finish('Панель перезапущена.', { success: true });
        return;
      }
      setPhase(operation.accepted ? 'Перезапуск запрошен. Ожидаем запуска панели…' : 'Проверяем, был ли запущен перезапуск…');
    } else {
      const state = await read('/api/update/state');
      if (active !== current) return;
      window.dispatchEvent(new CustomEvent('bot4vps:update-state', { detail: state }));
      if (BUSY.includes(state.status)) operation.seenBusy = true;
      if (state.status === 'failed' && (operation.seenBusy || changed)) {
        finish(`Операция завершилась с ошибкой: ${state.last_error || 'причина не указана'}`);
        return;
      }
      if (state.status === 'idle' && (changed || operation.seenBusy)
          && sameVersion(state.current_version, operation.target)
          && sameVersion(panel.version, operation.target)) {
        finish(operation.kind === 'rollback' ? 'Откат завершён. Панель готова.' : 'Обновление установлено. Панель готова.', { success: true });
        return;
      }
      const phases = {
        downloading: 'Загружаем файлы версии…',
        installing: 'Устанавливаем обновление. Затем панель будет перезапущена…',
        rolling_back: 'Устанавливаем выбранную версию. Затем панель будет перезапущена…',
      };
      setPhase(phases[state.status] || 'Проверяем результат операции…');
    }
    remember(operation);
  } catch (error) {
    if (active !== current) return;
    if (error.status === 401 || error.status === 403) {
      finish('Панель отвечает, но для проверки результата требуется повторный вход.', { login: true });
      return;
    }
    setPhase(operation.stage === 'waiting' || operation.stage === 'starting'
      ? 'Связь с панелью потеряна. Проверяем состояние подготовки…'
      : 'Панель временно недоступна. Ожидаем восстановления связи…');
    // Сеть недоступна — неизвестно, на каком именно этапе остановка/запуск.
    current.modal.querySelector('[data-note]').textContent =
      'Проверяем связь автоматически. Подготовка и запущенная операция продолжаются на сервере.';
  }
  if (active === current) {
    renderWait();
    current.pollTimer = setTimeout(() => poll(current), 1500);
  }
}

function startProgress(operation) {
  const current = { operation, modal: createProgress(operation), pollTimer: null, clockTimer: null };
  active = current;
  current.modal.querySelector('[data-force]').onclick = () => preparationControl(current, 'force');
  current.modal.querySelector('[data-cancel]').onclick = () => preparationControl(current, 'cancel');
  remember(operation);
  renderWait();
  current.clockTimer = setInterval(renderWait, 1000);
  return current;
}

export async function runPanelMaintenance({ kind, preview, target }) {
  if (active) return;
  const operation = {
    id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    kind, preview, target, started: Date.now(), stage: 'starting', accepted: false, seenBusy: false,
  };
  const current = startProgress(operation);
  try {
    const result = await post('/api/system/maintenance/begin', { id: operation.id, kind, target });
    if (result.ok === false) throw new Error(result.error || result.message || 'Не удалось запустить операцию');
    applyPreparation(current, result.maintenance);
  } catch (error) {
    const uncertain = error.name === 'AbortError' || error instanceof TypeError
      || [408, 502, 503, 504].includes(error.status);
    if (!uncertain) {
      finish(`Не удалось запустить операцию: ${error.message}`);
      return;
    }
    // Разрыв ответа не доказывает отказ: POST мог успеть запустить restart.
    setPhase('Ответ на запрос не получен. Проверяем связь и результат операции…');
  }
  if (active === current) poll(current);
}

// Обновление вкладки во время ожидания не теряет открытое окно операции.
try {
  const pending = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
  if (pending && TITLES[pending.kind] && pending.preview?.instance_id
      && Array.isArray(pending.preview.tasks?.running) && Number.isFinite(pending.started)
      && Date.now() - pending.started < 24 * 60 * 60 * 1000) {
    const current = startProgress(pending);
    poll(current);
  } else if (pending) forget();
} catch { forget(); }
