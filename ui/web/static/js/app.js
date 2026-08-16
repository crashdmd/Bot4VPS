import { tickClock, showPage, toast, parseEmoji, initEmojiObserver, confirmAction } from './ui.js';
import { loadDashboard, loadSummary, bindDashboard, stopDashMetrics, updateDashboardData } from './dashboard.js?v=20260816-server-singleton-v1';
import { loadEvents, openEventDetail, applyEventsSnapshot, initSystemMonitor, stopSystemMonitor } from './monitor.js?v=20260816-task-history-v3';
import { loadServers, loadQueues, loadHistory, loadGroupsAndKeys,
  bindServerUI, stopWatchers, openServer, lastServerTab,
} from './servers.js?v=20260816-task-history-v3';
import { loadScripts, bindScriptsUI } from './scripts.js?v=20260816-server-singleton-v1';
import { loadWireguard, bindWireguardUI, stopWgTimers, openWgServerById } from './wireguard.js?v=20260816-service-singleton-v1';
import { loadDocker, bindDockerUI, stopDockerTimers, openDockerServerById } from './docker.js?v=20260816-service-singleton-v1';
import { bindTasksUI } from './tasks.js?v=20260816-task-history-v3';
import { loadFiles, bindFilesUI } from './files.js?v=20260816-service-singleton-v1';
import { bindEditorUI } from './editor.js?v=20260815-scripts-table-v1';
import { bindTerminalUI, closeTerminal } from './terminal.js';
import { bindSettingsUI, loadAccount, loadTelegramSettings, loadGroupsAdmin, initTheme } from './settings.js?v=20260816-server-singleton-v1';
import { startSSE, registerNotificationsRefresh } from './sse.js?v=20260816-task-history-v3';
import { state, setPage } from './state.js';
import { j } from './api.js';
import { initAuth, bindAuthUI } from './auth.js';
import { bindGlobalSearch } from './search.js?v=20260816-server-singleton-v1';

async function refreshAll() {
  await Promise.all([
    loadDashboard(),
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
  if (page !== 'server' && page !== 'terminal') closeTerminal();
  if (page !== 'wireguard' && page !== 'wireguard-server') stopWgTimers();
  if (page !== 'docker' && page !== 'docker-server') stopDockerTimers();
  if (page !== 'dashboard') stopDashMetrics();
  if (page !== 'monitor') stopSystemMonitor();
  showPage(page);
  if (page === 'dashboard') loadDashboard();
  if (page === 'events') loadEvents();
  if (page === 'servers') loadServers();
  if (page === 'scripts') loadScripts();
  if (page === 'wireguard') loadWireguard();
  if (page === 'docker') loadDocker();
  if (page === 'files') loadFiles();
  if (page === 'queues') { loadQueues(); loadHistory(); }
  if (page === 'monitor') { loadDashboard(); initSystemMonitor(); }
  if (page === 'settings') {
    loadAccount();
    loadTelegramSettings().catch(e => console.warn('[settings] telegram status', e));
    loadGroupsAdmin();
  }
}

// Мобильное меню (боковой дрэвер ≤640px)
const side = document.querySelector('.side');
const backdrop = document.getElementById('nav-backdrop');
const closeDrawer = () => {
  side?.classList.remove('open');
  backdrop?.classList.remove('open');
  document.body.classList.remove('menu-open');
};

document.querySelectorAll('.side [data-page]').forEach(b => {
  b.addEventListener('click', () => { onNav(b.dataset.page); closeDrawer(); });
});

document.querySelectorAll('.side .nav-group-head').forEach(b => {
  b.addEventListener('click', () => b.closest('.nav-group')?.classList.toggle('open'));
});

// Счётчик серверов в хедере ведёт на страницу «Серверы»
document.getElementById('header-servers-link')?.addEventListener('click', () => {
  onNav('servers');
});

document.getElementById('nav-toggle')?.addEventListener('click', () => {
  const open = side?.classList.toggle('open');
  backdrop?.classList.toggle('open', !!open);
  document.body.classList.toggle('menu-open', !!open);
});
backdrop?.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

document.getElementById('btn-events-mark-read')?.addEventListener('click', () => {
  markAllNotificationsRead();
});
document.getElementById('btn-journal')?.addEventListener('click', () => loadEvents(100)); // expanded
document.getElementById('btn-events-clear')?.addEventListener('click', async () => {
  if (!await confirmAction({
    message: 'Очистить журнал событий?',
    confirmFirst: true,
  })) return;
  try {
    await j('/api/events', { method: 'DELETE' });
    toast('Очищено', true);
    loadEvents(5);
  } catch (e) { toast(e.message, false); }
});

bindDashboard();
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
bindGlobalSearch();

// Инициализация темы
initTheme();

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

async function loadVersion() {
  try {
    const ping = await j('/api/ping');
    const versionInfo = document.getElementById('version-info');
    if (versionInfo && ping.version) versionInfo.textContent = `v${ping.version}`;
  } catch (err) {
    console.warn('Failed to load application version:', err);
  }
}

async function boot() {
  // Авторизация выключена (локальный режим) → initAuth сразу вернёт true.
  // Иначе при отсутствии сессии покажется оверлей логина, boot остановится,
  // а после входа страница перезагрузится и boot дойдёт до конца.
  if (!(await initAuth())) return;
  await loadVersion();

  // Проверяем авторизацию и отображаем профиль если нужно
  try {
    const me = await j('/api/me');
    const profileBtn = document.getElementById('profile-btn');
    const profileName = document.getElementById('profile-name');
    const profileWrap = document.getElementById('profile-wrap');
    if (me.auth_enabled && me.user) {
      if (profileWrap) profileWrap.style.display = 'block';
      if (profileBtn) profileBtn.style.display = 'flex';
      if (profileName) profileName.textContent = me.user.charAt(0).toUpperCase();
    } else {
      if (profileWrap) profileWrap.style.display = 'none';
    }
  } catch (_) {
    const profileWrap = document.getElementById('profile-wrap');
    if (profileWrap) profileWrap.style.display = 'none';
  }

  // Инициализация выпадающего меню уведомлений
  initNotificationsDropdown();
  registerNotificationsRefresh(refreshOpenNotificationsDropdown);
  initProfileMenu();


  // Загружаем данные для хедера при старте
  loadHeaderData();

  setInterval(tickClock, 1000);
  tickClock();
  startSSE();
  await restoreSession();
  // Если восстановили «Настройки» — статус Telegram мог не успеть/не отрисоваться
  try {
    if ((localStorage.getItem('bot4vps_page') || '') === 'settings'
        || document.getElementById('page-settings')?.classList.contains('on')) {
      await loadTelegramSettings();
    }
  } catch (e) { console.warn('[boot] telegram status', e); }


  // Инициализируем глобальный наблюдатель за эмодзи
  initEmojiObserver();
  // Парсим существующий контент
  parseEmoji();

  // Обновление данных хедера каждые 3 секунды
  setInterval(loadHeaderData, 3000);

  // Обновление виджета "Система" на дашборде каждые 3 секунды
  setInterval(() => {
    if (state.page === 'dashboard') {
      updateDashboardData();
    }
  }, 3000);

  // Fallback polling — реже, если SSE жив
  setInterval(() => {
    if (state.sseConnected) {
      // только тяжёлое, чего нет в snapshot
      if (state.page === 'queues') loadQueues();
      return;
    }
    loadSummary();
    loadHeaderData(); // обновляем хедер
    if (state.page === 'servers') loadServers();
    if (state.page === 'queues') { loadQueues(); loadHistory(); }
  }, 8000);
}

// Инициализация выпадающего меню уведомлений

function initProfileMenu() {
  const btn = document.getElementById('profile-btn');
  const menu = document.getElementById('profile-menu');
  const wrap = document.getElementById('profile-wrap');
  if (!btn || !menu) return;

  const close = () => menu.classList.remove('show');
  const toggle = (e) => {
    e.stopPropagation();
    menu.classList.toggle('show');
  };
  btn.addEventListener('click', toggle);
  btn.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(e); }
  });
  document.addEventListener('click', e => {
    if (!wrap?.contains(e.target)) close();
  });
  document.getElementById('profile-menu-settings')?.addEventListener('click', e => {
    e.stopPropagation();
    close();
    onNav('settings');
  });
  document.getElementById('profile-menu-logout')?.addEventListener('click', async e => {
    e.stopPropagation();
    close();
    try {
      await j('/api/logout', { method: 'POST' });
    } catch (_) {}
    location.reload();
  });
}

function initNotificationsDropdown() {
  const btn = document.getElementById('notifications-btn');
  const dropdown = document.getElementById('notifications-dropdown');
  if (!btn || !dropdown) return;

  // Вставляем SVG иконку колокольчика (сохраняем бейдж)
  const badge = btn.querySelector('.badge');

  // Определяем цвет stroke в зависимости от темы
  const isDark = !document.documentElement.hasAttribute('data-theme');
  const strokeColor = isDark ? '#ffffff' : '#1a1a1a';

  btn.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
    <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
  </svg>`;
  if (badge) btn.appendChild(badge);

  // Закрытие при клике вне меню
  document.addEventListener('click', (e) => {
    if (!btn.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.classList.remove('show');
    }
  });

  // Открытие/закрытие меню
  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const isOpen = dropdown.classList.toggle('show');
    if (isOpen) {
      await loadNotificationsDropdown();
    }
  });

  // Любое событие, помеченное прочитанным (в журнале, на дашборде или
  // здесь), должно сразу отражаться на бейдже
  window.addEventListener('event-read', () => {
    loadHeaderData();
    if (dropdown.classList.contains('show')) loadNotificationsDropdown();
  });
}

// SSE вызывает этот helper после snapshot событий. Закрытый dropdown не
// трогаем; открытый обновляем через уже существующий загрузчик.
export function refreshOpenNotificationsDropdown() {
  const dropdown = document.getElementById('notifications-dropdown');
  if (dropdown?.classList.contains('show')) loadNotificationsDropdown();
}

// Загрузка данных для выпадающего меню
async function loadNotificationsDropdown() {
  try {
    // Загружаем непрочитанные уведомления (события)
    // limit=100 — столько же, сколько держит журнал (core MAX_EVENTS),
    // иначе бейдж и «Очистить» считают только по первым 25
    const eventsResponse = await j('/api/events?limit=100');
    const events = Array.isArray(eventsResponse) ? eventsResponse : (eventsResponse?.events || []);

    // Синхронизируем события с кэшом monitor.js
    applyEventsSnapshot(events);

    const allUnread = events.filter(e => !e.read);
    const unread = allUnread.slice(0, 5);   // в списке показываем 5 свежих

    const list = document.getElementById('notif-list');
    if (unread.length === 0) {
      list.innerHTML = '<div class="dropdown-empty">Нет новых уведомлений</div>';
    } else {
      list.innerHTML = unread.map(e => `
        <div class="dropdown-item" data-event-id="${e.id}">
          <div class="dropdown-item-icon"></div>
          <div class="dropdown-item-content">
            <div class="dropdown-item-title">${e.title || 'Уведомление'}</div>
            <div class="dropdown-item-text">${e.message || ''}</div>
          </div>
        </div>
      `).join('');

      // Добавляем обработчики кликов (теперь передаём ID)
      list.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', e => {
          e.stopPropagation();
          notificationClick(item.dataset.eventId);
        });
      });

      // Действие относится ко всем непрочитанным, а не только к показанной
      // пятёрке. Сами события остаются в журнале.
      const markReadBtn = document.createElement('button');
      markReadBtn.className = 'dropdown-btn';
      markReadBtn.textContent = '✓ Пометить все как прочитанные';
      markReadBtn.addEventListener('click', e => {
        e.stopPropagation();
        markAllNotificationsRead(allUnread);
      });
      list.appendChild(markReadBtn);
    }

    // Обновляем бейдж с количеством непрочитанных
    const badge = document.getElementById('notif-badge');
    if (badge) {
      if (allUnread.length > 0) {
        badge.textContent = String(allUnread.length);
        badge.style.display = 'flex';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch (err) {
    console.error('Failed to load notifications dropdown:', err);
  }
}

// Клик по уведомлению — открываем ту же карточку, что и в журнале.
// Пометку прочитанным делает сам openEventDetail, а обновление
// бейджа прилетит через событие 'event-read'.
function notificationClick(eventId) {
  if (!eventId) return;
  openEventDetail(eventId);
  document.getElementById('notifications-dropdown')?.classList.remove('show');
}

// Массовая отметка прочитанными. API принимает один event_id, поэтому
// сохраняем существующую пакетную отправку, но локальный UI меняем только
// после успешного завершения всех запросов.
async function markAllNotificationsRead(unreadEvents) {
  try {
    let events = Array.isArray(unreadEvents) ? unreadEvents : null;
    if (!events) {
      const response = await j('/api/events?limit=100');
      const snapshot = Array.isArray(response) ? response : (response?.events || []);
      applyEventsSnapshot(snapshot);
      events = snapshot.filter(event => !event.read);
    }

    const ids = events.map(event => event.id).filter(id => id != null);
    const markRead = id => j('/api/events/mark-read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: id }),
    });
    for (let i = 0; i < ids.length; i += 10) {
      await Promise.all(ids.slice(i, i + 10).map(markRead));
    }

    applyEventsSnapshot(events.map(event => ({ ...event, read: true })));
    await loadHeaderData();
    const dropdown = document.getElementById('notifications-dropdown');
    if (dropdown?.classList.contains('show')) await loadNotificationsDropdown();
  } catch (err) {
    console.error('Failed to mark all notifications as read:', err);
    toast(err.message, false);
  }
}

// Обновление элементов статуса в хедере
function updateHeaderStatus(summary) {
  // Счетчик серверов - используем реальные данные из API
  const totalCount = summary.servers || 0;
  const serversCountEl = document.getElementById('header-servers-count');
  if (serversCountEl) {
    // Правильное склонение: 1 сервер, 2-4 сервера, 5+ серверов
    let word = 'серверов';
    if (totalCount % 10 === 1 && totalCount % 100 !== 11) {
      word = 'сервер';
    } else if ([2, 3, 4].includes(totalCount % 10) && ![12, 13, 14].includes(totalCount % 100)) {
      word = 'сервера';
    }
    serversCountEl.textContent = `${totalCount} ${word}`;
  }

  // Статус системы - просто показываем что работает
  const dotEl = document.getElementById('header-system-dot');
  const statusEl = document.getElementById('header-system-status');
  if (dotEl) {
    dotEl.className = 'dropdown-status-dot ok';
  }
  if (statusEl) {
    statusEl.textContent = 'Система в норме';
  }
}

// Загрузка данных для хедера
async function loadHeaderData() {
  try {
    const summary = await j('/api/summary');
    updateHeaderStatus(summary);

    // Обновляем бейдж уведомлений (limit как в дропдауне — иначе счёт разойдётся)
    const eventsResponse = await j('/api/events?limit=100');
    const events = Array.isArray(eventsResponse) ? eventsResponse : (eventsResponse?.events || []);

    // Синхронизируем события с кэшом monitor.js
    applyEventsSnapshot(events);

    const totalUnread = events.filter(e => !e.read).length;
    const badge = document.getElementById('notif-badge');
    if (badge) {
      if (totalUnread > 0) {
        badge.textContent = String(totalUnread);
        badge.style.display = 'flex';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch (err) {
    console.error('Failed to load header data:', err);
  }
}

boot();
