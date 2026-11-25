<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { Bridge } from './main';
import type { GatewayMonitor, TrafficCounters, TrafficHistory } from './types/gateway';
type TrafficRole = 'lan' | 'wan';
const roles: TrafficRole[] = ['lan', 'wan'];
const props = defineProps<{ monitor: GatewayMonitor; nodeId?: string; bridge?: Bridge }>();
const span = ref(3600), hovered = ref<Record<TrafficRole,number|null>>({lan:null,wan:null}), history = ref<TrafficHistory[] | null>(null), error = ref('');
let alive = true, generation = 0;
let historyTimer: ReturnType<typeof setInterval> | undefined;
async function load() {
  if (!props.bridge || !props.nodeId) return;
  const current = ++generation;
  try {
    const data = await props.bridge.request('/api/gateways/' + encodeURIComponent(props.nodeId) + '/traffic?seconds=' + span.value);
    if (alive && current === generation && Array.isArray(data.traffic_history)) { history.value = data.traffic_history; error.value = ''; }
  } catch (e: unknown) { if (alive && current === generation) error.value = e instanceof Error ? e.message : String(e); }
}
watch([span, () => props.nodeId], () => { hovered.value = {lan:null,wan:null}; history.value = null; void load(); }, { immediate: true });
onMounted(() => { historyTimer = setInterval(() => { if (!document.hidden) void load(); }, 30000); });
onUnmounted(() => { alive = false; generation++; clearInterval(historyTimer); });
const format = (value: number | null | undefined, rate=false) => {
  if (value==null) return '—';
  const units=['Б','КБ','МБ','ГБ','ТБ']; let n=Number(value),i=0;
  while(n>=1024&&i<units.length-1){n/=1024;i++;}
  return (n<10?n.toFixed(1):Math.round(n))+' '+units[i]+(rate?'/с':'');
};
const points = computed(() => {
  const all=history.value ?? props.monitor.traffic_history ?? []; const last=all.at(-1)?.at||Date.now()/1000;
  return all.filter(item=>item.at>=last-span.value);
});
const end = computed(() => points.value.at(-1)?.at || props.monitor.checked_at || Date.now()/1000);
const start = computed(() => end.value - span.value);
const timeLabel = (at: number) => new Date(at*1000).toLocaleString('ru-RU', span.value >= 43200 ? {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'} : {hour:'2-digit',minute:'2-digit'});
function max(role:TrafficRole){return Math.max(1,...points.value.flatMap(point=>[point[role]?.rx_bps||0,point[role]?.tx_bps||0]));}
function path(role:TrafficRole,key:keyof TrafficCounters){
  let result='',joined=false;
  const peak = max(role);
  points.value.forEach(point=>{
    const value=point[role]?.[key]; if(typeof value!=='number'){joined=false;return;}
    const x=10+(point.at-start.value)/span.value*580,y=132-value/peak*112;
    result+=(joined?' L':' M')+x.toFixed(1)+' '+y.toFixed(1); joined=true;
  });
  return result;
}
function hover(event:PointerEvent,role:TrafficRole){
  if (!points.value.length) { hovered.value[role] = null; return; }
  const box=(event.currentTarget as Element).getBoundingClientRect();
  const at = start.value + Math.max(0, Math.min(1, (event.clientX-box.left)/box.width))*span.value;
  hovered.value[role] = points.value.reduce((best: number, row, i: number) => Math.abs(row.at-at)<Math.abs(points.value[best].at-at) ? i : best, 0);
}
function point(role:TrafficRole){const index=hovered.value[role];return index==null?null:points.value[index];}
</script>
<template>
  <section class="gw-traffic-overview"><header class="gw-section-header"><h3>Трафик сети</h3><div class="gw-traffic-tools"><p class="gw-hint">Скорость и объём данных через LAN и WAN</p><select v-model="span" aria-label="Период графиков"><option :value="3600">Час</option><option :value="21600">6 часов</option><option :value="43200">12 часов</option><option :value="86400">Сутки</option></select></div></header>
    <p v-if="error" class="gw-chart-note">{{ error }}</p>
    <div class="gw-traffic-grid"><article v-for="role in roles" :key="role" class="gw-panel gw-traffic-card">
      <header class="gw-section-header"><h3>{{ role.toUpperCase() }}</h3><span class="gw-status" :class="monitor.traffic?.[role]?.up ? 'good':'warn'">{{ monitor.traffic?.[role]?.up ? 'Подключён':'Отключён' }}</span></header>
      <div class="gw-traffic-speeds"><span class="gw-rx">↓ {{ format(monitor.traffic?.[role]?.rx_bps,true) }}</span><span class="gw-tx">↑ {{ format(monitor.traffic?.[role]?.tx_bps,true) }}</span></div>
      <div class="gw-traffic-plot" @pointermove="hover($event,role)" @pointerleave="hovered[role]=null"><svg viewBox="0 0 600 148" preserveAspectRatio="none" role="img" :aria-label="'Скорость трафика '+role.toUpperCase()"><line v-for="y in [20,76,132]" :key="y" x1="10" :y1="y" x2="590" :y2="y" class="gw-chart-grid"/><path :d="path(role,'rx_bps')" class="gw-chart-rx"/><path :d="path(role,'tx_bps')" class="gw-chart-tx"/></svg><div v-if="points.length<2" class="gw-chart-empty">Накапливаем данные графика</div><div v-if="point(role)" class="gw-chart-tip">{{ new Date(point(role)!.at*1000).toLocaleTimeString() }} · ↓ {{ format(point(role)![role]?.rx_bps,true) }} · ↑ {{ format(point(role)![role]?.tx_bps,true) }}</div></div>
      <div class="gw-traffic-total"><div><span>Получено</span><strong>{{ format(monitor.traffic?.[role]?.rx_bytes) }}</strong></div><div><span>Передано</span><strong>{{ format(monitor.traffic?.[role]?.tx_bytes) }}</strong></div></div>
    </article></div>
    <p class="gw-hint gw-counter-note">Графики: {{ timeLabel(start) }} — {{ timeLabel(end) }}. Объём данных — с последней загрузки / сброса счётчиков</p>
  </section>
</template>
<style>
.gw-traffic-overview{margin-top:28px}.gw-traffic-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.gw-traffic-speeds{display:flex;justify-content:space-between;gap:15px;font-size:18px;font-weight:600}.gw-rx{color:#63a8f5}.gw-tx{color:#62c7a7}.gw-traffic-plot{height:150px;position:relative;margin:16px 0}.gw-traffic-plot svg{display:block;width:100%;height:100%}.gw-chart-grid{stroke:var(--border,#29374b);stroke-dasharray:4 4;stroke-width:1}.gw-chart-rx,.gw-chart-tx{fill:none;stroke-width:2;vector-effect:non-scaling-stroke;stroke-linecap:round;stroke-linejoin:round}.gw-chart-rx{stroke:#63a8f5}.gw-chart-tx{stroke:#62c7a7}.gw-chart-empty{position:absolute;inset:0;display:grid;place-items:center;font-size:12px;color:var(--text-muted,#98a8bd)}.gw-chart-tip{position:absolute;left:10px;bottom:0;font-size:11px;background:var(--bg-base,#101927);padding:7px;border:1px solid var(--border,#29374b);border-radius:6px}.gw-traffic-total{display:grid;grid-template-columns:1fr 1fr;gap:15px;border-top:1px solid var(--border,#29374b);padding-top:16px}.gw-traffic-total span{display:block;font-size:12px;color:var(--text-muted,#98a8bd)}.gw-traffic-total strong{display:block;font-size:21px;margin-top:8px}.gw-counter-note{font-size:11px!important;margin-bottom:0}@media(max-width:800px){.gw-traffic-grid{grid-template-columns:1fr}.gw-traffic-speeds{font-size:16px}}
</style>
<style>
.gw-traffic-tools{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin-left:auto}.gw-shell .gw-traffic-tools p{margin:0;font-size:11px;white-space:nowrap}.gw-shell .gw-traffic-overview>.gw-section-header>h3{flex-shrink:0}.gw-shell .gw-traffic-tools select{margin:0}@media(max-width:600px){.gw-traffic-tools{max-width:calc(100% - 100px);gap:5px;flex-wrap:wrap}.gw-shell .gw-traffic-tools p{font-size:10px;white-space:normal;text-align:right}.gw-shell .gw-traffic-tools select{align-self:auto}}
</style>
<style>
@media(max-width:600px){.gw-shell .gw-detail .gw-traffic-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.gw-shell .gw-detail .gw-traffic-overview>.gw-section-header{flex-direction:row;align-items:center}.gw-shell .gw-detail .gw-traffic-card>.gw-section-header{flex-direction:row;align-items:center;gap:4px}.gw-shell .gw-detail .gw-traffic-card .gw-traffic-speeds{flex-direction:column;gap:2px;font-size:12px}.gw-shell .gw-detail .gw-traffic-card .gw-traffic-total{grid-template-columns:1fr;gap:3px}.gw-shell .gw-detail .gw-traffic-card .gw-traffic-total strong{font-size:12px}.gw-shell .gw-detail .gw-traffic-card{min-width:0}}
</style>
<style>
.gw-shell .gw-traffic-overview{margin-top:12px}.gw-shell .gw-detail .gw-traffic-card .gw-traffic-plot{height:56px}.gw-shell .gw-detail .gw-traffic-card{padding:10px}@media(max-width:600px){.gw-shell .gw-detail .gw-traffic-card .gw-traffic-plot{height:60px}}
</style>
<style>
.gw-shell .gw-traffic-overview>.gw-section-header select{flex:0 0 auto;width:auto;min-width:120px;max-width:50%;height:28px;font-size:12px;padding:3px 25px 3px 7px}.gw-shell .gw-traffic-card{padding:11px}.gw-shell .gw-traffic-card>.gw-section-header{margin-bottom:6px}.gw-shell .gw-traffic-card .gw-status{padding:3px 6px;font-size:10px}.gw-shell .gw-traffic-card .gw-traffic-plot{height:80px;margin:8px 0}.gw-shell .gw-traffic-card .gw-traffic-total{padding-top:7px}.gw-traffic-total>div{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}.gw-shell .gw-traffic-total span,.gw-shell .gw-traffic-total strong{display:inline;margin:0}.gw-shell .gw-traffic-overview>.gw-section-header h3,.gw-shell .gw-traffic-overview>.gw-section-header p{line-height:1.3}@media(max-width:600px){.gw-shell .gw-traffic-card .gw-traffic-plot{height:70px}.gw-shell .gw-traffic-overview>.gw-section-header{gap:8px}.gw-shell .gw-traffic-overview>.gw-section-header select{max-width:none;align-self:flex-end}}
</style>
<style>
.gw-traffic-overview{margin-top:16px}.gw-traffic-overview>.gw-section-header{margin-bottom:10px}.gw-traffic-overview>.gw-section-header h3{font-size:14px}.gw-traffic-overview>.gw-section-header p{font-size:11px;margin-top:3px}.gw-traffic-grid{gap:10px}.gw-traffic-card{padding:13px}.gw-traffic-card>.gw-section-header{margin-bottom:8px}.gw-traffic-card h3{font-size:13px}.gw-traffic-speeds{font-size:14px}.gw-traffic-plot{height:96px;margin:9px 0}.gw-traffic-total{padding-top:9px;gap:10px}.gw-traffic-total span{font-size:10px}.gw-traffic-total strong{font-size:14px;margin-top:3px}.gw-counter-note{margin-top:7px}@media(max-width:600px){.gw-traffic-plot{height:80px}.gw-traffic-speeds{font-size:13px}}
</style>
