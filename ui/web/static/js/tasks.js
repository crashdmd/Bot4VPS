// Общие операции с задачами Task Manager — не привязаны к конкретному сервису.
// Используются страницей «Очереди» (servers.js) и страницами сервисов.
// Модалка #task-log-modal общая: задача любого сервиса выглядит одинаково.
import { j, esc } from './api.js';
import { toast } from './ui.js';
import { ansiToHtml } from './ansi.js';

let taskLogCtx = null;   // id задачи в открытой модалке
let taskLogTimer = null; // интервал автодобновления живой задачи

const LOG_POLL_MS = 1500;

export function openTaskLog(taskId) {
  taskLogCtx = taskId;
  const title = document.getElementById('task-log-title');
  const body = document.getElementById('task-log-body');
  if (title) title.textContent = 'Лог задачи';
  if (body) {
    body.textContent = 'Загрузка…';
    // Новое открытие — прилипание к низу включено; уход вверх отключает
    // (см. слушатель scroll ниже).
    body.__stick = true;
  }
  document.getElementById('task-log-modal')?.classList.add('open');
  return refreshTaskLog();
}

// Автообновление: живая задача обновляется сама (как окно установки);
// завершённая — последний fetch показывает финальный лог, поллинг стоп.
export async function refreshTaskLog() {
  if (!taskLogCtx) return;
  const bodyEl = document.getElementById('task-log-body');
  if (!bodyEl) return;
  try {
    // Ответ плоский (тот же эндпоинт читает live-вывод задачи):
    // поля Task + emoji/duration/status/is_done.
    const t = await j(`/api/tasks/${encodeURIComponent(taskLogCtx)}`);
    const title = document.getElementById('task-log-title');
    if (title) title.textContent = `Лог — ${t.name || t.id}`;
    const lines = Array.isArray(t.output_lines) ? [...t.output_lines] : [];
    const resultOut = t.result ? (t.result.output || '') : '';
    const resultErr = t.result ? (t.result.error || '') : '';
    if (resultOut) {
      resultOut.split('\n').forEach(line => {
        if (!lines.includes(line)) lines.push(line);
      });
    }
    const fallbackError = t.error || resultErr;
    if (fallbackError && !lines.includes(fallbackError)) lines.push(fallbackError);
    const allText = lines.join('\n');
    bodyEl.innerHTML = allText
      ? allText.split('\n').map(ansiToHtml).join('\n')
      : esc('(лог пуст)');
    // Stick-to-bottom: прилипает к новым строкам, только если пользователь
    // сам не ушёл вверх; вернулся к низу — прилипание снова включается.
    if (bodyEl.__stick !== false) bodyEl.scrollTop = bodyEl.scrollHeight;
    if (t.is_done || t.status === 'done' || t.status === 'failed'
        || t.status === 'error' || t.status === 'cancelled') {
      stopTaskLogPolling();
    } else {
      startTaskLogPolling();
    }
  } catch (e) {
    bodyEl.textContent = e.message || 'Не удалось получить лог';
  }
}

function startTaskLogPolling() {
  if (taskLogTimer) return;
  taskLogTimer = setInterval(() => {
    // модалку закрыли руками — стоп (closeTaskLog тоже чистит)
    if (!document.getElementById('task-log-modal')?.classList.contains('open')) {
      stopTaskLogPolling();
      return;
    }
    refreshTaskLog();
  }, LOG_POLL_MS);
}

function stopTaskLogPolling() {
  if (taskLogTimer) { clearInterval(taskLogTimer); taskLogTimer = null; }
}

export function closeTaskLog() {
  taskLogCtx = null;
  stopTaskLogPolling();
  document.getElementById('task-log-modal')?.classList.remove('open');
}

// Отмена конкретной задачи (в отличие от очистки всей очереди).
// Внимание: для уже выполняющейся SSH-операции отменяется ожидание задачи —
// удалённая команда может дойти до конца. Текст подтверждения в UI об этом
// предупреждает (§27).
export async function cancelTaskAPI(taskId) {
  try {
    await j(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' });
    toast('Задача отменена', true);
    return true;
  } catch (e) {
    toast(e.message, false);
    return false;
  }
}

export function bindTasksUI() {
  document.getElementById('task-log-close')?.addEventListener('click', closeTaskLog);
  document.getElementById('task-log-x')?.addEventListener('click', closeTaskLog);
  // Пользователь уехал вверх — не дёргать прокрутку под ним; вернулся к
  // низу — снова прилипать к новым строкам.
  document.getElementById('task-log-body')?.addEventListener('scroll', e => {
    const el = e.target;
    el.__stick = el.scrollHeight - el.scrollTop - el.clientHeight < 4;
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (document.getElementById('task-log-modal')?.classList.contains('open')) {
      closeTaskLog();
    }
  });
}
