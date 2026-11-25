<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue';
import type { Bridge } from './main';
import GatewayDialog from './GatewayDialog.vue';
const props = defineProps<{ node: any; bridge: Bridge; initialQuery?: string }>();
const emit = defineEmits<{ changed: [] }>();
const query = ref(props.initialQuery || ''), installed = ref(false), loading = ref(false), acting = ref(false), error = ref('');
const result = ref<any>({ items: [], total: 0, offset: 0, has_indexes: false });
const plan = ref<any>(null);
let searchTimer: ReturnType<typeof setTimeout> | undefined, serial = 0;
const base = () => '/api/gateways/' + encodeURIComponent(props.node.id);
const post = (path: string, body: unknown, method = 'POST') => props.bridge.request(base() + path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
async function load(offset = 0) {
  const request = ++serial; loading.value = true; error.value = '';
  try {
    const data = await props.bridge.request(base() + '/packages?query=' + encodeURIComponent(query.value) + '&installed=' + installed.value + '&offset=' + offset);
    if (request === serial) result.value = data;
  } catch (e: any) { if (request === serial) error.value = e.message; }
  finally { if (request === serial) loading.value = false; }
}
async function apply(value: any) {
  const task = await post('/router-operations', { plan_token: value.plan_token, confirmed: true });
  plan.value = null;
  props.bridge.task({ taskId: task.task_id, title: value.action === 'refresh' ? 'Обновление списка пакетов' : 'Установка ' + value.package, cancellable: false,
    onDone: async () => { await load(); emit('changed'); } });
}
async function refreshIndexes() {
  if (acting.value) return; acting.value = true; error.value = '';
  try { const value = await post('/packages/plan', { action: 'refresh' }); await apply(value); }
  catch (e: any) { error.value = e.message; }
  finally { acting.value = false; }
}
async function installation(name: string) {
  if (acting.value) return; acting.value = true; error.value = '';
  try { plan.value = await post('/packages/plan', { action: 'install', package: name }); }
  catch (e: any) { error.value = e.message; }
  finally { acting.value = false; }
}
async function install() {
  if (acting.value) return; acting.value = true; error.value = '';
  try { await apply(plan.value); } catch (e: any) { error.value = e.message; }
  finally { acting.value = false; }
}
function select(value: boolean) { installed.value = value; void load(); }
function discardPlan() {
  const token = plan.value?.plan_token; plan.value = null; error.value = '';
  if (token) post('/operation-plans/' + encodeURIComponent(token), {}, 'DELETE').catch((e: any) => { error.value = e.message; });
}
watch(query, () => { if (searchTimer) clearTimeout(searchTimer); searchTimer = setTimeout(() => void load(), 300); });
onMounted(() => void load());
onUnmounted(() => { serial++; if (searchTimer) clearTimeout(searchTimer); });
</script>
<template>
  <section class="gw-packages">

    <header class="gw-section-header"><div><h3>Пакетный менеджер</h3><p class="gw-hint">{{ result.manager || 'OpenWrt' }} · {{ result.installed_count ?? '—' }} установленных пакетов</p></div><button :disabled="acting" @click="refreshIndexes">Обновить список пакетов</button></header>
    <p class="gw-hint">Обновляется каталог репозиториев. Установленные пакеты и прошивка автоматически не обновляются.</p>
    <div v-if="error && !plan" class="gw-error" role="alert">{{ error }}</div>
    <div class="gw-package-filters"><div class="gw-segment"><button :class="{ on: !installed }" @click="select(false)">Доступные</button><button :class="{ on: installed }" @click="select(true)">Установленные</button></div><form @submit.prevent="load()"><input v-model="query" type="search" aria-label="Поиск пакетов" placeholder="Название или описание пакета…" maxlength="100" /><button :disabled="loading">Найти</button></form></div>
    <p v-if="!result.has_indexes && !loading" class="gw-notice">Список доступных пакетов ещё не загружен. Нажмите «Обновить список пакетов» — ход загрузки появится в журнале.</p>
    <div class="gw-table-wrap" :aria-busy="loading"><table class="gw-package-table"><thead><tr><th>Пакет</th><th>Версия</th><th></th></tr></thead><tbody><tr v-for="item in result.items" :key="item.name"><td><strong>{{ item.name }}</strong><small>{{ item.description }}</small></td><td><span>{{ item.installed_version || item.version }}</span><small v-if="item.installed_version && item.installed_version !== item.version">В каталоге: {{ item.version }}</small></td><td><span v-if="item.installed_version" class="gw-status good">Установлен</span><button v-else :disabled="acting || loading" @click="installation(item.name)">Установить</button></td></tr></tbody></table></div>
    <p v-if="!result.items.length" class="gw-hint">{{ loading ? 'Загружаем пакеты…' : query ? 'По вашему запросу пакеты не найдены.' : 'Пакетов в этом списке нет.' }}</p>
    <footer class="gw-pagination"><span class="gw-hint">{{ loading ? 'Загрузка…' : result.total ? (result.offset + 1) + '–' + Math.min(result.offset + result.items.length, result.total) + ' из ' + result.total : '0 пакетов' }}</span><div class="gw-actions"><button :disabled="loading || result.offset === 0" @click="load(Math.max(0, result.offset - 40))">Назад</button><button :disabled="loading || result.offset + 40 >= result.total" @click="load(result.offset + 40)">Далее</button></div></footer>
  </section>
  <GatewayDialog v-if="plan" :title="'Установить ' + plan.package + '?'" :busy="acting" @close="discardPlan">
    <p>Пакетный менеджер рассчитает и установит необходимые зависимости из настроенных репозиториев роутера.</p>
    <pre class="gw-plan-output">{{ plan.summary.join('\n') }}</pre>
    <p class="gw-hint">Установочные скрипты пакетов могут менять настройки и запускать службы. Автоматическая замена уже установленных пакетов отключена.</p>
    <p v-if="error" class="gw-error" role="alert">{{ error }}</p>
    <div class="gw-actions"><button class="gw-primary" :disabled="acting" @click="install">Да, установить</button><button :disabled="acting" @click="discardPlan">Отмена</button></div>
  </GatewayDialog>
</template>
<style>
.gw-section-header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:14px}.gw-section-header h3{margin:0}.gw-section-header p{margin:5px 0 0}.gw-package-filters{display:flex;gap:16px;align-items:center;margin:22px 0}.gw-package-filters form{display:flex;gap:8px;flex:1}.gw-shell input,.gw-shell select,.gw-shell textarea{background:var(--field,#101927);color:inherit;border:1px solid var(--border,#29374b);border-radius:8px;padding:10px;font:inherit;min-width:0}.gw-package-filters input{width:100%}.gw-segment{display:flex;gap:4px;padding:4px;border:1px solid var(--border,#29374b);border-radius:12px}.gw-shell .gw-segment button{border:0;background:transparent;white-space:nowrap}.gw-shell .gw-segment .on{background:#5299e920;color:var(--gw-accent)}.gw-pagination{display:flex;justify-content:space-between;align-items:center;margin-top:18px;gap:12px}.gw-notice{padding:14px;background:#5299e912;border-radius:10px;font-size:13px;line-height:1.6;color:var(--text-muted,#98a8bd)}.gw-plan-output{max-height:260px;overflow:auto;padding:14px;background:var(--field,#101927);border-radius:9px;white-space:pre-wrap;font-size:12px}.gw-package-table{white-space:normal!important}.gw-package-table td:first-child{width:60%}.gw-package-table td:last-child{text-align:right}.gw-package-table small{max-width:520px;line-height:1.6}.gw-package-table strong{overflow-wrap:anywhere}.gw-package-table td{vertical-align:top}
@media(max-width:700px){.gw-section-header,.gw-package-filters{align-items:stretch;flex-direction:column}.gw-segment{align-self:flex-start}.gw-package-table th,.gw-package-table td{padding:11px 6px}.gw-package-table small{font-size:11px}.gw-pagination{flex-wrap:wrap}}
</style>
<style>
.gw-shell .gw-package-filters{gap:9px;margin:12px 0}.gw-shell .gw-package-filters input{padding:6px 8px;font-size:12px;min-height:30px}.gw-shell .gw-package-filters button,.gw-shell .gw-segment button{padding:6px 9px;font-size:11px}.gw-shell .gw-segment{padding:3px;border-radius:8px}.gw-shell .gw-package-table td{padding-top:7px;padding-bottom:7px;font-size:12px}.gw-shell .gw-package-table small{font-size:10px;line-height:1.35;margin-top:2px}.gw-shell .gw-package-table button{padding:5px 8px;font-size:11px}.gw-shell .gw-package-table strong{font-size:12px}.gw-shell .gw-packages>.gw-section-header button{padding:6px 9px;font-size:11px}.gw-shell .gw-package-table th{font-size:11px;padding-top:7px;padding-bottom:7px}.gw-shell .gw-package-filters form{gap:6px}.gw-shell .gw-packages>.gw-pagination{margin-top:10px;font-size:11px}
</style>
