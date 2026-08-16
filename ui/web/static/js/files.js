// Раздел «Файлы»: локальная Docker/Compose-библиотека и SSH-ключи.
import { j, esc } from './api.js';
import { toast, confirmAction, plural } from './ui.js';
import { openEditor } from './editor.js?v=20260815-scripts-table-v1';
import { openDockerProjectFile } from './docker.js?v=20260816-service-singleton-v1';

let fileRoot = 'docker';
let dockerProject = '';
let dockerDir = '';
let libraryDialogMode = '';
let pendingProjectZip = null;

function fmtSize(n) {
  if (n == null) return '';
  if (n < 1024) return n + ' б';
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' КБ';
  return (n / (1024 * 1024)).toFixed(1) + ' МБ';
}

function iconFor(name) {
  const n = String(name || '').toLowerCase();
  if (fileRoot === 'keys') return '🔑';
  if (n.endsWith('.sh')) return '📜';
  if (n.endsWith('.yml') || n.endsWith('.yaml')) return '🧩';
  if (n === '.env' || n.endsWith('/.env')) return '⚙️';
  if (isImage(n)) return '🖼';
  return '📄';
}

function isImage(name) {
  return /\.(jpe?g|png|webp|gif)$/i.test(String(name || ''));
}

function isSvg(name) {
  return /\.svg$/i.test(String(name || ''));
}

function setShown(id, shown) {
  const el = document.getElementById(id);
  if (el) el.style.display = shown ? '' : 'none';
}

function updateChrome() {
  setShown('btn-create-key', fileRoot === 'keys');
  setShown('upload-label', fileRoot !== 'docker');

  const dockerRoot = fileRoot === 'docker' && !dockerProject;
  const dockerInside = fileRoot === 'docker' && !!dockerProject;
  setShown('btn-docker-project-new', dockerRoot);
  setShown('docker-project-upload-label', dockerRoot);
  setShown('btn-docker-file-new', dockerInside);
  setShown('btn-docker-folder-new', dockerInside);
  setShown('docker-file-upload-label', dockerInside);

  renderBreadcrumbs();
}

function renderBreadcrumbs() {
  const crumbs = document.getElementById('file-crumbs');
  if (!crumbs) return;
  if (fileRoot !== 'docker') {
    crumbs.classList.add('hidden');
    crumbs.innerHTML = '';
    return;
  }
  crumbs.classList.remove('hidden');
  if (!dockerProject) {
    crumbs.innerHTML = 'Локальная библиотека Docker/Compose-проектов. Развёртывание выполняется в Docker → Compose.';
    return;
  }

  const parts = dockerDir ? dockerDir.split('/').filter(Boolean) : [];
  let current = '';
  const html = [
    '<button type="button" class="docker-crumb" data-dcrumb-projects>Docker</button>',
    `<button type="button" class="docker-crumb" data-dcrumb-dir="">${esc(dockerProject)}</button>`,
  ];
  parts.forEach((part, index) => {
    current = current ? `${current}/${part}` : part;
    if (index === parts.length - 1) html.push(`<b>${esc(part)}</b>`);
    else html.push(`<button type="button" class="docker-crumb" data-dcrumb-dir="${esc(current)}">${esc(part)}</button>`);
  });
  crumbs.innerHTML = html.join(' <span aria-hidden="true">/</span> ');
  crumbs.querySelector('[data-dcrumb-projects]')?.addEventListener('click', () => {
    dockerProject = '';
    dockerDir = '';
    loadFiles();
  });
  crumbs.querySelectorAll('[data-dcrumb-dir]').forEach(b => b.onclick = () => {
    dockerDir = b.dataset.dcrumbDir || '';
    loadFiles();
  });
}

function dockerFilePath(name) {
  return dockerDir ? `${dockerDir}/${name}` : name;
}

function openDockerEntry(item) {
  if (item.is_dir) {
    dockerDir = item.path;
    loadFiles();
    return;
  }
  if (isImage(item.path) || isSvg(item.path)) {
    openDockerProjectFile(dockerProject, item.path);
    return;
  }
  openDockerProjectFile(dockerProject, item.path);
}

export async function loadFiles() {
  updateChrome();
  const el = document.getElementById('file-list');
  if (!el) return;
  try {
    const qs = new URLSearchParams({ root: fileRoot });
    if (fileRoot === 'docker' && dockerProject) {
      qs.set('project', dockerProject);
      if (dockerDir) qs.set('directory', dockerDir);
    }
    const data = await j('/api/files?' + qs);
    const items = data.items || [];

    if (!items.length) {
      const hint = fileRoot === 'docker'
        ? (dockerProject ? 'Папка пуста. Создайте файл, папку или загрузите файл.' : 'Проектов пока нет.')
        : 'Пусто';
      el.innerHTML = `<div class="empty" style="padding:.8rem">${hint}</div>`;
      return;
    }

    if (data.level === 'projects') {
      el.innerHTML = `<div class="docker-library-projects">${items.map(p => `
        <div class="docker-library-project" role="button" tabindex="0" data-project-open="${esc(p.name)}">
          <span class="docker-library-project-main">
            <span class="docker-library-project-name">📦 ${esc(p.name)}</span>
            <span class="docker-library-project-meta">${p.compose_file ? 'Compose' : 'Пустой проект'} · ${p.files} ${plural(p.files, 'файл', 'файла', 'файлов')}${p.size ? ' · ' + fmtSize(p.size) : ''}</span>
          </span>
          <button type="button" class="secondary docker-library-action" data-project-del="${esc(p.name)}" title="Удалить проект" aria-label="Удалить проект ${esc(p.name)}">🗑</button>
        </div>`).join('')}</div>`;
      el.querySelectorAll('[data-project-open]').forEach(card => {
        const open = () => {
          dockerProject = card.dataset.projectOpen;
          dockerDir = '';
          loadFiles();
        };
        card.onclick = open;
        card.onkeydown = e => {
          if (e.target !== card) return;
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        };
      });
      el.querySelectorAll('[data-project-del]').forEach(b => b.onclick = async e => {
        e.preventDefault();
        e.stopPropagation();
        const name = b.dataset.projectDel;
        const approved = await confirmAction({
          title: `Удалить проект «${name}»?`,
          message: 'Проект и всё его содержимое будут удалены.',
          confirmText: 'Удалить',
        });
        if (!approved) return;
        try {
          await j(`/api/services/docker/-/stacks/${encodeURIComponent(name)}`, { method: 'DELETE' });
          toast('Проект удалён', true);
          await loadFiles();
        } catch (err) { toast(err.message, false); }
      });
      return;
    }

    if (fileRoot === 'docker') {
      el.innerHTML = items.map(f => {
        const svg = isSvg(f.path);
        const image = isImage(f.path);
        const viewBtn = (image || svg)
          ? `<button type="button" class="secondary docker-library-action" data-docker-view="${esc(f.path)}" title="Просмотреть">👁</button>`
          : '';
        const editBtn = f.editable
          ? `<button type="button" class="secondary docker-library-action" data-docker-edit="${esc(f.path)}" title="Редактировать">✏️</button>`
          : '';
        // Основной Compose-файл определяет backend. Расширения здесь намеренно
        // не проверяются: любой другой YAML остаётся обычным удаляемым файлом.
        const deleteBtn = (f.is_dir || !f.is_compose)
          ? `<button type="button" class="secondary docker-library-action" data-docker-delete="${esc(f.path)}" title="Удалить" aria-label="Удалить ${esc(f.name)}">🗑</button>`
          : '';
        return `<div class="file-row" role="button" tabindex="0" data-docker-entry="${esc(f.path)}">
          <span class="docker-library-entry-main">
            <span class="file-icon">${f.is_dir ? '📁' : iconFor(f.path)}</span>
            <span class="docker-library-entry-name">${esc(f.name)}</span>
            ${!f.is_dir && f.size != null ? `<span class="file-meta">${fmtSize(f.size)}</span>` : ''}
          </span>
          <span class="docker-library-actions">${viewBtn}${editBtn}${deleteBtn}</span>
        </div>`;
      }).join('');

      el.querySelectorAll('[data-docker-entry]').forEach(row => {
        const item = items.find(x => x.path === row.dataset.dockerEntry);
        const open = () => item && openDockerEntry(item);
        row.onclick = open;
        row.onkeydown = e => {
          if (e.target !== row) return;
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        };
      });
      el.querySelectorAll('[data-docker-view]').forEach(b => b.onclick = e => {
        e.preventDefault();
        e.stopPropagation();
        openDockerProjectFile(dockerProject, b.dataset.dockerView);
      });
      el.querySelectorAll('[data-docker-edit]').forEach(b => b.onclick = e => {
        e.preventDefault();
        e.stopPropagation();
        const path = b.dataset.dockerEdit;
        // SVG превью определяется как image/svg+xml, поэтому для текстовой правки
        // открываем уже существующий общий редактор. Для остальных файлов сохраняем
        // существующую Docker-модалку редактора/preview.
        if (isSvg(path)) openEditor('docker', path, dockerProject, loadFiles);
        else openDockerProjectFile(dockerProject, path);
      });
      el.querySelectorAll('[data-docker-delete]').forEach(b => b.onclick = e => {
        e.preventDefault();
        e.stopPropagation();
        const item = items.find(x => x.path === b.dataset.dockerDelete);
        if (item) deleteDockerEntry(item);
      });
      return;
    }

    // Keys: прежние действия, включая скачивание вне Docker-библиотеки.
    el.innerHTML = items.map(f => {
      const dlQs = new URLSearchParams({ root: fileRoot, name: f.name });
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
          <a class="btn secondary" style="padding:.2rem .45rem;text-decoration:none" href="/api/files/download?${dlQs}" title="Скачать">⬇</a>
          <button type="button" class="secondary" style="padding:.2rem .45rem" data-del="${esc(f.name)}" title="Удалить">🗑</button>
        </span></div>`;
    }).join('');
    el.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
      openEditor(fileRoot, b.dataset.edit, '', loadFiles));
    el.querySelectorAll('[data-viewkey]').forEach(b => b.onclick = () => viewKey(b.dataset.viewkey));
    el.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      const name = b.dataset.del;
      const approved = await confirmAction({
        title: `Удалить файл «${name}»?`,
        confirmText: 'Удалить',
      });
      if (!approved) return;
      try {
        const q = new URLSearchParams({ root: fileRoot, name });
        await j('/api/files?' + q, { method: 'DELETE' });
        loadFiles();
      } catch (err) { toast(err.message, false); }
    });
  } catch (e) {
    // Если открытая папка была удалена извне, поднимаемся к ближайшему
    // существующему родителю и синхронно обновляем breadcrumbs.
    if (fileRoot === 'docker' && dockerProject && dockerDir &&
        /Папка не найдена|нет папки/i.test(String(e.message || ''))) {
      dockerDir = dockerDir.split('/').slice(0, -1).join('/');
      updateChrome();
      return loadFiles();
    }
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

async function deleteDockerEntry(item) {
  const folder = !!item.is_dir;
  const approved = await confirmAction({
    title: `${folder ? 'Удалить папку' : 'Удалить файл'} «${item.name}»?`,
    message: folder ? 'Все файлы и подпапки внутри будут удалены.' : '',
    confirmText: 'Удалить',
  });
  if (!approved) return;
  try {
    const qs = new URLSearchParams({
      root: 'docker',
      project: dockerProject,
      name: item.path,
    });
    await j('/api/files?' + qs, { method: 'DELETE' });
    toast(folder ? 'Папка удалена' : 'Файл удалён', true);
    await loadFiles();
  } catch (e) {
    toast(e.message, false);
  }
}

// ---------------- диалог Docker-библиотеки ----------------

function openLibraryDialog(mode, options = {}) {
  libraryDialogMode = mode;
  const modal = document.getElementById('docker-library-modal');
  const title = document.getElementById('docker-library-title');
  const label = document.getElementById('docker-library-name-label');
  const input = document.getElementById('docker-library-name');
  const typeRow = document.getElementById('docker-library-type-row');
  const type = document.getElementById('docker-library-type');
  const warn = document.getElementById('docker-library-warn');
  const submit = document.getElementById('docker-library-submit');
  const isFile = mode === 'file';
  typeRow.classList.toggle('hidden', !isFile);
  type.classList.toggle('hidden', !isFile);
  warn.textContent = options.warn || '';

  if (mode === 'project') {
    title.textContent = 'Создание проекта';
    label.textContent = 'Название проекта';
    input.placeholder = 'monitoring';
    submit.textContent = 'Создать';
  } else if (mode === 'key') {
    title.textContent = 'Создание SSH-ключа';
    label.textContent = 'Имя ключа';
    input.placeholder = 'my-key';
    submit.textContent = 'Создать';
  } else if (mode === 'folder') {
    title.textContent = 'Создать папку';
    label.textContent = 'Название';
    input.placeholder = 'config';
    submit.textContent = 'Создать';
  } else if (mode === 'file') {
    title.textContent = 'Создать файл';
    label.textContent = 'Имя';
    type.value = options.type || 'yaml';
    input.placeholder = type.value === 'env' ? '.env' : 'docker-compose.yml';
    submit.textContent = 'Создать';
  } else {
    title.textContent = 'Загрузить проект с другим именем';
    label.textContent = 'Название проекта';
    input.placeholder = 'project-2';
    submit.textContent = 'Загрузить';
  }
  input.value = options.name || (mode === 'file' ? 'docker-compose.yml' : '');
  modal.classList.add('open');
  setTimeout(() => { input.focus(); input.select(); }, 30);
}

function closeLibraryDialog() {
  document.getElementById('docker-library-modal')?.classList.remove('open');
  document.getElementById('docker-library-warn').textContent = '';
  libraryDialogMode = '';
  pendingProjectZip = null;
}

async function submitLibraryDialog() {
  const input = document.getElementById('docker-library-name');
  const warn = document.getElementById('docker-library-warn');
  const name = (input?.value || '').trim();
  if (!name) { warn.textContent = 'Укажите имя.'; return; }
  try {
    if (libraryDialogMode === 'project') {
      const d = await j('/api/files/docker/projects', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      dockerProject = d.project.name;
      dockerDir = '';
      closeLibraryDialog();
      toast('Проект создан', true);
      await loadFiles();
      return;
    }
    if (libraryDialogMode === 'folder') {
      await j('/api/files/docker/directories', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: dockerProject, directory: dockerDir, name }),
      });
      closeLibraryDialog();
      toast('Папка создана', true);
      await loadFiles();
      return;
    }
    if (libraryDialogMode === 'file') {
      const kind = document.getElementById('docker-library-type').value;
      const d = await j('/api/files/docker/files', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: dockerProject, directory: dockerDir, name, kind }),
      });
      closeLibraryDialog();
      toast('Файл создан', true);
      await loadFiles();
      openDockerProjectFile(dockerProject, d.file.path);
      return;
    }
    if (libraryDialogMode === 'key') {
      await j('/api/keys/create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      closeLibraryDialog();
      toast('Ключ создан', true);
      await loadFiles();
      return;
    }
    if (libraryDialogMode === 'zip-conflict' && pendingProjectZip) {
      const file = pendingProjectZip;
      await uploadDockerProject(file, name);
    }
  } catch (e) {
    warn.textContent = e.message;
  }
}

async function parseFetchResponse(response) {
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = {}; }
  return { text, data };
}

async function uploadDockerProject(file, name = '') {
  const fd = new FormData();
  fd.append('file', file);
  const qs = name ? '?name=' + encodeURIComponent(name) : '';
  const response = await fetch('/api/files/docker/projects/upload' + qs, { method: 'POST', body: fd });
  const { text, data } = await parseFetchResponse(response);
  if (!response.ok) {
    const detail = data.detail;
    if (response.status === 409) {
      const info = detail && typeof detail === 'object' ? detail : { message: String(detail || text), name };
      pendingProjectZip = file;
      openLibraryDialog('zip-conflict', { name: info.name || name, warn: info.message || 'Проект уже существует.' });
      return;
    }
    throw new Error(typeof detail === 'string' ? detail : (detail?.message || text || 'Ошибка загрузки'));
  }
  dockerProject = data.project.name;
  dockerDir = '';
  closeLibraryDialog();
  toast('Проект загружен', true);
  await loadFiles();
}

async function uploadDockerFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const qs = new URLSearchParams({ project: dockerProject });
  if (dockerDir) qs.set('directory', dockerDir);
  const response = await fetch('/api/files/docker/upload?' + qs, { method: 'POST', body: fd });
  const { text, data } = await parseFetchResponse(response);
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.message || text));
  toast('Файл загружен', true);
  await loadFiles();
}

export function bindFilesUI() {
  window.addEventListener('docker-project-file-saved', () => {
    if (fileRoot === 'docker') loadFiles();
  });

  document.getElementById('btn-docker-project-new')?.addEventListener('click', () => openLibraryDialog('project'));
  document.getElementById('btn-docker-folder-new')?.addEventListener('click', () => openLibraryDialog('folder'));
  document.getElementById('btn-docker-file-new')?.addEventListener('click', () => openLibraryDialog('file'));
  document.getElementById('docker-library-cancel')?.addEventListener('click', closeLibraryDialog);
  document.getElementById('docker-library-submit')?.addEventListener('click', submitLibraryDialog);
  document.getElementById('docker-library-name')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); submitLibraryDialog(); }
    else if (e.key === 'Escape') closeLibraryDialog();
  });
  document.getElementById('docker-library-type')?.addEventListener('change', e => {
    const input = document.getElementById('docker-library-name');
    input.value = e.target.value === 'env' ? '.env' : 'docker-compose.yml';
    input.placeholder = input.value;
    input.focus();
    input.select();
  });

  document.getElementById('docker-project-upload')?.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try { await uploadDockerProject(file); }
    catch (err) { toast(err.message, false); }
  });
  document.getElementById('docker-file-upload')?.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try { await uploadDockerFile(file); }
    catch (err) { toast(err.message, false); }
  });

  document.getElementById('file-tabs')?.querySelectorAll('[data-root]').forEach(b => {
    b.onclick = () => {
      fileRoot = b.dataset.root;
      dockerProject = '';
      dockerDir = '';
      document.getElementById('file-tabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      loadFiles();
    };
  });

  document.getElementById('btn-create-key')?.addEventListener('click', () => openLibraryDialog('key'));

  document.getElementById('upload-file')?.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const response = await fetch('/api/files/upload?root=' + encodeURIComponent(fileRoot), { method: 'POST', body: fd });
      const { text, data } = await parseFetchResponse(response);
      if (!response.ok) throw new Error(data.detail || text);
      toast('OK', true);
      loadFiles();
    } catch (err) { toast(err.message, false); }
    e.target.value = '';
  });
}
