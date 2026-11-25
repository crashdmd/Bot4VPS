<script setup lang="ts">
import { onMounted, ref } from 'vue';
import type { Bridge } from '../main';
import GatewayDialog from '../GatewayDialog.vue';
const props = defineProps<{ node: any; bridge: Bridge }>();
const emit = defineEmits<{ close: []; changed: [] }>();
const busy = ref(false), error = ref(''), plan = ref<any>(null);
const base = '/api/gateways/' + encodeURIComponent(props.node.id);
const post = (path: string, data: unknown, method = 'POST') => props.bridge.request(base + path, {
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
});
async function prepare() {
  busy.value = true; error.value = '';
  try {
    const config = await props.bridge.request(base + '/network');
    if (!config.settings_hash) throw new Error('Не удалось прочитать актуальные настройки firewall');
    plan.value = await post('/network/plan', { action: 'firewall_restart', data: { config_hash: config.settings_hash } });
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
async function apply() {
  if (busy.value || !plan.value) return;
  busy.value = true; error.value = '';
  try {
    const value = plan.value;
    const task = await post('/router-operations', { plan_token: value.plan_token, confirmed: true });
    plan.value = null; emit('close');
    props.bridge.task({ taskId: task.task_id, title: value.title, cancellable: false, onDone: async () => emit('changed') });
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
async function cancel() {
  if (busy.value) return;
  busy.value = true; error.value = '';
  try {
    if (plan.value) await post('/operation-plans/' + encodeURIComponent(plan.value.plan_token), {}, 'DELETE');
    plan.value = null; emit('close');
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
onMounted(() => void prepare());
</script>
<template>
  <GatewayDialog title="Перезапуск firewall" :busy="busy" @close="cancel">
    <p v-if="error" class="gw-error" role="alert">{{ error }}</p>
    <p v-if="busy && !plan" class="gw-hint">Получаем план перезапуска…</p>
    <template v-if="plan">
      <ul class="gw-change-list"><li v-for="(change, index) in plan.summary" :key="index">{{ change }}</li></ul>
      <ul v-if="plan.warnings?.length" class="gw-notice"><li v-for="(warning, index) in plan.warnings" :key="index">{{ warning }}</li></ul>
      <p class="gw-notice">Панель проверит связь. Если подтверждение не придёт в течение {{ plan.rollback_seconds }} секунд, роутер восстановит прежнюю конфигурацию.</p>
    </template>
    <div class="gw-actions">
      <button v-if="plan" class="gw-primary" :disabled="busy" @click="apply">Перезапустить</button>
      <button v-else-if="error" :disabled="busy" @click="prepare">Повторить</button>
      <button :disabled="busy" @click="cancel">Отмена</button>
    </div>
  </GatewayDialog>
</template>
