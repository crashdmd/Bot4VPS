/**
 * Единое состояние Web UI.
 */
export const state = {
  servers: [],
  groups: [],
  keys: [],
  scripts: [],
  openServerId: null,
  openServerData: null,
  quickSetupServerId: null,
  watchTaskId: null,
  page: 'dashboard',
  serverTab: 'status',
  serverGroupTab: '__all__',
  serverSort: { key: 'name', descending: false },
  // скрипт для запуска сразу после открытия терминала (режим «в терминале»); null — bare shell
  pendingTermScript: null,
  serverQuery: '',
  fileRoot: 'scripts',
  sseConnected: false,
};

export function setServers(list) {
  state.servers = list || [];
}
export function setGroups(list) {
  state.groups = list || [];
}
export function setKeys(list) {
  state.keys = list || [];
}
export function setScripts(list) {
  state.scripts = list || [];
}
export function setOpenServer(id, data) {
  state.openServerId = id;
  if (arguments.length > 1) state.openServerData = data;
  try {
    if (id) {
      localStorage.setItem('bot4vps_server_id', id);
      localStorage.setItem('bot4vps_page', 'server');
    } else {
      localStorage.removeItem('bot4vps_server_id');
    }
  } catch (_) {}
}
export function setQuickSetupServer(id) {
  const normalized = id == null ? null : String(id).trim();
  state.quickSetupServerId = normalized || null;
  try {
    if (state.quickSetupServerId) {
      localStorage.setItem('bot4vps_quick_setup_server_id', state.quickSetupServerId);
      localStorage.setItem('bot4vps_page', 'quick-setup');
    } else {
      localStorage.removeItem('bot4vps_quick_setup_server_id');
    }
  } catch (_) {}
}

export function clearQuickSetupServer() {
  state.quickSetupServerId = null;
  try { localStorage.removeItem('bot4vps_quick_setup_server_id'); } catch (_) {}
}

export function setPage(page) {
  state.page = page;
  try { localStorage.setItem('bot4vps_page', page); } catch (_) {}
}
export function setServerTab(tab) {
  state.serverTab = tab;
  try { localStorage.setItem('bot4vps_server_tab', tab); } catch (_) {}
}

export function setServerGroupTab(tab) {
  state.serverGroupTab = tab || '__all__';
}

export function setServerSort(key, descending = false) {
  state.serverSort = { key, descending: !!descending };
}

export function setServerQuery(query) {
  state.serverQuery = String(query || '');
}
