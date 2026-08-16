// Полноценный терминал: xterm.js (фронт) ↔ WebSocket ↔ core.terminal.ShellSession (PT).
// ANSI/интерактивность/resize/Ctrl+C — нативно через xterm.js + PTY.
import { toast } from './ui.js';
import { state } from './state.js';

const XTERM_THEME = {
  dark: { background: '#0a0e14', foreground: '#e6edf3', cursor: '#e6edf3', selectionBackground: '#264f7888' },
  light: { background: '#ffffff', foreground: '#1f2328', cursor: '#1f2328', selectionBackground: '#9ec6f888' },
};

let term = null;
let fitAddon = null;
let ws = null;
let ro = null;
let curServerId = null;

function resolvedTheme() {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function setStatus(text, ok = null) {
  const el = document.getElementById('term-status');
  if (!el) return;
  el.textContent = text;
  el.style.color = ok === true ? 'var(--ok)' : ok === false ? 'var(--err)' : '';
}

function ensureTerm() {
  if (term) return term;
  const host = document.getElementById('term-xterm');
  if (!host || !window.Terminal) { toast('xterm.js не загрузился', false); return null; }
  const FitCls = window.FitAddon && (window.FitAddon.FitAddon || window.FitAddon);

  term = new window.Terminal({
    cursorBlink: true,
    fontFamily: 'ui-monospace,Consolas,monospace',
    fontSize: 13,
    scrollback: 5000,
    theme: XTERM_THEME[resolvedTheme()],
  });
  if (FitCls) { fitAddon = new FitCls(); term.loadAddon(fitAddon); }
  term.open(host);
  if (fitAddon) { try { fitAddon.fit(); } catch {} }
  // ввод пользователя → PTY
  term.onData(d => sendMsg({ type: 'input', data: d }));
  // изменение размера терминала → PTY
  term.onResize(({ cols, rows }) => sendMsg({ type: 'resize', cols, rows }));
  // авто-fit при ресайзе контейнера
  if (window.ResizeObserver) {
    ro = new ResizeObserver(() => { if (fitAddon) { try { fitAddon.fit(); } catch {} } });
    ro.observe(host);
  }
  return term;
}

function sendMsg(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function connect(sid, script = null) {
  closeWs();
  const t = ensureTerm();
  if (!t) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/api/servers/${encodeURIComponent(sid)}/shell/ws`;
  setStatus('SSH · подключение…');
  let sock;
  try {
    sock = new WebSocket(url);
  } catch (e) {
    setStatus('SSH · ошибка: ' + e.message, false);
    return;
  }
  ws = sock;
  sock.binaryType = 'arraybuffer';
  sock.onopen = () => {
    setStatus('SSH · подключено', true);
    if (term) sendMsg({ type: 'resize', cols: term.cols, rows: term.rows });
    // запуск скрипта как первое действие в открытой сессии (режим «в терминале»)
    if (script) sendMsg({ type: 'run_script', name: script });
    if (fitAddon) { try { fitAddon.fit(); } catch {} }
    term && term.focus();
  };
  sock.onmessage = ev => { if (term) term.write(typeof ev.data === 'string' ? ev.data : new TextDecoder().decode(ev.data)); };
  sock.onclose = () => setStatus('SSH · отключено', false);
  sock.onerror = () => setStatus('SSH · ошибка соединения', false);
}

function closeWs() {
  if (ws) {
    ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.onopen = null;
    try { ws.close(); } catch {}
    ws = null;
  }
}

function resolveServerId() {
  // Единый источник — state (общий для всех модулей). Не импортируем servers.js:
  // другой URL импорта создал бы второй экземпляр модуля с пустым openServerId.
  return state.openServerId
    || state.openServerData?.server?.id
    || window._openServerData?.server?.id
    || document.getElementById('btn-open-terminal')?.dataset?.serverId
    || null;
}

export async function openTerminal() {
  const sid = resolveServerId();
  if (!sid) {
    toast('Сначала откройте сервер', false);
    return;
  }
  curServerId = sid;
  const t = ensureTerm();
  if (!t) return;
  // скрипт, который надо запустить сразу после подключения (режим «в терминале»)
  const script = state.pendingTermScript || null;
  state.pendingTermScript = null;
  connect(sid, script);
}

export function closeTerminal() {
  closeWs();
  if (ro) { try { ro.disconnect(); } catch {} ro = null; }
  if (term) { try { term.dispose(); } catch {} term = null; fitAddon = null; }
  setStatus('SSH · отключено');
}

// синхронизация темы xterm с темой приложения (событие из settings.js)
window.addEventListener('bot4vps:theme', e => {
  if (term && e.detail && e.detail.resolved) term.options.theme = XTERM_THEME[e.detail.resolved] || XTERM_THEME.dark;
});

export function bindTerminalUI() {
  document.getElementById('term-reconnect')?.addEventListener('click', () => {
    const sid = curServerId || resolveServerId();
    if (sid) {
      curServerId = sid;
      connect(sid);
    } else {
      toast('Откройте сервер', false);
    }
  });
}
