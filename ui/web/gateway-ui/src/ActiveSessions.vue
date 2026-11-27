<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { Bridge } from './main';

interface Rates { rx_bps: number; tx_bps: number }
interface Connection extends Rates {
  id: string;
  device_name?: string | null;
  device_ip: string;
  name?: string | null;
  domain?: string | null;
  destination_ip?: string | null;
  observed_ip?: string | null;
  via_fake_ip: boolean;
}
interface Sample {
  status: 'warming' | 'ready' | 'integration' | 'accounting' | 'unavailable' | 'networks';
  connections?: Connection[]; offloaded?: boolean; truncated?: boolean;
  total?: Rates; wan?: Rates | null;
}

const props = defineProps<{ nodeId: string; bridge: Bridge; collect: boolean }>();
const sample = ref<Sample>();
const error = ref(false);
const supported = ref(true);
const messages: Partial<Record<Sample['status'], string>> = {
  warming: 'Сравниваем первые замеры трафика…',
  integration: 'Обновите интеграцию Bot4VPS во вкладке «Доступ».',
  accounting: 'На OpenWrt выключен учёт байтов соединений.',
  unavailable: 'Счётчики соединений шлюза сейчас недоступны.',
  networks: 'Шлюз не сообщил адреса локальных сетей.',
};
const deviceFilter = ref('');
const destinationFilter = ref('');
const routeFilter = ref<'all' | 'direct' | 'fake'>('all');
const viewport = ref<HTMLElement>();
const history = new Map<string, Connection>();
const recorded = ref<Connection[]>([]);
const devices = new Map<string, Connection>();
const deviceOptions = ref<Connection[]>([]);
const scrollTop = ref(0);
const rowHeight = 32;
const viewportRows = 15;
const overscan = 4;
const destinationTerm = computed(() => destinationFilter.value.trim().toLocaleLowerCase('ru'));
const rows = computed(() => {
  return recorded.value.filter(row =>
    (routeFilter.value === 'all' || row.via_fake_ip === (routeFilter.value === 'fake')) &&
    (!deviceFilter.value || row.device_ip === deviceFilter.value) &&
    (!destinationTerm.value || [row.name, row.domain, row.destination_ip, row.observed_ip].some(value =>
      value?.toLocaleLowerCase('ru').includes(destinationTerm.value)))
  );
});
const first = computed(() => Math.max(0, Math.min(
  Math.floor(scrollTop.value / rowHeight), rows.value.length - viewportRows,
) - overscan));
const last = computed(() => Math.min(rows.value.length, first.value + viewportRows + 2 * overscan + 1));
watch([deviceFilter, destinationFilter, routeFilter], () => {
  scrollTop.value = 0;
  viewport.value?.scrollTo(0, 0);
});
const message = computed(() => {
  if (error.value) return 'Не удалось получить сеансы. Повторяем запрос.';
  if (sample.value?.status !== 'ready') return sample.value ? messages[sample.value.status] : 'Получаем счётчики шлюза…';
  if (!sample.value.connections) return 'Получаем список соединений…';
  if (!rows.value.length) {
    const filtering = deviceFilter.value || destinationTerm.value || routeFilter.value !== 'all';
    return filtering ? 'Совпадений нет.' : 'Соединений пока нет.';
  }
  return '';
});
function target(row: Connection) {
  const label = row.name || row.domain || row.destination_ip || row.observed_ip || '—';
  return row.domain && row.destination_ip ? label + ' (' + row.destination_ip + ')' : label;
}
function device(row: Connection) {
  return row.device_name ? row.device_name + ' (' + row.device_ip + ')' : row.device_ip;
}
function targetTitle(row: Connection) {
  return row.domain && row.domain !== row.name ? target(row) + ' · ' + row.domain : target(row);
}
const number = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
function speed(bits?: number) {
  if (bits === undefined) return '—';
  return bits > 0 && bits < 100_000 ? '<0,1' : number.format(bits / 1_000_000);
}

let active = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let request: AbortController | undefined;
async function poll() {
  if (!active || !props.collect || request || !supported.value) return;
  const current = new AbortController();
  request = current;
  try {
    const data: Sample = await props.bridge.request(`/api/gateways/${encodeURIComponent(props.nodeId)}/active-sessions?view=connections`,
      { signal: current.signal });
    if (!current.signal.aborted) {
      sample.value = data;
      error.value = false;
      let devicesChanged = false;
      for (const row of data.connections || []) {
        history.set(row.id, row);
        const device = devices.get(row.device_ip);
        if (!device || (row.device_name && row.device_name !== device.device_name)) {
          devices.set(row.device_ip, row);
          devicesChanged = true;
        }
      }
      if (devicesChanged) deviceOptions.value = [...devices.values()];
      if (data.connections?.length) recorded.value = [...history.values()];
    }
  } catch (failure) {
    if (!current.signal.aborted) {
      supported.value = (failure as { status?: number })?.status !== 404;
      sample.value = undefined;
      error.value = true;
    }
  } finally {
    if (request === current) request = undefined;
    if (active && props.collect && supported.value && !current.signal.aborted) {
      timer = setTimeout(poll, error.value || sample.value?.status === 'integration' ? 10_000 : 3000);
    }
  }
}
function cancel() {
  clearTimeout(timer);
  request?.abort();
  request = undefined;
}
onMounted(() => { active = true; void poll(); });
onUnmounted(() => { active = false; cancel(); });
watch(() => props.collect, collect => { if (collect) void poll(); else cancel(); });
</script>

<template>
  <section v-if="supported" class="active-sessions" aria-label="Активные сеансы">
    <details class="sessions-disclosure">
      <summary class="sessions-summary">
        <span class="sessions-header">
          <span class="session-arrow" aria-hidden="true">›</span>
          <strong>Активные сеансы</strong>
          <span class="sessions-caption">Мбит/с · обновление каждые 3 с</span>
        </span>
        <span class="sessions-totals">
          <span class="sessions-total">WAN <b>↓ {{ speed(sample?.wan?.rx_bps) }} · ↑ {{ speed(sample?.wan?.tx_bps) }}</b></span>
          <span class="sessions-total">Устройства <b>↓ {{ speed(sample?.total?.rx_bps) }} · ↑ {{ speed(sample?.total?.tx_bps) }}</b></span>
        </span>
      </summary>
      <div class="sessions-content">
        <div class="sessions-filter">
          <select v-model="deviceFilter" aria-label="Фильтр по устройству">
            <option value="">Все устройства</option>
            <option v-for="row in deviceOptions" :key="row.device_ip" :value="row.device_ip">{{ device(row) }}</option>
          </select>
          <input v-model="destinationFilter" type="search" aria-label="Фильтр по назначению" placeholder="Сервис, домен или IP" />
          <select v-model="routeFilter" aria-label="Фильтр по маршруту">
            <option value="all">Все маршруты</option>
            <option value="direct">Напрямую</option>
            <option value="fake">Через Fake-IP</option>
          </select>
          <span class="session-limit" :title="sample?.offloaded || sample?.truncated ? 'Часть трафика может отсутствовать' : 'Скорости по последнему замеру'">
            {{ sample?.offloaded || sample?.truncated ? 'Последний замер · неполный трафик' : 'Скорости по последнему замеру' }}
          </span>
        </div>
        <div class="sessions-horizontal">
          <div ref="viewport" class="sessions-scroll" tabindex="0" :style="{ '--session-row-height': rowHeight + 'px', '--session-rows': viewportRows }"
            aria-label="Список активных соединений" @scroll="scrollTop = viewport?.scrollTop || 0">
            <div class="sessions-table" role="table" aria-label="Активные соединения">
              <div class="session-grid session-labels" role="row">
                <span role="columnheader">Устройство</span><span role="columnheader">Назначение</span><span role="columnheader">Маршрут</span><span role="columnheader" title="Последний замер по соединению">↓ Приём</span><span role="columnheader" title="Последний замер по соединению">↑ Передача</span>
              </div>
              <div v-if="first" aria-hidden="true" :style="{ height: first * rowHeight + 'px' }"></div>
              <div v-for="row in rows.slice(first, last)" :key="row.id" class="session-grid session-connection" role="row">
                <span class="session-name" role="cell" :title="device(row)">{{ device(row) }}</span>
                <span role="cell" :title="targetTitle(row)">{{ target(row) }}</span>
                <span class="session-route" role="cell" :title="row.via_fake_ip ? 'Адрес подменён Fake-IP' : 'Обращение к реальному IP'">{{ row.via_fake_ip ? 'Через Fake-IP' : 'Напрямую' }}</span>
                <b class="session-rx" role="cell">{{ speed(row.rx_bps) }}</b><b class="session-tx" role="cell">{{ speed(row.tx_bps) }}</b>
              </div>
              <div v-if="last < rows.length" aria-hidden="true" :style="{ height: (rows.length - last) * rowHeight + 'px' }"></div>
            </div>
            <p v-if="message" class="gw-hint" role="status">{{ message }}</p>
          </div>
        </div>
      </div>
    </details>
  </section>
</template>

<style scoped>
.active-sessions { border: 1px solid var(--border); border-radius: 9px; background: var(--panel,var(--card)); margin-top: 15px; overflow: hidden; }
.sessions-summary { display: block; padding: 10px 13px; list-style: none; cursor: pointer; }
.sessions-summary::-webkit-details-marker { display: none; }
.sessions-summary:hover { background: var(--hover,rgba(112,156,221,.08)); }
.sessions-summary:focus-visible { outline: 2px solid var(--accent,#72b3ff); outline-offset: -2px; }
.sessions-header { display: flex; align-items: center; gap: 7px; }
.sessions-header strong { font-size: 14px; }
.sessions-caption { margin-left: auto; font-size: 11px; color: var(--text-muted,#9eacc1); white-space: nowrap; }
.sessions-totals { display: flex; gap: 6px 18px; padding: 5px 0 0 18px; color: var(--text-muted,#9eacc1); font-size: 12px; }
.sessions-total { white-space: nowrap; font-variant-numeric: tabular-nums; }
.sessions-totals b { color: var(--text,#e7efff); margin-left: 4px; }
.sessions-content { border-top: 1px solid var(--border); }
.sessions-filter { display: grid; grid-template-columns: repeat(2,minmax(0,220px)) max-content minmax(0,1fr); align-items: center; gap: 8px; padding: 8px 13px; }
.sessions-filter :is(input,select) { width: 100%; min-width: 0; }
.sessions-filter .session-limit { color: var(--text-muted,#9eacc1); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sessions-scroll .gw-hint { margin: 0; padding: 8px 13px; }
.sessions-horizontal { overflow-x: auto; }
.sessions-scroll { --session-header-height: 30px; height: calc(var(--session-header-height) + var(--session-rows) * var(--session-row-height)); min-width: 645px; overflow-y: auto; scrollbar-gutter: stable; }
.sessions-table { font-variant-numeric: tabular-nums; }
.session-grid { display: grid; grid-template-columns: minmax(145px,1fr) minmax(150px,1.35fr) 104px 74px 78px; gap: 9px; align-items: center; padding: 0 13px; }
.session-grid > span { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.session-grid > :nth-last-child(-n+2) { white-space: nowrap; text-align: right; }
.session-labels { box-sizing: border-box; height: var(--session-header-height); position: sticky; top: 0; z-index: 1; color: var(--text-muted,#9eacc1); background: var(--field,#101927); font-size: 11px; }
.session-connection { box-sizing: border-box; height: var(--session-row-height); border-top: 1px solid var(--border); font-size: 12px; }
.session-name { font-weight: 600; }
.session-route { color: var(--text-muted,#9eacc1); font-size: 11px; }
.session-arrow { width: 11px; text-align: center; color: var(--accent,#72b3ff); font-size: 15px; }
.sessions-disclosure[open] > .sessions-summary .session-arrow { transform: rotate(90deg); }
.session-rx { color: #72b3ff; }.session-tx { color: #dfa2f0; }
@media (max-width: 650px) {
  .sessions-filter { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .sessions-scroll { min-width: 465px; }
  .session-grid { grid-template-columns: minmax(104px,1fr) minmax(112px,1.25fr) 80px 53px 56px; padding-inline: 7px; gap: 4px; }
  .session-connection,.session-labels,.session-route { font-size: 10px; }
}
@media (max-width: 430px) {
  .sessions-summary { padding-inline: 9px; }
  .sessions-caption { font-size: 10px; }
  .sessions-totals { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px; }
  .sessions-total { display: flex; flex-direction: column; }
  .sessions-totals b { margin-left: 0; }
}
</style>
