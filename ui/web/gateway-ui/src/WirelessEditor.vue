<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import type { Bridge } from './main';
import GatewayDialog from './GatewayDialog.vue';
import WirelessChannels from './WirelessChannels.vue';
import { networksForScan } from './wirelessScan';
const props = defineProps<{ node: any; bridge: Bridge }>();
const emit = defineEmits<{ changed: [] }>();
const model = ref<any>({ radios: [], networks: [] }), loading = ref(false), busy = ref(false), error = ref('');
const editor = ref<any>(null), plan = ref<any>(null), scanning = ref(false), scanRadio = ref<any>(null), scanResult = ref<any>(null), scanError = ref(''), scanTab = ref('channels');
let alive = true;
const base = () => '/api/gateways/' + encodeURIComponent(props.node.id);
const post = (path: string, data: unknown, method = 'POST') => props.bridge.request(base() + path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
const networks = (value: any) => Array.isArray(value) ? value : value ? String(value).split(/\s+/) : [];
const encryptionNames: Record<string, string> = { none: 'Без защиты', psk2: 'WPA2-PSK', 'psk2+ccmp': 'WPA2-PSK (CCMP)', 'psk-mixed': 'WPA/WPA2-PSK', sae: 'WPA3-SAE', 'sae-mixed': 'WPA2/WPA3', 'sae+ccmp': 'WPA3-SAE (CCMP)', 'sae-mixed+ccmp': 'WPA2/WPA3 (CCMP)' };
const frequency = (n: any) => typeof n === 'number' ? (n / 1000).toFixed(3) + ' ГГц' : '—';
const band = (radio: any) => ({ '2g': '2,4 ГГц', '5g': '5 ГГц', '6g': '6 ГГц' }[radio.band as string] || frequency(radio.frequency));
const scanNetworks = computed(() => networksForScan(scanResult.value, scanRadio.value));
function protection(n: any) {
  if (!n.encryption?.enabled) return 'Открытая';
  return n.encryption.wpa?.length ? 'WPA ' + n.encryption.wpa.join('/') : 'Защищена';
}
async function load() {
  loading.value = true; error.value = '';
  try { const data = await props.bridge.request(base() + '/wireless'); if (alive) model.value = data; }
  catch (e: any) { if (alive) error.value = e.message; }
  finally { if (alive) loading.value = false; }
}
function edit(radio: any) {
  error.value = '';
  editor.value = { ...radio, original: radio, disabled: radio.disabled === '1', channel: radio.channel || 'auto', country: radio.country || '', txpower: radio.txpower || '', htmode: radio.htmode || 'NOHT',
    interfaces: radio.interfaces.map((i: any) => ({ ...i, original: i, disabled: i.disabled === '1', hidden: i.hidden === '1', isolate: i.isolate === '1', network: networks(i.network), ssid: i.ssid || '', encryption: i.encryption || 'none', key: '' })) };
}
const countryName = (code: string) => { try { return new Intl.DisplayNames(['ru'], {type:'region'}).of(code) || code; } catch { return code; } };
const modeName = (mode: string) => { const match = /^(HT|VHT|HE|EHT)(\d+)$/.exec(mode); return match ? `${match[2]} МГц · Wi-Fi ${{HT:'4 (HT)', VHT:'5 (VHT)', HE:'6 (HE)', EHT:'7 (EHT)'}[match[1]]}` : '20 МГц · без расширений HT'; };
function closeEditor() { editor.value = null; error.value = ''; }
function changes(current: any, original: any, names: string[], booleans: string[] = []) {
  const out: any = {};
  for (const name of names) {
    const value = booleans.includes(name) ? current[name] ? '1' : '0' : current[name] === '' ? null : current[name];
    const old = booleans.includes(name) ? original[name] === '1' ? '1' : '0' : name === 'network' ? networks(original[name]) : original[name] ?? (name === 'channel' ? 'auto' : name === 'encryption' ? 'none' : name === 'htmode' ? 'NOHT' : null);
    if (JSON.stringify(value) !== JSON.stringify(old)) out[name] = value;
  }
  return out;
}
async function review() {
  busy.value = true; error.value = '';
  try {
    const radio = editor.value;
    const data = { config_hash: model.value.config_hash, radio: radio.name,
      settings: changes(radio, radio.original, ['disabled', 'channel', 'country', 'txpower', 'htmode'], ['disabled']),
      interfaces: radio.interfaces.map((i: any) => {
        const settings = changes(i, i.original, ['disabled', 'ssid', 'encryption', 'hidden', 'isolate', 'network'], ['disabled', 'hidden', 'isolate']);
        if (i.key && i.encryption !== 'none') settings.key = i.key;
        return { id: i.id, settings };
      }).filter((i: any) => Object.keys(i.settings).length) };
    plan.value = await post('/network/plan', { action: 'wireless', data });
    for (const i of radio.interfaces) i.key = '';
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
function discard() {
  const token = plan.value?.plan_token; plan.value = null; error.value = '';
  if (token) post('/operation-plans/' + encodeURIComponent(token), {}, 'DELETE').catch((e: any) => { error.value = e.message; });
}
async function apply() {
  busy.value = true; error.value = '';
  try {
    const result = await post('/router-operations', { plan_token: plan.value.plan_token, confirmed: true });
    plan.value = null; closeEditor();
    props.bridge.task({ taskId: result.task_id, title: 'Настройка Wi-Fi', cancellable: false, onDone: async () => { await load(); emit('changed'); } });
  } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
}
async function scan(radio: any) {
  if (scanning.value) return;
  if (scanRadio.value?.name !== radio.name) scanResult.value = null;
  scanRadio.value = radio; scanning.value = true; scanError.value = '';
  try { const data = await post('/wireless/' + encodeURIComponent(radio.name) + '/scan', {}); if (alive) scanResult.value = data; }
  catch (e: any) { if (alive) scanError.value = e.message; }
  finally { if (alive) scanning.value = false; }
}
onMounted(() => void load());
onUnmounted(() => { alive = false; editor.value = null; });
</script>
<template>
  <section class="gw-wireless">
    <header class="gw-section-header"><div><h3>Беспроводные сети</h3><p class="gw-hint">Радиомодули, сети Wi-Fi и обзор каналов</p></div><button :disabled="loading || busy" @click="load">Обновить</button></header>
    <p v-if="error && !editor && !plan" class="gw-error" role="alert">{{ error }}</p>
    <p v-if="!model.radios.length && !error" class="gw-hint">{{ loading ? 'Получаем настройки Wi-Fi…' : 'На шлюзе нет настроенных радиомодулей Wi-Fi.' }}</p>
    <section v-for="radio in model.radios" :key="radio.name" class="gw-radio">
      <header class="gw-section-header"><div><h3>{{ radio.name }} · {{ band(radio) }}</h3><p class="gw-hint">{{ radio.up ? 'Работает' : radio.disabled === '1' ? 'Выключен' : 'Не активен' }} · Канал {{ radio.runtime_channel || radio.channel || 'Авто' }}<span v-if="radio.htmode"> · {{ radio.htmode }}</span></p></div><div class="gw-actions"><button :disabled="busy || scanning || !radio.up" @click="scan(radio)">Просмотр каналов</button><button :disabled="busy || scanning" @click="edit(radio)">Настроить Wi-Fi</button></div></header>
      <div class="gw-table-wrap"><table><thead><tr><th>Сеть</th><th>Режим</th><th>Защита</th><th>Подключение</th><th>Состояние</th></tr></thead><tbody><tr v-for="iface in radio.interfaces" :key="iface.id"><td><strong>{{ iface.ssid || iface.id }}</strong><small>{{ iface.ifname || iface.id }}</small></td><td>{{ iface.mode === 'ap' ? 'Точка доступа' : iface.mode === 'sta' ? 'Клиент' : iface.mode }}</td><td>{{ encryptionNames[iface.encryption || 'none'] || iface.encryption }}</td><td>{{ networks(iface.network).join(', ') || 'Без привязки' }}</td><td><span class="gw-status" :class="radio.up && iface.disabled !== '1' ? 'good' : 'warn'">{{ iface.disabled === '1' ? 'Выключена' : radio.up ? 'Включена' : 'Не активна' }}</span></td></tr></tbody></table></div>
    </section>
  </section>
  <GatewayDialog v-if="editor && !plan" :title="'Настройки Wi-Fi · ' + editor.name" :wide="true" :compact="true" :busy="busy" @close="closeEditor">
    <form class="gw-form" @submit.prevent="review">
      <label class="gw-check"><input v-model="editor.disabled" type="checkbox" /> Выключить радиомодуль</label>
      <div class="gw-two"><label>Канал<select v-model="editor.channel"><option value="auto">Автоматически</option><option v-if="editor.channel !== 'auto' && !editor.frequencies.some((f: any) => String(f.channel) === editor.channel)" :value="editor.channel">{{ editor.channel }} (текущий)</option><option v-for="f in editor.frequencies" :key="f.channel" :value="String(f.channel)" :disabled="f.restricted">{{ f.channel }} · {{ frequency(f.mhz || f.frequency) }}{{ f.restricted ? ' · Недоступен' : '' }}</option></select></label><label>Ширина канала<select v-model="editor.htmode"><option v-for="m in [...new Set([editor.original.htmode || 'NOHT', ...editor.htmodes])]" :key="String(m)" :value="m">{{ modeName(String(m)) }}</option></select></label></div>
      <p class="gw-hint gw-mode-help">HT — Wi-Fi 4, VHT — Wi-Fi 5, HE — Wi-Fi 6, EHT — Wi-Fi 7. Более широкая полоса может повысить скорость, но занимает больше эфира; на загруженных 2,4 ГГц обычно удобнее 20 МГц.</p>
      <div class="gw-two"><label>Страна<select v-model="editor.country" aria-label="Страна"><option value="">По умолчанию</option><option value="00">00 · Всемирный регуляторный домен</option><option v-if="editor.country && editor.country !== '00' && !editor.countries?.some((row: any) => row.code === editor.country)" :value="editor.country" disabled>{{ editor.country }} · текущее значение</option><option v-for="country in editor.countries || []" :key="country.code" :value="country.code">{{ country.code }} · {{ countryName(country.code) }}</option></select></label><label>Мощность передатчика<select v-model="editor.txpower" aria-label="Мощность передатчика"><option value="">Автоматически</option><option v-if="editor.txpower && !editor.txpowers?.some((row: any) => String(row.dbm) === String(editor.txpower))" :value="editor.txpower" disabled>{{ editor.txpower }} dBm · текущее значение</option><option v-for="power in editor.txpowers || []" :key="power.dbm" :value="String(power.dbm)">{{ power.dbm }} dBm · {{ power.mw }} мВт</option></select><small>Только значения драйвера; ограничения выбранной страны применяет OpenWrt.</small></label></div>
      <h3>Сети на радиомодуле</h3>
      <details v-for="iface in editor.interfaces" :key="iface.id" class="gw-wifi-form" open><summary>{{ iface.ssid || iface.id }} · {{ iface.mode === 'ap' ? 'Точка доступа' : iface.mode === 'sta' ? 'Клиент' : iface.mode }}</summary><div class="gw-rule-fields">
        <label class="gw-check"><input v-model="iface.disabled" type="checkbox" /> Выключить эту сеть</label>
        <label>Имя сети (SSID)<input v-model="iface.ssid" required maxlength="32" /></label>
        <label>Защита<select v-model="iface.encryption"><option v-if="!encryptionNames[iface.original.encryption]" :value="iface.original.encryption">{{ iface.original.encryption }} (текущая)</option><option v-for="(name, value) in encryptionNames" :key="value" :value="value">{{ name }}</option></select></label>
        <label v-if="iface.encryption !== 'none' && encryptionNames[iface.encryption]">Пароль Wi-Fi<input v-model="iface.key" type="password" autocomplete="new-password" minlength="8" maxlength="64" :required="!iface.has_key" :placeholder="iface.has_key ? 'Оставьте пустым, чтобы сохранить текущий' : ''" /></label>
        <p v-if="iface.encryption === 'none'" class="gw-hint">Сеть будет открытой, сохранённый пароль будет удалён.</p>
        <fieldset class="gw-wifi-networks"><legend>Сетевые подключения</legend><label v-for="name in model.networks" :key="name" class="gw-check"><input v-model="iface.network" type="checkbox" :value="name" /> {{ name }}</label></fieldset>
        <div class="gw-two"><label class="gw-check"><input v-model="iface.hidden" type="checkbox" /> Скрыть SSID</label><label class="gw-check"><input v-model="iface.isolate" type="checkbox" /> Изолировать клиентов</label></div>
      </div></details>
      <p class="gw-hint">Применение временно отключит беспроводных клиентов. При потере доступа панель не подтвердит изменения, и роутер восстановит прежний Wi-Fi.</p>
      <p v-if="error" class="gw-error" role="alert">{{ error }}</p><div class="gw-actions"><button class="gw-primary" :disabled="busy">Проверить изменения</button><button type="button" :disabled="busy" @click="closeEditor">Отмена</button></div>
    </form>
  </GatewayDialog>
  <GatewayDialog v-if="plan" title="Проверка изменений Wi-Fi" :busy="busy" @close="discard"><ul class="gw-change-list"><li v-for="(change, i) in plan.summary" :key="i">{{ change }}</li></ul><p class="gw-hint">Откат при отсутствии подтверждения: {{ plan.rollback_seconds }} секунд.</p><p v-if="error" class="gw-error" role="alert">{{ error }}</p><div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="apply">Да, применить</button><button :disabled="busy" @click="discard">Назад</button></div></GatewayDialog>
  <GatewayDialog v-if="scanRadio" :title="'Обзор каналов · ' + scanRadio.name" :wide="true" :busy="scanning" @close="scanRadio = null">
    <header class="gw-section-header"><p class="gw-hint">{{ scanning ? 'Сканируем эфир…' : scanResult ? 'Последнее сканирование: ' + new Date(scanResult.scanned_at * 1000).toLocaleTimeString('ru-RU') : scanError ? 'Сканирование не выполнено' : 'Ожидание запуска сканирования' }}</p><button :disabled="scanning" @click="scan(scanRadio)">{{ scanning ? 'Сканирование…' : 'Сканировать снова' }}</button></header>
    <p class="gw-hint">Во время сканирования Wi-Fi может ненадолго замедлиться. Список показывает сети, видимые этому роутеру.</p><p v-if="scanError" class="gw-error" role="alert">{{ scanError }}</p>
    <template v-if="scanResult"><nav class="gw-tabs" aria-label="Результаты сканирования"><button :class="{ on: scanTab === 'channels' }" @click="scanTab = 'channels'">Каналы</button><button :class="{ on: scanTab === 'networks' }" @click="scanTab = 'networks'">Соседние сети ({{ scanNetworks.length }})</button></nav>
      <WirelessChannels v-if="scanTab === 'channels'" :data="{ ...scanResult, networks: scanNetworks }" :radio="scanRadio" />
      <template v-else><div class="gw-table-wrap"><table><thead><tr><th>Сеть</th><th>Канал</th><th>Частота</th><th>Сигнал</th><th>Защита</th></tr></thead><tbody><tr v-for="n in scanNetworks" :key="n.bssid + ':' + n.frequency"><td>{{ n.ssid || 'Скрытая сеть' }}<small>{{ n.bssid }}</small></td><td>{{ n.channel }}</td><td>{{ frequency(n.frequency) }}</td><td>{{ n.signal == null ? '—' : n.signal + ' dBm' }}</td><td>{{ protection(n) }}</td></tr></tbody></table></div><p v-if="!scanNetworks.length" class="gw-hint">Соседние сети не найдены.</p></template>
    </template>
  </GatewayDialog>
</template>
<style>
.gw-radio{padding:22px 0;border-top:1px solid var(--border,#29374b)}.gw-radio h3{font-size:15px}.gw-wifi-form{border-bottom:1px solid var(--border,#29374b)}.gw-wifi-form summary{padding:14px 0;cursor:pointer;font-weight:600;font-size:14px}.gw-wireless-advanced{margin-top:14px}.gw-wifi-networks{border:0;padding:0;margin:0;display:flex;gap:16px;flex-wrap:wrap}.gw-wifi-networks legend{font-size:13px;margin-bottom:5px}.gw-channel-load{display:flex;gap:8px;align-items:center}.gw-channel-load meter{width:72px;accent-color:var(--accent,#63a8f5)}
.gw-dialog-compact .gw-form{gap:10px}.gw-dialog-compact .gw-form label{gap:5px;font-size:12px}.gw-dialog-compact .gw-form .gw-two{gap:10px}.gw-dialog-compact .gw-form h3{font-size:14px;margin:4px 0}.gw-dialog-compact .gw-wifi-form summary{padding:8px 0;font-size:12px}.gw-dialog-compact .gw-form p.gw-hint,.gw-dialog-compact .gw-form small{font-size:11px;line-height:1.4}.gw-dialog-compact .gw-form .gw-rule-fields{gap:8px}.gw-dialog-compact .gw-form .gw-actions{margin-top:8px}.gw-dialog-compact .gw-mode-help{margin:0}
</style>
