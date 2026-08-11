import { j, esc } from './api.js';
import { ansiToHtml } from './ansi.js';
import { toast, showPage, onlineBadge, sslBadge, metricTile, bindPasswordToggles } from './ui.js';
import { state, setServers, setGroups, setKeys, setOpenServer, setPage, setServerTab } from './state.js';
import { openTerminal, closeTerminal } from './terminal.js';
import { openTaskLog, cancelTaskAPI } from './tasks.js';

/** @deprecated use state.servers */
export let lastServers = state.servers;
export let lastGroups = state.groups;
export let lastKeys = state.keys;
export let openServerId = null;
export let watchTaskId = null;
let metricsTimer = null;
let logTimer = null;

export async function loadGroupsAndKeys() {
  try { setGroups((await j('/api/groups')).groups || []); } catch { setGroups([]); }
  try { setKeys((await j('/api/keys')).keys || []); } catch { setKeys([]); }
  lastGroups = state.groups;
  lastKeys = state.keys;
}

export async function loadServers() {
  try {
    const data = await j('/api/servers');
    setServers(data.servers || []);
    lastServers = state.servers;
    renderServers();
  } catch (e) {
    document.getElementById('servers').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function filteredServers() {
  const q = (state.serverQuery || '').trim().toLowerCase();
  const list = state.servers;
  if (!q) return list;
  return list.filter(s => {
    const blob = [s.name, s.host, s.group, s.user, s.id].map(x => String(x || '').toLowerCase()).join(' ');
    return q.split(/\s+/).every(part => blob.includes(part));
  });
}

export function renderServersFromState() { renderServers(); }

export function renderServers() {
  const el = document.getElementById('servers');
  const list = filteredServers();
  const hint = document.getElementById('server-search-hint');
  if (hint) hint.textContent = state.serverQuery.trim() ? `${list.length} из ${state.servers.length}` : '';
  if (!state.servers.length) { el.innerHTML = '<div class="empty">Нет серверов</div>'; return; }
  if (!list.length) { el.innerHTML = '<div class="empty">Ничего не найдено</div>'; return; }
  const by = {};
  list.forEach(s => { const g = s.group || '(без группы)'; (by[g] = by[g] || []).push(s); });
  let h = '';
  Object.keys(by).sort().forEach(g => {
    h += `<div class="group-title">${esc(g)} · ${by[g].length}</div><div class="grid">`;
    h += by[g].map(s => `<div class="card clickable" data-sid="${esc(s.id)}">
      <span class="ping" id="ping-${esc(s.id)}">…</span>
      <h3>${esc(s.name)}</h3>
      <div class="row">${esc(s.host || '—')}</div>
      <div class="row" style="margin-top:.4rem">${onlineBadge(s.online)}</div>
      ${s.certificate_check ? `<div class="row">${sslBadge(s)}</div>` : ''}
      ${s.has_running ? '<div class="row">▶ идёт задача</div>' : ''}
    </div>`).join('');
    h += '</div>';
  });
  el.innerHTML = h;
  el.querySelectorAll('[data-sid]').forEach(c => c.onclick = () => openServer(c.dataset.sid));
  list.forEach(s => fillPing(s.id));
}

async function fillPing(id) {
  const el = document.getElementById('ping-' + id);
  if (!el) return;
  try {
    const r = await j('/api/servers/' + encodeURIComponent(id) + '/ping');
    if (r.ok) { el.textContent = r.ms + ' ms'; el.className = 'ping ok'; }
    else { el.textContent = 'timeout'; el.className = 'ping bad'; }
  } catch { el.textContent = '—'; el.className = 'ping'; }
}

export function setServerQuery(q) {
  state.serverQuery = q;
  renderServers();
}

export function stopWatchers() {
  if (metricsTimer) { clearInterval(metricsTimer); metricsTimer = null; }
  if (logTimer) { clearInterval(logTimer); logTimer = null; }
  closeTerminal();
}

function startWatchers() {
  stopWatchers();
  refreshMetrics();
  metricsTimer = setInterval(refreshMetrics, 5000);
  logTimer = setInterval(() => {
    const log = document.getElementById('tab-log');
    if (log && !log.classList.contains('hidden')) refreshTaskLog();
  }, 1500);
}

export async function openServer(id) {
  openServerId = id;
  setOpenServer(id, null);
  try {
    const data = await j('/api/servers/' + encodeURIComponent(id));
    const s = data.server || {}, mon = data.monitor || {};
    const avail = mon.availability || {}, cert = mon.certificate || {};
    state.openServerData = data; window._openServerData = data;
    document.getElementById('srv-title').textContent = s.name || id;
    document.getElementById('srv-kv').innerHTML = `
      <dt>Host</dt><dd>${esc(s.host)}:${esc(s.port || 22)}</dd>
      <dt>User</dt><dd>${esc(s.user)} · ${esc(s.auth_type)}</dd>
      <dt>Группа</dt><dd>${esc(s.group)}</dd>
      <dt>Online</dt><dd>${avail.online === true ? '🟢 да' : avail.online === false ? '🔴 нет' : '—'} ${esc(avail.checked || '')}</dd>
      <dt>SSL</dt><dd>${s.certificate_check ? esc(cert.status || '—') + (cert.days_left != null ? ' · ' + cert.days_left + ' дн.' : '') : 'выкл'}</dd>`;
    const act = document.getElementById('srv-actions');
    act.innerHTML = '';
    const add = (t, cls, fn) => {
      const b = document.createElement('button');
      b.textContent = t; if (cls) b.className = cls; b.onclick = fn; act.appendChild(b);
    };
    add('▶ Скрипт', '', () => import('./scripts.js').then(m => m.openRunModal(id, null)));
    add('Reboot', 'danger', async () => {
      if (!confirm('Reboot?')) return;
      try {
        const r = await j('/api/servers/' + encodeURIComponent(id) + '/reboot', { method: 'POST' });
        toast(r.ok ? 'reboot' : 'fail', r.ok);
      } catch (e) { toast(e.message, false); }
    });
    if (data.running_task) { watchTaskId = data.running_task.id; state.watchTaskId = watchTaskId; }
    await loadGroupsAndKeys();
    showPage('server');
    showTab(lastServerTab());
    startWatchers();
  } catch (e) { toast(e.message, false); }
}

const VALID_TABS = ['status', 'settings', 'terminal', 'log', 'queue'];

export function showTab(tab) {
  if (!VALID_TABS.includes(tab)) tab = 'status';
  setServerTab(tab);
  document.querySelectorAll('#srv-tabs [data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  VALID_TABS.forEach(t => {
    const el = document.getElementById('tab-' + t);
    if (el) el.classList.toggle('hidden', t !== tab);
  });
  if (tab === 'settings') fillSettingsForm();
  if (tab === 'log') refreshTaskLog();
  if (tab === 'queue') loadSrvQueue();
  if (tab === 'terminal') openTerminal();
  else closeTerminal();
}

export function lastServerTab() {
  try {
    const t = localStorage.getItem('bot4vps_server_tab') || state.serverTab;
    return VALID_TABS.includes(t) ? t : 'status';
  } catch (_) {
    return 'status';
  }
}

function metricsNA(reason) {
  const box = document.getElementById('srv-metrics');
  const st = document.getElementById('srv-metrics-st');
  if (box) box.innerHTML =
    metricTile('CPU', 'N/A', null) +
    metricTile('RAM', 'N/A', null) +
    metricTile('Disk', 'N/A', null) +
    metricTile('Load', 'N/A', null) +
    metricTile('Uptime', 'N/A', null);
  if (st) st.textContent = reason || 'недоступно';
}

export async function refreshMetrics() {
  if (!openServerId) return;
  const st = document.getElementById('srv-metrics-st');
  const box = document.getElementById('srv-metrics');
  try {
    const m = await j('/api/servers/' + encodeURIComponent(openServerId) + '/metrics');
    if (!m.ok) {
      metricsNA(m.error || 'SSH недоступен');
      return;
    }
    // если все null/пусто — тоже N/A
    const empty = m.cpu == null && m.ram_pct == null && m.disk_pct == null
      && (!m.load || m.load === 'N/A') && (!m.uptime || m.uptime === 'N/A');
    if (empty) {
      metricsNA('нет данных');
      return;
    }
    if (st) st.textContent = 'Обновлено';
    if (box) box.innerHTML =
      metricTile('CPU', m.cpu != null ? m.cpu + '%' : 'N/A', m.cpu) +
      metricTile('RAM', m.ram_pct != null ? m.ram_pct + '%' : 'N/A', m.ram_pct) +
      metricTile('Disk', m.disk_pct != null ? m.disk_pct + '%' : 'N/A', m.disk_pct) +
      metricTile('Load', (m.load && m.load !== 'N/A') ? m.load : 'N/A', null) +
      metricTile('Uptime', (m.uptime && m.uptime !== 'N/A') ? m.uptime : 'N/A', null);
  } catch (e) {
    metricsNA(e.message || 'ошибка');
  }
}

export async function refreshTaskLog() {
  const box = document.getElementById('task-log');
  if (!box) return;
  if (!watchTaskId && openServerId) {
    try {
      const d = await j('/api/servers/' + encodeURIComponent(openServerId));
      if (d.running_task) watchTaskId = d.running_task.id;
    } catch {}
  }
  if (!watchTaskId) { box.textContent = 'Нет активной задачи'; return; }
  try {
    const t = await j('/api/tasks/' + encodeURIComponent(watchTaskId));
    const lines = t.output_lines || [];
    const head = `${esc(t.emoji || '')} ${esc(t.name)} · ${esc(t.status)} · ${esc(t.duration || '')}`;
    const body = lines.length ? lines.map(ansiToHtml).join('\n') : esc('(нет вывода)');
    box.innerHTML = `<div class="tasklog-head">${head}</div><div class="tasklog-body">${'─'.repeat(36)}\n${body}</div>`;
    box.scrollTop = box.scrollHeight;
  } catch (e) { box.textContent = e.message; }
}

async function loadSrvQueue() {
  if (!openServerId) return;
  try {
    const d = await j('/api/servers/' + encodeURIComponent(openServerId));
    const el = document.getElementById('srv-queue');
    const run = d.running_task, q = d.queue || [], st = d.queue_state || {};
    el.innerHTML = `<div class="card" style="min-height:0">
      <div class="row">${run ? esc(run.emoji || '') + ' <b>' + esc(run.name) + '</b>' : 'Нет активной'}</div>
      <div class="progress ${st.paused ? 'paused' : ''}"><i></i></div>
      ${q.map(t => `<div class="row">⏳ ${esc(t.name)}</div>`).join('') || '<div class="row">очередь пуста</div>'}
      <div class="actions">
        <button type="button" class="secondary" data-a="continue">▶</button>
        <button type="button" class="secondary" data-a="retry">🔄</button>
        <button type="button" class="secondary" data-a="clear">⏹</button>
      </div></div>`;
    el.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => {
      try {
        await j('/api/queues/' + encodeURIComponent(openServerId) + '/' + b.dataset.a, { method: 'POST' });
        loadSrvQueue();
      } catch (e) { toast(e.message, false); }
    });
  } catch (e) {
    document.getElementById('srv-queue').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

export async function loadQueues() {
  try {
    const data = await j('/api/queues');
    const el = document.getElementById('queues');
    if (!data.queues.length) { el.innerHTML = '<div class="empty">Нет активных</div>'; return; }
    el.innerHTML = data.queues.map(q => {
      const run = q.running;
      const runningCard = run ? `<div class="card" style="margin-bottom:.5rem;min-height:0;background:var(--hover)">
        <h4 style="margin:0 0 .3rem">${esc(run.emoji || '')} ${esc(run.name)}</h4>
        <div class="row" style="color:var(--muted);font-size:.82rem">⏳ выполняется</div>
        <div class="actions" style="margin-top:.5rem">
          <button type="button" class="secondary" data-task-log="${esc(run.id)}" style="font-size:.8rem">📄 Лог</button>
          <button type="button" class="danger" data-task-cancel="${esc(run.id)}" style="font-size:.8rem">✕ Отменить</button>
        </div>
      </div>` : '';
      const queueCards = (q.queue || []).map(t => `<div class="card" style="margin-bottom:.5rem;min-height:0">
        <h4 style="margin:0 0 .3rem">${esc(t.emoji || '')} ${esc(t.name)}</h4>
        <div class="row" style="color:var(--muted);font-size:.82rem">⏸ в очереди</div>
        <div class="actions" style="margin-top:.5rem">
          <button type="button" class="danger" data-task-cancel="${esc(t.id)}" style="font-size:.8rem">✕ Отменить</button>
        </div>
      </div>`).join('');
      return `<div class="card" style="margin-bottom:1rem"><h3>${esc(q.server_name)}</h3>
        <div class="progress ${q.paused ? 'paused' : ''}"><i></i></div>
        ${runningCard}${queueCards}
        <div class="actions" style="margin-top:.8rem;border-top:1px solid var(--border);padding-top:.8rem">
          <button type="button" class="secondary" data-q="${esc(q.server_id)}" data-a="continue">▶ Возобновить</button>
          <button type="button" class="secondary" data-q="${esc(q.server_id)}" data-a="retry">🔄 Повтор</button>
          <button type="button" class="secondary" data-q="${esc(q.server_id)}" data-a="clear">⏹ Очистить очередь</button>
        </div></div>`;
    }).join('');
    el.querySelectorAll('[data-q]').forEach(b => b.onclick = async () => {
      try {
        await j('/api/queues/' + encodeURIComponent(b.dataset.q) + '/' + b.dataset.a, { method: 'POST' });
        loadQueues();
      } catch (e) { toast(e.message, false); }
    });
    el.querySelectorAll('[data-task-log]').forEach(b => b.onclick = () => openTaskLog(b.dataset.taskLog));
    el.querySelectorAll('[data-task-cancel]').forEach(b => b.onclick = async () => {
      // §27: для задачи в очереди отмена снимает её до старта. Для уже
      // выполняющейся отменяется ожидание — запущенная на сервере команда
      // может дойти до конца. Не обещаем пользователю большего.
      if (!(await confirm(
        'Отменить эту задачу?\n\n' +
        'Задача в очереди — не будет запущена.\n' +
        'Задача уже выполняется — Bot4VPS перестанет её ждать, но команда, ' +
        'запущенная на сервере, может завершиться сама.\n\n' +
        'Остальные задачи в очереди продолжат работу.'
      ))) return;
      try {
        await cancelTaskAPI(b.dataset.taskCancel);
        loadQueues();
      } catch (e) { toast(e.message, false); }
    });
  } catch (e) {
    document.getElementById('queues').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

export async function loadHistory() {
  try {
    const data = await j('/api/tasks/history?limit=12');
    const tasks = data.tasks || [];
    const el = document.getElementById('history');
    if (!tasks.length) { el.innerHTML = '<div class="empty">Пусто (RAM)</div>'; return; }
    el.innerHTML = tasks.map(t => `<div class="card" style="min-height:0"><h3>${esc(t.emoji || '')} ${esc(t.name)}</h3>
      <div class="row">${esc(t.status)} · ${esc(t.duration)}</div><div class="row">${esc(t.server_name)}</div></div>`).join('');
  } catch (e) {
    document.getElementById('history').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

function toggleAuthFields() {
  const isKey = document.getElementById('sf-auth').value === 'key';
  document.getElementById('sf-pass-wrap').classList.toggle('hidden', isKey);
  document.getElementById('sf-key-wrap').classList.toggle('hidden', !isKey);
}

export function fillSettingsForm() {
  const data = state.openServerData || window._openServerData;
  if (!data || !data.server) return;
  const s = data.server;
  document.getElementById('sf-name').value = s.name || '';
  document.getElementById('sf-host').value = s.host || '';
  document.getElementById('sf-port').value = s.port || 22;
  document.getElementById('sf-user').value = s.user || '';
  document.getElementById('sf-auth').value = s.auth_type || 'password';
  document.getElementById('sf-password').value = '';
  document.getElementById('sf-ssl-host').value = s.ssl_host || '';
  document.getElementById('sf-cert').checked = !!s.certificate_check;
  const gsel = document.getElementById('sf-group');
  gsel.innerHTML = state.groups.map(g =>
    `<option value="${esc(g.name)}" ${g.name === s.group ? 'selected' : ''}>${esc(g.name)}</option>`
  ).join('') || `<option value="${esc(s.group || '')}">${esc(s.group || '')}</option>`;
  const ksel = document.getElementById('sf-key');
  ksel.innerHTML = state.keys.map(k => {
    const sel = (s.key_path || '').endsWith(k.name) || s.key_path === k.path;
    return `<option value="${esc(k.path)}" ${sel ? 'selected' : ''}>${esc(k.name)}</option>`;
  }).join('') || '<option value="">— нет ключей —</option>';
  toggleAuthFields();
  bindPasswordToggles();
}

export async function saveServerSettings() {
  if (!openServerId) return;
  const body = {
    name: document.getElementById('sf-name').value.trim(),
    host: document.getElementById('sf-host').value.trim(),
    port: +document.getElementById('sf-port').value,
    user: document.getElementById('sf-user').value.trim(),
    group: document.getElementById('sf-group').value,
    auth_type: document.getElementById('sf-auth').value,
    certificate_check: document.getElementById('sf-cert').checked,
    ssl_host: document.getElementById('sf-ssl-host').value.trim() || null,
  };
  const pass = document.getElementById('sf-password').value;
  if (body.auth_type === 'password' && pass) body.password = pass;
  if (body.auth_type === 'key') body.key_path = document.getElementById('sf-key').value || null;
  try {
    await j('/api/servers/' + encodeURIComponent(openServerId), {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    toast('Сохранено', true);
    await openServer(openServerId);
    showTab('settings');  // remain on settings after save
    loadServers();
  } catch (e) { toast(e.message, false); }
}

/**
 * Тест SSH строго по полям формы (host/port/user/auth).
 * Пароль/ключ: из формы, если пусто — с сохранённого сервера (тот же id).
 * Никогда не тестирует «старый» host/port из БД, если в форме другие.
 */
export async function testServerForm() {
  if (!openServerId) {
    toast('Нет открытого сервера', false);
    return;
  }
  const auth = document.getElementById('sf-auth').value;
  const host = document.getElementById('sf-host').value.trim();
  const port = +document.getElementById('sf-port').value || 22;
  const user = document.getElementById('sf-user').value.trim();
  if (!host) { toast('Укажите host', false); return; }

  const body = {
    server_id: openServerId,
    host,
    port,
    user,
    auth_type: auth,
  };
  if (auth === 'password') {
    const pass = document.getElementById('sf-password').value;
    if (pass) body.password = pass;
  } else {
    const key_path = document.getElementById('sf-key').value || '';
    if (key_path) body.key_path = key_path;
  }

  try {
    const r = await j('/api/ssh/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const where = r.tested
      ? ` (${r.tested.host}:${r.tested.port})`
      : ` (${host}:${port})`;
    toast((r.ok ? 'SSH OK' : (r.message || 'Ошибка')) + where, r.ok);
  } catch (e) {
    toast(e.message, false);
  }
}

export async function deleteServer() {
  if (!openServerId) return;
  if (!confirm('Удалить сервер безвозвратно?')) return;
  try {
    await j('/api/servers/' + encodeURIComponent(openServerId), { method: 'DELETE' });
    toast('Удалён', true);
    openServerId = null;
    stopWatchers();
    try { localStorage.setItem('bot4vps_page', 'servers'); localStorage.removeItem('bot4vps_server_id'); } catch (_) {}
    showPage('servers');
    loadServers();
  } catch (e) { toast(e.message, false); }
}

export function openAddServerModal() {
  loadGroupsAndKeys().then(() => {
    const gsel = document.getElementById('af-group');
    gsel.innerHTML = state.groups.map(g => `<option value="${esc(g.name)}">${esc(g.name)}</option>`).join('')
      || '<option value="vps">vps</option>';
    const ksel = document.getElementById('af-key');
    ksel.innerHTML = state.keys.map(k => `<option value="${esc(k.path)}">${esc(k.name)}</option>`).join('')
      || '<option value="">—</option>';
    document.getElementById('add-server-modal').classList.add('open');
    toggleAddAuth();
    bindPasswordToggles();
  });
}

function toggleAddAuth() {
  const isKey = document.getElementById('af-auth').value === 'key';
  document.getElementById('af-pass-wrap').classList.toggle('hidden', isKey);
  document.getElementById('af-key-wrap').classList.toggle('hidden', !isKey);
}

export async function submitAddServer() {
  const body = {
    name: document.getElementById('af-name').value.trim(),
    host: document.getElementById('af-host').value.trim(),
    port: +document.getElementById('af-port').value || 22,
    user: document.getElementById('af-user').value.trim() || 'root',
    group: document.getElementById('af-group').value,
    auth_type: document.getElementById('af-auth').value,
    password: document.getElementById('af-password').value || null,
    key_path: document.getElementById('af-key').value || null,
    ssl_host: document.getElementById('af-ssl').value.trim() || null,
    certificate_check: document.getElementById('af-cert').checked,
    test: document.getElementById('af-test').checked,
  };
  if (!body.name || !body.host) { toast('Имя и host обязательны', false); return; }
  try {
    const r = await j('/api/servers', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    document.getElementById('add-server-modal').classList.remove('open');
    toast('Сервер добавлен', true);
    await loadServers();
    if (r.id) openServer(r.id);
  } catch (e) { toast(e.message, false); }
}

export function bindServerUI() {
  const search = document.getElementById('server-search');
  if (search) {
    search.addEventListener('input', () => setServerQuery(search.value));
    search.addEventListener('keydown', e => {
      if (e.key === 'Escape') { search.value = ''; setServerQuery(''); }
    });
  }
  document.getElementById('btn-add-server')?.addEventListener('click', openAddServerModal);
  document.getElementById('btn-back-servers')?.addEventListener('click', () => {
    openServerId = null; stopWatchers();
    try { localStorage.setItem('bot4vps_page', 'servers'); localStorage.removeItem('bot4vps_server_id'); } catch (_) {}
    showPage('servers');
  });
  document.getElementById('srv-tabs')?.querySelectorAll('[data-tab]').forEach(b => {
    b.addEventListener('click', () => showTab(b.dataset.tab));
  });
  document.getElementById('sf-auth')?.addEventListener('change', toggleAuthFields);
  document.getElementById('sf-save')?.addEventListener('click', saveServerSettings);
  document.getElementById('sf-test')?.addEventListener('click', testServerForm);
  document.getElementById('sf-delete')?.addEventListener('click', deleteServer);
  document.getElementById('af-auth')?.addEventListener('change', toggleAddAuth);
  document.getElementById('af-save')?.addEventListener('click', submitAddServer);
  document.getElementById('af-cancel')?.addEventListener('click', () =>
    document.getElementById('add-server-modal').classList.remove('open'));
  document.getElementById('add-server-modal')?.addEventListener('click', e => {
    if (e.target.id === 'add-server-modal') e.currentTarget.classList.remove('open');
  });
  bindPasswordToggles();
}