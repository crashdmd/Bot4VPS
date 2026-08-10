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
  watchTaskId: null,
  page: 'servers',
  serverTab: 'status',
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
export function setPage(page) {
  state.page = page;
  try { localStorage.setItem('bot4vps_page', page); } catch (_) {}
}
export function setServerTab(tab) {
  state.serverTab = tab;
  try { localStorage.setItem('bot4vps_server_tab', tab); } catch (_) {}
}
