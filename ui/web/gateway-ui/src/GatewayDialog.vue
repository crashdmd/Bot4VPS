<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue';
const props = defineProps<{ title: string; busy?: boolean; wide?: boolean; compact?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLElement>();
let previous: HTMLElement | null = null;
function close() { if (!props.busy) emit('close'); }
function keys(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); close(); }
  if (event.key !== 'Tab' || !dialog.value) return;
  const items = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')].filter(el => el.getClientRects().length);
  const first = items[0], last = items[items.length - 1];
  if (!first) { event.preventDefault(); dialog.value.focus(); return; }
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !dialog.value.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
}
onMounted(async () => {
  previous = document.activeElement as HTMLElement;
  document.addEventListener('keydown', keys, true);
  await nextTick(); dialog.value?.focus();
});
onUnmounted(() => { document.removeEventListener('keydown', keys, true); if (previous?.isConnected) previous.focus(); });
</script>
<template>
  <Teleport to="body">
    <div class="gw-shell gw-dialog-overlay">
      <section ref="dialog" class="gw-panel gw-dialog" :class="{ 'gw-dialog-wide': wide, 'gw-dialog-compact': compact }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
        <header class="gw-dialog-header"><h2>{{ title }}</h2><button type="button" aria-label="Закрыть диалог" :disabled="busy" @click="close">×</button></header>
        <slot />
      </section>
    </div>
  </Teleport>
</template>
<style>
.gw-shell.gw-dialog-overlay{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:#06111ecc;padding:24px;z-index:1100;max-width:none;margin:0;backdrop-filter:blur(3px)}
.gw-dialog{width:min(620px,100%);max-height:calc(100dvh - 48px);overflow:auto;outline:none;box-shadow:0 20px 70px #0006}.gw-shell .gw-dialog{background:var(--bg-base,#101927)}.gw-dialog-wide{width:min(880px,100%)}
.gw-dialog-header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px}.gw-dialog-header h2{font-size:21px;margin:0}.gw-dialog-header button{font-size:23px;line-height:1;padding:6px 11px}.gw-dialog .gw-form{max-width:none}.gw-dialog .gw-actions{margin-top:22px}.gw-dialog p{line-height:1.6}
@media(max-width:600px){.gw-shell.gw-dialog-overlay{padding:12px}.gw-shell .gw-dialog{max-height:calc(100dvh - 24px);padding:18px}}
.gw-shell .gw-dialog-compact{width:min(720px,100%);padding:16px}.gw-dialog-compact>.gw-dialog-header{margin-bottom:10px}.gw-dialog-compact>.gw-dialog-header h2{font-size:18px}.gw-dialog-compact>.gw-dialog-header button{font-size:20px;padding:4px 8px}.gw-dialog-compact>.gw-hint{font-size:12px;line-height:1.45;margin:8px 0}.gw-dialog-compact .gw-reserve-settings .gw-actions select{width:auto;flex:1;min-width:0}@media(max-width:600px){.gw-shell .gw-dialog-compact{padding:14px}}
</style>
