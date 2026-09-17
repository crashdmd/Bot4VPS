import { state, setServers } from './state.js';
import { applyEventsSnapshot } from './monitor.js?v=20260915-taskfail-v2';

let es = null;
let notificationsRefresh = null;
let taskHistoryRevision = null;
let securityRevision = null;
let xuiCacheRevision = null;
let onlineById = null;   // id -> true/false (до первого снапшота — null)

export function registerNotificationsRefresh(handler) {
  notificationsRefresh = typeof handler === 'function' ? handler : null;
}

export function startSSE() {
  if (es) return;
  try {
    es = new EventSource('/api/stream');
  } catch (e) {
    console.warn('SSE unavailable', e);
    return;
  }

  es.addEventListener('hello', () => {
    state.sseConnected = true;
    const core = document.getElementById('core-status');
    if (core) core.innerHTML = '<span class="dot"></span>Core · SSE';
  });

  es.addEventListener('snapshot', (ev) => {
    try {
      applySnapshot(JSON.parse(ev.data));
    } catch (e) {
      console.warn('SSE parse', e);
    }
  });

  es.onerror = () => {
    state.sseConnected = false;
  };
}

export function stopSSE() {
  if (es) {
    es.close();
    es = null;
  }
  state.sseConnected = false;
}

function applySnapshot(data) {
  if (data.servers) {
    // Смена online/offline любого сервера — отдельное событие: страницы
    // сервисов (WG/Docker) перечитывают список, чтобы оффлайн-строки были
    // актуальны без захода на страницу «Серверы».
    const nextOnline = new Map(data.servers.map(s => [s.id, `${s.online}|${s.port_ok ?? ''}`]));
    if (onlineById) {
      let changed = false;
      for (const [id, online] of nextOnline) {
        if (onlineById.get(id) !== online) { changed = true; break; }
      }
      if (changed) window.dispatchEvent(new CustomEvent('bot4vps:availability-changed'));
    }
    onlineById = nextOnline;
    const previousById = new Map(state.servers.map(server => [server.id, server]));
    setServers(data.servers.map(s => {
      const previous = previousById.get(s.id) || {};
      return {
        ...previous,
        ...s,
        // Старый Core мог не включать uptime в SSE; не затираем уже загруженный кэш.
        uptime: s.uptime ?? previous.uptime,
        uptime_seconds: s.uptime_seconds ?? previous.uptime_seconds,
        has_running: !!s.has_running,
      };
    }));
    import('./servers.js?v=20260915-sysfix-v2').then(m => {
      if (state.page === 'servers' && m.renderServersFromState) m.renderServersFromState();
    }).catch(() => {});
  }
  if (data.summary) {
    // KPI-чипы (Серверов/Очередей/▶ задач) убраны из верхней панели —
    // snapshot summary больше никуда не пишет. Монитор берёт своё ниже.
  }
  if (data.task_history_revision !== undefined
      && data.task_history_revision !== taskHistoryRevision) {
    taskHistoryRevision = data.task_history_revision;
    if (state.page === 'queues') {
      import('./servers.js?v=20260915-sysfix-v2').then(m => {
        m.loadHistory?.();
      }).catch(() => {});
    }
  }
  if (data.security_revision
      && data.security_revision !== securityRevision) {
    const known = securityRevision !== null;
    securityRevision = data.security_revision;
    // Первый снапшот после загрузки — состояние карточек уже актуально,
    // событие не нужно. Дальше: секреты переписали из CLI/TG или другой
    // сессии Web — Настройки перечитывают карточки «Безопасность».
    if (known) window.dispatchEvent(new CustomEvent('bot4vps:security-changed'));
  }
  if (data.xui_cache_revision
      && data.xui_cache_revision !== xuiCacheRevision) {
    const known = xuiCacheRevision !== null;
    xuiCacheRevision = data.xui_cache_revision;
    if (known) window.dispatchEvent(new CustomEvent('bot4vps:xui-cache-changed'));
  }
  if (data.events) {
    // Не перетираем раскрытый список коротким срезом — мержим в кэш и
    // рендерим с учётом выбранного пользователем лимита (см. monitor.js).
    if (state.page === 'events') {
      applyEventsSnapshot(data.events);
    }
    // Открытая карточка сервера — обновить блок «Недавние события»
    if (state.page === 'server') {
      import('./servers.js?v=20260915-sysfix-v2').then(m => {
        if (m.refreshOpenServerEvents) m.refreshOpenServerEvents();
        else if (m.openServerId) {
          // fallback: модуль мог ещё не экспортировать helper
        }
      }).catch(() => {});
    }
    if (notificationsRefresh) notificationsRefresh();
  }
}
