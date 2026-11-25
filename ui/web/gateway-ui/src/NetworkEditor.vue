<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import type { Bridge } from './main';
import RouterSettings from './RouterSettings.vue';
import GatewayDialog from './GatewayDialog.vue';
const props = defineProps<{ node: any; bridge: Bridge }>();
const emit = defineEmits<{ changed: [] }>();
const model = ref<any>({ interfaces: [], routes: [], devices: [] });
const loading = ref(false), busy = ref(false), error = ref(''), plan = ref<any>(null);
const settingsMode = ref<'dhcp'|null>(null), dhcpInterface = ref('');
const editor = ref<any>(null), editingRoutes = ref(false), routes = ref<any[]>([]);
const devices = computed(() => [...new Set([...(model.value.devices || []), ...(editor.value?.device ? [editor.value.device] : [])])]);
let alive = true;
const base = () => '/api/gateways/' + encodeURIComponent(props.node.id);
const post = (path: string, data: unknown, method = 'POST') => props.bridge.request(base() + path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
const list = (value: any) => Array.isArray(value) ? value.join(', ') : value || '';
const split = (value: string) => value.split(/[\s,]+/).filter(Boolean);
const nullable = (value: any) => value === '' || value == null ? null : String(value);
function live(iface: any) { return props.node.monitor.interfaces?.find((item: any) => item.name === iface.name) || iface; }
function management(iface: any) { return iface.ipaddr === props.node.host || iface.runtime_addresses?.includes(props.node.host); }
async function load() {
  loading.value = true; error.value = '';
  try { const data = await props.bridge.request(base() + '/network'); if (alive) model.value = data; }
  catch (e: any) { if (alive) error.value = e.message; }
  finally { if (alive) loading.value = false; }
}
async function perform(action: () => Promise<void>) {
  if (busy.value) return; busy.value = true; error.value = '';
  try { await action(); } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
function edit(iface?: any) {
  error.value = '';
  editor.value = { existing: !!iface, name: iface?.name || '', proto: iface?.proto || 'dhcp',
    device: iface?.device || '', ipaddr: iface?.ipaddr || '', netmask: iface?.netmask || '255.255.255.0', gateway: iface?.gateway || '',
    dns: list(iface?.dns), metric: iface?.metric || '', mtu: iface?.mtu || '', defaultroute: iface?.defaultroute !== '0',
    peerdns: iface?.peerdns !== '0', auto: iface?.auto !== '0', username: iface?.username || '', password: '',
    private_key: '', has_password: !!iface?.has_password, has_private_key: !!iface?.has_private_key,
    addresses: list(iface?.addresses), listen_port: iface?.listen_port || '',
    peers: (iface?.peers || []).map((peer: any) => ({ ...peer, allowed_ips: list(peer.allowed_ips), preshared_key: '', route_allowed_ips: peer.route_allowed_ips === '1' })) };
}
async function prepare(action: string, data: any) {
  await perform(async () => {
    const value = await post('/network/plan', { action, data: { ...data, config_hash: model.value.config_hash } });
    editor.value = null; editingRoutes.value = false; plan.value = value;
  });
}
async function reviewInterface() {
  const value = editor.value;
  const settings: any = { proto: value.proto, device: nullable(value.device), dns: split(value.dns),
    metric: nullable(value.metric), mtu: nullable(value.mtu), auto: value.auto ? '1' : '0',
    defaultroute: value.defaultroute ? '1' : '0', peerdns: value.peerdns ? '1' : '0' };
  if (value.proto === 'static') Object.assign(settings, { ipaddr: value.ipaddr, netmask: value.netmask, gateway: nullable(value.gateway) });
  if (value.proto === 'pppoe') { settings.username = value.username; if (value.password) settings.password = value.password; }
  const data: any = { interface: value.name, settings };
  if (value.proto === 'wireguard') {
    settings.addresses = split(value.addresses); settings.listen_port = nullable(value.listen_port);
    if (value.private_key) settings.private_key = value.private_key;
    data.peers = value.peers.map((peer: any) => {
      const item: any = { public_key: peer.public_key, endpoint_host: nullable(peer.endpoint_host), endpoint_port: nullable(peer.endpoint_port),
        allowed_ips: split(peer.allowed_ips || ''), persistent_keepalive: nullable(peer.persistent_keepalive),
        route_allowed_ips: peer.route_allowed_ips ? '1' : '0', description: nullable(peer.description) };
      if (peer.id) item.id = peer.id;
      if (peer.preshared_key) item.preshared_key = peer.preshared_key;
      return item;
    });
  }
  await prepare('edit', data);
}
function editRoutes() {
  error.value = ''; routes.value = model.value.routes.map((item: any) => ({ interface: item.interface || '', target: item.target || '',
    netmask: item.netmask || '255.255.255.255', gateway: item.gateway || '', metric: item.metric || '', table: item.table || '', onlink: item.onlink === '1' }));
  editingRoutes.value = true;
}
function addRoute() { routes.value.push({ interface: model.value.interfaces[0]?.name || '', target: '', netmask: '', gateway: '', metric: '', table: '', onlink: false }); }
async function reviewRoutes() {
  await prepare('routes', { routes: routes.value.map(item => ({ interface: item.interface, target: item.target,
    netmask: nullable(item.netmask), gateway: nullable(item.gateway), metric: nullable(item.metric), table: nullable(item.table), onlink: item.onlink ? '1' : '0' })) });
}
async function apply() {
  await perform(async () => {
    const value = plan.value;
    const result = await post('/router-operations', { plan_token: value.plan_token, confirmed: true });
    plan.value = null;
    props.bridge.task({ taskId: result.task_id, title: value.title + (value.interface ? ' ' + value.interface : ''), cancellable: false,
      onDone: async () => { await load(); emit('changed'); } });
  });
}
function discardPlan() {
  const token = plan.value?.plan_token; plan.value = null; error.value = '';
  if (token) post('/operation-plans/' + encodeURIComponent(token), {}, 'DELETE').catch((e: any) => { error.value = e.message; });
}
onMounted(() => void load());
onUnmounted(() => { alive = false; editor.value = null; });
</script>
<template>
  <section class="gw-network">
    <header class="gw-section-header"><div><h3>Подключения</h3><p class="gw-hint">LAN, WAN и туннели · настройки и состояние</p></div><div class="gw-actions"><button :disabled="loading || busy" @click="load">Обновить</button><button :disabled="loading || busy || !model.config_hash" @click="edit()">Добавить подключение</button></div></header>
    <p v-if="error && !editor && !editingRoutes && !plan" class="gw-error" role="alert">{{ error }}</p>
    <div class="gw-interface-list" :aria-busy="loading"><article v-for="iface in model.interfaces" :key="iface.name" class="gw-interface">
      <div class="gw-interface-name"><h4>{{ iface.name }}</h4><small v-if="management(iface)">Доступ к панели</small></div>
      <div class="gw-interface-info"><span>{{ iface.proto }} · {{ iface.device || iface.runtime_device || '—' }}</span><strong>{{ live(iface).addresses?.join(', ') || iface.runtime_addresses?.join(', ') || iface.ipaddr || list(iface.addresses) || 'Без адреса' }}</strong><small v-if="iface.gateway">Шлюз {{ iface.gateway }}</small></div>
      <div class="gw-interface-state"><span class="gw-status" :class="live(iface).up ? 'good' : 'warn'">{{ live(iface).up ? 'Подключён' : live(iface).pending ? 'Подключается' : 'Отключён' }}</span></div>
      <div class="gw-interface-actions"><button :disabled="busy" @click="edit(iface)">Настроить</button><button :disabled="busy" @click="dhcpInterface = iface.name; settingsMode = 'dhcp'">DHCP</button><button v-if="live(iface).up" :disabled="busy" @click="prepare('reconnect', { interface: iface.name })">Переподключить</button><button :disabled="busy || management(iface) && live(iface).up" :title="management(iface) ? 'Интерфейс доступа изменяется через форму с откатом' : ''" @click="prepare(live(iface).up ? 'down' : 'up', { interface: iface.name })">{{ live(iface).up ? 'Отключить' : 'Подключить' }}</button></div>
    </article></div>
    <p v-if="!model.interfaces.length" class="gw-hint">{{ loading ? 'Получаем состояние сети…' : 'Интерфейсы не найдены.' }}</p>
    <header class="gw-section-header gw-routes-heading"><div><h3>Статические маршруты IPv4</h3><p class="gw-hint">Автоматические маршруты создаются протоколами подключений</p></div><button :disabled="busy || loading || !model.config_hash" @click="editRoutes">Настроить маршруты</button></header>
    <div v-if="model.routes.length" class="gw-table-wrap"><table><thead><tr><th>Сеть</th><th>Через шлюз</th><th>Интерфейс</th><th>Метрика</th></tr></thead><tbody><tr v-for="route in model.routes" :key="route.id"><td>{{ route.target }}<small>{{ route.netmask }}</small></td><td>{{ route.gateway || 'Напрямую' }}</td><td>{{ route.interface }}</td><td>{{ route.metric || '0' }}</td></tr></tbody></table></div><p v-else class="gw-hint">Статические маршруты не заданы.</p>
  </section>
  <RouterSettings v-if="settingsMode" :node="node" :bridge="bridge" :mode="settingsMode" :iface="settingsMode === 'dhcp' ? dhcpInterface : undefined" @close="settingsMode = null" @changed="load(); emit('changed')" />
  <GatewayDialog v-if="editor" :title="editor.existing ? 'Настройка ' + editor.name : 'Новое подключение'" :wide="true" :busy="busy" @close="editor = null; error = ''">
    <form class="gw-form gw-network-form" @submit.prevent="reviewInterface">
      <div class="gw-two"><label>Имя интерфейса<input v-model="editor.name" required pattern="[A-Za-z][A-Za-z0-9_]{0,30}" :readonly="editor.existing" placeholder="wan, lan, wg0" /></label><label>Протокол<select v-model="editor.proto"><option value="dhcp">DHCP-клиент</option><option value="static">Статический адрес</option><option value="pppoe">PPPoE</option><option value="wireguard">WireGuard</option><option value="none">Без протокола</option></select></label></div>
      <label v-if="editor.proto !== 'wireguard'">Сетевое устройство<select v-model="editor.device"><option value="">Автоматически</option><option v-for="device in devices" :key="device" :value="device">{{ device }}</option></select></label>
      <template v-if="editor.proto === 'static'"><div class="gw-two"><label>IPv4-адрес<input v-model="editor.ipaddr" required placeholder="192.168.1.2" /></label><label>Маска подсети<input v-model="editor.netmask" required placeholder="255.255.255.0" /></label></div><label>IPv4-шлюз<input v-model="editor.gateway" placeholder="192.168.1.1" /></label></template>
      <template v-if="editor.proto === 'pppoe'"><label>Логин PPPoE<input v-model="editor.username" required autocomplete="off" /></label><label>Пароль PPPoE<input v-model="editor.password" type="password" autocomplete="off" :required="!editor.has_password" :placeholder="editor.has_password ? 'Пустое поле сохраняет текущий пароль' : ''" /></label></template>
      <template v-if="editor.proto === 'wireguard'"><label>Приватный ключ WireGuard<input v-model="editor.private_key" type="password" autocomplete="off" :required="!editor.has_private_key" :placeholder="editor.has_private_key ? 'Пустое поле сохраняет текущий ключ' : ''" /></label><div class="gw-two"><label>Адреса туннеля<input v-model="editor.addresses" required placeholder="10.10.0.2/24" /></label><label>Порт WireGuard<input v-model="editor.listen_port" type="number" min="1" max="65535" placeholder="Автоматически" /></label></div></template>
      <label>DNS-серверы<input v-model="editor.dns" placeholder="1.1.1.1, 8.8.8.8" /><small>Несколько адресов разделяются пробелами или запятыми</small></label>
      <details class="gw-network-extra"><summary>Дополнительные параметры</summary><div class="gw-two"><label>Метрика маршрута<input v-model="editor.metric" type="number" min="0" placeholder="По умолчанию" /></label><label>MTU<input v-model="editor.mtu" type="number" min="576" max="65535" placeholder="По умолчанию" /></label></div><label class="gw-check"><input v-model="editor.auto" type="checkbox" /> Подключать при загрузке роутера</label><label class="gw-check"><input v-model="editor.defaultroute" type="checkbox" /> Использовать маршрут по умолчанию</label><label v-if="editor.proto === 'dhcp' || editor.proto === 'pppoe'" class="gw-check"><input v-model="editor.peerdns" type="checkbox" /> Получать DNS от подключения</label></details>
      <section v-if="editor.proto === 'wireguard'"><header class="gw-section-header"><h3>Пиры WireGuard</h3><button type="button" @click="editor.peers.push({ public_key: '', allowed_ips: '', endpoint_host: '', endpoint_port: '', persistent_keepalive: '', preshared_key: '', route_allowed_ips: true })">Добавить пир</button></header><article v-for="(peer, index) in editor.peers" :key="peer.id || index" class="gw-peer-form"><div class="gw-section-header"><h4>Пир {{ Number(index) + 1 }}</h4><button type="button" @click="editor.peers.splice(index, 1)">Удалить пир</button></div><label>Публичный ключ<input v-model="peer.public_key" required autocomplete="off" /></label><div class="gw-two"><label>Endpoint<input v-model="peer.endpoint_host" placeholder="vpn.example.org" /></label><label>Порт<input v-model="peer.endpoint_port" type="number" min="1" max="65535" /></label></div><label>Разрешённые сети<input v-model="peer.allowed_ips" required placeholder="0.0.0.0/0, ::/0" /></label><div class="gw-two"><label>Keepalive, секунд<input v-model="peer.persistent_keepalive" type="number" min="0" max="65535" placeholder="25" /></label><label>Общий ключ, необязательно<input v-model="peer.preshared_key" type="password" autocomplete="off" :placeholder="peer.has_preshared_key ? 'Пустое поле сохраняет текущий ключ' : ''" /></label></div><label class="gw-check"><input v-model="peer.route_allowed_ips" type="checkbox" /> Создать маршруты для разрешённых сетей</label></article></section>
      <p class="gw-hint">Перед применением вы увидите изменения. Если панель не подтвердит доступность, роутер восстановит прежнюю сеть.</p><p v-if="error" class="gw-error" role="alert">{{ error }}</p>
      <div class="gw-actions"><button class="gw-primary" :disabled="busy">Проверить изменения</button><button type="button" :disabled="busy" @click="editor = null">Отмена</button><button v-if="editor.existing" type="button" :disabled="busy" @click="prepare('delete', { interface: editor.name })">Удалить интерфейс</button></div>
    </form>
  </GatewayDialog>
  <GatewayDialog v-if="editingRoutes" title="Статические маршруты IPv4" :wide="true" :busy="busy" @close="editingRoutes = false; error = ''">
    <form class="gw-form" @submit.prevent="reviewRoutes"><article v-for="(route, index) in routes" :key="index" class="gw-route-form"><div class="gw-section-header"><h4>Маршрут {{ Number(index) + 1 }}</h4><button type="button" @click="routes.splice(index, 1)">Удалить маршрут</button></div><div class="gw-two"><label>Сеть назначения<input v-model="route.target" required placeholder="10.20.0.0/24" /></label><label>Интерфейс<select v-model="route.interface"><option v-for="iface in model.interfaces" :key="iface.name" :value="iface.name">{{ iface.name }}</option></select></label></div><div class="gw-two"><label>Через шлюз<input v-model="route.gateway" placeholder="Напрямую, если пусто" /></label><label>Маска, если в адресе нет /префикса<input v-model="route.netmask" placeholder="255.255.255.0" /></label></div><div class="gw-two"><label>Метрика<input v-model="route.metric" type="number" min="0" /></label><label>Таблица маршрутов<input v-model="route.table" type="number" min="0" placeholder="Основная" /></label></div><label class="gw-check"><input v-model="route.onlink" type="checkbox" /> Шлюз доступен напрямую</label></article><button type="button" @click="addRoute">Добавить маршрут</button><p v-if="!routes.length" class="gw-hint">Статические маршруты будут отсутствовать. Автоматические маршруты сохраняются.</p><p v-if="error" class="gw-error" role="alert">{{ error }}</p><div class="gw-actions"><button class="gw-primary" :disabled="busy">Проверить изменения</button><button type="button" :disabled="busy" @click="editingRoutes = false">Отмена</button></div></form>
  </GatewayDialog>
  <GatewayDialog v-if="plan" title="Проверка сетевых изменений" :busy="busy" @close="discardPlan">
    <h3>{{ plan.title }} {{ plan.interface }}</h3><ul class="gw-change-list"><li v-for="(change, index) in plan.summary" :key="index">{{ change }}</li></ul>
    <p v-if="plan.address_changes" class="gw-notice">Адрес подключения изменится на <strong>{{ plan.new_api_host }}</strong>. Панель проверит новый адрес и сохранит его после успешного применения.</p>
    <p>Роутер ждёт подтверждения до {{ plan.rollback_seconds }} секунд. Если панель потеряет связь, прежняя конфигурация будет восстановлена автоматически.</p><p v-if="error" class="gw-error" role="alert">{{ error }}</p>
    <div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="apply">Да, применить изменения</button><button :disabled="busy" @click="discardPlan">Отмена</button></div>
  </GatewayDialog>
</template>
<style>
.gw-interface-list{display:grid;gap:12px}.gw-interface{display:grid;grid-template-columns:115px minmax(0,calc(50% - 191px)) 112px minmax(0,1fr);align-items:center;gap:10px;border:1px solid var(--border,#29374b);border-radius:12px;padding:18px}.gw-interface h4{margin:0 0 10px;font-size:17px}.gw-interface-name small,.gw-interface-info small{display:block;margin-top:7px;color:var(--text-muted,#98a8bd);font-size:11px}.gw-interface-info span{display:block;font-size:12px;color:var(--text-muted,#98a8bd)}.gw-interface-info strong{display:block;margin-top:8px;font-size:14px;overflow-wrap:anywhere}.gw-interface-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}.gw-shell .gw-interface-actions button{font-size:12px;padding:9px 11px}.gw-routes-heading{margin-top:32px}.gw-network-extra{border:1px solid var(--border,#29374b);padding:14px;border-radius:10px}.gw-network-extra summary{cursor:pointer;font-size:13px}.gw-network-extra .gw-two{margin-top:18px}.gw-network-form small{color:var(--text-muted,#98a8bd);font-size:11px}.gw-shell .gw-check,.gw-shell .gw-form .gw-check{display:flex;align-items:center;gap:10px;margin-top:10px}.gw-shell .gw-check input{width:auto;min-width:auto;accent-color:#357bc8}.gw-peer-form,.gw-route-form{display:grid;gap:14px;padding:17px;border:1px solid var(--border,#29374b);border-radius:11px;margin:16px 0}.gw-peer-form h4,.gw-route-form h4{margin:0}.gw-change-list{line-height:1.8;overflow-wrap:anywhere}
.gw-interface-state{display:flex;align-items:center;justify-content:center;min-width:0}
@media(max-width:780px){.gw-interface{grid-template-columns:minmax(0,1fr) 112px minmax(0,1fr);gap:8px 10px;padding:10px 0}.gw-interface-name{grid-column:1;grid-row:1}.gw-interface-info{grid-column:1;grid-row:2}.gw-interface-state{grid-column:2;grid-row:1/3;justify-self:center}.gw-interface-actions{grid-column:1/-1;grid-row:3;justify-content:flex-start}.gw-interface h4{margin:0}}
</style>
