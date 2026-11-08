// Операции с задачами из очередей и истории используют то же окно,
// что скрипты и установщики сервисов.
import { j } from './api.js';
import { toast, infoModal } from './ui.js';
import { openTaskModal } from './taskmodal.js?v=20260914-v3';

function openTaskHelp() {
  if (document.getElementById('confirm-modal')?.classList.contains('open')) return;
  void infoModal({
    title: 'Задачи и журнал',
    message: 'Журнал выполняющейся задачи обновляется автоматически. Свёрнутое окно можно вернуть из плашки в шапке панели. Отмена прекращает ожидание, но удалённая команда может завершиться сама; уже сделанные изменения не откатываются.',
    handbookAnchor: 'tasks',
  });
}

export function openTaskLog(taskId) {
  return openTaskModal({ taskId, cancellable: true, notifyCompletion: false, onHelp: openTaskHelp });
}

export async function cancelTaskAPI(taskId) {
  try {
    await j(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' });
    toast('Задача отменена', true);
    return true;
  } catch (e) { toast(e.message, false); return false; }
}
