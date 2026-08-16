// Глобальный поиск Bot4VPS
import { esc } from './api.js';
import { state, setPage } from './state.js';
import { showPage } from './ui.js';

let searchResults = [];

export function bindGlobalSearch() {
  const input = document.getElementById('global-search');
  const resultsBox = createResultsBox();

  input?.addEventListener('input', (e) => {
    const query = e.target.value.trim().toLowerCase();
    if (query.length < 2) {
      resultsBox.style.display = 'none';
      return;
    }

    searchResults = performSearch(query);
    renderResults(resultsBox, searchResults);
  });

  input?.addEventListener('focus', () => {
    if (searchResults.length > 0) {
      resultsBox.style.display = 'block';
    }
  });

  input?.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      resultsBox.style.display = 'none';
      input.blur();
    }
  });

  // Закрытие по клику вне
  document.addEventListener('click', (e) => {
    if (!input?.contains(e.target) && !resultsBox.contains(e.target)) {
      resultsBox.style.display = 'none';
    }
  });

  // Ctrl+K — фокус на поиск
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      input?.focus();
    }
  });
}

function createResultsBox() {
  let box = document.getElementById('global-search-results');
  if (!box) {
    box = document.createElement('div');
    box.id = 'global-search-results';
    box.style.cssText = `
      position:absolute;
      top:calc(100% + 0.5rem);
      left:0;
      right:0;
      max-height:400px;
      overflow:auto;
      background:var(--panel);
      backdrop-filter:blur(12px);
      border:1px solid var(--border);
      border-radius:var(--radius-md);
      box-shadow:var(--shadow-lg);
      z-index:100;
      display:none;
    `;
    document.querySelector('.search-wrap')?.appendChild(box);
  }
  return box;
}

function performSearch(query) {
  const results = [];

  // Поиск серверов
  state.servers.forEach(s => {
    const name = (s.name || '').toLowerCase();
    const host = (s.host || '').toLowerCase();
    const group = (s.group || '').toLowerCase();
    if (name.includes(query) || host.includes(query) || group.includes(query)) {
      results.push({
        type: 'server',
        title: s.name,
        subtitle: s.host,
        icon: '🖥',
        data: s
      });
    }
  });

  // Поиск разделов
  const sections = [
    { name: 'Обзор', page: 'dashboard', icon: '📊' },
    { name: 'Серверы', page: 'servers', icon: '🖥' },
    { name: 'Очереди', page: 'queues', icon: '📋' },
    { name: 'WireGuard', page: 'wireguard', icon: '🌐' },
    { name: 'Docker', page: 'docker', icon: '🐳' },
    { name: 'Скрипты', page: 'scripts', icon: '📜' },
    { name: 'Файлы', page: 'files', icon: '📂' },
    { name: 'Мониторинг', page: 'monitor', icon: '📡' },
    { name: 'Журнал уведомлений', page: 'events', icon: '📖' },
    { name: 'Настройки', page: 'settings', icon: '⚙️' }
  ];

  sections.forEach(sec => {
    if (sec.name.toLowerCase().includes(query)) {
      results.push({
        type: 'section',
        title: sec.name,
        subtitle: 'Раздел',
        icon: sec.icon,
        data: sec
      });
    }
  });

  return results.slice(0, 10);
}

function renderResults(box, results) {
  if (!results.length) {
    box.innerHTML = '<div style="padding:1rem;color:var(--text-muted);text-align:center">Ничего не найдено</div>';
    box.style.display = 'block';
    return;
  }

  box.innerHTML = results.map(r => `
    <div class="search-result-item" data-type="${r.type}" data-id="${r.data.id || r.data.page || ''}">
      <span style="font-size:1.25rem">${r.icon}</span>
      <div style="flex:1">
        <div style="font-weight:600;font-size:0.9rem">${esc(r.title)}</div>
        <div style="font-size:0.75rem;color:var(--text-dim)">${esc(r.subtitle)}</div>
      </div>
    </div>
  `).join('');

  box.style.display = 'block';

  // Обработка кликов
  box.querySelectorAll('.search-result-item').forEach(item => {
    item.addEventListener('click', () => {
      const type = item.dataset.type;
      const id = item.dataset.id;

      if (type === 'server') {
        import('./servers.js?v=20260815-settings-files-v2').then(m => {
          setPage('servers');
          showPage('servers');
          m.openServer(id);
        });
      } else if (type === 'section') {
        setPage(id);
        showPage(id);
      }

      box.style.display = 'none';
      document.getElementById('global-search').value = '';
    });
  });
}

// Стили для результатов
const style = document.createElement('style');
style.textContent = `
  .search-result-item{
    display:flex;
    align-items:center;
    gap:0.75rem;
    padding:0.75rem 1rem;
    cursor:pointer;
    transition:all 0.15s;
    border-bottom:1px solid var(--border);
  }
  .search-result-item:last-child{
    border-bottom:none;
  }
  .search-result-item:hover{
    background:var(--card-hover);
    transform:translateX(2px);
  }
  .search-result-item:active{
    transform:translateX(0);
  }
`;
document.head.appendChild(style);
