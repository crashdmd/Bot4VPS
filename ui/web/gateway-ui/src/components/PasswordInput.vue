<script setup lang="ts">
import { ref, watch } from 'vue';

defineOptions({ inheritAttrs: false });
const value = defineModel<string>({ required: true });
const visible = ref(false);
watch(value, text => { if (!text) visible.value = false; });
</script>

<template>
  <span class="gw-password">
    <input v-bind="$attrs" v-model="value" :type="visible ? 'text' : 'password'" spellcheck="false" autocapitalize="off" />
    <button type="button" class="gw-password-eye" :aria-label="visible ? 'Скрыть введённое' : 'Показать введённое'"
      :title="visible ? 'Скрыть введённое' : 'Показать введённое'" :aria-pressed="visible" @click.prevent="visible = !visible">👁</button>
  </span>
</template>

<style>
.gw-password{display:flex;position:relative;min-width:0}
.gw-shell .gw-password input{padding-right:44px}
.gw-shell .gw-password .gw-password-eye{position:absolute;right:1px;top:1px;bottom:1px;width:40px;padding:0;border:0;background:transparent}
.gw-password-eye[aria-pressed="true"]{color:var(--gw-accent)}
</style>
