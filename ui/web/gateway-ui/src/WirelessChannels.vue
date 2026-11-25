<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { channelFrequency, numeric, segmentsForNetwork } from './wirelessScan';
const props = defineProps<{ data: any; radio: any }>();
const selected = ref<string | null>(null), hovered = ref<string | null>(null), channel = ref<any>(null);
const highlighted = computed(() => hovered.value || selected.value);
const media = window.matchMedia('(max-width:600px)'), narrow = ref(media.matches);
const resize = () => { narrow.value = media.matches; };
onMounted(() => media.addEventListener('change', resize));
onUnmounted(() => media.removeEventListener('change', resize));
const W = computed(() => narrow.value ? 520 : 900), LEFT = 48, RIGHT = computed(() => W.value - 48), TOP = 26, BASE = 244;
const number = (value: any) => typeof value === 'number' && Number.isFinite(value);
function color(value: string) {
  let hash = 0;
  for (const char of value) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `hsl(${(Math.imul(hash, 0x9e3779b1) >>> 0) % 360} 65% 56%)`;
}
const peers = computed(() => (props.data.networks || []).filter((row: any) => number(row.frequency) && number(row.signal))
  .map((row: any, i: number) => ({ ...row, id: (row.bssid || i) + ':' + row.frequency, color: color(row.bssid || row.ssid || String(i)), segments: segmentsForNetwork(row) }))
  .sort((a: any, b: any) => a.signal - b.signal));
watch(() => props.data.networks, () => {
  if (selected.value && !peers.value.some((peer: any) => peer.id === selected.value)) selected.value = null;
  hovered.value = null; channel.value = null;
});
const channels = computed(() => {
  const rows = new Map<number, any>();
  const add = (frequency: number, channel: any) => {
    if (!rows.has(frequency)) rows.set(frequency, { frequency, channel, count: 0, busy_pct: null, noise: null });
    return rows.get(frequency);
  };
  for (const entry of props.data.frequencies || []) {
    const mhz = numeric(entry.mhz || entry.frequency);
    if (mhz != null) add(mhz, entry.channel);
  }
  for (const peer of props.data.networks || []) if (number(peer.frequency)) add(peer.frequency, peer.channel).count++;
  for (const survey of props.data.survey || []) {
    const mhz = numeric(survey.frequency);
    if (mhz == null) continue;
    const band = mhz < 3000 ? '2g' : mhz >= 5925 ? '6g' : '5g';
    const inferred = mhz === 2484 ? 14 : mhz === 5935 ? 2 : (mhz - (band === '2g' ? 2407 : band === '6g' ? 5950 : mhz < 5000 ? 4000 : 5000)) / 5;
    Object.assign(add(mhz, inferred), survey, { busy_pct: numeric(survey.busy_pct) });
  }
  return [...rows.values()].sort((a, b) => a.frequency - b.frequency);
});
const extent = computed(() => {
  const values = [...channels.value.map(row => row.frequency), ...peers.value.flatMap((peer: any) => peer.segments.flatMap((segment: any) => [segment.center - segment.width / 2, segment.center + segment.width / 2]))];
  return values.length ? [Math.min(...values) - 5, Math.max(...values) + 5] : [2400, 2490];
});
const x = (mhz: number) => LEFT + (mhz - extent.value[0]) / Math.max(1, extent.value[1] - extent.value[0]) * (RIGHT.value - LEFT);
const y = (signal: number) => BASE - (Math.max(-100, Math.min(-20, signal)) + 100) / 80 * (BASE - TOP);
const busyY = (pct: number) => BASE - Math.max(0, Math.min(100, pct)) / 100 * (BASE - TOP);
const ticks = computed(() => channels.value.filter((_, i) => i % Math.max(1, Math.ceil(channels.value.length / (narrow.value ? 8 : 18))) === 0));
const knownBusy = computed(() => channels.value.some(row => number(row.busy_pct)));
const barWidth = computed(() => Math.max(3, Math.min(20, (RIGHT.value - LEFT) / Math.max(1, channels.value.length) * 0.5)));
const currentFrequency = computed(() => channels.value.find(row => row.in_use)?.frequency
  || numeric(props.radio?.frequency) || channelFrequency(Number(props.radio?.runtime_channel || props.radio?.channel), props.radio?.band));
const active = computed(() => peers.value.find((peer: any) => peer.id === highlighted.value));
function path(peer: any, segment: any) {
  const left = x(segment.center - segment.width / 2), right = x(segment.center + segment.width / 2), peak = y(peer.signal);
  const shoulder = Math.min((right - left) / 4, (RIGHT.value - LEFT) * 5 / (extent.value[1] - extent.value[0]));
  return `M${left},${BASE} L${left + shoulder},${peak} L${right - shoulder},${peak} L${right},${BASE} Z`;
}
const widthLabel = (peer: any) => peer.segments.every((segment: any) => segment.known) ? peer.segments.map((segment: any) => segment.width).join('+') + ' МГц' : 'ширина неизвестна (контур 20 МГц)';
const toggle = (peer: any) => { selected.value = selected.value === peer.id ? null : peer.id; };
const detail = computed(() => active.value ? `${active.value.ssid || 'Скрытая сеть'} · канал ${active.value.channel} · ${active.value.signal} dBm · ${widthLabel(active.value)}`
  : channel.value ? `Канал ${channel.value.channel} · ${channel.value.frequency} МГц · ${channel.value.busy_pct == null ? 'нет измерения занятости' : 'занятость ' + channel.value.busy_pct + '%'}${channel.value.noise == null ? '' : ' · шум ' + channel.value.noise + ' dBm'} · сетей: ${channel.value.count}`
  : 'Наведите на сеть или столбик. Нажмите на название сети, чтобы выделить её.');
</script>
<template>
  <section class="gw-channel-charts">
    <article class="gw-spectrum-card">
      <header><h3>Wi-Fi каналы и соседние сети</h3><span>{{ peers.length }} сетей на графике</span></header>
      <div class="gw-spectrum-plot">
        <svg :viewBox="`0 0 ${W} 282`" role="img" aria-label="Каналы и уровень сигнала соседних Wi-Fi сетей" @mouseleave="hovered = null; channel = null">
          <g v-for="dbm in [-100,-80,-60,-40,-20]" :key="dbm"><line :x1="LEFT" :y1="y(dbm)" :x2="RIGHT" :y2="y(dbm)" class="gw-spectrum-grid"/><text x="40" :y="y(dbm)+4" text-anchor="end">{{ dbm }}</text></g>
          <text x="8" y="14">dBm</text><text v-if="knownBusy" :x="W-8" y="14" text-anchor="end">%</text>
          <g v-if="knownBusy"><text v-for="pct in [0,25,50,75,100]" :key="pct" :x="RIGHT+8" :y="busyY(pct)+4">{{ pct }}</text></g>
          <g v-for="row in channels.filter(row => number(row.busy_pct))" :key="row.frequency" class="gw-spectrum-occupancy" tabindex="0" role="button" :aria-label="`Канал ${row.channel}, занятость ${row.busy_pct}%`" @mouseenter="channel=row; hovered=null" @mouseleave="channel=null" @focus="channel=row; hovered=null" @blur="channel=null">
            <rect :x="x(row.frequency)-barWidth/2" :y="busyY(row.busy_pct)" :width="barWidth" :height="Math.max(1,BASE-busyY(row.busy_pct))" rx="2" :fill="row.busy_pct>=70?'#e4b56c':'#62c7a7'" fill-opacity="0.45"/>
          </g>
          <line v-if="currentFrequency" :x1="x(currentFrequency)" :y1="TOP" :x2="x(currentFrequency)" :y2="BASE" class="gw-spectrum-current"/>
          <g v-for="peer in peers" :key="peer.id" :opacity="highlighted && highlighted !== peer.id ? 0.2 : 1" class="gw-spectrum-peer" tabindex="0" role="button" :aria-label="`${peer.ssid || 'Скрытая сеть'}, канал ${peer.channel}, ${peer.signal} dBm`" @mouseenter="hovered = peer.id; channel=null" @mouseleave="hovered = null" @focus="hovered = peer.id; channel=null" @blur="hovered = null" @click="toggle(peer)" @keydown.enter.prevent="toggle(peer)" @keydown.space.prevent="toggle(peer)">
            <path v-for="(segment,i) in peer.segments" :key="i" :d="path(peer,segment)" :fill="peer.color" fill-opacity="0.13" :stroke="peer.color" :stroke-width="highlighted === peer.id ? 3 : 1.5"/>
            <text :x="x(peer.frequency)" :y="y(peer.signal)-5" text-anchor="middle" :style="{fill:peer.color}" class="gw-spectrum-ssid">{{ (peer.ssid || 'Скрытая сеть').slice(0, narrow ? 12 : 20) }}</text>
          </g>
          <g v-for="tick in ticks" :key="tick.frequency"><text :x="x(tick.frequency)" y="263" text-anchor="middle">{{ tick.channel }}</text></g>
          <text :x="RIGHT" y="279" text-anchor="end">Канал</text>
        </svg>
        <p v-if="!peers.length" class="gw-spectrum-empty">{{ data.networks?.length ? 'Сети найдены, но драйвер не сообщил канал или уровень сигнала.' : 'Соседние сети не найдены' }}</p>
      </div>
      <div class="gw-spectrum-detail" role="status" aria-live="polite"><span :title="detail">{{ detail }}</span></div>
      <div class="gw-spectrum-key" aria-label="Легенда графика"><span><i class="gw-key-line"/>Контуры — сигнал сетей, шкала слева (dBm)</span><span v-if="currentFrequency"><i class="gw-key-current"/>Пунктир — текущий канал</span><template v-if="knownBusy"><span><i class="gw-key-busy"/>Зелёный — занятость менее 70%</span><span><i class="gw-key-crowded"/>Жёлтый — занятость от 70%</span><span>Столбики — занятость эфира, шкала справа (%)</span></template><span v-else>Измерения занятости от драйвера отсутствуют</span></div>
      <div class="gw-spectrum-legend"><button v-for="peer in peers" :key="peer.id" :class="{on:selected===peer.id}" :aria-pressed="selected===peer.id" @mouseenter="hovered=peer.id; channel=null" @mouseleave="hovered=null" @focus="hovered=peer.id; channel=null" @blur="hovered=null" @click="toggle(peer)"><i :style="{background:peer.color}"/><span>{{ peer.ssid || 'Скрытая сеть' }}</span><small>{{ peer.signal }} dBm</small></button></div>
      <p class="gw-chart-note">Высота контура — сила сигнала, ширина — полоса сети. Если ширина неизвестна, показан контур 20 МГц. Занятость измеряется драйвером; число сетей не заменяет это измерение.</p>
    </article>
  </section>
</template>
<style>
.gw-channel-charts{min-width:0}.gw-spectrum-card{border:1px solid var(--border,#29374b);border-radius:10px;padding:14px;min-width:0}.gw-spectrum-card>header{display:flex;justify-content:space-between;align-items:center;gap:12px}.gw-spectrum-card h3{font-size:14px;margin:0}.gw-spectrum-card>header span{font-size:11px;color:var(--text-muted,#98a8bd)}.gw-spectrum-plot{position:relative;margin-top:10px;min-width:0}.gw-spectrum-plot svg{width:100%;display:block;overflow:hidden}.gw-spectrum-card svg text{font-size:11px;fill:var(--text-muted,#98a8bd)}.gw-spectrum-card svg .gw-spectrum-ssid{fill:inherit;font-size:10px;pointer-events:none}.gw-spectrum-grid{stroke:var(--border,#29374b);stroke-dasharray:4 4}.gw-spectrum-current{stroke:var(--text);stroke-dasharray:4 4;stroke-width:1.5}.gw-spectrum-peer,.gw-spectrum-occupancy{cursor:pointer;outline:none}.gw-spectrum-peer:focus-visible path,.gw-spectrum-occupancy:focus-visible rect{stroke-width:3;stroke:var(--text)}.gw-spectrum-empty{position:absolute;inset:0;display:grid;place-items:center;text-align:center;color:var(--text-muted,#98a8bd);font-size:12px;pointer-events:none}.gw-spectrum-detail{display:flex;align-items:center;height:32px;min-height:32px;overflow:hidden;font-size:12px;color:var(--text);margin:4px 0}.gw-spectrum-detail>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.gw-spectrum-key{display:flex;gap:5px 14px;flex-wrap:wrap;font-size:10px;line-height:1.5;color:var(--text-muted,#98a8bd);margin:4px 0 8px}.gw-spectrum-key>span{display:flex;align-items:center;gap:6px}.gw-spectrum-key i{display:inline-block;width:12px;height:8px;flex:0 0 auto}.gw-key-line{border-top:2px solid var(--accent)}.gw-key-current{border-top:2px dashed var(--text)}.gw-key-busy{background:#62c7a7}.gw-key-crowded{background:#e4b56c}.gw-spectrum-legend{display:flex;gap:5px;flex-wrap:wrap;max-height:84px;overflow:auto;padding:3px 0;scrollbar-gutter:stable}.gw-shell .gw-spectrum-legend button{display:flex;align-items:center;gap:6px;font-size:11px;padding:4px 7px;max-width:100%;min-width:0}.gw-spectrum-legend i{width:8px;height:8px;flex-shrink:0;border-radius:50%}.gw-spectrum-legend button>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.gw-spectrum-legend small{color:var(--text-muted,#98a8bd);white-space:nowrap}.gw-spectrum-legend .on{border-color:var(--accent,#63a8f5)}.gw-chart-note{font-size:10px;color:var(--text-muted,#98a8bd);line-height:1.5;margin:8px 0 0}@media(max-width:600px){.gw-spectrum-card{padding:10px}.gw-spectrum-card>header{display:block}.gw-spectrum-card>header span{display:block;margin-top:4px}.gw-spectrum-card svg text{font-size:13px}.gw-spectrum-card svg .gw-spectrum-ssid{font-size:11px}.gw-spectrum-detail{font-size:11px}.gw-spectrum-key{font-size:10px}}
</style>
