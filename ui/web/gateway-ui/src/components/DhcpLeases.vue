<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import type { Bridge } from '../main';
import GatewayDialog from '../GatewayDialog.vue';
import RouterSettings from '../RouterSettings.vue';
import type { DhcpLease, DhcpReservation, DhcpReservationForm, Gateway } from '../types/gateway';

const props = defineProps<{ node: Gateway; bridge: Bridge; busy: boolean; revision?: number; onTaskDone: () => void }>();
const emit = defineEmits<{ close: [] }>();
const config = ref<{ hash: string; reservations: DhcpReservation[] } | null>(null);
const loading = ref(false), error = ref('');
const draft = ref<DhcpReservationForm | null>(null);
const view = ref<'issued'|'static'>('issued'), query = ref(''), page = ref(1);
const pageSize = 20;
let requestId = 0;

const online = computed(() => props.node.monitor.ok && !props.node.monitor.stale);
const canChange = computed(() => online.value && !!props.node.monitor.capabilities?.controls?.available && !!config.value && !loading.value && !props.busy && !error.value);
const leases = computed(() => props.node.monitor.clients || []);
const leasesAvailable = computed(() => props.node.monitor.capabilities?.clients?.available ?? Array.isArray(props.node.monitor.clients));
const reservations = computed(() => config.value?.reservations || []);
const rows = computed(() => {
  const all = view.value === 'static'
    ? reservations.value.map(reservation => ({ key: reservation.id, name: reservation.name, ip: reservation.ip, mac: reservation.mac.join(', '), reservation, kind: 'static' }))
    : leases.value.map(lease => ({ key: lease.macaddr + ':' + lease.ipaddr, name: lease.hostname === '*' ? '' : lease.hostname, ip: lease.ipaddr, mac: lease.macaddr, lease, kind: leaseKind(lease) }));
  const term = query.value.trim().toLowerCase();
  return all.filter(row => [row.name, row.ip, row.mac].some(value => value?.toLowerCase().includes(term)));
});
const pages = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize)));
const pageRows = computed(() => rows.value.slice((page.value - 1) * pageSize, page.value * pageSize));
watch([query, view], () => { page.value = 1; });
watch(pages, count => { page.value = Math.min(page.value, count); });

async function load() {
  const request = ++requestId;
  loading.value = false;
  error.value = '';
  if (!online.value) return;
  loading.value = true;
  try {
    const model = await props.bridge.request('/api/gateways/' + encodeURIComponent(props.node.id) + '/network');
    if (request !== requestId) return;
    config.value = Array.isArray(model.dhcp_reservations) && typeof model.settings_hash === 'string'
      ? { hash: model.settings_hash, reservations: model.dhcp_reservations } : null;
  } catch (cause) {
    if (request === requestId) error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    if (request === requestId) loading.value = false;
  }
}
watch([online, () => props.revision], () => void load(), { immediate: true });
onUnmounted(() => { requestId++; });

function open(mode: DhcpReservationForm['mode'], reservation?: DhcpReservation, lease?: DhcpLease) {
  if (!canChange.value || !config.value) return;
  draft.value = { configHash: config.value.hash, mode, reservation, lease };
}
function leaseKind(lease: DhcpLease) {
  if (!config.value || loading.value || error.value) return 'unknown';
  const mac = lease.macaddr?.toLowerCase();
  return lease.ipaddr && reservations.value.some(row =>
    row.ip === lease.ipaddr && (!row.mac.length || row.mac.some(value => value.toLowerCase() === mac)))
    ? 'static' : 'issued';
}
function hasReservationConflict(lease: DhcpLease) {
  const mac = lease.macaddr?.toLowerCase();
  return reservations.value.some(row => row.ip === lease.ipaddr || row.mac.some(value => value.toLowerCase() === mac));
}
function closeForm(submitted?: boolean) {
  if (submitted) emit('close');
  else draft.value = null;
}
</script>

<template>
  <GatewayDialog v-if="!draft" title="DHCP-аренды" wide @close="emit('close')">
    <div class="gw-package-filters">
      <div class="gw-segment" role="group" aria-label="Список DHCP-аренд">
        <button type="button" :class="{ on: view === 'issued' }" :aria-pressed="view === 'issued'" @click="view = 'issued'">Текущие</button>
        <button type="button" :class="{ on: view === 'static' }" :aria-pressed="view === 'static'" @click="view = 'static'">Статические</button>
      </div>
      <input v-model="query" type="search" aria-label="Поиск DHCP-аренд" placeholder="Имя, IP или MAC" />
      <button class="gw-primary" :disabled="!canChange" @click="open('add')">Закрепить IPv4 вручную</button>
    </div>
    <p v-if="error" class="gw-hint" role="status">Не удалось определить тип аренды: {{ error }} <button @click="load">Повторить</button></p>
    <p v-else-if="!online" class="gw-hint">Шлюз недоступен. Показаны последние полученные данные.</p>
    <p v-else-if="loading" class="gw-hint" role="status">Загрузка статических аренд…</p>
    <p v-else-if="!config" class="gw-hint">Тип аренды недоступен. Обновите интеграцию Bot4VPS во вкладке «Доступ».</p>
    <div v-if="pageRows.length" class="gw-table-wrap">
      <table class="gw-dhcp-table">
        <thead><tr><th scope="col">Устройство</th><th scope="col">IPv4-адрес</th><th scope="col">MAC-адрес</th><th scope="col">Тип аренды</th><th v-if="view === 'static'" scope="col">Действия</th></tr></thead>
        <tbody>
          <tr v-for="row in pageRows" :key="row.key">
            <td>{{ row.name || 'Без имени' }}</td><td>{{ row.ip || '—' }}</td><td>{{ row.mac || '—' }}</td>
            <td class="gw-dhcp-kind">
              <div class="gw-dhcp-kind-body" :class="{ 'is-static': row.kind === 'static' }">
                <span class="gw-dhcp-marker" :class="row.kind">{{ row.kind === 'static' ? 'Статическая' : row.kind === 'issued' ? 'Аренда' : '—' }}</span>
                <button v-if="'lease' in row && row.kind === 'issued' && row.lease.macaddr && row.lease.ipaddr && !hasReservationConflict(row.lease)" :disabled="!canChange" @click="open('add', undefined, row.lease)">Закрепить IP</button>
              </div>
            </td>
            <td v-if="'reservation' in row">
              <div class="gw-actions">
                <button :disabled="!canChange" @click="open('edit', row.reservation)">Изменить</button>
                <button class="gw-danger" :disabled="!canChange" @click="open('delete', row.reservation)">Удалить</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else-if="view === 'issued' && !leasesAvailable" class="gw-hint">Данные о выданных IPv4-адресах недоступны.</p>
    <p v-else-if="view === 'issued' || config" class="gw-hint">{{ query.trim() ? 'Аренды не найдены' : view === 'issued' ? 'Нет выданных IPv4-адресов' : 'Нет статических IPv4-аренд' }}</p>
    <footer v-if="pages > 1" class="gw-pagination gw-dhcp-pagination">
      <span class="gw-hint">{{ (page - 1) * pageSize + 1 }}–{{ Math.min(page * pageSize, rows.length) }} из {{ rows.length }}</span>
      <div class="gw-actions">
        <button :disabled="page === 1" @click="page--">Назад</button><span aria-live="polite">{{ page }} / {{ pages }}</span><button :disabled="page === pages" @click="page++">Далее</button>
      </div>
    </footer>
  </GatewayDialog>
  <RouterSettings v-else :node="node" :bridge="bridge" mode="dhcp_reservation" :reservation-form="draft" :on-task-done="onTaskDone" @close="closeForm" />
</template>

<style>
.gw-dhcp-table td:nth-child(2), .gw-dhcp-table td:nth-child(3), .gw-dhcp-table .gw-actions { white-space: nowrap; }
.gw-shell .gw-dhcp-table tbody td { height: 49px; padding-block: 4px; }
.gw-dhcp-kind { width: 116px; }
.gw-dhcp-kind-body { display: grid; grid-template-rows: 15px 22px; gap: 2px; align-items: center; justify-items: start; }
.gw-dhcp-kind-body.is-static { grid-template-rows: auto; }
.gw-dhcp-marker { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; }
.gw-dhcp-marker::before { content: ''; width: 7px; height: 7px; border-radius: 50%; }
.gw-dhcp-marker.static::before { background: #3b82f6; }
.gw-dhcp-marker.issued::before { background: #eab308; }
.gw-shell .gw-dhcp-kind-body button, .gw-shell .gw-dhcp-table .gw-actions button { padding: 2px 7px; font-size: 11px; line-height: 16px; border-radius: 6px; }
.gw-dhcp-table .gw-actions { flex-wrap: nowrap; }
.gw-dialog .gw-dhcp-table .gw-actions, .gw-dialog .gw-dhcp-pagination .gw-actions { margin-top: 0; }
</style>
