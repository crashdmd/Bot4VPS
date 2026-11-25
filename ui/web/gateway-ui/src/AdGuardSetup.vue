<script setup lang="ts">
import { onMounted, ref } from 'vue';
import type { Bridge } from './main';
import GatewayDialog from './GatewayDialog.vue';
import ProjectInfo from './ProjectInfo.vue';
const props = defineProps<{ node: any; bridge: Bridge }>();
const emit = defineEmits<{ close: []; install: []; start: [] }>();
const guide = ref<any>(null), error = ref('');
const url = (port: number) => 'http://' + (props.node.host.includes(':') ? '[' + props.node.host + ']' : props.node.host) + ':' + port + '/';
onMounted(async () => { try { guide.value = await props.bridge.request('/api/gateways/' + encodeURIComponent(props.node.id) + '/adguard'); } catch (e: any) { error.value = e.message; } });
</script>
<template>
  <GatewayDialog title="AdGuard Home: установка и настройка DNS" :wide="true" @close="emit('close')">
    <ProjectInfo id="adguardhome" />
    <p v-if="error" class="gw-error">{{ error }}</p><p v-if="!guide && !error">Проверяем роутер…</p>
    <template v-if="guide">
      <div class="gw-notice"><strong>{{ guide.installed ? 'AdGuard Home установлен' : 'Установка из официального GitHub-релиза' }}</strong><p>Свободное место: {{ guide.free_bytes == null ? 'Не определено' : (guide.free_bytes / 1048576).toFixed(0) + ' МБ' }}. Бинарный файл и журнал запросов требуют места; для небольшого flash рекомендуется внешнее хранилище.</p><p>Занятые порты: {{ guide.occupied_ports.filter((p: any) => [53,54,80,443,3000,5353,8080].includes(p.port)).map((p: any) => p.port + '/' + p.protocol).join(', ') || 'Не обнаружены' }}.</p></div>
      <p v-if="guide.setup_port_busy && !guide.configured" class="gw-error">Порт 3000 занят. Перед первым запуском освободите его через консоль или настройки службы.</p>
      <ol class="gw-setup-steps"><li v-for="(step, i) in guide.steps" :key="i">{{ step }}</li></ol>
      <p v-if="guide.dns_dependencies.length" class="gw-notice">Найдены зависимости DNS: {{ guide.dns_dependencies.join('; ') }}. До их изменения остановка и удаление сервиса запрещены.</p>
      <div class="gw-actions"><button v-if="!guide.installed" class="gw-primary" @click="emit('install')">Выбрать версию и установить</button><button v-else-if="!node.monitor.services?.some((s: any) => s.id === 'adguardhome' && s.running)" :disabled="guide.setup_port_busy && !guide.configured" class="gw-primary" @click="emit('start')">Запустить сервис</button><a v-if="guide.installed" :href="url(guide.web_port)" target="_blank" rel="noopener noreferrer">{{ guide.configured ? 'Открыть AdGuard Home' : 'Открыть мастер на порту 3000' }} ↗</a></div>
      <p class="gw-hint">Официальные инструкции: <a v-for="source in guide.sources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.name }} ↗ </a></p>
    </template>
  </GatewayDialog>
</template>
<style>.gw-setup-steps{padding-left:22px;line-height:1.7}.gw-setup-steps li{padding-left:6px;margin:14px 0}.gw-notice p{margin:8px 0 0}</style>
