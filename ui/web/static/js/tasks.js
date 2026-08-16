// Общие операции с задачами Task Manager — не привязаны к конкретному сервису.
// Используются страницей «Очереди» (servers.js) и страницами сервисов.
// Модалка #task-log-modal общая: задача любого сервиса выглядит одинаково.
import { j, esc } from './api.js';
import { toast } from './ui.js';
import { ansiToHtml } from './ansi.js';

let taskLogCtx = null;   // id задачи в открытой модалке

export function openTaskLog(taskId) {
  taskLogCtx = taskId;
  const title = document.getElementById('task-log-title');
  const body = document.getElementById('task-log-body');
  if (title) title.textContent = '📄 Лог задачи';
  if (body) body.textContent = 'Загрузка…';
  document.getElementById('task-log-modal')?.classList.add('open');
  return refreshTaskLog();
}

export async function refreshTaskLog() {
  if (!taskLogCtx) return;
  const bodyEl = document.getElementById('task-log-body');
  if (!bodyEl) return;
  try {
    // Ответ плоский (тот же эндпоинт читает live-вывод задачи):
    // поля Task + emoji/duration/status/is_done.
    const t = await j(`/api/tasks/${encodeURIComponent(taskLogCtx)}`);
    const title = document.getElementById('task-log-title');
    if (title) {
      title.textContent =
        `${t.emoji || '📄'} ${t.name || t.id} · ${t.status || ''} · ${t.duration || ''}`;
    }
    const lines = Array.isArray(t.output_lines) ? t.output_lines : [];
    const resultOut = t.result ? (t.result.output || '') : '';
    const resultErr = t.result ? (t.result.error || '') : '';
    const allText = lines.join('\n') || resultOut || t.error || resultErr;
    bodyEl.innerHTML = allText
      ? allText.split('\n').map(ansiToHtml).join('\n')
      : esc('(лог пуст)');
    bodyEl.scrollTop = bodyEl.scrollHeight;
  } catch (e) {
    bodyEl.textContent = e.message || 'Не удалось получить лог';
  }
}

export function closeTaskLog() {
  taskLogCtx = null;
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
  document.getElementById('task-log-refresh')?.addEventListener('click', refreshTaskLog);
  document.getElementById('task-log-close')?.addEventListener('click', closeTaskLog);
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (document.getElementById('task-log-modal')?.classList.contains('open')) {
      closeTaskLog();
    }
  });
}
