<script setup lang="ts">
import { onMounted, ref } from 'vue';
import type { Bridge } from './main';
import GatewayDialog from './GatewayDialog.vue';
const props = defineProps<{ node: any; bridge: Bridge; mode: 'dhcp' | 'dns' | 'firewall'; iface?: string }>();
const emit = defineEmits<{ close: []; changed: [] }>();
const model = ref<any>(null), form = ref<any>({}), plan = ref<any>(null), busy = ref(false), error = ref('');
const firewallTab = ref('general');
const deleted = ref<string[]>([]), changedRules = ref<Set<string>>(new Set());
const deletedRedirects = ref<string[]>([]), changedRedirects = ref<Set<string>>(new Set());
const redirectKeys = ['id', 'name', 'src', 'dest', 'src_ip', 'dest_ip', 'proto', 'src_dport', 'dest_port', 'enabled', 'reflection'];
const title = { dhcp: 'DHCP-сервер', dns: 'DNS роутера', firewall: 'Настройки firewall' };
const split = (v: any) => String(v || '').split(/[\s,]+/).filter(Boolean);
const list = (v: any) => Array.isArray(v) ? v.join(', ') : v || '';
const base = () => '/api/gateways/' + encodeURIComponent(props.node.id);
const post = (path: string, body: any, method = 'POST') => props.bridge.request(base() + path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
function dnsInstance(id: string) {
  const v = model.value.dns.find((x: any) => x.id === id) || {};
  form.value = { ...v, port: v.port ?? '53', server: list(v.server), cachesize: v.cachesize ?? '150', domain: v.domain || '', local: v.local || '', noresolv: v.noresolv === '1', rebind_protection: v.rebind_protection !== '0', domainneeded: v.domainneeded === '1', boguspriv: v.boguspriv !== '0' };
}
async function load() {
  busy.value = true;
  try {
    model.value = await props.bridge.request(base() + '/network');
    if (props.mode === 'dns') dnsInstance(model.value.dns[0]?.id);
    else if (props.mode === 'dhcp') {
      const v = model.value.dhcp.find((x: any) => x.interface === props.iface);
      form.value = { ignore: !v || v.ignore === '1', start: v?.start ?? '100', limit: v?.limit ?? '150', leasetime: v?.leasetime || '12h', dns: list(v?.dns) };
    } else {
      const f = model.value.firewall;
      form.value = { redirectsSupported: Array.isArray(f.redirects), redirects: (f.redirects || []).filter((x: any) => !x.target || x.target === 'DNAT').map((x: any) => ({ ...x })), defaults: { input: 'REJECT', output: 'ACCEPT', forward: 'REJECT', ...f.defaults }, zones: f.zones.map((x: any) => ({ ...x })), rules: f.rules.map((x: any) => ({ ...x, editable: !x.target || ['ACCEPT', 'REJECT', 'DROP'].includes(x.target) })) };
    }
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
function removeRule(index: number) { const r = form.value.rules[index]; if (r.id) deleted.value.push(r.id); form.value.rules.splice(index, 1); }
function touch(rule: any) { if (rule.id) changedRules.value.add(rule.id); }
function newRule() { firewallTab.value = 'rules'; form.value.rules.push({ name: '', src: 'lan', dest: '', proto: 'tcp', dest_port: '', target: 'ACCEPT', enabled: '1', editable: true }); }
function newRedirect() { firewallTab.value = 'redirects'; form.value.redirects.push({ name: '', src: 'wan', dest: 'lan', proto: ['tcp', 'udp'], src_dport: '', dest_ip: '', dest_port: '', enabled: '1', reflection: '1' }); }
function removeRedirect(index: number) { const row = form.value.redirects[index]; if (row.id) deletedRedirects.value.push(row.id); form.value.redirects.splice(index, 1); }
function touchRedirect(row: any) { if (row.id) changedRedirects.value.add(row.id); }
function allowed(values: any, names: string[]) { const result: any = {}; for (const name of names) if (values[name] !== undefined) result[name] = values[name] === '' ? null : values[name]; return result; }
async function review(action = props.mode as string) {
  busy.value = true; error.value = '';
  try {
    const data: any = { config_hash: model.value.settings_hash };
    const f = form.value;
    if (action === 'dhcp') Object.assign(data, { interface: props.iface, settings: { ignore: f.ignore ? '1' : '0', start: String(f.start), limit: String(f.limit), leasetime: f.leasetime, dns: split(f.dns) } });
    if (action === 'dns') Object.assign(data, { section: f.id, settings: { port: String(f.port), server: split(f.server), cachesize: String(f.cachesize), domain: f.domain || null, local: f.local || null, noresolv: f.noresolv ? '1' : '0', rebind_protection: f.rebind_protection ? '1' : '0', domainneeded: f.domainneeded ? '1' : '0', boguspriv: f.boguspriv ? '1' : '0' } });
    if (action === 'firewall') Object.assign(data, { settings: allowed(f.defaults, ['input', 'output', 'forward', 'synflood_protect']), zones: f.zones.map((x: any) => allowed(x, ['id', 'input', 'output', 'forward', 'masq', 'mtu_fix'])), rules: f.rules.filter((x: any) => !x.id || changedRules.value.has(x.id)).map((x: any) => allowed(x, ['id', 'name', 'src', 'dest', 'src_ip', 'dest_ip', 'proto', 'dest_port', 'target', 'enabled'])), deleted_rules: deleted.value });
    if (action === 'firewall' && f.redirectsSupported) Object.assign(data, { redirects: f.redirects.filter((x: any) => !x.id || changedRedirects.value.has(x.id)).map((x: any) => allowed(x, redirectKeys)), deleted_redirects: deletedRedirects.value });
    plan.value = await post('/network/plan', { action, data });
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
async function apply() {
  busy.value = true;
  try {
    const value = plan.value;
    const task = await post('/router-operations', { plan_token: value.plan_token, confirmed: true });
    plan.value = null; emit('close');
    props.bridge.task({ taskId: task.task_id, title: value.title, cancellable: false, onDone: async () => emit('changed') });
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
function discard() {
  const token = plan.value?.plan_token; plan.value = null; error.value = '';
  if (token) post('/operation-plans/' + encodeURIComponent(token), {}, 'DELETE').catch((e: any) => { error.value = e.message; });
}
onMounted(() => void load());
</script>
<template>
  <GatewayDialog :title="plan ? 'Проверка изменений' : title[mode] + (iface ? ' · ' + iface : '')" :wide="true" :busy="busy" @close="plan ? discard() : emit('close')">
    <p v-if="error" class="gw-error" role="alert">{{ error }}</p>
    <template v-if="plan">
      <ul class="gw-change-list"><li v-for="(change, i) in plan.summary" :key="i">{{ change }}</li></ul>
      <section v-if="plan.warnings?.length" class="gw-notice"><h3>Последствия изменений</h3><ul><li v-for="(warning, i) in plan.warnings" :key="i">{{ warning }}</li></ul></section>
      <p class="gw-notice">Если панель не подтвердит результат в течение {{ plan.rollback_seconds }} секунд, роутер вернёт прежнюю конфигурацию. Изменения, сделанные параллельно в LuCI, не будут перезаписаны.</p>
      <div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="apply">Да, применить</button><button :disabled="busy" @click="discard">Назад</button></div>
    </template>
    <form v-else-if="model" class="gw-form" @submit.prevent="review()">
      <template v-if="mode === 'dhcp'">
        <label class="gw-check"><input v-model="form.ignore" type="checkbox" /> Выключить DHCP-сервер на {{ iface }}</label>
        <p v-if="!form.ignore" class="gw-notice">В одном сегменте должен работать один DHCP-сервер. При наличии основного роутера оставьте DHCP здесь выключенным.</p>
        <div class="gw-two"><label>Начальный адрес (смещение в подсети)<input v-model="form.start" type="number" min="0" :disabled="form.ignore" required /></label><label>Количество адресов<input v-model="form.limit" type="number" min="1" :disabled="form.ignore" required /></label></div>
        <label>Время аренды<input v-model="form.leasetime" placeholder="12h" /></label>
        <label>DNS для DHCP-клиентов (IPv4)<input v-model="form.dns" placeholder="Пусто — адрес роутера" /><small>Меняется только DHCP option 6. Другие опции, статические аренды и настройки IPv6 сохраняются. Клиенты получат изменение при обновлении аренды.</small></label>
      </template>
      <template v-if="mode === 'dns'">
        <p class="gw-hint">DNS подключения WAN задаётся в его настройках. Здесь — локальный DNS-сервис dnsmasq и серверы, на которые он отправляет запросы.</p>
        <label v-if="model.dns.length > 1">Экземпляр dnsmasq<select :value="form.id" @change="dnsInstance(($event.target as HTMLSelectElement).value)"><option v-for="s in model.dns" :key="s.id" :value="s.id">{{ s.id }}</option></select></label>
        <p v-if="!model.dns.length" class="gw-notice">dnsmasq не настроен. Сначала установите или настройте его в LuCI.</p>
        <template v-else>
          <div class="gw-two"><label>Порт DNS<input v-model="form.port" type="number" min="0" max="65535" required /><small>53 — обычный DNS; 0 отключает только DNS.</small></label><label>Размер кэша<input v-model="form.cachesize" type="number" min="0" required /></label></div>
          <label>Внешние DNS-серверы<textarea v-model="form.server" rows="3" placeholder="1.1.1.1&#10;127.0.0.1#5353&#10;/example.org/192.168.1.2" /><small>По одному серверу на строку; адрес#порт, /домен/адрес#порт.</small></label>
          <label class="gw-check"><input v-model="form.noresolv" type="checkbox" /> Использовать только указанные upstream (не получать DNS от WAN)</label>
          <div class="gw-two"><label>Локальный домен<input v-model="form.domain" placeholder="lan" /></label><label>Локальная зона<input v-model="form.local" placeholder="/lan/" /></label></div>
          <label class="gw-check"><input v-model="form.rebind_protection" type="checkbox" /> Защита DNS rebinding</label><label class="gw-check"><input v-model="form.domainneeded" type="checkbox" /> Не отправлять имена без домена</label><label class="gw-check"><input v-model="form.boguspriv" type="checkbox" /> Не отправлять обратные запросы частных адресов</label>
          <p v-if="form.nftset || form.ipset" class="gw-notice">dnsmasq использует наборы для маршрутизации. При переходе на AdGuard Home сохраните путь запросов через dnsmasq для нужных доменов.</p>
        </template>
      </template>
      <template v-if="mode === 'firewall'">
        <p class="gw-hint">Основные политики, зоны, правила трафика и перенаправления портов. Расширенные параметры и специальные правила NAT сохраняются.</p>
        <nav class="gw-tabs" aria-label="Разделы firewall"><button type="button" :class="{ on: firewallTab === 'general' }" @click="firewallTab = 'general'">Общие настройки</button><button type="button" :class="{ on: firewallTab === 'zones' }" @click="firewallTab = 'zones'">Зоны ({{ form.zones.length }})</button><button type="button" :class="{ on: firewallTab === 'rules' }" @click="firewallTab = 'rules'">Правила трафика ({{ form.rules.length }})</button><button type="button" :class="{ on: firewallTab === 'redirects' }" @click="firewallTab = 'redirects'">Перенаправление портов ({{ form.redirects.length }})</button></nav>
        <section v-show="firewallTab === 'general'"><h3>Политики по умолчанию</h3><p class="gw-hint">Применяются к трафику, для которого не задано отдельное правило.</p><div class="gw-policy-grid"><label v-for="key in ['input','output','forward']" :key="key">{{ { input: 'Входящие', output: 'Исходящие', forward: 'Пересылка' }[key as 'input'|'output'|'forward'] }}<select v-model="form.defaults[key]"><option>ACCEPT</option><option>REJECT</option><option>DROP</option></select></label></div>
        </section><section v-show="firewallTab === 'zones'"><h3>Зоны</h3><p class="gw-hint">Политики для групп сетевых интерфейсов. Правила отдельных соединений находятся на вкладке «Правила трафика».</p>
        <article v-for="zone in form.zones" :key="zone.id" class="gw-settings-row"><h4>{{ zone.name }} · {{ list(zone.network) }}</h4><div class="gw-policy-grid"><label v-for="key in ['input','output','forward']" :key="key">{{ { input: 'Входящие', output: 'Исходящие', forward: 'Пересылка' }[key as 'input'|'output'|'forward'] }}<select v-model="zone[key]"><option>ACCEPT</option><option>REJECT</option><option>DROP</option></select></label></div><div class="gw-two"><label>NAT (маскарадинг)<select v-model="zone.masq"><option :value="undefined">По умолчанию</option><option value="1">Включён</option><option value="0">Выключен</option></select></label><label>Коррекция MSS<select v-model="zone.mtu_fix"><option :value="undefined">По умолчанию</option><option value="1">Включён</option><option value="0">Выключен</option></select></label></div></article>
        </section><section v-show="firewallTab === 'rules'"><header class="gw-section-header"><h3>Правила трафика</h3><button type="button" @click="newRule">Добавить правило</button></header>
        <details v-for="(rule, i) in form.rules" :key="rule.id || i" :open="!rule.id" class="gw-settings-rule" @input="touch(rule)" @change="touch(rule)"><summary><strong>{{ rule.name || rule.id || 'Новое правило' }}</strong><span>{{ rule.src || 'Роутер' }} → {{ rule.dest || 'Роутер' }} · {{ list(rule.proto) || 'all' }} {{ rule.dest_port || '' }} · {{ rule.target || 'ACCEPT' }}</span><small>{{ rule.enabled === '0' ? 'Выключено' : 'Включено' }}</small></summary><div class="gw-rule-fields"><button type="button" class="gw-danger" @click="removeRule(Number(i))">Удалить правило</button><p v-if="!rule.editable" class="gw-hint">{{ rule.target }} · Расширенное правило. Редактирование доступно в LuCI.</p><template v-else><label>Название<input v-model="rule.name" /></label><div class="gw-two"><label>Исходная зона<select v-model="rule.src"><option value="">Сам роутер</option><option value="*">Любая</option><option v-for="z in form.zones" :key="z.id" :value="z.name">{{ z.name }}</option></select></label><label>Зона назначения<select v-model="rule.dest"><option value="">Сам роутер</option><option value="*">Любая</option><option v-for="z in form.zones" :key="z.id" :value="z.name">{{ z.name }}</option></select></label></div><div class="gw-two"><label>Протокол<select v-model="rule.proto"><option v-if="Array.isArray(rule.proto)" :value="rule.proto">{{ list(rule.proto) }}</option><option>tcp</option><option>udp</option><option>icmp</option><option>icmpv6</option><option>all</option></select></label><label>Порт назначения<input v-model="rule.dest_port" placeholder="443 или 1000-2000" /></label></div><div class="gw-two"><label>Действие<select v-model="rule.target"><option>ACCEPT</option><option>REJECT</option><option>DROP</option></select></label><label>Состояние<select v-model="rule.enabled"><option :value="undefined">Включено по умолчанию</option><option value="1">Включено</option><option value="0">Выключено</option></select></label></div></template></div></details><p v-if="!form.rules.length" class="gw-hint">Правила трафика не настроены.</p></section>
        <section v-show="firewallTab === 'redirects'">
          <header class="gw-section-header"><h3>Перенаправление портов</h3><button type="button" :disabled="!form.redirectsSupported" @click="newRedirect">Добавить перенаправление</button></header>
          <p v-if="!form.redirectsSupported" class="gw-notice">Обновите интеграцию Bot4VPS на шлюзе для управления перенаправлениями портов.</p>
          <p v-else class="gw-hint">Внешний порт → IP устройства и внутренний порт. Изменения применяются после проверки плана.</p>
          <details v-for="(rule, i) in form.redirects" :key="rule.id || i" :open="!rule.id" class="gw-settings-rule" @input="touchRedirect(rule)" @change="touchRedirect(rule)">
            <summary><strong>{{ rule.name || rule.id || 'Новое перенаправление' }}</strong><span>{{ rule.src }}:{{ rule.src_dport }} → {{ rule.dest_ip || 'Роутер' }}:{{ rule.dest_port || rule.src_dport }} · {{ list(rule.proto) || 'TCP и UDP' }}</span><small>{{ rule.enabled === '0' ? 'Выключено' : 'Включено' }}</small></summary>
            <div class="gw-rule-fields"><button type="button" class="gw-danger" @click="removeRedirect(Number(i))">Удалить перенаправление</button>
              <label>Название<input v-model="rule.name" /></label>
              <div class="gw-two"><label>Исходная зона<select v-model="rule.src"><option v-for="z in form.zones" :key="z.id" :value="z.name">{{ z.name }}</option></select></label><label>Зона назначения<select v-model="rule.dest"><option v-for="z in form.zones" :key="z.id" :value="z.name">{{ z.name }}</option></select></label></div>
              <div class="gw-two"><label>Внешний порт<input v-model="rule.src_dport" placeholder="443 или 1000-2000" /></label><label>IP устройства назначения<input v-model="rule.dest_ip" placeholder="192.168.1.10" /></label></div>
              <div class="gw-two"><label>Внутренний порт<input v-model="rule.dest_port" placeholder="Пусто — внешний порт" /></label><label>Протокол<select v-model="rule.proto"><option :value="['tcp','udp']">TCP и UDP</option><option value="tcp">TCP</option><option value="udp">UDP</option></select></label></div>
              <label>Разрешённый IP источника<input v-model="rule.src_ip" placeholder="Пусто — любой адрес; можно CIDR" /></label>
              <div class="gw-two"><label>Состояние<select v-model="rule.enabled"><option :value="undefined">Включено по умолчанию</option><option value="1">Включено</option><option value="0">Выключено</option></select></label><label>NAT loopback<select v-model="rule.reflection"><option :value="undefined">По умолчанию</option><option value="1">Включён</option><option value="0">Выключен</option></select><small>Доступ из LAN через внешний адрес.</small></label></div>
            </div>
          </details><p v-if="form.redirectsSupported && !form.redirects.length" class="gw-hint">Перенаправления не настроены.</p>
        </section>
      </template>
      <div class="gw-actions"><button class="gw-primary" :disabled="busy || mode === 'dns' && !model.dns.length">Проверить изменения</button><button type="button" :disabled="busy" @click="emit('close')">Закрыть</button></div>
    </form><p v-else-if="busy">Получаем конфигурацию…</p>
  </GatewayDialog>
</template>
<style>
.gw-policy-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.gw-settings-row{display:grid;gap:14px;border:1px solid var(--border,#29374b);padding:16px;border-radius:12px}.gw-settings-row h4{margin:0}.gw-form small{color:var(--text-muted,#98a8bd);font-size:12px;line-height:1.6}.gw-form .gw-check{display:flex;align-items:center;gap:10px}.gw-form .gw-check input{width:auto}
@media(max-width:600px){.gw-policy-grid{grid-template-columns:1fr}}
</style>

<style>
.gw-settings-row{border:0;border-bottom:1px solid var(--border,#29374b);border-radius:0;padding:18px 0}
.gw-settings-rule{border-bottom:1px solid var(--border,#29374b)}.gw-settings-rule summary{display:grid;grid-template-columns:minmax(140px,1fr) minmax(150px,2fr) auto;gap:12px;padding:16px 0;cursor:pointer;font-size:13px;list-style:none}.gw-settings-rule summary strong:before{content:'▸';margin-right:8px;color:var(--text-muted,#98a8bd)}.gw-settings-rule[open] summary strong:before{content:'▾'}.gw-settings-rule summary span,.gw-settings-rule summary small{color:var(--text-muted,#98a8bd)}.gw-rule-fields{display:grid;gap:14px;padding:0 0 20px}.gw-rule-fields>button{justify-self:end}
@media(max-width:650px){.gw-settings-rule summary{grid-template-columns:1fr auto}.gw-settings-rule summary span{grid-column:1/-1;grid-row:2}}
</style>
