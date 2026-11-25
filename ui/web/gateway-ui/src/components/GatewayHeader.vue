<script setup lang="ts">
import type { Gateway } from '../types/gateway';
defineProps<{node:Gateway;busy:boolean}>();
const emit=defineEmits<{console:[]}>();
</script>
<template>
<header class="gw-header"><div><span class="gw-eyebrow">OPENWRT {{ node.monitor.board?.release?.version }}</span><h2 class="gw-title-with-icon"><span class="gw-router-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20"><rect x="3" y="11" width="18" height="9" rx="2"/><path d="M7 11V5m10 6V5M5 6a10 10 0 0 1 14 0M8 8a6 6 0 0 1 8 0M7 16h.01M11 16h.01"/></svg></span>{{ node.name }}</h2><p>{{ node.monitor.board?.model || node.host }} · {{ node.host }}</p></div><div class="gw-actions"><button aria-label="Открыть консоль шлюза" :disabled="busy" @click="emit('console')">Консоль</button><a :href="node.luci_url" target="_blank" rel="noopener noreferrer">LuCI ↗</a></div></header>
</template>
<style>.gw-title-with-icon{display:flex;align-items:center;gap:10px}.gw-title-with-icon .gw-router-icon{width:30px;height:30px;flex:0 0 auto}</style>
