// Панель управления группами серверов (боковая панель на странице «Серверы»).
// Вынесен из settings.js: настройки больше не отвечают за группы, а единственный
// импортер — servers.js (динамический, при открытии панели).
// Спецификатор с ?v= обязателен: единый инстанс модуля (см. CLAUDE.md, ES-синглтоны).
import { j, esc } from './api.js';
import { toast, confirmAction } from './ui.js';
import { state, setGroups, setServerGroupTab } from './state.js';

const MODULE_V = '20260911-groups-v2';

function closeGroupsPanel() {
  const panel = document.getElementById('groups-panel');
  if (panel) panel.classList.remove('open');
}

// ---------------- Список групп ----------------
export async function loadGroupsAdmin(groupsOverride = null) {
  const box = document.getElementById('groups-list');
  if (!box) {
    console.warn('[groups] #groups-list not found');
    return;
  }
  box.innerHTML = '<div class="acc-note">Загрузка групп…</div>';
  try {
    const data = groupsOverride || await j('/api/groups');
    const groups = Array.isArray(data) ? data
      : (Array.isArray(data?.groups) ? data.groups : []);
    setGroups(groups);
    if (!groups.length) {
      box.innerHTML = '<div class="acc-note">Групп пока нет — создайте первую ниже</div>';
      return;
    }
    box.innerHTML = groups.map(g => {
      const name = (g && g.name) != null ? String(g.name) : String(g);
      const ssl = g && g.ssl_monitor ? 'checked' : '';
      const n = (g && g.servers != null) ? g.servers : 0;
      const canDelete = n === 0;
      return `<div class="group-row" data-name="${esc(name)}">
        <input class="grp-name" value="${esc(name)}" placeholder="Название"/>
        <label class="grp-ssl-label">
          <input type="checkbox" class="grp-ssl-cb" ${ssl}/>
          <span>SSL</span>
        </label>
        <span class="grp-count" title="Серверов в группе">${n}</span>
        <button type="button" class="icon-btn grp-save" title="Сохранить">💾</button>
        <button type="button" class="icon-btn grp-del ${canDelete ? '' : 'group-delete-blocked'}" title="${canDelete ? 'Удалить' : 'Нельзя удалить группу с серверами — сначала переместите серверы'}">🗑</button>
      </div>`;
    }).join('');
  } catch (e) {
    console.error('[groups] load failed', e);
    box.innerHTML = `<div class="acc-note" style="color:var(--err)">Ошибка загрузки: ${esc(e.message || e)}</div>`;
  }
}

async function refreshAfterGroupMutation({ oldName = null, newName = null, createdName = null, deletedName = null } = {}) {
  const data = await j('/api/groups');
  const groups = Array.isArray(data) ? data
    : (Array.isArray(data?.groups) ? data.groups : []);
  setGroups(groups);

  if (oldName && newName && state.serverGroupTab === oldName) {
    setServerGroupTab(newName);
  } else if (deletedName && state.serverGroupTab === deletedName) {
    setServerGroupTab('__all__');
  }

  // Новые и переименованные группы сразу включаются в отображение списка.
  // Это особенно важно, когда в localStorage уже сохранён список видимых групп.
  const shownName = createdName || newName;
  if (shownName) ensureGroupDisplayed(shownName, oldName);

  const serversModule = await import('./servers.js?v=20260913-hostkey-v2');
  await serversModule.loadServers();
  await loadGroupsAdmin(groups);
  await loadGroupsDisplayOrder();
}

function ensureGroupDisplayed(name, oldName = null) {
  const groupName = String(name || '').trim();
  if (!groupName) return;

  try {
    const rawVisible = localStorage.getItem('bot4vps_visible_groups');
    if (rawVisible) {
      const parsed = JSON.parse(rawVisible);
      if (Array.isArray(parsed)) {
        const visible = parsed.filter(value => value !== oldName);
        if (!visible.includes(groupName)) visible.push(groupName);
        localStorage.setItem('bot4vps_visible_groups', JSON.stringify(visible));
      }
    }

    const rawOrder = localStorage.getItem('bot4vps_group_order');
    if (rawOrder) {
      const parsed = JSON.parse(rawOrder);
      if (Array.isArray(parsed)) {
        const order = parsed.map(value => value === oldName ? groupName : value);
        if (!order.includes(groupName)) order.push(groupName);
        localStorage.setItem('bot4vps_group_order', JSON.stringify(order));
      }
    }
  } catch (_) {}
}


async function saveGroupRow(row) {
  const oldName = row.dataset.name;
  const newName = (row.querySelector('.grp-name').value || '').trim();
  const ssl = row.querySelector('.grp-ssl-cb').checked;
  if (!newName) { toast('Название пустое', false); return; }
  try {
    const body = { ssl_monitor: ssl };
    if (newName !== oldName) body.name = newName;
    await j(`/api/groups/${encodeURIComponent(oldName)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    toast('Группа сохранена', true);
    await refreshAfterGroupMutation({
      oldName,
      newName: newName !== oldName ? newName : null,
    });
  } catch (e) {
    toast(e.message || String(e), false);
  }
}

async function deleteGroupRow(row) {
  const name = row.dataset.name;
  if (!await confirmAction({ message: `Удалить группу «${name}»?` })) return;
  try {
    await j(`/api/groups/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast('Группа удалена', true);
    await refreshAfterGroupMutation({ deletedName: name });
  } catch (e) {
    const message = e.message || String(e);
    toast(message.includes('перемест')
      ? message
      : `${message}. Сначала переместите серверы в другую группу.`, false);
  }
}

async function createGroup() {
  const name = (document.getElementById('grp-new-name').value || '').trim();
  const ssl = !!document.getElementById('grp-new-ssl')?.checked;
  if (!name) { toast('Введите название', false); return; }
  try {
    await j('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ssl_monitor: ssl }),
    });
    const inp = document.getElementById('grp-new-name');
    if (inp) inp.value = '';
    const cb = document.getElementById('grp-new-ssl');
    if (cb) cb.checked = false;
    toast('Группа создана', true);
    await refreshAfterGroupMutation({ createdName: name });
  } catch (e) {
    toast(e.message || String(e), false);
  }
}

// ---------------- Настройка отображения меню серверов ----------------
let draggedElement = null;

export async function loadGroupsDisplayOrder() {
  const box = document.getElementById('groups-display-list');
  if (!box) return;

  box.innerHTML = '<div class="acc-note">Загрузка…</div>';

  try {
    const data = await j('/api/groups');
    const groups = Array.isArray(data?.groups) ? data.groups : [];

    if (!groups.length) {
      box.innerHTML = '<div class="acc-note">Групп пока нет</div>';
      return;
    }

    // Получаем сохранённые настройки
    let savedOrder = [];
    let visibleGroups = null;
    try {
      const orderStr = localStorage.getItem('bot4vps_group_order');
      const visibleStr = localStorage.getItem('bot4vps_visible_groups');
      if (orderStr) savedOrder = JSON.parse(orderStr);
      if (visibleStr) visibleGroups = new Set(JSON.parse(visibleStr));
    } catch (_) {}

    // Формируем список групп с учётом сохранённого порядка
    const groupNames = groups.map(g => (g && g.name) != null ? String(g.name) : String(g));
    let orderedNames = [];

    savedOrder.forEach(name => {
      if (groupNames.includes(name)) orderedNames.push(name);
    });

    groupNames.forEach(name => {
      if (!orderedNames.includes(name)) orderedNames.push(name);
    });

    // Если нет сохранённых настроек видимости, все группы видимы по умолчанию
    if (!visibleGroups) {
      visibleGroups = new Set(orderedNames);
    }

    box.innerHTML = orderedNames.map(name => {
      const isVisible = visibleGroups.has(name);
      return `<div class="group-display-row" draggable="true" data-name="${esc(name)}">
        <span class="drag-handle">☰</span>
        <label class="group-display-label">
          <input type="checkbox" class="group-visible-cb" ${isVisible ? 'checked' : ''}/>
          <span>${esc(name)}</span>
        </label>
      </div>`;
    }).join('');

    // Обработчики изменения видимости
    box.querySelectorAll('.group-visible-cb').forEach(cb => {
      cb.addEventListener('change', saveGroupsDisplaySettings);
    });

  } catch (e) {
    box.innerHTML = `<div class="acc-note" style="color:var(--err)">Ошибка: ${esc(e.message || e)}</div>`;
  }
}

function bindGroupsDisplayOrder() {
  const box = document.getElementById('groups-display-list');
  if (!box || box.dataset.dragBound) return;
  box.dataset.dragBound = '1';

  box.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.group-display-row');
    if (row) {
      draggedElement = row;
      row.classList.add('dragging');
    }
  });

  box.addEventListener('dragend', (e) => {
    const row = e.target.closest('.group-display-row');
    if (row) {
      row.classList.remove('dragging');
      draggedElement = null;
      saveGroupsDisplaySettings();
    }
  });

  box.addEventListener('dragover', (e) => {
    e.preventDefault();
    const afterElement = getDragAfterElement(box, e.clientY);
    if (afterElement == null) {
      box.appendChild(draggedElement);
    } else {
      box.insertBefore(draggedElement, afterElement);
    }
  });
}

function getDragAfterElement(container, y) {
  const draggableElements = [...container.querySelectorAll('.group-display-row:not(.dragging)')];

  return draggableElements.reduce((closest, child) => {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;

    if (offset < 0 && offset > closest.offset) {
      return { offset: offset, element: child };
    } else {
      return closest;
    }
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function saveGroupsDisplaySettings() {
  const box = document.getElementById('groups-display-list');
  if (!box) return;

  const rows = box.querySelectorAll('.group-display-row');
  const order = [];
  const visible = [];

  rows.forEach(row => {
    const name = row.dataset.name;
    order.push(name);
    const cb = row.querySelector('.group-visible-cb');
    if (cb && cb.checked) visible.push(name);
  });

  try {
    localStorage.setItem('bot4vps_group_order', JSON.stringify(order));
    localStorage.setItem('bot4vps_visible_groups', JSON.stringify(visible));

    // Обновляем отображение серверов, если страница серверов открыта
    if (window.renderServers && typeof window.renderServers === 'function') {
      window.renderServers();
    }
    // Альтернативно через импорт, если доступен.
    // Спецификатор сверить с app.js — тот же ?v=, иначе второй инстанс модуля.
    import(`./servers.js?v=20260913-hostkey-v2`).then(m => m.renderServers()).catch(() => {});
  } catch (e) {
    console.error('Failed to save group display settings', e);
  }
}

// ---------------- Биндинг (один раз при загрузке приложения) ----------------
export function bindGroupsPanelUI() {
  const box = document.getElementById('groups-list');
  if (box && !box.dataset.bound) {
    box.dataset.bound = '1';
    box.addEventListener('click', (ev) => {
      const row = ev.target.closest('.group-row');
      if (!row) return;
      if (ev.target.closest('.grp-save')) saveGroupRow(row);
      if (ev.target.closest('.grp-del')) deleteGroupRow(row);
    });
  }
  const btn = document.getElementById('grp-create');
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = '1';
    btn.addEventListener('click', createGroup);
  }
  const close = document.getElementById('groups-panel-close');
  if (close && !close.dataset.bound) {
    close.dataset.bound = '1';
    close.addEventListener('click', closeGroupsPanel);
  }
  bindGroupsDisplayOrder();
}
