<script setup lang="ts">
import { computed } from 'vue';
import { serviceProjects } from './serviceProjects';
const props = defineProps<{ id: string; compact?:boolean; help?:boolean }>();
const emit = defineEmits<{ help: [] }>();
const project = computed(() => serviceProjects.find(row => row.id === props.id));
const owner = computed(() => project.value?.repository.split('/')[0]);
</script>
<template>
  <div v-if="project" class="gw-project-info" :class="{compact}">
    <p :title="project.description">{{ project.description }}</p>
    <div class="gw-project-links">
      <a :aria-label="'Автор проекта: ' + project.author" :href="'https://github.com/' + owner" target="_blank" rel="noopener noreferrer">{{ project.author }}</a><span aria-hidden="true">·</span>
      <a :href="'https://github.com/' + project.repository" :title="project.repository" target="_blank" rel="noopener noreferrer">GitHub ↗</a><button v-if="help" type="button" @click="emit('help')">Помощь</button>
    </div>
  </div>
</template>
<style>
.gw-project-info{margin-top:3px;min-width:0}.gw-project-info p{margin:0 0 4px;font-size:12px;line-height:1.55;color:var(--text-muted,#98a8bd)}.gw-project-links{display:flex;flex-wrap:wrap;align-items:center;gap:5px 7px;font-size:11px;line-height:1.6}.gw-project-links span{color:var(--text-muted,#98a8bd)}.gw-shell .gw-project-links a{color:var(--gw-accent,#5299e9);text-decoration:none;padding:0;background:none;border:0;overflow-wrap:anywhere}.gw-project-links a:hover{text-decoration:underline}
.gw-project-info.compact p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}.gw-project-info.compact .gw-project-links{font-size:10px;line-height:1.4}</style>

<style>.gw-shell .gw-project-links button{padding:0;border:0;background:none;font:inherit;line-height:inherit;color:var(--gw-accent,#5299e9);cursor:pointer}.gw-project-links button:hover{text-decoration:underline}</style>

<style>.gw-project-links{flex-wrap:nowrap;white-space:nowrap;width:max-content}</style>
