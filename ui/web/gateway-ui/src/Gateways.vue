<script setup lang="ts">
import ProjectInfo from './ProjectInfo.vue';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { Bridge } from './main';
import GatewayDialog from './GatewayDialog.vue';
import AdGuardSetup from './AdGuardSetup.vue';
import RouterSettings from './RouterSettings.vue';
import NetworkEditor from './NetworkEditor.vue';
import PackageManager from './PackageManager.vue';
import TrafficCharts from './TrafficCharts.vue';
import WirelessEditor from './WirelessEditor.vue';
import GatewayServices from './components/GatewayServices.vue';
import GatewayHeader from './components/GatewayHeader.vue';
import GatewayBackups from './components/GatewayBackups.vue';
import OperationPlanDialog from './dialogs/OperationPlan.vue';
import IntegrationUpdateDialog from './dialogs/IntegrationUpdate.vue';
import TlsTrustDialog from './dialogs/TlsTrust.vue';
import FirewallRestart from './dialogs/FirewallRestart.vue';
import type { IntegrationUpdatePlan, OperationPlan, ServiceId, ServiceUpdateState, TlsTrustChange, UpdateStage } from './types/gateway';
const adguardOpen = ref(false);
const serviceSettings = ref<'dns'|'firewall'|null>(null);
const firewallRestartNode = ref<any>(null);
const props = defineProps<{ bridge: Bridge; wizard: boolean; initialPlan: any }>();
const locationKey = 'bot4vps_gateway_location';
function readLocation(): { nodeId: string; tab: string } | null {
  if (props.wizard || props.initialPlan?.return_node_id) return null;
  try {
    const value = JSON.parse(sessionStorage.getItem(locationKey) || 'null');
    return value && typeof value.nodeId === 'string' && ['overview', 'network', 'wifi', 'services', 'packages', 'backups', 'logs', 'access'].includes(value.tab) ? value : null;
  } catch (_) { return null; }
}
const restoredLocation = readLocation();
const nodes = ref<any[]>([]), selected = ref<string | null>(props.wizard ? null : props.initialPlan?.return_node_id || restoredLocation?.nodeId || null), busy = ref(false), error = ref('');
const adding = ref(props.wizard), mode = ref('ssh'), plan = ref<any>(props.initialPlan), instructions = ref(false);
const tab = ref(restoredLocation?.tab || 'overview'), log = ref(''), saved = ref('');
watch([selected, tab], ([nodeId, page]) => {
  if (props.wizard) return;
  try {
    if (nodeId) sessionStorage.setItem(locationKey, JSON.stringify({ nodeId, tab: page }));
    else sessionStorage.removeItem(locationKey);
  } catch (_) { /* Navigation still works when browser storage is unavailable. */ }
}, { immediate: true });
const packageQuery = ref('');
const servicesRevision = ref(0);
const deleting = ref<any>(null);
const operation = ref<OperationPlan | null>(null), catalogOpen = ref(false), reserveEnabled = ref(false), reserveKeep = ref<2 | 3>(3);
const operationNodeId = ref<string | null>(null);
const updateStates = ref<Record<string, ServiceUpdateState>>({});
const attachedUpdateTasks = new Set<string>();
const updateKey = (nodeId: string, service: string) => nodeId + ':' + service;
function taskSnapshot(samples:{id:string;service_update_tasks?:{service:ServiceId;task_id:string;stage:UpdateStage}[]}[]) {
  const running = new Set<string>();let refreshServices=false;
  for (const node of samples) for (const pending of node.service_update_tasks || []) {
    running.add(pending.task_id);updateStates.value[updateKey(node.id,pending.service)]={stage:pending.stage,task_id:pending.task_id};
  }
  for (const [key,state] of Object.entries(updateStates.value)) if (state.stage!=='review' && state.task_id && !running.has(state.task_id)) {
    delete updateStates.value[key];if(key.startsWith((active.value?.id||'')+':'))refreshServices=true;
  }
  if(refreshServices && tab.value==='services')servicesRevision.value++;
}
const activeUpdates = computed(() => Object.fromEntries(Object.entries(updateStates.value).filter(([key]) => key.startsWith((active.value?.id || '') + ':')).map(([key, state]) => [key.split(':').at(-1), state])));
const operationFromCatalog = ref(false);
const cachedBundles = ref<any[]>([]), versions = ref<Record<string, string[]>>({ podkop: [], ssclash: [], adguardhome: [] });
const chosen = ref<Record<string, string>>({ podkop: '', ssclash: '', adguardhome: '' });
const form = ref({ name: '', host: '', port: 22, user: 'root', password: '', url: '', username: '', tls_sha256: '' });
const sshForm = ref({ user: 'root', port: 22, auth_type: 'password', password: '', key_path: '' });
const pinChange = ref<TlsTrustChange|null>(null);
const integrationPlan = ref<IntegrationUpdatePlan|null>(null);
const active = computed(() => nodes.value.find(n => n.id === selected.value));
const monitor = computed(() => active.value?.monitor || {});
const wireguard = computed<any[]>(() => Object.values(monitor.value.wireguard || {}));
const query = ref('');
const clientQuery = ref(''), clientPage = ref(1), clientPageSize = 20;
const clients = computed(() => (monitor.value.clients || []).filter((client: any) =>
  [client.hostname, client.ipaddr, client.macaddr].join(' ').toLowerCase().includes(clientQuery.value.toLowerCase())));
const clientPages = computed(() => Math.max(1, Math.ceil(clients.value.length / clientPageSize)));
const pageClients = computed(() => clients.value.slice((clientPage.value - 1) * clientPageSize, clientPage.value * clientPageSize));
watch(clientQuery, () => { clientPage.value = 1; });
watch(clientPages, count => { clientPage.value = Math.min(clientPage.value, count); });
watch(selected, () => { clientQuery.value = ''; clientPage.value = 1; });
function openServiceSettings(service: any) {
  if (service.id === 'firewall') serviceSettings.value = 'firewall';
  else if (service.id === 'dnsmasq') serviceSettings.value = 'dns';
  else if (service.id === 'adguardhome') adguardOpen.value = true;
  else windowOpenService(service);
}

const visibleNodes = computed(() => nodes.value.filter(node => (node.name+' '+node.host+' '+(node.monitor.board?.model||'')).toLowerCase().includes(query.value.toLowerCase())));
const actionNames: Record<string, string> = { start: 'Запуск', stop: 'Остановка', restart: 'Перезапуск', remove: 'Удаление', install: 'Установка' };
const tabs = [{ id: 'overview', name: 'Обзор' }, { id: 'network', name: 'Сеть' }, { id: 'wifi', name: 'Wi-Fi' }, { id: 'services', name: 'Службы' }, { id: 'packages', name: 'Пакеты' }, { id: 'backups', name: 'Резервные копии' }, { id: 'logs', name: 'Журнал' }, { id: 'access', name: 'Доступ' }];
let timer: ReturnType<typeof setInterval> | undefined;
let alive = true;
const post = (url: string, data: unknown, method = 'POST') => props.bridge.request(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
const bytes = (n: number | null | undefined) => n == null ? '—' : n > 1073741824 ? (n / 1073741824).toFixed(1) + ' ГБ' : n > 1048576 ? (n / 1048576).toFixed(1) + ' МБ' : n > 1024 ? (n / 1024).toFixed(1) + ' КБ' : n + ' Б';
const uptime = (seconds: number) => !seconds ? '—' : Math.floor(seconds / 86400) + ' д ' + Math.floor(seconds % 86400 / 3600) + ' ч';
async function openAdguardHome() {
  const node = active.value; if (!node) return;
  const popup = window.open('about:blank', '_blank');
  try { const guide = await props.bridge.request('/api/gateways/'+encodeURIComponent(node.id)+'/adguard');
    const host = node.host.includes(':')?'['+node.host+']':node.host;
    const url = 'http://'+host+':'+(guide.web_port || 3000)+'/';
    if(popup) { popup.opener=null; popup.location.href=url; } else error.value='Браузер заблокировал открытие сервиса';
  } catch(e:unknown) { popup?.close(); error.value=e instanceof Error?e.message:String(e); }
}
function windowOpenService(service: any) { if (service.id === 'ssclash' || service.id === 'adguardhome') window.open(serviceUrl(service), '_blank', 'noopener,noreferrer'); else window.open(new URL('/cgi-bin/luci/admin/services/' + (service.id === 'podkop' ? 'podkop' : ''), active.value.luci_url).href, '_blank', 'noopener,noreferrer'); }
function serviceUrl(service: any) {
  const host = active.value.host.includes(':') ? '[' + active.value.host + ']' : active.value.host;
  const port = Number(service.web_port) || (service.id === 'adguardhome' ? 3000 : 9091);
  return (service.web_https ? 'https://' : 'http://') + host + ':' + port + '/';
}
async function load() {
  try { const data = await props.bridge.request('/api/gateways'); if (data.enabled === false) { props.bridge.navigate('dashboard'); return; } nodes.value = data.gateways || []; if (selected.value && !nodes.value.some(node => node.id === selected.value)) { selected.value = null; tab.value = 'overview'; } taskSnapshot(nodes.value); props.bridge.changed(); }
  catch (e: any) { error.value = e.message; }
}
async function pollMonitor() {
  if (document.hidden || busy.value || adding.value) return;
  try {
    const data = await props.bridge.request('/api/gateways/status');
    if (!alive || !Array.isArray(data.gateways)) return;
    if (data.gateways.length !== nodes.value.length || data.gateways.some((node:{id:string}) => !nodes.value.some(existing=>existing.id===node.id))) { await load(); return; }
    for (const sample of data.gateways) {
      const node = nodes.value.find(node=>node.id===sample.id); node.monitor={...node.monitor,...sample.monitor};
    }
    taskSnapshot(data.gateways);
  } catch(e:unknown) { if(alive)error.value=e instanceof Error?e.message:String(e); }
}
function refocus() { if (!document.hidden && !adding.value && !props.wizard) void load(); }
async function perform(action: () => Promise<void>) {
  if (busy.value) return; busy.value = true; error.value = '';
  try { await action(); } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
async function probe() {
  await perform(async () => {
    if (mode.value === 'api') {
      const result = await post('/api/gateways/manual', { name: form.value.name, url: form.value.url, username: form.value.username,
        password: form.value.password, tls_sha256: form.value.tls_sha256 || null });
      form.value.password = ''; adding.value = false; selected.value = result.id;
      await load(); props.bridge.navigate('gateways'); props.bridge.close?.(); return;
    }
    const result = await post('/api/gateways/probe', { name: form.value.name, host: form.value.host, port: Number(form.value.port),
      user: form.value.user, password: form.value.password, auth_type: 'password' });
    form.value.password = '';
    if (result.node_type !== 'openwrt') throw new Error('На этом устройстве OpenWrt не обнаружен. Добавьте его в разделе «Серверы».');
    plan.value = result;
  });
}
async function decision(value: string) {
  await perform(async () => {
    const result = await post('/api/gateways/bootstrap/' + encodeURIComponent(plan.value.draft_token), { decision: value });
    if (value === 'no') { plan.value = null; adding.value = false; props.bridge.close?.(); return; }
    if (value === 'manual') { instructions.value = true; return; }
    adding.value = false;
    props.bridge.task({ taskId: result.task_id, title: 'Подключение шлюза', cancellable: false,
      onDone: async (task: any) => {
        if (task.status === 'success' || task.status === 'success_warn') { await load(); props.bridge.navigate('gateways'); }
      }, renderResult: (task: any, element: HTMLElement) => {
        const text = document.createElement('p');
        text.textContent = ['success', 'success_warn'].includes(task.status) ? task.status === 'success_warn' ? 'Шлюз подключён и сохранён. Есть предупреждения — проверьте журнал задачи и вкладку «Доступ». Повторное подключение не требуется.' : 'Управление доступом: LuCI → Службы → Bot4VPS. Секрет в журнал не записывается.' : 'Подключение не завершено. Проверьте журнал и настройки роутера.';
        element.replaceChildren(text);
      } });
    props.bridge.close?.();
  });
}
async function selectTab(value: string) {
  serviceSettings.value = null; adguardOpen.value = false; tab.value = value; error.value = ''; saved.value = ''; catalogOpen.value = false;
  if (value === 'logs' && active.value) await perform(async () => { log.value = (await props.bridge.request('/api/gateways/' + active.value.id + '/logs')).output; });
  if (value === 'access' && active.value) {
    form.value.name = active.value.name; form.value.url = active.value.api_url;
    form.value.username = active.value.api_username; form.value.tls_sha256 = active.value.tls_sha256 || ''; form.value.password = '';
    sshForm.value = { user: active.value.ssh_user || 'root', port: active.value.ssh_port || 22, auth_type: active.value.ssh_auth_type || 'password', password: '', key_path: '' };
  }
}
async function servicePlan(service: string, action: string, bundleId?: string, rollbackBundleId?: string, webScope?:'lan'|'wan') {
  const nodeId = active.value?.id;
  if (!nodeId) return;
  await perform(async () => {
    const result = await post('/api/gateways/' + nodeId + '/services/' + service + '/plan', { action, keep_backup: true, bundle_id: bundleId || null, rollback_bundle_id: rollbackBundleId || null, web_scope:webScope || null });
    if (!alive || active.value?.id !== nodeId) { await post('/api/gateways/' + nodeId + '/operation-plans/' + encodeURIComponent(result.plan_token), {}, 'DELETE'); return; }
    operation.value = result; operationNodeId.value = nodeId;
    operationFromCatalog.value = catalogOpen.value;
    catalogOpen.value = false;
  });
}
function trackUpdateTask(nodeId: string, service: ServiceId, taskId: string, stage: UpdateStage) {
  const key = updateKey(nodeId, service);
  updateStates.value[key] = {stage, task_id: taskId};
  if (attachedUpdateTasks.has(taskId)) return;
  attachedUpdateTasks.add(taskId);
  props.bridge.task({taskId, title:stage === 'prepare' ? 'Подготовка обновления '+service : 'Обновление '+service, cancellable:false, onDone:async()=>{
    try {
      const task = await props.bridge.request('/api/tasks/'+encodeURIComponent(taskId));
      if (updateStates.value[key]?.task_id && updateStates.value[key].task_id!==taskId) return;
      if (!task.success) { if (alive && active.value?.id === nodeId) error.value = task.error || 'Обновление завершилось с ошибкой. Проверьте журнал задачи.'; delete updateStates.value[key]; return; }
      if (stage === 'prepare') {
        if (!alive || active.value?.id !== nodeId) { delete updateStates.value[key]; return; }
        const prepared = JSON.parse(task.result.output);
        if (prepared.review_prepared) {
          const plan = await props.bridge.request('/api/gateways/'+nodeId+'/services/'+service+'/update-plan?task_id='+encodeURIComponent(taskId));
          if (updateStates.value[key]?.task_id && updateStates.value[key].task_id!==taskId) return;
          if (!alive || active.value?.id!==nodeId) { delete updateStates.value[key]; return; }
          resumeUpdate(plan);
        }
        else await servicePlan(service, 'update', prepared.bundle_id, prepared.rollback_bundle_id);
        if (operation.value?.action === 'update' && operation.value.service === service && operationNodeId.value === nodeId) updateStates.value[key] = {stage:'review',task_id:operation.value.preparation_task_id || taskId};
        else delete updateStates.value[key];
      } else {
        delete updateStates.value[key];
        if (alive) { await load(); await loadReserve(); servicesRevision.value++; }
      }
    } catch (e: unknown) { if (!updateStates.value[key]?.task_id || updateStates.value[key].task_id===taskId) delete updateStates.value[key]; if (alive && active.value?.id === nodeId) error.value = e instanceof Error ? e.message : String(e); }
  }});
}
function resumeUpdate(plan: OperationPlan) {
  const nodeId = active.value?.id;
  if (!nodeId || plan.node_id && plan.node_id !== nodeId) return;
  operation.value = plan; operationNodeId.value = nodeId;
  updateStates.value[updateKey(nodeId, plan.service)] = {stage:'review',task_id:plan.preparation_task_id || undefined};
}
function detectPendingUpdate(service: ServiceId, state: ServiceUpdateState) {
  if (active.value && state.task_id) updateStates.value[updateKey(active.value.id,service)]={stage:state.stage,task_id:state.task_id};
}
async function updateService(service: ServiceId) {
  const nodeId = active.value?.id;
  if (!nodeId || busy.value || updateStates.value[updateKey(nodeId, service)]) return;
  const key = updateKey(nodeId, service); updateStates.value[key] = {stage:'prepare'};
  await perform(async () => {
    try { const result = await post('/api/gateways/' + nodeId + '/services/' + service + '/update-bundle', {}); trackUpdateTask(nodeId, service, result.task_id, 'prepare'); }
    catch (e) { delete updateStates.value[key]; throw e; }
  });
}
async function finalizeBootstrap() {
  await perform(async()=>{
    const result=await post('/api/gateways/'+active.value.id+'/bootstrap/finalize',{});
    props.bridge.task({taskId:result.task_id,title:'Фиксация подключения',cancellable:false,onDone:load});
  });
}
async function reviewIntegration() {
  const node=active.value;if(!node)return;
  await perform(async()=>{
    const plan=await post('/api/gateways/'+node.id+'/integration/plan',{});
    integrationPlan.value={...plan,nodeId:node.id,name:node.name};
  });
}
function cancelIntegration() {
  const plan=integrationPlan.value;integrationPlan.value=null;
  if(plan)post('/api/gateways/'+plan.nodeId+'/integration/plans/'+encodeURIComponent(plan.plan_token),{},'DELETE').catch((e:unknown)=>{error.value=e instanceof Error?e.message:String(e);});
}
async function applyIntegration() {
  const plan=integrationPlan.value;if(!plan)return;
  await perform(async()=>{
    const result=await post('/api/gateways/'+plan.nodeId+'/integration',{plan_token:plan.plan_token,confirmed:true});
    integrationPlan.value=null;
    props.bridge.task({taskId:result.task_id,title:'Обновление интеграции Bot4VPS',cancellable:false,onDone:async()=>{if(alive){await load();servicesRevision.value++;}}});
  });
}
async function cancelOperation() {
  const token = operation.value?.plan_token;
  const id = operationNodeId.value || active.value?.id;
  if (operation.value?.action === 'update' && id) delete updateStates.value[updateKey(id, operation.value.service)];
  const updating = operation.value?.action==='update';
  operation.value = null; operationNodeId.value = null; error.value = '';
  if (operationFromCatalog.value) catalogOpen.value = true;
  operationFromCatalog.value = false;
  if (token && id) {
    try { await post('/api/gateways/' + encodeURIComponent(id) + '/operation-plans/' + encodeURIComponent(token), {}, 'DELETE'); }
    catch(e:unknown) { error.value=e instanceof Error?e.message:String(e); }
    finally { if(updating)servicesRevision.value++; }
  }
}
async function applyOperation() {
  const planned = operation.value, nodeId = operationNodeId.value || active.value?.id;
  if (!planned || !nodeId) return;
  await perform(async () => {
    const result = await post('/api/gateways/' + nodeId + '/operations', { plan_token: planned.plan_token, confirmed: true });
    const name = planned.service; operation.value = null; operationNodeId.value = null;
    if (planned.action === 'update') { trackUpdateTask(nodeId, name, result.task_id, 'apply'); return; }
    props.bridge.task({ taskId: result.task_id, title: 'Операция: ' + name, cancellable: false,
      onDone: async () => { await load(); await loadReserve(); servicesRevision.value++; },
      onResultClosed: (task: any) => { if (alive && active.value?.id===nodeId && name==='adguardhome' && planned.action==='install' && ['success','success_warn'].includes(task.status)) adguardOpen.value=true; } });
  });
}
async function loadReserve() {
  const data = await props.bridge.request('/api/gateways/reserve');
  reserveEnabled.value = data.settings.enabled; reserveKeep.value = data.settings.keep;
  cachedBundles.value = data.bundles;
}
async function openCatalog() {
  catalogOpen.value = true;
  await perform(async () => {
    await loadReserve();
    await Promise.all(['podkop', 'ssclash', 'adguardhome'].map(async profile => {
      const data = await props.bridge.request('/api/gateways/catalog/' + profile + '?node_id=' + encodeURIComponent(active.value.id));
      versions.value[profile] = data.versions;
      if (!data.versions.includes(chosen.value[profile])) chosen.value[profile] = data.versions[0] || '';
    }));
  });
}
async function saveReserve() {
  await perform(async () => {
    await post('/api/gateways/reserve', { enabled: reserveEnabled.value, keep: Number(reserveKeep.value) }, 'PUT');
    saved.value = reserveEnabled.value ? 'Резервирование включено. Службы на роутере не устанавливаются и не обновляются.' : 'Автоматическое резервирование отключено. Сохранённые резервные версии останутся на панели.';
  });
}
async function prepareBundle(profile: string) {
  await perform(async () => {
    const data = await post('/api/gateways/' + active.value.id + '/bundles', { profile, version: chosen.value[profile] });
    props.bridge.task({ taskId: data.task_id, title: 'Подготовка комплекта ' + profile, cancellable: false,
      onDone: async () => { await loadReserve(); } });
  });
}
function availableBundle(profile: string) {
  return cachedBundles.value.find(b => b.profile === profile && b.version === chosen.value[profile]
    && b.platform.release?.version === monitor.value.board?.release?.version
    && b.platform.release?.target === monitor.value.board?.release?.target && b.complete);
}
async function saveAccess() {
  const nodeId = active.value?.id;
  if (!nodeId) return;
  const previous = active.value.tls_sha256;
  const next = form.value.tls_sha256 || null;
  if (previous && previous !== next) { pinChange.value = {nodeId,previous,next}; return; }
  await submitAccess(false);
}
async function submitAccess(confirmed:boolean) {
  const nodeId = active.value?.id;
  if (!nodeId || confirmed && pinChange.value?.nodeId !== nodeId) return;
  pinChange.value=null;
  await perform(async () => {
    await post('/api/gateways/' + nodeId + '/credentials', { name: form.value.name, url: form.value.url,
      username: form.value.username, password: form.value.password, tls_sha256: form.value.tls_sha256 || null, tls_pin_confirmed:confirmed }, 'PUT');
    form.value.password = ''; saved.value = 'Доступ проверен и сохранён'; await load();
  });
}
async function openConsole() {
  if (!active.value.ssh_configured) { await selectTab('access'); error.value = 'Сначала сохраните SSH-доступ для консоли.'; return; }
  await perform(async () => { await props.bridge.console?.(active.value); });
}
async function saveSSH() {
  await perform(async () => {
    await post('/api/gateways/' + active.value.id + '/ssh', { ...sshForm.value, password: sshForm.value.password || null }, 'PUT');
    sshForm.value.password = ''; saved.value = 'SSH-доступ проверен и сохранён. Пароль зашифрован мастер-ключом панели.'; await load();
  });
}
async function deletionPlan() {
  await perform(async () => { deleting.value = await props.bridge.request('/api/gateways/' + active.value.id + '/deletion-plan'); });
}
async function removeGateway() {
  await perform(async () => {
    const result = await post('/api/gateways/' + active.value.id, { confirmed: true, plan_token: deleting.value.plan_token }, 'DELETE');
    deleting.value = null;
    props.bridge.task({ taskId: result.task_id, title: 'Удаление шлюза и отзыв API', cancellable: false,
      onDone: async () => { selected.value = null; await load(); },
      renderResult: (task: any, element: HTMLElement) => {
        const p = document.createElement('p');
        p.textContent = task.status === 'success' ? 'Удаление шлюза завершено. Результат очистки Bot4VPS — в журнале задачи. Настройки роутера и установленные службы сохранены.' : 'Отзыв доступа или очистка интеграции не завершены. Запись шлюза сохранена; проверьте журнал задачи.';
        element.replaceChildren(p);
      } });
  });
}
onMounted(() => { if (!props.wizard) { void load().then(() => { if (alive && active.value) return selectTab(tab.value); }); timer = setInterval(() => { void pollMonitor(); }, 5000); document.addEventListener('visibilitychange',refocus); } });
onUnmounted(() => { alive = false; if (timer) clearInterval(timer); document.removeEventListener('visibilitychange',refocus); form.value.password = ''; sshForm.value.password = ''; });
</script>

<template>
<div class="gw-shell" :class="{ 'gw-wizard': wizard }">
  <div v-if="error" class="gw-error" role="alert">{{ error }}</div>
  <IntegrationUpdateDialog v-if="integrationPlan" :plan="integrationPlan" :busy="busy" :error="error" @cancel="cancelIntegration" @apply="applyIntegration" />
  <TlsTrustDialog v-if="pinChange" :change="pinChange" :busy="busy" @cancel="pinChange=null" @apply="submitAccess(true)" />
  <template v-if="adding">
    <header class="gw-header"><div><span class="gw-eyebrow">НОВОЕ ПОДКЛЮЧЕНИЕ</span><h2>Добавить шлюз</h2><p>Подключение OpenWrt к вашей инфраструктуре</p></div></header>
    <template v-if="!plan">
      <div class="gw-tabs"><button :class="{ on: mode === 'ssh' }" @click="mode = 'ssh'">Настроить автоматически</button><button :class="{ on: mode === 'api' }" @click="mode = 'api'">API уже настроен</button></div>
      <form class="gw-form" @submit.prevent="probe">
        <label>Имя шлюза<input v-model="form.name" placeholder="Определится по модели роутера" maxlength="100" /></label>
        <template v-if="mode === 'ssh'">
          <label>Адрес роутера<input v-model="form.host" required placeholder="192.168.1.1" /></label>
          <div class="gw-two"><label>SSH-порт<input v-model="form.port" required type="number" min="1" max="65535" /></label><label>Логин<input v-model="form.user" required autocomplete="username" /></label></div>
          <label>SSH-пароль<input v-model="form.password" required type="password" autocomplete="off" /></label>
          <p class="gw-hint">Сначала панель проверит устройство и покажет необходимые изменения. Проверка ничего не устанавливает.</p>
        </template>
        <template v-else>
          <label>HTTPS API<input v-model="form.url" required type="url" placeholder="https://192.168.1.1/ubus" /></label>
          <label>Логин API<input v-model="form.username" required autocomplete="username" /></label>
          <label>Секрет API<input v-model="form.password" required type="password" autocomplete="off" /></label>
          <label>SHA-256 сертификата<input v-model="form.tls_sha256" placeholder="Для собственного сертификата роутера" /></label>
        </template>
        <div class="gw-actions"><button class="gw-primary" :disabled="busy">{{ busy ? 'Проверяем…' : mode === 'ssh' ? 'Проверить роутер' : 'Проверить и подключить' }}</button><button type="button" @click="adding = false; bridge.close?.()" :disabled="busy">Отмена</button></div>
      </form>
    </template>
    <template v-else>
      <div class="gw-detected"><span class="gw-status good">OpenWrt обнаружен</span><h3>{{ plan.board.model }}</h3><p v-if="plan.name">Имя шлюза: {{ plan.name }}</p><p>{{ plan.board.release?.version }} · {{ plan.board.release?.target }}</p></div>
      <div class="gw-panel"><h3>Для подключения панель выполнит</h3>
        <ul><li v-for="pkg in plan.missing_packages" :key="pkg">Установит пакет <strong>{{ pkg }}</strong></li><li v-if="!plan.missing_packages?.length">Необходимые пакеты уже установлены</li><li v-for="change in plan.changes" :key="change">{{ change }}</li><li v-if="plan.https_configuration_required">Включит HTTPS на адресе LAN</li></ul>
        <p class="gw-hint">Прошивка и установленные пакеты не обновляются. Сетевые интерфейсы не перенастраиваются. Ход настройки будет виден в журнале.</p>
      </div>
      <div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="decision('automatic')">Да, настроить автоматически</button><button :disabled="busy" @click="decision('no')">Нет</button><button :disabled="busy" @click="decision('manual')">Настроить самостоятельно</button></div>
      <div v-if="instructions" class="gw-panel"><h3>Самостоятельная настройка</h3><pre v-if="plan.manual.commands.length">{{ plan.manual.commands.join('\n') }}</pre><ol><li v-for="step in plan.manual.steps" :key="step">{{ step }}</li></ol><details><summary>Права мониторинга rpcd</summary><pre>{{ JSON.stringify(plan.manual.acl, null, 2) }}</pre></details><button @click="mode = 'api'; plan = null">Указать данные API</button></div>
    </template>
  </template>
  <template v-else-if="!wizard">
    <template v-if="!active">
    <header class="gw-header"><div><span class="gw-eyebrow">СЕТЬ И МАРШРУТИЗАЦИЯ</span><h1>Шлюзы</h1><p>OpenWrt · {{ nodes.length }} подключений</p></div><button class="gw-primary" @click="bridge.add?.()">Добавить шлюз</button></header>
    <div v-if="!nodes.length" class="gw-empty"><div class="gw-empty-icon">⌘</div><h2>Подключите ваш OpenWrt</h2><p>Обзор сети, состояние служб и операции с понятным журналом.</p><button class="gw-primary" @click="bridge.add?.()">Добавить шлюз</button></div>
    <input v-if="nodes.length>3" v-model="query" class="gw-node-search" type="search" aria-label="Поиск шлюзов" placeholder="Найти шлюз по имени или адресу" />
    <div v-if="visibleNodes.length" class="server-table-wrap gw-server-table-wrap"><table class="server-table gw-server-table"><thead><tr><th>Имя шлюза</th><th>Адрес / OpenWrt</th><th>Статус</th><th>Нагрузка</th><th>Трафик LAN / WAN</th></tr></thead><tbody>
      <tr v-for="node in visibleNodes" :key="node.id" class="server-table-row" tabindex="0" role="button" @click="selected = node.id; tab = 'overview'; error = ''" @keydown.enter.prevent="selected = node.id; tab = 'overview'; error = ''" @keydown.space.prevent="selected = node.id; tab = 'overview'; error = ''">
        <td class="server-name-cell"><div class="gw-server-identity"><span class="gw-router-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20"><rect x="3" y="11" width="18" height="9" rx="2"/><path d="M7 11V5m10 6V5M5 6a10 10 0 0 1 14 0M8 8a6 6 0 0 1 8 0M7 16h.01M11 16h.01"/></svg></span><strong :title="node.name">{{ node.name }}</strong></div></td>
        <td class="server-host-cell"><span>{{ node.host }}</span><small>OpenWrt {{ node.monitor.board?.release?.version || '—' }}</small></td>
        <td><span class="gw-status" :class="node.monitor.ok ? 'good' : 'warn'">{{ node.monitor.ok ? node.monitor.stale ? 'Данные устарели' : 'На связи' : 'Нет доступа к API' }}</span></td>
        <td class="gw-server-sensors"><div class="gw-card-stats"><span>CPU <b>{{ node.monitor.cpu_pct == null ? '—' : node.monitor.cpu_pct + '%' }}</b></span><span>RAM <b>{{ node.monitor.ram_pct == null ? '—' : node.monitor.ram_pct + '%' }}</b></span><span>SoC <b>{{ node.monitor.temperature == null ? '—' : node.monitor.temperature + '°C' }}</b></span></div></td>
        <td class="gw-server-traffic"><span>LAN ↓ {{ bytes(node.monitor.traffic?.lan?.rx_bps) }}/с · ↑ {{ bytes(node.monitor.traffic?.lan?.tx_bps) }}/с</span><span>WAN ↓ {{ bytes(node.monitor.traffic?.wan?.rx_bps) }}/с · ↑ {{ bytes(node.monitor.traffic?.wan?.tx_bps) }}/с</span></td>
      </tr>
    </tbody></table></div>
    </template>
    <section v-if="active" class="gw-detail">
      <button class="gw-back-link" :disabled="busy" @click="selected = null; catalogOpen = false">← Все шлюзы</button>
      <GatewayHeader :node="active" :busy="busy" @console="openConsole" />
      <p v-if="!monitor.ok" class="gw-error">{{ monitor.error }}. {{ monitor.error_code === 'permission' ? 'Проверьте доступ в LuCI или укажите новый секрет во вкладке «Доступ».' : 'Проверьте доступность API роутера. Панель повторит проверку автоматически.' }}</p>
      <p v-if="active.bootstrap_state === 'commit_pending'" class="gw-hint">Шлюз подключён. Фиксация транзакции не подтверждена; завершите её во вкладке «Доступ».</p>
      <div class="gw-tabs"><button v-for="item in tabs" :key="item.id" :class="{ on: tab === item.id }" @click="selectTab(item.id)">{{ item.name }}</button></div>
      <template v-if="tab === 'overview'">      <div class="gw-metrics"><div class="gw-panel"><span>Загрузка CPU</span><strong>{{ monitor.cpu_pct == null ? '—' : monitor.cpu_pct + '%' }}</strong></div><div class="gw-panel"><span>Оперативная память</span><strong>{{ monitor.ram_pct == null ? '—' : monitor.ram_pct + '%' }}</strong><small>{{ bytes(monitor.ram_used) }} / {{ bytes(monitor.ram_total) }}</small></div><div class="gw-panel"><span>Свободное место</span><strong>{{ bytes(monitor.storage_free) }}</strong><small>из {{ bytes(monitor.storage_total) }}</small></div><div class="gw-panel"><span>Время работы</span><strong>{{ uptime(monitor.uptime) }}</strong></div><div class="gw-panel"><span>Температура</span><strong>{{ monitor.temperature == null ? 'Нет датчика' : monitor.temperature + '°C' }}</strong><small v-if="monitor.temperature_support?.virtual">Виртуальная машина</small><button v-if="monitor.temperature_support?.package" @click="packageQuery = monitor.temperature_support.package; selectTab('packages')">Проверить пакет датчика</button></div></div><TrafficCharts :monitor="monitor" :node-id="active.id" :bridge="bridge" /></template>
      <template v-if="tab === 'network'">
        <NetworkEditor :key="active.id"  :node="active" :bridge="bridge" @changed="load" />
        <section class="gw-clients-section">
          <header class="gw-section-header"><div><h3>DHCP-клиенты <small>{{ monitor.clients?.length || 0 }}</small></h3><p class="gw-hint">Аренда DHCP не подтверждает текущую доступность клиента.</p></div><input v-model="clientQuery" type="search" aria-label="Поиск DHCP-клиентов" placeholder="Имя, IP или MAC" /></header>
          <div class="gw-table-wrap"><table><thead><tr><th>Клиент</th><th>IP-адрес</th><th>MAC-адрес</th></tr></thead><tbody><tr v-for="client in pageClients" :key="client.macaddr + ':' + client.ipaddr"><td>{{ client.hostname || 'Без имени' }}</td><td>{{ client.ipaddr }}</td><td>{{ client.macaddr }}</td></tr></tbody></table></div>
          <p v-if="!clients.length" class="gw-hint">{{ clientQuery ? 'Клиенты не найдены' : 'Нет данных об арендах' }}</p>
          <footer v-if="clients.length" class="gw-pagination"><span class="gw-hint">{{ (clientPage - 1) * clientPageSize + 1 }}–{{ Math.min(clientPage * clientPageSize, clients.length) }} из {{ clients.length }}</span><div class="gw-actions"><button :disabled="clientPage === 1" @click="clientPage--">Назад</button><span aria-live="polite">{{ clientPage }} / {{ clientPages }}</span><button :disabled="clientPage >= clientPages" @click="clientPage++">Далее</button></div></footer>
        </section>
      </template>
      <WirelessEditor v-if="tab === 'wifi'" :key="active.id" :node="active" :bridge="bridge" @changed="load" />
      <GatewayServices v-if="tab === 'services'" :key="active.id" :revision="servicesRevision" :node="active" :bridge="bridge" :busy="busy" :updating="activeUpdates" @pending="detectPendingUpdate" @resume="resumeUpdate" @web-access="scope => servicePlan('ssclash', 'web_access', undefined, undefined, scope)" @catalog="openCatalog" @settings="openServiceSettings" @help="adguardOpen=true" @open-adguard="openAdguardHome" @action="servicePlan" @firewall-restart="firewallRestartNode = active" @update="updateService" />
      <GatewayBackups v-if="tab === 'backups'" :key="active.id" :node="active" :bridge="bridge" />
      <FirewallRestart v-if="firewallRestartNode" :node="firewallRestartNode" :bridge="bridge" @close="firewallRestartNode = null" @changed="load" />
      <RouterSettings v-if="serviceSettings" :node="active" :bridge="bridge" :mode="serviceSettings" @close="serviceSettings = null" @changed="load" />
      <GatewayDialog v-if="catalogOpen" title="Установка служб" :wide="true" :compact="true" @close="catalogOpen = false; error = ''">
        <p class="gw-hint">Готовые комплекты с зависимостями для вашего OpenWrt. Скачивание на панель и установка на роутер выполняются отдельно.</p>
        <p v-if="busy" class="gw-hint" role="status">Получаем совместимые версии…</p>
        <p v-if="error" class="gw-error" role="alert">{{ error }}</p>
        <div class="gw-catalog-list">
          <details v-for="profile in ['podkop', 'ssclash', 'adguardhome']" :key="profile" class="gw-catalog-item">
            <summary class="gw-catalog-summary"><div><h3>{{ profile === 'podkop' ? 'Podkop' : profile === 'ssclash' ? 'SSClash-Go' : 'AdGuard Home' }}</h3><ProjectInfo :id="profile" /></div><span v-if="monitor.services?.some((service: any) => service.id === profile)" class="gw-status good">Установлен</span></summary>
            <div class="gw-catalog-body">
              <div class="gw-catalog-controls"><label class="gw-field">Версия<select v-model="chosen[profile]" :disabled="busy"><option v-for="version in versions[profile]" :key="version">{{ version }}</option><option v-if="!versions[profile]?.length" value="">{{ busy ? 'Загружаем версии…' : 'Нет совместимых версий' }}</option></select></label><div class="gw-actions"><button v-if="!availableBundle(profile)" :disabled="busy || !chosen[profile]" @click="prepareBundle(profile)">Скачать комплект на панель</button><button v-else :disabled="busy || monitor.services?.some((service: any) => service.id === profile)" class="gw-primary" @click="servicePlan(profile, 'install', availableBundle(profile).id)">Установить</button><button v-if="profile === 'adguardhome'" @click="catalogOpen = false; adguardOpen = true">Настроить DNS</button></div></div>
              <p class="gw-hint">{{ availableBundle(profile) ? 'Комплект сохранён на панели — установка доступна без GitHub.' : 'Панель скачает файлы и все совместимые зависимости.' }}</p>
              <p v-if="profile === 'adguardhome'" class="gw-hint">Установка не переключает DNS и DHCP.</p>
              <p v-if="monitor.services?.some((service: any) => service.id === profile)" class="gw-hint">Обновление установленной службы доступно в списке сервисов, если найдена новая совместимая версия.</p>
            </div>
          </details>
        </div>
        <section class="gw-reserve-settings"><h3>Резерв версий на панели</h3><label class="gw-check"><input v-model="reserveEnabled" type="checkbox" /> Хранить установочные комплекты резервно</label><p class="gw-hint">Резерв позволяет устанавливать сервисы при недоступном GitHub. Скачивание не запускает установку или обновление на роутере.</p><div class="gw-actions"><select v-model="reserveKeep" aria-label="Количество резервных версий"><option :value="2">2 последние совместимые версии</option><option :value="3">3 последние совместимые версии</option></select><button :disabled="busy" @click="saveReserve">Сохранить настройки</button></div><p v-if="saved" class="gw-hint" role="status">{{ saved }}</p></section>
      </GatewayDialog>
      <AdGuardSetup v-if="adguardOpen" :node="active" :bridge="bridge" @close="adguardOpen = false" @install="adguardOpen = false; openCatalog()" @start="adguardOpen = false; servicePlan('adguardhome', 'start')" />
      <PackageManager v-if="tab === 'packages'" :key="active.id" :node="active" :bridge="bridge" :initial-query="packageQuery" @changed="load" />
      <div v-if="tab === 'logs'" class="gw-panel"><div class="gw-actions"><h3>Системный журнал</h3><button :disabled="busy" @click="selectTab('logs')">Обновить</button></div><pre class="gw-log">{{ log || 'Нет записей' }}</pre></div>
      <section v-if="tab === 'access'" class="gw-access">
        <div v-if="active.managed && active.ssh_configured" class="gw-section-header"><p class="gw-hint">RPC-компоненты и интерфейс LuCI Bot4VPS</p><button :disabled="busy" @click="reviewIntegration">Обновить интеграцию Bot4VPS</button></div>
        <button v-if="active.bootstrap_state === 'commit_pending'" :disabled="busy" @click="finalizeBootstrap">Завершить фиксацию подключения</button>
        <header class="gw-section-header"><div><h3>Доступ к шлюзу</h3><p class="gw-hint">Данные API и SSH для подключения панели</p></div><button class="gw-danger" :disabled="busy" @click="deletionPlan">{{ active.deletion_pending ? 'Повторить отзыв и удаление' : 'Удалить шлюз' }}</button></header>
        <p v-if="saved" class="gw-hint" role="status">{{ saved }}</p>
        <div class="gw-access-columns">
          <form class="gw-form" @submit.prevent="saveAccess"><h4>API OpenWrt</h4><p class="gw-hint">Управление секретом: <a :href="active.access_url" target="_blank" rel="noopener noreferrer">LuCI → Службы → Bot4VPS ↗</a></p><label>Имя шлюза<input v-model="form.name" placeholder="Определится по модели роутера" maxlength="100" /></label><label>Адрес API<input v-model="form.url" required /></label><label>Логин API<input v-model="form.username" required /></label><label>Новый секрет<input v-model="form.password" type="password" required autocomplete="off" /></label><label>SHA-256 сертификата<input v-model="form.tls_sha256" /></label><div class="gw-actions"><button class="gw-primary" :disabled="busy">Проверить и сохранить API</button></div></form>
          <form class="gw-form" @submit.prevent="saveSSH"><h4>SSH для консоли</h4><p class="gw-hint">Пароль хранится зашифрованным мастер-ключом панели.</p><div class="gw-two"><label>SSH-логин<input v-model="sshForm.user" required /></label><label>SSH-порт<input v-model="sshForm.port" type="number" min="1" max="65535" required /></label></div><label>Авторизация<select v-model="sshForm.auth_type"><option value="password">Пароль</option><option value="key">SSH-ключ панели</option></select></label><label v-if="sshForm.auth_type === 'password'">SSH-пароль<input v-model="sshForm.password" type="password" autocomplete="off" :placeholder="active.ssh_configured ? 'Оставьте пустым, чтобы сохранить текущий' : ''" /></label><label v-else>Путь к SSH-ключу<input v-model="sshForm.key_path" placeholder="/opt/bot4vps/keys/имя_ключа" /></label><div class="gw-actions"><button class="gw-primary" :disabled="busy">Проверить и сохранить SSH</button></div></form>
        </div>
      </section>
      <template v-if="tab === 'network'">

        <section v-if="wireguard.length" style="margin-top:24px"><h3>WireGuard</h3><div v-for="iface in wireguard" :key="iface.name" class="gw-panel"><h3>{{ iface.name }}</h3><p v-if="!iface.peers.length" class="gw-hint">Пиры не настроены</p><div v-for="(peer, index) in iface.peers" :key="index" style="margin-top:12px"><span class="gw-status" :class="peer.recent_handshake ? 'good' : 'warn'">{{ peer.recent_handshake ? 'Недавний handshake' : 'Нет недавнего handshake' }}</span><p>{{ peer.endpoint === '(none)' ? 'Endpoint не определён' : peer.endpoint }} · ↓ {{ bytes(peer.rx_bytes) }} · ↑ {{ bytes(peer.tx_bytes) }}</p></div><p class="gw-hint">Handshake показывает обмен ключами за последние 3 минуты. Простаивающий туннель может не обмениваться пакетами.</p></div></section>
      </template>
    </section>
  </template>
  <GatewayDialog v-if="deleting" title="Удаление шлюза" :busy="busy" @close="deleting = null"><h2>Удалить {{ deleting.name }}?</h2><ol><li v-for="step in deleting.steps" :key="step">{{ step }}</li></ol><p>Сохранятся: {{ deleting.preserved.join(', ') }}.</p><p v-if="deleting.manual" class="gw-hint">Для вручную настроенного API может потребоваться отзыв учётной записи в LuCI. Без подтверждения отзыва панель сохранит запись.</p><div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="removeGateway">Да, отозвать доступ и удалить</button><button :disabled="busy" @click="deleting = null">Отмена</button></div></GatewayDialog>
  <OperationPlanDialog v-if="operation" :operation="operation" :busy="busy" :error="error" @apply="applyOperation" @cancel="cancelOperation" />
</div>
</template>

<style>
.gw-shell{--gw-accent:#63a8f5;color:var(--text,#e6edf7);font-family:inherit;max-width:none;width:100%;margin:0}.gw-shell *{box-sizing:border-box}.gw-header{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.gw-header h1,.gw-header h2{margin:5px 0 8px}.gw-header p,.gw-card p,.gw-hint{color:var(--text-muted,#98a8bd);font-size:14px;line-height:1.65}.gw-eyebrow{font-size:10px;letter-spacing:.15em;color:var(--gw-accent);font-weight:700}.gw-shell button,.gw-shell a{font:inherit}.gw-shell button{border:1px solid var(--border,#29374b);background:var(--card,#172131);color:inherit;border-radius:10px;padding:10px 15px;cursor:pointer}.gw-shell button:disabled{opacity:.55;cursor:wait}.gw-shell button:hover:not(:disabled){border-color:var(--gw-accent)}.gw-shell .gw-primary{background:#357bc8;color:#fff;border-color:#357bc8;font-weight:600}.gw-shell a{color:var(--gw-accent)}.gw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}.gw-shell .gw-card{text-align:left;padding:22px;transition:border-color .2s,transform .2s}.gw-card.selected{border-color:var(--gw-accent)}.gw-card h3{font-size:19px;margin:16px 0 8px}.gw-card-stats{display:flex;gap:22px;border-top:1px solid var(--border,#29374b);padding-top:17px;margin-top:18px}.gw-card-stats span{font-size:11px;color:var(--text-muted,#98a8bd)}.gw-card-stats b{display:block;margin-top:5px;font-size:17px;color:var(--text,#e6edf7)}.gw-status{font-size:11px;display:inline-flex;align-items:center;gap:7px;border-radius:20px;padding:5px 10px;background:#8896aa18}.gw-status:before{content:'';width:6px;height:6px;background:currentColor;border-radius:50%}.gw-status.good{color:#69c9ac;background:#42b79415}.gw-status.warn{color:#e4b56c;background:#dba14c15}.gw-panel,.gw-detail{background:var(--card,#172131);border:1px solid var(--border,#29374b);border-radius:14px;padding:22px}.gw-detail{margin-top:25px}.gw-tabs{display:flex;gap:5px;margin:18px 0 24px;padding-bottom:8px;border-bottom:1px solid var(--border,#29374b);overflow:auto}.gw-shell .gw-tabs button{border:0;background:transparent;color:var(--text-muted,#98a8bd);white-space:nowrap}.gw-shell .gw-tabs .on{color:var(--gw-accent);background:#5299e915}.gw-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.gw-metrics span,.gw-metrics small{display:block;font-size:12px;color:var(--text-muted,#98a8bd)}.gw-metrics strong{display:block;font-size:25px;margin:15px 0 8px}.gw-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.gw-form{max-width:620px;display:grid;gap:17px}.gw-form label{font-size:13px;display:grid;gap:8px}.gw-form input{background:var(--field,#101927);color:inherit;border:1px solid var(--border,#29374b);border-radius:8px;padding:11px;font:inherit;width:100%}.gw-two{align-items:start;display:grid;grid-template-columns:1fr 1fr;gap:16px}.gw-error{padding:13px 16px;background:#a93d4420;border:1px solid #a93d4450;color:#f0a2a8;border-radius:10px;margin-bottom:20px;line-height:1.5}.gw-detected{margin:20px 0}.gw-panel h3{margin-top:0}.gw-panel ul,.gw-panel ol{padding-left:20px;line-height:1.9}.gw-panel pre{overflow:auto;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}.gw-log{max-height:450px;overflow:auto;font-family:monospace}.gw-table-wrap{overflow:auto}.gw-table-wrap table{width:100%;border-collapse:collapse;white-space:nowrap}.gw-table-wrap th,.gw-table-wrap td{padding:13px;text-align:left;border-bottom:1px solid var(--border,#29374b);font-size:13px}.gw-table-wrap th{color:var(--text-muted,#98a8bd);font-weight:500}.gw-table-wrap small{display:block;color:var(--text-muted,#98a8bd);margin-top:5px}.gw-empty{text-align:center;border:1px dashed var(--border,#29374b);padding:55px 25px;border-radius:16px}.gw-empty-icon{font-size:38px;color:var(--gw-accent)}.gw-empty p{color:var(--text-muted,#98a8bd);margin-bottom:22px}.gw-wizard{padding:8px}.gw-wizard .gw-panel{margin-bottom:20px}@media(max-width:750px){.gw-metrics{grid-template-columns:1fr 1fr}.gw-header{align-items:flex-start;flex-direction:column}.gw-detail{padding:15px}.gw-two{grid-template-columns:1fr}.gw-grid{grid-template-columns:1fr}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell .gw-server-table-wrap{border:1px solid var(--border,#29374b);background:var(--panel,var(--card));border-radius:14px;overflow:auto}.gw-shell .gw-server-table{width:100%;border-collapse:collapse;font-size:12px}.gw-shell .gw-server-table th{text-align:left;font-size:11px;white-space:nowrap;padding:10px 13px;color:var(--text-muted,#98a8bd);background:var(--field,#101927)}.gw-shell .gw-server-table td{padding:10px 13px;border-top:1px solid var(--border,#29374b)}.gw-shell .gw-server-identity{display:flex;align-items:center;gap:10px;min-width:0}.gw-shell .gw-server-identity strong{display:block;font-size:14px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:26rem}.gw-router-icon{display:grid;place-items:center;width:32px;height:32px;flex:0 0 auto;border:1px solid var(--border,#29374b);border-radius:9px;background:var(--accent-soft,#5299e915);color:var(--accent,#63a8f5)}.gw-router-icon svg{fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.gw-shell .gw-server-table .server-host-cell small{display:block;font-size:10px;color:var(--text-muted,#98a8bd);margin-top:3px}.gw-shell .gw-server-table .gw-status{font-size:10px;white-space:nowrap;padding:4px 7px}.gw-shell .gw-server-table .gw-card-stats{gap:13px;padding:0;margin:0;border:0;white-space:nowrap}.gw-shell .gw-server-table .gw-card-stats span{font-size:10px}.gw-shell .gw-server-table .gw-card-stats b{display:inline;font-size:12px;margin-left:5px}.gw-shell .gw-server-traffic{font-size:10px;color:var(--text-muted,#98a8bd);white-space:nowrap}.gw-shell .gw-server-traffic span{display:block;margin:2px 0}.gw-shell .gw-server-table .server-table-row{cursor:pointer}.gw-shell .gw-server-table .server-table-row:hover{background:var(--field,#101927)}.gw-shell .gw-server-table .server-table-row:focus-visible{outline:2px solid var(--accent,#63a8f5);outline-offset:-2px}@media(max-width:640px){.gw-shell .gw-server-table-wrap{background:transparent;border:0;overflow:visible}.gw-shell .gw-server-table thead{display:none}.gw-shell .gw-server-table tbody{display:block}.gw-shell .gw-server-table .server-table-row{height:auto;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 10px;padding:11px;background:var(--panel,var(--card));border:1px solid var(--border,#29374b);border-radius:12px;margin-bottom:8px}.gw-shell .gw-server-table td{display:block;padding:0;border:0}.gw-shell .gw-server-table .server-name-cell{grid-column:1;grid-row:1;white-space:normal}.gw-shell .gw-server-table .server-host-cell{grid-column:1;grid-row:2;padding-left:42px}.gw-shell .gw-server-table td:nth-child(3){grid-column:2;grid-row:1/3}.gw-shell .gw-server-table .gw-server-sensors{display:block;grid-column:1/3;grid-row:3}.gw-shell .gw-server-table .gw-server-traffic{display:flex;flex-wrap:wrap;gap:3px 12px;grid-column:1/3;grid-row:4}.gw-shell .gw-server-identity strong{font-size:13px;max-width:100%}.gw-shell .gw-server-table .gw-card-stats{justify-content:flex-start}.gw-shell .gw-server-table .gw-status{font-size:9px}.gw-shell .gw-server-identity{gap:8px}.gw-router-icon{width:28px;height:28px}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell .gw-detail>header.gw-header{margin:16px 0}.gw-shell .gw-detail>header.gw-header .gw-eyebrow{font-size:11px;line-height:1.5}.gw-shell .gw-detail>header.gw-header h2{font-size:24px;line-height:1.3;margin:5px 0 7px}.gw-shell .gw-detail>header.gw-header p{font-size:13px;line-height:1.5}@media(max-width:600px){.gw-shell .gw-detail>header.gw-header h2{font-size:23px}.gw-shell .gw-detail>header.gw-header p{font-size:12px}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell div.gw-node-list{gap:0;border-top:1px solid var(--border,#29374b)}.gw-shell .gw-node-list button.gw-card{border:0;border-bottom:1px solid var(--border,#29374b);border-radius:0;background:transparent}.gw-shell .gw-node-list button.gw-card:hover{background:var(--gateway-row-hover,var(--accent-soft,#5299e915))}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell .gw-node-list{gap:7px}.gw-shell .gw-node-list .gw-card{padding:11px 13px;grid-template-columns:minmax(0,1fr) auto auto;grid-template-rows:auto auto;gap:3px 18px;border-radius:9px}.gw-shell .gw-node-list .gw-card h3{grid-column:1;grid-row:1;font-size:15px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.gw-shell .gw-node-list .gw-card>p{grid-column:1;grid-row:2;font-size:11px;line-height:1.3;margin:0}.gw-shell .gw-node-list .gw-card>.gw-status{grid-column:3;grid-row:1;justify-self:end;font-size:10px;padding:3px 6px}.gw-shell .gw-node-list .gw-card-stats{grid-column:2;grid-row:1/3;gap:13px;margin:0;padding:0;align-self:center}.gw-shell .gw-node-list .gw-card-stats span{font-size:10px}.gw-shell .gw-node-list .gw-card-stats b{display:inline;font-size:13px;margin:0 0 0 5px}.gw-shell .gw-node-list .gw-node-traffic{grid-column:3;grid-row:2;margin:0;padding:0;border:0;font-size:10px;gap:10px;justify-content:flex-end}.gw-shell .gw-node-search{font-size:12px;padding:7px 9px;margin-bottom:10px}@media(max-width:750px){.gw-shell .gw-node-list .gw-card{grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;padding:10px}.gw-shell .gw-node-list .gw-card>.gw-status{grid-column:2;grid-row:1}.gw-shell .gw-node-list .gw-card-stats{grid-column:1/3;grid-row:3;gap:16px;justify-content:flex-start}.gw-shell .gw-node-list .gw-node-traffic{grid-column:1/3;grid-row:4;justify-content:flex-start;flex-wrap:wrap;gap:3px 9px}.gw-shell .gw-node-list .gw-card>p{grid-column:1/3}.gw-shell .gw-node-list .gw-card-stats b{font-size:12px}.gw-shell .gw-node-list .gw-card h3{font-size:14px}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell .gw-detail .gw-section-header{gap:10px;margin-bottom:10px}.gw-shell .gw-detail .gw-section-header h3{font-size:14px}.gw-shell .gw-detail .gw-section-header p{font-size:11px;line-height:1.4;margin-top:3px}.gw-shell .gw-detail .gw-network .gw-interface{padding:10px 0;gap:10px}.gw-shell .gw-detail .gw-network .gw-interface h4{font-size:15px;margin-bottom:5px}.gw-shell .gw-detail .gw-interface-info span{font-size:11px;margin-top:3px}.gw-shell .gw-detail .gw-interface-info strong{font-size:12px;margin-top:4px}.gw-shell .gw-detail .gw-interface-actions button{padding:6px 9px;font-size:11px}.gw-shell .gw-detail .gw-routes-heading{margin-top:18px}.gw-shell .gw-detail .gw-clients-section{margin-top:18px}.gw-shell .gw-detail .gw-table-wrap th,.gw-shell .gw-detail .gw-table-wrap td{padding:8px 10px;font-size:12px}.gw-shell .gw-detail .gw-pagination{margin-top:10px}.gw-shell .gw-detail .gw-service-row{padding:10px 0;gap:10px}.gw-shell .gw-detail .gw-service-info h3{font-size:14px;margin-bottom:3px}.gw-shell .gw-detail .gw-service-info p{font-size:11px;line-height:1.4}.gw-shell .gw-detail .gw-service-actions{gap:5px}.gw-shell .gw-detail .gw-service-actions button{font-size:11px;padding:6px 9px}.gw-shell .gw-detail .gw-service-row>.gw-status{min-width:94px;font-size:10px;padding:4px 7px}.gw-shell .gw-detail .gw-radio{padding:13px 0}.gw-shell .gw-detail .gw-radio h3{font-size:14px}.gw-shell .gw-detail .gw-radio .gw-actions button{padding:6px 9px;font-size:11px}.gw-shell .gw-detail .gw-wireless>.gw-section-header>button{padding:6px 9px;font-size:11px}.gw-shell .gw-detail .gw-spectrum-card{padding:11px}.gw-shell .gw-network-form,.gw-shell .gw-wifi-form{font-size:12px}.gw-shell .gw-network-form .gw-rule-fields,.gw-shell .gw-wifi-form .gw-rule-fields{gap:10px}.gw-shell .gw-wifi-form summary{padding:9px 0;font-size:13px}.gw-shell .gw-detail .gw-network-extra{padding:10px}@media(max-width:600px){.gw-shell .gw-detail .gw-service-row{grid-template-columns:minmax(0,1fr) 100px;gap:8px}.gw-shell .gw-detail .gw-section-header{gap:7px}.gw-shell .gw-detail .gw-spectrum-card{padding:9px}.gw-shell .gw-detail .gw-radio>.gw-section-header{gap:7px}.gw-shell .gw-detail .gw-clients-section>.gw-section-header input{width:100%;font-size:12px}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


@media(max-width:600px){.gw-shell .gw-detail>.gw-header{flex-direction:row;align-items:center;gap:8px}.gw-shell .gw-detail>.gw-header>div:first-child{flex:1 1 160px;min-width:0}.gw-shell .gw-detail>.gw-header .gw-actions{flex:0 0 auto}.gw-shell .gw-detail .gw-metrics .gw-panel{padding:8px}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell .gw-detail>.gw-tabs{margin:8px 0 10px;padding-bottom:5px}.gw-shell .gw-detail>.gw-tabs button{font-size:12px;padding:6px 10px}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-shell .gw-back-link{margin-bottom:4px;font-size:12px}.gw-shell .gw-detail>.gw-header{margin:8px 0}.gw-shell .gw-detail>.gw-header .gw-eyebrow{display:block;line-height:14px}.gw-shell .gw-detail>.gw-header h2{font-size:20px;line-height:1.2;margin:3px 0}.gw-shell .gw-detail>.gw-header p{line-height:1.3}.gw-shell .gw-detail .gw-metrics .gw-panel{padding:10px}.gw-shell .gw-detail .gw-metrics span{font-size:10px;line-height:1.5}.gw-shell .gw-detail .gw-metrics strong{font-size:19px;line-height:1.2;margin:4px 0 2px}.gw-shell .gw-detail .gw-metrics small{line-height:1.4}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}


.gw-delete-overlay{position:fixed;inset:0;display:grid;place-items:center;padding:20px;background:#06111ecc;z-index:1100}.gw-delete-dialog{width:min(600px,100%);max-height:90vh;overflow:auto}.gw-delete-dialog p{line-height:1.6}
.gw-detail{padding:16px}.gw-detail>.gw-header{margin:12px 0}.gw-detail>.gw-header h2{font-size:22px;margin:0 0 4px}.gw-detail>.gw-header p{font-size:12px;margin:0}.gw-detail>.gw-tabs{margin:12px 0 16px}.gw-detail .gw-metrics{gap:9px}.gw-detail .gw-metrics .gw-panel{padding:12px;border-radius:10px}.gw-detail .gw-metrics span{font-size:11px}.gw-detail .gw-metrics strong{font-size:20px;margin:7px 0 3px;line-height:1.2}.gw-detail .gw-metrics small{font-size:10px}.gw-detail .gw-metrics button{font-size:11px;padding:5px 7px;margin-top:5px}@media(max-width:600px){.gw-detail{padding:12px}.gw-detail .gw-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.gw-detail .gw-metrics strong{font-size:18px}.gw-detail>.gw-header{gap:10px;flex-wrap:wrap}.gw-detail>.gw-header .gw-actions{font-size:12px}.gw-detail>.gw-header .gw-actions button{padding:7px 9px}}
.gw-shell .gw-back-link{border:0;background:transparent;padding:0;margin:0 0 24px;color:var(--text-muted,#98a8bd);font-size:13px}.gw-shell .gw-detail{margin-top:0}.gw-catalog-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}.gw-catalog-item{padding:20px;border:1px solid var(--border,#29374b);border-radius:12px}.gw-catalog-item h3{margin:0}.gw-catalog-item .gw-section-header{align-items:flex-start;flex-wrap:wrap}.gw-field{display:grid;gap:8px;font-size:13px;margin:18px 0}.gw-field select{width:100%}.gw-reserve-settings{border-top:1px solid var(--border,#29374b);padding-top:22px;margin-top:25px}.gw-clients-section{margin-top:32px}.gw-shell .gw-tabs{flex-wrap:wrap;overflow:visible}.gw-shell .gw-tabs button{font-size:13px;padding:9px 12px}.gw-form select{width:100%}
@media(max-width:700px){.gw-catalog-grid{grid-template-columns:1fr}.gw-catalog-item{padding:17px}.gw-detail .gw-header{gap:12px}}
.gw-shell select{background:var(--field,#101927);color:inherit;border:1px solid var(--border,#29374b);border-radius:7px;padding:8px;font:inherit}.gw-shell hr{border:0;border-top:1px solid var(--border,#29374b);margin:22px 0}
.gw-shell .gw-service-title{display:block;border:0;background:transparent;padding:0;margin:0 0 16px;font-size:18px;font-weight:650;text-align:left}.gw-shell select{padding-right:32px;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'%3E%3Cpath fill='none' stroke='%2398a8bd' stroke-width='1.5' d='m4 6 4 4 4-4'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center}.gw-service-link{margin:12px 0 16px;font-size:13px}
.gw-node-list{display:grid;gap:14px}.gw-node-list .gw-card{display:grid;grid-template-columns:minmax(220px,1fr) auto;gap:5px 25px;align-items:center}.gw-node-list .gw-card h3{margin:8px 0;font-size:21px}.gw-node-list .gw-card p{margin:0}.gw-node-list .gw-status{justify-self:start}.gw-node-list .gw-card-stats{grid-column:2;grid-row:1/4;border:0;margin:0;padding:0;gap:35px}.gw-node-traffic{grid-column:1/-1;display:flex;gap:25px;color:var(--text-muted,#98a8bd);font-size:12px;border-top:1px solid var(--border,#29374b);padding-top:14px;margin-top:12px}.gw-node-search{width:100%;margin:0 0 20px}.gw-metrics{grid-template-columns:repeat(5,minmax(0,1fr))}
@media(max-width:900px){.gw-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:650px){.gw-node-list .gw-card{display:block}.gw-node-list .gw-card-stats{margin-top:18px;gap:28px}.gw-node-traffic{flex-direction:column;gap:8px}.gw-metrics{grid-template-columns:1fr 1fr}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}

.gw-shell .gw-server-table-wrap{background:var(--panel)}.gw-shell .gw-server-table tbody tr{background:var(--field)}
</style>

<style>
.content:has(#page-gateways.on){max-width:none}#gateway-root{width:100%}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}

.gw-shell .gw-server-table-wrap{background:var(--panel)}.gw-shell .gw-server-table tbody tr{background:var(--field)}
</style>

<style>
.gw-shell{--gw-accent:var(--accent,#63a8f5)}
.gw-shell button:hover:not(:disabled){background:var(--card-hover,#202d40);color:var(--text,#e6edf7);box-shadow:none;transform:none;filter:none}
.gw-shell button:focus-visible{outline:2px solid var(--accent,#63a8f5);outline-offset:2px}
.gw-shell .gw-card:hover,.gw-shell .gw-card:focus-visible{background:var(--gateway-row-hover,var(--accent-soft,#5299e915));border-color:var(--border-hover,#46607f);color:var(--text,#e6edf7);box-shadow:none;transform:none}
.gw-shell .gw-tabs button:hover{background:var(--field,#101927);color:var(--text,#e6edf7)}
.gw-shell .gw-primary:hover:not(:disabled){background:var(--accent-hover,#2d6aae);color:#fff;border-color:var(--accent-hover,#2d6aae)}
.gw-shell .gw-danger{color:var(--err,#ef7f85);background:transparent}
.gw-shell .gw-danger:hover:not(:disabled){color:var(--err,#ef7f85);background:var(--err-bg,#a93d4415);border-color:var(--err,#ef7f85)}
.gw-shell .gw-detail{background:transparent;border:0;padding:0;border-radius:0}
.gw-service-list{border-top:1px solid var(--border,#29374b)}
.gw-service-row{display:grid;grid-template-columns:minmax(0,1fr) 130px minmax(0,1fr);align-items:center;gap:16px;padding:16px 0;border-bottom:1px solid var(--border,#29374b)}
.gw-service-row>.gw-status{justify-self:center;justify-content:center;min-width:112px}.gw-service-info{min-width:0}.gw-service-info h3{font-size:15px;margin:0 0 6px}.gw-service-info p{font-size:12px;color:var(--text-muted,#98a8bd);margin:0;line-height:1.5}
.gw-service-actions{display:flex;gap:7px;justify-content:flex-end;flex-wrap:wrap}.gw-shell .gw-service-actions button{font-size:12px;padding:8px 11px}
.gw-catalog-list{display:grid}.gw-catalog-list .gw-catalog-item{border:0;border-bottom:1px solid var(--border,#29374b);border-radius:0;padding:20px 0}.gw-catalog-list .gw-catalog-item:first-child{padding-top:0}
.gw-access-columns{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:16px}.gw-access h4{margin:0;font-size:15px}.gw-access .gw-form{align-content:start;gap:.65rem}.gw-access .gw-form label{gap:.25rem;margin:0;font-size:.78rem;font-weight:400}.gw-access .gw-two{gap:.8rem}.gw-shell .gw-access input,.gw-shell .gw-access select{height:var(--control-height,32px);min-height:var(--control-height,32px);padding:.35rem .65rem;font-size:var(--control-font-size,13px);border-radius:var(--control-radius,8px)}.gw-shell .gw-access select{padding-right:2rem}.gw-shell .gw-access button{min-height:var(--control-height,32px);padding:.35rem .65rem;font-size:var(--control-font-size,13px)}.gw-access .gw-hint{font-size:.78rem;line-height:1.45}.gw-access .gw-form p{margin:0}.gw-access-columns>.gw-form+.gw-form{border-left:1px solid var(--border,#29374b);padding-left:20px}
.gw-clients-section h3 small{font-size:12px;color:var(--text-muted,#98a8bd);font-weight:400;margin-left:8px}
.gw-shell .gw-interface{border:0;border-bottom:1px solid var(--border,#29374b);border-radius:0;padding:18px 0}.gw-interface-list{gap:0;border-top:1px solid var(--border,#29374b)}
@media(max-width:650px){.gw-service-row{grid-template-columns:minmax(0,1fr) 112px;gap:12px}.gw-service-actions{grid-column:1/-1;justify-content:flex-start}}
@media(max-width:750px){.gw-access-columns{grid-template-columns:1fr;gap:20px}.gw-access-columns>.gw-form+.gw-form{border-left:0;border-top:1px solid var(--border,#29374b);padding:16px 0 0}}
.gw-shell .gw-catalog-list .gw-catalog-item{padding:0}.gw-catalog-summary{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer;list-style:none}.gw-catalog-summary::-webkit-details-marker{display:none}.gw-catalog-summary::before{content:'›';font-size:20px;color:var(--text-muted,#98a8bd);transition:transform .15s}.gw-catalog-item[open]>.gw-catalog-summary::before{transform:rotate(90deg)}.gw-catalog-summary>div{flex:1;min-width:0}.gw-catalog-summary h3{font-size:14px;font-weight:500}.gw-shell .gw-catalog-summary p{font-size:11px;line-height:1.4;margin:3px 0 0}.gw-catalog-summary:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}.gw-catalog-body{padding:0 0 10px 20px}.gw-catalog-controls{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.gw-catalog-controls .gw-field{gap:4px;font-size:11px;margin:0;min-width:140px}.gw-catalog-controls select{padding:6px 9px;font-size:12px}.gw-shell .gw-catalog-controls .gw-actions{margin:0;gap:5px}.gw-shell .gw-catalog-controls button{padding:6px 9px;font-size:11px}.gw-shell .gw-catalog-body p{font-size:11px;line-height:1.4;margin:6px 0 0}.gw-shell .gw-reserve-settings{padding-top:12px;margin-top:14px}.gw-reserve-settings h3{font-size:14px;margin:0 0 8px}.gw-shell .gw-reserve-settings p,.gw-shell .gw-reserve-settings label{font-size:11px;line-height:1.4}.gw-shell .gw-reserve-settings .gw-actions{margin-top:9px;gap:6px}.gw-shell .gw-reserve-settings button,.gw-shell .gw-reserve-settings select{padding:6px 9px;font-size:11px}@media(max-width:600px){.gw-catalog-controls .gw-field{flex:1}.gw-catalog-summary h3{font-size:13px}}

.gw-shell .gw-server-table-wrap{background:var(--panel)}.gw-shell .gw-server-table tbody tr{background:var(--field)}
</style>
