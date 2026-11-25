<script setup lang="ts">
import GatewayDialog from '../GatewayDialog.vue';
import type { TlsTrustChange } from '../types/gateway';
defineProps<{change:TlsTrustChange;busy:boolean}>();
const emit=defineEmits<{apply:[];cancel:[]}>();
</script>
<template>
<GatewayDialog title="Изменение доверия HTTPS" :busy="busy" @close="emit('cancel')"><div class="gw-pin-detail"><p>Изменяется сохранённый отпечаток сертификата API.</p><p>Прежний: <code>{{ change.previous }}</code></p><p>Новый: <code>{{ change.next || 'Проверка стандартной цепочки сертификатов' }}</code></p><p>Подтвердите изменение после проверки сертификата роутера.</p></div><div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="emit('apply')">Да, принять изменение</button><button :disabled="busy" @click="emit('cancel')">Отмена</button></div></GatewayDialog>
</template>
<style>.gw-pin-detail code{overflow-wrap:anywhere;white-space:normal}</style>
