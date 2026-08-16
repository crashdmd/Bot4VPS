// Редактор текстовых файлов (скрипты, Compose-проекты).
//
// Использует CodeMirror 5, если он положен в /static/vendor/codemirror/
// (см. README.md в этом каталоге). Если файлов нет — работает встроенный
// редактор с нумерацией строк: та же функциональность, без подсветки.
// Так панель не зависит от интернета: остальной UI тоже полностью локальный.
import { j, esc } from './api.js';
import { toast, confirmAction } from './ui.js';

let ctx = null;      // {root, project, name, original}
let cm = null;       // экземпляр CodeMirror, если доступен
let onSaved = null;  // колбэк после успешного сохранения
let editorOptions = { discardOnCancel: false, shortcutSave: true };
let editorUiBound = false;

const hasCodeMirror = () => typeof window.CodeMirror === 'function';

// Режим подсветки по имени файла.
function modeFor(name) {
  const n = (name || '').toLowerCase();
  if (n.endsWith('.sh')) return 'shell';
  if (n.endsWith('.yml') || n.endsWith('.yaml')) return 'yaml';
  if (n.endsWith('.json')) return 'application/json';
  return null;
}

// ---------------- нумерация строк для fallback ----------------

function renderGutter() {
  const area = document.getElementById('editor-area');
  const gutter = document.getElementById('editor-gutter');
  if (!area || !gutter) return;
  const lines = area.value.split('\n').length;
  gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join('\n');
  gutter.scrollTop = area.scrollTop;
}

function bindFallbackEditor() {
  const area = document.getElementById('editor-area');
  if (!area || area.dataset.bound === '1') return;
  area.dataset.bound = '1';
  area.addEventListener('input', renderGutter);
  area.addEventListener('scroll', () => {
    const g = document.getElementById('editor-gutter');
    if (g) g.scrollTop = area.scrollTop;
  });
  // Tab внутри textarea должен вставлять отступ, а не уводить фокус.
  area.addEventListener('keydown', e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = area.selectionStart, en = area.selectionEnd;
      area.value = area.value.slice(0, s) + '  ' + area.value.slice(en);
      area.selectionStart = area.selectionEnd = s + 2;
      renderGutter();
    }
  });
}

// ---------------- открытие / сохранение ----------------

function currentText() {
  return cm ? cm.getValue() : (document.getElementById('editor-area')?.value ?? '');
}

function setText(text, name) {
  const wrap = document.getElementById('editor-cm-wrap');
  const plain = document.getElementById('editor-plain');
  if (hasCodeMirror()) {
    plain?.classList.add('hidden');
    wrap?.classList.remove('hidden');
    if (cm) { cm.toTextArea?.(); cm = null; }
    wrap.innerHTML = '';
    const instance = window.CodeMirror(wrap, {
      value: text,
      mode: modeFor(name),
      lineNumbers: true,
      lineWrapping: false,
      indentUnit: 2,
      tabSize: 2,
      indentWithTabs: false,
      theme: 'material-darker',
      extraKeys: {
        'Ctrl-S': () => { if (editorOptions.shortcutSave) save(); },
        'Cmd-S': () => { if (editorOptions.shortcutSave) save(); },
      },
    });
    cm = instance;
    // CodeMirror должен обновиться после layout открытой модалки. Guard не даёт
    // отложенному refresh затронуть уже заменённый экземпляр при быстрой загрузке.
    requestAnimationFrame(() => {
      if (cm === instance) instance.refresh();
    });
  } else {
    wrap?.classList.add('hidden');
    plain?.classList.remove('hidden');
    const area = document.getElementById('editor-area');
    area.value = text;
    bindFallbackEditor();
    renderGutter();
  }
}

export async function openEditor(root, name, project = '', afterSave = null, options = {}) {
  editorOptions = {
    discardOnCancel: options.discardOnCancel === true,
    shortcutSave: options.shortcutSave !== false,
  };
  const openedCtx = { root, project, name, original: '' };
  ctx = openedCtx;
  onSaved = afterSave;
  const title = document.getElementById('editor-title');
  const warn = document.getElementById('editor-warn');
  const info = document.getElementById('editor-info');
  const shortcuts = document.getElementById('editor-shortcuts');
  if (title) title.textContent = '✏️ ' + (project ? `${project}/${name}` : name);
  if (warn) warn.textContent = '';
  if (info) {
    info.textContent = hasCodeMirror()
      ? '' : 'Подсветка синтаксиса недоступна (нет vendor/codemirror) — редактор работает без неё.';
  }
  if (shortcuts) {
    shortcuts.textContent = editorOptions.shortcutSave
      ? 'Ctrl+S — сохранить без закрытия, Esc — закрыть'
      : 'Изменения сохраняются только кнопкой «Сохранить»';
  }
  document.getElementById('editor-modal')?.classList.add('open');
  setText('Загрузка…', name);

  try {
    const qs = new URLSearchParams({ root, name });
    if (project) qs.set('project', project);
    const d = await j('/api/files/read?' + qs);
    if (ctx !== openedCtx) return;
    ctx.original = d.content || '';
    setText(ctx.original, name);
  } catch (e) {
    if (ctx !== openedCtx) return;
    setText('', name);
    if (warn) warn.textContent = e.message;
  }
}

// closeAfter=true — кнопка «Сохранить» (сохранил и вышел).
// closeAfter=false — Ctrl+S: сохраняем на месте, чтобы можно было писать дальше.
async function save(closeAfter = false) {
  if (!ctx) return;
  const warn = document.getElementById('editor-warn');
  const content = currentText();
  if (warn) warn.textContent = '';
  try {
    await j('/api/files/write', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        root: ctx.root, name: ctx.name, project: ctx.project, content,
      }),
    });
    ctx.original = content;
    const refresh = onSaved;
    toast('Файл сохранён', true);
    if (closeAfter) close(true);   // force: изменения уже записаны
    if (refresh) refresh();
  } catch (e) {
    // Ошибка валидации (битый YAML) приходит с бэка — показываем, не закрывая
    // редактор, чтобы правку можно было исправить.
    if (warn) warn.textContent = e.message;
    else toast(e.message, false);
  }
}

// closeAfter=true — кнопка «Сохранить» зовёт close(true) — там подтверждение не нужно.
async function close(force = false) {
  if (!force && !editorOptions.discardOnCancel && ctx && currentText() !== ctx.original) {
    if (!await confirmAction({
      title: 'Закрыть без сохранения?',
      message: 'Есть несохранённые изменения — они будут потеряны.',
      confirmText: 'Закрыть',
    })) return;
  }
  document.getElementById('editor-modal')?.classList.remove('open');
  if (cm) { cm = null; }
  ctx = null;
  onSaved = null;
  editorOptions = { discardOnCancel: false, shortcutSave: true };
}

export function bindEditorUI() {
  if (editorUiBound) return;
  editorUiBound = true;
  // Кнопка сохраняет и закрывает редактор.
  document.getElementById('editor-save')?.addEventListener('click', () => save(true));
  document.getElementById('editor-cancel')?.addEventListener('click', () => close());
  // Ctrl+S работает и в fallback-режиме (в CodeMirror — через extraKeys).
  document.addEventListener('keydown', e => {
    const open = document.getElementById('editor-modal')?.classList.contains('open');
    if (!open) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (editorOptions.shortcutSave) save();
    } else if (e.key === 'Escape') {
      close();
    }
  });
}
