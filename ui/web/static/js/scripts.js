import { j, esc } from './api.js';
import { toast } from './ui.js';
import { openServer, showTab } from './servers.js';
import { state, setScripts, setServerTab } from './state.js';

// lastScripts -> state.scripts

export async function loadScripts() {
  try {
    const data = await j('/api/scripts');
    setScripts(data.scripts || []);
    const el = document.getElementById('scripts');
    if (!state.scripts.length) { el.innerHTML = '<div class="empty">Нет .sh</div>'; return; }
    el.innerHTML = state.scripts.map(s => {
      const params = (s.params || []).map(p => esc(p.label || p.name)).join(', ');
      const meta = [s.version ? ('v' + s.version) : '', s.author || ''].filter(Boolean).join(' · ');
      return `<div class="card">
        <div class="card-body">
          <h3>📜 ${esc(s.name)}</h3>
          <div class="row">${s.description ? esc(s.description) : (s.lines ?? '?') + ' строк'}</div>
          ${meta ? `<div class="row">${esc(meta)}</div>` : ''}
          <div class="row">${params ? 'Параметры: ' + params : 'без параметров'}</div>
        </div>
        <div class="card-actions">
          <button type="button" class="secondary" data-view="${esc(s.name)}">👁 Открыть</button>
          <button type="button" data-sc="${esc(s.name)}">▶ Выполнить</button>
          <button type="button" data-term="${esc(s.name)}">💻 Запустить в терминале</button>
        </div>
      </div>`;
    }).join('');
    el.querySelectorAll('[data-sc]').forEach(b => b.onclick = () => openRunModal(null, b.dataset.sc));
    el.querySelectorAll('[data-term]').forEach(b => b.onclick = () => openRunModal(null, b.dataset.term, 'terminal'));
    el.querySelectorAll('[data-view]').forEach(b => b.onclick = () => viewScript(b.dataset.view));
  } catch (e) {
    document.getElementById('scripts').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
  }
}

export async function viewScript(name) {
  try {
    const d = await j('/api/scripts/' + encodeURIComponent(name));
    const modal = document.getElementById('script-modal');
    const title = document.getElementById('script-view-title');
    const body = document.getElementById('script-view-body');
    if (!modal || !title || !body) { toast('Модалка не найдена', false); return; }
    title.textContent = d.name || name;
    body.textContent = d.content || '(пусто)';
    modal.classList.add('open');
  } catch (e) { toast(e.message, false); }
}

// ---- Параметры скрипта в модалке запуска ----

function currentScript() {
  const name = document.getElementById('run-script')?.value;
  return state.scripts.find(s => s.name === name) || null;
}

function parseCond(c) {
  // формат условия из core/script_utils: "paramname:value" (сравнение case-insensitive)
  if (!c || !String(c).includes(':')) return null;
  const idx = c.indexOf(':');
  return { name: c.slice(0, idx).trim(), value: c.slice(idx + 1) };
}

function buildRunParams(script) {
  const box = document.getElementById('run-params');
  if (!box) return;
  box.innerHTML = '';
  if (!script || !Array.isArray(script.params) || !script.params.length) return;

  const values = {};
  // значения по умолчанию
  script.params.forEach(p => {
    if (p.type === 'select' && p.options && p.options.length) values[p.name] = p.options[0].value;
    else if (p.type === 'bool') values[p.name] = 'false';
    else values[p.name] = '';
  });

  function applyConditions() {
    box.querySelectorAll('.run-param').forEach(w => {
      const cn = w.dataset.condName, cv = w.dataset.condVal;
      if (!cn) return;
      const cur = String(values[cn] ?? '').toLowerCase();
      w.classList.toggle('hidden', cur !== String(cv ?? '').toLowerCase());
    });
  }

  script.params.forEach(p => {
    const wrap = document.createElement('div');
    wrap.className = 'run-param';
    wrap.dataset.name = p.name;
    const cond = parseCond(p.condition);
    if (cond) { wrap.dataset.condName = cond.name; wrap.dataset.condVal = cond.value; }

    const label = document.createElement('label');
    label.className = 'row';
    label.textContent = p.label || p.name;

    let field;
    if (p.type === 'select') {
      field = document.createElement('select');
      (p.options || []).forEach(o => {
        const op = document.createElement('option');
        op.value = o.value; op.textContent = o.label || o.value;
        field.appendChild(op);
      });
      field.value = values[p.name];
    } else if (p.type === 'bool') {
      field = document.createElement('select');
      [['true', 'Да'], ['false', 'Нет']].forEach(([v, l]) => {
        const op = document.createElement('option');
        op.value = v; op.textContent = l; field.appendChild(op);
      });
      field.value = 'false';
    } else {
      field = document.createElement('input');
      field.type = p.type === 'number' ? 'number' : 'text';
      field.value = values[p.name];
    }
    const update = () => { values[p.name] = field.value; applyConditions(); };
    field.addEventListener('input', update);
    field.addEventListener('change', update);

    wrap.appendChild(label);
    wrap.appendChild(field);
    box.appendChild(wrap);
  });

  box._values = values;
  applyConditions();
}

function collectRunValues() {
  const box = document.getElementById('run-params');
  const out = {};
  if (!box || !box._values) return out;
  box.querySelectorAll('.run-param:not(.hidden)').forEach(w => {
    const name = w.dataset.name;
    const v = box._values[name];
    if (v == null || v === '') return; // пустые text/number пропускаем
    out[name] = String(v);
  });
  return out;
}

// режим работы модала запуска: 'background' (очередь) | 'terminal' (PTY)
let runMode = 'background';

export function openRunModal(serverId, scriptName, mode = 'background') {
  if (!state.scripts.length || !state.servers.length) {
    toast('Нет скриптов или серверов', false); return;
  }
  runMode = mode;
  const isTerm = mode === 'terminal';
  document.getElementById('run-script').innerHTML = state.scripts.map(s =>
    `<option value="${esc(s.name)}" ${s.name === scriptName ? 'selected' : ''}>${esc(s.name)}</option>`
  ).join('');
  document.getElementById('run-server').innerHTML = state.servers.map(s =>
    `<option value="${esc(s.id)}" ${s.id === serverId ? 'selected' : ''}>${esc(s.name)}</option>`
  ).join('');
  buildRunParams(currentScript());
  // в терминале параметры не нужны (ввод интерактивный); меняем кнопку подтверждения
  document.getElementById('run-params').classList.toggle('hidden', isTerm);
  document.getElementById('btn-run-confirm').textContent = isTerm ? '💻 Открыть терминал' : 'Выполнить';
  document.getElementById('run-modal').classList.add('open');
}

export async function confirmRun() {
  const script_name = document.getElementById('run-script').value;
  const server_id = document.getElementById('run-server').value;
  if (runMode === 'terminal') {
    // интерактивный запуск: открыть терминал сервера и запустить скрипт в PTY.
    // setServerTab('status') перед openServer — чтобы тот не открыл «блуждающий»
    // терминал через showTab(lastServerTab) (особенно если юзер ранее был на вкладке
    // «Терминал»: тогда lastServerTab()==='terminal'). Финальный терминал открываем сами.
    document.getElementById('run-modal').classList.remove('open');
    setServerTab('status');
    await openServer(server_id);
    state.pendingTermScript = script_name;
    showTab('terminal');   // → openTerminal() → connect(sid, script) → WS run_script
    return;
  }
  const values = collectRunValues();
  try {
    const r = await j('/api/tasks/enqueue', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ script_name, server_id, values }),
    });
    document.getElementById('run-modal').classList.remove('open');
    toast('В очереди', true);
    if (r.task) {
      await openServer(server_id);
      showTab('log');
    }
  } catch (e) { toast(e.message, false); }
}

export function bindScriptsUI() {
  document.getElementById('btn-run-confirm')?.addEventListener('click', confirmRun);
  document.getElementById('btn-run-cancel')?.addEventListener('click', () =>
    document.getElementById('run-modal').classList.remove('open'));
  document.getElementById('run-script')?.addEventListener('change', () =>
    buildRunParams(currentScript()));
  document.getElementById('run-modal')?.addEventListener('click', e => {
    if (e.target.id === 'run-modal') e.currentTarget.classList.remove('open');
  });
  document.getElementById('script-modal-close')?.addEventListener('click', () =>
    document.getElementById('script-modal')?.classList.remove('open'));
  document.getElementById('script-modal')?.addEventListener('click', e => {
    if (e.target.id === 'script-modal') e.currentTarget.classList.remove('open');
  });
  document.getElementById('upload-script')?.addEventListener('change', async e => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await fetch('/api/upload/script', { method: 'POST', body: fd });
      const t = await r.text(); let d; try { d = JSON.parse(t); } catch { d = {}; }
      if (!r.ok) throw new Error(d.detail || t);
      toast('OK', true); loadScripts();
    } catch (err) { toast(err.message, false); }
    e.target.value = '';
  });
}
