import { state, setServers } from './state.js';
import { renderMonitor, applyEventsSnapshot } from './monitor.js';

let es = null;

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
    setServers(data.servers.map(s => ({ ...s, has_running: !!s.has_running })));
    import('./servers.js').then(m => {
      if (state.page === 'servers' && m.renderServersFromState) m.renderServersFromState();
    }).catch(() => {});
  }
  if (data.summary) {
    // KPI-чипы (Серверов/Очередей/▶ задач) убраны из верхней панели —
    // snapshot summary больше никуда не пишет. Монитор берёт своё ниже.
  }
  if (data.monitor && state.page === 'monitor') {
    renderMonitor(data.monitor);
  }
  if (data.events && state.page === 'events') {
    // Не перетираем раскрытый список коротким срезом — мержим в кэш и
    // рендерим с учётом выбранного пользователем лимита (см. monitor.js).
    applyEventsSnapshot(data.events);
  }
}
