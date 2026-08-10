import { j } from './api.js';
import { toast, syncServerTime, tickClock } from './ui.js';
import { renderMonitor } from './monitor.js';

export async function loadSummary() {
  try {
    try {
      const pong = await j('/api/ping');
      if (pong.server_ts) syncServerTime(pong.server_ts);
      tickClock();
    } catch (_) {}
    const s = await j('/api/summary');
    const core = document.getElementById('core-status');
    if (core) core.innerHTML = '<span class="dot"></span>Core';
    const err = document.getElementById('api-err');
    if (err) err.textContent = '';
    renderMonitor(s.monitor);
  } catch (e) {
    const core = document.getElementById('core-status');
    if (core) core.innerHTML = '<span class="dot off"></span>Offline';
    const err = document.getElementById('api-err');
    if (err) err.textContent = String(e.message || e);
  }
}
