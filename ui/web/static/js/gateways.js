import { j } from './api.js';
import { toast, confirmAction } from './ui.js';

let bridge = null, pageUnmount = null, modalUnmount = null, viewModule = null;
let pageGeneration = 0, terminalGatewayId = null;
export function openGatewayFromDashboard(id) {
  window.b4vNav?.('gateways', { nodeId: id });
}
async function view() {
  if (!document.getElementById('gateway-vue-css')) {
    const css = document.createElement('link'); css.id = 'gateway-vue-css'; css.rel = 'stylesheet';
    css.href = '/static/gateways/gateways.css?v=20261127-session-devices'; document.head.append(css);
  }
  viewModule ||= import('/static/gateways/gateways.js?v=20261127-session-devices');
  return viewModule;
}
export async function refreshGatewayNav() {
  try {
    const data = await j('/api/gateways');
    const button = document.querySelector('[data-page="gateways"]');
    if (button) button.hidden = data.enabled === false || data.enabled == null && !(data.gateways?.length);
  } catch (_) { /* Login gate may not have opened yet. */ }
}
export async function openGatewayPage({ restore = false, nodeId = null } = {}) {
  const generation = ++pageGeneration;
  try {
    const module = await view();
    if (generation !== pageGeneration) return;
    pageUnmount?.();
    pageUnmount = module.mount(document.getElementById('gateway-root'), bridge, false, {
      restore_location: restore, return_node_id: nodeId,
    });
  } catch (error) { toast(error.message, false); }
}
export function stopGatewayPage() { pageGeneration++; pageUnmount?.(); pageUnmount = null; }
export async function openGatewayWizard(plan = null) {
  if (!bridge) return;
  try {
    const module = await view();
    modalUnmount?.(); document.getElementById('gateway-add-modal')?.remove();
    const modal = document.createElement('div'); modal.id = 'gateway-add-modal'; modal.className = 'modal-bg open';
    const root = document.createElement('div'); root.className = 'modal';
    root.style.cssText = 'width:min(760px,100%);max-height:92vh;overflow:auto';
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', 'Добавить шлюз');
    modal.append(root); document.body.append(modal);
    modalUnmount = module.mount(root, { ...bridge, close: () => { modalUnmount?.(); modalUnmount = null; modal.remove(); } }, true, plan);
  } catch (error) { toast(error.message, false); }
}
export function bindGateways(options) {
  window.addEventListener('bot4vps:openwrt-feature-changed', refreshGatewayNav);
  bridge = { request: j, task: options.task, navigate: options.navigate, changed: refreshGatewayNav, add: openGatewayWizard,
    console: async node => {
      terminalGatewayId = node.id;
      const terminal = await import('./terminal.js?v=20260905-glassblue-v2');
      options.navigate('terminal');
      requestAnimationFrame(() => terminal.openGatewayTerminal(node));
    } };
  document.getElementById('btn-back-from-terminal')?.addEventListener('click', event => {
    if (event.currentTarget.dataset.nodeKind !== 'gateways') return;
    event.preventDefault(); event.stopImmediatePropagation();
    options.navigate('gateways', { nodeId: terminalGatewayId });
    terminalGatewayId = null;
  }, { capture: true });
  document.getElementById('header-add-node')?.addEventListener('click', () => {
    const menu = document.getElementById('header-add-node-menu'); menu.hidden = !menu.hidden;
  });
  document.getElementById('header-add-gateway')?.addEventListener('click', () => {
    document.getElementById('header-add-node-menu').hidden = true; openGatewayWizard();
  });
  document.getElementById('header-add-server')?.addEventListener('click', () => {
    document.getElementById('header-add-node-menu').hidden = true; options.server();
  });
  window.addEventListener('bot4vps:gateway-detected', async event => {
    if (await confirmAction({ title: 'Обнаружен OpenWrt', message: 'Это шлюз OpenWrt. Перейти в отдельный мастер добавления шлюза?', confirmFirst: true })) {
      openGatewayWizard(event.detail);
    } else {
      j('/api/gateways/bootstrap/' + encodeURIComponent(event.detail.draft_token), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision: 'no' }) }).catch(() => {});
    }
  });
}
