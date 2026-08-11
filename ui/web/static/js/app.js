import { tickClock, showPage, toast } from './ui.js';
import { loadSummary } from './dashboard.js';
import { loadEvents } from './monitor.js';
import {
  loadServers, loadQueues, loadHistory, loadGroupsAndKeys,
  bindServerUI, stopWatchers, openServer, lastServerTab,
} from './servers.js';
import { loadScripts, bindScriptsUI } from './scripts.js';
import { loadWireguard, bindWireguardUI, stopWgTimers, openWgServerById } from './wireguard.js';
import { loadDocker, bindDockerUI, stopDockerTimers, openDockerServerById } from './docker.js';
import { bindTasksUI } from './tasks.js';
import { loadFiles, bindFilesUI } from './files.js';
import { bindEditorUI } from './editor.js';
import { bindTerminalUI } from './terminal.js';
import { bindSettingsUI, loadAccount, loadGroupsAdmin } from './settings.js';
import { startSSE } from './sse.js';
import { state, setPage } from './state.js';
import { j } from './api.js';
import { initAuth, bindAuthUI } from './auth.js';

async function refreshAll() {
  await Promise.all([
    loadSummary(),
    loadServers(),
    loadQueues(),
    loadHistory(),
    loadScripts(),
    loadFiles(),
    loadEvents(state.page === 'events' ? 100 : 5),
    loadWireguard(),
    loadDocker(),
  ]);
}

function onNav(page) {
  setPage(page);
  if (page !== 'server') stopWatchers();
  if (page !== 'wireguard' && page !== 'wireguard-server') stopWgTimers();
  if (page !== 'docker' && page !== 'docker-server') stopDockerTimers();
  showPage(page);
  if (page === 'events') loadEvents(); // сохраняет текущий limit (5 или 100)
  if (page === 'servers') loadServers();
  if (page === 'scripts') loadScripts();
  if (page === 'wireguard') loadWireguard();
  if (page === 'docker') loadDocker();
  if (page === 'files') loadFiles();
  if (page === 'queues') { loadQueues(); loadHistory(); }
  if (page === 'monitor') loadSummary();
  if (page === 'settings') { loadAccount(); loadGroupsAdmin(); }
}

// Мобильное меню (боковой дрэвер ≤640px)
const side = document.querySelector('.side');
const backdrop = document.getElementById('nav-backdrop');
const closeDrawer = () => { side?.classList.remove('open'); backdrop?.classList.remove('open'); };

document.querySelectorAll('.side [data-page]').forEach(b => {
  b.addEventListener('click', () => { onNav(b.dataset.page); closeDrawer(); });
});

document.querySelectorAll('.side .nav-group-head').forEach(b => {
  b.addEventListener('click', () => b.closest('.nav-group')?.classList.toggle('open'));
});

document.getElementById('nav-toggle')?.addEventListener('click', () => {
  const open = side?.classList.toggle('open');
  backdrop?.classList.toggle('open', !!open);
});
backdrop?.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

document.getElementById('btn-journal')?.addEventListener('click', () => loadEvents(100)); // expanded
document.getElementById('btn-events-clear')?.addEventListener('click', async () => {
  if (!confirm('Очистить журнал событий?')) return;
  try {
    await j('/api/events', { method: 'DELETE' });
    toast('Очищено', true);
    loadEvents(5);
  } catch (e) { toast(e.message, false); }
});

bindServerUI();
bindScriptsUI();
bindTasksUI();
bindWireguardUI();
bindDockerUI();
bindFilesUI();
bindEditorUI();
bindTerminalUI();
bindSettingsUI();
bindAuthUI();

async function restoreSession() {
  await loadGroupsAndKeys();
  await refreshAll();

  let page = 'servers';
  let serverId = null;
  try {
    page = localStorage.getItem('bot4vps_page') || 'servers';
    serverId = localStorage.getItem('bot4vps_server_id');
  } catch (_) {}

  if (page === 'server' && serverId) {
    try {
      await openServer(serverId);
      return;
    } catch (_) {
      try {
        localStorage.removeItem('bot4vps_server_id');
        localStorage.setItem('bot4vps_page', 'servers');
      } catch (_) {}
      onNav('servers');
      return;
    }
  }

  let wgServerId = null;
  try { wgServerId = localStorage.getItem('bot4vps_wg_server_id'); } catch (_) {}
  if (page === 'wireguard-server' && wgServerId) {
    try {
      await openWgServerById(wgServerId);
      return;
    } catch (_) {
      try {
        localStorage.removeItem('bot4vps_wg_server_id');
        localStorage.setItem('bot4vps_page', 'wireguard');
      } catch (_) {}
      onNav('wireguard');
      return;
    }
  }

  let dockerServerId = null;
  try { dockerServerId = localStorage.getItem('bot4vps_docker_server_id'); } catch (_) {}
  if (page === 'docker-server' && dockerServerId) {
    try {
      await openDockerServerById(dockerServerId);
      return;
    } catch (_) {
      try {
        localStorage.removeItem('bot4vps_docker_server_id');
        localStorage.setItem('bot4vps_page', 'docker');
      } catch (_) {}
      onNav('docker');
      return;
    }
  }

  if (page && page !== 'servers' && page !== 'server'
      && page !== 'wireguard-server' && page !== 'docker-server') {
    onNav(page);
  }
}

async function boot() {
  // Авторизация выключена (локальный режим) → initAuth сразу вернёт true.
  // Иначе при отсутствии сессии покажется оверлей логина, boot остановится,
  // а после входа страница перезагрузится и boot дойдёт до конца.
  if (!(await initAuth())) return;

  setInterval(tickClock, 1000);
  tickClock();
  startSSE();
  await restoreSession();

  // Fallback polling — реже, если SSE жив
  setInterval(() => {
    if (state.sseConnected) {
      // только тяжёлое, чего нет в snapshot
      if (state.page === 'queues') loadQueues();
      return;
    }
    loadSummary();
    if (state.page === 'servers') loadServers();
    if (state.page === 'queues') loadQueues();
  }, 8000);
}

boot();
