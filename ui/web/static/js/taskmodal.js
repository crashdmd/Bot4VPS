// Общая модалка живого прогресса задачи (паттерн окна установки 3x-ui):
// шапка с именем/статусом/длительностью, лог со stick-to-bottom, кнопка
// «в фон ↓» (свернуть — задача продолжается, тост по завершении) и
// «Закрыть» в терминальном состоянии. Используют WG и Docker.
//
// Статусы task_manager: queued/running/success/success_warn/failed/
// cancelled (поля ответа: emoji/duration/is_done/success).
//
// Фон — как у визарда 3x-ui: любое закрытие («в фон ↓», Escape, смена
// задачи) снимает только окно, а поллинг и колбэки живут, пока задача не
// завершится. Финал в фоне = тост + onDone/onClose — страница обновляется
// и без открытой модалки.

import { j, esc } from './api.js';
import { toast } from './ui.js';
import { ansiToHtml } from './ansi.js';

const timers = {};   // taskId -> setInterval
const onDone = {};   // taskId -> callback(t)
const modals = {};   // taskId -> элемент модалки (нет/отсоединён → фон)

/** Открыть модалку прогресса задачи.
 *  opts: {title, taskId, doneLabel?, onDone?(t), onClose?()}
 *  doneLabel — текст успеха (по умолчанию «Задача выполнена»). */
export function openTaskModal(opts) {
  const { title, taskId } = opts || {};
  if (!taskId) return;
  let bg = document.getElementById('task-progress-modal');
  if (bg) bg.remove();  // предыдущая модалка: её задача уходит в фон (см. tick)
  bg = document.createElement('div');
  bg.className = 'modal-bg open';
  bg.id = 'task-progress-modal';
  bg.innerHTML = `
  <div class="modal" style="width:min(680px,100%)">
    <div class="section-head" style="margin-bottom:.6rem">
      <h3 style="margin:0">${esc(title || 'Задача')}</h3>
      <button type="button" id="task-progress-bg" title="Свернуть окно: задача продолжается в фоне, уведомлю по завершении"
              style="padding:.2rem .55rem;font-size:.78rem">в фон ↓</button>
    </div>
    <div class="tabs-hint" id="task-progress-steptitle" style="margin:0 0 .6rem">Выполняется — это может занять несколько минут</div>
    <div id="task-progress-log"><div class="empty">Ожидание очереди…</div></div>
    <div class="err-hint" id="task-progress-warn" style="white-space:pre-wrap;color:var(--err);font-size:.78rem"></div>
    <div class="actions" style="margin-top:.8rem;justify-content:space-between" id="task-progress-actions"></div>
  </div>`;
  document.body.appendChild(bg);
  modals[taskId] = bg;
  // Клик мимо окна НЕ закрывает: случайный клик по затемнению не должен
  // терять прогресс. Закрытие — кнопками или Escape.
  bg.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); closeTaskModal(taskId); }
  });
  const bgBtn = bg.querySelector('#task-progress-bg');
  bgBtn.onclick = () => closeTaskModal(taskId);
  onDone[taskId] = opts.onDone || null;
  stopTimer(taskId);  // вдруг эта задача уже подхвачена резюмом после перезагрузки
  timers[taskId] = setInterval(() => tick(taskId, opts), 1500);
  tick(taskId, opts);
}

/** Подхватить незавершённые задачи после (пере)загрузки страницы: рефреш
 *  убивает весь JS, включая фоновый поллинг модалки. /api/queues отдаёт
 *  running+queued по всем серверам — на каждую вешаем тихий фоновый ватчер:
 *  финал придёт тостом, а активная страница сервиса обновится событием
 *  bot4vps:task-done (у резюма нет своих onDone). */
export async function resumeBackgroundTasks() {
  let r;
  try { r = await j('/api/queues'); }
  catch { return; }
  for (const row of r?.queues || []) {
    for (const t of [row.running, ...(row.queue || [])]) {
      if (!t || !t.id || timers[t.id]) continue;
      const label = `${t.name || 'Задача'}${row.server_name ? ` · ${row.server_name}` : ''}`;
      const opts = { title: label, taskId: t.id, doneLabel: `${label} — выполнено`, resumed: true };
      timers[t.id] = setInterval(() => tick(t.id, opts), 1500);
    }
  }
}

/** Закрыть модалку задачи. Любой способ («в фон ↓», Escape) снимает только
 *  окно: задача продолжает поллиться, финал придёт тостом (паттерн 3x-ui). */
function closeTaskModal(taskId) {
  const el = modals[taskId];
  delete modals[taskId];
  el?.remove();
}

function stopTimer(taskId) {
  if (timers[taskId]) { clearInterval(timers[taskId]); delete timers[taskId]; }
}

/** Финал задачи: общая часть для обоих путей — почистить реестры,
 *  дернуть onDone (обновление статуса) и тост успеха/ошибки. */
function finishTask(taskId, t, opts) {
  stopTimer(taskId);
  delete modals[taskId];
  const doneCb = onDone[taskId];
  delete onDone[taskId];
  if (t.success) toast(opts.doneLabel || 'Задача выполнена', true);
  else toast(`Задача завершилась с ошибкой${t.error ? `: ${t.error}` : ''}`, false);
  return doneCb;
}

async function tick(taskId, opts) {
  let t;
  try { t = await j('/api/tasks/' + encodeURIComponent(taskId)); }
  catch { return; }
  const el = modals[taskId];
  // Окна нет (свернули в фон / закрыли / открыли задачу поновее) — тихо
  // ждём финала: тост + колбэки, без DOM.
  if (!el || !el.isConnected) {
    if (!t.is_done) return;
    const doneCb = finishTask(taskId, t, opts);
    doneCb?.(t);
    opts.onClose?.(t);
    // Подхваченные после перезагрузки задачи: активная страница сервиса
    // слушает событие и обновляет список (своих onDone у резюма нет).
    if (opts.resumed) document.dispatchEvent(new CustomEvent('bot4vps:task-done', { detail: t }));
    return;
  }
  const log = el.querySelector('#task-progress-log');
  const head = `${esc(t.emoji || '')} ${esc(t.name || '')} · ${esc(t.status || '')} · ${esc(t.duration || '')}`;
  const lines = t.output_lines || [];
  // При провале дописываем вывод команды (result.output — stdout/stderr
  // с сервера): в output_lines только наши emit-строки, без них причина
  // ошибки в окне не видна («завершилась с ошибкой (код 1)» и всё).
  let body;
  if (lines.length) body = lines.map(ansiToHtml).join('\n');
  else body = ansiToHtml(t.result?.output || t.result?.error || t.error || '(нет вывода)');
  if (!t.success && t.result?.output
      && String(t.result.output).trim() !== lines.join('\n').trim()) {
    body += `\n${'─'.repeat(36)}\n${ansiToHtml(String(t.result.output).trim())}`;
  }
  log.innerHTML = `<div class="tasklog-head">${head}</div>
    <div class="logbox" style="max-height:40vh">${body}</div>`;
  // Stick-to-bottom: прилипает к низу, пока пользователь не уехал вверх;
  // вернулся к низу — прилипание снова включено.
  const box = log.querySelector('.logbox');
  if (box) {
    const stick = box.__stick !== false;
    box.onscroll = () => {
      box.__stick = box.scrollHeight - box.scrollTop - box.clientHeight < 4;
    };
    if (stick) box.scrollTop = box.scrollHeight;
  }
  if (!t.is_done) return;
  const doneCb = finishTask(taskId, t, opts);
  el.querySelector('#task-progress-bg')?.classList.add('hidden');
  const steptitle = el.querySelector('#task-progress-steptitle');
  const warn = el.querySelector('#task-progress-warn');
  const actions = el.querySelector('#task-progress-actions');
  if (t.success) {
    if (steptitle) steptitle.textContent = opts.doneLabel || 'Готово';
    if (warn) warn.textContent = '';
  } else {
    if (steptitle) steptitle.textContent = 'Не удалось';
    if (warn) warn.textContent = t.result?.error || t.error || 'Задача завершена с ошибкой';
  }
  if (actions) actions.innerHTML =
    '<button type="button" id="task-progress-close" style="margin-left:auto">Закрыть</button>';
  el.querySelector('#task-progress-close')?.addEventListener('click', () => {
    el.remove();
    opts.onClose?.(t);
  });
  doneCb?.(t);
}
