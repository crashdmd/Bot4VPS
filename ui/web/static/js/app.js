import { tickClock, syncServerClock, showPage, toast, parseEmoji, initEmojiObserver, confirmAction, bindTelegramHealthDialog } from './ui.js';
import { loadDashboard, loadSummary, bindDashboard, stopDashMetrics, updateDashboardData, updateDashboardState } from './dashboard.js?v=20260912-chlogwrap-v1';
import { loadEvents, openEventDetail, applyEventsSnapshot, initSystemMonitor, stopSystemMonitor } from './monitor.js?v=20260912-chlogwrap-v1';
import { loadServers, loadQueues, loadHistory, loadGroupsAndKeys,
  bindServerUI, stopWatchers, openServer, closeGroupsPanel, lastServerTab,
  startSshProbeLoop, stopSshProbeLoop,
} from './servers.js?v=20260912-chlogwrap-v1';
import { loadScripts, bindScriptsUI } from './scripts.js?v=20260826-host-timezone-v2';
import { loadWireguard, bindWireguardUI, stopWgTimers, openWgServerById } from './wireguard.js?v=20260911-tabhint-v2';
import { loadDocker, bindDockerUI, stopDockerTimers, openDockerServerById } from './docker.js?v=20260911-tabhint-v2';
import { bindTasksUI } from './tasks.js?v=20260816-task-history-v3';
import { loadFiles, bindFilesUI } from './files.js?v=20260911-tabhint-v2';
import { bindEditorUI } from './editor.js?v=20260815-scripts-table-v1';
import { bindTerminalUI, closeTerminal } from './terminal.js?v=20260905-glassblue-v2';
import { startSSE, registerNotificationsRefresh } from './sse.js?v=20260912-chlogwrap-v1';
import { state, setPage, clearQuickSetupServer } from './state.js';
import { j, esc } from './api.js';
import { initAuth, bindAuthUI } from './auth.js';
import { initSetup, bindSetupUI } from './setup.js?v=20260910-setup-v4';
import { bindGlobalSearch } from './search.js?v=20260911-nav-v6';
import { bindBackupUI, loadBackups, stopBackupTimers } from './backup.js?v=20260912-tzdrop-v1';

const QUICK_SETUP_MODULE_URL = './quick_setup.js?v=20260909-qs-ssl-v40';
const quickSetupModule = import(QUICK_SETUP_MODULE_URL).catch(error => {
  console.error('[quick-setup] module unavailable:', error);
  return null;
});

async function openQuickSetupFromCard(serverId) {
  const normalizedId = String(serverId ?? '').trim();
  if (!normalizedId) throw new Error('Сервер для настроек не выбран');

  const module = await quickSetupModule;
  if (!module?.openQuickSetup) {
    throw new Error('Модуль настроек сервера недоступен');
  }
  const opened = await module.openQuickSetup(normalizedId, {
    historyMode: 'push',
    throwOnError: true,
  });
  if (opened === false) throw new Error('Не удалось открыть настройки сервера');
  return opened;
}

// Settings — отдельная подсистема. Загружаем её лениво, чтобы ошибка нового
// модуля не останавливала Dashboard, Servers и остальные страницы.
const settingsModule = import('./settings.js?v=20260912-chlogwrap-v1')
  .catch(error => {
    console.error('[settings] module unavailable:', error);
    return null;
  });

function loadSettingsPage() {
  settingsModule.then(module => module?.loadSettings());
}

function stopSettingsPageTimers() {
  settingsModule.then(module => module?.stopSettingsTimers());
}

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

function clearQuickSetupLocation() {
  const url = new URL(window.location.href);
  if (url.searchParams.get('page') !== 'quick-setup' && !url.searchParams.has('server_id')) return;
  url.searchParams.delete('page');
  url.searchParams.delete('server_id');
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

function onNav(page) {
  if (state.page === 'quick-setup' && page !== 'quick-setup') {
    clearQuickSetupServer();
    clearQuickSetupLocation();
  }
  setPage(page);
  if (page !== 'servers') closeGroupsPanel();
  if (page !== 'server') stopWatchers();
  if (page !== 'servers') stopSshProbeLoop();
  if (page !== 'server' && page !== 'terminal') closeTerminal();
  if (page !== 'wireguard' && page !== 'wireguard-server') stopWgTimers();
  if (page !== 'docker' && page !== 'docker-server') stopDockerTimers();
  if (page !== 'dashboard') stopDashMetrics();
  if (page !== 'monitor') stopSystemMonitor();
  if (page !== 'backups') stopBackupTimers();
  if (page !== 'settings') stopSettingsPageTimers();
  showPage(page);
  if (page === 'dashboard') loadDashboard();
  if (page === 'events') loadEvents();
  if (page === 'servers') { loadServers(); startSshProbeLoop(); }
  if (page === 'scripts') loadScripts();
  if (page === 'wireguard') loadWireguard();
  if (page === 'docker') loadDocker();
  if (page === 'files') loadFiles();
  if (page === 'backups') loadBackups();
  if (page === 'queues') { loadQueues(); loadHistory(); }
  if (page === 'monitor') { loadDashboard(); initSystemMonitor(); }
  if (page === 'settings') loadSettingsPage();
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
window.b4vNav = onNav;  // навигация из других модулей (дашборд и т.п.)

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
bindServerUI({ openQuickSetup: openQuickSetupFromCard });
bindScriptsUI();
bindTasksUI();
bindWireguardUI();
bindDockerUI();
bindFilesUI();
bindEditorUI();
bindTerminalUI();
// Settings подключается лениво вместе с групповой панелью.
settingsModule.then(module => {
  module?.bindSettingsUI();
  module?.initTheme();
}).catch(() => {});
// Групповая панель подключается лениво: ошибка её отдельного модуля
// не должна останавливать загрузку всей панели управления.
import('./groups_panel.js?v=20260911-groups-v2')
  .then(m => m.bindGroupsPanelUI())
  .catch(error => console.warn('[groups] module unavailable:', error));
bindAuthUI();
bindSetupUI();
bindGlobalSearch();
bindBackupUI();
bindTelegramHealthDialog();
quickSetupModule.then(module => module?.bindQuickSetupNav({
  openServer,
  openServers: () => onNav('servers'),
})).catch(() => {});
window.addEventListener('bot4vps:open-settings-category', async event => {
  const category = event.detail?.category;
  if (category !== 'telegram') return;
  try {
    const module = await settingsModule;
    if (!module) throw new Error('settings module unavailable');
    await module.selectSettingsCategory(category);
    onNav('settings');
    closeDrawer();
  } catch (_) {
    toast('Не удалось открыть настройки Telegram', false);
  }
});

async function restoreSession() {
  await loadGroupsAndKeys();
  await refreshAll();

  let page = 'servers';
  let serverId = null;
  try {
    page = localStorage.getItem('bot4vps_page') || 'servers';
    serverId = localStorage.getItem('bot4vps_server_id');
  } catch (_) {}

  const query = new URLSearchParams(window.location.search);
  let quickSetupServerId = null;
  if (query.get('page') === 'quick-setup') {
    quickSetupServerId = (query.get('server_id') || '').trim() || null;
  } else if (page === 'quick-setup') {
    try {
      quickSetupServerId = localStorage.getItem('bot4vps_quick_setup_server_id');
    } catch (_) {}
  }
  if (quickSetupServerId) {
    try {
      const module = await quickSetupModule;
      if (!module) throw new Error('Модуль настроек сервера недоступен');
      await module.openQuickSetup(quickSetupServerId, {
        historyMode: 'replace',
        throwOnError: true,
      });
      return;
    } catch (_) {
      clearQuickSetupServer();
      clearQuickSetupLocation();
      try { localStorage.setItem('bot4vps_page', 'servers'); } catch (_) {}
      onNav('servers');
      return;
    }
  } else if (page === 'quick-setup') {
    clearQuickSetupServer();
    clearQuickSetupLocation();
    onNav('servers');
    return;
  }

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

window.addEventListener('popstate', async () => {
  const query = new URLSearchParams(window.location.search);
  const queryServerId = query.get('page') === 'quick-setup'
    ? (query.get('server_id') || '').trim()
    : '';
  if (queryServerId) {
    const module = await quickSetupModule;
    if (module) {
      await module.openQuickSetup(queryServerId, { historyMode: 'none' });
    }
    return;
  }
  if (state.page === 'quick-setup') {
    const serverId = state.quickSetupServerId;
    clearQuickSetupServer();
    if (serverId) {
      try {
        await openServer(serverId);
        return;
      } catch (_) {}
    }
    onNav('servers');
  }
});

async function loadVersion() {
  try {
    const ping = await j('/api/ping');
    syncServerClock(ping);
    const versionInfo = document.getElementById('version-info');
    if (versionInfo && ping.version) versionInfo.textContent = `v${ping.version}`;
  } catch (err) {
    console.warn('Failed to load application version:', err);
  }
}

async function boot() {
  // Первичная настройка: пока действует код установки и админа нет,
  // всё закрыто бэкендом — показываем мастер/заглушку и останавливаем
  // загрузку (после создания админа страница перезагрузится на логин).
  if (!(await initSetup())) return;
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

  // Мастер-ключ потерян при наличии enc1: данных → красный баннер
  // поверх всего: молчать нельзя, пользователь должен выбрать действие.
  checkMasterKeyBanner();
  // Ключ восстановили/пересоздали в карточке настроек → убираем баннер
  window.addEventListener('bot4vps:masterkey-changed', checkMasterKeyBanner);
  // Ключ могут восстановить и вне Web (CLI bot4vps) — периодически
  // перепроверяем, чтобы баннер ушёл сам, без перезагрузки страницы.
  setInterval(checkMasterKeyBanner, 15000);


  // Загружаем данные для хедера при старте
  loadHeaderData();

  setInterval(tickClock, 1000);
  tickClock();
  startSSE();
  await restoreSession();
  // Если восстановили «Настройки», onNav уже загрузил активную категорию.

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

  // Полоса «Требует внимания», подзаголовок, бейдж непрочитанных —
  // реже (лёгкие API, без SSH), но без ручного обновления страницы
  setInterval(() => {
    if (state.page === 'dashboard') {
      updateDashboardState();
    }
  }, 10000);

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
    // Открытие профиля закрывает меню уведомлений (и наоборот):
    // stopPropagation ниже не даст document-клику сделать это самому
    document.getElementById('notifications-dropdown')?.classList.remove('show');
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

  // Определяем цвет stroke в зависимости от темы (glass — тёмная)
  const themeAttr = document.documentElement.getAttribute('data-theme');
  const isDark = themeAttr !== 'light';
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
    // Открытие уведомлений закрывает меню профиля (и наоборот):
    // stopPropagation не даст document-клику сделать это самому
    document.getElementById('profile-menu')?.classList.remove('show');
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

let mkBannerDismissed = false;

async function checkMasterKeyBanner() {
  // Тихий опрос: любые проблемы мастер-ключа всплывут красным баннером
  // сверху. ok/missing_no_data — штатные состояния, ничего не показываем
  // (и убираем баннер, если проблема решена — восстановили ключ).
  try {
    const st = await j('/api/masterkey/status');
    if (st.state !== 'missing_with_data' && st.state !== 'mismatch') {
      mkBannerDismissed = false;
      document.getElementById('mk-banner')?.remove();
      return;
    }
    // Пользователь уже скрыл баннер — периодическая перепроверка не
    // должна возвращать его; вернётся только после перезагрузки.
    if (mkBannerDismissed) return;
    let banner = document.getElementById('mk-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'mk-banner';
      banner.className = 'mk-banner';
      document.body.prepend(banner);
    }
    const isMismatch = st.state === 'mismatch';
    banner.innerHTML = `
      <div class="mk-banner-inner">
        <div class="mk-banner-text">
          <strong>⚠️ Мастер-ключ ${isMismatch ? 'не совпадает с зашифрованными данными' : 'отсутствует'}</strong>
          <span>Обнаружены зашифрованные данные, для расшифровки которых требуется существующий мастер-ключ. ${esc(st.encrypted_fields?.map(f => ({server_passwords: 'пароли серверов', bot_token: 'Telegram Bot Token', totp_secret: 'секрет 2FA'}[f] || f)).join(', ') || '')}</span>
        </div>
        <div class="mk-banner-actions">
          <a href="#settings" data-goto-settings-web class="mk-banner-btn">Перейти к восстановлению</a>
          <a href="#" class="mk-banner-btn secondary" data-mk-dismiss>Скрыть</a>
        </div>
      </div>`;
    banner.querySelector('[data-mk-dismiss]')?.addEventListener('click', e => {
      e.preventDefault();
      mkBannerDismissed = true;
      banner.remove();
    });
    banner.querySelector('[data-goto-settings-web]')?.addEventListener('click', e => {
      e.preventDefault();
      // onNav (не showPage): подгружает саму страницу настроек — иначе
      // открывалась пустая/прошлая страница, а клик по пункту меню не попадал
      onNav('settings');
      // Меню настроек рендерится асинхронно — ждём кнопку раздела
      const openSecurity = (tries = 0) => {
        const btn = document.querySelector('[data-settings-category="web"]');
        if (btn) { btn.click(); return; }
        if (tries < 50) setTimeout(() => openSecurity(tries + 1), 100);
      };
      openSecurity();
    });
  } catch (_) {
    // Ошибка опроса не должна ломать загрузку панели
  }
}

boot();
