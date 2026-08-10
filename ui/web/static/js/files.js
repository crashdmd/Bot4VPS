import { j, esc } from './api.js';
import { toast } from './ui.js';

let fileRoot = 'scripts';

export async function loadFiles() {
  try {
    const data = await j('/api/files?root=' + encodeURIComponent(fileRoot));
    const el = document.getElementById('file-list');
    const btnKey = document.getElementById('btn-create-key');
    if (btnKey) btnKey.style.display = fileRoot === 'keys' ? '' : 'none';
    const items = (data.items || []).filter(i => !i.is_dir);
    if (!items.length) { el.innerHTML = '<div class="empty" style="padding:.8rem">Пусто</div>'; return; }
    el.innerHTML = items.map(f => {
      const kb = f.size != null ? (f.size < 1024 ? f.size + ' б' : Math.round(f.size / 1024) + ' КБ') : '';
      const icon = fileRoot === 'keys' ? '🔑' : '📄';
      const viewBtn = fileRoot === 'keys'
        ? `<button type="button" class="secondary" style="padding:.2rem .45rem" data-viewkey="${esc(f.name)}">👁</button>`
        : '';
      return `<div class="file-row"><span>${icon} ${esc(f.name)}${kb ? ' · ' + kb : ''}</span>
      <span style="display:flex;gap:.3rem;flex-shrink:0">
        ${viewBtn}
        <a class="btn secondary" style="padding:.2rem .45rem;text-decoration:none"
           href="/api/files/download?root=${encodeURIComponent(fileRoot)}&name=${encodeURIComponent(f.name)}">⬇</a>
        <button type="button" class="secondary" style="padding:.2rem .45rem" data-del="${esc(f.name)}">🗑</button>
      </span></div>`;
    }).join('');
    el.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
      if (!confirm('Удалить ' + b.dataset.del + '?')) return;
      try {
        await j('/api/files?root=' + encodeURIComponent(fileRoot) + '&name=' + encodeURIComponent(b.dataset.del), { method: 'DELETE' });
        loadFiles();
      } catch (e) { toast(e.message, false); }
    });
    el.querySelectorAll('[data-viewkey]').forEach(b => b.onclick = () => viewKey(b.dataset.viewkey));
  } catch (e) {
    document.getElementById('file-list').innerHTML = '<div class="empty" style="padding:.8rem">' + esc(e.message) + '</div>';
  }
}

async function viewKey(name) {
  try {
    const d = await j('/api/keys/view?name=' + encodeURIComponent(name));
    const modal = document.getElementById('script-modal');
    const title = document.getElementById('script-view-title');
    const body = document.getElementById('script-view-body');
    title.textContent = '🔑 ' + (d.name || name);
    let text = d.content || '';
    if (d.public) text += '\n\n--- PUBLIC ---\n' + d.public;
    body.textContent = text;
    modal.classList.add('open');
  } catch (e) { toast(e.message, false); }
}

export function bindFilesUI() {
  document.getElementById('file-tabs')?.querySelectorAll('[data-root]').forEach(b => {
    b.onclick = () => {
      fileRoot = b.dataset.root;
      document.getElementById('file-tabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      loadFiles();
    };
  });
  document.getElementById('btn-create-key')?.addEventListener('click', async () => {
    const name = prompt('Имя ключа (без пробелов):');
    if (!name) return;
    try {
      await j('/api/keys/create', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      toast('Ключ создан', true); loadFiles();
    } catch (e) { toast(e.message, false); }
  });
  document.getElementById('upload-file')?.addEventListener('change', async e => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await fetch('/api/files/upload?root=' + encodeURIComponent(fileRoot), { method: 'POST', body: fd });
      const t = await r.text(); let d; try { d = JSON.parse(t); } catch { d = {}; }
      if (!r.ok) throw new Error(d.detail || t);
      toast('OK', true); loadFiles();
    } catch (err) { toast(err.message, false); }
    e.target.value = '';
  });
}
