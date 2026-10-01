import { state, setServers } from './state.js';
import { applyEventsSnapshot } from './monitor.js?v=20261001-mobile-charts-v1';

let es = null;
let notificationsRefresh = null;
let taskHistoryRevision = null;
let securityRevision = null;
let xuiCacheRevision = null;
let onlineById = null;   // id -> true/false (до первого снапшота — null)
let connectedOnce = false;

// Версии модулей — те же, что в app.js: одинаковый адрес импорта означает
// один экземпляр модуля, то есть общее состояние страницы (импорт «заново»
// с другим ?v= создал бы вторую копию со своим lastOverview).
const METRICS_MODULE = './metrics.js?v=20261001-mobile-charts-v1';
const AUDIT_MODULE = './audit.js?v=20261001-mobile-charts-v1';

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
    const reconnected = connectedOnce;
    connectedOnce = true;
    state.sseConnected = true;
    const core = document.getElementById('core-status');
    if (core) core.innerHTML = '<span class="dot"></span>Core · SSE';
    // Поток отдаёт свежее, но пропущенное за время разрыва не досылает:
    // страницы, которые живут историей, перечитывают данные запросом —
    // иначе вкладка застыла бы на числах до переподключения. На первый
    // `hello` делать нечего: страница ещё грузит свои данные сама.
    if (!reconnected) return;
    import(METRICS_MODULE).then(m => m.reloadMetricsAfterReconnect()).catch(() => {});
    import(AUDIT_MODULE).then(m => m.reloadAuditAfterReconnect()).catch(() => {});
  });

  // `event: metrics` — одна проба одного сервера (§11). Открытая страница
  // метрик дописывает точку; сама страница решает, что с ней делать.
  es.addEventListener('metrics', (ev) => {
    if (state.page !== 'metrics') return;
    let frame;
    try { frame = JSON.parse(ev.data); } catch (_) { return; }
    import(METRICS_MODULE).then(m => m.applyMetricsFrame(frame)).catch(() => {});
  });

  // `event: audit` — сырая append-only запись. Для UI это только сигнал
  // инвалидации: один frame может создать операцию или изменить её итог.
  es.addEventListener('audit', (ev) => {
    let frame;
    try { frame = JSON.parse(ev.data); } catch (_) { return; }
    if (state.page === 'history' && state.historyTab === 'actions') {
      import(AUDIT_MODULE).then(m => m.applyAuditFrame(frame)).catch(() => {});
    }
    if (state.page === 'metrics') {
      import(METRICS_MODULE).then(m => m.applyAuditFrame(frame)).catch(() => {});
    }
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
      const changedServerIds = [];
      for (const [id, online] of nextOnline) {
        if (onlineById.get(id) !== online) changedServerIds.push(id);
      }
      for (const id of onlineById.keys()) {
        if (!nextOnline.has(id)) changedServerIds.push(id);
      }
      if (changedServerIds.length) {
        window.dispatchEvent(new CustomEvent('bot4vps:availability-changed', {
          detail: { serverIds: changedServerIds },
        }));
      }
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
    import('./servers.js?v=20261001-mobile-charts-v1').then(m => {
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
    if (state.page === 'history' && state.historyTab === 'queues') {
      import('./servers.js?v=20261001-mobile-charts-v1').then(m => {
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
    if (state.page === 'history' && state.historyTab !== 'queues') {
      applyEventsSnapshot(data.events);
    }
    // Открытая карточка сервера — обновить блок «Недавние события»
    if (state.page === 'server') {
      import('./servers.js?v=20261001-mobile-charts-v1').then(m => {
        if (m.refreshOpenServerEvents) m.refreshOpenServerEvents();
        else if (m.openServerId) {
          // fallback: модуль мог ещё не экспортировать helper
        }
      }).catch(() => {});
    }
    if (notificationsRefresh) notificationsRefresh();
  }
}
