// Глобальный поиск Bot4VPS
import { esc } from './api.js';
import { state, setPage } from './state.js';
import { showPage } from './ui.js';
import { WIREGUARD_ICON, DOCKER_ICON } from './icons.js?v=20260905-brandicons-v2';
import { setServerQuery as setServerListQuery } from './servers.js?v=20260913-hostkey-v2';

let searchResults = [];

export function bindGlobalSearch() {
  const input = document.getElementById('global-search');
  const resultsBox = createResultsBox();

  input?.addEventListener('input', (e) => {
    const rawQuery = e.target.value;
    const query = rawQuery.trim().toLowerCase();
    setServerListQuery(rawQuery);
    if (query.length < 2) {
      searchResults = [];
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
      input.value = '';
      setServerListQuery('');
      searchResults = [];
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
      background:var(--bg-base);
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
    { name: 'Дашборд', page: 'dashboard', icon: '📊' },
    { name: 'Серверы', page: 'servers', icon: '🖥' },
    { name: 'Задачи', page: 'queues', icon: '📋' },
    { name: 'WireGuard', page: 'wireguard', icon: WIREGUARD_ICON },
    { name: 'Docker', page: 'docker', icon: DOCKER_ICON },
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

  // Поиск по категориям Настроек («общие» → Настройки → Общие):
  // те же id, что рендерит renderNav() в settings.js
  const settingsSections = [
    { name: 'Общие', id: 'common', icon: '◉', desc: 'Мониторинг и интерфейс' },
    { name: 'Безопасность', id: 'web', icon: '🛡', desc: 'Вход, 2FA, мастер-ключ, порт' },
    { name: 'Telegram', id: 'telegram', icon: '↗', desc: 'Бот и получатель' },
    { name: 'История и данные', id: 'data', icon: '▤', desc: 'Лимиты хранения' },
    { name: 'Обновления', id: 'updates', icon: '⇧', desc: 'Проверка и установка' },
    { name: 'О программе', id: 'about', icon: 'i', desc: 'Версия и проект' }
  ];

  settingsSections.forEach(sec => {
    if (sec.name.toLowerCase().includes(query) || sec.desc.toLowerCase().includes(query)) {
      results.push({
        type: 'settings',
        title: sec.name,
        subtitle: `Настройки · ${sec.desc}`,
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
        import('./servers.js?v=20260913-hostkey-v2').then(m => {
          setPage('servers');
          showPage('servers');
          m.openServer(id);
        });
      } else if (type === 'section') {
        setPage(id);
        showPage(id);
      } else if (type === 'settings') {
        // Категория настроек: открыть Настройки и выбрать её в меню
        const cat = searchResults.find(r => r.type === 'settings' && r.data.id === id);
        setPage('settings');
        showPage('settings');
        import('./settings.js?v=20260913-hostkey-v2').then(m => {
          m.selectSettingsCategory?.(id);
        });
      }

      box.style.display = 'none';
      document.getElementById('global-search').value = '';
      setServerListQuery('');
      searchResults = [];
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
  }
  .search-result-item:active{
    background:var(--field);
  }
`;
document.head.appendChild(style);
