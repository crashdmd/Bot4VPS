<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import type { Bridge } from '../main';
import ProjectInfo from '../ProjectInfo.vue';
import GatewayDialog from '../GatewayDialog.vue';
import type { Gateway, OperationPlan, Service, ServiceId, ServiceUpdate, ServiceUpdateState } from '../types/gateway';
const props = defineProps<{ node: Gateway; bridge: Bridge; busy: boolean; revision?:number; updating?: Partial<Record<ServiceId,ServiceUpdateState>> }>();
const emit = defineEmits<{ catalog: []; firewallRestart: []; settings: [service:Service]; help: []; openAdguard: []; action: [id:ServiceId,action:string]; update: [id:ServiceId]; pending:[id:ServiceId,state:ServiceUpdateState]; resume:[plan:OperationPlan]; webAccess:[scope:'lan'|'wan'] }>();
const updates = ref<Partial<Record<ServiceId,ServiceUpdate>>>({}), loading = ref(false), error = ref(''), checkedAt = ref<number|null>(null);
const services = computed(()=>props.node.monitor.services || []);
const descriptions: Record<ServiceId,string> = {dnsmasq:'Локальный DNS и DHCP',firewall:'Защита роутера и правила трафика',podkop:'Выборочная маршрутизация через sing-box',ssclash:'Clash / Mihomo и правила маршрутизации',adguardhome:'Фильтрация DNS и блокировка рекламы'};
const versionForm = ref<{id:ServiceId; name:string; fingerprint:string; version:string}|null>(null), versionBusy = ref(false), versionError = ref('');
function openVersion(service:Service) {
  const fingerprint=updates.value[service.id]?.fingerprint;
  if(!fingerprint)return;
  versionError.value='';versionForm.value={id:service.id,name:service.name,fingerprint,version:''};
}
async function saveVersion() {
  const form=versionForm.value,nodeId=props.node.id;
  if(!form||versionBusy.value)return;
  versionBusy.value=true;versionError.value='';
  try {
    await props.bridge.request('/api/gateways/'+encodeURIComponent(nodeId)+'/services/'+form.id+'/version', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:form.version,fingerprint:form.fingerprint,confirmed:true})});
    versionForm.value=null;await loadUpdates();
  } catch(e:unknown){versionError.value=e instanceof Error?e.message:String(e);}
  finally{versionBusy.value=false;}
}
let generation=0;
onUnmounted(()=>{generation++;});
function pending(id:ServiceId):ServiceUpdateState|undefined { return props.updating?.[id] || (updates.value[id]?.stage ? {stage:updates.value[id]!.stage!,task_id:updates.value[id]?.task_id || undefined} : undefined); }
function updateLabel(id:ServiceId) { return pending(id)?.stage==='prepare' ? 'Подготовка…' : pending(id)?.stage==='apply' ? 'Обновление…' : pending(id)?.stage==='review' ? updates.value[id]?.plan ? 'Продолжить обновление' : 'Ожидает подтверждения' : 'Обновить до '+updates.value[id]?.latest; }
function updateDisabled(id:ServiceId) { return props.busy || loading.value || !!error.value || !!pending(id) && !(pending(id)?.stage==='review' && updates.value[id]?.plan); }
function update(id:ServiceId) { const plan=updates.value[id]?.plan; if(pending(id)?.stage==='review' && plan)emit('resume',plan);else emit('update',id); }
function updateStatus(id:ServiceId) {
  if (['dnsmasq','firewall'].includes(id)) return '';
  if (loading.value) return 'Проверяю обновления…';
  if (error.value) return 'Не удалось проверить обновления';
  const state = updates.value[id];
  if (state?.available) return 'Есть обновление до ' + state.latest;
  if (state?.status === 'current_cached') return 'Актуальная среди сохранённых версий';
  if (state?.warning) return 'Проверка не завершена';
  if (state?.status === 'newer') return 'Установленная версия новее доступного релиза';
  if (state?.current && state.latest) return 'Актуальная версия';
  return 'Обновления не проверены';
}
async function loadUpdates(background=false) {
  const run=++generation;if(!background)loading.value=true;error.value='';
  try {const data=await props.bridge.request('/api/gateways/'+encodeURIComponent(props.node.id)+'/service-updates');if(run===generation){updates.value=data.services || {};checkedAt.value=data.checked_at || Math.floor(Date.now()/1000);for(const [id,state] of Object.entries(updates.value))if(state.task_id&&state.stage)emit('pending',id as ServiceId,{stage:state.stage,task_id:state.task_id});}}
  catch(e:unknown){if(run===generation)error.value=e instanceof Error?e.message:String(e);}
  finally{if(run===generation)loading.value=false;}
}
watch(()=>props.revision,()=>{void loadUpdates(true);});
watch(()=>props.node.id,()=>{updates.value={};checkedAt.value=null;versionForm.value=null;void loadUpdates();},{immediate:true});
</script>
<template>
  <header class="gw-section-header"><div><h3>Сервисы из GitHub</h3><p class="gw-hint">Podkop, SSClash-Go и AdGuard Home · версии и резервные комплекты</p></div><div class="gw-actions"><button :disabled="busy||loading" @click="loadUpdates()">{{ loading ? 'Проверяю…' : 'Проверить обновления' }}</button><button class="gw-primary" :disabled="busy" @click="emit('catalog')">Установить сервис</button></div></header>
  <p class="gw-hint" aria-live="polite">{{ loading ? 'Проверяю установленные версии и совместимые официальные релизы…' : error ? 'Проверка не завершена.' : checkedAt ? 'Проверено в ' + new Date(checkedAt * 1000).toLocaleTimeString('ru-RU') : 'Версии ещё не проверены.' }}</p>
  <p v-if="error" class="gw-hint" role="status">{{ error }}</p>
  <div class="gw-service-columns" aria-hidden="true"><span>Сервис</span><span>Версия</span><span>Статус</span><span>Действия</span></div>
  <div class="gw-service-list"><article v-for="service in services" :key="service.id" class="gw-service-row"><div class="gw-service-info"><h3>{{ service.name }} </h3><ProjectInfo v-if="['podkop','ssclash','adguardhome'].includes(service.id)" :id="service.id" compact :help="service.id==='adguardhome'" @help="emit('help')" /><p v-else>{{ descriptions[service.id] }}</p><p v-if="updates[service.id]?.warning" class="gw-hint gw-version-warning" role="status" :title="updates[service.id]?.warning || undefined">{{ updates[service.id]?.warning }}</p></div><div class="gw-service-versions" :title="(updates[service.id]?.installed_version || updates[service.id]?.current || service.version || '—') + (updates[service.id]?.available ? ' → ' + updates[service.id]?.latest : '')"><span>{{ updates[service.id]?.installed_version || updates[service.id]?.current || service.version || '—' }}</span><span v-if="updates[service.id]?.available" class="gw-next-version">→ {{ updates[service.id]?.latest }}</span></div><div class="gw-service-state"><span class="gw-status" :class="service.running?'good':'warn'">{{ service.running?'Работает':'Остановлена' }}</span><span v-if="updateStatus(service.id)" class="gw-status" :class="loading || error || updates[service.id]?.warning || updates[service.id]?.available ? 'warn' : 'good'">{{ updateStatus(service.id) }}</span></div><div class="gw-service-actions"><button v-if="['ssclash','adguardhome'].includes(service.id) && !updates[service.id]?.current && updates[service.id]?.fingerprint" :disabled="busy||loading||versionBusy" @click="openVersion(service)">Указать установленную версию</button><button :disabled="busy" @click="service.id==='adguardhome'?emit('openAdguard'):emit('settings',service)">{{ service.id==='adguardhome'?'Открыть AdGuard Home':'Настроить'+(['podkop','ssclash'].includes(service.id)?' ↗':'') }}</button><template v-if="node.monitor.capabilities?.controls?.available"><button v-if="updates[service.id]?.available || pending(service.id)" class="gw-update-button" :disabled="updateDisabled(service.id)" :title="'Обновить до '+updates[service.id]?.latest" @click="update(service.id)">{{ updateLabel(service.id) }}</button><button v-if="service.id==='ssclash' && service.managed" :disabled="busy || !!pending(service.id)" @click="emit('webAccess',service.web_scope==='wan'?'lan':'wan')">{{ service.web_scope==='wan'?'Только LAN':'Доступ из WAN' }}</button><button v-if="service.running || service.id==='firewall'" :disabled="busy || !!pending(service.id)" @click="service.id==='firewall' ? emit('firewallRestart') : emit('action',service.id,'restart')">Перезапустить</button><button v-if="!['dnsmasq','firewall'].includes(service.id)" :disabled="busy || !!pending(service.id)" @click="emit('action',service.id,service.running?'stop':'start')">{{ service.running?'Остановить':'Запустить' }}</button><button v-if="['podkop','ssclash'].includes(service.id)||service.id==='adguardhome'&&service.managed" class="gw-danger" :disabled="busy || !!pending(service.id)" @click="emit('action',service.id,'remove')">Удалить</button></template></div></article><p v-if="!services.length" class="gw-hint">Установленные сервисы пока не определены.</p></div>
  <GatewayDialog v-if="versionForm" :title="'Установленная версия · '+versionForm.name" @close="!versionBusy && (versionForm=null)">
    <p class="gw-hint">Укажите версию, которая сейчас показана в интерфейсе сервиса. Сохраняется только запись о версии; сервис и настройки не меняются.</p>
    <label class="gw-version-field">Установленная версия<input v-model.trim="versionForm.version" placeholder="Например, 7.7.4" inputmode="decimal" :disabled="versionBusy" /></label>
    <p v-if="versionError" class="gw-error" role="alert">{{ versionError }}</p>
    <div class="gw-actions"><button class="gw-primary" :disabled="versionBusy||!/^v?[0-9]+[.][0-9]+[.][0-9]+$/.test(versionForm.version)" @click="saveVersion">{{versionBusy?'Сохраняю…':'Подтвердить версию'}}</button><button :disabled="versionBusy" @click="versionForm=null">Отмена</button></div>
  </GatewayDialog>
</template>
<style>
.gw-shell .gw-detail .gw-service-row,.gw-shell .gw-service-columns{grid-template-columns:minmax(150px,1fr) 230px 260px minmax(160px,1fr);gap:12px}
.gw-service-columns{display:grid;padding:8px 0;color:var(--text-muted);font-size:10px}.gw-service-columns>span:last-child{text-align:right}
.gw-service-versions{display:flex;flex-wrap:nowrap;white-space:nowrap;align-items:center;gap:3px 7px;font-size:12px;font-variant-numeric:tabular-nums}.gw-next-version{color:var(--warn);flex-shrink:0}.gw-service-versions>span{flex-shrink:0;white-space:nowrap}
.gw-service-state{display:flex;align-items:center;gap:5px;flex-wrap:nowrap}.gw-service-state .gw-status{font-size:10px;padding:4px 6px;white-space:nowrap}
.gw-shell .gw-service-info .gw-version-warning{margin-top:4px;max-width:250px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:10px}
.gw-shell .gw-service-actions .gw-update-button{border-color:var(--warn,#e4b56c);color:var(--warn,#e4b56c);background:transparent}
.gw-version-field{display:grid;gap:7px;margin:14px 0;font-size:12px;color:var(--text-muted)}.gw-version-field input{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--text);font:inherit}
@media(max-width:1000px){.gw-shell .gw-detail .gw-service-row,.gw-shell .gw-service-columns{grid-template-columns:minmax(150px,1fr) 230px 250px}.gw-service-actions{grid-column:1/-1;justify-content:flex-start}.gw-service-columns>span:last-child{display:none}}
@media(max-width:780px){.gw-shell .gw-detail .gw-service-list .gw-service-row{grid-template-columns:minmax(0,1fr) 230px;gap:6px 10px}.gw-service-columns{display:none}.gw-service-state{grid-column:1/-1}.gw-service-actions{grid-column:1/-1}.gw-shell .gw-service-info .gw-version-warning{max-width:none}}
</style>

<style>.gw-service-versions{align-self:start;padding-top:3px}</style>
