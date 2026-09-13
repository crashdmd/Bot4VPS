/**
 * Настройки сервера (Quick Setup).
 * Без Task Manager — операции идут синхронно через API ядра.
 */
import { j, esc } from './api.js';
import { showPage, toast, confirmAction, formatServerDateTime } from './ui.js';
import {
  state,
  setPage,
  setQuickSetupServer,
  clearQuickSetupServer,
} from './state.js';

let busy = false;
let busyGeneration = 0;
let contextGeneration = 0;
let lastOverview = null;
let activeSection = 'system';
let qsModalReturnFocus = null;
let qsModalChoiceResolve = null;
// Предупреждение «ключ используется двумя пользователями» показывается
// один раз на пару (сервер, владелец-конфликт) за сессию страницы.
const qsSharedKeyWarned = new Set();
let navigation = {
  openServer: null,
  openServers: null,
};

function captureContext() {
  const serverId = String(state.quickSetupServerId || '').trim();
  return serverId ? { serverId, generation: contextGeneration } : null;
}

function contextIsCurrent(context) {
  return !!context
    && state.page === 'quick-setup'
    && state.quickSetupServerId === context.serverId
    && contextGeneration === context.generation;
}

function requireContext() {
  const context = captureContext();
  if (!context) throw new Error('Сервер для настроек не выбран');
  return context;
}

function setBusy(on, context = null) {
  if (context && !contextIsCurrent(context)) return;
  if (on) {
    busy = true;
    busyGeneration = context?.generation ?? contextGeneration;
  } else if (!context || busyGeneration === context.generation) {
    busy = false;
  }
  const body = document.getElementById('qs-body');
  if (body) body.classList.toggle('qs-busy', busy);
}

function syncQuickSetupLocation(serverId, mode) {
  if (mode === 'none') return;
  const url = new URL(window.location.href);
  url.searchParams.set('page', 'quick-setup');
  url.searchParams.set('server_id', serverId);
  const target = `${url.pathname}${url.search}${url.hash}`;
  if (mode === 'replace') history.replaceState(null, '', target);
  else history.pushState(null, '', target);
}

function clearQuickSetupLocation() {
  const url = new URL(window.location.href);
  url.searchParams.delete('page');
  url.searchParams.delete('server_id');
  history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
}

class QuickSetupContextChanged extends Error {
  constructor() {
    super('Контекст настроек сервера изменился');
    this.name = 'QuickSetupContextChanged';
  }
}

async function requestForContext(context, url, options) {
  const result = await j(url, options);
  if (!contextIsCurrent(context)) throw new QuickSetupContextChanged();
  return result;
}

function showContextToast(context, message, ok) {
  if (contextIsCurrent(context)) toast(message, ok);
}

function statusDot(ok) {
  if (ok === true) return '<span class="qs-status-dot on" title="ok"></span>';
  if (ok === false) return '<span class="qs-status-dot off" title="off"></span>';
  return '<span class="qs-status-dot unk" title="?"></span>';
}

function section(title, inner, id, headActions = '') {
  const idAttr = id ? ` id="${id}"` : '';
  return `<section class="set-section qs-panel"${idAttr} data-qs-panel="${id || ''}">
    <div class="set-section-head"><h2>${title}</h2>${headActions}</div>
    <div class="qs-section-body">${inner}</div>
  </section>`;
}

function qsAdminRights() {
  // sudo у текущего пользователя Bot4VPS (root — всегда); false →
  // доступны только собственные SSH-ключи и смена своего пароля.
  return lastOverview?.ssh_access?.sudo_capable !== false;
}

function qsNoRightsBlock() {
  return '<div class="qs-no-rights">🔒 У вас нет прав суперпользователя, этот пункт меню вам недоступен</div>';
}

const QS_NAV = [
  { id: 'system', icon: '📦', title: 'Система', subtitle: 'Сведения и обновления', panel: 'qs-sec-system' },
  { id: 'ssh', icon: '🔐', title: 'SSH / Доступ', subtitle: 'Пользователь и порт', panel: 'qs-sec-ssh' },
  { id: 'firewall', icon: '🔥', title: 'Firewall', subtitle: 'Порты и backend', panel: 'qs-sec-firewall' },
  { id: 'fail2ban', icon: '🛡', title: 'Fail2ban', subtitle: 'SSH jail', panel: 'qs-sec-fail2ban' },
  { id: 'packages', icon: '🧰', title: 'Пакеты', subtitle: 'Установка ПО', panel: 'qs-sec-packages' },
];

function renderQsNav() {
  const nav = document.getElementById('qs-nav');
  if (!nav) return;
  nav.innerHTML = QS_NAV.map((c) => `
    <button type="button" data-qs-section="${c.id}" class="${c.id === activeSection ? 'on' : ''}">
      <span class="settings-nav-icon">${c.icon}</span>
      <span><strong>${esc(c.title)}</strong><small>${esc(c.subtitle)}</small></span>
    </button>
  `).join('');
  nav.querySelectorAll('[data-qs-section]').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeSection = btn.getAttribute('data-qs-section') || 'system';
      applyQsSection();
    });
  });
}

function applyQsSection() {
  const map = Object.fromEntries(QS_NAV.map((c) => [c.id, c.panel]));
  const want = map[activeSection] || 'qs-sec-system';
  document.querySelectorAll('#qs-body .qs-panel').forEach((el) => {
    el.hidden = el.id !== want;
  });
  document.querySelectorAll('#qs-nav [data-qs-section]').forEach((btn) => {
    btn.classList.toggle('on', btn.getAttribute('data-qs-section') === activeSection);
  });
}


function row(label, value, actionsHtml = '') {
  return `<div class="qs-row">
    <span class="qs-row-label">${esc(label)}</span>
    <span class="qs-row-value">${value}</span>
    <span class="qs-row-actions">${actionsHtml || ''}</span>
  </div>`;
}

function renderSystem(sys, d, local) {
  const name = local?.name ?? d?.name;
  const group = local?.group ?? d?.group;
  const nameRow = `<div class="qs-row qs-setting-row">
    <span class="qs-row-label"><strong>Имя</strong><small>отображается в списке серверов</small></span>
    <span class="qs-row-value qs-setting-control">
      <input id="qs-set-name" value="${esc(String(name || ''))}" style="width:11rem" maxlength="64">
      <button type="button" class="qs-compact" id="qs-set-name-btn">Сохранить</button>
    </span>
  </div>`;
  const groupOptions = (local?.groups?.length ? local.groups : (group ? [group] : []))
    .map(g => `<option value="${esc(g)}" ${g === group ? 'selected' : ''}>${esc(g)}</option>`)
    .join('');
  const groupRow = `<div class="qs-row qs-setting-row">
    <span class="qs-row-label"><strong>Группа</strong><small>категория сервера в списке</small></span>
    <span class="qs-row-value qs-setting-control">
      <select id="qs-set-group" style="width:11rem">${groupOptions || '<option value="">—</option>'}</select>
      <button type="button" class="qs-compact" id="qs-set-group-btn">Сохранить</button>
    </span>
  </div>`;
  // Проверять SSL — как в старой модалке «Изменить настройки»: чекбокс
  // раскрывает поле домена на той же строке (справа от чекбокса).
  // Пустой домен = проверка по host.
  const sslEnabled = !!local?.ssl_enabled;
  const sslRow = `<div class="qs-row qs-setting-row">
    <span class="qs-row-label"><strong>Проверять SSL</strong><small>домен для проверки; пусто — по host, стереть и сохранить = удалить</small></span>
    <span class="qs-row-value qs-setting-control">
      <input type="checkbox" id="qs-set-cert"${sslEnabled ? ' checked' : ''}>
      <span class="qs-ssl-host${sslEnabled ? '' : ' hidden'}" id="qs-set-ssl-wrap">
        <input id="qs-set-ssl" value="${esc(String(local?.ssl_host || ''))}" style="width:9.5rem" maxlength="255" placeholder="domain.com">
        <button type="button" class="qs-compact" id="qs-set-ssl-btn">Сохранить</button>
      </span>
    </span>
  </div>`;
  let updates = '—';
  let updatesAvailable = false;
  if (sys?.updates_available === true) {
    updatesAvailable = true;
    // updates_summary вида «доступны (5)» — вынимаем число для человекочитаемого текста
    const count = (sys.updates_summary?.match(/\d+/) || [])[0];
    updates = '<span class="qs-status-dot qs-status-dot-warn"></span>'
      + (count ? `Доступно ${count} пакетов к обновлению` : 'Доступно обновление пакетов');
  } else if (sys?.updates_available === false) {
    updates = statusDot(true) + esc(sys.updates_summary || 'система актуальна');
  } else if (sys?.updates_summary) {
    updates = esc(sys.updates_summary);
  }
  if (sys?.error) {
    updates += ` <span class="qs-muted">(${esc(sys.error)})</span>`;
  }
  // Пока не проверяли — показываем время последней проверки вместо статуса
  if (sys?.updates_available == null && sys?.last_check) {
    updates = `<span class="qs-muted">последняя проверка: ${esc(formatServerDateTime(sys.last_check, { seconds: true }))}</span>`;
  }
  const upgradeBtn = updatesAvailable
    ? '<button type="button" class="qs-updates-upgrade" id="qs-btn-upgrade">Обновить</button>'
    : '';

  const sshMark = d?.ssh_ok
    ? statusDot(true) + 'Доступен'
    : d
      ? statusDot(false) + 'Недоступен' + (d.ssh_error ? ` <span class="qs-muted">(${esc(d.ssh_error)})</span>` : '')
      : '—';
  const port = d?.ssh_port != null ? String(d.ssh_port) : '—';
  const sshLine = d ? `${sshMark} <span class="qs-meta-sep">|</span> ${esc(port)}` : '—';

  const cpu = d
    ? ([d.cpu_model, d.cpu_cores != null ? `${d.cpu_cores} cores` : null].filter(Boolean).map(esc).join(' · ') || '—')
    : '—';
  const osLine = d
    ? ([d.os, d.os_version && d.os_version !== '—' ? d.os_version : null].filter(Boolean).map(esc).join(' ') || '—')
    : '—';

  return section('📦 Система', `
    <div class="qs-rows">
      ${row('OS', osLine)}
      ${row('CPU', cpu)}
      ${row('RAM', esc(d?.ram || '—'))}
      ${row('Disk', esc(d?.disk || '—'))}
      ${row('Uptime', esc(d?.uptime || '—'))}
      ${row('SSH', sshLine)}
    </div>
    <div class="qs-subhead qs-subhead-div">Обновления</div>
    <div class="qs-rows">
      <div class="qs-row">
        <span class="qs-row-label">Пакеты</span>
        <span class="qs-row-value">${updates}${upgradeBtn}</span>
        <span class="qs-row-actions">
          <button type="button" class="qs-pkg-install qs-updates-check" id="qs-btn-check-updates">проверить</button>
        </span>
      </div>
    </div>
    <div class="qs-subhead qs-subhead-div">Сервер</div>
    <div class="qs-rows">
      ${nameRow}
      ${groupRow}
      ${sslRow}
    </div>
  `, 'qs-sec-system');
}

function _fwActiveCandidates(fw) {
  const list = Array.isArray(fw?.backends) ? fw.backends : [];
  return list.filter(c => c && c.active === true && c.backend);
}

function _fwHasConflict(fw = lastOverview?.firewall) {
  return _fwActiveCandidates(fw).length > 1;
}

function _fwConflictNames(fw = lastOverview?.firewall) {
  return _fwActiveCandidates(fw)
    .map(c => c.label || c.backend)
    .join(', ');
}

async function _confirmFwConflict(context, operation) {
  if (!_fwHasConflict()) return false;
  const names = _fwConflictNames();
  return confirmAction({
    title: 'Несколько активных firewall',
    message: `Конфликт всё ещё присутствует (${names}). ${operation} будет выполнена во всех активных поддерживаемых firewall. Продолжить?`,
    confirmText: 'Продолжить',
    cancelText: 'Отмена',
    confirmFirst: true,
  }).then(approved => !!approved && contextIsCurrent(context));
}

function _fwPortFormHtml() {
  return `
      <div class="qs-port-form">
        <label>Source IP
          <input type="text" id="qs-fw-source" class="qs-fw-source-input" placeholder="С какого IP разрешить вход">
          <small id="qs-fw-source-hint" class="qs-muted qs-fw-source-hint">Не указано — с любого IP</small>
        </label>
        <label>Протокол
          <select id="qs-fw-proto">
            <option value="tcp">TCP</option>
            <option value="udp">UDP</option>
            <option value="any">ANY</option>
          </select>
        </label>
        <label>Порт <input type="number" id="qs-fw-port" min="1" max="65535" placeholder="443"></label>
        <button type="button" id="qs-fw-open">➕ Открыть</button>
        <button type="button" class="secondary" id="qs-fw-list">📋 Правила</button>
      </div>`;
}

const FW_SOURCE_HINT_ANY = 'Не указано — с любого IP';
const FW_SOURCE_HINT_INVALID = 'Введён неверный IP адрес';

function _fwSourceHostValid(host) {
  if (host.includes(':')) {
    // IPv6: hex-сегменты до 4 знаков, не более одного «::»
    return /^[0-9A-Fa-f:]+$/.test(host)
      && (host.match(/::/g) || []).length <= 1
      && host.split(':').every(part => part.length <= 4);
  }
  const octets = host.split('.');
  return octets.length === 4
    && octets.every(octet => /^\d{1,3}$/.test(octet) && Number(octet) <= 255);
}

function _fwSourceValid(value) {
  const raw = String(value || '').trim();
  if (!raw) return true;
  const parts = raw.split('/');
  if (parts.length > 2) return false;
  if (!_fwSourceHostValid(parts[0])) return false;
  if (parts.length === 2) {
    const prefix = parts[1];
    if (!/^\d{1,3}$/.test(prefix)) return false;
    const max = parts[0].includes(':') ? 128 : 32;
    if (Number(prefix) > max) return false;
  }
  return true;
}

function _fwAutoDotValue(value, previous) {
  // Автоточка — только для IPv4-ввода; IPv6 (":") и CIDR ("/") не трогаем.
  // Точка не дублируется, когда её ставит сам пользователь.
  if (value.includes(':') || value.includes('/')) return value;
  const collapsed = value.replace(/\.\.+/g, '.');
  const segments = collapsed.split('.');
  const inserted = value.length > String(previous || '').length;
  if (
    inserted
    && segments.length < 4
    && /^\d{3}$/.test(segments[segments.length - 1])
  ) {
    return `${collapsed}.`;
  }
  return collapsed;
}

function _fwSourceRefresh() {
  const source = document.getElementById('qs-fw-source');
  const hint = document.getElementById('qs-fw-source-hint');
  const open = document.getElementById('qs-fw-open');
  if (!source) return;
  const valid = _fwSourceValid(source.value);
  source.classList.toggle('qs-invalid', !valid);
  if (hint) {
    hint.textContent = valid ? FW_SOURCE_HINT_ANY : FW_SOURCE_HINT_INVALID;
    hint.classList.toggle('qs-invalid', !valid);
  }
  if (open) open.disabled = !valid;
}

function _fwOnSourceInput() {
  const source = document.getElementById('qs-fw-source');
  if (!source) return;
  const previous = source.dataset.autodotPrev || '';
  const next = _fwAutoDotValue(source.value, previous);
  if (next !== source.value) source.value = next;
  source.dataset.autodotPrev = source.value;
  _fwSourceRefresh();
}

function _fwBackendLabel(name) {
  return ({ ufw: 'UFW', firewalld: 'firewalld', nftables: 'nftables' })[name] || name;
}

function _fwNftablesChainSelection(fw = lastOverview?.firewall) {
  const nftables = (Array.isArray(fw?.backends) ? fw.backends : [])
    .find(item => item?.backend === 'nftables');
  const selection = nftables?.chain_selection;
  if (selection?.required !== true || !Array.isArray(selection.candidates)) return null;
  const candidates = selection.candidates.filter(candidate => candidate
    && ['family', 'table', 'chain'].every(field => (
      typeof candidate[field] === 'string' && candidate[field].length > 0
    )));
  return candidates.length ? { candidates } : null;
}

function _fwNftablesChainChoicesHtml(candidates) {
  return candidates.map((candidate, index) => `<div class="qs-list-row">
    <span>${esc(candidate.family)} / ${esc(candidate.table)} / ${esc(candidate.chain)}</span>
    <button type="button" class="secondary" data-fw-chain-index="${index}">Выбрать</button>
  </div>`).join('');
}

function _fwAvailableBackendsHtml(fw) {
  const candidates = new Map(
    (Array.isArray(fw?.backends) ? fw.backends : [])
      .filter(item => item?.backend)
      .map(item => [String(item.backend), item]),
  );
  const anyActive = fw?.active === true || _fwActiveCandidates(fw).length > 0;
  const rows = ['nftables', 'ufw', 'firewalld'].map((name) => {
    const candidate = candidates.get(name);
    const installed = Boolean(candidate) || candidate?.installed === true;
    const isActive = candidate?.active === true;
    const status = isActive
      ? statusDot(true) + 'Активен'
      : (installed ? 'Доступен' : 'Не установлен');
    const buttons = [];
    if (!installed) {
      buttons.push(`<button type="button" data-fw-target="${esc(name)}" data-fw-action="install">Установить и активировать</button>`);
    } else {
      if (!isActive) {
        const action = anyActive ? 'use' : 'enable';
        const label = anyActive ? 'Переключить' : 'Включить';
        buttons.push(`<button type="button" data-fw-target="${esc(name)}" data-fw-action="${action}">${label}</button>`);
      }
      buttons.push(`<button type="button" class="secondary" data-fw-remove="${esc(name)}">Удалить</button>`);
    }
    // Порядок строк: активный → установленные (не активны) → не установленные
    const rank = isActive ? 0 : (installed ? 1 : 2);
    return {
      rank,
      html: `<div class="qs-fw-candidate" data-fw-backend="${esc(name)}">
      <span class="qs-fw-candidate-name">${esc(_fwBackendLabel(name))} <small class="qs-muted">${status}</small></span>
      <span class="qs-fw-candidate-actions">${buttons.join('')}</span>
    </div>`,
    };
  })
    .sort((a, b) => a.rank - b.rank)
    .map((row) => row.html)
    .join('');
  return `<div id="qs-fw-available" class="qs-fw-candidates">${rows}</div>`;
}

function renderFirewall(fw, rules) {
  if (!qsAdminRights()) return section('🔥 Firewall', qsNoRightsBlock(), 'qs-sec-firewall');
  const backend = fw?.backend;
  const active = fw?.active;
  const activeCandidates = _fwActiveCandidates(fw);
  const ambiguous = !backend && activeCandidates.length > 1;

  const activeRows = ambiguous
    ? `<div class="qs-fw-conflict">
        <strong>Обнаружено несколько активных firewall</strong>
        <span>${activeCandidates.map(item => esc(item.label || _fwBackendLabel(item.backend))).join(', ')}</span>
      </div>`
    : '';
  const chainSelectionAction = _fwNftablesChainSelection(fw)
    ? `<div class="qs-fw-conflict">
        <strong>Для nftables требуется выбрать существующую input chain</strong>
        <span>Выберите цепочку перед использованием nftables.</span>
        <div class="qs-section-actions">
          <button type="button" id="qs-fw-select-nftables-chain">Выбрать цепочку</button>
        </div>
      </div>`
    : '';
  const actions = (backend && active === true) || ambiguous
    ? _fwPortFormHtml()
    : '';
  const headActions = backend && active === true && !ambiguous
    ? '<button type="button" class="qs-btn-danger-outline" id="qs-fw-disable">⏸ Отключить firewall</button>'
    : '';
  const errorNote = !ambiguous && !backend && fw?.error
    ? `<p class="qs-muted">Состояние firewall не определено (${esc(fw.error)}); управление правилами остановлено.</p>`
    : '';
  const inactiveNote = !ambiguous && !backend && !fw?.error && active === false
    ? '<p class="qs-muted">Firewall не активен: трафик не фильтруется.</p>'
    : '';

  const body = `
    ${activeRows}
    ${chainSelectionAction}
    ${errorNote}
    ${inactiveNote}
    ${actions}
    <h4>Доступные firewall</h4>
    ${_fwAvailableBackendsHtml(fw)}`;
  return section('🔥 Firewall', body, 'qs-sec-firewall', headActions);
}

async function onFwSaveNftablesChain(candidate, context) {
  if (busy || !contextIsCurrent(context)) return;
  const { serverId } = context;
  const token = {
    family: candidate.family,
    table: candidate.table,
    chain: candidate.chain,
  };
  setBusy(true, context);
  try {
    const result = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/nftables/chain`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(token),
      },
    );
    if (!result.ok) {
      showContextToast(
        context,
        result.message || result.error || 'Цепочка nftables не сохранена',
        false,
      );
      return;
    }
    closeQsListModal();
    await reloadOverview({ updates: false }, context);
    showContextToast(context, result.message || 'Цепочка nftables сохранена', true);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка выбора nftables chain', false);
  } finally {
    setBusy(false, context);
  }
}

function onFwSelectNftablesChain() {
  const context = captureContext();
  if (busy || !context) return;
  const selection = _fwNftablesChainSelection();
  if (!selection) return;
  openQsListModal(
    'Выберите цепочку nftables',
    _fwNftablesChainChoicesHtml(selection.candidates),
  );
  document.querySelectorAll('[data-fw-chain-index]').forEach((button) => {
    button.addEventListener('click', () => {
      const candidate = selection.candidates[Number(button.dataset.fwChainIndex)];
      if (candidate) onFwSaveNftablesChain(candidate, context);
    });
  });
}

async function onFwSwitch(target) {
  const context = captureContext();
  if (busy || !context || !target) return;
  const { serverId } = context;
  const approved = await confirmAction({
    title: `Переключить на ${_fwBackendLabel(target)}?`,
    message: `Вы хотите переключиться на ${_fwBackendLabel(target)} как активный firewall?`,
    confirmText: 'Переключить',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  await executeFwTransaction(
    _fwSwitchTransaction(serverId, target),
    context,
  );
}

// Категории каталога пакетов (backend отдаёт category в PackageItem)
const PKG_CATEGORY_TITLES = {
  utils: 'Утилиты',
  net: 'Сеть',
  diag: 'Диагностика',
  services: 'Сервисы',
};

function renderPackages(pkg) {
  if (!qsAdminRights()) return section('🧰 Пакеты', qsNoRightsBlock(), 'qs-sec-packages');
  const items = pkg?.items || [];
  // Группировка по категориям; порядок групп фиксирован, пустые скрыты
  const order = ['utils', 'net', 'diag', 'services'];
  const groups = new Map(order.map(c => [c, []]));
  for (const i of items) {
    const cat = groups.has(i.category) ? i.category : 'utils';
    groups.get(cat).push(i);
  }
  const blocks = [...groups.entries()]
    .filter(([, rows]) => rows.length)
    .map(([cat, rows]) => {
      const title = PKG_CATEGORY_TITLES[cat] || 'Прочее';
      // Сервисы после установки могут запуститься и начать принимать
      // соединения — предупреждаем; firewall затрагивать не собираемся.
      const warn = cat === 'services'
        ? '<p class="qs-muted">⚠️ Сервис после установки может быть автоматически запущен и начать принимать соединения.</p>'
        : '';
      const list = rows
        // Неустановленные сверху, установленные под ними; внутри блока —
        // по алфавиту. Выбор «что поставить» важнее уже сделанного.
        .slice()
        .sort((a, b) => (a.installed - b.installed) || a.name.localeCompare(b.name))
        .map(i => {
        // Установленный — яркий зелёный чип, неустановленный — тусклый
        const mark = i.installed
          ? '<span class="qs-pkg-st on">● установлен</span>'
          : '<span class="qs-pkg-st">○ не установлен</span>';
        // Установленные — недоступны; НЕустановленные НЕ отмечены
        // галочкой по умолчанию: выбор всегда за пользователем.
        // Инлайн-кнопка «установить» видна только у отмеченных строк —
        // до отмечания строка остаётся чистой.
        const disabled = i.installed ? 'disabled' : '';
        // Кнопка ПЕРЕД индикатором «○ не установлен»; появляется (hidden
        // снимается) только на строках с отмеченным чек-боксом.
        const installBtn = i.installed ? '' : '<button type="button" class="qs-pkg-install" data-pkg-install="' + esc(i.name) + '" hidden>установить</button>';
        return `<label class="qs-pkg-row">
          <input type="checkbox" data-pkg="${esc(i.name)}" ${disabled}>
          <span class="qs-pkg-name">${esc(i.name)}</span>
          <span class="qs-pkg-st-wrap">${installBtn}${mark}</span>
        </label>`;
      }).join('');
      return `<div class="qs-pkg-group">
        <div class="qs-pkg-group-title">${esc(title)}</div>
        ${warn}
        ${list}
      </div>`;
    }).join('');
  const body = blocks || '<span class="qs-muted">Нет данных</span>';
  const err = pkg?.error ? `<p class="qs-muted">${esc(pkg.error)}</p>` : '';
  return section('🧰 Пакеты', `
    ${err}
    ${body}
    <div class="qs-section-actions">
      <button type="button" id="qs-btn-pkg-install">Установить выбранные</button>
      <button type="button" class="secondary" id="qs-btn-pkg-refresh">Обновить список</button>
    </div>
  `, 'qs-sec-packages');
}



function renderSshAccess(s) {
  const err = s?.error ? ` <span class="qs-muted">(${esc(s.error)})</span>` : '';
  const pwdRaw = (s?.password_auth || '').toLowerCase();
  const pwdOn = pwdRaw.includes('разреш') || pwdRaw === 'yes';
  const pwdStatus = s?.password_auth
    ? statusDot(pwdOn) + esc(s.password_auth)
    : '—';
  const rootRaw = (s?.root_login || '').toLowerCase();
  const rootOn = rootRaw.includes('разреш') || rootRaw === 'yes';
  const rootStatus = s?.root_login
    ? statusDot(rootOn && !rootRaw.includes('только')) + esc(s.root_login)
    : '—';
  const authType = s?.auth_type === 'key' ? 'SSH-ключ' : 'Пароль';
  // Password-auth выключен на сервере (или не прочитан): паролем войти
  // нельзя — единственный вариант, локальный ключ Bot4VPS.
  const pwdAuthOff = s?.password_auth && !pwdOn;
  const switchHint = pwdAuthOff
    ? 'На сервере выключена авторизация по паролю: вход выполняется выбранным локальным ключом Bot4VPS. Пароль целевого пользователя нужен только для sudo, если NOPASSWD не настроен.'
    : 'Выберите способ авторизации: «Паролю» — вход паролем целевого пользователя, «SSH-ключу» — выбранным локальным ключом Bot4VPS. Этот выбор меняет тип авторизации в servers.json. Пароль текущего аккаунта не переиспользуется.';
  const pwdBtnLabel = pwdOn ? 'Выключить password auth' : 'Включить password auth';
  const rootBtnLabel = rootOn ? 'Запретить root login' : 'Разрешить root login';
  // Административные блоки — только при подтверждённом sudo; без него
  // пользователь управляет лишь собственной SSH-авторизацией.
  const isAdmin = s?.sudo_capable !== false;
  const createUserBlock = `
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">👤 Создать пользователя</div>
        <div class="qs-port-form qs-ssh-inline">
          <input id="qs-ssh-newuser" autocomplete="username" placeholder="имя" style="width:8rem">
          <span class="qs-pass-wrap"><input id="qs-ssh-newuser-pass" type="password" autocomplete="new-password" placeholder="пароль (необязательно)" style="width:12rem">${qsPassEye('qs-ssh-newuser-pass')}</span>
          <label><input type="checkbox" id="qs-ssh-newuser-sudo"> sudo</label>
          <button type="button" class="qs-compact" id="qs-ssh-create-user">Создать</button>
          <button type="button" class="secondary qs-compact" id="qs-ssh-users">Пользователи</button>
        </div>
        <p class="qs-muted">Создание не переключает Bot4VPS на новый аккаунт.</p>
      </div>`;
  const ownPasswordBlock = `
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">🔑 Сменить текущий пароль</div>
        <div class="qs-section-actions">
          <button type="button" class="secondary" id="qs-ssh-set-own-pass">Сменить пароль</button>
        </div>
        <p class="qs-muted">Пароль меняется под вашим пользователем (без sudo) и проверяется реальным SSH-входом.</p>
      </div>`;
  const portBlock = `
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">🚪 SSH-порт</div>
        <div class="qs-port-form">
          <input type="number" id="qs-ssh-port" min="1" max="65535" value="${esc(String(s?.port ?? 22))}" style="width:5.5rem">
          <button type="button" class="qs-compact" id="qs-ssh-set-port">Изменить порт</button>
        </div>
      </div>`;
  const rootPwdBlock = `
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">👑 Вход root / 🔓 Аутентификация по паролю</div>
        <div class="qs-section-actions">
          <button type="button" class="secondary" id="qs-ssh-root-toggle" data-enabled="${rootOn ? '1' : '0'}">${rootBtnLabel}</button>
          <button type="button" class="secondary" id="qs-ssh-pwdauth-toggle" data-enabled="${pwdOn ? '1' : '0'}">${pwdBtnLabel}</button>
        </div>
      </div>`;
  const hostKeyBlock = `
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">🛡 SSH host key</div>
        <div class="qs-rows">
          ${row('Тип ключа', s?.host_key_type ? esc(s.host_key_type) : '—')}
          ${row('Отпечаток', s?.host_key_fingerprint
            ? `<code style="overflow-wrap:anywhere">${esc(s.host_key_fingerprint)}</code>`
            : statusDot() + 'не закреплён — запишется при первом подключении')}
        </div>
        ${s?.host_key_mismatch ? `
        <p class="qs-muted" style="color:var(--err)">Сервер предъявил другой host key — подключения заблокированы, пароль не отправлялся. Если сервер переустановлен, примите текущий ключ.</p>
        <div class="qs-section-actions">
          <button type="button" class="secondary" id="qs-ssh-hostkey-accept">Принять текущий ключ</button>
        </div>` : ''}
        <p class="qs-muted">Каждое подключение сверяется с сохранённым host key до отправки пароля. Кнопка принятия появляется, только если сервер предъявил другой ключ (например, после переустановки ОС).</p>
      </div>`;
  return section('🔐 SSH / Доступ', `
    <div class="qs-rows">
      ${row('Пользователь', esc(s?.user || '—') + err)}
      ${row('Метод входа', esc(authType))}
      ${row('SSH-порт', esc(String(s?.port ?? '—')))}
      ${row('Вход root', rootStatus)}
      ${row('Аутентификация по паролю', pwdStatus)}
    </div>
    <div class="qs-ssh-forms">
      ${isAdmin ? createUserBlock : ownPasswordBlock}
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">↪ Переключить пользователя</div>
        ${!pwdAuthOff ? `
        <div class="qs-port-form qs-ssh-auth-row">
          <label for="qs-ssh-switch-auth">Авторизоваться по:</label>
          <select id="qs-ssh-switch-auth" style="width:9rem">
            <option value="password">паролю</option>
            <option value="key">SSH-ключу</option>
          </select>
        </div>` : ''}
        <div class="qs-port-form">
          <input id="qs-ssh-switch-user" autocomplete="username" placeholder="существующий пользователь" style="width:12rem">
          <select id="qs-ssh-switch-key" style="width:13rem${!pwdAuthOff ? ';display:none' : ''}"><option value="">— выбрать ключ —</option></select>
          <span class="qs-pass-wrap"><input id="qs-ssh-switch-pass" type="password" autocomplete="current-password" placeholder="пароль целевого пользователя" style="width:13rem">${qsPassEye('qs-ssh-switch-pass')}</span>
          <button type="button" class="qs-compact" id="qs-ssh-switch-user-btn">Переключить</button>
        </div>
        <p class="qs-muted">${esc(switchHint)}</p>
      </div>
      ${isAdmin ? portBlock : ''}
      <div class="qs-ssh-block">
        <div class="qs-ssh-block-title">🔐 SSH-ключи доступа</div>
        <div class="qs-rows">${row('SSH-key статус', !s?.key_configured
          ? statusDot() + 'не прописан'
          : s?.key_present === false
            ? statusDot(false) + 'запись устарела: ключ не найден на сервере (для текущего пользователя)'
            : statusDot(true) + (s?.key_present === true
              ? 'прописан — ключ подтверждён на сервере'
              : 'прописан в servers.json — Bot4VPS сможет войти по этому ключу'))}</div>
        <div class="qs-section-actions">
          <button type="button" id="qs-ssh-key-manager">Менеджер ключей</button>
        </div>
        <p class="qs-muted qs-ssh-keys-hint">Создание ключа и удаление — в «Менеджере ключей»${isAdmin ? '' : ' (доступны только ваши ключи)'}.</p>
      </div>
      ${hostKeyBlock}
      ${isAdmin ? rootPwdBlock : ''}
    </div>
    <p class="qs-muted">Опасные изменения блокируются, пока не подтверждён запасной SSH/sudo-доступ.</p>
  `, 'qs-sec-ssh');
}

const F2B_BAN_TIME_OPTIONS = ['10m', '1h', '6h', '1d', '1w'];
const F2B_FIND_TIME_OPTIONS = ['1m', '5m', '10m', '1h', '1d'];
const F2B_MAX_RETRY_OPTIONS = [3, 5, 7, 10];
const F2B_PRESET = { banTime: '1h', findTime: '10m', maxRetry: 5 };

const F2B_DURATION_UNITS = [
  { seconds: 604800, one: 'неделя', few: 'недели', many: 'недель' },
  { seconds: 86400, one: 'день', few: 'дня', many: 'дней' },
  { seconds: 3600, one: 'час', few: 'часа', many: 'часов' },
  { seconds: 60, one: 'минута', few: 'минуты', many: 'минут' },
  { seconds: 1, one: 'секунда', few: 'секунды', many: 'секунд' },
];

function f2bPluralForm(amount, one, few, many) {
  const mod10 = amount % 10;
  const mod100 = amount % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

// Токены того же формата, что принимает backend: [1-9]\d{0,8}(s|m|h|d|w)?
function parseF2bDurationSeconds(raw) {
  const value = String(raw ?? '').trim().toLowerCase();
  const match = value.match(/^([1-9][0-9]{0,8})(s|m|h|d|w)?$/);
  if (!match) return null;
  const factor = { s: 1, m: 60, h: 3600, d: 86400, w: 604800 }[match[2] || 's'];
  return parseInt(match[1], 10) * factor;
}

function formatF2bDurationRu(raw) {
  let seconds = parseF2bDurationSeconds(raw);
  if (seconds == null) {
    const fallback = String(raw ?? '').trim();
    return fallback || '—';
  }
  const parts = [];
  for (const unit of F2B_DURATION_UNITS) {
    if (parts.length >= 2) break;
    const amount = Math.floor(seconds / unit.seconds);
    if (amount > 0) {
      seconds -= amount * unit.seconds;
      parts.push(`${amount} ${f2bPluralForm(amount, unit.one, unit.few, unit.many)}`);
    }
  }
  return parts.join(' ') || 'меньше секунды';
}

function f2bDurationSelectHtml(id, label, options, current) {
  const raw = String(current ?? '').trim();
  const currentSeconds = parseF2bDurationSeconds(raw);
  const items = [];
  let selected = false;
  for (const token of options) {
    const seconds = parseF2bDurationSeconds(token);
    if (seconds == null) continue;
    const isSelected = !selected && currentSeconds != null && seconds === currentSeconds;
    if (isSelected) selected = true;
    items.push(`<option value="${esc(token)}"${isSelected ? ' selected' : ''}>${esc(formatF2bDurationRu(token))}</option>`);
  }
  if (currentSeconds != null && !selected) {
    selected = true;
    items.push(`<option value="${esc(raw)}" selected>${esc(formatF2bDurationRu(raw))} · ${esc(raw)}</option>`);
  } else if (raw && currentSeconds == null) {
    selected = true;
    items.push(`<option value="${esc(raw)}" selected>${esc(raw)}</option>`);
  }
  const placeholderLabel = !raw ? 'неизвестно' : 'не менять';
  items.unshift(`<option value=""${selected ? '' : ' selected'}>${placeholderLabel}</option>`);
  return `<select id="${esc(id)}" aria-label="${esc(label)}">${items.join('')}</select>`;
}

function f2bRetrySelectHtml(current) {
  const raw = current == null ? '' : String(current).trim();
  const value = /^[0-9]+$/.test(raw) ? parseInt(raw, 10) : null;
  const items = [];
  let selected = false;
  for (const option of F2B_MAX_RETRY_OPTIONS) {
    const isSelected = !selected && value === option;
    if (isSelected) selected = true;
    items.push(`<option value="${option}"${isSelected ? ' selected' : ''}>${option}</option>`);
  }
  if (value != null && !selected) {
    selected = true;
    items.push(`<option value="${value}" selected>${value}</option>`);
  }
  const placeholderLabel = value == null ? 'неизвестно' : 'не менять';
  items.unshift(`<option value=""${selected ? '' : ' selected'}>${placeholderLabel}</option>`);
  return `<select id="qs-f2b-maxretry" aria-label="Max retries">${items.join('')}</select>`;
}

function f2bSettingRow(label, description, controlHtml) {
  return `<div class="qs-row qs-setting-row">
    <span class="qs-row-label"><strong>${esc(label)}</strong><small>${esc(description)}</small></span>
    <span class="qs-row-value qs-setting-control">${controlHtml}</span>
  </div>`;
}

function f2bPresetStatus(fb) {
  const banSeconds = parseF2bDurationSeconds(fb?.ban_time);
  const findSeconds = parseF2bDurationSeconds(fb?.find_time);
  const maxRetry = fb?.max_retry;
  if (banSeconds == null || findSeconds == null || maxRetry == null) {
    return { level: 'unknown', text: 'Текущие параметры неизвестны, пока правило блокировки SSH неактивно' };
  }
  const recommended = banSeconds === parseF2bDurationSeconds(F2B_PRESET.banTime)
    && findSeconds === parseF2bDurationSeconds(F2B_PRESET.findTime)
    && maxRetry === F2B_PRESET.maxRetry;
  return recommended
    ? { level: 'ok', text: 'Используются рекомендуемые настройки' }
    : { level: 'diff', text: 'Настройки отличаются от рекомендуемых' };
}

function f2bStatusErrorNote(fb) {
  const error = String(fb?.error || '').trim();
  if (!error) return '';
  const short = ['running', 'stopped', 'absent'].includes(fb?.state)
    ? 'Не удалось получить состояние Fail2ban полностью'
    : 'Не удалось получить состояние Fail2ban';
  return ` <span class="qs-muted">· ${esc(short)}</span>
    <details class="qs-f2b-error"><summary>Подробнее</summary><pre>${esc(error)}</pre></details>`;
}

function renderFail2ban(fb) {
  if (!qsAdminRights()) return section('🛡 Fail2ban', qsNoRightsBlock(), 'qs-sec-fail2ban');
  const installed = !!fb?.installed;
  const running = fb?.running === true;
  const stopped = installed && fb?.running === false;
  const state = fb?.state || (installed ? (running ? 'running' : 'stopped') : 'absent');
  let statusVal;
  if (state === 'running') {
    statusVal = statusDot(true) + 'Запущен';
  } else if (state === 'stopped') {
    statusVal = statusDot(false) + 'Остановлен';
  } else {
    statusVal = statusDot(null) + 'Не установлен';
  }
  const autostartLabel = fb?.autostart === true
    ? 'автозапуск включён'
    : fb?.autostart === false ? 'автозапуск выключен' : '';
  if (autostartLabel) statusVal += ` <span class="qs-meta-sep">·</span> <span class="qs-muted">${autostartLabel}</span>`;
  statusVal += f2bStatusErrorNote(fb);

  if (state === 'absent') {
    return section('🛡 Fail2ban', `
      <div class="qs-rows">${row('Fail2ban', statusVal)}</div>
      <p class="qs-muted">Fail2ban следит за журналами служб и временно блокирует IP-адреса, с которых идёт перебор паролей. Сервис не установлен. Установка не создаёт и не включает Правила блокировки автоматически.</p>
      <div class="qs-section-actions">
        <button type="button" id="qs-f2b-install">Установить</button>
      </div>
    `, 'qs-sec-fail2ban');
  }

  const serviceActions = state === 'running'
    ? '<button type="button" class="secondary" id="qs-f2b-stop">Остановить Fail2ban</button>'
    : '<button type="button" id="qs-f2b-start">Запустить Fail2ban</button>';
  const jailCount = fb?.jail_count != null ? String(fb.jail_count) : '—';
  const bannedCount = fb?.banned_count != null ? String(fb.banned_count) : '—';
  const preset = f2bPresetStatus(fb);

  const protectionSettings = `
    <div class="qs-subhead">Настройки защиты</div>
    <div class="qs-rows qs-f2b-protection">
      ${f2bSettingRow('Ban time', 'На сколько времени блокировать IP после нарушений', f2bDurationSelectHtml('qs-f2b-bantime', 'Ban time', F2B_BAN_TIME_OPTIONS, fb?.ban_time))}
      ${f2bSettingRow('Find time', 'За какой период учитывать неудачные попытки входа', f2bDurationSelectHtml('qs-f2b-findtime', 'Find time', F2B_FIND_TIME_OPTIONS, fb?.find_time))}
      ${f2bSettingRow('Max retries', 'Сколько неудачных попыток приводит к блокировке', f2bRetrySelectHtml(fb?.max_retry))}
    </div>
    <p class="qs-f2b-preset ${esc(preset.level)}">${esc(preset.text)}. Рекомендуется: ${F2B_PRESET.maxRetry} ${esc(f2bPluralForm(F2B_PRESET.maxRetry, 'попытка', 'попытки', 'попыток'))} · ${esc(formatF2bDurationRu(F2B_PRESET.findTime))} на попытки · блокировка на ${esc(formatF2bDurationRu(F2B_PRESET.banTime))}.</p>
    <div class="qs-section-actions">
      <button type="button" id="qs-f2b-apply">Применить</button>
    </div>`;

  const quickLists = `
    <div class="qs-subhead">Быстрые списки</div>
    <div class="qs-rows">
      ${row('Заблокированные IP', `${esc(bannedCount)} <span class="qs-muted">· адреса, заблокированные за нарушение правил</span>`, '<button type="button" class="secondary" id="qs-f2b-banned">Открыть список</button>')}
      ${row('Whitelist', '<span class="qs-muted">IP-адреса, которые Fail2ban никогда не блокирует</span>', '<button type="button" class="secondary" id="qs-f2b-whitelist">Открыть список</button>')}
    </div>`;

  const extraSettings = `
    <div class="qs-subhead">Дополнительно</div>
    <div class="qs-rows">
      ${row('Правила блокировки', `${esc(jailCount)} <span class="qs-muted">· какие службы защищает Fail2ban</span>`, '<button type="button" class="secondary" id="qs-f2b-jails">Настроить</button>')}
      ${row('Фильтры', '<span class="qs-muted">· какие события считаются нарушениями</span>', '<button type="button" class="secondary" id="qs-f2b-filters">Открыть</button>')}
      ${row('Конфигурация', '<span class="qs-muted">· файлы настроек Fail2ban для опытных пользователей</span>', '<button type="button" class="secondary" id="qs-f2b-configuration">Открыть</button>')}
    </div>`;

  const dangerZone = `
    <div class="qs-f2b-danger">
      <div class="qs-section-actions">
        ${serviceActions}
        <button type="button" class="secondary" id="qs-f2b-refresh">Обновить</button>
        <button type="button" class="secondary danger" id="qs-f2b-uninstall">Удалить Fail2ban</button>
      </div>
    </div>`;

  return section('🛡 Fail2ban', `
    <div class="qs-rows">
      ${row('Fail2ban', statusVal)}
    </div>
    ${protectionSettings}
    ${quickLists}
    ${extraSettings}
    ${dangerZone}
    <p class="qs-muted">Настройки защиты применяются только после успешной проверки конфигурации Fail2ban; при ошибке предыдущие значения восстанавливаются.</p>
  `, 'qs-sec-fail2ban');
}

function renderPlaceholder(title, text, id) {
  return section(title, `<p class="qs-placeholder">${esc(text)}</p>`, id);
}


function renderOverview(data) {
  lastOverview = data;
  const body = document.getElementById('qs-body');
  if (!body) return;
  const nameEl = document.getElementById('qs-server-name');
  const ipEl = document.getElementById('qs-server-ip');
  if (nameEl) nameEl.textContent = data.server_name || data.server_id || '—';
  if (ipEl) ipEl.textContent = data.host || '—';

  body.innerHTML = [
    renderSystem(data.system, data.diagnostics, data.local_settings),
    renderFirewall(data.firewall, data.firewall_rules || []),
    renderFail2ban(data.fail2ban),
    renderSshAccess(data.ssh_access),
    renderPackages(data.packages),
  ].join('');

  renderQsNav();
  applyQsSection();
  bindActions();
  fillSshSwitchKeySelect();
  maybeWarnSharedKey(data.ssh_access, data.server_id);
}

// Селект ключа в блоке «Переключить пользователя» (режим «SSH-ключу» или
// выключенная password-auth): заполняется локальными ключами бота в фоне,
// ошибка не критична. Идемпотентен: перед заполнением селект очищается —
// вызывается и при первичном рендере, и после onSshRefresh (секция
// перерисовывается, скрытый по умолчанию селект не должен оставаться пустым).
async function fillSshSwitchKeySelect() {
  const select = document.getElementById('qs-ssh-switch-key');
  if (!select) return;
  const context = captureContext();
  if (!context) return;
  try {
    const r = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(context.serverId)}/quick-setup/ssh/local-keys?scope=switch`,
    );
    if (!contextIsCurrent(context)) return;
    // Только если элемент всё ещё жив (секция не перерисована за время запроса)
    if (document.getElementById('qs-ssh-switch-key') !== select) return;
    const keys = (r.ok && r.data?.keys) || [];
    select.innerHTML = '<option value="">— выбрать ключ —</option>';
    keys.forEach((k) => {
      if (!k?.private_exists) return; // приватной части нет — войти нельзя
      const opt = document.createElement('option');
      opt.value = `/opt/bot4vps/keys/${k.name}`;
      opt.textContent = `🔑 ${k.name}${k.in_use ? ' (используется)' : ''}`;
      select.appendChild(opt);
    });
    if (select.options.length <= 1) {
      select.innerHTML = '<option value="">— нет ключей —</option>';
    }
  } catch { /* селект останется пустым — валидация не пустит */ }
}

function bindActions() {
  document.getElementById('qs-btn-check-updates')?.addEventListener('click', onCheckUpdates);
  document.getElementById('qs-btn-upgrade')?.addEventListener('click', onUpgrade);
  document.getElementById('qs-set-name-btn')?.addEventListener('click', onSetName);
  document.getElementById('qs-set-group-btn')?.addEventListener('click', onSetGroup);
  document.getElementById('qs-set-name')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') onSetName();
  });
  // SSL: чекбокс раскрывает/прячет строку домена и сразу применяет настройку
  document.getElementById('qs-set-cert')?.addEventListener('change', () => {
    const on = document.getElementById('qs-set-cert')?.checked === true;
    syncSslRow(on);
    onSetSslCheck();
  });
  document.getElementById('qs-set-ssl-btn')?.addEventListener('click', onSetSslHost);
  document.getElementById('qs-set-ssl')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') onSetSslHost();
  });
  document.getElementById('qs-btn-pkg-install')?.addEventListener('click', onPkgInstall);
  document.getElementById('qs-btn-pkg-refresh')?.addEventListener('click', onPkgRefresh);
  bindQsPkgRows();
  document.getElementById('qs-f2b-install')?.addEventListener('click', onF2bInstall);
  document.getElementById('qs-f2b-start')?.addEventListener('click', onF2bStart);
  document.getElementById('qs-f2b-stop')?.addEventListener('click', onF2bStop);
  document.getElementById('qs-f2b-uninstall')?.addEventListener('click', onF2bUninstall);
  document.getElementById('qs-f2b-jails')?.addEventListener('click', onF2bJails);
  document.getElementById('qs-f2b-filters')?.addEventListener('click', onF2bFilters);
  document.getElementById('qs-f2b-whitelist')?.addEventListener('click', onF2bWhitelist);
  document.getElementById('qs-f2b-configuration')?.addEventListener('click', onF2bConfiguration);
  document.getElementById('qs-ssh-create-user')?.addEventListener('click', onSshCreateUser);
  document.getElementById('qs-ssh-switch-user-btn')?.addEventListener('click', onSshSwitchUser);
  // Enter в поле пароля = «Переключить»; Enter в поле пользователя —
  // переход в поле пароля (переключаться без пароля/ключа нелогично)
  document.getElementById('qs-ssh-switch-user')?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    document.getElementById('qs-ssh-switch-pass')?.focus();
  });
  document.getElementById('qs-ssh-switch-pass')?.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter') return;
    ev.preventDefault();
    onSshSwitchUser();
  });
  // П3: «Авторизоваться по» — единственное место явной смены типа
  // авторизации. В режиме «SSH-ключу» показываем селект ключа, плейсхолдер
  // пароля меняется на sudo-подсказку (пароль при key-роуте — sudo-cred).
  document.getElementById('qs-ssh-switch-auth')?.addEventListener('change', () => {
    const keyMode = document.getElementById('qs-ssh-switch-auth')?.value === 'key';
    const keyEl = document.getElementById('qs-ssh-switch-key');
    if (keyEl) keyEl.style.display = keyMode ? '' : 'none';
    const passEl = document.getElementById('qs-ssh-switch-pass');
    if (passEl) passEl.placeholder = keyMode
      ? 'sudo-пароль цели (необязательно)'
      : 'пароль целевого пользователя';
  });
  document.getElementById('qs-ssh-users')?.addEventListener('click', onSshUsers);
  document.getElementById('qs-ssh-set-port')?.addEventListener('click', onSshPort);
  document.getElementById('qs-ssh-hostkey-accept')?.addEventListener('click', onSshHostKeyAccept);
  document.getElementById('qs-ssh-set-own-pass')?.addEventListener('click', onSshSetOwnPass);
  document.getElementById('qs-ssh-key-manager')?.addEventListener('click', onSshKeyManager);
  document.getElementById('qs-ssh-root-toggle')?.addEventListener('click', () => {
    const on = document.getElementById('qs-ssh-root-toggle')?.dataset?.enabled === '1';
    onSshRoot(!on);
  });
  document.getElementById('qs-ssh-pwdauth-toggle')?.addEventListener('click', () => {
    const on = document.getElementById('qs-ssh-pwdauth-toggle')?.dataset?.enabled === '1';
    onSshPwdAuth(!on);
  });
  document.getElementById('qs-f2b-apply')?.addEventListener('click', onF2bApply);
  document.getElementById('qs-f2b-banned')?.addEventListener('click', onF2bBanned);
  document.getElementById('qs-f2b-restart')?.addEventListener('click', onF2bRestart);
  document.getElementById('qs-f2b-refresh')?.addEventListener('click', onF2bRefresh);
  document.getElementById('qs-fw-source')?.addEventListener('input', _fwOnSourceInput);
  document.getElementById('qs-fw-open')?.addEventListener('click', () => onFwPort('open'));
  document.getElementById('qs-fw-list')?.addEventListener('click', onFwList);
  document.getElementById('qs-fw-disable')?.addEventListener('click', onFwDisable);
  document.getElementById('qs-fw-select-nftables-chain')?.addEventListener('click', onFwSelectNftablesChain);
  document.querySelectorAll('[data-fw-target]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.fwTarget;
      if (btn.dataset.fwAction === 'install') onFwInstall(target);
      else if (btn.dataset.fwAction === 'enable') onFwEnable(target);
      else onFwSwitch(target);
    });
  });
  document.querySelectorAll('[data-fw-remove]').forEach(btn => {
    btn.addEventListener('click', () => onFwRemove(btn.dataset.fwRemove));
  });
}

// Локальные поля servers.json (имя, группа) — PATCH /api/servers/{id},
// реальный SSH не нужен.
async function onSetName() {
  const context = captureContext();
  if (busy || !context) return;
  const input = document.getElementById('qs-set-name');
  const name = (input?.value || '').trim();
  if (!name) { showContextToast(context, 'Имя не может быть пустым', false); return; }
  setBusy(true, context);
  try {
    await requestForContext(context,
      `/api/servers/${encodeURIComponent(context.serverId)}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) },
    );
    showContextToast(context, 'Имя сохранено', true);
    await reloadOverview({ updates: false }, context);
  } catch (e) {
    showContextToast(context, e.message || 'Не удалось сохранить имя', false);
  } finally {
    setBusy(false, context);
  }
}

async function onSetGroup() {
  const context = captureContext();
  if (busy || !context) return;
  const group = document.getElementById('qs-set-group')?.value || '';
  setBusy(true, context);
  try {
    await requestForContext(context,
      `/api/servers/${encodeURIComponent(context.serverId)}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ group }) },
    );
    showContextToast(context, 'Группа сохранена', true);
    await reloadOverview({ updates: false }, context);
  } catch (e) {
    showContextToast(context, e.message || 'Не удалось сохранить группу', false);
  } finally {
    setBusy(false, context);
  }
}

// Показ/скрытие строки домена по чекбоксу «Проверять SSL».
function syncSslRow(on) {
  const wrap = document.getElementById('qs-set-ssl-wrap');
  if (wrap) wrap.classList.toggle('hidden', !on);
  if (on) setTimeout(() => document.getElementById('qs-set-ssl')?.focus(), 50);
}

// Чекбокс «Проверять SSL» — как в старой модалке «Изменить настройки»:
// PATCH certificate_check (сервер заодно пересобирает сертификат в
// monitor.json). При включении отправляем домен как есть: пустая строка
// на сервере означает «удалить домен» (проверка по host).
async function onSetSslCheck() {
  const context = captureContext();
  if (busy || !context) return;
  const box = document.getElementById('qs-set-cert');
  const on = box?.checked === true;
  const host = (document.getElementById('qs-set-ssl')?.value || '').trim();
  const body = on
    ? { certificate_check: true, ssl_host: host }
    : { certificate_check: false };
  setBusy(true, context);
  try {
    await requestForContext(context,
      `/api/servers/${encodeURIComponent(context.serverId)}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    );
    showContextToast(context, on ? 'Проверка SSL включена' : 'Проверка SSL выключена', true);
    await reloadOverview({ updates: false }, context);
  } catch (e) {
    showContextToast(context, e.message || 'Не удалось сохранить настройку SSL', false);
    if (box) box.checked = !on; // вернуть видимое состояние к сохранённому
    syncSslRow(!on);
  } finally {
    setBusy(false, context);
  }
}

// «Сохранить» в строке домена: домен + включённая проверка одним PATCH.
// Пустое поле — осмысленное действие: домен удаляется, проверка уходит
// по host сервера (раньше пустое молча не трогало старый домен).
async function onSetSslHost() {
  const context = captureContext();
  if (busy || !context) return;
  const host = (document.getElementById('qs-set-ssl')?.value || '').trim();
  setBusy(true, context);
  try {
    await requestForContext(context,
      `/api/servers/${encodeURIComponent(context.serverId)}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ certificate_check: true, ssl_host: host }) },
    );
    showContextToast(context, host ? 'Домен SSL сохранён' : 'Домен удалён — проверка по host', true);
    await reloadOverview({ updates: false }, context);
  } catch (e) {
    showContextToast(context, e.message || 'Не удалось сохранить домен SSL', false);
  } finally {
    setBusy(false, context);
  }
}

async function onCheckUpdates() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/system/check-updates`,
      { method: 'POST' },
    );
    if (r.system) {
      const el = document.getElementById('qs-sec-system');
      if (el) {
        const tmp = document.createElement('div');
        tmp.innerHTML = renderSystem(r.system, lastOverview?.diagnostics, lastOverview?.local_settings);
        el.replaceWith(tmp.firstElementChild);
        bindActions();
        applyQsSection();
      }
      showContextToast(context,r.system.updates_summary || 'Проверка выполнена', true);
    }
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка проверки', false);
  } finally {
    setBusy(false, context);
  }
}

async function onUpgrade() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const approved = await confirmAction({
    title: 'Обновить систему?',
    message: 'Будут выполнены apt-get update и apt-get upgrade. Операция может занять несколько минут.',
    confirmText: 'Обновить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  showContextToast(context,'Обновление системы…', true);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/system/upgrade`,
      { method: 'POST' },
    );
    if (r.ok) {
      showContextToast(context,r.message || 'Система обновлена', true);
      await reloadOverview({ updates: true }, context);
    } else {
      showContextToast(context,r.error || r.message || 'Ошибка обновления', false);
    }
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка обновления', false);
  } finally {
    setBusy(false, context);
  }
}

async function onDiagnostics() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/diagnostics`,
    );
    if (r.diagnostics) {
      if (lastOverview) lastOverview.diagnostics = r.diagnostics;
      const el = document.getElementById('qs-sec-system');
      if (el) {
        const tmp = document.createElement('div');
        tmp.innerHTML = renderSystem(lastOverview?.system, r.diagnostics, lastOverview?.local_settings);
        el.replaceWith(tmp.firstElementChild);
        bindActions();
        applyQsSection();
      }
      showContextToast(context,'Сведения обновлены', true);
    }
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

async function onPkgRefresh() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/packages`,
    );
    const el = document.getElementById('qs-sec-packages');
    if (el && r.packages) {
      const tmp = document.createElement('div');
      tmp.innerHTML = renderPackages(r.packages);
      el.replaceWith(tmp.firstElementChild);
      bindActions();
      applyQsSection();
    }
    showContextToast(context,'Список пакетов обновлён', true);
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

function bindQsPkgRows() {
  // Делегированная обработка в секции Пакеты: галочка показывает/прячет
  // инлайн-«установить» у строки; клик по ней ставит один пакет.
  const root = document.getElementById('qs-sec-packages');
  if (!root || root.dataset.qsPkgBound === '1') return;
  root.dataset.qsPkgBound = '1';
  root.addEventListener('change', (e) => {
    const input = e.target.closest('input[data-pkg]');
    if (!input) return;
    const row = input.closest('.qs-pkg-row');
    const btn = row?.querySelector('.qs-pkg-install');
    if (btn) btn.hidden = !input.checked;
  });
  root.addEventListener('click', (e) => {
    const btn = e.target.closest('button.qs-pkg-install');
    if (!btn || btn.hidden) return;
    e.preventDefault();
    onPkgInstall([btn.dataset.pkgInstall]);
  });
}

async function onPkgInstall(explicitNames = null) {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const names = explicitNames
    || [...document.querySelectorAll('#qs-sec-packages input[data-pkg]:checked:not(:disabled)')]
      .map(el => el.dataset.pkg)
      .filter(Boolean);
  if (!names.length) {
    showContextToast(context,'Выберите пакеты для установки', false);
    return;
  }
  const approved = await confirmAction({
    title: 'Установить пакеты?',
    message: names.join(', ') + (
      names.some(n => ['nginx', 'apache2', 'certbot', 'docker.io', 'python3', 'python3-pip', 'mariadb-server', 'postgresql', 'cron', 'logrotate', 'acl'].includes(n))
        ? '\n\n⚠️ Сервис после установки может быть автоматически запущен и начать принимать соединения.'
        : ''
    ),
    confirmText: 'Установить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/packages/install`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ packages: names }) },
    );
    if (r.ok) {
      showContextToast(context,r.message || 'Установлено', true);
      await reloadOverview({ updates: false }, context);
    } else {
      showContextToast(context,r.error || r.message || 'Ошибка установки', false);
    }
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка установки', false);
  } finally {
    setBusy(false, context);
  }
}



async function onSshCreateUser() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const username = document.getElementById('qs-ssh-newuser')?.value?.trim();
  const password = document.getElementById('qs-ssh-newuser-pass')?.value || undefined;
  const sudo = !!document.getElementById('qs-ssh-newuser-sudo')?.checked;
  if (!username) { showContextToast(context,'Укажите имя пользователя', false); return; }
  if (!/^[a-z_][a-z0-9_-]{0,31}$/.test(username)) {
    showContextToast(context, 'Имя пользователя: 1–32 символа, строчная латиница, начинается с буквы или «_»', false);
    return;
  }
  if (password !== undefined && password.length < 6) {
    showContextToast(context, 'Пароль — минимум 6 символов (или оставьте поле пустым)', false);
    return;
  }
  const approved = await confirmAction({
    title: 'Создать пользователя?',
    message: `${username}` + (password ? ' (с отдельным паролем)' : ' (без пароля)')
      + (sudo ? ', добавить право sudo.' : '.')
      + ' Bot4VPS останется на текущем аккаунте.',
    confirmText: 'Создать',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,`/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, sudo }),
    });
    if (r.ok) {
      showContextToast(context,r.message || 'Пользователь создан', true);
      const nameInput = document.getElementById('qs-ssh-newuser');
      const passInput = document.getElementById('qs-ssh-newuser-pass');
      if (nameInput) nameInput.value = '';
      if (passInput) passInput.value = '';
    } else showContextToast(context,r.message || r.error || 'Ошибка создания', false);
  } catch (e) {
    showContextToast(
      context,
      e.status === 422
        ? 'Проверьте поля: имя — строчная латиница (буква или «_» в начале), пароль — минимум 6 символов'
        : (e.message || 'Ошибка создания'),
      false,
    );
  }
  finally { setBusy(false, context); }
}

async function onSshSwitchUser() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const username = document.getElementById('qs-ssh-switch-user')?.value?.trim();
  const password = document.getElementById('qs-ssh-switch-pass')?.value || undefined;
  if (!username) { showContextToast(context,'Укажите существующего пользователя', false); return; }
  if (!/^[a-z_][a-z0-9_-]{0,31}$/.test(username)) {
    showContextToast(context, 'Имя пользователя: 1–32 символа, строчная латиница, начинается с буквы или «_»', false);
    return;
  }
  // П3: способ авторизации выбирается явно. При выключенной password-auth
  // единственный вариант — локальный ключ бота; иначе читаем дропдаун
  // «Авторизоваться по» (default: паролю).
  const s = lastOverview?.ssh_access;
  const rawPwd = (s?.password_auth || '').toLowerCase();
  const pwdOn = rawPwd.includes('разреш') || rawPwd === 'yes';
  const pwdAuthOff = !!(s?.password_auth && !pwdOn);
  const authMode = pwdAuthOff ? 'key' : (document.getElementById('qs-ssh-switch-auth')?.value || 'password');
  const keyPathEl = document.getElementById('qs-ssh-switch-key');
  const keyPath = authMode === 'key' ? (keyPathEl?.value || undefined) : undefined;
  if (authMode === 'key' && !keyPath) {
    showContextToast(context, pwdAuthOff
      ? 'На сервере выключена авторизация по паролю — выберите локальный ключ Bot4VPS для входа'
      : 'Выберите локальный ключ Bot4VPS для входа', false);
    return;
  }
  if (authMode === 'password' && !password) {
    showContextToast(context, 'Укажите пароль целевого пользователя', false);
    return;
  }
  const approved = await confirmAction({
    title: `Переключить Bot4VPS на ${username}?`,
    message: authMode === 'key'
      ? 'Будут проверены реальный вход выбранным SSH-ключом и sudo; тип авторизации в servers.json сменится на SSH-ключ. Пароль используется только как sudo-пароль цели.'
      : 'Будут проверены реальный вход указанным паролем целевого пользователя и sudo. Только после этого изменится локальная запись.',
    confirmText: 'Переключить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  // Пароль и ключ — в базовом теле: все повторы (подтверждение
  // «переключить всё равно», sudo-gate) обязаны нести те же credentials.
  const send = (extra) => requestForContext(context,`/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/switch`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, key_path: keyPath, ...extra }),
  });
  try {
    let r = await send({});
    // П4: sudo-gate — ключ-переключение на sudo/root-аккаунт с sudo-less
    // текущего. Пароль цели проверяется на сервере; до трёх попыток,
    // отмена закрывает modal без переключения. auth_type остаётся key.
    for (let attempt = 0; !r.ok && (r.error === 'sudo_password_required' || r.error === 'sudo_password_invalid') && attempt < 3; attempt++) {
      const pw = await promptSudoGatePassword(username, r.error === 'sudo_password_invalid' ? r.message : null);
      if (!contextIsCurrent(context)) return;
      if (pw === null) { r = null; break; }
      // Пароль из sudo-gate заменяет базовый (он проверен сервером)
      r = await send({ password: pw });
    }
    if (r === null) return;
    if (r.ok) {
      showContextToast(context,r.message || 'Пользователь переключён', true);
      // Оверлей снимаем сразу: переключение завершено, перезагрузка
      // статуса — фоновая (страница перерисуется по готовности данных).
      setBusy(false, context);
      await reloadOverview({ updates: false }, context);
      return;
    } else if (r.data?.confirmation_required && r.data?.login_verified) {
      const proceed = await confirmAction({
        title: `Переключить Bot4VPS на ${username}?`,
        message: `⚠️ SSH-вход под ${username} проверен.\n${r.message}\nПосле переключения Bot4VPS не сможет выполнять административные операции, пока sudo не заработает (например, не будет исправлен пароль).\nПереключить всё равно?`,
        confirmText: 'Переключить',
        cancelText: 'Отмена',
        confirmFirst: true,
      });
      if (!proceed || !contextIsCurrent(context)) return;
      const retry = await send({ allow_without_sudo: true });
      if (retry.ok) {
        showContextToast(context,retry.message || 'Пользователь переключён', true);
        // Аналогично: успех — оверлей снят, статус грузится в фоне
        setBusy(false, context);
        await reloadOverview({ updates: false }, context);
        return;
      } else showContextToast(context,retry.message || retry.error || 'Переключение не выполнено', false);
    } else showContextToast(context,r.message || r.error || 'Переключение не выполнено', false);
  } catch (e) { showContextToast(context,e.message || 'Ошибка переключения', false); }
  finally { setBusy(false, context); }
}

function sshManagerRights(users) {
  // Индикатор полных прав в списке пользователей: «Сменить пароль» виден,
  // когда текущий пользователь Bot4VPS сам обладает sudo (root — всегда).
  // Менеджер ключей открывается всем — свои ключи доступны и без sudo,
  // операции с чужими ключами проверяет backend.
  const me = users.find((u) => u.current);
  if (!me) return false;
  return me.uid === 0 || me.sudo_capable === true;
}

function renderSshUsers(users, rootPwChange = false) {
  if (!users.length) return '<p class="qs-list-empty">Пользователи не найдены.</p>';
  const canManage = sshManagerRights(users);
  return users.map((user) => {
    const sudo = user.sudo_capable === true
      ? 'sudo доступен'
      : user.sudo_capable === false ? 'sudo недоступен' : 'sudo не определён';
    const login = user.login_capable ? 'SSH-вход разрешён shell-политикой' : 'SSH-вход отключён';
    const reason = user.protected_reason
      ? `<div class="qs-user-protection">${esc(user.protected_reason)}</div>`
      : '';
    const choose = user.login_capable && !user.current
      ? `<button type="button" class="secondary qs-user-select" data-username="${esc(user.username)}">Выбрать</button>`
      : '';
    // sudo-редактор: выдача для тех, у кого нет; отзыв для тех, у кого есть.
    // Обе кнопки — на одном месте (нижний ярус): у пользователя либо есть
    // sudo (отзыв, оранжевая), либо нет (выдача, синяя). У root кнопок нет
    // вовсе — root и так полные права.
    const grant = user.sudo_capable !== true && user.uid !== 0
      ? `<button type="button" class="secondary qs-user-sudo" data-username="${esc(user.username)}">Выдать sudo</button>`
      : '';
    const revoke = user.sudo_capable === true && user.uid !== 0 && !user.current
      ? `<button type="button" class="secondary qs-user-revoke-sudo" data-username="${esc(user.username)}">Отозвать sudo</button>`
      : '';
    const sudoBtn = grant || revoke;
    // Пароль root (когда root не активный пользователь) меняем только при
    // рабочем root-парольном входе по SSH — иначе кнопку не показываем.
    const rootNeedsOld = user.uid === 0 && !user.current;
    // Своей учётной записи «Сменить пароль» доступен всегда — passwd без
    // sudo меняет свой пароль; чужим — только с sudo-правами менеджера.
    const canChangePass = user.current || (canManage && (!rootNeedsOld || rootPwChange));
    const passBtn = canChangePass
      ? `<button type="button" class="secondary qs-compact qs-user-pass" data-username="${esc(user.username)}"${rootNeedsOld ? ' data-needs-old="1"' : ''}>Сменить пароль</button>`
      : '';
    const remove = user.can_delete
      ? `<button type="button" class="secondary danger qs-user-delete" data-username="${esc(user.username)}">Удалить</button>`
      : `<button type="button" class="secondary" disabled title="${esc(user.protected_reason || 'Удаление запрещено')}">Удалить нельзя</button>`;
    // Кнопки в две строки: верх — обычные действия (Выбрать/Сменить пароль),
    // низ — sudo-редактор (Выдать/Отозвать) и деструктивная «Удалить».
    return `<div class="qs-list-row qs-user-row">
      <div class="qs-user-info">
        <strong>${esc(user.username)}</strong>${user.current ? ' <span class="qs-status-chip">текущий</span>' : ''}
        <small>UID ${esc(String(user.uid))} · ${esc(user.shell || '—')} · ${esc(login)} · ${esc(sudo)}</small>
        ${reason}
      </div>
      <div class="qs-user-btn-cols">
        <div class="qs-user-actions">${choose}${passBtn}</div>
        ${(sudoBtn || remove) ? `<div class="qs-user-actions qs-user-actions-danger">${sudoBtn}${remove}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

function chooseSshUserDeletePolicy(username) {
  openQsListModal(
    `Удалить пользователя ${username}?`,
    `<div class="qs-f2b-uninstall-choice">
      <p>Удаляется только учётная запись. Выберите, что сделать с домашним каталогом (например, /home/${esc(username)}).</p>
      <div class="qs-section-actions">
        <button type="button" id="qs-user-del-keep">Оставить домашний каталог</button>
        <button type="button" class="secondary danger" id="qs-user-del-remove">Удалить вместе с данными</button>
        <button type="button" class="secondary" id="qs-user-del-cancel">Отмена</button>
      </div>
    </div>`,
  );
  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const finish = (value) => {
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.(value);
    };
    document.getElementById('qs-user-del-keep')?.addEventListener('click', () => finish(false));
    document.getElementById('qs-user-del-remove')?.addEventListener('click', () => finish(true));
    document.getElementById('qs-user-del-cancel')?.addEventListener('click', () => finish(null));
  });
}

// Кнопка-«глаз» рядом с полем пароля: показать ввод и спрятать обратно.
function qsPassEye(inputId) {
  return `<button type="button" class="qs-eye" data-eye-for="${esc(inputId)}" title="Показать пароль" aria-label="Показать пароль">👁</button>`;
}

function bindQsPasswordEyes() {
  if (document.body?.dataset?.qsEyesBound === '1') return;
  if (document.body) document.body.dataset.qsEyesBound = '1';
  // Делегирование на document: работает во всех модалках и после любого ререндера.
  document.addEventListener('click', (e) => {
    const btn = e.target?.closest?.('.qs-eye');
    if (!btn) return;
    const input = document.getElementById(btn.dataset.eyeFor || '');
    if (!input) return;
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    const label = show ? 'Скрыть пароль' : 'Показать пароль';
    btn.textContent = show ? '🙈' : '👁';
    btn.title = label;
    btn.setAttribute('aria-label', label);
  });
}

function promptQsPasswordChange(username, needsOld) {
  const oldField = needsOld
    ? `<label for="qs-prompt-old">Старый пароль root</label>
      <div class="qs-pass-wrap">
        <input id="qs-prompt-old" type="password" autocomplete="current-password" placeholder="старый пароль root">
        ${qsPassEye('qs-prompt-old')}
      </div>`
    : '';
  const hint = needsOld
    ? 'Старый пароль root проверяется реальным SSH-входом; после смены новый пароль также проверяется входом.'
    : 'Новый пароль (6–256 символов). После смены пароль проверяется реальным SSH-входом под этим пользователем.';
  openQsListModal(
    `Сменить пароль ${username}?`,
    `<div class="qs-f2b-uninstall-choice">
      <p>${esc(hint)}</p>
      <div class="qs-prompt-form">
        ${oldField}
        <label for="qs-prompt-pass">Новый пароль</label>
        <div class="qs-pass-wrap">
          <input id="qs-prompt-pass" type="password" autocomplete="new-password" placeholder="новый пароль">
          ${qsPassEye('qs-prompt-pass')}
        </div>
        <p class="qs-muted" id="qs-prompt-warn"></p>
        <div class="qs-section-actions">
          <button type="button" id="qs-prompt-ok">Сменить</button>
          <button type="button" class="secondary" id="qs-prompt-cancel">Отмена</button>
        </div>
      </div>
    </div>`,
  );
  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const finish = (value) => {
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.(value);
    };
    const submit = () => {
      const warn = document.getElementById('qs-prompt-warn');
      const value = document.getElementById('qs-prompt-pass')?.value || '';
      if (value.length < 6) {
        if (warn) warn.textContent = 'Новый пароль — минимум 6 символов.';
        return;
      }
      const old = needsOld ? (document.getElementById('qs-prompt-old')?.value || '') : null;
      if (needsOld && !old) {
        if (warn) warn.textContent = 'Укажите старый пароль root.';
        return;
      }
      finish({ password: value, oldPassword: old });
    };
    document.getElementById('qs-prompt-ok')?.addEventListener('click', submit);
    document.getElementById('qs-prompt-cancel')?.addEventListener('click', () => finish(null));
    document.getElementById('qs-prompt-pass')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submit();
    });
    document.getElementById('qs-prompt-old')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') document.getElementById('qs-prompt-pass')?.focus();
    });
    setTimeout(() => (needsOld
      ? document.getElementById('qs-prompt-old')
      : document.getElementById('qs-prompt-pass')
    )?.focus(), 30);
  });
}

// П4: sudo-gate. Ключ-переключение на sudo/root-аккаунт, когда текущий
// пользователь без sudo, требует пароль цели: он проверяется на сервере
// и сохраняется как sudo-credential (тип авторизации остаётся «ключ»).
// invalidMessage — пояснение предыдущей неудачной попытки, если она была.
function promptSudoGatePassword(username, invalidMessage = null) {
  openQsListModal(
    'Учётная запись суперпользователя',
    `<div class="qs-f2b-uninstall-choice">
      <p>Вы пытаетесь переподключиться на учётную запись суперпользователя, введите пароль${username ? ` пользователя <strong>${esc(username)}</strong>` : ''}. Неверный пароль запрещает переключение.</p>
      ${invalidMessage ? `<p class="qs-user-protection">${esc(invalidMessage)}</p>` : ''}
      <div class="qs-prompt-form">
        <div class="qs-pass-wrap">
          <input id="qs-sudogate-pass" type="password" autocomplete="current-password" placeholder="пароль">
          ${qsPassEye('qs-sudogate-pass')}
        </div>
        <p class="qs-muted" id="qs-sudogate-warn"></p>
        <div class="qs-section-actions">
          <button type="button" id="qs-sudogate-ok">Проверить и переключить</button>
          <button type="button" class="secondary" id="qs-sudogate-cancel">Отмена</button>
        </div>
      </div>
    </div>`,
  );
  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const finish = (value) => {
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.(value);
    };
    const submit = () => {
      const warn = document.getElementById('qs-sudogate-warn');
      const value = document.getElementById('qs-sudogate-pass')?.value || '';
      if (!value) {
        if (warn) warn.textContent = 'Введите пароль.';
        return;
      }
      finish(value);
    };
    document.getElementById('qs-sudogate-ok')?.addEventListener('click', submit);
    document.getElementById('qs-sudogate-cancel')?.addEventListener('click', () => finish(null));
    document.getElementById('qs-sudogate-pass')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') submit();
    });
    setTimeout(() => document.getElementById('qs-sudogate-pass')?.focus(), 30);
  });
}

function sshKeyManagerNote(data) {
  if (data.password_auth === false) {
    return 'Аутентификация по паролю запрещена: последний ключ текущего пользователя и root удалить нельзя (должен остаться рабочий способ входа).';
  }
  if (data.is_root && !data.is_current_root) {
    return 'Для действий с ключами root требуется пароль root — он проверяется реальным SSH-входом и нигде не сохраняется.';
  }
  return '';
}

function sshKeyManagerUsers(users) {
  // Ключи имеют смысл только для аккаунтов с SSH-входом (root — всегда).
  return users.filter((u) => u.login_capable || u.uid === 0);
}

function renderSshKeyManager(username, data, users = []) {
  const keys = data?.keys || [];
  const note = sshKeyManagerNote(data);
  const selector = users.length
    ? `<div class="qs-port-form qs-ssh-inline">
        <label for="qs-key-user">Пользователь</label>
        <select id="qs-key-user">
          ${sshKeyManagerUsers(users).map((u) => `
            <option value="${esc(u.username)}"${u.username === username ? ' selected' : ''}>
              ${esc(u.username)}${u.current ? ' (текущий)' : ''}
            </option>
          `).join('')}
        </select>
      </div>`
    : '';
  const rootField = data?.is_root && !data?.is_current_root
    ? `<div class="qs-port-form qs-ssh-inline">
        <label for="qs-key-root-pass">Пароль root</label>
        <span class="qs-pass-wrap"><input id="qs-key-root-pass" type="password" autocomplete="current-password" placeholder="пароль root" style="width:11rem">${qsPassEye('qs-key-root-pass')}</span>
      </div>`
    : '';
  const isCurrent = !!data?.is_current_user;
  const keyRowActions = (k) => {
    if (k.route_uses_key) {
      return '<span class="qs-status-chip">используется Bot4VPS</span>';
    }
    if (k.is_recorded) {
      return '<span class="qs-status-chip">прописан в servers.json</span>';
    }
    if (isCurrent && k.local_match) {
      return `<button type="button" class="secondary qs-compact qs-key-select" data-fingerprint="${esc(k.fingerprint)}">Выбрать ключ</button>`;
    }
    return '';
  };
  const listHtml = keys.length
    ? keys.map((k) => `<div class="qs-list-row qs-key-row">
        <div class="qs-user-info">
          <strong>${esc(k.type)}</strong>${k.comment ? ` <span class="qs-status-chip">${esc(k.comment)}</span>` : ''}
          <small style="font-family:ui-monospace,monospace">${esc(k.fingerprint)}</small>
        </div>
        <div class="qs-user-actions">
          ${keyRowActions(k)}
          <button type="button" class="secondary danger qs-compact qs-key-delete" data-fingerprint="${esc(k.fingerprint)}">Удалить</button>
        </div>
      </div>`).join('')
    : '<p class="qs-list-empty">Ключей нет. «Создать ключ» сгенерирует пару во встроенном хранилище Bot4VPS и добавит публичную часть в authorized_keys пользователя.</p>';
  const selectHint = isCurrent
    ? '<p class="qs-muted">«Выбрать ключ» сверяет ключ на сервере с локальным ключом Bot4VPS и прописывает его key_path в servers.json. Способ авторизации не меняется — ключ просто запоминается на случай перехода на key-auth.</p>'
    : '';
  return `<div class="qs-key-manager">
    ${selector}
    <p>Пользователь <strong>${esc(username)}</strong>${data?.is_current_user ? ' <span class="qs-status-chip">текущий</span>' : ''} · ключей: ${keys.length}</p>
    ${note ? `<p class="qs-muted">${esc(note)}</p>` : ''}
    ${rootField}
    <div class="qs-section-actions">
      <button type="button" id="qs-key-create">Создать ключ</button>
      ${isCurrent ? '<button type="button" class="secondary" id="qs-key-add-pub">Добавить готовый ключ на сервер</button>' : ''}
    </div>
    ${listHtml}
    ${selectHint}
  </div>`;
}

function bindSshKeyManager(context, serverId, username, users = []) {
  const body = document.getElementById('qs-list-modal-body');
  const rootPassword = () => document.getElementById('qs-key-root-pass')?.value || null;
  document.getElementById('qs-key-user')?.addEventListener('change', async (e) => {
    if (busy || !contextIsCurrent(context)) return;
    const next = e.target?.value || username;
    if (next === username) return;
    await openSshKeyManager(context, serverId, next, users);
  });
  document.getElementById('qs-key-create')?.addEventListener('click', async () => {
    if (busy || !contextIsCurrent(context)) return;
    const payload = {};
    const rp = rootPassword();
    if (rp) payload.root_password = rp;
    setBusy(true, context);
    try {
      const r = await requestForContext(
        context,
        `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/keys`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      );
      showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
      if (r.ok) {
        // П1: «Создать ключ» меняет только key_path — тип авторизации не
        // трогаем. Обновляем SSH-статус (key_path/key_configured), без
        // перезагрузки всего overview.
        if (r.data?.key_recorded) await onSshRefresh({ quiet: true, force: true });
        await openSshKeyManager(context, serverId, username, users);
      }
    } catch (e) { showContextToast(context, e.message || 'Ошибка создания ключа', false); }
    finally { setBusy(false, context); }
  });
  document.getElementById('qs-key-add-pub')?.addEventListener('click', async () => {
    if (busy || !contextIsCurrent(context)) return;
    // Свободные локальные ключи — для выбора в модалке (ошибка не критична)
    let freeKeys = [];
    try {
      const r = await requestForContext(
        context,
        `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/local-keys`,
      );
      freeKeys = r.ok ? (r.data?.keys || []) : [];
    } catch { freeKeys = []; }
    const public_key = await promptQsAddPubkey(freeKeys);
    if (public_key === null || !contextIsCurrent(context)) return;
    qsModalReturnFocus = document.getElementById('qs-key-add-pub') || qsModalReturnFocus;
    setBusy(true, context);
    try {
      // Тот же endpoint, что раньше был у блока «Публичный ключ»:
      // ключ пишется в authorized_keys текущего пользователя Bot4VPS.
      const r = await requestForContext(
        context,
        `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/key`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ public_key, switch_to_key: false }),
        },
      );
      showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
      if (r.ok) await openSshKeyManager(context, serverId, username, users);
    } catch (e) { showContextToast(context, e.message || 'Ошибка добавления ключа', false); }
    finally { setBusy(false, context); }
  });
  body?.querySelectorAll('.qs-key-select').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const fingerprint = btn.dataset.fingerprint || '';
      setBusy(true, context);
      try {
        const r = await requestForContext(
          context,
          `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/keys/select`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fingerprint }),
          },
        );
        showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
        // key_path записан — статус «SSH-key статус» обновляется сразу
        if (r.ok) await onSshRefresh({ quiet: true, force: true });
        if (r.ok) await openSshKeyManager(context, serverId, username, users);
      } catch (e) { showContextToast(context, e.message || 'Ошибка выбора ключа', false); }
      finally { setBusy(false, context); }
    });
  });
  body?.querySelectorAll('.qs-key-delete').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const fingerprint = btn.dataset.fingerprint || '';
      const approved = await confirmAction({
        title: 'Удалить ключ?',
        message: `Ключ ${fingerprint.slice(0, 20)}… будет удалён из authorized_keys пользователя ${username}. Локальная копия в «Файлы → Ключи» не затрагивается.`,
        confirmText: 'Удалить',
        confirmFirst: true,
      });
      if (!approved || !contextIsCurrent(context)) return;
      const payload = { fingerprint };
      const rp = rootPassword();
      if (rp) payload.root_password = rp;
      setBusy(true, context);
      try {
        const r = await requestForContext(
          context,
          `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/keys`,
          {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          },
        );
        showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
        if (r.ok) {
          if (r.data?.switched_to_password) await reloadOverview({ updates: false }, context);
          // Записанный key_path затёрт — «SSH-key статус» обновляется сразу
          else if (r.data?.key_path_cleared) await onSshRefresh({ quiet: true, force: true });
          await openSshKeyManager(context, serverId, username, users);
        }
      } catch (e) { showContextToast(context, e.message || 'Ошибка удаления ключа', false); }
      finally { setBusy(false, context); }
    });
  });
}

async function openSshKeyManager(context, serverId, username, users = []) {
  setBusy(true, context);
  try {
    const r = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/keys`,
    );
    if (!r.ok) {
      showContextToast(context, r.message || r.error || 'Ключи недоступны', false);
      return;
    }
    openQsListModal('SSH-ключи доступа', renderSshKeyManager(username, r.data, users), true);
    bindSshKeyManager(context, serverId, username, users);
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка получения ключей', false);
  } finally { setBusy(false, context); }
}

async function onSshKeyManager() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const ssh = lastOverview?.ssh_access;
  // Без sudo — сразу собственные ключи, без списка пользователей и селектора.
  if (ssh?.sudo_capable === false) {
    const me = String(ssh?.user || '').trim();
    if (!me) { showContextToast(context, 'Не удалось определить текущего пользователя', false); return; }
    await openSshKeyManager(context, serverId, me);
    return;
  }
  setBusy(true, context);
  try {
    const r = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users`,
    );
    const users = r.data?.users || [];
    if (!r.ok || !users.length) {
      showContextToast(context, r.message || r.error || 'Пользователи недоступны', false);
      return;
    }
    // Права проверяет backend: без sudo доступны только собственные ключи.
    const current = users.find((u) => u.current) || users[0];
    await openSshKeyManager(context, serverId, current.username, users);
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка открытия менеджера ключей', false);
  } finally { setBusy(false, context); }
}

function bindSshUserRows(context, serverId) {
  const body = document.getElementById('qs-list-modal-body');
  body?.querySelectorAll('.qs-user-select').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!contextIsCurrent(context)) return;
      const input = document.getElementById('qs-ssh-switch-user');
      if (input) input.value = btn.dataset.username || '';
      qsModalReturnFocus = input || qsModalReturnFocus;
      closeQsListModal();
    });
  });
  body?.querySelectorAll('.qs-user-delete').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const username = btn.dataset.username || '';
      const removeHome = await chooseSshUserDeletePolicy(username);
      if (removeHome === null || !contextIsCurrent(context)) return;
      qsModalReturnFocus = btn.isConnected ? btn : qsModalReturnFocus;
      setBusy(true, context);
      try {
        const r = await requestForContext(
          context,
          `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}`,
          {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ remove_home: removeHome }),
          },
        );
        showContextToast(context,r.message || r.error || 'Удаление не выполнено', !!r.ok);
        if (r.ok) {
          btn.closest('.qs-user-row')?.remove();
          if (body && !body.querySelector('.qs-user-row')) {
            body.innerHTML = '<p class="qs-list-empty">Пользователи не найдены.</p>';
          }
        }
      } catch (e) { showContextToast(context,e.message || 'Ошибка удаления', false); }
      finally { setBusy(false, context); }
    });
  });
  body?.querySelectorAll('.qs-user-revoke-sudo').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const username = btn.dataset.username || '';
      const approved = await confirmAction({
        title: `Отозвать sudo у пользователя ${username}?`,
        message: 'Пользователь будет удалён из группы sudo/wheel, после чего отсутствие прав будет проверено. Пароль и SSH-доступ пользователя не затрагиваются.',
        confirmText: 'Отозвать sudo',
        confirmFirst: true,
      });
      if (!approved || !contextIsCurrent(context)) return;
      qsModalReturnFocus = btn.isConnected ? btn : qsModalReturnFocus;
      setBusy(true, context);
      try {
        const r = await requestForContext(
          context,
          `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/sudo`,
          { method: 'DELETE' },
        );
        showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
        if (r.ok) {
          closeQsListModal();
          setBusy(false, context);
          await onSshUsers();
          return;
        }
      } catch (e) { showContextToast(context, e.message || 'Ошибка отзыва sudo', false); }
      finally { setBusy(false, context); }
    });
  });
  body?.querySelectorAll('.qs-user-pass').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const username = btn.dataset.username || '';
      const needsOld = btn.dataset.needsOld === '1';
      const creds = await promptQsPasswordChange(username, needsOld);
      if (creds === null || !contextIsCurrent(context)) return;
      qsModalReturnFocus = btn.isConnected ? btn : qsModalReturnFocus;
      setBusy(true, context);
      try {
        const payload = { password: creds.password };
        if (creds.oldPassword) payload.old_password = creds.oldPassword;
        const r = await requestForContext(
          context,
          `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/password`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          },
        );
        showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
      } catch (e) { showContextToast(context, e.message || 'Ошибка смены пароля', false); }
      finally { setBusy(false, context); }
    });
  });
  body?.querySelectorAll('.qs-user-sudo').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const username = btn.dataset.username || '';
      const approved = await confirmAction({
        title: `Выдать sudo пользователю ${username}?`,
        message: 'При необходимости будет установлен пакет sudo, пользователь будет добавлен в группу sudo/wheel, после чего права будут проверены.',
        confirmText: 'Выдать sudo',
        confirmFirst: true,
      });
      if (!approved || !contextIsCurrent(context)) return;
      setBusy(true, context);
      try {
        const r = await requestForContext(
          context,
          `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/sudo`,
          { method: 'POST' },
        );
        showContextToast(context,r.message || r.error || 'Операция не выполнена', !!r.ok);
        if (r.ok) {
          closeQsListModal();
          setBusy(false, context);
          await onSshUsers();
          return;
        }
      } catch (e) { showContextToast(context,e.message || 'Ошибка выдачи sudo', false); }
      finally { setBusy(false, context); }
    });
  });
}

async function onSshUsers() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users`,
    );
    const users = r.data?.users || [];
    // wide: до пяти кнопок в строке пользователя (Выбрать/Выдать-Отозвать
    // sudo/Сменить пароль/Удалить) — 480px им тесно.
    openQsListModal('Пользователи', renderSshUsers(users, r.data?.root_password_change === true), true);
    bindSshUserRows(context, serverId);
    if (!r.ok) showContextToast(context,r.message || r.error || 'Список недоступен', false);
  } catch (e) { showContextToast(context,e.message || 'Ошибка получения пользователей', false); }
  finally { setBusy(false, context); }
}

/** Принять текущий host key сервера (после переустановки сервера). */
async function onSshHostKeyAccept() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const approved = await confirmAction({
    title: 'Принять текущий host key?',
    message: 'Bot4VPS подключится к серверу без сверки и заменит сохранённый SSH host key на предъявленный сейчас. Продолжайте, только если вы уверены, что сервер переустановлен или его ключ законно изменился.',
    confirmText: 'Принять',
    cancelText: 'Отмена',
    danger: true,
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/hostkey/accept`,
      { method: 'POST' });
    showContextToast(context, r.ok
      ? `Новый host key принят: ${r.host_key?.fingerprint || '?'}`
      : (r.message || r.error || 'Ошибка'), r.ok);
    if (r.ok) await reloadOverview({ updates: false }, context);
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

async function onSshPort() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const port = parseInt(document.getElementById('qs-ssh-port')?.value, 10);
  if (!port || port < 1 || port > 65535) { showContextToast(context,'Порт 1–65535', false); return; }
  const acknowledgeConflict = _fwHasConflict();
  const conflictText = acknowledgeConflict
    ? ` Обнаружен конфликт (${_fwConflictNames()}): новый порт будет открыт во всех активных поддерживаемых firewall, а старые правила закроются только после успешной проверки нового SSH-входа.`
    : '';
  const approved = await confirmAction({
    title: 'Изменить SSH-порт?',
    message: `Новый порт ${port}: откроется в firewall, изменится sshd, проверка входа, затем servers.json.${conflictText}`,
    confirmText: 'Изменить',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,`/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/port`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        port,
        acknowledge_firewall_conflict: acknowledgeConflict,
      }),
    });
    if (r.ok) {
      showContextToast(context,r.message || 'OK', true);
      await reloadOverview({ updates: false }, context);
    } else {
      const retained = r.data?.firewall?.new_rule_retained === true;
      const retainedWarning = retained
        ? `Новый порт ${r.data?.new_port || port} оставлен открытым для повторной попытки`
        : '';
      const baseMessage = r.message || r.error || 'Ошибка';
      showContextToast(
        context,
        retainedWarning && !baseMessage.includes(retainedWarning)
          ? `${baseMessage}. ${retainedWarning}`
          : baseMessage,
        false,
      );
    }
  } catch (e) { showContextToast(context,e.message || 'Ошибка', false); }
  finally { setBusy(false, context); }
}

async function onSshSetOwnPass() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const username = String(lastOverview?.ssh_access?.user || '').trim();
  if (!username) { showContextToast(context, 'Не удалось определить текущего пользователя', false); return; }
  const creds = await promptQsPasswordChange(username, false);
  if (creds === null || !contextIsCurrent(context)) return;
  qsModalReturnFocus = document.getElementById('qs-ssh-set-own-pass') || qsModalReturnFocus;
  setBusy(true, context);
  try {
    const r = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(username)}/password`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: creds.password }),
      },
    );
    showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
  } catch (e) { showContextToast(context, e.message || 'Ошибка смены пароля', false); }
  finally { setBusy(false, context); }
}

function promptQsAddPubkey(freeKeys = []) {
  const freeKeysHtml = freeKeys.length ? `
      <p class="qs-muted">Или выберите свободный локальный ключ Bot4VPS (нигде не используется):</p>
      <div class="qs-list">${freeKeys.map((k) => `
        <div class="qs-list-row">
          <span>🔑 <strong>${esc(k.name)}</strong> <span class="qs-muted">${esc(k.type || '')} ${esc(k.fingerprint || '')}</span></span>
          <button type="button" class="secondary" data-addpub-free="${esc(k.name)}" data-addpub-key="${esc(k.public_key)}">Выбрать</button>
        </div>`).join('')}</div>` : '';
  openQsListModal(
    'Добавить SSH-ключ',
    `<div class="qs-f2b-uninstall-choice">
      <p>Вставьте ваш публичный ключ:</p>
      <textarea id="qs-addpub-key" rows="3" placeholder="ssh-ed25519 AAAA… comment" style="width:100%;max-width:36rem;font-family:ui-monospace,monospace;font-size:.8rem"></textarea>
      <p class="qs-muted" id="qs-addpub-warn"></p>
      ${freeKeysHtml}
      <div class="qs-section-actions">
        <button type="button" id="qs-addpub-ok">ОК</button>
        <button type="button" class="secondary" id="qs-addpub-cancel">Отмена</button>
      </div>
    </div>`,
  );
  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const finish = (value) => {
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.(value);
    };
    const submit = () => {
      const key = document.getElementById('qs-addpub-key')?.value?.trim() || '';
      const warn = document.getElementById('qs-addpub-warn');
      if (!/^ssh-(ed25519|rsa|ecdsa|dss)\s+\S+/i.test(key)) {
        if (warn) warn.textContent = 'Ключ должен начинаться с типа, например: ssh-ed25519 AAAA…';
        return;
      }
      finish(key);
    };
    document.getElementById('qs-addpub-ok')?.addEventListener('click', submit);
    document.getElementById('qs-addpub-cancel')?.addEventListener('click', () => finish(null));
    document.querySelectorAll('[data-addpub-free]').forEach((btn) => {
      btn.addEventListener('click', () => finish(btn.dataset.addpubKey || null));
    });
    setTimeout(() => document.getElementById('qs-addpub-key')?.focus(), 30);
  });
}

function sshMutationFailureText(r) {
  const base = r.message || r.error || 'Операция не выполнена';
  const detail = r.error && r.error !== r.message ? ` ${String(r.error).slice(0, 300)}` : '';
  const rollbackError = r.data?.rollback?.error ? ` · откат: ${String(r.data.rollback.error).slice(0, 200)}` : '';
  return `${base}${detail}${rollbackError}`;
}

async function onSshRoot(enabled) {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const approved = await confirmAction({
    title: enabled ? 'Разрешить root login?' : 'Запретить root login?',
    message: enabled ? 'PermitRootLogin yes' : 'Перед запретом нужен не-root пользователь в Bot4VPS.',
    confirmText: 'Применить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,`/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/root-login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    if (r.ok) { showContextToast(context,r.message || 'OK', true); await onSshRefresh({ quiet: true, force: true }); }
    else showContextToast(context,sshMutationFailureText(r), false);
  } catch (e) { showContextToast(context,e.message || 'Ошибка', false); }
  finally { setBusy(false, context); }
}

async function applySshPwdAuth(context, serverId, enabled) {
  setBusy(true, context);
  try {
    const r = await requestForContext(context,`/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/password-auth`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    if (r.ok) { showContextToast(context,r.message || 'OK', true); await onSshRefresh({ quiet: true, force: true }); }
    else showContextToast(context,sshMutationFailureText(r), false);
  } catch (e) { showContextToast(context,e.message || 'Ошибка', false); }
  finally { setBusy(false, context); }
}

// Перед отключением парольной авторизации. Возвращает:
// 'ready'    — ключ уже прописан в servers.json, можно отключать;
// 'selected' — пользователь выбрал ключ (прописан и проверен);
// null       — нет подходящего ключа (показана ошибка) или отмена.
async function offerQsKeyBeforePwdDisable(context, serverId) {
  try {
    const users = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users`,
    );
    const me = (users.data?.users || []).find((u) => u.current);
    if (!users.ok || !me) {
      showContextToast(context, users.message || users.error || 'Пользователи недоступны', false);
      return null;
    }
    const keys = await requestForContext(
      context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(me.username)}/keys`,
    );
    if (!keys.ok) {
      showContextToast(context, keys.message || keys.error || 'Ключи недоступны', false);
      return null;
    }
    const keyList = keys.data?.keys || [];
    // Ключ уже записан в servers.json («Выбрать ключ») и совпадает с
    // серверным — повторно предлагать выбор не нужно.
    if (keyList.some((k) => k.is_recorded)) return 'ready';
    const candidates = keyList.filter((k) => k.local_match && !k.route_uses_key);
    if (!candidates.length) {
      showContextToast(
        context,
        'Нет ключа: у Bot4VPS нет локального ключа, совпадающего с ключами пользователя на сервере. Сначала создайте ключ в «Менеджере ключей».',
        false,
      );
      return null;
    }
    const rows = candidates.map((k) => `<div class="qs-list-row qs-key-row">
        <div class="qs-user-info">
          <strong>${esc(k.type)}</strong>${k.key_name ? ` <span class="qs-status-chip">${esc(k.key_name)}</span>` : ''}
          <small style="font-family:ui-monospace,monospace">${esc(k.fingerprint)}</small>
        </div>
        <div class="qs-user-actions">
          <button type="button" class="qs-compact qs-pwdkey-select" data-fingerprint="${esc(k.fingerprint)}">Выбрать</button>
        </div>
      </div>`).join('');
    const choice = await new Promise((resolve) => {
      openQsListModal(
        'Отключить вход по паролю?',
        `<div class="qs-key-manager">
          <p>У Bot4VPS есть локальный ключ, совпадающий с ключом пользователя <strong>${esc(me.username)}</strong> на сервере. Выберите его — ключ будет прописан в servers.json, проверен реальным входом, и вход по паролю отключится.</p>
          ${rows}
          <div class="qs-section-actions">
            <button type="button" class="secondary" id="qs-pwdkey-cancel">Отмена</button>
          </div>
        </div>`,
        true,
      );
      qsModalChoiceResolve = resolve;
      const finish = (value) => {
        const pending = qsModalChoiceResolve;
        qsModalChoiceResolve = null;
        closeQsListModal();
        pending?.(value);
      };
      document.querySelectorAll('#qs-list-modal-body .qs-pwdkey-select').forEach((btn) => {
        btn.addEventListener('click', () => finish({ fingerprint: btn.dataset.fingerprint || '' }));
      });
      document.getElementById('qs-pwdkey-cancel')?.addEventListener('click', () => finish(null));
    });
    if (!choice) return null;
    setBusy(true, context);
    try {
      const r = await requestForContext(
        context,
        `/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh/users/${encodeURIComponent(me.username)}/keys/select`,
        {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fingerprint: choice.fingerprint }),
        },
      );
      showContextToast(context, r.message || r.error || 'Операция не выполнена', !!r.ok);
      return r.ok ? 'selected' : null;
    } catch (e) {
      showContextToast(context, e.message || 'Ошибка выбора ключа', false);
      return null;
    } finally { setBusy(false, context); }
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка', false);
    return null;
  }
}

async function onSshPwdAuth(enabled) {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  if (!enabled) {
    const prepared = await offerQsKeyBeforePwdDisable(context, serverId);
    if (!contextIsCurrent(context)) return;
    if (prepared !== 'ready' && prepared !== 'selected') return;
    // Ключ прописан в servers.json: backend выполнит все проверки
    // (файл, совпадение с сервером, реальный вход) и при успехе
    // отключит пароль — без повторных вопросов.
    await applySshPwdAuth(context, serverId, false);
    return;
  }
  const approved = await confirmAction({
    title: 'Включить password auth?',
    message: 'PasswordAuthentication yes',
    confirmText: 'Применить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  await applySshPwdAuth(context, serverId, enabled);
}

// Реестр ключей обнаружил, что файл ключа маршрута Bot4VPS уже
// используется на сервере другим пользователем (один ключ — один
// пользователь). Сообщаем и предлагаем создать новый в менеджере.
function maybeWarnSharedKey(s, serverId) {
  if (!s?.key_shared_with) return;
  const marker = `${serverId || ''}:${s.key_shared_with}`;
  if (qsSharedKeyWarned.has(marker)) return;
  qsSharedKeyWarned.add(marker);
  openQsListModal(
    'Ключ используется двумя пользователями',
    `<div class="qs-key-manager">
      <p>Вашим файлом ключа уже авторизовывается пользователь <strong>${esc(s.key_shared_with)}</strong>.
      Можете продолжать пользоваться этим же ключем, или создайте себе новый в менеджере ключей.</p>
      <div class="qs-section-actions">
        <button type="button" id="qs-sharedkey-ok">ОК</button>
        <button type="button" class="secondary" id="qs-sharedkey-manager">Менеджер ключей</button>
      </div>
    </div>`,
  );
  document.getElementById('qs-sharedkey-ok')?.addEventListener('click', closeQsListModal);
  document.getElementById('qs-sharedkey-manager')?.addEventListener('click', () => {
    closeQsListModal();
    onSshKeyManager();
  });
}

async function onSshRefresh(opts = {}) {
  const context = captureContext();
  if (!context) return;
  const { serverId } = context;
  const quiet = !!opts.quiet;
  if (busy && !opts.force) return;
  const wasBusy = busy;
  if (!wasBusy) setBusy(true, context);
  try {
    const r = await requestForContext(context,`/api/servers/${encodeURIComponent(serverId)}/quick-setup/ssh`);
    const el = document.getElementById('qs-sec-ssh');
    if (el && r.ssh_access) {
      if (lastOverview) lastOverview.ssh_access = r.ssh_access;
      const tmp = document.createElement('div');
      tmp.innerHTML = renderSshAccess(r.ssh_access);
      el.replaceWith(tmp.firstElementChild);
      bindActions();
      applyQsSection();
      // Селект ключа перерисовался пустым — заполняем заново (скрытый
      // по умолчанию, но при выборе «SSH-ключу» должен быть уже заполнен).
      fillSshSwitchKeySelect();
      maybeWarnSharedKey(r.ssh_access, serverId);
    }
    if (!quiet) showContextToast(context,'SSH-статус обновлён', true);
  } catch (e) {
    if (!quiet) showContextToast(context,e.message || 'Ошибка', false);
    else throw e;
  } finally {
    if (!wasBusy) setBusy(false, context);
  }
}

async function onF2bInstall() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const approved = await confirmAction({
    title: 'Установить Fail2ban?',
    message: 'Будет установлен пакет fail2ban. Правила блокировки не создаются и не включаются автоматически.',
    confirmText: 'Установить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/fail2ban/install`,
      { method: 'POST' },
    );
    if (r.ok) {
      showContextToast(context,r.message || 'Установлен', true);
      await reloadOverview({ updates: false }, context);
    } else showContextToast(context,r.message || 'Fail2ban не установлен', false);
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}


function f2bUrl(serverId, suffix) {
  return `/api/servers/${encodeURIComponent(serverId)}/quick-setup/fail2ban/${suffix}`;
}

function f2bJsonOptions(method, body) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

const F2B_JAIL_DESCRIPTIONS = {
  sshd: 'Защита SSH: блокирует IP после неудачных попыток входа по SSH.',
  'nginx-http-auth': 'Защита авторизации nginx (basic auth).',
  'nginx-botsearch': 'Блокирует ботов, сканирующих сайт на уязвимости (nginx).',
  'nginx-bad-request': 'Блокирует некорректные HTTP-запросы к nginx.',
  'nginx-limit-req': 'Блокирует IP, превышающие лимит запросов nginx.',
  'apache-auth': 'Защита авторизации Apache.',
  'apache-badbots': 'Блокирует известных ботов-коллекторов (Apache).',
  'apache-botsearch': 'Блокирует ботов, сканирующих сайт на уязвимости (Apache).',
  'apache-fakegooglebot': 'Блокирует подделки Googlebot (Apache).',
  'apache-modsecurity': 'Обрабатывает срабатывания ModSecurity (Apache).',
  'apache-nohome': 'Блокирует поиск домашних каталогов (Apache).',
  'apache-noscript': 'Блокирует запросы скриптов в статике (Apache).',
  'apache-overflows': 'Блокирует подозрительно длинные запросы (Apache).',
  'apache-shellshock': 'Блокирует атаки Shellshock (Apache).',
  postfix: 'Защита Postfix: злоупотребление почтовой доставкой.',
  'postfix-rbl': 'Блокирует IP из почтовых чёрных списков (Postfix).',
  'postfix-sasl': 'Блокирует перебор SMTP-авторизации (Postfix).',
  dovecot: 'Защита IMAP/POP3-авторизации Dovecot.',
  dropbear: 'Защита SSH-сервера dropbear.',
  proftpd: 'Защита FTP-сервера ProFTPD.',
  'pure-ftpd': 'Защита FTP-сервера Pure-FTPd.',
  vsftpd: 'Защита FTP-сервера vsftpd.',
  'named-refused': 'Блокирует запрещённые DNS-запросы BIND.',
  'mysqld-auth': 'Блокирует перебор паролей MySQL/MariaDB.',
  recidive: 'Повторные нарушители: повторный бан на неделю по всем портам.',
};

const F2B_JAIL_REASON_HINTS = {
  user_managed: 'задано в вашем файле конфигурации — измените его в разделе «Конфигурация»',
  unknown_source: 'включается вручную в конфигурации Fail2ban',
  missing_service: 'сервис не найден на сервере',
  missing_logs: 'сервис есть, но его логи недоступны Fail2ban',
  unknown: 'недостаточно данных для автоматического включения',
};

function f2bJailRow(jail, sshJailEnabled) {
  const name = jail.name || '—';
  const isSshd = name === 'sshd';
  const active = jail.active === true;
  const description = F2B_JAIL_DESCRIPTIONS[name] || '';
  const detailParts = [
    active && jail.banned != null ? `заблокировано: ${jail.banned}` : '',
    !isSshd && jail.source ? `источник: ${jail.source}` : '',
  ].filter(Boolean);
  const reasonHint = !isSshd && jail.reason
    ? (F2B_JAIL_REASON_HINTS[jail.reason] || '')
    : '';
  let control;
  if (isSshd) {
    const enabled = sshJailEnabled === true;
    control = `<button type="button" class="secondary qs-f2b-jail-toggle" data-enabled="${enabled ? '0' : '1'}">${enabled ? 'Выключить' : 'Включить'}</button>`;
  } else if (jail.toggleable === true) {
    control = `<button type="button" class="secondary qs-f2b-jail-toggle" data-jail="${esc(name)}" data-enabled="${active ? '0' : '1'}">${active ? 'Выключить' : 'Включить'}</button>`;
  } else {
    control = '<button type="button" class="secondary qs-f2b-jail-config">Настроить</button>';
  }
  return `<div class="qs-list-row qs-f2b-item qs-jail-row">
    <span class="qs-jail-info">
      <strong>${esc(name)}</strong>
      ${description ? `<small>${esc(description)}</small>` : ''}
      ${detailParts.length ? `<small class="qs-muted">${esc(detailParts.join(' · '))}</small>` : ''}
      ${reasonHint ? `<small class="qs-muted">${esc(reasonHint)}</small>` : ''}
      ${jail.error ? `<small class="qs-muted">${esc(jail.error)}</small>` : ''}
    </span>
    <span class="qs-jail-state">${active ? statusDot(true) + 'Включено' : statusDot(false) + 'Выключено'}</span>
    <span class="qs-jail-actions">${control}</span>
  </div>`;
}

function renderF2bJails(jails, sshJailEnabled) {
  const intro = '<p class="qs-list-note">Правила блокировки определяют, какие службы защищает Fail2ban. Перед включением проверяется конфигурация и фактическое состояние Fail2ban; при ошибке всё возвращается назад.</p>';
  const safe = Array.isArray(jails) ? jails : [];
  if (!safe.length) {
    return `${intro}<p class="qs-list-empty">Правила блокировки не найдены.</p>`;
  }
  const enabledJails = safe.filter((jail) => jail.active === true);
  const availableJails = safe.filter((jail) => jail.active !== true && (jail.name === 'sshd' || jail.toggleable === true));
  const manualJails = safe.filter((jail) => jail.active !== true && jail.name !== 'sshd' && jail.toggleable !== true);
  const rows = (list) => list.map((jail) => f2bJailRow(jail, sshJailEnabled)).join('');
  const enabledGroup = enabledJails.length
    ? `<div class="qs-jail-group"><div class="qs-jail-group-head">Включённые · ${enabledJails.length}</div>${rows(enabledJails)}</div>`
    : '';
  const availableGroup = availableJails.length
    ? `<div class="qs-jail-group"><div class="qs-jail-group-head">Доступные для включения · ${availableJails.length}</div>${rows(availableJails)}</div>`
    : '';
  const manualGroup = manualJails.length
    ? `<details class="qs-jail-group qs-jail-group-manual"><summary>Требуют ручной настройки · ${manualJails.length}</summary>${rows(manualJails)}</details>`
    : '';
  return intro + enabledGroup + availableGroup + manualGroup;
}

async function onF2bSshJailToggle(context, serverId, enabled) {
  const approved = await confirmAction({
    title: enabled ? 'Включить правило блокировки SSH?' : 'Выключить правило блокировки SSH?',
    message: enabled
      ? 'Fail2ban начнёт временно блокировать IP-адреса после неудачных попыток входа по SSH.'
      : 'Защита SSH от перебора паролей будет отключена.',
    confirmText: enabled ? 'Включить' : 'Выключить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const result = await requestForContext(
      context,
      f2bUrl(serverId, 'settings'),
      f2bJsonOptions('POST', { ssh_jail_enabled: enabled }),
    );
    showContextToast(
      context,
      result.message || (result.ok ? 'Правило блокировки обновлено' : 'Не удалось изменить правило блокировки'),
      !!result.ok,
    );
    if (result.ok) {
      await refreshF2bSection(context);
      await loadF2bJails(context, serverId);
    }
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка изменения правила блокировки', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bJailToggle(context, serverId, jail, enabled) {
  const dangerous = jail === 'recidive';
  const approved = await confirmAction({
    title: enabled ? `Включить правило блокировки ${jail}?` : `Выключить правило блокировки ${jail}?`,
    message: enabled
      ? (dangerous
        ? 'Правило recidive повторно блокирует нарушителей на неделю по всем портам. Убедитесь, что ваш собственный IP не может попасть под него.'
        : `Fail2ban начнёт отслеживать нарушения для ${jail} и временно блокировать IP-адреса.`)
      : `Защита ${jail} будет отключена.`,
    confirmText: enabled ? 'Включить' : 'Выключить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const result = await requestForContext(
      context,
      f2bUrl(serverId, `jails/${encodeURIComponent(jail)}/enabled`),
      f2bJsonOptions('POST', { enabled }),
    );
    showContextToast(
      context,
      result.message || (result.ok ? 'Правило блокировки обновлено' : 'Не удалось изменить правило блокировки'),
      !!result.ok,
    );
    if (result.ok) {
      await refreshF2bSection(context);
      await loadF2bJails(context, serverId);
    }
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка изменения правила блокировки', false);
  } finally {
    setBusy(false, context);
  }
}

function bindF2bJails(context, serverId) {
  const body = document.getElementById('qs-list-modal-body');
  body?.querySelectorAll('.qs-f2b-jail-toggle').forEach((button) => {
    button.addEventListener('click', () => {
      if (busy || !contextIsCurrent(context)) return;
      const enabled = button.dataset.enabled === '1';
      const jail = button.dataset.jail || '';
      if (jail) onF2bJailToggle(context, serverId, jail, enabled);
      else onF2bSshJailToggle(context, serverId, enabled);
    });
  });
  body?.querySelectorAll('.qs-f2b-jail-config').forEach((button) => {
    button.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      setBusy(true, context);
      try {
        await loadF2bConfiguration(context, serverId);
      } catch (error) {
        showContextToast(context, error.message || 'Не удалось открыть конфигурацию', false);
      } finally {
        setBusy(false, context);
      }
    });
  });
}

async function loadF2bJails(context, serverId) {
  const result = await requestForContext(context, f2bUrl(serverId, 'jails'));
  if (!contextIsCurrent(context)) return result;
  openQsListModal(
    'Правила блокировки',
    renderF2bJails(result.data?.jails || [], lastOverview?.fail2ban?.ssh_jail_enabled),
  );
  bindF2bJails(context, serverId);
  return result;
}

async function refreshF2bSection(context) {
  const r = await requestForContext(
    context,
    `/api/servers/${encodeURIComponent(context.serverId)}/quick-setup/fail2ban`,
  );
  if (!contextIsCurrent(context)) return;
  if (lastOverview && r.fail2ban) lastOverview.fail2ban = r.fail2ban;
  const el = document.getElementById('qs-sec-fail2ban');
  if (el && r.fail2ban) {
    const tmp = document.createElement('div');
    tmp.innerHTML = renderFail2ban(r.fail2ban);
    el.replaceWith(tmp.firstElementChild);
    bindActions();
    applyQsSection();
  }
}

const F2B_FILTER_DESCRIPTIONS = {
  sshd: 'неудачные попытки входа по SSH',
  'nginx-http-auth': 'неудачные попытки входа в nginx (basic auth)',
};

function renderF2bFilters(filters) {
  const intro = '<p class="qs-list-note">Фильтры определяют, какие записи в журналах служб Fail2ban считает подозрительной активностью. Фильтр выбирается в правиле блокировки.</p>';
  if (!Array.isArray(filters) || !filters.length) {
    return `${intro}<p class="qs-list-empty">Фильтры не найдены.</p>`;
  }
  return intro + filters.map((filter) => {
    const name = filter.name || filter.filename || '—';
    const description = F2B_FILTER_DESCRIPTIONS[name];
    const detail = [filter.filename || '—', description].filter(Boolean).join(' · ');
    return `<div class="qs-list-row qs-f2b-item">
      <span><strong>${esc(name)}</strong><small>${esc(detail)}</small></span>
    </div>`;
  }).join('');
}

function renderF2bBans(bans) {
  const safeBans = Array.isArray(bans)
    ? bans.filter((ban) => ban && ban.jail && ban.ip)
    : [];
  const intro = '<p class="qs-list-note">IP-адреса, заблокированные Fail2ban за нарушение правил. Разблокировка вступает в силу сразу.</p>';
  if (!safeBans.length) return `${intro}<p class="qs-list-empty">Заблокированных IP нет.</p>`;
  return intro + safeBans.map((ban) => `<div class="qs-list-row qs-f2b-item">
    <span><strong>${esc(ban.ip)}</strong><small>правило: ${esc(ban.jail)}</small></span>
    <button type="button" class="secondary danger qs-f2b-unban"
      data-jail="${esc(ban.jail)}" data-ip="${esc(ban.ip)}">Разблокировать</button>
  </div>`).join('');
}

function bindF2bBans(context, serverId) {
  const body = document.getElementById('qs-list-modal-body');
  body?.querySelectorAll('.qs-f2b-unban').forEach((button) => {
    button.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const jail = button.dataset.jail || '';
      const ip = button.dataset.ip || '';
      if (!jail || !ip) return;
      const approved = await confirmAction({
        title: 'Разблокировать IP?',
        message: `${jail}: ${ip}`,
        confirmText: 'Разблокировать',
        confirmFirst: true,
      });
      if (!approved || !contextIsCurrent(context)) return;
      setBusy(true, context);
      try {
        const result = await requestForContext(
          context,
          f2bUrl(serverId, 'unban'),
          f2bJsonOptions('POST', { jail, ip }),
        );
        showContextToast(context, result.message || 'Операция завершена', !!result.ok);
        if (result.ok) {
          button.closest('.qs-f2b-item')?.remove();
          if (body && !body.querySelector('.qs-f2b-unban')) {
            body.innerHTML = '<p class="qs-list-empty">Заблокированных IP нет.</p>';
          }
        }
      } catch (error) {
        showContextToast(context, error.message || 'Ошибка разблокировки', false);
      } finally {
        setBusy(false, context);
      }
    });
  });
}

function renderF2bWhitelist(entries) {
  const rows = Array.isArray(entries) && entries.length
    ? entries.map((entry) => `<div class="qs-list-row qs-f2b-item">
        <span><strong>${esc(entry.ip || '—')}</strong><small>${esc(entry.source || 'источник не указан')}</small></span>
        ${entry.managed === true
          ? `<button type="button" class="secondary danger qs-f2b-whitelist-remove"
              data-ip="${esc(entry.ip || '')}">Удалить</button>`
          : '<small class="qs-muted">Задан в конфигурации Fail2ban — изменить можно в разделе «Конфигурация»</small>'}
      </div>`).join('')
    : '<p class="qs-list-empty">Whitelist пуст.</p>';
  return `<div class="qs-f2b-whitelist-form">
    <p class="qs-list-note">Whitelist — IP-адреса, которые Fail2ban никогда не блокирует, даже при неудачных попытках входа.</p>
    <p class="qs-warn">Если вы заходите на сервер с постоянного IP-адреса или через VPN, добавьте его сюда — иначе вы можете заблокировать сами себя. Не добавляйте чужие публичные адреса.</p>
    <label for="qs-f2b-whitelist-ip">IP или CIDR</label>
    <div class="qs-port-form">
      <input id="qs-f2b-whitelist-ip" maxlength="64" inputmode="text" placeholder="192.0.2.10 или 2001:db8::/32">
      <button type="button" id="qs-f2b-whitelist-add">Добавить</button>
    </div>
    <div class="qs-f2b-list">${rows}</div>
  </div>`;
}

async function loadF2bWhitelist(context, serverId) {
  const result = await requestForContext(context, f2bUrl(serverId, 'whitelist'));
  if (!contextIsCurrent(context)) return result;
  openQsListModal('Whitelist', renderF2bWhitelist(result.data?.entries || []));
  bindF2bWhitelist(context, serverId);
  return result;
}

function bindF2bWhitelist(context, serverId) {
  const body = document.getElementById('qs-list-modal-body');
  const input = document.getElementById('qs-f2b-whitelist-ip');
  document.getElementById('qs-f2b-whitelist-add')?.addEventListener('click', async () => {
    if (busy || !contextIsCurrent(context)) return;
    const ip = input?.value?.trim() || '';
    if (!ip) {
      showContextToast(context, 'Укажите IP-адрес или CIDR', false);
      return;
    }
    setBusy(true, context);
    try {
      const result = await requestForContext(
        context,
        f2bUrl(serverId, 'whitelist'),
        f2bJsonOptions('POST', { ip }),
      );
      showContextToast(context, result.message || 'Whitelist не изменён', !!result.ok);
      if (result.ok) await loadF2bWhitelist(context, serverId);
    } catch (error) {
      showContextToast(context, error.message || 'Ошибка изменения Whitelist', false);
    } finally {
      setBusy(false, context);
    }
  });
  body?.querySelectorAll('.qs-f2b-whitelist-remove').forEach((button) => {
    button.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      const ip = button.dataset.ip || '';
      if (!ip) return;
      const approved = await confirmAction({
        title: 'Удалить IP из Whitelist?',
        message: ip,
        confirmText: 'Удалить',
        confirmFirst: true,
      });
      if (!approved || !contextIsCurrent(context)) return;
      setBusy(true, context);
      try {
        const result = await requestForContext(
          context,
          f2bUrl(serverId, 'whitelist'),
          f2bJsonOptions('DELETE', { ip }),
        );
        showContextToast(context, result.message || 'Whitelist не изменён', !!result.ok);
        if (result.ok) await loadF2bWhitelist(context, serverId);
      } catch (error) {
        showContextToast(context, error.message || 'Ошибка изменения Whitelist', false);
      } finally {
        setBusy(false, context);
      }
    });
  });
}

function f2bConfigKindLabel(kind) {
  if (kind === 'jail') return 'Jail (jail.d) · правила блокировки';
  if (kind === 'filter') return 'Filter (filter.d) · фильтры распознавания';
  return kind || '—';
}

function f2bConfigStandardNote(filename) {
  if (filename === 'jail.conf') return ' · штатный системный файл Fail2ban — изменяйте с осторожностью';
  if (filename === 'jail.local') return ' · стандартный файл переопределений';
  return '';
}

function renderF2bConfiguration(files) {
  const rows = Array.isArray(files) && files.length
    ? files.map((file) => {
      const standard = file.standard === true;
      return `<div class="qs-list-row qs-f2b-config-row">
        <span><strong>${esc(file.filename || '—')}</strong><small>${esc(f2bConfigKindLabel(file.kind))}${standard ? esc(f2bConfigStandardNote(file.filename)) : ''}</small></span>
        <span class="qs-f2b-config-actions">
          <button type="button" class="secondary qs-f2b-config-open"
            data-kind="${esc(file.kind || '')}" data-filename="${esc(file.filename || '')}">Открыть</button>
          ${standard ? '' : `<button type="button" class="secondary danger qs-f2b-config-delete"
            data-kind="${esc(file.kind || '')}" data-filename="${esc(file.filename || '')}">Удалить</button>`}
        </span>
      </div>`;
    }).join('')
    : '<p class="qs-list-empty">Файлы конфигурации не найдены.</p>';
  return `<p class="qs-list-note">Расширенные настройки Fail2ban в файлах конфигурации. Большинству пользователей редактирование не требуется — основные настройки доступны выше. Штатные файлы jail.conf и jail.local нельзя удалить через Quick Setup; изменения проверяются, при ошибке файл восстанавливается.</p>
  <div class="qs-f2b-config-create">
    <strong>Добавить конфиг</strong>
    <div class="qs-port-form">
      <select id="qs-f2b-config-kind" aria-label="Тип нового файла">
        <option value="jail">Jail (jail.d)</option>
        <option value="filter">Filter (filter.d)</option>
      </select>
      <input id="qs-f2b-config-filename" maxlength="128" placeholder="custom.local" aria-label="Имя нового файла">
    </div>
    <textarea id="qs-f2b-config-new-content" rows="4" maxlength="524288" placeholder="Содержимое нового файла"></textarea>
    <button type="button" id="qs-f2b-config-create-btn">Добавить конфиг</button>
  </div>
  <div class="qs-f2b-list">${rows}</div>`;
}

function configRefFromElement(element) {
  return {
    kind: element?.dataset?.kind || '',
    filename: element?.dataset?.filename || '',
  };
}

function renderF2bConfigEditor(ref, standard = false) {
  return `<div class="qs-f2b-config-editor">
    <button type="button" class="secondary" id="qs-f2b-config-back">← К списку файлов</button>
    <p class="qs-muted">${esc(ref.kind)} / ${esc(ref.filename)}${standard ? ' · стандартный файл' : ''}</p>
    ${standard ? '<p class="qs-warn">Это стандартный файл Fail2ban. Сохранение потребует отдельного подтверждения; удалить его через Quick Setup нельзя.</p>' : ''}
    <textarea id="qs-f2b-config-content" rows="18" maxlength="524288" spellcheck="false"></textarea>
    <div class="qs-section-actions">
      <button type="button" id="qs-f2b-config-save">Сохранить</button>
      ${standard ? '' : '<button type="button" class="secondary danger" id="qs-f2b-config-delete-editor">Удалить файл</button>'}
    </div>
    <p class="qs-muted">Перед сохранением выполняются fail2ban-client -t, reload и проверка; при ошибке файл восстанавливается.</p>
  </div>`;
}

function isStandardF2bConfig(ref) {
  return ref?.kind === 'jail' && ['jail.conf', 'jail.local'].includes(ref?.filename);
}

async function loadF2bConfiguration(context, serverId) {
  const result = await requestForContext(context, f2bUrl(serverId, 'configuration'));
  if (!contextIsCurrent(context)) return result;
  const files = result.data?.files || [];
  openQsListModal('Конфигурация', renderF2bConfiguration(files));
  bindF2bConfiguration(context, serverId, files);
  return result;
}

async function openF2bConfigurationFile(context, serverId, ref) {
  const params = new URLSearchParams({ kind: ref.kind, filename: ref.filename });
  const result = await requestForContext(
    context,
    `${f2bUrl(serverId, 'configuration/content')}?${params.toString()}`,
  );
  if (!contextIsCurrent(context)) return;
  const standard = isStandardF2bConfig(ref);
  openQsListModal(
    `Конфигурация · ${ref.filename}`,
    renderF2bConfigEditor(ref, standard),
  );
  const content = document.getElementById('qs-f2b-config-content');
  if (content) content.value = String(result.data?.content || '');
  bindF2bConfigEditor(context, serverId, ref, standard);
}

function validConfigFilename(kind, filename) {
  const common = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:conf|local)$/.test(filename)
    && !filename.includes('..');
  if (!common) return false;
  return kind === 'jail' || (kind === 'filter' && filename.endsWith('.conf'));
}

function bindF2bConfiguration(context, serverId, files = []) {
  const body = document.getElementById('qs-list-modal-body');
  const existing = new Set(
    (Array.isArray(files) ? files : []).map((file) => `${file.kind}:${file.filename}`),
  );
  body?.querySelectorAll('.qs-f2b-config-open').forEach((button) => {
    button.addEventListener('click', async () => {
      if (busy || !contextIsCurrent(context)) return;
      setBusy(true, context);
      try {
        await openF2bConfigurationFile(context, serverId, configRefFromElement(button));
      } catch (error) {
        showContextToast(context, error.message || 'Ошибка чтения конфигурации', false);
      } finally {
        setBusy(false, context);
      }
    });
  });
  body?.querySelectorAll('.qs-f2b-config-delete').forEach((button) => {
    button.addEventListener('click', () => deleteF2bConfiguration(context, serverId, configRefFromElement(button)));
  });
  document.getElementById('qs-f2b-config-create-btn')?.addEventListener('click', async () => {
    if (busy || !contextIsCurrent(context)) return;
    const kind = document.getElementById('qs-f2b-config-kind')?.value || '';
    const filename = document.getElementById('qs-f2b-config-filename')?.value?.trim() || '';
    const content = document.getElementById('qs-f2b-config-new-content')?.value || '';
    if (!['jail', 'filter'].includes(kind) || !validConfigFilename(kind, filename)) {
      showContextToast(
        context,
        kind === 'filter'
          ? 'Для Filter разрешено безопасное имя файла .conf'
          : 'Для Jail разрешено безопасное имя файла .conf или .local',
        false,
      );
      return;
    }
    if (isStandardF2bConfig({ kind, filename })) {
      showContextToast(context, 'Стандартные файлы нельзя создавать через эту форму', false);
      return;
    }
    if (existing.has(`${kind}:${filename}`)) {
      showContextToast(context, 'Файл уже существует. Откройте его для изменения', false);
      return;
    }
    setBusy(true, context);
    try {
      const result = await requestForContext(
        context,
        f2bUrl(serverId, 'configuration/content'),
        f2bJsonOptions('PUT', {
          kind,
          filename,
          content,
          create_only: true,
        }),
      );
      showContextToast(context, result.message || 'Файл не создан', !!result.ok);
      if (result.ok) await loadF2bConfiguration(context, serverId);
    } catch (error) {
      showContextToast(context, error.message || 'Ошибка создания файла', false);
    } finally {
      setBusy(false, context);
    }
  });
}

async function deleteF2bConfiguration(context, serverId, ref) {
  if (busy || !contextIsCurrent(context)) return;
  const approved = await confirmAction({
    title: `Удалить ${ref.filename}?`,
    message: 'Файл будет удалён после проверки конфигурации. Стандартные файлы удалить нельзя.',
    confirmText: 'Удалить файл',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const result = await requestForContext(
      context,
      f2bUrl(serverId, 'configuration/content'),
      f2bJsonOptions('DELETE', ref),
    );
    showContextToast(context, result.message || 'Файл не удалён', !!result.ok);
    if (result.ok) await loadF2bConfiguration(context, serverId);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка удаления файла', false);
  } finally {
    setBusy(false, context);
  }
}

function bindF2bConfigEditor(context, serverId, ref, standard = false) {
  document.getElementById('qs-f2b-config-back')?.addEventListener('click', async () => {
    if (busy || !contextIsCurrent(context)) return;
    setBusy(true, context);
    try {
      await loadF2bConfiguration(context, serverId);
    } catch (error) {
      showContextToast(context, error.message || 'Ошибка списка конфигурации', false);
    } finally {
      setBusy(false, context);
    }
  });
  document.getElementById('qs-f2b-config-save')?.addEventListener('click', async () => {
    if (busy || !contextIsCurrent(context)) return;
    if (standard) {
      const approved = await confirmAction({
        title: `Изменить стандартный файл ${ref.filename}?`,
        message: 'Ошибка в стандартном файле может остановить Fail2ban. Перед применением будет выполнена проверка, а при неудаче — точный rollback.',
        confirmText: 'Проверить и сохранить',
        confirmFirst: true,
      });
      if (!approved || !contextIsCurrent(context)) return;
    }
    const content = document.getElementById('qs-f2b-config-content')?.value || '';
    setBusy(true, context);
    try {
      const result = await requestForContext(
        context,
        f2bUrl(serverId, 'configuration/content'),
        f2bJsonOptions('PUT', { ...ref, content }),
      );
      showContextToast(context, result.message || 'Конфигурация не сохранена', !!result.ok);
      if (result.ok) await openF2bConfigurationFile(context, serverId, ref);
    } catch (error) {
      showContextToast(context, error.message || 'Ошибка сохранения конфигурации', false);
    } finally {
      setBusy(false, context);
    }
  });
  const deleteButton = document.getElementById('qs-f2b-config-delete-editor');
  if (standard) {
    if (deleteButton) {
      deleteButton.disabled = true;
      deleteButton.title = 'Стандартный файл нельзя удалить';
    }
  } else {
    deleteButton?.addEventListener('click', () => deleteF2bConfiguration(context, serverId, ref));
  }
}

async function onF2bStart() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await requestForContext(context, f2bUrl(serverId, 'start'), { method: 'POST' });
    if (result.ok) {
      showContextToast(context, result.message || 'Fail2ban запущен', true);
      await reloadOverview({ updates: false }, context);
    } else showContextToast(context, result.message || 'Fail2ban не запущен', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка запуска Fail2ban', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bStop() {
  const context = captureContext();
  if (busy || !context) return;
  const approved = await confirmAction({
    title: 'Остановить Fail2ban?',
    message: 'Остановить Fail2ban? Защита от перебора будет отключена.',
    confirmText: 'Остановить',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await requestForContext(context, f2bUrl(serverId, 'stop'), { method: 'POST' });
    if (result.ok) {
      showContextToast(context, result.message || 'Fail2ban остановлен', true);
      await reloadOverview({ updates: false }, context);
    } else showContextToast(context, result.message || 'Fail2ban не остановлен', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка остановки Fail2ban', false);
  } finally {
    setBusy(false, context);
  }
}

function chooseF2bUninstallPolicy() {
  openQsListModal(
    'Удалить Fail2ban?',
    `<div class="qs-f2b-uninstall-choice">
      <p>Выберите, что сделать с конфигурацией Fail2ban после удаления пакета.</p>
      <div class="qs-section-actions">
        <button type="button" id="qs-f2b-uninstall-keep">Сохранить конфигурацию</button>
        <button type="button" class="secondary danger" id="qs-f2b-uninstall-remove">Удалить конфигурацию</button>
        <button type="button" class="secondary" id="qs-f2b-uninstall-cancel">Отмена</button>
      </div>
    </div>`,
  );
  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const finish = (value) => {
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.(value);
    };
    document.getElementById('qs-f2b-uninstall-keep')?.addEventListener('click', () => finish(false));
    document.getElementById('qs-f2b-uninstall-remove')?.addEventListener('click', () => finish(true));
    document.getElementById('qs-f2b-uninstall-cancel')?.addEventListener('click', () => finish(null));
  });
}

async function onF2bUninstall() {
  const context = captureContext();
  if (busy || !context) return;
  const removeConfig = await chooseF2bUninstallPolicy();
  if (removeConfig === null || !contextIsCurrent(context)) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await requestForContext(
      context,
      f2bUrl(serverId, 'uninstall'),
      f2bJsonOptions('POST', { remove_config: removeConfig }),
    );
    if (result.ok) {
      showContextToast(context, result.message || 'Fail2ban удалён', true);
      await reloadOverview({ updates: false }, context);
    } else showContextToast(context, result.message || 'Fail2ban не удалён', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка удаления Fail2ban', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bJails() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await loadF2bJails(context, serverId);
    if (!result?.ok) showContextToast(context, result?.message || 'Правила блокировки недоступны', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка получения Правила блокировки', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bFilters() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await requestForContext(context, f2bUrl(serverId, 'filters'));
    openQsListModal('Фильтры', renderF2bFilters(result.data?.filters || []));
    if (!result.ok) showContextToast(context, result.message || 'Фильтры недоступны', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка получения Фильтры', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bWhitelist() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await loadF2bWhitelist(context, serverId);
    if (!result?.ok) showContextToast(context, result?.message || 'Whitelist недоступен', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка получения Whitelist', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bConfiguration() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await loadF2bConfiguration(context, serverId);
    if (!result?.ok) showContextToast(context, result?.message || 'Конфигурация недоступна', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка получения конфигурации', false);
  } finally {
    setBusy(false, context);
  }
}
async function onF2bApply() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const fb = lastOverview?.fail2ban;
  if (fb?.state && fb.state !== 'running') {
    showContextToast(context, 'Сначала запустите Fail2ban', false);
    return;
  }
  const body = {
    ban_time: document.getElementById('qs-f2b-bantime')?.value?.trim() || undefined,
    find_time: document.getElementById('qs-f2b-findtime')?.value?.trim() || undefined,
    max_retry: parseInt(document.getElementById('qs-f2b-maxretry')?.value, 10) || undefined,
  };
  if (body.max_retry != null && body.max_retry <= 2) {
    const approved = await confirmAction({
      title: 'Применить агрессивные настройки?',
      message: `Fail2ban будет блокировать IP уже после ${body.max_retry} ${f2bPluralForm(body.max_retry, 'неудачной попытки', 'неудачных попыток', 'неудачных попыток')} входа. Убедитесь, что это не заблокирует ваш собственный доступ.`,
      confirmText: 'Применить',
      confirmFirst: true,
    });
    if (!approved || !contextIsCurrent(context)) return;
  }
  if (fb?.ssh_jail_enabled !== true) {
    const approved = await confirmAction({
      title: 'Включить правило блокировки SSH?',
      message: 'Правило блокировки SSH сейчас неактивно, поэтому настройки защиты применить нельзя. Включить его вместе с настройками?',
      confirmText: 'Включить и применить',
      confirmFirst: true,
    });
    if (!approved || !contextIsCurrent(context)) return;
    body.ssh_jail_enabled = true;
  }
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/fail2ban/settings`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    );
    if (r.ok) {
      showContextToast(context,r.message || 'Настройки применены', true);
      await reloadOverview({ updates: false }, context);
    } else showContextToast(context,r.message || 'Настройки не применены', false);
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка применения настроек', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bBanned() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const result = await requestForContext(context, f2bUrl(serverId, 'banned'));
    openQsListModal('Заблокированные IP', renderF2bBans(result.data?.bans || []));
    bindF2bBans(context, serverId);
    if (!result.ok) showContextToast(context, result.message || 'Список банов недоступен', false);
  } catch (error) {
    showContextToast(context, error.message || 'Ошибка получения списка банов', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bRestart() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/fail2ban/restart`,
      { method: 'POST' },
    );
    if (r.ok) {
      showContextToast(context,r.message || 'Перезапущен', true);
      await reloadOverview({ updates: false }, context);
    } else showContextToast(context,r.message || 'Перезапуск не выполнен', false);
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

async function onF2bRefresh() {
  const context = captureContext();
  if (busy || !context) return;
  setBusy(true, context);
  try {
    await refreshF2bSection(context);
    showContextToast(context,'Статус Fail2ban обновлён', true);
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка обновления статуса Fail2ban', false);
  } finally {
    setBusy(false, context);
  }
}


function modalFocusable(bg) {
  return [...bg.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((el) => !el.hidden && el.getClientRects().length > 0);
}

function openQsListModal(title, bodyHtml, wide = false) {
  const bg = document.getElementById('qs-list-modal');
  const titleEl = document.getElementById('qs-list-modal-title');
  const body = document.getElementById('qs-list-modal-body');
  if (!bg || !body) return;
  if (qsModalChoiceResolve) {
    const resolve = qsModalChoiceResolve;
    qsModalChoiceResolve = null;
    resolve(null);
  }
  qsModalReturnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
  // Ширину задаём при каждом открытии: менеджер ключей шире обычных окон.
  const modalEl = bg.querySelector('.modal');
  if (modalEl) modalEl.style.width = wide ? 'min(640px,100%)' : 'min(480px,100%)';
  if (titleEl) titleEl.textContent = title;
  body.innerHTML = bodyHtml;
  bg.classList.add('open');
  requestAnimationFrame(() => {
    const focusable = modalFocusable(bg);
    (focusable[0] || bg.querySelector('.modal'))?.focus();
  });
}

function closeQsListModal() {
  const bg = document.getElementById('qs-list-modal');
  const choiceResolve = qsModalChoiceResolve;
  qsModalChoiceResolve = null;
  if (!bg?.classList.contains('open')) {
    choiceResolve?.(null);
    return;
  }
  bg.classList.remove('open');
  const returnFocus = qsModalReturnFocus;
  qsModalReturnFocus = null;
  choiceResolve?.(null);
  if (returnFocus?.isConnected) requestAnimationFrame(() => returnFocus.focus());
}

function bindQsListModal() {
  const bg = document.getElementById('qs-list-modal');
  if (!bg || bg.dataset.bound) return;
  bg.dataset.bound = '1';
  const dialog = bg.querySelector('.modal');
  if (dialog && !dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
  document.getElementById('qs-list-modal-close')?.addEventListener('click', closeQsListModal);
  // Модалки закрываются только явными действиями (крестик/Esc/кнопки):
  // случайный клик мимо окна больше не закрывает их.
  document.addEventListener('keydown', (e) => {
    if (!bg.classList.contains('open')) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeQsListModal();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = modalFocusable(bg);
    if (!focusable.length) {
      e.preventDefault();
      dialog?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
}

async function onFwInstall(backend) {
  const context = captureContext();
  if (busy || !context || !backend) return;
  const { serverId } = context;
  const activeSources = _fwActiveCandidates(lastOverview?.firewall);
  if (activeSources.length > 1) {
    showContextToast(
      context,
      'Обнаружено несколько активных firewall. Сначала устраните конфликт и обновите статус.',
      false,
    );
    return;
  }

  const source = activeSources.length === 1 ? activeSources[0] : null;
  const targetLabel = _fwBackendLabel(backend);
  const sourceLabel = source
    ? (source.label || _fwBackendLabel(source.backend))
    : '';
  const approved = await confirmAction(source ? {
    title: `Установить и активировать ${targetLabel}?`,
    message: `Сейчас активен ${sourceLabel}. Bot4VPS выполнит: установить ${targetLabel} → перенести понятные правила → проверить SSH → отключить текущий firewall ${sourceLabel}.`,
    confirmText: 'Установить и активировать',
    cancelText: 'Отмена',
    confirmFirst: true,
  } : {
    title: `Установить и активировать ${targetLabel}?`,
    message: `Будет установлен и включён ${targetLabel}. Текущий SSH-порт будет разрешён и проверен автоматически.`,
    confirmText: 'Установить и активировать',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;

  await executeFwTransaction(
    _fwInstallTransaction(serverId, backend, Boolean(source)),
    context,
  );
}

function _fwPortArgs() {
  const port = parseInt(document.getElementById('qs-fw-port')?.value, 10);
  const protocol = document.getElementById('qs-fw-proto')?.value || 'tcp';
  const source = document.getElementById('qs-fw-source')?.value.trim() || '';
  return { port, protocol, source };
}

function _fwResetPortForm() {
  const source = document.getElementById('qs-fw-source');
  const proto = document.getElementById('qs-fw-proto');
  const port = document.getElementById('qs-fw-port');
  if (source) source.value = '';
  if (proto) proto.value = 'tcp';
  if (port) port.value = '';
  if (source) source.dataset.autodotPrev = '';
  _fwSourceRefresh();
}

function _fwInstallTransaction(serverId, backend, confirmSwitch) {
  return {
    url: `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/install`,
    failureMessage: 'Установка и активация firewall не выполнена',
    buildBody(continuation) {
      const body = { backend };
      if (confirmSwitch) body.confirm_switch = true;
      if (continuation) body.continuation = continuation;
      return body;
    },
  };
}

function _fwSwitchTransaction(serverId, target) {
  return {
    url: `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/switch`,
    failureMessage: 'Переключение firewall не выполнено',
    buildBody(continuation, selectedRules) {
      const body = { target, confirm: true };
      if (continuation) body.continuation = continuation;
      if (selectedRules !== null && selectedRules !== undefined) {
        body.selected_rules = selectedRules;
      }
      return body;
    },
  };
}

function _fwMigrationTransaction(serverId, target) {
  return {
    url: `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/migration`,
    failureMessage: 'Миграция firewall не выполнена',
    buildBody(continuation) {
      const body = { target, confirm: true };
      if (continuation) body.continuation = continuation;
      return body;
    },
  };
}

function _fwRecoverableModal(result) {
  const decision = result.data?.decision_required;
  let title;
  let message;
  let items = [];
  let selectable = false;
  let migratableRules = [];
  let ambiguousRules = [];

  if (decision === 'continue_without_rule_migration') {
    title = 'Правила текущего firewall недоступны';
    message = 'Не удалось прочитать правила текущего firewall. Продолжить — начнёт новую попытку без автоматического переноса правил. Отмена — сохранит текущий firewall без изменений.';
    items = (Array.isArray(result.data?.inventory_errors) ? result.data.inventory_errors : [])
      .map(item => item?.backend ? `Правила ${_fwBackendLabel(item.backend)} не прочитаны` : '')
      .filter(Boolean);
  } else if (decision === 'skip_ambiguous_rules') {
    selectable = true;
    migratableRules = (Array.isArray(result.data?.migratable_rules) ? result.data.migratable_rules : [])
      .filter(item => item && typeof item === 'object');
    ambiguousRules = Array.isArray(result.data?.ambiguous_rules) ? result.data.ambiguous_rules : [];
    title = 'Выбор правил для переноса';
    message = 'Отметьте правила, которые нужно перенести на новый firewall. Неотмеченные и неоднозначные правила перенесены не будут. SSH-порт останется открытым в любом случае. Отмена — сохранит текущий firewall без изменений.';
  } else if (decision === 'skip_failed_rules') {
    title = 'Не все правила удалось перенести';
    message = 'Изменения текущей попытки полностью откатаны, source firewall и SSH подтверждены. Продолжить — начнёт новую чистую попытку без перечисленных правил. Отмена оставит source firewall активным.';
    items = (Array.isArray(result.data?.failed_rules) ? result.data.failed_rules : [])
      .map((item) => {
        const port = item?.port ?? '—';
        const protocol = item?.protocol || 'tcp';
        const source = item?.source ? ` от ${item.source}` : '';
        const sources = Array.isArray(item?.from) && item.from.length
          ? ` (${item.from.map(_fwBackendLabel).join(', ')})`
          : '';
        return `${port}/${protocol}${source}${sources}`;
      });
  } else {
    return Promise.resolve(null);
  }

  const ruleLabel = (item) => {
    const port = item?.port ?? '—';
    const protocol = item?.protocol || 'tcp';
    const source = item?.source ? ` от ${item.source}` : '';
    const sources = Array.isArray(item?.from) && item.from.length
      ? ` (${item.from.map(_fwBackendLabel).join(', ')})`
      : '';
    return `${port}/${protocol}${source}${sources}`;
  };
  const list = items.length
    ? `<ul class="qs-fw-plan-actions">${items.map(item => `<li><code>${esc(item)}</code></li>`).join('')}</ul>`
    : '';
  const checkboxes = migratableRules.length
    ? `<ul class="qs-fw-plan-actions qs-fw-rule-choices">${migratableRules.map((item, index) => (
      `<li><label class="qs-fw-rule-choice">`
      + `<input type="checkbox" class="qs-fw-rule-select" data-index="${index}" checked> `
      + `<code>${esc(ruleLabel(item))}</code></label></li>`
    )).join('')}</ul>`
    : '';
  const ambiguousList = ambiguousRules.length
    ? '<p class="qs-fw-rule-note">Не подлежат переносу:</p>'
      + `<ul class="qs-fw-plan-actions">${ambiguousRules.map((item) => {
        const backend = item?.backend ? `${_fwBackendLabel(item.backend)}: ` : '';
        return `<li><code>${esc(`${backend}${item?.rule || 'Правило без описания'}`)}</code></li>`;
      }).join('')}</ul>`
    : '';
  const selectionNote = selectable
    ? '<p id="qs-fw-selection-note" class="qs-fw-rule-note" hidden>Не выбрано ни одного правила: на новый firewall будет перенесён только SSH-порт.</p>'
    : '';
  openQsListModal(
    title,
    `<div class="qs-fw-plan">
      <p>${esc(message)}</p>
      ${list}
      ${checkboxes}
      ${ambiguousList}
      ${selectionNote}
      <div class="qs-section-actions">
        <button type="button" id="qs-fw-decision-continue">Продолжить</button>
        <button type="button" class="secondary" id="qs-fw-decision-cancel">Отмена</button>
      </div>
    </div>`,
  );

  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const selectedRules = () => {
      if (!selectable) return null;
      return [...document.querySelectorAll('.qs-fw-rule-select')]
        .filter(box => box.checked)
        .map((box) => {
          const item = migratableRules[Number(box.dataset.index)];
          return {
            port: item?.port,
            protocol: item?.protocol || 'tcp',
            source: item?.source || '',
          };
        });
    };
    const finish = (approved) => {
      const chosen = approved ? selectedRules() : null;
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.({ approved, selectedRules: chosen });
    };
    document.getElementById('qs-fw-decision-continue')?.addEventListener('click', () => finish(true));
    document.getElementById('qs-fw-decision-cancel')?.addEventListener('click', () => finish(false));
    if (selectable) {
      const note = document.getElementById('qs-fw-selection-note');
      const boxes = () => [...document.querySelectorAll('.qs-fw-rule-select')];
      const syncNote = () => {
        if (note) note.hidden = boxes().some(box => box.checked);
      };
      boxes().forEach((box) => box.addEventListener('change', syncNote));
      syncNote();
    }
  });
}

function _fwContinuationFrom(result) {
  const continuation = result.data?.continue_with;
  return continuation && typeof continuation === 'object' && !Array.isArray(continuation)
    ? continuation
    : null;
}

function _fwRollbackUnverified(result) {
  const data = result.data;
  if (!data || data.changed !== true) return false;
  if (data.rollback) return data.rollback.verified !== true;
  return data.phase === 'rollback';
}

async function executeFwTransaction(operation, context) {
  if (busy || !contextIsCurrent(context)) return;
  let continuation = null;
  let selectedRules = null;
  setBusy(true, context);
  try {
    while (contextIsCurrent(context)) {
      const result = await requestForContext(
        context,
        operation.url,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(operation.buildBody(continuation, selectedRules)),
        },
      );
      if (result.ok) {
        showContextToast(context, result.message || 'Операция выполнена', true);
        break;
      }

      const decision = result.data?.decision_required;
      if (
        decision === 'continue_without_rule_migration'
        || decision === 'skip_ambiguous_rules'
        || decision === 'skip_failed_rules'
      ) {
        if (decision === 'skip_failed_rules' && result.data?.rollback?.verified !== true) {
          showContextToast(
            context,
            result.message || 'Rollback firewall и SSH не подтверждён. Автоматическое продолжение заблокировано.',
            false,
          );
          break;
        }
        const nextContinuation = _fwContinuationFrom(result);
        if (!nextContinuation) {
          showContextToast(
            context,
            result.message || 'Сервер не выдал безопасное продолжение операции firewall',
            false,
          );
          break;
        }
        const choice = await _fwRecoverableModal(result);
        if (!choice?.approved || !contextIsCurrent(context)) break;
        continuation = nextContinuation;
        selectedRules = choice.selectedRules ?? null;
        continue;
      }

      if (result.data?.critical === true) {
        if (_fwRollbackUnverified(result)) {
          showContextToast(
            context,
            result.message || 'Безопасное исходное состояние firewall не подтверждено. Автоматический повтор заблокирован.',
            false,
          );
          break;
        }
        const retry = await confirmAction({
          title: 'Операция firewall остановлена',
          message: result.message || `Сбой на этапе ${result.data?.phase || 'проверки firewall'}.`,
          confirmText: 'Повторить',
          cancelText: 'Отмена',
          confirmFirst: true,
        });
        if (!retry || !contextIsCurrent(context)) break;
        continue;
      }

      showContextToast(
        context,
        result.message || result.error || operation.failureMessage,
        false,
      );
      break;
    }
  } catch (error) {
    showContextToast(context, error.message || operation.failureMessage, false);
  } finally {
    try { await reloadOverview({ updates: false }, context); } catch (_) { /* status remains unchanged */ }
    setBusy(false, context);
  }
}

async function executeFwMigration(target, context = captureContext()) {
  if (!context || !target) return;
  await executeFwTransaction(
    _fwMigrationTransaction(context.serverId, target),
    context,
  );
}

async function onFwPort(action) {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const { port, protocol, source } = _fwPortArgs();
  if (!port || port < 1 || port > 65535) {
    showContextToast(context,'Укажите порт 1–65535', false);
    return;
  }
  const rule = `${port}/${protocol}${source ? ` от ${source}` : ''}`;
  const acknowledgeConflict = _fwHasConflict();
  if (acknowledgeConflict) {
    const approved = await _confirmFwConflict(
      context,
      action === 'open' ? `Открытие ${rule}` : `Безопасное закрытие ${rule}`,
    );
    if (!approved) return;
  }
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/${action}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          port,
          protocol,
          source,
          acknowledge_firewall_conflict: acknowledgeConflict,
        }),
      },
    );
    if (r.ok) {
      showContextToast(context,r.message || 'OK', true);
      if (action === 'open') _fwResetPortForm();
    } else {
      showContextToast(context,r.message || r.error || 'Ошибка', false);
    }
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

async function onFwDisable() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  const approved = await confirmAction({
    title: 'Отключить firewall?',
    message: 'Правила сохранятся, но перестанут применяться до следующего включения.',
    confirmText: 'Отключить',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/disable`,
      { method: 'POST' },
    );
    if (r.ok) {
      showContextToast(context, r.message || 'OK', true);
      await reloadOverview({ updates: false }, context);
    } else {
      showContextToast(context, r.message || r.error || 'Ошибка', false);
    }
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

async function _fwEnableRequest(target, context) {
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/enable`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend: target }),
      },
    );
    if (r.ok) {
      showContextToast(context, r.message || 'OK', true);
      await reloadOverview({ updates: false }, context);
    } else {
      showContextToast(context, r.message || r.error || 'Ошибка', false);
    }
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

async function onFwEnable(target) {
  const context = captureContext();
  if (busy || !context || !target) return;
  const label = _fwBackendLabel(target);
  const approved = await confirmAction({
    title: `Включить ${label}?`,
    message: `${label} снова начнёт фильтровать трафик по сохранённым правилам. Текущий SSH-порт будет разрешён и проверен автоматически.`,
    confirmText: 'Включить',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  await _fwEnableRequest(target, context);
}

async function onFwRemove(target) {
  const context = captureContext();
  if (busy || !context || !target) return;
  const { serverId } = context;
  const label = _fwBackendLabel(target);
  const nftablesNote = target === 'nftables'
    ? ' Правила, уже загруженные в kernel, не удалялись и останутся до перезагрузки сервера.'
    : '';
  const approved = await confirmAction({
    title: `Удалить ${label}?`,
    message: `Пакет ${label} будет удалён с сервера (без purge — конфигурация сохраняется). Если ${label} активен, он сначала будет отключён.${nftablesNote}`,
    confirmText: 'Удалить',
    cancelText: 'Отмена',
    confirmFirst: true,
  });
  if (!approved || !contextIsCurrent(context)) return;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/remove`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend: target }),
      },
    );
    if (r.ok) {
      showContextToast(context, r.message || 'OK', true);
      await reloadOverview({ updates: false }, context);
      await _fwOfferEnableAfterRemove(context);
    } else {
      showContextToast(context, r.message || r.error || 'Ошибка', false);
    }
  } catch (e) {
    showContextToast(context, e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}

function _fwInstalledInactiveBackends(fw) {
  const list = Array.isArray(fw?.backends) ? fw.backends : [];
  return list
    .filter(c => (
      c && c.backend
      && c.installed !== false
      && c.active !== true
      && c.manageable !== false
    ))
    .map(c => c.backend);
}

function _fwChooseEnableAfterRemove(names) {
  const buttons = names.map(name => (
    `<button type="button" data-fw-enable-choice="${esc(name)}">Включить ${esc(_fwBackendLabel(name))}</button>`
  )).join('');
  openQsListModal(
    'Firewall удалён',
    `<div class="qs-fw-enable-choice">
      <p>Хотите включить один из установленных firewall?</p>
      <div class="qs-section-actions">${buttons}
        <button type="button" class="secondary" data-fw-enable-cancel>Не включать</button>
      </div>
    </div>`,
  );
  return new Promise((resolve) => {
    qsModalChoiceResolve = resolve;
    const finish = (value) => {
      const pending = qsModalChoiceResolve;
      qsModalChoiceResolve = null;
      closeQsListModal();
      pending?.(value);
    };
    document.querySelectorAll('[data-fw-enable-choice]').forEach(btn => {
      btn.addEventListener('click', () => finish(btn.dataset.fwEnableChoice));
    });
    document.querySelector('[data-fw-enable-cancel]')?.addEventListener('click', () => finish(null));
  });
}

async function _fwOfferEnableAfterRemove(context) {
  // Предложение показывается только после успешного удаления (вызывается
  // из onFwRemove после reloadOverview) и только когда ни один firewall
  // не активен. Автоматического включения нет — только явный выбор.
  if (!contextIsCurrent(context)) return;
  const fw = lastOverview?.firewall;
  if (fw?.active === true || _fwActiveCandidates(fw).length > 0) return;
  const names = _fwInstalledInactiveBackends(fw);
  if (!names.length) return;
  let target = null;
  if (names.length === 1) {
    const label = _fwBackendLabel(names[0]);
    const approved = await confirmAction({
      title: `Firewall удалён. Хотите включить ${label}?`,
      message: `${label} установлен и сейчас не активен: трафик не фильтруется.`,
      confirmText: 'Включить',
      cancelText: 'Не включать',
      confirmFirst: true,
    });
    target = approved ? names[0] : null;
  } else {
    target = await _fwChooseEnableAfterRemove(names);
  }
  if (!target || !contextIsCurrent(context)) return;
  await _fwEnableRequest(target, context);
}

async function onFwList() {
  const context = captureContext();
  if (busy || !context) return;
  const { serverId } = context;
  setBusy(true, context);
  try {
    const r = await requestForContext(context,
      `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/rules`,
    );
    const rules = r.data?.rules || [];
    let html;
    if (!rules.length) {
      html = '<p class="qs-list-empty">Открытых правил нет</p>';
    } else {
      html = rules.map((rule, i) => {
        const port = rule.port;
        const proto = rule.protocol || 'tcp';
        const src = rule.source || '';
        const label = `${esc(port)}/${esc(proto)} · ${esc(rule.action || 'allow')}`
          + (src ? ` · ${esc(src)}` : '');
        return `<div class="qs-list-row">
          <span>${label}</span>
          <button type="button" class="secondary qs-fw-rule-close" data-port="${esc(port)}" data-proto="${esc(proto)}" data-source="${esc(src)}" title="Закрыть порт">✕</button>
        </div>`;
      }).join('');
    }
    openQsListModal('Правила firewall', html);
    document.querySelectorAll('.qs-fw-rule-close').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const port = parseInt(btn.dataset.port, 10);
        const protocol = btn.dataset.proto || 'tcp';
        const source = btn.dataset.source || '';
        if (!port) return;
        const rule = `${port}/${protocol}${source ? ` от ${source}` : ''}`;
        const approved = await confirmAction({
          title: `Закрыть порт ${rule}?`,
          confirmText: 'Да',
          cancelText: 'Нет',
          confirmFirst: true,
        });
        if (!approved || !contextIsCurrent(context)) return;
        setBusy(true, context);
        try {
          const acknowledgeConflict = _fwHasConflict();
          if (acknowledgeConflict) {
            const approved = await _confirmFwConflict(
              context,
              `Безопасное закрытие ${rule}`,
            );
            if (!approved) return;
          }
          const cr = await requestForContext(context,
            `/api/servers/${encodeURIComponent(serverId)}/quick-setup/firewall/close`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                port,
                protocol,
                source,
                acknowledge_firewall_conflict: acknowledgeConflict,
              }),
            },
          );
          if (cr.ok) {
            showContextToast(context,cr.message || 'Закрыто', true);
            btn.closest('.qs-list-row')?.remove();
            const body = document.getElementById('qs-list-modal-body');
            if (body && !body.querySelector('.qs-list-row')) {
              body.innerHTML = '<p class="qs-list-empty">Открытых правил нет</p>';
            }
          } else {
            showContextToast(context,cr.message || cr.error || 'Ошибка', false);
          }
        } catch (e) {
          showContextToast(context,e.message || 'Ошибка', false);
        } finally {
          setBusy(false, context);
        }
      });
    });
    if (!r.ok) showContextToast(context,r.message || r.error || 'Нет правил', false);
  } catch (e) {
    showContextToast(context,e.message || 'Ошибка', false);
  } finally {
    setBusy(false, context);
  }
}


async function reloadOverview({ updates = true } = {}, context = requireContext()) {
  if (!contextIsCurrent(context)) throw new QuickSetupContextChanged();
  const q = updates ? '' : '?updates=false';
  const data = await requestForContext(
    context,
    `/api/servers/${encodeURIComponent(context.serverId)}/quick-setup${q}`,
  );
  if (contextIsCurrent(context)) renderOverview(data);
  return data;
}

export async function openQuickSetup(serverId, options = {}) {
  const normalizedId = String(serverId || '').trim();
  if (!normalizedId) {
    const error = new Error('Сервер для настроек не выбран');
    if (options.throwOnError) throw error;
    return false;
  }
  const historyMode = ['push', 'replace', 'none'].includes(options.historyMode)
    ? options.historyMode
    : 'push';

  contextGeneration += 1;
  busy = false;
  busyGeneration = contextGeneration;
  lastOverview = null;
  closeQsListModal();
  setQuickSetupServer(normalizedId);
  setPage('quick-setup');
  showPage('quick-setup');
  syncQuickSetupLocation(normalizedId, historyMode);
  const context = requireContext();

  const body = document.getElementById('qs-body');
  if (body) {
    body.classList.remove('qs-busy');
    body.innerHTML = '<div class="empty">Загрузка…</div>';
  }
  const nameEl = document.getElementById('qs-server-name');
  const ipEl = document.getElementById('qs-server-ip');
  if (nameEl) nameEl.textContent = normalizedId;
  if (ipEl) ipEl.textContent = '—';

  try {
    await reloadOverview({ updates: true }, context);
    return true;
  } catch (error) {
    if (error instanceof QuickSetupContextChanged) return false;
    if (contextIsCurrent(context)) {
      if (body) body.innerHTML = `<div class="empty">${esc(error.message || 'Ошибка загрузки')}</div>`;
      showContextToast(context, error.message || 'Не удалось загрузить настройки', false);
    }
    if (options.throwOnError) throw error;
    return false;
  }
}

async function leaveQuickSetup() {
  const context = captureContext();
  const serverId = context?.serverId || null;
  contextGeneration += 1;
  busy = false;
  lastOverview = null;
  clearQuickSetupServer();
  clearQuickSetupLocation();

  if (serverId && typeof navigation.openServer === 'function') {
    try {
      await navigation.openServer(serverId);
      return;
    } catch (error) {
      toast(error.message || 'Не удалось открыть карточку сервера', false);
    }
  }
  if (typeof navigation.openServers === 'function') {
    navigation.openServers();
    return;
  }
  showPage('servers');
  setPage('servers');
}

export function bindQuickSetupNav(callbacks = {}) {
  navigation = {
    openServer: typeof callbacks.openServer === 'function' ? callbacks.openServer : navigation.openServer,
    openServers: typeof callbacks.openServers === 'function' ? callbacks.openServers : navigation.openServers,
  };
  bindQsListModal();
  bindQsPasswordEyes();
  const back = document.getElementById('btn-back-from-quick-setup');
  if (!back || back.dataset.qsBound === '1') return;
  back.dataset.qsBound = '1';
  back.addEventListener('click', leaveQuickSetup);
}
