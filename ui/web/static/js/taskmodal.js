// Единые окна задач и плашки свёрнутых окон в шапке панели.
import { j, esc } from './api.js';
import { toast, confirmAction } from './ui.js';
import { TaskLogBuffer, taskDuration } from './tasklog.js';

const watchers = new Map();
const DOCK_KEY = 'bot4vps:background-task-windows';
let foreground = null;
let clockTimer = null;
const STATUS_LABELS = {
  queued: 'В очереди', running: 'Выполняется', success: 'Выполнено',
  success_warn: 'Выполнено с предупреждениями', failed: 'Ошибка', cancelled: 'Отменена',
};

/** opts: {taskId, title?, taskName?, serverName?, cancellable?, onTasks?(),
 * onDone?(t), onClose?(t), renderResult?(t, element), onHelp?(), notifyCompletion?}. */
export function openTaskModal(opts) {
  const taskId = opts?.taskId;
  if (!taskId) return;
  const watch = watchers.get(taskId) || startWatcher(taskId, opts);
  watch.opts = { ...watch.opts, ...opts };
  if (foreground && foreground !== watch) {
    if (foreground.done) dispose(foreground); else background(foreground);
  }
  foreground = watch;
  watch.background = false;
  if (!watch.modal) createModal(watch);
  if (!watch.modal.isConnected) document.body.insertBefore(watch.modal, document.getElementById('confirm-modal'));
  if (watch.task) renderTask(watch);
  updateDock(watch);
  watch.modal.querySelector(watch.done ? '#task-progress-close' : '#task-progress-bg').focus();
  tick(watch);
}

function createModal(watch) {
  const opts = watch.opts;
  const el = watch.modal = document.createElement('div');
  el.className = 'modal-bg open'; el.id = 'task-progress-modal';
  el.innerHTML = `
  <div class="modal" style="width:min(680px,100%)" role="dialog" aria-modal="true" aria-labelledby="task-progress-title">
    <div class="section-head" style="margin-bottom:.6rem">
      <h3 id="task-progress-title" style="margin:0">${esc(opts.title || opts.taskName || watch.task?.name || 'Задача')}</h3>
      <button type="button" class="secondary" id="task-progress-tasks" style="padding:.2rem .55rem;font-size:.78rem">Перейти в меню задач</button>
    </div>
    <div class="tabs-hint" id="task-progress-steptitle" style="margin:0 0 .6rem">Ожидание очереди…</div>
    <div id="task-progress-log">
      <div class="tasklog-head" id="task-progress-head"></div>
      <p class="hint hidden" id="task-progress-truncated">Часть вывода недоступна по лимиту журнала.</p>
      <div class="logbox" style="max-height:40vh">Ожидание вывода…</div>
    </div>
    <div class="err-hint" id="task-progress-warn" role="status" style="white-space:pre-wrap;color:var(--err);font-size:.78rem"></div>
    <div id="task-progress-result" class="hidden"></div>
    <div class="actions" style="margin-top:.8rem;justify-content:space-between">
      <button type="button" class="secondary" id="task-progress-bg" title="Задача продолжится в фоне; окно можно вернуть из шапки панели">Свернуть в фон ↓</button>
      ${opts.onHelp ? '<button type="button" class="secondary faq-help-link" id="task-progress-help">ⓘ О задачах</button>' : ''}
      ${opts.cancellable ? '<button type="button" class="danger" id="task-progress-cancel" style="margin-left:auto">Отменить задачу</button>' : ''}
      <button type="button" id="task-progress-close" class="hidden" style="margin-left:auto">Закрыть</button>
    </div>
  </div>`;
  const close = () => { if (watch.done) dispose(watch); else background(watch); };
  el.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  });
  el.querySelector('#task-progress-bg').onclick = close;
  el.querySelector('#task-progress-close').onclick = close;
  el.querySelector('#task-progress-tasks').onclick = () => {
    close(); (watch.opts.onTasks || (() => window.b4vNav?.('queues')))();
  };
  const cancelBtn = el.querySelector('#task-progress-cancel');
  if (cancelBtn) cancelBtn.onclick = () => cancelTask(watch);
  const helpBtn = el.querySelector('#task-progress-help');
  if (helpBtn) helpBtn.onclick = () => watch.opts.onHelp();
  const box = el.querySelector('.logbox');
  box.__stick = true;
  box.onscroll = () => { box.__stick = box.scrollHeight - box.scrollTop - box.clientHeight < 4; };
  updateCancelButton(watch);
}

function startWatcher(taskId, opts) {
  const watch = { taskId, opts, modal: null, busy: false, done: false, background: true,
    cancelling: false, cancelRequested: false, wasActive: false, log: new TaskLogBuffer() };
  watchers.set(taskId, watch);
  watch.timer = setInterval(() => tick(watch), 1500);
  if (!clockTimer) clockTimer = setInterval(updateClock, 1000);
  return watch;
}

function background(watch) {
  watch.modal?.remove(); watch.background = true;
  if (foreground === watch) foreground = null;
  updateDock(watch);
}

function reportClose(watch) {
  if (watch.closeReported) return;
  watch.closeReported = true;
  try {
    watch.opts.onClose?.(watch.task)?.catch(error => toast(error.message || 'Не удалось обновить страницу', false));
  } catch (error) { toast(error.message || 'Не удалось обновить страницу', false); }
}

function dispose(watch) {
  if (!watchers.has(watch.taskId)) return;
  clearInterval(watch.timer); watch.modal?.remove(); watch.pill?.remove();
  watchers.delete(watch.taskId);
  if (foreground === watch) foreground = null;
  reportClose(watch); refreshDock(); updateClock();
}

function elapsed(watch) {
  if (!watch.task || watch.task.status === 'queued') return 0;
  return (watch.baseElapsed ?? (Number(watch.task?.elapsed_seconds ?? watch.task?.duration_seconds) || 0))
    + (!watch.done && watch.task.status === 'running' && watch.receivedAt
      ? Math.max(0, (Date.now() - watch.receivedAt) / 1000) : 0);
}

function timeLabel(watch) {
  return !watch.task || watch.task.status === 'queued' ? 'Ожидает очереди' : taskDuration(elapsed(watch));
}

function updateClock() {
  for (const watch of watchers.values()) {
    if (watch.parts) watch.parts.time.textContent = timeLabel(watch);
    if (watch.task && watch.modal) renderHeading(watch);
  }
  if (![...watchers.values()].some(watch => !watch.done) && clockTimer) {
    clearInterval(clockTimer); clockTimer = null;
  }
}

function refreshDock() {
  const dock = document.getElementById('task-dock');
  const entries = [...watchers.values()].filter(watch => watch.background);
  const priority = watch => watch.task?.status === 'running' ? 0 : watch.done ? 2 : 1;
  const visible = entries.slice().sort((a, b) => priority(a) - priority(b)
    || (a.done && b.done
      ? (b.task?.finished_at || '').localeCompare(a.task?.finished_at || '')
      : (a.task?.created_at || '').localeCompare(b.task?.created_at || ''))).slice(0, 3);
  for (const watch of watchers.values()) {
    if (!watch.pill) continue;
    const index = visible.indexOf(watch);
    watch.pill.hidden = index === -1;
    watch.pill.style.order = String(index);
  }
  if (dock) dock.hidden = entries.length === 0;
  // Метаданные для восстановления после обновления страницы, без лога и секретов.
  try {
    if (entries.length) sessionStorage.setItem(DOCK_KEY, JSON.stringify(entries.map(watch => ({
      taskId: watch.taskId, title: watch.opts.title, taskName: watch.opts.taskName || watch.task?.name,
      serverName: watch.opts.serverName || watch.task?.server_name,
    }))));
    else sessionStorage.removeItem(DOCK_KEY);
  } catch { /* хранилище необязательно */ }
}

function updateDock(watch) {
  const dock = document.getElementById('task-dock');
  if (!dock) return;
  if (!watch.pill && watch.background) {
    const pill = watch.pill = document.createElement('button');
    pill.type = 'button'; pill.className = 'task-dock-item';
    pill.dataset.taskId = watch.taskId;
    const name = document.createElement('span'); name.className = 'task-dock-name';
    const server = document.createElement('span'); server.className = 'task-dock-server';
    const time = document.createElement('span'); time.className = 'task-dock-time';
    pill.append(name, server, time); dock.appendChild(pill);
    watch.parts = { name, server, time };
    pill.onclick = () => openTaskModal({ taskId: watch.taskId });
  }
  if (watch.pill) {
    watch.pill.hidden = !watch.background;
    const name = watch.opts.taskName || watch.task?.name || watch.opts.title || 'Задача';
    const server = watch.opts.serverName || watch.task?.server_name || 'Сервер';
    const status = watch.task?.status || 'queued';
    watch.parts.name.textContent = name; watch.parts.server.textContent = server;
    watch.parts.time.textContent = timeLabel(watch);
    watch.pill.dataset.status = status;
    watch.pill.title = `${name} · ${server} · ${STATUS_LABELS[status] || status} — открыть лог`;
    watch.pill.setAttribute('aria-label', watch.pill.title);
  }
  refreshDock();
}

export async function resumeBackgroundTasks() {
  let saved = [];
  try { saved = JSON.parse(sessionStorage.getItem(DOCK_KEY) || '[]'); } catch { /* необязательно */ }
  for (const opts of Array.isArray(saved) ? saved.slice(0, 100) : []) {
    if (!opts?.taskId || watchers.has(opts.taskId)) continue;
    const watch = startWatcher(opts.taskId, { ...opts, notifyCompletion: false, resumed: true });
    updateDock(watch); tick(watch);
  }
  let r;
  try { r = await j('/api/queues'); } catch { return; }
  for (const row of r?.queues || []) {
    for (const t of [row.running, ...(row.queue || [])]) {
      if (!t?.id || watchers.has(t.id)) continue;
      const opts = { taskId: t.id, title: `${t.name || 'Задача'} · ${row.server_name || ''}`,
        taskName: t.name, serverName: row.server_name, resumed: true };
      const watch = startWatcher(t.id, opts); watch.task = t; watch.wasActive = true;
      updateDock(watch); tick(watch);
    }
  }
}

async function cancelTask(watch) {
  if (watch.done || watch.cancelling || watch.cancelRequested) return;
  watch.cancelling = true; updateCancelButton(watch);
  try {
    const approved = await confirmAction({
      title: 'Отменить эту задачу?',
      message: 'Задача в очереди не будет запущена. Для уже выполняющейся задачи Bot4VPS перестанет её ждать, но команда на сервере может завершиться сама. Уже сделанные изменения не откатываются. Остальные задачи продолжат работу.',
      confirmText: 'Отменить',
    });
    if (!approved || watch.done) return;
    await j(`/api/tasks/${encodeURIComponent(watch.taskId)}/cancel`, { method: 'POST' });
    watch.cancelRequested = true;
    if (!watch.done) toast('Запрошена отмена задачи', true);
    await tick(watch);
  } catch (error) { if (!watch.done) toast(error.message || 'Не удалось отменить задачу', false); }
  finally { watch.cancelling = false; updateCancelButton(watch); }
}

function updateCancelButton(watch) {
  const button = watch.modal?.querySelector('#task-progress-cancel');
  if (!button) return;
  button.classList.toggle('hidden', watch.done);
  button.disabled = watch.done || watch.cancelling || watch.cancelRequested;
  button.textContent = watch.cancelRequested ? 'Отмена запрошена…' : 'Отменить задачу';
}

function renderHeading(watch) {
  const t = watch.task;
  watch.modal.querySelector('#task-progress-title').textContent = watch.opts.title
    || `${watch.opts.taskName || t.name || 'Задача'}${t.server_name ? ` — ${t.server_name}` : ''}`;
  watch.modal.querySelector('#task-progress-head').textContent =
    `${t.emoji || ''} ${t.name || ''} · ${t.status === 'queued'
      ? timeLabel(watch) : `${STATUS_LABELS[t.status] || t.status || ''} · ${timeLabel(watch)}`}`;
}

function renderTask(watch) {
  const el = watch.modal, t = watch.task;
  if (!el || !t) return;
  renderHeading(watch);
  const box = el.querySelector('.logbox'), body = watch.log.html(t);
  const scrollTop = box.scrollTop, stick = box.__stick !== false;
  if (box.innerHTML !== body) box.innerHTML = body;
  box.scrollTop = stick ? box.scrollHeight : scrollTop;
  el.querySelector('#task-progress-truncated').classList.toggle('hidden', !watch.log.truncated);
  const step = el.querySelector('#task-progress-steptitle');
  const warn = el.querySelector('#task-progress-warn'); warn.textContent = '';
  if (!watch.done) {
    step.textContent = watch.cancelRequested ? 'Ожидание отмены…'
      : t.status === 'queued' ? 'В очереди — ожидание завершения предыдущих задач'
      : 'Выполняется — лог обновляется автоматически';
  } else {
    el.querySelector('#task-progress-bg').classList.add('hidden');
    const closeBtn = el.querySelector('#task-progress-close'); closeBtn.classList.remove('hidden');
    if (el.isConnected && el.contains(document.activeElement)) closeBtn.focus();
    step.textContent = t.status === 'cancelled' ? 'Задача отменена'
      : t.status === 'success_warn' ? 'Выполнено с предупреждениями'
      : t.success ? watch.opts.doneLabel || 'Готово' : 'Не удалось';
    if (!t.success && t.status !== 'cancelled') warn.textContent = t.result?.error || t.error || 'Задача завершена с ошибкой';
    if (watch.opts.renderResult && !watch.resultRendered) {
      watch.resultRendered = true;
      const result = el.querySelector('#task-progress-result'); result.classList.remove('hidden');
      Promise.resolve().then(() => watch.opts.renderResult(t, result)).catch(() => {
        result.textContent = 'Не удалось загрузить результат. Подробности доступны в карточке сервиса.';
      });
    }
  }
  updateCancelButton(watch);
}

async function tick(watch) {
  if (watch.busy || watch.done || !watchers.has(watch.taskId)) return;
  watch.busy = true;
  let t;
  try { t = await j(`/api/tasks/${encodeURIComponent(watch.taskId)}?full_output=true`); }
  catch (error) {
    if (error.status === 404 && watch.background) { dispose(watch); return; }
    if (watch.modal) watch.modal.querySelector('#task-progress-warn').textContent = 'Не удалось обновить лог. Повторяем подключение…';
    return;
  } finally { watch.busy = false; }
  if (!watchers.has(watch.taskId)) return;
  const previousElapsed = elapsed(watch);
  const serverElapsed = Number(t.elapsed_seconds ?? t.duration_seconds);
  const justStarted = watch.task?.status === 'queued' && t.status === 'running';
  watch.baseElapsed = justStarted ? (Number.isFinite(serverElapsed) ? serverElapsed : 0)
    : t.is_done ? (Number.isFinite(serverElapsed) ? serverElapsed : previousElapsed)
    : Math.max(previousElapsed, Number.isFinite(serverElapsed) ? serverElapsed : 0);
  watch.task = t; watch.receivedAt = Date.now(); watch.log.update(t);
  watch.wasActive ||= !t.is_done;
  if (t.is_done) {
    watch.done = true; clearInterval(watch.timer);
    const finished = [...watchers.values()].filter(entry => entry.done && entry.background && entry !== watch);
    for (const old of finished.slice(0, Math.max(0, finished.length - 19))) dispose(old);
  }
  renderTask(watch); updateDock(watch); updateClock();
  if (!t.is_done) return;
  const opts = watch.opts;
  if (opts.notifyCompletion !== false || watch.wasActive) {
    if (t.status === 'cancelled') toast('Задача отменена', true);
    else if (t.status === 'success_warn') toast(`${opts.title || 'Задача'} — выполнено с предупреждениями`, true);
    else if (t.success) toast(opts.doneLabel || 'Задача выполнена', true);
    else toast(`Задача завершилась с ошибкой${t.error ? `: ${t.error}` : ''}`, false);
  }
  Promise.resolve().then(() => opts.onDone?.(t)).catch(error => {
    toast(error.message || 'Не удалось обновить состояние сервиса', false);
  });
  if (watch.background) {
    if (t.status === 'failed') reportClose(watch);
    else dispose(watch);
  }
  if (opts.resumed) document.dispatchEvent(new CustomEvent('bot4vps:task-done', { detail: t }));
}
