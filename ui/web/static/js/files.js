// Раздел «Файлы»: scripts, keys и docker (библиотека Compose-проектов).
//
// scripts/keys — плоский список. docker — два уровня: сначала проекты
// (Compose-проект = каталог), затем файлы внутри выбранного, включая вложенные.
// Правка текстовых файлов — через модуль editor.js; keys не редактируются.
import { j, esc } from './api.js';
import { toast } from './ui.js';
import { openEditor } from './editor.js';

let fileRoot = 'scripts';
let dockerProject = '';   // выбранный Compose-проект (только для root=docker)

function fmtSize(n) {
  if (n == null) return '';
  if (n < 1024) return n + ' б';
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' КБ';
  return (n / (1024 * 1024)).toFixed(1) + ' МБ';
}

function iconFor(name) {
  const n = name.toLowerCase();
  if (fileRoot === 'keys') return '🔑';
  if (n.endsWith('.sh')) return '📜';
  if (n.endsWith('.yml') || n.endsWith('.yaml')) return '🧩';
  if (n === '.env' || n.endsWith('/.env')) return '⚙️';
  return '📄';
}

function updateChrome() {
  // Кнопка создания ключа — только на вкладке keys.
  const btnKey = document.getElementById('btn-create-key');
  if (btnKey) btnKey.style.display = fileRoot === 'keys' ? '' : 'none';
  // Создание скрипта — только на вкладке scripts.
  const btnScript = document.getElementById('btn-create-script');
  if (btnScript) btnScript.style.display = fileRoot === 'scripts' ? '' : 'none';
  // Загрузку Compose-проекта делает раздел Docker (там выбор имени и разбор
  // ZIP), поэтому на этой вкладке кнопку скрываем.
  const upload = document.getElementById('upload-label');
  if (upload) upload.style.display = fileRoot === 'docker' ? 'none' : '';

  const crumbs = document.getElementById('file-crumbs');
  if (!crumbs) return;
  if (fileRoot !== 'docker') {
    crumbs.classList.add('hidden');
    crumbs.innerHTML = '';
    return;
  }
  crumbs.classList.remove('hidden');
  crumbs.innerHTML = dockerProject
    ? `<a href="#" id="crumb-root">📚 Проекты</a> / <b>${esc(dockerProject)}</b>`
    : 'Библиотека Compose-проектов Bot4VPS. Здесь — правка файлов, развёртывание — в разделе Docker.';
  crumbs.querySelector('#crumb-root')?.addEventListener('click', e => {
    e.preventDefault();
    dockerProject = '';
    loadFiles();
  });
}

export async function loadFiles() {
  updateChrome();
  const el = document.getElementById('file-list');
  if (!el) return;
  try {
    const qs = new URLSearchParams({ root: fileRoot });
    if (fileRoot === 'docker' && dockerProject) qs.set('project', dockerProject);
    const data = await j('/api/files?' + qs);
    const items = data.items || [];

    if (!items.length) {
      const hint = (fileRoot === 'docker' && !dockerProject)
        ? 'Проектов нет. Загрузите Compose-проект в разделе Docker → Compose.'
        : 'Пусто';
      el.innerHTML = `<div class="empty" style="padding:.8rem">${hint}</div>`;
      return;
    }

    // --- уровень проектов (docker) ---
    if (data.level === 'projects') {
      el.innerHTML = items.map(p => `<div class="file-row">
        <span>📦 ${esc(p.name)} · файлов: ${p.files}${p.size ? ' · ' + fmtSize(p.size) : ''}</span>
        <span style="display:flex;gap:.3rem;flex-shrink:0">
          <button type="button" class="secondary" style="padding:.2rem .45rem" data-open="${esc(p.name)}">Открыть</button>
        </span></div>`).join('');
      el.querySelectorAll('[data-open]').forEach(b => b.onclick = () => {
        dockerProject = b.dataset.open;
        loadFiles();
      });
      return;
    }

    // --- уровень файлов ---
    el.innerHTML = items.map(f => {
      const dlQs = new URLSearchParams({ root: fileRoot, name: f.name });
      if (dockerProject) dlQs.set('project', dockerProject);
      const editBtn = f.editable
        ? `<button type="button" class="secondary" style="padding:.2rem .45rem" data-edit="${esc(f.name)}" title="Редактировать">✏️</button>`
        : '';
      const viewBtn = fileRoot === 'keys'
        ? `<button type="button" class="secondary" style="padding:.2rem .45rem" data-viewkey="${esc(f.name)}" title="Показать">👁</button>`
        : '';
      return `<div class="file-row">
        <span>${iconFor(f.name)} ${esc(f.name)}${f.size != null ? ' · ' + fmtSize(f.size) : ''}</span>
        <span style="display:flex;gap:.3rem;flex-shrink:0">
          ${viewBtn}${editBtn}
          <a class="btn secondary" style="padding:.2rem .45rem;text-decoration:none"
             href="/api/files/download?${dlQs}" title="Скачать">⬇</a>
          <button type="button" class="secondary" style="padding:.2rem .45rem" data-del="${esc(f.name)}" title="Удалить">🗑</button>
        </span></div>`;
    }).join('');

    el.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
      openEditor(fileRoot, b.dataset.edit, dockerProject, loadFiles));
    el.querySelectorAll('[data-viewkey]').forEach(b => b.onclick = () => viewKey(b.dataset.viewkey));
    el.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      if (!confirm('Удалить ' + b.dataset.del + '?')) return;
      try {
        const q = new URLSearchParams({ root: fileRoot, name: b.dataset.del });
        if (dockerProject) q.set('project', dockerProject);
        await j('/api/files?' + q, { method: 'DELETE' });
        loadFiles();
      } catch (e) { toast(e.message, false); }
    });
  } catch (e) {
    el.innerHTML = '<div class="empty" style="padding:.8rem">' + esc(e.message) + '</div>';
  }
}

async function viewKey(name) {
  try {
    const d = await j('/api/keys/view?name=' + encodeURIComponent(name));
    const modal = document.getElementById('script-modal');
    const title = document.getElementById('script-view-title');
    const body = document.getElementById('script-view-body');
    title.textContent = '🔑 ' + (d.name || name);
    let text = d.content || '';
    if (d.public) text += '\n\n--- PUBLIC ---\n' + d.public;
    body.textContent = text;
    modal.classList.add('open');
  } catch (e) { toast(e.message, false); }
}

// ---------------- создание скрипта ----------------

function openScriptNew() {
  const input = document.getElementById('script-new-name');
  const warn = document.getElementById('script-new-warn');
  if (input) input.value = '';
  if (warn) warn.textContent = '';
  document.getElementById('script-new-modal')?.classList.add('open');
  setTimeout(() => input?.focus(), 30);
}

function closeScriptNew() {
  document.getElementById('script-new-modal')?.classList.remove('open');
}

async function createScript() {
  const warn = document.getElementById('script-new-warn');
  const name = (document.getElementById('script-new-name')?.value || '').trim();
  if (!name) { warn.textContent = 'Укажите имя файла.'; return; }
  try {
    const d = await j('/api/files/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    closeScriptNew();
    toast('Скрипт создан', true);
    await loadFiles();
    // Сразу открываем редактор с заготовкой — пользователь начинает писать код.
    openEditor('scripts', d.name, '', loadFiles);
  } catch (e) {
    // Ошибка имени (traversal, дубликат) приходит с бэка — показываем в модалке.
    warn.textContent = e.message;
  }
}

export function bindFilesUI() {
  document.getElementById('btn-create-script')?.addEventListener('click', openScriptNew);
  document.getElementById('script-new-create')?.addEventListener('click', createScript);
  document.getElementById('script-new-cancel')?.addEventListener('click', closeScriptNew);
  document.getElementById('script-new-name')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); createScript(); }
    else if (e.key === 'Escape') closeScriptNew();
  });

  document.getElementById('file-tabs')?.querySelectorAll('[data-root]').forEach(b => {
    b.onclick = () => {
      fileRoot = b.dataset.root;
      dockerProject = '';          // при смене вкладки выходим на верхний уровень
      document.getElementById('file-tabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      loadFiles();
    };
  });
  document.getElementById('btn-create-key')?.addEventListener('click', async () => {
    const name = prompt('Имя ключа (без пробелов):');
    if (!name) return;
    try {
      await j('/api/keys/create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      toast('Ключ создан', true); loadFiles();
    } catch (e) { toast(e.message, false); }
  });
  document.getElementById('upload-file')?.addEventListener('change', async e => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await fetch('/api/files/upload?root=' + encodeURIComponent(fileRoot), { method: 'POST', body: fd });
      const t = await r.text(); let d; try { d = JSON.parse(t); } catch { d = {}; }
      if (!r.ok) throw new Error(d.detail || t);
      toast('OK', true); loadFiles();
    } catch (err) { toast(err.message, false); }
    e.target.value = '';
  });
}
