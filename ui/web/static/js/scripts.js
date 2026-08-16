import { j, esc } from './api.js';
import { toast, confirmAction } from './ui.js';
import { openEditor } from './editor.js?v=20260815-scripts-table-v1';
import { openServer, openServerTerminal } from './servers.js?v=20260816-task-history-v3';
import { state, setScripts } from './state.js';

const SCRIPT_PAGE_SIZE = 9;
const selectedScripts = new Set();
let scriptsQuery = '';
let scriptsPage = 1;

function displayName(script) {
  const described = String(script?.description || '').trim();
  if (described) return described;
  const plain = String(script?.name || '').replace(/\.sh$/i, '').replace(/[_-]+/g, ' ').trim();
  return plain ? plain.charAt(0).toUpperCase() + plain.slice(1) : script.name;
}

function formatModified(value) {
  if (value == null || value === '') return '—';
  const numeric = Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric)
    : new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(date);
}

function filteredScripts() {
  const query = scriptsQuery.trim().toLocaleLowerCase('ru-RU');
  if (!query) return state.scripts;
  return state.scripts.filter(script => {
    const haystack = `${displayName(script)} ${script.name}`.toLocaleLowerCase('ru-RU');
    return haystack.includes(query);
  });
}

function visiblePage(all = filteredScripts()) {
  const pages = Math.max(1, Math.ceil(all.length / SCRIPT_PAGE_SIZE));
  scriptsPage = Math.min(Math.max(1, scriptsPage), pages);
  const start = (scriptsPage - 1) * SCRIPT_PAGE_SIZE;
  return { items: all.slice(start, start + SCRIPT_PAGE_SIZE), pages };
}

function renderPager(pages) {
  const pager = document.getElementById('scripts-pagination');
  if (!pager) return;
  if (!state.scripts.length) {
    pager.innerHTML = '';
    return;
  }

  const pageButtons = [];
  for (let page = 1; page <= pages; page += 1) {
    if (pages > 7 && page !== 1 && page !== pages && Math.abs(page - scriptsPage) > 1) {
      if (page === 2 || page === pages - 1) pageButtons.push('<span class="scripts-page-gap">…</span>');
      continue;
    }
    pageButtons.push(
      `<button type="button" class="scripts-page-btn${page === scriptsPage ? ' on' : ''}" data-script-page="${page}" aria-label="Страница ${page}"${page === scriptsPage ? ' aria-current="page"' : ''}>${page}</button>`
    );
  }

  pager.innerHTML = `
    <button type="button" class="scripts-page-btn" data-script-page-prev aria-label="Предыдущая страница" ${scriptsPage <= 1 ? 'disabled' : ''}>←</button>
    ${pageButtons.join('')}
    <button type="button" class="scripts-page-btn" data-script-page-next aria-label="Следующая страница" ${scriptsPage >= pages ? 'disabled' : ''}>→</button>`;

  pager.querySelector('[data-script-page-prev]')?.addEventListener('click', () => {
    if (scriptsPage > 1) { scriptsPage -= 1; renderScriptsTable(); }
  });
  pager.querySelector('[data-script-page-next]')?.addEventListener('click', () => {
    if (scriptsPage < pages) { scriptsPage += 1; renderScriptsTable(); }
  });
  pager.querySelectorAll('[data-script-page]').forEach(button => {
    button.addEventListener('click', () => {
      scriptsPage = Number(button.dataset.scriptPage) || 1;
      renderScriptsTable();
    });
  });
}

function updateSelectionChrome(items) {
  const bulk = document.getElementById('scripts-bulk-actions');
  bulk?.classList.toggle('hidden', selectedScripts.size === 0);

  const selectPage = document.getElementById('scripts-select-page');
  if (!selectPage) return;
  const selectedVisible = items.filter(script => selectedScripts.has(script.name)).length;
  selectPage.checked = items.length > 0 && selectedVisible === items.length;
  selectPage.indeterminate = selectedVisible > 0 && selectedVisible < items.length;
  selectPage.disabled = items.length === 0;
}

function closeScriptActionsMenu() {
  document.getElementById('scripts-actions-pop')?.classList.add('hidden');
}

function openScriptActionsMenu(anchor, scriptName) {
  let pop = document.getElementById('scripts-actions-pop');
  if (!pop) {
    pop = document.createElement('div');
    pop.id = 'scripts-actions-pop';
    pop.className = 'wg-prof-pop scripts-actions-pop hidden';
    document.body.appendChild(pop);
  }

  pop.innerHTML = `
    <button type="button" data-script-menu-action="run">▶ Запустить</button>
    <button type="button" data-script-menu-action="terminal">&gt;_ Терминал</button>
    <button type="button" data-script-menu-action="edit">✎ Редактировать</button>
    <hr/>
    <button type="button" class="danger" data-script-menu-action="delete">🗑 Удалить</button>`;

  pop.querySelectorAll('[data-script-menu-action]').forEach(button => {
    button.addEventListener('click', () => {
      const action = button.dataset.scriptMenuAction;
      closeScriptActionsMenu();
      if (action === 'run') openRunModal(null, scriptName);
      else if (action === 'terminal') openRunModal(null, scriptName, 'terminal');
      else if (action === 'edit') openEditor(
        'scripts', scriptName, '', loadScripts,
        { discardOnCancel: true, shortcutSave: false },
      );
      else if (action === 'delete') deleteOneScript(scriptName);
    });
  });

  pop.classList.remove('hidden');
  const rect = anchor.getBoundingClientRect();
  const popWidth = pop.offsetWidth || 200;
  let left = rect.right - popWidth;
  let top = rect.bottom + 4;
  left = Math.max(8, Math.min(left, window.innerWidth - popWidth - 8));
  if (top + pop.offsetHeight > window.innerHeight - 8) {
    top = Math.max(8, rect.top - pop.offsetHeight - 4);
  }
  pop.style.position = 'fixed';
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

function bindTableRows(items) {
  const body = document.getElementById('scripts-body');
  if (!body) return;

  closeScriptActionsMenu();

  body.querySelectorAll('[data-script-select]').forEach(input => {
    input.addEventListener('change', () => {
      if (input.checked) selectedScripts.add(input.dataset.scriptSelect);
      else selectedScripts.delete(input.dataset.scriptSelect);
      updateSelectionChrome(items);
    });
  });
  body.querySelectorAll('[data-script-menu]').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation();
      openScriptActionsMenu(button, button.dataset.scriptMenu);
    });
  });
  body.querySelectorAll('[data-script-run]').forEach(button => {
    button.addEventListener('click', () => openRunModal(null, button.dataset.scriptRun));
  });
  body.querySelectorAll('[data-script-terminal]').forEach(button => {
    button.addEventListener('click', () => openRunModal(null, button.dataset.scriptTerminal, 'terminal'));
  });
  body.querySelectorAll('[data-script-edit]').forEach(button => {
    button.addEventListener('click', () => openEditor(
      'scripts', button.dataset.scriptEdit, '', loadScripts,
      { discardOnCancel: true, shortcutSave: false },
    ));
  });
  body.querySelectorAll('[data-script-delete]').forEach(button => {
    button.addEventListener('click', () => deleteOneScript(button.dataset.scriptDelete));
  });
}

function renderScriptsTable() {
  const body = document.getElementById('scripts-body');
  if (!body) return;

  const all = filteredScripts();
  const { items, pages } = visiblePage(all);
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="5" class="scripts-empty-cell">${state.scripts.length ? 'Ничего не найдено' : 'Нет .sh-скриптов'}</td></tr>`;
  } else {
    body.innerHTML = items.map(script => {
      const hasParams = Array.isArray(script.params) && script.params.length > 0;
      return `<tr>
        <td class="scripts-check-col">
          <input type="checkbox" data-script-select="${esc(script.name)}" aria-label="Выбрать ${esc(script.name)}" ${selectedScripts.has(script.name) ? 'checked' : ''}/>
        </td>
        <td>
          <div class="scripts-name-main">${esc(displayName(script))}</div>
          <div class="scripts-file-name">${esc(script.name)}</div>
        </td>
        <td class="scripts-param-col">
          <span class="scripts-param ${hasParams ? 'yes' : 'no'}">${hasParams ? '✓ Да' : '✕ Нет'}</span>
        </td>
        <td class="scripts-date-col"><time>${esc(formatModified(script.modified || script.mtime))}</time></td>
        <td class="scripts-actions-col">
          <div class="scripts-row-actions">
            <button type="button" class="secondary scripts-more-btn" data-script-menu="${esc(script.name)}" aria-label="Действия со скриптом ${esc(displayName(script))}" title="Действия">⋯</button>
            <button type="button" class="secondary scripts-action-btn" data-script-run="${esc(script.name)}">▶ Запустить</button>
            <button type="button" class="secondary scripts-action-btn" data-script-terminal="${esc(script.name)}">&gt;_ Терминал</button>
            <button type="button" class="secondary scripts-action-btn" data-script-edit="${esc(script.name)}">✎ Редактировать</button>
            <button type="button" class="danger-transparent scripts-action-btn" data-script-delete="${esc(script.name)}">🗑 Удалить</button>
          </div>
        </td>
      </tr>`;
    }).join('');
  }

  bindTableRows(items);
  updateSelectionChrome(items);
  renderPager(pages);
}

async function fillMissingModified(scripts) {
  const missing = scripts.filter(script => !script.modified && !script.mtime);
  await Promise.all(missing.map(async script => {
    try {
      const query = new URLSearchParams({ root: 'scripts', name: script.name });
      const response = await fetch(`/api/files/download?${query}`, { method: 'HEAD' });
      const modified = response.headers.get('Last-Modified');
      if (response.ok && modified) script.modified = modified;
    } catch (_) {
      // Основной API уже отдаёт дату; HEAD — только совместимый fallback.
    }
  }));
}

export async function loadScripts() {
  try {
    const data = await j('/api/scripts');
    setScripts(data.scripts || []);
    await fillMissingModified(state.scripts);
    const existing = new Set(state.scripts.map(script => script.name));
    [...selectedScripts].forEach(name => {
      if (!existing.has(name)) selectedScripts.delete(name);
    });
    renderScriptsTable();
  } catch (error) {
    const body = document.getElementById('scripts-body');
    if (body) body.innerHTML = `<tr><td colspan="5" class="scripts-empty-cell">${esc(error.message)}</td></tr>`;
  }
}

async function deleteScriptNames(names) {
  for (const name of names) {
    await j(`/api/files?root=scripts&name=${encodeURIComponent(name)}`, { method: 'DELETE' });
    selectedScripts.delete(name);
  }
  await loadScripts();
}

async function deleteOneScript(name) {
  const approved = await confirmAction({
    title: 'Удалить скрипт?',
    message: `Файл «${name}» будет удалён из библиотеки.`,
    confirmText: 'Удалить',
  });
  if (!approved) return;
  try {
    await deleteScriptNames([name]);
    toast('Скрипт удалён', true);
  } catch (error) {
    toast(error.message, false);
  }
}

async function deleteSelectedScripts() {
  const names = [...selectedScripts];
  if (!names.length) return;
  const approved = await confirmAction({
    title: 'Удалить выбранные скрипты?',
    message: `Будет удалено: ${names.length}.`,
    confirmText: 'Удалить',
  });
  if (!approved) return;
  try {
    await deleteScriptNames(names);
    toast('Выбранные скрипты удалены', true);
  } catch (error) {
    toast(error.message, false);
    await loadScripts();
  }
}

function downloadSingle(name) {
  const link = document.createElement('a');
  const query = new URLSearchParams({ root: 'scripts', name });
  link.href = `/api/files/download?${query}`;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function downloadSelectedScripts() {
  const names = [...selectedScripts];
  if (!names.length) return;
  if (names.length === 1) {
    downloadSingle(names[0]);
    return;
  }

  try {
    const query = new URLSearchParams();
    names.forEach(name => query.append('names', name));
    const response = await fetch(`/api/scripts-archive.zip?${query}`);
    if (!response.ok) {
      const text = await response.text();
      let detail = text;
      try { detail = JSON.parse(text).detail || text; } catch (_) {}
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'scripts.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (error) {
    toast(error.message, false);
  }
}

function openCreateScript() {
  const input = document.getElementById('script-create-name');
  const warn = document.getElementById('script-create-warn');
  if (input) input.value = '';
  if (warn) warn.textContent = '';
  document.getElementById('script-create-modal')?.classList.add('open');
  setTimeout(() => input?.focus(), 30);
}

function closeCreateScript() {
  document.getElementById('script-create-modal')?.classList.remove('open');
}

async function createScript() {
  const input = document.getElementById('script-create-name');
  const warn = document.getElementById('script-create-warn');
  const name = String(input?.value || '').trim();
  if (!name) {
    if (warn) warn.textContent = 'Укажите имя файла.';
    return;
  }
  if (warn) warn.textContent = '';
  try {
    const created = await j('/api/files/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    closeCreateScript();
    await loadScripts();
    openEditor('scripts', created.name, '', loadScripts, {
      discardOnCancel: true,
      shortcutSave: false,
    });
  } catch (error) {
    if (warn) warn.textContent = error.message;
  }
}

// ---- Параметры скрипта в модалке запуска ----

function currentScript() {
  const name = document.getElementById('run-script')?.value;
  return state.scripts.find(s => s.name === name) || null;
}

function parseCond(c) {
  // формат условия из core/script_utils: "paramname:value" (сравнение case-insensitive)
  if (!c || !String(c).includes(':')) return null;
  const idx = c.indexOf(':');
  return { name: c.slice(0, idx).trim(), value: c.slice(idx + 1) };
}

function buildRunParams(script) {
  const box = document.getElementById('run-params');
  if (!box) return;
  box.innerHTML = '';
  if (!script || !Array.isArray(script.params) || !script.params.length) return;

  const values = {};
  script.params.forEach(p => {
    if (p.type === 'select' && p.options && p.options.length) values[p.name] = p.options[0].value;
    else if (p.type === 'bool') values[p.name] = 'false';
    else values[p.name] = '';
  });

  function applyConditions() {
    box.querySelectorAll('.run-param').forEach(w => {
      const cn = w.dataset.condName, cv = w.dataset.condVal;
      if (!cn) return;
      const cur = String(values[cn] ?? '').toLowerCase();
      w.classList.toggle('hidden', cur !== String(cv ?? '').toLowerCase());
    });
  }

  script.params.forEach(p => {
    const wrap = document.createElement('div');
    wrap.className = 'run-param';
    wrap.dataset.name = p.name;
    const cond = parseCond(p.condition);
    if (cond) { wrap.dataset.condName = cond.name; wrap.dataset.condVal = cond.value; }

    const label = document.createElement('label');
    label.className = 'row';
    label.textContent = p.label || p.name;

    let field;
    if (p.type === 'select') {
      field = document.createElement('select');
      (p.options || []).forEach(o => {
        const op = document.createElement('option');
        op.value = o.value; op.textContent = o.label || o.value;
        field.appendChild(op);
      });
      field.value = values[p.name];
    } else if (p.type === 'bool') {
      field = document.createElement('select');
      [['true', 'Да'], ['false', 'Нет']].forEach(([v, l]) => {
        const op = document.createElement('option');
        op.value = v; op.textContent = l; field.appendChild(op);
      });
      field.value = 'false';
    } else {
      field = document.createElement('input');
      field.type = p.type === 'number' ? 'number' : 'text';
      field.value = values[p.name];
    }
    const update = () => { values[p.name] = field.value; applyConditions(); };
    field.addEventListener('input', update);
    field.addEventListener('change', update);

    wrap.appendChild(label);
    wrap.appendChild(field);
    box.appendChild(wrap);
  });

  box._values = values;
  applyConditions();
}

function collectRunValues() {
  const box = document.getElementById('run-params');
  const out = {};
  if (!box || !box._values) return out;
  box.querySelectorAll('.run-param:not(.hidden)').forEach(w => {
    const name = w.dataset.name;
    const v = box._values[name];
    if (v == null || v === '') return;
    out[name] = String(v);
  });
  return out;
}

let runMode = 'background';

export function openRunModal(serverId, scriptName, mode = 'background') {
  if (!state.scripts.length || !state.servers.length) {
    toast('Нет скриптов или серверов', false); return;
  }
  runMode = mode;
  const isTerm = mode === 'terminal';
  document.getElementById('run-script').innerHTML = state.scripts.map(s =>
    `<option value="${esc(s.name)}" ${s.name === scriptName ? 'selected' : ''}>${esc(s.name)}</option>`
  ).join('');
  document.getElementById('run-server').innerHTML = state.servers.map(s =>
    `<option value="${esc(s.id)}" ${s.id === serverId ? 'selected' : ''}>${esc(s.name)}</option>`
  ).join('');
  buildRunParams(currentScript());
  document.getElementById('run-params').classList.toggle('hidden', isTerm);
  document.getElementById('btn-run-confirm').textContent = isTerm ? '💻 Открыть терминал' : 'Выполнить';
  document.getElementById('run-modal').classList.add('open');
}

export async function confirmRun() {
  const script_name = document.getElementById('run-script').value;
  const server_id = document.getElementById('run-server').value;
  if (runMode === 'terminal') {
    document.getElementById('run-modal').classList.remove('open');
    await openServer(server_id);
    state.pendingTermScript = script_name;
    openServerTerminal();
    return;
  }
  const values = collectRunValues();
  try {
    const result = await j('/api/tasks/enqueue', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ script_name, server_id, values }),
    });
    document.getElementById('run-modal').classList.remove('open');
    toast('В очереди', true);
    if (result.task) await openServer(server_id);
  } catch (error) { toast(error.message, false); }
}

export function bindScriptsUI() {
  document.addEventListener('click', closeScriptActionsMenu);
  document.getElementById('scripts-actions-pop')?.addEventListener('click', event => event.stopPropagation());
  window.addEventListener('resize', closeScriptActionsMenu);
  window.addEventListener('scroll', closeScriptActionsMenu, true);

  document.getElementById('scripts-search')?.addEventListener('input', event => {
    scriptsQuery = event.target.value || '';
    scriptsPage = 1;
    renderScriptsTable();
  });
  document.getElementById('scripts-select-page')?.addEventListener('change', event => {
    const { items } = visiblePage();
    items.forEach(script => {
      if (event.target.checked) selectedScripts.add(script.name);
      else selectedScripts.delete(script.name);
    });
    renderScriptsTable();
  });
  document.getElementById('scripts-download-selected')?.addEventListener('click', downloadSelectedScripts);
  document.getElementById('scripts-delete-selected')?.addEventListener('click', deleteSelectedScripts);

  document.getElementById('btn-new-script')?.addEventListener('click', openCreateScript);
  document.getElementById('script-create-submit')?.addEventListener('click', createScript);
  document.getElementById('script-create-cancel')?.addEventListener('click', closeCreateScript);
  document.getElementById('script-create-name')?.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); createScript(); }
    else if (event.key === 'Escape') closeCreateScript();
  });

  document.getElementById('btn-run-confirm')?.addEventListener('click', confirmRun);
  document.getElementById('btn-run-cancel')?.addEventListener('click', () =>
    document.getElementById('run-modal').classList.remove('open'));
  document.getElementById('run-script')?.addEventListener('change', () =>
    buildRunParams(currentScript()));
  document.getElementById('run-modal')?.addEventListener('click', event => {
    if (event.target.id === 'run-modal') event.currentTarget.classList.remove('open');
  });

  document.getElementById('script-modal-close')?.addEventListener('click', () =>
    document.getElementById('script-modal')?.classList.remove('open'));
  document.getElementById('script-modal')?.addEventListener('click', event => {
    if (event.target.id === 'script-modal') event.currentTarget.classList.remove('open');
  });

  document.getElementById('upload-script')?.addEventListener('change', async event => {
    const input = event.target;
    const files = [...(input.files || [])];
    if (!files.length) return;

    let checked;
    try {
      const response = await fetch('/api/scripts/upload-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ names: files.map(file => file.name) }),
      });
      const text = await response.text();
      let data;
      try { data = JSON.parse(text); } catch (_) { data = {}; }
      if (!response.ok) throw new Error(data.detail || text || `HTTP ${response.status}`);
      checked = Array.isArray(data.files) ? data.files : [];
      if (checked.length !== files.length) throw new Error('Сервер вернул неполный результат проверки');
    } catch (error) {
      toast(`Не удалось проверить имена: ${error.message}`, false);
      input.value = '';
      return;
    }

    const duplicates = [];
    const rejected = [];
    const candidates = [];
    checked.forEach((item, index) => {
      const label = item.name && item.name !== item.original
        ? `${item.original} → ${item.name}`
        : (item.original || files[index].name);
      if (item.error) rejected.push(`${label}: ${item.error}`);
      else if (item.exists) duplicates.push(label);
      else candidates.push(files[index]);
    });

    if (duplicates.length) {
      toast(`Уже существуют и не будут загружены: ${duplicates.join(', ')}`, false);
    }
    if (!candidates.length) {
      if (rejected.length) toast(`Не загружено: ${rejected.join('; ')}`, false);
      input.value = '';
      return;
    }

    const uploaded = [];
    const failed = [...rejected];
    for (const file of candidates) {
      const form = new FormData();
      form.append('file', file);
      try {
        const response = await fetch('/api/upload/script', { method: 'POST', body: form });
        const text = await response.text();
        let data;
        try { data = JSON.parse(text); } catch (_) { data = {}; }
        if (!response.ok) throw new Error(data.detail || text || `HTTP ${response.status}`);
        uploaded.push(data.name || file.name);
      } catch (error) {
        failed.push(`${file.name}: ${error.message}`);
      }
    }

    if (uploaded.length) {
      toast(uploaded.length === 1 ? `Скрипт «${uploaded[0]}» загружен` : `Загружено скриптов: ${uploaded.length}`, true);
      await loadScripts();
    }
    if (failed.length) toast(`Не загружено: ${failed.join('; ')}`, false);
    input.value = '';
  });
}
