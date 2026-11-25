<script setup lang="ts">
import GatewayDialog from '../GatewayDialog.vue';
import type { IntegrationUpdatePlan } from '../types/gateway';
defineProps<{plan:IntegrationUpdatePlan;busy:boolean;error?:string}>();
const emit=defineEmits<{apply:[];cancel:[]}>();
</script>
<template>
<GatewayDialog :title="'Обновление интеграции · '+plan.name" :compact="true" :busy="busy" @close="emit('cancel')"><p v-if="error" class="gw-error" role="alert">{{ error }}</p><p v-for="warning in plan.warnings" :key="warning" class="gw-notice">{{ warning }}</p><details><summary>Компоненты для обновления ({{ plan.files.length }})</summary><ul><li v-for="path in plan.files" :key="path">{{ path }}</li></ul></details><div class="gw-actions"><button class="gw-primary" :disabled="busy" @click="emit('apply')">Да, обновить интеграцию</button><button :disabled="busy" @click="emit('cancel')">Отмена</button></div></GatewayDialog>
</template>
